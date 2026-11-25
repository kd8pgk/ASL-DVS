(function () {
  const $ = (id) => document.getElementById(id);
  let editing = false;
  let askId = 0;

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
    const rows = (s.notice ? 1 : 0) + (s.ask ? 1 : 0) + (s.popup ? 1 : 0);
    document.documentElement.style.setProperty('--top', `${44 + 34 * rows}px`);
    show($('blank'), s.blank);
    show($('blank-ram'), !s.ram);
    renderError(s.error);
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
  window.nb.onState(render);
  window.nb.onFocusAddress(() => $('addr').focus());
  window.nb.state().then(render);
  $('addr').focus();
})();
