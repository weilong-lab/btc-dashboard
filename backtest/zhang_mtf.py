"""张主任 10/27–10/28 的多周期超买超卖规则，以及聊天里提出的几条判断，逐条用历史数据检验。

规则原文（10/28 21:56 起）：
  先看 4 小时 MA99 方向定多空 → 再看 1 小时、30 分现在处于上涨还是下跌阶段 → 最后看 5 分、15 分的 RSI 和 KDJ（RSI 优先）。
  5 分：J > 110 或 < -5，和/或 RSI6 > 80 或 < 20；15 分放宽：J > 100 或 < 0，和/或 RSI6 > 70 或 < 20。
  同一个指标要在 5 分和 15 分同时在区间外（RSI 优先：两个周期 RSI 都在区间外就报，KDJ 不用满足；只有 KDJ 两周期在区间外也报）。
  只有 5 分在区间外不报，必须 15 分也在区间外。再出现量价顶 / 底背离 → 强提示。顺序：先指标、后量、再看 MA7 拐不拐头。

指标都按「此刻」算：15 分、30 分、1 小时、4 小时的 RSI / KDJ 用到当前这根还没走完的 K 线
（和看盘软件里看到的一样）；均线方向只用已经走完的 K 线。信号在 5 分钟 K 线收盘出现，下一根开盘市价进场。
手续费按市价进出 0.10% 往返。数据：币安 U 本位永续 1 分钟，统计 2021-01 起。

用法：.venv/bin/python zhang_mtf.py      结果写到 results_zhang_mtf.txt
"""
import os
import sys

import numpy as np
import pandas as pd

import zhang
from direction_model_full import load_1m

HERE = os.path.dirname(os.path.abspath(__file__))
FEE = 0.10
START = "2021-01-01"
OUT = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    OUT.append(s)


def agg(df, rule):
    return df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def live_osc(d5, rule):
    """在每根 5 分钟收盘时，算 rule 周期（含当前未走完那根）的 RSI6 和 KDJ 的 J。"""
    big = agg(d5, rule)
    a = 1 / 6
    delta = big["close"].diff()
    up = delta.clip(lower=0).ewm(alpha=a, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=a, adjust=False).mean()
    low8 = big["low"].rolling(8).min()
    high8 = big["high"].rolling(8).max()
    k, d, _ = zhang.kdj(big)
    prev = pd.DataFrame({"up": up, "dn": dn, "c": big["close"], "l8": low8, "h8": high8, "k": k, "d": d})
    prev.index = prev.index + pd.Timedelta(rule)  # 这些值在下一根大 K 线开始时可用
    start = d5.index.floor(rule)
    p = prev.reindex(start)
    p.index = d5.index
    g = d5.groupby(start)
    ph = g["high"].cummax()
    pl = g["low"].cummin()
    c = d5["close"]
    dl = c - p["c"]
    u = p["up"] * (1 - a) + a * dl.clip(lower=0)
    w = p["dn"] * (1 - a) + a * (-dl).clip(lower=0)
    rsi = 100 - 100 / (1 + u / w.replace(0, np.nan))
    lo = np.minimum(p["l8"], pl)
    hi = np.maximum(p["h8"], ph)
    rsv = ((c - lo) / (hi - lo).replace(0, np.nan) * 100).fillna(50)
    kk = p["k"] * 2 / 3 + rsv / 3
    dd = p["d"] * 2 / 3 + kk / 3
    return rsi, 3 * kk - 2 * dd


def closed(d5, rule, s):
    """把大周期已收盘 K 线上算出的序列 s 对齐到 5 分钟（收盘后才可用）。"""
    s = s.copy()
    s.index = s.index + pd.Timedelta(rule)
    return s.reindex(d5.index, method="ffill")


def build():
    d1 = load_1m("BTCUSDT_perp_1m.csv.gz")
    d5 = zhang.signals(zhang.add_indicators(agg(d1, "5min").assign(
        taker_buy_volume=0.0)))
    for tf in ("15min", "30min", "1h", "4h"):
        d5[f"rsi_{tf}"], d5[f"j_{tf}"] = live_osc(d5, tf)
    for tf in ("30min", "1h"):
        b = agg(d5, tf)
        ma7 = b["close"].rolling(7).mean()
        d5[f"ph_{tf}"] = closed(d5, tf, np.sign(ma7 - ma7.shift(1)))
    h4 = agg(d5, "4h")
    ma99 = h4["close"].rolling(99).mean()
    d5["ma99_4h_dir"] = closed(d5, "4h", np.sign(ma99 - ma99.shift(3)))
    d5["ma99_4h"] = closed(d5, "4h", ma99)
    h1 = agg(d5, "1h")
    d5["atr1h"] = closed(d5, "1h", zhang.atr(h1))
    return d1, d5


# ---------------- 结果统计 ----------------

def dedupe(mask, gap):
    """同方向信号 gap 根 5 分钟内只算第一次。"""
    idx = np.flatnonzero(mask)
    keep, last = [], -10**9
    for t in idx:
        if t - last >= gap:
            keep.append(t)
            last = t
    out = np.zeros(len(mask), bool)
    out[keep] = True
    return out


def forward(d5, mask, side, gap=12):
    """进场后 15 分 / 30 分 / 1 小时 / 4 小时的涨跌（按方向，已是「对的方向为正」），不含手续费。"""
    m = dedupe(np.asarray(mask, bool) & (d5.index >= START), gap)
    o = d5["open"].to_numpy()
    c = d5["close"].to_numpy()
    idx = np.flatnonzero(m)
    idx = idx[idx + 49 < len(d5)]
    sg = 1 if side == "long" else -1
    res = {}
    for name, h in (("15m", 3), ("30m", 6), ("1h", 12), ("4h", 48)):
        r = sg * (c[idx + h] / o[idx + 1] - 1) * 100
        res[name] = r
    return idx, res


def trade(d5, idx, side, exit_rule, max_bars=48, stop_atr=None):
    """逐笔模拟：下一根开盘进场；exit_rule(t, e) 在第 t 根收盘为真就在下一根开盘走（e = 进场那根）；可选 1 小时 ATR 止损。"""
    o, h, l = (d5[k].to_numpy() for k in ("open", "high", "low"))
    atr = d5["atr1h"].to_numpy()
    sg = 1 if side == "long" else -1
    out, busy = [], -1
    for t in idx:
        e = t + 1
        if e <= busy or e + max_bars + 1 >= len(d5):
            continue
        px = o[e]
        stop = px - sg * stop_atr * atr[t] if stop_atr else None
        x = None
        for j in range(e, e + max_bars):
            if stop is not None and ((l[j] <= stop) if sg > 0 else (h[j] >= stop)):
                x, xj = stop, j
                break
            if exit_rule(j, e):
                x, xj = o[j + 1], j + 1
                break
        if x is None:
            xj = e + max_bars
            x = o[xj]
        out.append((t, sg * (x / px - 1) * 100 - FEE, xj - e))
        busy = xj
    return out


def show(d5, name, mask, side, exits=True):
    idx, r = forward(d5, mask, side)
    n = len(idx)
    if n < 5:
        say(f"  {name:<34} {side:<5} 次数 {n}（太少）")
        return
    yrs = (d5.index[-1] - pd.Timestamp(START, tz="UTC")).days / 365.25
    cells = []
    for k, v in r.items():
        cells.append(f"{k} 对 {np.mean(v > 0) * 100:4.0f}% 均 {np.mean(v):+.3f}%")
    say(f"  {name:<34} {side:<5} 每年 {n / yrs:5.0f} 次 | " + " | ".join(cells))
    if not exits:
        return
    rsi, j = d5["rsi6"].to_numpy(), d5["j"].to_numpy()
    opp = (lambda t, e=0: rsi[t] > 80 or j[t] > 110) if side == "long" else (lambda t, e=0: rsi[t] < 20 or j[t] < -5)
    for label, rule, st in (("拿 1 小时", lambda t, e=0: False, None),
                            ("5 分反向极值就走（最长 4h）", opp, None),
                            ("同上 + 1 ATR 止损", opp, 1.0)):
        mb = 12 if label == "拿 1 小时" else 48
        tr = trade(d5, idx, side, rule, mb, st)
        p = np.array([x[1] for x in tr])
        yr = pd.Series(p, index=d5.index[[x[0] for x in tr]]).groupby(lambda x: x.year).mean()
        pos = int((yr > 0).sum())
        say(f"      {label:<26} 扣费每笔 {p.mean():+.3f}%  胜率 {np.mean(p > 0) * 100:3.0f}%  "
            f"持有中位 {np.median([x[2] for x in tr]) * 5:.0f} 分  年份为正 {pos}/{len(yr)}")


def all_out(d5, short):
    """5 分、15 分、30 分、1 小时、4 小时每个周期 RSI6 或 J 有一项在区间外（5 分用 80/20、110/-5，其余 70/20、100/0）。"""
    m = (d5["rsi6"] > 80) | (d5["j"] > 110) if short else (d5["rsi6"] < 20) | (d5["j"] < -5)
    for tf in ("15min", "30min", "1h", "4h"):
        r, j = d5[f"rsi_{tf}"], d5[f"j_{tf}"]
        m &= ((r > 70) | (j > 100)) if short else ((r < 20) | (j < 0))
    return m


def main():
    d1, d5 = build()
    say(f"数据：{d5.index[0]} → {d5.index[-1]}，统计从 {START} 开始；手续费 {FEE}% 往返")
    r5, j5 = d5["rsi6"], d5["j"]
    r15, j15 = d5["rsi_15min"], d5["j_15min"]
    bias = d5["ma99_4h_dir"]
    up_ph = (d5["ph_1h"] > 0) & (d5["ph_30min"] > 0)
    dn_ph = (d5["ph_1h"] < 0) & (d5["ph_30min"] < 0)

    # 10/28 版
    s5 = (j5 > 110) | (r5 > 80)
    l5 = (j5 < -5) | (r5 < 20)
    s15 = (j15 > 100) | (r15 > 70)
    l15 = (j15 < 0) | (r15 < 20)
    # 10/28 补充：同一个指标在 5 分和 15 分同时在区间外才算（RSI 优先：两个周期 RSI 都在区间外一定报，KDJ 不用满足）
    rsi_s, rsi_l = (r5 > 80) & (r15 > 70), (r5 < 20) & (r15 < 20)
    kdj_s, kdj_l = (j5 > 110) & (j15 > 100), (j5 < -5) & (j15 < 0)
    base_s, base_l = rsi_s | kdj_s, rsi_l | kdj_l
    # 量价背离：最近 6 根创了 2 小时新高（新低），但这 6 根里最大的量还不到之前 2 小时最大量的 9 成
    v = d5["volume"]
    nh = d5["high"].rolling(6).max() >= d5["high"].shift(6).rolling(24).max()
    nl = d5["low"].rolling(6).min() <= d5["low"].shift(6).rolling(24).min()
    vol_hi = v.rolling(6).max() < 0.9 * v.shift(6).rolling(24).max()
    div_s, div_l = nh & vol_hi, nl & vol_hi
    ma7 = d5["ma7"]
    t7_s, t7_l = ma7 < ma7.shift(1), ma7 > ma7.shift(1)

    say("\n== 1. 10/28 版：5 分 + 15 分同时在区间外 ==")
    say("（「对」= 方向对的比例，「均」= 平均涨跌，均未扣费；下面三行是三种卖法扣费后的结果）")
    show(d5, "只看 5 分（对照）", s5, "short", False)
    show(d5, "只看 5 分（对照）", l5, "long", False)
    show(d5, "5 分 + 15 分", base_s, "short")
    show(d5, "5 分 + 15 分", base_l, "long")
    show(d5, "  其中 RSI 两周期都在区间外", rsi_s, "short")
    show(d5, "  其中 RSI 两周期都在区间外", rsi_l, "long")
    show(d5, "  只有 KDJ 两周期在区间外", kdj_s & ~rsi_s, "short")
    show(d5, "  只有 KDJ 两周期在区间外", kdj_l & ~rsi_l, "long")
    show(d5, "  旧口径（两周期各有一项即可）", s5 & s15, "short", False)
    show(d5, "  旧口径（两周期各有一项即可）", l5 & l15, "long", False)
    show(d5, "+ 4h MA99 同向", base_s & (bias < 0), "short")
    show(d5, "+ 4h MA99 同向", base_l & (bias > 0), "long")
    show(d5, "+ 4h 同向 + 1h/30m 正在反弹", base_s & (bias < 0) & up_ph, "short")
    show(d5, "+ 4h 同向 + 1h/30m 正在回调", base_l & (bias > 0) & dn_ph, "long")
    show(d5, "逆 4h MA99（对照）", base_s & (bias > 0), "short")
    show(d5, "逆 4h MA99（对照）", base_l & (bias < 0), "long")
    show(d5, "+ 量价背离（强提示）", base_s & div_s, "short")
    show(d5, "+ 量价背离（强提示）", base_l & div_l, "long")
    show(d5, "+ 量价背离 + MA7 拐头", base_s & div_s & t7_s, "short")
    show(d5, "+ 量价背离 + MA7 拐头", base_l & div_l & t7_l, "long")
    # 按顺序：先指标（最近 6 根内出现过 5+15 分区间外）→ 量价背离 → 这一根 MA7 刚拐头
    def recent(m, n=6):
        return m.astype(float).rolling(n).max().fillna(0).astype(bool)
    turn_s = t7_s & ~t7_s.shift(1).fillna(False).astype(bool)
    turn_l = t7_l & ~t7_l.shift(1).fillna(False).astype(bool)
    seq_s = recent(base_s) & recent(div_s) & turn_s
    seq_l = recent(base_l) & recent(div_l) & turn_l
    show(d5, "顺序：指标→背离→MA7 刚拐头", seq_s, "short")
    show(d5, "顺序：指标→背离→MA7 刚拐头", seq_l, "long")
    show(d5, "顺序全套 + 4h MA99 同向", seq_s & (bias < 0), "short")
    show(d5, "顺序全套 + 4h MA99 同向", seq_l & (bias > 0), "long")
    show(d5, "指标→MA7 刚拐头（不要背离）", recent(base_s) & turn_s, "short")
    show(d5, "指标→MA7 刚拐头（不要背离）", recent(base_l) & turn_l, "long")

    # 「买进去差不多就是最高 / 最低点」：进场价离之后 1 小时的最低（做多）/ 最高（做空）有多远
    for side, m in (("long", base_l), ("short", base_s)):
        idx, _ = forward(d5, m, side)
        o_, l_, h_ = (d5[k].to_numpy() for k in ("open", "low", "high"))
        if side == "long":
            gap = [(o_[t + 1] / l_[t + 1:t + 13].min() - 1) * 100 for t in idx]
        else:
            gap = [(1 - o_[t + 1] / h_[t + 1:t + 13].max()) * 100 for t in idx]
        gap = np.array(gap)
        say(f"  {'做多' if side == 'long' else '做空'}进场后 1 小时内还会再往不利方向走：中位 {np.median(gap):.2f}%，"
            f"不到 0.1% 的只占 {np.mean(gap < 0.1) * 100:.0f}%，五次里有一次超过 {np.percentile(gap, 80):.2f}%")
    show(d5, "两周期都极端（J>110 且 RSI>80）", (j5 > 110) & (r5 > 80) & (j15 > 110) & (r15 > 80), "short")
    show(d5, "两周期都极端（J<-5 且 RSI<20）", (j5 < -5) & (r5 < 20) & (j15 < -5) & (r15 < 20), "long")

    say("\n== 1b. 10/27 版：再加 30 分 / 1 小时也在区间外（「妥上加妥」） ==")
    s30 = (d5["j_30min"] > 100) | (d5["rsi_30min"] > 70)
    l30 = (d5["j_30min"] < 0) | (d5["rsi_30min"] < 20)
    s1h = (d5["j_1h"] > 100) | (d5["rsi_1h"] > 70)
    l1h = (d5["j_1h"] < 0) | (d5["rsi_1h"] < 20)
    show(d5, "5+15+30 分", base_s & s30, "short")
    show(d5, "5+15+30 分", base_l & l30, "long")
    show(d5, "5+15+30 分+1 小时", base_s & s30 & s1h, "short")
    show(d5, "5+15+30 分+1 小时", base_l & l30 & l1h, "long")

    say("\n== 1c. 按年份：5 分 + 15 分 + 4h 同向，拿 1 小时，扣费每笔 ==")
    for side, m in (("short", base_s & (bias < 0)), ("long", base_l & (bias > 0))):
        idx, _ = forward(d5, m, side)
        tr = trade(d5, idx, side, lambda t, e=0: False, 12)
        s = pd.Series([x[1] for x in tr], index=d5.index[[x[0] for x in tr]])
        g = s.groupby(s.index.year).agg(["count", "mean"])
        say(f"  {side}: " + "  ".join(f"{y}: {int(r['count'])} 笔 {r['mean']:+.3f}%" for y, r in g.iterrows()))

    say("\n== 1d. 最近一周（10/22–10/28）触发明细（5 分 + 15 分，东京时间） ==")
    for side, m in (("空", base_s), ("多", base_l)):
        mm = dedupe(np.asarray(m & (d5.index >= "2026-10-21T15:00Z"), bool), 12)
        for t in np.flatnonzero(mm):
            if t + 13 >= len(d5):
                continue
            px = d5["open"].iat[t + 1]
            r1 = (d5["close"].iat[t + 12] / px - 1) * 100 * (1 if side == "多" else -1)
            mfe = ((d5["high"].iloc[t + 1:t + 13].max() / px - 1) * 100 if side == "多"
                   else (1 - d5["low"].iloc[t + 1:t + 13].min() / px) * 100)
            say(f"  {d5.index[t].tz_convert('Asia/Tokyo'):%m-%d %H:%M} {side} 进场 {px:,.0f}  "
                f"1 小时后 {r1:+.2f}%  1 小时内最多顺向 {mfe:.2f}%  4h MA99 {'向上' if bias.iat[t] > 0 else '向下'}")

    # ---------- 1e. 按指标卖（MA7 拐头、出现反向信号等） ----------
    say("\n== 1e. 按指标卖：进场同上（5 分 + 15 分），卖出看盘面信号，最长拿 24 小时 ==")
    say("（每种卖法都是信号出现那根收盘后、下一根开盘市价卖；扣 0.10% 手续费）")
    c_ = d5["close"].to_numpy(); m7 = d5["ma7"].to_numpy(); r5a, j5a = r5.to_numpy(), j5.to_numpy()
    sgS, sgL = base_s.to_numpy(), base_l.to_numpy()
    div_sa, div_la = div_s.fillna(False).to_numpy(), div_l.fillna(False).to_numpy()
    def exits(side):
        lg = side == "long"
        up = lambda t: m7[t] > m7[t - 1]
        dn = lambda t: m7[t] < m7[t - 1]
        against = dn if lg else up
        favor = up if lg else dn
        opp5 = (lambda t: r5a[t] > 80 or j5a[t] > 110) if lg else (lambda t: r5a[t] < 20 or j5a[t] < -5)
        oppsig = (lambda t: sgS[t]) if lg else (lambda t: sgL[t])
        oppdiv = (lambda t: div_sa[t]) if lg else (lambda t: div_la[t])
        cross = (lambda t: c_[t] < m7[t]) if lg else (lambda t: c_[t] > m7[t])
        def turned_back(t, e):        # MA7 先朝有利方向拐过，之后又拐回来
            return against(t) and any(favor(k) for k in range(e, t))
        def any_opp(t, e):            # 张主任做空 / 做多条件里出现任意一项：5 分反向超买超卖、量价反向背离、MA7 拐回
            return opp5(t) or oppdiv(t) or turned_back(t, e)
        return [
            ("MA7 一往不利方向拐就卖", lambda t, e: against(t)),
            ("MA7 先拐向有利、再拐回来就卖", turned_back),
            ("收盘跌破 / 站上 MA7 就卖", lambda t, e: cross(t)),
            ("5 分出现反向超买 / 超卖就卖", lambda t, e: opp5(t)),
            ("出现完整反向信号（5+15 分）就卖", lambda t, e: oppsig(t)),
            ("反向条件任意一项出现就卖", any_opp),
            ("先有浮盈，MA7 拐回就卖", lambda t, e: turned_back(t, e) and (c_[t] > c_[e] if lg else c_[t] < c_[e])),
        ]
    for side, m in (("short", base_s), ("long", base_l), ("short", base_s & (bias < 0)), ("long", base_l & (bias > 0))):
        idx, _ = forward(d5, m, side)
        tag = ("做空" if side == "short" else "做多") + ("（顺 4h MA99）" if len(idx) < 4000 and m is not base_s and m is not base_l else "")
        say(f"  {tag}：")
        for label, rule in exits(side):
            for st in (None, 1.0):
                tr = trade(d5, idx, side, rule, 288, st)
                p = np.array([x[1] for x in tr])
                yr = pd.Series(p, index=d5.index[[x[0] for x in tr]]).groupby(lambda x: x.year).mean()
                say(f"    {label + ('' if st is None else ' + 1 ATR 止损'):<34} 胜率 {np.mean(p > 0) * 100:3.0f}%  扣费每笔 {p.mean():+.3f}%  "
                    f"不扣费 {p.mean() + FEE:+.3f}%  持有中位 {np.median([x[2] for x in tr]) * 5:4.0f} 分  年份为正 {int((yr > 0).sum())}/{len(yr)}")

    # ---------- 2. 全周期超买 ----------
    say("\n== 2. 5 分到 4 小时全部严重超买 / 超卖（10/28 17:53「全仓梭哈做空」） ==")
    allhot = (r5 > 80) & (r15 > 80) & (d5["rsi_1h"] > 80) & (d5["rsi_4h"] > 80)
    allcold = (r5 < 20) & (r15 < 20) & (d5["rsi_1h"] < 20) & (d5["rsi_4h"] < 20)
    show(d5, "RSI6 5m/15m/1h/4h 全 > 80", allhot, "short")
    show(d5, "RSI6 5m/15m/1h/4h 全 < 20", allcold, "long")
    hot2 = allhot & (r5 > 90)
    show(d5, "同上且 5 分 RSI6 > 90", hot2, "short")
    idx, r = forward(d5, allhot, "short", gap=288)
    say(f"  一天只算一次：共 {len(idx)} 次，4 小时后跌的 {np.mean(r['4h'] > 0) * 100:.0f}%，"
        f"中位 {np.median(r['4h']):+.2f}%，最差 {r['4h'].min():+.2f}%（做空方向）")
    h = d5["high"].to_numpy()
    o = d5["open"].to_numpy()
    worst = [(h[t + 1:t + 49].max() / o[t + 1] - 1) * 100 for t in idx]
    say(f"  进场后 4 小时内先往上冲的幅度：中位 {np.median(worst):.2f}%，五次里最差一次 {np.percentile(worst, 80):.2f}%，"
        f"最大 {max(worst):.2f}%（50 倍杠杆约 2% 就爆仓）")

    # 全周期超卖做多：一天只算一次，看是不是靠少数几次暴跌撑起来的
    idx, r = forward(d5, allcold, "long", gap=288)
    s = pd.Series(r["1h"] - FEE, index=d5.index[idx])
    say(f"  全周期超卖做多，一天只算一次：{len(idx)} 天，拿 1 小时扣费均 {s.mean():+.3f}%、中位 {s.median():+.3f}%、"
        f"胜率 {np.mean(s > 0) * 100:.0f}%；去掉最好的 5 次后均 {s.sort_values().iloc[:-5].mean():+.3f}%")
    say("    按年：" + "  ".join(f"{y}: {len(g)} 天 {g.mean():+.3f}%" for y, g in s.groupby(s.index.year)))
    lo = d5["low"].to_numpy()
    o_ = d5["open"].to_numpy()
    dd = np.array([(1 - lo[t + 1:t + 13].min() / o_[t + 1]) * 100 for t in idx])
    say(f"    进场后 1 小时内先再跌：中位 {np.median(dd):.2f}%，五次里最差一次 {np.percentile(dd, 80):.2f}%，最大 {dd.max():.2f}%")

    # 张主任口径（10/28 晚）：5 分、15 分、30 分、1 小时、4 小时每个周期都在区间外（RSI6 或 J 任一项）
    say("\n== 2b. 张主任口径：5 分 / 15 分 / 30 分 / 1 小时 / 4 小时全部在区间外（面板「极端」提醒用这组数） ==")
    o_, h_, l_, c_ = (d5[k].to_numpy() for k in ("open", "high", "low", "close"))
    for side, m in (("short", all_out(d5, True)), ("long", all_out(d5, False))):
        idx = np.flatnonzero(dedupe(m.to_numpy() & (d5.index >= START), 288))
        idx = idx[idx + 289 < len(d5)]
        sg = 1 if side == "long" else -1
        r4 = sg * (c_[idx + 48] / o_[idx + 1] - 1) * 100 - FEE
        adv = np.array([((h_[t + 1:t + 49].max() / o_[t + 1] - 1) if sg < 0 else (1 - l_[t + 1:t + 49].min() / o_[t + 1])) * 100 for t in idx])
        yr = pd.Series(r4, index=d5.index[idx]).groupby(lambda x: x.year).mean()
        say(f"  {'全部超买做空' if sg < 0 else '全部超卖做多'}：{len(idx)} 天，4 小时后方向对 {np.mean(r4 + FEE > 0) * 100:.0f}%，扣费均 {r4.mean():+.3f}%，"
            f"年份为正 {int((yr > 0).sum())}/{len(yr)}")
        say(f"    4 小时内先反向走：中位 {np.median(adv):.2f}%，五次里有一次超过 {np.percentile(adv, 80):.2f}%，最大 {adv.max():.1f}%；"
            f"≥1%（100 倍爆仓）{np.mean(adv >= 1) * 100:.0f}%，≥2%（50 倍爆仓）{np.mean(adv >= 2) * 100:.0f}%")

    # ---------- 3. 4h MA99 当压力位 ----------
    say("\n== 3. 4 小时 MA99 是不是压力 / 支撑 ==")
    ma = d5["ma99_4h"]
    c = d5["close"]
    below_long = (c < ma).rolling(48).min().astype(bool)
    above_long = (c > ma).rolling(48).min().astype(bool)
    for lvl, name in ((1.0, "MA99 本身"), (1.01, "MA99 上方 1%（对照）"), (0.99, "MA99 下方 1%（对照）")):
        line = ma * lvl
        touch_up = below_long.shift(1).fillna(False) & (d5["high"] >= line) & (c.shift(1) < line)
        touch_dn = above_long.shift(1).fillna(False) & (d5["low"] <= line) & (c.shift(1) > line)
        for side, m, back in (("short", touch_up, lambda t, L: d5["close"].iat[t + 48] < L),
                              ("long", touch_dn, lambda t, L: d5["close"].iat[t + 48] > L)):
            idx, r = forward(d5, m, side, gap=288)
            ln = line.to_numpy()
            rej = np.mean([back(t, ln[t]) for t in idx]) * 100
            say(f"  {name:<20} {'从下往上碰' if side == 'short' else '从上往下碰'}  {len(idx):4d} 次  "
                f"4 小时后回到线{'下' if side == 'short' else '上'} {rej:3.0f}%  按反向做 4h 均 {np.mean(r['4h']):+.3f}%")

    # ---------- 4. 聊天里其他判断 ----------
    say("\n== 4. 其他判断 ==")
    show(d5, "10/24：RSI6>70 或 J>100 做空", (r5 > 70) | (j5 > 100), "short", False)
    show(d5, "10/24：RSI6<20 或 J<0 做多", (r5 < 20) | (j5 < 0), "long", False)
    show(d5, "10/24：RSI6>90 且 J>120「闭眼空」", (r5 > 90) & (j5 > 120), "short")
    show(d5, "10/24：RSI6<20 且 J<-10「闭眼多」", (r5 < 20) & (j5 < -10), "long")
    b15 = agg(d5, "15min")
    ma25_15 = b15["close"].rolling(25).mean()
    below25 = d5["close"] < closed(d5, "15min", ma25_15)
    show(d5, "10/22：15 分 RSI>70 且站不上 MA25", (r15 > 70) & below25, "short")
    show(d5, "  对照：15 分 RSI>70 且在 MA25 上", (r15 > 70) & ~below25, "short", False)
    # 阶梯式下跌 / 上涨：连续三根同色实体 K 线，每根开盘贴着上一根收盘、没有反抽
    bear = d5["close"] < d5["open"]
    bull = d5["close"] > d5["open"]
    atr5 = d5["atr"]
    stair_dn = bear & bear.shift(1) & bear.shift(2) & (d5["high"] <= d5["close"].shift(1) + 0.1 * atr5) & (
        d5["high"].shift(1) <= d5["close"].shift(2) + 0.1 * atr5) & ((d5["close"].shift(3) - d5["close"]) > 1.5 * atr5)
    stair_up = bull & bull.shift(1) & bull.shift(2) & (d5["low"] >= d5["close"].shift(1) - 0.1 * atr5) & (
        d5["low"].shift(1) >= d5["close"].shift(2) - 0.1 * atr5) & ((d5["close"] - d5["close"].shift(3)) > 1.5 * atr5)
    show(d5, "10/22：三根阶梯下跌后顺势空", stair_dn, "short", False)
    show(d5, "10/22：三根阶梯上涨后顺势多", stair_up, "long", False)
    # 高点一次比一次低 + 无量拉升 → 诱多
    hh = b15["high"]
    piv = (hh.shift(1) > hh.shift(2)) & (hh.shift(1) > hh)  # 15 分钟摆动高点（右边一根确认）
    pv = hh.shift(1)[piv]
    last_ph = pv.reindex(b15.index).ffill()
    prev_ph = pv.shift(1).reindex(b15.index).ffill()
    lower_highs = closed(d5, "15min", (last_ph < prev_ph) & (pv.shift(1).shift(1).reindex(b15.index).ffill() > prev_ph))
    vol_med = v.rolling(288).median()
    rally = (d5["close"] - d5["low"].rolling(12).min() > 1.0 * d5["atr1h"]) & (v.rolling(12).mean() < vol_med)
    rally_v = (d5["close"] - d5["low"].rolling(12).min() > 1.0 * d5["atr1h"]) & (v.rolling(12).mean() >= vol_med)
    show(d5, "10/24：高点降低 + 无量拉升 → 空", lower_highs.fillna(False).astype(bool) & rally, "short", False)
    show(d5, "  对照：同样拉升但放量", lower_highs.fillna(False).astype(bool) & rally_v, "short", False)
    show(d5, "  对照：无量拉升（不管高点）", rally, "short", False)

    with open(os.path.join(HERE, "results_zhang_mtf.txt"), "w") as f:
        f.write("\n".join(OUT) + "\n")


if __name__ == "__main__":
    main()
