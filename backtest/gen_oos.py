"""生成方向模型在 2021–2026 的样本外逐根概率（每年只用之前的数据训练），供统一规则回测使用。

输出：data/oos_probs_5m.csv.gz，列：time, p15, p1h, p4h（上涨概率，0–1）
用法：.venv/bin/python gen_oos.py
"""
import os

import numpy as np
import pandas as pd

from direction_model import features
from direction_model_full import load_1m, to5m, train

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    perp5 = to5m(load_1m("BTCUSDT_perp_1m.csv.gz"))
    f = features(perp5, 288).replace([np.inf, -np.inf], np.nan)
    cols = list(f.columns)
    out = pd.DataFrame(index=perp5.index)
    for name, h in (("p15", 3), ("p1h", 12), ("p4h", 48)):
        fwd = np.log(perp5["close"].shift(-h) / perp5["close"])
        data = f.assign(y=(fwd > 0).astype(float), fwd=fwd).dropna()
        data = data[data.fwd != 0]
        col = pd.Series(np.nan, index=perp5.index)
        for y in range(2021, 2027):
            tr = data[data.index < f"{y}-01-01"]
            mu, sd, w = train(tr, cols)
            te = f[(f.index >= f"{y}-01-01") & (f.index < f"{y + 1}-01-01")].dropna()
            X = np.column_stack([np.ones(len(te)), ((te[cols] - mu) / sd).clip(-5, 5).to_numpy()])
            col.loc[te.index] = 1 / (1 + np.exp(-X @ w))
        out[name] = col
        print(name, "完成", flush=True)
    out = out.dropna()
    out.to_csv(os.path.join(HERE, "data", "oos_probs_5m.csv.gz"), float_format="%.4f")
    print(len(out), out.index[0], out.index[-1])


if __name__ == "__main__":
    main()
