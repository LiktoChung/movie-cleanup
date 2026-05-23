from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import DATA_DIR, SCAN_PROGRESS_JSON

SCAN_CANCEL_FLAG = DATA_DIR / ".scan-cancel"


class ScanCancelled(Exception):
    """Raised when the user cancels a scan from the web UI."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_progress(path: Path | None = None) -> dict[str, Any] | None:
    p = path or SCAN_PROGRESS_JSON
    if not p.exists():
        return None
    for _ in range(3):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            continue
        except OSError:
            return None
    return None


def request_cancel() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCAN_CANCEL_FLAG.touch()


def clear_cancel_request() -> None:
    try:
        SCAN_CANCEL_FLAG.unlink(missing_ok=True)
    except OSError:
        pass


def is_cancel_requested() -> bool:
    return SCAN_CANCEL_FLAG.exists()


class ScanProgress:
    """Write scan progress to JSON for the web UI (and optional CLI)."""

    def __init__(self, path: Path | None = None, *, enabled: bool = True) -> None:
        self.path = path or SCAN_PROGRESS_JSON
        self.enabled = enabled
        self.phase = "starting"
        self.label = "Starting"
        self.current = 0
        self.total = 0
        self.message: str | None = None
        self.running = False
        self.error: str | None = None
        self._started_at: str | None = None
        self._tick_counter = 0

    def _write(self, **extra: Any) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        total = self.total or 0
        current = self.current
        percent: float | None = None
        if total > 0:
            percent = round(min(100.0, current / total * 100), 1)

        payload: dict[str, Any] = {
            "running": self.running,
            "phase": self.phase,
            "label": self.label,
            "current": current,
            "total": total,
            "percent": percent,
            "message": self.message,
            "error": self.error,
            "updated_at": _now_iso(),
            **extra,
        }
        if "started_at" in extra:
            payload["started_at"] = extra["started_at"]
            self._started_at = extra["started_at"]
        elif self._started_at:
            payload["started_at"] = self._started_at
        elif self.running:
            self._started_at = _now_iso()
            payload["started_at"] = self._started_at

        tmp = self.path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def begin(self, library_path: str | None = None) -> None:
        clear_cancel_request()
        self.running = True
        self.phase = "starting"
        self.label = "Starting scan"
        self.current = 0
        self.total = 0
        self.message = library_path
        self.error = None
        self._started_at = _now_iso()
        self._write(started_at=self._started_at)

    def set_phase(self, phase: str, label: str, total: int | None = None) -> None:
        self.phase = phase
        self.label = label
        self.current = 0
        self.total = total or 0
        self.message = None
        self._tick_counter = 0
        self._write()

    def tick(self, current: int, total: int | None = None, message: str | None = None) -> None:
        self.current = current
        if total is not None:
            self.total = total
        if message is not None:
            self.message = message
        # Throttle disk writes (every item on large libraries is heavy on network shares)
        self._tick_counter += 1
        if self._tick_counter % 5 != 0 and current != self.total:
            return
        self._write()

    def done(self, summary: dict[str, Any] | None = None) -> None:
        self.running = False
        self.phase = "done"
        self.label = "Scan complete"
        self.current = self.total
        self.error = None
        if summary:
            self.message = (
                f"{summary.get('total_items', 0)} items, "
                f"{summary.get('duplicate_groups', 0)} duplicate groups"
            )
        self._write()

    def fail(self, error: str) -> None:
        self.running = False
        self.phase = "error"
        self.label = "Scan failed"
        self.error = error
        self._write()

    def cancelled(self) -> None:
        clear_cancel_request()
        self.running = False
        self.phase = "cancelled"
        self.label = "Scan cancelled"
        self.error = None
        self._write()
