const P = require('./policy');

const MIN_PANE = 240;
const GAP = 6;
const STRIP = 28;
const SLOTS = ['left', 'right', 'lower'];
const SLOT_LABEL = { left: 'Left', right: 'Right', lower: 'Lower' };
const SINGLE_ONLY = new Set(['h44', 'instmon', 'termon']);
const MAX_SAVED_PAGES = 12;
const LH_PAGE = 'lasthard';
const REF_W = 800;
const REF_H = 500;
const ZOOM_MIN = 0.4;
const ZOOM_MAX = 1.6;
const AUTO_MIN = 0.5;
const ZOOM_STEP = 0.1;
const UNITS = 15;
const SIDEBAR_UNITS = 2.25;
const HEADER = 44;
const SIDEBAR_MIN = 176;

function grid(w, h) {
  const sidebar = Math.min(w, Math.max(SIDEBAR_MIN, Math.round((w * SIDEBAR_UNITS) / UNITS)));
  const header = HEADER;
  return { sidebar, header, strip: STRIP, area: { x: sidebar, y: header, w: Math.max(0, w - sidebar), h: Math.max(0, h - header) } };
}

const WIN_W = 1280;
const WIN_H = 800;
const WIN_MIN_W = 900;
const WIN_MIN_H = 560;

function windowSize(work) {
  const ww = Math.max(1, Math.floor(Number(work && work.width) || WIN_W));
  const wh = Math.max(1, Math.floor(Number(work && work.height) || WIN_H));
  return {
    width: Math.min(WIN_W, ww),
    height: Math.min(WIN_H, wh),
    minWidth: Math.min(WIN_MIN_W, ww),
    minHeight: Math.min(WIN_MIN_H, wh),
    maximize: ww < WIN_W || wh < WIN_H,
  };
}

function emptyState() {
  return {
    tabs: [],
    slots: { left: [], right: [], lower: [] },
    sel: { left: null, right: null, lower: null },
    single: null,
    view: 'single',
    focus: 'left',
    ratio: 0.5,
    zooms: {},
  };
}

function keyOf(nodeId, pageId) {
  return `${nodeId}:${pageId}`;
}

function lhKey(name) {
  return `lh:${String(name).toLowerCase()}`;
}

function itemKey(it) {
  return it.kind === 'lh' ? lhKey(it.name) : keyOf(it.nodeId, it.pageId);
}

function hasTab(s, k) {
  return Boolean(k) && s.tabs.some((t) => t.key === k);
}

function isSingleOnly(s, k) {
  const t = s.tabs.find((x) => x.key === k);
  return Boolean(t) && SINGLE_ONLY.has(t.pageId);
}

function slotOf(s, k) {
  return SLOTS.find((sl) => s.slots[sl].includes(k)) || null;
}

function occupied(s) {
  return SLOTS.filter((sl) => s.sel[sl]);
}

function settle(s) {
  const tabs = s.tabs;
  const slots = { left: [], right: [], lower: [] };
  const seen = new Set();
  for (const sl of SLOTS) {
    for (const k of (s.slots && s.slots[sl]) || []) {
      if (hasTab(s, k) && !seen.has(k) && !isSingleOnly(s, k)) {
        seen.add(k);
        slots[sl].push(k);
      }
    }
  }
  const sel = { left: null, right: null, lower: null };
  for (const sl of SLOTS) sel[sl] = slots[sl].includes(s.sel && s.sel[sl]) ? s.sel[sl] : slots[sl][0] || null;
  const zooms = {};
  for (const k of Object.keys(s.zooms || {})) if (hasTab(s, k) && Number.isFinite(s.zooms[k])) zooms[k] = s.zooms[k];
  if (!tabs.length) return { ...s, tabs, slots, sel, zooms: {}, single: null, view: 'single', focus: 'left' };
  const occ = SLOTS.filter((sl) => sel[sl]);
  let view = s.view === 'slots' && occ.length ? 'slots' : 'single';
  let single = hasTab(s, s.single) ? s.single : null;
  if (view === 'single' && !single) single = (occ.length ? sel[occ[0]] : null) || tabs[0].key;
  const focus = SLOTS.includes(s.focus) && sel[s.focus] ? s.focus : occ[0] || 'left';
  return { ...s, tabs, slots, sel, zooms, single, view, focus };
}

function paneList(s) {
  if (s.view === 'slots' && occupied(s).length) return occupied(s).map((sl) => ({ slot: sl, key: s.sel[sl] }));
  return s.single ? [{ slot: null, key: s.single }] : [];
}

function shown(s) {
  return paneList(s).map((p) => p.key);
}

function focusedKey(s) {
  const list = paneList(s);
  const hit = list.find((p) => p.slot === s.focus) || list[0];
  return hit ? hit.key : null;
}

function addTab(s, nodeId, pageId) {
  const key = keyOf(nodeId, pageId);
  if (hasTab(s, key)) return s;
  return { ...s, tabs: [...s.tabs, { key, nodeId, pageId }] };
}

function showAlone(s, key) {
  if (!hasTab(s, key)) return s;
  return settle({ ...s, single: key, view: 'single' });
}

function openKey(s, key) {
  if (!hasTab(s, key)) return s;
  const sl = slotOf(s, key);
  if (sl) return settle({ ...s, sel: { ...s.sel, [sl]: key }, focus: sl, view: 'slots' });
  return showAlone(s, key);
}

function openTab(s, nodeId, pageId) {
  return openKey(addTab(s, nodeId, pageId), keyOf(nodeId, pageId));
}

function putLastHeard(s, nodeId, url, name) {
  const key = lhKey(name);
  const tab = { key, nodeId, pageId: LH_PAGE, kind: 'lh', name, url };
  const has = s.tabs.some((t) => t.key === key);
  return { ...s, tabs: has ? s.tabs.map((t) => (t.key === key ? tab : t)) : [...s.tabs, tab] };
}

function openLastHeard(s, nodeId, url, name) {
  return showAlone(putLastHeard(s, nodeId, url, name), lhKey(name));
}

function dropLastHeard(s, ok) {
  let out = s;
  for (const t of s.tabs) if (t.kind === 'lh' && !ok(t)) out = closeTab(out, t.key);
  return out;
}

function putInSlot(s, key, slot) {
  if (!hasTab(s, key) || !SLOTS.includes(slot) || isSingleOnly(s, key)) return s;
  const slots = {};
  for (const sl of SLOTS) slots[sl] = s.slots[sl].filter((k) => k !== key);
  slots[slot] = [...slots[slot], key];
  return settle({ ...s, slots, sel: { ...s.sel, [slot]: key }, focus: slot, view: 'slots' });
}

function dropKey(s, key, slot) {
  return putInSlot(s, key, slot);
}

function unslot(s, key) {
  const sl = slotOf(s, key);
  if (!sl) return s;
  const slots = { ...s.slots, [sl]: s.slots[sl].filter((k) => k !== key) };
  const next = settle({ ...s, slots });
  if (next.view === 'slots' && !occupied(next).length) return settle({ ...next, view: 'single', single: key });
  return { ...next, single: next.single || key };
}

function nextSlot(s) {
  const free = SLOTS.find((sl) => !s.slots[sl].length);
  return free || s.focus;
}

function addNext(s, key) {
  if (!hasTab(s, key) || isSingleOnly(s, key)) return openKey(s, key);
  if (slotOf(s, key)) return openKey(s, key);
  return putInSlot(s, key, nextSlot(s));
}

function setView(s, view) {
  if (view === 'single') {
    if (s.view === 'single') return s;
    return settle({ ...s, view: 'single', single: s.sel[s.focus] || s.single });
  }
  if (view === 'slots') {
    if (!occupied(s).length || s.view === 'slots') return s;
    return settle({ ...s, view: 'slots' });
  }
  return s;
}

function canSplit(s) {
  return occupied(s).length >= 1;
}

function canBack(s) {
  return s.view === 'single' && canSplit(s);
}

function closeTab(s, key) {
  if (!hasTab(s, key)) return s;
  const tabs = s.tabs.filter((t) => t.key !== key);
  const slots = {};
  for (const sl of SLOTS) slots[sl] = s.slots[sl].filter((k) => k !== key);
  let next = { ...s, tabs, slots };
  if (s.view === 'single' && s.single === key) {
    const any = SLOTS.some((sl) => slots[sl].some((k) => tabs.some((t) => t.key === k)));
    next = { ...next, single: null, view: any ? 'slots' : 'single' };
  }
  return settle(next);
}

function closeNode(s, nodeId) {
  let out = s;
  for (const t of s.tabs) if (t.nodeId === nodeId) out = closeTab(out, t.key);
  return out;
}

function setRatio(s, r) {
  const n = Number(r);
  if (!Number.isFinite(n)) return s;
  return { ...s, ratio: Math.min(0.9, Math.max(0.1, n)) };
}

function focusSlot(s, slot) {
  if (!SLOTS.includes(slot) || !s.sel[slot]) return s;
  return { ...s, focus: slot };
}

function focusKey(s, key) {
  const sl = slotOf(s, key);
  if (!sl || s.view !== 'slots' || s.sel[sl] !== key) return s;
  return { ...s, focus: sl };
}

function applyArrangement(s, spec, selSpec, ratio) {
  const all = SLOTS.flatMap((sl) => (spec[sl] || []));
  if (!all.length || all.length > MAX_SAVED_PAGES || new Set(all).size !== all.length) return s;
  if (all.some((k) => !hasTab(s, k) || isSingleOnly(s, k))) return s;
  const slots = {};
  const sel = {};
  for (const sl of SLOTS) {
    slots[sl] = [...(spec[sl] || [])];
    sel[sl] = selSpec && slots[sl].includes(selSpec[sl]) ? selSpec[sl] : slots[sl][0] || null;
  }
  const r = Number.isFinite(ratio) ? Math.min(0.9, Math.max(0.1, ratio)) : s.ratio;
  const first = SLOTS.find((sl) => slots[sl].length);
  return settle({ ...s, slots, sel, ratio: r, view: 'slots', focus: first });
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

function autoZoom(w, h) {
  if (!(w > 0) || !(h > 0)) return 1;
  return round2(Math.min(1, Math.max(AUTO_MIN, Math.min(w / REF_W, h / REF_H))));
}

function zoomFor(s, key, w, h) {
  const z = s.zooms && s.zooms[key];
  return Number.isFinite(z) ? z : autoZoom(w, h);
}

function setZoom(s, key, z) {
  if (!hasTab(s, key) || !Number.isFinite(z)) return s;
  return { ...s, zooms: { ...s.zooms, [key]: round2(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z))) } };
}

function fitZoom(s, key) {
  if (!s.zooms || s.zooms[key] === undefined) return s;
  const zooms = { ...s.zooms };
  delete zooms[key];
  return { ...s, zooms };
}

function stepZoom(s, key, dir, w, h) {
  if (!hasTab(s, key) || (dir !== 1 && dir !== -1)) return s;
  return setZoom(s, key, zoomFor(s, key, w, h) + dir * ZOOM_STEP);
}

function clampRatio(ratio, total) {
  const usable = total - GAP;
  if (usable < MIN_PANE * 2) return 0.5;
  const lo = MIN_PANE / usable;
  return Math.min(1 - lo, Math.max(lo, ratio));
}

function rects(s, area) {
  const f = { x: area.x, y: area.y, w: Math.max(0, area.w), h: Math.max(0, area.h) };
  const list = paneList(s);
  if (list.length <= 1) return { panes: list.map(() => f), dividers: [] };
  const top = list.filter((p) => p.slot === 'left' || p.slot === 'right');
  const low = list.find((p) => p.slot === 'lower');
  const rowH = low && top.length ? Math.floor((f.h - GAP) / 2) : f.h;
  const rect = {};
  const dividers = [];
  if (top.length === 2) {
    const usable = f.w - GAP;
    const a = Math.floor(usable * clampRatio(s.ratio, f.w));
    rect[top[0].slot] = { x: f.x, y: f.y, w: a, h: rowH };
    rect[top[1].slot] = { x: f.x + a + GAP, y: f.y, w: Math.max(0, usable - a), h: rowH };
    dividers.push({ rect: { x: f.x + a, y: f.y, w: GAP, h: rowH }, axis: 'x', drag: true });
  } else if (top.length === 1) {
    rect[top[0].slot] = { x: f.x, y: f.y, w: f.w, h: rowH };
  }
  if (low) {
    if (top.length) {
      rect.lower = { x: f.x, y: f.y + rowH + GAP, w: f.w, h: Math.max(0, f.h - GAP - rowH) };
      dividers.push({ rect: { x: f.x, y: f.y + rowH, w: f.w, h: GAP }, axis: 'y', drag: false });
    } else {
      rect.lower = f;
    }
  }
  return { panes: list.map((p) => rect[p.slot]), dividers };
}

function viewRect(s, rect) {
  if (paneList(s).length < 2) return rect;
  return { x: rect.x, y: rect.y + STRIP, w: rect.w, h: Math.max(0, rect.h - STRIP) };
}

function dropZones(area) {
  const f = { x: area.x, y: area.y, w: Math.max(0, area.w), h: Math.max(0, area.h) };
  const bottom = Math.floor(f.h / 3);
  const top = f.h - bottom;
  const half = Math.floor(f.w / 2);
  return [
    { id: 'left', rect: { x: f.x, y: f.y, w: half, h: top } },
    { id: 'right', rect: { x: f.x + half, y: f.y, w: f.w - half, h: top } },
    { id: 'lower', rect: { x: f.x, y: f.y + top, w: f.w, h: bottom } },
  ];
}

function serialize(s) {
  const keep = s.tabs;
  const ok = (k) => keep.some((t) => t.key === k);
  const slots = {};
  const sel = {};
  for (const sl of SLOTS) {
    slots[sl] = s.slots[sl].filter(ok);
    sel[sl] = ok(s.sel[sl]) ? s.sel[sl] : null;
  }
  return {
    version: 2,
    tabs: keep.map((t) => (t.kind === 'lh' ? { kind: 'lh', nodeId: t.nodeId, name: t.name, url: t.url } : { nodeId: t.nodeId, pageId: t.pageId })),
    slots,
    sel,
    single: ok(s.single) ? s.single : null,
    zooms: Object.fromEntries(Object.entries(s.zooms || {}).filter(([k]) => ok(k))),
    view: s.view,
    focus: s.focus,
    ratio: s.ratio,
  };
}

function fromOldPanes(saved) {
  const list = Array.isArray(saved.panes) ? saved.panes.filter((k) => typeof k === 'string') : [];
  const slots = { left: [], right: [], lower: [] };
  const mode = saved.mode;
  if (mode === 'cols' || mode === 'trio') {
    if (typeof saved.panes[0] === 'string') slots.left = [saved.panes[0]];
    if (typeof saved.panes[1] === 'string') slots.right = [saved.panes[1]];
    if (mode === 'trio' && typeof saved.panes[2] === 'string') slots.lower = [saved.panes[2]];
  }
  return { slots, single: list[0] || null, view: mode === 'cols' || mode === 'trio' ? 'slots' : 'single' };
}

function restore(saved, nodes, pages) {
  const base = emptyState();
  if (!saved || !Array.isArray(saved.tabs)) return base;
  const seen = new Set();
  const tabs = [];
  for (const t of saved.tabs) {
    if (!t || typeof t.nodeId !== 'string' || !nodes.some((n) => n.id === t.nodeId)) continue;
    if (t.kind === 'lh') {
      const name = P.cleanLastHeardName(t.name);
      if (!name || typeof t.url !== 'string') continue;
      const key = lhKey(name);
      if (seen.has(key)) continue;
      seen.add(key);
      tabs.push({ key, nodeId: t.nodeId, pageId: LH_PAGE, kind: 'lh', name, url: t.url });
      continue;
    }
    if (typeof t.pageId !== 'string' || !pages.some((p) => p.id === t.pageId)) continue;
    const key = keyOf(t.nodeId, t.pageId);
    if (seen.has(key)) continue;
    seen.add(key);
    tabs.push({ key, nodeId: t.nodeId, pageId: t.pageId });
  }
  const src = saved.slots && typeof saved.slots === 'object' ? saved : { ...saved, ...fromOldPanes(saved) };
  const slots = {};
  for (const sl of SLOTS) slots[sl] = Array.isArray(src.slots && src.slots[sl]) ? src.slots[sl].filter((k) => typeof k === 'string') : [];
  const sel = {};
  for (const sl of SLOTS) sel[sl] = src.sel && typeof src.sel[sl] === 'string' ? src.sel[sl] : null;
  return settle({
    ...base,
    tabs,
    slots,
    sel,
    single: typeof src.single === 'string' ? src.single : null,
    zooms: src.zooms && typeof src.zooms === 'object' ? Object.fromEntries(Object.entries(src.zooms).filter(([, v]) => Number.isFinite(v)).map(([k, v]) => [k, round2(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v)))])) : {},
    view: src.view === 'slots' ? 'slots' : 'single',
    focus: src.focus,
    ratio: Number.isFinite(src.ratio) ? Math.min(0.9, Math.max(0.1, src.ratio)) : 0.5,
  });
}

module.exports = {
  MIN_PANE,
  GAP,
  STRIP,
  HEADER,
  windowSize,
  SLOTS,
  SLOT_LABEL,
  SINGLE_ONLY,
  MAX_SAVED_PAGES,
  lhKey,
  itemKey,
  REF_W,
  REF_H,
  ZOOM_MIN,
  ZOOM_MAX,
  AUTO_MIN,
  ZOOM_STEP,
  autoZoom,
  zoomFor,
  setZoom,
  fitZoom,
  stepZoom,
  grid,
  emptyState,
  keyOf,
  slotOf,
  occupied,
  paneList,
  shown,
  focusedKey,
  addTab,
  showAlone,
  openKey,
  openTab,
  openLastHeard,
  putLastHeard,
  dropLastHeard,
  putInSlot,
  dropKey,
  unslot,
  addNext,
  setView,
  canSplit,
  canBack,
  closeTab,
  closeNode,
  setRatio,
  focusSlot,
  focusKey,
  applyArrangement,
  clampRatio,
  rects,
  viewRect,
  dropZones,
  serialize,
  restore,
};
