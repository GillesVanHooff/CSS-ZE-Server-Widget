# CSS ZE Server Widget

A lightweight Windows system tray widget for CSS: ZE servers.

- The tray menu lists each server with its name, map, player count and ping.
- Click a server to join it. CSS launches through Steam if it isn't already running.
- Servers that are down stay in the list as offline and come back on their own.

> **Status:** the tray app works. Packaging as an `.exe` isn't done yet.

## Requirements

- Windows 10/11
- Python 3.12+ from [python.org](https://www.python.org/downloads/) (not the Microsoft Store placeholder)
- Steam with Counter-Strike: Source installed

## Setup

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

Click the tray icon (left or right) to open the menu. The icon shows the total number of players on the
online servers. Hover over it to see players and capacity, for example `44/104`.

To check the servers without the tray, run `.venv\Scripts\python.exe query.py`.

## Configuration

Add and remove servers from the tray menu:

- **Add server…** opens a small window for `IP:port` and an optional name. If the clipboard holds an
  address, the field is filled in already.
- **Add server from clipboard** adds the address you copied without opening a window. It accepts
  `1.2.3.4`, `1.2.3.4:27015`, `connect 1.2.3.4:27015` and `steam://connect/1.2.3.4:27015`.
- **Remove server** lists the servers. It asks before removing one.

These save to `servers.json`, so the folder it sits in must be writable. You can also edit the file by
hand. The optional `name` replaces the name the server reports.

```json
[
  { "name": "UNLOZE ZE", "ip": "51.195.188.106", "port": 27015 }
]
```

## How it works

The widget polls each server about every 30 seconds with Valve's A2S query protocol over UDP. Ping is
the measured round-trip time of the query. Clicking a server opens `steam://connect/IP:PORT`.
