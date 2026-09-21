"""One-off probe: does Yahoo answer its authenticated endpoint from a CI runner?

The chart endpoint behind prices needs no handshake and is expected to work
anywhere. quoteSummary, which carries analyst targets and market state, needs a
cookie and crumb, and Yahoo restricts that from datacenter addresses. This
decides whether a scheduled job can collect that data or whether it has to run
somewhere else. Delete this once the question is settled.
"""

from datetime import datetime, timezone

import yfinance as yf

TICKERS = ["NVDA", "AAPL", "KO"]

print("probe run (UTC):", datetime.now(timezone.utc).isoformat(timespec="seconds"))

print("\n--- chart endpoint: prices and indicators ---")
try:
    history = yf.download(TICKERS, period="5d", interval="1d", group_by="ticker",
                          auto_adjust=True, progress=False)
    print(f"rows={len(history)} columns={len(history.columns)}")
    print("RESULT: chart endpoint OK" if len(history) else "RESULT: chart endpoint EMPTY")
except Exception as e:
    print(f"RESULT: chart endpoint FAILED {type(e).__name__}: {e}")

print("\n--- quoteSummary: market state and analyst data ---")
reached = 0
for ticker in TICKERS:
    try:
        info = yf.Ticker(ticker).info
        state = info.get("marketState")
        print(f"{ticker}: keys={len(info)} marketState={state!r} "
              f"targetMedianPrice={info.get('targetMedianPrice')!r} "
              f"analysts={info.get('numberOfAnalystOpinions')!r}")
        if state:
            reached += 1
    except Exception as e:
        print(f"{ticker}: EXCEPTION {type(e).__name__}: {e}")

print(f"\nRESULT: quoteSummary reachable for {reached}/{len(TICKERS)} tickers")
print("VERDICT:", "USABLE FROM CI" if reached == len(TICKERS) else "BLOCKED FROM CI")
