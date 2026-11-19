# Changelog

## Unreleased

1. A texture in the simulator keeps its vertex color, atlas, file and texture coordinates.
2. The new helper `wow.aura_button()` is a fake aura button that runs the dispel type textures of the client.
3. A button in the simulator keeps its enabled state (`Enable`, `Disable`, `SetEnabled`, `IsEnabled`), and a check button keeps its checked state (`SetChecked`, `GetChecked`).
4. A region in the simulator keeps its anchor points (`SetPoint`, `ClearAllPoints`, `GetPoint`, `GetNumPoints`) and its horizontal justification (`SetJustifyH`, `GetJustifyH`).

## 0.1.0, 2026-11-08

The first release of wow-addon-agentic-workflow. A real port of ArenaLive from TBC Classic tested the template in the client.

The template contains these parts:

1. A pin of the game build in `wow-target.toml`, and a status command that compares it with the live build, the client and the UI source.
2. An MCP server and the `waw` command line for API questions on the pinned build.
3. Static analysis for removed APIs, old combat log code, restricted events, secret comparisons, TOC and XML errors, and Lua 5.1 syntax.
4. An offline simulator with secret values, XML frames, Blizzard templates, CVars and timers.
5. An in-client test addon that returns test results, probe data and Lua errors through SavedVariables.
6. A code graph with codebase-memory-mcp: one index for each repository, and shared indexes for FrameXML and reference addons.
7. Agent instructions, skills, code guidelines, and migration notes with field results from the pilot port.
8. Commands to create addon repositories and to copy tool updates to them.
