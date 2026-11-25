const { _electron } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const https = require('node:https');
const { execFileSync } = require('node:child_process');

const root = path.join(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'nb-smoke-'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, what, ms = 15000) {
  const until = Date.now() + ms;
  for (;;) {
    let ok = false;
    try {
      ok = await fn();
    } catch {
      ok = false;
    }
    if (ok) return;
    if (Date.now() > until) throw new Error(`timed out waiting for ${what}`);
    await sleep(100);
  }
}

function noProxy(env) {
  const out = {};
  for (const [k, v] of Object.entries(env)) if (!/^(https?|all|no)_proxy$/i.test(k)) out[k] = v;
  out.NO_PROXY = '*';
  out.no_proxy = '*';
  return out;
}

function listen(server) {
  return new Promise((r) => server.listen(0, '127.0.0.1', () => r(server.address().port)));
}

function walk(dir) {
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    out.push(p);
    if (fs.statSync(p).isDirectory()) out.push(...walk(p));
  }
  return out;
}

async function main() {
  const seenB = [];
  const seenA = [];
  let portB = 0;
  const a = http.createServer((q, s) => {
    seenA.push({ url: q.url, cookie: q.headers.cookie || '' });
    if (q.url === '/file') {
      s.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Content-Disposition': 'attachment; filename="thing.bin"' });
      return s.end('secret bytes');
    }
    if (q.url === '/two') {
      s.writeHead(200, { 'Content-Type': 'text/html' });
      return s.end('<!doctype html><title>page two</title><p>two</p>');
    }
    s.writeHead(200, { 'Content-Type': 'text/html', 'Set-Cookie': 'fp=1; Path=/' });
    return s.end(`<!doctype html><title>page one</title><p>one</p>
<img src="http://localhost:${portB}/pixel.gif?n=${Date.now()}" width="1" height="1">
<a id="newtab" href="/two" target="_blank" style="display:block;position:absolute;left:20px;top:80px;width:200px;height:40px;background:#333;color:#fff">open in new tab</a>`);
  });
  const b = http.createServer((q, s) => {
    seenB.push({ url: q.url, cookie: q.headers.cookie || '' });
    s.writeHead(200, { 'Content-Type': 'image/gif', 'Set-Cookie': 'tp=1; Path=/; SameSite=None' });
    s.end(Buffer.from('R0lGODlhAQABAAAAACw=', 'base64'));
  });
  const plain = http.createServer((q, s) => {
    s.writeHead(200, { 'Content-Type': 'text/html' });
    s.end('<!doctype html><title>plain only</title><p>plain</p>');
  });
  const key = path.join(tmp, 'k.pem');
  const crt = path.join(tmp, 'c.pem');
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', crt, '-days', '2', '-subj', '/CN=stub', '-addext', 'subjectAltName=IP:127.0.0.1,DNS:pub.test'], { stdio: 'ignore' });
  const tls = https.createServer({ key: fs.readFileSync(key), cert: fs.readFileSync(crt) }, (q, s) => {
    s.writeHead(200, { 'Content-Type': 'text/html' });
    s.end('<!doctype html><title>tls page</title><p>tls</p>');
  });
  const portA = await listen(a);
  portB = await listen(b);
  const portPlain = await listen(plain);
  const portTls = await listen(tls);

  const ramBase = path.join(tmp, 'ram');
  const realHome = path.join(tmp, 'home');
  fs.mkdirSync(ramBase);
  fs.mkdirSync(realHome);
  const app = await _electron.launch({
    executablePath: require('electron'),
    args: [root, '--no-sandbox', '--host-resolver-rules=MAP pub.test 127.0.0.1'],
    env: { ...noProxy(process.env), NULLBROWSER_RAM_BASE: ramBase, HOME: realHome, XDG_CONFIG_HOME: path.join(realHome, '.config'), XDG_CACHE_HOME: path.join(realHome, '.cache') },
  });
  await waitFor(() => app.windows().some((w) => w.url().endsWith('/ui/index.html')), 'the toolbar window');
  const win = app.windows().find((w) => w.url().endsWith('/ui/index.html'));
  await win.waitForLoadState('domcontentloaded');
  const pageEval = (code, gesture = false) => app.evaluate(({ BrowserWindow }, [c, g]) => BrowserWindow.getAllWindows()[0].contentView.children[0].webContents.executeJavaScript(c, g), [code, gesture]);
  const pageUrl = () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].contentView.children[0].webContents.getURL());
  const go = async (text) => {
    await win.fill('#addr', text);
    await win.press('#addr', 'Enter');
  };

  await win.waitForSelector('#blank:not([hidden])');
  assert.equal(await win.inputValue('#addr'), '');
  await win.evaluate(() => document.fonts.ready);
  assert.equal(await win.evaluate(() => document.fonts.check('16px "Readex Pro"')), true, 'the shared Readex Pro font is loaded from the app');
  assert.match(await win.evaluate(() => getComputedStyle(document.body).fontFamily), /Readex Pro/);
  const inside = await app.evaluate(({ app: a2 }) => ({ home: process.env.HOME, user: a2.getPath('userData'), jit: a2.commandLine.getSwitchValue('js-flags') }));
  assert.equal(inside.jit, '--jitless', 'JIT is off');
  assert.ok(inside.home.startsWith(ramBase) && inside.user.startsWith(ramBase), 'home and the Chromium profile are in the RAM folder');
  const ramDirs = fs.readdirSync(ramBase).filter((n) => n.startsWith('null-browser-'));
  assert.equal(ramDirs.length, 1);

  await go(`127.0.0.1:${portA}/`.replace(/^/, 'http://'));
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/`, 'the first page');
  await waitFor(() => seenB.length >= 1, 'the third-party pixel');
  await win.waitForSelector('#sec.bad');
  assert.equal(await win.textContent('#sec'), 'Not secure');

  await go(`http://127.0.0.1:${portA}/`);
  await waitFor(() => seenA.filter((r) => r.url === '/').length >= 2 && seenB.length >= 2, 'the second visit');
  assert.match(seenA.filter((r) => r.url === '/')[1].cookie, /fp=1/, 'first-party cookies work');
  assert.equal(seenB[1].cookie, '', 'third-party cookies are accepted and never sent back');

  const perms = await pageEval(`(async () => {
    const n = await Notification.requestPermission();
    let cam = 'allowed';
    try { await navigator.mediaDevices.getUserMedia({ video: true, audio: true }); } catch (e) { cam = 'refused'; }
    let geo = await new Promise((r) => navigator.geolocation.getCurrentPosition(() => r('allowed'), () => r('refused'), { timeout: 3000 }));
    return { n, cam, geo };
  })()`, true);
  assert.deepEqual(perms, { n: 'denied', cam: 'refused', geo: 'refused' });

  assert.equal(await pageEval(`window.open('http://127.0.0.1:${portA}/two') === null`), true, 'a script pop-up gets nothing');
  await sleep(500);
  assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 1);
  assert.equal(await pageUrl(), `http://127.0.0.1:${portA}/`);

  await app.evaluate(({ BrowserWindow }) => {
    const wc = BrowserWindow.getAllWindows()[0].contentView.children[0].webContents;
    wc.focus();
    wc.sendInputEvent({ type: 'mouseDown', x: 60, y: 100, button: 'left', clickCount: 1 });
    wc.sendInputEvent({ type: 'mouseUp', x: 60, y: 100, button: 'left', clickCount: 1 });
  });
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/two`, 'a clicked new-tab link opens in the same page');
  assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 1);

  await go(`http://127.0.0.1:${portA}/file`);
  await win.waitForFunction(() => /Downloads are off/.test(document.getElementById('notice').textContent));

  await go(`http://pub.test:${portTls}/`);
  await win.waitForSelector('#msg:not([hidden])');
  assert.match(await win.textContent('#msg-title'), /certificate is not valid/);
  assert.equal(await win.locator('#msg-main').isHidden(), true, 'a public site with a bad certificate cannot be trusted');
  assert.equal(await win.inputValue('#addr'), `https://pub.test:${portTls}/`, 'http was upgraded to https first');

  await go(`http://pub.test:${portPlain}/`);
  await win.waitForFunction(() => /no secure version/.test(document.getElementById('msg-title').textContent));
  await win.click('#msg-main');
  await waitFor(async () => (await pageUrl()) === `http://pub.test:${portPlain}/`, 'open anyway loads the plain page');
  await win.waitForSelector('#sec.bad');

  await go(`https://127.0.0.1:${portTls}/`);
  await win.waitForFunction(() => /certificate is not valid/.test(document.getElementById('msg-title').textContent));
  assert.match(await win.textContent('#msg-mono'), /SHA-256 ([0-9A-F]{2}:){31}[0-9A-F]{2}/);
  await win.click('#msg-main');
  await waitFor(async () => (await pageUrl()) === `https://127.0.0.1:${portTls}/`, 'a device on your own network can be trusted for the session');
  await win.waitForSelector('#sec.ok');

  await win.click('#home');
  await win.waitForSelector('#blank:not([hidden])');

  const ramDir = path.join(ramBase, ramDirs[0]);
  assert.ok(fs.existsSync(ramDir));
  await app.close();
  try {
    await waitFor(() => !fs.existsSync(ramDir), 'the RAM folder is removed on quit');
  } catch (e) {
    console.error('LEFT:', fs.existsSync(ramDir) ? walk(ramDir).map((p) => p.slice(ramDir.length)).join(' ') : 'gone');
    throw e;
  }
  assert.deepEqual(fs.readdirSync(ramBase), [], 'nothing is left in the RAM base');
  assert.deepEqual(walk(realHome).map((p) => p.slice(realHome.length)), [], 'nothing was written to the real home folder');

  for (const sv of [a, b, plain, tls]) sv.close();
  console.log('smoke ok');
}

main().then(() => process.exit(0), (e) => {
  console.error(e);
  process.exit(1);
});
