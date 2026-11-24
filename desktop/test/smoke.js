const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { _electron } = require('playwright');

const root = path.join(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ncd-smoke-'));

function listen(server) {
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
}

function pageServer(name) {
  const hits = [];
  const handler = (req, res) => {
    hits.push(req.url);
    res.setHeader('content-type', 'text/html');
    res.end(`<!doctype html><title>${name}</title><body><h1>${name}</h1><a id="out" target="_blank" href="https://example.invalid/">out</a></body>`);
  };
  return { hits, handler };
}

async function urls(app) {
  return app.evaluate(({ webContents }) => webContents.getAllWebContents().map((w) => w.getURL()));
}

async function waitFor(fn, what, ms = 8000) {
  const end = Date.now() + ms;
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 100));
  }
}

async function main() {
  const ctl = pageServer('stub controller');
  const tlk = pageServer('stub talker');
  const ctlSrv = http.createServer(ctl.handler);
  const tlkSrv = http.createServer(tlk.handler);
  const ctlPort = await listen(ctlSrv);
  const tlkPort = await listen(tlkSrv);

  const key = path.join(tmp, 'k.pem');
  const crt = path.join(tmp, 'c.pem');
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', crt, '-days', '2', '-subj', '/CN=stub', '-addext', 'subjectAltName=IP:127.0.0.1'], { stdio: 'ignore' });
  const tls = pageServer('stub tls talker');
  const tlsSrv = https.createServer({ key: fs.readFileSync(key), cert: fs.readFileSync(crt) }, tls.handler);
  const tlsPort = await listen(tlsSrv);

  const app = await _electron.launch({
    executablePath: require('electron'),
    args: [root, '--no-sandbox'],
    env: { ...process.env, NODECONTROLLER_DATA: path.join(tmp, 'data') },
  });
  const win = await app.firstWindow();
  await win.waitForLoadState('domcontentloaded');

  assert.equal(await win.title(), 'Node Controller');
  assert.match(await win.textContent('#empty'), /Add a node/);

  await win.click('#add');
  await win.fill('#f-name', 'Stub');
  await win.fill('#f-host', '127.0.0.1');
  await win.fill('#f-port-controller', String(ctlPort));
  await win.fill('#f-port-talker', String(tlkPort));
  await win.fill('#f-lan', 'bad');
  await win.click('#f-save');
  assert.match(await win.textContent('#f-error'), /LAN/);
  await win.fill('#f-lan', '');
  await win.click('#f-save');
  await win.waitForSelector('.node');
  assert.equal(await win.textContent('.node-name'), 'Stub');

  const saved = JSON.parse(fs.readFileSync(path.join(tmp, 'data', 'nodes.json'), 'utf8'));
  assert.equal(saved.nodes.length, 1);
  assert.equal(saved.nodes[0].ports.talker, tlkPort);

  const buttons = win.locator('.pages button');
  assert.deepEqual(await buttons.allTextContents(), ['Node Controller', 'Node Talker']);

  await buttons.nth(0).click();
  await waitFor(async () => (await urls(app)).some((u) => u === `http://127.0.0.1:${ctlPort}/`), 'controller page');
  assert.match(await win.textContent('#title'), /Stub · Node Controller/);
  assert.ok(ctl.hits.includes('/'));

  await buttons.nth(1).click();
  await waitFor(async () => (await urls(app)).some((u) => u === `http://127.0.0.1:${tlkPort}/`), 'talker page');
  assert.match(await win.textContent('#title'), /Stub · Node Talker/);
  assert.equal((await urls(app)).filter((u) => u.includes(`:${ctlPort}/`)).length, 0);

  await win.click('#close');
  assert.match(await win.textContent('#title'), /Pick a page/);

  await win.click('.node-top button');
  await win.fill('#f-host', 'https://127.0.0.1');
  await win.fill('#f-port-talker', String(tlsPort));
  await win.click('#f-save');
  await win.waitForSelector('.node-host:has-text("https://127.0.0.1")');

  await win.locator('.pages button').nth(1).click();
  await win.waitForSelector('#fail:not([hidden])');
  assert.match(await win.textContent('#fail-cert'), /SHA-256 ([0-9A-F]{2}:){31}[0-9A-F]{2}/);
  assert.equal(tls.hits.length, 0);

  await win.click('#fail-trust');
  await waitFor(async () => (await urls(app)).some((u) => u === `https://127.0.0.1:${tlsPort}/`), 'pinned https page');
  await waitFor(() => tls.hits.includes('/'), 'request to the pinned https node');
  assert.equal(await win.locator('#fail').isHidden(), true);
  const pinned = JSON.parse(fs.readFileSync(path.join(tmp, 'data', 'nodes.json'), 'utf8')).nodes[0].pin;
  assert.match(pinned, /^[0-9a-f]{64}$/);

  await win.click('#close');
  await win.click('.node-top button');
  await win.click('#f-delete');
  await win.waitForFunction(() => document.querySelectorAll('.node').length === 0);
  assert.equal(JSON.parse(fs.readFileSync(path.join(tmp, 'data', 'nodes.json'), 'utf8')).nodes.length, 0);

  await app.close();
  for (const s of [ctlSrv, tlkSrv, tlsSrv]) s.close();
  console.log('smoke ok');
}

main().then(() => process.exit(0), (e) => {
  console.error(e);
  process.exit(1);
});
