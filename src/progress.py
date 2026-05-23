from __future__ import annotations

import sys
import time
from typing import Callable, Iterable, Iterator, TypeVar

from src.scan_progress import ScanCancelled, ScanProgress, is_cancel_requested

T = TypeVar("T")


def track(
    iterable: Iterable[T],
    *,
    total: int | None = None,
    desc: str = "",
    disable: bool = False,
    unit: str = "item",
    reporter: ScanProgress | None = None,
    get_message: Callable[[T], str | None] | None = None,
) -> Iterator[T]:
    """Iterate with optional web progress file, tqdm on stderr, or simple fallback."""
    it: Iterable[T] = iterable

    if not disable:
        try:
            from tqdm import tqdm

            it = tqdm(
                iterable,
                total=total,
                desc=desc,
                unit=unit,
                dynamic_ncols=True,
                file=sys.stderr,
            )
        except ImportError:
            if reporter is None:
                yield from _simple_progress(iterable, total=total, desc=desc)
                return

    for i, item in enumerate(it, 1):
        if is_cancel_requested():
            if reporter:
                reporter.cancelled()
            raise ScanCancelled()
        if reporter:
            msg = get_message(item) if get_message else None
            reporter.tick(i, total, msg)
        yield item


def _simple_progress(
    iterable: Iterable[T],
    *,
    total: int | None,
    desc: str,
) -> Iterator[T]:
    """Minimal progress without tqdm."""
    start = time.monotonic()
    label = desc or "Progress"
    for i, item in enumerate(iterable, 1):
        elapsed = time.monotonic() - start
        rate = i / elapsed if elapsed > 0 else 0
        if total:
            pct = i / total * 100
            line = f"\r{label}: {i}/{total} ({pct:.0f}%) — {rate:.1f}/s"
        else:
            line = f"\r{label}: {i} — {rate:.1f}/s"
        print(line, end="", file=sys.stderr, flush=True)
        yield item
    print(file=sys.stderr)
