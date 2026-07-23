import os
import sys


def resource_path(relative_path):
    """Resolve a path to a bundled resource (templates/, prompts/).

    Works both running from source (relative to the project root) and
    packaged as a PyInstaller executable, where data files are extracted
    under sys._MEIPASS (onefile) or live next to the executable (onedir).
    """
    base_path = getattr(sys, "_MEIPASS", None)
    if base_path is None:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)
