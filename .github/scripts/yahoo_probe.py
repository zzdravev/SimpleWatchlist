"""Probe: does Yahoo keep answering its authenticated endpoint from a CI runner?

A single successful call proves little. The real job would request the whole
watchlist, in parallel, and possibly more than once in a session. quoteSummary
needs a cookie and crumb, and Yahoo throttles both by volume and by repetition,
so this measures a realistic load rather than one lucky request.

Delete this once the question is settled.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import yfinance as yf

TICKERS = ["NVDA", "VUAA.L", "KO", "JNJ", "O", "META", "GOOGL", "MSFT",
           "TSLA", "AAPL", "AMZN", "JPM", "AVGO", "CVX"]
PAUSE_SECONDS = 30


def fetch(ticker):
    """True when Yahoo actually answered: every valid symbol carries marketState."""
    try:
        return bool(yf.Ticker(ticker).info.get("marketState"))
    except Exception:
        return False


def run_round(label, parallel):
    started = time.monotonic()
    if parallel:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(fetch, TICKERS))
    else:
        results = [fetch(t) for t in TICKERS]
    ok = sum(results)
    failed = [t for t, good in zip(TICKERS, results) if not good]
    print(f"{label:<28} {ok:>2}/{len(TICKERS)} ok   {time.monotonic() - started:5.1f}s"
          + (f"   missed: {', '.join(failed)}" if failed else ""))
    return ok


print("probe run (UTC):", datetime.now(timezone.utc).isoformat(timespec="seconds"))
print(f"watchlist size: {len(TICKERS)}\n")

scores = []
scores.append(("sequential, round 1", run_round("sequential, round 1", parallel=False)))

for round_number in (1, 2, 3):
    time.sleep(PAUSE_SECONDS)
    label = f"parallel x8, round {round_number}"
    scores.append((label, run_round(label, parallel=True)))

total = sum(s for _, s in scores)
expected = len(scores) * len(TICKERS)
print(f"\nTOTAL: {total}/{expected} successful quoteSummary calls "
      f"across {len(scores)} rounds ({PAUSE_SECONDS}s apart)")
print("VERDICT:", "STABLE UNDER LOAD" if total == expected
      else "DEGRADES UNDER LOAD" if total > 0 else "BLOCKED")
