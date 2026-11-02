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

Two layers: a shared universe that the owner maintains, and per-user extras.

**Universe (shared).** The S&P 100 plus a few hand-picked tickers (the list is still
to come) in `data/universe.csv`: ticker, name, sector. Users pick from it with
`st.multiselect` instead of typing free text. The CI job covers the whole universe,
so every ticker in it has analyst and event data.

**Editing the universe from the app.** Streamlit Cloud's filesystem resets on every
restart, so the app cannot save the list locally. Instead:

- A small admin panel, locked by a password from `st.secrets`, adds or removes
  tickers.
- A change is committed to `data/universe.csv` through the GitHub API, using a
  fine-grained token limited to this repository with Contents write access.
- The analyst-record workflow gains `data/universe.csv` in its `push.paths`, so the
  commit itself starts collection and a new ticker has data within a couple of
  minutes. The app's commit must not carry `[skip ci]`. The push also redeploys the
  app.
- Input is validated as a ticker symbol before anything is written.

**Extras (per user).** Anyone can add tickers outside the universe. They are stored
in that user's cookie and are not shared.

- Prices and signals work for any symbol, since the price history endpoint answers
  Streamlit Cloud.
- Earnings dates come live from Finnhub, for US symbols only.
- Analyst targets and ex-dividend dates are unavailable, because Yahoo refuses the
  quote endpoint from Streamlit Cloud. Such rows are marked as limited data rather
  than showing blanks that look like errors.

**Remembering the choice.** The selection and the extras are saved per browser in a
cookie: read with `st.context.cookies`, written with a small script like the
existing scroll helper. If Streamlit Cloud's iframe blocks the cookie, fall back to a
localStorage component. No database and no user login.

**Secrets this needs on Streamlit Cloud:** `FINNHUB_API_KEY`, `ADMIN_PASSWORD`, and
`GITHUB_TOKEN` (the fine-grained token above).

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

## Waiting on

- The extra tickers to add to the S&P 100 for the initial universe.
