# AI Conversation Log — Ukraine Air Raid Intelligence Dashboard

**Project:** Time-series analytics dashboard for Ukrainian air raid alerts
**Stack:** Python · Streamlit · Plotly · PyArrow · scikit-learn
**Roles:** User = Lead Engineer · Claude = Junior Developer

---

## Session 1 — Phase 1 Build

**User:** Build Ukraine air raid alerts dashboard. Stack: Python, Streamlit, Plotly. Data: alerts.in.ua API + Vadimkin CSV. Needs choropleth map, heatmap, frequency chart, probability gauge.

**Claude:** Generated 17 files: `ingest.py`, `app.py`, `src/api/`, `src/pipeline/` (mapper, cleaner, aggregator), `src/cache/store.py`, `src/analytics/` (seasonality, frequency, predictor), `src/ui/` (map, charts, state), `tests/`.

---

**User:** Where do I get the API key?

**Claude:** alerts.in.ua issues tokens manually via Telegram `@alerts_in_ua_bot`. Non-commercial free. Updated `CLAUDE.md`.

---

**User:** (Role: Principal PSE) alerts.in.ua rate limit (2 req/min) unviable for 4yr history. Pivot: Vadimkin GitHub CSV for historical data, alerts.in.ua live API only for current status.

**Claude:** Rewrote `ingest.py` — `CsvFetcher` downloads Vadimkin CSV (no rate limits, daily updated), `AlertCleaner` resolves anomalies, `Aggregator` writes Parquet. `app.py` makes one live API call per load only.

---

**User:** Errors on startup — GeoJSON 404. Also make API key optional.

**Claude:** Root cause 1: Placeholder GeoJSON URL didn't exist. Fixed to `EugeneBorshch/ukraine_geojson/master/UA_FULL_Ukraine.geojson`. `name:en` → `name_en` normalization added.
Root cause 2: Missing API key crashed on import. Made optional — returns `""`, live status silently degrades.
Root cause 3: `python3 app.py` vs `streamlit run app.py` — added `get_script_run_ctx()` guard.
Commit: `feat: implement Phase 1 dashboard architecture`

---

**User:** Streamlit page blank on startup.

**Claude:** Root cause: `sys.exit(1)` guard used `__name__ == "__main__"` — Streamlit sets same flag. `get_script_run_ctx()` returns `None` only outside Streamlit runtime. Fixed.
Commit: `fix: blank page on streamlit run caused by incorrect __main__ guard`

---

**User:** `KeyError: 'is_permanent_outlier'`

**Claude:** Root cause: `store.read_raw()` returns empty DataFrame (no Parquet yet). Analytics functions accessed columns before `df.empty` guard. Added guards to `seasonality.py`, `predictor.py`, `charts.py`.
Commit: `fix: KeyError on is_permanent_outlier when cache is empty`

---

**User:** SSL `CERTIFICATE_VERIFY_FAILED` running `ingest.py`.

**Claude:** Root cause: macOS Python 3.10 (python.org) ships without CA certs; `pd.read_csv(url)` uses urllib. Switched to `httpx` (certifi-backed) — download bytes first, pass via `io.BytesIO`.
Commit: `fix: SSL certificate failure on macOS Python 3.10`

---

**User:** `ValueError: CSV schema mismatch` — expected `id`, `location_oblast`; actual: `oblast`, `raion`, `hromada`, `level`, `started_at`, `finished_at`, `source`.

**Claude:** Root cause: Assumed stale Vadimkin schema. Rewrote `_CSV_COLUMN_MAP` to match actual columns. Synthesise `alert_id` via MD5 hash. Also fixed `aggregator.py`: `id` → `alert_id`, `started_at` → `start_time`.
Commit: `fix: adapt to actual Vadimkin CSV schema`

---

**User:** `TypeError: cannot safely cast non-equivalent uint64 to int64`

**Claude:** Root cause: `hash_pandas_object` returns uint64; values >2^63 overflow pandas `Int64`. Fixed with `.to_numpy().view(np.int64)` bit-reinterpretation. Also moved imports to module top, removed unused column assignment, added tz-aware guard in `filter_delta`.
Commit: `fix: uint64→int64 overflow in id synthesis`

---

**User:** Oblast selection unresponsive. Heatmap uniform color. Frequency empty. Probability 0.

**Claude:** Root cause (selection): `selection.get("points")` fails on Streamlit `SelectionState` object (not a dict) → silent `AttributeError`. Fixed with `isinstance(sel, dict)` branch + `getattr` fallback.
Root cause (charts): Vadimkin CSV uses Ukrainian transliteration ("Cherkaska oblast"); GeoJSON uses English ("Cherkasy Oblast"). Parquet stored wrong names → zero filter matches.
Fix: `_VADIMKIN_TO_CANONICAL` dict (26 entries) maps all Ukrainian admin names to canonical GeoJSON names. `_load_geojson()` patches stale GeoJSON spellings in-memory: "Kiev Oblast" → "Kyiv Oblast", "Odessa Oblast" → "Odesa Oblast".
Also fixed `use_container_width` deprecation: replaced with `width="stretch"`.
Commits: `fix: oblast name mismatch`, `fix: robust event parsing`

---

**User:** (Role: Principal PSE / KSE Audit) Three items: (1) Dec 2025 raion mapping, (2) Probability math transparency, (3) Missing end times.

**Claude:** Audit results:
1. **Raion mapping** ✅ — Vadimkin `oblast` column always carries parent oblast regardless of `level`. No KATOTTG lookup needed. Sub-level rows inflate counts (known gap).
2. **Probability math** ✅ — Real `LogisticRegression`: features `rolling_7d`, `hour_of_day`, `day_of_week` (Z-score standardised); target = `any alert in next 12h`. Fallback: `rolling_7d / 168`. Added `st.caption()` to tab3.
3. **Missing end times** ✅ — Two-tier imputation: recent (<12h) → `ingest_ts`; old → `start + 24h`.
Commit: `docs: add methodology caption to Alert Probability tab`

---

**User:** Cannot accept the known gap. Implement temporal deduplication — if oblast has alert A→B, sub-level overlapping rows must be merged.

**Claude:** Added `AlertCleaner._merge_overlapping_intervals()` — vectorized sweep-line: group by oblast, sort by `started_at` + level priority (oblast < raion < hromada), cumulative-max end time identifies block boundaries, keep first row per block with block's max end, recompute duration. Called at end of `clean()` so raw Parquet itself is deduplicated.
Commit: `fix: temporal deduplication of multi-level alert rows per oblast`

---

**User:** `KeyError: 'start_time'`

**Claude:** Root cause: `_merge_overlapping_intervals()` used Parquet column name `start_time` inside `clean()` where DataFrame still has CSV column name `started_at`. Rename happens later in `store._df_to_raw_table()`. Fixed 3 occurrences.
Commit: `fix: use started_at (CSV column) not start_time (Parquet column)`

---

## Session 2 — UI Refinement

**User:** (Role: Principal PSE) Two changes: (1) Transparent map background. (2) Replace cumulative duration axis with average duration per alert.

**Claude:** (Plan approved) Change 1: `paper_bgcolor`, `plot_bgcolor`, `geo.bgcolor` all set to `"rgba(0,0,0,0)"`. Plotly choropleth has THREE separate background layers — all three required for true transparency.
Change 2: Dropped `make_subplots`. Computed `avg_duration_h = total_duration_hours / alert_count`. Bars (left axis, 18% opacity) + scatter line (right axis, full opacity). `hovermode="x unified"`.
Commit: `feat: transparent map background + avg-duration-per-alert frequency chart`

---

**User:** (Screenshot) Heatmap still uniform color for "Kiev Oblast".

**Claude:** Root cause: `aggregator.compute_rollups()` outer-joins weekly × heatmap on `oblast_name` → cartesian product (168 rows per week per oblast). National view collapses via `groupby`. Oblast view had no dedup → same hour/dow cells stacked → uniform. Rewrote `seasonality.compute_heatmap_matrix()` to read directly from raw Parquet, bypass aggregator.

---

**User:** Map still has white box. Make map taller. Set bar opacity to 32%.

**Claude:** Root cause: `paper_bgcolor`/`plot_bgcolor` only clear figure frame. Choropleth geo canvas has own `geo.bgcolor` layer. Added `bgcolor="rgba(0,0,0,0)"` to `fig.update_geos()`. Height 420 → 520. Bars 0.18 → 0.32.
Commit: `fix: geo canvas transparency, map height, bar opacity`

---

## Session 3 — Map & Opacity Polish

**User:** (1) `height=520` does nothing. (2) Make region borders black. (3) Bars 100% opacity when selecting oblast.

**Claude:** Bug 1: `fitbounds="locations"` makes Plotly auto-scale projection to fill container — changing height scales everything proportionally. Fixed: replaced with explicit `lataxis_range=[43.5, 53.5]`, `lonaxis_range=[21.5, 41.0]`. Height → 560.
Bug 2: `marker_line_color="white"` → `"black"` on both traces.
Bug 3: Aggregator outer-join creates 168 duplicate rows per week per oblast (24h × 7d). 168 bars × rgba(0.32) ≈ solid. Fix: `drop_duplicates(subset=["period_start"])` after oblast filter.
Commit: `fix: map geo bounds, black borders, bar opacity on oblast filter`

---

**User:** When selecting oblast, dim other oblasts to 80% opacity.

**Claude:** Attempted `opacity=0.8` on `go.Choropleth` → `ValueError: Invalid property`. `go.Choropleth` has no top-level `opacity`. Fixed using `selectedpoints=[sel_idx]` + `selected=dict(marker=dict(opacity=1.0))` + `unselected=dict(marker=dict(opacity=0.2))`. `sel_idx` = index of selected oblast in `df["oblast"]`.
Commits: `feat: dim unselected oblasts`, `fix: use selectedpoints/unselected for choropleth opacity dimming`

---

**User:** Check `requirements.txt`. Write structured README.

**Claude:** `numpy` missing — imported (`np.int64`, uint64 bit-reinterpretation) but not listed. Added `numpy>=1.26`. README written: Features, Setup (4 steps), Architecture (dir tree + import rules), Data Sources, Data Anomalies (3 + dedup), Cron/Refresh, Tests.
Commit: `chore: add missing numpy to requirements, write project README`

---

**User:** Remove yellow border on selection. Set unselected opacity to 0.3.

**Claude:** Removed transparent-fill yellow border overlay trace. Updated `unselected=dict(marker=dict(opacity=0.3))`.
Commit: `fix: remove yellow border overlay on selection, set unselected opacity to 0.3`

---

**User:** Log entire conversation in AI_LOG.md with author labels.

**Claude:** Added `**User:**` / `**Claude:**` labels at 47 turn boundaries via Python script. All original content preserved. Compressed to 200 lines (this file).
Commits: `docs: add User/Claude labels`, `docs: compress AI_LOG to 200 lines`

---

*Log maintained by Claude Sonnet 4.6 · Last updated: 2026-06-21*
