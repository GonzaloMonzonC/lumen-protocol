//! Digest recalculable — detectar que dos nodos materializaron estados distintos.
//!
//! ## Por qué existe esto
//!
//! Smith, en la revisión del diseño:
//!
//! > *"Poder recalcular desde cero y comparar digest entre réplicas. **Si no
//! > puedes recalcular, no tienes CRDT, tienes gossip con esperanza.**"*
//!
//! El problema que resuelve: aunque la función de convergencia sea pura, el
//! código que la **aplica** puede tener un bug. Un aplicador malo produce
//! divergencia permanente y silenciosa: dos nodos con los mismos hechos y estados
//! distintos.
//!
//! Con un digest, se detecta en el acto: *"tú dices A1B2, yo digo C3D4"*.
//!
//! ## Cómo se consigue que sea determinista
//!
//! Tres reglas, y las tres importan:
//!
//! 1. **Se ordenan los hechos antes de derivar.** El orden de llegada no puede
//!    cambiar el resultado. Se ordena por `(nodo, serie, seq, instance_id)`.
//! 2. **Se usa el ÚLTIMO hecho por clave, según ese orden.** No el último que
//!    llegó: el último según el orden canónico.
//! 3. **El digest incluye el tipo**, para que un cambio de regla de convergencia
//!    cambie el digest.
//!
//! ## Lo que NO resuelve
//!
//! El digest detecta divergencia **entre nodos con los mismos hechos**. Si dos
//! nodos tienen **hechos distintos** (una partición sin reconverger), tendrán
//! digests distintos y eso es correcto: no es un bug, es que no han fusionado.
//! Para distinguir un caso del otro hace falta comparar también el conjunto de
//! hechos — y eso lo hará la reconvergencia.

use crate::cadena::sha256_hex;
use crate::replicacion::{Hecho, TipoHecho};
use std::collections::BTreeMap;

/// Estado derivado de un conjunto de hechos.
///
/// `clave -> (valor, tipo, quién lo escribió, cuándo)`. Se usa `BTreeMap` para
/// que el recorrido sea **siempre el mismo orden**: si fuera un `HashMap`, el
/// digest cambiaría entre ejecuciones.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Estado {
    pub valores: BTreeMap<String, EntradaEstado>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntradaEstado {
    pub valor: String,
    pub tipo: TipoHecho,
    /// Nodo que escribió el hecho vigente.
    pub nodo: String,
    /// `seq` del hecho vigente dentro de su serie.
    pub seq: u64,
    /// Instancia, para distinguir ramas.
    pub instancia: String,
}

impl Estado {
    pub fn vacio() -> Self {
        Self::default()
    }

    pub fn obtener(&self, clave: &str) -> Option<&EntradaEstado> {
        self.valores.get(clave)
    }

    pub fn len(&self) -> usize {
        self.valores.len()
    }

    pub fn esta_vacio(&self) -> bool {
        self.valores.is_empty()
    }

    /// Digest del estado. Es lo que se compara entre réplicas.
    pub fn digest(&self) -> String {
        let mut lineas = Vec::with_capacity(self.valores.len());
        // BTreeMap ya recorre en orden de clave: determinista por construcción.
        for (clave, e) in &self.valores {
            lineas.push(format!(
                "{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}",
                clave,
                e.valor,
                e.tipo.etiqueta(),
                e.nodo,
                e.seq,
                e.instancia
            ));
        }
        sha256_hex(lineas.join("\x1e").as_bytes())
    }
}

/// Deriva el estado de un conjunto de hechos.
///
/// **Función pura**: el mismo conjunto, en cualquier orden, da el mismo estado.
///
/// ## La regla de convergencia
///
/// Para cada clave gana el hecho con `(seq, instance_id)` mayor **dentro del
/// orden canónico de la serie**. No se usa `ts` (relojes no sincronizados) ni el
/// orden de llegada (no es determinista).
///
/// Esto es deliberadamente simple. La regla completa del diseño (epoch, hash,
/// conflicto explícito) se construye **encima** de esto; aquí lo que se prueba es
/// que la derivación es determinista y que el digest la detecta.
pub fn derivar(hechos: &[Hecho]) -> Estado {
    // 1. Orden canónico: no depende del orden de llegada.
    let mut ordenados: Vec<&Hecho> = hechos.iter().collect();
    ordenados.sort_by(|a, b| {
        (a.nodo.as_str(), a.serie.as_str(), a.seq, a.instance_id.as_str())
            .cmp(&(b.nodo.as_str(), b.serie.as_str(), b.seq, b.instance_id.as_str()))
    });

    // 2. El último por clave en ese orden gana.
    let mut estado = Estado::vacio();
    for h in ordenados {
        if h.valor.is_empty() {
            // Borrado: valor vacío quita la clave.
            estado.valores.remove(&h.clave);
            continue;
        }
        let nuevo = EntradaEstado {
            valor: h.valor.clone(),
            tipo: h.tipo,
            nodo: h.nodo.clone(),
            seq: h.seq,
            instancia: h.instance_id.clone(),
        };
        // Al recorrer en orden canónico, el último que se escribe es el vigente.
        estado.valores.insert(h.clave.clone(), nuevo);
    }
    estado
}

/// Compara dos réplicas y dice si han divergido.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Diagnostico {
    /// Mismo digest: las dos calcularon lo mismo.
    Iguales(String),
    /// Digest distinto: hay divergencia. Se dice **qué claves** difieren, no solo
    /// que difieren: sin el detalle, un bug es indepurable.
    Divergen {
        digest_a: String,
        digest_b: String,
        solo_en_a: Vec<String>,
        solo_en_b: Vec<String>,
        distintos: Vec<String>,
    },
}

impl Diagnostico {
    pub fn es_igual(&self) -> bool {
        matches!(self, Diagnostico::Iguales(_))
    }
}

/// Compara dos estados clave por clave.
pub fn comparar(a: &Estado, b: &Estado) -> Diagnostico {
    let da = a.digest();
    let db = b.digest();
    if da == db {
        return Diagnostico::Iguales(da);
    }

    let mut solo_en_a = Vec::new();
    let mut solo_en_b = Vec::new();
    let mut distintos = Vec::new();

    for (clave, ea) in &a.valores {
        match b.valores.get(clave) {
            None => solo_en_a.push(clave.clone()),
            Some(eb) if ea != eb => distintos.push(clave.clone()),
            _ => {}
        }
    }
    for clave in b.valores.keys() {
        if !a.valores.contains_key(clave) {
            solo_en_b.push(clave.clone());
        }
    }

    Diagnostico::Divergen { digest_a: da, digest_b: db, solo_en_a, solo_en_b, distintos }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn h(nodo: &str, clave: &str, valor: &str, seq: u64) -> Hecho {
        Hecho::v3(nodo, "s", seq, "inst-A", 0, clave, valor, "", 100, TipoHecho::Idempotente)
    }

    #[test]
    fn el_orden_de_llegada_no_cambia_el_digest() {
        // LA PROPIEDAD CLAVE: dos nodos que reciben los mismos hechos en orden
        // distinto deben calcular el mismo digest.
        let hechos = vec![h("A", "x", "1", 0), h("A", "y", "2", 1), h("A", "x", "3", 2)];

        let mut al_reves = hechos.clone();
        al_reves.reverse();
        let mut mezclados = vec![hechos[1].clone(), hechos[2].clone(), hechos[0].clone()];

        let d1 = derivar(&hechos).digest();
        let d2 = derivar(&al_reves).digest();
        let d3 = derivar(&mezclados).digest();

        assert_eq!(d1, d2, "orden inverso debe dar el mismo digest");
        assert_eq!(d1, d3, "orden mezclado debe dar el mismo digest");
        mezclados.clear();
    }

    #[test]
    fn gana_el_ultimo_por_orden_canonico() {
        let hechos = vec![h("A", "x", "primero", 0), h("A", "x", "ultimo", 5)];
        let e = derivar(&hechos);
        assert_eq!(e.obtener("x").map(|v| v.valor.as_str()), Some("ultimo"));
    }

    #[test]
    fn un_valor_vacio_borra_la_clave() {
        let hechos = vec![h("A", "x", "algo", 0), h("A", "x", "", 1)];
        let e = derivar(&hechos);
        assert!(e.obtener("x").is_none(), "valor vacio debe borrar");
    }

    #[test]
    fn el_mismo_conjunto_da_siempre_el_mismo_digest() {
        let hechos = vec![h("A", "x", "1", 0), h("B", "y", "2", 0)];
        assert_eq!(derivar(&hechos).digest(), derivar(&hechos).digest());
    }

    #[test]
    fn un_hecho_distinto_cambia_el_digest() {
        let a = vec![h("A", "x", "1", 0)];
        let b = vec![h("A", "x", "2", 0)];
        assert_ne!(derivar(&a).digest(), derivar(&b).digest());
    }

    #[test]
    fn comparar_detecta_que_claves_difieren() {
        let a = derivar(&vec![h("A", "x", "1", 0), h("A", "y", "2", 0)]);
        let b = derivar(&vec![h("A", "x", "9", 0), h("A", "z", "3", 0)]);

        match comparar(&a, &b) {
            Diagnostico::Divergen { solo_en_a, solo_en_b, distintos, .. } => {
                assert_eq!(solo_en_a, vec!["y".to_string()]);
                assert_eq!(solo_en_b, vec!["z".to_string()]);
                assert_eq!(distintos, vec!["x".to_string()]);
            }
            _ => panic!("deberia divergir"),
        }
    }

    #[test]
    fn dos_replicas_del_mismo_conjunto_no_divergen() {
        let hechos = vec![h("A", "x", "1", 0), h("B", "y", "2", 0)];
        let a = derivar(&hechos);
        let mut rev = hechos.clone();
        rev.reverse();
        let b = derivar(&rev);
        assert!(comparar(&a, &b).es_igual());
    }

    #[test]
    fn el_tipo_afecta_al_digest() {
        // Un cambio de regla de convergencia debe verse en el digest.
        let mut a = h("A", "x", "1", 0);
        a.tipo = TipoHecho::Idempotente;
        let mut b = h("A", "x", "1", 0);
        b.tipo = TipoHecho::ConRevision;
        assert_ne!(derivar(&[a]).digest(), derivar(&[b]).digest());
    }

    #[test]
    fn estado_vacio_tiene_digest_estable() {
        let e = Estado::vacio();
        assert!(e.esta_vacio());
        assert_eq!(e.digest(), Estado::vacio().digest());
    }
}
