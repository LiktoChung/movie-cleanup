from __future__ import annotations

import json
import re
from pathlib import Path

from src.config import SCAN_JSON
from src.grouper import build_duplicate_groups
from src.library_rename import rename_item_folder
from src.scanner import dict_to_item, item_to_dict
from src.scan_store import _norm_path
from src.tmdb_client import MovieInfo, TmdbClient


def find_existing_copies(
    scan_data: dict,
    tmdb_id: int,
    *,
    exclude_path: str | None = None,
) -> list[dict]:
    """Other library items already linked to this TMDB id."""
    exclude = _norm_path(exclude_path) if exclude_path else None
    copies: list[dict] = []
    for item in scan_data.get("all_items", []):
        if item.get("tmdb_id") != tmdb_id:
            continue
        if exclude and _norm_path(item["path"]) == exclude:
            continue
        copies.append(item)
    return copies


def duplicate_info_for_tmdb(
    scan_data: dict,
    tmdb_id: int,
    *,
    exclude_path: str | None = None,
) -> dict:
    copies = find_existing_copies(scan_data, tmdb_id, exclude_path=exclude_path)
    group_keys = {
        g.get("group_key")
        for g in scan_data.get("duplicate_groups", [])
        if g.get("tmdb_id") == tmdb_id
    }
    return {
        "is_duplicate": len(copies) >= 1,
        "existing_count": len(copies),
        "in_duplicate_group": bool(group_keys),
        "group_keys": sorted(group_keys),
        "copies": copies,
    }


def load_scan_data() -> dict:
    if not SCAN_JSON.exists():
        return {"all_items": [], "duplicate_groups": []}
    with open(SCAN_JSON, encoding="utf-8") as f:
        return json.load(f)


def _dedupe_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        q = q.strip()
        if len(q) < 2:
            continue
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out


def _typo_variants(title: str) -> list[str]:
    """Generic spelling variants for manual TMDB lookup."""
    variants: list[str] = []
    collapsed = re.sub(r"(.)\1+", r"\1", title, flags=re.I)
    if collapsed.lower() != title.lower():
        variants.append(collapsed)
    if re.search(r"ee", title, re.I):
        once = re.sub(r"ee", "e", title, count=1, flags=re.I)
        if once.lower() != title.lower():
            variants.append(once)
    # Extra vowel in long tokens (e.g. Emeregency -> Emergency)
    for word in title.split():
        if len(word) < 7:
            continue
        for i, ch in enumerate(word):
            if ch.lower() in "aeiou" and i > 0 and i < len(word) - 1:
                shortened = word[:i] + word[i + 1 :]
                if len(shortened) >= 4:
                    variant = title.replace(word, shortened, 1)
                    if variant.lower() != title.lower():
                        variants.append(variant)
                break
    return variants


def _queries_for_item(scan_data: dict, item_path: str) -> list[str]:
    from src.parser import search_title_variants

    target = _norm_path(item_path)
    for item in scan_data.get("all_items", []):
        if _norm_path(item["path"]) != target:
            continue
        raw = item.get("raw_name") or Path(item_path).name
        return search_title_variants(raw, item.get("parsed_title"))
    return []


def search_movies(
    client: TmdbClient,
    query: str,
    year: int | None,
    scan_data: dict,
    *,
    item_path: str | None = None,
    limit: int = 12,
) -> list[dict]:
    """Search TMDB with year fallback and title variants from the library item."""
    queries = _dedupe_queries([query])
    if item_path:
        queries = _dedupe_queries(queries + _queries_for_item(scan_data, item_path))
    expanded: list[str] = []
    for q in queries:
        expanded.append(q)
        expanded.extend(_typo_variants(q))
    queries = _dedupe_queries(expanded)

    seen_ids: set[int] = set()
    results: list[dict] = []

    for q in queries:
        year_attempts = [year, None] if year is not None else [None]
        found_for_query = False
        for y in year_attempts:
            for movie in client.search_movie(q, y):
                if movie.tmdb_id in seen_ids:
                    continue
                seen_ids.add(movie.tmdb_id)
                results.append(
                    movie_to_search_result(
                        movie, scan_data, exclude_path=item_path
                    )
                )
                found_for_query = True
                if len(results) >= limit:
                    return results
            if found_for_query:
                break
        if found_for_query and q.lower() == query.strip().lower():
            break

    return results


def movie_to_search_result(
    movie: MovieInfo,
    scan_data: dict,
    *,
    exclude_path: str | None = None,
) -> dict:
    dup = duplicate_info_for_tmdb(
        scan_data, movie.tmdb_id, exclude_path=exclude_path
    )
    return {
        "tmdb_id": movie.tmdb_id,
        "imdb_id": movie.imdb_id,
        "title": movie.title,
        "year": movie.year,
        "poster_url": movie.poster_url,
        "duplicate": dup,
    }


def apply_tmdb_match(item_path: str, tmdb_id: int, client: TmdbClient) -> dict:
    """Link an unresolved item to a TMDB movie and rebuild scan.json groups."""
    if not SCAN_JSON.exists():
        raise FileNotFoundError("No scan data")

    movie = client.get_by_tmdb_id(tmdb_id)
    if not movie:
        raise ValueError(f"TMDB movie {tmdb_id} not found")

    with open(SCAN_JSON, encoding="utf-8") as f:
        data = json.load(f)

    target_norm = _norm_path(item_path)
    items = [dict_to_item(i) for i in data.get("all_items", [])]
    found = None
    for item in items:
        if _norm_path(item.path) == target_norm:
            found = item
            break

    if not found:
        raise ValueError(f"Item not in scan: {item_path}")

    rename = rename_item_folder(found, movie)
    if rename.error:
        raise ValueError(f"Could not rename folder: {rename.error}")

    found.tmdb_id = movie.tmdb_id
    found.imdb_id = movie.imdb_id
    found.title = movie.title
    found.year = movie.year
    found.poster_url = movie.poster_url
    found.confidence = "high"
    found.group_key = f"tmdb:{movie.tmdb_id}"
    found.unresolved_reason = None

    report = build_duplicate_groups(
        items,
        empty_folders=data.get("empty_folders", []),
    )
    report["scanned_at"] = data.get("scanned_at")
    report["library_path"] = data.get("library_path")

    with open(SCAN_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    resolved_path = found.path
    dup = duplicate_info_for_tmdb(report, tmdb_id, exclude_path=resolved_path)
    group = next(
        (g for g in report.get("duplicate_groups", []) if g.get("tmdb_id") == tmdb_id),
        None,
    )
    return {
        "scan": report,
        "item": item_to_dict(found),
        "duplicate": dup,
        "duplicate_group": group,
        "rename": {
            "renamed": rename.renamed,
            "old_path": rename.old_path,
            "new_path": rename.new_path,
            "old_name": rename.old_name,
            "new_name": rename.new_name,
        },
    }
