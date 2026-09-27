import json
import re
from datetime import date

import pytest

from wiki_trends import workspace as w
from wiki_trends.fmt import fmt_num, fmt_pct


def valid(**over):
    d = {
        "question": "q",
        "langs": ["uk"],
        "start": "2023-09",
        "end": "2025-08",
        "items": [{"qid": "Q333", "label": "astronomy", "role": "core"}],
    }
    d.update(over)
    return d


def test_fmt():
    assert fmt_pct(18.24) == "+18.2%"
    assert fmt_pct(None) == "n/a"
    assert fmt_num(1720.4, 0) == "1,720"
    assert fmt_num(41.3, 2) == "41.30"


def test_month_arithmetic():
    assert w.shift_month("2024-01", -1) == "2023-12"
    assert w.shift_month("2023-11", 3) == "2024-02"
    assert w.months_between("2023-11", "2024-02") == ["2023-11", "2023-12", "2024-01", "2024-02"]
    assert w.month_end("2024-02") == date(2024, 2, 29)
    assert w.month_start("2024-02") == date(2024, 2, 1)


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2025, 9, 27), "2025-08"),
        (date(2025, 9, 2), "2025-08"),
        (date(2025, 9, 1), "2025-07"),  # Aug 31 may not be published yet
    ],
)
def test_last_complete_month(today, expected):
    assert w.last_complete_month(today) == expected


def test_basket_defaults():
    b = w.basket_from_dict(valid())
    assert b.weights == w.DEFAULT_WEIGHTS
    assert b.title_overrides == {}
    assert len(b.months) == 24
    assert b.items[0] == w.Item("Q333", "astronomy", "core")


@pytest.mark.parametrize(
    "over,field",
    [
        ({"langs": []}, "langs"),
        ({"langs": ["Polish"]}, "langs"),
        ({"langs": ["pl", "pl"]}, "langs"),
        ({"start": "2023-13"}, "start"),
        ({"start": "2025-09"}, "start"),
        ({"start": "2014-01"}, "start"),
        ({"start": "2025-06"}, "start"),
        ({"items": []}, "items"),
        ({"items": [{"qid": "333"}]}, "items[0].qid"),
        ({"items": [{"qid": "Q1", "role": "main"}]}, "items[0].role"),
        ({"items": [{"qid": "Q1"}, {"qid": "Q1"}]}, "items[1].qid"),
        ({"weights": {"growth": 0.5, "level": 0.5, "confidence": 0.5}}, "weights"),
        ({"weights": {"growth": 1.0}}, "weights"),
        ({"title_overrides": {"uk-Q333": "X"}}, "title_overrides"),
    ],
)
def test_basket_errors_name_the_field(over, field):
    with pytest.raises(w.BasketError, match=re.escape(field)):
        w.basket_from_dict(valid(**over))


def test_basket_missing_field():
    d = valid()
    del d["question"]
    with pytest.raises(w.BasketError, match="question"):
        w.basket_from_dict(d)


def test_validate_dates():
    b = w.basket_from_dict(valid(end="2025-09"))
    with pytest.raises(w.BasketError, match=r"'end'.*2025-08"):
        w.validate_dates(b, date(2025, 9, 27))
    w.validate_dates(w.basket_from_dict(valid()), date(2025, 9, 27))


def test_basket_hash_changes_with_content():
    a = w.basket_from_dict(valid())
    b = w.basket_from_dict(valid(langs=["uk", "pl"]))
    assert w.basket_hash(a) == w.basket_hash(w.basket_from_dict(valid()))
    assert w.basket_hash(a) != w.basket_hash(b)


def test_init_workspace_and_lookup(tmp_path):
    ws = w.init_workspace("Astronomy UK!", date(2025, 9, 27), cwd=tmp_path)
    assert ws == tmp_path / "wiki-trends-work" / "astronomy-uk"
    template = json.loads((ws / "basket.json").read_text())
    assert (template["start"], template["end"]) == ("2023-09", "2025-08")
    assert w.resolve_workspace_path("astronomy-uk", cwd=tmp_path) == ws
    assert w.resolve_workspace_path(str(ws), cwd=tmp_path) == ws
    with pytest.raises(w.BasketError, match="already exists"):
        w.init_workspace("astronomy-uk", date(2025, 9, 27), cwd=tmp_path)
    with pytest.raises(w.BasketError, match="No workspace"):
        w.resolve_workspace_path("nope", cwd=tmp_path)


def test_template_basket_explains_what_to_fill(tmp_path):
    ws = w.init_workspace("t", date(2025, 9, 27), cwd=tmp_path)
    with pytest.raises(w.BasketError, match="langs"):
        w.load_basket(ws)


def test_load_basket_bad_json(tmp_path):
    (tmp_path / "basket.json").write_text("{not json")
    with pytest.raises(w.BasketError, match="not valid JSON"):
        w.load_basket(tmp_path)


def test_run_history_and_diff(tmp_path):
    b1 = w.basket_from_dict(valid()).to_dict()
    b2 = w.basket_from_dict(
        valid(langs=["uk", "pl"], start="2022-09", items=[{"qid": "Q333", "label": "astronomy"}, {"qid": "Q4213", "label": "telescope"}])
    ).to_dict()
    s1 = {"basket": b1, "headline": {"uk": {"growth_norm_pct": 10.0, "confidence": "High"}}}
    s2 = {"basket": b2, "headline": {"uk": {"growth_norm_pct": 4.0, "confidence": "Medium"}, "pl": {"growth_norm_pct": 1.0, "confidence": "Low"}}}
    assert w.record_run(tmp_path, s1) is None
    prev = w.record_run(tmp_path, s2)
    assert prev == s1
    assert (tmp_path / "history" / "run-002.json").exists()
    diff = w.diff_snapshots(prev, s2)
    assert "window: 2023-09..2025-08 -> 2022-09..2025-08" in diff
    assert "languages added: pl" in diff
    assert "items added: telescope (Q4213)" in diff
    assert "uk: growth +10.0% -> +4.0%, confidence High -> Medium" in diff
    assert w.diff_snapshots(None, s2) == []
