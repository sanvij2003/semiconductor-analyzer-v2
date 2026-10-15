# Semiconductor Stock Financial Analysis

A Streamlit dashboard that turns a Finviz Elite screener export of large-cap US semiconductor
stocks into five interactive views: company snapshot, peer comparison, growth vs valuation,
technicals and trend, and long-term returns. Built with AI coding assistants for Week 1 of the
Mastering Agentic AI course.

## The five tabs

| Tab | What it shows |
|---|---|
| Company Snapshot | 11 KPI cards for one ticker: market cap, price, P/S, P/E, Forward P/E, EPS growth this and next year, gross margin, insider ownership, RSI, % from 52-week high |
| Peer Comparison | Sortable table (n/a for missing values, $B/$T market caps) and ranked bars for Forward P/E, P/S, gross margin, EPS Next Y |
| Growth vs Valuation | Expected EPS growth vs Forward P/E, bubble area = market cap, OLS trend line with R², and each stock's distance above or below the line |
| Technicals & Trend | Uptrend / Downtrend / Mixed map from SMA50 and SMA200, RSI ranking with 30/70 lines, 52-week range position |
| Long-term Returns | YTD, 3-year and 5-year returns, with a period selector; missing data shows as gaps, not zeros |

The sidebar filters every tab by market cap range and ticker (empty = all stocks) and has a
**Download filtered data** button.

## Run it (Windows, macOS or Linux)

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

**Get the data, option A: live from Finviz (needs Finviz Elite)**
1. Copy `.env.example` to `.env` and paste your API token after `FINVIZ_API_KEY=`.
2. `python fetch_data.py`

**Get the data, option B: from a saved export (no key needed)**
```bash
python fetch_data.py --from-file data/sample_export.csv
```

**Start the app**
```bash
streamlit run app.py
```
Open http://localhost:8501. The app runs only on your computer.

**Run the tests**
```bash
pytest
```

## Live data

With `FINVIZ_API_KEY` in `.env`, the app downloads the export itself; the sidebar's **Data**
section controls it.
- **Refresh now** downloads fresh data. It's limited to one Finviz request per 60 seconds;
  clicking sooner tells you how long to wait.
- **Auto-refresh** re-downloads every 1, 5 or 15 minutes (default 5). Finviz is called at most once
  per interval, however many browser tabs are open or reloads you do.
- **Last updated** shows when the data was saved, in Central Time.
- If a download fails, the app keeps showing the last good data with a warning, and the saved file
  is never overwritten by a bad download. Without a key, it shows the saved data and live refresh
  is turned off.

## Data and cleaning rules

Screen: Industry = Semiconductors, Country = USA, Market Cap = Large (over $10B). 22 stocks.

| Raw format in the Finviz export | Cleaning rule |
|---|---|
| Market Cap in millions (NVDA: 5525647.97) | Multiply by 1,000,000 |
| Percent columns as "74.67%" | Strip the % sign only, never rescale |
| SMA50 / SMA200 = % distance of price from the moving average | Keep as percent; they are not prices |
| 52W Range as text ("164.27 - 243.37") | Split into 52W Low and 52W High |
| Blank cells (CBRS, a recent IPO; INTC P/E) | Missing values, shown as n/a |
| "No." row-number column | Dropped |

## Security
- The API key lives only in `.env`, which is in `.gitignore`. The fetch script never prints it,
  and error messages never include the authenticated URL.
- `data/` is in `.gitignore`: Finviz data is licensed to your account and shouldn't be republished.
- Don't deploy the app publicly with live Finviz data.

## Limitations
- Earnings growth only, no revenue growth or operating margin. EPS growth from a depressed base
  looks inflated.
- Snapshot data as of the export date, with no history.
- The app shows how much of a valuation the current numbers support. It can't judge narrative:
  contracts, product cycles or announcements.
