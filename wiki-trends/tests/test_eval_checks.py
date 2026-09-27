import json

from evals.checks import grade, merge, parse_stream
from synth import build_workspace, const, exp_growth, narrative_for
from wiki_trends.analyze import analyze_workspace
from wiki_trends.check import check_workspace
from wiki_trends.report import report_workspace

CASE = {"id": "x", "turns": ["q"], "expect_langs": ["uk"]}


def stream(commands, final, session="s1"):
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": session})]
    for c in commands:
        lines.append(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": c}}]}}))
    lines.append(json.dumps({"type": "result", "result": final, "session_id": session,
                             "total_cost_usd": 0.01, "duration_ms": 2000}))
    return lines


def finished_workdir(tmp_path):
    root = tmp_path / "wd" / "wiki-trends-work"
    root.mkdir(parents=True)
    spec = {"uk": {"edition": const(1e7), "articles": {t: exp_growth(100, 0.03) for t in "ABC"}}}
    ws = build_workspace(root, spec, name="astro")
    analysis = analyze_workspace(ws)
    (ws / "narrative.md").write_text(narrative_for(analysis, "uk"), encoding="utf-8")
    assert check_workspace(ws) == []
    report_workspace(ws)
    return tmp_path / "wd"


def by_name(results):
    return {r.name: r for r in results}


def test_parse_stream_and_merge():
    t = parse_stream(stream(["/s/scripts/wt run astro"], "done") + ["not json"])
    assert (t.session_id, t.final_text, len(t.tool_calls), t.cost_usd, t.duration_s) == ("s1", "done", 1, 0.01, 2.0)
    m = merge([t, parse_stream(stream(["/s/scripts/wt check astro"], "second"))])
    assert len(m.tool_calls) == 2 and m.final_text == "second" and m.cost_usd == 0.02


def test_grade_good_run(tmp_path):
    wd = finished_workdir(tmp_path)
    final = "Interest is growing, high confidence. Limitation: pageviews are not willingness to pay."
    results = by_name(grade(parse_stream(stream(["/s/scripts/wt run astro"], final)), wd, CASE))
    assert set(results) == {"used_cli", "no_own_fetch", "basket_valid", "langs_match", "report_one_page",
                            "check_passes", "states_confidence", "confidence_matches", "mentions_limitations"}
    assert all(r.passed for r in results.values()), [r for r in results.values() if not r.passed]


def test_grade_catches_bad_run(tmp_path):
    wd = finished_workdir(tmp_path)
    t = parse_stream(stream(["curl https://wikimedia.org/api/rest_v1/metrics/pageviews/x", "cat wiki-trends-work/a"], "Low confidence."))
    results = by_name(grade(t, wd, {**CASE, "expect_langs": ["pl"], "must_mention_any": ["planet"]}))
    for name in ("used_cli", "no_own_fetch", "langs_match", "confidence_matches", "mentions_limitations", "must_mention_any"):
        assert not results[name].passed, name


def test_grade_without_workspace(tmp_path):
    results = by_name(grade(parse_stream(stream([], "")), tmp_path, CASE))
    assert not results["basket_valid"].passed and not results["report_one_page"].passed
    assert not results["check_passes"].passed


def test_expect_reuse_needs_second_run(tmp_path):
    wd = finished_workdir(tmp_path)
    results = by_name(grade(parse_stream(stream([], "")), wd, {**CASE, "expect_reuse": True}))
    assert not results["reused_workspace"].passed
