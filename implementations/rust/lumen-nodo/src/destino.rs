//! Escritura del estado recibido en el `Host` de la MVM.
//!
//! Se abstrae con un trait mínimo (`Destino`) en vez de acoplarse a
//! `MemoryHost`, por dos razones: se puede probar sin base de datos, y el día
//! que exista un host replicado (DDP sobre QUIC) solo cambia la implementación,
//! no esta lógica.

use crate::aplicar::{ErrorAplicar, Escritura};

/// Dónde se aplican las escrituras. Un `set` por subíndice, semántica MUMPS.
pub trait Destino {
    /// Escribe `ns(subs) = valor`. Devuelve el número de niveles tocados.
    fn set(&mut self, ns: &str, subs: &[String], valor: &str) -> Result<usize, String>;
    /// Si el destino admite escrituras (un nodo en solo-lectura no).
    fn acepta_escrituras(&self) -> bool {
        true
    }
}

/// Resultado de aplicar un frame, con lo necesario para el ACK y el log.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Aplicado {
    pub ns: String,
    pub subs: Vec<String>,
    /// Bytes del valor escrito (para poder reportar cuánto entró de verdad).
    pub bytes: usize,
    /// Hash de la muestra si la cadena está activa (`sign=hash-chain`).
    pub hash: Option<String>,
}

/// Aplica una escritura al destino. No hay atajos: si el `set` falla, falla.
pub fn aplicar<D: Destino>(destino: &mut D, w: &Escritura) -> Result<Aplicado, ErrorAplicar> {
    if !destino.acepta_escrituras() {
        return Err(ErrorAplicar::NoAceptaEscrituras);
    }
    destino
        .set(&w.ns, &w.subs, &w.valor)
        .map_err(ErrorAplicar::Host)?;
    Ok(Aplicado {
        ns: w.ns.clone(),
        subs: w.subs.clone(),
        bytes: w.valor.len(),
        hash: None,
    })
}

/// Destino en memoria, para tests y para nodos sin persistencia.
///
/// Lleva también el estado de la cadena (`EstadoCadena`), de modo que sirve
/// tanto para el camino simple como para `sign=hash-chain`. Un destino real
/// (`DestinoMvm`) hace lo propio leyendo/escribiendo en `^CADENA`.
#[derive(Debug, Default)]
pub struct DestinoMemoria {
    pub escrituras: Vec<(String, Vec<String>, String)>,
    pub solo_lectura: bool,
    pub cadenas: std::collections::HashMap<String, (u64, String)>,
}

fn clave_serie(serie: &crate::cadena::Serie) -> String {
    format!("{}::{}", serie.ns, serie.etiqueta())
}

impl crate::cadena::EstadoCadena for DestinoMemoria {
    fn ultima(&self, serie: &crate::cadena::Serie) -> Option<u64> {
        self.cadenas.get(&clave_serie(serie)).map(|(n, _)| *n)
    }
    fn hash_ultimo(&self, serie: &crate::cadena::Serie) -> Option<String> {
        self.cadenas
            .get(&clave_serie(serie))
            .map(|(_, h)| h.clone())
    }
    fn guardar(&mut self, serie: &crate::cadena::Serie, numero: u64, hash: &str) -> Result<(), String> {
        self.cadenas
            .insert(clave_serie(serie), (numero, hash.to_string()));
        Ok(())
    }
}

impl Destino for DestinoMemoria {
    fn set(&mut self, ns: &str, subs: &[String], valor: &str) -> Result<usize, String> {
        self.escrituras
            .push((ns.to_string(), subs.to_vec(), valor.to_string()));
        Ok(subs.len())
    }

    fn acepta_escrituras(&self) -> bool {
        !self.solo_lectura
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::aplicar::parsear_set;

    #[test]
    fn aplica_una_escritura() {
        let mut d = DestinoMemoria::default();
        let w = parsear_set(b"^FLOTA(BARCO,lat)=41.38").unwrap();
        let a = aplicar(&mut d, &w).unwrap();
        assert_eq!(a.ns, "FLOTA");
        assert_eq!(a.subs, vec!["BARCO", "lat"]);
        assert_eq!(a.bytes, 5);
        assert_eq!(d.escrituras.len(), 1);
        assert_eq!(d.escrituras[0].2, "41.38");
    }

    #[test]
    fn nodo_solo_lectura_rechaza() {
        let mut d = DestinoMemoria {
            solo_lectura: true,
            ..Default::default()
        };
        let w = parsear_set(b"^A(k)=1").unwrap();
        let e = aplicar(&mut d, &w).unwrap_err();
        assert_eq!(e, ErrorAplicar::NoAceptaEscrituras);
        assert!(d.escrituras.is_empty(), "no debe escribir nada");
    }

    #[test]
    fn error_del_host_se_propaga() {
        struct Rojo;
        impl Destino for Rojo {
            fn set(&mut self, _: &str, _: &[String], _: &str) -> Result<usize, String> {
                Err("disco lleno".into())
            }
        }
        let w = parsear_set(b"^A(k)=1").unwrap();
        let e = aplicar(&mut Rojo, &w).unwrap_err();
        assert!(matches!(e, ErrorAplicar::Host(m) if m.contains("disco lleno")));
    }
}
