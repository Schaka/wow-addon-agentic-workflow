-- Checks of the textures and of wow.aura_button in the simulator. Usage: lua aura_button_sim.lua
-- The test prints "ok" if every check passes.
local wowsim = require("wowsim")

local api = {
  version = "1.0.0", build = 1, interface = 16001, enums = {}, restricted_events = {}, events = {},
  templates = {}, widget_methods = {}, functions = {}, ui_globals = {}, cvars = {}, addons = {},
}

local function check(condition, message) if not condition then error("FAILED: " .. message, 0) end end
local function raises(fn, pattern)
  local ok, err = pcall(fn)
  check(not ok, "expected an error for " .. pattern)
  check(tostring(err):find(pattern), "error text " .. tostring(err) .. " does not match " .. pattern)
end

local sim = wowsim.new(api)
local env = sim.env

-- A texture keeps its color, atlas, file and texture coordinates.
local texture = env.UIParent:CreateTexture()
check(select("#", texture:GetVertexColor()) == 4, "default vertex color")
texture:SetVertexColor(0.1, 0.2, 0.3)
local r, g, b, a = texture:GetVertexColor()
check(r == 0.1 and g == 0.2 and b == 0.3 and a == 1, "vertex color")
texture:SetAtlas("an-atlas")
check(texture:GetAtlas() == "an-atlas", "atlas")
texture:SetTexture("Interface\\Buttons\\Demo")
check(texture:GetTexture() == "Interface\\Buttons\\Demo" and texture:GetAtlas() == nil, "a file replaces the atlas")
texture:SetTexCoord(0, 0.5, 0, 0.25)
local left, right, top, bottom = texture:GetTexCoord()
check(left == 0 and right == 0.5 and top == 0 and bottom == 0.25, "texture coordinates")

-- The aura button needs the enum of the build.
raises(function() sim:aura_button() end, "needs Enum.CustomAuraButtonDispelTypeTextureStyle")

env.Enum = { CustomAuraButtonDispelTypeTextureStyle = { Border = 0, BorderWithIcon = 1, Icon = 2, PreserveAsset = 3, CustomAsset = 4 } }
local button = sim:aura_button()

-- The default of the texture shows a harmful aura with a dispel type, with the style BorderWithIcon.
local border = env.UIParent:CreateTexture()
button:AddDispelTypeTexture(border, {})
button:ApplyAura({ isHarmful = true, dispelName = "Magic" })
check(border:IsShown() and border:GetAtlas() == "ui-debuff-border-magic-icon", "default style on a magic debuff")
button:ApplyAura({ isHarmful = true, dispelName = nil })
check(not border:IsShown(), "a physical debuff is hidden by default")
button:ApplyAura({ isHelpful = true, dispelName = "Magic" })
check(not border:IsShown(), "a buff is hidden by default")

-- The style PreserveAsset keeps the asset and sets the color of the dispel type. showWithoutDispelType shows a physical debuff.
local overlay = env.UIParent:CreateTexture()
local second = sim:aura_button()
second:AddDispelTypeTexture(overlay, { style = 3, showWithoutDispelType = true })
raises(function() second:ApplyAura({ isHarmful = true, dispelName = nil }) end, "DEBUFF_TYPE_NONE_COLOR")
env.DEBUFF_TYPE_NONE_COLOR = env.CreateColor(0.8, 0, 0)
env.DEBUFF_TYPE_MAGIC_COLOR = env.CreateColor(0.2, 0.6, 1)
overlay:SetTexture("Interface\\Buttons\\UI-Debuff-Overlays")
second:ApplyAura({ isHarmful = true, dispelName = nil })
r, g, b = overlay:GetVertexColor()
check(overlay:IsShown() and r == 0.8 and g == 0 and b == 0, "a physical debuff gets the color of None")
check(overlay:GetTexture() == "Interface\\Buttons\\UI-Debuff-Overlays", "PreserveAsset keeps the texture")
second:ApplyAura({ isHarmful = true, dispelName = "Magic" })
r, g, b = overlay:GetVertexColor()
check(r == 0.2 and g == 0.6 and b == 1, "a magic debuff gets the color of Magic")

-- The stealable filter shows a texture only for a stealable aura (or only for the others).
env.Enum.CustomAuraButtonDispelTypeStealableFilter = { Stealable = 0, NotStealable = 1 }
local glow = env.UIParent:CreateTexture()
local fourth = sim:aura_button()
fourth:AddDispelTypeTexture(glow, { style = 3, showWhenHelpful = true, showWhenHarmful = false, showWithoutDispelType = true, stealableFilter = 0 })
env.DEBUFF_TYPE_MAGIC_COLOR = env.CreateColor(0.2, 0.6, 1)
fourth:ApplyAura({ isHelpful = true, dispelName = "Magic", isStealable = true })
check(glow:IsShown(), "a stealable buff shows the texture")
fourth:ApplyAura({ isHelpful = true, dispelName = "Magic", isStealable = false })
check(not glow:IsShown(), "a buff that is not stealable hides the texture")
fourth:ApplyAura({ isHarmful = true, dispelName = "Magic", isStealable = true })
check(not glow:IsShown(), "a debuff hides the texture with showWhenHarmful off")

-- A custom color map replaces the color of the dispel type.
local plain = env.UIParent:CreateTexture()
local fifth = sim:aura_button()
fifth:AddDispelTypeTexture(plain, { style = 3, showWhenHelpful = true, stealableFilter = 0, customDispelColorMap = { Magic = env.CreateColor(1, 1, 1) } })
fifth:ApplyAura({ isHelpful = true, dispelName = "Magic", isStealable = true })
r, g, b = plain:GetVertexColor()
check(r == 1 and g == 1 and b == 1, "the color map wins over the color of the type")

-- A style that the fake does not run raises an error.
local third = sim:aura_button()
third:AddDispelTypeTexture(env.UIParent:CreateTexture(), { style = 2 })
raises(function() third:ApplyAura({ isHarmful = true, dispelName = "Magic" }) end, "does not run this dispel texture style")

-- A button keeps its enabled state, and a check button keeps its checked state.
local button = env.CreateFrame("CheckButton", nil, env.UIParent)
check(button:IsEnabled() == true and button:GetChecked() == false, "a new button is enabled and not checked")
button:Disable()
check(button:IsEnabled() == false, "Disable")
button:Enable()
check(button:IsEnabled() == true, "Enable")
button:SetEnabled(false)
check(button:IsEnabled() == false, "SetEnabled")
button:SetChecked(1)
check(button:GetChecked() == true, "SetChecked")
button:SetChecked(false)
check(button:GetChecked() == false, "SetChecked false")

-- A region keeps its anchor points and its horizontal justification.
local region = env.UIParent:CreateFontString()
check(region:GetNumPoints() == 0 and region:GetPoint() == nil, "a new region has no point")
local other = env.CreateFrame("Frame", nil, env.UIParent)
region:SetPoint("BOTTOM", other, "TOP", 3, 4)
local point, relativeTo, relativePoint, x, y = region:GetPoint()
check(point == "BOTTOM" and relativeTo == other and relativePoint == "TOP" and x == 3 and y == 4, "SetPoint with all arguments")
region:ClearAllPoints()
check(region:GetNumPoints() == 0, "ClearAllPoints")
region:SetPoint("LEFT", other)
point, relativeTo, relativePoint, x, y = region:GetPoint()
check(point == "LEFT" and relativeTo == other and relativePoint == "LEFT" and x == 0 and y == 0, "the relative point defaults to the point")
region:SetPoint("TOP", 5, 6)
point, relativeTo, relativePoint, x, y = region:GetPoint(2)
check(point == "TOP" and relativeTo == env.UIParent and relativePoint == "TOP" and x == 5 and y == 6, "SetPoint with offsets only")
check(region:GetJustifyH() == "CENTER", "default justification")
region:SetJustifyH("LEFT")
check(region:GetJustifyH() == "LEFT", "SetJustifyH")
print("ok")
