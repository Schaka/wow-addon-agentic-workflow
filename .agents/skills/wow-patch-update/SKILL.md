---
name: wow-patch-update
description: Move this repository to a new WoW Forever build. Use it after a Blizzard patch, or for target drift. Not for normal addon work.
---

# Update to a new build

1. Run `./waw target status`.
2. Run `./waw api sync --latest`.
3. If the output shows the same build as the pin, the UI source is not ready. Stop and tell the user.
4. Run `./waw api diff --summary`. Then run `./waw api diff` and read the removed and changed items.
5. Run `./waw check --build latest` and `./waw test --build latest`.
6. Fix each error. Look up changed APIs with the `wow-api-verify` skill.
7. Update `tools/wawlib/data/migrations.json` for each API that Blizzard removed.
8. Run `./waw target bump`.
9. Run `./waw index`. The new build gets its own shared FrameXML index.
10. If the interface value changed, edit `interface` in `wow-target.toml` and every TOC file.
11. Run `./waw verify` and `python3 tools/tests/test_waw.py`.
12. Run the in-client layer. Use `--probe` for a new build.
13. If a fact changed, update `docs/platform.md`.

Do not bump the pin before the review. The pin states that a person or an agent reviewed the build.
