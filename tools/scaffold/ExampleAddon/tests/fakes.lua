-- The fakes that every test of this addon needs. The smoke test uses them too.
wow.stub("UnitHealth", function() return 50 end)
wow.stub("UnitHealthMax", function() return 200 end)
