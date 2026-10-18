# Digest canónico y determinismo cruzado

Proyección canónica del estado de la MVM para **replay verificable**, y test de
equivalencia **WASM ↔ nativo**.

---

## 1. El problema que resuelve

El `state` que devuelve la MVM incluye `zh_start` (timestamp de arranque) y
`rng_state`. Por eso dos ejecuciones del mismo programa dan digests distintos:

```
run 1: 4813ed05e30419e6   zh_start=1792304652.0856464
run 2: 5bbde3602b6452a1   zh_start=1792304652.0861535
run 3: 88ecc84c7e470b25   zh_start=1792304652.0864230
run 4: 2d5b14b04b48078d   zh_start=1792304652.0866644
```

El `program_hash` **sí** es estable, pero es el hash del **código**, no del estado.
No sirve como certificado de replay.

Esto bloquea el producto de "caja negra de agentes" (doc `15` del estudio), que
es el que se apoya en poder demostrar que una decisión se re-ejecuta igual.

---

## 2. La proyección

Se hashea **solo** esto, en orden canónico:

```
ns ␟ subkeys ␟ valor(valor_canónico)
```

Y se excluye **todo** lo demás: `zh_start`, `rng_state`, `fibers`, `ip`, `stack`,
PIDs, timestamps.

### Valor canónico

| tipo | normalización |
|---|---|
| número | 12 cifras significativas (`format(v, ".12g")`) |
| entero exacto | sin `.0` (`3.0` → `"3"`) |
| `-0.0` | `"0"` (mismo valor que `0.0`) |
| `nan` / `inf` / `-inf` | marcadores explícitos, distinguibles |
| string | tal cual |
| `None`/`undefined` | marcador `\x00none` (no colisiona con strings) |

**Por qué 12 cifras:** absorbe el ruido de coma flotante. `0.1+0.2` da
`0.30000000000000004` en crudo, y con la proyección da el mismo digest que `0.3`.
Sin esto, un ULP rompe el certificado.

Si algún día se necesita exactitud decimal real (dinero), esto tiene que pasar a
`Decimal`, no a `float`.

---

## 3. Uso

```python
from digest_canonico import digest_de_globals, digest_de_ejecucion, diff_estados

r = L.execute("S ^A(1)=1")
digest_de_globals(r["globals"])       # digest del ESTADO
digest_de_ejecucion(prog, r)          # digest de (programa + estado)
diff_estados(g1, g2)                  # QUÉ cambió, línea a línea
```

`diff_estados` es la pieza del "diff de políticas" del doc `15`: cambiar una regla
y ver **qué** decisiones habrían cambiado, no solo que el digest difiere.

### Versionado

`VERSION = "1"` va dentro del hash. Si cambia la proyección, sube la versión y
**todos los certificados viejos quedan invalidados a propósito**. Eso es lo
correcto: un certificado que se validara con otra proyección estaría mintiendo.

---

## 4. Determinismo cruzado WASM ↔ nativo

El doc `01` §4 afirma: *"un solo código de simulación para cliente y servidor.
Nada de reimplementar reglas en C# o TS"*. Eso solo vale si los dos motores dan
el mismo resultado. **No estaba comprobado.**

Medido, 11 casos:

| caso | nativo | wasm |
|---|---|---|
| entero | `a652cdfa…` | `a652cdfa…` |
| string | `5266cb0b…` | `5266cb0b…` |
| decimal exacto | `259ed13e…` | `259ed13e…` |
| **1/3** | `2642a2f7…` | `2642a2f7…` |
| **0.1+0.2 (ULP)** | `b71c1b59…` | `b71c1b59…` |
| negativo | `2c35a800…` | `2c35a800…` |
| bucle + ramas | `bfee8c06…` | `bfee8c06…` |
| anidado | `740145dc…` | `740145dc…` |
| varios ns | `fe0a1399…` | `fe0a1399…` |
| sobrescritura | `dbec9c56…` | `dbec9c56…` |
| string largo | `9639daab…` | `9639daab…` |

**11/11 idénticos.** La premisa del `01` se sostiene al menos en estos casos.

Verificado también que **discrimina**: `^A(1)=1`, `^A(1)=2` y `^B(1)=1` dan tres
digests distintos. Si el test diera siempre igual, no probaría nada.

---

## 5. Trampas de la API WASM (encontradas a base de golpes)

Esta es la parte que hará perder una tarde a quien venga después.

### `m_compile` devuelve `Uint8Array`, no un objeto

Devuelve el JSON serializado **byte a byte**. `JSON.parse` directo produce un
objeto con claves `"0"`, `"1"`, `"2"`… y 200 elementos:

```js
// MAL
const c = JSON.parse(mod.m_compile(prog));   // -> {"0":123,"1":34,...}

// BIEN
const bytes = mod.m_compile(prog);           // Uint8Array
const c = JSON.parse(Buffer.from(bytes).toString('utf8'));
```

### `m_execute` espera bytecode, no fuente ni JSON

La API es de más bajo nivel que el motor nativo. El nativo recibe
`{"source": ..., "globals": [...], ...}` y devuelve todo. El WASM recibe el
**bytecode compilado** y devuelve solo el texto de salida.

**La que devuelve el estado completo es `m_execute_raw(compiled, globals_json)`.**
Con `m_execute` el resultado es un string vacío y `globals` sale a 0 — un fallo
silencioso que parece "no hay estado" en vez de "función equivocada".

### El segundo argumento es un ARRAY JSON, no un objeto

```js
mod.m_execute_raw(bytes, '{}')   // Parse globals JSON: invalid type: map, expected a sequence
mod.m_execute_raw(bytes, '[]')   // OK
```

### En Windows, `import()` necesita URL `file://`

```js
import(join(dir, 'pkg', 'lumen_mlight.js'))                    // ERR_UNSUPPORTED_ESM_URL_SCHEME
import(pathToFileURL(join(dir, 'pkg', 'lumen_mlight.js')).href) // OK
```

### Hay que inicializar wasm-bindgen antes

El export por defecto es la función de init:

```js
const mod = await import(pkgUrl);
await mod.default({ module_or_path: readFileSync(wasmPath) });
```

---

## 6. Los tests

```bash
LUMEN_REPO=~/Documents/GitHub/lumen-protocol python test_digest_reproducible.py
LUMEN_REPO=~/Documents/GitHub/lumen-protocol python test_wasm_vs_nativo.py
```

`test_digest_reproducible.py` — 8 comprobaciones:
1. el `state` crudo **no** es reproducible (el problema, demostrado)
2. el digest canónico **sí** lo es (la solución)
3. discrimina entre estados distintos
4. absorbe el ULP (`0.1+0.2` == `0.3`)
5. sensible a cambios reales de valor
6. estable ante distinto orden de escritura
7. `diff_estados` dice qué cambió
8. el digest de ejecución incluye el programa

`test_wasm_vs_nativo.py` — 11 casos, compara digests entre los dos motores.

---

## 7. Lo que esto NO resuelve

- **No decide el contrato de replay completo.** El digest cubre el estado; un
  certificado necesita además: versión de reglas, versión de modelo, y las
  respuestas LLM cacheadas. El doc `15` lo pide y aquí no está.
- **No mide rendimiento.** El WASM es más lento (el doc `01` estima 1,5–3×); no
  lo he medido aquí.
- **Los 11 casos son sintéticos.** No cubre todas las construcciones de M: faltan
  `$P` con separadores raros, `$ORDER`, locks, `$DEVICE`, `yield`/`resume`.
- **No he comprobado qué pasa con el `rng_state`.** Si un programa usa aleatoriedad,
  dos ejecuciones divergen por diseño. Eso necesita semilla explícita, y no está.
