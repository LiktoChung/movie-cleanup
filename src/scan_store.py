from __future__ import annotations

import json
from pathlib import Path

from src.config import SCAN_JSON
from src.grouper import build_duplicate_groups
from src.scanner import dict_to_item


def _norm_path(path: str) -> str:
    return str(path).replace("/", "\\").lower()


def remove_items_from_scan(removed_paths: list[str]) -> bool:
    """Drop quarantined paths from scan.json and rebuild groups. Returns True if updated."""
    if not removed_paths or not SCAN_JSON.exists():
        return False

    removed = {_norm_path(p) for p in removed_paths}

    with open(SCAN_JSON, encoding="utf-8") as f:
        data = json.load(f)

    all_items = [
        i for i in data.get("all_items", []) if _norm_path(i["path"]) not in removed
    ]
    items = [dict_to_item(i) for i in all_items]
    report = build_duplicate_groups(items)
    report["scanned_at"] = data.get("scanned_at")
    report["library_path"] = data.get("library_path")

    SCAN_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(SCAN_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return True
