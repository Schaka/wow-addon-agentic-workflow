-- ./waw check validates game API names against the pinned build.
-- Luacheck handles code quality, so it ignores global access here.
std = "lua51"
max_line_length = false
ignore = { "11.", "21./_.*", "212" }
exclude_files = { ".waw/", "dist/", "tools/tests/fixtures/", "**/Libs/" }
