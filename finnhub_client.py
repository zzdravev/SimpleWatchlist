"""Live company details from Finnhub for the ticker panel.

Unlike Yahoo's quote endpoint, Finnhub answers Streamlit Cloud, so these are fetched
when a row is opened rather than collected in CI: one ticker at a time, five calls,
cached so reopening a row costs nothing. The free tier covers US listings only; a
symbol like VUAA.L gets None everywhere and the panel shows what it can without it.

The key comes from Streamlit secrets or the environment, as FINNHUB_API_KEY. Without
one every function returns None and configured() says why.
"""
import os
from datetime import timedelta

import requests
import streamlit as st

from engine import market_today

API = "https://finnhub.io/api/v1"
TIMEOUT_SECONDS = 10


def _key():
    try:
        key = st.secrets.get("FINNHUB_API_KEY")
    except Exception:  # no secrets file at all
        key = None
    return (key or os.environ.get("FINNHUB_API_KEY") or "").strip()


def configured():
    return bool(_key())


def symbol_for(ticker):
    """Finnhub spelling of a Yahoo symbol, or None for a listing the free tier refuses.

    Yahoo marks share classes with a dash (BRK-B) where Finnhub uses a dot, and
    non-US listings with an exchange suffix (VUAA.L).
    """
    if "." in ticker:
        return None
    return ticker.replace("-", ".")


class _Unavailable(Exception):
    """A failure worth retrying: network trouble, a rate limit or a server error.

    Raised inside the cached functions so that st.cache_data, which never caches an
    exception, does not keep a transient failure for hours.
    """


def _get(path, **params):
    """Parsed JSON, or None when the answer is a lasting no (no key, no access)."""
    key = _key()
    if not key:
        return None
    try:
        # The key goes in a header so it never appears in a URL or an error message.
        response = requests.get(f"{API}/{path}", params=params,
                                headers={"X-Finnhub-Token": key}, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise _Unavailable(type(e).__name__) from None
    if response.status_code in (401, 403, 404):
        return None
    if response.status_code != 200:
        raise _Unavailable(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise _Unavailable("invalid JSON") from None


def _safe(fetch):
    """Wrap a cached fetch so callers get None instead of an exception."""
    def call(*args, **kwargs):
        try:
            return fetch(*args, **kwargs)
        except _Unavailable:
            return None
    call.__doc__ = fetch.__doc__
    return call


@st.cache_data(ttl=timedelta(hours=12), show_spinner=False)
def _profile(ticker):
    """Name, industry, exchange, market cap (in millions), logo and website."""
    symbol = symbol_for(ticker)
    data = _get("stock/profile2", symbol=symbol) if symbol else None
    return data or None


@st.cache_data(ttl=timedelta(hours=6), show_spinner=False)
def _metrics(ticker):
    """Finnhub's basic financials: P/E, beta, dividend yield, growth and the like."""
    symbol = symbol_for(ticker)
    data = _get("stock/metric", symbol=symbol, metric="all") if symbol else None
    return (data or {}).get("metric") or None


@st.cache_data(ttl=timedelta(hours=6), show_spinner=False)
def _earnings_history(ticker):
    """The last four reported quarters, newest first, with estimate and surprise."""
    symbol = symbol_for(ticker)
    data = _get("stock/earnings", symbol=symbol, limit=4) if symbol else None
    return data or None


@st.cache_data(ttl=timedelta(hours=6), show_spinner=False)
def _recommendations(ticker):
    """Monthly analyst rating counts, newest first."""
    symbol = symbol_for(ticker)
    data = _get("stock/recommendation", symbol=symbol) if symbol else None
    return data or None


@st.cache_data(ttl=timedelta(minutes=30), show_spinner=False)
def _news(ticker, days=7, limit=6):
    """Recent company headlines, newest first, one per distinct headline."""
    symbol = symbol_for(ticker)
    if not symbol:
        return None
    today = market_today()
    data = _get("company-news", symbol=symbol,
                **{"from": (today - timedelta(days=days)).isoformat(), "to": today.isoformat()})
    if not data:
        return None
    seen, items = set(), []
    # Syndicated stories repeat under the same headline; keep the first of each.
    for item in sorted(data, key=lambda n: n.get("datetime", 0), reverse=True):
        headline = (item.get("headline") or "").strip()
        if not headline or headline in seen or not item.get("url"):
            continue
        seen.add(headline)
        items.append(item)
        if len(items) == limit:
            break
    return items or None


profile = _safe(_profile)
metrics = _safe(_metrics)
earnings_history = _safe(_earnings_history)
recommendations = _safe(_recommendations)
news = _safe(_news)


@st.cache_data(ttl=timedelta(hours=6), show_spinner=False)
def _next_earnings(ticker, horizon_days=120):
    """The next earnings date as an event entry in the daily record's shape."""
    symbol = symbol_for(ticker)
    if not symbol:
        return None
    today = market_today()
    data = _get("calendar/earnings", symbol=symbol, **{
        "from": today.isoformat(), "to": (today + timedelta(days=horizon_days)).isoformat()})
    rows = sorted((r for r in (data or {}).get("earningsCalendar") or []
                   if r.get("date", "") >= today.isoformat()), key=lambda r: r["date"])
    if not rows:
        return None
    row = rows[0]
    earnings = {"date": row["date"], "confirmed": False, "yahoo": None, "finnhub": row["date"]}
    for source, field in (("epsEstimate", "eps_estimate"), ("revenueEstimate", "revenue_estimate")):
        if row.get(source) is not None:
            earnings[field] = row[source]
    return {"earnings": earnings}


next_earnings = _safe(_next_earnings)
