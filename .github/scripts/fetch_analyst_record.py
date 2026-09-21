"""Collect the slow-moving analyst figures for the watchlist and store them.

Yahoo refuses its authenticated quote endpoint from Streamlit Cloud but answers
it from a CI runner, so this runs on a schedule and writes what the app cannot
fetch for itself. Only fields that change on the order of days are recorded:
market state and extended-hours prices are live values, and a day-old copy of
them would mislead rather than merely age.

Keys match yfinance's .info so the app can merge the record straight over a
refused response.
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yfinance as yf  # noqa: E402

from engine import DEFAULT_TICKERS, RECORD_PATH  # noqa: E402

FIELDS = ["targetMedianPrice", "targetMeanPrice", "targetLowPrice", "targetHighPrice",
          "numberOfAnalystOpinions", "recommendationKey"]


def fetch(ticker):
    """None when Yahoo refused. An empty dict means it answered but the ticker has
    no analyst coverage, which is normal for an ETF and not a failure."""
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        print(f"{ticker}: {type(e).__name__}: {e}")
        return ticker, None

    if not info.get("marketState"):
        print(f"{ticker}: refused, no marketState in response")
        return ticker, None

    entry = {field: info[field] for field in FIELDS if info.get(field) is not None}
    print(f"{ticker}: {len(entry)} fields")
    return ticker, entry


def main():
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(pool.map(fetch, DEFAULT_TICKERS))

    answered = sorted(t for t, entry in results.items() if entry is not None)
    collected = {t: entry for t, entry in results.items() if entry}

    # An empty result means Yahoo refused everything; keeping the previous record
    # is better than replacing good data with nothing.
    if not collected:
        print("\nFAILED: no ticker returned analyst data, leaving the record untouched")
        return 1

    RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECORD_PATH.write_text(
        json.dumps(
            {
                "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                # Everything Yahoo answered for, so the app can tell "no analyst
                # coverage" apart from "never looked at".
                "checked": answered,
                "tickers": collected,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    missing = sorted(set(DEFAULT_TICKERS) - set(collected))
    print(f"\nwrote {RECORD_PATH.relative_to(ROOT)} for {len(collected)}/{len(DEFAULT_TICKERS)} tickers")
    if missing:
        print("no analyst data for:", ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
