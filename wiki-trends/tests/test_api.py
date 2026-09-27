import itertools
from datetime import date
from urllib.parse import quote

import pytest
import requests

from wiki_trends.api import AQS, ApiError, NotFound, WikiClient, encode_title, user_agent


class Scripted:
    """Transport returning queued (status, body) pairs; an Exception entry is raised."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, params, headers):
        self.calls.append((url, params, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(responses):
    transport = Scripted(responses)
    sleeps = []
    client = WikiClient(transport=transport, sleep=sleeps.append, clock=itertools.count(0, 10).__next__)
    return client, transport, sleeps


def test_article_daily_url_and_parse():
    c, t, _ = make([(200, {"items": [{"timestamp": "2024010100", "views": 5}, {"timestamp": "2024010200", "views": 7}]})])
    out = c.article_daily("uk", "Астрономія", date(2024, 1, 1), date(2024, 1, 2))
    assert out == {"2024-01-01": 5, "2024-01-02": 7}
    assert t.calls[0][0] == (
        f"{AQS}/per-article/uk.wikipedia/all-access/user/{quote('Астрономія', safe='')}/daily/2024010100/2024010200"
    )
    assert c.requests_made == 1


@pytest.mark.parametrize(
    "title,encoded",
    [("AC/DC", "AC%2FDC"), ("What?", "What%3F"), ("Rock 'n' roll", "Rock_%27n%27_roll"), ("Intermittent fasting", "Intermittent_fasting")],
)
def test_titles_are_url_encoded(title, encoded):
    assert encode_title(title) == encoded


def test_edition_daily_url():
    c, t, _ = make([(200, {"items": [{"timestamp": "2024010100", "views": 1000}]})])
    assert c.edition_daily("pl", date(2024, 1, 1), date(2024, 1, 1)) == {"2024-01-01": 1000}
    assert t.calls[0][0] == f"{AQS}/aggregate/pl.wikipedia/all-access/user/daily/2024010100/2024010100"


def test_user_agent_uses_contact(monkeypatch):
    monkeypatch.setenv("WIKI_TRENDS_CONTACT", "me@example.com")
    assert "me@example.com" in user_agent()
    c, t, _ = make([(200, {"items": []})])
    c.edition_daily("pl", date(2024, 1, 1), date(2024, 1, 1))
    assert "me@example.com" in t.calls[0][2]["User-Agent"]


def test_retries_then_succeeds():
    c, t, sleeps = make([(429, None), (503, None), requests.ConnectionError("boom"), (200, {"items": []})])
    assert c.edition_daily("pl", date(2024, 1, 1), date(2024, 1, 1)) == {}
    assert sleeps == [1.0, 2.0, 4.0]
    assert len(t.calls) == 4


def test_gives_up_after_max_attempts():
    c, t, _ = make([(503, None)] * 5)
    with pytest.raises(ApiError, match="gave up after 5 attempts"):
        c.edition_daily("pl", date(2024, 1, 1), date(2024, 1, 1))
    assert len(t.calls) == 5


def test_404_is_not_found_without_retry():
    c, t, _ = make([(404, {"title": "Not found."})])
    with pytest.raises(NotFound):
        c.article_daily("pl", "Nope", date(2024, 1, 1), date(2024, 1, 1))
    assert len(t.calls) == 1


def test_400_fails_fast_with_detail():
    c, t, _ = make([(400, {"detail": "bad date"})])
    with pytest.raises(ApiError, match="HTTP 400.*bad date"):
        c.edition_daily("pl", date(2024, 1, 1), date(2024, 1, 1))
    assert len(t.calls) == 1


def test_search_items():
    c, t, _ = make([(200, {"search": [{"id": "Q333", "label": "astronomy", "description": "study of celestial objects"}]})])
    assert c.search_items("astronomy", "en") == [{"qid": "Q333", "label": "astronomy", "description": "study of celestial objects"}]
    params = t.calls[0][1]
    assert params["action"] == "wbsearchentities" and params["search"] == "astronomy" and params["language"] == "en"


def test_sitelinks_missing_items_and_chunking():
    calls = []

    def transport(url, params, headers):
        calls.append(params)
        ents = {}
        for q in params["ids"].split("|"):
            if q == "Q999":
                ents[q] = {"id": q, "missing": ""}
            else:
                ents[q] = {"id": q, "sitelinks": {"ukwiki": {"title": f"T{q}"}, "enwiki": {"title": "ignored"}}}
        return 200, {"entities": ents}

    c = WikiClient(transport=transport, sleep=lambda s: None)
    qids = [f"Q{i}" for i in range(1, 51)] + ["Q999"]
    out = c.sitelinks(qids, ["uk", "pl"])
    assert len(calls) == 2
    assert calls[0]["sitefilter"] == "ukwiki|plwiki"
    assert out["Q1"] == {"uk": "TQ1"}
    assert out["Q999"] is None


def test_sitelinks_api_error():
    c, _, _ = make([(200, {"error": {"code": "no-such-entity", "info": "Could not find Q0"}})])
    with pytest.raises(ApiError, match="Could not find Q0"):
        c.sitelinks(["Q0"], ["uk"])
