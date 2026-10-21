"""模拟盘：按 rules_spec.json 的统一规则，用实时 K 线逐根执行规则 A / B，记录每一笔（和 backtest/rules_backtest.py 同口径）。

由 monitor.py 每轮调用 PaperTrader.step()；也可单独运行：python3 paper.py --once
依赖：pandas、numpy（见 requirements.txt），以及 ../backtest 里的 zhang.py、direction_model.py 和模型参数。
输出：out/paper.json（面板读取）、out/paper_state.json（重启后续跑）
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backtest"))
import zhang  # noqa: E402
from direction_model import features  # noqa: E402

SPEC = json.load(open(os.path.join(ROOT, "rules_spec.json"), encoding="utf-8"))
WEIGHTS = json.load(open(os.path.join(ROOT, "backtest", "results", "direction_weights_full.json"), encoding="utf-8"))
MAKER, TAKER = SPEC["fees"]["maker_pct"], SPEC["fees"]["taker_pct"]
FAPI = "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit=1500"


def fetch_5m():
    with urllib.request.urlopen(urllib.request.Request(FAPI, headers={"User-Agent": "btc-paper/1.0"}), timeout=20) as r:
        k = json.load(r)
    df = pd.DataFrame([[x[0], x[1], x[2], x[3], x[4], x[5], x[9]] for x in k],
                      columns=["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"])
    df["time"] = pd.to_datetime(df.open_time, unit="ms", utc=True)
    df = df.set_index("time").drop(columns=["open_time"]).astype(float)
    return df.iloc[:-1]  # 去掉未收盘的一根


def prob(f, name):
    m = WEIGHTS[name]
    x = ((f[m["cols"]] - np.array(m["mu"])) / np.array(m["sd"])).clip(-5, 5).fillna(0).to_numpy()
    return 1 / (1 + np.exp(-(m["w"][0] + x @ np.array(m["w"][1:]))))


def annotate(df):
    d = zhang.signals(zhang.add_indicators(df.copy()))
    f = features(df, 288).replace([np.inf, -np.inf], np.nan)
    d["p15"], d["p1h"], d["p4h"] = prob(f, "15 分钟"), prob(f, "1 小时"), prob(f, "4 小时")
    h1 = d[["close"]].resample("1h").last().dropna()
    h1["ma25"] = h1.close.rolling(25).mean()
    tr = pd.DataFrame({"up1h": (h1.close > h1.ma25) & (h1.ma25 > h1.ma25.shift(6)),
                       "dn1h": (h1.close < h1.ma25) & (h1.ma25 < h1.ma25.shift(6))})
    tr.index = tr.index + pd.Timedelta("1h")
    d = d.join(tr.reindex(d.index, method="ffill").fillna(False))
    ny = d.index.tz_convert("America/New_York")
    mins = ny.hour * 60 + ny.minute - 570
    d["weekend"] = ny.weekday >= 5
    d["lowvol"] = d.volume < 0.5 * d.volume.rolling(288).median()
    d["pre_open"] = (ny.weekday < 5) & (mins >= -SPEC["event_block_min"]) & (mins < 0)
    d["hi12"], d["lo12"] = d.high.rolling(12).max(), d.low.rolling(12).min()
    return d


class PaperTrader:
    def __init__(self, out_dir, log=print):
        self.out, self.log = out_dir, log
        self.state_path = os.path.join(out_dir, "paper_state.json")
        self.st = json.load(open(self.state_path)) if os.path.exists(self.state_path) else {
            "last_bar": None, "A": {"mode": "flat", "trades": [], "missed": 0}, "B": {"mode": "flat", "trades": []}}

    # ---------- 逐根推进 ----------
    def step(self):
        try:
            d = annotate(fetch_5m())
        except Exception as ex:
            self.log("模拟盘取数失败:", ex); return
        last = self.st["last_bar"]
        new = d if last is None else d[d.index > pd.Timestamp(last)]
        if last is None:
            new = d.iloc[-1:]  # 第一次启动：只从最新一根开始，不回放历史
        for t, bar in new.iterrows():
            self.bar_a(t, bar)
            self.bar_b(t, bar)
            self.st["last_bar"] = t.isoformat()
        self.save(d)

    def bar_a(self, t, b):
        s, A = SPEC["rule_a"], self.st["A"]
        if A["mode"] == "pending":
            A["waited"] += 1
            if (b.low < A["px"]) if A["side"] == "long" else (b.high > A["px"]):
                A.update(mode="open", entry=A["px"], entry_time=t.isoformat(), held=0, fee=MAKER)
            elif A["waited"] >= s["limit_valid_bars"]:
                A["missed"] += 1; A["mode"] = "flat"
            return
        if A["mode"] == "open":
            A["held"] += 1
            sgn = 1 if A["side"] == "long" else -1
            if s.get("use_insurance_stop"):
                stop = A["entry"] * (1 - sgn * s["insurance_stop_pct"] / 100)
                if (b.low <= stop) if sgn > 0 else (b.high >= stop):
                    return self.close("A", t, stop, A["fee"] + TAKER, "保险止损")
            if A["held"] >= s["hold_bars"]:
                A.update(mode="exiting", exit_px=float(b.close), waited=0)
            return
        if A["mode"] == "exiting":
            A["waited"] += 1
            if (b.high > A["exit_px"]) if A["side"] == "long" else (b.low < A["exit_px"]):
                return self.close("A", t, A["exit_px"], A["fee"] + MAKER, "到期挂单平仓")
            if A["waited"] >= s["limit_valid_bars"]:
                return self.close("A", t, float(b.close), A["fee"] + TAKER, "到期市价平仓")
            return
        if b.pre_open or np.isnan(b.p4h):
            return
        side = "long" if b.p4h >= s["p_long"] else "short" if b.p4h <= s["p_short"] else None
        if side:
            A.update(mode="pending", side=side, px=float(b.close), waited=0, signal_time=t.isoformat(), p=round(float(b.p4h), 4))

    def bar_b(self, t, b):
        s, B = SPEC["rule_b"], self.st["B"]
        if B["mode"] == "pending":       # 市价单：在信号后下一根开盘成交
            sgn = 1 if B["side"] == "long" else -1
            px = float(b.open)
            risk = max((px - B["lo12"] + s["stop_atr"] * B["atr"]) if sgn > 0 else (B["hi12"] + s["stop_atr"] * B["atr"] - px), px * 0.001)
            B.update(mode="open", entry=px, entry_time=t.isoformat(), held=0, fee=TAKER, stop=px - sgn * risk, tp=px + sgn * s["tp_R"] * risk)
        if B["mode"] == "open":
            B["held"] += 1
            long_ = B["side"] == "long"
            if (b.low <= B["stop"]) if long_ else (b.high >= B["stop"]):
                return self.close("B", t, B["stop"], B["fee"] + TAKER, "止损")
            if (b.high >= B["tp"]) if long_ else (b.low <= B["tp"]):
                return self.close("B", t, B["tp"], B["fee"] + MAKER, "止盈")
            if B["held"] >= s["max_hold_bars"]:
                return self.close("B", t, float(b.close), B["fee"] + TAKER, "到期平仓")
            return
        pm = (b.p15 + b.p1h) / 2
        ok = not (b.weekend or b.lowvol or b.pre_open)
        side = None
        if ok and b.long_B and not b.dn1h and pm >= 0.5:
            side = "long"
        elif ok and b.short_B and not b.up1h and pm <= 0.5:
            side = "short"
        if side:
            B.update(mode="pending", side=side, signal_time=t.isoformat(), hi12=float(b.hi12), lo12=float(b.lo12), atr=float(b.atr))

    def close(self, rule, t, px, fee, why):
        R = self.st[rule]
        sgn = 1 if R["side"] == "long" else -1
        ret = sgn * (px / R["entry"] - 1) * 100 - fee
        R["trades"].append(dict(side=R["side"], signal_time=R.get("signal_time"), entry_time=R["entry_time"], entry=round(R["entry"], 1),
                                exit_time=t.isoformat(), exit=round(px, 1), ret_pct=round(ret, 4), why=why))
        R["trades"] = R["trades"][-500:]
        for k in ("side", "px", "waited", "entry", "entry_time", "held", "fee", "exit_px", "stop", "tp", "signal_time", "p", "hi12", "lo12", "atr"):
            R.pop(k, None)
        R["mode"] = "flat"
        self.log(f"模拟盘 规则{rule} 平仓：{why}，{ret:+.3f}%")

    # ---------- 输出 ----------
    def save(self, d):
        json.dump(self.st, open(self.state_path, "w"), ensure_ascii=False, default=str)
        out = {"updated": datetime.now(timezone.utc).isoformat(), "last_bar": self.st["last_bar"], "price": float(d.close.iloc[-1]), "rules": {}}
        for k in ("A", "B"):
            R = self.st[k]; tr = R["trades"]
            rets = [x["ret_pct"] for x in tr]
            open_pos = {x: R[x] for x in ("side", "entry", "entry_time", "px", "stop", "tp", "held", "waited", "signal_time") if x in R}
            out["rules"][k] = dict(name=SPEC[f"rule_{k.lower()}"]["name"], mode=R["mode"], position=open_pos, missed=R.get("missed", 0),
                                   n=len(rets), win=round(sum(r > 0 for r in rets) / len(rets) * 100, 1) if rets else None,
                                   avg=round(float(np.mean(rets)), 4) if rets else None, cum=round(float(np.sum(rets)), 3) if rets else 0,
                                   backtest=SPEC[f"rule_{k.lower()}"]["backtest"], recent=tr[-30:][::-1])
        json.dump(out, open(os.path.join(self.out, "paper.json"), "w"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    p = PaperTrader(os.path.join(HERE, "out"))
    p.step()
    print(json.dumps(json.load(open(os.path.join(HERE, "out", "paper.json")))["rules"]["A"], ensure_ascii=False)[:400])
