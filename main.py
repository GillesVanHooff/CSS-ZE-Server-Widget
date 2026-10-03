import ctypes

from query import load_servers
from tray import TrayApp

APP_TITLE = "CSS ZE widget"
ERROR_ALREADY_EXISTS = 183
MB_ICONERROR = 0x10
MB_ICONINFORMATION = 0x40

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _message(text, flags):
    # The packaged .exe has no console, so anything the user must see goes in a message box.
    ctypes.windll.user32.MessageBoxW(None, text, APP_TITLE, flags)


def main():
    # Windows holds a named mutex until the process exits, so a second copy finds it and stops.
    _mutex = kernel32.CreateMutexW(None, False, "css-ze-widget")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _message("The widget is already running. Look for it in the system tray.", MB_ICONINFORMATION)
        return
    try:
        servers = load_servers()
    except (OSError, ValueError) as e:  # missing file, bad JSON, or an invalid entry
        _message(f"Could not load servers.json:\n\n{e}", MB_ICONERROR)
        return
    TrayApp(servers).run()


if __name__ == "__main__":
    main()
