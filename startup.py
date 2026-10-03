"""Start with Windows, through a value under the current user's Run key (no admin rights needed)."""

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "CSS-ZE-Widget"


def _command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # From source: pythonw.exe, so no console window opens at login.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{Path(__file__).with_name("main.py")}"'


def is_enabled():
    """True only if the Run value starts this copy, so a moved .exe shows as off and can be fixed by ticking it."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0] == _command()
    except OSError:  # no value yet
        return False


def set_enabled(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
