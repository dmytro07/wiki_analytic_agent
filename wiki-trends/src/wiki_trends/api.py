"""The only module that talks to the network: Wikimedia AQS pageviews and Wikidata."""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Callable
from urllib.parse import quote

import requests

AQS = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
WIKIDATA = "https://www.wikidata.org/w/api.php"
RETRY_STATUSES = {429, 500, 502, 503, 504}
FIRST_DELAY, MAX_DELAY = 2.0, 30.0  # seconds; 7 attempts wait ~90 s in total, enough for rate limits
WIKIDATA_BATCH = 50

Transport = Callable[[str, "dict | None", dict], "tuple[int, dict | None]"]


class ApiError(RuntimeError):
    """The API could not give us the data; the message says what to try."""


class NotFound(ApiError):
    """HTTP 404: no data for this article/range, or unknown project."""


def user_agent() -> str:
    contact = os.environ.get("WIKI_TRENDS_CONTACT", "set WIKI_TRENDS_CONTACT to your email or URL")
    return f"wiki-trends-skill/0.1 ({contact}) python-requests"


def requests_transport(url: str, params: dict | None, headers: dict) -> tuple[int, dict | None]:
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body


def project_for(lang: str) -> str:
    return f"{lang}.wikipedia"


def encode_title(title: str) -> str:
    return quote(title.replace(" ", "_"), safe="")


def _stamp(d: date) -> str:
    return d.strftime("%Y%m%d") + "00"


def _detail(body) -> str:
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("title") or "")
    return ""


def _daily_items(body: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in body.get("items", []):
        ts = item["timestamp"]  # YYYYMMDDHH
        out[f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"] = int(item["views"])
    return out


class WikiClient:
    def __init__(
        self,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_attempts: int = 7,
        min_interval: float = 0.02,  # ≤50 requests/second
    ):
        self.transport = transport or requests_transport
        self.sleep, self.clock = sleep, clock
        self.max_attempts, self.min_interval = max_attempts, min_interval
        self.requests_made = 0
        self._last = float("-inf")

    def _get(self, url: str, params: dict | None = None) -> dict:
        headers = {"User-Agent": user_agent(), "Accept": "application/json"}
        delay, last_error = FIRST_DELAY, ""
        for attempt in range(1, self.max_attempts + 1):
            wait = self._last + self.min_interval - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._last = self.clock()
            self.requests_made += 1
            try:
                status, body = self.transport(url, params, headers)
            except requests.RequestException as exc:
                status, body, last_error = None, None, str(exc)
            if status == 200:
                return body or {}
            if status == 404:
                raise NotFound(url)
            if status is not None and status not in RETRY_STATUSES:
                raise ApiError(f"HTTP {status} from {url}: {_detail(body)}")
            if status is not None:
                last_error = f"HTTP {status}"
            if attempt < self.max_attempts:
                self.sleep(delay)
                delay = min(delay * 2, MAX_DELAY)
        raise ApiError(
            f"gave up after {self.max_attempts} attempts on {url} ({last_error}); "
            "the Wikimedia API may be down or rate-limiting; wait a minute and run the same command again "
            "(data already downloaded is cached)"
        )

    # --- Wikidata -------------------------------------------------------------

    def search_items(self, term: str, lang: str, limit: int = 5) -> list[dict]:
        body = self._get(
            WIKIDATA,
            {"action": "wbsearchentities", "search": term, "language": lang, "uselang": lang,
             "type": "item", "limit": limit, "format": "json"},
        )
        return [
            {"qid": hit["id"], "label": hit.get("label", ""), "description": hit.get("description", "")}
            for hit in body.get("search", [])
        ]

    def sitelinks(self, qids: list[str], langs: list[str]) -> dict[str, dict[str, str] | None]:
        site_of = {lang: lang.replace("-", "_") + "wiki" for lang in langs}
        out: dict[str, dict[str, str] | None] = {}
        for i in range(0, len(qids), WIKIDATA_BATCH):
            chunk = qids[i:i + WIKIDATA_BATCH]
            body = self._get(
                WIKIDATA,
                {"action": "wbgetentities", "ids": "|".join(chunk), "props": "sitelinks",
                 "sitefilter": "|".join(site_of.values()), "format": "json"},
            )
            if "error" in body:
                raise ApiError(f"Wikidata error: {body['error'].get('info', body['error'])}")
            entities = body.get("entities", {})
            for qid in chunk:
                ent = entities.get(qid)
                if ent is None or "missing" in ent:
                    out[qid] = None
                    continue
                links = ent.get("sitelinks", {})
                out[qid] = {lang: links[site]["title"] for lang, site in site_of.items() if site in links}
        return out

    # --- pageviews ------------------------------------------------------------

    def article_daily(self, lang: str, title: str, start: date, end: date) -> dict[str, int]:
        url = (f"{AQS}/per-article/{project_for(lang)}/all-access/user/{encode_title(title)}"
               f"/daily/{_stamp(start)}/{_stamp(end)}")
        return _daily_items(self._get(url))

    def edition_daily(self, lang: str, start: date, end: date) -> dict[str, int]:
        url = f"{AQS}/aggregate/{project_for(lang)}/all-access/user/daily/{_stamp(start)}/{_stamp(end)}"
        return _daily_items(self._get(url))
