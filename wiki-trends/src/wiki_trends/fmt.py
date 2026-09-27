"""Number formatting shared by summaries, charts and reports."""

from __future__ import annotations


def fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1f}%"


def fmt_num(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{x:,.{digits}f}" if digits else f"{round(x):,}"
