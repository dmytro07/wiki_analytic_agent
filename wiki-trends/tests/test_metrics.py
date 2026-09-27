import numpy as np
import pandas as pd
import pytest

from wiki_trends.metrics import (
    breaks,
    direction,
    flipped,
    growth_pct,
    normalize,
    seasonality_strength,
    trend,
    window_monthly,
)
from wiki_trends.workspace import months_between, shift_month


def series(values, start="2023-01"):
    idx = months_between(start, shift_month(start, len(values) - 1))
    return pd.Series(values, index=idx, dtype=float)


def test_window_monthly_sums_and_reindexes():
    s = pd.Series([1, 2, 3, 4], index=pd.date_range("2024-01-30", "2024-02-02"), dtype=float)
    out = window_monthly(s, ["2023-12", "2024-01", "2024-02"])
    assert np.isnan(out["2023-12"])
    assert out["2024-01"] == 3 and out["2024-02"] == 7


def test_normalize_zero_edition_month_is_nan():
    out = normalize(series([10, 10]), series([1e6, 0]))
    assert out.iloc[0] == 10.0
    assert np.isnan(out.iloc[1])


def test_growth_yoy():
    g, method = growth_pct(series([100] * 12 + [120] * 12))
    assert method == "yoy_12m"
    assert g == pytest.approx(20.0)


def test_growth_uses_last_24_months():
    g, _ = growth_pct(series([999] * 6 + [100] * 12 + [150] * 12))
    assert g == pytest.approx(50.0)


def test_growth_half_split_for_short_windows():
    g, method = growth_pct(series([100] * 5 + [999] + [80] * 5))
    assert method == "half_split"
    assert g == pytest.approx(-20.0)


def test_growth_skips_nan_months():
    v = [100.0] * 12 + [120.0] * 12
    v[3] = np.nan
    v[15] = np.nan
    assert growth_pct(series(v))[0] == pytest.approx(20.0)


def test_growth_none_when_prior_is_zero():
    assert growth_pct(series([0] * 12 + [5] * 12))[0] is None


def test_direction_flipped_breaks():
    assert (direction(4.9), direction(5.1), direction(-6), direction(None)) == (0, 1, -1, 0)
    assert flipped(20, -10) and not flipped(20, 2)
    assert breaks(20, 2) and breaks(20, -10)
    assert not breaks(20, 15) and not breaks(2, -30)


def test_trend_on_steady_growth():
    t = trend(series([100 * 1.03**i for i in range(24)]))
    assert t["slope_pct_per_year"] == pytest.approx(42.58, abs=0.1)
    assert t["p_value"] < 0.001


def test_trend_on_constant_series():
    t = trend(series([50] * 24))
    assert t["slope_pct_per_year"] == pytest.approx(0.0)
    assert t["p_value"] == 1.0


def test_trend_needs_six_months():
    assert trend(series([1, 2, 3]))["p_value"] is None


def test_seasonality_strength():
    seasonal = series([100 * (1 + 0.5 * np.sin(2 * np.pi * i / 12)) for i in range(36)])
    assert seasonality_strength(seasonal) > 0.9
    noise = series(list(100 + np.random.default_rng(0).normal(0, 10, 60)))
    assert seasonality_strength(noise) < 0.5
    assert seasonality_strength(series([100] * 12)) is None
    assert seasonality_strength(series([100] * 24)) == 0.0
