//! Servidor MCP NATIVO del MVM — `mcp:serve`.
//!
//! Hasta ahora el MVM era solo CLIENTE MCP (`$DEVICE("mcp:call",…)`): sabía
//! consumir servidores MCP ajenos, pero no exponerse como uno. Este módulo cierra
//! el otro lado: cualquier cliente MCP (Claude Desktop, LangChain, otro agente)
//! puede llamar a las rutinas M de este nodo.
//!
//! # Por qué NO es un `$DEVICE`
//!
//! `Vm::new(program, &mut host)` toma el host PRESTADO durante toda la
//! ejecución. Un device corre *dentro* de ese préstamo, así que no puede crear
//! otro VM sobre el mismo host (sería re-entrante y el borrow checker lo impide).
//! Por eso el servidor vive FUERA del VM: es un bucle que, por cada petición,
//! hace lo mismo que el ffi — bloquear el host, montar un VM, ejecutar.
//!
//! # Protocolo
//!
//! JSON-RPC 2.0 sobre HTTP (una petición por POST, respuesta JSON). Métodos:
//!
//! | método            | qué hace                                      |
//! |-------------------|-----------------------------------------------|
//! | `initialize`      | handshake; devuelve capabilities + serverInfo |
//! | `tools/list`      | catálogo desde `^TOOLS`                       |
//! | `tools/call`      | ejecuta la rutina M de la tool                |
//! | `ping`            | liveness                                      |
//!
//! # Cómo se declara una tool
//!
//! En la PDB (`^TOOLS`), igual que el catálogo que ya usa el motor:
//!
//! ```text
//! ^TOOLS("__names")            = "saludar,contar"
//! ^TOOLS("saludar","desc")     = "Saluda a alguien por su nombre"
//! ^TOOLS("saludar","kind")     = "m:%SALUDAR"
//! ^TOOLS("saludar","params")   = {"type":"object","properties":{...},...}
//! ```
//!
//! Al llamar `tools/call` con `{"name":"saludar","arguments":{"quien":"Ana"}}`,
//! el servidor escribe cada argumento en `^MCPARGS("<clave>")`, llama a la
//! rutina `%SALUDAR` y devuelve su salida como `content[0].text`.
//! La rutina lee `^MCPARGS` como cualquier global.

#![cfg(not(target_arch = "wasm32"))]

use crate::compiler::Compiler;
use crate::host::{GlobalEntry, Host, MemoryHost};
use crate::mcp_auth::{self, AuthMode};
use crate::value::{Subscript, Value};
use crate::vm::{Execution, Vm};
use serde_json::{json, Value as Json};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};

/// Configuración del servidor.
#[derive(Clone, Debug)]
pub struct ServeConfig {
    pub host_addr: String,
    pub port: u16,
    /// Timeout por petición, en segundos. Una rutina colgada no bloquea para
    /// siempre al cliente (se corta la conexión y se devuelve error).
    pub timeout_secs: u64,
    pub server_name: String,
    pub server_version: String,
    /// Clave HMAC del ecosistema. Vacía = modo lectura (solo loopback).
    pub hmac_key: String,
}

impl Default for ServeConfig {
    fn default() -> Self {
        Self {
            host_addr: "127.0.0.1".to_string(),
            port: 8790,
            timeout_secs: 30,
            server_name: "lumen-mvm".to_string(),
            server_version: env!("CARGO_PKG_VERSION").to_string(),
            hmac_key: String::new(),
        }
    }
}

/// Arranca el servidor y BLOQUEA hasta que el proceso muera.
///
/// `entries` es el estado inicial de la PDB (se clona en cada petición, así cada
/// llamada ve el mismo punto de partida y los cambios se persisten al final).
pub fn serve(config: ServeConfig, entries: Vec<GlobalEntry>) -> std::io::Result<()> {
    let mode = AuthMode::from_key(&config.hmac_key);
    // En modo lectura se fuerza loopback aunque se haya pedido 0.0.0.0: sin
    // clave, el servidor no debe ser alcanzable desde la red.
    let bind_host = mode.effective_bind(&config.host_addr);
    let addr = format!("{}:{}", bind_host, config.port);
    let listener = TcpListener::bind(&addr)?;
    // Estado compartido: la PDB vive aquí y sobrevive entre peticiones.
    let state: Arc<Mutex<Vec<GlobalEntry>>> = Arc::new(Mutex::new(entries));

    match mode {
        AuthMode::Signed => eprintln!(
            "[mcp:serve] escuchando en http://{}  (HMAC obligatorio · escritura permitida)",
            addr
        ),
        AuthMode::ReadOnlyLocal => {
            eprintln!(
                "[mcp:serve] escuchando en http://{}  (SIN clave: solo lectura, solo loopback)",
                addr
            );
            if bind_host != config.host_addr {
                eprintln!(
                    "[mcp:serve] aviso: se pidio {}, forzado 127.0.0.1 por no haber clave",
                    config.host_addr
                );
            }
        }
    }

    for stream in listener.incoming() {
        let mut stream = match stream {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[mcp:serve] conexion rechazada: {e}");
                continue;
            }
        };
        // Defensa en profundidad: aunque el bind sea loopback, se rechaza
        // cualquier origen no local en modo lectura.
        if mode == AuthMode::ReadOnlyLocal {
            if let Ok(peer) = stream.peer_addr() {
                if !mcp_auth::is_loopback(&peer.ip()) {
                    eprintln!("[mcp:serve] rechazado origen no local {}", peer.ip());
                    let _ = write_json(&mut stream, 403, &json!({
                        "error": "sin clave configurada: solo acceso local"
                    }));
                    continue;
                }
            }
        }
        // Un cliente por conexión, secuencial: el MVM no es thread-safe por
        // diseño (host único) y serializar evita carreras sobre la PDB.
        let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(
            config.timeout_secs.max(1),
        )));
        if let Err(e) = handle_connection(&mut stream, &config, &mode, &state) {
            eprintln!("[mcp:serve] error atendiendo conexion: {e}");
        }
    }
    Ok(())
}

/// Lee una petición HTTP, la procesa y escribe la respuesta.
fn handle_connection(
    stream: &mut TcpStream,
    config: &ServeConfig,
    mode: &AuthMode,
    state: &Arc<Mutex<Vec<GlobalEntry>>>,
) -> std::io::Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);

    // ── Línea de petición: "POST /mcp HTTP/1.1" ──
    let mut request_line = String::new();
    if reader.read_line(&mut request_line)? == 0 {
        return Ok(()); // conexión vacía (health probe)
    }
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("").to_string();
    let path = parts.next().unwrap_or("/").to_string();

    // ── Cabeceras ──
    let mut content_length = 0usize;
    let mut headers: Vec<(String, String)> = Vec::new();
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            break;
        }
        let t = line.trim_end();
        if t.is_empty() {
            break;
        }
        if let Some((k, v)) = t.split_once(':') {
            let (k, v) = (k.trim().to_string(), v.trim().to_string());
            if k.eq_ignore_ascii_case("content-length") {
                content_length = v.parse().unwrap_or(0);
            }
            headers.push((k, v));
        }
    }

    // ── GET /health: sonda barata para saber si el nodo está vivo ──
    if method == "GET" && (path == "/health" || path == "/") {
        return write_json(stream, 200, &json!({
            "ok": true, "name": config.server_name, "version": config.server_version,
            "protocol": "mcp", "transport": "http"
        }));
    }
    if method != "POST" {
        return write_json(stream, 405, &json!({"error": "solo POST /mcp"}));
    }

    // ── Cuerpo ──
    let mut body = vec![0u8; content_length];
    if content_length > 0 {
        reader.read_exact(&mut body)?;
    }
    let raw_body = String::from_utf8_lossy(&body).to_string();

    // ── Gate HMAC: con clave configurada, TODA petición POST debe ir firmada ──
    // Se firma sobre el cuerpo CRUDO recibido, no sobre un JSON reserializado
    // (reserializar cambia espacios y rompe la verificación).
    if *mode == AuthMode::Signed {
        if let Err(why) = mcp_auth::verify(&headers, &raw_body, &config.hmac_key) {
            eprintln!("[mcp:serve] 401 {why}");
            return write_json(stream, 401, &json!({
                "jsonrpc": "2.0", "id": Json::Null,
                "error": {"code": -32001, "message": format!("HMAC_INVALID: {why}")}
            }));
        }
    }

    let req: Json = match serde_json::from_slice(&body) {
        Ok(v) => v,
        Err(e) => {
            return write_json(stream, 200, &json!({
                "jsonrpc": "2.0", "id": Json::Null,
                "error": {"code": -32700, "message": format!("parse error: {e}")}
            }));
        }
    };

    let id = req.get("id").cloned().unwrap_or(Json::Null);
    let method_name = req.get("method").and_then(|m| m.as_str()).unwrap_or("");
    let params = req.get("params").cloned().unwrap_or(json!({}));

    // JSON-RPC 2.0: las notificaciones (sin id) no llevan respuesta.
    if req.get("id").is_none() {
        return write_json(stream, 200, &json!({}));
    }

    let result = dispatch(method_name, &params, config, mode, state);
    let resp = match result {
        Ok(r) => json!({"jsonrpc": "2.0", "id": id, "result": r}),
        Err((code, msg)) => json!({
            "jsonrpc": "2.0", "id": id,
            "error": {"code": code, "message": msg}
        }),
    };
    write_json(stream, 200, &resp)
}

fn write_json(stream: &mut TcpStream, status: u16, body: &Json) -> std::io::Result<()> {
    let payload = serde_json::to_string(body).unwrap_or_else(|_| "{}".into());
    let head = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\
         Access-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n",
        status,
        if status == 200 { "OK" } else { "Error" },
        payload.len()
    );
    stream.write_all(head.as_bytes())?;
    stream.write_all(payload.as_bytes())?;
    stream.flush()
}

/// Reparte el método JSON-RPC. Devuelve `Err((code, mensaje))` → error JSON-RPC.
fn dispatch(
    method: &str,
    params: &Json,
    config: &ServeConfig,
    mode: &AuthMode,
    state: &Arc<Mutex<Vec<GlobalEntry>>>,
) -> Result<Json, (i64, String)> {
    match method {
        "initialize" => Ok(json!({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": false}},
            "serverInfo": {"name": config.server_name, "version": config.server_version}
        })),
        "notifications/initialized" => Ok(json!({})),
        "ping" => Ok(json!({})),
        "tools/list" => {
            let guard = state.lock().map_err(|_| (-32603, "PDB bloqueada".to_string()))?;
            Ok(json!({"tools": tools_from_pdb(&guard)}))
        }
        "tools/call" => {
            // Tier escritura: sin clave no se ejecuta NADA. Leer el catálogo sí,
            // ejecutar rutinas no — una rutina M puede escribir en la PDB.
            if !mode.allows_write() {
                return Err((
                    -32003,
                    "modo lectura: sin DDP_HMAC_KEY no se ejecutan rutinas. \
                     Arranca con clave y firma la peticion."
                        .to_string(),
                ));
            }
            let name = params
                .get("name")
                .and_then(|v| v.as_str())
                .ok_or((-32602, "tools/call: falta 'name'".to_string()))?;
            let args = params
                .get("arguments")
                .cloned()
                .unwrap_or(json!({}));
            let mut guard = state
                .lock()
                .map_err(|_| (-32603, "PDB bloqueada".to_string()))?;
            call_tool(&mut guard, name, &args)
        }
        other => Err((-32601, format!("metodo no soportado: {other}"))),
    }
}

/// Construye el `tools/list` MCP desde `^TOOLS` (mismo catálogo que el motor).
///
/// Cada tool: `{"name","description","inputSchema"}`. El `inputSchema` sale de
/// `^TOOLS(nombre,"params")`; si falta, se usa un objeto abierto para que el
/// cliente pueda llamarla igualmente en vez de romper el listado.
fn tools_from_pdb(entries: &[GlobalEntry]) -> Vec<Json> {
    let mut host = MemoryHost::from_entries(entries.to_vec());
    let names = host
        .get("TOOLS", &[Subscript::String("__names".into())])
        .ok()
        .flatten()
        .map(|v| v.as_string())
        .unwrap_or_default();

    let mut out = Vec::new();
    for name in names.split(',').map(|s| s.trim()).filter(|s| !s.is_empty()) {
        let desc = host
            .get("TOOLS", &[
                Subscript::String(name.to_string()),
                Subscript::String("desc".into()),
            ])
            .ok()
            .flatten()
            .map(|v| v.as_string())
            .unwrap_or_default();
        let params = host
            .get("TOOLS", &[
                Subscript::String(name.to_string()),
                Subscript::String("params".into()),
            ])
            .ok()
            .flatten()
            .map(|v| v.as_string())
            .unwrap_or_default();
        let schema: Json = serde_json::from_str(&params).unwrap_or_else(|_| {
            json!({"type": "object", "additionalProperties": true})
        });
        out.push(json!({
            "name": name,
            "description": desc,
            "inputSchema": schema
        }));
    }
    out
}

/// Ejecuta una tool: escribe los argumentos en `^MCPARGS` y corre su rutina M.
fn call_tool(
    entries: &mut Vec<GlobalEntry>,
    name: &str,
    args: &Json,
) -> Result<Json, (i64, String)> {
    // 1) ¿Qué hay que ejecutar? `kind` = "m:%RUTINA" (o "d:dev:acc" en el futuro).
    let mut probe = MemoryHost::from_entries(entries.clone());
    let kind = probe
        .get("TOOLS", &[
            Subscript::String(name.to_string()),
            Subscript::String("kind".into()),
        ])
        .ok()
        .flatten()
        .map(|v| v.as_string())
        .unwrap_or_default();

    let routine = match kind.strip_prefix("m:") {
        Some(r) => r.trim().trim_start_matches('%').to_string(),
        None => {
            if kind.is_empty() {
                return Err((
                    -32602,
                    format!("tool '{name}' no existe en ^TOOLS (falta \"kind\")"),
                ));
            }
            return Err((
                -32603,
                format!("tool '{name}': kind '{kind}' aun no soportado (solo m:%RUTINA)"),
            ));
        }
    };

    // 2) Argumentos → ^MCPARGS("clave") = valor. Los no-string se serializan JSON
    //    para que la rutina M los lea como texto y decida (M-Light no tiene tipos
    //    compuestos nativos; el JSON en un global es el patrón del ecosistema).
    //
    //    ⚠ ANTES de escribir hay que LIMPIAR ^MCPARGS: si no, una llamada sin
    //    cierta clave reutiliza el valor de la anterior (medido: `saludar` sin
    //    `quien` devolvía el nombre de la petición previa). Cada tools/call debe
    //    ver exactamente sus propios argumentos.
    entries.retain(|e| e.ns != "MCPARGS");
    if let Some(obj) = args.as_object() {
        for (k, v) in obj {
            let val = match v {
                Json::String(s) => s.clone(),
                other => other.to_string(),
            };
            entries.push(GlobalEntry {
                ns: "MCPARGS".to_string(),
                subs: vec![Subscript::String(k.clone())],
                value: Value::String(val),
            });
        }
    }
    entries.push(GlobalEntry {
        ns: "MCPARGS".to_string(),
        subs: vec![Subscript::String("__tool".into())],
        value: Value::String(name.to_string()),
    });

    // 3) Cargar las rutinas: las del host (`^ROUTINE`) y la que pidió la tool.
    let mut host = MemoryHost::from_entries(entries.clone());
    let routines = routines_from_pdb(&mut host);
    if !routines.iter().any(|(n, _)| n.eq_ignore_ascii_case(&routine)) {
        return Err((
            -32603,
            format!("routine '{routine}' (tool '{name}') no esta en ^ROUTINE"),
        ));
    }
    for (n, src) in &routines {
        host.add_routine(n.clone(), src.clone());
    }

    // 4) Ejecutar. Mismo patrón que el ffi: VM sobre el host, gas acotado.
    let source = format!("D ^{routine}");
    let program = match Compiler::compile(&source) {
        Ok(p) => p,
        Err(e) => return Err((-32603, format!("compile error: {e}"))),
    };
    let out = {
        let mut vm = Vm::new(program, &mut host);
        vm.state.gas_limit = 5_000_000; // techo anti `while(1)`
        let exec = vm.run_slice(vm.state.gas_limit);
        let output = vm.state.output.clone();
        let err = vm.state.error.clone();
        let state = vm.state.clone();
        (exec, output, err, state)
    };

    let (exec, output, err, vm_state) = out;

    // 5) Persistir el estado (la rutina puede haber escrito en la PDB).
    *entries = host.entries();

    match exec {
        Execution::Error => {
            let msg = err
                .map(|e| e.zerror)
                .unwrap_or_else(|| "error de ejecucion".to_string());
            return Err((-32603, format!("rutina '{routine}': {msg}")));
        }
        _ => {}
    }

    // Si la VM quedó a medias (gas agotado) hay que decirlo, no fingir éxito.
    if vm_state.error.is_some() || vm_state.gas_used >= vm_state.gas_limit {
        return Err((
            -32603,
            format!(
                "rutina '{routine}': limite de ejecucion alcanzado (gas {}/{})",
                vm_state.gas_used, vm_state.gas_limit
            ),
        ));
    }

    Ok(json!({
        "content": [{"type": "text", "text": output}],
        "isError": false
    }))
}

/// Extrae las rutinas de `^ROUTINE(nombre,linea) = "texto"` (mismo formato que
/// usa el resto del motor para rutinas en caliente).
fn routines_from_pdb(host: &mut MemoryHost) -> Vec<(String, String)> {
    use std::collections::BTreeMap;
    // La linea es un subindice NUMERICO (f64 en M-Light). Se ordena por valor
    // con `sort_by` una vez recogido, no como clave de mapa.
    let mut lines: BTreeMap<String, Vec<(f64, String)>> = BTreeMap::new();

    let mut cur: Option<Subscript> = None;
    loop {
        match host.order("ROUTINE", &[], cur.as_ref(), 1) {
            Ok(Some(sub)) => {
                if let Subscript::String(rname) = &sub {
                    let mut lcur: Option<Subscript> = None;
                    loop {
                        match host.order(
                            "ROUTINE",
                            &[Subscript::String(rname.clone())],
                            lcur.as_ref(),
                            1,
                        ) {
                            Ok(Some(lsub)) => {
                                if let Subscript::Number(n) = &lsub {
                                    if let Ok(Some(Value::String(v))) = host.get(
                                        "ROUTINE",
                                        &[
                                            Subscript::String(rname.clone()),
                                            lsub.clone(),
                                        ],
                                    ) {
                                        lines
                                            .entry(rname.clone())
                                            .or_default()
                                            .push((*n, v.clone()));
                                    }
                                }
                                lcur = Some(lsub);
                            }
                            _ => break,
                        }
                    }
                }
                cur = Some(sub);
            }
            _ => break,
        }
    }

    lines
        .into_iter()
        .map(|(n, mut ls)| {
            ls.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
            let code = ls
                .into_iter()
                .map(|(_, v)| v)
                .collect::<Vec<_>>()
                .join("\n");
            (n, code)
        })
        .collect()
}
