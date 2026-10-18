#!/usr/bin/env python3
"""test_web_extract_h5.py — H5

Tres defectos medidos en el extractor de `web`:
  1. Sin readability: dejaba la navegacion (4.051 palabras de menus en un repo de
     GitHub donde habia ~400 utiles).
  2. `title` se buscaba DESPUES de borrar los tags -> caia siempre al URL.
  3. `content_type = "text/html"  # assumed` -> un JSON se "extraia" como HTML.

Todo con FIXTURE local: sin red, valido en CI.
    python test_web_extract_h5.py [-v]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "tests" / "fixtures"

# Frases que solo aparecen en la navegacion / boilerplate del fixture.
NAV_MARKERS = ["Skip to content", "Branches", "Go to file", "Pull requests",
               "Insights", "Terms", "Privacy", "Sign up", "Watching 12"]
# Frases que son el contenido real.
REAL_MARKERS = ["cognitive operating system", "MUMPS heritage",
                "transport-agnostic", "survive context compression"]


def find_server():
    for parent in Path(__file__).resolve().parents:
        cand = parent / "implementations/mcp-servers/web/server.py"
        if cand.is_file():
            return cand.parent
    return Path.home() / "Documents/GitHub/lumen-protocol/implementations/mcp-servers/web"


def load_module(webdir):
    sys.path.insert(0, str(webdir))
    import importlib
    return importlib.import_module("server")


def fake_fetch_factory(payload, ctype):
    """Sustituye _safe_fetch_typed para no tocar la red."""
    def _fake(url, *a, **kw):
        return payload, ctype
    return _fake


def main():
    verbose = "-v" in sys.argv
    webdir = find_server()
    if not (webdir / "server.py").is_file():
        print(f"SKIP: no encuentro {webdir}/server.py")
        return 0

    fixture = FIXTURES / "github_repo_divnav.html"
    if not fixture.is_file():
        print(f"SKIP: falta el fixture {fixture}")
        return 0

    html = fixture.read_text(encoding="utf-8")
    mod = load_module(webdir)

    fails = []
    st = mod._extractor_status()
    print(f"extractor disponible: {st['name']}" + (f" ({st['detail']})" if st["detail"] else ""))
    if st["name"] != "trafilatura":
        fails.append("trafilatura no esta instalada: el test no puede validar H5 de verdad")

    # ── 1. HTML: sin navegacion, con contenido, y title correcto ──
    mod._safe_fetch_typed = fake_fetch_factory(html.encode("utf-8"), "text/html; charset=utf-8")
    r = mod._extract_page("https://example.com/GonzaloMonzonC/lumen-protocol", max_chars=5000)

    if verbose:
        print(json.dumps({k: (v[:220] if isinstance(v, str) else v) for k, v in r.items()},
                         indent=2, ensure_ascii=False))

    content = r.get("content", "")
    words = content.split()

    nav_hits = [m for m in NAV_MARKERS if m.lower() in content.lower()]
    nav_ratio = (len(nav_hits) / len(NAV_MARKERS)) if NAV_MARKERS else 0
    print(f"  palabras totales : {len(words)}  (word_count={r.get('word_count')})")
    print(f"  marcadores nav   : {len(nav_hits)}/{len(NAV_MARKERS)} -> {nav_hits}")
    if nav_hits:
        fails.append(f"quedan {len(nav_hits)} marcadores de navegacion: {nav_hits}")

    real_hits = [m for m in REAL_MARKERS if m.lower() in content.lower()]
    print(f"  contenido real   : {len(real_hits)}/{len(REAL_MARKERS)}")
    if len(real_hits) < 3:
        fails.append(f"solo {len(real_hits)}/{len(REAL_MARKERS)} frases de contenido real: "
                     f"el extractor se come el articulo")

    # Los comentarios HTML no deben filtrarse al texto.
    if "es lo que GitHub sirve" in content:
        fails.append("el texto de un comentario HTML acaba en el contenido")

    # ── 2. title extraido antes de mutar el HTML ──
    title = r.get("title", "")
    print(f"  title            : {title[:80]!r}")
    if title.startswith("http") or title == r.get("url"):
        fails.append(f"title cae al URL ({title!r}): se extrae despues de borrar los tags")
    elif "lumen" not in title.lower():
        fails.append(f"title no parece el del documento: {title!r}")

    # ── 3. el extractor se declara en la respuesta ──
    if r.get("extractor") != "trafilatura":
        fails.append(f"extractor declarado = {r.get('extractor')!r}, esperado 'trafilatura'")
    if "content_type" not in r:
        fails.append("la respuesta no expone content_type")

    # ── 4. Content-Type JSON: devolver tal cual, no "extraer" HTML ──
    payload = json.dumps({"ok": True, "items": [1, 2, 3]})
    mod._safe_fetch_typed = fake_fetch_factory(payload.encode("utf-8"), "application/json")
    rj = mod._extract_page("https://example.com/api", max_chars=5000)
    if verbose:
        print("  json ->", json.dumps(rj, ensure_ascii=False)[:200])
    if rj.get("extractor") != "raw-json":
        fails.append(f"un JSON no se devuelve tal cual (extractor={rj.get('extractor')!r})")
    if '"ok"' not in (rj.get("content") or ""):
        fails.append("el contenido JSON se perdio al 'extraerlo'")

    # ── 5. PDF: error claro, no HTML inventado ──
    mod._safe_fetch_typed = fake_fetch_factory(b"%PDF-1.4 fake", "application/pdf")
    rp = mod._extract_page("https://example.com/doc.pdf")
    if not rp.get("error"):
        fails.append(f"un PDF no da error claro: {rp.get('content', '')[:80]!r}")

    # ── 6. truncated coherente con word_count ──
    mod._safe_fetch_typed = fake_fetch_factory(html.encode("utf-8"), "text/html")
    rt = mod._extract_page("https://example.com/x", max_chars=80)
    if not rt.get("truncated"):
        fails.append("con max_chars=80 deberia marcar truncated=true")
    if rt.get("word_count", 0) <= 80:
        fails.append(f"word_count ({rt.get('word_count')}) deberia ser del ORIGINAL, "
                     f"no del texto truncado")

    print()
    if fails:
        print(f"FALLO ({len(fails)})")
        for f in fails:
            print(f"   - {f}")
        return 1
    print("PASS: extractor con readability, title correcto y Content-Type respetado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
