(() => {
  "use strict";

  const state = { days: 30 };
  let timelineChart = null;
  let toolsChart = null;

  const fmtInt = (n) => new Intl.NumberFormat("en-US").format(Math.round(n || 0));
  const fmtPct = (n) => `${(n || 0).toFixed(1)}%`;
  const fmtCost = (n) => `$${(n || 0).toFixed(4)}`;

  Chart.defaults.color = "#8891a0";
  Chart.defaults.borderColor = "rgba(255,255,255,0.08)";
  Chart.defaults.font.family = "system-ui, -apple-system, sans-serif";

  async function fetchJson(url) {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`${url} -> ${res.status}`);
    return res.json();
  }

  function daysParam() {
    return state.days ? `?days=${state.days}` : "";
  }

  async function refresh() {
    document.getElementById("refresh-btn").disabled = true;
    try {
      const [summary, records, recentRequests, sessions, decisions] = await Promise.all([
        fetchJson(`/api/summary${daysParam()}`),
        fetchJson(`/api/records${daysParam()}`),
        fetchJson(`/api/records${daysParam()}${daysParam() ? "&" : "?"}limit=50`),
        fetchJson(`/api/sessions${daysParam()}`),
        fetchJson(`/api/decisions?limit=20`),
      ]);
      renderKpis(summary, sessions.sessions || [], records.records || []);
      renderToolChart(summary.by_tool || {});
      renderContentTypeTable(summary.by_content_type || {});
      renderTimeline(records.records || []);
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

  function renderKpis(s, sessions, records) {
    document.getElementById("kpi-calls").textContent = fmtInt(s.total_calls);
    document.getElementById("kpi-saved").textContent = fmtInt(s.tokens_saved);
    document.getElementById("kpi-eff").textContent = fmtPct(s.avg_efficiency_pct);
    document.getElementById("kpi-cost").textContent = fmtCost(s.cost_usd_saved);

    document.getElementById("kpi-sessions").textContent = fmtInt(sessions.length);
    const avgCalls = sessions.length ? sessions.reduce((sum, x) => sum + x.calls, 0) / sessions.length : 0;
    document.getElementById("kpi-avg-calls").textContent = avgCalls.toFixed(1);
    document.getElementById("kpi-tools").textContent = fmtInt(Object.keys(s.by_tool || {}).length);

    const bestSaved = records.reduce((max, r) => Math.max(max, r.tokens_saved || 0), 0);
    document.getElementById("kpi-best-call").textContent = bestSaved ? fmtInt(bestSaved) + " tok" : "–";

    document.getElementById("kpi-latency-avg").textContent = s.avg_latency_ms ? fmtMs(s.avg_latency_ms) : "–";
    document.getElementById("kpi-latency-p95").textContent = s.p95_latency_ms ? fmtMs(s.p95_latency_ms) : "–";
    document.getElementById("kpi-latency-max").textContent = s.max_latency_ms ? fmtMs(s.max_latency_ms) : "–";
  }

  function fmtMs(ms) {
    return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
  }

  function renderSessions(sessions) {
    const tbody = document.getElementById("table-sessions");
    if (!sessions.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-secondary">No sessions recorded yet.</td></tr>';
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

  // ── charts (Chart.js, vendored locally — no CDN) ────────────────────────────
  //
  // Chart instances are created once and updated in place via chart.update().
  // Never call `new Chart(...)` again on the same <canvas> without destroying
  // the previous instance first — Chart.js does not clean up its resize
  // listener on the old instance, so each recreation compounds the canvas's
  // reported size and the chart visibly grows on every redraw.

  function renderToolChart(byTool) {
    const entries = Object.entries(byTool).sort((a, b) => b[1] - a[1]).slice(0, 8);
    const labels = entries.map((e) => e[0]);
    const values = entries.map((e) => e[1]);

    if (!toolsChart) {
      const ctx = document.getElementById("chart-tools").getContext("2d");
      toolsChart = new Chart(ctx, {
        type: "bar",
        data: {
          labels,
          datasets: [{ label: "Tokens saved", data: values, backgroundColor: "#6ea8fe", borderRadius: 4 }],
        },
        options: chartOptions(),
      });
    } else {
      toolsChart.data.labels = labels;
      toolsChart.data.datasets[0].data = values;
      toolsChart.update();
    }
  }

  function renderTimeline(records) {
    const empty = document.getElementById("timeline-empty");
    const byDay = new Map();
    for (const r of records) {
      if (!r.ts) continue;
      const day = r.ts.slice(0, 10); // ISO date prefix
      byDay.set(day, (byDay.get(day) || 0) + (r.tokens_saved || 0));
    }
    const days = Array.from(byDay.keys()).sort().slice(-14); // keep it readable
    empty.style.display = days.length ? "none" : "block";

    const labels = days;
    const values = days.map((d) => byDay.get(d));

    if (!timelineChart) {
      const ctx = document.getElementById("chart-timeline").getContext("2d");
      timelineChart = new Chart(ctx, {
        type: "bar",
        data: {
          labels,
          datasets: [{ label: "Tokens saved", data: values, backgroundColor: "#75b798", borderRadius: 4 }],
        },
        options: chartOptions(),
      });
    } else {
      timelineChart.data.labels = labels;
      timelineChart.data.datasets[0].data = values;
      timelineChart.update();
    }
  }

  function chartOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, ticks: { callback: (v) => fmtInt(v) } },
      },
    };
  }

  document.querySelectorAll(".range-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".range-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.days = btn.dataset.days ? Number(btn.dataset.days) : null;
      refresh();
    });
  });

  document.getElementById("refresh-btn").addEventListener("click", refresh);

  refresh();
  setInterval(refresh, 20000);
})();
