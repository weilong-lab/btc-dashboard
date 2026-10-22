"""一周里哪些时段波动大、哪些时段可以放心不盯盘（东京时间）。

用 2021–2026 年 1 分钟永续数据：
- 每个小时（东京时间）的 1 小时振幅，相对全时段中位数的倍数
- 每个小时出现「30 分钟内走 ≥3 ATR」大行情的频率，相对平均的倍数
美国夏令时（3 月到 11 月初）和冬令时，美国相关的时段在东京时间会差 1 小时，所以分开统计。
结果写进 dashboard/live/context.js 的 HOURVOL（面板「盯盘时间表」用）。

用法：.venv/bin/python hour_vol.py
"""
import numpy as np
import pandas as pd

from context_js import write_var
from direction_model_full import load_1m


def main():
    d = load_1m("BTCUSDT_perp_1m.csv.gz")
    d = d[d.index >= "2021-01-01"]
    h1 = d.resample("1h").agg({"high": "max", "low": "min", "open": "first"}).dropna()
    rng = (h1.high - h1.low) / h1.open * 100
    atr = (h1.high - h1.low).rolling(24).mean().shift(1)
    rel = (h1.high - h1.low) / atr                      # 这一小时振幅 ÷ 过去 24 小时平均，消除不同年份波动水平的差异
    # 大行情：30 分钟内最高最低差 ≥ 3 个 ATR 的起点
    o, h, l = d.open.to_numpy(), d.high.to_numpy(), d.low.to_numpy()
    hi30 = pd.Series(h).iloc[::-1].rolling(30, min_periods=30).max().iloc[::-1].to_numpy()
    lo30 = pd.Series(l).iloc[::-1].rolling(30, min_periods=30).min().iloc[::-1].to_numpy()
    A = atr.reindex(d.index, method="ffill").to_numpy()
    big = (np.maximum(hi30 - o, o - lo30) >= 3 * A) & np.isfinite(A)
    starts = d.index[np.where(big & ~np.roll(big, 1))[0]]

    jst = h1.index.tz_convert("Asia/Tokyo")
    ny = h1.index.tz_convert("America/New_York")
    dst = np.asarray([bool(x.dst()) for x in ny])
    wk = np.asarray(jst.weekday)            # 东京时间的星期（0 = 周一）
    bj = pd.Series(1, index=starts.tz_convert("Asia/Tokyo").floor("h")).groupby(level=0).sum()
    bigh = bj.reindex(h1.index.tz_convert("Asia/Tokyo")).fillna(0).to_numpy()

    out = {}
    for name, m_dst in (("夏令时", dst), ("冬令时", ~dst)):
        rows = []
        for grp, m_wk in (("工作日", (wk >= 0) & (wk <= 4)), ("周六", wk == 5), ("周日", wk == 6)):
            for hr in range(24):
                m = m_dst & m_wk & (np.asarray(jst.hour) == hr)
                if m.sum() < 30:
                    continue
                rows.append(dict(段=grp, 时=hr, 振幅倍数=round(float(np.nanmedian(rel[m]) / np.nanmedian(rel)), 2),
                                 大行情倍数=round(float(bigh[m].mean() / bigh.mean()), 2), 振幅中位pct=round(float(np.nanmedian(rng[m])), 3)))
        t = pd.DataFrame(rows)
        out[name] = {g: {int(r.时): [r.振幅倍数, r.大行情倍数] for r in x.itertuples()} for g, x in t.groupby("段")}
        print(f"\n== 美国{name}（东京时间）")
        for g, x in t.groupby("段", sort=False):
            top = x.sort_values("振幅倍数", ascending=False).head(6)
            low = x.sort_values("振幅倍数").head(6)
            print(f"  {g} 最活跃：", "；".join(f"{int(r.时):02d}点 振幅×{r.振幅倍数} 大行情×{r.大行情倍数}" for r in top.itertuples()))
            print(f"  {g} 最安静：", "；".join(f"{int(r.时):02d}点 振幅×{r.振幅倍数} 大行情×{r.大行情倍数}" for r in low.itertuples()))
    write_var("HOURVOL", "一周各小时（东京时间）的振幅倍数和大行情倍数，分美国夏令时 / 冬令时（2021–2026），来自 backtest/hour_vol.py", out)


if __name__ == "__main__":
    main()
