/**
 * Detection page — live two-tier gauge, state badge, sparkline, incident log.
 */
(function () {
  "use strict";

  const RF = window.ReadingFields || {};
  const AA = window.AdminAuth;
  const POLL_MS = 5000;
  const SPARK_WINDOW_MS = 60_000;

  let config = {
    alert_threshold_ma: 100,
    isolation_threshold_ma: 300,
  };
  let sparkSeries = [];
  let gaugeMaxMa = 450;

  const els = {
    stateBadge: document.getElementById("det-state-badge"),
    stateReadout: document.getElementById("det-state-readout"),
    isolationBanner: document.getElementById("det-isolation-banner"),
    gaugeNeedle: document.getElementById("gauge-needle"),
    gaugeMa: document.getElementById("gauge-ma"),
    gaugeMaA: document.getElementById("gauge-ma-a"),
    zoneNormal: document.getElementById("zone-normal"),
    zoneInvestigation: document.getElementById("zone-investigation"),
    bandNormal: document.getElementById("band-normal"),
    bandInvestigation: document.getElementById("band-investigation"),
    bandIsolation: document.getElementById("band-isolation"),
    legendAlert: document.getElementById("legend-alert-ma"),
    legendIso: document.getElementById("legend-iso-ma"),
    sparkCanvas: document.getElementById("spark-canvas"),
    tbody: document.getElementById("incidents-body"),
    filterUnack: document.getElementById("filter-unack"),
    btnRefresh: document.getElementById("incidents-refresh"),
  };

  function maToA(ma) {
    return (Number(ma) / 1000).toFixed(3);
  }

  function displayState(reading) {
    const st = RF.systemStatus ? RF.systemStatus(reading) : "normal";
    if (st === "isolated") return { key: "isolated", label: "ISOLATED" };
    if (st === "alert") return { key: "investigation", label: "INVESTIGATION" };
    return { key: "normal", label: "NORMAL" };
  }

  function computeGaugeMax() {
    gaugeMaxMa = Math.max(
      config.isolation_threshold_ma * 1.5,
      config.isolation_threshold_ma + 100,
      400
    );
  }

  function applyGaugeLayout() {
    computeGaugeMax();
    const alert = config.alert_threshold_ma;
    const iso = config.isolation_threshold_ma;
    const pctAlert = (alert / gaugeMaxMa) * 100;
    const pctIso = (iso / gaugeMaxMa) * 100;

    if (els.zoneNormal) els.zoneNormal.style.width = pctAlert + "%";
    if (els.zoneInvestigation) {
      els.zoneInvestigation.style.width = Math.max(0, pctIso - pctAlert) + "%";
    }

    const aAlert = maToA(alert);
    const aIso = maToA(iso);
    if (els.bandNormal) {
      els.bandNormal.textContent = `Normal\n0 – ${aAlert} A`;
    }
    if (els.bandInvestigation) {
      els.bandInvestigation.textContent = `Investigation\n${aAlert} – ${aIso} A`;
    }
    if (els.bandIsolation) {
      els.bandIsolation.textContent = `Isolation\n> ${aIso} A`;
    }
    if (els.legendAlert) els.legendAlert.textContent = `${alert} mA (${aAlert} A)`;
    if (els.legendIso) els.legendIso.textContent = `${iso} mA (${aIso} A)`;
  }

  function updateGauge(reading) {
    if (!reading) return;
    const ma = RF.differentialMa ? RF.differentialMa(reading) : 0;
    const pct = Math.min(100, Math.max(0, (ma / gaugeMaxMa) * 100));
    if (els.gaugeNeedle) els.gaugeNeedle.style.left = pct + "%";
    if (els.gaugeMa) els.gaugeMa.textContent = ma.toFixed(1);
    if (els.gaugeMaA) els.gaugeMaA.textContent = maToA(ma) + " A";
  }

  function updateStateBadge(reading) {
    if (!reading || !els.stateBadge) return;
    const { key, label } = displayState(reading);
    els.stateBadge.textContent = label;
    els.stateBadge.className = "det-state-badge det-state-badge--" + key;

    const ma = RF.differentialMa ? RF.differentialMa(reading) : 0;
    const deviceSt = RF.systemStatus ? RF.systemStatus(reading) : "normal";
    if (els.stateReadout) {
      els.stateReadout.innerHTML =
        `Device status: <strong>${deviceSt}</strong> · ` +
        `Differential: <strong>${ma.toFixed(1)} mA</strong> (${maToA(ma)} A)`;
    }

    if (els.isolationBanner) {
      els.isolationBanner.classList.toggle("is-visible", key === "isolated");
    }
  }

  function applyReading(reading) {
    if (!RF.hasReadingData || !RF.hasReadingData(reading)) return;
    updateGauge(reading);
    updateStateBadge(reading);
    pushSpark(reading);
  }

  function pushSpark(reading) {
    const ma = RF.differentialMa ? RF.differentialMa(reading) : 0;
    const ts = RF.readingTs ? RF.readingTs(reading) : reading.timestamp;
    const t = new Date(ts).getTime();
    if (Number.isNaN(t)) return;
    sparkSeries.push({ t, ma });
    const cutoff = Date.now() - SPARK_WINDOW_MS;
    sparkSeries = sparkSeries.filter((p) => p.t >= cutoff);
    drawSpark();
  }

  function drawSpark() {
    const canvas = els.sparkCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width;
    const h = rect.height;
    ctx.clearRect(0, 0, w, h);

    if (sparkSeries.length < 2) {
      ctx.fillStyle = "#8a9bb0";
      ctx.font = "12px IBM Plex Sans, sans-serif";
      ctx.fillText("Collecting differential samples…", 8, h / 2);
      return;
    }

    const now = Date.now();
    const tMin = now - SPARK_WINDOW_MS;
    const maxY = Math.max(gaugeMaxMa, ...sparkSeries.map((p) => p.ma), 50);
    const alertY = h - (config.alert_threshold_ma / maxY) * (h - 8);
    const isoY = h - (config.isolation_threshold_ma / maxY) * (h - 8);

    ctx.strokeStyle = "rgba(46,204,113,0.25)";
    ctx.beginPath();
    ctx.moveTo(0, alertY);
    ctx.lineTo(w, alertY);
    ctx.stroke();
    ctx.strokeStyle = "rgba(231,76,60,0.35)";
    ctx.beginPath();
    ctx.moveTo(0, isoY);
    ctx.lineTo(w, isoY);
    ctx.stroke();

    ctx.strokeStyle = "#00a3e0";
    ctx.lineWidth = 2;
    ctx.beginPath();
    sparkSeries.forEach((p, i) => {
      const x = ((p.t - tMin) / SPARK_WINDOW_MS) * w;
      const y = h - (p.ma / maxY) * (h - 8);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function tierPill(tier) {
    const t = (tier || "").toLowerCase();
    if (t === "investigation") {
      return '<span class="pill-tier pill-tier--investigation">Investigation</span>';
    }
    if (t === "isolation") {
      return '<span class="pill-tier pill-tier--isolation">Isolation</span>';
    }
    return `<span class="pill-tier pill-tier--unknown">${tier || "—"}</span>`;
  }

  async function loadIncidents() {
    if (!els.tbody) return;
    const unack = els.filterUnack && els.filterUnack.checked;
    const url = `/api/alerts?limit=100&offset=0${unack ? "&acknowledged=false" : ""}`;
    const res = await fetch(url);
    if (!res.ok) {
      els.tbody.innerHTML = '<tr><td colspan="6">Failed to load incidents.</td></tr>';
      return;
    }
    const body = await res.json();
    const items = body.items || [];
    if (!items.length) {
      els.tbody.innerHTML = '<tr><td colspan="6">No incidents recorded.</td></tr>';
      return;
    }
    els.tbody.innerHTML = items
      .map((a) => {
        const ts = new Date(a.timestamp || a.ts).toLocaleString();
        const ma = Number(a.differential_ma) || 0;
        const ack = a.acknowledged
          ? '<span class="status-dot status-dot--ok"></span> Acknowledged'
          : '<span class="status-dot status-dot--err"></span> Open';
        const btn = a.acknowledged
          ? ""
          : `<button type="button" class="btn btn--primary" data-id="${a.id}">Acknowledge</button>`;
        return `<tr>
          <td class="mono">${ts}</td>
          <td>${tierPill(a.tier)}</td>
          <td class="det-diff-cell">${ma.toFixed(0)} mA<br><span style="color:var(--color-slate-400)">${maToA(ma)} A</span></td>
          <td>${a.message || "—"}</td>
          <td>${ack}</td>
          <td>${btn}</td>
        </tr>`;
      })
      .join("");
  }

  async function loadConfig() {
    try {
      const res = await fetch("/api/config");
      if (res.ok) {
        const cfg = await res.json();
        config.alert_threshold_ma = Number(cfg.alert_threshold_ma) || 100;
        config.isolation_threshold_ma = Number(cfg.isolation_threshold_ma) || 300;
      }
    } catch (e) {
      console.warn("[detection] config fetch failed", e);
    }
    applyGaugeLayout();
  }

  function bindEvents() {
    els.tbody?.addEventListener("click", async (e) => {
      const btn = e.target.closest("button[data-id]");
      if (!btn) return;
      const res = await fetch(`/api/alerts/${btn.dataset.id}/ack`, {
        method: "POST",
        headers: AA ? AA.adminHeaders() : {},
      });
      if (!res.ok && res.status === 401) {
        alert("Unauthorized — set the Admin token on the Settings page.");
        return;
      }
      loadIncidents();
    });

    els.btnRefresh?.addEventListener("click", loadIncidents);
    els.filterUnack?.addEventListener("change", loadIncidents);

    document.getElementById("sidebar-toggle")?.addEventListener("click", () => {
      document.querySelector(".sidebar")?.classList.toggle("open");
    });

    window.addEventListener("resize", () => drawSpark());
  }

  async function init() {
    await loadConfig();
    bindEvents();
    loadIncidents();

    if (typeof startPolling === "function") {
      startPolling(applyReading, POLL_MS);
    } else {
      try {
        const res = await fetch("/api/latest");
        if (res.ok) applyReading(await res.json());
      } catch (e) {
        console.warn("[detection] latest fetch failed", e);
      }
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
