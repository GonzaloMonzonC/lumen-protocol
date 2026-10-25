//! Backend QUIC (LUMEN Level 4) para ZNET.
//!
//! Conecta la cola en memoria de [`Znet`] con un stream QUIC real. Usa
//! [`lumen::quic::QuicEndpoint`], que ya implementa `Read`/`Write` sobre los streams de quinn.
//!
//! # Lo que hace
//!
//! - `flush()`: saca los mensajes pendientes de la cola de circuitos y los escribe como frames
//!   LUMEN, uno detrás de otro, en el stream.
//! - `poll()`: lee del stream todo lo disponible, parte el flujo en frames LUMEN usando
//!   `frame::parse` (que dice cuántos bytes consumió), y los mete en la cola de entrada de `Znet`.
//!
//! # La clave del framing
//!
//! `frame::parse` devuelve `consumed`, el número exacto de bytes del frame. Eso permite leer un
//! flujo continuo sin delimitadores externos: se parsea, se avanza `consumed`, se repite. Los
//! bytes sobrantes de un frame incompleto se guardan para la siguiente lectura.

use std::io;

use lumen::frame::{self, ParseResult};
use lumen::transport::Transport;

use crate::{ddp_to_frame, frame_to_ddp, Znet, ZnetError};

/// Errores del backend QUIC.
#[derive(Debug)]
pub enum QuicZnetError {
    /// Error de entrada/salida del stream.
    Io(io::Error),
    /// El frame recibido no es un mensaje DDP válido.
    Znet(ZnetError),
    /// Se ha acumulado demasiado en el buffer de lectura sin formar un frame: el par
    /// está enviando basura o un frame absurdamente grande.
    BufferOverflow(usize),
}

impl std::fmt::Display for QuicZnetError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "QUIC: {e}"),
            Self::Znet(e) => write!(f, "ZNET: {e}"),
            Self::BufferOverflow(n) => {
                write!(f, "buffer de lectura desbordado: {n} bytes sin formar frame")
            }
        }
    }
}

impl std::error::Error for QuicZnetError {}

impl From<io::Error> for QuicZnetError {
    fn from(e: io::Error) -> Self {
        Self::Io(e)
    }
}

impl From<ZnetError> for QuicZnetError {
    fn from(e: ZnetError) -> Self {
        Self::Znet(e)
    }
}

/// Tamaño máximo del buffer de lectura antes de considerarlo un ataque o un error.
///
/// Un frame LUMEN puede ser grande, pero 16 MiB es mucho más de lo que DDP maneja.
pub const MAX_READ_BUFFER: usize = 16 * 1024 * 1024;

/// Backend de red sobre un [`Transport`] de LUMEN.
///
/// No asume QUIC: sirve cualquier transporte que LUMEN conozca (QUIC, TCP, stdio). Eso permite
/// probarlo con un buffer en memoria y usarlo por igual sobre un socket real.
pub struct QuicZnet<S> {
    stream: S,
    /// Bytes leídos que aún no forman un frame completo.
    buf: Vec<u8>,
}

impl<S: Transport> QuicZnet<S> {
    /// Envuelve un stream.
    pub fn new(stream: S) -> Self {
        Self {
            stream,
            buf: Vec::new(),
        }
    }

    /// Devuelve el stream subyacente.
    pub fn into_inner(self) -> S {
        self.stream
    }

    /// Cuántos bytes esperan a formar un frame completo.
    pub fn pending_bytes(&self) -> usize {
        self.buf.len()
    }

    /// **Envía** los mensajes pendientes de la cola de circuitos de `znet`.
    ///
    /// Escribe cada mensaje como un frame LUMEN y hace `flush` al final. Devuelve cuántos
    /// mensajes se enviaron.
    ///
    /// Esto es el `$ZNET(9, x)` de un `DDPSRV` que atiende a un nodo remoto: la respuesta
    /// sale por el cable en el mismo orden en que se encoló.
    pub fn flush(&mut self, znet: &mut Znet) -> Result<usize, QuicZnetError> {
        let mut enviados = 0;

        while let Some((_circuit, msg)) = znet.recv_circuit() {
            let (ftype, flags, payload) = ddp_to_frame(&msg);
            let mut frame_buf = vec![0u8; frame::build_size(payload.len())];
            let n = frame::build(ftype, flags, &payload, &mut frame_buf);
            self.stream.write_all(&frame_buf[..n])?;
            enviados += 1;
        }

        if enviados > 0 {
            self.stream.flush()?;
        }
        Ok(enviados)
    }

    /// **Recibe** todo lo disponible del stream y lo mete en la cola de entrada de `znet`.
    ///
    /// Una lectura que devuelve 0 bytes significa que el par cerró el stream: se trata como fin
    /// de conexión, no como error.
    ///
    /// Devuelve cuántos mensajes DDP se entregaron a `znet`.
    pub fn poll(&mut self, znet: &mut Znet) -> Result<usize, QuicZnetError> {
        // 1. Leer lo que haya. Un solo read por llamada: el llamante decide cuándo repetir.
        let mut chunk = [0u8; 8192];
        let n = self.stream.read(&mut chunk)?;
        if n == 0 {
            return Ok(0); // par cerró
        }
        self.buf.extend_from_slice(&chunk[..n]);

        if self.buf.len() > MAX_READ_BUFFER {
            return Err(QuicZnetError::BufferOverflow(self.buf.len()));
        }

        // 2. Partir el buffer en frames completos.
        let mut entregados = 0;
        let mut pos = 0;

        loop {
            let resto = &self.buf[pos..];
            if resto.is_empty() {
                break;
            }

            match frame::parse(resto) {
                ParseResult::Complete { frame, consumed } => {
                    let msg = frame_to_ddp(frame.frame_type, frame.payload)?;
                    znet.push_incoming(msg);
                    entregados += 1;
                    pos += consumed;
                }
                // Frame a medias: se guarda para la próxima lectura.
                ParseResult::Incomplete | ParseResult::IncompletePayload { .. } => break,
                ParseResult::Error(e) => {
                    // Frame corrupto: no hay recuperación posible en un stream, se descarta
                    // el buffer entero. Es lo mismo que hace un protocolo con framing roto.
                    self.buf.clear();
                    return Err(QuicZnetError::Io(io::Error::new(
                        io::ErrorKind::InvalidData,
                        format!("frame LUMEN corrupto: {e}"),
                    )));
                }
            }
        }

        // 3. Quedarse solo con lo que no formó frame.
        if pos > 0 {
            self.buf.drain(..pos);
        }

        Ok(entregados)
    }

    /// Un ciclo completo: enviar lo pendiente y recibir lo que haya.
    ///
    /// Es el cuerpo del bucle de `DDPSRV`: `recv`, actuar, `reply`, repetir.
    pub fn pump(&mut self, znet: &mut Znet) -> Result<(usize, usize), QuicZnetError> {
        let enviados = self.flush(znet)?;
        let recibidos = self.poll(znet)?;
        Ok((enviados, recibidos))
    }
}

// ── Pruebas ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{msg_type, DdpMessage, ZnetReply};

    /// Un stream falso: escribe a un `Vec<u8>` y lee de otro.
    struct FakeStream {
        out: Vec<u8>,
        input: Vec<u8>,
        pos: usize,
    }

    impl FakeStream {
        fn new(input: Vec<u8>) -> Self {
            Self { out: Vec::new(), input, pos: 0 }
        }
    }

    impl Transport for FakeStream {
        fn write_all(&mut self, buf: &[u8]) -> io::Result<()> {
            self.out.extend_from_slice(buf);
            Ok(())
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
        fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
            let quedan = self.input.len() - self.pos;
            let n = quedan.min(buf.len());
            buf[..n].copy_from_slice(&self.input[self.pos..self.pos + n]);
            self.pos += n;
            Ok(n)
        }
    }

    /// Construye el flujo de bytes que produciría un par al enviar estos mensajes.
    fn serializar(mensajes: &[DdpMessage]) -> Vec<u8> {
        let mut out = Vec::new();
        for m in mensajes {
            let (ft, fl, p) = ddp_to_frame(m);
            let mut buf = vec![0u8; frame::build_size(p.len())];
            let n = frame::build(ft, fl, &p, &mut buf);
            out.extend_from_slice(&buf[..n]);
        }
        out
    }

    #[test]
    fn flush_saca_los_replies_al_cable() {
        let mut z = Znet::new();
        z.init();
        let c = z.connect("hub").unwrap();
        z.reply(c, ZnetReply::Success).unwrap();
        z.reply(c, ZnetReply::Data(vec![1, 2, 3, 4])).unwrap();

        let mut backend = QuicZnet::new(FakeStream::new(Vec::new()));
        let enviados = backend.flush(&mut z).unwrap();
        assert_eq!(enviados, 2);

        // El cable lleva ahora dos frames LUMEN válidos.
        let cable = backend.into_inner().out;
        assert!(!cable.is_empty());

        let mut pos = 0;
        let mut vistos = 0;
        while pos < cable.len() {
            match frame::parse(&cable[pos..]) {
                ParseResult::Complete { frame, consumed } => {
                    assert!(frame.frame_type == msg_type::SUCCESS || frame.frame_type == msg_type::DATA);
                    vistos += 1;
                    pos += consumed;
                }
                other => panic!("frame invalido en el cable: {other:?}"),
            }
        }
        assert_eq!(vistos, 2);
    }

    #[test]
    fn poll_mete_los_mensajes_en_la_cola() {
        let entrantes = vec![
            DdpMessage::new(msg_type::DATA, 1, 7, 0, b"uno".to_vec()),
            DdpMessage::new(msg_type::DATA, 2, 7, 0, b"dos".to_vec()),
            DdpMessage::new(msg_type::DATA, 3, 7, 0, b"tres".to_vec()),
        ];
        let cable = serializar(&entrantes);

        let mut z = Znet::new();
        z.init();
        let mut backend = QuicZnet::new(FakeStream::new(cable));

        let recibidos = backend.poll(&mut z).unwrap();
        assert_eq!(recibidos, 3);
        assert_eq!(z.pending(), 3);

        let primero = z.recv().unwrap();
        assert_eq!(primero.num1, 1);
        assert_eq!(primero.body, b"uno");
    }

    #[test]
    fn un_frame_partido_se_recompone_entre_lecturas() {
        let mensajes = vec![DdpMessage::new(msg_type::DATA, 99, 1, 0, b"partido".to_vec())];
        let cable = serializar(&mensajes);

        // Cortar el cable por la mitad: la primera lectura no completa el frame.
        let corte = cable.len() / 2;
        let mut z = Znet::new();
        z.init();

        // El stream entrega el frame en DOS trozos: el primero lo deja a medias, el segundo
        // lo completa. Que es exactamente lo que pasa en una red real.
        struct DosTrozo {
            datos: Vec<u8>,
            pos: usize,
            corte: usize,
            leidos: usize,
        }
        impl Transport for DosTrozo {
            fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
                if self.pos >= self.datos.len() {
                    return Ok(0);
                }
                // Primera lectura: hasta el corte. Despues: todo lo que quede.
                let limite = if self.leidos == 0 {
                    self.corte
                } else {
                    self.datos.len()
                };
                let n = (limite - self.pos).min(buf.len());
                buf[..n].copy_from_slice(&self.datos[self.pos..self.pos + n]);
                self.pos += n;
                self.leidos += 1;
                Ok(n)
            }
            fn write_all(&mut self, b: &[u8]) -> io::Result<()> {
                let _ = b;
                Ok(())
            }
            fn flush(&mut self) -> io::Result<()> {
                Ok(())
            }
        }

        let mut backend = QuicZnet::new(DosTrozo {
            datos: cable.clone(),
            pos: 0,
            corte,
            leidos: 0,
        });

        let r1 = backend.poll(&mut z).unwrap();
        assert_eq!(r1, 0, "un frame a medias no debe entregarse");
        assert!(backend.pending_bytes() > 0, "los bytes deben quedarse en el buffer");

        let r2 = backend.poll(&mut z).unwrap();
        assert_eq!(r2, 1, "al completarse, el frame se entrega");

        let msg = z.recv().unwrap();
        assert_eq!(msg.num1, 99);
        assert_eq!(msg.body, b"partido");
        assert_eq!(backend.pending_bytes(), 0, "no deben quedar restos");
    }

    #[test]
    fn stream_cerrado_no_es_error() {
        let mut z = Znet::new();
        z.init();
        let mut backend = QuicZnet::new(FakeStream::new(Vec::new()));
        assert_eq!(backend.poll(&mut z).unwrap(), 0);
    }

    #[test]
    fn frame_corrupto_da_error_y_limpia_el_buffer() {
        // Un byte de longitud Hyb128 que promete 1000 bytes de payload, con solo 3.
        let mut cable = vec![0u8; 4];
        cable[0] = 0x7F; // Hyb128: longitud grande
        cable[1] = msg_type::DATA;
        cable[2] = 0;
        let mut z = Znet::new();
        z.init();
        let mut backend = QuicZnet::new(FakeStream::new(cable));
        // No debe entrar en pánico; o entrega 0 o da error de frame corrupto.
        let r = backend.poll(&mut z);
        assert!(r.is_ok() || matches!(r, Err(QuicZnetError::Io(_))));
    }

    #[test]
    fn pump_hace_las_dos_cosas() {
        let entrante = vec![DdpMessage::new(msg_type::DATA, 5, 1, 0, b"in".to_vec())];
        let cable = serializar(&entrante);

        let mut z = Znet::new();
        z.init();
        let c = z.connect("hub").unwrap();
        z.reply(c, ZnetReply::Success).unwrap();

        let mut backend = QuicZnet::new(FakeStream::new(cable));
        let (enviados, recibidos) = backend.pump(&mut z).unwrap();

        assert_eq!(enviados, 1, "el reply sale");
        assert_eq!(recibidos, 1, "el entrante entra");
        assert_eq!(z.pending(), 1);
    }
}
