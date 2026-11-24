const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createSessionMarker } = require('../src/session');

function file() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ncs-')), 'sub', 'running.json');
}

test('the first run is not a crash, and it leaves a marker while it runs', () => {
  const f = file();
  const m = createSessionMarker(f, () => 123);
  assert.equal(m.begin().crashed, false);
  assert.deepEqual(JSON.parse(fs.readFileSync(f, 'utf8')), { pid: process.pid, at: 123 });
});

test('a run that ends cleanly removes the marker, so the next start is normal', () => {
  const f = file();
  const m = createSessionMarker(f);
  m.begin();
  m.end();
  assert.equal(fs.existsSync(f), false);
  assert.equal(createSessionMarker(f).begin().crashed, false);
});

test('a marker left behind means the last run did not exit cleanly', () => {
  const f = file();
  createSessionMarker(f).begin();
  assert.equal(createSessionMarker(f).begin().crashed, true);
  assert.equal(createSessionMarker(f).begin().crashed, true);
});

test('ending twice, or without a start, is harmless', () => {
  const f = file();
  const m = createSessionMarker(f);
  m.end();
  m.begin();
  m.end();
  m.end();
  assert.equal(fs.existsSync(f), false);
});

test('a folder that cannot be written does not throw', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ncs-'));
  const plain = path.join(dir, 'a-file');
  fs.writeFileSync(plain, 'x');
  const m = createSessionMarker(path.join(plain, 'sub', 'running.json'));
  assert.deepEqual(m.begin(), { crashed: false });
  m.end();
});
