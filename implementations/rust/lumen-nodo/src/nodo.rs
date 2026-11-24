//! El bucle del nodo: escucha, valida el frame, lo aplica, responde ACK.
//!
//! Cada decisión está puesta para poder explicarla en voz alta:
//! - un frame que no se entiende **no** se aplica, y se responde FAILURE
//! - un frame válido se aplica y se responde SUCCESS
//! - hay techo de tamaño por frame: un par no puede pedirnos memoria sin límite
//! - hay techo de frames por conexión: una conexión no es un grifo infinito
//! - si el destino está en solo lectura, se responde FAILURE sin tocar la PDB

use std::time::{Duration, Instant};

use lumen::frame::{self, ParseResult};
use lumen::quic::{pinned_client_config, QuicEndpoint};
use lumen::transport::Transport;
use lumen_znet::{ddp_to_frame, frame_to_ddp, msg_type, DdpMessage};

use crate::aplicar::{parsear_set, ErrorAplicar};
use crate::destino::{aplicar, Aplicado, Destino};
use crate::profile::{Identity, Profile};

/// Techo de bytes que se acumulan esperando un frame completo.
/// Un frame mayor que esto se descarta: no vamos a crecer sin límite por un
/// par que dice "voy a mandar 400 MB".
pub const MAX_FRAME: usize = 1 << 20; // 1 MiB

/// Frames máximos atendidos por conexión antes de cerrarla.
pub const MAX_FRAMES_POR_CONEXION: usize = 10_000;

/// Tiempo de espera para el primer byte de una conexión.
pub const TIMEOUT_CONEXION: Duration = Duration::from_secs(30);

/// Qué le pasó a una conexión, para poder registrarlo.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ResumenConexion {
    pub frames_aplicados: usize,
    pub frames_fallidos: usize,
    pub frames_grandes: usize,
    pub bytes_entrantes: usize,
    pub cierre: &'static str,
}

/// Atiende UNA conexión ya aceptada hasta que se cierra o se agota.
///
/// Deliberadamente secuencial: un nodo pequeño no necesita concurrencia para
/// demostrar el camino, y la concurrencia mal hecha es cómo se pierde un frame
/// sin enterarse. Se añadirá cuando haya volumen medido, no antes.
pub fn atender<T: Transport, D: Destino + crate::cadena::EstadoCadena>(
    transporte: &mut T,
    destino: &mut D,
    encadenar: bool,
    log: &mut dyn FnMut(&str),
) -> ResumenConexion {
    let mut resumen = ResumenConexion::default();
    let mut buf: Vec<u8> = Vec::new();
    let inicio = Instant::now();

    loop {
        if resumen.frames_aplicados + resumen.frames_fallidos >= MAX_FRAMES_POR_CONEXION {
            resumen.cierre = "techo de frames";
            log("cerrando: techo de frames alcanzado");
            break;
        }
        if inicio.elapsed() > TIMEOUT_CONEXION {
            resumen.cierre = "timeout";
            log("cerrando: timeout de conexion");
            break;
        }

        let mut chunk = [0u8; 8192];
        let n = match transporte.read(&mut chunk) {
            Ok(0) => {
                resumen.cierre = "par cerro";
                break;
            }
            Ok(n) => n,
            Err(e) => {
                resumen.cierre = "error de lectura";
                log(&format!("error leyendo: {e}"));
                break;
            }
        };
        resumen.bytes_entrantes += n;
        buf.extend_from_slice(&chunk[..n]);

        if buf.len() > MAX_FRAME {
            resumen.frames_grandes += 1;
            log(&format!(
                "frame demasiado grande ({} > {}): descartado sin aplicar",
                buf.len(),
                MAX_FRAME
            ));
            buf.clear();
            continue;
        }

        // Procesar todos los frames completos que haya en el buffer.
        loop {
            let parsed = frame::parse(&buf);
            let ParseResult::Complete { frame, consumed } = parsed else {
                break;
            };
            let tipo = frame.frame_type;
            let payload = frame.payload.to_vec();
            buf.drain(..consumed);

            let respuesta = procesar(tipo, &payload, destino, encadenar, log);
            resumen.frames_aplicados += 1;

            let (ft, fl, p) = ddp_to_frame(&respuesta);
            let mut out = vec![0u8; frame::build_size(p.len())];
            let m = frame::build(ft, fl, &p, &mut out);
            if let Err(e) = transporte.write_all(&out[..m]).and_then(|_| transporte.flush()) {
                resumen.cierre = "error de escritura";
                log(&format!("error respondiendo: {e}"));
                return resumen;
            }
        }
    }
    resumen
}

/// Decide qué hacer con un frame recibido y construye la respuesta DDP.
pub fn procesar<D: Destino + crate::cadena::EstadoCadena>(
    tipo: u8,
    payload: &[u8],
    destino: &mut D,
    encadenar: bool,
    log: &mut dyn FnMut(&str),
) -> DdpMessage {
    // El frame LUMEN lleva su propio tipo; el DDP va dentro. Si no es DATA,
    // no hay nada que aplicar (NOTIFY se ignora a propósito: no hay gossip).
    match frame_to_ddp(tipo, payload) {
        Ok(msg) => {
            if msg.kind != msg_type::DATA {
                log(&format!("frame tipo 0x{:02x} ignorado (no es DATA)", tipo));
                return DdpMessage::new(msg_type::EMPTY, msg.num1, msg.num2, 0, Vec::new());
            }
            match aplicar_payload_con(&msg.body, destino, encadenar, log) {
                Ok(a) => {
                    log(&format!(
                        "aplicado ^{}({})=<{} bytes>",
                        a.ns,
                        a.subs.join(","),
                        a.bytes
                    ));
                    DdpMessage::new(msg_type::SUCCESS, msg.num1, msg.num2, 0, Vec::new())
                }
                Err(e) => {
                    log(&format!("rechazado: {e}"));
                    let detalle = e.to_string().into_bytes();
                    DdpMessage::new(msg_type::FAILURE, msg.num1, msg.num2, 0, detalle)
                }
            }
        }
        Err(e) => {
            log(&format!("frame no es DDP: {e}"));
            // Sin num1/num2 legibles, respondemos con ceros: el par sabrá que
            // su frame no se entendió.
            DdpMessage::new(msg_type::FAILURE, 0, 0, 0, e.to_string().into_bytes())
        }
    }
}

/// Parsea y aplica la carga. Un solo sitio donde se decide qué es aceptable.
pub fn aplicar_payload<D: Destino + crate::cadena::EstadoCadena>(
    payload: &[u8],
    destino: &mut D,
    log: &mut dyn FnMut(&str),
) -> Result<Aplicado, ErrorAplicar> {
    aplicar_payload_con(payload, destino, false, log)
}

/// Igual que `aplicar_payload`, con el encadenado explícito.
///
/// `encadenar=true` (perfil con `sign=hash-chain`) firma la muestra: en vez de
/// guardar el valor crudo, guarda `valor|prev|hash`.
pub fn aplicar_payload_con<D: Destino + crate::cadena::EstadoCadena>(
    payload: &[u8],
    destino: &mut D,
    encadenar: bool,
    log: &mut dyn FnMut(&str),
) -> Result<Aplicado, ErrorAplicar> {
    let w = parsear_set(payload)?;
    if w.ns.eq_ignore_ascii_case("CONFIG")
        || w.ns.eq_ignore_ascii_case("SYSINFO")
        || w.ns.eq_ignore_ascii_case(crate::cadena::NS_CADENA)
    {
        // Un par no cambia la configuración del nodo por la red, ni el estado
        // de las cadenas (si pudiera, podría falsear el "último hash" y
        // reescribir el pasado de una serie).
        return Err(ErrorAplicar::NsInvalido(format!(
            "^{} no se acepta por red",
            w.ns
        )));
    }
    log(&format!("escritura ^{}({})", w.ns, w.subs.join(",")));
    if encadenar {
        return crate::cadena::aplicar_encadenado_destino(destino, &w, log);
    }
    aplicar(destino, &w)
}

/// Arranca el nodo servidor según el perfil. Devuelve el endpoint ya escuchando.
///
/// `pin` es la huella que, si `identity=pin`, se exige al par. El servidor no
/// la usa (él presenta su certificado); se pasa aquí para que el llamador tenga
/// TODO lo que el perfil dice en un solo sitio visible.
pub fn escuchar(perfil: &Profile, pin: Option<&str>) -> Result<(QuicEndpoint, String), String> {
    let addr = perfil
        .listen
        .ok_or_else(|| "el perfil no tiene direccion de escucha".to_string())?;
    if perfil.identity == Identity::Pin && pin.is_none() {
        return Err("identity=pin pero no se paso la huella".into());
    }
    // `server_with_pin` genera certificado propio y devuelve su huella: el
    // operador la fija en el nodo contrario. El servidor no verifica al
    // cliente (no hay mTLS): eso es `identity=pubkey`, que no existe todavía.
    lumen::quic::server_with_pin(&addr.to_string())
        .map_err(|e| format!("no se pudo escuchar en {addr}: {e}"))
}

/// Cliente listo para conectar, con la identidad que diga el perfil.
pub fn conectar_como_cliente(perfil: &Profile) -> Result<QuicEndpoint, String> {
    match perfil.identity {
        Identity::Pin => {
            let hex = perfil
                .pin
                .as_deref()
                .ok_or_else(|| "identity=pin sin huella".to_string())?;
            let cfg = pinned_client_config(hex).map_err(|e| format!("pin invalido: {e}"))?;
            QuicEndpoint::client_with_config(Some(cfg)).map_err(|e| e.to_string())
        }
        Identity::None => QuicEndpoint::client().map_err(|e| e.to_string()),
        Identity::Pubkey => Err("identity=pubkey no implementado".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::destino::DestinoMemoria;

    fn frame_ddp(payload: &[u8]) -> Vec<u8> {
        let msg = DdpMessage::new(msg_type::DATA, 7, 3, 0, payload.to_vec());
        let (ft, fl, p) = ddp_to_frame(&msg);
        let mut out = vec![0u8; frame::build_size(p.len())];
        let n = frame::build(ft, fl, &p, &mut out);
        out.truncate(n);
        out
    }

    /// Transporte en memoria: permite probar el bucle SIN red.
    struct Mem {
        entrada: Vec<u8>,
        pos: usize,
        salida: Vec<u8>,
    }
    impl Transport for Mem {
        fn read(&mut self, b: &mut [u8]) -> std::io::Result<usize> {
            let n = (self.entrada.len() - self.pos).min(b.len());
            b[..n].copy_from_slice(&self.entrada[self.pos..self.pos + n]);
            self.pos += n;
            Ok(n)
        }
        fn write_all(&mut self, b: &[u8]) -> std::io::Result<()> {
            self.salida.extend_from_slice(b);
            Ok(())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }

    #[test]
    fn aplica_un_frame_y_responde_ack() {
        let carga = b"^FLOTA(BARCO,lat)=41.38";
        let mut t = Mem {
            entrada: frame_ddp(carga),
            pos: 0,
            salida: Vec::new(),
        };
        let mut d = DestinoMemoria::default();
        let mut logs = Vec::new();
        let r = atender(&mut t, &mut d, false, &mut |s| logs.push(s.to_string()));

        assert_eq!(r.frames_aplicados, 1);
        assert_eq!(r.frames_fallidos, 0);
        assert_eq!(d.escrituras.len(), 1);
        assert_eq!(d.escrituras[0].0, "FLOTA");
        assert_eq!(d.escrituras[0].2, "41.38");

        // La salida debe ser un frame DDP de tipo SUCCESS.
        let ParseResult::Complete { frame, .. } = frame::parse(&t.salida) else {
            panic!("la respuesta no es un frame completo");
        };
        let resp = frame_to_ddp(frame.frame_type, frame.payload).unwrap();
        assert_eq!(resp.kind, msg_type::SUCCESS);
        assert_eq!(resp.num1, 7, "el id de mensaje debe volver intacto");
        assert_eq!(resp.num2, 3, "el circuito debe volver intacto");
    }

    #[test]
    fn varios_frames_en_un_solo_chunk() {
        let mut entrada = frame_ddp(b"^A(k)=1");
        entrada.extend(frame_ddp(b"^B(k)=2"));
        let mut t = Mem {
            entrada,
            pos: 0,
            salida: Vec::new(),
        };
        let mut d = DestinoMemoria::default();
        let r = atender(&mut t, &mut d, false, &mut |_| {});
        assert_eq!(r.frames_aplicados, 2);
        assert_eq!(d.escrituras.len(), 2);
        assert_eq!(d.escrituras[0].0, "A");
        assert_eq!(d.escrituras[1].0, "B");
    }

    #[test]
    fn carga_invalida_no_escribe_y_responde_failure() {
        let mut t = Mem {
            entrada: frame_ddp(b"esto no es un set"),
            pos: 0,
            salida: Vec::new(),
        };
        let mut d = DestinoMemoria::default();
        let r = atender(&mut t, &mut d, false, &mut |_| {});
        assert_eq!(r.frames_aplicados, 1);
        assert!(d.escrituras.is_empty(), "no debe escribir nada");
        let ParseResult::Complete { frame, .. } = frame::parse(&t.salida) else {
            panic!("sin respuesta");
        };
        let resp = frame_to_ddp(frame.frame_type, frame.payload).unwrap();
        assert_eq!(resp.kind, msg_type::FAILURE);
    }

    #[test]
    fn config_por_red_se_rechaza() {
        let mut d = DestinoMemoria::default();
        let mut logs = Vec::new();
        let e = aplicar_payload(b"^CONFIG(x)=y", &mut d, &mut |s| logs.push(s.to_string()))
            .unwrap_err();
        assert!(matches!(e, ErrorAplicar::NsInvalido(_)));
        assert!(d.escrituras.is_empty());
    }

    #[test]
    fn sysinfo_por_red_se_rechaza() {
        let mut d = DestinoMemoria::default();
        assert!(aplicar_payload(b"^SYSINFO(x)=y", &mut d, &mut |_| {}).is_err());
    }

    #[test]
    fn destino_solo_lectura_no_escribe() {
        let mut d = DestinoMemoria {
            solo_lectura: true,
            ..Default::default()
        };
        let e = aplicar_payload(b"^A(k)=1", &mut d, &mut |_| {}).unwrap_err();
        assert_eq!(e, ErrorAplicar::NoAceptaEscrituras);
        assert!(d.escrituras.is_empty());
    }

    /// Un frame que declara un payload razonable pero deja el buffer a medias
    /// NO debe aplicarse: se espera a tenerlo completo. Este test existe
    /// porque el primero que escribi usaba un byte 0x7f como "longitud
    /// absurda" y resulta que NO lo es: con el bit alto a 0 es una longitud
    /// corta (<64). Con el, `frame::parse` cerraba frames validos de 0 bytes
    /// y el nodo los contaba como aplicados. El test estaba mal y el bucle
    /// estaba bien; esto lo fija.
    #[test]
    fn frame_truncado_no_se_aplica() {
        // Longitud declarada 100 (u16), pero solo llegan 10 bytes de payload.
        let mut buf = vec![0x80u8, 100, 0, 0x01, 0x00];
        buf.extend_from_slice(&[0u8; 10]);
        let mut t = Mem {
            entrada: buf,
            pos: 0,
            salida: Vec::new(),
        };
        let mut d = DestinoMemoria::default();
        let r = atender(&mut t, &mut d, false, &mut |_| {});
        assert_eq!(r.frames_aplicados, 0, "un frame truncado NO se aplica");
        assert!(d.escrituras.is_empty());
        assert_eq!(r.cierre, "par cerro");
    }

    /// Un buffer que supera MAX_FRAME sin contener un frame completo se
    /// descarta y se anota, sin contar frames inexistentes.
    #[test]
    fn buffer_desmesurado_se_descarta_sin_aplicar() {
        // Hyb128 modo u32 con valor enorme: imposible de completar.
        let mut buf = vec![0xC0u8, 0xFF, 0xFF, 0xFF, 0x7F];
        buf.extend(std::iter::repeat(0u8).take(MAX_FRAME + 10));
        let mut t = Mem {
            entrada: buf,
            pos: 0,
            salida: Vec::new(),
        };
        let mut d = DestinoMemoria::default();
        let r = atender(&mut t, &mut d, false, &mut |_| {});
        assert!(d.escrituras.is_empty());
        assert_eq!(r.frames_aplicados, 0, "no debe contar frames inexistentes");
        assert!(
            r.frames_grandes > 0,
            "debe registrar que descarto un buffer desmesurado (resumen: {r:?})"
        );
    }
}
