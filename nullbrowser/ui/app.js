(function () {
  const $ = (id) => document.getElementById(id);
  let editing = false;
  let askId = 0;
  let leaveId = 0;
  let bmOpen = false;
  let fastJsNow = false;
  let lineNow = { mode: 'auto', images: true, saveData: false, readAhead: false, open: false };
  const NEXT_MODE = { auto: 'on', on: 'off', off: 'auto' };
  const MODE_LABEL = { auto: 'Slow: Auto', on: 'Slow: On', off: 'Slow: Off' };

  function renderLine(l) {
    lineNow = l;
    const line = $('line');
    line.textContent = l.active ? 'Slow' : 'Line';
    line.classList.toggle('on', Boolean(l.active) || !l.images);
    line.setAttribute('aria-expanded', l.open ? 'true' : 'false');
    show($('lineset'), Boolean(l.open));
    $('ls-mode').textContent = MODE_LABEL[l.mode] || 'Slow: Auto';
    $('ls-images').textContent = l.images ? 'Images: On' : 'Images: Off';
    $('ls-save').textContent = l.saveData ? 'Save-Data: On' : 'Save-Data: Off';
    $('ls-ahead').textContent = l.readAhead ? 'Read ahead: On' : 'Read ahead: Off';
    $('ls-shotwin').checked = Boolean(l.shotWindow);
    const loading = Boolean(l.active && (l.busy || l.retrying));
    show($('linebar'), loading || Boolean(l.ahead));
    const parts = [];
    if (loading) {
      parts.push('Slow line');
      if (l.retrying) parts.push('the line dropped, trying again');
      if (l.total) parts.push(`image ${Math.min(l.done + 1, l.total)} of ${l.total}, in viewing order`);
      if (l.rate) parts.push(l.rate);
    }
    if (l.ahead) parts.push(l.ahead);
    $('linebar-text').textContent = parts.join(' \u00b7 ');
    show($('ls-stop'), loading);
    return (l.open ? 1 : 0) + (loading || l.ahead ? 1 : 0);
  }

  function renderBookmarks(list) {
    const ul = $('bm-list');
    ul.textContent = '';
    for (const b of list) {
      const li = document.createElement('li');
      const link = document.createElement('button');
      link.type = 'button';
      link.className = 'bm-link';
      link.title = b.url;
      link.textContent = b.title || b.url;
      link.addEventListener('click', () => {
        bmOpen = false;
        show($('bm-panel'), false);
        go(b.url);
      });
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'bm-remove';
      rm.setAttribute('aria-label', `Remove ${b.title || b.url}`);
      rm.textContent = '✕';
      rm.addEventListener('click', (ev) => {
        ev.stopPropagation();
        window.nb.removeBookmark(b.id);
      });
      li.appendChild(link);
      li.appendChild(rm);
      ul.appendChild(li);
    }
    show($('bm-empty'), list.length === 0);
    $('bm').textContent = list.length ? `★ ${list.length}` : '☆';
  }

  function show(el, on) {
    el.hidden = !on;
  }

  function render(s) {
    if (!s) return;
    $('back').disabled = !s.canBack;
    $('forward').disabled = !s.canForward;
    $('reload').textContent = s.loading ? '✕' : '⟳';
    $('reload').title = s.loading ? 'Stop (Esc)' : 'Reload (Ctrl+R)';
    if (!editing) $('addr').value = s.error && s.error.url ? s.error.url : s.url;
    const sec = $('sec');
    if (s.url && s.secure) {
      sec.textContent = 'Secure';
      sec.className = 'sec ok';
      show(sec, true);
    } else if (s.url && s.insecure) {
      sec.textContent = 'Not secure';
      sec.className = 'sec bad';
      show(sec, true);
    } else {
      show(sec, false);
    }
    document.title = s.title ? `${s.title} - Null Browser` : 'Null Browser';
    show($('notice'), Boolean(s.notice));
    $('notice').textContent = s.notice || '';
    askId = s.ask ? s.ask.id : 0;
    show($('ask'), Boolean(s.ask));
    if (s.ask) {
      $('ask-text').textContent = s.ask.busy ? `${s.ask.text} Loading\u2026` : s.ask.text;
      $('ask-open').disabled = s.ask.busy;
      $('ask-cancel').disabled = s.ask.busy;
    }
    show($('popbar'), Boolean(s.popup));
    $('pop-text').textContent = s.popup ? `A pop-up from ${s.popup} was blocked.` : '';
    fastJsNow = Boolean(s.fastJs);
    $('fastjs').textContent = s.fastJs ? 'JIT: On' : 'JIT: Off';
    $('fastjs').title = s.fastJs
      ? 'Faster JavaScript is on for this run. Turning it off restarts Null Browser.'
      : 'Turn on faster JavaScript (restarts Null Browser now; off again next time you start it).';
    leaveId = s.leave ? s.leave.id : 0;
    show($('leavebar'), Boolean(s.leave));
    if (s.leave) $('leave-text').textContent = s.leave.text;
    const jsAsking = s.jsAsk !== null && s.jsAsk !== undefined;
    show($('jsbar'), jsAsking);
    if (jsAsking) {
      $('jsbar-text').textContent = s.jsAsk
        ? 'Turn on faster JavaScript? Null Browser restarts now, and goes back to JIT off the next time you start it.'
        : 'Turn off faster JavaScript and go back to JIT off? Null Browser restarts now.';
    }
    const lineRows = renderLine(s.line || lineNow);
    show($('shotbar'), Boolean(s.shot));
    if (s.shot) {
      $('shot-text').textContent = s.shot.text;
      $('shot-save').disabled = s.shot.busy;
      $('shot-cancel').disabled = s.shot.busy;
    }
    renderDownloads(s.dl || {});
    const dlRows = (s.dl && s.dl.asking ? 1 : 0) + (s.dl && s.dl.queue && s.dl.queue.length ? 1 : 0);
    const rows = (s.notice ? 1 : 0) + (s.ask ? 1 : 0) + (s.popup ? 1 : 0) + (jsAsking ? 1 : 0) + (s.leave ? 1 : 0) + (s.shot ? 1 : 0) + lineRows + dlRows;
    document.documentElement.style.setProperty('--top', `${44 + 34 * rows}px`);
    show($('blank'), s.blank);
    show($('blank-ram'), !s.ram);
    renderBookmarks(s.bookmarks || []);
    renderError(s.error);
  }

  let dlState = {};
  let dlWarnShown = false;

  function linkRow(item) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'dl-item';
    b.title = item.href;
    const name = document.createElement('b');
    name.textContent = item.name;
    const where = document.createElement('small');
    where.textContent = `${item.path}  ·  ${item.host}`;
    b.appendChild(name);
    b.appendChild(where);
    b.addEventListener('click', () => window.nb.dlOne(item.href));
    const badge = document.createElement('span');
    badge.className = 'dl-badge';
    badge.textContent = { pdf: 'PDF', mp3: 'MP3', wav: 'WAV', webm: 'WebM', mp4: 'MP4', jpg: 'JPG', mpeg: 'MPEG', webp: 'WebP' }[item.kind] || item.kind;
    li.appendChild(b);
    li.appendChild(badge);
    return li;
  }

  function queueRow(item) {
    const li = document.createElement('li');
    const name = document.createElement('b');
    name.className = 'dl-item';
    name.style.display = 'block';
    name.textContent = item.name;
    name.title = item.href;
    const state = document.createElement('span');
    const labels = { waiting: 'Waiting', downloading: 'Downloading…', done: `Saved as ${item.saved}`, refused: item.reason, login: item.reason, cancelled: 'Cancelled' };
    state.className = 'dl-state' + (item.state === 'done' ? ' ok' : item.state === 'refused' || item.state === 'login' ? ' bad' : '');
    state.textContent = labels[item.state] || item.state;
    state.style.flex = '1';
    li.appendChild(name);
    li.appendChild(state);
    if (item.state === 'waiting' || item.state === 'downloading') {
      const c = document.createElement('button');
      c.type = 'button';
      c.textContent = 'Cancel';
      c.addEventListener('click', () => window.nb.dlCancel(item.id));
      li.appendChild(c);
    } else if (item.state === 'login') {
      const r = document.createElement('button');
      r.type = 'button';
      r.textContent = 'Retry with sign-in';
      r.addEventListener('click', () => window.nb.dlRetry(item.id));
      li.appendChild(r);
    }
    if (item.state !== 'waiting' && item.state !== 'downloading') {
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.textContent = '✕';
      rm.setAttribute('aria-label', `Remove ${item.name}`);
      rm.addEventListener('click', () => window.nb.dlRemove(item.id));
      li.appendChild(rm);
    }
    return li;
  }

  function renderDownloads(d) {
    dlState = d;
    const dl = $('dl');
    dl.classList.toggle('on', Boolean(d.allowed));
    dl.setAttribute('aria-expanded', d.panel ? 'true' : 'false');
    dl.title = d.allowed ? 'Download files from this page' : 'Downloads are off. Click to allow them for this run.';
    show($('dlallow'), Boolean(d.asking));
    const list = d.list || [];
    const queue = d.queue || [];
    show($('dl-panel'), Boolean(d.panel && d.allowed));
    const ul = $('dl-list');
    ul.textContent = '';
    if (d.panel && d.allowed) {
      const all = document.createElement('li');
      const allBtn = document.createElement('button');
      allBtn.type = 'button';
      allBtn.className = 'dl-item dl-all';
      allBtn.textContent = list.length ? `Download all ${list.length} files…` : 'Download all';
      allBtn.disabled = list.length === 0;
      allBtn.addEventListener('click', () => window.nb.dlWarn(true));
      all.appendChild(allBtn);
      ul.appendChild(all);
      for (const item of list) ul.appendChild(linkRow(item));
      const notes = [];
      const err = String(d.scanError || '');
      if (err === 'page') notes.push('Could not read this page.');
      else if (err.startsWith('frames:')) notes.push(`${err.slice(7)} embedded frame${err === 'frames:1' ? '' : 's'} could not be read.`);
      if (d.probing > 0) notes.push(`Checking ${d.probing} more link${d.probing === 1 ? '' : 's'}…`);
      if (d.total > list.length) notes.push(`Showing the first ${list.length} of ${d.total} files.`);
      if (d.skipped > 0) notes.push(`${d.skipped} more link${d.skipped === 1 ? '' : 's'} were not checked (limit 100).`);
      $('dl-note').textContent = notes.join(' ');
      show($('dl-note'), notes.length > 0);
      show($('dl-rescanrow'), err === 'page');
      show($('dl-empty'), list.length === 0 && !err && !(d.probing > 0));
    }
    show($('dl-warn'), Boolean(d.warn && d.allowed && list.length));
    if (d.warn && d.allowed && list.length) {
      const n = list.length;
      $('dl-warn-title').textContent = `Download all ${n} files from this page?`;
      $('dl-warn-text').textContent = 'These files download one at a time into your Downloads folder, up to 200 files and 2 GB in total. Each file is checked, but a check cannot prove a file is safe. Only do this for a page you trust.';
      $('dl-warn-go').textContent = `Download all ${n} files`;
      if (!dlWarnShown) $('dl-warn-cancel').focus();
      dlWarnShown = true;
    } else {
      dlWarnShown = false;
    }
    const qDone = queue.filter((i) => i.state === 'done').length;
    const current = queue.find((i) => i.state === 'downloading');
    show($('dlqbar'), queue.length > 0);
    $('dlq-text').textContent = `Queue: ${qDone} of ${queue.length} done${current ? ` · ${current.name}` : ''}`;
    show($('dl-qpanel'), Boolean(d.queuePanel && queue.length));
    const ql = $('dl-qlist');
    ql.textContent = '';
    for (const item of queue) ql.appendChild(queueRow(item));
    show($('dl-qempty'), queue.length === 0);
  }

  function renderError(e) {
    show($('msg'), Boolean(e));
    if (!e) return;
    const main = $('msg-main');
    show($('msg-mono'), false);
    show(main, false);
    if (e.kind === 'nohttps') {
      $('msg-title').textContent = 'This site has no secure version';
      $('msg-text').textContent = `${e.host} did not answer over https. If you open it anyway, everything you send and see can be read or changed on the way.`;
      main.textContent = 'Open anyway (not secure)';
      main.onclick = () => window.nb.allowHttp();
      show(main, true);
    } else if (e.kind === 'cert') {
      $('msg-title').textContent = 'This site’s certificate is not valid';
      $('msg-text').textContent = e.trustable
        ? `${e.host} is on your own network. If this is your own device, check that the fingerprint matches before trusting it. It is trusted only until Null Browser closes.`
        : `${e.host} could not prove who it is (${e.message}). The page was not opened.`;
      if (e.shown) {
        $('msg-mono').textContent = `SHA-256 ${e.shown}`;
        show($('msg-mono'), true);
      }
      if (e.trustable) {
        main.textContent = 'Trust for this session';
        main.onclick = () => window.nb.trustCert();
        show(main, true);
      }
    } else {
      $('msg-title').textContent = 'The page could not be opened';
      $('msg-text').textContent = e.message || 'It did not load.';
    }
  }

  function go(text) {
    window.nb.go(text);
  }

  for (const type of ['copy', 'cut', 'paste', 'drop']) {
    document.addEventListener(type, (ev) => {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }, true);
  }
  document.addEventListener('auxclick', (ev) => {
    if (ev.button === 1) ev.preventDefault();
  }, true);
  document.addEventListener('mouseup', (ev) => {
    if (ev.button === 1) ev.preventDefault();
  }, true);
  $('form').addEventListener('submit', (ev) => {
    ev.preventDefault();
    editing = false;
    go($('addr').value);
    $('addr').blur();
  });
  $('addr').addEventListener('focus', () => {
    editing = true;
    $('addr').select();
  });
  $('addr').addEventListener('blur', () => {
    editing = false;
  });
  $('addr').addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') {
      editing = false;
      window.nb.state().then(render);
      $('addr').blur();
    }
  });
  $('back').addEventListener('click', () => window.nb.nav('back'));
  $('forward').addEventListener('click', () => window.nb.nav('forward'));
  $('reload').addEventListener('click', async () => {
    const s = await window.nb.state();
    window.nb.nav(s && s.loading ? 'stop' : 'reload');
  });
  $('home').addEventListener('click', () => window.nb.nav('home'));
  $('msg-retry').addEventListener('click', () => window.nb.nav('reload'));
  $('ask-open').addEventListener('click', () => window.nb.fileAnswer(askId, true));
  $('ask-cancel').addEventListener('click', () => window.nb.fileAnswer(askId, false));
  $('pop-allow').addEventListener('click', () => window.nb.allowSite());
  $('pop-close').addEventListener('click', () => window.nb.dismissPopup());
  $('bm').addEventListener('click', (ev) => {
    ev.stopPropagation();
    bmOpen = !bmOpen;
    show($('bm-panel'), bmOpen);
  });
  $('bm-import').addEventListener('click', () => window.nb.importBookmarks());
  $('line').addEventListener('click', () => window.nb.lineSet('open', !lineNow.open));
  $('ls-close').addEventListener('click', () => window.nb.lineSet('open', false));
  $('ls-mode').addEventListener('click', () => window.nb.lineSet('mode', NEXT_MODE[lineNow.mode] || 'auto'));
  $('ls-images').addEventListener('click', () => window.nb.lineSet('images', !lineNow.images));
  $('ls-save').addEventListener('click', () => window.nb.lineSet('saveData', !lineNow.saveData));
  $('ls-ahead').addEventListener('click', () => window.nb.lineSet('readAhead', !lineNow.readAhead));
  $('ls-stop').addEventListener('click', () => window.nb.stopImages());
  $('ls-shot').addEventListener('click', () => window.nb.screenshot());
  $('ls-shotwin').addEventListener('change', (ev) => window.nb.lineSet('shotWindow', ev.target.checked));
  $('shot-save').addEventListener('click', () => window.nb.shotAnswer(true));
  $('shot-cancel').addEventListener('click', () => window.nb.shotAnswer(false));
  $('fastjs').addEventListener('click', () => window.nb.requestFastJs(!fastJsNow));
  let launcher = null;
  function renderLauncher() {
    const b = $('launcher');
    if (!launcher || !launcher.available) {
      b.hidden = true;
      return;
    }
    b.hidden = false;
    if (!launcher.installed) {
      b.textContent = 'Add to menu';
      b.title = 'Add Null Browser to the app menu and the desktop (writes a few files to your home folder)';
    } else if (!launcher.fromInstalled) {
      b.textContent = 'Update menu copy';
      b.title = `Replace the copy the menu starts (${launcher.installedVersion || 'unknown version'}) with this one`;
    } else {
      b.textContent = 'Remove from menu';
      b.title = 'Take Null Browser out of the app menu and off the desktop';
    }
  }
  async function launcherClick() {
    if (!launcher) return;
    const removing = launcher.installed && launcher.fromInstalled;
    const r = removing ? await window.nb.removeLauncher() : await window.nb.addLauncher();
    if (r.status) launcher = r.status;
    renderLauncher();
  }
  $('launcher').addEventListener('click', launcherClick);
  window.nb.launcherStatus().then((st) => {
    launcher = st;
    renderLauncher();
  });
  $('ramopen').addEventListener('click', () => window.nb.openRam());
  $('wipe').addEventListener('click', () => window.nb.wipeAll());
  $('leave-go').addEventListener('click', () => window.nb.leaveAnswer(leaveId, true));
  $('leave-stay').addEventListener('click', () => window.nb.leaveAnswer(leaveId, false));
  $('jsbar-yes').addEventListener('click', () => window.nb.confirmFastJs());
  $('jsbar-no').addEventListener('click', () => window.nb.cancelFastJs());
  document.addEventListener('click', (ev) => {
    if (bmOpen && ev.target !== $('bm') && !$('bm-panel').contains(ev.target)) {
      bmOpen = false;
      show($('bm-panel'), false);
    }
  });
  $('dl').addEventListener('click', () => {
    if (!dlState.allowed) {
      window.nb.dlAsk();
      return;
    }
    window.nb.dlPanel(!dlState.panel);
  });
  let panelSent = 0;
  function reportPanels() {
    let bottom = 0;
    for (const el of document.querySelectorAll('.panel')) {
      if (el.hidden) continue;
      bottom = Math.max(bottom, Math.ceil(el.getBoundingClientRect().bottom));
    }
    if (bottom !== panelSent) {
      panelSent = bottom;
      window.nb.panelSpace(bottom);
    }
  }
  const panelWatch = new ResizeObserver(reportPanels);
  for (const el of document.querySelectorAll('.panel')) panelWatch.observe(el);
  $('dl-rescan').addEventListener('click', () => window.nb.dlRescan());
  $('dl-close').addEventListener('click', () => window.nb.dlPanel(false));
  $('dl-yes').addEventListener('click', () => window.nb.dlAnswer(true));
  $('dl-no').addEventListener('click', () => window.nb.dlAnswer(false));
  $('dl-warn-cancel').addEventListener('click', () => window.nb.dlWarn(false));
  $('dl-warn-go').addEventListener('click', () => window.nb.dlAll());
  $('dl-qclose').addEventListener('click', () => window.nb.dlQueuePanel(false));
  $('dl-qclear').addEventListener('click', () => window.nb.dlClear());
  $('dlq-open').addEventListener('click', () => window.nb.dlQueuePanel(!dlState.queuePanel));
  $('dlq-cancel').addEventListener('click', () => window.nb.dlCancelAll());
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    if (dlState.warn) window.nb.dlWarn(false);
    else if (dlState.panel) window.nb.dlPanel(false);
    else if (dlState.queuePanel) window.nb.dlQueuePanel(false);
  });
  window.nb.onState(render);
  window.nb.onFocusAddress(() => $('addr').focus());
  window.nb.state().then(render);
  $('addr').focus();
})();
