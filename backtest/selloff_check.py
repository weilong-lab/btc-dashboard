"""连续下跌时，方向模型「偏涨」到底靠不靠谱。

场景：4 小时内已跌 ≥1.5%、RSI6 ≤ 20（超卖）——模型这时几乎总是给出偏涨。
看样本外（2021–2026 逐年滚动）里，这种时候：
- 模型说涨，之后真的涨了的比例（准确率）
- 之后的平均涨跌、反弹前还要再跌多少（最大不利幅度）
- 镜像：4 小时内已涨 ≥1.5%、RSI6 ≥ 80（超买）时同样统计
结果写入 results/selloff_check.csv，并导出 dashboard/live/context.js 给面板用

用法：.venv/bin/python selloff_check.py
"""
import os

import numpy as np
import pandas as pd

from direction_model import features
from context_js import write_var
from direction_model_full import load_1m, to5m

HERE = os.path.dirname(os.path.abspath(__file__))
HZ = [("p15", 3, "15 分钟"), ("p1h", 12, "1 小时"), ("p4h", 48, "4 小时")]


def main():
    d5 = to5m(load_1m("BTCUSDT_perp_1m.csv.gz"))
    f = features(d5, 288)
    oos = pd.read_csv(os.path.join(HERE, "data", "oos_probs_5m.csv.gz"), parse_dates=["time"]).set_index("time")
    c, lo, hi = d5["close"], d5["low"], d5["high"]
    d = f.join(oos, how="inner")
    rsi = (d.rsi6 + 0.5) * 100
    ret4h = np.expm1(d.ret_48) * 100
    # (名称, 条件, 方向)：方向 -1 = 急跌超卖（看反弹前还要再跌多少），+1 = 急涨超买（看回落前还要再涨多少）
    groups = [
        ("全部时段", pd.Series(True, index=d.index), -1),
        ("drop", (ret4h <= -1.5) & (ret4h > -3) & (rsi <= 20), -1),
        ("drop3", (ret4h <= -3) & (rsi <= 20), -1),
        ("rally", (ret4h >= 1.5) & (ret4h < 3) & (rsi >= 80), 1),
        ("rally3", (ret4h >= 3) & (rsi >= 80), 1),
    ]
    names = {"drop": "4h 跌 1.5–3% 且 RSI6 ≤20", "drop3": "4h 跌 ≥3% 且 RSI6 ≤20",
             "rally": "4h 涨 1.5–3% 且 RSI6 ≥80", "rally3": "4h 涨 ≥3% 且 RSI6 ≥80"}
    rows, ctx = [], {}
    for gname, m, side in groups:
        for col, h, hname in HZ:
            fwd = (c.shift(-h) / c - 1).reindex(d.index) * 100
            # 之后 h 根内逆着模型方向的最远点：急跌时看最低点（反弹前再跌多少），急涨时看最高点
            ext = lo[::-1].rolling(h, min_periods=h).min()[::-1] if side < 0 else hi[::-1].rolling(h, min_periods=h).max()[::-1]
            mae = (ext.shift(-1) / c - 1).reindex(d.index) * 100
            sel = m & fwd.notna() & mae.notna()
            p, y = d.loc[sel, col], fwd[sel] > 0
            up_call = p > 0.5
            n_ind = max(int(sel.sum() / h), 1)
            if gname in names:
                rev = (fwd[sel] > 0) if side < 0 else (fwd[sel] < 0)
                ctx.setdefault(gname, {"name": names[gname]})[hname] = {
                    "n": n_ind, "rev": round(rev.mean() * 100, 1), "err": round(98 / np.sqrt(n_ind), 1),
                    "med": round(fwd[sel].median(), 2), "mae": round(mae[sel].median(), 2),
                    "mae80": round(mae[sel].quantile(0.2 if side < 0 else 0.8), 2)}
            rows.append({
                "场景": names.get(gname, gname), "周期": hname, "样本": int(sel.sum()), "独立样本": n_ind,
                "模型说涨占比%": round(up_call.mean() * 100, 1),
                "模型准确率%": round(((p > 0.5) == y).mean() * 100, 1),
                "说涨时真涨%": round(y[up_call].mean() * 100, 1) if up_call.any() else None,
                "实际上涨比例%": round(y.mean() * 100, 1),
                "误差±": round(98 / np.sqrt(n_ind), 1),
                "之后平均涨跌%": round(fwd[sel].mean(), 3),
                "之后涨跌中位数%": round(fwd[sel].median(), 3),
                "期间逆向中位数%": round(mae[sel].median(), 2),
                "期间逆向P80%": round(mae[sel].quantile(0.2 if side < 0 else 0.8), 2),
            })
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print(out.to_string(index=False))
    out.to_csv(os.path.join(HERE, "results", "selloff_check.csv"), index=False)
    write_var("CONTEXT", "急涨急跌情境的历史统计（2021–2026 样本外），来自 backtest/selloff_check.py", ctx)


if __name__ == "__main__":
    main()
