-- Run the real harness in the simulator and write its SavedVariables file.
-- Usage: lua harness_roundtrip.lua <manifest.lua> <harness dir> <output file>
local wowsim = require("wowsim")
local api = dofile(arg[1])
local dir, output = arg[2], arg[3]
api.addons["!WawHarness"] = { dir = dir, files = { { lua = "Manifest.lua" }, { lua = "Core.lua" }, { lua = "Specs.lua" } }, saved = { "WawHarnessDB" }, specs = {} }

local sim = wowsim.new(api)
sim:stub("C_AddOns.GetAddOnInfo", function(name) return name, name, "", true, nil, "INSECURE" end)
sim:stub("UnitHealth", function() return 1 end)
sim:stub("UnitHealthMax", function() return 2 end)
sim:load("!WawHarness")
for name in pairs(api.addons) do
  if name ~= "!WawHarness" then sim:load(name) end
end
local names = { "!WawHarness" }
for name in pairs(api.addons) do
  if name ~= "!WawHarness" then names[#names + 1] = name end
end
sim:login(names)
sim:advance(10)
sim.env.geterrorhandler()("Interface/AddOns/ExampleAddon/Core.lua:9: example failure")
sim:logout()

local function serialize(value, out)
  local kind = type(value)
  if kind == "table" then
    out[#out + 1] = "{\n"
    for k, v in pairs(value) do
      out[#out + 1] = "[" .. (type(k) == "string" and string.format("%q", k) or tostring(k)) .. "] = "
      serialize(v, out)
      out[#out + 1] = ",\n"
    end
    out[#out + 1] = "}"
  elseif kind == "string" then
    out[#out + 1] = string.format("%q", value)
  else
    out[#out + 1] = tostring(value)
  end
end
local out = { "WawHarnessDB = " }
serialize(sim.env.WawHarnessDB, out)
local handle = assert(io.open(output, "w"))
handle:write(table.concat(out))
handle:close()
