"""In-memory stand-in for Wikidata and the Wikimedia pageviews API (no network)."""

from datetime import date, datetime, timedelta
from urllib.parse import unquote


def _parse(stamp: str) -> date:
    return datetime.strptime(stamp[:8], "%Y%m%d").date()


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


class FakeWiki:
    def __init__(self, sitelinks, article_views=None, edition_views=None, missing_titles=(),
                 unknown_langs=("xx",), search_results=()):
        self.sitelinks = sitelinks  # {qid: {lang: title}}
        self.article_views = article_views or (lambda lang, title, day: 100)
        self.edition_views = edition_views or (lambda lang, day: 1_000_000)
        self.missing_titles = set(missing_titles)
        self.unknown_langs = set(unknown_langs)
        self.search_results = list(search_results)  # [(qid, label, description)]
        self.calls: list[str] = []

    def __call__(self, url, params, headers):
        self.calls.append(url)
        if "wikidata.org" in url:
            return 200, self._wikidata(params)
        path = url.split("/metrics/pageviews/", 1)[1].split("/")
        lang = path[1].split(".")[0]
        if lang in self.unknown_langs:
            return 404, {"title": "Not found."}
        if path[0] == "per-article":
            title = unquote(path[4]).replace("_", " ")
            if title in self.missing_titles:
                return 404, {"title": "Not found."}
            days, fn = _days(_parse(path[6]), _parse(path[7])), lambda d: self.article_views(lang, title, d)
        elif path[0] == "aggregate":
            days, fn = _days(_parse(path[5]), _parse(path[6])), lambda d: self.edition_views(lang, d)
        else:
            return 400, {"detail": "unexpected url"}
        items = []
        for d in days:
            v = int(fn(d))
            if v > 0:
                items.append({"timestamp": d.strftime("%Y%m%d00"), "views": v})
        return 200, {"items": items}

    def _wikidata(self, params):
        if params["action"] == "wbsearchentities":
            return {"search": [{"id": q, "label": l, "description": d} for q, l, d in self.search_results]}
        sites = params["sitefilter"].split("|")
        ents = {}
        for q in params["ids"].split("|"):
            if q not in self.sitelinks:
                ents[q] = {"id": q, "missing": ""}
                continue
            ents[q] = {"id": q, "sitelinks": {
                f"{lang}wiki": {"site": f"{lang}wiki", "title": t}
                for lang, t in self.sitelinks[q].items() if f"{lang}wiki" in sites
            }}
        return {"entities": ents, "success": 1}
