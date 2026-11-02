"""Re-test the app's signal logic on a broad universe (see docs/backtest-brief.md).

The indicators and the signal ladder below are copied from engine.py line for line
and must stay that way: the point is to test what the app does, not an improved
version of it. Nothing in engine.py or app.py is imported or changed.

Universes
    A  point-in-time S&P 500, 1996 onward. A ticker-day counts only while that
       ticker was an index member on that day (membership from the fja05680/sp500
       dataset, pinned below). Members whose price history Yahoo no longer has are
       missing; coverage is reported.
    B  today's S&P 500 constituents over the same dates, member or not: the
       survivorship-biased version of A, kept to show which way the bias pushes.
    C  the fourteen DEFAULT_TICKERS, five years to the end of September 2026: a
       replication check against the numbers the app's thresholds came from.

Usage
    python scripts/backtest_broad_universe.py            # download, analyse, write docs/
    python scripts/backtest_broad_universe.py --offline  # reuse the price cache only

Prices are cached under .cache/backtest/ (not committed). Outputs go to docs/.
"""

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CACHE = ROOT / ".cache" / "backtest"

# Point-in-time S&P 500 membership, 1996 onward. Pinned to a commit so a re-run uses
# the same list; bump it deliberately.
MEMBERSHIP_COMMIT = "a2430f2af0c79ddf0748e91de11bdeb1616ab5a7"
MEMBERSHIP_URL = ("https://raw.githubusercontent.com/fja05680/sp500/" + MEMBERSHIP_COMMIT +
                  "/S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv")

DEFAULT_TICKERS = ["NVDA", "VUAA.L", "KO", "JNJ", "O", "META", "GOOGL", "MSFT",
                   "TSLA", "AAPL", "AMZN", "JPM", "AVGO", "CVX"]

PRICE_START = "1993-01-01"      # three years of warm-up before the membership data starts
SIGNAL_START = "1996-01-02"     # first day of membership data
NARROW_START, NARROW_END = "2021-10-01", "2026-09-30"
WARMUP_BARS = 250               # the app computes on one year of daily bars
HORIZONS = (20, 60)
RECOVERY_BARS = 252
BOOT_ROUNDS = 2000
ATR_MULTIPLES = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
SIGNALS = ["STRONG BUY (Dip)", "BUY (Mod Dip)", "HOLD", "OVEREXTENDED", "VERY OVEREXTENDED"]


# --------------------------------------------------------------------------------------
# Indicators and signals: copied from engine.py. Do not "improve" these.
# --------------------------------------------------------------------------------------

def _wilder_rma(series, period):
    """Wilder's smoothed moving average - the basis of standard RSI and ATR."""
    return series.ewm(alpha=1 / period, adjust=False).mean()


def indicators(df):
    """engine.py's indicator block, kept as full series instead of the last value."""
    close = df['Close']
    high = df['High']
    low = df['Low']

    delta = close.diff()
    avg_gain = _wilder_rma(delta.clip(lower=0), 14)
    avg_loss = _wilder_rma(-delta.clip(upper=0), 14)
    rsi = 100 - (100 / (1 + avg_gain / avg_loss))

    sma20 = close.rolling(window=20).mean()
    std20 = close.rolling(window=20).std(ddof=0)
    upper_band = sma20 + (std20 * 2)
    lower_band = sma20 - (std20 * 2)

    tr = np.maximum((high - low), np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr = _wilder_rma(tr, 14)

    mod_dip = lower_band
    strong_dip = mod_dip - (0.5 * atr)
    mod_tp = upper_band
    strong_tp = mod_tp + (0.5 * atr)

    # The same if/elif ladder as engine.py, evaluated for every day at once.
    signal = np.select(
        [close <= strong_dip, close <= mod_dip, close >= strong_tp, close >= mod_tp],
        ["STRONG BUY (Dip)", "BUY (Mod Dip)", "VERY OVEREXTENDED", "OVEREXTENDED"],
        default="HOLD")

    is_buy = np.char.find(signal.astype(str), "BUY") >= 0
    conviction = np.where(~is_buy, "", np.where(rsi < 30, "HIGH", np.where(rsi < 40, "MEDIUM", "LOW")))

    out = pd.DataFrame({
        "close": close, "rsi": rsi, "atr": atr, "lower": lower_band, "upper": upper_band,
        "signal": signal, "conviction": conviction,
    }, index=df.index)
    # Research-only columns, not used by the app.
    out["sma200"] = close.rolling(window=200).mean()
    out["dist_lower_atr"] = (lower_band - close) / atr   # >0: below the lower band, in ATR
    out["dist_upper_atr"] = (close - upper_band) / atr   # >0: above the upper band, in ATR
    for h in HORIZONS:
        out[f"fwd{h}"] = close.shift(-h) / close - 1
    prior_high = close.rolling(RECOVERY_BARS, min_periods=RECOVERY_BARS).max()
    future_max = close[::-1].rolling(RECOVERY_BARS, min_periods=RECOVERY_BARS).max()[::-1].shift(-1)
    out["recovered"] = np.where(future_max.isna() | prior_high.isna(), np.nan,
                                (future_max >= prior_high).astype(float))
    out["bar"] = np.arange(len(out))
    return out


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------

def yahoo_symbol(ticker):
    return ticker.replace(".", "-")


def load_membership(offline):
    path = CACHE / "membership.csv"
    if not path.exists():
        if offline:
            sys.exit(f"--offline but {path} is missing")
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(MEMBERSHIP_URL, timeout=60) as response:
            path.write_bytes(response.read())
    raw = pd.read_csv(path)
    dates = pd.to_datetime(raw["date"]).to_numpy()
    rows = [sorted(set(str(t).strip() for t in s.split(",") if str(t).strip())) for s in raw["tickers"]]
    return dates, rows


def download_one_batch(symbols, start, end=None, threads=8):
    import yfinance as yf
    try:
        data = yf.download(symbols, start=start, end=end, interval="1d", group_by="ticker",
                           auto_adjust=True, progress=False, threads=threads)
    except Exception as e:
        print(f"batch of {len(symbols)} failed: {e}", flush=True)
        return {}
    frames = {}
    for s in symbols:
        try:
            df = data[s] if isinstance(data.columns, pd.MultiIndex) else data
            df = df[["Open", "High", "Low", "Close"]].dropna()
        except Exception:
            continue
        if len(df):
            df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
            frames[s] = df.astype("float64")
    return frames


def download(symbols, start, cache_name, offline, end=None, batch=50, passes=3):
    """Sequential batches, eight threads inside each (yfinance's own pool: concurrent
    yf.download calls share module-level state and must not overlap). Misses are
    retried in later passes; delisted symbols simply keep missing."""
    path = CACHE / f"{cache_name}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    if offline:
        sys.exit(f"--offline but {path} is missing")
    CACHE.mkdir(parents=True, exist_ok=True)
    import yfinance as yf
    yf.set_tz_cache_location(str(CACHE / "yf-tz"))
    started = time.monotonic()
    frames, missing = {}, list(symbols)
    for attempt in range(passes):
        size = batch if attempt == 0 else 10
        for i in range(0, len(missing), size):
            frames.update(download_one_batch(missing[i:i + size], start, end))
        before = len(missing)
        missing = [s for s in symbols if s not in frames]
        print(f"{cache_name}: pass {attempt + 1}: {len(frames)}/{len(symbols)} "
              f"({time.monotonic() - started:.0f}s)", flush=True)
        if not missing or len(missing) == before and attempt > 0:
            break
        time.sleep(5)
    pd.to_pickle(frames, path)
    return frames


# --------------------------------------------------------------------------------------
# Panel construction
# --------------------------------------------------------------------------------------

def membership_mask(index, ticker, pit_dates, pit_sets):
    """True on the days `ticker` was an S&P 500 member (latest change on or before)."""
    row = np.searchsorted(pit_dates, index.to_numpy(), side="right") - 1
    member = np.array([ticker in s for s in pit_sets])
    return np.where(row >= 0, member[np.clip(row, 0, None)], False)


def first_membership_start(ticker, pit_dates, pit_rows):
    for d, row in zip(pit_dates, pit_rows):
        if ticker in row:
            return pd.Timestamp(d)
    return None


def build_panel(frames, pit_dates, pit_rows, current):
    pit_sets = [set(r) for r in pit_rows]
    first_pit = pd.Timestamp(pit_dates[0])
    panels, coverage = [], []
    for ticker in sorted(set().union(*pit_sets)):
        symbol = yahoo_symbol(ticker)
        df = frames.get(symbol)
        start = first_membership_start(ticker, pit_dates, pit_rows)
        status = "ok"
        if df is None or df.empty:
            status = "no Yahoo history"
        else:
            first_bar = df.index[0]
            # A delisted company's symbol is often reused later, and Yahoo then returns
            # the new company's history under the old name. A removed member whose Yahoo
            # history starts well after it joined the index is treated as such a case.
            if ticker not in current and first_bar > max(start, first_pit) + pd.Timedelta(days=31):
                status = "excluded: history starts after membership (possible reused symbol)"
        if status != "ok":
            coverage.append({"ticker": ticker, "yahoo": symbol, "status": status,
                             "member_days": None, "covered_days": 0})
            continue
        ind = indicators(df)
        ind["in_index"] = membership_mask(ind.index, ticker, pit_dates, pit_sets)
        ind["current"] = ticker in current
        gaps = ind.index.to_series().diff().dt.days
        big_gap = gaps[ind["in_index"].to_numpy() & (gaps > 31).to_numpy()]
        if ticker not in current and len(big_gap):
            coverage.append({"ticker": ticker, "yahoo": symbol,
                             "status": "excluded: gap of more than a month while a member",
                             "member_days": None, "covered_days": 0})
            continue
        ind = ind[(ind["bar"] >= WARMUP_BARS) & (ind.index >= SIGNAL_START)]
        ind = ind[ind["in_index"] | ind["current"]]
        valid = ind[["rsi", "atr", "lower", "upper", "sma200"]].notna().all(axis=1)
        ind = ind[valid]
        ind.insert(0, "ticker", ticker)
        panels.append(ind)
        coverage.append({"ticker": ticker, "yahoo": symbol, "status": status,
                         "member_days": None, "covered_days": int(ind["in_index"].sum())})
    panel = pd.concat(panels)
    panel.index.name = "date"
    panel = panel.reset_index()
    return panel, pd.DataFrame(coverage)


def member_ticker_days(pit_dates, pit_rows, calendar):
    """Ticker-days of membership on the trading calendar: the denominator of coverage."""
    row = np.searchsorted(pit_dates, calendar.to_numpy(), side="right") - 1
    sizes = np.array([len(r) for r in pit_rows])
    return int(sizes[row[row >= 0]].sum())


def add_excess(panel, universe_mask):
    """Forward return minus the same-day mean of all days in the same universe."""
    out = {}
    for h in HORIZONS:
        col = f"fwd{h}"
        day_mean = panel.loc[universe_mask].groupby("date")[col].mean()
        out[f"xs{h}"] = panel[col] - panel["date"].map(day_mean)
    return pd.DataFrame(out, index=panel.index), day_mean


# --------------------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------------------

def episode_start(panel, flag):
    """First day of each run of `flag` per ticker: one row per dip rather than per day."""
    prev = flag.groupby(panel["ticker"]).shift(1, fill_value=False)
    return flag & ~prev


def describe(df, h):
    col, xs = f"fwd{h}", f"xs{h}"
    sub = df[df[col].notna()]
    if not len(sub):
        return {"n": 0}
    r = sub[col]
    return {
        "n": int(len(sub)), "tickers": int(sub["ticker"].nunique()),
        "mean": float(r.mean()), "median": float(r.median()), "win": float((r > 0).mean()),
        "p10": float(r.quantile(0.10)), "xs": float(sub[xs].mean()) if xs in sub else np.nan,
    }


def boot_diff(a, b, h, rounds=BOOT_ROUNDS, seed=7):
    """95% interval for mean(a) - mean(b), resampling calendar quarters.

    Signals cluster in time (a crash puts hundreds of stocks on the lower band in the
    same week) and 60-day windows overlap, so day-level standard errors would be far
    too small. Quarters are the resampling unit.
    """
    col = f"fwd{h}"
    a, b = a[a[col].notna()], b[b[col].notna()]
    if not len(a) or not len(b):
        return (np.nan, np.nan)
    qa = a.groupby(a["date"].dt.to_period("Q"))[col].agg(["sum", "count"])
    qb = b.groupby(b["date"].dt.to_period("Q"))[col].agg(["sum", "count"])
    q = qa.join(qb, how="outer", lsuffix="_a", rsuffix="_b").fillna(0.0)
    rng = np.random.default_rng(seed)
    w = rng.multinomial(len(q), np.full(len(q), 1 / len(q)), size=rounds)
    with np.errstate(invalid="ignore", divide="ignore"):
        diff = (w @ q["sum_a"].to_numpy()) / (w @ q["count_a"].to_numpy()) - \
               (w @ q["sum_b"].to_numpy()) / (w @ q["count_b"].to_numpy())
    diff = diff[np.isfinite(diff)]
    return (float(np.percentile(diff, 2.5)), float(np.percentile(diff, 97.5)))


def pct(x, signed=True):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def row_cells(label, stats_by_h, ci_by_h=None):
    cells = [label, f"{stats_by_h[60].get('n', 0):,}"]
    for h in HORIZONS:
        s = stats_by_h[h]
        if not s.get("n"):
            cells += ["n/a"] * 4
            continue
        cells += [pct(s["mean"]), pct(s["win"], signed=False), pct(s["median"]), pct(s["xs"])]
    cells.append(pct(stats_by_h[60].get("p10")) if stats_by_h[60].get("n") else "n/a")
    if ci_by_h is not None:
        lo, hi = ci_by_h
        cells.append(f"{pct(lo)} to {pct(hi)}")
    return cells


HEADER = ["Group", "Days (60d)", "Mean 20d", "Win 20d", "Median 20d", "Excess 20d",
          "Mean 60d", "Win 60d", "Median 60d", "Excess 60d", "10th pct 60d"]


def md_table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def group_table(groups, baseline, with_ci=True):
    """groups: list of (label, frame). CI is for the 60-day mean minus the baseline."""
    rows, data = [], []
    for label, frame in groups:
        stats = {h: describe(frame, h) for h in HORIZONS}
        ci = boot_diff(frame, baseline, 60) if with_ci and frame is not baseline else None
        rows.append(row_cells(label, stats, ci if with_ci else None))
        data.append({"group": label, **{f"h{h}": stats[h] for h in HORIZONS},
                     "ci60_vs_baseline": ci})
    header = HEADER + (["60d minus baseline, 95% CI"] if with_ci else [])
    if with_ci:
        for r in rows:
            if len(r) < len(header):
                r.append("—")
    return md_table(header, rows), data


# --------------------------------------------------------------------------------------
# Report sections
# --------------------------------------------------------------------------------------

def analyse(u, name):
    """All tables for one universe. `u` holds that universe's rows only."""
    out, data = [], {}
    is_dip = u["signal"].isin(["STRONG BUY (Dip)", "BUY (Mod Dip)"])
    is_up = u["signal"].isin(["OVEREXTENDED", "VERY OVEREXTENDED"])
    dip, up = u[is_dip], u[is_up]

    # Q1: signals against the baseline.
    groups = [("Baseline: all days", u)] + [(s, u[u["signal"] == s]) for s in SIGNALS]
    groups.insert(3, ("Any dip (STRONG BUY or BUY)", dip))
    t, data["signals"] = group_table(groups, u)
    out += [f"### {name}: signals against the baseline (all signal days)", "", t, ""]

    first = u[episode_start(u, is_dip)]
    first_up = u[episode_start(u, is_up)]
    groups = [("Baseline: all days", u), ("Dip, first day of each episode", first),
              ("Upper band, first day of each episode", first_up)]
    t, data["episodes"] = group_table(groups, u)
    out += [f"### {name}: first day of each signal episode only", "", t, ""]

    # Q1 by period.
    rows = []
    period = u["date"].dt.year
    for year, frame in u.groupby(period):
        d = frame[frame["signal"].isin(["STRONG BUY (Dip)", "BUY (Mod Dip)"])]
        sb = frame[frame["signal"] == "STRONG BUY (Dip)"]
        b, dd, s = describe(frame, 60), describe(d, 60), describe(sb, 60)
        if not b.get("n"):
            continue
        rows.append([year, pct(b["mean"]), f"{dd.get('n', 0):,}",
                     pct(dd.get("mean")) if dd.get("n") else "n/a",
                     pct(dd["mean"] - b["mean"]) if dd.get("n") else "n/a",
                     pct(dd.get("xs")) if dd.get("n") else "n/a",
                     pct(s.get("mean")) if s.get("n") else "n/a",
                     pct(s["mean"] - b["mean"]) if s.get("n") else "n/a"])
    out += [f"### {name}: dips by year of the signal (60-day forward returns)", "",
            md_table(["Year", "Baseline mean", "Dip days", "Dip mean", "Dip minus baseline",
                      "Dip excess vs same day", "STRONG BUY mean", "STRONG BUY minus baseline"], rows), ""]
    data["by_year"] = rows

    # Q2: RSI at the moment of a dip.
    groups = [("Baseline: all days", u), ("Dip, conviction HIGH (RSI<30)", dip[dip["conviction"] == "HIGH"]),
              ("Dip, conviction MEDIUM (30-40)", dip[dip["conviction"] == "MEDIUM"]),
              ("Dip, conviction LOW (RSI>=40)", dip[dip["conviction"] == "LOW"])]
    t, data["conviction"] = group_table(groups, u)
    hi, lo = dip[dip["conviction"] == "HIGH"], dip[dip["conviction"] == "LOW"]
    ci = boot_diff(hi, lo, 60)
    data["high_minus_low_ci60"] = ci
    out += [f"### {name}: dips by conviction (RSI at the signal)", "", t, "",
            f"HIGH minus LOW, 60-day mean: {pct(describe(hi, 60).get('mean', np.nan) - describe(lo, 60).get('mean', np.nan))}, "
            f"95% CI {pct(ci[0])} to {pct(ci[1])}.", ""]

    deciles = pd.qcut(dip["rsi"], 10, duplicates="drop")
    groups = [(f"RSI {iv.left:.1f}-{iv.right:.1f}", frame) for iv, frame in dip.groupby(deciles, observed=True)]
    t, data["rsi_deciles"] = group_table(groups, u)
    out += [f"### {name}: dips by RSI decile at the signal", "", t, ""]

    edges = [0, 20, 25, 30, 35, 40, 45, 50, 100]
    buckets = pd.cut(dip["rsi"], edges, right=False)
    groups = [(f"RSI {iv.left:.0f}-{iv.right:.0f}", frame) for iv, frame in dip.groupby(buckets, observed=True)]
    t, data["rsi_buckets"] = group_table(groups, u)
    out += [f"### {name}: dips by fixed RSI bucket", "", t, ""]

    # Q3: trend filter.
    above = dip[dip["close"] > dip["sma200"]]
    below = dip[dip["close"] <= dip["sma200"]]
    groups = [("Baseline: all days", u), ("Dip above SMA200", above), ("Dip below SMA200", below),
              ("STRONG BUY above SMA200", above[above["signal"] == "STRONG BUY (Dip)"]),
              ("STRONG BUY below SMA200", below[below["signal"] == "STRONG BUY (Dip)"]),
              ("HIGH conviction above SMA200", above[above["conviction"] == "HIGH"]),
              ("HIGH conviction below SMA200", below[below["conviction"] == "HIGH"])]
    t, data["trend"] = group_table(groups, u)
    ci = boot_diff(above, below, 60)
    data["above_minus_below_ci60"] = ci
    out += [f"### {name}: dips split by the SMA200 trend", "", t, "",
            f"Above minus below, 60-day mean: {pct(describe(above, 60).get('mean', np.nan) - describe(below, 60).get('mean', np.nan))}, "
            f"95% CI {pct(ci[0])} to {pct(ci[1])}.", ""]

    rows = []
    for label, frame in [("above SMA200", above), ("below SMA200", below)]:
        known = frame[frame["recovered"].notna()]
        share = known["recovered"].mean() if len(known) else np.nan
        for rec_label, rec in [("recovered", 1.0), ("did not recover", 0.0)]:
            part = known[known["recovered"] == rec]
            s = describe(part, 60)
            rows.append([f"Dip {label}, {rec_label}", f"{s.get('n', 0):,}",
                         pct(len(part) / len(known), signed=False) if len(known) else "n/a",
                         pct(s.get("mean")) if s.get("n") else "n/a",
                         pct(s.get("win"), signed=False) if s.get("n") else "n/a"])
        rows.append([f"Dip {label}: share that recovered", f"{len(known):,}", pct(share, signed=False), "", ""])
    out += [f"### {name}: dips by trend and by whether the stock later recovered", "",
            "Recovered = the close regained its prior 52-week high within the next 252 trading days. "
            "This uses the future and cannot be traded on; it shows how much of each result depends on "
            "the stock coming back.", "",
            md_table(["Group", "Days", "Share of group", "Mean 60d", "Win 60d"], rows), ""]
    data["recovery"] = rows

    # Q4: upper band.
    groups = [("Baseline: all days", u), ("OVEREXTENDED", u[u["signal"] == "OVEREXTENDED"]),
              ("VERY OVEREXTENDED", u[u["signal"] == "VERY OVEREXTENDED"]),
              ("Upper band, RSI>70", up[up["rsi"] > 70]),
              ("Upper band above SMA200", up[up["close"] > up["sma200"]]),
              ("Upper band below SMA200", up[up["close"] <= up["sma200"]])]
    t, data["upper"] = group_table(groups, u)
    out += [f"### {name}: upper-band signals", "", t, ""]

    # Q5: ATR offset.
    groups = [("Baseline: all days", u)]
    for lo_k, hi_k in zip(ATR_MULTIPLES, list(ATR_MULTIPLES[1:]) + [np.inf]):
        part = dip[(dip["dist_lower_atr"] >= lo_k) & (dip["dist_lower_atr"] < hi_k)]
        groups.append((f"{lo_k:g} to {hi_k:g} ATR below the lower band", part))
    t, data["atr_bins"] = group_table(groups, u)
    out += [f"### {name}: dips by distance below the lower band", "",
            "STRONG BUY is 0.5 ATR or more below the band. Each row is one slice of distance.", "", t, ""]

    rows = []
    for k in ATR_MULTIPLES[1:]:
        deep = dip[dip["dist_lower_atr"] >= k]
        shallow = dip[dip["dist_lower_atr"] < k]
        sd, ss = describe(deep, 60), describe(shallow, 60)
        ci = boot_diff(deep, shallow, 60)
        rows.append([f"{k:g} ATR", f"{sd.get('n', 0):,}", pct(sd.get("mean")), pct(sd.get("win"), False),
                     f"{ss.get('n', 0):,}", pct(ss.get("mean")), pct(ss.get("win"), False),
                     pct(sd.get("mean", np.nan) - ss.get("mean", np.nan)), f"{pct(ci[0])} to {pct(ci[1])}"])
    out += [f"### {name}: where to put the STRONG cut on the dip side", "",
            "Each row splits all dips at k ATR below the band and compares the two sides over 60 days.", "",
            md_table(["Cut k", "Days at or beyond k", "Mean 60d", "Win 60d", "Days short of k", "Mean 60d",
                      "Win 60d", "Beyond minus short", "95% CI"], rows), ""]
    data["atr_cuts_dip"] = rows

    rows = []
    for k in ATR_MULTIPLES[1:]:
        far = up[up["dist_upper_atr"] >= k]
        near = up[up["dist_upper_atr"] < k]
        sf, sn = describe(far, 60), describe(near, 60)
        rows.append([f"{k:g} ATR", f"{sf.get('n', 0):,}", pct(sf.get("mean")), pct(sf.get("win"), False),
                     f"{sn.get('n', 0):,}", pct(sn.get("mean")), pct(sn.get("win"), False),
                     pct(sf.get("mean", np.nan) - sn.get("mean", np.nan))])
    out += [f"### {name}: the same split on the upper side", "",
            md_table(["Cut k", "Days at or beyond k", "Mean 60d", "Win 60d", "Days short of k", "Mean 60d",
                      "Win 60d", "Beyond minus short"], rows), ""]
    data["atr_cuts_upper"] = rows
    return out, data


# --------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="use the cache only, no network")
    args = parser.parse_args()
    run_started = datetime.now(timezone.utc)

    pit_dates, pit_rows = load_membership(args.offline)
    current = set(pit_rows[-1])
    all_members = sorted(set().union(*map(set, pit_rows)))
    print(f"membership: {len(pit_rows)} change dates, {len(all_members)} tickers ever, "
          f"{len(current)} current", flush=True)

    frames = download([yahoo_symbol(t) for t in all_members], PRICE_START, "sp500", args.offline)
    narrow_frames = download(DEFAULT_TICKERS, "2020-01-01", "narrow", args.offline,
                             end="2026-10-01")

    panel, coverage = build_panel(frames, pit_dates, pit_rows, current)
    last_fwd = panel.loc[panel["fwd60"].notna(), "date"].max()
    calendar = pd.DatetimeIndex(sorted(panel.loc[panel["date"] <= last_fwd, "date"].unique()))
    possible = member_ticker_days(pit_dates, pit_rows, calendar)
    covered = int(((panel["in_index"]) & (panel["date"] <= last_fwd)).sum())

    sections, results = [], {}
    universes = {"A": panel["in_index"].to_numpy(), "B": panel["current"].to_numpy()}
    excess = {}
    for key, mask in universes.items():
        xs, day_mean = add_excess(panel, mask)
        excess[key] = xs
        u = pd.concat([panel.loc[mask], xs.loc[mask]], axis=1)
        title = {"A": "A. Point-in-time S&P 500, 1996-2026",
                 "B": "B. Today's constituents only, same dates (survivorship-biased)"}[key]
        out, data = analyse(u, title)
        sections += [f"## {title}", ""] + out
        results[key] = data

    # C: the original fourteen, five years to September 2026, for replication.
    narrow = []
    for symbol, df in narrow_frames.items():
        ind = indicators(df)
        ind = ind[(ind["bar"] >= WARMUP_BARS) & (ind.index >= NARROW_START) & (ind.index <= NARROW_END)]
        ind = ind[ind[["rsi", "atr", "lower", "upper", "sma200"]].notna().all(axis=1)]
        ind.insert(0, "ticker", symbol)
        narrow.append(ind)
    narrow = pd.concat(narrow)
    narrow.index.name = "date"
    narrow = narrow.reset_index()
    xs, _ = add_excess(narrow, np.ones(len(narrow), dtype=bool))
    narrow = pd.concat([narrow, xs], axis=1)
    out, data = analyse(narrow, "C. The fourteen DEFAULT_TICKERS, Oct 2021 - Sep 2026")
    sections = ["## C. Replication: the fourteen DEFAULT_TICKERS, Oct 2021 - Sep 2026", ""] + out + sections
    results["C"] = data

    # ---- outputs
    DOCS.mkdir(exist_ok=True)
    # One row per non-HOLD signal day. The band levels are left out because they follow
    # from close, atr and the two distances; gzip keeps the file under GitHub's limits.
    signal_cols = ["date", "ticker", "signal", "conviction", "close", "rsi", "atr", "sma200",
                   "dist_lower_atr", "dist_upper_atr", "fwd20", "fwd60", "recovered",
                   "in_index", "current"]
    sig = panel[panel["signal"] != "HOLD"][signal_cols].copy()
    for key in ("A", "B"):
        for h in HORIZONS:
            sig[f"xs{h}_{key}"] = excess[key].loc[sig.index, f"xs{h}"]
    sig["date"] = sig["date"].dt.strftime("%Y-%m-%d")
    sig[["in_index", "current"]] = sig[["in_index", "current"]].astype(int)
    sig.to_csv(DOCS / "backtest-broad-universe-signals.csv.gz", index=False, float_format="%.4g",
               compression={"method": "gzip", "mtime": 0})

    base = []
    for key, mask in universes.items():
        g = panel.loc[mask].groupby("date")
        b = pd.DataFrame({"universe": key, "days": g.size(), "mean_fwd20": g["fwd20"].mean(),
                          "mean_fwd60": g["fwd60"].mean()})
        base.append(b)
    base = pd.concat(base).reset_index()
    base["date"] = base["date"].dt.strftime("%Y-%m-%d")
    base.to_csv(DOCS / "backtest-broad-universe-baseline-by-day.csv", index=False, float_format="%.5g")

    narrow_out = narrow[narrow["signal"] != "HOLD"][[c for c in signal_cols if c in narrow] + ["xs20", "xs60"]].copy()
    narrow_out["date"] = narrow_out["date"].dt.strftime("%Y-%m-%d")
    narrow_out.drop(columns=[c for c in ("in_index", "current") if c in narrow_out]).to_csv(
        DOCS / "backtest-narrow-replication-signals.csv", index=False, float_format="%.5g")

    coverage.to_csv(DOCS / "backtest-broad-universe-coverage.csv", index=False)

    import yfinance
    status_counts = coverage["status"].value_counts().to_dict()
    meta = {
        "run_utc": run_started.isoformat(timespec="seconds"),
        "membership_source": MEMBERSHIP_URL,
        "membership_last_change": str(pd.Timestamp(pit_dates[-1]).date()),
        "tickers_ever": len(all_members), "tickers_current": len(current),
        "ticker_status": status_counts,
        "signal_dates": [str(panel["date"].min().date()), str(last_fwd.date())],
        "member_ticker_days_possible": possible, "member_ticker_days_covered": covered,
        "coverage_share": covered / possible if possible else None,
        "universe_A_days": int(universes["A"].sum()), "universe_B_days": int(universes["B"].sum()),
        "narrow_tickers": sorted(narrow_frames), "versions": {
            "python": sys.version.split()[0], "pandas": pd.__version__, "numpy": np.__version__,
            "yfinance": yfinance.__version__},
    }
    head = [
        "# Broad-universe backtest: generated tables", "",
        "Generated by `scripts/backtest_broad_universe.py`; do not edit by hand. The written report "
        "with verdicts is `docs/backtest-broad-universe.md`.", "",
        "Returns are close to close over 20 and 60 trading days after the signal day. "
        "Win = share of days with a positive forward return. Excess = forward return minus the "
        "same-day mean of the whole universe, which removes the market's move. "
        "95% intervals come from a bootstrap over calendar quarters.", "",
        "```json", json.dumps(meta, indent=2), "```", "",
    ]
    (DOCS / "backtest-broad-universe-tables.md").write_text("\n".join(head + sections) + "\n", encoding="utf-8")
    (DOCS / "backtest-broad-universe-results.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=1, default=str), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
