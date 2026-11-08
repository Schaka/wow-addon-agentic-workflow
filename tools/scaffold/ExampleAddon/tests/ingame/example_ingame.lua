-- In-client tests. These run on the real client after a /reload.
describe("ExampleAddon on the client", function()
  it("is loaded", function()
    assert.is_true(C_AddOns.IsAddOnLoaded("ExampleAddon"))
  end)

  it("sees the Forever project id", function()
    assert.equals(WOW_PROJECT_ID, WOW_PROJECT_CAMELOT)
  end)

  it("created its saved data", function()
    assert.not_nil(ExampleAddonDB)
  end)

  it_async("can use a timer", function(done)
    C_Timer.After(0.1, function() done() end)
  end, 2)
end)
