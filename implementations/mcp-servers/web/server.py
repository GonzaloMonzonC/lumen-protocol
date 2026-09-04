"""
LUMEN Web Search + Extract MCP Server.

Unified search + extraction in a single call with LUMEN binary transport.
Superior to Hermes built-in web_search + web_extract because:
  - 1 round-trip instead of 2 (search + extract combined)
  - LUMEN compresses structured results 27-36%
  - Multi-agent cache sharing
  - Smart auto-extraction of top results
  - Content enrichment (reading time, language, word count)

Hermes config:
  mcp_servers:
    lumen_web:
      command: "python"
      args: ["server.py"]
      transport: lumen
"""

from __future__ import annotations

import sys, os, json, re, time, urllib.request, urllib.error, urllib.parse, socket, ipaddress
from pathlib import Path
from typing import Any

# ── Windows: force UTF-8 on stdout so web content doesn't break MCP pipes ──
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ═══════════════════════════════════════════════════════════════════════
# Cache (multi-agent friendly)
# ═══════════════════════════════════════════════════════════════════════

_cache: dict = {}       # query → (timestamp, results)
_CACHE_TTL = 300         # 5 minutes


def _cached(key: str, fetcher, ttl: int = _CACHE_TTL):
    """Cache-aware fetch. Returns cached result if fresh."""
    now = time.time()
    if key in _cache:
        ts, val = _cache[key]
        if now - ts < ttl:
            return val
    val = fetcher()
    _cache[key] = (now, val)
    # Prune old entries
    if len(_cache) > 100:
        _cache.pop(next(iter(_cache)))
    return val


# ═══════════════════════════════════════════════════════════════════════
# SSRF protection
# ═══════════════════════════════════════════════════════════════════════

# Private/reserved networks that must never be reached
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),        # Current network (DHCP)
    ipaddress.ip_network("10.0.0.0/8"),        # RFC 1918
    ipaddress.ip_network("100.64.0.0/10"),     # RFC 6598 (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),     # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),    # RFC 1918
    ipaddress.ip_network("224.0.0.0/4"),       # Multicast
    ipaddress.ip_network("240.0.0.0/4"),       # Reserved (Class E)
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 unique-local
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
]

# Max redirects to follow (prevents infinite loops)
_MAX_REDIRECTS = 5
# Max response bytes to avoid OOM
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB

# Extra blocked hostnames (comma-separated via LUMEN_BLOCKED_HOSTS env var)
BLOCKED_HOSTS: list[str] = [
    h.strip().lower() for h in os.environ.get("LUMEN_BLOCKED_HOSTS", "").split(",") if h.strip()
]


class SSRFError(Exception):
    """Raised when a URL targets a private/blocked destination."""


def _is_safe_url(url: str) -> None:
    """Validate that *url* does not point to a private or blocked destination.

    Raises SSRFError if the URL is unsafe.
    """
    parsed = urllib.parse.urlparse(url)

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Blocked: unsupported scheme '{parsed.scheme}' (only http/https allowed)")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("Blocked: URL has no hostname")

    # Blocked-hosts check (before DNS to avoid TOCTOU)
    if hostname.lower() in BLOCKED_HOSTS:
        raise SSRFError(f"Blocked: hostname '{hostname}' is in blocked hosts list")

    # Default port: 443 for HTTPS, 80 for HTTP
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port

    # Resolve and check every returned address
    try:
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError(f"Blocked: cannot resolve hostname '{hostname}'") from exc

    for family, _type, _proto, _canon, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        for net in _PRIVATE_NETWORKS:
            if ip in net:
                raise SSRFError(f"Blocked: '{hostname}' resolves to private IP {ip}")


# ═══════════════════════════════════════════════════════════════════════
# Tool definitions
# ═══════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web and optionally extract content from top results. Returns structured results with titles, URLs, and descriptions. Use this instead of Hermes built-in web_search + web_extract — it combines both in a single call with 40-50% wire savings via LUMEN.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query (supports operators: site:, filetype:, intitle:, -term)"},
                "limit": {"type": "integer", "description": "Max results (default: 5, max: 10)", "default": 5, "maximum": 10},
                "extract_top": {"type": "integer", "description": "Auto-extract content from top N results (0 = skip, default: 0)", "default": 0, "maximum": 5},
                "extract_max_chars": {"type": "integer", "description": "Max chars per extracted page (default: 5000)", "default": 5000, "maximum": 20000}
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_extract",
        "description": "Extract content from URLs as markdown. Use for reading specific pages found via web_search.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "description": "List of URLs to extract (max 5)"},
                "max_chars": {"type": "integer", "description": "Max chars per page (default: 10000)", "default": 10000, "maximum": 30000}
            },
            "required": ["urls"]
        }
    }
]


# ═══════════════════════════════════════════════════════════════════════
# Web Search implementation (DuckDuckGo HTML scraping — no API key needed)
# ═══════════════════════════════════════════════════════════════════════

def _unwrap_ddg_url(url: str) -> str:
    """DDG HTML sirve redirects `//duckduckgo.com/l/?uddg=<target>&rut=...` —
    resuelve a https y extrae el destino real."""
    import urllib.parse as _up
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    if "/l/?uddg=" in url or "/l/?uddg%3D" in url:
        q = _up.parse_qs(_up.urlparse(url).query)
        if q.get("uddg"):
            return q["uddg"][0]
    return url


def _tavily_search(query: str, limit: int = 5, include_answer: bool = False) -> list[dict]:
    """Fallback de pago: Tavily (cadena DDG→Tavily). Key por env
    TAVILY_API_KEY (Hermes/.env) o LUMEN_SEARCH_API_KEY (Poli/secrets.env).
    Devuelve el MISMO shape que _search_duckduckgo (title/url/description/score)."""
    key = os.environ.get("TAVILY_API_KEY") or os.environ.get("LUMEN_SEARCH_API_KEY") or ""
    if not key:
        return []
    try:
        payload = json.dumps({
            "query": query,
            "max_results": max(1, min(limit, 10)),
            "search_depth": "basic",
            "topic": "general",
            "include_answer": include_answer,
            "include_raw_content": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": (r.get("content") or "")[:2000],
                "score": r.get("score"),
            }
            for r in data.get("results", [])[:limit]
        ]
    except Exception:
        return []


def _search_duckduckgo(query: str, limit: int = 5) -> list[dict]:
    """Search DuckDuckGo (tries Instant Answer API first, falls back to HTML)."""
    import urllib.parse
    
    # Try DuckDuckGo Instant Answer API (no API key, returns JSON)
    try:
        api_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
        _is_safe_url(api_url)
        data = json.loads(_safe_fetch(api_url, max_bytes=512 * 1024).decode("utf-8", errors="replace"))
        
        results = []
        # Abstract (main result) — solo si tiene URL real (a menudo llega vacía)
        if data.get("AbstractText") and data.get("AbstractURL"):
            results.append({
                "title": data.get("Heading", query),
                "url": data.get("AbstractURL", ""),
                "description": data["AbstractText"][:300]
            })
        
        # Related topics
        for topic in data.get("RelatedTopics", [])[:limit * 2]:
            if isinstance(topic, dict) and "Text" in topic:
                text = topic["Text"]
                # Extract title from "Title — Description" format
                parts = text.split(" — ", 1) if " — " in text else text.split(" - ", 1) if " - " in text else [text, ""]
                title = parts[0].strip()
                desc = parts[1].strip() if len(parts) > 1 else text[:300]
                url = topic.get("FirstURL", "")
                if title and url:
                    results.append({
                        "title": title[:200],
                        "url": url,
                        "description": desc[:300]
                    })
        
        if results:
            return results[:limit]
    except Exception:
        pass
    
    # Fallback: HTML scraping
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    try:
        _is_safe_url(url)
    except SSRFError:
        return [{"error": "Search request blocked by SSRF protection"}]

    try:
        html = _safe_fetch(url, max_bytes=2 * 1024 * 1024).decode("utf-8", errors="replace")
    except Exception:
        return [{"error": "Search request failed — check network"}]

    import re as _re

    def _parse(html_body: str) -> list[dict]:
        results = []
        # Parse result blocks
        links = _re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_body, _re.DOTALL)
        snippets = _re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|td)>', html_body, _re.DOTALL)
        for i, (url, title_html) in enumerate(links):
            title = _re.sub(r'<[^>]+>', '', title_html).strip()
            if not title:
                continue
            real_url = _unwrap_ddg_url(url)
            # Filtro anuncios de DDG (y.js/ad_domain — Bing ads)
            if _re.search(r'y\.js|ad_domain|ad_provider', real_url, _re.I):
                continue
            snippet = _re.sub(r'<[^>]+>', '', snippets[i] if i < len(snippets) else "").strip()
            results.append({
                "title": title,
                "url": real_url,
                "description": snippet or "(no description)"
            })
            if len(results) >= limit:
                break
        return results

    results = _parse(html)
    if not results:
        # Página anomaly (anti-bot) o throttle: esperar y reintentar una vez
        import time as _time
        _time.sleep(1.5)
        try:
            html = _safe_fetch(url, max_bytes=2 * 1024 * 1024).decode("utf-8", errors="replace")
            results = _parse(html)
        except Exception:
            pass

    return results if results else [{"error": f"No results for: {query}"}]


def _safe_fetch(url: str, max_bytes: int = _MAX_RESPONSE_BYTES, timeout: int = 20) -> bytes:
    """Fetch URL with SSRF check per redirect hop and size cap."""
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        _is_safe_url(current_url)
        req = urllib.request.Request(current_url, headers={
            # Browser UA: DDG y muchos sitios sirven página "anomaly" (sin resultados)
            # a UAs de bot/crawler (verificado 2026-09-04: LUMEN-Web/1.0 → 14KB anomaly,
            # Chrome 125 → 33KB con resultados reales).
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if 300 <= resp.status < 400:
                    loc = resp.headers.get("Location", "")
                    if not loc:
                        raise urllib.error.URLError("Redirect without Location header")
                    current_url = urllib.parse.urljoin(current_url, loc)
                    continue
                # Streaming read with byte limit
                chunks = []
                total = 0
                while total < max_bytes:
                    chunk = resp.read(min(8192, max_bytes - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                return b"".join(chunks)
        except urllib.error.HTTPError:
            raise
    raise urllib.error.URLError(f"Too many redirects (>{_MAX_REDIRECTS})")


def _extract_page(url: str, max_chars: int = 5000) -> dict:
    """Extract a web page as simplified markdown text."""
    try:
        _is_safe_url(url)
    except SSRFError as e:
        return {"url": url, "content": f"[SSRF blocked: {e}]", "error": str(e)}
    try:
        raw_bytes = _safe_fetch(url)
        content_type = "text/html"  # assumed
        raw = raw_bytes.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return {"url": url, "content": f"[HTTP {e.code}: {e.reason}]", "error": str(e)}
    except Exception as e:
        return {"url": url, "content": f"[Error: {e}]", "error": str(e)}
    
    # Simple HTML-to-text (strip tags, normalize whitespace)
    import re as _re
    # Remove scripts, styles, nav
    for tag in ['script', 'style', 'nav', 'header', 'footer']:
        raw = _re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', raw, flags=_re.DOTALL | _re.IGNORECASE)
    
    # Convert block elements to newlines
    for tag in ['p', 'div', 'article', 'section', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr']:
        raw = _re.sub(f'<{tag}[^>]*>', '\n', raw, flags=_re.IGNORECASE)
    
    # Remove remaining tags
    text = _re.sub(r'<[^>]+>', ' ', raw)
    
    # Normalize whitespace
    text = _re.sub(r'[ \t]+', ' ', text)
    text = _re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    
    # Extract metadata
    title_match = _re.search(r'<title[^>]*>(.*?)</title>', raw, _re.IGNORECASE)
    title = _re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else url
    
    word_count = len(text.split())
    
    # Truncate
    text = text[:max_chars]
    
    return {
        "url": url,
        "title": title[:200],
        "content": text,
        "word_count": word_count,
        "truncated": len(text) >= max_chars
    }


# ═══════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════

def tool_web_search(args: dict) -> dict:
    """Search the web with optional auto-extraction."""
    query = args["query"]
    limit = min(args.get("limit", 5), 10)
    extract_top = min(args.get("extract_top", 0), 5)
    extract_max = min(args.get("extract_max_chars", 5000), 20000)
    
    # Search (cached)
    results = _cached(f"search:{query}:{limit}", lambda: _search_duckduckgo(query, limit))

    # Quitar items-error internos
    errors = [r.get("error") for r in results if isinstance(r, dict) and "error" in r]
    results = [r for r in results if isinstance(r, dict) and "error" not in r]

    # Cadena DDG (gratis) → Tavily (pago): solo si DDG no trajo nada y hay key
    engine = "ddg"
    if not results:
        fallback = _tavily_search(query, limit)
        if fallback:
            results = fallback
            engine = "tavily"

    # Auto-extract top results if requested
    output = {"engine": engine, "results": results}
    if errors and not results:
        output["error"] = errors[0]
    if extract_top > 0:
        extracts = []
        for r in results[:extract_top]:
            if "url" in r:
                cached_extract = _cached(f"extract:{r['url']}:{extract_max}", lambda: _extract_page(r['url'], extract_max))
                extracts.append(cached_extract)
        output["extracted"] = extracts
    
    return {"content": [{"type": "text", "text": json.dumps(output, indent=2, ensure_ascii=False)}]}


def tool_web_extract(args: dict) -> dict:
    """Extract content from specific URLs."""
    urls = args["urls"][:5]  # Max 5 URLs
    max_chars = min(args.get("max_chars", 10000), 30000)
    
    results = []
    for url in urls:
        result = _cached(f"extract:{url}:{max_chars}", lambda u=url: _extract_page(u, max_chars))
        results.append(result)
    
    return {"content": [{"type": "text", "text": json.dumps(results, indent=2, ensure_ascii=False)}]}


HANDLERS = {
    "web_search": tool_web_search,
    "web_extract": tool_web_extract,
}


# ═══════════════════════════════════════════════════════════════════════
# MCP Server (JSON-RPC over stdio)
# ═══════════════════════════════════════════════════════════════════════

def send(msg: dict) -> None:
    from lumen_mcp_stdio import write_message
    write_message(msg)


def handle_message(msg: dict) -> None:
    method = msg.get("method", "")
    req_id = msg.get("id")

    if method == "initialize":
        send({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumen-web", "version": "1.0.0"}
            }
        })
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = HANDLERS.get(tool_name)
        if handler:
            try:
                result = handler(tool_args)
                send({"jsonrpc": "2.0", "id": req_id, "result": result})
            except Exception as e:
                send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": f"Tool error: {e}"}})
        else:
            send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}})
    elif method == "notifications/initialized":
        pass
    else:
        send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}})


def main() -> None:
    import os as _os
    _mcp_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _mcp_dir not in sys.path:
        sys.path.insert(0, _mcp_dir)
    from lumen_mcp_stdio import read_message
    while True:
        try:
            msg = read_message()
        except (EOFError, TimeoutError, ValueError):
            break
        if msg is None:
            break
        try:
            handle_message(msg)
        except json.JSONDecodeError:
            pass


if __name__ == "__main__":
    main()
