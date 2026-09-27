# Writing narrative.md

`WT check` enforces this format. Use this template:

```markdown
# <Headline: the answer in at most 15 words>

- <finding with a number copied from the summary>
- <finding>
- <finding>

## Recommendation

<At most 80 words: what to research or build next and why, with caveats.>
```

## Rules that `WT check` enforces

- Headline ≤15 words. 3–5 findings as `- ` bullets. `## Recommendation` ≤80 words. Whole file ≤230 words.
- Every number must exist in analysis.json. Rounding is allowed (18.2 → "18%"), inventing is not ("18.4%").
  Years, dates and small counts (≤24, like "3 articles") are ignored.
  Do not compute differences, ratios or sums yourself. Monthly raw values are not citable.
- Growth words (growing, rising, increase, gain…) about a language whose trend is not significant
  (p ≥ 0.05) need a qualifier in the same clause: "not statistically significant", "no clear trend", "may".
- If the recommendation covers a language with Low confidence (or it is the only language),
  it must contain a caveat: "low confidence", "tentative" or "uncertain".

## What to say

- **Growth** = change in the topic's *share* of the edition's views, last 12 months vs the 12 before.
  Mention raw views when they point the other way (`edition_effect`).
- **Level** = views per million edition views: how big the audience is relative to that Wikipedia.
- Name flagged checks in plain words.
- **Recommendation** = what to research next and why, not "launch now". For comparisons, name the top 1–2
  languages by score and say what would change the ranking (e.g. other weights).

| Situation | Say |
|---|---|
| High confidence, growth ≥ +5% | "Interest is growing: +X% share year over year (significant, p=…)." |
| `significance` warn | "No clear trend (p=…)." |
| `spike_dependence` fail | "The rise comes from a short spike, not a lasting trend." |
| `edition_effect` warn | "Raw views fell X% but the topic's share rose Y%: the whole edition shrank." |
| `coverage` fail | "No <language> article exists for this topic: a content gap, not proof of low interest." |
| `low_volume` | "Too few views to measure a trend reliably." |

## Example

```markdown
# Polish interest in intermittent fasting is growing; Czech is flat

- Polish: +18.2% share of views year over year, significant trend (p=0.004).
- Czech: +3.1%, not statistically significant (p=0.41).
- Polish level is 41.3 views per million vs 12.0 for Czech.

## Recommendation

Research Polish users next. Czech is tentative: low confidence, revisit later.
Pageviews show attention, not willingness to pay, so validate with interviews.
```
