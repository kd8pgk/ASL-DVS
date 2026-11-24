const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createStore, exportText, importText } = require('../src/store');
const { normalizeNode } = require('../src/node');

function tmp() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ncd-')), 'nodes.json');
}

test('a missing or broken file loads as no nodes', () => {
  const f = tmp();
  assert.deepEqual(createStore(f).load(), []);
  fs.writeFileSync(f, '{nope');
  assert.deepEqual(createStore(f).load(), []);
});

test('save then load returns the same nodes', () => {
  const f = tmp();
  const s = createStore(f);
  const a = normalizeNode({ name: 'A', host: 'a.local' }).node;
  const b = normalizeNode({ name: 'B', host: 'https://b.local', awayHost: 'b.example.com' }).node;
  s.save([a, b]);
  assert.deepEqual(s.load(), [a, b]);
  assert.equal(fs.existsSync(`${f}.tmp`), false);
});

test('bad entries and repeated ids are dropped on load', () => {
  const f = tmp();
  const a = normalizeNode({ name: 'A', host: 'a.local' }).node;
  fs.writeFileSync(f, JSON.stringify({ nodes: [a, a, { host: 'bad host' }, null, 5] }));
  assert.deepEqual(createStore(f).load(), [a]);
});

test('export then import into an empty list restores the nodes', () => {
  const a = normalizeNode({ name: 'A', host: 'a.local' }).node;
  const r = importText([], exportText([a]));
  assert.deepEqual(r.nodes, [a]);
  assert.deepEqual([r.added, r.replaced, r.skipped], [1, 0, 0]);
});

test('import replaces a node with the same id and adds the rest', () => {
  const a = normalizeNode({ name: 'A', host: 'a.local' }).node;
  const a2 = { ...a, name: 'A renamed' };
  const c = normalizeNode({ name: 'C', host: 'c.local' }).node;
  const r = importText([a], JSON.stringify([a2, c, { host: '' }]));
  assert.deepEqual(r.nodes.map((n) => n.name), ['A renamed', 'C']);
  assert.deepEqual([r.added, r.replaced, r.skipped], [1, 1, 1]);
});

test('import refuses text that is not a node file', () => {
  assert.match(importText([], 'x').error, /JSON/);
  assert.match(importText([], '{"a":1}').error, /no nodes/);
});
