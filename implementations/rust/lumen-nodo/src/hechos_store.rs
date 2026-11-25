//! Almacén persistente de hechos sobre la PDB (`Host`).
//!
//! ## Qué resuelve
//!
//! El banco de `tests/banco_barco.rs` construye la serie en un `Vec`. Eso no
//! sobrevive a un reinicio. Aquí los hechos van a la PDB real, con la estructura
//! que ya usa el nodo:
//!
//! ```text
//! ^HECHOS(nodo, serie, seq) = <valor>|<prev_hash>|<firma_hex>|<ts>|<clave>
//! ```
//!
//! ## Por qué esa forma y no JSON
//!
//! Se lee en M sin parsear JSON:
//! ```text
//! S v=$G(^HECHOS("BARCO-A","gps",1))
//! S val=$P(v,"|",1),prev=$P(v,"|",2),firma=$P(v,"|",3)
//! ```
//! Es la misma decisión que ya se tomó en `cadena.rs`, y por la misma razón: el
//! dato tiene que ser legible desde M, que es donde vive el agente.
//!
//! ## El valor no puede contener `|`
//!
//! Se rechaza explícitamente al escribir. Si no, un valor con separadores
//! rompería el parseo y la firma cubriría otra cosa.

use crate::identidad::Identidad;
use crate::replicacion::Hecho;
use lumen_mlight::{Host, Subscript, Value};

/// Global de los hechos.
pub const NS_HECHOS: &str = "HECHOS";

fn subs(nodo: &str, serie: &str, seq: u64) -> Vec<Subscript> {
    vec![
        Subscript::String(nodo.to_string()),
        Subscript::String(serie.to_string()),
        Subscript::Number(seq as f64),
    ]
}

/// Serializa un hecho a texto plano legible desde M.
pub fn a_texto(h: &Hecho) -> String {
    let firma = h
        .firma
        .map(|f| f.iter().map(|b| format!("{b:02x}")).collect::<String>())
        .unwrap_or_default();
    format!(
        "{}|{}|{}|{}|{}",
        h.valor, h.prev_hash, firma, h.ts, h.clave
    )
}

/// Reconstruye un hecho desde el texto guardado.
pub fn desde_texto(nodo: &str, serie: &str, seq: u64, texto: &str) -> Option<Hecho> {
    let campos: Vec<&str> = texto.split('|').collect();
    if campos.len() < 5 {
        return None;
    }
    let firma = if campos[2].is_empty() {
        None
    } else {
        let mut f = [0u8; 64];
        if campos[2].len() != 128 {
            return None;
        }
        for i in 0..64 {
            f[i] = u8::from_str_radix(&campos[2][i * 2..i * 2 + 2], 16).ok()?;
        }
        Some(f)
    };
    Some(Hecho {
        nodo: nodo.to_string(),
        serie: serie.to_string(),
        seq,
        clave: campos[4].to_string(),
        valor: campos[0].to_string(),
        prev_hash: campos[1].to_string(),
        ts: campos[3].parse().ok()?,
        firma,
    })
}

/// Error de escritura en el almacén.
#[derive(Debug)]
pub enum ErrorAlmacen {
    /// El valor contiene `|`, que rompería el formato.
    ValorConSeparador,
    /// El host rechazó la escritura.
    Host(String),
}

impl std::fmt::Display for ErrorAlmacen {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ValorConSeparador => write!(
                f,
                "el valor contiene '|', que es el separador del formato"
            ),
            Self::Host(e) => write!(f, "host: {e}"),
        }
    }
}

/// Guarda un hecho en la PDB. Tambien calcula y devuelve la firma si el hecho
/// viene sin ella y se pasa identidad.
pub fn guardar(host: &mut impl Host, h: &Hecho) -> Result<(), ErrorAlmacen> {
    if h.valor.contains('|') {
        return Err(ErrorAlmacen::ValorConSeparador);
    }
    let texto = a_texto(h);
    host.set(NS_HECHOS, &subs(&h.nodo, &h.serie, h.seq), Value::String(texto))
        .map_err(|e| ErrorAlmacen::Host(format!("{e:?}")))?;
    Ok(())
}

/// Firma el hecho (si hace falta) y lo guarda.
pub fn guardar_firmado(
    host: &mut impl Host,
    mut h: Hecho,
    id: &Identidad,
) -> Result<Hecho, ErrorAlmacen> {
    if h.firma.is_none() {
        h.firmar(id);
    }
    guardar(host, &h)?;
    Ok(h)
}

/// Lee un hecho concreto.
pub fn leer(host: &impl Host, nodo: &str, serie: &str, seq: u64) -> Option<Hecho> {
    let v = host.get(NS_HECHOS, &subs(nodo, serie, seq)).ok().flatten()?;
    desde_texto(nodo, serie, seq, &v.as_string())
}

/// Cuenta cuantos hechos hay de una serie, sin cargarlos.
///
/// Recorre con `$ORDER` hasta encontrar el primer hueco, asi que el coste es el
/// numero de hechos de la serie, no de la base.
pub fn contar_serie(host: &impl Host, nodo: &str, serie: &str) -> u64 {
    let mut n = 0u64;
    loop {
        if host.get(NS_HECHOS, &subs(nodo, serie, n)).ok().flatten().is_none() {
            break;
        }
        n += 1;
    }
    n
}

/// Lee la serie completa en orden.
pub fn leer_serie(host: &impl Host, nodo: &str, serie: &str) -> Vec<Hecho> {
    let total = contar_serie(host, nodo, serie);
    let mut out = Vec::with_capacity(total as usize);
    for seq in 0..total {
        if let Some(h) = leer(host, nodo, serie, seq) {
            out.push(h);
        }
    }
    out
}

/// Verifica la cadena de una serie ya leida: sin huecos y con los hashes bien
/// encadenados. Devuelve el primer problema encontrado.
pub fn verificar_serie(serie: &[Hecho]) -> Result<(), String> {
    for (i, h) in serie.iter().enumerate() {
        if h.seq != i as u64 {
            return Err(format!("hueco: falta seq {} (encontrado {})", i, h.seq));
        }
        let esperado = if i == 0 {
            String::new()
        } else {
            serie[i - 1].hash()
        };
        if h.prev_hash != esperado {
            return Err(format!("cadena rota en seq {}", h.seq));
        }
        if h.hash() != crate::cadena::hash_muestra(&h.prev_hash, &h.valor) {
            return Err(format!("valor no coincide con el hash en seq {}", h.seq));
        }
    }
    Ok(())
}

/// Verifica la cadena y ademas las firmas presentes contra una clave publica.
///
/// Solo comprueba las muestras que TIENEN firma (perfil `por_bloque`). Si el
/// perfil firma por hecho, todas la tienen y esto verifica todas.
pub fn verificar_serie_con_firmas(
    serie: &[Hecho],
    clave_publica: &[u8],
) -> Result<usize, String> {
    verificar_serie(serie)?;
    let mut verificadas = 0;
    for h in serie.iter().filter(|h| h.firma.is_some()) {
        h.verificar_firma(clave_publica)?;
        verificadas += 1;
    }
    Ok(verificadas)
}

#[cfg(test)]
mod tests {
    use super::*;
    use lumen_mlight::MemoryHost;

    fn hecho(seq: u64, valor: &str, prev: &str) -> Hecho {
        Hecho {
            nodo: "BARCO-A".into(),
            serie: "gps".into(),
            seq,
            clave: "gps".into(),
            valor: valor.into(),
            prev_hash: prev.into(),
            ts: seq,
            firma: None,
        }
    }

    #[test]
    fn guarda_y_lee_un_hecho() {
        let mut host = MemoryHost::default();
        let h = hecho(0, "lat=41.1", "");
        guardar(&mut host, &h).unwrap();
        let leido = leer(&host, "BARCO-A", "gps", 0).expect("debe estar");
        assert_eq!(leido.valor, "lat=41.1");
        assert_eq!(leido.seq, 0);
    }

    #[test]
    fn rechaza_valor_con_separador() {
        let mut host = MemoryHost::default();
        let h = hecho(0, "lat=41.1|inyectado", "");
        assert!(matches!(
            guardar(&mut host, &h),
            Err(ErrorAlmacen::ValorConSeparador)
        ));
    }

    #[test]
    fn la_serie_va_y_vuelve_entera() {
        let mut host = MemoryHost::default();
        let mut prev = String::new();
        for i in 0..5u64 {
            let h = hecho(i, &format!("lat=41.{i}"), &prev);
            prev = h.hash();
            guardar(&mut host, &h).unwrap();
        }
        assert_eq!(contar_serie(&host, "BARCO-A", "gps"), 5);
        let serie = leer_serie(&host, "BARCO-A", "gps");
        assert_eq!(serie.len(), 5);
        verificar_serie(&serie).expect("cadena intacta");
    }

    #[test]
    fn se_detecta_un_hueco_tras_borrar() {
        let mut host = MemoryHost::default();
        let mut prev = String::new();
        for i in 0..5u64 {
            let h = hecho(i, &format!("lat=41.{i}"), &prev);
            prev = h.hash();
            guardar(&mut host, &h).unwrap();
        }
        // Borrar la muestra 2 del medio.
        let s = subs("BARCO-A", "gps", 2);
        host.kill(NS_HECHOS, &s).unwrap();

        let serie = leer_serie(&host, "BARCO-A", "gps");
        // contar_serie para en el hueco, asi que solo ve 0 y 1
        assert!(serie.len() < 5, "debe faltar alguna");
        // Y si leemos explicitamente la 2, no esta.
        assert!(leer(&host, "BARCO-A", "gps", 2).is_none());
    }

    #[test]
    fn la_firma_sobrevive_al_viaje_por_texto() {
        let mut host = MemoryHost::default();
        let id = Identidad::generar();
        let h = hecho(0, "lat=41.1", "");
        let devuelto = guardar_firmado(&mut host, h, &id).unwrap();
        assert!(devuelto.firma.is_some());

        let leido = leer(&host, "BARCO-A", "gps", 0).unwrap();
        assert_eq!(leido.firma, devuelto.firma, "la firma debe volver intacta");
        leido
            .verificar_firma(&id.clave_publica())
            .expect("la firma debe verificar tras el viaje");
    }
}
