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
//! `	oml
//! [dependencies]
//! lumen = { version = "0.1", features = ["quic"] }
//! `

use std::io;
use std::net::SocketAddr;
use std::sync::Arc;

use quinn::{Endpoint, Connection, RecvStream, SendStream, ServerConfig, ClientConfig, TransportConfig};
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
) -> io::Result<(rustls::pki_types::CertificateDer<'static>, rustls::pki_types::PrivateKeyDer<'static>)> {
    let cert = rcgen::generate_simple_self_signed(subject_alt_names.to_vec())
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("cert generation failed: {e}")))?;
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

pub struct QuicEndpoint {
    endpoint: Endpoint,
    runtime: Arc<Runtime>,
}

impl QuicEndpoint {
    pub fn server(addr: &str) -> io::Result<Self> {
        let runtime = Arc::new(tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .thread_name("lumen-quic-server")
            .enable_all()
            .build()
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("tokio runtime: {e}")))?);

        let _guard = runtime.enter();
        let server_config = default_server_config()?;
        let socket_addr: SocketAddr = addr.parse()
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, format!("invalid address '{addr}': {e}")))?;
        let socket = std::net::UdpSocket::bind(socket_addr)
            .map_err(|e| io::Error::new(io::ErrorKind::AddrInUse, format!("UDP bind: {e}")))?;
        let endpoint = runtime.block_on(async {
            Endpoint::new(Default::default(), Some(server_config), socket, Arc::new(quinn::TokioRuntime))
                .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("QUIC endpoint: {e}")))
        })?;

        Ok(Self { endpoint, runtime })
    }

    pub fn client() -> io::Result<Self> {
        let runtime = Arc::new(tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .thread_name("lumen-quic-client")
            .enable_all()
            .build()
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("tokio runtime: {e}")))?);

        let _guard = runtime.enter();
        let client_config = default_client_config()?;
        let socket_addr: SocketAddr = "0.0.0.0:0".parse().unwrap();
        let socket = std::net::UdpSocket::bind(socket_addr)
            .map_err(|e| io::Error::new(io::ErrorKind::AddrInUse, format!("UDP bind: {e}")))?;
        let mut endpoint = runtime.block_on(async {
            Endpoint::new(Default::default(), None, socket, Arc::new(quinn::TokioRuntime))
                .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("QUIC endpoint: {e}")))
        })?;
        endpoint.set_default_client_config(client_config);

        Ok(Self { endpoint, runtime })
    }

    pub fn accept(&mut self) -> io::Result<QuicTransport> {
        self.runtime.block_on(async {
            match self.endpoint.accept().await {
                Some(incoming) => {
                    let conn = incoming.await
                        .map_err(|e| io::Error::new(io::ErrorKind::ConnectionRefused, format!("QUIC handshake failed: {e}")))?;
                    let (send, recv) = conn.accept_bi().await
                        .map_err(|e| io::Error::new(io::ErrorKind::ConnectionReset, format!("stream accept failed: {e}")))?;
                    Ok(QuicTransport {
                        send: Some(send),
                        recv: Some(recv),
                        connection: conn,
                        _endpoint: self.endpoint.clone(),
                        _runtime: self.runtime.clone(),
                        runtime_handle: self.runtime.handle().clone(),
                        read_buffer: Vec::new(),
                        read_pos: 0,
                    })
                }
                None => Err(io::Error::new(io::ErrorKind::NotConnected, "endpoint closed")),
            }
        })
    }

    pub fn connect(&mut self, addr: &str) -> io::Result<QuicTransport> {
        let socket_addr: SocketAddr = addr.parse()
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, format!("invalid address '{addr}': {e}")))?;
        let server_name = "lumen.local".to_string();

        self.runtime.block_on(async {
            let conn = self.endpoint.connect(socket_addr, &server_name)
                .map_err(|e| io::Error::new(io::ErrorKind::ConnectionRefused, format!("QUIC connect: {e}")))?;
            let conn = conn.await
                .map_err(|e| io::Error::new(io::ErrorKind::ConnectionRefused, format!("QUIC handshake failed: {e}")))?;
            let (send, recv) = conn.open_bi().await
                .map_err(|e| io::Error::new(io::ErrorKind::ConnectionReset, format!("stream open failed: {e}")))?;
            Ok(QuicTransport {
                send: Some(send),
                recv: Some(recv),
                connection: conn,
                _endpoint: self.endpoint.clone(),
                _runtime: self.runtime.clone(),
                runtime_handle: self.runtime.handle().clone(),
                read_buffer: Vec::new(),
                read_pos: 0,
            })
        })
    }

    pub fn runtime_handle(&self) -> tokio::runtime::Handle {
        self.runtime.handle().clone()
    }

    pub fn local_addr(&self) -> io::Result<SocketAddr> {
        Ok(self.endpoint.local_addr()
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
}

impl QuicTransport {
    pub fn connect(addr: &str) -> io::Result<Self> {
        let mut endpoint = QuicEndpoint::client()?;
        endpoint.connect(addr)
    }

    pub fn peer_certificate(&self) -> Option<Vec<rustls::pki_types::CertificateDer<'static>>> {
        self.connection.peer_identity()
            .and_then(|id| id.downcast::<Vec<rustls::pki_types::CertificateDer>>().ok())
            .map(|arc| (*arc).clone())
    }

    pub fn remote_address(&self) -> SocketAddr {
        self.connection.remote_address()
    }
}

impl crate::transport::Transport for QuicTransport {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        if self.read_pos < self.read_buffer.len() {
            let remaining = &self.read_buffer[self.read_pos..];
            let n = remaining.len().min(buf.len());
            buf[..n].copy_from_slice(&remaining[..n]);
            self.read_pos += n;
            return Ok(n);
        }

        let recv = self.recv.as_mut()
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotConnected, "recv stream closed"))?;

        self.runtime_handle.block_on(async {
            match recv.read_to_end(65536).await {
                Ok(data) if data.is_empty() => Ok(0),
                Ok(data) => {
                    self.read_buffer = data;
                    let n = self.read_buffer.len().min(buf.len());
                    buf[..n].copy_from_slice(&self.read_buffer[..n]);
                    self.read_pos = n;
                    Ok(n)
                }
                Err(e) => Err(io::Error::new(io::ErrorKind::ConnectionReset, format!("QUIC read: {e}"))),
            }
        })
    }

    fn write_all(&mut self, buf: &[u8]) -> io::Result<()> {
        let send = self.send.as_mut()
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotConnected, "send stream closed"))?;
        let data = buf.to_vec();
        self.runtime_handle.block_on(async {
            send.write_all(&data).await
                .map_err(|e| io::Error::new(io::ErrorKind::ConnectionReset, format!("QUIC write: {e}")))
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
        let quic_cfg = quinn::crypto::rustls::QuicServerConfig::try_from(std::sync::Arc::new(crypto)).unwrap();
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
        crypto.dangerous().set_certificate_verifier(std::sync::Arc::new(SkipCertVerifier));
        crypto.alpn_protocols = vec![b"lumen/1.0".to_vec()];
        crypto.enable_early_data = true;
        let quic_cfg = quinn::crypto::rustls::QuicClientConfig::try_from(std::sync::Arc::new(crypto)).unwrap();
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
                Default::default(), Some(server_config), server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(), None, client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
            client_ep.set_default_client_config(client_config);

            let addr: std::net::SocketAddr = format!("127.0.0.1:{server_port}").parse().unwrap();
            let client_connecting = client_ep.connect(addr, "lumen.local").unwrap();
            let incoming = server_ep.accept().await.unwrap();
            let server_conn = incoming.await.unwrap();
            let client_conn = client_connecting.await.unwrap();

            let (mut client_send, _client_recv) = client_conn.open_bi().await.unwrap();
            client_send.write_all(b"hello lumen over quic").await.unwrap();
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
                Default::default(), Some(server_config), server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(), None, client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
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
                Default::default(), Some(server_config), server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(), None, client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
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
                Default::default(), Some(server_config), server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(), None, client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
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
                Default::default(), Some(server_config), server_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
            let mut client_ep = quinn::Endpoint::new(
                Default::default(), None, client_sock,
                std::sync::Arc::new(quinn::TokioRuntime),
            ).unwrap();
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
