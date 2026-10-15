import json
from pathlib import Path

import pytest

from nzw import cli, discovery, gamefiles, launch, settings as settings_mod
from nzw.settings import Settings


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def steam(tmp_path):
    """A Steam library with the game, two Workshop items and local content."""
    lib = tmp_path / "Steam"
    root = lib / "steamapps" / "common" / discovery.GAME_DIR_NAME
    root.mkdir(parents=True)
    (root / "BlackOps3.exe").write_bytes(b"")
    (root / "boiii.exe").write_bytes(b"")
    ws = lib / "steamapps" / "workshop" / "content" / "311210"
    write_json(ws / "111" / "workshop.json",
               {"Title": "Leviathan", "FolderName": "zm_leviathan", "PublisherID": "111", "Type": "map"})
    (ws / "111" / "previewimage.png").write_bytes(b"png")
    write_json(ws / "222" / "workshop.json",
               {"Title": "All-Around Enhancement", "FolderName": "aae", "PublisherID": "222", "Type": "mod"})
    write_json(root / "usermaps" / "zm_local" / "zone" / "workshop.json", {"Title": "Local Map", "FolderName": "zm_local"})
    (root / "mods" / "bare_mod" / "zone").mkdir(parents=True)
    (root / "mods" / "bare_mod" / "zone" / "mod.ff").write_bytes(b"")
    return lib, root


def test_parse_vdf_library_folders():
    text = '''"libraryfolders"
    {
        "0" { "path" "C:\\\\Program Files (x86)\\\\Steam" "apps" { "311210" "1" } }
        "1" { "path" "D:\\\\SteamLibrary" }
    }'''
    data = discovery.parse_vdf(text)
    assert data["libraryfolders"]["1"]["path"] == "D:\\SteamLibrary"
    assert data["libraryfolders"]["0"]["apps"]["311210"] == "1"


def test_find_root_and_scan(steam):
    lib, root = steam
    assert discovery.find_game_root([lib]) == root
    maps, mods = discovery.scan_all(root, [lib])
    by_name = {m.folder_name: m for m in maps}
    assert "zm_castle" in by_name and by_name["zm_castle"].is_official
    assert by_name["zm_leviathan"].publisher_id == "111"
    assert by_name["zm_leviathan"].preview.name == "previewimage.png"
    assert by_name["zm_local"].source == "local"
    assert {m.folder_name for m in mods} == {"aae", "bare_mod"}
    assert next(m for m in mods if m.folder_name == "aae").ugc_name == "222"


def test_classify_falls_back_to_prefix():
    assert discovery.classify({"FolderName": "zm_x"}) == "map"
    assert discovery.classify({"FolderName": "cool_mod"}) == "mod"
    assert discovery.classify({"FolderName": "zm_x", "Type": "mod"}) == "mod"


def _plan(root, map_name, mod_name=None, **overrides):
    maps, mods = discovery.scan_all(root, [])
    s = Settings(game_root=str(root), **overrides)
    m = next(i for i in maps if i.folder_name == map_name)
    mod = next(i for i in mods if i.folder_name == mod_name) if mod_name else None
    return s, launch.build_plan(s, m, mod)


def _dvars(args):
    return {args[i + 1]: args[i + 2] for i, a in enumerate(args) if a == "+set"}


def test_boiii_official_no_mod(steam):
    _, root = steam
    _, plan = _plan(root, "zm_castle")
    assert plan.args[:4] == ["-launch", "-nointro", "-nocinematics", "-borderless"]
    d = _dvars(plan.args)
    assert d["nzw_autostart"] == "1" and d["nzw_autostart_map"] == "zm_castle"
    assert "nzw_autostart_mod" not in d


def test_boiii_custom_map_mounts_usermaps(steam):
    _, root = steam
    _, plan = _plan(root, "zm_leviathan")
    assert _dvars(plan.args)["nzw_autostart_mod"] == "usermaps"


def test_boiii_mod_plus_custom_map(steam):
    _, root = steam
    _, plan = _plan(root, "zm_leviathan", "aae", unsafe_lua=True)
    d = _dvars(plan.args)
    assert d["nzw_autostart_mod"] == "222" and d["nzw_autostart_mod_alt"] == "aae"
    assert "-unsafe-lua" in plan.args


def test_loadout_dvars(steam):
    _, root = steam
    s = Settings(game_root=str(root))
    s.loadout.weapon = "ar_standard"
    s.loadout.weapon_upgraded = True
    s.loadout.perks = ["specialty_armorvest", "specialty_fastreload"]
    s.loadout.bgb_pack = ["a", "b", "c", "d", "e", "f"]
    s.unlock_gobblegums = True
    m = discovery.official_maps()[0]
    d = _dvars(launch.build_plan(s, m, None).args)
    assert d["nzw_weapon"] == "ar_standard" and d["nzw_weapon_upgraded"] == "1"
    assert d["nzw_perks"] == "specialty_armorvest,specialty_fastreload"
    assert d["nzw_bgb_pack"] == "a,b,c,d,e"
    assert d["cg_unlockall_gobblegums"] == "1"


def test_vanilla_command_line(steam):
    _, root = steam
    _, plan = _plan(root, "zm_leviathan", client="vanilla", map_command="devmap")
    assert plan.exe.name == "BlackOps3.exe"
    assert plan.args == ["+set", "fs_game", "usermaps", "+devmap", "zm_leviathan"]


def test_extra_args_are_appended(steam):
    _, root = steam
    _, plan = _plan(root, "zm_zod", extra_args='+set name "Dr Monty"')
    assert plan.args[-3:] == ["+set", "name", "Dr Monty"]


def test_prepare_boiii_installs_scripts_and_binds(steam):
    _, root = steam
    binds = root / "boiii_players" / "user" / "binds.cfg"
    binds.parent.mkdir(parents=True)
    binds.write_text('bind g "say hi"\n')
    (root / "boiii_players" / "config.ini").write_text('MaxFPS = "165"\nFOV = "90"\n')
    s, plan = _plan(root, "zm_leviathan", uncap_menu_fps=True)
    log = launch.prepare(plan, s)
    assert (root / "boiii" / "ui_scripts" / "nzw_autostart" / "__init__.lua").is_file()
    assert (root / "boiii" / "custom_scripts" / "zm" / "nzw_loadout.gsc").is_file()
    assert gamefiles.read_binds(binds) == {"g": "say hi", "f9": "fast_restart", "f10": "map_restart", "f11": "quit"}
    assert (root / "boiii_players" / "config.ini").read_text() == 'MaxFPS = "0"\nFOV = "90"\n'
    # Workshop item is in the game's own library, so boiii finds it without a link
    assert not any("linked" in line for line in log)
    # Second run is a no-op for scripts
    assert not any("installed" in line for line in launch.prepare(plan, s))


def test_junction_for_foreign_library(steam, tmp_path):
    _, root = steam
    other = tmp_path / "Other" / "steamapps" / "workshop" / "content" / "311210" / "333"
    write_json(other / "workshop.json", {"Title": "Far", "FolderName": "zm_far", "PublisherID": "333", "Type": "map"})
    item = discovery.scan_workshop(other.parent)[0]
    link = gamefiles.ensure_junction(root, item)
    assert link == root / "usermaps" / "zm_far" / "zone"
    assert (link / "workshop.json").is_file()
    assert gamefiles.ensure_junction(root, item) is None


def test_bind_validation():
    assert gamefiles.valid_bind("F9", "fast_restart")
    assert not gamefiles.valid_bind("F 9", "x")
    assert not gamefiles.valid_bind("F9", 'say "hi"')


def test_vanilla_hides_and_restores_videos(steam):
    _, root = steam
    video = root / "video"
    video.mkdir()
    (video / "BO3_Global_Logo_LogoSequence.mkv").write_bytes(b"v")
    (video / "zm_castle_load.mkv").write_bytes(b"v")
    s, plan = _plan(root, "zm_castle", client="vanilla")
    launch.prepare(plan, s)
    assert sorted(p.name for p in video.iterdir()) == ["BO3_Global_Logo_LogoSequence.mkv.nzwbak", "zm_castle_load.mkv"]
    launch.finish(plan)
    assert sorted(p.name for p in video.iterdir()) == ["BO3_Global_Logo_LogoSequence.mkv", "zm_castle_load.mkv"]


def test_missing_exe_is_reported(steam):
    _, root = steam
    (root / "boiii.exe").unlink()
    s, plan = _plan(root, "zm_castle")
    with pytest.raises(launch.LaunchError):
        launch.prepare(plan, s)


def test_settings_roundtrip(tmp_path):
    s = Settings(game_root="X", client="vanilla")
    s.loadout.perks = ["specialty_armorvest"]
    path = tmp_path / "s.json"
    settings_mod.save(s, path)
    loaded = settings_mod.load(path)
    assert loaded == s
    path.write_text('{"client": "boiii", "unknown_key": 1, "loadout": {"weapon": "ray_gun"}}')
    assert settings_mod.load(path).loadout.weapon == "ray_gun"


def test_cli_dry_run(steam, capsys, monkeypatch, tmp_path):
    lib, root = steam
    monkeypatch.setattr(settings_mod, "settings_path", lambda: tmp_path / "none.json")
    monkeypatch.setattr(discovery, "steam_libraries", lambda steam_roots=None: [lib])
    assert cli.main(["--game-root", str(root), "--play", "Leviathan", "--mod", "222", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "nzw_autostart_map zm_leviathan" in out and "nzw_autostart_mod 222" in out


def test_v1_settings_migrate_to_devmap(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"map_command": "map"}')
    assert settings_mod.load(path).map_command == "devmap"
    path.write_text('{"version": 2, "map_command": "map"}')
    assert settings_mod.load(path).map_command == "map"


def test_probe_command(steam):
    _, root = steam
    cmd = launch.probe_command(Settings(game_root=str(root)))
    assert "-unsafe-lua" in cmd and cmd[-3:] == ["+set", "nzw_probe", "1"]
    assert (root / "boiii" / "ui_scripts" / "nzw_probe" / "__init__.lua").is_file()
