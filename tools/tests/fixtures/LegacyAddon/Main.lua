-- This file breaks the rules on purpose. The tool tests use it.
local frame = CreateFrame("Frame")
frame:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")
frame:RegisterEvent("NOT_A_REAL_EVENT")
local name = GetSpellInfo(133)
local info = C_Spell.NotAFunction(133)
local x = CombatLogGetCurrentEventInfo()
if UnitHealth("player") > 10 then print(name, info, x, string.format("%d", 1)) end
local hp = UnitHealth("target")
local half = hp / 2
goto done
::done::
print(half, TotallyMissingFunction())
print(GetSpellTexture(1)) -- waw-ignore: migration-api
local tint = SomeRemovedColorTable["none"]
local function OnAura(_, updateInfo) if updateInfo.isFullUpdate == true then print("full") end end
