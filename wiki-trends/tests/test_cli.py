import json
import os
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from fakes import FakeWiki
from synth import narrative_for
from wiki_trends import cli
from wiki_trends.api import WikiClient
from wiki_trends.cache import Cache

SKILL_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = FakeWiki(
        {"Q333": {"uk": "Астрономія", "pl": "Astronomia"}, "Q4213": {"uk": "Телескоп"}},
        article_views=lambda lang, title, d: int(100 * 1.03 ** ((d - date(2023, 1, 1)).days / 30.44)),
        edition_views=lambda lang, d: 10_000_000,
        search_results=[("Q333", "astronomy", "scientific study of celestial objects")],
    )
    cache = Cache(tmp_path / "cache.sqlite")
    monkeypatch.setattr(cli, "make_client", lambda: WikiClient(transport=fake, sleep=lambda s: None))
    monkeypatch.setattr(cli, "make_cache", lambda: cache)
    monkeypatch.setattr(cli, "today", lambda: date(2025, 9, 27))
    monkeypatch.setattr(cli, "now", lambda: datetime(2025, 9, 27, 10, 0, tzinfo=timezone.utc))
    monkeypatch.chdir(tmp_path)
    return fake, tmp_path / "wiki-trends-work" / "astro"


def edit_basket(ws, **fields):
    b = json.loads((ws / "basket.json").read_text())
    b.update(fields)
    (ws / "basket.json").write_text(json.dumps(b, ensure_ascii=False))


ITEMS = [{"qid": "Q333", "label": "astronomy", "role": "core"}, {"qid": "Q4213", "label": "telescope", "role": "related"}]


def test_end_to_end_workflow(env, capsys):
    fake, ws = env
    assert cli.main(["init", "astro"]) == 0
    edit_basket(ws, question="Is astronomy interest growing on ukwiki?", langs=["uk"], items=ITEMS)
    capsys.readouterr()

    assert cli.main(["run", "astro"]) == 0
    out = capsys.readouterr().out
    assert "confidence" in out and "Next: write" in out
    assert len(out.strip().splitlines()) <= 20

    calls = len(fake.calls)
    assert cli.main(["run", "astro"]) == 0
    out = capsys.readouterr().out
    assert "0 API request(s)" in out
    assert len(fake.calls) == calls + 1  # only the Wikidata sitelinks lookup

    assert cli.main(["check", "astro"]) == 1
    assert "narrative.md not found" in capsys.readouterr().out
    analysis = json.loads((ws / "analysis.json").read_text())
    (ws / "narrative.md").write_text(narrative_for(analysis, "uk"), encoding="utf-8")
    assert cli.main(["check", "astro"]) == 0
    assert cli.main(["report", "astro"]) == 0
    assert (ws / "report.pdf").exists()


def test_follow_up_reports_changes(env, capsys):
    _, ws = env
    cli.main(["init", "astro"])
    edit_basket(ws, question="q", langs=["uk"], items=ITEMS)
    cli.main(["run", "astro"])
    edit_basket(ws, langs=["uk", "pl"])
    capsys.readouterr()
    assert cli.main(["run", "astro"]) == 0
    out = capsys.readouterr().out
    assert "Changes since previous run: languages added: pl" in out
    assert "Missing: pl:telescope" in out


def test_search(env, capsys):
    assert cli.main(["resolve", "--search", "astronomy", "--lang", "en"]) == 0
    assert "Q333\tastronomy" in capsys.readouterr().out


def test_json_output(env, capsys):
    _, ws = env
    cli.main(["init", "astro"])
    edit_basket(ws, question="q", langs=["uk"], items=ITEMS)
    cli.main(["run", "astro"])
    capsys.readouterr()
    assert cli.main(["analyze", "astro", "--json"]) == 0
    assert "uk" in json.loads(capsys.readouterr().out)["languages"]


def test_errors_are_one_actionable_line(env, capsys):
    cli.main(["init", "astro"])
    capsys.readouterr()
    assert cli.main(["run", "astro"]) == 2
    err = capsys.readouterr().err.strip()
    assert err.startswith("error: basket.json:") and "langs" in err and len(err.splitlines()) == 1
    assert cli.main(["run", "nope"]) == 2
    assert "wt init" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_wrapper_script_runs_from_any_directory(tmp_path):
    proc = subprocess.run([str(SKILL_DIR / "scripts" / "wt"), "--help"], cwd=tmp_path,
                          capture_output=True, text=True, timeout=300, env={**os.environ})
    assert proc.returncode == 0, proc.stderr
    assert "wiki-trends" in proc.stdout and "run" in proc.stdout
