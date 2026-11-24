//! Aplicación de un frame recibido al estado del nodo.
//!
//! Esta pieza es deliberadamente pequeña y sin red: recibe bytes, decide qué
//! son, y los aplica a la PDB. Así se puede probar entera sin abrir un socket.
//!
//! Formato de la carga: la MISMA convención que `^SYS("JOURNAL",…)` usa en el
//! repo — `^NS(sub1,sub2)=valor`. Se parsea aquí porque un nodo no acepta
//! código M arbitrario de la red: acepta **datos con forma de SET**.

use std::fmt;

/// Un SET que un par nos pide aplicar.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Escritura {
    pub ns: String,
    pub subs: Vec<String>,
    pub valor: String,
}

/// Por qué un frame no se pudo aplicar.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ErrorAplicar {
    /// La carga no tiene forma de `^NS(...)=valor`.
    Formato(String),
    /// El namespace no es válido (vacío, o no empieza por letra).
    NsInvalido(String),
    /// El nodo no acepta escrituras de red (perfil offline o rol que no escribe).
    NoAceptaEscrituras,
    /// El host de la MVM rechazó el SET.
    Host(String),
}

impl fmt::Display for ErrorAplicar {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ErrorAplicar::Formato(m) => write!(f, "formato de carga invalido: {m}"),
            ErrorAplicar::NsInvalido(ns) => write!(f, "namespace invalido: '{ns}'"),
            ErrorAplicar::NoAceptaEscrituras => {
                write!(f, "este nodo no acepta escrituras de red")
            }
            ErrorAplicar::Host(m) => write!(f, "el host rechazo el SET: {m}"),
        }
    }
}

/// Parsea `^NS(sub1,sub2)=valor` (con los subíndices entre comillas o no).
///
/// Reglas, deliberadamente estrictas:
/// - empieza por `^`
/// - `(` … `)` obligatorio
/// - `=` obligatorio
/// - los subíndices se separan por `,` **fuera de comillas**
/// - un valor vacío es válido (`^A="..."` con `""` no es lo mismo que ausente,
///   pero aquí ambos escriben cadena vacía y eso es lo que se documenta)
pub fn parsear_set(carga: &[u8]) -> Result<Escritura, ErrorAplicar> {
    let texto = std::str::from_utf8(carga)
        .map_err(|e| ErrorAplicar::Formato(format!("no es UTF-8: {e}")))?;
    let texto = texto.trim();
    if let Some(i) = texto.find('\0') {
        return Err(ErrorAplicar::Formato(format!("byte NUL en posicion {i}")));
    }

    let resto = texto
        .strip_prefix('^')
        .ok_or_else(|| ErrorAplicar::Formato("la carga debe empezar por '^'".into()))?;

    let abre = resto
        .find('(')
        .ok_or_else(|| ErrorAplicar::Formato("falta '(' del subindice".into()))?;
    let ns = &resto[..abre];
    if ns.is_empty() || !ns.chars().next().unwrap().is_alphabetic() {
        return Err(ErrorAplicar::NsInvalido(ns.to_string()));
    }

    // Recorrer hasta el ')' de cierre, respetando comillas.
    let despues = &resto[abre + 1..];
    let mut en_comillas = false;
    let mut cierre = None;
    for (i, c) in despues.char_indices() {
        match c {
            '"' => en_comillas = !en_comillas,
            ')' if !en_comillas => {
                cierre = Some(i);
                break;
            }
            _ => {}
        }
    }
    let cierre = cierre.ok_or_else(|| ErrorAplicar::Formato("falta ')' de cierre".into()))?;
    let dentro = &despues[..cierre];
    let cola = &despues[cierre + 1..];
    let valor = cola
        .strip_prefix('=')
        .ok_or_else(|| ErrorAplicar::Formato("falta '=' tras el subindice".into()))?;

    // Separar por comas fuera de comillas.
    let mut subs = Vec::new();
    let mut actual = String::new();
    let mut en_comillas = false;
    for c in dentro.chars() {
        match c {
            '"' => {
                en_comillas = !en_comillas;
                actual.push(c);
            }
            ',' if !en_comillas => {
                subs.push(limpiar_sub(&actual));
                actual.clear();
            }
            _ => actual.push(c),
        }
    }
    subs.push(limpiar_sub(&actual));

    Ok(Escritura {
        ns: ns.to_string(),
        subs,
        valor: valor.to_string(),
    })
}

/// Quita comillas envolventes y espacios de un subíndice.
fn limpiar_sub(s: &str) -> String {
    let t = s.trim();
    if t.len() >= 2 && t.starts_with('"') && t.ends_with('"') {
        t[1..t.len() - 1].replace("\"\"", "\"")
    } else {
        t.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parsea_set_simple() {
        let w = parsear_set(b"^SYS(\"JOURNAL\",1)=p1^p2").unwrap();
        assert_eq!(w.ns, "SYS");
        assert_eq!(w.subs, vec!["JOURNAL", "1"]);
        assert_eq!(w.valor, "p1^p2");
    }

    #[test]
    fn parsea_sin_comillas() {
        let w = parsear_set(b"^FLOTA(BARCO,lat)=41.38").unwrap();
        assert_eq!(w.ns, "FLOTA");
        assert_eq!(w.subs, vec!["BARCO", "lat"]);
        assert_eq!(w.valor, "41.38");
    }

    #[test]
    fn parsea_un_solo_subindice() {
        let w = parsear_set(b"^A(x)=1").unwrap();
        assert_eq!(w.subs, vec!["x"]);
        assert_eq!(w.valor, "1");
    }

    #[test]
    fn parsea_valor_con_comas_y_parentesis() {
        let w = parsear_set(b"^A(k)=lista,con,comas(yparens)").unwrap();
        assert_eq!(w.subs, vec!["k"]);
        assert_eq!(w.valor, "lista,con,comas(yparens)");
    }

    #[test]
    fn coma_dentro_de_comillas_no_separa() {
        let w = parsear_set(b"^A(\"a,b\",c)=v").unwrap();
        assert_eq!(w.subs, vec!["a,b", "c"]);
    }

    #[test]
    fn parentesis_dentro_de_comillas_no_cierra() {
        let w = parsear_set(b"^A(\"x)y\")=v").unwrap();
        assert_eq!(w.subs, vec!["x)y"]);
    }

    #[test]
    fn valor_vacio_es_valido() {
        let w = parsear_set(b"^A(k)=").unwrap();
        assert_eq!(w.valor, "");
    }

    #[test]
    fn sin_arroba_falla() {
        assert!(parsear_set(b"SYS(x)=1").is_err());
    }

    #[test]
    fn sin_parentesis_falla() {
        assert!(parsear_set(b"^SYS=1").is_err());
    }

    #[test]
    fn sin_igual_falla() {
        assert!(parsear_set(b"^SYS(x)").is_err());
    }

    #[test]
    fn ns_que_no_empieza_por_letra_falla() {
        assert!(matches!(
            parsear_set(b"^1SYS(x)=1"),
            Err(ErrorAplicar::NsInvalido(_))
        ));
        assert!(matches!(
            parsear_set(b"^(x)=1"),
            Err(ErrorAplicar::NsInvalido(_))
        ));
    }

    #[test]
    fn byte_nul_se_rechaza() {
        assert!(parsear_set(b"^A(k)=x\0y").is_err());
    }

    #[test]
    fn no_utf8_se_rechaza() {
        assert!(parsear_set(&[0x5E, 0x41, 0x28, 0xFF, 0x29, 0x3D, 0x31]).is_err());
    }

    #[test]
    fn no_acepta_codigo_m() {
        // Un intento de inyección: no es una escritura, es código.
        let w = parsear_set(b"^A(k)=1 W \"pwned\"").unwrap();
        // Se acepta como VALOR literal (texto), no se ejecuta.
        assert_eq!(w.valor, "1 W \"pwned\"");
        assert_eq!(w.ns, "A");
    }
}
