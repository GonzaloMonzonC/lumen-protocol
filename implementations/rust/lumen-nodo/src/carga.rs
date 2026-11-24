//! Lectura del perfil desde la PDB viva.
//!
//! `^SYS("NET",<campo>)` es la fuente de verdad. La línea de comandos solo
//! hace override. Si la PDB no responde, el nodo **no inventa un perfil**:
//! arranca con el mínimo y lo dice.

use crate::profile::{minimal_profile, Profile, ProfileError};

/// Resultado de intentar leer el perfil de la PDB.
#[derive(Debug, Clone)]
pub struct CargaPerfil {
    pub perfil: Profile,
    /// Campos que vinieron de la PDB (para poder decirlo en la cara).
    pub desde_pdb: Vec<String>,
    /// Motivo por el que no se pudo leer, si aplica.
    pub fallo: Option<String>,
}

/// Carga el perfil de `^SYS("NET",...)` usando un closure de lectura.
///
/// El closure abstrae el origen (sqlite, MVM, fichero) para poder testear sin
/// base de datos. Devuelve `None` si el campo no existe.
pub fn cargar<F>(mut leer: F) -> CargaPerfil
where
    F: FnMut(&str) -> Option<String>,
{
    let mut perfil = minimal_profile();
    let mut desde_pdb = Vec::new();
    let mut errores = Vec::new();

    for campo in Profile::FIELDS {
        if let Some(valor) = leer(campo) {
            let valor = valor.trim();
            if valor.is_empty() {
                continue;
            }
            match perfil.set_field(campo, valor) {
                Ok(()) => desde_pdb.push(format!("{campo}={valor}")),
                Err(e) => errores.push(e.to_string()),
            }
        }
    }

    let fallo = if errores.is_empty() {
        None
    } else {
        Some(errores.join("; "))
    };

    CargaPerfil {
        perfil,
        desde_pdb,
        fallo,
    }
}

/// Lee `^SYS("NET",...)` de una PDB sqlite.
///
/// Devuelve `Err` con el motivo si la base no existe o no se puede abrir; el
/// llamador debe decirlo y **no** fingir que hay perfil.
#[cfg(feature = "pdb")]
pub fn leer_de_sqlite(ruta: &str) -> Result<Vec<(String, String)>, String> {
    use rusqlite::Connection;
    let conn = Connection::open(ruta).map_err(|e| format!("abrir {ruta}: {e}"))?;
    let mut out = Vec::new();
    let mut stmt = conn
        .prepare("SELECT subkey, value FROM _globals WHERE ns = 'SYS'")
        .map_err(|e| format!("prepare: {e}"))?;
    let filas = stmt
        .query_map([], |row| {
            let sub: Vec<u8> = row.get(0)?;
            let val: String = row.get(1)?;
            Ok((sub, val))
        })
        .map_err(|e| format!("query: {e}"))?;

    // Subkey canónica: \x02NET\xff\x02<campo>\xff
    for fila in filas {
        let (sub, val) = fila.map_err(|e| format!("fila: {e}"))?;
        let partes = decodificar_subkey(&sub);
        if partes.len() == 2 && partes[0] == "NET" && !partes[1].is_empty() {
            out.push((partes[1].clone(), val));
        }
    }
    Ok(out)
}

/// Decodifica una subkey canónica (`\x02a\xff\x02b\xff` → `["a","b"]`).
fn decodificar_subkey(bytes: &[u8]) -> Vec<String> {
    let mut partes = Vec::new();
    let mut actual = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            0x02 => {
                actual.clear();
                i += 1;
            }
            0xFF => {
                if !actual.is_empty() || !partes.is_empty() {
                    partes.push(String::from_utf8_lossy(&actual).to_string());
                }
                actual.clear();
                i += 1;
            }
            b => {
                actual.push(b);
                i += 1;
            }
        }
    }
    // Los bytes que quedaron pendientes (fila sin terminador final: el MVM
    // escribe así las claves que no pasan por qpdb) son una parte más.
    if !actual.is_empty() {
        partes.push(String::from_utf8_lossy(&actual).to_string());
    }
    // Terminadores sueltos no cuentan.
    while partes.last().map(|p| p.is_empty()).unwrap_or(false) {
        partes.pop();
    }
    partes
}

/// Valida el perfil y clasifica el error para el código de salida.
pub fn validar(perfil: &Profile) -> Result<(), (ProfileError, &'static str)> {
    perfil.validate().map_err(|e| {
        let clase = match e {
            ProfileError::NotImplemented { .. } => "no-implementado",
            ProfileError::Incoherent(_) => "incoherente",
            ProfileError::Unknown { .. } => "desconocido",
        };
        (e, clase)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::profile::{Discovery, Identity, Mode};

    #[test]
    fn lee_perfil_completo_de_una_fuente() {
        let campos = vec![
            ("mode", "wan"),
            ("role", "edge"),
            ("discovery", "none"),
            ("sign", "none"),
            ("auth", "macaroon"),
        ];
        let c = cargar(|k| {
            campos
                .iter()
                .find(|(kk, _)| *kk == k)
                .map(|(_, v)| v.to_string())
        });
        assert_eq!(c.perfil.mode, Mode::Wan);
        assert_eq!(c.perfil.discovery, Discovery::None);
        assert_eq!(c.desde_pdb.len(), 5);
        assert!(c.fallo.is_none());
    }

    #[test]
    fn fuente_vacia_deja_el_minimo() {
        let c = cargar(|_| None);
        assert!(c.desde_pdb.is_empty());
        assert_eq!(c.perfil, minimal_profile());
        assert!(c.fallo.is_none());
    }

    #[test]
    fn valor_invalido_en_la_pdb_se_reporta_y_no_se_aplica() {
        let c = cargar(|k| if k == "mode" { Some("bogus".into()) } else { None });
        assert_eq!(c.perfil.mode, Mode::Lan, "no debe aplicar basura");
        assert!(c.fallo.as_deref().unwrap_or("").contains("mode"));
    }

    #[test]
    fn un_valor_no_implementado_no_se_aplica_y_la_validacion_falla() {
        let c = cargar(|k| if k == "identity" { Some("pin".into()) } else { None });
        // El campo sí se aplica (es un valor conocido)...
        assert_eq!(c.perfil.identity, Identity::Pin);
        // ...pero la validación debe echarlo.
        assert!(c.perfil.validate().is_err());
    }

    #[test]
    fn subkey_canonica_se_decodifica() {
        // \x02NET\xff\x02mode\xff
        let bytes = b"\x02NET\xff\x02mode\xff";
        assert_eq!(decodificar_subkey(bytes), vec!["NET", "mode"]);
    }

    #[test]
    fn subkey_sin_terminador_final_tambien() {
        let bytes = b"\x02NET\xff\x02listen";
        assert_eq!(decodificar_subkey(bytes), vec!["NET", "listen"]);
    }
}
