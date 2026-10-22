"""持仓中盘面突变时，马上卖 vs 按原计划拿着，哪个更好。

持仓：规则 A 的进场（同 exit_study.py），原计划持有 4 小时。持有期间：
1. 第一次出现一根 5 分钟 K 线逆向走 ≥ k 个 ATR（急跌砸到多单 / 急涨冲击空单）：
   「马上卖」= 下一根开盘市价卖；「按计划」= 拿到 4 小时。比较之后这段的收益。
2. 第一次出现 5 分钟顺向 ≥ k 个 ATR：马上止盈 vs 按计划。
3. 持有期间遇到美股开盘：开盘前 15 分钟卖掉 vs 拿过开盘。
ATR = 进场时过去 24 小时 1h K 线平均振幅。手续费：提前卖多一笔市价 0.05%。

用法：.venv/bin/python inplay_check.py
"""
import numpy as np
import pandas as pd

from exit_study import entries
from rules_backtest import load, TAKER

HOLD = 48


def main():
    d = load()
    h1 = d[["high", "low"]].resample("1h").agg({"high": "max", "low": "min"})
    a1 = (h1.high - h1.low).rolling(24).mean()
    a1.index = a1.index + pd.Timedelta("1h")
    atr = a1.reindex(d.index, method="ffill").to_numpy()
    o, c = d.open.to_numpy(), d.close.to_numpy()
    ny = d.index.tz_convert("America/New_York")
    open_bar = np.asarray((ny.weekday < 5) & (ny.hour == 9) & (ny.minute == 30))
    ent = [x for x in entries(d) if x[0] == "A"]
    res = {}
    for _, t, e, side, px, _f in ent:
        s, a, end = (1 if side == "long" else -1), atr[t], e + HOLD
        if not np.isfinite(a) or end + 1 >= len(d):
            continue
        for k in (0.5, 1.0, 1.5):
            for kind in ("逆向", "顺向"):
                for j in range(e, end):
                    mv = s * (c[j] - o[j])
                    if (kind == "逆向" and mv <= -k * a) or (kind == "顺向" and mv >= k * a):
                        sell_now = s * (o[j + 1] / px - 1) * 100 - TAKER          # 多付一笔市价费（按计划到期也要付，这里只算差额）
                        hold = s * (c[end] / px - 1) * 100
                        res.setdefault((kind, k), []).append(sell_now - hold)
                        break
        for j in range(e, end):
            if open_bar[j]:
                pre = max(j - 3, e)
                res.setdefault(("美股开盘", 0), []).append(s * (o[pre] / px - 1) * 100 - TAKER - s * (c[end] / px - 1) * 100)
                res.setdefault(("美股开盘·波动", 0), []).append(abs(s * (c[end] / o[pre] - 1) * 100))
                break
    print(f"规则 A 进场 {len(ent)} 笔，原计划持有 4 小时。数值 = 「马上卖」比「按计划拿着」多赚的百分比（负数 = 马上卖更差）")
    for (kind, k), v in res.items():
        v = np.array(v)
        if kind == "美股开盘·波动":
            print(f"  拿过美股开盘那段的平均绝对波动：{v.mean():.3f}%（{len(v)} 次）")
            continue
        label = f"5 分钟{kind} ≥{k} ATR" if k else "美股开盘前 15 分钟卖掉"
        print(f"  {label:20} 出现 {len(v):5} 次  马上卖 − 按计划：平均 {v.mean():+.3f}%  ±{1.96 * v.std() / np.sqrt(len(v)):.3f}  马上卖更好的比例 {np.mean(v > 0) * 100:.0f}%")


if __name__ == "__main__":
    main()
