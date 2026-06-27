# New LUMEN Tool: Overlap Check Protocol

> **Proven June 2026**: Reduces proposed tools by 60-70% by leveraging existing LUMEN infrastructure.

## The Protocol

Before proposing ANY new LUMEN tool, run this checklist:

### 1. List ALL existing tools by category

| Category | Tools | What they do |
|----------|-------|-------------|
| Work tracking | work_start, work_block, work_done, work_log | Task lifecycle management |
| Patterns | pattern_record, pattern_match | Institutional knowledge |
| Decisions | decision_log, decision_list | Architecture decisions |
| Model | model_add, model_query, model_stats, etc. | Entity graph |
| Thinking | sequential_thinking, thought_*, chain_* | Reasoning chains |
| Context | context_preserve, context_check | Cross-session anchoring |
| Sessions | session_init, session_list | Multi-agent isolation |
| Assumptions | assume, list_assumptions, check_assumption | Premise validation |
| Messages | agent_message, agent_inbox | Cross-session communication |
| Wiki | wiki_create, wiki_read, wiki_*, model CRUD | Persistent docs |

### 2. Map each proposed feature to an existing tool

For each proposed tool, ask:
- Is there an existing tool that already does 70%+ of this?
- Can I EXTEND an existing tool instead of creating a new one?
- Does the new tool offer structural value (organization, visualization) that existing tools lack?

### 3. The Integration Rule

If a new feature is primarily about **organization/visualization** of EXISTING data, it belongs in:
- The **dashboard HTML** (UI-only feature)
- An **extension of an existing tool** (add fields, not new tools)
- NOT as a standalone tool suite

### 4. Minimal Viable Set

After overlap analysis, propose the MINIMUM number of new tools:
- Features that create/manage NEW data structures = tools
- Features that reorganize/display existing data = dashboard UI
- Features that bridge existing systems = 1-2 integration tools

## Example: Kanban Cognitive (June 2026)

**Initial proposal**: 12 tools
**After overlap check**: 4 tools + dashboard UI

| Proposed tool | Mapped to | Outcome |
|---------------|-----------|---------|
| niche_create | Categorization via work_start + tags | Not needed — extend work_start |
| task_create | work_start with niche field | Keep as task_create |
| task_move | work_block/change status | Keep as task_move |
| task_link | Link to chain/pattern/decision | Keep as task_link |
| task_list | Filtered work_log | Keep as task_list |
| kanban_board | Dashboard view of work_log | Dashboard UI only |
| kanban_dashboard | Dashboard view | Dashboard UI only |
| niche_list | Dashboard filter | Dashboard UI only |
| task_delete | Not needed (archive) | Remove |
| task_block | work_block with blockers | Merge into task_move |
| niche_stats | Dashboard metrics | Dashboard UI only |
| cross_niche_tasks | task_list with cross tag | Dashboard UI only |

**Final (proposal phase)**: 4 tools + dashboard UI = 67% reduction

**Final (implementation, June 2026)**: 7 tools + dashboard UI. The 4-tool set was extended with:
- `niche_update` — needed for archiving/closing niches (user-requested feature)
- Task-level edit via `task_move` parameters (title, desc, priority as optional params)
- HTTP endpoints `/kanban` (GET) + `/kanban/move` (POST) for dashboard drag-and-drop

The additional 3 tools accounted for real-world needs discovered during implementation (archive lifecycle, inline task editing, HTTP API for drag-and-drop). The dashboard UI callable at `http://host:port/` with the kanban panel under the 📋 toggle.
