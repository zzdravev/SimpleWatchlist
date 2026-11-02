import re
from datetime import date

import streamlit as st
import pandas as pd
import browser_store
from engine import DEFAULT_TICKERS, get_financial_data, market_today


def short_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b")
    except ValueError:
        return "an earlier run"

st.set_page_config(page_title="Simple Watchlist", layout="wide")

DEFAULT_TICKER_TEXT = ", ".join(DEFAULT_TICKERS)

# Analyst targets go stale without being withdrawn: PARA once showed a $24 target
# against a $0.93 price (+2480%). Past this point the target says nothing useful.
IMPLAUSIBLE_UPSIDE = 200

# A table held in session state from an earlier version of the code can be missing
# columns this script now expects, so check the schema instead of crashing on it.
REQUIRED_COLUMNS = {
    "Ticker", "Price", "Ext", "Signal", "Conviction", "Next Event", "RSI (14)", "RSI Sig",
    "Mod Dip", "Strong Dip", "Mod TP", "Strong TP", "Upside %",
    "Target Median", "Target Low", "Target High", "Analyst Rec", "Market",
}

if "ticker_input" not in st.session_state:
    st.session_state.ticker_input = DEFAULT_TICKER_TEXT
if "show_editor" not in st.session_state:
    st.session_state.show_editor = False

# Every column the table can show except Ticker, which always stays. Columns are
# saved as the hidden set rather than the visible one, so a column added in a later
# version shows up for returning visitors instead of being hidden by default.
OPTIONAL_COLUMNS = [
    "Price", "Ext", "Signal", "Conviction", "Next Event", "RSI (14)", "RSI Sig", "Mod Dip",
    "Strong Dip", "Mod TP", "Strong TP", "Upside %", "Target Median", "Target Low",
    "Target High", "Analyst Rec",
]
if "visible_columns" not in st.session_state:
    hidden = browser_store.read("hidden_columns", default=[])
    if not isinstance(hidden, list):
        hidden = []
    st.session_state.visible_columns = [c for c in OPTIONAL_COLUMNS if c not in hidden]


# Events further out than this are listed but not coloured; at EVENT_ALERT_DAYS or
# fewer the cell turns solid red.
EVENT_HORIZON_DAYS = 30
EVENT_ALERT_DAYS = 3


def _blend(stops, t):
    """Colour at position t (0..1) along evenly spaced RGB stops."""
    t = min(max(t, 0.0), 1.0) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    frac = t - i
    return tuple(round(a + (b - a) * frac) for a, b in zip(stops[i], stops[i + 1]))


def event_days(label):
    """Days until the event in a "Next Event" label, or None if there is none."""
    match = re.search(r"· ~?(today|\d+)d?$", str(label))
    if not match:
        return None
    return 0 if match.group(1) == "today" else int(match.group(1))


def format_money(value):
    if not isinstance(value, (int, float)):
        return None
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(value) >= size:
            return f"${value / size:.1f}{suffix}"
    return f"${value:,.0f}"


def render_event_panel(ticker, events, today, generated):
    """Upcoming events for one ticker, shown under the table when its row is selected."""
    st.markdown(f"##### {ticker} · upcoming events")
    events = events or {}
    rows = []
    names = (("earnings", "Earnings"), ("ex_dividend", "Ex-dividend"),
             ("dividend_payment", "Dividend payment"))
    for kind, name in names:
        event = events.get(kind)
        if not event:
            continue
        when = date.fromisoformat(event["date"])
        days = (when - today).days
        if days < 0:
            continue
        details = []
        if kind == "earnings":
            if event.get("confirmed"):
                status = "Confirmed"
                hour = {"bmo": "before the open", "amc": "after the close"}.get(event.get("hour"))
                if hour:
                    details.append(hour)
            else:
                status = "Estimated"
                if event.get("latest"):
                    details.append(f"window to {date.fromisoformat(event['latest']).strftime('%d %b')}")
            sources = [f"{src} {date.fromisoformat(event[key]).strftime('%d %b')}"
                       for src, key in (("Yahoo", "yahoo"), ("Finnhub", "finnhub")) if event.get(key)]
            if len(sources) == 2 and event["yahoo"] != event["finnhub"]:
                details.append("sources differ: " + ", ".join(sources))
            if isinstance(event.get("eps_estimate"), (int, float)):
                details.append(f"EPS est. {event['eps_estimate']:.2f}")
            revenue = format_money(event.get("revenue_estimate"))
            if revenue:
                details.append(f"revenue est. {revenue}")
        elif kind == "ex_dividend":
            status = "Announced"
            details.append("buy before this date to receive the next dividend")
        else:
            status = "Announced"
        rows.append({
            "Event": name,
            "Date": when.strftime("%a %d %b %Y"),
            "In": "today" if days == 0 else f"{days} days",
            "Status": status,
            "Details": " · ".join(details),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No earnings or dividend dates known for the next 120 days.")
    if generated:
        st.caption(
            f"Collected {short_date(generated)} from Yahoo and Finnhub. An estimated earnings "
            "date is a projection until the company confirms it. Where the sources are a day "
            "apart Yahoo's date is used, since Finnhub often runs a day early; where they "
            "differ by more, the earlier date is used so the warning is not late."
        )


# Streamlit generates a .st-key-<key> class for keyed containers; that is the
# supported way to address an element, unlike ids injected through raw HTML.
EDITOR_SELECTOR = ".st-key-ticker-editor"
TOP_SELECTOR = ".st-key-app-top"


def toggle_editor():
    st.session_state.show_editor = not st.session_state.show_editor
    st.session_state.scroll_target = EDITOR_SELECTOR if st.session_state.show_editor else None


def save_columns():
    visible = set(st.session_state.visible_columns)
    browser_store.write("hidden_columns", [c for c in OPTIONAL_COLUMNS if c not in visible])


def request_refresh(scroll_to_top=False):
    st.session_state.force_refresh = True
    if scroll_to_top:
        st.session_state.scroll_target = TOP_SELECTOR


with st.container(key="app-top"):
    header, columns_col, refresh_col, edit_col = st.columns([5, 1, 1, 1], vertical_alignment="center")
    with header:
        st.markdown("#### Simple Watchlist")
    with columns_col:
        with st.popover("Columns", width="stretch"):
            st.pills("Shown columns", OPTIONAL_COLUMNS, selection_mode="multi",
                     key="visible_columns", on_change=save_columns,
                     help="Remembered in this browser.")
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
        (st.session_state.df_data, st.session_state.errors,
         st.session_state.meta) = get_financial_data(tickers)
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
        elif val == "WEAK":
            # Pale: a dip with RSI of 40 or more did no better than an average day.
            return "background-color: #f0f4c3; color: #827717;"
        # A distance to the next dip. Deliberately pastel: a triggered signal should
        # stay visibly stronger than merely being near one.
        try:
            distance = float(str(val).split()[0])
        except ValueError:
            return ""
        neutral, near = (245, 245, 245), (197, 225, 165)
        weight = 1 - min(max(distance, 0) / 3, 1)
        r, g, b = (round(n + (t - n) * weight) for n, t in zip(neutral, near))
        return f"background-color: rgb({r}, {g}, {b}); color: #263238;"

    # Pastel shades keep the analyst columns visually secondary to the
    # technical signals, which are the ones actually driving decisions.
    analyst_rec_colors = {
        "STRONG_BUY": ("#c8e6c9", "#1b5e20"),
        "BUY": ("#e8f5e9", "#2e7d32"),
        "HOLD": ("#eceff1", "#37474f"),
        "UNDERPERFORM": ("#ffe0b2", "#e65100"),
        "SELL": ("#ffcdd2", "#b71c1c"),
    }

    def highlight_event(val):
        days = event_days(val)
        if days is None or days > EVENT_HORIZON_DAYS:
            return ""
        if days <= EVENT_ALERT_DAYS:
            return "background-color: #e53935; color: white; font-weight: bold;"
        # Green far out, amber halfway, light red approaching the alert threshold.
        stops = ((200, 230, 201), (255, 224, 130), (239, 154, 154))
        position = (EVENT_HORIZON_DAYS - days) / (EVENT_HORIZON_DAYS - EVENT_ALERT_DAYS)
        r, g, b = _blend(stops, position)
        return f"background-color: rgb({r}, {g}, {b}); color: #263238;"

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
                 "OVEREXTENDED means the price is stretched above the upper band: returns "
                 "after it were below average but still positive, so it is a reason not to "
                 "add rather than a reason to sell. \u2193 means the price is below its "
                 "200-day average: only 41% of such dips regained their prior high within a "
                 "year, against 78% in an uptrend.",
        ),
        "Conviction": st.column_config.TextColumn(
            help="For a live dip, HIGH (RSI below 30), MEDIUM (30 to 40) or WEAK (40 and "
                 "above). Over 1996-2026 on the S&P 500, a HIGH dip returned +5.6% over 60 "
                 "days and a WEAK one +3.3%, no better than an average day at +3.2%. The "
                 "extra return at low RSI comes with deeper losses when it goes wrong. "
                 "Otherwise it shows how far the price still is from the Mod Dip level, "
                 "measured in ATR so tickers of different volatility compare. Smaller is "
                 "closer; it is a watch list, not a signal.",
        ),
        "Next Event": st.column_config.TextColumn(
            width="medium",
            help="The nearest earnings report or ex-dividend date, in calendar days. "
                 f"Coloured from green at {EVENT_HORIZON_DAYS} days to red at "
                 f"{EVENT_ALERT_DAYS} or fewer. A tilde (~) marks an earnings date the "
                 "company has not confirmed yet. Select the row for details. A dip just "
                 "before earnings is often the market positioning for the report rather "
                 "than an opportunity.",
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
        .map(highlight_event, subset=["Next Event"])
        .map(highlight_analyst_rec, subset=["Analyst Rec"])
        .map(highlight_upside, subset=["Upside %"])
    )

    # Only what cannot be learned elsewhere: how current the prices are, and where
    # the analyst figures came from. Column meanings live in the header tooltips
    # and the expander below, so they are not repeated here.
    meta = st.session_state.get("meta") or {}
    parts = []
    if meta.get("last_close"):
        parts.append(f"Prices to {short_date(meta['last_close'])}")
    if meta.get("record_used"):
        parts.append(f"analyst data from the record of {short_date(meta.get('record_generated'))}")
    elif not meta.get("quotes_refused"):
        parts.append("analyst data live")
    if market_states:
        parts.append(f"market {', '.join(market_states).lower()}")
    if meta.get("quotes_refused"):
        parts.append("Ext unavailable on this deployment")
    st.caption(" · ".join(parts))
    table = st.dataframe(styled_df, width="stretch", height=560, hide_index=True, row_height=28,
                         column_config=column_config,
                         column_order=["Ticker", *st.session_state.visible_columns],
                         key="watchlist_table", on_select="rerun", selection_mode="single-row")

    selected = table.selection.rows
    if selected and selected[0] < len(df):
        ticker = df.iloc[selected[0]]["Ticker"]
        with st.container(border=True):
            render_event_panel(ticker, meta.get("events", {}).get(ticker), market_today(),
                               meta.get("record_generated"))
    else:
        st.caption("Select a row to see that ticker's upcoming events.")
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
below the lower band is a dip, above the upper band is *overextended*. The numbers below
come from a backtest over every S&P 500 member from 1996 to 2026; the details are in
`docs/backtest-broad-universe.md`.

A dip did beat an average day: +4.8% over the next 60 days for a STRONG BUY, against
+3.2% for any day. But almost all of that comes from *when* dips happen. They cluster in
market-wide sell-offs, when everything is cheap, so on a dip day an index fund would have
done about as well. Read a BUY as "the market is on sale", not as "this stock beats the
others".

`Conviction` grades a dip by RSI. A HIGH dip (RSI under 30) returned +5.6%, a WEAK one
(RSI 40 or more) +3.3%, which is no better than not having a signal. The extra return at
low RSI is paid for in risk: those dips also had the deepest losses when they went wrong.

A **↓** after a signal means the price is below its 200-day average. That is not a
reason to skip a dip, since the backtest could not settle whether it is, but it is a
different bet: only 41% of such dips regained their prior high within a year, against 78%
for dips in an uptrend. An overextended reading with ↓ is the weakest upper-band case.

Overextended is deliberately not called a sell. Returns after it were below average,
+2.2% against +3.2%, but still positive, so it means "don't add here" rather than "get
out".

When there is no dip, `Conviction` shows how far the price still has to fall to reach
`Mod Dip`, counted in ATR so a quiet stock and a volatile one can be compared. Those
values are shown in pale green rather than solid: read them as "worth watching", never as
"nearly a buy".

**Your levels (middle).** `Mod Dip` and `Mod TP` are the Bollinger bands themselves;
`Strong Dip` and `Strong TP` sit half an ATR beyond them, so they adjust to how volatile
each stock currently is. These are the prices that would trigger the next signal. The
STRONG tier is a price level, not a better signal: no offset tested separated outcomes.
Any column can be hidden from the `Columns` menu, and the choice is remembered in this
browser.

**Analyst context (right).** Price targets are 12-month estimates from sell-side analysts.
They are shown in pale colours on purpose: they lag the price, are revised upward only
after a stock has already run, and are almost always bullish. They are **not** part of the
signal logic, and they are worth reading mainly as a spread — a wide `Target Low` to
`Target High` range means analysts disagree, so the median tells you little.

**Upcoming events.** `Next Event` counts down to the nearest earnings report or
ex-dividend date, turning from green at 30 days to red at 3 or fewer. Select a row to see
all of that ticker's known dates. A dip in the days before earnings is often the market
positioning for the report, which is a different situation from the sell-offs the
backtest measured.

**What this does not do.** Apart from those dates it knows nothing about earnings,
valuation, debt, news or anything fundamental. It measures how a price sits relative to
its own recent range, and those relationships hold on average, not in any individual case.
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

# Last, so every setting changed during this run is saved in one go.
browser_store.flush()
