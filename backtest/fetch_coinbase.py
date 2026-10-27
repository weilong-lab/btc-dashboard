"""下载 Coinbase BTC-USD 和 USDT-USD 的历史 K 线，用来回测「Coinbase 溢价」。

- 1 小时：BTC-USD 2020-01 起；USDT-USD 从上线起（2021 年）
- 5 分钟：最近 400 天（看更短周期）

Coinbase 公开接口每次最多 300 根，按时间倒着一段段取；已下载的部分会跳过，可重复运行。
用法：.venv/bin/python fetch_coinbase.py
输出：data/coinbase_<产品>_<周期>.csv（time_ms, open, high, low, close, volume）
"""
import csv
import json
import os
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
API = "https://api.exchange.coinbase.com/products/{p}/candles?granularity={g}&start={s}&end={e}"
UA = {"User-Agent": "btc-research/1.0"}
START_1H = 1577836800          # 2020-01-01 UTC（秒）


def get(url):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + 2 * attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 + 3 * attempt)
    raise RuntimeError("下载失败：" + url)


def fetch(product, gran, start):
    out = os.path.join(DATA, f"coinbase_{product}_{gran // 60}m.csv")
    have = {}
    if os.path.exists(out):
        with open(out) as f:
            for r in csv.DictReader(f):
                have[int(r["time_ms"])] = r
    now = int(time.time()) // gran * gran
    # 已有数据的最后一根之后才需要补；第一次运行从 start 开始
    lo = max(start, (max(have) // 1000 + gran) if have else start)
    span, n, empty = 300 * gran, 0, 0
    e = now
    while e > lo:
        s = max(lo, e - span)
        rows = get(API.format(p=product, g=gran, s=s, e=e - 1))
        n += 1
        for t, low, high, op, cl, vol in rows:
            have[t * 1000] = {"time_ms": t * 1000, "open": op, "high": high, "low": low, "close": cl, "volume": vol}
        # 产品还没上线时会连续返回空，连着空 20 段就停
        empty = empty + 1 if not rows else 0
        if empty >= 20:
            break
        e = s
        time.sleep(0.15)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time_ms", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for t in sorted(have):
            w.writerow(have[t])
    print(f"{product} {gran // 60}m：{len(have)} 根（本次请求 {n} 次）→ {os.path.relpath(out, HERE)}")


if __name__ == "__main__":
    fetch("BTC-USD", 3600, START_1H)
    fetch("USDT-USD", 3600, START_1H)
    five = int(time.time()) - 400 * 86400
    fetch("BTC-USD", 300, five)
    fetch("USDT-USD", 300, five)
