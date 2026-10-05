"""Query CS:S servers over Valve's A2S protocol and report their status."""

import ipaddress
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import a2s

TIMEOUT = 3.0

# Packaged: in %APPDATA%, which is always writable and stays put when the .exe is moved.
# From source: next to this file, so a development copy keeps its own list.
if getattr(sys, "frozen", False):
    CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "CSS-ZE-Widget"
else:
    CONFIG_DIR = Path(__file__).parent
SERVERS_FILE = CONFIG_DIR / "servers.json"

# Written to servers.json when it doesn't exist yet, e.g. the first time the .exe runs.
DEFAULT_SERVERS = [{"name": "UNLOZE ZE", "ip": "51.195.188.106", "port": 27015}]


def load_servers(path=SERVERS_FILE):
    """Read servers.json, creating it with the default servers if it's missing.
    Raises ValueError with a readable message if an entry is invalid."""
    if not path.exists():
        save_servers(DEFAULT_SERVERS, path)
    with open(path, encoding="utf-8") as f:
        servers = json.load(f)
    if not isinstance(servers, list):
        raise ValueError("servers.json must contain a list of servers")
    for n, server in enumerate(servers, 1):
        _validate(server, f"servers.json entry {n}")
    return servers


def _validate(server, where):
    # ip and port end up in a steam:// URL, so only accept a plain IPv4 address and a port number.
    if not isinstance(server, dict):
        raise ValueError(f"{where}: must be an object")
    ip = server.get("ip")
    try:
        ipaddress.IPv4Address(ip if isinstance(ip, str) else "")
    except ValueError:
        raise ValueError(f"{where}: ip {ip!r} is not an IPv4 address") from None
    port = server.get("port", 27015)
    if type(port) is not int or not 1 <= port <= 65535:  # type() check also rejects true/false
        raise ValueError(f"{where}: port {port!r} must be a number from 1 to 65535")
    name = server.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError(f"{where}: name {name!r} must be text")
    if not isinstance(server.get("preferred", False), bool):
        raise ValueError(f"{where}: preferred must be true or false")


def preferred_address(servers):
    """Address of the preferred server, or None. If a hand edit marks several, the first one wins."""
    return next((address(s) for s in servers if s.get("preferred")), None)


def save_servers(servers, path=SERVERS_FILE):
    """Write servers.json with one server per line, like the hand-written file."""
    lines = ["  { " + ", ".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in s.items()) + " }"
             for s in servers]
    write_file(path, "[\n" + ",\n".join(lines) + "\n]\n" if lines else "[]\n")


def write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)  # the AppData folder doesn't exist on first run
    # Write a temp file and swap it in, so a crash mid-write can't leave a broken file.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# The first IPv4 address in the text, with an optional :port.
ADDRESS_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?::(\d+))?(?!\d)")


def parse_address(text, name=None):
    """Make a server entry from pasted text: 1.2.3.4, 1.2.3.4:27016, "connect 1.2.3.4:27016",
    steam://connect/1.2.3.4:27016, and so on. Raises ValueError with a readable message."""
    match = ADDRESS_RE.search(text)
    if not match:
        raise ValueError("No IP address found. Expected something like 1.2.3.4:27015.")
    server = {"name": name} if name else {}
    server.update(ip=match[1], port=int(match[2] or 27015))
    _validate(server, "Address")
    return server


def address(server):
    return f"{server['ip']}:{server.get('port', 27015)}"


def _info_with_retry(address):
    # UDP queries get dropped now and then (~1 in 4 seen on UNLOZE), so one timeout
    # isn't enough to call a server offline.
    try:
        return a2s.info(address, timeout=TIMEOUT)
    except TimeoutError:
        return a2s.info(address, timeout=TIMEOUT)


def query_server(server):
    """Return a status dict for one server. Never raises: failures mean offline."""
    ip, port = server["ip"], server.get("port", 27015)
    status = {
        "name": server.get("name") or address(server),
        "address": address(server),
        "online": False,
        "map": None,
        "players": 0,
        "max_players": 0,
        "ping_ms": None,
        "event": False,
    }
    try:
        info = _info_with_retry((ip, port))
    except (OSError, a2s.BrokenMessageError):  # timeouts are OSError too
        return status

    status.update(
        online=True,
        map=info.map_name,
        players=info.player_count - info.bot_count,
        max_players=info.max_players,
        ping_ms=round(info.ping * 1000),
        # Checked on the live name, so it works even when servers.json overrides the name.
        event="EVENT" in info.server_name,
    )
    if not server.get("name"):
        status["name"] = info.server_name.strip(" |")
    return status


def query_all(servers):
    """Query all servers in parallel, so one timeout doesn't hold up the rest."""
    with ThreadPoolExecutor(max_workers=max(len(servers), 1)) as pool:
        return list(pool.map(query_server, servers))


def totals(statuses):
    """(players, capacity) summed over online servers."""
    online = [s for s in statuses if s["online"]]
    return sum(s["players"] for s in online), sum(s["max_players"] for s in online)


BOLD_DIGITS = str.maketrans("0123456789", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗")


def bold_digits(text):
    """Swap 0-9 for Unicode bold digits, since Windows menus can't bold part of a line."""
    return text.translate(BOLD_DIGITS)


def format_status(s, bold=False, favourite=False):
    if not s["online"]:
        return f"{s['name']} · offline"
    players = f"{s['players']}/{s['max_players']}"
    name = f"[EVENT] {s['name']}" if s["event"] else s["name"]
    map_name = f"♥ {s['map']}" if favourite else s["map"]
    return f"{name} · {map_name} · {bold_digits(players) if bold else players} · {s['ping_ms']} ms"


if __name__ == "__main__":
    for s in query_all(load_servers()):
        print(format_status(s))
