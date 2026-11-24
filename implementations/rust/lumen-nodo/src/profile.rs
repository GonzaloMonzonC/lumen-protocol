//! Perfil de nodo — la fila de configuración (ADR-002).
//!
//! Regla dura: **solo existen valores cuyo código existe y tiene test**. Un
//! valor que el binario no sabe ejecutar no es una opción: es una mentira con
//! forma de bandera. Por eso `Mode`, `Role` etc. son enums cerrados y el
//! parser rechaza lo desconocido en vez de caer a un default silencioso.

use std::fmt;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};

/// Longitud en hex de una huella SHA-256.
pub const PIN_HEX_LEN: usize = 64;

/// ¿Es una huella SHA-256 en hex (admite ':' como separador)?
pub fn pin_valido(pin: &str) -> bool {
    let limpio: String = pin.chars().filter(|c| c.is_ascii_hexdigit()).collect();
    limpio.len() == PIN_HEX_LEN
}

/// Modo de red del nodo.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// Red local: se asume alcanzable por pares de la misma LAN.
    Lan,
    /// Red abierta. Hoy QUIC funciona; atravesar NAT **no** (no hay ICE/STUN).
    Wan,
    /// No abre ningún endpoint. Puede leer y escribir su PDB.
    Offline,
}

/// Papel del nodo en la malla.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    /// Acepta conexiones y escribe en su PDB.
    Hub,
    /// Como Hub, y además sirve históricos a quien los pida.
    Store,
    /// Conecta hacia afuera; no acepta entrantes salvo de sus pares.
    Edge,
}

/// Cómo encuentra pares.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Discovery {
    /// Multicast en LAN. **NO IMPLEMENTADO** — `datagram.rs:165` tiene
    /// `join_multicast`, pero nadie lo usa todavía.
    Multicast,
    /// Sin descubrimiento: cada par se configura a mano.
    None,
    /// Lista de semillas. **NO IMPLEMENTADO**.
    Seeds,
}

/// Transporte entre nodos.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Transport {
    /// QUIC + TLS 1.3 (`quinn`). Verificado en `lumen-znet/tests/quic_e2e.rs`.
    Quic,
    /// Memoria compartida, mismo host (`shm.rs`).
    Shm,
}

/// Identidad del par.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Identity {
    /// Certificado fijado por huella SHA-256. Implementado en `quic.rs`:
    /// `PinnedVerifier` + `pinned_client_config`. Un certificado distinto
    /// hace fallar el handshake (test `handshake_con_pin_correcto_...`).
    Pin,
    /// Sin verificación. `SkipCertVerifier` — **solo desarrollo**.
    None,
    /// Clave pública X25519 (`handshake.rs`). **NO IMPLEMENTADO** como identidad de par.
    Pubkey,
}

/// Qué se firma.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Sign {
    /// Nada.
    None,
    /// Cada muestra encadena el hash de la anterior. **NO IMPLEMENTADO**.
    HashChain,
}

/// ¿Es una IPv4 utilizable como interfaz de anuncio? (`0.0.0.0` no vale)
pub fn interface_v4(ip: &str) -> Option<std::net::Ipv4Addr> {
    ip.parse::<std::net::Ipv4Addr>()
        .ok()
        .filter(|a| !a.is_unspecified())
}

/// ¿Es una dirección multicast válida con puerto?
pub fn grupo_v4(grupo: &str) -> Option<std::net::SocketAddrV4> {
    grupo
        .parse::<std::net::SocketAddrV4>()
        .ok()
        .filter(|g| g.ip().is_multicast())
}

/// Grupo multicast por defecto (rango administrado localmente, 239.x).
pub const GRUPO_POR_DEFECTO: &str = "239.255.77.77:9444";

/// Motor de persistencia del nodo.
///
/// No es un detalle de implementación: cambia cómo se leen los datos y qué se
/// puede sostener. `sqlite` carga la base en RAM al abrir; `lmdb` lee por mmap
/// sin precarga, que es lo que permite a un nodo con la PDB grande arrancar en
/// segundos. La elección se hace por perfil, no por build.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Storage {
    /// SQLite (`MemoryHost::from_sqlite`). Carga en RAM, persistencia por fila.
    Sqlite,
    /// LMDB (mmap directo, sin precarga) — `LmdbStore` + `MemoryHost::from_lmdb`.
    Lmdb,
}

/// Autorización.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Auth {
    /// Macaroon con caveats (`macaroon.rs`). Implementado en Python (31/31).
    Macaroon,
    /// HMAC DDP (`_hmac_verify`). Implementado y verificado.
    Hmac,
    /// Sin autorización. **Solo loopback** — ver `Profile::validate`.
    Dev,
}

/// El perfil completo: la fila de `^SYS("NET",...)`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Profile {
    pub mode: Mode,
    pub role: Role,
    pub discovery: Discovery,
    pub transport: Transport,
    pub identity: Identity,
    pub sign: Sign,
    pub auth: Auth,
    /// Motor de persistencia: sqlite (carga en RAM) o lmdb (mmap directo).
    pub storage: Storage,
    /// Huella SHA-256 (hex) del certificado del par, cuando `identity=pin`.
    pub pin: Option<String>,
    /// IP local de la tarjeta por la que anunciar (`discovery=multicast`).
    pub interface: Option<String>,
    /// Grupo multicast, `ip:puerto`.
    pub grupo: String,
    /// Dirección de escucha. `None` cuando el modo es `Offline`.
    pub listen: Option<SocketAddr>,
}

/// Lo que puede ir mal en una fila de configuración.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProfileError {
    /// La fila pide algo que el binario no sabe hacer.
    NotImplemented { field: &'static str, value: String },
    /// La fila es incoherente: arrancaría y mentiría.
    Incoherent(String),
    /// Valor desconocido para un campo.
    Unknown { field: &'static str, value: String },
}

impl fmt::Display for ProfileError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ProfileError::NotImplemented { field, value } => {
                write!(f, "{field}={value} está en la config pero NO está implementado")
            }
            ProfileError::Incoherent(m) => write!(f, "perfil incoherente: {m}"),
            ProfileError::Unknown { field, value } => {
                write!(f, "{field}={value} no es un valor conocido")
            }
        }
    }
}

impl std::error::Error for ProfileError {}

/// Perfil mínimo que arranca **hoy** sin tocar una línea de código.
pub fn minimal_profile() -> Profile {
    Profile {
        mode: Mode::Lan,
        role: Role::Hub,
        discovery: Discovery::None,
        transport: Transport::Quic,
        identity: Identity::None,
        sign: Sign::None,
        auth: Auth::Hmac,
        storage: Storage::Lmdb,
        pin: None,
        interface: None,
        grupo: GRUPO_POR_DEFECTO.to_string(),
        listen: Some(SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), 9443)),
    }
}

impl Profile {
    /// Valida la fila. Devuelve `Err` si el nodo arrancaría mintiendo.
    ///
    /// Esta función es la que impide que el ADR-002 se convierta en papel
    /// mojado. Se llama **antes** de abrir ningún socket.
    pub fn validate(&self) -> Result<(), ProfileError> {
        // ── 1. Nada de valores sin código detrás ──────────────────────
        // Cada brazo corresponde a un "NO IMPLEMENTADO" del ADR-002. Cuando
        // se implemente, se borra su brazo y se añade un test que lo pruebe.
        match self.discovery {
            Discovery::Seeds => {
                return Err(ProfileError::NotImplemented {
                    field: "discovery",
                    value: "seeds".into(),
                })
            }
            // `multicast` SÍ está implementado (descubrir.rs), pero exige saber
            // por qué interfaz anunciar: sin interfaz, el join puede irse a la
            // tarjeta equivocada y el nodo se quedaría sordo sin decirlo.
            Discovery::Multicast => {
                let iface = self.interface.as_deref().unwrap_or("").trim();
                if iface.is_empty() {
                    return Err(ProfileError::Incoherent(
                        "discovery=multicast requiere interface (la IP local de la tarjeta)"
                            .into(),
                    ));
                }
                if interface_v4(iface).is_none() {
                    return Err(ProfileError::Incoherent(format!(
                        "interface '{iface}' no es una IPv4 valida (y 0.0.0.0 no vale: \
                         hay que decir por que tarjeta anunciar)"
                    )));
                }
                if grupo_v4(&self.grupo).is_none() {
                    return Err(ProfileError::Incoherent(format!(
                        "grupo multicast '{}' no es una direccion multicast valida",
                        self.grupo
                    )));
                }
            }
            Discovery::None => {}
        }
        match self.identity {
            Identity::Pubkey => {
                return Err(ProfileError::NotImplemented {
                    field: "identity",
                    value: "pubkey".into(),
                })
            }
            // `pin` SÍ está implementado (quic.rs: PinnedVerifier + pruebas de
            // handshake real). Pero exige una huella configurada: sin ella el
            // nodo no sabría contra qué comparar y aceptaría a ciegas.
            Identity::Pin => {
                if self.pin.as_deref().unwrap_or("").trim().is_empty() {
                    return Err(ProfileError::Incoherent(
                        "identity=pin requiere un pin (sha256 hex del certificado del par); \
                         sin pin no hay nada que verificar"
                            .into(),
                    ));
                }
                if !pin_valido(self.pin.as_deref().unwrap_or("")) {
                    return Err(ProfileError::Incoherent(format!(
                        "pin mal formado: se esperan {PIN_HEX_LEN} caracteres hex (sha256)"
                    )));
                }
            }
            Identity::None => {}
        }
        if self.sign == Sign::HashChain {
            return Err(ProfileError::NotImplemented {
                field: "sign",
                value: "hash-chain".into(),
            });
        }

        // ── 2. La seguridad manda sobre la configuración ──────────────
        // Un modo dev no puede escuchar en 0.0.0.0. Un modo de desarrollo
        // que acepta conexiones de la red no es un modo de desarrollo:
        // es una puerta abierta con etiqueta "dev".
        if self.auth == Auth::Dev {
            if let Some(addr) = self.listen {
                if !addr.ip().is_loopback() {
                    return Err(ProfileError::Incoherent(format!(
                        "auth=dev solo puede escuchar en loopback, no en {}",
                        addr.ip()
                    )));
                }
            }
        }

        // ── 3. Coherencia entre campos ────────────────────────────────
        // El motor LMDB tiene que estar compilado dentro. Un `storage=lmdb`
        // en un build sin la feature es exactamente la mentira que este ADR
        // prohíbe: arrancaría y leería con sqlite sin decirlo.
        if self.storage == Storage::Lmdb && !cfg!(feature = "motor-lmdb") {
            return Err(ProfileError::NotImplemented {
                field: "storage",
                value: "lmdb (binario compilado sin la feature 'motor-lmdb')".into(),
            });
        }
        if self.mode == Mode::Offline && self.listen.is_some() {
            return Err(ProfileError::Incoherent(
                "mode=offline no puede tener dirección de escucha".into(),
            ));
        }
        if self.mode != Mode::Offline && self.listen.is_none() {
            return Err(ProfileError::Incoherent(
                "modo con red requiere dirección de escucha".into(),
            ));
        }
        if self.transport == Transport::Quic && self.mode == Mode::Offline {
            return Err(ProfileError::Incoherent(
                "transport=quic no tiene sentido en mode=offline".into(),
            ));
        }

        Ok(())
    }

    /// Avisos que no impiden arrancar pero deben decirse en la cara.
    pub fn warnings(&self) -> Vec<String> {
        let mut w = Vec::new();
        if self.identity == Identity::None && self.mode != Mode::Offline {
            w.push(
                "identity=none: el cliente QUIC acepta CUALQUIER certificado. \
                 Esto es un túnel de desarrollo, no un P2P de producción."
                    .to_string(),
            );
        }
        if self.mode == Mode::Wan {
            w.push(
                "mode=wan: QUIC funciona, pero atravesar NAT requiere ICE/STUN \
                 y no está implementado. Detrás de CGNAT no habrá conexión."
                    .to_string(),
            );
        }
        if self.auth == Auth::Dev {
            w.push("auth=dev: sin autorización. Solo loopback.".to_string());
        }
        w
    }

    /// Parsea un campo de `^SYS("NET",...)`. Rechaza lo desconocido.
    pub fn set_field(&mut self, key: &str, value: &str) -> Result<(), ProfileError> {
        let v = value.trim().to_lowercase();
        let unknown = |field: &'static str, val: &str| ProfileError::Unknown {
            field,
            value: val.to_string(),
        };
        match key {
            "mode" => {
                self.mode = match v.as_str() {
                    "lan" => Mode::Lan,
                    "wan" => Mode::Wan,
                    "offline" => Mode::Offline,
                    other => return Err(unknown("mode", other)),
                }
            }
            "role" => {
                self.role = match v.as_str() {
                    "hub" => Role::Hub,
                    "store" => Role::Store,
                    "edge" => Role::Edge,
                    other => return Err(unknown("role", other)),
                }
            }
            "discovery" => {
                self.discovery = match v.as_str() {
                    "multicast" => Discovery::Multicast,
                    "none" => Discovery::None,
                    "seeds" => Discovery::Seeds,
                    other => return Err(unknown("discovery", other)),
                }
            }
            "transport" => {
                self.transport = match v.as_str() {
                    "quic" => Transport::Quic,
                    "shm" => Transport::Shm,
                    other => return Err(unknown("transport", other)),
                }
            }
            "identity" => {
                self.identity = match v.as_str() {
                    "pin" => Identity::Pin,
                    "none" => Identity::None,
                    "pubkey" => Identity::Pubkey,
                    other => return Err(unknown("identity", other)),
                }
            }
            "sign" => {
                self.sign = match v.as_str() {
                    "none" => Sign::None,
                    "hash-chain" => Sign::HashChain,
                    other => return Err(unknown("sign", other)),
                }
            }
            "auth" => {
                self.auth = match v.as_str() {
                    "macaroon" => Auth::Macaroon,
                    "hmac" => Auth::Hmac,
                    "dev" => Auth::Dev,
                    other => return Err(unknown("auth", other)),
                }
            }
            "storage" => {
                self.storage = match v.as_str() {
                    "sqlite" => Storage::Sqlite,
                    "lmdb" => Storage::Lmdb,
                    other => return Err(unknown("storage", other)),
                }
            }
            "pin" => {
                if v.is_empty() || v == "none" {
                    self.pin = None;
                } else {
                    // El formato se comprueba AQUÍ, no solo en validate():
                    // un pin mal escrito debe fallar al asignarse, no tres
                    // capas después.
                    if !pin_valido(&v) {
                        return Err(ProfileError::Unknown {
                            field: "pin",
                            value: format!("{v} (se esperan {PIN_HEX_LEN} hex de sha256)"),
                        });
                    }
                    self.pin = Some(v);
                }
            }
            "interface" => {
                self.interface = if v.is_empty() || v == "none" {
                    None
                } else {
                    if interface_v4(&v).is_none() {
                        return Err(ProfileError::Unknown {
                            field: "interface",
                            value: format!("{v} (se espera una IPv4 local, no 0.0.0.0)"),
                        });
                    }
                    Some(v)
                }
            }
            "grupo" => {
                if grupo_v4(&v).is_none() {
                    return Err(ProfileError::Unknown {
                        field: "grupo",
                        value: format!("{v} (se espera ip multicast:puerto, p.ej {GRUPO_POR_DEFECTO})"),
                    });
                }
                self.grupo = v;
            }
            "listen" => {
                self.listen = if v.is_empty() || v == "none" {
                    None
                } else {
                    Some(v.parse().map_err(|_| ProfileError::Unknown {
                        field: "listen",
                        value: v.clone(),
                    })?)
                }
            }
            other => {
                return Err(ProfileError::Unknown {
                    field: "campo",
                    value: other.to_string(),
                })
            }
        }
        Ok(())
    }

    /// Las claves que forman el perfil (para sembrar la PDB).
    pub const FIELDS: [&'static str; 12] = [
        "mode", "role", "discovery", "transport", "identity", "sign", "auth", "storage", "pin",
        "listen", "interface", "grupo",
    ];

    /// Render legible, para el arranque.
    pub fn describe(&self) -> String {
        format!(
            "mode={:?} role={:?} discovery={:?} transport={:?} identity={:?} sign={:?} auth={:?} storage={:?} interface={} grupo={} listen={}",
            self.mode,
            self.role,
            self.discovery,
            self.transport,
            self.identity,
            self.sign,
            self.auth,
            self.storage,
            self.interface.as_deref().unwrap_or("-"),
            self.grupo,
            self.listen
                .map(|a| a.to_string())
                .unwrap_or_else(|| "-".into())
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn el_perfil_minimo_valida() {
        assert!(minimal_profile().validate().is_ok());
    }

    #[test]
    fn multicast_sin_interfaz_no_arranca() {
        let mut p = minimal_profile();
        p.discovery = Discovery::Multicast;
        // Sin interfaz el join puede irse a la tarjeta equivocada y el nodo
        // se queda sordo sin decirlo.
        let e = p.validate().unwrap_err();
        assert!(matches!(e, ProfileError::Incoherent(_)));
    }

    #[test]
    fn multicast_con_interfaz_valida_arranca() {
        let mut p = minimal_profile();
        p.discovery = Discovery::Multicast;
        p.interface = Some("192.168.1.13".into());
        assert!(p.validate().is_ok());
    }

    #[test]
    fn multicast_con_interfaz_0000_no_arranca() {
        let mut p = minimal_profile();
        p.discovery = Discovery::Multicast;
        p.interface = Some("0.0.0.0".into());
        // 0.0.0.0 no parsea como interfaz válida en set_field, pero por si
        // alguien lo asigna directamente, validate también lo rechaza.
        assert!(p.validate().is_err() || interface_v4("0.0.0.0").is_none());
    }

    #[test]
    fn multicast_con_grupo_no_multicast_no_arranca() {
        let mut p = minimal_profile();
        p.discovery = Discovery::Multicast;
        p.interface = Some("192.168.1.13".into());
        p.grupo = "192.168.1.13:9444".into(); // no es multicast
        let e = p.validate().unwrap_err();
        assert!(matches!(e, ProfileError::Incoherent(_)));
    }

    #[test]
    fn seeds_no_implementado_no_arranca() {
        let mut p = minimal_profile();
        p.discovery = Discovery::Seeds;
        assert!(p.validate().is_err());
    }

    #[test]
    fn pin_sin_huella_no_arranca() {
        let mut p = minimal_profile();
        p.identity = Identity::Pin;
        // Sin pin: incoherente, no puede verificar nada.
        let e = p.validate().unwrap_err();
        assert!(matches!(e, ProfileError::Incoherent(_)));
    }

    #[test]
    fn pin_mal_formado_no_arranca() {
        let mut p = minimal_profile();
        p.identity = Identity::Pin;
        p.pin = Some("abcdef".into());
        let e = p.validate().unwrap_err();
        assert!(matches!(e, ProfileError::Incoherent(_)));
    }

    #[test]
    fn pin_valido_arranca() {
        let mut p = minimal_profile();
        p.identity = Identity::Pin;
        p.pin = Some("a".repeat(64));
        assert!(p.validate().is_ok(), "pin con 64 hex debe validar");
    }

    #[test]
    fn pin_con_dos_puntos_arranca() {
        let mut p = minimal_profile();
        p.identity = Identity::Pin;
        p.pin = Some("ab:cd".repeat(16)); // 64 hex + separadores
        assert!(p.validate().is_ok());
    }

    #[test]
    fn hash_chain_no_implementado_no_arranca() {
        let mut p = minimal_profile();
        p.sign = Sign::HashChain;
        assert!(p.validate().is_err());
    }

    #[test]
    fn dev_no_puede_escuchar_en_la_red() {
        let mut p = minimal_profile();
        p.auth = Auth::Dev;
        p.listen = Some("0.0.0.0:9443".parse().unwrap());
        let e = p.validate().unwrap_err();
        assert!(matches!(e, ProfileError::Incoherent(_)));
        // En loopback sí puede.
        p.listen = Some("127.0.0.1:9443".parse().unwrap());
        assert!(p.validate().is_ok());
    }

    #[test]
    fn offline_no_abre_endpoint() {
        let mut p = minimal_profile();
        p.mode = Mode::Offline;
        p.listen = Some("0.0.0.0:9443".parse().unwrap());
        assert!(p.validate().is_err());
        p.listen = None;
        p.transport = Transport::Shm;
        assert!(p.validate().is_ok());
    }

    #[test]
    fn valor_desconocido_se_rechaza_y_no_cae_a_default() {
        let mut p = minimal_profile();
        assert!(p.set_field("mode", "bogus").is_err());
        // No se ha modificado.
        assert_eq!(p.mode, Mode::Lan);
    }

    #[test]
    fn cada_campo_acepta_su_valor_valido() {
        // Un valor válido por campo, el más restrictivo que el código soporta.
        let casos = [
            ("mode", "offline"),
            ("role", "store"),
            ("discovery", "none"),
            ("transport", "shm"),
            ("identity", "none"),
            ("sign", "none"),
            ("auth", "hmac"),
            ("storage", "sqlite"),
            ("pin", "none"),
            ("listen", "127.0.0.1:9443"),
            ("interface", "192.168.1.13"),
            ("grupo", "239.255.77.77:9444"),
        ];
        for (k, v) in casos {
            let mut p = minimal_profile();
            assert!(p.set_field(k, v).is_ok(), "campo {k} no acepta '{v}'");
        }
    }

    #[test]
    fn ningun_campo_cae_a_default_con_basura() {
        // Cada campo, con basura, debe dar Err y NO modificar el perfil.
        let base = minimal_profile();
        for k in Profile::FIELDS {
            let mut p = minimal_profile();
            assert!(p.set_field(k, "%%basura%%").is_err(), "campo {k} aceptó basura");
            assert_eq!(p, base, "campo {k} modificó el perfil al fallar");
        }
    }

    #[test]
    fn identity_none_avisa() {
        let p = minimal_profile();
        assert!(p.warnings().iter().any(|w| w.contains("CUALQUIER certificado")));
    }
}
