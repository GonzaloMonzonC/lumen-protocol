//! Integración real: los frames que produce ZNET deben ser parseables por el codec LUMEN.
//!
//! Las pruebas unitarias de `lib.rs` demuestran que el mapeo DDP <-> LUMEN es reversible
//! *consigo mismo*. Eso no prueba nada: un codec que se entiende solo con sí mismo siempre
//! pasa. Este test usa `lumen::frame::build` y `lumen::frame::parse` — el codec **real** —
//! para demostrar que un mensaje DDP viaja en un frame LUMEN válido.

use lumen::frame::{self, ParseResult};
use lumen_znet::{ddp_to_frame, frame_to_ddp, msg_type, DdpMessage, DDP_HEADER_LEN};

/// Un mensaje DDP construido como lo haría `DDPSRV`.
fn mensaje_de_ddpsrv() -> DdpMessage {
    DdpMessage::new(
        msg_type::DATA,
        // num1: el id de mensaje que DDPSRV arma con $ZCHAR($ZB##100, ...)
        0x012C,
        // num2: el número de circuito
        7,
        0,
        b"^SYS(\"JOURNAL\",1)"[..].to_vec(),
    )
}

#[test]
fn un_mensaje_ddp_cabe_en_un_frame_lumen_valido() {
    let msg = mensaje_de_ddpsrv();

    // 1. Traducir a piezas de frame LUMEN.
    let (frame_type, flags, payload) = ddp_to_frame(&msg);

    // 2. Construirlo con el codec REAL de LUMEN.
    let mut buf = vec![0u8; frame::build_size(payload.len())];
    let written = frame::build(frame_type, flags, &payload, &mut buf);
    assert_eq!(written, buf.len(), "el tamaño calculado no coincide con el escrito");

    // 3. Parsearlo con el parser REAL de LUMEN.
    let (parsed, consumed) = match frame::parse(&buf) {
        ParseResult::Complete { frame, consumed } => (frame, consumed),
        other => panic!("LUMEN no pudo parsear el frame: {other:?}"),
    };
    assert_eq!(consumed, written, "LUMEN consumio {consumed}, se escribieron {written}");

    // 4. Los campos sobreviven.
    assert_eq!(parsed.frame_type, msg_type::DATA);
    assert_eq!(parsed.flags, 0);

    // 5. Y el mensaje DDP se recupera intacto.
    let vuelta = frame_to_ddp(parsed.frame_type, parsed.payload).unwrap();
    assert_eq!(vuelta.num1, 0x012C);
    assert_eq!(vuelta.num2, 7);
    assert_eq!(vuelta.body, msg.body);
}

#[test]
fn el_overhead_de_lumen_es_menor_que_el_de_ddp_crudo() {
    // Un mensaje DDP pequeño, el caso típico de un ACK o un cambio de journal.
    let msg = DdpMessage::new(msg_type::SUCCESS, 1, 2, 0, Vec::new());
    let ddp_bytes = msg.encode();
    assert_eq!(ddp_bytes.len(), DDP_HEADER_LEN);

    // En LUMEN el tipo va en la cabecera del frame, así que el payload son 5 bytes.
    let (ftype, flags, payload) = ddp_to_frame(&msg);
    let mut buf = vec![0u8; frame::build_size(payload.len())];
    let total = frame::build(ftype, flags, &payload, &mut buf);

    // Frame = Hyb128(len) + tipo + flags + payload(5)
    // El payload son 5 bytes porque el tipo se movió a la cabecera del frame.
    assert_eq!(payload.len(), DDP_HEADER_LEN - 1);
    assert_eq!(total, 8, "Hyb128(1) + 2 + 5 = 8 bytes");
}

#[test]
fn un_frame_lumen_ajeno_no_se_confunde_con_ddp() {
    // Payload demasiado corto para llevar la cabecera DDP restante.
    let corto = [0u8; 3];
    let mut buf = vec![0u8; frame::build_size(corto.len())];
    let n = frame::build(msg_type::DATA, 0, &corto, &mut buf);
    let parsed = match frame::parse(&buf[..n]) {
        ParseResult::Complete { frame, .. } => frame,
        other => panic!("frame no parseable: {other:?}"),
    };
    assert!(
        frame_to_ddp(parsed.frame_type, parsed.payload).is_err(),
        "un payload de 3 bytes no es un mensaje DDP y debe rechazarse"
    );
}

#[test]
fn muchos_mensajes_seguidos_se_parsean_uno_a_uno() {
    // Esto es lo que hace DDPSRV en su bucle: recv, actuar, responder, repetir.
    let mensajes: Vec<DdpMessage> = (0..50)
        .map(|i| DdpMessage::new(msg_type::DATA, i, 1, 0, format!("msg-{i}").into_bytes()))
        .collect();

    let mut stream = Vec::new();
    for m in &mensajes {
        let (ft, fl, p) = ddp_to_frame(m);
        let mut buf = vec![0u8; frame::build_size(p.len())];
        let n = frame::build(ft, fl, &p, &mut buf);
        stream.extend_from_slice(&buf[..n]);
    }

    // Leer el stream frame a frame, como haría un receptor de verdad.
    let mut pos = 0;
    let mut recuperados = Vec::new();
    while pos < stream.len() {
        match frame::parse(&stream[pos..]) {
            ParseResult::Complete { frame, consumed } => {
                let msg = frame_to_ddp(frame.frame_type, frame.payload).unwrap();
                recuperados.push(msg);
                // `consumed` es exactamente lo que ocupa este frame: sin recalcular nada.
                pos += consumed;
            }
            other => panic!("stream cortado en {pos}: {other:?}"),
        }
    }

    assert_eq!(recuperados.len(), 50);
    for (i, m) in recuperados.iter().enumerate() {
        assert_eq!(m.num1, i as u16);
        assert_eq!(m.body, format!("msg-{i}").into_bytes());
    }
}
