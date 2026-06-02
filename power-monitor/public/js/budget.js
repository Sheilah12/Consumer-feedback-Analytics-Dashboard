/**
 * Budget cap and cost estimator.
 */
(function () {
  async function refresh() {
    const hours = parseInt(document.getElementById("budget-hours")?.value || "24", 10);
    const capInput = document.getElementById("budget-cap");
    const cap = capInput?.value ? parseFloat(capInput.value) : null;

    let url = `/api/budget/estimate?hours=${hours}`;
    if (cap !== null && !Number.isNaN(cap)) {
      url += `&cap_kwh=${cap}`;
    }

    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();

    const energyEl = document.getElementById("budget-energy");
    const costEl = document.getElementById("budget-cost");
    const capEl = document.getElementById("budget-cap-cost");
    const statusEl = document.getElementById("budget-status");

    if (energyEl) energyEl.textContent = data.energy_kwh.toFixed(3);
    const cost = data.estimated_cost_kes ?? data.estimated_cost;
    if (costEl) costEl.textContent = `KES ${Number(cost).toFixed(2)}`;
    if (capEl) {
      capEl.textContent =
        data.cap_cost_kes != null
          ? `KES ${data.cap_cost_kes.toFixed(2)}`
          : data.cap_cost != null
            ? `KES ${data.cap_cost.toFixed(2)}`
            : "—";
    }
    if (statusEl) {
      if (data.over_cap) {
        statusEl.textContent = "Over budget cap";
        statusEl.className = "badge badge--alert";
      } else {
        statusEl.textContent = "Within cap";
        statusEl.className = "badge";
      }
    }

    const tariffEl = document.getElementById("budget-tariff");
    if (tariffEl) {
      tariffEl.textContent = `KES ${data.tariff_kwh_cost.toFixed(2)} / kWh`;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    refresh();
    document.getElementById("budget-refresh")?.addEventListener("click", refresh);
    document.getElementById("budget-hours")?.addEventListener("change", refresh);
    const capInput = document.getElementById("budget-cap");
    const saved = localStorage.getItem("power_monitor_daily_budget_kwh");
    if (capInput && saved) capInput.value = saved;
    capInput?.addEventListener("change", () => {
      const v = parseFloat(capInput.value, 10);
      if (Number.isFinite(v) && v > 0) {
        localStorage.setItem("power_monitor_daily_budget_kwh", String(v));
      } else {
        localStorage.removeItem("power_monitor_daily_budget_kwh");
      }
      refresh();
    });

    const toggle = document.getElementById("sidebar-toggle");
    const sidebar = document.querySelector(".sidebar");
    toggle?.addEventListener("click", () => sidebar?.classList.toggle("open"));
  });
})();
