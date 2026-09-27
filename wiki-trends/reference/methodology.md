# Methodology

## Data

- Source: Wikimedia Pageviews API, daily, `access=all-access`, `agent=user` (known bots and crawlers
  excluded; some automated traffic still gets through). Titles come from Wikidata sitelinks.
- The basket is the unit of analysis: 3–8 Wikidata items. A basket is sturdier than one article.
- `fetch` downloads the window plus 3 months on each side (for the window check). The current month
  and the last days (publication lag) are never used. Past days are cached forever.
- Articles that did not exist for part of the range get zeros and are flagged by `coverage`.

## Metrics (per language)

| Metric | Definition |
|---|---|
| `level_norm` | Median over months of (basket views / edition views × 1,000,000) |
| `level_raw` | Median monthly basket views |
| `growth_norm_pct` | Mean monthly share, last 12 months vs previous 12 (same calendar months, so seasonality cancels). Windows under 24 months: second half vs first half (`growth_method = half_split`) |
| `growth_raw_pct` | Same on raw views |
| `trend_pct_per_year` | Theil–Sen slope of log monthly share, as % per year (robust to outliers) |
| `trend_p` | Mann–Kendall test (Kendall's tau of share vs time) |
| `seasonality` | Mean correlation between consecutive years' detrended monthly shapes (0 = none, 1 = identical each year) |

"Flat" means |growth| < 5%.

## Trust checks

| Check | fail | warn |
|---|---|---|
| `spike_dependence` | growth flips or becomes flat when computed on monthly medians, or with the top 1% of days removed | growth halves in either variant |
| `article_concentration` | removing any one article flips or flattens growth | one article > 60% of views, or single-article basket |
| `edition_effect` | — | raw and share growth point in opposite directions |
| `low_volume` | median < 10 views/day | median < 50 views/day |
| `coverage` | no article in this language for any item | core item missing; article with no data or starting mid-window |
| `significance` | — | p ≥ 0.05 or too few months |
| `window_sensitivity` | — | growth flips sign when the window moves ±3 months |

## Confidence

Any `fail` → **Low**. Two or more `warn` → **Medium**. Otherwise **High**.

## Ranking (several languages)

Score = w_growth × G + w_level × L + w_confidence × (High 1, Medium 0.5, Low 0), where
G = growth on an absolute scale (−50% or less → 0, 0% → 0.5, +50% or more → 1), so a declining language never
earns growth credit just for declining least, and L = level ÷ the largest level among the compared languages.
Default weights 0.4 / 0.4 / 0.2; set them in basket.json. The weights are printed with every score.

## Known limitations

- Pageviews measure attention, not purchase intent.
- Views of redirects and of former titles are not counted.
- Monthly values are autocorrelated, so p-values are optimistic; the other checks compensate.
- Readers of a language edition are not the same as residents of a country (e.g. Spanish, English).
- Mobile-app views are included in `all-access`; the Wikipedia app's share differs by language.
