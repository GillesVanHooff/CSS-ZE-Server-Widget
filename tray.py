"""System tray icon: player totals on the icon, one menu line per server."""

import gc
import os
import threading
from functools import lru_cache, partial

import pystray
from PIL import Image, ImageDraw, ImageFont
from pystray._util import win32  # private pystray API: keep pystray pinned in requirements.txt

from dialogs import MB_ICONERROR, ask_server, confirm, message, read_clipboard
from query import address, bold_digits, format_status, parse_address, query_all, save_servers, totals

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


def _draw_fitted(draw, text, max_size):
    """Draw text as large as fits in a max_size square, centered on its actual ink."""
    size = max_size * 2
    while size > 8:
        font = _font(size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        if right - left <= max_size and bottom - top <= max_size:
            break
        size -= 1
    draw.text((ICON_SIZE / 2 - (left + right) / 2, ICON_SIZE / 2 - (top + bottom) / 2),
              text, font=font, fill=TEXT)


def make_icon(players=None, event=False):
    """Total player count on a colored square (orange during an event); a dash when everything is offline."""
    online = players is not None
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, ICON_SIZE - 1, ICON_SIZE - 1), radius=8,
                           fill=EVENT_BG if event else ONLINE_BG if online else OFFLINE_BG)
    _draw_fitted(draw, str(players) if online else "–", ICON_SIZE - 6)
    return img


class _Icon(pystray.Icon):
    """Opens the menu on left click too; pystray only does that on right click."""

    def _on_notify(self, wparam, lparam):
        if lparam == win32.WM_LBUTTONUP:
            lparam = win32.WM_RBUTTONUP
        super()._on_notify(wparam, lparam)


def _connect(address):
    return lambda: os.startfile(f"steam://connect/{address}")


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
            for s in self.statuses:
                yield pystray.MenuItem(format_status(s, bold=True), _connect(s["address"]), enabled=s["online"])
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Add server…", self._dialog(self._ask_server))
        yield pystray.MenuItem("Add server from clipboard", self._dialog(self._add_from_clipboard))
        yield pystray.MenuItem("Remove server", pystray.Menu(self._remove_items), enabled=bool(self.servers))
        yield pystray.MenuItem("Refresh now", self._wake.set)
        yield pystray.MenuItem("Quit", self._quit)

    def _remove_items(self):
        for server in self.servers:
            yield pystray.MenuItem(self._label(server), self._dialog(partial(self._confirm_remove, server)))

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
        ask_server(lambda text, name: self._add(parse_address(text, name)), initial)

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

    def _refresh(self):
        statuses = query_all(self.servers)
        # A server removed while the queries ran must not come back from these results.
        listed = {address(s) for s in self.servers}
        self._show([s for s in statuses if s["address"] in listed])

    def _show(self, statuses):
        """Put statuses on the icon, tooltip and menu."""
        with self._show_lock:  # the refresh thread and a remove can both get here
            self.statuses = statuses
            players, capacity = totals(statuses)
            shown = (players if capacity else None, any(s["event"] for s in statuses))
            if shown != self._shown:
                event_started = shown[1] and not self._shown[1]
                self.icon.icon = make_icon(*shown)
                self._shown = shown
                if event_started:
                    threading.Thread(target=self._blink, daemon=True).start()
            self.icon.title = (f"CSS ZE: {bold_digits(f'{players}/{capacity}')} players" if capacity
                               else "CSS ZE: all servers offline")
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
