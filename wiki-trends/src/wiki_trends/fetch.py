"""Download (or reuse cached) daily pageviews for a workspace and write data.csv."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from .api import ApiError, NotFound, WikiClient, project_for
from .cache import TOTAL_KEY, Cache
from .workspace import (
    FIRST_MONTH,
    Basket,
    BasketError,
    basket_hash,
    last_complete_month,
    load_basket,
    month_end,
    month_start,
    read_json,
    shift_month,
    validate_dates,
    write_json,
)

PAD_MONTHS = 3  # extra data on each side for the window-sensitivity check
COLUMNS = ["date", "lang", "qid", "title", "views", "edition_total", "missing"]


def padded_range(basket: Basket, today: date) -> tuple[date, date]:
    start = max(shift_month(basket.start, -PAD_MONTHS), FIRST_MONTH)
    end = min(shift_month(basket.end, PAD_MONTHS), last_complete_month(today))
    return month_start(start), month_end(end)


def ensure_series(client: WikiClient, cache: Cache, lang: str, key: str, start: date, end: date) -> dict[str, tuple[int, bool]]:
    """Fill any uncached days of one series from the API, then return all of [start, end]."""
    project = project_for(lang)
    for a, b in cache.missing_ranges(project, key, start, end):
        try:
            if key == TOTAL_KEY:
                views = client.edition_daily(lang, a, b)
            else:
                views = client.article_daily(lang, key, a, b)
        except NotFound:
            if key == TOTAL_KEY:
                raise ApiError(f"no pageview data for '{project}'; check the language code in basket.json 'langs'") from None
            cache.put(project, key, a, b, {}, missing=True)
            continue
        cache.put(project, key, a, b, views)
    return cache.get(project, key, start, end)


def fetch_workspace(ws: Path, client: WikiClient, cache: Cache, today: date, now: datetime) -> dict:
    basket = load_basket(ws)
    validate_dates(basket, today)
    resolved_path = ws / "resolved.json"
    if not resolved_path.exists():
        raise BasketError(f"resolved.json not found; run: wt run {ws.name}")
    resolved = read_json(resolved_path)
    if resolved.get("basket_hash") != basket_hash(basket):
        raise BasketError(f"basket.json changed since resolve; run: wt run {ws.name}")

    start, end = padded_range(basket, today)
    before = client.requests_made
    rows = []
    for lang in basket.langs:
        totals = ensure_series(client, cache, lang, TOTAL_KEY, start, end)
        for art in (a for a in resolved["articles"] if a["lang"] == lang):
            series = ensure_series(client, cache, lang, art["title"], start, end)
            for day, (views, missing) in sorted(series.items()):
                rows.append([day, lang, art["qid"], art["title"], views, totals.get(day, (0, False))[0], int(missing)])

    with open(ws / "data.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    meta = {
        "basket_hash": basket_hash(basket),
        "retrieved_at": now.isoformat(timespec="seconds"),
        "range": [start.isoformat(), end.isoformat()],
        "window": [basket.start, basket.end],
        "api_requests": client.requests_made - before,
        "rows": len(rows),
    }
    write_json(ws / "fetch_meta.json", meta)
    return meta
