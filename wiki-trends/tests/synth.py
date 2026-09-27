"""Synthetic workspaces with known answers, for analysis, report and eval tests."""

import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd

from wiki_trends.fmt import fmt_num, fmt_pct
from wiki_trends.workspace import basket_hash, load_basket, month_end, month_start, shift_month, write_json


def const(v):
    return lambda days: np.full(len(days), float(v))


def exp_growth(v0, monthly_rate):
    return lambda days: v0 * (1 + monthly_rate) ** (np.arange(len(days)) / 30.44)


def seasonal(v0, amp):
    return lambda days: v0 * (1 + amp * np.sin(2 * np.pi * (days.month.to_numpy() - 1) / 12))


def with_spike(fn, day, extra):
    def f(days):
        v = fn(days).copy()
        v[days.get_loc(pd.Timestamp(day))] += extra
        return v
    return f


def build_workspace(root, spec, start="2023-01", end="2024-12", extra_langs=(), gaps=(), missing_titles=(), name="ws"):
    ws = Path(root) / name
    ws.mkdir(parents=True)
    langs = list(spec) + list(extra_langs)
    titles = sorted({t for s in spec.values() for t in s["articles"]})
    qid_of = {t: f"Q{100 + i}" for i, t in enumerate(titles)}
    items = [{"qid": qid_of[t], "label": t.lower(), "role": "core"} for t in titles]
    for g in gaps:
        if g["qid"] not in {i["qid"] for i in items}:
            items.append({"qid": g["qid"], "label": g["label"], "role": g["role"]})
    basket = {"question": "Synthetic question?", "langs": langs, "start": start, "end": end, "items": items}
    (ws / "basket.json").write_text(json.dumps(basket), encoding="utf-8")
    h = basket_hash(load_basket(ws))
    articles = [
        {"lang": lang, "qid": qid_of[t], "label": t.lower(), "role": "core", "title": t, "source": "wikidata"}
        for lang, s in spec.items() for t in s["articles"]
    ]
    write_json(ws / "resolved.json", {"basket_hash": h, "articles": articles, "gaps": list(gaps)})
    days = pd.date_range(month_start(shift_month(start, -3)), month_end(shift_month(end, 3)), freq="D")
    n = 0
    with open(ws / "data.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "lang", "qid", "title", "views", "edition_total", "missing"])
        for lang, s in spec.items():
            edition = s["edition"](days)
            for t, fn in s["articles"].items():
                views = fn(days)
                miss = int(t in missing_titles)
                for i, d in enumerate(days):
                    writer.writerow([d.strftime("%Y-%m-%d"), lang, qid_of[t], t, int(round(views[i])), int(round(edition[i])), miss])
                    n += 1
    write_json(ws / "fetch_meta.json", {
        "basket_hash": h, "retrieved_at": "2025-09-27T10:00:00+00:00",
        "range": [days[0].strftime("%Y-%m-%d"), days[-1].strftime("%Y-%m-%d")],
        "window": [start, end], "api_requests": 0, "rows": n,
    })
    return ws


def narrative_for(analysis, lang):
    """A narrative that passes `check` whatever the numbers are."""
    d = analysis["languages"][lang]
    b = d["basket"]
    return (
        f"# Interest in the topic on {lang} Wikipedia\n\n"
        f"- Share of edition views changed {fmt_pct(b['growth_norm_pct'])} year over year.\n"
        f"- Median level is {fmt_num(b['level_norm'], 2)} views per million.\n"
        f"- Confidence is {d['confidence'].lower()}.\n\n"
        "## Recommendation\n\n"
        "Treat this as a tentative signal and validate it with user interviews.\n"
    )
