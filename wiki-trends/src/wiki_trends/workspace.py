"""Workspace layout, basket schema, month arithmetic and run history."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .fmt import fmt_pct

WORK_DIR_NAME = "wiki-trends-work"
DEFAULT_WEIGHTS = {"growth": 0.4, "level": 0.4, "confidence": 0.2}
FIRST_MONTH = "2015-07"  # the pageviews API has no earlier data
MIN_WINDOW_MONTHS = 6
DATA_LAG_DAYS = 2  # AQS publishes a day's data about a day later; keep a margin

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_QID_RE = re.compile(r"^Q[1-9]\d*$")
_LANG_RE = re.compile(r"^[a-z][a-z0-9-]{1,11}$")
_OVERRIDE_RE = re.compile(r"^[a-z][a-z0-9-]{1,11}:Q[1-9]\d*$")


class BasketError(ValueError):
    """A workspace input is missing or invalid. The message says how to fix it."""


# --- months -----------------------------------------------------------------


def shift_month(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-"))
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_start(ym: str) -> date:
    y, m = map(int, ym.split("-"))
    return date(y, m, 1)


def month_end(ym: str) -> date:
    return month_start(shift_month(ym, 1)) - timedelta(days=1)


def months_between(start: str, end: str) -> list[str]:
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur = shift_month(cur, 1)
    return out


def last_complete_month(today: date) -> str:
    """Latest month whose every day is already published by the pageviews API."""
    ref = today - timedelta(days=DATA_LAG_DAYS)
    ym = f"{ref.year:04d}-{ref.month:02d}"
    return ym if month_end(ym) == ref else shift_month(ym, -1)


# --- basket -----------------------------------------------------------------


@dataclass
class Item:
    qid: str
    label: str
    role: str = "core"


@dataclass
class Basket:
    question: str
    langs: list[str]
    start: str
    end: str
    items: list[Item]
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    title_overrides: dict[str, str] = field(default_factory=dict)

    @property
    def months(self) -> list[str]:
        return months_between(self.start, self.end)

    def to_dict(self) -> dict:
        return asdict(self)


def _err(msg: str) -> BasketError:
    return BasketError(f"basket.json: {msg}")


def basket_from_dict(d: dict) -> Basket:
    def need(key: str, typ: type):
        if key not in d:
            raise _err(f"missing field '{key}'")
        if not isinstance(d[key], typ):
            raise _err(f"'{key}' must be a {typ.__name__}")
        return d[key]

    question = need("question", str)
    langs = need("langs", list)
    if not langs:
        raise _err("'langs' must list at least one Wikipedia language code, e.g. [\"uk\"]")
    for lang in langs:
        if not isinstance(lang, str) or not _LANG_RE.match(lang):
            raise _err(f"'langs' has invalid code {lang!r}; use Wikipedia codes like 'uk', 'pl'")
    if len(set(langs)) != len(langs):
        raise _err("'langs' lists a language twice")

    start, end = need("start", str), need("end", str)
    for key, value in (("start", start), ("end", end)):
        if not _MONTH_RE.match(value):
            raise _err(f"'{key}' must be YYYY-MM, got {value!r}")
    if start > end:
        raise _err(f"'start' ({start}) is after 'end' ({end})")
    if start < FIRST_MONTH:
        raise _err(f"'start' must be {FIRST_MONTH} or later (the pageviews API has no earlier data)")
    if len(months_between(start, end)) < MIN_WINDOW_MONTHS:
        raise _err(f"window 'start'..'end' must span at least {MIN_WINDOW_MONTHS} months")

    raw_items = need("items", list)
    if not raw_items:
        raise _err("'items' must list at least one Wikidata item; find QIDs with: wt resolve --search TERM --lang CODE")
    items: list[Item] = []
    seen: set[str] = set()
    for i, it in enumerate(raw_items):
        if not isinstance(it, dict):
            raise _err(f"items[{i}] must be an object with 'qid', 'label', 'role'")
        qid = it.get("qid")
        if not isinstance(qid, str) or not _QID_RE.match(qid):
            raise _err(f"items[{i}].qid must look like 'Q333', got {qid!r}")
        if qid in seen:
            raise _err(f"items[{i}].qid {qid} is listed twice")
        seen.add(qid)
        role = it.get("role", "core")
        if role not in ("core", "related"):
            raise _err(f"items[{i}].role must be 'core' or 'related', got {role!r}")
        items.append(Item(qid=qid, label=str(it.get("label") or qid), role=role))

    weights = d.get("weights") or dict(DEFAULT_WEIGHTS)
    if not isinstance(weights, dict) or set(weights) != set(DEFAULT_WEIGHTS):
        raise _err("'weights' must have exactly the keys growth, level, confidence")
    if not all(isinstance(v, (int, float)) and v >= 0 for v in weights.values()):
        raise _err("'weights' values must be non-negative numbers")
    if abs(sum(weights.values()) - 1) > 1e-6:
        raise _err(f"'weights' must sum to 1, got {sum(weights.values()):.3f}")

    overrides = d.get("title_overrides") or {}
    if not isinstance(overrides, dict):
        raise _err("'title_overrides' must be an object like {\"uk:Q333\": \"Астрономія\"}")
    for key, title in overrides.items():
        if not _OVERRIDE_RE.match(key) or not isinstance(title, str) or not title.strip():
            raise _err(f"'title_overrides' key {key!r} must look like 'uk:Q333' with a non-empty title")

    return Basket(question, list(langs), start, end, items, {k: float(v) for k, v in weights.items()}, dict(overrides))


def load_basket(ws: Path) -> Basket:
    path = ws / "basket.json"
    if not path.exists():
        raise BasketError(f"{path} not found; create a workspace with: wt init <slug>")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _err(f"not valid JSON (line {exc.lineno}: {exc.msg})") from None
    if not isinstance(data, dict):
        raise _err("must be a JSON object")
    return basket_from_dict(data)


def validate_dates(basket: Basket, today: date) -> None:
    last = last_complete_month(today)
    if basket.end > last:
        raise _err(f"'end' is {basket.end} but the latest complete month is {last}; set \"end\": \"{last}\"")


def basket_hash(basket: Basket) -> str:
    return text_sha(json.dumps(basket.to_dict(), sort_keys=True, ensure_ascii=False))[:16]


def stale_analysis_message(ws: Path, analysis: dict) -> str | None:
    """Why analysis.json no longer matches basket.json, or None when it still does."""
    recorded = analysis.get("provenance", {}).get("basket_hash")
    if not recorded or not (ws / "basket.json").exists():
        return None
    try:
        current = basket_hash(load_basket(ws))
    except BasketError as exc:
        return str(exc)
    if current != recorded:
        return f"basket.json changed since the last analysis; run: wt run {ws.name}"
    return None


# --- files ------------------------------------------------------------------


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- workspaces -------------------------------------------------------------


def work_root(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / WORK_DIR_NAME


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]
    if not slug:
        raise BasketError(f"cannot make a workspace name from {text!r}; use letters or digits")
    return slug


def init_workspace(slug: str, today: date, cwd: Path | None = None) -> Path:
    slug = slugify(slug)
    ws = work_root(cwd) / slug
    if (ws / "basket.json").exists():
        raise BasketError(f"workspace '{slug}' already exists at {ws}; edit its basket.json or pick another name")
    ws.mkdir(parents=True, exist_ok=True)
    end = last_complete_month(today)
    template = {
        "question": "",
        "langs": [],
        "start": shift_month(end, -23),
        "end": end,
        "items": [],
        "weights": dict(DEFAULT_WEIGHTS),
        "title_overrides": {},
    }
    write_json(ws / "basket.json", template)
    return ws


def resolve_workspace_path(arg: str, cwd: Path | None = None) -> Path:
    direct = Path(arg)
    if (direct / "basket.json").exists():
        return direct
    by_slug = work_root(cwd) / arg
    if (by_slug / "basket.json").exists():
        return by_slug
    raise BasketError(f"No workspace at '{arg}' (looked in {direct} and {by_slug}); create one with: wt init <slug>")


# --- run history ------------------------------------------------------------


def record_run(ws: Path, snapshot: dict) -> dict | None:
    """Store this run's snapshot; return the previous one (or None)."""
    hist = ws / "history"
    hist.mkdir(exist_ok=True)
    runs = sorted(hist.glob("run-*.json"))
    prev = read_json(runs[-1]) if runs else None
    write_json(hist / f"run-{len(runs) + 1:03d}.json", snapshot)
    return prev


def diff_snapshots(prev: dict | None, cur: dict) -> list[str]:
    if prev is None:
        return []
    lines: list[str] = []
    pb, cb = prev["basket"], cur["basket"]
    if (pb["start"], pb["end"]) != (cb["start"], cb["end"]):
        lines.append(f"window: {pb['start']}..{pb['end']} -> {cb['start']}..{cb['end']}")
    added = [lang for lang in cb["langs"] if lang not in pb["langs"]]
    removed = [lang for lang in pb["langs"] if lang not in cb["langs"]]
    if added:
        lines.append("languages added: " + ", ".join(added))
    if removed:
        lines.append("languages removed: " + ", ".join(removed))
    p_items = {i["qid"]: i["label"] for i in pb["items"]}
    c_items = {i["qid"]: i["label"] for i in cb["items"]}
    new_items = [f"{c_items[q]} ({q})" for q in c_items if q not in p_items]
    gone_items = [f"{p_items[q]} ({q})" for q in p_items if q not in c_items]
    if new_items:
        lines.append("items added: " + ", ".join(new_items))
    if gone_items:
        lines.append("items removed: " + ", ".join(gone_items))
    if pb["weights"] != cb["weights"]:
        lines.append(f"weights: {pb['weights']} -> {cb['weights']}")
    for lang, h in cur["headline"].items():
        old = prev["headline"].get(lang)
        if old and old != h:
            lines.append(
                f"{lang}: growth {fmt_pct(old['growth_norm_pct'])} -> {fmt_pct(h['growth_norm_pct'])}, "
                f"confidence {old['confidence']} -> {h['confidence']}"
            )
    return lines
