-- A headless WoW Forever simulator for offline tests.
-- It works on PUC Lua 5.1 and LuaJIT. It has no external dependencies.
--
-- Design rules:
--   * An API that the pinned build does not have reads as nil, like the client.
--   * An API that exists but has no fake raises a clear error when called.
--     A test never passes because a stub silently returned nothing.
--   * Secret values raise on arithmetic, comparison, length, index and call.
--   * wow.secret_table(t) makes a secret table. It raises on index, length, pairs and ipairs.
--   * A secret boolean cannot raise in a truth test or in "== true", because plain Lua gives no hook for them.
--     The loader rewrites the plain pattern "name.field == true" so that it raises. See wow.strict_compare.
--     docs/testing.md lists what the simulator still cannot catch.
local M = {}

local rawtype, rawtostring = type, tostring
local secrets = setmetatable({}, { __mode = "k" }) -- proxy -> { value=, kind= }

local function secret_error(op)
  error("attempted to " .. op .. " a secret value (tainted code cannot do this)", 2)
end

local function make_secret(value)
  local proxy = newproxy(true)
  local mt = getmetatable(proxy)
  secrets[proxy] = { value = value, kind = rawtype(value) }
  local function unwrap(x)
    if secrets[x] then return secrets[x].value end
    return x
  end
  local function arith() secret_error("perform arithmetic on") end
  mt.__add, mt.__sub, mt.__mul, mt.__div, mt.__mod, mt.__pow, mt.__unm = arith, arith, arith, arith, arith, arith, arith
  mt.__lt = function() secret_error("compare") end
  mt.__le = function() secret_error("compare") end
  mt.__eq = function() secret_error("compare") end
  mt.__len = function() secret_error("get the length of") end
  mt.__index = function() secret_error("index") end
  mt.__newindex = function() secret_error("index") end
  mt.__call = function() secret_error("call") end
  mt.__concat = function(a, b)
    -- The client allows a secret string or number in a concatenation. A boolean never works in Lua.
    if rawtype(value) == "boolean" then secret_error("concatenate") end
    return make_secret(rawtostring(unwrap(a)) .. rawtostring(unwrap(b)))
  end
  mt.__tostring = function() return "<secret>" end
  return proxy
end

local function is_secret(v) return rawtype(v) == "userdata" and secrets[v] ~= nil end

-- A secret table is a proxy. The client raises an error for every read of its content.
-- The message has the same shape as the client message, for example when a secret table reaches ipairs.
local secret_tables = setmetatable({}, { __mode = "k" }) -- proxy -> the hidden table
local function is_secret_table(v) return rawtype(v) == "userdata" and secret_tables[v] ~= nil end

local function secret_table_error(op)
  error("attempt to " .. op .. " a secret table value (a secret table value, while execution tainted by 'waw')", 3)
end

local function make_secret_table(content)
  if rawtype(content) ~= "table" then error("waw: wow.secret_table needs a table", 2) end
  local proxy = newproxy(true)
  local mt = getmetatable(proxy)
  secret_tables[proxy] = content
  mt.__index = function() secret_table_error("index") end
  mt.__newindex = function() secret_table_error("index") end
  mt.__len = function() secret_table_error("get the length of") end
  mt.__call = function() secret_table_error("call") end
  mt.__eq = function() secret_table_error("compare") end
  mt.__concat = function() secret_table_error("concatenate") end
  mt.__tostring = function() return "<secret table>" end
  return proxy
end

-- Strict compare ------------------------------------------------------------
-- Lua never calls __eq when a userdata is compared with a boolean. So "secret == true" is false and does not raise,
-- but the client raises an error for it. The loader rewrites this plain pattern in the source of the addon:
--   name.field == true   becomes   __waw_cmp(name.field, "==", true)
-- The helper raises if the left value is secret. The rewrite keeps every line break, so error lines stay the same.
-- It skips strings and comments. It rewrites only if the token before the operand binds weaker than "==".
-- It cannot see a truth test (if x then), a "not x", a comparison with a variable, or a call result.
local WEAK_BEFORE = { ["("] = true, [","] = true, ["{"] = true, ["="] = true, ["and"] = true, ["or"] = true,
  ["then"] = true, ["if"] = true, ["elseif"] = true, ["while"] = true, ["until"] = true, ["return"] = true }

-- Split the source into code pieces and pieces that must stay as they are (strings and comments).
local function split_source(source)
  local pieces, pos, len = {}, 1, #source
  local code_start = 1
  local function flush(stop)
    if stop >= code_start then pieces[#pieces + 1] = { code = true, text = source:sub(code_start, stop) } end
  end
  while pos <= len do
    local c = source:sub(pos, pos)
    local stop
    if c == "-" and source:sub(pos, pos + 1) == "--" then
      local level = source:match("^%-%-%[(=*)%[", pos)
      if level then
        local _, e = source:find("]" .. level .. "]", pos, true)
        stop = e or len
      else
        stop = (source:find("\n", pos, true) or len + 1) - 1
      end
    elseif c == "[" and source:match("^%[=*%[", pos) then
      local level = source:match("^%[(=*)%[", pos)
      local _, e = source:find("]" .. level .. "]", pos, true)
      stop = e or len
    elseif c == '"' or c == "'" then
      local i = pos + 1
      while i <= len do
        local d = source:sub(i, i)
        if d == "\\" then i = i + 1 elseif d == c or d == "\n" then break end
        i = i + 1
      end
      stop = math.min(i, len)
    end
    if stop then
      flush(pos - 1)
      pieces[#pieces + 1] = { code = false, text = source:sub(pos, stop) }
      pos, code_start = stop + 1, stop + 1
    else
      pos = pos + 1
    end
  end
  flush(len)
  return pieces
end

-- The word before position i (skipping spaces and tabs) or a one-character operator.
local function token_before(text, i)
  local j = i - 1
  while j >= 1 and text:sub(j, j):match("[ \t]") do j = j - 1 end
  if j < 1 then return "" end
  local word = text:sub(1, j):match("([%a_][%w_]*)$")
  if word then return word end
  -- A two-character operator such as == or <= is never a weak neighbour.
  local two = text:sub(math.max(j - 1, 1), j)
  if two:match("^[=~<>]=$") then return two end
  return text:sub(j, j)
end

local function rewrite_code(text)
  local out, pos = {}, 1
  while true do
    local s, e, chain, op, literal = text:find("([%a_][%w_]*[%w_%.]*)[ \t]*([=~]=)[ \t]*(%a+)", pos)
    if not s then break end
    local ok = (literal == "true" or literal == "false") and not chain:find("%.$") and not chain:find("%.%.")
    -- The operand must not continue a longer name or a call: look at the character before and after.
    local after = text:sub(e + 1, e + 1)
    if ok and (text:sub(s - 1, s - 1):match("[%w_%.:]") or after:match("[%w_]")) then ok = false end
    if ok and not WEAK_BEFORE[token_before(text, s)] and s > 1 and token_before(text, s) ~= "" then ok = false end
    if ok and (chain == "true" or chain == "false" or chain == "nil" or chain:match("^not$")) then ok = false end
    if ok then
      out[#out + 1] = text:sub(pos, s - 1)
      out[#out + 1] = string.format('__waw_cmp(%s, "%s", %s)', chain, op, literal)
    else
      out[#out + 1] = text:sub(pos, e)
    end
    pos = e + 1
  end
  out[#out + 1] = text:sub(pos)
  return table.concat(out)
end

local function rewrite_bool_compares(source)
  local out = {}
  for _, piece in ipairs(split_source(source)) do
    out[#out + 1] = piece.code and rewrite_code(piece.text) or piece.text
  end
  return table.concat(out)
end

local function copy_table(t)
  local out = {}
  for k, v in pairs(t) do out[k] = v end
  return out
end

local function split_path(name)
  local parts = {}
  for part in name:gmatch("[^.]+") do parts[#parts + 1] = part end
  return parts
end

local function pure_bit()
  local ok, lib = pcall(require, "bit")
  if ok then return lib end
  local function fold(a, b, f)
    local result, bitval = 0, 1
    a, b = a % 4294967296, b % 4294967296
    for _ = 1, 32 do
      if f(a % 2, b % 2) then result = result + bitval end
      a, b, bitval = math.floor(a / 2), math.floor(b / 2), bitval * 2
    end
    return result
  end
  return {
    band = function(a, b) return fold(a, b, function(x, y) return x == 1 and y == 1 end) end,
    bor = function(a, b) return fold(a, b, function(x, y) return x == 1 or y == 1 end) end,
    bxor = function(a, b) return fold(a, b, function(x, y) return x ~= y end) end,
    lshift = function(a, n) return (a * 2 ^ n) % 4294967296 end,
    rshift = function(a, n) return math.floor((a % 4294967296) / 2 ^ n) end,
  }
end

local function strsplit(delimiter, text, limit)
  local out, pos, count = {}, 1, 0
  while true do
    count = count + 1
    local s, e = nil, nil
    if not limit or count < limit then
      for i = pos, #text do
        if delimiter:find(text:sub(i, i), 1, true) then s, e = i, i break end
      end
    end
    if not s then out[#out + 1] = text:sub(pos) break end
    out[#out + 1] = text:sub(pos, s - 1)
    pos = e + 1
  end
  return unpack(out)
end

-- Every test builds a new simulator, but the addon files do not change during a run. Compiling each file once
-- per run instead of once per test made the ArenaLive suite several times faster.
local chunk_cache = {}

local function compiled_chunk(full, strict)
  local key = full .. (strict and "#strict" or "")
  local chunk = chunk_cache[key]
  if chunk then return chunk end
  local handle, open_err = io.open(full, "rb")
  if not handle then error("waw: " .. open_err) end
  local source = handle:read("*a"):gsub("^\239\187\191", "")
  handle:close()
  if strict then source = rewrite_bool_compares(source) end
  local syntax
  chunk, syntax = loadstring(source, "@" .. full)
  if not chunk then error(syntax, 0) end
  chunk_cache[key] = chunk
  return chunk
end

function M.new(api)
  local sim = { api = api, frames = {}, timers = {}, now = 1000, chat = {}, errors = {}, stubs = {},
                saved = {}, loaded = {}, in_combat = false, cvars = {} }
  local env = {}
  sim.env = env

  -- Lua 5.1 subset that the client exposes.
  for _, name in ipairs({ "assert", "error", "ipairs", "next", "pairs", "pcall", "rawequal", "rawget", "rawset",
    "select", "setmetatable", "getmetatable", "tonumber", "unpack", "xpcall", "loadstring", "getfenv", "setfenv",
    "collectgarbage", "gcinfo" }) do
    env[name] = _G[name]
  end
  env.math, env.table = copy_table(math), copy_table(table)
  env.string = copy_table(string)
  env._VERSION = "Lua 5.1"
  getmetatable("").__index = env.string -- ("%d"):format(x) must accept secret values too.
  env._G = env
  env.bit = pure_bit()

  env.type = function(v)
    if is_secret(v) then return secrets[v].kind end
    if is_secret_table(v) then return "table" end
    return rawtype(v)
  end
  -- Lua 5.1 has no __pairs and no __ipairs. So the loop functions must know the secret table.
  env.pairs = function(t)
    if is_secret_table(t) then secret_table_error("iterate over") end
    return pairs(t)
  end
  env.ipairs = function(t)
    if is_secret_table(t) then secret_table_error("iterate over") end
    return ipairs(t)
  end
  env.next = function(t, k)
    if is_secret_table(t) then secret_table_error("iterate over") end
    return next(t, k)
  end
  env.tostring = function(v)
    if is_secret(v) then return make_secret(rawtostring(secrets[v].value)) end
    return rawtostring(v)
  end

  local function any_secret(...)
    for i = 1, select("#", ...) do
      if is_secret((select(i, ...))) then return true end
    end
    return false
  end
  local function reveal_all(...)
    local out = { ... }
    for i = 1, select("#", ...) do
      if is_secret(out[i]) then out[i] = secrets[out[i]].value end
    end
    return unpack(out, 1, select("#", ...))
  end
  local function concat_values(sep, ...)
    local out = {}
    for i = 1, select("#", ...) do
      out[i] = rawtostring((select(i, reveal_all(...))))
    end
    return table.concat(out, sep)
  end

  local real_format = string.format
  env.string.format = function(fmt, ...)
    if any_secret(...) then return make_secret(real_format(fmt, reveal_all(...))) end
    return real_format(fmt, ...)
  end
  env.string.join = function(sep, ...)
    if any_secret(...) then return make_secret(concat_values(sep, ...)) end
    return concat_values(sep, ...)
  end
  env.string.concat = function(...)
    if any_secret(...) then return make_secret(concat_values("", ...)) end
    return concat_values("", ...)
  end
  env.string.split, env.string.trim = strsplit, function(s) return (s:gsub("^%s*(.-)%s*$", "%1")) end
  env.format, env.strjoin, env.strconcat = env.string.format, env.string.join, env.string.concat
  env.strsplit, env.strtrim = strsplit, env.string.trim
  env.strlen, env.strlower, env.strupper, env.strsub = string.len, string.lower, string.upper, string.sub
  env.strfind, env.strmatch, env.gsub, env.strrep = string.find, string.match, string.gsub, string.rep
  env.strbyte, env.strchar, env.strrev, env.gmatch = string.byte, string.char, string.reverse, string.gmatch
  env.tinsert, env.tremove, env.sort = table.insert, table.remove, table.sort
  env.floor, env.ceil, env.abs, env.min, env.max = math.floor, math.ceil, math.abs, math.min, math.max
  env.sqrt, env.random, env.mod = math.sqrt, math.random, math.fmod
  env.wipe = function(t) for k in pairs(t) do t[k] = nil end return t end
  env.table.wipe = env.wipe
  env.tContains = function(t, v) for _, x in pairs(t) do if x == v then return true end end return false end
  env.date = os.date
  env.time = function() return math.floor(sim.now) end
  env.GetTime = function() return sim.now end
  env.GetTimePreciseSec = env.GetTime
  env.debugprofilestop = function() return sim.now * 1000 end
  env.debugstack = function() return debug.traceback("", 2) end

  -- Secret value and security helpers.
  env.issecretvalue = is_secret
  env.canaccessvalue = function(v) return not is_secret(v) end
  -- issecrettable is true for a secret table. A table that only holds secret values is not a secret table.
  -- Assumption: issecretvalue is false for a secret table. The probe in the client must show the real answer.
  env.issecrettable = function(v) return is_secret_table(v) end
  env.canaccesstable = function(v) return not is_secret_table(v) end
  env.hasanysecretvalues = any_secret
  -- Used by the strict compare rewrite of the loader. It raises like the client, if the left value is secret.
  env.__waw_cmp = function(left, op, right)
    if is_secret(left) then
      error("attempt to compare (a secret " .. secrets[left].kind .. " value, while execution tainted by 'waw')", 2)
    end
    if op == "==" then return left == right end
    return left ~= right
  end
  env.InCombatLockdown = function() return sim.in_combat end
  env.hooksecurefunc = function(a, b, c)
    local tbl, name, hook = env, a, b
    if rawtype(a) == "table" then tbl, name, hook = a, b, c end
    local orig = tbl[name]
    if orig == nil then error("hooksecurefunc: unknown function " .. rawtostring(name), 2) end
    tbl[name] = function(...)
      local results = { orig(...) }
      hook(...)
      return unpack(results)
    end
  end
  env.securecallfunction = function(f, ...) return f(...) end
  local error_handler = function(msg) sim.errors[#sim.errors + 1] = rawtostring(msg) return msg end
  env.geterrorhandler = function() return error_handler end
  env.seterrorhandler = function(f) error_handler = f end

  -- Client identity comes from the pinned target.
  env.GetBuildInfo = function()
    return api.version, rawtostring(api.build), "offline", api.interface
  end
  env.WOW_PROJECT_ID, env.WOW_PROJECT_CAMELOT, env.WOW_PROJECT_MAINLINE, env.WOW_PROJECT_CLASSIC = 18, 18, 1, 2
  env.GetLocale = function() return "enUS" end

  -- CVars. A CVar starts at the default value of the build. An unknown CVar reads as nil, like the client.
  local cvar_defaults = api.cvars or {}
  local function get_cvar(name)
    local value = sim.cvars[name]
    if value == nil then value = cvar_defaults[name] end
    return value
  end
  local function set_cvar(name, value)
    if cvar_defaults[name] == nil and sim.cvars[name] == nil then return false end
    if rawtype(value) == "boolean" then value = value and "1" or "0" end
    sim.cvars[name] = value ~= nil and rawtostring(value) or nil
    return true
  end
  local function get_cvar_bool(name)
    local value = get_cvar(name)
    if value == nil then return nil end
    return value ~= "0" and value ~= ""
  end
  env.GetCVar, env.SetCVar, env.GetCVarBool = get_cvar, set_cvar, get_cvar_bool
  env.GetCVarDefault = function(name) return cvar_defaults[name] end
  local c_cvar = { GetCVar = get_cvar, SetCVar = set_cvar, GetCVarBool = get_cvar_bool,
                   GetCVarDefault = env.GetCVarDefault }

  -- FrameXML helpers that addons commonly call during load.
  env.Mixin = function(object, ...)
    for i = 1, select("#", ...) do
      for k, v in pairs((select(i, ...))) do object[k] = v end
    end
    return object
  end
  env.CreateFromMixins = function(...) return env.Mixin({}, ...) end

  -- Colors, as in Blizzard_SharedXML/Color.lua. Many addons create colors while they load.
  local color_methods = {}
  function color_methods:GetRGB() return self.r, self.g, self.b end
  function color_methods:GetRGBA() return self.r, self.g, self.b, self.a end
  function color_methods:SetRGB(r, g, b) self.r, self.g, self.b = r, g, b end
  function color_methods:SetRGBA(r, g, b, a) self.r, self.g, self.b, self.a = r, g, b, a end
  env.CreateColor = function(r, g, b, a)
    return setmetatable({ r = r, g = g, b = b, a = a or 1 }, { __index = color_methods })
  end
  env.SlashCmdList, env.hash_SlashCmdList = {}, {}

  env.print = function(...)
    local parts = {}
    for i = 1, select("#", ...) do parts[i] = rawtostring((select(i, ...))) end
    sim.chat[#sim.chat + 1] = table.concat(parts, " ")
  end

  local enum = {}
  for name, values in pairs(api.enums) do enum[name] = values end
  env.Enum = enum

  -- Frames ------------------------------------------------------------------
  local frame_mt = {}
  local methods = {}

  function methods:SetScript(kind, fn) self.__scripts[kind] = fn end
  function methods:GetScript(kind) return self.__scripts[kind] end
  function methods:HookScript(kind, fn)
    local orig = self.__scripts[kind]
    self.__scripts[kind] = function(...)
      if orig then orig(...) end
      fn(...)
    end
  end
  function methods:HasScript() return true end
  local function validate_event(event)
    if api.restricted_events[event] then
      error("Frame:RegisterEvent(): " .. event .. " is restricted on this build. The client blocks addon registration.", 3)
    end
    if not api.events[event] then
      error("Frame:RegisterEvent(): " .. rawtostring(event) .. " is not a known event on build " .. api.build, 3)
    end
  end
  function methods:RegisterEvent(event)
    validate_event(event)
    self.__events[event] = true
    return true
  end
  function methods:RegisterUnitEvent(event, ...)
    validate_event(event)
    self.__events[event] = { ... }
    return true
  end
  function methods:UnregisterEvent(event) self.__events[event] = nil end
  function methods:UnregisterAllEvents() self.__events = {} end
  function methods:IsEventRegistered(event) return self.__events[event] ~= nil end
  function methods:Show() self.__shown = true end
  function methods:Hide() self.__shown = false end
  function methods:SetShown(v) self.__shown = not not v end
  function methods:IsShown() return self.__shown end
  function methods:IsVisible() return self.__shown end
  function methods:GetName() return self.__name end
  function methods:GetParent() return self.__parent end
  function methods:GetObjectType() return self.__type end
  function methods:SetID(id) self.__id = id end
  function methods:GetID() return self.__id or 0 end
  function methods:SetAttribute(k, v) self.__attrs[k] = v end
  function methods:GetAttribute(k) return self.__attrs[k] end
  function methods:SetText(v) self.__text = v end
  function methods:GetText() return self.__text end
  function methods:SetValue(v) self.__value = v end
  function methods:GetValue() return self.__value end
  function methods:SetMinMaxValues(a, b) self.__min, self.__max = a, b end
  function methods:GetMinMaxValues() return self.__min, self.__max end

  local function new_frame(kind, name, parent)
    local frame = { __type = kind or "Frame", __name = name, __parent = parent, __scripts = {}, __events = {},
                    __attrs = {}, __shown = true }
    setmetatable(frame, frame_mt)
    sim.frames[#sim.frames + 1] = frame
    if name then env[name] = frame end
    return frame
  end
  local FRAME_TAGS = {}
  for _, tag in ipairs({ "Frame", "Button", "CheckButton", "StatusBar", "Slider", "EditBox", "ScrollFrame",
    "MessageFrame", "ScrollingMessageFrame", "Cooldown", "GameTooltip", "Model", "PlayerModel", "SimpleHTML",
    "ColorSelect", "MovieFrame", "Browser", "Texture", "FontString", "Line", "MaskTexture", "AnimationGroup",
    "Alpha", "Scale", "Translation", "Rotation", "Path", "Animation", "Font", "ItemButton", "DropdownButton",
    "EventFrame", "EventButton", "ContainedAlertFrame" }) do
    FRAME_TAGS[tag] = true
  end
  local CONTAINER_TAGS = { Frames = true, Layers = true, Layer = true, Animations = true, ScrollChild = true }
  local templates = setmetatable({}, { __index = api.templates })

  local apply_template

  local function compile_script(tag, source, chunk_name)
    local header = tag == "OnEvent" and "return function(self, event, ...) " or "return function(self, ...) "
    local chunk, syntax = loadstring(header .. source .. "\nend", "@" .. chunk_name)
    if not chunk then error(syntax, 0) end
    setfenv(chunk, env)
    return chunk()
  end

  local function apply_scripts(frame, node, file)
    for _, script in ipairs(node.children) do
      local handler = script.attrs["function"]
      local method = script.attrs["method"]
      if handler then
        local name = handler
        frame.__scripts[script.tag] = function(...) return env[name](...) end
      elseif method then
        local name = method
        frame.__scripts[script.tag] = function(self, ...) return self[name](self, ...) end
      elseif script.text then
        frame.__scripts[script.tag] = compile_script(script.tag, script.text, file)
      end
    end
  end

  -- Build the children of an XML node on a frame. Templates add their children first.
  local function build_children(frame, node, file)
    for _, child in ipairs(node.children) do
      if child.tag == "Scripts" then
        apply_scripts(frame, child, file)
      elseif CONTAINER_TAGS[child.tag] then
        build_children(frame, child, file)
      elseif FRAME_TAGS[child.tag] then
        sim:build_xml(child, frame, file)
      end
    end
  end

  -- The SecureHandler templates add methods to a frame. The restricted environment is not simulated,
  -- so these methods only keep the data that a test can read back and run nothing.
  local function install_secure_methods(frame)
    frame.__refs = frame.__refs or {}
    rawset(frame, "WrapScript", function() end)
    rawset(frame, "UnwrapScript", function() end)
    rawset(frame, "SetFrameRef", function(self, label, other) self.__refs[label] = other end)
    rawset(frame, "GetFrameRef", function(self, label) return self.__refs[label] end)
    rawset(frame, "Execute", function() end)
    rawset(frame, "ExecuteFrameScript", function() end)
    rawset(frame, "RunAttribute", function() end)
    rawset(frame, "ChildUpdate", function() end)
  end

  apply_template = function(frame, names, file)
    for name in (names or ""):gmatch("[^,%s]+") do
      if name:find("SecureHandler", 1, true) then install_secure_methods(frame) end
      local template = templates[name]
      if not template then
        error("CreateFrame: the template " .. name .. " does not exist on build " .. api.build, 3)
      end
      if template.attrs.inherits then apply_template(frame, template.attrs.inherits, file) end
      if template.attrs.mixin and rawget(env, template.attrs.mixin) then
        env.Mixin(frame, rawget(env, template.attrs.mixin))
      end
      build_children(frame, template, file)
    end
  end

  function sim:build_xml(node, parent, file)
    local attrs = node.attrs
    if attrs.virtual and attrs.virtual:lower() == "true" then
      templates[attrs.name] = node
      return nil
    end
    if not FRAME_TAGS[node.tag] then return nil end
    local name = attrs.name
    -- $parent is the name of the closest named ancestor. An unnamed frame passes the name of its parent on.
    local context = parent and (parent.__name or parent.__name_context)
    if name and context then name = name:gsub("%$parent", context) end
    local frame = new_frame(node.tag, name, parent)
    frame.__name_context = context
    if attrs.parent then frame.__parent = env[attrs.parent] end
    if parent and attrs.parentkey then parent[attrs.parentkey] = frame end
    if parent and attrs.parentarray then
      parent[attrs.parentarray] = parent[attrs.parentarray] or {}
      table.insert(parent[attrs.parentarray], frame)
    end
    if attrs.inherits then apply_template(frame, attrs.inherits, file) end
    if attrs.mixin and rawget(env, attrs.mixin) then env.Mixin(frame, rawget(env, attrs.mixin)) end
    build_children(frame, node, file)
    local on_load = frame.__scripts.OnLoad
    if on_load then on_load(frame) end
    return frame
  end

  function methods:CreateFontString(name) return new_frame("FontString", name, self) end
  function methods:CreateTexture(name) return new_frame("Texture", name, self) end
  function methods:CreateAnimationGroup(name) return new_frame("AnimationGroup", name, self) end
  function methods:CreateAnimation(kind, name) return new_frame(kind or "Animation", name, self) end
  function methods:CreateLine(name) return new_frame("Line", name, self) end

  frame_mt.__index = function(self, key)
    local method = methods[key]
    if method then return method end
    local kinds = api.widget_methods[key]
    if kinds then
      -- The method exists on the client. The simulator returns neutral values of the documented types.
      return function()
        local out = {}
        for i, kind in ipairs(kinds) do
          if kind == "number" then out[i] = 0
          elseif kind == "boolean" then out[i] = false
          elseif kind == "string" then out[i] = ""
          end
        end
        -- Object returns stay nil. Trailing nils are dropped, so that GetRegions and GetChildren return nothing
        -- and loops over select("#", ...) do not index a nil value.
        local last = 0
        for i = 1, #kinds do
          if out[i] ~= nil then last = i end
        end
        return unpack(out, 1, last)
      end
    end
    return nil
  end

  env.CreateFrame = function(kind, name, parent, template)
    local frame = new_frame(kind, name, parent)
    if template then apply_template(frame, template, "CreateFrame") end
    local on_load = frame.__scripts.OnLoad
    if on_load then on_load(frame) end
    return frame
  end
  env.UIParent = new_frame("Frame", "UIParent")
  env.WorldFrame = new_frame("Frame", "WorldFrame")
  env.DEFAULT_CHAT_FRAME = new_frame("MessageFrame", "DEFAULT_CHAT_FRAME")
  env.DEFAULT_CHAT_FRAME.AddMessage = function(_, text) sim.chat[#sim.chat + 1] = rawtostring(text) end

  -- Timers ------------------------------------------------------------------
  local function add_timer(delay, fn, iterations, handle)
    local timer = handle or {}
    timer.__fire, timer.__fn, timer.__delay, timer.__left = sim.now + delay, fn, delay, iterations
    timer.Cancel = function(self) self.__cancelled = true end
    timer.IsCancelled = function(self) return self.__cancelled == true end
    sim.timers[#sim.timers + 1] = timer
    return timer
  end

  local c_timer = {
    After = function(delay, fn) add_timer(delay, fn, 1) end,
    NewTimer = function(delay, fn) return add_timer(delay, fn, 1) end,
    NewTicker = function(delay, fn, iterations) return add_timer(delay, fn, iterations or math.huge) end,
  }

  local c_addons = {
    IsAddOnLoaded = function(name) return sim.loaded[name] == true end,
    GetAddOnMetadata = function(_, key) return key == "Version" and "test" or nil end,
  }

  -- An unknown name reads as nil. A known name without a fake raises an error when called.
  local function missing_fake(name)
    return function()
      error("waw: " .. name .. " exists on build " .. api.build .. " but has no fake. Call wow.stub(\"" .. name .. "\", fn) in the test.", 2)
    end
  end

  -- The event table of the snapshot decides, like the client does.
  local c_event_utils = {
    IsEventValid = function(event) return api.events[event] ~= nil end,
  }

  -- C_CurveUtil.EvaluateColorFromBoolean accepts a secret boolean. The client picks the color without revealing it.
  local c_curve_util = {
    EvaluateColorFromBoolean = function(value, if_true, if_false)
      if is_secret(value) then value = secrets[value].value end
      return value and if_true or if_false
    end,
  }
  local namespaces = { C_Timer = c_timer, C_AddOns = c_addons, C_EventUtils = c_event_utils, C_CVar = c_cvar,
                       C_CurveUtil = c_curve_util }
  local namespace_mt = {
    __index = function(ns, key)
      local full = rawget(ns, "__ns_name") .. "." .. key
      if api.functions[full] then return missing_fake(full) end
      return nil
    end,
  }
  local function namespace(name)
    local ns = namespaces[name]
    if not ns then
      ns = {}
      namespaces[name] = ns
    end
    if not getmetatable(ns) then
      rawset(ns, "__ns_name", name)
      setmetatable(ns, namespace_mt)
    end
    return ns
  end

  -- A FrameXML global exists in the client, but the simulator does not run FrameXML.
  local function ui_proxy(name)
    local proxy = namespaces[name]
    if proxy then return proxy end
    local function missing(_, key)
      error("waw: FrameXML global " .. name .. (key and ("." .. rawtostring(key)) or "")
        .. " exists on the client but has no fake. Call wow.stub in the test.", 2)
    end
    proxy = setmetatable({}, { __index = missing, __call = function() missing() end })
    namespaces[name] = proxy
    return proxy
  end

  local has_namespace = {}
  for full in pairs(api.functions) do
    local head = full:match("^([%w_]+)%.")
    if head then has_namespace[head] = true end
  end

  setmetatable(env, {
    __index = function(_, key)
      if rawtype(key) ~= "string" then return nil end
      if has_namespace[key] then return namespace(key) end
      if api.functions[key] then return missing_fake(key) end
      if api.ui_globals[key] then return ui_proxy(key) end
      return nil
    end,
  })

  -- Public helpers ----------------------------------------------------------
  function sim:stub(name, fn)
    local parts = split_path(name)
    local known = api.functions[name] or api.ui_globals[parts[1]] or (#parts == 1 and rawget(env, name) ~= nil)
    if not known then
      error("waw: cannot stub " .. name .. " because it does not exist on build " .. api.build, 2)
    end
    if #parts == 1 then
      rawset(env, name, fn)
    elseif has_namespace[parts[1]] then
      rawset(namespace(parts[1]), parts[2], fn)
    else
      rawset(ui_proxy(parts[1]), parts[2], fn)
    end
  end

  function sim:secret(value) return make_secret(value) end
  -- A secret table. Index, length, pairs, ipairs and next raise the error of the client.
  function sim:secret_table(content) return make_secret_table(content or {}) end
  -- Turn the rewrite of "name.field == true" on or off for the addons that load next. The default is on.
  function sim:strict_compare(enabled) sim.strict = enabled ~= false end
  function sim:reveal(value)
    if is_secret(value) then return secrets[value].value end
    return value
  end

  function sim:load(name)
    local info = api.addons[name]
    if not info then error("waw: unknown addon " .. rawtostring(name), 2) end
    local ns = {}
    for _, saved in ipairs(info.saved) do
      if sim.saved[saved] ~= nil then env[saved] = sim.saved[saved] end
    end
    for _, item in ipairs(info.files) do
      if item.xml then
        sim:build_xml(item.xml, nil, info.dir .. "/xml")
      else
        local chunk = compiled_chunk(info.dir .. "/" .. item.lua, sim.strict ~= false)
        setfenv(chunk, env)
        chunk(name, ns)
      end
    end
    sim.loaded[name] = true
    return ns
  end

  -- Load an addon after the addons that it depends on. Return the load order.
  function sim:load_with_deps(name, order)
    order = order or {}
    for _, dep in ipairs(api.addons[name].deps or {}) do
      if api.addons[dep] and not sim.loaded[dep] then sim:load_with_deps(dep, order) end
    end
    sim:load(name)
    order[#order + 1] = name
    return order
  end

  function sim:fire(event, ...)
    if not api.events[event] then error("waw: " .. rawtostring(event) .. " is not an event on build " .. api.build, 2) end
    local unit = ...
    local snapshot = copy_table(sim.frames)
    for _, frame in ipairs(snapshot) do
      local registration = frame.__events[event]
      local deliver = registration == true
      if rawtype(registration) == "table" then
        for _, wanted in ipairs(registration) do
          if wanted == unit then deliver = true end
        end
      end
      if deliver then
        local handler = frame.__scripts.OnEvent
        if handler then handler(frame, event, ...) end
      end
    end
  end

  function sim:login(names)
    for _, name in ipairs(names) do sim:fire("ADDON_LOADED", name, false) end
    sim:fire("PLAYER_LOGIN")
    sim:fire("PLAYER_ENTERING_WORLD", true, false)
  end

  function sim:logout()
    sim:fire("PLAYER_LOGOUT")
    for name in pairs(sim.loaded) do
      for _, saved in ipairs(api.addons[name].saved) do sim.saved[saved] = rawget(env, saved) end
    end
  end

  -- Run the OnUpdate script of every shown frame. A frame counts as shown if it and its parents are shown.
  local function run_on_update(elapsed)
    for _, frame in ipairs(sim.frames) do
      local script = frame.__scripts and frame.__scripts.OnUpdate
      if script then
        local visible, node = true, frame
        while node do
          if not node.__shown then visible = false break end
          node = node.__parent
        end
        if visible then script(frame, elapsed) end
      end
    end
  end

  -- Time moves in steps of 0.05 seconds, like a game that runs at 20 frames per second.
  -- Each step runs the timers that are due and then the OnUpdate scripts.
  local STEP = 0.05

  function sim:advance(seconds)
    local target = sim.now + seconds
    while sim.now < target - 1e-9 do
      local step = math.min(STEP, target - sim.now)
      sim:advance_timers(step)
      run_on_update(step)
    end
  end

  function sim:advance_timers(seconds)
    local stop = sim.now + seconds
    while true do
      local nearest
      for _, timer in ipairs(sim.timers) do
        if not timer.__cancelled and timer.__fire <= stop and (not nearest or timer.__fire < nearest.__fire) then
          nearest = timer
        end
      end
      if not nearest then break end
      sim.now = nearest.__fire
      nearest.__left = nearest.__left - 1
      if nearest.__left <= 0 then
        nearest.__cancelled = true
      else
        nearest.__fire = sim.now + nearest.__delay
      end
      nearest.__fn(nearest)
    end
    sim.now = stop
  end

  function sim:set_combat(value)
    sim.in_combat = value
    sim:fire(value and "PLAYER_REGEN_DISABLED" or "PLAYER_REGEN_ENABLED")
  end

  return sim
end

return M
