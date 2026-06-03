/**
 * Optional ADMIN_TOKEN for protected writes — stored in sessionStorage only.
 */
(function (global) {
  "use strict";

  const STORAGE_KEY = "power_monitor_admin_token";

  function getAdminToken() {
    try {
      return sessionStorage.getItem(STORAGE_KEY) || "";
    } catch {
      return "";
    }
  }

  function setAdminToken(value) {
    try {
      const v = String(value || "").trim();
      if (v) sessionStorage.setItem(STORAGE_KEY, v);
      else sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }

  /** Merge Content-Type and X-Admin-Token when a token is stored. */
  function adminHeaders(extra) {
    const headers = Object.assign({}, extra || {});
    const token = getAdminToken();
    if (token) headers["X-Admin-Token"] = token;
    return headers;
  }

  global.AdminAuth = {
    getAdminToken,
    setAdminToken,
    adminHeaders,
  };
})(window);
