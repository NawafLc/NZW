"""Locate the game install and enumerate maps/mods without starting the game.

Layouts handled (matching what boiii-free's workshop component reads):

* Steam Workshop:  <library>/steamapps/workshop/content/311210/<id>/workshop.json
  (zone files sit directly in the item folder)
* Local usermaps:  <GameRoot>/usermaps/<FolderName>/zone/workshop.json
* Local mods:      <GameRoot>/mods/<FolderName>/zone/workshop.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import APP_ID, OFFICIAL_MAPS

GAME_DIR_NAME = "Call of Duty Black Ops III"
PREVIEW_NAMES = ("previewimage.png", "preview.png", "previewimage.jpg", "preview.jpg")


@dataclass
class ContentItem:
    kind: str  # "map" or "mod"
    title: str
    folder_name: str  # engine-internal name (map name for maps)
    source: str  # "official", "workshop" or "local"
    path: Path | None = None  # folder containing the zone files
    publisher_id: str = ""
    description: str = ""
    preview: Path | None = None
    group: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def is_official(self) -> bool:
        return self.source == "official"

    @property
    def ugc_name(self) -> str:
        """Name the engine's mod loader identifies this item by."""
        if self.publisher_id.isdigit():
            return self.publisher_id
        return self.folder_name

    @property
    def key(self) -> str:
        return f"{self.source}:{self.kind}:{self.ugc_name}"


# --------------------------------------------------------------------------
# Steam / game root discovery
# --------------------------------------------------------------------------

def parse_vdf(text: str) -> dict:
    """Minimal parser for Valve's KeyValues text format (libraryfolders.vdf)."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack: list[dict] = [{}]
    pending_key: str | None = None
    for quoted, brace in tokens:
        if brace == "{":
            child: dict = {}
            stack[-1][pending_key if pending_key is not None else ""] = child
            stack.append(child)
            pending_key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            pending_key = None
        else:
            value = quoted.replace("\\\\", "\\")
            if pending_key is None:
                pending_key = value
            else:
                stack[-1][pending_key] = value
                pending_key = None
    return stack[0]


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            for hive, sub in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(hive, sub) as key:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(Path(winreg.QueryValueEx(key, name)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots.append(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam")
    else:
        home = Path.home()
        roots += [home / ".steam" / "steam", home / ".local" / "share" / "Steam"]
    seen, unique = set(), []
    for r in roots:
        k = str(r).lower()
        if k not in seen and r.exists():
            seen.add(k)
            unique.append(r)
    return unique


def steam_libraries(steam_roots: list[Path] | None = None) -> list[Path]:
    """Every Steam library folder (the directory that contains `steamapps`)."""
    libs: list[Path] = []
    for root in steam_roots if steam_roots is not None else _steam_roots():
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
            folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
            for entry in folders.values():
                p = entry.get("path") if isinstance(entry, dict) else entry
                if p and not str(p).isdigit():
                    libs.append(Path(p))
    seen, unique = set(), []
    for lib in libs:
        k = str(lib).lower()
        if k not in seen:
            seen.add(k)
            unique.append(lib)
    return unique


def find_game_root(libraries: list[Path] | None = None) -> Path | None:
    for lib in libraries if libraries is not None else steam_libraries():
        candidate = lib / "steamapps" / "common" / GAME_DIR_NAME
        if (candidate / "BlackOps3.exe").exists():
            return candidate
    return None


def workshop_dirs(game_root: Path | None, libraries: list[Path] | None = None) -> list[Path]:
    """Workshop content folders for app 311210, the game's own library first."""
    dirs: list[Path] = []
    if game_root is not None:
        # <lib>/steamapps/common/<game> -> <lib>/steamapps/workshop/content/311210
        dirs.append(game_root.parent.parent / "workshop" / "content" / APP_ID)
    for lib in libraries if libraries is not None else steam_libraries():
        dirs.append(lib / "steamapps" / "workshop" / "content" / APP_ID)
    seen, unique = set(), []
    for d in dirs:
        k = os.path.normcase(os.path.abspath(d))
        if k not in seen and d.is_dir():
            seen.add(k)
            unique.append(d)
    return unique


# --------------------------------------------------------------------------
# Content scanning
# --------------------------------------------------------------------------

def read_workshop_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def classify(data: dict, fallback_folder: str = "") -> str:
    t = str(data.get("Type", "")).strip().lower()
    if t in ("map", "mod"):
        return t
    folder = str(data.get("FolderName") or fallback_folder)
    return "map" if folder.lower().startswith("zm_") else "mod"


def _find_preview(folder: Path, data: dict) -> Path | None:
    for key in ("PreviewFile", "PreviewImage", "Thumbnail"):
        name = data.get(key)
        if isinstance(name, str) and name:
            p = Path(name)
            p = p if p.is_absolute() else folder / p.name
            if p.is_file():
                return p
    for name in PREVIEW_NAMES:
        for base in (folder, folder.parent):
            if (base / name).is_file():
                return base / name
    return None


def _item_from_json(data: dict, folder: Path, source: str, dir_name: str) -> ContentItem:
    folder_name = str(data.get("FolderName") or dir_name)
    publisher = str(data.get("PublisherID") or data.get("PublishedFileId") or "")
    if not publisher and source == "workshop" and dir_name.isdigit():
        publisher = dir_name
    return ContentItem(
        kind=classify(data, dir_name),
        title=str(data.get("Title") or folder_name),
        folder_name=folder_name,
        source=source,
        path=folder,
        publisher_id=publisher,
        description=str(data.get("Description") or ""),
        preview=_find_preview(folder, data),
    )


def scan_workshop(content_dir: Path) -> list[ContentItem]:
    items = []
    for entry in sorted(content_dir.iterdir()) if content_dir.is_dir() else []:
        if not entry.is_dir():
            continue
        data = read_workshop_json(entry / "workshop.json")
        if data is not None:
            items.append(_item_from_json(data, entry, "workshop", entry.name))
    return items


def scan_local(game_root: Path, sub: str) -> list[ContentItem]:
    """Scan <GameRoot>/usermaps or <GameRoot>/mods."""
    base = game_root / sub
    items = []
    for entry in sorted(base.iterdir()) if base.is_dir() else []:
        zone = entry / "zone"
        if not zone.is_dir():
            continue
        data = read_workshop_json(zone / "workshop.json")
        if data is None:
            # Hand-installed content without metadata: trust the folder.
            if not any(zone.glob("*.ff")):
                continue
            data = {"FolderName": entry.name, "Type": "map" if sub == "usermaps" else "mod"}
        item = _item_from_json(data, zone, "local", entry.name)
        # The folder it lives in decides how the engine treats it.
        item.kind = "map" if sub == "usermaps" else "mod"
        items.append(item)
    return items


def official_maps() -> list[ContentItem]:
    return [
        ContentItem(kind="map", title=title, folder_name=name, source="official", group=group)
        for name, title, group in OFFICIAL_MAPS
    ]


def scan_all(game_root: Path | None, libraries: list[Path] | None = None) -> tuple[list[ContentItem], list[ContentItem]]:
    """Return (maps, mods). Local copies win over Workshop items of the same name."""
    maps = official_maps()
    found: list[ContentItem] = []
    if game_root is not None:
        found += scan_local(game_root, "usermaps") + scan_local(game_root, "mods")
    for d in workshop_dirs(game_root, libraries):
        found += scan_workshop(d)

    seen: set[tuple[str, str]] = set()
    mods: list[ContentItem] = []
    for item in found:
        ident = (item.kind, item.folder_name.lower())
        if ident in seen:
            continue
        seen.add(ident)
        (maps if item.kind == "map" else mods).append(item)
    return maps, sorted(mods, key=lambda i: i.title.lower())
