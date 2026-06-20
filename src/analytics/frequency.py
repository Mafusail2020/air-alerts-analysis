"""Weekly alert frequency with average duration per alert overlay."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def build_frequency_figure(
    agg: pd.DataFrame,
    oblast_name: str | None = None,
    title: str = "Weekly Alert Frequency & Avg Duration per Alert",
) -> go.Figure:
    """
    Args:
        agg: alerts_agg DataFrame with period_start, oblast_name,
             alert_count, total_duration_hours.
        oblast_name: Filter to oblast or None for national totals.

    Returns:
        Single-canvas Plotly figure: pale count bars (left axis) overlaid
        with avg_duration_per_alert line (right axis).  The dual-axis
        secondary-y subplot design was replaced because cumulative hours
        and absolute count share no common unit, making the intersection
        arbitrary.  avg_duration = total_hours / count is analytically
        coherent on a shared time axis — rising line = longer individual
        alerts (tactical intensity); rising bars = higher event frequency.
    """
    df = agg.copy()
    if "period_start" not in df.columns or df.empty:
        return go.Figure()

    if oblast_name:
        df = df[df["oblast_name"] == oblast_name]
        # aggregator outer-joins weekly (period × oblast) with heatmap
        # (hour × dow × oblast), producing 168 duplicate rows per week.
        # National branch collapses them via groupby; oblast branch must
        # deduplicate here or 168 overlapping bars render as 100% opacity.
        df = df.drop_duplicates(subset=["period_start"])
    else:
        # National: aggregate across all oblasts per week
        df = (
            df.groupby("period_start", as_index=False)
            .agg(
                alert_count=("alert_count", "sum"),
                total_duration_hours=("total_duration_hours", "sum"),
            )
        )

    df = df.sort_values("period_start")
    df = df.dropna(subset=["period_start", "alert_count"])

    # Derived metric: average hours under alert per distinct event
    df["avg_duration_h"] = (
        df["total_duration_hours"] / df["alert_count"].replace(0, pd.NA)
    ).round(2)

    fig = go.Figure()

    # Structural background — frequency context, deliberately de-emphasised
    fig.add_trace(
        go.Bar(
            x=df["period_start"],
            y=df["alert_count"],
            name="Alert Count",
            marker_color="rgba(220, 60, 60, 0.32)",
            marker_line_width=0,
            yaxis="y",
        )
    )

    # Primary analytical signal — average intensity per event
    fig.add_trace(
        go.Scatter(
            x=df["period_start"],
            y=df["avg_duration_h"],
            name="Avg Duration / Alert (hrs)",
            mode="lines+markers",
            line=dict(color="rgba(30, 180, 255, 1.0)", width=2),
            marker=dict(size=4),
            yaxis="y2",
        )
    )

    fig.update_layout(
        title=title,
        yaxis=dict(title="Alert Count", showgrid=False),
        yaxis2=dict(
            title="Avg Duration / Alert (hrs)",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=60, t=60, b=40),
        hovermode="x unified",
        barmode="overlay",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(title_text="Week")
    return fig
