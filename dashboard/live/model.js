/* 方向模型（浏览器 + Node 通用）。与 backtest/direction_model.py 的 features() 逐项对应。
   bars: [{t: 开盘时间毫秒, o, h, l, c, v, tb}]，按时间升序，最后一根可以是未走完的 K 线。 */
(function (root) {
  const NYFMT = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "2-digit", hourCycle: "h23" });
  function nyParts(ms) {
    const p = NYFMT.formatToParts(new Date(ms));
    const wd = p.find(x => x.type === "weekday").value;
    return { weekend: wd === "Sat" || wd === "Sun", hour: +p.find(x => x.type === "hour").value };
  }
  const mean = (a, i, n) => { let s = 0; for (let k = i - n + 1; k <= i; k++) s += a[k]; return s / n; };
  function median(a, i, n) {
    const s = a.slice(i - n + 1, i + 1).sort((x, y) => x - y), m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  function ewm(arr, alpha) {           // pandas ewm(adjust=False)，跳过开头的 NaN
    const out = new Array(arr.length).fill(NaN); let prev = NaN;
    for (let i = 0; i < arr.length; i++) {
      const x = arr[i];
      if (isNaN(x)) { out[i] = prev; continue; }
      prev = isNaN(prev) ? x : alpha * x + (1 - alpha) * prev; out[i] = prev;
    }
    return out;
  }
  function rsi6(c) {
    const up = [NaN], dn = [NaN];
    for (let i = 1; i < c.length; i++) { const d = c[i] - c[i - 1]; up.push(Math.max(d, 0)); dn.push(Math.max(-d, 0)); }
    const u = ewm(up, 1 / 6), d = ewm(dn, 1 / 6);
    return u.map((x, i) => d[i] === 0 ? NaN : 100 - 100 / (1 + x / d[i]));
  }
  function kdjJ(b) {
    const rsv = b.map((x, i) => {
      if (i < 8) return 50;
      let lo = Infinity, hi = -Infinity;
      for (let k = i - 8; k <= i; k++) { lo = Math.min(lo, b[k].l); hi = Math.max(hi, b[k].h); }
      return hi === lo ? 50 : (x.c - lo) / (hi - lo) * 100;
    });
    const k = ewm(rsv, 1 / 3), d = ewm(k, 1 / 3);
    return k.map((x, i) => 3 * x - 2 * d[i]);
  }
  function macdHist(c) {
    const f = ewm(c, 2 / 13), s = ewm(c, 2 / 27), dif = f.map((x, i) => x - s[i]), dea = ewm(dif, 2 / 10);
    return dif.map((x, i) => x - dea[i]);
  }
  // 4 小时趋势：UTC 对齐的 4h 收盘价 / 其 25 根均值 - 1，只用已经走完的 4h 桶
  function trend4h(b5, atMs) {
    const H4 = 4 * 3600e3, buckets = new Map();
    for (const x of b5) buckets.set(Math.floor(x.t / H4) * H4, x.c);
    const keys = [...buckets.keys()].filter(k => k + H4 <= atMs).sort((a, b) => a - b);
    if (keys.length < 25) return NaN;
    const last = keys.slice(-25).map(k => buckets.get(k));
    return last[24] / (last.reduce((s, x) => s + x, 0) / 25) - 1;
  }
  function features(b, dayBars, b5ForTrend) {
    const i = b.length - 1, c = b.map(x => x.c), v = b.map(x => x.v);
    if (i < Math.max(dayBars, 99) + 1) return null;
    const f = {};
    for (const k of [1, 3, 12, 48, dayBars]) f["ret_" + k] = Math.log(c[i] / c[i - k]);
    for (const n of [7, 25, 99]) f["dist_ma" + n] = c[i] / mean(c, i, n) - 1;
    f.rsi6 = rsi6(c)[i] / 100 - 0.5;
    f.j = (kdjJ(b)[i] - 50) / 100;
    f.hist = macdHist(c)[i] / c[i];
    const med = median(v, i, dayBars);
    f.vol_ratio = Math.log(Math.max(v[i] / med, 1e-3));
    f.taker_buy_1 = (v[i] ? b[i].tb / v[i] : 0.5) - 0.5;
    let tb12 = 0, v12 = 0; for (let k = i - 11; k <= i; k++) { tb12 += b[k].tb; v12 += v[k]; }
    f.taker_buy_12 = tb12 / v12 - 0.5;
    let hi = -Infinity, lo = Infinity; for (let k = i - dayBars + 1; k <= i; k++) { hi = Math.max(hi, b[k].h); lo = Math.min(lo, b[k].l); }
    f.pos24 = (c[i] - lo) / (hi - lo) - 0.5;
    f.range24 = (hi - lo) / c[i];
    const ny = nyParts(b[i].t);
    f.weekend = ny.weekend ? 1 : 0;
    f.us_hours = !ny.weekend && ny.hour >= 9 && ny.hour < 16 ? 1 : 0;
    f.us_open_hour = !ny.weekend && ny.hour === 9 ? 1 : 0;
    f.trend4h = trend4h(b5ForTrend || b, b[i].t);
    return f;
  }
  function predict(model, f) {
    if (!f) return NaN;
    let z = model.w[0];
    for (let k = 0; k < model.cols.length; k++) {
      let x = f[model.cols[k]];
      if (!isFinite(x)) x = model.mu[k];
      x = Math.max(-5, Math.min(5, (x - model.mu[k]) / model.sd[k]));
      z += model.w[k + 1] * x;
    }
    return 1 / (1 + Math.exp(-z));
  }
  /* 张主任完整版信号（与 backtest/zhang.py signals() 同口径），返回最近 3 根内是否触发及各项状态 */
  function zhang(b, look = 6, volWin = 24) {
    const n = b.length; if (n < 130) return null;
    const c = b.map(x => x.c), v = b.map(x => x.v), J = kdjJ(b), R = rsi6(c), H = macdHist(c);
    const ma = (i, k) => mean(c, i, k);
    const at = i => {
      const m7 = ma(i, 7), m7p = ma(i - 1, 7), m7pp = ma(i - 2, 7), m25 = ma(i, 25), m7p25 = ma(i - 1, 25);
      const crossDn = [0, 1, 2].some(k => ma(i - k, 7) < ma(i - k, 25) && ma(i - k - 1, 7) >= ma(i - k - 1, 25));
      const crossUp = [0, 1, 2].some(k => ma(i - k, 7) > ma(i - k, 25) && ma(i - k - 1, 7) <= ma(i - k - 1, 25));
      const trigS = c[i] < m7 && m7 < m7p && m7p >= m7pp && (m7 > m25 || crossDn);
      const trigL = c[i] > m7 && m7 > m7p && m7p <= m7pp && (m7 < m25 || crossUp);
      const win = a => a.slice(i - look + 1, i + 1);
      const hot = Math.max(...win(J)) > 100 && Math.max(...win(R)) > 70, cold = Math.min(...win(J)) < 0 && Math.min(...win(R)) < 20;
      const hMax = Math.max(...win(H)), hMin = Math.min(...win(H));
      const fadeS = hMax > 0 && H[i] < hMax, fadeL = hMin < 0 && H[i] > hMin;
      const threeDown = v[i] < v[i - 1] && v[i - 1] < v[i - 2];
      const hiW = b.slice(i - look + 1, i + 1), loIdx = hiW.reduce((m, x, k) => x.l < hiW[m].l ? k : m, 0), hiIdx = hiW.reduce((m, x, k) => x.h > hiW[m].h ? k : m, 0);
      const prior = b.slice(i - look - volWin + 1, i - look + 1), priorMaxV = Math.max(...prior.map(x => x.v));
      const newHigh = hiW[hiIdx].h >= Math.max(...prior.map(x => x.h)), newLow = hiW[loIdx].l <= Math.min(...prior.map(x => x.l));
      const volS = (newHigh && hiW[hiIdx].v < 0.9 * priorMaxV) || threeDown, volL = (newLow && hiW[loIdx].v < 0.9 * priorMaxV) || threeDown;
      let above = 0, below = 0; for (let k = i - look; k < i; k++) { if (c[k] > ma(k, 7)) above++; if (c[k] < ma(k, 7)) below++; }
      return { trigS, trigL, hot, cold, fadeS, fadeL, volS, volL, above7: above >= 4, below7: below >= 4,
        shortB: trigS && hot && fadeS && volS && above >= 4, longB: trigL && cold && fadeL && volL && below >= 4,
        J: J[i], R: R[i], threeDown, m7Down: m7 < m7p && m7p >= m7pp, m7Up: m7 > m7p && m7p <= m7pp, hist: H[i], hMax, hMin };
    };
    const now = at(n - 1), recent = [n - 1, n - 2, n - 3].map(at);
    let hi12 = -Infinity, lo12 = Infinity; for (let k = n - 12; k < n; k++) { hi12 = Math.max(hi12, b[k].h); lo12 = Math.min(lo12, b[k].l); }
    return { now, shortRecent: recent.some(x => x.shortB), longRecent: recent.some(x => x.longB), hi12, lo12 };
  }
  const api = { features, predict, nyParts, zhang };
  if (typeof module !== "undefined") module.exports = api; else root.BTCModel = api;
})(this);
