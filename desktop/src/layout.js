const MIN_PANE = 240;
const GAP = 6;
const MODES = ['single', 'cols', 'trio'];
const COUNT = { single: 1, cols: 2, trio: 3 };
const LH_KEY = 'lh';
const UNITS = 15;
const SIDEBAR_UNITS = 3;

function grid(w, h) {
  const sidebar = Math.round((w * SIDEBAR_UNITS) / UNITS);
  const header = Math.round(w / UNITS);
  return { sidebar, header, area: { x: sidebar, y: header, w: Math.max(0, w - sidebar), h: Math.max(0, h - header) } };
}

function emptyState() {
  return { tabs: [], panes: [null, null, null], mode: 'single', ratio: 0.5, focus: 0 };
}

function keyOf(nodeId, pageId) {
  return `${nodeId}:${pageId}`;
}

function settle(s) {
  const tabs = s.tabs;
  if (!tabs.length) return { ...s, tabs, panes: [null, null, null], mode: 'single', focus: 0 };
  const has = (k) => tabs.some((t) => t.key === k);
  let mode = MODES.includes(s.mode) ? s.mode : 'single';
  while (COUNT[mode] > tabs.length) mode = MODES[MODES.indexOf(mode) - 1];
  const n = COUNT[mode];
  const seen = new Set();
  const panes = [0, 1, 2].map((i) => {
    const k = s.panes[i];
    if (i < n && k && has(k) && !seen.has(k)) {
      seen.add(k);
      return k;
    }
    return null;
  });
  for (let i = 0; i < n; i += 1) {
    if (panes[i] === null) {
      const f = tabs.find((t) => !seen.has(t.key));
      if (f) {
        panes[i] = f.key;
        seen.add(f.key);
      }
    }
  }
  const focus = Number.isInteger(s.focus) && s.focus >= 0 && s.focus < n ? s.focus : 0;
  return { ...s, tabs, panes, mode, focus };
}

function shown(s) {
  return s.panes.slice(0, COUNT[s.mode]);
}

function openTab(s, nodeId, pageId) {
  const key = keyOf(nodeId, pageId);
  const tabs = s.tabs.some((t) => t.key === key) ? s.tabs : [...s.tabs, { key, nodeId, pageId }];
  return openKey({ ...s, tabs }, key);
}

function openKey(s, key) {
  if (!s.tabs.some((t) => t.key === key)) return s;
  const at = shown(s).indexOf(key);
  if (at >= 0) return { ...s, focus: at };
  const panes = [...s.panes];
  panes[s.focus] = key;
  return settle({ ...s, panes });
}

function openLastHeard(s, nodeId, url) {
  const has = s.tabs.some((t) => t.key === LH_KEY);
  const tabs = has
    ? s.tabs.map((t) => (t.key === LH_KEY ? { ...t, nodeId, url } : t))
    : [...s.tabs, { key: LH_KEY, nodeId, pageId: 'lasthard', kind: 'lh', url }];
  const st = { ...s, tabs };
  const vis = shown(st);
  const at = vis.indexOf(LH_KEY);
  if (at >= 0) return { ...st, focus: at };
  if (st.mode === 'trio') {
    const panes = [...st.panes];
    panes[2] = LH_KEY;
    return settle({ ...st, panes, focus: 2 });
  }
  if (st.mode === 'cols') return settle({ ...st, mode: 'trio', panes: [vis[0], vis[1], LH_KEY], focus: 2 });
  return settle({ ...st, mode: 'cols', panes: [vis[0], LH_KEY, null], focus: 1 });
}

function closeTab(s, key) {
  const tabs = s.tabs.filter((t) => t.key !== key);
  const panes = s.panes.map((k) => (k === key ? null : k));
  return settle({ ...s, tabs, panes });
}

function closeNode(s, nodeId) {
  let out = s;
  for (const t of s.tabs) if (t.nodeId === nodeId) out = closeTab(out, t.key);
  return out;
}

function setMode(s, mode) {
  if (!MODES.includes(mode) || mode === s.mode) return s;
  const n = COUNT[mode];
  if (n > s.tabs.length) return s;
  const cur = shown(s);
  if (mode === 'single') {
    const keep = s.panes[s.focus] || s.panes[0];
    return settle({ ...s, mode, panes: [keep, null, null], focus: 0 });
  }
  if (s.mode === 'single') {
    const key = cur[0];
    const at = (k) => s.tabs.findIndex((t) => t.key === k);
    let pick = s.tabs.slice(0, n).map((t) => t.key);
    if (!pick.includes(key)) pick[n - 1] = key;
    pick = pick.sort((a, b) => at(a) - at(b));
    return settle({ ...s, mode, panes: [pick[0], pick[1], pick[2] || null], focus: pick.indexOf(key) });
  }
  if (mode === 'cols') {
    if (s.focus === 2) return settle({ ...s, mode, panes: [cur[0], cur[2], null], focus: 1 });
    return settle({ ...s, mode, panes: [cur[0], cur[1], null] });
  }
  return settle({ ...s, mode, panes: [cur[0], cur[1], null] });
}

function setRatio(s, r) {
  const n = Number(r);
  if (!Number.isFinite(n)) return s;
  return { ...s, ratio: Math.min(0.9, Math.max(0.1, n)) };
}

function focusPane(s, i) {
  if (!Number.isInteger(i) || i < 0 || i >= COUNT[s.mode]) return s;
  return s.panes[i] ? { ...s, focus: i } : s;
}

function serialize(s) {
  const keep = s.tabs.filter((t) => t.kind !== 'lh');
  return {
    tabs: keep.map((t) => ({ nodeId: t.nodeId, pageId: t.pageId })),
    panes: s.panes.map((k) => (keep.some((t) => t.key === k) ? k : null)),
    mode: s.mode,
    ratio: s.ratio,
    focus: s.focus,
  };
}

function restore(saved, nodes, pages) {
  const base = emptyState();
  if (!saved || !Array.isArray(saved.tabs)) return base;
  const seen = new Set();
  const tabs = [];
  for (const t of saved.tabs) {
    if (!t || typeof t.nodeId !== 'string' || typeof t.pageId !== 'string') continue;
    if (!nodes.some((n) => n.id === t.nodeId) || !pages.some((p) => p.id === t.pageId)) continue;
    const key = keyOf(t.nodeId, t.pageId);
    if (seen.has(key)) continue;
    seen.add(key);
    tabs.push({ key, nodeId: t.nodeId, pageId: t.pageId });
  }
  const panes = Array.isArray(saved.panes) ? saved.panes.slice(0, 3) : [];
  while (panes.length < 3) panes.push(null);
  return settle({
    ...base,
    tabs,
    panes: panes.map((k) => (typeof k === 'string' ? k : null)),
    mode: saved.mode,
    ratio: Number.isFinite(saved.ratio) ? Math.min(0.9, Math.max(0.1, saved.ratio)) : 0.5,
    focus: saved.focus,
  });
}

function clampRatio(ratio, total) {
  const usable = total - GAP;
  if (usable < MIN_PANE * 2) return 0.5;
  const lo = MIN_PANE / usable;
  return Math.min(1 - lo, Math.max(lo, ratio));
}

function rects(s, area) {
  const f = { x: area.x, y: area.y, w: Math.max(0, area.w), h: Math.max(0, area.h) };
  if (s.mode === 'single') return { panes: [f], dividers: [] };
  const usable = f.w - GAP;
  const a = Math.floor(usable * clampRatio(s.ratio, f.w));
  const top = s.mode === 'cols' ? f.h : Math.floor((f.h - GAP) / 2);
  const left = { x: f.x, y: f.y, w: a, h: top };
  const right = { x: f.x + a + GAP, y: f.y, w: Math.max(0, usable - a), h: top };
  const vertical = { rect: { x: f.x + a, y: f.y, w: GAP, h: top }, axis: 'x', drag: true };
  if (s.mode === 'cols') return { panes: [left, right], dividers: [vertical] };
  const bottom = { x: f.x, y: f.y + top + GAP, w: f.w, h: Math.max(0, f.h - GAP - top) };
  const horizontal = { rect: { x: f.x, y: f.y + top, w: f.w, h: GAP }, axis: 'y', drag: false };
  return { panes: [left, right, bottom], dividers: [vertical, horizontal] };
}

module.exports = {
  MIN_PANE,
  GAP,
  MODES,
  COUNT,
  LH_KEY,
  grid,
  emptyState,
  keyOf,
  shown,
  openTab,
  openKey,
  openLastHeard,
  closeTab,
  closeNode,
  setMode,
  setRatio,
  focusPane,
  serialize,
  restore,
  clampRatio,
  rects,
};
