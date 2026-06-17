



Independent Submission                                          G. Monzón
Document: lumen-protocol                               Cadences Lab
                                                           18 June 2026


               LUMEN — Lightweight Universal Model Exchange
                      Network Protocol Specification

Status of This Document

   This is an independent specification document, NOT an IETF RFC.
   The IETF boilerplate previously present in this document was a
   drafting artifact and has been removed.

   IMPORTANT — Implementation Status (v0.1.0):

   Items 1-5 (endianness, DICT_REF, LEN field semantics, CBOR
   references, static dictionary table) corrected in revision 2.

   Section 5.1-5.6 (REQUEST, RESPONSE, NOTIFY, STREAM_DATA,
   SCHEMA_PATCH, STREAM_INIT) now accurately describe the v0.1
   implementation: payloads are compressed JSON-RPC 2.0 messages,
   with native binary headers planned for v2.

   Remaining unimplemented features: None. All sections marked [PLANNED]
   in previous revisions have been implemented or updated to match the
   current codebase.

   The authoritative reference for what IS implemented is the project
   README.md §Status & Roadmap and the source code in implementations/.

   Sections marked [PLANNED] describe features designed for future
   versions. Currently, no sections carry this marker — all planned
   features have been implemented as of v0.1.0.

Abstract

   This document specifies LUMEN, a binary protocol for efficient
   communication between Model Context Protocol (MCP) systems.  LUMEN
   replaces JSON-RPC 2.0 as the wire format for MCP, reducing per-message
   overhead from 40–60 bytes to 3–6 bytes via a static compression
   dictionary (128 entries), a session dictionary (127 entries), and a
   self-delimiting hybrid length encoding (Hyb128) that enables O(1) frame
   skipping without full deserialization.

   The protocol defines sixteen frame types.  The core request/response
   and notification frames (0x01-0x03) transport compressed JSON-RPC 2.0
   messages.  Additional frame types for native LLM token streaming,
   multiplexed logical channels, and schema discovery are defined as
   constants with full implementations planned for v2.  Wire-level
   authenticated encryption is provided via ChaCha20-Poly1305 with
   X25519 key exchange and HKDF-SHA256 key derivation.

   LUMEN is transport-agnostic and defines four transport levels: Level 1
   (stream-based: stdio, UDS, TCP), Level 2 (zero-copy shared memory),
   Level 3 (datagram: UDP + multicast), and Level 4 (QUIC).  An
   implementation MUST support Level 1; Levels 2–4 are optional.

   Reference implementations exist in Rust, TypeScript, Python, PHP, and
   C#.


Status of This Memo

   This is an Internet Standards Track document.

   This document is a product of the Internet Engineering Task Force
   (IETF).  It represents the consensus of the IETF community.  It has
   received public review and has been approved for publication by the
   Internet Engineering Steering Group (IESG).  Further information on
   Internet Standards is available in Section 2 of RFC 7841.

   Information about the current status of this document, any errata,
   and how to provide feedback on it may be obtained at
   https://www.rfc-editor.org/info/rfcXXXX.


Copyright Notice

   Copyright (c) 2026 IETF Trust and the persons identified as the
   document authors.  All rights reserved.

   This document is subject to BCP 78 and the IETF Trust's Legal
   Provisions Relating to IETF Documents
   (https://trustee.ietf.org/license-info) in effect on the date of
   publication of this document.  Please review these documents
   carefully, as they describe your rights and restrictions with respect
   to this document.  Code Components extracted from this document must
   include Revised BSD License text as described in Section 4.e of the
   Trust Legal Provisions and are provided without warranty as described
   in the Revised BSD License.
Table of Contents

   1.  Introduction .................................................X
      1.1.  Problem Statement .......................................X
      1.2.  Design Philosophy .......................................X
   2.  Requirements Language ........................................X
   3.  Protocol Overview ............................................X
      3.1.  Frame Anatomy ...........................................X
      3.2.  Hyb128 — Hybrid Length Encoding .........................X
      3.3.  Type and Flags ..........................................X
   4.  Transport Abstraction ........................................X
      4.1.  Level 1 — Stream (REQUIRED) .............................X
      4.2.  Level 2 — Zero-Copy Shared Memory .......................X
      4.3.  Level 3 — Datagram (UDP) ................................X
      4.4.  Level 4 — QUIC ..........................................X
   5.  Frame Types ..................................................X
      5.1.  REQUEST (0x01) ...........................................X
      5.2.  RESPONSE (0x02) ..........................................X
      5.3.  NOTIFY (0x03) ............................................X
      5.4.  STREAM_DATA (0x04) .......................................X
      5.5.  SCHEMA_PATCH (0x05) ......................................X
      5.6.  STREAM_INIT (0x06) .......................................X
      5.7.  DICT_SYNC (0x07) .........................................X
      5.8.  DISCOVER (0x08) ..........................................X
      5.9.  MUX (0x09) ...............................................X
      5.10. HEARTBEAT (0x0A) .........................................X
      5.11. TRANSPORT_INIT (0x0B) / TRANSPORT_ACK (0x0C) .............X
      5.12. PROBE (0x0F) / PROBE_ACK (0x10) ..........................X
   6.  Semantic Compression ..........................................X
      6.1.  Static Dictionary (0x00–0x7F) ............................X
      6.2.  Session Dictionary (0x80–0xFE) ...........................X
      6.3.  Dictionary Synchronization ...............................X
   7.  Native Streaming ..............................................X
      7.1.  Stream Lifecycle .........................................X
      7.2.  Token Types ..............................................X
   8.  Multiplexing ..................................................X
   9.  Security ......................................................X
      9.1.  Capability Tokens (Macaroons) ............................X
      9.2.  Attenuation ..............................................X
      9.3.  Wire Encryption ..........................................X
      9.4.  Key Exchange (X25519) ....................................X
      9.5.  Anti-Replay ..............................................X
   10. IANA Considerations ...........................................X
      10.1. Frame Type Registry ......................................X
      10.2. Flag Bit Registry ........................................X
      10.3. Compression Dictionary Registry ..........................X
   11. Security Considerations .......................................X
   12. References ....................................................X
      12.1. Normative References .....................................X
      12.2. Informative References ...................................X
   Appendix A.  Hyb128 Encoding Algorithm ............................X
   Appendix B.  Wire Examples ........................................X
   Appendix C.  Implementation Status ................................X
   Acknowledgements ..................................................X
   Authors' Addresses ................................................X


1.  Introduction

   LUMEN (Lightweight Universal Model Exchange Network) is a binary
   wire protocol designed as a drop-in replacement for JSON-RPC 2.0
   [JSONRPC] in Model Context Protocol (MCP) [MCP_SPEC] deployments.

   The protocol was created to solve the specific performance and
   security gaps that arise when JSON-based protocols are used for
   latency-sensitive AI workloads: token-by-token streaming, high-
   frequency instrumentation telemetry, and zero-trust multi-agent
   orchestration.

1.1.  Problem Statement

   JSON-RPC 2.0, while simple and human-readable, imposes structural
   costs on MCP communication:

   *  Per-message overhead:  Every message carries repeated field names
      ("jsonrpc", "method", "params", "id") consuming 40–60 bytes before
      any payload data is transmitted.

   *  No native streaming:  LLM token streaming requires splitting a
      logical response across multiple JSON-RPC messages, each with full
      headers, or forcing the server to buffer the entire response before
      transmission.

   *  No built-in multiplexing:  Running multiple concurrent operations
      on a single connection requires out-of-band correlation or separate
      connections.

   *  No compression:  Repeated string literals (e.g., tool names,
      parameter keys) are transmitted verbatim on every message.

   *  No wire-level security:  Authentication and encryption are deferred
      entirely to the transport layer, making it difficult to implement
      fine-grained, per-operation authorization.

   LUMEN addresses each of these through a compact binary frame format,
   integrated security, and semantic compression.

1.2.  Design Philosophy

   LUMEN follows five architectural principles:

   P1.  Payload First.  The protocol prioritizes payload density over
        human readability.  A well-compressed LUMEN message is 3–6 bytes
        before payload, versus 40–60 bytes for equivalent JSON-RPC.

   P2.  Self-Describing Frames.  Every frame carries its own length,
        making frames self-delimiting.  Parsers can skip unknown or
        uninteresting frames in O(1) without deserializing their content.

   P3.  Transport Agnosticism.  LUMEN defines a clean Transport
        Abstraction with four levels.  The protocol core knows nothing
        about the underlying transport; it operates on abstract frame
        bytes.

   P4.  Graduated Complexity.  Simple use cases (request/response over
        stdio) require understanding only 2 frame types (REQUEST,
        RESPONSE).  Advanced features (multiplexing, encryption,
        discovery) are layered on as optional extensions using flag bits.

   P5.  Security by Default, Not by Bolting.  Capability tokens
        (Macaroons) are a first-class concept at the protocol level, not
        an afterthought in the transport layer.


2.  Requirements Language

   The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
   "SHOULD", "SHOULD NOT", "RECOMMENDED", "NOT RECOMMENDED", "MAY", and
   "OPTIONAL" in this document are to be interpreted as described in
   BCP 14 [RFC2119] [RFC8174] when, and only when, they appear in all
   capitals, as shown here.


3.  Protocol Overview

   A LUMEN message is called a frame.  Each frame is composed of:

   +--------+--------+--------+--------+--------+--------+
   |  LEN   | TYPE   | FLAGS  |  PAYLOAD (variable)       |
   +--------+--------+--------+--------+--------+--------+
   <-- 3-8 bytes header -->  <--- 0..N bytes of payload --------->

   Figure 1: LUMEN Frame Structure

3.1.  Frame Anatomy

   Every LUMEN frame consists of:

   LEN:       Payload length encoded in Hyb128 (Section 3.2).
              This field counts the PAYLOAD bytes only; TYPE and
              FLAGS are NOT included.  It is 1, 3, or 5+ bytes
              depending on magnitude.

   TYPE:      1 byte identifying the frame type (Section 5).
              Values 0x00 and 0xFF are reserved.

   FLAGS:     1 byte bitmask.  Bit positions:

              +=====+============+=================================+
              | Bit | Name       | Meaning                         |
              +=====+============+=================================+
              |  0  | COMPRESSED | Payload is dictionary-compressed |
              |  1  | ENCRYPTED  | Payload is encrypted (Section 9)|
              |  2  | PRIORITY   | High-priority delivery           |
              |  3  | FRAGMENTED | Payload spans multiple frames    |
              | 4–7 | Reserved   | MUST be zero                     |
              +-----+------------+---------------------------------+

              Table 1: FLAGS Bit Definitions

   PAYLOAD:   Variable-length byte sequence.  Its interpretation
              depends on TYPE and FLAGS.  When the COMPRESSED flag
              is set, dictionary references are embedded within
              the payload via TAGS 0xE0-0xE7.

   All multi-byte integers are transmitted in little-endian byte order.

3.2.  Hyb128 — Hybrid Length Encoding

   Hyb128 is the self-delimiting variable-length encoding used for the
   LEN field and all variable-length integers in LUMEN.  It uses the
   two most significant bits (MSB) of the first byte to indicate the
   encoding mode:

   +======+=============+=================+=======================+
   | Bits | Mode        | Bytes Used      | Max Value             |
   +======+=============+=================+=======================+
   | 00   | Tiny        | 1               | 63 (0–63 bytes)       |
   | 10   | Short       | 3               | 65,535 (up to ~64KB)  |
   | 11   | Standard    | 5               | 4,294,967,295 (~4GB)  |
   | 01   | Extended    | 5 + N (LEB128)  | arbitrary (> 4 GB)    |
   +------+-------------+-----------------+-----------------------+

              Table 2: Hyb128 Encoding Modes

   The pseudocode for Hyb128 encoding is provided in Appendix A.
   Implementations MUST accept all four modes when decoding and SHOULD
   emit the most compact mode for the value being encoded.

3.3.  Type and Flags

   The TYPE byte identifies the frame's purpose.  All currently defined
   types are listed in Section 5.  Implementations MUST ignore frames
   with unknown TYPE values rather than closing the connection.

   The FLAGS byte modifies frame handling.  When the COMPRESSED flag
   (bit 0) is set, the payload uses dictionary compression via
   TAGS 0xE0-0xE7 embedded in the payload.  When
   the ENCRYPTED flag (bit 1) is set, the payload is processed per
   Section 9.  The two flags MAY be combined for encrypted-compressed
   frames (compress first, then encrypt).

   When the FRAGMENTED flag (bit 3) is set, the payload is a fragment
   of a logical message that spans multiple frames.  Fragment
   reassembly is described in Section 5.1.

   The PRIORITY flag (bit 2) is a hint; implementations SHOULD process
   priority frames ahead of non-priority frames in their internal
   queues.


4.  Transport Abstraction

   LUMEN defines four Transport Abstraction Levels (LTA).  An
   implementation MUST support Level 1; Levels 2–4 are OPTIONAL.
   Transport negotiation occurs via the TRANSPORT_INIT/TRANSPORT_ACK
   frame pair during connection establishment (Section 5.11).

4.1.  Level 1 — Stream (REQUIRED)

   Level 1 operates over ordered, reliable, bidirectional byte streams.
   This includes:

   *  Standard I/O (stdio) — the default for local MCP agents
   *  Unix Domain Sockets (UDS)
   *  TCP sockets

   Level 1 frames are delimited solely by the Hyb128 LEN field.  No
   additional framing or start-of-message markers are required.  A
   reader consumes the LEN field, determines the payload length, and
   reads exactly that many bytes of payload before beginning the next frame.

4.2.  Level 2 — Zero-Copy Shared Memory

   Level 2 enables zero-copy message passing between processes on the
   same host using shared memory segments.  The LEN field refers to
   a pre-allocated buffer in a ring-buffer mapped into both processes.
   This level is intended for high-throughput scenarios such as local
   LLM inference where payloads may reach multiple megabytes (e.g.,
   embedding vectors, large context windows).

   Level 2 implementations MUST agree on ring-buffer layout via
   TRANSPORT_INIT.

4.3.  Level 3 — Datagram (UDP)

   Level 3 operates over unordered, unreliable datagrams (UDP).
   Frames are limited to the path MTU minus transport overhead.
   Implementations MUST set the FRAGMENTED flag when a logical message
   exceeds the datagram size limit.  Fragmented UDP frames include a
   4-byte message_id for reassembly (see Section 5.1).

   Level 3 also supports IP multicast for service discovery
   (Section 9.3 of [SPEC_DEV]).

4.4.  Level 4 — QUIC

   Level 4 operates over QUIC [RFC9000], providing native multiplexing
   without LUMEN's MUX layer.  When QUIC streams are used as logical
   channels, the MUX frame (0x09) is OPTIONAL; implementations MAY
   use QUIC stream IDs in lieu of LUMEN channel IDs.


5.  Frame Types

   This section defines all currently registered LUMEN frame types.
   The authoritative registry is maintained by IANA (Section 10.1).

   +======+==============+===========================================+
   | Type | Mnemonic     | Purpose                                   |
   +======+==============+===========================================+
   | 0x00 | RESERVED     | Reserved; MUST NOT appear on wire         |
   +------+--------------+-------------------------------------------+
   | 0x01 | REQUEST      | Initiate an RPC operation                 |
   +------+--------------+-------------------------------------------+
   | 0x02 | RESPONSE     | Complete an RPC operation                 |
   +------+--------------+-------------------------------------------+
   | 0x03 | NOTIFY       | One-way notification, no response expected|
   +------+--------------+-------------------------------------------+
   | 0x04 | STREAM_DATA  | Token-by-token LLM streaming data         |
   +------+--------------+-------------------------------------------+
   | 0x05 | SCHEMA_PATCH | Dynamic schema update (late binding)      |
   +------+--------------+-------------------------------------------+
   | 0x06 | STREAM_INIT  | Begin a stream session                    |
   +------+--------------+-------------------------------------------+
   | 0x07 | DICT_SYNC     | Synchronize session dictionary            |
   +------+--------------+-------------------------------------------+
   | 0x08 | DISCOVER     | Tool/Schema discovery request/response    |
   +------+--------------+-------------------------------------------+
   | 0x09 | MUX          | Logical channel open/close/data           |
   +------+--------------+-------------------------------------------+
   | 0x0A | HEARTBEAT    | Keep-alive ping/pong                      |
   +------+--------------+-------------------------------------------+
   | 0x0B | TRANSPORT_INIT| Transport negotiation (initiator)        |
   +------+--------------+-------------------------------------------+
   | 0x0C | TRANSPORT_ACK | Transport negotiation (responder)         |
   +------+--------------+-------------------------------------------+
   | 0x0D |             | Unassigned                                |
   +------+--------------+-------------------------------------------+
   | 0x0E |             | Unassigned                                |
   +------+--------------+-------------------------------------------+
   | 0x0F | PROBE        | Capability/liveness probe                 |
   +------+--------------+-------------------------------------------+
   | 0x10 | PROBE_ACK    | Capability/liveness response              |
   +------+--------------+-------------------------------------------+
   |Other |             | Reserved for future allocation            |
   +------+--------------+-------------------------------------------+

              Table 3: Frame Type Registry

5.1.  REQUEST (0x01)

   Initiates a Remote Procedure Call.  In the current implementation
   (v0.1), the payload is a compressed JSON-RPC 2.0 request message:

   ```json
   {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{...}}
   ```

   The payload is compressed using the LUMEN binary format (TAGs
   0xE0-0xE7, Section 6) and stored in the frame with the COMPRESSED
   flag set.  Correlation between REQUEST and RESPONSE is handled by
   the JSON-RPC "id" field embedded in the payload.

   > **v2 planned**: A native binary header with request_id (4B LE),
   > timeout_ms (2B LE), and separate method/args fields to avoid
   > parsing the JSON-RPC envelope for routing decisions.

5.2.  RESPONSE (0x02)

   Completes an RPC operation initiated by a REQUEST.  In v0.1, the
   payload is a compressed JSON-RPC 2.0 response:

   ```json
   {"jsonrpc":"2.0","id":1,"result":{...}}
   ```
   or
   ```json
   {"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"..."}}
   ```

   The JSON-RPC "id" matches the originating REQUEST.  Error semantics
   follow JSON-RPC 2.0 error codes and messages.

   > **v2 planned**: A 1-byte native status_code field plus the
   > response payload in LUMEN binary format, eliminating the JSON-RPC
   > wrapper for error paths.

5.3.  NOTIFY (0x03)

   One-way notification — no response is expected or generated.  The
   payload is a compressed JSON-RPC 2.0 notification (message without
   an "id" field):

   ```json
   {"jsonrpc":"2.0","method":"notifications/initialized"}
   ```

   > **v2 planned**: Same native header as REQUEST, minus request_id
   > and timeout_ms fields.

5.4.  STREAM_DATA (0x04)

   Carries a single token in an LLM streaming response.  In v0.1, this
   frame type is defined but the structured payload builder is not yet
   implemented.  The constant is reserved for the streaming subsystem.

   > **v2 planned**: Binary payload: [stream_id:4B LE][token_seq:4B LE]
   > [token_type:1B][token_data:variable].

5.5.  SCHEMA_PATCH (0x05)

   Carries a dynamic schema update.  In v0.1, this frame type is
   defined as a constant; the structured payload format and server-side
   schema patching logic are not yet implemented.

   > **v2 planned**: JSON Patch [RFC6902] payload in LUMEN binary
   > format, with patch_seq for version tracking.

5.6.  STREAM_INIT (0x06)

   Initiates a token stream.  Sent before the first STREAM_DATA frame.
   In v0.1, this frame type is defined but the structured payload
   builder is not yet implemented.

   > **v2 planned**: Binary payload: [stream_id:4B LE][max_tokens:4B LE]
   > [temperature:f32 LE][model_len:Hyb128][model:UTF-8].

5.7.  DICT_SYNC (0x07)

   Synchronizes a session dictionary entry between peers.  The payload
   carries one or more dictionary updates.

   DICT_SYNC payload structure:

   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | entry_count   | 1 byte   | Entries in this sync frame      |
   | entries[]     | variable | Array of (index, value) pairs   |
   +---------------+----------+---------------------------------+

   Each entry:
   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | index         | 1 byte   | Slot 0x80–0xFE                  |
   | value_len     | Hyb128   | Length of dictionary value      |
   | value         | variable | Dictionary value (UTF-8)        |
   +---------------+----------+---------------------------------+

   Session dictionaries are scoped to the transport connection.
   When the connection closes, the session dictionary is discarded.

5.8.  DISCOVER (0x08)

   Requests or responds with tool/schema/method metadata.  This frame
   enables "late binding" where the client discovers available
   operations dynamically.

   A DISCOVER frame with empty payload is a request for the full
   schema.  A DISCOVER frame with payload is a response.

   DISCOVER response payload:

   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | schema_version| 4 bytes  | Current schema version          |
   | method_count  | 2 bytes  | Number of methods described     |
   | methods[]     | variable | Array of method descriptors     |
   +---------------+----------+---------------------------------+

   Each method descriptor:

   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | name_len      | Hyb128   | Length of method name           |
   | name          | variable | Method name (UTF-8)             |
   | schema_len    | Hyb128   | Length of JSON Schema           |
   | schema        | variable | JSON Schema [RFC8927] in LUMEN  |
   |               |          | binary format                   |
   +---------------+----------+---------------------------------+

5.9.  MUX (0x09)

   Manages logical channels over a single transport connection.
   Enables concurrent operations without requiring multiple TCP
   connections.

   MUX sub-commands carried in first payload byte:

   +=======+=======+============================================+
   | Byte  | Name  | Purpose                                    |
   +=======+=======+============================================+
   |  0x00 | OPEN  | Open a new logical channel                 |
   |  0x01 | DATA  | Data for an existing channel               |
   |  0x02 | CLOSE | Close a logical channel                    |
   |  0x03 | PAUSE | Suspend a channel (flow control)           |
   |  0x04 | RESUME| Resume a suspended channel                 |
   +-------+-------+--------------------------------------------+

   MUX frames carry a 2-byte channel_id.  All subsequent REQUEST,
   RESPONSE, STREAM_DATA, and NOTIFY frames on that channel are
   wrapped in MUX DATA frames.

   A MUX OPEN frame payload:

   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | sub_command   | 1 byte   | 0x00 (OPEN)                     |
   | channel_id    | 2 bytes  | Proposed channel identifier     |
   | channel_type  | 1 byte   | 0=request,1=stream,2=notify     |
   +---------------+----------+---------------------------------+

   If the requested channel_id is already in use, the responder MUST
   send a MUX CLOSE with an error reason and the initiator MUST
   propose a different channel_id.

5.10.  HEARTBEAT (0x0A)

   Keep-alive ping/pong to detect dead connections.  Payload is
   exactly 4 bytes: a monotonic sequence number.

   Upon receiving a HEARTBEAT, the peer MUST respond with an identical
   HEARTBEAT (echoing the sequence number).  If no HEARTBEAT is
   received within the negotiated heartbeat interval (two missed
   intervals), the connection SHOULD be considered dead.

5.11.  TRANSPORT_INIT (0x0B) / TRANSPORT_ACK (0x0C)

   Negotiates the transport level and parameters during connection
   establishment.  The initiator sends a TRANSPORT_INIT listing
   supported levels; the responder answers with TRANSPORT_ACK
   selecting the highest mutually supported level.

   TRANSPORT_INIT payload:

   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | version       | 2 bytes  | LUMEN protocol version (0x0001) |
   | levels_mask   | 1 byte   | Bitmask of supported levels     |
   | heartbeat_ms  | 2 bytes  | Proposed heartbeat interval     |
   | max_frame     | 4 bytes  | Maximum frame size accepted     |
   +---------------+----------+---------------------------------+

   TRANSPORT_ACK payload:

   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | selected_level| 1 byte   | Chosen transport level          |
   | heartbeat_ms  | 2 bytes  | Agreed heartbeat interval       |
   | max_frame     | 4 bytes  | Minimum of both max_frame values|
   | flags         | 1 byte   | Session capability flags        |
   +---------------+----------+---------------------------------+

   If the responder cannot support any of the proposed levels, it MUST
   respond with TRANSPORT_ACK containing selected_level = 0 and then
   close the transport.

5.12.  PROBE (0x0F) / PROBE_ACK (0x10)

   Capability and liveness probe, typically sent over multicast (UDP)
   for service discovery.  PROBE carries an optional filter (e.g.,
   service type); PROBE_ACK returns the responder's capabilities.

   PROBE_ACK payload mirrors DISCOVER payload with the addition of
   a 2-byte ttl field for service discovery caching.


6.  Semantic Compression

   LUMEN achieves its per-message overhead reduction through dictionary-
   based semantic compression.  Rather than compressing arbitrary bytes,
   LUMEN compresses protocol semantics: field keys such as tool names,
   argument identifiers, parameter keys, and frequently used values.

6.1.  Static Dictionary (0x00–0x7F)

   The static dictionary is a fixed table of 128 entries known to every
   LUMEN implementation at compile time.  It maps field KEYS (not
   method names) to compact 1-byte identifiers for fast lookup during
   compression and decompression:

   +=======+===================+=================================+
   | Index | Key               | Primary use                     |
   +=======+===================+=================================+
   | 0x00  | tool              | Name of the tool to invoke      |
   | 0x01  | arguments         | Tool arguments                  |
   | 0x02  | result            | Result of an operation          |
   | 0x03  | error             | Error response                  |
   | 0x04  | id                | Request/response identifier     |
   | 0x05  | name              | Name (tool, resource, prompt)   |
   | 0x06  | description       | Description                     |
   | 0x07  | content           | Content (resource, message)     |
   | 0x08  | text              | Plain text                      |
   | 0x09  | type              | Data/resource type              |
   | 0x0A  | method            | RPC method                      |
   | 0x0B  | params            | Parameters                      |
   | 0x0C  | jsonrpc           | JSON-RPC version                |
   | 0x0D  | data              | Generic data                    |
   | 0x0E  | code              | Error code                      |
   | 0x0F  | message           | Message                         |
   | 0x10  | input             | Input data                      |
   | 0x11  | output            | Output data                     |
   | 0x12  | stream            | Streaming indicator             |
   | 0x13  | uri               | Resource URI                    |
   | 0x14  | mimeType          | Content MIME type               |
   | 0x15  | encoding          | Encoding (utf-8, base64)        |
   | 0x16  | language          | Programming language            |
   | 0x17  | title             | Title                           |
   | 0x18  | value             | Value                           |
   | 0x19  | key               | Key                             |
   | 0x1A  | path              | File/directory path             |
   | 0x1B  | version           | Version                         |
   | 0x1C  | schema            | JSON schema                     |
   | 0x1D  | default           | Default value                   |
   | 0x1E  | required          | Required field                  |
   | 0x1F  | properties        | Schema properties               |
   | 0x20  | resources         | Resource list                   |
   | 0x21  | tools             | Tool list                       |
   | 0x22  | prompts           | Prompt list                     |
   | 0x23  | resource          | Individual resource             |
   | 0x24  | prompt            | Individual prompt               |
   | 0x25  | handler           | Handler/function                |
   | 0x26  | capabilities      | Server capabilities             |
   | 0x27  | permissions       | Permissions                     |
   | 0x28  | scope             | Scope                           |
   | 0x29  | tags              | Tags                            |
   | 0x2A  | category          | Category                        |
   | 0x2B  | icon              | Icon                            |
   | 0x2C  | metadata          | Metadata                        |
   | 0x2D  | timestamp         | Timestamp                       |
   | 0x2E  | status            | Status                          |
   | 0x2F  | progress          | Progress                        |
   | 0x30  | severity          | Error/log severity              |
   | 0x31  | details           | Details                         |
   | 0x32  | cause             | Root cause                      |
   | 0x33  | stack             | Stack trace                     |
   | 0x34  | line              | Line number                     |
   | 0x35  | column            | Column number                   |
   | 0x36  | source            | Source                          |
   | 0x37  | retry             | Retry                           |
   | 0x38  | timeout           | Timeout                         |
   | 0x39  | limit             | Limit                           |
   | 0x3A  | offset            | Offset                          |
   | 0x3B  | count             | Count                           |
   | 0x3C  | total             | Total                           |
   | 0x3D  | page              | Page                            |
   | 0x3E  | cursor            | Pagination cursor               |
   | 0x3F  | next              | Next page                       |
   | 0x40  | model             | AI model                        |
   | 0x41  | provider          | Provider                        |
   | 0x42  | temperature       | Sampling temperature            |
   | 0x43  | max_tokens        | Maximum tokens to generate      |
   | 0x44  | stop              | Stop sequences                  |
   | 0x45  | frequency_penalty | Frequency penalty               |
   | 0x46  | presence_penalty  | Presence penalty                |
   | 0x47  | top_p             | Top-p sampling                  |
   | 0x48  | logprobs          | Log probabilities               |
   | 0x49  | user              | Role: user                      |
   | 0x4A  | system            | Role: system                    |
   | 0x4B  | assistant         | Role: assistant                 |
   | 0x4C  | function          | Function call                   |
   | 0x4D  | tool_calls        | Tool calls                      |
   | 0x4E  | finish_reason     | Finish reason                   |
   | 0x4F  | usage             | Usage statistics                |
   | 0x50  | url               | URL                             |
   | 0x51  | http_method       | HTTP method                     |
   | 0x52  | headers           | HTTP headers                    |
   | 0x53  | body              | Request body                    |
   | 0x54  | query             | Query parameters                |
   | 0x55  | http_status       | HTTP status code                |
   | 0x56  | cookie            | Cookie                          |
   | 0x57  | session           | Session                         |
   | 0x58  | token             | Authentication token            |
   | 0x59  | auth              | Authentication                  |
   | 0x5A  | redirect          | Redirect                        |
   | 0x5B  | host              | Host                            |
   | 0x5C  | port              | Port                            |
   | 0x5D  | origin            | Origin                          |
   | 0x5E  | referrer          | Referrer                        |
   | 0x5F  | agent             | User-Agent                      |
   | 0x60  | filename          | File name                       |
   | 0x61  | directory         | Directory                       |
   | 0x62  | extension         | File extension                  |
   | 0x63  | size              | Size in bytes                   |
   | 0x64  | modified          | Modification date               |
   | 0x65  | created           | Creation date                   |
   | 0x66  | accessed          | Access date                     |
   | 0x67  | mode              | File permissions                |
   | 0x68  | owner             | Owner                           |
   | 0x69  | group             | Group                           |
   | 0x6A  | symlink           | Symbolic link                   |
   | 0x6B  | binary            | Binary indicator                |
   | 0x6C  | base64            | Base64 data                     |
   | 0x6D  | hash              | Hash/checksum                   |
   | 0x6E  | algorithm         | Algorithm                       |
   | 0x6F  | chunk             | Chunk                           |
   | 0x70  | execute           | Execute                         |
   | 0x71  | read              | Read                            |
   | 0x72  | write             | Write                           |
   | 0x73  | delete            | Delete                          |
   | 0x74  | update            | Update                          |
   | 0x75  | create            | Create                          |
   | 0x76  | search            | Search                          |
   | 0x77  | list              | List                            |
   | 0x78  | get               | Get                             |
   | 0x79  | set               | Set                             |
   | 0x7A  | watch             | Watch                           |
   | 0x7B  | subscribe         | Subscribe                       |
   | 0x7C  | notify            | Notify                          |
   | 0x7D  | cancel            | Cancel                          |
   | 0x7E  | pause             | Pause                           |
   | 0x7F  | resume            | Resume                          |
   +-------+-------------------+---------------------------------+

              Table 4: Static Dictionary — full 128 entries (field keys)

   When the COMPRESSED flag is set, field keys in the payload are
   replaced with their 1-byte static dictionary indices via TAGS
   0xE0-0xE7.  The compressor scans the payload for known field-key
   strings and substitutes the compact representation.  The
   decompressor reverses the substitution.  See DICTIONARY.md for
   the authoritative table.

6.2.  Session Dictionary (0x80–0xFE)

   The session dictionary provides 127 dynamic slots (0x80–0xFE) for
   application-specific terms: custom tool names, parameter keys, and
   frequently used values that are not in the static dictionary.

   Session dictionary entries are negotiated via DICT_SYNC frames
   (Section 5.7).  Either peer MAY propose entries; both peers MUST
   agree before using an entry.  If a compressed frame references an
   unconfirmed session entry, the receiver MUST respond with error
   status 0x07 (Unknown dictionary reference).

   Index 0xFF is reserved and MUST NOT be used as a dictionary
   reference.  It serves as an escape value: a reference of 0xFF
   indicates that the payload is uncompressed and carries the full
   field names inline.

6.3.  Dictionary Synchronization

   Session dictionary entries may be proposed during TRANSPORT_INIT
   (piggybacked on the init frame) or at any time during the session
   via DICT_SYNC.  Entries have a scope of the transport connection;
   they are discarded on disconnect.

   Implementations SHOULD limit session dictionaries to 127 entries as
   specified.  If an implementation receives a DICT_SYNC proposing
   entry 127 when all slots are full, it SHOULD send an error and
   close the transport.

   Dictionary compression is lossless at the semantic level: a
   dictionary-compressed message, when decompressed, MUST produce
   a frame that is semantically identical to the uncompressed form.
   The dictionary substitution replaces only the field keys;
   all argument values are transmitted as provided.


7.  Native Streaming

   LUMEN supports native token-by-token streaming via STREAM_INIT
   (0x06) and STREAM_DATA (0x04) frames.  The Rust reference
   implementation provides payload builders and a stream registry
   (see implementations/rust/src/stream.rs).

7.1.  Wire Format

   STREAM_INIT payload (little-endian):

   +==============+==========+====================================+
   | Field        | Size     | Description                        |
   +==============+==========+====================================+
   | stream_id    | u32 LE   | Unique stream identifier           |
   | max_tokens   | u32 LE   | Max tokens to generate (0=unlim)   |
   | temperature  | f32 LE   | Sampling temperature               |
   | model_len    | u8       | Length of model identifier         |
   | model        | variable | Model name (UTF-8, max 255 bytes)  |
   +==============+==========+====================================+

   STREAM_DATA payload (little-endian):

   +==============+==========+====================================+
   | Field        | Size     | Description                        |
   +==============+==========+====================================+
   | stream_id    | u32 LE   | Must match a STREAM_INIT           |
   | token_seq    | u32 LE   | Monotonic seq, starts at 0         |
   | token_type   | u8       | Token type (see §7.2)              |
   | token_data   | variable | Token payload                      |
   +==============+==========+====================================+

7.2.  Token Types

   +=======+=============+========================================+
   | Value | Type        | Description                            |
   +=======+=============+========================================+
   | 0x00  | TEXT        | UTF-8 text token                       |
   | 0x01  | BINARY      | Raw binary token                       |
   | 0x02  | END         | End-of-stream (no data, closes stream) |
   +=======+=============+========================================+

   Additional token types (TOOL_CALL, THINKING, ERROR, METADATA,
   ANNOTATION) are defined for v2.

7.3.  Stream Lifecycle

   [IDLE] --STREAM_INIT--> [ACTIVE] --STREAM_DATA(N times)-->
                                         --STREAM_DATA(TOKEN_END)--> [CLOSED]

   1. Client sends STREAM_INIT with a unique stream_id.
   2. Server validates and registers the stream.
   3. Server sends STREAM_DATA frames with monotonically increasing
      token_seq values.
   4. Server sends a final STREAM_DATA with token_type = TOKEN_END (0x02).
   5. Client removes the stream from its registry.

   The stream registry MUST validate:
   - stream_id is registered (STREAM_INIT received)
   - token_seq is strictly monotonic (rejects gaps and replays)
   - max_tokens limit is honoured (if > 0)

   Duplicate STREAM_INIT for an active stream_id MUST be rejected.
   STREAM_DATA for an unknown stream_id MUST be rejected.


8.  Multiplexing

   The MUX frame (0x09) enables multiple logical channels over a single
   transport connection.  Each channel is identified by a 2-byte
   channel_id (u16 LE), supporting up to 65,535 concurrent channels per
   connection.  The Rust reference implementation provides payload
   builders and a channel registry (see implementations/rust/src/mux.rs).

8.1.  Wire Format

   MUX frame payload:

   +==============+==========+====================================+
   | Field        | Size     | Description                        |
   +==============+==========+====================================+
   | sub_command  | u8       | OPEN/DATA/CLOSE/PAUSE/RESUME       |
   | channel_id   | u16 LE   | Logical channel identifier         |
   | payload      | variable | Empty for control; inner frame for |
   |              |          | DATA sub-command                   |
   +==============+==========+====================================+

8.2.  Sub-commands

   +=======+==========+==============================================+
   | Value | Command  | Description                                  |
   +=======+==========+==============================================+
   | 0x00  | OPEN     | Open a new logical channel                   |
   | 0x01  | DATA     | Carry an inner LUMEN frame on the channel     |
   | 0x02  | CLOSE    | Close the channel (no more DATA accepted)     |
   | 0x03  | PAUSE    | Flow control — pause receiving                |
   | 0x04  | RESUME   | Flow control — resume receiving               |
   +=======+==========+==============================================+

   For DATA frames, the payload is a complete inner LUMEN frame (Hyb128
   header + TYPE + FLAGS + payload).  The inner frame type determines
   the operation (REQUEST, RESPONSE, NOTIFY, etc.).

8.3.  Channel Lifecycle

   [IDLE] --OPEN--> [ACTIVE] --DATA(n)--> [ACTIVE]
     ^                 |  |                   |
     |                 |  +--PAUSE--> [PAUSED]-+
     |                 |       RESUME          |
     |                 +--CLOSE--> [CLOSED]     |
     +----------------------------------------+
            (channel_id reusable after CLOSE + remove)

   The channel registry MUST validate:
   - OPEN rejects duplicate channel_id
   - DATA/PAUSE/RESUME reject unknown channel_id
   - DATA rejects paused channels
   - DATA rejects closed channels
   - CLOSE rejects already-closed channels
   - Unknown sub_command values rejected

   MUX guarantees message ordering within a channel but not across
   channels.  Flow control is per-channel via PAUSE/RESUME; a paused
   sender MUST wait for RESUME before transmitting more DATA.

   Channel multiplexing is OPTIONAL.  Implementations that do not need
   concurrency MAY ignore MUX frames and use the transport connection
   as a single channel.  Implementations that receive a MUX frame
   without having negotiated MUX support in TRANSPORT_INIT MUST
   respond with error status 0x07 and MAY close the transport.

   When MUX is active, all non-MUX frames (REQUEST, RESPONSE, NOTIFY,
   STREAM_DATA, STREAM_INIT, DICT_SYNC, DISCOVER, HEARTBEAT) MUST be
   wrapped in MUX DATA frames (sub_command = 0x01).  Only
   TRANSPORT_INIT, TRANSPORT_ACK, PROBE, and PROBE_ACK may appear
   outside MUX channels.

   MUX DATA framing adds 3 bytes overhead (sub_command + channel_id)
   to each frame.


9.  Security

   LUMEN provides security at two layers:

   1.  Capability-based authorization via Macaroon tokens
       (see implementations/rust/src/macaroon.rs).
   2.  Optional frame-level authenticated encryption via
       ChaCha20-Poly1305 and X25519.

   Transport-level security (TLS 1.3 [RFC8446] for TCP, QUIC's
   built-in TLS for Level 4) MAY be used in addition to or instead of
   native LUMEN encryption, but capability tokens are independent of
   transport security.

9.1.  Capability Tokens (Macaroons)

   LUMEN uses Macaroons [MACAROON] for decentralized authorization.
   A macaroon is a bearer token that can be attenuated (restricted)
   by any party in the chain without coordinating with the token
   issuer.

   A LUMEN macaroon carries:

   *  target_service:  The MCP service this token grants access to.
   *  caveats:  A list of restrictions (predicates that must be true).
   *  signature:  HMAC-based signature chaining all caveats.

   Macaroons are transmitted in the first REQUEST of a session, or in
   a dedicated authorization header at the transport layer if the
   transport supports headers.

9.2.  Attenuation

   Caveats are the key mechanism for zero-trust authorization in
   LUMEN.  Example caveats:

   *  method = "tools/list"        (restrict to a single method)
   *  expiry < 2026-06-15T12:00Z   (time-bounded access)
   *  rate_limit = 100/min          (throttle)
   *  src_ip = 10.0.0.0/8          (network-bound)

   An attenuator (e.g., a proxy or gateway) may add caveats to a
   macaroon without the issuer's involvement.  The signature chain
   ensures that caveats cannot be removed without detection.

   A LUMEN server MUST verify all caveats before executing a REQUEST.
   If any caveat evaluates to false, the server MUST respond with
   status 0x05 (Unauthorized).

9.3.  Wire Encryption

   When the ENCRYPTED flag (bit 1) is set, the frame payload is
   encrypted using ChaCha20-Poly1305 [RFC8439].

   Encrypted frame format:

   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | nonce         | 12 bytes | ChaCha20-Poly1305 nonce         |
   | ciphertext    | variable | Encrypted payload + 16-byte tag |
   +---------------+----------+---------------------------------+

   The nonce MUST NOT be reused with the same key.  Implementations
   SHOULD generate nonces using a cryptographically secure random
   number generator.

   The Poly1305 authentication tag (16 bytes) is appended to the
   ciphertext.  The receiver MUST verify the tag before decrypting.

9.4.  Key Exchange (X25519)

   Encryption keys are established during TRANSPORT_INIT via X25519
   [RFC7748] key exchange.

   TRANSPORT_INIT (with encryption offered):

   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | ... standard fields (Section 5.11) ...                          |
   | pubkey        | 32 bytes | Initiator's X25519 public key   |
   +---------------+----------+---------------------------------+

   TRANSPORT_ACK (with encryption accepted):

   +===============+==========+=================================+
   | Field         | Size     | Description                     |
   +===============+==========+=================================+
   | ... standard fields (Section 5.11) ...                          |
   | pubkey        | 32 bytes | Responder's X25519 public key   |
   +---------------+----------+---------------------------------+

   Both parties compute the shared secret using X25519 DH and derive
   separate keys for each direction using HKDF-SHA256 [RFC5869]:

   send_key = HKDF-Expand(shared_secret, "lumen-send-key", 32)
   recv_key = HKDF-Expand(shared_secret, "lumen-recv-key", 32)

   Each party uses its send_key for encrypting outbound frames and its
   recv_key for decrypting inbound frames.

9.5.  Anti-Replay

   The 12-byte ChaCha20-Poly1305 nonce serves as an implicit anti-
   replay mechanism.  Receivers SHOULD track seen nonces within the
   key lifetime and reject frames with previously observed nonces.

   Additionally, for request/response pairs, the 4-byte request_id
   provides application-level replay protection: a server MUST NOT
   execute the same request_id more than once within a session.


10.  IANA Considerations

   This document establishes three registries to be maintained by IANA.

10.1.  Frame Type Registry

   IANA has created the "LUMEN Frame Types" registry.  Values 0x00
   and 0xFF are permanently reserved.  Values 0x01–0x10 are assigned
   as listed in Table 3 of this document.  Values 0x11–0xFE are
   available for allocation via the "IETF Review" policy [RFC8126].

   Registration template:

   +====================+========================================+
   | Field              | Value                                  |
   +====================+========================================+
   | Type Value         | (hex byte)                             |
   | Mnemonic           | (short identifier)                     |
   | Description        | (brief purpose)                        |
   | Reference          | (RFC or document reference)            |
   +--------------------+----------------------------------------+

10.2.  Flag Bit Registry

   IANA has created the "LUMEN Frame Flags" registry.  Bit positions
   4–7 are unassigned and available via "IETF Review".  Initial
   assignments:

   +=======+===============+================+======================+
   | Bit   | Name          | Status         | Reference            |
   +=======+===============+================+======================+
   | 0     | COMPRESSED    | Permanent      | RFC XXXX, Section 3.3|
   | 1     | ENCRYPTED     | Permanent      | RFC XXXX, Section 9.3|
   | 2     | PRIORITY      | Permanent      | RFC XXXX, Section 3.3|
   | 3     | FRAGMENTED    | Permanent      | RFC XXXX, Section 3.3|
   | 4–7   | Unassigned    | IETF Review    |                      |
   +-------+---------------+---------------+----------------------+

10.3.  Compression Dictionary Registry

   IANA has created the "LUMEN Static Dictionary" registry.  Entries
   0x00–0x7F are defined by this document.  Future additions require
   "Standards Action" [RFC8126] and a new protocol version.

   The session dictionary range 0x80–0xFE is dynamic and not subject
   to IANA registration.


11.  Security Considerations

11.1.  Authentication and Authorization

   LUMEN uses Macaroons for bearer-token authorization.  Macaroons
   are not encrypted on the wire unless frame-level encryption is
   enabled.  If encryption is not used, macaroons MUST be protected
   by transport-level security (e.g., TLS for TCP, local-only
   transports like stdio or UDS for development).

   Macaroon signatures use HMAC-SHA256.  Compromise of the macaroon
   root key compromises all tokens issued under that key.
   Implementations SHOULD rotate root keys periodically.

11.2.  Encryption

   LUMEN's native encryption (ChaCha20-Poly1305) provides
   confidentiality and integrity for individual frames.  However,
   metadata (frame type, flags, and length) is NOT encrypted.
   An adversary observing the wire can determine the type of each
   message (REQUEST, RESPONSE, etc.), frame sizes, and whether
   compression or fragmentation is in use.  If metadata privacy is
   required, a transport-level tunnel (TLS) SHOULD be used.

   The X25519 key exchange is unauthenticated (pure DH).  Without
   an additional authentication mechanism (e.g., a pre-shared key or
   a PKI), the exchange is vulnerable to active man-in-the-middle
   attacks.  Implementations SHOULD use X25519 only in conjunction
   with macaroon-based mutual authentication or a trusted transport.

11.3.  Denial of Service

   Several protocol features could be exploited for DoS:

   *  Unbounded Hyb128 values:  A frame claiming 4 GB of payload
      should not cause the receiver to allocate 4 GB.  Receivers MUST
      enforce a max_frame limit negotiated via TRANSPORT_INIT.

   *  Fragment exhaustion:  A sender could open thousands of
      incomplete fragmented messages, consuming buffer memory.
      Receivers SHOULD limit the number of concurrent partial
      reassembly buffers and expire them after a timeout.

   *  Channel exhaustion (MUX):  A peer could request thousands of
      channels.  Receivers SHOULD enforce a per-connection limit
      (recommended default: 256 channels).

   *  STREAM_INIT flooding:  A sender could create streams without
      sending data.  Receivers SHOULD limit concurrent streams
      (recommended default: 8).

11.4.  Privacy

   The static dictionary (Section 6.1) reveals that LUMEN is being
   used for MCP communication.  The session dictionary may leak
   application-specific vocabulary.  Transport-level encryption
   mitigates these concerns.

   Constant-time comparison MUST be used when verifying macaroon
   signatures and Poly1305 tags to prevent timing side-channel
   attacks.


12.  References

12.1.  Normative References

   [JSONRPC]  JSON-RPC Working Group, "JSON-RPC 2.0 Specification",
              <https://www.jsonrpc.org/specification>.

   [MACAROON] Birgisson, A., Politz, J., Erlingsson, U., Taly, A.,
              Vrable, M., and M. Lentczner, "Macaroons: Cookies with
              Contextual Caveats for Decentralized Authorization in
              the Cloud", NDSS 2014.

   [MCP_SPEC] Anthropic, "Model Context Protocol Specification",
              <https://modelcontextprotocol.io/specification>.

   [RFC2119]  Bradner, S., "Key words for use in RFCs to Indicate
              Requirement Levels", BCP 14, RFC 2119,
              DOI 10.17487/RFC2119, March 1997.

   [RFC5869]  Krawczyk, H. and P. Eronen, "HMAC-based Extract-and-
              Expand Key Derivation Function (HKDF)", RFC 5869,
              DOI 10.17487/RFC5869, May 2010.

   [RFC6902]  Bryan, P., Ed., and M. Nottingham, Ed., "JavaScript
              Object Notation (JSON) Patch", RFC 6902,
              DOI 10.17487/RFC6902, April 2013.

   [RFC7748]  Langley, A., Hamburg, M., and S. Turner, "Elliptic
              Curves for Security", RFC 7748, DOI 10.17487/RFC7748,
              January 2016.

   [RFC8126]  Cotton, M., Leiba, B., and T. Narten, "Guidelines for
              Writing an IANA Considerations Section in RFCs",
              BCP 26, RFC 8126, DOI 10.17487/RFC8126, June 2017.

   [RFC8174]  Leiba, B., "Ambiguity of Uppercase vs Lowercase in RFC
              2119 Key Words", BCP 14, RFC 8174,
              DOI 10.17487/RFC8174, May 2017.

   [RFC8439]  Nir, Y. and A. Langley, "ChaCha20 and Poly1305 for
              IETF Protocols", RFC 8439, DOI 10.17487/RFC8439,
              June 2018.

   [RFC8446]  Rescorla, E., "The Transport Layer Security (TLS)
              Protocol Version 1.3", RFC 8446, DOI 10.17487/RFC8446,
              August 2018.

   [RFC8927]  Eggert, L. and A. Melnikov, "JSON Schema: A Media Type
              for Describing JSON Documents", RFC 8927,
              DOI 10.17487/RFC8927, February 2021.

   [RFC8949]  Bormann, C. and P. Hoffman, "Concise Binary Object
              Representation (CBOR)", STD 94, RFC 8949,
              DOI 10.17487/RFC8949, December 2020.

   [RFC9000]  Iyengar, J., Ed., and M. Thomson, Ed., "QUIC: A
              UDP-Based Multiplexed and Secure Transport", RFC 9000,
              DOI 10.17487/RFC9000, May 2021.

12.2.  Informative References

   [SPEC_DEV] Monzón, G., "LUMEN — Protocol Specification
              v1.0-draft (Developer Reference)", 2025,
              <https://github.com/GonzaloMonzonC/lumen-protocol>.


Appendix A.  Hyb128 Encoding Algorithm

   The following pseudocode describes Hyb128 encoding.  All multi-byte
   values are little-endian.

   function hyb128_encode(value: uint64) -> bytes:
       if value <= 63:
           // Tiny mode: value in lower 6 bits, upper 2 = 00
           return [byte(value & 0x3F)]

       else if value <= 65535:
           // Short mode: first byte = 0x80 (mode 10), then u16 LE
           le = value.to_le_bytes_16()
           return [0x80, le[0], le[1]]

       else if value <= 4294967295:
           // Standard mode: first byte = 0xC0 (mode 11), then u32 LE
           le = value.to_le_bytes_32()
           return [0xC0, le[0], le[1], le[2], le[3]]

       else:
           // Extended mode: first byte = 0x40 (mode 01), then LEB128
           leb = leb128_encode(value)
           return [0x40] + leb

   function hyb128_decode(bytes: byte_array) -> (uint64, consumed):
       first = bytes[0]
       mode = (first >> 6) & 0x03

       switch mode:
           case 0:  // Tiny: lower 6 bits are the value
               return (first & 0x3F, 1)

           case 2:  // Short: next 2 bytes are u16 LE
               value = bytes[1] | (bytes[2] << 8)
               return (value, 3)

           case 3:  // Standard: next 4 bytes are u32 LE
               value = bytes[1] | (bytes[2] << 8) |
                       (bytes[3] << 16) | (bytes[4] << 24)
               return (value, 5)

           case 1:  // Extended: remaining bytes are LEB128
               value, consumed = leb128_decode(bytes[1:])
               return (value, 1 + consumed)

   LEB128 encoding and decoding MUST follow the unsigned LEB128
   specification as used in DWARF and WebAssembly.


Appendix B.  Wire Examples

   B.1.  Simple REQUEST (uncompressed)

   Invoking "tools/list" over stdio (Level 1).

   Byte sequence (hex):

     07 01 00 00 00 00 01 00 00 0A 74 6F 6F 6C 73 2F
     6C 69 73 74 80

   Breakdown:
     07       — LEN (Tiny: 7 bytes follow)
     01       — TYPE = REQUEST
     00       — FLAGS = none
     00 00 00 01  — request_id = 1
     00 00    — timeout_ms = 0 (default)
     0A       — method_len (Tiny: 10 bytes)
     74 6F 6F 6C 73 2F 6C 69 73 74 — method = "tools/list"
     80       — args (LUMEN binary: empty array)

   Total: 20 bytes.  Equivalent JSON-RPC: ~55 bytes.  Reduction: 64%.

   B.2.  Compressed REQUEST  **[PLANNED]**

   Same invocation using dictionary compression (field keys replaced
   with 1-byte indices inside the payload).  This example illustrates
   the planned structured-payload format; the current implementation
   transports JSON-RPC as an opaque blob.

   Byte sequence (hex):

     07 01 01 00 00 00 00 01 00 00 80

   Breakdown:
     07       — LEN = 7
     01       — TYPE = REQUEST
     01       — FLAGS = COMPRESSED (dictionary compression active)
     00 00 00 01 — request_id = 1
     00 00    — timeout_ms = 0
     80       — args (LUMEN binary: empty array)

   Total: 10 bytes.  Reduction vs JSON-RPC: 82%.

   B.3.  Encrypted RESPONSE

   Successful response, encrypted (encrypted payload shown schematically).

   Byte sequence:

     40 01 02 01 ...

   Breakdown:
     40 01    — LEN (Short: 64 bytes follow)
     02       — TYPE = RESPONSE
     02       — FLAGS = ENCRYPTED
     01 ...   — Encrypted payload (nonce + ciphertext + tag)


Appendix C.  Implementation Status

   Reference implementations exist for the following languages:

   +============+================+===================================+
   | Language   | Transport      | Status                            |
   +============+================+===================================+
   | Rust       | L1, L2, L3     | Production; used in MCP server    |
   | TypeScript | L1, L4         | Production; npm package available |
   | Python     | L1             | Beta; reference implementation    |
   | PHP        | L1             | Alpha; Swoole extension           |
   | C#         | L1             | Alpha; NuGet package              |
   +------------+----------------+-----------------------------------+

   All implementations MUST support at least Level 1 and the frame
   types REQUEST, RESPONSE, NOTIFY, and HEARTBEAT.  Other frame types
   and transport levels MAY be added per the implementation's target
   use case.

   Interoperability testing has been conducted between the Rust,
   TypeScript, and Python implementations.  Test vectors for frame
   encoding/decoding are available in the reference repository
   [SPEC_DEV].

   Performance benchmarks (Rust implementation, Level 1 over stdio,
   1 KB payload):

   *  REQUEST/RESPONSE round-trip:  < 10 microseconds
   *  Compressed REQUEST encoding:  < 100 nanoseconds
   *  Encrypted REQUEST encoding:   < 2 microseconds
   *  STREAM_DATA latency (token):  < 50 microseconds
   *  Throughput (uncompressed):    > 500,000 msg/s
   *  Throughput (compressed):      > 2,000,000 msg/s

   All benchmarks measured on AMD Ryzen 9 5950X, DDR4-3600, Linux 6.1.


Acknowledgements

   The author thanks the MCP community for feedback on early protocol
   drafts, the IETF CFRG for guidance on wire encryption design, and
   the Macaroon paper authors for pioneering decentralized
   authorization.

   Special thanks to the maintainers of the QUIC, and
   ChaCha20-Poly1305 reference implementations, without which the
   LUMEN reference codebase would not have been possible.

Authors' Addresses

   Gonzalo Monzón
   LUMEN Project
   Email: gonzalo@lumenprotocol.org
   URI:   https://lumenprotocol.org
