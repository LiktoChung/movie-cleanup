#!/usr/bin/env python3
"""Serve web UI for reviewing duplicate movies and quarantining copies."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import DATA_DIR, LIBRARY_PATH, PORT, PROJECT_ROOT, SCAN_JSON, TMDB_API_KEY
from src.empty_folders import remove_empty_folders, remove_empty_folders_from_scan
from src.quarantine import quarantine_paths
from src.scan_progress import ScanProgress, is_cancel_requested, read_progress, request_cancel
from src.scan_store import _norm_path, remove_items_from_scan
from src.tmdb_client import TmdbClient
from src.tmdb_lookup import apply_tmdb_match, load_scan_data, search_movies

WEB_DIR = PROJECT_ROOT / "web"
app = FastAPI(title="Movie Duplicate Cleanup")

_scan_lock = threading.Lock()
_rescan_running = False
_scan_process: subprocess.Popen[int] | None = None


class QuarantineRequest(BaseModel):
    quarantine_paths: list[str]
    keeper_path: str | None = None
    tmdb_id: int | None = None
    note: str = ""


class ApplyTmdbMatchRequest(BaseModel):
    item_path: str
    tmdb_id: int


class RemoveEmptyFoldersRequest(BaseModel):
    paths: list[str]


def _load_scan() -> dict:
    if not SCAN_JSON.exists():
        raise HTTPException(
            status_code=404,
            detail="No scan data. Run: python scan.py",
        )
    with open(SCAN_JSON, encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/scan")
def api_scan() -> dict:
    return _load_scan()


@app.get("/api/status")
def api_status() -> dict:
    prog = read_progress()
    running = _rescan_running or bool(prog and prog.get("running"))
    return {
        "scan_exists": SCAN_JSON.exists(),
        "scan_path": str(SCAN_JSON),
        "rescan_running": running,
        "progress": prog,
    }


@app.post("/api/quarantine")
def api_quarantine(body: QuarantineRequest) -> dict:
    if not body.quarantine_paths:
        raise HTTPException(status_code=400, detail="No paths to quarantine")

    keeper = body.keeper_path
    to_move = [p for p in body.quarantine_paths if p != keeper]
    if not to_move:
        raise HTTPException(status_code=400, detail="Nothing to quarantine")

    results = quarantine_paths(
        to_move,
        note=body.note,
        tmdb_id=body.tmdb_id,
    )
    failed = [r for r in results if not r.get("success", True)]
    success_sources = [r["source"] for r in results if r.get("success") and r.get("source")]
    if success_sources:
        remove_items_from_scan(success_sources)

    return {
        "moved": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }


@app.post("/api/rescan")
def api_rescan() -> dict:
    global _rescan_running
    with _scan_lock:
        if _rescan_running:
            prog = read_progress()
            return {"status": "already_running", "progress": prog}
        _rescan_running = True

    # Write progress before starting subprocess so the UI updates immediately
    ScanProgress().begin(str(LIBRARY_PATH))
    prog = read_progress()

    def run_scan() -> None:
        global _rescan_running, _scan_process
        proc: subprocess.Popen[int] | None = None
        try:
            proc = subprocess.Popen(
                [sys.executable, str(PROJECT_ROOT / "scan.py"), "-q"],
                cwd=str(PROJECT_ROOT),
            )
            with _scan_lock:
                _scan_process = proc
            exit_code = proc.wait()
            prog_after = read_progress()
            if (
                exit_code != 0
                and prog_after
                and prog_after.get("running")
                and prog_after.get("phase") not in ("cancelled", "error", "done")
                and not is_cancel_requested()
            ):
                ScanProgress().fail(f"Scan exited with code {exit_code}")
        finally:
            with _scan_lock:
                _scan_process = None
                _rescan_running = False

    thread = threading.Thread(target=run_scan, daemon=True)
    thread.start()
    return {"status": "started", "progress": prog}


@app.get("/api/tmdb/search")
def api_tmdb_search(
    q: str = Query(..., min_length=2),
    year: int | None = None,
    item_path: str | None = None,
) -> dict:
    if not TMDB_API_KEY:
        raise HTTPException(status_code=503, detail="TMDB_API_KEY not set")
    query = q.strip()
    scan_data = load_scan_data()
    client = TmdbClient()
    try:
        results = search_movies(
            client,
            query,
            year,
            scan_data,
            item_path=item_path,
        )
        return {"query": query, "year": year, "results": results}
    finally:
        client.close()


@app.post("/api/tmdb/apply-match")
def api_apply_tmdb_match(body: ApplyTmdbMatchRequest) -> dict:
    if not TMDB_API_KEY:
        raise HTTPException(status_code=503, detail="TMDB_API_KEY not set")
    client = TmdbClient()
    try:
        result = apply_tmdb_match(body.item_path, body.tmdb_id, client)
        return {"status": "ok", **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        client.close()


@app.post("/api/cancel-scan")
def api_cancel_scan() -> dict:
    global _rescan_running, _scan_process
    with _scan_lock:
        running = _rescan_running
        proc = _scan_process

    prog = read_progress()
    if not running and not (prog and prog.get("running")):
        return {"status": "not_running", "progress": prog}

    request_cancel()
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)

    ScanProgress().cancelled()
    with _scan_lock:
        _rescan_running = False

    return {"status": "cancelled", "progress": read_progress()}


@app.post("/api/empty-folders/remove")
def api_remove_empty_folders(body: RemoveEmptyFoldersRequest) -> dict:
    if not body.paths:
        raise HTTPException(status_code=400, detail="No paths to remove")

    scan_data = _load_scan()
    allowed = {_norm_path(f["path"]) for f in scan_data.get("empty_folders", [])}
    library_path = scan_data.get("library_path")
    library_root = Path(library_path) if library_path else LIBRARY_PATH

    results = remove_empty_folders(
        body.paths,
        allowed_paths=allowed,
        library_root=library_root,
    )
    removed = [
        r["path"]
        for r in results
        if r.get("success") and not r.get("already_gone")
    ]
    if removed or any(r.get("already_gone") for r in results):
        remove_empty_folders_from_scan(
            [r["path"] for r in results if r.get("success")]
        )

    failed = [r for r in results if not r.get("success")]
    return {
        "removed": len(removed),
        "failed": len(failed),
        "results": results,
        "scan": _load_scan(),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Open http://127.0.0.1:{PORT}")
    if not SCAN_JSON.exists():
        print("Note: No scan data yet. Run: python scan.py")
    if TMDB_API_KEY:
        print("TMDB manual search: enabled (/api/tmdb/search)")
    else:
        print("TMDB manual search: disabled (set TMDB_API_KEY in .env)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
