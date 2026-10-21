"""统一规则回测：严格按面板执行方式模拟，规则参数来自 rules_spec.json（面板、模拟盘共用同一份）。

用法：.venv/bin/python rules_backtest.py
输出：results/rules_backtest.csv（汇总）、results/rules_trades.csv（逐笔）
"""
import json
import os

import numpy as np
import pandas as pd

import zhang
from direction_model_full import load_1m, to5m

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = json.load(open(os.path.join(HERE, "..", "rules_spec.json"), encoding="utf-8"))
MAKER, TAKER = SPEC["fees"]["maker_pct"], SPEC["fees"]["taker_pct"]


def load():
    d5 = zhang.signals(zhang.add_indicators(to5m(load_1m("BTCUSDT_perp_1m.csv.gz"))))
    oos = pd.read_csv(os.path.join(HERE, "data", "oos_probs_5m.csv.gz"), index_col=0, parse_dates=True)
    d5 = d5.join(oos, how="inner")
    # 1 小时趋势（只用已收盘的 1h K 线）
    h1 = d5[["close"]].resample("1h").last().dropna()
    h1["ma25"] = h1.close.rolling(25).mean()
    up = (h1.close > h1.ma25) & (h1.ma25 > h1.ma25.shift(6)); dn = (h1.close < h1.ma25) & (h1.ma25 < h1.ma25.shift(6))
    tr = pd.DataFrame({"up1h": up, "dn1h": dn}); tr.index = tr.index + pd.Timedelta("1h")
    d5 = d5.join(tr.reindex(d5.index, method="ffill").fillna(False))
    ny = d5.index.tz_convert("America/New_York")
    mins = ny.hour * 60 + ny.minute - 570
    d5["weekend"] = ny.weekday >= 5
    d5["lowvol"] = d5.volume < 0.5 * d5.volume.rolling(288).median()
    d5["pre_open"] = (ny.weekday < 5) & (mins >= -SPEC["event_block_min"]) & (mins < 0)   # 美股开盘前 1h（事件代理）
    hi24, lo24 = d5.high.rolling(288).max(), d5.low.rolling(288).min()
    d5["near_sup"] = ((d5.close - lo24) / d5.close < 0.003) | ((d5.close % 1000) / d5.close < 0.003)
    d5["near_res"] = ((hi24 - d5.close) / d5.close < 0.003) | (((1000 - d5.close % 1000) % 1000) / d5.close < 0.003)
    return d5


def rule_a(d, use_stop):
    s = SPEC["rule_a"]
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    p4, blk = d.p4h.to_numpy(), d.pre_open.to_numpy()
    n, out, t, missed = len(d), [], 0, 0
    W, H = s["limit_valid_bars"], s["hold_bars"]
    while t < n - H - 2 * W - 2:
        side = "long" if p4[t] >= s["p_long"] else "short" if p4[t] <= s["p_short"] else None
        if side is None or blk[t]:
            t += 1; continue
        px = c[t]
        fill = next((k for k in range(t + 1, t + 1 + W) if (l[k] < px if side == "long" else h[k] > px)), None)
        if fill is None:
            missed += 1; t += 1; continue
        sgn = 1 if side == "long" else -1
        stop = px * (1 - sgn * s["insurance_stop_pct"] / 100)
        end, exit_px, fee = fill + H, None, MAKER
        for k in range(fill, end + 1):
            if use_stop and ((l[k] <= stop) if side == "long" else (h[k] >= stop)):
                exit_px, fee = stop, MAKER + TAKER; end = k; break
        if exit_px is None:
            lim = c[end]
            got = next((k for k in range(end + 1, end + 1 + W) if (h[k] > lim if side == "long" else l[k] < lim)), None)
            exit_px, fee = (lim, 2 * MAKER) if got is not None else (c[end + W], MAKER + TAKER)
            end = got if got is not None else end + W
        ret = sgn * (exit_px / px - 1) * 100 - fee
        out.append(dict(rule="A" + ("+保险止损" if use_stop else ""), time=d.index[t], side=side, ret=ret))
        t = end + 1
    return out, missed


def rule_b(d, location=False):
    s = SPEC["rule_b"]
    o, h, l, c, atr = (d[k].to_numpy() for k in ("open", "high", "low", "close", "atr"))
    hi12, lo12 = d.high.rolling(12).max().to_numpy(), d.low.rolling(12).min().to_numpy()
    pm = ((d.p15 + d.p1h) / 2).to_numpy()
    sigL = (d.long_B & ~d.dn1h & ~d.weekend & ~d.lowvol & ~d.pre_open & (pm >= 0.5)).to_numpy()
    sigS = (d.short_B & ~d.up1h & ~d.weekend & ~d.lowvol & ~d.pre_open & (pm <= 0.5)).to_numpy()
    if location:
        sigL &= d.near_sup.to_numpy(); sigS &= d.near_res.to_numpy()
    n, out, busy = len(d), [], -1
    for t in np.flatnonzero(sigL | sigS):
        e = t + 1
        if e >= n or e <= busy:
            continue
        side = "long" if sigL[t] else "short"; sgn = 1 if side == "long" else -1
        px = o[e]
        risk = max((px - lo12[t] + s["stop_atr"] * atr[t]) if side == "long" else (hi12[t] + s["stop_atr"] * atr[t] - px), px * 0.001)
        stop, tp = px - sgn * risk, px + sgn * s["tp_R"] * risk
        exit_px, fee, j = None, TAKER + TAKER, e
        for j in range(e, min(e + s["max_hold_bars"], n)):
            if (l[j] <= stop) if side == "long" else (h[j] >= stop):
                exit_px = stop; break
            if (h[j] >= tp) if side == "long" else (l[j] <= tp):
                exit_px, fee = tp, TAKER + MAKER; break
        if exit_px is None:
            exit_px = c[j]
        out.append(dict(rule="B" + "+关键价位（等待计划）" * location, time=d.index[t], side=side, ret=sgn * (exit_px / px - 1) * 100 - fee))
        busy = j
    return out


def summarize(t, label, missed=None):
    rows = []
    for side, g in [("全部", t)] + [("做多" if s == "long" else "做空", t[t.side == s]) for s in ("long", "short")]:
        if not len(g):
            continue
        by = g.groupby(g.time.dt.year).ret.mean()
        rows.append(dict(规则=label, 方向=side, 笔数=len(g), 每年=round(len(g) / g.time.dt.year.nunique()), 胜率=round((g.ret > 0).mean() * 100, 1),
                         每笔pct=round(g.ret.mean(), 3), t值=round(g.ret.mean() / (g.ret.std() / np.sqrt(len(g))), 2),
                         正收益年数=f"{(by > 0).sum()}/{len(by)}", 最差年=round(by.min(), 3),
                         挂单未成交=missed if side == "全部" else None))
    return rows


def main():
    d = load()
    print(f"{len(d):,} 根 5m，{d.index[0]} → {d.index[-1]}", flush=True)
    rows, trades = [], []
    for use_stop in (False, True):
        tr, missed = rule_a(d, use_stop); trades += tr
        rows += summarize(pd.DataFrame(tr), tr[0]["rule"], missed)
    for loc in (False, True):
        tr = rule_b(d, loc); trades += tr
        if tr:
            rows += summarize(pd.DataFrame(tr), tr[0]["rule"])
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(HERE, "results", "rules_backtest.csv"), index=False)
    pd.DataFrame(trades).to_csv(os.path.join(HERE, "results", "rules_trades.csv"), index=False)
    pd.set_option("display.width", 250)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
