(function () {
  const $ = (id) => document.getElementById(id);
  const GAP = 6;
  let nodes = [];
  let pages = [];
  let lay = null;
  let editing = null;
  let noticeTimer = 0;
  let paneSig = '';

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

  function placeRect(e, r) {
    e.style.left = `${r.x}px`;
    e.style.top = `${r.y}px`;
    e.style.width = `${r.w}px`;
    e.style.height = `${r.h}px`;
  }

  function renderNodes() {
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
        const tab = lay && lay.tabs.find((t) => t.nodeId === n.id && t.pageId === p.id);
        const b = el('button', tab && tab.shown >= 0 ? 'on' : '', p.label);
        b.type = 'button';
        b.addEventListener('click', () => window.nc.openTab(n.id, p.id));
        box.append(b);
      }
      li.append(box);
      ul.append(li);
    }
  }

  function renderTabs() {
    const box = $('tabs');
    box.textContent = '';
    if (!lay) return;
    for (const t of lay.tabs) {
      const cls = ['tab'];
      if (t.shown >= 0) cls.push('shown');
      if (t.shown >= 0 && t.shown === lay.focus) cls.push('focus');
      const tab = el('div', cls.join(' '));
      tab.setAttribute('role', 'tab');
      tab.append(el('span', `dot ${t.status}`));
      tab.append(el('span', 'label', t.via === 'away' ? `${t.label} (away)` : t.via === 'lan' ? `${t.label} (LAN address)` : t.label));
      const x = el('button', 'x', '×');
      x.type = 'button';
      x.title = 'Close (Ctrl+W)';
      x.addEventListener('click', (ev) => {
        ev.stopPropagation();
        window.nc.closeTab(t.key);
      });
      tab.append(x);
      tab.addEventListener('click', () => window.nc.activateTab(t.key));
      box.append(tab);
    }
    for (const b of $('modes').querySelectorAll('button')) {
      const m = b.dataset.mode;
      b.classList.toggle('on', lay.mode === m);
      b.disabled = m !== 'single' && !lay.canSplit && lay.mode === 'single';
    }
    $('reload').disabled = !lay.tabs.length;
  }

  function failPanel(pane) {
    const e = pane.error;
    const key = pane.key;
    const tab = lay.tabs.find((t) => t.key === key);
    const box = el('div', 'pane-msg');
    placeRect(box, pane.rect);
    box.append(el('h2', '', `Could not open ${tab ? tab.label : 'the page'}`));
    box.append(el('p', '', e.message || 'The page did not load.'));
    if (e.cert) box.append(el('p', 'mono', `This node's certificate is not trusted. SHA-256 ${e.cert.fingerprint}`));
    const row = el('div', 'row');
    if (e.cert) {
      const trust = el('button', 'primary', 'Trust this certificate');
      trust.type = 'button';
      trust.addEventListener('click', async () => {
        const r = await window.nc.trustCert(e.nodeId, e.cert.raw);
        if (r.error) return notice(r.error, true);
        nodes = r.nodes;
        renderNodes();
      });
      row.append(trust);
    }
    const retry = el('button', '', 'Try again');
    retry.type = 'button';
    retry.addEventListener('click', () => window.nc.reloadTab(key));
    row.append(retry);
    box.append(row);
    return box;
  }

  function startDrag(ev, divider) {
    ev.preventDefault();
    const rows = lay.mode === 'rows';
    const p0 = lay.panes[0].rect;
    const p1 = lay.panes[1].rect;
    const start = rows ? p0.y : p0.x;
    const total = rows ? p0.h + GAP + p1.h : p0.w + GAP + p1.w;
    divider.classList.add('drag');
    divider.setPointerCapture(ev.pointerId);
    let queued = null;
    const flush = () => {
      if (queued === null) return;
      window.nc.setRatio(queued);
      queued = null;
    };
    const move = (m) => {
      const pos = (rows ? m.clientY : m.clientX) - start - GAP / 2;
      const ratio = pos / (total - GAP);
      if (queued === null) requestAnimationFrame(flush);
      queued = ratio;
    };
    const stop = () => {
      divider.removeEventListener('pointermove', move);
      divider.removeEventListener('pointerup', stop);
      divider.removeEventListener('pointercancel', stop);
      divider.classList.remove('drag');
      flush();
    };
    divider.addEventListener('pointermove', move);
    divider.addEventListener('pointerup', stop);
    divider.addEventListener('pointercancel', stop);
  }

  function sigOf() {
    return JSON.stringify([lay.mode, lay.overlay, Boolean(lay.divider), lay.panes.map((p) => [p.status, p.key, p.error && p.error.message])]);
  }

  function positionPanes() {
    for (const c of $('panes').children) {
      if (c.classList.contains('divider')) placeRect(c, lay.divider);
      else placeRect(c, lay.panes[Number(c.dataset.pane)].rect);
    }
  }

  function renderPanes() {
    const sig = sigOf();
    if (sig === paneSig) {
      positionPanes();
      return;
    }
    paneSig = sig;
    const box = $('panes');
    box.textContent = '';
    if (lay.overlay) return;
    lay.panes.forEach((pane, i) => {
      if (pane.status === 'ok') return;
      let m;
      if (pane.status === 'failed') {
        m = failPanel(pane);
      } else {
        m = el('div', 'pane-msg');
        placeRect(m, pane.rect);
        if (pane.status === 'empty') m.append(el('p', '', 'Add a node, then open Node Controller or Node Talker from the list. Open two pages and pick Columns or Rows to see them side by side.'));
        else m.append(el('p', '', 'Connecting…'));
      }
      m.dataset.pane = String(i);
      box.append(m);
    });
    if (lay.divider && lay.panes.length === 2) {
      const d = el('div', `divider ${lay.mode}`);
      placeRect(d, lay.divider);
      d.addEventListener('pointerdown', (ev) => startDrag(ev, d));
      d.addEventListener('dblclick', () => window.nc.setRatio(0.5));
      box.append(d);
    }
  }

  function render() {
    renderTabs();
    renderNodes();
    renderPanes();
  }

  function onLayout(next) {
    lay = next;
    render();
  }

  function openDialog(n) {
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
    renderNodes();
    notice('Node saved.');
  }

  async function removeNode() {
    if (!editing) return;
    const r = await window.nc.removeNode(editing.id);
    nodes = r.nodes || nodes;
    closeDialog();
    renderNodes();
    notice('Node deleted.');
  }

  async function importNodes() {
    const r = await window.nc.importNodes();
    if (r.canceled) return;
    if (r.error) return notice(r.error, true);
    nodes = r.nodes;
    renderNodes();
    notice(`Imported ${r.added} new, ${r.replaced} updated, ${r.skipped} skipped.`);
  }

  async function exportNodes() {
    const r = await window.nc.exportNodes();
    if (r.canceled) return;
    if (r.error) return notice(r.error, true);
    notice('Nodes exported.');
  }

  async function init() {
    const info = await window.nc.info();
    pages = info.pages;
    $('ver').textContent = `Version ${info.version}`;
    nodes = await window.nc.listNodes();
    $('add').addEventListener('click', () => openDialog(null));
    $('import').addEventListener('click', importNodes);
    $('export').addEventListener('click', exportNodes);
    $('reload').addEventListener('click', () => {
      if (!lay) return;
      const key = lay.panes[lay.focus] && lay.panes[lay.focus].key;
      if (key) window.nc.reloadTab(key);
    });
    for (const b of $('modes').querySelectorAll('button')) b.addEventListener('click', () => window.nc.setMode(b.dataset.mode));
    $('f-cancel').addEventListener('click', closeDialog);
    $('dlg').addEventListener('cancel', () => window.nc.overlay(false));
    $('form').addEventListener('submit', saveDialog);
    $('f-delete').addEventListener('click', removeNode);
    $('f-pin-clear').addEventListener('click', () => {
      if (editing) editing.pin = '';
      $('f-pin-row').hidden = true;
    });
    window.nc.onLayout(onLayout);
    onLayout(await window.nc.getLayout());
  }

  init();
})();
