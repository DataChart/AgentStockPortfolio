/* Agent Stock Portfolio dashboard. Reads the repo's JSON data; no build step. */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const usd = (n, d = 2) =>
    (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (n) => (n > 0 ? "+" : "") + n.toFixed(2) + "%";
  const cls = (n) => (n > 0 ? "up" : n < 0 ? "down" : "");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtDate = (iso) => new Date(iso + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);
  const link = (u, label) => (safeUrl(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(label || hostname(u))}</a>` : esc(u || "n/a"));
  function hostname(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } }

  async function getJSON(path, fallback) {
    try { const r = await fetch(path, { cache: "no-store" }); return r.ok ? await r.json() : fallback; } catch { return fallback; }
  }
  async function getText(path) {
    try { const r = await fetch(path, { cache: "no-store" }); return r.ok ? await r.text() : ""; } catch { return ""; }
  }

  let state = {};

  async function init() {
    const [cfg, ledger, history, portfolio, strategy] = await Promise.all([
      getJSON("config/settings.json", {}),
      getJSON("data/ledger.json", { transactions: [] }),
      getJSON("data/history.json", { snapshots: [] }),
      getJSON("data/portfolio.json", {}),
      getText("data/strategy.md"),
    ]);
    state = { cfg, txs: ledger.transactions || [], snaps: history.snapshots || [], p: portfolio, range: "all" };
    renderHeader();
    renderKpis();
    renderChart();
    renderHistoryTable();
    renderHoldings();
    renderTxLog();
    $("#strategy").innerHTML = strategy ? markdown(strategy) : '<p class="muted">No guidance yet. The analyst writes here after the first review.</p>';
    const repo = cfg.repo_url || "#";
    $("#repo-link").href = repo;
    const fee = activeFee(cfg);
    if (fee) $("#fee-note").textContent =
      `Fee model: ${usd(fee.commission_per_trade)} commission per trade, plus ${fee.slippage_pct}% slippage (buys fill above the quote, sells below). ` +
      `Limits: ${cfg.limits.max_buys_per_day} buy and ${cfg.limits.max_sells_per_day} sell per trading day. Starting cash ${usd(cfg.starting_cash, 0)}.`;
    document.querySelectorAll(".range button").forEach((b) =>
      b.addEventListener("click", () => {
        document.querySelectorAll(".range button").forEach((x) => x.classList.toggle("on", x === b));
        state.range = b.dataset.range;
        renderChart();
      })
    );
    let t;
    window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(renderChart, 120); });
  }

  function activeFee(cfg) {
    const s = cfg.fees && cfg.fees.schedule;
    return s && s.length ? s[s.length - 1] : null;
  }

  function renderHeader() {
    const { p, txs, snaps } = state;
    $("#asof").textContent = p.as_of ? `values as of ${fmtDate(p.as_of)} close` : "no data yet";
    const all = txs.map((t) => t.fact_check || {}).concat(snaps.map((s) => s.fact_check || {}));
    const flagged = all.filter((f) => f.status === "flagged").length;
    const pending = all.filter((f) => f.status !== "cleared" && f.status !== "flagged").length;
    const pill = $("#audit-pill");
    pill.hidden = false;
    if (flagged) { pill.className = "pill fail"; pill.textContent = `✕ ${flagged} item${flagged > 1 ? "s" : ""} failed fact check`; }
    else if (pending) { pill.className = "pill pend"; pill.textContent = `● ${pending} awaiting fact check`; }
    else if (!txs.length) { pill.className = "pill ok"; pill.textContent = "✓ Opening balance fact check cleared"; }
    else { pill.className = "pill ok"; pill.textContent = `✓ All ${txs.length} trade${txs.length > 1 ? "s" : ""} fact check cleared`; }
  }

  function renderKpis() {
    const { p, cfg } = state;
    const start = p.starting_cash ?? cfg.starting_cash ?? 10000;
    const total = p.total_value ?? start;
    const ret = p.return_pct ?? 0;
    const unreal = (p.positions || []).reduce((a, x) => a + (x.unrealized_pl || 0), 0);
    const tiles = [
      { label: "Total value", value: usd(total), delta: `<span class="${cls(total - start)}">${usd(total - start)} vs ${usd(start, 0)} start</span>`, hero: true },
      { label: "Return (ROI)", value: `<span class="${cls(ret)}">${pct(ret)}</span>`, delta: "after all fees" },
      { label: "Cash", value: usd(p.cash ?? start), delta: `${(((p.cash ?? start) / total) * 100).toFixed(0)}% of portfolio` },
      { label: "Realized P/L", value: `<span class="${cls(p.realized_pl || 0)}">${usd(p.realized_pl || 0)}</span>`, delta: `unrealized <span class="${cls(unreal)}">${usd(unreal)}</span>` },
      { label: "Fees paid", value: usd(p.fees_paid || 0), delta: `${p.trade_count || 0} trades` },
    ];
    $("#kpis").innerHTML = tiles.map((t) =>
      `<div class="kpi"><div class="label">${t.label}</div><div class="value num${t.hero ? " hero" : ""}">${t.value}</div><div class="delta muted">${t.delta}</div></div>`
    ).join("");
  }

  /* ---------- line chart (hand-rolled SVG, one series + baseline) ---------- */
  function renderChart() {
    const el = $("#chart");
    const start = state.cfg.starting_cash ?? 10000;
    let pts = state.snaps.map((s) => ({ date: s.date, v: s.total_value, s }));
    if (state.range !== "all" && pts.length) {
      const last = new Date(pts[pts.length - 1].date);
      const cut = new Date(last - Number(state.range) * 864e5).toISOString().slice(0, 10);
      pts = pts.filter((p) => p.date >= cut);
    }
    if (pts.length < 2) {
      el.innerHTML = `<div class="empty"><div><div class="num" style="font-size:22px;color:var(--text)">${usd(pts.length ? pts[0].v : start)}</div>
        The line starts once the agents have recorded two daily closes.</div></div>`;
      return;
    }
    const W = el.clientWidth, H = el.clientHeight;
    const m = { t: 12, r: W < 500 ? 56 : 72, b: 26, l: W < 500 ? 48 : 64 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const t0 = Date.parse(pts[0].date), t1 = Date.parse(pts[pts.length - 1].date);
    const vals = pts.map((p) => p.v).concat([start]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.12 || hi * 0.02;
    lo -= pad; hi += pad;
    const ticks = niceTicks(lo, hi, 5);
    lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    const x = (d) => m.l + ((Date.parse(d) - t0) / (t1 - t0 || 1)) * iw;
    const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * ih;

    const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
    const area = `${line}L${x(pts[pts.length - 1].date).toFixed(1)},${(m.t + ih).toFixed(1)}L${m.l},${(m.t + ih).toFixed(1)}Z`;
    const grid = ticks.map((t) => `<line class="gridline" x1="${m.l}" x2="${m.l + iw}" y1="${y(t)}" y2="${y(t)}"/>
      <text class="axis-label" x="${m.l - 8}" y="${y(t) + 4}" text-anchor="end">${compact(t)}</text>`).join("");
    const xt = dateTicks(pts, Math.max(2, Math.floor(iw / 110)));
    const xl = xt.map((p) => `<text class="axis-label" x="${x(p.date)}" y="${H - 6}" text-anchor="middle">${shortDate(p.date)}</text>`).join("");

    const byDate = {};
    state.txs.forEach((t) => (byDate[t.date] = (byDate[t.date] || []).concat(t)));
    const marks = pts.flatMap((p) => (byDate[p.date] || []).map((t, k) => {
      const cx = x(p.date), cy = y(p.v) + (t.action === "BUY" ? 14 : -14) + (k > 1 ? 10 : 0);
      return t.action === "BUY"
        ? `<path class="mk-buy" d="M${cx},${cy - 5}L${cx + 5},${cy + 4}L${cx - 5},${cy + 4}Z"/>`
        : `<path class="mk-sell" d="M${cx},${cy + 5}L${cx + 5},${cy - 4}L${cx - 5},${cy - 4}Z"/>`;
    })).join("");

    const last = pts[pts.length - 1];
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      ${grid}${xl}
      <line class="base" x1="${m.l}" x2="${m.l + iw}" y1="${y(start)}" y2="${y(start)}"/>
      <path class="area" d="${area}"/><path class="line" d="${line}"/>
      ${marks}
      <circle class="dot" cx="${x(last.date)}" cy="${y(last.v)}" r="4.5"/>
      <text class="end-label" x="${x(last.date) + 10}" y="${y(last.v) + 4}">${compact(last.v)}</text>
      <line class="cross" id="cross" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/>
      <circle class="dot" id="hover-dot" r="5" visibility="hidden"/>
      <rect id="hit" x="${m.l}" y="0" width="${iw}" height="${H}" fill="transparent"/>
    </svg>`;

    const tip = $("#tip"), cross = $("#cross"), hd = $("#hover-dot"), svg = el.querySelector("svg");
    const hide = () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); hd.setAttribute("visibility", "hidden"); };
    $("#hit").addEventListener("mousemove", (ev) => {
      const r = svg.getBoundingClientRect();
      const mx = ((ev.clientX - r.left) / r.width) * W;
      let best = pts[0];
      for (const p of pts) if (Math.abs(x(p.date) - mx) < Math.abs(x(best.date) - mx)) best = p;
      const bx = x(best.date), by = y(best.v);
      cross.setAttribute("x1", bx); cross.setAttribute("x2", bx); cross.setAttribute("visibility", "visible");
      hd.setAttribute("cx", bx); hd.setAttribute("cy", by); hd.setAttribute("visibility", "visible");
      const trades = (byDate[best.date] || []).map((t) => `<div class="t-row">${t.action === "BUY" ? "▲ Bought" : "▼ Sold"} ${esc(t.ticker)}</div>`).join("");
      tip.innerHTML = `<div class="t-date">${fmtDate(best.date)}</div><div class="t-val num">${usd(best.v)}</div>
        <div class="t-row"><span class="${cls(best.s.return_pct)}">${pct(best.s.return_pct)}</span> · cash ${usd(best.s.cash, 0)}</div>${trades}`;
      tip.hidden = false;
      const px = r.left + (bx / W) * r.width, py = r.top + (by / H) * r.height;
      const tw = tip.offsetWidth;
      tip.style.left = Math.min(window.innerWidth - tw - 8, Math.max(8, px + 14)) + "px";
      tip.style.top = Math.max(8, py - tip.offsetHeight - 12) + "px";
    });
    $("#hit").addEventListener("mouseleave", hide);
  }

  function niceTicks(lo, hi, n) {
    const span = hi - lo, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((s) => s * mag).find((s) => span / s <= n) || 10 * mag;
    const out = [];
    for (let v = Math.floor(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v * 100) / 100);
    return out;
  }
  function dateTicks(pts, n) {
    if (pts.length <= n) return pts;
    const out = [], step = (pts.length - 1) / (n - 1);
    for (let i = 0; i < n; i++) out.push(pts[Math.round(i * step)]);
    return out;
  }
  const compact = (v) => (Math.abs(v) >= 1000 ? "$" + (v / 1000).toFixed(v >= 100000 ? 0 : 1) + "k" : usd(v, 0));
  const shortDate = (d) => new Date(d + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

  function renderHistoryTable() {
    const rows = state.snaps.slice().reverse().map((s) =>
      `<tr><td>${fmtDate(s.date)}</td><td class="n">${usd(s.total_value)}</td><td class="n ${cls(s.return_pct)}">${pct(s.return_pct)}</td>
       <td class="n">${usd(s.cash)}</td><td class="n">${usd(s.holdings_value)}</td><td>${badge(s.fact_check)}</td></tr>`).join("");
    $("#history-table").innerHTML = `<thead><tr><th>Date</th><th class="n">Total</th><th class="n">Return</th><th class="n">Cash</th><th class="n">Holdings</th><th>Valuation check</th></tr></thead><tbody>${rows}</tbody>`;
  }

  function renderHoldings() {
    const pos = state.p.positions || [];
    const total = state.p.total_value || 1;
    if (!pos.length) { $("#holdings").outerHTML = '<p class="muted" id="holdings">All cash. No open positions yet.</p>'; return; }
    const rows = pos.map((h) =>
      `<tr><td><b>${esc(h.ticker)}</b></td><td class="n">${fmtShares(h.shares)}</td><td class="n">${usd(h.avg_cost)}</td>
       <td class="n">${h.last_price != null ? usd(h.last_price) : "n/a"}</td><td class="n">${usd(h.market_value)}</td>
       <td class="n ${cls(h.unrealized_pl)}">${pct(h.unrealized_pl_pct)}</td><td class="n">${((h.market_value / total) * 100).toFixed(1)}%</td></tr>`).join("");
    $("#holdings").innerHTML = `<thead><tr><th>Ticker</th><th class="n">Shares</th><th class="n">Avg cost</th><th class="n">Last</th><th class="n">Value</th><th class="n">P/L</th><th class="n">Weight</th></tr></thead><tbody>${rows}</tbody>`;
  }
  const fmtShares = (s) => Number(s).toLocaleString("en-US", { maximumFractionDigits: 4 });

  function badge(fc) {
    const s = (fc || {}).status;
    if (s === "cleared") return '<span class="badge ok">✓ Fact check cleared</span>';
    if (s === "flagged") return '<span class="badge fail">✕ Failed fact check</span>';
    return '<span class="badge pend">● Pending fact check</span>';
  }

  function renderTxLog() {
    const el = $("#txlog");
    if (!state.txs.length) { el.innerHTML = '<p class="muted">No trades yet. The research agent trades after each US market close.</p>'; return; }
    const repo = state.cfg.repo_url;
    el.innerHTML = state.txs.slice().reverse().map((t) => {
      const fc = t.fact_check || {};
      const buy = t.action === "BUY";
      const fcBody = fc.status === "cleared"
        ? `Cleared ${esc((fc.checked_at || "").slice(0, 10))}. Independent price ${usd(fc.verified_price, 2)} from ${link(fc.verified_source)} (${fc.price_diff_pct}% from the quote). Checks: ${esc((fc.checks || []).join(", "))}.${fc.notes ? " " + esc(fc.notes) : ""}`
        : fc.status === "flagged" ? `Flagged: ${esc(fc.reason)}` : "Not yet reviewed by the fact-check agent.";
      const journal = repo ? ` · <a href="${esc(repo)}/blob/main/data/journal/${esc(t.date)}.md" target="_blank" rel="noopener">day's journal</a>` : "";
      return `<details class="tx">
        <summary>
          <span class="mono muted">${esc(t.date)}</span>
          <span class="act ${buy ? "buy" : "sell"}">${buy ? "BUY" : "SELL"}</span>
          <span class="tkr">${esc(t.ticker)}</span>
          <span class="amt num">${fmtShares(t.shares)} sh @ ${usd(t.exec_price)} = ${usd(Math.abs(t.cash_delta))}${!buy && t.realized_pl != null ? ` · <span class="${cls(t.realized_pl)}">${usd(t.realized_pl)}</span>` : ""}</span>
          ${badge(fc)}
        </summary>
        <div class="tx-body">
          <div><h3>Why</h3><p>${esc(t.rationale)}</p></div>
          <div class="facts num">
            <div><span>Quoted price</span>${usd(t.quote_price)}</div>
            <div><span>Fill after slippage</span>${usd(t.exec_price, 4)}</div>
            <div><span>Commission + slippage</span>${usd(t.commission)} + ${usd(t.slippage_cost)}</div>
            <div><span>Cash ${buy ? "spent" : "received"}</span>${usd(Math.abs(t.cash_delta))}</div>
            <div><span>Cash after</span>${usd(t.cash_after)}</div>
            ${!buy ? `<div><span>Realized P/L</span><b class="${cls(t.realized_pl)}">${usd(t.realized_pl ?? 0)}</b></div>` : ""}
          </div>
          <div><h3>Price source</h3><p>${link(t.price_source)} at ${esc(t.price_timestamp)}${journal}</p></div>
          <div><h3>Fact check</h3><p>${fcBody}</p></div>
          <div class="muted mono" style="font-size:11.5px">${esc(t.id)} · hash ${esc((t.hash || "").slice(0, 16))}…</div>
        </div>
      </details>`;
    }).join("");
  }

  /* Tiny markdown subset for the analyst's guidance: headings, bullets, bold, links, paragraphs. */
  function markdown(md) {
    const inline = (s) => esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    const out = [];
    let list = false;
    // The card already has a title, so drop the document's own top heading.
    for (const raw of md.replace(/^#\s+.*\n/, "").split("\n")) {
      const line = raw.trimEnd();
      const h = line.match(/^(#{1,3})\s+(.*)/);
      const li = line.match(/^\s*[-*]\s+(.*)/);
      if (!li && list) { out.push("</ul>"); list = false; }
      if (h) out.push(`<h3>${inline(h[2])}</h3>`);
      else if (li) { if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${inline(li[1])}</li>`); }
      else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
    }
    if (list) out.push("</ul>");
    return out.join("");
  }

  init();
})();
