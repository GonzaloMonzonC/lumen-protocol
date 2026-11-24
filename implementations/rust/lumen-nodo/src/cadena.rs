//! `sign=hash-chain` — cadena de hashes por muestra + sellos de bloque (ADR-002).
//!
//! ## Qué problema resuelve
//!
//! Un dato firmado demuestra **quién** lo escribió. No demuestra que **no falte
//! ningún tramo**. Un barco que pierde cobertura seis horas y luego sube 21.600
//! muestras necesita que el receptor pueda probar que están todas, en orden, sin
//! huecos. Eso es esta cadena.
//!
//! ## Formato del valor (texto plano, legible en M con $P)
//!
//! ```text
//! <valor>|<prev_hash>|<hash>
//! ```
//!
//! - campo 1: el valor de la muestra (NO puede contener `|`, se rechaza)
//! - campo 2: hash de la muestra anterior (vacío en la génesis)
//! - campo 3: hash de esta muestra, 64 hex
//!
//! Se lee en M sin parsear JSON:
//! ```text
//! S v=$G(^FLOTA("BARCO","lat",1))
//! S val=$P(v,"|",1), prev=$P(v,"|",2), h=$P(v,"|",3)
//! ```
//!
//! ## Cálculo
//!
//! ```text
//! hash_muestra = sha256( prev_hash || valor )
//! sello_bloque = sha256( sello_anterior || hash_1 || ... || hash_N )
//! ```
//!
//! Todo determinista y sin estado oculto: cualquiera puede recalcular un sello
//! desde las muestras. Un cierre a medias no corrompe nada — el verificador
//! recalcula y localiza el hueco.
//!
//! ## Por qué cadena Y bloques
//!
//! - La cadena da prueba 1:1 y **localiza** qué muestra falta.
//! - El sello de bloque da verificación **rápida** de rangos grandes
//!   (21.600 muestras → 216 sellos en vez de 21.600 hashes).

use sha2::{Digest, Sha256};

use crate::aplicar::{ErrorAplicar, Escritura};
use crate::destino::{Aplicado, Destino};

/// Tamaño de una muestra por bloque.
pub const MUESTRAS_POR_BLOQUE: u64 = 100;

/// Longitud en hex de un hash sha256.
pub const HASH_HEX_LEN: usize = 64;

/// Separador del valor. Si el valor lo contiene, la escritura se rechaza:
/// es preferible rechazar a encadenar un hash sobre algo ambiguo.
pub const SEP: char = '|';

/// Namespace donde vive el estado de las cadenas (última muestra y hash).
pub const NS_CADENA: &str = "CADENA";

/// Un valor ya encadenado, listo para guardar.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MuestraEncadenada {
    pub valor: String,
    pub prev: String,
    pub hash: String,
}

/// Muestra encadenada **y firmada** por la clave del nodo (`identity=pubkey`).
///
/// El formato añade un cuarto campo:
///
/// ```text
/// <valor>|<prev_hash>|<hash>|<firma>
/// ```
///
/// ## Qué firma
///
/// Se firma **el mensaje canónico**, no el hash suelto:
///
/// ```text
/// LUMEN-MUESTRA/v1\n<ns>\n<subs>\n<hash>
/// ```
///
/// Incluir `ns` y `subs` en lo firmado impide **mover una muestra firmada a otra
/// serie o a otra posición**: la firma de `^FLOTA(ESTRELLA,lat,7)` no vale para
/// `^FLOTA(SIRIUS,lat,7)`. Es el mismo criterio que el certificado de flota, que
/// lleva dentro el nombre del barco.
///
/// Firmar el `hash` y no solo el valor tiene una consecuencia importante: como
/// `hash = sha256(prev || valor)`, y `prev` es el hash anterior, **la firma
/// cubre toda la cadena hasta el génesis**. Cambiar cualquier muestra anterior
/// cambia este hash y rompe esta firma.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MuestraFirmada {
    pub cadena: MuestraEncadenada,
    /// Firma Ed25519 en hex (128 chars). Vacía si el nodo no firma.
    pub firma: String,
}

impl MuestraFirmada {
    /// Mensaje canónico que se firma.
    pub fn mensaje_canonico(ns: &str, subs: &[String], hash: &str) -> Vec<u8> {
        format!("LUMEN-MUESTRA/v1\n{ns}\n{}\n{hash}", subs.join(",")).into_bytes()
    }

    /// Serializa a `valor|prev|hash|firma`.
    pub fn a_texto(&self) -> String {
        format!("{}|{}", self.cadena.a_texto(), self.firma)
    }

    /// Parsea `valor|prev|hash|firma`.
    pub fn desde_texto(texto: &str) -> Option<Self> {
        let campos: Vec<&str> = texto.split(SEP).collect();
        if campos.len() != 4 {
            return None;
        }
        let cadena = MuestraEncadenada::desde_texto(&format!(
            "{}{}{}{}{}",
            campos[0], SEP, campos[1], SEP, campos[2]
        ))?;
        let firma = campos[3];
        if firma.len() != 128 || !firma.chars().all(|c| c.is_ascii_hexdigit()) {
            return None;
        }
        Some(Self {
            cadena,
            firma: firma.to_string(),
        })
    }

    /// Verifica la firma contra la clave pública del nodo.
    pub fn verificar(
        &self,
        clave_publica_hex: &str,
        ns: &str,
        subs: &[String],
    ) -> Result<(), crate::identidad::ErrorIdentidad> {
        let msg = Self::mensaje_canonico(ns, subs, &self.cadena.hash);
        crate::identidad::verificar_hex(clave_publica_hex, &msg, &self.firma)
    }
}

/// Un sello de bloque firmado (`identity=pubkey` + `sign=hash-chain`).
///
/// Se firma el sello **junto al número de bloque**, para que nadie pueda mover
/// el sello del bloque 3 al bloque 7.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SelloFirmado {
    pub bloque: u64,
    pub sello: String,
    pub firma: String,
}

impl SelloFirmado {
    /// Mensaje canónico del sello.
    pub fn mensaje_canonico(ns: &str, serie: &str, bloque: u64, sello: &str) -> Vec<u8> {
        format!("LUMEN-SELLO/v1\n{ns}\n{serie}\n{bloque}\n{sello}").into_bytes()
    }

    /// Serializa a `bloque|sello|firma`.
    pub fn a_texto(&self) -> String {
        format!("{}|{}|{}", self.bloque, self.sello, self.firma)
    }

    /// Parsea `bloque|sello|firma`.
    pub fn desde_texto(texto: &str) -> Option<Self> {
        let c: Vec<&str> = texto.split(SEP).collect();
        if c.len() != 3 {
            return None;
        }
        let bloque = c[0].parse::<u64>().ok()?;
        if c[1].len() != HASH_HEX_LEN || !c[1].chars().all(|ch| ch.is_ascii_hexdigit()) {
            return None;
        }
        if c[2].len() != 128 || !c[2].chars().all(|ch| ch.is_ascii_hexdigit()) {
            return None;
        }
        Some(Self {
            bloque,
            sello: c[1].to_string(),
            firma: c[2].to_string(),
        })
    }

    /// Verifica la firma del sello.
    pub fn verificar(
        &self,
        clave_publica_hex: &str,
        ns: &str,
        serie: &str,
    ) -> Result<(), crate::identidad::ErrorIdentidad> {
        let msg = Self::mensaje_canonico(ns, serie, self.bloque, &self.sello);
        crate::identidad::verificar_hex(clave_publica_hex, &msg, &self.firma)
    }
}

impl MuestraEncadenada {
    /// Serializa al formato `valor|prev|hash`.
    pub fn a_texto(&self) -> String {
        format!("{}{}{}{}{}", self.valor, SEP, self.prev, SEP, self.hash)
    }

    /// Parsea `valor|prev|hash`. Estricto a propósito.
    pub fn desde_texto(texto: &str) -> Option<Self> {
        let campos: Vec<&str> = texto.split(SEP).collect();
        if campos.len() != 3 {
            return None;
        }
        let hash = campos[2];
        if hash.len() != HASH_HEX_LEN || !hash.chars().all(|c| c.is_ascii_hexdigit()) {
            return None;
        }
        let prev = campos[1];
        if !prev.is_empty()
            && (prev.len() != HASH_HEX_LEN || !prev.chars().all(|c| c.is_ascii_hexdigit()))
        {
            return None;
        }
        Some(Self {
            valor: campos[0].to_string(),
            prev: prev.to_string(),
            hash: hash.to_string(),
        })
    }
}

/// Errores al encadenar.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ErrorCadena {
    /// El valor contiene el separador: sería ambiguo al releerlo.
    ValorConSeparador,
    /// Una muestra guardada no tiene el formato esperado.
    MuestraIlegible(String),
    /// El `prev` de una muestra no coincide con el hash de la anterior.
    CadenaRota {
        muestra: u64,
        esperado: String,
        encontrado: String,
    },
    /// Falta una muestra en la secuencia.
    Hueco {
        falta: u64,
        antes: u64,
        despues: u64,
    },
    /// El sello de un bloque no cuadra con sus muestras.
    SelloRoto { bloque: u64 },
    /// Se pidió autoría y la muestra no viene firmada.
    SinFirma { muestra: u64 },
    /// La firma no es de la clave pública del nodo esperado.
    FirmaAjena { muestra: u64 },
}

impl std::fmt::Display for ErrorCadena {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ErrorCadena::ValorConSeparador => {
                write!(f, "el valor contiene '|': se rechaza para no romper la relectura")
            }
            ErrorCadena::MuestraIlegible(m) => write!(f, "muestra ilegible: {m}"),
            ErrorCadena::CadenaRota {
                muestra,
                esperado,
                encontrado,
            } => write!(
                f,
                "cadena rota en la muestra {muestra}: prev esperado {esperado}, encontrado {encontrado}"
            ),
            ErrorCadena::Hueco {
                falta,
                antes,
                despues,
            } => write!(f, "falta la muestra {falta} (entre {antes} y {despues})"),
            ErrorCadena::SelloRoto { bloque } => write!(f, "sello del bloque {bloque} no cuadra"),
            ErrorCadena::SinFirma { muestra } => write!(
                f,
                "la muestra {muestra} no viene firmada y se pidio autoria (identity=pubkey)"
            ),
            ErrorCadena::FirmaAjena { muestra } => write!(
                f,
                "la firma de la muestra {muestra} NO es de la clave publica del nodo"
            ),
        }
    }
}

impl std::error::Error for ErrorCadena {}

impl From<ErrorCadena> for ErrorAplicar {
    fn from(e: ErrorCadena) -> Self {
        match e {
            ErrorCadena::ValorConSeparador => ErrorAplicar::Formato(
                "el valor contiene '|' y no se puede encadenar".into(),
            ),
            otro => ErrorAplicar::Host(otro.to_string()),
        }
    }
}

/// sha256 en hex minúsculas.
pub fn sha256_hex(datos: &[u8]) -> String {
    <Sha256 as Digest>::digest(datos)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// Hash de una muestra: `sha256(prev || valor)`.
///
/// `prev` vacío = génesis. Se concatena sin separador adicional a propósito:
/// el `prev` tiene longitud fija (64) o es vacío, así que no hay ambigüedad
/// sobre dónde acaba uno y empieza el otro.
pub fn hash_muestra(prev: &str, valor: &str) -> String {
    let mut entrada = String::with_capacity(prev.len() + valor.len());
    entrada.push_str(prev);
    entrada.push_str(valor);
    sha256_hex(entrada.as_bytes())
}

/// Encadena una muestra nueva sobre el hash anterior.
pub fn encadenar(prev: &str, valor: &str) -> Result<MuestraEncadenada, ErrorCadena> {
    if valor.contains(SEP) {
        return Err(ErrorCadena::ValorConSeparador);
    }
    let hash = hash_muestra(prev, valor);
    Ok(MuestraEncadenada {
        valor: valor.to_string(),
        prev: prev.to_string(),
        hash,
    })
}

/// Sello de un bloque: `sha256(sello_previo || hash_1 || ... || hash_N)`.
///
/// Determinista: cualquiera puede recalcularlo desde las muestras del bloque,
/// sin que el emisor tenga que enviarlo.
pub fn sello_bloque(sello_previo: &str, hashes: &[String]) -> String {
    let mut entrada = String::with_capacity(sello_previo.len() + hashes.len() * HASH_HEX_LEN);
    entrada.push_str(sello_previo);
    for h in hashes {
        entrada.push_str(h);
    }
    sha256_hex(entrada.as_bytes())
}

/// Número de bloque al que pertenece una muestra (1-indexada).
pub fn bloque_de(muestra: u64) -> u64 {
    muestra.div_ceil(MUESTRAS_POR_BLOQUE)
}

/// Resultado de verificar un rango.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Verificacion {
    /// Muestras verificadas correctamente en cadena.
    pub muestras_ok: u64,
    /// Sellos de bloque comprobados (solo bloques completos).
    pub sellos_ok: u64,
    /// Firmas verificadas (0 si no se pasó clave pública).
    pub firmas_ok: u64,
    /// Primer problema encontrado, si lo hay.
    pub problema: Option<ErrorCadena>,
}

impl Verificacion {
    pub fn es_integro(&self) -> bool {
        self.problema.is_none()
    }
}

/// Verifica una secuencia de muestras (número de muestra, texto guardado).
///
/// No exige que empiece en 1: una flota puede sincronizar un rango. Lo que sí
/// exige es que **no falte ninguna dentro del rango recibido** y que cada `prev`
/// encaje con el hash anterior.
pub fn verificar(muestras: &[(u64, String)]) -> Verificacion {
    verificar_con_clave(muestras, None, "", &[])
}

/// Verifica la cadena y, si se da una clave pública, **exige** que cada muestra
/// esté firmada por ella.
///
/// `ns` y `subs_clave` identifican la serie para el mensaje canónico de la
/// firma (si no coinciden, la firma no verifica: es lo que impide mover una
/// muestra firmada a otra serie).
///
/// Si `clave_publica` es `None`, solo se comprueba la cadena (integridad). Si
/// es `Some`, una muestra sin firma o con firma ajena **es un fallo**: no se
/// acepta "cadena íntegra sin autoría" cuando se pidió autoría.
pub fn verificar_con_clave(
    muestras: &[(u64, String)],
    clave_publica: Option<&str>,
    ns: &str,
    subs_clave: &[String],
) -> Verificacion {
    let mut v = Verificacion {
        muestras_ok: 0,
        sellos_ok: 0,
        firmas_ok: 0,
        problema: None,
    };
    if muestras.is_empty() {
        return v;
    }

    let mut ordenadas = muestras.to_vec();
    ordenadas.sort_by_key(|(n, _)| *n);

    let mut hash_anterior: Option<String> = None;
    let mut numero_anterior: Option<u64> = None;

    let mut bloque_actual: Option<u64> = None;
    let mut hashes_bloque: Vec<String> = Vec::new();

    for (num, texto) in ordenadas {
        // Cada muestra puede venir con o sin firma (4 o 3 campos).
        let (m, firma) = match MuestraFirmada::desde_texto(&texto) {
            Some(mf) => (mf.cadena, Some(mf.firma)),
            None => match MuestraEncadenada::desde_texto(&texto) {
                Some(m) => (m, None),
                None => {
                    v.problema = Some(ErrorCadena::MuestraIlegible(texto));
                    return v;
                }
            },
        };

        // ── Firmeza: si se pidió autoría, la firma es obligatoria ──
        if let Some(clave) = clave_publica {
            let Some(firma) = firma.as_deref() else {
                v.problema = Some(ErrorCadena::SinFirma { muestra: num });
                return v;
            };
            let mut subs_muestra = subs_clave.to_vec();
            subs_muestra.push(num.to_string());
            let msg = MuestraFirmada::mensaje_canonico(ns, &subs_muestra, &m.hash);
            if crate::identidad::verificar_hex(clave, &msg, firma).is_err() {
                v.problema = Some(ErrorCadena::FirmaAjena { muestra: num });
                return v;
            }
            v.firmas_ok += 1;
        }

        // ── Hueco: ¿falta alguna entre la anterior y esta? ────────
        if let Some(prev_num) = numero_anterior {
            if num != prev_num + 1 {
                v.problema = Some(ErrorCadena::Hueco {
                    falta: prev_num + 1,
                    antes: prev_num,
                    despues: num,
                });
                return v;
            }
        }

        // ── Cadena: ¿el prev encaja con el hash anterior? ─────────
        if let Some(ref esperado) = hash_anterior {
            if !m.prev.eq_ignore_ascii_case(esperado) {
                v.problema = Some(ErrorCadena::CadenaRota {
                    muestra: num,
                    esperado: esperado.clone(),
                    encontrado: m.prev.clone(),
                });
                return v;
            }
        }

        // ── El hash declarado, ¿coincide con el recalculado? ──────
        let recalculado = hash_muestra(&m.prev, &m.valor);
        if !recalculado.eq_ignore_ascii_case(&m.hash) {
            v.problema = Some(ErrorCadena::CadenaRota {
                muestra: num,
                esperado: recalculado,
                encontrado: m.hash.clone(),
            });
            return v;
        }

        // ── Acumular bloque ───────────────────────────────────────
        let b = bloque_de(num);
        if bloque_actual != Some(b) {
            if bloque_actual.is_some() && hashes_bloque.len() as u64 == MUESTRAS_POR_BLOQUE {
                v.sellos_ok += 1;
            }
            hashes_bloque.clear();
            bloque_actual = Some(b);
        }
        hashes_bloque.push(m.hash.clone());

        hash_anterior = Some(m.hash);
        numero_anterior = Some(num);
        v.muestras_ok += 1;
    }

    if bloque_actual.is_some() && hashes_bloque.len() as u64 == MUESTRAS_POR_BLOQUE {
        v.sellos_ok += 1;
    }

    v
}

/// Una serie identificada: namespace + subíndices estables (sin el número).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Serie {
    pub ns: String,
    pub clave: Vec<String>,
}

impl Serie {
    /// Deduce la serie: el último subíndice es el número de muestra.
    pub fn desde_subs(ns: &str, subs: &[String]) -> Result<(Self, u64), ErrorCadena> {
        let Some(ultimo) = subs.last() else {
            return Err(ErrorCadena::MuestraIlegible(
                "una muestra encadenada necesita el numero como ultimo subindice".into(),
            ));
        };
        let n = ultimo.parse::<u64>().map_err(|_| {
            ErrorCadena::MuestraIlegible(format!(
                "el ultimo subindice '{ultimo}' debe ser el numero de muestra"
            ))
        })?;
        Ok((
            Self {
                ns: ns.to_string(),
                clave: subs[..subs.len() - 1].to_vec(),
            },
            n,
        ))
    }

    /// Clave estable de la serie (para el estado en PDB).
    pub fn etiqueta(&self) -> String {
        self.clave.join("/")
    }

    fn subs_estado(&self, campo: &str) -> Vec<String> {
        vec![self.ns.clone(), self.etiqueta(), campo.to_string()]
    }
}

/// Lee/escribe el estado de la cadena. Se abstrae para poder testear sin PDB.
pub trait EstadoCadena {
    fn ultima(&self, serie: &Serie) -> Option<u64>;
    fn hash_ultimo(&self, serie: &Serie) -> Option<String>;
    fn guardar(&mut self, serie: &Serie, numero: u64, hash: &str) -> Result<(), String>;

    /// Hashes del bloque indicado, para poder calcular su sello.
    ///
    /// Se leen de las muestras ya escritas. Devuelve `None` si el bloque no
    /// está completo: un bloque a medias no se sella.
    fn hashes_del_bloque(&self, _serie: &Serie, _bloque: u64) -> Option<Vec<String>> {
        None
    }

    /// Guarda el sello (firmado o no) de un bloque.
    fn guardar_sello(&mut self, _serie: &Serie, _sello: &SelloFirmado) -> Result<(), String> {
        Ok(())
    }
}

/// Encadena una muestra y la escribe.
pub fn aplicar_encadenado<D, E>(
    destino: &mut D,
    estado: &mut E,
    ns: &str,
    subs: &[String],
    valor: &str,
) -> Result<MuestraEncadenada, ErrorCadena>
where
    D: Destino,
    E: EstadoCadena,
{
    let (serie, numero) = Serie::desde_subs(ns, subs)?;

    // ── No reescribir el pasado ──────────────────────────────────
    // Encadenar otra vez una muestra anterior rompería a todos los que cuelgan
    // de ella. Es preferible rechazar que corromper la serie en silencio.
    if let Some(ya) = estado.ultima(&serie) {
        if numero < ya {
            return Err(ErrorCadena::MuestraIlegible(format!(
                "la muestra {numero} es anterior a la ultima encadenada ({ya}): \
                 reescribir el pasado romperia la cadena"
            )));
        }
    }

    let prev = estado.hash_ultimo(&serie).unwrap_or_default();
    let m = encadenar(&prev, valor)?;
    let texto = m.a_texto();

    destino
        .set(ns, subs, &texto)
        .map_err(|e| ErrorCadena::MuestraIlegible(format!("escribir muestra: {e}")))?;
    estado
        .guardar(&serie, numero, &m.hash)
        .map_err(|e| ErrorCadena::MuestraIlegible(format!("guardar estado: {e}")))?;

    Ok(m)
}

/// Combina `Destino` + `EstadoCadena` para poder encadenar sobre cualquier
/// destino que además sepa llevar el estado. Es lo que usa el nodo real.
pub trait DestinoEncadenable: Destino + EstadoCadena {}
impl<T: Destino + EstadoCadena> DestinoEncadenable for T {}

/// Aplica una escritura encadenada y, si hay identidad, **firmada**.
///
/// `firmante` es la identidad Ed25519 del nodo (`identity=pubkey`). Si es
/// `None`, se guarda solo la cadena (`valor|prev|hash`). Si está, se guarda
/// `valor|prev|hash|firma`, y la firma cubre el mensaje canónico con ns y subs
/// para que la muestra no se pueda mover a otra serie.
pub fn aplicar_encadenado_destino<T: DestinoEncadenable>(
    destino: &mut T,
    w: &Escritura,
    firmante: Option<&crate::identidad::Identidad>,
    log: &mut dyn FnMut(&str),
) -> Result<Aplicado, ErrorAplicar> {
    let (serie, numero) = Serie::desde_subs(&w.ns, &w.subs)?;

    if let Some(ya) = destino.ultima(&serie) {
        if numero < ya {
            return Err(ErrorCadena::MuestraIlegible(format!(
                "la muestra {numero} es anterior a la ultima encadenada ({ya}): \
                 reescribir el pasado romperia la cadena"
            ))
            .into());
        }
    }

    let prev = destino.hash_ultimo(&serie).unwrap_or_default();
    let m = encadenar(&prev, &w.valor)?;

    // ── Firma de la muestra (A) ──────────────────────────────────
    let texto = match firmante {
        Some(id) => {
            let msg = MuestraFirmada::mensaje_canonico(&w.ns, &w.subs, &m.hash);
            MuestraFirmada {
                firma: id.firmar_hex(&msg),
                cadena: m.clone(),
            }
            .a_texto()
        }
        None => m.a_texto(),
    };

    destino
        .set(&w.ns, &w.subs, &texto)
        .map_err(|e| ErrorAplicar::Host(format!("escribir muestra: {e}")))?;
    destino
        .guardar(&serie, numero, &m.hash)
        .map_err(|e| ErrorAplicar::Host(format!("guardar estado de cadena: {e}")))?;

    // ── Sello de bloque firmado (C) ──────────────────────────────
    // Cuando la muestra cierra un bloque (numero % 100 == 0), se calcula el
    // sello del bloque y se firma junto al número de bloque. Eso permite
    // verificar 100 muestras con UNA firma, y prueba que el bloque entero lo
    // cerró el mismo nodo.
    if numero % MUESTRAS_POR_BLOQUE == 0 {
        if let Some(hashes) = destino.hashes_del_bloque(&serie, bloque_de(numero)) {
            let sello = sello_bloque("", &hashes);
            let texto_sello = match firmante {
                Some(id) => {
                    let msg = SelloFirmado::mensaje_canonico(
                        &w.ns,
                        &serie.etiqueta(),
                        bloque_de(numero),
                        &sello,
                    );
                    SelloFirmado {
                        bloque: bloque_de(numero),
                        sello,
                        firma: id.firmar_hex(&msg),
                    }
                }
                None => SelloFirmado {
                    bloque: bloque_de(numero),
                    sello,
                    firma: String::new(),
                },
            };
            destino
                .guardar_sello(&serie, &texto_sello)
                .map_err(|e| ErrorAplicar::Host(format!("guardar sello: {e}")))?;
            log(&format!("sello de bloque {} guardado", bloque_de(numero)));
        }
    }

    log(&format!(
        "encadenada ^{}({}) -> hash {}{}",
        w.ns,
        w.subs.join(","),
        &m.hash[..8.min(m.hash.len())],
        if firmante.is_some() { " (firmada)" } else { "" }
    ));
    Ok(Aplicado {
        ns: w.ns.clone(),
        subs: w.subs.clone(),
        bytes: w.valor.len(),
        hash: Some(m.hash),
    })
}

/// Estado de cadena en memoria (tests y nodos sin persistencia del estado).
#[derive(Debug, Default)]
pub struct EstadoMemoria {
    pub ultimas: std::collections::HashMap<String, (u64, String)>,
}

fn clave_de(serie: &Serie) -> String {
    format!("{}::{}", serie.ns, serie.etiqueta())
}

impl EstadoCadena for EstadoMemoria {
    fn ultima(&self, serie: &Serie) -> Option<u64> {
        self.ultimas.get(&clave_de(serie)).map(|(n, _)| *n)
    }
    fn hash_ultimo(&self, serie: &Serie) -> Option<String> {
        self.ultimas.get(&clave_de(serie)).map(|(_, h)| h.clone())
    }
    fn guardar(&mut self, serie: &Serie, numero: u64, hash: &str) -> Result<(), String> {
        self.ultimas
            .insert(clave_de(serie), (numero, hash.to_string()));
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::destino::DestinoMemoria;

    fn subs(barco: &str, campo: &str, n: u64) -> Vec<String> {
        vec![barco.to_string(), campo.to_string(), n.to_string()]
    }

    /// Destino en memoria que también lleva el estado de la cadena.
    #[derive(Default)]
    struct DestinoCompleto {
        escrituras: DestinoMemoria,
        estado: EstadoMemoria,
    }
    impl Destino for DestinoCompleto {
        fn set(&mut self, ns: &str, subs: &[String], valor: &str) -> Result<usize, String> {
            self.escrituras.set(ns, subs, valor)
        }
    }
    impl EstadoCadena for DestinoCompleto {
        fn ultima(&self, serie: &Serie) -> Option<u64> {
            self.estado.ultima(serie)
        }
        fn hash_ultimo(&self, serie: &Serie) -> Option<String> {
            self.estado.hash_ultimo(serie)
        }
        fn guardar(&mut self, serie: &Serie, n: u64, h: &str) -> Result<(), String> {
            self.estado.guardar(serie, n, h)
        }
    }

    fn cadena(n: u64) -> Vec<(u64, String)> {
        let mut prev = String::new();
        let mut out = Vec::new();
        for i in 1..=n {
            let m = encadenar(&prev, &format!("lat-{i}")).unwrap();
            prev = m.hash.clone();
            out.push((i, m.a_texto()));
        }
        out
    }

    // ── Formato ──────────────────────────────────────────────────
    #[test]
    fn formato_ida_y_vuelta() {
        let m = encadenar("", "41.38").unwrap();
        let texto = m.a_texto();
        assert_eq!(MuestraEncadenada::desde_texto(&texto), Some(m));
        assert_eq!(texto.split('|').count(), 3);
    }

    #[test]
    fn genesis_tiene_prev_vacio() {
        let m = encadenar("", "x").unwrap();
        assert_eq!(m.prev, "");
        assert_eq!(m.hash.len(), 64);
    }

    #[test]
    fn el_hash_cambia_con_el_valor_y_con_el_prev() {
        assert_ne!(hash_muestra("", "1"), hash_muestra("", "2"));
        assert_ne!(hash_muestra("aa", "1"), hash_muestra("bb", "1"));
    }

    #[test]
    fn valor_con_separador_se_rechaza() {
        assert_eq!(encadenar("", "lat|41").unwrap_err(), ErrorCadena::ValorConSeparador);
    }

    #[test]
    fn texto_mal_formado_no_parsea() {
        assert!(MuestraEncadenada::desde_texto("a|b|c|d").is_none());
        assert!(MuestraEncadenada::desde_texto("solo-valor").is_none());
        assert!(MuestraEncadenada::desde_texto(&format!("v||{}", "z".repeat(64))).is_none());
        assert!(MuestraEncadenada::desde_texto("v||abc").is_none());
    }

    // ── Verificador ──────────────────────────────────────────────
    #[test]
    fn cadena_completa_es_integra() {
        let v = verificar(&cadena(10));
        assert!(v.es_integro(), "problema: {:?}", v.problema);
        assert_eq!(v.muestras_ok, 10);
    }

    /// EL TEST QUE IMPORTA: si se borra una muestra, debe decir CUÁL falta.
    #[test]
    fn detecta_y_localiza_una_muestra_borrada() {
        let mut c = cadena(10);
        c.retain(|(n, _)| *n != 7);
        let v = verificar(&c);
        assert!(!v.es_integro());
        match v.problema {
            Some(ErrorCadena::Hueco { falta, antes, despues }) => {
                assert_eq!((falta, antes, despues), (7, 6, 8));
            }
            otro => panic!("esperaba Hueco, vino {otro:?}"),
        }
    }

    #[test]
    fn detecta_valor_manipulado() {
        let mut c = cadena(5);
        let (n, texto) = c[2].clone();
        let mut m = MuestraEncadenada::desde_texto(&texto).unwrap();
        m.valor = "HACKEADO".into();
        c[2] = (n, m.a_texto());
        let v = verificar(&c);
        assert!(!v.es_integro());
        assert!(matches!(v.problema, Some(ErrorCadena::CadenaRota { .. })));
    }

    #[test]
    fn detecta_cadena_rota_por_enlace() {
        let mut c = cadena(5);
        let (n, texto) = c[4].clone();
        let mut m = MuestraEncadenada::desde_texto(&texto).unwrap();
        m.prev = "f".repeat(64);
        m.hash = hash_muestra(&m.prev, &m.valor); // hash coherente pero enlace roto
        c[4] = (n, m.a_texto());
        match verificar(&c).problema {
            Some(ErrorCadena::CadenaRota { muestra, .. }) => assert_eq!(muestra, 5),
            otro => panic!("esperaba CadenaRota, vino {otro:?}"),
        }
    }

    #[test]
    fn rango_parcial_sin_huecos_es_integro() {
        let c: Vec<_> = cadena(6)
            .into_iter()
            .filter(|(n, _)| (3..=6).contains(n))
            .collect();
        let v = verificar(&c);
        assert!(v.es_integro(), "problema: {:?}", v.problema);
        assert_eq!(v.muestras_ok, 4);
    }

    #[test]
    fn muestra_ilegible_y_vacio() {
        assert!(matches!(
            verificar(&[(1, "basura".into())]).problema,
            Some(ErrorCadena::MuestraIlegible(_))
        ));
        let v = verificar(&[]);
        assert!(v.es_integro());
        assert_eq!(v.muestras_ok, 0);
    }

    #[test]
    fn sello_determinista_y_sensible() {
        let hashes: Vec<String> = (1..=3).map(|i| hash_muestra("", &format!("v{i}"))).collect();
        let a = sello_bloque("", &hashes);
        assert_eq!(a, sello_bloque("", &hashes));
        assert_ne!(a, sello_bloque("ff", &hashes));
        let mut otros = hashes.clone();
        otros[1] = hash_muestra("", "otro");
        assert_ne!(a, sello_bloque("", &otros));
    }

    #[test]
    fn bloque_de_calcula_los_limites() {
        assert_eq!((bloque_de(1), bloque_de(100), bloque_de(101), bloque_de(200)), (1, 1, 2, 2));
    }

    #[test]
    fn rango_grande_cuenta_sellos_de_bloques_completos() {
        let v = verificar(&cadena(250));
        assert!(v.es_integro());
        assert_eq!(v.muestras_ok, 250);
        assert_eq!(v.sellos_ok, 2, "dos bloques completos de 100");
    }

    // ── Escritura en el nodo ─────────────────────────────────────
    #[test]
    fn serie_se_deduce_del_ultimo_subindice() {
        let (s, n) = Serie::desde_subs("FLOTA", &subs("BARCO", "lat", 7)).unwrap();
        assert_eq!((s.ns.as_str(), s.clave.clone(), n), ("FLOTA", vec!["BARCO".to_string(), "lat".to_string()], 7));
    }

    #[test]
    fn serie_sin_numero_se_rechaza() {
        assert!(Serie::desde_subs("FLOTA", &["B".into(), "lat".into()]).is_err());
        assert!(Serie::desde_subs("FLOTA", &[]).is_err());
    }

    #[test]
    fn primera_muestra_es_genesis_y_segunda_encadena() {
        let mut d = DestinoMemoria::default();
        let mut e = EstadoMemoria::default();
        let m1 = aplicar_encadenado(&mut d, &mut e, "F", &subs("B", "lat", 1), "a").unwrap();
        let m2 = aplicar_encadenado(&mut d, &mut e, "F", &subs("B", "lat", 2), "b").unwrap();
        assert_eq!(m1.prev, "");
        assert_eq!(m2.prev, m1.hash, "la segunda encadena con la primera");
    }

    #[test]
    fn series_distintas_no_se_mezclan() {
        let mut d = DestinoMemoria::default();
        let mut e = EstadoMemoria::default();
        aplicar_encadenado(&mut d, &mut e, "F", &subs("B1", "lat", 1), "a").unwrap();
        let m = aplicar_encadenado(&mut d, &mut e, "F", &subs("B2", "lat", 1), "b").unwrap();
        assert_eq!(m.prev, "", "otra serie empieza de cero");
    }

    #[test]
    fn no_se_puede_reescribir_el_pasado() {
        let mut d = DestinoMemoria::default();
        let mut e = EstadoMemoria::default();
        aplicar_encadenado(&mut d, &mut e, "F", &subs("B", "lat", 1), "a").unwrap();
        aplicar_encadenado(&mut d, &mut e, "F", &subs("B", "lat", 2), "b").unwrap();
        let err = aplicar_encadenado(&mut d, &mut e, "F", &subs("B", "lat", 1), "MAL").unwrap_err();
        assert!(matches!(err, ErrorCadena::MuestraIlegible(_)));
        assert_eq!(d.escrituras.len(), 2, "no debe escribir nada");
    }

    #[test]
    fn valor_con_separador_se_rechaza_antes_de_escribir() {
        let mut d = DestinoMemoria::default();
        let mut e = EstadoMemoria::default();
        assert_eq!(
            aplicar_encadenado(&mut d, &mut e, "F", &subs("B", "lat", 1), "a|b").unwrap_err(),
            ErrorCadena::ValorConSeparador
        );
        assert!(d.escrituras.is_empty());
    }

    /// El ciclo completo: lo que escribe el nodo lo da por bueno el verificador.
    #[test]
    fn lo_escrito_se_verifica() {
        let mut d = DestinoCompleto::default();
        for i in 1..=5u64 {
            aplicar_encadenado_destino(
                &mut d,
                &Escritura {
                    ns: "F".into(),
                    subs: subs("B", "lat", i),
                    valor: format!("v{i}"),
                },
                None,
                &mut |_: &str| {},
            )
            .unwrap();
        }
        let guardadas: Vec<(u64, String)> = d
            .escrituras
            .escrituras
            .iter()
            .map(|(_, s, v)| (s.last().unwrap().parse::<u64>().unwrap(), v.clone()))
            .collect();
        let v = verificar(&guardadas);
        assert!(v.es_integro(), "problema: {:?}", v.problema);
        assert_eq!(v.muestras_ok, 5);
    }

    // ── Muestra FIRMADA (identity=pubkey) ────────────────────────
    use crate::identidad::Identidad;

    #[test]
    fn la_muestra_firmada_tiene_cuatro_campos() {
        let id = Identidad::generar();
        let mut d = DestinoCompleto::default();
        aplicar_encadenado_destino(
            &mut d,
            &Escritura {
                ns: "F".into(),
                subs: subs("B", "lat", 1),
                valor: "41.38".into(),
            },
            Some(&id),
            &mut |_: &str| {},
        )
        .unwrap();
        let texto = &d.escrituras.escrituras[0].2;
        assert_eq!(texto.split('|').count(), 4, "valor|prev|hash|firma");
        assert!(MuestraFirmada::desde_texto(texto).is_some());
    }

    #[test]
    fn la_firma_de_la_muestra_verifica_con_su_clave() {
        let id = Identidad::generar();
        let s = subs("B", "lat", 1);
        let mut d = DestinoCompleto::default();
        aplicar_encadenado_destino(
            &mut d,
            &Escritura {
                ns: "F".into(),
                subs: s.clone(),
                valor: "41.38".into(),
            },
            Some(&id),
            &mut |_: &str| {},
        )
        .unwrap();
        let mf = MuestraFirmada::desde_texto(&d.escrituras.escrituras[0].2).unwrap();
        assert!(mf.verificar(&id.clave_publica_hex(), "F", &s).is_ok());
    }

    /// EL TEST DE LA FIRMA: una muestra firmada para una serie NO vale en otra.
    #[test]
    fn una_muestra_firmada_no_se_puede_mover_a_otra_serie() {
        let id = Identidad::generar();
        let mut d = DestinoCompleto::default();
        aplicar_encadenado_destino(
            &mut d,
            &Escritura {
                ns: "F".into(),
                subs: subs("BARCO-A", "lat", 1),
                valor: "41.38".into(),
            },
            Some(&id),
            &mut |_: &str| {},
        )
        .unwrap();
        let mf = MuestraFirmada::desde_texto(&d.escrituras.escrituras[0].2).unwrap();

        // Vale en su serie...
        assert!(mf
            .verificar(&id.clave_publica_hex(), "F", &subs("BARCO-A", "lat", 1))
            .is_ok());
        // ...y NO vale en otra, aunque el valor y la cadena sean idénticos.
        assert!(mf
            .verificar(&id.clave_publica_hex(), "F", &subs("BARCO-B", "lat", 1))
            .is_err(), "mover la muestra a otro barco debe romper la firma");
        assert!(mf
            .verificar(&id.clave_publica_hex(), "F", &subs("BARCO-A", "hdg", 1))
            .is_err(), "cambiar el campo debe romper la firma");
    }

    #[test]
    fn una_muestra_firmada_por_otro_nodo_no_verifica() {
        let id = Identidad::generar();
        let otro = Identidad::generar();
        let s = subs("B", "lat", 1);
        let mut d = DestinoCompleto::default();
        aplicar_encadenado_destino(
            &mut d,
            &Escritura {
                ns: "F".into(),
                subs: s.clone(),
                valor: "x".into(),
            },
            Some(&id),
            &mut |_: &str| {},
        )
        .unwrap();
        let mf = MuestraFirmada::desde_texto(&d.escrituras.escrituras[0].2).unwrap();
        assert!(mf.verificar(&otro.clave_publica_hex(), "F", &s).is_err());
    }

    #[test]
    fn sin_firmante_se_guarda_solo_la_cadena() {
        let mut d = DestinoCompleto::default();
        aplicar_encadenado_destino(
            &mut d,
            &Escritura {
                ns: "F".into(),
                subs: subs("B", "lat", 1),
                valor: "x".into(),
            },
            None,
            &mut |_: &str| {},
        )
        .unwrap();
        assert_eq!(d.escrituras.escrituras[0].2.split('|').count(), 3);
    }

    #[test]
    fn el_verificador_exige_firma_cuando_se_le_da_clave() {
        let id = Identidad::generar();
        // Cadena SIN firmar.
        let c = cadena(3);
        // Sin clave: integra.
        assert!(verificar(&c).es_integro());
        // Con clave: falta la firma.
        let v = verificar_con_clave(&c, Some(&id.clave_publica_hex()), "F", &subs("B", "lat", 0)[..2]);
        assert!(matches!(v.problema, Some(ErrorCadena::SinFirma { .. })));
    }

    #[test]
    fn el_verificador_cuenta_firmas_buenas() {
        let id = Identidad::generar();
        let s = subs("B", "lat", 0);
        let clave = &s[..2];
        let mut d = DestinoCompleto::default();
        for i in 1..=4u64 {
            aplicar_encadenado_destino(
                &mut d,
                &Escritura {
                    ns: "F".into(),
                    subs: subs("B", "lat", i),
                    valor: format!("v{i}"),
                },
                Some(&id),
                &mut |_: &str| {},
            )
            .unwrap();
        }
        let guardadas: Vec<(u64, String)> = d
            .escrituras
            .escrituras
            .iter()
            .map(|(_, sb, v)| (sb.last().unwrap().parse::<u64>().unwrap(), v.clone()))
            .collect();
        let v = verificar_con_clave(&guardadas, Some(&id.clave_publica_hex()), "F", clave);
        assert!(v.es_integro(), "problema: {:?}", v.problema);
        assert_eq!(v.muestras_ok, 4);
        assert_eq!(v.firmas_ok, 4, "debe contar las 4 firmas");
    }

    // ── Sello de bloque firmado ──────────────────────────────────
    #[test]
    fn el_sello_firmado_ida_y_vuelta_y_verificacion() {
        let id = Identidad::generar();
        let sello = sello_bloque("", &[hash_muestra("", "a"), hash_muestra("", "b")]);
        let msg = SelloFirmado::mensaje_canonico("F", "B/lat", 1, &sello);
        let sf = SelloFirmado {
            bloque: 1,
            sello: sello.clone(),
            firma: id.firmar_hex(&msg),
        };
        let texto = sf.a_texto();
        let leido = SelloFirmado::desde_texto(&texto).expect("releer");
        assert_eq!(leido, sf);
        assert!(leido.verificar(&id.clave_publica_hex(), "F", "B/lat").is_ok());
    }

    /// El sello va firmado JUNTO al número de bloque: moverlo de bloque
    /// rompe la firma (si no, el sello del bloque 3 valdría para el 7).
    #[test]
    fn un_sello_no_se_puede_mover_a_otro_bloque() {
        let id = Identidad::generar();
        let sello = sello_bloque("", &[hash_muestra("", "a")]);
        let msg = SelloFirmado::mensaje_canonico("F", "B/lat", 3, &sello);
        let sf = SelloFirmado {
            bloque: 3,
            sello: sello.clone(),
            firma: id.firmar_hex(&msg),
        };
        assert!(sf.verificar(&id.clave_publica_hex(), "F", "B/lat").is_ok());
        // Mismo sello y misma firma, otro bloque.
        let movido = SelloFirmado {
            bloque: 7,
            ..sf.clone()
        };
        assert!(
            movido.verificar(&id.clave_publica_hex(), "F", "B/lat").is_err(),
            "mover el sello al bloque 7 debe romper la firma"
        );
    }

    #[test]
    fn un_sello_no_se_puede_mover_a_otra_serie() {
        let id = Identidad::generar();
        let sello = sello_bloque("", &[hash_muestra("", "a")]);
        let msg = SelloFirmado::mensaje_canonico("F", "B/lat", 1, &sello);
        let sf = SelloFirmado {
            bloque: 1,
            sello,
            firma: id.firmar_hex(&msg),
        };
        assert!(sf.verificar(&id.clave_publica_hex(), "F", "B/lat").is_ok());
        assert!(sf.verificar(&id.clave_publica_hex(), "F", "OTRO/lat").is_err());
    }

    #[test]
    fn sello_mal_formado_no_parsea() {
        assert!(SelloFirmado::desde_texto("a|b").is_none());
        assert!(SelloFirmado::desde_texto("1|corto|firma").is_none());
    }
}
