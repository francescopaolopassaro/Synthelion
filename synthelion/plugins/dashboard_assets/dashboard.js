(() => {
  "use strict";

  const state = { days: 30 };
  let timelineChart = null;
  let toolsChart = null;

  const fmtInt = (n) => new Intl.NumberFormat("en-US").format(Math.round(n || 0));
  const fmtPct = (n) => `${(n || 0).toFixed(1)}%`;
  const fmtCo2 = (mg) => (mg || 0) >= 1000 ? `${((mg || 0) / 1000).toFixed(2)}g` : `${(mg || 0).toFixed(1)}mg`;

  Chart.defaults.color = "#8891a0";
  Chart.defaults.borderColor = "rgba(255,255,255,0.08)";
  Chart.defaults.font.family = "system-ui, -apple-system, sans-serif";

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
  }

  function fmtMs(ms) {
    return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
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
    btn.disabled = true;
    status.textContent = "Upgrading — this can take a minute…";
    status.className = "text-sm text-secondary";
    try {
      const r = await postJson("/api/upgrade", {});
      if (r.success) {
        status.textContent = "Upgraded. Restart the dashboard/MCP server to activate.";
        status.className = "text-sm text-success";
      } else {
        status.textContent = "Upgrade failed — see server log.";
        status.className = "text-sm text-danger";
      }
    } catch (err) {
      status.textContent = "Error: " + err.message;
      status.className = "text-sm text-danger";
    } finally {
      btn.disabled = false;
    }
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

  function notificationItemHtml(n) {
    const cls = n.level === "error" ? "text-danger" : "text-warning";
    return `<div class="d-flex flex-column py-1">
      <span class="text-sm font-weight-bold ${cls}">${escapeHtml(n.title)}</span>
      <span class="text-xs text-secondary">${escapeHtml(n.message)}</span>
    </div>`;
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

      const dropdown = document.getElementById("notif-dropdown");
      dropdown.innerHTML = notifications.length
        ? notifications.map((n) => `<li class="mb-1 px-2">${notificationItemHtml(n)}</li>`).join("")
        : '<li class="text-secondary text-sm px-2">No notifications.</li>';

      const pageList = document.getElementById("notif-page-list");
      pageList.innerHTML = notifications.length
        ? notifications.map((n) => `<li class="list-group-item">${notificationItemHtml(n)}</li>`).join("")
        : '<li class="list-group-item text-secondary">No notifications — everything looks fine.</li>';

      const profileList = document.getElementById("profile-notifications-list");
      if (profileList) {
        profileList.innerHTML = notifications.length
          ? notifications.map((n) => `<li class="list-group-item border-0 px-0">${notificationItemHtml(n)}</li>`).join("")
          : '<li class="list-group-item border-0 px-0 text-sm text-secondary">No notifications — everything looks fine.</li>';
      }
    } catch (err) {
      // non-critical
    }
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

  // ── page routing (client-side; server serves the same shell for every
  // route in _PAGE_ROUTES — see dashboard.py) ─────────────────────────────

  const PAGE_TITLES = {
    overview: "Overview", charts: "Charts", sessions: "Sessions", requests: "Recent requests",
    decisions: "Decisions", settings: "Settings", profile: "Profile", notifications: "Notifications",
    cluster: "Cluster",
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
    // .nav-link.active alone only tweaks padding in Material Dashboard's CSS —
    // the visible highlighted pill comes from the bg-gradient-* utility class
    // itself, so it has to be toggled alongside .active, not left to CSS.
    document.querySelectorAll(".sidenav .nav-link[data-page-link]").forEach((link) => {
      const isActive = link.dataset.page === name;
      link.classList.toggle("active", isActive);
      link.classList.toggle("bg-gradient-info", isActive);
    });
    document.getElementById("breadcrumb-page").textContent = PAGE_TITLES[name] || "Overview";
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
  loadStorageStatus();
  loadProfile();
  loadNotifications();
  loadClusterStatus();
  navigate(window.location.pathname, false);
  setInterval(refresh, 20000);
  setInterval(loadNotifications, 60000);
  setInterval(loadClusterStatus, 15000);
})();
