---
name: wow-test-client
description: Run tests in the real WoW Forever client, or read the Lua errors of a play session, through a /reload that the user types. Only after offline tests pass, or for an error that the user reports.
---

# Test in the real client

Run `./waw verify` first. If offline tests fail, do not ask the user to open the game.

Do not send keystrokes, mouse events or window automation to the client. Blizzard treats a program that presses keys as a Terms of Use violation. The user types every command in the game.

## Run in-game tests

1. Run `./waw ingame prepare`. Add `--probe` to record the runtime API.
2. Ask the user to type `/reload` and to wait for the `WAW result` line.
3. Ask the user to type `/reload` again.
4. Run `./waw ingame collect --wait 300`.
5. If the result warns about the build, tell the user.

## Read Lua errors

1. If this session has no prepared run, run `./waw ingame prepare`.
2. Ask the user to use the addon and then to type `/reload`.
3. Run `./waw ingame errors --wait 300`.
4. Read the message and the stack of each error.
5. Reproduce each error with an offline test. Then fix it.

Add `--all` to see errors from other addons. Do not fix the code of another addon.

For a blocked action, ask the user to type `/console taintLog 1`, then reproduce the problem. The errors command reads `Logs/taint.log`.
