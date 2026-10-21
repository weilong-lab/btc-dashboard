"""用全部历史数据按年滚动检验方向模型。

- 永续 2020-01 → 至今：每个检验年份只用它之前的全部数据训练（1 分钟模型只用之前 12 个月，控制内存）
- 额外检验：模型从没见过的 2017-08 → 2019-12 现货行情
- 最后用全部永续数据训练最终模型，导出给仪表盘

用法：.venv/bin/python direction_model_full.py
输出：results/direction_full_walkforward.csv、results/direction_weights_full.json
"""
import json
import os

import numpy as np
import pandas as pd

from direction_model import features, fit_logit, auc

HERE = os.path.dirname(os.path.abspath(__file__))
HORIZONS_5M = [("5 分钟", 1), ("15 分钟", 3), ("1 小时", 12), ("4 小时", 48), ("24 小时（大势）", 288)]


def load_1m(name):
    df = pd.read_csv(os.path.join(HERE, "data", name))
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.set_index("time").drop(columns=["open_time"]).astype(float)


def to5m(d1):
    return d1.resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "taker_buy_volume": "sum"}).dropna()


def dataset(df, h, day_bars):
    f = features(df, day_bars)
    fwd = np.log(df["close"].shift(-h) / df["close"])
    d = f.assign(y=(fwd > 0).astype(float), fwd=fwd).replace([np.inf, -np.inf], np.nan).dropna()
    return d[d.fwd != 0], list(f.columns)


def train(tr, cols):
    mu, sd = tr[cols].mean(), tr[cols].std().replace(0, 1)
    X = np.column_stack([np.ones(len(tr)), ((tr[cols] - mu) / sd).clip(-5, 5).to_numpy()])
    w = fit_logit(X, tr.y.to_numpy(), l2=len(tr) * 1e-3)
    return mu, sd, w


def score(te, cols, mu, sd, w, h):
    X = np.column_stack([np.ones(len(te)), ((te[cols] - mu) / sd).clip(-5, 5).to_numpy()])
    p = 1 / (1 + np.exp(-X @ w))
    y = te.y.to_numpy()
    conf = np.abs(p - 0.5) >= 0.05
    n_ind = max(len(te) // h, 1)
    return dict(样本=len(te), 独立样本=n_ind, 准确率=round(((p > 0.5) == y).mean() * 100, 2),
                误差=round(0.5 / np.sqrt(n_ind) * 196, 2), AUC=round(auc(y, p), 3),
                高把握占比=round(conf.mean() * 100, 1),
                高把握准确率=round(((p[conf] > 0.5) == y[conf]).mean() * 100, 2) if conf.any() else None,
                多数方向=round(max(y.mean(), 1 - y.mean()) * 100, 2))


def main():
    perp1 = load_1m("BTCUSDT_perp_1m.csv.gz")
    spot1 = load_1m("BTCUSDT_spot_1m.csv.gz")
    perp5, spot5 = to5m(perp1), to5m(spot1)
    print(f"永续 1m {len(perp1):,} 根，5m {len(perp5):,} 根；现货 5m {len(spot5):,} 根", flush=True)
    rows, final = [], {}
    years = range(2021, 2027)

    for name, h in HORIZONS_5M:
        data, cols = dataset(perp5, h, 288)
        sdata, _ = dataset(spot5.loc[:"2019-12-31"], h, 288)
        for y in years:
            tr = data[data.index < f"{y}-01-01"]
            te = data[(data.index >= f"{y}-01-01") & (data.index < f"{y + 1}-01-01")]
            if len(te) < 1000:
                continue
            mu, sd, w = train(tr, cols)
            rows.append(dict(周期=name, 检验=str(y), 训练样本=len(tr), **score(te, cols, mu, sd, w, h)))
        mu, sd, w = train(data[data.index < "2026-01-01"], cols)
        rows.append(dict(周期=name, 检验="2017-19 现货", 训练样本=None, **score(sdata, cols, mu, sd, w, h)))
        mu, sd, w = train(data, cols)
        final[name] = dict(cols=cols, mu=mu.round(8).tolist(), sd=sd.round(8).tolist(), w=np.round(w, 6).tolist(), horizon_bars=h, bar="5m")
        print(f"{name} 完成", flush=True)

    # 1 分钟：每年只用之前 12 个月训练
    data, cols = dataset(perp1, 1, 1440)
    for y in years:
        tr = data[(data.index >= f"{y - 1}-01-01") & (data.index < f"{y}-01-01")]
        te = data[(data.index >= f"{y}-01-01") & (data.index < f"{y + 1}-01-01")]
        if len(te) < 1000:
            continue
        mu, sd, w = train(tr, cols)
        rows.append(dict(周期="1 分钟", 检验=str(y), 训练样本=len(tr), **score(te, cols, mu, sd, w, 1)))
    mu, sd, w = train(data[data.index >= data.index[-1] - pd.Timedelta(days=365)], cols)
    final["1 分钟"] = dict(cols=cols, mu=mu.round(8).tolist(), sd=sd.round(8).tolist(), w=np.round(w, 6).tolist(), horizon_bars=1, bar="1m")
    print("1 分钟 完成", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(HERE, "results", "direction_full_walkforward.csv"), index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200); pd.set_option("display.max_columns", 20)
    print(out.to_string(index=False))

    # 汇总：把 2021–2026 各年的检验合并（按样本加权）
    summ = {}
    for name in ["1 分钟"] + [n for n, _ in HORIZONS_5M]:
        g = out[(out.周期 == name) & (out.检验.str.match(r"^\d{4}$"))]
        acc = (g.准确率 * g.样本).sum() / g.样本.sum()
        n_ind = g.独立样本.sum()
        hi = (g.高把握准确率 * g.样本 * g.高把握占比).sum() / (g.样本 * g.高把握占比).sum()
        yrs_above = int((g.准确率 > 50).sum())
        spot = out[(out.周期 == name) & (out.检验 == "2017-19 现货")]
        summ[name] = dict(test_acc=round(acc, 2), err=round(0.5 / np.sqrt(n_ind) * 196, 2), acc_conf=round(hi, 2),
                          conf_share=round((g.高把握占比 * g.样本).sum() / g.样本.sum(), 1), years_above_50=f"{yrs_above}/{len(g)}",
                          spot_2017_19=float(spot.准确率.iloc[0]) if len(spot) else None)
        final[name].update(summ[name])
    print("\n汇总（2021–2026 逐年样本外合计）：")
    print(pd.DataFrame(summ).T.to_string())
    with open(os.path.join(HERE, "results", "direction_weights_full.json"), "w") as fp:
        json.dump(final, fp, ensure_ascii=False)


if __name__ == "__main__":
    main()
