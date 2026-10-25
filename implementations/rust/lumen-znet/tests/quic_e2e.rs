//! Prueba de extremo a extremo sobre QUIC real.
//!
//! Levanta un servidor QUIC de LUMEN, conecta un cliente, y hace viajar un mensaje DDP
//! en las dos direcciones. Esto sí es transporte de verdad: sockets UDP, handshake TLS,
//! streams de quinn.
//!
//! Requiere la feature `quic`.

#![cfg(feature = "quic")]

use std::thread;
use std::time::{Duration, Instant};

use lumen::quic::QuicEndpoint;
use lumen::frame::{self, ParseResult};
use lumen::transport::Transport;
use lumen_znet::{ddp_to_frame, frame_to_ddp, msg_type, DdpMessage, QuicZnet, Znet, ZnetReply};

#[test]
fn un_mensaje_ddp_viaja_por_quic_de_verdad() {
    // 1. Servidor a la escucha en un puerto libre.
    let mut servidor = QuicEndpoint::server("127.0.0.1:0")
        .expect("el servidor QUIC debe levantarse en localhost");
    let addr = servidor.local_addr().expect("addr del servidor");
    let addr_str = format!("127.0.0.1:{}", addr.port());

    // 2. Hilo servidor: acepta, lee un mensaje DDP, responde, y devuelve lo que vio.
    let hilo = thread::spawn(move || {
        let mut transporte = match servidor.accept() {
            Ok(t) => t,
            Err(e) => return Err(format!("accept: {e}")),
        };

        // Leer hasta tener un frame completo.
        let mut buf = Vec::new();
        let inicio = Instant::now();
        let frame_visto = loop {
            if inicio.elapsed() > Duration::from_secs(10) {
                return Err("timeout esperando frame".to_string());
            }
            let mut chunk = [0u8; 4096];
            match transporte.read(&mut chunk) {
                Ok(0) => return Err("stream cerrado antes de tiempo".into()),
                Ok(n) => buf.extend_from_slice(&chunk[..n]),
                Err(e) => return Err(format!("read: {e}")),
            }
            // Convertir a DdpMessage ANTES de tocar el buffer: el Frame pide prestado de él.
            if let ParseResult::Complete { frame, consumed } = frame::parse(&buf) {
                let convertido = frame_to_ddp(frame.frame_type, frame.payload);
                buf.drain(..consumed);
                break convertido.map_err(|e| format!("frame no es DDP: {e}"))?;
            }
        };

        let recibido = frame_visto;

        // Responder con un ACK.
        let respuesta = DdpMessage::new(msg_type::SUCCESS, recibido.num1, recibido.num2, 0, Vec::new());
        let (ft, fl, p) = ddp_to_frame(&respuesta);
        let mut out = vec![0u8; frame::build_size(p.len())];
        let n = frame::build(ft, fl, &p, &mut out);
        transporte.write_all(&out[..n]).map_err(|e| format!("write: {e}"))?;
        transporte.flush().map_err(|e| format!("flush: {e}"))?;
        // Mantener la conexion viva un momento para que el ACK llegue antes de cerrar.
        // Sin esto el stream se cierra con el ACK aun en vuelo y el cliente lee 0.
        std::thread::sleep(std::time::Duration::from_millis(300));

        Ok(recibido)
    });

    // 3. Cliente: esperar a que el servidor este en accept(), luego conectar.
    // Sin esta pausa hay carrera: el cliente abre el stream bi antes de que el servidor
    // llame a accept_bi(), y el handshake se pierde.
    thread::sleep(Duration::from_millis(300));

    // 3.b Cliente: conecta y manda un mensaje DDP.
    let mut cliente = QuicEndpoint::client().expect("el cliente QUIC debe crearse");

    let mut transporte = cliente
        .connect(&addr_str)
        .expect("debe establecerse la conexion QUIC local");

    // El mensaje que viaja: uno con la forma de los de DDPSRV.
    let enviado = DdpMessage::new(
        msg_type::DATA,
        0x012C,
        7,
        0,
        b"^SYS(\"JOURNAL\",1)=p1^p2".to_vec(),
    );
    let (ft, fl, p) = ddp_to_frame(&enviado);
    let mut out = vec![0u8; frame::build_size(p.len())];
    let n = frame::build(ft, fl, &p, &mut out);
    transporte
        .write_all(&out[..n])
        .and_then(|_| transporte.flush())
        .expect("debe poder escribirse el frame DDP en el stream QUIC");

    // 4. Leer la respuesta.
    let mut buf = Vec::new();
    let inicio = Instant::now();
    let respuesta = loop {
        if inicio.elapsed() > Duration::from_secs(10) {
            panic!("timeout esperando la respuesta del servidor QUIC");
        }
        let mut chunk = [0u8; 4096];
        match transporte.read(&mut chunk) {
            Ok(0) => panic!("el stream se cerro esperando respuesta"),
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(e) => panic!("error leyendo la respuesta: {e}"),
        }
        if let ParseResult::Complete { frame, consumed } = frame::parse(&buf) {
            let convertido = frame_to_ddp(frame.frame_type, frame.payload);
            buf.drain(..consumed);
            break convertido;
        }
    };

    // 5. Comprobar que llegó bien a los dos lados.
    let vio_el_servidor = hilo.join().expect("el hilo del servidor no debe entrar en pánico");

    let recibido = vio_el_servidor
        .unwrap_or_else(|e| panic!("el servidor QUIC no recibio el mensaje: {e}"));

    assert_eq!(recibido.num1, 0x012C, "el id de mensaje debe llegar intacto");
    assert_eq!(recibido.num2, 7, "el circuito debe llegar intacto");
    assert_eq!(recibido.body, enviado.body, "la carga util debe llegar intacta");
    let respuesta = respuesta.expect("la respuesta debe ser un mensaje DDP valido");
    assert_eq!(respuesta.kind, msg_type::SUCCESS, "la respuesta debe ser un ACK");
}

#[test]
fn el_backend_generico_funciona_sobre_un_vec() {
    // Sin red: demuestra que QuicZnet<S> sirve para cualquier Read+Write,
    // lo que permite sustituir el transporte en tests.
    struct Mem {
        out: Vec<u8>,
        inp: Vec<u8>,
        pos: usize,
    }
    impl Transport for Mem {
        fn read(&mut self, b: &mut [u8]) -> std::io::Result<usize> {
            let n = (self.inp.len() - self.pos).min(b.len());
            b[..n].copy_from_slice(&self.inp[self.pos..self.pos + n]);
            self.pos += n;
            Ok(n)
        }
        fn write_all(&mut self, b: &[u8]) -> std::io::Result<()> {
            self.out.extend_from_slice(b);
            Ok(())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }

    let mut z = Znet::new();
    z.init();
    let c = z.connect("hub").unwrap();
    z.reply(c, ZnetReply::Success).unwrap();

    let mut backend = QuicZnet::new(Mem { out: Vec::new(), inp: Vec::new(), pos: 0 });
    let enviados = backend.flush(&mut z).unwrap();
    assert_eq!(enviados, 1);
    assert!(!backend.into_inner().out.is_empty());
}
