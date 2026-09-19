import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta

# Траење на кешот во секунди (на пр. 300 секунди = 5 минути)
CACHE_EXPIRY_SECONDS = 300
_data_cache = {}

def get_financial_data(tickers):
    """
    Презема и процесира податоци за листа на тикери со вградено кеширање.
    """
    now = datetime.now()
    cache_key = tuple(sorted(tickers))
    
    # Проверка дали имаме валидни кеширани податоци
    if cache_key in _data_cache:
        cached_time, cached_df = _data_cache[cache_key]
        if (now - cached_time).total_seconds() < CACHE_EXPIRY_SECONDS:
            return cached_df

    # Batch Download од yfinance
    raw_data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", auto_adjust=True)
    
    results = []
    
    for ticker in tickers:
        try:
            df = raw_data[ticker].dropna() if len(tickers) > 1 else raw_data.dropna()
            if df.empty:
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

            # Конверзија за LSE (GBp -> GBP)
            if ticker.endswith(".L") and current_price > 500: # Груба процена за пенси
                current_price /= 100
                mod_dip /= 100
                strong_dip /= 100
                mod_tp /= 100
                strong_tp /= 100

            # Wall Street target/rec (Преку Ticker објект)
            t_obj = yf.Ticker(ticker)
            info = t_obj.info
            target_price = info.get('targetMeanPrice', np.nan)
            recommendation = info.get('recommendationKey', 'N/A').upper()

            results.append({
                "Ticker": ticker,
                "Price": round(current_price, 2),
                "RSI (14)": round(current_rsi, 1),
                "Signal": price_signal,
                "Mod Dip": round(mod_dip, 2),
                "Strong Dip": round(strong_dip, 2),
                "Mod TP": round(mod_tp, 2),
                "Target Price": round(target_price, 2) if pd.notnull(target_price) else "N/A",
                "Analyst Rec": recommendation
            })
        except Exception as e:
            print(f"Грешка при процесирање на {ticker}: {e}")

    final_df = pd.DataFrame(results)
    _data_cache[cache_key] = (now, final_df)
    return final_df