import json

from wiki_trends.check import check_narrative, check_workspace, parse_narrative
from wiki_trends.langs import mentions
from wiki_trends.workspace import file_sha, text_sha


def lang(conf, growth, p, level=10.0, raw=1000.0, median=100.0):
    return {
        "basket": {"level_norm": level, "level_raw": raw, "growth_norm_pct": growth, "growth_raw_pct": -2.0,
                   "growth_method": "yoy_12m", "trend_pct_per_year": 15.1, "trend_p": p, "seasonality": 0.1,
                   "median_daily_views": median},
        "articles": [], "checks": [], "confidence": conf,
        "monthly": [{"month": "2024-01", "views": 987654, "edition_total": 1, "norm": 1.0}],
    }


ANALYSIS = {
    "question": "q",
    "window": {"start": "2023-09", "end": "2025-08", "months": 24},
    "weights": {"growth": 0.4, "level": 0.4, "confidence": 0.2},
    "items": [],
    "languages": {
        "pl": lang("High", 18.2, 0.004, level=41.3, raw=52310.0, median=1720.0),
        "cs": lang("Low", 3.1, 0.41, level=12.0),
    },
    "ranking": [
        {"lang": "pl", "score": 0.96, "growth_norm_pct": 18.2, "level_norm": 41.3, "confidence": "High"},
        {"lang": "cs", "score": 0.1, "growth_norm_pct": 3.1, "level_norm": 12.0, "confidence": "Low"},
    ],
    "gaps": [],
    "provenance": {},
}

GOOD = """# Polish interest in intermittent fasting is growing; Czech is flat

- Polish: +18.2% share of views year over year, significant trend (p=0.004).
- Czech: +3.1%, not statistically significant (p=0.41).
- Polish level is 41.3 views per million vs 12.0 for Czech.

## Recommendation

Research Polish users next. Czech is tentative: low confidence, revisit later.
"""


def messages(text, analysis=ANALYSIS):
    return [str(i) for i in check_narrative(text, analysis)]


def test_good_narrative_passes():
    assert messages(GOOD) == []


def test_parse_narrative():
    n = parse_narrative(GOOD)
    assert n.headline == (1, "Polish interest in intermittent fasting is growing; Czech is flat")
    assert [line for line, _ in n.findings] == [3, 4, 5]
    assert n.recommendation.startswith("Research Polish") and n.recommendation_line == 7


def test_wrong_number_rejected():
    out = messages(GOOD.replace("+18.2%", "+25%"))
    assert len(out) == 1 and out[0].startswith("line 3:") and "'+25%'" in out[0]


def test_number_formats_accepted():
    extra = "- Polish median is 1,720 daily views, 52,310 per month, raw −2.0% since 2023 (2023-09 to 2025-08, 24 months).\n"
    text = GOOD.replace("\n## Recommendation", extra + "\n## Recommendation")
    assert messages(text) == []


def test_monthly_values_are_not_sources():
    text = GOOD.replace("\n## Recommendation", "- Peak month had 987,654 views.\n\n## Recommendation")
    assert any("987,654" in m for m in messages(text))


def test_unqualified_growth_for_nonsignificant_language():
    text = GOOD.replace("- Czech: +3.1%, not statistically significant (p=0.41).", "- Czech interest is growing too (+3.1%).")
    out = messages(text)
    assert len(out) == 1 and "Czech" in out[0] and "not statistically significant" in out[0]


def test_qualified_growth_is_fine():
    text = GOOD.replace("- Czech: +3.1%, not statistically significant (p=0.41).",
                        "- Czech interest may be growing (+3.1%), but the trend is not statistically significant.")
    assert messages(text) == []


def test_low_confidence_needs_caveat():
    text = GOOD.replace("Research Polish users next. Czech is tentative: low confidence, revisit later.",
                        "Research Polish and Czech users next.")
    out = messages(text)
    assert len(out) == 1 and "Czech" in out[0] and "Low" in out[0]


def test_single_low_language_needs_caveat_even_unnamed():
    analysis = {**ANALYSIS, "languages": {"cs": ANALYSIS["languages"]["cs"]}, "ranking": []}
    text = """# Czech fasting interest

- Czech: +3.1%, not statistically significant (p=0.41).
- Level is 12.0 views per million.
- Few articles cover it.

## Recommendation

Build the course next.
"""
    assert any("Low" in m for m in messages(text, analysis))


def test_structure_limits():
    too_long = "# " + " ".join(["word"] * 16) + "\n\n- a\n- b\n\n"
    out = " | ".join(messages(too_long))
    assert "headline has 16 words" in out
    assert "2 findings" in out
    assert "missing '## Recommendation'" in out
    huge = GOOD.replace("revisit later.", "revisit later. " + " ".join(["filler"] * 200))
    out = " | ".join(messages(huge))
    assert "recommendation has" in out and "narrative has" in out


def test_language_mentions():
    assert mentions("Polish readers", "pl")
    assert mentions("on ukwiki", "uk")
    assert not mentions("It is growing", "it")
    assert mentions("itwiki grew", "it") and mentions("Italian grew", "it")


def test_check_workspace_records_result(tmp_path):
    (tmp_path / "analysis.json").write_text(json.dumps(ANALYSIS))
    assert [str(i) for i in check_workspace(tmp_path)] == ["narrative.md not found; write it following reference/report-guide.md"]
    (tmp_path / "narrative.md").write_text(GOOD, encoding="utf-8")
    assert check_workspace(tmp_path) == []
    status = json.loads((tmp_path / "check.json").read_text())
    assert status["passed"] is True
    assert status["narrative_sha"] == text_sha(GOOD)
    assert status["analysis_sha"] == file_sha(tmp_path / "analysis.json")
