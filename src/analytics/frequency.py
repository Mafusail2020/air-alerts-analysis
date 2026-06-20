"""Dual-axis weekly frequency vs. cumulative duration chart."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build_frequency_figure(
    agg: pd.DataFrame,
    oblast_name: str | None = None,
    title: str = "Weekly Alert Frequency vs. Cumulative Duration",
) -> go.Figure:
    """
    Args:
        agg: alerts_agg DataFrame with period_start, oblast_name,
             alert_count, total_duration_hours.
        oblast_name: Filter to oblast or None for national totals.

    Returns:
        Dual-axis Plotly figure.
    """
    df = agg.copy()
    if "period_start" not in df.columns or df.empty:
        return go.Figure()

    if oblast_name:
        df = df[df["oblast_name"] == oblast_name]
    else:
        # National: sum across all oblasts per week
        df = (
            df.groupby("period_start", as_index=False)
            .agg(alert_count=("alert_count", "sum"), total_duration_hours=("total_duration_hours", "sum"))
        )

    df = df.sort_values("period_start")
    df = df.dropna(subset=["period_start", "alert_count"])

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=df["period_start"],
            y=df["alert_count"],
            name="Alert Count",
            marker_color="rgba(220, 60, 60, 0.7)",
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=df["period_start"],
            y=df["total_duration_hours"],
            name="Cumulative Duration (hrs)",
            mode="lines+markers",
            line=dict(color="rgba(30, 120, 200, 0.9)", width=2),
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title=title,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=60, t=60, b=40),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Alert Count", secondary_y=False)
    fig.update_yaxes(title_text="Duration (hours)", secondary_y=True)
    fig.update_xaxes(title_text="Week")
    return fig
