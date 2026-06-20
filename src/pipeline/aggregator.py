"""Pre-compute rollups from alerts_raw.parquet → alerts_agg.parquet.

Permanent outliers are excluded at write time so the dashboard never
needs to apply a runtime filter.
"""

from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)


def compute_rollups(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Args:
        raw: Full alerts_raw DataFrame (post-cleaner).

    Returns:
        Aggregated DataFrame with columns:
          - period_start      (timestamp[UTC], weekly Monday bucket)
          - oblast_name       (str)
          - alert_count       (int32)
          - total_duration_hours (float32)
          - hour_of_day       (int8)
          - day_of_week       (int8)
          - heatmap_cell_count (int32)
    """
    # Exclude permanent outliers — baked in at write time
    clean = raw[~raw["is_permanent_outlier"]].copy()

    started = pd.to_datetime(clean["started_at"], utc=True)
    clean["hour_of_day"] = started.dt.hour.astype("int8")
    clean["day_of_week"] = started.dt.dayofweek.astype("int8")  # 0=Mon

    # Weekly frequency + magnitude per oblast
    clean["period_start"] = started.dt.to_period("W").apply(lambda p: p.start_time).dt.tz_localize("UTC")

    weekly = (
        clean.groupby(["period_start", "oblast_name"])
        .agg(
            alert_count=("id", "count"),
            total_duration_hours=("duration_seconds", lambda s: s.sum(skipna=True) / 3600.0),
        )
        .reset_index()
    )
    weekly["alert_count"] = weekly["alert_count"].astype("int32")
    weekly["total_duration_hours"] = weekly["total_duration_hours"].astype("float32")

    # Heatmap cell counts per (hour, dow, oblast)
    heatmap = (
        clean.groupby(["hour_of_day", "day_of_week", "oblast_name"])
        .agg(heatmap_cell_count=("id", "count"))
        .reset_index()
    )
    heatmap["heatmap_cell_count"] = heatmap["heatmap_cell_count"].astype("int32")

    # Merge into one wide table (NaN for non-applicable columns is acceptable)
    agg = weekly.merge(
        heatmap,
        on="oblast_name",
        how="outer",
    )

    log.info(
        "Aggregation complete — %d weekly rows, %d heatmap rows",
        len(weekly),
        len(heatmap),
    )
    return agg
