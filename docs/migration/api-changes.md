# Port an older addon

Forever has Classic content but the modern API. An addon for Classic Era does not load or run without changes.

## Procedure

1. Copy the addon to `addons/<Name>/`.
2. Set `## Interface: 16001` in the TOC file.
3. Run `./waw check <Name>`. The output names each removed API and its replacement.
4. Fix the combat log findings first. See `docs/migration/combat-log.md`.
5. Fix the other findings. Read the return shape of each replacement, because many replacements return a table.
6. Update embedded libraries. For example, AceDB-3.0 needs revision 36 or later on Forever, according to the Decursive project.
7. Run `./waw test`, and add fakes in `tests/fakes.lua` until the smoke test passes.
8. Run the in-client layer. See `docs/testing.md`.

## Common replacements

The file `tools/wawlib/data/migrations.json` holds the full list. A test makes sure that each replacement exists on the pinned build.

| Old API | Replacement | Change |
| --- | --- | --- |
| `GetSpellInfo` | `C_Spell.GetSpellInfo` | Returns one table |
| `GetSpellCooldown` | `C_Spell.GetSpellCooldown` | Returns one table |
| `GetItemInfo` | `C_Item.GetItemInfo` | Returns `nil` until the data is cached |
| `GetContainerItemInfo` | `C_Container.GetContainerItemInfo` | Returns one table |
| `GetAddOnMetadata` | `C_AddOns.GetAddOnMetadata` | Same arguments |
| `IsAddOnLoaded` | `C_AddOns.IsAddOnLoaded` | Same arguments |
| `UnitAura` | `C_UnitAuras.GetAuraDataByIndex` | Returns one table, which can contain secret values |
| `SendAddonMessage` | `C_ChatInfo.SendAddonMessage` | Same purpose |
| `GetQuestLogTitle` | `C_QuestLog.GetInfo` | Returns one table |
| `GetPlayerMapPosition` | `C_Map.GetPlayerMapPosition` | Needs a map ID |
| `InterfaceOptions_AddCategory` | `Settings.RegisterAddOnCategory` | Uses the Settings API |

## Item and spell data

The client loads item and spell data on demand. The first query can return `nil`.

```lua
C_Item.RequestLoadItemDataByID(itemID)
-- Then wait for ITEM_DATA_LOAD_RESULT with this item ID and success = true.
```

Use `C_Spell.RequestLoadSpellData` and `SPELL_DATA_LOAD_RESULT` for spells.

## Game data

Forever content is not the same as Classic Era content. Do not copy spell IDs, item IDs, quest IDs or map IDs from another client without a test.

## Multiple clients

Some addons support Forever and other clients with one code base. Test for each API at runtime. If the file list differs, use a separate `_Camelot` TOC file. Add a `-- waw-ignore: migration-api` comment on a guarded call to an old API.
