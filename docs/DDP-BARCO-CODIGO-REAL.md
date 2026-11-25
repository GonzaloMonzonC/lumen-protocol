# Replicación de hechos — perfil de barco en código real

> 2026-11-24. Lleva el prototipo a producción: **firma Ed25519 real, perfil
> desde fichero, cadena de hashes real.**
> Código en `implementations/rust/lumen-nodo/src/replicacion.rs`.

---

## 1 · Qué se ha construido

| Pieza | Antes (prototipo Python) | Ahora (Rust) |
|---|---|---|
| Firma | hash simulado | **Ed25519 real** (`ed25519-dalek`) |
| Perfil | diccionario Python | **fichero JSON** validado |
| Cadena | hash propio | **`cadena::hash_muestra`**, el módulo real |
| Identidad | nombre en texto | **clave pública Ed25519** |

## 2 · El perfil, ahora es un fichero

`implementations/rust/lumen-nodo/perfiles/`:

```json
{
  "retencion_modo": "ventana",
  "retencion_horas": 168,
  "replicacion": "flota",
  "firma": "por_bloque",
  "firma_bloque_n": 100,
  "compactacion": "sellos",
  "conflicto": "ultimo_gana"
}
```

Cuatro ficheros: `barco.json`, `enjambre.json`, `ledger.json`, `config.json`.
**Todos cargan y validan** (test `todos_los_perfiles_json_cargan_y_validan`).

`validar()` rechaza combinaciones incoherentes: ventana sin horas, interés sin
lista de series, firma por bloque con tamaño 0, etc.

## 3 · Banco de escenarios: barco, con criptografía real

```
cargo test --release --test banco_barco -- --nocapture
```

Resultado sobre **21.600 muestras** (6 h a 1 Hz):

```
[OK] el hub recibe todas las muestras        -> 21600 de 21600
[OK] firma por bloque, no por hecho          -> 216 firmas para 21600 muestras
[OK] cadena intacta sin huecos
[OK] todas las firmas verifican con la clave del barco
[OK] una muestra de un impostor se rechaza
[OK] manipular rompe cadena Y firma
[OK] el ultimo hecho se conserva al compactar -> seq=21599
[OK] el estado es el ultimo valor             -> lat=41.021599

escritura de 21600 muestras firmadas: 239,0 ms
firmas Ed25519 reales: 216
```

**El número que hace viable el caso de uso: 216 firmas Ed25519 para 21.600
muestras.** Con firma por hecho serían 21.600 firmas; el barco no puede.
Con firma por bloque de 100, sí.

## 4 · Decisiones que se ven ahora en código

### 4.1 El nodo va DENTRO de la identidad del hecho

```rust
pub fn identidad(&self) -> (String, String, u64) {
    (self.nodo.clone(), self.serie.clone(), self.seq)
}
```

Sin el nodo, dos barcos con `seq=0` colisionan y uno se pierde. Fue el fallo
que apareció al ejecutar el prototipo.

### 4.2 El contenido firmado usa separador, no concatenación

```rust
format!("{}\x1f{}\x1f{}...", nodo, serie, seq, ...)
```

Con concatenación simple, `("ab","c")` y `("a","bc")` dan los mismos bytes y la
misma firma. Con `\x1f` no. Hay test: `el_separador_evita_colisiones_de_concatenacion`.

### 4.3 La compactación no se come el último hecho

Regla heredada del prototipo: si se tira el último hecho de una serie, el nodo
queda sin estado. Verificado en el banco: `seq=21599` sobrevive.

## 5 · Verificado

```
cargo test                        → 140 tests + los nuevos, todos verdes
cargo test --test banco_barco     → 3 tests, 8 criterios OK
cargo test --test perfiles_json   → 4 perfiles cargan y validan
```

Tests nuevos en `replicacion.rs`:
- `los_cuatro_perfiles_son_validos`
- `un_perfil_incoherente_se_rechaza`
- `el_perfil_va_y_vuelve_por_json`
- `la_firma_ed25519_verifica_y_detecta_manipulacion`
- `un_impostor_no_puede_firmar_como_el_barco`
- `el_separador_evita_colisiones_de_concatenacion`

## 6 · Lo que AÚN falta (siguiente tramo)

Sigue sin estar, y no lo disimulo:

1. **Transporte por `lumen-znet`.** El banco construye la serie en memoria y la
   "recibe" en el mismo proceso. Falta mandarla por el cable y verificar al
   llegar. `lumen-znet` ya funciona; lo que falta es el pegamento.
2. **Persistencia.** Los hechos viven en un `Vec`. Falta escribirlos en la PDB
   (tabla `_hechos`) para que sobrevivan al reinicio.
3. **Compactación real sobre disco.** Hoy está probada en memoria.
4. **Verificación de flota completa.** `verificar_firma` usa la clave del barco;
   falta el paso de comprobar que esa clave está firmada por la raíz del armador
   (`identidad::verificar_miembro`, que ya existe).
5. **Split-brain.** Sin probar.

## 7 · Orden propuesto

1. Persistir hechos en PDB (tabla `_hechos` con índice `(nodo, serie, seq)`).
2. Transporte real por `lumen-znet`.
3. Verificación de flota de punta a punta.
4. Compactación sobre disco.
5. Split-brain.

Los puntos 1 y 2 son los que convierten esto en algo usable. El 3 es el que
hace que valga para el paper: **probar que el dato viene de un barco de mi flota,
no solo que alguien con una clave lo firmó.**
