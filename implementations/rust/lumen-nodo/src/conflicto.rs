//! Hecho de conflicto — la evidencia firmada de que dos ramas chocaron.
//!
//! ## Por qué existe
//!
//! Smith, en la revisión del diseño:
//!
//! > *"Sin hecho de conflicto explícito, **la unión es una pérdida silenciosa**."*
//!
//! El sistema ya **detecta** conflictos (`hechos_wire::Conflicto`) y las dos ramas
//! coexisten. Pero esa detección vivía **solo en memoria**, en un `Vec` del
//! resumen de recepción: al reiniciar el nodo, **se perdía**.
//!
//! Un conflicto que se olvida al reiniciar es casi tan malo como un conflicto que
//! se descarta: el operador ya no puede auditar qué pasó.
//!
//! ## Qué es un hecho de conflicto
//!
//! Un hecho normal — firmado, encadenado, en su propia serie `^conflictos` — que
//! dice:
//!
//! - qué dos ramas chocaron (instancias y hashes)
//! - qué epoch tenía cada una
//! - por qué no se pudieron fusionar solas
//!
//! ## Lo que NO hace
//!
//! **No resuelve el conflicto.** No elige ganador. Solo deja constancia firmada
//! de que existe, para que un operador decida. Eso es exactamente lo que pedía el
//! diseño: *"conflicto semántico = hecho explícito + cuarentena, jamás pérdida
//! silenciosa"*.
//!
//! La resolución (si la hay) será **otro hecho** que lo referencia. Nada se
//! reescribe.

use crate::hechos_wire::Conflicto;
use crate::replicacion::{Hecho, TipoHecho};

/// Serie donde viven los hechos de conflicto de un nodo.
pub const SERIE_CONFLICTOS: &str = "conflictos";

/// Motivo por el que un conflicto no se pudo resolver solo.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MotivoConflicto {
    /// Dos ramas escribieron sobre la misma clave con valores distintos.
    ///
    /// La unión de hechos no lo arregla: hay dos valores y ninguno es "más
    /// verdadero" que el otro por sí mismo.
    ValoresIncompatibles,
    /// Dos ramas reservaron **el mismo recurso exclusivo**.
    ///
    /// Smith fue explícito: *"dos ramas reservan el mismo volumen de aire →
    /// converge perfectamente a un estado con doble asignación"*. Converger no
    /// es corregir.
    RecursoDisputado,
    /// Un hecho de seguridad (`ConRevision`) choca con otro.
    ///
    /// Nunca se resuelve por `ultimo_gana`: un viraje evasivo ya ejecutado no se
    /// puede reescribir.
    DecisionDeSeguridad,
    /// El epoch de una rama saltó más de lo permitido.
    EpochSospechoso,
}

impl MotivoConflicto {
    pub fn etiqueta(&self) -> &'static str {
        match self {
            MotivoConflicto::ValoresIncompatibles => "valores-incompatibles",
            MotivoConflicto::RecursoDisputado => "recurso-disputado",
            MotivoConflicto::DecisionDeSeguridad => "decision-seguridad",
            MotivoConflicto::EpochSospechoso => "epoch-sospechoso",
        }
    }

    /// ¿Requiere decisión humana, o una regla automática puede resolverlo?
    ///
    /// Solo `ValoresIncompatibles` **podría** resolverse solo con una regla
    /// declarada. Los otros tres **no**: afectan a recursos o a seguridad.
    pub fn requiere_operador(&self) -> bool {
        !matches!(self, MotivoConflicto::ValoresIncompatibles)
    }
}

/// Construye el hecho que deja constancia del conflicto.
///
/// El valor del hecho lleva toda la evidencia en texto, para que se pueda leer
/// sin herramientas: quien consulte la serie `conflictos` ve directamente qué
/// pasó.
pub fn hecho_de_conflicto(
    nodo: &str,
    instancia: &str,
    epoch: u64,
    seq: u64,
    prev_hash: &str,
    ts: u64,
    c: &Conflicto,
    motivo: MotivoConflicto,
) -> Hecho {
    // La clave identifica el conflicto: nodo, serie y posición.
    let clave = format!("{}:{}:{}", c.nodo, c.serie, c.seq);

    // El valor es legible a propósito: esto lo va a leer un operador.
    let valor = format!(
        "motivo={}; clave={}; rama_a=inst:{} hash:{} epoch:{}; rama_b=inst:{} hash:{} epoch:{}; pendiente=operador:{}",
        motivo.etiqueta(),
        clave,
        c.instance_existente,
        c.hash_existente,
        c.epoch_existente,
        c.instance_nueva,
        c.hash_nuevo,
        c.epoch_nuevo,
        motivo.requiere_operador()
    );

    Hecho::v3(
        nodo,
        SERIE_CONFLICTOS,
        seq,
        instancia,
        epoch,
        &clave,
        &valor,
        prev_hash,
        ts,
        // Un conflicto es por definición algo que necesita revisión.
        TipoHecho::ConRevision,
    )
}

/// Deduce el motivo a partir de la evidencia y del tipo de hecho enfrentado.
pub fn motivo_de(c: &Conflicto, tipo: TipoHecho) -> MotivoConflicto {
    if c.epoch_nuevo != c.epoch_existente {
        // Epoch distinto en la misma posición: puede ser reinstalación legítima
        // o un salto sospechoso. Requiere revisión en cualquier caso.
        return MotivoConflicto::EpochSospechoso;
    }
    match tipo {
        TipoHecho::RecursoExclusivo => MotivoConflicto::RecursoDisputado,
        TipoHecho::ConRevision => MotivoConflicto::DecisionDeSeguridad,
        _ => MotivoConflicto::ValoresIncompatibles,
    }
}

/// Extrae el motivo de un hecho de conflicto ya guardado.
pub fn motivo_de_hecho(h: &Hecho) -> Option<MotivoConflicto> {
    if h.serie != SERIE_CONFLICTOS {
        return None;
    }
    let m = h.valor.strip_prefix("motivo=")?;
    let etiqueta = m.split(';').next()?;
    match etiqueta {
        "valores-incompatibles" => Some(MotivoConflicto::ValoresIncompatibles),
        "recurso-disputado" => Some(MotivoConflicto::RecursoDisputado),
        "decision-seguridad" => Some(MotivoConflicto::DecisionDeSeguridad),
        "epoch-sospechoso" => Some(MotivoConflicto::EpochSospechoso),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn conflicto() -> Conflicto {
        Conflicto {
            nodo: "DRON-A".into(),
            serie: "reserva".into(),
            seq: 7,
            instance_existente: "inst-1".into(),
            instance_nueva: "inst-2".into(),
            hash_existente: "aa".repeat(32),
            hash_nuevo: "bb".repeat(32),
            epoch_existente: 0,
            epoch_nuevo: 0,
        }
    }

    #[test]
    fn el_hecho_de_conflicto_lleva_toda_la_evidencia() {
        let c = conflicto();
        let h = hecho_de_conflicto(
            "NODO-1", "inst-hub", 0, 0, "", 1000, &c,
            MotivoConflicto::RecursoDisputado,
        );
        let v = &h.valor;
        assert!(v.contains("motivo=recurso-disputado"));
        assert!(v.contains("DRON-A:reserva:7"));
        assert!(v.contains(&c.hash_existente));
        assert!(v.contains(&c.hash_nuevo));
        assert!(v.contains("inst-1") && v.contains("inst-2"));
        assert!(v.contains("pendiente=operador:true"));
    }

    #[test]
    fn un_conflicto_de_recurso_no_se_resuelve_solo() {
        assert!(MotivoConflicto::RecursoDisputado.requiere_operador());
        assert!(MotivoConflicto::DecisionDeSeguridad.requiere_operador());
        assert!(MotivoConflicto::EpochSospechoso.requiere_operador());
        // El unico que podria tener regla automatica.
        assert!(!MotivoConflicto::ValoresIncompatibles.requiere_operador());
    }

    #[test]
    fn el_tipo_marca_el_motivo() {
        let c = conflicto();
        assert_eq!(
            motivo_de(&c, TipoHecho::RecursoExclusivo),
            MotivoConflicto::RecursoDisputado
        );
        assert_eq!(
            motivo_de(&c, TipoHecho::ConRevision),
            MotivoConflicto::DecisionDeSeguridad
        );
        assert_eq!(
            motivo_de(&c, TipoHecho::Idempotente),
            MotivoConflicto::ValoresIncompatibles
        );
    }

    #[test]
    fn un_epoch_distinto_se_marca_sospechoso() {
        let mut c = conflicto();
        c.epoch_nuevo = 5;
        assert_eq!(
            motivo_de(&c, TipoHecho::Idempotente),
            MotivoConflicto::EpochSospechoso
        );
    }

    #[test]
    fn el_motivo_se_puede_releer_del_hecho() {
        for m in [
            MotivoConflicto::ValoresIncompatibles,
            MotivoConflicto::RecursoDisputado,
            MotivoConflicto::DecisionDeSeguridad,
            MotivoConflicto::EpochSospechoso,
        ] {
            let h = hecho_de_conflicto("N", "i", 0, 0, "", 1, &conflicto(), m);
            assert_eq!(motivo_de_hecho(&h), Some(m), "debe releerse {m:?}");
        }
    }

    #[test]
    fn un_hecho_normal_no_es_un_conflicto() {
        let h = Hecho::v3("N", "gps", 0, "i", 0, "k", "v", "", 1, TipoHecho::Idempotente);
        assert!(motivo_de_hecho(&h).is_none());
    }

    #[test]
    fn el_hecho_de_conflicto_es_de_revision() {
        // Nunca debe converger solo: es un aviso, no una decision.
        let h = hecho_de_conflicto("N", "i", 0, 0, "", 1, &conflicto(),
            MotivoConflicto::RecursoDisputado);
        assert_eq!(h.tipo, TipoHecho::ConRevision);
        assert!(!h.tipo.converge_solo());
        assert_eq!(h.serie, SERIE_CONFLICTOS);
    }
}
