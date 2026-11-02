import csv
import json
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import date, datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Cache lifetime in seconds (300 seconds = 5 minutes)
CACHE_EXPIRY_SECONDS = 300
_data_cache = {}

DEFAULT_TICKERS = ["NVDA", "VUAA.L", "KO", "JNJ", "O", "META", "GOOGL", "MSFT",
                   "TSLA", "AAPL", "AMZN", "JPM", "AVGO", "CVX"]

# Written daily by .github/workflows/analyst-record.yml. Yahoo refuses the
# authenticated quote endpoint from Streamlit Cloud but answers it from CI, so the
# slow-moving analyst figures are collected there and read back from disk here.
RECORD_PATH = Path(__file__).with_name("data") / "analyst_record.json"

# The tickers users pick from, and the ones the daily record job covers.
UNIVERSE_PATH = Path(__file__).with_name("data") / "universe.csv"


def load_universe():
    """Rows of data/universe.csv as dicts (ticker, name, sector, group), or [] if absent."""
    try:
        with open(UNIVERSE_PATH, encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def load_analyst_record():
    try:
        with open(RECORD_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


EVENT_LABELS = {"earnings": "Earnings", "ex_dividend": "Ex-div"}


def market_today():
    """Today's date where the US market is, which is what event countdowns refer to."""
    return datetime.now(ZoneInfo("America/New_York")).date()


def next_event(entry, today):
    """Label for the nearest upcoming earnings or ex-dividend date, e.g. "Earnings · ~9d".

    A tilde marks an earnings date the company has not confirmed. Days are calendar
    days, counted at render time from the stored date, so a record that is a day old
    still counts down correctly. "-" when nothing is known within the horizon.
    """
    candidates = []
    for kind in EVENT_LABELS:
        event = (entry or {}).get(kind)
        try:
            days = (date.fromisoformat(event["date"]) - today).days
        except (TypeError, KeyError, ValueError):
            continue
        if days >= 0:
            candidates.append((days, kind, event))
    if not candidates:
        return "-"
    days, kind, event = min(candidates, key=lambda c: c[0])
    when = "today" if days == 0 else f"{days}d"
    if kind == "earnings" and not event.get("confirmed"):
        when = "~" + when
    return f"{EVENT_LABELS[kind]} · {when}"


def _wilder_rma(series, period):
    """Wilder's smoothed moving average - the basis of standard RSI and ATR."""
    return series.ewm(alpha=1 / period, adjust=False).mean()


def _num(info, key):
    """Read a numeric field from yfinance .info, which may be absent or None."""
    value = info.get(key)
    return float(value) if isinstance(value, (int, float)) else np.nan


def _fmt(value, signed=False, suffix=""):
    """Analyst figures are missing often enough that they are rendered as text:
    Streamlit prints a null in a number column as the literal word "None"."""
    if pd.isna(value):
        return "N/A"
    return f"{value:+.2f}{suffix}" if signed else f"{value:.2f}{suffix}"


def _fetch_ticker_info(ticker):
    """Fetch analyst info for a single ticker (runs in parallel)."""
    try:
        info = yf.Ticker(ticker).info
        return ticker, info, None
    except Exception as e:
        return ticker, {}, str(e)


def get_financial_data(tickers):
    """
    Download and process data for a list of tickers, with built-in caching.
    Returns (DataFrame, list of errors, meta) where meta reports whether the
    daily analyst record was needed and how old it is.
    """
    now = datetime.now()
    cache_key = tuple(sorted(tickers))

    if cache_key in _data_cache:
        cached_time, cached_df, cached_errors, cached_meta = _data_cache[cache_key]
        if (now - cached_time).total_seconds() < CACHE_EXPIRY_SECONDS:
            return cached_df, cached_errors, cached_meta

    errors = []
    record = load_analyst_record()
    record_tickers = record.get("tickers", {})
    # Tickers the record job looked at, including those that legitimately have no
    # analyst coverage, so an ETF is not reported as a failure.
    record_checked = set(record.get("checked", record_tickers))
    # Upcoming events exist only in the record: Yahoo's live quote is refused on the
    # hosted app, and the events change on the order of days anyway.
    record_events = record.get("events", {})
    today = market_today()
    meta = {"record_generated": record.get("generated"), "record_used": False,
            "quotes_refused": False, "last_close": None,
            "events": {t: record_events[t] for t in tickers if t in record_events},
            # Daily series per ticker for the detail panel's chart and returns. Kept
            # here because the download is already paid for; nothing else re-fetches.
            "history": {}}

    raw_data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", auto_adjust=True)

    # Analyst data is one network call per ticker, so fetch them concurrently
    info_by_ticker = {}
    with ThreadPoolExecutor(max_workers=min(8, len(tickers)) or 1) as executor:
        futures = {executor.submit(_fetch_ticker_info, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, info, err = future.result()
            info_by_ticker[ticker] = info
            if err:
                errors.append(f"{ticker}: could not fetch analyst data ({err})")

    # Yahoo answers with an empty payload instead of an error when it refuses a request,
    # which would otherwise show up as silently blank analyst columns. Every valid symbol
    # carries marketState, ETFs included, so its absence means a real miss. The quote
    # endpoint needs an authenticated handshake and Yahoo restricts it from datacenter
    # addresses, so this is expected to be persistent on hosted deployments.
    missing_quotes = sorted(t for t in tickers if not info_by_ticker.get(t, {}).get('marketState'))
    # Only a wholesale refusal means the endpoint is unreachable here; one bad symbol
    # says nothing about the deployment.
    meta["quotes_refused"] = len(missing_quotes) == len(tickers) and bool(tickers)

    results = []

    for ticker in tickers:
        try:
            df = raw_data[ticker].dropna()
            if df.empty:
                errors.append(f"{ticker}: no historical data found")
                continue

            close = df['Close']
            high = df['High']
            low = df['Low']
            current_price = close.iloc[-1]

            last_bar = str(df.index[-1])[:10]
            if meta["last_close"] is None or last_bar > meta["last_close"]:
                meta["last_close"] = last_bar

            # RSI (14), Wilder smoothing - matches TradingView / Yahoo
            delta = close.diff()
            avg_gain = _wilder_rma(delta.clip(lower=0), 14)
            avg_loss = _wilder_rma(-delta.clip(upper=0), 14)
            rsi = 100 - (100 / (1 + avg_gain / avg_loss))
            current_rsi = rsi.iloc[-1]

            # Bollinger Bands (20, 2); ddof=0 is the charting-platform convention
            sma20 = close.rolling(window=20).mean()
            std20 = close.rolling(window=20).std(ddof=0)
            upper_band = sma20 + (std20 * 2)
            lower_band = sma20 - (std20 * 2)

            # ATR (14), Wilder smoothing
            tr = np.maximum((high - low), np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
            atr = _wilder_rma(tr, 14).iloc[-1]

            # Long-term trend. A year of daily bars leaves about 50 values past the
            # warm-up; a younger listing simply has none and gets no trend marker.
            sma200_series = close.rolling(window=200).mean()
            sma200 = sma200_series.iloc[-1]
            below_trend = pd.notna(sma200) and current_price < sma200

            meta["history"][ticker] = pd.DataFrame({
                "Close": close, "High": high, "Low": low,
                "Upper": upper_band, "Lower": lower_band, "SMA200": sma200_series,
            })

            # Dynamic dip / take-profit levels for the DCA strategy
            mod_dip = lower_band.iloc[-1]
            strong_dip = mod_dip - (0.5 * atr)
            mod_tp = upper_band.iloc[-1]
            strong_tp = mod_tp + (0.5 * atr)

            # Price signal. Upper-band touches are labelled "overextended" rather
            # than "sell": on the 1996-2026 S&P 500 backtest (docs/backtest-broad-
            # universe.md) they returned +2.2% over 60 days against a +3.2% baseline,
            # below average but still positive, so "don't add here", not "exit".
            # The STRONG tier is kept as a price level, although that backtest found
            # no ATR offset that separates outcomes once volatility is matched.
            price_signal = "HOLD"
            if current_price <= strong_dip:
                price_signal = "STRONG BUY (Dip)"
            elif current_price <= mod_dip:
                price_signal = "BUY (Mod Dip)"
            elif current_price >= strong_tp:
                price_signal = "VERY OVEREXTENDED"
            elif current_price >= mod_tp:
                price_signal = "OVEREXTENDED"

            # Below SMA200 the trend is down. Not a filter: the backtest could not
            # settle whether one helps. But such dips are a different bet: 41% of them
            # regained their prior 52-week high within a year, against 78% above the
            # trend, with a fatter left tail. An upper-band touch below SMA200 was the
            # weakest upper-band case. The marker makes that visible without hiding it.
            if below_trend and price_signal != "HOLD":
                price_signal += " \u2193"

            if current_rsi < 30:
                rsi_signal = "OVERSOLD"
            elif current_rsi > 70:
                rsi_signal = "OVERBOUGHT"
            else:
                rsi_signal = "NEUTRAL"

            # Conviction grades a dip by RSI. On the broad backtest a dip with RSI<30
            # returned +5.6% over 60 days and one with RSI 40 or more +3.3%, the same
            # as the +3.2% baseline. So a WEAK dip is no better than no signal. The
            # extra return at low RSI comes with worse tails and vanishes against
            # stocks of equal volatility: it pays for risk, it is not a free edge.
            # A dip fires on only a minority of days, so the rest of the time the
            # column reports the distance left to one, measured in ATR so that it
            # compares across tickers.
            if "BUY" in price_signal:
                if current_rsi < 30:
                    conviction = "HIGH"
                elif current_rsi < 40:
                    conviction = "MEDIUM"
                else:
                    conviction = "WEAK"
            elif pd.notna(mod_dip) and pd.notna(atr) and atr > 0:
                conviction = f"{(current_price - mod_dip) / atr:.1f} ATR"
            else:
                conviction = "-"

            # Analyst context (already fetched above; no extra network cost). When the
            # quote endpoint was refused, fall back to the daily record for the figures
            # that change slowly. Market state and extended hours are deliberately not
            # filled in: a day-old value there would be misleading rather than stale.
            info = info_by_ticker.get(ticker, {})
            if not info.get('marketState') and ticker in record_tickers:
                info = {**record_tickers[ticker], **info}
                meta["record_used"] = True

            # Extended-hours quote. Pre/post-market prints are thin and volatile, so
            # they are reported for reference only and never feed the indicators
            # above, which stay on settled regular-session closes.
            market_state = info.get('marketState') or 'UNKNOWN'
            if market_state.startswith('PRE'):
                ext_price = _num(info, 'preMarketPrice')
                ext_change = _num(info, 'preMarketChangePercent')
            elif market_state.startswith('POST') or market_state == 'CLOSED':
                ext_price = _num(info, 'postMarketPrice')
                ext_change = _num(info, 'postMarketChangePercent')
            else:
                ext_price = ext_change = np.nan

            if pd.notna(ext_price):
                extended = f"{ext_price:.2f}"
                if pd.notna(ext_change):
                    extended += f" ({ext_change:+.2f}%)"
            else:
                extended = "N/A"

            target_median = _num(info, 'targetMedianPrice')
            if pd.isna(target_median):
                target_median = _num(info, 'targetMeanPrice')
            target_low = _num(info, 'targetLowPrice')
            target_high = _num(info, 'targetHighPrice')
            analyst_count = _num(info, 'numberOfAnalystOpinions')
            recommendation = (info.get('recommendationKey') or 'N/A').upper()
            if pd.notna(analyst_count):
                recommendation = f"{recommendation} ({int(analyst_count)})"

            upside = (target_median / current_price - 1) * 100 if pd.notna(target_median) else np.nan

            results.append({
                "Ticker": ticker,
                "Price": round(current_price, 2),
                "Ext": extended,
                "Signal": price_signal,
                "Conviction": conviction,
                "Next Event": next_event(record_events.get(ticker), today),
                "RSI (14)": round(current_rsi, 2),
                "RSI Sig": rsi_signal,
                "Mod Dip": round(mod_dip, 2),
                "Strong Dip": round(strong_dip, 2),
                "Mod TP": round(mod_tp, 2),
                "Strong TP": round(strong_tp, 2),
                "Upside %": _fmt(upside, signed=True, suffix="%"),
                "Target Median": _fmt(target_median),
                "Target Low": _fmt(target_low),
                "Target High": _fmt(target_high),
                "Analyst Rec": recommendation,
                "Market": market_state,
            })
        except Exception as e:
            errors.append(f"{ticker}: processing error ({e})")
            print(f"Error processing {ticker}: {e}")

    # Only a refusal the record cannot cover is worth a warning, and only for a ticker
    # that otherwise worked: one that failed outright already said so above. Where the
    # record fills in, the caption reports it, so a warning still means something broke.
    priced = {row["Ticker"] for row in results}
    uncovered = [t for t in missing_quotes if t not in record_checked and t in priced]
    if uncovered:
        errors.append(
            "Yahoo returned no analyst data for " + ", ".join(uncovered) +
            ". Its authenticated endpoint is usually blocked for hosted apps and rate-limited "
            "elsewhere. Prices, signals and indicators are unaffected."
        )

    final_df = pd.DataFrame(results)
    _data_cache[cache_key] = (now, final_df, errors, meta)
    return final_df, errors, meta
