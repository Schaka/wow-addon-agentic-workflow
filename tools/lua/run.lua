-- The offline test runner. Usage: lua run.lua <manifest.lua> [name filter]
-- Every test gets a new simulator. Each addon also gets a built-in smoke test.
local wowsim = require("wowsim")

local manifest_path, filter = arg[1], arg[2]
local api = dofile(manifest_path)

local passed, failed, pending = 0, 0, 0
local failures = {}

local function deep_equal(a, b, seen)
  if a == b then return true end
  if type(a) ~= "table" or type(b) ~= "table" then return false end
  seen = seen or {}
  if seen[a] == b then return true end
  seen[a] = b
  for k, v in pairs(a) do
    if not deep_equal(v, b[k], seen) then return false end
  end
  for k in pairs(b) do
    if a[k] == nil then return false end
  end
  return true
end

local function show(v)
  if type(v) == "string" then return string.format("%q", v) end
  return tostring(v)
end

local function fail(message) error(message, 3) end

local assertions = setmetatable({
  equals = function(actual, expected)
    if actual ~= expected then fail("expected " .. show(expected) .. ", got " .. show(actual)) end
  end,
  same = function(actual, expected)
    if not deep_equal(actual, expected) then fail("tables differ") end
  end,
  is_true = function(v) if v ~= true then fail("expected true, got " .. show(v)) end end,
  is_false = function(v) if v ~= false then fail("expected false, got " .. show(v)) end end,
  is_nil = function(v) if v ~= nil then fail("expected nil, got " .. show(v)) end end,
  not_nil = function(v) if v == nil then fail("expected a value, got nil") end end,
  matches = function(text, pattern)
    if not tostring(text):find(pattern) then fail(show(text) .. " does not match " .. show(pattern)) end
  end,
  errors = function(fn, pattern)
    local ok, err = pcall(fn)
    if ok then fail("expected an error") end
    if pattern and not tostring(err):find(pattern) then fail("error " .. show(err) .. " does not match " .. show(pattern)) end
  end,
}, { __call = function(_, v, message)
  if not v then fail(message or "assertion failed") end
  return v
end })

local current_sim
local wow = setmetatable({}, { __index = function(_, key)
  local value = current_sim[key]
  if type(value) == "function" then
    return function(...) return value(current_sim, ...) end
  end
  return value
end })

-- tests/fakes.lua holds the fakes that an addon needs in every test.
-- The fakes of the addons in "## Dependencies" run first. A dependent addon needs them too, because the
-- simulator loads the dependencies. An own fake of the dependent addon replaces the inherited one.
local function apply_fakes(addon, applied)
  applied = applied or {}
  if applied[addon] or not api.addons[addon] then return end
  applied[addon] = true
  for _, dependency in ipairs(api.addons[addon].deps or {}) do apply_fakes(dependency, applied) end
  local path = api.addons[addon].fakes
  if not path then return end
  local chunk, syntax = loadfile(path)
  if not chunk then error(syntax, 0) end
  setfenv(chunk, setmetatable({ wow = wow }, { __index = _G }))
  chunk()
end

local function run_test(addon, label, body)
  if filter and not label:find(filter, 1, true) then return end
  current_sim = wowsim.new(api)
  local ok, err = xpcall(function()
    apply_fakes(addon)
    body()
  end, function(message) return debug.traceback(tostring(message), 2) end)
  if ok then
    passed = passed + 1
    if os.getenv("WAW_VERBOSE") then print("[pass] " .. label) end
  else
    failed = failed + 1
    failures[#failures + 1] = label .. "\n    " .. tostring(err):gsub("\n", "\n    ")
    print("[FAIL] " .. label)
  end
end

local function load_spec(addon, path)
  local stack, tests = {}, {}
  local before = {}
  local spec_env = setmetatable({ wow = wow, assert = assertions }, { __index = _G })

  function spec_env.describe(name, body)
    stack[#stack + 1] = name
    local mark = #before
    body()
    for i = #before, mark + 1, -1 do before[i] = nil end
    stack[#stack] = nil
  end
  function spec_env.before_each(fn) before[#before + 1] = fn end
  function spec_env.it(name, body)
    local hooks = { unpack(before) }
    tests[#tests + 1] = { label = addon .. " :: " .. table.concat(stack, " > ") .. " > " .. name, hooks = hooks, body = body }
  end
  function spec_env.pending(name)
    pending = pending + 1
    print("[todo] " .. addon .. " :: " .. name)
  end

  local chunk, syntax = loadfile(path)
  if not chunk then
    failed = failed + 1
    failures[#failures + 1] = path .. "\n    " .. tostring(syntax)
    print("[FAIL] " .. path)
    return
  end
  setfenv(chunk, spec_env)
  chunk()
  for _, test in ipairs(tests) do
    run_test(addon, test.label, function()
      for _, hook in ipairs(test.hooks) do hook() end
      test.body()
    end)
  end
end

local names = {}
for _, name in ipairs(api.selected or {}) do names[#names + 1] = name end
table.sort(names)

for _, name in ipairs(names) do
  run_test(name, name .. " :: smoke > loads every TOC file and survives login and logout", function()
    local order = wow.load_with_deps(name)
    wow.login(order)
    wow.advance(5)
    wow.logout()
    if #current_sim.errors > 0 then error(table.concat(current_sim.errors, "\n")) end
  end)
  for _, spec in ipairs(api.addons[name].specs) do load_spec(name, spec) end
end

print(string.format("%d passed, %d failed, %d pending (offline simulator, build %d)", passed, failed, pending, api.build))
if #failures > 0 then
  print("\nFailures:")
  for _, text in ipairs(failures) do print("* " .. text) end
  os.exit(1)
end
os.exit(0)
