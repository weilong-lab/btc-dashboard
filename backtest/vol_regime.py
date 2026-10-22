"""波动大小变化时，「跌多了买、涨多了空」还管不管用；进场后通常要扛多少逆向波动。

1. 逆向幅度：任意时刻进场（多空都算），之后 1h / 4h / 24h 内最远逆向走了多少，
   用「过去 24 小时 1h K 线平均振幅」（下称 ATR）做单位。波动大时按现在的 ATR 换算成美元，
   就是现在进场大概要扛多少。
2. 波动状态：最近 7 天 ATR ÷ 之前 30 天 ATR。>1.3 算扩张，<0.77 算收缩。
   分状态看急跌超卖后反弹（4h 跌 ≥1.5%、RSI6 ≤20）和急涨超买后回落的比例。

用法：.venv/bin/python vol_regime.py
结果追加到 dashboard/live/context.js 的 VOLSTAT
"""
import os

import numpy as np
import pandas as pd

from direction_model import features
from context_js import write_var
from direction_model_full import load_1m, to5m

HERE = os.path.dirname(os.path.abspath(__file__))
H = {"1 小时": 12, "4 小时": 48, "24 小时": 288}


def fwd_ext(s, h, fn):
    """之后 h 根（不含当前）里的最高 / 最低。"""
    return getattr(s[::-1].rolling(h, min_periods=h), fn)()[::-1].shift(-1)


def main():
    d5 = to5m(load_1m("BTCUSDT_perp_1m.csv.gz"))
    d5 = d5[d5.index >= "2021-01-01"]
    c, hi, lo = d5.close, d5.high, d5.low
    h1 = d5.resample("1h").agg({"high": "max", "low": "min"})
    atr1h = (h1.high - h1.low).rolling(24).mean()
    atr1h.index = atr1h.index + pd.Timedelta(hours=1)      # 只用已经走完的 1h K 线
    atr = atr1h.reindex(d5.index, method="ffill")
    ratio = (atr1h.rolling(24 * 7).mean() / atr1h.shift(24 * 7).rolling(24 * 30).mean()).reindex(d5.index, method="ffill")
    regime = pd.cut(ratio, [0, 0.77, 1.3, 99], labels=["收缩", "正常", "扩张"])

    out = {"mae_atr": {}, "regime": {}}
    rows = []
    for name, h in H.items():
        adv_long = (c - fwd_ext(lo, h, "min")) / atr          # 做多：之后最低点离进场多远
        adv_short = (fwd_ext(hi, h, "max") - c) / atr         # 做空：之后最高点离进场多远
        a = pd.concat([adv_long, adv_short]).dropna()
        a = a[np.isfinite(a)]
        q = a.quantile([0.5, 0.8, 0.95])
        out["mae_atr"][name] = {"p50": round(q[0.5], 2), "p80": round(q[0.8], 2), "p95": round(q[0.95], 2)}
        rows.append((name, *[round(x, 2) for x in q]))
    print("任意时刻进场，之后最远逆向（ATR 倍数，ATR = 过去 24h 的 1h K 线平均振幅）")
    for r in rows:
        print(f"  {r[0]}: 中位 {r[1]}  P80 {r[2]}  P95 {r[3]}")
    # 检验：按 ATR 换算是否比固定美元更稳（同一分位在不同波动状态下是否接近）
    for name, h in H.items():
        adv = ((c - fwd_ext(lo, h, "min")) / atr).dropna()
        by = adv.groupby(regime.reindex(adv.index), observed=True).median()
        print(f"  {name} 中位逆向（ATR 倍数）分状态：", {k: round(v, 2) for k, v in by.items()})

    f = features(d5, 288)
    rsi = (f.rsi6 + 0.5) * 100
    r4 = np.expm1(f.ret_48) * 100
    print("\n急跌超卖 / 急涨超买之后（1 小时、4 小时）按波动状态：")
    for key, m, side in [("drop", (r4 <= -1.5) & (rsi <= 20), -1), ("rally", (r4 >= 1.5) & (rsi >= 80), 1)]:
        out["regime"][key] = {}
        for reg in ["收缩", "正常", "扩张"]:
            res = {}
            for name, h in [("1 小时", 12), ("4 小时", 48)]:
                fwd = c.shift(-h) / c - 1
                sel = m & (regime == reg) & fwd.notna()
                n = int(sel.sum() / h)
                if n < 10:
                    continue
                rev = (fwd[sel] > 0).mean() if side < 0 else (fwd[sel] < 0).mean()
                ext = fwd_ext(lo, h, "min") if side < 0 else fwd_ext(hi, h, "max")
                adv = (abs(ext / c - 1) * 100)[sel]
                res[name] = {"n": n, "rev": round(rev * 100, 1), "err": round(98 / np.sqrt(n), 1),
                             "adv50": round(adv.median(), 2), "adv80": round(adv.quantile(0.8), 2)}
            out["regime"][key][reg] = res
            print(f"  {key} {reg}: {res}")
    share = regime.value_counts(normalize=True).round(3).to_dict()
    print("\n各状态时间占比：", share)

    write_var("VOLSTAT", "波动状态与逆向幅度（2021–2026），来自 backtest/vol_regime.py", out)


if __name__ == "__main__":
    main()
