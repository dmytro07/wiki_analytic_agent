"""Map basket items (Wikidata QIDs) to article titles in each requested language."""

from __future__ import annotations

from pathlib import Path

from .api import WikiClient
from .workspace import BasketError, basket_hash, load_basket, write_json


def search(client: WikiClient, term: str, lang: str) -> list[dict]:
    return client.search_items(term, lang)


def resolve_workspace(ws: Path, client: WikiClient) -> dict:
    basket = load_basket(ws)
    links = client.sitelinks([it.qid for it in basket.items], basket.langs)
    unknown = [it.qid for it in basket.items if links.get(it.qid) is None]
    if unknown:
        raise BasketError(
            f"basket.json: unknown Wikidata item(s) {', '.join(unknown)}; "
            'find valid QIDs with: wt resolve --search "<term>" --lang <code>'
        )
    articles, gaps = [], []
    for lang in basket.langs:
        seen_titles: set[str] = set()
        for it in basket.items:
            override = basket.title_overrides.get(f"{lang}:{it.qid}")
            title = override or links[it.qid].get(lang)
            if not title or title in seen_titles:
                gaps.append({"lang": lang, "qid": it.qid, "label": it.label, "role": it.role})
                continue
            seen_titles.add(title)
            articles.append({
                "lang": lang, "qid": it.qid, "label": it.label, "role": it.role,
                "title": title, "source": "override" if override else "wikidata",
            })
    result = {"basket_hash": basket_hash(basket), "articles": articles, "gaps": gaps}
    write_json(ws / "resolved.json", result)
    return result
