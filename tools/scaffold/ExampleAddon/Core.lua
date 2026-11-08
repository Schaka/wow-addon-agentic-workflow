-- Game integration. Keep this file thin and put decisions in Logic.lua.
local addonName, ns = ...

local frame = CreateFrame("Frame")
local bar = CreateFrame("StatusBar", nil, UIParent)
local label = bar:CreateFontString(nil, "OVERLAY", "GameFontNormal")

-- UnitHealth can return a secret value. A widget accepts a secret value.
-- Addon code must not do arithmetic on it or compare it.
function ns.UpdateHealth()
  local current = UnitHealth("player")
  local maximum = UnitHealthMax("player")
  bar:SetMinMaxValues(0, maximum)
  bar:SetValue(current)
  if issecretvalue(current) or issecretvalue(maximum) then
    label:SetText("")
  elseif ns.db.showPercent then
    label:SetText(ns.FormatPercent(current, maximum))
  end
end

local handlers = {}

-- SavedVariables exist only after ADDON_LOADED for this addon.
function handlers.ADDON_LOADED(name)
  if name ~= addonName then return end
  ExampleAddonDB = ns.ApplyDefaults(ExampleAddonDB or {}, ns.defaults)
  ns.db = ExampleAddonDB
  frame:UnregisterEvent("ADDON_LOADED")
end

function handlers.PLAYER_LOGIN()
  ns.db.greeted = ns.db.greeted + 1
  ns.UpdateHealth()
end

function handlers.UNIT_HEALTH()
  ns.UpdateHealth()
end

frame:SetScript("OnEvent", function(_, event, ...)
  handlers[event](...)
end)
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterUnitEvent("UNIT_HEALTH", "player")
