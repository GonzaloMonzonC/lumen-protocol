# MVM nativa: el motor M-Light en Linux

> Implementado el 21-nov-2026. Complementa a [`RAG-EMBEDDINGS.md`](RAG-EMBEDDINGS.md).

## WASM o nativa: cuándo cada una

El motor compila a dos destinos. No son alternativas excluyentes, sirven a
cosas distintas.

| | WASM (`pkg/`) | Nativa (`liblumen_mlight.so`) |
|---|---|---|
| Tamaño | **1,2 MB** | 6,5 MB |
| Arranque | milisegundos | milisegundos |
| Corre en | navegador, edge, nodos de 32 bits | Linux (contenedor, servidor) |
| Capacidades nuevas | implementar en Rust y recompilar | igual, pero cabe todo |
| Embeddings en proceso | **no** (modelo de 120 MB) | **sí** |
| Servicios externos | necesita un vectorizador aparte | ninguno |

**Regla práctica**:

- **WASM** si el objetivo es portabilidad: que el mismo motor funcione en un
  navegador, en un nodo de 32 bits y en un contenedor.
- **Nativa** si el objetivo es un servicio con todo dentro: menos piezas, menos
  contenedores, menos cosas que se caigan.

Para servir un buscador con embeddings, la nativa gana: **un contenedor en vez
de dos**.

## La API C

El `.so` exporta tres funciones:

```c
char *lm_compile_json(const char *source);
char *lm_execute_json(const char *request_json);
void  lm_string_free(char *value);
```

Las cadenas devueltas son del motor: hay que liberarlas con `lm_string_free`.
Olvidarlo es una fuga lenta que solo se nota en un servicio de larga vida.

### La petición

```json
{
  "program": { ...lo que devolvió lm_compile_json... },
  "globals": [ ...los globals de la llamada anterior... ],
  "gas_limit": 50000000
}
```

**Los globals se pasan en cada llamada.** El motor es sin estado: lo que
cargaste antes no existe ahora. Si no se pasan, `rag:embed:stats` responde
`vecs=0` y parece que el corpus no cargó, cuando lo que pasa es que se perdió.

**`gas_limit` explícito.** Sin él, cargar 341 trozos con sus 384 floats se
queda corto y devuelve los globals vacíos — el mismo síntoma, otra causa.

### La respuesta

```json
{
  "ok": true,
  "execution": "halted",
  "program": { ... },
  "state": {
    "output": "vecs=341;dim=384",
    "vars": {}, "ip": 6, ...
  },
  "globals": [ ... ]
}
```

⚠️ **La salida del `W` está en `state.output`, NO en la raíz.**

En la API WASM la respuesta trae `output` en la raíz. En la API C viene dentro
de `state`. Copiar código de una a otra sin mirar esto da `output = None` con
`ok = true`, que es el peor error posible: parece que funciona.

## Compilar

### Para Linux nativo (desde el propio Linux, o en Docker)

```bash
cd build-iso-i686/mlight-so
cargo build --release
# → target/release/liblumen_mlight.so
```

**La versión de Rust importa.** Con `rust:1.83` falla: `zeroize 1.9.2` exige la
feature `edition2024`, no estabilizada hasta 1.85. La máquina de desarrollo
usa 1.95. Si se sube el toolchain local, subir también el de la imagen.

### Para i686 (nodos de 32 bits)

```bash
bash build-i686-so-gnu.sh
# → build-iso-i686/mlight-so/target/i686-unknown-linux-gnu/release/liblumen_mlight.so
```

Usa `zigcc-i686` como compilador cruzado y **glibc**: musl no soporta `cdylib`.

### Compilar cruzado desde Windows a x86_64

No está soportado en esta máquina: falta `x86_64-linux-gnu-gcc`. Si hace falta,
la vía limpia es compilar dentro de la imagen de Docker (ver el Dockerfile de
ejemplo abajo), que es reproducible y no depende del toolchain local.

## Ejemplo: contenedor con motor + embeddings en un solo proceso

```dockerfile
FROM rust:1.95-slim AS motor
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY _motor/ /src/implementations/rust/lumen-m-light/
COPY _so/ /src/build-iso-i686/mlight-so/
RUN cd /src/build-iso-i686/mlight-so && cargo build --release \
    && mkdir -p /out && cp target/release/liblumen_mlight.so /out/

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastembed==0.8.0 numpy
COPY --from=motor /out/liblumen_mlight.so /app/
COPY servidor.py /app/
CMD ["python", "/app/servidor.py"]
```

`libgomp1` es necesario para onnxruntime (lo usa fastembed). Sin él, el modelo
no carga y el error no lo dice claramente.

## Envoltorio mínimo en Python

```python
import ctypes, json

m = ctypes.CDLL("/app/liblumen_mlight.so")
m.lm_compile_json.restype = ctypes.c_void_p
m.lm_compile_json.argtypes = [ctypes.c_char_p]
m.lm_execute_json.restype = ctypes.c_void_p
m.lm_execute_json.argtypes = [ctypes.c_char_p]
m.lm_string_free.argtypes = [ctypes.c_void_p]

def _coge(p):
    if not p:
        return ""
    try:
        return ctypes.string_at(p).decode("utf-8", "replace")
    finally:
        m.lm_string_free(p)

GLOBALS = []

def ejecuta(src: str) -> str:
    global GLOBALS
    program = json.loads(_coge(m.lm_compile_json(src.encode())))
    if program.get("error"):
        raise RuntimeError(program["error"])
    r = json.loads(_coge(m.lm_execute_json(json.dumps({
        "program": program,
        "globals": GLOBALS,
        "gas_limit": 50_000_000,
    }).encode())))
    if isinstance(r.get("globals"), list):
        GLOBALS = r["globals"]          # imprescindible: el motor no recuerda
    if r.get("error"):
        raise RuntimeError(r["error"])
    return (r.get("state") or {}).get("output", "")    # OJO: state.output
```

## Comprobación rápida

```bash
docker run --rm -v $PWD/datos:/datos:ro mi-mvm-native \
  python -c "
import json,urllib.request
print(json.loads(urllib.request.urlopen('http://127.0.0.1:8183/health').read()))
"
# → {"ok": true, "trozos": 341, "dim": 384, "error": null}
```

Si `ok` es `false` y `error` dice «esperaba N vecs, hay 0», el problema está en
la carga (globals perdidos o gas insuficiente), no en el corpus.
