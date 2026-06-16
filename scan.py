#!/usr/bin/env python3
"""Scan movie library, resolve via TMDB, write duplicate report to data/scan.json."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from src.config import DATA_DIR, LIBRARY_PATH, QUARANTINE_PATH, SCAN_JSON, TMDB_API_KEY
from src.grouper import build_duplicate_groups
from src.resolver import resolve_items
from src.scan_progress import ScanCancelled, ScanProgress, is_cancel_requested
from src.scanner import scan_library
from src.tmdb_client import TmdbClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan movie library for duplicates")
    parser.add_argument(
        "--path",
        type=Path,
        default=LIBRARY_PATH,
        help=f"Library path (default: {LIBRARY_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SCAN_JSON,
        help=f"Output JSON path (default: {SCAN_JSON})",
    )
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="Scan files only, skip TMDB resolution",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Disable terminal progress bars (web progress file is still updated)",
    )
    args = parser.parse_args()
    show_bars = not args.quiet
    started = time.monotonic()
    progress = ScanProgress(enabled=True)

    library_path = args.path
    if not library_path.exists():
        print(f"Error: library path does not exist: {library_path}", file=sys.stderr)
        progress.fail(f"Library path does not exist: {library_path}")
        return 1

    if not args.no_resolve and not TMDB_API_KEY:
        print(
            "Error: TMDB_API_KEY not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        progress.fail("TMDB_API_KEY not set")
        return 1

    progress.begin(str(library_path))
    try:
        print(f"Library: {library_path}", file=sys.stderr)
        items, empty_folders = scan_library(
            library_path,
            QUARANTINE_PATH,
            show_progress=show_bars,
            reporter=progress,
        )
        print(f"Found {len(items)} movie items (folders + loose files)", file=sys.stderr)
        if empty_folders:
            print(f"Found {len(empty_folders)} empty folder(s)", file=sys.stderr)

        if not args.no_resolve:
            print("Resolving metadata via TMDB (cached)...", file=sys.stderr)
            client = TmdbClient()
            try:
                resolve_items(
                    items,
                    client,
                    show_progress=show_bars,
                    reporter=progress,
                )
            finally:
                client.close()

        if is_cancel_requested():
            raise ScanCancelled()

        progress.set_phase("grouping", "Building duplicate groups")
        if show_bars:
            print("Building duplicate groups...", file=sys.stderr)
        report = build_duplicate_groups(items, empty_folders=empty_folders)
        report["scanned_at"] = datetime.now().isoformat()
        report["library_path"] = str(library_path)

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        elapsed = time.monotonic() - started
        s = report["summary"]
        progress.done(s)
        print(file=sys.stderr)
        print(f"Done in {elapsed:.1f}s", file=sys.stderr)
        print(f"Wrote: {args.output}")
        print(f"  Total items:       {s['total_items']}")
        print(f"  Duplicate groups:  {s['duplicate_groups']} ({s['duplicate_items']} items)")
        print(f"  Unresolved:        {s['unresolved']}")
        print(f"  Empty folders:     {s.get('empty_folders', 0)}")
        print()
        print("Run: python serve.py")
        return 0
    except ScanCancelled:
        progress.cancelled()
        print("Scan cancelled.", file=sys.stderr)
        return 130
    except Exception as e:
        progress.fail(str(e))
        print(f"Error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(1)
