# Project rules for Claude Code

Semiconductor Stock Financial Analysis: a Streamlit + Plotly dashboard over a Finviz Elite screener export.

## Files
- `fetch_data.py`: downloads the Finviz export and cleans it into `data/fundamentals.csv`
- `analysis.py`: calculations and formatting (no Streamlit code; unit-tested)
- `charts.py`: Plotly figures
- `app.py`: the Streamlit app (5 tabs)
- `tests/test_analysis.py`: checks values against the Finviz screener

## Rules
- Read `FINVIZ_API_KEY` from `.env` with python-dotenv. Never print, log, hard-code or commit it.
- Finviz units: Market Cap is in millions (multiply by 1,000,000). Percent columns arrive as "74.67%":
  strip the % sign, never rescale. SMA50/SMA200 are % distance from the moving average, not prices.
  Blank cells are missing; display "n/a".
- Never exclude real data from charts (e.g. negative growth) unless I say so. Only drop missing values.
- Don't cap chart axes in a way that hides data points.
- Build one feature per request. Don't add tabs I haven't asked for.
- Run `pytest` after every change to `fetch_data.py` or `analysis.py`.
- Never run `git commit` or `git push` without asking me first. Never commit `data/` or `.env`.
- Don't deploy or publish the app: Finviz data is licensed to my account.
