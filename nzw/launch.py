"""Turn a (map, mod, settings) selection into a game process.

boiii.exe path (default):
    boiii.exe -launch -nointro -nocinematics -borderless
              +set nzw_autostart 1 +set nzw_autostart_map zm_castle
              +set nzw_autostart_mod <publisherId|usermaps> ...
    The bundled ui_script mounts the mod on the first frontend frame and then
    runs `map <name>`; this avoids `+map` firing before the frontend/LPC is up.

BlackOps3.exe path (vanilla Steam + T7Patch):
    BlackOps3.exe +set fs_game <publisherId|usermaps> +devmap <name>
    Videos are renamed for the session and restored when the game exits.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import gamefiles
from .discovery import ContentItem
from .settings import Settings


class LaunchError(Exception):
    pass


@dataclass
class LaunchPlan:
    exe: Path
    args: list[str]
    cwd: Path
    client: str
    map_item: ContentItem
    mod_item: ContentItem | None
    notes: list[str] = field(default_factory=list)

    @property
    def command_line(self) -> str:
        return subprocess.list2cmdline([str(self.exe), *self.args])


def required_mod(map_item: ContentItem, mod_item: ContentItem | None) -> str:
    """The UGC name that must be mounted: a gameplay mod, 'usermaps', or ''."""
    if mod_item is not None:
        return mod_item.ugc_name
    if not map_item.is_official:
        return "usermaps"
    return ""


def _set(name: str, value: object) -> list[str]:
    if isinstance(value, bool):
        value = int(value)
    return ["+set", name, str(value)]


def loadout_args(settings: Settings) -> list[str]:
    lo = settings.loadout
    args: list[str] = []
    if lo.weapon:
        args += _set("nzw_weapon", lo.weapon)
        if lo.weapon_upgraded:
            args += _set("nzw_weapon_upgraded", 1)
    if lo.perks:
        args += _set("nzw_perks", ",".join(lo.perks))
    if lo.points > 0:
        args += _set("nzw_points", lo.points)
    pack = [g for g in lo.bgb_pack if g][:5]
    if pack:
        args += _set("nzw_bgb_pack", ",".join(pack))
    if lo.bgb_start:
        args += _set("nzw_bgb_start", lo.bgb_start)
    if settings.unlock_gobblegums:
        args += _set("cg_unlockall_gobblegums", 1)
    if settings.unlock_attachments:
        args += _set("cg_unlockall_attachments", 1)
    if settings.unlock_camos:
        args += _set("cg_unlockall_camos_and_reticles", 1)
    return args


def build_plan(settings: Settings, map_item: ContentItem, mod_item: ContentItem | None) -> LaunchPlan:
    if map_item.kind != "map":
        raise LaunchError(f"{map_item.title} is not a map")
    if mod_item is not None and mod_item.kind != "mod":
        raise LaunchError(f"{mod_item.title} is not a mod")
    if not settings.game_root:
        raise LaunchError("Game folder is not set")
    root = Path(settings.game_root)
    mod = required_mod(map_item, mod_item)
    extra = shlex.split(settings.extra_args) if settings.extra_args.strip() else []
    notes: list[str] = []

    if settings.client == "boiii":
        exe = root / settings.boiii_exe
        args = ["-launch"]
        if settings.skip_intro:
            args.append("-nointro")
        if settings.skip_cinematics:
            args.append("-nocinematics")
        if settings.unsafe_lua:
            args.append("-unsafe-lua")
        if settings.display == "borderless":
            args.append("-borderless")
        elif settings.display == "windowed":
            args.append("-windowed")
        args += _set("nzw_autostart", 1)
        args += _set("nzw_autostart_tries", 0)
        args += _set("nzw_autostart_map", map_item.folder_name)
        args += _set("nzw_autostart_cmd", settings.map_command)
        args += _set("nzw_autostart_delay", settings.autostart_delay_ms)
        if mod:
            args += _set("nzw_autostart_mod", mod)
            if mod_item is not None and mod_item.folder_name != mod:
                args += _set("nzw_autostart_mod_alt", mod_item.folder_name)
        args += loadout_args(settings)
    elif settings.client == "vanilla":
        exe = root / "BlackOps3.exe"
        args = []
        if mod:
            args += _set("fs_game", mod)
        args += [f"+{settings.map_command}", map_item.folder_name]
        if any([settings.loadout.weapon, settings.loadout.perks, settings.loadout.bgb_pack,
                settings.loadout.bgb_start, settings.loadout.points]):
            notes.append("Loadout scripts need boiii; the vanilla client ignores them.")
        if mod_item is not None and not map_item.is_official:
            notes.append("Vanilla mounts a single fs_game; if the custom map is missing, launch it without the mod.")
    else:
        raise LaunchError(f"Unknown client '{settings.client}'")

    return LaunchPlan(exe=exe, args=args + extra, cwd=root, client=settings.client,
                      map_item=map_item, mod_item=mod_item, notes=notes)


def prepare(plan: LaunchPlan, settings: Settings) -> list[str]:
    """Write everything the plan depends on into the game folder. Returns a log."""
    root = plan.cwd
    log: list[str] = []
    if not plan.exe.is_file():
        raise LaunchError(f"{plan.exe.name} not found in {root}")

    if plan.client == "boiii":
        for path in gamefiles.install_scripts(root):
            log.append(f"installed {path.relative_to(root)}")
        for item in (plan.map_item, plan.mod_item):
            if item is not None and not item.is_official:
                link = gamefiles.ensure_junction(root, item)
                if link:
                    log.append(f"linked {link.relative_to(root)} -> {item.path}")
        if settings.write_binds and settings.binds:
            gamefiles.write_binds(root / "boiii_players" / "user" / "binds.cfg", settings.binds)
            log.append("updated boiii_players/user/binds.cfg")
        ini = root / "boiii_players" / "config.ini"
    else:
        if settings.hide_videos_vanilla:
            for path in gamefiles.hide_videos(root):
                log.append(f"hid video/{path.name}")
        ini = root / "players" / "config.ini"

    if settings.uncap_menu_fps and gamefiles.set_ini_value(ini, "MaxFPS", "0"):
        log.append(f"set MaxFPS=0 in {ini.relative_to(root)}")
    return log


def probe_command(settings: Settings) -> list[str]:
    """boiii command line that only dumps frontend lobby data (see nzw_probe Lua)."""
    if not settings.game_root:
        raise LaunchError("Game folder is not set")
    root = Path(settings.game_root)
    exe = root / settings.boiii_exe
    if not exe.is_file():
        raise LaunchError(f"{exe.name} not found in {root}")
    gamefiles.install_scripts(root)
    return [str(exe), "-launch", "-nointro", "-unsafe-lua", "-windowed", *_set("nzw_probe", 1)]


def start(plan: LaunchPlan) -> subprocess.Popen:
    kwargs = {}
    if hasattr(subprocess, "DETACHED_PROCESS"):
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen([str(plan.exe), *plan.args], cwd=plan.cwd, close_fds=True, **kwargs)


def finish(plan: LaunchPlan) -> list[str]:
    """Run after the game exits."""
    if plan.client == "vanilla":
        return [f"restored video/{p.name}" for p in gamefiles.restore_videos(plan.cwd)]
    return []
