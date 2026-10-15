-- NZW probe (installed by the NZW launcher; inert unless `+set nzw_probe 1`).
--
-- Dumps the frontend's lobby buttons, lobby targets and mode-related engine
-- functions to <GameRoot>/nzw_probe.txt, then appends the session/lobby mode
-- every few seconds so navigating into Zombies by hand shows what changes.
-- Needs -unsafe-lua for file access (`python -m nzw --probe` passes it).

if Engine.GetCurrentMap() ~= "core_frontend" then
  return
end
local okFlag, flag = pcall(Engine.DvarString, nil, "nzw_probe")
if not okFlag or flag ~= "1" then
  return
end

local out = io.open("nzw_probe.txt", "a")
if not out then
  Engine.SetDvar("nzw_probe_status", "cannot open nzw_probe.txt (launch with -unsafe-lua)")
  return
end

local function w(...)
  local parts = {}
  for i = 1, select("#", ...) do
    parts[#parts + 1] = tostring(select(i, ...))
  end
  out:write(table.concat(parts, " "), "\n")
  out:flush()
end

local function safe(f, ...)
  local ok, a, b = pcall(f, ...)
  if ok then
    return tostring(a) .. (b ~= nil and (" " .. tostring(b)) or "")
  end
  return "ERR " .. tostring(a)
end

-- Reverse lookup so button actions print as their global function names.
local fnNames = {}
for k, v in pairs(_G) do
  if type(v) == "function" and type(k) == "string" then
    fnNames[v] = k
  end
end
local function fname(f)
  if type(f) ~= "function" then
    return tostring(f)
  end
  return fnNames[f] or "<anonymous>"
end

local function sortedKeys(t)
  local keys = {}
  for k in pairs(t) do
    keys[#keys + 1] = k
  end
  table.sort(keys, function(a, b)
    return tostring(a) < tostring(b)
  end)
  return keys
end

local function modeLine()
  return "sessionMode=" .. safe(Engine.CurrentSessionMode)
    .. " lobbyMode=" .. safe(Engine.GetLobbyMode)
    .. " lobbyMainMode=" .. safe(Engine.GetLobbyMainMode)
    .. " lobbyNetworkMode=" .. safe(Engine.GetLobbyNetworkMode)
    .. " primaryController=" .. safe(Engine.GetPrimaryController)
end

w("==== NZW probe " .. tostring(os and os.date and os.date() or "") .. " ====")
w(modeLine())

w("-- Enum.eModes")
if Enum and Enum.eModes then
  for _, k in ipairs(sortedKeys(Enum.eModes)) do
    w("  " .. tostring(k) .. " = " .. tostring(Enum.eModes[k]))
  end
end
for _, enumName in ipairs({ "LobbyMode", "LobbyMainMode", "LobbyNetworkMode", "LobbyType" }) do
  if Enum and type(Enum[enumName]) == "table" then
    w("-- Enum." .. enumName)
    for _, k in ipairs(sortedKeys(Enum[enumName])) do
      w("  " .. tostring(k) .. " = " .. tostring(Enum[enumName][k]))
    end
  end
end

w("-- Engine functions (mode/lobby/session/launch/map)")
for _, k in ipairs(sortedKeys(Engine)) do
  local n = tostring(k)
  if n:find("Mode") or n:find("Lobby") or n:find("Session") or n:find("Launch") or n:find("Map") or n:find("Controller") then
    w("  Engine." .. n)
  end
end

w("-- Global functions (lobby/navigate/mode/launch/zombie)")
for _, k in ipairs(sortedKeys(_G)) do
  local n = tostring(k)
  if type(_G[k]) == "function" and (n:find("Lobby") or n:find("Navigate") or n:find("Mode") or n:find("Launch") or n:find("ZM") or n:find("Zombie") or n:find("Map")) then
    w("  " .. n)
  end
end

if LuaUtils then
  w("-- LuaUtils functions (lobby/mode/launch/map)")
  for _, k in ipairs(sortedKeys(LuaUtils)) do
    local n = tostring(k)
    if n:find("Lobby") or n:find("Mode") or n:find("Launch") or n:find("Map") or n:find("Mods") then
      w("  LuaUtils." .. n)
    end
  end
end

if CoD and CoD.LobbyButtons then
  w("-- CoD.LobbyButtons")
  for _, k in ipairs(sortedKeys(CoD.LobbyButtons)) do
    local b = CoD.LobbyButtons[k]
    if type(b) == "table" then
      w("  " .. tostring(k) .. " stringRef=" .. tostring(b.stringRef) .. " action=" .. fname(b.action)
        .. " param=" .. tostring(b.param) .. " customId=" .. tostring(b.customId))
    end
  end
end

if LobbyData and LobbyData.UITargets then
  w("-- LobbyData.UITargets")
  for _, k in ipairs(sortedKeys(LobbyData.UITargets)) do
    local t = LobbyData.UITargets[k]
    if type(t) == "table" then
      local fields = {}
      for _, fk in ipairs(sortedKeys(t)) do
        local v = t[fk]
        if type(v) ~= "table" then
          fields[#fields + 1] = tostring(fk) .. "=" .. (type(v) == "function" and fname(v) or tostring(v))
        end
      end
      w("  " .. tostring(k) .. " " .. table.concat(fields, " "))
    end
  end
end

w("-- mode samples every 3s (press ENTER, open Zombies, then Solo/Local)")
Engine.SetDvar("nzw_probe_status", "dump written")

local last = ""
local function sample()
  local line = modeLine()
  if line ~= last then
    last = line
    w(line)
  end
end
pcall(function()
  LUI.roots.UIRootFull:addElement(LUI.UITimer.newElementTimer(3000, false, sample))
end)
