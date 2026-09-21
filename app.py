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


# Streamlit generates a .st-key-<key> class for keyed containers; that is the
# supported way to address an element, unlike ids injected through raw HTML.
EDITOR_SELECTOR = ".st-key-ticker-editor"
TOP_SELECTOR = ".st-key-app-top"


def toggle_editor():
    st.session_state.show_editor = not st.session_state.show_editor
    st.session_state.scroll_target = EDITOR_SELECTOR if st.session_state.show_editor else None


def request_refresh(scroll_to_top=False):
    st.session_state.force_refresh = True
    if scroll_to_top:
        st.session_state.scroll_target = TOP_SELECTOR


with st.container(key="app-top"):
    header, refresh_col, edit_col = st.columns([6, 1, 1], vertical_alignment="center")
    with header:
        st.markdown("#### Simple Watchlist")
    with refresh_col:
        st.button("Refresh", key="refresh_top", width="stretch", on_click=request_refresh)
    with edit_col:
        st.button("Edit tickers", key="edit_toggle", width="stretch", on_click=toggle_editor)

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
        try:
            val = float(str(val).rstrip("%"))
        except ValueError:
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

    # Streamlit's guidance: column_config handles formatting, Styler only colours.
    price_help = "Price level derived from the last 20 regular-session closes."
    column_config = {
        "Ticker": st.column_config.TextColumn(help="Yahoo Finance symbol."),
        "Price": st.column_config.NumberColumn(
            format="%.2f",
            help="Last regular-session close. Extended hours are excluded so the indicators stay comparable.",
        ),
        "Ext": st.column_config.TextColumn(
            help="Latest pre- or post-market quote and its change against the regular close. "
                 "Reference only: it never feeds the indicators.",
        ),
        "Signal": st.column_config.TextColumn(
            help="Where the close sits against the Bollinger bands. BUY levels mark dips. "
                 "OVEREXTENDED means the price is stretched above the upper band, which is a "
                 "reason not to add rather than a reason to sell.",
        ),
        "Conviction": st.column_config.TextColumn(
            help="Strength of a BUY signal, combining the dip with RSI. Over a 5-year backtest "
                 "of this watchlist, a dip with RSI below 30 returned +12.8% over 60 days "
                 "against +4.0% for a dip with RSI above 40.",
        ),
        "RSI (14)": st.column_config.NumberColumn(
            format="%.2f",
            help="Relative Strength Index over 14 days with Wilder smoothing, the same figure "
                 "TradingView and Yahoo report.",
        ),
        "RSI Sig": st.column_config.TextColumn(help="OVERSOLD below 30, OVERBOUGHT above 70."),
        "Mod Dip": st.column_config.NumberColumn(
            format="%.2f", help=f"Lower Bollinger band (20, 2). A close at or below it triggers BUY. {price_help}"),
        "Strong Dip": st.column_config.NumberColumn(
            format="%.2f", help=f"Lower band minus half an ATR: a deeper dip, triggering STRONG BUY. {price_help}"),
        "Mod TP": st.column_config.NumberColumn(
            format="%.2f", help=f"Upper Bollinger band (20, 2). {price_help}"),
        "Strong TP": st.column_config.NumberColumn(
            format="%.2f", help=f"Upper band plus half an ATR. {price_help}"),
        # Text rather than numbers: these are missing often enough that a null number
        # column would print "None" across the table.
        "Upside %": st.column_config.TextColumn(
            alignment="right",
            help="Distance from the price to the median analyst target. Above "
                 f"{IMPLAUSIBLE_UPSIDE}% the cell turns grey, because a target that far away is "
                 "almost certainly stale rather than an opportunity.",
        ),
        "Target Median": st.column_config.TextColumn(
            alignment="right",
            help="Median 12-month analyst target, more robust to outliers than the mean.",
        ),
        "Target Low": st.column_config.TextColumn(
            alignment="right",
            help="Lowest 12-month analyst target. A wide low-to-high spread means analysts disagree."),
        "Target High": st.column_config.TextColumn(
            alignment="right", help="Highest 12-month analyst target."),
        "Analyst Rec": st.column_config.TextColumn(
            help="Consensus recommendation, with the number of contributing analysts in brackets.",
        ),
    }

    styled_df = (
        df.style
        .map(highlight_extended, subset=["Ext"])
        .map(highlight_signals, subset=["Signal"])
        .map(highlight_rsi_signal, subset=["RSI Sig"])
        .map(highlight_conviction, subset=["Conviction"])
        .map(highlight_analyst_rec, subset=["Analyst Rec"])
        .map(highlight_upside, subset=["Upside %"])
    )

    st.caption(
        f"Market state: {', '.join(market_states) or 'unknown'}. "
        "Ext is the latest pre/post-market quote; indicators and signals use regular-session closes only."
    )
    st.dataframe(styled_df, width="stretch", height=560, hide_index=True, row_height=28,
                 column_config=column_config)
else:
    st.warning("No data found for the selected tickers.")

if st.session_state.show_editor:
    st.divider()
    with st.container(key="ticker-editor"):
        # persist_state keeps the value when the editor is collapsed; without it
        # Streamlit drops the widget state and the watchlist resets to defaults.
        st.text_input("Tickers (comma separated)", key="ticker_input", persist_state="session")
    st.button("Refresh", key="refresh_bottom", on_click=request_refresh, kwargs={"scroll_to_top": True})
    st.caption(
        "Analyst targets are 12-month forward estimates and are not part of the signal logic. "
        f"An upside above {IMPLAUSIBLE_UPSIDE}% is shown in grey: the target is most likely stale."
    )

st.divider()

with st.expander("How to read this table"):
    st.markdown(
        """
The table scans a watchlist for **dips worth buying into**, in the spirit of dollar-cost
averaging. Every indicator is computed from the last year of daily closes.

**Your signals (left).** `Signal` compares the latest close to its Bollinger bands: at or
below the lower band is a dip, above the upper band is *overextended*. Overextended is
deliberately not called a sell — over a 5-year backtest of this watchlist, prices after
that signal returned about as much as the average day, so it means "don't add here"
rather than "get out". `Conviction` grades a dip by how oversold RSI is at the same time,
which is where the edge actually sits: a dip with RSI under 30 returned +12.8% over the
next 60 days, against +4.0% for a dip with RSI over 40.

**Your levels (middle).** `Mod Dip` and `Mod TP` are the Bollinger bands themselves;
`Strong Dip` and `Strong TP` sit half an ATR beyond them, so they adjust to how volatile
each stock currently is. These are the prices that would trigger the next signal.

**Analyst context (right).** Price targets are 12-month estimates from sell-side analysts.
They are shown in pale colours on purpose: they lag the price, are revised upward only
after a stock has already run, and are almost always bullish. They are **not** part of the
signal logic, and they are worth reading mainly as a spread — a wide `Target Low` to
`Target High` range means analysts disagree, so the median tells you little.

**What this does not do.** It knows nothing about earnings, valuation, debt, news or
anything fundamental. It measures how a price sits relative to its own recent range, and
those relationships hold on average, not in any individual case.
"""
    )

st.caption(
    "Technical indicators for research only, not financial advice. Signals are derived from "
    "past prices and say nothing certain about future returns. Data comes from Yahoo Finance "
    "and may be delayed, adjusted or wrong: verify before acting on it."
)

scroll_target = st.session_state.pop("scroll_target", None)
if scroll_target:
    focus_editor = "true" if scroll_target == EDITOR_SELECTOR else "false"
    # scroll_target is always one of our own constants, never user input
    st.iframe(
        f"""
        <script>
            setTimeout(function () {{
                try {{
                    const doc = window.parent.document;
                    const target = doc.querySelector("{scroll_target}");
                    if (target) {{
                        target.scrollIntoView({{behavior: "smooth", block: "center"}});
                    }}
                    if ({focus_editor}) {{
                        const input = doc.querySelector("{EDITOR_SELECTOR} input");
                        if (input) {{ input.focus(); }}
                    }}
                }} catch (e) {{}}
            }}, 150);
        </script>
        """,
        height=1,
    )
