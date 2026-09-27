import pytest
from pypdf import PdfReader

from synth import build_workspace, const, exp_growth, narrative_for
from wiki_trends.analyze import analyze_workspace
from wiki_trends.check import check_workspace
from wiki_trends.report import ReportError, limitations, report_workspace

ED = const(1e7)


def ready_ws(tmp_path, spec=None, narrate="uk", **kw):
    spec = spec or {"uk": {"edition": ED, "articles": {t: exp_growth(100, 0.03) for t in "ABC"}}}
    ws = build_workspace(tmp_path, spec, **kw)
    analysis = analyze_workspace(ws)
    (ws / "narrative.md").write_text(narrative_for(analysis, narrate), encoding="utf-8")
    return ws, analysis


def pdf(path):
    reader = PdfReader(path)
    return len(reader.pages), "\n".join(p.extract_text() for p in reader.pages)


def test_report_is_one_page_with_all_sections(tmp_path):
    ws, _ = ready_ws(tmp_path)
    assert check_workspace(ws) == []
    pages, text = pdf(report_workspace(ws))
    assert pages == 1
    for heading in ("Findings", "By language", "Recommendation", "Trust checks", "Assumptions & limitations"):
        assert heading in text
    assert "Interest in the topic on uk Wikipedia" in text
    assert "UNCHECKED" not in text


def test_report_refuses_without_check(tmp_path):
    ws, _ = ready_ws(tmp_path)
    with pytest.raises(ReportError, match="wt check"):
        report_workspace(ws)


def test_report_refuses_after_narrative_edit(tmp_path):
    ws, _ = ready_ws(tmp_path)
    assert check_workspace(ws) == []
    (ws / "narrative.md").write_text((ws / "narrative.md").read_text() + "\nExtra line.\n", encoding="utf-8")
    with pytest.raises(ReportError):
        report_workspace(ws)


def test_force_stamps_unchecked(tmp_path):
    ws, _ = ready_ws(tmp_path)
    _, text = pdf(report_workspace(ws, force=True))
    assert "UNCHECKED DRAFT" in text


def test_eight_languages_still_one_page(tmp_path):
    langs = ["pl", "cs", "sk", "uk", "de", "fr", "es", "pt"]
    spec = {lang: {"edition": ED, "articles": {t: exp_growth(100 + i * 50, 0.01 * i) for t in "ABC"}}
            for i, lang in enumerate(langs)}
    ws, _ = ready_ws(tmp_path, spec, narrate="pl")
    assert check_workspace(ws) == []
    assert pdf(report_workspace(ws))[0] == 1


def test_limitations_cover_window_gaps_and_low_confidence(tmp_path):
    gap = {"lang": "cs", "qid": "Q900", "label": "telescope", "role": "related"}
    ws = build_workspace(tmp_path, {"pl": {"edition": ED, "articles": {"A": const(3)}}},
                         start="2024-01", end="2024-12", extra_langs=("cs",), gaps=[gap])
    text = " ".join(limitations(analyze_workspace(ws)))
    assert "agent=user" in text and "redirects" in text and "willingness to pay" in text
    assert "halves of the window" in text
    assert "cs: telescope" in text
    assert "low confidence" in text


def _edit_basket(ws):
    import json
    b = json.loads((ws / "basket.json").read_text())
    b["start"] = "2023-02"
    (ws / "basket.json").write_text(json.dumps(b))


def test_check_rejects_analysis_for_an_older_basket(tmp_path):
    ws, _ = ready_ws(tmp_path)
    _edit_basket(ws)
    assert any("basket.json changed" in str(i) and "wt run" in str(i) for i in check_workspace(ws))


def test_report_rejects_analysis_for_an_older_basket(tmp_path):
    ws, _ = ready_ws(tmp_path)
    assert check_workspace(ws) == []
    _edit_basket(ws)
    with pytest.raises(ReportError, match="basket.json changed"):
        report_workspace(ws)


def test_report_redraws_a_stale_chart(tmp_path):
    ws, analysis = ready_ws(tmp_path)
    (ws / "charts").mkdir(exist_ok=True)
    (ws / "charts" / "trend.png").write_bytes(b"chart from an older run")
    assert check_workspace(ws) == []
    report_workspace(ws)
    assert (ws / "charts" / "trend.png").read_bytes()[:4] == b"\x89PNG"


def test_heaviest_report_stays_above_the_footer(tmp_path):
    import matplotlib.pyplot as plt
    from wiki_trends.report import FOOTER_TOP, fit_layout

    langs = ["pl", "cs", "sk", "uk", "de", "fr", "es", "pt"]
    spec = {lang: {"edition": ED, "articles": {"A": const(3), "B": exp_growth(20, 0.01 * i)}}
            for i, lang in enumerate(langs)}
    gaps = [{"lang": lang, "qid": "Q900", "label": "a missing related topic", "role": "related"} for lang in langs]
    ws = build_workspace(tmp_path, spec, gaps=gaps)
    analysis = analyze_workspace(ws)
    long = "word " * 26  # 15 + 5 × 26 + 80 = 225 words, inside check's 230-word limit
    text = ("# " + "headline " * 15 + "\n\n" + "".join(f"- {long}\n" for _ in range(5))
            + "\n## Recommendation\n\n" + "advice " * 80 + "\n")
    fig, bottom = fit_layout(ws, analysis, text)
    plt.close(fig)
    assert bottom >= FOOTER_TOP
