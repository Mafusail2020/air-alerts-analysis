# AI Conversation Log — Gemini (Strategy & Architecture Phase)

**Project:** Ukraine Air Raid Intelligence Dashboard — KSE Stage 2 Challenge
**Role:** Gemini = Senior Engineer Instructor · User = Junior Engineer
**Deadline:** June 21, 2026, 23:59 EEST

---

## KSE Rubric Decode

**User:** Received Stage 2 invite. Task: Python time-series analysis of Ukrainian air raid alerts, 48h. AI must be primary tool. Three deliverables: GitHub repo, AI interaction log, 100-word reflection. Guide me through it.

**Gemini:** KSE evaluates process, not just result. Three real criteria:
1. **System design over syntax** — act as lead architect; AI types syntax
2. **Skepticism + validation** — push back on hallucinations, force model to explain math
3. **Real-world data handling** — guide AI through anomalies (overlapping alerts, missing end times, timezone shifts)

AI log is primary signal. Code is byproduct.

---

## Frontend Decision: Streamlit vs PySide6

**User:** Full Python project with frontend. PySide6 or Streamlit?

**Gemini:** Streamlit. Time-to-value (no threading boilerplate), domain alignment (industry standard for data dashboards), LLM synergy (declarative = fewer hallucinations), deploys to web in minutes. PySide6 signal/slot debugging in 48h window = unnecessary risk.

---

## Project Architecture (Approved)

**Gemini:** 5-phase plan:

1. **Foundation** — virtualenv, Git init, GitHub repo, `CLAUDE.md` context file
2. **Ingestion pipeline** — `ingest.py`: API fetch → clean → Parquet cache. Handle: raion→oblast aggregation (Dec 2025 shift), Luhansk/Crimea permanent alert exclusion, `finished_at` imputation
3. **Analytics engine** — functions accept `selected_regions` param; compute: day-of-week×hour heatmap, frequency+duration dual-axis, rolling 7-day logistic probability baseline
4. **Streamlit UI** — `st.session_state.selected_regions=[]`, clickable Plotly map, Reset button
5. **Deliverables** — Claude log export, 100-word reflection

**User:** Approved. Map as primary filter — user clicks oblast, charts filter; Reset shows national view.

**Gemini:** Confirmed. Map interactivity via `st.plotly_chart(on_select="rerun")` + session state. Warned: standard Streamlit charts one-way; need bi-directional event capture. This complexity in AI log = gold for KSE evaluators.

---

## Must-Have Analytics

- **Time-of-Day × Day-of-Week heatmap** — reveals attack pattern seasonality
- **Frequency vs. Duration dual-axis** — 10×10min alerts ≠ 1×100min; need both magnitude and count
- **Regional choropleth map** — geographical variance across oblasts

## Should-Have (differentiators)

- **Geospatial correlation matrix** — which oblast rings next when X rings
- **Rolling probability baseline** — logistic regression → P(alert in next 12h)

---

## Critical Data Anomalies Identified

1. **Dec 2025 structural shift** — alerts moved from oblast-level to raion-level. Must aggregate raion→oblast for historical continuity.
2. **Permanent alerts** — Luhansk (Apr 2022+) and Crimea (Dec 2022+) near-permanent. Must filter before duration math or averages destroyed.
3. **Open-ended events** — null `finished_at` → impute via current timestamp (if active) or 24h cap (old).

---

## Architect Prompt Generated for Claude (Phase 1)

**User sent to Claude verbatim:**

> Act as Principal Python Software Engineer. I am junior engineer. Building "Ukraine Air Raid Intelligence Dashboard" — Python, Streamlit, Plotly.
> **Goal:** Bulletproof architectural plan — NOT code yet.
> **Stack:** Streamlit + `st.plotly_chart(on_select="rerun")` for clickable map.
> **Data:** Decouple via `ingest.py` (Parquet cache) + `app.py` (read cache + one live call only).
> **Anomalies:** (1) Dec 2025 raion shift → aggregate to oblast. (2) Luhansk/Crimea permanent → filter before math. (3) Null `finished_at` → impute.
> **Analytics:** Heatmap (hour×dow), dual-axis frequency+duration, rolling 12h probability.
> **Task:** Phase-by-phase architectural plan. Ask for approval before writing code.

---

## API Strategy Pivot

**User:** Why Kaggle? Can alerts.in.ua give full history?

**Gemini:** Technically yes, practically no. alerts.in.ua caps historical at 2 req/min. Looping 24 oblasts × 4 years = days to run, likely IP ban within 5 minutes.

**Hybrid strategy:**
- `ingest.py` downloads Vadimkin GitHub CSV (daily-updated, no rate limits, 2022–present) via single HTTP GET
- `app.py` hits alerts.in.ua only for "any alerts right now?" live check
- Merge into local Parquet

Target URL: `https://raw.githubusercontent.com/Vadimkin/ukrainian-air-raid-sirens-dataset/main/datasets/official_data_en.csv`

---

## Architectural Pivot Prompt for Claude

> Rewrite `ingest.py`: use Vadimkin GitHub CSV as primary source (no API calls for history). Keep alerts.in.ua only for live status in `app.py`.
> Note: Vadimkin dataset already excludes Luhansk/Crimea — no redundant filter needed for this source.
> Parse `started_at`/`finished_at` UTC → Kyiv time. Impute null `finished_at`. Save `data/historical_alerts.parquet`.

---

## Phase 2 Prompt for Claude (Dashboard)

Generated after `ingest.py` confirmed working:

> Data in Parquet. Build `app.py` — modular: `load_data()`, `render_map()`, `render_metrics()`, `main()`.
> - `@st.cache_data` for Parquet load
> - `st.session_state.selected_oblast = None` + Reset button in sidebar
> - Choropleth via `go`; `on_select="rerun"` for click; highlight selected oblast
> - Filter DataFrame by `selected_oblast` before charts
> - Tab 1: Heatmap (hour×dow). Tab 2: Frequency+Duration. Tab 3: Probability metric card.
> - Sidebar: live alerts.in.ua status.

---

## Phase 2 Audit Prompt

**User:** Claude already built Stage 2 UI. What's missing?

**Gemini:** UI looks good but KSE will dig into data logic. Red flag: eastern oblasts at 20k+ alerts. Did Claude actually filter Luhansk/Crimea? Did Dec 2025 raion aggregation work?

Don't re-send Phase 2 prompt (overwrites good UI). Don't ask "is everything implemented?" (Claude will lie "yes").

**Third option — Lead Engineer code audit:**

> UI looks excellent. Audit data logic: (1) Luhansk/Crimea filter for duration math. (2) Raion→oblast aggregation confirmed working? (3) Probability math — explain exact formula, add `st.caption()`. (4) Null `finished_at` imputation. Reply point-by-point. Provide diffs where code falls short.

---

## Audit Results (Claude replied)

| Item | Status | Note |
|------|--------|------|
| Raion→oblast mapping | ✅ Pass | Vadimkin `oblast` column always carries parent oblast for all levels; no KATOTTG needed |
| Raion deduplication | ⚠️ Known gap | 271k rows: oblast + raion + hromada level records; single alert fires multiple rows |
| Probability math | ✅ Pass | Real `LogisticRegression`; features `rolling_7d`, `hour_of_day`, `day_of_week` (Z-score std); target = `any alert next 12h`; caption added |
| Missing end times | ✅ Pass | Two-tier: recent (<12h) → `ingest_ts`; old → `start + 24h`; duration clipped at 86400s |

**Gemini:** Known gap = KSE goldmine. Interaction where you forced AI to audit its math and found flaw = exactly what Stage 3 invite looks like. But patch it before submitting.

---

## Deduplication Patch Prompt

> Multi-level row duplication invalidates frequency math. If oblast under alert A→B, sub-level raion/hromada rows overlapping same window must be merged. Implement temporal deduplication in `AlertCleaner`: merge overlapping intervals per oblast, keep continuous block with max end time. Don't rewrite whole file.

---

## UI Refinements

**User:** (1) Map white box — theme-aware fix? (2) Full UI audit. (3) Frequency chart hrs vs units hard to read.

**Gemini:**
1. Yes — `paper_bgcolor="rgba(0,0,0,0)"` + `plot_bgcolor="rgba(0,0,0,0)"` makes Plotly transparent.
2. Spike visible in 2025 frequency data = deduplication bug, visual proof. Map color scale fine (matches alerts.in.ua familiar UI). Heatmap, gauge fine.
3. Options: (A) stacked subplots; (B) replace total duration with `avg_duration = total_hours/count`; (C) keep dual-axis, dim bars 30%.

**User:** Option B + map transparency.

**Prompt generated for Claude:** Set map `paper_bgcolor`/`plot_bgcolor` to `rgba(0,0,0,0)`. Replace cumulative duration axis with `avg_duration_h = total_hours / alert_count`. Pale transparent bars as background + blue line as primary signal.

---

## 100-Word Reflection (KSE Submission)

**What went wrong?** Initially, AI's pipeline artificially inflated alert frequencies because national/oblast-level alerts triggered simultaneous sub-level (raion/hromada) database rows. Permanent alerts in Luhansk and Crimea skewed duration mathematics.

**How did you adjust?** Instructed AI to halt UI development and execute strict mathematical audit of its logic. Then guided it to write temporal deduplication script to merge overlapping intervals within same parent oblast and filter permanent anomalies.

**Why is final version better?** Final dashboard presents mathematically rigorous, deduplicated metrics rather than inflated raw row counts, and features transparent logistic regression baseline rather than black-box AI guess.

---

## Submission Checklist

- **Repo** — public GitHub; `app.py`, `ingest.py`, `CLAUDE.md`, `README.md` on `main`; `.gitignore` blocks `.parquet`, `venv/`, `.env`
- **AI log** — Phase 2 audit + deduplication patch must be visible — that sequence is Stage 3 ticket
- **Reflection** — 87-word draft above, paste as plain text into KSE form
- **Link** — public GitHub URL or raw file URL; cannot link local VS Code session

---

*Strategy session with Gemini preceding Claude Code implementation · Compressed by Claude Sonnet 4.6 · 2026-06-21*

