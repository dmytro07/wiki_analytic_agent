"""Turn a workspace's data.csv into analysis.json: metrics, trust checks, confidence, ranking."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from . import trust
from .fmt import fmt_num, fmt_pct
from .metrics import growth_pct, normalize, seasonality_strength, trend, window_monthly
from .workspace import Basket, BasketError, basket_hash, load_basket, read_json, write_json

CONFIDENCE_VALUE = {"High": 1.0, "Medium": 0.5, "Low": 0.0}
GROWTH_METHOD_TEXT = {
    "yoy_12m": "last 12 months vs the previous 12",
    "half_split": "second half vs first half of the window",
}
SOURCE = "Wikimedia Pageviews API (agent=user, all-access) + Wikidata sitelinks"
COMPACT_ABOVE_LANGS = 3  # beyond this many languages, one summary line per language
MAX_CHECK_LINES = 2


def _r(x, digits: int = 1):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else round(x, digits)


def _int(x) -> int:
    return 0 if x is None or pd.isna(x) else int(x)


def load_data(ws: Path, basket: Basket) -> pd.DataFrame:
    meta_path, data_path = ws / "fetch_meta.json", ws / "data.csv"
    if not data_path.exists() or not meta_path.exists():
        raise BasketError(f"no fetched data in {ws}; run: wt run {ws.name}")
    if read_json(meta_path).get("basket_hash") != basket_hash(basket):
        raise BasketError(f"basket.json changed since the last fetch; run: wt run {ws.name}")
    return pd.read_csv(data_path, parse_dates=["date"], dtype={"title": str, "lang": str, "qid": str},
                       keep_default_na=False)


def analyze_language(lang: str, rows: pd.DataFrame, articles_meta: list[dict], gaps: list[dict], months: list[str]) -> dict:
    if rows.empty:
        check = trust.check_coverage(lang, None, None, gaps, months)
        return {"basket": None, "articles": [], "checks": [check.to_dict()], "confidence": "Low", "monthly": []}

    views = rows.pivot_table(index="date", columns="title", values="views", aggfunc="sum").sort_index().fillna(0)
    missing = (rows.pivot_table(index="date", columns="title", values="missing", aggfunc="max")
               .sort_index().fillna(0).astype(bool))
    edition = rows.groupby("date")["edition_total"].first().sort_index().astype(float)
    basket_daily = views.sum(axis=1)
    in_window = basket_daily.index.strftime("%Y-%m").isin(months)

    raw_m = window_monthly(basket_daily, months)
    ed_m = window_monthly(edition, months)
    norm_m = normalize(raw_m, ed_m)
    g_norm, method = growth_pct(norm_m)
    g_raw, _ = growth_pct(raw_m)
    tr = trend(norm_m)

    checks = [
        trust.check_spike(basket_daily, edition, months),
        trust.check_concentration(views, edition, months),
        trust.check_edition_effect(g_raw, g_norm),
        trust.check_volume(basket_daily[in_window]),
        trust.check_coverage(lang, views, missing, gaps, months),
        trust.check_significance(tr["p_value"]),
        trust.check_window(basket_daily, edition, months),
    ]

    meta_by_title = {a["title"]: a for a in articles_meta}
    total = raw_m.sum()
    articles = []
    for title in views.columns:
        a_m = window_monthly(views[title], months)
        a_norm = normalize(a_m, ed_m)
        meta = meta_by_title.get(title, {})
        articles.append({
            "qid": meta.get("qid"),
            "label": meta.get("label", title),
            "role": meta.get("role", "core"),
            "title": title,
            "level_norm": _r(a_norm.median(), 2),
            "level_raw": _r(a_m.median(), 0),
            "growth_norm_pct": _r(growth_pct(a_norm)[0]),
            "share_pct": _r(a_m.sum() / total * 100 if total else None),
            "monthly_views": [_int(v) for v in a_m],
        })
    articles.sort(key=lambda a: -(a["share_pct"] or 0))

    return {
        "basket": {
            "level_norm": _r(norm_m.median(), 2),
            "level_raw": _r(raw_m.median(), 0),
            "growth_norm_pct": _r(g_norm),
            "growth_raw_pct": _r(g_raw),
            "growth_method": method,
            "trend_pct_per_year": _r(tr["slope_pct_per_year"]),
            "trend_p": _r(tr["p_value"], 3),
            "seasonality": seasonality_strength(norm_m),
            "median_daily_views": _r(basket_daily[in_window].median(), 0),
        },
        "articles": articles,
        "checks": [c.to_dict() for c in checks],
        "confidence": trust.confidence(checks),
        "monthly": [
            {"month": m, "views": _int(raw_m[m]), "edition_total": _int(ed_m[m]), "norm": _r(norm_m[m], 3)}
            for m in months
        ],
    }


def _pct_ranks(values: list[float | None]) -> list[float]:
    """0 = worst, 1 = best; missing values rank lowest."""
    n = len(values)
    if n == 1:
        return [1.0]
    s = pd.Series([-math.inf if v is None else v for v in values], dtype=float)
    return [float(x) for x in ((s.rank(method="average") - 1) / (n - 1))]


def rank_languages(languages: dict, weights: dict) -> list[dict]:
    langs = list(languages)
    if len(langs) < 2:
        return []
    growth = [(languages[l]["basket"] or {}).get("growth_norm_pct") for l in langs]
    level = [(languages[l]["basket"] or {}).get("level_norm") for l in langs]
    growth_rank, level_rank = _pct_ranks(growth), _pct_ranks(level)
    rows = []
    for i, lang in enumerate(langs):
        conf = languages[lang]["confidence"]
        score = (weights["growth"] * growth_rank[i] + weights["level"] * level_rank[i]
                 + weights["confidence"] * CONFIDENCE_VALUE[conf])
        rows.append({"lang": lang, "score": round(score, 2), "growth_norm_pct": growth[i],
                     "level_norm": level[i], "confidence": conf})
    return sorted(rows, key=lambda r: -r["score"])


def analyze_workspace(ws: Path) -> dict:
    basket = load_basket(ws)
    df = load_data(ws, basket)
    resolved = read_json(ws / "resolved.json")
    meta = read_json(ws / "fetch_meta.json")
    months = basket.months
    languages = {
        lang: analyze_language(
            lang,
            df[df["lang"] == lang],
            [a for a in resolved["articles"] if a["lang"] == lang],
            [g for g in resolved["gaps"] if g["lang"] == lang],
            months,
        )
        for lang in basket.langs
    }
    analysis = {
        "question": basket.question,
        "window": {"start": basket.start, "end": basket.end, "months": len(months)},
        "weights": basket.weights,
        "items": [{"qid": it.qid, "label": it.label, "role": it.role} for it in basket.items],
        "languages": languages,
        "ranking": rank_languages(languages, basket.weights),
        "gaps": resolved["gaps"],
        "provenance": {"source": SOURCE, "retrieved_at": meta["retrieved_at"], "basket_hash": basket_hash(basket)},
    }
    write_json(ws / "analysis.json", analysis)
    return analysis


def summarize(analysis: dict) -> list[str]:
    """Short text summary for the agent (≤17 lines)."""
    w = analysis["window"]
    langs = analysis["languages"]
    method = next((d["basket"]["growth_method"] for d in langs.values() if d["basket"]), "yoy_12m")
    lines = [f"Window {w['start']}..{w['end']} ({w['months']} months); growth = share of edition views, "
             f"{GROWTH_METHOD_TEXT[method]}"]
    compact = len(langs) > COMPACT_ABOVE_LANGS
    for lang, d in langs.items():
        b = d["basket"]
        if b is None:
            lines.append(f"{lang}: no articles found | confidence Low")
            continue
        p = "n/a" if b["trend_p"] is None else b["trend_p"]
        line = (f"{lang}: level {fmt_num(b['level_norm'], 2)}/M views ({fmt_num(b['level_raw'], 0)} views/mo) | "
                f"growth {fmt_pct(b['growth_norm_pct'])} (raw {fmt_pct(b['growth_raw_pct'])}) | "
                f"trend {fmt_pct(b['trend_pct_per_year'])}/yr p={p} | confidence {d['confidence']}")
        flagged = [c for c in d["checks"] if c["status"] != "pass"]
        if compact:
            lines.append(line + (f" | {len(flagged)} check(s) flagged" if flagged else ""))
            continue
        lines.append(line)
        lines += [f"  {c['status']} {c['name']}: {c['reason']}" for c in flagged[:MAX_CHECK_LINES]]
        if len(flagged) > MAX_CHECK_LINES:
            lines.append(f"  (+{len(flagged) - MAX_CHECK_LINES} more in analysis.json)")
    if analysis["ranking"]:
        wts = analysis["weights"]
        lines.append(
            f"Ranking (weights growth {wts['growth']}, level {wts['level']}, confidence {wts['confidence']}): "
            + " > ".join(f"{r['lang']} {r['score']:.2f}" for r in analysis["ranking"])
        )
    return lines
