import json

import pytest

from synth import build_workspace, const, exp_growth, seasonal, with_spike
from wiki_trends.analyze import analyze_workspace, rank_languages, summarize
from wiki_trends.workspace import BasketError

ED = const(1e7)


def one_lang(articles, edition=ED, lang="uk"):
    return {lang: {"edition": edition, "articles": articles}}


def statuses(a, lang="uk"):
    return {c["name"]: c["status"] for c in a["languages"][lang]["checks"]}


def test_steady_growth_is_high_confidence(tmp_path):
    ws = build_workspace(tmp_path, one_lang({t: exp_growth(100, 0.03) for t in "ABC"}))
    a = analyze_workspace(ws)
    b = a["languages"]["uk"]["basket"]
    assert b["growth_norm_pct"] == pytest.approx(42.6, abs=1.5)
    assert b["growth_method"] == "yoy_12m"
    assert b["trend_p"] < 0.01
    assert set(statuses(a).values()) == {"pass"}
    assert a["languages"]["uk"]["confidence"] == "High"
    assert a["ranking"] == []
    assert json.loads((ws / "analysis.json").read_text())["window"] == {"start": "2023-01", "end": "2024-12", "months": 24}


def test_flat_series(tmp_path):
    a = analyze_workspace(build_workspace(tmp_path, one_lang({t: const(200) for t in "ABC"})))
    assert abs(a["languages"]["uk"]["basket"]["growth_norm_pct"]) < 1
    assert a["languages"]["uk"]["confidence"] == "High"


def test_single_spike_is_low_confidence(tmp_path):
    arts = {"A": with_spike(const(100), "2024-06-15", 200_000), "B": const(100), "C": const(100)}
    a = analyze_workspace(build_workspace(tmp_path, one_lang(arts)))
    assert a["languages"]["uk"]["basket"]["growth_norm_pct"] > 100
    assert statuses(a)["spike_dependence"] == "fail"
    assert a["languages"]["uk"]["confidence"] == "Low"


def test_seasonal_only(tmp_path):
    a = analyze_workspace(build_workspace(tmp_path, one_lang({t: seasonal(200, 0.5) for t in "ABC"})))
    b = a["languages"]["uk"]["basket"]
    assert abs(b["growth_norm_pct"]) < 5
    assert b["seasonality"] > 0.8


def test_edition_wide_growth_warns(tmp_path):
    spec = one_lang({t: exp_growth(100, 0.015) for t in "ABC"}, edition=exp_growth(1e7, 0.04))
    a = analyze_workspace(build_workspace(tmp_path, spec))
    b = a["languages"]["uk"]["basket"]
    assert b["growth_raw_pct"] > 10 and b["growth_norm_pct"] < -10
    assert statuses(a)["edition_effect"] == "warn"


def test_one_article_carries_growth(tmp_path):
    arts = {"A": const(100), "B": const(100), "C": exp_growth(20, 0.08)}
    a = analyze_workspace(build_workspace(tmp_path, one_lang(arts)))
    assert statuses(a)["article_concentration"] == "fail"
    shares = [x["share_pct"] for x in a["languages"]["uk"]["articles"]]
    assert shares == sorted(shares, reverse=True)
    assert len(a["languages"]["uk"]["articles"][0]["monthly_views"]) == 24


def test_low_volume_is_low_confidence(tmp_path):
    a = analyze_workspace(build_workspace(tmp_path, one_lang({"A": const(3)})))
    assert statuses(a)["low_volume"] == "fail"
    assert a["languages"]["uk"]["confidence"] == "Low"


def test_language_without_articles(tmp_path):
    gap = {"lang": "cs", "qid": "Q100", "label": "a", "role": "core"}
    ws = build_workspace(tmp_path, one_lang({"A": exp_growth(100, 0.03)}, lang="pl"), extra_langs=("cs",), gaps=[gap])
    a = analyze_workspace(ws)
    cs = a["languages"]["cs"]
    assert cs["basket"] is None and cs["confidence"] == "Low"
    assert cs["checks"][0]["name"] == "coverage" and cs["checks"][0]["status"] == "fail"
    assert [r["lang"] for r in a["ranking"]] == ["pl", "cs"]


def test_ranking_prefers_growing_bigger_language(tmp_path):
    spec = {
        "pl": {"edition": ED, "articles": {t: exp_growth(1000, 0.03) for t in "ABC"}},
        "cs": {"edition": ED, "articles": {t: const(60) for t in "ABC"}},
    }
    a = analyze_workspace(build_workspace(tmp_path, spec))
    assert a["ranking"][0]["lang"] == "pl"
    assert a["ranking"][0]["score"] > a["ranking"][1]["score"]


def test_rank_languages_weights():
    langs = {
        "a": {"basket": {"growth_norm_pct": 50.0, "level_norm": 1.0}, "confidence": "High"},
        "b": {"basket": {"growth_norm_pct": 5.0, "level_norm": 100.0}, "confidence": "High"},
    }
    by_growth = rank_languages(langs, {"growth": 1.0, "level": 0.0, "confidence": 0.0})
    by_level = rank_languages(langs, {"growth": 0.0, "level": 1.0, "confidence": 0.0})
    assert by_growth[0]["lang"] == "a" and by_level[0]["lang"] == "b"


def test_analyze_rejects_stale_fetch(tmp_path):
    ws = build_workspace(tmp_path, one_lang({"A": const(100)}))
    b = json.loads((ws / "basket.json").read_text())
    b["start"] = "2023-02"
    (ws / "basket.json").write_text(json.dumps(b))
    with pytest.raises(BasketError, match="wt run"):
        analyze_workspace(ws)


def test_summary_is_short_even_with_many_languages(tmp_path):
    spec = {lang: {"edition": ED, "articles": {t: const(100) for t in "AB"}} for lang in ["pl", "cs", "sk", "uk", "de", "fr"]}
    a = analyze_workspace(build_workspace(tmp_path, spec))
    lines = summarize(a)
    assert len(lines) <= 17
    assert lines[-1].startswith("Ranking (weights growth 0.4, level 0.4, confidence 0.2)")


def test_summary_lists_flagged_checks(tmp_path):
    arts = {"A": with_spike(const(100), "2024-06-15", 200_000), "B": const(100), "C": const(100)}
    lines = summarize(analyze_workspace(build_workspace(tmp_path, one_lang(arts))))
    assert any(line.strip().startswith("fail spike_dependence") for line in lines)
    assert "confidence Low" in lines[1]


def test_ranking_uses_growth_and_level_magnitudes_not_just_order():
    langs = {
        "pl": {"basket": {"growth_norm_pct": -40.0, "level_norm": 50.0}, "confidence": "High"},
        "cs": {"basket": {"growth_norm_pct": 35.0, "level_norm": 49.0}, "confidence": "Medium"},
    }
    ranking = rank_languages(langs, {"growth": 0.4, "level": 0.4, "confidence": 0.2})
    assert ranking[0]["lang"] == "cs"
