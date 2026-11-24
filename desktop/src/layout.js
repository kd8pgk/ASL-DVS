const MIN_PANE = 240;
const GAP = 6;
const MODES = ['single', 'cols', 'rows'];

function emptyState() {
  return { tabs: [], panes: [null, null], mode: 'single', ratio: 0.5, focus: 0 };
}

function keyOf(nodeId, pageId) {
  return `${nodeId}:${pageId}`;
}

function settle(s) {
  const tabs = s.tabs;
  let mode = MODES.includes(s.mode) ? s.mode : 'single';
  if (tabs.length < 2) mode = 'single';
  const has = (k) => tabs.some((t) => t.key === k);
  const panes = s.panes.map((k) => (has(k) ? k : null));
  if (panes[0] !== null && panes[0] === panes[1]) panes[1] = null;
  let focus = s.focus === 1 ? 1 : 0;
  if (!tabs.length) return { ...s, tabs, panes: [null, null], mode: 'single', focus: 0 };
  if (mode === 'single') {
    if (panes[0] === null) panes[0] = tabs[0].key;
    panes[1] = null;
    focus = 0;
  } else {
    for (let i = 0; i < 2; i += 1) {
      if (panes[i] === null) {
        const f = tabs.find((t) => !panes.includes(t.key));
        panes[i] = f ? f.key : null;
      }
    }
  }
  return { ...s, tabs, panes, mode, focus };
}

function shown(s) {
  return s.mode === 'single' ? [s.panes[0]] : [s.panes[0], s.panes[1]];
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
  if (mode === 'single') {
    const keep = s.panes[s.focus] || s.panes[0];
    return settle({ ...s, mode, panes: [keep, null], focus: 0 });
  }
  if (s.tabs.length < 2) return s;
  const out = settle({ ...s, mode, focus: s.focus });
  if (s.mode === 'single' && out.panes[0] && out.panes[1]) {
    const at = (k) => out.tabs.findIndex((t) => t.key === k);
    if (at(out.panes[0]) > at(out.panes[1])) return { ...out, panes: [out.panes[1], out.panes[0]], focus: 1 };
  }
  return out;
}

function setRatio(s, r) {
  const n = Number(r);
  if (!Number.isFinite(n)) return s;
  return { ...s, ratio: Math.min(0.9, Math.max(0.1, n)) };
}

function focusPane(s, i) {
  if (s.mode === 'single') return { ...s, focus: 0 };
  if (i !== 0 && i !== 1) return s;
  return s.panes[i] ? { ...s, focus: i } : s;
}

function serialize(s) {
  return {
    tabs: s.tabs.map((t) => ({ nodeId: t.nodeId, pageId: t.pageId })),
    panes: s.panes,
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
  const panes = Array.isArray(saved.panes) ? saved.panes.slice(0, 2) : [null, null];
  while (panes.length < 2) panes.push(null);
  const s = {
    ...base,
    tabs,
    panes: panes.map((k) => (typeof k === 'string' ? k : null)),
    mode: saved.mode,
    ratio: Number.isFinite(saved.ratio) ? Math.min(0.9, Math.max(0.1, saved.ratio)) : 0.5,
    focus: saved.focus,
  };
  return settle(s);
}

function clampRatio(ratio, total) {
  const usable = total - GAP;
  if (usable < MIN_PANE * 2) return 0.5;
  const lo = MIN_PANE / usable;
  return Math.min(1 - lo, Math.max(lo, ratio));
}

function rects(s, area) {
  const full = { x: area.x, y: area.y, w: Math.max(0, area.w), h: Math.max(0, area.h) };
  if (s.mode === 'single') return { panes: [full], divider: null };
  if (s.mode === 'cols') {
    const usable = full.w - GAP;
    const a = Math.floor(usable * clampRatio(s.ratio, full.w));
    return {
      panes: [
        { x: full.x, y: full.y, w: a, h: full.h },
        { x: full.x + a + GAP, y: full.y, w: Math.max(0, usable - a), h: full.h },
      ],
      divider: { x: full.x + a, y: full.y, w: GAP, h: full.h },
    };
  }
  const usable = full.h - GAP;
  const a = Math.floor(usable * clampRatio(s.ratio, full.h));
  return {
    panes: [
      { x: full.x, y: full.y, w: full.w, h: a },
      { x: full.x, y: full.y + a + GAP, w: full.w, h: Math.max(0, usable - a) },
    ],
    divider: { x: full.x, y: full.y + a, w: full.w, h: GAP },
  };
}

module.exports = {
  MIN_PANE,
  GAP,
  MODES,
  emptyState,
  keyOf,
  shown,
  openTab,
  openKey,
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
