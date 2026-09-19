import streamlit as st
import pandas as pd
from engine import get_financial_data

st.set_page_config(page_title="Watchlist & Alert App", layout="wide")

st.title("📈 Watchlist & Financial Alerts (DCA Focused)")

# Подготвени тикери (US + UK)
default_tickers = "NVDA, VUAA.L, KO, JNJ, O, META, GOOGL, MSFT, TSLA, AAPL, AMZN, JPM, AVGO, CVX"
user_input = st.text_input("Внесете тикери (одделени со запирка):", default_tickers)

# Исправена линија 13:
tickers = [t.strip().upper() for t in user_input.split(",") if t.strip()]

should_refresh = (
    st.button("Освежи податоци")
    or "df_data" not in st.session_state
    or st.session_state.get("last_tickers") != tickers
)

if should_refresh:
    with st.spinner("Се преземаат податоци од Yahoo Finance..."):
        st.session_state.df_data, st.session_state.errors = get_financial_data(tickers)
        st.session_state.last_tickers = tickers

if st.session_state.get("errors"):
    st.warning("Проблем при преземање за некои тикери:\n\n" + "\n".join(f"- {e}" for e in st.session_state.errors))

if "df_data" in st.session_state and not st.session_state.df_data.empty:
    df = st.session_state.df_data.copy()

    # Стилизирање на табелата (бои за сигнали)
    def highlight_signals(val):
        if "BUY" in str(val):
            return "background-color: #2e7d32; color: white;"
        elif "SELL" in str(val):
            return "background-color: #c62828; color: white;"
        return ""

    def highlight_rsi_signal(val):
        if val == "OVERSOLD":
            return "background-color: #2e7d32; color: white;"
        elif val == "OVERBOUGHT":
            return "background-color: #c62828; color: white;"
        return ""

    decimal_columns = ["Price", "RSI (14)", "Mod Dip", "Strong Dip", "Mod TP", "Strong TP", "Target Price"]

    def format_decimal(val):
        if isinstance(val, (int, float)) and pd.notnull(val):
            return f"{val:.2f}"
        return "N/A"

    styled_df = (
        df.style
        .map(highlight_signals, subset=["Signal"])
        .map(highlight_rsi_signal, subset=["RSI Sig"])
        .format(format_decimal, subset=decimal_columns)
    )

    st.dataframe(styled_df, width="stretch", height=400, hide_index=True)
else:
    st.warning("Нема пронајдено податоци за избраните тикери.")