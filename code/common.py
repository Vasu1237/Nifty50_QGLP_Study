"""Nifty 50 study helpers (subfolder of P1 Data): paths, cached + rate-limited HTTP, transformation log, CSV output.

Layout (relative to the P1 Data folder):
  raw/            untouched downloads (cache; never edited)
  manual_input/   files YOU download by hand where a site's terms forbid automation
  clean/          pipeline outputs, named <item>_<YYYY-MM-DD>.csv
  logs/           transformations.csv (every transformation) + run logs
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import os
import time
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
P1_ROOT = ROOT.parent
P1_CLEAN = P1_ROOT / "clean"
P1_RAW = P1_ROOT / "raw"
RAW = ROOT / "raw"
MANUAL = ROOT / "manual_input"
CLEAN = ROOT / "clean"
LOGS = ROOT / "logs"
for _d in (RAW, MANUAL, CLEAN, LOGS):
    _d.mkdir(parents=True, exist_ok=True)

TODAY = dt.date.today().isoformat()
START_DATE = "2010-01-01"
UA = "Mozilla/5.0 (research data pipeline; academic use)"


def log(item: str, step: str, detail: str, rows_in: int | None = None, rows_out: int | None = None) -> None:
    """Append one transformation to logs/transformations.csv and echo it."""
    path = LOGS / "transformations.csv"
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "item", "step", "detail", "rows_in", "rows_out"])
        w.writerow([dt.datetime.now().isoformat(timespec="seconds"), item, step, detail, rows_in, rows_out])
    print(f"[{item}] {step}: {detail}" + (f" ({rows_in} -> {rows_out})" if rows_in is not None else ""))


def out_path(item: str) -> Path:
    return CLEAN / f"{item}_{TODAY}.csv"


def save(df, item: str) -> Path:
    p = out_path(item)
    df.to_csv(p, index=False)
    log(item, "save", str(p.name), rows_out=len(df))
    return p


def latest(item: str) -> Path | None:
    files = sorted(CLEAN.glob(f"{item}_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].csv"))
    return files[-1] if files else None


class RateLimiter:
    """Sliding-window limiter supporting several (max_calls, seconds) windows."""

    def __init__(self, *windows: tuple[int, float]):
        self.windows = windows
        self.calls: list[float] = []

    def wait(self) -> None:
        while True:
            now = time.monotonic()
            longest = max(s for _, s in self.windows)
            self.calls = [t for t in self.calls if now - t < longest]
            sleep = 0.0
            for n, s in self.windows:
                recent = [t for t in self.calls if now - t < s]
                if len(recent) >= n:
                    sleep = max(sleep, s - (now - recent[0]) + 0.01)
            if sleep <= 0:
                self.calls.append(now)
                return
            time.sleep(sleep)


def cached_get(url: str, cache_file: Path, headers: dict | None = None,
               limiter: RateLimiter | None = None, retries: int = 4) -> bytes:
    """GET url, caching the raw bytes to cache_file. Cached files are never re-downloaded."""
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return cache_file.read_bytes()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    h = {"User-Agent": UA}
    h.update(headers or {})
    for attempt in range(retries):
        if limiter:
            limiter.wait()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                data = r.read()
            tmp = cache_file.with_suffix(cache_file.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, cache_file)
            return data
        except HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 5)
                continue
            raise
    raise RuntimeError("unreachable")


def gunzip_json(b: bytes):
    return json.loads(gzip.decompress(b))
