---
name: wow-code-graph
description: Find or understand Lua or XML code in this repository or in Blizzard FrameXML with codebase-memory-mcp instead of reading files. Not for the question whether an API exists (use `wow-api-verify`).
---

# Use the code graph first

Reading whole files uses a large amount of context. A graph query returns only what you need.

1. Call `wow_code_index`. If MCP is not available, run `./waw index status`.
2. If an index is missing, run `./waw index`.
3. Find a symbol with `search_graph`. Give the project name, a `query`, and a `limit` of 10 to 20.
4. Read one symbol with `get_code_snippet`.
5. Find callers with `trace_path`. Use the full method name, such as `CCIndicator:UpdateCache`.
6. Find literal text, event names and API names with `search_code`.
7. If you must edit a file, read it directly. Read only the part that you change. Use `offset` and `limit` for a large file.

Each project has one purpose:

| Project | Content |
| --- | --- |
| `repo-<folder>` | The code of this repository |
| `wow-framexml-<product>-<build>` | Blizzard UI source for the pinned build |
| `wow-ref-<name>` | Reference addons |

A graph does not see dynamic dispatch, such as `object[methodName](...)`, or handlers registered by a string. Use `search_code` for those cases. An empty caller list does not prove that code is unused.

The API tools, such as `wow_api_lookup`, decide whether an API exists on the build. The graph shows how code uses an API.

If `codebase-memory-mcp` is not installed, use text search and read small ranges.
