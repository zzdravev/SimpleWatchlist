# Brief: re-test the signal logic on a broad universe

## Why this exists

Every threshold in this app came from one backtest over **fourteen tickers** — the list
in `DEFAULT_TICKERS` in `engine.py` — across **five years ending September 2026**. Those
fourteen are today's mega-cap winners, measured over a period in which almost everything
rose. The sample is survivorship-biased and bull-biased, and the conclusions drawn from
it are currently load-bearing:

| Finding from the narrow sample | Now baked into the app |
|---|---|
| Dip signals beat baseline: STRONG BUY +9.8% / 72.7% win over 60 days vs +5.3% / 62.1% baseline | The BUY signals exist at all |
| A dip with RSI<30 returned +12.8% over 60 days (82% win) vs +4.0% with RSI>40 | The HIGH / MEDIUM / LOW thresholds at RSI 30 and 40 |
| Forward returns after upper-band signals were +5.6%, **above** baseline | Those are labelled OVEREXTENDED, not SELL, and coloured amber |
| An SMA200 trend filter did not help: dips below SMA200 did slightly better (+8.1% vs +7.7%) | No trend filter was added |

The last one is the most suspect. "Only buy dips in an uptrend" is standard advice, and
it failed here — but on a basket where every name recovered from every dip, because the
losers are not in the basket. On a broad universe it may well hold.

**The job is to find out whether these four findings survive a harder test.**

## What to do

Read the indicator and signal code in `engine.py` first and replicate it exactly: RSI(14)
with Wilder smoothing, Bollinger(20, 2) with `ddof=0`, ATR(14) with Wilder smoothing, dip
and take-profit levels at the bands and at half an ATR beyond them. Do not re-derive or
"improve" it — the point is to test what the app actually does.

Then run it over a universe that is as broad and as long as you can get, and measure the
same things: forward returns at 20 and 60 days after each signal, win rates, counts, and
a baseline of all days for comparison.

### Questions, in priority order

1. **Do the dip signals still beat the baseline?** If the edge disappears on a broad
   universe, that is the headline and everything else is secondary.
2. **Does the RSI split still hold?** Is a dip with RSI<30 still markedly better than a
   dip with RSI>40, and are 30 and 40 roughly the right cut points, or does the data
   suggest different ones? Report the forward return by RSI decile at the moment of a
   dip, so the thresholds can be judged rather than assumed.
3. **Does the SMA200 filter help on this universe?** This is the finding most likely to
   flip. Report it split by trend, and also split by whether the stock later recovered,
   if you can.
4. **Are upper-band signals still not bearish?** If forward returns after them are now
   clearly below baseline, the OVEREXTENDED labelling needs revisiting.
5. **Is 0.5 ATR the right offset** for the STRONG tiers, or would another multiple
   separate outcomes better?

### On the data, and on being honest about it

Full survivorship-bias-free data including delisted companies is hard to obtain for free,
and you probably will not get it from Yahoo. Do not pretend otherwise.

A realistic improvement is a few hundred current constituents of a broad index over the
longest history available, which at least fixes the "fourteen mega-caps" problem and
covers 2008, 2020 and 2022 drawdowns. If you can find a free source of historical index
membership or delisted tickers, use it and say so.

**State plainly which biases remain.** A confident number from a still-biased sample is
worse than an honest "this still does not answer the survivorship question", because the
first will get acted on. If a result is weak or ambiguous, say it is weak or ambiguous.

Yahoo answers reliably from CI runners — a probe took 56/56 calls through an eight-worker
pool — so parallel downloads are fine, but batch sensibly and handle failures.

## What to produce

- `docs/backtest-broad-universe.md` — the report. Lead with a verdict on each of the five
  questions, each marked as confirming, contradicting or failing to settle the original
  finding. Then the tables. Then the method, the universe, the period, and the biases
  that remain.
- The raw per-signal results as CSV under `docs/`, so the numbers can be re-checked.
- The script that produced it, so it can be re-run.

## Constraints

- **Do not modify `app.py` or `engine.py`.** This is research. Any change to thresholds or
  logic is a separate decision for the repository owner to make after reading the report.
- Do not change the scheduled workflow or the analyst record.
- If a finding contradicts what is above, say so directly. Confirming the existing design
  is not the goal; testing it is.
