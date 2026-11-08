# The WoW Forever platform

This document lists facts about the client and the evidence for each fact. Facts change with each build. Use `./waw target status` for the current build.

## Identity

| Fact | Value | Evidence |
| --- | --- | --- |
| Blizzard product code | `wowf` | Blizzard version service |
| Client version family | `1.60.1` | Blizzard version service |
| TOC interface value | `16001` | Warcraft Wiki and shipped addons |
| TOC game type | `camelot`, with the alias `forever` | Blizzard TOC files and Warcraft Wiki |
| Project constant | `WOW_PROJECT_CAMELOT = 18` | `Blizzard_ProjectConstants/Camelot/ProjectConstants.lua` |
| Install folder | `_forever_` | Local install |
| UI source | Branch `forever` of `Gethe/wow-ui-source` | Mirror of the client export |

An earlier beta used the install folder `_classic_beta_`. Early beta reports also show `WOW_PROJECT_ID = 1`. Those reports are out of date.

To detect Forever at runtime, use this test:

```lua
local isForever = WOW_PROJECT_ID == (WOW_PROJECT_CAMELOT or 18)
```

## Build sources

The tools compare four sources:

| Source | Meaning |
| --- | --- |
| Pin | The build that this repository targets |
| Live | What Blizzard serves now, from `https://us.version.battle.net/v2/products/wowf/versions` |
| UI source | The newest export in the `forever` branch |
| Installed | The `.build.info` file of the local client |

The installed build can be older than live until the launcher updates the game.

## TOC files

Blizzard's own files use `AllowLoadGameType camelot`. The client accepts both the `_Camelot` and the `_Forever` file suffix, according to the Warcraft Wiki. Real addons use both.

BigWigs packager recognizes `_Camelot` but not `_Forever`. This template uses `<Name>.toc` for addons that support only Forever, and `_Camelot` for addons that support many clients.

## Lua environment

The client runs a restricted Lua 5.1. It has no `io`, `os`, `require`, `dofile` or `loadfile`. It adds the `bit` library and WoW string helpers such as `strsplit`.

## Combat data

Forever uses the Midnight addon restrictions. The Warcraft Wiki and the addon restriction fields in the Blizzard API documentation support this. See `docs/migration/combat-log.md` and `docs/migration/secret-values.md`.

## Deprecation shims

A deprecation shim is a Blizzard alias that keeps an old API name working. The files in `Blizzard_Deprecated*` define these aliases. The CVar `loadDeprecationFallbacks` controls whether they load. Blizzard states that it will remove them.

Do not depend on a shim. An alias can also point to a function that addons cannot call. `CombatLogGetCurrentEventInfo` is an example.

## Answered by the pilot port

The ArenaLive pilot port measured these facts on build 70862 on 2026-11-08. The details are in `docs/migration/field-notes.md`.

1. `C_CombatLog.IsCombatLogRestricted()` returned true for addon code.
2. A runtime probe recorded every function that the client exposes. `./waw ingame prepare --probe` repeats it for a new build.
3. In the open world, the aura data of an enemy in combat and the cast spell IDs of other players were secret. The addon restriction types all reported false.

## Open questions

These items do not have firm evidence. Test them in the client:

1. Whether addon messages work in combat. Open Raid Library stops its messages in combat on Midnight.
2. Which values are secret inside instances, battlegrounds and PvP. The pilot measured only the open world.
