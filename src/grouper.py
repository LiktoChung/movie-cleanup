from __future__ import annotations

import re
from collections import defaultdict

from src.scanner import LibraryItem, item_to_dict
from src.folder_fixup import folder_fixup_issues


def _resolution_score(item: LibraryItem) -> int:
    hint = (item.quality_hint or item.raw_name).lower()
    if "2160p" in hint or "4k" in hint:
        return 400
    if "1080p" in hint:
        return 300
    if "720p" in hint:
        return 200
    if "480p" in hint:
        return 100
    return 150


def _keeper_score(item: LibraryItem) -> int:
    score = _resolution_score(item)
    score += min(item.size_bytes // (1024 * 1024 * 1024), 50)  # up to +50 for GB
    if item.item_type == "folder":
        score += 10
    if item.confidence == "high":
        score += 5
    return score


def assign_keeper_scores(items: list[LibraryItem]) -> None:
    for item in items:
        item.keeper_score = _keeper_score(item)


def build_folder_fixups(items: list[LibraryItem]) -> list[dict]:
    fixups: list[dict] = []
    for item in items:
        if item.item_type != "folder":
            continue
        issues = folder_fixup_issues(
            item.raw_name,
            video_subfolder=item.video_subfolder,
            proposed_name=item.proposed_folder_name,
        )
        if not issues:
            continue
        fixups.append(
            {
                "path": item.path,
                "name": item.raw_name,
                "issues": issues,
                "video_subfolder": item.video_subfolder,
                "proposed_folder_name": item.proposed_folder_name,
                "parsed_title": item.parsed_title,
                "parsed_year": item.parsed_year,
            }
        )
    fixups.sort(key=lambda f: (f.get("name") or "").lower())
    return fixups


def build_duplicate_groups(
    items: list[LibraryItem],
    *,
    empty_folders: list[dict] | None = None,
) -> dict:
    """Build scan output structure with duplicate groups and unresolved items."""
    empty_folders = empty_folders or []
    assign_keeper_scores(items)

    by_key: dict[str, list[LibraryItem]] = defaultdict(list)
    unresolved: list[LibraryItem] = []

    for item in items:
        if item.confidence == "low" or not item.tmdb_id:
            unresolved.append(item)
            continue
        key = item.group_key or f"tmdb:{item.tmdb_id}"
        by_key[key].append(item)

    duplicate_groups = []
    for key, group_items in by_key.items():
        if len(group_items) < 2:
            continue

        group_items.sort(key=lambda i: i.keeper_score, reverse=True)
        best = group_items[0]
        for i, item in enumerate(group_items):
            item.suggested_keeper = i == 0

        sample = group_items[0]
        duplicate_groups.append(
            {
                "group_key": key,
                "tmdb_id": sample.tmdb_id,
                "imdb_id": sample.imdb_id,
                "title": sample.title,
                "year": sample.year,
                "poster_url": sample.poster_url,
                "items": [item_to_dict(i) for i in group_items],
            }
        )

    duplicate_groups.sort(
        key=lambda g: (g.get("title") or "").lower(),
    )

    folder_fixups = build_folder_fixups(items)

    return {
        "summary": {
            "total_items": len(items),
            "duplicate_groups": len(duplicate_groups),
            "duplicate_items": sum(len(g["items"]) for g in duplicate_groups),
            "unresolved": len(unresolved),
            "empty_folders": len(empty_folders),
            "folder_fixups": len(folder_fixups),
        },
        "duplicate_groups": duplicate_groups,
        "unresolved": [item_to_dict(i) for i in unresolved],
        "empty_folders": empty_folders,
        "folder_fixups": folder_fixups,
        "all_items": [item_to_dict(i) for i in items],
    }
