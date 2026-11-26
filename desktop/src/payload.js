const L = require('./layout');
const PR = require('./presets');
const { PAGES } = require('./node');

function labelOf(tab, nodes) {
  if (tab.kind === 'lh') return tab.name;
  const n = nodes.find((x) => x.id === tab.nodeId);
  const p = PAGES.find((x) => x.id === tab.pageId);
  return `${n ? n.name || n.host : '?'} · ${p ? p.label : '?'}`;
}

function shortLabel(ls, key) {
  const t = ls.tabs.find((x) => x.key === key);
  if (!t) return '';
  if (t.kind === 'lh') return t.name;
  const p = PAGES.find((x) => x.id === t.pageId);
  return p ? p.label : t.pageId;
}

function buildPayload({ ls, nodes, splits, rt, grid: g, down, overlay, restart }) {
  const r = L.rects(ls, g.area);
  const list = L.paneList(ls);
  const vis = list.map((p) => p.key);
  const pageOf = (t) => PAGES.find((x) => x.id === t.pageId);
  const zoomOf = {};
  list.forEach((p, i) => {
    const v = L.viewRect(ls, r.panes[i]);
    zoomOf[p.key] = L.zoomFor(ls, p.key, v.w, v.h);
  });
  return {
    grid: { sidebar: g.sidebar, header: g.header, strip: g.strip },
    view: ls.view,
    ratio: ls.ratio,
    focus: ls.focus,
    down,
    canSplit: L.canSplit(ls),
    canBack: L.canBack(ls),
    canSave: L.SLOTS.reduce((n, sl) => n + ls.slots[sl].length, 0) >= 2,
    splits: splits.map((p) => ({ id: p.id, name: p.name, count: PR.count(p) })),
    zones: L.dropZones(g.area),
    overlay,
    restart,
    slots: L.SLOTS.map((sl) => ({
      slot: sl,
      label: L.SLOT_LABEL[sl],
      pages: ls.slots[sl].map((k) => ({ key: k, label: labelOf(ls.tabs.find((t) => t.key === k), nodes), selected: ls.sel[sl] === k })),
    })),
    tabs: ls.tabs.map((t) => {
      const e = rt.get(t.key);
      const pg = pageOf(t);
      return {
        key: t.key,
        nodeId: t.nodeId,
        pageId: t.pageId,
        kind: t.kind || 'page',
        label: labelOf(t, nodes),
        slot: L.slotOf(ls, t.key),
        singleOnly: Boolean(pg && pg.single),
        shown: vis.includes(t.key),
        zoom: zoomOf[t.key] === undefined ? 1 : zoomOf[t.key],
        focused: vis.includes(t.key) && L.focusedKey(ls) === t.key,
        status: e ? e.status : 'idle',
        idle: e ? e.idle === true : true,
        via: e ? e.via : 'home',
      };
    }),
    panes: list.map((p, i) => {
      const e = rt.get(p.key);
      const rect = r.panes[i];
      return {
        slot: p.slot,
        key: p.key,
        rect,
        view: L.viewRect(ls, rect),
        label: labelOf(ls.tabs.find((t) => t.key === p.key), nodes),
        zoom: zoomOf[p.key],
        zoomSet: ls.zooms[p.key] !== undefined,
        stack: p.slot ? ls.slots[p.slot].map((k) => ({ key: k, label: shortLabel(ls, k), selected: k === p.key })) : [],
        status: e ? e.status : 'loading',
        error: e && e.status === 'failed' ? e.error : null,
      };
    }),
    strips: list.length >= 2,
    dividers: r.dividers,
  };
}

module.exports = { labelOf, shortLabel, buildPayload };
