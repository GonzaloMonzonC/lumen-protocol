//! Las 24 funciones de `$ZNET` de MSM.
//!
//! ANTES: este crate implementaba 6 funciones (8, 9, 17, 22, 30, 31) porque solo
//! miraba las rutinas ya extraidas de `DATABASE.MSM`, que es un subconjunto.
//!
//! Buscando en el binario crudo de todos los volumenes aparecen 24. Cada una es una
//! OPERACION DISTINTA de red, no un parametro de la misma funcion.
//!
//! Fuente: `DATABASE.MSM` y `utils.msm` (binario crudo), 25/10/2026.

// --- Recepcion -------------------------------------------------------------

/// `M=$ZNET(8)` — recv BLOQUEANTE del enlace (espera 4 decisegundos en `DDPSRV`).
pub const RECV: u8 = 8;
/// `M=$ZNET(31)` — recv de la cola de circuitos.
pub const RECV_CIRCUIT: u8 = 31;
/// `A=$ZNET(41)` — recv de LAT (link down).
pub const RECV_LAT: u8 = 41;

// --- Respuesta / envio -----------------------------------------------------

/// `Z=$ZNET(9,x)` — responder: `"S"`, `"F"`, `""` o binario.
pub const REPLY: u8 = 9;
/// `A=$ZNET(11,$ZCHAR(CMD))` — broadcast a TODOS los links online.
pub const BROADCAST: u8 = 11;
/// `A=$ZNET(12,$ZCHAR(CMD))` — comando a un circuito concreto.
pub const SEND_CIRCUIT: u8 = 12;
/// `A=$ZNET(13)` — recoge de la cola de un circuito.
pub const RECV_CIRCUIT_Q: u8 = 13;
/// `A=$ZNET(40,MSG)` — envia anuncio LAT.
pub const SEND_LAT: u8 = 40;
/// `Z=$ZNET(10,$ZCHAR(n))` — control de protocolo / errores.
pub const CONTROL: u8 = 10;

// --- Gestion de circuitos --------------------------------------------------

/// `$ZNET(22,M)` — crear circuito hacia un destino.
pub const CREATE_CIRCUIT: u8 = 22;
/// `$ZNET(19,$ZCHAR(89,1))` — aceptar o rechazar un circuito (`'Y'` = 89).
pub const ACCEPT_CIRCUIT: u8 = 19;
/// `ECIR=$ZNET(27)` — recoge el circuito aceptado.
pub const ACCEPTED_CIRCUIT: u8 = 27;
/// `X=$ZNET(25,M)` — enumerar circuitos (recorre los LCBs).
pub const ENUM_CIRCUITS: u8 = 25;
/// `XX=$ZNET(26,X)` — flush + update DDP al desmontar.
pub const FLUSH_DDP: u8 = 26;

// --- Gestion de enlaces ----------------------------------------------------

/// `X=$ZNET(17)` — inicializa el subsistema de red.
pub const INIT: u8 = 17;
/// `Z=$ZNET(30)` — inicializa un enlace.
pub const INIT_LINK: u8 = 30;
/// `X=$ZNET(14)` — estado del link / arranque.
pub const LINK_STATE: u8 = 14;
/// `X=$ZNET(15)` — deshabilita un link.
pub const LINK_DISABLE: u8 = 15;
/// `XX=$ZNET(18)` — info del link (flags, direccion).
pub const LINK_INFO: u8 = 18;
/// `errcode=$ZNET(32,"")` — inicializa el socket TCP/IP.
pub const INIT_SOCKET: u8 = 32;
/// `Z=$ZNET(16)` — para el servidor DDP.
pub const STOP_SERVERS: u8 = 16;

// --- Comando remoto --------------------------------------------------------

/// `X=$ZNET(24,cmd)` — ejecuta un comando MUMPS en otro contexto.
pub const EXEC_REMOTE: u8 = 24;

/// Codigos de `$ZNET(10)`, documentados en el propio codigo de MSM.
pub mod control {
    /// Password incorrecto: `S Z=$ZNET(10,$ZCHAR(1))`.
    pub const PASSWORD_ERROR: u8 = 1;
    /// Datos demasiado largos: `I X>255 S Z=$ZNET(10,$ZCHAR(21))`.
    pub const DATA_TOO_LONG: u8 = 21;
}

/// Valores de `CMD` que circulan por `ALLINKS` hacia `$ZNET(11)`.
pub mod cmd {
    /// `D ALLINKS^DDPSRV(80)` — arranque.
    pub const START: u8 = 80;
    /// `D ALLINKS^DDPSRV(82)` — parada.
    pub const SHUTDOWN: u8 = 82;
    /// `D ALLINKS^DDPSRV(92)` — opcion 3 del menu, actualizar tabla de circuitos.
    pub const UPDATE_CIRCUITS: u8 = 92;
}

/// Lee un `u16` little-endian de `datos` en el offset dado (base 0).
pub fn lee_u16_le(datos: &[u8], off: usize) -> u16 {
    (datos[off] as u16) | ((datos[off + 1] as u16) << 8)
}

/// Los cuatro numeros de cabecera que MSM documenta en los comentarios de `$ZNET(10)`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CamposDocumentados {
    /// `$ZAS(M,4)*256+$ZAS(M,3)` — longitud de datos.
    pub longitud_datos: u16,
    /// `$ZAS(M,6)*256+$ZAS(M,5)`.
    pub num2: u16,
    /// `$ZAS(M,8)*256+$ZAS(M,7)` — primera parte del subindice.
    pub subindice_1: u16,
    /// `$ZAS(M,10)*256+$ZAS(M,9)` — segunda parte del subindice.
    pub subindice_2: u16,
}

/// Extrae los campos que MSM documenta en los comentarios de `$ZNET(10)`.
///
/// Los offsets vienen de `$ZAS`, que es 1-indexado en MUMPS: `$ZAS(M,3)` es el
/// byte 3, o sea el offset 2 en base 0.
pub fn campos_documentados(m: &[u8]) -> Option<CamposDocumentados> {
    if m.len() < 10 {
        return None;
    }
    Some(CamposDocumentados {
        longitud_datos: lee_u16_le(m, 2),
        num2: lee_u16_le(m, 4),
        subindice_1: lee_u16_le(m, 6),
        subindice_2: lee_u16_le(m, 8),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn los_campos_documentados_se_leen_little_endian() {
        // Construir un mensaje con los valores que MSM esperaria.
        let mut m = vec![0u8; 12];
        m[0] = 0x03; // tipo
        // longitud de datos = 0x0140 (320) -> $ZAS(M,3)=0x40, $ZAS(M,4)=0x01
        m[2] = 0x40;
        m[3] = 0x01;
        // num2 = 7
        m[4] = 0x07;
        m[5] = 0x00;
        // subindice_1 = 0x1234
        m[6] = 0x34;
        m[7] = 0x12;
        // subindice_2 = 0x00FF
        m[8] = 0xFF;
        m[9] = 0x00;

        let c = campos_documentados(&m).unwrap();
        assert_eq!(c.longitud_datos, 320);
        assert_eq!(c.num2, 7);
        assert_eq!(c.subindice_1, 0x1234);
        assert_eq!(c.subindice_2, 0x00FF);
    }

    #[test]
    fn mensaje_corto_no_tiene_campos() {
        assert!(campos_documentados(&[1, 2, 3]).is_none());
    }

    #[test]
    fn los_comandos_de_allinks_son_los_del_codigo() {
        // ALLINKS^DDPSRV(80) en START, (82) en STOP, (92) en UPDATE.
        assert_eq!(cmd::START, 80);
        assert_eq!(cmd::SHUTDOWN, 82);
        assert_eq!(cmd::UPDATE_CIRCUITS, 92);
    }

    #[test]
    fn los_codigos_de_control_son_los_del_codigo() {
        // $ZNET(10,$ZCHAR(1)) = password, $ZNET(10,$ZCHAR(21)) = datos largos
        assert_eq!(control::PASSWORD_ERROR, 1);
        assert_eq!(control::DATA_TOO_LONG, 21);
    }
}
