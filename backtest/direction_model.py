"""多周期方向模型：预测未来 1m / 5m / 15m / 1h / 4h / 24h 是涨还是跌，并用样本外数据检验准确率。

方法：逻辑回归（numpy 实现，带 L2），按时间先后切分：前 2/3 训练，后 1/3 检验，不打乱顺序。
1 分钟周期用最近 60 天 1 分钟数据，其余周期用 12 个月 5 分钟数据。

用法：.venv/bin/python direction_model.py
输出：results/direction_model.csv（各周期准确率）、results/direction_weights.json（给仪表盘用的模型参数）
"""
import json
import os

import numpy as np
import pandas as pd

import zhang

HERE = os.path.dirname(os.path.abspath(__file__))


def features(df, day_bars):
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    for k in (1, 3, 12, 48, day_bars):
        f[f"ret_{k}"] = np.log(c / c.shift(k))
    for n in (7, 25, 99):
        f[f"dist_ma{n}"] = c / c.rolling(n).mean() - 1
    f["rsi6"] = zhang.rsi(c, 6) / 100 - 0.5
    _, _, j = zhang.kdj(df)
    f["j"] = (j - 50) / 100
    f["hist"] = zhang.macd_hist(c) / c
    v = df["volume"]
    f["vol_ratio"] = np.log((v / v.rolling(day_bars).median()).clip(lower=1e-3))
    tb = (df["taker_buy_volume"] / v.replace(0, np.nan)).fillna(0.5)
    f["taker_buy_1"] = tb - 0.5
    f["taker_buy_12"] = (df["taker_buy_volume"].rolling(12).sum() / v.rolling(12).sum()) - 0.5
    hi, lo = df["high"].rolling(day_bars).max(), df["low"].rolling(day_bars).min()
    f["pos24"] = (c - lo) / (hi - lo) - 0.5
    f["range24"] = (hi - lo) / c
    ny = df.index.tz_convert("America/New_York")
    f["weekend"] = (ny.weekday >= 5).astype(float)
    f["us_hours"] = ((ny.weekday < 5) & (ny.hour >= 9) & (ny.hour < 16)).astype(float)
    f["us_open_hour"] = ((ny.weekday < 5) & (ny.hour == 9)).astype(float)
    h4 = df["close"].resample("4h").last()
    trend = (h4 / h4.rolling(25).mean() - 1)
    trend.index = trend.index + pd.Timedelta(hours=4)
    f["trend4h"] = trend.reindex(df.index, method="ffill")
    return f


def fit_logit(X, y, l2=1.0, iters=300):
    """牛顿法（IRLS）逻辑回归。X 已标准化，第一列为常数项。"""
    w = np.zeros(X.shape[1])
    reg = np.eye(X.shape[1]) * l2
    reg[0, 0] = 0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (p - y) + reg @ w
        H = (X * (p * (1 - p))[:, None]).T @ X + reg
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


def auc(y, s):
    order = np.argsort(s)
    ranks = np.empty(len(s)); ranks[order] = np.arange(1, len(s) + 1)
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    return (ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def evaluate(df, horizons, day_bars, label_unit):
    f = features(df, day_bars)
    rows, models = [], {}
    for name, h in horizons:
        fwd = np.log(df["close"].shift(-h) / df["close"])
        data = f.assign(y=(fwd > 0).astype(float), fwd=fwd).dropna()
        data = data[data.fwd != 0]
        cols = [c for c in f.columns]
        split = int(len(data) * 2 / 3)
        tr, te = data.iloc[:split], data.iloc[split:]
        mu, sd = tr[cols].mean(), tr[cols].std().replace(0, 1)
        Xtr = np.column_stack([np.ones(len(tr)), ((tr[cols] - mu) / sd).clip(-5, 5).to_numpy()])
        Xte = np.column_stack([np.ones(len(te)), ((te[cols] - mu) / sd).clip(-5, 5).to_numpy()])
        w = fit_logit(Xtr, tr.y.to_numpy(), l2=len(tr) * 1e-3)
        p = 1 / (1 + np.exp(-Xte @ w))
        yte = te.y.to_numpy()
        acc = ((p > 0.5) == yte).mean()
        conf = np.abs(p - 0.5) >= 0.05
        acc_conf = ((p[conf] > 0.5) == yte[conf]).mean() if conf.any() else np.nan
        base_up = max(yte.mean(), 1 - yte.mean())
        mom = np.sign(te[f"ret_{min(h, day_bars) if f'ret_{h}' in te else 12}"]) if f"ret_{h}" in te else np.sign(te["ret_12"])
        mom_acc = ((mom > 0) == (yte == 1)).mean()
        # 非重叠样本数（衡量真正独立的检验次数）
        n_indep = len(te) // h
        se = 0.5 / np.sqrt(max(n_indep, 1))
        rows.append({"周期": name, "检验区间": f"{te.index[0]:%Y-%m-%d} → {te.index[-1]:%Y-%m-%d}",
                     "检验样本": len(te), "独立样本≈": n_indep, "模型准确率%": round(acc * 100, 1),
                     "随机误差±%": round(se * 196, 1), "AUC": round(auc(yte, p), 3),
                     "高把握(|p-50%|≥5%)占比%": round(conf.mean() * 100, 1), "高把握时准确率%": round(acc_conf * 100, 1) if acc_conf == acc_conf else None,
                     "全猜多数方向%": round(base_up * 100, 1), "动量跟随%": round(mom_acc * 100, 1)})
        models[name] = dict(cols=cols, mu=mu.round(8).tolist(), sd=sd.round(8).tolist(), w=np.round(w, 6).tolist(),
                            bar=label_unit, horizon_bars=h, test_acc=round(acc * 100, 1), test_auc=round(auc(yte, p), 3),
                            acc_conf=round(acc_conf * 100, 1) if acc_conf == acc_conf else None, conf_share=round(conf.mean() * 100, 1))
    return rows, models


def main():
    d5 = zhang.load_5m(os.path.join(HERE, "data", "BTCUSDT_5m.csv"))
    d1 = zhang.load_5m(os.path.join(HERE, "data", "BTCUSDT_1m.csv"))
    rows1, m1 = evaluate(d1, [("1 分钟", 1)], day_bars=1440, label_unit="1m")
    rows5, m5 = evaluate(d5, [("5 分钟", 1), ("15 分钟", 3), ("1 小时", 12), ("4 小时", 48), ("24 小时（大势）", 288)], day_bars=288, label_unit="5m")
    out = pd.DataFrame(rows1 + rows5)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(out.to_string(index=False))
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    out.to_csv(os.path.join(HERE, "results", "direction_model.csv"), index=False)
    with open(os.path.join(HERE, "results", "direction_weights.json"), "w") as fp:
        json.dump({**m1, **m5}, fp, ensure_ascii=False)

    # 当前（数据最后一根）各周期的预测
    print("\n数据最后时刻的预测：")
    for d, models, day in ((d1, m1, 1440), (d5, m5, 288)):
        f = features(d, day).iloc[-1]
        for name, m in models.items():
            x = np.concatenate([[1], ((f[m["cols"]] - np.array(m["mu"])) / np.array(m["sd"])).clip(-5, 5).to_numpy()])
            p = 1 / (1 + np.exp(-x @ np.array(m["w"])))
            print(f"  {name}: 上涨概率 {p*100:.1f}%（检验准确率 {m['test_acc']}%）  时间 {d.index[-1].tz_convert('Asia/Tokyo')}")


if __name__ == "__main__":
    main()
