---
name: wow-forever-migrate
description: Port an addon from Classic, TBC, Midnight or another client to WoW Forever: removed APIs, the old combat log, secret values and TOC changes. Not for new addons.
---

# Port an addon to WoW Forever

1. Read the procedure in `docs/migration/api-changes.md`. In `docs/migration/field-notes.md`, read the sections "What addon code can read", "Four tools that still work" and "Dead ends", and the one recipe for the feature that you port. Skip the other sections.
2. Copy the addon to `addons/<Name>/` and set `## Interface: 16001`.
3. Run `./waw check <Name>`.
4. If a finding names the combat log, follow `docs/migration/combat-log.md`.
5. If an API can return a secret value, follow `docs/migration/secret-values.md`.
6. For each finding, call `wow_migration_lookup` and `wow_api_lookup`. Compare the old and new return shapes.
7. Run `./waw test`. Add fakes to `tests/fakes.lua` until the smoke test passes.
8. Use the `wow-test-client` skill for real behavior.

Do not hide a finding with `waw-ignore` unless the call is guarded at runtime.

If a feature has no replacement, tell the user. Do not build a workaround that reads protected data.

Do not copy spell, item, quest or map IDs from another client without a test.

When a port finds a new fact in the client, add it to `docs/migration/field-notes.md` in the template. Name the build and the evidence. Then run `./waw sync-tools` for the addon repositories.
