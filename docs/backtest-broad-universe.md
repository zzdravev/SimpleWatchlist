# Signal logic on a broad universe: results

Answer to `docs/backtest-brief.md`. The app's code was not changed. The full generated
tables are in `docs/backtest-broad-universe-tables.md`, and the script is
`scripts/backtest_broad_universe.py`.

The per-signal rows (`backtest-broad-universe-signals.csv.gz`, about 20 MB) are too large
to keep in the repository. Each workflow run attaches them as the artifact
`backtest-broad-universe-signals` for 90 days, and running the script locally writes them
to `docs/`, which git ignores. The smaller CSVs (baseline by day, coverage per ticker, the
replication signals) are committed.

## Verdicts

The broad test covers point-in-time S&P 500 members, 1996 to August 2026: 759 tickers,
2.58 million member-days and 135,000 dip days. Before the broad test, the method was
checked on the original fourteen tickers over the original five years. It reproduces the
original numbers closely (see [Replication](#replication)), so any difference below comes
from the universe, not from the method.

| # | Question | Verdict | In one line |
|---|---|---|---|
| 1 | Do dip signals beat the baseline? | **Confirms the direction, contradicts the size** | Raw edge survives at about a third of its narrow-sample size. Nearly all of it comes from *when* dips happen, not *which* stock dips. |
| 2 | Does the RSI split hold? | **Confirms the direction, contradicts the size; 30/40 not supported as natural cuts** | Lower RSI is better in raw terms, as a smooth slope with no break at 30. The whole slope disappears once volatility is matched. |
| 3 | Does an SMA200 filter help? | **Fails to settle** | Raw mean: no, dips below SMA200 still did better, as in the narrow sample. Volatility-matched and tail risk: leans toward the filter, but not significantly. The remaining survivorship bias hits this question hardest. |
| 4 | Are upper-band signals not bearish? | **Contradicts "above baseline"; supports "not a sell"** | Returns after upper-band signals are now reliably *below* baseline, but still positive. |
| 5 | Is 0.5 ATR the right offset? | **Contradicts the idea that the STRONG tier separates outcomes** | No multiple from 0.25 to 1.5 ATR separates outcomes once volatility is matched. 0.5 is as good as any and no better than none. |

### 1. Do the dip signals still beat the baseline?

Over 60 days, compared with the average of all member-days:

| | Narrow sample (orig.) | Broad, point-in-time |
|---|---|---|
| Baseline, all days | +5.3%, 62.1% win | +3.2%, 59.9% win |
| STRONG BUY | +9.8%, 72.7% win | +4.8%, 63.0% win |
| STRONG BUY minus baseline | +4.5 pts | **+1.6 pts** (95% CI +0.8 to +2.6) |
| Any dip minus baseline | — | **+1.2 pts** (+0.7 to +1.8) |

The raw edge is real in this sample. It was positive in 28 of 31 calendar years (not in
1999, 2007 or 2017), and the intervals exclude zero. But it is roughly a third of what the
narrow sample showed, and two checks shrink it much further.

- **Remove the same-day market move.** Compare each dip with the average stock *on the
  same day*. The edge falls to +0.3 pts for any dip (CI 0.0 to +0.6) and +0.4 pts for STRONG
  BUY (−0.1 to +0.9). Dips cluster in sell-offs: 5% of trading days hold a third of all dip
  days. From those days, the *whole universe* returned +6.0% over the next 60 days, against
  +3.2% on an average day. Buying on a dip day mostly means buying when everything is cheap.
- **Also match volatility.** Compare each dip with stocks of the same volatility quintile
  on the same day. The edge is +0.1 pts for any dip (−0.1 to +0.4) and +0.1 pts for STRONG
  BUY (−0.3 to +0.6), indistinguishable from zero. Per ticker it is a coin flip: the
  volatility-matched dip excess was positive for 50.1% of the 591 tickers with at least 20
  dip days.
- The stock-relative edge was not stable over time either. It was positive in most years
  from 1996 to 2010 (13 of 15), around zero from 2011 to 2020 (negative in six of ten
  years), and mixed since.

**What this means.** For someone who buys only on signal days, the raw comparison is the
relevant one, and it still favours buying on dips, by a smaller margin. What the signal does
not do is pick stocks: on a dip day, buying an index fund would have captured about the same
return. The "BUY" signal is a market-timing signal dressed as a stock signal.

### 2. Does the RSI split still hold?

| Dip, 60 days | Narrow (orig.) | Broad | Broad, vol-matched excess |
|---|---|---|---|
| HIGH (RSI < 30) | +12.8%, 82% win | +5.6%, 63.6% win | +0.0% (−0.5 to +0.6) |
| MEDIUM (30–40) | — | +4.1%, 61.7% win | +0.2% (−0.1 to +0.4) |
| LOW (RSI ≥ 40) | +4.0% | +3.3%, 60.5% win | +0.2% (−0.1 to +0.5) |
| HIGH minus LOW | +8.8 pts | **+2.3 pts** (+0.6 to +4.2) | **−0.2 pts** (−0.8 to +0.4) |

RSI deciles at the moment of a dip, raw 60-day mean (full table in the generated file):

| RSI decile | < 24.8 | 24.8–28.2 | 28.2–30.5 | 30.5–32.3 | 32.3–34.0 | 34.0–35.5 | 35.5–37.1 | 37.1–38.9 | 38.9–41.2 | > 41.2 |
|---|---|---|---|---|---|---|---|---|---|---|
| Mean 60d | +6.8% | +4.9% | +4.8% | +4.8% | +4.4% | +4.0% | +3.8% | +3.7% | +3.4% | +3.2% |
| Minus baseline | +3.6 | +1.8 | +1.6 | +1.6 | +1.2 | +0.8 | +0.7 | +0.6 | +0.2 | +0.0 |

- In raw returns the direction holds: lower RSI, better return. The step from HIGH to LOW is
  about a quarter of the narrow sample's.
- **30 is not a natural cut.** Returns fall smoothly through the 25–35 range. Only the
  lowest decile (RSI below about 25) stands out, and that is where the deepest sell-offs are.
- **40 is roughly where the raw edge ends.** Dips above RSI 39–41 return the same as an
  average day. So a LOW-conviction dip is, in raw terms, no better than not having a signal.
- **The slope is volatility, not RSI.** In volatility-matched excess, every decile sits
  between −0.1 and +0.5 pts and HIGH minus LOW is −0.2 pts. A low RSI at a dip marks a
  volatile stock in a falling market, and that is what the extra raw return pays for. The
  lowest RSI buckets also have the worst tails: the 10th percentile of 60-day returns is
  −20.4% for RSI below 20, against −14.4% for the baseline.

### 3. Does the SMA200 filter help on this universe?

| Dip, 60 days | Narrow (orig.) | Broad | Broad, 10th pct | Broad, vol-matched excess |
|---|---|---|---|---|
| Above SMA200 | +7.7% | +3.6%, 62.1% win | −12.6% | **+0.3%** (+0.1 to +0.6) |
| Below SMA200 | +8.1% | +4.9%, 62.0% win | −17.1% | **−0.0%** (−0.4 to +0.4) |
| Above minus below | −0.4 pts | −1.3 pts (−3.1 to +0.4) | | +0.4 pts (−0.2 to +0.9) |

By whether the stock later recovered (regained its prior 52-week high within a year; this
uses the future and is descriptive only):

| Dip | Share that recovered | Mean 60d if recovered | Mean 60d if not |
|---|---|---|---|
| Above SMA200 | 77.7% | +7.0% | −8.7% |
| Below SMA200 | **40.6%** (narrow sample: 50.3%) | +12.8% | −0.5% |

- **Raw mean: the finding did not flip.** Dips below SMA200 still did better on average, by
  more than in the narrow sample.
- **But they are a different bet.** Their left tail is much fatter (10th percentile −17.1%
  against −12.6%). Fewer than half recovered within a year, against 78% of dips above the
  trend. Their extra raw return goes away once volatility is matched. Dips *above* SMA200 are
  the only dip group whose volatility-matched excess clears zero, and only just.
- **Why this does not settle it.** The test is still missing a third of member-days (see
  [Biases](#biases-that-remain)). That missing part includes the companies that failed or
  were bought cheaply after long declines. Those are exactly the below-SMA200 dips that never
  recovered. Every missing loser would lower the below-SMA200 row more than any other row in
  this report. The raw "no filter needed" conclusion is the one most likely to be
  overstated. A volatility-matched lean of +0.4 pts in favour of the filter, with a CI
  crossing zero, is too weak to act on.

### 4. Are upper-band signals still not bearish?

| 60 days | Narrow (orig.) | Broad | Minus baseline | Vol-matched excess |
|---|---|---|---|---|
| OVEREXTENDED | above baseline | +2.2%, 58.2% win | **−0.9 pts** (−1.4 to −0.5) | −0.2% (−0.4 to −0.1) |
| VERY OVEREXTENDED | +5.6% | +2.2%, 57.9% win | **−1.0 pts** (−1.6 to −0.4) | −0.2% (−0.5 to +0.1) |
| Upper band, below SMA200 | — | +1.7%, 54.7% win | −1.4 pts (−2.6 to −0.3) | −0.9% (−1.4 to −0.4) |

- The narrow-sample finding that forward returns after upper-band signals beat the
  baseline does not survive. On the broad universe they are reliably below it, in raw terms
  and after removing the market.
- They are still not bearish in absolute terms. Holding after an upper-band signal returned
  +2.2% over 60 days, with a win rate near 58%. "Don't add here" fits the data. "Exit" does
  not.
- The amber OVEREXTENDED labelling survives. The justification in the `engine.py` comment
  ("forward returns after those signals match or beat the baseline") no longer holds.
- The weakest case is a rally to the upper band in a stock below its SMA200. It is the
  most clearly negative upper-band group after volatility matching (−0.9 pts).

### 5. Is 0.5 ATR the right offset?

All dips, split at k ATR below the lower band, 60 days:

| Cut k | Beyond k | Short of k | Raw difference (95% CI) | Vol-matched difference (95% CI) |
|---|---|---|---|---|
| 0.25 | +4.6% | +4.1% | +0.5 (−0.1 to +1.2) | +0.0 (−0.2 to +0.3) |
| **0.5 (current)** | +4.8% | +4.2% | +0.6 (−0.2 to +1.5) | +0.0 (−0.4 to +0.4) |
| 0.75 | +5.0% | +4.2% | +0.8 (−0.3 to +2.1) | −0.1 (−0.6 to +0.5) |
| 1.0 | +5.1% | +4.3% | +0.8 (−0.7 to +2.5) | −0.1 (−0.9 to +0.9) |
| 1.5 | +5.7% | +4.3% | +1.3 (−1.0 to +4.3) | +0.3 (−1.6 to +2.9) |
| 2.0 | +8.3% | +4.3% | +3.9 (−0.4 to +11.6) | +2.8 (−1.5 to +10.3) |

- No cut from 0.25 to 1.5 ATR separates outcomes. Raw differences are under a point with
  intervals spanning zero, and volatility-matched differences are zero.
- Beyond 2 ATR (852 days, a handful of crash episodes) the raw number jumps, but the
  interval runs from about zero to +12 pts. That is a few events, not a tier.
- In the narrow sample the 0.5 cut looked like it mattered: +3.7 pts raw, CI 0.0 to +7.5.
  Even there, the volatility-matched difference was −0.1 pts.
- On the upper side, VERY OVEREXTENDED and OVEREXTENDED have the same forward returns (+2.2%
  each), so the offset does not separate anything there either.

## Replication

The method run on the original fourteen tickers, October 2021 to September 2026
(signal-day closes, 60-day forward returns):

| | Original backtest | This script |
|---|---|---|
| Baseline | +5.3%, 62.1% win | +5.3%, 62.0% win |
| STRONG BUY | +9.8%, 72.7% win | +10.2%, 74.7% win |
| Dip with RSI < 30 | +12.8%, 82% win | +12.1%, 80.9% win |
| Dip with RSI > 40 | +4.0% | +2.7% |
| Upper band (VERY OVEREXTENDED) | +5.6% | +5.6% |
| Dip below / above SMA200 | +8.1% / +7.7% | +8.4% / +6.2% |

The small differences come from data revisions and the exact window edges. Separately, the
indicator code was checked against `engine.get_financial_data()` on synthetic prices: the
same signal and conviction on 300 of 300 randomly chosen days.

Even on the narrow sample, the volatility-matched excess of STRONG BUY is only +0.4 pts,
with a CI from −1.5 to +2.3. The large raw numbers the thresholds came from were mostly
market and volatility timing all along. The narrow sample did not have enough independent
episodes to show it.

## Method

- **Indicators and signals** are copied line for line from `engine.py`: RSI(14) and ATR(14)
  with Wilder smoothing (`ewm(alpha=1/14, adjust=False)`), Bollinger(20, 2) with `ddof=0`,
  dip and take-profit levels at the bands and half an ATR beyond them, the same if/elif
  ladder, and conviction at RSI 30 and 40. They are computed on each ticker's full history
  instead of a one-year window. After the 250-bar warm-up the two agree (checked above).
  SMA200, distances in ATR and the recovery flag are added for analysis only.
- **Prices**: Yahoo daily bars, `auto_adjust=True` as in the app, from 1993 so that 1996
  starts warm. They were downloaded on a GitHub Actions runner, because this repository's
  development container cannot reach Yahoo. The workflow is
  `.github/workflows/backtest-broad-universe.yml`.
- **Signals**: evaluated at each day's close. Forward returns run close to close over 20 and
  60 trading days. Win means a positive forward return. No costs, no slippage.
- **Universe A (headline)**: a ticker-day counts only while that ticker was an S&P 500
  member on that day. Membership comes from the point-in-time file in
  [fja05680/sp500](https://github.com/fja05680/sp500) (MIT licence, pinned to commit
  `a2430f2`, last change 2026-08-18). Forward returns follow the stock after it leaves the
  index, as a holder would.
- **Universe B**: today's 503 constituents over the same dates, member or not. This is the
  survivorship-biased version, kept for comparison; its tables are in the generated file.
  Its baseline is a full point higher (+4.2% against +3.2% over 60 days). The dip-minus-
  baseline spreads are about the same (+1.3 against +1.2 pts).
- **Baseline**: all universe days with valid indicators, equally weighted. **Excess**: minus
  the same-day universe mean. **Vol-matched excess**: minus the same-day mean of stocks in
  the same quintile of ATR/close.
- **Uncertainty**: dip days are heavily clustered in time and 60-day windows overlap, so
  day-level standard errors would be far too narrow. All intervals are 95% bootstrap
  intervals that resample whole calendar quarters (about 120). They are still approximate.
  Many comparisons were made, so treat a single interval that barely excludes zero with
  caution.
- **Period**: signal dates 1996-01-02 to 2026-08-07, the last date with 60 days of future
  data. This covers 2000–02, 2008–09, 2020 and 2022.

## Biases that remain

This test is much harder than the narrow one, but it does **not** answer the survivorship
question. Read every number above with these in mind.

1. **A third of the index is missing.** Of 1,209 tickers that were ever members, Yahoo had
   no usable history for 450. The covered member-days are 67% of all member-days. The
   missing names are not all failures. They mix:
   - bankruptcies and distressed sales (the cases that matter most for dips);
   - takeovers, often at a premium;
   - ticker changes, which Yahoo files under the new symbol only. Meta's 2013–2022 days
     under `FB` are missing, for example.

   There is no way to tell from this data which of these dominates. As argued under
   question 3, the missing failures would hurt the below-SMA200 and low-RSI rows most.
2. **Symbol reuse.** The membership file names tickers as of each day, and Yahoo returns
   the current holder of a symbol. Where a symbol passed to a company with a longer history
   (for example `T`, old AT&T to SBC in 2005), the early days carry the wrong company's
   prices. 128 former members whose Yahoo history starts well after they joined are
   flagged; only 9 of them contribute any days. Leaving those out changes no headline number by more than 0.1 pt; that table is
   in the generated file.
3. **Membership data quality.** The file's author notes that the 1996–2000 rows may miss a
   few symbols, and that post-2019 changes are reconstructed from Wikipedia.
4. **US large caps only.** S&P 500 members are pre-filtered by size and profitability. The
   app's own list includes a London-listed ETF (`VUAA.L`) and a REIT (`O`). Small caps,
   other markets and ETFs are not tested.
5. **Simplifications.** Close-to-close returns, no costs, equal weights, and no position
   sizing or DCA cash-flow model. The test measures the signal, not the strategy built on it.

## What to make of it

The app's code was not changed; these are points for the owner to decide on. The narrow
backtest's numbers, which still appear in the `engine.py` comments, overstate every edge
by a factor of two to four. The broad data support a weaker reading: a dip signal is a
reasonable "the market is on sale today" flag. It is not evidence that the particular stock
is a better buy than any other stock that day. RSI conviction and the STRONG tier add
nothing beyond that once volatility is accounted for. Upper-band signals mean "below-average
return ahead", not "above". Whether an SMA200 filter helps remains open, and it is the
question that survivorship-free data, such as a paid dataset with delisted companies,
would most likely change.
