"""Download Binance USDT-M BTCUSDT perpetual klines into data/*.csv.

Usage: python fetch_data.py [days]   (default 365)
Re-running only fetches bars newer than what is already on disk.
"""
import csv
import json
import os
import sys
import time
import urllib.request

BASE = "https://fapi.binance.com/fapi/v1/klines"
SYMBOL = "BTCUSDT"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
STEP_MS = {"5m": 300_000}


def fetch(interval, start_ms, end_ms):
    rows = []
    cur = start_ms
    while cur < end_ms:
        url = f"{BASE}?symbol={SYMBOL}&interval={interval}&startTime={cur}&limit=1500"
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    batch = json.load(r)
                break
            except Exception as e:  # network hiccup or rate limit
                print("retry", attempt, e)
                time.sleep(2 + attempt * 3)
        else:
            raise RuntimeError("download failed at " + str(cur))
        if not batch:
            break
        rows.extend(batch)
        cur = batch[-1][0] + STEP_MS[interval]
        time.sleep(0.15)
    return [r for r in rows if r[0] < end_ms]


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 365
    os.makedirs(DATA, exist_ok=True)
    interval = "5m"
    path = os.path.join(DATA, f"{SYMBOL}_{interval}.csv")
    end_ms = int(time.time() * 1000) // STEP_MS[interval] * STEP_MS[interval]
    start_ms = end_ms - days * 86_400_000
    existing = []
    if os.path.exists(path):
        with open(path) as f:
            existing = list(csv.reader(f))[1:]
        if existing:
            start_ms = max(start_ms, int(existing[-1][0]) + STEP_MS[interval])
    new = fetch(interval, start_ms, end_ms)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"])
        for r in existing:
            w.writerow(r)
        for r in new:
            w.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[9]])
    print(f"{path}: {len(existing)} existing + {len(new)} new bars")


if __name__ == "__main__":
    main()
