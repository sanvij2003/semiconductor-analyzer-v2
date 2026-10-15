"""Checks the cleaning and calculations against values read off the Finviz screener."""

from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from analysis import add_derived, fmt_money_big, fmt_pct, growth_valuation, range_position
from fetch_data import clean

SAMPLE = Path(__file__).parent.parent / "data" / "sample_export.csv"


@pytest.fixture(scope="module")
def df():
    raw = pd.read_csv(StringIO(SAMPLE.read_text()), dtype=str, keep_default_na=False)
    return add_derived(clean(raw)).set_index("Ticker", drop=False)


def test_shape(df):
    assert len(df) == 22
    assert "No." not in df.columns and {"52W Low", "52W High"} <= set(df.columns)


def test_nvda_matches_finviz(df):
    nvda = df.loc["NVDA"]
    assert fmt_money_big(nvda["Market Cap"]) == "$5.53T"
    assert nvda["Gross Margin"] == pytest.approx(74.67)   # % stripped, not rescaled
    assert nvda["SMA50"] == pytest.approx(3.24)
    assert (nvda["52W Low"], nvda["52W High"]) == (164.27, 243.37)
    assert fmt_pct(nvda["% from 52W High"]) == "-5.79%"


def test_missing_values_stay_missing(df):
    assert pd.isna(df.loc["CBRS", "Forward P/E"]) and pd.isna(df.loc["INTC", "P/E"])


def test_trend_groups(df):
    counts = df["Trend"].value_counts().to_dict()
    assert counts == {"Uptrend": 15, "Downtrend": 3, "Mixed": 4}
    assert set(df[df["Trend"] == "Downtrend"].index) == {"AVGO", "CBRS", "MCHP"}


def test_growth_valuation_keeps_negatives(df):
    eligible, excluded, fit = growth_valuation(df.reset_index(drop=True))
    assert list(excluded["Ticker"]) == ["CBRS"]
    assert {"QCOM", "SWKS"} <= set(eligible["Ticker"])
    assert fit.n == 21
    assert fit.intercept == pytest.approx(19.18, abs=0.01)
    assert fit.slope == pytest.approx(0.2147, abs=0.0005)
    assert fit.r2 == pytest.approx(0.207, abs=0.001)


def test_range_position():
    assert range_position(229.28, 164.27, 243.37) == pytest.approx(82.19, abs=0.01)
    assert pd.isna(range_position(10, 20, 20))
