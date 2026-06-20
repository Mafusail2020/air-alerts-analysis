"""Session state management and map event guard.

Prevents redundant reruns when user clicks the same oblast twice.
"""

from __future__ import annotations

import hashlib

import streamlit as st


def init_session_state() -> None:
    """Call once at the top of app.py before any widget renders."""
    if "selected_oblast" not in st.session_state:
        st.session_state["selected_oblast"] = None
    if "_last_map_event_id" not in st.session_state:
        st.session_state["_last_map_event_id"] = None


def handle_map_event(event: object) -> None:
    """
    Process a plotly on_select event from the choropleth map.
    No-ops if event is empty or identical to the last processed event.
    Triggers st.rerun() only when the selection genuinely changes.

    Handles both dict-style (older Streamlit) and object-style (newer Streamlit)
    event shapes so this doesn't break on library updates.
    """
    if not event:
        return

    # selection can be an attribute (Streamlit object) or a key (plain dict)
    sel = getattr(event, "selection", None)
    if sel is None and isinstance(event, dict):
        sel = event.get("selection")
    if sel is None:
        return

    # points can be .points attribute or ["points"] key depending on version
    if isinstance(sel, dict):
        points = sel.get("points", [])
    else:
        points = getattr(sel, "points", [])

    if not points:
        return

    # Hash the points list only — not the entire selection struct which changes
    # shape across Streamlit versions and would break deduplication.
    event_hash = hashlib.md5(str(points).encode()).hexdigest()
    if event_hash == st.session_state.get("_last_map_event_id"):
        return  # same region re-clicked — no action

    oblast = _parse_oblast_from_points(points)
    if not oblast:
        return

    st.session_state["selected_oblast"] = oblast
    st.session_state["_last_map_event_id"] = event_hash
    st.rerun()


def _parse_oblast_from_points(points: list) -> str | None:
    """Extract the location label from Plotly selection points.

    Tries multiple fields in order because choropleth point dicts vary:
      1. "location"    — most reliable; Plotly sets this from the locations array
      2. "customdata"  — fallback; handles str, list[str], or list[list[str]]
      3. "pointNumber" — last resort; indexes into _map_feature_names in session state
    """
    if not points:
        return None
    pt = points[0]
    pt_dict = pt if isinstance(pt, dict) else {}

    # 1. location field (Plotly choropleth sets this to the locations array value)
    loc = pt_dict.get("location") or getattr(pt, "location", None)
    if loc and isinstance(loc, str):
        return loc

    # 2. customdata — may be bare string, list[str], or list[list[str]]
    cd = pt_dict.get("customdata") or getattr(pt, "customdata", None)
    if cd is not None:
        if isinstance(cd, str) and cd:
            return cd
        if isinstance(cd, (list, tuple)) and cd:
            inner = cd[0]
            if isinstance(inner, (list, tuple)) and inner:
                return str(inner[0])
            if inner is not None:
                return str(inner)

    # 3. pointNumber → look up in the feature name list stored at render time
    idx = (
        pt_dict.get("pointNumber")
        or pt_dict.get("pointIndex")
        or getattr(pt, "pointNumber", None)
    )
    if idx is not None:
        features: list = st.session_state.get("_map_feature_names", [])
        try:
            i = int(idx)
            if 0 <= i < len(features):
                return features[i]
        except (TypeError, ValueError):
            pass

    return None


def reset_selection() -> None:
    """Called by the Reset button's on_click handler."""
    st.session_state["selected_oblast"] = None
    st.session_state["_last_map_event_id"] = None
