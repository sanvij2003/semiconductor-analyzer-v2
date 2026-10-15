"""Semiconductor Stock Financial Analysis: a Streamlit dashboard over a Finviz screener export.

Run:  streamlit run app.py
"""

from __future__ import annotations

import math
import os
import threading
import time

import pandas as pd
import streamlit as st

import charts
import fetch_data
from analysis import NA, add_derived, fmt_money_big, fmt_num, fmt_pct, growth_valuation
from fetch_data import (DEFAULT_URL, FetchError, claim_refresh, fetch_and_save, fmt_ct, get_data,
                        has_key, load_env)

load_env()
URL_TEMPLATE = os.environ.get("FINVIZ_EXPORT_URL") or DEFAULT_URL  # holds the placeholder, never the key
INTERVALS = [1, 5, 15]           # minutes
REFRESH_COOLDOWN = 60            # seconds: "Refresh now" forces at most one extra request per minute
TICK_SECONDS = 15                # how often auto-refresh checks whether the cache has expired

PCT_COLS = ["SMA50", "SMA200", "Perf YTD", "Perf 3Y", "Perf 5Y", "EPS This Y", "EPS Next Y",
            "Gross Margin", "Insider Own", "% from 52W High", "52W Position"]

st.set_page_config(page_title="Semiconductor Stock Financial Analysis", page_icon="📊", layout="wide")


@st.cache_resource
def request_log() -> dict:
    """Shared by every session and tab on this server: when Finviz was last called."""
    return {"last": 0.0, "lock": threading.Lock()}


def _download(url_template: str) -> str | None:
    """Exactly one Finviz request. Returns an error message instead of raising, so a failure is
    cached for the interval too and a Finviz outage can't trigger a request on every reload."""
    log = request_log()
    log["last"] = time.time()
    try:
        fetch_and_save(url_template)
        return None
    except FetchError as exc:
        return str(exc)
    except Exception as exc:  # never show a traceback: it could contain the authenticated URL
        return f"Unexpected error while refreshing ({type(exc).__name__})."
    finally:
        log["last"] = time.time()


# One cache per interval, so each TTL equals its interval. These must be separate functions:
# Streamlit keys a cache by function name and source, so one function wrapped three times shares one.
@st.cache_data(ttl=60, show_spinner="Refreshing from Finviz…")
def download_every_1m(url_template: str) -> str | None:
    return _download(url_template)


@st.cache_data(ttl=5 * 60, show_spinner="Refreshing from Finviz…")
def download_every_5m(url_template: str) -> str | None:
    return _download(url_template)


@st.cache_data(ttl=15 * 60, show_spinner="Refreshing from Finviz…")
def download_every_15m(url_template: str) -> str | None:
    return _download(url_template)


DOWNLOADERS = {1: download_every_1m, 5: download_every_5m, 15: download_every_15m}


def saved_mtime() -> float:
    path = fetch_data.CLEAN_PATH
    return path.stat().st_mtime if path.exists() else 0.0


@st.fragment(run_every=TICK_SECONDS)
def auto_refresh(interval_s: float, shown_mtime: float) -> None:
    """Rerun the whole app once this interval's cache has expired, or when another tab saved newer data."""
    # +1s: file times are finer than the displayed datetime, so an exact comparison would loop forever.
    if time.time() - request_log()["last"] >= interval_s + 2 or saved_mtime() > shown_mtime + 1:
        st.rerun(scope="app")


def styled(df: pd.DataFrame):
    """Readable formatting with 'n/a' for missing values; sorting still uses the real numbers."""
    fmt = {c: (lambda v: fmt_pct(v)) for c in PCT_COLS if c in df}
    fmt.update({c: (lambda v: fmt_num(v)) for c in ("Price", "P/S", "P/E", "Forward P/E", "RSI",
                                                     "52W Low", "52W High", "Trend-implied Forward P/E")
                if c in df})
    if "Market Cap" in df:
        fmt["Market Cap"] = fmt_money_big
    if "Distance" in df:
        fmt["Distance"] = lambda v: NA if pd.isna(v) else f"{v:+.2f}"
    return df.style.format(fmt, na_rep=NA)


# ---------- data ----------
live_ok = has_key()
with st.sidebar:
    st.header("Data")
    no_key_help = None if live_ok else "Add FINVIZ_API_KEY to .env to enable live data."
    refresh = st.button("Refresh now", disabled=not live_ok, help=no_key_help)
    auto = st.toggle("Auto-refresh", value=False, disabled=not live_ok, help=no_key_help)
    interval = st.radio("Refresh interval", INTERVALS, index=INTERVALS.index(5), horizontal=True,
                        format_func=lambda m: f"{m} min", disabled=not live_ok,
                        help="Finviz is called at most once per interval, however many tabs or reloads.")
    last_updated = st.empty()

if refresh:
    allowed, since = claim_refresh(request_log(), REFRESH_COOLDOWN)
    if allowed:
        for downloader in DOWNLOADERS.values():
            downloader.clear()
    else:
        st.sidebar.info(f"Finviz was called {int(since)}s ago. Try again in "
                        f"{math.ceil(REFRESH_COOLDOWN - since)}s.")


def fetch() -> None:
    error = DOWNLOADERS[interval](URL_TEMPLATE)
    if error:
        raise FetchError(error)


result = get_data(fetch)
if result.df is None:
    st.error(result.message)
    st.stop()
last_updated.caption(f"Last updated: {fmt_ct(result.updated_at)}")
if auto:
    auto_refresh(interval * 60, result.updated_at.timestamp())

df_all = add_derived(result.df)

# ---------- sidebar filters ----------
with st.sidebar:
    st.header("Filter companies")
    lo_b = float(df_all["Market Cap"].min() / 1e9)
    hi_b = float(df_all["Market Cap"].max() / 1e9)
    cap_range = st.slider("Market cap range ($B)", min_value=round(lo_b, 2), max_value=round(hi_b, 2),
                          value=(round(lo_b, 2), round(hi_b, 2)), format="$%.0fB")
    st.caption(f"From {fmt_money_big(cap_range[0] * 1e9)} to {fmt_money_big(cap_range[1] * 1e9)}"
               .replace("$", r"\$"))
    picked = st.multiselect("Tickers", sorted(df_all["Ticker"]), placeholder="All tickers",
                            help="Leave empty to include every stock.")

lo, hi = cap_range[0] * 1e9 - 1e6, cap_range[1] * 1e9 + 1e6  # tolerance for slider rounding
df = df_all[df_all["Market Cap"].between(lo, hi)]
if picked:
    df = df[df["Ticker"].isin(picked)]

with st.sidebar:
    st.caption(f"{len(df)} of {len(df_all)} companies match")
    st.download_button("Download filtered data", df.to_csv(index=False).encode(),
                       file_name="semis_filtered.csv", mime="text/csv", disabled=df.empty)

# ---------- header ----------
st.title("Semiconductor Stock Financial Analysis")
st.caption(f"Data as of {fmt_ct(result.updated_at)}, from a Finviz Elite screener export · "
           "Large-cap (> \\$10B) US semiconductor companies")
if result.message:
    (st.info if not live_ok else st.warning)(result.message)

if df.empty:
    st.info("No companies match these filters. Widen the market cap range or clear the ticker filter.")
    st.stop()

tab_snap, tab_peer, tab_gv, tab_tech, tab_ret = st.tabs(
    ["Company Snapshot", "Peer Comparison", "Growth vs Valuation", "Technicals & Trend", "Long-term Returns"])

# ---------- 1. Company Snapshot ----------
with tab_snap:
    tickers = list(df["Ticker"])
    ticker = st.selectbox("Pick a ticker", tickers, index=tickers.index("NVDA") if "NVDA" in tickers else 0)
    row = df[df["Ticker"] == ticker].iloc[0]
    st.subheader(f"{ticker} — {row['Company']}")

    cards = [
        ("Market Cap", fmt_money_big(row["Market Cap"])),
        ("Price", fmt_num(row["Price"], prefix="$")),
        ("P/S", fmt_num(row["P/S"])),
        ("P/E", fmt_num(row["P/E"])),
        ("Forward P/E", fmt_num(row["Forward P/E"])),
        ("EPS This Y", fmt_pct(row["EPS This Y"])),
        ("EPS Next Y", fmt_pct(row["EPS Next Y"])),
        ("Gross Margin", fmt_pct(row["Gross Margin"])),
        ("Insider Own", fmt_pct(row["Insider Own"])),
        ("RSI", fmt_num(row["RSI"])),
        ("% from 52-week high", fmt_pct(row["% from 52W High"])),
    ]
    for start, width in ((0, 4), (4, 4), (8, 3)):
        cols = st.columns(width, border=True)
        for col, (label, value) in zip(cols, cards[start:start + width]):
            col.metric(label, value)

    missing = [label for label, value in cards if value == NA]
    if missing:
        st.info(f"{ticker} has no value for {', '.join(missing)} in this export, so those cards show n/a. "
                "The other metrics are still available.")
    with st.expander("How this is calculated"):
        st.markdown("- Growth, margin and ownership values are percentage points from Finviz (74.67 = 74.67%).\n"
                    "- Market Cap: Finviz exports millions of dollars; the app multiplies by 1,000,000.\n"
                    "- % from 52-week high = (Price ÷ 52W High − 1) × 100. Negative means below the high.")

# ---------- 2. Peer Comparison ----------
with tab_peer:
    st.subheader("Peer Comparison")
    st.caption("Click any column header to sort. Market caps in \\$B / \\$T; percentages are percentage points.")
    first = ["Ticker", "Market Cap", "Price", "Forward P/E", "P/S", "EPS Next Y", "Gross Margin"]
    rest = ["Company", "52W Range", "SMA50", "SMA200", "P/E", "Perf YTD", "Perf 3Y", "Perf 5Y",
            "EPS This Y", "Insider Own", "RSI"]
    st.dataframe(styled(df[first + rest]), hide_index=True, width="stretch", placeholder=NA)

    c1, c2 = st.columns(2)
    c1.plotly_chart(charts.ranking_bar(df, "Forward P/E", "Forward P/E, lowest first", suffix="×"),
                    width="stretch")
    c2.plotly_chart(charts.ranking_bar(df, "P/S", "Price-to-sales, lowest first", suffix="×"),
                    width="stretch")
    c3, c4 = st.columns(2)
    c3.plotly_chart(charts.ranking_bar(df, "Gross Margin", "Gross margin, highest first", suffix="%",
                                       ascending=False), width="stretch")
    c4.plotly_chart(charts.ranking_bar(df, "EPS Next Y", "Expected EPS growth next year, highest first",
                                       suffix="%", ascending=False), width="stretch")
    st.caption("Lower valuation multiples and higher margins or growth rank at the top of each chart.")

# ---------- 3. Growth vs Valuation ----------
with tab_gv:
    st.subheader("Growth vs Valuation")
    eligible, excluded, fit = growth_valuation(df)
    if eligible.empty:
        st.info("None of the filtered stocks have both EPS Next Y and Forward P/E.")
    else:
        st.plotly_chart(charts.growth_scatter(eligible, fit), width="stretch")
        st.caption("Each bubble is a stock; bubble area shows market cap. Points above the line are valued "
                   "higher than their expected EPS growth implies; points below are valued lower.")
        if fit is not None:
            st.markdown(f"**Trend line:** Forward P/E = {fit.intercept:.2f} + {fit.slope:.3f} × EPS Next Y "
                        f"· **R² = {fit.r2:.2f}** across {fit.n} stocks. Expected growth explains about "
                        f"{fit.r2 * 100:.0f}% of the differences in valuation.")
        if not excluded.empty:
            st.markdown("**Excluded (missing EPS Next Y or Forward P/E)**")
            st.dataframe(excluded, hide_index=True, width="stretch", placeholder=NA)

        if fit is not None:
            st.markdown("#### Distance from the trend line")
            table = eligible[["Ticker", "EPS Next Y", "Forward P/E", "Trend-implied Forward P/E",
                              "Distance", "Reading"]].sort_values("Distance", ascending=False)
            st.dataframe(styled(table), hide_index=True, width="stretch", placeholder=NA)
        with st.expander("How this is calculated"):
            st.markdown("- Unweighted ordinary least squares (OLS) line through all eligible stocks.\n"
                        "- Distance = actual Forward P/E − trend-implied Forward P/E, in P/E multiple units.\n"
                        "- Only stocks missing a required value are excluded. Negative expected growth is "
                        "kept: it is real information, not bad data.\n"
                        "- The axis is not capped, so every stock is fully visible.\n"
                        "- The line describes this sample. It is not a forecast or a recommendation.")

# ---------- 4. Technicals & Trend ----------
with tab_tech:
    st.subheader("Technicals & Trend")
    st.plotly_chart(charts.trend_map(df), width="stretch")
    st.caption("Upper right = Uptrend (price above both averages). Lower left = Downtrend (below both). "
               "The other two corners are Mixed.")
    groups = (df.groupby("Trend")["Ticker"].apply(lambda s: ", ".join(sorted(s)))
              .reindex(["Uptrend", "Downtrend", "Mixed"]).dropna().reset_index())
    groups.insert(1, "Count", groups["Ticker"].str.count(",") + 1)
    groups.columns = ["Group", "Count", "Tickers"]
    st.dataframe(groups, hide_index=True, width="stretch", placeholder=NA)

    st.plotly_chart(charts.rsi_bar(df), width="stretch")
    st.caption("RSI above 70 is usually read as overbought and below 30 as oversold.")
    st.plotly_chart(charts.range_position_bar(df), width="stretch")
    st.caption("100% means the price is at its 52-week high; 0% means it is at its 52-week low.")
    with st.expander("How this is calculated"):
        st.markdown("- SMA50 / SMA200 are Finviz's % distance of price from the 50-day and 200-day "
                    "simple moving averages (not the averages themselves).\n"
                    "- 52-week position = (Price − 52W Low) ÷ (52W High − 52W Low) × 100.")

# ---------- 5. Long-term Returns ----------
with tab_ret:
    st.subheader("Long-term Returns")
    choice = st.radio("Show", ["All periods", "YTD", "3 years", "5 years"], horizontal=True)
    periods = {"All periods": ["Perf YTD", "Perf 3Y", "Perf 5Y"], "YTD": ["Perf YTD"],
               "3 years": ["Perf 3Y"], "5 years": ["Perf 5Y"]}[choice]
    st.plotly_chart(charts.returns_grouped(df, periods), width="stretch")
    st.caption("Stocks with no data for a period (recent IPOs) show a gap, not a zero bar, and sort last. "
               "Pick a single period to compare smaller returns more easily.")
