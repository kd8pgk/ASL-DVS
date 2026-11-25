#!/usr/bin/env node
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { _electron } = require('playwright');
const { start } = require('./server');

const root = path.join(__dirname, '..', 'nullbrowser');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = Number(process.env.ATTACKLAB_PORT || 18388);

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
  const { lab, server, secure, httpsPort } = start({ port: PORT, host: '127.0.0.1' });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fplab-run-'));
  fs.mkdirSync(path.join(tmp, 'ram'));
  const app = await _electron.launch({
    executablePath: require(path.join(root, 'node_modules', 'electron')),
    args: [root, '--no-sandbox', `--host-resolver-rules=MAP localhost 127.0.0.1`],
    env: { ...noProxy(process.env), NULLBROWSER_RAM_BASE: path.join(tmp, 'ram') },
  });
  await waitFor(() => app.windows().some((w) => w.url().endsWith('/ui/index.html')), 15000);
  const win = app.windows().find((w) => w.url().endsWith('/ui/index.html'));
  await win.waitForLoadState('domcontentloaded');
  const pageEval = (code) => app.evaluate(({ BrowserWindow }, c) => BrowserWindow.getAllWindows().find((w) => w.contentView && w.contentView.children.length > 0).contentView.children[0].webContents.mainFrame.executeJavaScript(c, true), code);
  const seen = (what) => () => lab.events.some((e) => e.test === 'fingerprint' && e.what === what);
  const trust = async () => {
    if (await waitFor(async () => win.evaluate(() => !document.getElementById('msg-main').hidden), 8000)) await win.click('#msg-main');
  };
  await win.fill('#addr', `https://127.0.0.1:${httpsPort}/t/fingerprint`);
  await win.press('#addr', 'Enter');
  await trust();
  await waitFor(seen('headers-first'), 15000);
  await sleep(1500);
  await pageEval("document.getElementById('again').click(); true");
  await waitFor(seen('headers-again'), 15000);
  await waitFor(seen('done'), 15000);
  await sleep(800);
  await pageEval("document.getElementById('cross').click(); true");
  await trust();
  await waitFor(seen('headers-cross'), 15000);
  await sleep(500);
  const raw = lab.events.filter((e) => e.test === 'fingerprint' && /^headers|script/.test(e.what)).map((e) => `${e.what}: ${e.data}`);
  process.stdout.write(`${JSON.stringify({ verdict: lab.verdict('fingerprint'), raw }, null, 2)}\n`);
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
