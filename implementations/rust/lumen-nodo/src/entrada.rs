//! Verificación de lo que llega por la red (`identity=pubkey`).
//!
//! ## El agujero que cierra
//!
//! Hasta aquí el nodo **firmaba** lo que escribía, pero al **recibir** de otro
//! barco guardaba lo que le mandaran. Eso es la mitad del trabajo: una firma que
//! nadie comprueba no protege de nada.
//!
//! ## Qué se comprueba, en este orden
//!
//! Para una muestra firmada que llega por red:
//!
//! 1. **La cadena es válida** (`hash == sha256(prev||valor)`)
//! 2. **La firma es de la clave que dice el certificado de flota** del barco
//! 3. **Ese certificado lo emitió la raíz del armador** que el nodo ya conoce
//!
//! Sólo si pasan las tres se escribe. Si falla cualquiera, se rechaza y se
//! responde FAILURE con el motivo: **no se guarda lo que no se puede verificar**.
//!
//! ## Lo que NO hace
//!
//! No descubre la clave del barco por su cuenta: hay que tenerla en el registro
//! de flota (`^FLOTA(ns, barco, "clave")` y `"certificado"`). Sin registro, un
//! nodo con `identity=pubkey` rechaza lo que no conoce — que es lo correcto:
//! aceptar claves desconocidas convertiría la verificación en un trámite.
//!
//! ## Por qué se acepta `identidad=pin` o `none` sin esta pieza
//!
//! `pin` verifica el certificado TLS del transporte: sabes con quién hablas.
//! `pubkey` verifica **el dato** además del transporte. Son niveles distintos y
//! se configuran por separado; exigir pubkey a todo el mundo rompería los nodos
//! que solo quieren sincronizar entre máquinas propias.

use crate::cadena::{
    verificar_con_clave, ErrorCadena, MuestraEncadenada, MuestraFirmada, Verificacion,
};
use crate::identidad::{CertificadoFlota, Identidad};

/// Lo que el nodo sabe de un barco de su flota.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BarcoConocido {
    /// Clave pública Ed25519 del barco (64 hex).
    pub clave: String,
    /// Certificado emitido por la raíz del armador.
    pub certificado: String,
}

/// De dónde se leen los barcos conocidos (la PDB, en el nodo real).
pub trait RegistroFlota {
    /// Busca un barco por su identificador. `None` si no está registrado.
    fn barco(&self, nombre: &str) -> Option<BarcoConocido>;
}

/// Resultado de verificar un lote que llega por red.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntradaVerificada {
    /// Muestras que pasaron todas las comprobaciones y se pueden escribir.
    pub aceptadas: Vec<(u64, MuestraEncadenada)>,
    /// Cuántas firmas se comprobaron.
    pub firmas_ok: u64,
    /// Primer problema, si lo hubo.
    pub problema: Option<ErrorCadena>,
}

impl EntradaVerificada {
    pub fn es_valida(&self) -> bool {
        self.problema.is_none() && !self.aceptadas.is_empty()
    }
}

/// Verifica un lote de muestras firmadas que llega de un barco.
///
/// `barco` es el nombre con el que el emisor se identifica; `ns` y `serie` son
/// la serie a la que pertenecen (van dentro del mensaje firmado, así que una
/// muestra de otra serie no pasa).
///
/// `raiz_armador` es la clave pública de la raíz de ESTA flota. Si el
/// certificado del barco no cuelga de ella, se rechaza aunque la firma sea
/// perfecta.
pub fn verificar_entrada(
    barco: &str,
    ns: &str,
    serie: &[String],
    muestras: &[(u64, String)],
    registro: &dyn RegistroFlota,
    raiz_armador: &str,
) -> EntradaVerificada {
    let mut out = EntradaVerificada {
        aceptadas: Vec::new(),
        firmas_ok: 0,
        problema: None,
    };

    // ── 1. ¿Conocemos a este barco? ──────────────────────────────
    let Some(conocido) = registro.barco(barco) else {
        out.problema = Some(ErrorCadena::MuestraIlegible(format!(
            "el barco '{barco}' no esta en el registro de flota: no se puede verificar"
        )));
        return out;
    };

    // ── 2. ¿Su certificado lo emitió nuestra raíz? ───────────────
    let Ok(cert) = CertificadoFlota::desde_texto(&conocido.certificado) else {
        out.problema = Some(ErrorCadena::MuestraIlegible(format!(
            "el certificado de '{barco}' esta mal formado"
        )));
        return out;
    };
    if let Err(e) = cert.verificar_con_raiz(raiz_armador) {
        out.problema = Some(ErrorCadena::MuestraIlegible(format!(
            "'{barco}' no pertenece a esta flota: {e}"
        )));
        return out;
    }

    // ── 3. ¿La clave del registro es la del certificado? ─────────
    // Si no coinciden, el registro y el certificado se contradicen y no hay
    // forma de saber cuál vale. Se rechaza en vez de elegir uno.
    if !conocido.clave.eq_ignore_ascii_case(&cert.clave_barco) {
        out.problema = Some(ErrorCadena::MuestraIlegible(format!(
            "la clave registrada de '{barco}' no coincide con su certificado"
        )));
        return out;
    }

    // ── 4. Cadena + firmas del lote ──────────────────────────────
    let v = verificar_con_clave(muestras, Some(&conocido.clave), ns, serie);
    out.firmas_ok = v.firmas_ok;
    if let Some(p) = v.problema {
        out.problema = Some(p);
        return out;
    }

    // ── 5. Si todo pasa, se aceptan ──────────────────────────────
    for (n, texto) in muestras {
        let m = MuestraFirmada::desde_texto(texto)
            .map(|mf| mf.cadena)
            .or_else(|| MuestraEncadenada::desde_texto(texto))
            .expect("ya verificado arriba");
        out.aceptadas.push((*n, m));
    }
    out
}

/// Registro de flota en memoria (tests).
#[derive(Debug, Default)]
pub struct RegistroMemoria {
    barcos: std::collections::HashMap<String, BarcoConocido>,
}

impl RegistroMemoria {
    pub fn alta(&mut self, nombre: &str, clave: &str, certificado: &str) {
        self.barcos.insert(
            nombre.to_string(),
            BarcoConocido {
                clave: clave.to_string(),
                certificado: certificado.to_string(),
            },
        );
    }
}

impl RegistroFlota for RegistroMemoria {
    fn barco(&self, nombre: &str) -> Option<BarcoConocido> {
        self.barcos.get(nombre).cloned()
    }
}

/// Construye el registro de flota a partir de una raíz que da de alta barcos.
///
/// Es el atajo para operar: la armadora registra sus barcos firmando sus claves,
/// y el nodo guarda clave + certificado. En el nodo real esto vive en
/// `^FLOTA(<ns>, <barco>, "clave"|"certificado")`.
pub fn alta_de_barco(
    raiz: &Identidad,
    armador: &str,
    barco: &str,
    clave_barco: &str,
) -> Option<BarcoConocido> {
    let cert = CertificadoFlota::emitir(raiz, armador, barco, clave_barco).ok()?;
    Some(BarcoConocido {
        clave: clave_barco.to_string(),
        certificado: cert.a_texto(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cadena::{encadenar, verificar};

    fn serie() -> Vec<String> {
        vec!["ESTRELLA".to_string(), "lat".to_string()]
    }

    /// Construye un lote firmado por un barco, con la cadena correcta.
    fn lote_firmado(id: &Identidad, n: u64) -> Vec<(u64, String)> {
        let s = serie();
        let mut prev = String::new();
        let mut out = Vec::new();
        for i in 1..=n {
            let m = encadenar(&prev, &format!("4{i}.0")).expect("encadenar");
            prev = m.hash.clone();
            let mut subs = s.clone();
            subs.push(i.to_string());
            let msg = MuestraFirmada::mensaje_canonico("FLOTA", &subs, &m.hash);
            let mf = MuestraFirmada {
                cadena: m,
                firma: id.firmar_hex(&msg),
            };
            out.push((i, mf.a_texto()));
        }
        out
    }

    fn flota() -> (Identidad, RegistroMemoria) {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let mut reg = RegistroMemoria::default();
        let conocido = alta_de_barco(&raiz, "Armadora", "ESTRELLA", &barco.clave_publica_hex())
            .expect("alta");
        reg.alta("ESTRELLA", &conocido.clave, &conocido.certificado);
        (raiz, reg)
    }

    #[test]
    fn lote_firmado_por_un_barco_registrado_se_acepta() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let mut reg = RegistroMemoria::default();
        let c = alta_de_barco(&raiz, "Armadora", "ESTRELLA", &barco.clave_publica_hex()).unwrap();
        reg.alta("ESTRELLA", &c.clave, &c.certificado);

        let lote = lote_firmado(&barco, 5);
        let r = verificar_entrada(
            "ESTRELLA",
            "FLOTA",
            &serie(),
            &lote,
            &reg,
            &raiz.clave_publica_hex(),
        );
        assert!(r.es_valida(), "problema: {:?}", r.problema);
        assert_eq!(r.aceptadas.len(), 5);
        assert_eq!(r.firmas_ok, 5);
    }

    #[test]
    fn un_barco_no_registrado_se_rechaza() {
        let (raiz, reg) = flota();
        let intruso = Identidad::generar();
        let lote = lote_firmado(&intruso, 3);
        let r = verificar_entrada(
            "DESCONOCIDO",
            "FLOTA",
            &serie(),
            &lote,
            &reg,
            &raiz.clave_publica_hex(),
        );
        assert!(!r.es_valida());
        assert!(r.aceptadas.is_empty(), "no debe aceptar nada");
        assert!(r.problema.unwrap().to_string().contains("no esta en el registro"));
    }

    #[test]
    fn un_barco_de_otra_flota_se_rechaza() {
        // Registrado en SU flota, pero nuestra raíz no lo respalda.
        let nuestra = Identidad::generar();
        let otra = Identidad::generar();
        let barco = Identidad::generar();

        let mut reg = RegistroMemoria::default();
        let c = alta_de_barco(&otra, "Otra", "ESTRELLA", &barco.clave_publica_hex()).unwrap();
        reg.alta("ESTRELLA", &c.clave, &c.certificado);

        let lote = lote_firmado(&barco, 3);
        let r = verificar_entrada(
            "ESTRELLA",
            "FLOTA",
            &serie(),
            &lote,
            &reg,
            &nuestra.clave_publica_hex(),
        );
        assert!(!r.es_valida());
        assert!(
            r.problema.unwrap().to_string().contains("no pertenece a esta flota"),
            "debe rechazar por flota"
        );
    }

    #[test]
    fn una_muestra_manipulada_se_rechaza() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let mut reg = RegistroMemoria::default();
        let c = alta_de_barco(&raiz, "A", "ESTRELLA", &barco.clave_publica_hex()).unwrap();
        reg.alta("ESTRELLA", &c.clave, &c.certificado);

        let mut lote = lote_firmado(&barco, 5);
        // Manipular el valor de la muestra 3 sin tocar la firma.
        let (n, texto) = lote[2].clone();
        let mut mf = MuestraFirmada::desde_texto(&texto).unwrap();
        mf.cadena.valor = "999.9".into();
        lote[2] = (n, mf.a_texto());

        let r = verificar_entrada(
            "ESTRELLA",
            "FLOTA",
            &serie(),
            &lote,
            &reg,
            &raiz.clave_publica_hex(),
        );
        assert!(!r.es_valida(), "un valor manipulado debe rechazarse");
    }

    #[test]
    fn una_firma_ajena_se_rechaza() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let impostor = Identidad::generar();
        let mut reg = RegistroMemoria::default();
        let c = alta_de_barco(&raiz, "A", "ESTRELLA", &barco.clave_publica_hex()).unwrap();
        reg.alta("ESTRELLA", &c.clave, &c.certificado);

        // El lote lo firma el impostor, no el barco registrado.
        let lote = lote_firmado(&impostor, 3);
        let r = verificar_entrada(
            "ESTRELLA",
            "FLOTA",
            &serie(),
            &lote,
            &reg,
            &raiz.clave_publica_hex(),
        );
        assert!(!r.es_valida());
        assert!(matches!(r.problema, Some(ErrorCadena::FirmaAjena { .. })));
    }

    #[test]
    fn muestras_sin_firmar_se_rechazan_cuando_se_pide_autoria() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let mut reg = RegistroMemoria::default();
        let c = alta_de_barco(&raiz, "A", "ESTRELLA", &barco.clave_publica_hex()).unwrap();
        reg.alta("ESTRELLA", &c.clave, &c.certificado);

        // Cadena sin firma.
        let mut prev = String::new();
        let mut lote = Vec::new();
        for i in 1..=3u64 {
            let m = encadenar(&prev, &format!("v{i}")).unwrap();
            prev = m.hash.clone();
            lote.push((i, m.a_texto()));
        }
        let r = verificar_entrada(
            "ESTRELLA",
            "FLOTA",
            &serie(),
            &lote,
            &reg,
            &raiz.clave_publica_hex(),
        );
        assert!(!r.es_valida());
        assert!(matches!(r.problema, Some(ErrorCadena::SinFirma { .. })));
    }

    #[test]
    fn un_registro_que_contradice_el_certificado_se_rechaza() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let otro = Identidad::generar();
        let mut reg = RegistroMemoria::default();
        let c = alta_de_barco(&raiz, "A", "ESTRELLA", &barco.clave_publica_hex()).unwrap();
        // Registramos el certificado del barco pero con la clave de OTRO.
        reg.alta("ESTRELLA", &otro.clave_publica_hex(), &c.certificado);

        let lote = lote_firmado(&barco, 3);
        let r = verificar_entrada(
            "ESTRELLA",
            "FLOTA",
            &serie(),
            &lote,
            &reg,
            &raiz.clave_publica_hex(),
        );
        assert!(!r.es_valida());
        assert!(r.problema.unwrap().to_string().contains("no coincide con su certificado"));
    }

    #[test]
    fn un_lote_de_otra_serie_se_rechaza() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let mut reg = RegistroMemoria::default();
        let c = alta_de_barco(&raiz, "A", "ESTRELLA", &barco.clave_publica_hex()).unwrap();
        reg.alta("ESTRELLA", &c.clave, &c.certificado);

        let lote = lote_firmado(&barco, 3);
        // Verificamos como si fuera otra serie: la firma no cubre estos subs.
        let otra = vec!["ESTRELLA".to_string(), "hdg".to_string()];
        let r = verificar_entrada(
            "ESTRELLA",
            "FLOTA",
            &otra,
            &lote,
            &reg,
            &raiz.clave_publica_hex(),
        );
        assert!(!r.es_valida(), "una muestra de lat no vale como hdg");
    }

    #[test]
    fn la_cadena_del_lote_aceptado_es_integra() {
        let raiz = Identidad::generar();
        let barco = Identidad::generar();
        let mut reg = RegistroMemoria::default();
        let c = alta_de_barco(&raiz, "A", "ESTRELLA", &barco.clave_publica_hex()).unwrap();
        reg.alta("ESTRELLA", &c.clave, &c.certificado);

        let lote = lote_firmado(&barco, 8);
        let r = verificar_entrada(
            "ESTRELLA",
            "FLOTA",
            &serie(),
            &lote,
            &reg,
            &raiz.clave_publica_hex(),
        );
        assert!(r.es_valida());
        // Las muestras aceptadas, verificadas como cadena, también son íntegras.
        let como_texto: Vec<(u64, String)> = r
            .aceptadas
            .iter()
            .map(|(n, m)| (*n, m.a_texto()))
            .collect();
        assert!(verificar(&como_texto).es_integro());
    }
}
