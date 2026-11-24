//! Descubrimiento de pares en la LAN por multicast (ADR-002, `discovery=multicast`).
//!
//! ## Por qué multicast y no DHT
//!
//! En una LAN no hace falta Kademlia: hace falta **saber quién está**. Un
//! datagrama a un grupo multicast llega a todos los nodos de la subred sin
//! configuración, sin semillas y sin servidor. La DHT solo tiene sentido
//! cuando se sale de la LAN, y ese es otro problema (y otro ADR).
//!
//! ## Lo que se anuncia y lo que NO
//!
//! El anuncio lleva lo mínimo para poder conectar **con seguridad**:
//! - la versión del protocolo de anuncio
//! - el papel del nodo (hub/store/edge)
//! - la dirección y el puerto QUIC donde escucha
//! - **la huella sha256 de su certificado**
//!
//! La huella es la pieza clave: sin ella, descubrir un nodo sería descubrir un
//! desconocido al que hay que aceptar a ciegas. Con ella, el que descubre puede
//! fijar el pin y hablar con identidad verificada. **El descubrimiento no es una
//! puerta trasera a la seguridad: es lo que hace usable el pin.**
//!
//! ## Lo que este módulo NO hace
//!
//! - No se anuncia a sí mismo como nodo de confianza: solo dice "existo aquí".
//! - No acepta conexiones: solo informa de dónde conectar.
//! - No verifica el anuncio (cualquiera puede emitir uno) → por eso lleva
//!   huella y el receptor debe **fijarla explícitamente** o descartar el par.

use std::io;
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4};

use lumen::datagram::DatagramTransport;
use lumen::frame;
use lumen::transport::Transport;

/// Grupo multicast por defecto (rango administrado localmente, 239.x).
pub const GRUPO_POR_DEFECTO: &str = "239.255.77.77:9444";

/// Versión del formato de anuncio. Un nodo con otra versión se ignora.
pub const VERSION_ANUNCIO: u8 = 1;

/// Tipo de frame que llevan los anuncios (dentro del rango reservado LUMEN).
/// Se usa `TYPE_DISCOVER` (0x08), que existe en `frame.rs` pero no tenía
/// emisor hasta ahora.
pub const TIPO_ANUNCIO: u8 = frame::TYPE_DISCOVER;

/// Lo que un nodo anuncia de sí mismo.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Anuncio {
    pub version: u8,
    /// Papel: "hub" | "store" | "edge".
    pub role: String,
    /// Dónde escucha QUIC (ip:puerto).
    pub quic: SocketAddr,
    /// Huella sha256 (hex) de su certificado, para poder fijar el pin.
    pub huella: String,
}

impl Anuncio {
    /// Serializa a un payload compacto y legible: `v1|hub|ip:port|hex64`.
    ///
    /// Texto y no binario a propósito: un anuncio es pequeño, se inspecciona
    /// con `tcpdump` o un log, y el coste de parseo es irrelevante. Si algún
    /// día pesa, se cambia a binario con la versión por delante.
    pub fn a_payload(&self) -> Vec<u8> {
        format!(
            "v{}|{}|{}|{}",
            self.version, self.role, self.quic, self.huella
        )
        .into_bytes()
    }

    /// Parsea un payload. `None` si no es un anuncio válido de esta versión.
    pub fn desde_payload(payload: &[u8]) -> Option<Self> {
        let texto = std::str::from_utf8(payload).ok()?;
        let campos: Vec<&str> = texto.trim().split('|').collect();
        if campos.len() != 4 {
            return None;
        }
        let version = campos[0].strip_prefix('v')?.parse::<u8>().ok()?;
        if version != VERSION_ANUNCIO {
            return None;
        }
        let role = campos[1].to_string();
        if !matches!(role.as_str(), "hub" | "store" | "edge") {
            return None;
        }
        let quic: SocketAddr = campos[2].parse().ok()?;
        let huella = campos[3].to_string();
        // La huella debe ser sha256 hex: si no, el anuncio no sirve para fijar
        // pin y aceptarlo daría una falsa sensación de verificación.
        if huella.chars().filter(|c| c.is_ascii_hexdigit()).count() != 64 {
            return None;
        }
        Some(Self {
            version,
            role,
            quic,
            huella,
        })
    }
}

/// Emisor/receptor de anuncios sobre un socket UDP multicast.
pub struct Descubrimiento {
    transporte: DatagramTransport,
    grupo: SocketAddr,
}

impl Descubrimiento {
    /// Se une al grupo en la interfaz indicada y queda listo para anunciar y
    /// escuchar.
    ///
    /// `interfaz` es la IP local de la tarjeta (p.ej. `192.168.1.13`). En
    /// Windows es obligatoria: sin ella el join puede irse a la interfaz
    /// equivocada.
    pub fn unirse(grupo: &str, interfaz: &str) -> io::Result<Self> {
        let grupo: SocketAddr = grupo
            .parse()
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, format!("grupo {grupo}: {e}")))?;
        // ⚠️ Windows (error 10049): NO se puede hacer bind a la dirección
        // multicast. Hay que hacer bind a `0.0.0.0:<puerto>` y DESPUÉS unirse
        // al grupo. En Linux el bind directo al grupo sí funciona, así que este
        // camino vale en las dos plataformas — verificado en Windows 24-nov-2026.
        let puerto = grupo.port();
        let bind_addr = format!("0.0.0.0:{puerto}");
        // `bind_reutilizable`: varios nodos en la misma máquina comparten
        // grupo y puerto. Sin SO_REUSEADDR el segundo da `10048 address
        // already in use` en Windows (verificado 24-nov-2026).
        let transporte = DatagramTransport::bind_reutilizable(&bind_addr)?;
        let iface = format!("{interfaz}:0");
        transporte
            .join_multicast(&grupo.to_string(), &iface)
            .map_err(|e| {
                io::Error::new(
                    e.kind(),
                    format!("join multicast a {grupo} por {interfaz}: {e}"),
                )
            })?;
        // TTL 1: no salir de la subred. Un anuncio no debe cruzar un router.
        transporte.set_multicast_ttl(1)?;
        Ok(Self { transporte, grupo })
    }

    /// Emite un anuncio al grupo.
    pub fn anunciar(&self, anuncio: &Anuncio) -> io::Result<usize> {
        let marco = lumen::datagram::build_dgram(
            TIPO_ANUNCIO,
            0,
            &anuncio.a_payload(),
        );
        self.transporte.send_frame_to(&marco, self.grupo)
    }

    /// Lee un anuncio si hay uno esperando (no bloquea).
    ///
    /// Devuelve también la IP de origen, que es lo que se usa para decidir si
    /// el anuncio viene de la propia máquina (y descartarlo).
    pub fn recibir(&mut self) -> io::Result<Option<(Anuncio, SocketAddr)>> {
        let Some((bytes, origen)) = self.transporte.recv_frame()? else {
            return Ok(None);
        };
        match frame::parse(bytes) {
            frame::ParseResult::Complete { frame, .. } => {
                if frame.frame_type != TIPO_ANUNCIO {
                    return Ok(None);
                }
                Ok(Anuncio::desde_payload(frame.payload).map(|a| (a, origen)))
            }
            _ => Ok(None),
        }
    }

    /// Dirección local del socket (para diagnóstico).
    pub fn local_addr(&self) -> io::Result<SocketAddr> {
        self.transporte.local_addr()
    }
}

/// ¿El anuncio es nuestro propio anuncio?
///
/// ⚠️ Se compara por **huella de certificado**, no por IP.
///
/// Comparar por IP parecía razonable y era un error: dos nodos en la misma
/// máquina (puertos distintos) comparten IP y se descartarían mutuamente para
/// siempre; y tras un NAT varios nodos pueden compartir IP pública. La huella
/// del certificado es única por nodo, así que identifica al emisor de verdad.
///
/// Verificado 24-nov-2026: dos nodos en `192.168.1.17` con el filtro por IP no
/// se veían; por huella se ven correctamente.
pub fn es_propio(anuncio: &Anuncio, mi_huella: &str) -> bool {
    anuncio.huella.eq_ignore_ascii_case(mi_huella)
}

/// Construye la dirección de interfaz válida o explica por qué no.
pub fn interfaz_v4(ip: &str) -> Option<Ipv4Addr> {
    ip.parse::<Ipv4Addr>().ok().filter(|a| !a.is_unspecified())
}

/// Grupo como SocketAddrV4 (para validaciones).
pub fn grupo_v4(grupo: &str) -> Option<SocketAddrV4> {
    grupo
        .parse::<SocketAddrV4>()
        .ok()
        .filter(|g| g.ip().is_multicast())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn anuncio_de_prueba() -> Anuncio {
        Anuncio {
            version: VERSION_ANUNCIO,
            role: "hub".into(),
            quic: "192.168.1.13:9443".parse().unwrap(),
            huella: "a".repeat(64),
        }
    }

    #[test]
    fn anuncio_ida_y_vuelta() {
        let a = anuncio_de_prueba();
        let p = a.a_payload();
        let b = Anuncio::desde_payload(&p).expect("debe parsear");
        assert_eq!(a, b);
    }

    #[test]
    fn anuncio_con_version_distinta_se_ignora() {
        let p = b"v9|hub|192.168.1.13:9443|".to_vec();
        let mut p = p;
        p.extend("a".repeat(64).bytes());
        assert!(Anuncio::desde_payload(&p).is_none());
    }

    #[test]
    fn anuncio_sin_huella_valida_se_ignora() {
        // Huella corta: no sirve para fijar pin, así que no es un anuncio útil.
        let p = b"v1|hub|192.168.1.13:9443|abc";
        assert!(Anuncio::desde_payload(p).is_none());
    }

    #[test]
    fn anuncio_con_rol_desconocido_se_ignora() {
        let mut p = b"v1|pirata|192.168.1.13:9443|".to_vec();
        p.extend("a".repeat(64).bytes());
        assert!(Anuncio::desde_payload(&p).is_none());
    }

    #[test]
    fn anuncio_con_direccion_mala_se_ignora() {
        let mut p = b"v1|hub|no-es-una-ip|".to_vec();
        p.extend("a".repeat(64).bytes());
        assert!(Anuncio::desde_payload(&p).is_none());
    }

    #[test]
    fn anuncio_con_campos_de_mas_se_ignora() {
        let mut p = b"v1|hub|192.168.1.13:9443|x|y|".to_vec();
        p.extend("a".repeat(64).bytes());
        assert!(Anuncio::desde_payload(&p).is_none());
    }

    #[test]
    fn anuncio_vacio_se_ignora() {
        assert!(Anuncio::desde_payload(b"").is_none());
        assert!(Anuncio::desde_payload(b"basura").is_none());
    }

    #[test]
    fn se_reconoce_el_anuncio_propio_por_huella() {
        let mio = "a".repeat(64);
        let mut a = anuncio_de_prueba();
        a.huella = mio.clone();
        assert!(es_propio(&a, &mio));

        // Otro nodo en la MISMA IP (mismo host, otro puerto) NO es propio:
        // es un par legítimo y debe verse.
        let mut otro = anuncio_de_prueba();
        otro.quic = "192.168.1.13:9444".parse().unwrap();
        otro.huella = "b".repeat(64);
        assert!(
            !es_propio(&otro, &mio),
            "dos nodos en la misma IP son pares distintos y deben verse"
        );
    }

    #[test]
    fn la_huella_se_compara_sin_importar_mayusculas() {
        let mut a = anuncio_de_prueba();
        a.huella = "AB".repeat(32);
        assert!(es_propio(&a, &"ab".repeat(32)));
    }

    #[test]
    fn grupo_valido_es_multicast() {
        assert!(grupo_v4("239.255.77.77:9444").is_some());
        // Una IP normal NO es un grupo multicast: unir ese grupo fallaría.
        assert!(grupo_v4("192.168.1.13:9444").is_none());
    }

    #[test]
    fn interfaz_unspecified_se_rechaza() {
        assert!(interfaz_v4("0.0.0.0").is_none());
        assert!(interfaz_v4("192.168.1.13").is_some());
        assert!(interfaz_v4("basura").is_none());
    }

    /// El anuncio debe caber en un datagrama (sin fragmentar en la práctica).
    #[test]
    fn el_anuncio_cabe_en_un_datagrama() {
        let p = anuncio_de_prueba().a_payload();
        assert!(
            p.len() < 200,
            "un anuncio debe ser pequeño, mide {} bytes",
            p.len()
        );
    }
}
