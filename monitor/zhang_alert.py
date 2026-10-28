"""张主任多周期规则提醒（10/28 版），和面板「张主任多周期信号」卡片、backtest/zhang_mtf.py 同口径。

每根 5 分钟 K 线收盘检查一次：
  ① 4 小时 MA99 方向（已收盘 K 线，和 3 根前比）定大方向；② 1 小时、30 分 MA7 方向看所处阶段；
  ③ 5 分：RSI6 > 80 或 J > 110 超买，RSI6 < 20 或 J < -5 超卖；④ 15 分（含当前未走完那根）：RSI6 > 70 或 J > 100 超买，
  RSI6 < 20 或 J < 0 超卖。同一个指标要 5 分和 15 分同时在区间外才提醒（RSI 优先：两个周期 RSI 都在区间外一定报，
  KDJ 不用满足；只有 KDJ 两个周期在区间外也报，但写明参考性弱一些）；⑤ 再有量价背离 = 强烈；⑥ 附上 5 分 MA7 是否拐头。
  另外：两个周期都超买（超卖）却还在放量创新高（新低）→「反常」提醒；
  5 分 / 15 分 / 30 分 / 1 小时 / 4 小时全部在区间外 →「极端」提醒，写明历史上通常先反向走多远、50 倍 / 100 倍先爆仓的比例。
同一种提醒同方向 60 分钟内只发一次。顺 4 小时大方向的发红色（马上推），逆大方向的发黄色（合并推）。
回测见 backtest/README.md「张主任多周期规则」：方向对的比例约 58%，但扣手续费后每笔为负，所以提醒正文会写明只是提示。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backtest"))
import zhang  # noqa: E402

NOTE = "回测：同类提示之后 15 分钟方向对约 58%，但平均幅度不够付手续费，只作提示。"
# 极端：5 分 / 15 分 / 30 分 / 1 小时 / 4 小时全部在区间外。数字来自 backtest/zhang_mtf.py 第 2b 节（2021–2026，一天只算一次）
EXTREME = {
    "short": dict(med=0.65, p80=1.63, lev100=36, lev50=13, net=-0.07, yrs="6 年里只有 1 年为正"),
    "long": dict(med=0.72, p80=1.88, lev100=39, lev50=19, net=+0.12, yrs="6 年里 4 年为正，但 2025、2026 都为负"),
}


def _agg(d, rule):
    return d.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def _osc(b):
    _, _, j = zhang.kdj(b)
    return float(zhang.rsi(b["close"], 6).iloc[-1]), float(j.iloc[-1])


def evaluate(d5, h4):
    """d5：已收盘的 5 分钟 K 线（≥ 600 根）；h4：已收盘的 4 小时 K 线（≥ 103 根）。返回这一根收盘时的状态。"""
    end = d5.index[-1] + pd.Timedelta("5min")
    r5, j5 = _osc(d5.iloc[-300:])
    b15 = _agg(d5.iloc[-900:], "15min")          # 最后一根可能没走完，和看盘软件一样算进去
    r15, j15 = _osc(b15.iloc[-300:])
    r30, j30 = _osc(_agg(d5, "30min").iloc[-200:])
    r1h, j1h = _osc(_agg(d5, "1h").iloc[-120:])
    part = d5[d5.index >= h4.index[-1] + pd.Timedelta("4h")]   # 当前还没走完的 4 小时那根
    b4 = pd.concat([h4[["open", "high", "low", "close", "volume"]], _agg(part, "4h")]) if len(part) else h4
    r4h, j4h = _osc(b4.iloc[-120:])
    big = ((r15, j15), (r30, j30), (r1h, j1h), (r4h, j4h))
    ext_s = (r5 > 80 or j5 > 110) and all(r > 70 or j > 100 for r, j in big)
    ext_l = (r5 < 20 or j5 < -5) and all(r < 20 or j < 0 for r, j in big)

    def phase(rule):
        b = _agg(d5, rule)
        b = b[b.index + pd.Timedelta(rule) <= end]  # 只用已收盘的
        m = b["close"].rolling(7).mean()
        return int(np.sign(m.iloc[-1] - m.iloc[-2]))

    ma99 = h4["close"].rolling(99).mean()
    dir4 = int(np.sign(ma99.iloc[-1] - ma99.iloc[-4]))
    v, h, l = d5["volume"], d5["high"], d5["low"]
    vol_lo = v.iloc[-6:].max() < 0.9 * v.iloc[-30:-6].max()
    div_s = h.iloc[-6:].max() >= h.iloc[-30:-6].max() and vol_lo
    div_l = l.iloc[-6:].min() <= l.iloc[-30:-6].min() and vol_lo
    m7 = d5["close"].rolling(7).mean()
    t7, t7p = np.sign(m7.iloc[-1] - m7.iloc[-2]), np.sign(m7.iloc[-2] - m7.iloc[-3])
    by_s = "+".join(n for n, ok in (("RSI", r5 > 80 and r15 > 70), ("KDJ", j5 > 110 and j15 > 100)) if ok)
    by_l = "+".join(n for n, ok in (("RSI", r5 < 20 and r15 < 20), ("KDJ", j5 < -5 and j15 < 0)) if ok)
    short, long = bool(by_s), not by_s and bool(by_l)
    hot = v.iloc[-1] > 2 * v.iloc[-25:-1].mean() and v.iloc[-1] > v.iloc[-2]
    return dict(t=end, close=float(d5["close"].iloc[-1]), dir4=dir4, ma99=float(ma99.iloc[-1]),
                ph1=phase("1h"), ph30=phase("30min"), r5=r5, j5=j5, r15=r15, j15=j15,
                short=short, long=long, by=by_s if short else by_l, div_s=bool(div_s), div_l=bool(div_l), t7=int(t7), turned=bool(t7 != t7p),
                anom_s=bool(short and hot and h.iloc[-1] >= h.iloc[-12:].max()),
                anom_l=bool(long and hot and l.iloc[-1] <= l.iloc[-12:].min()),
                ext="short" if ext_s else "long" if ext_l else None,
                ext_rsi=dict(m5=r5, m15=r15, m30=r30, h1=r1h, h4=r4h))


def describe_extreme(z):
    side = z.get("ext")
    if not side:
        return []
    s, e = side == "short", EXTREME[side]
    ob, word = ("超买", "空") if s else ("超卖", "多")
    r = z["ext_rsi"]
    body = (f"5 分、15 分、30 分、1 小时、4 小时全部{ob}（RSI6：{r['m5']:.0f} / {r['m15']:.0f} / {r['m30']:.0f} / {r['h1']:.0f} / {r['h4']:.0f}），现价 {z['close']:,.0f}。"
            f"历史上同样情况之后 4 小时内，价格通常还会先往{'上冲' if s else '下砸'} {e['med']}%，五次里有一次超过 {e['p80']}%；"
            f"按这个幅度，50 倍杠杆约 {e['lev50']}% 的时候会先爆仓，100 倍约 {e['lev100']}%。"
            f"按 4 小时后平仓算扣费每笔 {e['net']:+.2f}%（{e['yrs']}）。方向常常是对的，但先扛得住反向那一段才行。")
    return [("red", f"张主任规则 · 极端：所有周期都{ob}（偏{word}，先防反向冲）", body, f"extreme-{side}")]


def describe(z):
    """返回 [(level, title, body, key)]，没有信号返回空。"""
    side = "short" if z["short"] else "long" if z["long"] else None
    if not side:
        return []
    s = side == "short"
    word, ob = ("做空", "超买") if s else ("做多", "超卖")
    with4 = z["dir4"] < 0 if s else z["dir4"] > 0
    div = z["div_s"] if s else z["div_l"]
    turned_ok = z["t7"] < 0 if s else z["t7"] > 0
    by = {"RSI+KDJ": "RSI 和 KDJ", "KDJ": "KDJ"}.get(z["by"], "RSI")
    byt = f"{by} 两个周期都{ob}" + ("（RSI 没到，参考性弱一些）" if by == "KDJ" else "")
    arrow = lambda x: "向上" if x > 0 else "向下" if x < 0 else "走平"
    facts = (f"现价 {z['close']:,.0f}。4 小时 MA99 {z['ma99']:,.0f} {arrow(z['dir4'])}；1 小时 {arrow(z['ph1'])}、30 分 {arrow(z['ph30'])}；"
             f"5 分 RSI6 {z['r5']:.1f} / J {z['j5']:.1f}，15 分 RSI6 {z['r15']:.1f} / J {z['j15']:.1f}；"
             f"5 分 MA7 {arrow(z['t7'])}{'（刚拐头）' if z['turned'] else ''}。")
    if z["anom_s"] if s else z["anom_l"]:
        return [("red", f"张主任规则 · 反常异动：{ob}还在放量{'冲高' if s else '下杀'}",
                 f"5 分和 15 分 {byt}，但这根量是之前 2 小时均量的 2 倍以上，还在创{'新高' if s else '新低'}，可能有场外资金在推，先别{word}。" + facts, f"anom-{side}")]
    title = f"张主任规则 · {'强烈' if div else ''}提示{word}" + ("" if with4 else "（逆 4 小时大方向）")
    body = (f"5 分和 15 分 {byt}" + (f"，并且量价{'顶' if s else '底'}背离" if div else "") + "；"
            + ("顺 4 小时 MA99 方向。" if with4 else "但逆着 4 小时 MA99 方向，要更小心。")
            + ("MA7 已拐头。" if turned_ok else "MA7 还没拐头，可以再等等。") + facts + NOTE)
    return [("red" if with4 else "yellow", title, body, f"{'strong' if div else 'sig'}-{side}")]


class ZhangAlert:
    def __init__(self, out_dir, send, log=print):
        self.path = os.path.join(out_dir, "zhang_alert_state.json")
        self.send, self.log = send, log
        try:
            self.st = json.load(open(self.path))
        except Exception:
            self.st = {"last_bar": None, "sent": {}}

    def step(self):
        try:
            import market_data as MD
            from paper import fetch_5m
            d5 = fetch_5m()
            k4 = MD.klines("4h", 120)
            h4 = pd.DataFrame([[x[0], x[1], x[2], x[3], x[4], x[5]] for x in k4], columns=["t", "open", "high", "low", "close", "volume"])
            h4.index = pd.to_datetime(h4.pop("t"), unit="ms", utc=True)
            h4 = h4.astype(float).iloc[:-1]
        except Exception as ex:
            self.log("张主任规则取数失败:", ex)
            return
        bar = d5.index[-1].isoformat()
        if bar == self.st["last_bar"]:
            return
        first = self.st["last_bar"] is None
        self.st["last_bar"] = bar
        z = evaluate(d5, h4)
        now = z["t"].timestamp()
        for level, title, body, key in describe_extreme(z) + describe(z):
            gap = 4 * 3600 if key.startswith("extreme") else 3600   # 极端情况往往持续好几个小时，4 小时内只提醒一次
            if first or now - self.st["sent"].get(key, 0) < gap:
                continue
            self.st["sent"][key] = now
            self.send(level, title, body, "张主任规则")
        json.dump(self.st, open(self.path, "w"))
