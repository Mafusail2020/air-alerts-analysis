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
    """
    if not event:
        return
    selection = getattr(event, "selection", None) or (
        event.get("selection") if isinstance(event, dict) else None
    )
    if not selection:
        return

    event_hash = hashlib.md5(str(selection).encode()).hexdigest()
    if event_hash == st.session_state.get("_last_map_event_id"):
        return  # same region re-clicked — no action

    # Extract oblast name from the Plotly selection payload
    points = selection if isinstance(selection, list) else selection.get("points", [])
    if not points:
        return

    oblast = _parse_oblast_from_points(points)
    if not oblast:
        return

    st.session_state["selected_oblast"] = oblast
    st.session_state["_last_map_event_id"] = event_hash
    st.rerun()


def _parse_oblast_from_points(points: list) -> str | None:
    """Extract the location label from Plotly selection points."""
    if not points:
        return None
    pt = points[0]
    if isinstance(pt, dict):
        return pt.get("location") or pt.get("customdata", [None])[0]
    return getattr(pt, "location", None)


def reset_selection() -> None:
    """Called by the Reset button's on_click handler."""
    st.session_state["selected_oblast"] = None
    st.session_state["_last_map_event_id"] = None
