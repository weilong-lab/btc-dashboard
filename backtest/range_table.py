"""预期振幅表：按「时段」×「过去 24h 活跃度」统计接下来 1h / 4h 的振幅（%），给仪表盘做波动尺子。

用法：.venv/bin/python range_table.py   → results/range_table.csv
"""
import os
import numpy as np
import pandas as pd
import zhang

HERE = os.path.dirname(os.path.abspath(__file__))
CPI = pd.to_datetime([f"{d} 08:30" for d in __import__("events_study").CPI_DATES]).tz_localize("America/New_York").tz_convert("UTC")

df = zhang.load_5m(os.path.join(HERE, "data", "BTCUSDT_5m.csv"))
h = df.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
hi1, lo1 = h.high, h.low
h["rng1"] = (hi1 - lo1) / h.open * 100
h["rng4"] = (hi1[::-1].rolling(4).max()[::-1] - lo1[::-1].rolling(4).min()[::-1]) / h.open * 100
h["prev24"] = (hi1.rolling(24).max() - lo1.rolling(24).min()).shift(1) / h.open * 100
ny = h.index.tz_convert("America/New_York")
sess = np.where(ny.weekday >= 5, "周末",
       np.where(h.index.isin(CPI.floor("1h")), "CPI 发布后1h",
       np.where((ny.hour == 9), "美股开盘那1h(9:00-10:00 ET)",
       np.where((ny.hour >= 8) & (ny.hour < 16), "美股交易时段其他小时", "工作日非美股时段"))))
h["时段"] = sess
h["活跃度"] = pd.qcut(h["prev24"], 3, labels=["过去24h平静", "过去24h一般", "过去24h活跃"])
h = h.dropna(subset=["prev24", "rng4"])
t = h.groupby(["时段", "活跃度"], observed=True).agg(
    样本=("rng1", "size"), 未来1h振幅中位=("rng1", "median"), 未来1h振幅P80=("rng1", lambda s: s.quantile(.8)),
    未来4h振幅中位=("rng4", "median"), 未来4h振幅P80=("rng4", lambda s: s.quantile(.8))).round(2)
t["1h中位≈点数@82k"] = (t["未来1h振幅中位"] / 100 * 82000).round(-1).astype(int)
t["4hP80≈点数@82k"] = (t["未来4h振幅P80"] / 100 * 82000).round(-1).astype(int)
pd.set_option("display.width", 250)
print(t.to_string())
t.to_csv(os.path.join(HERE, "results", "range_table.csv"))
