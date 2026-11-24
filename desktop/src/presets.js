const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const L = require('./layout');

const MAX = 20;
const NAME_MAX = 40;

function normalizePreset(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const name = String(raw.name == null ? '' : raw.name).trim().slice(0, NAME_MAX);
  if (!name || !Array.isArray(raw.items) || raw.items.length < 2 || raw.items.length > 3) return null;
  const items = [];
  const seen = new Set();
  for (const it of raw.items) {
    if (!it || typeof it.nodeId !== 'string' || typeof it.pageId !== 'string') return null;
    const key = L.keyOf(it.nodeId, it.pageId);
    if (seen.has(key)) return null;
    seen.add(key);
    items.push({ nodeId: it.nodeId, pageId: it.pageId });
  }
  const ratio = Number.isFinite(raw.ratio) ? Math.min(0.9, Math.max(0.1, raw.ratio)) : 0.5;
  return {
    id: typeof raw.id === 'string' && raw.id ? raw.id : crypto.randomUUID(),
    name,
    mode: items.length === 3 ? 'trio' : 'cols',
    items,
    ratio,
  };
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
    fs.writeFileSync(tmp, JSON.stringify({ version: 1, splits: list }, null, 2));
    fs.renameSync(tmp, file);
  }

  return { load, save };
}

function fromState(s, name) {
  const sv = s.mode === 'single' ? L.savedOf(s) : { mode: s.mode, panes: s.panes };
  if (!sv) return { error: 'There is no split to save. Show two or three pages together first.' };
  const keys = sv.panes.slice(0, L.COUNT[sv.mode]).filter(Boolean);
  const tabs = keys.map((k) => s.tabs.find((t) => t.key === k));
  if (tabs.some((t) => !t || t.kind === 'lh')) return { error: 'A split that holds Last Heard cannot be saved, because its page is not kept.' };
  const preset = normalizePreset({ name, items: tabs.map((t) => ({ nodeId: t.nodeId, pageId: t.pageId })), ratio: s.ratio });
  if (!preset) return { error: 'Give the split a name.' };
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

function apply(s, preset, nodes, pages) {
  for (const it of preset.items) {
    if (!nodes.some((n) => n.id === it.nodeId)) return { error: `"${preset.name}" uses a node that has been deleted.` };
    if (!pages.some((p) => p.id === it.pageId)) return { error: `"${preset.name}" uses a page that does not exist.` };
  }
  let next = s;
  for (const it of preset.items) next = L.addTab(next, it.nodeId, it.pageId);
  const keys = preset.items.map((it) => L.keyOf(it.nodeId, it.pageId));
  const done = L.applyArrangement(next, preset.mode, keys, preset.ratio);
  if (done === next) return { error: 'That split could not be shown.' };
  return { state: done };
}

module.exports = { MAX, NAME_MAX, normalizePreset, createPresetStore, fromState, put, apply };
