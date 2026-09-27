from datetime import date
from pathlib import Path

from wiki_trends.cache import Cache, default_cache_path


def test_put_fills_absent_days_with_zero(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.put("uk.wikipedia", "Астрономія", date(2024, 1, 1), date(2024, 1, 3), {"2024-01-02": 7})
    assert c.get("uk.wikipedia", "Астрономія", date(2024, 1, 1), date(2024, 1, 3)) == {
        "2024-01-01": (0, False),
        "2024-01-02": (7, False),
        "2024-01-03": (0, False),
    }


def test_missing_flag(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.put("pl.wikipedia", "X", date(2024, 1, 1), date(2024, 1, 2), {}, missing=True)
    assert c.get("pl.wikipedia", "X", date(2024, 1, 1), date(2024, 1, 2))["2024-01-01"] == (0, True)


def test_missing_ranges_coalesce_gaps(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.put("pl.wikipedia", "X", date(2024, 1, 5), date(2024, 1, 10), {})
    assert c.missing_ranges("pl.wikipedia", "X", date(2024, 1, 1), date(2024, 1, 15)) == [
        (date(2024, 1, 1), date(2024, 1, 4)),
        (date(2024, 1, 11), date(2024, 1, 15)),
    ]
    assert c.missing_ranges("pl.wikipedia", "X", date(2024, 1, 5), date(2024, 1, 10)) == []


def test_cache_persists_and_keys_are_separate(tmp_path):
    path = tmp_path / "sub" / "c.sqlite"
    Cache(path).put("pl.wikipedia", "X", date(2024, 1, 1), date(2024, 1, 1), {"2024-01-01": 3})
    again = Cache(path)
    assert again.get("pl.wikipedia", "X", date(2024, 1, 1), date(2024, 1, 1)) == {"2024-01-01": (3, False)}
    assert again.get("cs.wikipedia", "X", date(2024, 1, 1), date(2024, 1, 1)) == {}


def test_default_cache_path(monkeypatch, tmp_path):
    monkeypatch.setenv("WIKI_TRENDS_CACHE", str(tmp_path / "x.sqlite"))
    assert default_cache_path() == tmp_path / "x.sqlite"
    monkeypatch.delenv("WIKI_TRENDS_CACHE")
    assert default_cache_path() == Path.home() / ".cache" / "wiki-trends" / "cache.sqlite"
