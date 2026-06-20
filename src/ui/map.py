"""Choropleth map of Ukraine with oblast-level click selection."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_GEO_PATH = Path(__file__).resolve().parents[2] / "data" / "geo" / "ukraine_oblasts.geojson"
_GEOJSON_URL = (
    "https://raw.githubusercontent.com/EugeneBorshch/ukraine_geojson"
    "/master/UA_FULL_Ukraine.geojson"
)


@st.cache_data(ttl=86400)
def _load_geojson() -> dict:
    if _GEO_PATH.exists():
        data = json.loads(_GEO_PATH.read_text())
    else:
        import httpx
        resp = httpx.get(_GEOJSON_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        _GEO_PATH.parent.mkdir(parents=True, exist_ok=True)
        _GEO_PATH.write_text(json.dumps(data))

    # Two fixes applied to every feature in-place:
    # 1. Rename "name:en" → "name_en" (Plotly featureidkey can't parse colons).
    # 2. Normalize stale English spellings to match Parquet canonical names
    #    so choropleth on_select returns the same string used to filter data.
    _name_fixes = {
        "Kiev Oblast":   "Kyiv Oblast",   # old transliteration
        "Odessa Oblast": "Odesa Oblast",  # old transliteration
    }
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if "name:en" in props:
            props["name_en"] = props["name:en"]
        if "name_en" in props and props["name_en"] in _name_fixes:
            props["name_en"] = _name_fixes[props["name_en"]]

    return data


def render_map(
    active_oblasts: set[str],
    alert_counts: dict[str, int],
    selected_oblast: str | None,
) -> object:
    """
    Renders an interactive choropleth map and returns the on_select event.

    Args:
        active_oblasts: Oblast names currently under active alerts.
        alert_counts: Mapping of oblast_name → total alert count for color scale.
        selected_oblast: Currently selected oblast (highlighted differently).

    Returns:
        Plotly on_select event object (or None).
    """
    geojson = _load_geojson()

    # Build a DataFrame for Plotly choropleth
    feature_props = [f["properties"] for f in geojson.get("features", [])]
    name_field = _detect_name_field(feature_props)
    oblast_names = [p.get(name_field, "") for p in feature_props]

    df = pd.DataFrame(
        {
            "oblast": oblast_names,
            "count": [alert_counts.get(n, 0) for n in oblast_names],
            "active": [1 if n in active_oblasts else 0 for n in oblast_names],
        }
    )

    fig = go.Figure(
        go.Choropleth(
            geojson=geojson,
            locations=df["oblast"],
            featureidkey=f"properties.{name_field}",
            z=df["count"],
            colorscale="Reds",
            colorbar=dict(title="Total Alerts"),
            marker_line_color="white",
            marker_line_width=0.5,
            customdata=df[["oblast"]].values,
        )
    )

    # Highlight selected oblast with a border overlay
    if selected_oblast:
        selected_df = df[df["oblast"] == selected_oblast]
        if not selected_df.empty:
            fig.add_trace(
                go.Choropleth(
                    geojson=geojson,
                    locations=selected_df["oblast"],
                    featureidkey=f"properties.{name_field}",
                    z=[1],
                    colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
                    showscale=False,
                    marker_line_color="yellow",
                    marker_line_width=3,
                )
            )

    fig.update_geos(
        fitbounds="locations",
        visible=False,
        projection_scale=1,
        bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=520,
        dragmode=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    # Store ordered feature names so state.py can fall back to pointNumber lookup
    # if the "location" field is absent from the Plotly selection event.
    st.session_state["_map_feature_names"] = oblast_names

    event = st.plotly_chart(
        fig,
        width="stretch",
        on_select="rerun",
        key="ukraine_map",
        config={
            "scrollZoom": False,
            "doubleClick": False,
            "displayModeBar": False,
        },
    )
    return event


def _detect_name_field(feature_props: list[dict]) -> str:
    """Detect the GeoJSON property key that holds the English Oblast name.

    name_en is preferred — it is normalised from name:en by _load_geojson().
    """
    candidates = ["name_en", "NAME_1", "shapeName", "name", "NAME"]
    if not feature_props:
        return "name_en"
    for candidate in candidates:
        if candidate in feature_props[0]:
            return candidate
    return list(feature_props[0].keys())[0]
