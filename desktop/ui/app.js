(function () {
  const $ = (id) => document.getElementById(id);
  let nodes = [];
  let pages = [];
  let active = null;
  let editing = null;
  let pendingCert = null;
  let noticeTimer = 0;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function notice(text, bad) {
    const n = $('notice');
    n.textContent = text;
    n.className = bad ? 'notice bad' : 'notice';
    n.hidden = false;
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => { n.hidden = true; }, 5000);
  }

  function nodeLabel(n) {
    return n.name || n.host;
  }

  function showStage(which) {
    $('empty').hidden = which !== 'empty';
    $('fail').hidden = which !== 'fail';
  }

  function setTitle() {
    if (!active) {
      $('title').textContent = 'Pick a page';
      $('reload').disabled = true;
      $('close').disabled = true;
      return;
    }
    const n = nodes.find((x) => x.id === active.nodeId);
    const p = pages.find((x) => x.id === active.pageId);
    const via = active.via === 'away' ? ' (away)' : active.via === 'lan' ? ' (LAN address)' : '';
    $('title').textContent = `${n ? nodeLabel(n) : ''} · ${p ? p.label : ''}${via}`;
    $('reload').disabled = false;
    $('close').disabled = false;
  }

  function render() {
    const ul = $('nodes');
    ul.textContent = '';
    for (const n of nodes) {
      const li = el('li', 'node');
      const top = el('div', 'node-top');
      top.append(el('div', 'node-name', nodeLabel(n)));
      const edit = el('button', '', 'Edit');
      edit.type = 'button';
      edit.addEventListener('click', () => openDialog(n));
      top.append(edit);
      li.append(top);
      li.append(el('div', 'node-host', `${n.https ? 'https' : 'http'}://${n.host}`));
      const box = el('div', 'pages');
      for (const p of pages) {
        const b = el('button', active && active.nodeId === n.id && active.pageId === p.id ? 'on' : '', p.label);
        b.type = 'button';
        b.addEventListener('click', () => openPage(n.id, p.id));
        box.append(b);
      }
      li.append(box);
      ul.append(li);
    }
    if (!nodes.length) showStage('empty');
  }

  async function openPage(nodeId, pageId) {
    active = { nodeId, pageId, via: 'home' };
    pendingCert = null;
    showStage('none');
    render();
    setTitle();
    $('title').textContent = 'Connecting…';
    const r = await window.nc.openPage(nodeId, pageId);
    if (!r.ok) {
      active = null;
      showStage('empty');
      notice(r.message || 'Could not open the page.', true);
      render();
      setTitle();
      return;
    }
    active.via = r.via;
    setTitle();
  }

  async function closePage() {
    await window.nc.closePage();
    active = null;
    showStage('empty');
    render();
    setTitle();
  }

  function onError(e) {
    if (!active || active.nodeId !== e.nodeId || active.pageId !== e.pageId) return;
    const n = nodes.find((x) => x.id === e.nodeId);
    const p = pages.find((x) => x.id === e.pageId);
    $('fail-title').textContent = `Could not open ${p ? p.label : 'the page'} on ${n ? nodeLabel(n) : 'the node'}`;
    $('fail-text').textContent = e.message || 'The page did not load.';
    pendingCert = e.cert ? { nodeId: e.nodeId, raw: e.cert.raw } : null;
    $('fail-cert').hidden = !e.cert;
    $('fail-cert').textContent = e.cert ? `This node's certificate is not trusted. SHA-256 ${e.cert.fingerprint}` : '';
    $('fail-trust').hidden = !e.cert;
    showStage('fail');
  }

  function openDialog(n) {
    editing = n || null;
    $('dlg-title').textContent = n ? 'Edit node' : 'Add node';
    $('f-name').value = n ? n.name : '';
    $('f-host').value = n ? n.host : '';
    $('f-https').checked = n ? n.https : false;
    for (const p of pages) $(`f-port-${p.id}`).value = n ? n.ports[p.id] : p.port;
    $('f-away').value = n && n.awayHost ? `${n.awayHttps ? 'https' : 'http'}://${n.awayHost}${n.awayPort === (n.awayHttps ? 443 : 80) ? '' : `:${n.awayPort}`}` : '';
    $('f-lan').value = n ? n.lanIp : '';
    const pin = n ? n.pin : '';
    $('f-pin-row').hidden = !pin;
    $('f-pin').textContent = pin ? (pin.toUpperCase().match(/.{2}/g) || []).join(':') : '';
    $('f-delete').hidden = !n;
    $('f-error').hidden = true;
    editing = n ? { ...n } : null;
    window.nc.overlay(true);
    $('dlg').showModal();
    $('f-name').focus();
  }

  function closeDialog() {
    $('dlg').close();
    window.nc.overlay(false);
  }

  async function saveDialog(ev) {
    ev.preventDefault();
    const raw = {
      id: editing ? editing.id : undefined,
      name: $('f-name').value,
      host: $('f-host').value,
      https: $('f-https').checked,
      ports: {},
      awayHost: $('f-away').value,
      lanIp: $('f-lan').value,
      pin: editing ? editing.pin : '',
      lanPin: editing ? editing.lanPin : '',
    };
    for (const p of pages) raw.ports[p.id] = $(`f-port-${p.id}`).value;
    const r = await window.nc.saveNode(raw);
    if (r.error) {
      $('f-error').textContent = r.error;
      $('f-error').hidden = false;
      return;
    }
    nodes = r.nodes;
    closeDialog();
    render();
    setTitle();
    notice('Node saved.');
  }

  async function removeNode() {
    if (!editing) return;
    const id = editing.id;
    const r = await window.nc.removeNode(id);
    nodes = r.nodes || nodes;
    if (active && active.nodeId === id) {
      active = null;
      showStage('empty');
    }
    closeDialog();
    render();
    setTitle();
    notice('Node deleted.');
  }

  async function importNodes() {
    const r = await window.nc.importNodes();
    if (r.canceled) return;
    if (r.error) return notice(r.error, true);
    nodes = r.nodes;
    render();
    notice(`Imported ${r.added} new, ${r.replaced} updated, ${r.skipped} skipped.`);
  }

  async function exportNodes() {
    const r = await window.nc.exportNodes();
    if (r.canceled) return;
    if (r.error) return notice(r.error, true);
    notice('Nodes exported.');
  }

  async function trust() {
    if (!pendingCert) return;
    const r = await window.nc.trustCert(pendingCert.nodeId, pendingCert.raw);
    if (r.error) return notice(r.error, true);
    nodes = r.nodes;
    if (active) openPage(active.nodeId, active.pageId);
  }

  async function init() {
    const info = await window.nc.info();
    pages = info.pages;
    $('ver').textContent = `Version ${info.version}`;
    nodes = await window.nc.listNodes();
    $('add').addEventListener('click', () => openDialog(null));
    $('import').addEventListener('click', importNodes);
    $('export').addEventListener('click', exportNodes);
    $('reload').addEventListener('click', () => active && openPage(active.nodeId, active.pageId));
    $('close').addEventListener('click', closePage);
    $('f-cancel').addEventListener('click', closeDialog);
    $('dlg').addEventListener('cancel', () => window.nc.overlay(false));
    $('form').addEventListener('submit', saveDialog);
    $('f-delete').addEventListener('click', removeNode);
    $('f-pin-clear').addEventListener('click', () => {
      if (editing) editing.pin = '';
      $('f-pin-row').hidden = true;
    });
    $('fail-retry').addEventListener('click', () => active && openPage(active.nodeId, active.pageId));
    $('fail-trust').addEventListener('click', trust);
    window.nc.onPageError(onError);
    window.nc.onPageLoaded(() => {});
    render();
    setTitle();
    showStage('empty');
  }

  init();
})();
