//! Multiplexed logical channels — MUX frame (0x09) payload builders.
//!
//! Enables multiple independent request/response streams over a single
//! transport connection.  Each channel carries its own sequence of
//! REQUEST / RESPONSE / NOTIFY frames without blocking other channels.
//!
//! ## Wire format (little-endian)
//!
//! MUX frame payload:
//! ```text
//! [sub_command: u8][channel_id: u16 LE][payload: variable]
//! ```
//!
//! **Sub-commands:**
//! - `0x00` OPEN  — opens a new logical channel
//! - `0x01` DATA  — carries an inner LUMEN frame on the channel
//! - `0x02` CLOSE — closes the channel (no more DATA accepted)
//! - `0x03` PAUSE — flow control: pause receiving (sender stops)
//! - `0x04` RESUME — flow control: resume receiving
//!
//! **OPEN payload:** empty (channel established by the sub_command alone).
//!
//! **DATA payload:** a complete inner LUMEN frame (Hyb128 header + TYPE +
//! FLAGS + payload).  The inner frame type determines the operation
//! (REQUEST, RESPONSE, NOTIFY, etc.).
//!
//! ## Channel lifecycle
//!
//! ```text
//! [IDLE] --OPEN--> [ACTIVE] --DATA(n times)--> [ACTIVE]
//!   ^                 |  |                        |
//!   |                 |  +--PAUSE--> [PAUSED]-----+
//!   |                 |                |  RESUME  |
//!   |                 +--CLOSE--> [CLOSED]         |
//!   +---------------------------------------------+
//!             (channel_id may be reused after CLOSE)
//! ```

use std::collections::HashMap;

// ── Sub-command constants ───────────────────────────────────────────────────

/// Open a new logical channel.
pub const MUX_OPEN: u8 = 0x00;
/// Carry data on an existing channel (inner frame follows).
pub const MUX_DATA: u8 = 0x01;
/// Close the channel.
pub const MUX_CLOSE: u8 = 0x02;
/// Flow control — pause the channel.
pub const MUX_PAUSE: u8 = 0x03;
/// Flow control — resume the channel.
pub const MUX_RESUME: u8 = 0x04;

// ── MuxFrame ────────────────────────────────────────────────────────────────

/// A decoded MUX frame payload.
///
/// The payload of a TYPE_MUX (0x09) frame decodes into one of these.
/// For DATA sub-commands, `inner` contains the raw bytes of the wrapped
/// LUMEN frame, which should be parsed separately via `frame::parse()`.
#[derive(Debug, Clone)]
pub struct MuxFrame {
    /// Sub-command: OPEN, DATA, CLOSE, PAUSE, or RESUME.
    pub sub_command: u8,
    /// Logical channel identifier (unique within the connection).
    pub channel_id: u16,
    /// For DATA: the raw inner LUMEN frame bytes.  Empty for control
    /// sub-commands (OPEN, CLOSE, PAUSE, RESUME).
    pub inner: Vec<u8>,
}

impl MuxFrame {
    /// Minimum payload size: sub_command + channel_id = 3 bytes.
    pub const MIN_LEN: usize = 3;

    /// Build an OPEN frame (establish a new channel).
    pub fn open(channel_id: u16) -> Self {
        Self {
            sub_command: MUX_OPEN,
            channel_id,
            inner: Vec::new(),
        }
    }

    /// Build a DATA frame carrying an inner LUMEN frame.
    pub fn data(channel_id: u16, inner_frame: Vec<u8>) -> Self {
        Self {
            sub_command: MUX_DATA,
            channel_id,
            inner: inner_frame,
        }
    }

    /// Build a CLOSE frame.
    pub fn close(channel_id: u16) -> Self {
        Self {
            sub_command: MUX_CLOSE,
            channel_id,
            inner: Vec::new(),
        }
    }

    /// Build a PAUSE frame.
    pub fn pause(channel_id: u16) -> Self {
        Self {
            sub_command: MUX_PAUSE,
            channel_id,
            inner: Vec::new(),
        }
    }

    /// Build a RESUME frame.
    pub fn resume(channel_id: u16) -> Self {
        Self {
            sub_command: MUX_RESUME,
            channel_id,
            inner: Vec::new(),
        }
    }

    /// Encode into the binary payload for a MUX frame.
    pub fn encode(&self) -> Vec<u8> {
        let cap = 3 + self.inner.len();
        let mut buf = Vec::with_capacity(cap);
        buf.push(self.sub_command);
        buf.extend_from_slice(&self.channel_id.to_le_bytes());
        buf.extend_from_slice(&self.inner);
        buf
    }

    /// Decode a MUX payload. Returns `None` if too short.
    pub fn decode(data: &[u8]) -> Option<Self> {
        if data.len() < Self::MIN_LEN {
            return None;
        }
        let sub_command = data[0];
        let channel_id = u16::from_le_bytes(data[1..3].try_into().ok()?);
        let inner = data[3..].to_vec();

        Some(Self {
            sub_command,
            channel_id,
            inner,
        })
    }

    /// Returns `true` if this is a DATA sub-command.
    pub fn is_data(&self) -> bool {
        self.sub_command == MUX_DATA
    }

    /// Returns `true` if this is an OPEN sub-command.
    pub fn is_open(&self) -> bool {
        self.sub_command == MUX_OPEN
    }

    /// Returns `true` if this is a CLOSE sub-command.
    pub fn is_close(&self) -> bool {
        self.sub_command == MUX_CLOSE
    }

    /// Human-readable sub-command name.
    pub fn sub_command_name(&self) -> &'static str {
        match self.sub_command {
            MUX_OPEN => "OPEN",
            MUX_DATA => "DATA",
            MUX_CLOSE => "CLOSE",
            MUX_PAUSE => "PAUSE",
            MUX_RESUME => "RESUME",
            _ => "UNKNOWN",
        }
    }

    /// Size of the encoded payload in bytes.
    pub fn encoded_len(&self) -> usize {
        3 + self.inner.len()
    }
}

// ── Channel state ───────────────────────────────────────────────────────────

/// State of a logical channel.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChannelState {
    /// Channel is open and accepting DATA frames.
    Active,
    /// Channel is paused — sender should not send DATA until RESUME.
    Paused,
    /// Channel has been closed.
    Closed,
}

// ── MuxRegistry ─────────────────────────────────────────────────────────────

/// Error returned by [`MuxRegistry`] operations.
#[derive(Debug, PartialEq, Eq)]
pub enum MuxError {
    /// Operation on an unknown channel_id.
    UnknownChannel(u16),
    /// OPEN received for an already-active channel.
    DuplicateChannel(u16),
    /// DATA received on a closed channel.
    ChannelClosed(u16),
    /// DATA received on a paused channel (sender must wait for RESUME).
    ChannelPaused(u16),
    /// CLOSE received on an already-closed channel.
    AlreadyClosed(u16),
    /// Unknown sub_command value.
    UnknownCommand(u8),
}

impl std::fmt::Display for MuxError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UnknownChannel(id) => write!(f, "unknown channel {id}"),
            Self::DuplicateChannel(id) => write!(f, "duplicate channel {id}"),
            Self::ChannelClosed(id) => write!(f, "channel {id} is closed"),
            Self::ChannelPaused(id) => write!(f, "channel {id} is paused"),
            Self::AlreadyClosed(id) => write!(f, "channel {id} already closed"),
            Self::UnknownCommand(cmd) => write!(f, "unknown sub-command 0x{cmd:02x}"),
        }
    }
}

impl std::error::Error for MuxError {}

/// Tracks the state of multiplexed logical channels within a connection.
///
/// Validates channel lifecycle transitions and rejects operations on
/// channels in invalid states.
#[derive(Debug, Default)]
pub struct MuxRegistry {
    channels: HashMap<u16, ChannelState>,
}

impl MuxRegistry {
    /// Create a new empty registry.
    pub fn new() -> Self {
        Self {
            channels: HashMap::new(),
        }
    }

    /// Process an incoming MUX frame and update channel state.
    ///
    /// Returns the inner frame bytes for DATA sub-commands so the caller
    /// can parse and dispatch them.  For control sub-commands (OPEN,
    /// CLOSE, PAUSE, RESUME), returns `Ok(None)`.
    pub fn accept(&mut self, frame: &MuxFrame) -> Result<Option<Vec<u8>>, MuxError> {
        match frame.sub_command {
            MUX_OPEN => {
                if self.channels.contains_key(&frame.channel_id) {
                    return Err(MuxError::DuplicateChannel(frame.channel_id));
                }
                self.channels
                    .insert(frame.channel_id, ChannelState::Active);
                Ok(None)
            }

            MUX_DATA => {
                let state = self
                    .channels
                    .get(&frame.channel_id)
                    .ok_or(MuxError::UnknownChannel(frame.channel_id))?;
                match state {
                    ChannelState::Active => Ok(Some(frame.inner.clone())),
                    ChannelState::Paused => Err(MuxError::ChannelPaused(frame.channel_id)),
                    ChannelState::Closed => Err(MuxError::ChannelClosed(frame.channel_id)),
                }
            }

            MUX_CLOSE => {
                let state = self
                    .channels
                    .get(&frame.channel_id)
                    .ok_or(MuxError::UnknownChannel(frame.channel_id))?;
                if *state == ChannelState::Closed {
                    return Err(MuxError::AlreadyClosed(frame.channel_id));
                }
                self.channels
                    .insert(frame.channel_id, ChannelState::Closed);
                Ok(None)
            }

            MUX_PAUSE => {
                let state = self
                    .channels
                    .get_mut(&frame.channel_id)
                    .ok_or(MuxError::UnknownChannel(frame.channel_id))?;
                if *state == ChannelState::Closed {
                    return Err(MuxError::ChannelClosed(frame.channel_id));
                }
                *state = ChannelState::Paused;
                Ok(None)
            }

            MUX_RESUME => {
                let state = self
                    .channels
                    .get_mut(&frame.channel_id)
                    .ok_or(MuxError::UnknownChannel(frame.channel_id))?;
                if *state == ChannelState::Closed {
                    return Err(MuxError::ChannelClosed(frame.channel_id));
                }
                *state = ChannelState::Active;
                Ok(None)
            }

            _ => Err(MuxError::UnknownCommand(frame.sub_command)),
        }
    }

    /// Remove a channel from the registry (e.g., after CLOSE processed).
    /// This frees the channel_id for reuse.
    pub fn remove(&mut self, channel_id: u16) -> Option<ChannelState> {
        self.channels.remove(&channel_id)
    }

    /// Get the current state of a channel.
    pub fn state(&self, channel_id: u16) -> Option<ChannelState> {
        self.channels.get(&channel_id).copied()
    }

    /// Number of channels (including paused and closed, until removed).
    pub fn len(&self) -> usize {
        self.channels.len()
    }

    /// Returns `true` if there are no channels.
    pub fn is_empty(&self) -> bool {
        self.channels.is_empty()
    }

    /// Number of active (non-paused, non-closed) channels.
    pub fn active_count(&self) -> usize {
        self.channels
            .values()
            .filter(|s| **s == ChannelState::Active)
            .count()
    }
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // ── MuxFrame encode/decode ───────────────────────────────────────────

    #[test]
    fn mux_open_roundtrip() {
        let frame = MuxFrame::open(42);
        assert!(frame.is_open());
        assert!(!frame.is_data());
        assert!(!frame.is_close());
        assert_eq!(frame.inner.len(), 0);

        let encoded = frame.encode();
        assert_eq!(encoded.len(), 3);
        let decoded = MuxFrame::decode(&encoded).unwrap();
        assert_eq!(decoded.sub_command, MUX_OPEN);
        assert_eq!(decoded.channel_id, 42);
        assert!(decoded.inner.is_empty());
    }

    #[test]
    fn mux_data_roundtrip() {
        let inner = b"inner frame bytes".to_vec();
        let frame = MuxFrame::data(7, inner.clone());
        assert!(frame.is_data());

        let encoded = frame.encode();
        let decoded = MuxFrame::decode(&encoded).unwrap();
        assert_eq!(decoded.sub_command, MUX_DATA);
        assert_eq!(decoded.channel_id, 7);
        assert_eq!(decoded.inner, inner);
        assert_eq!(decoded.encoded_len(), encoded.len());
    }

    #[test]
    fn mux_close_roundtrip() {
        let frame = MuxFrame::close(99);
        assert!(frame.is_close());
        assert_eq!(frame.sub_command_name(), "CLOSE");

        let encoded = frame.encode();
        let decoded = MuxFrame::decode(&encoded).unwrap();
        assert_eq!(decoded.sub_command, MUX_CLOSE);
        assert_eq!(decoded.channel_id, 99);
    }

    #[test]
    fn mux_pause_resume_roundtrip() {
        let pause = MuxFrame::pause(1);
        let resume = MuxFrame::resume(1);

        assert_eq!(pause.sub_command, MUX_PAUSE);
        assert_eq!(resume.sub_command, MUX_RESUME);

        let dec_pause = MuxFrame::decode(&pause.encode()).unwrap();
        let dec_resume = MuxFrame::decode(&resume.encode()).unwrap();
        assert_eq!(dec_pause.sub_command, MUX_PAUSE);
        assert_eq!(dec_resume.sub_command, MUX_RESUME);
    }

    #[test]
    fn mux_decode_too_short() {
        assert!(MuxFrame::decode(&[]).is_none());
        assert!(MuxFrame::decode(&[0x00, 0x01]).is_none()); // 2 bytes, need 3
        assert!(MuxFrame::decode(&[0x00, 0x01, 0x02]).is_some()); // 3 bytes = ok
    }

    #[test]
    fn mux_unknown_command_name() {
        let frame = MuxFrame {
            sub_command: 0xFF,
            channel_id: 0,
            inner: vec![],
        };
        assert_eq!(frame.sub_command_name(), "UNKNOWN");
    }

    // ── MuxRegistry ──────────────────────────────────────────────────────

    #[test]
    fn registry_open_and_data() {
        let mut reg = MuxRegistry::new();
        assert!(reg.is_empty());

        // Open channel
        assert!(reg.accept(&MuxFrame::open(1)).unwrap().is_none());
        assert_eq!(reg.state(1), Some(ChannelState::Active));
        assert_eq!(reg.active_count(), 1);

        // Send data
        let inner = reg
            .accept(&MuxFrame::data(1, b"hello".to_vec()))
            .unwrap();
        assert_eq!(inner, Some(b"hello".to_vec()));
    }

    #[test]
    fn registry_duplicate_open_rejected() {
        let mut reg = MuxRegistry::new();
        reg.accept(&MuxFrame::open(1)).unwrap();
        assert!(matches!(
            reg.accept(&MuxFrame::open(1)),
            Err(MuxError::DuplicateChannel(1))
        ));
    }

    #[test]
    fn registry_unknown_channel_rejected() {
        let mut reg = MuxRegistry::new();
        assert!(matches!(
            reg.accept(&MuxFrame::data(999, vec![])),
            Err(MuxError::UnknownChannel(999))
        ));
    }

    #[test]
    fn registry_lifecycle() {
        let mut reg = MuxRegistry::new();

        // OPEN → ACTIVE
        reg.accept(&MuxFrame::open(1)).unwrap();
        assert_eq!(reg.active_count(), 1);

        // DATA passes through
        reg.accept(&MuxFrame::data(1, b"a".to_vec())).unwrap();

        // PAUSE
        reg.accept(&MuxFrame::pause(1)).unwrap();
        assert_eq!(reg.state(1), Some(ChannelState::Paused));
        assert_eq!(reg.active_count(), 0);

        // DATA rejected while paused
        assert!(matches!(
            reg.accept(&MuxFrame::data(1, b"b".to_vec())),
            Err(MuxError::ChannelPaused(1))
        ));

        // RESUME
        reg.accept(&MuxFrame::resume(1)).unwrap();
        assert_eq!(reg.state(1), Some(ChannelState::Active));
        assert_eq!(reg.active_count(), 1);

        // DATA accepted again
        reg.accept(&MuxFrame::data(1, b"c".to_vec())).unwrap();

        // CLOSE
        reg.accept(&MuxFrame::close(1)).unwrap();
        assert_eq!(reg.state(1), Some(ChannelState::Closed));

        // DATA rejected after close
        assert!(matches!(
            reg.accept(&MuxFrame::data(1, b"d".to_vec())),
            Err(MuxError::ChannelClosed(1))
        ));

        // CLOSE again rejected
        assert!(matches!(
            reg.accept(&MuxFrame::close(1)),
            Err(MuxError::AlreadyClosed(1))
        ));

        // Remove and re-open
        reg.remove(1);
        assert!(reg.accept(&MuxFrame::open(1)).is_ok());
        assert_eq!(reg.state(1), Some(ChannelState::Active));
    }

    #[test]
    fn registry_multiple_channels() {
        let mut reg = MuxRegistry::new();

        for id in 0..10u16 {
            reg.accept(&MuxFrame::open(id)).unwrap();
        }
        assert_eq!(reg.len(), 10);
        assert_eq!(reg.active_count(), 10);

        // Close half
        for id in 0..5u16 {
            reg.accept(&MuxFrame::close(id)).unwrap();
        }
        assert_eq!(reg.active_count(), 5);
        assert_eq!(reg.len(), 10); // closed channels still registered

        // Remove closed channels
        for id in 0..5u16 {
            reg.remove(id);
        }
        assert_eq!(reg.len(), 5);
    }

    #[test]
    fn registry_unknown_command_rejected() {
        let mut reg = MuxRegistry::new();
        reg.accept(&MuxFrame::open(1)).unwrap();

        let bad = MuxFrame {
            sub_command: 0xFF,
            channel_id: 1,
            inner: vec![],
        };
        assert!(matches!(
            reg.accept(&bad),
            Err(MuxError::UnknownCommand(0xFF))
        ));
    }

    #[test]
    fn registry_pause_resume_on_closed_rejected() {
        let mut reg = MuxRegistry::new();
        reg.accept(&MuxFrame::open(1)).unwrap();
        reg.accept(&MuxFrame::close(1)).unwrap();

        assert!(matches!(
            reg.accept(&MuxFrame::pause(1)),
            Err(MuxError::ChannelClosed(1))
        ));
        assert!(matches!(
            reg.accept(&MuxFrame::resume(1)),
            Err(MuxError::ChannelClosed(1))
        ));
    }

    #[test]
    fn encoded_len_matches_encode() {
        let open = MuxFrame::open(1);
        assert_eq!(open.encode().len(), open.encoded_len());

        let data = MuxFrame::data(1, vec![0u8; 100]);
        assert_eq!(data.encode().len(), data.encoded_len());

        let close = MuxFrame::close(1);
        assert_eq!(close.encode().len(), close.encoded_len());
    }

    // ── Edge cases ──────────────────────────────────────────────────────

    #[test]
    fn mux_channel_id_max() {
        let frame = MuxFrame::open(u16::MAX);
        let decoded = MuxFrame::decode(&frame.encode()).unwrap();
        assert_eq!(decoded.channel_id, u16::MAX);
    }

    #[test]
    fn mux_double_pause_idempotent() {
        let mut reg = MuxRegistry::new();
        reg.accept(&MuxFrame::open(1)).unwrap();
        reg.accept(&MuxFrame::pause(1)).unwrap();
        assert_eq!(reg.state(1), Some(ChannelState::Paused));
        // Second pause on already-paused channel should succeed (idempotent)
        reg.accept(&MuxFrame::pause(1)).unwrap();
        assert_eq!(reg.state(1), Some(ChannelState::Paused));
    }

    #[test]
    fn mux_resume_when_active_idempotent() {
        let mut reg = MuxRegistry::new();
        reg.accept(&MuxFrame::open(1)).unwrap();
        // Resume on already-active channel should succeed (idempotent)
        reg.accept(&MuxFrame::resume(1)).unwrap();
        assert_eq!(reg.state(1), Some(ChannelState::Active));
    }

    #[test]
    fn mux_close_paused_channel() {
        let mut reg = MuxRegistry::new();
        reg.accept(&MuxFrame::open(1)).unwrap();
        reg.accept(&MuxFrame::pause(1)).unwrap();
        // Closing a paused channel should work
        reg.accept(&MuxFrame::close(1)).unwrap();
        assert_eq!(reg.state(1), Some(ChannelState::Closed));
    }

    #[test]
    fn mux_remove_idle_channel() {
        let mut reg = MuxRegistry::new();
        reg.accept(&MuxFrame::open(1)).unwrap();
        reg.accept(&MuxFrame::close(1)).unwrap();
        let old_state = reg.remove(1);
        assert_eq!(old_state, Some(ChannelState::Closed));
        // Now channel_id 1 is free — open should work
        assert!(reg.accept(&MuxFrame::open(1)).is_ok());
    }

    #[test]
    fn mux_remove_nonexistent() {
        let mut reg = MuxRegistry::new();
        assert_eq!(reg.remove(999), None);
        assert_eq!(reg.state(999), None);
    }

    #[test]
    fn mux_data_empty_inner() {
        // DATA with empty inner frame — unusual but valid
        let frame = MuxFrame::data(1, vec![]);
        let mut reg = MuxRegistry::new();
        reg.accept(&MuxFrame::open(1)).unwrap();
        let inner = reg.accept(&frame).unwrap();
        assert_eq!(inner, Some(vec![]));
    }

    #[test]
    fn mux_is_predicates_unknown_command() {
        let bad = MuxFrame {
            sub_command: 0xFF,
            channel_id: 0,
            inner: vec![],
        };
        assert!(!bad.is_open());
        assert!(!bad.is_data());
        assert!(!bad.is_close());
        assert_eq!(bad.sub_command_name(), "UNKNOWN");
    }
}
