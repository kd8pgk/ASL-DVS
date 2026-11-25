const fs = require('node:fs');
const path = require('node:path');
const { app, ipcMain, dialog } = require('electron');
const { PAGES, MAX_PINS, normalizeNode } = require('./node');
const { exportText, importText } = require('./store');
const L = require('./layout');
const PR = require('./presets');
const LN = require('./launcher');

const CONNECTION_FIELDS = ['host', 'https', 'schemes', 'ports', 'pins', 'lanIp', 'awayHost', 'awayPort', 'awayHttps'];

function registerIpc(ctx) {
  const {
    S, SES, INTERNAL, refused, router, monitor, presetStore,
    fromShell, payload, persist, push, sync, update, focusView, closeRt, closeTab, reloadTab, zoomKey,
    snapshot, emitNotice, openExternalPage, logLine, launcherPaths, runningAppImage,
  } = ctx;
  let shellReady = false;
  let startupNotice = ctx.startupNotice || '';
  const str = (v) => typeof v === 'string';
  ipcMain.handle('app:info', (e) => (fromShell(e) ? { version: app.getVersion(), pages: PAGES } : null));
  ipcMain.handle('layout:get', (e) => {
    if (!fromShell(e)) return null;
    if (!shellReady) {
      shellReady = true;
      process.stderr.write('shell-ready\n');
      if (startupNotice) {
        const text = startupNotice;
        startupNotice = '';
        setTimeout(() => emitNotice(text, true), 400);
      }
    }
    return payload();
  });
  ipcMain.handle('nodes:list', (e) => (fromShell(e) ? snapshot() : []));
  ipcMain.handle('nodes:save', (e, raw) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const r = normalizeNode(raw);
    if (!r.node) return { error: r.error };
    const i = S.nodes.findIndex((n) => n.id === r.node.id);
    let changed = false;
    if (i >= 0) {
      const old = S.nodes[i];
      changed = CONNECTION_FIELDS.some((f) => JSON.stringify(old[f]) !== JSON.stringify(r.node[f]));
      S.nodes[i] = r.node;
      router.forget(r.node.id);
    } else {
      S.nodes.push(r.node);
    }
    persist();
    if (changed) for (const t of S.ls.tabs) if (t.nodeId === r.node.id && t.kind !== 'lh') closeRt(t.key);
    sync();
    monitor.refresh();
    return { node: r.node, nodes: snapshot() };
  });
  ipcMain.handle('nodes:remove', async (e, id) => {
    if (!fromShell(e) || !str(id)) return { error: 'Not allowed.' };
    for (const t of S.ls.tabs) if (t.nodeId === id) closeRt(t.key);
    S.ls = L.closeNode(S.ls, id);
    S.nodes = S.nodes.filter((n) => n.id !== id);
    S.splits = S.splits.filter((p) => !L.SLOTS.some((sl) => p.slots[sl].some((it) => it.nodeId === id)));
    presetStore.save(S.splits);
    router.forget(id);
    persist();
    sync();
    monitor.refresh();
    try {
      await SES.nodePartition(id).clearStorageData();
    } catch {
      return { nodes: snapshot() };
    }
    return { nodes: snapshot() };
  });
  ipcMain.handle('nodes:export', async (e) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const r = await dialog.showSaveDialog(S.win, {
      defaultPath: 'nodecontroller-nodes.json',
      filters: [{ name: 'JSON', extensions: ['json'] }],
    });
    if (r.canceled || !r.filePath) return { canceled: true };
    try {
      fs.writeFileSync(r.filePath, exportText(S.nodes));
    } catch (err) {
      logLine(`export failed: ${err && err.code ? err.code : err}`);
      return { error: 'The node list could not be written there. Pick another folder.' };
    }
    return { path: r.filePath };
  });
  ipcMain.handle('nodes:import', async (e) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const r = await dialog.showOpenDialog(S.win, { properties: ['openFile'], filters: [{ name: 'JSON', extensions: ['json'] }] });
    if (r.canceled || !r.filePaths.length) return { canceled: true };
    let text;
    try {
      text = fs.readFileSync(r.filePaths[0], 'utf8');
    } catch {
      return { error: 'That file could not be read.' };
    }
    const res = importText(S.nodes, text);
    if (res.error) return res;
    S.nodes = res.nodes;
    for (const n of S.nodes) router.forget(n.id);
    persist();
    sync();
    monitor.refresh();
    return { nodes: snapshot(), added: res.added, replaced: res.replaced, skipped: res.skipped };
  });
  ipcMain.handle('tabs:open', (e, nodeId, pageId) => {
    if (!fromShell(e) || !str(nodeId) || !str(pageId)) return { ok: false };
    if (!S.nodes.some((n) => n.id === nodeId) || !PAGES.some((p) => p.id === pageId)) return { ok: false };
    if (PAGES.find((p) => p.id === pageId).external) {
      openExternalPage(nodeId, pageId);
      return { ok: true };
    }
    update(L.openTab(S.ls, nodeId, pageId));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:activate', (e, key) => {
    if (!fromShell(e) || !str(key)) return { ok: false };
    update(L.openKey(S.ls, key));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:close', (e, key) => {
    if (fromShell(e) && str(key)) closeTab(key);
    return { ok: true };
  });
  ipcMain.handle('tabs:reload', (e, key) => {
    if (fromShell(e) && str(key)) reloadTab(key);
    return { ok: true };
  });
  const resolveKey = (arg) => {
    if (!arg || typeof arg !== 'object') return null;
    if (str(arg.key)) return S.ls.tabs.some((t) => t.key === arg.key) ? arg.key : null;
    if (str(arg.nodeId) && str(arg.pageId) && S.nodes.some((n) => n.id === arg.nodeId) && INTERNAL.some((p) => p.id === arg.pageId)) {
      S.ls = L.addTab(S.ls, arg.nodeId, arg.pageId);
      return L.keyOf(arg.nodeId, arg.pageId);
    }
    return null;
  };
  ipcMain.handle('tabs:drop', (e, arg) => {
    if (!fromShell(e) || !arg || !str(arg.slot) || !L.SLOTS.includes(arg.slot)) return { ok: false };
    const key = resolveKey(arg);
    if (!key) return { ok: false };
    update(L.putInSlot(S.ls, key, arg.slot));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:next', (e, arg) => {
    if (!fromShell(e)) return { ok: false };
    const key = resolveKey(arg);
    if (!key) return { ok: false };
    update(L.addNext(S.ls, key));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:alone', (e, arg) => {
    if (!fromShell(e)) return { ok: false };
    const key = resolveKey(arg);
    if (!key) return { ok: false };
    update(L.showAlone(S.ls, key));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:unslot', (e, arg) => {
    if (!fromShell(e)) return { ok: false };
    const key = resolveKey(arg);
    if (!key) return { ok: false };
    update(L.unslot(S.ls, key));
    focusView();
    return { ok: true };
  });
  ipcMain.handle('tabs:zoom', (e, arg) => {
    if (!fromShell(e) || !arg || !str(arg.op)) return { ok: false };
    zoomKey(str(arg.key) ? arg.key : L.focusedKey(S.ls), arg.op);
    return { ok: true };
  });
  ipcMain.handle('tabs:view', (e, view) => {
    if (fromShell(e) && str(view)) {
      update(L.setView(S.ls, view));
      focusView();
    }
    return { ok: true };
  });
  ipcMain.handle('splits:save', (e, name) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const made = PR.fromState(S.ls, name);
    if (made.error) return { error: made.error };
    const r = PR.put(S.splits, made.preset);
    if (r.error) return { error: r.error };
    S.splits = r.list;
    presetStore.save(S.splits);
    push();
    return { ok: true };
  });
  ipcMain.handle('splits:apply', (e, id) => {
    if (!fromShell(e) || !str(id)) return { error: 'Not allowed.' };
    const preset = S.splits.find((p) => p.id === id);
    if (!preset) return { error: 'That split is gone.' };
    const r = PR.apply(S.ls, preset, S.nodes, INTERNAL);
    if (r.error) return { error: r.error };
    update(r.state);
    focusView();
    return { ok: true };
  });
  ipcMain.handle('splits:remove', (e, id) => {
    if (!fromShell(e) || !str(id)) return { error: 'Not allowed.' };
    S.splits = S.splits.filter((p) => p.id !== id);
    presetStore.save(S.splits);
    push();
    return { ok: true };
  });
  ipcMain.handle('tabs:ratio', (e, ratio) => {
    if (fromShell(e)) update(L.setRatio(S.ls, ratio));
    return { ok: true };
  });
  ipcMain.handle('tabs:focus', (e, slot) => {
    if (fromShell(e) && str(slot)) {
      update(L.focusSlot(S.ls, slot));
      focusView();
    }
    return { ok: true };
  });
  ipcMain.handle('app:restart', (e) => {
    if (!fromShell(e)) return { ok: false };
    logLine('restarting at the user\'s request');
    if (process.env.APPIMAGE) app.relaunch({ execPath: process.env.APPIMAGE, args: process.argv.slice(1) });
    else app.relaunch();
    app.quit();
    return { ok: true };
  });
  ipcMain.handle('launcher:status', (e) => (fromShell(e) ? LN.launcherStatus(launcherPaths(), runningAppImage(), app.getVersion()) : null));
  ipcMain.handle('launcher:install', (e) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    let r;
    try {
      let icon = null;
      try {
        icon = fs.readFileSync(path.join(__dirname, '..', 'ui', 'icon.png'));
      } catch {
        icon = null;
      }
      r = LN.installLauncher({ paths: launcherPaths(), running: runningAppImage(), iconPng: icon, version: app.getVersion() });
    } catch (err) {
      logLine(`launcher install failed: ${err && err.code ? err.code : err}`);
      return { error: 'The launcher could not be added. See diagnostics.log.' };
    }
    if (r.error) return r;
    logLine(`launcher added${r.shortcut ? ' with a desktop icon' : ''}`);
    return { ok: true, shortcut: Boolean(r.shortcut), status: LN.launcherStatus(launcherPaths(), runningAppImage(), app.getVersion()) };
  });
  ipcMain.handle('launcher:remove', (e) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    LN.removeLauncher({ paths: launcherPaths() });
    logLine('launcher removed');
    return { ok: true, status: LN.launcherStatus(launcherPaths(), runningAppImage(), app.getVersion()) };
  });
  ipcMain.handle('ui:overlay', (e, on) => {
    if (!fromShell(e)) return { ok: false };
    S.overlay = Boolean(on);
    sync();
    return { ok: true };
  });
  ipcMain.handle('cert:trust', (e, nodeId, fingerprint) => {
    if (!fromShell(e)) return { error: 'Not allowed.' };
    const node = S.nodes.find((n) => n.id === nodeId);
    if (!node) return { error: 'That node is gone.' };
    const want = String(fingerprint || '').toLowerCase().replace(/[^0-9a-f]/g, '');
    const hit = [...refused.values()].find((r) => r.fingerprint === want && r.nodeIds.includes(nodeId));
    if (!hit) return { error: 'That certificate was not the one refused.' };
    node.pins = [...node.pins.filter((p) => p !== hit.fingerprint), hit.fingerprint].slice(-MAX_PINS);
    for (const [k, r] of refused) if (r.fingerprint === hit.fingerprint) refused.delete(k);
    router.forget(nodeId);
    persist();
    for (const t of S.ls.tabs) if (t.nodeId === nodeId && t.kind !== 'lh') closeRt(t.key);
    sync();
    return { nodes: snapshot() };
  });
}

module.exports = { registerIpc, CONNECTION_FIELDS };
