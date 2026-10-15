"""Plotly figures for the dashboard. One accent color for single-series charts
(the ticker is always on the axis or labeled), three fixed colors for the
three return periods. Every chart has hover tooltips."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go

from analysis import TrendFit

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_3 = "#8a8983"
GRID = "#e6e5e0"
SURFACE = "#ffffff"

PERIOD_COLORS = {"Perf YTD": BLUE, "Perf 3Y": ORANGE, "Perf 5Y": AQUA}
PERIOD_LABELS = {"Perf YTD": "YTD", "Perf 3Y": "3 years", "Perf 5Y": "5 years"}


def _base(fig: go.Figure, title: str, height: int) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=16, color=INK)),
        height=height,
        margin=dict(l=10, r=20, t=50, b=40),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color=INK_2),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRID, font=dict(color=INK, size=12)),
        barcornerradius=4,
        showlegend=False,
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=INK_3, linecolor=GRID, tickfont=dict(color=INK_2))
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=INK_3, linecolor=GRID, tickfont=dict(color=INK_2))
    return fig


def ranking_bar(df: pd.DataFrame, col: str, title: str, *, suffix: str = "",
                ascending: bool = True) -> go.Figure:
    """Horizontal bars, best-first at the top. Missing values are left off and noted in the title."""
    data = df[["Ticker", col]].dropna().sort_values(col, ascending=ascending)
    skipped = len(df) - len(data)
    fig = go.Figure(go.Bar(
        x=data[col], y=data["Ticker"], orientation="h", marker_color=BLUE,
        text=[f"{v:,.2f}{suffix}" for v in data[col]], textposition="outside",
        textfont=dict(color=INK_2, size=11), cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>" + col + ": %{x:,.2f}" + suffix + "<extra></extra>",
    ))
    if skipped:
        title += f"  ·  {skipped} n/a not shown"
    _base(fig, title, height=max(260, 24 * len(data) + 90))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(ticksuffix=suffix)
    return fig


def growth_scatter(eligible: pd.DataFrame, fit: TrendFit | None) -> go.Figure:
    caps = eligible["Market Cap"].fillna(0).clip(lower=0)
    max_cap = caps.max() or 1
    sizes = [max(9.0, 60 * math.sqrt(c / max_cap)) for c in caps]  # area ~ market cap
    fig = go.Figure(go.Scatter(
        x=eligible["EPS Next Y"], y=eligible["Forward P/E"], mode="markers+text",
        text=eligible["Ticker"], textposition="top center", textfont=dict(color=INK_2, size=11),
        marker=dict(size=sizes, color=BLUE, opacity=0.75, line=dict(color=SURFACE, width=2)),
        customdata=eligible[["Company", "Distance"]] if "Distance" in eligible else eligible[["Company"]],
        hovertemplate=("<b>%{text}</b> · %{customdata[0]}<br>EPS Next Y: %{x:.2f}%<br>"
                       "Forward P/E: %{y:.2f}×"
                       + ("<br>Distance from line: %{customdata[1]:+.2f}" if "Distance" in eligible else "")
                       + "<extra></extra>"),
        name="Stocks",
    ))
    if fit is not None:
        x0, x1 = float(eligible["EPS Next Y"].min()), float(eligible["EPS Next Y"].max())
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[fit.intercept + fit.slope * x0, fit.intercept + fit.slope * x1],
            mode="lines", line=dict(color=INK_2, width=2), name="Trend line",
            hovertemplate=f"Trend line<br>R² = {fit.r2:.2f}<extra></extra>",
        ))
    _base(fig, "Expected EPS growth vs. Forward P/E", height=560)
    fig.update_xaxes(title="Expected EPS growth next year (%)", ticksuffix="%")
    fig.update_yaxes(title="Forward P/E (×)", ticksuffix="×", rangemode="tozero")
    return fig


def trend_map(df: pd.DataFrame) -> go.Figure:
    data = df.dropna(subset=["SMA50", "SMA200"])
    fig = go.Figure(go.Scatter(
        x=data["SMA200"], y=data["SMA50"], mode="markers+text", text=data["Ticker"],
        textposition="top center", textfont=dict(color=INK_2, size=11),
        marker=dict(size=10, color=BLUE, line=dict(color=SURFACE, width=2)),
        customdata=data[["Trend"]],
        hovertemplate=("<b>%{text}</b> · %{customdata[0]}<br>vs 200-day avg: %{x:+.2f}%"
                       "<br>vs 50-day avg: %{y:+.2f}%<extra></extra>"),
    ))
    fig.add_hline(y=0, line=dict(color=INK_3, width=1, dash="dash"))
    fig.add_vline(x=0, line=dict(color=INK_3, width=1, dash="dash"))
    for x, y, label, xa, ya in ((1, 1, "Uptrend", "right", "top"), (0, 0, "Downtrend", "left", "bottom"),
                                (0, 1, "Mixed", "left", "top"), (1, 0, "Mixed", "right", "bottom")):
        fig.add_annotation(x=x, y=y, xref="paper", yref="paper", text=label, showarrow=False,
                           xanchor=xa, yanchor=ya, font=dict(color=INK_3, size=13))
    _base(fig, "Price distance from the 50-day and 200-day moving averages", height=540)
    fig.update_xaxes(title="Price vs 200-day average (%)", ticksuffix="%", zeroline=False)
    fig.update_yaxes(title="Price vs 50-day average (%)", ticksuffix="%", zeroline=False)
    return fig


def rsi_bar(df: pd.DataFrame) -> go.Figure:
    fig = ranking_bar(df, "RSI", "RSI (14-day), highest first", ascending=False)
    for level, label in ((30, "30 · oversold"), (70, "70 · overbought")):
        fig.add_vline(x=level, line=dict(color=INK_3, width=1, dash="dash"),
                      annotation_text=label, annotation_position="top",
                      annotation_font=dict(color=INK_3, size=11))
    fig.update_xaxes(range=[0, 100])
    return fig


def range_position_bar(df: pd.DataFrame) -> go.Figure:
    fig = ranking_bar(df, "52W Position", "Position within the 52-week range (0% = low, 100% = high)",
                      suffix="%", ascending=False)
    fig.update_xaxes(range=[0, 115])
    return fig


def returns_grouped(df: pd.DataFrame, periods: list[str]) -> go.Figure:
    """Grouped bars, sorted by the longest selected period; missing values are gaps, not zeros."""
    sort_col = periods[-1]
    data = df.assign(_missing=df[sort_col].isna()).sort_values(["_missing", sort_col],
                                                                ascending=[True, False])
    fig = go.Figure()
    for p in periods:
        fig.add_trace(go.Bar(
            x=data["Ticker"], y=data[p], name=PERIOD_LABELS[p], marker_color=PERIOD_COLORS[p],
            marker_line=dict(color=SURFACE, width=1),
            hovertemplate="<b>%{x}</b><br>" + PERIOD_LABELS[p] + ": %{y:,.2f}%<extra></extra>",
        ))
    _base(fig, f"Returns by ticker, sorted by {PERIOD_LABELS[sort_col]} return", height=520)
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08, showlegend=True,
                      margin=dict(l=10, r=20, t=90, b=40),
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, font=dict(color=INK_2)))
    fig.update_yaxes(title="Return (%)", ticksuffix="%")
    fig.update_xaxes(showgrid=False, tickangle=-45)
    return fig
