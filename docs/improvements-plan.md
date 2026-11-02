# Planned improvements

Agreed while the broad-universe re-test was running. Nothing here is built yet;
implementation starts after the re-test, so any threshold changes it produces land
first and these features build on the result.

## 1. Next-event column

One column showing the nearest upcoming event per ticker, e.g. `Earnings · 9d` or
`Ex-div · 4d`.

- **Earnings date:** Finnhub `calendar/earnings`, queried per symbol, cross-checked
  against Yahoo. Yahoo marks whether a date is confirmed or estimated; Finnhub does
  not. An unconfirmed date is shown with a tilde: `~9d`.
- **Ex-dividend date:** Yahoo only (Finnhub's dividend endpoints are paid).
- **Colour:** gradient from green at 30 days to red at 3 days or fewer. Beyond 30
  days the cell stays neutral.
- Accumulating ETFs such as VUAA.L have neither event; the cell is empty, not an
  error.
- Collected by the daily CI job alongside the analyst record, since Yahoo refuses the
  quote endpoint from Streamlit Cloud.

## 2. Ticker detail panel

Selecting a row opens a panel below the table (Streamlit row selection; a cell link
can only open an external page).

- From price history (works everywhere): chart with the Bollinger bands and dip
  levels, 52-week high/low, distance from the high, 1M/3M/YTD/1Y returns.
- From Finnhub: company profile (name, industry, market cap, logo, website), basic
  metrics (P/E, beta), earnings history with surprise %, recommendation trend, and
  recent news.
- Upcoming events in full: both earnings and ex-dividend, with EPS and revenue
  estimates.
- External links: Yahoo Finance, TradingView, the company website.

## 3. Personal watchlists

- Tickers are picked from a curated list (`data/universe.csv`: ticker, name, sector)
  with `st.multiselect`, instead of free text. The CI job covers the whole universe,
  so every selectable ticker has analyst and event data.
- The last selection is remembered per browser in a cookie: read with
  `st.context.cookies`, written with a small script like the existing scroll helper.
  If Streamlit Cloud's iframe blocks the cookie, fall back to a localStorage
  component. No database and no login.

## Data sources, as probed on 2 November 2026

Finnhub free tier, called with a real key against this watchlist:

| Endpoint | Free | Use |
|---|---|---|
| `calendar/earnings` | yes, at least four months ahead | event column |
| `stock/earnings` | yes | detail panel |
| `stock/profile2` | yes | detail panel |
| `stock/metric` | yes | detail panel |
| `company-news` | yes | detail panel |
| `stock/recommendation` | yes | detail panel |
| `stock/price-target` | no | stays on Yahoo |
| `stock/dividend`, `stock/dividend2` | no | stays on Yahoo |
| any `.L` symbol | no | stays on Yahoo |
| `stock/candle` | no | stays on Yahoo |

Two pitfalls found:

- The market-wide earnings calendar silently caps at 1500 rows, which a single week
  already fills. Query per symbol instead; at 60 calls a minute this is no constraint.
- The `hour` field on distant dates is unreliable: JPM, KO, JNJ and CVX all show
  `amc` although they usually report before the open. Do not display it for
  unconfirmed dates.

The key is stored as the `FINNHUB_API_KEY` repository secret for CI. It will also go
into Streamlit secrets if any of this is fetched live.

## Open question

- Size and source of the universe: a hand-maintained list, or a base such as the
  S&P 100 plus a few European names.
