from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SCAN_JSON = DATA_DIR / "scan.json"
SCAN_PROGRESS_JSON = DATA_DIR / "scan-progress.json"
CACHE_DB = DATA_DIR / "cache.db"
QUARANTINE_LOG = DATA_DIR / "quarantine-log.jsonl"

load_dotenv(PROJECT_ROOT / ".env")


def _path(key: str, default: str) -> Path:
    return Path(os.getenv(key, default))


def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default)


TMDB_API_KEY: str = _str("TMDB_API_KEY")
LIBRARY_PATH: Path = _path("LIBRARY_PATH", r"\\path\to\your\movie\library")
QUARANTINE_PATH: Path = _path("QUARANTINE_PATH", r"\\path\to\your\quarantine\directory")
PORT: int = int(_str("PORT", "8765"))

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".wmv", ".mov", ".ts", ".m2ts"}
