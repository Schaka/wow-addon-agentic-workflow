# Replace the combat log

Addons on Forever cannot read the combat log. Old code that registers the event or calls the reader will fail.

## Evidence

| Fact | Source |
| --- | --- |
| `COMBAT_LOG_EVENT_UNFILTERED` and `COMBAT_LOG_EVENT` have `HasRestrictions = true`. | Blizzard `CombatLogDocumentation.lua`, Forever branch |
| `GetCurrentEventInfo` exists only in `C_CombatLogSecure` and `C_CombatLogInternal`. | Blizzard API documentation, Forever branch |
| The alias `CombatLogGetCurrentEventInfo` points to `C_CombatLog.GetCurrentEventInfo`, which does not exist. | `Blizzard_DeprecatedCombatLog/Deprecated_CombatLog.lua` |
| Registration of these events raises an error on Midnight. | Warcraft Wiki, Patch 12.0.0 API changes |
| One addon on Forever reported a block at login for this event. | `rdimascio/wow-ai` pull request 13 |
| DBM treats Forever as a restricted client. | `DBM-Core.lua`, function `IsRestricted` |

## Replacements

Each row shows a verified event or API on the pinned build. Replacements give less data than the combat log. Many of them are secret for other units: the pilot port measured that the spell IDs of other players' casts were secret, also in the open world. See `docs/migration/field-notes.md` before you design a replacement.

| Old sub-event or purpose | Replacement | Notes |
| --- | --- | --- |
| `SPELL_CAST_START` | `UNIT_SPELLCAST_START` | Can be secret: spell cast restriction |
| `SPELL_CAST_SUCCESS` | `UNIT_SPELLCAST_SUCCEEDED` | Can be secret: spell cast restriction |
| `SPELL_INTERRUPT` | `UNIT_SPELLCAST_INTERRUPTED` | Can be secret: spell cast restriction |
| `SPELL_AURA_APPLIED`, `SPELL_AURA_REMOVED` | `UNIT_AURA`, then `C_UnitAuras.GetAuraDataByAuraInstanceID` | Can be secret: aura restriction |
| `SWING_DAMAGE`, `SPELL_DAMAGE` on one unit | `UNIT_COMBAT` | Payload: unit, event, flag text, amount, school mask |
| Damage and healing totals | `C_DamageMeter` and the `DAMAGE_METER_*` events | Some results are secret in combat |
| `UNIT_DIED` | The `UNIT_DIED` event | Payload: GUID. Can be secret: unit identity restriction |
| Own death details | `PLAYER_DEAD`, then `C_DeathRecap.GetRecapEvents` | |
| Boss timers | `ENCOUNTER_START`, `ENCOUNTER_END`, `C_EncounterTimeline` | Timeline events can be secret |
| Enter and leave combat | `PLAYER_REGEN_DISABLED`, `PLAYER_REGEN_ENABLED` | |
| Threat | `UNIT_THREAT_LIST_UPDATE`, `UNIT_THREAT_SITUATION_UPDATE` | |
| Quest kills and experience | `QUEST_LOG_UPDATE`, `UNIT_QUEST_LOG_CHANGED`, `PLAYER_XP_UPDATE` | |

## Features without a replacement

These features do not have a verified replacement on the pinned build:

1. A swing timer that needs each melee swing.
2. A full log of the actions of other players.
3. Damage breakdowns that need each hit from each source.

Do not parse combat log chat lines as a workaround. Reports state that these lines are also not readable by addons.

## Procedure

1. Run `./waw check` and read each `migration-event` and `migration-api` finding.
2. List the data that each combat log branch uses.
3. Look up the replacement with `wow_api_lookup`, and read its `flags` value.
4. If the replacement can be secret, read `docs/migration/secret-values.md`.
5. Add an offline test that fires the new event with `wow.fire`.
6. Add an in-client test for the real payload.
7. If a feature has no replacement, remove it and tell the user.
