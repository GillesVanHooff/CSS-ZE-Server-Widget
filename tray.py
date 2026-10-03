"""System tray icon: player totals on the icon, one menu line per server."""

import os
import threading
from functools import lru_cache

import pystray
from PIL import Image, ImageDraw, ImageFont
from pystray._util import win32  # private pystray API: keep pystray pinned in requirements.txt

from query import bold_digits, format_status, query_all, totals

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
        self.icon = _Icon(
            "css-ze-widget", make_icon(), "CSS ZE: checking servers…",
            menu=pystray.Menu(self._menu_items),
        )

    def _menu_items(self):
        # pystray calls this each time the menu is built, so it always shows fresh data.
        if self.statuses is None:
            yield pystray.MenuItem("Checking servers…", None, enabled=False)
        else:
            for s in self.statuses:
                yield pystray.MenuItem(format_status(s, bold=True), _connect(s["address"]), enabled=s["online"])
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Refresh now", self._wake.set)
        yield pystray.MenuItem("Quit", self._quit)

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
        self.statuses = query_all(self.servers)
        players, capacity = totals(self.statuses)
        shown = (players if capacity else None, any(s["event"] for s in self.statuses))
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
