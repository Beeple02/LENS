"""Configuration loading and first-run setup for LENS."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

_DEFAULT_CONFIG = """\
[general]
currency = "EUR"
date_format = "%Y-%m-%d"
http_timeout = 10
cache_fundamentals_hours = 24

[watchlist]
default = "Main"

[portfolio]
default_account = "Main"

[display]
refresh_interval = 30
sparkline_days = 30
"""

_LENS_DIR = Path.home() / ".lens"
_CONFIG_PATH = _LENS_DIR / "config.toml"
_DB_PATH = _LENS_DIR / "lens.db"


def get_lens_dir() -> Path:
    return _LENS_DIR


def get_config_path() -> Path:
    return _CONFIG_PATH


def get_db_path() -> Path:
    return _DB_PATH


def ensure_dirs() -> None:
    """Create ~/.lens/ and default config on first run."""
    _LENS_DIR.mkdir(parents=True, exist_ok=True)
    if not _CONFIG_PATH.exists():
        _CONFIG_PATH.write_text(_DEFAULT_CONFIG)


def load_config() -> dict[str, Any]:
    """Load config from ~/.lens/config.toml, creating it if absent."""
    ensure_dirs()
    with open(_CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


class Config:
    """Thin wrapper around the TOML config dict."""

    def __init__(self) -> None:
        self._data = load_config()

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(key, default)
        return node

    @property
    def currency(self) -> str:
        return self.get("general", "currency", default="EUR")

    @property
    def date_format(self) -> str:
        return self.get("general", "date_format", default="%Y-%m-%d")

    @property
    def http_timeout(self) -> int:
        return self.get("general", "http_timeout", default=10)

    @property
    def cache_fundamentals_hours(self) -> int:
        return self.get("general", "cache_fundamentals_hours", default=24)

    @property
    def default_watchlist(self) -> str:
        return self.get("watchlist", "default", default="Main")

    @property
    def default_account(self) -> str:
        return self.get("portfolio", "default_account", default="Main")

    @property
    def refresh_interval(self) -> int:
        return self.get("display", "refresh_interval", default=30)

    @property
    def sparkline_days(self) -> int:
        return self.get("display", "sparkline_days", default=30)

    @property
    def db_path(self) -> Path:
        return get_db_path()
