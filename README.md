# NZW

A fast external launcher for *Call of Duty: Black Ops III* Zombies. You pick the map, mod and loadout in a small window, press **Play**, and the game starts straight into the match without going through the 3D main menu.

It works like the League of Legends client. There are two processes:

1. **NZW** (Python + Tkinter) opens in under a second. It finds the game and your Steam Workshop content, keeps your settings, and stays minimised while you play.
2. **The game.** NZW starts `boiii.exe` (recommended) or `BlackOps3.exe` with flags that skip the intro, mount the mod and load the map. When the game exits, the NZW window comes back.

## Running it

You need Windows and Python 3.10 or newer. Tkinter ships with the python.org installer.

```bat
pip install .
python -m nzw                                      :: opens the window (pythonw -m nzw: no console)
python -m nzw --list                               :: prints detected maps and mods
python -m nzw --play zm_castle --dry-run           :: prints the command line it would run
python -m nzw --play "Leviathan" --mod 2631943123  :: launches without the window
```

pip also installs `nzw` and `nzw-gui` commands. They only work if pip's Scripts folder is on your PATH. If you get "not recognized", pip printed that folder in a warning during install; add it to PATH, or keep using `python -m nzw`.

To build a single `.exe`, run `pip install pyinstaller` and then `pyinstaller -w -n NZW --add-data "nzw/game_scripts;nzw/game_scripts" -p . nzw/__main__.py`.

## What happens when you press Play

### boiii.exe (default)

```
boiii.exe -launch -nointro -nocinematics -borderless
          +set nzw_autostart 1 +set nzw_autostart_map zm_leviathan
          +set nzw_autostart_mod usermaps
          +set nzw_weapon ar_standard +set nzw_perks specialty_armorvest ...
```

| Flag | Effect (checked against boiii-free source) |
| --- | --- |
| `-launch` | Skips boiii's built-in CEF launcher window (`main.cpp`) |
| `-nointro` | Skips only `BO3_Global_Logo_LogoSequence` (`intro.cpp`) |
| `-nocinematics` | Skips every cinematic played through `Cinematic_StartPlayback` |
| `-borderless` / `-windowed` | Sets `r_fullscreen` to 2 or 0 after the config loads (`startup_flags.cpp`) |
| `-unsafe-lua` | Pre-approves unsafe Lua for overhaul mods (`ui_scripting.cpp`) |

NZW does not use `+map` here, because it can run before the frontend and LPC have finished initialising. Instead, before launching, NZW installs two scripts into `<GameRoot>/boiii/`. The Steam `BlackOps3.exe` never reads that folder.

- `ui_scripts/nzw_autostart/__init__.lua`: on the first `core_frontend` load, it mounts the requested mod (or `usermaps`) with `LuaUtils.Mods_LoadMod`. That reloads the frontend once. The script then runs `devmap <name>` and clears `nzw_autostart`, so returning to the menu after a match doesn't start the map again. It gives up after two failed mod loads. If the game wasn't started by NZW, the script does nothing.
- `custom_scripts/zm/nzw_loadout.gsc`: on the player's first spawn, it reads the `nzw_*` dvars and gives the weapon (optionally Pack-a-Punched), perks, bonus points, GobbleGum pack and a starting gum. It skips perks and gums the map doesn't have.

NZW also makes these changes before launching. All of them are additive:

- Merges your utility binds (F9 `fast_restart`, F10 `map_restart`, F11 `quit`) into `boiii_players/user/binds.cfg`. Your other binds are kept.
- Optionally sets `MaxFPS = "0"` in `boiii_players/config.ini`.
- Creates a directory junction only if a Workshop item lives in a different Steam library from the game. boiii already scans `<GameRoot>/../../workshop/content/311210` by itself, so items in the game's own library need nothing.

### BlackOps3.exe (vanilla Steam + T7Patch)

```
BlackOps3.exe +set fs_game <workshopId|usermaps> +map zm_castle
```

There is no Lua or GSC hook in this mode, so loadouts aren't applied. If you enable it, NZW renames the intro and forest videos in `video/` to `*.nzwbak` and renames them back when the game exits, or the next time NZW starts if it crashed.

## Corrections to the original design notes

I read the boiii-free source while building this. It differs from the original spec in these places:

| Spec said | Source actually does |
| --- | --- |
| Custom scripts go in `<GameRoot>/data/scripts/zm` and `<GameRoot>/data/ui_scripts` | boiii loads them from `%LOCALAPPDATA%/boiii/data/...` and `<GameRoot>/boiii/{scripts,custom_scripts,ui_scripts}`. New scripts belong in `custom_scripts/`, because `scripts/` is for overriding stock scripts. |
| `-nointro` sets `com_introPlayed` | It only skips the logo video. |
| Workshop items need junctions into `usermaps/`/`mods/` | boiii reads Steam Workshop content directly when the game is in the same Steam library. Junctions are only a fallback. |
| Workshop items keep `workshop.json` under `zone/` | That is true only for local `usermaps/<name>/zone/` and `mods/<name>/zone/`. Steam Workshop items keep `workshop.json` at the root of `311210/<id>/`. |
| Classify maps by a `zm_` prefix | `workshop.json` has `"Type": "map" \| "mod"`, which is what boiii uses. The prefix is only a fallback. |

## Still needs testing in the game

These parts can't be tested without Windows and the game:

- **Auto-start timing.** If `map` fires too early on your machine, raise `nzw_autostart_delay` in Options → Extra arguments (`+set nzw_autostart_delay 3000`), or try the other map command in Options. Plain `map` from the title screen crashed in testing with a missing `zm_perks` HUD asset, so `devmap` is the default.
- **Mod plus custom map together** depends on the engine mounting `usermaps` alongside an active mod, as boiii's `CL_SetupForNewServerMap` hook does. The vanilla client mounts only one `fs_game`.
- **The GobbleGum pack override** replaces `self.bgb_pack` after spawn. It works if the map reads that array when a machine is used, which is how stock `_zm_bgb.gsc` behaves.
- **Display names in the weapon and gum lists** come from community naming. Every field is editable, so you can type any internal name.

## Probe mode

`python -m nzw --probe` starts boiii with `-unsafe-lua` and installs a script that writes `<GameRoot>/nzw_probe.txt`. The file contains the frontend's `CoD.LobbyButtons`, `LobbyData.UITargets`, the mode-related `Engine` functions, and a log of the session and lobby mode as you click into Zombies. Use it to find the stock calls that put the frontend into Zombies mode. Running `map` or `devmap` from the title screen crashes with a missing `zm_perks` HUD asset, because the session isn't in Zombies mode yet.

## Development

```sh
pip install -e .[test]
pytest
```

The core (`discovery`, `launch`, `gamefiles`, `settings`) doesn't depend on the UI and is covered by `tests/`. `gui.py` is a thin Tkinter layer on top.
