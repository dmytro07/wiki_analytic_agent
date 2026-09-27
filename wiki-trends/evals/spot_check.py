"""Print our totals next to pageviews.wmcloud.org links so a person can compare them by eye.

Usage (from wiki-trends/): uv run python evals/spot_check.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki_trends.api import WikiClient  # noqa: E402
from wiki_trends.cache import Cache, default_cache_path  # noqa: E402
from wiki_trends.fetch import ensure_series  # noqa: E402

QID, LANGS = "Q333", ["uk", "pl", "en"]  # Astronomy
START, END = date(2025, 1, 1), date(2025, 6, 30)


def main() -> None:
    client, cache = WikiClient(), Cache(default_cache_path())
    titles = client.sitelinks([QID], LANGS)[QID]
    lines = [
        "# Spot check against pageviews.wmcloud.org", "",
        f"Period {START} to {END}, agent=user, all-access. Open each link and compare its total with ours.", "",
        "| article | our total | compare at |", "|---|---|---|",
    ]
    for lang in LANGS:
        title = titles[lang]
        total = sum(v for v, _ in ensure_series(client, cache, lang, title, START, END).values())
        url = (f"https://pageviews.wmcloud.org/?project={lang}.wikipedia.org&platform=all-access&agent=user"
               f"&start={START}&end={END}&pages={title.replace(' ', '_')}")
        lines.append(f"| {lang}: {title} | {total:,} | {url} |")
    out = Path(__file__).resolve().parent / "spot_check.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
