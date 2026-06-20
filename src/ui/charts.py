"""Chart rendering wrappers called by app.py.

Each function reads from cache via store.py and delegates to the
analytics module. app.py stays thin — one call per widget section.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from src.analytics import frequency as freq_mod
from src.analytics import seasonality as season_mod
from src.analytics import predictor as pred_mod
from src.cache import store


@st.cache_data(ttl=300, show_spinner=False)
def _cached_raw(oblast_name: str | None) -> object:
    return store.read_raw(oblast_name)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_agg(oblast_name: str | None) -> object:
    return store.read_agg(oblast_name)


def render_seasonality_heatmap(oblast_name: str | None) -> None:
    raw = store.read_raw()
    matrix = season_mod.compute_heatmap_matrix(raw, oblast_name)
    title_suffix = oblast_name or "All Oblasts (National)"
    fig = season_mod.build_heatmap_figure(
        matrix, title=f"Alert Seasonality — {title_suffix}"
    )
    st.plotly_chart(fig, use_container_width=True)


def render_frequency_chart(oblast_name: str | None) -> None:
    agg = store.read_agg()
    if agg.empty:
        st.info("Run `python ingest.py` to populate the cache.")
        return
    title_suffix = oblast_name or "National"
    fig = freq_mod.build_frequency_figure(
        agg, oblast_name, title=f"Weekly Frequency vs. Duration — {title_suffix}"
    )
    st.plotly_chart(fig, use_container_width=True)


def render_prediction_gauge(oblast_name: str | None) -> None:
    if not oblast_name:
        st.info("Select an oblast on the map to see the predictive baseline.")
        return

    raw = store.read_raw()
    prob = pred_mod.predict_alert_probability(oblast_name, raw)
    pct = round(prob * 100, 1)

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=pct,
            title={"text": f"P(Alert next 12h) — {oblast_name}"},
            number={"suffix": "%"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "crimson"},
                "steps": [
                    {"range": [0, 33], "color": "lightgreen"},
                    {"range": [33, 66], "color": "gold"},
                    {"range": [66, 100], "color": "tomato"},
                ],
                "threshold": {
                    "line": {"color": "black", "width": 3},
                    "thickness": 0.75,
                    "value": pct,
                },
            },
        )
    )
    fig.update_layout(height=300, margin=dict(l=30, r=30, t=60, b=20))
    st.plotly_chart(fig, use_container_width=True)
