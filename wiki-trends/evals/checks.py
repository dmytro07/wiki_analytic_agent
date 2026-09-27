"""Deterministic grading of one eval run: the transcript plus the files the agent produced."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from wiki_trends.check import check_workspace
from wiki_trends.workspace import WORK_DIR_NAME, BasketError, load_basket, read_json

CLI_RE = re.compile(r"scripts/wt\b|\bwiki-trends\s+(init|resolve|fetch|analyze|chart|check|report|run)\b")
OWN_FETCH_PATTERNS = ("wikimedia.org/api", "wikidata.org/w/api", "import requests", "urllib.request", "curl ")
CONFIDENCE_RE = re.compile(
    r"\b(high|medium|low)\b[^.\n]{0,25}\bconfidence\b|\bconfidence\b[^.]{0,40}?\b(high|medium|low)\b", re.I)
LIMITATION_RE = re.compile(
    r"limitation|assumption|caveat|willingness to pay|demand to pay|would pay|purchase intent|attention, not|not (?:the same as|a proxy for)",
    re.I)


@dataclass
class Transcript:
    tool_calls: list[dict] = field(default_factory=list)  # {"name", "input"}
    final_text: str = ""
    session_id: str | None = None
    cost_usd: float = 0.0
    duration_s: float = 0.0


@dataclass
class Result:
    name: str
    passed: bool
    detail: str = ""


def parse_stream(lines) -> Transcript:
    t = Transcript()
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            t.session_id = event.get("session_id") or t.session_id
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    t.tool_calls.append({"name": block.get("name"), "input": block.get("input", {})})
        elif kind == "result":
            t.final_text = event.get("result") or ""
            t.session_id = event.get("session_id") or t.session_id
            t.cost_usd += event.get("total_cost_usd") or 0.0
            t.duration_s += (event.get("duration_ms") or 0) / 1000
    return t


def merge(parts: list[Transcript]) -> Transcript:
    return Transcript(
        tool_calls=[c for p in parts for c in p.tool_calls],
        final_text=parts[-1].final_text if parts else "",
        session_id=parts[-1].session_id if parts else None,
        cost_usd=sum(p.cost_usd for p in parts),
        duration_s=sum(p.duration_s for p in parts),
    )


def workspaces(workdir: Path) -> list[Path]:
    return sorted(p.parent for p in (workdir / WORK_DIR_NAME).glob("*/basket.json"))


def grade(t: Transcript, workdir: Path, case: dict) -> list[Result]:
    results: list[Result] = []
    commands = [c["input"].get("command", "") for c in t.tool_calls if c["name"] == "Bash"]
    results.append(Result("used_cli", any(CLI_RE.search(c) for c in commands), f"{len(commands)} bash calls"))
    blobs = [json.dumps(c["input"], ensure_ascii=False) for c in t.tool_calls]
    offenders = [p for p in OWN_FETCH_PATTERNS if any(p in b for b in blobs)]
    results.append(Result("no_own_fetch", not offenders, ", ".join(offenders)))

    found = workspaces(workdir)
    ws = max(found, key=lambda p: (p / "basket.json").stat().st_mtime) if found else None
    basket, detail = None, "no workspace"
    if ws:
        try:
            basket, detail = load_basket(ws), str(ws.name)
        except BasketError as exc:
            detail = str(exc)
    results.append(Result("basket_valid", basket is not None, detail))
    if case.get("expect_langs"):
        got = basket.langs if basket else []
        results.append(Result("langs_match", set(case["expect_langs"]) <= set(got), f"got {got}"))

    pdf = ws / "report.pdf" if ws else None
    pages = len(PdfReader(pdf).pages) if pdf and pdf.exists() else 0
    results.append(Result("report_one_page", pages == 1, f"{pages} page(s)"))
    if ws and (ws / "analysis.json").exists():
        issues = check_workspace(ws)
        results.append(Result("check_passes", not issues, "; ".join(str(i) for i in issues)[:200]))
    else:
        results.append(Result("check_passes", False, "no analysis.json"))

    stated = {(m.group(1) or m.group(2)).capitalize() for m in CONFIDENCE_RE.finditer(t.final_text)}
    results.append(Result("states_confidence", bool(stated), ", ".join(sorted(stated))))
    if ws and (ws / "analysis.json").exists():
        actual = {d["confidence"] for d in read_json(ws / "analysis.json")["languages"].values()}
        results.append(Result("confidence_matches", bool(stated) and stated <= actual,
                              f"stated {sorted(stated)}, analysis {sorted(actual)}"))
    results.append(Result("mentions_limitations", bool(LIMITATION_RE.search(t.final_text))))
    if case.get("must_mention_any"):
        hit = [w for w in case["must_mention_any"] if w.lower() in t.final_text.lower()]
        results.append(Result("must_mention_any", bool(hit), ", ".join(hit)))
    if case.get("expect_reuse"):
        reused = len(found) == 1 and (found[0] / "history" / "run-002.json").exists()
        results.append(Result("reused_workspace", reused, f"{len(found)} workspace(s)"))
    return results
