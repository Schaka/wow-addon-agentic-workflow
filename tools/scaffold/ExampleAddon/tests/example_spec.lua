-- Offline tests. Run them with: ./waw test
describe("ExampleAddon", function()
  local ns

  before_each(function()
    ns = wow.load("ExampleAddon")
  end)

  it("rounds the percentage", function()
    assert.equals(ns.FormatPercent(1, 3), "33%")
    assert.equals(ns.FormatPercent(0, 0), "0%")
  end)

  it("creates saved data at login and counts logins", function()
    wow.login({ "ExampleAddon" })
    assert.equals(ns.db.greeted, 1)
    assert.is_true(ns.db.showPercent)
  end)

  it("keeps saved values over defaults", function()
    wow.saved.ExampleAddonDB = { showPercent = false }
    ns = wow.load("ExampleAddon")
    wow.login({ "ExampleAddon" })
    assert.is_false(ns.db.showPercent)
  end)

  it("does not read a secret health value", function()
    wow.login({ "ExampleAddon" })
    wow.stub("UnitHealth", function() return wow.secret(50) end)
    wow.fire("UNIT_HEALTH", "player")
  end)

  it("raises an error for arithmetic on a secret value", function()
    local secret = wow.secret(50)
    assert.errors(function() return secret + 1 end, "secret")
    assert.errors(function() return secret < 1 end, "secret")
    assert.equals(wow.env.type(secret), "number")
  end)

  it("runs the OnUpdate script of a shown frame when time passes", function()
    local frame = wow.env.CreateFrame("Frame")
    local elapsedTotal = 0
    frame:SetScript("OnUpdate", function(_, elapsed) elapsedTotal = elapsedTotal + elapsed end)
    wow.advance(1)
    assert.is_true(elapsedTotal > 0.99 and elapsedTotal < 1.01)
    frame:Hide()
    wow.advance(1)
    assert.is_true(elapsedTotal < 1.01)
  end)
end)
