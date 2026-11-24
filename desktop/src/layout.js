const MIN_PANE = 240;
const GAP = 6;
const STRIP = 28;
const MODES = ['single', 'cols', 'trio'];
const COUNT = { single: 1, cols: 2, trio: 3 };
const LH_KEY = 'lh';
const UNITS = 15;
const SIDEBAR_UNITS = 3;

function grid(w, h) {
  const sidebar = Math.round((w * SIDEBAR_UNITS) / UNITS);
  const header = Math.round(w / UNITS);
  return { sidebar, header, strip: STRIP, area: { x: sidebar, y: header, w: Math.max(0, w - sidebar), h: Math.max(0, h - header) } };
}

function emptyState() {
  return { tabs: [], panes: [null, null, null], mode: 'single', saved: null, ratio: 0.5, focus: 0 };
}

function keyOf(nodeId, pageId) {
  return `${nodeId}:${pageId}`;
}

function hasTab(s, k) {
  return Boolean(k) && s.tabs.some((t) => t.key === k);
}

function arrangement(s, mode, panes) {
  const list = [];
  for (let i = 0; i < COUNT[mode]; i += 1) if (hasTab(s, panes[i]) && !list.includes(panes[i])) list.push(panes[i]);
  if (list.length >= 3 && mode === 'trio') return { mode: 'trio', panes: list.slice(0, 3) };
  if (list.length >= 2) return { mode: 'cols', panes: [list[0], list[1], null] };
  return null;
}

function savedOf(s) {
  if (!s.saved) return null;
  const a = arrangement(s, s.saved.mode, s.saved.panes);
  return a ? { mode: a.mode, panes: [a.panes[0], a.panes[1], a.panes[2] || null] } : null;
}

function settle(s) {
  const tabs = s.tabs;
  if (!tabs.length) return { ...s, tabs, panes: [null, null, null], mode: 'single', saved: null, focus: 0 };
  let mode = MODES.includes(s.mode) ? s.mode : 'single';
  let panes = [null, null, null];
  if (mode === 'single') {
    panes[0] = hasTab(s, s.panes[0]) ? s.panes[0] : tabs[0].key;
  } else {
    const a = arrangement(s, mode, s.panes);
    if (a) {
      mode = a.mode;
      panes = [a.panes[0], a.panes[1], a.panes[2] || null];
    } else {
      mode = 'single';
      const keep = s.panes.find((k) => hasTab(s, k));
      panes[0] = keep || tabs[0].key;
    }
  }
  let focus = Number.isInteger(s.focus) ? s.focus : 0;
  if (focus < 0 || focus >= COUNT[mode] || !panes[focus]) focus = 0;
  const next = { ...s, tabs, panes, mode, focus };
  next.saved = mode === 'single' ? savedOf(next) : { mode, panes: [...panes] };
  return next;
}

function shown(s) {
  return s.panes.slice(0, COUNT[s.mode]);
}

function addTab(s, nodeId, pageId) {
  const key = keyOf(nodeId, pageId);
  if (hasTab(s, key)) return s;
  return { ...s, tabs: [...s.tabs, { key, nodeId, pageId }] };
}

function showAlone(s, key) {
  if (!hasTab(s, key)) return s;
  return settle({ ...s, mode: 'single', panes: [key, null, null], focus: 0 });
}

function restoreSaved(s, focusKey) {
  const sv = savedOf(s);
  if (!sv) return null;
  const at = focusKey ? sv.panes.indexOf(focusKey) : -1;
  return settle({ ...s, mode: sv.mode, panes: sv.panes, focus: at >= 0 ? at : 0 });
}

function openKey(s, key) {
  if (!hasTab(s, key)) return s;
  const at = shown(s).indexOf(key);
  if (at >= 0) return { ...s, focus: at };
  const back = savedOf(s);
  if (back && back.panes.includes(key)) return restoreSaved(s, key);
  return showAlone(s, key);
}

function openTab(s, nodeId, pageId) {
  return openKey(addTab(s, nodeId, pageId), keyOf(nodeId, pageId));
}

function openLastHeard(s, nodeId, url) {
  const has = s.tabs.some((t) => t.key === LH_KEY);
  const tabs = has
    ? s.tabs.map((t) => (t.key === LH_KEY ? { ...t, nodeId, url } : t))
    : [...s.tabs, { key: LH_KEY, nodeId, pageId: 'lasthard', kind: 'lh', url }];
  return openKey({ ...s, tabs }, LH_KEY);
}

function backToSplit(s) {
  if (s.mode !== 'single') return s;
  return restoreSaved(s, null) || s;
}

function canBack(s) {
  return s.mode === 'single' && savedOf(s) !== null;
}

function closeTab(s, key) {
  if (!hasTab(s, key)) return s;
  const wasShown = shown(s).includes(key);
  const tabs = s.tabs.filter((t) => t.key !== key);
  const panes = s.panes.map((k) => (k === key ? null : k));
  const next = { ...s, tabs, panes };
  if (wasShown && s.mode === 'single') {
    const back = restoreSaved({ ...next, saved: s.saved }, null);
    if (back && back.mode !== 'single') return back;
  }
  return settle(next);
}

function closeNode(s, nodeId) {
  let out = s;
  for (const t of s.tabs) if (t.nodeId === nodeId) out = closeTab(out, t.key);
  return out;
}

function removePane(s, i) {
  if (s.mode === 'single' || !Number.isInteger(i) || i < 0 || i >= COUNT[s.mode]) return s;
  const panes = [...s.panes];
  panes[i] = null;
  return settle({ ...s, panes, focus: 0 });
}

function applyArrangement(s, mode, keys, ratio) {
  if (!['cols', 'trio'].includes(mode) || keys.length !== COUNT[mode] || keys.some((k) => !hasTab(s, k)) || new Set(keys).size !== keys.length) return s;
  const r = Number.isFinite(ratio) ? Math.min(0.9, Math.max(0.1, ratio)) : s.ratio;
  return settle({ ...s, mode, panes: [keys[0], keys[1], keys[2] || null], ratio: r, focus: 0 });
}

function setMode(s, mode) {
  if (!MODES.includes(mode) || mode === s.mode) return s;
  const n = COUNT[mode];
  if (n > s.tabs.length) return s;
  if (mode === 'single') return showAlone(s, s.panes[s.focus] || s.panes[0]);
  const back = savedOf(s);
  if (back && back.mode === mode) return restoreSaved(s, s.panes[s.focus]);
  const cur = shown(s);
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
  const third = s.tabs.find((t) => !cur.includes(t.key));
  return settle({ ...s, mode, panes: [cur[0], cur[1], third ? third.key : null] });
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

function viewRect(s, rect) {
  if (s.mode === 'single') return rect;
  return { x: rect.x, y: rect.y + STRIP, w: rect.w, h: Math.max(0, rect.h - STRIP) };
}

function dropZones(s, area) {
  const f = { x: area.x, y: area.y, w: Math.max(0, area.w), h: Math.max(0, area.h) };
  if (s.mode === 'single') {
    const half = Math.floor(f.w / 2);
    return [
      { id: 'pane0', rect: { x: f.x, y: f.y, w: half, h: f.h } },
      { id: 'right', rect: { x: f.x + half, y: f.y, w: f.w - half, h: f.h } },
    ];
  }
  const r = rects(s, area);
  if (s.mode === 'cols') {
    const bottom = Math.floor(f.h / 3);
    const top = f.h - bottom;
    return [
      { id: 'pane0', rect: { x: r.panes[0].x, y: f.y, w: r.panes[0].w, h: top } },
      { id: 'pane1', rect: { x: r.panes[1].x, y: f.y, w: r.panes[1].w, h: top } },
      { id: 'below', rect: { x: f.x, y: f.y + top, w: f.w, h: bottom } },
    ];
  }
  return r.panes.map((rect, i) => ({ id: `pane${i}`, rect }));
}

function zoneIds(s) {
  if (s.mode === 'single') return ['pane0', 'right'];
  if (s.mode === 'cols') return ['pane0', 'pane1', 'below'];
  return ['pane0', 'pane1', 'pane2'];
}

function dropKey(s, key, zone) {
  if (!hasTab(s, key) || !zoneIds(s).includes(zone)) return s;
  const cur = shown(s);
  if (zone === 'right') {
    if (cur[0] === key) return s;
    return settle({ ...s, mode: 'cols', panes: [cur[0], key, null], focus: 1 });
  }
  if (zone === 'below') {
    if (cur.includes(key)) return s;
    return settle({ ...s, mode: 'trio', panes: [cur[0], cur[1], key], focus: 2 });
  }
  const i = Number(zone.slice(4));
  if (s.mode === 'single') return showAlone(s, key);
  const panes = [...s.panes];
  const j = cur.indexOf(key);
  if (j === i) return { ...s, focus: i };
  if (j >= 0) {
    panes[j] = panes[i];
    panes[i] = key;
  } else {
    panes[i] = key;
  }
  return settle({ ...s, panes, focus: i });
}

function nextZone(s) {
  if (s.mode === 'single') return 'right';
  if (s.mode === 'cols') return 'below';
  return 'pane2';
}

function addNext(s, key) {
  if (!hasTab(s, key)) return s;
  const at = shown(s).indexOf(key);
  if (at >= 0) return { ...s, focus: at };
  return dropKey(s, key, nextZone(s));
}

function serialize(s) {
  const keep = s.tabs.filter((t) => t.kind !== 'lh');
  const ok = (k) => keep.some((t) => t.key === k);
  const sv = s.saved ? { mode: s.saved.mode, panes: s.saved.panes.map((k) => (ok(k) ? k : null)) } : null;
  return {
    tabs: keep.map((t) => ({ nodeId: t.nodeId, pageId: t.pageId })),
    panes: s.panes.map((k) => (ok(k) ? k : null)),
    mode: s.mode,
    saved: sv,
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
  const list = (v) => {
    const a = Array.isArray(v) ? v.slice(0, 3) : [];
    while (a.length < 3) a.push(null);
    return a.map((k) => (typeof k === 'string' ? k : null));
  };
  const sv = saved.saved && typeof saved.saved === 'object' && MODES.includes(saved.saved.mode) ? { mode: saved.saved.mode, panes: list(saved.saved.panes) } : null;
  return settle({
    ...base,
    tabs,
    panes: list(saved.panes),
    mode: saved.mode,
    saved: sv,
    ratio: Number.isFinite(saved.ratio) ? Math.min(0.9, Math.max(0.1, saved.ratio)) : 0.5,
    focus: saved.focus,
  });
}

module.exports = {
  MIN_PANE,
  GAP,
  STRIP,
  MODES,
  COUNT,
  LH_KEY,
  grid,
  emptyState,
  keyOf,
  shown,
  addTab,
  showAlone,
  openTab,
  openKey,
  openLastHeard,
  backToSplit,
  canBack,
  savedOf,
  closeTab,
  closeNode,
  removePane,
  applyArrangement,
  setMode,
  setRatio,
  focusPane,
  clampRatio,
  rects,
  viewRect,
  dropZones,
  zoneIds,
  dropKey,
  addNext,
  serialize,
  restore,
};
