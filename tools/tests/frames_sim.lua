-- Checks of frame visibility in the simulator. Usage: lua frames_sim.lua
-- The test prints "ok" if every check passes.
local wowsim = require("wowsim")

local api = {
  version = "1.0.0", build = 1, interface = 16001, restricted_events = {}, templates = {}, widget_methods = {},
  ui_globals = {}, cvars = {}, addons = {}, enums = {}, events = {}, functions = {},
}

local function check(condition, message) if not condition then error("FAILED: " .. message, 0) end end

local sim = wowsim.new(api)
local env = sim.env

local parent = env.CreateFrame("Frame")
local child = env.CreateFrame("Frame", nil, parent)
check(child:IsVisible(), "a shown child of a shown parent is visible")
parent:Hide()
check(child:IsShown() and not child:IsVisible(), "a hidden parent hides the child")
local other = env.CreateFrame("Frame")
child:SetParent(other)
check(child:GetParent() == other and child:IsVisible(), "SetParent moves the child to a shown parent")

print("ok")
