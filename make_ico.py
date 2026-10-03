"""Write the .exe icon (make_app_icon in tray.py) as an .ico file. build.ps1 runs this.

Usage: python make_ico.py OUTPUT.ico
"""

import sys
from pathlib import Path

from tray import make_app_icon

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main(out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    images = [make_app_icon(s) for s in SIZES]
    # One hand-drawn image per size, so the small sizes aren't blurry shrinks of the 256 px one.
    images[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])


if __name__ == "__main__":
    main(sys.argv[1])
