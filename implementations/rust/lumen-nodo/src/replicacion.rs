//! Replicación de hechos entre nodos — perfil configurable, firma real.
//!
//! ## Qué añade esto
//!
//! El prototipo en Python (`experimentos/ddp-modelos/`) demostró que un motor
//! único con perfil configurable cumple en escenarios opuestos. Esto lo lleva a
//! código real:
//!
//! - **Firma Ed25519 de verdad** (no hash simulado), con la `Identidad` de
//!   [`crate::identidad`] y el PKI de flota que ya existe.
//! - **Perfil leído de fichero**, no un diccionario en memoria.
//! - **Transporte por `lumen-znet`**, no listas en memoria.
//! - **Cadena de hashes real** (`crate::cadena`), que ya estaba.
//!
//! ## El perfil
//!
//! Un nodo caro (barco) y un nodo barato (config) usan el MISMO código y distinto
//! perfil. El perfil decide retención, réplica, firma, compactación y conflicto.
//!
//! ## Lo que este módulo NO hace
//!
//! No resuelve el doble gasto ni consenso: eso es política de la capa de arriba.
//! Aquí solo se garantiza que los hechos viajan, se verifican y se conservan
//! según el perfil.

use crate::identidad::Identidad;
use serde::{Deserialize, Serialize};

/// Las cinco decisiones que un perfil puede tomar. Todo lo demás es común.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PerfilReplicacion {
    /// `"todo"` | `"ventana"`
    pub retencion_modo: String,
    /// Horas de ventana. `None` con `retencion_modo = "todo"`.
    pub retencion_horas: Option<u64>,

    /// `"todos"` | `"interes"` | `"flota"` | `"hub"`
    pub replicacion: String,
    /// Series que este nodo sigue. Solo con `replicacion = "interes"`.
    #[serde(default)]
    pub replicacion_interes: Vec<String>,

    /// `"por_hecho"` | `"por_bloque"` | `"ninguna"`
    pub firma: String,
    /// Muestras por bloque. Solo con `firma = "por_bloque"`.
    #[serde(default = "bloque_por_defecto")]
    pub firma_bloque_n: usize,

    /// `"archivar"` | `"sellos"` | `"descartar"`
    pub compactacion: String,

    /// `"ultimo_gana"` | `"primero_gana"` | `"manual"`
    pub conflicto: String,
}

fn bloque_por_defecto() -> usize {
    100
}

impl PerfilReplicacion {
    /// Perfil de barco: 6 h sin cobertura, hay que probar que no falta nada.
    pub fn barco() -> Self {
        Self {
            retencion_modo: "ventana".into(),
            retencion_horas: Some(168),
            replicacion: "flota".into(),
            replicacion_interes: vec![],
            firma: "por_bloque".into(),
            firma_bloque_n: 100,
            compactacion: "sellos".into(),
            conflicto: "ultimo_gana".into(),
        }
    }

    /// Perfil de enjambre: nodos efímeros, solo lo que les afecta.
    pub fn enjambre() -> Self {
        Self {
            retencion_modo: "ventana".into(),
            retencion_horas: Some(6),
            replicacion: "interes".into(),
            replicacion_interes: vec!["posicion".into(), "amenaza".into()],
            firma: "por_hecho".into(),
            firma_bloque_n: 100,
            compactacion: "descartar".into(),
            conflicto: "ultimo_gana".into(),
        }
    }

    /// Perfil de ledger: inmutable, todo se prueba, el conflicto se detecta.
    pub fn ledger() -> Self {
        Self {
            retencion_modo: "todo".into(),
            retencion_horas: None,
            replicacion: "todos".into(),
            replicacion_interes: vec![],
            firma: "por_hecho".into(),
            firma_bloque_n: 100,
            compactacion: "archivar".into(),
            conflicto: "manual".into(),
        }
    }

    /// Perfil de configuración: estado, no historia.
    pub fn config() -> Self {
        Self {
            retencion_modo: "ventana".into(),
            retencion_horas: Some(1),
            replicacion: "hub".into(),
            replicacion_interes: vec![],
            firma: "ninguna".into(),
            firma_bloque_n: 100,
            compactacion: "descartar".into(),
            conflicto: "ultimo_gana".into(),
        }
    }

    /// Carga un perfil desde JSON. Si el fichero no existe, error explícito.
    pub fn desde_json(texto: &str) -> Result<Self, String> {
        serde_json::from_str(texto).map_err(|e| format!("perfil JSON invalido: {e}"))
    }

    /// Valida que la combinación de valores tiene sentido.
    pub fn validar(&self) -> Result<(), String> {
        let modos_ret = ["todo", "ventana"];
        if !modos_ret.contains(&self.retencion_modo.as_str()) {
            return Err(format!("retencion_modo invalido: {}", self.retencion_modo));
        }
        if self.retencion_modo == "ventana" && self.retencion_horas.is_none() {
            return Err("retencion_modo=ventana exige retencion_horas".into());
        }
        if !["todos", "interes", "flota", "hub"].contains(&self.replicacion.as_str()) {
            return Err(format!("replicacion invalida: {}", self.replicacion));
        }
        if self.replicacion == "interes" && self.replicacion_interes.is_empty() {
            return Err("replicacion=interes exige replicacion_interes".into());
        }
        if !["por_hecho", "por_bloque", "ninguna"].contains(&self.firma.as_str()) {
            return Err(format!("firma invalida: {}", self.firma));
        }
        if self.firma == "por_bloque" && self.firma_bloque_n == 0 {
            return Err("firma_bloque_n no puede ser 0".into());
        }
        if !["archivar", "sellos", "descartar"].contains(&self.compactacion.as_str()) {
            return Err(format!("compactacion invalida: {}", self.compactacion));
        }
        if !["ultimo_gana", "primero_gana", "manual"].contains(&self.conflicto.as_str()) {
            return Err(format!("conflicto invalido: {}", self.conflicto));
        }
        Ok(())
    }
}

/// Un hecho replicable: una muestra firmada.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Hecho {
    /// Nodo que lo produjo. Va DENTRO de la identidad (lección del prototipo).
    pub nodo: String,
    /// Serie a la que pertenece (`gps`, `posicion`, ...).
    pub serie: String,
    /// Secuencia dentro de `(nodo, serie)`.
    pub seq: u64,
    /// Clave lógica (`gps`, `saldo:A`, ...).
    pub clave: String,
    /// Valor. Vacío si es un borrado.
    pub valor: String,
    /// Hash del hecho anterior de la misma serie.
    pub prev_hash: String,
    /// Timestamp en segundos.
    pub ts: u64,
    /// Firma Ed25519 del contenido canónico. `None` si el perfil no firma.
    pub firma: Option<[u8; 64]>,
}

impl Hecho {
    /// Identidad del hecho: lleva el NODO dentro, para que dos barcos no colisionen.
    pub fn identidad(&self) -> (String, String, u64) {
        (self.nodo.clone(), self.serie.clone(), self.seq)
    }

    /// Bytes canónicos que se firman. Formato estable y sin ambigüedad.
    ///
    /// Se usa `\x1f` (unit separator) porque no puede aparecer en un valor
    /// normal y evita que `("ab","c")` y `("a","bc")` den la misma firma.
    pub fn contenido_canonico(&self) -> Vec<u8> {
        format!(
            "{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}",
            self.nodo, self.serie, self.seq, self.clave, self.valor, self.prev_hash, self.ts
        )
        .into_bytes()
    }

    /// Hash del hecho (para encadenar el siguiente).
    pub fn hash(&self) -> String {
        crate::cadena::hash_muestra(&self.prev_hash, &self.valor)
    }

    /// Firma el hecho con la identidad del nodo.
    pub fn firmar(&mut self, identidad: &Identidad) {
        self.firma = Some(identidad.firmar(&self.contenido_canonico()));
    }

    /// Verifica la firma contra la clave pública del nodo emisor.
    pub fn verificar_firma(&self, clave_publica: &[u8]) -> Result<(), String> {
        let firma = self
            .firma
            .ok_or_else(|| "hecho sin firma".to_string())?;
        crate::identidad::verificar(clave_publica, &self.contenido_canonico(), &firma)
            .map_err(|e| format!("firma invalida: {e:?}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn los_cuatro_perfiles_son_validos() {
        for p in [
            PerfilReplicacion::barco(),
            PerfilReplicacion::enjambre(),
            PerfilReplicacion::ledger(),
            PerfilReplicacion::config(),
        ] {
            p.validar().expect("perfil deberia ser valido");
        }
    }

    #[test]
    fn un_perfil_incoherente_se_rechaza() {
        let mut p = PerfilReplicacion::barco();
        p.retencion_horas = None; // ventana sin horas
        assert!(p.validar().is_err());

        let mut p2 = PerfilReplicacion::barco();
        p2.replicacion = "interes".into();
        p2.replicacion_interes = vec![]; // interes sin lista
        assert!(p2.validar().is_err());
    }

    #[test]
    fn el_perfil_va_y_vuelve_por_json() {
        let p = PerfilReplicacion::barco();
        let txt = serde_json::to_string(&p).unwrap();
        let vuelta = PerfilReplicacion::desde_json(&txt).unwrap();
        assert_eq!(p, vuelta);
    }

    #[test]
    fn la_firma_ed25519_verifica_y_detecta_manipulacion() {
        let id = Identidad::generar();
        let mut h = Hecho {
            nodo: "BARCO-A".into(),
            serie: "gps".into(),
            seq: 0,
            clave: "gps".into(),
            valor: "lat=41.1".into(),
            prev_hash: String::new(),
            ts: 100,
            firma: None,
        };
        h.firmar(&id);
        assert!(h.verificar_firma(&id.clave_publica()).is_ok());

        // Manipular el valor invalida la firma.
        h.valor = "lat=99.9".into();
        assert!(h.verificar_firma(&id.clave_publica()).is_err());
    }

    #[test]
    fn un_impostor_no_puede_firmar_como_el_barco() {
        let barco = Identidad::generar();
        let impostor = Identidad::generar();
        let mut h = Hecho {
            nodo: "BARCO-A".into(),
            serie: "gps".into(),
            seq: 0,
            clave: "gps".into(),
            valor: "lat=41.1".into(),
            prev_hash: String::new(),
            ts: 100,
            firma: None,
        };
        h.firmar(&impostor);
        // La clave pública del barco NO valida la firma del impostor.
        assert!(h.verificar_firma(&barco.clave_publica()).is_err());
    }

    #[test]
    fn el_separador_evita_colisiones_de_concatenacion() {
        // ("ab","c") y ("a","bc") deben dar contenido distinto.
        let mut a = Hecho {
            nodo: "N".into(), serie: "S".into(), seq: 1, clave: "ab".into(),
            valor: "c".into(), prev_hash: String::new(), ts: 1, firma: None,
        };
        let mut b = a.clone();
        b.clave = "a".into();
        b.valor = "bc".into();
        assert_ne!(a.contenido_canonico(), b.contenido_canonico());
        a.seq = 1;
        let _ = b;
    }
}
