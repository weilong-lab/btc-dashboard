"""BTC 行情数据来源。

默认（本机）：币安 USDT 永续合约（fapi.binance.com）。
GitHub Actions 的服务器在美国，币安合约和主站接口会返回 451（地区限制），所以云上设
MARKET_SOURCE=cloud：
- K 线：币安公开行情镜像 data-api.binance.vision 的 BTCUSDT 现货（格式和合约 K 线一样，也有主动买入量）。
  现货和永续价格通常只差 0.01%–0.05%，方向模型在现货数据上的样本外准确率和永续相当（2017–19 现货检验 53.3%）。
- 持仓量、资金费率、多空比：OKX 的 BTC-USDT 永续（只看变化幅度，用来做盘面异常提醒）。
面板在浏览器里直接连币安，不受影响。只用标准库。
"""
import json
import os
import urllib.request

SOURCE = os.environ.get("MARKET_SOURCE", "binance")
FAPI = "https://fapi.binance.com"
VISION = "https://data-api.binance.vision"
OKX = "https://www.okx.com"


def _get(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "btc-monitor/1.0"}), timeout=timeout) as r:
        return json.load(r)


def klines(interval, limit=1500, start_ms=None):
    """[[开盘时间, 开, 高, 低, 收, 量, 收盘时间, 成交额, 笔数, 主动买入量, ...], ...]，和币安格式一致。"""
    if SOURCE == "binance":
        url = f"{FAPI}/fapi/v1/klines?symbol=BTCUSDT&interval={interval}&limit={min(limit, 1500)}"
        return _get(url + (f"&startTime={int(start_ms)}" if start_ms is not None else ""))
    base = f"{VISION}/api/v3/klines?symbol=BTCUSDT&interval={interval}"
    if start_ms is not None:
        return _get(f"{base}&limit={min(limit, 1000)}&startTime={int(start_ms)}")
    first = _get(f"{base}&limit={min(limit, 1000)}")
    if limit > 1000 and first:                    # 现货接口一次最多 1000 根：往前再取一次拼起来
        first = _get(f"{base}&limit={limit - len(first)}&endTime={int(first[0][0] - 1)}") + first
    return first


def open_interest():
    """当前持仓量（BTC）。"""
    if SOURCE == "binance":
        return float(_get(f"{FAPI}/fapi/v1/openInterest?symbol=BTCUSDT")["openInterest"])
    return float(_get(f"{OKX}/api/v5/public/open-interest?instId=BTC-USDT-SWAP")["data"][0]["oiCcy"])


def funding_pct():
    """最近一次资金费率（%）。"""
    if SOURCE == "binance":
        return float(_get(f"{FAPI}/fapi/v1/premiumIndex?symbol=BTCUSDT")["lastFundingRate"]) * 100
    return float(_get(f"{OKX}/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")["data"][0]["fundingRate"]) * 100


def long_short(n=4):
    """最近 n 个 5 分钟的多空账户比，从旧到新。"""
    if SOURCE == "binance":
        return [float(x["longShortRatio"]) for x in _get(f"{FAPI}/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=5m&limit={n}")]
    d = _get(f"{OKX}/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=5m")["data"]
    return [float(x[1]) for x in d[:n]][::-1]
