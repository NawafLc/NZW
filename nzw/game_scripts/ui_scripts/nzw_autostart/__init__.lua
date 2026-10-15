-- NZW auto-start (installed by the NZW launcher into <GameRoot>/boiii/ui_scripts/).
--
-- Inert unless the launcher started the game with `+set nzw_autostart 1`.
-- On the first frontend load it mounts the requested mod (or "usermaps"),
-- which reloads the frontend and runs this script again, then starts the map
-- and clears nzw_autostart so returning to the menu after a match stays put.

-- Progress is written to the nzw_autostart_status dvar; type
-- `nzw_autostart_status` in the boiii console to read it.
local function status(text)
  pcall(Engine.SetDvar, "nzw_autostart_status", text)
  print("[NZW] " .. text)
end

local currentMap = Engine.GetCurrentMap()
if currentMap ~= "core_frontend" then
  return
end

local function dvarString(name)
  local ok, value = pcall(Engine.DvarString, nil, name)
  if ok and type(value) == "string" then
    return value
  end
  return ""
end

local function dvarInt(name)
  return tonumber(dvarString(name)) or 0
end

if dvarInt("nzw_autostart") ~= 1 then
  status("loaded, inactive (nzw_autostart=" .. dvarString("nzw_autostart") .. ")")
  return
end
status("loaded, active")

local wantMod = dvarString("nzw_autostart_mod")
local wantModAlt = dvarString("nzw_autostart_mod_alt")
local mapName = dvarString("nzw_autostart_map")
local mapCmd = dvarString("nzw_autostart_cmd")
if mapCmd == "" then
  mapCmd = "devmap"
end

local function abort(reason)
  Engine.SetDvar("nzw_autostart", 0)
  status("aborted: " .. reason)
end

local function activeMod()
  if type(Engine.IsUsingMods) == "function" and Engine.IsUsingMods() and type(Engine.UsingModsUgcName) == "function" then
    return Engine.UsingModsUgcName() or ""
  end
  return ""
end

if mapName == "" then
  abort("no map requested")
  return
end

local current = activeMod()
if wantMod ~= "" and current ~= wantMod and (wantModAlt == "" or current ~= wantModAlt) then
  local tries = dvarInt("nzw_autostart_tries")
  if tries >= 2 then
    abort("mod '" .. wantMod .. "' did not load (active: '" .. current .. "')")
    return
  end
  Engine.SetDvar("nzw_autostart_tries", tries + 1)
  status("loading mod " .. wantMod .. " (active: '" .. current .. "')")
  local ok = pcall(LuaUtils.Mods_LoadMod, wantMod)
  if not ok then
    Engine.Exec(0, "loadmod " .. wantMod)
  end
  return
end

-- The title screen has no session mode (eModes INVALID = 3); loading a ZM
-- map from there crashes on missing ZM HUD assets. Switch to Zombies first,
-- the way boiii does before joining a server (Com_SwitchMode).
local MODE_ZOMBIES = 0

local function sessionMode()
  local ok, mode = pcall(Engine.CurrentSessionMode)
  return ok and tonumber(mode) or -1
end

local function addTimer(ms, fn)
  for _, rootName in ipairs({ "UIRootFull", "UIRoot0" }) do
    local ok = pcall(function()
      LUI.roots[rootName]:addElement(LUI.UITimer.newElementTimer(ms, true, fn))
    end)
    if ok then
      return rootName
    end
  end
  return nil
end

local delay = dvarInt("nzw_autostart_delay")
if delay <= 0 then
  delay = 1000
end

local fired = false
local function launch()
  if fired or dvarInt("nzw_autostart") ~= 1 then
    return
  end
  fired = true
  Engine.SetDvar("nzw_autostart", 0)
  status("ran: " .. mapCmd .. " " .. mapName .. " (sessionMode=" .. sessionMode() .. ")")
  Engine.Exec(0, mapCmd .. " " .. mapName)
end

local function scheduleLaunch()
  local root = addTimer(delay, launch)
  if root then
    status("waiting " .. delay .. "ms (" .. root .. ") to run " .. mapCmd .. " " .. mapName)
  else
    launch()
  end
end

if sessionMode() == MODE_ZOMBIES then
  scheduleLaunch()
  return
end

local modeTries = dvarInt("nzw_autostart_modetries")
if modeTries >= 2 then
  abort("could not switch to Zombies (sessionMode=" .. sessionMode() .. ", last: "
    .. dvarString("nzw_autostart_modelog") .. ")")
  return
end
Engine.SetDvar("nzw_autostart_modetries", modeTries + 1)

local attempts = {}
local function try(label, f, ...)
  if type(f) ~= "function" then
    attempts[#attempts + 1] = label .. ":missing"
    return false
  end
  local ok, err = pcall(f, ...)
  attempts[#attempts + 1] = label .. (ok and ":ok" or (":err " .. tostring(err)))
  return ok
end

local controller = 0
pcall(function()
  controller = Engine.GetPrimaryController() or 0
end)

-- 1) Navigate the lobby VM into the local Zombies lobby, like the menu does.
local target = nil
pcall(function()
  target = LobbyData.UITargets.UI_ZMLOBBYLANGAME
end)
local switched = false
if target ~= nil then
  switched = try("GoForward", Engine.LobbyVM_CallFunc, "GoForward",
    { controller = controller, toTarget = target })
else
  attempts[#attempts + 1] = "UI_ZMLOBBYLANGAME:missing"
end
-- 2) Fall back to switching the session mode directly.
if not switched then
  switched = try("SwitchMode(c,'zm')", Engine.SwitchMode, controller, "zm")
    or try("SwitchMode(c,0)", Engine.SwitchMode, controller, MODE_ZOMBIES)
end

local log = table.concat(attempts, "; ")
Engine.SetDvar("nzw_autostart_modelog", log)
status("switching to Zombies: " .. log)

-- If the switch reloads the frontend this script runs again in ZM mode.
-- Otherwise poll a few times for the mode change.
local polls = 0
local function poll()
  if fired or dvarInt("nzw_autostart") ~= 1 then
    return
  end
  if sessionMode() == MODE_ZOMBIES then
    scheduleLaunch()
    return
  end
  polls = polls + 1
  if polls >= 8 then
    abort("still sessionMode=" .. sessionMode() .. " after switch attempts: " .. log)
    return
  end
  addTimer(1000, poll)
end
addTimer(1000, poll)
