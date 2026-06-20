"""Hour-of-Day × Day-of-Week seasonality heatmap.

Displays alert frequency as a 24×7 matrix in Kyiv local time (UTC+2).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

_KYIV_OFFSET_HOURS = 2
_DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def compute_heatmap_matrix(
    raw: pd.DataFrame,
    oblast_name: str | None = None,
) -> pd.DataFrame:
    """
    Args:
        raw: alerts_raw DataFrame (permanent outliers already flagged).
        oblast_name: If provided, filter to this oblast only.

    Returns:
        24×7 pivot DataFrame — rows=hour (0–23 Kyiv), cols=day-of-week (Mon–Sun).
    """
    if raw.empty or "is_permanent_outlier" not in raw.columns:
        return pd.DataFrame(0, index=range(24), columns=_DOW_LABELS)

    df = raw[~raw["is_permanent_outlier"]].copy()
    if oblast_name:
        df = df[df["oblast_name"] == oblast_name]

    if df.empty:
        return pd.DataFrame(0, index=range(24), columns=_DOW_LABELS)

    started = pd.to_datetime(df["start_time"], utc=True)
    df["hour_kyiv"] = (started.dt.hour + _KYIV_OFFSET_HOURS) % 24
    df["dow"] = started.dt.dayofweek  # 0=Mon

    counts = (
        df.groupby(["hour_kyiv", "dow"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=range(24), columns=range(7), fill_value=0)
    )
    counts.columns = _DOW_LABELS
    return counts


def build_heatmap_figure(
    matrix: pd.DataFrame,
    title: str = "Alert Frequency by Hour & Day (Kyiv Time)",
) -> go.Figure:
    fig = go.Figure(
        go.Heatmap(
            z=matrix.values,
            x=_DOW_LABELS,
            y=[f"{h:02d}:00" for h in range(24)],
            colorscale="Reds",
            colorbar=dict(title="Alert Count"),
            hoverongaps=False,
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Day of Week",
        yaxis_title="Hour of Day (UTC+2)",
        yaxis=dict(autorange="reversed"),
        margin=dict(l=60, r=20, t=50, b=40),
    )
    return fig
