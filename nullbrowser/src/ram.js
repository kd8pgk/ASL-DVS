const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');

const PREFIX = 'null-browser-';

function ramBase(override) {
  if (override) return { dir: override, ram: true };
  try {
    const st = fs.statSync('/dev/shm');
    if (st.isDirectory()) {
      fs.accessSync('/dev/shm', fs.constants.W_OK);
      return { dir: '/dev/shm', ram: true };
    }
  } catch {
    return { dir: os.tmpdir(), ram: false };
  }
  return { dir: os.tmpdir(), ram: false };
}

function alive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return Boolean(err && err.code === 'EPERM');
  }
}

function ownerTag() {
  return typeof process.getuid === 'function' ? String(process.getuid()) : 'u';
}

function rammaidSweep(base) {
  const tag = `${PREFIX}${ownerTag()}-`;
  let removed = 0;
  let names = [];
  try {
    names = fs.readdirSync(base);
  } catch {
    return 0;
  }
  for (const name of names) {
    if (!name.startsWith(tag)) continue;
    const dir = path.join(base, name);
    let pid = 0;
    try {
      pid = Number(fs.readFileSync(path.join(dir, 'pid'), 'utf8').trim());
    } catch {
      pid = 0;
    }
    if (pid && alive(pid)) continue;
    try {
      fs.rmSync(dir, { recursive: true, force: true });
      removed += 1;
    } catch {
      continue;
    }
  }
  return removed;
}

function createRamDir(base, pid = process.pid) {
  const dir = path.join(base, `${PREFIX}${ownerTag()}-${pid}-${crypto.randomBytes(6).toString('hex')}`);
  fs.mkdirSync(dir, { mode: 0o700 });
  fs.chmodSync(dir, 0o700);
  fs.writeFileSync(path.join(dir, 'pid'), String(pid), { mode: 0o600 });
  const sub = {};
  for (const name of ['home', 'config', 'cache', 'data', 'state', 'chromium', 'session', 'temp', 'files']) {
    sub[name] = path.join(dir, name);
    fs.mkdirSync(sub[name], { mode: 0o700 });
  }
  return { dir, sub };
}

function adoptRamDir(dir) {
  const sub = {};
  for (const name of ['home', 'config', 'cache', 'data', 'state', 'chromium', 'session', 'temp', 'files']) {
    sub[name] = path.join(dir, name);
    fs.mkdirSync(sub[name], { recursive: true, mode: 0o700 });
  }
  return { dir, sub };
}

function prelaunchDir(value) {
  if (!value || !path.isAbsolute(value) || !path.basename(value).startsWith(PREFIX)) return '';
  try {
    if (!fs.statSync(value).isDirectory()) return '';
  } catch {
    return '';
  }
  return value;
}

function realHome(env, fallback) {
  const v = env && env.NULLBROWSER_REAL_HOME;
  if (!v || !path.isAbsolute(v) || path.basename(v).startsWith(PREFIX)) return fallback;
  try {
    if (!fs.statSync(v).isDirectory()) return fallback;
  } catch {
    return fallback;
  }
  return v;
}

function relaunchEnv(env, ramDir, home) {
  const out = { NULLBROWSER_PRELAUNCH_DIR: null, NULLBROWSER_REAL_HOME: home, HOME: home };
  for (const key of ['XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'TMPDIR']) {
    const v = env && env[key];
    if (v && ramDir && (v === ramDir || v.startsWith(`${ramDir}${path.sep}`))) out[key] = null;
  }
  return out;
}

function rammaidRemove(dir) {
  if (!dir || !path.basename(dir).startsWith(PREFIX)) return false;
  try {
    fs.rmSync(dir, { recursive: true, force: true });
    return !fs.existsSync(dir);
  } catch {
    return false;
  }
}

function rammaidAfterExit(dir, pid = process.pid, run = spawn) {
  if (!dir || !path.basename(dir).startsWith(PREFIX) || !path.isAbsolute(dir)) return false;
  try {
    const child = run('/bin/sh', ['-c', 'while kill -0 "$1" 2>/dev/null; do sleep 0.2; done; rm -rf -- "$2"', 'null-browser-clean', String(pid), dir], { detached: true, stdio: 'ignore' });
    child.unref();
    return true;
  } catch {
    return false;
  }
}

module.exports = { PREFIX, ramBase, rammaidSweep, createRamDir, adoptRamDir, prelaunchDir, realHome, relaunchEnv, rammaidRemove, rammaidAfterExit, alive };
