-- A fake of the aura button of the client, for offline tests. Get it with wow.aura_button().
--
-- The client fills a button of a custom aura container. The addon only gives it widgets (SetIcon, AddDispelTypeTexture,
-- and the like). The simulator has no container, so a test cannot check what the client draws.
-- This fake keeps the widgets and, in ApplyAura(auraData), runs the logic of the dispel type textures.
-- It follows Blizzard_AuraContainer/Blizzard_CustomAuraButton.lua of the pinned build (ShouldShowDispelTypeForAura,
-- ApplyDispelTypeTextureStyle and ApplyCustomDispelTypeTextureColor), and the table DEBUFF_DISPLAY_INFO in
-- Blizzard_FrameXMLUtil/AuraUtil.lua.
--
-- What it does not do: icon, time and count. It also does not draw the styles Icon and CustomAsset with assets.
-- A style that the fake does not run raises an error, so a test cannot pass by accident.
--
-- The colors DEBUFF_TYPE_NONE_COLOR, DEBUFF_TYPE_MAGIC_COLOR and so on are globals of the client engine, not FrameXML.
-- A test that checks a color sets them first, for example:
--   wow.env.DEBUFF_TYPE_NONE_COLOR = wow.env.CreateColor(0.8, 0, 0)

local M = {}

-- The atlases of AuraUtil.lua. A dispel type without an entry uses "None".
local DISPLAY_INFO = {
  Magic = { color = "DEBUFF_TYPE_MAGIC_COLOR", basic = "ui-debuff-border-magic-noicon", dispel = "ui-debuff-border-magic-icon" },
  Curse = { color = "DEBUFF_TYPE_CURSE_COLOR", basic = "ui-debuff-border-curse-noicon", dispel = "ui-debuff-border-curse-icon" },
  Disease = { color = "DEBUFF_TYPE_DISEASE_COLOR", basic = "ui-debuff-border-disease-noicon", dispel = "ui-debuff-border-disease-icon" },
  Poison = { color = "DEBUFF_TYPE_POISON_COLOR", basic = "ui-debuff-border-poison-noicon", dispel = "ui-debuff-border-poison-icon" },
  Bleed = { color = "DEBUFF_TYPE_BLEED_COLOR", basic = "ui-debuff-border-bleed-noicon", dispel = "ui-debuff-border-bleed-icon" },
  None = { color = "DEBUFF_TYPE_NONE_COLOR", basic = "ui-debuff-border-default-noicon" },
}

-- The defaults of CustomAuraButtonDispelTypeTextureOptions in the API documentation.
local OPTION_DEFAULTS = { showAlways = false, showWhenHarmful = true, showWhenHelpful = false, showWithoutDispelType = false }

function M.new(sim, env, api, new_frame, parent)
  local style = rawget(env, "Enum") and env.Enum.CustomAuraButtonDispelTypeTextureStyle
  if not style then
    error("waw: wow.aura_button needs Enum.CustomAuraButtonDispelTypeTextureStyle, which this build does not have", 2)
  end

  local button = new_frame("Button", nil, parent)
  button.__dispel_textures = {}

  local function display_info(dispel_name)
    -- A secret dispel type is not a key of a plain table. The client picks the entry itself, so the fake cannot.
    if type(dispel_name) ~= "string" then dispel_name = "None" end
    return DISPLAY_INFO[dispel_name] or DISPLAY_INFO.None
  end

  local function border_color(info)
    local color = rawget(env, info.color)
    if not color then
      error("waw: " .. info.color .. " is a global of the client engine. Set it in the test, for example "
        .. "wow.env." .. info.color .. " = wow.env.CreateColor(r, g, b).", 3)
    end
    return color
  end

  function button:SetIcon(texture) self.icon = texture end
  function button:SetDurationCooldown(cooldown) self.durationCooldown = cooldown end
  function button:SetDurationText(fontString) self.durationText = fontString end
  function button:SetApplicationCount(fontString) self.applicationCount = fontString end

  function button:AddDispelTypeTexture(texture, options)
    local processed = {}
    for key, value in pairs(OPTION_DEFAULTS) do processed[key] = value end
    for key, value in pairs(options or {}) do processed[key] = value end
    if processed.style == nil then processed.style = style.BorderWithIcon end
    self.__dispel_textures[#self.__dispel_textures + 1] = { texture = texture, options = processed }
  end

  -- ShouldShowDispelTypeForAura of Blizzard_CustomAuraButton.lua.
  local function should_show(options, aura)
    if not aura then return false end
    if options.showAlways then return true end
    if aura.isHarmful and not options.showWhenHarmful then return false end
    if aura.isHelpful and not options.showWhenHelpful then return false end
    if aura.dispelName == nil and not options.showWithoutDispelType then return false end
    if options.stealableFilter ~= nil then
      local filter = env.Enum.CustomAuraButtonDispelTypeStealableFilter
      if not filter then
        error("waw: wow.aura_button needs Enum.CustomAuraButtonDispelTypeStealableFilter for stealableFilter", 3)
      end
      local required = (options.stealableFilter == filter.Stealable)
      if (aura.isStealable == true) ~= required then return false end
    end
    return true
  end

  local function apply_style(texture, options, aura)
    local info = display_info(aura.dispelName)
    if options.style == style.Border then
      texture:SetAtlas(info.basic)
      texture:SetVertexColor(1, 1, 1, 1)
    elseif options.style == style.BorderWithIcon then
      texture:SetAtlas(info.dispel or info.basic)
      texture:SetVertexColor(1, 1, 1, 1)
    elseif options.style == style.PreserveAsset then
      local color = border_color(info)
      texture:SetVertexColor(color:GetRGBA())
    else
      error("waw: the fake aura button does not run this dispel texture style", 3)
    end
  end

  -- Give the aura data of one aura (a table like C_UnitAuras.GetAuraDataByAuraInstanceID returns it).
  -- The fields that the dispel textures read are isHarmful, isHelpful, isStealable and dispelName (nil for a physical effect).
  function button:ApplyAura(aura)
    for _, item in ipairs(self.__dispel_textures) do
      if should_show(item.options, aura) then
        apply_style(item.texture, item.options, aura)
        if item.options.customDispelColorMap then
          local color = item.options.customDispelColorMap[aura.dispelName or "None"]
          -- Blizzard calls GetRGBA on the entry, so it must be a color object.
          if color then item.texture:SetVertexColor(color:GetRGBA()) end
        end
        item.texture:Show()
      else
        item.texture:Hide()
      end
    end
  end

  return button
end

return M
