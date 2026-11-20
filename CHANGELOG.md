# Changelog

## Unreleased

1. A texture in the simulator keeps its vertex color, atlas, file and texture coordinates.
2. The new helper `wow.aura_button()` is a fake aura button that runs the dispel type textures of the client.
3. A button in the simulator keeps its enabled state (`Enable`, `Disable`, `SetEnabled`, `IsEnabled`). A check button keeps its checked state (`SetChecked`, `GetChecked`).
4. A region in the simulator keeps its anchor points (`SetPoint`, `ClearAllPoints`, `GetPoint`, `GetNumPoints`). It also keeps its horizontal justification (`SetJustifyH`, `GetJustifyH`).
5. A region in the simulator keeps the size that the code sets (`SetSize`, `SetWidth`, `SetHeight`, `GetWidth`, `GetHeight`, `GetSize`). A size from an XML file is not read.
6. A frame in the simulator keeps its frame level (`SetFrameLevel`, `GetFrameLevel`). Without a level, a frame sits one level above its parent.
7. The new helper `wow.items()` holds item data for a test. It installs fakes for the item, equipment, bag and tooltip data functions, and it loads an item that is not cached after a request.
8. The new helper `wow.tooltip(name)` is a tooltip that records its lines and runs the post calls of `TooltipDataProcessor`, like the client.
9. The new helper `wow.addon_channel()` installs fakes for addon messages. It keeps the prefix, size, secret argument and lockdown rules, and it delivers messages from other players.
10. In the simulator, `IsVisible` is true only when the frame and all its parents are shown, as in the client. `SetParent` changes the parent.

## 0.1.0, 2026-11-08

The first release of wow-addon-agentic-workflow. A real port of ArenaLive from TBC Classic tested the template in the client.

The template contains these parts:

1. A pin of the game build in `wow-target.toml`. A status command compares it with the live build, the client and the UI source.
2. An MCP server and the `waw` command line for API questions on the pinned build.
3. Static analysis for removed APIs, old combat log code, restricted events, secret comparisons, TOC and XML errors, and Lua 5.1 syntax.
4. An offline simulator with secret values, XML frames, Blizzard templates, CVars and timers.
5. An in-client test addon that returns test results, probe data and Lua errors through SavedVariables.
6. A code graph with codebase-memory-mcp: one index for each repository, and shared indexes for FrameXML and reference addons.
7. Agent instructions, skills, code guidelines, and migration notes with field results from the pilot port.
8. Commands to create addon repositories and to copy tool updates to them.
