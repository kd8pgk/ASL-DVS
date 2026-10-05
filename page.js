
"use strict";

window._authLostHandled = false;

const _rawFetch = window.fetch.bind(window);
window.fetch = async function(input, init) {
  const url = typeof input === "string" ? input : (input && input.url) || "";
  const isApi = url.startsWith("/api/");
  const skipAuth = url === "/api/login" || url === "/api/ping";
  const res = await _rawFetch(input, init);
  if (isApi && !skipAuth && res.status === 401) _onAuthLost();
  return res;
};

let _appStarted = false;
const _RELOGIN_KEY         = "sysmonRelogin";
const _RELOGIN_WINDOW_MS   = 30000;
const _SESSION_EXPIRED_MSG = "Session expired — please log in again.";

function _onAuthLost() {
  if (window._authLostHandled) return;
  window._authLostHandled = true;
  if (_appStarted) {
    let last = 0;
    try { last = Number(sessionStorage.getItem(_RELOGIN_KEY)) || 0; } catch (_) {}
    if (!last || Date.now() - last > _RELOGIN_WINDOW_MS) {
      let stamped = false;
      try { sessionStorage.setItem(_RELOGIN_KEY, String(Date.now())); stamped = true; } catch (_) {}
      if (stamped) {
        location.reload();
        return;
      }
    }
  }
  showLoginScreen(_SESSION_EXPIRED_MSG);
}
function showLoginScreen(msg) {
  const el = document.getElementById("login-screen"); if (!el) return;
  el.classList.add("open");
  const errEl = document.getElementById("login-err"); if (errEl) errEl.textContent = msg || "";
  const pwEl = document.getElementById("login-pw");
  if (pwEl) { pwEl.value = ""; setTimeout(() => pwEl.focus(), 0); }
}
function hideLoginScreen() {
  const el = document.getElementById("login-screen"); if (el) el.classList.remove("open");
}

async function _doLogin(ev) {
  if (ev) ev.preventDefault();
  const pwEl = document.getElementById("login-pw");
  const btnEl = document.getElementById("login-btn");
  const errEl = document.getElementById("login-err");
  const password = pwEl ? pwEl.value : "";
  if (!password) return;
  if (btnEl) btnEl.disabled = true;
  if (errEl) errEl.textContent = "";
  try {
    const r = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password })
    });
    const d = await r.json().catch(() => ({ ok: false, message: "Unexpected response" }));
    if (r.ok && d.ok) {
      window._authLostHandled = false;
      try { sessionStorage.removeItem(_RELOGIN_KEY); } catch (_) {}
      hideLoginScreen();
      _startApp();
    } else {
      if (errEl) errEl.textContent = d.message || "Login failed";
    }
  } catch (e) {
    if (errEl) errEl.textContent = "Network error — is sysmon reachable?";
  } finally {
    if (btnEl) btnEl.disabled = false;
  }
}
function doLogout() {
  fetch("/api/logout", { method: "POST" })
    .catch(() => {})
    .finally(() => location.reload());
}


const TABS = ["overview","services","ports","firewall","journal","asldvs","reg","phone","tune","hardware","dvsm","stfu","m17","zello","sdcard","security","edit"];

let _enabledTabSet = new Set(TABS);

let _savedEnabledTabs = TABS.slice();
let _zelloInstalled   = false;

let _ptRefreshTimer  = null;
let _phRefreshTimer  = null;
let _s3RefreshTimer  = null;
let _sdTestTimer = null;
let _statusPollTimer = null;

function _applyTabVisibilityGated() {
  const list = _savedEnabledTabs.filter(t => t !== "zello" || _zelloInstalled);
  applyTabVisibility(list);
}


function stopTabPolling(tab) {
  let cleared = false;
  if (tab === "ports"    && _ptRefreshTimer) { clearInterval(_ptRefreshTimer); _ptRefreshTimer = null; cleared = true; }
  if (tab === "phone"    && _phRefreshTimer) { clearInterval(_phRefreshTimer); _phRefreshTimer = null; cleared = true; }
  if (tab === "services" && _s3RefreshTimer) { clearInterval(_s3RefreshTimer); _s3RefreshTimer = null; cleared = true; }
  if (tab === "sdcard"   && _sdTestTimer)    { clearInterval(_sdTestTimer);    _sdTestTimer    = null; cleared = true; }
  if (cleared) console.info("[sysmon] polling stopped: " + tab);
  return cleared;
}

function startStatusPolling() {
  if (_statusPollTimer) return;
  pollStatus();
  _statusPollTimer = setInterval(pollStatus, 5000);
}
function stopStatusPolling() {
  if (_statusPollTimer) { clearInterval(_statusPollTimer); _statusPollTimer = null; }
}

function switchTab(name, rgb) {
  TABS.forEach(t => {
    const panel = document.getElementById("panel-" + t);
    const btn   = document.getElementById("tbtn-" + t);
    if (!panel || !btn) return;
    const active = t === name;
    panel.classList.toggle("active", active);
    btn.classList.toggle("active",   active);
    if (active && rgb) {
      btn.style.setProperty("--ta",     `rgb(${rgb})`);
      btn.style.setProperty("--ta-rgb", rgb);
    }
  });
  TABS.forEach(t => document.body.classList.toggle("tab-" + t, t === name));

  TABS.forEach(t => { if (t !== name && t !== "sdcard") stopTabPolling(t); });

  if (_enabledTabSet.has(name) &&
      typeof window["loadTab_" + name] === "function") {
    window["loadTab_" + name]();
  }
}

function applyTabVisibility(enabled) {
  const set = new Set(Array.isArray(enabled) && enabled.length ? enabled : TABS);
  set.add("overview"); set.add("edit");
  _enabledTabSet = set;
  for (const t of TABS) {
    const btn = document.getElementById("tbtn-" + t);
    if (btn) btn.style.display = set.has(t) ? "" : "none";
    if (!set.has(t)) {
      if (t === "sdcard" && _sdTestTimer) {
        toast("SD test continues in background — re-enable tab to monitor", "info", 5000);
      }
      stopTabPolling(t);
    }
  }
  const active = TABS.find(t =>
    document.getElementById("tbtn-" + t)?.classList.contains("active"));
  if (active && !set.has(active)) {
    switchTab("overview", "0,255,229");
  }
}

let _toastId = 0;
function toast(msg, type, ms) {
  ms   = ms   || 3500;
  type = type || "info";
  const el = document.createElement("div");
  el.className  = "toast-item " + type;
  el.textContent = msg;
  el.id = "toast-" + (++_toastId);
  document.getElementById("toast-stack").appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("show")));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 300);
  }, ms);
}

async function api(path, method, body) {
  method = method || "GET";
  try {
    const opts = {method: method, headers: {}};
    if (body !== null && body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(path, opts);
    document.body.classList.remove("offline");
    return await r.json();
  } catch(e) {
    document.body.classList.add("offline");
    return null;
  }
}

let _uptimeBase = null;

let _wfmShutdownShown = false;
function showWfmShutdown(state) {
  if (_wfmShutdownShown) return;
  _wfmShutdownShown = true;
  const trig = state.trigger === "low_voltage" ? "Low voltage" :
               state.trigger === "no_conn"     ? "Lost network connection" : "wifimon";
  document.getElementById("wfm-shutdown-msg").textContent =
    trig + " — " + (state.reason || "shutting down now.");
  document.getElementById("wfm-shutdown-overlay").classList.add("open");
}

async function pollStatus() {
  const d = await api("/api/status");
  if (!d) return;

  if (d.wifimon_shutdown && d.wifimon_shutdown.active) showWfmShutdown(d.wifimon_shutdown);

  if (typeof d.zello_installed === "boolean" && d.zello_installed !== _zelloInstalled) {
    _zelloInstalled = d.zello_installed;
    _applyTabVisibilityGated();
  }

  window._portConflicts = d.port_conflicts || {};

  if (d.callsign) document.getElementById("hdr-callsign").textContent = d.callsign;
  if (d.node)     document.getElementById("hdr-node").textContent     = d.node;

  if (d.uptime_s != null) {
    _uptimeBase = {s: d.uptime_s, at: Date.now()};
    renderUptime();
  }

  const load = d.load || {};
  if (d.hostname) {
    const h = document.getElementById("s-host");
    h.textContent = d.hostname;
  }
  if (load.l1 != null) {
    const el  = document.getElementById("s-load");
    const l1  = parseFloat(load.l1);
    el.textContent = load.l1 + " / " + load.l5 + " / " + load.l15;
    el.className   = "sv" + (l1 > 3 ? " hot" : l1 > 1.5 ? " warn" : " ok");
  }
  if (d.memory && d.memory.used_mb != null) {
    document.getElementById("s-mem").textContent =
      d.memory.used_mb + " / " + d.memory.total_mb + " MiB";
  }
  if (d.cpu_temp != null) {
    const el = document.getElementById("s-temp");
    el.textContent = d.cpu_temp + "°C";
    el.className   = "sv" + (d.cpu_temp > 75 ? " hot" : d.cpu_temp > 60 ? " warn" : " ok");
  }
  if (d.throttle_state && d.throttle_state.available) {
    const ts  = d.throttle_state;
    const el  = document.getElementById("s-volt");
    
    if (ts.uv_now) {
      el.textContent = "⚡ UV";
      el.className   = "sv hot";
    } else if (ts.throttled_now) {
      el.textContent = "⚡ THR";
      el.className   = "sv hot";
    } else if (ts.uv_ever || ts.freq_cap_ever || ts.throttled_ever || ts.temp_ever) {
      el.textContent = "WARN";
      el.className   = "sv warn";
    } else {
      el.textContent = "OK";
      el.className   = "sv ok";
    }
    
    const bits = [];
    if (ts.uv_now)         bits.push("Under-voltage NOW");
    if (ts.freq_cap_now)   bits.push("Freq cap NOW");
    if (ts.throttled_now)  bits.push("Throttled NOW");
    if (ts.temp_now)       bits.push("Temp limit NOW");
    if (ts.uv_ever)        bits.push("Under-voltage since boot");
    if (ts.freq_cap_ever)  bits.push("Freq cap since boot");
    if (ts.throttled_ever) bits.push("Throttled since boot");
    if (ts.temp_ever)      bits.push("Temp limit since boot");
    el.title = bits.length
      ? `Power: ${ts.raw}\n${bits.join("\n")}`
      : `Power OK (${ts.raw})`;
    
    if (ts.uv_now && !window._uvToastShown) {
      window._uvToastShown = true;
      toast("⚡ Under-voltage detected — check power supply", "warn");
    } else if (!ts.uv_now) {
      window._uvToastShown = false;
    }
  } else if (d.pi_voltage != null) {
    
    const el = document.getElementById("s-volt");
    el.textContent = d.pi_voltage.toFixed(4) + "V";
    el.className   = "sv" + (d.pi_voltage < 0.82 ? " warn" : " ok");
    el.title       = "Core voltage (internal) — not supply voltage";
  }

  const rb = document.getElementById("restart-banner");
  if (rb) rb.classList.toggle("show", !!d.needs_restart);
}

function portBadge(port, proto) {
  const conflicts = window._portConflicts || {};
  const key       = `${proto}:${port}`;
  const span      = document.createElement("span");
  if (conflicts[key]) {
    const procs = conflicts[key].map(p => `${p.process}(${p.pid})`).join(", ");
    span.className = "pc-dup";
    span.textContent = "[DUP]";
    span.title = `Duplicate: ${procs}`;
  } else {
    span.className = "pc-ok";
    span.textContent = "[OK]";
    span.title = "No other process is bound to this port/protocol";
  }
  return span;
}

function renderUptime() {
  if (!_uptimeBase) return;
  const elapsed = Math.floor((Date.now() - _uptimeBase.at) / 1000);
  const total   = _uptimeBase.s + elapsed;
  const h  = Math.floor(total / 3600);
  const m  = Math.floor((total % 3600) / 60);
  const s  = total % 60;
  document.getElementById("hdr-uptime").textContent =
    "UP " + h + ":" + String(m).padStart(2,"0") + ":" + String(s).padStart(2,"0");
}


window.loadTab_overview = function() { loadOverview(); };

async function loadOverview() {
  const d = await api("/api/overview");
  if (!d) return;
  renderOverview(d.groups);
}

function renderOverview(groups) {
  const container = document.getElementById("ov-content");
  if (!container) return;

  Array.from(container.querySelectorAll(".ov-card")).forEach(el => el.remove());
  const loading = document.getElementById("ov-loading");
  if (loading) loading.style.display = "none";

  if (!groups || !groups.length) {
    if (loading) { loading.textContent = "No services configured."; loading.style.display = "flex"; }
    return;
  }

  groups.forEach(grp => {
    const card = document.createElement("div");
    card.className = "ov-card";

    const hdr = document.createElement("div");
    hdr.className = "ov-card-hdr ov-hdr-grid";
    hdr.innerHTML =
      `<span></span>` +
      `<span class="ov-card-title">${esc(grp.group)}</span>` +
      `<span class="ov-hdr-owner">Owner</span>` +
      `<span class="ov-hdr-mode">Perms</span>` +
      `<span class="ov-hdr-status">Status</span>` +
      `<span class="ov-hdr-port">Port</span>` +
      `<span></span>` +
      `<span></span>`;
    card.appendChild(hdr);

    grp.services.forEach(svc => renderOvRow(card, svc));

    container.insertBefore(card, document.getElementById("ov-global-bar"));
  });
}

function renderOvRow(card, svc) {
  const row = document.createElement("div");
  const ni  = svc.state === "not-inst";
  row.className = "ov-row" + (ni ? " not-inst" : "");

  const dot = dotEl(svc.state, svc.enabled);

  const name = document.createElement("a");
  name.className = "ov-name" + (ni ? " ni" : "");
  name.textContent = svc.unit.replace(".service", "");
  if (!ni) {
    name.href = "#";
    name.onclick = e => {
      e.preventDefault();
      _dpOriginTab = "overview";
      switchTab("services", "0,255,229");
      if (typeof openServicePanel === "function") openServicePanel(svc.unit, svc.desc);
    };
  }

  const ownerEl = _ovOwnerCell(svc);
  const modeEl   = _ovModeCell(svc);

  const state = document.createElement("span");
  state.className = "ov-state " + stateClass(svc.state);
  state.textContent = svc.state;

  const portEl = document.createElement("span");
  portEl.className = "ov-port";
  if (svc.nr > 0) {
    portEl.className = "ov-nr" + (svc.nr > 3 ? " nr-warn" : "");
    portEl.textContent = `NR:${svc.nr}${svc.nr > 3 ? "⚠" : ""}`;
  } else if (svc.port && svc.port !== "-") {
    portEl.textContent = `:${svc.port}/${svc.proto}`;
  }

  const badgeEl = document.createElement("span");
  if (svc.state === "active" && svc.port && svc.port !== "-" && svc.port !== "parse") {
    const b = portBadge(svc.port, svc.proto || "tcp");
    badgeEl.className   = b.className;
    badgeEl.textContent = b.textContent;
    if (b.title) badgeEl.title = b.title;
  } else {
    badgeEl.className = "pc-empty";
  }

  const btns = document.createElement("div");
  btns.className = "ov-btns";
  if (!ni) {
    ovBtns(svc).forEach(b => btns.appendChild(b));
  }

  row.appendChild(dot);
  row.appendChild(name);
  row.appendChild(ownerEl);
  row.appendChild(modeEl);
  row.appendChild(state);
  row.appendChild(portEl);
  row.appendChild(badgeEl);
  row.appendChild(btns);
  card.appendChild(row);
}

function _ovSecurityJump(checkId) {
  if (!_enabledTabSet.has("security")) return;
  switchTab("security", "255,90,120");
  setTimeout(() => {
    if (typeof secToggle === "function" && !_secOpen.has(checkId + ":why")) {
      secToggle(checkId, "why");
    }
    document.getElementById("sec-row-" + checkId)
            ?.scrollIntoView({block: "center", behavior: "smooth"});
  }, 350);
}

function _ovWireSecurityJump(el, checkId, why) {
  if (!_enabledTabSet.has("security")) return;
  el.classList.add("sec-link");
  el.title = (el.title ? el.title + "\n\n" : "") + why;
  el.onclick = e => { e.preventDefault(); e.stopPropagation(); _ovSecurityJump(checkId); };
}

function _ovOwnerCell(svc) {
  const el = document.createElement("span");
  el.className = "ov-owner";
  el.textContent = svc.owner || "—";
  if (!svc.installed || svc.owner_source === "none") {
    el.title = "not installed";
    return el;
  }
  const srcTxt = svc.owner_source === "running"    ? "running as"
               : svc.owner_source === "configured" ? "configured User="
               :                                     "no User= set — systemd runs it as root";
  const bits = [`${svc.owner} — ${srcTxt}`];
  if (svc.owner_config) bits.push(`systemd User=${svc.owner_config}`);
  if (svc.owner_group)  bits.push(`Group=${svc.owner_group}`);

  if (svc.owner_is_root && svc.owner_exempt) {
    el.classList.add("own-ok");
    bits.push("root by design for this unit");
  } else if (svc.owner_is_root) {
    el.classList.add("own-warn");
    bits.push("this unit does not require root");
  }
  el.title = bits.join("; ");
  if (svc.owner_is_root && !svc.owner_exempt) {
    _ovWireSecurityJump(el, "service_nonroot",
                         "Click for the Security tab's explanation");
  }
  return el;
}

function _ovModeCell(svc) {
  const el = document.createElement("span");
  el.className = "ov-mode";
  if (!svc.installed) { el.textContent = "—"; el.title = "not installed"; return el; }
  el.textContent = svc.mode || "—";

  const lines = [];
  if (svc.unit_path) {
    lines.push(`unit  ${svc.mode || "?"}  ${svc.unit_owner || "?"}  ${svc.unit_path}`);
  } else {
    lines.push("unit  (FragmentPath not reported)");
  }
  if (svc.bin_path) {
    lines.push(`bin   ${svc.bin_mode || "?"}  ${svc.bin_owner || "?"}  ${svc.bin_path}`);
  }
  if (Array.isArray(svc.perm_reasons) && svc.perm_reasons.length) {
    lines.push("", ...svc.perm_reasons);
  }
  if      (svc.perm_verdict === "fail") el.classList.add("perm-fail");
  else if (svc.perm_verdict === "warn") el.classList.add("perm-warn");
  el.title = lines.join("\n");
  if (svc.perm_verdict === "fail" || svc.perm_verdict === "warn") {
    _ovWireSecurityJump(el, "unit_file_perms",
                         "Click for the Security tab's explanation");
  }
  return el;
}

function ovBtns(svc) {
  const make = (label, cls, action) => {
    const b = document.createElement("button");
    b.className = `btn ${cls} btn-sm`;
    b.textContent = label;
    b.onclick = () => svcAction(action, svc.unit, b);
    return b;
  };
  const editBtn = () => {
    const b = document.createElement("button");
    b.className = "btn btn-muted btn-sm";
    b.textContent = "Edit";
    b.onclick = e => { e.stopPropagation(); openUnitFileEditor(svc.unit); };
    return b;
  };
  switch (svc.state) {
    case "active":
      return [make("↺ Restart", "btn-blue",  "restart"),
              make("■ Stop",    "btn-amber",  "stop"),
              make("☠ Kill",   "btn-red",    "kill_pid"),
              editBtn()];
    case "failed":
      return [make("▶ Start",  "btn-green",  "start"),
              make("✕ Reset",  "btn-amber",  "reset_failed"),
              editBtn()];
    case "inactive":
      return [make("▶ Start",  "btn-green",  "start"),
              editBtn()];
    default:
      return [];
  }
}

function _svcPollAfterRestart() {
  [3000, 8000, 16000, 28000].forEach(delay => setTimeout(loadOverview, delay));
}

async function svcAction(action, unit, btn) {
  
  if (action === "stop") {
    if (!await confirm(`Stop  ${unit}?`)) return;
  } else if (action === "kill_pid") {
    if (!await confirm(`☠ Kill PID for ${unit}?\n\nSends SIGKILL immediately — no clean shutdown.`)) return;
  } else if (action === "disable") {
    if (!await confirm(`Disable  ${unit}  at boot?`)) return;
  } else if (action === "mask") {
    if (!await confirm(`Mask  ${unit}?  This prevents it from starting.`)) return;
  }
  if (btn) btn.disabled = true;
  const d = await api("/api/svc", "POST", {action: action, unit: unit});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    if (d.async) { _svcPollAfterRestart(); } else { setTimeout(loadOverview, 800); }
  }
}

function dotColorClass(state, enabled) {
  if (enabled === "masked") return "dot-fail";
  return {
    "active":   "dot-on",
    "failed":   "dot-fail",
    "inactive": "dot-warn",
    "not-inst": "dot-off",
    "unknown":  "dot-unknown",
  }[state] || "dot-unknown";
}

function dotEl(state, enabled) {
  const d = document.createElement("span");
  d.className = "dot " + dotColorClass(state, enabled);
  return d;
}

function stateClass(state) {
  return {"active":"st-active","failed":"st-failed",
          "inactive":"st-inactive","not-inst":"st-notinst",
          "unknown":"st-unknown"}[state] || "st-unknown";
}

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

let _s3Scope  = "active";
let _s3Filter = "";
let _s3FilterTimer = null;

function openServicePanel(unit, desc) {
  openPanel(unit, desc || "");
}

window.loadTab_services = function() {
  if (!_enabledTabSet.has("services")) return;
  clearInterval(_s3RefreshTimer);
  loadGeneralList();
  _s3RefreshTimer = setInterval(loadGeneralList, 30_000);
}


let _cfg_nr_warn = "3";
let _cfg_nr_crit = "10";

let _dpUnit       = "";
let _dpActiveView = "";
let _dpOriginTab  = "";
const TAB_RGB = {
  overview:"0,255,229", services:"0,255,229", ports:"34,212,255",
  firewall:"255,170,34", journal:"212,102,255", asldvs:"255,61,90",
  reg:"120,180,255", phone:"0,255,176",
  tune:"255,68,204", hardware:"0,200,120", net:"64,224,208", dvsm:"255,170,34",
  stfu:"0,191,255", zello:"255,140,0", sdcard:"180,140,255", edit:"255,208,64"
};

function dpUnit() { return _dpUnit; }

let _dpBodyDefault = null;
function _dpRestoreBody() {
  const body = document.getElementById("dpanel-body");
  if (!body) return;
  if (_dpBodyDefault === null) { _dpBodyDefault = body.innerHTML; return; }
  if (body.dataset.custom) {
    body.innerHTML = _dpBodyDefault;
    delete body.dataset.custom;
  }
}

async function openPanel(unit, desc) {
  _dpRestoreBody();
  _dpUnit       = unit;
  _dpActiveView = "";

  document.getElementById("dpanel-unit").textContent  = unit.replace(".service","");
  document.getElementById("dpanel-desc").textContent  = desc || "Loading…";
  document.getElementById("dpanel-badges").innerHTML  = "";
  document.getElementById("dpanel-output").innerHTML  =
    '<span class="dp-out-dim">Loading…</span>';
  dpSetReload(false);

  document.getElementById("dpanel-overlay").classList.add("open");
  document.getElementById("dpanel").classList.add("open");

  await dpRefreshHeader();
  dpLoadStatus();
}

function closePanel() {
  document.getElementById("dpanel-overlay").classList.remove("open");
  document.getElementById("dpanel").classList.remove("open");
  _dpUnit       = "";
  _dpActiveView = "";
  if (_dpOriginTab && _dpOriginTab !== "services") {
    switchTab(_dpOriginTab, TAB_RGB[_dpOriginTab]);
  }
  _dpOriginTab = "";
}

async function dpRefreshHeader() {
  if (!_dpUnit) return;
  const d = await api(`/api/services/detail?unit=${encodeURIComponent(_dpUnit)}`);
  if (!d || !d.ok) return;

  document.getElementById("dpanel-unit").textContent =
    _dpUnit.replace(".service","");
  document.getElementById("dpanel-desc").textContent = d.desc || _dpUnit;

  const accent = {
    "active":   "var(--green)",
    "failed":   "var(--red)",
    "inactive": "var(--amber)",
  }[d.state] || "var(--teal)";
  document.getElementById("dpanel").style.setProperty("--panel-accent", accent);

  const badgeEl = document.getElementById("dpanel-badges");
  badgeEl.innerHTML = "";

  const mkBadge = (text, cls) => {
    const b = document.createElement("span");
    b.className = "dpbadge " + cls;
    b.textContent = text;
    badgeEl.appendChild(b);
  };

  const stateCls = d.state === "active"  ? "dpbadge-state-active"
                 : d.state === "failed"  ? "dpbadge-state-failed"
                 : "dpbadge-state-other";
  mkBadge(d.state, stateCls);

  const enCls = d.enabled === "enabled" ? "dpbadge-enabled" : "dpbadge-disabled";
  mkBadge(d.enabled || "unknown", enCls);

  if (d.pid) mkBadge(`PID ${d.pid}`, "dpbadge-info");

  const nr = d.nrestarts || 0;
  if (nr > 0) {
    const nrCls = nr >= parseInt(_cfg_nr_crit) ? "dpbadge-crit"
                : nr >= parseInt(_cfg_nr_warn)  ? "dpbadge-warn"
                : "dpbadge-info";
    mkBadge(`NR:${nr}${nr >= parseInt(_cfg_nr_warn) ? "⚠" : ""}`, nrCls);
  }

  if (d.cpu_pct != null) mkBadge(`CPU ${d.cpu_pct}%`, "dpbadge-info");
  if (d.rss_mb  != null) mkBadge(`${d.rss_mb} MiB`,  "dpbadge-info");

  if (d.installed && d.owner) {
    const ownCls = (d.owner_is_root && !d.owner_exempt) ? "dpbadge-warn"
                 : d.owner_is_root                       ? "dpbadge-info"
                 :                                         "dpbadge-enabled";
    mkBadge(`user ${d.owner}`, ownCls);
  }
  if (d.perm_verdict === "fail")      mkBadge("perms", "dpbadge-crit");
  else if (d.perm_verdict === "warn") mkBadge("perms", "dpbadge-warn");

  dpSetReload(!!d.can_reload);

  dpRenderOwnZone(d);
  dpRenderPinZone(_dpUnit);
}

function dpRenderOwnZone(d) {
  const host = document.getElementById("dp-own-zone");
  if (!host) return;
  if (!d.installed) { host.innerHTML = ""; return; }

  const row = (lbl, val, cls) =>
    `<div class="dp-own-row"><span class="dp-own-lbl">${_esc(lbl)}</span>` +
    `<span class="dp-own-val ${cls || ""}">${_esc(val)}</span></div>`;

  const srcTxt = d.owner_source === "running"    ? "running as"
               : d.owner_source === "configured" ? "configured User="
               :                                   "no User= set";
  const ownCls = (d.owner_is_root && !d.owner_exempt) ? "warn" : "";

  let html = `<div class="dpzone-lbl">Ownership &amp; permissions</div>`;
  html += row("Runs as", `${d.owner}  (${srcTxt})`, ownCls);
  html += row("systemd", `User=${d.owner_config || "(unset)"}` +
                          `  Group=${d.owner_group || "(unset)"}`, "");
  if (d.owner_is_root && d.owner_exempt) {
    html += row("", "root by design for this unit", "");
  }

  const f = d.unit_file || {}, b = d.exec_file || {};
  if (f.path) {
    html += row("Unit file", f.exists
      ? `${f.mode}  ${f.owner}:${f.group}  ${f.path}`
      : `${f.path}  (not readable)`,
      f.exists && (f.world_writable ? "fail" : (f.group_writable || !f.root_owned) ? "warn" : ""));
  }
  if (b.path) {
    html += row("ExecStart", b.exists
      ? `${b.mode}  ${b.owner}:${b.group}  ${b.path}`
      : `${b.path}  (not readable)`,
      b.exists && (b.world_writable ? "fail" : (b.group_writable || !b.root_owned) ? "warn" : ""));
  }
  (d.perm_reasons || []).forEach(r => { html += row("", r, "warn"); });

  host.innerHTML = html;
}

function dpSetReload(canReload) {
  const btn = document.getElementById("dp-btn-reload");
  if (!btn) return;
  btn.disabled = !canReload;
  btn.title    = canReload ? "" : "This unit does not support reload";
  btn.style.opacity = canReload ? "1" : "0.35";
}

async function dpRenderPinZone(unit) {
  const row = document.getElementById("dp-pin-row");
  if (!row) return;
  row.innerHTML = '<span style="font-family:var(--sans);font-size:var(--fs-sm);color:#fff">…</span>';

  const d = await api("/api/pinned");
  if (!d) { row.innerHTML = ""; return; }

  const isPinned = d.pinned_units.includes(unit);
  const groups   = d.groups;

  row.innerHTML = "";

  if (isPinned) {
    const btn = document.createElement("button");
    btn.className = "btn btn-red btn-sm";
    btn.textContent = "✕ Unpin";
    btn.onclick = () => dpUnpinService(unit, btn);
    row.appendChild(btn);
    const note = document.createElement("span");
    note.style.cssText = "font-family:var(--sans);font-size:var(--fs-xs);color:#fff;margin-left:.4rem";
    note.textContent = "Remove from pinned list";
    row.appendChild(note);
  } else {
    const sel = document.createElement("select");
    sel.title = "Choose group";
    groups.forEach(g => {
      const opt = document.createElement("option");
      opt.value = g; opt.textContent = g;
      sel.appendChild(opt);
    });
    const newOpt = document.createElement("option");
    newOpt.value = "__new__"; newOpt.textContent = "＋ New group…";
    sel.appendChild(newOpt);

    const btn = document.createElement("button");
    btn.className = "btn btn-lime btn-sm";
    btn.style.cssText = "color:var(--lime);border-color:var(--lime-dim)";
    btn.textContent = "📌 Pin";
    btn.onclick = () => dpPinService(unit, sel, btn);

    row.appendChild(sel);
    row.appendChild(btn);
  }
}

async function dpPinService(unit, sel, btn) {
  let group = sel.value;
  if (group === "__new__") {
    group = prompt("New group name:");
    if (!group || !group.trim()) return;
    group = group.trim();
  }
  if (btn) btn.disabled = true;
  const d = await api("/api/pinned", "POST", {action: "pin", unit, group});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Pinned" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    dpRenderPinZone(unit);
    if (typeof loadOverview === "function") setTimeout(loadOverview, 400);
  }
}

async function dpUnpinService(unit, btn) {
  if (!await confirm(`Remove  ${unit}  from the pinned list?`)) return;
  if (btn) btn.disabled = true;
  const d = await api("/api/pinned", "POST", {action: "unpin", unit});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Unpinned" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    dpRenderPinZone(unit);
    if (typeof loadOverview === "function") setTimeout(loadOverview, 400);
  }
}

async function dpSvcAction(action, unit) {
  
  if (action === "stop") {
    if (!await confirm(`Stop  ${unit || _dpUnit}?`)) return;
  } else if (action === "disable") {
    if (!await confirm(`Disable  ${unit || _dpUnit}  at boot?`)) return;
  } else if (action === "mask") {
    if (!await confirm(`Mask  ${unit || _dpUnit}?  This prevents it from starting.`)) return;
  }
  const url  = "/api/svc";
  const body = action === "reload_daemon"
    ? {action: "reload_daemon"}
    : {action: action, unit: unit};

  const d = await api(url, "POST", body);
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");

  if (d.ok) {
    if (d.async) {
      [3000, 8000, 16000, 28000].forEach(delay => setTimeout(async () => {
        await dpRefreshHeader();
        if (typeof loadOverview === "function") loadOverview();
      }, delay));
      [3500, 8500, 16500, 28500].forEach(delay => setTimeout(() => dpLoadStatus(), delay));
    } else {
      setTimeout(async () => {
        await dpRefreshHeader();
        if (typeof loadOverview === "function") loadOverview();
      }, 700);
      setTimeout(() => dpLoadStatus(), 1200);
    }
  }
}

async function dpLoadStatus() {
  if (!_dpUnit) return;
  _dpActiveView = "status";

  const out = document.getElementById("dpanel-output");
  out.innerHTML = '<span class="dp-out-dim">Loading…</span>';

  const d = await api(
    `/api/services/detail?unit=${encodeURIComponent(_dpUnit)}&view=status&lines=50`
  );
  if (!d || !d.ok) {
    out.innerHTML = `<span class="dp-out-fail">Error: ${esc(d?.message || "request failed")}</span>`;
    return;
  }
  out.innerHTML = "";
  (d.output || "").split("\n").forEach(line => {
    const div = document.createElement("div");
    const lower = line.toLowerCase();
    if (lower.includes("failed") || lower.includes("error") || lower.includes("fatal")) {
      div.className = "dp-out-fail";
    } else if (lower.includes("warn") || lower.includes("notice")) {
      div.className = "dp-out-warn";
    } else if (lower.includes("started") || lower.includes("active") ||
               lower.includes("loaded") || lower.match(/\bok\b/)) {
      div.className = "dp-out-ok";
    } else {
      div.className = "dp-out-dim";
    }
    div.textContent = line || "\u00a0";
    out.appendChild(div);
  });
}

function dotClass(state, enabled) {
  return dotColorClass(state, enabled);
}

let _ptProto      = "both";

window.loadTab_ports = function() {
  if (!_enabledTabSet.has("ports")) return;
  clearInterval(_ptRefreshTimer);
  loadPorts();
  _ptRefreshTimer = setInterval(loadPorts, 15_000);
};

let _fwBackend = "none";
let _fwCockpitInstalled = false;
let _fwRawOpen = false;
let _fwManualOpen = false;

window.loadTab_firewall = function() { loadFirewall(); };

let _fwRules = [];


let _jpUnit  = "";
let _jpLines = 200;
let _jpRaw   = "";
let _jpFilteredText = "";

window.loadTab_journal = function() { loadJournalList(); };

async function loadJournalList() {
  const d = await api("/api/journal/list");
  if (!d) return;
  renderJournalList(d.services || []);
}

function renderJournalList(services) {
  const body = document.getElementById("jl-body");
  if (!body) return;
  body.innerHTML = "";

  if (!services.length) {
    body.innerHTML =
      '<div class="stub-panel" style="min-height:60px">No services found.</div>';
    return;
  }

  services.forEach(svc => {
    const row = document.createElement("div");
    row.className = "jl-row";
    row.onclick   = e => {
      if (e.target.classList.contains("jl-btn")) return;
      openJournalPopup(svc.unit);
    };

    row.innerHTML =
      `<span class="dot ${dotClass(svc.state, svc.enabled)}"></span>` +
      `<span class="jl-name">${esc(svc.unit.replace(".service",""))}</span>` +
      `<span class="jl-state ${stateClass(svc.state)}">${esc(svc.state)}</span>` +
      `<button class="jl-btn" onclick="openJournalPopup('${esc(svc.unit)}')">▤ Journal</button>`;
    body.appendChild(row);
  });
}

async function openJournalPopup(unit) {
  _jpUnit = unit;
  const title = document.getElementById("jp-title");
  if (title) title.textContent = `▤ ${unit.replace(".service","")} — Journal`;

  document.getElementById("jp-overlay").classList.add("open");
  document.getElementById("jp-grep").value = "";

  jpSetLinesUI(_jpLines);

  await jpRefresh();
}

function closeJournalPopup() {
  document.getElementById("jp-overlay").classList.remove("open");
  _jpUnit = "";
}

function jpOverlayClick(e) {
  if (e.target === document.getElementById("jp-overlay")) closeJournalPopup();
}

async function jpCopy() {
  if (!_jpFilteredText) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(_jpFilteredText);
}

async function jpRefresh() {
  if (!_jpUnit) return;
  const body = document.getElementById("jp-body");
  if (body) body.textContent = "Loading…";

  const d = await api(
    `/api/journal/fetch?unit=${encodeURIComponent(_jpUnit)}&lines=${_jpLines}`
  );
  if (!d) {
    if (body) body.innerHTML = '<span class="jp-err">Request failed</span>';
    return;
  }
  if (!d.ok) {
    if (body) body.innerHTML =
      `<span class="jp-err">${esc(d.message || "Journal fetch failed")}</span>`;
    _jpRaw = "";
    return;
  }

  _jpRaw = d.output || "";
  jpApplyGrep();
}

function jpApplyGrep() {
  const term = (document.getElementById("jp-grep")?.value || "").trim();
  const body = document.getElementById("jp-body");
  if (!body) return;

  const lines = _jpRaw.split("\n");
  const filtered = term
    ? lines.filter(l => l.toLowerCase().includes(term.toLowerCase()))
    : lines;

  if (!filtered.length || (filtered.length === 1 && !filtered[0])) {
    body.innerHTML = '<span class="jp-dim">-- No entries --</span>';
    _jpFilteredText = "";
    return;
  }

  _jpFilteredText = filtered.join("\n");
  body.innerHTML = "";
  filtered.forEach(line => {
    const div = document.createElement("div");
    const lower = line.toLowerCase();
    if (lower.includes("error") || lower.includes("failed") || lower.includes("fatal")) {
      div.className = "jp-err";
    } else if (lower.includes("warn") || lower.includes("notice")) {
      div.className = "jp-warn";
    } else if (lower.includes("started") || lower.includes("active") ||
               lower.includes("loaded") || lower.match(/\bok\b/)) {
      div.className = "jp-ok";
    } else if (line.startsWith("--")) {
      div.className = "jp-dim";
    } else {
      div.className = "jp-ts";
    }
    div.textContent = line || "\u00a0";
    body.appendChild(div);
  });

  body.scrollTop = body.scrollHeight;
}

function jpSetLines(n) {
  _jpLines = n;
  jpSetLinesUI(n);
  jpRefresh();
}

function jpSetLinesUI(n) {
  const map = {50: "jp-ln-50", 200: "jp-ln-200", 2000: "jp-ln-all"};
  Object.entries(map).forEach(([k, id]) => {
    const btn = document.getElementById(id);
    if (btn) btn.classList.toggle("on", parseInt(k) === n);
  });
}

let _jpGrepTimer = null;
function jpGrepChanged() {
  clearTimeout(_jpGrepTimer);
  _jpGrepTimer = setTimeout(jpApplyGrep, 250);
}

async function jpSvcAction(action) {
  if (!_jpUnit) return;
  const d = await api("/api/svc", "POST", {action, unit: _jpUnit});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    setTimeout(jpRefresh, 1500);
    if (typeof loadJournalList === "function") setTimeout(loadJournalList, 1000);
  }
}


let _edDirty = false;

window.loadTab_edit = function() { edReload(); edAslDvsLoad(); };

let _edAslOpen = false;

let _edPinnedOpen = false;

async function edAslDvsLoad() {
  if (!_edAslOpen) return;

  const da = await api("/api/asterisk/files?all=1");
  if (da) renderAstFiles(da.files || [], da.dir || "/etc/asterisk",
                          "ed-ast-file-body", true);
  const dm = await api("/api/allmon3/files?all=1");
  if (dm) renderAllmon3Files(dm.files || [], "ed-allmon3-file-body", true);
  const dd = await api("/api/dvswitch/files?all=1");
  if (dd) renderDvsFiles(dd.files || [], "ed-dvs-file-body", true);

  const body = document.getElementById("ed-asl-body");
  if (body && _edAslOpen) body.style.maxHeight = "none";
}

async function edToggleFileHidden(filename, isHidden) {
  const cfg = await api("/api/config");
  if (!cfg || !cfg.ok) { toast("Failed to load config", "err"); return; }

  const current = new Set(
    (cfg.asldvs?.hidden_files || "").split(",").map(s => s.trim()).filter(Boolean)
  );

  if (isHidden) {
    current.delete(filename);
  } else {
    current.add(filename);
  }

  const d = await api("/api/config", "POST",
    {"asldvs.hidden_files": [...current].join(",")});
  if (!d || !d.ok) {
    toast(d?.message || "Save failed", "err"); return;
  }

  toast(isHidden ? `${filename} shown` : `${filename} hidden`, "ok", 2000);

  edAslDvsLoad();
  if (typeof loadAstFiles     === "function") loadAstFiles();
  if (typeof loadAllmon3Files === "function") loadAllmon3Files();
  if (typeof loadDvsFiles     === "function") loadDvsFiles();
}

const ED_FIELDS = [
  {id: "ed-callsign",  key: "identity.callsign"},
  {id: "ed-node",      key: "identity.node"},
  {id: "ed-label",     key: "identity.label"},
  {id: "ed-port",      key: "server.port"},
  {id: "ed-host",      key: "server.host"},
  {id: "ed-cpu-warn",  key: "thresholds.cpu_warn_pct"},
  {id: "ed-rss-warn",  key: "thresholds.rss_warn_mb"},
  {id: "ed-nr-warn",   key: "thresholds.nr_warn"},
  {id: "ed-nr-crit",   key: "thresholds.nr_crit"},
];

const ED_LOCKED_TABS = ["overview", "edit"];

function edCountPinned() {
  const ta  = document.getElementById("ed-pinned");
  const cnt = document.getElementById("ed-pinned-count");
  if (!ta || !cnt) return;
  const n = ta.value.split("\n").filter(l => {
    const t = l.trim();
    return t && !t.startsWith("#") && !t.startsWith("__GROUP__");
  }).length;
  cnt.textContent = `${n} service entr${n === 1 ? "y" : "ies"}`;
}

let _pageVisible = document.visibilityState === "visible";

document.addEventListener("visibilitychange", () => {
  if (_pausedByNavigation) return;
  
  _pageVisible = document.visibilityState === "visible";
  if (_pageVisible) {
    startStatusPolling();
    console.info("[sysmon] Polling resumed (page visible)");
  } else {
    stopStatusPolling();
    stopTabPolling("ports");
    stopTabPolling("services");
    console.info("[sysmon] Polling paused (page hidden)");
  }
});

document.addEventListener("DOMContentLoaded", () => {
  const ta = document.getElementById("ed-pinned");
  if (ta) ta.addEventListener("input", edCountPinned);
});

async function _copyWithVerify(src) {
  let wrote = false;
  try {
    await navigator.clipboard.writeText(src);
    wrote = true;
  } catch {
    const tmp = document.createElement("textarea");
    tmp.value = src;
    tmp.style.position = "fixed";
    tmp.style.left = "-9999px";
    tmp.setAttribute("readonly", "");
    document.body.appendChild(tmp);
    tmp.focus();
    tmp.setSelectionRange(0, tmp.value.length);
    try {
      document.execCommand("copy");
      wrote = true;
    } catch { wrote = false; }
    document.body.removeChild(tmp);
  }
  if (!wrote) { toast("Copy failed", "err"); return; }

  try {
    const check = await navigator.clipboard.readText();
    if (check === src) {
      toast("Copied ✓", "ok", 2000);
    } else {
      await alertModal(
        `⚠ Clipboard copy may be incomplete (${check.length} of ${src.length} ` +
        `characters). This can happen on some mobile browsers with large ` +
        `files — try again, or use a desktop browser if this persists.`
      );
    }
  } catch {
    toast("Copied — could not confirm on this browser", "info", 3000);
  }
}

let _modalResolve = null;

function confirm(msg) {
  
  return new Promise(resolve => {
    _modalResolve = resolve;
    document.getElementById("modal-msg").textContent = msg;
    document.getElementById("modal-overlay").classList.add("open");
  });
}

function modalCancel() {
  document.getElementById("modal-overlay").classList.remove("open");
  _resetModalAlertUI();
  if (_modalResolve) { _modalResolve(false); _modalResolve = null; }
}

function modalConfirm() {
  document.getElementById("modal-overlay").classList.remove("open");
  _resetModalAlertUI();
  if (_modalResolve) { _modalResolve(true); _modalResolve = null; }
}

let _modalIsAlert = false;

function alertModal(msg) {
  _modalIsAlert = true;
  const cancelBtn = document.querySelector("#modal-btns .btn-muted");
  const okBtn = document.getElementById("modal-ok");
  if (cancelBtn) cancelBtn.style.display = "none";
  if (okBtn) okBtn.textContent = "OK";
  return confirm(msg);
}

function _resetModalAlertUI() {
  if (!_modalIsAlert) return;
  const cancelBtn = document.querySelector("#modal-btns .btn-muted");
  const okBtn = document.getElementById("modal-ok");
  if (cancelBtn) cancelBtn.style.display = "";
  if (okBtn) okBtn.textContent = "Confirm";
  _modalIsAlert = false;
}
document.addEventListener("DOMContentLoaded", () => {
  const ok = document.getElementById("modal-ok");
  if (ok) ok.addEventListener("click", modalConfirm);
  const ov = document.getElementById("modal-overlay");
  if (ov) ov.addEventListener("click", e => {
    if (e.target === ov) modalCancel();
  });
});

async function postAction(url, action, btn, confirmMsg) {
  if (confirmMsg) {
    const ok = await confirm(confirmMsg);
    if (!ok) return;
  }
  if (btn) btn.disabled = true;
  const d = await api(url, "POST", {action: action});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
}

let _pausedByNavigation = false;

function pauseAllPolling() {
  _pausedByNavigation = true;
  sessionStorage.setItem("sysmon_paused_by_nav", "1");
  stopStatusPolling();
  stopTabPolling("ports");
  stopTabPolling("services");
  stopTabPolling("sdcard");
  stopTabPolling("phone");
  console.info("[sysmon] All polling paused (navigating to dashboard)");
}

function resumeAllPolling() {
  _pausedByNavigation = false;
  startStatusPolling();
  console.info("[sysmon] All polling resumed");
}


let _ufUnit = "";

async function openUnitFileEditor(unit) {
  _ufUnit = unit;

  document.getElementById("uf-title").textContent    = `✎ ${unit.replace(".service","")}`;
  document.getElementById("uf-path").textContent     = "Loading…";
  document.getElementById("uf-textarea").value       = "";
  document.getElementById("uf-status").textContent   = "";
  document.getElementById("uf-promoted-bar").classList.remove("show");
  document.getElementById("uf-save-btn").disabled    = true;
  document.getElementById("uf-restart-btn").disabled = true;
  document.getElementById("uf-overlay").classList.add("open");

  const d = await api(`/api/unit_file?unit=${encodeURIComponent(unit)}`);
  if (!d || !d.ok) {
    document.getElementById("uf-path").textContent   = d?.message || "Failed to load";
    document.getElementById("uf-textarea").value     = "";
    ufSetStatus(d?.message || "Error loading unit file", false);
    return;
  }

  document.getElementById("uf-path").textContent     = d.read_path;
  document.getElementById("uf-textarea").value       = d.content;
  document.getElementById("uf-save-btn").disabled    = !d.writable;
  document.getElementById("uf-restart-btn").disabled = false;
  ufSetStatus(d.writable ? "" : "Read-only (not running as root)");

  if (d.promoted) {
    document.getElementById("uf-promoted-bar").classList.add("show");
    document.getElementById("uf-path").textContent =
      `${d.path}  (override — original: ${d.read_path})`;
  }
}

function closeUnitFileEditor() {
  document.getElementById("uf-overlay").classList.remove("open");
  const rb = document.getElementById("uf-restart-btn");
  if (rb) rb.style.display = "";
  _ufUnit = "";
}

function ufOverlayClick(e) {
  if (e.target === document.getElementById("uf-overlay")) closeUnitFileEditor();
}

async function ufCopy() {
  const ta = document.getElementById("uf-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

function ufSetStatus(msg, ok) {
  const el = document.getElementById("uf-status");
  if (!el) return;
  el.textContent = msg;
  el.style.color = ok === true  ? "var(--green)"
                 : ok === false ? "var(--red)"
                 : "#3a5278";
}

async function _ufSaveOrig() {
  if (!_ufUnit) return;
  const content = document.getElementById("uf-textarea").value;
  const btn     = document.getElementById("uf-save-btn");
  if (btn) btn.disabled = true;
  ufSetStatus("Saving…");

  const d = await api("/api/unit_file", "POST", {unit: _ufUnit, content});
  if (btn) btn.disabled = false;

  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Save failed", false);
    toast(d?.message || "Save failed", "err");
    return;
  }

  const detail = d.reload_ok ? "daemon-reload OK" : "saved (daemon-reload failed)";
  ufSetStatus(`Saved ✓  —  ${detail}`, d.reload_ok);
  toast(d.message, d.reload_ok ? "ok" : "err");

  if (d.path) document.getElementById("uf-path").textContent = d.path;
  document.getElementById("uf-promoted-bar").classList.remove("show");
}

async function ufRestart() {
  if (!_ufUnit) return;
  if (!await confirm(`Restart ${_ufUnit} to apply unit file changes?`)) return;
  const d = await api("/api/svc", "POST", {action: "restart", unit: _ufUnit});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Restarted" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) { d.async ? _svcPollAfterRestart() : setTimeout(loadOverview, 800); }
}

async function ufReloadDaemon() {
  ufSetStatus("Reloading daemon…");
  const d = await api("/api/svc", "POST", {action: "reload_daemon"});
  if (!d) { ufSetStatus("Server unreachable", false); return; }
  ufSetStatus(d.message || (d.ok ? "Daemon reloaded" : "Failed"), d.ok);
}

window.loadTab_asldvs = function() { loadAstFiles(); loadAllmon3Files(); loadDvsFiles(); loadDstarGw(); };

// v6.13.66: D-Star -- ircDDBGateway card (read-only checks on /etc/ircddbgateway
// for the dashboard's gateway linking).  Edit opens the DVSwitch file editor.
let _dstarGw = null;
async function loadDstarGw() {
  const d = await api("/api/dstar-gw");
  if (!d) return;
  _dstarGw = d;
  _dvsmSetBadge("dstargw-badge", d.status, d.badge);
  _renderCompatTable("dstargw-body", d.checks || []);
}
async function dstarGwRestart() {
  if (!await confirm("Restart ircddbgatewayd? Any D-Star link drops.")) return;
  const d = await api("/api/dstar-gw", "POST", {action: "restart"});
  if (!d || !d.ok) { toast(d?.message || "Restart failed", "err"); return; }
  toast("ircddbgatewayd restarted", "ok");
  setTimeout(loadDstarGw, 1500);
}
function dstarGwEdit() {
  if (_dstarGw && _dstarGw.present === false) { toast("/etc/ircddbgateway not found", "warn"); return; }
  openDvsEditor("ircddbgateway");
}
function dstarGwCopy(btn) {
  if (!_dstarGw) return;
  const lines = [`D-Star — ircDDBGateway (${_dstarGw.path}): ${_dstarGw.badge}`];
  (_dstarGw.checks || []).forEach(c => {
    lines.push(`[${String(c.status || "").toUpperCase()}] ${c.enables}: ${c.key}`);
    if (c.fix) lines.push(`    -> ${c.fix}`);
  });
  dvsmCopy(btn, lines.join("\n"));
}

const _REG_HTTP_IDS = {body: "reg-http-body", meta: "reg-http-meta", status: "reg-http-status"};
const _REG_IAX_IDS  = {body: "reg-iax-body",  meta: "reg-iax-meta",  status: "reg-iax-status"};

window.loadTab_reg = async function() {
  if (!_enabledTabSet.has("reg")) return;
  const [dHttp, dIax] = await Promise.all([api("/api/reg/http"), api("/api/reg/iax")]);

  if (!dHttp || !dHttp.ok) { _regShowUnreachable(_REG_HTTP_IDS); }
  else                     { renderRegChecks(dHttp.checks, dHttp.status, _REG_HTTP_IDS); }

  if (!dIax || !dIax.ok) { _regShowUnreachable(_REG_IAX_IDS); }
  else                   { renderRegChecks(dIax.checks, dIax.status, _REG_IAX_IDS); }
};
let _phData = {};

window.phCopyCard = async function(pfx) {
  const text = phCardText(pfx);
  if (!text.trim()) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(text);
};

const _rtResult = {};
window.rtOut = async function() {
  const b = document.getElementById("rt-out-btn"); if (b) b.disabled = true;
  const box = document.getElementById("rt-out-box");
  if (box) box.innerHTML = '<div class="stub-panel" style="min-height:40px">Testing…</div>';
  const d = await api("/api/phone/routertest", "POST", {part: "out"});
  if (b) b.disabled = false;
  if (!d || !d.ok) { if (box) box.innerHTML = '<div class="stub-panel">Test failed: ' + _esc((d && d.message) || "no reply") + '</div>'; return; }
  rtChecks("rt-out-box", "out", d.checks);
};
window.rtAudio = async function() {
  const b = document.getElementById("rt-audio-btn"); if (b) b.disabled = true;
  const box = document.getElementById("rt-audio-box");
  if (box) box.innerHTML = '<div class="stub-panel" style="min-height:40px">Counting packets…</div>';
  const a = await api("/api/phone/routertest", "POST", {part: "audio"});
  await new Promise(r => setTimeout(r, 4000));
  const z = await api("/api/phone/routertest", "POST", {part: "audio"});
  if (b) b.disabled = false;
  if (!a || !a.ok || !z || !z.ok) { if (box) box.innerHTML = '<div class="stub-panel">Check failed</div>'; return; }
  const checks = [];
  if (!z.calls.length) {
    checks.push({id: "nocall", title: "Call audio", status: "info", value: "no call is up",
                 note: "Start a Test call on the dashboard Phone tab, then press Check audio now"});
  }
  z.calls.forEach(c => {
    const p = (a.calls || []).find(x => x.channel === c.channel) || c;
    const sec = Math.max(1, (z.t - a.t));
    const rx = Math.round((c.rx - p.rx) / sec), tx = Math.round((c.tx - p.tx) / sec);
    const lossy = c.rx_pct >= 5 || c.tx_pct >= 5;
    let st = "pass", note = "Audio is getting out and coming back in";
    if (rx <= 0 && tx <= 0) { st = "fail"; note = "No audio either way -- the call may be on hold or the audio ports are blocked"; }
    else if (rx <= 0) { st = "fail"; note = "Audio goes out but none comes back in -- check the router forward and Pi firewall for the audio ports"; }
    else if (tx <= 0) { st = "warn"; note = "Audio comes in but none goes out -- normal on a simplex node while nobody is talking; key up and check again"; }
    else if (lossy) { st = "warn"; note = "Packets are being lost -- expect choppy audio. Check WiFi signal and internet load"; }
    checks.push({id: "a-" + c.channel, title: c.channel + " (" + c.codec + ", up " + c.uptime + ")", status: st,
                 value: `in ${rx}/s · out ${tx}/s · lost in ${c.rx_pct}% out ${c.tx_pct}% · jitter ${c.rx_jitter}/${c.tx_jitter}`,
                 note: note});
  });
  rtChecks("rt-audio-box", "audio", checks);
};
window.rtIn = async function(start) {
  const box = document.getElementById("rt-in-box");
  if (box) box.innerHTML = '<div class="stub-panel" style="min-height:40px">Reading…</div>';
  const d = await api("/api/phone/routertest", "POST", {part: start ? "in_start" : "in"});
  if (!d || !d.ok) { if (box) box.innerHTML = '<div class="stub-panel">Check failed</div>'; return; }
  rtChecks("rt-in-box", "in", d.checks);
};

const PM_STATE = {"ready": ["pass", "READY"], "missing": ["fail", "MISSING"], "off": ["info", "OFF"],
                  "not set up": ["info", "NOT SET UP"], "asterisk down": ["warn", "ASTERISK DOWN"]};

let _pmJobTimer = null;

let _pmLast = null;

let _pmRoot = true;
const PM_ASK = {
  "conf:load":   m => `Set ${m} to load in modules.conf?\n\nsysmon backs up modules.conf first. It takes effect the next time Asterisk restarts -- use Start to load it now.`,
  "conf:noload": m => `Set ${m} to noload in modules.conf?\n\nAsterisk won't load it at the next restart. Use Stop to unload it now.`,
  "live:start":  m => `Start (load) ${m} now?`,
  "live:stop":   m => `Stop (unload) ${m} now?\n\nAnything using it stops working until it is started again.`,
};

window.loadTab_phone = async function() {
  if (!_enabledTabSet.has("phone")) return;
  const d = await api("/api/phone");
  if (!d || !d.ok) {
    ["live", "node", "nets", "hoip", "dial", "health", "mods", "calls"].forEach(p => {
      const b = phBody(p);
      if (b) b.appendChild(phEl("div", "stub-panel", "Server unreachable"));
      phSetCard(p, "info", "—", "—");
    });
    return;
  }
  _phData = d;
  phRenderAll();
  if (_phRefreshTimer) clearInterval(_phRefreshTimer);
  _phRefreshTimer = setInterval(phPollLive, 5000);
};


window.loadTab_sdcard = function() {
  if (!_enabledTabSet.has("sdcard")) return;
  loadSdHealth(); loadSdTests();
};

window.loadTab_hardware = function() { loadHardware(); };

const _hwPingCache = {};

let _hwUsbView  = "flat";
let _hwAlsaView = "playback";
let _hwDiagData = null;

const _HW_AMBE_PAIRS  = {"0403:6015": "ThumbDV"};
const _HW_FTDI_VIDS   = {"0403": true};

function _esc(s) {
  return String(s || "")
    .replace(/&/g,"&amp;")
    .replace(/</g,"&lt;")
    .replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;")
    .replace(/'/g,"&#39;");
}

async function loadAstFiles() {
  const d = await api("/api/asterisk/files");
  if (!d) return;
  renderAstFiles(d.files || [], d.dir || "/etc/asterisk");
}

async function loadDvsFiles() {
  const d = await api("/api/dvswitch/files");
  if (!d) return;
  renderDvsFiles(d.files || []);
}

function _fileCheckRows(cb, checks) {
  checks.forEach(c => {
    if (c.title.startsWith("[")) {
      const lbl = document.createElement("div");
      lbl.style.cssText =
        "font-family:var(--sans);font-size:var(--fs-xs);letter-spacing:.15em;" +
        "text-transform:uppercase;color:#fff;padding:.4rem .9rem .15rem 1.1rem;" +
        "border-top:1px solid var(--border)";
      lbl.textContent = c.title + (c.value ? "  — " + c.value : "");
      cb.appendChild(lbl);
      return;
    }

    const crow = document.createElement("div");
    crow.className = "ast-check-row";

    const title = document.createElement("span");
    title.className   = "ast-check-title";
    title.textContent = c.title;

    const val = document.createElement("span");
    val.className   = "ast-check-value";
    val.textContent = c.value || "";

    const badge = document.createElement("span");
    if (c.status === "pass") {
      badge.className = "ast-check-pass"; badge.textContent = "[PASS]";
    } else if (c.status === "fail") {
      badge.className = "ast-check-fail"; badge.textContent = "[FAIL]";
    } else if (c.status === "info") {
      badge.className = "ast-check-info"; badge.textContent = "[INFO]";
    } else {
      badge.className = "ast-check-none"; badge.textContent = "[NONE]";
    }

    crow.appendChild(title);
    crow.appendChild(val);
    crow.appendChild(badge);
    cb.appendChild(crow);

    if (c.note) {
      const nrow = document.createElement("div");
      nrow.className = "ast-check-note";
      if (c.url) {
        const a = document.createElement("a");
        a.href = c.url; a.target = "_blank"; a.rel = "noopener noreferrer";
        a.className = "ast-check-link"; a.textContent = c.note;
        nrow.appendChild(a);
      } else {
        nrow.textContent = c.note;
      }
      cb.appendChild(nrow);
    }
    if (Array.isArray(c.notes)) {
      c.notes.forEach(line => {
        const nrow = document.createElement("div");
        nrow.className   = "ast-check-note";
        nrow.textContent = line;
        cb.appendChild(nrow);
      });
    }
  });
}

function _filePortLinesEl(portLines) {
  const pl = document.createElement("div");
  pl.className = "ast-port-lines";
  let lastSection = null;
  portLines.forEach(entry => {
    const section = (typeof entry === "object") ? entry.section : "";
    const rawLine = (typeof entry === "object") ? entry.line    : entry;
    if (section && section !== lastSection) {
      const lbl = document.createElement("span");
      lbl.className   = "ast-section-lbl";
      lbl.textContent = "[" + section + "]";
      pl.appendChild(lbl);
      lastSection = section;
    }
    const wrap = document.createElement("div");
    wrap.style.cssText = "display:flex;align-items:baseline;gap:.4rem";
    const span = document.createElement("span");
    span.className   = "ast-port-line";
    span.style.flex  = "1";
    span.textContent = rawLine;
    wrap.appendChild(span);
    const badge = portBadgeFromLine(rawLine);
    if (badge) { badge.style.marginRight = ".9rem"; wrap.appendChild(badge); }
    pl.appendChild(wrap);
  });
  return pl;
}

function renderDvsFiles(files, targetId, editMode) {
  const body = document.getElementById(targetId || "dvs-file-body");
  if (!body) return;
  body.innerHTML = "";

  if (!files.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:40px">No files configured.</div>';
    return;
  }

  files.forEach(f => {
    const isHidden  = !!f.hidden;
    const portLines = f.port_lines || [];

    const row = document.createElement("div");
    row.className = "ast-row";
    if (isHidden) row.style.opacity = "0.45";
    row.onclick = e => { if (e.target.tagName === "BUTTON") return; openDvsEditor(f.label); };

    const nameEl = document.createElement("span");
    nameEl.className = "ast-name";
    nameEl.innerHTML =
      `${esc(f.label)}<span style="color:#fff;font-size:var(--fs-xs);margin-left:.6rem">${esc(f.path)}</span>`;
    if (!f.exists) {
      nameEl.innerHTML +=
        `<span style="color:var(--amber);font-size:var(--fs-xs);margin-left:.4rem">⚠ not found</span>`;
    }
    if (isHidden) {
      nameEl.innerHTML +=
        `<span style="color:#fff;font-size:var(--fs-xs);margin-left:.4rem">hidden</span>`;
    }

    const btns = document.createElement("div");
    btns.style.cssText = "display:flex;gap:.3rem";

    const editBtn = document.createElement("button");
    editBtn.className   = "btn btn-muted btn-sm";
    editBtn.textContent = "Edit";
    editBtn.onclick     = e => { e.stopPropagation(); openDvsEditor(f.label); };
    btns.appendChild(editBtn);

    if (editMode) {
      const hideBtn = document.createElement("button");
      hideBtn.className   = "btn btn-sm " + (isHidden ? "btn-green" : "btn-amber");
      hideBtn.textContent = isHidden ? "Show" : "Hide";
      hideBtn.onclick     = e => { e.stopPropagation(); edToggleFileHidden(f.label, isHidden); };
      btns.appendChild(hideBtn);
    }

    row.appendChild(nameEl);
    row.appendChild(btns);
    body.appendChild(row);

    const checks      = (typeof f === "object" && Array.isArray(f.checks)) ? f.checks : [];
    if (checks.length) {
      const cb = document.createElement("div");
      cb.className = "ast-checks";
      _fileCheckRows(cb, checks);
      body.appendChild(cb);
    }

    if (portLines.length) body.appendChild(_filePortLinesEl(portLines));
  });
}

function _ufOpenReset(unit, title, pathText) {
  _ufUnit = unit;
  document.getElementById("uf-title").textContent      = `✎ ${title}`;
  document.getElementById("uf-path").textContent       = pathText;
  document.getElementById("uf-textarea").value         = "";
  document.getElementById("uf-status").textContent     = "";
  document.getElementById("uf-promoted-bar").classList.remove("show");
  document.getElementById("uf-save-btn").disabled      = true;
  document.getElementById("uf-restart-btn").disabled   = true;
  document.getElementById("uf-restart-btn").style.display = "none";
  document.getElementById("uf-overlay").classList.add("open");
}

async function _ufOpenLabelFile(prefix, apiBase, label) {
  _ufOpenReset(prefix + label, label, "Loading…");
  const d = await api(`${apiBase}?label=${encodeURIComponent(label)}`);
  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Failed to load", false);
    return;
  }
  document.getElementById("uf-textarea").value      = d.content;
  document.getElementById("uf-save-btn").disabled   = !d.writable;
  document.getElementById("uf-path").textContent    = d.path;
  if (!d.exists) {
    ufSetStatus("⚠ File does not exist yet — saving will create it", false);
  } else {
    ufSetStatus(d.writable ? "" : "Read-only (not running as root)");
  }
}

async function openDvsEditor(label) {
  return _ufOpenLabelFile("\x00dvs:", "/api/dvswitch/file", label);
}

async function loadAllmon3Files() {
  const d = await api("/api/allmon3/files");
  if (!d) return;
  renderAllmon3Files(d.files || []);
}

function renderAllmon3Files(files, targetId, editMode) {
  const body = document.getElementById(targetId || "allmon3-file-body");
  if (!body) return;
  body.innerHTML = "";

  if (!files.length) {
    body.innerHTML =
      '<div class="stub-panel" style="min-height:40px">No Allmon3 files found.</div>';
    return;
  }

  files.forEach(f => {
    const isHidden  = !!f.hidden;
    const isRO      = !!f.readonly;
    const portLines = f.port_lines || [];

    const row = document.createElement("div");
    row.className = "ast-row";
    if (isHidden) row.style.opacity = "0.45";
    row.onclick = e => { if (e.target.tagName === "BUTTON") return; openAllmon3Editor(f.label); };

    const nameEl = document.createElement("span");
    nameEl.className = "ast-name";
    nameEl.innerHTML =
      `${esc(f.label)}<span style="color:#fff;font-size:var(--fs-xs);margin-left:.6rem">${esc(f.path)}</span>`;
    if (!f.exists) {
      nameEl.innerHTML +=
        `<span style="color:var(--amber);font-size:var(--fs-xs);margin-left:.4rem">⚠ not found</span>`;
    }
    if (isHidden) {
      nameEl.innerHTML +=
        `<span style="color:#fff;font-size:var(--fs-xs);margin-left:.4rem">hidden</span>`;
    }
    if (isRO) {
      nameEl.innerHTML +=
        `<span style="color:#fff;font-size:var(--fs-xs);margin-left:.4rem">read-only</span>`;
    }

    const btns = document.createElement("div");
    btns.style.cssText = "display:flex;gap:.3rem";

    const editBtn = document.createElement("button");
    editBtn.className   = "btn btn-muted btn-sm";
    editBtn.textContent = isRO ? "View" : "Edit";
    editBtn.onclick     = e => { e.stopPropagation(); openAllmon3Editor(f.label); };
    btns.appendChild(editBtn);

    if (editMode) {
      const hideBtn = document.createElement("button");
      hideBtn.className   = "btn btn-sm " + (isHidden ? "btn-green" : "btn-amber");
      hideBtn.textContent = isHidden ? "Show" : "Hide";
      hideBtn.onclick     = e => { e.stopPropagation(); edToggleFileHidden(f.label, isHidden); };
      btns.appendChild(hideBtn);
    }

    row.appendChild(nameEl);
    row.appendChild(btns);
    body.appendChild(row);

    const checks = (typeof f === "object" && Array.isArray(f.checks)) ? f.checks : [];
    if (checks.length) {
      const cb = document.createElement("div");
      cb.className = "ast-checks";
      _fileCheckRows(cb, checks);
      body.appendChild(cb);
    }

    if (portLines.length) body.appendChild(_filePortLinesEl(portLines));
  });
}

async function openAllmon3Editor(label) {
  _ufOpenReset("\x00allmon3:" + label, label, "Loading…");

  const d = await api(`/api/allmon3/file?label=${encodeURIComponent(label)}`);
  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Failed to load", false);
    return;
  }
  document.getElementById("uf-textarea").value    = d.content;
  document.getElementById("uf-path").textContent  = d.path;
  if (d.readonly) {
    document.getElementById("uf-save-btn").disabled = true;
    ufSetStatus("⚠ Managed by allmon3-passwd — read-only via this UI", false);
  } else if (!d.exists) {
    ufSetStatus("⚠ File does not exist yet — saving will create it", false);
  } else {
    document.getElementById("uf-save-btn").disabled = !d.writable;
    ufSetStatus(d.writable ? "" : "Read-only (not running as root)");
  }
}

window.loadTab_tune = function() { loadSimpleUSBTune(); loadRptNodes(); Promise.all([loadRadioPresets(), loadRadioDriver()]).then(() => { updateRadioButtons(); restoreActiveRadioButton(); }); };

const RN_DUPLEX = [
  ["0", "0 – half duplex, no telemetry or hang time"],
  ["1", "1 – half duplex, telemetry and hang time"],
  ["2", "2 – full duplex (repeater)"],
  ["3", "3 – full duplex, no repeated audio"],
  ["4", "4 – full duplex, repeat only when autopatch is down"],
];
const RN_TELEM = [
  ["0", "0 – off"],
  ["1", "1 – on"],
  ["2", "2 – timed (2 min after a command)"],
];
window.rnData = null;
window.rnOrig = {};

function tuneCardDefaultOpen(moduleState) {
  return moduleState === "load" || moduleState === "require";
}
function setCardOpen(bodyId, btnId, open) {
  const body = document.getElementById(bodyId);
  const btn  = document.getElementById(btnId);
  if (!body || !btn) return;
  body.classList.toggle("hidden", !open);
  btn.textContent = open ? "Hide" : "Show";
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}
function setTuneCardOpen(open) {
  setCardOpen("su-tune-body", "su-tune-toggle", open);
}

window._radioRestartBusy = false;

function setRadioRestartBusy(busy) {
  window._radioRestartBusy = !!busy;
  const ids = ["su-save-btn", "su-reload-btn", "ur-save-btn", "ur-reload-btn"];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) el.disabled = !!busy;
  }
  for (let i = 1; i <= 5; i++) {
    const btn = document.getElementById(`radio-btn-${i}`);
    if (btn && busy) btn.disabled = true;
  }
  if (!busy) updateRadioButtons();
}

async function pollRadioStackStatus() {
  const DEADLINE_MS = 35000;
  const INTERVAL_MS = 1500;
  const t0 = Date.now();

  while (Date.now() - t0 < DEADLINE_MS) {
    await new Promise(r => setTimeout(r, INTERVAL_MS));
    const s = await api("/api/radio/stack_status");
    if (!s || !s.ok) continue;

    if (s.restarting) continue;

    if (s.last_ok === false) {
      return { ok: false, msg: s.last_msg || "Asterisk restart failed" };
    }
    if (s.up === true) {
      return { ok: true, msg: "Asterisk restarted" };
    }
  }
  return {
    ok: false,
    msg: "Restart started but the stack is slow to settle — check the Services tab",
  };
}

const TUNE_CFG = {
  label: "SimpleUSB",
  readEndpoint: "/api/simpleusb/tune",
  notFoundMsg: "⚠ simpleusb.conf not found at /etc/asterisk/simpleusb.conf",
  fields: [
    { id: "rxmixerset", label: "RX Mixer Set", color: "var(--blue)",   tint: "rgba(100,150,220,0.15)", min: 0, max: 1000, step: 1, dec: 0, def: 500 },
    { id: "txmixaset",  label: "TX Mix A Set", color: "var(--green)",  tint: "rgba(100,180,100,0.15)", min: 0, max: 1000, step: 1, dec: 0, def: 300 },
    { id: "txmixbset",  label: "TX Mix B Set", color: "var(--orange)", tint: "rgba(220,140,60,0.15)",  min: 0, max: 1000, step: 1, dec: 0, def: 300 },
  ],
  advFields: [
    { id: "carrierfrom",        label: "Carrier From",          type: "select", def: "no",
      options: ["no", "usb", "usbinvert", "pp", "ppinvert"] },
    { id: "rxboost",            label: "RX Boost",              type: "bool",   def: "no", always: true },
    { id: "ctcssfrom",          label: "CTCSS From",            type: "select", def: "no",
      options: ["no", "usb", "usbinvert", "pp", "ppinvert"] },
    { id: "deemphasis",         label: "De-emphasis",           type: "bool",   def: "no", always: true },
    { id: "plfilter",           label: "PL Filter",             type: "bool",   def: "no" },
    { id: "invertptt",          label: "Invert PTT",            type: "bool",   def: "no" },
    { id: "preemphasis",        label: "Pre-emphasis",          type: "bool",   def: "no", always: true },
    { id: "legacyaudioscaling", label: "Legacy Audio Scaling",  type: "bool",   def: "yes" },
  ],
  pinGroups: [
    { id: "gpio", label: "GPIO", title: "GPIO pins",
      note: "Extra GPIO on the USB interface (pin 3 is PTT; 5-8 CM119 only)",
      pins: [1, 2, 4, 5, 6, 7, 8], collapsed: false,
      options: ["in", "out0", "out1"] },
    { id: "pp",   label: "PP",   title: "Parallel port pins",
      note: "Hardware parallel port pins 1-17",
      pins: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17], collapsed: true,
      options: ["in", "out0", "out1", "ptt", "cor", "ctcss"] },
  ],
  numberFields: [
    { id: "rxondelay",  label: "RX On Delay",  hint: "ms Frames 0-100 Range", min: 0, max: 100 },
    { id: "txoffdelay", label: "TX Off Delay", hint: "ms Frames 0-100 Range", min: 0, max: 100 },
  ],
};

function tuneFieldSpec(fieldId) {
  return TUNE_CFG.fields.find(f => f.id === fieldId);
}

async function loadSimpleUSBTune() {
  const cfg    = TUNE_CFG;
  const prefix = "su";
  const body   = document.getElementById(`${prefix}-tune-body`);
  const status = document.getElementById(`${prefix}-tune-status`);
  try {
    const resp = await api(cfg.readEndpoint);
    if (!resp || !resp.exists) {
      if (body)   body.innerHTML = `<div class="stub-panel" style="min-height:60px">${cfg.notFoundMsg}</div>`;
      if (status) status.textContent = "not found";
      if (resp) setTuneCardOpen(tuneCardDefaultOpen(resp.module));
      return;
    }
    if (status) status.textContent = "ready";
    renderTuneCard(resp.settings || {});
    setTuneCardOpen(tuneCardDefaultOpen(resp.module));
  } catch (e) {
    if (body)   body.innerHTML = `<div class="stub-panel" style="color:#f88;min-height:60px">Error: ${e.message}</div>`;
    if (status) status.textContent = "error";
  }
}

function renderTuneCard(s) {
  const cfg    = TUNE_CFG;
  const prefix = "su";
  const body   = document.getElementById(`${prefix}-tune-body`);
  if (!body) return;

  const originals = {};
  const fieldHtml = cfg.fields.map(f => {
    const val = s[f.id] ?? f.def;
    originals[f.id] = Number(val);
    const pct   = ((Number(val) - f.min) / (f.max - f.min)) * 100;
    const shown = f.dec ? Number(val).toFixed(f.dec) : val;
    return `
      <div style="display: grid; gap: 0.6rem">
        <label for="${prefix}-${f.id}" style="
          font-weight: 600;
          font-size: 0.9rem;
          color: ${f.color};
          display: flex;
          justify-content: space-between;
          align-items: center">
          <span>${f.label}</span>
          <input type="number" id="${prefix}-${f.id}-val"
            value="${shown}" step="${f.step}" min="${f.min}" max="${f.max}"
            aria-label="${f.label} exact value"
            style="
              font-family: var(--sans);
              font-size:var(--fs-base);
              font-weight: 400;
              background: ${f.tint};
              border: 1px solid var(--border2);
              border-radius: 0.3rem;
              padding: 0.2rem 0.4rem;
              width: 5.5rem;
              text-align: right;
              color: var(--text)"
            onchange="tuneNumberInput('${f.id}')"
            oninput="tuneNumberInput('${f.id}')">
        </label>
        <input type="range" id="${prefix}-${f.id}"
          min="${f.min}" max="${f.max}" step="${f.step}" value="${val}"
          aria-label="${f.label} slider (${f.min}-${f.max})"
          aria-valuemin="${f.min}" aria-valuemax="${f.max}" aria-valuenow="${val}"
          style="
            width: 100%;
            height: 6px;
            border-radius: 3px;
            background: linear-gradient(to right,
              ${f.color} 0%,
              ${f.color} ${pct}%,
              #ddd ${pct}%,
              #ddd 100%);
            accent-color: ${f.color};
            cursor: pointer"
          title="Valid range: ${f.min}–${f.max}"
          oninput="tuneSlide('${f.id}')">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size:var(--fs-sm); color: #5a7898">
          <span>Min: ${f.min}</span>
          <span style="text-align: right">Max: ${f.max}</span>
        </div>
      </div>`;
  }).join("");

  const selStyle = "font-family: var(--sans); font-size:var(--fs-base); " +
    "background: var(--surface2); border: 1px solid var(--border2); " +
    "border-radius: 0.3rem; padding: 0.25rem 0.4rem; color: var(--text)";
  let boolFieldsHtml = "";
  if (cfg.advFields && cfg.advFields.length) {
    const rows = cfg.advFields.map(f => {
      if (f.type === "select") {
        const cur = f.options.includes(s[f.id]) ? s[f.id] : f.def;
        originals[f.id] = cur;
        const opts = f.options.map(o =>
          `<option value="${o}"${o === cur ? " selected" : ""}>${o}</option>`).join("");
        return `
        <label for="${prefix}-${f.id}" style="
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size:var(--fs-base);
          color: var(--text)">
          <span>${f.label}</span>
          <select id="${prefix}-${f.id}" aria-label="${f.label}"
            style="${selStyle}" onchange="checkTuneDirty()">${opts}</select>
        </label>`;
      }
      const cur     = (s[f.id] === "yes" || s[f.id] === "no") ? s[f.id] : f.def;
      const checked = cur === "yes";
      originals[f.id] = checked ? "yes" : "no";
      return `
        <label for="${prefix}-${f.id}" style="
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size:var(--fs-base);
          color: var(--text);
          cursor: pointer">
          <input type="checkbox" id="${prefix}-${f.id}"
            ${checked ? "checked" : ""}
            aria-label="${f.label}"
            onchange="checkTuneDirty()">
          <span>${f.label}</span>
        </label>`;
    }).join("");

    const pinHtml = (cfg.pinGroups || []).map(g => {
      const cells = g.pins.map(n => {
        const id  = `${g.id}${n}`;
        const cur = g.options.includes(s[id]) ? s[id] : "";
        originals[id] = cur;
        const opts = [`<option value=""${cur === "" ? " selected" : ""}>—</option>`]
          .concat(g.options.map(o =>
            `<option value="${o}"${o === cur ? " selected" : ""}>${o}</option>`)).join("");
        return `
          <label for="${prefix}-${id}" style="
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.4rem;
            font-size:var(--fs-base);
            color: var(--text)">
            <span>${g.label} ${n}</span>
            <select id="${prefix}-${id}" aria-label="${g.title} ${n}"
              style="${selStyle}" onchange="checkTuneDirty()">${opts}</select>
          </label>`;
      }).join("");
      const inner = `
        <div style="font-size:var(--fs-xs); color: #5a7898">${g.note}</div>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr)); gap: 0.5rem">
          ${cells}
        </div>`;
      const titleCss = "font-weight: 600; font-size: 0.9rem; color: var(--text)";
      if (g.collapsed) {
        return `
        <details style="display: grid; gap: 0.5rem">
          <summary style="cursor: pointer; ${titleCss}">${g.title}</summary>
          <div style="display: grid; gap: 0.5rem; margin-top: 0.5rem">${inner}</div>
        </details>`;
      }
      return `
        <div style="display: grid; gap: 0.5rem">
          <div style="${titleCss}">${g.title}</div>
          ${inner}
        </div>`;
    }).join("");

    boolFieldsHtml = `
      <div style="display: grid; gap: 0.6rem">
        <div style="
          font-weight: 600;
          font-size: 0.9rem;
          color: var(--text)">Simpleusb Advanced Settings</div>
        <div style="display: grid; gap: 0.5rem">
          ${rows}
        </div>
        ${pinHtml}
      </div>`;
  }

  let numberFieldsHtml = "";
  if (cfg.numberFields && cfg.numberFields.length) {
    const rows = cfg.numberFields.map(f => {
      const val = Number(s[f.id] ?? 0);
      originals[f.id] = val;
      const checked = val > 0;
      return `
        <div style="display: grid; gap: 0.4rem">
          <label for="${prefix}-${f.id}-enable" style="
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size:var(--fs-base);
            color: var(--text);
            cursor: pointer">
            <input type="checkbox" id="${prefix}-${f.id}-enable"
              ${checked ? "checked" : ""}
              aria-label="Enable ${f.label}"
              onchange="tuneDelayToggle('${f.id}')">
            <span>${f.label}</span>
            <span style="font-size:var(--fs-xs); color: #5a7898">${f.hint}</span>
          </label>
          <input type="number" id="${prefix}-${f.id}"
            value="${val}" min="${f.min}" max="${f.max}" step="1"
            ${checked ? "" : "disabled"}
            aria-label="${f.label} value (${f.min}-${f.max})"
            style="
              font-family: var(--sans);
              font-size:var(--fs-base);
              background: var(--surface2);
              border: 1px solid var(--border2);
              border-radius: 0.3rem;
              padding: 0.3rem 0.5rem;
              width: 6rem;
              color: var(--text)"
            onchange="tuneDelayInput('${f.id}')"
            oninput="tuneDelayInput('${f.id}')">
        </div>`;
    }).join("");
    numberFieldsHtml = `
      <div style="display: grid; gap: 0.6rem">
        <div style="
          font-weight: 600;
          font-size: 0.9rem;
          color: var(--text)">RX/TX Delay</div>
        <div style="display: grid; gap: 0.8rem">
          ${rows}
        </div>
      </div>`;
  }

  window[`${prefix}_original_values`] = originals;

  const tipText = "RX adjusts input levels. TX adjusts output levels for each channel.";

  const defaultInfo = `
      <div style="
        font-size:var(--fs-base);
        color: #fff;
        padding: 0.8rem;
        background: rgba(60,180,200,0.08);
        border-radius: 0.3rem;
        border-left: 3px solid var(--teal);
        line-height: 1.4">
        <strong>ℹ Default:</strong> Radio 1 preset is applied on startup.
      </div>`;

  body.innerHTML = `
    <div style="display: grid; gap: 1.4rem; padding: 1rem">

      <div style="
        padding: 0.8rem;
        background: rgba(100,120,140,0.08);
        border-radius: 0.4rem;
        font-size:var(--fs-base);
        border-left: 3px solid var(--blue)">
        <div style="color: #3a5278; font-weight: 500; margin-bottom: 0.2rem">USB Device</div>
        <div style="font-family: var(--sans); color: var(--blue)">${esc(s.devstr || "—")}</div>
      </div>

      ${fieldHtml}
      ${boolFieldsHtml}
      ${numberFieldsHtml}

      <div style="display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.5rem">
        <button class="btn btn-blue btn-sm" id="${prefix}-save-btn"
          onclick="openTuneSaveDialog()"
          title="Save — choose preset and reload options">
          💾 Save
        </button>
        <button class="btn btn-muted btn-sm" id="${prefix}-reset-btn"
          onclick="resetTuneCard()"
          title="Revert to server values without saving">
          ↺ Reset
        </button>
        <span id="${prefix}-dirty-indicator" style="display:none;font-size:var(--fs-base);color:var(--amber);align-self:center">● unsaved changes</span>
      </div>

      <div style="
        font-size:var(--fs-base);
        color: #5a7898;
        padding: 0.8rem;
        background: rgba(100,120,140,0.04);
        border-radius: 0.3rem;
        line-height: 1.4">
        <strong>Tip:</strong> ${tipText} Use <strong>Save</strong> and enable restart in the dialog to apply changes immediately to Asterisk.
      </div>

      ${defaultInfo}

    </div>
  `;
}

function tuneSlide(fieldId) {
  const spec = tuneFieldSpec(fieldId);
  const sl = document.getElementById(`su-${fieldId}`);
  if (!spec || !sl) return;
  const v = parseFloat(sl.value);
  const pct = ((v - spec.min) / (spec.max - spec.min)) * 100;
  const box = document.getElementById(`su-${fieldId}-val`);
  if (box) box.value = spec.dec ? v.toFixed(spec.dec) : String(v);
  sl.setAttribute("aria-valuenow", sl.value);
  sl.style.background =
    `linear-gradient(to right, ${spec.color} 0%, ${spec.color} ${pct}%, #ddd ${pct}%, #ddd 100%)`;
  checkTuneDirty();
}

function tuneNumberInput(fieldId) {
  const spec = tuneFieldSpec(fieldId);
  const box  = document.getElementById(`su-${fieldId}-val`);
  const sl   = document.getElementById(`su-${fieldId}`);
  if (!spec || !box || !sl) return;
  let v = parseFloat(box.value);
  if (!Number.isFinite(v)) return;
  if (v < spec.min) v = spec.min;
  if (v > spec.max) v = spec.max;
  if (spec.step) {
    const steps = Math.round((v - spec.min) / spec.step);
    v = spec.min + steps * spec.step;
  }
  if (spec.dec) v = parseFloat(v.toFixed(spec.dec));
  sl.value = v;
  box.value = spec.dec ? v.toFixed(spec.dec) : String(v);
  const pct = ((v - spec.min) / (spec.max - spec.min)) * 100;
  sl.setAttribute("aria-valuenow", v);
  sl.style.background =
    `linear-gradient(to right, ${spec.color} 0%, ${spec.color} ${pct}%, #ddd ${pct}%, #ddd 100%)`;
  checkTuneDirty();
}

function tuneDelaySpec(fieldId) {
  return (TUNE_CFG.numberFields || []).find(f => f.id === fieldId);
}

function tuneDelayToggle(fieldId) {
  const cb  = document.getElementById(`su-${fieldId}-enable`);
  const box = document.getElementById(`su-${fieldId}`);
  if (!cb || !box) return;
  box.disabled = !cb.checked;
  if (!cb.checked) {
    box.value = "0";
  }
  checkTuneDirty();
}

function tuneDelayInput(fieldId) {
  const spec = tuneDelaySpec(fieldId);
  const box  = document.getElementById(`su-${fieldId}`);
  if (!spec || !box) return;
  let v = parseInt(box.value, 10);
  if (!Number.isFinite(v)) return;
  if (v < spec.min) v = spec.min;
  if (v > spec.max) v = spec.max;
  box.value = String(v);
  checkTuneDirty();
}

function resetTuneCard() {
  const cfg    = TUNE_CFG;
  const prefix = "su";
  const orig   = window[`${prefix}_original_values`];
  if (!orig) return;
  for (const f of cfg.fields) {
    if (orig[f.id] === undefined) continue;
    const sl = document.getElementById(`${prefix}-${f.id}`);
    if (sl) { sl.value = orig[f.id]; tuneSlide(f.id); }
  }
  if (cfg.advFields) {
    for (const f of cfg.advFields) {
      if (orig[f.id] === undefined) continue;
      const el = document.getElementById(`${prefix}-${f.id}`);
      if (!el) continue;
      if (f.type === "select") el.value = orig[f.id];
      else el.checked = orig[f.id] === "yes";
    }
  }
  if (cfg.pinGroups) {
    for (const g of cfg.pinGroups) {
      for (const n of g.pins) {
        const id = `${g.id}${n}`;
        if (orig[id] === undefined) continue;
        const el = document.getElementById(`${prefix}-${id}`);
        if (el) el.value = orig[id];
      }
    }
  }
  if (cfg.numberFields) {
    for (const f of cfg.numberFields) {
      if (orig[f.id] === undefined) continue;
      const cb  = document.getElementById(`${prefix}-${f.id}-enable`);
      const box = document.getElementById(`${prefix}-${f.id}`);
      if (cb)  cb.checked = orig[f.id] > 0;
      if (box) { box.value = String(orig[f.id]); box.disabled = !(orig[f.id] > 0); }
    }
  }
  checkTuneDirty();
  toast("Reset to server values", 1);
}

function getTuneValues() {
  const cfg    = TUNE_CFG;
  const prefix = "su";
  const out = {};
  for (const f of cfg.fields) {
    const el = document.getElementById(`${prefix}-${f.id}`);
    if (!el || el.value === "") continue;
    out[f.id] = f.dec ? parseFloat(el.value) : parseInt(el.value);
  }
  const orig = window[`${prefix}_original_values`] || {};
  if (cfg.advFields) {
    for (const f of cfg.advFields) {
      const el = document.getElementById(`${prefix}-${f.id}`);
      if (!el) continue;
      const v = f.type === "select" ? el.value : (el.checked ? "yes" : "no");
      if (f.always || v !== orig[f.id]) out[f.id] = v;
    }
  }
  if (cfg.pinGroups) {
    for (const g of cfg.pinGroups) {
      for (const n of g.pins) {
        const id = `${g.id}${n}`;
        const el = document.getElementById(`${prefix}-${id}`);
        if (el && el.value !== orig[id]) out[id] = el.value;
      }
    }
  }
  if (cfg.numberFields) {
    for (const f of cfg.numberFields) {
      const cb  = document.getElementById(`${prefix}-${f.id}-enable`);
      const box = document.getElementById(`${prefix}-${f.id}`);
      if (!cb) continue;
      if (!cb.checked) { out[f.id] = 0; continue; }
      let v = box ? parseInt(box.value, 10) : 0;
      if (!Number.isFinite(v)) v = 0;
      if (v < f.min) v = f.min;
      if (v > f.max) v = f.max;
      out[f.id] = v;
    }
  }
  return out;
}

function isTuneDirty() {
  const prefix = "su";
  const orig = window[`${prefix}_original_values`];
  if (!orig) return false;
  const cur = getTuneValues();
  for (const [k, v] of Object.entries(cur)) {
    if (orig[k] === undefined) continue;
    if (typeof v === "string" || typeof orig[k] === "string") {
      if (String(v) !== String(orig[k])) return true;
      continue;
    }
    if (Math.abs(Number(v) - Number(orig[k])) > 0.005) return true;
  }
  return false;
}

function checkTuneDirty() {
  const dirty = isTuneDirty();
  const ind = document.getElementById("su-dirty-indicator");
  if (ind) ind.style.display = dirty ? "inline" : "none";
  return dirty;
}

window.radioDialogSlot = null;
window.radioDialogMode = null;
window.radioDialogDriver = null;
window._tuneReloadChoice = false;

async function loadRadioPresets() {
  try {
    const result = await api("/api/radio/presets");
    if (!result || !result.ok) {
      console.warn("Failed to load radio presets");
      window.radioPresets = {};
      return;
    }
    window.radioPresets = result.presets || {};
    window.radioTune = result.tune || { active_slot: 0, active_driver: "", simpleusb: {} };
  } catch (e) {
    console.error("Error loading radio presets:", e);
    window.radioPresets = {};
    window.radioTune = { active_slot: 0, active_driver: "", simpleusb: {} };
  }
}

function restoreActiveRadioButton() {
  const tune = window.radioTune;
  const currentDrv = window.radioDriver?.active || null;
  const slot = tune?.active_slot || 0;
  const drvMatch = slot >= 1 && slot <= 5 &&
                   currentDrv && tune.active_driver === currentDrv;
  setActiveRadioButton(drvMatch ? slot : 0);
}

function radioPresetIsStale(slot) {
  const tune = window.radioTune;
  const currentDrv = window.radioDriver?.active || null;
  if (!tune || !currentDrv) return false;
  if (tune.active_slot !== slot || tune.active_driver !== currentDrv) return false;
  const preset = window.radioPresets?.[slot];
  const mirror = tune[currentDrv] || {};
  if (!preset) return false;
  for (const k of Object.keys(preset)) {
    if (k === "title") continue;
    if (mirror[k] === undefined) continue;
    const a = Number(preset[k]), b = Number(mirror[k]);
    if (Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) > 0.005) return true;
  }
  return false;
}

async function loadRadioDriver() {
  try {
    const r = await api("/api/radio/driver");
    window.radioDriver = (r && r.ok) ? r : null;
  } catch (e) {
    console.error("Error loading radio driver:", e);
    window.radioDriver = null;
  }
  return window.radioDriver;
}

function showRadioDialogFormView() {
  document.getElementById("radio-dialog-form-view").style.display = "block";
  document.getElementById("radio-dialog-restart-view").style.display = "none";
}

function openTuneSaveDialog() {
  const driver = "simpleusb";
  if (!isTuneDirty()) {
    toast("No changes to save", 1);
    return;
  }

  window.radioDialogMode = "tunesave";
  window.radioDialogDriver = driver;
  window.radioDialogSlot = null;
  window.radioDialogSource = null;

  document.getElementById("radio-dialog-hdr").textContent = "Save SimpleUSB Tune";
  document.getElementById("radio-dialog-msg").textContent = "Optional preset name:";
  document.getElementById("radio-dialog-error").style.display = "none";
  document.getElementById("radio-dialog-save-btn").textContent = "Save";

  const tune = window.radioTune;
  const preselect = (tune && tune.active_driver === driver &&
                      tune.active_slot >= 1 && tune.active_slot <= 5)
    ? String(tune.active_slot) : "1";
  const sel = document.getElementById("radio-dialog-preset-select");
  sel.value = preselect;
  document.getElementById("radio-dialog-preset-row").style.display = "block";
  tuneDialogPresetChanged();

  const reloadToggle = document.getElementById("radio-dialog-reload-toggle");
  reloadToggle.checked = window._tuneReloadChoice;
  document.getElementById("radio-dialog-reload-row").style.display = "block";
  tuneDialogReloadChanged();

  showRadioDialogFormView();
  document.getElementById("radio-dialog-overlay").style.display = "flex";
}

function tuneDialogPresetChanged() {
  const sel = document.getElementById("radio-dialog-preset-select");
  const titleInput = document.getElementById("radio-dialog-title");
  const titleRow = titleInput?.parentElement;
  if (titleRow) titleRow.style.display = sel.value ? "" : "none";
  if (titleInput) {
    const preset = sel.value ? window.radioPresets?.[parseInt(sel.value)] : null;
    titleInput.value = preset?.title ?? "";
  }
}

function tuneDialogReloadChanged() {
  const on = document.getElementById("radio-dialog-reload-toggle")?.checked;
  window._tuneReloadChoice = !!on;
  const warn = document.getElementById("radio-dialog-reload-warn");
  if (warn) warn.style.display = on ? "block" : "none";
}

function updateRadioButtons() {
  const presets = window.radioPresets || {};
  const drv = window.radioDriver;
  const noDriver = !!(drv && drv.none);

  for (let slot = 1; slot <= 5; slot++) {
    const btn = document.getElementById(`radio-btn-${slot}`);
    if (!btn) continue;

    const preset = presets[slot];
    const populated = preset && preset.rxmixerset !== undefined;

    if (populated && !noDriver) {
      btn.disabled = false;
      btn.classList.remove("empty");
      const stale = radioPresetIsStale(slot);
      btn.textContent = (preset.title || `Radio ${slot}`) + (stale ? " *" : "");
      btn.style.opacity = stale ? "0.75" : "";
      btn.title = `Apply ${preset.title || `Radio ${slot}`}: ` +
                  `RX=${preset.rxmixerset}, TX-A=${preset.txmixaset}, TX-B=${preset.txmixbset}` +
                  (stale ? " — current settings have been changed since this preset was applied" : "");
    } else if (populated && noDriver) {
      btn.disabled = true;
      btn.classList.add("empty");
      btn.textContent = preset.title || `Radio ${slot}`;
      btn.title = "No radio channel driver loaded (chan_simpleusb)";
    } else {
      btn.disabled = true;
      btn.classList.add("empty");
      btn.textContent = `Radio ${slot}`;
      btn.title = `Radio ${slot} preset is empty`;
    }
  }
}

async function applyRadioPreset(slot) {

  const preset = window.radioPresets?.[slot];
  if (!preset || preset.rxmixerset === undefined) {
    toast(`⚠ Preset ${slot} is empty`, 0);
    return;
  }

  let drv = window.radioDriver;
  if (!drv) drv = await loadRadioDriver();
  const active = drv?.active || null;

  if (!active) {
    toast("⚠ No radio channel driver loaded (chan_simpleusb)", 0);
    updateRadioButtons();
    return;
  }
  const endpoint   = "/api/simpleusb/tune";
  const cardPrefix = "su";
  const refreshFn  = loadSimpleUSBTune;
  const payload    = {
    rxmixerset: preset.rxmixerset,
    txmixaset:  preset.txmixaset,
    txmixbset:  preset.txmixbset,
    reload:     true,
    slot:       slot,
  };

  const body = document.getElementById(`${cardPrefix}-tune-body`);
  const isCardVisible = body && body.offsetParent !== null;

  if (isCardVisible) {
    const rxId  = "su-rxmixerset";
    const txaId = "su-txmixaset";
    const txbId = "su-txmixbset";
    const curRx  = document.getElementById(rxId)?.value;
    const curTxa = document.getElementById(txaId)?.value;
    const curTxb = document.getElementById(txbId)?.value;

    if (curRx && curTxa && curTxb &&
        parseInt(curRx)  === preset.rxmixerset &&
        parseInt(curTxa) === preset.txmixaset &&
        parseInt(curTxb) === preset.txmixbset) {
      toast(`✓ ${preset.title || `Radio ${slot}`} already applied`, 1);
      setActiveRadioButton(slot);
      return;
    }
  }

  if (window._radioRestartBusy) {
    toast("⚠ Restart in progress — try again shortly", 0);
    return;
  }

  const btn = document.getElementById(`radio-btn-${slot}`);
  if (btn) btn.disabled = true;
  const presetName = preset.title || `Radio ${slot}`;
  const originalText = btn ? btn.textContent : presetName;

  try {
    const result = await api(endpoint, "POST", payload);
    if (!result || !result.ok) {
      const errMsg = result?.message || "Unknown error";
      toast(`✗ Apply failed: ${errMsg}`, 0);
      return;
    }

    if (window.radioTune) {
      window.radioTune.active_slot = slot;
      window.radioTune.active_driver = active;
      const mirror = window.radioTune[active] || (window.radioTune[active] = {});
      for (const k of Object.keys(preset)) {
        if (k !== "title" && preset[k] !== undefined) mirror[k] = preset[k];
      }
    }
    setActiveRadioButton(slot);

    if (result.restart !== "started") {
      toast(`⚠ ${presetName} applied, but restart not started: ${result.restart_msg || "unknown"}`, 0);
      return;
    }

    if (btn) { btn.classList.add("spinner"); btn.textContent = "⟳"; }
    setRadioRestartBusy(true);
    const r = await pollRadioStackStatus();
    setRadioRestartBusy(false);
    if (btn) { btn.classList.remove("spinner"); btn.textContent = originalText; }

    if (r.ok) {
      toast(`✓ Applied & Asterisk restarted: ${presetName}`, 2);
      if (isCardVisible && refreshFn) refreshFn();
      updateRadioButtons();
      setActiveRadioButton(slot);
    } else {
      toast(`⚠ ${presetName} applied, but: ${r.msg}`, 0);
    }
  } catch (e) {
    toast(`✗ Error: ${e.message}`, 0);
  } finally {
    if (btn && !window._radioRestartBusy) btn.disabled = false;
  }
}

function setActiveRadioButton(slot) {
  for (let i = 1; i <= 5; i++) {
    const btn = document.getElementById(`radio-btn-${i}`);
    if (btn) btn.classList.remove("active");
  }
  const activeBtn = document.getElementById(`radio-btn-${slot}`);
  if (activeBtn) activeBtn.classList.add("active");
}

function renderAstFiles(files, dir, targetId, editMode) {
  const body = document.getElementById(targetId || "ast-file-body");
  if (!body) return;
  body.innerHTML = "";

  if (!files.length) {
    body.innerHTML =
      `<div class="stub-panel" style="min-height:60px">` +
      `No .conf files found in ${esc(dir)}</div>`;
    return;
  }

  files.forEach(f => {
    const name     = typeof f === "string" ? f : f.name;
    const isHidden = typeof f === "object" && !!f.hidden;
    const portLines = (typeof f === "object" && f.port_lines) || [];

    const row = document.createElement("div");
    row.className = "ast-row";
    if (isHidden) row.style.opacity = "0.45";
    row.onclick = e => { if (e.target.tagName === "BUTTON") return; openAstEditor(name); };

    const nameEl = document.createElement("span");
    nameEl.className   = "ast-name";
    nameEl.textContent = name;
    if (isHidden) {
      const dim = document.createElement("span");
      dim.style.cssText = "color:#fff;font-size:var(--fs-xs);margin-left:.5rem";
      dim.textContent   = "hidden";
      nameEl.appendChild(dim);
    }

    const btns = document.createElement("div");
    btns.style.cssText = "display:flex;gap:.3rem";

    const editBtn = document.createElement("button");
    editBtn.className   = "btn btn-muted btn-sm";
    editBtn.textContent = "Edit";
    editBtn.onclick     = e => { e.stopPropagation(); openAstEditor(name); };
    btns.appendChild(editBtn);

    if (editMode) {
      const hideBtn = document.createElement("button");
      hideBtn.className   = "btn btn-sm " + (isHidden ? "btn-green" : "btn-amber");
      hideBtn.textContent = isHidden ? "Show" : "Hide";
      hideBtn.onclick     = e => { e.stopPropagation(); edToggleFileHidden(name, isHidden); };
      btns.appendChild(hideBtn);
    }

    row.appendChild(nameEl);
    row.appendChild(btns);
    body.appendChild(row);

    const checks      = (typeof f === "object" && Array.isArray(f.checks)) ? f.checks : [];
    const collapsible = (typeof f === "object" && !!f.collapsible);
    if (checks.length) {
      const cb = document.createElement("div");
      cb.className = "ast-checks";

      if (collapsible) {
        cb.style.display = "none";
        const toggleBtn = document.createElement("button");
        toggleBtn.className   = "ast-toggle";
        toggleBtn.textContent = "▶ Show";
        toggleBtn.onclick     = e => {
          e.stopPropagation();
          const open = cb.style.display !== "none";
          cb.style.display    = open ? "none" : "";
          toggleBtn.textContent = open ? "▶ Show" : "▼ Hide";
        };
        btns.insertBefore(toggleBtn, btns.firstChild);
      }

      _fileCheckRows(cb, checks);
      body.appendChild(cb);
    }

    if (portLines.length) body.appendChild(_filePortLinesEl(portLines));
  });
}

async function openAstEditor(name) {
  document.getElementById("dpanel")?.style.setProperty("--panel-accent", "var(--red)");
  document.getElementById("uf-overlay").style.setProperty("--uf-accent", "var(--red)");
  _ufOpenReset("\x00ast:" + name, name, `/etc/asterisk/${name}`);


  const d = await api(`/api/asterisk/file?name=${encodeURIComponent(name)}`);
  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Failed to load", false);
    return;
  }
  document.getElementById("uf-textarea").value      = d.content;
  document.getElementById("uf-save-btn").disabled   = !d.writable;
  document.getElementById("uf-path").textContent    = d.path;
  ufSetStatus(d.writable ? "" : "Read-only (not running as root)");
}

async function _ufSaveFile(url, payload, what, confirmText, after) {
  if (!await confirm(confirmText)) return;
  const content = document.getElementById("uf-textarea").value;
  const btn     = document.getElementById("uf-save-btn");
  if (btn) btn.disabled = true;
  ufSetStatus("Saving…");
  const d = await api(url, "POST", {...payload, content});
  if (btn) btn.disabled = false;
  if (!d || !d.ok) {
    ufSetStatus(d?.message || "Save failed", false);
    toast(d?.message || "Save failed", "err");
    return;
  }
  ufSetStatus("Saved ✓", true);
  toast(`Saved ${what}`, "ok");
  if (after) after();
}

async function ufSave() {
  const overwrite = l => `Save changes to ${l}?\n\nThis overwrites the file on disk.`;
  if (_ufUnit.startsWith("\x00ast:")) {
    const name = _ufUnit.slice(5);
    return _ufSaveFile("/api/asterisk/file", {name}, name,
      `Save changes to ${name}?\n\nThis overwrites /etc/asterisk/${name} on disk.`);
  } else if (_ufUnit.startsWith("\x00dvs:")) {
    const label = _ufUnit.slice(5);
    return _ufSaveFile("/api/dvswitch/file", {label}, label, overwrite(label), loadDvsFiles);
  } else if (_ufUnit.startsWith("\x00allmon3:")) {
    const label = _ufUnit.slice(9);
    return _ufSaveFile("/api/allmon3/file", {label}, label, overwrite(label), loadAllmon3Files);
  } else if (_ufUnit.startsWith("\x00appconf:")) {
    const label = _ufUnit.slice(9);
    return _ufSaveFile("/api/appconf/file", {label}, label, overwrite(label));
  } else {
    return _ufSaveOrig();
  }
}

function portBadgeFromLine(line) {
  const m = line.match(/[=:]\s*(\d{4,5})\s*(?:[;#]|$)/);
  if (!m) return null;
  const port = m[1];
  const lower = line.toLowerCase();
  const proto = (lower.includes("udp") ||
                 ["4569","34000","34001","31100","17000","42000","42020","42021"].includes(port))
                ? "udp" : "tcp";
  return portBadge(port, proto);
}

window.loadTab_dvsm = function() { loadDvsm(); };

const _dvsmRevealed = new Map();
const _dvsmSecrets  = new Map();


window.loadTab_stfu = function() { loadStfu(); };
window.loadTab_m17  = function() { loadM17(); };


const _stfuSecrets  = new Map();
const _stfuRevealed = new Map();

let _stfuSampleText = "";

let _stfuDvsPath = "";

let _stfuLoadedContent = null;

let _m17SampleText = "";
let _m17IniPath = "";
let _m17LoadedContent = null;


let _zelloSampleText    = "";
let _zelloOverridePath  = "";
let _zelloLoadedContent = null;

window.loadTab_zello = function() { loadZello(); };


function _startApp() {
  _appStarted = true;
  if (sessionStorage.getItem("sysmon_paused_by_nav")) {
    sessionStorage.removeItem("sysmon_paused_by_nav");
    _pausedByNavigation = true;
  }

  const lnk = document.getElementById("lnk-dashboard");
  if (lnk) {
    const port = window.location.port || "8989";
    const host = window.location.hostname;
    const dashboardUrl = `http://${host}:8989/`;
    lnk.href = dashboardUrl;
    lnk.title = "Return to ASL-DVS Dashboard";
  }

  const qlHost = window.location.hostname;
  const qlPorts = {"lnk-allmon3": 8080, "lnk-cockpit": 9090, "lnk-wifimon": 8991};
  for (const [id, port] of Object.entries(qlPorts)) {
    const el = document.getElementById(id);
    if (el) el.href = `http://${qlHost}:${port}/`;
  }
  const qlPaths = {"lnk-dvswitch": "/dvswitch", "lnk-m17": "/m17"};
  for (const [id, path] of Object.entries(qlPaths)) {
    const el = document.getElementById(id);
    if (el) el.href = `http://${qlHost}${path}`;
  }

  api("/api/config").then(d => {
    if (d && d.ok) {
      _savedEnabledTabs = d.ui?.enabled_tabs || TABS.slice();
      _applyTabVisibilityGated();
    }
  }).catch(() => {});

  Promise.all([loadRadioPresets(), loadRadioDriver()]).then(() => {
    updateRadioButtons();
    restoreActiveRadioButton();
  });

  if (_pausedByNavigation) {
    resumeAllPolling();
  } else {
    startStatusPolling();
  }

  if (typeof switchTab === "function") {
    switchTab("overview", "0,255,229");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  (async function _authBoot() {
    try {
      const r = await fetch("/api/whoami");
      if (r.ok) { hideLoginScreen(); _startApp(); return; }
    } catch (_) { }
    let relogin = null;
    try { relogin = sessionStorage.getItem(_RELOGIN_KEY); } catch (_) {}
    showLoginScreen(relogin ? _SESSION_EXPIRED_MSG : "");
  })();
});

let _secData = null;
let _secBusy = false;
const _secOpen = new Set();

const _SEC_LAYER_IDS = ["dvswitch", "asl", "usrp2m17", "cross-cutting"];

function secToggle(id, kind) {
  const key   = id + ":" + kind;
  const panel = document.getElementById("sec-" + kind + "-" + id);
  const btn   = document.getElementById("sec-btn-" + kind + "-" + id);
  if (!panel) return;
  const show = panel.hidden;
  panel.hidden = !show;
  if (show) _secOpen.add(key); else _secOpen.delete(key);
  if (btn) {
    btn.classList.toggle("on", show);
    btn.setAttribute("aria-expanded", show ? "true" : "false");
  }
}

window.loadTab_security = function() {
  if (!_enabledTabSet.has("security")) return;
  _secFetch(false);
};

window.addEventListener("beforeunload", () => {
  stopStatusPolling();
});

// ========================================================================
// TAB: Overview
// ========================================================================
// ---- general ----
async function svcGlobal(action, btn) {
  if (btn) btn.disabled = true;
  const d = await api("/api/svc", "POST", {action: action});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadOverview, 1200);
}

// ========================================================================
// TAB: Services
// ========================================================================
// ---- general ----
async function loadGeneralList() {
  const qs = `?scope=${_s3Scope}&filter=${encodeURIComponent(_s3Filter)}&all=1`;
  const d  = await api("/api/services" + qs);
  if (!d) return;
  renderGeneralList(d);
}

// ---- card: Services ----
function renderGeneralList(d) {
  const body = document.getElementById("s3-gen-body");
  if (!body) return;
  body.innerHTML = "";

  if (!d.items || d.items.length === 0) {
    body.innerHTML = '<div class="stub-panel" style="min-height:60px">No services found.</div>';
    return;
  }

  d.items.forEach(svc => {
    const row = document.createElement("div");
    row.className = "s3-gen-row";
    row.onclick   = e => {
      if (e.target.tagName === "BUTTON") return;
      openServicePanel(svc.unit, "");
    };

    const editBtn = document.createElement("button");
    editBtn.className   = "btn btn-muted btn-sm";
    editBtn.textContent = "Edit";
    editBtn.onclick     = e => { e.stopPropagation(); openUnitFileEditor(svc.unit); };

    row.innerHTML =
      `<span class="dot ${dotClass(svc.state, svc.enabled)}"></span>` +
      `<span class="s3-gen-name">${esc(svc.unit)}</span>`;

    row.appendChild(_ovOwnerCell(svc));
    row.appendChild(_ovModeCell(svc));

    const row2 = document.createElement("div");
    row2.className = "s3-gen-row2";
    const stateEl = document.createElement("span");
    stateEl.className   = "s3-state " + stateClass(svc.state);
    stateEl.textContent = svc.state;
    row2.appendChild(stateEl);
    row2.appendChild(editBtn);

    row.appendChild(row2);
    body.appendChild(row);
  });
}

function s3SetScope(scope) {
  _s3Scope = scope;
  document.getElementById("s3-btn-active").classList.toggle("on", scope === "active");
  document.getElementById("s3-btn-all").classList.toggle("on", scope === "all");
  loadGeneralList();
}

function s3FilterChanged() {
  clearTimeout(_s3FilterTimer);
  _s3FilterTimer = setTimeout(() => {
    _s3Filter = document.getElementById("s3-filter").value.trim();
    loadGeneralList();
  }, 300);
}

// ========================================================================
// TAB: Ports
// ========================================================================
// ---- general ----
function ptSetProto(proto) {
  _ptProto = proto;
  ["both","tcp","udp"].forEach(p => {
    const btn = document.getElementById("pt-btn-" + p);
    if (btn) btn.classList.toggle("on", p === proto);
  });
  loadPorts();
}

// ========================================================================
// TAB: Firewall
// ========================================================================
// ---- general ----
function renderFwSummary(el, d, rules) {
  if (!el) return;
  if (_fwBackend === "none") { el.classList.add("hidden"); el.innerHTML = ""; return; }
  el.classList.remove("hidden");

  const dot = d.status === "active" ? "🟢"
            : d.status === "inactive" ? "⚪" : "🟡";

  let where = "";
  if (_fwBackend === "firewalld" && d.zone_info) {
    const ifaces = (d.zone_info.interfaces || []).join(", ") || "no interface bound";
    where = ` — zone "${esc(d.zone_info.zone)}" on ${esc(ifaces)}` +
      ((d.zone_info.other_zones || []).length
        ? ` (+ zone${d.zone_info.other_zones.length > 1 ? "s" : ""} ${esc(d.zone_info.other_zones.join(", "))})` : "");
  } else if (_fwBackend === "nft" && d.chain_info) {
    where = ` — ${esc(d.chain_info.family)} ${esc(d.chain_info.table)} ${esc(d.chain_info.chain)}`;
  }

  const total   = new Set(rules.filter(r => r.action === "ALLOW").map(r => r.to)).size;
  const labeled = rules.filter(r => r.service).length;
  const countTxt = total
    ? `${total} port${total === 1 ? "" : "s"} allowed` +
      (labeled ? ` (${labeled} tied to known services)` : "")
    : "no ports currently allowed through this tool";

  el.innerHTML =
    `<span class="fw-summary-dot">${dot}</span>` +
    `<span>${esc(_fwBackend)}${where} — ${countTxt}</span>`;
}

function renderFwZoneDetails(el, d) {
  if (!el) return;
  if (_fwBackend !== "firewalld" || !d.zone_info) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.classList.remove("hidden");
  const zi = d.zone_info;
  const rows = [["Zone", zi.zone]];
  if ((zi.interfaces || []).length) rows.push(["Interface", zi.interfaces.join(", ")]);
  rows.push(["Policy", zi.target_desc || zi.target || "unknown"]);
  if (zi.rich_rule_count) {
    rows.push(["Rich rules", `${zi.rich_rule_count} (see raw output below)`]);
  }
  el.innerHTML = rows.map(([lbl, val]) =>
    `<div class="fw-zone-row"><span class="fw-zone-lbl">${esc(lbl)}</span>` +
    `<span class="fw-zone-val">${esc(String(val))}</span></div>`
  ).join("");
}

function openFwPanel(rule) {
  document.getElementById("dpanel").style.setProperty(
    "--panel-accent", "var(--orange)");

  document.getElementById("dpanel-unit").textContent =
    `Rule #${rule.display_num ?? rule.num} — ${rule.to}`;
  document.getElementById("dpanel-desc").textContent =
    `${rule.action}  ${rule.from}${rule.service ? "  →  " + rule.service : ""}`;
  document.getElementById("dpanel-badges").innerHTML = "";
  document.getElementById("dpanel-output").innerHTML =
    '<span class="dp-out-dim">Select an action below</span>';

  const body = document.getElementById("dpanel-body");
  _dpRestoreBody();
  body.dataset.custom = "1";
  const svcHtml = rule.service ? `
    <div class="dpzone-lbl">Service Actions</div>
    <div class="dpbtn-row">
      <button class="btn btn-blue  btn-sm"
        onclick="ptSvcAction('restart','${esc(rule.service)}.service')">↺ Restart</button>
      <button class="btn btn-amber btn-sm"
        onclick="ptSvcAction('stop','${esc(rule.service)}.service')">■ Stop</button>
      <button class="btn btn-purple btn-sm"
        onclick="ptViewJournal('${esc(rule.service)}.service')">▤ Journal</button>
    </div>` : "";

  body.innerHTML = `
    <div class="dpzone-lbl">Rule Details</div>
    <div style="padding:.55rem .9rem;font-family:var(--sans);font-size:var(--fs-sm);
      border-bottom:1px solid var(--border);line-height:1.9">
      <div><span style="color:#fff;font-size:var(--fs-xs);letter-spacing:.12em;
        text-transform:uppercase">Rule #&nbsp;</span>
        <span style="color:var(--orange)">${esc(String(rule.display_num ?? rule.num))}</span></div>
      <div><span style="color:#fff;font-size:var(--fs-xs);letter-spacing:.12em;
        text-transform:uppercase">Port&nbsp;&nbsp;&nbsp;</span>
        <span style="color:var(--text-bright)">${esc(rule.to)}</span></div>
      <div><span style="color:#fff;font-size:var(--fs-xs);letter-spacing:.12em;
        text-transform:uppercase">Action&nbsp;</span>
        <span class="fw-action ${esc(rule.action)}" style="display:inline">
        ${esc(rule.action)}</span></div>
      <div><span style="color:#fff;font-size:var(--fs-xs);letter-spacing:.12em;
        text-transform:uppercase">From&nbsp;&nbsp;&nbsp;</span>
        <span>${esc(rule.from)}</span></div>
      ${rule.service ? `<div><span style="color:#fff;font-size:var(--fs-xs);
        letter-spacing:.12em;text-transform:uppercase">Service</span>
        <span style="color:var(--amber)">${esc(rule.service)}.service</span></div>` : ""}
    </div>
    <div class="dpzone-lbl">Rule Actions</div>
    <div class="dpbtn-row">
      ${rule.deletable === false
        ? `<span style="font-size:var(--fs-xs);color:var(--text-dim)">Rich rule — read-only here</span>`
        : `<button class="btn btn-red btn-sm"
        onclick="fwDeleteRule('${esc(String(rule.num))}',this);closePanel()">✕ ${rule.via === "service" ? "Remove Service " + esc(rule.fw_service) : "Delete Rule"}</button>`}
    </div>
    <div style="margin:.3rem .9rem .55rem;font-size:var(--fs-xs);color:var(--text-dim);
      line-height:1.5">
      ${_fwCockpitInstalled
        ? `To change this rule's action, use Cockpit's firewall panel
           (<span style="color:var(--blue)">https://&lt;host&gt;:9090</span> →
           Networking → Firewall) — sysmon only deletes existing rules.`
        : `To change this rule's action, delete it and re-add it with the
           desired action, or use the ufw CLI directly — sysmon only
           deletes existing rules.`}
    </div>
    ${svcHtml}
    <div id="dpanel-output" style="margin:.55rem .9rem;background:#0a1020;
      border:1px solid var(--border);border-radius:3px;min-height:50px;
      max-height:160px;overflow-y:auto;padding:.5rem .7rem;
      font-family:var(--sans);font-size:var(--fs-sm);color:#fff;line-height:1.65">
      <span class="dp-out-dim">Action results appear here</span>
    </div>`;

  document.getElementById("dpanel-overlay").classList.add("open");
  document.getElementById("dpanel").classList.add("open");
}

async function fwDeleteRule(num, btn) {
  let q = `Delete firewall rule ${num}?`;
  if (String(num).startsWith("svc:")) {
    const [svc, zone] = String(num).slice(4).split("@");
    const ports = [...new Set((_fwRules || []).filter(r => r.num === num).map(r => r.to))];
    q = `Remove firewalld service "${svc}" from zone ${zone}?\n\n` +
        `This closes: ${ports.join(", ") || "(no ports)"}` +
        (svc === "cockpit" ? "\n\nWarning: this closes Cockpit itself." : "") +
        (svc === "ssh" ? "\n\nWarning: this closes SSH access." : "");
  }
  if (!await confirm(q)) return;
  if (btn) btn.disabled = true;
  const d = await api("/api/firewall", "POST", {action: "delete", rule_num: num});
  if (btn) btn.disabled = false;
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Rule deleted" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadFirewall, 600);
}

async function fwUfwEnable() {
  const d = await api("/api/firewall", "POST", {action: "enable"});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "ufw enabled" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadFirewall, 800);
}

async function fwUfwDisable() {
  if (!await confirm("Disable ufw? All firewall rules will be inactive.")) return;
  const d = await api("/api/firewall", "POST", {action: "disable"});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "ufw disabled" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadFirewall, 800);
}

// ---- card: Firewall Rules ----
async function loadFirewall() {
  const d = await api("/api/firewall");
  if (!d) return;
  _fwBackend = d.backend || "none";
  _fwCockpitInstalled = !!d.cockpit_installed;

  const bv = document.getElementById("fw-backend-val");
  const sv = document.getElementById("fw-status-val");
  if (bv) bv.textContent = _fwBackend;
  if (sv) {
    sv.textContent = d.status || "";
    sv.className   = "fw-status-val " + (d.status || "");
  }

  const ufwSec   = document.getElementById("fw-ufw-section");
  const rawSec   = document.getElementById("fw-raw-section");
  const noneSec  = document.getElementById("fw-none-section");
  const ufwBtns  = document.getElementById("fw-ufw-btns");
  const sumLine  = document.getElementById("fw-summary-line");
  const zoneCard = document.getElementById("fw-zone-details");

  ufwSec .classList.toggle("hidden", !["ufw","nft","firewalld"].includes(_fwBackend));
  rawSec .classList.toggle("hidden", !["nft","iptables","firewalld"].includes(_fwBackend));
  noneSec.classList.toggle("hidden", _fwBackend !== "none");
  if (ufwBtns) ufwBtns.style.display = _fwBackend === "ufw" ? "flex" : "none";

  const rules = d.rules || [];
  _fwRules = rules;
  if (["ufw","nft","firewalld"].includes(_fwBackend)) {
    renderFwRules(rules);
  }

  renderFwSummary(sumLine, d, rules);
  renderFwZoneDetails(zoneCard, d);

  if (rawSec && !rawSec.classList.contains("hidden")) {
    const pre = document.getElementById("fw-raw-pre");
    if (pre) pre.textContent = d.raw || "(empty ruleset)";
  }
}

function fwToggleRaw() {
  _fwRawOpen = !_fwRawOpen;
  document.getElementById("fw-raw-toggle-hdr") ?.classList.toggle("open", _fwRawOpen);
  document.getElementById("fw-raw-toggle-body")?.classList.toggle("open", _fwRawOpen);
}

function fwToggleManual() {
  _fwManualOpen = !_fwManualOpen;
  document.getElementById("fw-manual-hdr") ?.classList.toggle("open", _fwManualOpen);
  document.getElementById("fw-manual-body")?.classList.toggle("open", _fwManualOpen);
  const chev = document.getElementById("fw-manual-chevron");
  if (chev) chev.textContent = _fwManualOpen ? "▼" : "▶";
}

async function fwRawCopy() {
  const pre = document.getElementById("fw-raw-pre");
  if (!pre || !pre.textContent) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(pre.textContent);
}

function renderFwRules(rules) {
  const body = document.getElementById("fw-rule-body");
  if (!body) return;
  body.innerHTML = "";

  if (!rules.length) {
    body.innerHTML =
      '<div class="stub-panel" style="min-height:50px">No rules configured.</div>';
    return;
  }

  rules.forEach(r => {
    const row = document.createElement("div");
    row.className = "fw-row";
    row.onclick   = e => {
      if (e.target.classList.contains("fw-del")) return;
      openFwPanel(r);
    };

    const svcTxt = r.service || "—";
    const svcCls = r.service ? "fw-svc" : "fw-svc unknown";

    const canDel = r.deletable !== false;
    row.innerHTML =
      `<span class="fw-num">${esc(String(r.display_num ?? r.num))}</span>` +
      `<span class="fw-to">${esc(r.to)}</span>` +
      `<span class="fw-action ${esc(r.action)}">${esc(r.action)}</span>` +
      `<span class="fw-from">${esc(r.from)}</span>` +
      `<span class="${svcCls}">${esc(svcTxt)}</span>` +
      (canDel
        ? `<span class="fw-del" onclick="fwDeleteRule('${esc(String(r.num))}',this)">✕</span>`
        : `<span class="fw-del" style="visibility:hidden">✕</span>`);
    body.appendChild(row);
  });
}

async function fwAddRule() {
  const port   = document.getElementById("fw-add-port").value.trim();
  const proto  = document.getElementById("fw-add-proto").value;
  const action = document.getElementById("fw-add-action").value;
  const from_  = document.getElementById("fw-add-from").value.trim() || "Anywhere";
  if (!port) { toast("Enter a port number", "err"); return; }
  const d = await api("/api/firewall", "POST",
    {action: action, port: port, proto: proto, src: from_});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "Rule added" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    document.getElementById("fw-add-port").value = "";
    document.getElementById("fw-add-from").value = "";
    setTimeout(loadFirewall, 600);
  }
}

// ========================================================================
// TAB: Reg
// ========================================================================
// ---- general ----
function _regShowUnreachable(ids) {
  const body = document.getElementById(ids.body);
  if (body) body.innerHTML = '<div class="stub-panel" style="min-height:60px">Server unreachable</div>';
  const status = document.getElementById(ids.status);
  if (status) { status.className = "reg-card-status"; status.textContent = "—"; }
}

// ========================================================================
// TAB: Phone
// ========================================================================
// ---- general ----
function phSetCard(pfx, status, label, meta) {
  const st = document.getElementById("ph-" + pfx + "-status");
  const mt = document.getElementById("ph-" + pfx + "-meta");
  if (st) { st.className = "reg-card-status " + (status || "info"); st.textContent = label || "—"; }
  if (mt) mt.textContent = meta || "—";
}

function phBody(pfx) {
  const b = document.getElementById("ph-" + pfx + "-body");
  if (b) b.innerHTML = "";
  return b;
}

function phNote(body, text) { body.appendChild(phEl("div", "ph-note", text)); }

function phSec(d, id) { return (d && d.sections || []).find(s => s.id === id) || null; }

function phStar(code) { return code ? "*" + code : ""; }

function phRenderLive(s) {
  const body = phBody("live");
  if (!body) return;
  if (!s) { phSetCard("live", "info", "—", "—"); phNote(body, "No data"); return; }
  if (!s.found) {
    phSetCard("live", "fail", "DOWN", s.running === false ? "Asterisk not running" : "unavailable");
    phNote(body, s.note || "Live status is unavailable");
    return;
  }
  const label = {idle: "IDLE", dialing: "DIALING", incoming: "INCOMING", in_call: "IN CALL"}[s.state] || s.state.toUpperCase();
  phSetCard("live", s.state === "idle" ? "info" : "pass", label,
            s.calls.length ? s.calls.length + " call" + (s.calls.length === 1 ? "" : "s") : "no calls");
  const pn = s.phone_node || {};
  const pnName = pn.node ? pn.node + (pn.network ? " (" + pn.network + ")" : "") : "";
  let linkTxt = pn.linked === true ? `${pnName} is linked to ${pn.main_node}`
                : pn.linked === false ? `${pnName} is not linked to ${pn.main_node} (it links while the dashboard Phone tab is open)`
                : pn.node ? "unknown" : "";
  if ((pn.others_linked || []).length)
    linkTxt += ` — also linked: ${pn.others_linked.join(", ")} (only the picked network's node should be)`;
  const f = s.flags || {};
  body.appendChild(phKV([
    ["Phone node", linkTxt],
    ["Dashboard Phone tab", f.open === "1" ? "open (incoming calls are answered)" : (f.open === undefined ? "" : "closed (callers get busy)")],
    ["Network in use", f.active],
    ["Phone patch", f.patch === "0" ? "OFF" : (f.patch === "1" ? "on" : "")],
  ]));
  if (s.calls.length) {
    body.appendChild(phEl("div", "ph-sub", "Calls now"));
    const t = phEl("table", "ph-tbl");
    s.calls.forEach(c => {
      const tr = phEl("tr");
      [c.direction, c.network_name, c.state.replace("_", " "), c.seconds + " s", c.who_last4 ? "…" + c.who_last4 : ""]
        .forEach(x => tr.appendChild(phEl("td", "", x)));
      t.appendChild(tr);
    });
    body.appendChild(t);
  }
  if ((s.registrations || []).length) {
    body.appendChild(phEl("div", "ph-sub", "Sign-in"));
    const t = phEl("table", "ph-tbl");
    s.registrations.forEach(r => {
      const tr = phEl("tr");
      tr.appendChild(phEl("td", "", r.name));
      const td = phEl("td");
      td.appendChild(phBadge(r.state, r.registered === true ? "pass" : r.registered === false ? "fail" : "info"));
      tr.appendChild(td);
      t.appendChild(tr);
    });
    body.appendChild(t);
  }
}

function phRenderNode(s) {
  const body = phBody("node");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("node", "info", "NONE", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  phSetCard("node", "pass", "FOUND", s.nodes.length + " node" + (s.nodes.length === 1 ? "" : "s"));
  s.nodes.forEach(n => {
    const blk = phEl("div", "ph-blk");
    const hdr = phEl("div", "ph-blk-hdr", "Node " + n.node);
    hdr.appendChild(phBadge(n.role, n.is_phone_bridge ? "pass" : "info"));
    hdr.appendChild(phBadge(n.managed_by, "info"));
    blk.appendChild(hdr);
    const ap = n.autopatch;
    const opts = ap ? Object.entries(ap.options || {}).map(e => e[0] + "=" + e[1]).join(", ") : "";
    const sx = Object.entries(n.simplex || {}).map(e => e[0] + " " + e[1]).join(", ");
    blk.appendChild(phKV([
      ["Mode", n.mode + " (duplex " + n.duplex + ")"],
      ["Channel", n.rxchannel],
      ["In [nodes]", n.in_nodes_list ? (n.nodes_line || "yes") : "no"],
      ["Dialing context", n.context],
      ["Dial code", ap ? phStar(ap.code) + (opts ? "  —  " + opts : "") : "none"],
      ["Hang-up", (n.hangup || []).map(h => phStar(h.code) + " " + h.kind).join(", ") || "none"],
      ["Patch on / off", (n.patch_on || n.patch_off) ? phStar(n.patch_on) + " / " + phStar(n.patch_off) : ""],
      ["Key transmitter", phStar(n.ptt)],
      ["Function list", n.functions],
      ["Simplex timing", sx],
      ["Written in", n.file],
    ]));
    body.appendChild(blk);
  });
}

function phRenderNets(s, live) {
  const body = phBody("nets");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("nets", "info", "NONE", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  const regs = {};
  (live && live.found ? live.registrations || [] : []).forEach(r => { regs[r.id] = r; });
  phSetCard("nets", "pass", "FOUND", s.networks.length + " network" + (s.networks.length === 1 ? "" : "s"));
  s.networks.forEach(n => {
    const blk = phEl("div", "ph-blk");
    const hdr = phEl("div", "ph-blk-hdr", n.name);
    hdr.appendChild(phBadge(n.type_label, "info"));
    hdr.appendChild(phBadge(n.source, "info"));
    blk.appendChild(hdr);
    const r = regs[n.id];
    let signIn = "";
    if (!n.registers) signIn = n.type === "sip_ip" ? "no login (matched by address)" : "does not sign in";
    else if (r) signIn = r.state;
    else signIn = live && live.found ? "unknown" : "Asterisk not running";
    blk.appendChild(phKV([
      ["Server", n.host ? n.host + (n.port ? ":" + n.port : "") : ""],
      ["Username", n.username],
      ["Password", n.type === "sip_ip" ? "" : (n.has_secret ? "set" : "MISSING")],
      ["Caller ID", n.caller_id],
      ["Sign-in", signIn],
      ["Incoming context", n.context],
      ["Matched address", n.match],
      ["Written in", n.file],
    ]));
    body.appendChild(blk);
  });
  (s.transports || []).forEach(t => {
    const blk = phEl("div", "ph-blk");
    const hdr = phEl("div", "ph-blk-hdr", "SIP transport " + t.name);
    hdr.appendChild(phBadge(t.source, "info"));
    blk.appendChild(hdr);
    blk.appendChild(phKV([
      ["Protocol / bind", [t.protocol, t.bind].filter(Boolean).join("  ")],
      ["Home network", t.local_net],
      ["Public address", [t.external_signaling, t.external_media].filter((v, i, a) => v && a.indexOf(v) === i).join(", ")],
    ]));
    body.appendChild(blk);
  });
}

function phRenderDialing(s, nets) {
  const body = phBody("dial");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("dial", "info", "NONE", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  const names = {};
  ((nets && nets.networks) || []).forEach(n => { names[n.id] = n.name; });
  const miss = s.missing_contexts || [];
  phSetCard("dial", miss.length ? "fail" : "pass", miss.length ? "MISSING" : "FOUND",
            s.outgoing.length + " context" + (s.outgoing.length === 1 ? "" : "s"));
  miss.forEach(c => phNote(body, "Context " + c + " is named by an autopatch code but is not in extensions.conf"));
  body.appendChild(phEl("div", "ph-sub", "Outgoing"));
  s.outgoing.forEach(o => {
    const blk = phEl("div", "ph-blk");
    if (o.kind === "dashboard") {
      const hdr = phEl("div", "ph-blk-hdr", names[o.network] || o.network);
      hdr.appendChild(phBadge(o.dialing, "info"));
      blk.appendChild(hdr);
      blk.appendChild(phKV([
        ["Number sent as", o.number_format],
        ["911", o.e911 ? "allowed" : "off"],
        ["International", o.international ? "allowed" : "off"],
        ["Blocked groups", o.blocked && o.blocked.length ? o.blocked.length + ":  " + o.blocked.join("  ") : "none"],
        ["Dials", (o.dials || []).join("  ")],
      ]));
    } else {
      const hdr = phEl("div", "ph-blk-hdr", "Context " + o.context);
      hdr.appendChild(phBadge("as written", "info"));
      blk.appendChild(hdr);
      if (o.lines && o.lines.length) {
        blk.appendChild(phEl("pre", "ph-pre", o.lines.join("\n") + (o.truncated ? "\n…" : "")));
      }
    }
    body.appendChild(blk);
  });
  if ((s.incoming || []).length) {
    body.appendChild(phEl("div", "ph-sub", "Incoming"));
    s.incoming.forEach(i => {
      const blk = phEl("div", "ph-blk");
      const hdr = phEl("div", "ph-blk-hdr", names[i.network] || i.network);
      hdr.appendChild(phBadge(i.mode, /straight|missing|no context/.test(i.mode) ? "warn" : "info"));
      blk.appendChild(hdr);
      blk.appendChild(phKV([
        ["Context", i.context],
        ["Trusted numbers", i.trusted_last4.length ? i.trusted_last4.map(x => "…" + x).join("  ") : ""],
        ["Connects to node", i.connects_node],
        ["Answered only while dashboard Phone tab is open", i.busy_when_tab_closed ? "yes" : (i.mode === "asks for a PIN" || i.mode.indexOf("straight") === 0 || i.mode.indexOf("only trusted") === 0 ? "no" : "")],
      ]));
      if (i.lines && i.lines.length) blk.appendChild(phEl("pre", "ph-pre", i.lines.join("\n")));
      body.appendChild(blk);
    });
  }
}

function phRenderHealth(s) {
  if (!s || !s.found) {
    phSetCard("health", "info", "—", "—");
    const b = phBody("health"); if (b) phNote(b, "No data");
    return;
  }
  const checks = (s.checks || []).map(c => Object.assign({}, c, {status: c.status === "ok" ? "pass" : c.status}));
  const overall = checks.some(c => c.status === "fail") ? "fail" : checks.some(c => c.status === "warn") ? "warn"
                : checks.some(c => c.status === "pass") ? "pass" : "info";
  renderRegChecks(checks, overall, {body: "ph-health-body", meta: "ph-health-meta", status: "ph-health-status"});
}

function phRenderCalls(s) {
  const body = phBody("calls");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("calls", "info", "N/A", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  phSetCard("calls", "info", "LOG", s.calls.length + " attempt" + (s.calls.length === 1 ? "" : "s"));
  if (!s.calls.length) { phNote(body, s.note || "No phone call attempts in the last 24 hours"); return; }
  const t = phEl("table", "ph-tbl");
  const head = phEl("tr");
  ["When", "Direction", "Network", "Number"].forEach(h => head.appendChild(phEl("th", "", h)));
  t.appendChild(head);
  s.calls.forEach(c => {
    const tr = phEl("tr");
    [c.time, c.direction, c.network_name, c.last4 ? "…" + c.last4 : ""].forEach(x => tr.appendChild(phEl("td", "", x)));
    t.appendChild(tr);
  });
  body.appendChild(t);
  body.appendChild(phEl("div", "ph-note", "Each row is a call attempt seen in the last 24 hours (a ring, not proof it was answered)"
                        + (s.sources && s.sources.length ? " · from " + s.sources.join(", ") : "")
                        + (s.note ? " · " + s.note : "")));
}

function phHoipLink(url) {
  if (!/^https:\/\/([a-z0-9-]+\.)*hamsoverip\.com\//i.test(url || "")) return "";
  const a = phEl("a", "btn btn-muted btn-sm ph-link", "Open HOIP website");
  a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
  return a;
}

function phCardText(pfx) {
  const body = document.getElementById("ph-" + pfx + "-body");
  if (!body) return "";
  const t = x => (x || "").replace(/\s+/g, " ").trim();
  const txt = id => t((document.getElementById(id) || {}).textContent);
  const card = body.closest(".s3-card");
  const title = card ? t((card.querySelector(".s3-card-title") || {}).textContent) : pfx;
  const sum = [txt("ph-" + pfx + "-status"), txt("ph-" + pfx + "-meta")].filter(x => x && x !== "—").join(", ");
  const out = ["Phone · " + title + (sum ? " — " + sum : ""),
               "sysmon v__VERSION__ · " + new Date().toLocaleString(), ""];
  const walk = el => {
    for (const n of el.children) {
      const c = n.classList;
      if (c.contains("ph-nocopy")) continue;
      if (c.contains("ph-kv")) {
        const kids = [...n.children];
        for (let i = 0; i + 1 < kids.length; i += 2) {
          const a = kids[i + 1].querySelector("a");
          out.push(t(kids[i].textContent) + ": " + (a ? a.href : t(kids[i + 1].textContent)));
        }
      } else if (c.contains("ast-check-row")) {
        const g = sel => t((n.querySelector(sel) || {}).textContent);
        out.push(t(n.lastElementChild ? n.lastElementChild.textContent : "") + " " +
                 g(".ast-check-title") + (g(".ast-check-value") ? " — " + g(".ast-check-value") : ""));
      } else if (c.contains("ast-check-note")) {
        out.push("    " + t(n.textContent));
      } else if (n.tagName === "TABLE") {
        n.querySelectorAll("tr").forEach(tr => out.push([...tr.children].filter(x => !x.classList.contains("ph-nocopy"))
                                                           .map(x => t(x.textContent)).join(" | ")));
      } else if (n.tagName === "PRE") {
        out.push(n.textContent.replace(/\s+$/, ""));
      } else if (c.contains("ph-blk-hdr")) {
        out.push("", [...n.childNodes].filter(x => !(x.classList && x.classList.contains("ph-nocopy")))
                                      .map(x => t(x.textContent)).filter(Boolean).join(" · "));
      } else if (c.contains("ph-sub")) {
        out.push("", t(n.textContent).toUpperCase());
      } else if (n.children.length && !c.contains("ph-note") && !c.contains("stub-panel")) {
        walk(n);
      } else if (t(n.textContent)) {
        out.push(t(n.textContent));
      }
    }
  };
  walk(body);
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

function rtHeader() {
  const vals = Object.values(_rtResult);
  if (!vals.length) return;
  const s = vals.includes("fail") ? "fail" : vals.includes("warn") ? "warn" : vals.includes("pass") ? "pass" : "info";
  phSetCard("rt", s, s.toUpperCase(), Object.keys(_rtResult).length + " of 3 run");
}

function rtChecks(boxId, key, checks) {
  const cs = (checks || []).map(c => Object.assign({}, c, {status: c.status === "ok" ? "pass" : c.status}));
  const st = cs.some(c => c.status === "fail") ? "fail" : cs.some(c => c.status === "warn") ? "warn"
           : cs.some(c => c.status === "pass") ? "pass" : "info";
  renderRegChecks(cs, st, {body: boxId});
  _rtResult[key] = st; rtHeader();
}

function phRenderAll() {
  const d = _phData;
  const live = phSec(d, "live"), nets = phSec(d, "networks");
  phRenderLive(live);
  phRenderNode(phSec(d, "node"));
  phRenderNets(nets, live);
  phRenderHoip(phSec(d, "hoip"));
  phRenderDialing(phSec(d, "dialing"), nets);
  phRenderHealth(phSec(d, "health"));
  phRenderModules(phSec(d, "modules"));
  phRenderCalls(phSec(d, "calls"));
}

function pmConfText(r) {
  if (r.conf === "-") return "any one";
  const w = (r.where || []).filter(x => x !== "modules.conf");
  return r.conf + (w.length ? " (" + w.join(", ") + ")" : "");
}

function pmCell(text, cls) { return phEl("td", cls || "", text); }

function pmTable(rows) {
  const t = phEl("table", "ph-tbl");
  const head = phEl("tr");
  ["Module", "modules.conf", "Now", "File"].forEach(h => head.appendChild(phEl("th", "", h)));
  head.appendChild(phEl("th", "ph-nocopy", "Change"));
  t.appendChild(head);
  rows.forEach(r => {
    const tr = phEl("tr");
    const name = pmCell(r.module + (r.locked ? "  🔒" : ""));
    name.title = r.why + (r.locked ? " -- locked: stopping it would take down the nodes or every call" : "");
    if (r.shown) name.title += " (running: " + r.shown + ")";
    tr.appendChild(name);
    tr.appendChild(pmCell(pmConfText(r), r.conf === "noload" ? "pm-warn" : (r.conf === "not listed" ? "pm-dim" : "")));
    tr.appendChild(pmCell(r.running === null ? "?" : (r.running ? "running" : "stopped"),
                          r.running === null ? "pm-dim" : (r.running ? "pm-ok" : "pm-bad")));
    tr.appendChild(pmCell(r.file === null ? "?" : (r.file ? "yes" : "MISSING"),
                          r.file === false ? "pm-bad" : ""));
    tr.appendChild(pmControls(r));
    tr.dataset.module = r.module;
    t.appendChild(tr);
  });
  return t;
}

function phRenderModules(s) {
  const body = phBody("mods");
  if (!body) return;
  if (!s || !s.found) {
    phSetCard("mods", "info", "—", "—");
    phNote(body, (s && s.note) || "No data");
    return;
  }
  const gs = s.groups || [];
  const conf = gs.filter(g => g.configured);
  let st = ["info", "—"];
  if (!s.asterisk_running) st = ["warn", "ASTERISK DOWN"];
  else if (conf.some(g => g.state === "missing")) st = ["fail", "MISSING"];
  else if (conf.length && conf.every(g => g.state === "ready")) st = ["pass", "READY"];
  else if (conf.some(g => g.state === "off")) st = ["info", "PART OFF"];
  phSetCard("mods", st[0], st[1], gs.map(g => (g.feature === "reverse" ? "reverse" : "autopatch") + ": " + g.state).join(" · "));
  if (s.note) phNote(body, s.note);
  _pmRoot = !!s.root;
  const rows = s.rows || [];
  gs.forEach(g => {
    const blk = phEl("div", "ph-blk");
    const hdr = phEl("div", "ph-blk-hdr");
    hdr.appendChild(phEl("span", "", g.label));
    const b = PM_STATE[g.state] || ["info", g.state.toUpperCase()];
    hdr.appendChild(phBadge(b[1], b[0]));
    hdr.dataset.feature = g.feature;
    hdr.appendChild(pmGroupButtons(g, rows));
    blk.appendChild(hdr);
    if (_pmLast && _pmLast.feature === g.feature)
      blk.appendChild(phEl("pre", "ph-pre " + (_pmLast.ok ? "" : "pm-warn"), _pmLast.lines.join("\n")));
    if (!g.configured) phNote(blk, "Not set up on this node, so nothing here is needed for it.");
    else if (g.state === "missing") phNote(blk, "Not running or missing: " + g.not_running.join(", "));
    else if (g.state === "off") phNote(blk, "Turned off: its own modules are set to noload and stopped.");
    const own = rows.filter(r => r.features.length === 1 && r.features[0] === g.feature);
    if (own.length) { blk.appendChild(phEl("div", "ph-sub", "Only this feature uses")); blk.appendChild(pmTable(own)); }
    body.appendChild(blk);
  });
  const shared = rows.filter(r => r.features.length > 1);
  if (shared.length) {
    const blk = phEl("div", "ph-blk");
    blk.appendChild(phEl("div", "ph-sub", "Used by both  (🔒 = locked)"));
    blk.appendChild(pmTable(shared));
    body.appendChild(blk);
  }
  const foot = [];
  if (s.moddir) foot.push("Module folder: " + s.moddir);
  else foot.push("Couldn't find Asterisk's module folder, so file checks show ?");
  foot.push("modules.conf autoload: " + (s.autoload ? "on (unlisted modules load too)" : "off (only listed modules load)"));
  foot.forEach(x => phNote(body, x));
  if (s.missing_files && s.missing_files.length) { body.appendChild(pmInstallBlock(s)); pmJobPoll(); }
  if (!s.root) phNote(body, "sysmon isn't running as root, so the buttons can't change anything.");
}

function pmInstallBlock(s) {
  const blk = phEl("div", "ph-blk");
  blk.id = "pm-install";
  blk.appendChild(phEl("div", "ph-sub", "Install options"));
  phNote(blk, "Missing from the Pi: " + s.missing_files.join(", "));
  const pk = s.packages || [];
  if (pk.length) {
    phNote(blk, "These come in the package " + pk.join(", ") + ". Reinstalling it puts the files back.");
    const row = phEl("div", "pm-btns ph-nocopy");
    row.style.padding = "0 .9rem .3rem";
    const lab = phEl("label", "pm-dim");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = true; cb.id = "pm-upd";
    lab.appendChild(cb); lab.appendChild(document.createTextNode(" Update the package list first"));
    row.appendChild(lab);
    if (_pmRoot) row.appendChild(pmBtn("Reinstall " + pk.join(", "), false, "Runs apt-get install --reinstall",
                                       () => pmReinstall(pk)));
    blk.appendChild(row);
  } else {
    phNote(blk, "Couldn't tell which package should have these files. Steps: 1) run  dpkg -l | grep asterisk  to see the Asterisk packages; 2) reinstall the main one with  sudo apt-get install --reinstall <package>; 3) press Re-check.");
  }
  phNote(blk, "Or by hand, in a terminal on the Pi:");
  blk.appendChild(phEl("pre", "ph-pre", "sudo apt-get update\nsudo apt-get install --reinstall -y " + (pk.join(" ") || "<package>")));
  const out = phEl("pre", "ph-pre ph-nocopy");
  out.id = "pm-job-out"; out.style.display = "none";
  blk.appendChild(out);
  return blk;
}

async function pmReinstall(pk) {
  const upd = !!(document.getElementById("pm-upd") || {}).checked;
  if (!await confirm(`Reinstall ${pk.join(", ")}?\n\n` + (upd ? "Updates the package list first, then reinstalls. " : "") +
                     "This can take a few minutes. If the package restarts Asterisk, any call drops and the nodes are briefly down.")) return;
  const r = await api("/api/phone/modules", "POST", {op: "reinstall", update: upd});
  if (!r || !r.ok) { toast((r && r.message) || "Couldn't start", "err", 7000); return; }
  toast(r.message || "Started", "ok");
  pmJobPoll();
}

async function pmJobPoll() {
  if (_pmJobTimer) { clearTimeout(_pmJobTimer); _pmJobTimer = null; }
  const j = await api("/api/net/job");
  const out = document.getElementById("pm-job-out");
  if (!j || j.action !== "phone_reinstall") return;
  if (out) {
    out.style.display = "";
    out.textContent = (j.lines || []).slice(-40).join("\n") + (j.status === "running" ? "\n… running (" + j.elapsed + "s)" : "");
    out.scrollTop = out.scrollHeight;
  }
  if (j.status === "running") { _pmJobTimer = setTimeout(pmJobPoll, 2000); return; }
  if (!out || out.dataset.done === j.finished_key) return;
  out.dataset.done = j.finished_key;
  toast(j.success ? "Reinstall finished" : "Reinstall failed -- see the output on the card", j.success ? "ok" : "err", 7000);
  if (j.success) setTimeout(pmReload, 1500);
}

function pmGroupButtons(g, rows) {
  const w = phEl("span", "pm-btns ph-nocopy");
  w.style.marginLeft = "auto";
  if (!g.configured || !_pmRoot) return w;
  w.appendChild(pmBtn("Activate", false, "Set load and start every module this feature needs",
                      () => pmFeature(g, rows, true)));
  w.appendChild(pmBtn("Deactivate", false, "Set noload and stop the modules only this feature uses",
                      () => pmFeature(g, rows, false)));
  return w;
}

async function pmFeature(g, rows, on) {
  const other = (_phData.sections && phSec(_phData, "modules") || {}).groups || [];
  const otherOn = other.some(x => x.feature !== g.feature && x.configured);
  const free = rows.filter(r => !r.locked && r.features.indexOf(g.feature) >= 0);
  let q;
  if (on) {
    q = `Activate ${g.label}?\n\nSets load in modules.conf for:\n  ${free.map(r => r.module).join("\n  ") || "(nothing)"}\n\nand starts any that are stopped. modules.conf is backed up first.`;
  } else {
    const alone = free.filter(r => r.features.length === 1 || !otherOn);
    const kept = free.filter(r => alone.indexOf(r) < 0);
    q = `Deactivate ${g.label}?\n\nSets noload and stops:\n  ${alone.map(r => r.module).join("\n  ") || "(nothing)"}` +
        (kept.length ? `\n\nLeft running (the other feature uses them):\n  ${kept.map(r => r.module).join("\n  ")}` : "") +
        `\n\nmodules.conf is backed up first.`;
  }
  if (!await confirm(q)) return;
  const r = await api("/api/phone/modules", "POST", {op: on ? "activate" : "deactivate", feature: g.feature});
  if (r) _pmLast = {feature: g.feature, lines: [r.message].concat(r.details || []), ok: r.ok};
  await pmShowResult(r);
  pmReload();
}

function pmBtn(label, dis, title, fn) {
  const b = phEl("button", "btn btn-muted btn-sm", label);
  b.disabled = !!dis; if (title) b.title = title;
  b.onclick = fn;
  return b;
}

function pmControls(r) {
  const td = phEl("td", "ph-nocopy");
  if (r.locked || !_pmRoot) return td;
  const w = phEl("div", "pm-btns");
  w.appendChild(pmBtn("Load", r.conf === "load", "Set 'load' in modules.conf (at next Asterisk restart)",
                      () => pmChange("conf", r.module, "load")));
  w.appendChild(pmBtn("No load", r.conf === "noload", "Set 'noload' in modules.conf (at next Asterisk restart)",
                      () => pmChange("conf", r.module, "noload")));
  w.appendChild(pmBtn("Start", r.running !== false || r.file === false,
                      r.file === false ? "The module file is missing -- see install options" : "Load it now",
                      () => pmChange("live", r.module, "start")));
  w.appendChild(pmBtn("Stop", r.running !== true, "Unload it now", () => pmChange("live", r.module, "stop")));
  td.appendChild(w);
  return td;
}

async function pmReload() {
  const d = await api("/api/phone?section=modules");
  if (!d || !d.ok || !d.sections || !d.sections.length) return;
  _phData.sections = (_phData.sections || []).filter(x => x.id !== "modules").concat(d.sections);
  phRenderModules(d.sections[0]);
}

async function pmShowResult(r) {
  if (!r) { toast("Server unreachable", "err"); return; }
  toast(r.message || (r.ok ? "Done" : "Failed"), r.ok ? "ok" : "err", r.ok ? 3500 : 7000);
  (r.warnings || []).forEach(w => toast(w, "err", 8000));
  if (!r.ok && r.restart_hint && await confirm("Restart Asterisk now?\n\nThis drops any call and briefly takes the nodes down.")) {
    const s = await api("/api/svc", "POST", {unit: "asterisk.service", action: "restart"});
    toast(s && s.ok ? "Asterisk restarting" : ((s && s.message) || "Restart failed"), s && s.ok ? "ok" : "err");
    setTimeout(pmReload, 6000);
  }
}

async function pmChange(op, module, value) {
  if (!await confirm(PM_ASK[op + ":" + value](module))) return;
  const r = await api("/api/phone/modules", "POST", {op: op, module: module, value: value});
  await pmShowResult(r);
  pmReload();
}

async function phPollLive() {
  const d = await api("/api/phone?section=live");
  if (!d || !d.ok || !d.sections || !d.sections.length) return;
  const secs = (_phData.sections || []).filter(x => x.id !== "live");
  _phData.sections = secs.concat(d.sections);
  phRenderLive(d.sections[0]);
  phRenderNets(phSec(_phData, "networks"), d.sections[0]);
}

// ---- card: Hams Over IP ----
function phRenderHoip(s) {
  const card = document.getElementById("ph-hoip-card");
  if (!card) return;
  if (!s || !s.found || !(s.accounts || []).length) { card.style.display = "none"; return; }
  card.style.display = "";
  const body = phBody("hoip");
  if (!body) return;
  let fails = 0, warns = 0, passes = 0;
  s.accounts.forEach((a, i) => {
    const blk = phEl("div", "ph-blk");
    blk.appendChild(phEl("div", "ph-blk-hdr", a.name + (a.callsign ? " · " + a.callsign : "")));
    blk.appendChild(phKV([
      ["Server", a.host + (a.port ? ":" + a.port : "")],
      ["Extension", a.extension || a.username],
      ["SIP username", a.username],
      ["Caller ID", a.caller_id],
      ["Incoming calls go to", a.context],
      ["Pi SIP port", a.sip_port ? "UDP " + a.sip_port : ""],
      ["Audio ports", a.rtp && a.rtp.length === 2 ? "UDP " + a.rtp[0] + "-" + a.rtp[1] : ""],
      ["Voicemail", a.voicemail_access ? "dial " + (a.voicemail_dial || a.voicemail_access) : ""],
      ["Website", phHoipLink(a.login_url)],
    ]));
    const box = phEl("div");
    box.id = "ph-hoip-checks-" + i;
    blk.appendChild(box);
    body.appendChild(blk);
    const checks = (a.checks || []).map(c => Object.assign({}, c, {status: c.status === "ok" ? "pass" : c.status}));
    fails  += checks.filter(c => c.status === "fail").length;
    warns  += checks.filter(c => c.status === "warn").length;
    passes += checks.filter(c => c.status === "pass").length;
    renderRegChecks(checks, null, {body: box.id});
  });
  const overall = fails ? "fail" : warns ? "warn" : passes ? "pass" : "info";
  phSetCard("hoip", overall, overall.toUpperCase(),
            fails ? fails + " issue" + (fails === 1 ? "" : "s")
                  : warns ? warns + " warning" + (warns === 1 ? "" : "s") : "all clear");
  phNote(body, "Password and PIN are never shown. The only thing sent from the Pi is one test packet to the HOIP server (no login); nothing on the Pi is changed.");
}

// ========================================================================
// TAB: Tune
// ========================================================================
// ---- general ----
function toggleRptCard() {
  toggleCard("rn-body", "rn-toggle");
}

async function loadRptNodes() {
  const body   = document.getElementById("rn-body");
  const status = document.getElementById("rn-status");
  if (!body) return;
  const resp = await api("/api/rpt/nodesettings");
  if (!resp || !resp.ok) {
    if (status) status.textContent = "unavailable";
    body.innerHTML = `<div class="stub-panel" style="min-height:60px">${esc((resp && resp.message) || "Could not read rpt.conf")}</div>`;
    return;
  }
  window.rnData = resp;
  if (status) status.textContent = `${resp.nodes.length} node${resp.nodes.length === 1 ? "" : "s"}`;
  renderRptNodes();
}

function rnSelect(id, list, cur, disabled) {
  const known = list.some(([v]) => v === cur);
  const extra = known ? "" : `<option value="${esc(cur)}" selected>${esc(cur || "(blank)")} – value in file</option>`;
  const opts = list.map(([v, t]) =>
    `<option value="${v}"${v === cur ? " selected" : ""}>${esc(t)}</option>`).join("");
  return `<select id="${id}" ${disabled ? "disabled" : ""} onchange="rnChanged('${id.split("-")[1]}')"
    style="font-family:var(--sans);font-size:var(--fs-base);background:var(--surface2);border:1px solid var(--border2);border-radius:.3rem;padding:.25rem .4rem;color:var(--text);max-width:100%">${extra}${opts}</select>`;
}

function rnSrc(src) {
  return `<div style="font-size:var(--fs-xs);color:#5a7898">${esc(src)}</div>`;
}

function rnValues(id) {
  const g = k => document.getElementById(`rn-${id}-${k}`);
  if (!g("duplex")) return null;
  return {duplex: g("duplex").value, telemdefault: g("telemdefault").value,
          hangtime: g("hangtime").value.trim(), linktolink: g("linktolink").checked ? "yes" : "no"};
}

function rnChanges(id) {
  const cur = rnValues(id), orig = window.rnOrig[id];
  if (!cur || !orig) return {};
  const out = {};
  for (const k of Object.keys(cur)) if (cur[k] !== orig[k]) out[k] = cur[k];
  return out;
}

function rnChanged(id, quiet) {
  const cur = rnValues(id);
  if (!cur) return;
  const row = (window.rnData && window.rnData.nodes || []).find(n => n.node === id);
  const ht = document.getElementById(`rn-${id}-hangtime`);
  if (ht && row && row.editable) ht.disabled = cur.duplex === "0";
  const warn = [];
  if (cur.duplex === "0") warn.push("hangtime has no effect with duplex 0.");
  if (cur.linktolink === "yes" && cur.duplex !== "0") warn.push("linktolink only works with duplex 0.");
  const hv = Number(cur.hangtime);
  if (cur.hangtime === "" || !Number.isInteger(hv) || hv < 0 || hv > 60000)
    warn.push("hangtime must be a whole number from 0 to 60000.");
  const w = document.getElementById(`rn-${id}-warn`);
  if (w) w.textContent = warn.join(" ");
  if (!quiet) rnDirtyAll();
}

function rnDirtyAll() {
  const d = window.rnData;
  const dirty = !!d && d.nodes.some(n => Object.keys(rnChanges(n.node)).length);
  const el = document.getElementById("rn-dirty");
  if (el) el.style.display = dirty ? "" : "none";
  return dirty;
}

async function saveRptNodes() {
  const d = window.rnData;
  const res = document.getElementById("rn-result");
  if (!d || !res) return;
  const todo = d.nodes.filter(n => n.editable && Object.keys(rnChanges(n.node)).length);
  if (!todo.length) { res.style.color = "var(--text)"; res.textContent = "No changes to save."; return; }
  for (const n of todo) {
    const c = rnChanges(n.node);
    if ("hangtime" in c) {
      const hv = Number(c.hangtime);
      if (c.hangtime === "" || !Number.isInteger(hv) || hv < 0 || hv > 60000) {
        res.style.color = "var(--red)";
        res.textContent = `Node ${n.node}: hangtime must be a whole number from 0 to 60000.`;
        return;
      }
    }
  }
  const reload = document.getElementById("rn-reload").checked;
  const btn = document.getElementById("rn-save-btn");
  if (btn) btn.disabled = true;
  res.style.color = "var(--text)";
  res.textContent = "Saving…";
  const lines = [];
  let allOk = true;
  for (let i = 0; i < todo.length; i++) {
    const n = todo[i];
    const r = await api("/api/rpt/nodesettings", "POST",
      {node: n.node, changes: rnChanges(n.node), reload: reload && i === todo.length - 1});
    const ok = !!(r && r.ok);
    allOk = allOk && ok;
    lines.push(`${ok ? "✓" : "✗"} ${(r && r.message) || `Node ${n.node}: no response`}`);
  }
  if (btn) btn.disabled = false;
  await loadRptNodes();
  const res2 = document.getElementById("rn-result");
  if (res2) {
    res2.style.color = allOk ? "var(--green)" : "var(--red)";
    res2.textContent = lines.join("\n");
  }
}

function toggleCard(bodyId, btnId) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  setCardOpen(bodyId, btnId, body.classList.contains("hidden"));
}

function toggleTuneCard() {
  toggleCard("su-tune-body", "su-tune-toggle");
}

function showRadioDialogError(msg) {
  const el = document.getElementById("radio-dialog-error");
  if (el) { el.textContent = "✗ " + msg; el.style.display = "block"; }
}

function closeRadioDialog() {
  document.getElementById("radio-dialog-overlay").style.display = "none";
  document.getElementById("radio-dialog-preset-row").style.display = "none";
  document.getElementById("radio-dialog-reload-row").style.display = "none";
  showRadioDialogFormView();
  window.radioDialogSlot = null;
  window.radioDialogSource = null;
  window.radioDialogMode = null;
  window.radioDialogDriver = null;
}

async function confirmRadioDialog() {
  if (window.radioDialogMode === "tunesave") {
    await confirmTuneSaveDialog();
    return;
  }

  const slot = window.radioDialogSlot;
  if (slot === null || slot === undefined) return;
  const title = document.getElementById("radio-dialog-title")?.value?.trim() || "";

  const driver = "simpleusb";
  const payload = {
    slot: slot,
    title: title,
    driver: driver,
    ...getTuneValues(),
  };

  try {
    const result = await api("/api/radio/presets", "POST", payload);
    if (!result || !result.ok) {
      toast(`✗ Failed: ${result?.message || "unknown error"}`, 0);
      return;
    }

    toast(`✓ ${result.message}`, 2);
    closeRadioDialog();

    await loadRadioPresets();
    updateRadioButtons();
    restoreActiveRadioButton();
  } catch (e) {
    toast(`✗ Error: ${e.message}`, 0);
  }
}

async function confirmTuneSaveDialog() {
  const driver = window.radioDialogDriver;
  if (!driver) return;

  if (window._radioRestartBusy) {
    showRadioDialogError("Restart in progress — try again shortly");
    return;
  }

  const fields  = getTuneValues();
  const slotVal = document.getElementById("radio-dialog-preset-select")?.value || "";
  const reload  = !!document.getElementById("radio-dialog-reload-toggle")?.checked;
  const title   = document.getElementById("radio-dialog-title")?.value?.trim() || "";

  const payload = { driver, ...fields, reload };
  if (slotVal) {
    payload.preset_slot  = parseInt(slotVal);
    payload.preset_title = title;
  }

  const saveBtn = document.getElementById("radio-dialog-save-btn");
  if (saveBtn) saveBtn.disabled = true;
  document.getElementById("radio-dialog-error").style.display = "none";

  try {
    const result = await api("/api/radio/tune/save", "POST", payload);
    if (!result || !result.ok) {
      showRadioDialogError(result?.message || "Unknown error — check if running as root");
      return;
    }

    if (result.preset_saved === false && result.preset_msg) {
      toast(`⚠ ${result.preset_msg}`, 0);
    }

    if (!reload) {
      toast("✓ Saved — " + result.message, 2);
      closeRadioDialog();
      refreshTuneCardAfterSave();
      return;
    }

    if (result.restart !== "started") {
      showRadioDialogError(`Saved, but restart not started: ${result.restart_msg || "unknown"}`);
      return;
    }

    document.getElementById("radio-dialog-form-view").style.display = "none";
    document.getElementById("radio-dialog-restart-view").style.display = "block";
    document.getElementById("radio-dialog-restart-msg").style.display = "none";
    document.getElementById("radio-dialog-restart-dismiss").style.display = "none";

    setRadioRestartBusy(true);
    const r = await pollRadioStackStatus();
    setRadioRestartBusy(false);

    if (r.ok) {
      toast("✓ Saved & Asterisk restarted — " + result.message, 2);
      closeRadioDialog();
      refreshTuneCardAfterSave();
    } else {
      const rmsg = document.getElementById("radio-dialog-restart-msg");
      if (rmsg) { rmsg.textContent = "⚠ " + r.msg; rmsg.style.display = "block"; }
      document.getElementById("radio-dialog-restart-dismiss").style.display = "inline-block";
    }
  } catch (e) {
    showRadioDialogError(e.message);
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

function refreshTuneCardAfterSave() {
  loadSimpleUSBTune();
  loadRadioPresets().then(() => {
    updateRadioButtons();
    restoreActiveRadioButton();
  });
}

// ---- card: Node Settings — rpt.conf ----
function renderRptNodes() {
  const body = document.getElementById("rn-body");
  const d = window.rnData;
  if (!body || !d) return;
  window.rnOrig = {};
  if (!d.nodes.length) {
    body.innerHTML = `<div class="stub-panel" style="min-height:60px">No nodes found in ${esc(d.path)}</div>`;
    return;
  }
  const lab = "font-size:var(--fs-base);color:var(--text);display:grid;gap:.2rem;align-content:start";
  const rows = d.nodes.map(n => {
    const v = n.values;
    const id = n.node;
    const dis = !n.editable;
    window.rnOrig[id] = {duplex: v.duplex.value, telemdefault: v.telemdefault.value,
                         hangtime: v.hangtime.value, linktolink: v.linktolink.value};
    const lock = dis ? `<div style="font-size:var(--fs-xs);color:var(--amber)">🔒 ${esc(n.locked)}</div>` : "";
    return `
      <div id="rn-row-${id}" style="padding:.7rem .8rem;background:rgba(100,120,140,0.06);border-radius:.4rem;border-left:3px solid var(--blue);display:grid;gap:.5rem">
        <div style="display:flex;gap:.6rem;align-items:baseline;flex-wrap:wrap">
          <strong style="color:var(--blue)">${esc(id)}</strong>
          <span style="font-size:var(--fs-xs);color:#5a7898">${esc(n.role)}${n.private ? " · private" : ""}</span>
        </div>
        ${lock}
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:.6rem">
          <label style="${lab}"><span>duplex</span>${rnSelect(`rn-${id}-duplex`, RN_DUPLEX, v.duplex.value, dis)}${rnSrc(v.duplex.source)}</label>
          <label style="${lab}"><span>telemdefault</span>${rnSelect(`rn-${id}-telemdefault`, RN_TELEM, v.telemdefault.value, dis)}${rnSrc(v.telemdefault.source)}</label>
          <label style="${lab}"><span>hangtime (ms)</span>
            <input type="number" id="rn-${id}-hangtime" value="${esc(v.hangtime.value)}" min="0" max="60000" step="100" ${dis ? "disabled" : ""}
              oninput="rnChanged('${id}')" onchange="rnChanged('${id}')"
              aria-label="hangtime in milliseconds (0-60000)"
              style="font-family:var(--sans);font-size:var(--fs-base);background:var(--surface2);border:1px solid var(--border2);border-radius:.3rem;padding:.3rem .5rem;width:7rem;color:var(--text)">
            <div style="font-size:var(--fs-xs);color:#5a7898">Default 5000 ms · range 0–60000 ms</div>
            ${rnSrc(v.hangtime.source)}</label>
          <label style="${lab}"><span>linktolink</span>
            <span style="display:flex;align-items:center;gap:.4rem"><input type="checkbox" id="rn-${id}-linktolink" ${v.linktolink.value === "yes" ? "checked" : ""} ${dis ? "disabled" : ""}
              onchange="rnChanged('${id}')"> full duplex radio link</span>
            ${rnSrc(v.linktolink.source)}</label>
        </div>
        <div id="rn-${id}-warn" style="font-size:var(--fs-xs);color:var(--amber)"></div>
      </div>`;
  }).join("");
  body.innerHTML = `
    <div style="display:grid;gap:1rem;padding:1rem">
      <div style="font-size:var(--fs-base);color:#5a7898;line-height:1.4">
        Values shown are what each node uses. The tag under each one says where it comes from:
        <strong>set on node</strong>, <strong>from</strong> a template, or the ASL3 <strong>default</strong>.
        Saving writes only changed settings into that node's own section of ${esc(d.path)}; templates are never changed.
      </div>
      ${rows}
      <div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center">
        <button class="btn btn-blue btn-sm" id="rn-save-btn" onclick="saveRptNodes()" title="Save changed settings">💾 Save</button>
        <button class="btn btn-muted btn-sm" id="rn-reset-btn" onclick="renderRptNodes()" title="Revert to the values in the file">↺ Reset</button>
        <label style="display:flex;align-items:center;gap:.4rem;font-size:var(--fs-base);color:var(--text)">
          <input type="checkbox" id="rn-reload"> Reload app_rpt after save</label>
        <span id="rn-dirty" style="display:none;font-size:var(--fs-base);color:var(--amber)">● unsaved changes</span>
      </div>
      <div style="font-size:var(--fs-xs);color:var(--amber)">Reloading app_rpt drops this system's current links.</div>
      <div id="rn-result" style="font-size:var(--fs-base);white-space:pre-line"></div>
    </div>`;
  d.nodes.forEach(n => rnChanged(n.node, true));
  rnDirtyAll();
}

// ========================================================================
// TAB: Hardware
// ========================================================================
// ---- general ----
async function loadHardware() {
  const d = await api("/api/hardware");
  if (!d) {
    document.getElementById("hw-ambe-meta").textContent  = "error";
    document.getElementById("hw-audio-meta").textContent = "error";
    document.getElementById("hw-pwr-meta").textContent   = "error";
    return;
  }
  renderAmbeSection(d.ambe  || []);
  renderAudioSection(d.audio || []);
  renderPowerSection(d.power || null);
  loadHardwareDiag();
}

async function loadHardwareDiag() {
  ["hw-usb-body", "hw-afs-body", "hw-alsa-body"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '<div class="stub-panel" style="min-height:48px">Loading…</div>';
  });
  const d = await api("/api/hardware/diag");
  if (!d) {
    ["hw-usb-body","hw-afs-body","hw-alsa-body"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="stub-panel">Server error</div>';
    });
    return;
  }
  _hwDiagData = d;
  renderUsbSection(d.lsusb         || {});
  renderAslFindSoundSection(d.asl_find_sound || {});
  renderAlsaSection(d.alsa         || {});
}

function _usbLineBadge(line) {
  
  const m = line.match(/ID\s+([0-9a-f]{4}):([0-9a-f]{4})/i);
  if (!m) return "";
  const key = `${m[1].toLowerCase()}:${m[2].toLowerCase()}`;
  const vid  = m[1].toLowerCase();
  if (_HW_AMBE_PAIRS[key]) {
    return `<span class="hw-usb-badge ambe">${_esc(_HW_AMBE_PAIRS[key])}</span>`;
  }
  if (_HW_FTDI_VIDS[vid]) {
    return `<span class="hw-usb-badge ftdi">possible AMBE</span>`;
  }
  return "";
}

function renderUsbSection(data) {
  const body = document.getElementById("hw-usb-body");
  const meta = document.getElementById("hw-usb-meta");
  if (!body) return;

  if (!data.available) {
    if (meta) meta.textContent = "unavailable";
    body.innerHTML =
      `<div class="hw-diag-note">${_esc(data.error || "lsusb not available")}</div>`;
    return;
  }

  const flat  = data.flat  || [];
  const tree  = data.tree  || "";
  if (meta) meta.textContent = flat.length + " device" + (flat.length !== 1 ? "s" : "");

  _hwUsbView = _hwUsbView || "flat";
  _renderUsbView(flat, tree);
}

function _renderUsbView(flat, tree) {
  const body = document.getElementById("hw-usb-body");
  if (!body) return;

  const btnFlat = document.getElementById("hw-usb-btn-flat");
  const btnTree = document.getElementById("hw-usb-btn-tree");
  if (btnFlat) btnFlat.classList.toggle("active", _hwUsbView === "flat");
  if (btnTree) btnTree.classList.toggle("active", _hwUsbView === "tree");

  body.innerHTML = "";

  if (_hwUsbView === "flat") {
    if (!flat.length) {
      body.innerHTML = '<div class="hw-diag-note">No USB devices found.</div>';
      return;
    }
    const pre = document.createElement("pre");
    pre.className = "hw-diag-pre";
    flat.forEach(line => {
      const span = document.createElement("span");
      span.style.display = "block";
      span.innerHTML = _esc(line) + _usbLineBadge(line);
      pre.appendChild(span);
    });
    body.appendChild(pre);
  } else {
    const pre = document.createElement("pre");
    pre.className = "hw-diag-pre";
    pre.textContent = tree || "(no tree output)";
    body.appendChild(pre);
  }
}

function hwUsbToggle(view) {
  _hwUsbView = view;
  if (!_hwDiagData) return;
  const data = _hwDiagData.lsusb || {};
  _renderUsbView(data.flat || [], data.tree || "");
}

function renderAslFindSoundSection(data) {
  const body = document.getElementById("hw-afs-body");
  const meta = document.getElementById("hw-afs-meta");
  if (!body) return;

  if (!data.installed) {
    if (meta) meta.textContent = "not installed";
    body.innerHTML =
      `<div class="hw-diag-note">${_esc(data.error ||
        "asl-find-sound not found — install asl3 or asl-apt-utils")}</div>`;
    return;
  }

  if (meta) meta.textContent = "installed";

  body.innerHTML = "";
  const note = document.createElement("div");
  note.className   = "hw-diag-note";
  note.textContent = "Run this tool when chan_simpleusb reports no audio device. " +
                     "It identifies C-Media USB sound cards compatible with chan_simpleusb.";
  body.appendChild(note);

  const pre = document.createElement("pre");
  pre.className   = "hw-diag-pre";
  pre.textContent = data.output || "(no output)";
  body.appendChild(pre);
}

function renderAlsaSection(data) {
  const body = document.getElementById("hw-alsa-body");
  const meta = document.getElementById("hw-alsa-meta");
  if (!body) return;

  if (!data.available) {
    if (meta) meta.textContent = "unavailable";
    body.innerHTML =
      `<div class="hw-diag-note">${_esc(data.error || "aplay not available")}</div>`;
    return;
  }

  const cardLines = (data.playback || "").split("\n")
    .filter(l => l.match(/^card\s+\d+/i)).length;
  if (meta) meta.textContent = cardLines + " card" + (cardLines !== 1 ? "s" : "");

  _hwAlsaView = _hwAlsaView || "playback";
  _renderAlsaView(data);
}

function _renderAlsaView(data) {
  const body = document.getElementById("hw-alsa-body");
  if (!body) return;

  const btnPb  = document.getElementById("hw-alsa-btn-pb");
  const btnCap = document.getElementById("hw-alsa-btn-cap");
  if (btnPb)  btnPb.classList.toggle("active",  _hwAlsaView === "playback");
  if (btnCap) btnCap.classList.toggle("active", _hwAlsaView === "capture");

  body.innerHTML = "";

  const note = document.createElement("div");
  note.className   = "hw-diag-note";
  note.textContent = _hwAlsaView === "playback"
    ? "Playback devices — set devusb = hw:CARD,0 in chan_simpleusb.conf (e.g. devusb = hw:1,0)"
    : "Capture devices — microphone/line-in paths for the same card index";
  body.appendChild(note);

  const pre = document.createElement("pre");
  pre.className = "hw-diag-pre";
  const text = _hwAlsaView === "playback"
    ? (data.playback || "(no playback devices)")
    : (data.capture  || "(no capture devices)");
  pre.textContent = text;
  body.appendChild(pre);
}

function hwAlsaToggle(view) {
  _hwAlsaView = view;
  if (!_hwDiagData) return;
  _renderAlsaView(_hwDiagData.alsa || {});
}

function renderPowerSection(pwr) {
  const body = document.getElementById("hw-pwr-body");
  const meta = document.getElementById("hw-pwr-meta");
  if (!body) return;

  if (!pwr) {
    if (meta) meta.textContent = "—";
    body.innerHTML =
      `<div class="stub-panel" style="min-height:60px">No data</div>`;
    return;
  }

  const ts   = pwr.throttle  || {};
  const temp = pwr.cpu_temp;
  const cv   = pwr.core_volts;

  if (meta) {
    if (!ts.available) {
      meta.textContent = "vcgencmd unavailable";
    } else {
      meta.textContent = ts.raw || "0x0";
    }
  }

  const cls = (status) => ({
    ok: "ok", warn: "warn", uv: "hot", throttled: "hot"
  }[status] || "");

  const pwrLabel = {
    ok:        "OK",
    warn:      "WARN — past events (see flags below)",
    uv:        "⚡ UNDER-VOLTAGE NOW",
    throttled: "⚡ THROTTLED NOW",
  }[ts.pwr_status] || "—";

  let cvHtml = "";
  if (cv != null) {
    cvHtml = `<tr>
      <td class="hw-pwr-lbl">Core Voltage</td>
      <td class="hw-pwr-val">
        ${cv.toFixed(4)}V
        <span class="hw-pwr-note">Internal SoC rail — not the 5V supply voltage</span>
      </td>
    </tr>`;
  }

  let tempHtml = "";
  if (temp != null) {
    const tc = temp > 75 ? "hot" : temp > 60 ? "warn" : "ok";
    const tn = temp > 80 ? "Hard throttle active above 80°C"
             : temp > 75 ? "Approaching throttle threshold"
             : temp > 60 ? "Soft temperature limit may engage"
             : "Normal operating range";
    tempHtml = `<tr>
      <td class="hw-pwr-lbl">SoC Temp</td>
      <td class="hw-pwr-val ${tc}">
        ${temp}°C
        <span class="hw-pwr-note">${_esc(tn)}</span>
      </td>
    </tr>`;
  }

  let html = `<table class="hw-pwr-tbl">`;

  if (ts.available) {
    html += `<tr>
      <td class="hw-pwr-lbl">Power Health</td>
      <td class="hw-pwr-val ${cls(ts.pwr_status)}">${_esc(pwrLabel)}</td>
    </tr>
    <tr>
      <td class="hw-pwr-lbl">Bitmask</td>
      <td class="hw-pwr-val">
        ${_esc(ts.raw)}
        <span class="hw-pwr-note">vcgencmd get_throttled — threshold ~4.63V</span>
      </td>
    </tr>`;
  } else {
    html += `<tr>
      <td class="hw-pwr-lbl">Power Health</td>
      <td class="hw-pwr-val dim">vcgencmd unavailable
        <span class="hw-pwr-note">install libraspberrypi-bin or check PATH</span>
      </td>
    </tr>`;
  }

  html += cvHtml + tempHtml + `</table>`;

  if (ts.available) {
    const flags = [
      { label: "UV now",       set: ts.uv_now,        kind: "now"  },
      { label: "Freq cap now", set: ts.freq_cap_now,  kind: "now"  },
      { label: "Throttled now",set: ts.throttled_now, kind: "now"  },
      { label: "Temp now",     set: ts.temp_now,      kind: "now"  },
      { label: "UV since boot",       set: ts.uv_ever,        kind: "ever" },
      { label: "Freq cap since boot", set: ts.freq_cap_ever,  kind: "ever" },
      { label: "Throttled since boot",set: ts.throttled_ever, kind: "ever" },
      { label: "Temp since boot",     set: ts.temp_ever,      kind: "ever" },
    ];
    html += `<div class="hw-diag-note">
      "now" = actively occurring at this moment; "since boot" = happened at
      least once since the last reboot, may not still be happening.
    </div>`;
    html += `<div class="hw-pwr-flags">`;
    flags.forEach(f => {
      const cls = f.set ? (f.kind === "now" ? "set-now" : "set-ever") : "clear";
      html += `<span class="hw-pwr-flag ${cls}">${_esc(f.label)}</span>`;
    });
    html += `</div>`;
  }

  body.innerHTML = html;
}

function renderAmbeSection(devices) {
  const body = document.getElementById("hw-ambe-body");
  const meta = document.getElementById("hw-ambe-meta");
  if (!body) return;

  if (!devices.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:50px">No AMBE devices detected</div>';
    meta.textContent = "none detected";
    return;
  }

  const primary = devices.find(d => d.ambe_known) || devices[0];
  const nodeStr = (primary.dev_nodes || []).join(" · ") || "no node";
  meta.textContent = primary.label + " · " + nodeStr;

  let html = "";

  if (devices.length > 1) {
    html += `<div class="hw-multi-warn">
      ⚠ ${devices.length} AMBE devices detected — showing first recognized
    </div>`;
  }

  const dotCls = primary.ambe_known ? "dot-on" : "dot-warn";
  const dotTitle = primary.ambe_known
    ? "Recognized AMBE VID:PID — confirmed dongle"
    : "Not a recognized AMBE VID:PID — treated as generic serial";
  const badge  = primary.ambe_known
    ? `<span class="hw-badge hw-badge-ambe" title="Confirmed AMBE dongle (known VID:PID)">AMBE</span>`
    : `<span class="hw-badge hw-badge-serial" title="Generic serial device — VID:PID not in the known AMBE list">SERIAL</span>`;
  const sym = primary.udev_symlink
    ? `<span style="color:var(--teal)"> → ${primary.udev_symlink}</span>` : "";
  const srcTag = primary.source === "watchdog"
    ? `<span class="hw-badge hw-badge-watchdog" title="Detected by DMRWatchMon's background scan, not this page's own live probe">watchdog</span>` : "";

  html += `<div class="hw-dev-row-hdr">
    <span class="dot ${dotCls}" title="${_esc(dotTitle)}"></span>
    <span style="font-family:var(--sans);font-size:.946rem;
      color:var(--text-bright);font-weight:bold">${_esc(primary.label)}</span>
    ${badge}
    <span style="font-family:var(--sans);font-size:var(--fs-xs);
      color:#fff;margin-left:.2rem">${_esc(nodeStr)}${sym}</span>
    ${srcTag}
    <span style="margin-left:auto">
      <button class="hw-gear-btn" id="hw-gear-btn"
        onclick="hwToggleActionZone(this)" title="Configure">⚙ Configure</button>
    </span>
  </div>`;

  const vid_pid = primary.vid && primary.pid
    ? `<span class="hw-dev-val dim">${_esc(primary.vid)}:${_esc(primary.pid)}</span>` : "";
  const mfr = primary.manufacturer
    ? `<div class="hw-dev-row">
        <span class="hw-dev-label">Mfr</span>
        <span class="hw-dev-val dim">${_esc(primary.manufacturer)}</span>
      </div>` : "";
  html += `<div class="hw-dev-info">
    <div class="hw-dev-row">
      <span class="hw-dev-label">Chip</span>
      <span class="hw-dev-val" id="hw-chip-name">${_esc(primary.product || primary.label)}</span>
    </div>
    <div class="hw-dev-row">
      <span class="hw-dev-label">VID:PID</span>
      ${vid_pid}
    </div>
    ${mfr}
    <div class="hw-dev-row">
      <span class="hw-dev-label">Node</span>
      <span class="hw-dev-val">${_esc(nodeStr)}</span>
      ${primary.udev_symlink
        ? `<span style="font-family:var(--sans);font-size:var(--fs-xs);color:#fff;margin-left:.4rem">→</span>
           <span class="hw-dev-val sym">${_esc(primary.udev_symlink)}</span>` : ""}
    </div>
  </div>`;

  html += `<div class="hw-section-lbl">AMBE Health</div>`;

  const layerDefs = [
    ["l1", "Kernel recognized"],
    ["l2", "Serial port accessible"],
    ["l3", "Process holding port"],
  ];
  for (const [key, label] of layerDefs) {
    const l = (primary.layers || {})[key] || {ok: null, detail: ""};
    html += _hwCheckRow(label, l.ok, l.detail, key);
  }

  const cached = _hwPingCache[primary.dev_nodes && primary.dev_nodes[0]];
  const l4 = cached || (primary.layers || {}).l4 || {ok: null, detail: "press Ping to test"};
  html += _hwCheckRow("Chip responding", l4.ok, l4.detail, "l4");
  html += _hwCheckLegend();
  if (l4.ok === null) {
    html += `<div class="hw-diag-note">
      ◌ here just means this session hasn't run the ping test yet — not a
      failure. It's manual-only because it needs exclusive access to the
      serial port: if AMBE is working normally, DVSwitch is already holding
      that port, so a ping right now would likely fail because the port is
      busy doing its job, not because the chip is bad. To get a real
      pass/fail, stop DVSwitch first, then Ping, then restart it.
    </div>`;
  }

  const symlinkVal = primary.udev_rule ? primary.udev_rule.symlink
    : (primary.product || primary.label || "").replace(/\s+/g, "");
  const hasRule = !!(primary.udev_rule);
  const devNode = (primary.dev_nodes || [])[0] || "";

  html += `<div class="hw-action-zone" id="hw-action-zone">
    
    <div class="hw-action-sub">
      <div class="hw-action-sub-title">Persistent Name (udev symlink)</div>
      <div class="hw-action-row">
        <input class="hw-action-inp" id="hw-symlink-inp"
          value="${_esc(symlinkVal)}" placeholder="e.g. ThumbDV" maxlength="32">
        <button class="btn btn-teal btn-sm"
          onclick="hwApplyUdev('${_esc(primary.vid)}','${_esc(primary.pid)}')">Apply</button>
        <button class="btn btn-muted btn-sm hw-remove-btn${hasRule ? " visible" : ""}"
          id="hw-remove-btn"
          onclick="hwDelUdev('${_esc(primary.vid)}','${_esc(primary.pid)}')">Remove</button>
      </div>
      <div class="hw-symlink-hint">
        Creates <span>/dev/${_esc(symlinkVal)}</span> — point DVSwitch config here
      </div>
    </div>
    
    <div class="hw-action-sub">
      <div class="hw-action-sub-title">Baud Rate</div>
      <div class="hw-action-row">
        <select class="hw-action-sel" id="hw-baud-sel">
          <option value="460800">460800 — standard</option>
          <option value="230400">230400 — early units</option>
        </select>
        <button class="btn btn-blue btn-sm"
          onclick="hwSetBaud('${_esc(devNode)}')">Set</button>
      </div>
      <div class="hw-action-note">
        stty is session-only — lost on reconnect and reboot.<br>
        Point DVSwitch config to /dev/&lt;symlink&gt; for persistence.
      </div>
    </div>
    
    <div class="hw-action-sub">
      <div class="hw-action-sub-title">Chip Ping — DVSI PROD_ID Query</div>
      <div class="hw-action-row">
        <button class="btn btn-purple btn-sm" id="hw-ping-btn"
          onclick="hwPing('${_esc(devNode)}')">⚡ Ping Chip</button>
        <span class="hw-ping-result" id="hw-ping-result"></span>
      </div>
      <div class="hw-action-note">
        Ping will fail if DVSwitch is holding the port — stop it first.
      </div>
    </div>
  </div>`;

  html += `<div class="hw-card-footer">
    <button class="btn btn-muted btn-sm" onclick="loadHardware()">↻ Re-check</button>
    <button class="hw-reset-chip-btn" id="hw-reset-btn"
      onclick="hwResetChip('${_esc(devNode)}')">⟳ Reset Chip</button>
    <span class="hw-reset-status" id="hw-reset-status"></span>
    <span class="hw-source-tag" style="margin-left:auto">
      source: ${_esc(primary.source || "live")}</span>
  </div>`;

  body.innerHTML = html;

  if (cached) _hwApplyPingResult(cached, false);
}

function _hwCheckRow(label, ok, detail, id) {
  const icon  = ok === true  ? ["ok",   "✓"]
              : ok === false ? ["fail", "✗"]
              : ok === "warn"? ["warn", "⚠"]
              :                ["pend", "◌"];
  const detCls = ok === true ? "ok" : ok === false ? "fail" : "";
  return `<div class="hw-check-row" id="hw-row-${id}">
    <span class="hw-check-icon ${icon[0]}" id="hw-icon-${id}">${icon[1]}</span>
    <span class="hw-check-label">${_esc(label)}</span>
    <span class="hw-check-detail ${detCls}" id="hw-det-${id}">${_esc(detail)}</span>
  </div>`;
}

function _hwCheckLegend() {
  return `<div class="hw-diag-note">
    ✓ pass &nbsp;·&nbsp; ✗ fail &nbsp;·&nbsp; ⚠ warning &nbsp;·&nbsp; ◌ not yet tested
  </div>`;
}

function renderAudioSection(devices) {
  const body = document.getElementById("hw-audio-body");
  const meta = document.getElementById("hw-audio-meta");
  if (!body) return;

  const usb = devices.filter(d => d.is_usb);

  if (!usb.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:50px">No USB audio devices detected</div>';
    meta.textContent = "none detected";
    return;
  }

  const primary = usb[0];
  meta.textContent = (primary.card_name || "USB Audio") +
                     " · hw:" + primary.card_index;

  let html = "";

  const dotCls = (primary.checks.c1.ok && primary.checks.c2.ok)
    ? "dot-on" : "dot-warn";
  const dotTitle = (primary.checks.c1.ok && primary.checks.c2.ok)
    ? "Recognized by the kernel and not held by another process"
    : "Not fully ready — see Audio Health rows below for which check is failing";
  html += `<div class="hw-dev-row-hdr">
    <span class="dot ${dotCls}" title="${_esc(dotTitle)}"></span>
    <span style="font-family:var(--sans);font-size:.946rem;
      color:var(--text-bright);font-weight:bold">${_esc(primary.card_name)}</span>
    <span class="hw-badge hw-badge-audio">USB AUDIO</span>
    <span style="font-family:var(--sans);font-size:var(--fs-xs);
      color:#fff;margin-left:.4rem">hw:${primary.card_index}</span>
  </div>`;

  const chipset = primary.vid && primary.pid
    ? `<div class="hw-dev-row">
        <span class="hw-dev-label">VID:PID</span>
        <span class="hw-dev-val dim">${_esc(primary.vid)}:${_esc(primary.pid)}</span>
      </div>` : "";
  const ttyRow = (primary.tty_nodes && primary.tty_nodes.length)
    ? `<div class="hw-dev-row">
        <span class="hw-dev-label">Node</span>
        <span class="hw-dev-val">${_esc(primary.tty_nodes.join(" · "))}</span>
      </div>` : "";
  html += `<div class="hw-dev-info">
    <div class="hw-dev-row">
      <span class="hw-dev-label">Card</span>
      <span class="hw-dev-val">${_esc(primary.card_name)}</span>
    </div>
    <div class="hw-dev-row">
      <span class="hw-dev-label">ALSA</span>
      <span class="hw-dev-val">hw:${primary.card_index},0</span>
    </div>
    ${chipset}
    ${ttyRow}
  </div>`;

  html += `<div class="hw-section-lbl">Audio Health</div>`;
  html += _hwCheckRow("Kernel recognized",    primary.checks.c1.ok, primary.checks.c1.detail, "au-c1");
  html += _hwCheckRow("Device free",          primary.checks.c2.ok, primary.checks.c2.detail, "au-c2");
  html += _hwCheckLegend();

  html += `<div class="hw-section-lbl">Compatibility</div>
  <div class="hw-diag-note">
    DVSwitch needs 8kHz mono capture+playback (AMBE bridging); ASL Node needs
    CM1xx-style GPIO (PTT/COS/CTCSS) for a full repeater-style node. A generic
    USB headset can pass one and not the other — that's normal, not a fault.
  </div>
  <div class="hw-compat-section">`;

  if (primary.dvswitch_ok) {
    html += `<div class="hw-compat-row">
      <span class="hw-compat-label">DVSwitch</span>
      <span class="hw-compat-ok">YES</span>
      <span class="hw-compat-reason">8kHz · S16_LE · mono · capture+playback</span>
    </div>`;
  } else {
    html += `<div class="hw-compat-row">
      <span class="hw-compat-label">DVSwitch</span>
      <span class="hw-compat-fail">NO</span>
      <span class="hw-compat-reason">${_esc(primary.dvswitch_fail_reason || "check failed")}</span>
    </div>`;
  }

  if (primary.asl_ok) {
    html += `<div class="hw-compat-row">
      <span class="hw-compat-label">ASL Node</span>
      <span class="hw-compat-ok">YES</span>
      <span class="hw-compat-reason">CM1xx GPIO capable (PTT · COS · CTCSS)</span>
    </div>`;
  } else {
    const aslCls = primary.dvswitch_ok ? "hw-compat-warn" : "hw-compat-fail";
    html += `<div class="hw-compat-row">
      <span class="hw-compat-label">ASL Node</span>
      <span class="${aslCls}">NO</span>
      <span class="hw-compat-reason">${_esc(primary.asl_fail_reason || "")}</span>
    </div>`;
    if (primary.dvswitch_ok) {
      html += `<div class="hw-compat-note">
        DVSwitch YES + ASL NO is expected for generic headsets — not a detection error
      </div>`;
    }
  }

  html += `</div>`;

  html += `<div class="hw-card-footer">
    <button class="btn btn-muted btn-sm" onclick="loadHardware()">↻ Re-check</button>
  </div>`;

  body.innerHTML = html;
}

function hwToggleActionZone(btn) {
  const zone = document.getElementById("hw-action-zone");
  if (!zone) return;
  const open = zone.classList.toggle("open");
  btn.classList.toggle("open", open);
  btn.textContent = open ? "✕ Close" : "⚙ Configure";
}

async function hwApplyUdev(vid, pid) {
  const inp = document.getElementById("hw-symlink-inp");
  if (!inp) return;
  const sym = inp.value.trim();
  if (!sym || !/^[A-Za-z0-9_\-]{1,32}$/.test(sym)) {
    toast("Invalid name — A-Z 0-9 _ - only, max 32 chars", "err"); return;
  }
  const d = await api("/api/hardware", "POST",
    {action:"set_udev", vid, pid, symlink: sym});
  if (!d) { toast("Request failed", "err"); return; }
  toast(d.message || (d.ok ? "Rule saved" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) {
    const hint = document.querySelector(".hw-symlink-hint span");
    if (hint) hint.textContent = "/dev/" + sym;
    const rm = document.getElementById("hw-remove-btn");
    if (rm) rm.classList.add("visible");
    loadHardware();
  }
}

async function hwDelUdev(vid, pid) {
  const d = await api("/api/hardware", "POST",
    {action:"del_udev", vid, pid});
  if (!d) { toast("Request failed", "err"); return; }
  toast(d.message || (d.ok ? "Rule removed" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) loadHardware();
}

async function hwSetBaud(dev) {
  const sel  = document.getElementById("hw-baud-sel");
  const baud = sel ? parseInt(sel.value, 10) : 460800;
  const d = await api("/api/hardware", "POST",
    {action:"set_tty", dev, baud});
  if (!d) { toast("Request failed", "err"); return; }
  toast(d.message || (d.ok ? "Baud set" : "Failed"), d.ok ? "ok" : "err");
}

async function hwPing(dev) {
  const btn    = document.getElementById("hw-ping-btn");
  const result = document.getElementById("hw-ping-result");
  if (!dev) { toast("No device node", "err"); return; }
  if (btn) { btn.disabled = true; btn.textContent = "⚡ Pinging…"; }
  if (result) { result.className = "hw-ping-result"; result.style.display = "none"; }

  const d = await api("/api/hardware", "POST", {action:"ping", dev});

  if (btn)  { btn.disabled = false; btn.textContent = "⚡ Ping Chip"; }
  if (!d)   { toast("Ping request failed", "err"); return; }

  _hwPingCache[dev] = {
    ok:     d.ok,
    detail: d.ok
      ? `${d.product_id} · ${d.baud_used} baud`
      : (d.error || "no response"),
  };
  _hwApplyPingResult(_hwPingCache[dev], true);
  toast(d.ok
    ? `Chip responding — ${d.product_id}`
    : (d.error || "No response"), d.ok ? "ok" : "err");
}

async function hwResetChip(dev) {
  const btn    = document.getElementById("hw-reset-btn");
  const status = document.getElementById("hw-reset-status");
  if (!dev) { toast("No device node", "err"); return; }

  if (btn) {
    btn.disabled      = true;
    btn.textContent   = "⟳ Working…";
    btn.style.opacity = ".55";
  }
  if (status) {
    status.className     = "hw-reset-status warn";
    status.textContent   = "stopping services…";
  }

  const d = await api("/api/hardware", "POST", {action: "reset_ambe", dev});

  if (btn) {
    btn.disabled      = false;
    btn.textContent   = "⟳ Reset Chip";
    btn.style.opacity = "";
  }

  if (!d) {
    toast("Reset request failed", "err");
    if (status) {
      status.textContent = "request failed";
      status.className   = "hw-reset-status fail";
    }
    return;
  }

  if (status) {
    if (d.ok) {
      const reEnum  = d.re_detected ? "re-enumerated ✓" : "sent — allow a moment";
      const svcPart = d.svc_summary ? ` · ${d.svc_summary}` : "";
      status.textContent = reEnum + svcPart;
      status.className   = "hw-reset-status " + (d.re_detected ? "ok" : "warn");
    } else {
      status.textContent = d.message || "reset failed";
      status.className   = "hw-reset-status fail";
    }
  }

  if (d.ok) {
    const failedRestarts = (d.restart_results || []).filter(r => !r.ok);
    if (failedRestarts.length) {
      const names = failedRestarts.map(r => r.unit).join(", ");
      toast(`Chip reset · failed to restart: ${names}`, "info");
    } else {
      toast(d.re_detected
        ? `Chip reset — services restarted · ${d.svc_summary || ""}`
        : `Reset sent · ${d.svc_summary || ""}`, "ok");
    }
    setTimeout(() => loadHardware(), 2500);
  } else {
    toast(d.message || "Reset failed", "err");
  }
}

function _hwApplyPingResult(cached, showInline) {
  const icon = document.getElementById("hw-icon-l4");
  const det  = document.getElementById("hw-det-l4");
  if (icon && det) {
    if (cached.ok) {
      icon.className   = "hw-check-icon ok";
      icon.textContent = "✓";
      det.className    = "hw-check-detail ok";
    } else {
      icon.className   = "hw-check-icon fail";
      icon.textContent = "✗";
      det.className    = "hw-check-detail fail";
    }
    det.textContent = cached.detail;
  }
  if (showInline) {
    const result = document.getElementById("hw-ping-result");
    if (result) {
      result.textContent = cached.detail;
      result.className   = "hw-ping-result " + (cached.ok ? "ok" : "fail");
    }
  }
  if (cached.ok) {
    const chipEl = document.getElementById("hw-chip-name");
    if (chipEl) {
      const prod = cached.detail.split(" · ")[0];
      if (prod) chipEl.textContent = prod;
    }
  }
}

// ========================================================================
// TAB: DVSM
// ========================================================================
// ---- general ----
async function loadDvsm() {
  
  ["direct", "iaxrpt", "node", "usrp"].forEach(k =>
    _dvsmSetBadge("dvsm-badge-" + k, "info", "...")
  );

  const d = await api("/api/dvsm");
  if (!d) {
    ["direct", "iaxrpt", "node", "usrp"].forEach(k =>
      _dvsmSetBadge("dvsm-badge-" + k, "fail", "ERR")
    );
    toast("DVSM: failed to load config", "warn");
    return;
  }

  const ipEl = document.getElementById("dvsm-node-ip");
  if (ipEl) ipEl.textContent = d.node_ip || "—";

  const a = d.accounts || {};
  _dvsmRenderAccount("dvsm-body-direct", "dvsm-badge-direct", a.direct_iax2 || {}, "direct");
  _dvsmRenderAccount("dvsm-body-iaxrpt", "dvsm-badge-iaxrpt", a.iaxrpt      || {}, "iaxrpt");
  _dvsmRenderAccount("dvsm-body-node",   "dvsm-badge-node",   a.node_mode   || {}, "node");
  _dvsmRenderAccount("dvsm-body-usrp",   "dvsm-badge-usrp",   a.usrp        || {}, "usrp");

  _dvsmRenderCompat("dvsm-body-compat", d.compat || []);
}

// ========================================================================
// TAB: STFU
// ========================================================================
// ---- general ----
function _stfuCopySecret(btn, fid) {
  dvsmCopy(btn, _stfuSecrets.get(fid) || "");
}

function _stfuReveal(eyeBtn, fid) {
  _toggleReveal(eyeBtn, fid, _stfuRevealed, _stfuSecrets);
}

function _stfuRenderInstall(bodyId, badgeId, inst) {
  _renderInstallTable(bodyId, badgeId, inst, {
    binDefault: "/opt/STFU/STFU",
    binLabel:   "Binary present and executable",
    binFix:     "Download STFU.armhf from DVSwitch GitHub → copy to /opt/STFU/STFU → chmod +x",
    unit:       "stfu",
    unitFix:    "Copy stfu.service to /lib/systemd/system/ → systemctl daemon-reload",
  });
}

function _stfuRenderConfig(bodyId, badgeId, pathId, cfgWrapper) {
  
  const fields = cfgWrapper.fields || [];
  
  let hasBmAddr = false, hasBmPw = false, hasDmrId = false;
  fields.forEach(f => {
    if (!f.label) return;
    if (f.label === "BM Server"   && f.value && f.value !== "—") hasBmAddr = true;
    if (f.label === "BM Password" && f.secret)                    hasBmPw   = true;
    if (f.label === "DMR ID"      && f.value && f.value !== "—") hasDmrId  = true;
  });
  const status = (hasBmAddr && hasBmPw && hasDmrId) ? "pass"
               : (hasBmAddr || hasDmrId)             ? "warn" : "fail";
  _dvsmSetBadge(badgeId, status);

  const pathEl = document.getElementById(pathId);
  if (pathEl && cfgWrapper.dvs_path) {
    pathEl.textContent = cfgWrapper.dvs_path + " [STFU]";
  }

  const body = document.getElementById(bodyId);
  if (!body) return;

  if (!cfgWrapper.raw_ok) {
    body.innerHTML =
      `<div class="dvsm-note err">&#x26A0; ${_esc(cfgWrapper.error || "DVSwitch.ini not readable")}</div>`;
    return;
  }
  if (!cfgWrapper.stfu_present) {
    body.innerHTML =
      `<div class="dvsm-note warn">&#x26A0; No [STFU] section found in DVSwitch.ini —` +
      ` paste the sample stanza below into the file and restart.</div>`;
    return;
  }

  let html   = "";
  let inTbl  = false;
  let cardKey = 0;

  fields.forEach(f => {
    
    if (f.group) {
      if (inTbl) { html += `</table>`; inTbl = false; }
      html += `<span class="dvsm-sec-lbl">${_esc(f.group)}</span>`;
      return;
    }

    if (!inTbl) { html += `<table class="dvsm-fields">`; inTbl = true; }

    const fid = `stfu-fv-${cardKey++}`;
    let valTd, actTd;

    if (f.masked) {
      _stfuRevealed.delete(fid);
      if (f.secret) {
        _stfuSecrets.set(fid, f.secret);
        valTd = `<td class="dvsm-val-cell">` +
                `<span id="${fid}" class="dvsm-val masked">` +
                `&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;</span></td>`;
        actTd = `<td class="dvsm-actions">` +
                `<button class="dvsm-eye" title="Reveal"` +
                ` onclick="_stfuReveal(this,'${fid}')">&#x1F441;</button>` +
                `<button class="dvsm-copy"` +
                ` onclick="_stfuCopySecret(this,'${fid}')">&#x2398;</button>` +
                `</td>`;
      } else {
        valTd = `<td class="dvsm-val-cell">` +
                `<span class="dvsm-val placeholder">${_esc(f.note || "not set")}</span></td>`;
        actTd = `<td class="dvsm-actions"></td>`;
      }
    } else {
      const raw     = (f.value !== null && f.value !== undefined) ? String(f.value) : "—";
      const noteHtml = f.note
        ? `<span style="display:block;font-size:var(--fs-xs);color:#fff;margin-top:.1rem">` +
          `${_esc(f.note)}</span>`
        : "";
      valTd = `<td class="dvsm-val-cell">` +
              `<span class="dvsm-val${raw === "—" ? " placeholder" : ""}">` +
              `${_esc(raw)}</span>${noteHtml}</td>`;
      actTd = raw !== "—"
        ? `<td class="dvsm-actions">` +
          `<button class="dvsm-copy" data-copyval="${_esc(raw)}"` +
          ` onclick="dvsmCopyAttr(this)">&#x2398;</button></td>`
        : `<td class="dvsm-actions"></td>`;
    }
    html += `<tr><td class="dvsm-lbl">${_esc(f.label)}</td>${valTd}${actTd}</tr>`;
  });
  if (inTbl) html += `</table>`;
  body.innerHTML = html;
}

function _stfuRenderSample(bodyId, rawText) {
  _stfuSampleText = rawText;
  _renderSampleCode(bodyId, rawText, /^\s*;/, /^([^=]+)(=)(.*)/);
}

function _stfuRenderCompat(bodyId, compat) {
  _renderCompatTable(bodyId, compat);
}

function stfuCopyStanza(btn) {
  dvsmCopy(btn, _stfuSampleText);
  
  const orig = btn.textContent;
  btn.textContent = "✓ Copied";
  setTimeout(() => { btn.textContent = orig; }, 1400);
}

async function stfuOpenEditor() {
  if (!_stfuDvsPath) { toast("DVSwitch.ini path unknown — refresh first", "warn"); return; }

  const taExisting = document.getElementById("stfu-textarea");
  if (taExisting && _stfuLoadedContent !== null && taExisting.value !== _stfuLoadedContent) {
    if (!await confirm("Discard unsaved changes to DVSwitch.ini?")) return;
  }

  const label = _stfuDvsPath.split("/").pop();

  const d = await api(`/api/dvswitch/file?label=${encodeURIComponent(label)}`);
  if (!d || !d.ok) {
    toast(d?.message || "Could not load DVSwitch.ini", "err"); return;
  }

  const ta = document.getElementById("stfu-textarea");
  if (ta) ta.value = d.content || "";
  _stfuLoadedContent = d.content || "";

  const pathEl = document.getElementById("stfu-editor-path");
  if (pathEl) pathEl.textContent = _stfuDvsPath;

  const wrap   = document.getElementById("stfu-editor-wrap");
  const togBtn = document.getElementById("stfu-editor-toggle");
  if (wrap)   { wrap.classList.add("open"); }
  if (togBtn) { togBtn.textContent = "▲ Collapse"; }

  if (wrap) wrap.closest(".s3-card")
    .scrollIntoView({ behavior: "smooth", block: "start" });

  if (ta) {
    const idx = ta.value.indexOf("[STFU]");
    if (idx !== -1) {
      ta.focus();
      ta.setSelectionRange(idx, idx + 6);
      const linesBefore = ta.value.substring(0, idx).split("\n").length - 1;
      const lh = parseFloat(getComputedStyle(ta).lineHeight) || 22;
      ta.scrollTop = linesBefore * lh;
    }
  }
}

function stfuToggleEditor() {
  const wrap   = document.getElementById("stfu-editor-wrap");
  const togBtn = document.getElementById("stfu-editor-toggle");
  if (!wrap) return;
  const opening = !wrap.classList.contains("open");
  wrap.classList.toggle("open", opening);
  if (togBtn) togBtn.textContent = opening ? "▲ Collapse" : "▼ Expand";
  if (opening) stfuOpenEditor();
}

async function stfuRestart() {
  if (!await confirm("Restart STFU service?")) return;
  const d = await api("/api/stfu", "POST", {action: "restart"});
  if (!d || !d.ok) { toast(d?.message || "Restart failed", "err"); return; }
  toast("STFU restarted", "ok");
}

function stfuDiscardEdit() {
  const wrap   = document.getElementById("stfu-editor-wrap");
  const togBtn = document.getElementById("stfu-editor-toggle");
  const ta     = document.getElementById("stfu-textarea");
  if (wrap)   wrap.classList.remove("open");
  if (togBtn) togBtn.textContent = "▼ Expand";
  if (ta)     ta.value = "";
}

async function loadStfu() {
  
  _stfuSecrets.clear();
  _stfuRevealed.clear();

  ["install", "config"].forEach(k =>
    _dvsmSetBadge("stfu-badge-" + k, "info", "...")
  );

  const d = await api("/api/stfu");
  if (!d || !d.ok) {
    ["install", "config"].forEach(k =>
      _dvsmSetBadge("stfu-badge-" + k, "fail", "ERR")
    );
    toast("STFU: failed to load config", "warn");
    return;
  }

  _stfuDvsPath = d.dvs_path || "";

  _stfuRenderInstall("stfu-body-install", "stfu-badge-install", d.install || {});
  _stfuRenderConfig("stfu-body-config",  "stfu-badge-config",
                    "stfu-config-path",  d.config || {});
  _stfuRenderCompat("stfu-body-compat",  d.compat || []);
  _stfuRenderSample("stfu-body-sample",  d.sample_stanza || "");
}

// ---- card: Edit DVSwitch.ini ----
async function stfuSave() {
  const ta = document.getElementById("stfu-textarea");
  if (!ta || !_stfuDvsPath) return;
  const label   = _stfuDvsPath.split("/").pop();
  const content = ta.value;
  if (!await confirm(`Save changes to ${label}?\n\nThis overwrites the file on disk.`)) return;
  const d = await api("/api/dvswitch/file", "POST", {label, content});
  if (!d || !d.ok) { toast(d?.message || "Save failed", "err"); return; }
  _stfuLoadedContent = content;
  toast(`Saved ${label}`, "ok");
}

async function stfuCopy() {
  const ta = document.getElementById("stfu-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

// ========================================================================
// TAB: M17
// ========================================================================
// ---- general ----
function _m17RenderInstall(bodyId, badgeId, inst) {
  _renderInstallTable(bodyId, badgeId, inst, {
    binDefault: "/opt/USRP2M17/USRP2M17",
    binLabel:   "Binary present and executable",
    binFix:     "See USRP2M17 Bridge Manual §5 — build/install USRP2M17 to /opt/USRP2M17/",
    unit:       "usrp2m17",
    unitFix:    "Copy usrp2m17.service to /lib/systemd/system/ → systemctl daemon-reload",
  });
}

function _m17RenderConfig(bodyId, badgeId, pathId, cfgWrapper) {
  const fields = cfgWrapper.fields || [];

  let hasCallsign = false, hasAddr = false;
  fields.forEach(f => {
    if (!f.label) return;
    if (f.label === "Callsign" && f.value) hasCallsign = true;
    if (f.label === "Address"  && f.value && f.value !== "0.0.0.0") hasAddr = true;
  });
  const status = (hasCallsign && hasAddr) ? "pass" : (hasCallsign || hasAddr) ? "warn" : "fail";
  _dvsmSetBadge(badgeId, status);

  const pathEl = document.getElementById(pathId);
  if (pathEl && cfgWrapper.ini_path) {
    pathEl.textContent = cfgWrapper.ini_path;
  }

  const body = document.getElementById(bodyId);
  if (!body) return;

  if (!cfgWrapper.raw_ok) {
    body.innerHTML =
      `<div class="dvsm-note err">&#x26A0; ${_esc(cfgWrapper.error || "USRP2M17.ini not readable")}</div>`;
    return;
  }

  let html   = "";
  let inTbl  = false;

  fields.forEach(f => {
    if (f.group) {
      if (inTbl) { html += `</table>`; inTbl = false; }
      html += `<span class="dvsm-sec-lbl">${_esc(f.group)}</span>`;
      return;
    }

    if (!inTbl) { html += `<table class="dvsm-fields">`; inTbl = true; }

    const raw      = (f.value !== null && f.value !== undefined) ? String(f.value) : "—";
    const noteHtml = f.note
      ? `<span style="display:block;font-size:var(--fs-xs);color:#fff;margin-top:.1rem">` +
        `${_esc(f.note)}</span>`
      : "";
    const valTd = `<td class="dvsm-val-cell">` +
      `<span class="dvsm-val${raw === "—" ? " placeholder" : ""}">` +
      `${_esc(raw)}</span>${noteHtml}</td>`;
    const actTd = raw !== "—"
      ? `<td class="dvsm-actions">` +
        `<button class="dvsm-copy" data-copyval="${_esc(raw)}"` +
        ` onclick="dvsmCopyAttr(this)">&#x2398;</button></td>`
      : `<td class="dvsm-actions"></td>`;
    html += `<tr><td class="dvsm-lbl">${_esc(f.label)}</td>${valTd}${actTd}</tr>`;
  });
  if (inTbl) html += `</table>`;
  body.innerHTML = html;
}

function _m17RenderCompat(bodyId, compat) {
  _renderCompatTable(bodyId, compat);
}

function _m17RenderSample(bodyId, rawText) {
  _m17SampleText = rawText;
  _renderSampleCode(bodyId, rawText, /^\s*;/, /^([^=]+)(=)(.*)/);
}

function _m17RenderHosts(bodyId, badgeId, hosts) {
  hosts = hosts || {};
  const body = document.getElementById(bodyId);
  if (!body) return;

  let status, badgeText;
  if (!hosts.present) {
    status = "fail"; badgeText = "MISSING";
  } else if (!hosts.ok) {
    status = "fail"; badgeText = "INVALID";
  } else if ((hosts.age_days || 0) > 1) {
    status = "warn"; badgeText = "STALE";
  } else {
    status = "pass"; badgeText = "OK";
  }
  _dvsmSetBadge(badgeId, status, badgeText);

  if (!hosts.present) {
    body.innerHTML = `<div class="stub-panel" style="min-height:60px">` +
      `Reflector list not found — click Update Now to fetch it.</div>`;
    return;
  }

  const rows = [];
  if (hosts.ok) {
    rows.push(["Usable reflectors", String(hosts.count)]);
    rows.push(["List generated", _esc(hosts.generated || "unknown")]);
  } else {
    rows.push(["Problem", _esc(hosts.error || "invalid file")]);
  }
  rows.push(["File age", (hosts.age_days == null ? "—" : `${hosts.age_days}d`)]);
  rows.push(["File size", `${(hosts.size || 0).toLocaleString()} bytes`]);

  body.innerHTML = `<table class="dvsm-compat-tbl">` +
    rows.map(([k, v]) => `<tr><td class="dvsm-ct-key">${k}</td>` +
      `<td class="dvsm-ct-enables" colspan="2">${v}</td></tr>`).join("") +
    `</table>`;
}

async function m17UpdateHosts() {
  _dvsmSetBadge("m17-badge-hosts", "info", "...");
  const d = await api("/api/m17", "POST", {action: "update_hosts"});
  if (!d || !d.ok) { toast(d?.message || "Reflector list update failed", "err"); }
  else { toast(d.message || "Reflector list updated", "ok"); }
  loadM17();
}

function m17CopyStanza(btn) {
  dvsmCopy(btn, _m17SampleText);
  const orig = btn.textContent;
  btn.textContent = "✓ Copied";
  setTimeout(() => { btn.textContent = orig; }, 1400);
}

async function m17Restart() {
  if (!await confirm("Restart usrp2m17 service?")) return;
  const d = await api("/api/m17", "POST", {action: "restart"});
  if (!d || !d.ok) { toast(d?.message || "Restart failed", "err"); return; }
  toast("usrp2m17 restarted", "ok");
  loadM17();
}

async function m17OpenEditor() {
  if (!_m17IniPath) { toast("USRP2M17.ini path unknown — refresh first", "warn"); return; }

  const taExisting = document.getElementById("m17-textarea");
  if (taExisting && _m17LoadedContent !== null && taExisting.value !== _m17LoadedContent) {
    if (!await confirm("Discard unsaved changes to USRP2M17.ini?")) return;
  }

  const label = _m17IniPath.split("/").pop();

  const d = await api(`/api/dvswitch/file?label=${encodeURIComponent(label)}`);
  if (!d || !d.ok) {
    toast(d?.message || "Could not load USRP2M17.ini", "err"); return;
  }

  const ta = document.getElementById("m17-textarea");
  if (ta) ta.value = d.content || "";
  _m17LoadedContent = d.content || "";

  const pathEl = document.getElementById("m17-editor-path");
  if (pathEl) pathEl.textContent = _m17IniPath;

  const wrap   = document.getElementById("m17-editor-wrap");
  const togBtn = document.getElementById("m17-editor-toggle");
  if (wrap)   { wrap.classList.add("open"); }
  if (togBtn) { togBtn.textContent = "▲ Collapse"; }

  if (wrap) wrap.closest(".s3-card")
    .scrollIntoView({ behavior: "smooth", block: "start" });

  if (ta) ta.focus();
}

function m17ToggleEditor() {
  const wrap   = document.getElementById("m17-editor-wrap");
  const togBtn = document.getElementById("m17-editor-toggle");
  if (!wrap) return;
  const opening = !wrap.classList.contains("open");
  wrap.classList.toggle("open", opening);
  if (togBtn) togBtn.textContent = opening ? "▲ Collapse" : "▼ Expand";
  if (opening) m17OpenEditor();
}

function m17DiscardEdit() {
  const wrap   = document.getElementById("m17-editor-wrap");
  const togBtn = document.getElementById("m17-editor-toggle");
  const ta     = document.getElementById("m17-textarea");
  if (wrap)   wrap.classList.remove("open");
  if (togBtn) togBtn.textContent = "▼ Expand";
  if (ta)     ta.value = "";
}

async function loadM17() {
  ["install", "config", "hosts"].forEach(k =>
    _dvsmSetBadge("m17-badge-" + k, "info", "...")
  );

  const d = await api("/api/m17");
  if (!d || !d.ok) {
    ["install", "config", "hosts"].forEach(k =>
      _dvsmSetBadge("m17-badge-" + k, "fail", "ERR")
    );
    toast("M17: failed to load config", "warn");
    return;
  }

  _m17RenderInstall("m17-body-install", "m17-badge-install", d.install || {});
  _m17RenderConfig("m17-body-config",  "m17-badge-config",
                    "m17-config-path",  d.config || {});
  _m17RenderCompat("m17-body-compat",  d.compat || []);
  _m17RenderHosts("m17-body-hosts", "m17-badge-hosts", d.hosts || {});
  _m17RenderSample("m17-body-sample",  d.sample_stanza || "");
  _m17IniPath = (d.config && d.config.ini_path) || "";
}

// ---- card: Edit USRP2M17.ini ----
async function m17Save() {
  const ta = document.getElementById("m17-textarea");
  if (!ta || !_m17IniPath) return;
  const label   = _m17IniPath.split("/").pop();
  const content = ta.value;
  if (!await confirm(`Save changes to ${label}?\n\nThis overwrites the file on disk. ` +
                      `Remember: the ASL-DVS-M17 dashboard will overwrite it again on the next connect/disconnect.`)) return;
  const d = await api("/api/dvswitch/file", "POST", {label, content});
  if (!d || !d.ok) { toast(d?.message || "Save failed", "err"); return; }
  _m17LoadedContent = content;
  toast(`Saved ${label}`, "ok");
}

async function m17Copy() {
  const ta = document.getElementById("m17-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

// ========================================================================
// TAB: Zello
// ========================================================================
// ---- general ----
function _zelloRenderInstall(bodyId, badgeId, inst) {
  _renderInstallTable(bodyId, badgeId, inst, {
    binDefault: "/opt/asl-zello-bridge/venv/bin/asl-zello-bridge",
    binLabel:   "Bridge installed (pip+venv or setup.py)",
    binFix:     "See README — pip+venv install (recommended) or deprecated setup.py",
    unit:       "asl-zello-bridge",
    unitFix:    "Copy asl-zello-bridge.service to /etc/systemd/system/ → systemctl daemon-reload",
  });
}

function _zelloRenderStatus(bodyId, status, inst) {
  const body = document.getElementById(bodyId);
  if (!body) return;

  const chip = (label, ok, warnOnly) => {
    const cls = ok ? "pass" : (warnOnly ? "warn" : "fail");
    const bc  = _dvsmBadgeClass(cls);
    return `<span class="dpbadge ${bc}" style="margin-right:.4rem">${_esc(label)}</span>`;
  };

  let html = `<div style="padding:.5rem .6rem">`;
  html += chip("Service: " + (inst.service_active ? "active" : "inactive"), inst.service_active);
  html += chip("Auth: " + (status.authenticated ? "logged in" : "not authenticated"), status.authenticated);
  html += chip("Channel: " + (status.channel_ready ? "ready" : "not ready"), status.channel_ready);
  if (status.currently_keyed) {
    html += chip("On air: " + (status.keyed_by || "unknown"), true);
  }
  html += `</div>`;

  const notes = [];
  if (status.last_activity) {
    const rel = status.last_activity_at ? ` (${_esc(status.last_activity_at)})` : "";
    notes.push(`<div class="dvsm-note src">Last activity: ${_esc(status.last_activity)}${rel}</div>`);
  }
  if (status.last_warn) {
    notes.push(`<div class="dvsm-note warn">&#x26A0; ${_esc(status.last_warn)}</div>`);
  }
  if (status.last_error) {
    notes.push(`<div class="dvsm-note err">&#x2717; ${_esc(status.last_error)}</div>`);
  }
  if (!status.journal_ok) {
    notes.push(`<div class="dvsm-note src">No journal history yet — status will populate once the service has logged something</div>`);
  }

  body.innerHTML = html + notes.join("");
}

function _zelloRenderSample(bodyId, rawText) {
  _zelloSampleText = rawText;
  _renderSampleCode(bodyId, rawText, /^\s*#/, /^(Environment=[^=]+)(=)(.*)/);
}

function zelloCopySample(btn) {
  dvsmCopy(btn, _zelloSampleText);
  const orig = btn.textContent;
  btn.textContent = "✓ Copied";
  setTimeout(() => { btn.textContent = orig; }, 1400);
}

async function loadZello() {
  ["install", "config"].forEach(k =>
    _dvsmSetBadge("zello-badge-" + k, "info", "...")
  );

  const d = await api("/api/zello");
  if (!d || !d.ok) {
    ["install", "config"].forEach(k =>
      _dvsmSetBadge("zello-badge-" + k, "fail", "ERR")
    );
    toast("Zello: failed to load config", "warn");
    return;
  }

  _zelloOverridePath = d.override_path || "";

  _zelloRenderInstall("zello-body-install", "zello-badge-install", d.install || {});
  _zelloRenderStatus("zello-body-status", d.status || {}, d.install || {});
  _dvsmRenderAccount("zello-body-config", "zello-badge-config", d.config || {}, "zello");
  _dvsmRenderCompat("zello-body-compat", d.compat || []);
  _zelloRenderSample("zello-body-sample", d.sample_override || "");

  const pathEl = document.getElementById("zello-config-path");
  if (pathEl) {
    pathEl.textContent = `${d.config?.mode === "work" ? "Work" : "Free"} mode — ${_zelloOverridePath}`;
  }

  window._zelloEditableCache = d.editable_content || "";
}

async function zelloOpenEditor() {
  const taExisting = document.getElementById("zello-textarea");
  if (taExisting && _zelloLoadedContent !== null && taExisting.value !== _zelloLoadedContent) {
    if (!await confirm("Discard unsaved changes to the Zello override?")) return;
  }

  const d = await api("/api/zello");
  if (!d || !d.ok) { toast(d?.message || "Could not load Zello config", "err"); return; }

  const ta = document.getElementById("zello-textarea");
  if (ta) ta.value = d.editable_content || "";
  _zelloLoadedContent = d.editable_content || "";
  _zelloOverridePath  = d.override_path || _zelloOverridePath;

  const pathEl = document.getElementById("zello-editor-path");
  if (pathEl) pathEl.textContent = _zelloOverridePath;

  const wrap   = document.getElementById("zello-editor-wrap");
  const togBtn = document.getElementById("zello-editor-toggle");
  if (wrap)   wrap.classList.add("open");
  if (togBtn) togBtn.textContent = "▲ Collapse";

  if (wrap) wrap.closest(".s3-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

function zelloToggleEditor() {
  const wrap   = document.getElementById("zello-editor-wrap");
  const togBtn = document.getElementById("zello-editor-toggle");
  if (!wrap) return;
  const opening = !wrap.classList.contains("open");
  wrap.classList.toggle("open", opening);
  if (togBtn) togBtn.textContent = opening ? "▲ Collapse" : "▼ Expand";
  if (opening) zelloOpenEditor();
}

async function zelloAction(action) {
  const verbs = {start: "Start", stop: "Stop", restart: "Restart"};
  const verb  = verbs[action] || action;
  if (!await confirm(`${verb} asl-zello-bridge?`)) return;
  const d = await api("/api/zello", "POST", {action});
  if (!d || !d.ok) { toast(d?.message || `${verb} failed`, "err"); return; }
  toast(`asl-zello-bridge: ${verb.toLowerCase()}ed`, "ok");
  setTimeout(loadZello, 1200);
}

function zelloDiscardEdit() {
  const wrap   = document.getElementById("zello-editor-wrap");
  const togBtn = document.getElementById("zello-editor-toggle");
  if (wrap)   wrap.classList.remove("open");
  if (togBtn) togBtn.textContent = "▼ Expand";
  _zelloLoadedContent = null;
}

// ---- card: Edit Override ----
async function zelloSave() {
  const ta = document.getElementById("zello-textarea");
  if (!ta) return;
  const content = ta.value;
  if (!await confirm(
    "Save changes to the Zello systemd override?\n\n" +
    "This overwrites override.conf on disk, including the plaintext password. " +
    "Won't take effect until you Restart.")) return;

  const d = await api("/api/zello", "POST", {action: "save_override_raw", content});
  if (!d || !d.ok) { toast(d?.message || "Save failed", "err"); return; }
  _zelloLoadedContent = content;
  toast("Saved — restart to apply", "ok");
  loadZello();
}

async function zelloCopy() {
  const ta = document.getElementById("zello-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

// ========================================================================
// TAB: SD Card
// ========================================================================
// ---- general ----
async function loadSdHealth() {
  const body = document.getElementById("sd-health-body");
  const meta = document.getElementById("sd-health-meta");
  const btn  = document.getElementById("sd-health-refresh");
  if (body) body.innerHTML =
    `<div class="stub-panel" style="min-height:80px">Reading SD card…</div>`;
  if (meta) meta.textContent = "checking…";
  if (btn)  btn.disabled = true;

  const d = await api("/api/sdcard");

  if (btn) btn.disabled = false;
  if (!d || !d.ok) {
    if (meta) meta.textContent = "error";
    if (body) body.innerHTML =
      `<div class="stub-panel" style="min-height:60px">Failed to read SD card status</div>`;
    return;
  }
  renderSdHealth(d);
}

function renderSdHealth(d) {
  const body = document.getElementById("sd-health-body");
  const meta = document.getElementById("sd-health-meta");
  if (!body) return;

  const dev  = d.device     || {};
  const id   = d.identity   || {};
  const cap  = d.capacity   || {};
  const fs   = d.filesystem || {};
  const io   = d.io         || {};
  const err  = d.errors     || {};
  const warn = d.warnings   || [];

  const row = (label, val, cls, note) => {
    if (val === undefined || val === null || val === "") return "";
    const noteHtml = note ? `<span class="hw-pwr-note">${_esc(note)}</span>` : "";
    return `<tr>
      <td class="hw-pwr-lbl">${_esc(label)}</td>
      <td class="hw-pwr-val ${cls || ""}">${_esc(val)}${noteHtml}</td>
    </tr>`;
  };
  const sect = (title, rows) =>
    rows ? `<div class="hw-pwr-lbl" style="padding:.55rem .9rem .15rem;
              color:#fff;letter-spacing:.12em">${_esc(title)}</div>
            <table class="hw-pwr-tbl">${rows}</table>` : "";

  const devName = (id.manufacturer && id.manufacturer !== "n/a")
    ? `${id.manufacturer} ${id.name && id.name !== "n/a" ? id.name : ""}`.trim()
    : (dev.disk_path || "unknown device");
  if (meta) {
    if (warn.length) {
      meta.textContent = `${devName} · ⚠ ${warn.length} issue${warn.length>1?"s":""}`;
      meta.style.color = "var(--red)";
    } else {
      meta.textContent = `${devName} · healthy`;
      meta.style.color = "var(--green)";
    }
  }

  let html = "";

  if (warn.length) {
    html += `<div class="hw-diag-pre" style="border-left:3px solid var(--red);
      color:var(--red);margin:.2rem 0 .4rem">` +
      warn.map(w => "⚠ " + _esc(w)).join("\n") + `</div>`;
  }

  html += sect("Device",
    row("Disk",        dev.disk_path) +
    row("Root source", dev.root_source));

  let idRows =
    row("Manufacturer", id.manufacturer) +
    row("Product",      id.name) +
    row("Serial",       id.serial) +
    row("Mfg date",     id.date) +
    row("FW / HW rev",  (id.fwrev && id.hwrev) ? `${id.fwrev} / ${id.hwrev}` : "") +
    row("Erase size",   id.preferred_erase_size);
  if (id.is_emmc) {
    idRows += row("Life time",   id.life_time, "warn");
    idRows += row("Pre-EOL info", id.pre_eol_info, "warn");
  }
  html += sect("Identity", idRows);

  const upct = cap.fs_used_pct;
  const ucls = upct == null ? "" : upct >= 90 ? "hot" : upct >= 75 ? "warn" : "ok";
  const ipct = cap.inodes_used_pct;
  const icls = ipct == null ? "" : ipct >= 90 ? "hot" : ipct >= 75 ? "warn" : "ok";
  html += sect("Capacity",
    row("Card size",   cap.size_h) +
    row("FS total",    cap.fs_total_h) +
    row("FS used",     upct != null ? `${cap.fs_used_h} (${upct}%)` : cap.fs_used_h, ucls) +
    row("FS available", cap.fs_avail_h) +
    row("Inodes used", ipct != null ? `${ipct}%` : null, icls));

  if (fs.available) {
    const stClean = String(fs.state || "").toLowerCase().includes("clean");
    html += sect("Filesystem (ext4)",
      row("State",          fs.state, stClean ? "ok" : "hot") +
      row("Mount count",    (fs.mount_count != null && fs.max_mount_count != null)
                              ? `${fs.mount_count} / ${fs.max_mount_count}` : fs.mount_count) +
      row("Last checked",   fs.last_checked) +
      row("Lifetime writes", fs.lifetime_writes) +
      row("Errors behavior", fs.errors_behavior));
  } else {
    html += sect("Filesystem (ext4)",
      row("Status", fs.error || "unavailable", "warn",
          "tune2fs reads the superblock — run sysmon as root for FS stats"));
  }

  if (io.available) {
    html += sect("I/O counters (since boot)",
      row("Bytes read",    io.bytes_read_h) +
      row("Bytes written", io.bytes_written_h,
          null, "Cumulative since last boot — wear proxy, not card-lifetime total"));
  }

  let errRows = "";
  if (err.ro_mount) {
    errRows += row("Root mount", err.ro_mount === "ro" ? "READ-ONLY" : "read-write",
                   err.ro_mount === "ro" ? "hot" : "ok",
                   err.ro_mount === "ro" ? "Filesystem dropped to read-only — likely corruption" : "");
  }
  if (err.available) {
    errRows += row("Kernel error lines", String(err.count),
                   err.count > 0 ? "warn" : "ok");
  } else if (err.note) {
    errRows += row("Kernel log", err.note, "warn");
  }
  html += sect("Errors", errRows);

  if (err.available && err.kernel_lines && err.kernel_lines.length) {
    html += `<div style="display:flex;align-items:center;justify-content:space-between;
      padding:.55rem .9rem .15rem">
      <span class="hw-pwr-lbl" style="padding:0;color:#fff;letter-spacing:.12em">
        Kernel storage log (last ${err.kernel_lines.length})</span>
      <button class="btn btn-muted btn-sm" onclick="sdKernelLogCopy()">⎘ Copy</button>
    </div>`;
    html += `<pre class="hw-diag-pre" id="sd-kernel-log-pre" style="max-height:220px;overflow:auto">` +
      err.kernel_lines.map(l => _esc(l)).join("\n") + `</pre>`;
  }

  body.innerHTML = html ||
    `<div class="stub-panel" style="min-height:60px">No SD card data</div>`;
}

async function sdKernelLogCopy() {
  const pre = document.getElementById("sd-kernel-log-pre");
  if (!pre || !pre.textContent) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(pre.textContent);
}

async function loadSdTests() {
  const d = await api("/api/sdcard/test");
  renderSdTests(d || {});
  if (d && d.status === "running" && !_sdTestTimer) {
    _sdTestTimer = setInterval(sdTestPoll, 1500);
  }
}

async function sdTestPoll() {
  const d = await api("/api/sdcard/test");
  renderSdTests(d || {});
  if (!d || d.status !== "running") {
    clearInterval(_sdTestTimer); _sdTestTimer = null;
  }
}

async function sdTestStart(test) {
  const label = "Run a read-only fsck (fsck -n) on the root partition?\n\n" +
    "Safe and non-destructive. Results are advisory because the root filesystem is mounted live.";
  if (!await confirm(label)) return;

  const d = await api("/api/sdcard/test", "POST", {action: "start", test: test});
  if (!d || !d.ok) { toast((d && d.message) || "Could not start test", "err"); }
  else { toast(d.message || "Started", "ok"); }
  await loadSdTests();
  if (d && d.ok && !_sdTestTimer) _sdTestTimer = setInterval(sdTestPoll, 1500);
}

async function sdTestCancel() {
  const d = await api("/api/sdcard/test", "POST", {action: "cancel"});
  if (d && d.message) toast(d.message, d.ok ? "ok" : "err");
  await loadSdTests();
}

function renderSdTests(d) {
  const body = document.getElementById("sd-test-body");
  const meta = document.getElementById("sd-test-meta");
  if (!body) return;

  const running = d.status === "running";
  if (meta) {
    meta.textContent = running ? `running ${d.test || ""}…`
      : (d.status && d.status !== "idle") ? `${d.test || ""}: ${d.status}` : "read-only";
    meta.style.color = running ? "var(--amber)"
      : d.status === "cancelled" ? "var(--text-dim)"
      : (d.status === "done" && /error/i.test(d.message || "")) ? "var(--red)"
      : d.status === "done" ? "var(--green)" : "";
  }

  let html = "";

  html += `<div class="hw-diag-pre" style="border-left:3px solid var(--amber);
    color:var(--amber);margin:.1rem 0 .5rem">⚠ Read-only diagnostics only. ` +
    `fsck -n on a mounted root is advisory.</div>`;

  html += `<div style="display:flex;gap:.4rem;flex-wrap:wrap;margin:.2rem 0 .5rem">`;
  if (running) {
    html += `<button class="btn btn-red btn-sm" onclick="sdTestCancel()">■ Cancel</button>`;
  } else {
    html += `<button class="btn btn-muted btn-sm" onclick="sdTestStart('fsck')">Run fsck -n (advisory)</button>`;
  }
  html += `</div>`;

  if (d.pct != null) {
    const pct = Math.max(0, Math.min(100, d.pct));
    html += `<div style="background:#152033;border-radius:3px;height:14px;overflow:hidden;margin:.2rem 0">
      <div style="height:100%;width:${pct}%;background:var(--amber);transition:width .4s"></div>
    </div>
    <div class="hw-pwr-note" style="margin:0 0 .3rem">${pct}% ${d.progress ? "· " + _esc(d.progress) : ""}</div>`;
  }

  if (d.status && d.status !== "idle") {
    const elapsed = d.elapsed != null ? ` · ${d.elapsed}s` : "";
    html += `<div class="hw-pwr-note" style="margin:.1rem 0 .4rem">
      <b>${_esc((d.test||"").toUpperCase())}</b> on ${_esc(d.target||"?")} — ${_esc(d.status)}${elapsed}
      ${d.message ? "<br>" + _esc(d.message) : ""}</div>`;
  }

  if (d.lines && d.lines.length) {
    html += `<pre class="hw-diag-pre" style="max-height:240px;overflow:auto">` +
      d.lines.map(l => _esc(l)).join("\n") + `</pre>`;
  }

  body.innerHTML = html;
}

// ========================================================================
// TAB: Security
// ========================================================================
// ---- general ----
function _secIcon(status) {
  if (status === "pass") return ["ok",   "✓"];
  if (status === "fail") return ["fail", "✗"];
  if (status === "warn") return ["warn", "⚠"];
  return ["pend", "◌"];
}

function _secRowDetail(c) {
  const d = c.detail || {};
  if (Array.isArray(d.binds) && d.binds.length) {
    const bad = d.binds.filter(b => b.verdict && b.verdict !== "pass");
    if (bad.length) {
      const b = bad[0];
      return `${b.addr || "?"}:${b.port} ${b.scope}` +
             (bad.length > 1 ? ` +${bad.length - 1}` : "");
    }
    const listening = d.binds.filter(b => b.scope !== "not_listening");
    return listening.length ? `${listening.length} bind(s), all local/VPN`
                            : "configured, not listening";
  }
  if (Array.isArray(d.units) && d.units.length) {
    const bad = d.units.filter(u => u.verdict !== "pass");
    return bad.length ? `${bad.length} unit(s) as root` : `${d.units.length} unit(s) ok`;
  }
  if (Array.isArray(d.reasons) && d.reasons.length) return d.reasons[0];
  if (Array.isArray(d.notes)   && d.notes.length)   return d.notes[0];
  if (Array.isArray(d.findings) && d.findings.length) return d.findings[0];
  if (d.jails && d.jails.length) return d.jails.join(", ");
  return "";
}

function _secRefs(refs) {
  if (!Array.isArray(refs) || !refs.length) return "";
  const items = refs.map(r => r && r.url
    ? `<a href="${_esc(r.url)}" target="_blank" rel="noopener noreferrer"
         >&#8599; ${_esc(r.label)}</a>`
    : `<span class="sec-ref-plain">&#8226; ${_esc((r && r.label) || "")}</span>`
  ).join("");
  return `<span class="sec-note-h">References</span>
    <span class="sec-refs">${items}</span>`;
}

function _secNoteWhy(c) {
  const p = t => `<span class="sec-note-p">${_esc(t)}</span>`;
  return `<div class="ast-check-note sec-note" id="sec-why-${_esc(c.id)}"${
      _secOpen.has(c.id + ":why") ? "" : " hidden"}>
    <span class="sec-note-h">Severity</span>
    <span class="sec-sev ${_esc(c.severity)}">${_esc(c.severity)}</span>
    <span class="sec-note-h">What this check reads</span>${p(c.source)}
    <span class="sec-note-h">What the result means</span>${p(c.meaning)}
    ${c.risk ? `<span class="sec-note-h">Why it matters</span>${p(c.risk)}` : ""}
    <span class="sec-note-h">How to fix it</span>${p(c.remediation)}
    ${_secRefs(c.references)}
  </div>`;
}

function _secNoteRaw(c) {
  let body;
  try { body = JSON.stringify(c.detail, null, 2); }
  catch (e) { body = String(c.detail); }
  const redacted = c.sensitive
    ? `<div class="sec-redacted">&#128274; This check reads credential
         material. What you see below is all the backend produces for it:
         booleans and lengths, redacted server-side before the response was
         built. No secret value is sent to this page.</div>`
    : "";
  return `<div class="ast-check-note sec-note" id="sec-raw-${_esc(c.id)}"${
      _secOpen.has(c.id + ":raw") ? "" : " hidden"}>
    <span class="sec-note-h">Raw check output</span>
    ${redacted}
    <div class="sec-note-raw">${_esc(body)}</div>
  </div>`;
}

function _secRow(c) {
  const [icls, ichar] = _secIcon(c.status);
  const dcls = c.status === "pass" ? "ok" : c.status === "fail" ? "fail"
             : c.status === "warn" ? "warn" : "";
  const id   = _esc(c.id);
  const whyOn = _secOpen.has(c.id + ":why") ? " on" : "";
  const rawOn = _secOpen.has(c.id + ":raw") ? " on" : "";
  return `<div class="hw-check-row" id="sec-row-${id}">
    <span class="hw-check-icon ${icls}">${ichar}</span>
    <span class="hw-check-label">${_esc(c.label)}</span>
    <span class="sec-row-actions">
      <span class="sec-row-detail ${dcls}" title="${_esc(_secRowDetail(c))}"
        >${_esc(_secRowDetail(c))}</span>
      <button class="ast-toggle${whyOn}" id="sec-btn-why-${id}"
              aria-expanded="${_secOpen.has(c.id + ":why")}"
              title="source, meaning and fix"
              onclick="secToggle('${id}','why')">?</button>
      <button class="ast-toggle${rawOn}" id="sec-btn-raw-${id}"
              aria-expanded="${_secOpen.has(c.id + ":raw")}"
              title="raw check output"
              onclick="secToggle('${id}','raw')">raw</button>
    </span>
  </div>` + _secNoteWhy(c) + _secNoteRaw(c);
}

function _secSetCard(layerId, layer, checks) {
  const body   = document.getElementById("sec-body-" + layerId);
  const badge  = document.getElementById("sec-status-" + layerId);
  const meta   = document.getElementById("sec-meta-" + layerId);
  if (!body) return;

  if (badge) {
    const st = (layer && layer.status) || "info";
    badge.className   = "reg-card-status " + (st === "not_implemented" || st === "error" ? "info" : st);
    badge.textContent = st.replace("_", " ").toUpperCase();
  }
  if (meta) {
    const c = (layer && layer.counts) || {};
    meta.textContent = c.fail ? `${c.fail} issue${c.fail === 1 ? "" : "s"}`
                     : c.warn ? `${c.warn} warning${c.warn === 1 ? "" : "s"}`
                     : c.total ? "all clear" : "—";
  }
  if (!checks.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:60px">No checks in this layer</div>';
    return;
  }
  body.innerHTML = checks.map(_secRow).join("");
}

function _secShowUnreachable() {
  _SEC_LAYER_IDS.forEach(l => {
    const body = document.getElementById("sec-body-" + l);
    if (body) body.innerHTML =
      '<div class="stub-panel" style="min-height:60px">Server unreachable</div>';
    const badge = document.getElementById("sec-status-" + l);
    if (badge) { badge.className = "reg-card-status"; badge.textContent = "—"; }
  });
  ["pass","warn","fail","total"].forEach(k => {
    const el = document.getElementById("sec-n-" + k);
    if (el) el.textContent = "–";
  });
}

function secRender(d) {
  _secData = d;
  const sum = d.summary || {};
  const set = (id, v) => { const el = document.getElementById(id);
                            if (el) el.textContent = (v === undefined ? "–" : v); };
  set("sec-n-pass",  sum.pass);
  set("sec-n-warn",  sum.warn);
  set("sec-n-fail",  sum.fail);
  set("sec-n-total", sum.total);

  const ts = document.getElementById("sec-last-run");
  if (ts) {
    const when = d.last_run_timestamp
      ? new Date(d.last_run_timestamp * 1000).toLocaleTimeString()
      : "never";
    ts.textContent = d.cached
      ? `last run ${when} · cached (${d.cache_age_sec || 0}s old)`
      : `last run ${when}`;
  }

  const byLayer = {};
  (d.layers || []).forEach(l => { byLayer[l.id] = l; });
  _SEC_LAYER_IDS.forEach(l => {
    _secSetCard(l, byLayer[l], (d.checks || []).filter(c => c.layer === l));
  });
}

function _secSetBusy(busy) {
  _secBusy = busy;
  const all = document.getElementById("sec-rerun-all");
  if (all) {
    all.disabled    = busy;
    all.textContent = busy ? "Running…" : "↻ Re-run checks";
  }
  document.querySelectorAll(".sec-card-rerun").forEach(b => { b.disabled = busy; });
  const bar = document.querySelector("#panel-security .sec-summary");
  if (bar) bar.classList.toggle("sec-busy", busy);
}

async function _secFetch(refresh) {
  if (_secBusy) return;
  _secSetBusy(true);
  try {
    const d = await api("/api/security/checks" + (refresh ? "?refresh=1" : ""));
    if (!d || !d.ok) { _secShowUnreachable(); return; }
    secRender(d);
  } finally {
    _secSetBusy(false);
  }
}

function secRerun() { _secFetch(true); }

// ========================================================================
// TAB: Edit
// ========================================================================
// ---- general ----
function edToggleAslDvs() {
  _edAslOpen = !_edAslOpen;
  const body    = document.getElementById("ed-asl-body");
  const hdr     = document.getElementById("ed-asl-hdr");
  const chevron = document.getElementById("ed-asl-chevron");
  if (!body) return;

  if (_edAslOpen) {
    hdr?.classList.add("open");
    body.classList.remove("collapsed");
    body.style.maxHeight = body.scrollHeight + "px";
    body.addEventListener("transitionend", function _edAslUnfreeze(e) {
      if (e.propertyName !== "max-height") return;
      body.removeEventListener("transitionend", _edAslUnfreeze);
      if (_edAslOpen) body.style.maxHeight = "none";
    });
    edAslDvsLoad();
  } else {
    hdr?.classList.remove("open");
    body.style.maxHeight = body.scrollHeight + "px";
    requestAnimationFrame(() => requestAnimationFrame(() => {
      body.style.maxHeight = "0";
      body.classList.add("collapsed");
    }));
  }
}

function edTogglePinned() {
  _edPinnedOpen = !_edPinnedOpen;
  const body    = document.getElementById("ed-pinned-body");
  const hdr     = document.getElementById("ed-pinned-hdr");
  const chevron = document.getElementById("ed-pinned-chevron");
  if (!body) return;

  if (_edPinnedOpen) {
    hdr?.classList.add("open");
    body.classList.remove("collapsed");
    body.style.maxHeight = body.scrollHeight + "px";
    body.addEventListener("transitionend", function _edPinnedUnfreeze(e) {
      if (e.propertyName !== "max-height") return;
      body.removeEventListener("transitionend", _edPinnedUnfreeze);
      if (_edPinnedOpen) body.style.maxHeight = "none";
    });
  } else {
    hdr?.classList.remove("open");
    body.style.maxHeight = body.scrollHeight + "px";
    requestAnimationFrame(() => requestAnimationFrame(() => {
      body.style.maxHeight = "0";
      body.classList.add("collapsed");
    }));
  }
}

async function edReload() {
  const d = await api("/api/config");
  if (!d || !d.ok) { toast("Failed to load config", "err"); return; }

  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val || "";
  };
  set("ed-callsign", d.identity?.callsign);
  set("ed-node",     d.identity?.node);
  set("ed-label",    d.identity?.label);
  set("ed-port",     d.server?.port);
  set("ed-host",     d.server?.host);
  set("ed-cpu-warn", d.thresholds?.cpu_warn_pct);
  set("ed-rss-warn", d.thresholds?.rss_warn_mb);
  set("ed-nr-warn",  d.thresholds?.nr_warn);
  set("ed-nr-crit",  d.thresholds?.nr_crit);

  const ta = document.getElementById("ed-pinned");
  if (ta) ta.value = d.services?.pinned || "";

  edSetTabVis(d.ui?.enabled_tabs);

  edCountPinned();
  edClearErrors();
  edSetStatus("");
  _edDirty = false;
  edUpdateSaveBtn(true);
}

function edSetTabVis(enabled) {
  const set = new Set(Array.isArray(enabled) ? enabled : TABS);
  for (const t of TABS) {
    if (ED_LOCKED_TABS.includes(t)) continue;
    const chk = document.getElementById("tabchk-" + t);
    if (chk) chk.checked = set.has(t);
  }
}

function edGetTabVis() {
  const out = [];
  for (const t of TABS) {
    if (ED_LOCKED_TABS.includes(t)) { out.push(t); continue; }
    const chk = document.getElementById("tabchk-" + t);
    if (chk && chk.checked) out.push(t);
  }
  return out;
}

function edTabVisChanged() {
  _edDirty = true;
  edSetStatus("");
}

function edValidate() {
  _edDirty = true;
  let valid = true;

  const cs = (document.getElementById("ed-callsign")?.value || "").trim();
  valid = edField("ed-callsign", "ed-callsign-err",
    cs.length >= 1 && cs.length <= 9 && /^[A-Z0-9 /.\-]+$/i.test(cs),
    "A-Z 0-9 - / . only, max 9 chars") && valid;

  const node = (document.getElementById("ed-node")?.value || "").trim();
  valid = edField("ed-node", "ed-node-err",
    /^\d{1,7}$/.test(node),
    "Numeric only, 1–7 digits") && valid;

  const port = (document.getElementById("ed-port")?.value || "").trim();
  const portN = parseInt(port);
  valid = edField("ed-port", "ed-port-err",
    /^\d+$/.test(port) && portN >= 1024 && portN <= 65535,
    "Integer 1024–65535") && valid;

  const host = (document.getElementById("ed-host")?.value || "").trim();
  valid = edField("ed-host", "ed-host-err",
    host.length > 0, "Must not be empty") && valid;

  edUpdateSaveBtn(valid);
  return valid;
}

function edField(inpId, errId, ok, errMsg) {
  const inp = document.getElementById(inpId);
  const err = document.getElementById(errId);
  if (inp) inp.classList.toggle("invalid", !ok);
  if (err) {
    err.textContent = ok ? "" : errMsg;
    err.classList.toggle("show", !ok);
  }
  return ok;
}

function edClearErrors() {
  ED_FIELDS.forEach(f => {
    const inp = document.getElementById(f.id);
    if (inp) inp.classList.remove("invalid");
  });
  document.querySelectorAll(".ed-err").forEach(el => {
    el.textContent = "";
    el.classList.remove("show");
  });
}

function edUpdateSaveBtn(valid) {
  const btn = document.getElementById("ed-save-btn");
  if (btn) btn.disabled = !valid;
}

function edSetStatus(msg, ok) {
  const el = document.getElementById("ed-status");
  if (!el) return;
  el.textContent = msg;
  el.style.color = ok === true  ? "var(--green)"
                 : ok === false ? "var(--red)"
                 : "#3a5278";
}

async function edSave() {
  if (!edValidate()) {
    toast("Fix validation errors before saving", "err"); return;
  }
  const btn = document.getElementById("ed-save-btn");
  if (btn) btn.disabled = true;
  edSetStatus("Saving…");

  const payload = {};
  ED_FIELDS.forEach(f => {
    const el = document.getElementById(f.id);
    if (el && el.value.trim() !== "") payload[f.key] = el.value.trim();
  });
  const ta = document.getElementById("ed-pinned");
  if (ta) payload["services.pinned"] = ta.value;

  const visTabs = edGetTabVis();
  payload["ui.enabled_tabs"] = visTabs.join(",");

  const d = await api("/api/config", "POST", payload);
  if (btn) btn.disabled = false;

  if (!d) {
    edSetStatus("Server unreachable", false);
    toast("Server unreachable", "err");
    return;
  }
  if (!d.ok) {
    const errMsg = (d.errors || [d.message || "Save failed"]).join("; ");
    edSetStatus(errMsg, false);
    toast(errMsg, "err");
    return;
  }

  _savedEnabledTabs = visTabs;
  _applyTabVisibilityGated();

  edSetStatus("Saved ✓", true);
  toast("Config saved", "ok");
  _edDirty = false;

  const nrWarn = document.getElementById("ed-nr-warn");
  const nrCrit = document.getElementById("ed-nr-crit");
  if (nrWarn) _cfg_nr_warn = nrWarn.value;
  if (nrCrit) _cfg_nr_crit = nrCrit.value;
}

async function edAllConf(mode) {
  const overlay = document.getElementById("allconf-overlay");
  const ta      = document.getElementById("allconf-textarea");
  const info    = document.getElementById("allconf-info");
  const title   = document.getElementById("allconf-title");
  if (!overlay || !ta || !info) return;

  ta.value        = "";
  info.textContent = "Loading…";
  if (title) {
    title.textContent = mode === "dvs"
      ? "DVS Config Files"
      : "ASL Config Files";
  }
  overlay.classList.add("open");

  const sep  = n => "═".repeat(n);
  const hdr  = (label, path) =>
    `# ${sep(60)}\n# ${label}   (${path})\n# ${sep(60)}`;
  const parts = [];

  if (mode !== "dvs") {
    const da = await api("/api/asterisk/files");
    if (da && Array.isArray(da.files)) {
      for (const f of da.files) {
        const name = typeof f === "string" ? f : f.name;
        const d = await api(`/api/asterisk/file?name=${encodeURIComponent(name)}`);
        if (d && d.ok) {
          parts.push(`${hdr(name, d.path)}\n${d.content}`);
        }
      }
    }

    const dm = await api("/api/allmon3/files");
    if (dm && Array.isArray(dm.files)) {
      for (const f of dm.files) {
        if (!f.exists) continue;
        const d = await api(`/api/allmon3/file?label=${encodeURIComponent(f.label)}`);
        if (d && d.ok && d.exists) {
          parts.push(`${hdr(f.label, d.path)}\n${d.content}`);
        }
      }
    }
  }

  if (mode === "dvs") {
    const dd = await api("/api/dvswitch/files");
    if (dd && Array.isArray(dd.files)) {
      for (const f of dd.files) {
        if (!f.exists) continue;
        const d = await api(`/api/dvswitch/file?label=${encodeURIComponent(f.label)}`);
        if (d && d.ok && d.exists) {
          parts.push(`${hdr(f.label, d.path)}\n${d.content}`);
        }
      }
    }
  }

  ta.value = parts.join("\n\n");
  const n  = parts.length;
  info.textContent = n
    ? `${n} file${n !== 1 ? "s" : ""} — select all (Ctrl+A) and copy, or use Copy All`
    : "No visible conf files found";
}

function allConfOverlayClick(e) {
  if (e.target === document.getElementById("allconf-overlay")) closeAllConf();
}

function closeAllConf() {
  document.getElementById("allconf-overlay")?.classList.remove("open");
}

async function allConfCopy() {
  const ta = document.getElementById("allconf-textarea");
  if (!ta || !ta.value) { toast("Nothing to copy", "err"); return; }
  await _copyWithVerify(ta.value);
}

async function openAppConfEditor(label) {
  return _ufOpenLabelFile("\x00appconf:", "/api/appconf/file", label);
}

// ========================================================================
// SHARED: Ports + Firewall
// ========================================================================
async function loadPorts() {
  const d = await api(`/api/ports?proto=${_ptProto}`);
  if (!d) return;
  renderPorts(d.ports || []);

  const ts = document.getElementById("pt-refresh-ts");
  if (ts) ts.textContent = "↻ " + new Date().toTimeString().slice(0,8);
}

function renderPorts(ports) {
  const body = document.getElementById("pt-body");
  if (!body) return;
  body.innerHTML = "";

  if (!ports.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:60px">No open ports found.</div>';
    return;
  }

  ports.forEach(p => {
    const row = document.createElement("div");
    row.className = "pt-row";
    row.onclick   = () => openPortPanel(p);

    const svcText = p.service || "— unknown —";
    const svcCls  = p.service ? "pt-service" : "pt-service unknown";
    const dotCls  = p.service ? "dot-on" : "dot-off";

    row.innerHTML =
      `<span class="dot ${dotCls}"></span>` +
      `<span class="pt-port">${esc(p.port)}</span>` +
      `<span class="pt-proto ${p.proto}">${esc(p.proto)}</span>` +
      `<span class="pt-process">${esc(p.process || "—")}</span>` +
      `<span class="pt-pid">${p.pid || "—"}</span>` +
      `<span class="${svcCls}">${esc(svcText)}</span>`;
    row.appendChild(portBadge(p.port, p.proto));
    body.appendChild(row);
  });
}

function openPortPanel(p) {
  
  _dpUnit = "";

  document.getElementById("dpanel").style.setProperty(
    "--panel-accent", "var(--blue)");

  document.getElementById("dpanel-unit").textContent =
    `:${p.port} / ${p.proto}`;
  document.getElementById("dpanel-desc").textContent =
    p.process + (p.service ? "  —  " + p.service + ".service" : "");
  document.getElementById("dpanel-badges").innerHTML = "";
  document.getElementById("dpanel-output").innerHTML =
    '<span class="dp-out-dim">Select an action below</span>';

  const body = document.getElementById("dpanel-body");
  _dpRestoreBody();
  body.dataset.custom = "1";
  body.innerHTML = `
    <div class="dpzone-lbl">Port Details</div>
    <div style="padding:.55rem .9rem;font-family:var(--sans);font-size:var(--fs-sm);
      border-bottom:1px solid var(--border);line-height:1.9">
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">Port&nbsp;&nbsp;&nbsp;</span>
        <span style="color:var(--blue)">${esc(p.port)}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">Proto&nbsp;&nbsp;</span>
        <span style="color:${p.proto==="tcp"?"var(--blue)":"var(--green)"}">
        ${esc(p.proto.toUpperCase())}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">Process</span>
        <span style="color:var(--teal)">${esc(p.process || "—")}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">PID&nbsp;&nbsp;&nbsp;&nbsp;</span>
        <span>${p.pid || "—"}</span></div>
      <div><span style="color:#fff;letter-spacing:.12em;text-transform:uppercase;
        font-size:var(--fs-xs)">Listen&nbsp;&nbsp;</span>
        <span>${esc(p.addr || "0.0.0.0")}:${esc(p.port)}</span></div>
      ${p.service ? `<div><span style="color:#fff;letter-spacing:.12em;
        text-transform:uppercase;font-size:var(--fs-xs)">Service</span>
        <span style="color:var(--amber)">${esc(p.service)}.service</span></div>` : ""}
    </div>
    <div class="dpzone-lbl">Port Probes</div>
    <div class="dpbtn-row">
      ${p.proto==="tcp"
        ? `<button class="btn btn-blue btn-sm"
             onclick="ptProbeHttp('${p.port}')">⦿ HTTP Probe</button>
           <button class="btn btn-muted btn-sm"
             onclick="ptProbeTcp('${p.port}')">⦿ TCP Probe</button>`
        : `<button class="btn btn-muted btn-sm"
             onclick="ptProbeUdp('${p.port}')">⦿ UDP Probe</button>`}
    </div>
    ${p.service ? `
    <div class="dpzone-lbl">Service Actions</div>
    <div class="dpbtn-row">
      <button class="btn btn-blue  btn-sm"
        onclick="ptSvcAction('restart','${esc(p.service)}.service')">↺ Restart Service</button>
      <button class="btn btn-amber btn-sm"
        onclick="ptSvcAction('stop','${esc(p.service)}.service')">■ Stop Service</button>
      <button class="btn btn-purple btn-sm"
        onclick="ptViewJournal('${esc(p.service)}.service')">▤ Journal</button>
    </div>` : ""}
    <div class="dpzone-lbl">Firewall</div>
    <div id="pt-fw-state" style="padding:.25rem .9rem .35rem;font-family:var(--sans);
      font-size:var(--fs-xs);${p.fw_state ? "" : "display:none"}">${p.fw_state ? `<span style="color:#fff">Currently</span>&nbsp;
      <span style="color:${p.fw_state==="allow"?"var(--green)":"var(--red)"}">
      ${p.fw_state==="allow"?"ALLOWED":"DENIED"}</span>` : ""}</div>
    <div class="dpbtn-row">
      <button class="btn btn-green btn-sm"
        onclick="ptFwAllow('${p.port}','${p.proto}')">+ Allow ${p.port}/${p.proto}</button>
      <button class="btn btn-red btn-sm"
        onclick="ptFwDeny('${p.port}','${p.proto}')">✕ Deny ${p.port}/${p.proto}</button>
    </div>
    <div id="dpanel-output" style="margin:.55rem .9rem;background:#0a1020;
      border:1px solid var(--border);border-radius:3px;min-height:60px;
      max-height:180px;overflow-y:auto;padding:.5rem .7rem;
      font-family:var(--sans);font-size:var(--fs-sm);color:#fff;line-height:1.65">
      <span class="dp-out-dim">Probe results appear here</span>
    </div>`;

  document.getElementById("dpanel-overlay").classList.add("open");
  document.getElementById("dpanel").classList.add("open");
}

function _ptOut(html) {
  const out = document.getElementById("dpanel-output");
  if (!out) return;
  out.innerHTML = html;
  out.scrollIntoView({block: "nearest", behavior: "smooth"});
}

async function _ptProbe(kind, port) {
  _ptOut(`<span class="dp-out-dim">Probing ${kind.toUpperCase()} :${esc(port)}…</span>`);
  const d = await api(`/api/ports/probe?type=${kind}&port=${encodeURIComponent(port)}`);
  if (!d) { _ptOut('<span class="dp-out-fail">Request failed</span>'); return; }
  _ptOut(`<span class="${d.ok ? "dp-out-ok" : "dp-out-fail"}">${esc(d.message || "done")}</span>`);
}

function ptProbeHttp(port) { return _ptProbe("http", port); }

function ptProbeTcp(port) { return _ptProbe("tcp", port); }

function ptProbeUdp(port) { return _ptProbe("udp", port); }

async function ptSvcAction(action, unit) {
  const d = await api("/api/svc", "POST", {action, unit});
  if (!d) { toast("Server unreachable", "err"); return; }
  toast(d.message || (d.ok ? "OK" : "Failed"), d.ok ? "ok" : "err");
  if (d.ok) setTimeout(loadPorts, 800);
}

function ptViewJournal(unit) {
  
  closePanel();
  openJournalPopup(unit);
}

async function _ptFw(action, port, proto) {
  _ptOut(`<span class="dp-out-dim">${action === "allow" ? "Allowing" : "Denying"} ${esc(port)}/${esc(proto)}…</span>`);
  const d = await api("/api/firewall", "POST",
    {action, port, proto, src: "Anywhere"});
  if (!d) { toast("Server unreachable", "err"); _ptOut('<span class="dp-out-fail">Server unreachable</span>'); return; }
  const msg = d.message || (d.ok ? "Rule added" : "Failed");
  toast(msg, d.ok ? "ok" : "err");
  _ptOut(`<span class="${d.ok ? "dp-out-ok" : "dp-out-fail"}">${esc(msg)}</span>`);
  if (d.ok) {
    const st = document.getElementById("pt-fw-state");
    if (st) {
      st.innerHTML = `<span style="color:#fff">Currently</span>&nbsp;` +
        `<span style="color:${action === "allow" ? "var(--green)" : "var(--red)"}">` +
        `${action === "allow" ? "ALLOWED" : "DENIED"}</span>`;
      st.style.display = "";
    }
    if (typeof loadPorts === "function") loadPorts();
  }
}

function ptFwAllow(port, proto) { return _ptFw("allow", port, proto); }

function ptFwDeny(port, proto) { return _ptFw("deny", port, proto); }

// ========================================================================
// SHARED: DVSM + Zello
// ========================================================================
function dvsmCopySecret(btn, fid) { dvsmCopy(btn, _dvsmSecrets.get(fid) || ""); }

function dvsmReveal(eyeBtn, fid) {
  _toggleReveal(eyeBtn, fid, _dvsmRevealed, _dvsmSecrets);
}

function _dvsmRenderAccount(bodyId, badgeId, acct, cardKey) {
  _dvsmSetBadge(badgeId, acct.status);
  const body = document.getElementById(bodyId);
  if (!body) return;

  if (!acct.fields) {
    body.innerHTML = `<div class="dvsm-note err">&#x26A0; ${_esc(acct.error || "No data")}</div>`;
    return;
  }

  let rows = "";
  (acct.fields || []).forEach((f, i) => {
    const fid = "dvsm-fv-" + cardKey + "-" + i;
    let valTd, actTd;

    if (f.masked) {
      
      _dvsmRevealed.delete(fid);
      if (f.secret) {
        _dvsmSecrets.set(fid, f.secret);
        valTd = `<td class="dvsm-val-cell">` +
                `<span id="${fid}" class="dvsm-val masked">` +
                `&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;&#x25CF;</span></td>`;
        actTd = `<td class="dvsm-actions">` +
                `<button class="dvsm-eye" title="Reveal"` +
                ` onclick="dvsmReveal(this,'${fid}')">&#x1F441;</button>` +
                `<button class="dvsm-copy"` +
                ` onclick="dvsmCopySecret(this,'${fid}')">&#x2398;</button>` +
                `</td>`;
      } else {
        
        valTd = `<td class="dvsm-val-cell">` +
                `<span class="dvsm-val placeholder">${_esc(f.note || "not found")}</span></td>`;
        actTd = `<td class="dvsm-actions"></td>`;
      }
    } else {
      const raw = (f.value !== null && f.value !== undefined) ? String(f.value) : "—";
      const noteHtml = f.note
        ? `<span style="display:block;font-size:var(--fs-xs);color:#fff;margin-top:.1rem">` +
          `${_esc(f.note)}</span>`
        : "";
      valTd = `<td class="dvsm-val-cell">` +
              `<span class="dvsm-val${raw === "—" ? " placeholder" : ""}">` +
              `${_esc(raw)}</span>${noteHtml}</td>`;
      actTd = raw !== "—"
        ? `<td class="dvsm-actions">` +
          `<button class="dvsm-copy" data-copyval="${_esc(raw)}"` +
          ` onclick="dvsmCopyAttr(this)">&#x2398;</button></td>`
        : `<td class="dvsm-actions"></td>`;
    }
    rows += `<tr><td class="dvsm-lbl">${_esc(f.label)}</td>${valTd}${actTd}</tr>`;
  });

  let notesHtml = "";
  (acct.notes   || []).forEach(n => {
    notesHtml += `<div class="dvsm-note warn">&#x26A0; ${_esc(n)}</div>`;
  });
  (acct.missing || []).forEach(n => {
    notesHtml += `<div class="dvsm-note err">&#x2717; ${_esc(n)}</div>`;
  });
  if (acct.error) {
    notesHtml += `<div class="dvsm-note src">Source error: ${_esc(acct.error)}</div>`;
  }

  body.innerHTML = `<table class="dvsm-fields">${rows}</table>${notesHtml}`;
}

function _dvsmRenderCompat(bodyId, compat) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  if (!compat || !compat.length) {
    body.innerHTML = `<div class="stub-panel" style="min-height:40px">No checks available</div>`;
    return;
  }

  let html = "";
  let curFile = null;
  compat.forEach(c => {
    const fileKey = (c.source || "").split(/[\s[]/)[0];
    if (fileKey !== curFile) {
      if (curFile !== null) html += `</table>`;
      curFile = fileKey;
      html += `<span class="dvsm-sec-lbl">${_esc(c.source)}</span>` +
              `<table class="dvsm-compat-tbl">`;
    }
    const sub = c.fix || (c.status === "info" && c.value ? c.value : null);
    html += _compatRowHtml(c.key, c.enables, c.status, sub);
  });
  if (curFile !== null) html += `</table>`;
  body.innerHTML = html;
}

// ========================================================================
// SHARED: DVSM + STFU + M17 + Zello
// ========================================================================
function _dvsmBadgeClass(status) {
  return {pass: "dpbadge-state-active",
          fail: "dpbadge-state-failed",
          warn: "dpbadge-warn",
          info: "dpbadge-info"}[status] || "dpbadge-info";
}

function _dvsmSetBadge(id, status, text) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = (text || status || "—").toUpperCase();
  el.className   = "dpbadge " + _dvsmBadgeClass(status);
}

function dvsmCopy(btn, value) {
  navigator.clipboard.writeText(String(value || "")).catch(() => {});
  const orig = btn.textContent;
  btn.textContent = "✓";
  btn.classList.add("copied");
  setTimeout(() => { btn.textContent = orig; btn.classList.remove("copied"); }, 1200);
}

function dvsmCopyAttr(btn) { dvsmCopy(btn, btn.getAttribute("data-copyval") || ""); }

function _compatRowHtml(key, enables, status, sub) {
  const bc = _dvsmBadgeClass(status);
  const bt = _esc((status || "—").toUpperCase());
  let html = `<tr>` +
    `<td class="dvsm-ct-key">${_esc(key)}</td>` +
    `<td class="dvsm-ct-enables">${_esc(enables)}</td>` +
    `<td class="dvsm-ct-badge"><span class="dpbadge ${bc}">${bt}</span></td>` +
    `</tr>`;
  if (sub) {
    html += `<tr class="dvsm-ct-fix-row">` +
            `<td colspan="3" class="dvsm-ct-fix">&#x21B3; ${_esc(sub)}</td>` +
            `</tr>`;
  }
  return html;
}

// ========================================================================
// SHARED: small helpers used by two or more tabs
// ========================================================================
function renderRegChecks(checks, overallStatus, ids) {
  const body   = document.getElementById(ids.body);
  const meta   = document.getElementById(ids.meta);
  const status = document.getElementById(ids.status);
  if (!body) return;

  if (status) {
    const s = overallStatus || "info";
    status.className   = "reg-card-status " + s;
    status.textContent = s.toUpperCase();
  }

  if (!Array.isArray(checks) || !checks.length) {
    body.innerHTML = '<div class="stub-panel" style="min-height:60px">No checks available</div>';
    if (meta) meta.textContent = "—";
    return;
  }
  if (meta) {
    const fails = checks.filter(c => c.status === "fail").length;
    const warns = checks.filter(c => c.status === "warn").length;
    meta.textContent = fails ? `${fails} issue${fails === 1 ? "" : "s"}`
                      : warns ? `${warns} warning${warns === 1 ? "" : "s"}`
                      : "all clear";
  }
  const cb = document.createElement("div");
  cb.className = "ast-checks";
  checks.forEach(c => {
    const crow = document.createElement("div");
    crow.className = "ast-check-row";

    const title = document.createElement("span");
    title.className   = "ast-check-title";
    title.textContent = c.title;

    const val = document.createElement("span");
    val.className   = "ast-check-value";
    val.textContent = c.value || "";

    const badge = document.createElement("span");
    if      (c.status === "pass") { badge.className = "ast-check-pass"; badge.textContent = "[PASS]"; }
    else if (c.status === "fail") { badge.className = "ast-check-fail"; badge.textContent = "[FAIL]"; }
    else if (c.status === "warn") { badge.className = "ast-check-warn"; badge.textContent = "[WARN]"; }
    else if (c.status === "info") { badge.className = "ast-check-info"; badge.textContent = "[INFO]"; }
    else                          { badge.className = "ast-check-none"; badge.textContent = "[NONE]"; }

    crow.appendChild(title);
    crow.appendChild(val);
    crow.appendChild(badge);
    cb.appendChild(crow);

    if (c.note) {
      const nrow = document.createElement("div");
      nrow.className = "ast-check-note";
      if (c.url) {
        const a = document.createElement("a");
        a.href   = c.url;
        a.target = "_blank";
        a.textContent = c.note;
        nrow.appendChild(a);
      } else {
        nrow.textContent = c.note;
      }
      cb.appendChild(nrow);
    }
  });
  body.innerHTML = "";
  body.appendChild(cb);
}

function phEl(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

function phBadge(text, cls) { return phEl("span", "reg-card-status " + (cls || "info"), text); }

function phKV(rows) {
  const d = phEl("div", "ph-kv");
  rows.forEach(r => {
    if (r[1] === null || r[1] === undefined || r[1] === "") return;
    d.appendChild(phEl("div", "k", r[0]));
    const v = phEl("div", "v");
    if (r[1] instanceof Node) v.appendChild(r[1]); else v.textContent = String(r[1]);
    d.appendChild(v);
  });
  return d;
}

function _renderCompatTable(bodyId, compat) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  if (!compat || !compat.length) {
    body.innerHTML = `<div class="stub-panel" style="min-height:40px">No checks available</div>`;
    return;
  }
  let html = `<table class="dvsm-compat-tbl">`;
  compat.forEach(c => { html += _compatRowHtml(c.key, c.enables, c.status, c.fix); });
  html += `</table>`;
  body.innerHTML = html;
}

function _renderInstallTable(bodyId, badgeId, inst, spec) {
  const allOk  = inst.binary_ok && inst.service_installed && inst.service_active;
  const anyOk  = inst.binary_ok || inst.service_installed;
  const status = allOk ? "pass" : anyOk ? "warn" : "fail";
  _dvsmSetBadge(badgeId, status);

  const body = document.getElementById(bodyId);
  if (!body) return;

  const row = (key, enables, ok, fixMsg) =>
    _compatRowHtml(key, enables, ok ? "pass" : (fixMsg ? "warn" : "fail"),
                   ok ? null : fixMsg);

  let html = `<table class="dvsm-compat-tbl">`;
  html += row(
    inst.binary_path || spec.binDefault,
    spec.binLabel,
    inst.binary_ok,
    inst.binary_ok ? null : spec.binFix
  );
  html += row(
    inst.service_path || `${spec.unit}.service`,
    "systemd unit installed",
    inst.service_installed,
    inst.service_installed ? null : spec.unitFix
  );
  html += row(
    "Service active",
    `systemctl is-active ${spec.unit}`,
    inst.service_active,
    (!inst.service_active && inst.service_installed)
      ? `systemctl start ${spec.unit}`
      : (!inst.service_active ? "Install service first" : null)
  );
  html += `</table>`;
  body.innerHTML = html;
}

function _renderSampleCode(bodyId, rawText, commentRe, kvRe) {
  const body = document.getElementById(bodyId);
  if (!body) return;

  const highlighted = rawText
    .split("\n")
    .map(line => {
      if (commentRe.test(line))
        return `<span style="color:#fff">${_esc(line)}</span>`;
      const secM = line.match(/^(\[.+?\])(.*)/);
      if (secM)
        return `<span class="stfu-ini-section">${_esc(secM[1])}</span>` +
               `<span style="color:#fff">${_esc(secM[2])}</span>`;
      const kvM = line.match(kvRe);
      if (kvM) {
        const valPart = kvM[3].includes("<")
          ? `<span class="stfu-ini-ph">${_esc(kvM[3])}</span>`
          : `<span style="color:var(--text-bright)">${_esc(kvM[3])}</span>`;
        return `<span class="stfu-ini-key">${_esc(kvM[1])}</span>` +
               `<span style="color:#fff">=</span>` + valPart;
      }
      return _esc(line);
    })
    .join("\n");

  body.innerHTML = `<pre class="stfu-code">${highlighted}</pre>`;
}

function _toggleReveal(eyeBtn, fid, revealed, secrets) {
  const el  = document.getElementById(fid);
  if (!el) return;
  const now = !revealed.get(fid);
  revealed.set(fid, now);
  if (now) {
    el.textContent = secrets.get(fid) || "(empty)";
    el.classList.remove("masked");
    eyeBtn.classList.add("revealed");
    eyeBtn.title = "Hide";
  } else {
    el.textContent = "●●●●●●●●";
    el.classList.add("masked");
    eyeBtn.classList.remove("revealed");
    eyeBtn.title = "Reveal";
  }
}

