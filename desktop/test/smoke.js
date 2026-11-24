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
  return new Promise((resolve) => server.listen(0, '0.0.0.0', () => resolve(server.address().port)));
}

function pageServer(name, extra = '') {
  const hits = [];
  const handler = (req, res) => {
    hits.push(req.url);
    res.setHeader('content-type', 'text/html');
    res.end(`<!doctype html><title>${name}</title><body><h1>${name}</h1><a id="out" target="_blank" href="https://example.invalid/">out</a>${extra}</body>`);
  };
  return { hits, handler };
}

function probeScript(extPort) {
  return `<img src="http://localhost:${extPort}/pixel"><script>
(async () => {
  const out = {};
  try { await new Promise((ok, no) => navigator.geolocation.getCurrentPosition(ok, no)); out.geo = 'ok'; } catch (e) { out.geo = e.code === 1 ? 'denied' : 'other'; }
  for (const n of ['microphone', 'camera', 'notifications', 'midi', 'clipboard-read']) {
    try { out[n] = (await navigator.permissions.query({ name: n })).state; } catch (e) { out[n] = 'error'; }
  }
  try { await navigator.mediaDevices.getUserMedia({ audio: true }); out.audio = 'ok'; } catch (e) { out.audio = e.name; }
  try { await fetch('http://localhost:${extPort}/fetch', { mode: 'no-cors' }); out.ext = 'reached'; } catch (e) { out.ext = 'blocked'; }
  try { out.sock = await new Promise((ok) => { const w = new WebSocket('ws://localhost:${extPort}/ws'); w.onopen = () => ok('open'); w.onerror = () => ok('blocked'); }); } catch (e) { out.sock = 'blocked'; }
  document.title = JSON.stringify(out);
})();
</script>`;
}

async function views(app) {
  return app.evaluate(({ BrowserWindow }) => {
    const w = BrowserWindow.getAllWindows()[0];
    return w.contentView.children.map((v) => ({ url: v.webContents.getURL(), bounds: v.getBounds(), visible: v.getVisible() }));
  });
}

async function chord(app, keyCode) {
  await app.evaluate(({ BrowserWindow }, k) => {
    const wc = BrowserWindow.getAllWindows()[0].webContents;
    wc.focus();
    wc.sendInputEvent({ type: 'keyDown', keyCode: k, modifiers: ['control'] });
    wc.sendInputEvent({ type: 'keyUp', keyCode: k, modifiers: ['control'] });
  }, keyCode);
}

async function inPage(app, part, code) {
  return app.evaluate(({ BrowserWindow }, arg) => {
    const v = BrowserWindow.getAllWindows()[0].contentView.children.find((c) => c.webContents.getURL().includes(arg.part));
    return v.webContents.executeJavaScript(arg.code, true);
  }, { part, code });
}

async function contentSize(app) {
  return app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getContentSize());
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
  const ext = pageServer('outside');
  const extSrv = http.createServer(ext.handler);
  const extPort = await listen(extSrv);
  const ctl = pageServer('stub controller', probeScript(extPort));
  const tlk = pageServer('stub talker');
  const lh = pageServer('stub last heard', `<script>(async () => { let r; try { await fetch('http://localhost:${extPort}/lh', { mode: 'no-cors' }); r = 'reached'; } catch (e) { r = 'blocked'; } document.title = r; })();</script>`);
  const ctlSrv = http.createServer(ctl.handler);
  const tlkSrv = http.createServer(tlk.handler);
  const lhSrv = http.createServer(lh.handler);
  const ctlPort = await listen(ctlSrv);
  const tlkPort = await listen(tlkSrv);
  const lhPort = await listen(lhSrv);

  const key = path.join(tmp, 'k.pem');
  const crt = path.join(tmp, 'c.pem');
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', crt, '-days', '2', '-subj', '/CN=stub', '-addext', 'subjectAltName=IP:127.0.0.1'], { stdio: 'ignore' });
  const tls = pageServer('stub tls talker');
  const tlsSrv = https.createServer({ key: fs.readFileSync(key), cert: fs.readFileSync(crt) }, tls.handler);
  const tlsPort = await listen(tlsSrv);

  const data = path.join(tmp, 'data');
  const launch = () => _electron.launch({
    executablePath: require('electron'),
    args: [root, '--no-sandbox'],
    env: { ...process.env, NODECONTROLLER_DATA: data },
  });
  let app = await launch();
  let win = await app.firstWindow();
  await win.waitForLoadState('domcontentloaded');

  assert.equal(await win.title(), 'Node Controller');
  assert.match(await win.textContent('.pane-msg'), /Add a node/);
  assert.equal(await win.locator('#modes button[data-mode="cols"]').isDisabled(), true);
  assert.equal(await win.locator('#modes button[data-mode="trio"]').isDisabled(), true);
  assert.deepEqual(await win.locator('#modes button').allTextContents(), ['1 page', '2 pages', '3 pages']);

  async function addNode(name, host, bad) {
    await win.click('#add');
    await win.fill('#f-name', name);
    await win.fill('#f-host', host);
    await win.fill('#f-port-controller', String(ctlPort));
    await win.fill('#f-port-talker', String(tlkPort));
    if (bad) {
      await win.fill('#f-lan', 'bad');
      await win.click('#f-save');
      assert.match(await win.textContent('#f-error'), /LAN/);
      await win.fill('#f-lan', '');
    }
    await win.click('#f-save');
    await win.waitForFunction((n) => [...document.querySelectorAll('.node-name')].some((e) => e.textContent === n), name);
  }

  await addNode('Stub', '127.0.0.1', true);

  const nodesFile = path.join(data, 'nodes.json');
  const saved = JSON.parse(fs.readFileSync(nodesFile, 'utf8'));
  assert.equal(saved.nodes.length, 1);
  assert.equal(saved.nodes[0].ports.talker, tlkPort);

  const page = (n, i) => win.locator('.node').nth(n).locator('.pages button').nth(i);
  assert.deepEqual(await page(0, 0).allTextContents(), ['Node Controller']);

  await page(0, 0).click();
  await waitFor(async () => (await views(app)).some((v) => v.url === `http://127.0.0.1:${ctlPort}/` && v.visible), 'controller page');
  assert.deepEqual(await win.locator('.tab .label').allTextContents(), ['Stub · Node Controller']);

  const probe = await waitFor(async () => {
    const t = await inPage(app, `127.0.0.1:${ctlPort}/`, 'document.title').catch(() => '');
    return String(t).startsWith('{') ? JSON.parse(t) : null;
  }, 'permission probe');
  assert.deepEqual(probe, { geo: 'denied', microphone: 'granted', camera: 'denied', notifications: 'denied', midi: 'denied', 'clipboard-read': 'denied', audio: 'NotFoundError', ext: 'blocked', sock: 'blocked' });
  assert.deepEqual(ext.hits, []);

  await page(0, 1).click();
  await waitFor(async () => (await views(app)).some((v) => v.url === `http://127.0.0.1:${tlkPort}/` && v.visible), 'talker page');
  let vs = await views(app);
  assert.equal(vs.length, 2);
  assert.deepEqual(vs.map((v) => v.visible), [false, true]);
  assert.equal(await win.locator('#modes button[data-mode="cols"]').isDisabled(), false);
  assert.equal(await win.locator('#modes button[data-mode="trio"]').isDisabled(), true);

  let [W, H] = await contentSize(app);
  const sidebar = Math.round((W * 3) / 15);
  const header = Math.round(W / 15);
  const one = vs.find((v) => v.visible).bounds;
  assert.deepEqual(one, { x: sidebar, y: header, width: W - sidebar, height: H - header });
  assert.equal(await win.locator('#head').evaluate((e) => Math.round(e.getBoundingClientRect().height)), header);
  assert.equal(await win.locator('#side').evaluate((e) => Math.round(e.getBoundingClientRect().width)), sidebar);

  await win.click('#modes button[data-mode="cols"]');
  await waitFor(async () => (await views(app)).filter((v) => v.visible).length === 2, 'two visible views');
  vs = await views(app);
  const [pa, pb] = [...vs].sort((x, y) => x.bounds.x - y.bounds.x);
  assert.equal(pa.bounds.x, sidebar);
  assert.equal(pa.bounds.y, header);
  assert.equal(pa.bounds.x + pa.bounds.width + 6, pb.bounds.x);
  assert.equal(pb.bounds.x + pb.bounds.width, W);
  assert.equal(pa.bounds.width, Math.floor(((W - sidebar - 6) * 1) / 2));
  assert.equal(pa.bounds.height, H - header);
  assert.equal(await win.locator('.tab.shown').count(), 2);
  assert.equal(await win.locator('.tab.focus').count(), 1);

  const focusLabel = () => win.locator('.tab.focus .label').textContent();
  const before = await focusLabel();
  const other = before.includes('Controller') ? `:${tlkPort}/` : `:${ctlPort}/`;
  await app.evaluate(({ BrowserWindow }, part) => {
    const v = BrowserWindow.getAllWindows()[0].contentView.children.find((c) => c.webContents.getURL().includes(part));
    v.webContents.focus();
  }, other);
  await waitFor(async () => (await focusLabel()) !== before, 'focus moves with the page');

  const left = async () => [...(await views(app))].filter((v) => v.visible).sort((x, y) => x.bounds.x - y.bounds.x)[0];
  const div = await win.locator('.divider.cols').boundingBox();
  await win.mouse.move(div.x + 3, div.y + 200);
  await win.mouse.down();
  await win.mouse.move(div.x + 103, div.y + 200, { steps: 6 });
  await win.mouse.up();
  await waitFor(async () => (await left()).bounds.width > pa.bounds.width + 80, 'divider drag');
  await win.dblclick('.divider.cols');
  await waitFor(async () => Math.abs((await left()).bounds.width - pa.bounds.width) <= 1, 'divider reset');

  await chord(app, '3');
  await new Promise((r) => setTimeout(r, 400));
  assert.equal(await win.locator('#modes button.on').getAttribute('data-mode'), 'cols');

  await addNode('Stub2', '127.0.0.3', false);
  await page(1, 0).click();
  await waitFor(async () => (await views(app)).length === 3, 'third page');
  assert.equal(await win.locator('.tab').count(), 3);
  assert.equal(await win.locator('#modes button[data-mode="trio"]').isDisabled(), false);

  await chord(app, '3');
  await waitFor(async () => (await views(app)).filter((v) => v.visible).length === 3, 'three visible views');
  vs = (await views(app)).filter((v) => v.visible);
  const top = vs.filter((v) => v.bounds.y === header).sort((x, y) => x.bounds.x - y.bounds.x);
  const bottom = vs.find((v) => v.bounds.y !== header);
  assert.equal(top.length, 2);
  assert.equal(top[0].bounds.height, top[1].bounds.height);
  assert.equal(top[0].bounds.x + top[0].bounds.width + 6, top[1].bounds.x);
  assert.equal(top[0].bounds.width, Math.floor((W - sidebar - 6) / 2));
  assert.deepEqual([bottom.bounds.x, bottom.bounds.width], [sidebar, W - sidebar]);
  assert.equal(bottom.bounds.y, header + top[0].bounds.height + 6);
  assert.ok(Math.abs(bottom.bounds.height - top[0].bounds.height) <= 1);
  assert.equal(bottom.bounds.y + bottom.bounds.height, H);
  assert.equal(await win.locator('.divider.gapline').count(), 1);
  assert.equal(await win.locator('.divider.cols').count(), 1);

  await inPage(app, `127.0.0.1:${tlkPort}/`, `window.open('http://10.9.9.9/x', 'nt_lh') && 1`);
  await win.waitForFunction(() => /refused/.test(document.getElementById('notice').textContent));
  assert.equal(await win.locator('.tab').count(), 3);

  await inPage(app, `127.0.0.1:${tlkPort}/`, `window.open('http://127.0.0.1:${lhPort}/lh', 'nt_lh') && 1`);
  await waitFor(async () => (await views(app)).some((v) => v.url === `http://127.0.0.1:${lhPort}/lh`), 'Last Heard page');
  assert.equal(await win.locator('.tab').count(), 4);
  assert.ok((await win.locator('.tab .label').allTextContents()).includes('Last Heard'));
  const lhView = () => views(app).then((all) => all.find((v) => v.url.includes(`:${lhPort}/`)));
  await waitFor(async () => (await lhView()).visible, 'Last Heard visible');
  assert.deepEqual([(await lhView()).bounds.x, (await lhView()).bounds.width], [sidebar, W - sidebar]);
  assert.equal(await win.locator('#modes button.on').getAttribute('data-mode'), 'trio');
  const lhTitle = await waitFor(async () => {
    const t = await inPage(app, `:${lhPort}/`, 'document.title').catch(() => '');
    return t === 'blocked' || t === 'reached' ? t : '';
  }, 'Last Heard request check');
  assert.equal(lhTitle, 'blocked');
  assert.deepEqual(ext.hits, []);

  await app.evaluate(({ BrowserWindow }) => {
    const v = BrowserWindow.getAllWindows()[0].contentView.children.find((c) => c.webContents.getURL().includes('/lh'));
    v.webContents.focus();
  });
  await waitFor(async () => (await win.locator('.tab.focus .label').textContent()) === 'Last Heard', 'Last Heard focused');

  await app.close();
  app = await launch();
  win = await app.firstWindow();
  await win.waitForLoadState('domcontentloaded');
  await waitFor(async () => (await views(app)).filter((v) => v.visible).length === 3, 'restored three pages');
  assert.equal(await win.locator('#modes button.on').getAttribute('data-mode'), 'trio');
  assert.equal(await win.locator('.tab').count(), 3);
  assert.equal((await win.locator('.tab .label').allTextContents()).includes('Last Heard'), false);

  await win.locator('.tab .x').nth(0).click();
  await waitFor(async () => (await views(app)).length === 2, 'two views after close');
  assert.equal(await win.locator('#modes button.on').getAttribute('data-mode'), 'cols');
  await win.locator('.tab .x').nth(0).click();
  await waitFor(async () => (await views(app)).length === 1, 'one view after close');
  assert.equal(await win.locator('#modes button.on').getAttribute('data-mode'), 'single');
  assert.equal((await views(app))[0].visible, true);
  await chord(app, 'w');
  await waitFor(async () => (await views(app)).length === 0, 'no views after Ctrl+W');
  assert.match(await win.textContent('.pane-msg'), /Add a node/);

  await win.locator('.node').nth(1).locator('.node-top button').click();
  await win.click('#f-delete');
  await win.waitForFunction(() => document.querySelectorAll('.node').length === 1);

  await win.click('.node-top button');
  await win.fill('#f-host', 'https://127.0.0.1');
  await win.fill('#f-port-talker', String(tlsPort));
  await win.click('#f-save');
  await win.waitForSelector('.node-host:has-text("https://127.0.0.1")');

  await page(0, 1).click();
  await win.waitForSelector('.pane-msg h2');
  assert.match(await win.textContent('.pane-msg h2'), /Could not open Stub · Node Talker/);
  assert.match(await win.textContent('.pane-msg .mono'), /SHA-256 ([0-9A-F]{2}:){31}[0-9A-F]{2}/);
  assert.equal(tls.hits.length, 0);
  assert.equal(await win.locator('.tab .dot.failed').count(), 1);

  await win.click('text=Trust this certificate');
  await waitFor(() => tls.hits.includes('/'), 'request to the pinned https node');
  await waitFor(async () => (await win.locator('.pane-msg').count()) === 0, 'failure panel gone');
  const pinned = JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].pin;
  assert.match(pinned, /^[0-9a-f]{64}$/);

  await win.click('.node-top button');
  await win.click('#f-delete');
  await win.waitForFunction(() => document.querySelectorAll('.node').length === 0);
  assert.equal(JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes.length, 0);
  assert.equal(await win.locator('.tab').count(), 0);
  assert.equal((await views(app)).length, 0);

  await app.close();
  for (const sv of [ctlSrv, tlkSrv, tlsSrv, extSrv, lhSrv]) sv.close();
  console.log('smoke ok');
}

main().then(() => process.exit(0), (e) => {
  console.error(e);
  process.exit(1);
});
