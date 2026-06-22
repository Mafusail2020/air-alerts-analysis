# Ukraine Air Raid Intelligence Dashboard (Built for KSE Stage 2 Test task)

Interactive time-series analytics dashboard for Ukrainian air raid alerts. Built with Python, Streamlit, and Plotly.

---

## Features

- **Choropleth map** — click any oblast to filter all panels. Selected region highlighted; others dimmed to 80%.
- **Seasonality heatmap** — alert frequency by hour of day (Kyiv time, UTC+2) × day of week.
- **Frequency vs. duration chart** — weekly alert count (bars) overlaid with average alert duration per event (line). Rising line = longer individual alerts; rising bars = higher event frequency.
- **Alert probability gauge** — logistic regression model per oblast. Features: rolling 7-day count, hour of day, day of week (Z-score standardised). Target: P(≥1 alert in next 12 hours).
- **Live status bar** — calls `alerts.in.ua` API once per load to show currently active oblasts.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Add your `alerts.in.ua` API token (live status only — historical data needs no key):

```
ALERTS_API_KEY=your_token_here
```

> Token issued by the alerts.in.ua team. Request via Telegram: `@alerts_in_ua_bot`. Non-commercial use is free; approval typically within hours.

### 3. Populate cache

```bash
python ingest.py --full   # first run: full historical load (~2022–present)
python ingest.py          # subsequent: incremental update
```

### 4. Launch dashboard

```bash
streamlit run app.py
```

---

## Architecture

```
air-alerts-analysis/
├── app.py              # Streamlit entry point — reads cache, one live API call
├── ingest.py           # CLI: fetch → clean → aggregate → write Parquet
├── src/
│   ├── api/            # alerts.in.ua client (used by app.py for live status only)
│   ├── pipeline/       # cleaner.py, aggregator.py, mapper.py (used by ingest.py only)
│   ├── analytics/      # frequency.py, seasonality.py, predictor.py (used by app.py only)
│   ├── ui/             # map.py, charts.py, state.py (used by app.py only)
│   └── cache/          # store.py — all Parquet I/O
└── data/cache/         # alerts_raw.parquet, alerts_agg.parquet (gitignored)
```

**Data flow:** `ingest.py` writes Parquet → `app.py` reads Parquet. No direct API calls from `app.py` except the single live status check.

**Import rules (strictly enforced):**
- `src/api/` and `src/pipeline/` → imported only by `ingest.py`
- `src/analytics/` and `src/ui/` → imported only by `app.py`

---

## Data Sources

| Source | Purpose | Auth |
|--------|---------|------|
| [`Vadimkin/ukrainian-air-raid-sirens-dataset`](https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset) | Historical alerts (2022–present) | None |
| `alerts.in.ua` REST API | Live active-alert status | API token |

Historical CSV columns: `oblast`, `raion`, `hromada`, `level`, `started_at`, `finished_at`, `source`.

---

## Data Anomalies

Three anomalies are resolved before any aggregation or modelling:

1. **Permanent outliers** — Luhansk Oblast (Apr 2022+) and Autonomous Republic of Crimea (Dec 2022+) maintain near-permanent alert status. Flagged as `is_permanent_outlier=True`; excluded from all aggregates and model training; shown as status badges in the dashboard.

2. **Open-ended events** — alerts with null `finished_at` are imputed:
   - If started within the last 12 hours: `end_time = ingest_timestamp` (still active)
   - If older: `end_time = started_at + 24h` (hard cap)

3. **Post-Dec 2025 raion mapping** — API returns raion-level regions after `2025-12-01`. `src/pipeline/mapper.py` normalises these to oblast level via KATOTTG lookup before any processing.

**Temporal deduplication:** sub-oblast rows (raion, hromada) that overlap a parent oblast interval are merged using a sweep-line algorithm in `AlertCleaner._merge_overlapping_intervals()`. This prevents double-counting when a single alert event generates multiple rows at different administrative levels.

---

## Cron / Refresh

Run `ingest.py` on a schedule to keep the cache current:

```bash
# macOS launchd or cron example — daily at 06:00
0 6 * * * cd /path/to/air-alerts-analysis && python ingest.py >> logs/ingest.log 2>&1
```

The dashboard reads exclusively from the Parquet cache and will show stale data if `ingest.py` hasn't run recently. The footer displays the last ingest timestamp.

---

## Tests

```bash
pytest tests/
```

Covers: `AlertCleaner` (cleaner.py), `mapper.py` KATOTTG normalization, `predictor.py` probability model.
