"""急涨急跌开始后追进去，能不能吃到后面那段。

触发：过去 N 分钟（5 或 15）已走 ≥ k 个 ATR（ATR = 过去 24 小时 1h K 线平均振幅，约 400 美元），
下一分钟开盘市价顺势进场。看之后 15 / 30 / 60 分钟：
- 继续同方向的比例、平均涨跌
- 先再顺势走 0.5 ATR 还是先回吐 0.5 ATR
- 一个简单打法：止盈 1 ATR、止损 0.5 ATR、最长 30 分钟，市价进出（往返 0.10% 手续费）
另外统计：30 分钟内走 ≥ 3 ATR 的大行情，触发时已经走掉了多少、还剩多少。

以及大行情（30 分钟走 ≥3 ATR）在美东 8:30（多数美国数据公布）、9:30 美股开盘这两个时段的发生频率是平时的几倍。
结果写进 dashboard/live/context.js 的 FASTMOVE，面板「急动提醒」用。

用法：.venv/bin/python fast_move.py
"""
import numpy as np
import pandas as pd

from context_js import write_var
from direction_model_full import load_1m

FEE = 0.10   # 往返，%（市价进出）


def main():
    d = load_1m("BTCUSDT_perp_1m.csv.gz")
    d = d[d.index >= "2021-01-01"]
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    h1 = d.resample("1h").agg({"high": "max", "low": "min"})
    atr = (h1.high - h1.low).rolling(24).mean()
    atr.index = atr.index + pd.Timedelta(hours=1)
    A = atr.reindex(d.index, method="ffill").to_numpy()
    ny = d.index.tz_convert("America/New_York")
    usopen = np.asarray((ny.weekday < 5) & (((ny.hour == 9) & (ny.minute >= 30)) | ((ny.hour == 10) & (ny.minute < 30))))
    n = len(c)

    def run(N, k, mask=None, label=""):
        mv = c - np.roll(o, N - 1)                # 过去 N 根（含当前）从开盘到收盘
        mv[:N] = 0
        trig = np.abs(mv) >= k * A
        if mask is not None:
            trig &= mask
        idx = np.where(trig)[0]
        idx = idx[idx < n - 61]
        # 去重：同一波只算第一次触发（30 分钟内不重复）
        keep, last = [], -10 ** 9
        for i in idx:
            if i - last >= 30:
                keep.append(i)
                last = i
        idx = np.array(keep)
        if len(idx) < 30:
            return None
        sg = np.sign(mv[idx])
        e = o[idx + 1]                             # 下一分钟开盘进场
        res = {"触发": len(idx)}
        for m in (15, 30, 60):
            r = sg * (c[idx + m] / e - 1) * 100
            res[f"{m}m 继续%"] = round((r > 0).mean() * 100, 1)
            res[f"{m}m 平均%"] = round(r.mean(), 3)
        # 先顺势 0.5ATR 还是先回吐 0.5ATR（60 分钟内）；以及止盈 1ATR / 止损 0.5ATR / 最长 30 分钟
        first_good, pnl = [], []
        for j, i in enumerate(idx):
            a, s, en = A[i], sg[j], e[j]
            fg, out = None, None
            for t in range(i + 1, min(i + 61, n)):
                up = (h[t] - en) if s > 0 else (en - l[t])
                dn = (en - l[t]) if s > 0 else (h[t] - en)
                if fg is None:
                    if dn >= 0.5 * a:
                        fg = False
                    elif up >= 0.5 * a:
                        fg = True
                if out is None and t <= i + 30:
                    if dn >= 0.5 * a:
                        out = -0.5 * a / en * 100
                    elif up >= 1.0 * a:
                        out = 1.0 * a / en * 100
                    elif t == i + 30:
                        out = s * (c[t] / en - 1) * 100
                if fg is not None and out is not None:
                    break
            first_good.append(bool(fg))
            pnl.append((out if out is not None else 0) - FEE)
        res["先顺势0.5ATR%"] = round(np.mean(first_good) * 100, 1)
        res["打法每笔%"] = round(np.mean(pnl), 3)
        res["打法胜率%"] = round(np.mean(np.array(pnl) > 0) * 100, 1)
        print(f"{label:22} {res}")
        return {"n": len(idx), "c15": res["15m 继续%"], "c30": res["30m 继续%"], "c60": res["60m 继续%"], "a30": res["30m 平均%"],
                "first": res["先顺势0.5ATR%"], "pnl": res["打法每笔%"], "win": res["打法胜率%"]}

    out = {"all": {}, "usopen": {}, "window": {}}
    print("追进去之后（2021–2026，1 分钟数据；往返手续费 0.10%）")
    for N in (5, 15):
        for k in (1.0, 1.5, 2.0, 3.0):
            out["all"][f"{N}_{k}"] = run(N, k, label=f"{N} 分钟内走 ≥{k} ATR")
    print("\n只看美股开盘 1 小时（美东 9:30–10:30）")
    for N, k in ((5, 1.0), (5, 1.5), (15, 1.5), (15, 2.0)):
        out["usopen"][f"{N}_{k}"] = run(N, k, usopen, label=f"{N} 分钟内走 ≥{k} ATR")

    # 大行情还剩多少：30 分钟内最大走 ≥ 3 ATR 的段落，以「5 分钟走 ≥1 ATR」触发时已走比例
    print("\n30 分钟内走 ≥3 ATR 的大行情：第一次出现「5 分钟走 ≥1 ATR」时已经走掉多少")
    mv5 = c - np.roll(o, 4)
    left, seen = [], -10 ** 9
    for i in range(30, n - 31, 1):
        if i - seen < 60:
            continue
        hi, lo = h[i:i + 30].max(), l[i:i + 30].min()
        a = A[i]
        if not np.isfinite(a):
            continue
        up_move, dn_move = hi - o[i], o[i] - lo
        if max(up_move, dn_move) < 3 * a:
            continue
        s = 1 if up_move >= dn_move else -1
        total = up_move if s > 0 else dn_move
        trig = [t for t in range(i, i + 30) if s * mv5[t] >= a]
        if trig:
            t = trig[0]
            done = s * (c[t] - o[i])
            left.append(((total - done) / total, total / a))
        seen = i
    if left:
        fr = np.array([x[0] for x in left])
        print(f"  共 {len(left)} 段；触发时还剩的中位 {np.median(fr) * 100:.0f}%，四分之一的段落剩不到 {np.quantile(fr, 0.25) * 100:.0f}%")
        print("  注意：这些是事后挑出来的大行情；同样的触发条件在其他时候大多只是普通波动（见上表）。")
        out["left_med"] = round(float(np.median(fr)) * 100)

    # 大行情时段：30 分钟内走 ≥3 ATR 的起点落在哪个时段，和该时段占全部时间的比例相比
    wk = np.asarray(ny.weekday < 5)
    mins = np.asarray(ny.hour * 60 + ny.minute)
    win = {"data": wk & (mins >= 510) & (mins < 570), "open": wk & (mins >= 570) & (mins < 630)}
    hi30 = pd.Series(h).iloc[::-1].rolling(30, min_periods=30).max().iloc[::-1].to_numpy()
    lo30 = pd.Series(l).iloc[::-1].rolling(30, min_periods=30).min().iloc[::-1].to_numpy()
    big = (np.maximum(hi30 - o, o - lo30) >= 3 * A) & np.isfinite(A)
    starts = np.where(big & ~np.roll(big, 1))[0]                  # 每段只算起点
    print(f"\n大行情（30 分钟走 ≥3 ATR）共 {len(starts)} 段")
    for key, m in win.items():
        share_t, share_b = m.mean(), m[starts].mean()
        out["window"][key] = round(float(share_b / share_t), 1)
        print(f"  {key}: 时间占 {share_t * 100:.1f}%，大行情占 {share_b * 100:.1f}%，是平时的 {share_b / share_t:.1f} 倍")
    write_var("FASTMOVE", "急动后追进去的历史结果与大行情时段（2021–2026），来自 backtest/fast_move.py", out)


if __name__ == "__main__":
    main()
