# LUMEN Tools Guide — When to Use Each Tool

Practical decision guide for all 18 LUMEN MCP tools across 3 servers.
Use this to choose the right tool for every scenario.

---

## Reading Files

### `read_file`
**Case**: Read 1 file, ≤2000 lines.  
**Example**: "Read config.yaml to check the settings."  
**Why not built-in**: 100K char guard protects LLM context from flooding.

### `read_files` 🔥
**Case**: Inspect MULTIPLE files at once.  
**Example**: "Show me auth.py, models.py, and views.py."  
**Advantage**: 1 round-trip instead of N. The LLM saves turns.  
**Built-in**: ❌ does not exist.

### `stream_read` 🔥
**Case**: File >2000 lines or >100KB.  
**Example**: "Review the 50MB production log."  
**Advantage**: Chunk-by-chunk pagination. Does not flood context.  
**Built-in**: ❌ does not exist. read_file caps at 2000 lines.

**DECISION:**
```
1 file <2000 lines? → read_file
2-20 small files?   → read_files 🔥
Huge file?          → stream_read 🔥
```

---

## Searching

### `search_files`
**Case**: Find ALL occurrences of something.  
**Example**: "Find all TODOs in the project."  
**Extra modes**: `files_only` (just names), `count` (statistics).  
**Built-in**: exists but no output_mode or offset.

### `search_with_context` 🔥
**Case**: Understand the CONTEXT around a match.  
**Example**: "How is the process() function used in this file?"  
**Advantage**: ±N lines around match, `>>>` marks the hit line.  
**Built-in**: ❌ does not exist.

**DECISION:**
```
List of matches?     → search_files
Understand context?  → search_with_context 🔥
```

---

## Writing & Editing

### `write_file`
**Case**: Create or overwrite a complete file.  
**Example**: "Generate the configuration file."  
**Built-in**: functionally identical.

### `patch`
**Case**: Surgical change in an existing file.  
**Example**: "Change 'localhost' to '0.0.0.0' in settings.py."  
**Safety**: detects multiple occurrences, requires `replace_all`.  
**Built-in**: functionally identical.

**DECISION:**
```
New or full file?  → write_file
Targeted change?   → patch
```

---

## Navigation

### `list_directory` 🔥
**Case**: See what's in a directory.  
**Example**: "What files are in tests/?"  
**Advantage**: no terminal needed, built-in glob filter.  
**Built-in**: ❌ does not exist (LLM uses terminal ls/dir).

---

## Web

### `web_search`
**Case**: Quick search without API key.  
**Example**: "Search for info about this error I'm seeing."  
**Advantage**: search + extract in 1 call (`extract_top=N`).  
**Built-in**: Firecrawl (better quality, requires subscription).

### `web_extract`
**Case**: Read content from a specific URL.  
**Example**: "Extract the docs from python.org."  
**Built-in**: Firecrawl (better quality).

**DECISION:**
```
Professional quality?  → Hermes Firecrawl
Fast + free + unified? → LUMEN web 🔥
```

---

## Reasoning (7 Thinking Tools)

### `sequential_thinking` 🔥
**Case**: Complex problem requiring MULTIPLE steps.  
**Example**: "Plan the database migration."  
**Advantage**: thoughts persist outside LLM context window.  
**Use when**: the LLM tends to forget steps or needs revisions.

### `thought_similarity` 🔥
**Case**: "Have I thought about this before?"  
**Use when**: long chains, avoid redundancy.

### `thought_contradiction` 🔥
**Case**: Verify reasoning consistency.  
**Use when**: complex plans with many dependencies.

### `thought_summarize` 🔥
**Case**: Chain is too long, need a summary.  
**Example**: 30 thoughts → 3 key themes.

### `thought_to_plan` 🔥
**Case**: Convert reasoning into ACTION.  
**Example**: Thoughts → executable task list.

### `thought_evaluate` 🔥
**Case**: "Is this thought good?"  
**Use when**: improving reasoning quality.

### `thought_bridge` 🔥
**Case**: "Did I think about this in a previous session?"  
**Use when**: multi-session projects.

**TYPICAL FLOW:**
```
1. sequential_thinking  → 10-15 thoughts
2. thought_similarity   → verify no repetitions
3. thought_contradiction → check consistency
4. thought_summarize    → summary for context
5. thought_to_plan      → convert to action
6. thought_bridge       → cross-session knowledge
```

---

## Monitoring

### `server_stats` 🔥
**Case**: Is the LUMEN server healthy?  
**Example**: "How many operations has it processed today?"  
**Built-in**: ❌ does not exist.

---

## Golden Rule: LUMEN or Built-in?

**Use LUMEN when:**
- ✅ Operation repeats often (wire savings accumulate)
- ✅ Multi-agent workflow (1 server for all agents)
- ✅ Need exclusive features (bulk, context, thinking)
- ✅ Want zero API key dependencies (web without Firecrawl)

**Use Built-in when:**
- ✅ One-off simple operation (read 1 small file)
- ✅ Maximum speed needed (0.16ms vs 0.42ms)
- ✅ Professional quality is critical (Firecrawl > DuckDuckGo)
