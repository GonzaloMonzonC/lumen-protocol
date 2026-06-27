# LUMEN Dashboard Pattern — Session 2026-06-16

Real session where a LUMEN thinking monitor dashboard was built from scratch
using the cognitive tools themselves as data sources.

## Architecture

- **Stack**: Astro 5 + Tailwind CSS + Alpine.js 3.x (no React needed for static dashboard)
- **CSS**: Exact clone of cadenceslab.com design system (global.css from cadenceslab/src/styles/)
- **Deploy**: Vercel static hosting via monorepo subdirectory

## Dashboard Panels Built

1. **KPIs** — thought count, avg score, contradictions, bridge count (glass cards)
2. **Heatmap** — activity by theme × month (color intensity)
3. **Active Chains** — clickable → modal with all thoughts in chain
4. **Bridge Connections** — horizontal bars with similarity %, clickable → detail
5. **Memory Usage** — progress bars for thoughts/chains/refs
6. **Memory Manager** — clear chains / clear bridges buttons
7. **Plans Generated** — thought_to_plan output as expandable steps
8. **Similar Thoughts** — thought_similarity matches between thoughts
9. **Thematic Clusters** — thought_summarize themes, clickable → drill down

## Tool Data Usage

| Panel | Tool | Data shape |
|-------|------|------------|
| KPIs | (manual tally) | Counts from session activity |
| Chains | indirect | Chain IDs collected during session |
| Bridges | `thought_bridge` | Cross-chain matches with similarity % |
| Plans | `thought_to_plan` | Markdown plan with steps + dependencies |
| Similarity | `thought_similarity` | Thought pairs with match % |
| Themes | `thought_summarize` | Clusters with thought counts |
| Contradictions | `thought_contradiction` | Boolean + details |

## Modals Pattern (Alpine.js + Astro)

```html
<!-- In Layout.astro <body> -->
<body x-data="{ activeModal: null, openModal(id) { this.activeModal = id }, closeModal() { this.activeModal = null } }" @keydown.escape="closeModal()">

<!-- In page -->
<button @click="openModal('kpi-thoughts')">Click me</button>

<div x-cloak x-show="activeModal === 'kpi-thoughts'" class="modal-overlay" @click.self="closeModal()">
  <div class="modal-card">
    <button @click="closeModal()">&times;</button>
    <!-- content -->
  </div>
</div>
```

CSS (in global.css, NOT inline):
```css
.modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,0.75); z-index:9999; display:flex; align-items:center; justify-content:center; padding:1rem }
.modal-card { background:rgba(20,20,35,0.98); backdrop-filter:blur(24px); border:1px solid rgba(255,255,255,0.08); border-radius:1.25rem; max-width:560px; width:100%; max-height:85vh; overflow-y:auto; padding:1.5rem; z-index:10000 }
```

## Key Pitfalls

1. **CSS in Layout.astro gets stripped**: Astro extracts `<style>` from Layout during build.
   Always put custom CSS in `src/styles/global.css`.
2. **`base: './'` doesn't work with islands**: Use absolute path like `/project-name/dist/`.
3. **`<div>` wrapper in React islands breaks flex**: Use `<>...</>` fragment.
4. **Alpine.js CDN**: Include in Layout, not page. Add `x-cloak` CSS: `[x-cloak]{display:none!important}`.
5. **Tool availability varies**: Only 7/29 tools available in this instance. Focus dashboard on the 7 stable Reasoning Chain tools.
