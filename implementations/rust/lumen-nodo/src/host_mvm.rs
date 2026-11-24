//! Destino sobre el host de la MVM: los SETs aterrizan en la PDB.
//!
//! `MemoryHost::from_sqlite` (feature `sqlite`, activa por defecto) abre la
//! base, carga lo que hay y **persiste cada `set()`** en `_globals`. Es el
//! mismo host que usa Poli, así que un nodo y un agente escriben con la misma
//! semántica y el mismo formato de subkey.
//!
//! Se declara en un módulo aparte y detrás de feature para que el binario
//! pueda compilarse sin sqlite (nodo mínimo embebido).

use lumen_mlight::{Host, MemoryHost, Subscript};
use lumen_mlight::Value;

use crate::destino::Destino;

/// Convierte un subíndice de texto al tipo M: entero si lo parece, cadena si no.
///
/// La regla importa: `^A(1)` y `^A("1")` son claves DISTINTAS en MUMPS, y el
/// decode del host preserva el tipo desde el fix de `3528f30`. Si aquí
/// metiéramos todo como cadena, un nodo escribiría en una clave que el agente
/// no lee. Por eso el número se reconoce como número.
fn sub_de_texto(s: &str) -> Subscript {
    if let Ok(n) = s.parse::<f64>() {
        // Solo si el texto ES el número (evita "1.0"->1 y "+1"->1 sorpresas).
        if formato_canonico(n) == s {
            return Subscript::Number(n);
        }
    }
    Subscript::String(s.to_string())
}

/// Representación de un número que `parse::<f64>()` aceptaría sin cambios.
fn formato_canonico(n: f64) -> String {
    if n.fract() == 0.0 && n.abs() < 1e15 {
        format!("{}", n as i64)
    } else {
        format!("{n}")
    }
}

/// Host de la MVM como destino de las escrituras de red.
pub struct DestinoMvm {
    host: MemoryHost,
    /// Si el nodo es de solo lectura, se niega a escribir (rol/perfil).
    solo_lectura: bool,
    /// Qué motor está sirviendo de verdad (para poder decirlo en voz alta).
    motor: crate::profile::Storage,
}

impl DestinoMvm {
    /// Abre la PDB con SQLite (carga en RAM, persistencia por fila).
    ///
    /// Falla si la base no se puede abrir: preferimos no arrancar antes que
    /// arrancar escribiendo en el vacío.
    pub fn abrir_sqlite(ruta_pdb: &str, solo_lectura: bool) -> Result<Self, String> {
        let host = MemoryHost::from_sqlite(ruta_pdb)
            .map_err(|e| format!("no se pudo abrir la PDB {ruta_pdb}: {e}"))?;
        Ok(Self {
            host,
            solo_lectura,
            motor: crate::profile::Storage::Sqlite,
        })
    }

    /// Abre la PDB con LMDB (mmap directo, sin precarga a RAM).
    ///
    /// ⚠️ Recibe un **directorio**, no un fichero: LMDB trabaja sobre un
    /// entorno (`data.mdb` + `lock.mdb` dentro).
    #[cfg(feature = "motor-lmdb")]
    pub fn abrir_lmdb(dir: &str, solo_lectura: bool) -> Result<Self, String> {
        let host = MemoryHost::from_lmdb(dir)
            .map_err(|e| format!("no se pudo abrir el entorno LMDB {dir}: {e}"))?;
        Ok(Self {
            host,
            solo_lectura,
            motor: crate::profile::Storage::Lmdb,
        })
    }

    /// Abre según lo que diga el perfil. Es la única puerta que debe usarse.
    pub fn abrir(ruta: &str, motor: crate::profile::Storage, solo_lectura: bool) -> Result<Self, String> {
        match motor {
            crate::profile::Storage::Sqlite => Self::abrir_sqlite(ruta, solo_lectura),
            #[cfg(feature = "motor-lmdb")]
            crate::profile::Storage::Lmdb => Self::abrir_lmdb(ruta, solo_lectura),
            #[cfg(not(feature = "motor-lmdb"))]
            crate::profile::Storage::Lmdb => {
                Err("storage=lmdb pero el binario se compilo sin 'motor-lmdb'".to_string())
            }
        }
    }

    /// Qué motor está sirviendo de verdad.
    pub fn motor(&self) -> crate::profile::Storage {
        self.motor
    }

    /// Lectura, para verificar tras escribir.
    pub fn leer(&self, ns: &str, subs: &[String]) -> Option<String> {
        let subs_m: Vec<Subscript> = subs.iter().map(|s| sub_de_texto(s)).collect();
        self.host
            .get(ns, &subs_m)
            .ok()
            .flatten()
            .map(|v| v.as_string())
    }

    /// `$D` del nodo, para comprobar que existe lo que acabamos de escribir.
    pub fn existe(&self, ns: &str, subs: &[String]) -> u8 {
        let subs_m: Vec<Subscript> = subs.iter().map(|s| sub_de_texto(s)).collect();
        self.host.data(ns, &subs_m).unwrap_or(0)
    }
}

impl Destino for DestinoMvm {
    fn set(&mut self, ns: &str, subs: &[String], valor: &str) -> Result<usize, String> {
        let subs_m: Vec<Subscript> = subs.iter().map(|s| sub_de_texto(s)).collect();
        self.host
            .set(ns, &subs_m, Value::String(valor.to_string()))?;
        Ok(subs_m.len())
    }

    fn acepta_escrituras(&self) -> bool {
        !self.solo_lectura
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sub_entero_se_reconoce() {
        assert_eq!(sub_de_texto("1"), Subscript::Number(1.0));
        assert_eq!(sub_de_texto("42"), Subscript::Number(42.0));
        assert_eq!(sub_de_texto("-7"), Subscript::Number(-7.0));
    }

    #[test]
    fn sub_que_parece_numero_pero_no_lo_es_queda_cadena() {
        // "1.0" -> el canónico es "1", no coincide: se deja como cadena.
        assert_eq!(sub_de_texto("1.0"), Subscript::String("1.0".into()));
        assert_eq!(sub_de_texto("+1"), Subscript::String("+1".into()));
        assert_eq!(sub_de_texto("007"), Subscript::String("007".into()));
    }

    #[test]
    fn sub_de_texto_queda_cadena() {
        assert_eq!(sub_de_texto("lat"), Subscript::String("lat".into()));
        assert_eq!(sub_de_texto("BARCO-1"), Subscript::String("BARCO-1".into()));
    }

    #[test]
    fn sub_decimal_se_reconoce() {
        assert_eq!(sub_de_texto("41.38"), Subscript::Number(41.38));
    }

    #[test]
    fn pdb_temporal_escribe_y_lee() {
        let dir = std::env::temp_dir().join(format!("lumen-nodo-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let ruta = dir.join("t.db");
        let ruta_s = ruta.to_string_lossy().to_string();

        {
            let mut d = DestinoMvm::abrir_sqlite(&ruta_s, false).expect("abrir");
            d.set("FLOTA", &["BARCO".into(), "lat".into()], "41.38")
                .expect("set");
            assert_eq!(
                d.leer("FLOTA", &["BARCO".into(), "lat".into()]).as_deref(),
                Some("41.38")
            );
            assert_eq!(d.existe("FLOTA", &["BARCO".into(), "lat".into()]), 1);
        }
        // Reabrir: el dato debe seguir ahí (persistencia real, no RAM).
        {
            let d = DestinoMvm::abrir_sqlite(&ruta_s, false).expect("reabrir");
            assert_eq!(
                d.leer("FLOTA", &["BARCO".into(), "lat".into()]).as_deref(),
                Some("41.38"),
                "el dato debe persistir tras cerrar y reabrir"
            );
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn solo_lectura_no_escribe() {
        let dir = std::env::temp_dir().join(format!("lumen-nodo-ro-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let ruta = dir.join("ro.db").to_string_lossy().to_string();
        let mut d = DestinoMvm::abrir_sqlite(&ruta, true).expect("abrir");
        assert!(!d.acepta_escrituras());
        // El set directo al host sigue funcionando (es el trait, no la política);
        // la política la aplica `destino::aplicar`.
        assert!(d.set("A", &["k".into()], "v").is_ok());
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// LMDB trabaja sobre un DIRECTORIO, no un fichero. Este test fija ese
    /// contrato y comprueba que lo escrito sobrevive a cerrar y reabrir el
    /// entorno (que es lo que hace un nodo al reiniciar).
    #[cfg(feature = "motor-lmdb")]
    #[test]
    fn lmdb_escribe_lee_y_persiste() {
        let dir = std::env::temp_dir().join(format!("lumen-nodo-lmdb-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let dir_s = dir.to_string_lossy().to_string();

        {
            let mut d = DestinoMvm::abrir_lmdb(&dir_s, false).expect("abrir lmdb");
            assert_eq!(d.motor(), crate::profile::Storage::Lmdb);
            d.set("FLOTA", &["BARCO".into(), "lat".into()], "41.38")
                .expect("set lmdb");
            assert_eq!(
                d.leer("FLOTA", &["BARCO".into(), "lat".into()]).as_deref(),
                Some("41.38")
            );
            assert_eq!(d.existe("FLOTA", &["BARCO".into(), "lat".into()]), 1);
        }
        // Reabrir el entorno: el dato debe seguir.
        {
            let d = DestinoMvm::abrir_lmdb(&dir_s, false).expect("reabrir lmdb");
            assert_eq!(
                d.leer("FLOTA", &["BARCO".into(), "lat".into()]).as_deref(),
                Some("41.38"),
                "LMDB debe persistir el SET tras cerrar y reabrir"
            );
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Un nodo que escribe por LMDB debe leer lo MISMO que escribiría por
    /// sqlite para el mismo `^NS(subs)`. Si divergen, el tipo de subíndice se
    /// está perdiendo en algún camino.
    #[cfg(feature = "motor-lmdb")]
    #[test]
    fn lmdb_y_sqlite_ven_la_misma_clave() {
        let base = std::env::temp_dir().join(format!("lumen-nodo-par-{}", std::process::id()));
        let dir_lmdb = base.join("lmdb");
        std::fs::create_dir_all(&dir_lmdb).unwrap();
        let ruta_sqlite = base.join("s.db").to_string_lossy().to_string();

        let mut por_lmdb =
            DestinoMvm::abrir_lmdb(&dir_lmdb.to_string_lossy(), false).expect("lmdb");
        let mut por_sqlite = DestinoMvm::abrir_sqlite(&ruta_sqlite, false).expect("sqlite");

        // Clave con subíndice numérico y con cadena: las dos deben coincidir.
        por_lmdb.set("T", &["1".into(), "lat".into()], "a").unwrap();
        por_sqlite.set("T", &["1".into(), "lat".into()], "a").unwrap();
        por_lmdb.set("T", &["BARCO".into()], "b").unwrap();
        por_sqlite.set("T", &["BARCO".into()], "b").unwrap();

        assert_eq!(
            por_lmdb.leer("T", &["1".into(), "lat".into()]),
            por_sqlite.leer("T", &["1".into(), "lat".into()]),
            "subindice numerico: lmdb y sqlite deben coincidir"
        );
        assert_eq!(
            por_lmdb.leer("T", &["BARCO".into()]),
            por_sqlite.leer("T", &["BARCO".into()]),
            "subindice cadena: lmdb y sqlite deben coincidir"
        );
        drop(por_lmdb);
        let _ = std::fs::remove_dir_all(&base);
    }
}
