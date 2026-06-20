# AI Conversation Log — Ukraine Air Raid Intelligence Dashboard

**Project:** Time-series analytics dashboard for Ukrainian air raid alerts  
**Stack:** Python · Streamlit · Plotly · PyArrow · scikit-learn  
**Roles:** User = Lead Engineer · Claude = Junior Developer

---

## Session 1 — Phase 1 Architecture & Initial Build

### Turn 1
**User:** Build a Ukraine air raid alerts analytics dashboard. Stack: Python, Streamlit, Plotly. Data sources: alerts.in.ua API (historical + live) and Vadimkin GitHub CSV. Needs choropleth map, seasonality heatmap, frequency chart, probability gauge.

**Claude:** Generated 17 files covering full Phase 1 architecture:

| File | Role |
|------|------|
| `requirements.txt` | 8 dependencies |
| `.env.example` | API key template |
| `ingest.py` | CLI orchestrator |
| `app.py` | Streamlit entry point |
| `src/api/schemas.py` | Pydantic v2 models |
| `src/api/client.py` | Async fetcher with backoff |
| `src/pipeline/mapper.py` | Raion→Oblast KATOTTG normalization |
| `src/pipeline/cleaner.py` | Anomaly resolver |
| `src/pipeline/aggregator.py` | Weekly + heatmap rollups |
| `src/cache/store.py` | Parquet I/O |
| `src/analytics/seasonality.py` | 24×7 heatmap |
| `src/analytics/frequency.py` | Dual-axis frequency chart |
| `src/analytics/predictor.py` | LogisticRegression per oblast |
| `src/ui/state.py` | Session state + MD5 event guard |
| `src/ui/map.py` | Choropleth + on_select |
| `src/ui/charts.py` | Chart wrappers |
| `tests/` | Unit tests for cleaner, mapper, predictor |

---

### Turn 2
**User:** Explain where I can get the API key.

**Claude:** alerts.in.ua issues tokens manually. Request via Telegram `@alerts_in_ua_bot`. Non-commercial use is free; approval typically within hours. Updated `CLAUDE.md` with setup commands, API key instructions, architecture summary, and three data anomaly constraints.

---

### Turn 3 — Architectural Pivot
**User:** (Role: Principal Python Software Engineer) Reviewed API constraints. alerts.in.ua rate limit (2 req/min for history) is unviable for 4-year time-series analysis. Pivot to hybrid ingestion: Vadimkin GitHub CSV for historical data, alerts.in.ua live API only for current status.

**Claude:** Rewrote `ingest.py` with hybrid pipeline — `CsvFetcher` downloads Vadimkin CSV (no rate limits, daily updated), `AlertCleaner` resolves anomalies, `Aggregator` writes Parquet. `app.py` makes one live API call per load for current status only.

---

### Turn 4 — KSE Audit
**User:** (Role: Principal Python Software Engineer) KSE is evaluating us on real-world data anomaly handling. Audit three areas: (1) Dec 2025 raion mapping, (2) Probability math transparency, (3) Missing end times.

**Claude:** Point-by-point audit response — all three areas were already handled: raion mapping via `RAION_EPOCH = 2025-12-01` in `mapper.py`, open-ended events imputed in `AlertCleaner.clean()`, probability model documented in `app.py` tab3 caption.

---

### Turn 5 — Temporal Deduplication
**User:** Cannot accept the "Known gap" on multi-level row duplication. Update `AlertCleaner` to perform temporal deduplication — if an oblast has active alert A→B, sub-level alerts within same oblast overlapping must be merged or dropped.

**Claude:** Implemented `AlertCleaner._merge_overlapping_intervals()` — vectorized sweep-line algorithm. Groups by `oblast_name`, sorts by `started_at` + region priority (oblast < raion < hromada), computes cumulative max end time, assigns block IDs, keeps first row per block with the block's max end time.

---

### Turn 6 — Bug: KeyError start_time
**User:** Got `KeyError: 'start_time'` error.

**Claude:** Root cause: `_merge_overlapping_intervals()` referenced Parquet column name `start_time` inside `AlertCleaner.clean()` where the DataFrame still has CSV column names (`started_at`). Fixed by replacing `start_time` with `started_at` in 3 places (sort key, block predicate, duration calculation).

---

### Turn 7 — CSS/Visual Fixes
**User:** Fix map transparency — white box still visible. Make map taller. Set bar opacity to 32%.

**Claude:**
- White box: `paper_bgcolor`/`plot_bgcolor` only clear figure frame; `geo.bgcolor` is a separate Plotly layer. Added `bgcolor="rgba(0,0,0,0)"` to `fig.update_geos()`.
- Height: set `height=520`.
- Bars: changed `marker_color` to `rgba(220, 60, 60, 0.32)`.

---

### Turn 8 — Other Bugs Fixed
**User:** Various errors during development.

**Claude:** Fixed across multiple turns:
- `GeoJSON 404` — wrong URL, fixed to correct EugeneBorshch repo path.
- `sys.exit(1)` on `streamlit run` — used `get_script_run_ctx()` to detect runtime context.
- `SSL CERTIFICATE_VERIFY_FAILED` on macOS — switched CSV download from `urllib` to `httpx` (certifi-backed).
- `uint64→int64 TypeError` — `hash_pandas_object` returns uint64; values >2^63 overflow Int64. Fixed with `.to_numpy().view(np.int64)`.
- Oblast name mismatch — Vadimkin CSV uses Ukrainian transliteration ("Kyivska oblast"), GeoJSON uses English. Built explicit 26-entry `_VADIMKIN_TO_CANONICAL` mapping dict.
- GeoJSON stale spellings — "Kiev Oblast" → "Kyiv Oblast", "Odessa Oblast" → "Odesa Oblast" fixed in-memory in `_load_geojson()`.

---

## Session 2 — UI Refinement (Phase 2)

### Turn 1
**User:** Two changes: (1) Make map background fully transparent. (2) Eliminate cumulative duration axis — replace with average duration per alert.

**Claude:** Planned and implemented:
- Map: `paper_bgcolor="rgba(0,0,0,0)"`, `plot_bgcolor="rgba(0,0,0,0)"`, `geo.bgcolor="rgba(0,0,0,0)"`.
- Frequency chart: Dropped `make_subplots`, computed `avg_duration_h = total_duration_hours / alert_count`, new dual-axis `go.Figure` with bars (left) + scatter line (right).

---

### Turn 2
**User:** Oblast selection completely unresponsive + `use_container_width` deprecation warnings.

**Claude:** Fixed event handler in `state.py` to handle both dict and object Streamlit event shapes. Replaced `use_container_width=True` with `width="stretch"` across all `st.plotly_chart()` calls.

---

### Turn 3 — Heatmap Bug
**User:** (Screenshot) Alert Seasonality heatmap shows uniform color for "Kiev Oblast". Analyze and fix.

**Claude:** Root cause: `aggregator.compute_rollups()` outer-joins weekly data with heatmap data on `oblast_name`, creating cartesian product (168 rows per week per oblast). Rewrote `seasonality.compute_heatmap_matrix()` to read directly from raw Parquet, not from the aggregated rollup.

---

## Session 3 — Map Proportions, Borders, Opacity (Current)

### Turn 1
**User:** (Session continuation) Three issues: (1) `height=520` does nothing — width auto-scales too. (2) Make region separator lines black. (3) Bars opacity becomes 100% when selecting an oblast — fix it.

**Claude:** Implemented all three fixes:

1. **Map height** — `fitbounds="locations"` was making Plotly auto-scale the geo projection to fill the Streamlit container — changing height just scaled everything proportionally, no visual change. Replaced with explicit lat/lon bounds (`lataxis_range=[43.5, 53.5]`, `lonaxis_range=[21.5, 41.0]`) that pin Ukraine's geographic aspect ratio. Height bumped to `560`.

2. **Black borders** — Changed `marker_line_color="white"` → `"black"` on both Choropleth traces via `replace_all=True`.

3. **Bars 100% opacity** — Root cause: `aggregator.compute_rollups()` outer-joins weekly (period × oblast) with heatmap (hour × dow × oblast) on `oblast_name`. Creates 168 duplicate rows per week per oblast (24h × 7d). National view collapses them via `groupby("period_start")`. Oblast-filtered view had no deduplication — 168 overlapping bars each at `rgba(0.32)` appeared solid. Fix: `df.drop_duplicates(subset=["period_start"])` after oblast filter in `build_frequency_figure()`.

Commit: `fix: map geo bounds, black borders, bar opacity on oblast filter`

---

### Turn 2
**User:** When I select an oblast, make other oblasts dim to 80% opacity.

**Claude:** Two-trace approach — base choropleth at `opacity=0.8` when selection active, full-colour overlay for selected oblast at `opacity=1.0` with yellow border. Both traces pin `zmin`/`zmax` so selected oblast colour doesn't shift.

Commit: `feat: dim unselected oblasts to 80% opacity on selection`

---

### Turn 3
**User:** `ValueError: Invalid property specified for object of type plotly.graph_objs.Choropleth: 'opacity'`

**Claude:** `go.Choropleth` has no top-level `opacity` property (confirmed by full valid-props list in the error). Correct mechanism: `selectedpoints` + `selected`/`unselected` marker styling — both listed as valid properties.

Fix:
```python
choropleth_kwargs.update(
    selectedpoints=[sel_idx],
    selected=dict(marker=dict(opacity=1.0)),
    unselected=dict(marker=dict(opacity=0.2)),
)
```

Yellow border overlay reverted to transparent-fill (colorscale hack) since base trace now handles colour weight. `sel_idx` is derived from `df.index[df["oblast"] == selected_oblast][0]`.

Commit: `fix: use selectedpoints/unselected for choropleth opacity dimming`

---

### Turn 4
**User:** Check requirements.txt for completeness. Write a structured README.

**Claude:**

**requirements.txt audit:** `numpy` was imported (`np.int64`, uint64 bit-reinterpretation) but missing. Added `numpy>=1.26`. All other imports covered: `streamlit`, `plotly`, `pandas`, `pyarrow`, `pydantic`, `httpx`, `scikit-learn`, `python-dotenv`. `pytest` is dev-only, not added.

**README.md:** Written from scratch with sections: Features, Setup (4 steps), Architecture (directory tree + import rules), Data Sources (table), Data Anomalies (all 3 + temporal deduplication), Cron/Refresh, Tests.

Commit: `chore: add missing numpy to requirements, write project README`

---

### Turn 5
**User:** Remove yellow tracing around oblast when selecting. Set opacity change to 0.3.

**Claude:** Removed the transparent-fill yellow border overlay trace entirely. Updated `unselected=dict(marker=dict(opacity=0.3))`. Selection now communicated solely by contrast between selected (1.0) and unselected (0.3) regions.

Commit: `fix: remove yellow border overlay on selection, set unselected opacity to 0.3`

---

### Turn 6
**User:** Check and format AI_LOG.md. Log our entire conversation in that file (also write who wrote each message).

**Claude:** Read existing `AI_LOG.md` (155KB unformatted raw dump). Rewrote with structured format — prior sessions reconstructed from context summary, current session logged turn-by-turn with `User:` / `Claude:` labels.

---

*Log maintained by Claude Sonnet 4.6 · Last updated: 2026-06-21*
