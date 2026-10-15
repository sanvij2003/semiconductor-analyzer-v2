"""Calculations and formatting used by the dashboard. No Streamlit code here,
so every function can be unit-tested on its own."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

NA = "n/a"


# ---------- formatting ----------

def is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value)


def fmt_money_big(value) -> str:
    """Dollars -> '$5.53T' / '$196.83B' / '$850.0M'."""
    if is_missing(value):
        return NA
    v = float(value)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"${v / div:,.2f}{suffix}"
    return f"${v:,.0f}"


def fmt_pct(value, digits: int = 2) -> str:
    """Percentage points -> '74.67%' (no rescaling)."""
    return NA if is_missing(value) else f"{float(value):,.{digits}f}%"


def fmt_num(value, digits: int = 2, prefix: str = "") -> str:
    return NA if is_missing(value) else f"{prefix}{float(value):,.{digits}f}"


# ---------- per-stock metrics ----------

def pct_from_52w_high(price, high) -> float:
    """(Price / 52W High - 1) x 100. Negative = below the high."""
    if is_missing(price) or is_missing(high) or float(high) == 0:
        return float("nan")
    return (float(price) / float(high) - 1) * 100


def range_position(price, low, high) -> float:
    """Where the price sits in its 52-week range: 0 = at the low, 100 = at the high."""
    if any(is_missing(x) for x in (price, low, high)) or float(high) <= float(low):
        return float("nan")
    return (float(price) - float(low)) / (float(high) - float(low)) * 100


def trend_group(sma50, sma200) -> str:
    """Uptrend: above both averages. Downtrend: below both. Otherwise Mixed."""
    if is_missing(sma50) or is_missing(sma200):
        return NA
    if sma50 > 0 and sma200 > 0:
        return "Uptrend"
    if sma50 < 0 and sma200 < 0:
        return "Downtrend"
    return "Mixed"


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["% from 52W High"] = [pct_from_52w_high(p, h) for p, h in zip(out["Price"], out["52W High"])]
    out["52W Position"] = [range_position(p, lo, hi)
                           for p, lo, hi in zip(out["Price"], out["52W Low"], out["52W High"])]
    out["Trend"] = [trend_group(a, b) for a, b in zip(out["SMA50"], out["SMA200"])]
    return out


# ---------- growth vs valuation ----------

@dataclass
class TrendFit:
    intercept: float
    slope: float
    r2: float
    n: int


def growth_valuation(df: pd.DataFrame, x: str = "EPS Next Y", y: str = "Forward P/E"):
    """Split into eligible / excluded rows and fit an unweighted OLS line.

    Only rows MISSING x or y are excluded. Negative growth is real information
    (shrinking expected earnings) and stays in the chart and the fit.
    """
    missing_x = df[x].isna()
    missing_y = df[y].isna()
    excluded = df.loc[missing_x | missing_y, ["Ticker"]].copy()
    excluded["Reason"] = [
        "; ".join(r for r, m in ((f"{x} missing", mx), (f"{y} missing", my)) if m)
        for mx, my in zip(missing_x[missing_x | missing_y], missing_y[missing_x | missing_y])
    ]
    eligible = df.loc[~(missing_x | missing_y)].copy()

    fit = None
    if len(eligible) >= 2 and eligible[x].nunique() >= 2:
        xs = eligible[x].astype(float).to_numpy()
        ys = eligible[y].astype(float).to_numpy()
        slope, intercept = np.polyfit(xs, ys, 1)
        pred = intercept + slope * xs
        ss_res = float(((ys - pred) ** 2).sum())
        ss_tot = float(((ys - ys.mean()) ** 2).sum())
        r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
        fit = TrendFit(float(intercept), float(slope), r2, len(eligible))
        eligible["Trend-implied Forward P/E"] = intercept + slope * eligible[x]
        eligible["Distance"] = eligible[y] - eligible["Trend-implied Forward P/E"]
        eligible["Reading"] = np.where(eligible["Distance"] > 0,
                                       "Above: priced richly for expected growth",
                                       "Below: priced low for expected growth")
    return eligible, excluded.reset_index(drop=True), fit
