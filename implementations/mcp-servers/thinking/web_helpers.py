"""
Web extraction helpers for web_snapshot tool.
Copied from web/server.py and adapted for thinking server integration.
"""
import re, time, urllib.request, urllib.error, urllib.parse, socket, ipaddress

_PRIVATE_NETS = [ipaddress.ip_network(n) for n in [
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10",
    "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.168.0.0/16", "224.0.0.0/4", "240.0.0.0/4",
    "::1/128", "fc00::/7", "fe80::/10"
]]
_MAX_REDIRECTS = 5
_MAX_BYTES = 5 * 1024 * 1024


def is_safe_url(url: str) -> None:
    """SSRF protection: raise ValueError if url targets private/blocked destination."""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme: {p.scheme}")
    host = p.hostname
    if not host:
        raise ValueError("No hostname")
    port = p.port or (443 if p.scheme == "https" else 80)
    addrs = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    for fam, _type, _proto, _canon, sa in addrs:
        ip = ipaddress.ip_address(sa[0])
        for net in _PRIVATE_NETS:
            if ip in net:
                raise ValueError(f"Private IP: {ip}")


def safe_fetch(url: str, max_bytes: int = _MAX_BYTES, timeout: int = 20) -> bytes:
    """Fetch URL with SSRF check per redirect hop and size cap."""
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        is_safe_url(current_url)
        req = urllib.request.Request(current_url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; LUMEN-Web/1.0)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 300 <= resp.status < 400:
                loc = resp.headers.get("Location", "")
                if not loc:
                    raise urllib.error.URLError("Redirect without Location header")
                current_url = urllib.parse.urljoin(current_url, loc)
                continue
            chunks = []
            total = 0
            while total < max_bytes:
                chunk = resp.read(min(8192, max_bytes - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            return b"".join(chunks)
    raise urllib.error.URLError(f"Too many redirects (> {_MAX_REDIRECTS})")


def extract_page(url: str, max_chars: int = 10000) -> dict:
    """Extract a web page as simplified markdown text."""
    try:
        is_safe_url(url)
        raw_bytes = safe_fetch(url)
        raw = raw_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        return {"url": url, "content": f"[Error: {e}]", "error": str(e)}

    # Remove scripts, styles, nav, header, footer
    for tag in ['script', 'style', 'nav', 'header', 'footer']:
        raw = re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', raw, flags=re.DOTALL | re.IGNORECASE)

    # Convert block elements to newlines
    for tag in ['p', 'div', 'article', 'section', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr']:
        raw = re.sub(f'<{tag}[^>]*>', '\n', raw, flags=re.IGNORECASE)

    # Remove remaining tags
    text = re.sub(r'<[^>]+>', ' ', raw)

    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # Extract metadata
    title_match = re.search(r'<title[^>]*>(.*?)</title>', raw, re.IGNORECASE)
    title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else url

    word_count = len(text.split())
    text = text[:max_chars]

    return {
        "url": url,
        "title": title[:200],
        "content": text,
        "word_count": word_count,
        "truncated": len(text) >= max_chars
    }
