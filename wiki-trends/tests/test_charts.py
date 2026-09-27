from synth import build_workspace, const, exp_growth
from wiki_trends.analyze import analyze_workspace
from wiki_trends.charts import render_charts

ED = const(1e7)


def spec(langs):
    return {lang: {"edition": ED, "articles": {"A": exp_growth(100, 0.03), "B": const(50)}} for lang in langs}


def test_multi_language_charts(tmp_path):
    ws = build_workspace(tmp_path, spec(["pl", "cs"]))
    paths = render_charts(ws, analyze_workspace(ws))
    assert [p.name for p in paths] == ["trend.png", "articles.png", "ranking.png"]
    assert all(p.exists() and p.stat().st_size > 5_000 for p in paths)


def test_single_language_has_no_ranking_chart(tmp_path):
    ws = build_workspace(tmp_path, spec(["uk"]))
    assert [p.name for p in render_charts(ws, analyze_workspace(ws))] == ["trend.png", "articles.png"]


def test_language_without_data_still_renders(tmp_path):
    gap = {"lang": "cs", "qid": "Q900", "label": "x", "role": "core"}
    ws = build_workspace(tmp_path, spec(["pl"]), extra_langs=("cs",), gaps=[gap])
    assert len(render_charts(ws, analyze_workspace(ws))) == 3


def test_no_data_at_all(tmp_path):
    analysis = {
        "weights": {"growth": 0.4, "level": 0.4, "confidence": 0.2},
        "languages": {"cs": {"basket": None, "articles": [], "checks": [], "confidence": "Low", "monthly": []}},
        "ranking": [],
    }
    assert [p.name for p in render_charts(tmp_path, analysis)] == ["trend.png", "articles.png"]
