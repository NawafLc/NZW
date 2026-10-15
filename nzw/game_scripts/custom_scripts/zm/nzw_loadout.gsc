// NZW loadout (installed by the NZW launcher into <GameRoot>/boiii/custom_scripts/zm/).
//
// Reads dvars the launcher sets on the command line and applies them on the
// player's first spawn. Every dvar is optional; with none set this does nothing.
//
//   nzw_weapon           weapon name to give, e.g. "ar_standard"
//   nzw_weapon_upgraded  1 = give the Pack-a-Punched version
//   nzw_perks            comma list, e.g. "specialty_armorvest,specialty_fastreload"
//   nzw_points           extra starting points
//   nzw_bgb_pack         comma list of up to 5 gums offered by GobbleGum machines
//   nzw_bgb_start        gum to activate on spawn

#using scripts\codescripts\struct;
#using scripts\shared\array_shared;
#using scripts\zm\_zm_bgb;
#using scripts\zm\_zm_perks;
#using scripts\zm\_zm_score;
#using scripts\zm\_zm_weapons;

function autoexec nzw_loadout_init()
{
    level thread nzw_on_connect();
}

function nzw_on_connect()
{
    for (;;)
    {
        level waittill("connected", player);
        player thread nzw_apply_on_first_spawn();
    }
}

function nzw_apply_on_first_spawn()
{
    self endon("disconnect");
    self waittill("spawned_player");
    // Let the map hand out its default loadout before adding ours.
    wait 1;

    self nzw_give_weapon();
    self nzw_give_perks();
    self nzw_give_points();
    self nzw_set_bgb_pack();
    self nzw_give_bgb();
}

function nzw_split(value)
{
    result = [];
    if (!isdefined(value) || value == "")
    {
        return result;
    }
    foreach (token in strtok(value, ","))
    {
        if (token != "")
        {
            result[result.size] = token;
        }
    }
    return result;
}

function nzw_give_weapon()
{
    name = GetDvarString("nzw_weapon");
    if (name == "")
    {
        return;
    }
    weapon = GetWeapon(name);
    if (!isdefined(weapon) || weapon == level.weaponnone)
    {
        IPrintLn("^1NZW: unknown weapon " + name);
        return;
    }
    upgraded = GetDvarInt("nzw_weapon_upgraded") == 1;
    if (upgraded)
    {
        upgrade = zm_weapons::get_upgrade_weapon(weapon);
        if (isdefined(upgrade) && upgrade != level.weaponnone)
        {
            weapon = upgrade;
        }
    }
    self zm_weapons::weapon_give(weapon, upgraded);
}

function nzw_give_perks()
{
    foreach (perk in nzw_split(GetDvarString("nzw_perks")))
    {
        if (!isdefined(level._custom_perks) || !isdefined(level._custom_perks[perk]))
        {
            continue; // perk not on this map
        }
        if (!self HasPerk(perk))
        {
            self zm_perks::give_perk(perk, false);
        }
    }
}

function nzw_give_points()
{
    points = GetDvarInt("nzw_points");
    if (points > 0)
    {
        self zm_score::add_to_player_score(points);
    }
}

function nzw_set_bgb_pack()
{
    pack = [];
    foreach (gum in nzw_split(GetDvarString("nzw_bgb_pack")))
    {
        if (isdefined(level.bgb) && isdefined(level.bgb[gum]) && pack.size < 5)
        {
            pack[pack.size] = gum;
        }
    }
    if (pack.size > 0)
    {
        self.bgb_pack = pack;
        self.bgb_pack_randomized = [];
    }
}

function nzw_give_bgb()
{
    gum = GetDvarString("nzw_bgb_start");
    if (gum != "" && isdefined(level.bgb) && isdefined(level.bgb[gum]))
    {
        self bgb::give(gum);
    }
}
