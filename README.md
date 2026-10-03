# CSS ZE Server Widget

A lightweight Windows system tray widget for CSS: ZE servers.

- The tray menu lists each server with its name, map, player count and ping.
- Click a server to join it. CSS launches through Steam if it isn't already running.
- Servers that are down stay in the list as offline and come back on their own.
- When an event starts, the icon flashes. It stays orange while the event is on.

<p>
  <img src="screenshots/ZE_Player_Count_1.png" alt="Tray menu with a server's map, players and ping" width="355">
  &nbsp;
  <img src="screenshots/ZE_Player_Count_2.png" alt="Add server dialog" width="291">
  &nbsp;
  <img src="screenshots/ZE_Player_Count_3.png" alt="Tooltip showing players and capacity" width="152">
</p>

## Download

**[Download CSS-ZE-Widget.exe](https://github.com/GillesVanHooff/CSS-ZE-Server-Widget/releases/latest/download/CSS-ZE-Widget.exe)**
(latest release; older versions are on the [releases page](https://github.com/GillesVanHooff/CSS-ZE-Server-Widget/releases)).

Put it in any folder and run it. You need Windows 10/11 and Steam with Counter-Strike: Source. Python isn't needed.

The `.exe` isn't signed, so the first time Windows shows "Windows protected your PC". Click **More info**,
then **Run anyway**.

## Configuration

Add and remove servers from the tray menu:

- **Add server…** opens a small window for `IP:port` and an optional name. If the clipboard holds an
  address, the field is filled in already.
- **Add server from clipboard** adds the address you copied without opening a window. It accepts
  `1.2.3.4`, `1.2.3.4:27015`, `connect 1.2.3.4:27015` and `steam://connect/1.2.3.4:27015`.
- **Remove server** lists the servers. It asks before removing one.
- **Preferred server** picks one server for the icon. The icon then shows that server's players instead of
  the total, the server is listed first with a ★, and the tooltip shows both. Click it again to go back to
  the total.
- **Open servers.json** opens the list in Notepad. The widget picks up your changes on the next refresh,
  or right away with **Refresh now**.

The list is saved in `servers.json`:

- The `.exe` keeps it in `%APPDATA%\CSS-ZE-Widget\`, so it stays put when the `.exe` moves.
- Running from source, it's the one in the project folder.

If the file is missing, it's created with UNLOZE ZE. If a hand edit breaks it, the widget says so and keeps
the previous list. The optional `name` replaces the name the server reports, and `"preferred": true`
marks the preferred server.

```json
[
  { "name": "UNLOZE ZE", "ip": "51.195.188.106", "port": 27015, "preferred": true },
  { "ip": "1.2.3.4", "port": 27015 }
]
```

## How it works

The widget polls each server about every 30 seconds with Valve's A2S query protocol over UDP. Ping is
the measured round-trip time of the query. Clicking a server opens `steam://connect/IP:PORT`.
