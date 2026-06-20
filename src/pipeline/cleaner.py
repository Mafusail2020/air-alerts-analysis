"""Anomaly resolution pipeline.

Applies fixes in strict order (order matters):
  1. Flag permanent outliers (Luhansk, Crimea) — BEFORE any duration math
  2. Impute open-ended events (null end_time)
  3. Compute duration_seconds — LAST, after all time values are resolved
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

log = logging.getLogger(__name__)

MAX_IMPUTE_HOURS: int = 24  # domain cap for open-ended events

PERMANENT_OUTLIER_OBLASTS: frozenset[str] = frozenset(
    {
        "Luhansk Oblast",
        "Autonomous Republic of Crimea",
    }
)


def resolve_anomalies(
    df: pd.DataFrame,
    active_alert_ids: set[int],
    ingest_ts: datetime,
) -> pd.DataFrame:
    """
    Args:
        df: DataFrame post-mapper (must have oblast_name, started_at, finished_at, id).
        active_alert_ids: Set of alert IDs currently active per live API call.
        ingest_ts: UTC timestamp of this ingest run.

    Returns:
        DataFrame with added columns:
          - is_permanent_outlier (bool)
          - end_time_raw (datetime, original value preserved)
          - end_time_resolved (datetime, never null)
          - is_open_ended (bool)
          - duration_seconds (float32)
    """
    df = df.copy()
    ingest_ts_utc = ingest_ts.astimezone(timezone.utc)

    # ── Step 1: Permanent outlier flagging ─────────────────────────────────
    df["is_permanent_outlier"] = df["oblast_name"].isin(PERMANENT_OUTLIER_OBLASTS)
    outlier_count = df["is_permanent_outlier"].sum()
    if outlier_count:
        log.info("Flagged %d permanent-outlier records (Luhansk/Crimea)", outlier_count)

    # ── Step 2: Preserve raw end time and impute missing values ────────────
    df["end_time_raw"] = pd.to_datetime(df["finished_at"], utc=True, errors="coerce")
    df["is_open_ended"] = df["end_time_raw"].isna()

    open_ended = df["is_open_ended"]
    open_ended_count = open_ended.sum()
    if open_ended_count:
        log.info("Found %d open-ended events — imputing end times", open_ended_count)

    df["end_time_resolved"] = df["end_time_raw"].copy()

    # Active alerts: cap at ingest_ts
    active_mask = open_ended & df["id"].isin(active_alert_ids)
    df.loc[active_mask, "end_time_resolved"] = ingest_ts_utc

    # Inactive open-ended alerts: cap at start + MAX_IMPUTE_HOURS
    inactive_mask = open_ended & ~df["id"].isin(active_alert_ids)
    df.loc[inactive_mask, "end_time_resolved"] = (
        df.loc[inactive_mask, "started_at"]
        + timedelta(hours=MAX_IMPUTE_HOURS)
    )

    df["end_time_resolved"] = pd.to_datetime(df["end_time_resolved"], utc=True)

    # ── Step 3: Duration calculation (always last) ─────────────────────────
    started = pd.to_datetime(df["started_at"], utc=True)
    raw_seconds = (df["end_time_resolved"] - started).dt.total_seconds()

    max_seconds = MAX_IMPUTE_HOURS * 3600.0
    df["duration_seconds"] = raw_seconds.clip(lower=0, upper=max_seconds).astype("float32")

    # Permanent outliers: set duration to NaN so they can never pollute averages
    df.loc[df["is_permanent_outlier"], "duration_seconds"] = float("nan")

    return df
