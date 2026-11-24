const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync, spawn, spawnSync } = require('node:child_process');

const root = path.join(__dirname, '..');
const unpacked = process.env.NC_UNPACKED || path.join(root, 'dist', 'linux-unpacked');
const bin = path.join(unpacked, 'nodecontroller');

const EXPECT_FUSES = {
  RunAsNode: 'Disabled',
  EnableCookieEncryption: 'Enabled',
  EnableNodeOptionsEnvironmentVariable: 'Disabled',
  EnableNodeCliInspectArguments: 'Disabled',
  EnableEmbeddedAsarIntegrityValidation: 'Enabled',
  OnlyLoadAppFromAsar: 'Enabled',
  LoadBrowserProcessSpecificV8Snapshot: 'Disabled',
  GrantFileProtocolExtraPrivileges: 'Enabled',
};

function fuses() {
  const out = execFileSync(path.join(root, 'node_modules', '.bin', 'electron-fuses'), ['read', '--app', bin], { encoding: 'utf8' });
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

async function main() {
  assert.ok(fs.existsSync(bin), 'run npm run dist first');

  const got = fuses();
  for (const [k, v] of Object.entries(EXPECT_FUSES)) assert.equal(got[k], v, `fuse ${k}`);

  const files = asarFiles().filter((f) => !f.endsWith('/') && f !== '/');
  const allowed = /^\/(package\.json|src|ui|src\/[a-z]+\.js|ui\/(app\.js|index\.html|style\.css))$/;
  for (const f of files) assert.match(f, allowed, `unexpected file in the app archive: ${f}`);
  assert.ok(files.includes('/src/main.js') && files.includes('/ui/index.html'));
  assert.equal(files.some((f) => f.includes('node_modules') || f.includes('/test/')), false);

  assert.deepEqual(fs.readdirSync(path.join(unpacked, 'locales')), ['en-US.pak']);
  assert.equal(fs.existsSync(path.join(unpacked, 'resources', 'app-update.yml')), false);

  const env = { ...process.env, NODECONTROLLER_DATA: fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'ncd-pkg-')) };
  for (const flag of ['--remote-debugging-port=9333', '--inspect=9334', '--js-flags=--expose-gc']) {
    const r = spawnSync(bin, ['--no-sandbox', flag], { env, encoding: 'utf8', timeout: 20000 });
    assert.equal(r.status, 2, `${flag} should be refused, got ${r.status}`);
    assert.match(r.stderr, /Refused/);
  }
  const viaEnv = spawnSync(bin, ['--no-sandbox'], { env: { ...env, NODE_OPTIONS: '--inspect=9335', ELECTRON_RUN_AS_NODE: '1' }, input: 'console.log(1)', encoding: 'utf8', timeout: 8000 });
  assert.notEqual((viaEnv.stdout || '').trim(), '1', 'ELECTRON_RUN_AS_NODE must not run a script');

  const child = spawn(bin, ['--no-sandbox'], { env, stdio: ['ignore', 'ignore', 'pipe'] });
  let err = '';
  child.stderr.on('data', (d) => {
    err += d.toString();
  });
  const until = Date.now() + 20000;
  while (!err.includes('shell-ready') && child.exitCode === null && Date.now() < until) await sleep(200);
  assert.ok(err.includes('shell-ready'), `the packaged window did not load its page:\n${err.slice(-600)}`);
  assert.equal(/Failed to load/.test(err), false, `the packaged app reported a load failure:\n${err.slice(-600)}`);
  await sleep(4000);
  assert.equal(child.exitCode, null, 'the packaged app should still be running');
  const ss = spawnSync('ss', ['-H', '-tunap'], { encoding: 'utf8' });
  const mine = (ss.stdout || '').split('\n').filter((l) => /nodecontroller|chrome_crashpad/.test(l));
  const outside = mine.filter((l) => {
    const cols = l.trim().split(/\s+/);
    const peer = cols[5] || '';
    return peer && !/^(127\.|\[::1\]|\*|0\.0\.0\.0|\[::\]|::)/.test(peer);
  });
  assert.deepEqual(outside, [], 'the idle app must not talk to any other host');
  assert.equal(mine.some((l) => /LISTEN/.test(l)), false, 'the app must not listen on any port');
  child.kill('SIGTERM');
  console.log('package ok');
}

main().then(() => process.exit(0), (e) => {
  console.error(e);
  process.exit(1);
});
