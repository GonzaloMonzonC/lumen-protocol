//! Cota de epoch: lo que la custodia sola NO puede parar.
//!
//! ## La diferencia que se prueba aquí
//!
//! - La **custodia** impide saltos sin firmar: no puedes pasar del epoch 0 al 50
//!   sin presentar los 50 saltos firmados.
//! - La **cota** impide que un nodo **comprometido** (que sí puede firmarlos
//!   todos) absorba el sistema con un epoch enorme.
//!
//! Sin cota, un atacante con la clave de un dron gana siempre. Con cota, va a
//! cuarentena y el nodo sigue operando con la rama buena.

use lumen_nodo_lib::cota_epoch::{Cota, Cuarentena, Veredicto};
use lumen_nodo_lib::epoch::{verificar_con_cota, Custodia, SaltoEpoch};
use lumen_nodo_lib::identidad::Identidad;

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

/// Construye una cadena de `n` saltos firmados por el atacante.
fn cadena_de_saltos(id: &Identidad, desde: u64, n: u64) -> Vec<SaltoEpoch> {
    (0..n)
        .map(|i| {
            let d = desde + i;
            SaltoEpoch::crear(d, d + 1, "inst-mala", id).expect("salto")
        })
        .collect()
}

#[test]
fn la_custodia_sola_admite_una_cadena_larga_firmada() {
    // ESTE es el agujero: si el atacante tiene la clave, firma todos los saltos
    // y la custodia no tiene nada que objetar.
    println!();
    println!("==================================================================");
    println!("COTA DE EPOCH — el ataque que la custodia sola no para");
    println!("==================================================================");

    let atacante = Identidad::generar();
    let saltos = cadena_de_saltos(&atacante, 0, 100);

    let sin_cota = lumen_nodo_lib::epoch::verificar_cadena(
        0, 100, &saltos, &atacante.clave_publica_hex(),
    );

    println!("  atacante firma 100 saltos validos");
    println!("[{}] la custodia los acepta: {:?}", marca(sin_cota == Custodia::Valido), sin_cota);
    assert_eq!(
        sin_cota,
        Custodia::Valido,
        "la custodia NO puede parar esto: las firmas son validas"
    );
}

#[test]
fn la_cota_para_el_mismo_ataque() {
    let atacante = Identidad::generar();
    let saltos = cadena_de_saltos(&atacante, 0, 100);

    // Mismo ataque, ahora con cota.
    let con_cota = verificar_con_cota(
        0, 100, &saltos, &atacante.clave_publica_hex(), Cota::default(),
    );

    println!();
    match &con_cota {
        Custodia::FueraDeCota { motivo, .. } => {
            println!("[{}] la cota lo detecta y NO lo absorbe", marca(true));
            println!("      {motivo}");
        }
        otro => panic!("deberia ir a cuarentena, dio {otro:?}"),
    }
    assert!(matches!(con_cota, Custodia::FueraDeCota { .. }));
}

#[test]
fn el_ataque_a_2_a_la_63_va_a_cuarentena() {
    // El caso que describio Smith en el diseno.
    let atacante = Identidad::generar();
    let cota = Cota::default();

    let v = cota.revisar(0, u64::MAX);
    println!();
    println!("[{}] epoch 0 -> 2^64 a cuarentena", marca(v.va_a_cuarentena()));
    println!("      {}", v.motivo());
    assert!(v.va_a_cuarentena());

    // Y con saltos firmados de verdad, tampoco pasa la cota (ni se molestan en
    // verificarse: eso evita un ataque de denegacion por CPU).
    let saltos = cadena_de_saltos(&atacante, 0, 5);
    let r = verificar_con_cota(0, u64::MAX, &saltos, &atacante.clave_publica_hex(), cota);
    println!("[{}] y la cadena presentada no se acepta", marca(matches!(r, Custodia::FueraDeCota { .. })));
    assert!(matches!(r, Custodia::FueraDeCota { .. }));
}

#[test]
fn una_reinstalacion_normal_sigue_pasando() {
    // La cota no puede romper el caso legitimo.
    let id = Identidad::generar();
    let saltos = cadena_de_saltos(&id, 0, 1);

    let r = verificar_con_cota(0, 1, &saltos, &id.clave_publica_hex(), Cota::default());
    println!();
    println!("[{}] una reinstalacion normal (salto de 1) sigue pasando", marca(r == Custodia::Valido));
    assert_eq!(r, Custodia::Valido);
}

#[test]
fn la_cuarentena_aparta_la_rama_mala_y_deja_la_buena() {
    // Lo que el nodo hace con el veredicto: apartar, no romper.
    let atacante = Identidad::generar();
    let mut q = Cuarentena::nueva();

    let v = Cota::default().revisar(0, 5000);
    if let Veredicto::EnCuarentena { .. } = v {
        q.apartar("inst-mala", &v.motivo());
    }

    println!();
    println!("[{}] la rama atacante queda apartada", marca(q.esta_apartada("inst-mala")));
    println!("[{}] la rama buena sigue operando", marca(!q.esta_apartada("inst-buena")));
    assert!(q.esta_apartada("inst-mala"));
    assert!(!q.esta_apartada("inst-buena"));
    println!("      motivo guardado: {}...",
        &q.motivo("inst-mala").unwrap()[..50.min(q.motivo("inst-mala").unwrap().len())]);

    // Y solo un operador la libera.
    q.liberar("inst-mala");
    println!("[{}] un operador puede liberarla tras revisar", marca(!q.esta_apartada("inst-mala")));
    let _ = atacante;
}

#[test]
fn el_retroceso_de_epoch_siempre_es_cuarentena() {
    let id = Identidad::generar();
    let r = verificar_con_cota(10, 3, &[], &id.clave_publica_hex(), Cota::default());
    println!();
    println!("[{}] epoch 10 -> 3 (retroceso) -> cuarentena",
        marca(matches!(r, Custodia::FueraDeCota { .. })));
    assert!(matches!(r, Custodia::FueraDeCota { .. }));
}

#[test]
fn una_cota_ancha_permite_reinstalaciones_frecuentes() {
    // El numero correcto depende del despliegue: es configurable.
    let id = Identidad::generar();
    let saltos = cadena_de_saltos(&id, 0, 8);

    let estricta = verificar_con_cota(0, 8, &saltos, &id.clave_publica_hex(), Cota::nueva(1));
    let ancha = verificar_con_cota(0, 8, &saltos, &id.clave_publica_hex(), Cota::nueva(10));

    println!();
    println!("[{}] cota 1  -> cuarentena (salto de 8)", marca(matches!(estricta, Custodia::FueraDeCota { .. })));
    println!("[{}] cota 10 -> aceptado (salto de 8)", marca(ancha == Custodia::Valido));
    assert!(matches!(estricta, Custodia::FueraDeCota { .. }));
    assert_eq!(ancha, Custodia::Valido);
}
