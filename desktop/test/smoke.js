const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync, spawn } = require('node:child_process');
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
    env: { ...process.env, NODECONTROLLER_DATA: data, NODECONTROLLER_EXTERNAL_LOG: extLog, NODECONTROLLER_PROBE_MS: '300' },
  });
  let app = await launch();
  let win = await app.firstWindow();
  await win.waitForLoadState('domcontentloaded');

  const U = (n) => `http://127.0.0.1:${P[n]}/`;
  const LHU = `http://127.0.0.1:${lp}/lh`;
  const visible = async () => (await views(app)).filter((v) => v.visible);
  const view = () => win.locator('#views button.on').getAttribute('data-view');
  const PG = ['Node Controller', 'Node Talker', 'SysMon', 'Node Monitor', 'Node Recorder', 'WifiMon', '44helper', 'Install Monitor', 'Terminal Monitor', 'Pi-Piper ↗', 'Pibrary ↗'];
  const pgEntry = (name) => (name === 'Install Monitor'
    ? win.locator('#side-foot .entry')
    : win.locator('#pages .entry').filter({ has: win.locator('.entry-main', { hasText: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`) }) }));
  const page = (i) => pgEntry(PG[i]);
  const classes = async (loc) => ((await loc.getAttribute('class')) || '').split(/\s+/);
  const pageNames = () => win.locator('#pages .entry-main').allTextContents();
  const openCount = () => win.locator('#pages .entry.sel, #pages .entry.open, .slot .entry, #side-foot .entry.sel, #side-foot .entry.open').count();
  const closeAll = async () => {
    for (let i = 0; i < 40 && (await win.locator('.slot .entry .x').count()); i += 1) {
      await win.locator('.slot .entry .x').first().click();
      await new Promise((r) => setTimeout(r, 120));
    }
    for (let i = 0; i < 40 && (await win.locator('#pages .entry .x').count()); i += 1) {
      await win.locator('#pages .entry .x').first().click();
      await new Promise((r) => setTimeout(r, 120));
    }
    for (let i = 0; i < 5 && (await win.locator('#side-foot .entry.sel, #side-foot .entry.open').count()); i += 1) {
      await win.locator('#side-foot .entry.sel, #side-foot .entry.open').first().click({ button: 'right' });
      await win.locator('#menu .menu-item', { hasText: 'Close tab' }).click();
      await new Promise((r) => setTimeout(r, 120));
    }
  };
  const size = async () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].getContentSize());
  const slotEntries = (sl) => win.locator(`.slot[data-slot="${sl}"] .entry-main`).allTextContents();
  const slotSel = (sl) => win.locator(`.slot[data-slot="${sl}"] .entry.sel .entry-main`).textContent();
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
  await win.waitForSelector('#pages .group');
  const nodesFile = path.join(data, 'nodes.json');
  const savedNodes = JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes;
  assert.deepEqual(savedNodes[0].ports, P);
  assert.equal(await win.locator('#tabs, .tab').count(), 0);
  await waitFor(async () => (await pageNames()).length === 10, 'every running page is listed');
  assert.deepEqual(await pageNames(), ['Node Controller', 'Node Talker', 'SysMon', 'Node Monitor', 'Node Recorder', 'WifiMon', '44helper', 'Terminal Monitor', 'Pi-Piper ↗', 'Pibrary ↗']);
  assert.deepEqual(await win.locator('#side-foot .entry-main').allTextContents(), ['Install Monitor']);
  assert.equal(await page(9).getAttribute('draggable'), 'false');
  assert.equal(await page(7).getAttribute('draggable'), 'false');
  assert.equal(await win.locator('.group-name').textContent(), 'Stub');

  const serverOf = (n) => servers[names.indexOf(n)];
  const stop = (n) => new Promise((r) => serverOf(n).close(r));
  const start = (n) => new Promise((r) => serverOf(n).listen(P[n], '0.0.0.0', r));
  await stop('sysmon');
  await stop('recorder');
  await waitFor(async () => !(await pageNames()).includes('SysMon') && !(await pageNames()).includes('Node Recorder'), 'stopped pages are hidden');
  assert.equal((await pageNames()).length, 8);
  await start('sysmon');
  await start('recorder');
  await waitFor(async () => (await pageNames()).includes('SysMon') && (await pageNames()).includes('Node Recorder'), 'started pages come back');

  await stop('instmon');
  await waitFor(async () => (await classes(page(7))).includes('down'), 'a stopped Install Monitor is marked');
  assert.deepEqual(await win.locator('#side-foot .entry-main').allTextContents(), ['Install Monitor']);
  await start('instmon');
  await waitFor(async () => !(await classes(page(7))).includes('down'), 'Install Monitor is up again');

  await page(2).locator('.entry-main').click();
  await showing(U('sysmon'));
  await stop('sysmon');
  await new Promise((r) => setTimeout(r, 900));
  assert.ok((await pageNames()).includes('SysMon'), 'a stopped page that is open stays in the list');
  await waitFor(async () => (await classes(page(2))).includes('down'), 'and is marked as stopped');
  await start('sysmon');
  await waitFor(async () => !(await classes(page(2))).includes('down'), 'and unmarked when it runs again');
  await page(2).locator('.x').click();
  await waitFor(async () => (await views(app)).length === 0, 'SysMon closed');

  await page(9).locator('.entry-main').click();
  await waitFor(() => fs.existsSync(extLog) && fs.readFileSync(extLog, 'utf8').includes(`http://127.0.0.1:${P.piper}/`), 'Pi-Piper opened in the browser');
  await win.waitForFunction(() => /Pi-Piper on Stub opened in your web browser/.test(document.getElementById('notice').textContent));
  await page(10).locator('.entry-main').click();
  await waitFor(() => fs.readFileSync(extLog, 'utf8').includes(`http://127.0.0.1:${P.pibrary}/`), 'Pibrary opened in the browser');
  await page(10).click({ button: 'right' });
  assert.deepEqual(await win.locator('#menu .menu-item').allTextContents(), ['Open in web browser']);
  await win.locator('#menu .menu-item').click();
  await waitFor(() => fs.readFileSync(extLog, 'utf8').trim().split('\n').length === 3, 'the menu opens the browser too');
  assert.equal(await openCount(), 0);
  assert.equal((await views(app)).length, 0);

  await page(0).locator('.entry-main').click();
  await showing(U('controller'));
  assert.ok((await classes(page(0))).includes('sel'));
  assert.equal(await view(), 'single');
  assert.equal(await win.locator('#title .title-text').textContent(), 'Stub · Node Controller');
  const probe = await waitFor(async () => {
    const t = await inPage(app, `127.0.0.1:${P.controller}/`, 'document.title').catch(() => '');
    return String(t).startsWith('{') ? JSON.parse(t) : null;
  }, 'permission probe');
  assert.deepEqual(probe, { geo: 'denied', microphone: 'granted', camera: 'denied', notifications: 'denied', midi: 'denied', 'clipboard-read': 'denied', audio: 'NotFoundError', ext: 'blocked', sock: 'blocked' });
  assert.deepEqual(ext.hits, []);

  await app.evaluate(({ BrowserWindow }, part) => {
    const v = BrowserWindow.getAllWindows()[0].contentView.children.find((c) => c.webContents.getURL().includes(part));
    v.webContents.forcefullyCrashRenderer();
  }, `127.0.0.1:${P.controller}/`);
  await win.waitForSelector('.pane-msg h2');
  assert.match(await win.textContent('.pane-msg h2'), /Could not open Stub · Node Controller/);
  assert.match(await win.textContent('.pane-msg p'), /stopped working/);
  assert.ok((await classes(page(0))).includes('failed'));
  const diag = path.join(data, 'diagnostics.log');
  await waitFor(() => fs.existsSync(diag) && /page process gone: .*:controller reason=/.test(fs.readFileSync(diag, 'utf8')), 'the crash is written to diagnostics.log');
  assert.equal(await win.title(), 'Node Controller Desktop');
  await win.click('.pane-msg button:has-text("Try again")');
  await showing(U('controller'));
  await waitFor(async () => (await win.locator('.pane-msg').count()) === 0, 'the page is back after a crash');
  assert.ok(!(await classes(page(0))).includes('failed'));

  await inPage(app, `127.0.0.1:${P.controller}/`, `window.open('${LHU}', 'asl_dvs_lh') && 1`);
  await showing(LHU);
  assert.equal(await view(), 'single');
  assert.equal(await win.locator('#pages .entry[data-key="lh"]').count(), 1);
  await win.locator('#pages .entry[data-key="lh"] .x').click();
  await showing(U('controller'));

  await inPage(app, `127.0.0.1:${P.controller}/`, `window.open('${U('talker')}', 'asl_dvs_listen') && 1`);
  await showing(U('talker'));
  assert.ok((await classes(page(0))).includes('open') && (await classes(page(1))).includes('sel'));
  await inPage(app, `127.0.0.1:${P.controller}/`, `location.assign('${U('talker')}x')`);
  await new Promise((r) => setTimeout(r, 600));
  assert.ok(await state(U('controller')), 'the controller page stays where it was');
  assert.equal(await openCount(), 2);

  let [W, H] = await size();
  const g = L.grid(W, H);
  same((await visible())[0].bounds, g.area, 'one page fills the 12 units');
  assert.equal(await win.locator('#head').evaluate((e) => Math.round(e.getBoundingClientRect().height)), g.header);
  assert.equal(await win.locator('#side').evaluate((e) => Math.round(e.getBoundingClientRect().width)), g.sidebar);
  let t = await state(U('talker'));
  let c = await state(U('controller'));
  assert.deepEqual([t.throttled, t.muted, c.throttled, c.muted], [false, false, true, true]);
  assert.ok((await classes(page(0))).includes('idle'));
  assert.ok(!(await classes(page(1))).includes('idle'));

  await page(0).locator('.entry-main').click();
  await showing(U('controller'));
  t = await state(U('talker'));
  assert.deepEqual([t.visible, t.throttled, t.muted], [false, false, false]);
  assert.ok(!(await classes(page(1))).includes('idle'));

  await dragTo(win, page(0), win.locator('.slot[data-slot="left"]'));
  await waitFor(async () => (await view()) === 'slots' && (await slotEntries('left')).length === 1, 'controller in the left slot');
  assert.deepEqual(await slotEntries('left'), [Lb('Node Controller')]);
  assert.equal(await win.locator('.slot[data-slot="left"].focus').count(), 1);
  assert.ok(!(await pageNames()).includes('Node Controller'));
  await showing(U('controller'));
  same((await visible())[0].bounds, g.area, 'a lone left slot is a one page view');
  assert.equal(await win.locator('.pane-strip').count(), 0);
  assert.equal(await win.locator('#views button[data-view="slots"]').isDisabled(), false);

  await dragTo(win, page(1), win.locator('.zone[data-zone="right"]'));
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
  {
    const vsz = async (u) => JSON.parse(await inPage(app, u.replace('http://', '').replace(/\/$/, '') + '/', 'JSON.stringify([innerWidth, innerHeight, Math.round(devicePixelRatio * 100) / 100])'));
    const checks = [['sysmon', ex.views[0]], ['talker', ex.views[1]], ['nodemon', ex.views[2]]];
    for (const [n, v] of checks) {
      const z = L.autoZoom(v.w, v.h);
      assert.ok(z < 1 && z >= 0.5, `${n} is scaled down to fit (${z})`);
      const [iw, ih] = await vsz(U(n));
      assert.ok(Math.abs(iw - Math.round(v.w / z)) <= 1 && Math.abs(ih - Math.round(v.h / z)) <= 1, `${n} sees ${iw}x${ih}, expected about ${Math.round(v.w / z)}x${Math.round(v.h / z)}`);
    }
    assert.deepEqual(await win.locator('.pane-strip .zoom-pct').allTextContents(), checks.map(([, v]) => `${Math.round(L.autoZoom(v.w, v.h) * 100)}%`));
    assert.equal(await win.locator('#title .zoom-chip').count(), 1);

    await inPage(app, `127.0.0.1:${P.sysmon}/`, `document.body.insertAdjacentHTML('beforeend', '<button id="cb" style="position:fixed;left:120px;top:90px;width:90px;height:40px" onclick="document.title=\\'clicked\\'">x</button>') || 1`);
    const zS = L.autoZoom(ex.views[0].w, ex.views[0].h);
    const box = JSON.parse(await inPage(app, `127.0.0.1:${P.sysmon}/`, 'JSON.stringify(document.getElementById("cb").getBoundingClientRect())'));
    await app.evaluate(({ BrowserWindow }, a) => {
      const v = BrowserWindow.getAllWindows()[0].contentView.children.find((c) => c.webContents.getURL().includes(a.part));
      const x = Math.round(a.x);
      const y = Math.round(a.y);
      v.webContents.sendInputEvent({ type: 'mouseMove', x, y });
      v.webContents.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: 1 });
      v.webContents.sendInputEvent({ type: 'mouseUp', x, y, button: 'left', clickCount: 1 });
    }, { part: `127.0.0.1:${P.sysmon}/`, x: (box.left + box.width / 2) * zS, y: (box.top + box.height / 2) * zS });
    await waitFor(async () => (await inPage(app, `127.0.0.1:${P.sysmon}/`, 'document.title')) === 'clicked', 'a click lands on the right spot in a scaled pane');

    const pct = () => win.locator('.pane-strip').nth(0).locator('.zoom-pct');
    const before = await pct().textContent();
    await win.locator('.pane-strip').nth(0).locator('.zoom button', { hasText: '+' }).click();
    await waitFor(async () => (await pct()).textContent().then((t) => t !== before), 'the plus button makes the pane bigger');
    assert.ok(Number.parseInt(await pct().textContent(), 10) > Number.parseInt(before, 10));
    assert.ok((await classes(pct())).includes('set'));
    const [iw2] = await vsz(U('sysmon'));
    assert.ok(iw2 < Math.round(ex.views[0].w / zS), 'the page now sees a narrower window');
    await pct().click();
    await waitFor(async () => (await pct().textContent()) === before, 'clicking the percentage fits the pane again');
    assert.ok(!(await classes(pct())).includes('set'));

    await win.locator('.pane-strip').nth(0).click();
    await chord(app, '-');
    await waitFor(async () => Number.parseInt(await pct().textContent(), 10) < Number.parseInt(before, 10), 'Ctrl+minus makes it smaller');
    await chord(app, '0');
    await waitFor(async () => (await pct().textContent()) === before, 'Ctrl+0 fits it again');
    await chord(app, '=');
    await waitFor(async () => Number.parseInt(await pct().textContent(), 10) > Number.parseInt(before, 10), 'Ctrl+plus makes it bigger');
    await win.locator('#title .zoom-chip').click();
    await waitFor(async () => (await pct().textContent()) === before, 'the chip in the title bar fits it again');
  }

  await page(4).click({ button: 'right' });
  assert.deepEqual(await win.locator('#menu .menu-item').allTextContents(), ['Show alone', 'Put in Left slot', 'Put in Right slot', 'Put in Lower slot']);
  await win.locator('#menu .menu-item', { hasText: 'Put in Right slot' }).click();
  await showing(U('sysmon'), U('recorder'), U('nodemon'));
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker'), Lb('Node Recorder')]);
  t = await state(U('talker'));
  assert.deepEqual([t.visible, t.throttled, t.muted], [false, false, false]);

  await page(5).locator('.entry-main').click({ modifiers: ['Control'] });
  await showing(U('sysmon'), U('wifimon'), U('nodemon'));
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker'), Lb('Node Recorder'), Lb('WifiMon')]);
  const idleOnes = (await views(app)).filter((v) => !v.visible && v.throttled).map((v) => v.url).sort();
  assert.deepEqual(idleOnes, [U('controller'), U('recorder')].sort());

  await entryIn('right', 'Node Talker').locator('.entry-main').click();
  await showing(U('sysmon'), U('talker'), U('nodemon'));
  assert.equal(await win.locator('.slot[data-slot="right"].focus').count(), 1);

  await page(6).click({ button: 'right' });
  assert.deepEqual(await win.locator('#menu .menu-item').allTextContents(), ['Show alone']);
  await win.keyboard.press('Escape');
  await page(6).locator('.entry-main').click();
  await showing(U('h44'));
  assert.equal(await view(), 'single');
  assert.deepEqual(await slotEntries('left'), [Lb('Node Controller'), Lb('SysMon')]);
  assert.equal(await page(6).getAttribute('draggable'), 'false');
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
  assert.equal(await page(8).getAttribute('draggable'), 'false');
  await page(7).locator('.entry-main').click();
  await showing(U('instmon'));
  assert.equal(await page(7).getAttribute('draggable'), 'false');
  assert.equal(await win.locator('#side-foot .entry .x').count(), 0);
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
  await win.locator('#pages .entry[data-key="lh"] .entry-main').click();
  await showing(LHU);
  await win.locator('#pages .entry[data-key="lh"]').click({ button: 'right' });
  await win.locator('#menu .menu-item', { hasText: 'Put in Lower slot' }).click();
  await showing(U('sysmon'), U('talker'), LHU);
  assert.deepEqual(await slotEntries('lower'), [Lb('Node Monitor'), 'Last Heard']);
  await win.click('#save-split');
  await win.fill('#n-name', 'Nope');
  await win.click('#form-name button[type="submit"]');
  assert.match(await win.textContent('#n-error'), /Last Heard/);
  await win.click('#n-cancel');
  await win.locator('.slot[data-slot="lower"] .entry', { hasText: 'Last Heard' }).locator('.x').click();
  await win.locator('#pages .entry[data-key="lh"] .x').click();
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
  assert.ok((await pageNames()).includes('Node Recorder'));
  await win.click('.split-name');
  await waitFor(async () => (await slotEntries('right')).length === 3, 'saved split applied');
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker'), Lb('Node Recorder'), Lb('WifiMon')]);
  assert.equal(await view(), 'slots');

  await app.close();
  assert.equal(fs.existsSync(path.join(data, 'running.json')), false, 'a clean exit removes the marker');
  app = await launch();
  win = await app.firstWindow();
  await win.waitForLoadState('domcontentloaded');
  await waitFor(async () => (await visible()).length === 3, 'restored slots');
  assert.equal(await win.locator('#notice:not([hidden])').count(), 0);
  assert.equal(await view(), 'slots');
  assert.deepEqual(await slotEntries('left'), [Lb('Node Controller'), Lb('SysMon')]);
  assert.deepEqual(await slotEntries('right'), [Lb('Node Talker'), Lb('Node Recorder'), Lb('WifiMon')]);
  assert.deepEqual(await slotEntries('lower'), [Lb('Node Monitor')]);
  assert.deepEqual(await win.locator('.split-name').allTextContents(), ['Desk']);
  assert.equal((await views(app)).length, 3);
  assert.equal(await openCount(), 9);

  await closeAll();
  await waitFor(async () => (await views(app)).length === 0, 'all tabs closed');
  assert.match(await win.textContent('.pane-msg[data-empty]'), /Add a node/);
  assert.deepEqual(await slotEntries('left'), []);
  await win.click('.split-name');
  await waitFor(async () => (await visible()).length === 3, 'saved split opens its pages');
  assert.equal(await openCount(), 6);

  {
    const running = path.join(data, 'running.json');
    const nodesBefore = JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0];
    const second = spawn(require('electron'), [root, '--no-sandbox'], { env: { ...process.env, NODECONTROLLER_DATA: data }, stdio: 'ignore' });
    const code = await new Promise((res) => {
      second.on('exit', res);
      setTimeout(() => {
        second.kill();
        res('timeout');
      }, 25000);
    });
    assert.equal(code, 0, 'a second copy hands over and quits');
    assert.equal(await win.title(), 'Node Controller Desktop');
    assert.ok(fs.existsSync(running), 'the first copy keeps its marker');
    assert.equal(await openCount(), 6);

    const pid = app.process().pid;
    app.process().kill('SIGKILL');
    await waitFor(() => {
      try {
        process.kill(pid, 0);
        return false;
      } catch {
        return true;
      }
    }, 'the app is gone');
    assert.ok(fs.existsSync(running), 'a hard kill leaves the marker');
    app = await launch();
    win = await app.firstWindow();
    await win.waitForLoadState('domcontentloaded');
    await win.waitForFunction(() => /closed unexpectedly last time/.test(document.getElementById('notice').textContent));
    assert.equal(await openCount(), 0);
    assert.equal((await views(app)).length, 0);
    assert.equal(await win.locator('.slot .entry').count(), 0);
    assert.match(await win.textContent('.pane-msg[data-empty]'), /Add a node/);
    assert.deepEqual(await win.locator('.split-name').allTextContents(), ['Desk']);
    assert.deepEqual(JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0], nodesBefore);
    assert.match(fs.readFileSync(path.join(data, 'diagnostics.log'), 'utf8'), /did not exit cleanly/);
    await win.click('.split-name');
    await waitFor(async () => (await visible()).length === 3, 'a saved split still opens after the reset');
    assert.equal(await openCount(), 6);
    await app.close();
    assert.equal(fs.existsSync(running), false);
    app = await launch();
    win = await app.firstWindow();
    await win.waitForLoadState('domcontentloaded');
    await waitFor(async () => (await visible()).length === 3, 'after a clean exit the pages come back as before');
    assert.equal(await win.locator('#notice:not([hidden])').count(), 0);
  }

  await chord(app, '1');
  await waitFor(async () => (await view()) === 'single', 'single');
  await closeAll();
  await waitFor(async () => (await views(app)).length === 0, 'tabs closed again');

  await win.click('.group-head button');
  await win.fill('#f-host', 'https://127.0.0.1');
  await win.fill('#f-port-talker', String(tlsPort));
  await win.click('#f-save');
  await waitFor(() => JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].https === true, 'the node is saved as https');

  await page(1).locator('.entry-main').click();
  await win.waitForSelector('.pane-msg h2');
  assert.match(await win.textContent('.pane-msg h2'), /Could not open Stub · Node Talker/);
  assert.match(await win.textContent('.pane-msg .mono'), /SHA-256 ([0-9A-F]{2}:){31}[0-9A-F]{2}/);
  assert.equal(tls.hits.length, 0);
  assert.ok((await classes(page(1))).includes('failed'));
  await win.click('text=Trust this certificate');
  await waitFor(() => tls.hits.includes('/'), 'request to the pinned https node');
  await waitFor(async () => (await win.locator('.pane-msg').count()) === 0, 'failure panel gone');
  let pins = JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].pins;
  assert.equal(pins.length, 1);
  assert.match(pins[0], /^[0-9a-f]{64}$/);

  await win.click('.group-head button');
  await win.fill('#f-port-controller', String(tlsPort2));
  await win.click('#f-save');
  await win.waitForFunction(() => !document.getElementById('dlg').open);
  await page(0).locator('.entry-main').click();
  await win.waitForSelector('.pane-msg h2');
  assert.match(await win.textContent('.pane-msg h2'), /Could not open Stub · Node Controller/);
  assert.equal(tls2.hits.length, 0);
  await win.click('text=Trust this certificate');
  await waitFor(() => tls2.hits.includes('/'), 'request to the second pinned certificate');
  pins = JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].pins;
  assert.equal(pins.length, 2);
  assert.notEqual(pins[0], pins[1]);
  await page(1).locator('.entry-main').click();
  await waitFor(async () => (await visible()).some((v) => v.url.startsWith('https://127.0.0.1:') && v.url.includes(String(tlsPort))), 'the first certificate is still trusted');

  await closeAll();
  await waitFor(async () => (await views(app)).length === 0, 'pages closed before the scheme checks');
  await page(2).locator('.entry-main').click();
  await showing(U('sysmon'));
  await waitFor(() => JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].schemes.sysmon === 'http', 'a plain page on an https node is learned as http');
  await win.waitForFunction(() => /SysMon on Stub answers on http, not https/.test(document.getElementById('notice').textContent));
  await closeAll();

  await win.click('.group-head button');
  await win.uncheck('#f-https');
  await win.fill('#f-port-nodemon', String(tlsPort2));
  await win.click('#f-save');
  await win.waitForFunction(() => !document.getElementById('dlg').open);
  await page(3).locator('.entry-main').click();
  await waitFor(async () => (await visible()).some((v) => v.url === `https://127.0.0.1:${tlsPort2}/`), 'a TLS page on an http node is learned as https and the trusted certificate is accepted');
  assert.equal(JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].schemes.nodemon, 'https');
  assert.equal(JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].schemes.sysmon, 'http');
  await closeAll();

  await win.click('.group-head button');
  assert.equal(await win.locator('#f-scheme-row').isVisible(), true);
  const remembered = await win.textContent('#f-schemes');
  assert.match(remembered, /SysMon on http/);
  assert.match(remembered, /Node Monitor on https/);
  await win.click('#f-scheme-clear');
  assert.equal(await win.locator('#f-scheme-row').isHidden(), true);
  await win.click('#f-save');
  await win.waitForFunction(() => !document.getElementById('dlg').open);
  assert.deepEqual(JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes[0].schemes, {});

  await win.click('.group-head button');
  await win.click('#f-delete');
  await win.waitForFunction(() => document.querySelectorAll('#pages .group').length === 0);
  assert.equal(JSON.parse(fs.readFileSync(nodesFile, 'utf8')).nodes.length, 0);
  assert.equal(JSON.parse(fs.readFileSync(splitsFile, 'utf8')).splits.length, 0);
  assert.equal(await openCount(), 0);
  assert.equal((await views(app)).length, 0);

  await app.close();
  for (const sv of [...servers, tlsSrv, tlsSrv2, extSrv]) sv.close();
  console.log('smoke ok');
}

main().then(() => process.exit(0), (e) => {
  console.error(e);
  process.exit(1);
});
