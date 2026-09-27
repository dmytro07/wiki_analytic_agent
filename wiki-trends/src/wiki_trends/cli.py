"""Command-line entry point `wiki-trends` (the skill calls it through scripts/wt)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone

from .analyze import analyze_workspace, summarize
from .api import ApiError, WikiClient
from .cache import Cache, default_cache_path
from .charts import render_charts
from .check import check_workspace
from .fetch import fetch_workspace
from .report import ReportError, report_workspace
from .resolve import resolve_workspace, search
from .workspace import (
    BasketError,
    diff_snapshots,
    init_workspace,
    load_basket,
    read_json,
    record_run,
    resolve_workspace_path,
)

MAX_GAP_LINES = 8
MAX_CHANGES = 4


# Factories patched in tests.
def make_client() -> WikiClient:
    return WikiClient()


def make_cache() -> Cache:
    return Cache(default_cache_path())


def today() -> date:
    return date.today()


def now() -> datetime:
    return datetime.now(timezone.utc)


def _emit(args, payload, lines: list[str]) -> None:
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("\n".join(lines))


def _resolve_lines(result: dict) -> list[str]:
    langs = {a["lang"] for a in result["articles"]}
    lines = [f"Resolved {len(result['articles'])} article(s) in {len(langs)} language(s)"]
    gaps = result["gaps"]
    if gaps:
        shown = "; ".join(f"{g['lang']}:{g['label']} ({g['qid']}, {g['role']})" for g in gaps[:MAX_GAP_LINES])
        lines.append("Missing: " + shown + (" …" if len(gaps) > MAX_GAP_LINES else ""))
    return lines


def _fetch_line(meta: dict) -> str:
    return (f"Fetched {meta['range'][0]}..{meta['range'][1]} (window ±3 months): "
            f"{meta['api_requests']} API request(s), the rest from cache")


def cmd_init(args) -> int:
    ws = init_workspace(args.slug, today())
    _emit(args, {"workspace": str(ws)}, [
        f"Created {ws / 'basket.json'}",
        f"Next: fill in question, langs and items (QIDs from `wt resolve --search`), then: wt run {ws.name}",
    ])
    return 0


def cmd_resolve(args) -> int:
    if args.search:
        if not args.lang:
            raise BasketError("--search needs --lang, e.g. --lang en")
        hits = search(make_client(), args.search, args.lang)
        lines = [f"{h['qid']}\t{h['label']} — {h['description']}" for h in hits]
        _emit(args, {"results": hits}, lines or [f"No Wikidata items match '{args.search}'; try other words or --lang en"])
        return 0
    if not args.workspace:
        raise BasketError("give a workspace, or --search TEXT --lang CODE")
    result = resolve_workspace(resolve_workspace_path(args.workspace), make_client())
    _emit(args, result, _resolve_lines(result))
    return 0


def cmd_fetch(args) -> int:
    meta = fetch_workspace(resolve_workspace_path(args.workspace), make_client(), make_cache(), today(), now())
    _emit(args, meta, [_fetch_line(meta)])
    return 0


def cmd_analyze(args) -> int:
    ws = resolve_workspace_path(args.workspace)
    analysis = analyze_workspace(ws)
    _emit(args, analysis, summarize(analysis) + [f"Details: {ws / 'analysis.json'}"])
    return 0


def cmd_chart(args) -> int:
    ws = resolve_workspace_path(args.workspace)
    if not (ws / "analysis.json").exists():
        raise BasketError(f"analysis.json not found; run: wt run {ws.name}")
    paths = render_charts(ws, read_json(ws / "analysis.json"))
    _emit(args, {"charts": [str(p) for p in paths]}, ["Charts: " + ", ".join(str(p) for p in paths)])
    return 0


def cmd_check(args) -> int:
    ws = resolve_workspace_path(args.workspace)
    issues = check_workspace(ws)
    if issues:
        _emit(args, {"passed": False, "issues": [str(i) for i in issues]},
              ["check FAILED; fix narrative.md and run check again:"] + [f"  {i}" for i in issues])
        return 1
    _emit(args, {"passed": True}, [f"check passed; now run: wt report {ws.name}"])
    return 0


def cmd_report(args) -> int:
    path = report_workspace(resolve_workspace_path(args.workspace), force=args.force)
    _emit(args, {"report": str(path)}, [f"Report: {path}"])
    return 0


def cmd_run(args) -> int:
    ws = resolve_workspace_path(args.workspace)
    client, cache = make_client(), make_cache()
    resolved = resolve_workspace(ws, client)
    meta = fetch_workspace(ws, client, cache, today(), now())
    analysis = analyze_workspace(ws)
    charts = render_charts(ws, analysis)
    snapshot = {
        "basket": load_basket(ws).to_dict(),
        "headline": {lang: {"growth_norm_pct": (d["basket"] or {}).get("growth_norm_pct"), "confidence": d["confidence"]}
                     for lang, d in analysis["languages"].items()},
    }
    changes = diff_snapshots(record_run(ws, snapshot), snapshot)
    lines = _resolve_lines(resolved) + [_fetch_line(meta)] + summarize(analysis)
    if changes:
        lines.append("Changes since previous run: " + "; ".join(changes[:MAX_CHANGES]))
    lines += [
        f"Files: {ws / 'analysis.json'}, charts in {ws / 'charts'}",
        f"Next: write {ws / 'narrative.md'}, then: wt check {ws.name}",
    ]
    _emit(args, {"workspace": str(ws), "analysis": analysis, "changes": changes,
                 "charts": [str(p) for p in charts]}, lines)
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print machine-readable JSON instead of a summary")
    parser = argparse.ArgumentParser(prog="wiki-trends",
                                     description="Wikipedia pageview trends for topic and language decisions.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", parents=[common], help="create a workspace with a basket.json template")
    p.add_argument("slug")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("resolve", parents=[common],
                       help="search Wikidata (--search) or map a workspace's items to article titles")
    p.add_argument("workspace", nargs="?")
    p.add_argument("--search")
    p.add_argument("--lang")
    p.set_defaults(func=cmd_resolve)

    for name, func, text in (
        ("fetch", cmd_fetch, "download missing pageviews into data.csv"),
        ("analyze", cmd_analyze, "compute metrics, trust checks and confidence"),
        ("chart", cmd_chart, "draw PNG charts"),
        ("check", cmd_check, "validate narrative.md against analysis.json"),
        ("run", cmd_run, "resolve + fetch + analyze + chart, then print a summary"),
    ):
        p = sub.add_parser(name, parents=[common], help=text)
        p.add_argument("workspace")
        p.set_defaults(func=func)

    p = sub.add_parser("report", parents=[common], help="render the one-page PDF (needs a passing check)")
    p.add_argument("workspace")
    p.add_argument("--force", action="store_true", help="render anyway, stamped UNCHECKED DRAFT")
    p.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (BasketError, ApiError, ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
