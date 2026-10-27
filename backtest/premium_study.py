"""Coinbase 溢价能不能预测 BTC 接下来的涨跌？

溢价 = Coinbase BTC-USD ÷（币安现货 BTCUSDT × Coinbase USDT-USD）− 1，和面板「美国资金」卡片同一个算法。
先跑 fetch_coinbase.py 下载 Coinbase K 线；币安现货用 data/BTCUSDT_spot_1m.csv.gz。

检验：
1. 溢价和「同一小时」的涨跌是什么关系（它是不是只是跟着价格走）
2. 溢价和「之后」1h / 4h / 24h 涨跌的秩相关（IC），按年分开，长周期用不重叠样本
3. 按溢价 z 分数（只用过去 7 天算均值和标准差，没有未来数据）分档，看之后 4h 涨跌，美股盘中和其他时段分开
4. 简单打法：美股盘中 z > 1 做多、z < -1 做空，持有 4h，扣手续费，按年列
5. 最近 400 天的 5 分钟数据：z 分数（过去 24h）对之后 15 分钟 / 1 小时

用法：.venv/bin/python premium_study.py   输出同时写到 results_premium.txt
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    OUT.append(s)


def load_cb(product, mins):
    d = pd.read_csv(os.path.join(DATA, f"coinbase_{product}_{mins}m.csv"))
    return d.set_index(pd.to_datetime(d.time_ms, unit="ms", utc=True))["close"]


def load_spot():
    d = pd.read_csv(os.path.join(DATA, "BTCUSDT_spot_1m.csv.gz"), usecols=["open_time", "close"])
    return d.set_index(pd.to_datetime(d.open_time, unit="ms", utc=True))["close"]


def bar_close(s1m, rule):
    # K 线按开盘时间标记：这一根的收盘 = 区间里最后一分钟的收盘（和 Coinbase 的 close 对齐）
    return s1m.resample(rule, label="left", closed="left").last()


def us_open(idx):
    ny = idx.tz_convert("America/New_York")
    m = ny.hour * 60 + ny.minute
    return (ny.weekday < 5) & (m >= 570) & (m < 960)


def spearman(a, b):
    ok = a.notna() & b.notna()
    if ok.sum() < 30:
        return np.nan, 0
    return a[ok].rank().corr(b[ok].rank()), int(ok.sum())


def tstat(r, n):
    return r * np.sqrt(max(n - 2, 1)) / np.sqrt(max(1 - r * r, 1e-9))


def frame(mins, rule, zwin):
    spot = bar_close(SPOT, rule)
    cb, usdt = load_cb("BTC-USD", mins), load_cb("USDT-USD", mins)
    df = pd.DataFrame({"cb": cb, "usdt": usdt, "bn": spot}).dropna()
    df["p"] = (df.cb / (df.bn * df.usdt) - 1) * 100          # 溢价（%）
    m, sd = df.p.rolling(zwin, min_periods=zwin // 2).mean(), df.p.rolling(zwin, min_periods=zwin // 2).std()
    df["z"] = ((df.p - m) / sd).shift(0)                        # 只用到这一根为止的数据
    df["us"] = us_open(df.index)
    return df


def fwd(df, n):
    return (df.bn.shift(-n) / df.bn - 1) * 100


def hourly():
    df = frame(60, "1h", 24 * 7)
    say(f"\n===== 1 小时数据：{df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}，{len(df)} 根 =====")
    say(f"溢价分布（%）：中位 {df.p.median():+.4f}，P10 {df.p.quantile(.1):+.4f}，P90 {df.p.quantile(.9):+.4f}，P1 {df.p.quantile(.01):+.4f}，P99 {df.p.quantile(.99):+.4f}")
    for y, g in df.groupby(df.index.year):
        say(f"  {y}：中位 {g.p.median():+.4f}%，平均 {g.p.mean():+.4f}%，美股盘中平均 {g.p[g.us].mean():+.4f}%，其他时段平均 {g.p[~g.us].mean():+.4f}%")

    past1 = (df.bn / df.bn.shift(1) - 1) * 100
    r, n = spearman(df.p, past1)
    say(f"\n[1] 溢价 vs 同一小时涨跌：秩相关 {r:+.3f}（n={n}）——正数说明溢价主要是跟着当下的买卖在走")
    r, n = spearman(df.p.diff(), past1)
    say(f"    溢价变化 vs 同一小时涨跌：秩相关 {r:+.3f}")

    say("\n[2] 溢价 / z 分数 vs 之后的涨跌（IC = 秩相关；|t| > 2 才算显著；4h、24h 用不重叠样本）")
    for h in (1, 4, 24):
        f = fwd(df, h)
        for name, x in (("溢价", df.p), ("z 分数", df.z), ("溢价变化", df.p.diff())):
            row = []
            for y, g in df.groupby(df.index.year):
                gi = g.index[::h]
                r, n = spearman(x.loc[gi], f.loc[gi])
                row.append(f"{y} {r:+.3f}" if n else f"{y} —")
            gi = df.index[::h]
            r, n = spearman(x.loc[gi], f.loc[gi])
            ru, nu = spearman(x.loc[gi][df.us.loc[gi]], f.loc[gi][df.us.loc[gi]])
            say(f"  之后 {h:>2}h · {name:<4}：全部 IC {r:+.4f}（t {tstat(r, n):+.1f}，n={n}）· 美股盘中 IC {ru:+.4f}（t {tstat(ru, nu):+.1f}）· 按年 " + "  ".join(row))

    say("\n[3] 按 z 分数分档，之后 4h 涨跌（%），美股盘中 / 其他时段；最后一列是同时段全部样本的平均")
    f4 = fwd(df, 4)
    bins = [-np.inf, -2, -1, -0.5, 0.5, 1, 2, np.inf]
    labels = ["z<-2", "-2~-1", "-1~-0.5", "-0.5~0.5", "0.5~1", "1~2", "z>2"]
    for tag, mask in (("美股盘中", df.us), ("其他时段", ~df.us)):
        g = df[mask].assign(f=f4[mask]).dropna(subset=["z", "f"])
        cut = pd.cut(g.z, bins, labels=labels)
        parts = []
        for lab in labels:
            x = g.f[cut == lab]
            parts.append(f"{lab}: {x.mean():+.3f}（涨 {(x > 0).mean() * 100:.0f}%，n={len(x)}）")
        say(f"  {tag}：" + " | ".join(parts) + f" ‖ 全部 {g.f.mean():+.3f}")

    say("\n[4] 美股盘中 z>1 做多 / z<-1 做空，持有 4h，同方向 4h 内不重复；每笔扣往返手续费（吃单 0.10% / 挂单 0.04%）")
    sig = pd.Series(0, index=df.index)
    sig[(df.z > 1) & df.us] = 1
    sig[(df.z < -1) & df.us] = -1
    trades, last = [], None
    for t, s in sig[sig != 0].items():
        if last is not None and t < last + pd.Timedelta(hours=4):
            continue
        r = f4.get(t)
        if pd.notna(r):
            trades.append((t, s, s * r))
            last = t
    tr = pd.DataFrame(trades, columns=["t", "side", "r"]).set_index("t")
    for y, g in tr.groupby(tr.index.year):
        say(f"  {y}：{len(g):>4} 笔（多 {int((g.side > 0).sum())} / 空 {int((g.side < 0).sum())}），不计费每笔 {g.r.mean():+.3f}%，胜率 {(g.r > 0).mean() * 100:.0f}%，扣吃单费 {g.r.mean() - 0.10:+.3f}%，扣挂单费 {g.r.mean() - 0.04:+.3f}%")
    if len(tr):
        t = tr.r.mean() / (tr.r.std() / np.sqrt(len(tr)))
        say(f"  合计：{len(tr)} 笔，不计费每笔 {tr.r.mean():+.3f}%（t {t:+.1f}），多单 {tr.r[tr.side > 0].mean():+.3f}%，空单 {tr.r[tr.side < 0].mean():+.3f}%")
    return df


def five_min():
    df = frame(5, "5min", 12 * 24)
    say(f"\n===== 5 分钟数据：{df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}，{len(df)} 根 =====")
    for n, lab in ((3, "15 分钟"), (12, "1 小时")):
        f = fwd(df, n)
        gi = df.index[::n]
        for name, x in (("溢价", df.p), ("z 分数", df.z), ("溢价变化", df.p.diff())):
            r, k = spearman(x.loc[gi], f.loc[gi])
            ru, ku = spearman(x.loc[gi][df.us.loc[gi]], f.loc[gi][df.us.loc[gi]])
            say(f"  之后 {lab} · {name:<4}：全部 IC {r:+.4f}（t {tstat(r, k):+.1f}，n={k}）· 美股盘中 IC {ru:+.4f}（t {tstat(ru, ku):+.1f}，n={ku}）")
    f = fwd(df, 12)
    g = df[df.us].assign(f=f[df.us]).dropna(subset=["z", "f"])
    for lo, hi, lab in ((-np.inf, -2, "z<-2"), (-2, -1, "-2~-1"), (-1, 1, "-1~1"), (1, 2, "1~2"), (2, np.inf, "z>2")):
        x = g.f[(g.z > lo) & (g.z <= hi)]
        say(f"  美股盘中 {lab:<6}：之后 1h 平均 {x.mean():+.3f}%，涨 {(x > 0).mean() * 100:.0f}%，n={len(x)}")


if __name__ == "__main__":
    SPOT = load_spot()
    say(f"币安现货 1 分钟数据到 {SPOT.index[-1]:%Y-%m-%d %H:%M} UTC")
    hourly()
    five_min()
    with open(os.path.join(HERE, "results_premium.txt"), "w") as f:
        f.write("\n".join(OUT) + "\n")
    sys.exit(0)
