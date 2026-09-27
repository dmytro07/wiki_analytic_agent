import json

import pytest

from fakes import FakeWiki
from wiki_trends.api import WikiClient
from wiki_trends.resolve import resolve_workspace, search
from wiki_trends.workspace import BasketError, basket_hash, load_basket


def write_basket(ws, **over):
    ws.mkdir(parents=True, exist_ok=True)
    b = {
        "question": "q",
        "langs": ["uk", "cs"],
        "start": "2024-01",
        "end": "2024-06",
        "items": [
            {"qid": "Q333", "label": "astronomy", "role": "core"},
            {"qid": "Q4213", "label": "telescope", "role": "related"},
        ],
    }
    b.update(over)
    (ws / "basket.json").write_text(json.dumps(b, ensure_ascii=False))
    return ws


FAKE = FakeWiki(
    {"Q333": {"uk": "Астрономія", "cs": "Astronomie"}, "Q4213": {"uk": "Телескоп"}},
    search_results=[("Q333", "astronomy", "scientific study of celestial objects")],
)


def client():
    return WikiClient(transport=FAKE, sleep=lambda s: None)


def test_search():
    assert search(client(), "astronomy", "en")[0]["qid"] == "Q333"


def test_resolve_articles_and_gaps(tmp_path):
    ws = write_basket(tmp_path / "ws")
    out = resolve_workspace(ws, client())
    assert {(a["lang"], a["title"]) for a in out["articles"]} == {("uk", "Астрономія"), ("cs", "Astronomie"), ("uk", "Телескоп")}
    assert out["gaps"] == [{"lang": "cs", "qid": "Q4213", "label": "telescope", "role": "related"}]
    saved = json.loads((ws / "resolved.json").read_text())
    assert saved["basket_hash"] == basket_hash(load_basket(ws))


def test_title_override_wins(tmp_path):
    ws = write_basket(tmp_path / "ws", title_overrides={"cs:Q4213": "Dalekohled"})
    out = resolve_workspace(ws, client())
    over = [a for a in out["articles"] if a["lang"] == "cs" and a["qid"] == "Q4213"]
    assert over == [{"lang": "cs", "qid": "Q4213", "label": "telescope", "role": "related", "title": "Dalekohled", "source": "override"}]
    assert out["gaps"] == []


def test_unknown_qid_is_actionable(tmp_path):
    ws = write_basket(tmp_path / "ws", items=[{"qid": "Q123456789", "label": "nonsense"}])
    with pytest.raises(BasketError, match=r"Q123456789.*resolve --search"):
        resolve_workspace(ws, client())
