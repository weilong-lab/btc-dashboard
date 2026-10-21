"""方向模型能否在扣手续费后赚钱：逐年样本外，只在高把握时进场，持有到该周期结束（不重叠）。"""
import os, numpy as np, pandas as pd
from direction_model_full import load_1m, to5m, dataset, train
HERE = os.path.dirname(os.path.abspath(__file__))
perp5 = to5m(load_1m("BTCUSDT_perp_1m.csv.gz"))
rows = []
for name, h in (("15 分钟", 3), ("1 小时", 12), ("4 小时", 48)):
    data, cols = dataset(perp5, h, 288)
    for y in range(2021, 2027):
        tr = data[data.index < f"{y}-01-01"]; te = data[(data.index >= f"{y}-01-01") & (data.index < f"{y+1}-01-01")]
        mu, sd, w = train(tr, cols)
        X = np.column_stack([np.ones(len(te)), ((te[cols] - mu) / sd).clip(-5, 5).to_numpy()])
        p = 1 / (1 + np.exp(-X @ w))
        te = te.assign(p=p).iloc[::h]               # 不重叠：每个周期只做一次决策
        for th in (0.05, 0.08):
            sel = te[(te.p - 0.5).abs() >= th]
            ret = np.sign(sel.p - 0.5) * (np.exp(sel.fwd) - 1) * 100   # 每笔收益 %
            for fee_name, fee in (("不计费", 0), ("全挂单0.04%", 0.04), ("挂单+市价0.07%", 0.07)):
                r = ret - fee
                rows.append(dict(周期=name, 年=y, 把握=f"≥{int(th*100)}%", 手续费=fee_name, 笔数=len(r),
                                 胜率=round((r > 0).mean()*100, 1), 每笔=round(r.mean(), 3), 全年累计=round(r.sum(), 1)))
out = pd.DataFrame(rows)
out.to_csv(os.path.join(HERE, "results", "model_pnl.csv"), index=False)
pd.set_option("display.width", 220); pd.set_option("display.max_rows", 300)
piv = out.pivot_table(index=["周期", "把握", "手续费"], columns="年", values="每笔").round(3)
piv["正收益年数"] = (piv > 0).sum(axis=1)
print("每笔平均收益（%，不含杠杆）：")
print(piv.to_string())
print(out.groupby(["周期","把握","手续费"]).笔数.mean().round(0).unstack().to_string())
