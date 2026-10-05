"""Favourite maps: the maps CS:S has downloaded, and favourites.json."""

import json
import re
import winreg
from pathlib import Path

from query import CONFIG_DIR, write_file

FAVOURITES_FILE = CONFIG_DIR / "favourites.json"

CSTRIKE = Path("steamapps", "common", "Counter-Strike Source", "cstrike")


def _steam_libraries():
    """Every Steam library folder: the Steam folder itself plus those in libraryfolders.vdf."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = Path(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:  # Steam isn't installed
        return []
    libraries = [steam]
    try:
        vdf = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries
    # Lines like: "path"		"D:\\Steam" (the backslashes are escaped)
    libraries += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf)]
    return libraries


def local_maps():
    """Names of the maps in every CS:S install, lowercase and without .bsp. Empty if none is found."""
    names = set()
    for library in _steam_libraries():
        cstrike = library / CSTRIKE
        # Maps from servers land in download\maps; custom\<addon>\maps holds hand-installed ones.
        for folder in [cstrike / "maps", cstrike / "download" / "maps", *cstrike.glob("custom/*/maps")]:
            names.update(bsp.stem.lower() for bsp in folder.glob("*.bsp"))
    return names


def load_favourites(path=FAVOURITES_FILE):
    """(maps, notify) from favourites.json. No file yet means no favourites, with notifications on.
    Raises ValueError with a readable message if the file is invalid."""
    if not path.exists():
        return frozenset(), True
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError('favourites.json must be an object like { "notify": true, "maps": [] }')
    maps, notify = data.get("maps", []), data.get("notify", True)
    if not isinstance(maps, list) or not all(isinstance(m, str) for m in maps):
        raise ValueError("favourites.json: maps must be a list of map names")
    if not isinstance(notify, bool):
        raise ValueError("favourites.json: notify must be true or false")
    # Lowercase, since Windows file names (and so map names) ignore case.
    return frozenset(m.strip().lower() for m in maps if m.strip()), notify


def save_favourites(maps, notify, path=FAVOURITES_FILE):
    write_file(path, json.dumps({"notify": notify, "maps": sorted(maps)}, indent=2, ensure_ascii=False) + "\n")
