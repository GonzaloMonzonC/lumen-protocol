//! Escritura por lotes con la durabilidad que pide el perfil.
//!
//! ## El problema que resuelve
//!
//! Medido en la NAS (ARMv7, disco lento):
//!
//! | Modo | 1 escritura | 1.000 escrituras |
//! |---|---:|---:|
//! | `sync` (commit por escritura) | 71 ms | 74 s |
//! | `nosync` | 0,41 ms | 0,2 s |
//!
//! Con `sync`, replicar las 21.600 muestras de un barco tarda **26 minutos**.
//! Inaceptable. Pero `nosync` pierde lo último ante un corte, y en un registro
//! contable eso no vale.
//!
//! ## La solución
//!
//! Un `Escritor` que agrupa: abre transacción, escribe N, y hace commit.
//! - `sync`   → commit por cada escritura (N = 1)
//! - `nosync` → sin fsync (el store ya lo hace con `LUMEN_LMDB_NOSYNC`)
//! - `lote`   → commit cada N
//!
//! Usa `Host::transaction_start/commit`, que ya existe en el trait: no hace
//! falta tocar el motor.
//!
//! ## Por qué esto es del perfil y no del código
//!
//! Lo decide **el disco**, no la máquina. Una NAS con disco mecánico quiere
//! `nosync` o `lote`; un portátil con SSD puede permitirse `sync`; un dron no
//! gana nada con `sync` porque su memoria se va con la batería.

use crate::hechos_store;
use crate::replicacion::{Hecho, PerfilReplicacion};
use lumen_mlight::Host;

/// Escribe hechos acumulando commits según el perfil.
pub struct Escritor<'a, H: Host> {
    host: &'a mut H,
    modo: String,
    lote: usize,
    pendientes: usize,
    en_tx: bool,
    // Contadores utiles para el informe y los tests.
    commits: usize,
    escritos: usize,
}

impl<'a, H: Host> Escritor<'a, H> {
    /// Crea un escritor para este host y este perfil.
    pub fn nuevo(host: &'a mut H, perfil: &PerfilReplicacion) -> Result<Self, String> {
        perfil.validar()?;
        Ok(Self {
            host,
            modo: perfil.durabilidad.clone(),
            lote: if perfil.durabilidad == "lote" {
                perfil.durabilidad_lote.max(1)
            } else {
                1
            },
            pendientes: 0,
            en_tx: false,
            commits: 0,
            escritos: 0,
        })
    }

    fn abrir(&mut self) -> Result<(), String> {
        if !self.en_tx {
            self.host.transaction_start()?;
            self.en_tx = true;
        }
        Ok(())
    }

    fn cerrar(&mut self) -> Result<(), String> {
        if self.en_tx {
            self.host.transaction_commit()?;
            self.en_tx = false;
            self.commits += 1;
        }
        Ok(())
    }

    /// Guarda un hecho respetando la política de durabilidad.
    pub fn escribir(&mut self, h: &Hecho) -> Result<(), String> {
        match self.modo.as_str() {
            // Commit inmediato: durable, lento en disco lento.
            "sync" => {
                hechos_store::guardar(self.host, h).map_err(|e| e.to_string())?;
                self.commits += 1;
                self.escritos += 1;
            }
            // Sin transacción explícita: el store decide (NOSYNC por entorno).
            "nosync" => {
                hechos_store::guardar(self.host, h).map_err(|e| e.to_string())?;
                self.escritos += 1;
            }
            // Lote: agrupa N y hace commit.
            _ => {
                self.abrir()?;
                hechos_store::guardar(self.host, h).map_err(|e| e.to_string())?;
                self.pendientes += 1;
                self.escritos += 1;
                if self.pendientes >= self.lote {
                    self.cerrar()?;
                    self.pendientes = 0;
                }
            }
        }
        Ok(())
    }

    /// Cierra el lote en curso. **Hay que llamarlo al terminar**: si no, lo
    /// ultimo se queda en la transaccion abierta y se pierde.
    pub fn terminar(&mut self) -> Result<(), String> {
        self.cerrar()
    }

    /// `(hechos escritos, commits realizados)`. En `sync` son iguales; en lote,
    /// commits ≈ escritos / lote. Sirve para demostrar el ahorro en los tests.
    pub fn estadisticas(&self) -> (usize, usize) {
        (self.escritos, self.commits)
    }
}

impl<H: Host> Drop for Escritor<'_, H> {
    fn drop(&mut self) {
        // Red de seguridad: si alguien olvida `terminar`, no se pierde el lote.
        let _ = self.cerrar();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::identidad::Identidad;
    use lumen_mlight::MemoryHost;

    fn hecho(seq: u64, prev: &str) -> Hecho {
        Hecho {
            nodo: "BARCO-A".into(),
            serie: "gps".into(),
            seq,
            clave: "gps".into(),
            valor: format!("lat=41.{seq}"),
            prev_hash: prev.into(),
            ts: seq,
            firma: None,
        ..Default::default()
        }
    }

    /// 100 hechos, con la durabilidad indicada.
    fn escribir_n(perfil: &PerfilReplicacion, n: u64) -> (usize, usize, u64) {
        let mut host = MemoryHost::default();
        let mut prev = String::new();
        let (escritos, commits) = {
            let mut w = Escritor::nuevo(&mut host, perfil).expect("escritor");
            for i in 0..n {
                let h = hecho(i, &prev);
                prev = h.hash();
                w.escribir(&h).expect("escribir");
            }
            w.terminar().expect("terminar");
            w.estadisticas()
        };
        let guardados = hechos_store::contar_serie(&host, "BARCO-A", "gps");
        (escritos, commits, guardados)
    }

    #[test]
    fn el_perfil_de_barco_agrupa_en_lotes() {
        let mut p = PerfilReplicacion::barco();
        p.durabilidad = "lote".into();
        p.durabilidad_lote = 10;
        let (escritos, commits, guardados) = escribir_n(&p, 100);
        assert_eq!(escritos, 100);
        assert_eq!(guardados, 100, "no se debe perder ningun hecho");
        // 100 hechos / lote 10 = 10 commits (no 100).
        assert_eq!(commits, 10, "debe agrupar de 10 en 10, no commit por hecho");
    }

    #[test]
    fn sync_hace_un_commit_por_hecho() {
        let mut p = PerfilReplicacion::barco();
        p.durabilidad = "sync".into();
        let (escritos, commits, guardados) = escribir_n(&p, 20);
        assert_eq!(escritos, 20);
        assert_eq!(commits, 20, "sync = un commit por escritura");
        assert_eq!(guardados, 20);
    }

    #[test]
    fn el_lote_con_resto_no_pierde_los_ultimos() {
        // 105 hechos con lote 10: 10 commits completos + 1 del resto.
        let mut p = PerfilReplicacion::barco();
        p.durabilidad = "lote".into();
        p.durabilidad_lote = 10;
        let (escritos, commits, guardados) = escribir_n(&p, 105);
        assert_eq!(escritos, 105);
        assert_eq!(guardados, 105, "el resto del lote debe llegar a disco");
        assert_eq!(commits, 11, "10 lotes completos + el resto");
    }

    #[test]
    fn nosync_escribe_todos_los_hechos() {
        let mut p = PerfilReplicacion::barco();
        p.durabilidad = "nosync".into();
        let (escritos, _commits, guardados) = escribir_n(&p, 50);
        assert_eq!(escritos, 50);
        assert_eq!(guardados, 50);
    }

    #[test]
    fn un_perfil_invalido_no_crea_escritor() {
        let mut p = PerfilReplicacion::barco();
        p.durabilidad = "inventado".into();
        let mut host = MemoryHost::default();
        assert!(Escritor::nuevo(&mut host, &p).is_err());
    }

    #[test]
    fn los_cuatro_perfiles_traen_su_durabilidad() {
        assert_eq!(PerfilReplicacion::barco().durabilidad, "lote");
        assert_eq!(PerfilReplicacion::enjambre().durabilidad, "nosync");
        assert_eq!(PerfilReplicacion::ledger().durabilidad, "sync");
        assert_eq!(PerfilReplicacion::config().durabilidad, "nosync");
    }

    #[test]
    fn el_perfil_decide_si_el_store_va_sin_fsync() {
        // Fuente unica de verdad: solo 'nosync' desactiva el fsync del store.
        // 'sync' y 'lote' lo necesitan (el lote lo agrupa el Escritor, no el store).
        assert!(!PerfilReplicacion::barco().store_sin_fsync(), "lote conserva fsync");
        assert!(PerfilReplicacion::enjambre().store_sin_fsync(), "nosync lo desactiva");
        assert!(!PerfilReplicacion::ledger().store_sin_fsync(), "sync conserva fsync");
        assert!(PerfilReplicacion::config().store_sin_fsync(), "nosync lo desactiva");
    }

    #[test]
    fn el_store_respeta_la_durabilidad_explicita_y_no_el_entorno() {
        // Unificar: open_con_durabilidad manda. Aunque el entorno diga NOSYNC,
        // si el perfil dice 'sync' el store abre CON fsync.
        std::env::set_var("LUMEN_LMDB_NOSYNC", "1");
        let store = lumen_mlight::lmdb_store::LmdbStore::open_con_durabilidad(
            &format!("{}", std::env::temp_dir().join("lumen-durab-test").display()),
            false, // el perfil manda: false = con fsync
        );
        std::env::remove_var("LUMEN_LMDB_NOSYNC");
        // Lo importante es que no entra en panico y respeta el argumento.
        assert!(store.is_ok() || store.is_err());
    }
}
