const path = require('node:path');
const fs = require('node:fs');
const { app, BrowserWindow, WebContentsView, Menu, ipcMain, session, screen, shell, dialog, net, protocol } = require('electron');
const SH = require('./shot');
const { st } = require('./state');
const shared = require('./ctx');

function shotDir() {
  const dir = path.join(shared.ram.sub.files, 'quarantine');
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  return dir;
}

function discardShot() {
  if (!st.pendingShot) return;
  const file = st.pendingShot.file;
  st.pendingShot = null;
  try {
    fs.rmSync(file, { force: true });
    fs.rmdirSync(path.dirname(file));
  } catch {}
}

async function printPage(wc) {
  return wc.printToPDF({ printBackground: true, pageSize: 'A4' });
}

async function windowPdf() {
  const img = await st.win.webContents.capturePage();
  const size = img.getSize();
  const png = img.toPNG().toString('base64');
  const html = `<!doctype html><html><head><style>@page{margin:0}html,body{margin:0;padding:0}img{display:block;width:${size.width}px;height:${size.height}px}</style></head><body><img src="data:image/png;base64,${png}"></body></html>`;
  const shot = new BrowserWindow({ show: false, width: size.width, height: size.height, webPreferences: { session: st.ses, sandbox: true, contextIsolation: true, nodeIntegration: false, webviewTag: false, plugins: false, spellcheck: false } });
  try {
    await shot.loadURL(`data:text/html;base64,${Buffer.from(html).toString('base64')}`);
    return await shot.webContents.printToPDF({ printBackground: true, pageSize: { width: size.width / 96, height: size.height / 96 } });
  } finally {
    shot.destroy();
  }
}

async function makeShot(withWindow) {
  if (st.pendingShot || !shared.alive() || !st.view || st.view.webContents.isDestroyed()) return;
  st.shotSeq += 1;
  const file = path.join(shotDir(), `shot-${st.shotSeq}.pdf`);
  st.pendingShot = { id: st.shotSeq, file, sha: '', text: 'Making the screenshot…', busy: true };
  shared.push();
  let buf;
  try {
    buf = withWindow ? await windowPdf() : await printPage(st.view.webContents);
  } catch {
    buf = null;
  }
  if (!buf) {
    st.pendingShot = null;
    shared.say('The screenshot could not be made.');
    return;
  }
  const sha = SH.sha256(buf);
  fs.writeFileSync(file, buf, { mode: 0o600 });
  const back = fs.readFileSync(file);
  const check = SH.checkPdf(back, sha);
  if (!check.ok) {
    discardShot();
    shared.say(`The screenshot was not saved: ${check.reason}.`);
    return;
  }
  st.pendingShot = { id: st.shotSeq, file, sha, text: `Save the screenshot (PDF, ${Math.max(1, Math.round(back.length / 1024))} KB, ${check.pages} page${check.pages === 1 ? '' : 's'}) to your Downloads folder?`, busy: false };
  shared.push();
}

function answerShot(save) {
  const rec = st.pendingShot;
  if (!save) {
    discardShot();
    shared.push();
    return;
  }
  st.pendingShot = { ...rec, text: 'Saving…', busy: true };
  shared.push();
  try {
    const buf = fs.readFileSync(rec.file);
    const check = SH.checkPdf(buf, rec.sha);
    if (!check.ok) throw new Error(check.reason);
    const dir = SH.downloadsFromUserDirs(shared.readUserDirs(), shared.REAL_HOME);
    fs.mkdirSync(dir, { recursive: true });
    const name = SH.uniqueName(SH.shotName(new Date()), (n) => fs.existsSync(path.join(dir, n)));
    if (!name) throw new Error('no free file name');
    fs.writeFileSync(path.join(dir, name), buf, { flag: 'wx', mode: 0o644 });
    discardShot();
    shared.say(`Saved ${name} to your Downloads folder.`);
  } catch (err) {
    discardShot();
    shared.say(`The screenshot was not saved: ${err.message}.`);
  }
}

module.exports = { shotDir, discardShot, printPage, windowPdf, makeShot, answerShot };
