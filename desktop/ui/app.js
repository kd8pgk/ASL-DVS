(function () {
  const $ = (id) => document.getElementById(id);
  const GAP = 6;
  let nodes = [];
  let pages = [];
  let lay = null;
  let editing = null;
  let noticeTimer = 0;
  let drag = null;
  let menuOpen = false;
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
    noticeTimer = setTimeout(() => { n.hidden = true; }, 6000);
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

  function wantsOverlay() {
    return Boolean(drag) || menuOpen || $('dlg').open || $('dlg-name').open;
  }

  function setOverlay() {
    window.nc.overlay(wantsOverlay());
  }

  function argOf(src) {
    return src.key ? { key: src.key } : { nodeId: src.nodeId, pageId: src.pageId };
  }

  function activate(src, ev) {
    if (ev && (ev.ctrlKey || ev.metaKey)) return window.nc.addNext(argOf(src));
    if (src.key) return window.nc.activateTab(src.key);
    return window.nc.openTab(src.nodeId, src.pageId);
  }

  function startDrag(ev, src) {
    drag = src;
    ev.dataTransfer.effectAllowed = 'move';
    ev.dataTransfer.setData('text/plain', src.key || `${src.nodeId}:${src.pageId}`);
    setTimeout(() => {
      if (drag) setOverlay();
      if (drag && lay) renderPanes();
    }, 0);
  }

  function endDrag() {
    if (!drag) return;
    drag = null;
    setOverlay();
    if (lay) render();
  }

  const SLOT_NAMES = { left: 'Left slot', right: 'Right slot', lower: 'Lower slot' };

  function zoneLabel(id) {
    return SLOT_NAMES[id] || id;
  }

  function closeMenu() {
    if (!menuOpen) return;
    menuOpen = false;
    $('menu').hidden = true;
    setOverlay();
  }

  function tabFor(src) {
    if (!lay) return null;
    if (src.key) return lay.tabs.find((t) => t.key === src.key) || null;
    return lay.tabs.find((t) => t.nodeId === src.nodeId && t.pageId === src.pageId) || null;
  }

  function isSingleOnly(src) {
    const t = tabFor(src);
    if (t) return t.singleOnly;
    const p = pages.find((x) => x.id === src.pageId);
    return Boolean(p && p.single);
  }

  function showMenu(ev, src) {
    ev.preventDefault();
    if (!lay) return;
    const menu = $('menu');
    menu.textContent = '';
    const tab = tabFor(src);
    const add = (label, fn) => {
      const b = el('button', 'menu-item', label);
      b.type = 'button';
      b.addEventListener('click', () => {
        closeMenu();
        fn();
      });
      menu.append(b);
    };
    add('Show alone', () => window.nc.showAlone(argOf(src)));
    if (!isSingleOnly(src)) {
      for (const z of lay.zones) {
        if (tab && tab.slot === z.id) continue;
        add(`Put in ${SLOT_NAMES[z.id]}`, () => window.nc.dropTab({ ...argOf(src), slot: z.id }));
      }
    }
    if (tab && tab.slot) add('Take out of its slot', () => window.nc.unslot({ key: tab.key }));
    if (tab) add('Close tab', () => window.nc.closeTab(tab.key));
    menu.hidden = false;
    menu.style.left = `${Math.min(ev.clientX, window.innerWidth - 220)}px`;
    menu.style.top = `${Math.min(ev.clientY, window.innerHeight - 40 - menu.children.length * 30)}px`;
    menuOpen = true;
    setOverlay();
  }

  function entry(src, label, cls, extra) {
    const li = el('li', `entry ${cls || ''}`.trim());
    const b = el('button', 'entry-main', label);
    b.type = 'button';
    li.draggable = true;
    b.addEventListener('click', (ev) => activate(src, ev));
    li.addEventListener('contextmenu', (ev) => showMenu(ev, src));
    li.addEventListener('dragstart', (ev) => startDrag(ev, src));
    li.addEventListener('dragend', endDrag);
    li.append(b);
    if (extra) li.append(extra);
    return li;
  }

  function smallButton(text, title, fn) {
    const x = el('button', 'x', text);
    x.type = 'button';
    x.title = title;
    x.addEventListener('click', (ev) => {
      ev.stopPropagation();
      fn();
    });
    return x;
  }

  function dropTarget(node, onDrop) {
    node.addEventListener('dragenter', (ev) => {
      if (!drag) return;
      ev.preventDefault();
      node.classList.add('over');
    });
    node.addEventListener('dragover', (ev) => {
      if (!drag) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'move';
      node.classList.add('over');
    });
    node.addEventListener('dragleave', (ev) => {
      if (!node.contains(ev.relatedTarget)) node.classList.remove('over');
    });
    node.addEventListener('drop', (ev) => {
      ev.preventDefault();
      const src = drag;
      node.classList.remove('over');
      endDrag();
      if (src) onDrop(src);
    });
  }

  function renderSlots() {
    const box = $('slots-box');
    box.textContent = '';
    if (!lay) return;
    for (const sl of lay.slots) {
      const sec = el('section', `sec slot${lay.view === 'slots' && lay.focus === sl.slot ? ' focus' : ''}`);
      sec.dataset.slot = sl.slot;
      sec.append(el('div', 'sec-head', `${sl.label} slot`));
      const ul = el('ul', 'entries');
      if (!sl.pages.length) ul.append(el('li', 'hint', 'Drop a page here'));
      for (const pg of sl.pages) {
        const src = { key: pg.key };
        const out = smallButton('×', 'Take out of this slot', () => window.nc.unslot(src));
        ul.append(entry(src, pg.label, pg.selected ? 'sel' : '', out));
      }
      sec.append(ul);
      dropTarget(sec, (src) => window.nc.dropTab({ ...argOf(src), slot: sl.slot }));
      box.append(sec);
    }
  }

  function renderSingles() {
    const ul = $('singles');
    ul.textContent = '';
    const list = lay ? lay.tabs.filter((t) => !t.slot) : [];
    if (!list.length) ul.append(el('li', 'hint', 'Pages you open appear here'));
    for (const t of list) {
      const src = { key: t.key };
      const cls = lay.view === 'single' && t.shown ? 'sel' : '';
      ul.append(entry(src, t.label, cls, smallButton('×', 'Close', () => window.nc.closeTab(t.key))));
    }
    dropTarget($('singles-box'), (src) => {
      const t = tabFor(src);
      if (t && t.slot) window.nc.unslot({ key: t.key });
      else if (!t) window.nc.showAlone(argOf(src));
    });
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
        const b = el('button', tab ? (tab.shown ? 'on' : 'open') : '', p.label);
        b.type = 'button';
        b.draggable = !p.single;
        const src = { nodeId: n.id, pageId: p.id };
        b.addEventListener('click', (ev) => activate(src, ev));
        b.addEventListener('contextmenu', (ev) => showMenu(ev, src));
        b.addEventListener('dragstart', (ev) => startDrag(ev, src));
        b.addEventListener('dragend', endDrag);
        box.append(b);
      }
      li.append(box);
      ul.append(li);
    }
  }

  function renderSplits() {
    const list = lay ? lay.splits : [];
    $('splits-box').hidden = list.length === 0;
    const ul = $('splits');
    ul.textContent = '';
    for (const sp of list) {
      const li = el('li', 'split-row');
      const b = el('button', 'split-name', sp.name);
      b.type = 'button';
      b.title = `Show ${sp.count} pages together`;
      b.addEventListener('click', async () => {
        const r = await window.nc.applySplit(sp.id);
        if (r.error) notice(r.error, true);
      });
      const x = el('button', 'x', '×');
      x.type = 'button';
      x.title = 'Delete this saved split';
      x.addEventListener('click', () => window.nc.removeSplit(sp.id));
      li.append(b, x);
      ul.append(li);
    }
  }

  function renderTabs() {
    const box = $('tabs');
    box.textContent = '';
    if (!lay) return;
    for (const t of lay.tabs) {
      const cls = ['tab'];
      if (t.shown) cls.push('shown');
      if (t.focused) cls.push('focus');
      const tab = el('div', cls.join(' '));
      tab.setAttribute('role', 'tab');
      tab.draggable = true;
      tab.append(el('span', `dot ${t.status}${t.idle ? ' idle' : ''}`));
      tab.append(el('span', 'label', t.via === 'away' ? `${t.label} (away)` : t.via === 'lan' ? `${t.label} (LAN address)` : t.label));
      const x = el('button', 'x', '×');
      x.type = 'button';
      x.title = 'Close (Ctrl+W)';
      x.addEventListener('click', (ev) => {
        ev.stopPropagation();
        window.nc.closeTab(t.key);
      });
      tab.append(x);
      const src = { key: t.key };
      tab.addEventListener('click', (ev) => activate(src, ev));
      tab.addEventListener('contextmenu', (ev) => showMenu(ev, src));
      tab.addEventListener('dragstart', (ev) => startDrag(ev, src));
      tab.addEventListener('dragend', endDrag);
      box.append(tab);
    }
    for (const b of $('views').querySelectorAll('button')) {
      const v = b.dataset.view;
      b.classList.toggle('on', lay.view === v);
      b.disabled = v === 'slots' ? !lay.canSplit : !lay.tabs.length;
    }
    $('save-split').disabled = !lay.canSave;
    $('reload').disabled = !lay.tabs.length;
  }

  function failPanel(pane) {
    const e = pane.error;
    const key = pane.key;
    const box = el('div', 'pane-msg');
    placeRect(box, pane.view);
    box.append(el('h2', '', `Could not open ${pane.label || 'the page'}`));
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

  function startDivider(ev, divider) {
    ev.preventDefault();
    const p0 = lay.panes[0].rect;
    const p1 = lay.panes[1].rect;
    const start = p0.x;
    const total = p0.w + GAP + p1.w;
    divider.classList.add('drag');
    divider.setPointerCapture(ev.pointerId);
    let queued = null;
    const flush = () => {
      if (queued === null) return;
      window.nc.setRatio(queued);
      queued = null;
    };
    const move = (m) => {
      const pos = m.clientX - start - GAP / 2;
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

  function strip(pane, i) {
    const s = el('div', `pane-strip${lay.focus === pane.slot ? ' focus' : ''}`);
    placeRect(s, { x: pane.rect.x, y: pane.rect.y, w: pane.rect.w, h: lay.grid.strip });
    s.dataset.strip = String(i);
    s.append(el('span', 'strip-slot', SLOT_NAMES[pane.slot] ? SLOT_NAMES[pane.slot].replace(' slot', '') : ''));
    const stack = el('div', 'strip-stack');
    if (pane.stack.length > 1) {
      for (const item of pane.stack) {
        const b = el('button', item.selected ? 'on' : '', item.label);
        b.type = 'button';
        b.addEventListener('click', (ev) => {
          ev.stopPropagation();
          window.nc.activateTab(item.key);
        });
        stack.append(b);
      }
    } else {
      stack.append(el('span', 'strip-title', pane.label));
    }
    s.append(stack);
    const alone = el('button', '', 'Alone');
    alone.type = 'button';
    alone.title = 'Show this page by itself';
    alone.addEventListener('click', (ev) => {
      ev.stopPropagation();
      window.nc.showAlone({ key: pane.key });
    });
    const out = el('button', '', 'Out');
    out.type = 'button';
    out.title = 'Take this page out of its slot';
    out.addEventListener('click', (ev) => {
      ev.stopPropagation();
      window.nc.unslot({ key: pane.key });
    });
    s.append(alone, out);
    s.addEventListener('click', () => window.nc.focusSlot(pane.slot));
    return s;
  }

  function zoneLayer(box) {
    for (const z of lay.zones) {
      const d = el('div', 'zone');
      placeRect(d, z.rect);
      d.dataset.zone = z.id;
      d.append(el('span', 'zone-label', zoneLabel(z.id)));
      d.addEventListener('dragenter', (ev) => {
        ev.preventDefault();
        d.classList.add('over');
      });
      d.addEventListener('dragover', (ev) => {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
        d.classList.add('over');
      });
      d.addEventListener('dragleave', () => d.classList.remove('over'));
      d.addEventListener('drop', (ev) => {
        ev.preventDefault();
        const src = drag;
        endDrag();
        if (src) window.nc.dropTab({ ...argOf(src), slot: z.id });
      });
      box.append(d);
    }
  }

  function sigOf() {
    return JSON.stringify([lay.view, lay.overlay, Boolean(drag), lay.dividers.length, lay.focus, lay.strips, lay.panes.map((p) => [p.slot, p.status, p.key, p.label, p.error && p.error.message, p.stack.map((x) => `${x.key}:${x.selected}`)])]);
  }

  function positionPanes() {
    for (const c of $('panes').children) {
      if (c.dataset.empty !== undefined) {
        const a = lay.zones;
        placeRect(c, { x: a[0].rect.x, y: a[0].rect.y, w: a[2].rect.w, h: a[0].rect.h + a[2].rect.h });
      } else if (c.dataset.divider !== undefined) placeRect(c, lay.dividers[Number(c.dataset.divider)].rect);
      else if (c.dataset.strip !== undefined) placeRect(c, { x: lay.panes[Number(c.dataset.strip)].rect.x, y: lay.panes[Number(c.dataset.strip)].rect.y, w: lay.panes[Number(c.dataset.strip)].rect.w, h: lay.grid.strip });
      else if (c.dataset.pane !== undefined) placeRect(c, lay.panes[Number(c.dataset.pane)].view);
      else if (c.dataset.zone !== undefined) placeRect(c, lay.zones.find((z) => z.id === c.dataset.zone).rect);
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
    if (drag) {
      zoneLayer(box);
      return;
    }
    if (lay.overlay) return;
    if (!lay.panes.length) {
      const a = lay.zones;
      const m = el('div', 'pane-msg');
      placeRect(m, { x: a[0].rect.x, y: a[0].rect.y, w: a[2].rect.w, h: a[0].rect.h + a[2].rect.h });
      m.append(el('p', '', 'Add a node, then open a page from the list. Drag a page into the Left, Right or Lower slot, or onto this area, to show pages together.'));
      m.dataset.empty = '1';
      box.append(m);
    }
    lay.panes.forEach((pane, i) => {
      if (lay.strips && pane.key) box.append(strip(pane, i));
      if (pane.status === 'ok') return;
      let m;
      if (pane.status === 'failed') {
        m = failPanel(pane);
      } else {
        m = el('div', 'pane-msg');
        placeRect(m, pane.view);
        m.append(el('p', '', 'Connecting…'));
      }
      m.dataset.pane = String(i);
      box.append(m);
    });
    lay.dividers.forEach((dv, i) => {
      const d = el('div', dv.drag ? 'divider cols' : 'divider gapline');
      placeRect(d, dv.rect);
      d.dataset.divider = String(i);
      if (dv.drag) {
        d.addEventListener('pointerdown', (ev) => startDivider(ev, d));
        d.addEventListener('dblclick', () => window.nc.setRatio(0.5));
      }
      box.append(d);
    });
  }

  function render() {
    renderTabs();
    renderSlots();
    renderSingles();
    renderNodes();
    renderSplits();
    renderPanes();
  }

  function onLayout(next) {
    lay = next;
    const root = document.documentElement.style;
    root.setProperty('--sidebar', `${lay.grid.sidebar}px`);
    root.setProperty('--header', `${lay.grid.header}px`);
    if (drag || menuOpen) {
      renderPanes();
      return;
    }
    render();
  }

  function buildPortInputs() {
    const box = $('f-ports');
    box.textContent = '';
    for (const p of pages) {
      const label = el('label', '', `${p.label} port`);
      const input = el('input');
      input.id = `f-port-${p.id}`;
      input.type = 'number';
      input.min = '1';
      input.max = '65535';
      label.append(input);
      box.append(label);
    }
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
    $('dlg').showModal();
    setOverlay();
    $('f-name').focus();
  }

  function closeDialog() {
    $('dlg').close();
    setOverlay();
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

  function openNameDialog() {
    $('n-name').value = '';
    $('n-error').hidden = true;
    $('dlg-name').showModal();
    setOverlay();
    $('n-name').focus();
  }

  function closeNameDialog() {
    $('dlg-name').close();
    setOverlay();
  }

  async function saveName(ev) {
    ev.preventDefault();
    const r = await window.nc.saveSplit($('n-name').value);
    if (r.error) {
      $('n-error').textContent = r.error;
      $('n-error').hidden = false;
      return;
    }
    closeNameDialog();
    notice('Split saved.');
  }

  async function init() {
    const info = await window.nc.info();
    pages = info.pages;
    $('ver').textContent = `Version ${info.version}`;
    nodes = await window.nc.listNodes();
    buildPortInputs();
    $('add').addEventListener('click', () => openDialog(null));
    $('import').addEventListener('click', importNodes);
    $('export').addEventListener('click', exportNodes);
    $('reload').addEventListener('click', () => {
      const t = lay && lay.tabs.find((x) => x.focused);
      if (t) window.nc.reloadTab(t.key);
    });
    $('save-split').addEventListener('click', openNameDialog);
    for (const b of $('views').querySelectorAll('button')) b.addEventListener('click', () => window.nc.setView(b.dataset.view));
    $('f-cancel').addEventListener('click', closeDialog);
    $('dlg').addEventListener('close', setOverlay);
    $('form').addEventListener('submit', saveDialog);
    $('f-delete').addEventListener('click', removeNode);
    $('f-pin-clear').addEventListener('click', () => {
      if (editing) editing.pin = '';
      $('f-pin-row').hidden = true;
    });
    $('n-cancel').addEventListener('click', closeNameDialog);
    $('dlg-name').addEventListener('close', setOverlay);
    $('form-name').addEventListener('submit', saveName);
    document.addEventListener('mousedown', (ev) => {
      if (menuOpen && !$('menu').contains(ev.target)) closeMenu();
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        closeMenu();
        endDrag();
      }
    });
    document.addEventListener('dragend', endDrag);
    document.addEventListener('drop', () => setTimeout(endDrag, 0));
    window.addEventListener('blur', closeMenu);
    window.nc.onLayout(onLayout);
    window.nc.onNotice((n) => notice(n.text, n.bad));
    onLayout(await window.nc.getLayout());
  }

  init();
})();
