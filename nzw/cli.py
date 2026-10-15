"""Command-line entry point. With no arguments it opens the GUI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import discovery, launch, settings as settings_mod


def _find(items: list[discovery.ContentItem], name: str) -> discovery.ContentItem | None:
    name_l = name.lower()
    for item in items:
        if name_l in (item.folder_name.lower(), item.publisher_id.lower(), item.title.lower()):
            return item
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nzw", description="Black Ops III Zombies launcher")
    p.add_argument("--game-root", help="override the detected game folder")
    p.add_argument("--list", action="store_true", help="list maps and mods, then exit")
    p.add_argument("--play", metavar="MAP", help="launch MAP (internal name, Workshop ID or title)")
    p.add_argument("--mod", help="gameplay mod to load with --play")
    p.add_argument("--client", choices=["boiii", "vanilla"])
    p.add_argument("--dry-run", action="store_true", help="print the command line without launching")
    args = p.parse_args(argv)

    s = settings_mod.load()
    if args.game_root:
        s.game_root = args.game_root
    if args.client:
        s.client = args.client
    if not s.game_root:
        found = discovery.find_game_root()
        if found:
            s.game_root = str(found)

    if not (args.list or args.play):
        from .gui import run

        return run(s)

    root = Path(s.game_root) if s.game_root else None
    maps, mods = discovery.scan_all(root)

    if args.list:
        print(f"Game folder: {root or '(not found)'}")
        print("\nMaps:")
        for m in maps:
            print(f"  {m.folder_name:28} {m.title}  [{m.source}{' ' + m.publisher_id if m.publisher_id else ''}]")
        print("\nMods:")
        for m in mods or []:
            print(f"  {m.ugc_name:28} {m.title}  [{m.source}]")
        if not mods:
            print("  (none)")
        return 0

    map_item = _find(maps, args.play)
    if map_item is None:
        print(f"Unknown map: {args.play}", file=sys.stderr)
        return 2
    mod_item = None
    if args.mod:
        mod_item = _find(mods, args.mod)
        if mod_item is None:
            print(f"Unknown mod: {args.mod}", file=sys.stderr)
            return 2

    try:
        plan = launch.build_plan(s, map_item, mod_item)
    except launch.LaunchError as e:
        print(e, file=sys.stderr)
        return 2
    print(plan.command_line)
    for note in plan.notes:
        print(f"note: {note}")
    if args.dry_run:
        return 0
    try:
        for line in launch.prepare(plan, s):
            print(line)
    except (launch.LaunchError, OSError) as e:
        print(e, file=sys.stderr)
        return 1
    proc = launch.start(plan)
    code = proc.wait()
    for line in launch.finish(plan):
        print(line)
    return code
