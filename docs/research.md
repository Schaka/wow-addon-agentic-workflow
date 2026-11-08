# Research notes

This document records what other projects do and which ideas this template uses. The review date is 2026-11-08.

## API servers for agents

| Project | Forever data | Result |
| --- | --- | --- |
| Koodattu/wow-addon-api-mcp | Bundled snapshot of 1.60.1 | Good restriction data and version diffs. It does not know the pin of a repository. |
| RdyGaming/hated-wow-mcp | Bundled index and optional sync | Many tools, including art and model data. It does not know the pin of a repository. |
| PhilIsHere/wow-dev-mcp | Name lists for each client | Good for global strings. No signatures. |
| spartanui-wow/wow-api-mcp | Reads the Ketho extension | The review found no Forever channel. |
| Xerrion/wow-addon-skills | Local annotations | Portable skill and server. |

None of these servers compares the pin of a repository with the live build. This template therefore includes a small server that builds its data from the exact UI source of the pinned build. You can add one of these servers as well, for art data or for global strings.

## Addon projects

| Project | Practice | Used here |
| --- | --- | --- |
| Questie | busted tests next to the code, luacheck in CI, a Forever work list | Offline tests, CI |
| DBM | luacheck and LuaLS in CI, one TOC with many interface values, runtime client flags | Client detection |
| Atlas and AtlasLoot | Separate TOC files for each client | TOC analysis |
| Decursive | Static analysis against Forever UI source, CI tests the packaged TOC | Static analysis |
| tv (TemplateViewer) | "Evidence, not memory" rule, pinned UI source, Lua 5.1 guard, in-game audit saved to disk | Pin, evidence order, SavedVariables report |
| Mechanic | Queue, reload, then read SavedVariables. Offline stubs | The in-client bridge |
| wowless | Headless client with a taint-aware Lua | Considered. It is pre-alpha and builds in Docker. |
| elune | Lua 5.1 with taint support | Candidate for a more accurate simulator |
| ForeverProbe in justadakaje/wow-addons | Runtime dump of the API | Runtime probe |

The wowless project states that an error is almost certainly in wowless and not in the addon. For this reason, it is not a required layer. It has `wowf` data, so a later version can add it as an optional layer.

## Pilot port

The first real port was ArenaLive, a unit frame addon from TBC Classic. Its lessons are in `docs/migration/field-notes.md`. The research for it found these projects:

| Project | What it does on Forever or Midnight | Result |
| --- | --- | --- |
| MiniAuras (formerly MiniCC) | Supports Forever. Shows crowd control with custom aura containers and client filters. | The reference design for secret auras. "All Rights Reserved", so learn only. |
| BigDebuffs | No Forever build. Skips every aura with a secret spell ID. | Do not depend on it. |
| Open Raid Library | Does not load on Forever. Stops messages in combat on Midnight. | No library shares cooldowns on Forever yet. |
| DRList-1.0 | Falls back to its MoP table for the unknown project ID 18. | Usable with one mapping. MIT license. |
| DRPulse, Forever Simple DR | Track only target, focus and nameplates, and show uncertain data. | The same limits as the pilot. |

## Decisions

| Decision | Reason |
| --- | --- |
| Python standard library and plain Lua | No install step, and the tools work on Linux, Windows and macOS |
| Parse Lua data, and do not run it | Downloaded files and SavedVariables stay inert |
| One manual `/reload` in the loop | `ReloadUI` needs a hardware event. Blizzard treats a program that presses keys as a Terms of Use violation. |
| No screen reading | SavedVariables give structured data |
| A missing fake raises an error | A test cannot pass by accident |
| codebase-memory-mcp for code, one shared index for each build | Agents query code and do not read whole files. All repositories share the large indexes. |
| Data first, with in-game probes | The pilot found several wrong assumptions only with measured data. |

## Sources

1. [Blizzard version service for Forever](https://us.version.battle.net/v2/products/wowf/versions)
2. [Gethe/wow-ui-source, branch forever](https://github.com/Gethe/wow-ui-source/tree/forever)
3. [Ketho/BlizzardInterfaceResources, branch forever](https://github.com/Ketho/BlizzardInterfaceResources/tree/forever)
4. [Warcraft Wiki: TOC format](https://warcraft.wiki.gg/wiki/TOC_format)
5. [Warcraft Wiki: Patch 12.0.0 API changes](https://warcraft.wiki.gg/wiki/Patch_12.0.0/API_changes)
6. [Warcraft Wiki: Patch 1.60.1 API changes](https://warcraft.wiki.gg/wiki/Patch_1.60.1/API_changes)
7. [Warcraft Wiki: Secret Values](https://warcraft.wiki.gg/wiki/Secret_Values)
8. [Warcraft Wiki: ReloadUI](https://warcraft.wiki.gg/wiki/API_ReloadUI)
9. [Blizzard forum thread on automation terminology](https://us.forums.blizzard.com/en/blizzard/t/confusion-on-terminology-surrounding-automation/44564)
10. [BigWigs packager](https://github.com/BigWigsMods/packager)
11. [Questie](https://github.com/Questie/Questie)
12. [DBM](https://github.com/DeadlyBossMods/DeadlyBossMods)
13. [Atlas](https://github.com/arithmandar/Atlas)
14. [Decursive for Forever](https://github.com/Bl4ut0/Decursive)
15. [tv](https://github.com/Cidan/tv)
16. [Mechanic](https://github.com/Falkicon/Mechanic)
17. [wowless](https://github.com/wowless/wowless)
18. [elune](https://github.com/Meorawr/elune)
19. [rdimascio/wow-ai pull request 13](https://github.com/rdimascio/wow-ai/pull/13)
