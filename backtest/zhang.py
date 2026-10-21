"""张主任打法：指标、行情状态和信号的代码化版本。

所有函数只用当前及之前的 K 线（不偷看未来）。信号出现在第 t 根 K 线收盘，
回测时在第 t+1 根开盘价进场。
"""
import numpy as np
import pandas as pd


# ---------- 指标 ----------

def load_5m(path):
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("time").drop(columns=["open_time"]).astype(float)
    return df


def kdj(df, n=9):
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    rsv = ((df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100).fillna(50)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    return k, d, 3 * k - 2 * d


def rsi(close, n=6):
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def macd_hist(close, fast=12, slow=26, sig=9):
    dif = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    dea = dif.ewm(span=sig, adjust=False).mean()
    return dif - dea  # 正柱 = 多头动能，负柱 = 空头动能（与软件配色无关）


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df, n=14):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    a = atr(df, n)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def add_indicators(df):
    c = df["close"]
    for n in (7, 25, 99):
        df[f"ma{n}"] = c.rolling(n).mean()
    df["k"], df["d"], df["j"] = kdj(df)
    df["rsi6"] = rsi(c, 6)
    df["hist"] = macd_hist(c)
    df["atr"] = atr(df)
    return df


# ---------- 行情状态（4 小时） ----------

def regime_4h(df5, adx_min=25, slope_bars=6):
    """把 5 分钟数据合成 4 小时线，判断 上涨趋势 / 下跌趋势 / 区间震荡。

    趋势 = 4h ADX(14) >= adx_min，且收盘价与 MA25 同侧、MA25 在最近 slope_bars 根里同向。
    只用已经走完的 4h K 线，再对齐回 5 分钟。
    """
    h4 = df5[["open", "high", "low", "close", "volume"]].resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    h4["ma25"] = h4["close"].rolling(25).mean()
    h4["adx"] = adx(h4)
    slope = h4["ma25"] - h4["ma25"].shift(slope_bars)
    reg = np.where((h4["adx"] >= adx_min) & (h4["close"] > h4["ma25"]) & (slope > 0), "up",
          np.where((h4["adx"] >= adx_min) & (h4["close"] < h4["ma25"]) & (slope < 0), "down", "range"))
    h4["regime"] = reg
    h4.loc[h4["ma25"].isna() | h4["adx"].isna(), "regime"] = "na"
    # 4h K 线在其结束时刻才可用：开盘时间 + 4h
    avail = h4["regime"].copy()
    avail.index = avail.index + pd.Timedelta(hours=4)
    out = avail.reindex(df5.index, method="ffill").fillna("na")
    return out, h4


def _h4(df5):
    return df5[["open", "high", "low", "close", "volume"]].resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def regime_er(df5, win=12, er_min=0.3, hindsight=False):
    """效率比（ER）判定：净位移 / 路径总长。ER 高 = 走得直 = 趋势，低 = 来回磨 = 震荡。

    win 为 4h K 线根数（12 根 = 2 天）。
    hindsight=False：只看过去 win 根（实时可用）。
    hindsight=True：用前后各 win/2 根（事后真实状态，实盘拿不到，只用来衡量「状态判对」值多少）。
    """
    h4 = _h4(df5)
    c = h4["close"]
    step = c.diff().abs()
    if hindsight:
        half = win // 2
        net = c.shift(-half) - c.shift(half)
        path = step.rolling(win).sum().shift(-half)
    else:
        net = c - c.shift(win)
        path = step.rolling(win).sum()
    er = (net.abs() / path).where(path > 0)
    reg = np.where(er >= er_min, np.where(net > 0, "up", "down"), "range")
    reg = pd.Series(reg, index=h4.index).where(er.notna(), "na")
    if hindsight:
        # 事后标签直接贴在该 4h 时段本身
        return reg.reindex(df5.index, method="ffill").fillna("na")
    reg.index = reg.index + pd.Timedelta(hours=4)
    return reg.reindex(df5.index, method="ffill").fillna("na")


# ---------- 信号 ----------

def signals(df, look=6, vol_win=24):
    """返回 short_A/long_A（只看扳机）和 short_B/long_B（张主任完整版）布尔列。

    扳机（10/16 01:43 张主任的进场点）：收盘跌破 MA7，且 MA7 拐头向下，MA7 仍在 MA25 上方或刚下穿。
    完整版额外要求最近 look 根 K 线内（10/17 00:39 的六项 + 10/17 的「超买和衰竭缺一不可」）：
      - 超买：J 最高 > 100 且 RSI6 最高 > 70
      - 衰竭：MACD 正柱比最近峰值缩短
      - 量：创新高那根的量低于之前 vol_win 根的最大量（量价顶背离），或最近 3 根量连续递减
      - 之前价格站在 MA7 上方（最近 look 根里至少 4 根收盘在 MA7 上）
    做多是完全镜像（J < 0、RSI6 < 20、负柱收敛、底背离、长期在 MA7 下方后站上 MA7 且 MA7 拐头向上）。
    """
    c, ma7, ma25 = df["close"], df["ma7"], df["ma25"]
    ma7_dn = ma7 < ma7.shift(1)
    ma7_up = ma7 > ma7.shift(1)
    cross_dn_recent = ((ma7 < ma25) & (ma7.shift(1) >= ma25.shift(1))).rolling(3).max().astype(bool)
    cross_up_recent = ((ma7 > ma25) & (ma7.shift(1) <= ma25.shift(1))).rolling(3).max().astype(bool)

    trig_s = (c < ma7) & ma7_dn & (ma7.shift(1) >= ma7.shift(2)) & ((ma7 > ma25) | cross_dn_recent)
    trig_l = (c > ma7) & ma7_up & (ma7.shift(1) <= ma7.shift(2)) & ((ma7 < ma25) | cross_up_recent)

    hot = (df["j"].rolling(look).max() > 100) & (df["rsi6"].rolling(look).max() > 70)
    cold = (df["j"].rolling(look).min() < 0) & (df["rsi6"].rolling(look).min() < 20)

    h = df["hist"]
    fade_s = (h.rolling(look).max() > 0) & (h < h.rolling(look).max())
    fade_l = (h.rolling(look).min() < 0) & (h > h.rolling(look).min())

    v = df["volume"]
    three_down = (v < v.shift(1)) & (v.shift(1) < v.shift(2))
    # 最近 look 根内的最高价那根 K 线的量，与它之前 vol_win 根里的最大量比较
    hi_idx = df["high"].rolling(look).apply(np.argmax, raw=True)
    lo_idx = df["low"].rolling(look).apply(np.argmin, raw=True)
    vol_arr = v.to_numpy()
    n = len(df)
    vol_at_hi = np.full(n, np.nan)
    vol_at_lo = np.full(n, np.nan)
    prior_max = v.shift(look).rolling(vol_win).max().to_numpy()
    hi_i = hi_idx.to_numpy()
    lo_i = lo_idx.to_numpy()
    for t in range(look, n):
        if not np.isnan(hi_i[t]):
            vol_at_hi[t] = vol_arr[t - look + 1 + int(hi_i[t])]
        if not np.isnan(lo_i[t]):
            vol_at_lo[t] = vol_arr[t - look + 1 + int(lo_i[t])]
    new_high = df["high"].rolling(look).max() >= df["high"].shift(look).rolling(vol_win).max()
    new_low = df["low"].rolling(look).min() <= df["low"].shift(look).rolling(vol_win).min()
    div_s = new_high & (vol_at_hi < 0.9 * prior_max)
    div_l = new_low & (vol_at_lo < 0.9 * prior_max)
    vol_s = div_s | three_down
    vol_l = div_l | three_down

    above7 = (c > ma7).shift(1).rolling(look).sum() >= 4
    below7 = (c < ma7).shift(1).rolling(look).sum() >= 4

    df["short_A"] = trig_s.fillna(False)
    df["long_A"] = trig_l.fillna(False)
    df["short_B"] = (trig_s & hot & fade_s & vol_s & above7).fillna(False)
    df["long_B"] = (trig_l & cold & fade_l & vol_l & below7).fillna(False)
    return df


def us_open_window(index, before_min=60, after_min=30):
    """标记美股开盘（纽约 9:30）前 before_min 到开盘后 after_min 分钟，自动处理夏令时。"""
    ny = index.tz_convert("America/New_York")
    mins = ny.hour * 60 + ny.minute - (9 * 60 + 30)
    weekday = ny.weekday < 5
    return pd.Series(weekday & (mins >= -before_min) & (mins <= after_min), index=index)
