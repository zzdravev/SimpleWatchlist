import streamlit as st
import pandas as pd
from engine import get_financial_data

st.set_page_config(page_title="Simple Watchlist", layout="wide")

DEFAULT_TICKERS = "NVDA, VUAA.L, KO, JNJ, O, META, GOOGL, MSFT, TSLA, AAPL, AMZN, JPM, AVGO, CVX"

if "ticker_input" not in st.session_state:
    st.session_state.ticker_input = DEFAULT_TICKERS
if "show_editor" not in st.session_state:
    st.session_state.show_editor = False

header, refresh_col, edit_col = st.columns([6, 1, 1], vertical_alignment="center")
with header:
    st.markdown("#### Simple Watchlist")
with refresh_col:
    refresh_clicked = st.button("Refresh", width="stretch")
with edit_col:
    if st.button("Edit tickers", width="stretch"):
        st.session_state.show_editor = not st.session_state.show_editor

tickers = [t.strip().upper() for t in st.session_state.ticker_input.split(",") if t.strip()]

should_refresh = (
    refresh_clicked
    or "df_data" not in st.session_state
    or st.session_state.get("last_tickers") != tickers
)

if should_refresh:
    with st.spinner("Fetching data from Yahoo Finance..."):
        st.session_state.df_data, st.session_state.errors = get_financial_data(tickers)
        st.session_state.last_tickers = tickers

if st.session_state.get("errors"):
    st.warning("Some tickers could not be loaded:\n\n" + "\n".join(f"- {e}" for e in st.session_state.errors))

if "df_data" in st.session_state and not st.session_state.df_data.empty:
    df = st.session_state.df_data.copy()

    def highlight_signals(val):
        if "BUY" in str(val):
            return "background-color: #2e7d32; color: white;"
        elif "OVEREXTENDED" in str(val):
            return "background-color: #ef6c00; color: white;"
        return ""

    def highlight_rsi_signal(val):
        if val == "OVERSOLD":
            return "background-color: #2e7d32; color: white;"
        elif val == "OVERBOUGHT":
            return "background-color: #c62828; color: white;"
        return ""

    def highlight_conviction(val):
        if val == "HIGH":
            return "background-color: #1b5e20; color: white; font-weight: bold;"
        elif val == "MEDIUM":
            return "background-color: #558b2f; color: white;"
        elif val == "LOW":
            return "background-color: #9e9d24; color: white;"
        return ""

    # Pastel shades keep the analyst columns visually secondary to the
    # technical signals, which are the ones actually driving decisions.
    analyst_rec_colors = {
        "STRONG_BUY": ("#c8e6c9", "#1b5e20"),
        "BUY": ("#e8f5e9", "#2e7d32"),
        "HOLD": ("#eceff1", "#37474f"),
        "UNDERPERFORM": ("#ffe0b2", "#e65100"),
        "SELL": ("#ffcdd2", "#b71c1c"),
    }

    def highlight_analyst_rec(val):
        # Values look like "STRONG_BUY (59)"; exact lookup avoids BUY matching STRONG_BUY
        colors = analyst_rec_colors.get(str(val).split(" (")[0])
        if not colors:
            return ""
        background, text = colors
        return f"background-color: {background}; color: {text};"

    def highlight_upside(val):
        if not isinstance(val, (int, float)) or pd.isnull(val):
            return ""
        neutral = (245, 245, 245)
        target = (165, 214, 167) if val >= 0 else (239, 154, 154)
        weight = min(abs(val) / 40, 1.0)
        r, g, b = (round(n + (t - n) * weight) for n, t in zip(neutral, target))
        return f"background-color: rgb({r}, {g}, {b}); color: #263238;"

    decimal_columns = ["Price", "RSI (14)", "Mod Dip", "Strong Dip", "Mod TP", "Strong TP",
                       "Target Median", "Target Low", "Target High"]

    def format_decimal(val):
        if isinstance(val, (int, float)) and pd.notnull(val):
            return f"{val:.2f}"
        return "N/A"

    def format_upside(val):
        if isinstance(val, (int, float)) and pd.notnull(val):
            return f"{val:+.2f}%"
        return "N/A"

    styled_df = (
        df.style
        .map(highlight_signals, subset=["Signal"])
        .map(highlight_rsi_signal, subset=["RSI Sig"])
        .map(highlight_conviction, subset=["Conviction"])
        .map(highlight_analyst_rec, subset=["Analyst Rec"])
        .map(highlight_upside, subset=["Upside %"])
        .format(format_decimal, subset=decimal_columns)
        .format(format_upside, subset=["Upside %"])
    )

    st.dataframe(styled_df, width="stretch", height=560, hide_index=True, row_height=28)
else:
    st.warning("No data found for the selected tickers.")

if st.session_state.show_editor:
    st.divider()
    st.text_input("Tickers (comma separated)", key="ticker_input")
    st.caption("Analyst targets are 12-month forward estimates and are not part of the signal logic.")
