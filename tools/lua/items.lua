-- Item data for offline tests. Get the store with wow.items().
--
-- The client reads item data from its cache and from the server. The simulator has no item data, so a test defines the
-- items that it needs. wow.items() installs fakes for the item, equipment, bag and tooltip data functions of the build.
-- The fakes read the store. A function that the pinned build does not have stays nil, like in the client.
--
--   local items = wow.items()
--   items:define(2140, { name = "Carving Knife", quality = 1, level = 11, minLevel = 6, equipLoc = "INVTYPE_WEAPON",
--     classID = 2, subclassID = 15, sellPrice = 81, stats = { ITEM_MOD_DAMAGE_PER_SECOND_SHORT = 4.6 },
--     lines = { "Carving Knife", { "One-Hand", "Dagger" }, { "2 - 6 Damage", "Speed 1.60" } } })
--   items:equip(16, 2140)          -- GetInventoryItemLink("player", 16)
--   items:put(0, 1, 2140)          -- bag 0, slot 1
--
-- An item with cached = false behaves like an item that the client did not load yet: C_Item.GetItemInfo and
-- C_Item.GetItemStats return nothing, and C_TooltipInfo returns the line "Retrieving item information".
-- C_Item.RequestLoadItemDataByID loads it after 0.2 seconds and fires ITEM_DATA_LOAD_RESULT and GET_ITEM_INFO_RECEIVED.
--
-- What the store does not do: enchants, gems, random suffixes and bonus IDs. The link carries only the item ID and the
-- level. A test that needs another link passes link = "..." to define.

local M = {}

-- English names of the item classes, as the client returns them in itemType and itemSubType.
local CLASS_NAMES = { [2] = "Weapon", [4] = "Armor", [0] = "Consumable", [12] = "Quest", [15] = "Miscellaneous" }
local SUBCLASS_NAMES = {
  [2] = { [0] = "One-Handed Axes", [1] = "Two-Handed Axes", [2] = "Bows", [3] = "Guns", [4] = "One-Handed Maces",
    [5] = "Two-Handed Maces", [6] = "Polearms", [7] = "One-Handed Swords", [8] = "Two-Handed Swords", [10] = "Staves",
    [13] = "Fist Weapons", [14] = "Miscellaneous", [15] = "Daggers", [16] = "Thrown", [18] = "Crossbows", [19] = "Wands" },
  [4] = { [0] = "Miscellaneous", [1] = "Cloth", [2] = "Leather", [3] = "Mail", [4] = "Plate", [6] = "Shields",
    [7] = "Librams", [8] = "Idols", [9] = "Totems" },
}

-- Color codes of the item qualities, as in the links of the client.
local QUALITY_COLORS = { [0] = "ff9d9d9d", [1] = "ffffffff", [2] = "ff1eff00", [3] = "ff0070dd", [4] = "ffa335ee",
  [5] = "ffff8000" }

-- Equip locations that the client does not equip. C_Item.IsEquippableItem returns false for them.
local NOT_EQUIPPABLE = { [""] = true, INVTYPE_NON_EQUIP = true, INVTYPE_NON_EQUIP_IGNORE = true }

local RETRIEVING = "Retrieving item information"

function M.new(sim, env, api)
  local store = { items = {}, by_name = {}, equipped = {}, bags = {}, bag_sizes = {} }

  local function install(path, fn)
    if not api.functions[path] then return end
    local head, key = path:match("^([%w_]+)%.([%w_]+)$")
    if head then
      rawset(env[head], key, fn)
    else
      rawset(env, path, fn)
    end
  end

  local function make_link(id, item)
    if item.link then return item.link end
    local color = QUALITY_COLORS[item.quality or 1] or QUALITY_COLORS[1]
    return string.format("|c%s|Hitem:%d::::::::%d:::::::::|h[%s]|h|r", color, id, item.level or 1, item.name)
  end

  -- The fakes accept an item ID, an item link, an item string or an item name, like the client.
  local function resolve(info)
    if type(info) == "number" then return store.items[info], info end
    if type(info) ~= "string" then return nil end
    local id = tonumber(info:match("item:(%-?%d+)"))
    if id then return store.items[id], id end
    id = store.by_name[info]
    if id then return store.items[id], id end
    return nil
  end

  local function is_cached(item) return item and item.cached ~= false end

  function store:define(id, fields)
    if type(id) ~= "number" or type(fields) ~= "table" or type(fields.name) ~= "string" then
      error("waw: items:define(id, { name = ..., ... }) needs a number and a table with a name", 2)
    end
    local item = {}
    for k, v in pairs(fields) do item[k] = v end
    item.id = id
    item.equipLoc = item.equipLoc or ""
    item.classID = item.classID or 15
    item.subclassID = item.subclassID or 0
    item.stats = item.stats or {}
    item.lines = item.lines or { item.name }
    store.items[id] = item
    store.by_name[item.name] = id
    return make_link(id, item)
  end

  function store:link(id)
    local item = store.items[id]
    if not item then error("waw: item " .. tostring(id) .. " is not defined", 2) end
    return make_link(id, item)
  end

  -- Mark an item as loaded or not loaded, for example to test a second read after ITEM_DATA_LOAD_RESULT.
  function store:set_cached(id, cached)
    local item = store.items[id]
    if not item then error("waw: item " .. tostring(id) .. " is not defined", 2) end
    item.cached = cached ~= false
  end

  function store:equip(slot, id)
    if id ~= nil and not store.items[id] then error("waw: item " .. tostring(id) .. " is not defined", 2) end
    store.equipped[slot] = id
  end

  function store:bag(bag, size) store.bag_sizes[bag] = size end

  function store:put(bag, slot, id)
    if id ~= nil and not store.items[id] then error("waw: item " .. tostring(id) .. " is not defined", 2) end
    store.bags[bag] = store.bags[bag] or {}
    store.bags[bag][slot] = id
    if (store.bag_sizes[bag] or 0) < slot then store.bag_sizes[bag] = slot end
  end

  local function tooltip_data(item, id)
    local lines = {}
    if not is_cached(item) then
      lines[1] = { leftText = RETRIEVING, type = 0 }
    else
      for i, line in ipairs(item.lines) do
        if type(line) == "table" then
          lines[i] = { leftText = line[1], rightText = line[2], type = 0 }
        else
          lines[i] = { leftText = line, type = 0 }
        end
      end
    end
    return { type = 0, id = id, hyperlink = make_link(id, item), lines = lines }
  end

  -- C_Item ------------------------------------------------------------------
  install("C_Item.GetItemInfo", function(info)
    local item, id = resolve(info)
    if not is_cached(item) then return nil end
    local classNames = SUBCLASS_NAMES[item.classID] or {}
    return item.name, make_link(id, item), item.quality or 1, item.level or 1, item.minLevel or 0,
      CLASS_NAMES[item.classID] or "Miscellaneous", classNames[item.subclassID] or "Miscellaneous", item.stackCount or 1,
      item.equipLoc, item.icon or 134400, item.sellPrice or 0, item.classID, item.subclassID, item.bindType or 0,
      item.expansionID or 0, item.setID, false, item.description or ""
  end)

  -- The client knows the instant data of every item, also before the item data loads.
  install("C_Item.GetItemInfoInstant", function(info)
    local item, id = resolve(info)
    if not item then return nil end
    local classNames = SUBCLASS_NAMES[item.classID] or {}
    return id, CLASS_NAMES[item.classID] or "Miscellaneous", classNames[item.subclassID] or "Miscellaneous",
      item.equipLoc, item.icon or 134400, item.classID, item.subclassID
  end)

  install("C_Item.GetItemStats", function(link)
    local item = resolve(link)
    if not is_cached(item) then return nil end
    local copy = {}
    for k, v in pairs(item.stats) do copy[k] = v end
    return copy
  end)

  install("C_Item.GetItemIDForItemInfo", function(info)
    local item, id = resolve(info)
    return item and id or nil
  end)
  install("C_Item.DoesItemExistByID", function(id) return store.items[id] ~= nil end)
  install("C_Item.IsItemDataCachedByID", function(id) return is_cached(store.items[id]) end)
  install("C_Item.IsEquippableItem", function(info)
    local item = resolve(info)
    return item ~= nil and not NOT_EQUIPPABLE[item.equipLoc]
  end)

  install("C_Item.RequestLoadItemDataByID", function(info)
    local item, id = resolve(info)
    if not item or is_cached(item) or item.__loading then return end
    item.__loading = true
    env.C_Timer.After(0.2, function()
      item.__loading = nil
      item.cached = true
      if api.events.ITEM_DATA_LOAD_RESULT then sim:fire("ITEM_DATA_LOAD_RESULT", id, true) end
      if api.events.GET_ITEM_INFO_RECEIVED then sim:fire("GET_ITEM_INFO_RECEIVED", id, true) end
    end)
  end)

  -- Equipment and bags -------------------------------------------------------
  local function equipped(unit, slot)
    if unit ~= "player" then return nil end
    local id = store.equipped[slot]
    return id and store.items[id], id
  end

  install("GetInventoryItemLink", function(unit, slot)
    local item, id = equipped(unit, slot)
    return item and make_link(id, item) or nil
  end)
  install("GetInventoryItemID", function(unit, slot)
    local item, id = equipped(unit, slot)
    return item and id or nil
  end)

  local function in_bag(bag, slot)
    local id = store.bags[bag] and store.bags[bag][slot]
    return id and store.items[id], id
  end

  install("C_Container.GetContainerNumSlots", function(bag) return store.bag_sizes[bag] or 0 end)
  install("C_Container.GetContainerItemLink", function(bag, slot)
    local item, id = in_bag(bag, slot)
    return item and make_link(id, item) or nil
  end)
  install("C_Container.GetContainerItemID", function(bag, slot)
    local item, id = in_bag(bag, slot)
    return item and id or nil
  end)
  install("C_Container.GetContainerItemInfo", function(bag, slot)
    local item, id = in_bag(bag, slot)
    if not item then return nil end
    return { iconFileID = item.icon or 134400, stackCount = 1, isLocked = false, quality = item.quality or 1,
      isReadable = false, hasLoot = false, hyperlink = make_link(id, item), isFiltered = false, hasNoValue = false,
      itemID = id, isBound = item.bound == true, itemName = item.name }
  end)

  -- Tooltip data ---------------------------------------------------------------
  install("C_TooltipInfo.GetHyperlink", function(link)
    local item, id = resolve(link)
    if not item then return nil end
    return tooltip_data(item, id)
  end)
  install("C_TooltipInfo.GetBagItem", function(bag, slot)
    local item, id = in_bag(bag, slot)
    if not item then return nil end
    return tooltip_data(item, id)
  end)
  install("C_TooltipInfo.GetInventoryItem", function(unit, slot)
    local item, id = equipped(unit, slot)
    if not item then return nil end
    return tooltip_data(item, id)
  end)

  store.tooltip_data = function(_, info)
    local item, id = resolve(info)
    if not item then return nil end
    return tooltip_data(item, id)
  end
  return store
end

return M
