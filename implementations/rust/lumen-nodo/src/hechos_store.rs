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

fn subs(nodo: &str, serie: &str, seq: u64, instance_id: &str) -> Vec<Subscript> {
    // La instancia va en la clave para que dos ramas del mismo barco COEXISTAN.
    // Un hecho v1 no tiene instancia: se usa "_" para no romper las series ya
    // escritas (su clave sigue siendo la misma de antes).
    let inst = if instance_id.is_empty() { "_" } else { instance_id };
    vec![
        Subscript::String(nodo.to_string()),
        Subscript::String(serie.to_string()),
        Subscript::Number(seq as f64),
        Subscript::String(inst.to_string()),
    ]
}

/// Serializa un hecho a texto plano legible desde M.
///
/// Formato v2 (7 campos): `valor|prev_hash|firma|ts|clave|instance_id|epoch`
/// Formato v1 (5 campos): `valor|prev_hash|firma|ts|clave`
///
/// El número de campos distingue la versión al leer, así que un hecho v1 sigue
/// leyéndose igual que antes y **no hay migración**.
pub fn a_texto(h: &Hecho) -> String {
    let firma = h
        .firma
        .map(|f| f.iter().map(|b| format!("{b:02x}")).collect::<String>())
        .unwrap_or_default();
    if h.version >= 3 {
        // v3 = v2 + tipo. Se escribe SIEMPRE (aunque sea el por defecto) para
        // que el formato sea uno solo y no haya sorpresas al releer.
        format!(
            "{}|{}|{}|{}|{}|{}|{}|{}",
            h.valor, h.prev_hash, firma, h.ts, h.clave, h.instance_id, h.epoch,
            h.tipo.etiqueta()
        )
    } else if h.version == 2 {
        format!(
            "{}|{}|{}|{}|{}|{}|{}",
            h.valor, h.prev_hash, firma, h.ts, h.clave, h.instance_id, h.epoch
        )
    } else {
        format!("{}|{}|{}|{}|{}", h.valor, h.prev_hash, firma, h.ts, h.clave)
    }
}

/// Reconstruye un hecho desde el texto guardado.
///
/// Acepta los dos formatos: 5 campos = v1, 7 campos = v2. Así los hechos
/// escritos antes del cambio se siguen leyendo sin migrar nada.
pub fn desde_texto(nodo: &str, serie: &str, seq: u64, texto: &str) -> Option<Hecho> {
    let campos: Vec<&str> = texto.split('|').collect();
    if campos.len() != 5 && campos.len() != 7 && campos.len() != 8 {
        return None;
    }
    let firma = if campos[2].is_empty() {
        None
    } else {
        if campos[2].len() != 128 {
            return None;
        }
        let mut f = [0u8; 64];
        for i in 0..64 {
            f[i] = u8::from_str_radix(&campos[2][i * 2..i * 2 + 2], 16).ok()?;
        }
        Some(f)
    };
    let (version, instance_id, epoch, tipo) = if campos.len() == 8 {
        (
            3u8,
            campos[5].to_string(),
            campos[6].parse().ok()?,
            crate::replicacion::TipoHecho::desde_etiqueta(campos[7])
                .unwrap_or(crate::replicacion::TipoHecho::Idempotente),
        )
    } else if campos.len() == 7 {
        (2u8, campos[5].to_string(), campos[6].parse().ok()?, crate::replicacion::TipoHecho::Idempotente)
    } else {
        (1u8, String::new(), 0u64, crate::replicacion::TipoHecho::Idempotente)
    };
    Some(Hecho {
        version,
        nodo: nodo.to_string(),
        serie: serie.to_string(),
        seq,
        instance_id,
        epoch,
        tipo,
        clave: campos[4].to_string(),
        valor: campos[0].to_string(),
        prev_hash: campos[1].to_string(),
        ts: campos[3].parse().ok()?,
        firma, ..Default::default() })
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
    host.set(
        NS_HECHOS,
        &subs(&h.nodo, &h.serie, h.seq, &h.instance_id),
        Value::String(texto),
    )
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

/// Lee un hecho concreto de una instancia concreta.
pub fn leer(
    host: &impl Host,
    nodo: &str,
    serie: &str,
    seq: u64,
    instance_id: &str,
) -> Option<Hecho> {
    let v = host
        .get(NS_HECHOS, &subs(nodo, serie, seq, instance_id))
        .ok()
        .flatten()?;
    desde_texto(nodo, serie, seq, &v.as_string())
}

/// Lista las instancias que tienen un hecho en esta posición `(nodo, serie, seq)`.
///
/// Es lo que permite detectar split-brain: si hay más de una, hay dos ramas.
/// Se recorre con `$ORDER` sobre el cuarto subíndice (la instancia).
pub fn instancias_en_posicion(
    host: &impl Host,
    nodo: &str,
    serie: &str,
    seq: u64,
) -> Vec<String> {
    use lumen_mlight::Subscript;
    let padre = vec![
        Subscript::String(nodo.to_string()),
        Subscript::String(serie.to_string()),
        Subscript::Number(seq as f64),
    ];
    let mut out = Vec::new();
    let mut actual: Option<Subscript> = None;
    loop {
        let siguiente = host
            .order(NS_HECHOS, &padre, actual.as_ref(), 1)
            .ok()
            .flatten();
        match siguiente {
            Some(s) => {
                let nombre = match &s {
                    Subscript::String(t) => t.clone(),
                    Subscript::Number(n) => format!("{n}"),
                };
                // La instancia vacía se guarda como "_": se normaliza a "".
                out.push(if nombre == "_" { String::new() } else { nombre });
                actual = Some(s);
            }
            None => break,
        }
    }
    out
}

/// Lee la **rama principal**: la de instancia vacía (`_`).
///
/// Es lo que sigue funcionando para las series de una sola instancia, que son
/// todas las de hoy. Cuando hay split-brain, cada rama se lee aparte con
/// [`leer_rama`].
pub fn leer_principal(host: &impl Host, nodo: &str, serie: &str, seq: u64) -> Option<Hecho> {
    leer(host, nodo, serie, seq, "")
}

/// Lee un hecho de una rama concreta (por `instance_id`).
pub fn leer_rama(
    host: &impl Host,
    nodo: &str,
    serie: &str,
    seq: u64,
    instance_id: &str,
) -> Option<Hecho> {
    leer(host, nodo, serie, seq, instance_id)
}

/// Cuenta cuantos hechos hay de la rama principal, sin cargarlos.
///
/// Recorre hasta encontrar el primer hueco, asi que el coste es el numero de
/// hechos de la serie, no de la base.

/// Cuenta los hechos de una rama **concreta** (por `instance_id`).
///
/// ## Por qué existe esta y no basta `contar_serie`
///
/// `contar_serie` cuenta la rama **principal**, que es la de instancia `""`. Los
/// hechos escritos por un nodo con identidad van en SU instancia (`"hub"`,
/// `"inst-A"`, ...), así que `contar_serie` devuelve **0 siempre** para ellos.
///
/// Ese fallo silencioso hizo que los eventos de cuarentena se escribieran todos en
/// `seq 0` y **se sobrescribieran entre sí**: cinco eventos, uno guardado.
///
/// La lección es la misma que el bug del test anterior: `contar_serie` y
/// `leer_serie_de_rama` **no miran lo mismo**, y confundirlos falla en silencio.
pub fn contar_serie_rama(host: &impl Host, nodo: &str, serie: &str, instancia: &str) -> u64 {
    let mut n = 0u64;
    loop {
        if host
            .get(NS_HECHOS, &subs(nodo, serie, n, instancia))
            .ok()
            .flatten()
            .is_none()
        {
            break;
        }
        n += 1;
    }
    n
}

pub fn contar_serie(host: &impl Host, nodo: &str, serie: &str) -> u64 {
    let mut n = 0u64;
    loop {
        if host
            .get(NS_HECHOS, &subs(nodo, serie, n, ""))
            .ok()
            .flatten()
            .is_none()
        {
            break;
        }
        n += 1;
    }
    n
}

/// Lee la rama principal completa en orden.
pub fn leer_serie(host: &impl Host, nodo: &str, serie: &str) -> Vec<Hecho> {
    let total = contar_serie(host, nodo, serie);
    let mut out = Vec::with_capacity(total as usize);
    for seq in 0..total {
        if let Some(h) = leer_principal(host, nodo, serie, seq) {
            out.push(h);
        }
    }
    out
}

/// Lee una rama concreta completa en orden.
pub fn leer_serie_de_rama(
    host: &impl Host,
    nodo: &str,
    serie: &str,
    instance_id: &str,
) -> Vec<Hecho> {
    let mut out = Vec::new();
    let mut seq = 0u64;
    while let Some(h) = leer_rama(host, nodo, serie, seq, instance_id) {
        out.push(h);
        seq += 1;
    }
    out
}


/// Verifica **varias series en paralelo**, una por hilo.
///
/// ## Por qué esto importa
///
/// Medido: verificar una serie de 21.600 hechos (cadena + sellos) tarda
/// **0,6 s**. Para un ledger con 1 millón de cuentas serían **28 s** de
/// verificación por millón de hechos.
///
/// Pero la cadena es secuencial **solo dentro de una serie**. Series distintas
/// son independientes: la de un usuario no depende de la de otro. Con 8 núcleos,
/// 8 series se verifican a la vez.
///
/// En un ledger, cada cuenta es una serie → el paralelismo es natural.
///
/// Devuelve un `Result` por serie, en el mismo orden que la entrada.
pub fn verificar_series_en_paralelo(
    series: Vec<(String, Vec<Hecho>)>,
    verificar: impl Fn(&[Hecho]) -> Result<(), String> + Sync,
) -> Vec<(String, Result<(), String>)> {
    let verificar = &verificar;
    let mut out: Vec<(String, Result<(), String>)> = Vec::with_capacity(series.len());

    // Un lote de hilos igual al numero de nucleos, reutilizando std::thread
    // (sin anadir dependencias como rayon para una sola funcion).
    let nucleos = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
        .max(1);

    let mut pendientes = series.into_iter().collect::<Vec<_>>();
    // Se procesa en tandas de `nucleos` para no crear un hilo por serie.
    while !pendientes.is_empty() {
        let tanda: Vec<_> = pendientes.drain(..pendientes.len().min(nucleos)).collect();
        let resultados: Vec<(String, Result<(), String>)> = std::thread::scope(|scope| {
            let handles: Vec<_> = tanda
                .into_iter()
                .map(|(nombre, hechos)| {
                    scope.spawn(move || {
                        let r = verificar(&hechos);
                        (nombre, r)
                    })
                })
                .collect();
            handles.into_iter().map(|h| h.join().unwrap()).collect()
        });
        out.extend(resultados);
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
            ..Default::default()
        }
    }

    #[test]
    fn guarda_y_lee_un_hecho() {
        let mut host = MemoryHost::default();
        let h = hecho(0, "lat=41.1", "");
        guardar(&mut host, &h).unwrap();
        let leido = leer_principal(&host, "BARCO-A", "gps", 0).expect("debe estar");
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
        let s = subs("BARCO-A", "gps", 2, "");
        host.kill(NS_HECHOS, &s).unwrap();

        let serie = leer_serie(&host, "BARCO-A", "gps");
        // contar_serie para en el hueco, asi que solo ve 0 y 1
        assert!(serie.len() < 5, "debe faltar alguna");
        // Y si leemos explicitamente la 2, no esta.
        assert!(leer_principal(&host, "BARCO-A", "gps", 2).is_none());
    }

    #[test]
    fn la_firma_sobrevive_al_viaje_por_texto() {
        let mut host = MemoryHost::default();
        let id = Identidad::generar();
        let h = hecho(0, "lat=41.1", "");
        let devuelto = guardar_firmado(&mut host, h, &id).unwrap();
        assert!(devuelto.firma.is_some());

        let leido = leer_principal(&host, "BARCO-A", "gps", 0).unwrap();
        assert_eq!(leido.firma, devuelto.firma, "la firma debe volver intacta");
        leido
            .verificar_firma(&id.clave_publica())
            .expect("la firma debe verificar tras el viaje");
    }
}

/// Construye el árbol de Merkle de una serie **leída del store**.
///
/// ## Por qué aquí y no en `merkle.rs`
///
/// `merkle.rs` no sabe nada de hechos ni de la PDB: recibe hashes y devuelve un
/// árbol. Esta función es la que sabe **dónde están** esos hashes. Así el módulo
/// de Merkle sigue siendo puro y testeable sin base de datos.
///
/// ## Qué hashes se usan
///
/// El hash de cada hecho (`Hecho::hash()`), que ya incluye el contenido y el
/// hash anterior. Eso encadena la inclusión con la completitud: no son dos
/// pruebas independientes, están apoyadas la una en la otra.
pub fn arbol_de_serie<H: Host>(
    host: &H,
    nodo: &str,
    serie: &str,
    instancia: &str,
) -> crate::merkle::ArbolMerkle {
    let hechos = leer_serie_de_rama(host, nodo, serie, instancia);
    let hashes: Vec<String> = hechos.iter().map(|h| h.hash()).collect();
    crate::merkle::ArbolMerkle::nuevo(&hashes)
}

/// Genera la prueba de inclusión del hecho `seq` de una serie del store.
///
/// Devuelve `None` si la serie no existe o el `seq` está fuera de rango.
pub fn prueba_de_hecho<H: Host>(
    host: &H,
    nodo: &str,
    serie: &str,
    instancia: &str,
    seq: u64,
) -> Option<crate::merkle::PruebaInclusion> {
    let arbol = arbol_de_serie(host, nodo, serie, instancia);
    // El índice en el árbol es la posición en la serie ordenada por seq, no el
    // seq en sí (puede haber huecos).
    let hechos = leer_serie_de_rama(host, nodo, serie, instancia);
    let indice = hechos.iter().position(|h| h.seq == seq)?;
    arbol.prueba(indice)
}

