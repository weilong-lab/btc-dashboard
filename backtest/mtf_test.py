"""5 分钟信号失真问题：比较几种改法，做多 / 做空分开统计。数据：永续 2020-01 → 至今。

改法：
  A 只看 5 分钟（现状）
  B 5 分钟 + 1 小时趋势过滤（做多要求 1h 收盘在 MA25 上方且 MA25 向上；做空镜像）
  C 多周期共振：5 分钟扳机 + 15 分钟和 1 小时同时超买（做空）/ 超卖（做多）
  D 5 分钟，排除周末和低量（当前量 < 24h 中位数的一半）
  E/F/G 整套信号放在 15 分钟 / 1 小时 / 4 小时 K 线上

出场（各周期一致，按百分比，便于跨年份比较）：止损 = 最近 12 根高/低点外加 0.5 ATR，止盈 = 2 倍风险，
最长持有 288 根该周期 K 线；同根同时碰到止损止盈按止损算。手续费按全挂单 0.04% 往返。
用法：.venv/bin/python mtf_test.py
"""
import os

import numpy as np
import pandas as pd

import zhang
from direction_model_full import load_1m

HERE = os.path.dirname(os.path.abspath(__file__))
FEE = 0.04  # %，往返


def resample(d1, rule):
    return d1.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "taker_buy_volume": "sum"}).dropna()


def prep(df):
    return zhang.signals(zhang.add_indicators(df))


def align(src, rule, target_index, cols):
    """把较大周期的列对齐到 5 分钟：只用已经收盘的 K 线。"""
    s = src[cols].copy()
    s.index = s.index + pd.Timedelta(rule)
    return s.reindex(target_index, method="ffill")


def simulate(df, entries, side, max_hold=288):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr = df["atr"].to_numpy()
    hi12 = df["high"].rolling(12).max().to_numpy(); lo12 = df["low"].rolling(12).min().to_numpy()
    idx = np.flatnonzero(entries.to_numpy()); n = len(df); out = []; busy = -1
    for t in idx:
        e = t + 1
        if e >= n or e <= busy or np.isnan(atr[t]):
            continue
        px = o[e]
        risk = max((hi12[t] + 0.5 * atr[t] - px) if side == "short" else (px - lo12[t] + 0.5 * atr[t]), px * 0.001)
        stop = px + risk if side == "short" else px - risk
        tp = px - 2 * risk if side == "short" else px + 2 * risk
        exit_px, j = None, e
        for j in range(e, min(e + max_hold, n)):
            if (h[j] >= stop) if side == "short" else (l[j] <= stop):
                exit_px = stop; break
            if (l[j] <= tp) if side == "short" else (h[j] >= tp):
                exit_px = tp; break
        if exit_px is None:
            exit_px = c[j]
        ret = ((px - exit_px) if side == "short" else (exit_px - px)) / px * 100 - FEE
        out.append(dict(time=df.index[t], side=side, ret=ret, r=ret / (risk / px * 100)))
        busy = j
    return out


def summarize(rows, label):
    t = pd.DataFrame(rows)
    res = []
    for side, name in (("long", "做多"), ("short", "做空")):
        g = t[t.side == side] if len(t) else t
        if len(g) == 0:
            res.append(dict(改法=label, 方向=name, 每年笔数=0)); continue
        yrs = g.groupby(g.time.dt.year)
        by_year = yrs.ret.mean()
        res.append(dict(改法=label, 方向=name, 每年笔数=round(len(g) / g.time.dt.year.nunique()),
                        胜率=round((g.ret > 0).mean() * 100, 1), 每笔收益pct=round(g.ret.mean(), 3), 每笔R=round(g.r.mean(), 3),
                        t值=round(g.ret.mean() / (g.ret.std() / np.sqrt(len(g))), 2),
                        正收益年数=f"{int((by_year > 0).sum())}/{len(by_year)}"))
    return res


def main():
    d1 = load_1m("BTCUSDT_perp_1m.csv.gz")
    m5, m15, h1, h4 = (prep(resample(d1, r)) for r in ("5min", "15min", "1h", "4h"))
    print(f"5m {len(m5):,} 根", flush=True)

    # 1h 趋势
    h1["ma25s"] = h1["ma25"] - h1["ma25"].shift(6)
    trend = align(h1.assign(up=(h1.close > h1.ma25) & (h1.ma25s > 0), dn=(h1.close < h1.ma25) & (h1.ma25s < 0)), "1h", m5.index, ["up", "dn"]).fillna(False)
    # 15m / 1h 超买超卖（最近 6 根内 J、RSI 极值）
    def hotcold(df):
        return df.assign(hot=(df.j.rolling(6).max() > 100) & (df.rsi6.rolling(6).max() > 70),
                         cold=(df.j.rolling(6).min() < 0) & (df.rsi6.rolling(6).min() < 20))
    hc15 = align(hotcold(m15), "15min", m5.index, ["hot", "cold"]).fillna(False)
    hc1h = align(hotcold(h1), "1h", m5.index, ["hot", "cold"]).fillna(False)
    ny = m5.index.tz_convert("America/New_York")
    vol_ok = (m5.volume >= 0.5 * m5.volume.rolling(288).median()) & (ny.weekday < 5)

    rows = []
    for ver, vname in (("A", "扳机"), ("B", "完整版")):
        sL, sS = m5[f"long_{ver}"], m5[f"short_{ver}"]
        tag = f"（{vname}）"
        rows += summarize(simulate(m5, sL, "long") + simulate(m5, sS, "short"), "A 只看5分钟" + tag)
        rows += summarize(simulate(m5, sL & trend.up, "long") + simulate(m5, sS & trend.dn, "short"), "B 5分钟+1h趋势同向" + tag)
        rows += summarize(simulate(m5, sL & ~trend.dn, "long") + simulate(m5, sS & ~trend.up, "short"), "B' 5分钟+不逆1h趋势" + tag)
        rows += summarize(simulate(m5, m5.long_A & hc15.cold & hc1h.cold, "long") + simulate(m5, m5.short_A & hc15.hot & hc1h.hot, "short"), "C 三周期共振（5m扳机+15m+1h极值）")  if ver == "A" else []
        rows += summarize(simulate(m5, sL & vol_ok, "long") + simulate(m5, sS & vol_ok, "short"), "D 5分钟排除周末和低量" + tag)
        for df, name in ((m15, "E 15分钟"), (h1, "F 1小时"), (h4, "G 4小时")):
            rows += summarize(simulate(df, df[f"long_{ver}"], "long") + simulate(df, df[f"short_{ver}"], "short"), name + tag)
        print(f"{vname} 完成", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(HERE, "results", "mtf_test.csv"), index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
