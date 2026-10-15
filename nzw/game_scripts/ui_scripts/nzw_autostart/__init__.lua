-- NZW auto-start (installed by the NZW launcher into <GameRoot>/boiii/ui_scripts/).
--
-- Inert unless the launcher started the game with `+set nzw_autostart 1`.
-- On the first frontend load it mounts the requested mod (or "usermaps"),
-- which reloads the frontend and runs this script again, then starts the map
-- and clears nzw_autostart so returning to the menu after a match stays put.

if Engine.GetCurrentMap() ~= "core_frontend" then
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
  return
end

local wantMod = dvarString("nzw_autostart_mod")
local wantModAlt = dvarString("nzw_autostart_mod_alt")
local mapName = dvarString("nzw_autostart_map")
local mapCmd = dvarString("nzw_autostart_cmd")
if mapCmd == "" then
  mapCmd = "map"
end

local function abort(reason)
  Engine.SetDvar("nzw_autostart", 0)
  print("[NZW] auto-start aborted: " .. reason)
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
  print("[NZW] loading mod " .. wantMod)
  local ok = pcall(LuaUtils.Mods_LoadMod, wantMod)
  if not ok then
    Engine.Exec(0, "loadmod " .. wantMod)
  end
  return
end

Engine.SetDvar("nzw_autostart", 0)

local delay = dvarInt("nzw_autostart_delay")
if delay <= 0 then
  delay = 1000
end

local function launch()
  print("[NZW] starting " .. mapCmd .. " " .. mapName)
  Engine.Exec(0, mapCmd .. " " .. mapName)
end

-- Give the frontend a moment to finish initialising before changing level.
local scheduled = pcall(function()
  local root = LUI.roots.UIRoot0
  root:addElement(LUI.UITimer.newElementTimer(delay, true, launch))
end)
if not scheduled then
  launch()
end
