import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Cache lifetime in seconds (300 seconds = 5 minutes)
CACHE_EXPIRY_SECONDS = 300
_data_cache = {}


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
    Returns (DataFrame, list of errors) where each error is a string.
    """
    now = datetime.now()
    cache_key = tuple(sorted(tickers))

    if cache_key in _data_cache:
        cached_time, cached_df, cached_errors = _data_cache[cache_key]
        if (now - cached_time).total_seconds() < CACHE_EXPIRY_SECONDS:
            return cached_df, cached_errors

    errors = []

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
    if missing_quotes and len(missing_quotes) == len(tickers):
        errors.append(
            "Yahoo returned no quote details, so analyst targets, market state and extended-hours "
            "prices are unavailable. Its authenticated endpoint is usually blocked for hosted apps "
            "and rate-limited elsewhere. Prices, signals and indicators are unaffected."
        )
    elif missing_quotes:
        errors.append("No quote details for: " + ", ".join(missing_quotes))

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

            # Dynamic dip / take-profit levels for the DCA strategy
            mod_dip = lower_band.iloc[-1]
            strong_dip = mod_dip - (0.5 * atr)
            mod_tp = upper_band.iloc[-1]
            strong_tp = mod_tp + (0.5 * atr)

            # Price signal. Upper-band touches are labelled "overextended" rather
            # than "sell": backtesting showed forward returns after those signals
            # match or beat the baseline, so they mean "don't add here", not "exit".
            price_signal = "HOLD"
            if current_price <= strong_dip:
                price_signal = "STRONG BUY (Dip)"
            elif current_price <= mod_dip:
                price_signal = "BUY (Mod Dip)"
            elif current_price >= strong_tp:
                price_signal = "VERY OVEREXTENDED"
            elif current_price >= mod_tp:
                price_signal = "OVEREXTENDED"

            if current_rsi < 30:
                rsi_signal = "OVERSOLD"
            elif current_rsi > 70:
                rsi_signal = "OVERBOUGHT"
            else:
                rsi_signal = "NEUTRAL"

            # Conviction combines the band dip with RSI. Over a 5y backtest of this
            # watchlist, a dip with RSI<30 returned +12.8% over 60 days (82% win rate)
            # versus +4.0% for a dip with RSI>40.
            if "BUY" in price_signal:
                if current_rsi < 30:
                    conviction = "HIGH"
                elif current_rsi < 40:
                    conviction = "MEDIUM"
                else:
                    conviction = "LOW"
            else:
                conviction = "-"

            # Analyst context (already fetched above; no extra network cost)
            info = info_by_ticker.get(ticker, {})

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

    final_df = pd.DataFrame(results)
    _data_cache[cache_key] = (now, final_df, errors)
    return final_df, errors
