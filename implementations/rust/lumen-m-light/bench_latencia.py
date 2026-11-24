#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_latencia.py — banco de LATENCIA de cola del motor LUMEN.

Por qué existe: los documentos de especificación afirman latencias que el repo
nunca midió (papers hablan de "sub-microsegundos" y "p99.99"). Este banco mide
lo que hay de verdad, con los percentiles que se usan para defender una
afirmación de tiempo real: p50, p95, p99, p99.9 y jitter.

Metodología (importa para que las cifras valgan):
  - reloj: perf_counter_ns (nanosegundos, monotónico).
  - warmup antes de medir, para que no puntúe la primera compilación.
  - muestras ordenadas; los percentiles se toman por índice, no interpolando,
    así el p99.9 es una muestra REALMENTE observada y no una media inventada.
  - jitter = p99 - p50. No es desviación típica: es la cola que rompe un lazo
    de control, que es lo que de verdad se sufre.
  - se reporta también max, porque en tiempo real el peor caso es el que
    tumba un SLA.

Uso:
    python bench_latencia.py [--iters N] [--salida fichero.json]

`--iters` bajo (por defecto) para que corra en segundos; súbelo para publicar.
"""

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
sys.path.insert(0, str(REPO / "implementations" / "python" / "pdb-sync"))
sys.path.insert(0, str(REPO / "implementations" / "mcp-servers" / "pdb"))

# El cdylib puede ser mas viejo que algun .rs (el repo se toca a menudo) y
# ensure_built() intentaria recompilar, que no siempre es lo que se quiere para
# MEDIR. Si el artefacto existe, se usa tal cual: medimos el que hay desplegado.
_LIB = HERE / "target" / "release" / {
    "darwin": "liblumen_mlight.dylib",
    "linux": "liblumen_mlight.so",
}.get(sys.platform, "lumen_mlight.dll")
if _LIB.exists() and not os.environ.get("LUMEN_MLIGHT_LIB"):
    os.environ["LUMEN_MLIGHT_LIB"] = str(_LIB)

try:
    from lumen_mlight import compile_source, ensure_built, execute  # noqa: E402
except Exception as e:  # noqa: BLE001
    print("No se pudo cargar el motor: %s" % e)
    print("Compila primero:  cargo build --release --features minreq")
    raise SystemExit(2)


def pct(muestras_ordenadas, p):
    """Percentil por índice: devuelve una muestra observada, no una interpolación."""
    if not muestras_ordenadas:
        return 0.0
    i = int(round((len(muestras_ordenadas) - 1) * p))
    return muestras_ordenadas[max(0, min(i, len(muestras_ordenadas) - 1))]


def medir(fn, iters, warmup=50):
    """Mide fn() y devuelve la distribución completa en microsegundos."""
    for _ in range(warmup):
        fn()
    xs = []
    for _ in range(iters):
        t0 = time.perf_counter_ns()
        fn()
        xs.append((time.perf_counter_ns() - t0) / 1000.0)  # ns -> µs
    xs.sort()
    p50 = pct(xs, 0.50)
    p99 = pct(xs, 0.99)
    return {
        "iters": iters,
        "p50_us": round(p50, 3),
        "p95_us": round(pct(xs, 0.95), 3),
        "p99_us": round(p99, 3),
        "p999_us": round(pct(xs, 0.999), 3),
        "max_us": round(xs[-1], 3),
        "min_us": round(xs[0], 3),
        "jitter_us": round(p99 - p50, 3),
        "media_us": round(statistics.fmean(xs), 3),
        "ops_s": round(1_000_000 / p50) if p50 > 0 else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=2000)
    ap.add_argument("--salida", default=str(HERE / "bench_latencia.json"))
    args = ap.parse_args()

    if not ensure_built(quiet=True):
        print("El cdylib de Rust no está disponible.")
        raise SystemExit(2)

    # Programas de prueba. Se separa COMPILAR de EJECUTAR a propósito: el banco
    # viejo (benchmark.py) medía solo compile_source() y sus cifras no son
    # comparables con ejecutar. Mezclarlos es el error que hace que un documento
    # acabe afirmando una latencia que nadie midió.
    CASOS = [
        ("compile_1_linea", lambda: compile_source("S x=42"), 20,
         "compilar una instrucción (sin ejecutar)"),
        ("compile_4_lineas", lambda: compile_source("S x=42\nS y=x+1\nS z=y*2\nW z"), 20,
         "compilar un bloque mínimo (sin ejecutar)"),
        ("ejecutar_1_set", lambda: execute("S x=42", gas_limit=20), 20,
         "compilar + ejecutar una asignación"),
        ("math", lambda: execute("W 2+3*4", gas_limit=20), 20,
         "aritmética (compilar + ejecutar)"),
        ("for_100", lambda: execute("S t=0\nF i=1:1:100 { S t=t+i }", gas_limit=1000), 1000,
         "bucle de 100 iteraciones"),
        ("global_set_get", lambda: execute('S ^B("k")="v"\nW $G(^B("k"))', gas_limit=100), 100,
         "escritura y lectura de global"),
        ("order_10", lambda: execute('S k=$O(^C(""))', gas_limit=100), 100,
         "navegación $ORDER"),
    ]

    print("=" * 78)
    print("BANCO DE LATENCIA — motor LUMEN M-Light (Rust)")
    print("=" * 78)
    print("plataforma: %s" % platform.platform())
    print("máquina:    %s" % platform.machine())
    print("iters:      %d por caso" % args.iters)
    print()
    print("AVISO: estas cifras incluyen la frontera Python→FFI→motor→vuelta, que es")
    print("lo que ve un servicio real. El motor puro es más rápido; este banco mide")
    print("lo que se puede defender delante de un cliente.")
    print()
    hdr = "%-20s %9s %9s %9s %9s %9s %9s" % (
        "caso", "p50 µs", "p95 µs", "p99 µs", "p99.9 µs", "jitter", "ops/s")
    print(hdr)
    print("-" * len(hdr))

    metricas = {}
    for nombre, fn, gas, desc in CASOS:
        try:
            r = medir(fn, args.iters)
        except Exception as e:  # noqa: BLE001
            print("%-20s ERROR: %s" % (nombre, e))
            continue
        r["descripcion"] = desc
        metricas[nombre] = r
        print("%-20s %9.1f %9.1f %9.1f %9.1f %9.1f %9d" % (
            nombre, r["p50_us"], r["p95_us"], r["p99_us"],
            r["p999_us"], r["jitter_us"], r["ops_s"]))

    informe = {
        "schema": "lumen-latencia-v1",
        "que_mide": "latencia de cola del motor M-Light a través de su frontera FFI, en microsegundos",
        "aviso": "incluye el coste de la frontera Python->FFI. El motor puro es mas rapido.",
        "metodologia": {
            "reloj": "perf_counter_ns",
            "warmup": 50,
            "percentiles": "por índice sobre muestras ordenadas (valores observados)",
            "jitter": "p99 - p50 (cola, no desviación típica)",
            "unidad": "microsegundos",
            "compilar_vs_ejecutar": "casos separados a proposito; no son comparables",
        },
        "entorno": {
            "plataforma": platform.platform(),
            "maquina": platform.machine(),
            "python": platform.python_version(),
        },
        "metricas": metricas,
    }
    Path(args.salida).write_text(
        json.dumps(informe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print()
    print("Guardado en: %s" % args.salida)
    print()
    print("Recuerda: estas cifras son las que se pueden defender. Si un documento")
    print("afirma 'sub-microsegundos' o 'p99.99' y aquí sale otra cosa, el")
    print("documento está mal, no el banco.")


if __name__ == "__main__":
    main()
