---
name: wiki-trends
description: Measures interest in topics with Wikipedia pageviews across language editions, checks how far a trend can be trusted, and produces charts plus a one-page PDF report. Use when someone asks whether interest in a topic is growing, wants to compare interest between languages or markets, or needs data to choose the next course, topic or launch language.
compatibility: Needs uv (https://docs.astral.sh/uv/) and internet access to wikimedia.org and wikidata.org.
---

# wiki-trends

Answers "is interest in X growing, where, and can we trust it?" with Wikipedia pageviews.
The CLI does all data work. **Never write your own code to call Wikipedia/Wikidata APIs or to compute metrics.**

`WT` below means this skill's `scripts/wt`, called by full path, e.g. `/path/to/skills/wiki-trends/scripts/wt`.
Run it from the user's project directory; workspaces go to `./wiki-trends-work/<slug>/`.
The first call installs dependencies (about 30 s).
**Run every `WT` command in the foreground with a long timeout (600000 ms).** Never run it in the background,
never add `sleep`, and never end your turn while a command is still running.

## Workflow (do every step)

1. **Find Wikidata items.** For each concept run `WT resolve --search "intermittent fasting" --lang en`.
   Use only QIDs printed by this command; never guess one.
   Build a basket of 3–8 items: 1–2 `core` (the topic itself) and the rest `related` (sub-topics people read about).
   Example for an astronomy course: Astronomy (core), Telescope, Planet, Galaxy, Solar System (related).
2. **Create a workspace:** `WT init astronomy-uk`, then edit `wiki-trends-work/astronomy-uk/basket.json`:
   ```json
   {"question": "Is interest in astronomy growing on Ukrainian Wikipedia?",
    "langs": ["uk"],
    "start": "2023-09", "end": "2025-08",
    "items": [{"qid": "Q333", "label": "astronomy", "role": "core"},
              {"qid": "Q4213", "label": "telescope", "role": "related"}],
    "weights": {"growth": 0.4, "level": 0.4, "confidence": 0.2},
    "title_overrides": {}}
   ```
   - `langs`: Wikipedia codes: pl, cs, uk, es, pt, tr, vi, id, de, fr, it, ja …
   - Keep `start`/`end` from the template (the last 24 complete months) unless the user asks for another period.
     "Last three years" → move `start` 12 months earlier. At least 6 months.
   - `weights` only matter when comparing languages. Change them when the user says what "promising" means
     (e.g. "audience size matters most" → level 0.6, growth 0.2, confidence 0.2). They must sum to 1.
3. **Run the pipeline:** `WT run astronomy-uk`. Read the summary it prints.
4. **Judge the evidence.** For each language read `confidence` and the flagged checks:
   - `spike_dependence` → growth comes from a few days (news, viral post), not a lasting trend.
   - `article_concentration` → one article drives the result; consider adding related items.
   - `coverage` → an article is missing or new. Wrong article? Add
     `"title_overrides": {"uk:Q333": "Астрономія"}` and rerun.
   - `edition_effect` → the whole language edition's traffic moved; trust the normalized (share) number.
   - `significance` → do not call it growth; say "no clear trend".
   - `low_volume` → too few views to measure; say so.
   Fix what you can by editing basket.json and rerunning `WT run` (at most 2 reruns).
   Full numbers: `wiki-trends-work/<slug>/analysis.json`. Method details: `reference/methodology.md`.
5. **Write** `wiki-trends-work/<slug>/narrative.md`. Read `reference/report-guide.md` first and follow its template.
   Copy numbers exactly as the summary prints them.
6. **Check it:** `WT check astronomy-uk`. Fix every listed problem and run check again until it passes.
7. **Render the PDF:** `WT report astronomy-uk`.
8. **Reply to the user** in at most 8 lines:
   - the answer and the key numbers
   - confidence (High/Medium/Low) and the main reason
   - one limitation (pageviews show attention, not willingness to pay)
   - the PDF path and the basket items used, so they can change them

## Follow-up requests

Reuse the same workspace. Edit `basket.json` (add languages or items, change `start`/`end` or `weights`)
and run `WT run <slug>` again. Only missing data is downloaded and the output lists what changed.
Then redo steps 4–8 in full. Every reply, including follow-ups, must state the confidence level for each
language (e.g. "Confidence: High") and one limitation, exactly as in step 8. A new topic gets a new workspace.

## Commands

| Command | Does |
|---|---|
| `WT resolve --search TEXT --lang CODE` | Top Wikidata items for a term |
| `WT init SLUG` | New workspace with a basket.json template |
| `WT run SLUG` | resolve → fetch → analyze → chart, then a summary |
| `WT check SLUG` | Validates narrative.md against the data |
| `WT report SLUG` | One-page PDF (refuses until check passes) |
| `WT fetch SLUG`, `WT analyze SLUG`, `WT chart SLUG` | Single steps, for debugging |

Add `--json` to any command for machine-readable output.

## Rules

- Every number you state comes from `WT` output or analysis.json. Do not compute new numbers.
- Always state confidence. Low confidence → say the result is uncertain and why.
- Say that pageviews measure attention, not demand to pay, whenever you recommend something.
- Ambiguous topic (e.g. "Mercury")? Pick the meaning that fits the user's context, say which one you used.
- If a command prints `error: ...`, do what the message says. After a rate-limit error, run the same
  command again once (downloaded data is cached, so it resumes).
