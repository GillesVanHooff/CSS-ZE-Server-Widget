"""System tray icon: player totals on the icon, one menu line per server."""

import ctypes
import gc
import os
import subprocess
import threading
import time
import winreg
from functools import lru_cache, partial

import pystray
from PIL import Image, ImageDraw, ImageFont
from pystray._util import win32  # private pystray API: keep pystray pinned in requirements.txt

import startup
from dialogs import MB_ICONERROR, ask_favourites, ask_server, confirm, message, read_clipboard
from maps import FAVOURITES_FILE, load_favourites, local_maps, save_favourites
from query import (CONFIG_DIR, SERVERS_FILE, address, bold_digits, format_status, load_servers, parse_address,
                   preferred_address, query_all, save_servers, totals)

REFRESH_SECONDS = 30
ICON_SIZE = 64  # Windows scales it down to 16-32 px in the tray

BLINK_SECONDS = 10  # how long the icon flashes when an event starts
BLINK_INTERVAL = 0.5

ONLINE_BG = (46, 125, 50)
EVENT_BG = (230, 81, 0)  # deep orange, so the white digits stay readable
OFFLINE_BG = (97, 97, 97)
TEXT = (255, 255, 255)


@lru_cache  # _draw_fitted tries many sizes on every redraw
def _font(size):
    try:
        return ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def _draw_fitted(draw, text, box_w, box_h, center):
    """Draw text as large as fits in a box_w x box_h box, centered on its actual ink at center."""
    size = int(box_h * 2)
    while size > 4:
        font = _font(size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        if right - left <= box_w and bottom - top <= box_h:
            break
        size -= 1
    cx, cy = center
    draw.text((cx - (left + right) / 2, cy - (top + bottom) / 2), text, font=font, fill=TEXT)


def make_icon(players=None, event=False):
    """Total player count on a colored square (orange during an event); a dash when everything is offline."""
    online = players is not None
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, ICON_SIZE - 1, ICON_SIZE - 1), radius=8,
                           fill=EVENT_BG if event else ONLINE_BG if online else OFFLINE_BG)
    _draw_fitted(draw, str(players) if online else "–", ICON_SIZE - 6, ICON_SIZE - 6, (ICON_SIZE / 2, ICON_SIZE / 2))
    return img


SUBTITLE_MIN_SIZE = 64  # below this "player count" is an unreadable smudge, so only "ZE" is drawn


def make_app_icon(size):
    """The app's own icon (.exe, dialogs): "ZE" over "player count", in the tray icon's green."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=max(size // 8, 2), fill=ONLINE_BG)
    pad = max(size // 12, 1)
    inner = size - 2 * pad
    if size < SUBTITLE_MIN_SIZE:
        _draw_fitted(draw, "ZE", inner, inner * 0.7, (size / 2, size / 2))
    else:
        _draw_fitted(draw, "ZE", inner, inner * 0.55, (size / 2, pad + inner * 0.36))
        _draw_fitted(draw, "player count", inner, inner * 0.14, (size / 2, pad + inner * 0.84))
    return img


APP_ID = "CSS-ZE-Widget"
NOTIFICATION_ICON_FILE = CONFIG_DIR / "notification-icon.png"


def _register_app_id():
    """Give notifications the widget's name and icon in their header. Without an app ID, Windows shows the
    program ("Python" or "CSS-ZE-Widget.exe") with an icon it keeps from the first notification, which comes
    out blank because the tray icon has been redrawn by then."""
    try:
        NOTIFICATION_ICON_FILE.parent.mkdir(parents=True, exist_ok=True)
        make_app_icon(256).save(NOTIFICATION_ICON_FILE)  # every start, so a deleted file comes back
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{APP_ID}") as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "CSS ZE Widget")
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(NOTIFICATION_ICON_FILE))
    except OSError:
        return  # notifications still work, with the plain header
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


NIN_BALLOONUSERCLICK = win32.WM_USER + 5  # Windows sends this when a notification from the icon is clicked
SPI_GETMESSAGEDURATION = 0x2016


def _toast_seconds():
    """How long a notification stays on screen: Windows' "Dismiss notifications after" setting (5 s by
    default), plus a second for it to slide in and out. Windows itself reports it gone right away."""
    seconds = ctypes.c_ulong(5)
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETMESSAGEDURATION, 0, ctypes.byref(seconds), 0)
    return seconds.value + 1


class _Icon(pystray.Icon):
    """Opens the menu on left click too; pystray only does that on right click.
    A click on a notification joins toast_address, or opens the menu when it's None."""

    toast_address = None

    def _on_notify(self, wparam, lparam):
        if lparam == NIN_BALLOONUSERCLICK and self.toast_address:
            _connect(self.toast_address)()
            return
        if lparam in (win32.WM_LBUTTONUP, NIN_BALLOONUSERCLICK):
            lparam = win32.WM_RBUTTONUP
        super()._on_notify(wparam, lparam)


def _connect(address):
    return lambda: os.startfile(f"steam://connect/{address}")


def _open_server_browser():
    os.startfile("steam://open/servers")


def _open_servers_file():
    # Notepad rather than os.startfile: a fresh Windows has no app set for .json files.
    subprocess.Popen(["notepad.exe", str(SERVERS_FILE)])


def _mtime(path=SERVERS_FILE):
    try:
        return path.stat().st_mtime_ns
    except OSError:  # missing; load_servers recreates servers.json, favourites.json is optional
        return None


class TrayApp:
    def __init__(self, servers):
        self.servers = servers
        self.statuses = None  # None until the first refresh finishes
        self._shown = (None, False)  # make_icon args now on the icon: (players or None, event)
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._servers_lock = threading.Lock()  # add and remove each read, change and save the list
        self._dialog_open = threading.Lock()  # one dialog at a time
        self._show_lock = threading.Lock()
        self._servers_mtime = _mtime()  # main.py just loaded the file
        self.favourite_maps, self.notify = frozenset(), True  # loaded by the first refresh
        self._favourites_mtime = -1  # no file has this, so the first refresh loads favourites.json
        self._favourites_lock = threading.Lock()
        self._last_maps = {}  # address -> map last seen there, to spot map changes
        self._renotify = False  # set by "Refresh now": notify about favourites that are already on, too
        self._toast_until = 0.0  # time.monotonic() when the last notification has left the screen
        _register_app_id()  # before the tray icon exists, so its notifications get the ID
        self.icon = _Icon(
            "css-ze-widget", make_icon(), "CSS ZE: checking servers…",
            menu=pystray.Menu(self._menu_items),
        )

    def _menu_items(self):
        # pystray calls this each time the menu is built, so it always shows fresh data.
        if self.statuses is None:
            yield pystray.MenuItem("Checking servers…", None, enabled=False)
        elif not self.statuses:
            yield pystray.MenuItem("No servers yet", None, enabled=False)
        else:
            preferred = preferred_address(self.servers)
            for s in sorted(self.statuses, key=lambda s: s["address"] != preferred):  # preferred first
                text = format_status(s, bold=True, favourite=self._is_favourite(s))
                yield pystray.MenuItem(f"★ {text}" if s["address"] == preferred else text,
                                       _connect(s["address"]), enabled=s["online"])
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Steam server browser", _open_server_browser)
        yield pystray.MenuItem("Add server…", self._dialog(self._ask_server))
        yield pystray.MenuItem("Add server from clipboard", self._dialog(self._add_from_clipboard))
        yield pystray.MenuItem("Remove server", pystray.Menu(self._remove_items), enabled=bool(self.servers))
        yield pystray.MenuItem("Preferred server", pystray.Menu(self._preferred_items), enabled=bool(self.servers))
        yield pystray.MenuItem("Favourite maps", pystray.Menu(self._favourite_items))
        yield pystray.MenuItem("Open servers.json", _open_servers_file)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Start with Windows", self._toggle_startup, checked=lambda _item: startup.is_enabled())
        yield pystray.MenuItem("Refresh now", self._refresh_now)
        yield pystray.MenuItem("Quit", self._quit)

    def _remove_items(self):
        for server in self.servers:
            yield pystray.MenuItem(self._label(server), self._dialog(partial(self._confirm_remove, server)))

    def _preferred_items(self):
        preferred = preferred_address(self.servers)
        for server in self.servers:
            addr = address(server)
            yield pystray.MenuItem(self._label(server), self._prefer_action(addr),
                                   checked=lambda _item, addr=addr: addr == preferred, radio=True)

    def _prefer_action(self, addr):
        # A factory, so each menu item keeps its own address (a lambda in the loop would see only the last one).
        return lambda: self._toggle_preferred(addr)

    def _toggle_preferred(self, addr):
        """Make addr the preferred server, or clear it if it already is."""
        try:
            with self._servers_lock:
                make_preferred = preferred_address(self.servers) != addr
                servers = [{k: v for k, v in s.items() if k != "preferred"} for s in self.servers]
                for s in servers:
                    if make_preferred and address(s) == addr:
                        s["preferred"] = True
                self._save(servers)
        except ValueError as e:
            self._dialog(partial(message, str(e), MB_ICONERROR))()
            return
        if self.statuses is not None:
            self._show(self.statuses)  # redraw the icon now instead of after the refresh

    def _favourite_items(self):
        yield pystray.MenuItem("Edit favourites…", self._dialog(self._edit_favourites))
        yield pystray.MenuItem("Notify when one is played", self._toggle_notify, checked=lambda _item: self.notify)

    def _toggle_notify(self):
        try:
            self._change_favourites(notify=not self.notify)
        except ValueError as e:
            self._dialog(partial(message, str(e), MB_ICONERROR))()

    def _edit_favourites(self):
        maps = local_maps()
        if not maps:
            message("Couldn't find the Counter-Strike: Source maps folder, so only your favourites "
                    "and the maps the servers are playing now are listed.")
        # The maps on the servers now too, so one you haven't downloaded yet can still be picked.
        playing = {s["map"].lower() for s in self.statuses or [] if s["online"]}
        ask_favourites(sorted(maps | playing | self.favourite_maps), self.favourite_maps,
                       lambda added, removed: self._change_favourites(added, removed),
                       icons=[make_app_icon(s) for s in (16, 32, 48)])

    def _change_favourites(self, added=(), removed=(), notify=None):
        """Apply changes to the favourites and save favourites.json. Raises ValueError if it can't be saved."""
        with self._favourites_lock:
            maps = (self.favourite_maps | set(added)) - set(removed)
            notify = self.notify if notify is None else notify
            try:
                save_favourites(maps, notify)
            except OSError as e:
                raise ValueError(f"Could not save favourites.json:\n\n{e}") from None
            self.favourite_maps, self.notify = maps, notify
            self._favourites_mtime = _mtime(FAVOURITES_FILE)  # our own save, nothing to reload
        self.icon.update_menu()  # the ♥ on the server lines

    def _is_favourite(self, status):
        return status["online"] and status["map"].lower() in self.favourite_maps

    def _label(self, server):
        """Name and address, using the name the server reports when servers.json has none."""
        addr = address(server)
        name = server.get("name") or next((s["name"] for s in self.statuses or [] if s["address"] == addr), addr)
        return addr if name == addr else f"{name} ({addr})"

    def _dialog(self, show):
        """A menu action that runs show() on its own thread, since dialogs block and the tray must keep running."""
        def action():
            if not self._dialog_open.acquire(blocking=False):
                return  # another dialog is already open

            def run():
                try:
                    show()
                finally:
                    # Tk objects must be freed on the thread that made them, so collect any leftovers here.
                    gc.collect()
                    self._dialog_open.release()

            threading.Thread(target=run, daemon=True).start()
        return action

    def _ask_server(self):
        try:  # prefill the address when the clipboard holds one
            initial = address(parse_address(read_clipboard()))
        except ValueError:
            initial = ""
        ask_server(lambda text, name: self._add(parse_address(text, name)), initial,
                   icons=[make_app_icon(s) for s in (16, 32, 48)])

    def _toggle_startup(self):
        try:
            startup.set_enabled(not startup.is_enabled())
        except OSError as e:
            self._dialog(partial(message, f"Could not change Start with Windows:\n\n{e}", MB_ICONERROR))()

    def _add_from_clipboard(self):
        try:
            server = parse_address(read_clipboard())
            self._add(server)
        except ValueError as e:
            message(f"Could not add a server from the clipboard.\n\n{e}", MB_ICONERROR)
        else:
            message(f"Added {address(server)}.")

    def _confirm_remove(self, server):
        if not confirm(f"Remove {self._label(server)} from the list?"):
            return
        try:
            with self._servers_lock:
                self._save([s for s in self.servers if address(s) != address(server)])
        except ValueError as e:
            message(str(e), MB_ICONERROR)
            return
        # Update the menu and icon now; the refresh _save started still has to wait for the queries.
        if self.statuses is not None:
            self._show([s for s in self.statuses if s["address"] != address(server)])

    def _add(self, server):
        """Add a server and save servers.json. Raises ValueError if it's already listed or can't be saved."""
        with self._servers_lock:
            if any(address(s) == address(server) for s in self.servers):
                raise ValueError(f"{address(server)} is already in the list.")
            self._save(self.servers + [server])

    def _save(self, servers):
        # Callers hold _servers_lock. A new list, not changed in place, so a refresh in progress isn't affected.
        try:
            save_servers(servers)
        except OSError as e:
            raise ValueError(f"Could not save servers.json:\n\n{e}") from None
        self.servers = servers
        self._servers_mtime = _mtime()  # our own save, nothing to reload
        self._wake.set()  # query the new list right away

    def _refresh_loop(self):
        while not self._stopping.is_set():
            # Clear before querying, so a "Refresh now" click during the query isn't lost.
            self._wake.clear()
            try:
                self._refresh()
            except Exception:
                # An uncaught error would end this thread and freeze the widget; retry next pass instead.
                self.icon.title = "CSS ZE: refresh failed, retrying"
            self._wake.wait(REFRESH_SECONDS)

    def _reload_if_edited(self):
        """Pick up changes made to servers.json by hand, e.g. after "Open servers.json"."""
        with self._servers_lock:
            mtime = _mtime()
            if mtime == self._servers_mtime:
                return
            self._servers_mtime = mtime
            try:
                self.servers = load_servers()
            except (OSError, ValueError) as e:
                # Keep the last good list. The mtime is already stored, so this shows once per save.
                text = f"servers.json has an error, so the widget keeps using the previous list:\n\n{e}"
                self._dialog(partial(message, text, MB_ICONERROR))()

    def _reload_favourites_if_edited(self):
        """Pick up changes made to favourites.json by hand."""
        with self._favourites_lock:
            mtime = _mtime(FAVOURITES_FILE)
            if mtime == self._favourites_mtime:
                return
            self._favourites_mtime = mtime
            try:
                self.favourite_maps, self.notify = load_favourites()
            except (OSError, ValueError) as e:
                text = f"favourites.json has an error, so the widget keeps using the previous favourites:\n\n{e}"
                self._dialog(partial(message, text, MB_ICONERROR))()

    def _refresh(self):
        self._reload_if_edited()
        self._reload_favourites_if_edited()
        statuses = query_all(self.servers)
        # A server removed while the queries ran must not come back from these results.
        listed = {address(s) for s in self.servers}
        statuses = [s for s in statuses if s["address"] in listed]
        self._show(statuses)
        self._notify_favourites(statuses)

    def _refresh_now(self):
        self._renotify = True
        self._wake.set()

    def _notify_favourites(self, statuses):
        """Show a notification when a server switches to a favourite map. The first refresh counts as a
        switch, so a favourite that's already on gets one too, and so does the refresh "Refresh now" starts."""
        # Read and reset here, on the refresh thread. A click after this line leaves it set for the
        # refresh its _wake.set() starts right after this one.
        renotify, self._renotify = self._renotify, False
        if time.monotonic() < self._toast_until:
            # The last one is still on screen. Windows would queue another behind it, so quick clicks on
            # "Refresh now" piled up. Map switches still notify.
            renotify = False
        found = []
        for s in statuses:
            if not s["online"]:
                continue  # keep its last map, so coming back on the same map stays quiet
            map_name = s["map"].lower()
            if (renotify or self._last_maps.get(s["address"]) != map_name) and map_name in self.favourite_maps:
                found.append(s)
            self._last_maps[s["address"]] = map_name
        if not found or not self.notify:
            return
        preferred = preferred_address(self.servers)
        found.sort(key=lambda s: s["address"] != preferred)
        if len(found) == 1:
            s = found[0]
            title = f"♥ {s['map']}"
            text = f"{s['name']} · {s['players']}/{s['max_players']} players\nClick to join."
            self.icon.toast_address = s["address"]
        else:
            title = "♥ Favourite maps are on"
            text = "\n".join(f"{s['map']} on {s['name']}" for s in found) + "\nClick to pick a server."
            self.icon.toast_address = None  # a click opens the menu instead
        # Windows' limits for the notification's title and text.
        self.icon.notify(text[:255], title[:63])
        self._toast_until = time.monotonic() + _toast_seconds()

    def _show(self, statuses):
        """Put statuses on the icon, tooltip and menu."""
        with self._show_lock:  # the refresh thread and a remove can both get here
            self.statuses = statuses
            players, capacity = totals(statuses)
            total = f"{bold_digits(f'{players}/{capacity}')} players" if capacity else "all servers offline"
            addr = preferred_address(self.servers)
            preferred = next((s for s in statuses if s["address"] == addr), None)
            if preferred:
                # The icon follows the preferred server; the tooltip adds the total when there's more than one.
                icon_players = preferred["players"] if preferred["online"] else None
                count = f"{preferred['players']}/{preferred['max_players']}"
                own = f"{bold_digits(count)} players" if preferred["online"] else "offline"
                # pystray raises on tooltips over 128 characters, so cut long server names short.
                title = f"{preferred['name'][:40]}: {own}"
                if len(statuses) > 1:
                    title += f"\nAll servers: {total}"
            else:
                icon_players = players if capacity else None
                title = f"CSS ZE: {total}"
            shown = (icon_players, any(s["event"] for s in statuses))
            if shown != self._shown:
                event_started = shown[1] and not self._shown[1]
                self.icon.icon = make_icon(*shown)
                self._shown = shown
                if event_started:
                    threading.Thread(target=self._blink, daemon=True).start()
            self.icon.title = title
            self.icon.update_menu()

    def _blink(self):
        # Own thread, so the flashing doesn't hold up refreshes. Reads self._shown on every frame,
        # so a refresh in between still shows the latest count.
        for frame in range(int(BLINK_SECONDS / BLINK_INTERVAL)):
            if self._stopping.wait(BLINK_INTERVAL):
                return
            players, event = self._shown
            if not event:  # the event ended mid-blink and _refresh already drew the normal icon
                return
            self.icon.icon = make_icon(players, event=frame % 2 == 1)
        self.icon.icon = make_icon(*self._shown)

    def _quit(self):
        self._stopping.set()
        self._wake.set()
        self.icon.stop()

    def _setup(self, icon):
        # Runs once the tray loop is up. Daemon thread, so Quit doesn't wait for the loop. Python
        # still lets queries in flight finish before the process exits (at most 2 x TIMEOUT).
        icon.visible = True
        threading.Thread(target=self._refresh_loop, daemon=True).start()

    def run(self):
        self.icon.run(setup=self._setup)
