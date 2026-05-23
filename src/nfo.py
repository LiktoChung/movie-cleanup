from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NfoMetadata:
    path: Path | None = None
    imdb_id: str | None = None
    tmdb_id: str | None = None
    title: str | None = None
    year: int | None = None


def _normalize_imdb(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    match = re.search(r"(tt\d+)", value, re.I)
    return match.group(1).lower() if match else None


def _normalize_tmdb(value: str) -> str | None:
    value = value.strip()
    if value.isdigit():
        return value
    return None


def find_nfo(directory: Path) -> Path | None:
    """Find the best NFO file in a directory (movie.nfo preferred)."""
    if not directory.is_dir():
        return None
    preferred = ["movie.nfo", f"{directory.name}.nfo"]
    for name in preferred:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    for path in sorted(directory.glob("*.nfo")):
        if path.is_file():
            return path
    return None


def parse_nfo(path: Path) -> NfoMetadata:
    meta = NfoMetadata(path=path)
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except (ET.ParseError, OSError):
        return meta

    tag = root.tag.lower()
    if tag.endswith("movie") or tag == "movie":
        title_el = root.find("title")
        if title_el is not None and title_el.text:
            meta.title = title_el.text.strip()
        year_el = root.find("year")
        if year_el is not None and year_el.text and year_el.text.strip().isdigit():
            meta.year = int(year_el.text.strip())

    imdb_el = root.find("imdbid")
    if imdb_el is not None and imdb_el.text:
        meta.imdb_id = _normalize_imdb(imdb_el.text)

    for uid in root.findall("uniqueid"):
        uid_type = (uid.get("type") or uid.get("default") or "").lower()
        if uid.text is None:
            continue
        if "imdb" in uid_type and not meta.imdb_id:
            meta.imdb_id = _normalize_imdb(uid.text)
        elif "tmdb" in uid_type and not meta.tmdb_id:
            meta.tmdb_id = _normalize_tmdb(uid.text)

    return meta
