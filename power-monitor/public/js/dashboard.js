/**
 * Operations dashboard — SSE live stream, KPI cards, Chart.js real-time & daily.
 */
(function () {
  "use strict";

  const MAX_RT_POINTS = 30;
  const DELTA_WINDOW_MS = 5 * 60_000;
  const POLL_MS = 5000;
  const BUDGET_LS_KEY = "power_monitor_daily_budget_kwh";

  const els = {
    voltage: document.getElementById("val-voltage"),
    power: document.getElementById("val-power"),
    energy: document.getElementById("val-energy"),
    differential: document.getElementById("val-differential"),
    currentIn: document.getElementById("val-current-in"),
    currentOut: document.getElementById("val-current-out"),
    deltaVoltage: document.getElementById("delta-voltage"),
    deltaPower: document.getElementById("delta-power"),
    deltaEnergy: document.getElementById("delta-energy"),
    deltaDiff: document.getElementById("delta-diff"),
    liveBadge: document.getElementById("live-badge"),
    alertBanner: document.getElementById("alert-banner"),
    alertDetail: document.getElementById("alert-banner-detail"),
    statusDot: document.getElementById("status-dot"),
    statusLabel: document.getElementById("status-label"),
    sidebarLast: document.getElementById("sidebar-last-reading"),
    alertsBadge: document.getElementById("alerts-badge"),
    kpiGrid: document.getElementById("kpi-grid"),
    kpiDiff: document.getElementById("kpi-diff"),
  };

  let realtimeChart = null;
  let dailyChart = null;
  let pollTimer = null;
  let clockTimer = null;
  let lastReadingTs = null;
  const history = [];

  const palette = {
    cyan: "#00b4d8",
    cyanFill: "rgba(0, 180, 216, 0.15)",
    amber: "#d97706",
    blue: "rgba(21, 101, 192, 0.8)",
    blueSolid: "#1565c0",
    grid: "#e2e8f0",
    muted: "#64748b",
  };

  function parseReading(payload) {
    if (payload == null) return null;
    let r = payload;
    if (typeof r === "string") {
      try {
        r = JSON.parse(r);
      } catch {
        return null;
      }
    }
    if (typeof r === "string") {
      try {
        r = JSON.parse(r);
      } catch {
        return null;
      }
    }
    if (r.data && r.data.voltage !== undefined) r = r.data;
    if (r.voltage === undefined && r.real_power === undefined) return null;
    return r;
  }

  /** API returns differential in Amperes (4 dp). */
  function diffAmps(r) {
    return Number(r.differential_current) || 0;
  }

  function diffMa(r) {
    return diffAmps(r) * 1000;
  }

  function pushHistory(r) {
    const t = new Date(r.timestamp).getTime();
    if (Number.isNaN(t)) return;
    history.push({
      t,
      voltage: Number(r.voltage),
      power: Number(r.real_power),
      energy: Number(r.energy_kwh),
      diffA: diffAmps(r),
    });
    const cutoff = Date.now() - DELTA_WINDOW_MS - 5000;
    while (history.length && history[0].t < cutoff) history.shift();
  }

  function valueAtOrBefore(msAgo) {
    const target = Date.now() - msAgo;
    for (let i = history.length - 1; i >= 0; i--) {
      if (history[i].t <= target) return history[i];
    }
    return history.length ? history[0] : null;
  }

  function formatDelta(current, past, invert) {
    if (past == null || past === 0) return { text: "—", cls: "kpi-card__delta--flat" };
    const pct = ((current - past) / Math.abs(past)) * 100;
    if (Math.abs(pct) < 0.05) {
      return { text: "0.0% vs 5 min", cls: "kpi-card__delta--flat" };
    }
    const up = pct > 0;
    const good = invert ? !up : up;
    return {
      text: `${up ? "↑" : "↓"} ${Math.abs(pct).toFixed(1)}% vs 5 min`,
      cls: good ? "kpi-card__delta--up" : "kpi-card__delta--down",
    };
  }

  function setDelta(el, current, key, invert) {
    if (!el) return;
    const past = valueAtOrBefore(DELTA_WINDOW_MS);
    const d = formatDelta(current, past ? past[key] : null, invert);
    el.textContent = d.text;
    el.className = `kpi-card__delta ${d.cls}`;
  }

  function formatClock(ts) {
    if (!ts) return "—";
    return new Date(ts).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function updateSidebarClock() {
    if (els.sidebarLast) {
      els.sidebarLast.textContent = lastReadingTs ? formatClock(lastReadingTs) : "—";
    }
  }

  function setSystemStatus(alert) {
    if (els.statusDot) {
      els.statusDot.classList.toggle("sidebar-status__dot--ok", !alert);
      els.statusDot.classList.toggle("sidebar-status__dot--alert", alert);
    }
    if (els.statusLabel) {
      els.statusLabel.textContent = alert ? "⚠ THEFT DETECTED" : "SYSTEM NORMAL";
    }
    if (els.kpiDiff) {
      els.kpiDiff.classList.toggle("kpi-card--alert", alert);
    }
  }

  function setLiveBadge(mode) {
    if (!els.liveBadge) return;
    els.liveBadge.classList.remove("is-live", "is-reconnect", "is-poll");
    const map = {
      live: ["Live", "is-live"],
      reconnect: ["Reconnecting…", "is-reconnect"],
      poll: ["Polling", "is-poll"],
    };
    const [text, cls] = map[mode] || ["Connecting", ""];
    els.liveBadge.textContent = text;
    if (cls) els.liveBadge.classList.add(cls);
    document.querySelectorAll(".kpi-card").forEach((card) => {
      card.classList.toggle("kpi-card--reconnect", mode === "reconnect" || mode === "poll");
    });
  }

  function showAlertBanner(r) {
    if (!els.alertBanner) return;
    const on = Boolean(r.alert_triggered);
    els.alertBanner.classList.toggle("is-visible", on);
    if (on && els.alertDetail) {
      els.alertDetail.textContent = ` · ${diffMa(r).toFixed(0)} mA differential at ${new Date(r.timestamp).toLocaleString()}`;
    }
    setSystemStatus(on);
  }

  function pushRealtimeChart(r, skipUpdate) {
    if (!realtimeChart) return;
    const label = formatClock(r.timestamp);
    const power = Number(r.real_power) || 0;
    const ma = diffMa(r);

    realtimeChart.data.labels.push(label);
    realtimeChart.data.datasets[0].data.push(power);
    realtimeChart.data.datasets[1].data.push(ma);

    while (realtimeChart.data.labels.length > MAX_RT_POINTS) {
      realtimeChart.data.labels.shift();
      realtimeChart.data.datasets[0].data.shift();
      realtimeChart.data.datasets[1].data.shift();
    }

    if (!skipUpdate) {
      realtimeChart.update("none");
    }
  }

  function applyReading(raw, options) {
    const opts = options || {};
    const r = parseReading(raw);
    if (!r) return;

    pushHistory(r);
    lastReadingTs = r.timestamp;

    if (els.voltage) els.voltage.textContent = Number(r.voltage).toFixed(1);
    if (els.power) els.power.textContent = Number(r.real_power).toFixed(1);
    if (els.energy) els.energy.textContent = Number(r.energy_kwh).toFixed(4);
    if (els.differential) els.differential.textContent = diffAmps(r).toFixed(4);
    if (els.currentIn) els.currentIn.textContent = Number(r.current_in).toFixed(4);
    if (els.currentOut) els.currentOut.textContent = Number(r.current_out).toFixed(4);

    const snap = history[history.length - 1];
    if (snap) {
      setDelta(els.deltaVoltage, snap.voltage, "voltage", false);
      setDelta(els.deltaPower, snap.power, "power", false);
      setDelta(els.deltaEnergy, snap.energy, "energy", false);
      setDelta(els.deltaDiff, snap.diffA, "diffA", true);
    }

    showAlertBanner(r);
    if (!opts.skipChart) {
      pushRealtimeChart(r, opts.batchChart);
    }
    updateSidebarClock();
  }

  function initRealtimeChart() {
    if (typeof Chart === "undefined") {
      console.error("[dashboard] Chart.js not loaded");
      return false;
    }
    const ctx = document.getElementById("chart-realtime");
    if (!ctx) return false;

    realtimeChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Real Power (W)",
            data: [],
            borderColor: palette.cyan,
            backgroundColor: palette.cyanFill,
            fill: true,
            tension: 0.4,
            pointRadius: 0,
            borderWidth: 2,
            yAxisID: "y",
          },
          {
            label: "Differential (mA)",
            data: [],
            borderColor: palette.amber,
            borderDash: [6, 4],
            fill: false,
            tension: 0.4,
            pointRadius: 0,
            borderWidth: 2,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: palette.muted, boxWidth: 12, font: { size: 11 } } },
        },
        scales: {
          x: {
            ticks: { color: palette.muted, maxTicksLimit: 8, font: { size: 10 } },
            grid: { color: palette.grid },
          },
          y: {
            position: "left",
            beginAtZero: true,
            title: { display: true, text: "Power (W)", color: palette.muted },
            ticks: { color: palette.muted },
            grid: { color: palette.grid },
          },
          y1: {
            position: "right",
            beginAtZero: true,
            title: { display: true, text: "Diff (mA)", color: palette.amber },
            ticks: { color: palette.amber },
            grid: { drawOnChartArea: false },
          },
        },
      },
    });
    return true;
  }

  function buildLast7Days(apiDays) {
    const byDay = new Map((apiDays || []).map((d) => [d.day, Number(d.energy_kwh) || 0]));
    const labels = [];
    const values = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setHours(12, 0, 0, 0);
      d.setDate(d.getDate() - i);
      const key = d.toISOString().slice(0, 10);
      labels.push(
        d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })
      );
      values.push(byDay.get(key) ?? 0);
    }
    return { labels, values };
  }

  async function loadDailyChart() {
    if (typeof Chart === "undefined") return;
    const ctx = document.getElementById("chart-daily");
    if (!ctx) return;

    let days = [];
    try {
      const res = await fetch("/api/readings/daily");
      if (res.ok) days = await res.json();
    } catch (e) {
      console.warn("[dashboard] daily fetch failed", e);
    }

    const { labels, values } = buildLast7Days(days);
    const budgetRaw = localStorage.getItem(BUDGET_LS_KEY);
    const budget = parseFloat(budgetRaw, 10);
    const hasBudget = Number.isFinite(budget) && budget > 0;

    if (dailyChart) {
      dailyChart.destroy();
      dailyChart = null;
    }

    const datasets = [
      {
        type: "bar",
        label: "Energy (kWh)",
        data: values,
        backgroundColor: palette.blue,
        hoverBackgroundColor: palette.blueSolid,
        borderRadius: 4,
        order: 2,
      },
    ];

    if (hasBudget) {
      datasets.push({
        type: "line",
        label: "Daily budget",
        data: labels.map(() => budget),
        borderColor: palette.amber,
        borderDash: [8, 4],
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        order: 1,
      });
    }

    dailyChart = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: palette.muted, font: { size: 11 } } },
        },
        scales: {
          x: {
            ticks: { color: palette.muted, font: { size: 10 } },
            grid: { display: false },
          },
          y: {
            beginAtZero: true,
            title: { display: true, text: "Energy (kWh)", color: palette.muted },
            ticks: { color: palette.muted },
            grid: { color: palette.grid },
          },
        },
      },
    });
  }

  async function prefillRealtimeChart() {
    try {
      const res = await fetch("/api/readings?limit=30&offset=0");
      if (!res.ok) return;
      const body = await res.json();
      const items = body.items || body;
      if (!Array.isArray(items) || !items.length || !realtimeChart) return;

      const sorted = items.slice().reverse();
      sorted.forEach((row) => applyReading(row, { skipChart: true, batchChart: true }));
      sorted.forEach((row) => pushRealtimeChart(row, true));
      realtimeChart.update("none");
    } catch (e) {
      console.warn("[dashboard] prefill failed", e);
    }
  }

  async function loadLatest() {
    try {
      const res = await fetch("/api/latest");
      if (res.ok) applyReading(await res.json());
    } catch (e) {
      console.warn("[dashboard] latest failed", e);
    }
  }

  async function refreshAlertsBadge() {
    if (!els.alertsBadge) return;
    try {
      const res = await fetch("/api/alerts?limit=1&offset=0&acknowledged=false");
      if (!res.ok) return;
      const body = await res.json();
      const count = body.total != null ? body.total : (body.items || []).length;
      els.alertsBadge.textContent = count > 99 ? "99+" : String(count);
      els.alertsBadge.dataset.count = String(count);
    } catch {
      /* ignore */
    }
  }

  function startLiveUpdates() {
    const demo = typeof isDemoMode === "function" && isDemoMode();
    setLiveBadge(demo ? "poll" : "poll");
    if (typeof startPolling === "function") {
      startPolling((reading) => applyReading(reading), POLL_MS);
      return;
    }
    loadLatest();
    pollTimer = setInterval(loadLatest, POLL_MS);
  }

  function stopLiveUpdates() {
    if (typeof stopPolling === "function") {
      stopPolling();
    }
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function boot() {
    if (typeof Chart === "undefined") {
      console.error("[dashboard] Chart.js missing — check CDN / network");
      setLiveBadge("poll");
      startLiveUpdates();
      return;
    }

    initRealtimeChart();
    await loadLatest();
    await prefillRealtimeChart();
    await loadDailyChart();
    refreshAlertsBadge();
    startLiveUpdates();

    requestAnimationFrame(() => {
      realtimeChart?.resize();
      dailyChart?.resize();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    boot();
    clockTimer = setInterval(updateSidebarClock, 1000);
    setInterval(refreshAlertsBadge, 60000);

    document.getElementById("sidebar-toggle")?.addEventListener("click", () => {
      document.querySelector(".sidebar")?.classList.toggle("open");
    });
  });

  window.addEventListener("beforeunload", () => {
    stopLiveUpdates();
    if (clockTimer) clearInterval(clockTimer);
  });
})();
