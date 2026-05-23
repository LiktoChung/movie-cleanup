from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.scanner import LibraryItem
from src.tmdb_client import MovieInfo

_INVALID_WIN_CHARS = re.compile(r'[<>:"/\\|?*]')
_TRAILING_DOTS = re.compile(r"[\s.]+$")


@dataclass
class RenameResult:
    renamed: bool
    old_path: str | None = None
    new_path: str | None = None
    old_name: str | None = None
    new_name: str | None = None
    error: str | None = None


def canonical_folder_name(title: str, year: int | None) -> str:
    """Plex-style folder name: Title (Year)."""
    name = _INVALID_WIN_CHARS.sub("", title or "")
    name = re.sub(r"\s+", " ", name).strip()
    name = _TRAILING_DOTS.sub("", name)
    if year:
        name = f"{name} ({year})"
    return name or "Unknown"


def _unique_folder_path(parent: Path, name: str) -> Path:
    candidate = parent / name
    if not candidate.exists():
        return candidate
    for i in range(2, 100):
        alt = parent / f"{name} [{i}]"
        if not alt.exists():
            return alt
    raise ValueError(f"Could not find a free folder name for {name!r}")


def _rebase_path(path_str: str | None, old_root: Path, new_root: Path) -> str | None:
    if not path_str:
        return None
    try:
        rel = Path(path_str).relative_to(old_root)
        return str(new_root / rel)
    except ValueError:
        return path_str


def rename_item_folder(item: LibraryItem, movie: MovieInfo) -> RenameResult:
    """Rename a library folder to match the TMDB title (folders only)."""
    if item.item_type != "folder":
        return RenameResult(renamed=False)

    src = Path(item.path)
    if not src.is_dir():
        return RenameResult(
            renamed=False,
            error=f"Folder not found: {item.path}",
        )

    target_name = canonical_folder_name(movie.title, movie.year)
    if src.name.casefold() == target_name.casefold():
        return RenameResult(renamed=False)

    try:
        dest = _unique_folder_path(src.parent, target_name)
        src.rename(dest)
    except OSError as e:
        return RenameResult(renamed=False, error=str(e))

    old_path = item.path
    old_root = Path(old_path)
    new_path = str(dest)

    item.path = new_path
    item.raw_name = dest.name
    item.primary_video = _rebase_path(item.primary_video, old_root, dest)
    item.nfo_path = _rebase_path(item.nfo_path, old_root, dest)

    return RenameResult(
        renamed=True,
        old_path=old_path,
        new_path=new_path,
        old_name=old_root.name,
        new_name=dest.name,
    )
