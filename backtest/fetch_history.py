"""下载 BTC 全部历史数据。

- 币安现货 BTCUSDT 1 分钟：2017-08 → 上个月（data.binance.vision 月度包，校验 SHA256），本月用 REST 补齐
- 币安 U 本位永续 BTCUSDT 1 分钟：上线月 → 上个月，本月用 REST 补齐
- 资金费率：永续上线至今（REST）
- Bitstamp BTC/USD 1 小时：2011-08 → 2017-08（币安之前的历史）

用法：.venv/bin/python fetch_history.py        可重复运行，已下载的月份会跳过
输出：data/history/ 下的原始 zip，以及合并后的
      data/BTCUSDT_spot_1m.csv.gz、data/BTCUSDT_perp_1m.csv.gz、data/BTCUSDT_funding_all.csv、data/BTCUSD_bitstamp_1h.csv
"""
import csv
import gzip
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
HIST = os.path.join(DATA, "history")
VISION = "https://data.binance.vision/data"
UA = {"User-Agent": "Mozilla/5.0 btc-research"}
COLS = ["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"]


def get(url, timeout=60):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 + 3 * attempt)
        except Exception:
            time.sleep(2 + 3 * attempt)
    raise RuntimeError("下载失败: " + url)


def months(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def vision_month(market, y, m):
    """market: 'spot' 或 'futures/um'。返回本地 zip 路径，或 None（该月不存在）。"""
    name = f"BTCUSDT-1m-{y}-{m:02d}.zip"
    folder = os.path.join(HIST, market.replace("/", "_"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    if os.path.exists(path):
        return path
    base = f"{VISION}/{market}/monthly/klines/BTCUSDT/1m/{name}"
    blob = get(base)
    if blob is None:
        return None
    chk = get(base + ".CHECKSUM")
    if chk and chk.split()[0].decode() != hashlib.sha256(blob).hexdigest():
        raise RuntimeError("校验失败: " + name)
    with open(path, "wb") as f:
        f.write(blob)
    return path


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        raw = z.read(z.namelist()[0]).decode()
    for line in raw.splitlines():
        p = line.split(",")
        if not p[0].isdigit():
            continue  # 表头
        t = int(p[0])
        if t > 1e14:  # 2025 年起现货包改为微秒
            t //= 1000
        yield [t, p[1], p[2], p[3], p[4], p[5], p[9]]


def rest_tail(base_url, start_ms, limit):
    rows, cur = [], start_ms
    end = int(time.time() * 1000) // 60000 * 60000
    while cur < end:
        b = json.loads(get(f"{base_url}&startTime={cur}&limit={limit}"))
        if not b:
            break
        rows += [[r[0], r[1], r[2], r[3], r[4], r[5], r[9]] for r in b if r[0] < end]
        cur = b[-1][0] + 60000
        time.sleep(0.12)
    return rows


def build(market, first, rest_base, rest_limit, out_name):
    today = date.today()
    last_full = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    zips = []
    for y, m in months(first, last_full):
        p = vision_month(market, y, m)
        print(f"  {market} {y}-{m:02d}: {'ok' if p else '无数据'}", flush=True)
        if p:
            zips.append(p)
    out = os.path.join(DATA, out_name)
    n, last_t = 0, 0
    with gzip.open(out, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for p in zips:
            for r in read_zip(p):
                if r[0] > last_t:
                    w.writerow(r); n += 1; last_t = r[0]
        for r in rest_tail(rest_base, last_t + 60000, rest_limit):
            if r[0] > last_t:
                w.writerow(r); n += 1; last_t = r[0]
    print(f"{out_name}: {n:,} 根，截至 {datetime.fromtimestamp(last_t/1000, timezone.utc)}", flush=True)


def funding_all():
    rows, cur = [], int(datetime(2019, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
    while True:
        b = json.loads(get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime={cur}&limit=1000"))
        if not b:
            break
        rows += b
        cur = b[-1]["fundingTime"] + 1
        if len(b) < 1000:
            break
        time.sleep(0.2)
    with open(os.path.join(DATA, "BTCUSDT_funding_all.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["funding_time", "funding_rate"])
        for r in rows:
            w.writerow([r["fundingTime"], r["fundingRate"]])
    print(f"资金费率: {len(rows):,} 条", flush=True)


def bitstamp():
    rows, cur = [], int(datetime(2011, 8, 18, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2017, 8, 17, tzinfo=timezone.utc).timestamp())
    while cur < end:
        b = json.loads(get(f"https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=3600&limit=1000&start={cur}"))["data"]["ohlc"]
        if not b:
            break
        rows += [r for r in b if int(r["timestamp"]) < end]
        cur = int(b[-1]["timestamp"]) + 3600
        time.sleep(0.3)
    with open(os.path.join(DATA, "BTCUSD_bitstamp_1h.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["open_time", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow([int(r["timestamp"]) * 1000, r["open"], r["high"], r["low"], r["close"], r["volume"]])
    print(f"Bitstamp 1h: {len(rows):,} 根", flush=True)


def main():
    os.makedirs(HIST, exist_ok=True)
    print("== 资金费率 ==", flush=True); funding_all()
    print("== Bitstamp 2011–2017 ==", flush=True); bitstamp()
    print("== 币安永续 1m ==", flush=True)
    build("futures/um", (2019, 9), "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m", 1500, "BTCUSDT_perp_1m.csv.gz")
    print("== 币安现货 1m ==", flush=True)
    build("spot", (2017, 8), "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m", 1000, "BTCUSDT_spot_1m.csv.gz")
    print("全部完成", flush=True)


if __name__ == "__main__":
    main()
