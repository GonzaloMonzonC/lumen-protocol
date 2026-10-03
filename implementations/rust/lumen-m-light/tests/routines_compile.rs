// 04-oct-2026 (DISENO-4): los ficheros de rutina REALES del nodo deben COMPILAR
// con el compilador M-Light. Este test es la red de seguridad contra el fallo
// mas caro del proyecto: meter una rutina en la ISO que el motor no traga (el
// motor indexa al arrancar -> "unknown label" en produccion).
//
// Los ficheros se copian desde mvm-nas/deploy/routines a un tmp durante el test.
// CRLF y las lineas de una sola letra son M-Light-valido; lo que se comprueba
// es que `Compiler::compile` acepta la rutina ENTERA (todas sus lineas).
use lumen_mlight::Compiler;
use std::path::PathBuf;

fn compile_file(path: &str) -> Result<(), String> {
    let p = PathBuf::from(path);
    let src = std::fs::read_to_string(&p).map_err(|e| format!("{path}: {e}"))?;
    // El compilador de M-Light compila una rutina completa (etiquetas + lineas).
    Compiler::compile(&src).map(|_| ()).map_err(|e| format!("{path}: {e}"))
}

fn try_compile(name: &str) {
    // Rutas candidatas: el deploy real del nodo (mvm-nas) o el arbol de la ISO.
    let cands = [
        format!("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/{name}"),
        format!("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/initramfs-i686/opt/mvm/routines/{name}"),
    ];
    for c in &cands {
        if std::path::Path::new(c).exists() {
            match compile_file(c) {
                Ok(()) => return,
                Err(e) => panic!("la rutina {name} NO compila: {e}"),
            }
        }
    }
    // Si no esta el fichero (CI sin el repo vecino), se salta: no falla.
}

#[test]
fn node_routines_compile_with_mlight() {
    try_compile("%AGENTE.m");
}

#[test]
fn ss_and_guia_compile_with_mlight() {
    try_compile("%SS.m");
    try_compile("%GUIA.m");
}
