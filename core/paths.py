import os
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_path, user_config_path, user_data_path


APP_NAME = "auditoria-zabbix"


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


@dataclass(frozen=True)
class AppPaths:
    """Writable per-user locations, kept separate from bundled resources."""

    config_dir: Path
    cache_dir: Path
    data_dir: Path

    @property
    def settings_file(self):
        return self.config_dir / "settings.json"

    @property
    def audit_cache_file(self):
        return self.cache_dir / "last_audit_cache.json"

    def ensure_config_dir(self):
        return self._ensure_private_dir(self.config_dir)

    def ensure_cache_dir(self):
        return self._ensure_private_dir(self.cache_dir)

    def ensure_data_dir(self):
        return self._ensure_private_dir(self.data_dir)

    @staticmethod
    def _ensure_private_dir(path):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
        return path


def get_app_paths():
    """Return platform-native writable paths without depending on the cwd."""
    return AppPaths(
        config_dir=Path(user_config_path(APP_NAME, appauthor=False)),
        cache_dir=Path(user_cache_path(APP_NAME, appauthor=False)),
        data_dir=Path(user_data_path(APP_NAME, appauthor=False)),
    )
