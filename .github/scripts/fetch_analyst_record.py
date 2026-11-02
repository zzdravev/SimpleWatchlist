"""Collect the slow-moving analyst figures and upcoming events, and store them.

Yahoo refuses its authenticated quote endpoint from Streamlit Cloud but answers
it from a CI runner, so this runs on a schedule and writes what the app cannot
fetch for itself. Only fields that change on the order of days are recorded:
market state and extended-hours prices are live values, and a day-old copy of
them would mislead rather than merely age.

Covers every ticker in data/universe.csv plus the default watchlist, since any of
them can be on someone's screen.

Analyst keys match yfinance's .info so the app can merge the record straight over
a refused response. Events (next earnings, ex-dividend and payment dates) sit
under their own key. Earnings dates come from both Yahoo and Finnhub: Yahoo says
whether a date is confirmed, Finnhub adds EPS and revenue estimates, and where
the two disagree on an unconfirmed date the earlier one is kept, so the warning
comes too early rather than too late.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yfinance as yf  # noqa: E402

from engine import DEFAULT_TICKERS, RECORD_PATH, load_universe  # noqa: E402

FIELDS = ["targetMedianPrice", "targetMeanPrice", "targetLowPrice", "targetHighPrice",
          "numberOfAnalystOpinions", "recommendationKey"]

FINNHUB_CALENDAR = "https://finnhub.io/api/v1/calendar/earnings"
# How far ahead to look. The app colours events up to 30 days out and lists later
# ones in the detail panel.
HORIZON_DAYS = 120
# The free tier allows 60 calls a minute; stay just under it.
FINNHUB_SPACING_SECONDS = 1.1


def tickers_to_cover():
    universe = [row["ticker"] for row in load_universe()]
    return sorted(set(universe) | set(DEFAULT_TICKERS))


def _session_part(timestamp, tz_name):
    """"bmo", "amc" or "during" for a report time, or None when Yahoo gives no time.

    Unconfirmed dates are stored at midnight, which says nothing about the hour.
    """
    if not isinstance(timestamp, (int, float)):
        return None
    moment = datetime.fromtimestamp(timestamp, ZoneInfo(tz_name)).time()
    if (moment.hour, moment.minute) == (0, 0):
        return None
    if (moment.hour, moment.minute) < (9, 30):
        return "bmo"
    if moment.hour >= 16:
        return "amc"
    return "during"


def _date_at(timestamp, tz_name):
    """Calendar date of a Yahoo epoch timestamp, or None if it is not a number."""
    if not isinstance(timestamp, (int, float)):
        return None
    return datetime.fromtimestamp(timestamp, ZoneInfo(tz_name)).date()


def yahoo_events(info, today):
    """Upcoming events from a .info response.

    Earnings timestamps carry a real time of day, so they are read in the
    exchange's time zone. Dividend dates are stored as midnight UTC, and reading
    them in New York time would move them a day early.
    """
    tz_name = info.get("exchangeTimezoneName") or "America/New_York"
    events = {}

    start = _date_at(info.get("earningsTimestampStart") or info.get("earningsTimestamp"), tz_name)
    if start and start >= today:
        earnings = {"date": start.isoformat()}
        end = _date_at(info.get("earningsTimestampEnd"), tz_name)
        if end and end != start:
            earnings["latest"] = end.isoformat()
        estimate = info.get("isEarningsDateEstimate")
        if isinstance(estimate, bool):
            earnings["estimated"] = estimate
        if estimate is False:
            hour = _session_part(info.get("earningsTimestampStart") or info.get("earningsTimestamp"),
                                 tz_name)
            if hour:
                earnings["hour"] = hour
        events["earnings"] = earnings

    for field, name in (("exDividendDate", "ex_dividend"), ("dividendDate", "dividend_payment")):
        when = _date_at(info.get(field), "UTC")
        if when and when >= today:
            events[name] = {"date": when.isoformat()}
    return events


def fetch_yahoo(ticker, today):
    """(ticker, analyst entry, events). The entry is None when Yahoo refused; an
    empty dict means it answered but the ticker has no analyst coverage, which is
    normal for an ETF and not a failure."""
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        print(f"{ticker}: {type(e).__name__}: {e}")
        return ticker, None, {}

    if not info.get("marketState"):
        print(f"{ticker}: refused, no marketState in response")
        return ticker, None, {}

    entry = {field: info[field] for field in FIELDS if info.get(field) is not None}
    events = yahoo_events(info, today)
    print(f"{ticker}: {len(entry)} fields, events {events or '-'}")
    return ticker, entry, events


def finnhub_symbol(ticker):
    """Finnhub spelling of a Yahoo symbol, or None for one the free tier does not cover.

    Yahoo marks share classes with a dash (BRK-B) where Finnhub uses a dot, and
    marks non-US listings with an exchange suffix (VUAA.L), which the free tier
    refuses.
    """
    if "." in ticker:
        return None
    return ticker.replace("-", ".")


def fetch_finnhub(ticker, key, today):
    """Next earnings entry from Finnhub, or None. Retries briefly on a rate limit."""
    symbol = finnhub_symbol(ticker)
    if symbol is None:
        return None
    query = urllib.parse.urlencode({
        "symbol": symbol,
        "from": today.isoformat(),
        "to": (today + timedelta(days=HORIZON_DAYS)).isoformat(),
    })
    # The key goes in a header, not the URL, so it cannot end up in an error message.
    request = urllib.request.Request(f"{FINNHUB_CALENDAR}?{query}", headers={"X-Finnhub-Token": key})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                rows = json.load(response).get("earningsCalendar") or []
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            print(f"{ticker}: Finnhub HTTP {e.code}")
            return None
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"{ticker}: Finnhub {type(e).__name__}: {e}")
            return None

    upcoming = sorted((r for r in rows if r.get("date") and r["date"] >= today.isoformat()),
                      key=lambda r: r["date"])
    if not upcoming:
        return None
    row = upcoming[0]
    return {
        "date": row["date"],
        "hour": row.get("hour") or None,
        "eps_estimate": row.get("epsEstimate"),
        "revenue_estimate": row.get("revenueEstimate"),
    }


def _days_apart(first, second):
    """Absolute distance in days between two ISO dates, or None if either is missing."""
    if not first or not second:
        return None
    return abs((date.fromisoformat(first) - date.fromisoformat(second)).days)


def combine_earnings(yahoo, finnhub):
    """One earnings entry from the two sources, keeping both dates for display.

    A date Yahoo marks as confirmed wins, since that comes from the company.
    Otherwise Yahoo's date wins when the two are a day apart: on the first full
    run Finnhub was one day early for 40 tickers, including three dates the
    companies had confirmed and two that fell on a market holiday. A wider gap is
    a real disagreement, and the earlier date is kept so the warning comes early.

    Finnhub's estimates are kept when its date is the same report (within a day).
    The time of day comes from Yahoo's timestamp on a confirmed date only. Finnhub's
    was wrong even on confirmed dates: it gave after-close for Johnson & Johnson,
    which reports before the open.
    """
    if not yahoo and not finnhub:
        return None
    yahoo_date = yahoo.get("date") if yahoo else None
    finnhub_date = finnhub.get("date") if finnhub else None
    confirmed = bool(yahoo) and yahoo.get("estimated") is False

    gap = _days_apart(yahoo_date, finnhub_date)
    if confirmed or (gap is not None and gap <= 1):
        chosen = yahoo_date
    else:
        chosen = min(d for d in (yahoo_date, finnhub_date) if d)

    entry = {"date": chosen, "confirmed": confirmed, "yahoo": yahoo_date, "finnhub": finnhub_date}
    if yahoo and yahoo.get("latest"):
        entry["latest"] = yahoo["latest"]
    if confirmed and yahoo.get("hour"):
        entry["hour"] = yahoo["hour"]
    same_report = _days_apart(finnhub_date, chosen)
    if finnhub and same_report is not None and same_report <= 1:
        for field in ("eps_estimate", "revenue_estimate"):
            if finnhub.get(field) is not None:
                entry[field] = finnhub[field]
    return entry


def main():
    today = datetime.now(ZoneInfo("America/New_York")).date()
    tickers = tickers_to_cover()
    print(f"covering {len(tickers)} tickers, events from {today} for {HORIZON_DAYS} days\n")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda t: fetch_yahoo(t, today), tickers))

    analyst = {t: entry for t, entry, _ in results}
    yahoo_by_ticker = {t: events for t, _, events in results}
    answered = sorted(t for t, entry in analyst.items() if entry is not None)
    collected = {t: entry for t, entry in analyst.items() if entry}

    # An empty result means Yahoo refused everything; keeping the previous record
    # is better than replacing good data with nothing.
    if not collected:
        print("\nFAILED: no ticker returned analyst data, leaving the record untouched")
        return 1

    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    finnhub_by_ticker = {}
    if key:
        print()
        for ticker in tickers:
            if finnhub_symbol(ticker) is None:
                continue
            finnhub_by_ticker[ticker] = fetch_finnhub(ticker, key, today)
            time.sleep(FINNHUB_SPACING_SECONDS)
        found = sum(1 for v in finnhub_by_ticker.values() if v)
        print(f"Finnhub: next earnings for {found}/{len(finnhub_by_ticker)} US tickers")
    else:
        print("\nFINNHUB_API_KEY not set: earnings dates from Yahoo only")

    events = {}
    disagreements = []
    off_by_one = 0
    for ticker in tickers:
        from_yahoo = yahoo_by_ticker.get(ticker, {})
        entry = {name: value for name, value in from_yahoo.items() if name != "earnings"}
        earnings = combine_earnings(from_yahoo.get("earnings"), finnhub_by_ticker.get(ticker))
        if earnings:
            entry["earnings"] = earnings
            gap = _days_apart(earnings["yahoo"], earnings["finnhub"])
            if gap == 1:
                off_by_one += 1
            elif gap:
                disagreements.append(f"{ticker} yahoo {earnings['yahoo']} finnhub {earnings['finnhub']}"
                                     f"{' (confirmed)' if earnings['confirmed'] else ''}")
        if entry:
            events[ticker] = entry

    RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECORD_PATH.write_text(
        json.dumps(
            {
                "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                # Everything Yahoo answered for, so the app can tell "no analyst
                # coverage" apart from "never looked at".
                "checked": answered,
                "tickers": collected,
                "events_from": today.isoformat(),
                "events": events,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    missing = sorted(set(tickers) - set(collected))
    print(f"\nwrote {RECORD_PATH.relative_to(ROOT)}: analyst data for {len(collected)}/{len(tickers)} "
          f"tickers, events for {len(events)}")
    if missing:
        print("no analyst data for:", ", ".join(missing))
    confirmed = sum(1 for e in events.values() if e.get("earnings", {}).get("confirmed"))
    print(f"earnings dates confirmed by Yahoo: {confirmed}")
    print(f"Finnhub one day off Yahoo (Yahoo used): {off_by_one}")
    if disagreements:
        print("sources disagree by more than a day:\n  " + "\n  ".join(disagreements))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
