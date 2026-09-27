# wiki-trends: an Agent Skill for topic and language decisions from Wikipedia pageviews

B2C teams choosing the next course, topic or launch language can ask an agent questions like
"is interest in astronomy growing on Ukrainian Wikipedia, and can we trust it?". The skill's CLI fetches
pageviews, judges how far the trend can be trusted, draws charts, checks the agent's write-up against the data,
and renders a one-page PDF.

## Install

Requirements: [uv](https://docs.astral.sh/uv/) and internet access to wikimedia.org and wikidata.org.

```bash
cd wiki-trends && uv sync            # reproducible env from uv.lock
ln -s "$PWD" ~/.claude/skills/wiki-trends   # make it available to Claude Code
export WIKI_TRENDS_CONTACT="you@example.com"  # sent in the User-Agent, as Wikimedia asks
```

Then ask Claude Code (Haiku 4.5 is enough) e.g. *"Compare interest in intermittent fasting on Polish and Czech
Wikipedia over the last two years."*

## How it works

```
basket.json ──resolve──▶ resolved.json ──fetch──▶ data.csv ──analyze──▶ analysis.json ──chart──▶ charts/*.png
 (agent picks                (Wikidata          (daily views,        (metrics, 7 trust checks,
  3–8 Wikidata items)         sitelinks)         SQLite cache)        confidence, ranking)
                                                                            │
narrative.md (agent) ──check──▶ check.json ──report──▶ report.pdf (one A4 page)
```

`wt run <slug>` runs the first four steps. Each request gets a workspace under `./wiki-trends-work/<slug>/`,
so follow-ups ("add Polish", "use three years") edit `basket.json` and rerun: only missing days are downloaded,
and the output lists what changed.

## Design decisions

- **The code judges the evidence; the agent explains it.** Metrics, trust checks and the confidence rule are
  deterministic Python, so a small model gives the same verdict as a large one. The agent picks the basket and
  writes prose.
- **Topic = a basket of Wikidata items.** One article is fragile (renames, one viral day). The agent picks
  3–8 items from `resolve --search` results (it never invents QIDs); Wikidata sitelinks give the title in every
  language, and missing articles are reported as coverage gaps.
- **Share of edition traffic, not raw views.** Editions differ ~100× in size and overall Wikipedia traffic is
  drifting, so growth is measured on views per million edition views; raw counts are always shown beside it.
- **Seven trust checks** (spike dependence, article concentration, edition-wide effect, low volume, coverage,
  significance, window sensitivity) → High / Medium / Low confidence. See `reference/methodology.md`.
- **A check gate before the PDF.** `wt check` rejects numbers that are not in `analysis.json`, "growth" claims
  for non-significant trends, and recommendations on Low-confidence languages without a caveat. `wt report`
  refuses to render until the current narrative has passed.
- **Built for a cheap model.** One wrapper script, a `run` shortcut for the happy path, summaries of at most
  20 lines, `--json` when needed, and single-line error messages that name the fix.
- **Reproducible and self-contained.** Pure-wheel dependencies locked in `uv.lock`; matplotlib renders the PDF
  (no system libraries); everything lives in this directory.

## Verification

How the AI-written code and output were checked:

1. **Unit tests with known answers** (`uv run pytest`, no network): synthetic workspaces where the
   right answer is known in advance (flat, steady growth, a single spike, seasonal only, edition-wide growth,
   one article carrying growth, low volume, a language with no articles) pin every metric, check and
   confidence level. Recorded fixtures cover the API client, cache, fetch, narrative check, one-page PDF and CLI.
2. **Live consistency tests** (`uv run pytest -m live`): the sum of our daily views equals the API's own monthly
   figure; Wikidata sitelinks and edition totals return plausible real values.
3. **Manual spot check**: `evals/spot_check.md` lists our totals with pageviews.wmcloud.org links for
   the same query, to compare by eye.
4. **End-to-end evals on Claude Haiku 4.5**: `evals/run_evals.py` runs the brief's three example requests plus a
   follow-up, a thin-data wiki and an ambiguous topic through `claude -p`, then grades the artifacts
   deterministically (used the CLI, no hand-written API calls, valid basket, one-page PDF, check passes,
   confidence stated and matching the analysis, limitations mentioned). Final scorecard and what was changed
   between runs: [`evals/REPORT.md`](evals/REPORT.md). Raw run output goes to the git-ignored `evals/results/`.

## Limitations

- Pageviews measure attention, not willingness to pay.
- `agent=user` removes known bots, but some automated traffic remains.
- Redirects and former titles are not counted.
- A language edition is not a country (Spanish, English, Portuguese readers are spread worldwide).
- Monthly series are autocorrelated, so trend p-values are optimistic; the other checks compensate.
- Non-Latin scripts render with DejaVu Sans; CJK titles in the PDF footer may show missing glyphs.

## Roadmap

1. **Redirects and renames**: sum views over each article's redirects (MediaWiki `prop=redirects`) and
   former titles; this matters most for young or renamed articles.
2. **Basket suggestions**: propose related items from categories, Wikidata properties and outgoing links, ranked
   by views, for the user to approve, so baskets are less dependent on the agent's knowledge.
3. **Clickstream**: use the monthly clickstream dumps to see which pages send readers to the topic, and
   discover adjacent topics.
4. **Scale**: for many topics × languages, switch from the per-article API to the monthly pageview dumps
   loaded into DuckDB/Parquet, with batch analysis and a ranked table across hundreds of candidates.
5. **Forecasting**: seasonal forecasts with uncertainty bands, and change-point detection instead of fixed
   12-month comparisons.
6. **Audience size**: bundle speaker and internet-user counts (with citations) to turn shares into
   estimated audiences, with the extra assumptions stated in the report.
7. **Monitoring**: scheduled reruns of saved baskets with alerts when a trend or confidence level changes.

## Layout

```
SKILL.md                 agent instructions
reference/               methodology and narrative guide (read on demand)
scripts/wt               CLI wrapper (uv run)
src/wiki_trends/         api, cache, resolve, fetch, metrics, trust, analyze, charts, check, report, cli
tests/                   unit tests (+ live tests marked `live`)
evals/                   Haiku eval harness, cases, spot check, results
```
