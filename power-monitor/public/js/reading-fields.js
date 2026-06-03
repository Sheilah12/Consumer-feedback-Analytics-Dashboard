/**
 * Blynk stream field accessors — primary names + legacy API aliases.
 */
(function (global) {
  "use strict";

  function readingTs(r) {
    return r.ts || r.timestamp;
  }

  function liveCurrent(r) {
    return Number(r.live_current ?? r.current_in) || 0;
  }

  function neutralCurrent(r) {
    return Number(r.neutral_current ?? r.current_out) || 0;
  }

  /** Differential in amperes (A). */
  function differentialA(r) {
    if (r.differential != null) return Number(r.differential);
    if (r.differential_current != null) return Number(r.differential_current);
    if (r.differential_ma != null) return Number(r.differential_ma) / 1000;
    return 0;
  }

  function differentialMa(r) {
    return differentialA(r) * 1000;
  }

  function energyKwh(r) {
    return Number(r.energy_kwh_cumulative ?? r.energy_kwh) || 0;
  }

  function systemStatus(r) {
    if (r.system_status) return String(r.system_status).toLowerCase();
    if (r.alert_triggered || r.hardware_alert) return "alert";
    return "normal";
  }

  function isAlertReading(r) {
    return systemStatus(r) === "alert" || Boolean(r.alert_triggered);
  }

  function hasReadingData(r) {
    return (
      r &&
      (r.voltage != null ||
        r.real_power != null ||
        r.live_current != null ||
        r.current_in != null)
    );
  }

  global.ReadingFields = {
    readingTs,
    liveCurrent,
    neutralCurrent,
    differentialA,
    differentialMa,
    energyKwh,
    systemStatus,
    isAlertReading,
    hasReadingData,
  };
})(window);
