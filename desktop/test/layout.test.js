const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../src/layout');
const { PAGES } = require('../src/node');

const NODES = [{ id: 'a' }, { id: 'b' }];
const AREA = { x: 256, y: 85, w: 1024, h: 715 };

function open(s, n, p) {
  return L.openTab(s, n, p);
}

function many() {
  let s = L.emptyState();
  for (const [n, p] of [['a', 'controller'], ['a', 'talker'], ['a', 'sysmon'], ['a', 'nodemon'], ['a', 'recorder'], ['a', 'wifimon'], ['a', 'h44']]) s = L.addTab(s, n, p);
  return s;
}

function example() {
  let s = many();
  s = L.putInSlot(s, 'a:controller', 'left');
  s = L.putInSlot(s, 'a:sysmon', 'left');
  s = L.putInSlot(s, 'a:talker', 'right');
  s = L.putInSlot(s, 'a:recorder', 'right');
  s = L.putInSlot(s, 'a:wifimon', 'right');
  s = L.putInSlot(s, 'a:nodemon', 'lower');
  return s;
}

test('grid: sidebar is 3 of 15 units and the header is a thin fixed bar', () => {
  for (const [w, sidebar, header] of [[1280, 256, 44], [1600, 320, 44], [1920, 384, 44], [1500, 300, 44]]) {
    const g = L.grid(w, 800);
    assert.deepEqual([g.sidebar, g.header, g.strip], [sidebar, header, 28], `at ${w}`);
    assert.deepEqual(g.area, { x: sidebar, y: header, w: w - sidebar, h: 800 - header });
  }
  assert.equal(L.grid(10, 1).area.h, 0);
});

test('every page opens by itself as a single page', () => {
  let s = open(open(L.emptyState(), 'a', 'controller'), 'a', 'talker');
  assert.deepEqual(s.tabs.map((t) => t.key), ['a:controller', 'a:talker']);
  assert.equal(s.view, 'single');
  assert.equal(s.single, 'a:talker');
  assert.deepEqual(L.shown(s), ['a:talker']);
  assert.equal(open(s, 'a', 'talker').tabs.length, 2);
  assert.equal(L.canSplit(s), false);
});

test('putting a page in a slot shows the slots, a lone slot is a one page view', () => {
  let s = open(open(L.emptyState(), 'a', 'controller'), 'a', 'talker');
  s = L.putInSlot(s, 'a:controller', 'left');
  assert.equal(s.view, 'slots');
  assert.deepEqual(s.slots.left, ['a:controller']);
  assert.deepEqual(L.shown(s), ['a:controller']);
  assert.equal(L.paneList(s).length, 1);
  assert.deepEqual(L.rects(s, AREA), { panes: [AREA], dividers: [] });
  assert.deepEqual(L.viewRect(s, AREA), AREA);
});

test('the layout grows as slots fill: left, then right, then lower', () => {
  let s = many();
  s = L.putInSlot(s, 'a:controller', 'left');
  assert.deepEqual(L.paneList(s).map((p) => p.slot), ['left']);
  s = L.putInSlot(s, 'a:talker', 'right');
  assert.deepEqual(L.paneList(s).map((p) => p.slot), ['left', 'right']);
  s = L.putInSlot(s, 'a:sysmon', 'lower');
  assert.deepEqual(L.paneList(s).map((p) => p.slot), ['left', 'right', 'lower']);
  assert.deepEqual(L.shown(s), ['a:controller', 'a:talker', 'a:sysmon']);
});

test('your example: Controller and SysMon left, Talker, Recorder and WifiMon right, Node Monitor lower', () => {
  const s = example();
  assert.deepEqual(s.slots, { left: ['a:controller', 'a:sysmon'], right: ['a:talker', 'a:recorder', 'a:wifimon'], lower: ['a:nodemon'] });
  assert.deepEqual(s.sel, { left: 'a:sysmon', right: 'a:wifimon', lower: 'a:nodemon' });
  assert.equal(s.view, 'slots');
  assert.equal(s.focus, 'lower');
});

test('clicking a page in a slot selects it, focuses its slot and keeps the others showing', () => {
  let s = example();
  s = L.showAlone(s, 'a:h44');
  assert.equal(s.view, 'single');
  s = L.openKey(s, 'a:recorder');
  assert.equal(s.view, 'slots');
  assert.equal(s.focus, 'right');
  assert.deepEqual(L.shown(s), ['a:sysmon', 'a:recorder', 'a:nodemon']);
  s = L.openKey(s, 'a:controller');
  assert.deepEqual(L.shown(s), ['a:controller', 'a:recorder', 'a:nodemon']);
  assert.equal(s.focus, 'left');
  assert.equal(L.focusedKey(s), 'a:controller');
});

test('clicking a page that is not in a slot shows it alone and the slots stay', () => {
  let s = example();
  s = L.addTab(s, 'b', 'talker');
  s = L.openKey(s, 'b:talker');
  assert.equal(s.view, 'single');
  assert.deepEqual(L.shown(s), ['b:talker']);
  assert.deepEqual(s.slots.left, ['a:controller', 'a:sysmon']);
  assert.equal(L.canBack(s), true);
  const back = L.setView(s, 'slots');
  assert.equal(back.view, 'slots');
  assert.deepEqual(L.shown(back), ['a:sysmon', 'a:wifimon', 'a:nodemon']);
});

test('any page can go in any slot, and moving it takes it out of the old one', () => {
  let s = example();
  s = L.putInSlot(s, 'a:nodemon', 'left');
  assert.deepEqual(s.slots.lower, []);
  assert.equal(s.sel.lower, null);
  assert.deepEqual(s.slots.left, ['a:controller', 'a:sysmon', 'a:nodemon']);
  assert.deepEqual(L.paneList(s).map((p) => p.slot), ['left', 'right']);
  s = L.putInSlot(s, 'a:controller', 'lower');
  assert.deepEqual(s.slots.left, ['a:sysmon', 'a:nodemon']);
  assert.equal(s.sel.left, 'a:nodemon');
  assert.deepEqual(s.slots.lower, ['a:controller']);
});

test('dropping on the slot a page is already in only selects it', () => {
  let s = example();
  s = L.putInSlot(s, 'a:sysmon', 'left');
  assert.deepEqual(s.slots.left, ['a:controller', 'a:sysmon']);
  assert.equal(s.sel.left, 'a:sysmon');
});

test('44helper is always a single page and never goes in a slot', () => {
  const s = many();
  assert.equal(L.putInSlot(s, 'a:h44', 'left'), s);
  assert.equal(L.addNext(s, 'a:h44').view, 'single');
  assert.equal(L.addNext(s, 'a:h44').single, 'a:h44');
  assert.ok(L.SINGLE_ONLY.has('h44'));
  assert.deepEqual(PAGES.filter((p) => p.single).map((p) => p.id), [...L.SINGLE_ONLY]);
  const t = L.openTab(example(), 'a', 'h44');
  assert.equal(t.view, 'single');
  assert.deepEqual(L.shown(t), ['a:h44']);
});

test('Ctrl+click puts a page in the next empty slot, then in the focused one', () => {
  let s = many();
  s = L.addNext(s, 'a:controller');
  assert.deepEqual(s.slots.left, ['a:controller']);
  s = L.addNext(s, 'a:talker');
  assert.deepEqual(s.slots.right, ['a:talker']);
  s = L.addNext(s, 'a:sysmon');
  assert.deepEqual(s.slots.lower, ['a:sysmon']);
  s = L.focusSlot(s, 'right');
  s = L.addNext(s, 'a:nodemon');
  assert.deepEqual(s.slots.right, ['a:talker', 'a:nodemon']);
  const again = L.addNext(s, 'a:controller');
  assert.equal(again.focus, 'left');
  assert.deepEqual(again.slots, s.slots);
});

test('taking a page out of a slot returns it to the single pages', () => {
  let s = example();
  s = L.unslot(s, 'a:talker');
  assert.deepEqual(s.slots.right, ['a:recorder', 'a:wifimon']);
  assert.equal(s.sel.right, 'a:wifimon');
  assert.equal(L.slotOf(s, 'a:talker'), null);
  assert.ok(s.tabs.some((t) => t.key === 'a:talker'));
  let t = L.unslot(L.unslot(L.putInSlot(L.addTab(L.emptyState(), 'a', 'controller'), 'a:controller', 'left'), 'a:controller'), 'a:controller');
  assert.equal(t.view, 'single');
  assert.equal(t.single, 'a:controller');
  assert.equal(L.unslot(s, 'a:h44'), s);
});

test('closing a page takes it out of its slot; the slot shows the next one; empty slots disappear', () => {
  let s = example();
  s = L.closeTab(s, 'a:nodemon');
  assert.deepEqual(L.paneList(s).map((p) => p.slot), ['left', 'right']);
  s = L.closeTab(s, 'a:controller');
  assert.equal(s.sel.left, 'a:sysmon');
  s = L.closeTab(s, 'a:sysmon');
  assert.deepEqual(L.paneList(s).map((p) => p.slot), ['right']);
  assert.equal(s.view, 'slots');
});

test('closing the page shown alone goes back to the slots, or to another page', () => {
  let s = L.showAlone(example(), 'a:h44');
  s = L.closeTab(s, 'a:h44');
  assert.equal(s.view, 'slots');
  let t = L.closeTab(open(open(L.emptyState(), 'a', 'controller'), 'a', 'talker'), 'a:talker');
  assert.equal(t.single, 'a:controller');
  assert.deepEqual(L.closeTab(open(L.emptyState(), 'a', 'controller'), 'a:controller'), L.emptyState());
});

test('closing a node closes all its pages, Last Heard from it too', () => {
  let s = L.openLastHeard(example(), 'a', 'https://lh.example/x');
  s = L.openTab(s, 'b', 'talker');
  s = L.closeNode(s, 'a');
  assert.deepEqual(s.tabs.map((t) => t.key), ['b:talker']);
  assert.deepEqual(s.slots, { left: [], right: [], lower: [] });
});

test('the view buttons: single shows the focused page alone, slots brings the slots back', () => {
  let s = example();
  s = L.focusSlot(s, 'right');
  s = L.setView(s, 'single');
  assert.deepEqual(L.shown(s), ['a:wifimon']);
  assert.equal(L.setView(s, 'single'), s);
  s = L.setView(s, 'slots');
  assert.equal(L.paneList(s).length, 3);
  const none = open(L.emptyState(), 'a', 'controller');
  assert.equal(L.setView(none, 'slots'), none);
});

test('Last Heard opens as a single page and can be put in a slot like any page', () => {
  let s = L.openLastHeard(example(), 'a', 'https://lh.example/x');
  assert.equal(s.view, 'single');
  assert.deepEqual(L.shown(s), ['lh']);
  assert.equal(s.tabs.find((t) => t.key === 'lh').url, 'https://lh.example/x');
  s = L.openLastHeard(s, 'a', 'https://lh.example/y');
  assert.equal(s.tabs.filter((t) => t.key === 'lh').length, 1);
  assert.equal(s.tabs.find((t) => t.key === 'lh').url, 'https://lh.example/y');
  s = L.putInSlot(s, 'lh', 'lower');
  assert.deepEqual(s.slots.lower, ['a:nodemon', 'lh']);
  assert.equal(s.sel.lower, 'lh');
});

test('focus follows the page that was clicked into, only for the selected page of a slot', () => {
  let s = example();
  s = L.focusKey(s, 'a:sysmon');
  assert.equal(s.focus, 'left');
  const same = L.focusKey(s, 'a:controller');
  assert.equal(same, s);
  assert.equal(L.focusKey(s, 'a:h44'), s);
  assert.equal(L.focusSlot(s, 'nowhere'), s);
});

test('ratio is kept between 0.1 and 0.9 and ignores junk', () => {
  const s = L.emptyState();
  assert.equal(L.setRatio(s, 5).ratio, 0.9);
  assert.equal(L.setRatio(s, -1).ratio, 0.1);
  assert.equal(L.setRatio(s, 'x'), s);
});

test('rects: left and right are 6 and 6, with a gap and a drag handle', () => {
  let s = L.putInSlot(L.putInSlot(many(), 'a:controller', 'left'), 'a:talker', 'right');
  const r = L.rects(s, AREA);
  assert.equal(r.panes[0].w + L.GAP + r.panes[1].w, 1024);
  assert.equal(r.panes[0].w, 509);
  assert.deepEqual(r.panes.map((p) => p.h), [715, 715]);
  assert.deepEqual(r.dividers, [{ rect: { x: 256 + 509, y: 85, w: L.GAP, h: 715 }, axis: 'x', drag: true }]);
});

test('rects: left, right and lower are two over one with equal rows', () => {
  const r = L.rects(example(), AREA);
  const [a, b, c] = r.panes;
  assert.equal(a.y, b.y);
  assert.equal(a.h, b.h);
  assert.deepEqual([c.x, c.w], [AREA.x, AREA.w]);
  assert.equal(c.y, a.y + a.h + L.GAP);
  assert.ok(Math.abs(c.h - a.h) <= 1);
  assert.equal(a.h + L.GAP + c.h, AREA.h);
  assert.deepEqual(r.dividers.map((d) => [d.axis, d.drag]), [['x', true], ['y', false]]);
});

test('rects: any mix of slots fills the area: one over one when only one of left or right and lower are used', () => {
  let s = L.putInSlot(L.putInSlot(many(), 'a:controller', 'right'), 'a:talker', 'lower');
  let r = L.rects(s, AREA);
  assert.equal(L.paneList(s).map((p) => p.slot).join(), 'right,lower');
  assert.deepEqual([r.panes[0].x, r.panes[0].w, r.panes[1].x, r.panes[1].w], [AREA.x, AREA.w, AREA.x, AREA.w]);
  assert.equal(r.panes[0].h + L.GAP + r.panes[1].h, AREA.h);
  assert.deepEqual(r.dividers.map((d) => d.axis), ['y']);
  s = L.putInSlot(many(), 'a:talker', 'lower');
  assert.deepEqual(L.rects(s, AREA), { panes: [AREA], dividers: [] });
  s = L.putInSlot(L.putInSlot(many(), 'a:controller', 'right'), 'a:talker', 'left');
  r = L.rects(s, AREA);
  assert.equal(r.panes[0].x < r.panes[1].x, true);
});

test('rects: the ratio moves only the top row, and a pane keeps its minimum width', () => {
  const r = L.rects(example(), { x: 0, y: 0, w: 1000, h: 700 });
  assert.ok(r.panes[0].w >= L.MIN_PANE && r.panes[1].w >= L.MIN_PANE);
  const lo = L.rects(L.setRatio(example(), 0.1), { x: 0, y: 0, w: 1000, h: 700 });
  const hi = L.rects(L.setRatio(example(), 0.95), { x: 0, y: 0, w: 1000, h: 700 });
  assert.ok(lo.panes[0].w >= L.MIN_PANE);
  assert.ok(hi.panes[1].w >= L.MIN_PANE);
  assert.equal(lo.panes[2].w, 1000);
});

test('viewRect leaves a strip above each pane when two or more show, none for one', () => {
  const r = { x: 10, y: 20, w: 300, h: 400 };
  assert.deepEqual(L.viewRect(example(), r), { x: 10, y: 20 + L.STRIP, w: 300, h: 400 - L.STRIP });
  assert.deepEqual(L.viewRect(L.showAlone(example(), 'a:h44'), r), r);
  assert.equal(L.viewRect(example(), { x: 0, y: 0, w: 5, h: 10 }).h, 0);
});

test('drop zones are always left, right and lower: halves on top, a third below', () => {
  const z = L.dropZones(AREA);
  assert.deepEqual(z.map((x) => x.id), ['left', 'right', 'lower']);
  assert.equal(z[0].rect.w + z[1].rect.w, AREA.w);
  assert.equal(z[1].rect.x, z[0].rect.x + z[0].rect.w);
  assert.deepEqual([z[2].rect.x, z[2].rect.w], [AREA.x, AREA.w]);
  assert.equal(z[0].rect.h + z[2].rect.h, AREA.h);
  assert.ok(Math.abs(z[2].rect.h - AREA.h / 3) <= 1);
  assert.equal(z[2].rect.y, z[0].rect.y + z[0].rect.h);
});

test('applyArrangement sets the slots from existing pages only', () => {
  const s = many();
  const a = L.applyArrangement(s, { left: ['a:controller', 'a:sysmon'], right: ['a:talker'], lower: [] }, { left: 'a:sysmon' }, 0.3);
  assert.deepEqual(a.slots.left, ['a:controller', 'a:sysmon']);
  assert.equal(a.sel.left, 'a:sysmon');
  assert.equal(a.sel.right, 'a:talker');
  assert.equal(a.ratio, 0.3);
  assert.equal(a.view, 'slots');
  assert.equal(L.applyArrangement(s, { left: [], right: [], lower: [] }, {}, 0.5), s);
  assert.equal(L.applyArrangement(s, { left: ['a:controller', 'a:controller'] }, {}, 0.5), s);
  assert.equal(L.applyArrangement(s, { left: ['b:talker'] }, {}, 0.5), s);
  assert.equal(L.applyArrangement(s, { left: ['a:h44'] }, {}, 0.5), s);
});

test('serialize then restore gives the same layout', () => {
  let s = L.setRatio(example(), 0.3);
  s = L.focusSlot(L.openKey(s, 'a:recorder'), 'right');
  s = L.showAlone(s, 'a:h44');
  const back = L.restore(JSON.parse(JSON.stringify(L.serialize(s))), NODES, PAGES);
  assert.deepEqual(back.tabs, s.tabs);
  for (const k of ['slots', 'sel', 'single', 'view', 'focus', 'ratio']) assert.deepEqual(back[k], s[k], k);
});

test('Last Heard is not saved', () => {
  let s = L.putInSlot(L.openLastHeard(example(), 'a', 'https://lh.example/x'), 'lh', 'lower');
  const saved = L.serialize(s);
  assert.equal(JSON.stringify(saved).includes('lh'), false);
  assert.equal(saved.tabs.some((t) => t.pageId === 'lasthard'), false);
  const back = L.restore(JSON.parse(JSON.stringify(saved)), NODES, PAGES);
  assert.equal(back.tabs.some((t) => t.key === 'lh'), false);
  assert.equal(back.sel.lower, 'a:nodemon');
});

test('restore drops pages of missing nodes or pages and repairs the rest', () => {
  const saved = {
    tabs: [{ nodeId: 'a', pageId: 'controller' }, { nodeId: 'gone', pageId: 'talker' }, { nodeId: 'a', pageId: 'nope' }, { nodeId: 'a', pageId: 'controller' }],
    slots: { left: ['gone:talker', 'a:controller'], right: ['a:nope'], lower: [] },
    sel: { left: 'gone:talker', right: 'a:nope', lower: null },
    single: 'gone:talker',
    view: 'slots',
    focus: 'right',
    ratio: 7,
  };
  const s = L.restore(saved, NODES, PAGES);
  assert.deepEqual(s.tabs.map((t) => t.key), ['a:controller']);
  assert.deepEqual(s.slots, { left: ['a:controller'], right: [], lower: [] });
  assert.equal(s.sel.left, 'a:controller');
  assert.equal(s.focus, 'left');
  assert.equal(s.ratio, 0.9);
  assert.equal(s.view, 'slots');
});

test('restore reads the 0.5.0 layout file: two or three panes become left, right and lower', () => {
  const old = { tabs: [{ nodeId: 'a', pageId: 'controller' }, { nodeId: 'a', pageId: 'talker' }, { nodeId: 'a', pageId: 'sysmon' }], panes: ['a:talker', 'a:controller', 'a:sysmon'], mode: 'trio', ratio: 0.4, focus: 1 };
  const s = L.restore(old, NODES, PAGES);
  assert.deepEqual(s.slots, { left: ['a:talker'], right: ['a:controller'], lower: ['a:sysmon'] });
  assert.equal(s.view, 'slots');
  assert.equal(s.ratio, 0.4);
  const one = L.restore({ tabs: [{ nodeId: 'a', pageId: 'controller' }], panes: ['a:controller', null, null], mode: 'single' }, NODES, PAGES);
  assert.equal(one.view, 'single');
  assert.equal(one.single, 'a:controller');
});

test('restore of junk gives an empty layout', () => {
  assert.deepEqual(L.restore(null, NODES, PAGES), L.emptyState());
  assert.deepEqual(L.restore({ tabs: 5 }, NODES, PAGES), L.emptyState());
  const s = L.restore({ tabs: [{ nodeId: 'a', pageId: 'controller' }], slots: 7, sel: 3, view: 'weird' }, NODES, PAGES);
  assert.equal(s.view, 'single');
  assert.equal(s.single, 'a:controller');
});

test('auto zoom scales a page down to fit a small pane, never up, never below the floor', () => {
  assert.equal(L.autoZoom(1024, 715), 1);
  assert.equal(L.autoZoom(800, 500), 1);
  assert.equal(L.autoZoom(509, 325), 0.64);
  assert.equal(L.autoZoom(1024, 325), 0.65);
  assert.equal(L.autoZoom(509, 687), 0.64);
  assert.equal(L.autoZoom(300, 200), 0.5);
  assert.equal(L.autoZoom(0, 100), 1);
  assert.equal(L.autoZoom(NaN, 100), 1);
  assert.equal(L.AUTO_MIN, 0.5);
});

test('the three page layout at 1280 wide scales the top panes and the lower pane to fit', () => {
  const g = L.grid(1280, 800);
  const st = L.putInSlot(L.putInSlot(L.putInSlot(many(), 'a:controller', 'left'), 'a:talker', 'right'), 'a:nodemon', 'lower');
  const r = L.rects(st, g.area);
  const sizes = r.panes.map((p) => L.viewRect(st, p)).map((v) => L.autoZoom(v.w, v.h));
  assert.ok(sizes.every((z) => z < 1 && z >= 0.5), JSON.stringify(sizes));
  const one = L.showAlone(st, 'a:controller');
  const v = L.rects(one, g.area).panes[0];
  assert.equal(L.zoomFor(one, 'a:controller', v.w, v.h), 1);
});

test('a manual zoom wins over the automatic one, steps by a tenth within limits, and Fit clears it', () => {
  let s = open(open(L.emptyState(), 'a', 'controller'), 'a', 'talker');
  assert.equal(L.zoomFor(s, 'a:talker', 509, 325), 0.64);
  s = L.stepZoom(s, 'a:talker', 1, 509, 325);
  assert.equal(L.zoomFor(s, 'a:talker', 509, 325), 0.74);
  assert.equal(L.zoomFor(s, 'a:controller', 509, 325), 0.64);
  s = L.stepZoom(s, 'a:talker', -1, 509, 325);
  s = L.stepZoom(s, 'a:talker', -1, 509, 325);
  assert.equal(L.zoomFor(s, 'a:talker', 509, 325), 0.54);
  for (let i = 0; i < 20; i += 1) s = L.stepZoom(s, 'a:talker', -1, 509, 325);
  assert.equal(L.zoomFor(s, 'a:talker', 509, 325), L.ZOOM_MIN);
  for (let i = 0; i < 40; i += 1) s = L.stepZoom(s, 'a:talker', 1, 509, 325);
  assert.equal(L.zoomFor(s, 'a:talker', 509, 325), L.ZOOM_MAX);
  s = L.fitZoom(s, 'a:talker');
  assert.equal(L.zoomFor(s, 'a:talker', 509, 325), 0.64);
  assert.equal(L.fitZoom(s, 'a:talker'), s);
  assert.equal(L.stepZoom(s, 'nope', 1, 1, 1), s);
  assert.equal(L.stepZoom(s, 'a:talker', 2, 1, 1), s);
  assert.equal(L.setZoom(s, 'a:talker', 'x'), s);
  assert.equal(L.setZoom(s, 'a:talker', 99).zooms['a:talker'], L.ZOOM_MAX);
});

test('zooms are kept for open pages only, saved and restored, and Last Heard is not saved', () => {
  let s = L.setZoom(L.setZoom(example(), 'a:controller', 0.8), 'a:talker', 0.55);
  s = L.setZoom(L.openLastHeard(s, 'a', 'https://lh.example/x'), 'lh', 0.7);
  const saved = L.serialize(s);
  assert.deepEqual(saved.zooms, { 'a:controller': 0.8, 'a:talker': 0.55 });
  const back = L.restore(JSON.parse(JSON.stringify(saved)), NODES, PAGES);
  assert.deepEqual(back.zooms, { 'a:controller': 0.8, 'a:talker': 0.55 });
  const closed = L.closeTab(s, 'a:controller');
  assert.equal(closed.zooms['a:controller'], undefined);
  assert.equal(closed.zooms['a:talker'], 0.55);
  const odd = L.restore({ tabs: [{ nodeId: 'a', pageId: 'controller' }], zooms: { 'a:controller': 'x', 'a:gone': 0.6, 'a:talker': 0.5 } }, NODES, PAGES);
  assert.deepEqual(odd.zooms, {});
  const wide = L.restore({ tabs: [{ nodeId: 'a', pageId: 'controller' }], zooms: { 'a:controller': 9 } }, NODES, PAGES);
  assert.equal(wide.zooms['a:controller'], L.ZOOM_MAX);
});
