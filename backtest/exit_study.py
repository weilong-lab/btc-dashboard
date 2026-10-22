"""拿多久、什么时候卖：固定持有时间 vs 按波动（ATR）定的退出方式。

进场：规则 A（4 小时模型概率挂单，成交才算）和规则 B（张主任完整信号，下一根开盘市价），
和 rules_backtest.py 同口径；同一规则 4 小时内只取第一次，让每种退出方式比较的是同一批单。
ATR = 进场时过去 24 小时 1h K 线平均振幅。手续费：挂单 0.02%、市价 0.05%（止盈挂单，其余市价）。

退出方式：
- 现规则：A 持有 4 小时；B 止损（近 12 根高低点外 0.5 个 5 分钟 ATR）、止盈 2R、最长 24 小时
- 止损 1 / 止盈 1 ATR（最长 24 小时）
- 止损 1 / 止盈 2 ATR（最长 24 小时）
- 移动止损 1 ATR：从进场后最有利价回撤 1 ATR 就走（最长 24 小时）
- 保本 + 移动 0.75 ATR：先止损 1 ATR，顺势 0.5 ATR 后止损提到进场价，之后从最有利价回撤 0.75 ATR 就走
- 信号反转：15 分钟和 1 小时模型平均概率翻到反方向就走，止损 1.6 ATR，最长 24 小时

用法：.venv/bin/python exit_study.py
"""
import numpy as np
import pandas as pd

from rules_backtest import load, SPEC, MAKER, TAKER

MAXB = 288   # 24 小时（5 分钟 K 线）


def entries(d):
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    p4, blk = d.p4h.to_numpy(), d.pre_open.to_numpy()
    A, W, out = SPEC["rule_a"], SPEC["rule_a"]["limit_valid_bars"], []
    last = -10 ** 9
    for t in range(len(d) - MAXB - W - 2):
        side = "long" if p4[t] >= A["p_long"] else "short" if p4[t] <= A["p_short"] else None
        if side is None or blk[t] or t - last < 48:
            continue
        px = c[t]
        fill = next((k for k in range(t + 1, t + 1 + W) if (l[k] < px if side == "long" else h[k] > px)), None)
        if fill is None:
            continue
        out.append(("A", t, fill, side, px, MAKER))
        last = t
    B = SPEC["rule_b"]
    pm = ((d.p15 + d.p1h) / 2).to_numpy()
    sigL = (d.long_B & ~d.dn1h & ~d.weekend & ~d.lowvol & ~d.pre_open & (pm >= 0.5)).to_numpy()
    sigS = (d.short_B & ~d.up1h & ~d.weekend & ~d.lowvol & ~d.pre_open & (pm <= 0.5)).to_numpy()
    last = -10 ** 9
    for t in np.flatnonzero(sigL | sigS):
        if t + 1 + MAXB >= len(d) or t - last < 48:
            continue
        out.append(("B", t, t + 1, "long" if sigL[t] else "short", o[t + 1], TAKER))
        last = t
    return out


def simulate(d, ent, atr1h):
    o, h, l, c, atr5 = (d[k].to_numpy() for k in ("open", "high", "low", "close", "atr"))
    pm = ((d.p15 + d.p1h) / 2).to_numpy()
    hi12, lo12 = d.high.rolling(12).max().to_numpy(), d.low.rolling(12).min().to_numpy()
    B = SPEC["rule_b"]
    rows = []
    for rule, t, e, side, px, fee_in in ent:
        s, a = (1 if side == "long" else -1), atr1h[t]
        if not np.isfinite(a):
            continue

        def run(stop_d, tp_d=None, trail=None, be=None, flip=False, maxb=MAXB):
            stop = px - s * stop_d
            best = px
            for k in range(e, min(e + maxb, len(d))):
                hk, lk = h[k], l[k]
                if (lk <= stop) if s > 0 else (hk >= stop):
                    return s * (stop / px - 1) * 100 - fee_in - TAKER, k - e + 1
                if tp_d is not None and ((hk >= px + tp_d) if s > 0 else (lk <= px - tp_d)):
                    return tp_d / px * 100 - fee_in - MAKER, k - e + 1
                best = max(best, hk) if s > 0 else min(best, lk)
                if be is not None and s * (best - px) >= be:
                    stop = max(stop, px) if s > 0 else min(stop, px)
                if trail is not None and (be is None or s * (best - px) >= be):
                    stop = max(stop, best - trail) if s > 0 else min(stop, best + trail)
                if flip and k > e and ((pm[k] < 0.5) if s > 0 else (pm[k] > 0.5)):
                    return s * (c[k] / px - 1) * 100 - fee_in - TAKER, k - e + 1
            k = min(e + maxb, len(d)) - 1
            return s * (c[k] / px - 1) * 100 - fee_in - TAKER, k - e + 1

        if rule == "A":
            cur = run(1e9, maxb=SPEC["rule_a"]["hold_bars"])
        else:
            risk = max((px - lo12[t] + B["stop_atr"] * atr5[t]) if s > 0 else (hi12[t] + B["stop_atr"] * atr5[t] - px), px * 0.001)
            cur = run(risk, tp_d=B["tp_R"] * risk, maxb=B["max_hold_bars"])
        res = {
            "现规则": cur,
            "止损1/止盈1 ATR": run(a, a),
            "止损1/止盈2 ATR": run(a, 2 * a),
            "移动止损1 ATR": run(a, trail=a),
            "保本+移动0.75 ATR": run(a, trail=0.75 * a, be=0.5 * a),
            "信号反转": run(1.6 * a, flip=True),
        }
        for k, (r, bars) in res.items():
            rows.append(dict(rule=rule, time=d.index[t], atr=a, way=k, ret=r, hours=bars * 5 / 60))
    return pd.DataFrame(rows)


def main():
    d = load()
    h1 = d[["high", "low"]].resample("1h").agg({"high": "max", "low": "min"})
    atr = (h1.high - h1.low).rolling(24).mean()
    atr.index = atr.index + pd.Timedelta("1h")
    atr1h = atr.reindex(d.index, method="ffill").to_numpy()
    ent = entries(d)
    r = simulate(d, ent, atr1h)
    r["vol"] = r.groupby("rule").atr.transform(lambda x: pd.qcut(x / x.rolling(2000, min_periods=50).median(), 3, labels=["波动低", "中", "波动高"]))
    pd.set_option("display.width", 220)
    for rule, g in r.groupby("rule"):
        print(f"\n== 规则 {rule}：{g.time.nunique()} 笔（2021–2026，同一规则 4 小时内只取第一次）")
        rows = []
        for way, x in g.groupby("way", sort=False):
            by = x.groupby(x.time.dt.year).ret.mean()
            hold = x.groupby("vol", observed=True).hours.median()
            rows.append(dict(退出方式=way, 每笔pct=round(x.ret.mean(), 3), t值=round(x.ret.mean() / (x.ret.std() / np.sqrt(len(x))), 2),
                             胜率=round((x.ret > 0).mean() * 100, 1), 正收益年数=f"{(by > 0).sum()}/{len(by)}",
                             持有中位h=round(x.hours.median(), 1), 波动低时持有h=round(hold.get("波动低", np.nan), 1), 波动高时持有h=round(hold.get("波动高", np.nan), 1)))
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
