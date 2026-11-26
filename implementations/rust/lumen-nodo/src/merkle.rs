//! Prueba de inclusión (árbol de Merkle) sobre los hechos de una serie.
//!
//! ## Qué problema resuelve
//!
//! La cadena de hashes ya prueba **completitud**: que no falta ningún hecho. Pero
//! para comprobarlo hay que tener **la serie entera**. Con 21.600 hechos de un
//! barco es viable; con un millón de un ledger, no.
//!
//! Merkle añade **prueba de inclusión**: demostrar que UN hecho concreto está en
//! el registro, sin entregar el registro. La prueba son **log2(n) hashes**.
//!
//! ```text
//! 21.600 hechos -> prueba de ~15 hashes (~960 bytes)
//!  1.000.000    -> prueba de ~20 hashes (~1.280 bytes)
//! ```
//!
//! ## Por qué no es otra estructura paralela
//!
//! La cadena de hashes **ya es** un árbol degenerado: cada hash depende del
//! anterior. El árbol de Merkle se construye con **esos mismos hashes**, así que
//! no hay dos fuentes de verdad ni dos cosas que mantener.
//!
//! ## Qué NO prueba
//!
//! Merkle prueba **inclusión**, no **autoría**. Que un hecho esté en el árbol no
//! dice quién lo firmó: eso lo sigue dando Ed25519. Son dos comprobaciones
//! distintas y las dos hacen falta.
//!
//! Tampoco prueba que el árbol no se haya reconstruido desde cero: para eso está
//! la custodia de epoch y los sellos firmados.

use crate::cadena::sha256_hex;

/// Un nodo del árbol, ya calculado.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArbolMerkle {
    /// Hashes de las hojas (en orden: posición 0, 1, 2, …).
    hojas: Vec<String>,
    /// Niveles: `niveles[0]` son las hojas, `niveles[last]` es la raíz sola.
    niveles: Vec<Vec<String>>,
}

impl ArbolMerkle {
    /// Construye el árbol a partir de los hashes de los hechos, **en orden**.
    ///
    /// El orden importa: el mismo conjunto de hashes en otro orden da otra raíz.
    /// Eso es lo que impide que alguien reordene el registro sin que se note.
    pub fn nuevo(hashes: &[String]) -> Self {
        if hashes.is_empty() {
            return Self { hojas: Vec::new(), niveles: vec![Vec::new()] };
        }

        let mut niveles: Vec<Vec<String>> = Vec::new();
        niveles.push(hashes.to_vec());

        let mut actual = hashes.to_vec();
        while actual.len() > 1 {
            let mut siguiente = Vec::with_capacity((actual.len() + 1) / 2);
            for par in actual.chunks(2) {
                let h = match par.len() {
                    2 => hijo(&par[0], &par[1]),
                    // Número impar de nodos: el último sube tal cual.
                    //
                    // Esto NO es lo que hace Bitcoin (que duplica el último).
                    // Duplicar es más barato pero permite una colisión conocida
                    // (CVE-2012-2459): dos conjuntos distintos con la misma raíz.
                    // Subirlo sin tocar no tiene ese problema.
                    _ => par[0].clone(),
                };
                siguiente.push(h);
            }
            niveles.push(siguiente.clone());
            actual = siguiente;
        }

        Self { hojas: hashes.to_vec(), niveles }
    }

    /// La raíz del árbol. Es lo único que hay que publicar para poder verificar.
    pub fn raiz(&self) -> String {
        self.niveles
            .last()
            .and_then(|n| n.first())
            .cloned()
            .unwrap_or_else(|| "0".repeat(64))
    }

    pub fn hojas(&self) -> &[String] {
        &self.hojas
    }

    pub fn len(&self) -> usize {
        self.hojas.len()
    }

    pub fn esta_vacio(&self) -> bool {
        self.hojas.is_empty()
    }

    /// Genera la prueba de que el hecho de la posición `indice` está en el árbol.
    ///
    /// Devuelve los hashes hermanos de abajo arriba, con la posición de cada uno
    /// (izquierda o derecha) para poder recomponer el camino.
    pub fn prueba(&self, indice: usize) -> Option<PruebaInclusion> {
        if indice >= self.hojas.len() {
            return None;
        }
        let mut camino = Vec::new();
        let mut idx = indice;

        for nivel in &self.niveles {
            if nivel.len() <= 1 {
                break;
            }
            let hermano = if idx % 2 == 0 { idx + 1 } else { idx - 1 };
            // Si el hermano no existe (número impar), no se aporta nada: el nodo
            // sube tal cual.
            if hermano < nivel.len() {
                camino.push((nivel[hermano].clone(), idx % 2 == 1));
            }
            idx /= 2;
        }

        Some(PruebaInclusion {
            indice,
            hash_hoja: self.hojas[indice].clone(),
            camino,
            raiz: self.raiz(),
            total_hojas: self.hojas.len(),
        })
    }
}

/// Prueba de que un hecho está en el árbol.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PruebaInclusion {
    /// Posición del hecho en la serie.
    pub indice: usize,
    /// El hash del hecho (la hoja).
    pub hash_hoja: String,
    /// Hermanos del camino, de abajo arriba: (hash, ¿está a la izquierda?).
    pub camino: Vec<(String, bool)>,
    /// La raíz contra la que se comprueba.
    pub raiz: String,
    /// Cuántas hojas tenía el árbol (para detectar pruebas de otro árbol).
    pub total_hojas: usize,
}

impl PruebaInclusion {
    /// Tamaño de la prueba en bytes (32 por hash + separadores).
    pub fn bytes(&self) -> usize {
        self.camino.len() * (64 + 1)
    }

    /// Comprueba que la prueba lleva a la raíz declarada.
    ///
    /// **Solo comprueba matemática, no autoría.** El hash de la hoja se da por
    /// bueno: quien quiera saber si el hecho es auténtico tiene que verificar
    /// además su firma Ed25519.
    pub fn verificar(&self) -> bool {
        if self.total_hojas == 0 {
            return false;
        }
        let mut actual = self.hash_hoja.clone();
        let mut idx = self.indice;

        for (hermano, hermano_izquierda) in &self.camino {
            actual = if *hermano_izquierda {
                hijo(hermano, &actual)
            } else {
                hijo(&actual, hermano)
            };
            idx /= 2;
        }

        actual == self.raiz
    }
}

/// Hash de un nodo interno: sha256(izquierda || derecha).
///
/// Se usa un separador de un byte entre ambos para que `hijo(a, b)` no pueda
/// colisionar con `hijo(c, d)` por concatenación (`"ab"+"c"` vs `"a"+"bc"`).
fn hijo(izq: &str, der: &str) -> String {
    let mut datos = Vec::with_capacity(izq.len() + der.len() + 1);
    datos.extend_from_slice(izq.as_bytes());
    datos.push(b'\x1f');
    datos.extend_from_slice(der.as_bytes());
    sha256_hex(&datos)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hashes(n: usize) -> Vec<String> {
        (0..n).map(|i| sha256_hex(format!("hecho-{i}").as_bytes())).collect()
    }

    #[test]
    fn un_solo_hecho_tiene_por_raiz_su_propio_hash() {
        let h = hashes(1);
        let a = ArbolMerkle::nuevo(&h);
        assert_eq!(a.raiz(), h[0]);
        let p = a.prueba(0).expect("prueba");
        assert_eq!(p.camino.len(), 0);
        assert!(p.verificar(), "la prueba de un solo hecho debe verificar");
    }

    #[test]
    fn cien_hechos_dan_pruebas_que_verifican() {
        let h = hashes(100);
        let a = ArbolMerkle::nuevo(&h);
        for i in 0..100 {
            let p = a.prueba(i).expect("prueba");
            assert!(p.verificar(), "la prueba del hecho {i} debe verificar");
        }
    }

    #[test]
    fn la_prueba_es_logaritmica_no_lineal() {
        // 21.600 hechos -> la prueba debe ser de ~15 hashes, no de 21.600.
        let h = hashes(21_600);
        let a = ArbolMerkle::nuevo(&h);
        let p = a.prueba(12_345).expect("prueba");
        assert!(p.verificar());
        assert!(
            p.camino.len() <= 16,
            "prueba de {} hashes para 21.600 hechos: debe ser ~15",
            p.camino.len()
        );
        assert!(
            p.bytes() < 1200,
            "la prueba ocupa {} bytes: debe caber en un mensaje",
            p.bytes()
        );
    }

    #[test]
    fn cambiar_un_hecho_rompe_su_prueba() {
        let h = hashes(50);
        let a = ArbolMerkle::nuevo(&h);
        let mut p = a.prueba(7).expect("prueba");
        assert!(p.verificar());
        // Manipular el hash de la hoja.
        p.hash_hoja = sha256_hex(b"manipulado");
        assert!(!p.verificar(), "un hecho cambiado no debe poder probarse");
    }

    #[test]
    fn cambiar_un_hermano_rompe_la_prueba() {
        let h = hashes(50);
        let a = ArbolMerkle::nuevo(&h);
        let mut p = a.prueba(7).expect("prueba");
        p.camino[0].0 = sha256_hex(b"otro");
        assert!(!p.verificar(), "un hermano cambiado invalida el camino");
    }

    #[test]
    fn reordenar_cambia_la_raiz() {
        // Esto es lo que impide reordenar el registro sin que se note.
        let h = hashes(10);
        let a = ArbolMerkle::nuevo(&h);
        let mut rev = h.clone();
        rev.reverse();
        let b = ArbolMerkle::nuevo(&rev);
        assert_ne!(a.raiz(), b.raiz(), "otro orden debe dar otra raiz");
    }

    #[test]
    fn el_mismo_conjunto_da_siempre_la_misma_raiz() {
        let h = hashes(37);
        assert_eq!(ArbolMerkle::nuevo(&h).raiz(), ArbolMerkle::nuevo(&h).raiz());
    }

    #[test]
    fn un_numero_impar_de_hojas_no_duplica_el_ultimo() {
        // La trampa CVE-2012-2459: si el ultimo se duplica, dos conjuntos
        // distintos pueden dar la misma raiz. Aqui el ultimo sube tal cual.
        let cinco = hashes(5);
        let a = ArbolMerkle::nuevo(&cinco);
        // Con duplicado, 5 y 6 hojas podrian colisionar. Comprobamos que la
        // raiz de 5 no coincide con la de 5+duplicado explicito.
        let mut con_dup = cinco.clone();
        con_dup.push(cinco[4].clone());
        let b = ArbolMerkle::nuevo(&con_dup);
        assert_ne!(a.raiz(), b.raiz(), "5 hojas y 5+duplicado NO deben coincidir");
    }

    #[test]
    fn una_prueba_de_otro_arbol_no_vale() {
        let a = ArbolMerkle::nuevo(&hashes(20));
        let b = ArbolMerkle::nuevo(&hashes(21));
        let mut p = a.prueba(3).expect("prueba");
        p.raiz = b.raiz();
        assert!(!p.verificar(), "una prueba no vale contra la raiz de otro arbol");
    }

    #[test]
    fn indice_fuera_de_rango_no_da_prueba() {
        let a = ArbolMerkle::nuevo(&hashes(10));
        assert!(a.prueba(10).is_none());
        assert!(a.prueba(999).is_none());
    }

    #[test]
    fn arbol_vacio_no_revienta() {
        let a = ArbolMerkle::nuevo(&[]);
        assert!(a.esta_vacio());
        assert!(a.prueba(0).is_none());
        assert_eq!(a.raiz(), "0".repeat(64));
    }

    #[test]
    fn el_separador_evita_colisiones_de_concatenacion() {
        // ("ab","c") y ("a","bc") deben dar hashes distintos.
        assert_ne!(hijo("ab", "c"), hijo("a", "bc"));
    }
}
