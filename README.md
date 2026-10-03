# CSS ZE Server Widget

A lightweight Windows system tray widget for CSS: ZE servers.

- The tray menu lists each server with its name, map, player count and ping.
- Click a server to join it. CSS launches through Steam if it isn't already running.
- Servers that are down stay in the list as offline and come back on their own.

> **Status:** early development. Nothing is implemented yet.

## Requirements

- Windows 10/11
- Python 3.12+ from [python.org](https://www.python.org/downloads/) (not the Microsoft Store placeholder)
- Steam with Counter-Strike: Source installed

## Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install python-a2s pystray Pillow
python main.py
```

## Configuration

List the servers in `servers.json`. The optional `name` replaces the name the server reports.

```json
[
  { "name": "UNLOZE ZE", "ip": "51.195.188.106", "port": 27015 }
]
```

## How it works

The widget polls each server about every 30 seconds with Valve's A2S query protocol over UDP. Ping is
the measured round-trip time of the query. Clicking a server opens `steam://connect/IP:PORT`.
