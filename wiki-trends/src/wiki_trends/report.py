"""Render the one-page A4 PDF report with matplotlib only (no system libraries)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .analyze import GROWTH_METHOD_TEXT  # noqa: E402
from .charts import render_charts  # noqa: E402
from .check import parse_narrative  # noqa: E402
from .fmt import fmt_num, fmt_pct  # noqa: E402
from .langs import language_name  # noqa: E402
from .workspace import file_sha, read_json, stale_analysis_message, text_sha  # noqa: E402

A4 = (8.27, 11.69)  # inches
MARGIN = 0.06  # fraction of page width/height
LINE_HEIGHT = 1.4  # × font size
MAX_TABLE_ROWS = 8
MAX_LIMITATIONS = 9


class ReportError(RuntimeError):
    """The report cannot be rendered yet; the message says which command to run."""


def limitations(analysis: dict) -> list[str]:
    w = analysis["window"]
    methods = sorted({d["basket"]["growth_method"] for d in analysis["languages"].values() if d["basket"]})
    out = [
        "Interest = Wikipedia pageviews by people (agent=user); some automated traffic can still slip through.",
        "Values are per million views of each language edition, so editions of different size compare fairly; raw counts are shown too.",
        "Views of redirects and of articles under former titles are not counted.",
        "Pageviews show attention, not willingness to pay: use them to choose what to validate next.",
        f"Window {w['start']} to {w['end']} ({w['months']} months); growth = "
        + ("; ".join(GROWTH_METHOD_TEXT[m] for m in methods) or "n/a") + ".",
    ]
    if "half_split" in methods:
        out.append("Window under 24 months: growth compares halves of the window, which does not cancel seasonal swings.")
    gaps: dict[str, list[str]] = {}
    for g in analysis.get("gaps", []):
        gaps.setdefault(g["lang"], []).append(g["label"])
    if gaps:
        out.append("Missing articles: " + "; ".join(
            f"{lang}: {', '.join(labels[:3])}" + (" …" if len(labels) > 3 else "") for lang, labels in gaps.items()))
    for lang, d in analysis["languages"].items():
        if d["confidence"] == "Low":
            fail = next((c for c in d["checks"] if c["status"] == "fail"), None)
            out.append(f"{language_name(lang)} ({lang}) is low confidence: {fail['reason'] if fail else 'see trust checks'}.")
    return out[:MAX_LIMITATIONS]


class _Page:
    """Places text top-down on an A4 figure, tracking the vertical cursor."""

    def __init__(self, fig, scale: float = 1.0):
        self.fig = fig
        self.scale = scale  # font scale; smaller fonts fit more characters per line
        self.y = 1 - MARGIN * 0.8

    def text(self, s: str, size: float = 9, weight: str = "normal", color: str = "#222222", wrap: int = 100, gap: float = 0.35):
        size, wrap = size * self.scale, int(wrap / self.scale)
        lines: list[str] = []
        for para in s.split("\n"):
            lines += textwrap.wrap(para, wrap) or [""]
        step = size * LINE_HEIGHT / (A4[1] * 72)
        for line in lines:
            self.fig.text(MARGIN, self.y, line, fontsize=size, fontweight=weight, color=color, va="top")
            self.y -= step
        self.y -= gap * step

    def image(self, path: Path, height: float):
        ax = self.fig.add_axes([MARGIN, self.y - height, 1 - 2 * MARGIN, height])
        ax.imshow(plt.imread(path))
        ax.axis("off")
        self.y -= height + 0.008

    def table(self, header: list[str], rows: list[list[str]]):
        height = 0.019 * self.scale * (len(rows) + 1)
        ax = self.fig.add_axes([MARGIN, self.y - height, 1 - 2 * MARGIN, height])
        ax.axis("off")
        table = ax.table(cellText=rows, colLabels=header, cellLoc="left", colLoc="left", bbox=[0, 0, 1, 1])
        table.auto_set_font_size(False)
        table.set_fontsize(7 * self.scale)
        for (r, _), cell in table.get_celld().items():
            cell.set_edgecolor("#cccccc")
            if r == 0:
                cell.set_text_props(weight="bold")
        self.y -= height + 0.012


def _language_table(analysis: dict) -> tuple[list[str], list[list[str]]]:
    header = ["Language", "Level /M views", "Growth (share)", "Growth (raw)", "Trend / yr", "Confidence", "Score"]
    scores = {r["lang"]: r["score"] for r in analysis["ranking"]}
    order = [r["lang"] for r in analysis["ranking"]] or list(analysis["languages"])
    rows = []
    for lang in order[:MAX_TABLE_ROWS]:
        d = analysis["languages"][lang]
        b = d["basket"] or {}
        rows.append([
            f"{language_name(lang)} ({lang})", fmt_num(b.get("level_norm"), 2), fmt_pct(b.get("growth_norm_pct")),
            fmt_pct(b.get("growth_raw_pct")), fmt_pct(b.get("trend_pct_per_year")), d["confidence"],
            f"{scores[lang]:.2f}" if lang in scores else "–",
        ])
    return header, rows


def _trust_lines(analysis: dict) -> list[str]:
    lines = []
    for lang, d in list(analysis["languages"].items())[:MAX_TABLE_ROWS]:
        flagged = [c for c in d["checks"] if c["status"] != "pass"]
        detail = "; ".join(f"{c['status']}: {c['name'].replace('_', ' ')}" for c in flagged) or "all checks pass"
        lines.append(f"{lang} — {d['confidence']}: {detail}")
    return lines


def _footer(analysis: dict) -> str:
    w, prov = analysis["window"], analysis["provenance"]
    basket = ", ".join(f"{i['label']} ({i['qid']})" for i in analysis.get("items", []))
    text = (f"Data: {prov.get('source', '')}. Window {w['start']} to {w['end']}. "
            f"Retrieved {str(prov.get('retrieved_at', ''))[:16]}. Basket: {basket}. Generated by wiki-trends.")
    return "\n".join(textwrap.wrap(text, 170))


FOOTER_TOP = 0.045  # the footer (two 6 pt lines at y=0.015) ends below this; the body must stay above it
# Layouts tried in order until the body clears the footer: (chart height, font scale, compact trust/limitations).
LAYOUTS = ((0.24, 1.0, False), (0.17, 1.0, False), (0.13, 0.9, False), (0.11, 0.85, True))


def _compact_trust_line(analysis: dict) -> str:
    parts = []
    for lang, d in analysis["languages"].items():
        flagged = sum(c["status"] != "pass" for c in d["checks"])
        parts.append(f"{lang} {d['confidence']}" + (f" ({flagged} flagged)" if flagged else ""))
    return "; ".join(parts) + ". Details in analysis.json."


def _draw_body(fig, analysis: dict, n, trend_png: Path, layout: tuple) -> float:
    """Draw everything above the footer; return where the body ends (figure fraction)."""
    chart_height, scale, compact = layout
    page = _Page(fig, scale)
    page.text("WIKIPEDIA INTEREST REPORT", size=7.5, weight="bold", color="#666666", gap=0.2)
    page.text(analysis["question"] or "(no question recorded)", size=9, color="#444444", wrap=110)
    page.text(n.headline[1] if n.headline else "", size=14, weight="bold", wrap=70)
    page.text("Findings", size=10, weight="bold", gap=0.1)
    for _, finding in n.findings:
        page.text("• " + finding, size=8.5, wrap=115, gap=0.15)
    page.image(trend_png, height=chart_height)
    page.text("By language", size=10, weight="bold", gap=0.1)
    page.table(*_language_table(analysis))
    page.text("Recommendation", size=10, weight="bold", gap=0.1)
    page.text(n.recommendation, size=8.5, wrap=115)
    page.text("Trust checks", size=10, weight="bold", gap=0.1)
    for line in [_compact_trust_line(analysis)] if compact else _trust_lines(analysis):
        page.text(line, size=7.5, wrap=135, gap=0.1)
    page.y -= 0.006
    page.text("Assumptions & limitations", size=10, weight="bold", gap=0.1)
    for line in limitations(analysis):
        if compact:
            line = textwrap.shorten(line, int(135 / scale) - 2, placeholder=" …")
        page.text("• " + line, size=7.5, wrap=135, gap=0.1)
    return page.y


def fit_layout(ws: Path, analysis: dict, narrative_text: str):
    """Lay out the page, shrinking the chart until the body clears the footer. Returns (figure, body bottom)."""
    n = parse_narrative(narrative_text)
    render_charts(ws, analysis)  # always redraw: charts from an earlier run may be stale
    trend_png = ws / "charts" / "trend.png"
    for layout in LAYOUTS:
        fig = plt.figure(figsize=A4)
        bottom = _draw_body(fig, analysis, n, trend_png, layout)
        if bottom >= FOOTER_TOP:
            return fig, bottom
        plt.close(fig)
    raise ReportError("the report does not fit on one page; shorten narrative.md (fewer or shorter findings) "
                      "or compare fewer languages")


def render_report(ws: Path, analysis: dict, narrative_text: str, checked: bool) -> Path:
    out = ws / "report.pdf"
    with plt.rc_context({"pdf.fonttype": 42, "font.family": "DejaVu Sans"}):
        fig, _ = fit_layout(ws, analysis, narrative_text)
        fig.text(MARGIN, 0.015, _footer(analysis), fontsize=6, color="#777777", va="bottom")
        if not checked:
            fig.text(1 - MARGIN, 1 - MARGIN * 0.8, "UNCHECKED DRAFT", fontsize=9, color="#D55E00",
                     ha="right", va="top", fontweight="bold")
        fig.savefig(out, format="pdf")
        plt.close(fig)
    return out


def report_workspace(ws: Path, force: bool = False) -> Path:
    analysis_path, narrative_path = ws / "analysis.json", ws / "narrative.md"
    if not analysis_path.exists():
        raise ReportError(f"analysis.json not found; run: wt run {ws.name}")
    if not narrative_path.exists():
        raise ReportError(f"narrative.md not found; write it following reference/report-guide.md, then run: wt check {ws.name}")
    analysis = read_json(analysis_path)
    stale = stale_analysis_message(ws, analysis)
    if stale:
        raise ReportError(stale)
    text = narrative_path.read_text(encoding="utf-8")
    status = read_json(ws / "check.json") if (ws / "check.json").exists() else {}
    checked = (bool(status.get("passed")) and status.get("narrative_sha") == text_sha(text)
               and status.get("analysis_sha") == file_sha(analysis_path))
    if not checked and not force:
        raise ReportError(f"narrative.md has not passed the check (or changed since); run: wt check {ws.name}")
    return render_report(ws, analysis, text, checked)
