-- Pure logic. This file does not call the game API, so tests are simple.
local _, ns = ...

ns.defaults = { showPercent = true, greeted = 0 }

-- Copy missing default values into a saved table.
function ns.ApplyDefaults(saved, defaults)
  for key, value in pairs(defaults) do
    if saved[key] == nil then saved[key] = value end
  end
  return saved
end

function ns.FormatPercent(current, maximum)
  if maximum <= 0 then return "0%" end
  return string.format("%d%%", math.floor(current / maximum * 100 + 0.5))
end
