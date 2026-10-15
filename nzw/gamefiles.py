"""Everything the launcher writes into the game folder before a launch.

All changes are additive or reversible:
* scripts go into <GameRoot>/boiii/, which the Steam BlackOps3.exe never reads
* binds/config edits go into boiii_players/ (boiii) and only touch our keys
* Workshop junctions are links, never copies or moves
* hidden videos are renamed back when the game exits
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from importlib import resources
from pathlib import Path

from .catalog import APP_ID, SKIPPABLE_VIDEOS
from .discovery import ContentItem

VIDEO_SUFFIX = ".nzwbak"


# --------------------------------------------------------------------------
# In-game scripts (boiii only)
# --------------------------------------------------------------------------

SCRIPT_FILES = [
    "ui_scripts/nzw_autostart/__init__.lua",
    "custom_scripts/zm/nzw_loadout.gsc",
]


def install_scripts(game_root: Path) -> list[Path]:
    """Copy bundled scripts into <GameRoot>/boiii/. Returns files written."""
    written = []
    src_root = resources.files("nzw") / "game_scripts"
    for rel in SCRIPT_FILES:
        data = (src_root / rel).read_bytes()
        dest = game_root / "boiii" / rel
        if dest.is_file() and dest.read_bytes() == data:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written.append(dest)
    return written


# --------------------------------------------------------------------------
# Binds (boiii_players/user/binds.cfg, same format boiii's launcher writes)
# --------------------------------------------------------------------------

_BIND_RE = re.compile(r'^\s*bind\s+(\S+)\s+(.+?)\s*$', re.IGNORECASE)


def read_binds(path: Path) -> dict[str, str]:
    binds: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return binds
    for line in text.splitlines():
        m = _BIND_RE.match(line)
        if not m:
            continue
        cmd = m.group(2)
        if len(cmd) >= 2 and cmd[0] == '"' and cmd[-1] == '"':
            cmd = cmd[1:-1]
        binds[m.group(1).lower()] = cmd
    return binds


def valid_bind(key: str, command: str) -> bool:
    return (
        0 < len(key) <= 32
        and not any(c.isspace() or c in '";' for c in key)
        and 0 < len(command) <= 512
        and not any(c in command for c in '\r\n"')
    )


def write_binds(path: Path, new_binds: dict[str, str]) -> dict[str, str]:
    """Merge new_binds into the file, keeping the user's other binds."""
    binds = read_binds(path)
    for key, cmd in new_binds.items():
        if valid_bind(key, cmd):
            binds[key.lower()] = cmd
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f'bind {k} "{v}"\n' for k, v in binds.items()), encoding="utf-8")
    return binds


# --------------------------------------------------------------------------
# config.ini (key = "value" lines)
# --------------------------------------------------------------------------

def set_ini_value(path: Path, key: str, value: str) -> bool:
    """Set `key = "value"` in an existing config.ini. Returns True if changed."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False  # the game creates it on first run; don't invent one
    line = f'{key} = "{value}"'
    pattern = re.compile(rf'^{re.escape(key)}\s*=.*$', re.MULTILINE)
    if pattern.search(text):
        new = pattern.sub(lambda _: line, text, count=1)
    else:
        new = text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


# --------------------------------------------------------------------------
# Workshop junctions
# --------------------------------------------------------------------------

def engine_sees_workshop(game_root: Path, item: ContentItem) -> bool:
    """boiii scans <GameRoot>/../../workshop/content/311210 on its own."""
    if item.source != "workshop" or item.path is None:
        return True
    expected = game_root.parent.parent / "workshop" / "content" / APP_ID
    return os.path.normcase(os.path.abspath(item.path.parent)) == os.path.normcase(os.path.abspath(expected))


def junction_path(game_root: Path, item: ContentItem) -> Path:
    sub = "usermaps" if item.kind == "map" else "mods"
    return game_root / sub / item.folder_name / "zone"


def make_link(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        try:
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
            return
        except (ImportError, AttributeError, OSError):
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                check=True, capture_output=True,
            )
            return
    os.symlink(target, link, target_is_directory=True)


def ensure_junction(game_root: Path, item: ContentItem) -> Path | None:
    """Link a Workshop item into usermaps/ or mods/ when boiii can't find it."""
    if engine_sees_workshop(game_root, item):
        return None
    link = junction_path(game_root, item)
    if link.exists() or link.is_symlink():
        return None
    make_link(item.path, link)
    return link


# --------------------------------------------------------------------------
# Video hiding (vanilla client only; boiii skips videos in memory)
# --------------------------------------------------------------------------

def hide_videos(game_root: Path, names: list[str] = SKIPPABLE_VIDEOS) -> list[Path]:
    video_dir = game_root / "video"
    wanted = {n.lower() for n in names}
    hidden = []
    for f in video_dir.iterdir() if video_dir.is_dir() else []:
        if f.name.lower() in wanted and f.is_file():
            dest = f.with_name(f.name + VIDEO_SUFFIX)
            if dest.exists():
                continue
            f.rename(dest)
            hidden.append(dest)
    return hidden


def restore_videos(game_root: Path) -> list[Path]:
    """Undo hide_videos. Also cleans up after a launcher that crashed mid-session."""
    video_dir = game_root / "video"
    restored = []
    for f in video_dir.glob("*" + VIDEO_SUFFIX) if video_dir.is_dir() else []:
        original = f.with_name(f.name[: -len(VIDEO_SUFFIX)])
        if original.exists():
            continue
        f.rename(original)
        restored.append(original)
    return restored
