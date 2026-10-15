"""Download a Finviz Elite screener export and clean it for the dashboard.

Usage:
    python fetch_data.py                      # download using FINVIZ_EXPORT_URL + FINVIZ_API_KEY
    python fetch_data.py --url "<url>"        # download using a URL template with auth={FINVIZ_API_KEY}
    python fetch_data.py --from-file data/sample_export.csv   # clean a saved export, no download

Cleaning rules (verified against the live Finviz export):
    - Market Cap arrives in millions of dollars -> multiply by 1,000,000.
    - Percent columns arrive as "74.67%" -> strip the % sign only, never rescale.
    - SMA50 / SMA200 are the % distance of price from the moving average, not prices.
    - "52W Range" ("164.27 - 243.37") is split into numeric 52W Low and 52W High.
    - Blank cells are missing values. The "No." row-number column is dropped.

The API key is read from the environment (or a .env file) and is never printed.
The app calls get_data(), which falls back to the last saved file when a download fails.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
RAW_PATH = DATA_DIR / "raw_export.csv"
CLEAN_PATH = DATA_DIR / "fundamentals.csv"
CT = ZoneInfo("America/Chicago")

# Default screen: large-cap (> $10B) US semiconductors, custom columns.
DEFAULT_URL = (
    "https://elite.finviz.com/export.ashx?v=152"
    "&f=cap_largeover,geo_usa,ind_semiconductors&o=-marketcap"
    "&c=0,1,2,6,65,134,53,54,10,7,8,47,138,139,17,18,39,26,59"
    "&auth={FINVIZ_API_KEY}"
)

# Finviz's long export headers -> the short names used in the app.
HEADER_MAP = {
    "52-Week Range": "52W Range",
    "50-Day Simple Moving Average": "SMA50",
    "200-Day Simple Moving Average": "SMA200",
    "Performance (YTD)": "Perf YTD",
    "Performance (3 Years)": "Perf 3Y",
    "Performance (5 Years)": "Perf 5Y",
    "EPS Growth This Year": "EPS This Y",
    "EPS Growth Next Year": "EPS Next Y",
    "Gross M": "Gross Margin",
    "Insider Ownership": "Insider Own",
    "Relative Strength Index (14)": "RSI",
}

PERCENT_COLS = [
    "SMA50", "SMA200", "Perf YTD", "Perf 3Y", "Perf 5Y",
    "EPS This Y", "EPS Next Y", "Gross Margin", "Insider Own",
]
NUMBER_COLS = ["Price", "P/S", "P/E", "Forward P/E", "RSI"]
REQUIRED_COLS = ["Ticker", "Company", "Market Cap", "Price", "52W Range"] + PERCENT_COLS + [
    "P/S", "P/E", "Forward P/E", "RSI",
]

MIN_SECONDS_BETWEEN_REQUESTS = 0.6  # Finviz Elite allows 10 requests per 5 seconds


class FetchError(RuntimeError):
    """A download or cleaning failure. The message is safe to show: it never contains the key or URL."""


def has_key() -> bool:
    return bool(os.environ.get("FINVIZ_API_KEY", "").strip())


def load_env() -> None:
    """Load a local .env file if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).parent / ".env")


def download(url_template: str) -> str:
    """Download the export. The key is filled in here and never printed."""
    import requests

    key = os.environ.get("FINVIZ_API_KEY", "").strip()
    if not key:
        raise FetchError("FINVIZ_API_KEY is not set. Add it to .env or your environment.")
    if "{FINVIZ_API_KEY}" not in url_template:
        raise FetchError("The URL must contain the placeholder auth={FINVIZ_API_KEY}, not a real key.")

    url = url_template.replace("{FINVIZ_API_KEY}", key)
    time.sleep(MIN_SECONDS_BETWEEN_REQUESTS)
    try:
        resp = requests.get(url, timeout=30, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as exc:
        # Do not include the URL in the message, or chain the original error: both contain the key.
        raise FetchError(f"Network error while downloading the Finviz export ({type(exc).__name__}).") from None
    if resp.status_code != 200:
        raise FetchError(f"Finviz returned HTTP {resp.status_code}. Check the key and the export URL.")
    text = resp.text
    if text.lstrip().lower().startswith("<"):
        raise FetchError("Finviz returned a web page instead of CSV. The key is probably invalid or expired.")
    return text


def to_number(series: pd.Series) -> pd.Series:
    """Convert text like '74.67%', '1,029.00' or '' to floats (missing -> NaN)."""
    cleaned = (
        series.astype("string")
        .str.strip()
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace({"": pd.NA, "-": pd.NA})
    )
    return pd.to_numeric(cleaned, errors="raise")


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns=HEADER_MAP).copy()
    df = df.drop(columns=["No."], errors="ignore")

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Export is missing required columns: {missing}. "
                         "Check that the URL uses the custom column list (&c=...).")

    df["Market Cap"] = to_number(df["Market Cap"]) * 1_000_000
    for col in PERCENT_COLS + NUMBER_COLS:
        df[col] = to_number(df[col])

    rng = df["52W Range"].astype("string").str.split(" - ", n=1, expand=True)
    df["52W Low"] = to_number(rng[0])
    df["52W High"] = to_number(rng[1])

    order = ["Ticker", "Company", "Market Cap", "Price", "52W Range", "SMA50", "SMA200",
             "P/S", "P/E", "Forward P/E", "Perf YTD", "Perf 3Y", "Perf 5Y",
             "EPS This Y", "EPS Next Y", "Gross Margin", "Insider Own", "RSI",
             "52W Low", "52W High"]
    return df[order].sort_values("Market Cap", ascending=False).reset_index(drop=True)


def save(text: str) -> pd.DataFrame:
    """Clean an export and save it. Nothing is written unless cleaning succeeds."""
    try:
        cleaned = clean(pd.read_csv(StringIO(text), dtype=str, keep_default_na=False))
    except ValueError as exc:  # includes pandas parser errors and missing columns
        raise FetchError(f"The Finviz export could not be read: {exc}") from None

    DATA_DIR.mkdir(exist_ok=True)
    raw_tmp, clean_tmp = RAW_PATH.with_suffix(".csv.tmp"), CLEAN_PATH.with_suffix(".csv.tmp")
    try:
        # Write to temp files and swap them in, so a failed write never damages the last good data.
        raw_tmp.write_text(text, encoding="utf-8")
        cleaned.to_csv(clean_tmp, index=False)
        os.replace(raw_tmp, RAW_PATH)
        os.replace(clean_tmp, CLEAN_PATH)
    except OSError as exc:
        raise FetchError(f"Couldn't save the data file ({type(exc).__name__}).") from None
    return cleaned


def fetch_and_save(url_template: str) -> pd.DataFrame:
    """One request to Finviz, then clean and save. Raises FetchError on any failure."""
    return save(download(url_template))


def load_saved() -> tuple[pd.DataFrame | None, datetime | None]:
    """The last saved clean data and when it was written, or (None, None) if there is none."""
    if not CLEAN_PATH.exists():
        return None, None
    updated = datetime.fromtimestamp(CLEAN_PATH.stat().st_mtime, tz=CT)
    return pd.read_csv(CLEAN_PATH), updated


def fmt_ct(dt: datetime) -> str:
    """'Oct 15, 2026 2:05 PM CT' (built by hand: Windows strftime has no %-I)."""
    dt = dt.astimezone(CT)
    return f"{dt:%b} {dt.day}, {dt.year} {dt.hour % 12 or 12}:{dt:%M} {dt:%p} CT"


def claim_refresh(log: dict, cooldown: float, now: float | None = None) -> tuple[bool, float]:
    """A manual refresh may call Finviz only if the last request was at least `cooldown` seconds ago.

    log holds "last" (time of the last request) and "lock". Returns (allowed, seconds since the last
    request). When allowed, the request time is recorded under the lock, so of several tabs clicking
    at once only one wins.
    """
    now = time.time() if now is None else now
    with log["lock"]:
        since = now - log["last"]
        if since < cooldown:
            return False, since
        log["last"] = now
        return True, since


def _scrub(message: str) -> str:
    """Belt and braces: remove the key from any message that will be shown."""
    key = os.environ.get("FINVIZ_API_KEY", "").strip()
    return message.replace(key, "***") if key else message


@dataclass
class DataResult:
    df: pd.DataFrame | None       # None only when there is no data at all
    updated_at: datetime | None
    live: bool                    # True when the latest refresh succeeded
    message: str | None = None    # warning (df present) or error (df is None)


def get_data(fetch: Callable[[], object]) -> DataResult:
    """Refresh with fetch() if a key is set, otherwise or on failure fall back to the saved file.

    fetch must make at most one request and raise FetchError on failure. Never raises.
    """
    if not has_key():
        df, updated = load_saved()
        if df is None:
            return DataResult(None, None, False,
                              "No data yet. Add FINVIZ_API_KEY to .env for live data, or run "
                              "`python fetch_data.py --from-file data/sample_export.csv`.")
        return DataResult(df, updated, False,
                          f"FINVIZ_API_KEY isn't set in .env, so live refresh is off. "
                          f"Showing saved data, last updated {fmt_ct(updated)}.")
    try:
        fetch()
        error = None
    except FetchError as exc:
        error = _scrub(str(exc))
    except Exception as exc:  # never crash the app, and never show a traceback that could hold the URL
        error = f"Unexpected error while refreshing ({type(exc).__name__})."

    df, updated = load_saved()
    if error is None and df is not None:
        return DataResult(df, updated, True)
    if df is None:
        return DataResult(None, None, False, f"Couldn't download from Finviz: {error} No saved data yet.")
    return DataResult(df, updated, False,
                      f"Couldn't refresh from Finviz: {error} Showing the last good data, "
                      f"last updated {fmt_ct(updated)}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="Export URL template containing auth={FINVIZ_API_KEY}")
    parser.add_argument("--from-file", help="Clean a saved Finviz export instead of downloading")
    args = parser.parse_args()

    load_env()
    try:
        if args.from_file:
            cleaned = save(Path(args.from_file).read_text(encoding="utf-8-sig"))
        else:
            cleaned = fetch_and_save(args.url or os.environ.get("FINVIZ_EXPORT_URL") or DEFAULT_URL)
    except FetchError as exc:
        sys.exit(str(exc))

    print(f"Saved {RAW_PATH.name} and {CLEAN_PATH.name}: "
          f"{len(cleaned)} stocks, {len(cleaned.columns)} columns.\n")
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(cleaned.head(5).to_string(index=False))
    print("\nColumns:", ", ".join(cleaned.columns))


if __name__ == "__main__":
    main()
