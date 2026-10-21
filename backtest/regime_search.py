"""比较几种「实时可用」的行情状态判断，看哪种最接近事后真实状态、最能提升顺势交易。

用法：.venv/bin/python regime_search.py
"""
import os

import numpy as np
import pandas as pd

import zhang
from backtest import simulate, EXITS, HERE


def resample(df5, rule):
    x = df5[["open", "high", "low", "close", "volume"]].resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return x


def to5m(series, rule, index):
    s = series.copy()
    s.index = s.index + pd.Timedelta(rule)  # 该周期 K 线收盘后才可用
    return s.reindex(index, method="ffill").fillna("na")


def candidates(df):
    out = {}
    h1 = resample(df, "1h")
    ma = {n: h1["close"].rolling(n).mean() for n in (7, 25, 99)}
    up = (ma[7] > ma[25]) & (ma[25] > ma[99]) & (h1["close"] > ma[25])
    dn = (ma[7] < ma[25]) & (ma[25] < ma[99]) & (h1["close"] < ma[25])
    out["1h均线多空排列"] = to5m(pd.Series(np.where(up, "up", np.where(dn, "down", "range")), h1.index).where(ma[99].notna(), "na"), "1h", df.index)

    h4 = resample(df, "4h")
    m25 = h4["close"].rolling(25).mean()
    out["4h收盘在MA25上下"] = to5m(pd.Series(np.where(h4["close"] > m25, "up", "down"), h4.index).where(m25.notna(), "na"), "4h", df.index)

    # 4h 唐奇安：收盘突破前 18 根（3 天）的高/低点后，状态保持，直到反向突破
    hh = h4["high"].shift(1).rolling(18).max(); ll = h4["low"].shift(1).rolling(18).min()
    st, cur = [], "range"
    for c, a, b in zip(h4["close"], hh, ll):
        if np.isnan(a):
            st.append("na"); continue
        if c > a: cur = "up"
        elif c < b: cur = "down"
        st.append(cur)
    out["4h突破3日高低点"] = to5m(pd.Series(st, h4.index), "4h", df.index)

    # 4h 唐奇安 + 回到区间中部时视为震荡
    mid_band = []
    for c, a, b, s in zip(h4["close"], hh, ll, st):
        if s == "na": mid_band.append("na"); continue
        pos = (c - b) / (a - b) if a > b else 0.5
        mid_band.append(s if (s == "up" and pos > 0.6) or (s == "down" and pos < 0.4) else "range")
    out["4h突破+位置"] = to5m(pd.Series(mid_band, h4.index), "4h", df.index)

    d1 = resample(df, "1D")
    m20 = d1["close"].rolling(20).mean()
    out["日线收盘在MA20上下"] = to5m(pd.Series(np.where(d1["close"] > m20, "up", "down"), d1.index).where(m20.notna(), "na"), "1D", df.index)

    out["ADX(4h)"] = zhang.regime_4h(df, adx_min=20)[0]
    out["效率比(4h)"] = zhang.regime_er(df)
    return out


def main():
    df = zhang.add_indicators(zhang.load_5m(os.path.join(HERE, "data", "BTCUSDT_5m.csv")))
    df = zhang.signals(df)
    truth = zhang.regime_er(df, hindsight=True)
    cands = candidates(df)
    df = df.iloc[300:]
    truth = truth.iloc[300:]

    cfg = EXITS["结构 止损/2R止盈"]
    tr = pd.DataFrame([dict(t) for side in ("short", "long") for t in simulate(df, df[f"{side}_A"], side, cfg)])
    tr["truth"] = truth.loc[tr["time"]].to_numpy()

    rows = []
    for name, reg in cands.items():
        reg = reg.iloc[300:]
        tr["reg"] = reg.loc[tr["time"]].to_numpy()
        valid = (reg != "na") & (truth != "na")
        # 与事后真实状态一致的比例（只比方向：上涨/下跌）
        trend_truth = truth[valid].isin(["up", "down"])
        agree = (reg[valid][trend_truth] == truth[valid][trend_truth]).mean()
        wrong_way = ((reg[valid] == "up") & (truth[valid] == "down")) | ((reg[valid] == "down") & (truth[valid] == "up"))
        aligned = ((tr.side == "long") & (tr.reg == "up")) | ((tr.side == "short") & (tr.reg == "down"))
        counter = ((tr.side == "long") & (tr.reg == "down")) | ((tr.side == "short") & (tr.reg == "up"))
        def s(x):
            return f"{len(x)}笔 胜率{(x.pnl_pts>0).mean()*100:.0f}% 期望{x.pnl_pts.mean():+.0f}点"
        rows.append({"判断方法": name, "趋势段方向判对": f"{agree*100:.0f}%", "方向判反": f"{wrong_way.mean()*100:.0f}%",
                     "顺势单": s(tr[aligned]), "逆势单": s(tr[counter])})
    tr["reg"] = tr["truth"]
    aligned = ((tr.side == "long") & (tr.reg == "up")) | ((tr.side == "short") & (tr.reg == "down"))
    counter = ((tr.side == "long") & (tr.reg == "down")) | ((tr.side == "short") & (tr.reg == "up"))
    rows.append({"判断方法": "事后真实（上限）", "趋势段方向判对": "100%", "方向判反": "0%",
                 "顺势单": f"{aligned.sum()}笔 胜率{(tr[aligned].pnl_pts>0).mean()*100:.0f}% 期望{tr[aligned].pnl_pts.mean():+.0f}点",
                 "逆势单": f"{counter.sum()}笔 胜率{(tr[counter].pnl_pts>0).mean()*100:.0f}% 期望{tr[counter].pnl_pts.mean():+.0f}点"})
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(out.to_string(index=False))
    out.to_csv(os.path.join(HERE, "results", "regime_search.csv"), index=False)

    # 手续费敏感度：同一批交易换不同费率
    print("\n手续费敏感度（只看扳机 + 结构止损/2R，全部交易）")
    gross = tr.pnl_pts + 0.0007 * tr.entry
    for name, fee in (("不计手续费", 0.0), ("全挂单 0.04%", 0.0004), ("挂单进+市价出 0.07%", 0.0007), ("全市价 0.10%", 0.001)):
        net = gross - fee * tr.entry
        print(f"  {name:<16} 每笔期望 {net.mean():+.0f} 点  胜率 {(net>0).mean()*100:.0f}%")


if __name__ == "__main__":
    main()
