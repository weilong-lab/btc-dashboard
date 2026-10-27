/* 三个页面共用：页面切换、浅色 / 深色切换、设置下拉、第一次打开先选账户、切换账户后提醒同步、检查云端令牌 */
"use strict";
const UI = (() => {
  const page = document.body.dataset.page;
  const NAMES = { main: "陈总", zhang: "张主任" };
  const ls = { get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* 存不了 */ } }, del: k => { try { localStorage.removeItem(k); } catch (e) { /* 无所谓 */ } } };
  const PAGES = [["panel", "./", "作战面板", "面板"], ["sim", "sim.html", "模拟盘", "模拟"], ["review", "review.html", "复盘", "复盘"]];
  document.querySelectorAll(".pnav").forEach(n => {
    n.setAttribute("aria-label", "页面");
    n.innerHTML = PAGES.map(([k, href, l, s]) => `<a href="${href}"${k === page ? ' aria-current="page"' : ""}><span class="l">${l}</span><span class="s">${s}</span></a>`).join("");
  });
  // ---------- 浅色 / 深色背景：顶栏按钮一键切换，存在本机（三个页面共用）；没选过就跟随系统 ----------
  const root = document.documentElement, sysDark = matchMedia("(prefers-color-scheme: dark)"), themeFns = [];
  const isDark = () => root.dataset.theme ? root.dataset.theme === "dark" : sysDark.matches;
  const SUN = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  const MOON = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>';
  const thBtns = [];
  const paintTheme = () => thBtns.forEach(b => {
    const d = isDark();
    b.innerHTML = (d ? SUN : MOON) + `<span class="tl">${d ? "浅色" : "深色"}</span>`;
    b.setAttribute("aria-label", d ? "切换到浅色背景" : "切换到深色背景"); b.title = b.getAttribute("aria-label");
  });
  const themeChanged = () => { paintTheme(); themeFns.forEach(f => { try { f(isDark()); } catch (e) { /* 某个图表重画失败不影响其他 */ } }); };
  function setTheme(t) { root.dataset.theme = t; ls.set("btc_theme", t); themeChanged(); }
  function onTheme(fn) { themeFns.push(fn); }
  { const t = ls.get("btc_theme"); if (t === "light" || t === "dark") root.dataset.theme = t; }
  sysDark.addEventListener("change", () => { if (!root.dataset.theme) themeChanged(); });
  addEventListener("storage", e => { if (e.key === "btc_theme" && (e.newValue === "light" || e.newValue === "dark")) { root.dataset.theme = e.newValue; themeChanged(); } });
  document.querySelectorAll(".pnav").forEach(n => {
    const b = document.createElement("button"); b.type = "button"; b.className = "thbtn";
    b.onclick = () => setTheme(isDark() ? "light" : "dark");
    // 和页面切换放在一组（手机上同在第一行），不挤第二行的工具和行情数字
    const g = document.createElement("div"); g.className = "navgrp";
    n.before(g); g.append(b, n);
    thBtns.push(b);
  });
  paintTheme();

  const acct = ls.get("btc_account") === "zhang" ? "zhang" : "main";
  document.querySelectorAll(".prefs .who").forEach(el => { if (!el.textContent) el.textContent = NAMES[acct]; });
  document.addEventListener("click", e => document.querySelectorAll("details.prefs[open]").forEach(d => { if (!d.contains(e.target)) d.open = false; }));
  document.addEventListener("keydown", e => { if (e.key === "Escape") document.querySelectorAll("details.prefs[open]").forEach(d => { d.open = false; }); });

  // ---------- 弹窗 ----------
  function modal(html) {
    const el = document.createElement("div"); el.className = "uimodal"; el.innerHTML = `<div role="dialog" aria-modal="true">${html}</div>`;
    document.body.appendChild(el); return el;
  }

  // ---------- 第一次在这台设备打开：先选是谁（不再默认陈总，免得把别人的单记到陈总名下） ----------
  if (!ls.get("btc_account")) {
    const m = modal(`<h3>这台设备是谁在用？</h3><p>喊单、交易日志、模拟盘按人分开存。选错了会把单记到别人名下，之后可以在右上角「设置」里切换。</p>
      <div class="uibig">${Object.entries(NAMES).map(([k, n]) => `<button type="button" data-a="${k}">${n}</button>`).join("")}</div>`);
    m.addEventListener("click", e => { const b = e.target.closest("[data-a]"); if (!b) return; ls.set("btc_account", b.dataset.a); markSwitched(b.dataset.a); location.reload(); });
  }

  // ---------- 切换账户后：提醒先同步一次云端 ----------
  let syncFn = null, waiters = [];
  function onSync(fn) { syncFn = fn; waiters.forEach(w => w(fn)); waiters = []; }
  const getSync = () => syncFn ? Promise.resolve(syncFn) : new Promise(r => waiters.push(r));
  function markSwitched(to) { ls.set("btc_acct_switch", JSON.stringify({ to, t: Date.now() })); }
  let sw = null; try { sw = JSON.parse(ls.get("btc_acct_switch")); } catch (e) { /* 没有 */ }
  if (sw && Date.now() - sw.t < 120e3 && ls.get("btc_account")) {
    ls.del("btc_acct_switch");
    const m = modal(`<h3>已切换到 ${NAMES[sw.to] || sw.to}</h3>
      <p>换了账户，建议马上同步一次云端：先把云端最新的记录拉下来，再接着操作，免得看到的是这台设备上的旧数据。</p>
      <p class="uist" aria-live="polite"></p>
      <div class="uirow"><button type="button" data-x>稍后</button><button type="button" class="pri" data-go>立即同步</button></div>`);
    const st = m.querySelector(".uist"), go = m.querySelector("[data-go]");
    m.querySelector("[data-x]").onclick = () => m.remove();
    go.onclick = async () => {
      if (go.dataset.done) return m.remove();
      go.disabled = true; st.className = "uist"; st.textContent = "同步中…";
      try { const r = await (await getSync())(); st.className = "uist " + (r.ok ? "ok" : "no"); st.textContent = (r.ok ? "✓ 已同步：" : "✗ 没同步成功：") + r.msg; }
      catch (e) { st.className = "uist no"; st.textContent = "✗ 没同步成功：" + (e.message || e); }
      go.disabled = false; go.dataset.done = "1"; go.textContent = "好的";
    };
  }

  // ---------- 云端令牌：先确认能打开私有仓库，打不开就说清楚原因（以前会被当成「云端还没有文件」） ----------
  let tokOk = { tok: "", at: 0 };
  async function checkToken(token) {
    if (!token || (tokOk.tok === token && Date.now() - tokOk.at < 10 * 60e3)) return;
    let r; try { r = await fetch("https://api.github.com/repos/weilong-lab/btc-records", { headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" }, cache: "no-store" }); }
    catch (e) { return; }   // 断网之类，交给后面的同步自己报错
    if (r.status === 401) throw new Error("令牌无效或已过期，请重新生成");
    if (r.status === 403 || r.status === 404) throw new Error("这个令牌打不开私有仓库 btc-records：要在 weilong-lab 账号下生成细粒度令牌，只勾 btc-records，Contents 选 Read and write");
    if (r.ok) tokOk = { tok: token, at: Date.now() };
  }
  return { onSync, markSwitched, checkToken, NAMES, isDark, onTheme };
})();
