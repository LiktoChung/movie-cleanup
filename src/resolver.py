from __future__ import annotations

from src.parser import (
    clean_folder_title,
    collection_label,
    is_collection,
    is_short_title,
    is_sequel_title,
    is_tv_episode,
    normalize_title,
    search_title_variants,
    title_similarity,
)
from src.scanner import LibraryItem
from src.tmdb_client import MovieInfo, TmdbClient

_MIN_TITLE_SIMILARITY = 0.58
_MIN_TITLE_SIMILARITY_HIGH = 0.72
_MIN_SIMILARITY_YEAR_OFF_BY_ONE = 0.65
_MAX_SIMILARITY_SEQUEL_MISMATCH = 0.8


def resolve_items(
    items: list[LibraryItem],
    client: TmdbClient,
    *,
    show_progress: bool = True,
    reporter: object | None = None,
) -> None:
    from src.progress import track

    if reporter is not None:
        reporter.set_phase("tmdb", "TMDB lookup", len(items))

    for item in track(
        items,
        total=len(items),
        desc="TMDB lookup",
        disable=not show_progress,
        unit="movie",
        reporter=reporter,
        get_message=lambda i: i.raw_name,
    ):
        _resolve_item(item, client)


def _search_titles_for_item(item: LibraryItem) -> list[str]:
    return search_title_variants(item.raw_name, item.parsed_title)


def _resolve_item(item: LibraryItem, client: TmdbClient) -> None:
    if is_tv_episode(item.raw_name):
        item.group_key = f"path:{item.path}"
        item.title = clean_folder_title(item.raw_name) or item.raw_name
        item.confidence = "low"
        item.unresolved_reason = "TV episode (not a standalone movie in TMDB)"
        return

    coll_reason = collection_label(item.raw_name)
    if coll_reason or is_collection(item.raw_name, item.parsed_title):
        item.title = clean_folder_title(item.raw_name) or item.raw_name
        item.year = item.parsed_year
        item.confidence = "low"
        item.group_key = f"path:{item.path}"
        item.unresolved_reason = coll_reason or "Multi-movie pack"
        return

    movie: MovieInfo | None = None
    confidence = "low"

    if item.nfo_tmdb_id:
        movie = client.get_by_tmdb_id(int(item.nfo_tmdb_id))
        if movie:
            confidence = "high"

    if not movie and item.nfo_imdb_id:
        movie = client.find_by_imdb_id(item.nfo_imdb_id)
        if movie:
            confidence = "high"

    if not movie:
        year = item.nfo_year or item.parsed_year
        folder_clean = clean_folder_title(item.raw_name)
        folder_has_sequel = is_sequel_title(folder_clean)

        for query_title in _search_titles_for_item(item):
            if folder_has_sequel and not is_sequel_title(query_title):
                if is_short_title(query_title):
                    continue

            movie, confidence = _search_tmdb(client, query_title, year)
            if movie:
                break

    if movie:
        item.tmdb_id = movie.tmdb_id
        item.imdb_id = movie.imdb_id
        item.title = movie.title
        item.year = movie.year
        item.poster_url = movie.poster_url
        item.confidence = confidence
        item.group_key = f"tmdb:{movie.tmdb_id}"
    elif item.parsed_title or clean_folder_title(item.raw_name):
        item.title = clean_folder_title(item.raw_name) or item.parsed_title
        item.year = item.parsed_year
        norm = normalize_title(item.title or "")
        year_part = str(item.parsed_year) if item.parsed_year else "unknown"
        item.group_key = f"title:{norm}:{year_part}"
        item.confidence = "low"
        if item.size_bytes < 100 * 1024 * 1024:
            item.unresolved_reason = "Not matched on TMDB (file may be incomplete or mislabeled)"
        else:
            item.unresolved_reason = "Not matched on TMDB (may be TV, foreign title, or odd release name)"
    else:
        item.group_key = f"path:{item.path}"
        item.title = item.raw_name
        item.confidence = "low"
        item.unresolved_reason = "Could not parse a title from folder name"


def _search_tmdb(
    client: TmdbClient,
    query_title: str,
    year: int | None,
) -> tuple[MovieInfo | None, str]:
    """Search TMDB with year, then without (TMDB year filter hides ±1 releases)."""
    results = client.search_movie(query_title, year)
    movie, confidence = _pick_search_result(results, year, query_title)
    if movie:
        return movie, confidence

    if year is not None:
        results = client.search_movie(query_title, None)
        movie, confidence = _pick_search_result(results, year, query_title)
        if movie:
            return movie, confidence

    return None, "low"


def _year_matches(expected: int | None, candidate_year: int | None) -> bool:
    if expected is None:
        return True
    if candidate_year is None:
        return False
    if candidate_year == expected:
        return True
    return abs(candidate_year - expected) <= 1


def _sequel_mismatch(query_title: str, candidate_title: str) -> bool:
    q_seq = is_sequel_title(query_title)
    c_seq = is_sequel_title(candidate_title)
    if q_seq == c_seq:
        return False
    sim = title_similarity(query_title, candidate_title)
    return sim < _MAX_SIMILARITY_SEQUEL_MISMATCH or (c_seq and not q_seq and sim < 0.88)


def _pick_search_result(
    results: list[MovieInfo],
    expected_year: int | None,
    query_title: str,
) -> tuple[MovieInfo | None, str]:
    if not results:
        return None, "low"

    best: MovieInfo | None = None
    best_score = 0.0
    best_exact_year = False

    for candidate in results:
        if "making of" in (candidate.title or "").lower():
            continue

        sim = title_similarity(query_title, candidate.title)
        if sim < _MIN_TITLE_SIMILARITY:
            continue

        if _sequel_mismatch(query_title, candidate.title):
            continue

        if not _year_matches(expected_year, candidate.year):
            continue

        exact_year = (
            expected_year is not None
            and candidate.year is not None
            and candidate.year == expected_year
        )
        off_by_one = expected_year is not None and candidate.year is not None and not exact_year

        if off_by_one and sim < _MIN_SIMILARITY_YEAR_OFF_BY_ONE:
            continue

        score = sim
        if exact_year:
            score += 0.05

        if score > best_score or (score == best_score and exact_year and not best_exact_year):
            best_score = score
            best = candidate
            best_exact_year = exact_year

    if best is None:
        return None, "low"

    if best_exact_year and best_score >= _MIN_TITLE_SIMILARITY_HIGH:
        return best, "high"
    if best_score >= _MIN_TITLE_SIMILARITY:
        return best, "medium"

    return None, "low"
