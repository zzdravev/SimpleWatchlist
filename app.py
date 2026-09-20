import streamlit as st
import pandas as pd
from engine import get_financial_data

st.set_page_config(page_title="Simple Watchlist", layout="wide")

DEFAULT_TICKERS = "NVDA, VUAA.L, KO, JNJ, O, META, GOOGL, MSFT, TSLA, AAPL, AMZN, JPM, AVGO, CVX"

# Analyst targets go stale without being withdrawn: PARA once showed a $24 target
# against a $0.93 price (+2480%). Past this point the target says nothing useful.
IMPLAUSIBLE_UPSIDE = 200

# A table held in session state from an earlier version of the code can be missing
# columns this script now expects, so check the schema instead of crashing on it.
REQUIRED_COLUMNS = {
    "Ticker", "Price", "Ext", "Signal", "Conviction", "RSI (14)", "RSI Sig",
    "Mod Dip", "Strong Dip", "Mod TP", "Strong TP", "Upside %",
    "Target Median", "Target Low", "Target High", "Analyst Rec", "Market",
}

if "ticker_input" not in st.session_state:
    st.session_state.ticker_input = DEFAULT_TICKERS
if "show_editor" not in st.session_state:
    st.session_state.show_editor = False


def toggle_editor():
    st.session_state.show_editor = not st.session_state.show_editor
    st.session_state.scroll_target = "editor-anchor" if st.session_state.show_editor else None


def request_refresh(scroll_to_top=False):
    st.session_state.force_refresh = True
    if scroll_to_top:
        st.session_state.scroll_target = "top-anchor"


st.markdown('<div id="top-anchor"></div>', unsafe_allow_html=True)

header, refresh_col, edit_col = st.columns([6, 1, 1], vertical_alignment="center")
with header:
    st.markdown("#### Simple Watchlist")
with refresh_col:
    st.button("Refresh", width="stretch", on_click=request_refresh)
with edit_col:
    st.button("Edit tickers", width="stretch", on_click=toggle_editor)

tickers = [t.strip().upper() for t in st.session_state.ticker_input.split(",") if t.strip()]

cached = st.session_state.get("df_data")
stale_schema = cached is not None and not cached.empty and not REQUIRED_COLUMNS.issubset(cached.columns)

should_refresh = (
    st.session_state.pop("force_refresh", False)
    or "df_data" not in st.session_state
    or stale_schema
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

    # "Market" drives the status caption rather than a column of its own
    market_states = sorted({s for s in df["Market"] if s and s != "UNKNOWN"})
    df = df.drop(columns=["Market"])

    def highlight_extended(val):
        # Pastel: extended-hours moves are context, not a signal
        if "(+" in str(val):
            return "background-color: #e8f5e9; color: #2e7d32;"
        if "(-" in str(val):
            return "background-color: #ffebee; color: #c62828;"
        return ""

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
        if abs(val) > IMPLAUSIBLE_UPSIDE:
            # Grey rather than deep green, so a stale target does not read as the
            # strongest opportunity in the table.
            return "background-color: #eceff1; color: #78909c; font-style: italic;"
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
        .map(highlight_extended, subset=["Ext"])
        .map(highlight_signals, subset=["Signal"])
        .map(highlight_rsi_signal, subset=["RSI Sig"])
        .map(highlight_conviction, subset=["Conviction"])
        .map(highlight_analyst_rec, subset=["Analyst Rec"])
        .map(highlight_upside, subset=["Upside %"])
        .format(format_decimal, subset=decimal_columns)
        .format(format_upside, subset=["Upside %"])
    )

    st.caption(
        f"Market state: {', '.join(market_states) or 'unknown'}. "
        "Ext is the latest pre/post-market quote; indicators and signals use regular-session closes only."
    )
    st.dataframe(styled_df, width="stretch", height=560, hide_index=True, row_height=28)
else:
    st.warning("No data found for the selected tickers.")

if st.session_state.show_editor:
    st.divider()
    st.markdown('<div id="editor-anchor"></div>', unsafe_allow_html=True)
    with st.container(key="ticker-editor"):
        # persist_state keeps the value when the editor is collapsed; without it
        # Streamlit drops the widget state and the watchlist resets to defaults.
        st.text_input("Tickers (comma separated)", key="ticker_input", persist_state="session")
    st.button("Refresh", key="refresh_bottom", on_click=request_refresh, kwargs={"scroll_to_top": True})
    st.caption(
        "Analyst targets are 12-month forward estimates and are not part of the signal logic. "
        f"An upside above {IMPLAUSIBLE_UPSIDE}% is shown in grey: the target is most likely stale."
    )

scroll_target = st.session_state.pop("scroll_target", None)
if scroll_target:
    focus_editor = "true" if scroll_target == "editor-anchor" else "false"
    # scroll_target is always one of our own literals, never user input
    st.iframe(
        f"""
        <script>
            setTimeout(function () {{
                const doc = window.parent.document;
                const anchor = doc.getElementById("{scroll_target}");
                if (anchor) {{
                    anchor.scrollIntoView({{behavior: "smooth", block: "center"}});
                }}
                if ({focus_editor}) {{
                    const input = doc.querySelector(".st-key-ticker-editor input")
                        || doc.querySelector('input[aria-label="Tickers (comma separated)"]');
                    if (input) {{ input.focus(); }}
                }}
            }}, 150);
        </script>
        """,
        height=1,
    )
