(() => {
  "use strict";

  const state = { days: 30 };

  const fmtInt = (n) => new Intl.NumberFormat("en-US").format(Math.round(n || 0));
  const fmtPct = (n) => `${(n || 0).toFixed(1)}%`;
  const fmtCo2 = (mg) => (mg || 0) >= 1000 ? `${((mg || 0) / 1000).toFixed(2)}g` : `${(mg || 0).toFixed(1)}mg`;
  const fmtUsd = (v) => `$${(v || 0).toFixed((v || 0) < 1 ? 4 : 2)}`;
  const fmtMwh = (v) => `${(v || 0).toFixed(3)} mWh`;

  // ── chart layer (ECharts, Apache-2.0) ───────────────────────────────────
  // Categorical slots in fixed order — never cycled, never reassigned by rank,
  // so a series keeps its colour when the set it belongs to changes. Slot 1 is
  // the product accent. Validated against this dashboard's real card surface
  // (#ffffff): lightness band, chroma floor, adjacent-pair CVD separation and
  // the normal-vision floor all pass. Slots 3/4/5 sit below 3:1 contrast on
  // white, so anything using them ships visible labels or a table view.
  const SERIES = ["#0071e3", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"];
  const INK = { primary: "#1d1d1f", secondary: "#6e6e73", muted: "#86868b" };
  const GRID_LINE = "#e5e5ea";
  const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

  const charts = new Map();

  /** Create-or-reuse an ECharts instance bound to a container id. */
  function chartAt(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    let c = charts.get(id);
    // A chart built while its page was display:none measures 0×0 — re-measure
    // whenever the container has since been shown.
    if (c && (c.getWidth() === 0 || c.getHeight() === 0)) c.resize();
    if (!c) {
      c = echarts.init(el, null, { renderer: "canvas" });
      charts.set(id, c);
    }
    return c;
  }

  window.addEventListener("resize", () => charts.forEach((c) => c.resize()));

  /** Shared tooltip styling — light surface, hairline ring, no arrow chrome. */
  function tooltipStyle(extra) {
    return Object.assign({
      backgroundColor: "#ffffff",
      borderColor: GRID_LINE,
      borderWidth: 1,
      padding: [8, 11],
      textStyle: { color: INK.primary, fontSize: 12, fontFamily: FONT },
      extraCssText: "box-shadow:0 6px 20px rgba(0,0,0,.10);border-radius:10px;",
    }, extra || {});
  }

  /** Vertical accent-to-transparent fill used under line marks. */
  function areaFill(color) {
    return {
      color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: color + "40" },
        { offset: 1, color: color + "00" },
      ]),
    };
  }

  async function fetchJson(url) {
    const res = await fetch(url, { cache: "no-store" });
    if (res.status === 401) {
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
      throw new Error("Unauthorized — redirecting to login");
    }
    if (!res.ok) throw new Error(`${url} -> ${res.status}`);
    return res.json();
  }

  async function postJson(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.status === 401) {
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
      throw new Error("Unauthorized — redirecting to login");
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `${url} -> ${res.status}`);
    return body;
  }

  function daysParam() {
    return state.days ? `?days=${state.days}` : "";
  }

  async function refresh() {
    document.getElementById("refresh-btn").disabled = true;
    try {
      const [summary, records, recentRequests, sessions, decisions, storageStatus] = await Promise.all([
        fetchJson(`/api/summary${daysParam()}`),
        fetchJson(`/api/records${daysParam()}`),
        fetchJson(`/api/records${daysParam()}${daysParam() ? "&" : "?"}limit=50`),
        fetchJson(`/api/sessions${daysParam()}`),
        fetchJson(`/api/decisions?limit=20`),
        fetchJson(`/api/storage-status`),
      ]);
      renderKpis(summary, sessions.sessions || [], records.records || [], storageStatus);
      renderToolChart(summary.by_tool || {});
      renderContentTypeTable(summary.by_content_type || {});
      renderTimeline(records.records || []);
      renderKpiSparklines(records.records || []);
      renderSessions(sessions.sessions || []);
      renderRequests(recentRequests.records || []);
      renderDecisions(decisions);
      document.getElementById("last-updated").textContent =
        "Updated: " + new Date().toLocaleTimeString("en-US");
    } catch (err) {
      document.getElementById("last-updated").textContent = "Load error: " + err.message;
    } finally {
      document.getElementById("refresh-btn").disabled = false;
    }
  }

  function renderKpis(s, sessions, records, storageStatus) {
    document.getElementById("kpi-calls").textContent = fmtInt(s.total_calls);
    document.getElementById("kpi-saved").textContent = fmtInt(s.tokens_saved);
    document.getElementById("kpi-eff").textContent = fmtPct(s.avg_efficiency_pct);
    document.getElementById("kpi-co2").textContent = fmtCo2(s.co2_mg_saved);

    document.getElementById("kpi-sessions").textContent = fmtInt(sessions.length);
    const avgCalls = sessions.length ? sessions.reduce((sum, x) => sum + x.calls, 0) / sessions.length : 0;
    document.getElementById("kpi-avg-calls").textContent = avgCalls.toFixed(1);
    document.getElementById("kpi-tools").textContent = fmtInt(Object.keys(s.by_tool || {}).length);

    const bestSaved = records.reduce((max, r) => Math.max(max, r.tokens_saved || 0), 0);
    document.getElementById("kpi-best-call").textContent = bestSaved ? fmtInt(bestSaved) + " tok" : "–";

    document.getElementById("kpi-latency-avg").textContent = s.avg_latency_ms ? fmtMs(s.avg_latency_ms) : "–";
    document.getElementById("kpi-latency-p95").textContent = s.p95_latency_ms ? fmtMs(s.p95_latency_ms) : "–";
    document.getElementById("kpi-latency-max").textContent = s.max_latency_ms ? fmtMs(s.max_latency_ms) : "–";

    document.getElementById("kpi-cost").textContent = fmtUsd(s.cost_usd_saved);
    document.getElementById("kpi-energy").textContent = fmtMwh(s.energy_mwh_saved);
    document.getElementById("kpi-tokens-before").textContent = fmtInt(s.tokens_before);
    document.getElementById("kpi-decisions").textContent = fmtInt((storageStatus || {}).decisions);
    document.getElementById("kpi-pii-masked").textContent = fmtInt(s.pii_masked_count);
  }

  function fmtMs(ms) {
    return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
  }

  function initTooltips() {
    // KPI card labels are static DOM nodes (only their text content is refreshed on
    // each refresh()), so a single init at page load is enough — no re-init needed.
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => new bootstrap.Tooltip(el));
  }

  function initSidenavToggle() {
    const KEY = "synthelion_sidenav_collapsed";
    const btn = document.getElementById("sidenav-toggle");
    if (!btn) return;
    // Per-viewer UI preference only (does this browser show icons+text or
    // icons only) — never anything the backend needs to know about, so
    // localStorage is the right place for it, not a server-side setting.
    let collapsed = false;
    try { collapsed = localStorage.getItem(KEY) === "1"; } catch { /* ignore */ }
    document.body.classList.toggle("sidenav-collapsed", collapsed);
    btn.addEventListener("click", () => {
      collapsed = !document.body.classList.contains("sidenav-collapsed");
      document.body.classList.toggle("sidenav-collapsed", collapsed);
      try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch { /* ignore */ }
    });

    // Below lg the sidebar slides off-canvas instead of collapsing to icons,
    // so it needs its own toggle in the navbar.
    const mobileBtn = document.getElementById("mobile-sidenav-toggle");
    if (mobileBtn) {
      mobileBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        document.body.classList.toggle("sidenav-mobile-open");
      });
      document.addEventListener("click", (ev) => {
        if (!document.body.classList.contains("sidenav-mobile-open")) return;
        if (ev.target.closest("#sidenav-main") || ev.target.closest("#mobile-sidenav-toggle")) return;
        document.body.classList.remove("sidenav-mobile-open");
      });
    }
  }

  function renderSessions(sessions) {
    const tbody = document.getElementById("table-sessions");
    if (!sessions.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-secondary">No sessions recorded yet.</td></tr>';
      return;
    }
    tbody.innerHTML = sessions
      .map((s) => {
        const shortId = (s.session_id || "").slice(0, 8);
        const first = s.first_ts ? new Date(s.first_ts).toLocaleString("en-US") : "–";
        const last = s.last_ts ? new Date(s.last_ts).toLocaleString("en-US") : "–";
        const tools = (s.tools || []).join(", ") || "–";
        return `<tr>
          <td><code>${escapeHtml(shortId)}</code></td>
          <td>${s.pid ?? "–"}</td>
          <td class="text-end">${fmtInt(s.calls)}</td>
          <td class="text-end">${fmtInt(s.tokens_saved)}</td>
          <td class="small">${escapeHtml(tools)}</td>
          <td class="small text-secondary">${first}</td>
          <td class="small text-secondary">${last}</td>
          <td class="text-end">
            <button type="button" class="btn btn-sm btn-outline-danger py-0 px-2 delete-session-btn" data-session-id="${escapeHtml(s.session_id || "")}">Delete</button>
          </td>
        </tr>`;
      })
      .join("");
  }

  function renderRequests(records) {
    document.getElementById("requests-count").textContent = `${fmtInt(records.length)} shown`;
    const tbody = document.getElementById("table-requests");
    if (!records.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-secondary">No requests recorded yet.</td></tr>';
      return;
    }
    const sorted = [...records].sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));
    tbody.innerHTML = sorted
      .map((r) => {
        const time = r.ts ? new Date(r.ts).toLocaleString("en-US") : "–";
        const eff = r.tokens_before ? ((r.tokens_saved / r.tokens_before) * 100).toFixed(1) + "%" : "–";
        const shortSession = (r.session_id || "").slice(0, 8);
        const latency = r.duration_ms ? fmtMs(r.duration_ms) : "–";
        return `<tr>
          <td class="small text-secondary">${time}</td>
          <td>${escapeHtml(r.tool || "")}</td>
          <td class="small">${escapeHtml(r.content_type || "–")}</td>
          <td class="text-end">${fmtInt(r.tokens_before)}</td>
          <td class="text-end">${fmtInt(r.tokens_after)}</td>
          <td class="text-end">${fmtInt(r.tokens_saved)}</td>
          <td class="text-end">${eff}</td>
          <td class="text-end">${latency}</td>
          <td class="small"><code>${escapeHtml(shortSession)}</code></td>
        </tr>`;
      })
      .join("");
  }

  function renderContentTypeTable(byType) {
    const tbody = document.getElementById("table-content-type");
    const entries = Object.entries(byType).sort((a, b) => b[1] - a[1]);
    if (!entries.length) {
      tbody.innerHTML = '<tr><td colspan="2" class="text-secondary">No data.</td></tr>';
      return;
    }
    tbody.innerHTML = entries
      .map(([type, saved]) => `<tr><td>${escapeHtml(type)}</td><td class="text-end">${fmtInt(saved)}</td></tr>`)
      .join("");
  }

  function renderDecisions(decisions) {
    document.getElementById("decisions-backend").textContent = decisions.backend || "–";
    const list = document.getElementById("decisions-list");
    const items = decisions.decisions || [];
    if (!items.length) {
      list.innerHTML = '<li class="list-group-item text-secondary">No decisions recorded yet.</li>';
      return;
    }
    list.innerHTML = items
      .map((d) => {
        const ts = d.ts ? new Date(d.ts * 1000).toLocaleString("en-US") : "";
        const reason = d.reason ? `<div class="text-secondary small">${escapeHtml(d.reason)}</div>` : "";
        return `<li class="list-group-item">
          <div class="small text-secondary">${ts}</div>
          <div>${escapeHtml(d.text || "")}</div>
          ${reason}
        </li>`;
      })
      .join("");
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // Instances are created once per container id (see chartAt) and updated in
  // place with setOption(..., true). Never echarts.init() the same element
  // twice without dispose() — the old instance keeps its resize listener and
  // both draw onto the same node.

  function renderToolChart(byTool) {
    const entries = Object.entries(byTool).sort((a, b) => b[1] - a[1]).slice(0, 8);
    const c = chartAt("chart-tools");
    if (!c) return;
    // Horizontal bars: tool names are long, and a vertical layout would either
    // clip them or force diagonal labels. Highest value on top.
    const labels = entries.map((e) => e[0]).reverse();
    const values = entries.map((e) => e[1]).reverse();
    c.setOption({
      grid: { left: 4, right: 52, top: 8, bottom: 4, containLabel: true },
      xAxis: { type: "value", show: false },
      yAxis: {
        type: "category", data: labels,
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: INK.secondary, fontFamily: FONT, fontSize: 11 },
      },
      tooltip: tooltipStyle({
        trigger: "item",
        formatter: (p) => `<b>${p.name}</b><br>${fmtInt(p.value)} tokens saved`,
      }),
      series: [{
        type: "bar",
        data: values,
        barWidth: 12,
        itemStyle: { color: SERIES[0], borderRadius: [0, 4, 4, 0] },
        // Direct value labels: slot colours below 3:1 on white need visible
        // labels, and it saves a hover just to read the magnitude.
        label: {
          show: true, position: "right", formatter: (p) => fmtInt(p.value),
          color: INK.secondary, fontFamily: FONT, fontSize: 11,
        },
      }],
    }, true);
  }

  function renderTimeline(records) {
    const empty = document.getElementById("timeline-empty");
    const byDay = new Map();
    for (const r of records) {
      if (!r.ts) continue;
      const day = r.ts.slice(0, 10);
      byDay.set(day, (byDay.get(day) || 0) + (r.tokens_saved || 0));
    }
    const days = Array.from(byDay.keys()).sort().slice(-30);
    if (empty) empty.style.display = days.length ? "none" : "block";
    const values = days.map((d) => byDay.get(d));

    const c = chartAt("chart-timeline");
    if (!c) return;
    c.setOption({
      grid: { left: 8, right: 12, top: 16, bottom: 4, containLabel: true },
      xAxis: {
        type: "category", data: days, boundaryGap: false,
        axisLine: { lineStyle: { color: GRID_LINE } },
        axisTick: { show: false },
        axisLabel: { color: INK.muted, fontFamily: FONT, fontSize: 11, formatter: (v) => v.slice(5) },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: INK.muted, fontFamily: FONT, fontSize: 11, formatter: (v) => fmtInt(v) },
        splitLine: { lineStyle: { color: GRID_LINE, type: "dashed" } },
      },
      tooltip: tooltipStyle({
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: GRID_LINE, width: 1 } },
        formatter: (p) => `<b>${p[0].axisValue}</b><br>${fmtInt(p[0].data)} tokens saved`,
      }),
      series: [{
        type: "line",
        data: values,
        smooth: 0.35,
        showSymbol: false,
        // >=8px hit target on hover even though the resting mark is hidden.
        symbolSize: 9,
        lineStyle: { width: 2, color: SERIES[0] },
        itemStyle: { color: SERIES[0], borderColor: "#fff", borderWidth: 2 },
        areaStyle: areaFill(SERIES[0]),
      }],
    }, true);
  }

  // ── KPI sparklines ──────────────────────────────────────────────────────

  const _ENERGY_MWH_PER_TOKEN = 3.0e-7;   // mirrors ledger.py's constants, so
  const _CO2_MG_PER_MWH = 475.0;          // the daily split sums to the card total
  const _PRICE_PER_TOKEN = 3.0 / 1_000_000;

  /** Bucket raw ledger records into one point per day for every KPI that has
   *  a genuine time series. Metrics without one (ratios, external counters)
   *  are deliberately absent — a card with no real series shows the number
   *  alone rather than a decorative line. */
  function dailySeries(records) {
    const byDay = new Map();
    for (const r of records) {
      if (!r.ts) continue;
      const day = r.ts.slice(0, 10);
      let d = byDay.get(day);
      if (!d) {
        d = { calls: 0, saved: 0, before: 0, pii: 0, best: 0, durs: [], sessions: new Set(), tools: new Set() };
        byDay.set(day, d);
      }
      const saved = r.tokens_saved || 0;
      d.calls += 1;
      d.saved += saved;
      d.before += r.tokens_before || 0;
      d.pii += r.pii_masked_count || 0;
      if (saved > d.best) d.best = saved;
      if (r.duration_ms) d.durs.push(r.duration_ms);
      if (r.session_id) d.sessions.add(r.session_id);
      if (r.tool) d.tools.add(r.tool);
    }
    const days = Array.from(byDay.keys()).sort();
    const pick = (fn) => days.map((k) => fn(byDay.get(k)));
    const pctl = (arr, p) => {
      if (!arr.length) return 0;
      const s = [...arr].sort((a, b) => a - b);
      return s[Math.min(s.length - 1, Math.floor(s.length * p))];
    };
    return {
      days,
      calls: pick((d) => d.calls),
      saved: pick((d) => d.saved),
      before: pick((d) => d.before),
      pii: pick((d) => d.pii),
      best: pick((d) => d.best),
      sessions: pick((d) => d.sessions.size),
      tools: pick((d) => d.tools.size),
      eff: pick((d) => (d.before > 0 ? (d.saved / d.before) * 100 : 0)),
      co2: pick((d) => d.saved * _ENERGY_MWH_PER_TOKEN * _CO2_MG_PER_MWH),
      energy: pick((d) => d.saved * _ENERGY_MWH_PER_TOKEN),
      cost: pick((d) => d.saved * _PRICE_PER_TOKEN),
      lat_avg: pick((d) => (d.durs.length ? d.durs.reduce((a, b) => a + b, 0) / d.durs.length : 0)),
      lat_p95: pick((d) => pctl(d.durs, 0.95)),
      lat_max: pick((d) => (d.durs.length ? Math.max(...d.durs) : 0)),
    };
  }

  /** Percent change of the last day against the mean of the days before it.
   *  Returns null when there isn't enough history to compare honestly. */
  function trendDelta(values) {
    if (values.length < 2) return null;
    const last = values[values.length - 1];
    const prev = values.slice(0, -1);
    const base = prev.reduce((a, b) => a + b, 0) / prev.length;
    if (!base) return null;
    return ((last - base) / base) * 100;
  }

  function renderSparkline(el, days, values, invert) {
    const c = chartAt(el.id);
    if (!c) return;
    // Colour by direction, not by metric: rising is good unless the metric is
    // one where lower is better (latency, tokens sent).
    const delta = trendDelta(values);
    const rising = delta !== null && delta > 0;
    const good = delta === null ? null : (invert ? !rising : rising);
    const color = good === null ? SERIES[0] : (good ? "#1fa668" : "#d70015");
    c.setOption({
      grid: { left: 0, right: 0, top: 6, bottom: 0 },
      xAxis: { type: "category", data: days, show: false, boundaryGap: false },
      yAxis: { type: "value", show: true, min: "dataMin", axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
      tooltip: tooltipStyle({
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: GRID_LINE, width: 1 } },
        formatter: (p) => `<b>${p[0].axisValue}</b><br>${fmtInt(p[0].data)}`,
      }),
      series: [{
        type: "line",
        data: values,
        smooth: 0.35,
        showSymbol: false,
        lineStyle: { width: 2, color },
        areaStyle: areaFill(color),
        // Keep the final point visible as the "you are here" anchor.
        markPoint: {
          symbol: "circle", symbolSize: 7, silent: true,
          itemStyle: { color, borderColor: "#fff", borderWidth: 2 },
          label: { show: false },
          data: [{ coord: [days.length - 1, values[values.length - 1]] }],
        },
      }],
    }, true);
  }

  function renderKpiSparklines(records) {
    const series = dailySeries(records);
    document.querySelectorAll(".kpi-spark[data-metric]").forEach((el) => {
      const values = series[el.dataset.metric];
      if (!values || values.length < 2) { el.style.display = "none"; return; }
      el.style.display = "";
      const invert = el.dataset.invert === "1";
      renderSparkline(el, series.days, values, invert);

      const chip = document.getElementById(el.dataset.deltaFor + "-delta");
      if (!chip) return;
      const delta = trendDelta(values);
      if (delta === null || !isFinite(delta)) { chip.style.display = "none"; return; }
      const rising = delta > 0;
      const good = invert ? !rising : rising;
      chip.style.display = "";
      chip.className = "kpi-delta " + (good ? "up" : "down");
      chip.textContent = `${rising ? "▲" : "▼"} ${Math.abs(delta).toFixed(0)}%`;
      chip.title = "Last day vs the average of the preceding days in range";
    });
  }

  // The range control and Refresh live in the global navbar, but only these
  // pages actually render ledger data filtered by it. Pressing them from
  // anywhere else would silently change a filter with nothing on screen to
  // show for it, so jump to the dashboard and apply it there.
  const RANGE_AWARE_PAGES = new Set(["overview", "charts", "sessions", "requests"]);

  function goToDashboardIfNeeded() {
    const current = pageForPath(window.location.pathname);
    if (!RANGE_AWARE_PAGES.has(current)) navigate("/", true);
  }

  document.querySelectorAll(".range-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".range-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.days = btn.dataset.days ? Number(btn.dataset.days) : null;
      goToDashboardIfNeeded();
      refresh();
    });
  });

  document.getElementById("refresh-btn").addEventListener("click", () => {
    goToDashboardIfNeeded();
    refresh();
  });

  async function loadVersion() {
    try {
      const v = await fetchJson("/api/version");
      document.getElementById("version-badge").textContent = "v" + v.version;
      document.getElementById("version-info-current").textContent = "v" + v.version;
    } catch (err) {
      // non-critical — leave the placeholder badge in place
    }
  }

  // ── settings panel ───────────────────────────────────────────────────────

  function updateSessionBackendFields() {
    const backend = document.getElementById("settings-session-backend").value;
    document.getElementById("settings-redis-url-group").style.display = backend === "redis" ? "" : "none";
    document.getElementById("settings-postgres-dsn-group").style.display = backend === "postgres" ? "" : "none";
  }

  function updateVectorBackendFields() {
    const backend = document.getElementById("settings-vector-backend").value;
    document.getElementById("settings-qdrant-url-group").style.display = backend === "qdrant" ? "" : "none";
  }

  // Material Dashboard's ".input-group-outline" floats the <label> out of the way
  // only after the field's own "focusout" handler adds ".is-filled" to the parent
  // .input-group — which never fires when we set .value from JS (as loadSettings()
  // does), leaving the label visually stacked on top of the value/placeholder.
  // Mirror that same class toggle here right after populating each field.
  function markFilled(inputId) {
    const input = document.getElementById(inputId);
    const group = input && input.closest(".input-group");
    if (group) group.classList.toggle("is-filled", !!input.value);
  }

  async function loadSettings() {
    try {
      const { config } = await fetchJson("/api/config");
      document.getElementById("settings-compression-level").value = config.compression.default_level;
      document.getElementById("settings-wiki-depth").value = String(config.wiki.default_depth);
      document.getElementById("settings-session-backend").value = config.session_store.backend;
      document.getElementById("settings-redis-url").value = config.session_store.redis.url;
      document.getElementById("settings-postgres-dsn").value = config.session_store.postgres.dsn;
      document.getElementById("settings-vector-backend").value = config.vector_store.backend;
      document.getElementById("settings-qdrant-url").value = config.vector_store.qdrant.url;
      document.getElementById("settings-dashboard-host").value = config.dashboard.host;
      document.getElementById("settings-dashboard-port").value = String(config.dashboard.port);
      document.getElementById("settings-dashboard-realtime").value = config.dashboard.realtime;
      document.getElementById("settings-dashboard-ws-port").value = String(config.dashboard.websocket_port);
      ["settings-redis-url", "settings-postgres-dsn", "settings-qdrant-url",
       "settings-dashboard-host", "settings-dashboard-port", "settings-dashboard-ws-port"]
        .forEach(markFilled);
      updateSessionBackendFields();
      updateVectorBackendFields();
    } catch (err) {
      // non-critical — form just keeps its blank/default values
    }
  }

  async function loadStorageStatus() {
    try {
      const s = await fetchJson("/api/storage-status");
      document.getElementById("settings-info-sessions").textContent = fmtInt(s.sessions);
      document.getElementById("settings-info-decisions").textContent = fmtInt(s.decisions);
      document.getElementById("settings-info-records").textContent = fmtInt(s.ledger_records);
      document.getElementById("settings-info-backend").textContent = s.vector_backend;
    } catch (err) {
      // non-critical
    }
  }

  async function saveSettings() {
    const btn = document.getElementById("settings-save-btn");
    const status = document.getElementById("settings-status");
    btn.disabled = true;
    status.textContent = "Saving…";
    status.className = "text-sm text-secondary";
    const payload = {
      compression: { default_level: document.getElementById("settings-compression-level").value },
      wiki: { default_depth: Number(document.getElementById("settings-wiki-depth").value) },
      session_store: {
        backend: document.getElementById("settings-session-backend").value,
        redis: { url: document.getElementById("settings-redis-url").value },
        postgres: { dsn: document.getElementById("settings-postgres-dsn").value },
      },
      vector_store: {
        backend: document.getElementById("settings-vector-backend").value,
        qdrant: { url: document.getElementById("settings-qdrant-url").value },
      },
      dashboard: {
        host: document.getElementById("settings-dashboard-host").value,
        port: Number(document.getElementById("settings-dashboard-port").value),
        realtime: document.getElementById("settings-dashboard-realtime").value,
        websocket_port: Number(document.getElementById("settings-dashboard-ws-port").value),
      },
    };
    try {
      await postJson("/api/config", payload);
      status.textContent = "Saved.";
      status.className = "text-sm text-success";
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    } finally {
      btn.disabled = false;
    }
  }

  document.getElementById("settings-session-backend").addEventListener("change", updateSessionBackendFields);
  document.getElementById("settings-vector-backend").addEventListener("change", updateVectorBackendFields);
  document.getElementById("settings-save-btn").addEventListener("click", saveSettings);

  // ── privacy & security ───────────────────────────────────────────────────

  let privacyWhitelist = [];

  function renderWhitelist() {
    const list = document.getElementById("privacy-whitelist-list");
    if (!privacyWhitelist.length) {
      list.innerHTML = '<li class="list-group-item border-0 px-0 text-sm text-secondary">No whitelisted values yet.</li>';
      return;
    }
    list.innerHTML = privacyWhitelist.map((v, i) => `
      <li class="list-group-item border-0 px-0 d-flex justify-content-between align-items-center text-sm">
        <span>${escapeHtml(v)}</span>
        <button type="button" class="btn btn-sm btn-outline-danger mb-0 py-0 px-2 privacy-whitelist-remove" data-index="${i}">Remove</button>
      </li>`).join("");
    list.querySelectorAll(".privacy-whitelist-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        privacyWhitelist.splice(Number(btn.dataset.index), 1);
        renderWhitelist();
      });
    });
  }

  async function loadPrivacySettings() {
    try {
      const { config } = await fetchJson("/api/config");
      document.getElementById("privacy-enabled").checked = config.privacy.enabled;
      document.getElementById("privacy-auto-masking").checked = config.privacy.auto_masking;
      document.getElementById("privacy-injection-guard").checked = config.privacy.prompt_injection_guard;
      document.getElementById("privacy-transparency-notice").checked = config.privacy.ai_transparency_notice;
      document.getElementById("privacy-use-ml").checked = !!config.privacy.use_ml;
      document.getElementById("privacy-ml-model").value = config.privacy.ml_model || "gliner_small-v2.1";
      document.getElementById("privacy-ml-min-confidence").value = String(config.privacy.ml_min_confidence || 0.6);
      markFilled("privacy-ml-model");
      togglePrivacyMlFields();
      document.getElementById("privacy-block-on-risk").checked = config.privacy.block_on_risk;
      document.getElementById("privacy-block-min-score").value = String(config.privacy.block_min_score || 61);
      document.getElementById("privacy-language").value = config.privacy.language;
      document.getElementById("privacy-transparency-custom").value = config.privacy.transparency_custom_message || "";
      markFilled("privacy-transparency-custom");
      privacyWhitelist = (config.privacy.whitelist || []).slice();
      renderWhitelist();
    } catch (err) {
      // non-critical — form just keeps its blank/default values
    }
  }

  function togglePrivacyMlFields() {
    const enabled = document.getElementById("privacy-use-ml").checked;
    const fields = document.getElementById("privacy-ml-fields");
    if (fields) fields.style.display = enabled ? "" : "none";
  }

  async function savePrivacySettings() {
    const btn = document.getElementById("privacy-save-btn");
    const status = document.getElementById("privacy-save-status");
    btn.disabled = true;
    status.textContent = "Saving…";
    status.className = "text-sm text-secondary";
    const payload = {
      privacy: {
        enabled: document.getElementById("privacy-enabled").checked,
        auto_masking: document.getElementById("privacy-auto-masking").checked,
        prompt_injection_guard: document.getElementById("privacy-injection-guard").checked,
        ai_transparency_notice: document.getElementById("privacy-transparency-notice").checked,
        use_ml: document.getElementById("privacy-use-ml").checked,
        ml_model: document.getElementById("privacy-ml-model").value.trim() || "gliner_small-v2.1",
        ml_min_confidence: Number(document.getElementById("privacy-ml-min-confidence").value) || 0.6,
        block_on_risk: document.getElementById("privacy-block-on-risk").checked,
        block_min_score: Number(document.getElementById("privacy-block-min-score").value),
        language: document.getElementById("privacy-language").value,
        transparency_custom_message: document.getElementById("privacy-transparency-custom").value,
        whitelist: privacyWhitelist,
      },
    };
    try {
      await postJson("/api/config", payload);
      status.textContent = "Saved.";
      status.className = "text-sm text-success";
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    } finally {
      btn.disabled = false;
    }
  }

  document.getElementById("privacy-save-btn").addEventListener("click", savePrivacySettings);

  document.getElementById("privacy-use-ml").addEventListener("change", togglePrivacyMlFields);

  document.getElementById("privacy-whitelist-add-btn").addEventListener("click", () => {
    const input = document.getElementById("privacy-whitelist-input");
    const value = input.value.trim();
    if (value && !privacyWhitelist.includes(value)) {
      privacyWhitelist.push(value);
      renderWhitelist();
    }
    input.value = "";
  });

  document.getElementById("privacy-test-btn").addEventListener("click", async () => {
    const text = document.getElementById("privacy-test-input").value;
    const language = document.getElementById("privacy-language").value;
    try {
      const r = await postJson("/api/privacy-test", { text, language });
      document.getElementById("privacy-test-score").textContent = r.privacy.score;
      document.getElementById("privacy-test-risk").textContent = r.privacy.risk_level;
      document.getElementById("privacy-test-categories").textContent =
        r.privacy.detected_categories.length ? r.privacy.detected_categories.join(", ") : "none";
      document.getElementById("privacy-test-compliance").textContent =
        r.privacy.compliance_flags.length ? r.privacy.compliance_flags.join(", ") : "none";
      document.getElementById("privacy-test-masked").textContent = r.privacy.masked_text || "(no PII detected)";
      document.getElementById("privacy-test-injection-score").textContent = r.prompt_injection.score;
      document.getElementById("privacy-test-injection-risk").textContent = r.prompt_injection.risk_level;
      document.getElementById("privacy-test-injection-categories").textContent =
        r.prompt_injection.detected_categories.length ? r.prompt_injection.detected_categories.join(", ") : "none";
    } catch (err) {
      document.getElementById("privacy-test-risk").textContent = "Error: " + err.message;
    }
  });

  // ── security (WAF & firewall) ────────────────────────────────────────────

  async function loadWafSettings() {
    try {
      const { config } = await fetchJson("/api/config");
      const w = config.waf;
      document.getElementById("waf-enabled").checked = w.enabled;
      document.getElementById("waf-block-mode").checked = w.block_mode;
      document.getElementById("waf-rule-sql").checked = w.rule_sql_injection;
      document.getElementById("waf-rule-xss").checked = w.rule_xss;
      document.getElementById("waf-rule-path").checked = w.rule_path_traversal;
      document.getElementById("waf-rule-cmd").checked = w.rule_command_injection;
      document.getElementById("waf-rule-ua").checked = w.rule_bad_user_agent;
      document.getElementById("waf-rule-scanner").checked = w.rule_scanner_probe;
      document.getElementById("waf-inspect-body").checked = w.inspect_body;
      document.getElementById("waf-skip-authenticated").checked = w.skip_authenticated;
      document.getElementById("waf-autoban-enabled").checked = w.auto_ban_enabled;
      document.getElementById("waf-autoban-threshold").value = w.auto_ban_threshold;
      document.getElementById("waf-autoban-window").value = w.auto_ban_window_minutes;
      document.getElementById("waf-autoban-duration").value = w.auto_ban_duration_minutes;
      document.getElementById("waf-ratelimit-enabled").checked = w.rate_limit_enabled;
      document.getElementById("waf-ratelimit-rpm").value = w.rate_limit_requests_per_minute;
      document.getElementById("waf-ratelimit-ban").value = w.rate_limit_ban_minutes;
      document.getElementById("waf-block-status").value = w.block_status_code;
      document.getElementById("waf-log-retention").value = w.log_retention_days;
      document.getElementById("waf-block-message").value = w.block_message || "";
      document.getElementById("waf-excluded-paths").value = (w.excluded_paths || []).join("\n");
      ["waf-autoban-threshold", "waf-autoban-window", "waf-autoban-duration",
       "waf-ratelimit-rpm", "waf-ratelimit-ban", "waf-block-status", "waf-log-retention",
       "waf-block-message"].forEach(markFilled);
    } catch (err) {
      // non-critical — form just keeps its blank/default values
    }
  }

  async function saveWafSettings() {
    const btn = document.getElementById("waf-save-btn");
    const status = document.getElementById("waf-save-status");
    btn.disabled = true;
    status.textContent = "Saving…";
    status.className = "text-sm text-secondary";
    const payload = {
      waf: {
        enabled: document.getElementById("waf-enabled").checked,
        block_mode: document.getElementById("waf-block-mode").checked,
        rule_sql_injection: document.getElementById("waf-rule-sql").checked,
        rule_xss: document.getElementById("waf-rule-xss").checked,
        rule_path_traversal: document.getElementById("waf-rule-path").checked,
        rule_command_injection: document.getElementById("waf-rule-cmd").checked,
        rule_bad_user_agent: document.getElementById("waf-rule-ua").checked,
        rule_scanner_probe: document.getElementById("waf-rule-scanner").checked,
        inspect_body: document.getElementById("waf-inspect-body").checked,
        skip_authenticated: document.getElementById("waf-skip-authenticated").checked,
        auto_ban_enabled: document.getElementById("waf-autoban-enabled").checked,
        auto_ban_threshold: Number(document.getElementById("waf-autoban-threshold").value),
        auto_ban_window_minutes: Number(document.getElementById("waf-autoban-window").value),
        auto_ban_duration_minutes: Number(document.getElementById("waf-autoban-duration").value),
        rate_limit_enabled: document.getElementById("waf-ratelimit-enabled").checked,
        rate_limit_requests_per_minute: Number(document.getElementById("waf-ratelimit-rpm").value),
        rate_limit_ban_minutes: Number(document.getElementById("waf-ratelimit-ban").value),
        block_status_code: Number(document.getElementById("waf-block-status").value),
        log_retention_days: Number(document.getElementById("waf-log-retention").value),
        block_message: document.getElementById("waf-block-message").value,
        excluded_paths: document.getElementById("waf-excluded-paths").value
          .split("\n").map((s) => s.trim()).filter(Boolean),
      },
    };
    try {
      await postJson("/api/config", payload);
      status.textContent = "Saved.";
      status.className = "text-sm text-success";
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    } finally {
      btn.disabled = false;
    }
  }

  document.getElementById("waf-save-btn").addEventListener("click", saveWafSettings);

  async function loadWafIpRules() {
    const tbody = document.getElementById("waf-ip-rules-body");
    try {
      const { rules } = await fetchJson("/api/waf/ip-rules");
      if (!rules.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-sm text-secondary">No IP rules yet.</td></tr>';
        return;
      }
      tbody.innerHTML = rules.map((r) => `
        <tr>
          <td class="text-sm"><code>${escapeHtml(r.ip)}</code></td>
          <td class="text-sm">${escapeHtml(r.kind)}${r.auto ? ' <span class="badge badge-sm bg-gradient-secondary">auto</span>' : ""}</td>
          <td class="text-sm">${escapeHtml(r.reason || "–")}</td>
          <td class="text-sm">${r.expires_at ? new Date(r.expires_at * 1000).toLocaleString() : "never"}</td>
          <td><button type="button" class="btn btn-sm btn-outline-danger py-0 px-2 waf-ip-remove-btn" data-ip="${escapeHtml(r.ip)}" data-kind="${escapeHtml(r.kind)}">Remove</button></td>
        </tr>`).join("");
      tbody.querySelectorAll(".waf-ip-remove-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await postJson("/api/waf/ip-rules/delete", { ip: btn.dataset.ip, kind: btn.dataset.kind });
          loadWafIpRules();
        });
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-sm text-danger">Error: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  document.getElementById("waf-ip-add-btn").addEventListener("click", async () => {
    const ip = document.getElementById("waf-ip-input").value.trim();
    if (!ip) return;
    const kind = document.getElementById("waf-ip-kind").value;
    const reason = document.getElementById("waf-ip-reason").value.trim() || "Manual";
    try {
      await postJson("/api/waf/ip-rules", { ip, kind, reason });
      document.getElementById("waf-ip-input").value = "";
      document.getElementById("waf-ip-reason").value = "";
      loadWafIpRules();
    } catch (err) {
      // non-critical — the table just doesn't update
    }
  });

  async function loadWafEvents() {
    const tbody = document.getElementById("waf-events-body");
    try {
      const { events } = await fetchJson("/api/waf/events?limit=100");
      if (!events.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-sm text-secondary">No events yet.</td></tr>';
        return;
      }
      tbody.innerHTML = events.map((e) => {
        const cls = e.action === "Blocked" ? "text-danger" : "text-warning";
        return `
        <tr>
          <td class="text-sm">${new Date(e.ts).toLocaleString()}</td>
          <td class="text-sm"><code>${escapeHtml(e.ip || "–")}</code></td>
          <td class="text-sm">${escapeHtml(e.method || "")} ${escapeHtml(e.path || "")}</td>
          <td class="text-sm">${escapeHtml(e.category || "")}</td>
          <td class="text-sm">${escapeHtml(e.rule_name || "")}</td>
          <td class="text-sm">${escapeHtml(e.severity || "")}</td>
          <td class="text-sm ${cls}">${escapeHtml(e.action || "")}</td>
        </tr>`;
      }).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-sm text-danger">Error: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  // ── EnterpriseGuard (outbound DLP firewall) ─────────────────────────────────

  const EG_CATEGORIES = [
    "cloud_credentials", "database_connections", "ftp_credentials",
    "git_credentials", "private_keys", "api_tokens", "dotenv_bulk",
  ];

  async function loadEnterpriseGuardSettings() {
    try {
      const { config } = await fetchJson("/api/config");
      const eg = config.enterprise_guard || {};
      document.getElementById("eg-enabled").checked = eg.enabled !== false;
      document.getElementById("eg-use-defaults").checked = eg.use_default_blocked_paths !== false;
      const cats = eg.content_categories || {};
      EG_CATEGORIES.forEach((c) => {
        const el = document.getElementById("eg-cat-" + c);
        if (el) el.checked = cats[c] !== false;
      });
      document.getElementById("eg-blocked-paths").value = (eg.blocked_paths || []).join("\n");
    } catch (err) {
      // non-critical — form just keeps its blank/default values
    }
  }

  async function saveEnterpriseGuardSettings() {
    const btn = document.getElementById("eg-save-btn");
    const status = document.getElementById("eg-save-status");
    btn.disabled = true;
    status.textContent = "Saving…";
    status.className = "text-sm text-secondary";
    const content_categories = {};
    EG_CATEGORIES.forEach((c) => {
      const el = document.getElementById("eg-cat-" + c);
      if (el) content_categories[c] = el.checked;
    });
    const payload = {
      enterprise_guard: {
        enabled: document.getElementById("eg-enabled").checked,
        use_default_blocked_paths: document.getElementById("eg-use-defaults").checked,
        content_categories,
        blocked_paths: document.getElementById("eg-blocked-paths").value
          .split("\n").map((s) => s.trim()).filter(Boolean),
      },
    };
    try {
      await postJson("/api/config", payload);
      status.textContent = "Saved.";
      status.className = "text-sm text-success";
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    } finally {
      btn.disabled = false;
    }
  }

  document.getElementById("eg-save-btn").addEventListener("click", saveEnterpriseGuardSettings);

  document.getElementById("eg-test-btn").addEventListener("click", async () => {
    const resultDiv = document.getElementById("eg-test-result");
    resultDiv.innerHTML = '<span class="text-sm text-secondary">Checking…</span>';
    try {
      const r = await postJson("/api/enterprise-guard-test", {
        text: document.getElementById("eg-test-text").value,
        path: document.getElementById("eg-test-path").value,
      });
      const rows = [];
      if (r.text_result) rows.push(["Text", r.text_result]);
      if (r.path_result) rows.push(["Path", r.path_result]);
      if (!rows.length) {
        resultDiv.innerHTML = '<span class="text-sm text-secondary">Enter text and/or a path above, then Test.</span>';
        return;
      }
      resultDiv.innerHTML = rows.map(([label, res]) => {
        const cls = res.blocked ? "text-danger" : "text-success";
        const verdict = res.blocked ? "BLOCKED" : "Allowed";
        const detail = res.blocked ? ` — ${escapeHtml(res.category || "")} / ${escapeHtml(res.rule_name || "")}` : "";
        return `<div class="text-sm ${cls}"><strong>${label}: ${verdict}</strong>${detail}</div>`;
      }).join("");
    } catch (err) {
      resultDiv.innerHTML = `<span class="text-sm text-danger">Error: ${escapeHtml(err.message)}</span>`;
    }
  });

  async function loadEnterpriseGuardEvents() {
    const tbody = document.getElementById("eg-events-body");
    try {
      const { events } = await fetchJson("/api/enterprise-guard/events?limit=100");
      if (!events.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-sm text-secondary">No blocks yet.</td></tr>';
        return;
      }
      tbody.innerHTML = events.map((e) => `
        <tr>
          <td class="text-sm">${new Date(e.timestamp * 1000).toLocaleString()}</td>
          <td class="text-sm">${escapeHtml(e.source || "")}</td>
          <td class="text-sm">${escapeHtml(e.category || "")}</td>
          <td class="text-sm">${escapeHtml(e.rule_name || "")}</td>
        </tr>`).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="4" class="text-sm text-danger">Error: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  async function loadEnterpriseGuardClients() {
    const tbody = document.getElementById("eg-clients-body");
    try {
      const { clients } = await fetchJson("/api/enterprise-guard/clients");
      if (!clients.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-sm text-secondary">No clients registered.</td></tr>';
        return;
      }
      tbody.innerHTML = clients.map((c) => `
        <tr>
          <td class="text-sm">${escapeHtml(c.label || "(no label)")}${c.auto_discovered ? ' <span class="badge badge-sm bg-gradient-secondary">auto-discovered</span>' : ""}</td>
          <td class="text-sm"><code>${escapeHtml(c.ip || "–")}</code></td>
          <td class="text-sm"><code>${escapeHtml(c.mac || "–")}</code></td>
          <td class="text-sm">${c.blocked_paths.length} path(s)</td>
          <td>
            <div class="form-check form-switch mb-0">
              <input class="form-check-input eg-client-enable-toggle" type="checkbox" role="switch" data-id="${escapeHtml(c.id)}" ${c.enabled ? "checked" : ""}>
            </div>
          </td>
          <td><button type="button" class="btn btn-sm btn-outline-danger py-0 px-2 eg-client-remove-btn" data-id="${escapeHtml(c.id)}">Remove</button></td>
        </tr>`).join("");
      tbody.querySelectorAll(".eg-client-enable-toggle").forEach((el) => {
        el.addEventListener("change", async () => {
          await postJson("/api/enterprise-guard/clients/update", { id: el.dataset.id, enabled: el.checked });
        });
      });
      tbody.querySelectorAll(".eg-client-remove-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await postJson("/api/enterprise-guard/clients/delete", { id: btn.dataset.id });
          loadEnterpriseGuardClients();
        });
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-sm text-danger">Error: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  document.getElementById("eg-client-add-btn").addEventListener("click", async () => {
    const btn = document.getElementById("eg-client-add-btn");
    btn.disabled = true;
    try {
      await postJson("/api/enterprise-guard/clients", {
        label: document.getElementById("eg-client-label").value,
        ip: document.getElementById("eg-client-ip").value,
        mac: document.getElementById("eg-client-mac").value,
        blocked_paths: document.getElementById("eg-client-paths").value
          .split("\n").map((s) => s.trim()).filter(Boolean),
        enabled: true,
      });
      document.getElementById("eg-client-label").value = "";
      document.getElementById("eg-client-ip").value = "";
      document.getElementById("eg-client-mac").value = "";
      document.getElementById("eg-client-paths").value = "";
      loadEnterpriseGuardClients();
    } finally {
      btn.disabled = false;
    }
  });

  // ── proxy ─────────────────────────────────────────────────────────────────

  let _proxyRoutes = [];
  let _proxyFallbacks = [];

  async function loadProxyStatus() {
    try {
      const s = await fetchJson("/api/proxy/status");
      const badge = document.getElementById("proxy-state-badge");
      badge.textContent = s.running ? "Running" : "Stopped";
      badge.className = "badge " + (s.running ? "bg-gradient-success" : "bg-gradient-secondary");
      document.getElementById("proxy-address").textContent = `${s.host}:${s.port}`;
      document.getElementById("proxy-pid").textContent = s.pid || "–";
    } catch (err) {
      document.getElementById("proxy-control-status").textContent = "Error: " + err.message;
    }
  }

  document.getElementById("proxy-start-btn").addEventListener("click", async () => {
    const status = document.getElementById("proxy-control-status");
    status.textContent = "Starting…";
    status.className = "text-sm text-secondary";
    try {
      const r = await postJson("/api/proxy/start", {});
      status.textContent = r.status === "already_running" ? "Already running." : "Started.";
      status.className = "text-sm text-success";
      setTimeout(loadProxyStatus, 800);
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    }
  });

  document.getElementById("proxy-stop-btn").addEventListener("click", async () => {
    const status = document.getElementById("proxy-control-status");
    status.textContent = "Stopping…";
    status.className = "text-sm text-secondary";
    try {
      const r = await postJson("/api/proxy/stop", {});
      status.textContent = r.status === "not_running" ? "Was not running." : "Stopped.";
      status.className = "text-sm text-success";
      setTimeout(loadProxyStatus, 500);
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    }
  });

  async function loadProxyConfig() {
    try {
      const { config } = await fetchJson("/api/config");
      const p = config.proxy || {};
      document.getElementById("proxy-enabled").checked = !!p.enabled;
      document.getElementById("proxy-host").value = p.host || "127.0.0.1";
      document.getElementById("proxy-port").value = p.port || 8788;
      document.getElementById("proxy-anthropic-upstream").value = p.anthropic_upstream || "";
      document.getElementById("proxy-openai-upstream").value = p.openai_upstream || "";
      document.getElementById("proxy-gemini-upstream").value = p.gemini_upstream || "";
      document.getElementById("proxy-default-upstream").value = p.default_upstream || "";
      document.getElementById("proxy-cb-enabled").checked = p.circuit_breaker_enabled !== false;
      document.getElementById("proxy-cb-threshold").value = p.circuit_breaker_threshold ?? 3;
      document.getElementById("proxy-cb-window").value = p.circuit_breaker_window_seconds ?? 60;
      document.getElementById("proxy-cb-cooldown").value = p.circuit_breaker_cooldown_seconds ?? 30;
      document.getElementById("proxy-rh-enabled").checked = p.rolling_history_enabled !== false;
      document.getElementById("proxy-rh-threshold").value = p.rolling_history_threshold ?? 6;
      document.getElementById("proxy-ccr-enabled").checked = !!p.ccr_enabled;
      document.getElementById("proxy-ccr-min-saved").value = p.ccr_min_tokens_saved ?? 15;
      document.getElementById("proxy-ccr-ttl").value = p.ccr_ttl_seconds ?? 3600;
      document.getElementById("proxy-cache-enabled").checked = !!p.response_cache_enabled;
      document.getElementById("proxy-cache-ttl").value = p.response_cache_ttl_seconds ?? 120;
      document.getElementById("proxy-cache-max").value = p.response_cache_max_entries ?? 200;
      document.getElementById("proxy-budget").value = p.daily_budget_usd ?? 0;
      document.getElementById("proxy-output-shaping").checked = !!p.output_shaping_enabled;
      _proxyRoutes = (p.custom_routes || []).slice();
      _proxyFallbacks = (p.fallback_upstreams || []).slice();
      renderProxyRoutes();
      renderProxyFallbacks();
    } catch (err) {
      document.getElementById("proxy-upstreams-status").textContent = "Error: " + err.message;
    }
  }

  function renderProxyRoutes() {
    const tbody = document.getElementById("proxy-routes-table");
    if (!_proxyRoutes.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-secondary text-sm">No custom routes — built-in Anthropic/OpenAI/Gemini routing applies.</td></tr>';
      return;
    }
    tbody.innerHTML = _proxyRoutes.map((r, i) => `
      <tr>
        <td class="text-sm">${escapeHtml(r.label || "")}</td>
        <td class="text-sm"><code>${escapeHtml(r.path_prefix || "")}</code></td>
        <td class="text-sm">${escapeHtml(r.upstream || "")}</td>
        <td><button type="button" class="btn btn-link text-danger p-0 m-0 proxy-route-remove" data-idx="${i}">Remove</button></td>
      </tr>`).join("");
    tbody.querySelectorAll(".proxy-route-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        _proxyRoutes.splice(Number(btn.dataset.idx), 1);
        renderProxyRoutes();
        saveProxyRoutes();
      });
    });
  }

  function renderProxyFallbacks() {
    const el = document.getElementById("proxy-fallback-list");
    if (!_proxyFallbacks.length) {
      el.innerHTML = '<span class="text-secondary text-sm">No backup upstreams configured.</span>';
      return;
    }
    el.innerHTML = _proxyFallbacks.map((url, i) => `
      <span class="badge bg-gradient-secondary me-1 mb-1">
        ${escapeHtml(url)} <a href="#" class="text-white proxy-fallback-remove" data-idx="${i}" style="text-decoration:none">&times;</a>
      </span>`).join("");
    el.querySelectorAll(".proxy-fallback-remove").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        _proxyFallbacks.splice(Number(a.dataset.idx), 1);
        renderProxyFallbacks();
        saveProxyFallbacks();
      });
    });
  }

  async function saveProxyRoutes() {
    try {
      await postJson("/api/config", { proxy: { custom_routes: _proxyRoutes } });
    } catch (err) {
      document.getElementById("proxy-upstreams-status").textContent = "Error saving routes: " + err.message;
    }
  }

  async function saveProxyFallbacks() {
    try {
      await postJson("/api/config", { proxy: { fallback_upstreams: _proxyFallbacks } });
    } catch (err) {
      document.getElementById("proxy-reliability-status").textContent = "Error saving fallbacks: " + err.message;
    }
  }

  document.getElementById("proxy-save-upstreams-btn").addEventListener("click", async () => {
    const status = document.getElementById("proxy-upstreams-status");
    try {
      await postJson("/api/config", {
        proxy: {
          enabled: document.getElementById("proxy-enabled").checked,
          host: document.getElementById("proxy-host").value.trim(),
          port: parseInt(document.getElementById("proxy-port").value, 10) || 8788,
          anthropic_upstream: document.getElementById("proxy-anthropic-upstream").value.trim(),
          openai_upstream: document.getElementById("proxy-openai-upstream").value.trim(),
          gemini_upstream: document.getElementById("proxy-gemini-upstream").value.trim(),
          default_upstream: document.getElementById("proxy-default-upstream").value.trim(),
        },
      });
      status.textContent = "Saved. Restart the proxy for changes to take effect.";
      status.className = "text-sm text-success";
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    }
  });

  document.getElementById("proxy-save-reliability-btn").addEventListener("click", async () => {
    const status = document.getElementById("proxy-reliability-status");
    try {
      await postJson("/api/config", {
        proxy: {
          circuit_breaker_enabled: document.getElementById("proxy-cb-enabled").checked,
          circuit_breaker_threshold: parseInt(document.getElementById("proxy-cb-threshold").value, 10) || 3,
          circuit_breaker_window_seconds: parseInt(document.getElementById("proxy-cb-window").value, 10) || 60,
          circuit_breaker_cooldown_seconds: parseInt(document.getElementById("proxy-cb-cooldown").value, 10) || 30,
        },
      });
      status.textContent = "Saved. Restart the proxy for changes to take effect.";
      status.className = "text-sm text-success";
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    }
  });

  document.getElementById("proxy-save-advanced-btn").addEventListener("click", async () => {
    const status = document.getElementById("proxy-advanced-status");
    try {
      await postJson("/api/config", {
        proxy: {
          rolling_history_enabled: document.getElementById("proxy-rh-enabled").checked,
          rolling_history_threshold: parseInt(document.getElementById("proxy-rh-threshold").value, 10) || 6,
          ccr_enabled: document.getElementById("proxy-ccr-enabled").checked,
          ccr_min_tokens_saved: parseInt(document.getElementById("proxy-ccr-min-saved").value, 10) || 15,
          ccr_ttl_seconds: parseInt(document.getElementById("proxy-ccr-ttl").value, 10) || 3600,
          response_cache_enabled: document.getElementById("proxy-cache-enabled").checked,
          response_cache_ttl_seconds: parseInt(document.getElementById("proxy-cache-ttl").value, 10) || 120,
          response_cache_max_entries: parseInt(document.getElementById("proxy-cache-max").value, 10) || 200,
          daily_budget_usd: parseFloat(document.getElementById("proxy-budget").value) || 0,
          output_shaping_enabled: document.getElementById("proxy-output-shaping").checked,
        },
      });
      status.textContent = "Saved. Restart the proxy for changes to take effect.";
      status.className = "text-sm text-success";
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    }
  });

  document.getElementById("proxy-route-add-btn").addEventListener("click", () => {
    const label = document.getElementById("proxy-route-label").value.trim();
    const prefix = document.getElementById("proxy-route-prefix").value.trim();
    const upstream = document.getElementById("proxy-route-upstream").value.trim();
    if (!prefix || !upstream) return;
    _proxyRoutes.push({ label, path_prefix: prefix, upstream });
    document.getElementById("proxy-route-label").value = "";
    document.getElementById("proxy-route-prefix").value = "/";
    document.getElementById("proxy-route-upstream").value = "";
    renderProxyRoutes();
    saveProxyRoutes();
  });

  document.getElementById("proxy-fallback-add-btn").addEventListener("click", () => {
    const input = document.getElementById("proxy-fallback-input");
    const url = input.value.trim();
    if (!url) return;
    if (_proxyFallbacks.length >= 10) {
      document.getElementById("proxy-reliability-status").textContent = "Maximum of 10 backup upstreams.";
      return;
    }
    _proxyFallbacks.push(url);
    input.value = "";
    renderProxyFallbacks();
    saveProxyFallbacks();
  });

  document.getElementById("proxy-load-providers-btn").addEventListener("click", async () => {
    const select = document.getElementById("proxy-provider-picker");
    select.innerHTML = '<option value="">Loading…</option>';
    try {
      const { providers, error } = await fetchJson("/api/proxy/providers");
      if (error) {
        select.innerHTML = `<option value="">Error: ${escapeHtml(error)}</option>`;
        return;
      }
      select.innerHTML = '<option value="">Pick a provider…</option>' +
        providers.map((p) => `<option value="${escapeHtml(p.api)}" data-name="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join("");
    } catch (err) {
      select.innerHTML = `<option value="">Error: ${escapeHtml(err.message)}</option>`;
    }
  });

  document.getElementById("proxy-provider-picker").addEventListener("change", (ev) => {
    const opt = ev.target.selectedOptions[0];
    if (!opt || !opt.value) return;
    document.getElementById("proxy-route-upstream").value = opt.value;
    document.getElementById("proxy-route-label").value = opt.dataset.name || "";
  });

  async function loadProxyLogs() {
    const tbody = document.getElementById("proxy-logs-table");
    try {
      const { logs } = await fetchJson("/api/proxy/logs?limit=100");
      if (!logs.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-sm text-secondary">No proxy calls yet.</td></tr>';
        return;
      }
      tbody.innerHTML = logs.map((l) => {
        let resultCls = "text-success", resultText = "OK";
        if (l.blocked) { resultCls = "text-warning"; resultText = "Blocked (privacy)"; }
        else if (!l.responded) { resultCls = "text-danger"; resultText = "Failed"; }
        const saved = l.tokens_before > 0 ? `${Math.round((1 - l.tokens_after / l.tokens_before) * 100)}%` : "–";
        return `
        <tr>
          <td class="text-sm">${new Date(l.ts).toLocaleTimeString()}</td>
          <td class="text-sm">${escapeHtml(l.method || "")}</td>
          <td class="text-sm">${escapeHtml(l.path || "")}</td>
          <td class="text-sm">${escapeHtml((l.upstream || "").replace(/^https?:\/\//, ""))}</td>
          <td class="text-sm text-end">${l.status_code ?? "–"}</td>
          <td class="text-sm text-end">${Math.round(l.duration_ms)}ms</td>
          <td class="text-sm text-end">${saved}</td>
          <td class="text-sm ${resultCls}">${resultText}</td>
        </tr>`;
      }).join("");
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-sm text-danger">Error: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  // ── doctor / version / upgrade ───────────────────────────────────────────

  function doctorIcon(status) {
    if (status === "ok") return '<span class="text-success">✓</span>';
    if (status === "warn") return '<span class="text-warning">!</span>';
    return '<span class="text-danger">✗</span>';
  }

  document.getElementById("doctor-run-btn").addEventListener("click", async () => {
    const list = document.getElementById("doctor-list");
    list.innerHTML = '<li class="list-group-item border-0 px-0 text-sm text-secondary">Running…</li>';
    try {
      const { checks } = await fetchJson("/api/doctor");
      list.innerHTML = checks
        .map((c) => `<li class="list-group-item border-0 px-0 text-sm">${doctorIcon(c.status)} <strong>${escapeHtml(c.check)}</strong> — ${escapeHtml(c.detail)}</li>`)
        .join("");
    } catch (err) {
      list.innerHTML = `<li class="list-group-item border-0 px-0 text-sm text-danger">Error: ${escapeHtml(err.message)}</li>`;
    }
  });

  document.getElementById("version-check-btn").addEventListener("click", async () => {
    const status = document.getElementById("version-status");
    const upgradeBtn = document.getElementById("version-upgrade-btn");
    status.textContent = "Checking PyPI…";
    status.className = "text-sm text-secondary";
    try {
      const r = await fetchJson("/api/version-check");
      if (r.error) {
        status.textContent = "Could not reach PyPI: " + r.error;
        status.className = "text-sm text-danger";
        return;
      }
      if (r.update_available) {
        status.textContent = `Update available: v${r.current} → v${r.latest}`;
        status.className = "text-sm text-warning";
        upgradeBtn.style.display = "";
      } else {
        status.textContent = `Up to date (v${r.current}).`;
        status.className = "text-sm text-success";
        upgradeBtn.style.display = "none";
      }
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    }
  });

  document.getElementById("version-upgrade-btn").addEventListener("click", async () => {
    const status = document.getElementById("version-status");
    const btn = document.getElementById("version-upgrade-btn");
    const restartBtn = document.getElementById("version-restart-btn");
    btn.disabled = true;
    status.textContent = "Upgrading — this can take a minute…";
    status.className = "text-sm text-secondary";
    try {
      const r = await postJson("/api/upgrade", {});
      if (r.success) {
        status.textContent = "Upgraded. The MCP server needs a manual restart (by your agent/host) — the dashboard can restart itself below.";
        status.className = "text-sm text-success";
        btn.style.display = "none";
        restartBtn.style.display = "";
      } else {
        status.textContent = "Upgrade failed — see server log.";
        status.className = "text-sm text-danger";
        btn.disabled = false;
      }
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
      btn.disabled = false;
    }
  });

  document.getElementById("version-restart-btn").addEventListener("click", async () => {
    const status = document.getElementById("version-status");
    const btn = document.getElementById("version-restart-btn");
    btn.disabled = true;
    status.textContent = "Restarting dashboard…";
    status.className = "text-sm text-secondary";
    try {
      await postJson("/api/restart", {});
    } catch {
      // The connection drops as soon as the process re-execs — expected, not an error.
    }
    let attempts = 0;
    const poll = setInterval(async () => {
      attempts += 1;
      try {
        const res = await fetch(window.location.origin + "/login", { method: "GET" });
        if (res.ok || res.status === 200) {
          clearInterval(poll);
          window.location.reload();
        }
      } catch {
        // still restarting — server not accepting connections yet
      }
      if (attempts > 30) {
        clearInterval(poll);
        status.textContent = "Restart is taking longer than expected — reload the page manually.";
        status.className = "text-sm text-warning";
      }
    }, 1000);
  });

  // ── sessions cleanup ─────────────────────────────────────────────────────

  document.querySelectorAll(".prune-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const status = document.getElementById("prune-status");
      status.textContent = "Working…";
      status.className = "text-sm text-secondary";
      try {
        const r = await postJson("/api/sessions/prune", { days: Number(btn.dataset.days) });
        status.textContent = `Removed ${r.removed} record(s) older than ${r.days} days.`;
        status.className = "text-sm text-success";
        refresh();
        loadStorageStatus();
      } catch (err) {
        status.textContent = "Error: " + err.message;
        status.className = "text-sm text-danger";
      }
    });
  });

  document.getElementById("table-sessions").addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".delete-session-btn");
    if (!btn) return;
    const sessionId = btn.dataset.sessionId;
    if (!sessionId) return;
    btn.disabled = true;
    try {
      await postJson("/api/sessions/delete", { session_id: sessionId });
      refresh();
      loadStorageStatus();
    } catch (err) {
      btn.disabled = false;
      alert("Delete failed: " + err.message);
    }
  });

  document.querySelectorAll(".prune-decisions-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const status = document.getElementById("prune-decisions-status");
      status.textContent = "Working…";
      status.className = "text-sm text-secondary";
      try {
        const r = await postJson("/api/decisions/prune", { days: Number(btn.dataset.days) });
        status.textContent = `Removed ${r.removed} decision(s) older than ${r.days} days.`;
        status.className = "text-sm text-success";
        refresh();
        loadStorageStatus();
      } catch (err) {
        status.textContent = "Error: " + err.message;
        status.className = "text-sm text-danger";
      }
    });
  });

  // ── profile / account ────────────────────────────────────────────────────

  function setProfileUsername(username) {
    document.getElementById("profile-heading-username").textContent = username;
    document.getElementById("profile-info-username").textContent = username;
    // Navbar user chip + menu mirror the same account, so a username change
    // on the Profile page is reflected in the header without a reload.
    const name = username || "—";
    const initials = (username || "?").trim().slice(0, 2);
    const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    set("user-chip-name", name);
    set("user-menu-name", name);
    set("user-avatar", initials);
  }

  async function loadProfile() {
    try {
      const [account, version, { config }] = await Promise.all([
        fetchJson("/api/account"),
        fetchJson("/api/version"),
        fetchJson("/api/config"),
      ]);
      setProfileUsername(account.username);
      document.getElementById("profile-info-version").textContent = "v" + version.version;
      document.getElementById("profile-info-session-store").textContent = config.session_store.backend;
      document.getElementById("profile-info-vector-store").textContent = config.vector_store.backend;
    } catch (err) {
      // non-critical
    }
  }

  document.getElementById("profile-save-btn").addEventListener("click", async () => {
    const status = document.getElementById("profile-status");
    const currentPassword = document.getElementById("profile-current-password").value;
    const newUsername = document.getElementById("profile-new-username").value;
    const newPassword = document.getElementById("profile-new-password").value;
    status.textContent = "Saving…";
    status.className = "text-sm text-secondary";
    try {
      const r = await postJson("/api/account", {
        current_password: currentPassword,
        new_username: newUsername,
        new_password: newPassword,
      });
      status.textContent = "Credentials updated.";
      status.className = "text-sm text-success";
      setProfileUsername(r.username);
      document.getElementById("profile-current-password").value = "";
      document.getElementById("profile-new-username").value = "";
      document.getElementById("profile-new-password").value = "";
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    }
  });

  // ── notifications ────────────────────────────────────────────────────────

  // Distinct icon shape per level, so severity survives greyscale, colour-vision
  // differences and forced-colors mode instead of resting on the hue alone.
  const NOTIF_ICONS = {
    error: '<path d="M12 8v5"/><circle cx="12" cy="16.5" r=".6" fill="currentColor"/><path d="M10.3 3.9 2.8 17a2 2 0 0 0 1.7 3h15a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    warning: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="7.5" x2="12" y2="13"/><circle cx="12" cy="16.3" r=".6" fill="currentColor"/>',
    info: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16.5"/><circle cx="12" cy="8" r=".6" fill="currentColor"/>',
  };

  function notificationItemHtml(n) {
    const level = NOTIF_ICONS[n.level] ? n.level : "info";
    const action = n.link
      ? `<a class="notif-action" href="${escapeHtml(n.link)}" data-page-link>Review →</a>`
      : "";
    return `<li class="notif-item" data-level="${level}">
      <span class="notif-icon">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${NOTIF_ICONS[level]}</svg>
      </span>
      <div class="notif-body">
        <p class="notif-title">${escapeHtml(n.title)}</p>
        <p class="notif-message">${escapeHtml(n.message)}</p>
      </div>
      ${action}
    </li>`;
  }

  async function loadNotifications() {
    try {
      const { notifications } = await fetchJson("/api/notifications");
      const badge = document.getElementById("notif-badge");
      if (notifications.length) {
        badge.style.display = "";
        badge.textContent = String(notifications.length);
      } else {
        badge.style.display = "none";
      }

      const items = notifications.map(notificationItemHtml).join("");

      // Navbar bell: only the three most recent, with a link to the full page.
      const dropdown = document.getElementById("notif-dropdown");
      dropdown.innerHTML = notifications.length
        ? notifications.slice(0, 3).map(notificationItemHtml).join("") +
          (notifications.length > 3
            ? `<li class="px-2 pt-2"><a class="notif-action" href="/notifications" data-page-link>See all ${notifications.length} →</a></li>`
            : "")
        : '<li class="notif-empty py-3">Nothing to report.</li>';

      const pageList = document.getElementById("notif-page-list");
      pageList.innerHTML = items ||
        '<li class="notif-empty">No signals — configuration, guards and subscriptions all look healthy.</li>';

      for (const level of ["error", "warning", "info"]) {
        const el = document.getElementById("notif-count-" + level);
        if (el) el.textContent = String(notifications.filter((n) => (n.level || "info") === level).length);
      }

      const profileList = document.getElementById("profile-notifications-list");
      if (profileList) {
        profileList.innerHTML = items ||
          '<li class="notif-empty">No notifications — everything looks fine.</li>';
      }
    } catch (err) {
      // non-critical
    }
  }



  // ── compliance ──────────────────────────────────────────────────────────

  const COMPLIANCE_DOCS = [
    { kind: "technical-file", name: "Technical file", article: "EU AI Act Art. 11 / Annex IV" },
    { kind: "dpia", name: "DPIA", article: "GDPR Art. 35" },
    { kind: "fria", name: "FRIA", article: "EU AI Act Art. 27" },
    { kind: "executive-report", name: "Executive report", article: "Operational, last 30 days" },
  ];

  function renderComplianceDocs() {
    const list = document.getElementById("comp-docs");
    if (!list) return;
    list.innerHTML = COMPLIANCE_DOCS.map((d) => `
      <li class="doc-row">
        <div class="doc-main">
          <div class="doc-name">${escapeHtml(d.name)}</div>
          <div class="doc-article">${escapeHtml(d.article)}</div>
        </div>
        <div class="doc-actions">
          <a class="btn btn-sm btn-primary" href="/api/compliance/report?kind=${d.kind}&format=pdf">PDF</a>
          <a class="btn btn-sm btn-outline-secondary" href="/api/compliance/report?kind=${d.kind}&format=json">JSON</a>
        </div>
      </li>`).join("");
  }

  function renderComplianceRules(rules) {
    const tbody = document.getElementById("comp-rules-tbody");
    if (!tbody) return;
    tbody.innerHTML = rules.map((r) => `
      <tr>
        <td>
          <div class="text-sm fw-semibold">${escapeHtml(r.title)}</div>
          <div class="text-xs text-muted">${escapeHtml(r.id)} · ${escapeHtml(r.category)}</div>
        </td>
        <td><span class="risk-pill" data-risk="${escapeHtml(r.risk_level)}">${escapeHtml(r.risk_level)}</span></td>
        <td><span class="action-pill" data-action="${escapeHtml(r.action)}">${escapeHtml(r.action)}</span></td>
        <td><span class="text-sm text-muted">${escapeHtml(r.scope)}</span></td>
        <td class="text-end">
          <div class="form-check form-switch d-inline-block m-0">
            <input class="form-check-input comp-rule-toggle" type="checkbox"
                   data-rule="${escapeHtml(r.id)}" ${r.enabled ? "checked" : ""}>
          </div>
        </td>
      </tr>`).join("");

    tbody.querySelectorAll(".comp-rule-toggle").forEach((input) => {
      input.addEventListener("change", async () => {
        input.disabled = true;
        try {
          await fetchPostJson("/api/compliance/rules/update", {
            rule_id: input.dataset.rule, enabled: input.checked,
          });
          // Reload rather than patch in place: switching a control off changes
          // the traceability matrix and the warning panel too.
          await loadCompliance();
        } finally {
          input.disabled = false;
        }
      });
    });
  }

  function renderComplianceMatrix(rows) {
    const tbody = document.getElementById("comp-matrix-tbody");
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="notif-empty">No controls configured.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map((r) => `
      <tr>
        <td><span class="text-sm">${escapeHtml(r.module)}</span></td>
        <td><span class="text-sm text-muted">${escapeHtml(r.framework)}</span></td>
        <td><span class="text-sm">${escapeHtml(r.article)}</span></td>
        <td><span class="text-xs text-muted">${escapeHtml(r.obligation)}</span></td>
        <td><span class="badge ${r.enabled ? "bg-success" : "bg-danger"}">${r.enabled ? "yes" : "NO"}</span></td>
      </tr>`).join("");
  }

  async function loadCompliance() {
    try {
      const [status, matrix] = await Promise.all([
        fetchJson("/api/compliance/status"),
        fetchJson("/api/compliance/matrix"),
      ]);

      const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      const enabled = status.rules.filter((r) => r.enabled).length;
      const stats = status.statistics || {};
      const chain = status.audit_chain || {};

      set("comp-kpi-status", status.status);
      set("comp-kpi-fallback", `Fallback: ${status.fallback}`);
      set("comp-kpi-rules", `${enabled}/${status.rules.length}`);
      set("comp-kpi-rules-foot", `${status.rules.length - enabled} disabled`);
      set("comp-kpi-calls", fmtInt(stats.total_calls || 0));
      set("comp-kpi-violations", `${stats.violation_rate_pct || 0}% with findings`);
      set("comp-kpi-audit", chain.valid ? "Intact" : "Broken");
      set("comp-kpi-audit-note", chain.valid
        ? `${chain.entries || 0} entries, no tampering`
        : (chain.reason || "chain verification failed"));

      const sel = document.getElementById("comp-engine-status");
      if (sel) sel.value = status.status;

      // Controls that are on while their guard is off: the case where the
      // technical file would claim a control that inspects nothing.
      const broken = status.ineffective_controls || [];
      const row = document.getElementById("comp-warning-row");
      const list = document.getElementById("comp-warnings");
      if (row && list) {
        row.style.display = broken.length ? "" : "none";
        list.innerHTML = broken.map((h) => notificationItemHtml({
          level: "error",
          title: `${h.title} — backend ${h.backend_state}`,
          message: `${h.rule_id}: ${h.note || "the guard behind this control is not operational."}`,
        })).join("");
      }
      const badge = document.getElementById("compliance-nav-badge");
      if (badge) {
        badge.style.display = broken.length ? "" : "none";
        badge.textContent = String(broken.length);
      }

      renderComplianceRules(status.rules);
      renderComplianceMatrix(matrix.matrix || []);
      renderComplianceDocs();
    } catch (err) { /* non-critical */ }
  }

  function initCompliance() {
    const sel = document.getElementById("comp-engine-status");
    if (!sel) return;
    sel.addEventListener("change", async () => {
      sel.disabled = true;
      try {
        await fetchPostJson("/api/compliance/engine/update", { status: sel.value });
        await loadCompliance();
      } finally {
        sel.disabled = false;
      }
    });
  }

  // ── live monitor ────────────────────────────────────────────────────────
  //
  // Polled, not pushed: the dashboard is a stdlib HTTP server with no
  // websocket layer, and every source behind /api/live is an append-only file
  // the poll has to read anyway. The `since` cursor means each poll only
  // carries what happened after the previous one.

  const live = { cursor: 0, paused: false, filter: "", timer: null, rows: [], backoff: 0 };
  // 5s, not 1-2s: the WAF in front of this dashboard rate-limits inbound
  // requests, and with waf.skip_authenticated turned off an aggressive poll
  // gets the operator's own IP auto-banned from their own panel. The counters
  // describe a 5-minute window anyway, so a faster poll buys nothing.
  const LIVE_POLL_MS = 5000;
  const LIVE_MAX_BACKOFF_MS = 60000;
  const LIVE_MAX_ROWS = 200;
  const SECURITY_KINDS = new Set(["firewall", "waf", "policy"]);

  function liveRowHtml(ev, isNew) {
    const time = new Date(ev.ts * 1000).toLocaleTimeString("en-US", { hour12: false });
    return `<li class="live-row${isNew ? " is-new" : ""}" data-kind="${escapeHtml(ev.kind)}">
      <span class="live-time">${time}</span>
      <span class="live-kind" data-kind="${escapeHtml(ev.kind)}">${escapeHtml(ev.kind)}</span>
      <div class="live-main">
        <div class="live-title">${escapeHtml(ev.title || "")}</div>
        <div class="live-detail">${escapeHtml(ev.detail || "")}</div>
      </div>
    </li>`;
  }

  function renderLiveStream() {
    const list = document.getElementById("live-stream");
    if (!list) return;
    const shown = live.rows.filter((r) => {
      if (!live.filter) return true;
      if (live.filter === "security") return SECURITY_KINDS.has(r.ev.kind);
      return r.ev.kind === live.filter;
    });
    list.innerHTML = shown.length
      ? shown.map((r) => liveRowHtml(r.ev, r.isNew)).join("")
      : '<li class="notif-empty">Nothing matching this filter yet.</li>';
    // "New" is a one-render highlight; clear it so a filter switch doesn't
    // re-flash rows the operator has already seen.
    live.rows.forEach((r) => { r.isNew = false; });
  }

  function livePageVisible() {
    const section = document.querySelector('section[data-page="live"]');
    return !!section && section.style.display !== "none" && !document.hidden;
  }

  async function pollLive() {
    // Don't poll a page nobody is looking at, or a backgrounded tab: those
    // requests still count against the WAF's inbound rate limit while showing
    // the operator nothing.
    if (live.paused || !livePageVisible()) return;
    try {
      const data = await fetchJson(`/api/live?since=${live.cursor}`);
      const status = document.getElementById("live-status");
      if (data.events && data.events.length) {
        // Server returns newest-first; unshift oldest-first so ordering holds.
        data.events.slice().reverse().forEach((ev) => live.rows.unshift({ ev, isNew: true }));
        live.rows = live.rows.slice(0, LIVE_MAX_ROWS);
        renderLiveStream();
      }
      live.cursor = data.now || live.cursor;
      const c = data.counters || {};
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = fmtInt(v || 0); };
      set("live-requests", c.requests);
      set("live-compressions", c.compressions);
      set("live-blocked", c.blocked);
      set("live-gated", c.gated);
      if (status) status.textContent = `Live · updated ${new Date().toLocaleTimeString("en-US")}`;
      live.backoff = 0;
    } catch (err) {
      // Back off instead of hammering. A failing poll is often the WAF rate
      // limiter, and retrying at full speed just extends the ban that caused
      // the failure in the first place.
      live.backoff = live.backoff ? Math.min(live.backoff * 2, LIVE_MAX_BACKOFF_MS) : LIVE_POLL_MS * 2;
      const status = document.getElementById("live-status");
      if (status) {
        status.textContent = `Disconnected — retrying in ${Math.round(live.backoff / 1000)}s`;
      }
      clearInterval(live.timer);
      live.timer = setTimeout(function resume() {
        pollLive();
        live.timer = setInterval(pollLive, LIVE_POLL_MS);
      }, live.backoff);
    }
  }

  function initLiveMonitor() {
    const pauseBtn = document.getElementById("live-pause");
    if (!pauseBtn) return;

    pauseBtn.addEventListener("click", () => {
      live.paused = !live.paused;
      pauseBtn.textContent = live.paused ? "Resume" : "Pause";
      document.querySelectorAll(".live-dot").forEach((d) => d.classList.toggle("paused", live.paused));
      const status = document.getElementById("live-status");
      if (status && live.paused) status.textContent = "Paused — the feed keeps accumulating on the server.";
    });

    document.querySelectorAll(".live-filter").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".live-filter").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        live.filter = btn.dataset.kind || "";
        renderLiveStream();
      });
    });

    // Start the cursor at "now" so the first poll shows live activity rather
    // than replaying the whole day's history into the stream.
    live.cursor = Date.now() / 1000;
    pollLive();
    live.timer = setInterval(pollLive, LIVE_POLL_MS);
  }

  // ── cluster (master/slave) ───────────────────────────────────────────────

  let clusterTokenVisible = false;
  let lastClusterStatus = null;

  function renderClusterNodes(nodes) {
    const tbody = document.getElementById("cluster-nodes-table");
    if (!nodes.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-secondary">No nodes joined yet.</td></tr>';
      return;
    }
    const now = Date.now() / 1000;
    tbody.innerHTML = nodes
      .map((n) => {
        const stats = n.stats || {};
        const age = now - (n.last_seen || 0);
        const status = age < 90 ? '<span class="text-success">up</span>' : '<span class="text-warning">stale</span>';
        return `<tr>
          <td>${escapeHtml(n.node_id)}</td>
          <td class="small text-secondary">${escapeHtml(n.url || "–")}</td>
          <td class="text-end">${stats.total_calls != null ? fmtInt(stats.total_calls) : "–"}</td>
          <td class="text-end">${stats.tokens_saved != null ? fmtInt(stats.tokens_saved) : "–"}</td>
          <td class="small">${escapeHtml(stats.version || "–")}</td>
          <td>${status}</td>
        </tr>`;
      })
      .join("");
  }

  function renderClusterStatus(status) {
    lastClusterStatus = status;
    document.getElementById("cluster-role-badge").textContent = status.role;
    document.getElementById("cluster-node-id").textContent = status.node_id || "–";
    document.getElementById("cluster-master-url").textContent = status.role === "slave" ? (status.master_url || "–") : "–";

    const tokenGroup = document.getElementById("cluster-token-group");
    const becomeMasterBtn = document.getElementById("cluster-become-master-btn");
    const rotateBtn = document.getElementById("cluster-rotate-token-btn");
    const leaveBtn = document.getElementById("cluster-leave-btn");
    const joinRow = document.getElementById("cluster-join-row");
    const nodesRow = document.getElementById("cluster-nodes-row");

    if (status.role === "standalone") {
      tokenGroup.style.display = "none";
      becomeMasterBtn.style.display = "";
      rotateBtn.style.display = "none";
      leaveBtn.style.display = "none";
      joinRow.style.display = "";
      nodesRow.style.display = "none";
    } else if (status.role === "master") {
      tokenGroup.style.display = "";
      becomeMasterBtn.style.display = "none";
      rotateBtn.style.display = "";
      leaveBtn.style.display = "";
      joinRow.style.display = "none";
      nodesRow.style.display = "";
      renderClusterNodes(status.nodes || []);
    } else {
      // slave
      tokenGroup.style.display = "";
      becomeMasterBtn.style.display = "none";
      rotateBtn.style.display = "none";
      leaveBtn.style.display = "";
      joinRow.style.display = "none";
      nodesRow.style.display = "none";
    }

    updateClusterTokenDisplay();
  }

  function updateClusterTokenDisplay() {
    const el = document.getElementById("cluster-token-value");
    const toggle = document.getElementById("cluster-token-toggle");
    if (!lastClusterStatus || !lastClusterStatus.node_token) {
      el.textContent = "–";
      return;
    }
    el.textContent = clusterTokenVisible ? lastClusterStatus.node_token : "•".repeat(16);
    toggle.textContent = clusterTokenVisible ? "Hide" : "Show";
  }

  async function loadClusterStatus() {
    try {
      const status = await fetchJson("/api/cluster/status");
      renderClusterStatus(status);
    } catch (err) {
      // non-critical
    }
  }

  function clusterActionStatus(msg, cls) {
    const el = document.getElementById("cluster-action-status");
    el.textContent = msg;
    el.className = "text-sm mt-2 " + cls;
  }

  async function runClusterAction(payload) {
    try {
      const r = await postJson("/api/cluster/action", payload);
      clusterActionStatus("Done.", "text-success");
      renderClusterStatus(r.cluster);
      return r;
    } catch (err) {
      clusterActionStatus("Error: " + err.message, "text-danger");
      throw err;
    }
  }

  document.getElementById("cluster-become-master-btn").addEventListener("click", () => {
    runClusterAction({ action: "become_master" });
  });

  document.getElementById("cluster-rotate-token-btn").addEventListener("click", () => {
    if (confirm("Rotating the token disconnects every currently-joined node until they re-join with the new token. Continue?")) {
      runClusterAction({ action: "rotate_token" });
    }
  });

  document.getElementById("cluster-leave-btn").addEventListener("click", () => {
    if (confirm("Leave the cluster and return to standalone mode?")) {
      runClusterAction({ action: "leave" });
    }
  });

  document.getElementById("cluster-join-btn").addEventListener("click", () => {
    const masterUrl = document.getElementById("cluster-join-master-url").value.trim();
    const token = document.getElementById("cluster-join-token").value;
    if (!masterUrl || !token) {
      clusterActionStatus("Master URL and token are both required.", "text-danger");
      return;
    }
    runClusterAction({ action: "join", master_url: masterUrl, token });
  });

  document.getElementById("cluster-token-toggle").addEventListener("click", () => {
    clusterTokenVisible = !clusterTokenVisible;
    updateClusterTokenDisplay();
  });

  document.getElementById("cluster-token-copy").addEventListener("click", () => {
    if (lastClusterStatus && lastClusterStatus.node_token) {
      navigator.clipboard.writeText(lastClusterStatus.node_token).catch(() => {});
    }
  });

  // ── Enterprise load functions ──────────────────────────────────────────────

  // Provider marks: simple geometric glyphs keyed by provider id. Deliberately
  // NOT the vendors' real logos — those are trademarked assets we would have to
  // redistribute inside the wheel. Colour is the provider's recognisable hue;
  // the name always travels with the glyph, so nothing depends on colour alone.
  const PROVIDER_MARKS = {
    openai:     { color: "#10a37f", path: '<circle cx="12" cy="12" r="7"/><path d="M12 5v14M5.5 8.5l13 7M18.5 8.5l-13 7"/>' },
    anthropic:  { color: "#d97757", path: '<path d="M7 19 12 5l5 14"/><path d="M9 14h6"/>' },
    gemini:     { color: "#4285f4", path: '<path d="M12 3c.6 4.6 3.8 7.8 8.4 8.4-4.6.6-7.8 3.8-8.4 8.4-.6-4.6-3.8-7.8-8.4-8.4C8.2 10.8 11.4 7.6 12 3z"/>' },
    groq:       { color: "#f55036", path: '<circle cx="12" cy="12" r="7"/><path d="M12 12h4v3"/>' },
    mistral:    { color: "#fa520f", path: '<rect x="4" y="5" width="4" height="14"/><rect x="10" y="5" width="4" height="9"/><rect x="16" y="5" width="4" height="14"/>' },
    deepseek:   { color: "#4d6bfe", path: '<path d="M4 13c3.5-4 8-5.5 12-4.5"/><circle cx="17.5" cy="8" r="1.3"/><path d="M4 13c1 4 5 6 9 5"/>' },
    xai:        { color: "#1d1d1f", path: '<path d="M5 5l14 14M19 5L5 19"/>' },
    together:   { color: "#0f6fff", path: '<circle cx="9" cy="12" r="5"/><circle cx="15" cy="12" r="5"/>' },
    openrouter: { color: "#6566f1", path: '<path d="M3 12h6"/><path d="M15 6h6M15 18h6"/><path d="M9 12l6-6M9 12l6 6"/>' },
  };

  function providerMarkHtml(provider, small) {
    const key = (provider || "").toLowerCase();
    const p = PROVIDER_MARKS[key];
    const cls = "provider-mark" + (small ? " sm" : "");
    const size = small ? 12 : 15;
    if (!p) {
      const letter = (provider || "?").charAt(0).toUpperCase();
      return `<span class="${cls}" title="${escapeHtml(provider || "unknown")}" style="font-size:${small ? 10 : 12}px;font-weight:600">${escapeHtml(letter)}</span>`;
    }
    return `<span class="${cls}" title="${escapeHtml(provider)}" style="color:${p.color};border-color:${p.color}33;background:${p.color}14"><svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${p.path}</svg></span>`;
  }

  /** Fraction of a subscription's allowance already consumed, or null when the
   *  plan has no ceiling set (an unlimited plan cannot be "80% used"). */
  function subUsage(sub) {
    if (sub.type === "consumo" && sub.max_tokens) {
      return (sub.current_tokens_used || 0) / sub.max_tokens;
    }
    if (sub.type === "mensile" && sub.max_monthly_cost_usd) {
      return (sub.current_month_cost_usd || 0) / sub.max_monthly_cost_usd;
    }
    return null;
  }

  function quotaHtml(sub) {
    const used = subUsage(sub);
    if (used === null) return '<span class="quota-label">No limit set</span>';
    const pct = Math.min(100, used * 100);
    const cls = used >= 1 ? "over" : used >= 0.8 ? "warn" : "";
    const detail = sub.type === "consumo"
      ? `${fmtInt(sub.current_tokens_used)} / ${fmtInt(sub.max_tokens)} tok`
      : `${fmtUsd(sub.current_month_cost_usd)} / ${fmtUsd(sub.max_monthly_cost_usd)}`;
    return `<div class="quota"><div class="quota-track"><div class="quota-fill ${cls}" style="width:${pct.toFixed(1)}%"></div></div><span class="quota-label">${detail} · ${pct.toFixed(0)}%</span></div>`;
  }

  function subChipHtml(sub, providerByKey) {
    const provider = providerByKey[sub.provider_key_id] || "";
    const label = sub.type === "consumo" ? "metered" : "monthly";
    const used = subUsage(sub);
    const pct = used === null ? "" : ` ${Math.min(999, Math.round(used * 100))}%`;
    const title = `${provider} · ${sub.status}${sub.model ? " · " + sub.model : ""}`;
    return `<span class="sub-chip ${escapeHtml(sub.status)}" title="${escapeHtml(title)}">${providerMarkHtml(provider, true)}${label}${pct}</span>`;
  }

  const ROW_ICONS = {
    plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    rotate: '<path d="M21 12a9 9 0 1 1-3-6.7"/><polyline points="21 4 21 10 15 10"/>',
    pause: '<rect x="8" y="6" width="3" height="12"/><rect x="14" y="6" width="3" height="12"/>',
    play: '<polygon points="7 5 19 12 7 19"/>',
    link: '<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>',
    trash: '<polyline points="4 7 20 7"/><path d="M9 7V5h6v2"/><path d="M6 7l1 13h10l1-13"/>',
  };
  const rowIconBtn = (icon, cls, attrs, title) =>
    `<button class="row-action ${cls}" title="${title}" ${attrs}><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ROW_ICONS[icon]}</svg></button>`;

  async function loadEnterpriseUsers() {
    try {
      const [{ users }, { provider_keys }, dash] = await Promise.all([
        fetchJson("/api/enterprise/users"),
        fetchJson("/api/enterprise/provider-keys"),
        fetchJson("/api/enterprise/dashboard"),
      ]);
      const subs = dash.subscriptions || [];
      const providerByKey = {};
      (provider_keys || []).forEach((k) => { providerByKey[k.pk_id] = k.provider; });

      renderEnterpriseKpis(users, subs, dash.aggregate || {});
      renderSubscriptionAlerts(users, subs, providerByKey);
      renderEnterpriseUsersTable(users, subs, providerByKey);
      renderConsumption(users, subs, dash.by_user || []);
      renderTopModels(dash.by_model || []);
    } catch (err) { /* non-critical */ }
  }

  function renderEnterpriseKpis(users, subs, agg) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set("ent-kpi-users", fmtInt(users.length));
    set("ent-kpi-users-foot", `${users.filter((u) => u.status === "active").length} active`);
    set("ent-kpi-subs", fmtInt(subs.filter((s) => s.status === "active").length));
    set("ent-kpi-subs-foot", `${subs.length} total · ${subs.filter((s) => s.status === "exhausted").length} exhausted`);
    set("ent-kpi-tokens", fmtInt(agg.total_tokens_used || 0));
    set("ent-kpi-cost", fmtUsd(agg.total_cost_usd || 0));
  }

  function renderSubscriptionAlerts(users, subs, providerByKey) {
    const nameOf = (uid) => (users.find((u) => u.user_id === uid) || {}).label || uid;
    const alerts = [];
    for (const s of subs) {
      const provider = providerByKey[s.provider_key_id] || "provider";
      if (s.status === "exhausted") {
        alerts.push({ level: "error", title: `${nameOf(s.user_id)} — ${provider} plan exhausted`,
          message: "Requests through the proxy are refused until the plan is topped up or reset." });
        continue;
      }
      if (s.status === "suspended") {
        alerts.push({ level: "warning", title: `${nameOf(s.user_id)} — ${provider} plan suspended`,
          message: "Reactivate it from the Subscriptions page to restore access." });
        continue;
      }
      const used = subUsage(s);
      if (used !== null && used >= 0.8) {
        alerts.push({ level: "warning", title: `${nameOf(s.user_id)} — ${provider} at ${Math.round(used * 100)}% of quota`,
          message: s.type === "consumo" ? "Token allowance nearly spent." : "Monthly cost limit nearly reached." });
      }
    }
    const row = document.getElementById("ent-alerts-row");
    const list = document.getElementById("ent-alerts");
    if (!row || !list) return;
    row.style.display = alerts.length ? "" : "none";
    list.innerHTML = alerts.map(notificationItemHtml).join("");
  }

  function renderEnterpriseUsersTable(users, subs, providerByKey) {
    const tbody = document.getElementById("enterprise-users-tbody");
    if (!tbody) return;
    if (!users.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="notif-empty">No users yet — add the first one.</td></tr>';
      return;
    }
    tbody.innerHTML = users.map((u) => {
      const mine = subs.filter((s) => s.user_id === u.user_id);
      const providers = (u.synthelion_providers || []).length;
      const enabled = u.status === "active";
      return `<tr>
        <td><span class="text-sm fw-semibold">${escapeHtml(u.label || u.user_id)}</span></td>
        <td><span class="badge bg-secondary">${escapeHtml(u.role)}</span></td>
        <td><span class="badge ${enabled ? "bg-success" : "bg-secondary"}">${escapeHtml(u.status)}</span></td>
        <td><code style="font-size:.7rem">${escapeHtml(u.virtual_token.slice(0, 14))}…</code></td>
        <td><span class="text-sm text-muted">${providers} key(s)</span></td>
        <td>${mine.length ? mine.map((s) => subChipHtml(s, providerByKey)).join("") : '<span class="text-sm text-muted">No plan</span>'}</td>
        <td class="text-end" style="white-space:nowrap">
          ${rowIconBtn("plus", "ent-user-add-sub", `data-uid="${u.user_id}"`, "Activate a subscription")}
          ${rowIconBtn("link", "ent-user-assign", `data-uid="${u.user_id}"`, "Assign a provider key")}
          ${rowIconBtn(enabled ? "pause" : "play", "ent-user-toggle", `data-uid="${u.user_id}" data-enabled="${enabled ? 1 : 0}"`, enabled ? "Disable user" : "Enable user")}
          ${rowIconBtn("rotate", "enterprise-rotate-token", `data-uid="${u.user_id}"`, "Rotate virtual token")}
          ${rowIconBtn("trash", "enterprise-delete-user danger", `data-uid="${u.user_id}"`, "Delete user")}
        </td>
      </tr>`;
    }).join("");

    const on = (cls, fn) => tbody.querySelectorAll("." + cls).forEach((b) => b.addEventListener("click", () => fn(b)));
    on("enterprise-rotate-token", async (b) => {
      await fetchPostJson("/api/enterprise/users/rotate-token", { user_id: b.dataset.uid });
      loadEnterpriseUsers();
    });
    on("enterprise-delete-user", async (b) => {
      if (!confirm("Delete this user? Their subscriptions and provider assignments go too.")) return;
      await fetchPostJson("/api/enterprise/users/delete", { user_id: b.dataset.uid });
      loadEnterpriseUsers();
    });
    on("ent-user-toggle", async (b) => {
      await fetchPostJson("/api/enterprise/users/update", {
        user_id: b.dataset.uid, enabled: b.dataset.enabled === "1" ? 0 : 1,
      });
      loadEnterpriseUsers();
    });
    on("ent-user-assign", (b) => openAssignProvider(b.dataset.uid));
    on("ent-user-add-sub", (b) => openAddSubscription(b.dataset.uid));
  }

  function renderConsumption(users, subs, byUser) {
    const tbody = document.getElementById("ent-consumption-tbody");
    if (!tbody) return;
    const usage = new Map(byUser.map((r) => [r.user_id, r]));
    // Users with no activity still belong in the table — "nothing used yet" is
    // a real answer, and dropping them would hide a user who cannot connect.
    const rows = users
      .map((u) => ({ user: u, usage: usage.get(u.user_id) || {}, subs: subs.filter((s) => s.user_id === u.user_id) }))
      .sort((a, b) => (b.usage.total_tokens_used || 0) - (a.usage.total_tokens_used || 0));
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="notif-empty">No users yet.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map((row) => {
      // Show the tightest plan — the one that will cut the user off first.
      const withQuota = row.subs.map((s) => ({ s, u: subUsage(s) })).filter((x) => x.u !== null);
      withQuota.sort((a, b) => b.u - a.u);
      const quota = withQuota.length ? quotaHtml(withQuota[0].s) : '<span class="quota-label">No limit set</span>';
      return `<tr>
        <td><span class="text-sm fw-semibold">${escapeHtml(row.user.label || row.user.user_id)}</span></td>
        <td><span class="text-sm">${fmtInt(row.usage.total_requests || 0)}</span></td>
        <td><span class="text-sm">${fmtInt(row.usage.total_tokens_used || 0)}</span></td>
        <td><span class="text-sm">${fmtUsd(row.usage.total_cost_usd || 0)}</span></td>
        <td>${quota}</td>
      </tr>`;
    }).join("");
  }

  function renderTopModels(byModel) {
    const list = document.getElementById("ent-top-models");
    if (!list) return;
    if (!byModel.length) {
      list.innerHTML = '<li class="notif-empty">No activity recorded yet.</li>';
      return;
    }
    const max = Math.max.apply(null, byModel.map((m) => m.requests || 0)) || 1;
    list.innerHTML = byModel.slice(0, 10).map((m) => `<li class="model-row">${providerMarkHtml(m.provider)}<div class="model-main"><div class="model-name">${escapeHtml(m.model)}</div><div class="model-sub">${escapeHtml(m.provider || "unknown")} · ${fmtInt(m.tokens_used || 0)} tok · ${fmtUsd(m.cost_usd || 0)}</div><div class="model-bar" style="width:${Math.max(2, (m.requests / max) * 100)}%"></div></div><span class="model-count">${fmtInt(m.requests)}</span></li>`).join("");
  }

  /** Open the existing Add-subscription modal pre-scoped to one user. */
  async function openAddSubscription(userId) {
    const { provider_keys } = await fetchJson("/api/enterprise/provider-keys");
    if (!provider_keys.length) {
      alert("Add a provider key first — a subscription needs a key to bill against.");
      return;
    }
    const { users } = await fetchJson("/api/enterprise/users");
    const userSel = document.getElementById("add-sub-user");
    const pkSel = document.getElementById("add-sub-pk");
    userSel.innerHTML = users.map((u) => `<option value="${u.user_id}"${u.user_id === userId ? " selected" : ""}>${escapeHtml(u.label || u.user_id)}</option>`).join("");
    pkSel.innerHTML = provider_keys.map((k) => `<option value="${k.pk_id}">${escapeHtml(k.provider)} — ${escapeHtml(k.label || k.pk_id)}</option>`).join("");
    bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-add-sub")).show();
  }

  async function openAssignProvider(userId) {
    const { provider_keys } = await fetchJson("/api/enterprise/provider-keys");
    if (!provider_keys.length) {
      alert("No provider keys yet — add one on the Provider Keys page.");
      return;
    }
    const choice = prompt(
      "Assign which provider key?\n\n" +
      provider_keys.map((k, i) => `${i + 1}. ${k.provider} — ${k.label || k.pk_id}`).join("\n"),
      "1");
    const idx = parseInt(choice, 10) - 1;
    if (isNaN(idx) || !provider_keys[idx]) return;
    await fetchPostJson("/api/enterprise/users/assign-provider", {
      user_id: userId, provider_key_id: provider_keys[idx].pk_id,
    });
    loadEnterpriseUsers();
  }

  async function loadEnterpriseProviderKeys() {
    try {
      const { provider_keys } = await fetchJson("/api/enterprise/provider-keys");
      const tbody = document.getElementById("enterprise-pk-tbody");
      if (!tbody) return;
      tbody.innerHTML = provider_keys.map(k => `
        <tr>
          <td><span class="text-xs">${k.provider}</span></td>
          <td><span class="text-xs">${k.label || ""}</span></td>
          <td><span class="text-xs text-muted">${k.upstream_url || "(default)"}</span></td>
          <td>
            <button class="btn btn-link text-danger p-0 enterprise-delete-pk" data-pkid="${k.pk_id}" title="Delete key">✕</button>
          </td>
        </tr>
      `).join("");
      tbody.querySelectorAll(".enterprise-delete-pk").forEach(btn => btn.addEventListener("click", async () => {
        if (!confirm("Delete this provider key?")) return;
        await fetchPostJson("/api/enterprise/provider-keys/delete", { pk_id: btn.dataset.pkid });
        loadEnterpriseProviderKeys();
      }));
    } catch (err) { /* non-critical */ }
  }

  async function loadEnterpriseSubscriptions() {
    try {
      const { subscriptions } = await fetchJson("/api/enterprise/subscriptions");
      const tbody = document.getElementById("enterprise-subs-tbody");
      tbody.innerHTML = subscriptions.map(s => `
        <tr>
          <td><span class="text-xs">${s.user_id.slice(0,12)}…</span></td>
          <td><span class="text-xs">${s.provider_label || s.provider_key_id}</span></td>
          <td><span class="badge badge-sm bg-gradient-info">${s.type}</span></td>
          <td><span class="text-xs">${s.model || "all"}</span></td>
          <td><span class="text-xs">${(s.tokens_used||0).toLocaleString()}</span></td>
          <td><span class="text-xs">$${(s.cost_usd||0).toFixed(4)}</span></td>
          <td><span class="badge badge-sm ${s.status === "active" ? "bg-gradient-success" : "bg-gradient-secondary"}">${s.status}</span></td>
          <td>
            ${s.status === "active"
              ? `<button class="btn btn-link text-warning p-0 enterprise-suspend-sub" data-sid="${s.sub_id}" title="Suspend">⏸</button>`
              : `<button class="btn btn-link text-success p-0 enterprise-reactivate-sub" data-sid="${s.sub_id}" title="Reactivate">▶</button>`}
          </td>
        </tr>
      `).join("");
      tbody.querySelectorAll(".enterprise-suspend-sub").forEach(btn => btn.addEventListener("click", async () => {
        await fetchPostJson("/api/enterprise/subscriptions/suspend", { sub_id: btn.dataset.sid });
        loadEnterpriseSubscriptions();
      }));
      tbody.querySelectorAll(".enterprise-reactivate-sub").forEach(btn => btn.addEventListener("click", async () => {
        await fetchPostJson("/api/enterprise/subscriptions/reactivate", { sub_id: btn.dataset.sid });
        loadEnterpriseSubscriptions();
      }));
    } catch (err) { /* non-critical */ }
  }

  async function loadEnterpriseActivity() {
    try {
      const userId = document.getElementById("enterprise-activity-filter").value;
      const qs = userId ? `?user_id=${userId}` : "";
      const { activity } = await fetchJson(`/api/enterprise/activity${qs}`);
      const tbody = document.getElementById("enterprise-activity-tbody");
      tbody.innerHTML = activity.map(a => `
        <tr>
          <td><span class="text-xs">${new Date(a.timestamp).toLocaleString()}</span></td>
          <td><span class="text-xs">${(a.user_label || a.user_id).slice(0,20)}</span></td>
          <td><span class="text-xs">${a.provider || "—"}</span></td>
          <td><span class="text-xs">${a.model || "—"}</span></td>
          <td><span class="text-xs">${a.tokens_before || 0}→${a.tokens_after || 0}</span></td>
          <td><span class="text-xs">$${(a.cost_usd||0).toFixed(4)}</span></td>
          <td><span class="badge badge-sm ${a.status_code < 400 ? "bg-gradient-success" : "bg-gradient-danger"}">${a.status_code}</span></td>
        </tr>
      `).join("");
    } catch (err) { /* non-critical */ }
  }

  // ── Enterprise modal handlers ──────────────────────────────────────────────

  function initEnterpriseModals() {
    const bsModal = (id) => { try { return bootstrap.Modal.getOrCreateInstance(document.getElementById(id)); } catch { return null; } };

    // Add User
    const addUserBtn = document.getElementById("enterprise-add-user");
    if (addUserBtn) addUserBtn.addEventListener("click", () => bsModal("modal-add-user")?.show());
    const addUserSubmit = document.getElementById("add-user-submit");
    if (addUserSubmit) addUserSubmit.addEventListener("click", async () => {
      const label = document.getElementById("add-user-label").value.trim();
      const role = document.getElementById("add-user-role").value;
      if (!label) return;
      await fetchPostJson("/api/enterprise/users", { label, role });
      bsModal("modal-add-user")?.hide();
      document.getElementById("add-user-label").value = "";
      loadEnterpriseUsers();
    });

    // Add Provider Key
    const addPkBtn = document.getElementById("enterprise-add-pk");
    if (addPkBtn) addPkBtn.addEventListener("click", () => bsModal("modal-add-provider-key")?.show());
    const addPkSubmit = document.getElementById("add-pk-submit");
    if (addPkSubmit) addPkSubmit.addEventListener("click", async () => {
      const provider = document.getElementById("add-pk-provider").value;
      const label = document.getElementById("add-pk-label").value.trim();
      const api_key = document.getElementById("add-pk-apikey").value.trim();
      const upstream_url = document.getElementById("add-pk-upstream").value.trim() || null;
      if (!label || !api_key) return;
      await fetchPostJson("/api/enterprise/provider-keys", { provider, label, api_key, upstream_url });
      bsModal("modal-add-provider-key")?.hide();
      document.getElementById("add-pk-label").value = "";
      document.getElementById("add-pk-apikey").value = "";
      document.getElementById("add-pk-upstream").value = "";
      loadEnterpriseProviderKeys();
    });

    // Add Subscription
    const addSubBtn = document.getElementById("enterprise-add-sub");
    if (addSubBtn) addSubBtn.addEventListener("click", async () => {
      const { users } = await fetchJson("/api/enterprise/users");
      const { provider_keys } = await fetchJson("/api/enterprise/provider-keys");
      const userSel = document.getElementById("add-sub-user");
      const pkSel = document.getElementById("add-sub-pk");
      userSel.innerHTML = users.map(u => `<option value="${u.user_id}">${u.label || u.user_id}</option>`).join("");
      pkSel.innerHTML = provider_keys.map(k => `<option value="${k.pk_id}">${k.provider} — ${k.label || k.pk_id}</option>`).join("");
      bsModal("modal-add-sub")?.show();
    });
    const addSubType = document.getElementById("add-sub-type");
    if (addSubType) addSubType.addEventListener("change", () => {
      const isMensile = addSubType.value === "mensile";
      document.getElementById("add-sub-max-tokens-group").style.display = isMensile ? "none" : "";
      document.getElementById("add-sub-max-cost-group").style.display = isMensile ? "" : "none";
    });
    const addSubSubmit = document.getElementById("add-sub-submit");
    if (addSubSubmit) addSubSubmit.addEventListener("click", async () => {
      const user_id = document.getElementById("add-sub-user").value;
      const provider_key_id = document.getElementById("add-sub-pk").value;
      const type = document.getElementById("add-sub-type").value;
      const model = document.getElementById("add-sub-model").value.trim() || null;
      const max_tokens = parseInt(document.getElementById("add-sub-max-tokens").value) || 0;
      const max_monthly_cost_usd = parseFloat(document.getElementById("add-sub-max-cost").value) || 0;
      if (!user_id || !provider_key_id) return;
      await fetchPostJson("/api/enterprise/subscriptions", {
        user_id, provider_key_id, type, model, max_tokens, max_monthly_cost_usd,
      });
      bsModal("modal-add-sub")?.hide();
      loadEnterpriseSubscriptions();
    });
  }

  // ── page routing (client-side; server serves the same shell for every
  // route in _PAGE_ROUTES — see dashboard.py) ─────────────────────────────

  const PAGE_TITLES = {
    overview: "Overview", live: "Live monitor", compliance: "AI Compliance", charts: "Charts", sessions: "Sessions", requests: "Recent requests",
    decisions: "Decisions", settings: "Settings", profile: "Profile", notifications: "Notifications",
    cluster: "Cluster", doctor: "Doctor", version: "Version", privacy: "Privacy",
    security: "Security", proxy: "Proxy",
    "enterprise-users": "Enterprise Users", "enterprise-subscriptions": "Enterprise Subscriptions",
    "enterprise-activity": "Enterprise Activity", "enterprise-provider-keys": "Enterprise Provider Keys",
  };

  function pageForPath(path) {
    if (path === "/" || path === "/index.html" || path === "/overview") return "overview";
    const name = path.replace(/^\//, "");
    return PAGE_TITLES[name] ? name : "overview";
  }

  function showPage(name) {
    document.querySelectorAll("section[data-page]").forEach((section) => {
      section.style.display = section.dataset.page === name ? "" : "none";
    });
    document.querySelectorAll(".sidenav .nav-link[data-page-link]").forEach((link) => {
      link.classList.toggle("active", link.dataset.page === name);
    });
    // A chart laid out while its section was display:none measured 0×0 and
    // drew nothing; re-measure now that the section is on screen.
    requestAnimationFrame(() => charts.forEach((c) => c.resize()));
    document.getElementById("breadcrumb-page").textContent = PAGE_TITLES[name] || "Overview";
    // IP rules/events can change from other processes (auto-ban, rate limit) —
    // refresh them every time the page is opened, not just once at load.
    if (name === "security") {
      loadWafIpRules();
      loadWafEvents();
      loadEnterpriseGuardEvents();
      loadEnterpriseGuardClients();
    }
    if (name === "proxy") {
      loadProxyStatus();
      loadProxyConfig();
      loadProxyLogs();
    }
    if (name === "enterprise-users") {
      loadEnterpriseUsers();
    }
    if (name === "enterprise-subscriptions") {
      loadEnterpriseSubscriptions();
    }
    if (name === "enterprise-activity") {
      loadEnterpriseActivity();
    }
    if (name === "enterprise-provider-keys") {
      loadEnterpriseProviderKeys();
    }
  }

  function navigate(path, push) {
    const name = pageForPath(path);
    if (push) history.pushState({ page: name }, "", path);
    showPage(name);
  }

  document.addEventListener("click", (ev) => {
    const link = ev.target.closest("[data-page-link]");
    if (!link) return;
    ev.preventDefault();
    navigate(link.getAttribute("href"), true);
  });

  window.addEventListener("popstate", () => {
    showPage(pageForPath(window.location.pathname));
  });

  refresh();
  loadVersion();
  loadSettings();
  loadPrivacySettings();
  loadWafSettings();
  loadEnterpriseGuardSettings();
  loadStorageStatus();
  loadProfile();
  loadNotifications();
  loadClusterStatus();
  initEnterpriseModals();
  navigate(window.location.pathname, false);
  initTooltips();
  initSidenavToggle();
  initLiveMonitor();
  initCompliance();
  loadCompliance();

  const notifRefresh = document.getElementById("notif-refresh");
  if (notifRefresh) {
    notifRefresh.addEventListener("click", async () => {
      notifRefresh.disabled = true;
      try { await loadNotifications(); } finally { notifRefresh.disabled = false; }
    });
  }
  setInterval(refresh, 20000);
  setInterval(loadNotifications, 60000);
  setInterval(loadClusterStatus, 15000);
})();
