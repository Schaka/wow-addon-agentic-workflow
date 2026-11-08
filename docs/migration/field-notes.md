# Field notes: rebuild combat features

Old combat addons work in three steps: read an event, look up the spell ID in a table, and decide what to show. On Forever, the first two steps fail for enemies in many situations. This document describes how to rebuild each feature, and records what real ports proved.

Each fact names its evidence. "Client" means that a test in the real client showed it. "Docs" means the Blizzard API documentation of the pinned build. "Unconfirmed" means that only other sources report it.

The first port was ArenaLive, a unit frame addon from TBC Classic, on build 1.60.1.70862 in November 2026.

## What addon code can read

| Data | Readable? | Evidence |
| --- | --- | --- |
| `UnitHealth("player")`, `UnitPower("player")` | No, also out of combat | Client |
| `UnitHealthMax("player")`, `UnitName("player")` | Yes, out of combat | Client |
| Auras of the player, out of combat | Yes. `C_Secrets.ShouldAurasBeSecret()` returned false. | Client |
| `UNIT_AURA` payload for an enemy target in combat | No. `isFullUpdate` is a secret boolean, and `addedAuras` is a secret table. | Client |
| Entries of `C_UnitAuras.GetUnitAuras` | Sometimes. The result has `ConditionalSecretContents`. | Docs |
| A secret value as an argument to `C_UnitAuras.*` | No. The functions accept secret arguments only from untainted code. | Docs (`SecretArguments = "AllowedWhenUntainted"`) |
| `spellID` in `UNIT_SPELLCAST_*` events of other players | No, also in the open world and out of combat | Client |
| `Cooldown:GetCooldownTimes` | Secret for a frame with the secret cooldown aspect | Docs |
| Loss of control data of the player (`C_LossOfControl`) | Can be secret: the flag is `SecretWhenLossOfControlRestricted`. `priority` and `displayType` are never secret. | Docs |

### Combat recorder results

The ArenaLive combat recorder measured these facts on 2026-11-08, in the open world, outside any instance:

| Data | Out of combat | In combat |
| --- | --- | --- |
| `UNIT_SPELLCAST_SUCCEEDED` and `UNIT_SPELLCAST_START` of other players on nameplates: `spellID` and `castGUID` | Secret | Secret |
| `UNIT_SPELLCAST_SUCCEEDED` of `player`: `spellID` and `castGUID` | Readable | Readable |
| `UNIT_AURA` of an enemy mob as target: `isFullUpdate`, `addedAuras`, `removedAuraInstanceIDs` | Not measured | Secret |
| `C_UnitAuras.GetUnitAuras(target, "HARMFUL|CROWD_CONTROL", 1)` on an enemy mob | Not measured | Raises an error |
| `UnitCanAttack("player", unit)` | Readable | Readable |
| `C_ChatInfo.InChatMessagingLockdown()` | False | Not measured |
| `C_RestrictedActions.IsAddOnRestrictionActive` for all types | False | False at the start of combat |

Consequences:

1. Enemy spell IDs from nameplates are secret, also in the open world and out of combat. Cast-based tracking of other players does not work.
2. The custom aura container showed the Charge Stun on an enemy mob in combat. Choose the container path for every unit that the player can attack, before its aura data becomes secret.
3. A container that was off misses auras. After you turn it on, call `UpdateAllAuras`.
4. If a mob is immune to an effect, the effect has no aura. Test with more than one mob before you report a defect.
5. The DR tracker of ArenaLive counted Charge Stun on enemy mobs in some fights. Charge starts combat, so the first aura event can still be readable. Do not depend on this for auras later in combat.
6. A container with one group, `HARMFUL|CROWD_CONTROL`, showed the Charge Stun on a portrait. An earlier container with two groups, reordered with `SetAuraGroupLayout` and `SetAuraGroupEnabled`, showed nothing, and raised no error. Use one group per container, and stack containers with frame levels to set a priority.
7. A clipping parent (`SetClipsChildren`) does not hide container frames. A clipped test container showed the stun.
8. `HARMFUL|IMPORTANT` showed nothing for Rend and Charge Stun on mobs. Blizzard documents `IMPORTANT` for helpful auras that show on enemy nameplates.

Before you design a feature, measure the data in the content where the feature must work. The ArenaLive repository has a combat recorder spec that saves which values were secret during play.

## Four tools that still work

1. A widget accepts a secret value. `Texture:SetTexture(secretIcon)`, `StatusBar:SetValue(secretHealth)` and `FontString:SetText(secretName)` all work. Addon code cannot compare or calculate with the value.
2. The client classifies auras for you. Filter strings in `AuraUtil.AuraFilters` include `CROWD_CONTROL`, `BIG_DEFENSIVE`, `EXTERNAL_DEFENSIVE`, `IMPORTANT` and `DISPELLABLE`. Blizzard decides which auras belong to each filter.
3. A custom aura container (`Blizzard_AuraContainer`) lets the client choose, sort and draw auras from a filter string. It draws the icon and the timer, also for auras that addon code cannot read.
4. `C_CurveUtil.EvaluateColorFromBoolean(secretBoolean, colorIfTrue, colorIfFalse)` picks a color from a secret boolean. Pass the result to a widget with `color:GetRGB()`. For example, `IsShown()` of the shield on a Blizzard nameplate cast bar returned a secret boolean in the client.

## Recipe: show the most important crowd control on a portrait

This covers features like BigDebuffs, a CC indicator on a portrait, or a big icon on a nameplate.

1. For a unit that the player cannot attack, with readable aura data, use your own spell table and priorities. This path keeps full user control.
2. For a unit that the player can attack, use custom aura containers over the portrait: one container with the group `HARMFUL|CROWD_CONTROL`, and one with `HELPFUL|BIG_DEFENSIVE`. Give each container one group with `maxFrameCount = 1`. Stack them at the same spot, and give the container with the higher priority the higher frame level.
3. Make sure that only one of the two paths shows at a time.

ArenaLive-Forever implements this in `addons/ArenaLive3/CCIndicator.lua` and `AuraContainerUtil.lua`. It worked in the client on build 70862.

Do not match auras by icon. A secret icon cannot be compared, so an icon table cannot find it. "Show the newest aura big" does not work either, because addon code cannot read which aura is newest, and it cannot filter. The client filter is the only filter that works on secret data.

What the user loses on the container path: the per-spell priorities, custom spell lists, and every order except the order between the containers. Blizzard's list of crowd control effects decides what shows.

Other addons: current BigDebuffs skips every aura whose spell ID is secret. On restricted clients, it shows nothing for those auras.

## Recipe: diminishing returns

Diminishing returns tracking needs the spell ID, the target and the time of each crowd control effect. Without the combat log, the only source is the aura data of units that the player sees: target, focus, party members and nameplates.

1. Read `UNIT_AURA` for those units. Guard every field of the payload, because each field can be secret.
2. If the spell ID is readable, look up the category and update the tracker.
3. If the spell ID is secret, do not guess. Show nothing, or show that the state is unknown.
4. Units that the player does not see are not tracked.

Expect this to work for readable situations only. For enemies in combat, it often shows nothing. Do not use `UNIT_SPELLCAST_SUCCEEDED` of other players as a second source. The combat recorder showed that their spell IDs are secret.

For the category data, use DRList-1.0 (MIT license). DRList does not know the Forever project ID 18 and falls back to its MoP table. Map `WOW_PROJECT_CAMELOT` to its Classic table. No source shows yet whether Forever uses the Classic categories.

Other addons: DRPulse and Forever Simple DR track only target, focus and nameplates, and show which crowd control is not certain.

## Recipe: enemy cooldowns and special icons

Cooldown tracking needs the spell ID of each enemy cast.

1. Listen to `UNIT_SPELLCAST_SUCCEEDED` for target, focus, party and nameplate units.
2. If the spell ID is readable, start the cooldown from your table.
3. If it is secret, do nothing.

Enemy cooldowns in restricted content stay unknown. Show the class icon or the racial as a fallback.

## Recipe: share the cooldowns of your own group

Each player can read their own casts, so an addon can send them to the group.

1. Listen to `UNIT_SPELLCAST_SUCCEEDED` for `player`. Blizzard states that the player's own casts are not secret.
2. Send the spell ID with `C_ChatInfo.SendAddonMessage`. The function has no secret flags.
3. Before you send, call `C_ChatInfo.InChatMessagingLockdown()`. If it returns true, do not send.

Reports say that addons cannot send messages inside instances. Battlegrounds are instances. The combat recorder measures where the lockdown applies. Until then, this recipe is unconfirmed for instances.

Use an established library before you write your own protocol. The established library is Open Raid Library (LibOpenRaid, LGPL-2.1), which Details! uses. Its state in November 2026:

1. The upstream version does not load on Forever. It loads only for `WOW_PROJECT_MAINLINE` or an interface value of 100000 or higher, and Forever is 16001.
2. On Midnight, it sends no messages in combat and does not read cooldowns.
3. A copy that loads on Forever raises errors on secret spell IDs from party casts. The issue is Tercioo/Open-Raid-Library#73, open and without an answer.

If the combat recorder shows that messaging works where the feature needs it, add Forever support to LibOpenRaid and offer it upstream. Do not build a protocol that only one addon understands.

## Recipe: buff and debuff bars on enemies

The same container can draw a full buff and debuff bar. The ArenaLive aura bar uses it for every unit that the player can attack. The facts below come from the Blizzard source of the pinned build. The client has not shown yet that the bar works. Mark each fact "Docs" until a test in the client shows it.

1. Use two or three groups: `HELPFUL` for buffs, and `HARMFUL` for debuffs. Order them with `layoutIndex`, and give the second section `forceNewLine = true`. The target frame of Blizzard does the same. Evidence: Docs.
2. A filter string can negate a part with a leading `!`. `HARMFUL|PLAYER` shows the own debuffs, and `HARMFUL|!PLAYER` shows all others. Use the pair to draw the own debuffs larger without a double display. The part `RAID` turns a group into castable buffs or dispellable debuffs. Evidence: Docs (`AuraUtil.IsValidFilterString`).
3. The layout of the whole container has its own methods: `SetFlowLayoutAnchorPoint`, `SetFlowLayoutGrowthDirection(horizontal, vertical)` and `SetFlowLayoutMaximumLineSize`. The values of the direction are in `AnchorUtil.FlowDirection`. A group has `elementSpacing`, `lineSpacing`, `groupLineSpacing`, `forceNewLine`, `elementWidth`, `elementHeight` and `layoutIndex`. Evidence: Docs.
4. The container sets its own size from the frames that it shows. Addon code cannot hook the size change, because the container forbids untrusted layout scripts. `GetAuraGroupFrameCount` returns the number of frames that the client created in batches, not the number of visible auras. If a frame below the container needs a size, keep a fixed size from the configuration. Evidence: Docs.
5. The client fixes the size of an aura frame at creation. A new icon size needs a new container. Evidence: Docs (`DenyTaintedAccessWhenAurasAreSecret`).
6. When the frame gets a unit that the player can attack, choose the path at that moment. A late switch after the first secret aura event misses that aura. After you enable a container, call `UpdateAllAuras`. Evidence: Client for the crowd control indicator.

Options that the container cannot map: lists of spell IDs (the spell ID is secret), tooltips of the aura, and a maximum that counts over two groups.

## Reference addon

MiniAuras (formerly MiniCC) supports Forever. It shows crowd control on portraits, party frames and nameplates through custom aura containers with the `CROWD_CONTROL`, `IMPORTANT`, `BIG_DEFENSIVE` and `EXTERNAL_DEFENSIVE` filters. For your own interrupt, it reads the player's casts. For an ally, it uses the known interrupt spell of the class. Its license is "All Rights Reserved". Learn the approach, and do not copy its code.

Hooks on Blizzard functions do not reveal more data. A hook receives the same secret values, and the Blizzard aura code runs in a secure environment.

## Recipe: crowd control on the player

The client shows its own loss of control display. `C_LossOfControl.GetActiveLossOfControlData(index)` returns the same data. Use `priority` and `displayType`, which are never secret, to choose an entry. Pass the icon and the duration object to widgets.

## Dead ends

These ideas do not get secret data back. Each one was researched during the ArenaLive port. Do not research them again without new evidence, such as a new build or a Blizzard change.

| Idea | Why it fails | Evidence |
| --- | --- | --- |
| Decode a secret value | Secrets are opaque to addon code by design. Blizzard also made side channels secret, such as the width of a secret text. | Docs (secret aspects) |
| Read the tooltip of an aura, as on SoD | The tooltip aura functions are `SecretWhenUnitAuraRestricted`, and addon code cannot read text with a secret aspect. | Docs |
| Hook a Blizzard function | A hook receives the same secret values. The Blizzard aura code runs in a secure environment. | Docs |
| Match an aura by its icon | A secret icon cannot be compared. | Docs |
| Show the newest aura big | Addon code cannot tell which aura is newest, and it cannot filter secret auras. | Docs |
| Read the same unit through its nameplate | Secrecy depends on the unit and the content, not on the unit token. | Docs |
| Pass a secret aura instance ID back to `C_UnitAuras` | The functions accept secret arguments only from untainted code. | Docs |
| Take data from BigDebuffs | BigDebuffs has no Forever build. Its modern path skips every aura with a secret spell ID. | Its source |
| Parse combat log chat lines, from `COMBAT_LOG_MESSAGE` or from the window with `GetMessageInfo` | Each line reaches addon code as an 8-character escape token (shape `\|K...\|k`). The client puts the real text in its place at draw time. The token is readable but carries no data. | Client, 2026-11-08 |
| Hook the Blizzard combat log processor | It runs in the secure environment (`UseSecureEnvironment: 1`) and wraps its calls with `securecallfunction`. The global functions of `Blizzard_CombatLog` only handle menus and filter buttons. | Docs, FrameXML |
| Share cooldowns with Open Raid Library | It does not load on Forever, and it stops messages in combat on Midnight. | Its source |

The only tools that work on secret data are the widgets that accept secret values, the client aura filters, and the custom aura container. If a feature needs a decision in addon code that depends on enemy combat data, assume that the feature cannot work in combat.

## Blizzard frame structure

| Old access | Forever access | Evidence |
| --- | --- | --- |
| `nameplate.UnitFrame.castBar` | `nameplate.UnitFrame.CastBarsContainer.castBar` | Client error, FrameXML |
| `nameplate.UnitFrame.healthBar` | Unchanged | FrameXML |
| `PartyMemberFrame1` to `PartyMemberFrame4` | Member frames from `PartyFrame.PartyMemberFramePool` | FrameXML |

Search the frame in the `wow-framexml-<product>-<build>` code graph project before you read a child of a Blizzard frame.

## File names

The client ignores letter case in file names. Linux tools do not. Use the exact case of the file on disk. `./waw check` reports `toc-file-case` and `xml-file-case`.

## Testing without the right content

Some features need content that a tester cannot reach, for example PvP. Use the CVars in `docs/testing.md` to force the restricted paths. Test with crowd control on mobs. Write down what stays untested.
