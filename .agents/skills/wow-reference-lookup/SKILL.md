---
name: wow-reference-lookup
description: Find how Blizzard or a popular addon already builds a UI feature, such as a health bar, cast bar, aura display, unit frame or nameplate, before you write your own. Not for single API lookups.
---

# Look up a reference implementation

Do not invent a solution for a solved problem. Search in this order:

1. Blizzard FrameXML in `wow-framexml-<product>-<build>`. This code runs on the pinned build, so it is the first reference.
2. `wow-ref-ouf`, for small unit frame elements.
3. `wow-ref-elvui`, for a complete modern UI.
4. `wow-ref-dbm`, for client detection and restrictions. Run `./waw index --ref DBM` to add it.

To search a project:

1. Call `search_graph` with a short query, for example `unit frame health bar update`. Add `file_pattern` to narrow the result.
2. Call `search_code` for an API name, for example `SetCooldownFromDurationObject`.
3. Read one function with `get_code_snippet`.
4. Call `wow_api_lookup` for every API that you plan to use. A reference addon can target another client.

Follow these rules for licenses:

1. Blizzard code is a reference. Do not copy it into an addon.
2. If you keep its MIT notice, you can adapt oUF code.
3. ElvUI and DBM use custom licenses. Learn the approach, and write your own code.

Reference addons can be out of date for Forever. If a reference uses an API that the pinned build does not have, use the approach only.
