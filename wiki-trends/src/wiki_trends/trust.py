"""Trust checks: can the headline growth number be believed? Each check → pass | warn | fail."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .metrics import PER_MILLION, breaks, direction, flipped, growth_pct, month_key, normalize, window_monthly
from .workspace import month_start, shift_month

LOW_VOLUME_WARN = 50  # median views/day
LOW_VOLUME_FAIL = 10
CONCENTRATION_SHARE = 0.6
SPIKE_QUANTILE = 0.99
WINDOW_SHIFT = 3  # months
SIGNIFICANCE = 0.05


@dataclass
class Check:
    name: str
    status: str  # pass | warn | fail
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.0f}%"


def _norm_growth(basket_daily: pd.Series, edition_daily: pd.Series, months: list[str]) -> float | None:
    return growth_pct(normalize(window_monthly(basket_daily, months), window_monthly(edition_daily, months)))[0]


def check_spike(basket_daily: pd.Series, edition_daily: pd.Series, months: list[str]) -> Check:
    base = _norm_growth(basket_daily, edition_daily, months)
    ratio = basket_daily / edition_daily.where(edition_daily > 0) * PER_MILLION
    ratio = ratio[month_key(ratio.index).isin(months)].dropna()
    medians = growth_pct(ratio.groupby(month_key(ratio.index)).median().reindex(months))[0]
    kept = ratio[ratio <= ratio.quantile(SPIKE_QUANTILE)]
    trimmed = growth_pct(kept.groupby(month_key(kept.index)).mean().reindex(months))[0]
    detail = f"growth {_pct(base)}; on monthly medians {_pct(medians)}; without top 1% days {_pct(trimmed)}"
    if breaks(base, medians) or breaks(base, trimmed):
        return Check("spike_dependence", "fail", f"growth depends on a few spike days ({detail})")
    if direction(base) != 0 and any(v is not None and abs(v) < abs(base) / 2 for v in (medians, trimmed)):
        return Check("spike_dependence", "warn", f"growth halves without spike days ({detail})")
    return Check("spike_dependence", "pass", detail)


def check_concentration(articles_daily: pd.DataFrame, edition_daily: pd.Series, months: list[str]) -> Check:
    in_window = month_key(articles_daily.index).isin(months)
    totals = articles_daily[in_window].sum()
    if len(totals) == 1:
        return Check("article_concentration", "warn",
                     f"single-article basket ('{totals.index[0]}'); add related items for a sturdier signal")
    base = _norm_growth(articles_daily.sum(axis=1), edition_daily, months)
    for title in articles_daily.columns:
        alt = _norm_growth(articles_daily.drop(columns=title).sum(axis=1), edition_daily, months)
        if breaks(base, alt):
            return Check("article_concentration", "fail", f"growth {_pct(base)} becomes {_pct(alt)} without '{title}'")
    all_views = totals.sum()
    top = totals.idxmax()
    share = totals.max() / all_views if all_views else 0.0
    if share > CONCENTRATION_SHARE:
        return Check("article_concentration", "warn", f"'{top}' is {share:.0%} of basket views")
    return Check("article_concentration", "pass",
                 f"largest article '{top}' is {share:.0%} of views; growth holds without any single article")


def check_edition_effect(raw_growth: float | None, norm_growth: float | None) -> Check:
    if flipped(raw_growth, norm_growth):
        return Check("edition_effect", "warn",
                     f"raw views {_pct(raw_growth)} but share of edition views {_pct(norm_growth)}: "
                     "the whole edition's traffic moved")
    return Check("edition_effect", "pass", f"raw {_pct(raw_growth)}, share of edition {_pct(norm_growth)}")


def check_volume(daily_in_window: pd.Series) -> Check:
    med = float(daily_in_window.median()) if len(daily_in_window) else 0.0
    if med < LOW_VOLUME_FAIL:
        return Check("low_volume", "fail", f"median {med:.0f} views/day is too low to measure a trend")
    if med < LOW_VOLUME_WARN:
        return Check("low_volume", "warn", f"median {med:.0f} views/day; small changes look large")
    return Check("low_volume", "pass", f"median {med:,.0f} views/day")


def check_coverage(lang: str, articles_daily: pd.DataFrame | None, missing_daily: pd.DataFrame | None,
                   gaps: list[dict], months: list[str]) -> Check:
    if articles_daily is None or articles_daily.shape[1] == 0:
        return Check("coverage", "fail", f"no {lang} Wikipedia article for any basket item")
    issues = []
    core = [g["label"] for g in gaps if g["role"] == "core"]
    if core:
        issues.append(f"no {lang} article for core item(s): {', '.join(core)}")
    in_window = month_key(articles_daily.index).isin(months)
    win, miss = articles_daily[in_window], missing_daily[in_window]
    missing = [t for t in win.columns if miss[t].any()]
    if missing:
        issues.append(f"no data for part of the window: {', '.join(missing)}")
    cutoff = pd.Timestamp(month_start(months[0])) + pd.Timedelta(days=31)
    late = []
    for title in win.columns:
        if title in missing:
            continue
        nonzero = win.index[win[title] > 0]
        if len(nonzero) == 0 or nonzero[0] > cutoff:
            late.append(title)
    if late:
        issues.append(f"article(s) start mid-window or have no views: {', '.join(late)}")
    if issues:
        return Check("coverage", "warn", "; ".join(issues))
    return Check("coverage", "pass", f"{win.shape[1]} article(s) with data for the whole window")


def check_significance(p_value: float | None) -> Check:
    if p_value is None:
        return Check("significance", "warn", "too few months to test the trend")
    if p_value >= SIGNIFICANCE:
        return Check("significance", "warn", f"trend not statistically significant (p={p_value:.2f})")
    return Check("significance", "pass", f"trend is statistically significant (p={p_value:.3f})")


def check_window(basket_daily: pd.Series, edition_daily: pd.Series, months: list[str]) -> Check:
    available = set(month_key(basket_daily.index))
    base = _norm_growth(basket_daily, edition_daily, months)
    tested = []
    for shift in (-WINDOW_SHIFT, WINDOW_SHIFT):
        shifted = [shift_month(m, shift) for m in months]
        if not set(shifted) <= available:
            continue
        alt = _norm_growth(basket_daily, edition_daily, shifted)
        if flipped(base, alt):
            return Check("window_sensitivity", "warn",
                         f"growth {_pct(base)} flips to {_pct(alt)} when the window moves {shift:+d} months")
        tested.append(f"{shift:+d} months: {_pct(alt)}")
    if not tested:
        return Check("window_sensitivity", "pass", "not tested: no data around the window")
    return Check("window_sensitivity", "pass", f"growth {_pct(base)} holds when the window moves ({'; '.join(tested)})")


def confidence(checks: list[Check]) -> str:
    if any(c.status == "fail" for c in checks):
        return "Low"
    if sum(c.status == "warn" for c in checks) >= 2:
        return "Medium"
    return "High"
