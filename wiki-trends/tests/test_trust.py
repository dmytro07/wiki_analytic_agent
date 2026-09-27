import numpy as np
import pandas as pd

from wiki_trends import trust
from wiki_trends.trust import Check
from wiki_trends.workspace import months_between

DAYS = pd.date_range("2022-10-01", "2025-03-31")
MONTHS = months_between("2023-01", "2024-12")
ED = pd.Series(1e7, index=DAYS)


def daily(values):
    return pd.Series(np.asarray(values, dtype=float), index=DAYS)


def const(v):
    return daily(np.full(len(DAYS), v))


def growing(v0=100.0, rate=0.03):
    return daily(v0 * (1 + rate) ** (np.arange(len(DAYS)) / 30.44))


def by_month(values_by_month: dict):
    """Daily series whose value per day is set per month; months not listed use 100."""
    return daily([values_by_month.get(d.strftime("%Y-%m"), 100.0) for d in DAYS])


def test_spike_pass_on_steady_growth():
    assert trust.check_spike(growing(), ED, MONTHS).status == "pass"


def test_spike_fail_when_growth_is_one_day():
    s = const(300)
    s[pd.Timestamp("2024-06-15")] += 200_000
    c = trust.check_spike(s, ED, MONTHS)
    assert c.status == "fail" and "spike" in c.reason


def test_spike_warn_when_growth_halves():
    s = by_month({m: 110.0 for m in months_between("2024-01", "2025-03")})
    s[pd.Timestamp("2024-06-15")] += 5_400
    assert trust.check_spike(s, ED, MONTHS).status == "warn"


def test_concentration_single_article_warns():
    df = pd.DataFrame({"A": growing()})
    assert trust.check_concentration(df, ED, MONTHS).status == "warn"


def test_concentration_fail_when_one_article_carries_growth():
    df = pd.DataFrame({"A": const(100), "B": const(100), "C": growing(20, 0.08)})
    c = trust.check_concentration(df, ED, MONTHS)
    assert c.status == "fail" and "'C'" in c.reason


def test_concentration_warn_on_dominant_article():
    df = pd.DataFrame({"A": const(1000), "B": const(100), "C": const(100)})
    c = trust.check_concentration(df, ED, MONTHS)
    assert c.status == "warn" and "83%" in c.reason


def test_concentration_pass():
    df = pd.DataFrame({t: growing() for t in "ABC"})
    assert trust.check_concentration(df, ED, MONTHS).status == "pass"


def test_edition_effect():
    assert trust.check_edition_effect(19.6, -25.4).status == "warn"
    assert trust.check_edition_effect(19.6, 25.0).status == "pass"
    assert trust.check_edition_effect(2.0, -25.0).status == "pass"


def test_volume():
    assert trust.check_volume(pd.Series([5.0] * 30)).status == "fail"
    assert trust.check_volume(pd.Series([30.0] * 30)).status == "warn"
    assert trust.check_volume(pd.Series([100.0] * 30)).status == "pass"


def test_coverage():
    df = pd.DataFrame({"A": const(100), "B": const(100)})
    none_missing = df.astype(bool) & False
    assert trust.check_coverage("uk", None, None, [], MONTHS).status == "fail"
    assert trust.check_coverage("uk", df, none_missing, [], MONTHS).status == "pass"
    gap = [{"lang": "uk", "qid": "Q1", "label": "telescope", "role": "core"}]
    c = trust.check_coverage("uk", df, none_missing, gap, MONTHS)
    assert c.status == "warn" and "telescope" in c.reason
    related_gap = [{**gap[0], "role": "related"}]
    assert trust.check_coverage("uk", df, none_missing, related_gap, MONTHS).status == "pass"
    missing = none_missing.copy()
    missing["B"] = True
    assert "no data" in trust.check_coverage("uk", df, missing, [], MONTHS).reason
    late = df.copy()
    late.loc[late.index < "2023-06-01", "B"] = 0
    c = trust.check_coverage("uk", late, none_missing, [], MONTHS)
    assert c.status == "warn" and "mid-window" in c.reason


def test_significance():
    assert trust.check_significance(None).status == "warn"
    assert trust.check_significance(0.2).status == "warn"
    assert trust.check_significance(0.01).status == "pass"


def test_window_sensitivity_flip_warns():
    months = {m: 1000.0 for m in months_between("2022-10", "2022-12")}
    months.update({m: 400.0 for m in months_between("2024-10", "2024-12")})
    c = trust.check_window(by_month(months), ED, MONTHS)
    assert c.status == "warn" and "-3 months" in c.reason


def test_window_sensitivity_pass_and_untested():
    assert trust.check_window(growing(), ED, MONTHS).status == "pass"
    inside = growing()[(DAYS >= "2023-01-01") & (DAYS <= "2024-12-31")]
    c = trust.check_window(inside, ED, MONTHS)
    assert c.status == "pass" and "not tested" in c.reason


def test_confidence_rule():
    p, w, f = (Check("x", s, "") for s in ("pass", "warn", "fail"))
    assert trust.confidence([p, p, w]) == "High"
    assert trust.confidence([w, w, p]) == "Medium"
    assert trust.confidence([f, p]) == "Low"
