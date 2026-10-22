"""检验 jinwukong/btc-perpetual-alpha 里的「CTA 情绪因子」在我们的数据上有没有用。

它的因子（1 分钟）：
- ofr：本分钟主动买卖差 ÷ 成交量
- sent_short：ofr 的 5 分钟均值（短线情绪）
- sent_medium：softsign(资金费率 120 分钟均值 × 主动买卖差 120 分钟均值)（中线情绪）
- cta：两者合成（这里用排名后各半，避免它原文里用全样本分位数造成的未来信息）

看每年和之后 5 / 15 / 30 分钟涨跌的秩相关（IC），以及最极端 10% 时之后的平均涨跌，
和往返手续费（挂单 0.04% / 市价 0.10%）比。对照：我们方向模型的 15 分钟样本外概率。

用法：.venv/bin/python alpha_factor_check.py
"""
import os

import numpy as np
import pandas as pd

from direction_model_full import load_1m

HERE = os.path.dirname(os.path.abspath(__file__))


def rank_ic(a, b):
    m = a.notna() & b.notna()
    return np.corrcoef(a[m].rank(), b[m].rank())[0, 1]


def main():
    d = load_1m("BTCUSDT_perp_1m.csv.gz")
    d = d[d.index >= "2021-01-01"]
    fr = pd.read_csv(os.path.join(HERE, "data", "BTCUSDT_funding_all.csv"))
    fr.index = pd.to_datetime(fr.funding_time, unit="ms", utc=True)
    funding = fr.funding_rate.reindex(d.index, method="ffill")       # 结算后才知道，前向填充不含未来信息
    v, tb, c = d.volume, d.taker_buy_volume, d.close
    bs = 2 * tb - v
    f = pd.DataFrame(index=d.index)
    f["ofr"] = bs / v.replace(0, np.nan)
    f["sent_short"] = f.ofr.rolling(5, min_periods=1).mean()
    raw = funding.rolling(120, min_periods=1).mean() * bs.rolling(120, min_periods=1).mean()
    f["sent_medium"] = raw / (1 + raw.abs())
    f["cta"] = f.sent_short.rank(pct=True) + f.sent_medium.rank(pct=True)
    for h in (5, 15, 30):
        f[f"fwd{h}"] = c.shift(-h) / c - 1
    # 每 5 分钟取一个点，减少重叠样本
    s = f.iloc[::5].copy()
    oos = pd.read_csv(os.path.join(HERE, "data", "oos_probs_5m.csv.gz"), parse_dates=["time"]).set_index("time")
    oos.index = oos.index + pd.Timedelta(minutes=5)   # 概率用的是这根 5 分钟 K 线收盘时的数据，对齐到收盘时刻
    s = s.join(oos[["p15"]], how="left")

    rows = []
    for y, g in s.groupby(s.index.year):
        r = {"年份": y, "样本": len(g)}
        for col in ("sent_short", "sent_medium", "cta", "p15"):
            for h in (5, 15, 30):
                if col == "p15" and h != 15:
                    continue
                r[f"{col}→{h}m"] = round(rank_ic(g[col], g[f"fwd{h}"]), 4)
        rows.append(r)
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print("秩相关 IC（正 = 因子高时之后涨；|IC| < 0.01 基本没用）")
    print(out.to_string(index=False))

    print("\n最极端 10% 时，之后的平均涨跌（基点，1 基点 = 0.01%；往返手续费挂单 4 基点、市价 10 基点）")
    for col in ("sent_short", "sent_medium", "cta"):
        q = s[col].rank(pct=True)
        for h in (5, 15, 30):
            hi = s.loc[q >= 0.9, f"fwd{h}"].mean() * 1e4
            lo = s.loc[q <= 0.1, f"fwd{h}"].mean() * 1e4
            print(f"  {col:12} {h:>2}m：最高 10% {hi:+.2f}  最低 10% {lo:+.2f}  多空差 {hi - lo:+.2f}")


if __name__ == "__main__":
    main()
