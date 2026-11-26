//! Replicación de hechos entre nodos — perfil configurable, firma real.
//!
//! ## Qué añade esto
//!
//! El prototipo en Python (`experimentos/ddp-modelos/`) demostró que un motor
//! único con perfil configurable cumple en escenarios opuestos. Esto lo lleva a
//! código real:
//!
//! - **Firma Ed25519 de verdad** (no hash simulado), con la `Identidad` de
//!   [`crate::identidad`] y el PKI de flota que ya existe.
//! - **Perfil leído de fichero**, no un diccionario en memoria.
//! - **Transporte por `lumen-znet`**, no listas en memoria.
//! - **Cadena de hashes real** (`crate::cadena`), que ya estaba.
//!
//! ## El perfil
//!
//! Un nodo caro (barco) y un nodo barato (config) usan el MISMO código y distinto
//! perfil. El perfil decide retención, réplica, firma, compactación y conflicto.
//!
//! ## Lo que este módulo NO hace
//!
//! No resuelve el doble gasto ni consenso: eso es política de la capa de arriba.
//! Aquí solo se garantiza que los hechos viajan, se verifican y se conservan
//! según el perfil.

use crate::identidad::Identidad;
use serde::{Deserialize, Serialize};

/// Las cinco decisiones que un perfil puede tomar. Todo lo demás es común.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PerfilReplicacion {
    /// `"todo"` | `"ventana"`
    pub retencion_modo: String,
    /// Horas de ventana. `None` con `retencion_modo = "todo"`.
    pub retencion_horas: Option<u64>,

    /// `"todos"` | `"interes"` | `"flota"` | `"hub"`
    pub replicacion: String,
    /// Series que este nodo sigue. Solo con `replicacion = "interes"`.
    #[serde(default)]
    pub replicacion_interes: Vec<String>,

    /// `"por_hecho"` | `"por_bloque"` | `"ninguna"`
    pub firma: String,
    /// Muestras por bloque. Solo con `firma = "por_bloque"`.
    #[serde(default = "bloque_por_defecto")]
    pub firma_bloque_n: usize,

    /// `"archivar"` | `"sellos"` | `"descartar"`
    pub compactacion: String,

    /// `"ultimo_gana"` | `"primero_gana"` | `"manual"`
    pub conflicto: String,

    /// Cómo se confirma en disco. **Lo decide el disco, no la máquina.**
    ///
    /// - `"sync"`    — un `commit` con `fsync` por escritura. Durable: ante un
    ///   corte de luz no se pierde nada. Medido en la NAS: 71 ms por escritura.
    /// - `"nosync"`  — sin `fsync`. Rápido: medido en la NAS, 0,41 ms por
    ///   escritura (173× menos). Ante un corte se puede perder lo último, pero
    ///   LMDB no corrompe la base.
    /// - `"lote"`    — un `commit` cada `durabilidad_lote` escrituras. Punto
    ///   medio: se pierde como mucho el lote en curso.
    ///
    /// Por defecto `"lote"` con 64: es lo que aguanta tanto un SSD como un disco
    /// lento sin delatar ninguno de los dos.
    #[serde(default = "durabilidad_por_defecto")]
    pub durabilidad: String,

    /// Escrituras por `commit` cuando `durabilidad = "lote"`.
    #[serde(default = "lote_por_defecto")]
    pub durabilidad_lote: usize,

    /// Tamaño **inicial** del mapa de LMDB, en MB.
    ///
    /// No es un techo: si se llena, el store **crece solo** (duplica tamaño) y
    /// reintenta. Esto es solo el punto de partida, para no reservar un espacio
    /// de direcciones enorme cuando el nodo va a guardar poco.
    ///
    /// Lo que decide cuánto hace falta de verdad:
    /// - 40 barcos × 21.600 muestras ≈ 420 MB.
    /// - Un ledger de 1 M de usuarios, 5 M hechos/día ≈ 2,5 GB/día.
    ///
    /// Techo duro: **1.400 MB en 32 bits** (espacio de direcciones del proceso).
    #[serde(default = "mapsize_por_defecto")]
    pub mapsize_mb: usize,
}

fn mapsize_por_defecto() -> usize {
    1024
}

fn durabilidad_por_defecto() -> String {
    "lote".to_string()
}

fn lote_por_defecto() -> usize {
    64
}

fn bloque_por_defecto() -> usize {
    100
}

impl PerfilReplicacion {

    /// Aplica el perfil al entorno: cuántos MB de mapa y sin fsync o no.
    ///
    /// **Una sola fuente de verdad.** Antes el `MAPSIZE` venía de una variable de
    /// entorno y la durabilidad del perfil: dos sitios para lo mismo. Ahora
    /// ambos salen de aquí.
    ///
    /// El `mapsize_mb` del perfil es un **suelo**, no un techo: si se llena, el
    /// store crece solo.
    pub fn aplicar_al_entorno(&self) {
        // SAFETY: solo escribe variables de entorno del proceso, antes de abrir
        // el store. En Rust 2024 `set_var` es unsafe por los hilos; aquí se llama
        // al arrancar el nodo, antes de crear ninguno.
        unsafe {
            std::env::set_var("LUMEN_LMDB_MAPSIZE_MB", self.mapsize_mb.to_string());
        }
    }

    /// `true` si el store debe abrirse sin `fsync`.
    ///
    /// **Fuente unica de verdad**: el modo `sync` y `lote` necesitan fsync en el
    /// commit (el lote lo controla el escritor, no el store). Solo `nosync`
    /// desactiva el fsync del store.
    pub fn store_sin_fsync(&self) -> bool {
        self.durabilidad == "nosync"
    }

    /// Perfil de barco: 6 h sin cobertura, hay que probar que no falta nada.
    ///
    /// Durabilidad `lote`: un barco escribe a 1 Hz y suele llevar disco lento
    /// (NAS, SD, industrial). Con fsync por muestra tardaria 71 ms cada una
    /// (medido en NAS ARMv7); por lote de 64 baja a ~1 ms de media y se pierde
    /// como mucho el ultimo segundo de telemetria ante un corte.
    pub fn barco() -> Self {
        Self {
            retencion_modo: "ventana".into(),
            retencion_horas: Some(168),
            replicacion: "flota".into(),
            replicacion_interes: vec![],
            firma: "por_bloque".into(),
            firma_bloque_n: 100,
            compactacion: "sellos".into(),
            conflicto: "ultimo_gana".into(),
            durabilidad: "lote".into(),
            durabilidad_lote: 64,
            mapsize_mb: 512,
        }
    }

    /// Perfil de enjambre: nodos efímeros, solo lo que les afecta.
    ///
    /// Durabilidad `nosync`: un dron pierde la memoria al aterrizar de todas
    /// formas, y lo que importa es que el dato salga por el aire rapido. No
    /// tiene sentido pagar 70 ms por escritura para una telemetria que se
    /// pierde con la bateria.
    pub fn enjambre() -> Self {
        Self {
            retencion_modo: "ventana".into(),
            retencion_horas: Some(6),
            replicacion: "interes".into(),
            replicacion_interes: vec!["posicion".into(), "amenaza".into()],
            firma: "por_hecho".into(),
            firma_bloque_n: 100,
            compactacion: "descartar".into(),
            conflicto: "ultimo_gana".into(),
            durabilidad: "nosync".into(),
            durabilidad_lote: 64,
            mapsize_mb: 1024,
        }
    }

    /// Perfil de ledger: inmutable, todo se prueba, el conflicto se detecta.
    ///
    /// Durabilidad `sync`: un registro contable no puede perder escrituras.
    /// Aqui SI se paga el fsync por muestra, porque el valor esta en que el
    /// hecho este confirmado en disco cuando se da por bueno.
    pub fn ledger() -> Self {
        Self {
            retencion_modo: "todo".into(),
            retencion_horas: None,
            replicacion: "todos".into(),
            replicacion_interes: vec![],
            firma: "por_hecho".into(),
            firma_bloque_n: 100,
            compactacion: "archivar".into(),
            conflicto: "manual".into(),
            durabilidad: "sync".into(),
            durabilidad_lote: 64,
            mapsize_mb: 8192,
        }
    }

    /// Perfil de configuración: estado, no historia.
    ///
    /// Durabilidad `nosync`: si se pierde un cambio de temperatura de un agente
    /// ante un corte, se vuelve a escribir. No merece la pena el fsync.
    pub fn config() -> Self {
        Self {
            retencion_modo: "ventana".into(),
            retencion_horas: Some(1),
            replicacion: "hub".into(),
            replicacion_interes: vec![],
            firma: "ninguna".into(),
            firma_bloque_n: 100,
            compactacion: "descartar".into(),
            conflicto: "ultimo_gana".into(),
            durabilidad: "nosync".into(),
            durabilidad_lote: 64,
            mapsize_mb: 64,
        }
    }

    /// Carga un perfil desde JSON. Si el fichero no existe, error explícito.
    pub fn desde_json(texto: &str) -> Result<Self, String> {
        serde_json::from_str(texto).map_err(|e| format!("perfil JSON invalido: {e}"))
    }

    /// Valida que la combinación de valores tiene sentido.
    pub fn validar(&self) -> Result<(), String> {
        let modos_ret = ["todo", "ventana"];
        if !modos_ret.contains(&self.retencion_modo.as_str()) {
            return Err(format!("retencion_modo invalido: {}", self.retencion_modo));
        }
        if self.retencion_modo == "ventana" && self.retencion_horas.is_none() {
            return Err("retencion_modo=ventana exige retencion_horas".into());
        }
        if !["todos", "interes", "flota", "hub"].contains(&self.replicacion.as_str()) {
            return Err(format!("replicacion invalida: {}", self.replicacion));
        }
        if self.replicacion == "interes" && self.replicacion_interes.is_empty() {
            return Err("replicacion=interes exige replicacion_interes".into());
        }
        if !["por_hecho", "por_bloque", "ninguna"].contains(&self.firma.as_str()) {
            return Err(format!("firma invalida: {}", self.firma));
        }
        if self.firma == "por_bloque" && self.firma_bloque_n == 0 {
            return Err("firma_bloque_n no puede ser 0".into());
        }
        if !["archivar", "sellos", "descartar"].contains(&self.compactacion.as_str()) {
            return Err(format!("compactacion invalida: {}", self.compactacion));
        }
        if !["ultimo_gana", "primero_gana", "manual"].contains(&self.conflicto.as_str()) {
            return Err(format!("conflicto invalido: {}", self.conflicto));
        }
        if self.mapsize_mb == 0 {
            return Err("mapsize_mb debe ser mayor que 0".into());
        }
        // 32 bits: el mapa no puede pasar de ~1400 MB (espacio de direcciones).
        if cfg!(target_pointer_width = "32") && self.mapsize_mb > 1400 {
            return Err(format!(
                "mapsize_mb={} no cabe en 32 bits (maximo 1400)",
                self.mapsize_mb
            ));
        }
        if !["sync", "nosync", "lote"].contains(&self.durabilidad.as_str()) {
            return Err(format!("durabilidad invalida: {}", self.durabilidad));
        }
        if self.durabilidad == "lote" && self.durabilidad_lote == 0 {
            return Err("durabilidad=lote exige durabilidad_lote > 0".into());
        }
        Ok(())
    }
}

/// Un hecho replicable: una muestra firmada.
/// Tipo de un hecho: **qué regla de convergencia le aplica**.
///
/// ## Por qué hace falta
///
/// Sin tipar, todos los hechos son iguales y la reconvergencia no sabe qué
/// hacer con ellos. Poli lo dijo en la revisión:
/// *"si tratas todos los hechos como iguales, tendrás hechos huérfanos que nadie
/// sabe si importan. Sin tipado, la separación es cosmética."*
///
/// ## Y por qué NO todos valen `ultimo_gana`
///
/// Smith fue tajante: *"LWW sobre seguridad es un error de categoría"*. Un dron
/// que ya ejecutó un viraje evasivo lo hizo; no se puede reescribir que no lo
/// hizo. Para eso está [`TipoHecho::ConRevision`]: el conflicto se marca y
/// decide un operador, no una marca de tiempo.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum TipoHecho {
    /// **Telemetría**: el valor nuevo sustituye al viejo sin más. Es lo que
    /// hacía `ultimo_gana` y está bien para "la batería está al 47%",
    /// "el dron está en (lat, lon, alt)".
    ///
    /// Ojo: en telemetría, perder una lectura intermedia **no importa**.
    #[default]
    Idempotente,

    /// **Conmutativo**: el orden entre hechos distintos no cambia el resultado
    /// (contadores, sumas de horas de vuelo). Unirse = sumar.
    Conmutativo,

    /// **Recurso exclusivo**: reserva de algo que solo puede tener un dueño a la
    /// vez (volumen de aire, carril, ventana de aterrizaje).
    ///
    /// Dos ramas pueden reservar el mismo recurso. La unión **no** lo resuelve:
    /// hay que detectar el conflicto y marcarlo.
    RecursoExclusivo,

    /// **Seguridad o decisión**: cambio de modo, aborto de misión, RTH.
    ///
    /// **Nunca `ultimo_gana`.** Si un hecho así se aplicó, se aplicó. Para
    /// deshacerlo hace falta otro hecho que lo revoque explícitamente.
    ConRevision,
}

impl TipoHecho {
    /// Texto corto para el contenido canónico (y para el cable).
    ///
    /// Se firma, así que cambiarlo cambia la firma: nadie puede pasar un hecho
    /// de telemetría a seguridad sin invalidarlo.
    pub fn etiqueta(&self) -> &'static str {
        match self {
            TipoHecho::Idempotente => "idem",
            TipoHecho::Conmutativo => "conm",
            TipoHecho::RecursoExclusivo => "recurso",
            TipoHecho::ConRevision => "revision",
        }
    }

    pub fn desde_etiqueta(t: &str) -> Option<Self> {
        match t {
            "idem" => Some(TipoHecho::Idempotente),
            "conm" => Some(TipoHecho::Conmutativo),
            "recurso" => Some(TipoHecho::RecursoExclusivo),
            "revision" => Some(TipoHecho::ConRevision),
            _ => None,
        }
    }

    /// ¿Se puede resolver solo, sin intervención humana?
    ///
    /// Los de recurso y los de seguridad **no**: pueden llegar a un estado
    /// incorrecto aunque converja (lo que Smith llamó "divergencia exitosa").
    pub fn converge_solo(&self) -> bool {
        matches!(self, TipoHecho::Idempotente | TipoHecho::Conmutativo)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Hecho {
    /// Versión del formato. `1` = original (sin instancia ni epoch).
    /// `2` = con `instance_id` y `epoch`. Ver `contenido_canonico`.
    pub version: u8,
    /// Nodo que lo produjo. Va DENTRO de la identidad (lección del prototipo).
    pub nodo: String,
    /// Serie a la que pertenece (`gps`, `posicion`, ...).
    pub serie: String,
    /// Secuencia dentro de `(nodo, serie)`.
    pub seq: u64,
    /// Qué **proceso** lo escribió. Distingue una reinstalación de una
    /// suplantación y permite que dos ramas coexistan sin perderse.
    /// Vacío en hechos v1.
    pub instance_id: String,
    /// Era del escritor. Sube en reinstalación; un salto exige la firma del
    /// epoch anterior (cadena de custodia). `0` en hechos v1.
    pub epoch: u64,
    /// Clave lógica (`gps`, `saldo:A`, ...).
    pub clave: String,
    /// Valor. Vacío si es un borrado.
    pub valor: String,
    /// Hash del hecho anterior de la misma serie.
    pub prev_hash: String,
    /// **Tipo del hecho**: qué regla de convergencia le aplica.
    ///
    /// Solo cuenta en v3. En v1 y v2 se ignora al verificar (vale
    /// `Idempotente`), porque esos hechos ya están firmados sin el campo y
    /// añadirlo al contenido firmado los invalidaría todos.
    pub tipo: TipoHecho,

    /// Timestamp en segundos.
    pub ts: u64,
    /// Firma Ed25519 del contenido canónico. `None` si el perfil no firma.
    pub firma: Option<[u8; 64]>,
}

impl Default for Hecho {
    /// Hecho vacío en **v2**: es el formato recomendado, así que un literal que
    /// use `..Default::default()` queda en v2 sin tener que enumerar campos.
    ///
    /// Los tests y el código que construye hechos con struct literal siguen
    /// funcionando añadiendo `..Default::default()`.
    fn default() -> Self {
        Self {
            version: 2,
            nodo: String::new(),
            serie: String::new(),
            seq: 0,
            instance_id: String::new(),
            epoch: 0,
            clave: String::new(),
            valor: String::new(),
            prev_hash: String::new(),
            tipo: TipoHecho::Idempotente,
            ts: 0,
            firma: None,
        }
    }
}

impl Hecho {
    /// Hecho en **v3**: como v2 pero con el tipo de convergencia.
    ///
    /// Es el formato recomendado para todo lo nuevo. v1 y v2 se siguen leyendo
    /// (y verificando) pero no se emiten.
    #[allow(clippy::too_many_arguments)]
    pub fn v3(
        nodo: &str,
        serie: &str,
        seq: u64,
        instance_id: &str,
        epoch: u64,
        clave: &str,
        valor: &str,
        prev_hash: &str,
        ts: u64,
        tipo: TipoHecho,
    ) -> Self {
        Self {
            version: 3,
            nodo: nodo.into(),
            serie: serie.into(),
            seq,
            instance_id: instance_id.into(),
            epoch,
            clave: clave.into(),
            valor: valor.into(),
            prev_hash: prev_hash.into(),
            tipo,
            ts,
            firma: None,
        }
    }

    /// Hecho en formato **v2** (con instancia y epoch). Es el recomendado.
    pub fn v2(
        nodo: &str,
        serie: &str,
        seq: u64,
        instance_id: &str,
        epoch: u64,
        clave: &str,
        valor: &str,
        prev_hash: &str,
        ts: u64,
    ) -> Self {
        Self {
            version: 2,
            nodo: nodo.into(),
            serie: serie.into(),
            seq,
            instance_id: instance_id.into(),
            epoch,
            clave: clave.into(),
            valor: valor.into(),
            prev_hash: prev_hash.into(),
            tipo: TipoHecho::Idempotente,
            ts,
            firma: None,
        }
    }

    /// Hecho en formato **v1**. Solo para leer o escribir series antiguas.
    ///
    /// No se puede convertir un v1 a v2: su firma no cubre los campos nuevos y
    /// re-firmarlo rompería la inmutabilidad.
    #[allow(clippy::too_many_arguments)]
    pub fn v1(
        nodo: &str,
        serie: &str,
        seq: u64,
        clave: &str,
        valor: &str,
        prev_hash: &str,
        ts: u64,
    ) -> Self {
        Self {
            version: 1,
            nodo: nodo.into(),
            serie: serie.into(),
            seq,
            instance_id: String::new(),
            epoch: 0,
            clave: clave.into(),
            valor: valor.into(),
            prev_hash: prev_hash.into(),
            tipo: TipoHecho::Idempotente,
            ts,
            firma: None,
        }
    }

    /// Identidad del hecho: lleva el nodo **y la instancia** dentro.
    ///
    /// Sin `instance_id`, dos escritores del mismo barco (reinstalación, dos
    /// procesos, dos hubs en partición) colisionan y el segundo se pierde en
    /// silencio. Con él, coexisten como dos ramas.
    pub fn identidad(&self) -> (String, String, u64, String) {
        (
            self.nodo.clone(),
            self.serie.clone(),
            self.seq,
            self.instance_id.clone(),
        )
    }

    /// Bytes canónicos que se firman. **Elige el payload según la versión.**
    ///
    /// v1: formato original, sin `instance_id` ni `epoch`. Los hechos ya
    ///     escritos se firmaron así y **no se re-firman** (rompería la
    ///     inmutabilidad, que es el punto del sistema).
    /// v2: añade `instance_id` y `epoch` para poder distinguir dos escritores
    ///     del mismo barco sin descartar hechos.
    ///
    /// Se usa `\x1f` (unit separator) porque no puede aparecer en un valor
    /// normal y evita que `("ab","c")` y `("a","bc")` den la misma firma.
    pub fn contenido_canonico(&self) -> Vec<u8> {
        match self.version {
            1 => format!(
                "{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}",
                self.nodo, self.serie, self.seq, self.clave, self.valor, self.prev_hash, self.ts
            )
            .into_bytes(),
            // v3 = v2 + tipo del hecho. El tipo va DENTRO de lo firmado: si no,
            // alguien podría pasar un hecho de telemetría a seguridad sin
            // invalidar la firma, y la regla de convergencia dejaría de ser
            // creíble.
            3 => format!(
                "v3\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}",
                self.nodo,
                self.serie,
                self.seq,
                self.instance_id,
                self.epoch,
                self.clave,
                self.valor,
                self.prev_hash,
                self.ts,
                self.tipo.etiqueta()
            )
            .into_bytes(),
            _ => format!(
                "v2\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}\x1f{}",
                self.nodo,
                self.serie,
                self.seq,
                self.instance_id,
                self.epoch,
                self.clave,
                self.valor,
                self.prev_hash,
                self.ts
            )
            .into_bytes(),
        }
    }

    /// Hash del hecho (para encadenar el siguiente).
    ///
    /// No depende de la versión: encadena `prev_hash || valor`, que es lo que
    /// hace `cadena::hash_muestra`. Así una serie v1 y una v2 encadenan igual
    /// y la migración no rompe la cadena.
    pub fn hash(&self) -> String {
        crate::cadena::hash_muestra(&self.prev_hash, &self.valor)
    }

    /// ¿Es el mismo hecho lógico que otro? (mismo nodo, serie y seq)
    ///
    /// Dos hechos con la misma clave lógica pero distinta instancia son **dos
    /// ramas**, no un duplicado.
    pub fn misma_posicion(&self, otro: &Hecho) -> bool {
        self.nodo == otro.nodo && self.serie == otro.serie && self.seq == otro.seq
    }

    /// Firma el hecho con la identidad del nodo.
    pub fn firmar(&mut self, identidad: &Identidad) {
        self.firma = Some(identidad.firmar(&self.contenido_canonico()));
    }

    /// Verifica la firma contra la clave pública del nodo emisor.
    pub fn verificar_firma(&self, clave_publica: &[u8]) -> Result<(), String> {
        let firma = self
            .firma
            .ok_or_else(|| "hecho sin firma".to_string())?;
        crate::identidad::verificar(clave_publica, &self.contenido_canonico(), &firma)
            .map_err(|e| format!("firma invalida: {e:?}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cada_perfil_declara_su_mapsize() {
        // Los cuatro perfiles, de menos a mas.
        assert_eq!(PerfilReplicacion::config().mapsize_mb, 64);
        assert_eq!(PerfilReplicacion::barco().mapsize_mb, 512);
        assert_eq!(PerfilReplicacion::enjambre().mapsize_mb, 1024);
        assert_eq!(PerfilReplicacion::ledger().mapsize_mb, 8192);
    }

    #[test]
    fn un_mapsize_de_cero_es_invalido() {
        let mut p = PerfilReplicacion::barco();
        p.mapsize_mb = 0;
        assert!(p.validar().is_err(), "0 MB de mapa no tiene sentido");
    }

    #[test]
    fn en_32_bits_el_mapa_tiene_techo() {
        let mut p = PerfilReplicacion::ledger();
        p.mapsize_mb = 1401;
        if cfg!(target_pointer_width = "32") {
            assert!(p.validar().is_err(), "1401 MB no caben en 32 bits");
        } else {
            assert!(p.validar().is_ok(), "en 64 bits no hay ese techo");
        }
    }

    #[test]
    fn los_cuatro_perfiles_son_validos() {
        for p in [
            PerfilReplicacion::barco(),
            PerfilReplicacion::enjambre(),
            PerfilReplicacion::ledger(),
            PerfilReplicacion::config(),
        ] {
            p.validar().expect("perfil deberia ser valido");
        }
    }

    #[test]
    fn un_perfil_incoherente_se_rechaza() {
        let mut p = PerfilReplicacion::barco();
        p.retencion_horas = None; // ventana sin horas
        assert!(p.validar().is_err());

        let mut p2 = PerfilReplicacion::barco();
        p2.replicacion = "interes".into();
        p2.replicacion_interes = vec![]; // interes sin lista
        assert!(p2.validar().is_err());
    }

    #[test]
    fn el_perfil_va_y_vuelve_por_json() {
        let p = PerfilReplicacion::barco();
        let txt = serde_json::to_string(&p).unwrap();
        let vuelta = PerfilReplicacion::desde_json(&txt).unwrap();
        assert_eq!(p, vuelta);
    }

    #[test]
    fn la_firma_ed25519_verifica_y_detecta_manipulacion() {
        let id = Identidad::generar();
        let mut h = Hecho {
            nodo: "BARCO-A".into(),
            serie: "gps".into(),
            seq: 0,
            clave: "gps".into(),
            valor: "lat=41.1".into(),
            prev_hash: String::new(),
            ts: 100,
            firma: None,
            ..Default::default()
        };
        h.firmar(&id);
        assert!(h.verificar_firma(&id.clave_publica()).is_ok());

        // Manipular el valor invalida la firma.
        h.valor = "lat=99.9".into();
        assert!(h.verificar_firma(&id.clave_publica()).is_err());
    }

    #[test]
    fn un_impostor_no_puede_firmar_como_el_barco() {
        let barco = Identidad::generar();
        let impostor = Identidad::generar();
        let mut h = Hecho {
            nodo: "BARCO-A".into(),
            serie: "gps".into(),
            seq: 0,
            clave: "gps".into(),
            valor: "lat=41.1".into(),
            prev_hash: String::new(),
            ts: 100,
            firma: None,
            ..Default::default()
        };
        h.firmar(&impostor);
        // La clave pública del barco NO valida la firma del impostor.
        assert!(h.verificar_firma(&barco.clave_publica()).is_err());
    }

    #[test]
    fn el_separador_evita_colisiones_de_concatenacion() {
        // ("ab","c") y ("a","bc") deben dar contenido distinto.
        let mut a = Hecho {
            nodo: "N".into(), serie: "S".into(), seq: 1, clave: "ab".into(),
            valor: "c".into(), prev_hash: String::new(), ts: 1, firma: None,
            ..Default::default()
        };
        let mut b = a.clone();
        b.clave = "a".into();
        b.valor = "bc".into();
        assert_ne!(a.contenido_canonico(), b.contenido_canonico());
        a.seq = 1;
        let _ = b;
    }
}
