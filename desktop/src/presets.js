const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const L = require('./layout');
const P = require('./policy');

const MAX = 20;
const NAME_MAX = 40;

function normalizeItem(it) {
  if (!it || typeof it.nodeId !== 'string' || !it.nodeId) return null;
  if (it.kind === 'lh') {
    const name = P.cleanLastHeardName(it.name);
    return name && typeof it.url === 'string' && it.url ? { kind: 'lh', nodeId: it.nodeId, name, url: it.url } : null;
  }
  if (typeof it.pageId !== 'string' || !it.pageId) return null;
  return { nodeId: it.nodeId, pageId: it.pageId };
}

function itemOf(t) {
  return t.kind === 'lh' ? { kind: 'lh', nodeId: t.nodeId, name: t.name, url: t.url } : { nodeId: t.nodeId, pageId: t.pageId };
}

function fromOldItems(raw) {
  const items = Array.isArray(raw.items) ? raw.items : [];
  const slots = { left: [], right: [], lower: [] };
  if (items[0]) slots.left = [items[0]];
  if (items[1]) slots.right = [items[1]];
  if (items[2]) slots.lower = [items[2]];
  return slots;
}

function normalizePreset(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const name = String(raw.name == null ? '' : raw.name).trim().slice(0, NAME_MAX);
  if (!name) return null;
  const src = raw.slots && typeof raw.slots === 'object' ? raw.slots : fromOldItems(raw);
  const slots = { left: [], right: [], lower: [] };
  const seen = new Set();
  for (const sl of L.SLOTS) {
    const list = Array.isArray(src[sl]) ? src[sl] : [];
    for (const it of list) {
      const item = normalizeItem(it);
      if (!item) return null;
      const key = L.itemKey(item);
      if (seen.has(key)) return null;
      seen.add(key);
      slots[sl].push(item);
    }
  }
  if (seen.size < 2 || seen.size > L.MAX_SAVED_PAGES) return null;
  const sel = { left: null, right: null, lower: null };
  for (const sl of L.SLOTS) {
    const want = normalizeItem(raw.sel && raw.sel[sl]);
    const hit = want && slots[sl].find((it) => L.itemKey(it) === L.itemKey(want));
    sel[sl] = hit || slots[sl][0] || null;
  }
  const ratio = Number.isFinite(raw.ratio) ? Math.min(0.9, Math.max(0.1, raw.ratio)) : 0.5;
  return { id: typeof raw.id === 'string' && raw.id ? raw.id : crypto.randomUUID(), name, slots, sel, ratio };
}

function count(preset) {
  return L.SLOTS.reduce((n, sl) => n + preset.slots[sl].length, 0);
}

function cleanList(list) {
  const out = [];
  const ids = new Set();
  for (const raw of Array.isArray(list) ? list : []) {
    const p = normalizePreset(raw);
    if (p && !ids.has(p.id) && out.length < MAX) {
      ids.add(p.id);
      out.push(p);
    }
  }
  return out;
}

function createPresetStore(file) {
  function load() {
    try {
      const data = JSON.parse(fs.readFileSync(file, 'utf8'));
      return cleanList(Array.isArray(data) ? data : data.splits);
    } catch {
      return [];
    }
  }

  function save(list) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ version: 2, splits: list }, null, 2));
    fs.renameSync(tmp, file);
  }

  return { load, save };
}

function fromState(s, name) {
  const tab = (k) => s.tabs.find((t) => t.key === k);
  const total = L.SLOTS.reduce((n, sl) => n + s.slots[sl].length, 0);
  if (total < 2) return { error: 'There is nothing to save yet. Put two or more pages in the slots first.' };
  const slots = { left: [], right: [], lower: [] };
  const sel = { left: null, right: null, lower: null };
  for (const sl of L.SLOTS) {
    for (const k of s.slots[sl]) {
      const t = tab(k);
      if (!t) return { error: 'A page in the layout is missing, so it cannot be saved.' };
      slots[sl].push(itemOf(t));
    }
    const st = s.sel[sl] && tab(s.sel[sl]);
    sel[sl] = st ? itemOf(st) : null;
  }
  const preset = normalizePreset({ name, slots, sel, ratio: s.ratio });
  if (!preset) return { error: s.tabs.length && String(name || '').trim() ? 'That split has too many pages to save.' : 'Give the split a name.' };
  return { preset };
}

function put(list, preset) {
  const i = list.findIndex((p) => p.name.toLowerCase() === preset.name.toLowerCase());
  if (i >= 0) {
    const next = list.slice();
    next[i] = { ...preset, id: list[i].id };
    return { list: next };
  }
  if (list.length >= MAX) return { error: `You can keep ${MAX} saved splits. Delete one first.` };
  return { list: [...list, preset] };
}

function apply(s, preset, nodes, pages, lhOk) {
  const all = L.SLOTS.flatMap((sl) => preset.slots[sl]);
  for (const it of all) {
    if (!nodes.some((n) => n.id === it.nodeId)) return { error: `"${preset.name}" uses a node that has been deleted.` };
    if (it.kind === 'lh') {
      if (!lhOk(it.url)) return { error: `"${preset.name}" has a Last Heard address that is not allowed.` };
    } else if (!pages.some((p) => p.id === it.pageId)) return { error: `"${preset.name}" uses a page that does not exist.` };
  }
  let next = s;
  for (const it of all) next = it.kind === 'lh' ? L.putLastHeard(next, it.nodeId, it.url, it.name) : L.addTab(next, it.nodeId, it.pageId);
  const keys = {};
  const sel = {};
  for (const sl of L.SLOTS) {
    keys[sl] = preset.slots[sl].map((it) => L.itemKey(it));
    sel[sl] = preset.sel[sl] ? L.itemKey(preset.sel[sl]) : null;
  }
  const done = L.applyArrangement(next, keys, sel, preset.ratio);
  if (done === next) return { error: 'That split could not be shown.' };
  return { state: done };
}

module.exports = { MAX, NAME_MAX, normalizePreset, count, createPresetStore, fromState, put, apply };
