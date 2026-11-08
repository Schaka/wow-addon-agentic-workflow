---
name: wow-test-offline
description: Write or run offline Lua tests with the WoW simulator: specs, fakes, secret value tests, load order errors. Not for tests in the real client.
---

# Test an addon offline

Read `docs/testing.md` for the list of helpers and the limits of the simulator.

1. Put decisions in a pure Lua file that does not call the game API.
2. Write a failing test in `addons/<Name>/tests/<topic>_spec.lua`.
3. Run `./waw test <Name> --filter TEXT`.
4. Write the code until the test passes.
5. Run `./waw verify`.

If an error names a missing fake, add one with `wow.stub`. Do not add other fakes. Put a fake that every test needs in `tests/fakes.lua`.

If a value can be secret, add a test that uses `wow.secret`. The simulator does not find `secret == 5`, so read each equality test by hand.

Offline tests do not prove behavior that depends on taint, FrameXML or real game data. Use the `wow-test-client` skill for those cases.
