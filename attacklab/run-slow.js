#!/usr/bin/env node
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { _electron } = require('playwright');
const { start } = require('./server');
const { SLOW_TESTS } = require('./slowlab');

const root = path.join(__dirname, '..', 'nullbrowser');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = Number(process.env.ATTACKLAB_PORT || 18288);
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
      ok = await Promise.race([fn(), sleep(3000).then(() => false)]);
    } catch {
      ok = false;
    }
    if (ok) return true;
    if (Date.now() > until) return false;
    await sleep(250);
  }
}

async function main() {
  const { lab, server, secure } = start({ port: PORT, host: '127.0.0.1', rate: Number(process.env.ATTACKLAB_RATE || 16), panel: Number(process.env.ATTACKLAB_PANEL || 16) });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'slowlab-run-'));
  const ram = path.join(tmp, 'ram');
  fs.mkdirSync(ram);
  const app = await _electron.launch({
    executablePath: require(path.join(root, 'node_modules', 'electron')),
    args: [root, '--no-sandbox'],
    env: { ...noProxy(process.env), NULLBROWSER_RAM_BASE: ram },
  });
  await waitFor(() => app.windows().some((w) => w.url().endsWith('/ui/index.html')), 15000);
  const win = app.windows().find((w) => w.url().endsWith('/ui/index.html'));
  await win.waitForLoadState('domcontentloaded');
  const go = async (url) => {
    await win.fill('#addr', url);
    await win.press('#addr', 'Enter');
  };
  const pageEval = (code) => app.evaluate(({ BrowserWindow }, c) => BrowserWindow.getAllWindows().find((w) => w.contentView && w.contentView.children.length > 0).contentView.children[0].webContents.mainFrame.executeJavaScript(c, true), code);
  const step = (s) => process.stdout.write(`- ${s}\n`);
  const settled = (id) => () => !['pending', 'not run'].includes(lab.verdict(id).status);
  const text = (id) => win.evaluate((i) => document.getElementById(i).textContent, id);

  step('Slow: On');
  await win.click('#line');
  await win.waitForSelector('#lineset:not([hidden])');
  for (let i = 0; i < 3 && (await text('ls-mode')) !== 'Slow: On'; i += 1) {
    await win.click('#ls-mode');
    await sleep(300);
  }
  const statusSeen = [];

  step('comic in viewing order, with panel 4 cut off halfway');
  await go(`${base}/t/slow-order`);
  const watch = setInterval(async () => {
    try {
      const t = await text('linebar-text');
      if (t && statusSeen[statusSeen.length - 1] !== t) statusSeen.push(t);
    } catch {}
  }, 500);
  await waitFor(settled('slow-order'), 180000);
  await waitFor(settled('slow-resume'), 60000);

  step('scroll to panel 7 while panel 1 loads');
  await go(`${base}/t/slow-scroll`);
  await waitFor(() => lab.events.some((e) => e.test === 'slow-scroll' && e.what === 'img' && e.data === 's1'), 30000);
  await sleep(300);
  await pageEval("document.getElementById('s7').scrollIntoView(); true");
  await waitFor(settled('slow-scroll'), 60000);
  await win.click('#ls-stop').catch(() => {});

  step('Images: Off, text only');
  await win.click('#ls-images');
  await go(`${base}/t/slow-textonly`);
  await waitFor(async () => (await pageEval("(document.getElementById('txt')||{}).textContent||''")).length > 10, 15000);
  await sleep(3000);
  const textShown = await pageEval("(document.getElementById('txt')||{}).textContent||''");
  await go(`${base}/`);
  await sleep(1000);
  await win.click('#ls-images');

  step('Read ahead: On, then open page 2');
  await win.click('#ls-ahead');
  await go(`${base}/t/slow-ahead`);
  const ready = await waitFor(async () => /Next page ready \(3/.test(await text('linebar-text')), 90000);
  await pageEval("document.getElementById('next').click(); true");
  await waitFor(() => lab.events.some((e) => e.test === 'slow-ahead-2' && e.what === 'visited'), 20000);
  await sleep(3000);
  clearInterval(watch);

  const out = {};
  for (const t of SLOW_TESTS) out[t.id] = lab.verdict(t.id);
  out['slow-textonly'].textShown = textShown.slice(0, 40);
  out['slow-ahead'].readyNotice = ready;
  out.statusLines = statusSeen.slice(0, 8);
  if (process.env.ATTACKLAB_DEBUG) out.events = lab.events.filter((e) => /slow-(scroll|textonly)/.test(e.test)).map((e) => `${e.test} ${e.what} ${e.data}`);
  process.stdout.write(`\n${JSON.stringify(out, null, 2)}\n`);
  await app.close().catch(() => {});
  server.close();
  if (secure) secure.close();
  fs.rmSync(tmp, { recursive: true, force: true });
  process.exit(0);
}

process.on('unhandledRejection', () => {});

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
