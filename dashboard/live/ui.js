/* 三个页面共用：画页面切换，设置下拉上显示当前账户，点别处或按 Esc 收起 */
(function () {
  const page = document.body.dataset.page;
  const PAGES = [["panel", "./", "作战面板", "面板"], ["sim", "sim.html", "模拟盘", "模拟"], ["review", "review.html", "复盘", "复盘"]];
  document.querySelectorAll(".pnav").forEach(n => {
    n.setAttribute("aria-label", "页面");
    n.innerHTML = PAGES.map(([k, href, l, s]) => `<a href="${href}"${k === page ? ' aria-current="page"' : ""}><span class="l">${l}</span><span class="s">${s}</span></a>`).join("");
  });
  let acct = "main"; try { acct = localStorage.getItem("btc_account") === "zhang" ? "zhang" : "main"; } catch (e) { /* 默认陈总 */ }
  document.querySelectorAll(".prefs .who").forEach(el => { if (!el.textContent) el.textContent = acct === "zhang" ? "张主任" : "陈总"; });
  document.addEventListener("click", e => document.querySelectorAll("details.prefs[open]").forEach(d => { if (!d.contains(e.target)) d.open = false; }));
  document.addEventListener("keydown", e => { if (e.key === "Escape") document.querySelectorAll("details.prefs[open]").forEach(d => { d.open = false; }); });
})();
