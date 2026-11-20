-- A fake of the item tooltip pipeline, for offline tests. Get a tooltip with wow.tooltip(name).
--
-- In the client, a call such as GameTooltip:SetBagItem(bag, slot) reads the tooltip data from C_TooltipInfo, adds the
-- lines and then runs the post calls that addons added with TooltipDataProcessor.AddTooltipPostCall. This fake follows
-- TooltipDataHandlerMixin:InternalProcessInfo in Blizzard_SharedXMLGame/Tooltip/TooltipDataHandler.lua of the pinned
-- build: clear the lines, add the data lines, run the post calls for the data type and for AllTypes, then Show.
-- RefreshData runs the same steps again, like GameTooltipDataMixin:RefreshData.
--
-- The first call of wow.tooltip installs fakes for TooltipDataProcessor and TooltipUtil.GetDisplayedItem.
-- The Set functions read the C_TooltipInfo fakes, so a test calls wow.items() first.
--
-- A test reads the result with tooltip:Lines(), which returns { { left =, right =, r =, g =, b = }, ... }.
--
-- What it does not do: comparison tooltips, money lines, textures in lines, the size of the tooltip, and the
-- pre calls and line calls of TooltipDataProcessor.

local M = {}

local function install_processor(sim, env)
  if sim.__tooltip_processor then return sim.__tooltip_processor end
  local processor = { AllTypes = "ALL", __post = {} }
  function processor.AddTooltipPostCall(tooltipType, fn)
    if type(fn) ~= "function" then error("TooltipDataProcessor.AddTooltipPostCall: the callback is not a function", 2) end
    processor.__post[#processor.__post + 1] = { kind = tooltipType, fn = fn }
  end
  function processor.AddTooltipPreCall() end
  function processor.AddLinePreCall() end
  function processor.AddLinePostCall() end
  rawset(env, "TooltipDataProcessor", processor)

  -- TooltipUtil.GetDisplayedItem, as in Blizzard_SharedXMLGame/Tooltip/TooltipUtil.lua.
  local util = rawget(env, "TooltipUtil") or {}
  function util.GetDisplayedItem(tooltip)
    if tooltip:IsTooltipType(0) then
      local data = tooltip:GetPrimaryTooltipData()
      local hyperlink = data.hyperlink
      if data.guid and env.C_Item.GetItemLinkByGUID then hyperlink = env.C_Item.GetItemLinkByGUID(data.guid) end
      if hyperlink then
        local name = env.C_Item.GetItemInfo(hyperlink)
        return name, hyperlink, data.id
      end
    end
  end
  rawset(env, "TooltipUtil", util)
  sim.__tooltip_processor = processor
  return processor
end

function M.new(sim, env, api, new_frame, name, parent)
  local processor = install_processor(sim, env)
  local tooltip = new_frame("GameTooltip", name, parent or env.UIParent)
  tooltip.__lines = {}
  tooltip.__shown = false

  local function add(left, right, r, g, b)
    tooltip.__lines[#tooltip.__lines + 1] = { left = left, right = right, r = r, g = g, b = b }
  end

  function tooltip:AddLine(text, r, g, b) add(text, nil, r, g, b) end
  function tooltip:AddDoubleLine(left, right, r, g, b) add(left, right, r, g, b) end
  function tooltip:ClearLines() self.__lines = {} end
  function tooltip:NumLines() return #self.__lines end
  function tooltip:Lines() return self.__lines end
  function tooltip:SetOwner(owner) self.__owner = owner end
  function tooltip:GetOwner() return self.__owner end
  function tooltip:IsForbidden() return false end
  function tooltip:IsOwned(owner) return self.__owner == owner end
  function tooltip:GetPrimaryTooltipData()
    local info = self.infoList and self.infoList[1]
    return info and info.tooltipData
  end
  function tooltip:IsTooltipType(kind)
    local data = self:GetPrimaryTooltipData()
    return data ~= nil and data.type == kind
  end
  function tooltip:GetItem()
    local data = self:GetPrimaryTooltipData()
    if not data or data.type ~= 0 or not data.hyperlink then return nil end
    return env.C_Item.GetItemInfo(data.hyperlink), data.hyperlink
  end

  local function process(info)
    local data = info.tooltipData or (info.getter and info.getter())
    if not data then
      tooltip:Hide()
      return false
    end
    info.tooltipData = data
    tooltip.infoList = { info }
    tooltip:ClearLines()
    for _, line in ipairs(data.lines or {}) do add(line.leftText, line.rightText) end
    for _, call in ipairs(processor.__post) do
      if call.kind == processor.AllTypes or call.kind == data.type then call.fn(tooltip, data) end
    end
    tooltip:Show()
    return true
  end

  local function set_from(getter)
    return process({ getter = getter })
  end

  function tooltip:SetHyperlink(link)
    return set_from(function() return env.C_TooltipInfo.GetHyperlink(link) end)
  end
  function tooltip:SetBagItem(bag, slot)
    return set_from(function() return env.C_TooltipInfo.GetBagItem(bag, slot) end)
  end
  function tooltip:SetInventoryItem(unit, slot)
    return set_from(function() return env.C_TooltipInfo.GetInventoryItem(unit, slot) end)
  end
  -- Shows the data of any item. A test uses it for frames that the simulator does not have, such as a loot roll.
  function tooltip:SetItemData(data) return process({ tooltipData = data }) end

  function tooltip:RefreshData()
    local info = self.infoList and self.infoList[1]
    if not info then return end
    if info.getter then info.tooltipData = nil end
    process(info)
  end
  return tooltip
end

return M
