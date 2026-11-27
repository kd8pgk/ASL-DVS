const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { execFileSync, spawn, spawnSync } = require('node:child_process');

const root = path.join(__dirname, '..');
const unpacked = process.env.NB_UNPACKED || path.join(root, 'dist', 'linux-unpacked');
const bin = path.join(unpacked, 'nullbrowser');
const realBin = path.join(unpacked, 'nullbrowser-bin');

const EXPECT_FUSES = {
  RunAsNode: 'Disabled',
  EnableCookieEncryption: 'Enabled',
  EnableNodeOptionsEnvironmentVariable: 'Disabled',
  EnableNodeCliInspectArguments: 'Disabled',
  EnableEmbeddedAsarIntegrityValidation: 'Enabled',
  OnlyLoadAppFromAsar: 'Enabled',
  GrantFileProtocolExtraPrivileges: 'Enabled',
};

function fuses() {
  const out = execFileSync(path.join(root, 'node_modules', '.bin', 'electron-fuses'), ['read', '--app', realBin], { encoding: 'utf8' });
  const got = {};
  for (const m of out.matchAll(/^\s+(\w+) is (Enabled|Disabled)/gm)) got[m[1]] = m[2];
  return got;
}

function asarFiles() {
  const asar = require('@electron/asar');
  return asar.listPackage(path.join(unpacked, 'resources', 'app.asar')).map((f) => f.replace(/\\/g, '/')).sort();
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitFor(fn, ms) {
  const until = Date.now() + ms;
  for (;;) {
    if (fn()) return;
    if (Date.now() > until) throw new Error('timed out');
    await sleep(100);
  }
}

async function main() {
  assert.ok(fs.existsSync(realBin), 'run npm run dist first');
  assert.ok(fs.statSync(bin).mode & 0o111, 'the wrapper is executable');
  assert.match(fs.readFileSync(bin, 'utf8'), /^#!\/bin\/sh/, 'the wrapper is a shell script');

  assert.match(fs.readFileSync(bin, 'utf8'), /NULLBROWSER_REAL_HOME/, 'the wrapper hands the real home folder to the app');

  const got = fuses();
  for (const [k, v] of Object.entries(EXPECT_FUSES)) assert.equal(got[k], v, `fuse ${k}`);

  const files = asarFiles().filter((f) => !f.endsWith('/') && f !== '/');
  const allowed = /^\/(package\.json|src|ui|src\/[a-z]+\.js|ui\/(app\.js|index\.html|style\.css|icon\.png|fonts|fonts\/readex-pro-(400|700)\.woff2))$/;
  for (const f of files) assert.match(f, allowed, `unexpected file in the app archive: ${f}`);
  assert.ok(files.includes('/src/main.js') && files.includes('/ui/index.html'));
  assert.equal(files.some((f) => f.includes('node_modules') || f.includes('/test/')), false);

  assert.deepEqual(fs.readdirSync(path.join(unpacked, 'locales')), ['en-US.pak']);
  assert.equal(fs.existsSync(path.join(unpacked, 'resources', 'app-update.yml')), false);

  for (const flag of ['--remote-debugging-port=9433', '--inspect=9434', '--js-flags=--expose-gc']) {
    const r = spawnSync(bin, ['--no-sandbox', flag], { encoding: 'utf8', timeout: 20000, killSignal: 'SIGKILL' });
    assert.equal(r.status, 2, `${flag} should be refused, got ${r.status}`);
    assert.match(r.stderr, /Refused/);
  }
  const viaEnv = spawnSync(bin, ['--no-sandbox'], { env: { ...process.env, NODE_OPTIONS: '--inspect=9435', ELECTRON_RUN_AS_NODE: '1' }, input: 'console.log(1)', encoding: 'utf8', timeout: 8000, killSignal: 'SIGKILL' });
  assert.notEqual((viaEnv.stdout || '').trim(), '1', 'ELECTRON_RUN_AS_NODE must not run a script');

  const realHome = fs.mkdtempSync(path.join(os.tmpdir(), 'nb-pkg-home-'));
  const env = { ...process.env, HOME: realHome, XDG_CONFIG_HOME: path.join(realHome, '.config'), XDG_CACHE_HOME: path.join(realHome, '.cache') };
  const child = spawn(bin, ['--no-sandbox'], { env, stdio: ['ignore', 'ignore', 'pipe'] });
  let err = '';
  child.stderr.on('data', (d) => {
    err += d.toString();
  });
  await waitFor(() => err.includes('shell-ready') || child.exitCode !== null, 20000);
  assert.ok(err.includes('shell-ready'), `the packaged window did not load its page:\n${err.slice(-600)}`);
  assert.equal(/Failed to load/.test(err), false, `the packaged app reported a load failure:\n${err.slice(-600)}`);
  await sleep(4000);
  assert.equal(child.exitCode, null, 'the packaged app should still be running');
  assert.deepEqual(fs.readdirSync(realHome), [], 'the real home folder is untouched from the very first start, before the warm-up a dev run needs');
  const shm = fs.readdirSync('/dev/shm').filter((n) => n.startsWith('null-browser-'));
  assert.equal(shm.length, 1, 'the wrapper created exactly one RAM folder');
  const ss = spawnSync('ss', ['-H', '-tunap'], { encoding: 'utf8' });
  const mine = (ss.stdout || '').split('\n').filter((l) => /nullbrowser|chrome_crashpad/.test(l));
  const outside = mine.filter((l) => {
    const cols = l.trim().split(/\s+/);
    const peer = cols[5] || '';
    return peer && !/^(127\.|\[::1\]|\*|0\.0\.0\.0|\[::\]|::)/.test(peer);
  });
  assert.deepEqual(outside, [], 'the idle app must not talk to any other host');
  assert.equal(mine.some((l) => /LISTEN/.test(l)), false, 'the app must not listen on any port');
  child.kill('SIGTERM');
  await waitFor(() => fs.readdirSync('/dev/shm').filter((n) => n.startsWith('null-browser-')).length === 0, 10000);
  assert.deepEqual(fs.readdirSync(realHome), [], 'nothing was left in the real home folder after quitting either');
  console.log('package ok');
}

main().then(() => process.exit(0), (e) => {
  console.error(e);
  process.exit(1);
});
