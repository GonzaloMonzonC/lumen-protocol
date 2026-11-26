//! Cota de epoch — lo que evita que un nodo comprometido gane siempre.
//!
//! ## El ataque que hay que parar
//!
//! Smith, en la revisión del diseño:
//!
//! > *"Cualquiera con la clave de un dron fabrica `epoch = 2^63`, y como el merge
//! > es monótono, ese sello es **estado absorbente irreversible** — no puedes
//! > deshacerlo sin violar 'nunca se borra'."*
//!
//! La cadena de custodia (`epoch.rs`) ya impide saltar sin firmar cada paso. Pero
//! un nodo comprometido **puede firmar** sus propios saltos: tiene la clave.
//!
//! ## La única defensa honesta
//!
//! **Sin consenso no se puede prevenir.** Lo único que se puede hacer es
//! **detectar** y **no absorber**:
//!
//! - Un salto mayor de lo que es plausible → **cuarentena**, no se acepta.
//! - El nodo sigue funcionando con la rama buena.
//! - Queda constancia firmada para que un operador decida.
//!
//! Smith fue explícito: *"sin consenso, un dron comprometido es dueño del cielo.
//! Lo único honesto es **detectar**, no prevenir."*
//!
//! ## Qué es "plausible"
//!
//! Un epoch sube en **reinstalación** y en **recuperación**. En un enjambre, un
//! salto de 1 es normal; de 5 es raro; de un millón es un ataque o un bug.
//!
//! La cota es **configurable**, porque el número correcto depende del despliegue:
//! en un dron que se reinstala cada semana, 10 es razonable; en uno que nunca se
//! toca, 2 ya es sospechoso.

use std::collections::BTreeMap;


/// Serie donde se persiste la cuarentena de un nodo.
///
/// ## Por qué una serie y no una tabla aparte
///
/// La cuarentena **tiene que sobrevivir al reinicio**. Si vive solo en memoria,
/// al arrancar otra vez el nodo no recuerda qué ramas había apartado y las vuelve
/// a admitir sin revisión — **el mismo error que corregimos con los conflictos**.
///
/// Usar una serie de hechos significa:
/// - Se guarda en la PDB/LMDB **como todo lo demás** (nada nuevo que mantener).
/// - Queda **firmada y encadenada**: nadie puede borrar una cuarentena sin que
///   se note.
/// - Se puede **auditar**: hay historia de cuándo se apartó y cuándo se liberó.
///
/// Un evento de cuarentena es un hecho: `apartar` o `liberar`.
pub const SERIE_CUARENTENA: &str = "cuarentena";

/// Persiste un evento de cuarentena en el store, encadenado y firmado.
///
/// Devuelve el `seq` del hecho escrito.
pub fn persistir_evento<H: lumen_mlight::Host>(
    host: &mut H,
    nodo: &str,
    instancia: &str,
    epoch: u64,
    ts: u64,
    rama: &str,
    accion: AccionCuarentena,
    motivo: &str,
    firmante: Option<&crate::identidad::Identidad>,
) -> Option<u64> {
    use crate::hechos_store;
    use crate::replicacion::{Hecho, TipoHecho};

    // OJO: contar_serie_rama, NO contar_serie. La segunda cuenta la rama
    // principal (instancia "") y devolveria 0 siempre, sobrescribiendo cada
    // evento en seq 0.
    let seq = hechos_store::contar_serie_rama(host, nodo, SERIE_CUARENTENA, instancia);
    let prev = if seq == 0 {
        String::new()
    } else {
        hechos_store::leer(host, nodo, SERIE_CUARENTENA, seq - 1, instancia)
            .map(|h| h.hash())
            .unwrap_or_default()
    };

    // La clave es la rama afectada: así se puede consultar el último evento de
    // una rama concreta sin recorrer toda la serie.
    let valor = format!("accion={}; motivo={}", accion.etiqueta(), motivo);

    let mut h = Hecho::v3(
        nodo,
        SERIE_CUARENTENA,
        seq,
        instancia,
        epoch,
        rama,
        &valor,
        &prev,
        ts,
        // Apartar una rama es una decisión que afecta a la operación: nunca
        // converge sola.
        TipoHecho::ConRevision,
    );
    if let Some(id) = firmante {
        h.firmar(id);
    }
    hechos_store::guardar(host, &h).ok()?;
    Some(seq)
}

/// Reconstruye la cuarentena desde la serie persistida.
///
/// Recorre los eventos en orden y se queda con el último por rama: si una rama se
/// apartó y luego se liberó, **no está en cuarentena**.
pub fn reconstruir<H: lumen_mlight::Host>(
    host: &H,
    nodo: &str,
    instancia: &str,
) -> Cuarentena {
    use crate::hechos_store;

    let mut q = Cuarentena::nueva();
    let eventos = hechos_store::leer_serie_de_rama(host, nodo, SERIE_CUARENTENA, instancia);

    for h in eventos {
        let Some(accion) = AccionCuarentena::de_valor(&h.valor) else {
            continue;
        };
        let motivo = h
            .valor
            .split("motivo=")
            .nth(1)
            .unwrap_or("")
            .to_string();
        match accion {
            AccionCuarentena::Apartar => q.apartar(&h.clave, &motivo),
            AccionCuarentena::Liberar => {
                q.liberar(&h.clave);
            }
        }
    }
    q
}

/// Qué se hizo con una rama.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AccionCuarentena {
    Apartar,
    Liberar,
}

impl AccionCuarentena {
    pub fn etiqueta(&self) -> &'static str {
        match self {
            AccionCuarentena::Apartar => "apartar",
            AccionCuarentena::Liberar => "liberar",
        }
    }

    pub fn de_valor(valor: &str) -> Option<Self> {
        let a = valor.strip_prefix("accion=")?.split(';').next()?;
        match a {
            "apartar" => Some(AccionCuarentena::Apartar),
            "liberar" => Some(AccionCuarentena::Liberar),
            _ => None,
        }
    }
}

/// Resultado de revisar un salto de epoch contra la cota.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Veredicto {
    /// Salto normal, se acepta.
    Aceptado { desde: u64, hacia: u64 },
    /// Salto mayor de lo permitido: **no se absorbe, va a cuarentena**.
    ///
    /// No se rechaza del todo: el nodo puede tener una razón legítima
    /// (reinstalación tras perder la configuración). Pero no se acepta solo.
    EnCuarentena {
        desde: u64,
        hacia: u64,
        salto: u64,
        permitido: u64,
    },
    /// El epoch **baja**. Eso no puede pasar: es un sello viejo reinyectado o un
    /// reloj que retrocede. Siempre a cuarentena.
    Retrocede { desde: u64, hacia: u64 },
}

impl Veredicto {
    pub fn es_aceptado(&self) -> bool {
        matches!(self, Veredicto::Aceptado { .. })
    }

    /// ¿Hay que apartar esta rama de la operación normal?
    pub fn va_a_cuarentena(&self) -> bool {
        !self.es_aceptado()
    }

    /// Texto para el registro del operador.
    pub fn motivo(&self) -> String {
        match self {
            Veredicto::Aceptado { desde, hacia } => {
                format!("epoch {desde} -> {hacia}: dentro de la cota")
            }
            Veredicto::EnCuarentena { desde, hacia, salto, permitido } => format!(
                "epoch {desde} -> {hacia}: salto de {salto}, cota {permitido} — \
                 puede ser reinstalacion legitima o un nodo comprometido. \
                 NO se absorbe: requiere revision"
            ),
            Veredicto::Retrocede { desde, hacia } => format!(
                "epoch {desde} -> {hacia}: el epoch RETROCEDE, imposible en un nodo \
                 sano. Sello viejo reinyectado o reloj que retrocede"
            ),
        }
    }
}

/// Configuración de la cota.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Cota {
    /// Salto máximo aceptable sin revisión.
    pub salto_max: u64,
}

impl Default for Cota {
    /// Cota por defecto: **salto de 1**.
    ///
    /// En un enjambre sano el epoch sube de uno en uno (la custodia lo exige).
    /// Cualquier cosa mayor ya merece que alguien la mire.
    fn default() -> Self {
        Self { salto_max: 1 }
    }
}

impl Cota {
    pub fn nueva(salto_max: u64) -> Self {
        Self { salto_max }
    }

    /// Revisa un salto.
    pub fn revisar(&self, desde: u64, hacia: u64) -> Veredicto {
        if hacia < desde {
            return Veredicto::Retrocede { desde, hacia };
        }
        let salto = hacia - desde;
        if salto <= self.salto_max {
            Veredicto::Aceptado { desde, hacia }
        } else {
            Veredicto::EnCuarentena { desde, hacia, salto, permitido: self.salto_max }
        }
    }
}

/// Estado de cuarentena de un nodo: qué ramas están apartadas y por qué.
///
/// Se guarda en memoria **y** debe poder persistirse: si se pierde al reiniciar,
/// la rama en cuarentena volvería a entrar sin revisión. (La persistencia es
/// responsabilidad del llamante; aquí solo se modela.)
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Cuarentena {
    /// `instancia -> motivo` de por qué está apartada.
    apartadas: BTreeMap<String, String>,
}

impl Cuarentena {
    pub fn nueva() -> Self {
        Self::default()
    }

    /// Aparta una rama con su motivo.
    pub fn apartar(&mut self, instancia: &str, motivo: &str) {
        self.apartadas.insert(instancia.to_string(), motivo.to_string());
    }

    pub fn esta_apartada(&self, instancia: &str) -> bool {
        self.apartadas.contains_key(instancia)
    }

    pub fn motivo(&self, instancia: &str) -> Option<&str> {
        self.apartadas.get(instancia).map(|s| s.as_str())
    }

    /// Levanta la cuarentena. **Solo un operador debería llamar a esto.**
    pub fn liberar(&mut self, instancia: &str) -> bool {
        self.apartadas.remove(instancia).is_some()
    }

    pub fn len(&self) -> usize {
        self.apartadas.len()
    }

    pub fn esta_vacia(&self) -> bool {
        self.apartadas.is_empty()
    }

    pub fn apartadas(&self) -> impl Iterator<Item = (&String, &String)> {
        self.apartadas.iter()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn un_salto_de_uno_se_acepta() {
        let c = Cota::default();
        assert!(c.revisar(0, 1).es_aceptado());
        assert!(c.revisar(7, 8).es_aceptado());
    }

    #[test]
    fn sin_salto_tambien_se_acepta() {
        // Mismo epoch: no es un salto, es el mismo escritor.
        let c = Cota::default();
        assert!(c.revisar(5, 5).es_aceptado());
    }

    #[test]
    fn el_ataque_de_2_a_la_63_va_a_cuarentena() {
        // EL CASO DEL DISEÑO: un nodo comprometido fabrica un epoch enorme.
        let c = Cota::default();
        let v = c.revisar(0, u64::MAX);
        println!();
        println!("  ataque epoch 2^63 -> {:?}", v);
        assert!(v.va_a_cuarentena(), "un salto a 2^63 NO puede absorberse");
        if let Veredicto::EnCuarentena { salto, permitido, .. } = v {
            assert_eq!(permitido, 1);
            assert!(salto > permitido);
        } else {
            panic!("deberia ser cuarentena");
        }
    }

    #[test]
    fn el_epoch_no_puede_retroceder() {
        let c = Cota::default();
        let v = c.revisar(10, 3);
        assert!(matches!(v, Veredicto::Retrocede { .. }));
        assert!(v.va_a_cuarentena());
    }

    #[test]
    fn una_cota_mas_ancha_admite_reinstalaciones_frecuentes() {
        // Configurable: un dron que se reinstala a menudo necesita margen.
        let c = Cota::nueva(10);
        assert!(c.revisar(0, 10).es_aceptado());
        assert!(c.revisar(0, 11).va_a_cuarentena());
    }

    #[test]
    fn el_motivo_se_explica_para_el_operador() {
        let c = Cota::default();
        let m = c.revisar(0, 1000).motivo();
        println!();
        println!("  motivo: {m}");
        assert!(m.contains("1000"));
        assert!(m.contains("revision"));
        // No dice "ataque": no se puede saber. Dice lo que se sabe.
        assert!(!m.contains("ataque"));
    }

    #[test]
    fn cuarentena_aparta_y_libera() {
        let mut q = Cuarentena::nueva();
        assert!(q.esta_vacia());

        q.apartar("inst-mala", "salto de epoch imposible");
        assert!(q.esta_apartada("inst-mala"));
        assert!(!q.esta_apartada("inst-buena"));
        assert_eq!(q.motivo("inst-mala"), Some("salto de epoch imposible"));
        assert_eq!(q.len(), 1);

        assert!(q.liberar("inst-mala"));
        assert!(!q.esta_apartada("inst-mala"));
        assert!(!q.liberar("inst-mala"), "liberar dos veces no hace nada");
    }

    #[test]
    fn apartar_dos_veces_actualiza_el_motivo() {
        let mut q = Cuarentena::nueva();
        q.apartar("inst-x", "primero");
        q.apartar("inst-x", "segundo");
        assert_eq!(q.len(), 1);
        assert_eq!(q.motivo("inst-x"), Some("segundo"));
    }

    #[test]
    fn la_cuarentena_se_puede_recorrer() {
        let mut q = Cuarentena::nueva();
        q.apartar("a", "motivo a");
        q.apartar("b", "motivo b");
        let vistos: Vec<&String> = q.apartadas().map(|(k, _)| k).collect();
        assert_eq!(vistos, vec!["a", "b"], "orden determinista (BTreeMap)");
    }
}
