-- Checks of wow.items, wow.tooltip and wow.addon_channel in the simulator. Usage: lua items_sim.lua
-- The test prints "ok" if every check passes.
local wowsim = require("wowsim")

local function set(names)
  local out = {}
  for _, name in ipairs(names) do out[name] = true end
  return out
end

local api = {
  version = "1.0.0", build = 1, interface = 16001, restricted_events = {}, templates = {}, widget_methods = {},
  ui_globals = set({ "TooltipDataProcessor", "TooltipUtil" }), cvars = {}, addons = {},
  enums = { SendAddonMessageResult = { Success = 0, InvalidPrefix = 1, InvalidMessage = 2, TargetRequired = 6,
    AddOnMessageLockdown = 11 } },
  events = set({ "ITEM_DATA_LOAD_RESULT", "GET_ITEM_INFO_RECEIVED", "CHAT_MSG_ADDON" }),
  functions = set({ "C_Item.GetItemInfo", "C_Item.GetItemInfoInstant", "C_Item.GetItemStats",
    "C_Item.RequestLoadItemDataByID", "C_Item.IsEquippableItem", "GetInventoryItemLink", "GetInventoryItemID",
    "C_Container.GetContainerNumSlots", "C_Container.GetContainerItemLink", "C_Container.GetContainerItemInfo",
    "C_TooltipInfo.GetHyperlink", "C_TooltipInfo.GetBagItem", "C_TooltipInfo.GetInventoryItem", "C_Timer.After",
    "C_ChatInfo.RegisterAddonMessagePrefix", "C_ChatInfo.SendAddonMessage", "C_ChatInfo.InChatMessagingLockdown",
    "C_ChatInfo.IsAddonMessagePrefixRegistered" }),
}

local function check(condition, message) if not condition then error("FAILED: " .. message, 0) end end
local function raises(fn, pattern)
  local ok, err = pcall(fn)
  check(not ok, "expected an error for " .. pattern)
  check(tostring(err):find(pattern), "error text " .. tostring(err) .. " does not match " .. pattern)
end

local sim = wowsim.new(api)
local env = sim.env

-- Items: info, stats, equipment and bags.
local items = sim:items()
local link = items:define(2140, { name = "Carving Knife", quality = 1, level = 11, minLevel = 6,
  equipLoc = "INVTYPE_WEAPON", classID = 2, subclassID = 15, sellPrice = 81,
  stats = { ITEM_MOD_DAMAGE_PER_SECOND_SHORT = 4.6 },
  lines = { "Carving Knife", { "One-Hand", "Dagger" }, "Equip: +1 Agility" } })
check(link:find("|Hitem:2140:", 1, true) and link:find("[Carving Knife]", 1, true), "link format")
local name, fullLink, quality, level, minLevel, _, subType, _, equipLoc, _, sellPrice, classID, subclassID =
  env.C_Item.GetItemInfo(2140)
check(name == "Carving Knife" and fullLink == link and quality == 1 and level == 11 and minLevel == 6, "item info")
check(subType == "Daggers" and equipLoc == "INVTYPE_WEAPON" and sellPrice == 81, "item info details")
check(classID == 2 and subclassID == 15, "class and subclass")
check(env.C_Item.GetItemInfo(link) == "Carving Knife" and env.C_Item.GetItemInfo("item:2140") == "Carving Knife",
  "lookup by link and item string")
local stats = env.C_Item.GetItemStats(link)
stats.ITEM_MOD_DAMAGE_PER_SECOND_SHORT = 99
check(env.C_Item.GetItemStats(link).ITEM_MOD_DAMAGE_PER_SECOND_SHORT == 4.6, "stats are a copy")
check(env.C_Item.IsEquippableItem(2140) == true, "equippable")

items:equip(16, 2140)
check(env.GetInventoryItemLink("player", 16) == link and env.GetInventoryItemID("player", 16) == 2140, "equipped")
check(env.GetInventoryItemLink("party1", 16) == nil and env.GetInventoryItemLink("player", 17) == nil, "empty slots")
items:put(0, 3, 2140)
check(env.C_Container.GetContainerNumSlots(0) == 3, "bag size grows")
check(env.C_Container.GetContainerItemLink(0, 3) == link and env.C_Container.GetContainerItemLink(0, 1) == nil, "bag")
check(env.C_Container.GetContainerItemInfo(0, 3).itemID == 2140, "container item info")

-- An item that is not cached loads after a request.
items:define(5000, { name = "Late Item", equipLoc = "INVTYPE_HEAD", classID = 4, subclassID = 1, cached = false })
check(env.C_Item.GetItemInfo(5000) == nil and env.C_Item.GetItemStats("item:5000") == nil, "not cached")
check(env.C_Item.GetItemInfoInstant(5000) == 5000, "instant info without cache")
check(env.C_TooltipInfo.GetHyperlink("item:5000").lines[1].leftText == "Retrieving item information", "loading line")
local loaded
local frame = env.CreateFrame("Frame")
frame:RegisterEvent("ITEM_DATA_LOAD_RESULT")
frame:SetScript("OnEvent", function(_, _, id, success) loaded = id .. tostring(success) end)
env.C_Item.RequestLoadItemDataByID(5000)
sim:advance(0.1)
check(loaded == nil, "not loaded before 0.2 seconds")
sim:advance(0.2)
check(loaded == "5000true" and env.C_Item.GetItemInfo(5000) == "Late Item", "loaded after the request")

-- Tooltip: the post call runs after the lines, and RefreshData runs it again.
local tooltip = sim:tooltip("GameTooltip")
local calls = 0
env.TooltipDataProcessor.AddTooltipPostCall(env.TooltipDataProcessor.AllTypes, function(tip, data)
  calls = calls + 1
  check(data.id == 2140, "post call data")
  local _, shownLink = env.TooltipUtil.GetDisplayedItem(tip)
  check(shownLink == link, "displayed item")
  tip:AddLine("extra " .. calls, 0, 1, 0)
end)
tooltip:SetBagItem(0, 3)
local lines = tooltip:Lines()
check(#lines == 4 and lines[2].left == "One-Hand" and lines[2].right == "Dagger", "data lines")
check(lines[4].left == "extra 1" and lines[4].g == 1 and tooltip:IsShown(), "post call line")
tooltip:RefreshData()
check(tooltip:NumLines() == 4 and tooltip:Lines()[4].left == "extra 2", "refresh rebuilds the lines")
check(tooltip:SetBagItem(0, 1) == false and not tooltip:IsShown(), "an empty slot hides the tooltip")

-- Addon messages.
local channel = sim:addon_channel()
check(env.C_ChatInfo.RegisterAddonMessagePrefix("Demo") == 0, "register")
check(env.C_ChatInfo.RegisterAddonMessagePrefix("Demo") == 1, "duplicate prefix")
local received = {}
local listener = env.CreateFrame("Frame")
listener:RegisterEvent("CHAT_MSG_ADDON")
listener:SetScript("OnEvent", function(_, _, prefix, text, chatType, sender)
  received[#received + 1] = prefix .. "|" .. text .. "|" .. chatType .. "|" .. sender
end)
check(channel:receive("Other", "x", "PARTY", "A-B") == false and #received == 0, "unregistered prefix is dropped")
channel:receive("Demo", "hello", "PARTY", "Lyra-Realm")
check(received[1] == "Demo|hello|PARTY|Lyra-Realm", "delivered")
channel.own_name = "Me-Realm"
check(env.C_ChatInfo.SendAddonMessage("Demo", "q", "PARTY") == 0, "send")
check(#channel.sent == 1 and received[2] == "Demo|q|PARTY|Me-Realm", "echo of a group message")
check(env.C_ChatInfo.SendAddonMessage("Demo", string.rep("x", 256), "PARTY") == 2, "message too long")
check(env.C_ChatInfo.SendAddonMessage("Demo", "w", "WHISPER") == 6, "whisper needs a target")
raises(function() env.C_ChatInfo.SendAddonMessage("Demo", sim:secret("s"), "PARTY") end, "secret")
channel.lockdown = true
check(env.C_ChatInfo.InChatMessagingLockdown() == true, "lockdown")
check(env.C_ChatInfo.SendAddonMessage("Demo", "late", "PARTY") == 11 and #channel:messages("Demo") == 1, "blocked")

print("ok")
