"""Application configuration loaded from environment with sensible local defaults."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VOUT_DATA_DIR", BASE_DIR / "data"))
SENSITIVE_DIR = Path(os.environ.get("VOUT_SENSITIVE_DIR", BASE_DIR / "sensitive"))
PRESETS_DIR = BASE_DIR / "presets"
DB_PATH = Path(os.environ.get("VOUT_DB_PATH", DATA_DIR / "vout.db"))
DEFAULT_PRESET_PATH = PRESETS_DIR / "kosice-dh-2026-2030.json"
LOCAL_ROSTER_PATH = Path(os.environ.get("VOUT_ROSTER_PATH", SENSITIVE_DIR / "councilors.json"))
ADMIN_PIN = os.environ.get("VOUT_ADMIN_PIN", "1234")
HOST = os.environ.get("VOUT_HOST", "0.0.0.0")
PORT = int(os.environ.get("VOUT_PORT", "8000"))
DEFAULT_VOTE_DURATION_SEC = int(os.environ.get("VOUT_DEFAULT_DURATION", "15"))
