"""Which tickers a visitor watches: picked from the shared universe, plus their own.

The universe (data/universe.csv) is what the daily record job covers, so every
ticker in it has analyst figures and event dates. A visitor may add any other
symbol too; those extras get prices, signals and, for US listings, a live earnings
date, but no analyst targets or dividend dates. The choice is saved in the browser.
"""
import re

import browser_store
from engine import DEFAULT_TICKERS, load_universe

# Yahoo symbols: letters and digits, with "." for an exchange suffix (VUAA.L), "-"
# for a share class (BRK-B), "^" for an index and "=" for currencies and futures.
SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=]{0,14}$")
# Every ticker is a download and a row; past this the table gets slow to load.
MAX_TICKERS = 40
COOKIE = "watchlist"


def universe():
    """{ticker: row} for the shared list, in file order."""
    return {row["ticker"]: row for row in load_universe() if row.get("ticker")}


def normalise(values):
    """(valid tickers, rejected inputs): upper-cased, de-duplicated, order kept."""
    valid, rejected, seen = [], [], set()
    for value in values or []:
        symbol = str(value).strip().upper()
        if not symbol or symbol in seen:
            continue
        if SYMBOL.match(symbol):
            valid.append(symbol)
            seen.add(symbol)
        else:
            rejected.append(str(value).strip())
    return valid[:MAX_TICKERS], rejected


def saved_or_default():
    """The list saved in this browser, or the default watchlist for a first visit."""
    saved = browser_store.read(COOKIE)
    if isinstance(saved, list):
        valid, _ = normalise(saved)
        if valid:
            return valid
    return list(DEFAULT_TICKERS)


def save(tickers):
    browser_store.write(COOKIE, list(tickers))


def extras(tickers, shared=None):
    """Tickers outside the shared universe, which the daily job does not cover."""
    shared = universe() if shared is None else shared
    return [t for t in tickers if t not in shared]


def label(ticker, shared):
    row = shared.get(ticker)
    return f"{ticker} · {row['name']}" if row and row.get("name") else ticker
