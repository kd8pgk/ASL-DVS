const LABELS = ['Pictures only', 'Pictures and text', 'Pictures, text and links', 'Page layout and media, no scripts', 'Full page'];
const SHORT = ['Pictures', 'Text', 'Links', 'Layout', 'Full'];
const KEYS = { text: 1, links: 2, layout: 3, scripts: 4 };

const MAX_ITEMS = 400;
const MAX_TEXT_ITEMS = 1500;
const MAX_TEXT = 3000;
const MAX_URL = 4096;
const MAX_PIC_BYTES = 25 * 1024 * 1024;
const MAX_TOTAL_BYTES = 300 * 1024 * 1024;
const MAX_TOKENS = 600;
const MIN_SIDE = 120;

function normalizeTier(n) {
  const v = Math.round(Number(n));
  return Number.isFinite(v) ? Math.min(4, Math.max(0, v)) : 4;
}

function applyTick(tier, key, on) {
  const level = KEYS[key];
  if (!level) return normalizeTier(tier);
  return on ? Math.max(normalizeTier(tier), level) : Math.min(normalizeTier(tier), level - 1);
}

function flagsOf(tier) {
  const t = normalizeTier(tier);
  return { text: t >= 1, links: t >= 2, layout: t >= 3, scripts: t >= 4, gallery: t <= 2 };
}

function imageMimeOfHead(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 12) return '';
  if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'image/jpeg';
  if (buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return 'image/png';
  const head = buf.toString('latin1', 0, 12);
  if (head.startsWith('GIF87a') || head.startsWith('GIF89a')) return 'image/gif';
  if (head.startsWith('RIFF') && head.slice(8, 12) === 'WEBP') return 'image/webp';
  if (head.slice(4, 8) === 'ftyp') {
    const brand = buf.toString('latin1', 8, 12);
    if (brand === 'avif' || brand === 'avis') return 'image/avif';
  }
  return '';
}

function ourPolicy(tier, nonce) {
  if (tier <= 2) {
    return `default-src 'none'; script-src 'nonce-${nonce}'; style-src * 'unsafe-inline'; img-src nbimg:; font-src 'none'; media-src 'none'; frame-src 'none'; object-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'`;
  }
  return "script-src 'none'; object-src 'none'";
}

function pageHeaders(headers, tier, nonce) {
  const t = normalizeTier(tier);
  if (t >= 4) return null;
  const out = {};
  for (const [k, v] of Object.entries(headers || {})) {
    const name = k.toLowerCase();
    if (t <= 2 && (name === 'content-security-policy' || name === 'content-security-policy-report-only' || name === 'report-to' || name === 'reporting-endpoints' || name === 'nel')) continue;
    out[k] = v;
  }
  const key = Object.keys(out).find((k) => k.toLowerCase() === 'content-security-policy');
  if (key && t === 3) out[key] = [].concat(out[key]).concat(ourPolicy(t, nonce));
  else out['Content-Security-Policy'] = [ourPolicy(t, nonce)];
  return out;
}

function esc(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function cleanText(value, max) {
  return String(value === undefined || value === null ? '' : value).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, ' ').slice(0, max);
}

function cleanUrl(value, base) {
  const s = String(value || '').trim();
  if (!s || s.length > MAX_URL) return '';
  try {
    const u = new URL(s, base);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return '';
    u.hash = '';
    return u.href;
  } catch {
    return '';
  }
}

function imageLike(href) {
  try {
    return /\.(jpe?g|png|gif|webp|avif)$/i.test(new URL(href).pathname);
  } catch {
    return false;
  }
}

function sanitizeItems(raw, pageUrl, tier) {
  const flags = flagsOf(tier);
  const out = [];
  const seen = new Set();
  let texts = 0;
  const list = raw && Array.isArray(raw.items) ? raw.items : [];
  for (const it of list) {
    if (!it || typeof it !== 'object') continue;
    if (it.k === 'img') {
      if (out.filter((x) => x.k === 'img').length >= MAX_ITEMS) continue;
      let src = cleanUrl(it.src, pageUrl);
      const link = cleanUrl(it.href, pageUrl);
      let thumb = '';
      if (link && imageLike(link) && link !== src) {
        thumb = src;
        src = link;
      }
      if (!src || seen.has(src)) continue;
      const w = Math.max(0, Math.min(99999, Math.round(Number(it.w) || 0)));
      const h = Math.max(0, Math.min(99999, Math.round(Number(it.h) || 0)));
      if ((w > 0 && w < MIN_SIDE) || (h > 0 && h < MIN_SIDE)) continue;
      seen.add(src);
      out.push({ k: 'img', src, thumb: thumb && thumb !== src ? thumb : '', href: flags.links && link && link !== src ? link : '', w, h });
    } else if (it.k === 'text' && flags.text) {
      if (texts >= MAX_TEXT_ITEMS) continue;
      const tag = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'blockquote', 'figcaption', 'pre'].includes(it.tag) ? it.tag : 'p';
      const segs = [];
      let total = 0;
      for (const s of Array.isArray(it.segs) ? it.segs.slice(0, 80) : []) {
        if (!s || typeof s !== 'object') continue;
        const t = cleanText(s.t, MAX_TEXT);
        if (!t) continue;
        total += t.length;
        if (total > MAX_TEXT) break;
        const href = flags.links ? cleanUrl(s.href, pageUrl) : '';
        segs.push(href ? { t, href } : { t });
      }
      if (!segs.length) continue;
      texts += 1;
      out.push({ k: 'text', tag, segs });
    }
  }
  return { title: flags.text ? cleanText(raw && raw.title, 200) : '', items: out };
}

const STYLE = 'html{background:#0d0d0d;color:#d8d8d8}body{margin:0;font:16px/1.55 system-ui,sans-serif}main{max-width:960px;margin:0 auto;padding:1rem}main img{display:block;width:100%;height:auto;margin:0 0 1rem;background:#1a1a1a;cursor:zoom-in}main a.pl{display:block}main p,main li,main blockquote,main figcaption,main pre,main h1,main h2,main h3,main h4,main h5,main h6{margin:0 0 1rem;overflow-wrap:anywhere}main h1,main h2,main h3,main h4,main h5,main h6{color:#fff;line-height:1.25}main pre{white-space:pre-wrap}main li{list-style:none}main li:before{content:"\\2022  "}main blockquote{border-left:3px solid #444;padding-left:1rem;color:#bbb}a{color:#6cf}.note{color:#777;text-align:center;margin:3rem 0}#lb{position:fixed;inset:0;background:rgba(0,0,0,.94);display:flex;align-items:center;justify-content:center;z-index:9}#lb[hidden]{display:none}#lb img{max-width:100vw;max-height:100vh;object-fit:contain;cursor:zoom-out}#lb a,#lb button{position:fixed;background:#222;color:#fff;border:1px solid #555;border-radius:4px;padding:.4rem .8rem;font:inherit;cursor:pointer;text-decoration:none}#lbx{top:.6rem;right:.6rem}#lbp{left:.6rem;top:50%}#lbn{right:.6rem;top:50%}#lbl{left:.6rem;top:.6rem}#lbl[hidden]{display:none}';

function script(nonce, min) {
  return `<script nonce="${esc(nonce)}">(function(){var lb=document.getElementById('lb'),big=document.getElementById('lbi'),lk=document.getElementById('lbl'),at=0;function pics(){return Array.prototype.slice.call(document.querySelectorAll('main img'))}function show(i){var p=pics();if(!p.length)return;at=(i+p.length)%p.length;big.src=p[at].getAttribute('src');var h=p[at].getAttribute('data-href');if(h){lk.href=h;lk.hidden=false}else{lk.hidden=true}lb.hidden=false}function hide(){lb.hidden=true;big.removeAttribute('src')}document.addEventListener('load',function(e){var t=e.target;if(t&&t.tagName==='IMG'&&t.closest('main')&&(t.naturalWidth<${min}||t.naturalHeight<${min})){var a=t.parentNode;if(a&&a.tagName==='A'&&a.className==='pl')a.remove();else t.remove()}},true);document.addEventListener('error',function(e){var t=e.target;if(t&&t.tagName==='IMG'&&t.closest('main')){var f=t.getAttribute('data-fallback');if(f&&t.getAttribute('src')!==f){t.setAttribute('src',f)}else{var a=t.parentNode;if(a&&a.tagName==='A'&&a.className==='pl')a.remove();else t.remove()}}},true);document.addEventListener('click',function(e){var t=e.target;if(t&&t.tagName==='IMG'&&t.closest('main')){e.preventDefault();show(pics().indexOf(t));return}if(t&&t.id==='lbi'||t&&t.id==='lbx'||t===lb){hide();return}if(t&&t.id==='lbp'){show(at-1);return}if(t&&t.id==='lbn'){show(at+1)}});document.addEventListener('keydown',function(e){if(lb.hidden)return;if(e.key==='Escape')hide();else if(e.key==='ArrowLeft')show(at-1);else if(e.key==='ArrowRight'||e.key===' ')show(at+1)});})();</script>`;
}

function renderSegs(segs) {
  return segs.map((s) => (s.href ? `<a href="${esc(s.href)}" rel="noopener noreferrer">${esc(s.t)}</a>` : esc(s.t))).join('');
}

function buildGallery({ title, items, nonce, tokenFor }) {
  const parts = [];
  if (title) parts.push(`<h1>${esc(title)}</h1>`);
  let pics = 0;
  for (const it of items) {
    if (it.k === 'img') {
      const token = tokenFor(it.src);
      if (!token) continue;
      pics += 1;
      const fb = it.thumb ? tokenFor(it.thumb) : '';
      const img = `<img src="${esc(token)}" alt="" loading="lazy" decoding="async"${fb ? ` data-fallback="${esc(fb)}"` : ''}${it.href ? ` data-href="${esc(it.href)}"` : ''}>`;
      parts.push(img);
    } else if (it.k === 'text') {
      const tag = it.tag === 'figcaption' ? 'figcaption' : it.tag;
      parts.push(`<${tag}>${renderSegs(it.segs)}</${tag}>`);
    }
  }
  if (!pics) parts.push('<p class="note">No pictures found on this page.</p>');
  const body = `<main>${parts.join('\n')}</main><div id="lb" hidden><img id="lbi" alt=""><button id="lbx" type="button">&#10005;</button><button id="lbp" type="button">&#8249;</button><button id="lbn" type="button">&#8250;</button><a id="lbl" hidden rel="noopener noreferrer">Open link</a></div>`;
  return `<!doctype html><html lang="en" data-nb-gallery="1"><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>${esc(cleanText(title, 200) || 'Pictures')}</title><style>${STYLE}</style></head><body>${body}${script(nonce, MIN_SIDE)}</body></html>`;
}

module.exports = {
  LABELS,
  SHORT,
  KEYS,
  MAX_ITEMS,
  MAX_PIC_BYTES,
  MAX_TOTAL_BYTES,
  MAX_TOKENS,
  MIN_SIDE,
  normalizeTier,
  applyTick,
  flagsOf,
  imageMimeOfHead,
  ourPolicy,
  pageHeaders,
  esc,
  cleanUrl,
  imageLike,
  sanitizeItems,
  buildGallery,
};
