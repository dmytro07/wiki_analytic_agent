"""Run the eval cases through Claude Code headless and write a scorecard.

Usage (from wiki-trends/):
    uv run python evals/run_evals.py                      # all cases, Haiku 4.5
    uv run python evals/run_evals.py --case astronomy-uk  # one case
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(SKILL_DIR))

from evals.checks import Transcript, grade, merge, parse_stream, workspaces  # noqa: E402

TOOLS = "Bash,Read,Write,Edit,Glob,Grep,Skill"


def setup_workdir(root: Path, case_id: str) -> Path:
    workdir = root / case_id
    skills = workdir / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "wiki-trends").symlink_to(SKILL_DIR, target_is_directory=True)
    return workdir


def run_turn(prompt: str, workdir: Path, model: str, session_id: str | None, timeout: int) -> tuple[Transcript, list[str]]:
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
           "--allowedTools", TOOLS, "--setting-sources", "project,local"]
    if session_id:
        cmd += ["--resume", session_id]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout)
        lines = proc.stdout.splitlines()
        if proc.returncode != 0:
            print(f"  claude exited {proc.returncode}: {proc.stderr.strip()[:300]}", file=sys.stderr)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        lines = (out.decode() if isinstance(out, bytes) else out).splitlines()
        print(f"  timed out after {timeout}s", file=sys.stderr)
    transcript = parse_stream(lines)
    if not transcript.duration_s:
        transcript.duration_s = time.monotonic() - started
    if lines and "wiki-trends" not in lines[0]:
        print("  warning: the init event does not mention wiki-trends; was the skill loaded?", file=sys.stderr)
    return transcript, lines


def scorecard(rows: list[tuple[dict, Transcript, list]], model: str, stamp: str) -> str:
    names: list[str] = []
    for _, _, results in rows:
        names += [r.name for r in results if r.name not in names]
    lines = [f"# wiki-trends eval: {model} ({stamp})", "",
             "| case | " + " | ".join(names) + " | tool calls | time (s) | cost ($) |",
             "|" + "---|" * (len(names) + 4)]
    for case, t, results in rows:
        by = {r.name: r for r in results}
        cells = [("pass" if by[n].passed else "FAIL") if n in by else "–" for n in names]
        lines.append(f"| {case['id']} | " + " | ".join(cells)
                     + f" | {len(t.tool_calls)} | {t.duration_s:.0f} | {t.cost_usd:.3f} |")
    passed = sum(r.passed for _, _, rs in rows for r in rs)
    total = sum(len(rs) for _, _, rs in rows)
    lines += ["", f"**{passed}/{total} checks passed.**", "", "## Failures", ""]
    failures = [f"- `{case['id']}` {r.name}: {r.detail}" for case, _, rs in rows for r in rs if not r.passed]
    lines += failures or ["None."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run wiki-trends evals through Claude Code headless.")
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--case", action="append", help="case id (repeatable); default: all")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per turn")
    args = ap.parse_args(argv)
    if shutil.which("claude") is None:
        print("error: the `claude` CLI is not on PATH", file=sys.stderr)
        return 2

    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = HERE / "results" / f"{stamp}-{args.model}"
    out_dir.mkdir(parents=True)
    root = Path(tempfile.mkdtemp(prefix="wiki-trends-eval-"))

    rows = []
    for case in cases:
        print(f"[{case['id']}]", file=sys.stderr)
        workdir = setup_workdir(root, case["id"])
        parts, raw, session = [], [], None
        for prompt in case["turns"]:
            transcript, lines = run_turn(prompt, workdir, args.model, session, args.timeout)
            parts.append(transcript)
            raw += lines
            session = transcript.session_id or session
        merged = merge(parts)
        (out_dir / f"{case['id']}.jsonl").write_text("\n".join(raw) + "\n", encoding="utf-8")
        results = grade(merged, workdir, case)
        found = workspaces(workdir)
        if found:
            keep = out_dir / case["id"]
            keep.mkdir()
            for name in ("report.pdf", "narrative.md", "basket.json"):
                if (found[-1] / name).exists():
                    shutil.copy(found[-1] / name, keep / name)
        rows.append((case, merged, results))

    card = scorecard(rows, args.model, stamp)
    (out_dir / "scorecard.md").write_text(card, encoding="utf-8")
    (HERE / "results" / "LATEST.md").write_text(card, encoding="utf-8")
    print(card)
    print(f"Workdirs kept in {root}", file=sys.stderr)
    return 0 if all(r.passed for _, _, rs in rows for r in rs) else 1


if __name__ == "__main__":
    sys.exit(main())
