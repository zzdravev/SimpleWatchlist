import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Траење на кешот во секунди (на пр. 300 секунди = 5 минути)
CACHE_EXPIRY_SECONDS = 300
_data_cache = {}


def _fetch_ticker_info(ticker):
    """Ги презема analyst info податоците за еден тикер (за паралелно извршување)."""
    try:
        info = yf.Ticker(ticker).info
        return ticker, info, None
    except Exception as e:
        return ticker, {}, str(e)


def get_financial_data(tickers):
    """
    Презема и процесира податоци за листа на тикери со вградено кеширање.
    Враќа (DataFrame, list на грешки) каде секоја грешка е string со тикер и причина.
    """
    now = datetime.now()
    cache_key = tuple(sorted(tickers))

    # Проверка дали имаме валидни кеширани податоци
    if cache_key in _data_cache:
        cached_time, cached_df, cached_errors = _data_cache[cache_key]
        if (now - cached_time).total_seconds() < CACHE_EXPIRY_SECONDS:
            return cached_df, cached_errors

    errors = []

    # Batch Download од yfinance
    raw_data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", auto_adjust=True)

    # Паралелно преземање на analyst target/recommendation за сите тикери,
    # за да не се чека секој мрежен повик по ред
    info_by_ticker = {}
    with ThreadPoolExecutor(max_workers=min(8, len(tickers)) or 1) as executor:
        futures = {executor.submit(_fetch_ticker_info, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, info, err = future.result()
            info_by_ticker[ticker] = info
            if err:
                errors.append(f"{ticker}: не можев да ги преземам analyst податоците ({err})")

    results = []

    for ticker in tickers:
        try:
            df = raw_data[ticker].dropna()
            if df.empty:
                errors.append(f"{ticker}: нема пронајдени историски податоци")
                continue

            # 1. Затворачка цена
            close = df['Close']
            current_price = close.iloc[-1]

            # 2. RSI (14)
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]

            # 3. Bollinger Bands (20, 2)
            sma20 = close.rolling(window=20).mean()
            std20 = close.rolling(window=20).std()
            upper_band = sma20 + (std20 * 2)
            lower_band = sma20 - (std20 * 2)

            # 4. ATR (14)
            high = df['High']
            low = df['Low']
            tr = np.maximum((high - low), np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
            atr = tr.rolling(window=14).mean().iloc[-1]

            # 5. Динамички Dip / Take Profit Нивоа (За DCA стратегија)
            mod_dip = lower_band.iloc[-1]
            strong_dip = lower_band.iloc[-1] - (0.5 * atr)
            mod_tp = upper_band.iloc[-1]
            strong_tp = upper_band.iloc[-1] + (0.5 * atr)

            # Сигнали
            price_signal = "HOLD"
            if current_price <= strong_dip:
                price_signal = "STRONG BUY (Dip)"
            elif current_price <= mod_dip:
                price_signal = "BUY (Mod Dip)"
            elif current_price >= strong_tp:
                price_signal = "STRONG SELL (TP)"
            elif current_price >= mod_tp:
                price_signal = "SELL (Mod TP)"

            # RSI сигнал (пренакупеност / пренапродаденост)
            if current_rsi < 30:
                rsi_signal = "OVERSOLD"
            elif current_rsi > 70:
                rsi_signal = "OVERBOUGHT"
            else:
                rsi_signal = "NEUTRAL"

            # Wall Street target/rec (веќе преземени паралелно погоре)
            info = info_by_ticker.get(ticker, {})
            target_price = info.get('targetMeanPrice', np.nan)
            recommendation = info.get('recommendationKey', 'N/A').upper()

            results.append({
                "Ticker": ticker,
                "Price": round(current_price, 2),
                "Signal": price_signal,
                "RSI (14)": round(current_rsi, 2),
                "RSI Sig": rsi_signal,
                "Mod Dip": round(mod_dip, 2),
                "Strong Dip": round(strong_dip, 2),
                "Mod TP": round(mod_tp, 2),
                "Strong TP": round(strong_tp, 2),
                "Target Price": round(target_price, 2) if pd.notnull(target_price) else np.nan,
                "Analyst Rec": recommendation
            })
        except Exception as e:
            errors.append(f"{ticker}: грешка при процесирање ({e})")
            print(f"Грешка при процесирање на {ticker}: {e}")

    final_df = pd.DataFrame(results)
    _data_cache[cache_key] = (now, final_df, errors)
    return final_df, errors
