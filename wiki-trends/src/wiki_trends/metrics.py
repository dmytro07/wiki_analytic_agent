"""Pure time-series metrics on monthly pageview series indexed by 'YYYY-MM'."""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
from scipy import stats

FLAT_PCT = 5.0  # |growth| below this counts as flat when comparing directions
PER_MILLION = 1e6


def month_key(index: pd.DatetimeIndex) -> pd.Index:
    return index.strftime("%Y-%m")


def window_monthly(daily: pd.Series, months: list[str]) -> pd.Series:
    """Sum a daily series per month, restricted to `months` (months without data → NaN)."""
    return daily.groupby(month_key(daily.index)).sum().reindex(months).astype(float)


def normalize(article_monthly: pd.Series, edition_monthly: pd.Series) -> pd.Series:
    """Views per million views of the whole edition; months with no edition total → NaN."""
    edition = edition_monthly.reindex(article_monthly.index)
    return article_monthly / edition.where(edition > 0) * PER_MILLION


def growth_pct(monthly: pd.Series) -> tuple[float | None, str]:
    """% change of the recent period's mean vs the prior period's mean.

    ≥24 months: last 12 vs the 12 before (same calendar months, so seasonality cancels).
    Shorter: second half vs first half.
    """
    n = len(monthly)
    if n >= 24:
        prior, recent, method = monthly.iloc[-24:-12], monthly.iloc[-12:], "yoy_12m"
    else:
        half = n // 2
        prior, recent, method = monthly.iloc[:half], monthly.iloc[n - half:], "half_split"
    p, r = prior.mean(), recent.mean()
    if pd.isna(p) or pd.isna(r) or p <= 0:
        return None, method
    return float((r / p - 1) * 100), method


def direction(pct: float | None) -> int:
    if pct is None or math.isnan(pct) or abs(pct) < FLAT_PCT:
        return 0
    return 1 if pct > 0 else -1


def flipped(base: float | None, alt: float | None) -> bool:
    """Both clearly non-flat and pointing in opposite directions."""
    return direction(base) * direction(alt) == -1


def breaks(base: float | None, alt: float | None) -> bool:
    """The base has a clear direction that the alternative flattens or reverses."""
    return direction(base) != 0 and direction(alt) != direction(base)


def _log_values(monthly: pd.Series) -> np.ndarray | None:
    v = monthly.to_numpy(dtype=float)
    ok = np.isfinite(v) & (v > 0)
    if not ok.any():
        return None
    floor = v[ok].min() / 2
    return np.log(np.where(ok, v, floor))


def trend(monthly: pd.Series) -> dict:
    """Theil–Sen slope of log values as % per year, with a Mann–Kendall (Kendall tau vs time) p-value."""
    logv = _log_values(monthly)
    if logv is None or len(logv) < 6:
        return {"slope_pct_per_year": None, "p_value": None}
    x = np.arange(len(logv))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        slope = stats.theilslopes(logv, x)[0]
        p = stats.kendalltau(x, logv)[1]
    return {
        "slope_pct_per_year": float((math.exp(slope * 12) - 1) * 100),
        "p_value": 1.0 if p is None or math.isnan(p) else float(p),
    }


def seasonality_strength(monthly: pd.Series) -> float | None:
    """How well each year's detrended monthly shape repeats in the next (mean correlation, 0–1)."""
    logv = _log_values(monthly)
    if logv is None or len(logv) < 24:
        return None
    x = np.arange(len(logv))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        slope, intercept = stats.theilslopes(logv, x)[:2]
    resid = logv - (intercept + slope * x)
    n = len(resid)
    blocks = [resid[n - 12 * (k + 1): n - 12 * k] for k in range(n // 12)]
    corrs = [
        float(np.corrcoef(a, b)[0, 1])
        for a, b in zip(blocks, blocks[1:])
        if a.std() > 1e-9 and b.std() > 1e-9
    ]
    return round(max(0.0, float(np.mean(corrs))), 2) if corrs else 0.0
