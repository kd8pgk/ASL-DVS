const fs = require('node:fs');
const crypto = require('node:crypto');
const { dialog, ipcMain } = require('electron');
const P = require('./policy');
const BL = require('./blocklist');
const PU = require('./popups');
const { st } = require('./state');
const shared = require('./ctx');

const MAX_LOG = 200;
const MAX_FOUND = 40;
let hitTimer = null;

function pageHost() {
  return P.hostOf(shared.pageUrl());
}

function contents() {
  return st.view && !st.view.webContents.isDestroyed() ? st.view.webContents : null;
}

function logPop(kind, from, host, action) {
  const last = st.popLog[0];
  if (last && last.kind === kind && last.host === host && last.action === action && last.from === from) {
    last.n += 1;
  } else {
    st.popSeq += 1;
    st.popLog.unshift({ id: st.popSeq, kind, from, host, action, n: 1 });
    if (st.popLog.length > MAX_LOG) st.popLog.length = MAX_LOG;
  }
  if (st.popOpen) shared.push();
}

function noteBlocked(host) {
  st.blockHits.set(host, (st.blockHits.get(host) || 0) + 1);
  if (st.blockHits.size > 300) st.blockHits.delete(st.blockHits.keys().next().value);
  if (st.popOpen && !hitTimer) {
    hitTimer = setTimeout(() => {
      hitTimer = null;
      shared.push();
    }, 400);
    hitTimer.unref();
  }
}

function blockedBy(host) {
  return st.block.size() ? st.block.hostBlocked(host) : '';
}

function resetPage() {
  st.popFound = [];
  st.popNote = '';
  st.popPicking = false;
}

function resetRun() {
  resetPage();
  st.popLog = [];
  st.blockHits.clear();
}

function popState() {
  if (!st.popOpen) return { open: false };
  const snap = st.block.snapshot(100);
  const hits = [...st.blockHits.entries()].sort((a, b) => b[1] - a[1]).slice(0, 15);
  return {
    open: true,
    picking: st.popPicking,
    note: st.popNote,
    found: st.popFound.map(({ id, kind, tag, text, selector, frameHost, thirdParty, hosts, w, h }) => ({ id, kind, tag, text, selector, frameHost, thirdParty, hosts, w, h })),
    log: st.popLog.slice(0, 60),
    hostCount: snap.hostCount,
    elementCount: snap.elementCount,
    hosts: snap.hosts,
    elements: snap.elements,
    hits,
  };
}

function canBlock(host) {
  const clean = BL.cleanHost(host);
  if (!clean) return { ok: false, reason: 'That is not a host name.' };
  const top = pageHost();
  if (top && P.siteOf(top) === P.siteOf(clean)) return { ok: false, reason: 'That is the page\'s own site, so it was not blocked. Hide the element instead.' };
  return { ok: true, host: clean };
}

function blockHost(host) {
  const c = canBlock(host);
  if (!c.ok) {
    shared.say(c.reason);
    return false;
  }
  const r = st.block.addHost(c.host);
  if (!r.ok) {
    shared.say(`Not added: ${r.reason}.`);
    return false;
  }
  shared.say(r.added ? `Blocking ${c.host} from now on this run. Reload the page to see it gone.` : `${c.host} is already on the list.`);
  return true;
}

function register(fromShell) {
  ipcMain.on('nb-block-css', (e, host) => {
    e.returnValue = e.sender.session === st.ses && st.block.hasElements() ? st.block.cssFor(String(host || '')) : '';
  });
  ipcMain.handle('pop-panel', (e, on) => {
    if (!fromShell(e)) return { ok: false };
    st.popOpen = on === true;
    if (st.popOpen) {
      st.dlPanelOpen = false;
      st.dlQueueOpen = false;
    } else if (st.popPicking && contents()) {
      PU.cancelAll(contents(), st.popToken);
    }
    shared.push();
    return { ok: true };
  });
  ipcMain.handle('pop-find', async (e) => {
    if (!fromShell(e)) return { ok: false };
    const wc = contents();
    const top = pageHost();
    if (!wc || !top) {
      st.popNote = 'Open a page first.';
      shared.push();
      return { ok: false };
    }
    const url = shared.pageUrl();
    st.popNote = 'Looking…';
    shared.push();
    const r = await PU.findAll(wc, top);
    if (shared.pageUrl() !== url) return { ok: false };
    st.popFound = r.items.map((it) => {
      st.popFoundSeq += 1;
      return { ...it, id: st.popFoundSeq };
    });
    if (r.items.length) st.popNote = r.failed ? `${r.failed} frame${r.failed === 1 ? '' : 's'} could not be read.` : '';
    else st.popNote = r.failed ? 'Could not read the page.' : 'Nothing that looks like a pop-up was found. Try Pick.';
    shared.push();
    return { ok: true };
  });
  ipcMain.handle('pop-pick', async (e) => {
    if (!fromShell(e)) return { ok: false };
    const wc = contents();
    const top = pageHost();
    if (!wc || !top) return { ok: false };
    if (st.popPicking) {
      PU.cancelAll(wc, st.popToken);
      return { ok: true };
    }
    st.popPicking = true;
    st.popToken = crypto.randomBytes(6).toString('hex');
    st.popNote = 'Click the pop-up on the page. Esc cancels.';
    shared.push();
    const url = shared.pageUrl();
    const it = await PU.pickOne(wc, top, st.popToken);
    st.popPicking = false;
    if (shared.pageUrl() !== url) {
      shared.push();
      return { ok: false };
    }
    if (it) {
      st.popFoundSeq += 1;
      st.popFound.unshift({ ...it, id: st.popFoundSeq });
      if (st.popFound.length > MAX_FOUND) st.popFound.length = MAX_FOUND;
      st.popNote = '';
    } else {
      st.popNote = 'Nothing was picked.';
    }
    shared.push();
    return { ok: true };
  });
  ipcMain.handle('pop-show', (e, id) => {
    if (!fromShell(e)) return { ok: false };
    const f = st.popFound.find((x) => x.id === Number(id));
    const wc = contents();
    if (!f || !f.selector || !wc) return { ok: false };
    PU.outline(wc, f.frameHost, f.selector);
    return { ok: true };
  });
  ipcMain.handle('pop-hide', (e, id) => {
    if (!fromShell(e)) return { ok: false };
    const f = st.popFound.find((x) => x.id === Number(id));
    const wc = contents();
    if (!f || !f.selector || !f.frameHost || !wc) return { ok: false };
    const r = st.block.addElement(f.frameHost, f.selector);
    if (!r.ok) {
      shared.say(`Not added: ${r.reason}.`);
      return { ok: false };
    }
    shared.say(r.added ? `Hiding ${f.selector} on ${f.frameHost}.` : 'That element is already hidden.');
    PU.applyCss(wc, (h) => st.block.cssFor(h));
    shared.push();
    return { ok: true };
  });
  ipcMain.handle('pop-block', (e, id, host) => {
    if (!fromShell(e)) return { ok: false };
    const f = st.popFound.find((x) => x.id === Number(id));
    if (!f || !(f.hosts.includes(String(host)) || f.frameHost === String(host))) return { ok: false };
    const ok = blockHost(host);
    shared.push();
    return { ok };
  });
  ipcMain.handle('pop-block-log', (e, id) => {
    if (!fromShell(e)) return { ok: false };
    const entry = st.popLog.find((x) => x.id === Number(id));
    if (!entry) return { ok: false };
    const ok = blockHost(entry.host);
    shared.push();
    return { ok };
  });
  ipcMain.handle('pop-remove', (e, kind, a, b) => {
    if (!fromShell(e)) return { ok: false };
    const wc = contents();
    let ok = false;
    if (kind === 'host') ok = st.block.removeHost(a);
    else if (kind === 'element') {
      ok = st.block.removeElement(a, b);
      if (ok && wc) PU.applyCss(wc, (h) => st.block.cssFor(h));
    }
    shared.push();
    return { ok };
  });
  ipcMain.handle('pop-clear-log', (e) => {
    if (!fromShell(e)) return { ok: false };
    st.popLog = [];
    st.blockHits.clear();
    shared.push();
    return { ok: true };
  });
  ipcMain.handle('pop-import', async (e) => {
    if (!fromShell(e)) return { ok: false };
    const res = await dialog.showOpenDialog(st.win, {
      title: 'Import a block list',
      filters: [{ name: 'Block lists', extensions: ['txt', 'list', 'hosts', 'conf'] }, { name: 'All files', extensions: ['*'] }],
      properties: ['openFile'],
    });
    if (res.canceled || !res.filePaths[0]) return { ok: false };
    let text = '';
    try {
      if (fs.statSync(res.filePaths[0]).size > BL.MAX_FILE_BYTES) {
        shared.say('That block list is too big to import.');
        return { ok: false };
      }
      text = fs.readFileSync(res.filePaths[0], 'utf8');
    } catch {
      shared.say('That file could not be read.');
      return { ok: false };
    }
    const r = st.block.importText(text);
    const wc = contents();
    if (wc) PU.applyCss(wc, (h) => st.block.cssFor(h));
    shared.say(`Block list: ${r.hosts} host${r.hosts === 1 ? '' : 's'} and ${r.elements} element rule${r.elements === 1 ? '' : 's'} added${r.skipped ? `, ${r.skipped} line${r.skipped === 1 ? '' : 's'} skipped` : ''}${r.full ? ' (the list is full)' : ''}.`);
    shared.push();
    return { ok: true };
  });
}

module.exports = { register, popState, logPop, noteBlocked, blockedBy, resetPage, resetRun };
