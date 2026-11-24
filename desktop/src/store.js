const fs = require('node:fs');
const path = require('node:path');
const { normalizeNode } = require('./node');

const FORMAT = 'nodecontroller-desktop-nodes';

function cleanList(list) {
  const out = [];
  const ids = new Set();
  for (const raw of Array.isArray(list) ? list : []) {
    const r = normalizeNode(raw);
    if (r.node && !ids.has(r.node.id)) {
      ids.add(r.node.id);
      out.push(r.node);
    }
  }
  return out;
}

function createStore(file) {
  function load() {
    try {
      const data = JSON.parse(fs.readFileSync(file, 'utf8'));
      return cleanList(Array.isArray(data) ? data : data.nodes);
    } catch {
      return [];
    }
  }

  function save(nodes) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ format: FORMAT, version: 1, nodes }, null, 2));
    fs.renameSync(tmp, file);
  }

  return { load, save };
}

function exportText(nodes) {
  const copy = nodes.map((n) => ({ ...n }));
  return JSON.stringify({ format: FORMAT, version: 1, nodes: copy }, null, 2);
}

function importText(existing, text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return { error: 'That file is not valid JSON.' };
  }
  const list = Array.isArray(data) ? data : data && data.nodes;
  if (!Array.isArray(list)) return { error: 'That file has no nodes in it.' };
  const nodes = existing.map((n) => ({ ...n }));
  let added = 0;
  let replaced = 0;
  let skipped = 0;
  for (const raw of list) {
    const r = normalizeNode(raw);
    if (!r.node) {
      skipped += 1;
      continue;
    }
    const i = nodes.findIndex((n) => n.id === r.node.id);
    if (i >= 0) {
      nodes[i] = r.node;
      replaced += 1;
    } else {
      nodes.push(r.node);
      added += 1;
    }
  }
  return { nodes, added, replaced, skipped };
}

module.exports = { createStore, exportText, importText, cleanList, FORMAT };
