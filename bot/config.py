"""Loads config.toml and .env. Import `CONFIG`, `TOKEN`, `OWNER_ID` from here."""

import os
import tomllib
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _to_namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in value.items()})
    return value


def load_config(path: Path = ROOT / "config.toml") -> SimpleNamespace:
    with open(path, "rb") as f:
        return _to_namespace(tomllib.load(f))


CONFIG = load_config()


def apply_overrides(path: Path) -> None:
    """Overwrite CONFIG values in place from another TOML file (used by the tests to
    pin known settings). In place, because every module shares this CONFIG object."""
    with open(path, "rb") as f:
        for section, values in tomllib.load(f).items():
            target = getattr(CONFIG, section)
            for key, value in values.items():
                setattr(target, key, value)
TZ = ZoneInfo(CONFIG.server.timezone)
DB_PATH = ROOT / CONFIG.server.database_path

load_dotenv(ROOT / ".env")
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
_owner = os.getenv("OWNER_ID", "").strip()
OWNER_ID = int(_owner) if _owner.isdigit() else None
HEALTHCHECK_URL = os.getenv("HEALTHCHECK_URL", "").strip() or None
