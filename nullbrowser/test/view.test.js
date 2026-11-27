const test = require('node:test');
const assert = require('node:assert/strict');
const V = require('../src/view');
const VM = require('../src/viewmain');
const PU = require('../src/popups');

test('ticking a box ticks the ones above it and unticking one unticks the ones below it', () => {
  assert.equal(V.applyTick(0, 'links', true), 2);
  assert.equal(V.applyTick(0, 'scripts', true), 4);
  assert.equal(V.applyTick(4, 'layout', false), 2);
  assert.equal(V.applyTick(4, 'text', false), 0);
  assert.equal(V.applyTick(2, 'text', true), 2);
  assert.equal(V.applyTick(2, 'nonsense', true), 2);
  assert.equal(V.normalizeTier('x'), 4);
  assert.equal(V.normalizeTier(-3), 0);
  assert.deepEqual(V.flagsOf(0), { text: false, links: false, layout: false, scripts: false, gallery: true });
  assert.deepEqual(V.flagsOf(4), { text: true, links: true, layout: true, scripts: true, gallery: false });
  assert.equal(V.flagsOf(3).gallery, false);
});

test('headers: below the full page scripts are off, and the picture views drop the site policy and its reports', () => {
  const h = { 'Content-Type': ['text/html'], 'content-security-policy': ["script-src 'self' evil.test"], 'Content-Security-Policy-Report-Only': ['default-src x; report-uri https://r.test'], 'Report-To': ['x'], NEL: ['x'] };
  assert.equal(V.pageHeaders(h, 4, 'N'), null);
  const pic = V.pageHeaders(h, 0, 'NONCE');
  assert.deepEqual(Object.keys(pic).sort(), ['Content-Security-Policy', 'Content-Type']);
  assert.match(pic['Content-Security-Policy'][0], /script-src 'nonce-NONCE'/);
  assert.match(pic['Content-Security-Policy'][0], /frame-src 'none'/);
  assert.match(pic['Content-Security-Policy'][0], /img-src nbimg:/);
  const layout = V.pageHeaders(h, 3, 'NONCE');
  assert.equal(layout['content-security-policy'].length, 2);
  assert.equal(layout['content-security-policy'][1], "script-src 'none'; object-src 'none'");
  assert.equal(layout['Content-Security-Policy-Report-Only'] !== undefined, true);
  assert.equal(V.pageHeaders({ A: ['b'] }, 3, 'N')['Content-Security-Policy'][0], "script-src 'none'; object-src 'none'");
});

test('the first bytes of a fetched picture decide whether it is shown', () => {
  const pad = Buffer.alloc(32);
  assert.equal(V.imageMimeOfHead(Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), pad])), 'image/jpeg');
  assert.equal(V.imageMimeOfHead(Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), pad])), 'image/png');
  assert.equal(V.imageMimeOfHead(Buffer.concat([Buffer.from('GIF89a'), pad])), 'image/gif');
  assert.equal(V.imageMimeOfHead(Buffer.concat([Buffer.from('RIFF\0\0\0\0WEBP'), pad])), 'image/webp');
  assert.equal(V.imageMimeOfHead(Buffer.concat([Buffer.from('\0\0\0\x1cftypavif'), pad])), 'image/avif');
  for (const bad of ['<svg xmlns="http://www.w3.org/2000/svg"></svg>', '<!doctype html><html></html>', 'MZ\u0090\u0000\u0003\u0000\u0000\u0000\u0004\u0000\u0000\u0000', '%PDF-1.4\n%%EOF   ']) assert.equal(V.imageMimeOfHead(Buffer.from(bad)), '', bad);
});

const base = 'https://site.test/gallery/page';

test('what a page reports is cleaned: addresses, sizes, thumbnails, duplicates and text', () => {
  const raw = {
    title: 'A <b>title</b>\u0000',
    items: [
      { k: 'img', src: '/a/thumb.jpg', href: '/a/full.jpg', w: 0, h: 0 },
      { k: 'img', src: '/a/thumb.jpg', href: '/a/full.jpg' },
      { k: 'img', src: 'javascript:alert(1)' },
      { k: 'img', src: 'data:image/png;base64,AAAA' },
      { k: 'img', src: '/icon.png', w: 16, h: 16 },
      { k: 'img', src: '/wide.png', w: 800, h: 100 },
      { k: 'img', src: '/b.jpg', href: 'https://other.test/page.html' },
      { k: 'text', tag: 'script', segs: [{ t: 'Hello ' }, { t: 'link', href: '/x' }, { t: 'bad', href: 'javascript:1' }, null, { t: '' }] },
      { k: 'text', tag: 'h1', segs: [] },
      { k: 'other' },
      null,
    ],
  };
  const all = V.sanitizeItems(raw, base, 2);
  const imgs = all.items.filter((i) => i.k === 'img');
  assert.deepEqual(imgs.map((i) => i.src), ['https://site.test/a/full.jpg', 'https://site.test/b.jpg']);
  assert.equal(imgs[0].thumb, 'https://site.test/a/thumb.jpg');
  assert.equal(imgs[1].href, 'https://other.test/page.html');
  const text = all.items.find((i) => i.k === 'text');
  assert.equal(text.tag, 'p');
  assert.deepEqual(text.segs, [{ t: 'Hello ' }, { t: 'link', href: 'https://site.test/x' }, { t: 'bad' }]);
  assert.equal(all.title.includes('\u0000'), false);
  const onlyPics = V.sanitizeItems(raw, base, 0);
  assert.equal(onlyPics.items.some((i) => i.k === 'text'), false);
  assert.equal(onlyPics.title, '');
  assert.equal(onlyPics.items.every((i) => !i.href), true);
  const noLinks = V.sanitizeItems(raw, base, 1);
  assert.equal(noLinks.items.find((i) => i.k === 'text').segs.every((s) => !s.href), true);
});

test('the gallery page escapes everything a site gave and only has our own script', () => {
  const clean = { title: '<img src=x onerror=alert(1)>', items: [{ k: 'img', src: 'https://s.test/a.jpg?x=1&y="2"', thumb: 'https://s.test/t.jpg', href: '' }, { k: 'text', tag: 'p', segs: [{ t: '</p><script>alert(1)</script>' }, { t: 'go', href: 'https://s.test/x?a="b"' }] }] };
  const tokens = new Map();
  const html = V.buildGallery({ title: clean.title, items: clean.items, nonce: 'abc123', tokenFor: (u) => {
    const t = `nbimg://f/${tokens.size}`;
    tokens.set(u, t);
    return t;
  } });
  assert.equal(html.includes('<script>alert'), false);
  assert.equal(html.includes('<img src=x'), false);
  assert.match(html, /&lt;\/p&gt;&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /href="https:\/\/s\.test\/x\?a=&quot;b&quot;"/);
  assert.equal((html.match(/<script/g) || []).length, 1);
  assert.match(html, /<script nonce="abc123">/);
  assert.equal(html.includes('s.test/a.jpg'), false, 'the page address of a picture never goes into the gallery');
  assert.match(html, /src="nbimg:\/\/f\/0"/);
  assert.match(html, /data-fallback="nbimg:\/\/f\/1"/);
  assert.match(html, /data-nb-gallery="1"/);
  assert.match(html, /<meta name="referrer" content="no-referrer">/);
  const empty = V.buildGallery({ title: '', items: [], nonce: 'n', tokenFor: () => '' });
  assert.match(empty, /No pictures found/);
  assert.equal(empty.includes('<h1>'), false);
});

test('a column of pictures only: a gallery with no text items has no text tags', () => {
  const html = V.buildGallery({ title: '', items: [{ k: 'img', src: 'https://s.test/a.jpg', thumb: '', href: '' }], nonce: 'n', tokenFor: () => 'nbimg://f/1' });
  const main = /<main>([\s\S]*)<\/main>/.exec(html)[1];
  assert.equal(/<(p|h\d|li|a)[ >]/.test(main), false);
  assert.equal((main.match(/<img/g) || []).length, 1);
});

test('the in-page collector is plain text that evaluates to a call', () => {
  assert.doesNotThrow(() => new Function(`return ${PU.call(VM.collectFn, { text: true, links: true })}`));
});
