"""Checks against the real APIs. Run with: uv run pytest -m live -v"""

from datetime import date

import pytest
import requests

from wiki_trends.api import AQS, WikiClient, encode_title, user_agent

pytestmark = pytest.mark.live


def test_daily_sums_match_the_monthly_endpoint():
    daily = WikiClient().article_daily("en", "Astronomy", date(2024, 1, 1), date(2024, 1, 31))
    url = f"{AQS}/per-article/en.wikipedia/all-access/user/{encode_title('Astronomy')}/monthly/2024010100/2024013100"
    monthly = requests.get(url, headers={"User-Agent": user_agent()}, timeout=30).json()["items"][0]["views"]
    assert sum(daily.values()) == monthly


def test_sitelinks_resolve_real_titles():
    links = WikiClient().sitelinks(["Q333"], ["uk", "pl"])
    assert links["Q333"]["uk"] and links["Q333"]["pl"]


def test_edition_totals_are_plausible():
    totals = WikiClient().edition_daily("cs", date(2024, 1, 1), date(2024, 1, 3))
    assert len(totals) == 3 and all(v > 100_000 for v in totals.values())
