//! Los perfiles de `perfiles/*.json` cargan y son validos.
//!
//! Si alguien edita un JSON y lo deja incoherente, este test falla. Si anade un
//! perfil nuevo, se prueba solo con ponerlo en el directorio.

use lumen_nodo_lib::replicacion::PerfilReplicacion;
use std::path::Path;

#[test]
fn todos_los_perfiles_json_cargan_y_validan() {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("perfiles");
    let mut probados = 0;

    let mut entradas: Vec<_> = std::fs::read_dir(&dir)
        .expect("debe existir el directorio perfiles/")
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().map(|x| x == "json").unwrap_or(false))
        .collect();
    entradas.sort_by_key(|e| e.path());

    assert!(!entradas.is_empty(), "no hay ningun perfil en perfiles/");

    for e in entradas {
        let camino = e.path();
        let texto = std::fs::read_to_string(&camino)
            .unwrap_or_else(|err| panic!("no se pudo leer {:?}: {err}", camino));
        // Los JSON permiten claves extra con "_comentario": serde las ignora.
        let perfil = PerfilReplicacion::desde_json(&texto)
            .unwrap_or_else(|err| panic!("{:?} no parsea: {err}", camino));
        perfil
            .validar()
            .unwrap_or_else(|err| panic!("{:?} no valida: {err}", camino));
        println!("  {} -> OK (firma={}, retencion={})",
            camino.file_name().unwrap().to_string_lossy(), perfil.firma, perfil.retencion_modo);
        probados += 1;
    }
    assert!(probados > 0);
    println!("perfiles validados: {probados}");
}

#[test]
fn el_perfil_barco_json_coincide_con_el_programatico() {
    let camino = Path::new(env!("CARGO_MANIFEST_DIR")).join("perfiles").join("barco.json");
    let texto = std::fs::read_to_string(camino).expect("barco.json debe existir");
    let del_fichero = PerfilReplicacion::desde_json(&texto).expect("parsea");
    let programatico = PerfilReplicacion::barco();

    assert_eq!(del_fichero.retencion_modo, programatico.retencion_modo);
    assert_eq!(del_fichero.retencion_horas, programatico.retencion_horas);
    assert_eq!(del_fichero.replicacion, programatico.replicacion);
    assert_eq!(del_fichero.firma, programatico.firma);
    assert_eq!(del_fichero.firma_bloque_n, programatico.firma_bloque_n);
    assert_eq!(del_fichero.compactacion, programatico.compactacion);
    assert_eq!(del_fichero.conflicto, programatico.conflicto);
}
