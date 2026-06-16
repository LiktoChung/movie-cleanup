from __future__ import annotations

import json
import shutil
from pathlib import Path

from src.config import LIBRARY_PATH, SCAN_JSON
from src.scanner import find_folder_videos


def _norm_path(path: str) -> str:
    return str(path).replace("/", "\\").lower()


def _is_under_library(path: Path, library_root: Path) -> bool:
    try:
        path.resolve().relative_to(library_root.resolve())
        return True
    except (ValueError, OSError):
        return False


def remove_empty_folders(
    paths: list[str],
    *,
    allowed_paths: set[str],
    library_root: Path | None = None,
) -> list[dict]:
    """Delete folders that are still empty (no videos). Paths must be in allowed_paths."""
    root = library_root or LIBRARY_PATH
    results: list[dict] = []

    for src_str in paths:
        norm = _norm_path(src_str)
        if norm not in allowed_paths:
            results.append(
                {
                    "path": src_str,
                    "success": False,
                    "error": "Path is not in the scanned empty-folder list",
                }
            )
            continue

        src = Path(src_str)
        if not src.exists():
            results.append(
                {
                    "path": src_str,
                    "success": True,
                    "already_gone": True,
                }
            )
            continue

        if not src.is_dir():
            results.append(
                {
                    "path": src_str,
                    "success": False,
                    "error": "Not a directory",
                }
            )
            continue

        if not _is_under_library(src, root):
            results.append(
                {
                    "path": src_str,
                    "success": False,
                    "error": "Path is outside the library",
                }
            )
            continue

        if find_folder_videos(src)[0]:
            results.append(
                {
                    "path": src_str,
                    "success": False,
                    "error": "Folder now contains video files — skipped",
                }
            )
            continue

        try:
            shutil.rmtree(src)
            results.append({"path": src_str, "success": True})
        except OSError as e:
            results.append(
                {
                    "path": src_str,
                    "success": False,
                    "error": str(e),
                }
            )

    return results


def remove_empty_folders_from_scan(removed_paths: list[str]) -> bool:
    if not removed_paths or not SCAN_JSON.exists():
        return False

    removed = {_norm_path(p) for p in removed_paths}

    with open(SCAN_JSON, encoding="utf-8") as f:
        data = json.load(f)

    empty_folders = [
        f
        for f in data.get("empty_folders", [])
        if _norm_path(f["path"]) not in removed
    ]
    data["empty_folders"] = empty_folders
    summary = data.get("summary") or {}
    summary["empty_folders"] = len(empty_folders)
    data["summary"] = summary

    with open(SCAN_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return True
