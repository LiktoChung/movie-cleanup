from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from guessit import guessit

_SEQUEL_RE = re.compile(
    r"\b(part\s*\d+|part\s*(ii|iii|iv)|chapter\s*\d+|vol(?:ume)?\s*\d+|"
    r"ii|iii|iv|\d\.\d)\b",
    re.I,
)

_SITE_PREFIX_RE = re.compile(
    r"^www\.\S+?\s*[-–—]\s*",
    re.I,
)

_TRAILING_GROUP_RE = re.compile(
    r"[-\s]+(?:RARBG|ION10|ION15|NAISU|YIFY|YTS|TGx|GalaxyRG|CM|PSA|BONE|"
    r"RMTeam|Protozoan|Retr0|SM737|OFT|EVO|SPARKS|GECKOS|FGT|HighCode|"
    r"Hon3y|ExKinoRay|Twi7ter|DoVi|DDP|ATMOS|KINGDOM|KINGDOM_RG|EDGE2020|"
    r"edge2020|MSubs|Protozoan)(?:\b.*)?$",
    re.I,
)

# Trailing " - GROUP" scene tags
_TRAILING_DASH_GROUP_RE = re.compile(
    r"\s*-\s*(?:[A-Z][A-Z0-9_]{2,14}|MSubs)\s*$",
    re.I,
)

_TV_EPISODE_RE = re.compile(r"\bS\d{1,2}E\d{1,2}\b", re.I)

# Missing apostrophes in common contractions (release-folder spelling)
_CONTRACTION_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bdont\b", re.I), "don't"),
    (re.compile(r"\bwont\b", re.I), "won't"),
    (re.compile(r"\bcant\b", re.I), "can't"),
    (re.compile(r"\bisnt\b", re.I), "isn't"),
    (re.compile(r"\bwasnt\b", re.I), "wasn't"),
    (re.compile(r"\barent\b", re.I), "aren't"),
    (re.compile(r"\bwouldnt\b", re.I), "wouldn't"),
    (re.compile(r"\bcouldnt\b", re.I), "couldn't"),
    (re.compile(r"\bshouldnt\b", re.I), "shouldn't"),
]

# Sequel version when audio-channel cleanup turned "2.0" into "2 0"
_DECIMAL_SEQUEL_RE = re.compile(r"\b(\w+)\s+2\s+0\b", re.I)

_ROMAN_SEQUEL: dict[int, str] = {
    2: "II",
    3: "III",
    4: "IV",
    5: "V",
    6: "VI",
    7: "VII",
    8: "VIII",
    9: "IX",
    10: "X",
}


@dataclass
class ParsedName:
    title: str | None = None
    year: int | None = None
    screen_size: str | None = None
    source: str | None = None
    video_codec: str | None = None
    release_group: str | None = None
    edition: str | None = None
    other: list[str] | None = None

    @property
    def quality_hint(self) -> str:
        parts = []
        if self.screen_size:
            parts.append(str(self.screen_size))
        if self.source:
            parts.append(str(self.source))
        if self.video_codec:
            parts.append(str(self.video_codec))
        if self.edition:
            parts.append(str(self.edition))
        if self.other:
            parts.extend(str(o) for o in self.other if o)
        return " · ".join(parts) if parts else ""


def parse_name(name: str) -> ParsedName:
    """Parse a folder or file basename with guessit."""
    stem = re.sub(r"\.(mkv|mp4|avi|m4v|wmv|mov|ts|m2ts)$", "", name, flags=re.I)
    result = guessit(stem)

    title = result.get("title")
    if isinstance(title, list):
        title = title[0] if title else None
    if title is not None:
        title = str(title).strip()
        title = _strip_year_from_title(title)

    year = result.get("year")
    if isinstance(year, list):
        year = year[0] if year else None
    if year is not None:
        year = int(year)

    screen_size = result.get("screen_size")
    source = result.get("source")
    video_codec = result.get("video_codec")
    release_group = result.get("release_group")
    edition = result.get("edition")

    other_raw = result.get("other")
    other: list[str] | None = None
    if other_raw:
        other = [str(o) for o in (other_raw if isinstance(other_raw, list) else [other_raw])]

    return ParsedName(
        title=title,
        year=year,
        screen_size=str(screen_size) if screen_size else None,
        source=str(source) if source else None,
        video_codec=str(video_codec) if video_codec else None,
        release_group=str(release_group) if release_group else None,
        edition=str(edition) if edition else None,
        other=other,
    )


def _strip_year_from_title(title: str) -> str:
    return re.sub(r"\s+\b(19|20)\d{2}\b\s*$", "", title).strip()


def normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


_JUNK_TOKENS = re.compile(
    r"\b(1080p|720p|480p|2160p|4k|webrip|web-rip|web-rip|web-dl|web|bluray|blu-ray|brrip|"
    r"dvdrip|hdrip|hq|hdr|uhd|x264|x265|hevc|h\.?264|h\.?265|aac|dts|ac3|10bit|remux|"
    r"proper|repack|imax|extended|unrated|multi|dual[\s-]?audio|chi|eng|"
    r"rarbg|ion10|ion15|naisu|yts|yify|galaxy|psa|cm|bone|hdr|amzn|nf|bdrip|dvd|"
    r"atmos|ddp|msubs|readnfo|esub|line|remastered|ultimate|cut|"
    r"kingdom|edge2020|protozoan|rmteam|bone|subs|msubs|6ch|flux)\b",
    re.I,
)

# TV episode pattern — but S00E## rips of one-off films/specials are still movies
_TV_MOVIE_SPECIAL_HINT = re.compile(
    r"(opera|requiem|special|movie|concert|live)",
    re.I,
)


def is_sequel_title(title: str) -> bool:
    return bool(_SEQUEL_RE.search(title))


def is_tv_episode(raw_name: str) -> bool:
    if not _TV_EPISODE_RE.search(raw_name):
        return False
    # e.g. Metalocalypse S00E01 … Doomstar Requiem (feature-length special on TMDB)
    if _TV_MOVIE_SPECIAL_HINT.search(raw_name.replace(".", " ")):
        return False
    return True


def is_collection(raw_name: str, title: str | None = None) -> bool:
    combined = f"{raw_name} {title or ''}".lower()
    return bool(
        re.search(r"\b(trilogy|double feature|1 and 2|collection|pack)\b", combined, re.I)
        or re.search(r"\d{4}\s*,\s*\d{4}", raw_name)
    )


def _dots_to_spaces(stem: str) -> str:
    """Replace '.' with space but keep decimal sequel markers like 2.0."""
    protected = re.sub(r"(\d)\.(\d)", r"\1<DEC>\2", stem)
    protected = protected.replace("_", " ")
    protected = protected.replace(".", " ")
    return protected.replace("<DEC>", ".")


def _deleet_word(word: str) -> str:
    """0 -> o in mixed letter/digit tokens (e.g. Z00topia), not pure numbers or M3GAN-style."""
    if "0" not in word or not re.search(r"[A-Za-z]", word):
        return word
    if word.isdigit():
        return word
    # Keep tokens that use digits as intentional styling (e.g. M3GAN, Se7en)
    if re.search(r"[1-9]", word):
        return word
    return word.replace("0", "o")


def _apply_title_rewrites(title: str) -> str:
    title = _DECIMAL_SEQUEL_RE.sub(r"\1 2.0", title)
    for pattern, repl in _CONTRACTION_FIXES:
        title = pattern.sub(repl, title)
    return " ".join(_deleet_word(w) for w in title.split())


def _sequel_title_variants(title: str) -> list[str]:
    """Title 2 -> Title II, etc."""
    m = re.match(r"^(.+?)\s+(\d+)$", title.strip())
    if not m:
        return []
    n = int(m.group(2))
    roman = _ROMAN_SEQUEL.get(n)
    if not roman:
        return []
    base = m.group(1).strip()
    if not base:
        return []
    return [f"{base} {roman}"]


def _spacing_variants(title: str) -> list[str]:
    """NeZha -> Ne Zha when folder used CamelCase without spaces."""
    if " " in title:
        return []
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", title)
    if spaced == title:
        return []
    return [spaced]


def clean_folder_title(raw_name: str) -> str:
    """Derive a human title from folder/file name (before guessit truncation)."""
    stem = re.sub(r"\.(mkv|mp4|avi|m4v|wmv|mov|ts|m2ts)$", "", raw_name, flags=re.I)
    stem = _SITE_PREFIX_RE.sub("", stem)
    stem = re.sub(r"\[[^\]]+\]", " ", stem)
    stem = re.sub(r"\((\d{4})\)", " ", stem)
    stem = re.sub(r"\b(19|20)\d{2}\b", " ", stem)
    stem = re.sub(r"\bdd\d+\.\d+\b", " ", stem, flags=re.I)
    stem = re.sub(r"\bD\s*(?:BDRip|BDrip)\b", " ", stem, flags=re.I)
    stem = re.sub(r"\bA\.?\s*K\.?\s*A\.?\b", " ", stem, flags=re.I)
    stem = re.sub(r"\b\d\.\d\b", " ", stem)  # 5.1 / 7.1 audio
    stem = re.sub(r"\b\d{3,4}mb\b", " ", stem, flags=re.I)
    stem = _TRAILING_DASH_GROUP_RE.sub("", stem)
    stem = re.sub(r"-(?:RARBG|ION10|ION15|NAISU|GalaxyRG|YIFY|YTS|TGx|CM|PSA|BONE)\b", " ", stem, flags=re.I)
    stem = _dots_to_spaces(stem)
    stem = _JUNK_TOKENS.sub(" ", stem)
    stem = re.sub(r"\bdd\d+\b", " ", stem, flags=re.I)
    stem = _TRAILING_GROUP_RE.sub("", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" -")
    stem = _apply_title_rewrites(stem)
    return stem


def extra_search_titles(raw_name: str) -> list[str]:
    """Additional title variants for TMDB."""
    folder = clean_folder_title(raw_name)
    extras: list[str] = []
    if " - " in folder:
        head, tail = folder.split(" - ", 1)
        tail = tail.strip()
        if len(tail) > 3 and not re.match(r"^[A-Z0-9_]{3,14}$", tail):
            extras.append(tail)
            if head:
                extras.append(f"{head}: {tail}")
    # V+H+S style
    raw_stem = re.sub(r"\.(mkv|mp4|avi)$", "", raw_name, flags=re.I)
    if "+" in raw_stem and len(folder) <= 3:
        alt = re.sub(r"\+", " ", raw_stem)
        alt = re.sub(r"\(\d{4}\)", "", alt).strip()
        if alt:
            extras.append(alt)
            extras.append(alt.replace(" ", "/"))
    return extras


def search_title_variants(raw_name: str, parsed_title: str | None) -> list[str]:
    """All title strings to try on TMDB, best first."""
    variants: list[str] = []
    folder = clean_folder_title(raw_name)

    def add(t: str | None) -> None:
        if not t or not t.strip():
            return
        stripped = t.strip()
        if len(stripped) < 2 and not (len(stripped) == 1 and stripped.isalpha()):
            return
        t = _apply_title_rewrites(stripped)
        key = t.lower()
        if key not in {v.lower() for v in variants}:
            variants.append(t)

    add(folder)
    for extra in extra_search_titles(raw_name):
        add(extra)
    for variant in _sequel_title_variants(folder) + _spacing_variants(folder):
        add(variant)
    if parsed_title and len(parsed_title.strip()) <= 2:
        add(parsed_title.strip())

    if parsed_title:
        add(_strip_year_from_title(parsed_title))

    if parsed_title and len(parsed_title) <= 3 and folder:
        variants = [folder] + [v for v in variants if v != folder]

    return variants


def best_search_title(raw_name: str, parsed_title: str | None) -> str | None:
    variants = search_title_variants(raw_name, parsed_title)
    return variants[0] if variants else None


def title_similarity(a: str, b: str) -> float:
    """0-1 similarity between two titles (sequence + token overlap)."""
    na = normalize_title(a)
    nb = normalize_title(b)
    if not na or not nb:
        return 0.0

    sim = SequenceMatcher(None, na, nb).ratio()

    if na in nb or nb in na:
        sim = max(sim, 0.78)

    q_tokens = [t for t in na.split() if len(t) > 1]
    c_set = set(nb.split())
    if q_tokens:
        matched = sum(
            1
            for t in q_tokens
            if t in c_set or any(t in c or c in t for c in c_set if len(c) > 2)
        )
        token_ratio = matched / len(q_tokens)
        if token_ratio >= 0.66:
            sim = max(sim, 0.68 + token_ratio * 0.22)

    return sim


def is_short_title(title: str | None) -> bool:
    if not title:
        return True
    t = normalize_title(title)
    if len(t) == 1 and t.isalpha():
        return False
    return len(t) <= 3 or t in {"v", "oh", "dual"}


def collection_label(raw_name: str) -> str | None:
    """Human-readable reason when item is a multi-movie pack."""
    if re.search(r"\d{4}\s*,\s*\d{4}", raw_name):
        return "Multi-movie pack (several years in one folder)"
    if re.search(r"\b1\s+and\s+2\b", raw_name, re.I):
        return "Double-feature pack (two movies in one folder)"
    if re.search(r"\btrilogy\b", raw_name, re.I):
        return "Trilogy pack (three movies in one folder)"
    if re.search(r"\b(collection|pack)\b", raw_name, re.I):
        return "Collection / pack"
    return None
