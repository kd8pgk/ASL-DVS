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

function snapshot(dir) {
  const out = {};
  for (const p of walk(dir)) {
    const st = fs.statSync(p);
    out[p.slice(dir.length)] = st.isDirectory() ? 'dir' : `${st.size}:${st.mtimeMs}`;
  }
  return out;
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

const panelLog = [];

function pngOf(bytes) {
  const zlib = require('node:zlib');
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(zlib.crc32(td) >>> 0);
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(1, 0);
  ihdr.writeUInt32BE(1, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const head = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr)]);
  const tail = Buffer.concat([chunk('IDAT', zlib.deflateSync(Buffer.from([0, 9, 99, 200]))), chunk('IEND', Buffer.alloc(0))]);
  const text = Buffer.concat([Buffer.from('Fill\0', 'latin1'), Buffer.alloc(Math.max(0, bytes - head.length - tail.length - 18), 120)]);
  return Buffer.concat([head, chunk('tEXt', text), tail]);
}

async function main() {
  const seenB = [];
  const seenA = [];
  const seenPurge = [];
  let portB = 0;
  const a = http.createServer((q, s) => {
    seenA.push({ url: q.url, cookie: q.headers.cookie || '' });
    if (q.url === '/file') {
      s.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Content-Disposition': 'attachment; filename="thing.bin"' });
      return s.end('secret bytes');
    }
    if (q.url === '/doc.pdf') {
      const body = Buffer.from('%PDF-1.4\n% test document\n');
      s.writeHead(200, { 'Content-Type': 'application/pdf', 'Content-Length': body.length });
      return s.end(body);
    }
    if (q.url === '/fake.pdf') {
      s.writeHead(200, { 'Content-Type': 'application/pdf' });
      return s.end('<!doctype html><script>alert(1)</script>');
    }
    if (q.url === '/talk.mp3') {
      s.writeHead(200, { 'Content-Type': 'audio/mpeg' });
      return s.end(Buffer.concat([Buffer.from('ID3'), Buffer.from([4, 0, 0, 0, 0, 0, 0]), Buffer.alloc(64)]));
    }
    if (q.url === '/big.mp4') {
      s.writeHead(200, { 'Content-Type': 'video/mp4' });
      s.write(Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from('ftypisom'), Buffer.alloc(52)]));
      let sent = 0;
      const more = () => {
        if (sent >= 3 * 1024 * 1024 || s.destroyed) return s.end();
        sent += 128 * 1024;
        s.write(Buffer.alloc(128 * 1024));
        setTimeout(more, 20);
      };
      s.on('error', () => {});
      return more();
    }
    if (q.url === '/popup-target') {
      s.writeHead(200, { 'Content-Type': 'text/html' });
      return s.end('<!doctype html><title>popup</title><p>popup</p>');
    }
    if (q.url === '/two') {
      s.writeHead(200, { 'Content-Type': 'text/html' });
      return s.end('<!doctype html><title>page two</title><p>two</p>');
    }
    if (q.url === '/fanout') {
      s.writeHead(200, { 'Content-Type': 'text/html' });
      const imgs = Array.from({ length: 15 }, (_, i) => `<img src="https://fanout-${i}.invalid/x.png">`).join('');
      return s.end(`<!doctype html><title>fanout</title>${imgs}`);
    }
    if (q.url === '/trap') {
      s.writeHead(200, { 'Content-Type': 'text/html' });
      return s.end('<!doctype html><title>trap</title><div style="position:absolute;left:0;top:0;width:400px;height:300px"></div><script>addEventListener("beforeunload",(e)=>{e.preventDefault();e.returnValue="stay"})</script>');
    }
    if (q.url === '/comic') {
      s.writeHead(200, { 'Content-Type': 'text/html', 'Content-Security-Policy': "img-src 'self'" });
      return s.end('<!doctype html><title>comic</title><style>img{display:block;width:500px;height:400px;margin-bottom:20px}</style><p id="t">story</p><img src="/panel/1.png"><img src="/panel/2.png"><img src="/panel/3.png">');
    }
    if (q.url.startsWith('/panel/')) {
      const name = q.url.slice(7).split('?')[0];
      const body = pngOf(12 * 1024);
      const range = /^bytes=(\d+)-$/.exec(String(q.headers.range || ''));
      const from = range ? Number(range[1]) : 0;
      panelLog.push(`${range ? 'range' : 'get'} ${name}${range ? `@${from}` : ''}`);
      const headers = { 'Content-Type': 'image/png', 'Accept-Ranges': 'bytes', ETag: '"p"', 'Content-Length': body.length - from, 'Cache-Control': 'no-store' };
      if (range) headers['Content-Range'] = `bytes ${from}-${body.length - 1}/${body.length}`;
      s.writeHead(range ? 206 : 200, headers);
      let at = from;
      const cut = name === '2.png' && !range ? 6000 : -1;
      const tick = () => {
        if (s.destroyed) return;
        if (cut >= 0 && at >= cut) return s.socket.destroy();
        const end = Math.min(body.length, at + 2048, cut >= 0 ? cut : Infinity);
        s.write(body.subarray(at, end));
        at = end;
        if (at >= body.length) {
          panelLog.push(`done ${name}`);
          return s.end();
        }
        return setTimeout(tick, 60);
      };
      return tick();
    }
    if (q.url === '/clip') {
      s.writeHead(200, { 'Content-Type': 'text/html' });
      return s.end('<!doctype html><title>clip</title><input id="i" style="position:absolute;left:10px;top:10px;width:300px"><iframe id="f" src="/two" style="position:absolute;top:60px"></iframe>');
    }
    if (q.url === '/printtrap') {
      s.writeHead(200, { 'Content-Type': 'text/html' });
      return s.end('<!doctype html><title>printtrap</title><script>setTimeout(()=>{for(;;)window.print()},300)</script>');
    }
    if (q.url === '/busy') {
      s.writeHead(200, { 'Content-Type': 'text/html' });
      return s.end('<!doctype html><title>busy</title><script>const t=Date.now()+26000;while(Date.now()<t){}</script>');
    }
    s.writeHead(200, { 'Content-Type': 'text/html', 'Set-Cookie': 'fp=1; Path=/' });
    return s.end(`<!doctype html><title>page one</title><p>one</p>
<img src="http://localhost:${portB}/pixel.gif?n=${Date.now()}" width="1" height="1">
<a id="newtab" href="/two" target="_blank" style="display:block;position:absolute;left:20px;top:80px;width:200px;height:40px;background:#333;color:#fff">open in new tab</a>`);
  });
  const b = http.createServer((q, s) => {
    seenB.push({ url: q.url, cookie: q.headers.cookie || '' });
    s.writeHead(200, { 'Content-Type': 'image/gif', 'Set-Cookie': 'tp=1; Path=/; SameSite=None; Secure' });
    s.end(Buffer.from('R0lGODlhAQABAAAAACw=', 'base64'));
  });
  const plain = http.createServer((q, s) => {
    s.writeHead(200, { 'Content-Type': 'text/html' });
    s.end('<!doctype html><title>plain only</title><p>plain</p>');
  });
  const purge = http.createServer((q, s) => {
    seenPurge.push({ url: q.url, cookie: q.headers.cookie || '' });
    s.writeHead(200, { 'Content-Type': 'text/html', 'Set-Cookie': 'keep=1; Path=/' });
    s.end('<!doctype html><title>purge test</title><p>purge</p>');
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
  const portPurge = await listen(purge);

  const ramBase = path.join(tmp, 'ram');
  const realHome = path.join(tmp, 'home');
  const openLog = path.join(tmp, 'opened.log');
  fs.mkdirSync(ramBase);
  fs.mkdirSync(realHome);
  const launch = (extra = [], envExtra = {}) => _electron.launch({
    executablePath: require('electron'),
    args: [root, '--no-sandbox', '--host-resolver-rules=MAP pub.test 127.0.0.1,MAP other.test 127.0.0.1,MAP wd.test 127.0.0.1', ...extra],
    env: { ...noProxy(process.env), NULLBROWSER_RAM_BASE: ramBase, NULLBROWSER_OPEN_LOG: openLog, HOME: realHome, XDG_CONFIG_HOME: path.join(realHome, '.config'), XDG_CACHE_HOME: path.join(realHome, '.cache'), ...envExtra },
  });
  const warm = await launch();
  await waitFor(() => warm.windows().some((w) => w.url().endsWith('/ui/index.html')), 'the warm-up window');
  await sleep(1500);
  await warm.close();
  await waitFor(() => fs.readdirSync(ramBase).length === 0, 'the warm-up RAM folder is removed');
  const homeBefore = snapshot(realHome);
  const app = await launch([], { NULLBROWSER_MAX_BYTES: String(1024 * 1024) });
  await waitFor(() => app.windows().some((w) => w.url().endsWith('/ui/index.html')), 'the toolbar window');
  const win = app.windows().find((w) => w.url().endsWith('/ui/index.html'));
  await win.waitForLoadState('domcontentloaded');
  const pageEval = (code, gesture = false) => app.evaluate(({ BrowserWindow }, [c, g]) => BrowserWindow.getAllWindows().find((w) => w.contentView && w.contentView.children.length > 0).contentView.children[0].webContents.executeJavaScript(c, g), [code, gesture]);
  const pageUrl = () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find((w) => w.contentView && w.contentView.children.length > 0).contentView.children[0].webContents.getURL());
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

  const spell = await app.evaluate(({ session: s2, BrowserWindow }) => {
    const view = BrowserWindow.getAllWindows().find((w) => w.contentView && w.contentView.children.length > 0).contentView.children[0];
    return { default: s2.defaultSession.getSpellCheckerLanguages(), page: view.webContents.session.getSpellCheckerLanguages() };
  });
  assert.deepEqual(spell.default, [], 'no dictionary is ever fetched for the default session');
  assert.deepEqual(spell.page, [], 'no dictionary is ever fetched for the page session');

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

  const windows = () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed()).map((w) => ({ visible: w.isVisible(), url: w.webContents.getURL() })));
  assert.equal(await pageEval(`(() => { const w = window.open('http://127.0.0.1:${portA}/popup-target'); return w !== null && typeof w === 'object'; })()`), true, 'a script pop-up gets a window back');
  await win.waitForSelector('#popbar:not([hidden])');
  assert.match(await win.textContent('#pop-text'), /A pop-up from 127\.0\.0\.1 was blocked/);
  const during = await windows();
  assert.equal(during.filter((w) => w.visible).length, 1, 'the dropped pop-up is never shown');
  await waitFor(async () => (await windows()).length === 1, 'the dropped pop-up is closed after a few seconds', 8000);
  assert.equal(seenA.some((r) => r.url === '/popup-target'), false, 'the dropped pop-up loads nothing');
  assert.equal(await pageUrl(), `http://127.0.0.1:${portA}/`);

  await app.evaluate(({ BrowserWindow }) => {
    const wc = BrowserWindow.getAllWindows().find((w) => w.contentView && w.contentView.children.length > 0).contentView.children[0].webContents;
    wc.focus();
    wc.sendInputEvent({ type: 'mouseDown', x: 60, y: 100, button: 'left', clickCount: 1 });
    wc.sendInputEvent({ type: 'mouseUp', x: 60, y: 100, button: 'left', clickCount: 1 });
  });
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/two`, 'a clicked new-tab link opens in the same page');
  assert.equal(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 1);

  await go(`http://127.0.0.1:${portA}/trap`);
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/trap`, 'the leave-site trap page');
  await sleep(500);
  await app.evaluate(({ BrowserWindow }) => {
    const wc = BrowserWindow.getAllWindows().find((w) => w.contentView && w.contentView.children.length > 0).contentView.children[0].webContents;
    wc.sendInputEvent({ type: 'mouseDown', x: 100, y: 100, button: 'left', clickCount: 1 });
    wc.sendInputEvent({ type: 'mouseUp', x: 100, y: 100, button: 'left', clickCount: 1 });
  });
  await sleep(500);
  await go(`http://127.0.0.1:${portA}/two`);
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/two`, 'a page that asks to stay cannot hold you');
  await win.click('#line');
  await win.waitForSelector('#lineset:not([hidden])');
  await win.click('#ls-mode');
  assert.equal(await win.textContent('#ls-mode'), 'Slow: On');
  await go(`http://127.0.0.1:${portA}/comic`);
  await waitFor(() => panelLog.filter((l) => l.startsWith('done')).length === 3, 'the comic panels load', 30000);
  await waitFor(async () => (await pageEval("Array.from(document.images).every(function(i){return i.complete&&i.naturalWidth>0})")) === true, 'every panel shows on the page', 10000);
  assert.deepEqual(panelLog, ['get 1.png', 'done 1.png', 'get 2.png', 'range 2.png@6000', 'done 2.png', 'get 3.png', 'done 3.png'], 'panels load one at a time, in order, and a cut-off panel resumes where it stopped');
  panelLog.length = 0;
  await win.click('#ls-images');
  assert.equal(await win.textContent('#ls-images'), 'Images: Off');
  await go(`http://127.0.0.1:${portA}/two`);
  await go(`http://127.0.0.1:${portA}/comic`);
  await waitFor(async () => (await pageEval("(document.getElementById('t')||{}).textContent||''")) === 'story', 'the text-only page');
  await sleep(1000);
  assert.deepEqual(panelLog, [], 'with images off no image is fetched');
  await go(`http://127.0.0.1:${portA}/two`);
  await win.click('#ls-images');
  await win.click('#ls-mode');
  await win.click('#ls-mode');
  assert.equal(await win.textContent('#ls-mode'), 'Slow: Auto');
  await win.click('#ls-close');
  await win.waitForSelector('#lineset', { state: 'hidden' });

  const clip = (text) => app.evaluate(({ clipboard }, t) => (t === undefined ? clipboard.readText() : clipboard.writeText(t)), text);
  await go(`http://127.0.0.1:${portA}/clip`);
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/clip`, 'the clipboard page');
  await sleep(800);
  const writes = {
    exec: "(function(){var a=document.createElement('textarea');a.value='PWNED';document.body.appendChild(a);a.select();var r=document.execCommand('copy');a.remove();return r})()",
    event: "(function(){document.addEventListener('copy',function(e){e.clipboardData.setData('text/plain','PWNED');e.preventDefault()},{once:true});document.execCommand('copy');return 1})()",
    async: "navigator.clipboard.writeText('PWNED').then(function(){return 'ok'},function(e){return e.name})",
    frame: "(function(){var d=document.getElementById('f').contentDocument;var a=d.createElement('textarea');a.value='PWNED';d.body.appendChild(a);a.select();return d.execCommand('copy')})()",
    fresh: "(function(){var f=document.createElement('iframe');document.body.appendChild(f);var ex=f.contentWindow.Document.prototype.execCommand;var a=document.createElement('textarea');a.value='PWNED';document.body.appendChild(a);a.select();return ex.call(document,'copy')})()",
  };
  for (const [name, code] of Object.entries(writes)) {
    await clip('SENTINEL');
    await pageEval(code, true).catch(() => {});
    await sleep(200);
    assert.equal(await clip(), 'SENTINEL', `a page cannot write the clipboard (${name})`);
  }
  assert.match(String(await pageEval("navigator.clipboard.readText().then(function(){return 'read'},function(e){return e.name})", true)), /NotAllowedError/, 'a page cannot read the clipboard');
  await clip('PASTED');
  await pageEval("document.getElementById('i').focus(); true", true);
  const keyTo = (target, mods, keyCode) => app.evaluate(({ BrowserWindow }, [t, m, k]) => {
    const w = BrowserWindow.getAllWindows().find((x) => x.contentView && x.contentView.children.length > 0);
    const wc = t === 'page' ? w.contentView.children[0].webContents : w.webContents;
    wc.focus();
    wc.sendInputEvent({ type: 'keyDown', keyCode: k, modifiers: m });
    wc.sendInputEvent({ type: 'char', keyCode: k, modifiers: m });
    wc.sendInputEvent({ type: 'keyUp', keyCode: k, modifiers: m });
  }, [target, mods, keyCode]);
  await keyTo('page', ['control'], 'V');
  await keyTo('page', ['shift'], 'Insert');
  await sleep(300);
  assert.equal(await pageEval("document.getElementById('i').value"), '', 'Ctrl+V and Shift+Insert paste nothing into a page');
  await pageEval("(function(){var i=document.getElementById('i');i.value='SECRET';i.focus();i.select();return 1})()", true);
  await clip('SENTINEL');
  await keyTo('page', ['control'], 'C');
  await keyTo('page', ['control'], 'X');
  await keyTo('page', ['control'], 'Insert');
  await keyTo('page', ['shift'], 'Delete');
  await sleep(300);
  assert.equal(await clip(), 'SENTINEL', 'copy and cut keys put nothing on the clipboard');
  await win.fill('#addr', 'typed');
  await win.focus('#addr');
  await clip('PASTED');
  await keyTo('shell', ['control'], 'V');
  await keyTo('shell', ['shift'], 'Insert');
  await sleep(300);
  assert.equal(await win.inputValue('#addr'), 'typed', 'nothing pastes into the address bar');
  await win.evaluate(() => document.getElementById('addr').select());
  await clip('SENTINEL');
  await keyTo('shell', ['control'], 'C');
  await keyTo('shell', ['control'], 'X');
  await sleep(300);
  assert.equal(await clip(), 'SENTINEL', 'nothing is copied out of the address bar');
  assert.equal(await win.inputValue('#addr'), 'typed', 'cut does not remove the address text either');
  await win.press('#addr', 'Escape');

  await go(`http://127.0.0.1:${portA}/printtrap`);
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/printtrap`, 'the print trap page');
  await sleep(1500);
  await go(`http://127.0.0.1:${portA}/two`);
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/two`, 'a page stuck in a print dialog is closed when you leave it', 10000);
  assert.equal(await win.evaluate(() => document.getElementById('msg').hidden), true, 'leaving a stuck page shows no error');

  await go(`http://127.0.0.1:${portA}/file`);
  await win.waitForFunction(() => /Downloads are off/.test(document.getElementById('notice').textContent));

  const ramFiles = () => {
    const d = fs.readdirSync(ramBase).find((n) => n.startsWith('null-browser-'));
    return d ? fs.readdirSync(path.join(ramBase, d, 'files')) : [];
  };
  await go(`http://127.0.0.1:${portA}/two`);
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/two`, 'back on a page');
  await go(`http://127.0.0.1:${portA}/doc.pdf`);
  await win.waitForSelector('#ask:not([hidden])');
  assert.match(await win.textContent('#ask-text'), /^Open doc\.pdf \(PDF, \d+ bytes\) in your PDF viewer\?/);
  assert.equal(await pageUrl(), `http://127.0.0.1:${portA}/two`, 'the page stays where it was');
  await win.click('#ask-cancel');
  await win.waitForSelector('#ask', { state: 'hidden' });
  await sleep(300);
  assert.deepEqual(ramFiles(), [], 'a cancelled file is not kept');
  assert.equal(fs.existsSync(openLog), false, 'a cancelled file is not opened');
  await go(`http://127.0.0.1:${portA}/doc.pdf`);
  await win.waitForSelector('#ask:not([hidden])');
  await win.click('#ask-open');
  await waitFor(() => fs.existsSync(openLog), 'the PDF is handed to the system app');
  const opened = fs.readFileSync(openLog, 'utf8').trim().split('\n');
  assert.equal(opened.length, 1);
  assert.ok(opened[0].startsWith(ramBase), 'the handed-off file is in the RAM folder');
  assert.match(fs.readFileSync(opened[0], 'utf8'), /^%PDF-1\.4/);
  await go(`http://127.0.0.1:${portA}/fake.pdf`);
  await win.waitForSelector('#ask:not([hidden])');
  await win.click('#ask-open');
  await win.waitForFunction(() => /fake\.pdf is not really a PDF/.test(document.getElementById('notice').textContent));
  assert.equal(fs.readFileSync(openLog, 'utf8').trim().split('\n').length, 1, 'a file that is not what it claims is not opened');
  assert.equal(ramFiles().some((n) => n.endsWith('fake.pdf')), false, 'and is not kept');
  await go(`http://127.0.0.1:${portA}/talk.mp3`);
  await win.waitForSelector('#ask:not([hidden])');
  assert.match(await win.textContent('#ask-text'), /talk\.mp3 \(audio(, [^)]*)?\) in your music player/);
  await win.click('#ask-open');
  await waitFor(() => fs.readFileSync(openLog, 'utf8').trim().split('\n').length === 2, 'the audio file is handed on');
  await go(`http://127.0.0.1:${portA}/big.mp4`);
  await win.waitForSelector('#ask:not([hidden])');
  await win.click('#ask-open');
  await win.waitForFunction(() => /big\.mp4 is too big to open from memory/.test(document.getElementById('notice').textContent));
  await sleep(300);
  assert.equal(fs.readFileSync(openLog, 'utf8').trim().split('\n').length, 2, 'a file that grows past the cap with no size given is not opened');
  assert.equal(ramFiles().some((n) => n.endsWith('big.mp4')), false, 'and is not kept');

  await go(`http://127.0.0.1:${portA}/`);
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/`, 'page one again');
  await pageEval(`window.open('http://127.0.0.1:${portA}/popup-target'); true`);
  await win.waitForSelector('#popbar:not([hidden])');
  await win.click('#pop-allow');
  await win.waitForFunction(() => /allowed for 127\.0\.0\.1 until Null Browser closes/.test(document.getElementById('notice').textContent));
  const before = seenA.filter((r) => r.url === '/popup-target').length;
  await pageEval(`window.open('http://127.0.0.1:${portA}/popup-target', 'login', 'width=500,height=600'); true`);
  await waitFor(async () => (await windows()).some((w) => w.visible && w.url.endsWith('/popup-target')), 'an allowed pop-up opens for real');
  assert.equal(seenA.filter((r) => r.url === '/popup-target').length, before + 1);
  await app.evaluate(({ BrowserWindow }) => { for (const w of BrowserWindow.getAllWindows()) if (w.webContents.getURL().endsWith('/popup-target')) w.destroy(); });
  const bBefore = seenB.length;
  await go(`http://127.0.0.1:${portA}/two`);
  await go(`http://127.0.0.1:${portA}/`);
  await waitFor(() => seenB.length >= bBefore + 1, 'the pixel again');
  await go(`http://127.0.0.1:${portA}/two`);
  await go(`http://127.0.0.1:${portA}/`);
  await waitFor(() => seenB.length >= bBefore + 2, 'the pixel once more');
  assert.match(seenB[seenB.length - 1].cookie, /tp=1/, 'on an allowed site third-party sign-in cookies are kept for the session');

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

  const bmFile = path.join(tmp, 'bookmarks.html');
  fs.writeFileSync(bmFile, `<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
<DT><A HREF="http://127.0.0.1:${portA}/">Page one</A>
<DT><A HREF="javascript:alert(1)">evil</A>
</DL><p>`);
  await app.evaluate(({ dialog }, file) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [file] });
  }, bmFile);
  await win.click('#bm');
  await win.waitForSelector('#bm-panel:not([hidden])');
  await win.click('#bm-import');
  await win.waitForFunction(() => /1 bookmark imported/.test(document.getElementById('notice').textContent));
  await win.waitForSelector('#bm-list li');
  assert.equal(await win.locator('#bm-list li').count(), 1, 'only the http(s) link was imported');
  assert.match(await win.textContent('#bm'), /★ 1/);

  await app.evaluate(({ dialog }, file) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [file] });
  }, bmFile);
  await win.click('#bm-import');
  await win.waitForFunction(() => /already imported/.test(document.getElementById('notice').textContent));

  await win.click('.bm-link');
  await waitFor(async () => (await pageUrl()) === `http://127.0.0.1:${portA}/`, 'clicking a bookmark opens it');
  assert.equal(await win.locator('#bm-panel').isHidden(), true, 'the panel closes after a bookmark is opened');

  await win.click('#bm');
  await win.click('.bm-remove');
  await win.waitForSelector('#bm-empty:not([hidden])');
  assert.match(await win.textContent('#bm'), /☆/, 'the bookmark star shows empty once the list is empty');

  assert.match(await win.textContent('#fastjs'), /JIT: Off/);
  await win.click('#fastjs');
  await win.waitForSelector('#jsbar:not([hidden])');
  assert.match(await win.textContent('#jsbar-text'), /Turn on faster JavaScript/);
  await win.click('#jsbar-no');
  await win.waitForFunction(() => document.getElementById('jsbar').hidden);

  await go(`http://pub.test:${portPurge}/`);
  await waitFor(async () => (await pageUrl()) === `http://pub.test:${portPurge}/`, 'the purge-test page (first visit)');
  await waitFor(() => seenPurge.length >= 1, 'the first request');
  assert.equal(seenPurge[0].cookie, '', 'no cookie on the very first request');
  await go(`http://pub.test:${portPurge}/`);
  await waitFor(() => seenPurge.length >= 2, 'a second request to the same site');
  assert.match(seenPurge[1].cookie, /keep=1/, 'staying on the same site keeps its cookie');
  await go(`http://other.test:${portPurge}/`);
  await win.waitForFunction(() => /no secure version/.test(document.getElementById('msg-title').textContent));
  await win.click('#msg-main');
  await waitFor(async () => (await pageUrl()) === `http://other.test:${portPurge}/`, 'a different, unallowed site');
  await go(`http://pub.test:${portPurge}/`);
  await waitFor(() => seenPurge.length >= 4, 'back on the first site');
  assert.equal(seenPurge[3].cookie, '', 'leaving for a different, unallowed site purges its cookie');

  await pageEval(`window.open('http://pub.test:${portPurge}/popup'); true`);
  await win.waitForSelector('#popbar:not([hidden])');
  await win.click('#pop-allow');
  await win.waitForFunction(() => /allowed for pub\.test until Null Browser closes/.test(document.getElementById('notice').textContent));
  await go(`http://other.test:${portPurge}/`);
  await waitFor(async () => (await pageUrl()) === `http://other.test:${portPurge}/`, 'leaving the now-allowed site');
  await go(`http://pub.test:${portPurge}/`);
  await waitFor(() => seenPurge.length >= 6, 'back on the allowed site');
  assert.match(seenPurge[5].cookie, /keep=1/, 'an allowed site keeps its cookie across leaving and returning');

  await go(`http://wd.test:${portA}/`);
  await win.waitForFunction(() => /no secure version/.test(document.getElementById('msg-title').textContent));
  await win.click('#msg-main');
  await waitFor(async () => (await pageUrl()) === `http://wd.test:${portA}/`, 'the watchdog test site, authorized for http');

  await go(`http://wd.test:${portA}/fake.pdf`);
  await win.waitForSelector('#ask:not([hidden])');
  await win.click('#ask-open');
  await win.waitForFunction(() => /is not really a PDF/.test(document.getElementById('notice').textContent));
  await go(`http://wd.test:${portA}/fake.pdf`);
  await win.waitForSelector('#ask:not([hidden])');
  await win.click('#ask-open');
  await win.waitForFunction(() => /Watchdog: wd\.test sent disguised files repeatedly/.test(document.getElementById('notice').textContent));

  await pageEval(`for (let i = 0; i < 6; i += 1) window.open('http://wd.test:${portA}/popup-' + i); true`);
  await win.waitForFunction(() => /Watchdog: wd\.test kept opening pop-ups after being capped/.test(document.getElementById('notice').textContent));

  await go(`http://wd.test:${portA}/fanout`);
  await win.waitForFunction(() => /Watchdog: wd\.test contacted many different hosts at once/.test(document.getElementById('notice').textContent), undefined, { timeout: 15000 });

  await go(`http://wd.test:${portA}/busy`);
  await win.waitForFunction(() => /Watchdog: wd\.test used heavy CPU while idle/.test(document.getElementById('notice').textContent), undefined, { timeout: 30000 });

  await go(`http://wd.test:${portA}/`);
  await waitFor(async () => (await pageUrl()) === `http://wd.test:${portA}/`, 'back on the watchdog site');
  const crashOnce = () => app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find((w) => w.contentView && w.contentView.children.length > 0).contentView.children[0].webContents.forcefullyCrashRenderer());
  await crashOnce();
  await win.waitForFunction(() => /The page stopped working/.test(document.getElementById('msg-text') ? document.getElementById('msg-text').textContent : ''));
  await win.click('#msg-retry');
  await waitFor(async () => (await pageUrl()) === `http://wd.test:${portA}/`, 'back up after the first crash');
  await crashOnce();
  await win.waitForFunction(() => /Watchdog: wd\.test crashed repeatedly/.test(document.getElementById('notice').textContent));

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
  assert.deepEqual(snapshot(realHome), homeBefore, 'nothing was added to or changed in the real home folder');

  const preDir = path.join(ramBase, 'null-browser-0-999999-prelaunch');
  fs.mkdirSync(preDir, { mode: 0o700 });
  fs.writeFileSync(path.join(preDir, 'pid'), String(process.pid));
  for (const sub of ['home', 'config', 'cache', 'data', 'state', 'chromium', 'session', 'temp', 'files']) fs.mkdirSync(path.join(preDir, sub), { mode: 0o700 });
  const adopted = await launch([], { NULLBROWSER_PRELAUNCH_DIR: preDir });
  await waitFor(() => adopted.windows().some((w) => w.url().endsWith('/ui/index.html')), 'the adopted-folder window');
  await waitFor(() => fs.readdirSync(ramBase).filter((n) => n.startsWith('null-browser-')).length === 1, 'no second RAM folder is created alongside the adopted one');
  assert.deepEqual(fs.readdirSync(ramBase).filter((n) => n.startsWith('null-browser-')), ['null-browser-0-999999-prelaunch']);
  await adopted.close();
  await waitFor(() => !fs.existsSync(preDir), 'the adopted folder is removed on quit too');

  const fast = await launch(['--nb-fast-js']);
  await waitFor(() => fast.windows().some((w) => w.url().endsWith('/ui/index.html')), 'the faster-JavaScript window');
  const fastWin = fast.windows().find((w) => w.url().endsWith('/ui/index.html'));
  await fastWin.waitForLoadState('domcontentloaded');
  await fastWin.waitForFunction(() => window.nb !== undefined);
  const fastState = await fastWin.evaluate(() => window.nb.state());
  assert.equal(fastState.fastJs, true, 'the marker switches JIT back on for this run');
  assert.match(await fastWin.textContent('#fastjs'), /JIT: On/);
  assert.equal(await fast.evaluate(({ app: a2 }) => a2.commandLine.getSwitchValue('js-flags')), '', 'no --jitless is passed this run');
  await fast.close();
  await waitFor(() => fs.readdirSync(ramBase).length === 0, 'the faster-JavaScript run also cleans up its RAM folder');

  for (const sv of [a, b, plain, tls, purge]) sv.close();
  console.log('smoke ok');
}

process.on('unhandledRejection', (e) => {
  if (/Page\.handleJavaScriptDialog\): No dialog is showing/.test(String(e && e.message))) return;
  console.error(e);
  process.exit(1);
});

main().then(() => process.exit(0), (e) => {
  console.error(e);
  process.exit(1);
});
