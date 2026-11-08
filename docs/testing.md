# Testing

The tests run in layers. Fix each layer before you go to the next one. A problem found offline costs seconds. A problem found in the client costs a `/reload` by a person.

| Layer | Command | Needs the game | Finds |
| --- | --- | --- | --- |
| 1. Static analysis | `./waw check` | No | Removed APIs, old combat log code, unknown events, TOC errors, XML errors, syntax that is not Lua 5.1 |
| 2. Offline tests | `./waw test` | No | Logic errors, load order errors, errors at login, secret value misuse |
| 3. In-client tests | `./waw ingame prepare` and `collect` | Yes | Real API behavior, real restrictions |
| 4. Session errors | `./waw ingame errors` | Yes | Lua errors during real use |

Run layers 1 and 2 with `./waw verify`.

## Static analysis

The analysis compares each addon with the snapshot of the pinned build. It reports these problems as errors:

1. An API or event that the build does not have.
2. An API that only Blizzard code can call.
3. An old API that has a known replacement.
4. A TOC file with the wrong interface value or a missing file.
5. Syntax that exists in LuaJIT or Lua 5.2 but not in Lua 5.1.

If a value that can be secret reaches an operator, the analysis reports a warning. This warning is a heuristic. It follows only simple local variables.

If `luacheck` is installed, `./waw check` also runs it.

### Configuration of the static analysis

An addon repository can set these keys in the `[checks]` section of `wow-target.toml`:

| Key | Purpose |
| --- | --- |
| `custom_event_prefixes` | A list of prefixes. An event name that starts with one of them is an event of the addon itself. The analysis does not look it up on the build. |
| `optional_globals` | A list of global names that an optional addon defines, for example `["BigDebuffs"]`. Without an entry, the rule `api-global` warns about a table that nothing defines. |
| `generated_global_prefixes` | A list of prefixes. A global name that starts with one of them is created at runtime, for example by `CreateFrame` with a name from a table. The rule `api-global` does not warn about it. |
| `extra_globals` | A list of global names that the analysis must treat as defined. |
| `secret_guards` | A list of function names that guard a secret value, for example `["Secret.Key", "Secret.Fraction"]`. A name matches a call that equals it or ends with it after a dot. A local alias needs its own entry. The built-in guards are `issecretvalue` and `canaccessvalue`. |

The secret value warning checks one file at a time. A guard anywhere in a file clears the warning for that name in the whole file. To suppress one finding, use `-- waw-ignore: secret-compare` and give the reason.

## Offline tests

The simulator is `tools/lua/wowsim.lua`. It loads the addon in TOC order in a sandbox. The sandbox has no `io`, `os` or `require`, like the client.

It uses the snapshot to decide what exists:

1. A name that the build does not have reads as `nil`, like the client.
2. A name that exists but has no fake raises an error that names the function. A test cannot pass by accident.
3. `RegisterEvent` rejects unknown events and restricted events.
4. `CreateFrame` returns an object that accepts every widget method of the build and rejects other methods.

A fake is a small test replacement for a game function. Put the fakes that every test needs in `tests/fakes.lua`. The fakes of the addons in `## Dependencies` run first, so a dependent addon does not repeat them.

Each addon gets a smoke test without extra code. The smoke test loads every TOC file, then simulates login, five seconds of timers and logout.

Offline tests can use these helpers:

| Helper | Purpose |
| --- | --- |
| `wow.load(name)` | Load an addon and return its namespace table |
| `wow.login({ name })` | Fire `ADDON_LOADED`, `PLAYER_LOGIN` and `PLAYER_ENTERING_WORLD` |
| `wow.logout()` | Fire `PLAYER_LOGOUT` and store SavedVariables |
| `wow.fire(event, ...)` | Fire an event |
| `wow.advance(seconds)` | Run the timers for that time |
| `wow.stub(name, fn)` | Add a fake. The name must exist on the build. |
| `wow.secret(value)` | Create a secret value |
| `wow.secret_table(table)` | Create a secret table. Index, `#`, `pairs`, `ipairs` and `next` raise the error of the client. `type` still returns `table`, and `issecrettable` returns true. |
| `wow.strict_compare(false)` | Turn off the rewrite of `name.field == true` for the addons that load next. The rewrite is on by default. |
| `wow.saved.Name = value` | Set SavedVariables before login |
| `wow.set_combat(true)` | Enter combat |

### Secret values in a test

A payload can be readable and still hold secret parts. The event `UNIT_AURA` is the main example. In the client, `updateInfo` can be a plain table with `isFullUpdate` as a secret boolean and `addedAuras` as a secret table. Build this payload in a test:

```lua
wow.fire("UNIT_AURA", "target", {
  isFullUpdate = wow.secret(true),
  addedAuras = wow.secret_table({ { auraInstanceID = 1 } }),
})
```

The simulator raises an error for these reads of a secret table: index, `#`, `pairs`, `ipairs` and `next`.

A secret boolean cannot raise in `if x then` or in `x == true`, because plain Lua gives no hook for them. The loader closes the second gap in part. It rewrites the plain pattern `name.field == true` (also `== false`, `~= true` and `~= false`) in the addon source, so that it raises an error for a secret value. The rewrite skips strings and comments, keeps all line breaks, and works only if the token before the operand binds weaker than `==`. Turn it off with `wow.strict_compare(false)` before `wow.load`.

The static rule `secret-bool-compare` of `./waw check` covers the same pattern in the source, also in code that no test runs. It uses the boolean fields of the payload of every event with a `Secret*` flag, and the boolean fields of the result of a function with a `Secret*` flag that the same file calls.

### Limits of the simulator

The simulator does not replace the client. Plain Lua cannot show some behavior:

| Behavior | Result in the simulator |
| --- | --- |
| `secret == 5` | Returns false and raises no error. The client raises an error. |
| `secret == true` or `secret == false` | Raises an error only for the plain pattern `name.field == true` that the loader rewrites. A comparison with a variable, `secret ~= nil` or a call result returns false without an error. |
| A truth test on a secret boolean (`if x then`, `not x`, `x and y`) | Passes. The client raises an error. Only the static rule and a test in the client can find it. |
| A secret value as a table key | Passes. The client raises an error. |
| Which fields of a payload are secret | The test decides. The client decides by restrictions at that moment. Run the in-client probe to learn the real case. |
| `issecretvalue` of a secret table | The simulator returns false and `issecrettable` returns true. Check this in the client with the probe. |
| Frames defined in XML | The simulator runs XML `Script` files but does not create the frames. |
| A frame that the client fills, such as an `AuraContainer` | Not simulated. Fake only the methods that the code calls, with the documented names. |
| Taint and protected actions | Not simulated. |
| FrameXML code | Not simulated. Use `wow.stub`. |
| Real game data | Not simulated. Spell and item data come from fakes. |

## In-client tests

The test addon is `tools/ingame/WawHarness`. The tool installs it as `!WawHarness`, so that it loads before normal addons and records their load errors.

The client reads Lua at login and at `/reload`. It writes SavedVariables at `/reload` and at logout. One test run therefore needs two reloads:

1. Run `./waw ingame prepare`.
2. Type `/reload` in the client. The new code loads and the tests run.
3. Wait for the `WAW result` line.
4. Type `/reload` again. The client writes the results.
5. Run `./waw ingame collect --wait 300`.

A `/reload` also finds a new addon folder (build 70862, seen 2026-11-08).

Write in-client tests in `addons/<Name>/tests/ingame/`. They can use `describe`, `it`, `it_async` and `assert`.

To force restrictions during a test, type one of these commands in the client. A client restart resets these CVars.

```text
/console addonCombatRestrictionsForced 1
/console addonEncounterRestrictionsForced 1
/console addonChatRestrictionsForced 1
```

## Session errors

The test addon records Lua errors, blocked actions and Lua warnings for the whole session. BugGrabber disables `seterrorhandler`. With BugGrabber installed, the test addon reads the BugGrabber database.

1. Run `./waw ingame prepare`.
2. Use the addon in the client.
3. Type `/reload`.
4. Run `./waw ingame errors --wait 300`.

The command shows errors from this repository first. It also reads `Logs/FrameXML.log` and `Logs/taint.log`. To see errors from other addons, add `--all`.

To write taint data to `Logs/taint.log`, type `/console taintLog 1` and reload. Taint is the mark that the client puts on values that addon code touched.

## Runtime probe

Run `./waw ingame prepare --probe`, then do a normal test run. The client records every global function and every `C_` function that it exposes. `./waw ingame collect` saves this list, and the API tools then treat it as the best evidence for that build.

## Do not automate the client

Do not add tools that press keys, move the mouse or read the screen of the game. Blizzard treats a program that presses keys as a Terms of Use violation. A person types `/reload`.
