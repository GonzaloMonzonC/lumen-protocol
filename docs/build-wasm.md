# Build de WASM

`pkg/` es un **artefacto**: no va en git (está en `.gitignore`). Se regenera con:

```bash
bash scripts/build_wasm.sh
```

---

## El build de wasm NO es el build por defecto

Esto es el error nº1. Con los features de por defecto (`sqlite`, `minreq`,
`dll`), el build para `wasm32-unknown-unknown` **falla**, y el mensaje no dice
cuál es el problema real:

```
error: the wasm*-unknown-unknown targets are not supported by default,
       you may need to enable the "js" feature.
error: failed to run custom build command for `ring v0.17.14`
error: failed to run custom build command for `libsqlite3-sys v0.28.0`
```

**La causa es una cadena, no una dependencia suelta:**

```
minreq → rustls → ring → getrandom
```

`getrandom` no compila en `wasm32-unknown-unknown` sin el backend JS de
wasm-bindgen.

**La solución NO es añadir `getrandom = { features = ["js"] }` al
`Cargo.toml`.** Basta con excluir `minreq` del build:

```bash
cargo build --release --target wasm32-unknown-unknown \
  --no-default-features --features wasm
```

Con eso, `minreq` (y toda su cadena) sale del grafo y no hace falta tocar
ninguna dependencia. Verificado: el build limpio pasa sin parches.

---

## Lo que hace `scripts/build_wasm.sh`

1. Instala el target `wasm32-unknown-unknown` si falta.
2. Instala `wasm-bindgen-cli` **con la misma versión que el `Cargo.lock`**.
   Si no casan, el glue JS y el `.wasm` no se hablan y falla al instanciar con
   un error de imports.
3. Compila con `--no-default-features --features wasm`.
4. Genera `pkg/` con `wasm-bindgen`.

```bash
bash scripts/build_wasm.sh           # release
bash scripts/build_wasm.sh --debug   # debug, para depurar
```

---

## El test tenía un falso rojo (arreglado)

`test_wasm_vs_nativo.py` no comprobaba que existiera `pkg/`. Si faltaba, cada
caso terminaba en `ERR_MODULE_NOT_FOUND` y se contaba como **divergencia de
determinismo**:

```
FALLO: 11 caso(s) divergen -> entero, string, decimal exacto, ...
       WASM y nativo NO son intercambiables en esos casos.
```

Eso es falso y asusta: no hay ninguna divergencia, falta el artefacto.

**Ahora:**

| Situación | Qué dice | Exit |
|---|---|---|
| Falta `pkg/` | `NO EJECUTABLE: pkg/ no construido... ejecuta scripts/build_wasm.sh` | **2** |
| El wasm no ejecuta | `ERROR DE EJECUCIÓN en N casos` (separado de divergencia) | 1 |
| Digests distintos de verdad | `FALLO: N casos con digest DISTINTO` | 1 |
| Todo bien | `PASS: 11 casos, mismo digest` | 0 |

La distinción **error de ejecución ≠ digest distinto** importa: antes ambos
decían "diverge", y son problemas completamente distintos.

---

## Comprobar

```bash
cd implementations/rust/lumen-m-light
LUMEN_REPO=<ruta-repo> python test_wasm_vs_nativo.py
```

Cubre 11 casos, incluidos `0.1+0.2` (ULP), `1/3`, negativos, bucle con ramas,
subíndices anidados, varios namespaces y sobrescritura.

---

## El paquete del sitio web es otro

`ecos/site/sim/pkg/` es una **copia** con `--target web`. No la regenera este
script. Para el navegador:

```bash
cd implementations/rust/lumen-m-light
wasm-pack build --target web --no-default-features --features wasm
# wasm-pack escribe en pkg/ ; copiar a ecos/site/sim/pkg/
```

**Ojo:** `wasm-pack --out-dir <ruta>` falla en esta máquina. Sin `--out-dir`
usa `pkg/` y funciona.
