const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const R = require('../src/ram');

function base() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'nbram-'));
}

test('the working folder is private to the user and holds every place Chromium and the desktop write to', () => {
  const b = base();
  const r = R.createRamDir(b);
  assert.equal(fs.statSync(r.dir).mode & 0o777, 0o700);
  for (const k of ['home', 'config', 'cache', 'data', 'state', 'chromium', 'session', 'temp', 'files']) assert.ok(fs.statSync(r.sub[k]).isDirectory(), k);
  assert.equal(fs.readFileSync(path.join(r.dir, 'pid'), 'utf8'), String(process.pid));
  assert.ok(path.basename(r.dir).startsWith(R.PREFIX));
  fs.writeFileSync(path.join(r.sub.chromium, 'Cookies'), 'x');
  assert.equal(R.rammaidRemove(r.dir), true);
  assert.equal(fs.existsSync(r.dir), false);
});

test('a folder left by a crashed run is removed at the next start; a running one is kept', () => {
  const b = base();
  const dead = R.createRamDir(b, 999999);
  const live = R.createRamDir(b, process.pid);
  assert.equal(R.rammaidSweep(b), 1);
  assert.equal(fs.existsSync(dead.dir), false);
  assert.equal(fs.existsSync(live.dir), true);
});

test('only Null Browser folders are ever removed', () => {
  const b = base();
  const other = path.join(b, 'something-else');
  fs.mkdirSync(other);
  assert.equal(R.rammaidRemove(other), false);
  assert.equal(R.rammaidSweep(b), 0);
  assert.equal(fs.existsSync(other), true);
});

test('the RAM folder is /dev/shm when there is one, or an override for tests', () => {
  assert.deepEqual(R.ramBase('/x/y'), { dir: '/x/y', ram: true });
  const r = R.ramBase('');
  if (fs.existsSync('/dev/shm')) assert.deepEqual(r, { dir: '/dev/shm', ram: true });
  else assert.equal(r.ram, false);
});

test('a directory the launcher wrapper already built is adopted, not recreated, as long as the folder is its own', () => {
  const b = base();
  const wrapperMade = path.join(b, `${R.PREFIX}0-12345-abcdef`);
  fs.mkdirSync(wrapperMade, { mode: 0o700 });
  fs.writeFileSync(path.join(wrapperMade, 'pid'), '12345');
  assert.equal(R.prelaunchDir(wrapperMade), wrapperMade);
  assert.equal(R.prelaunchDir(path.join(b, 'not-ours')), '');
  assert.equal(R.prelaunchDir('relative/null-browser-x'), '');
  assert.equal(R.prelaunchDir(''), '');
  assert.equal(R.prelaunchDir(path.join(b, `${R.PREFIX}missing`)), '');

  const adopted = R.adoptRamDir(wrapperMade);
  assert.equal(adopted.dir, wrapperMade);
  for (const k of ['home', 'config', 'cache', 'data', 'state', 'chromium', 'session', 'temp', 'files']) assert.ok(fs.statSync(adopted.sub[k]).isDirectory(), k);
  assert.equal(R.rammaidRemove(adopted.dir), true);
});

test('after quit a detached cleaner waits for the browser to end, then removes the folder', () => {
  const calls = [];
  const fake = (cmd, args, opts) => {
    calls.push({ cmd, args, opts });
    return { unref() {} };
  };
  const b = base();
  const r = R.createRamDir(b);
  assert.equal(R.rammaidAfterExit(r.dir, 4242, fake), true);
  assert.equal(calls[0].cmd, '/bin/sh');
  assert.deepEqual(calls[0].args.slice(2), ['null-browser-clean', '4242', r.dir]);
  assert.match(calls[0].args[1], /kill -0 "\$1".*rm -rf -- "\$2"/);
  assert.equal(calls[0].opts.detached, true);
  assert.equal(R.rammaidAfterExit(path.join(b, 'other'), 1, fake), false);
  assert.equal(R.rammaidAfterExit('relative/null-browser-x', 1, fake), false);
  assert.equal(calls.length, 1);
});

test('the real home comes from the launcher, never from a RAM folder, and a restart gets the original environment back', () => {
  const b = base();
  const home = path.join(b, 'user');
  fs.mkdirSync(home);
  assert.equal(R.realHome({ NULLBROWSER_REAL_HOME: home }, '/fallback'), home);
  assert.equal(R.realHome({}, '/fallback'), '/fallback');
  assert.equal(R.realHome({ NULLBROWSER_REAL_HOME: 'relative' }, '/fallback'), '/fallback');
  assert.equal(R.realHome({ NULLBROWSER_REAL_HOME: path.join(b, 'gone') }, '/fallback'), '/fallback');
  assert.equal(R.realHome({ NULLBROWSER_REAL_HOME: path.join(b, `${R.PREFIX}0-1-x`) }, '/fallback'), '/fallback');
  const ram = path.join(b, `${R.PREFIX}0-1-x`);
  const env = R.relaunchEnv({ HOME: path.join(ram, 'home'), TMPDIR: path.join(ram, 'temp'), XDG_CONFIG_HOME: '/home/u/.config', XDG_CACHE_HOME: path.join(ram, 'cache') }, ram, '/home/u');
  assert.deepEqual(env, { NULLBROWSER_PRELAUNCH_DIR: null, NULLBROWSER_REAL_HOME: '/home/u', HOME: '/home/u', TMPDIR: null, XDG_CACHE_HOME: null });
});
