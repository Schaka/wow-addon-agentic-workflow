# Secret values

A secret value is a value that addon code can store and display but cannot read. The client uses secret values to stop addons from making decisions with combat data.

Source: the Warcraft Wiki page Secret Values, and the fields in the Blizzard API documentation.

## What addon code can do

Addon code can do these things with a secret value:

1. Store it in a variable or a table value.
2. Pass it to a function or to a widget.
3. Concatenate a secret string or number.
4. Use it with `string.format`, `string.join` and `string.concat`. The result is secret.
5. Call `type()`. It returns the real type.
6. Test the truth of a secret that is not a boolean.

## What raises an error

Addon code cannot do these things with a secret value:

1. Arithmetic.
2. Comparison.
3. A truth test on a secret boolean.
4. The `#` operator.
5. Use as a table key.
6. Index or call it.

`pcall` catches the error, but it does not give access to the value.

## How to find secret values

Run `./waw api lookup UnitHealth` and read `flags`.

| Flag | Meaning |
| --- | --- |
| `SecretReturns` | The return values can be secret |
| `SecretWhenUnitStatsRestricted` and other `SecretWhen*` flags | The return values are secret under that condition |
| `ConditionalSecret` | The return values are secret under conditions that the API defines |
| `RequiresUnitAuraAccess` and other `Requires*` flags | The call needs that access |
| `HasRestrictions` | The API or event has restrictions |
| `IsProtectedFunction` | Only secure code can call it in some states |

Run `./waw api restrictions` to list them. An event can have the same kinds of flags for its payload.

## Patterns

Pass a value directly to a widget. A widget accepts a secret value:

```lua
local current = UnitHealth("player")
bar:SetMinMaxValues(0, UnitHealthMax("player"))
bar:SetValue(current)
```

Guard code that needs the real value:

```lua
local current = UnitHealth("player")
if issecretvalue(current) then
  label:SetText("")
else
  label:SetText(ns.FormatPercent(current, maximum))
end
```

If the display depends on a value, use the client helpers. Examples are `C_CurveUtil.CreateCurve` and `C_DurationUtil.CreateDuration`.

## A payload can be readable and still hold secret parts

Do not test the payload table and then trust its fields. In the real client, the payload of `UNIT_AURA` for an enemy in combat was a plain table, but `updateInfo.isFullUpdate` was a secret boolean and `updateInfo.addedAuras` was a secret table. The code `updateInfo.isFullUpdate == true` raised the error "attempt to compare field 'isFullUpdate' (a secret boolean value)".

Follow these rules for every payload and every table that an API with a `Secret*` flag returns:

1. Make sure that each field is readable before you use it. For a boolean use `issecretvalue(value)` or a helper such as `Secret.IsTrue`. For a table use `issecrettable` or a helper such as `Secret.IsSecretTable`.
2. If the change list is not readable, do nothing for that update. A new scan cannot read secret auras either.
3. Never compare a field with `true`, `false` or `nil` before you know that it is readable.

The rule `secret-bool-compare` of `./waw check` warns about `field == true` and similar forms. The simulator can deliver this payload. See `wow.secret_table` in `docs/testing.md`.

## Show secret auras with an aura container

A secret aura has a secret spell ID, a secret icon and a secret time. The addon cannot look up the spell. It also cannot pass a secret `auraInstanceID` back to `C_UnitAuras`, because those arguments are `AllowedWhenUntainted`. So the client must draw the aura. This is the job of the aura container of Blizzard (`Blizzard_AuraContainer`). Its XML loads into the global environment, so that addon code can create it.

The pattern:

1. Create the container with `CreateFrame("AuraContainer", nil, parent, "CustomAuraContainerTemplate")` and call `SetUnit(unit)`.
2. Call `AddAuraGroup(groupKey, filterString, options)` for each kind of aura. The filter string uses `AuraUtil.AuraFilters`, for example `HARMFUL|CROWD_CONTROL` or `HELPFUL|BIG_DEFENSIVE`. A filter string combines with AND. It has no OR.
3. In `options.initializeFrame`, create a texture and a cooldown as children of the aura frame. Give them to the frame with `SetIcon(texture)` and `SetDurationCooldown(cooldown)`. The client then sets the icon and the time, also for a secret aura. Do all other setup here, because the client denies tainted access to the aura frame while auras are secret.
4. Use `options.maxFrameCount`, `options.sortMethod` and `options.layout` (`layoutIndex`) to choose how many frames show and in which order. Change them later with `SetAuraGroupMaxFrameCount`, `SetAuraGroupSortMethod` and `SetAuraGroupLayout`.
5. Call `container:UpdateAllAuras()` after a change of the target, because the container does not listen to `PLAYER_TARGET_CHANGED`.

The source is `Blizzard_AuraContainer/Blizzard_CustomAuraContainer.lua` and `Blizzard_AuraContainerShared.lua`. The container is not a protected frame, so combat lockdown does not apply to it. The addon cannot read which aura the client shows. It cannot filter by the type of crowd control, and it cannot set a priority per spell. Test this path in the client.

## Tests

1. Use `wow.secret(value)` in an offline test. The simulator raises an error for arithmetic and for `<`. Use `wow.secret_table(table)` for a secret table.
2. An offline test finds `secret == true` only in the plain pattern `name.field == true`. It does not find `secret == 5` or a truth test. See the limits in `docs/testing.md`.
3. In the client, force restrictions with the CVar `addonCombatRestrictionsForced`, then repeat the in-client test.
