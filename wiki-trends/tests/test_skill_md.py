import re
from pathlib import Path

from wiki_trends.cli import build_parser

SKILL = Path(__file__).resolve().parents[1]
TEXT = (SKILL / "SKILL.md").read_text(encoding="utf-8") if (SKILL / "SKILL.md").exists() else ""


def frontmatter():
    m = re.match(r"^---\n(.*?)\n---\n", TEXT, re.S)
    assert m, "SKILL.md must start with YAML frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


def test_frontmatter():
    fields = frontmatter()
    assert fields["name"] == "wiki-trends" == SKILL.name
    assert 0 < len(fields["description"]) <= 1024
    assert len(TEXT.splitlines()) <= 150


def test_referenced_files_exist():
    refs = set(re.findall(r"`((?:reference|scripts)/[\w./-]+)`", TEXT))
    assert refs
    for ref in refs:
        assert (SKILL / ref).exists(), ref


def test_documented_commands_exist():
    commands = set(re.findall(r"`WT (\w+)", TEXT))
    choices = build_parser()._subparsers._group_actions[0].choices
    assert commands and commands <= set(choices)
