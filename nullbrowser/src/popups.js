const DL = require('./download');
const BL = require('./blocklist');

function describeFn() {
  var NB = {};
  NB.hostOf = function (u) {
    try {
      return new URL(u, document.baseURI).hostname.toLowerCase();
    } catch (e) {
      return '';
    }
  };
  NB.selector = function (el) {
    function ok(s) {
      try {
        var n = document.querySelectorAll(s);
        return n.length >= 1 && n.length <= 3 && Array.prototype.indexOf.call(n, el) >= 0;
      } catch (e) {
        return false;
      }
    }
    var plain = /^[A-Za-z_][A-Za-z0-9_-]*$/;
    var tag = el.tagName.toLowerCase();
    var s;
    if (el.id && plain.test(el.id) && !/\d{4,}/.test(el.id)) {
      s = '#' + el.id;
      if (ok(s)) return s;
    }
    var cls = Array.prototype.filter.call(el.classList || [], function (c) {
      return plain.test(c) && c.length < 40 && !/\d{3,}/.test(c);
    });
    for (var i = 0; i < cls.length; i++) {
      s = tag + '.' + cls[i];
      if (ok(s)) return s;
    }
    if (cls.length > 1) {
      s = tag + '.' + cls[0] + '.' + cls[1];
      if (ok(s)) return s;
    }
    var role = el.getAttribute('role');
    if (role && plain.test(role)) {
      s = tag + '[role="' + role + '"]';
      if (ok(s)) return s;
    }
    var parts = [];
    var cur = el;
    for (var depth = 0; cur && cur.nodeType === 1 && depth < 5; depth++) {
      var t = cur.tagName.toLowerCase();
      if (cur.id && plain.test(cur.id) && !/\d{4,}/.test(cur.id)) {
        parts.unshift('#' + cur.id);
        break;
      }
      var n = 1;
      var sib = cur;
      while ((sib = sib.previousElementSibling)) if (sib.tagName === cur.tagName) n++;
      parts.unshift(t + ':nth-of-type(' + n + ')');
      cur = cur.parentElement;
    }
    s = parts.join('>');
    return ok(s) ? s : '';
  };
  NB.info = function (el, kind) {
    var here = location.hostname.toLowerCase();
    var seen = {};
    var hosts = [];
    var nodes = [el].concat(Array.prototype.slice.call(el.querySelectorAll('iframe,a[href],form[action],img[src],script[src],link[href]'), 0, 30));
    for (var i = 0; i < nodes.length; i++) {
      var raw = nodes[i].src || nodes[i].href || nodes[i].action || '';
      var h = NB.hostOf(typeof raw === 'string' ? raw : '');
      if (h && h !== here && !seen[h]) {
        seen[h] = 1;
        hosts.push(h);
      }
    }
    var r = el.getBoundingClientRect();
    var cs = getComputedStyle(el);
    return {
      kind: kind,
      tag: el.tagName.toLowerCase(),
      text: String(el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim().slice(0, 80),
      selector: NB.selector(el),
      frameHost: here,
      topHost: '',
      hosts: hosts.slice(0, 6),
      w: Math.round(r.width),
      h: Math.round(r.height),
      fixed: cs.position === 'fixed' || cs.position === 'sticky',
      z: parseInt(cs.zIndex, 10) || 0,
    };
  };
  return NB;
}

function findFn(describe) {
  var NB = describe();
  var out = [];
  var vw = Math.max(window.innerWidth, 1);
  var vh = Math.max(window.innerHeight, 1);
  var all = document.querySelectorAll('body *');
  for (var i = 0; i < all.length && i < 8000 && out.length < 30; i++) {
    var el = all[i];
    var cs = getComputedStyle(el);
    var pos = cs.position;
    if (el.tagName === 'IFRAME') {
      var fr = el.getBoundingClientRect();
      var fh = NB.hostOf(el.src || '');
      if (fh && fh !== location.hostname.toLowerCase() && cs.visibility !== 'hidden' && cs.display !== 'none' && fr.width * fr.height > 3000) {
        var fi = NB.info(el, 'frame');
        if (fh && fi.hosts.indexOf(fh) < 0) fi.hosts.unshift(fh);
        out.push(fi);
        continue;
      }
    }
    if (pos !== 'fixed' && pos !== 'sticky') continue;
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    var r = el.getBoundingClientRect();
    var share = (Math.min(r.right, vw) - Math.max(r.left, 0)) * (Math.min(r.bottom, vh) - Math.max(r.top, 0)) / (vw * vh);
    var z = parseInt(cs.zIndex, 10) || 0;
    if (share >= 0.15 || (z >= 1000 && share >= 0.02)) {
      var info = NB.info(el, share >= 0.7 ? 'cover' : 'overlay');
      out.push(info);
    }
  }
  return out;
}

function pickFn(describe, token) {
  var NB = describe();
  return new Promise(function (resolve) {
    var box = document.createElement('div');
    box.setAttribute('style', 'position:fixed;z-index:2147483647;pointer-events:none;border:3px solid #ffd040;background:rgba(255,208,64,.18);left:0;top:0;width:0;height:0');
    document.documentElement.appendChild(box);
    var done = false;
    var timer;
    function stop(value) {
      if (done) return;
      done = true;
      clearTimeout(timer);
      ['mouseover', 'mousedown', 'mouseup', 'pointerdown', 'pointerup', 'click', 'auxclick', 'contextmenu'].forEach(function (t) {
        window.removeEventListener(t, onEvent, true);
      });
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('nb-pick-' + token, onCancel, true);
      box.remove();
      resolve(value);
    }
    function onEvent(ev) {
      if (!ev.isTrusted) return;
      var el = ev.target;
      if (!el || el.nodeType !== 1) return;
      if (ev.type === 'mouseover') {
        var r = el.getBoundingClientRect();
        box.style.left = r.left + 'px';
        box.style.top = r.top + 'px';
        box.style.width = r.width + 'px';
        box.style.height = r.height + 'px';
        return;
      }
      ev.preventDefault();
      ev.stopImmediatePropagation();
      if (ev.type === 'click') stop(NB.info(el, 'picked'));
    }
    function onKey(ev) {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        stop(null);
      }
    }
    function onCancel() {
      stop(null);
    }
    ['mouseover', 'mousedown', 'mouseup', 'pointerdown', 'pointerup', 'click', 'auxclick', 'contextmenu'].forEach(function (t) {
      window.addEventListener(t, onEvent, true);
    });
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('nb-pick-' + token, onCancel, true);
    timer = setTimeout(function () {
      stop(null);
    }, 45000);
  });
}

function cancelFn(token) {
  window.dispatchEvent(new Event('nb-pick-' + token));
  return true;
}

function outlineFn(sel) {
  var el;
  try {
    el = document.querySelector(sel);
  } catch (e) {
    return false;
  }
  if (!el) return false;
  var r = el.getBoundingClientRect();
  var box = document.createElement('div');
  box.setAttribute('style', 'position:fixed;z-index:2147483647;pointer-events:none;border:4px solid #ffd040;background:rgba(255,208,64,.25);left:' + r.left + 'px;top:' + r.top + 'px;width:' + r.width + 'px;height:' + r.height + 'px');
  document.documentElement.appendChild(box);
  setTimeout(function () {
    box.remove();
  }, 2000);
  return true;
}

function applyFn(css) {
  var old = document.querySelectorAll('style[data-nb-block]');
  for (var i = 0; i < old.length; i++) old[i].remove();
  if (css) {
    var s = document.createElement('style');
    s.setAttribute('data-nb-block', '1');
    s.textContent = css;
    (document.head || document.documentElement).appendChild(s);
  }
  return true;
}

function call(fn, ...args) {
  const encoded = args.map((a) => (typeof a === 'function' ? `(${a.toString()})` : JSON.stringify(a)));
  return `(${fn.toString()})(${encoded.join(',')})`;
}

function frameList(wc) {
  const out = [];
  try {
    const top = wc.mainFrame;
    for (const f of top.framesInSubtree) {
      if (f.detached) continue;
      if (f !== top && (!f.url || f.url === 'about:blank')) continue;
      out.push({ frame: f, main: f === top });
    }
  } catch {
    return [];
  }
  return out;
}

function sanitizeItem(raw, topHost) {
  if (!raw || typeof raw !== 'object') return null;
  const str = (v, n) => String(v === undefined || v === null ? '' : v).replace(/[\u0000-\u001f\u007f]/g, ' ').slice(0, n);
  const hosts = [];
  for (const h of Array.isArray(raw.hosts) ? raw.hosts : []) {
    const c = BL.cleanHost(h);
    if (c && !hosts.includes(c)) hosts.push(c);
    if (hosts.length >= 6) break;
  }
  const frameHost = BL.cleanHost(raw.frameHost) || str(raw.frameHost, 100).toLowerCase();
  const kinds = ['frame', 'overlay', 'cover', 'picked'];
  return {
    kind: kinds.includes(raw.kind) ? raw.kind : 'overlay',
    tag: str(raw.tag, 20).toLowerCase(),
    text: str(raw.text, 80),
    selector: BL.validSelector(str(raw.selector, BL.MAX_SELECTOR)),
    frameHost,
    thirdParty: Boolean(frameHost) && frameHost !== topHost,
    hosts,
    w: Math.max(0, Math.min(99999, Math.round(Number(raw.w) || 0))),
    h: Math.max(0, Math.min(99999, Math.round(Number(raw.h) || 0))),
    fixed: Boolean(raw.fixed),
    z: Math.max(-1, Math.min(2147483647, Math.round(Number(raw.z) || 0))),
  };
}

async function findAll(wc, topHost) {
  const frames = frameList(wc);
  const got = await DL.collectFrames(frames, async (f) => ({ items: await f.frame.executeJavaScript(call(findFn, describeFn), false) }), 4000);
  const out = [];
  for (const it of got.items) {
    const s = sanitizeItem(it, topHost);
    if (s) out.push(s);
  }
  return { items: out, failed: got.failed + (got.mainFailed ? 1 : 0) };
}

async function pickOne(wc, topHost, token) {
  const frames = frameList(wc);
  let found = null;
  const runs = frames.map((f) =>
    f.frame.executeJavaScript(call(pickFn, describeFn, token), false).then(
      (r) => {
        if (r && !found) {
          found = r;
          cancelAll(wc, token);
        }
        return r;
      },
      () => null,
    ),
  );
  await Promise.all(runs);
  return found ? sanitizeItem(found, topHost) : null;
}

function cancelAll(wc, token) {
  for (const f of frameList(wc)) f.frame.executeJavaScript(call(cancelFn, token), false).catch(() => {});
}

async function applyCss(wc, cssForHost) {
  for (const f of frameList(wc)) {
    let host = '';
    try {
      host = new URL(f.frame.url).hostname.toLowerCase();
    } catch {
      host = '';
    }
    if (!host) continue;
    f.frame.executeJavaScript(call(applyFn, cssForHost(host)), false).catch(() => {});
  }
}

async function outline(wc, frameHost, selector) {
  for (const f of frameList(wc)) {
    let host = '';
    try {
      host = new URL(f.frame.url).hostname.toLowerCase();
    } catch {
      host = '';
    }
    if (host !== frameHost) continue;
    f.frame.executeJavaScript(call(outlineFn, selector), false).catch(() => {});
  }
}

module.exports = { describeFn, findFn, pickFn, cancelFn, outlineFn, applyFn, call, frameList, sanitizeItem, findAll, pickOne, cancelAll, applyCss, outline };
