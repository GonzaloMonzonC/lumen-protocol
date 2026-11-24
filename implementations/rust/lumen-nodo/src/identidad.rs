//! Identidad criptográfica de nodo y raíz de armador (`identity=pubkey`).
//!
//! ## El problema que resuelve
//!
//! Con `identity=pin`, la confianza es **un hash copiado a mano**. Sirve para
//! PC↔NAS; no sirve para una flota, porque un barco no puede llevar un pin por
//! cada par y alguien tendría que actualizarlos uno a uno.
//!
//! Aquí el nodo **es** su clave: un par Ed25519. Y por encima hay una **raíz de
//! armador** que firma las claves de sus barcos, de modo que un barco puede
//! verificar a otro sin conocerlo de antes:
//!
//! ```text
//!   RAÍZ DEL ARMADOR (Ed25519)
//!      └── firma ──▶ clave del BARCO A
//!                     └── firma ──▶ sus muestras, sus anuncios
//! ```
//!
//! Un barco B acepta a A si: (1) la clave de A verifica la firma de lo que
//! envía, y (2) esa clave está firmada por la raíz del armador que B ya tiene.
//! **Sin listas de hashes y sin autoridad remota.**
//!
//! ## Por qué Ed25519 y no reutilizar X25519
//!
//! X25519 (`crypto.rs`) sirve para **acordar** una clave simétrica (Diffie-
//! Hellman). No sirve para **firmar**: no hay verificación de autoría con una
//! clave pública. Son primitivas distintas y el propio `crypto.rs` lo apunta en
//! su documentación. Para identidad hace falta firma.
//!
//! ## Lo que esta pieza NO hace
//!
//! No sustituye a TLS. QUIC ya va cifrado con TLS 1.3 y `identity=pin` ya
//! verifica el certificado. Esto añade **autoría verificable**: quién firmó
//! esto, y bajo qué flota. Son cosas distintas y complementarias.

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use rand::rngs::OsRng;

/// Longitud de una clave pública Ed25519 en bytes.
pub const CLAVE_PUBLICA_LEN: usize = 32;
/// Longitud de una clave privada (semilla) Ed25519 en bytes.
pub const CLAVE_PRIVADA_LEN: usize = 32;
/// Longitud de una firma Ed25519 en bytes.
pub const FIRMA_LEN: usize = 64;

/// Errores de identidad.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ErrorIdentidad {
    /// Clave pública con longitud incorrecta o punto inválido.
    ClaveInvalida(String),
    /// Firma con longitud incorrecta.
    FirmaInvalida(String),
    /// La firma no corresponde a esa clave y ese mensaje.
    FirmaNoVerifica,
    /// No hay raíz de armador configurada: no se puede verificar pertenencia.
    SinRaiz,
    /// La clave del par no está firmada por la raíz configurada.
    NoPerteneceALaFlota { clave: String },
    /// Texto en hex mal formado.
    HexInvalido(String),
}

impl std::fmt::Display for ErrorIdentidad {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ErrorIdentidad::ClaveInvalida(m) => write!(f, "clave publica invalida: {m}"),
            ErrorIdentidad::FirmaInvalida(m) => write!(f, "firma invalida: {m}"),
            ErrorIdentidad::FirmaNoVerifica => write!(f, "la firma no corresponde a esa clave"),
            ErrorIdentidad::SinRaiz => {
                write!(f, "no hay raiz de armador configurada: no se puede verificar la flota")
            }
            ErrorIdentidad::NoPerteneceALaFlota { clave } => write!(
                f,
                "la clave {clave} NO esta firmada por la raiz del armador: no pertenece a esta flota"
            ),
            ErrorIdentidad::HexInvalido(m) => write!(f, "hex invalido: {m}"),
        }
    }
}

impl std::error::Error for ErrorIdentidad {}

/// Identidad de un nodo: su par de claves Ed25519.
pub struct Identidad {
    firmante: SigningKey,
}

impl Identidad {
    /// Genera una identidad nueva con entropía del sistema.
    pub fn generar() -> Self {
        Self {
            firmante: SigningKey::generate(&mut OsRng),
        }
    }

    /// Reconstruye la identidad desde su semilla (32 bytes).
    pub fn desde_semilla(semilla: &[u8; CLAVE_PRIVADA_LEN]) -> Self {
        Self {
            firmante: SigningKey::from_bytes(semilla),
        }
    }

    /// Reconstruye desde hex (lo que se guarda en la PDB).
    pub fn desde_hex(hex: &str) -> Result<Self, ErrorIdentidad> {
        let bytes = hex_a_bytes(hex)?;
        if bytes.len() != CLAVE_PRIVADA_LEN {
            return Err(ErrorIdentidad::ClaveInvalida(format!(
                "semilla de {} bytes, se esperaban {CLAVE_PRIVADA_LEN}",
                bytes.len()
            )));
        }
        let mut s = [0u8; CLAVE_PRIVADA_LEN];
        s.copy_from_slice(&bytes);
        Ok(Self::desde_semilla(&s))
    }

    /// Clave pública del nodo (lo que se publica y se firma).
    pub fn clave_publica(&self) -> [u8; CLAVE_PUBLICA_LEN] {
        self.firmante.verifying_key().to_bytes()
    }

    /// Clave pública en hex (para la PDB y los anuncios).
    pub fn clave_publica_hex(&self) -> String {
        bytes_a_hex(&self.clave_publica())
    }

    /// Semilla en hex. **Es un secreto**: solo para persistirla.
    pub fn semilla_hex(&self) -> String {
        bytes_a_hex(&self.firmante.to_bytes())
    }

    /// Firma un mensaje.
    pub fn firmar(&self, mensaje: &[u8]) -> [u8; FIRMA_LEN] {
        self.firmante.sign(mensaje).to_bytes()
    }

    /// Firma en hex.
    pub fn firmar_hex(&self, mensaje: &[u8]) -> String {
        bytes_a_hex(&self.firmar(mensaje))
    }
}

/// Verifica una firma con una clave pública.
pub fn verificar(
    clave_publica: &[u8],
    mensaje: &[u8],
    firma: &[u8],
) -> Result<(), ErrorIdentidad> {
    if clave_publica.len() != CLAVE_PUBLICA_LEN {
        return Err(ErrorIdentidad::ClaveInvalida(format!(
            "{} bytes, se esperaban {CLAVE_PUBLICA_LEN}",
            clave_publica.len()
        )));
    }
    if firma.len() != FIRMA_LEN {
        return Err(ErrorIdentidad::FirmaInvalida(format!(
            "{} bytes, se esperaban {FIRMA_LEN}",
            firma.len()
        )));
    }
    let mut c = [0u8; CLAVE_PUBLICA_LEN];
    c.copy_from_slice(clave_publica);
    let vk = VerifyingKey::from_bytes(&c)
        .map_err(|e| ErrorIdentidad::ClaveInvalida(e.to_string()))?;
    let mut f = [0u8; FIRMA_LEN];
    f.copy_from_slice(firma);
    let sig = Signature::from_bytes(&f);
    vk.verify(mensaje, &sig)
        .map_err(|_| ErrorIdentidad::FirmaNoVerifica)
}

/// Verifica una firma en hex.
pub fn verificar_hex(clave_hex: &str, mensaje: &[u8], firma_hex: &str) -> Result<(), ErrorIdentidad> {
    let clave = hex_a_bytes(clave_hex)?;
    let firma = hex_a_bytes(firma_hex)?;
    verificar(&clave, mensaje, &firma)
}

// ── Raíz de armador ────────────────────────────────────────────────────────

/// El certificado de flota: una clave de barco firmada por la raíz del armador.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CertificadoFlota {
    /// Nombre del armador (informativo, va dentro de lo firmado).
    pub armador: String,
    /// Identificador del barco (informativo, va dentro de lo firmado).
    pub barco: String,
    /// Clave pública del barco, en hex.
    pub clave_barco: String,
    /// Firma de la raíz sobre el mensaje canónico.
    pub firma_raiz: String,
}

impl CertificadoFlota {
    /// Mensaje canónico que se firma.
    ///
    /// Se construye con un formato explícito y separado para que no haya
    /// ambigüedad: si se concatenara sin separadores, "ab"+"c" y "a"+"bc"
    /// darían el mismo mensaje y una firma valdría para otro certificado.
    pub fn mensaje_canonico(armador: &str, barco: &str, clave_barco_hex: &str) -> Vec<u8> {
        format!(
            "LUMEN-FLOTA/v1\narmador:{armador}\nbarco:{barco}\nclave:{clave_barco_hex}"
        )
        .into_bytes()
    }

    /// Crea el certificado firmándolo con la clave del armador.
    pub fn emitir(
        raiz: &Identidad,
        armador: &str,
        barco: &str,
        clave_barco_hex: &str,
    ) -> Result<Self, ErrorIdentidad> {
        // La clave del barco debe ser una clave Ed25519 válida: si no, se
        // estaría firmando basura y el error aparecería al conectar.
        let clave = hex_a_bytes(clave_barco_hex)?;
        if clave.len() != CLAVE_PUBLICA_LEN {
            return Err(ErrorIdentidad::ClaveInvalida(format!(
                "clave del barco de {} bytes, se esperaban {CLAVE_PUBLICA_LEN}",
                clave.len()
            )));
        }
        let msg = Self::mensaje_canonico(armador, barco, clave_barco_hex);
        Ok(Self {
            armador: armador.to_string(),
            barco: barco.to_string(),
            clave_barco: clave_barco_hex.to_lowercase(),
            firma_raiz: raiz.firmar_hex(&msg),
        })
    }

    /// Verifica que este certificado lo emitió la raíz dada.
    pub fn verificar_con_raiz(&self, raiz_clave_publica_hex: &str) -> Result<(), ErrorIdentidad> {
        let msg = Self::mensaje_canonico(&self.armador, &self.barco, &self.clave_barco);
        verificar_hex(raiz_clave_publica_hex, &msg, &self.firma_raiz)
            .map_err(|_| ErrorIdentidad::NoPerteneceALaFlota {
                clave: self.clave_barco.clone(),
            })
    }

    /// Serializa a texto plano `armador|barco|clave|firma` (legible en M).
    pub fn a_texto(&self) -> String {
        format!(
            "{}|{}|{}|{}",
            self.armador, self.barco, self.clave_barco, self.firma_raiz
        )
    }

    /// Parsea el texto plano.
    pub fn desde_texto(texto: &str) -> Result<Self, ErrorIdentidad> {
        let c: Vec<&str> = texto.trim().split('|').collect();
        if c.len() != 4 {
            return Err(ErrorIdentidad::FirmaInvalida(format!(
                "certificado con {} campos, se esperaban 4",
                c.len()
            )));
        }
        Ok(Self {
            armador: c[0].to_string(),
            barco: c[1].to_string(),
            clave_barco: c[2].to_string(),
            firma_raiz: c[3].to_string(),
        })
    }
}

/// Verifica que una clave de barco pertenece a la flota Y que firmó un mensaje.
///
/// Es la comprobación completa que hace falta al recibir un anuncio o una
/// muestra: la firma tiene que ser del barco, y la clave del barco tiene que
/// colgar de la raíz del armador.
pub fn verificar_miembro(
    certificado: &CertificadoFlota,
    raiz_clave_publica_hex: &str,
    mensaje: &[u8],
    firma_hex: &str,
) -> Result<(), ErrorIdentidad> {
    // 1. ¿La raíz del armador emitió este certificado?
    certificado.verificar_con_raiz(raiz_clave_publica_hex)?;
    // 2. ¿Esta firma la hizo la clave de ese certificado?
    verificar_hex(&certificado.clave_barco, mensaje, firma_hex)
}

// ── Hex ────────────────────────────────────────────────────────────────────

fn hex_a_bytes(hex: &str) -> Result<Vec<u8>, ErrorIdentidad> {
    let limpio: String = hex.chars().filter(|c| !c.is_whitespace()).collect();
    if limpio.len() % 2 != 0 {
        return Err(ErrorIdentidad::HexInvalido("longitud impar".into()));
    }
    let mut out = Vec::with_capacity(limpio.len() / 2);
    let bytes = limpio.as_bytes();
    for i in (0..bytes.len()).step_by(2) {
        let par = std::str::from_utf8(&bytes[i..i + 2])
            .map_err(|_| ErrorIdentidad::HexInvalido("no es ascii".into()))?;
        let b = u8::from_str_radix(par, 16)
            .map_err(|_| ErrorIdentidad::HexInvalido(par.to_string()))?;
        out.push(b);
    }
    Ok(out)
}

fn bytes_a_hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identidad_genera_clave_de_32_bytes() {
        let id = Identidad::generar();
        assert_eq!(id.clave_publica().len(), CLAVE_PUBLICA_LEN);
        assert_eq!(id.clave_publica_hex().len(), 64);
    }

    #[test]
    fn dos_identidades_son_distintas() {
        assert_ne!(
            Identidad::generar().clave_publica_hex(),
            Identidad::generar().clave_publica_hex()
        );
    }

    #[test]
    fn firmar_y_verificar() {
        let id = Identidad::generar();
        let msg = b"^FLOTA(BARCO,lat,1)=41.38";
        let firma = id.firmar(msg);
        assert!(verificar(&id.clave_publica(), msg, &firma).is_ok());
    }

    #[test]
    fn firma_de_otro_mensaje_no_vale() {
        let id = Identidad::generar();
        let firma = id.firmar(b"mensaje A");
        assert_eq!(
            verificar(&id.clave_publica(), b"mensaje B", &firma).unwrap_err(),
            ErrorIdentidad::FirmaNoVerifica
        );
    }

    #[test]
    fn firma_de_otra_identidad_no_vale() {
        let a = Identidad::generar();
        let b = Identidad::generar();
        let firma = a.firmar(b"x");
        assert_eq!(
            verificar(&b.clave_publica(), b"x", &firma).unwrap_err(),
            ErrorIdentidad::FirmaNoVerifica
        );
    }

    #[test]
    fn semilla_ida_y_vuelta() {
        let id = Identidad::generar();
        let hex = id.semilla_hex();
        let id2 = Identidad::desde_hex(&hex).expect("desde hex");
        assert_eq!(id.clave_publica_hex(), id2.clave_publica_hex());
        // Y firma igual (misma clave privada).
        assert_eq!(id.firmar(b"x"), id2.firmar(b"x"));
    }

    #[test]
    fn semilla_de_longitud_mala_se_rechaza() {
        assert!(Identidad::desde_hex("abcd").is_err());
        assert!(Identidad::desde_hex(&"zz".repeat(32)).is_err());
    }

    #[test]
    fn clave_publica_de_longitud_mala_no_verifica() {
        assert!(matches!(
            verificar(&[0u8; 16], b"x", &[0u8; 64]),
            Err(ErrorIdentidad::ClaveInvalida(_))
        ));
    }

    #[test]
    fn firma_de_longitud_mala_no_verifica() {
        let id = Identidad::generar();
        assert!(matches!(
            verificar(&id.clave_publica(), b"x", &[0u8; 10]),
            Err(ErrorIdentidad::FirmaInvalida(_))
        ));
    }

    // ── Certificado de flota ─────────────────────────────────────
    #[test]
    fn el_armador_emite_y_verifica_un_certificado() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let cert = CertificadoFlota::emitir(
            &raiz,
            "Armadora Ejemplo",
            "BARCO-A",
            &barco.clave_publica_hex(),
        )
        .expect("emitir");
        assert!(cert.verificar_con_raiz(&raiz.clave_publica_hex()).is_ok());
    }

    #[test]
    fn una_raiz_distinta_no_valida_el_certificado() {
        let raiz = Identidad::generar();
        let otra_raiz = Identidad::generar();
        let barco = Identidad::generar();
        let cert = CertificadoFlota::emitir(&raiz, "A", "B", &barco.clave_publica_hex()).unwrap();
        // Otra flota no debe aceptar a este barco.
        assert!(matches!(
            cert.verificar_con_raiz(&otra_raiz.clave_publica_hex()),
            Err(ErrorIdentidad::NoPerteneceALaFlota { .. })
        ));
    }

    #[test]
    fn un_certificado_manipulado_no_verifica() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let mut cert =
            CertificadoFlota::emitir(&raiz, "A", "B", &barco.clave_publica_hex()).unwrap();
        // Cambiar el nombre del barco invalida la firma (va dentro del canónico).
        cert.barco = "BARCO-PIRATA".into();
        assert!(cert.verificar_con_raiz(&raiz.clave_publica_hex()).is_err());
    }

    #[test]
    fn cambiar_la_clave_del_barco_invalida_la_firma() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let otro = Identidad::generar();
        let mut cert =
            CertificadoFlota::emitir(&raiz, "A", "B", &barco.clave_publica_hex()).unwrap();
        cert.clave_barco = otro.clave_publica_hex();
        assert!(cert.verificar_con_raiz(&raiz.clave_publica_hex()).is_err());
    }

    /// El mensaje canónico tiene separadores: "ab"+"c" no debe colisionar con
    /// "a"+"bc".
    #[test]
    fn el_mensaje_canonico_no_es_ambiguo() {
        let m1 = CertificadoFlota::mensaje_canonico("ab", "c", "00");
        let m2 = CertificadoFlota::mensaje_canonico("a", "bc", "00");
        assert_ne!(m1, m2);
    }

    #[test]
    fn certificado_ida_y_vuelta_por_texto() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let cert = CertificadoFlota::emitir(&raiz, "Armadora", "B-1", &barco.clave_publica_hex())
            .unwrap();
        let texto = cert.a_texto();
        assert_eq!(CertificadoFlota::desde_texto(&texto).unwrap(), cert);
        assert!(cert.verificar_con_raiz(&raiz.clave_publica_hex()).is_ok());
    }

    #[test]
    fn certificado_con_campos_de_menos_no_parsea() {
        assert!(CertificadoFlota::desde_texto("a|b|c").is_err());
        assert!(CertificadoFlota::desde_texto("").is_err());
    }

    // ── La comprobación completa ─────────────────────────────────
    #[test]
    fn miembro_de_la_flota_con_firma_buena() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let cert =
            CertificadoFlota::emitir(&raiz, "Armadora", "B-1", &barco.clave_publica_hex()).unwrap();
        let msg = b"^FLOTA(B-1,lat,1)=41.38";
        let firma = barco.firmar_hex(msg);
        assert!(verificar_miembro(&cert, &raiz.clave_publica_hex(), msg, &firma).is_ok());
    }

    #[test]
    fn un_barco_ajeno_no_puede_firmar_como_si_fuera_de_la_flota() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let impostor = Identidad::generar();
        let cert =
            CertificadoFlota::emitir(&raiz, "Armadora", "B-1", &barco.clave_publica_hex()).unwrap();
        let msg = b"^FLOTA(B-1,lat,1)=0";
        // El impostor firma con SU clave, no con la del barco del certificado.
        let firma_impostor = impostor.firmar_hex(msg);
        assert_eq!(
            verificar_miembro(&cert, &raiz.clave_publica_hex(), msg, &firma_impostor).unwrap_err(),
            ErrorIdentidad::FirmaNoVerifica
        );
    }

    #[test]
    fn un_certificado_de_otra_flota_se_rechaza_aunque_la_firma_sea_buena() {
        let raiz = Identidad::generar();
        let otra_raiz = Identidad::generar();
        let barco = Identidad::generar();
        // El certificado lo emite OTRA raíz.
        let cert =
            CertificadoFlota::emitir(&otra_raiz, "Otra", "B-9", &barco.clave_publica_hex()).unwrap();
        let msg = b"x";
        let firma = barco.firmar_hex(msg);
        // Nuestra raíz no debe aceptarlo.
        assert!(matches!(
            verificar_miembro(&cert, &raiz.clave_publica_hex(), msg, &firma),
            Err(ErrorIdentidad::NoPerteneceALaFlota { .. })
        ));
    }
}
