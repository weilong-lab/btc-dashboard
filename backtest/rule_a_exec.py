"""规则 A 的执行方式敏感度：挂单进场（会被逆向成交）vs 市价进场；以及更高把握门槛。"""
import numpy as np, pandas as pd
from rules_backtest import load, MAKER, TAKER
d = load()
o, h, l, c, p4 = (d[k].to_numpy() for k in ("open", "high", "low", "close", "p4h"))
blk = d.pre_open.to_numpy(); n = len(d)
def run(th, entry, exit_, H=48, W=3):
    out, t = [], 0
    while t < n - H - 2 * W - 2:
        side = 1 if p4[t] >= 0.5 + th else -1 if p4[t] <= 0.5 - th else 0
        if side == 0 or blk[t]: t += 1; continue
        if entry == "market":
            f, px, fe = t + 1, o[t + 1], TAKER
        else:
            px = c[t]; f = next((k for k in range(t + 1, t + 1 + W) if (l[k] < px if side > 0 else h[k] > px)), None); fe = MAKER
            if f is None: t += 1; continue
        end = f + H
        if exit_ == "market":
            xp, fx = c[end], TAKER
        else:
            lim = c[end]; g = next((k for k in range(end + 1, end + 1 + W) if (h[k] > lim if side > 0 else l[k] < lim)), None)
            xp, fx = (lim, MAKER) if g is not None else (c[end + W], TAKER)
        out.append((d.index[t], side * (xp / px - 1) * 100 - fe - fx)); t = end + 1
    r = pd.DataFrame(out, columns=["time", "ret"]); by = r.groupby(r.time.dt.year).ret.mean()
    return dict(门槛=f"≥{50+th*100:.0f}%/≤{50-th*100:.0f}%", 进场=entry, 离场=exit_, 每年=round(len(r)/6), 胜率=round((r.ret>0).mean()*100,1),
                每笔pct=round(r.ret.mean(),3), 不计费=round((r.ret + (TAKER if entry=='market' else MAKER) + 0.035).mean(),3),
                t值=round(r.ret.mean()/(r.ret.std()/np.sqrt(len(r))),2), 正收益年数=f"{(by>0).sum()}/{len(by)}")
rows = [run(th, e, x) for th in (0.08, 0.10, 0.12) for e, x in (("maker", "maker"), ("market", "maker"), ("market", "market"))]
pd.set_option("display.width", 220); print(pd.DataFrame(rows).to_string(index=False))
