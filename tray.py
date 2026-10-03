"""System tray icon: player totals on the icon, one menu line per server."""

import os
import threading

import pystray
from PIL import Image, ImageDraw, ImageFont

from query import format_status, query_all, totals

REFRESH_SECONDS = 30
ICON_SIZE = 64  # Windows scales it down to 16-32 px in the tray

ONLINE_BG = (46, 125, 50)
OFFLINE_BG = (97, 97, 97)
TEXT = (255, 255, 255)


def _font(size):
    try:
        return ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def _draw_fitted(draw, text, center_y, max_width, max_height):
    """Draw text centered at center_y, as large as fits in the box."""
    size = max_height
    while size > 8:
        font = _font(size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        if right - left <= max_width:
            break
        size -= 2
    draw.text((ICON_SIZE / 2, center_y), text, font=font, fill=TEXT, anchor="mm")


def make_icon(players=None, capacity=None):
    """Players stacked over capacity like a fraction, e.g. 44 over 104."""
    online = capacity is not None and capacity > 0
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, ICON_SIZE - 1, ICON_SIZE - 1), radius=10,
                           fill=ONLINE_BG if online else OFFLINE_BG)
    width = ICON_SIZE - 6
    if online:
        half = ICON_SIZE // 2
        _draw_fitted(draw, str(players), half / 2 + 1, width, half - 2)
        draw.line((10, half, ICON_SIZE - 10, half), fill=TEXT, width=3)
        _draw_fitted(draw, str(capacity), half + half / 2 - 1, width, half - 2)
    else:
        _draw_fitted(draw, "–", ICON_SIZE / 2, width, ICON_SIZE - 10)
    return img


def _connect(address):
    return lambda: os.startfile(f"steam://connect/{address}")


class TrayApp:
    def __init__(self, servers):
        self.servers = servers
        self.statuses = None  # None until the first refresh finishes
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self.icon = pystray.Icon(
            "css-ze-widget", make_icon(), "CSS ZE: checking servers…",
            menu=pystray.Menu(self._menu_items),
        )

    def _menu_items(self):
        # pystray calls this each time the menu is built, so it always shows fresh data.
        if self.statuses is None:
            yield pystray.MenuItem("Checking servers…", None, enabled=False)
        else:
            for s in self.statuses:
                yield pystray.MenuItem(format_status(s), _connect(s["address"]), enabled=s["online"])
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Refresh now", self._wake.set)
        yield pystray.MenuItem("Quit", self._quit)

    def _refresh_loop(self):
        while not self._stopping.is_set():
            self.statuses = query_all(self.servers)
            players, capacity = totals(self.statuses)
            self.icon.icon = make_icon(players, capacity)
            self.icon.title = f"CSS ZE: {players}/{capacity} players" if capacity else "CSS ZE: all servers offline"
            self.icon.update_menu()
            self._wake.wait(REFRESH_SECONDS)
            self._wake.clear()

    def _quit(self):
        self._stopping.set()
        self._wake.set()
        self.icon.stop()

    def _setup(self, icon):
        # Runs once the tray loop is up. Daemon thread, so a query in flight can't block Quit.
        icon.visible = True
        threading.Thread(target=self._refresh_loop, daemon=True).start()

    def run(self):
        self.icon.run(setup=self._setup)
