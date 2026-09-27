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
