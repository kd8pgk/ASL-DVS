const crypto = require('node:crypto');
const { ipcMain } = require('electron');
const V = require('./view');
const PU = require('./popups');
const { st } = require('./state');
const shared = require('./ctx');
const { own, line } = require('./slowline');

function collectFn(opts) {
  var root = document.documentElement;
  if (root.hasAttribute('data-nb-gallery')) return { done: true };
  var items = [];
  var imgs = 0;
  var chars = 0;
  var visited = 0;
  var skip = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, SVG: 1, CANVAS: 1, IFRAME: 1, OBJECT: 1, EMBED: 1, HEAD: 1, SELECT: 1, OPTION: 1, TEXTAREA: 1, INPUT: 1, BUTTON: 1, NAV: 1, FOOTER: 1, ASIDE: 1, FORM: 1, AUDIO: 1, VIDEO: 0 };
  var blocks = { H1: 1, H2: 1, H3: 1, H4: 1, H5: 1, H6: 1, P: 1, LI: 1, BLOCKQUOTE: 1, FIGCAPTION: 1, PRE: 1, DT: 1, DD: 1 };
  var inline = { A: 1, SPAN: 1, B: 1, I: 1, EM: 1, STRONG: 1, SMALL: 1, CODE: 1, MARK: 1, U: 1, SUB: 1, SUP: 1, ABBR: 1, CITE: 1, TIME: 1, LABEL: 1, FONT: 1, S: 1, Q: 1 };
  var roles = { navigation: 1, banner: 1, complementary: 1, contentinfo: 1, search: 1 };
  function largest(sets, fallback) {
    var best = '';
    var bestW = -1;
    for (var i = 0; i < sets.length; i++) {
      if (!sets[i]) continue;
      var parts = String(sets[i]).split(/,\s+|,(?=[^\s])/);
      for (var j = 0; j < parts.length && j < 30; j++) {
        var bits = parts[j].trim().split(/\s+/);
        if (!bits[0]) continue;
        var d = bits[1] || '';
        var w = /w$/.test(d) ? parseFloat(d) : /x$/.test(d) ? parseFloat(d) * 1000 : 1;
        if (w > bestW) {
          bestW = w;
          best = bits[0];
        }
      }
    }
    return best || fallback;
  }
  function addImg(src, href, w, h) {
    if (!src || imgs >= 400) return;
    imgs++;
    items.push({ k: 'img', src: src, href: href || '', w: w || 0, h: h || 0 });
  }
  function pictureOf(el, href) {
    var sets = [];
    var pic = el.parentElement && el.parentElement.tagName === 'PICTURE' ? el.parentElement : null;
    if (pic) {
      var srcs = pic.querySelectorAll('source');
      for (var i = 0; i < srcs.length && i < 8; i++) sets.push(srcs[i].getAttribute('srcset'));
    }
    sets.push(el.getAttribute('srcset') || el.getAttribute('data-srcset'));
    var fallback = el.getAttribute('data-src') || el.getAttribute('data-original') || el.getAttribute('data-lazy-src') || el.getAttribute('data-lazy') || el.getAttribute('src') || '';
    var src = largest(sets, fallback);
    var wa = el.getAttribute('width');
    var ha = el.getAttribute('height');
    var w = /^\d+$/.test(wa || '') ? parseInt(wa, 10) : 0;
    var h = /^\d+$/.test(ha || '') ? parseInt(ha, 10) : 0;
    addImg(src, href, w, h);
  }
  function hiddenEl(cs) {
    return cs.display === 'none' || cs.visibility === 'hidden';
  }
  var run = [];
  var runTag = 'p';
  function flush() {
    if (!run.length || !opts.text) {
      run = [];
      return;
    }
    var segs = [];
    var any = false;
    for (var i = 0; i < run.length; i++) {
      var seg = run[i];
      var t = runTag === 'pre' ? seg.t : seg.t.replace(/\s+/g, ' ');
      if (!t) continue;
      if (/\S/.test(t)) any = true;
      segs.push(seg.href ? { t: t, href: seg.href } : { t: t });
    }
    run = [];
    if (!any || chars > 200000 || items.length > 1900) return;
    var first = segs[0];
    var last = segs[segs.length - 1];
    if (runTag !== 'pre') {
      first.t = first.t.replace(/^\s+/, '');
      last.t = last.t.replace(/\s+$/, '');
    }
    var len = 0;
    for (var k = 0; k < segs.length; k++) len += segs[k].t.length;
    if (len < 2) return;
    chars += len;
    items.push({ k: 'text', tag: runTag, segs: segs });
  }
  function hasPicture(el) {
    return !!el.querySelector('img,picture,video');
  }
  function anchorHref(a) {
    var h = a.getAttribute('href');
    return h && !/^\s*(javascript|data|mailto|tel):/i.test(h) ? a.href : '';
  }
  function walk(el, tag, linkHref) {
    var kids = el.childNodes;
    for (var i = 0; i < kids.length; i++) {
      if (++visited > 20000) return;
      var n = kids[i];
      if (n.nodeType === 3) {
        run.push({ t: n.nodeValue, href: linkHref || '' });
        continue;
      }
      if (n.nodeType !== 1) continue;
      var tg = n.tagName;
      if (skip[tg] || tg === 'AUDIO') continue;
      var role = n.getAttribute('role');
      if (role && roles[role]) continue;
      if (n.hasAttribute('hidden') || n.getAttribute('aria-hidden') === 'true') continue;
      var cs = getComputedStyle(n);
      if (hiddenEl(cs)) continue;
      if (tg === 'BR') {
        run.push({ t: ' ', href: '' });
        continue;
      }
      if (tg === 'IMG') {
        flush();
        var wrap = n.closest('a');
        pictureOf(n, wrap ? anchorHref(wrap) : '');
        continue;
      }
      if (tg === 'PICTURE') {
        var im = n.querySelector('img');
        if (im) {
          flush();
          var an = n.closest('a');
          pictureOf(im, an ? anchorHref(an) : '');
        }
        continue;
      }
      if (tg === 'VIDEO') {
        var poster = n.getAttribute('poster');
        if (poster) {
          flush();
          addImg(poster, '', 0, 0);
        }
        continue;
      }
      if (inline[tg] && !hasPicture(n)) {
        var href = tg === 'A' ? anchorHref(n) : linkHref;
        walk(n, tag, href);
        continue;
      }
      flush();
      var bg = cs.backgroundImage;
      if (bg && bg !== 'none') {
        var m = /url\(["']?([^"')]+)["']?\)/.exec(bg);
        var r = n.getBoundingClientRect();
        if (m && r.width >= 200 && r.height >= 150) addImg(m[1], '', Math.round(r.width), Math.round(r.height));
      }
      var next = blocks[tg] ? tg.toLowerCase() : tag;
      var prevTag = runTag;
      runTag = next;
      walk(n, next, '');
      flush();
      runTag = prevTag;
    }
  }
  var body = document.body;
  if (body) {
    runTag = 'p';
    walk(body, 'p', '');
    flush();
  }
  return { title: document.title || '', items: items, visited: visited };
}

function contents() {
  return st.view && !st.view.webContents.isDestroyed() ? st.view.webContents : null;
}

function tierState() {
  return { tier: st.viewTier, label: V.LABELS[st.viewTier], short: V.SHORT[st.viewTier], asking: st.viewAsking };
}

function viewState() {
  return tierState();
}

function headersFor(headers) {
  return V.pageHeaders(headers, st.viewTier, st.viewNonce);
}

function tokenFor(url) {
  if (!url) return '';
  if (st.viewFetch.size >= V.MAX_TOKENS) return '';
  const token = crypto.randomBytes(12).toString('hex');
  st.viewFetch.set(token, url);
  return `nbimg://f/${token}`;
}

function resetPage() {
  st.viewFetch.clear();
  st.viewBytes = 0;
  st.viewApplied += 1;
}

async function apply() {
  const wc = contents();
  const flags = V.flagsOf(st.viewTier);
  if (!wc || !flags.gallery) return;
  const url = shared.pageUrl();
  if (!/^https?:/.test(url)) return;
  const mark = st.viewApplied;
  let raw;
  try {
    raw = await wc.mainFrame.executeJavaScript(PU.call(collectFn, { text: flags.text, links: flags.links }), false);
  } catch {
    shared.say('This page could not be read for the picture view.');
    return;
  }
  if (!raw || raw.done) return;
  if (mark !== st.viewApplied || shared.pageUrl() !== url) return;
  const clean = V.sanitizeItems(raw, url, st.viewTier);
  const html = V.buildGallery({ title: clean.title, items: clean.items, nonce: st.viewNonce, tokenFor });
  try {
    await wc.mainFrame.executeJavaScript(`document.open();document.write(${JSON.stringify(html)});document.close();true`, false);
  } catch {
    shared.say('The picture view could not be shown for this page.');
  }
}

async function picture(token) {
  const url = st.viewFetch.get(token);
  const fail = (status) => new Response('', { status });
  if (!url) return fail(404);
  if (!line.images) return fail(204);
  if (st.viewBytes >= V.MAX_TOTAL_BYTES) return fail(413);
  own.add(url);
  try {
    const res = await st.ses.fetch(url, { credentials: 'omit', redirect: 'follow', headers: { Accept: 'image/avif,image/webp,image/png,image/jpeg,image/gif,image/*;q=0.8' } });
    if (!res.ok || !res.body) return fail(502);
    const declared = Number(res.headers.get('content-length'));
    if (declared > V.MAX_PIC_BYTES) return fail(413);
    const reader = res.body.getReader();
    const chunks = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.length;
      if (total > V.MAX_PIC_BYTES) {
        reader.cancel().catch(() => {});
        return fail(413);
      }
      chunks.push(Buffer.from(value));
    }
    const buf = Buffer.concat(chunks);
    const mime = V.imageMimeOfHead(buf);
    if (!mime) return fail(415);
    st.viewBytes += buf.length;
    return new Response(buf, { headers: { 'content-type': mime, 'cache-control': 'no-store' } });
  } catch {
    return fail(502);
  } finally {
    own.delete(url);
  }
}

function setTier(tier) {
  const next = V.normalizeTier(tier);
  const changed = next !== st.viewTier;
  st.viewTier = next;
  st.viewAsking = false;
  const wc = contents();
  if (changed && wc && /^https?:/.test(shared.pageUrl())) wc.reload();
  shared.push();
}

function register(fromShell) {
  ipcMain.handle('view-set', (e, tier) => {
    if (!fromShell(e)) return { ok: false };
    setTier(tier);
    return { ok: true };
  });
  ipcMain.handle('view-tick', (e, key, on) => {
    if (!fromShell(e)) return { ok: false };
    setTier(V.applyTick(st.viewTier, String(key), on === true));
    return { ok: true };
  });
}

module.exports = { collectFn, viewState, headersFor, resetPage, apply, picture, register, setTier };
