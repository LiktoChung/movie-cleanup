# Movie Duplicate Cleanup

Scan a movie library on a network share, resolve each folder/file to a canonical movie identity (NFO metadata + guessit + TMDB), find duplicates, and review them in a local web UI. Selected copies are **moved to quarantine**, not permanently deleted.

## Setup

1. Install Python 3.11+.
2. Copy `.env.example` to `.env` and set your [TMDB API key](https://www.themoviedb.org/settings/api).
3. Adjust `LIBRARY_PATH` and `QUARANTINE_PATH` if needed.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env with your TMDB_API_KEY
```

## Usage

### 1. Scan the library

```powershell
python scan.py
# Or specify a path:
python scan.py --path "\\path\to\movies"
# Progress bars show scan + TMDB phases; use -q to disable
python scan.py -q
```

This walks the library, parses names, queries TMDB (cached in `data/cache.db`), and writes `data/scan.json`.

### 2. Review duplicates in the web UI

```powershell
python serve.py
```

Open http://127.0.0.1:8765 in your browser.

- **Duplicate groups** show items that share the same TMDB movie ID.
- Pick which copy to **keep** (radio); check others to **quarantine**.
- **Low-confidence** items are listed separately for manual review.

### 3. Quarantine

Click **Quarantine selected** after confirming paths. Items are moved to:

`QUARANTINE_PATH\YYYY-MM-DD_HH-mm-ss\<original name>`

A log is appended to `data/quarantine-log.jsonl`.

## How matching works

1. Kodi-style `.nfo` files (`imdb` / `tmdb` unique IDs) — highest priority
2. `guessit` parse of folder or primary video filename
3. TMDB search by title + year
4. Items with the same **TMDB ID** are grouped as duplicates
5. Different years (e.g. Mean Girls 2004 vs 2024) get different TMDB IDs and are **not** grouped

## Safety

- No permanent deletes in v1 — only quarantine moves
- Confirmation modal before quarantine
- All moves logged to `data/quarantine-log.jsonl`
