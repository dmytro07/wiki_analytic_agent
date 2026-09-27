import csv
import json
from datetime import date, datetime, timezone

import pytest

from fakes import FakeWiki
from wiki_trends.api import ApiError, WikiClient
from wiki_trends.cache import Cache
from wiki_trends.fetch import fetch_workspace, padded_range
from wiki_trends.resolve import resolve_workspace
from wiki_trends.workspace import BasketError, basket_from_dict

TODAY = date(2025, 9, 27)
NOW = datetime(2025, 9, 27, 10, 0, tzinfo=timezone.utc)


def setup(tmp_path, fake, **over):
    ws = tmp_path / "ws"
    ws.mkdir()
    b = {"question": "q", "langs": ["uk"], "start": "2024-01", "end": "2024-06",
         "items": [{"qid": "Q333", "label": "astronomy"}, {"qid": "Q1", "label": "gone"}]}
    b.update(over)
    (ws / "basket.json").write_text(json.dumps(b, ensure_ascii=False))
    client = WikiClient(transport=fake, sleep=lambda s: None)
    resolve_workspace(ws, client)
    return ws, client, Cache(tmp_path / "cache.sqlite")


def fake():
    return FakeWiki(
        {"Q333": {"uk": "Астрономія"}, "Q1": {"uk": "Видалена"}},
        article_views=lambda lang, title, d: 50 + d.day,
        edition_views=lambda lang, d: 1_000_000,
        missing_titles={"Видалена"},
    )


def read_rows(ws):
    with open(ws / "data.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_padded_range_clips_to_complete_months():
    b = basket_from_dict({"question": "", "langs": ["uk"], "start": "2024-01", "end": "2025-08", "items": [{"qid": "Q1"}]})
    assert padded_range(b, TODAY) == (date(2023, 10, 1), date(2025, 8, 31))


def test_fetch_writes_padded_rows_and_meta(tmp_path):
    ws, client, cache = setup(tmp_path, fake())
    meta = fetch_workspace(ws, client, cache, TODAY, NOW)
    rows = read_rows(ws)
    days = (date(2024, 9, 30) - date(2023, 10, 1)).days + 1
    assert meta["rows"] == len(rows) == 2 * days
    assert meta["range"] == ["2023-10-01", "2024-09-30"]
    assert meta["retrieved_at"] == "2025-09-27T10:00:00+00:00"
    first = next(r for r in rows if r["title"] == "Астрономія")
    assert first == {"date": "2023-10-01", "lang": "uk", "qid": "Q333", "title": "Астрономія",
                     "views": "51", "edition_total": "1000000", "missing": "0"}
    gone = [r for r in rows if r["title"] == "Видалена"]
    assert all(r["missing"] == "1" and r["views"] == "0" for r in gone)


def test_second_fetch_uses_cache_only(tmp_path):
    f = fake()
    ws, client, cache = setup(tmp_path, f)
    first = fetch_workspace(ws, client, cache, TODAY, NOW)
    calls = len(f.calls)
    again = fetch_workspace(ws, client, cache, TODAY, NOW)
    assert first["api_requests"] == 3  # edition total + 2 articles
    assert again["api_requests"] == 0
    assert len(f.calls) == calls


def test_unknown_language_is_actionable(tmp_path):
    f = fake()
    f.sitelinks["Q333"]["xx"] = "Foo"
    ws, client, cache = setup(tmp_path, f, langs=["xx"])
    with pytest.raises(ApiError, match="language code"):
        fetch_workspace(ws, client, cache, TODAY, NOW)


def test_fetch_rejects_stale_resolve(tmp_path):
    ws, client, cache = setup(tmp_path, fake())
    b = json.loads((ws / "basket.json").read_text())
    b["start"] = "2023-12"
    (ws / "basket.json").write_text(json.dumps(b, ensure_ascii=False))
    with pytest.raises(BasketError, match="wt run"):
        fetch_workspace(ws, client, cache, TODAY, NOW)


def test_fetch_rejects_incomplete_end_month(tmp_path):
    ws, client, cache = setup(tmp_path, fake(), start="2025-01", end="2025-09")
    with pytest.raises(BasketError, match="latest complete month is 2025-08"):
        fetch_workspace(ws, client, cache, TODAY, NOW)


def test_unpublished_days_are_not_cached_as_zeros(tmp_path):
    f = fake()
    f.edition_views = lambda lang, d: 1_000_000 if d <= date(2024, 9, 28) else 0  # AQS omits unpublished days
    ws, client, cache = setup(tmp_path, f)  # window 2024-01..2024-06, padded to 2024-09-30
    meta = fetch_workspace(ws, client, cache, TODAY, NOW)
    assert max(r["date"] for r in read_rows(ws)) == "2024-09-28"
    assert meta["range"][1] == "2024-09-28"
    assert cache.get("uk.wikipedia", "__total__", date(2024, 9, 29), date(2024, 9, 30)) == {}
    assert cache.get("uk.wikipedia", "Астрономія", date(2024, 9, 29), date(2024, 9, 30)) == {}


def test_window_end_not_yet_published_is_actionable(tmp_path):
    f = fake()
    f.edition_views = lambda lang, d: 1_000_000 if d <= date(2024, 6, 27) else 0
    ws, client, cache = setup(tmp_path, f)
    with pytest.raises(BasketError, match=r'published only up to 2024-06-27.*"end": "2024-05"'):
        fetch_workspace(ws, client, cache, TODAY, NOW)
