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

async function dragTo(win, source, target) {
  await source.scrollIntoViewIfNeeded();
  const sb = await source.boundingBox();
  const cx = sb.x + sb.width / 2;
  const cy = sb.y + sb.height / 2;
  await win.mouse.move(cx, cy);
  await win.mouse.down();
  await win.mouse.move(cx + 10, cy + 10, { steps: 4 });
  await target.waitFor({ timeout: 8000 });
  await target.scrollIntoViewIfNeeded();
  const tb = await target.boundingBox();
  await win.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2, { steps: 10 });
  await win.mouse.up();
  await win.waitForFunction(() => document.querySelectorAll('.zone').length === 0);
}

function geo(sel, W, H, ratio = 0.5) {
  const g = L.grid(W, H);
  const st = { view: 'slots', single: null, ratio, sel: { left: sel.left || null, right: sel.right || null, lower: sel.lower || null } };
  const r = L.rects(st, g.area);
  return { g, rects: r.panes, views: r.panes.map((p) => L.viewRect(st, p)) };
}

function same(a, b, msg) {
  assert.deepEqual({ x: a.x, y: a.y, w: a.width, h: a.height }, { x: b.x, y: b.y, w: b.w, h: b.h }, msg);
}

async function main() {
  const ext = pageServer('outside');
  const extSrv = http.createServer(ext.handler);
  const extPort = await listen(extSrv);
  const names = ['controller', 'talker', 'sysmon', 'nodemon', 'recorder', 'wifimon', 'h44', 'instmon', 'termon', 'piper', 'pibrary'];
  const stubs = Object.fromEntries(names.map((n) => [n, pageServer(`stub ${n}`, n === 'controller' ? probeScript(extPort) : '')]));
  const lh = pageServer('stub last heard', `<script>(async () => { let r; try { await fetch('http://localhost:${extPort}/lh', { mode: 'no-cors' }); r = 'reached'; } catch (e) { r = 'blocked'; } document.title = r; })();</script>`);
  const servers = [...names.map((n) => http.createServer(stubs[n].handler)), http.createServer(lh.handler)];
  const P = {};
  for (let i = 0; i < names.length; i += 1) P[names[i]] = await listen(servers[i]);
  const lp = await listen(servers[names.length]);

  const key = path.join(tmp, 'k.pem');
  const crt = path.join(tmp, 'c.pem');
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', crt, '-days', '2', '-subj', '/CN=stub', '-addext', 'subjectAltName=IP:127.0.0.1'], { stdio: 'ignore' });
  const tls = pageServer('stub tls talker');
  const tlsSrv = https.createServer({ key: fs.readFileSync(key), cert: fs.readFileSync(crt) }, tls.handler);
  const tlsPort = await listen(tlsSrv);

  const key2 = path.join(tmp, 'k2.pem');
  const crt2 = path.join(tmp, 'c2.pem');
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key2, '-out', crt2, '-days', '2', '-subj', '/CN=stub2', '-addext', 'subjectAltName=IP:127.0.0.1'], { stdio: 'ignore' });
  const tls2 = pageServer('stub tls controller');
  const tlsSrv2 = https.createServer({ key: fs.readFileSync(key2), cert: fs.readFileSync(crt2) }, tls2.handler);
  const tlsPort2 = await listen(tlsSrv2);

  const data = path.join(tmp, 'data');
  const extLog = path.join(tmp, 'external.log');
  const launch = () => _electron.launch({
    executablePath: require('electron'),
    args: [root, '--no-sandbox'],
    env: { ...process.env, NODECONTROLLER_DATA: data, NODECONTROLLER_EXTERNAL_LOG: extLog },
  });
  let app = await launch();
  let win = await app.firstWindow();
  await win.waitForLoadState('domcontentloaded');

  const U = (n) => `http://127.0.0.1:${P[n]}/`;
  const LHU = `http://127.0.0.1:${lp}/lh`;
  const visible = async () => (await views(app)).filter((v) => v.visible);
  const view = () => win.locator('#views button.on').getAttribute('data-view');
  const tabLabels = () => win.locator('.tab .label').allTextContents();
  const page = (i) => win.locator('.node').nth(0).locator('.pages button').nth(i);
  const size = async () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getContentSize());
  const slotEntries = (sl) => win.locator(`.slot[data-slot="${sl}"] .entry-main`).allTextContents();
  const slotSel = (sl) => win.locator(`.slot[data-slot="${sl}"] .entry.sel .entry-main`).textContent();
  const singleEntries = () => win.locator('#singles .entry-main').allTextContents();
  const entryIn = (sl, text) => win.locator(`.slot[data-slot="${sl}"] .entry`, { hasText: text });
  const showing = async (...urls) => {
    await waitFor(async () => {
      const v = await visible();
      return v.length === urls.length && urls.every((u) => v.some((x) => x.url === u));
    }, `showing ${urls.join(', ')}`);
  };
  const state = async (url) => (await views(app)).find((v) => v.url === url);
  const Lb = (t) => t;

  assert.equal(await win.title(), 'Node Controller Desktop');
  assert.match(await win.textContent('.pane-msg[data-empty]'), /Add a node/);
  assert.equal(await win.locator('#views button[data-view="single"]').isDisabled(), true);
  assert.equal(await win.locator('#views button[data-view="slots"]').isDisabled(), true);
  assert.deepEqual(await win.locator('.slot .sec-head').allTextContents(), ['Left slot', 'Right slot', 'Lower slot']);
  assert.equal(await win.locator('.slot .hint').count(), 3);
  assert.equal(await win.locator('#save-split').isDisabled(), true);

  await win.click('#add');
  await win.fill('#f-name', 'Stub');
  await win.fill('#f-host', '127.0.0.1');
  for (const n of names) await win.fill(`#f-port-${n}`, String(P[n]));
  await win.fill('#f-lan', 'bad');
  await win.click('#f-save');
  assert.match(await win.textContent('#f-error'), /LAN/);
  await win.fill('#f-lan', '');
  await win.click('#f-save');
  await win.waitForSelector('.node');
  const nodesFile = path.join(data, 'nodes.json');
  const savedNodes = JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes;
  assert.deepEqual(savedNodes[0].ports, P);
  assert.deepEqual(await win.locator('.node .pages button').allTextContents(), ['Node Controller', 'Node Talker', 'SysMon', 'Node Monitor', 'Node Recorder', 'WifiMon', '44helper', 'Install Monitor', 'Terminal Monitor', 'Pi-Piper ↗', 'Pibrary ↗']);
  assert.deepEqual(await win.locator('#tabs .tab.ext .label').allTextContents(), ['Pi-Piper ↗', 'Pibrary ↗']);
  assert.equal(await win.locator('#tabs .tab.ext').count(), 2);
  assert.equal(await win.locator('.node .pages button').nth(9).getAttribute('draggable'), 'false');

  await win.locator('#tabs .tab.ext', { hasText: 'Pi-Piper' }).click();
  await waitFor(() => fs.existsSync(extLog) && fs.readFileSync(extLog, 'utf8').includes(`http://127.0.0.1:${P.piper}/`), 'Pi-Piper opened in the browser');
  await win.waitForFunction(() => /Pi-Piper on Stub opened in your web browser/.test(document.getElementById('notice').textContent));
  await page(10).click();
  await waitFor(() => fs.readFileSync(extLog, 'utf8').includes(`http://127.0.0.1:${P.pibrary}/`), 'Pibrary opened in the browser');
  await page(10).click({ button: 'right' });
  assert.deepEqual(await win.locator('#menu .menu-item').allTextContents(), ['Open in web browser']);
  await win.locator('#menu .menu-item').click();
  await waitFor(() => fs.readFileSync(extLog, 'utf8').trim().split('\n').length === 3, 'the menu opens the browser too');
  assert.equal(await win.locator('.tab:not(.ext)').count(), 0);
  assert.equal((await views(app)).length, 0);

  await page(0).click();
  await showing(U('controller'));
  assert.deepEqual(await singleEntries(), [Lb('Node Controller')]);
  assert.equal(await view(), 'single');
  const probe = await waitFor(async () => {
    const t = await inPage(app, `127.0.0.1:${P.controller}/`, 'document.title').catch(() => '');
    return String(t).startsWith('{') ? JSON.parse(t) : null;
  }, 'permission probe');
  assert.deepEqual(probe, { geo: 'denied', microphone: 'granted', camera: 'denied', notifications: 'denied', midi: 'denied', 'clipboard-read': 'denied', audio: 'NotFoundError', ext: 'blocked', sock: 'blocked' });
  assert.deepEqual(ext.hits, []);

  await inPage(app, `127.0.0.1:${P.controller}/`, `window.open('${LHU}', 'asl_dvs_lh') && 1`);
  await showing(LHU);
  assert.equal(await view(), 'single');
  assert.deepEqual(await singleEntries(), [Lb('Node Controller'), 'Last Heard']);
  await win.locator('#singles .entry', { hasText: 'Last Heard' }).locator('.x').click();
  await showing(U('controller'));

  await inPage(app, `127.0.0.1:${P.controller}/`, `window.open('${U('talker')}', 'asl_dvs_listen') && 1`);
  await showing(U('talker'));
  assert.deepEqual(await singleEntries(), [Lb('Node Controller'), Lb('Node Talker')]);
  await inPage(app, `127.0.0.1:${P.controller}/`, `location.assign('${U('talker')}x')`);
  await new Promise((r) => setTimeout(r, 600));
  assert.ok(await state(U('controller')), 'the controller page stays where it was');
  assert.equal(await win.locator('.tab:not(.ext)').count(), 2);

  let [W, H] = await size();
  const g = L.grid(W, H);
  same((await visible())[0].bounds, g.area, 'one page fills the 12 units');
  assert.equal(await win.locator('#head').evaluate((e) => Math.round(e.getBoundingClientRect().height)), g.header);
  assert.equal(await win.locator('#side').evaluate((e) => Math.round(e.getBoundingClientRect().width)), g.sidebar);
  let t = await state(U('talker'));
  let c = await state(U('controller'));
  assert.deepEqual([t.throttled, t.muted, c.throttled, c.muted], [false, false, true, true]);
  assert.equal(await win.locator('.tab', { hasText: 'Node Controller' }).locator('.dot.idle').count(), 1);

  await page(0).click();
  await showing(U('controller'));
  t = await state(U('talker'));
  assert.deepEqual([t.visible, t.throttled, t.muted], [false, false, false]);
  assert.equal(await win.locator('.tab', { hasText: 'Node Talker' }).locator('.dot.idle').count(), 0);

  await dragTo(win, win.locator('#singles .entry', { hasText: 'Node Controller' }), win.locator('.slot[data-slot="left"]'));
  await waitFor(async () => (await view()) === 'slots' && (await slotEntries('left')).length === 1, 'controller in the left slot');
  assert.deepEqual(await slotEntries('left'), [Lb('Node Controller')]);
  assert.equal(await win.locator('.slot[data-slot="left"].focus').count(), 1);
  assert.deepEqual(await singleEntries(), [Lb('Node Talker')]);
  await showing(U('controller'));
  same((await visible())[0].bounds, g.area, 'a lone left slot is a one page view');
  assert.equal(await win.locator('.pane-strip').count(), 0);
  assert.equal(await win.locator('#views button[data-view="slots"]').isDisabled(), false);

  await dragTo(win, win.locator('#singles .entry', { hasText: 'Node Talker' }), win.locator('.zone[data-zone="right"]'));
  await showing(U('controller'), U('talker'));
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker')]);
  let ex = geo({ left: 'x', right: 'y' }, W, H);
  same((await state(U('controller'))).bounds, ex.views[0], 'left pane');
  same((await state(U('talker'))).bounds, ex.views[1], 'right pane');
  assert.equal(await win.locator('.pane-strip').count(), 2);
  assert.deepEqual(await win.locator('.pane-strip .strip-slot').allTextContents(), ['Left', 'Right']);

  await dragTo(win, page(2), win.locator('.slot[data-slot="left"]'));
  await showing(U('sysmon'), U('talker'));
  assert.deepEqual(await slotEntries('left'), [Lb('Node Controller'), Lb('SysMon')]);
  assert.equal(await slotSel('left'), Lb('SysMon'));
  c = await state(U('controller'));
  assert.deepEqual([c.visible, c.throttled, c.muted], [false, true, true]);
  assert.deepEqual(await win.locator('.pane-strip').nth(0).locator('.strip-stack button').allTextContents(), ['Node Controller', 'SysMon']);

  await entryIn('left', 'Node Controller').locator('.entry-main').click();
  await showing(U('controller'), U('talker'));
  assert.equal(await slotSel('left'), Lb('Node Controller'));
  await win.locator('.pane-strip').nth(0).locator('.strip-stack button', { hasText: 'SysMon' }).click();
  await showing(U('sysmon'), U('talker'));

  await dragTo(win, page(3), win.locator('.zone[data-zone="lower"]'));
  await showing(U('sysmon'), U('talker'), U('nodemon'));
  [W, H] = await size();
  ex = geo({ left: 'x', right: 'y', lower: 'z' }, W, H);
  same((await state(U('sysmon'))).bounds, ex.views[0], 'left');
  same((await state(U('talker'))).bounds, ex.views[1], 'right');
  same((await state(U('nodemon'))).bounds, ex.views[2], 'lower');
  assert.equal(ex.rects[2].w, W - g.sidebar);
  assert.equal(await win.locator('.pane-strip').count(), 3);
  assert.equal(await win.locator('.divider.gapline').count(), 1);
  assert.equal(await win.locator('.divider.cols').count(), 1);

  await page(4).click({ button: 'right' });
  assert.deepEqual(await win.locator('#menu .menu-item').allTextContents(), ['Show alone', 'Put in Left slot', 'Put in Right slot', 'Put in Lower slot']);
  await win.locator('#menu .menu-item', { hasText: 'Put in Right slot' }).click();
  await showing(U('sysmon'), U('recorder'), U('nodemon'));
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker'), Lb('Node Recorder')]);
  t = await state(U('talker'));
  assert.deepEqual([t.visible, t.throttled, t.muted], [false, false, false]);

  await page(5).click({ modifiers: ['Control'] });
  await showing(U('sysmon'), U('wifimon'), U('nodemon'));
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker'), Lb('Node Recorder'), Lb('WifiMon')]);
  const idleOnes = (await views(app)).filter((v) => !v.visible && v.throttled).map((v) => v.url).sort();
  assert.deepEqual(idleOnes, [U('controller'), U('recorder')].sort());

  await entryIn('right', 'Node Talker').locator('.entry-main').click();
  await showing(U('sysmon'), U('talker'), U('nodemon'));
  assert.equal(await win.locator('.slot[data-slot="right"].focus').count(), 1);

  await page(6).click({ button: 'right' });
  assert.deepEqual(await win.locator('#menu .menu-item').allTextContents(), ['Show alone']);
  await page(6).press('Escape');
  await page(6).click();
  await showing(U('h44'));
  assert.equal(await view(), 'single');
  assert.deepEqual(await slotEntries('left'), [Lb('Node Controller'), Lb('SysMon')]);
  assert.equal(await win.locator('.node .pages button').nth(6).getAttribute('draggable'), 'false');
  await dragTo(win, page(6), win.locator('.slot[data-slot="lower"]'));
  assert.deepEqual(await slotEntries('lower'), [Lb('Node Monitor')]);
  assert.equal(await view(), 'single');
  await win.click('#views button[data-view="slots"]');
  await showing(U('sysmon'), U('talker'), U('nodemon'));
  assert.equal(await view(), 'slots');

  await page(8).click({ button: 'right' });
  assert.deepEqual(await win.locator('#menu .menu-item').allTextContents(), ['Show alone']);
  await win.locator('#menu .menu-item').click();
  await showing(U('termon'));
  assert.equal(await view(), 'single');
  assert.equal(await win.locator('.node .pages button').nth(8).getAttribute('draggable'), 'false');
  await page(7).click();
  await showing(U('instmon'));
  assert.equal(await win.locator('.node .pages button').nth(7).getAttribute('draggable'), 'false');
  assert.deepEqual(await slotEntries('left'), [Lb('Node Controller'), Lb('SysMon')]);
  await win.click('#views button[data-view="slots"]');
  await showing(U('sysmon'), U('talker'), U('nodemon'));

  await chord(app, '1');
  await waitFor(async () => (await view()) === 'single', 'single by shortcut');
  assert.equal((await visible()).length, 1);
  await chord(app, '2');
  await waitFor(async () => (await view()) === 'slots', 'slots by shortcut');
  assert.equal((await visible()).length, 3);

  await inPage(app, `127.0.0.1:${P.talker}/`, `window.open('http://10.9.9.9/x', 'nt_lh') && 1`);
  await win.waitForFunction(() => /refused/.test(document.getElementById('notice').textContent));
  await inPage(app, `127.0.0.1:${P.talker}/`, `window.open('${LHU}', 'nt_lh') && 1`);
  await showing(LHU);
  assert.equal(await view(), 'single');
  same((await visible())[0].bounds, g.area, 'Last Heard fills the page area');
  const lhTitle = await waitFor(async () => {
    const x = await inPage(app, `:${lp}/`, 'document.title').catch(() => '');
    return x === 'blocked' || x === 'reached' ? x : '';
  }, 'Last Heard request check');
  assert.equal(lhTitle, 'blocked');
  assert.deepEqual(ext.hits, []);
  await win.click('#views button[data-view="slots"]');
  await showing(U('sysmon'), U('talker'), U('nodemon'));
  await win.locator('#singles .entry', { hasText: 'Last Heard' }).locator('.entry-main').click();
  await showing(LHU);
  await win.locator('#singles .entry', { hasText: 'Last Heard' }).click({ button: 'right' });
  await win.locator('#menu .menu-item', { hasText: 'Put in Lower slot' }).click();
  await showing(U('sysmon'), U('talker'), LHU);
  assert.deepEqual(await slotEntries('lower'), [Lb('Node Monitor'), 'Last Heard']);
  await win.click('#save-split');
  await win.fill('#n-name', 'Nope');
  await win.click('#form-name button[type="submit"]');
  assert.match(await win.textContent('#n-error'), /Last Heard/);
  await win.click('#n-cancel');
  await win.locator('.slot[data-slot="lower"] .entry', { hasText: 'Last Heard' }).locator('.x').click();
  await win.locator('#singles .entry', { hasText: 'Last Heard' }).locator('.x').click();
  await showing(U('sysmon'), U('talker'), U('nodemon'));

  await win.click('#save-split');
  await win.fill('#n-name', 'Desk');
  await win.click('#form-name button[type="submit"]');
  await win.waitForSelector('.split-row');
  assert.deepEqual(await win.locator('.split-name').allTextContents(), ['Desk']);
  const splitsFile = path.join(data, 'splits.json');
  const sp1 = JSON.parse(fs.readFileSync(splitsFile, 'utf8')).splits;
  assert.equal(sp1.length, 1);
  assert.deepEqual(sp1[0].slots.left.map((i) => i.pageId), ['controller', 'sysmon']);
  assert.deepEqual(sp1[0].slots.right.map((i) => i.pageId), ['talker', 'recorder', 'wifimon']);
  assert.deepEqual(sp1[0].slots.lower.map((i) => i.pageId), ['nodemon']);
  assert.equal(sp1[0].sel.left.pageId, 'sysmon');

  await win.locator('.slot[data-slot="right"] .entry', { hasText: 'Node Recorder' }).locator('.x').click();
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker'), Lb('WifiMon')]);
  assert.ok((await singleEntries()).includes(Lb('Node Recorder')));
  await win.click('.split-name');
  await waitFor(async () => (await slotEntries('right')).length === 3, 'saved split applied');
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker'), Lb('Node Recorder'), Lb('WifiMon')]);
  assert.equal(await view(), 'slots');

  await app.close();
  app = await launch();
  win = await app.firstWindow();
  await win.waitForLoadState('domcontentloaded');
  await waitFor(async () => (await visible()).length === 3, 'restored slots');
  assert.equal(await view(), 'slots');
  assert.deepEqual(await slotEntries('left'), [Lb('Node Controller'), Lb('SysMon')]);
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker'), Lb('Node Recorder'), Lb('WifiMon')]);
  assert.deepEqual(await slotEntries('lower'), [Lb('Node Monitor')]);
  assert.deepEqual(await win.locator('.split-name').allTextContents(), ['Desk']);
  assert.equal((await views(app)).length, 3);
  assert.equal(await win.locator('.tab:not(.ext)').count(), 9);

  const total = await win.locator('.tab:not(.ext)').count();
  for (let i = 0; i < total; i += 1) await win.locator('.tab .x').nth(0).click();
  await waitFor(async () => (await views(app)).length === 0, 'all tabs closed');
  assert.match(await win.textContent('.pane-msg[data-empty]'), /Add a node/);
  assert.deepEqual(await slotEntries('left'), []);
  await win.click('.split-name');
  await waitFor(async () => (await visible()).length === 3, 'saved split opens its pages');
  assert.equal(await win.locator('.tab:not(.ext)').count(), 6);

  await chord(app, '1');
  await waitFor(async () => (await view()) === 'single', 'single');
  const tabsNow = await win.locator('.tab:not(.ext)').count();
  for (let i = 0; i < tabsNow; i += 1) await win.locator('.tab .x').nth(0).click();
  await waitFor(async () => (await views(app)).length === 0, 'tabs closed again');

  await win.click('.node-top button');
  await win.fill('#f-host', 'https://127.0.0.1');
  await win.fill('#f-port-talker', String(tlsPort));
  await win.click('#f-save');
  await win.waitForSelector('.node-host:has-text("https://127.0.0.1")');

  await page(1).click();
  await win.waitForSelector('.pane-msg h2');
  assert.match(await win.textContent('.pane-msg h2'), /Could not open Stub · Node Talker/);
  assert.match(await win.textContent('.pane-msg .mono'), /SHA-256 ([0-9A-F]{2}:){31}[0-9A-F]{2}/);
  assert.equal(tls.hits.length, 0);
  assert.equal(await win.locator('.tab .dot.failed').count(), 1);
  await win.click('text=Trust this certificate');
  await waitFor(() => tls.hits.includes('/'), 'request to the pinned https node');
  await waitFor(async () => (await win.locator('.pane-msg').count()) === 0, 'failure panel gone');
  let pins = JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].pins;
  assert.equal(pins.length, 1);
  assert.match(pins[0], /^[0-9a-f]{64}$/);

  await win.click('.node-top button');
  await win.fill('#f-port-controller', String(tlsPort2));
  await win.click('#f-save');
  await win.waitForFunction(() => !document.getElementById('dlg').open);
  await page(0).click();
  await win.waitForSelector('.pane-msg h2');
  assert.match(await win.textContent('.pane-msg h2'), /Could not open Stub · Node Controller/);
  assert.equal(tls2.hits.length, 0);
  await win.click('text=Trust this certificate');
  await waitFor(() => tls2.hits.includes('/'), 'request to the second pinned certificate');
  pins = JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].pins;
  assert.equal(pins.length, 2);
  assert.notEqual(pins[0], pins[1]);
  await page(1).click();
  await waitFor(async () => (await visible()).some((v) => v.url.startsWith('https://127.0.0.1:') && v.url.includes(String(tlsPort))), 'the first certificate is still trusted');

  await win.click('.node-top button');
  await win.click('#f-delete');
  await win.waitForFunction(() => document.querySelectorAll('.node').length === 0);
  assert.equal(JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes.length, 0);
  assert.equal(JSON.parse(fs.readFileSync(splitsFile, 'utf8')).splits.length, 0);
  assert.equal(await win.locator('.tab:not(.ext)').count(), 0);
  assert.equal((await views(app)).length, 0);

  await app.close();
  for (const sv of [...servers, tlsSrv, tlsSrv2, extSrv]) sv.close();
  console.log('smoke ok');
}

main().then(() => process.exit(0), (e) => {
  console.error(e);
  process.exit(1);
});
