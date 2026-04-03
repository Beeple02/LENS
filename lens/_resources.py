"""Resource path helper — works both in development and in PyInstaller bundles."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """
    Return the absolute path to a bundled resource.

    PyInstaller extracts files to sys._MEIPASS/_internal/.
    Our package files land at sys._MEIPASS/lens/<relative>.
    In development __file__ is lens/_resources.py, so parent is lens/.
    """
    if hasattr(sys, "_MEIPASS"):
        # Running from PyInstaller bundle: files are at _MEIPASS/lens/<relative>
        return Path(sys._MEIPASS) / "lens" / relative
    # Running from source: __file__ is lens/_resources.py, parent = lens/
    return Path(__file__).parent / relative
