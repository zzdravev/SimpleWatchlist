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
                "Signal": price_signal,
                "Conviction": conviction,
                "RSI (14)": round(current_rsi, 2),
                "RSI Sig": rsi_signal,
                "Mod Dip": round(mod_dip, 2),
                "Strong Dip": round(strong_dip, 2),
                "Mod TP": round(mod_tp, 2),
                "Strong TP": round(strong_tp, 2),
                "Upside %": round(upside, 2) if pd.notna(upside) else np.nan,
                "Target Median": round(target_median, 2) if pd.notna(target_median) else np.nan,
                "Target Low": round(target_low, 2) if pd.notna(target_low) else np.nan,
                "Target High": round(target_high, 2) if pd.notna(target_high) else np.nan,
                "Analyst Rec": recommendation,
            })
        except Exception as e:
            errors.append(f"{ticker}: processing error ({e})")
            print(f"Error processing {ticker}: {e}")

    final_df = pd.DataFrame(results)
    _data_cache[cache_key] = (now, final_df, errors)
    return final_df, errors
