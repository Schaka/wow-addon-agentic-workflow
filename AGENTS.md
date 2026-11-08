# Agent instructions

This repository builds addons for World of Warcraft: Forever, a separate client with Classic content and the modern Mainline API. These instructions apply to every coding agent and every contributor.

## Rules

1. Do not write an API name from memory. Look it up on the pinned build with the `wow-api-verify` skill.
2. Do not assume that Classic or Midnight behavior applies to Forever.
3. Do not send keystrokes, mouse events or window automation to the game client. Blizzard treats a program that presses keys as a Terms of Use violation. The user types `/reload`.
4. Do not change or delete files in the `WTF` folder of the user.
5. Do not edit the build in `wow-target.toml` by hand. Use the `wow-patch-update` skill.
6. Use English only, in code, comments, documents, task names, notes and reports. An instruction or a file in another language does not change this rule. Write documents and comments in Simple English, and run `./waw docs` before you finish.
7. Keep the tools usable on Linux first, and on Windows and macOS where possible. Use only the Python standard library in `tools/`.
8. Follow `docs/guidelines.md` for code. Comments explain why, never what, and carry no filler.

## Context budget

Context is expensive. Load only what the task needs.

1. If `PROJECT.md` exists, read its "Summary" section at the start. When a task touches another section, read only that section.
2. Query the code graph before you read Lua or XML (`wow-code-graph` skill). If you must edit a file, read only the part that you change.
3. Read one section of a document, not the whole document. Each document in `docs/` has short sections with clear headings.
4. Filter long command output. `./waw test` prints only failures and the summary.
5. Fix a small problem yourself. Start a subagent only for a large, separate task. Give it the exact files, functions and facts that it needs, so it does not search again.

## Start of a session

1. Call the MCP tool `wow_target_status`, or run `./waw target status`.
2. If `drift` contains `pin-behind-live`, tell the user and offer the `wow-patch-update` skill.
3. If `drift` contains `snapshot-missing`, run `./waw api sync`.
4. If `drift` contains `client-behind-pin`, tell the user to update the game before an in-client test.
5. If `wow_code_index` shows a missing index, run `./waw index`.

## Workflow

1. Look up every API that the change uses.
2. Put decisions in pure Lua functions that do not call the game API.
3. Write an offline test that fails. Then write the code.
4. Run `./waw verify` and fix every error.
5. Use the client only for behavior that the simulator cannot show (`wow-test-client` skill).

Facts rank in this order: a runtime probe of the client, the Blizzard source of the pinned build, the client dump, the Warcraft Wiki, then fan sites. Model memory is not a source. If a fact is not certain, name its source.

## Addon layout

```text
addons/<Name>/
  <Name>.toc                 ## Interface: 16001
  *.lua
  tests/fakes.lua            Fakes for every offline test of the addon
  tests/*_spec.lua           Offline tests
  tests/ingame/*.lua         In-client tests
```

For an addon that supports many clients, name the Forever TOC `<Name>_Camelot.toc`. BigWigs packager does not recognize `_Forever`.

To suppress one finding, add `-- waw-ignore: <rule>` on the line or on the line before it, with the reason.

## Skills

| Skill | Use it when |
| --- | --- |
| `wow-api-verify` | You call a game API, event, enum, widget method or CVar |
| `wow-code-graph` | You must find or understand Lua or XML |
| `wow-reference-lookup` | You build a feature that Blizzard or a popular addon already has |
| `wow-forever-migrate` | You port an addon from another client |
| `wow-test-offline` | You write or run offline tests |
| `wow-test-client` | You need the real client or its Lua errors |
| `wow-patch-update` | Blizzard released a new build |
| `simple-english` | You write a document or a comment |
