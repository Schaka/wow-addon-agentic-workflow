-- Checks of the secret value support in the simulator. Usage: lua secret_sim.lua <addon directory>
-- The test writes one small addon file, loads it, and prints "ok" if every check passes.
local wowsim = require("wowsim")
local dir = arg[1]

local api = {
  version = "1.0.0", build = 1, interface = 16001, enums = {}, restricted_events = {}, events = { UNIT_AURA = true },
  templates = {}, widget_methods = {}, functions = {}, ui_globals = {}, cvars = {},
  addons = { Demo = { dir = dir, saved = {}, deps = {}, files = { { lua = "Demo.lua" } } } },
}

local function check(condition, message) if not condition then error("FAILED: " .. message, 0) end end
local function raises(fn, pattern)
  local ok, err = pcall(fn)
  check(not ok, "expected an error for " .. pattern)
  check(tostring(err):find(pattern), "error text " .. tostring(err) .. " does not match " .. pattern)
end

-- The addon reads the payload like a careless addon does.
local handle = assert(io.open(dir .. "/Demo.lua", "w"))
handle:write([[
local addonName, ns = ...
function ns.Full(info) return info.isFullUpdate == true end
function ns.NotFull(info) return info.isFullUpdate ~= false end
function ns.Text() return "info.isFullUpdate == true" end -- info.isFullUpdate == true
function ns.Chained(a, info) return a == info.flag == true end
function ns.Loop(list) local n = 0 for _ in ipairs(list) do n = n + 1 end return n end
function ns.Size(list) return #list end
function ns.Pairs(list) local n = 0 for _ in pairs(list) do n = n + 1 end return n end
]])
handle:close()

local sim = wowsim.new(api)
local ns = sim:load("Demo")

-- A secret table raises for index, length, pairs and ipairs. It still has the type table.
local list = sim:secret_table({ 1, 2, 3 })
check(sim.env.type(list) == "table", "type of a secret table")
check(sim.env.issecrettable(list) == true, "issecrettable")
check(sim.env.issecrettable({}) == false, "issecrettable of a plain table")
raises(function() return list[1] end, "secret table")
raises(function() return ns.Size(list) end, "get the length of a secret table")
raises(function() return ns.Loop(list) end, "iterate over a secret table")
raises(function() return ns.Pairs(list) end, "iterate over a secret table")
check(ns.Loop({ 1, 2 }) == 2, "ipairs of a plain table still works")

-- The loader rewrite makes "secret == true" raise. A readable value behaves as before.
check(ns.Full({ isFullUpdate = true }) == true, "readable true")
check(ns.Full({ isFullUpdate = false }) == false, "readable false")
check(ns.NotFull({ isFullUpdate = false }) == false, "readable ~= false")
raises(function() return ns.Full({ isFullUpdate = sim:secret(true) }) end, "secret boolean value")
raises(function() return ns.NotFull({ isFullUpdate = sim:secret(false) }) end, "secret boolean value")
check(ns.Text() == "info.isFullUpdate == true", "a string is not rewritten")
check(ns.Chained(1, { flag = 1 }) == true, "a chained comparison is not rewritten")

-- With the rewrite off, the plain Lua result returns without an error. This is the gap that the static rule covers.
local plain = wowsim.new(api)
plain:strict_compare(false)
local plain_ns = plain:load("Demo")
check(plain_ns.Full({ isFullUpdate = plain:secret(true) }) == false, "no error without the rewrite")

-- A secret boolean raises for the operations that Lua can intercept.
local flag = sim:secret(true)
raises(function() return flag .. "x" end, "concatenate")
raises(function() return flag + 1 end, "arithmetic")
print("ok")
