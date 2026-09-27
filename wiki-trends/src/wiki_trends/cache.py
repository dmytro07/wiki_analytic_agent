"""SQLite cache of daily pageviews. Past days never change, so cached rows are reused forever."""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

TOTAL_KEY = "__total__"  # key for a whole edition's daily total


def default_cache_path() -> Path:
    env = os.environ.get("WIKI_TRENDS_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "wiki-trends" / "cache.sqlite"


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


class Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS daily ("
            " project TEXT NOT NULL, key TEXT NOT NULL, day TEXT NOT NULL,"
            " views INTEGER NOT NULL, missing INTEGER NOT NULL DEFAULT 0,"
            " PRIMARY KEY (project, key, day))"
        )
        self.conn.commit()

    def get(self, project: str, key: str, start: date, end: date) -> dict[str, tuple[int, bool]]:
        rows = self.conn.execute(
            "SELECT day, views, missing FROM daily WHERE project = ? AND key = ? AND day BETWEEN ? AND ?",
            (project, key, start.isoformat(), end.isoformat()),
        )
        return {day: (views, bool(missing)) for day, views, missing in rows}

    def put(self, project: str, key: str, start: date, end: date, views: dict[str, int], missing: bool = False) -> None:
        """Store every day in [start, end]; days absent from `views` are 0 (AQS omits zero-view days)."""
        rows = [(project, key, d.isoformat(), views.get(d.isoformat(), 0), int(missing)) for d in _days(start, end)]
        self.conn.executemany("INSERT OR REPLACE INTO daily VALUES (?, ?, ?, ?, ?)", rows)
        self.conn.commit()

    def missing_ranges(self, project: str, key: str, start: date, end: date) -> list[tuple[date, date]]:
        have = set(self.get(project, key, start, end))
        ranges: list[tuple[date, date]] = []
        run_start: date | None = None
        prev = start
        for d in _days(start, end):
            if d.isoformat() not in have:
                if run_start is None:
                    run_start = d
            elif run_start is not None:
                ranges.append((run_start, prev))
                run_start = None
            prev = d
        if run_start is not None:
            ranges.append((run_start, end))
        return ranges

    def close(self) -> None:
        self.conn.close()
