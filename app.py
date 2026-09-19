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

if st.button("Освежи податоци") or "df_data" not in st.session_state:
    with st.spinner("Се преземаат податоци од Yahoo Finance..."):
        st.session_state.df_data = get_financial_data(tickers)

if "df_data" in st.session_state and not st.session_state.df_data.empty:
    df = st.session_state.df_data.copy()

    # Стилизирање на табелата (бои за сигнали)
    def highlight_signals(val):
        if "BUY" in str(val):
            return "background-color: #2e7d32; color: white;"
        elif "SELL" in str(val):
            return "background-color: #c62828; color: white;"
        return ""

    styled_df = df.style.map(highlight_signals, subset=["Signal"])
    
    st.dataframe(styled_df, use_container_width=True, height=400)
else:
    st.warning("Нема пронајдено податоци за избраните тикери.")