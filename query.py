"""Query CS:S servers over Valve's A2S protocol and report their status."""

import ipaddress
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import a2s

TIMEOUT = 3.0

# servers.json sits next to the .exe when packaged, next to this file otherwise.
BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
SERVERS_FILE = BASE_DIR / "servers.json"


def load_servers(path=SERVERS_FILE):
    """Read servers.json. Raises ValueError with a readable message if an entry is invalid."""
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
        "name": server.get("name") or f"{ip}:{port}",
        "address": f"{ip}:{port}",
        "online": False,
        "map": None,
        "players": 0,
        "max_players": 0,
        "ping_ms": None,
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


def format_status(s):
    if not s["online"]:
        return f"{s['name']} · offline"
    return f"{s['name']} · {s['map']} · {s['players']}/{s['max_players']} · {s['ping_ms']} ms"


if __name__ == "__main__":
    for s in query_all(load_servers()):
        print(format_status(s))
