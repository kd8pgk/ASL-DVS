const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { _electron } = require('playwright');
const L = require('../src/layout');

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
    return w.contentView.children.map((v) => ({
      url: v.webContents.getURL(),
      bounds: v.getBounds(),
      visible: v.getVisible(),
      throttled: v.webContents.backgroundThrottling,
      muted: v.webContents.isAudioMuted(),
    }));
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

async function dragToZone(win, source, zoneId) {
  const box = await source.boundingBox();
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await win.mouse.move(cx, cy);
  await win.mouse.down();
  await win.mouse.move(cx + 12, cy + 12, { steps: 4 });
  const zone = win.locator(`.zone[data-zone="${zoneId}"]`);
  await zone.waitFor({ timeout: 8000 });
  const zb = await zone.boundingBox();
  await win.mouse.move(zb.x + zb.width / 2, zb.y + zb.height / 2, { steps: 10 });
  await win.mouse.up();
  await win.waitForFunction(() => document.querySelectorAll('.zone').length === 0);
}

function expected(mode, W, H, ratio = 0.5) {
  const g = L.grid(W, H);
  const r = L.rects({ mode, ratio }, g.area);
  return { g, panes: r.panes.map((p) => L.viewRect({ mode }, p)), rects: r.panes };
}

function same(a, b, msg) {
  assert.deepEqual({ x: a.x, y: a.y, w: a.width, h: a.height }, { x: b.x, y: b.y, w: b.w, h: b.h }, msg);
}

async function main() {
  const ext = pageServer('outside');
  const extSrv = http.createServer(ext.handler);
  const extPort = await listen(extSrv);
  const ctl = pageServer('stub controller', probeScript(extPort));
  const tlk = pageServer('stub talker');
  const sys = pageServer('stub sysmon');
  const nm = pageServer('stub node monitor');
  const lh = pageServer('stub last heard', `<script>(async () => { let r; try { await fetch('http://localhost:${extPort}/lh', { mode: 'no-cors' }); r = 'reached'; } catch (e) { r = 'blocked'; } document.title = r; })();</script>`);
  const servers = [ctl, tlk, sys, nm, lh].map((x) => http.createServer(x.handler));
  const ports = [];
  for (const sv of servers) ports.push(await listen(sv));
  const [cp, tp, sp, np, lp] = ports;

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

  const url = (port, p = '/') => `http://127.0.0.1:${port}${p}`;
  const visible = async () => (await views(app)).filter((v) => v.visible);
  const mode = () => win.locator('#modes button.on').getAttribute('data-mode');
  const tabLabels = () => win.locator('.tab .label').allTextContents();
  const tab = (text) => win.locator('.tab', { hasText: text });
  const page = (n, i) => win.locator('.node').nth(n).locator('.pages button').nth(i);
  const size = async () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getContentSize());
  const showing = async (...urls) => {
    await waitFor(async () => {
      const v = await visible();
      return v.length === urls.length && urls.every((u) => v.some((x) => x.url === u));
    }, `showing ${urls.join(', ')}`);
  };

  assert.equal(await win.title(), 'Node Controller');
  assert.match(await win.textContent('.pane-msg'), /Add a node/);
  assert.equal(await win.locator('#modes button[data-mode="cols"]').isDisabled(), true);
  assert.equal(await win.locator('#modes button[data-mode="trio"]').isDisabled(), true);
  assert.deepEqual(await win.locator('#modes button').allTextContents(), ['1 page', '2 pages', '3 pages']);
  assert.equal(await win.locator('#back').isHidden(), true);
  assert.equal(await win.locator('#save-split').isDisabled(), true);

  async function addNode(name, host, bad) {
    await win.click('#add');
    await win.fill('#f-name', name);
    await win.fill('#f-host', host);
    await win.fill('#f-port-controller', String(cp));
    await win.fill('#f-port-talker', String(tp));
    await win.fill('#f-port-sysmon', String(sp));
    await win.fill('#f-port-nodemon', String(np));
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
  assert.deepEqual([saved.nodes[0].ports.talker, saved.nodes[0].ports.sysmon, saved.nodes[0].ports.nodemon], [tp, sp, np]);
  assert.deepEqual(await win.locator('.node').nth(0).locator('.pages button').allTextContents(), ['Node Controller', 'Node Talker', 'SysMon', 'Node Monitor']);

  await page(0, 0).click();
  await showing(url(cp));
  assert.deepEqual(await tabLabels(), ['Stub · Node Controller']);
  const probe = await waitFor(async () => {
    const t = await inPage(app, `127.0.0.1:${cp}/`, 'document.title').catch(() => '');
    return String(t).startsWith('{') ? JSON.parse(t) : null;
  }, 'permission probe');
  assert.deepEqual(probe, { geo: 'denied', microphone: 'granted', camera: 'denied', notifications: 'denied', midi: 'denied', 'clipboard-read': 'denied', audio: 'NotFoundError', ext: 'blocked', sock: 'blocked' });
  assert.deepEqual(ext.hits, []);

  await inPage(app, `127.0.0.1:${cp}/`, `window.open('${url(lp, '/lh')}', 'asl_dvs_lh') && 1`);
  await showing(url(lp, '/lh'));
  assert.equal(await mode(), 'single');
  assert.equal(await win.locator('#back').isHidden(), true);
  await win.locator('.tab', { hasText: 'Last Heard' }).locator('.x').click();
  await showing(url(cp));

  await inPage(app, `127.0.0.1:${cp}/`, `window.open('${url(tp)}', 'asl_dvs_listen') && 1`);
  await showing(url(tp));
  assert.deepEqual(await tabLabels(), ['Stub · Node Controller', 'Stub · Node Talker']);
  await inPage(app, `127.0.0.1:${cp}/`, `location.assign('${url(tp, '/x')}')`);
  await new Promise((r) => setTimeout(r, 600));
  assert.ok((await views(app)).some((v) => v.url === url(cp)), 'the controller page stays where it was');
  assert.equal(await win.locator('.tab').count(), 2);

  let [W, H] = await size();
  let vs = await views(app);
  assert.equal(vs.length, 2);
  const g = L.grid(W, H);
  same(vs.find((v) => v.visible).bounds, g.area, 'one page fills the 12 units');
  assert.equal(await win.locator('#head').evaluate((e) => Math.round(e.getBoundingClientRect().height)), g.header);
  assert.equal(await win.locator('#side').evaluate((e) => Math.round(e.getBoundingClientRect().width)), g.sidebar);
  const shownV = vs.find((v) => v.url === url(tp));
  const hiddenV = vs.find((v) => v.url === url(cp));
  assert.deepEqual([shownV.throttled, shownV.muted], [false, false]);
  assert.deepEqual([hiddenV.throttled, hiddenV.muted], [true, true]);
  assert.equal(await win.locator('.tab', { hasText: 'Node Controller' }).locator('.dot.idle').count(), 1);
  assert.equal(await win.locator('.tab', { hasText: 'Node Talker' }).locator('.dot.idle').count(), 0);
  await page(0, 0).click();
  await showing(url(cp));
  {
    const t = (await views(app)).find((v) => v.url === url(tp));
    assert.equal(t.visible, false);
    assert.deepEqual([t.throttled, t.muted], [false, false]);
    assert.equal(await win.locator('.tab', { hasText: 'Node Talker' }).locator('.dot.idle').count(), 0);
  }
  await page(0, 1).click();
  await showing(url(tp));
  assert.equal(await win.locator('#modes button[data-mode="trio"]').isDisabled(), true);

  await dragToZone(win, tab('Node Controller'), 'right');
  await showing(url(tp), url(cp));
  assert.equal(await mode(), 'cols');
  assert.equal(await win.locator('.pane-strip').count(), 2);
  assert.deepEqual(await win.locator('.pane-strip .strip-title').allTextContents(), ['Stub · Node Talker', 'Stub · Node Controller']);
  assert.equal(await win.locator('.pane-strip.focus').count(), 1);
  let ex = expected('cols', W, H);
  same((await views(app)).find((v) => v.url === url(tp)).bounds, ex.panes[0], 'left pane');
  same((await views(app)).find((v) => v.url === url(cp)).bounds, ex.panes[1], 'right pane');
  assert.ok((await views(app)).every((v) => v.visible && !v.throttled && !v.muted));

  await page(0, 2).click();
  await showing(url(sp));
  assert.equal(await mode(), 'single');
  assert.equal(await win.locator('#back').isVisible(), true);
  vs = await views(app);
  assert.deepEqual(vs.filter((v) => v.throttled && v.muted).map((v) => v.url), [url(cp)]);
  assert.deepEqual(vs.filter((v) => !v.visible).map((v) => [v.url, v.throttled, v.muted]).sort(), [[url(cp), true, true], [url(tp), false, false]].sort());
  assert.equal(await win.locator('.pages button.on').count(), 1);
  assert.equal(await win.locator('.pages button.open').count(), 2);

  await page(0, 0).click();
  await showing(url(tp), url(cp));
  assert.equal(await mode(), 'cols');
  assert.equal(await win.locator('.pane-strip.focus .strip-title').textContent(), 'Stub · Node Controller');
  assert.equal(await win.locator('#back').isHidden(), true);
  await page(0, 2).click();
  await showing(url(sp));
  await win.click('#back');
  await showing(url(tp), url(cp));

  await dragToZone(win, page(0, 2), 'below');
  await showing(url(tp), url(cp), url(sp));
  assert.equal(await mode(), 'trio');
  ex = expected('trio', W, H);
  vs = await views(app);
  same(vs.find((v) => v.url === url(tp)).bounds, ex.panes[0], 'top left');
  same(vs.find((v) => v.url === url(cp)).bounds, ex.panes[1], 'top right');
  same(vs.find((v) => v.url === url(sp)).bounds, ex.panes[2], 'bottom');
  assert.equal(ex.rects[2].w, W - g.sidebar);
  assert.ok(Math.abs(ex.rects[2].h - ex.rects[0].h) <= 1);
  assert.equal(await win.locator('.pane-strip').count(), 3);
  assert.equal(await win.locator('.divider.gapline').count(), 1);
  assert.equal(await win.locator('.divider.cols').count(), 1);

  await page(0, 3).click({ button: 'right' });
  assert.deepEqual(await win.locator('#menu .menu-item').allTextContents(), ['Show alone', 'Replace left', 'Replace right', 'Replace bottom']);
  await win.locator('#menu .menu-item', { hasText: 'Replace bottom' }).click();
  await showing(url(tp), url(cp), url(np));
  vs = await views(app);
  same(vs.find((v) => v.url === url(np)).bounds, ex.panes[2], 'bottom replaced');
  assert.deepEqual([vs.find((v) => v.url === url(sp)).throttled, vs.find((v) => v.url === url(sp)).muted], [true, true]);

  await page(0, 2).click({ modifiers: ['Control'] });
  await showing(url(tp), url(cp), url(sp));

  await inPage(app, `127.0.0.1:${tp}/`, `window.open('http://10.9.9.9/x', 'nt_lh') && 1`);
  await win.waitForFunction(() => /refused/.test(document.getElementById('notice').textContent));
  assert.equal(await win.locator('.tab').count(), 4);

  await inPage(app, `127.0.0.1:${tp}/`, `window.open('${url(lp, '/lh')}', 'nt_lh') && 1`);
  await showing(url(lp, '/lh'));
  assert.equal(await mode(), 'single');
  assert.equal(await win.locator('.tab').count(), 5);
  same((await visible())[0].bounds, g.area, 'Last Heard fills the page area');
  const lhTitle = await waitFor(async () => {
    const t = await inPage(app, `:${lp}/`, 'document.title').catch(() => '');
    return t === 'blocked' || t === 'reached' ? t : '';
  }, 'Last Heard request check');
  assert.equal(lhTitle, 'blocked');
  assert.deepEqual(ext.hits, []);
  assert.equal(await win.locator('#back').isVisible(), true);
  await win.click('#back');
  await showing(url(tp), url(cp), url(sp));
  assert.equal(await mode(), 'trio');

  await addNode('Stub2', '127.0.0.3', false);
  await page(1, 0).click();
  await win.waitForFunction(() => document.querySelectorAll('.tab').length === 6);
  await showing(`http://127.0.0.3:${cp}/`);
  await page(0, 0).click();
  await showing(url(tp), url(cp), url(sp));

  await win.click('#save-split');
  await win.fill('#n-name', 'Desk');
  await win.click('#form-name button[type="submit"]');
  await win.waitForSelector('.split-row');
  assert.deepEqual(await win.locator('.split-name').allTextContents(), ['Desk']);
  const splitsFile = path.join(data, 'splits.json');
  const sp1 = JSON.parse(fs.readFileSync(splitsFile, 'utf8')).splits;
  assert.equal(sp1.length, 1);
  assert.deepEqual(sp1[0].items.map((i) => `${i.pageId}`), ['talker', 'controller', 'sysmon']);

  await win.locator('.pane-strip', { hasText: 'Stub · SysMon' }).locator('button', { hasText: 'Remove' }).click();
  await showing(url(tp), url(cp));
  assert.equal(await mode(), 'cols');
  await win.locator('.pane-strip', { hasText: 'Stub · Node Talker' }).locator('button', { hasText: 'Alone' }).click();
  await showing(url(tp));
  assert.equal(await mode(), 'single');
  await win.click('.split-name');
  await showing(url(tp), url(cp), url(sp));
  assert.equal(await mode(), 'trio');

  await app.close();
  app = await launch();
  win = await app.firstWindow();
  await win.waitForLoadState('domcontentloaded');
  await showing(url(tp), url(cp), url(sp));
  assert.equal(await mode(), 'trio');
  assert.equal(await win.locator('.tab').count(), 5);
  assert.deepEqual(await win.locator('.split-name').allTextContents(), ['Desk']);
  assert.equal((await views(app)).length, 3);

  const focusedTitle = await win.locator('.pane-strip.focus .strip-title').textContent();
  await chord(app, '1');
  await waitFor(async () => (await mode()) === 'single', 'one page by shortcut');
  assert.equal(await win.locator('.tab.focus .label').textContent(), focusedTitle);
  assert.equal((await visible()).length, 1);
  await chord(app, '3');
  await showing(url(tp), url(cp), url(sp));
  assert.equal(await mode(), 'trio');
  await chord(app, '2');
  await waitFor(async () => (await mode()) === 'cols', 'two pages by shortcut');
  assert.equal((await visible()).length, 2);
  await chord(app, '3');
  await waitFor(async () => (await mode()) === 'trio', 'the three pages come back');
  assert.equal((await visible()).length, 3);

  for (let i = 0; i < 5; i += 1) await win.locator('.tab .x').nth(0).click();
  await waitFor(async () => (await views(app)).length === 0, 'all tabs closed');
  assert.match(await win.textContent('.pane-msg'), /Add a node/);

  await win.locator('.node').nth(1).locator('.node-top button').click();
  await win.click('#f-delete');
  await win.waitForFunction(() => document.querySelectorAll('.node').length === 1);
  assert.equal(await win.locator('.split-row').count(), 1);

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
  assert.equal(JSON.parse(fs.readFileSync(splitsFile, 'utf8')).splits.length, 0);
  assert.equal(await win.locator('.tab').count(), 0);
  assert.equal((await views(app)).length, 0);

  await app.close();
  for (const sv of [...servers, tlsSrv, extSrv]) sv.close();
  console.log('smoke ok');
}

main().then(() => process.exit(0), (e) => {
  console.error(e);
  process.exit(1);
});
