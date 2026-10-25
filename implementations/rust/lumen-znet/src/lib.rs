//! ZNET — la primitiva de red `$ZNET` de MSM, reimplementada sobre LUMEN.
//!
//! # Qué es esto
//!
//! MSM tiene seis funciones intrínsecas de red bajo el nombre `$ZNET`. Son el único punto
//! donde el sistema de replicación DDP toca el sistema operativo. Este crate las reimplementa
//! sobre frames LUMEN en vez de sobre la pila de red nativa de MSM.
//!
//! # Por qué existe
//!
//! Solo **3 de 438 rutinas** usan `$ZNET` (`DDPSRV`, `STUDDP`, `WSAGENT`) — 3,9 KB de código.
//! Pero `$ZNET` no existe en Cloudflare Workers, así que el transporte hay que sustituirlo.
//! En vez de inventar un protocolo nuevo, se usa LUMEN, que ya está implementado, ya está
//! enlazado en `mvm-nas` y comparte naturaleza binaria con el DDP original.
//!
//! # Las seis funciones
//!
//! | `$ZNET` | Semántica | Este crate |
//! |---|---|---|
//! | `(17)` | inicializar red | [`znet_init`] |
//! | `(22, M)` | crear circuito | [`znet_connect`] |
//! | `(30)` | inicializar enlace | [`znet_link_init`] |
//! | `(8)` | recv bloqueante | [`Znet::recv`] |
//! | `(9, x)` | responder | [`Znet::reply`] |
//! | `(31)` | recv de circuitos | [`Znet::recv_circuit`] |
//!
//! # El mapeo de mensajes
//!
//! DDP transporta mensajes con cabecera de posiciones fijas:
//!
//! ```text
//! M: [tipo:1][num1:2 LE][num2:2 LE][flag:1][carga útil...]
//! ```
//!
//! Y LUMEN frames son `[Hyb128 len][type:1][flags:1][payload]`. El mapeo es directo:
//!
//! ```text
//! M[1]     tipo     -> frame type
//! M[2..3]  num1     -> correlation id (primeros 2 bytes del payload)
//! M[4..5]  num2     -> channel id  (siguientes 2 bytes del payload)
//! M[6]     flag     -> flags del frame
//! M[7..]   carga    -> resto del payload
//! ```
//!
//! Los 4 bytes big-endian que `DDPSRV` construye con `$ZCHAR($ZB##100, ...)` son el
//! identificador de mensaje; aquí viajan como los 4 primeros bytes del payload.

use std::collections::VecDeque;
use std::fmt;

// ── Constantes del protocolo DDP ────────────────────────────────────────────

/// Tamaño de la cabecera fija de un mensaje DDP: tipo(1) + num1(2) + num2(2) + flag(1).
pub const DDP_HEADER_LEN: usize = 6;

/// Tipos de mensaje DDP observados en `DDPSRV`.
pub mod msg_type {
    /// Mensaje de datos normal.
    pub const DATA: u8 = 0x01;
    /// Respuesta de éxito.
    pub const SUCCESS: u8 = 0x02;
    /// Respuesta de fallo.
    pub const FAILURE: u8 = 0x03;
    /// Mensaje vacío (sin carga útil).
    pub const EMPTY: u8 = 0x04;
    /// Error de circuito.
    pub const CIRCUIT_ERROR: u8 = 0x0B;
}

/// Las respuestas que `$ZNET(9, x)` acepta, tal como aparecen en `DDPSRV`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ZnetReply {
    /// `$ZNET(9, "S")` — success.
    Success,
    /// `$ZNET(9, "F")` — failure.
    Failure,
    /// `$ZNET(9, "")` — vacío.
    Empty,
    /// `$ZNET(9, $ZCHAR(...))` — datos binarios (4 bytes big-endian en el original).
    Data(Vec<u8>),
}

// ── Errores ─────────────────────────────────────────────────────────────────

/// Errores de ZNET. Los nombres siguen la terminología de MSM.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ZnetError {
    /// `$ZNET(17)` no se ha llamado: el subsistema no está inicializado.
    NotInitialized,
    /// No hay circuito para ese destino. En MSM: "Failed to Create Circuit".
    NoCircuit(String),
    /// Mensaje malformado: no llega al tamaño de la cabecera DDP.
    MalformedMessage { len: usize, min: usize },
    /// Destino vacío o inválido.
    InvalidDestination,
}

impl fmt::Display for ZnetError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotInitialized => write!(f, "ZNET no inicializado: falta $ZNET(17)"),
            Self::NoCircuit(d) => write!(f, "Failed to Create Circuit {d}"),
            Self::MalformedMessage { len, min } => {
                write!(f, "mensaje de {len} bytes, minimo {min}")
            }
            Self::InvalidDestination => write!(f, "destino invalido"),
        }
    }
}

impl std::error::Error for ZnetError {}

// ── Mensaje DDP ─────────────────────────────────────────────────────────────

/// Un mensaje DDP, con la cabecera descrita en `DDPSRV`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DdpMessage {
    /// Tipo de mensaje (`msg_type::*`).
    pub kind: u8,
    /// Primer número de la cabecera. En `DDPSRV` es el id de mensaje.
    pub num1: u16,
    /// Segundo número. En `DDPSRV` es el canal / circuito.
    pub num2: u16,
    /// Bandera de la cabecera.
    pub flag: u8,
    /// Carga útil: el texto a partir de `M[7]`.
    pub body: Vec<u8>,
}

impl DdpMessage {
    /// Construye un mensaje a partir de sus partes.
    pub fn new(kind: u8, num1: u16, num2: u16, flag: u8, body: Vec<u8>) -> Self {
        Self { kind, num1, num2, flag, body }
    }

    /// Serializa al formato binario de DDP: la cadena `M` del original.
    pub fn encode(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(DDP_HEADER_LEN + self.body.len());
        out.push(self.kind);
        out.extend_from_slice(&self.num1.to_le_bytes());
        out.extend_from_slice(&self.num2.to_le_bytes());
        out.push(self.flag);
        out.extend_from_slice(&self.body);
        out
    }

    /// Deserializa desde el formato binario de DDP.
    ///
    /// Es aquí donde se rechaza un mensaje malformado: si no llega a la cabecera,
    /// no se puede interpretar. `DDPSRV` asume que siempre llega.
    pub fn decode(bytes: &[u8]) -> Result<Self, ZnetError> {
        if bytes.len() < DDP_HEADER_LEN {
            return Err(ZnetError::MalformedMessage {
                len: bytes.len(),
                min: DDP_HEADER_LEN,
            });
        }
        Ok(Self {
            kind: bytes[0],
            num1: u16::from_le_bytes([bytes[1], bytes[2]]),
            num2: u16::from_le_bytes([bytes[3], bytes[4]]),
            flag: bytes[5],
            body: bytes[DDP_HEADER_LEN..].to_vec(),
        })
    }
}

// ── Conversión DDP <-> LUMEN ────────────────────────────────────────────────

/// Traduce un mensaje DDP a un frame LUMEN.
///
/// El mensaje DDP entero viaja como payload del frame, menos el tipo, que pasa a ser
/// el tipo del frame. Así el receptor puede clasificar sin deserializar el cuerpo.
pub fn ddp_to_frame(msg: &DdpMessage) -> (u8, u8, Vec<u8>) {
    // El payload son los 5 bytes de cabecera restantes + el cuerpo.
    let mut payload = Vec::with_capacity(5 + msg.body.len());
    payload.extend_from_slice(&msg.num1.to_le_bytes());
    payload.extend_from_slice(&msg.num2.to_le_bytes());
    payload.push(msg.flag);
    payload.extend_from_slice(&msg.body);
    (msg.kind, msg.flag, payload)
}

/// Traduce un frame LUMEN de vuelta a mensaje DDP.
///
/// El tipo del frame es el tipo del mensaje. Si el payload no llega a los 5 bytes
/// de cabecera restante, el frame no es un mensaje DDP.
pub fn frame_to_ddp(frame_type: u8, payload: &[u8]) -> Result<DdpMessage, ZnetError> {
    if payload.len() < 5 {
        return Err(ZnetError::MalformedMessage {
            len: payload.len(),
            min: 5,
        });
    }
    Ok(DdpMessage {
        kind: frame_type,
        num1: u16::from_le_bytes([payload[0], payload[1]]),
        num2: u16::from_le_bytes([payload[2], payload[3]]),
        flag: payload[4],
        body: payload[5..].to_vec(),
    })
}

// ── Estado del subsistema ───────────────────────────────────────────────────

/// Un circuito abierto, equivalente a la entrada de la tabla de circuitos de `DDPSRV`.
#[derive(Debug, Clone)]
pub struct Circuit {
    /// Destino, tal como se pasó a `$ZNET(22, M)`.
    pub dest: String,
    /// Identificador numérico del circuito.
    pub id: u16,
}

/// El subsistema ZNET.
///
/// Sustituye al estado global que en MSM vive en la tabla de circuitos del intérprete.
/// Aquí es explícito: se crea, se inicializa, y se le pasan mensajes.
pub struct Znet {
    initialized: bool,
    next_circuit_id: u16,
    circuits: Vec<Circuit>,
    /// Cola de mensajes recibidos. En MSM es la cola de red del intérprete.
    inbox: VecDeque<DdpMessage>,
    /// Cola de mensajes por circuito. En MSM es la cola de la tabla de circuitos.
    circuit_inbox: VecDeque<(u16, DdpMessage)>,
}

impl Default for Znet {
    fn default() -> Self {
        Self::new()
    }
}

impl Znet {
    /// Crea el subsistema, sin inicializar. Equivale a tener el intérprete arrancado
    /// pero sin haber llamado a `$ZNET(17)`.
    pub fn new() -> Self {
        Self {
            initialized: false,
            next_circuit_id: 1,
            circuits: Vec::new(),
            inbox: VecDeque::new(),
            circuit_inbox: VecDeque::new(),
        }
    }

    /// `$ZNET(17)` — inicializa el subsistema de red.
    pub fn init(&mut self) -> bool {
        self.initialized = true;
        true
    }

    /// `$ZNET(22, M)` — crea un circuito hacia un destino.
    ///
    /// Devuelve el identificador del circuito, o error si el destino está vacío
    /// o el subsistema no está inicializado. En MSM, un fallo aquí produce
    /// `"Failed to Create Circuit"` con `FAILCODE=51`, como en `WSAGENT`.
    pub fn connect(&mut self, dest: &str) -> Result<u16, ZnetError> {
        if !self.initialized {
            return Err(ZnetError::NotInitialized);
        }
        if dest.trim().is_empty() {
            return Err(ZnetError::InvalidDestination);
        }
        if let Some(c) = self.circuits.iter().find(|c| c.dest == dest) {
            return Ok(c.id);
        }
        let id = self.next_circuit_id;
        self.next_circuit_id = self.next_circuit_id.wrapping_add(1);
        self.circuits.push(Circuit { dest: dest.to_string(), id });
        Ok(id)
    }

    /// `$ZNET(30)` — inicializa un enlace concreto.
    ///
    /// En MSM asocia un LCB (link control block) a un número de enlace y puede dejarlo
    /// "Offline" si falla. Aquí el enlace es un circuito; devuelve `true` si quedó arriba.
    pub fn link_init(&mut self, dest: &str) -> bool {
        self.connect(dest).is_ok()
    }

    /// Circuitos abiertos. Equivale a `ALLINKS^DDPSRV` y a `^DDP("circuits")`.
    pub fn circuits(&self) -> &[Circuit] {
        &self.circuits
    }

    /// Cierra un circuito. `DDPSRV` lo hace en `CIRSHUT^DDPCIR`.
    pub fn close_circuit(&mut self, id: u16) -> bool {
        let before = self.circuits.len();
        self.circuits.retain(|c| c.id != id);
        self.circuits.len() != before
    }

    /// Encola un mensaje como si llegara de la red. Sustituye al `recv` del sistema.
    pub fn push_incoming(&mut self, msg: DdpMessage) {
        self.inbox.push_back(msg);
    }

    /// `$ZNET(8)` — recoge el siguiente mensaje de la cola de red.
    ///
    /// En MSM esta llamada **bloquea** hasta que llega un mensaje (`V 100:$J:0:4` en
    /// `DDPSRV`). Aquí es no bloqueante y devuelve `None` si no hay nada: el bloqueo
    /// lo pone quien llama, que es lo correcto cuando hay un event loop debajo.
    pub fn recv(&mut self) -> Option<DdpMessage> {
        self.inbox.pop_front()
    }

    /// `$ZNET(9, x)` — responde al mensaje en curso.
    ///
    /// El resultado se traduce a un mensaje DDP que se encola en la cola de circuitos.
    /// En `DDPSRV`: `"S"` responde éxito, `"F"` fallo, `""` vacío, y 4 bytes de datos
    /// se envían tal cual.
    pub fn reply(&mut self, circuit: u16, reply: ZnetReply) -> Result<(), ZnetError> {
        let msg = match reply {
            ZnetReply::Success => DdpMessage::new(msg_type::SUCCESS, 0, circuit, 0, Vec::new()),
            ZnetReply::Failure => {
                DdpMessage::new(msg_type::FAILURE, 0, circuit, 0, Vec::new())
            }
            ZnetReply::Empty => DdpMessage::new(msg_type::EMPTY, 0, circuit, 0, Vec::new()),
            ZnetReply::Data(d) => DdpMessage::new(msg_type::DATA, 0, circuit, 0, d),
        };
        self.circuit_inbox.push_back((circuit, msg));
        Ok(())
    }

    /// `$ZNET(31)` — recoge el siguiente mensaje de la cola de circuitos.
    pub fn recv_circuit(&mut self) -> Option<(u16, DdpMessage)> {
        self.circuit_inbox.pop_front()
    }

    /// Cuántos mensajes esperan en la cola de red. Útil para tests y para decidir
    /// si hace falta bloquear.
    pub fn pending(&self) -> usize {
        self.inbox.len()
    }
}

// ── Pruebas ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn init_es_necesario_para_conectar() {
        let mut z = Znet::new();
        assert_eq!(z.connect("192.168.1.10"), Err(ZnetError::NotInitialized));
        z.init();
        assert!(z.connect("192.168.1.10").is_ok());
    }

    #[test]
    fn circuito_repetido_devuelve_el_mismo_id() {
        let mut z = Znet::new();
        z.init();
        let a = z.connect("hub").unwrap();
        let b = z.connect("hub").unwrap();
        assert_eq!(a, b);
        assert_eq!(z.circuits().len(), 1);
    }

    #[test]
    fn destino_vacio_falla_como_en_wsagent() {
        let mut z = Znet::new();
        z.init();
        assert_eq!(z.connect("  "), Err(ZnetError::InvalidDestination));
    }

    #[test]
    fn mensaje_ddp_ida_y_vuelta() {
        let original = DdpMessage::new(msg_type::DATA, 0x1234, 7, 1, b"hola".to_vec());
        let bytes = original.encode();
        assert_eq!(bytes.len(), DDP_HEADER_LEN + 4);
        let recuperado = DdpMessage::decode(&bytes).unwrap();
        assert_eq!(original, recuperado);
    }

    #[test]
    fn mensaje_corto_se_rechaza() {
        let err = DdpMessage::decode(&[1, 2, 3]).unwrap_err();
        assert_eq!(err, ZnetError::MalformedMessage { len: 3, min: 6 });
    }

    #[test]
    fn ddp_a_lumen_y_vuelta_conserva_todo() {
        let original = DdpMessage::new(msg_type::DATA, 42, 9, 3, b"carga".to_vec());
        let (ftype, _flags, payload) = ddp_to_frame(&original);
        let vuelta = frame_to_ddp(ftype, &payload).unwrap();
        assert_eq!(original.kind, vuelta.kind);
        assert_eq!(original.num1, vuelta.num1);
        assert_eq!(original.num2, vuelta.num2);
        assert_eq!(original.flag, vuelta.flag);
        assert_eq!(original.body, vuelta.body);
    }

    #[test]
    fn recv_y_reply_usan_colas_distintas() {
        let mut z = Znet::new();
        z.init();
        let c = z.connect("hub").unwrap();
        z.push_incoming(DdpMessage::new(msg_type::DATA, 1, c, 0, b"x".to_vec()));
        assert_eq!(z.pending(), 1);
        assert!(z.recv().is_some());
        assert_eq!(z.pending(), 0);

        z.reply(c, ZnetReply::Success).unwrap();
        let (cid, msg) = z.recv_circuit().unwrap();
        assert_eq!(cid, c);
        assert_eq!(msg.kind, msg_type::SUCCESS);
    }

    #[test]
    fn reply_failure_y_vacio_tienen_tipos_distintos() {
        let mut z = Znet::new();
        z.init();
        z.reply(1, ZnetReply::Failure).unwrap();
        z.reply(1, ZnetReply::Empty).unwrap();
        assert_eq!(z.recv_circuit().unwrap().1.kind, msg_type::FAILURE);
        assert_eq!(z.recv_circuit().unwrap().1.kind, msg_type::EMPTY);
    }

    #[test]
    fn reply_con_datos_binarios_conserva_los_bytes() {
        let mut z = Znet::new();
        z.init();
        // Los 4 bytes big-endian que DDPSRV arma con $ZCHAR($ZB##100, ...)
        let datos = vec![0x00, 0x00, 0x01, 0x2C];
        z.reply(1, ZnetReply::Data(datos.clone())).unwrap();
        let msg = z.recv_circuit().unwrap().1;
        assert_eq!(msg.kind, msg_type::DATA);
        assert_eq!(msg.body, datos);
    }

    #[test]
    fn cerrar_circuito_lo_quita() {
        let mut z = Znet::new();
        z.init();
        let c = z.connect("hub").unwrap();
        assert!(z.close_circuit(c));
        assert!(z.circuits().is_empty());
        assert!(!z.close_circuit(c));
    }
}
