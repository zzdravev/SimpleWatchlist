"""The detail panel shown under the table when its ticker is clicked.

Price history comes from the download the table already made, so the chart and the
returns work everywhere. Company details, earnings history, analyst trends and news
come live from Finnhub (finnhub_client), which covers US listings on the free tier.
Upcoming events come from the daily record.
"""
from datetime import date
from urllib.parse import quote

import altair as alt
import pandas as pd
import streamlit as st

import finnhub_client

# Reference palette, validated for colour-vision deficiency on both surfaces:
# slot 1 for the price, slot 2 for the trend line.
PRICE_COLOR = "#2a78d6"
TREND_COLOR = "#eb6834"
LEVEL_COLOR = "#8a8984"


def short_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d %b")
    except ValueError:
        return "an earlier run"


def format_money(value):
    if not isinstance(value, (int, float)):
        return None
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(value) >= size:
            return f"${value / size:.1f}{suffix}"
    return f"${value:,.0f}"


def render_events(events, today, generated):
    """Every known upcoming date for one ticker."""
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
                hour = {"bmo": "before the open", "amc": "after the close",
                        "during": "during market hours"}.get(event.get("hour"))
                if hour:
                    details.append(hour)
            else:
                status = "Estimated"
                if event.get("latest"):
                    details.append(f"window to {date.fromisoformat(event['latest']).strftime('%d %b')}")
            sources = [f"{src} {date.fromisoformat(event[key]).strftime('%d %b')}"
                       for src, key in (("Yahoo", "yahoo"), ("Finnhub", "finnhub")) if event.get(key)]
            if event.get("finnhub") and not event.get("yahoo"):
                details.append("from Finnhub only, whose dates often run a day early")
            # A one-day gap is Finnhub running early, not a real disagreement.
            if len(sources) == 2 and abs((date.fromisoformat(event["yahoo"])
                                          - date.fromisoformat(event["finnhub"])).days) > 1:
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




def _pct(value, signed=True):
    if not isinstance(value, (int, float)) or pd.isna(value):
        return "N/A"
    return f"{value:+.1f}%" if signed else f"{value:.1f}%"


def _num(value, digits=2):
    if not isinstance(value, (int, float)) or pd.isna(value):
        return "N/A"
    return f"{value:.{digits}f}"


def _calendar_quarter(period):
    """'2026-09-30' -> 'Q3 2026': the calendar quarter Finnhub files the report under."""
    try:
        d = date.fromisoformat(str(period)[:10])
    except ValueError:
        return "N/A"
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


def external_links(ticker, profile):
    """Yahoo Finance, TradingView and the company's own site."""
    links = [f"[Yahoo Finance](https://finance.yahoo.com/quote/{quote(ticker)})"]
    exchange = (profile or {}).get("exchange", "").upper()
    if ticker.endswith(".L"):
        tv_symbol = "LSE:" + ticker[:-2]
    elif "NASDAQ" in exchange:
        tv_symbol = "NASDAQ:" + ticker.replace("-", ".")
    elif "NEW YORK" in exchange:
        tv_symbol = "NYSE:" + ticker.replace("-", ".")
    else:
        tv_symbol = ticker.replace("-", ".")
    links.append(f"[TradingView](https://www.tradingview.com/chart/?symbol={quote(tv_symbol)})")
    website = (profile or {}).get("weburl")
    if website and website.startswith(("https://", "http://")):
        links.append(f"[Company website]({website})")
    return " · ".join(links)


def returns(history):
    """Price changes over standard windows, from the year of daily closes."""
    close = history["Close"].dropna()
    if close.empty:
        return {}
    last = close.iloc[-1]

    def change_since(position):
        if len(close) <= position:
            return None
        return (last / close.iloc[-1 - position] - 1) * 100

    this_year = close[close.index.year == close.index[-1].year]
    start_of_year = close[close.index.year < close.index[-1].year]
    ytd_base = start_of_year.iloc[-1] if not start_of_year.empty else this_year.iloc[0]
    high = history["High"].max()
    low = history["Low"].min()
    return {
        "1M": change_since(21),
        "3M": change_since(63),
        "YTD": (last / ytd_base - 1) * 100,
        "1Y": (last / close.iloc[0] - 1) * 100,
        "from_high": (last / high - 1) * 100,
        "high": high,
        "low": low,
        # Where the price sits in its 52-week range, 0 at the low and 100 at the high.
        "range_position": (last - low) / (high - low) * 100 if high > low else None,
    }


def price_chart(history, mod_dip, strong_dip):
    """A year of closes with the Bollinger band, the 200-day average and the dip levels."""
    data = history.reset_index().rename(columns={history.index.name or "index": "Date"})
    data = data.rename(columns={data.columns[0]: "Date"})
    base = alt.Chart(data).encode(x=alt.X("Date:T", title=None, axis=alt.Axis(format="%b", grid=False,
                                                                       tickCount={"interval": "month", "step": 1})))
    y_scale = alt.Scale(zero=False)

    band = base.mark_area(color=LEVEL_COLOR, opacity=0.15).encode(
        y=alt.Y("Lower:Q", scale=y_scale, title=None), y2="Upper:Q")
    lines = base.transform_fold(["Close", "SMA200"], as_=["Series", "Value"]).transform_calculate(
        Series="datum.Series === 'Close' ? 'Close' : '200-day average'"
    ).mark_line(strokeWidth=2).encode(
        y=alt.Y("Value:Q", scale=y_scale),
        color=alt.Color("Series:N", scale=alt.Scale(domain=["Close", "200-day average"],
                                                    range=[PRICE_COLOR, TREND_COLOR]),
                        legend=alt.Legend(orient="top", title=None)),
        strokeDash=alt.StrokeDash("Series:N", scale=alt.Scale(domain=["Close", "200-day average"],
                                                              range=[[1, 0], [6, 4]]), legend=None),
    )

    layers = [band, lines]
    levels = pd.DataFrame([{"Level": "Mod Dip", "Price": mod_dip}, {"Level": "Strong Dip", "Price": strong_dip}])
    levels = levels.dropna()
    if not levels.empty:
        levels["Label"] = levels["Level"] + " " + levels["Price"].map(lambda v: f"{v:.2f}")
        rules = alt.Chart(levels).mark_rule(color=LEVEL_COLOR, strokeDash=[2, 3], strokeWidth=1).encode(y="Price:Q")
        # Mod Dip is always the higher level: label it above its line and Strong Dip
        # below its own, so the two never collide however close they sit.
        layers.append(rules)
        for level, offset in (("Mod Dip", -6), ("Strong Dip", 11)):
            subset = levels[levels["Level"] == level]
            if not subset.empty:
                layers.append(alt.Chart(subset).mark_text(
                    align="left", dx=4, dy=offset, color="#52514e", fontSize=11,
                ).encode(y="Price:Q", x=alt.value(0), text="Label:N"))

    # Hover: the nearest day gets a vertical rule and a tooltip with every value.
    hover = alt.selection_point(fields=["Date"], nearest=True, on="pointerover", empty=False)
    tooltip = [alt.Tooltip("Date:T", format="%a %d %b %Y"), alt.Tooltip("Close:Q", format=".2f"),
               alt.Tooltip("Upper:Q", title="Upper band", format=".2f"),
               alt.Tooltip("Lower:Q", title="Lower band", format=".2f"),
               alt.Tooltip("SMA200:Q", title="200-day average", format=".2f")]
    layers.append(base.mark_rule(color=LEVEL_COLOR).encode(
        opacity=alt.condition(hover, alt.value(0.6), alt.value(0)), tooltip=tooltip).add_params(hover))
    layers.append(base.mark_point(color=PRICE_COLOR, size=60, filled=True).encode(
        y=alt.Y("Close:Q", scale=y_scale), opacity=alt.condition(hover, alt.value(1), alt.value(0))))
    return alt.layer(*layers).properties(height=320)


def render_overview(ticker, row, history):
    stats = returns(history) if history is not None else {}
    cols = st.columns(6)
    cols[0].metric("Price", _num(row.get("Price")))
    cols[1].metric("1 month", _pct(stats.get("1M")))
    cols[2].metric("3 months", _pct(stats.get("3M")))
    cols[3].metric("Year to date", _pct(stats.get("YTD")))
    cols[4].metric("1 year", _pct(stats.get("1Y")))
    cols[5].metric("From 52-week high", _pct(stats.get("from_high")),
                   help=f"52-week range {_num(stats.get('low'))} to {_num(stats.get('high'))}.")
    if history is None:
        st.caption("Refresh the table to load the price chart.")
        return
    st.altair_chart(price_chart(history, row.get("Mod Dip"), row.get("Strong Dip")), width="stretch")
    st.caption(
        "Grey band: Bollinger bands (20, 2). Dotted lines: the current Mod Dip and Strong Dip "
        "levels. A close below the dashed 200-day average is what the ↓ marker means."
    )


def render_fundamentals(ticker):
    metrics = finnhub_client.metrics(ticker)
    history = finnhub_client.earnings_history(ticker)
    trend = finnhub_client.recommendations(ticker)
    if not (metrics or history or trend):
        st.caption("No company data for this listing: Finnhub's free tier covers US stocks only.")
        return

    left, right = st.columns(2)
    with left:
        st.markdown("**Valuation and risk**")
        m = metrics or {}
        rows = [
            ("P/E (trailing)", _num(m.get("peTTM"), 1)),
            ("P/E (forward)", _num(m.get("forwardPE"), 1)),
            ("Price / sales", _num(m.get("psTTM"), 1)),
            ("Dividend yield", _pct(m.get("currentDividendYieldTTM"), signed=False)),
            ("Beta", _num(m.get("beta"))),
            ("EPS growth, year on year", _pct(m.get("epsGrowthTTMYoy"))),
            ("Revenue growth, year on year", _pct(m.get("revenueGrowthTTMYoy"))),
            ("Net margin", _pct(m.get("netProfitMarginTTM"), signed=False)),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Measure", "Value"]), hide_index=True, width="stretch")
    with right:
        st.markdown("**Last four reports**")
        if history:
            rows = [{
                "Quarter": _calendar_quarter(h.get("period")),
                "Fiscal": f"FQ{h.get('quarter')} {h.get('year')}",
                "EPS estimate": _num(h.get("estimate")),
                "EPS actual": _num(h.get("actual")),
                "Surprise": _pct(h.get("surprisePercent")),
            } for h in history[:4]]
            table = pd.DataFrame(rows)
            # Finnhub's year and quarter are the company's fiscal ones (NVIDIA's FY2027
            # is mostly calendar 2026); show them only where they differ from the calendar.
            if all(r["Fiscal"] == "F" + r["Quarter"] for r in rows):
                table = table.drop(columns="Fiscal")
            st.dataframe(table, hide_index=True, width="stretch")
        else:
            st.caption("No earnings history.")

        st.markdown("**Analyst ratings**")
        if trend:
            latest = trend[0]
            parts = [f"{label} {latest.get(key, 0)}" for key, label in
                     (("strongBuy", "Strong buy"), ("buy", "Buy"), ("hold", "Hold"),
                      ("sell", "Sell"), ("strongSell", "Strong sell"))]
            st.write(" · ".join(parts))
            if len(trend) >= 4:
                def bullish(entry):
                    return entry.get("strongBuy", 0) + entry.get("buy", 0)
                change = bullish(latest) - bullish(trend[3])
                st.caption(f"As of {latest.get('period')}. Buy ratings {change:+d} against three months earlier.")
        else:
            st.caption("No analyst ratings.")


def render_news(ticker):
    items = finnhub_client.news(ticker)
    if not items:
        st.caption("No headlines in the last seven days, or none available for this listing.")
        return
    for item in items:
        when = pd.Timestamp(item.get("datetime", 0), unit="s", tz="UTC").tz_convert("America/New_York")
        headline = item["headline"].replace("[", "(").replace("]", ")")
        st.markdown(f"[{headline}]({item['url']})  \n"
                    f"<small>{item.get('source', '')} · {when.strftime('%d %b, %H:%M')} ET</small>",
                    unsafe_allow_html=True)
    st.caption("Headlines from Finnhub. Links open the original article.")


def render(ticker, row, history, events, today, generated, name=None, actions=None):
    """The whole panel for one selected ticker.

    actions, if given, draws the panel's buttons at the right of the heading.
    """
    profile = finnhub_client.profile(ticker)
    title = (profile or {}).get("name") or name or ""
    heading = f"##### {ticker}{' · ' + title if title else ''}"
    logo = (profile or {}).get("logo")
    has_logo = bool(logo and logo.startswith("https://"))
    widths = ([1] if has_logo else []) + ([11, 3] if actions else [14])
    cols = st.columns(widths, vertical_alignment="center")
    if has_logo:
        cols.pop(0).image(logo, width=40)
    cols[0].markdown(heading)
    if actions:
        with cols[1]:
            with st.container(horizontal=True, horizontal_alignment="right"):
                actions()

    facts = []
    if profile:
        if profile.get("finnhubIndustry"):
            facts.append(profile["finnhubIndustry"])
        cap = profile.get("marketCapitalization")
        if isinstance(cap, (int, float)) and cap > 0:
            facts.append("market cap " + format_money(cap * 1e6))
    facts.append(external_links(ticker, profile))
    st.markdown(" · ".join(facts))
    if not finnhub_client.configured():
        st.caption("Company details need a FINNHUB_API_KEY in the app's secrets.")

    render_overview(ticker, row, history)
    events_tab, fundamentals_tab, news_tab = st.tabs(["Upcoming events", "Fundamentals and analysts", "News"])
    with events_tab:
        render_events(events, today, generated)
    with fundamentals_tab:
        render_fundamentals(ticker)
    with news_tab:
        render_news(ticker)
