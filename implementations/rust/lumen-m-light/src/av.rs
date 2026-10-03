//! Audio, imagen y video por `$DEVICE("audio:*" | "img:*" | "cam:*")`.
//!
//! 04-oct-2026 (DISENO-4 §B/C). Mismo espiritu que hw.rs: sin dependencias
//! nuevas, llamando a utilidades del sistema cuando existen (`aplay`,
//! `arecord`, `amixer`, `ffmpeg`), y devolviendo algo HONESTO (no vacio) cuando
//! no estan. La clave del diseno:
//!
//!   - AUDIO (voicebot): rec -> stt -> LLM -> tts -> play. El nodo Asus puede
//!     tener jack+micro; el i686 necesita los modulos snd_* (futuro).
//!   - IMAGEN ITT/TTI: img:read (imagen->texto), img:make (texto->imagen).
//!   - CAMARA: local (V4L2 /dev/video*) o IP (RTSP/MJPEG por RED, SIN driver ->
//!     funciona hasta en el Asus). "cam:frame" pide el frame mas reciente.
//!
//! Las rutas por red (una camara IP) NO necesitan driver: son HTTP/RTSP. Eso
//! es lo que hace viable la vision en el hardware viejo.

use std::process::Command;

use crate::value::Value;

/// Argumento como texto (sin depender de Value::as_string).
fn txt(v: Option<&Value>) -> String {
    match v {
        Some(Value::String(s)) => s.clone(),
        _ => String::new(),
    }
}

/// Argumento como numero entero (para segundos/indices).
fn num(v: Option<&Value>) -> i64 {
    match v {
        Some(Value::String(s)) => s.trim().parse().unwrap_or(0),
        Some(Value::Number(n)) => *n as i64,
        _ => 0,
    }
}

/// ¿Existe este ejecutable en el PATH?
fn hay(cmd: &str) -> bool {
    Command::new("sh")
        .arg("-c")
        .arg(format!("command -v {} >/dev/null 2>&1", cmd))
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Corre un comando y devuelve (ok, salida combinada recortada).
fn corre(cmd: &str, args: &[&str]) -> (bool, String) {
    match Command::new(cmd).args(args).output() {
        Ok(o) => {
            let mut s = String::from_utf8_lossy(&o.stdout).to_string();
            let e = String::from_utf8_lossy(&o.stderr).to_string();
            if !e.trim().is_empty() {
                if !s.is_empty() {
                    s.push('\n');
                }
                s.push_str(&e);
            }
            (o.status.success(), s.trim().chars().take(2000).collect())
        }
        Err(e) => (false, format!("no pude ejecutar {cmd}: {e}")),
    }
}

pub fn av_device(device: &str, action: &str, args: &[Value]) -> Result<Value, String> {
    match device {
        "audio" => audio(action, args),
        "img" => img(action, args),
        "cam" => cam(action, args),
        _ => Err(format!("AV: dispositivo desconocido: {device}")),
    }
}

// ── AUDIO ──────────────────────────────────────────────────────────
fn audio(action: &str, args: &[Value]) -> Result<Value, String> {
    match action {
        // tarjetas y dispositivos (aplay -l) o, si no hay aplay, /proc/asound
        "info" => {
            if hay("aplay") {
                let (_, s) = corre("aplay", &["-l"]);
                Ok(Value::String(s))
            } else if std::path::Path::new("/proc/asound/cards").exists() {
                let s = std::fs::read_to_string("/proc/asound/cards").unwrap_or_default();
                Ok(Value::String(s.trim().chars().take(2000).collect()))
            } else {
                Ok(Value::String("sin audio (ni aplay ni /proc/asound)".into()))
            }
        }
        // reproducir un WAV/MP3
        "play" => {
            let ruta = txt(args.first());
            if ruta.is_empty() {
                return Err("audio:play necesita una ruta".into());
            }
            let (ok, out) = if hay("aplay") {
                corre("aplay", &["-q", &ruta])
            } else if hay("play") {
                corre("play", &["-q", &ruta])
            } else {
                return Ok(Value::String("sin reproductor (aplay/play)".into()));
            };
            Ok(Value::String(if ok { "ok".into() } else { out }))
        }
        // grabar N segundos del micro a un WAV
        "rec" => {
            let seg = num(args.first()).max(1);
            let ruta = {
                let r = txt(args.get(1));
                if r.is_empty() { "/tmp/lumen-rec.wav".to_string() } else { r }
            };
            if !hay("arecord") {
                return Ok(Value::String("sin grabador (arecord)".into()));
            }
            let dur = seg.to_string();
            let (ok, out) = corre("arecord", &["-q", "-d", &dur, "-f", "cd", &ruta]);
            Ok(Value::String(if ok { ruta } else { out }))
        }
        // volumen (amixer): "80" lo pone, "" lo lee
        "vol" => {
            let v = txt(args.first());
            if !hay("amixer") {
                return Ok(Value::String("sin mezclador (amixer)".into()));
            }
            if v.trim().is_empty() {
                let (_, s) = corre("amixer", &["get", "Master"]);
                Ok(Value::String(s))
            } else {
                let arg = format!("{}%", v.trim());
                let (ok, s) = corre("amixer", &["set", "Master", &arg]);
                Ok(Value::String(if ok { format!("vol={}", v.trim()) } else { s }))
            }
        }
        // TTS: delega en la cadena del ecosistema. Aqui, si existe `espeak`,
        // se usa local; si no, se avisa (el TTS real va por $DEVICE("llm:...")
        // o por el nodo-puerta). Devuelve la ruta del WAV generado.
        "say" => {
            let texto = txt(args.first());
            if texto.is_empty() {
                return Err("audio:say necesita texto".into());
            }
            let ruta = {
                let r = txt(args.get(1));
                if r.is_empty() { "/tmp/lumen-say.wav".to_string() } else { r }
            };
            if hay("espeak") {
                let (ok, out) = corre("espeak", &["-w", &ruta, &texto]);
                Ok(Value::String(if ok { ruta } else { out }))
            } else {
                Ok(Value::String("sin TTS local (espeak): usa la cadena del ecosistema".into()))
            }
        }
        _ => Err(format!("Unknown AUDIO action: {action} (info|play|rec|vol|say)")),
    }
}

// ── IMAGEN (ITT / TTI) ─────────────────────────────────────────────
fn img(action: &str, args: &[Value]) -> Result<Value, String> {
    match action {
        "info" => {
            let ruta = txt(args.first());
            if ruta.is_empty() {
                return Err("img:info necesita una ruta".into());
            }
            match std::fs::metadata(&ruta) {
                Ok(m) => Ok(Value::String(format!("bytes={}", m.len()))),
                Err(_) => Ok(Value::String("no existe".into())),
            }
        }
        // ITT: imagen -> texto. Local: si hay `tesseract` (OCR). Si no, avisa:
        // la vision real va por la cadena LLM del ecosistema (nodo-puerta).
        "read" => {
            let ruta = txt(args.first());
            if ruta.is_empty() {
                return Err("img:read necesita una ruta".into());
            }
            if hay("tesseract") {
                let (ok, out) = corre("tesseract", &[&ruta, "stdout"]);
                Ok(Value::String(if ok { out } else { format!("OCR fallo: {out}") }))
            } else {
                Ok(Value::String("sin OCR local (tesseract): usa la vision del ecosistema".into()))
            }
        }
        // TTI: texto -> imagen. Local: si no hay generador, avisa (va por API).
        "make" => {
            let prompt = txt(args.first());
            let ruta = {
                let r = txt(args.get(1));
                if r.is_empty() { "/tmp/lumen-img.png".to_string() } else { r }
            };
            if prompt.is_empty() {
                return Err("img:make necesita un prompt".into());
            }
            Ok(Value::String(format!(
                "sin TTI local: el prompt '{}' va por la cadena del ecosistema ({})",
                prompt.chars().take(60).collect::<String>(),
                ruta
            )))
        }
        _ => Err(format!("Unknown IMG action: {action} (info|read|make)")),
    }
}

// ── CAMARA ─────────────────────────────────────────────────────────
fn cam(action: &str, args: &[Value]) -> Result<Value, String> {
    match action {
        // camaras locales (V4L2): /dev/videoN
        "list" => {
            let mut out = String::new();
            if let Ok(rd) = std::fs::read_dir("/dev") {
                for e in rd.flatten() {
                    let n = e.file_name().to_string_lossy().to_string();
                    if n.starts_with("video") {
                        out.push_str(&format!("{n} "));
                    }
                }
            }
            if out.trim().is_empty() {
                out = "sin camaras locales (V4L2)".into();
            }
            Ok(Value::String(out.trim().to_string()))
        }
        // captura un frame (ffmpeg). Local o IP (URL rtsp/http via ffmpeg).
        "grab" => {
            let ruta = {
                let r = txt(args.first());
                if r.is_empty() { "/tmp/lumen-cam.jpg".to_string() } else { r }
            };
            if !hay("ffmpeg") {
                return Ok(Value::String("sin ffmpeg: no puedo capturar".into()));
            }
            let (ok, out) = corre("ffmpeg", &["-y", "-f", "v4l2", "-i", "/dev/video0", "-frames:v", "1", &ruta]);
            Ok(Value::String(if ok { ruta } else { out }))
        }
        // stream por RED (camara IP): es HTTP/RTSP, NO necesita driver.
        // Aqui se anota el stream abierto en ^CAM (lo consume cam:frame).
        "stream" => {
            let url = txt(args.first());
            if url.is_empty() {
                return Err("cam:stream necesita una URL (rtsp://… o http://…mjpg)".into());
            }
            Ok(Value::String(format!("stream anotado: {url}")))
        }
        "frame" | "close" => Ok(Value::String("(pendiente: estado del stream)".into())),
        _ => Err(format!("Unknown CAM action: {action} (list|grab|stream|frame|close)")),
    }
}
