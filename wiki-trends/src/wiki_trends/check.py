"""Validate narrative.md against analysis.json before it goes into a report."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .langs import language_name, mentions
from .workspace import file_sha, read_json, stale_analysis_message, text_sha, write_json

HEADLINE_MAX_WORDS = 15
FINDINGS_MIN, FINDINGS_MAX = 3, 5
RECOMMENDATION_MAX_WORDS = 80
TOTAL_MAX_WORDS = 230
SIGNIFICANCE = 0.05
SMALL_INT_MAX = 24  # plain counts like "3 articles" or "24 months" need no source
STANDARD_NUMBERS = {0.05, 0.01, 0.001}  # significance thresholds
SKIP_KEYS = {"monthly", "monthly_views"}  # raw series are not citable headline numbers

CAVEAT_WORDS = ("low confidence", "low-confidence", "uncertain", "tentative", "caution", "cautious",
                "weak evidence", "limited data", "unreliable", "not reliable")
QUALIFIERS = CAVEAT_WORDS + ("not significant", "not statistically", "insignificant", "no clear", "noisy",
                             "weak", "may ", "might ", "possibly", "not ", "no ", "flat", "stable", "declin")
GROWTH_RE = re.compile(r"\b(grow\w*|growth|ris(?:e|es|ing)|increas\w*|upward|surg\w*|gain\w*)\b", re.I)
NUMBER_RE = re.compile(
    r"(?<![\w.,\-−])(?P<sign>[-+−]?)(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?(?P<pct>\s?%)?(?![\w-])"
)
FLAT_PCT = 5.0  # same threshold as metrics.FLAT_PCT
COMMON_KEYS = ("window", "weights")  # numbers any sentence may cite
# "3x", "1.5M", "10k", "12pp": multipliers and units that analysis.json never contains, so they cannot be verified.
SUFFIX_NUMBER_RE = re.compile(r"(?<![\w.,])\d+(?:\.\d+)?\s?(?:x|×|k|K|M|pp)(?!\w)")
# Words that show a growth word is used about a decline ("growth fell", "no growth"), so it is not a false claim.
DECLINE_WORDS = ("not ", "no ", "n't", "declin", "fell", "fall", "drop", "decreas", "shrink", "down", "negative",
                 "lower", "lost", "loss")
NEGATIVE_NUMBER_RE = re.compile(r"[-−]\d")
CLAUSE_SPLIT_RE = re.compile(r"[.;:!?](?:\s|$)|\bbut\b|\bwhile\b|\bwhereas\b|\bhowever\b", re.I)


@dataclass
class Issue:
    line: int | None
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}" if self.line else self.message


@dataclass
class Narrative:
    headline: tuple[int, str] | None
    findings: list[tuple[int, str]]
    recommendation: str
    recommendation_line: int | None
    lines: list[tuple[int, str]]  # every content line, numbered from 1


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def parse_narrative(text: str) -> Narrative:
    headline, findings, rec, rec_line, lines = None, [], [], None, []
    section = "body"
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# ") and headline is None and section == "body":
            headline = (i, line[2:].strip())
            lines.append(headline)
            continue
        if re.match(r"^##\s*recommendation", line, re.I):
            section, rec_line = "rec", i
            continue
        if line.startswith("#"):
            section = "other"
            continue
        bullet = re.match(r"^[-*]\s+(.*)", line)
        if section == "body" and bullet:
            findings.append((i, bullet.group(1)))
            lines.append((i, bullet.group(1)))
            continue
        if section == "rec":
            rec.append(line)
        lines.append((i, line))
    return Narrative(headline, findings, " ".join(rec), rec_line, lines)


def _known_numbers(obj, out: set[float] | None = None) -> set[float]:
    out = set() if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if key not in SKIP_KEYS:
                _known_numbers(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _known_numbers(value, out)
    return out


def _number_pools(analysis: dict) -> tuple[set[float], dict[str, set[float]]]:
    """Numbers any sentence may cite, and numbers that belong to each language."""
    common: set[float] = set()
    for key in COMMON_KEYS:
        _known_numbers(analysis.get(key), common)
    per_lang = {lang: _known_numbers(d) for lang, d in analysis["languages"].items()}
    for row in analysis.get("ranking", []):
        _known_numbers(row, per_lang.setdefault(row["lang"], set()))
    return common, per_lang


def _unsupported_numbers(line: str, known: set[float]) -> list[str]:
    bad = [m.group(0).strip() for m in SUFFIX_NUMBER_RE.finditer(line)]
    for m in NUMBER_RE.finditer(line):
        frac = m.group("frac") or ""
        value = float(m.group("int").replace(",", "") + frac)
        plain_int = not frac and not m.group("pct") and not m.group("sign")
        if plain_int and (value <= SMALL_INT_MAX or 1990 <= value <= 2100):
            continue
        if value in STANDARD_NUMBERS:
            continue
        tolerance = 0.5 * 10 ** (-(len(frac) - 1 if frac else 0)) + 1e-9
        sign = m.group("sign")
        if sign:  # an explicit sign must match the sign in the data
            target = -value if sign in "-−" else value
            supported = any(abs(target - k) <= tolerance for k in known)
        else:
            supported = any(abs(value - abs(k)) <= tolerance for k in known)
        if not supported:
            bad.append(m.group(0).strip())
    return bad


def check_narrative(text: str, analysis: dict) -> list[Issue]:
    n = parse_narrative(text)
    langs = analysis["languages"]
    issues: list[Issue] = []

    if n.headline is None:
        issues.append(Issue(None, "missing headline: the first line must be '# <headline>'"))
    elif _words(n.headline[1]) > HEADLINE_MAX_WORDS:
        issues.append(Issue(n.headline[0], f"headline has {_words(n.headline[1])} words; max {HEADLINE_MAX_WORDS}"))
    if not FINDINGS_MIN <= len(n.findings) <= FINDINGS_MAX:
        issues.append(Issue(None, f"{len(n.findings)} findings; write {FINDINGS_MIN}-{FINDINGS_MAX} '- ' bullets "
                                  "before '## Recommendation'"))
    if n.recommendation_line is None or not n.recommendation:
        issues.append(Issue(None, "missing '## Recommendation' section with a paragraph under it"))
    elif _words(n.recommendation) > RECOMMENDATION_MAX_WORDS:
        issues.append(Issue(n.recommendation_line, f"recommendation has {_words(n.recommendation)} words; "
                                                   f"max {RECOMMENDATION_MAX_WORDS}"))
    total = sum(_words(t) for _, t in n.lines)
    if total > TOTAL_MAX_WORDS:
        issues.append(Issue(None, f"narrative has {total} words; max {TOTAL_MAX_WORDS} so the report fits one page"))

    common, per_lang = _number_pools(analysis)
    everything = common.union(*per_lang.values())
    for lineno, line in n.lines:
        named = [lang for lang in langs if mentions(line, lang)]
        known = common.union(*(per_lang[lang] for lang in named)) if named else everything
        for num in _unsupported_numbers(line, known):
            issues.append(Issue(lineno, f"number '{num}' is not in analysis.json; copy numbers exactly as the summary prints them"))

    not_significant = {
        lang for lang, d in langs.items()
        if d["basket"] is None or d["basket"]["trend_p"] is None or d["basket"]["trend_p"] >= SIGNIFICANCE
    }
    falling = {
        lang: d["basket"]["growth_norm_pct"] for lang, d in langs.items()
        if d["basket"] and d["basket"]["growth_norm_pct"] is not None and d["basket"]["growth_norm_pct"] <= -FLAT_PCT
    }
    for lineno, line in n.lines:
        for clause in CLAUSE_SPLIT_RE.split(line):
            if not GROWTH_RE.search(clause):
                continue
            low = clause.lower()
            named = [lang for lang in langs if mentions(clause, lang)]
            targets = named or (list(langs) if len(langs) == 1 else [])
            describes_decline = any(w in low for w in DECLINE_WORDS) or NEGATIVE_NUMBER_RE.search(clause)
            fell = [lang for lang in targets if lang in falling]
            if fell and not describes_decline:
                issues.append(Issue(lineno, "claims growth for " + ", ".join(
                    f"{language_name(l)} (share of views fell {falling[l]:.1f}%)" for l in fell)
                    + "; describe it as a decline"))
                continue
            if any(q in low for q in QUALIFIERS):
                continue
            bad = [lang for lang in targets if lang in not_significant]
            if bad:
                issues.append(Issue(lineno, f"claims growth for {', '.join(language_name(l) for l in bad)} but the "
                                            "trend is not statistically significant; say 'no clear trend' or add "
                                            "'not statistically significant'"))

    rec = n.recommendation.lower()
    if rec and not any(word in rec for word in CAVEAT_WORDS):
        for lang, d in langs.items():
            if d["confidence"] == "Low" and (len(langs) == 1 or mentions(rec, lang)):
                issues.append(Issue(n.recommendation_line, f"recommendation covers {language_name(lang)}, whose "
                                                           "confidence is Low; add a caveat such as 'low confidence' or 'tentative'"))
    return issues


def check_workspace(ws: Path) -> list[Issue]:
    analysis_path, narrative_path = ws / "analysis.json", ws / "narrative.md"
    if not analysis_path.exists():
        return [Issue(None, f"analysis.json not found; run: wt run {ws.name}")]
    if not narrative_path.exists():
        return [Issue(None, "narrative.md not found; write it following reference/report-guide.md")]
    analysis = read_json(analysis_path)
    stale = stale_analysis_message(ws, analysis)
    if stale:
        return [Issue(None, stale)]
    text = narrative_path.read_text(encoding="utf-8")
    issues = check_narrative(text, analysis)
    write_json(ws / "check.json", {
        "passed": not issues,
        "narrative_sha": text_sha(text),
        "analysis_sha": file_sha(analysis_path),
        "issues": [str(i) for i in issues],
    })
    return issues
