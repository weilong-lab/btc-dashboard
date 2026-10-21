"""两项补充：
1. 加入「区间位置」条件（只在过去 24 小时区间的上沿做空、下沿做多），看是否产生优势。
2. 列出 10/12–10/22 的信号，和聊天里的真实交易对照。

用法：.venv/bin/python edge_and_check.py
"""
import os

import numpy as np
import pandas as pd

import zhang
from backtest import simulate, EXITS, HERE, FEE


def summarize(tr, label):
    if len(tr) == 0:
        return f"{label:<34} 0 笔"
    w = tr.pnl_pts > 0
    gross = tr.pnl_pts + FEE * tr.entry
    half = tr.time < tr.time.min() + (tr.time.max() - tr.time.min()) / 2
    return (f"{label:<34} {len(tr):>4} 笔  胜率 {w.mean()*100:4.1f}%  每笔 {tr.pnl_pts.mean():+5.0f} 点"
            f"（不计费 {gross.mean():+4.0f}）  前半年 {tr[half].pnl_pts.mean():+4.0f} / 后半年 {tr[~half].pnl_pts.mean():+4.0f}")


def main():
    df = zhang.add_indicators(zhang.load_5m(os.path.join(HERE, "data", "BTCUSDT_5m.csv")))
    df = zhang.signals(df)
    hi24 = df["high"].rolling(288).max()
    lo24 = df["low"].rolling(288).min()
    df["pos24"] = (df["close"] - lo24) / (hi24 - lo24)
    df["width24"] = hi24 - lo24
    df["us_open"] = zhang.us_open_window(df.index)
    df = df.iloc[300:]

    print("== 1. 区间位置条件 ==")
    for ex in ("固定 止损300/止盈500", "结构 止损/2R止盈"):
        print(f"\n出场：{ex}")
        for ver, vname in (("A", "只看扳机"), ("B", "完整版")):
            for edge in (None, 0.8, 0.9):
                es = df[f"short_{ver}"] if edge is None else df[f"short_{ver}"] & (df.pos24 >= edge)
                el = df[f"long_{ver}"] if edge is None else df[f"long_{ver}"] & (df.pos24 <= 1 - edge)
                tr = pd.DataFrame(simulate(df, es, "short", EXITS[ex]) + simulate(df, el, "long", EXITS[ex]))
                tag = "不限位置" if edge is None else f"只在24h区间{int(edge*100)}%以上空/{int((1-edge)*100)}%以下多"
                print(summarize(tr, f"{vname} · {tag}"))

    print("\n== 2. 10/12–10/22 完整版信号（东京时间）==")
    win = df.loc["2026-10-11 15:00":"2026-10-21 18:00"]
    for side in ("short", "long"):
        sig = win[win[f"{side}_B"]]
        res = pd.DataFrame(simulate(df, df[f"{side}_B"] & df.index.isin(sig.index), side, EXITS["固定 止损300/止盈500"]))
        if len(res):
            res["jst"] = res["time"].dt.tz_convert("Asia/Tokyo").dt.strftime("%m-%d %H:%M")
            res["pos24"] = df.loc[res["time"], "pos24"].round(2).to_numpy()
            print(f"\n{'做空' if side=='short' else '做多'}信号：")
            print(res[["jst", "entry", "result", "pnl_pts", "mfe", "mae", "pos24"]].round(0).to_string(index=False))


if __name__ == "__main__":
    main()
