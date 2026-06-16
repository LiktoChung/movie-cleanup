from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.library_rename import RenameResult, _unique_folder_path, sanitize_folder_name
from src.parser import has_site_prefix, proposed_movie_folder_name
from src.scanner import find_folder_videos

_JUNK_TXT_RE = re.compile(
    r"torrent|downloaded\s+from|yify|rarbg|ettv|ettvhd|galaxy.?tv|1337x",
    re.I,
)


@dataclass
class FlattenResult:
    flattened: bool = False
    moved_files: list[str] | None = None
    removed_junk: list[str] | None = None
    error: str | None = None


@dataclass
class FixupResult:
    path: str
    flattened: bool = False
    renamed: bool = False
    new_path: str | None = None
    new_name: str | None = None
    flatten: FlattenResult | None = None
    rename: RenameResult | None = None
    error: str | None = None



def proposed_folder_name(
    raw_name: str,
    primary_video: Path | None = None,
    *,
    parsed_title: str | None = None,
    parsed_year: int | None = None,
) -> str | None:
    return proposed_movie_folder_name(
        raw_name,
        primary_video,
        parsed_title=parsed_title,
        parsed_year=parsed_year,
    )


def folder_fixup_issues(
    raw_name: str,
    *,
    video_subfolder: str | None = None,
    proposed_name: str | None = None,
) -> list[str]:
    issues: list[str] = []
    if video_subfolder:
        issues.append("nested_video")
    if proposed_name and raw_name.casefold() != proposed_name.casefold():
        if has_site_prefix(raw_name) or video_subfolder:
            issues.append("rename")
    return issues


def _is_junk_file(name: str) -> bool:
    lower = name.lower()
    if lower.endswith(".txt") and _JUNK_TXT_RE.search(name):
        return True
    if lower.endswith(".url") or lower.endswith(".html"):
        return True
    return False


def _remove_junk_files(folder: Path) -> list[str]:
    removed: list[str] = []
    try:
        for entry in folder.iterdir():
            if entry.is_file() and _is_junk_file(entry.name):
                try:
                    entry.unlink()
                    removed.append(entry.name)
                except OSError:
                    pass
    except OSError:
        pass
    return removed


def flatten_video_subfolder(folder: Path) -> FlattenResult:
    """Move movie files up from a single nested subfolder and remove junk."""
    videos, subfolder_name = find_folder_videos(folder)
    if not subfolder_name:
        return FlattenResult(error="No nested video subfolder to flatten")

    subfolder = folder / subfolder_name
    if not subfolder.is_dir():
        return FlattenResult(error=f"Subfolder not found: {subfolder_name}")

    moved: list[str] = []
    try:
        for entry in list(subfolder.iterdir()):
            dest = folder / entry.name
            if dest.exists():
                stem, suffix = entry.stem, entry.suffix
                n = 2
                while dest.exists():
                    dest = folder / f"{stem} ({n}){suffix}"
                    n += 1
            shutil.move(str(entry), str(dest))
            moved.append(str(dest))

        try:
            subfolder.rmdir()
        except OSError:
            shutil.rmtree(subfolder, ignore_errors=True)

        removed_junk = _remove_junk_files(folder)
        return FlattenResult(
            flattened=True,
            moved_files=moved,
            removed_junk=removed_junk,
        )
    except OSError as e:
        return FlattenResult(error=str(e))


def rename_library_folder(folder: Path, new_name: str) -> RenameResult:
    if folder.name.casefold() == new_name.casefold():
        return RenameResult(renamed=False)

    if not folder.is_dir():
        return RenameResult(renamed=False, error=f"Folder not found: {folder}")

    try:
        old_path = str(folder)
        old_name = folder.name
        dest = _unique_folder_path(folder.parent, new_name)
        folder.rename(dest)
        return RenameResult(
            renamed=True,
            old_path=old_path,
            new_path=str(dest),
            old_name=old_name,
            new_name=dest.name,
        )
    except OSError as e:
        return RenameResult(renamed=False, error=str(e))


def apply_folder_fixup(
    folder_path: str,
    *,
    flatten: bool = True,
    rename: bool = True,
    proposed_name: str | None = None,
) -> FixupResult:
    folder = Path(folder_path)
    result = FixupResult(path=folder_path)

    if flatten:
        flat = flatten_video_subfolder(folder)
        result.flatten = flat
        # Already flat (videos at top level) — skip, don't fail
        if flat.error and not flat.flattened:
            if flat.error == "No nested video subfolder to flatten":
                result.flatten = FlattenResult(flattened=False)
            else:
                result.error = flat.error
                return result
        else:
            result.flattened = flat.flattened

    if rename:
        target_name = proposed_name
        if not target_name:
            videos, _ = find_folder_videos(folder)
            primary = videos[0] if videos else None
            target_name = proposed_folder_name(folder.name, primary)
        if not target_name:
            result.error = "Could not determine a clean folder name"
            return result
        target_name = sanitize_folder_name(target_name)
        if not target_name:
            result.error = "Folder name is empty after cleanup"
            return result

        rename_result = rename_library_folder(folder, target_name)
        result.rename = rename_result
        if rename_result.error:
            result.error = rename_result.error
            return result
        result.renamed = rename_result.renamed
        if rename_result.new_path:
            result.new_path = rename_result.new_path
            result.new_name = rename_result.new_name

    return result
