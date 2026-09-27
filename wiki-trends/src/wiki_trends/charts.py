"""Matplotlib PNG charts for a workspace, in one consistent style."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#8C6D31", "#000000"]  # colour-blind safe
CONFIDENCE_COLORS = {"High": "#009E73", "Medium": "#E69F00", "Low": "#D55E00"}
STYLE = {
    "font.size": 8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linewidth": 0.5,
    "savefig.dpi": 150,
}
MAX_ARTICLES = 6


def _ticks(months: list[str]) -> tuple[list[int], list[str]]:
    step = max(1, len(months) // 8)
    pos = list(range(0, len(months), step))
    return pos, [months[i] for i in pos]


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def trend_chart(analysis: dict, path: Path) -> Path:
    with plt.rc_context(STYLE):
        fig, (top, bottom) = plt.subplots(2, 1, figsize=(8, 4.2), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
        months: list[str] = []
        for i, (lang, d) in enumerate(analysis["languages"].items()):
            if not d["monthly"]:
                continue
            months = [m["month"] for m in d["monthly"]]
            color = PALETTE[i % len(PALETTE)]
            x = range(len(months))
            norm = [float("nan") if m["norm"] is None else m["norm"] for m in d["monthly"]]
            top.plot(x, norm, color=color, lw=1.8, label=f"{lang} ({d['confidence']} confidence)")
            bottom.plot(x, [m["views"] for m in d["monthly"]], color=color, lw=1.2)
        if months:
            pos, labels = _ticks(months)
            bottom.set_xticks(pos, labels, rotation=45, ha="right")
            top.legend(frameon=False, fontsize=7)
        else:
            top.text(0.5, 0.5, "No data for any language", ha="center", va="center", transform=top.transAxes)
        top.set_ylabel("views per million\nedition views")
        bottom.set_ylabel("raw views\nper month")
        top.set_title("Interest over time (share of each language edition's views)", loc="left", fontsize=9)
        return _save(fig, path)


def articles_chart(analysis: dict, path: Path) -> Path:
    langs = [(lang, d) for lang, d in analysis["languages"].items() if d["articles"]]
    n = max(1, len(langs))
    cols = min(n, 3)
    rows = -(-n // cols)
    with plt.rc_context(STYLE):
        fig, axes = plt.subplots(rows, cols, figsize=(3.2 * cols + 0.8, 2.6 * rows), squeeze=False)
        for ax, (lang, d) in zip(axes.flat, langs):
            months = [m["month"] for m in d["monthly"]]
            arts = d["articles"][:MAX_ARTICLES]
            ax.stackplot(range(len(months)), [a["monthly_views"] for a in arts],
                         labels=[a["label"][:24] for a in arts], colors=PALETTE[:len(arts)], alpha=0.85)
            ax.set_title(f"{lang}: views by article (top {len(arts)})", loc="left", fontsize=8)
            pos, labels = _ticks(months)
            ax.set_xticks(pos, labels, rotation=45, ha="right", fontsize=6)
            ax.legend(fontsize=6, frameon=False, loc="upper left")
        for ax in list(axes.flat)[len(langs):]:
            ax.axis("off")
        if not langs:
            axes[0][0].text(0.5, 0.5, "No articles found", ha="center", va="center", transform=axes[0][0].transAxes)
        return _save(fig, path)


def ranking_chart(analysis: dict, path: Path) -> Path:
    rows = analysis["ranking"][::-1]
    w = analysis["weights"]
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(6, 0.4 * len(rows) + 1.2))
        ax.barh([r["lang"] for r in rows], [r["score"] for r in rows],
                color=[CONFIDENCE_COLORS[r["confidence"]] for r in rows])
        for i, r in enumerate(rows):
            ax.text(r["score"] + 0.01, i, f"{r['score']:.2f} ({r['confidence']})", va="center", fontsize=7)
        ax.set_xlim(0, 1.3)
        ax.set_title(f"Priority score (weights: growth {w['growth']}, level {w['level']}, confidence {w['confidence']})",
                     loc="left", fontsize=9)
        return _save(fig, path)


def render_charts(ws: Path, analysis: dict) -> list[Path]:
    out = ws / "charts"
    out.mkdir(exist_ok=True)
    paths = [trend_chart(analysis, out / "trend.png"), articles_chart(analysis, out / "articles.png")]
    if analysis["ranking"]:
        paths.append(ranking_chart(analysis, out / "ranking.png"))
    return paths
