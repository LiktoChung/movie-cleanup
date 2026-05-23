from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from src.config import CACHE_DB, TMDB_API_KEY

TMDB_BASE = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w185"
MIN_REQUEST_INTERVAL = 0.26  # ~40 req / 10s


@dataclass
class MovieInfo:
    tmdb_id: int
    imdb_id: str | None
    title: str
    year: int | None
    poster_path: str | None

    @property
    def poster_url(self) -> str | None:
        if self.poster_path:
            return f"{POSTER_BASE}{self.poster_path}"
        return None


class TmdbClient:
    def __init__(self, api_key: str | None = None, cache_path: Path | None = None):
        self.api_key = api_key or TMDB_API_KEY
        if not self.api_key:
            raise ValueError("TMDB_API_KEY is not set. Add it to .env")
        self.cache_path = cache_path or CACHE_DB
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0
        self._conn = sqlite3.connect(self.cache_path)
        self._init_cache()

    def _init_cache(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _cache_get(self, key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT payload FROM cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if row:
            return json.loads(row[0])
        return None

    def _cache_set(self, key: str, payload: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (cache_key, payload, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload), time.time()),
        )
        self._conn.commit()

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request = time.time()

    def _get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["api_key"] = self.api_key
        cache_key = f"GET:{path}:{json.dumps(params, sort_keys=True)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        self._throttle()
        url = f"{TMDB_BASE}{path}"
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        self._cache_set(cache_key, data)
        return data

    @staticmethod
    def _parse_movie(data: dict) -> MovieInfo:
        release = data.get("release_date") or ""
        year = int(release[:4]) if len(release) >= 4 and release[:4].isdigit() else None
        imdb = data.get("imdb_id")
        return MovieInfo(
            tmdb_id=int(data["id"]),
            imdb_id=imdb if imdb else None,
            title=data.get("title") or data.get("original_title") or "Unknown",
            year=year,
            poster_path=data.get("poster_path"),
        )

    def get_by_tmdb_id(self, tmdb_id: int) -> MovieInfo | None:
        try:
            data = self._get(f"/movie/{tmdb_id}")
            return self._parse_movie(data)
        except requests.HTTPError:
            return None

    def find_by_imdb_id(self, imdb_id: str) -> MovieInfo | None:
        imdb_id = imdb_id if imdb_id.startswith("tt") else f"tt{imdb_id}"
        try:
            data = self._get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
            results = data.get("movie_results") or []
            if results:
                return self._parse_movie(results[0])
        except requests.HTTPError:
            pass
        return None

    def search_movie(self, title: str, year: int | None = None) -> list[MovieInfo]:
        params: dict = {"query": title, "include_adult": "false"}
        if year:
            params["year"] = year
        try:
            data = self._get("/search/movie", params)
        except requests.HTTPError:
            return []
        return [self._parse_movie(r) for r in data.get("results", [])]
