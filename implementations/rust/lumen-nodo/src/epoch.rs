//! Cadena de custodia del epoch — impide que cualquiera suba el epoch.
//!
//! ## El agujero que cierra
//!
//! Con `instance_id` y `epoch` se puede distinguir una reinstalación de una
//! suplantación. Pero sin control del salto, **cualquiera con la clave del
//! barco puede declarar `epoch = 999999`** y ganar siempre en la política
//! `ultimo_gana` o en cualquier comparación por epoch.
//!
//! La clave del barco ya es poderosa (puede firmar hechos), pero el epoch es
//! **el orden entre historias**. Dejarlo libre significa que el orden lo decide
//! quien grita más alto.
//!
//! ## La regla
//!
//! Cada salto de epoch va firmado **por la clave del propio barco sobre el
//! epoch anterior**. Es una cadena:
//!
//! ```text
//! E0 ──firma(E0)──▶ E1 ──firma(E1)──▶ E2 ──firma(E2)──▶ E3
//! ```
//!
//! Para estar en `E3` hay que poder presentar la cadena completa desde un epoch
//! que el receptor ya conozca. **No basta con tener la clave: hay que demostrar
//! continuidad.**
//!
//! ## Qué NO resuelve
//!
//! Si se pierde la clave, no se puede firmar el salto. Eso es recuperación de
//! flota (la raíz del armador), y **está fuera de este módulo a propósito**: no
//! queremos que un mecanismo automático pueda saltarse la custodia.
//!
//! ## Por qué esto no es consenso
//!
//! No hay votación ni quórum: es una **cadena de firmas verificable**. Un nodo
//! puede comprobar por sí solo si un epoch es legítimo, sin hablar con nadie.
//! Eso es justo lo que un barco sin cobertura necesita.

use crate::identidad::{ErrorIdentidad, Identidad};

/// Un salto de epoch, firmado por el epoch anterior.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SaltoEpoch {
    /// Epoch de origen.
    pub desde: u64,
    /// Epoch de destino. Debe ser `desde + 1`.
    pub hacia: u64,
    /// `instance_id` del escritor que hace el salto.
    pub instancia: String,
    /// Firma del mensaje canónico con la clave del barco.
    pub firma: String,
}

/// El salto solo puede ser de uno en uno.
///
/// Permitir saltos de N abre la puerta a "estaba en el epoch 3 y ahora en el
/// 1000": si hay que firmar cada paso, no se puede inventar un salto grande sin
/// la cadena entera.
pub const SALTO_MAXIMO: u64 = 1;

impl SaltoEpoch {
    /// Mensaje canónico que se firma.
    ///
    /// Lleva la instancia dentro para que un salto no se pueda reutilizar
    /// cambiando de nodo, y separadores `\x1f` para que no haya ambigüedad de
    /// concatenación (misma lección que en el hecho).
    pub fn mensaje_canonico(desde: u64, hacia: u64, instancia: &str) -> Vec<u8> {
        format!("LUMEN-EPOCH/v1\x1f{desde}\x1f{hacia}\x1f{instancia}").into_bytes()
    }

    /// Crea el salto firmándolo con la identidad del barco.
    pub fn crear(
        desde: u64,
        hacia: u64,
        instancia: &str,
        id: &Identidad,
    ) -> Result<Self, String> {
        if hacia != desde + SALTO_MAXIMO {
            return Err(format!(
                "salto invalido: de {desde} a {hacia} (maximo +{SALTO_MAXIMO})"
            ));
        }
        let msg = Self::mensaje_canonico(desde, hacia, instancia);
        Ok(Self {
            desde,
            hacia,
            instancia: instancia.to_string(),
            firma: id.firmar_hex(&msg),
        })
    }

    /// Verifica la firma con la clave pública del barco.
    pub fn verificar(&self, clave_publica_hex: &str) -> Result<(), ErrorIdentidad> {
        let msg = Self::mensaje_canonico(self.desde, self.hacia, &self.instancia);
        crate::identidad::verificar_hex(clave_publica_hex, &msg, &self.firma)
    }

    /// Serializa a `desde|hacia|instancia|firma` (legible en M).
    pub fn a_texto(&self) -> String {
        format!("{}|{}|{}|{}", self.desde, self.hacia, self.instancia, self.firma)
    }

    /// Parsea el texto.
    pub fn desde_texto(texto: &str) -> Option<Self> {
        let c: Vec<&str> = texto.split('|').collect();
        if c.len() != 4 {
            return None;
        }
        Some(Self {
            desde: c[0].parse().ok()?,
            hacia: c[1].parse().ok()?,
            instancia: c[2].to_string(),
            firma: c[3].to_string(),
        })
    }
}

/// Resultado de comprobar si un epoch es alcanzable desde uno conocido.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Custodia {
    /// El epoch es el mismo, o se llega con la cadena presentada.
    Valido,
    /// Se llega, pero faltan saltos: hay un hueco en la cadena.
    FaltanSaltos { desde: u64, hacia: u64 },
    /// Un salto no verifica con la clave del barco.
    FirmaInvalida { desde: u64, hacia: u64 },
    /// Un salto salta más de uno.
    SaltoDemasiadoGrande { desde: u64, hacia: u64 },
    /// El epoch de destino es anterior al conocido: retroceso.
    Retroceso { conocido: u64, pretendido: u64 },
}

impl Custodia {
    pub fn es_valido(&self) -> bool {
        matches!(self, Custodia::Valido)
    }
}

/// Comprueba que se puede llegar de `epoch_conocido` a `epoch_pretendido`
/// usando la cadena de saltos presentada.
///
/// La cadena puede venir desordenada: se ordena por `desde`.
pub fn verificar_cadena(
    epoch_conocido: u64,
    epoch_pretendido: u64,
    saltos: &[SaltoEpoch],
    clave_publica_hex: &str,
) -> Custodia {
    if epoch_pretendido < epoch_conocido {
        return Custodia::Retroceso {
            conocido: epoch_conocido,
            pretendido: epoch_pretendido,
        };
    }
    if epoch_pretendido == epoch_conocido {
        return Custodia::Valido;
    }

    let mut ordenados: Vec<&SaltoEpoch> = saltos.iter().collect();
    ordenados.sort_by_key(|s| s.desde);

    let mut actual = epoch_conocido;
    for s in ordenados {
        if s.desde != actual {
            // Salto que no encadena con donde vamos.
            continue;
        }
        if s.hacia != s.desde + SALTO_MAXIMO {
            return Custodia::SaltoDemasiadoGrande {
                desde: s.desde,
                hacia: s.hacia,
            };
        }
        if s.verificar(clave_publica_hex).is_err() {
            return Custodia::FirmaInvalida {
                desde: s.desde,
                hacia: s.hacia,
            };
        }
        actual = s.hacia;
        if actual == epoch_pretendido {
            return Custodia::Valido;
        }
    }

    if actual < epoch_pretendido {
        Custodia::FaltanSaltos {
            desde: actual,
            hacia: epoch_pretendido,
        }
    } else {
        Custodia::Valido
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn un_salto_valido_verifica() {
        let barco = Identidad::generar();
        let s = SaltoEpoch::crear(3, 4, "inst-AAA", &barco).expect("crear");
        s.verificar(&barco.clave_publica_hex()).expect("debe verificar");
    }

    #[test]
    fn un_salto_de_mas_de_uno_se_rechaza_al_crearlo() {
        let barco = Identidad::generar();
        let r = SaltoEpoch::crear(3, 10, "inst-AAA", &barco);
        assert!(r.is_err(), "un salto de 7 no se debe poder crear");
    }

    #[test]
    fn otro_nodo_no_puede_firmar_el_salto() {
        let barco = Identidad::generar();
        let impostor = Identidad::generar();
        let s = SaltoEpoch::crear(0, 1, "inst-MALA", &impostor).expect("crear");
        assert!(
            s.verificar(&barco.clave_publica_hex()).is_err(),
            "la firma de otro nodo no debe valer"
        );
    }

    #[test]
    fn se_llega_con_la_cadena_completa() {
        let barco = Identidad::generar();
        let clave = barco.clave_publica_hex();
        let saltos = vec![
            SaltoEpoch::crear(0, 1, "inst-A", &barco).unwrap(),
            SaltoEpoch::crear(1, 2, "inst-A", &barco).unwrap(),
            SaltoEpoch::crear(2, 3, "inst-A", &barco).unwrap(),
        ];
        let c = verificar_cadena(0, 3, &saltos, &clave);
        assert_eq!(c, Custodia::Valido, "0->3 con la cadena debe valer: {c:?}");
    }

    #[test]
    fn sin_los_saltos_intermedios_no_se_llega() {
        let barco = Identidad::generar();
        let clave = barco.clave_publica_hex();
        // Solo el ultimo salto: no se puede llegar de 0 a 3.
        let saltos = vec![SaltoEpoch::crear(2, 3, "inst-A", &barco).unwrap()];
        let c = verificar_cadena(0, 3, &saltos, &clave);
        assert!(!c.es_valido(), "sin los intermedios NO debe valer");
        match c {
            Custodia::FaltanSaltos { desde, hacia } => {
                assert_eq!((desde, hacia), (0, 3));
            }
            otro => panic!("esperaba FaltanSaltos, vino {otro:?}"),
        }
    }

    #[test]
    fn un_epoch_anterior_es_retroceso() {
        let barco = Identidad::generar();
        let c = verificar_cadena(5, 2, &[], &barco.clave_publica_hex());
        assert!(matches!(c, Custodia::Retroceso { .. }), "no se puede ir atras");
    }

    #[test]
    fn un_salto_manipulado_no_verifica() {
        let barco = Identidad::generar();
        let clave = barco.clave_publica_hex();
        let mut s = SaltoEpoch::crear(0, 1, "inst-A", &barco).unwrap();
        // Cambiar la instancia invalida la firma: no se puede reutilizar el salto.
        s.instancia = "inst-B".into();
        let c = verificar_cadena(0, 1, &[s], &clave);
        assert!(
            matches!(c, Custodia::FirmaInvalida { .. } | Custodia::FaltanSaltos { .. }),
            "un salto manipulado no debe llevar a Valido: {c:?}"
        );
    }

    #[test]
    fn el_salto_va_y_vuelve_por_texto() {
        let barco = Identidad::generar();
        let s = SaltoEpoch::crear(7, 8, "inst-XYZ", &barco).unwrap();
        let vuelta = SaltoEpoch::desde_texto(&s.a_texto()).expect("parsear");
        assert_eq!(s, vuelta);
        vuelta.verificar(&barco.clave_publica_hex()).expect("verifica");
    }

    #[test]
    fn subir_el_epoch_a_lo_bruto_ya_no_basta() {
        // El agujero que esto cierra: declarar epoch=999 sin cadena.
        let barco = Identidad::generar();
        let clave = barco.clave_publica_hex();
        let c = verificar_cadena(0, 999, &[], &clave);
        assert!(!c.es_valido(), "epoch 999 sin cadena NO debe valer");
    }
}
