//! subkey.rs — puerto 1:1 de encode_subkey/decode_subkey de pdb_tools.py.
//!
//! La codificación orden-preservante es LA pieza portable del proyecto:
//! cualquier divergencia rompe la interoperabilidad de BDs entre motores.
//! Verificada byte a byte contra Python con tests/golden_subkey.json.
//!
//! Formato por subscript:
//!   0x00                          → sentinel NULL (legacy, solo último)
//!   0x01 + 8B double sortable + 0xFF → numérico
//!   0x02 + UTF-8 + 0xFF           → string
//!   0x02 0xFF                     → string vacía ""
//!
//! Doubles sortable (totalOrder por memcmp): big-endian; negativo → flip
//! de todos los bits; positivo → flip solo del bit de signo.
//!
//! Quirks de colación fijados por el golden (¡son producto, no bugs!):
//!   - números ordenan antes que strings (0x01 < 0x02)
//!   - una string PREFIJO de otra ordena DESPUÉS de ella ("ab" < "a",
//!     porque el terminador 0xFF supera cualquier byte de continuación)
//!   - "" es la MAYOR de las strings (0x02 0xFF)

/// Un subscript M: número, string o el sentinel NULL legacy.
#[derive(Debug, Clone, PartialEq)]
pub enum Sub {
    Num(f64),
    Str(String),
    Null,
}

/// IEEE 754 double → 8 bytes ordenables por memcmp.
pub fn double_to_sortable(value: f64) -> [u8; 8] {
    let raw = value.to_be_bytes();
    if raw[0] & 0x80 != 0 {
        // negativo: flip de todos los bits
        let mut out = [0u8; 8];
        for (i, b) in raw.iter().enumerate() {
            out[i] = b ^ 0xFF;
        }
        out
    } else {
        // positivo: flip solo del bit de signo
        let mut out = raw;
        out[0] ^= 0x80;
        out
    }
}

/// Inversa: 8 bytes sortable → double.
pub fn sortable_to_double(data: &[u8; 8]) -> f64 {
    let raw: [u8; 8] = if data[0] & 0x80 != 0 {
        // el original era positivo
        let mut out = *data;
        out[0] ^= 0x80;
        out
    } else {
        // el original era negativo
        let mut out = [0u8; 8];
        for (i, b) in data.iter().enumerate() {
            out[i] = b ^ 0xFF;
        }
        out
    };
    f64::from_be_bytes(raw)
}

/// Codifica una lista de subscripts en un BLOB ordenable.
pub fn encode_subkey(subs: &[Sub]) -> Vec<u8> {
    let mut out = Vec::new();
    for sub in subs {
        match sub {
            Sub::Null => out.push(0x00),
            Sub::Str(s) if s.is_empty() => {
                out.push(0x02);
                out.push(0xFF);
            }
            Sub::Num(n) => {
                out.push(0x01);
                out.extend_from_slice(&double_to_sortable(*n));
                out.push(0xFF);
            }
            Sub::Str(s) => {
                out.push(0x02);
                out.extend_from_slice(s.as_bytes());
                out.push(0xFF);
            }
        }
    }
    out
}

/// Decodifica un BLOB subkey completo a la lista de subscripts.
pub fn decode_subkey(blob: &[u8]) -> Vec<Sub> {
    let mut subs = Vec::new();
    let mut i = 0usize;
    while i < blob.len() {
        let typ = blob[i];
        i += 1;
        match typ {
            0x00 => {
                subs.push(Sub::Null);
                break; // el sentinel siempre es el último
            }
            0x01 => {
                if i + 8 > blob.len() {
                    break;
                }
                let mut d = [0u8; 8];
                d.copy_from_slice(&blob[i..i + 8]);
                i += 8;
                subs.push(Sub::Num(sortable_to_double(&d)));
                if i < blob.len() && blob[i] == 0xFF {
                    i += 1; // separador
                }
            }
            0x02 => {
                match blob[i..].iter().position(|&b| b == 0xFF) {
                    Some(0) => {
                        subs.push(Sub::Str(String::new())); // \x02\xFF = ""
                        i += 1;
                    }
                    Some(off) => {
                        let end = i + off;
                        let s = String::from_utf8_lossy(&blob[i..end]).into_owned();
                        subs.push(Sub::Str(s));
                        i = end + 1; // saltar separador
                    }
                    None => {
                        let s = String::from_utf8_lossy(&blob[i..]).into_owned();
                        subs.push(Sub::Str(s));
                        i = blob.len();
                    }
                }
            }
            _ => break, // tipo desconocido: parar (igual que Python implícitamente)
        }
    }
    subs
}

/// Extrae el segmento codificado de UN subscript empezando en `offset`.
/// Devuelve el rango [offset, fin) del segmento, o None si está mal formado.
pub fn segment_at(blob: &[u8], offset: usize) -> Option<std::ops::Range<usize>> {
    if offset >= blob.len() {
        return None;
    }
    match blob[offset] {
        0x00 => Some(offset..offset + 1),
        0x01 => {
            let end = offset + 1 + 8 + 1; // tipo + double + 0xFF
            if end <= blob.len() {
                Some(offset..end)
            } else {
                None
            }
        }
        0x02 => blob[offset + 1..]
            .iter()
            .position(|&b| b == 0xFF)
            .map(|off| offset..offset + 1 + off + 1),
        _ => None,
    }
}
