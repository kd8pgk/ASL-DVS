const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createLog } = require('../src/diag');

const fixed = () => new Date('2026-11-24T12:00:00.000Z');

test('lines go to the file with a time stamp, and the folder is made', () => {
  const dir = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ncdiag-')), 'sub');
  const file = path.join(dir, 'diagnostics.log');
  const echoed = [];
  const log = createLog(file, { now: fixed, echo: (l) => echoed.push(l) });
  log.write('hello');
  assert.equal(fs.readFileSync(file, 'utf8'), '2026-11-24T12:00:00.000Z hello\n');
  assert.deepEqual(echoed, ['2026-11-24T12:00:00.000Z hello\n']);
});

test('a full log is kept as diagnostics.log.1 instead of being wiped', () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ncdiag-')), 'diagnostics.log');
  const log = createLog(file, { max: 120, now: fixed, echo: () => {} });
  for (let i = 0; i < 5; i += 1) log.write(`line ${i} ${'x'.repeat(10)}`);
  const cur = fs.readFileSync(file, 'utf8');
  const old = fs.readFileSync(`${file}.1`, 'utf8');
  assert.ok(cur.length <= 120);
  assert.ok(old.length <= 120);
  assert.match(old, /line 2/);
  assert.match(old, /line 3/);
  assert.match(cur, /line 4/);
  assert.doesNotMatch(old + cur, /line 0/);
});

test('an unwritable log never throws', () => {
  const blocker = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ncdiag-')), 'file');
  fs.writeFileSync(blocker, '');
  const log = createLog(path.join(blocker, 'diagnostics.log'), { echo: () => {} });
  assert.doesNotThrow(() => log.write('x'));
});
