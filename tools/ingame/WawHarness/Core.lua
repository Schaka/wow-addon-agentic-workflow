-- The in-client test harness. It runs only on a development client.
--
-- The client writes SavedVariables at /reload and at logout. The first /reload
-- loads new code and runs the tests. The second /reload writes the results.
-- This addon never sends input and never acts on the game world.

local MAX_RUNS = 5
local MAX_ERRORS = 200

WawHarness = { specs = {} }
local H = WawHarness
local manifest = WawHarnessManifest or { addons = {} }
local db

local session = { errors = {}, source = "seterrorhandler" }
local byMessage = {}
local currentRun

-- A message can be a secret value. This function always returns a plain string.
local function plainText(value)
  if issecretvalue and issecretvalue(value) then return "<secret>" end
  return tostring(value)
end

local function record(kind, message, stack, addon)
  message = plainText(message)
  local existing = byMessage[message]
  if existing then
    existing.count = existing.count + 1
    return
  end
  if #session.errors >= MAX_ERRORS then return end
  local entry = { kind = kind, message = message, stack = stack and plainText(stack) or nil, addon = addon,
                  time = time(), count = 1 }
  byMessage[message] = entry
  session.errors[#session.errors + 1] = entry
end

-- BugGrabber replaces seterrorhandler with an empty function. When BugGrabber
-- is present, this addon reads the BugGrabber database at logout.
if not BugGrabber then
  local previous = geterrorhandler()
  seterrorhandler(function(message)
    record("lua-error", message, debugstack(2))
    return previous(message)
  end)
end

local function importBugGrabber()
  if not (BugGrabber and BugGrabber.GetDB and BugGrabber.GetSessionId) then return end
  session.source = "BugGrabber"
  local id = BugGrabber:GetSessionId()
  for _, item in ipairs(BugGrabber:GetDB()) do
    if item.session == id then
      record("lua-error", item.message, tostring(item.stack or "") .. "\n" .. tostring(item.locals or ""))
      byMessage[plainText(item.message)].count = item.counter or 1
    end
  end
end

-- Assertions. The names match the offline test runner.
local function fail(message) error(message, 3) end
local assertions = setmetatable({
  equals = function(actual, expected)
    if actual ~= expected then fail("expected " .. tostring(expected) .. ", got " .. tostring(actual)) end
  end,
  is_true = function(v) if v ~= true then fail("expected true, got " .. tostring(v)) end end,
  is_false = function(v) if v ~= false then fail("expected false, got " .. tostring(v)) end end,
  is_nil = function(v) if v ~= nil then fail("expected nil, got " .. tostring(v)) end end,
  not_nil = function(v) if v == nil then fail("expected a value, got nil") end end,
  matches = function(text, pattern)
    if not tostring(text):find(pattern) then fail(tostring(text) .. " does not match " .. pattern) end
  end,
}, { __call = function(_, v, message)
  if not v then fail(message or "assertion failed") end
  return v
end })

-- A spec calls H.report to save data for the agent, for example a table of spell facts.
function H.report(key, value)
  if currentRun then
    currentRun.report = currentRun.report or {}
    currentRun.report[key] = value
  end
end

function H.define(addon, file, body)
  H.specs[#H.specs + 1] = { addon = addon, file = file, body = body }
end

local function safely(fn, ...)
  local ok, a = pcall(fn, ...)
  if ok then return a end
  return nil
end

local function captureProbe(run)
  local names = {}
  for key, value in pairs(_G) do
    if type(key) == "string" then
      if type(value) == "function" then
        names[#names + 1] = key
      elseif type(value) == "table" and key:sub(1, 2) == "C_" then
        for field, member in pairs(value) do
          if type(field) == "string" and type(member) == "function" then
            names[#names + 1] = key .. "." .. field
          end
        end
      end
    end
  end
  run.probe_functions = names
end

local function describeAddons()
  local out = {}
  for _, name in ipairs(manifest.addons) do
    local _, title, _, loadable, reason = C_AddOns.GetAddOnInfo(name)
    out[name] = { title = title, loadable = loadable, reason = reason, loaded = C_AddOns.IsAddOnLoaded(name) }
  end
  return out
end

local function finish(run, queue)
  local passed, failed = 0, 0
  for _, test in ipairs(queue) do
    if test.status == "pass" then passed = passed + 1 else failed = failed + 1 end
  end
  for _, test in ipairs(queue) do test.run = nil end
  run.tests = queue
  db.last_run_id = run.run_id
  print(string.format("WAW result: %d passed, %d failed, %d errors recorded. Type /reload to save.",
    passed, failed, #session.errors))
end

local function runQueue(run, queue, index)
  local test = queue[index]
  if not test then return finish(run, queue) end
  local function advance() runQueue(run, queue, index + 1) end

  if test.async then
    local settled = false
    local function settle(message)
      if settled then return end
      settled = true
      test.status = message and "fail" or "pass"
      test.error = message
      advance()
    end
    local ok, err = xpcall(function() test.run(function(message) settle(message) end) end,
      function(message) return plainText(message) .. "\n" .. debugstack(2) end)
    if not ok then return settle(err) end
    C_Timer.After(test.timeout or 5, function() settle("timed out") end)
  else
    local ok, err = xpcall(test.run, function(message) return plainText(message) .. "\n" .. debugstack(2) end)
    test.status = ok and "pass" or "fail"
    test.error = (not ok) and err or nil
    advance()
  end
end

function H.run()
  local run = {
    run_id = manifest.run_id,
    build = tonumber((select(2, GetBuildInfo()))),
    interface = select(4, GetBuildInfo()),
    project_id = WOW_PROJECT_ID,
    addons = describeAddons(),
    client_errors = session.errors,
    restrictions = {
      combat_log = safely(C_CombatLog.IsCombatLogRestricted),
      secrets = safely(C_Secrets.HasSecretRestrictions),
      in_combat = InCombatLockdown(),
      script_errors = safely(GetCVar, "scriptErrors"),
    },
  }
  currentRun = run
  db.runs[manifest.run_id] = run
  db.order[#db.order + 1] = manifest.run_id
  while #db.order > MAX_RUNS do
    db.runs[table.remove(db.order, 1)] = nil
  end
  if manifest.probe then captureProbe(run) end

  local queue = {}
  for _, spec in ipairs(H.specs) do
    local names = {}
    local env = setmetatable({ assert = assertions, report = H.report }, { __index = _G, __newindex = _G })
    local function add(name, body, async, timeout)
      queue[#queue + 1] = { addon = spec.addon, file = spec.file, name = table.concat(names, " > ") .. " > " .. name,
                            run = body, async = async, timeout = timeout }
    end
    function env.describe(name, body)
      names[#names + 1] = name
      body()
      names[#names] = nil
    end
    function env.it(name, body) add(name, body, false) end
    function env.it_async(name, body, timeout) add(name, body, true, timeout) end
    setfenv(spec.body, env)
    local ok, err = xpcall(spec.body, function(message) return plainText(message) .. "\n" .. debugstack(2) end)
    if not ok then
      queue[#queue + 1] = { addon = spec.addon, file = spec.file, name = "load " .. spec.file, status = "fail", error = err,
                            run = function() error(err, 0) end }
    end
  end
  runQueue(run, queue, 1)
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterEvent("PLAYER_LOGOUT")
frame:RegisterEvent("ADDON_ACTION_BLOCKED")
frame:RegisterEvent("ADDON_ACTION_FORBIDDEN")
frame:RegisterEvent("LUA_WARNING")
frame:SetScript("OnEvent", function(_, event, first, second)
  if event == "ADDON_LOADED" and first == "!WawHarness" then
    WawHarnessDB = WawHarnessDB or {}
    db = WawHarnessDB
    db.runs = db.runs or {}
    db.order = db.order or {}
  elseif event == "PLAYER_LOGIN" then
    session.build = tonumber((select(2, GetBuildInfo())))
    session.started = time()
    db.session = session
    if manifest.run_id and manifest.run_id ~= db.last_run_id then
      C_Timer.After(1, H.run)
    end
  elseif event == "PLAYER_LOGOUT" then
    importBugGrabber()
    if currentRun then currentRun.client_errors = session.errors end
  elseif event == "ADDON_ACTION_BLOCKED" or event == "ADDON_ACTION_FORBIDDEN" then
    record(event, plainText(first) .. " tried to call " .. plainText(second), debugstack(2), plainText(first))
  elseif event == "LUA_WARNING" then
    record(event, first)
  end
end)

SLASH_WAW1 = "/waw"
SlashCmdList.WAW = function(text)
  if text == "run" then
    H.run()
  else
    print(string.format("WAW: run %s, %d errors this session. Commands: /waw run", tostring(manifest.run_id), #session.errors))
  end
end
