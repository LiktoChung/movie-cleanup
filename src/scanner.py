from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.config import VIDEO_EXTENSIONS
from src.nfo import find_nfo_near_videos, parse_nfo
from src.parser import parse_name, proposed_movie_folder_name


@dataclass
class EmptyFolder:
    path: str
    name: str
    reason: str  # no_files | no_video
    file_count: int = 0
    files: list[str] | None = None


def empty_folder_to_dict(folder: EmptyFolder) -> dict:
    data = {
        "path": folder.path,
        "name": folder.name,
        "reason": folder.reason,
        "file_count": folder.file_count,
    }
    if folder.files:
        data["files"] = folder.files
    return data


def _list_folder_entries(path: Path) -> list[str]:
    names: list[str] = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return names
    for entry in entries:
        if entry.name in (".", ".."):
            continue
        names.append(f"{entry.name}/" if entry.is_dir() else entry.name)
    return names


def classify_empty_folder(path: Path) -> EmptyFolder:
    """Folder at library root with no video files."""
    try:
        entries = [e for e in path.iterdir() if e.name not in (".", "..")]
    except OSError:
        return EmptyFolder(
            path=str(path),
            name=path.name,
            reason="no_files",
            file_count=0,
            files=[],
        )

    if not entries:
        return EmptyFolder(
            path=str(path),
            name=path.name,
            reason="no_files",
            file_count=0,
            files=[],
        )

    return EmptyFolder(
        path=str(path),
        name=path.name,
        reason="no_video",
        file_count=len(entries),
        files=_list_folder_entries(path),
    )


@dataclass
class LibraryItem:
    path: str
    item_type: str  # "folder" | "file"
    raw_name: str
    size_bytes: int = 0
    video_count: int = 0
    primary_video: str | None = None
    multiple_videos_warning: bool = False
    parsed_title: str | None = None
    parsed_year: int | None = None
    quality_hint: str = ""
    nfo_path: str | None = None
    nfo_imdb_id: str | None = None
    nfo_tmdb_id: str | None = None
    nfo_title: str | None = None
    nfo_year: int | None = None
    # Resolved (filled later)
    tmdb_id: int | None = None
    imdb_id: str | None = None
    title: str | None = None
    year: int | None = None
    poster_url: str | None = None
    confidence: str = "low"  # high | medium | low
    unresolved_reason: str | None = None
    # Grouping helpers
    group_key: str | None = None
    suggested_keeper: bool = False
    keeper_score: int = 0
    video_subfolder: str | None = None
    proposed_folder_name: str | None = None


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def collect_videos(directory: Path) -> list[Path]:
    """Collect video files in directory (non-recursive for performance)."""
    videos: list[Path] = []
    try:
        for entry in directory.iterdir():
            if entry.is_file() and _is_video(entry):
                videos.append(entry)
    except OSError:
        pass
    return videos


def find_folder_videos(directory: Path) -> tuple[list[Path], str | None]:
    """
    Videos in folder root, or from a single immediate subfolder.
    Returns (videos, subfolder_name) when videos only live in one subdir.
    """
    videos = collect_videos(directory)
    if videos:
        return videos, None

    hits: list[tuple[Path, list[Path]]] = []
    try:
        for entry in directory.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            sub_videos = collect_videos(entry)
            if sub_videos:
                hits.append((entry, sub_videos))
    except OSError:
        return [], None

    if not hits:
        return [], None

    if len(hits) == 1:
        subdir, sub_videos = hits[0]
        return sub_videos, subdir.name

    def total_size(vids: list[Path]) -> int:
        size = 0
        for v in vids:
            try:
                size += v.stat().st_size
            except OSError:
                pass
        return size

    best_dir, best_videos = max(hits, key=lambda pair: total_size(pair[1]))
    return best_videos, best_dir.name


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _parse_item_name(raw_name: str, primary_video: Path | None) -> tuple[str | None, int | None, str]:
    parsed = parse_name(raw_name)
    if not parsed.title and primary_video:
        parsed = parse_name(primary_video.stem)
    return parsed.title, parsed.year, parsed.quality_hint


def scan_library(
    library_path: Path,
    quarantine_path: Path | None = None,
    *,
    show_progress: bool = True,
    reporter: object | None = None,
) -> tuple[list[LibraryItem], list[dict]]:
    """Scan library root: one item per movie folder or loose video file."""
    from src.progress import track

    items: list[LibraryItem] = []
    empty_folders: list[EmptyFolder] = []
    quarantine_resolved = quarantine_path.resolve() if quarantine_path else None

    try:
        entries = sorted(library_path.iterdir(), key=lambda p: p.name.lower())
    except OSError as e:
        raise RuntimeError(f"Cannot read library path {library_path}: {e}") from e

    # Filter entries we will process (for accurate progress total)
    candidates: list[Path] = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if quarantine_resolved:
            try:
                if entry.resolve() == quarantine_resolved:
                    continue
            except OSError:
                pass
        if entry.is_file() and _is_video(entry):
            candidates.append(entry)
        elif entry.is_dir():
            candidates.append(entry)

    if reporter is not None:
        reporter.set_phase("scanning", "Scanning library", len(candidates))

    for entry in track(
        candidates,
        total=len(candidates),
        desc="Scanning library",
        disable=not show_progress,
        unit="entry",
        reporter=reporter,
        get_message=lambda e: e.name,
    ):
        if entry.is_file() and _is_video(entry):
            items.append(_build_file_item(entry))
        elif entry.is_dir():
            item = _build_folder_item(entry)
            if item is not None:
                items.append(item)
            else:
                empty_folders.append(classify_empty_folder(entry))

    return items, [empty_folder_to_dict(f) for f in empty_folders]


def _build_file_item(path: Path) -> LibraryItem:
    size = 0
    try:
        size = path.stat().st_size
    except OSError:
        pass

    title, year, quality = _parse_item_name(path.name, path)
    return LibraryItem(
        path=str(path),
        item_type="file",
        raw_name=path.name,
        size_bytes=size,
        video_count=1,
        primary_video=str(path),
        parsed_title=title,
        parsed_year=year,
        quality_hint=quality,
    )


def _build_folder_item(path: Path) -> LibraryItem | None:
    videos, video_subfolder = find_folder_videos(path)
    if not videos:
        return None

    videos.sort(key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
    primary = videos[0]

    size = _dir_size(path)
    nfo_path = find_nfo_near_videos(path, videos)
    nfo_meta = parse_nfo(nfo_path) if nfo_path else None

    title, year, quality = _parse_item_name(path.name, primary)
    proposed = proposed_movie_folder_name(
        path.name,
        primary,
        parsed_title=title,
        parsed_year=year,
    )

    item = LibraryItem(
        path=str(path),
        item_type="folder",
        raw_name=path.name,
        size_bytes=size,
        video_count=len(videos),
        primary_video=str(primary),
        multiple_videos_warning=len(videos) >= 2,
        parsed_title=title,
        parsed_year=year,
        quality_hint=quality,
        video_subfolder=video_subfolder,
        proposed_folder_name=proposed,
    )

    if nfo_meta and nfo_path:
        item.nfo_path = str(nfo_path)
        item.nfo_imdb_id = nfo_meta.imdb_id
        item.nfo_tmdb_id = nfo_meta.tmdb_id
        item.nfo_title = nfo_meta.title
        item.nfo_year = nfo_meta.year

    return item


def item_to_dict(item: LibraryItem) -> dict:
    return {
        "path": item.path,
        "type": item.item_type,
        "raw_name": item.raw_name,
        "size_bytes": item.size_bytes,
        "video_count": item.video_count,
        "primary_video": item.primary_video,
        "multiple_videos_warning": item.multiple_videos_warning,
        "parsed_title": item.parsed_title,
        "parsed_year": item.parsed_year,
        "quality_hint": item.quality_hint,
        "nfo_path": item.nfo_path,
        "nfo_imdb_id": item.nfo_imdb_id,
        "nfo_tmdb_id": item.nfo_tmdb_id,
        "nfo_title": item.nfo_title,
        "nfo_year": item.nfo_year,
        "tmdb_id": item.tmdb_id,
        "imdb_id": item.imdb_id,
        "title": item.title,
        "year": item.year,
        "poster_url": item.poster_url,
        "confidence": item.confidence,
        "unresolved_reason": item.unresolved_reason,
        "group_key": item.group_key,
        "suggested_keeper": item.suggested_keeper,
        "keeper_score": item.keeper_score,
        "video_subfolder": item.video_subfolder,
        "proposed_folder_name": item.proposed_folder_name,
    }


def dict_to_item(data: dict) -> LibraryItem:
    return LibraryItem(
        path=data["path"],
        item_type=data["type"],
        raw_name=data["raw_name"],
        size_bytes=data.get("size_bytes", 0),
        video_count=data.get("video_count", 0),
        primary_video=data.get("primary_video"),
        multiple_videos_warning=data.get("multiple_videos_warning", False),
        parsed_title=data.get("parsed_title"),
        parsed_year=data.get("parsed_year"),
        quality_hint=data.get("quality_hint", ""),
        nfo_path=data.get("nfo_path"),
        nfo_imdb_id=data.get("nfo_imdb_id"),
        nfo_tmdb_id=data.get("nfo_tmdb_id"),
        nfo_title=data.get("nfo_title"),
        nfo_year=data.get("nfo_year"),
        tmdb_id=data.get("tmdb_id"),
        imdb_id=data.get("imdb_id"),
        title=data.get("title"),
        year=data.get("year"),
        poster_url=data.get("poster_url"),
        confidence=data.get("confidence", "low"),
        unresolved_reason=data.get("unresolved_reason"),
        group_key=data.get("group_key"),
        suggested_keeper=data.get("suggested_keeper", False),
        keeper_score=data.get("keeper_score", 0),
        video_subfolder=data.get("video_subfolder"),
        proposed_folder_name=data.get("proposed_folder_name"),
    )
