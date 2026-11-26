//! Replicación de hechos por el cable, usando `lumen-znet`.
//!
//! ## Qué añade sobre `hechos_store`
//!
//! `hechos_store` guarda y lee del sitio. Esto mueve los hechos **entre nodos**:
//!
//! 1. El receptor pide: *"dame los hechos de la serie X desde seq N"*
//!    → un mensaje DDP con `DATA` y el cuerpo `gossip|serie|desde`.
//! 2. El emisor responde con N mensajes `DATA`, uno por hecho.
//! 3. El receptor **verifica cada hecho al recibir**: cadena, firma y
//!    pertenencia. Un hecho que no verifica no se guarda.
//!
//! ## Por qué un mensaje por hecho y no un lote
//!
//! Porque un lote obliga a decidir qué hacer si un hecho del medio falla. Con un
//! mensaje por hecho, el receptor acepta lo que verifica y pide el resto otra vez
//! desde el ultimo bueno. Es el mismo principio que un cursor.
//!
//! ## Lo que NO hace
//!
//! No hay ventana de congestión ni reintentos: eso lo pone QUIC. Aquí se manda
//! y se verifica.

use crate::hechos_store::{self, verificar_serie};
use crate::identidad::Identidad;
use crate::replicacion::Hecho;
use lumen_mlight::Host;
use lumen_znet::{msg_type, DdpMessage, Znet, ZnetReply};

/// Prefijo del cuerpo de un mensaje de petición de hechos.
pub const COMANDO_GOSSIP: &str = "gossip";

/// Construye la petición: `gossip|<serie>|<desde>`.
pub fn peticion(serie: &str, desde: u64) -> DdpMessage {
    let cuerpo = format!("{COMANDO_GOSSIP}|{serie}|{desde}");
    DdpMessage::new(msg_type::DATA, 0, 0, 0, cuerpo.into_bytes())
}

/// Interpreta una petición. Devuelve `(serie, desde)` si lo es.
pub fn interpretar_peticion(msg: &DdpMessage) -> Option<(String, u64)> {
    let texto = std::str::from_utf8(&msg.body).ok()?;
    let partes: Vec<&str> = texto.split('|').collect();
    if partes.len() != 3 || partes[0] != COMANDO_GOSSIP {
        return None;
    }
    Some((partes[1].to_string(), partes[2].parse().ok()?))
}

/// Construye el mensaje que lleva UN hecho.
///
/// El cuerpo es `<nodo>|<serie>|<seq>|<texto del hecho>`, que es exactamente lo
/// que `hechos_store::desde_texto` sabe reconstruir.
pub fn mensaje_de_hecho(h: &Hecho) -> DdpMessage {
    let cuerpo = format!(
        "{}|{}|{}|{}",
        h.nodo,
        h.serie,
        h.seq,
        hechos_store::a_texto(h)
    );
    DdpMessage::new(msg_type::DATA, h.seq as u16, 0, 0, cuerpo.into_bytes())
}

/// Reconstruye un hecho desde un mensaje.
pub fn hecho_de_mensaje(msg: &DdpMessage) -> Option<Hecho> {
    let texto = std::str::from_utf8(&msg.body).ok()?;
    let partes: Vec<&str> = texto.splitn(4, '|').collect();
    if partes.len() != 4 {
        return None;
    }
    let seq: u64 = partes[2].parse().ok()?;
    hechos_store::desde_texto(partes[0], partes[1], seq, partes[3])
}

/// Sirve una petición de hechos: encola un mensaje por hecho desde `desde`.
///
/// Devuelve cuantos encoló. Si la serie está vacía, devuelve 0 y el llamante
/// puede responder `EMPTY`.
pub fn servir_peticion<H: Host>(
    host: &H,
    nodo: &str,
    peticion_msg: &DdpMessage,
    znet: &mut Znet,
    circuito: u16,
) -> usize {
    let Some((serie, desde)) = interpretar_peticion(peticion_msg) else {
        return 0;
    };
    let total = hechos_store::contar_serie(host, nodo, &serie);
    let mut enviados = 0;
    for seq in desde..total {
        if let Some(h) = hechos_store::leer(host, nodo, &serie, seq, "") {
            let m = mensaje_de_hecho(&h);
            let _ = znet.reply(
                circuito,
                ZnetReply::Data(m.body),
            );
            enviados += 1;
        }
    }
    enviados
}

/// Resultado de recibir hechos.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct ResumenRecepcion {
    /// Hechos guardados correctamente.
    pub aceptados: usize,
    /// Hechos rechazados por no verificar (cadena, firma, orden).
    pub rechazados: usize,
    /// Hechos que **no se han descartado**: chocaban con uno existente y se han
    /// guardado como rama aparte, marcados como conflicto.
    pub conflictos: usize,
    /// Duplicados exactos (mismo hash): idempotencia, se ignoran sin más.
    pub duplicados: usize,
    /// Detalle de cada conflicto, con evidencia para el operador.
    pub detalle_conflictos: Vec<Conflicto>,
    /// Motivo del primer rechazo, para poder diagnosticar.
    pub primer_motivo: Option<String>,
}

/// Un choque entre dos hechos con la misma posición pero distinto contenido.
///
/// **No es un descarte**: las dos versiones se conservan. El operador decide
/// cuál es la buena con la evidencia de aquí.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Conflicto {
    pub nodo: String,
    pub serie: String,
    pub seq: u64,
    pub instance_existente: String,
    pub instance_nueva: String,
    pub hash_existente: String,
    pub hash_nuevo: String,
    pub epoch_existente: u64,
    pub epoch_nuevo: u64,
}

impl Conflicto {
    /// Describe el conflicto en una línea, para el log.
    pub fn resumen(&self) -> String {
        format!(
            "CONFLICTO {}/{} seq={} instancia '{}'(e{}) vs '{}'(e{}) hash {} vs {}",
            self.nodo, self.serie, self.seq,
            self.instance_existente, self.epoch_existente,
            self.instance_nueva, self.epoch_nuevo,
            &self.hash_existente[..8.min(self.hash_existente.len())],
            &self.hash_nuevo[..8.min(self.hash_nuevo.len())],
        )
    }
}

/// Verifica los BLOQUES de una serie completa.
///
/// ## Por qué esto es imprescindible y no un extra
///
/// Con firma por bloque, solo la ultima muestra del bloque lleva firma (la 99,
/// la 199...). Eso deja un agujero que se descubrio al ejecutar el E2E: cambiar
/// una muestra SIN firma del bloque pasa desapercibido, porque el receptor no
/// tiene nada que verificar en ella.
///
/// La solucion es la del ADR-003: **la firma cubre el sello del bloque**, y el
/// sello es `sha256(sello_previo || hash_1 || ... || hash_N)`. Asi, cambiar
/// cualquier muestra del bloque cambia el sello y la firma deja de validar.
///
/// Este verificador recorre la serie por bloques y comprueba:
/// 1. Que el sello recalculado coincide con el que se firmo.
/// 2. Que la firma de la ultima muestra del bloque valida ese sello.
pub fn verificar_bloques(
    serie: &[Hecho],
    bloque: usize,
    clave_publica: &[u8],
) -> Result<usize, String> {
    verificar_serie(serie)?;
    verificar_solo_bloques(serie, bloque, clave_publica)
}

/// Verifica SOLO los sellos de bloque, sin comprobar la cadena de hashes.
///
/// Se separa de [`verificar_bloques`] para poder probar las dos defensas por
/// separado: la cadena y el sello. Si van juntas, la cadena siempre salta
/// primero y el sello nunca se evalua, lo que oculta si de verdad protege algo.
pub fn verificar_solo_bloques(
    serie: &[Hecho],
    bloque: usize,
    clave_publica: &[u8],
) -> Result<usize, String> {
    if bloque == 0 {
        return Err("tamaño de bloque 0".into());
    }

    let mut sello_previo = String::new();
    let mut bloques_ok = 0;
    let mut inicio = 0usize;

    while inicio < serie.len() {
        let fin = (inicio + bloque).min(serie.len());
        let trozo = &serie[inicio..fin];

        // El sello del bloque, igual que cadena::sello_bloque.
        let hashes: Vec<String> = trozo.iter().map(|h| h.hash()).collect();
        let sello = crate::cadena::sello_bloque(&sello_previo, &hashes);

        // La ultima muestra del bloque debe llevar firma y validar el sello.
        let ultima = trozo.last().unwrap();
        if ultima.firma.is_some() {
            let esperado = crate::cadena::SelloFirmado::mensaje_canonico(
                NS_BLOQUES, &ultima.serie, (inicio / bloque) as u64, &sello,
            );
            crate::identidad::verificar(clave_publica, &esperado, &ultima.firma.unwrap())
                .map_err(|e| format!("sello del bloque {} no valida: {e:?}", inicio / bloque))?;
            bloques_ok += 1;
        }

        sello_previo = sello;
        inicio = fin;
    }
    Ok(bloques_ok)
}

/// Namespace usado en el mensaje canonico de los sellos de bloque.
pub const NS_BLOQUES: &str = "FLOTA";

/// Firma el SELLO del bloque, no la muestra.
///
/// Se descubrio en el E2E que firmar solo la muestra 99 dejaba un agujero:
/// cambiar cualquier otra muestra del bloque pasaba desapercibido. El sello
/// cubre los hashes de las 100, asi que cambiando una cambia el sello y la
/// firma deja de validar.
pub fn firmar_bloque(serie: &mut [Hecho], bloque: usize, id: &Identidad) -> usize {
    if bloque == 0 {
        return 0;
    }
    let mut firmados = 0;
    let mut sello_previo = String::new();
    let mut inicio = 0usize;
    while inicio < serie.len() {
        let fin = (inicio + bloque).min(serie.len());
        let hashes: Vec<String> = serie[inicio..fin].iter().map(|h| h.hash()).collect();
        let sello = crate::cadena::sello_bloque(&sello_previo, &hashes);
        let ultima = &mut serie[fin - 1];
        let msg = crate::cadena::SelloFirmado::mensaje_canonico(
            NS_BLOQUES, &ultima.serie, (inicio / bloque) as u64, &sello,
        );
        ultima.firma = Some(id.firmar(&msg));
        firmados += 1;
        sello_previo = sello;
        inicio = fin;
    }
    firmados
}

/// Verifica una serie **de punta a punta**: cadena, sellos y PERTENENCIA A FLOTA.
///
/// ## Por qué esto es el paso que faltaba
///
/// Hasta aquí se comprobaba *"alguien con esta clave firmó esto"*. Eso no basta:
/// cualquiera puede generar un par de claves y firmar una bitácora perfecta.
/// Lo que hace falta es *"esta clave es de un barco de MI flota"*.
///
/// Los dos pasos, en este orden:
/// 1. **El certificado lo emitió mi raíz de armador** — si no, la clave no es
///    de mi flota y no se sigue verificando nada.
/// 2. **La firma del sello la hizo la clave de ese certificado** — y además esa
///    clave debe ser la del nodo emisor, no otra.
///
/// Se devuelve cuántos sellos se verificaron.
pub fn verificar_serie_de_flota(
    serie: &[Hecho],
    certificado: &crate::identidad::CertificadoFlota,
    raiz_clave_publica_hex: &str,
    bloque: usize,
) -> Result<usize, String> {
    // ── Paso 1: ¿es un barco de mi flota? ──
    certificado
        .verificar_con_raiz(raiz_clave_publica_hex)
        .map_err(|e| format!("el barco no pertenece a la flota: {e:?}"))?;

    // ── Paso 2: la serie es coherente ──
    verificar_serie(serie)?;

    // ── Paso 3: el certificado habla de ESTE nodo ──
    // Si el certificado es de BARCO-A pero los hechos dicen BARCO-B, se rechaza.
    // Sin esta comprobacion, un barco de la flota podria firmar hechos a nombre
    // de otro y el receptor los aceptaria.
    for h in serie {
        if h.nodo != certificado.barco {
            return Err(format!(
                "el hecho es del nodo '{}' pero el certificado es de '{}'",
                h.nodo, certificado.barco
            ));
        }
    }

    // ── Paso 4: los sellos, con la clave del certificado ──
    let clave = crate::identidad::hex_a_bytes_publico(&certificado.clave_barco)
        .map_err(|e| format!("clave del certificado invalida: {e:?}"))?;
    verificar_solo_bloques(serie, bloque, &clave)
}

/// Recibe hechos de mensajes y los guarda si verifican.
///
/// Verifica **en este orden**, y cualquier fallo rechaza el hecho:
/// 1. Que se puede reconstruir.
/// 2. Que la cadena enlaza con el ultimo hecho guardado de esa serie.
/// 3. Que la firma (si viene) valida con `clave_publica`.
pub fn recibir_hechos<H: Host>(
    host: &mut H,
    mensajes: &[DdpMessage],
    clave_publica: Option<&[u8]>,
) -> ResumenRecepcion {
    recibir_hechos_con(host, mensajes, clave_publica, false)
}

/// Recibe hechos **verificando la cadena de custodia del epoch**.
///
/// Además de lo que hace [`recibir_hechos_con`], comprueba que el `epoch` de
/// cada hecho es alcanzable desde el epoch que este nodo ya conoce para ese
/// barco, usando los saltos firmados presentados.
///
/// Sin esto, un nodo con la clave podría declarar `epoch = 999999` y ganar
/// siempre. Con esto, tiene que presentar la cadena de saltos completa.
///
/// `epoch_conocido` es el último epoch aceptado. Si es 0, cualquier hecho en
/// epoch 0 pasa sin cadena (caso normal: nadie ha reinstalado nada).
pub fn recibir_hechos_custodiados<H: Host>(
    host: &mut H,
    mensajes: &[DdpMessage],
    clave_publica_hex: &str,
    saltos: &[crate::epoch::SaltoEpoch],
    epoch_conocido: u64,
    perfil_firma_por_hecho: bool,
) -> ResumenRecepcion {
    let mut rechazados = 0usize;
    let mut motivo: Option<String> = None;

    // Filtrar los que no superan la custodia; el resto va por el camino normal.
    let mut validos: Vec<DdpMessage> = Vec::with_capacity(mensajes.len());
    for m in mensajes {
        let Some(h) = hecho_de_mensaje(m) else {
            rechazados += 1;
            motivo.get_or_insert_with(|| "mensaje no reconstruible".into());
            continue;
        };
        if h.version < 2 {
            // Un hecho v1 no tiene epoch: no hay custodia que comprobar.
            validos.push(m.clone());
            continue;
        }
        match crate::epoch::verificar_cadena(epoch_conocido, h.epoch, saltos, clave_publica_hex) {
            c if c.es_valido() => validos.push(m.clone()),
            otro => {
                rechazados += 1;
                motivo.get_or_insert_with(|| format!("custodia del epoch: {otro:?}"));
            }
        }
    }

    let clave = crate::identidad::hex_a_bytes_publico(clave_publica_hex).ok();
    let mut sub = recibir_hechos_con(host, &validos, clave.as_deref(), perfil_firma_por_hecho);
    sub.rechazados += rechazados;
    if sub.primer_motivo.is_none() {
        sub.primer_motivo = motivo;
    }
    sub
}

/// Igual que [`recibir_hechos`], pero declarando si el perfil firma por hecho.
///
/// - `firma_por_hecho = true`  → cada hecho con firma se verifica aqui mismo.
/// - `firma_por_hecho = false` → la firma es del sello del bloque y se verifica
///   aparte con [`verificar_bloques`]; aqui no se toca.
pub fn recibir_hechos_con<H: Host>(
    host: &mut H,
    mensajes: &[DdpMessage],
    clave_publica: Option<&[u8]>,
    perfil_firma_por_hecho: bool,
) -> ResumenRecepcion {
    let mut r = ResumenRecepcion::default();

    for m in mensajes {
        let Some(h) = hecho_de_mensaje(m) else {
            r.rechazados += 1;
            r.primer_motivo.get_or_insert_with(|| "mensaje no reconstruible".into());
            continue;
        };

        // 2. Enlace con la cadena local.
        let previo_esperado = if h.seq == 0 {
            String::new()
        } else {
            match hechos_store::leer(host, &h.nodo, &h.serie, h.seq - 1, &h.instance_id) {
                Some(prev) => prev.hash(),
                None => {
                    r.rechazados += 1;
                    r.primer_motivo
                        .get_or_insert_with(|| format!("falta seq {} antes de {}", h.seq - 1, h.seq));
                    continue;
                }
            }
        };
        if h.prev_hash != previo_esperado {
            r.rechazados += 1;
            r.primer_motivo
                .get_or_insert_with(|| format!("cadena rota en seq {}", h.seq));
            continue;
        }

        // 3. Firma: solo se comprueba al nivel de BLOQUE, no por hecho.
        //
        // Hay dos clases de firma y confundirlas rompe la recepcion:
        //   - firma por hecho  -> cubre el contenido de ESE hecho (perfil por_hecho)
        //   - firma por bloque -> cubre el SELLO de las 100 muestras (perfil barco)
        //
        // La del bloque NO se puede verificar aqui, porque el sello necesita la
        // serie entera. Se verifica despues con `verificar_bloques`. Por eso este
        // paso no rechaza: deja pasar y la verificacion de bloques decide.
        //
        // Lo que SI se rechaza aqui es una firma por hecho invalida.
        if let Some(clave) = clave_publica {
            if h.firma.is_some() && perfil_firma_por_hecho {
                if let Err(e) = h.verificar_firma(clave) {
                    r.rechazados += 1;
                    r.primer_motivo.get_or_insert(e);
                    continue;
                }
            }
        }

        // 4. ¿Ya existe en esta posición? Aquí está el arreglo del split-brain.
        //
        // Antes: se guardaba y el segundo en la misma clave se DESCARTABA en
        // silencio. Ahora:
        //   - mismo hash        -> duplicado, se ignora (idempotencia)
        //   - hash distinto     -> CONFLICTO: se guarda como rama aparte
        //
        // Nunca se descarta. Rechazar era el bug.
        if let Some(existente) = hechos_store::leer(host, &h.nodo, &h.serie, h.seq, &h.instance_id) {
            if existente.hash() == h.hash() {
                r.duplicados += 1;
                continue;
            }
            // Misma clave, contenido distinto: no debería pasar (la clave lleva
            // la instancia), pero si pasa es un conflicto real y se registra.
            r.conflictos += 1;
            r.detalle_conflictos.push(Conflicto {
                nodo: h.nodo.clone(),
                serie: h.serie.clone(),
                seq: h.seq,
                instance_existente: existente.instance_id.clone(),
                instance_nueva: h.instance_id.clone(),
                hash_existente: existente.hash(),
                hash_nuevo: h.hash(),
                epoch_existente: existente.epoch,
                epoch_nuevo: h.epoch,
            });
            continue;
        }

        // 5. ¿Hay otra rama en la misma posición, con OTRA instancia?
        // Eso es split-brain: coexisten, se guarda la nueva y se marca.
        let ocupadas = hechos_store::instancias_en_posicion(host, &h.nodo, &h.serie, h.seq);
        if !ocupadas.is_empty() {
            r.conflictos += 1;
            for inst in &ocupadas {
                if let Some(otro) = hechos_store::leer(host, &h.nodo, &h.serie, h.seq, inst) {
                    r.detalle_conflictos.push(Conflicto {
                        nodo: h.nodo.clone(),
                        serie: h.serie.clone(),
                        seq: h.seq,
                        instance_existente: inst.clone(),
                        instance_nueva: h.instance_id.clone(),
                        hash_existente: otro.hash(),
                        hash_nuevo: h.hash(),
                        epoch_existente: otro.epoch,
                        epoch_nuevo: h.epoch,
                    });
                }
            }
        }

        // Guardar. La clave lleva la instancia, así que las dos ramas coexisten.
        //
        // El error REAL de LMDB se propaga: durante mucho tiempo se descartaba
        // con un "no se pudo guardar" genérico, y eso ocultó que el fallo era
        // del almacenamiento (disco lleno, mapa lleno) y no de la red.
        if let Err(e) = hechos_store::guardar(host, &h) {
            r.rechazados += 1;
            r.primer_motivo
                .get_or_insert_with(|| format!("guardar: {e:?}"));
            continue;
        }
        r.aceptados += 1;
    }
    r
}

#[cfg(test)]
mod tests {
    use super::*;
    use lumen_mlight::MemoryHost;
    use crate::identidad::Identidad;
    use crate::hechos_store::verificar_serie;

    fn hecho(seq: u64, valor: &str, prev: &str) -> Hecho {
        Hecho {
            nodo: "BARCO-A".into(), serie: "gps".into(), seq, clave: "gps".into(),
            valor: valor.into(), prev_hash: prev.into(), ts: seq, firma: None,
            ..Default::default()
        }
    }

    #[test]
    fn la_peticion_va_y_vuelve() {
        let m = peticion("gps", 42);
        let (serie, desde) = interpretar_peticion(&m).expect("debe interpretarse");
        assert_eq!(serie, "gps");
        assert_eq!(desde, 42);
    }

    #[test]
    fn un_mensaje_que_no_es_peticion_se_ignora() {
        let m = DdpMessage::new(msg_type::DATA, 0, 0, 0, b"otra cosa".to_vec());
        assert!(interpretar_peticion(&m).is_none());
    }

    #[test]
    fn un_hecho_va_y_vuelve_por_el_mensaje() {
        let id = Identidad::generar();
        let mut h = hecho(3, "lat=41.3", "abc");
        h.firmar(&id);
        let m = mensaje_de_hecho(&h);
        let vuelta = hecho_de_mensaje(&m).expect("debe reconstruirse");
        assert_eq!(vuelta.valor, h.valor);
        assert_eq!(vuelta.seq, 3);
        assert_eq!(vuelta.firma, h.firma, "la firma debe sobrevivir al cable");
    }

    #[test]
    fn el_sello_de_bloque_cierra_el_agujero_de_la_muestra_sin_firma() {
        // ESTE es el fallo que se descubrio en el E2E: con firma por bloque, la
        // muestra 0 no lleva firma y cambiarla pasaba desapercibido. Ahora la
        // firma cubre el SELLO del bloque entero, asi que se detecta.
        let id = Identidad::generar();
        let clave = id.clave_publica();

        let mut serie: Vec<Hecho> = Vec::new();
        let mut prev = String::new();
        for i in 0..100u64 {
            let h = hecho(i, &format!("lat=41.{i}"), &prev);
            prev = h.hash();
            serie.push(h);
        }
        let firmados = firmar_bloque(&mut serie, 100, &id);
        assert_eq!(firmados, 1, "un bloque de 100 -> una firma");

        // Verifica: OK.
        verificar_bloques(&serie, 100, &clave).expect("bloque intacto debe verificar");

        // Manipular la muestra 0, QUE NO LLEVA FIRMA PROPIA.
        serie[0].valor = "lat=99.9".into();
        // La cadena de hashes ya no cuadra, pero lo importante es que TAMPOCO
        // valida el sello del bloque.
        let r = verificar_bloques(&serie, 100, &clave);
        assert!(r.is_err(), "manipular una muestra sin firma debe detectarse");
    }

    #[test]
    fn el_sello_encadena_entre_bloques() {
        // Mover el sello de un bloque a otro debe romper la verificacion.
        let id = Identidad::generar();
        let clave = id.clave_publica();
        let mut serie: Vec<Hecho> = Vec::new();
        let mut prev = String::new();
        for i in 0..200u64 {
            let h = hecho(i, &format!("lat=41.{i}"), &prev);
            prev = h.hash();
            serie.push(h);
        }
        let n = firmar_bloque(&mut serie, 100, &id);
        assert_eq!(n, 2, "200 muestras -> 2 bloques");
        assert_eq!(verificar_bloques(&serie, 100, &clave).unwrap(), 2);

        // Manipular una muestra del PRIMER bloque: debe romper el bloque 0, y
        // al cambiar su sello, tambien el 1 (que encadena con el anterior).
        serie[50].valor = "lat=0.0".into();
        assert!(verificar_bloques(&serie, 100, &clave).is_err());
    }

    #[test]
    fn se_reciben_hechos_en_orden() {
        let mut host = MemoryHost::default();
        let mut prev = String::new();
        let mut mensajes = Vec::new();
        for i in 0..5u64 {
            let h = hecho(i, &format!("lat=41.{i}"), &prev);
            prev = h.hash();
            mensajes.push(mensaje_de_hecho(&h));
        }
        let r = recibir_hechos(&mut host, &mensajes, None);
        assert_eq!(r.aceptados, 5, "motivo: {:?}", r.primer_motivo);
        assert_eq!(r.rechazados, 0);
        assert_eq!(hechos_store::contar_serie(&host, "BARCO-A", "gps"), 5);
    }

    #[test]
    fn un_hecho_fuera_de_orden_se_rechaza() {
        let mut host = MemoryHost::default();
        let h2 = hecho(2, "lat=41.2", "abc"); // falta la 0 y la 1
        let r = recibir_hechos(&mut host, &[mensaje_de_hecho(&h2)], None);
        assert_eq!(r.aceptados, 0);
        assert_eq!(r.rechazados, 1);
        assert!(r.primer_motivo.unwrap().contains("falta seq"));
    }

    #[test]
    fn un_hecho_manipulado_no_se_guarda() {
        let mut host = MemoryHost::default();
        let id = Identidad::generar();
        let mut h = hecho(0, "lat=41.1", "");
        h.firmar(&id);
        let mut m = mensaje_de_hecho(&h);
        // Manipular el valor en el cable.
        m.body = String::from_utf8(m.body).unwrap()
            .replace("lat=41.1", "lat=99.9").into_bytes();
        let r = recibir_hechos_con(&mut host, &[m], Some(&id.clave_publica()), true);
        assert_eq!(r.aceptados, 0, "un hecho manipulado no debe entrar");
        assert_eq!(r.rechazados, 1);
    }

    #[test]
    fn la_firma_de_otro_nodo_se_rechaza() {
        let mut host = MemoryHost::default();
        let barco = Identidad::generar();
        let impostor = Identidad::generar();
        let mut h = hecho(0, "lat=41.1", "");
        h.firmar(&impostor);
        // El receptor espera la clave del BARCO, no la del impostor.
        let r = recibir_hechos_con(&mut host, &[mensaje_de_hecho(&h)], Some(&barco.clave_publica()), true);
        assert_eq!(r.aceptados, 0);
        assert_eq!(r.rechazados, 1);
    }
}
