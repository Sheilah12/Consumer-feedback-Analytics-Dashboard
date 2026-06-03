/**
 * Client polling for /api/latest — pauses when tab is hidden.
 * Demo mode (?demo=1): synthetic household load + periodic theft spikes locally.
 */
(function (global) {
  "use strict";

  const DEFAULT_INTERVAL_MS = 5000;
  const DEMO_THEFT_EVERY_MS = 90_000;
  const DEMO_THEFT_DURATION_MS = 5_000;

  let timer = null;
  let demoEnergy = 0;
  let demoLastTs = null;
  let demoTheftUntil = 0;
  let demoNextTheftAt = 0;
  let onReadingCb = null;
  let intervalMs = DEFAULT_INTERVAL_MS;

  function isDemoMode() {
    if (new URLSearchParams(global.location.search).get("demo") === "1") return true;
    try {
      return global.localStorage.getItem("power_monitor_demo") === "1";
    } catch {
      return false;
    }
  }

  function dispatch(name, detail) {
    global.dispatchEvent(new CustomEvent(name, { detail }));
  }

  function householdLoad(localHour) {
    if (localHour >= 6 && localHour < 9) return 1.35;
    if (localHour >= 18 && localHour < 22) return 1.45;
    if (localHour >= 22 || localHour < 6) return 0.55;
    return 0.85;
  }

  function demoReading() {
    const now = new Date();
    if (!demoNextTheftAt) demoNextTheftAt = now.getTime();

    if (now.getTime() >= demoNextTheftAt && !demoTheftUntil) {
      demoTheftUntil = now.getTime() + DEMO_THEFT_DURATION_MS;
      demoNextTheftAt = now.getTime() + DEMO_THEFT_EVERY_MS;
    }
    if (demoTheftUntil && now.getTime() > demoTheftUntil) demoTheftUntil = 0;

    const inTheft = demoTheftUntil && now.getTime() <= demoTheftUntil;
    const hourFrac = now.getHours() + now.getMinutes() / 60;
    const load = householdLoad(hourFrac);
    const t = now.getTime() / 1000;

    const voltage = 220 + 1.5 * Math.sin(t / 45);
    const baseAmps = 3.2 * load + 0.25 * Math.sin(t / 18);
    let currentIn;
    let currentOut;

    if (inTheft) {
      const deltaA = 0.35 + Math.random() * 0.25;
      currentIn = baseAmps + deltaA;
      currentOut = baseAmps - 0.02;
    } else {
      currentIn = baseAmps + (Math.random() - 0.5) * 0.06;
      currentOut = currentIn - (0.002 + Math.random() * 0.01);
    }

    const realPower = Math.max(0, voltage * Math.min(currentIn, currentOut));
    if (demoLastTs) {
      const dtH = (now.getTime() - demoLastTs) / 3_600_000;
      demoEnergy += (realPower / 1000) * dtH;
    }
    demoLastTs = now.getTime();

    const diffA = Math.abs(currentIn - currentOut);
    const diffMa = diffA * 1000;
    let systemStatus = "normal";
    if (inTheft && diffMa >= 300) {
      systemStatus = "isolated";
    } else if (inTheft || diffMa >= 100) {
      systemStatus = "alert";
    }
    const hardwareAlert = systemStatus === "isolated";
    const alertTriggered = systemStatus !== "normal";
    const tier =
      systemStatus === "isolated"
        ? "isolation"
        : systemStatus === "alert"
          ? "investigation"
          : null;
    const ts = now.toISOString();

    return {
      ts,
      timestamp: ts,
      live_current: Math.round(currentIn * 10000) / 10000,
      neutral_current: Math.round(currentOut * 10000) / 10000,
      differential: Math.round(diffA * 10000) / 10000,
      voltage: Math.round(voltage * 100) / 100,
      real_power: Math.round(realPower * 10) / 10,
      energy_kwh_cumulative: Math.round(demoEnergy * 10000) / 10000,
      system_status: systemStatus,
      tier,
      alert_triggered: alertTriggered,
      hardware_alert: hardwareAlert,
    };
  }

  async function fetchLatest() {
    if (isDemoMode()) {
      return demoReading();
    }
    const res = await fetch("/api/latest");
    if (!res.ok) throw new Error("latest fetch failed");
    return res.json();
  }

  async function tick() {
    try {
      const reading = await fetchLatest();
      if (onReadingCb) onReadingCb(reading);
      dispatch("sensor:reading", reading);
      const RF = global.ReadingFields;
      const isAlert = RF?.isAlertReading
        ? RF.isAlertReading(reading)
        : Boolean(reading.alert_triggered);
      if (isAlert) {
        dispatch("sensor:alert", reading);
      }
    } catch (err) {
      console.warn("[poll]", err);
    }
  }

  function schedule() {
    clearInterval(timer);
    if (global.document.visibilityState === "hidden") return;
    timer = setInterval(tick, intervalMs);
  }

  function startPolling(onReading, interval) {
    onReadingCb = onReading || null;
    intervalMs = interval || DEFAULT_INTERVAL_MS;
    tick();
    schedule();

    if (!global._pollVisibilityBound) {
      global._pollVisibilityBound = true;
      global.document.addEventListener("visibilitychange", () => {
        if (global.document.visibilityState === "hidden") {
          clearInterval(timer);
          timer = null;
        } else {
          tick();
          schedule();
        }
      });
    }
  }

  function stopPolling() {
    clearInterval(timer);
    timer = null;
    onReadingCb = null;
  }

  global.startPolling = startPolling;
  global.stopPolling = stopPolling;
  global.isDemoMode = isDemoMode;
})(window);
