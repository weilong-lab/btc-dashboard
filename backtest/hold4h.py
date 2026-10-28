"""「四小时理论」：张主任多周期信号（5 分 + 15 分同一指标在区间外，RSI 优先）出现后下一根开盘市价进，严格拿满 N 小时卖。
对照 1–8 小时，看 4 小时是不是特别。手续费 0.10% 往返，2021-01 起，持仓期间不重复开仓。
用法：.venv/bin/python hold4h.py      结果写到 results_hold4h.txt
"""
import os

import numpy as np
import pandas as pd

import zhang_mtf as Z

OUT = []


def say(s):
    print(s)
    OUT.append(s)


def main():
    _, d5 = Z.build()
    r5, j5, r15, j15 = d5["rsi6"], d5["j"], d5["rsi_15min"], d5["j_15min"]
    s = ((r5 > 80) & (r15 > 70)) | ((d5["j"] > 110) & (j15 > 100))
    l = ((r5 < 20) & (r15 < 20)) | ((j5 < -5) & (j15 < 0))
    bias = d5["ma99_4h_dir"]
    ok = lambda t, e=0: False
    sets = [("做空", "short", s), ("做多", "long", l),
            ("做空·顺 4h MA99", "short", s & (bias < 0)), ("做多·顺 4h MA99", "long", l & (bias > 0))]
    for name, side, m in sets:
        idx, _ = Z.forward(d5, m, side)
        say(f"\n{name}")
        say("  拿多久   笔数/年   赚钱的比例   扣费每笔   中位     最好 1/5   最差 1/5   年份为正")
        for hrs in (1, 2, 3, 4, 5, 6, 8):
            tr = Z.trade(d5, idx, side, ok, hrs * 12)
            p = pd.Series([x[1] for x in tr], index=d5.index[[x[0] for x in tr]])
            yrs = (p.index[-1] - p.index[0]).days / 365.25
            yr = p.groupby(p.index.year).mean()
            say(f"  {hrs} 小时   {len(p) / yrs:6.0f}    {np.mean(p > 0) * 100:5.1f}%    {p.mean():+.3f}%   {p.median():+.3f}%   "
                f"{p.quantile(0.8):+.2f}%    {p.quantile(0.2):+.2f}%    {int((yr > 0).sum())}/{len(yr)}")
            if hrs == 4:
                say("           按年 4 小时：" + "  ".join(f"{y}: {np.mean(g > 0) * 100:.0f}% 赚 {g.mean():+.3f}%" for y, g in p.groupby(p.index.year)))
    with open(os.path.join(Z.HERE, "results_hold4h.txt"), "w") as f:
        f.write("\n".join(OUT) + "\n")


if __name__ == "__main__":
    main()
