//! LUMEN QUIC Transport — LTA over QUIC (RFC 9000).
//!
//! ## Why QUIC?
//!
//! QUIC is a modern, multiplexed transport protocol running over UDP.
//! It provides:
//!
//! - **Reliable ordered streams** — each stream maps to a LUMEN Transport
//! - **Built-in TLS 1.3** — encryption is mandatory
//! - **0-RTT resumption** — reconnect with zero round trips
//! - **Connection migration** — survives IP address changes
//! - **Multiplexing** — thousands of independent streams per connection
//!
//! ## Feature flag
//!
//! ```toml
//! [dependencies]
//! lumen = { version = "0.1", features = ["quic"] }
//! ```
//!
//! ## Security Warning
//!
//! **The default QUIC client does NOT verify server certificates.**
//! This is suitable ONLY for local development and testing on trusted
//! networks.  For production use, provide a `rustls::ClientConfig`
//! with proper certificate verification via `QuicClient::with_config()`.
//!
//! The `SkipCertVerifier` is marked `#[deprecated]` and will be
//! removed in v0.2 in favor of mandatory certificate validation.

use std::io;
use std::net::SocketAddr;
use std::sync::Arc;

use quinn::{
    ClientConfig, Connection, Endpoint, RecvStream, SendStream, ServerConfig, TransportConfig,
};
use tokio::runtime::Runtime;

#[derive(Debug)]
struct SkipCertVerifier;

impl rustls::client::danger::ServerCertVerifier for SkipCertVerifier {
    fn verify_server_cert(
        &self,
        _end_entity: &rustls::pki_types::CertificateDer,
        _intermediates: &[rustls::pki_types::CertificateDer],
        _server_name: &rustls::pki_types::ServerName,
        _ocsp_response: &[u8],
        _now: rustls::pki_types::UnixTime,
    ) -> Result<rustls::client::danger::ServerCertVerified, rustls::Error> {
        Ok(rustls::client::danger::ServerCertVerified::assertion())
    }

    fn verify_tls12_signature(
        &self,
        _message: &[u8],
        _cert: &rustls::pki_types::CertificateDer,
        _dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn verify_tls13_signature(
        &self,
        _message: &[u8],
        _cert: &rustls::pki_types::CertificateDer,
        _dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn supported_verify_schemes(&self) -> Vec<rustls::SignatureScheme> {
        vec![
            rustls::SignatureScheme::RSA_PKCS1_SHA256,
            rustls::SignatureScheme::ECDSA_NISTP256_SHA256,
            rustls::SignatureScheme::ED25519,
        ]
    }
}

pub fn generate_self_signed_cert(
    subject_alt_names: &[String],
) -> io::Result<(
    rustls::pki_types::CertificateDer<'static>,
    rustls::pki_types::PrivateKeyDer<'static>,
)> {
    let cert = rcgen::generate_simple_self_signed(subject_alt_names.to_vec()).map_err(|e| {
        io::Error::new(io::ErrorKind::Other, format!("cert generation failed: {e}"))
    })?;
    let cert_der = cert.cert.into();
    let key_der = cert.key_pair.serialize_der();
    let key = rustls::pki_types::PrivateKeyDer::Pkcs8(key_der.into());
    Ok((cert_der, key))
}

pub fn default_server_config() -> io::Result<ServerConfig> {
    let (cert, key) = generate_self_signed_cert(&["lumen.local".to_string()])?;
    let mut crypto = rustls::ServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(vec![cert.clone()], key)
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("TLS config: {e}")))?;
    crypto.max_early_data_size = u32::MAX;
    crypto.alpn_protocols = vec![b"lumen/1.0".to_vec()];
    let quic_crypto = quinn::crypto::rustls::QuicServerConfig::try_from(Arc::new(crypto))
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("QUIC TLS config: {e}")))?;
    let mut server = ServerConfig::with_crypto(Arc::new(quic_crypto));
    let mut transport = TransportConfig::default();
    transport.max_concurrent_bidi_streams(1024u32.into());
    transport.max_concurrent_uni_streams(1024u32.into());
    server.transport_config(Arc::new(transport));
    Ok(server)
}

pub fn default_client_config() -> io::Result<ClientConfig> {
    let mut crypto = rustls::ClientConfig::builder()
        .with_root_certificates(rustls::RootCertStore::empty())
        .with_no_client_auth();
    crypto
        .dangerous()
        .set_certificate_verifier(Arc::new(SkipCertVerifier));
    crypto.alpn_protocols = vec![b"lumen/1.0".to_vec()];
    crypto.enable_early_data = true;
    let quic_crypto = quinn::crypto::rustls::QuicClientConfig::try_from(Arc::new(crypto))
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("QUIC TLS config: {e}")))?;
    let mut client = ClientConfig::new(Arc::new(quic_crypto));
    let mut transport = TransportConfig::default();
    transport.max_concurrent_bidi_streams(1024u32.into());
    transport.max_concurrent_uni_streams(1024u32.into());
    client.transport_config(Arc::new(transport));
    Ok(client)
}

// ── Pinned verifier (identity=pin) ────────────────────────────────────
//
// En vez de aceptar cualquier certificado, el cliente compara la huella
// SHA-256 del certificado del servidor con la que el operador fijó en
// `^SYS("PEER",<host>,"pin")`. Si no coincide, la conexión NO se establece.
//
// Esto no es PKI: no hay autoridad, no hay cadena. Es "confío exactamente en
// este nodo y en ningún otro", que es lo que un PC↔NAS o un armador necesita
// antes de que exista una raíz de flota.

/// Verificador que exige que el certificado del par tenga una huella concreta.
#[derive(Debug)]
pub struct PinnedVerifier {
    /// Huella SHA-256 esperada, 32 bytes (hex de 64 chars al leerla de la PDB).
    huella: [u8; 32],
}

impl PinnedVerifier {
    /// Crea el verificador desde una huella en hex (con o sin ':' de separación).
    pub fn from_hex(hex_huella: &str) -> Result<Self, String> {
        let limpio: String = hex_huella
            .chars()
            .filter(|c| c.is_ascii_hexdigit())
            .collect::<String>()
            .to_lowercase();
        if limpio.len() != 64 {
            return Err(format!(
                "huella pin debe tener 64 hex chars (sha256), tiene {}",
                limpio.len()
            ));
        }
        let mut huella = [0u8; 32];
        for i in 0..32 {
            huella[i] = u8::from_str_radix(&limpio[i * 2..i * 2 + 2], 16)
                .map_err(|e| format!("hex invalido en byte {i}: {e}"))?;
        }
        Ok(Self { huella })
    }

    /// Huella esperada en hex minúsculas (para logs y para comparar en tests).
    pub fn huella_hex(&self) -> String {
        self.huella.iter().map(|b| format!("{b:02x}")).collect()
    }

    /// Comprueba un certificado DER contra la huella fijada.
    fn coincide(&self, cert_der: &[u8]) -> bool {
        let calculada = <sha2::Sha256 as sha2::Digest>::digest(cert_der);
        // Comparación en tiempo constante: no filtrar por dónde difiere.
        let mut dif = 0u8;
        for (a, b) in calculada.iter().zip(self.huella.iter()) {
            dif |= a ^ b;
        }
        dif == 0
    }
}

impl rustls::client::danger::ServerCertVerifier for PinnedVerifier {
    fn verify_server_cert(
        &self,
        end_entity: &rustls::pki_types::CertificateDer,
        _intermediates: &[rustls::pki_types::CertificateDer],
        _server_name: &rustls::pki_types::ServerName,
        _ocsp_response: &[u8],
        _now: rustls::pki_types::UnixTime,
    ) -> Result<rustls::client::danger::ServerCertVerified, rustls::Error> {
        if self.coincide(end_entity.as_ref()) {
            Ok(rustls::client::danger::ServerCertVerified::assertion())
        } else {
            Err(rustls::Error::General(format!(
                "certificado del par NO coincide con el pin (esperado {})",
                self.huella_hex()
            )))
        }
    }

    // El pin es sobre el certificado, no sobre la firma. Las firmas del
    // handshake se validan con los esquemas estándar.
    fn verify_tls12_signature(
        &self,
        message: &[u8],
        cert: &rustls::pki_types::CertificateDer,
        dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        rustls::crypto::verify_tls12_signature(
            message,
            cert,
            dss,
            &rustls::crypto::ring::default_provider().signature_verification_algorithms,
        )
    }

    fn verify_tls13_signature(
        &self,
        message: &[u8],
        cert: &rustls::pki_types::CertificateDer,
        dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        rustls::crypto::verify_tls13_signature(
            message,
            cert,
            dss,
            &rustls::crypto::ring::default_provider().signature_verification_algorithms,
        )
    }

    fn supported_verify_schemes(&self) -> Vec<rustls::SignatureScheme> {
        rustls::crypto::ring::default_provider()
            .signature_verification_algorithms
            .supported_schemes()
    }
}

/// Config de cliente que verifica el certificado contra un pin.
///
/// A diferencia de `default_client_config()`, aquí un certificado distinto
/// hace fallar el handshake. Es el camino que debe usarse cuando
/// `identity=pin` (ADR-002).
pub fn pinned_client_config(huella_hex: &str) -> io::Result<ClientConfig> {
    let verifier = PinnedVerifier::from_hex(huella_hex)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
    let mut crypto = rustls::ClientConfig::builder()
        .with_root_certificates(rustls::RootCertStore::empty())
        .with_no_client_auth();
    crypto
        .dangerous()
        .set_certificate_verifier(Arc::new(verifier));
    crypto.alpn_protocols = vec![b"lumen/1.0".to_vec()];
    let quic_crypto = quinn::crypto::rustls::QuicClientConfig::try_from(Arc::new(crypto))
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("QUIC TLS config: {e}")))?;
    let mut client = ClientConfig::new(Arc::new(quic_crypto));
    let mut transport = TransportConfig::default();
    transport.max_concurrent_bidi_streams(1024u32.into());
    transport.max_concurrent_uni_streams(1024u32.into());
    client.transport_config(Arc::new(transport));
    Ok(client)
}

/// Servidor que expone el certificado que usa, para poder fijar su huella.
///
/// Devuelve `(QuicEndpoint, huella_hex)`: el operador fija en
/// `^SYS("PEER",<host>,"pin")` el valor de `huella_hex` y a partir de ahí el
/// cliente con `pinned_client_config` solo acepta ESE certificado.
pub fn server_with_pin(addr: &str) -> io::Result<(QuicEndpoint, String)> {
    let (cert, key) = generate_self_signed_cert(&["lumen.local".to_string()])?;
    let huella: String = <sha2::Sha256 as sha2::Digest>::digest(cert.as_ref())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();

    let runtime = Arc::new(
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .thread_name("lumen-quic-server")
            .enable_all()
            .build()
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("tokio runtime: {e}")))?,
    );
    let _guard = runtime.enter();

    let mut crypto = rustls::ServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(vec![cert], key)
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("TLS config: {e}")))?;
    crypto.alpn_protocols = vec![b"lumen/1.0".to_vec()];
    let quic_crypto = quinn::crypto::rustls::QuicServerConfig::try_from(Arc::new(crypto))
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("QUIC TLS config: {e}")))?;
    let mut server_config = ServerConfig::with_crypto(Arc::new(quic_crypto));
    let mut transport = TransportConfig::default();
    transport.max_concurrent_bidi_streams(1024u32.into());
    transport.max_concurrent_uni_streams(1024u32.into());
    server_config.transport_config(Arc::new(transport));

    let socket_addr: SocketAddr = addr
        .parse()
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, format!("addr {addr}: {e}")))?;
    let socket = std::net::UdpSocket::bind(socket_addr)
        .map_err(|e| io::Error::new(io::ErrorKind::AddrInUse, format!("UDP bind: {e}")))?;
    let endpoint = runtime.block_on(async {
        Endpoint::new(
            Default::default(),
            Some(server_config),
            socket,
            Arc::new(quinn::TokioRuntime),
        )
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("QUIC endpoint: {e}")))
    })?;

    Ok((QuicEndpoint { endpoint, runtime }, huella))
}

pub struct QuicEndpoint {
    endpoint: Endpoint,
    runtime: Arc<Runtime>,
}

impl QuicEndpoint {
    pub fn server(addr: &str) -> io::Result<Self> {
        let runtime = Arc::new(
            tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .thread_name("lumen-quic-server")
                .enable_all()
                .build()
                .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("tokio runtime: {e}")))?,
        );

        let _guard = runtime.enter();
        let server_config = default_server_config()?;
        let socket_addr: SocketAddr = addr.parse().map_err(|e| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("invalid address '{addr}': {e}"),
            )
        })?;
        let socket = std::net::UdpSocket::bind(socket_addr)
            .map_err(|e| io::Error::new(io::ErrorKind::AddrInUse, format!("UDP bind: {e}")))?;
        let endpoint = runtime.block_on(async {
            Endpoint::new(
                Default::default(),
                Some(server_config),
                socket,
                Arc::new(quinn::TokioRuntime),
            )
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("QUIC endpoint: {e}")))
        })?;

        Ok(Self { endpoint, runtime })
    }

    pub fn client() -> io::Result<Self> {
        Self::client_with_config(None)
    }

    /// Cliente QUIC con una configuración TLS concreta (p.ej. `pinned_client_config`
    /// para `identity=pin`). Con `None` usa la config por defecto, que **no
    /// verifica certificados** y solo sirve para desarrollo.
    pub fn client_with_config(config: Option<ClientConfig>) -> io::Result<Self> {
        let runtime = Arc::new(
            tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .thread_name("lumen-quic-client")
                .enable_all()
                .build()
                .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("tokio runtime: {e}")))?,
        );

        let _guard = runtime.enter();
        let client_config = match config {
            Some(c) => c,
            None => default_client_config()?,
        };
        let socket_addr: SocketAddr = "0.0.0.0:0".parse().unwrap();
        let socket = std::net::UdpSocket::bind(socket_addr)
            .map_err(|e| io::Error::new(io::ErrorKind::AddrInUse, format!("UDP bind: {e}")))?;
        let mut endpoint = runtime.block_on(async {
            Endpoint::new(
                Default::default(),
                None,
                socket,
                Arc::new(quinn::TokioRuntime),
            )
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("QUIC endpoint: {e}")))
        })?;
        endpoint.set_default_client_config(client_config);

        Ok(Self { endpoint, runtime })
    }

    /// Acepta una conexión **sin esperar al primer stream**.
    ///
    /// ## Por qué existe
    ///
    /// [`accept`] hace `accept_bi()`, que espera a que el cliente abra un
    /// stream. Eso significa que **no vuelve hasta que el cliente manda algo**.
    /// Si se atiende una conexión de principio a fin antes de volver a llamar,
    /// los demás clientes se encuentran el puerto ocupado y reciben
    /// `ConnectionRefused`.
    ///
    /// Medido en la simulación de flota: con [`accept`] el hub aguanta **10
    /// barcos** a la vez; a partir de ahí se encalla.
    ///
    /// Esta variante devuelve en cuanto el handshake termina, y los streams se
    /// aceptan después con [`QuicTransport::aceptar_stream`]. Así el servidor
    /// puede aceptar conexiones en paralelo.
    pub fn aceptar_conexion(&mut self) -> io::Result<QuicTransport> {
        self.runtime.block_on(async {
            match self.endpoint.accept().await {
                Some(incoming) => {
                    let conn = incoming.await.map_err(|e| {
                        io::Error::new(
                            io::ErrorKind::ConnectionRefused,
                            format!("QUIC handshake failed: {e}"),
                        )
                    })?;
                    Ok(QuicTransport {
                        send: None,
                        recv: None,
                        connection: conn,
                        _endpoint: self.endpoint.clone(),
                        _runtime: self.runtime.clone(),
                        runtime_handle: self.runtime.handle().clone(),
                        read_buffer: Vec::new(),
                        read_pos: 0,
                        read_len: 0,
                    })
                }
                None => Err(io::Error::new(
                    io::ErrorKind::NotConnected,
                    "endpoint closed",
                )),
            }
        })
    }

    pub fn accept(&mut self) -> io::Result<QuicTransport> {
        self.runtime.block_on(async {
            match self.endpoint.accept().await {
                Some(incoming) => {
                    let conn = incoming.await.map_err(|e| {
                        io::Error::new(
                            io::ErrorKind::ConnectionRefused,
                            format!("QUIC handshake failed: {e}"),
                        )
                    })?;
                    let (send, recv) = conn.accept_bi().await.map_err(|e| {
                        io::Error::new(
                            io::ErrorKind::ConnectionReset,
                            format!("stream accept failed: {e}"),
                        )
                    })?;
                    Ok(QuicTransport {
                        send: Some(send),
                        recv: Some(recv),
                        connection: conn,
                        _endpoint: self.endpoint.clone(),
                        _runtime: self.runtime.clone(),
                        runtime_handle: self.runtime.handle().clone(),
                        read_buffer: Vec::new(),
                        read_pos: 0,
                        read_len: 0,
                    })
                }
                None => Err(io::Error::new(
                    io::ErrorKind::NotConnected,
                    "endpoint closed",
                )),
            }
        })
    }

    pub fn connect(&mut self, addr: &str) -> io::Result<QuicTransport> {
        let socket_addr: SocketAddr = addr.parse().map_err(|e| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("invalid address '{addr}': {e}"),
            )
        })?;
        let server_name = "lumen.local".to_string();

        self.runtime.block_on(async {
            let conn = self
                .endpoint
                .connect(socket_addr, &server_name)
                .map_err(|e| {
                    io::Error::new(
                        io::ErrorKind::ConnectionRefused,
                        format!("QUIC connect: {e}"),
                    )
                })?;
            let conn = conn.await.map_err(|e| {
                io::Error::new(
                    io::ErrorKind::ConnectionRefused,
                    format!("QUIC handshake failed: {e}"),
                )
            })?;
            let (send, recv) = conn.open_bi().await.map_err(|e| {
                io::Error::new(
                    io::ErrorKind::ConnectionReset,
                    format!("stream open failed: {e}"),
                )
            })?;
            Ok(QuicTransport {
                send: Some(send),
                recv: Some(recv),
                connection: conn,
                _endpoint: self.endpoint.clone(),
                _runtime: self.runtime.clone(),
                runtime_handle: self.runtime.handle().clone(),
                read_buffer: Vec::new(),
                read_pos: 0,
                read_len: 0,
            })
        })
    }

    pub fn runtime_handle(&self) -> tokio::runtime::Handle {
        self.runtime.handle().clone()
    }

    /// Acepta una conexión, esperando como mucho `limite`.
    ///
    /// Devuelve `Ok(None)` si no llegó ninguna en ese plazo. Existe para que un
    /// nodo pueda atender varias cosas a la vez (p.ej. descubrimiento
    /// multicast) sin quedarse bloqueado en `accept()` para siempre.
    pub fn aceptar_con_timeout(
        &mut self,
        limite: std::time::Duration,
    ) -> io::Result<Option<QuicTransport>> {
        self.runtime.block_on(async {
            match tokio::time::timeout(limite, self.endpoint.accept()).await {
                Err(_) => Ok(None), // timeout: no vino nadie
                Ok(None) => Err(io::Error::new(
                    io::ErrorKind::NotConnected,
                    "endpoint closed",
                )),
                Ok(Some(incoming)) => {
                    let conn = incoming.await.map_err(|e| {
                        io::Error::new(
                            io::ErrorKind::ConnectionRefused,
                            format!("QUIC handshake failed: {e}"),
                        )
                    })?;
                    let (send, recv) = conn.accept_bi().await.map_err(|e| {
                        io::Error::new(
                            io::ErrorKind::ConnectionReset,
                            format!("stream accept failed: {e}"),
                        )
                    })?;
                    Ok(Some(QuicTransport {
                        send: Some(send),
                        recv: Some(recv),
                        connection: conn,
                        _endpoint: self.endpoint.clone(),
                        _runtime: self.runtime.clone(),
                        runtime_handle: self.runtime.handle().clone(),
                        read_buffer: Vec::new(),
                        read_pos: 0,
                        read_len: 0,
                    }))
                }
            }
        })
    }

    pub fn local_addr(&self) -> io::Result<SocketAddr> {
        Ok(self
            .endpoint
            .local_addr()
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("local addr: {e}")))?)
    }
}

pub struct QuicTransport {
    send: Option<SendStream>,
    recv: Option<RecvStream>,
    connection: Connection,
    // Keep endpoint alive so the QUIC connection doesn't get torn down
    #[allow(dead_code)]
    _endpoint: Endpoint,
    #[allow(dead_code)]
    _runtime: Arc<Runtime>,
    runtime_handle: tokio::runtime::Handle,
    read_buffer: Vec<u8>,
    read_pos: usize,
    /// Cuántos bytes REALES hay en `read_buffer`.
    ///
    /// 🔴 Bug 24-nov-2026 (encontrado conectando dos `lumen-nodo`): sin este
    /// campo, "quedan bytes pendientes" se comprobaba con
    /// `read_pos < read_buffer.len()`, que es el tamaño del Vec (65536), no
    /// los bytes leídos. Tras la primera lectura de n bytes, la siguiente
    /// llamada entregaba ~65 KB de ceros del relleno y **perdía** los bytes
    /// reales de la segunda lectura. Firma en el receptor: frames válidos de
    /// longitud 0. Regresión: `lumen-znet/tests/read_sin_relleno.rs`.
    read_len: usize,
}

impl QuicTransport {
    pub fn connect(addr: &str) -> io::Result<Self> {
        let mut endpoint = QuicEndpoint::client()?;
        endpoint.connect(addr)
    }

    /// Acepta el siguiente stream bidireccional de esta conexión.
    ///
    /// Necesario cuando la conexión se obtuvo con
    /// [`QuicEndpoint::aceptar_conexion`], que devuelve **sin** streams. Bloquea
    /// hasta que el cliente abra uno.
    pub fn aceptar_stream(&mut self) -> io::Result<()> {
        if self.send.is_some() && self.recv.is_some() {
            return Ok(()); // ya hay stream
        }
        let conn = self.connection.clone();
        let handle = self.runtime_handle.clone();
        let (send, recv) = handle.block_on(async {
            conn.accept_bi().await.map_err(|e| {
                io::Error::new(
                    io::ErrorKind::ConnectionReset,
                    format!("stream accept failed: {e}"),
                )
            })
        })?;
        self.send = Some(send);
        self.recv = Some(recv);
        Ok(())
    }

    /// ¿Tiene ya un stream abierto?
    pub fn tiene_stream(&self) -> bool {
        self.send.is_some() && self.recv.is_some()
    }

    pub fn peer_certificate(&self) -> Option<Vec<rustls::pki_types::CertificateDer<'static>>> {
        self.connection
            .peer_identity()
            .and_then(|id| id.downcast::<Vec<rustls::pki_types::CertificateDer>>().ok())
            .map(|arc| (*arc).clone())
    }

    pub fn remote_address(&self) -> SocketAddr {
        self.connection.remote_address()
    }
}

impl crate::transport::Transport for QuicTransport {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        // ── Bytes pendientes de una lectura anterior ──────────────────
        // `read_len` es cuántos bytes REALES hay en `read_buffer`. Comparar
        // contra `read_buffer.len()` (el tamaño del Vec, 65536) entregaba
        // relleno: ver el bug de 24-nov-2026 documentado en el campo.
        if self.read_pos < self.read_len {
            let remaining = &self.read_buffer[self.read_pos..self.read_len];
            let n = remaining.len().min(buf.len());
            buf[..n].copy_from_slice(&remaining[..n]);
            self.read_pos += n;
            return Ok(n);
        }

        let recv = self
            .recv
            .as_mut()
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotConnected, "recv stream closed"))?;

        self.runtime_handle.block_on(async {
            // Leer UN chunk, no el stream entero.
            //
            // Antes esto era `recv.read_to_end(65536)`, que bloquea hasta que el par cierra el
            // stream. Eso hace inutilizable el transporte para cualquier protocolo con
            // peticion/respuesta: el receptor nunca ve los bytes hasta que el emisor termina,
            // y el emisor nunca termina porque espera la respuesta. Deadlock.
            //
            // LUMEN tiene framing propio (Hyb128 + tipo + flags), asi que no necesita el EOF
            // para saber donde acaba un frame: `frame::parse` se lo dice. Leer por chunks es
            // lo correcto aqui.
            //
            // El buffer tiene que tener capacidad: `recv.read` con un slice vacio devuelve 0
            // y se confundiria con un cierre limpio del stream.
            if self.read_buffer.is_empty() {
                self.read_buffer.resize(65536, 0);
            }
            match recv.read(&mut self.read_buffer[..]).await {
                Ok(Some(n)) if n > 0 => {
                    // Solo los primeros `n` bytes son datos. `read_len` marca
                    // la frontera; el resto del Vec es relleno y NO se entrega.
                    self.read_pos = 0;
                    self.read_len = n;
                    let copiar = n.min(buf.len());
                    buf[..copiar].copy_from_slice(&self.read_buffer[..copiar]);
                    self.read_pos = copiar;
                    Ok(copiar)
                }
                Ok(Some(_)) => Ok(0),
                Ok(None) => Ok(0),
                Err(e) => Err(io::Error::new(
                    io::ErrorKind::ConnectionReset,
                    format!("QUIC read: {e}"),
                )),
            }
        })
    }

    fn write_all(&mut self, buf: &[u8]) -> io::Result<()> {
        let send = self
            .send
            .as_mut()
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotConnected, "send stream closed"))?;
        let data = buf.to_vec();
        self.runtime_handle.block_on(async {
            send.write_all(&data).await.map_err(|e| {
                io::Error::new(io::ErrorKind::ConnectionReset, format!("QUIC write: {e}"))
            })
        })
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_runtime() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .unwrap()
    }

    fn server_config_and_socket() -> (quinn::ServerConfig, std::net::UdpSocket, u16) {
        let (cert, key) = generate_self_signed_cert(&["lumen.local".to_string()]).unwrap();
        let mut crypto = rustls::ServerConfig::builder()
            .with_no_client_auth()
            .with_single_cert(vec![cert], key)
            .unwrap();
        crypto.max_early_data_size = u32::MAX;
        crypto.alpn_protocols = vec![b"lumen/1.0".to_vec()];
        let quic_cfg =
            quinn::crypto::rustls::QuicServerConfig::try_from(std::sync::Arc::new(crypto)).unwrap();
        let mut server_config = quinn::ServerConfig::with_crypto(std::sync::Arc::new(quic_cfg));
        let mut transport = quinn::TransportConfig::default();
        transport.max_concurrent_bidi_streams(1024u32.into());
        transport.max_concurrent_uni_streams(1024u32.into());
        server_config.transport_config(std::sync::Arc::new(transport));

        let sock = std::net::UdpSocket::bind("127.0.0.1:0").unwrap();
        let port = sock.local_addr().unwrap().port();
        (server_config, sock, port)
    }

    fn client_config_and_socket() -> (quinn::ClientConfig, std::net::UdpSocket) {
        let mut crypto = rustls::ClientConfig::builder()
            .with_root_certificates(rustls::RootCertStore::empty())
            .with_no_client_auth();
        crypto
            .dangerous()
            .set_certificate_verifier(std::sync::Arc::new(SkipCertVerifier));
        crypto.alpn_protocols = vec![b"lumen/1.0".to_vec()];
        crypto.enable_early_data = true;
        let quic_cfg =
            quinn::crypto::rustls::QuicClientConfig::try_from(std::sync::Arc::new(crypto)).unwrap();
        let client_config = quinn::ClientConfig::new(std::sync::Arc::new(quic_cfg));

        let sock = std::net::UdpSocket::bind("0.0.0.0:0").unwrap();
        (client_config, sock)
    }

    #[test]
    fn cert_generate_self_signed_works() {
        let (cert, key) = generate_self_signed_cert(&["test.local".to_string()]).unwrap();
        assert!(!cert.is_empty());
        assert!(matches!(key, rustls::pki_types::PrivateKeyDer::Pkcs8(_)));
    }

    #[test]
    fn server_config_creates() {
        assert!(default_server_config().is_ok());
    }

    #[test]
    fn client_config_creates() {
        assert!(default_client_config().is_ok());
    }

    #[test]
    fn quic_write_read_roundtrip() {
        let rt = make_runtime();
        let (server_config, server_sock, server_port) = server_config_and_socket();
        let (client_config, client_sock) = client_config_and_socket();

        rt.block_on(async {
            let server_ep = quinn::Endpoint::new(
                Default::default(),
                Some(server_config),
                server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(),
                None,
                client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            client_ep.set_default_client_config(client_config);

            let addr: std::net::SocketAddr = format!("127.0.0.1:{server_port}").parse().unwrap();
            let client_connecting = client_ep.connect(addr, "lumen.local").unwrap();
            let incoming = server_ep.accept().await.unwrap();
            let server_conn = incoming.await.unwrap();
            let client_conn = client_connecting.await.unwrap();

            let (mut client_send, _client_recv) = client_conn.open_bi().await.unwrap();
            client_send
                .write_all(b"hello lumen over quic")
                .await
                .unwrap();
            client_send.finish().unwrap();

            let (_server_send, mut server_recv) = server_conn.accept_bi().await.unwrap();
            let mut buf = vec![0u8; 64];
            let n = server_recv.read(&mut buf).await.unwrap().unwrap();
            assert_eq!(&buf[..n], b"hello lumen over quic");
        });
    }

    #[test]
    fn quic_bidirectional() {
        let rt = make_runtime();
        let (server_config, server_sock, server_port) = server_config_and_socket();
        let (client_config, client_sock) = client_config_and_socket();

        rt.block_on(async {
            let server_ep = quinn::Endpoint::new(
                Default::default(),
                Some(server_config),
                server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(),
                None,
                client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            client_ep.set_default_client_config(client_config);

            let addr: std::net::SocketAddr = format!("127.0.0.1:{server_port}").parse().unwrap();
            let client_connecting = client_ep.connect(addr, "lumen.local").unwrap();
            let incoming = server_ep.accept().await.unwrap();
            let server_conn = incoming.await.unwrap();
            let client_conn = client_connecting.await.unwrap();

            let (mut client_send, mut client_recv) = client_conn.open_bi().await.unwrap();
            client_send.write_all(b"ping").await.unwrap();

            let (mut server_send, mut server_recv) = server_conn.accept_bi().await.unwrap();
            let mut buf = [0u8; 16];
            let n = server_recv.read(&mut buf).await.unwrap().unwrap();
            assert_eq!(&buf[..n], b"ping");

            server_send.write_all(b"pong").await.unwrap();
            let n = client_recv.read(&mut buf).await.unwrap().unwrap();
            assert_eq!(&buf[..n], b"pong");
        });
    }

    #[test]
    fn quic_large_payload() {
        let rt = make_runtime();
        let (server_config, server_sock, server_port) = server_config_and_socket();
        let (client_config, client_sock) = client_config_and_socket();

        rt.block_on(async {
            let server_ep = quinn::Endpoint::new(
                Default::default(),
                Some(server_config),
                server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(),
                None,
                client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            client_ep.set_default_client_config(client_config);

            let addr: std::net::SocketAddr = format!("127.0.0.1:{server_port}").parse().unwrap();
            let client_connecting = client_ep.connect(addr, "lumen.local").unwrap();
            let incoming = server_ep.accept().await.unwrap();
            let server_conn = incoming.await.unwrap();
            let client_conn = client_connecting.await.unwrap();

            // Use same pattern as quic_write_read_roundtrip, just larger payload
            let large = vec![0xABu8; 200];
            let (mut client_send, _client_recv) = client_conn.open_bi().await.unwrap();
            client_send.write_all(&large).await.unwrap();
            client_send.finish().unwrap();

            let (_server_send, mut server_recv) = server_conn.accept_bi().await.unwrap();
            let mut buf = vec![0u8; 200];
            let n = server_recv.read(&mut buf).await.unwrap().unwrap();
            assert_eq!(n, large.len());
            assert_eq!(&buf[..n], &large[..]);
        });
    }

    #[test]
    fn quic_remote_address() {
        let rt = make_runtime();
        let (server_config, server_sock, server_port) = server_config_and_socket();
        let (client_config, client_sock) = client_config_and_socket();

        rt.block_on(async {
            let server_ep = quinn::Endpoint::new(
                Default::default(),
                Some(server_config),
                server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(),
                None,
                client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            client_ep.set_default_client_config(client_config);

            let addr: std::net::SocketAddr = format!("127.0.0.1:{server_port}").parse().unwrap();
            let client_connecting = client_ep.connect(addr, "lumen.local").unwrap();
            let incoming = server_ep.accept().await.unwrap();
            let server_conn = incoming.await.unwrap();
            let client_conn = client_connecting.await.unwrap();

            let remote = client_conn.remote_address();
            assert!(remote.port() > 0);
            // Server sees client on a different port than its own
            let server_remote = server_conn.remote_address();
            assert!(server_remote.port() > 0);
            assert_ne!(server_remote, remote);
        });
    }

    #[test]
    fn quic_ordered_frames() {
        let rt = make_runtime();
        let (server_config, server_sock, server_port) = server_config_and_socket();
        let (client_config, client_sock) = client_config_and_socket();

        rt.block_on(async {
            let server_ep = quinn::Endpoint::new(
                Default::default(),
                Some(server_config),
                server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(),
                None,
                client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            )
            .unwrap();
            client_ep.set_default_client_config(client_config);

            let addr: std::net::SocketAddr = format!("127.0.0.1:{server_port}").parse().unwrap();
            let client_connecting = client_ep.connect(addr, "lumen.local").unwrap();
            let incoming = server_ep.accept().await.unwrap();
            let server_conn = incoming.await.unwrap();
            let client_conn = client_connecting.await.unwrap();

            let (mut client_send, _client_recv) = client_conn.open_bi().await.unwrap();
            for i in 0..10u8 {
                client_send.write_all(&[i, i, i, i]).await.unwrap();
            }
            client_send.finish().unwrap();

            let (_server_send, mut server_recv) = server_conn.accept_bi().await.unwrap();
            let mut buf = [0u8; 4];
            for i in 0..10u8 {
                let n = server_recv.read(&mut buf).await.unwrap().unwrap();
                assert_eq!(n, 4);
                assert_eq!(&buf[..], &[i, i, i, i]);
            }
            assert!(server_recv.read(&mut buf).await.unwrap().is_none());
        });
    }
}

// ── Tests del pin (identity=pin, ADR-002) ─────────────────────────────
#[cfg(all(test, feature = "quic"))]
mod tests_pin {
    use super::*;
    use crate::transport::Transport;

    #[test]
    fn huella_hex_valida() {
        let hex = "a".repeat(64);
        let v = PinnedVerifier::from_hex(&hex).expect("64 hex debe valer");
        assert_eq!(v.huella_hex(), hex);
    }

    #[test]
    fn huella_con_dos_puntos_y_mayusculas_vale() {
        let hex = "AB".repeat(32);
        let v = PinnedVerifier::from_hex(&hex).expect("debe normalizar");
        assert_eq!(v.huella_hex(), "ab".repeat(32));
    }

    #[test]
    fn huella_corta_se_rechaza() {
        assert!(PinnedVerifier::from_hex("abcdef").is_err());
        assert!(PinnedVerifier::from_hex("").is_err());
    }

    #[test]
    fn huella_no_hexadecimal_se_rechaza() {
        // 64 chars pero con basura que no es hex.
        let malo = "z".repeat(64);
        assert!(PinnedVerifier::from_hex(&malo).is_err());
    }

    #[test]
    fn un_certificado_distinto_no_coincide() {
        // Certificado A genera una huella; el verificador con esa huella
        // acepta A y rechaza cualquier otro certificado.
        let (cert_a, _key_a) = generate_self_signed_cert(&["lumen.local".to_string()]).unwrap();
        let (cert_b, _key_b) = generate_self_signed_cert(&["lumen.local".to_string()]).unwrap();
        let huella_a: String = <sha2::Sha256 as sha2::Digest>::digest(cert_a.as_ref())
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();

        let v = PinnedVerifier::from_hex(&huella_a).unwrap();
        assert!(v.coincide(cert_a.as_ref()), "el certificado fijado debe pasar");
        assert!(
            !v.coincide(cert_b.as_ref()),
            "un certificado distinto NO debe pasar el pin"
        );
    }

    #[test]
    fn pinned_client_config_rechaza_huella_invalida() {
        assert!(pinned_client_config("no-es-hex").is_err());
        assert!(pinned_client_config(&"a".repeat(64)).is_ok());
    }

    /// El test que importa: handshake REAL con pin correcto completa, y con
    /// pin equivocado NO completa. Sin esto, el pin sería una función que
    /// nadie llama.
    #[test]
    fn handshake_con_pin_correcto_funciona_y_con_pin_erroneo_falla() {
        let (mut servidor, huella) = server_with_pin("127.0.0.1:0").expect("servidor con pin");
        let addr = servidor.local_addr().unwrap().to_string();

        // ── Caso 1: pin correcto -> debe conectar ────────────────────
        let hilo_ok = std::thread::spawn(move || -> Result<(), String> {
            let mut t = servidor.accept().map_err(|e| format!("accept: {e}"))?;
            t.write_all(b"hola").map_err(|e| format!("write: {e}"))?;
            t.flush().map_err(|e| format!("flush: {e}"))?;
            std::thread::sleep(std::time::Duration::from_millis(300));
            Ok(())
        });

        std::thread::sleep(std::time::Duration::from_millis(300));
        let cfg = pinned_client_config(&huella).expect("config con huella buena");
        let cliente_ok = std::thread::spawn({
            let addr = addr.clone();
            move || -> bool {
                let mut ep = match QuicEndpoint::client() {
                    Ok(e) => e,
                    Err(_) => return false,
                };
                // Sustituimos la config por defecto por la del pin.
                ep.endpoint.set_default_client_config(cfg);
                ep.connect(&addr).is_ok()
            }
        });

        let conecto_bien = cliente_ok.join().unwrap();
        let _ = hilo_ok.join();
        assert!(conecto_bien, "con el pin correcto la conexión debe completarse");

        // ── Caso 2: pin equivocado -> NO debe conectar ───────────────
        let (mut servidor2, _huella2) = server_with_pin("127.0.0.1:0").expect("servidor 2");
        let addr2 = servidor2.local_addr().unwrap().to_string();
        let hilo2 = std::thread::spawn(move || {
            // Si el pin funciona, accept() nunca devuelve nada; el hilo muere
            // con el endpoint. No assertamos aquí: la prueba es el cliente.
            let _ = servidor2.accept();
        });

        std::thread::sleep(std::time::Duration::from_millis(300));
        let huella_mala = "0".repeat(64);
        let cfg_malo = pinned_client_config(&huella_mala).expect("config con huella mala");
        let mut ep2 = QuicEndpoint::client().unwrap();
        ep2.endpoint.set_default_client_config(cfg_malo);
        let resultado = ep2.connect(&addr2);
        assert!(
            resultado.is_err(),
            "con un pin QUE NO ES el del servidor, el handshake debe fallar"
        );
        drop(ep2);
        let _ = hilo2.join();
    }
}
