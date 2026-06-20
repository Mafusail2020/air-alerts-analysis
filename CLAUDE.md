# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

> **Project Context:** We are building a time-series analytics dashboard for Ukrainian air raid alerts using Python, Streamlit, and Plotly. 

> **Core Directive:** Do not write large blocks of code without approving the architecture with me first. I am the Lead Engineer; you are the Junior Developer. Always prioritize handling data anomalies (missing end times, regional shifts post-Dec 2025, permanent alerts in Luhansk/Crimea) before calculating mathematical models.

Air alerts analysis project. Phase 1 architecture complete — all source files generated and approved.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # then add ALERTS_API_KEY
python ingest.py --full       # first run: full historical load
streamlit run app.py          # start dashboard
```

### Data Sources

**Historical (primary):** `Vadimkin/ukrainian-air-raid-sirens-dataset` GitHub CSV.
- URL: `https://raw.githubusercontent.com/Vadimkin/ukrainian-air-raid-sirens-dataset/main/datasets/official_data_en.csv`
- No API key. No rate limits. Daily updated. No `ingest.py` rate-limit concerns.
- Luhansk + Crimea **already excluded** from this dataset — `is_permanent_outlier` logic is a no-op but kept for schema compatibility.
- `location_oblast` is present on every row (including raion-type records) → `mapper.py` not needed for this source; `CsvFetcher._normalize_schema()` maps directly to `oblast_name`.

**Live status (secondary):** `alerts.in.ua` API — used only in `app.py` for "active alerts now?" check.
- Token issued manually by the alerts.in.ua team — no self-serve signup.
- Request access via Telegram: `@alerts_in_ua_bot`
- Non-commercial use is free; approval typically within hours to a day
- Paste the token into `.env` as `ALERTS_API_KEY=<your_token>`

## Architecture (Phase 1 — complete)

- `ingest.py` — CLI: fetches API, writes `data/cache/alerts_raw.parquet` + `alerts_agg.parquet`. Run on cron or manually.
- `app.py` — Streamlit dashboard: reads cache only; one live API call per load for active-alert status.
- `src/api/` — imported only by `ingest.py`. Never import from `app.py`.
- `src/pipeline/` — imported only by `ingest.py`. Anomaly resolution order: outlier flag → impute end times → compute duration.
- `src/analytics/` + `src/ui/` — imported only by `app.py`.

## Data Anomalies (hard constraints — resolve before any math)

1. **Permanent outliers:** Luhansk Oblast (Apr 2022+) and Autonomous Republic of Crimea (Dec 2022+) → `is_permanent_outlier=True`, excluded from all aggregates, shown as status badges.
2. **Open-ended events:** null `end_time` → cap at `ingest_ts` if active, else `start_time + 24h`.
3. **Post-Dec 2025 raion mapping:** `RAION_EPOCH = 2025-12-01`. API returns raion-level regions after this date → `src/pipeline/mapper.py` normalizes to oblast via KATOTTG lookup.
