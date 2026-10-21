"""资金费率、美股开盘、CPI 能否预测 BTC 接下来的方向和幅度。

用法：.venv/bin/python events_study.py
输出：终端报告 + results/events_*.csv
"""
import os

import numpy as np
import pandas as pd

import zhang

HERE = os.path.dirname(os.path.abspath(__file__))

# BLS CPI 发布日（美东 8:30）。2025-10 期因政府停摆未发布。
CPI_DATES = ["2025-10-24", "2025-12-18", "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10",
             "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-14"]


def load():
    df = zhang.load_5m(os.path.join(HERE, "data", "BTCUSDT_5m.csv"))
    fr = pd.read_csv(os.path.join(HERE, "data", "BTCUSDT_funding.csv"))
    fr["time"] = pd.to_datetime(fr["funding_time"] // 1000 * 1000, unit="ms", utc=True).dt.floor("5min")
    fr = fr.set_index("time")["funding_rate"].astype(float)
    return df, fr


def window(df, start, end):
    """[start, end) 内的收益率(%)、最高最低振幅(%)。start 时刻的开盘价为基准。"""
    seg = df.loc[start:end - pd.Timedelta(minutes=5)]
    if len(seg) == 0:
        return np.nan, np.nan
    p0 = seg["open"].iloc[0]
    return (seg["close"].iloc[-1] / p0 - 1) * 100, (seg["high"].max() - seg["low"].min()) / p0 * 100


def tstat(x):
    x = pd.Series(x).dropna()
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else np.nan


def sp(a, b):
    """Spearman 相关：先排名再算皮尔逊（不依赖 scipy）。"""
    m = pd.concat([a, b], axis=1).dropna()
    return m.iloc[:, 0].rank().corr(m.iloc[:, 1].rank())


def pct(x):
    return f"{x:+.2f}%" if pd.notna(x) else "—"


# ---------------- 1. 资金费率 ----------------

def funding_study(df, fr):
    rows = []
    for t, rate in fr.items():
        if t + pd.Timedelta(hours=72) > df.index[-1] or t - pd.Timedelta(hours=24) < df.index[0]:
            continue
        r8, g8 = window(df, t, t + pd.Timedelta(hours=8))
        r24, g24 = window(df, t, t + pd.Timedelta(hours=24))
        r72, _ = window(df, t, t + pd.Timedelta(hours=72))
        pr24, pg24 = window(df, t - pd.Timedelta(hours=24), t)
        rows.append(dict(time=t, rate=rate * 100, ret8=r8, ret24=r24, ret72=r72, rng8=g8, rng24=g24,
                         prev_ret24=pr24, prev_rng24=pg24))
    x = pd.DataFrame(rows).set_index("time")
    x["rate_pctile"] = x["rate"].rolling(90, min_periods=30).apply(lambda s: (s[:-1] < s[-1]).mean() * 100, raw=True)
    x.to_csv(os.path.join(HERE, "results", "events_funding.csv"))

    print("\n================ 1. 资金费率（每 8 小时一次，共 %d 次）================" % len(x))
    print(f"费率分布：中位 {x.rate.median():.4f}%，10% 分位 {x.rate.quantile(.1):.4f}%，90% 分位 {x.rate.quantile(.9):.4f}%，"
          f"为负的比例 {(x.rate < 0).mean()*100:.0f}%")
    base = dict(r24=x.ret24.mean(), up24=(x.ret24 > 0).mean() * 100, rng24=x.rng24.mean())
    print(f"基准（全部时刻）：未来 24h 平均 {pct(base['r24'])}，上涨概率 {base['up24']:.0f}%，24h 平均振幅 {base['rng24']:.2f}%")

    x["q"] = pd.qcut(x["rate"], 5, labels=["最低20%", "20-40%", "40-60%", "60-80%", "最高20%"])
    g = x.groupby("q", observed=True).agg(n=("ret24", "size"), 费率均值=("rate", "mean"),
                                          未来8h=("ret8", "mean"), 未来24h=("ret24", "mean"),
                                          上涨概率24h=("ret24", lambda s: (s > 0).mean() * 100),
                                          未来72h=("ret72", "mean"), 振幅24h=("rng24", "mean"))
    print("\n按费率高低分 5 组（绝对水平）：")
    print(g.round(4).to_string())

    y = x.dropna(subset=["rate_pctile"]).copy()
    y["pq"] = pd.cut(y["rate_pctile"], [-1, 10, 90, 101], labels=["近30天最低10%", "中间", "近30天最高10%"])
    g2 = y.groupby("pq", observed=True).agg(n=("ret24", "size"), 未来24h=("ret24", "mean"),
                                            上涨概率=("ret24", lambda s: (s > 0).mean() * 100),
                                            未来72h=("ret72", "mean"), 振幅24h=("rng24", "mean"))
    print("\n按费率在近 30 天里的相对位置：")
    print(g2.round(3).to_string())

    print("\n相关性（Spearman）：")
    for col, name in (("ret8", "未来8h方向"), ("ret24", "未来24h方向"), ("ret72", "未来72h方向"), ("rng24", "未来24h振幅")):
        print(f"  费率 vs {name}: {sp(x['rate'], x[col]):+.3f}")

    # 挤压组合：过去 24h 大涨/大跌，同时费率偏低/偏高
    med = x.rate.median()
    combos = {
        "过去24h涨>2% 且 费率低于中位（空头在逆势加仓）": (x.prev_ret24 > 2) & (x.rate < med),
        "过去24h涨>2% 且 费率高于中位（多头追涨）": (x.prev_ret24 > 2) & (x.rate >= med),
        "过去24h跌>2% 且 费率低于中位（空头追跌）": (x.prev_ret24 < -2) & (x.rate < med),
        "过去24h跌>2% 且 费率高于中位（多头抄底）": (x.prev_ret24 < -2) & (x.rate >= med),
    }
    print("\n价格 × 费率组合（检验「逆势加仓的一方会被挤」）：")
    half = x.index[0] + (x.index[-1] - x.index[0]) / 2
    for name, m in combos.items():
        s = x[m]
        a, b = s[s.index < half], s[s.index >= half]
        print(f"  {name}: {len(s)} 次，未来24h {pct(s.ret24.mean())}（上涨 {(s.ret24>0).mean()*100:.0f}%），"
              f"t={tstat(s.ret24):+.1f}；前半年 {pct(a.ret24.mean())} / 后半年 {pct(b.ret24.mean())}")

    print("\n幅度可预测性（对照组）：过去 24h 振幅 vs 未来 24h 振幅 Spearman "
          f"{sp(x['prev_rng24'], x['rng24']):+.3f}")
    x["pr_q"] = pd.qcut(x["prev_rng24"], 4, labels=["最平静25%", "偏平静", "偏活跃", "最活跃25%"])
    print(x.groupby("pr_q", observed=True).agg(n=("rng24", "size"), 过去24h振幅=("prev_rng24", "mean"),
                                               未来24h振幅=("rng24", "mean"),
                                               未来24h振幅P80=("rng24", lambda s: s.quantile(.8))).round(2).to_string())
    return x


# ---------------- 2. 美股开盘 ----------------

def us_open_study(df):
    ny = df.index.tz_convert("America/New_York")
    is_open = (ny.hour == 9) & (ny.minute == 30) & (ny.weekday < 5)
    opens = df.index[is_open]
    rows = []
    for t in opens:
        if t + pd.Timedelta(hours=4) > df.index[-1] or t - pd.Timedelta(hours=6) < df.index[0]:
            continue
        pre6, _ = window(df, t - pd.Timedelta(hours=6), t)
        pre1, g_pre1 = window(df, t - pd.Timedelta(hours=1), t)
        r30, _ = window(df, t, t + pd.Timedelta(minutes=30))
        r1, g1 = window(df, t, t + pd.Timedelta(hours=1))
        r4, g4 = window(df, t, t + pd.Timedelta(hours=4))
        rest, _ = window(df, t + pd.Timedelta(minutes=30), t + pd.Timedelta(hours=4))
        rows.append(dict(time=t, pre6=pre6, pre1=pre1, r30=r30, r1=r1, r4=r4, rest=rest, rng_pre1=g_pre1, rng1=g1, rng4=g4))
    x = pd.DataFrame(rows).set_index("time")
    x.to_csv(os.path.join(HERE, "results", "events_us_open.csv"))

    # 对照：同一时钟时刻的周末（无美股）
    wk = df.index[(ny.hour == 9) & (ny.minute == 30) & (ny.weekday >= 5)]
    ctrl = pd.DataFrame([dict(rng1=window(df, t, t + pd.Timedelta(hours=1))[1]) for t in wk
                         if t + pd.Timedelta(hours=1) <= df.index[-1]])
    # 对照：工作日其他整点的 1 小时振幅
    h1 = df.resample("1h").agg({"open": "first", "high": "max", "low": "min"}).dropna()
    h1["rng"] = (h1.high - h1.low) / h1.open * 100
    h1ny = h1.index.tz_convert("America/New_York")
    other = h1[(h1ny.weekday < 5) & ~h1ny.hour.isin([9, 10])]["rng"]

    print("\n================ 2. 美股开盘（纽约 9:30，共 %d 个交易日）================" % len(x))
    print(f"幅度：开盘后 1 小时平均振幅 {x.rng1.mean():.2f}%，开盘前 1 小时 {x.rng_pre1.mean():.2f}%，"
          f"同时刻周末 {ctrl.rng1.mean():.2f}%，工作日其他时段 1 小时 {other.mean():.2f}%")
    print(f"      开盘后 1 小时振幅超过 1% 的比例 {(x.rng1 > 1).mean()*100:.0f}%（其他时段 {(other > 1).mean()*100:.0f}%）")
    print(f"方向：开盘后 1h 平均 {pct(x.r1.mean())}（上涨 {(x.r1>0).mean()*100:.0f}%），"
          f"开盘后 4h 平均 {pct(x.r4.mean())}（上涨 {(x.r4>0).mean()*100:.0f}%，t={tstat(x.r4):+.1f}）")

    def follow(a, b, label):
        m = x[[a, b]].dropna()
        same = (np.sign(m[a]) == np.sign(m[b])).mean() * 100
        print(f"  {label}: 同向 {same:.0f}%，Spearman {sp(m[a], m[b]):+.3f}（50% = 没有预测力）")
    print("能否用开盘前/开盘初的走势预测之后：")
    follow("pre6", "r4", "开盘前 6h 方向 → 开盘后 4h 方向")
    follow("pre1", "r4", "开盘前 1h 方向 → 开盘后 4h 方向")
    follow("r30", "rest", "开盘头 30 分钟方向 → 之后 3.5h 方向")
    big = x[x.r30.abs() > 0.5]
    print(f"  开盘头 30 分钟波动 >0.5% 时（{len(big)} 次）: 之后 3.5h 同向 "
          f"{(np.sign(big.r30) == np.sign(big.rest)).mean()*100:.0f}%")
    print(f"  开盘前 1h 振幅 vs 开盘后 1h 振幅 Spearman {sp(x.rng_pre1, x.rng1):+.3f}")
    return x


# ---------------- 3. CPI ----------------

def cpi_study(df):
    rows = []
    for d in CPI_DATES:
        t = pd.Timestamp(f"{d} 08:30", tz="America/New_York").tz_convert("UTC")
        if t - pd.Timedelta(hours=24) < df.index[0] or t + pd.Timedelta(hours=24) > df.index[-1]:
            continue
        pre24, _ = window(df, t - pd.Timedelta(hours=24), t)
        r15, _ = window(df, t, t + pd.Timedelta(minutes=15))
        r1, g1 = window(df, t, t + pd.Timedelta(hours=1))
        r4, g4 = window(df, t, t + pd.Timedelta(hours=4))
        r24, g24 = window(df, t, t + pd.Timedelta(hours=24))
        rest, _ = window(df, t + pd.Timedelta(minutes=15), t + pd.Timedelta(hours=4))
        # 对照：发布前 20 个工作日同一时刻的 1h / 4h 振幅中位数
        ctrl1, ctrl4 = [], []
        for k in range(1, 29):
            c = t - pd.Timedelta(days=k)
            if c.tz_convert("America/New_York").weekday() < 5 and c - pd.Timedelta(hours=1) > df.index[0]:
                ctrl1.append(window(df, c, c + pd.Timedelta(hours=1))[1])
                ctrl4.append(window(df, c, c + pd.Timedelta(hours=4))[1])
        rows.append(dict(日期=d, 前24h=pre24, 头15分钟=r15, 后1h=r1, 后4h=r4, 后24h=r24, 后续3h45m=rest,
                         振幅1h=g1, 平日同时刻1h=np.nanmedian(ctrl1), 振幅4h=g4, 平日同时刻4h=np.nanmedian(ctrl4), 振幅24h=g24))
    x = pd.DataFrame(rows)
    x.to_csv(os.path.join(HERE, "results", "events_cpi.csv"), index=False)
    print("\n================ 3. CPI（美东 8:30 发布，共 %d 次）================" % len(x))
    print(x.round(2).to_string(index=False))
    print(f"\n幅度：发布后 1h 振幅中位 {x.振幅1h.median():.2f}% vs 平日同时刻 {x.平日同时刻1h.median():.2f}%"
          f"（{x.振幅1h.median()/x.平日同时刻1h.median():.1f} 倍）；4h {x.振幅4h.median():.2f}% vs {x.平日同时刻4h.median():.2f}%"
          f"（{x.振幅4h.median()/x.平日同时刻4h.median():.1f} 倍）；{(x.振幅1h > x.平日同时刻1h).mean()*100:.0f}% 的 CPI 日 1h 振幅高于平日")
    print(f"方向：发布后 4h 上涨 {(x.后4h>0).sum()} 次 / 下跌 {(x.后4h<0).sum()} 次")
    print(f"  头 15 分钟方向 → 之后 3h45m 同向 {(np.sign(x.头15分钟)==np.sign(x.后续3h45m)).sum()} / {len(x)} 次")
    print(f"  发布前 24h 方向 → 发布后 4h 同向 {(np.sign(x.前24h)==np.sign(x.后4h)).sum()} / {len(x)} 次")
    return x


def main():
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    df, fr = load()
    print(f"数据：{df.index[0]} → {df.index[-1]}")
    funding_study(df, fr)
    us_open_study(df)
    cpi_study(df)


if __name__ == "__main__":
    main()
