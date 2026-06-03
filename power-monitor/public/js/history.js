/**
 * Historical consumption analysis — power chart, heatmap, daily bars, data table.
 */
(function () {
  "use strict";

  const RF = window.ReadingFields || {};
  const ROWS_PER_PAGE = 25;
  const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  const palette = {
    navy: "#0a1628",
    blue: "#1565c0",
    blueLight: "#1e88e5",
    cyan: "#00b4d8",
    grid: "#e2e8f0",
    muted: "#64748b",
    amber: "#d97706",
  };

  let powerChart = null;
  let dailyChart = null;
  let zoomEnabled = false;
  let powerSeries = [];
  let allReadings = [];
  let tablePage = 0;
  let heatmapGrid = [];
  let heatmapMeta = { rows: [], maxVal: 0 };
  let loadSeq = 0;
  let loadTimer = null;
  let resizeTimer = null;

  const els = {
    main: document.querySelector(".main-content"),
    from: document.getElementById("date-from"),
    to: document.getElementById("date-to"),
    apply: document.getElementById("btn-apply-range"),
    tbody: document.getElementById("readings-tbody"),
    pageInfo: document.getElementById("page-info"),
    pagePrev: document.getElementById("page-prev"),
    pageNext: document.getElementById("page-next"),
    exportCsv: document.getElementById("btn-export-csv"),
    heatCanvas: document.getElementById("heatmap-canvas"),
    heatTooltip: document.getElementById("heatmap-tooltip"),
  };

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function localDateInput(d) {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  }

  /** Local calendar date → UTC ISO bounds for API queries. */
  function isoFromDate(dateStr, endOfDay) {
    if (!dateStr) return null;
    const [y, m, d] = dateStr.split("-").map(Number);
    const dt = new Date(
      y,
      m - 1,
      d,
      endOfDay ? 23 : 0,
      endOfDay ? 59 : 0,
      endOfDay ? 59 : 0,
      endOfDay ? 999 : 0
    );
    return dt.toISOString();
  }

  function defaultRange() {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - 6);
    els.to.value = localDateInput(to);
    els.from.value = localDateInput(from);
  }

  function getRange() {
    return {
      from: isoFromDate(els.from.value, false),
      to: isoFromDate(els.to.value, true),
    };
  }

  function diffMa(r) {
    return RF.differentialMa ? RF.differentialMa(r) : (Number(r.differential_current) || 0) * 1000;
  }

  function formatTs(iso) {
    return new Date(iso).toLocaleString([], {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function formatTsShort(iso) {
    return new Date(iso).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function queryParams(from, to, extra) {
    const p = new URLSearchParams(extra || {});
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    return p.toString();
  }

  async function fetchReadings(from, to) {
    const qs = queryParams(from, to, { limit: "500", offset: "0" });
    const res = await fetch(`/api/readings?${qs}`);
    if (!res.ok) throw new Error("readings fetch failed");
    const body = await res.json();
    const items = body.items || body;
    const tsOf = (r) => new Date(RF.readingTs ? RF.readingTs(r) : r.timestamp).getTime();
    return items.slice().sort((a, b) => tsOf(a) - tsOf(b));
  }

  async function fetchHourly(from, to) {
    const qs = queryParams(from, to);
    const res = await fetch(`/api/readings/hourly?${qs}`);
    if (!res.ok) return [];
    return res.json();
  }

  async function fetchDaily(from, to) {
    const qs = queryParams(from, to);
    const res = await fetch(`/api/readings/daily?${qs}`);
    if (!res.ok) return [];
    return res.json();
  }

  function registerZoomPlugin() {
    if (typeof Chart === "undefined") return false;
    try {
      if (typeof ChartZoom !== "undefined") {
        Chart.register(ChartZoom);
        return true;
      }
      if (typeof zoomPlugin !== "undefined") {
        Chart.register(zoomPlugin);
        return true;
      }
    } catch (err) {
      console.warn("[history] zoom plugin unavailable", err);
    }
    return false;
  }

  function powerChartOptions() {
    const plugins = {
      legend: { labels: { color: palette.muted } },
      tooltip: {
        callbacks: {
          title(items) {
            const idx = items[0]?.parsed?.x;
            if (idx == null || !powerSeries[idx]) return "";
            return formatTs(powerSeries[idx].timestamp);
          },
          label(ctx) {
            return `Power: ${ctx.parsed.y.toFixed(1)} W`;
          },
        },
      },
    };

    if (zoomEnabled) {
      plugins.zoom = {
        pan: { enabled: true, mode: "x", modifierKey: "shift" },
        zoom: {
          wheel: { enabled: true, speed: 0.05 },
          pinch: { enabled: true },
          mode: "x",
        },
        limits: { x: { minRange: 10 } },
      };
    }

    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      plugins,
      scales: {
        x: {
          type: "linear",
          ticks: {
            color: palette.muted,
            maxTicksLimit: 8,
            font: { size: 10 },
            callback(value) {
              const idx = Math.round(Number(value));
              if (!powerSeries[idx]) return "";
              return formatTsShort(powerSeries[idx].timestamp);
            },
          },
          grid: { color: palette.grid },
        },
        y: {
          beginAtZero: true,
          title: { display: true, text: "Power (W)", color: palette.muted },
          ticks: { color: palette.muted },
          grid: { color: palette.grid },
        },
      },
    };
  }

  function initPowerChart() {
    if (typeof Chart === "undefined" || powerChart) return;

    const canvas = document.getElementById("chart-power");
    if (!canvas) return;

    zoomEnabled = registerZoomPlugin();

    try {
      powerChart = new Chart(canvas, {
        type: "line",
        data: {
          datasets: [
            {
              label: "Real Power (W)",
              data: [],
              borderColor: palette.cyan,
              backgroundColor: "rgba(0, 180, 216, 0.12)",
              fill: true,
              tension: 0.2,
              pointRadius: 0,
              borderWidth: 2,
            },
          ],
        },
        options: powerChartOptions(),
      });

      canvas.addEventListener("dblclick", () => {
        if (powerChart && typeof powerChart.resetZoom === "function") {
          powerChart.resetZoom();
        }
      });
    } catch (err) {
      console.error("[history] power chart init failed", err);
      zoomEnabled = false;
      if (powerChart) {
        powerChart.destroy();
        powerChart = null;
      }
    }
  }

  function initDailyChart() {
    if (typeof Chart === "undefined" || dailyChart) return;
    const ctx = document.getElementById("chart-daily");
    if (!ctx) return;

    try {
      dailyChart = new Chart(ctx, {
        type: "bar",
        data: { labels: [], datasets: [] },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: { legend: { labels: { color: palette.muted } } },
          scales: {
            x: { ticks: { color: palette.muted, maxTicksLimit: 10 }, grid: { display: false } },
            y: {
              position: "left",
              beginAtZero: true,
              title: { display: true, text: "Energy (kWh)", color: palette.muted },
              ticks: { color: palette.muted },
              grid: { color: palette.grid },
            },
            y1: {
              position: "right",
              beginAtZero: true,
              title: { display: true, text: "Peak Current (A)", color: palette.amber },
              ticks: { color: palette.amber },
              grid: { drawOnChartArea: false },
            },
          },
        },
      });
    } catch (err) {
      console.error("[history] daily chart init failed", err);
      dailyChart = null;
    }
  }

  function ensureCharts() {
    initPowerChart();
    initDailyChart();
  }

  function updatePowerChart(readings) {
    ensureCharts();
    if (!powerChart) return;

    powerSeries = readings;
    const points = readings.map((r, i) => ({
      x: i,
      y: Number(r.real_power) || 0,
    }));

    powerChart.data.datasets[0].data = points;
    const maxX = Math.max(points.length - 1, 1);
    powerChart.options.scales.x.min = 0;
    powerChart.options.scales.x.max = maxX;
    powerChart.update("none");
    powerChart.resize();
  }

  /** Row keys use UTC dates to match SQLite `date(timestamp)` in the API. */
  function last7DayKeys(endDateStr) {
    const [ey, em, ed] = endDateStr.split("-").map(Number);
    const keys = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date(Date.UTC(ey, em - 1, ed - i));
      const key = d.toISOString().slice(0, 10);
      const wd = WEEKDAYS[d.getUTCDay()];
      keys.push({
        key,
        label: `${wd} ${d.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          timeZone: "UTC",
        })}`,
      });
    }
    return keys;
  }

  function buildHeatmapGrid(hourlyBuckets, toDateStr) {
    const rows = last7DayKeys(toDateStr || els.to.value);
    const grid = rows.map(() => new Array(24).fill(0));
    const rowIndex = new Map(rows.map((r, i) => [r.key, i]));

    hourlyBuckets.forEach((b) => {
      const dayKey = b.day || (b.hour ? String(b.hour).slice(0, 10) : null);
      const rowIdx = dayKey ? rowIndex.get(dayKey) : undefined;
      const h =
        b.hour_of_day != null
          ? b.hour_of_day
          : b.hour
            ? new Date(b.hour).getUTCHours()
            : -1;
      if (rowIdx != null && h >= 0 && h < 24) {
        grid[rowIdx][h] += Number(b.energy_kwh) || 0;
      }
    });

    let maxVal = 0;
    grid.forEach((row) => row.forEach((v) => { if (v > maxVal) maxVal = v; }));

    heatmapGrid = grid;
    heatmapMeta = { rows, maxVal: maxVal || 1 };
    scheduleHeatmapDraw();
  }

  function heatColor(t) {
    const x = Math.max(0, Math.min(1, t));
    if (x <= 0) return "#ffffff";
    if (x < 0.5) {
      const u = x * 2;
      return lerpColor("#ffffff", palette.blueLight, u);
    }
    const u = (x - 0.5) * 2;
    return lerpColor(palette.blueLight, palette.navy, u);
  }

  function lerpColor(a, b, t) {
    const pa = hexRgb(a);
    const pb = hexRgb(b);
    const r = Math.round(pa.r + (pb.r - pa.r) * t);
    const g = Math.round(pa.g + (pb.g - pa.g) * t);
    const bl = Math.round(pa.b + (pb.b - pa.b) * t);
    return `rgb(${r},${g},${bl})`;
  }

  function hexRgb(hex) {
    const h = hex.replace("#", "");
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16),
    };
  }

  function scheduleHeatmapDraw() {
    requestAnimationFrame(() => drawHeatmap());
  }

  function drawHeatmap() {
    const canvas = els.heatCanvas;
    if (!canvas || !heatmapGrid.length) return;

    const wrap = canvas.parentElement;
    const width = Math.max(wrap?.clientWidth || 0, 320);
    if (width < 100) {
      requestAnimationFrame(() => drawHeatmap());
      return;
    }

    const ctx = canvas.getContext("2d");
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const labelW = 88;
    const topH = 22;
    const cols = 24;
    const rows = heatmapGrid.length;
    const cellH = 28;
    const gap = 2;
    const height = topH + rows * (cellH + gap) + 8;

    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const cellW = (width - labelW - 8) / cols;

    ctx.fillStyle = palette.muted;
    ctx.font = "10px IBM Plex Sans, sans-serif";
    ctx.textAlign = "center";
    for (let h = 0; h < 24; h++) {
      if (h % 3 !== 0) continue;
      const x = labelW + h * cellW + cellW / 2;
      ctx.fillText(String(h), x, 12);
    }

    heatmapGrid.forEach((row, ri) => {
      const y = topH + ri * (cellH + gap);
      ctx.fillStyle = palette.muted;
      ctx.textAlign = "right";
      ctx.fillText(heatmapMeta.rows[ri]?.label || "", labelW - 6, y + cellH / 2 + 4);

      row.forEach((val, ci) => {
        const x = labelW + ci * cellW;
        ctx.fillStyle = heatColor(val / heatmapMeta.maxVal);
        ctx.fillRect(x + gap / 2, y, cellW - gap, cellH);
      });
    });

    canvas._layout = { labelW, topH, cellW, cellH, gap, cols, rows };
  }

  function heatmapHover(ev) {
    const canvas = els.heatCanvas;
    const tip = els.heatTooltip;
    if (!canvas || !tip || !canvas._layout) return;

    const rect = canvas.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    const y = ev.clientY - rect.top;
    const L = canvas._layout;

    const col = Math.floor((x - L.labelW) / L.cellW);
    const row = Math.floor((y - L.topH) / (L.cellH + L.gap));

    if (col < 0 || col >= 24 || row < 0 || row >= heatmapGrid.length) {
      tip.style.display = "none";
      return;
    }

    const val = heatmapGrid[row][col];
    const dayLabel = heatmapMeta.rows[row]?.label || "";
    tip.textContent = `${dayLabel} · ${col}:00 — ${val.toFixed(4)} kWh`;
    tip.style.display = "block";
    tip.style.left = ev.clientX + 12 + "px";
    tip.style.top = ev.clientY + 12 + "px";
  }

  function updateDailyChart(daily) {
    ensureCharts();
    if (!dailyChart) return;

    const labels = daily.map((d) => {
      const dt = new Date(d.day + "T12:00:00Z");
      return dt.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    });
    const energy = daily.map((d) => Number(d.energy_kwh) || 0);
    const peak = daily.map((d) => Number(d.peak_current) || 0);
    const avg = energy.length ? energy.reduce((a, b) => a + b, 0) / energy.length : 0;

    dailyChart.data.labels = labels;
    dailyChart.data.datasets = [
      {
        type: "bar",
        label: "Energy (kWh)",
        data: energy,
        backgroundColor: "rgba(21, 101, 192, 0.75)",
        yAxisID: "y",
        order: 2,
        minBarLength: 4,
      },
      {
        type: "bar",
        label: "Peak Current (A)",
        data: peak,
        backgroundColor: "rgba(217, 119, 6, 0.55)",
        yAxisID: "y1",
        order: 3,
        minBarLength: 4,
      },
      {
        type: "line",
        label: "Avg daily energy",
        data: labels.map(() => avg),
        borderColor: palette.amber,
        borderDash: [8, 4],
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        yAxisID: "y",
        order: 1,
      },
    ];
    dailyChart.update("none");
    dailyChart.resize();
  }

  function renderTable() {
    if (!els.tbody) return;
    const totalPages = Math.max(1, Math.ceil(allReadings.length / ROWS_PER_PAGE));
    tablePage = Math.min(tablePage, totalPages - 1);
    const start = tablePage * ROWS_PER_PAGE;
    const slice = allReadings.slice(start, start + ROWS_PER_PAGE);

    if (!slice.length) {
      els.tbody.innerHTML = '<tr><td colspan="8">No readings in this range.</td></tr>';
    } else {
      els.tbody.innerHTML = slice
        .map((r) => {
          const st = RF.systemStatus ? RF.systemStatus(r) : (r.alert_triggered ? "alert" : "normal");
          const pill =
            st === "alert"
              ? '<span class="pill pill--alert">Alert</span>'
              : '<span class="pill pill--ok">Normal</span>';
          const ts = RF.readingTs ? RF.readingTs(r) : r.timestamp;
          const live = RF.liveCurrent ? RF.liveCurrent(r) : Number(r.current_in);
          const neutral = RF.neutralCurrent ? RF.neutralCurrent(r) : Number(r.current_out);
          const energy = RF.energyKwh ? RF.energyKwh(r) : Number(r.energy_kwh);
          return `<tr>
            <td>${formatTs(ts)}</td>
            <td>${Number(r.voltage).toFixed(2)}</td>
            <td>${live.toFixed(4)}</td>
            <td>${neutral.toFixed(4)}</td>
            <td>${diffMa(r).toFixed(1)}</td>
            <td>${Number(r.real_power).toFixed(1)}</td>
            <td>${energy.toFixed(4)}</td>
            <td>${pill}</td>
          </tr>`;
        })
        .join("");
    }

    if (els.pageInfo) {
      els.pageInfo.textContent = `Page ${tablePage + 1} / ${totalPages} (${allReadings.length} rows)`;
    }
    if (els.pagePrev) els.pagePrev.disabled = tablePage <= 0;
    if (els.pageNext) els.pageNext.disabled = tablePage >= totalPages - 1;
  }

  function exportCsv() {
    if (!allReadings.length) return;
    const header = [
      "ts",
      "voltage_v",
      "live_current_a",
      "neutral_current_a",
      "differential_ma",
      "real_power_w",
      "energy_kwh_cumulative",
      "system_status",
    ];
    const rows = allReadings.map((r) => {
      const ts = RF.readingTs ? RF.readingTs(r) : r.timestamp;
      const live = RF.liveCurrent ? RF.liveCurrent(r) : r.current_in;
      const neutral = RF.neutralCurrent ? RF.neutralCurrent(r) : r.current_out;
      const energy = RF.energyKwh ? RF.energyKwh(r) : r.energy_kwh;
      const st = RF.systemStatus ? RF.systemStatus(r) : r.alert_triggered ? "alert" : "normal";
      return [
        ts,
        r.voltage,
        live,
        neutral,
        diffMa(r).toFixed(2),
        r.real_power,
        energy,
        st,
      ].join(",");
    });
    const csv = [header.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `readings_${els.from.value}_${els.to.value}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function setLoading(on) {
    els.main?.classList.toggle("hist-loading", on);
  }

  async function loadAll() {
    const { from, to } = getRange();
    if (!from || !to || from > to) return;

    const seq = ++loadSeq;
    setLoading(true);

    try {
      const [readings, hourly, daily] = await Promise.all([
        fetchReadings(from, to),
        fetchHourly(from, to),
        fetchDaily(from, to),
      ]);

      if (seq !== loadSeq) return;

      allReadings = readings;
      tablePage = 0;
      updatePowerChart(readings);
      buildHeatmapGrid(hourly, els.to.value);
      updateDailyChart(daily);
      renderTable();
    } catch (e) {
      console.error("[history]", e);
      if (seq === loadSeq && els.tbody) {
        els.tbody.innerHTML = '<tr><td colspan="8">Failed to load data.</td></tr>';
      }
    } finally {
      if (seq === loadSeq) setLoading(false);
    }
  }

  function scheduleLoadAll() {
    clearTimeout(loadTimer);
    loadTimer = setTimeout(loadAll, 250);
  }

  document.addEventListener("DOMContentLoaded", () => {
    defaultRange();
    ensureCharts();

    requestAnimationFrame(() => {
      loadAll();
    });

    els.apply?.addEventListener("click", loadAll);
    els.from?.addEventListener("change", scheduleLoadAll);
    els.to?.addEventListener("change", scheduleLoadAll);

    els.pagePrev?.addEventListener("click", () => {
      tablePage -= 1;
      renderTable();
    });
    els.pageNext?.addEventListener("click", () => {
      tablePage += 1;
      renderTable();
    });
    els.exportCsv?.addEventListener("click", exportCsv);

    els.heatCanvas?.addEventListener("mousemove", heatmapHover);
    els.heatCanvas?.addEventListener("mouseleave", () => {
      if (els.heatTooltip) els.heatTooltip.style.display = "none";
    });

    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        drawHeatmap();
        powerChart?.resize();
        dailyChart?.resize();
      }, 150);
    });

    document.getElementById("sidebar-toggle")?.addEventListener("click", () => {
      document.querySelector(".sidebar")?.classList.toggle("open");
      setTimeout(() => {
        drawHeatmap();
        powerChart?.resize();
        dailyChart?.resize();
      }, 220);
    });
  });
})();
