# LUMEN web_extract vs Hermes web_extract — Benchmark 2026-06-17

URL: `https://hermes-agent.nousresearch.com/docs` (5000 chars limit)

## Results

| Metric | Hermes (Firecrawl) | LUMEN (stdlib) |
|--------|-------------------|----------------|
| Content quality | Markdown limpio, estructurado | Texto plano con restos de navegación |
| Title detection | ✅ | ✅ |
| Word count | N/A | 752 |
| Wire (response) | ~3000B (est.) | 5449B → 5640B JSON |
| Wire savings | — | 4% (content dominates, not structure) |
| Latency | ~500ms | 183ms |
| Dependencies | Firecrawl API key / Nous subscription | Zero (stdlib only) |
| Search+Extract unified | ❌ (2 separate calls) | ✅ (1 call) |
| Multi-agent cache | ❌ | ✅ (5 min TTL, 100 entries) |
| Rate limiting | Via Firecrawl | Self-contained |
| Free tier | No (needs subscription) | Yes (DuckDuckGo API) |

## Honest Verdict

LUMEN web_extract is NOT superior to Hermes in content quality. Firecrawl is a professional web scraping service.

LUMEN wins on:
- Speed (183ms vs ~500ms)
- Cost (free, no API key)
- Unified search+extract (1 call vs 2)
- Multi-agent cache

Hermes wins on:
- Content quality (clean markdown vs raw text)
- Robustness (professional service vs regex HTML parsing)

**They are complementary, not competitors.** Use LUMEN for quick searches and lightweight extraction. Use Hermes when you need professional-quality content.

## Wire Savings Analysis

The 4% wire savings confirms the general principle: LUMEN compresses STRUCTURE (JSON keys, metadata) but NOT CONTENT (the page text itself). For content-heavy operations like web_extract, the wire benefit is minimal. The real value is in the unified search+extract workflow and multi-agent caching.
