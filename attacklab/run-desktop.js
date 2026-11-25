#!/usr/bin/env node
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { _electron } = require('playwright');
const { start } = require('./server');

const root = path.join(__dirname, '..', 'nullbrowser');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = Number(process.env.ATTACKLAB_PORT || 18188);
const base = `http://127.0.0.1:${PORT}`;

function noProxy(env) {
  const out = {};
  for (const [k, v] of Object.entries(env)) if (!/^(https?|all|no)_proxy$/i.test(k)) out[k] = v;
  out.NO_PROXY = '*';
  return out;
}

async function waitFor(fn, ms) {
  const until = Date.now() + ms;
  for (;;) {
    let ok = false;
    try {
      ok = await fn();
    } catch {
      ok = false;
    }
    if (ok) return true;
    if (Date.now() > until) return false;
    await sleep(200);
  }
}

async function main() {
  const { lab, server, secure, httpsPort } = start({ port: PORT, host: '127.0.0.1' });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'attacklab-run-'));
  const ram = path.join(tmp, 'ram');
  const openLog = path.join(tmp, 'opened.log');
  fs.mkdirSync(ram);
  fs.writeFileSync(openLog, '');
  const launch = () => _electron.launch({
    executablePath: require(path.join(root, 'node_modules', 'electron')),
    args: [root, '--no-sandbox'],
    env: { ...noProxy(process.env), NULLBROWSER_RAM_BASE: ram, NULLBROWSER_OPEN_LOG: openLog },
  });
  let app = await launch();
  let win = null;
  const attach = async () => {
    await waitFor(() => app.windows().some((w) => w.url().endsWith('/ui/index.html')), 15000);
    win = app.windows().find((w) => w.url().endsWith('/ui/index.html'));
    await win.waitForLoadState('domcontentloaded');
  };
  await attach();
  const go = async (url) => {
    await win.fill('#addr', url);
    await win.press('#addr', 'Enter');
  };
  const notice = () => win.evaluate(() => document.getElementById('notice').textContent);
  const pageEval = (code) => app.evaluate(({ BrowserWindow }, c) => BrowserWindow.getAllWindows().find((w) => w.contentView && w.contentView.children.length > 0).contentView.children[0].webContents.executeJavaScript(c, true), code);
  const opened = () => fs.readFileSync(openLog, 'utf8').trim().split('\n').filter(Boolean);
  const mark = (t, s, note) => {
    require('node:http').request({ host: '127.0.0.1', port: PORT, path: '/mark', method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }).end(`t=${t}&s=${s}`);
    notes[t] = note;
  };
  const notes = {};
  const step = (s) => process.stdout.write(`- ${s}\n`);

  step('pop-up flood');
  await go(`${base}/t/popups`);
  await sleep(6000);

  step('permission grab');
  await go(`${base}/t/permissions`);
  await sleep(7000);

  step('dangerous link types');
  await go(`${base}/t/schemes`);
  await sleep(8000);

  step('ClickFix copy trick');
  await go(`${base}/t/clickfix`);
  await sleep(1500);
  await pageEval("document.getElementById('go').click(); true");
  await sleep(1000);

  step('disguised files');
  const tryFile = async (name) => {
    const before = opened().length;
    await go(`${base}/dl/${name}`);
    let early = '';
    await waitFor(async () => {
      if (await win.evaluate(() => !document.getElementById('ask').hidden)) return true;
      early = await notice();
      return Boolean(early);
    }, 6000);
    const asked = await win.evaluate(() => !document.getElementById('ask').hidden);
    if (!asked) return { asked, notice: early, opened: opened().length > before, file: '' };
    await win.click('#ask-open');
    await waitFor(async () => opened().length > before || Boolean(await notice()), 6000);
    return { asked, notice: await notice(), opened: opened().length > before, file: opened().slice(-1)[0] || '' };
  };
  const results = {};
  for (const f of ['real.pdf', 'invoice.pdf', 'song.mp3', 'movie.mp4', 'page.pdf', 'eicar.pdf', 'setup.exe']) results[f] = await tryFile(f);
  const fakes = ['invoice.pdf', 'song.mp3', 'movie.mp4', 'page.pdf', 'eicar.pdf'];
  const fakeOpened = fakes.filter((f) => results[f].opened);
  const realOk = results['real.pdf'].opened;
  const exeOk = !results['setup.exe'].opened && /Downloads are off/.test(results['setup.exe'].notice);
  mark('disguised', fakeOpened.length === 0 && realOk && exeOk ? 'pass' : 'FAIL',
    `real opened=${realOk}; fakes opened=[${fakeOpened.join(',')}]; exe refused=${exeOk} (asked=${results['setup.exe'].asked}, notice="${results['setup.exe'].notice}")`);

  step('polyglot PDF');
  const poly = await tryFile('polyglot.pdf');
  mark('polyglot', poly.opened ? 'pass' : 'FAIL', poly.opened ? 'passed the type check, as expected (known limit)' : 'refused (unexpected)');

  step('path in the file name');
  const trav = await tryFile('trav');
  const safe = trav.opened && !trav.file.includes('..') && path.dirname(trav.file).startsWith(ram);
  mark('traversal', safe ? 'pass' : 'FAIL', `saved as ${trav.file ? path.basename(trav.file) : '(nothing)'}`);

  step('oversize file (size declared)');
  await go(`${base}/dl/huge.mp4`);
  await sleep(4000);
  const hugeNotice = await notice();

  step('oversize file (size hidden, 600 MB)');
  await go(`${base}/dl/endless.mp4`);
  if (await waitFor(async () => win.evaluate(() => !document.getElementById('ask').hidden), 8000)) await win.click('#ask-open');
  await waitFor(() => lab.verdict('size-stream').status !== 'pending' && lab.verdict('size-stream').status !== 'not run', 120000);
  await sleep(2000);
  const ramAfter = (() => {
    let total = 0;
    const walk = (d) => {
      for (const n of fs.readdirSync(d)) {
        const p = path.join(d, n);
        let st;
        try {
          st = fs.lstatSync(p);
        } catch {
          continue;
        }
        if (st.isDirectory()) walk(p);
        else if (st.isFile()) total += st.size;
      }
    };
    walk(ram);
    return total;
  })();

  step('redirect loop');
  await go(`${base}/dl/loop.pdf?n=1`);
  await sleep(5000);

  step('bad certificate');
  if (httpsPort) {
    await go(`https://127.0.0.1:${httpsPort}/t/cert-ok`);
    await sleep(3000);
    const shown = await win.evaluate(() => !document.getElementById('msg').hidden && /certificate is not valid/.test(document.getElementById('msg-title').textContent));
    const trustable = await win.evaluate(() => !document.getElementById('msg-main').hidden);
    mark('certificate', shown ? 'pass' : 'FAIL', `refused=${shown}; trust-for-session offered (private host)=${trustable}`);
  }

  step('fake lock screen');
  await go(`${base}/t/fullscreen`);
  await sleep(1500);
  await pageEval("document.getElementById('go').click(); true");
  await sleep(1500);
  const full = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isFullScreen());
  await go(`${base}/`);
  const escaped = await waitFor(async () => (await pageEval('location.pathname')) === '/', 6000);
  mark('fullscreen', !full && escaped ? 'pass' : 'FAIL', `window went full screen=${full}; address bar still got us out=${escaped}`);

  step('alert loop');
  await go(`${base}/t/alerts`);
  await sleep(1500);
  pageEval("document.getElementById('go').click(); true").catch(() => {});
  await sleep(3000);
  await go(`${base}/`);
  const alive = await waitFor(async () => (await pageEval('location.pathname')) === '/', 8000);
  mark('alerts', alive ? 'pass' : 'FAIL', `could leave the page=${alive}`);

  step('memory bomb');
  await go(`${base}/t/crash`);
  await sleep(1500);
  pageEval("document.getElementById('go').click(); true").catch(() => {});
  const died = await waitFor(async () => win.evaluate(() => /stopped working/.test(document.getElementById('msg-text').textContent || '') || /Watchdog/.test(document.getElementById('notice').textContent)), 60000);
  await go(`${base}/`);
  const back = await waitFor(async () => (await pageEval('location.pathname')) === '/', 10000);
  mark('crash', back ? 'pass' : 'FAIL', `page died or was flagged=${died}; browser usable after=${back}`);

  step('hidden miner (40 s busy loop)');
  await go(`${base}/t/cpu`);
  const flagged = await waitFor(async () => /Watchdog: .*heavy CPU/.test(await notice()), 45000);
  mark('cpu', flagged ? 'pass' : 'FAIL', `watchdog flagged it=${flagged}`);
  await sleep(1000);

  step('survives a restart? (set, quit, relaunch, check)');
  await go(`${base}/t/persist-set`);
  await sleep(2500);
  await app.close();
  app = await launch();
  await attach();
  await go(`${base}/t/persist-check`);
  await sleep(3000);
  await app.close();

  await sleep(500);
  const out = {};
  for (const id of Object.keys(JSON.parse(JSON.stringify(require('./server').TESTS.reduce((a, t) => ({ ...a, [t.id]: 1 }), {}))))) {
    out[id] = { ...lab.verdict(id), ...(notes[id] ? { note: notes[id] } : {}) };
  }
  out['size-declared'].notice = hugeNotice;
  out['size-stream'].ramFolderBytesAfter = ramAfter;
  process.stdout.write(`\n${JSON.stringify(out, null, 2)}\n`);
  server.close();
  if (secure) secure.close();
  fs.rmSync(tmp, { recursive: true, force: true });
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
