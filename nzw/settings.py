"""Launcher settings, persisted as JSON in the user's config directory."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .catalog import DEFAULT_BINDS


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "NZW"


@dataclass
class Loadout:
    weapon: str = ""
    weapon_upgraded: bool = False
    perks: list[str] = field(default_factory=list)
    points: int = 0
    bgb_pack: list[str] = field(default_factory=list)
    bgb_start: str = ""


@dataclass
class Settings:
    game_root: str = ""
    client: str = "boiii"  # "boiii" or "vanilla"
    boiii_exe: str = "boiii.exe"
    display: str = "borderless"  # "fullscreen", "windowed" or "borderless"
    skip_intro: bool = True
    skip_cinematics: bool = True
    unsafe_lua: bool = False
    map_command: str = "map"  # "map" or "devmap"
    autostart_delay_ms: int = 1000
    uncap_menu_fps: bool = False
    unlock_gobblegums: bool = False
    unlock_attachments: bool = False
    unlock_camos: bool = False
    write_binds: bool = True
    binds: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BINDS))
    hide_videos_vanilla: bool = True
    extra_args: str = ""
    last_map: str = ""
    last_mod: str = ""
    loadout: Loadout = field(default_factory=Loadout)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known and k != "loadout"}
        s = cls(**kwargs)
        lo = data.get("loadout")
        if isinstance(lo, dict):
            lo_known = {f.name for f in fields(Loadout)}
            s.loadout = Loadout(**{k: v for k, v in lo.items() if k in lo_known})
        return s

    def to_dict(self) -> dict:
        return asdict(self)


def settings_path() -> Path:
    return config_dir() / "settings.json"


def load(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        return Settings.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return Settings()


def save(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp, path)
