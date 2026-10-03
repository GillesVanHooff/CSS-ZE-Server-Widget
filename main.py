import ctypes

from dialogs import MB_ICONERROR, message
from query import load_servers
from tray import TrayApp

ERROR_ALREADY_EXISTS = 183

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def main():
    # The packaged .exe has no console, so anything the user must see goes in a message box.
    # Windows holds a named mutex until the process exits, so a second copy finds it and stops.
    _mutex = kernel32.CreateMutexW(None, False, "css-ze-widget")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        message("The widget is already running. Look for it in the system tray.")
        return
    try:
        servers = load_servers()
    except (OSError, ValueError) as e:  # missing file, bad JSON, or an invalid entry
        message(f"Could not load servers.json:\n\n{e}", MB_ICONERROR)
        return
    TrayApp(servers).run()


if __name__ == "__main__":
    main()
