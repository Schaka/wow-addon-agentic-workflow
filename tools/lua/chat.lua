-- A fake addon message channel, for offline tests. Get it with wow.addon_channel().
--
-- It installs fakes for C_ChatInfo.RegisterAddonMessagePrefix, IsAddonMessagePrefixRegistered, SendAddonMessage and
-- InChatMessagingLockdown. A test reads what the addon sent in channel.sent, and delivers messages from other players
-- with channel:receive(prefix, text, chatType, sender).
--
-- The rules follow the client and the API documentation of the pinned build:
--   * The client delivers CHAT_MSG_ADDON only for a registered prefix.
--   * SendAddonMessage does not accept secret arguments (SecretArguments = NotAllowed).
--   * A message has at most 255 bytes, and a prefix at most 16 characters.
--   * While channel.lockdown is true, InChatMessagingLockdown returns true and SendAddonMessage returns
--     Enum.SendAddonMessageResult.AddOnMessageLockdown without sending.
--   * The client sends a group message back to its sender too. Set channel.own_name to receive that echo.
--
-- What it does not do: throttling, whisper delivery to offline players and the real roster.

local M = {}

local GROUP_CHANNELS = { PARTY = true, RAID = true, INSTANCE_CHAT = true, GUILD = true, OFFICER = true }

function M.new(sim, env, api)
  local channel = { sent = {}, prefixes = {}, lockdown = false, own_name = nil }
  local results = (rawget(env, "Enum") and env.Enum.SendAddonMessageResult) or {}
  local function result(name, fallback) return results[name] or fallback end

  local function install(path, fn)
    if not api.functions[path] then return end
    local key = path:match("^C_ChatInfo%.([%w_]+)$")
    rawset(env.C_ChatInfo, key, fn)
  end

  install("C_ChatInfo.RegisterAddonMessagePrefix", function(prefix)
    if type(prefix) ~= "string" or #prefix == 0 or #prefix > 16 then return 2 end
    if channel.prefixes[prefix] then return 1 end
    channel.prefixes[prefix] = true
    return 0
  end)
  install("C_ChatInfo.IsAddonMessagePrefixRegistered", function(prefix) return channel.prefixes[prefix] == true end)
  install("C_ChatInfo.InChatMessagingLockdown", function() return channel.lockdown == true end)

  install("C_ChatInfo.SendAddonMessage", function(prefix, text, chatType, target)
    for _, value in ipairs({ prefix, text, chatType, target }) do
      if env.issecretvalue(value) then
        error("C_ChatInfo.SendAddonMessage: secret values are not allowed as arguments", 2)
      end
    end
    if type(prefix) ~= "string" or #prefix == 0 or #prefix > 16 then return result("InvalidPrefix", 1) end
    if type(text) ~= "string" or #text > 255 then return result("InvalidMessage", 2) end
    if chatType == "WHISPER" and (type(target) ~= "string" or target == "") then return result("TargetRequired", 6) end
    if channel.lockdown then return result("AddOnMessageLockdown", 11) end
    channel.sent[#channel.sent + 1] = { prefix = prefix, text = text, chatType = chatType, target = target }
    if channel.own_name and GROUP_CHANNELS[chatType or ""] then
      channel:receive(prefix, text, chatType, channel.own_name)
    end
    return result("Success", 0)
  end)

  -- Delivers a message like the client: only for a registered prefix. Returns true if the message was delivered.
  function channel:receive(prefix, text, chatType, sender)
    if not channel.prefixes[prefix] then return false end
    sim:fire("CHAT_MSG_ADDON", prefix, text, chatType, sender, "", 0, 0, "", 0)
    return true
  end

  -- The sent messages for one prefix, in order.
  function channel:messages(prefix)
    local out = {}
    for _, message in ipairs(channel.sent) do
      if message.prefix == prefix then out[#out + 1] = message end
    end
    return out
  end

  return channel
end

return M
