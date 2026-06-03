/**
 * Monthly usage cap — server-side budget, gauge, projection chart, appliance estimator.
 */
(function () {
  "use strict";

  const LS_KEY = "power_monitor_monthly_budget_kes";
  const AA = window.AdminAuth;
  const POLL_MS = 60_000;

  let capData = null;
  let tariff = 0;
  let monthChart = null;
  let refreshTimer = null;

  const els = {
    budgetInput: document.getElementById("monthly-budget"),
    saveBtn: document.getElementById("budget-save"),
    refreshBtn: document.getElementById("budget-refresh"),
    tariff: document.getElementById("budget-tariff"),
    statusPill: document.getElementById("budget-status-pill"),
    gaugeRing: document.getElementById("cap-gauge-ring"),
    capPct: document.getElementById("cap-pct"),
    statSpent: document.getElementById("stat-spent"),
    statProjected: document.getElementById("stat-projected"),
    statRemaining: document.getElementById("stat-remaining"),
    statDailyAllow: document.getElementById("stat-daily-allow"),
    statExhaustion: document.getElementById("stat-exhaustion"),
    statKwh: document.getElementById("stat-kwh"),
    estWatts: document.getElementById("est-watts"),
    estHours: document.getElementById("est-hours"),
    estDays: document.getElementById("est-days"),
    estCalc: document.getElementById("est-calc"),
    estResult: document.getElementById("est-result"),
  };

  function kes(n) {
    return `KES ${Number(n).toFixed(2)}`;
  }

  function gaugeColor(pct) {
    if (pct >= 100) return "#e74c3c";
    if (pct >= 70) return "#f39c12";
    return "#2ecc71";
  }

  function monthStartIso() {
    const now = new Date();
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString();
  }

  function mirrorBudgetInput(value) {
    if (!els.budgetInput) return;
    const v = Number(value);
    if (Number.isFinite(v) && v >= 0) {
      els.budgetInput.value = String(v);
      try {
        localStorage.setItem(LS_KEY, String(v));
      } catch {
        /* ignore */
      }
    }
  }

  function loadBudgetMirror() {
    if (!els.budgetInput) return;
    try {
      const saved = localStorage.getItem(LS_KEY);
      if (saved && !els.budgetInput.value) els.budgetInput.value = saved;
    } catch {
      /* ignore */
    }
  }

  async function loadConfig() {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const cfg = await res.json();
    tariff = Number(cfg.tariff_kwh_cost) || 0;
    if (els.tariff) els.tariff.textContent = `${kes(cfg.tariff_kwh_cost)} / kWh`;
    if (els.budgetInput && !els.budgetInput.value) {
      mirrorBudgetInput(cfg.monthly_budget_kes);
    }
  }

  async function saveBudget() {
    if (!els.budgetInput) return;
    const value = parseFloat(els.budgetInput.value);
    if (!Number.isFinite(value) || value < 0) return;
    mirrorBudgetInput(value);
    const res = await fetch("/api/config", {
      method: "POST",
      headers: AA ? AA.adminHeaders({ "Content-Type": "application/json" }) : { "Content-Type": "application/json" },
      body: JSON.stringify({ monthly_budget_kes: value }),
    });
    if (res.status === 401) {
      alert("Unauthorized — set the Admin token on the Settings page.");
      return;
    }
    if (res.ok) await refreshCap();
  }

  function renderCap(data) {
    capData = data;
    tariff = Number(data.tariff_kwh_cost) || tariff;
    const pct = Math.min(150, Number(data.pct_used) || 0);
    const displayPct = Math.round(pct * 10) / 10;

    if (els.gaugeRing) {
      els.gaugeRing.style.setProperty("--bud-pct", String(Math.min(100, pct)));
      els.gaugeRing.style.setProperty("--bud-gauge-color", gaugeColor(pct));
    }
    if (els.capPct) els.capPct.textContent = `${displayPct}%`;

    if (els.statSpent) els.statSpent.textContent = kes(data.month_to_date_cost);
    if (els.statProjected) els.statProjected.textContent = kes(data.projected_month_cost);
    if (els.statRemaining) els.statRemaining.textContent = kes(data.remaining_kes);
    if (els.statDailyAllow) els.statDailyAllow.textContent = kes(data.daily_allowance_remaining);
    if (els.statExhaustion) {
      els.statExhaustion.textContent = data.est_exhaustion_date || (data.remaining_kes <= 0 ? "At/over cap" : "—");
    }
    if (els.statKwh) els.statKwh.textContent = `${Number(data.month_to_date_kwh).toFixed(3)} kWh`;

    if (els.statusPill) {
      if (data.on_track) {
        els.statusPill.textContent = "On track";
        els.statusPill.className = "badge badge--pace-ok";
      } else {
        const over = Number(data.projected_overage) || 0;
        els.statusPill.textContent = over > 0 ? `Over pace (+${kes(over)})` : "Over pace";
        els.statusPill.className = "badge badge--pace-bad";
      }
    }

    if (els.estDays && data.days_in_month) {
      els.estDays.value = String(data.days_in_month);
    }
  }

  function buildChartSeries(dailyRows, cap) {
    const daysInMonth = cap.days_in_month;
    const budget = Number(cap.monthly_budget_kes) || 0;
    const tariffRate = Number(cap.tariff_kwh_cost) || 0;
    const year = new Date().getUTCFullYear();
    const month = new Date().getUTCMonth();

    const byDay = new Map((dailyRows || []).map((r) => [r.day, Number(r.energy_kwh) || 0]));
    const labels = [];
    const actual = [];
    const pace = [];
    const projected = [];

    let cumulative = 0;
    const dailyRate = cap.days_elapsed > 0 ? cap.month_to_date_cost / cap.days_elapsed : 0;

    for (let d = 1; d <= daysInMonth; d++) {
      const iso = new Date(Date.UTC(year, month, d)).toISOString().slice(0, 10);
      labels.push(String(d));
      const dayKwh = byDay.get(iso) || 0;
      cumulative += dayKwh;
      const cost = cumulative * tariffRate;
      actual.push(d <= cap.days_elapsed ? round2(cost) : null);
      pace.push(round2((budget / daysInMonth) * d));
      if (d >= cap.days_elapsed) {
        const base = cap.month_to_date_cost;
        projected.push(round2(base + dailyRate * (d - cap.days_elapsed)));
      } else {
        projected.push(null);
      }
    }

    return { labels, actual, pace, projected };
  }

  function round2(n) {
    return Math.round(Number(n) * 100) / 100;
  }

  async function renderChart(cap) {
    if (typeof Chart === "undefined") return;
    const canvas = document.getElementById("chart-monthly-cap");
    if (!canvas) return;

    let daily = [];
    try {
      const res = await fetch(`/api/readings/daily?from=${encodeURIComponent(monthStartIso())}`);
      if (res.ok) daily = await res.json();
    } catch (e) {
      console.warn("[budget] daily fetch failed", e);
    }

    const series = buildChartSeries(daily, cap);
    if (monthChart) {
      monthChart.destroy();
      monthChart = null;
    }

    monthChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: series.labels,
        datasets: [
          {
            label: "Actual cumulative (KES)",
            data: series.actual,
            borderColor: "#00a3e0",
            backgroundColor: "rgba(0,163,224,0.1)",
            tension: 0.2,
            fill: true,
            spanGaps: false,
          },
          {
            label: "Budget pace",
            data: series.pace,
            borderColor: "#2ecc71",
            borderDash: [6, 4],
            pointRadius: 0,
            tension: 0,
          },
          {
            label: "Projected trend",
            data: series.projected,
            borderColor: "#f39c12",
            borderDash: [2, 3],
            pointRadius: 0,
            tension: 0.2,
            spanGaps: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { title: { display: true, text: "Day of month (UTC)" } },
          y: { title: { display: true, text: "KES cumulative" }, beginAtZero: true },
        },
        plugins: { legend: { labels: { color: "#c5d0dc" } } },
      },
    });
  }

  function runApplianceEstimate() {
    if (!capData) return;
    const watts = parseFloat(els.estWatts?.value || "0", 10);
    const hours = parseFloat(els.estHours?.value || "0", 10);
    const days = parseInt(els.estDays?.value || "30", 10);
    if (!Number.isFinite(watts) || !Number.isFinite(hours) || !Number.isFinite(days)) return;
    const kwh = (watts / 1000) * hours * days;
    const cost = kwh * (Number(capData.tariff_kwh_cost) || tariff);
    if (els.estResult) {
      els.estResult.textContent = `${watts} W × ${hours} h/day × ${days} days ≈ ${kwh.toFixed(2)} kWh → ${kes(cost)} / month`;
    }
  }

  async function refreshCap() {
    const res = await fetch("/api/budget/cap");
    if (!res.ok) return;
    const data = await res.json();
    renderCap(data);
    await renderChart(data);
  }

  function bindEvents() {
    els.saveBtn?.addEventListener("click", saveBudget);
    els.refreshBtn?.addEventListener("click", refreshCap);
    els.estCalc?.addEventListener("click", runApplianceEstimate);
    els.budgetInput?.addEventListener("change", () => mirrorBudgetInput(els.budgetInput.value));

    document.getElementById("sidebar-toggle")?.addEventListener("click", () => {
      document.querySelector(".sidebar")?.classList.toggle("open");
    });
  }

  async function init() {
    loadBudgetMirror();
    bindEvents();
    await loadConfig();
    await refreshCap();
    refreshTimer = setInterval(refreshCap, POLL_MS);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
