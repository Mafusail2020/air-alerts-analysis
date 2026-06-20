"""Ukraine Air Raid Intelligence Dashboard.

Entry point: streamlit run app.py

Reads exclusively from data/cache/*.parquet (written by ingest.py).
One live API call per load: fetch currently active alerts for the status bar.
"""

from __future__ import annotations

import asyncio

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.api.client import fetch_active_alerts
from src.cache import store
from src.ui import charts, map as map_ui, state as state_mod

st.set_page_config(
    page_title="Ukraine Air Raid Intelligence",
    page_icon="🚨",
    layout="wide",
)


@st.cache_data(ttl=60, show_spinner=False)
def _get_active_oblasts() -> tuple[set[str], int]:
    """Returns (active oblast names, count). Cached 60s."""
    try:
        active = asyncio.run(fetch_active_alerts())
        names = {a.region_name for a in active}
        return names, len(names)
    except Exception:
        return set(), 0


def _get_alert_counts_for_map() -> dict[str, int]:
    raw = store.read_raw()
    if raw.empty:
        return {}
    return raw.groupby("oblast_name")["alert_id"].count().to_dict()


def main() -> None:
    state_mod.init_session_state()

    # ── Header ───────────────────────────────────────────────────────────────
    st.title("Ukraine Air Raid Intelligence Dashboard")

    active_oblasts, active_count = _get_active_oblasts()
    selected = st.session_state["selected_oblast"]

    col_status, col_reset = st.columns([6, 1])
    with col_status:
        if active_count:
            st.error(f"ACTIVE ALERTS: {active_count} oblast(s) currently under alert", icon="🚨")
        else:
            st.success("No active alerts at this time", icon="✅")

    with col_reset:
        if selected:
            st.button("Reset", on_click=state_mod.reset_selection, type="secondary")

    # ── Context label ────────────────────────────────────────────────────────
    if selected:
        st.subheader(f"Viewing: {selected}")
    else:
        st.subheader("National Overview")

    # ── Map ──────────────────────────────────────────────────────────────────
    alert_counts = _get_alert_counts_for_map()
    event = map_ui.render_map(
        active_oblasts=active_oblasts,
        alert_counts=alert_counts,
        selected_oblast=selected,
    )
    state_mod.handle_map_event(event)

    # ── Permanent outlier notice ─────────────────────────────────────────────
    if selected in {"Luhansk Oblast", "Autonomous Republic of Crimea"}:
        st.warning(
            f"{selected} has maintained a near-permanent alert status since "
            f"{'April 2022' if 'Luhansk' in selected else 'December 2022'}. "
            "Duration statistics are excluded from national aggregates to prevent skew.",
            icon="⚠️",
        )

    st.divider()

    # ── Analytics panels ─────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(
        ["Seasonality Heatmap", "Frequency vs. Duration", "Alert Probability"]
    )

    with tab1:
        st.caption("Alert frequency by hour of day (Kyiv time, UTC+2) and day of week.")
        charts.render_seasonality_heatmap(selected)

    with tab2:
        st.caption("Weekly alert count (bars, left axis) vs. cumulative alert duration in hours (line, right axis).")
        charts.render_frequency_chart(selected)

    with tab3:
        st.caption(
            "**Method:** Logistic regression (sklearn) trained per-oblast on hourly alert buckets. "
            "Features: (1) rolling 7-day alert count, (2) hour of day, (3) day of week — all Z-score standardised. "
            "Binary target: was there ≥1 alert in the 12 hours *after* each training hour? "
            "Output is P(alert | next 12 h) from `predict_proba()`. "
            "Falls back to `rolling_7d / 168` (naive frequency rate) if no trained model exists for the selected oblast."
        )
        charts.render_prediction_gauge(selected)

    # ── Cache status footer ───────────────────────────────────────────────────
    st.divider()
    last_ts = store.read_last_ingest_ts()
    if last_ts:
        st.caption(f"Cache last updated: {last_ts.strftime('%Y-%m-%d %H:%M UTC')} — run `python ingest.py` to refresh.")
    else:
        st.caption("No cache found. Run `python ingest.py` to populate data.")


if __name__ == "__main__":
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    if get_script_run_ctx() is None:
        import sys
        print(
            "\nERROR: Do not run this file with python3 directly.\n"
            "Launch with:\n\n    streamlit run app.py\n",
            file=sys.stderr,
        )
        sys.exit(1)

main()
