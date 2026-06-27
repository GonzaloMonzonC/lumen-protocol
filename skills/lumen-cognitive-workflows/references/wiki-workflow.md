# Wiki Building with Persistent State

**Implemented**: June 2026  
**Tools**: wiki_create, wiki_read, wiki_update, wiki_list (4 new MCP tools)

## Architecture

The wiki is a named-page knowledge base stored in `session.wiki: dict[str, dict]`. Each page has:
- `content`: markdown/text body
- `author`: agent or user identifier  
- `created_at`: Unix timestamp
- `updated_at`: Unix timestamp

Wiki pages are persisted via the Session `to_dict()`/`from_dict()` serialization to `.thinking_state.json`.

## Tools

```python
wiki_create(title, content, author="agent")    # Create or overwrite
wiki_read(title)                                # Read a page
wiki_update(title, content, mode="replace|append", author="agent")  # Update
wiki_list()                                     # List all pages
```

## Why Wiki vs Mental Model

- **Mental Model** (`model_add/map/stats`): Entity-relationship graph for CODEBASE architecture
- **Wiki** (`wiki_create/read/update/list`): Named pages for KNOWLEDGE documentation

The mental model answers "what depends on what in this codebase?"  
The wiki answers "what do we know about X topic?"

Both coexist and persist across sessions.

## Dashboard Integration

The wiki panel shows:
- Page titles (clickable → modal with full content)
- Character count per page
- Author + last updated timestamp

API field: `"wiki": [{title, chars, author, updated}]` in `/metrics` response.

## Pitfalls

- **Wiki is per-session**: Pages in `session_1` won't appear in `default` session's wiki list
- **No markdown rendering**: Content is plain text. Markdown rendering is a dashboard concern
- **No deletion tool**: Pages can only be overwritten with empty content, not deleted
