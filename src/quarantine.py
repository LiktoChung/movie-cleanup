from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from src.config import QUARANTINE_LOG, QUARANTINE_PATH


def quarantine_paths(
    paths: list[str],
    quarantine_base: Path | None = None,
    note: str = "",
    tmdb_id: int | None = None,
) -> list[dict]:
    """
    Move paths to quarantine folder. Returns list of move records.
  """
    base = quarantine_base or QUARANTINE_PATH
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest_dir = base / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)

    QUARANTINE_LOG.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for src_str in paths:
        src = Path(src_str)
        if not src.exists():
            results.append(
                {
                    "source": src_str,
                    "success": False,
                    "error": "Path does not exist",
                }
            )
            continue

        dest = dest_dir / src.name
        if dest.exists():
            dest = dest_dir / f"{src.stem}_{datetime.now().strftime('%H%M%S')}{src.suffix}"

        try:
            shutil.move(str(src), str(dest))
            record = {
                "timestamp": datetime.now().isoformat(),
                "source": str(src),
                "destination": str(dest),
                "tmdb_id": tmdb_id,
                "note": note,
                "success": True,
            }
            with open(QUARANTINE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            results.append(record)
        except OSError as e:
            results.append(
                {
                    "source": src_str,
                    "success": False,
                    "error": str(e),
                }
            )

    return results
