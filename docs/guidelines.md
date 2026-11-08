# Code guidelines

These rules apply to addon code in this repository and in every repository made from it. They aim at code that a person can read quickly, and that an agent can change safely.

## Readability

1. Write code that explains itself. Choose names that say what a value is or what a function does.
2. Keep functions short. If a function needs a comment to separate its parts, split it.
3. Prefer early returns to deep nesting.
4. Use one style for each thing. Do not mix `local function f` and `local f = function` in one file.
5. Keep lines under 120 characters.

## Comments

Do not over-comment. If a comment does not tell the reader something that the code cannot, delete it. The policy of the organization requires clear and thorough comments, so be thorough about reasons and silent about mechanics:

1. Explain why: a business rule, a client restriction, a workaround, an order that matters, or a value that looks arbitrary. These comments are required.
2. Name the evidence for a client fact: the build, the date, a Blizzard file and line, or an in-game error.
3. Give each file a header of one to three lines: what the module is for.
4. Mark security-relevant code: taint, protected frames, secure templates, combat lockdown, data that other players send, and SavedVariables that a user can edit.
5. Do not repeat what the code does. `-- Set the texture` above `icon:SetTexture(texture)` is noise.
6. Do not write documentation blocks that list parameters and returns that the names already show.
7. Do not write filler: no summaries of the obvious, no restated goals, no "this function handles", no multi-paragraph essays. If a reason needs more than three lines, it belongs in `PROJECT.md` or a document, with a short pointer in the code.
8. If you change code, update or delete its comment. A wrong comment is worse than none.

Example of a useful comment:

```lua
-- An enemy uses the container from the start. In combat its aura data becomes secret with the
-- first aura event, and a late switch misses that aura (in-game test, build 70862).
if Secret.IsTrue(UnitCanAttack("player", unit)) then
```

## Structure of an addon

1. Start each file with `local addonName, ns = ...`. Share state through `ns`. Create no globals, except SavedVariables, slash commands, and frames that Blizzard code must find by name.
2. Give each module one table on `ns`, for example `ns.HealthBar`. A module owns its frames and its events.
3. Separate logic from the game. Put decisions in functions that take values and return values. Keep the code that calls the game API thin. Then offline tests can cover the decisions.
4. Keep data apart from code. Spell tables, defaults and localization go in their own files.
5. Load order is the order in the TOC file. Put shared helpers first. Do not depend on another addon's load order. Use `## Dependencies` or `## OptionalDeps`.
6. Prefer Lua to XML for frames. Use XML only for templates that Blizzard code or several frames share.

## Lua and client basics

1. Use Lua 5.1 only. Do not use `goto`, `//` or bitwise operators. LuaJIT accepts `goto`, so only `./waw check` finds this error.
2. Do not use `require`, `dofile`, `io` or `os`. The client does not have them.
3. Pass a value that can be secret directly to a widget. Guard every other use with `issecretvalue`.
4. Request item and spell data, and wait for `ITEM_DATA_LOAD_RESULT` or `SPELL_DATA_LOAD_RESULT`. The first query can return `nil`.

## Events

1. Use one event frame for each module, and a handler table keyed by event name.
2. Use `RegisterUnitEvent` for unit events, so the client filters the units.
3. Register an event only while a feature needs it. When the feature turns off, unregister it.
4. Do not poll with `OnUpdate` for data that an event delivers. If a timer is necessary, use `C_Timer` and stop it when it is not needed.
5. Guard every field of an event payload that can be secret. See `docs/migration/secret-values.md`.

## SavedVariables

1. Read SavedVariables in `ADDON_LOADED` for your own addon. They do not exist earlier.
2. Store a version number. Migrate old data in one function that runs at load.
3. Fill missing values from a defaults table. Do not replace the table of the user.
4. Treat the data as untrusted input. A user can edit the file, and an old version can leave other shapes. Check types before use.

## Combat and taint

1. Do not change protected frames in combat. Test `InCombatLockdown()`, queue the change, and apply it on `PLAYER_REGEN_ENABLED`.
2. Do not write fields or call methods on Blizzard frames unless you must. Every write can spread taint into Blizzard code.
3. Hook Blizzard functions with `hooksecurefunc`, not by replacing them.
4. To hide a Blizzard frame, prefer the frame's own configuration or `UnregisterAllEvents` and a hook on `Show`. Do not change its parent.
5. Read the Blizzard structure of a frame in the FrameXML code graph before you depend on it. Names change between clients.

## Performance

1. Do not create tables or closures in code that runs on every frame or every event of a busy unit. Reuse tables.
2. Cache API functions in locals only in code that runs often.
3. If a value did not change, do not update its widget.
4. Throttle work that events can trigger many times per second, such as `UNIT_AURA` on nameplates.

## Libraries

1. Use an established library before you write your own: LibStub, Ace3, LibSharedMedia, DRList and others.
2. Embed libraries in `Libs/` and list them in the TOC or an XML file. Do not edit an embedded library. If it needs a fix for Forever, offer the fix upstream and record the patch in `PROJECT.md`.
3. Check that a library supports Forever before you depend on it. Many libraries test `WOW_PROJECT_ID` and do not know project ID 18.

## Data from other players

Addon messages and chat come from other players. Treat them as untrusted input:

1. Check the prefix, the sender and the size.
2. Parse with patterns that cannot fail on bad input. Do not use `loadstring` on received text.
3. Limit what one message can change.

## Tests

1. Write an offline test for each decision function.
2. Write an in-game spec for each fact about the client that the design depends on.
3. Fix the cause of a failure. Do not add a `waw-ignore` comment unless the code is guarded at runtime, and give the reason in the same comment.
