---
name: wow-api-verify
description: Look up a game function, event, enum, widget method or CVar on the pinned WoW Forever build before code uses it. Not for finding code in this repository (use `wow-code-graph`).
---

# Look up a WoW Forever API

Do not write an API name from memory. The Forever API differs from Classic and from Midnight.

1. Call `wow_target_status` once per session. If MCP is not available, run `./waw target status`.
2. Call `wow_api_lookup` with the exact name. If MCP is not available, run `./waw api lookup NAME`.
3. Read `availability.status`. If the status is `absent` or `secure-only`, do not use the API.
4. If the status is `deprecated-shim`, use the replacement that the result names.
5. If the status is `documented-unconfirmed`, add an in-client test for the API.
6. Read `definition.flags`. If a flag starts with `Secret`, follow `docs/migration/secret-values.md`.
7. Read the return shape in `definition.returns`. Many modern APIs return one table.
8. If you do not know how to use the API, call `wow_ui_source_search` and read how Blizzard uses it.

If the name is not found, read the `similar` list. Do not guess a name.

An answer applies only to the build that it names.
