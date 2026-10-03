"""Query CS:S servers over Valve's A2S protocol and report their status."""

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
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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
