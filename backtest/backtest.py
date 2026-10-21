"""回测张主任打法，按行情状态分组统计胜率与盈亏比。

用法：.venv/bin/python backtest.py
输出：终端表格 + results/summary.csv + results/trades.csv
"""
import os

import numpy as np
import pandas as pd

import zhang

HERE = os.path.dirname(os.path.abspath(__file__))
FEE = 0.0007          # 往返手续费：挂单开仓 0.02% + 市价/止损平仓 0.05%
MAX_HOLD = 288        # 最长持仓 24 小时（288 根 5 分钟）

EXITS = {
    # 张主任聊天里常用的点数：止损 200（后来改 300），止盈 500 左右
    "固定 止损200/止盈500": dict(kind="fixed", stop=200, tp=500),
    "固定 止损300/止盈500": dict(kind="fixed", stop=300, tp=500),
    # 结构化：止损放在最近 1 小时高/低点外加半个 ATR，止盈 = 2 倍风险
    "结构 止损/2R止盈": dict(kind="struct", r_mult=2.0),
}


def simulate(df, entries, side, exit_cfg):
    o, h, l = df["open"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
    atr = df["atr"].to_numpy()
    hi12 = df["high"].rolling(12).max().to_numpy()
    lo12 = df["low"].rolling(12).min().to_numpy()
    idx = np.flatnonzero(entries.to_numpy())
    n = len(df)
    out = []
    busy_until = -1
    for t in idx:
        e = t + 1
        if e >= n or e <= busy_until:  # 同方向持仓期间不重复开仓
            continue
        px = o[e]
        if exit_cfg["kind"] == "fixed":
            risk = exit_cfg["stop"]
            reward = exit_cfg["tp"]
        else:
            if side == "short":
                risk = max(hi12[t] + 0.5 * atr[t] - px, 50)
            else:
                risk = max(px - (lo12[t] - 0.5 * atr[t]), 50)
            reward = exit_cfg["r_mult"] * risk
        stop = px + risk if side == "short" else px - risk
        tp = px - reward if side == "short" else px + reward
        res, exit_px, j = "timeout", None, None
        mfe = mae = 0.0
        for j in range(e, min(e + MAX_HOLD, n)):
            if side == "short":
                mfe = max(mfe, px - l[j]); mae = max(mae, h[j] - px)
                hit_stop, hit_tp = h[j] >= stop, l[j] <= tp
            else:
                mfe = max(mfe, h[j] - px); mae = max(mae, px - l[j])
                hit_stop, hit_tp = l[j] <= stop, h[j] >= tp
            if hit_stop:  # 同一根里两者都碰到，按先止损算（保守）
                res, exit_px = "stop", stop
                break
            if hit_tp:
                res, exit_px = "tp", tp
                break
        if exit_px is None:
            exit_px = df["close"].iloc[j]
        gross = (px - exit_px) if side == "short" else (exit_px - px)
        net = gross - FEE * px
        out.append(dict(time=df.index[t], side=side, entry=px, exit=exit_px, result=res,
                        pnl_pts=net, r=net / risk, risk=risk, mfe=mfe, mae=mae, bars=j - e + 1))
        busy_until = j
    return out


def stats(tr):
    if len(tr) == 0:
        return dict(笔数=0)
    wins, losses = tr[tr.pnl_pts > 0], tr[tr.pnl_pts <= 0]
    avg_w = wins.pnl_pts.mean() if len(wins) else 0
    avg_l = -losses.pnl_pts.mean() if len(losses) else np.nan
    pf = wins.pnl_pts.sum() / -losses.pnl_pts.sum() if len(losses) and losses.pnl_pts.sum() < 0 else np.nan
    return {"笔数": len(tr), "胜率": round(len(wins) / len(tr) * 100, 1),
            "平均盈利(点)": round(avg_w), "平均亏损(点)": round(avg_l) if avg_l == avg_l else None,
            "盈亏比": round(avg_w / avg_l, 2) if avg_l and avg_l == avg_l else None,
            "利润因子": round(pf, 2) if pf == pf else None,
            "每笔期望(点)": round(tr.pnl_pts.mean()), "每笔期望(R)": round(tr.r.mean(), 2),
            "顺向中位(点)": round(tr.mfe.median()), "逆向中位(点)": round(tr.mae.median())}


def main():
    df = zhang.add_indicators(zhang.load_5m(os.path.join(HERE, "data", "BTCUSDT_5m.csv")))
    df = zhang.signals(df)
    df["reg_adx"], _ = zhang.regime_4h(df, adx_min=20)
    df["reg_er"] = zhang.regime_er(df)
    df["reg_true"] = zhang.regime_er(df, hindsight=True)
    df["us_open"] = zhang.us_open_window(df.index)
    df = df.iloc[300:]  # 丢掉指标预热期

    trades = []
    for exit_name, cfg in EXITS.items():
        for ver in ("A", "B"):
            for side in ("short", "long"):
                for tr in simulate(df, df[f"{side}_{ver}"], side, cfg):
                    tr.update(exit=exit_name, version=ver)
                    trades.append(tr)
    tr = pd.DataFrame(trades)
    for col in ("reg_adx", "reg_er", "reg_true", "us_open"):
        tr[col] = df.loc[tr["time"], col].to_numpy()
    half = df.index[0] + (df.index[-1] - df.index[0]) / 2
    tr["period"] = np.where(tr["time"] < half, "前半年", "后半年")

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    tr.to_csv(os.path.join(HERE, "results", "trades.csv"), index=False)

    rows = []
    def add(label, sub, **keys):
        rows.append({**keys, "分组": label, **stats(sub)})

    for (ex, ver), g in tr.groupby(["exit", "version"]):
        base = dict(出场=ex, 版本="只看扳机" if ver == "A" else "张主任完整版")
        add("全部", g, **base)
        for side, gs in g.groupby("side"):
            add("做空" if side == "short" else "做多", gs, **base)
        for reg_col, reg_name in (("reg_adx", "ADX实时"), ("reg_er", "ER实时"), ("reg_true", "事后真实")):
            for (side, reg), gs in g.groupby(["side", reg_col]):
                if reg == "na":
                    continue
                add(f"{reg_name}|{'做空' if side=='short' else '做多'}|{ {'up':'上涨','down':'下跌','range':'震荡'}[reg] }", gs, **base)
        for p, gs in g.groupby("period"):
            add(f"时间|{p}", gs, **base)
        add("美股开盘前1h~后30min", g[g.us_open], **base)
        add("其余时段", g[~g.us_open], **base)
    summ = pd.DataFrame(rows)
    summ.to_csv(os.path.join(HERE, "results", "summary.csv"), index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 400)
    print(f"数据：{df.index[0]} → {df.index[-1]}，{len(df)} 根 5 分钟 K 线")
    print(summ.to_string(index=False))


if __name__ == "__main__":
    main()
