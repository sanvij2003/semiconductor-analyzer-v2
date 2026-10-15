"""Live refresh: one request per refresh, and the last good data survives every kind of failure.

No network and no real key: requests.get is replaced and the data files live in a temp folder.
"""

import os
import threading

import pandas as pd
import pytest
import requests

import fetch_data
from fetch_data import FetchError, fetch_and_save, get_data

KEY = "TESTKEY-not-real-123"
URL = fetch_data.DEFAULT_URL

# A minimal one-row export with Finviz's long headers.
LONG = {v: k for k, v in fetch_data.HEADER_MAP.items()}
EXPORT_ROW = {
    "No.": "1", "Ticker": "NVDA", "Company": "NVIDIA Corp", "Market Cap": "5525647.97", "Price": "229.28",
    "52W Range": "164.27 - 243.37", "SMA50": "3.24%", "SMA200": "12.50%", "P/S": "30.10", "P/E": "55.00",
    "Forward P/E": "30.00", "Perf YTD": "40.00%", "Perf 3Y": "900.00%", "Perf 5Y": "1500.00%",
    "EPS This Y": "50.00%", "EPS Next Y": "35.00%", "Gross Margin": "74.67%", "Insider Own": "4.00%",
    "RSI": "60.00",
}
EXPORT_CSV = (",".join(f'"{LONG.get(k, k)}"' for k in EXPORT_ROW) + "\n"
              + ",".join(f'"{v}"' for v in EXPORT_ROW.values()) + "\n")
SAVED_CSV = "Ticker,Company,Market Cap\nOLD,Last Good Inc,1000000\n"


class FakeResponse:
    def __init__(self, status_code=200, text=EXPORT_CSV):
        self.status_code, self.text = status_code, text


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp data folder, a fake key, no rate-limit sleep, and a counter of requests made."""
    monkeypatch.setattr(fetch_data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fetch_data, "RAW_PATH", tmp_path / "raw_export.csv")
    monkeypatch.setattr(fetch_data, "CLEAN_PATH", tmp_path / "fundamentals.csv")
    monkeypatch.setattr(fetch_data, "MIN_SECONDS_BETWEEN_REQUESTS", 0)
    monkeypatch.setenv("FINVIZ_API_KEY", KEY)
    calls = []

    def respond_with(result):
        def fake_get(url, **kwargs):
            calls.append(url)
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(requests, "get", fake_get)

    return tmp_path, calls, respond_with


def save_last_good(folder):
    path = folder / "fundamentals.csv"
    path.write_text(SAVED_CSV)
    os.utime(path, (1_760_000_000, 1_760_000_000))  # Oct 9, 2025 3:53 AM CT
    return path


def assert_safe(message):
    assert KEY not in message and "auth=" not in message and "finviz.com" not in message


@pytest.mark.parametrize("failure", [
    requests.ConnectionError(f"Max retries exceeded with url: /export.ashx?auth={KEY}"),
    requests.Timeout(f"Read timed out: https://elite.finviz.com/export.ashx?auth={KEY}"),
    FakeResponse(status_code=500, text="Server error"),
    FakeResponse(status_code=200, text="<!DOCTYPE html><html>Login</html>"),
    FakeResponse(status_code=200, text="not,a,finviz\nexport,at,all\n"),
], ids=["network", "timeout", "http-500", "login-page", "wrong-columns"])
def test_failure_keeps_last_good_data(env, failure):
    folder, calls, respond_with = env
    saved = save_last_good(folder)
    respond_with(failure)

    result = get_data(lambda: fetch_and_save(URL))

    assert len(calls) == 1
    assert not result.live
    assert list(result.df["Ticker"]) == ["OLD"]
    assert saved.read_text() == SAVED_CSV            # the last good file is untouched
    assert not (folder / "raw_export.csv").exists()
    assert "last updated Oct 9, 2025 3:53 AM CT" in result.message
    assert_safe(result.message)


def test_failure_with_no_saved_data_returns_error_not_crash(env):
    folder, calls, respond_with = env
    respond_with(requests.ConnectionError(f"auth={KEY}"))

    result = get_data(lambda: fetch_and_save(URL))

    assert result.df is None and not result.live
    assert "No saved data yet" in result.message
    assert_safe(result.message)


def test_unexpected_error_is_caught_and_hides_details(env):
    folder, _, _ = env
    save_last_good(folder)

    def broken():
        raise KeyError(f"https://elite.finviz.com/export.ashx?auth={KEY}")

    result = get_data(broken)

    assert list(result.df["Ticker"]) == ["OLD"]
    assert "KeyError" in result.message
    assert_safe(result.message)


def test_missing_key_uses_saved_data_without_a_request(env, monkeypatch):
    folder, calls, respond_with = env
    save_last_good(folder)
    respond_with(FakeResponse())
    monkeypatch.delenv("FINVIZ_API_KEY")

    result = get_data(lambda: fetch_and_save(URL))

    assert calls == []
    assert list(result.df["Ticker"]) == ["OLD"] and not result.live
    assert "FINVIZ_API_KEY isn't set" in result.message


def test_missing_key_and_no_saved_data(env, monkeypatch):
    monkeypatch.delenv("FINVIZ_API_KEY")
    result = get_data(lambda: pytest.fail("must not fetch without a key"))
    assert result.df is None and "--from-file" in result.message


def test_success_saves_both_files_with_one_request(env):
    folder, calls, respond_with = env
    save_last_good(folder)
    respond_with(FakeResponse())

    result = get_data(lambda: fetch_and_save(URL))

    assert len(calls) == 1 and KEY in calls[0]       # the key goes into the request only
    assert result.live and result.message is None
    assert list(result.df["Ticker"]) == ["NVDA"]
    assert result.df.loc[0, "Market Cap"] == pytest.approx(5_525_647_970_000)
    assert (folder / "raw_export.csv").read_text() == EXPORT_CSV
    assert not list(folder.glob("*.tmp"))


def test_fetch_error_message_never_contains_key(env):
    _, _, respond_with = env
    respond_with(requests.ConnectionError(f"https://elite.finviz.com/export.ashx?auth={KEY}"))
    with pytest.raises(FetchError) as info:
        fetch_and_save(URL)
    assert_safe(str(info.value))
    assert info.value.__cause__ is None and info.value.__suppress_context__


def new_log(last=0.0):
    return {"last": last, "lock": threading.Lock()}


def test_refresh_cooldown_blocks_a_second_request_within_60s():
    log = new_log()
    assert fetch_data.claim_refresh(log, 60, now=1000.0)[0]
    assert log["last"] == 1000.0

    allowed, since = fetch_data.claim_refresh(log, 60, now=1059.0)
    assert not allowed and since == pytest.approx(59.0)
    assert log["last"] == 1000.0                     # a refused click doesn't restart the cooldown

    assert fetch_data.claim_refresh(log, 60, now=1060.0) == (True, pytest.approx(60.0))
    assert log["last"] == 1060.0


def test_refresh_cooldown_counts_from_any_request_not_just_clicks():
    log = new_log(last=1000.0)                       # e.g. an auto-refresh download just ran
    assert not fetch_data.claim_refresh(log, 60, now=1030.0)[0]


def test_refresh_cooldown_lets_only_one_of_many_simultaneous_clicks_through():
    log = new_log()
    results, start = [], threading.Barrier(20)

    def click():
        start.wait()
        results.append(fetch_data.claim_refresh(log, 60, now=1000.0)[0])

    threads = [threading.Thread(target=click) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1


def test_saved_data_reads_like_the_app_expects(env):
    folder, _, _ = env
    save_last_good(folder)
    df, updated = fetch_data.load_saved()
    assert isinstance(df, pd.DataFrame) and fetch_data.fmt_ct(updated) == "Oct 9, 2025 3:53 AM CT"
