const test = require('node:test');
const assert = require('node:assert/strict');
const D = require('../src/download');

const pdf = (extra = '') => Buffer.from(`%PDF-1.4\n<</Type /Page>>\n${extra}${' '.repeat(2000)}\n%%EOF\n`, 'latin1');
const mp3 = () => Buffer.concat([Buffer.from([0xff, 0xfb, 0x90, 0x00]), Buffer.alloc(400)]);
const wav = () => {
  const b = Buffer.alloc(400);
  b.write('RIFF', 0, 'latin1');
  b.writeUInt32LE(b.length - 8, 4);
  b.write('WAVE', 8, 'latin1');
  return b;
};
const webm = () => Buffer.concat([Buffer.from([0x1a, 0x45, 0xdf, 0xa3]), Buffer.from('....B.webm'), Buffer.alloc(300)]);
const mp4 = () => {
  const ftyp = Buffer.alloc(16);
  ftyp.writeUInt32BE(16, 0);
  ftyp.write('ftyp', 4, 'latin1');
  const moov = Buffer.alloc(8);
  moov.writeUInt32BE(8, 0);
  moov.write('moov', 4, 'latin1');
  return Buffer.concat([ftyp, moov]);
};
const jpg = () => Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.alloc(300), Buffer.from([0xff, 0xd9])]);
const mpeg = () => Buffer.concat([Buffer.from([0, 0, 1, 0xba]), Buffer.alloc(300)]);

const webp = () => {
  const b = Buffer.alloc(400);
  b.write('RIFF', 0, 'latin1');
  b.writeUInt32LE(b.length - 8, 4);
  b.write('WEBPVP8 ', 8, 'latin1');
  return b;
};

const good = { pdf: pdf(), mp3: mp3(), wav: wav(), webm: webm(), mp4: mp4(), jpg: jpg(), mpeg: mpeg(), webp: webp() };

test('each allowed type passes with its own check', () => {
  for (const [kind, buf] of Object.entries(good)) {
    const r = D.checkDownload(kind, buf, D.sha256(buf));
    assert.equal(r.ok, true, `${kind}: ${r.reason}`);
  }
});

test('a file that changed after it was checked is refused', () => {
  const b = Buffer.from(good.jpg);
  const sha = D.sha256(b);
  b[10] ^= 1;
  assert.match(D.checkDownload('jpg', b, sha).reason, /changed/);
});

test('a Windows program is refused, even hidden inside a real PDF', () => {
  const exe = Buffer.alloc(0x100);
  exe.write('MZ', 0, 'latin1');
  exe.writeUInt32LE(0x80, 0x3c);
  exe.write('PE\0\0', 0x80, 'latin1');
  const b = Buffer.concat([good.pdf, exe]);
  assert.match(D.checkDownload('pdf', b, D.sha256(b)).reason, /Windows program/);
});

test('an ELF program is refused', () => {
  const b = Buffer.concat([good.mp4, Buffer.from([0x7f, 0x45, 0x4c, 0x46, 2, 1, 1])]);
  assert.match(D.checkDownload('mp4', b, D.sha256(b)).reason, /program/);
});

test('a script or web page inside a media file is refused', () => {
  const b = Buffer.concat([good.mp4, Buffer.from('<script>alert(1)</script>')]);
  assert.match(D.checkDownload('mp4', b, D.sha256(b)).reason, /web page code/);
  const c = Buffer.concat([good.mp3, Buffer.from('#!/bin/sh\n')]);
  assert.match(D.checkDownload('mp3', c, D.sha256(c)).reason, /script/);
});

test('a PDF with a script action is refused, not stripped', () => {
  const b = pdf('/OpenAction <</S /JavaScript>>\n');
  assert.match(D.checkDownload('pdf', b, D.sha256(b)).reason, /runs code/);
});

test('a disguised file fails its own type check', () => {
  const htmlAsJpg = Buffer.from('<p>not an image</p>' + ' '.repeat(300));
  assert.equal(D.checkDownload('jpg', htmlAsJpg, D.sha256(htmlAsJpg)).ok, false);
  const pdfAsMp4 = pdf();
  assert.match(D.checkDownload('mp4', pdfAsMp4, D.sha256(pdfAsMp4)).reason, /not really a MP4/);
});

test('a WAV whose size does not match its header is refused', () => {
  const b = wav();
  b.writeUInt32LE(9999, 4);
  assert.match(D.checkDownload('wav', b, D.sha256(b)).reason, /does not match/);
});

test('an MP4 whose boxes run past the end is refused', () => {
  const b = mp4();
  b.writeUInt32BE(9999, 0);
  assert.equal(D.checkDownload('mp4', b, D.sha256(b)).ok, false);
});

test('only the listed types are allowed', () => {
  assert.equal(D.kindOfPath('/a/b.exe'), '');
  assert.equal(D.kindOfPath('/a/b.zip'), '');
  assert.equal(D.kindOfPath('/a/b.PDF'), 'pdf');
  assert.equal(D.kindOfPath('/a/b.mpg'), 'mpeg');
  assert.equal(D.checkDownload('zip', Buffer.alloc(100), 'x').ok, false);
});

test('the saved name comes from the server and gets the right extension', () => {
  assert.equal(D.safeName('../../evil.exe', 'pdf'), 'evil.pdf');
  assert.equal(D.safeName('strip 12.PDF', 'pdf'), 'strip 12.pdf');
  assert.equal(D.safeName('', 'mp3'), 'download.mp3');
  assert.equal(D.safeName('a:b*c?.jpg', 'jpg'), 'a_b_c_.jpg');
});

test('a taken name gets a number and is never overwritten', () => {
  const taken = new Set(['a.pdf', 'a-2.pdf']);
  assert.equal(D.uniqueName('a.pdf', (n) => taken.has(n)), 'a-3.pdf');
  assert.equal(D.uniqueName('b.pdf', () => false), 'b.pdf');
});

test('the list has only the main page links of the allowed types, merged, sorted, with name, path and host', () => {
  const page = 'https://comic.test/strip/5';
  const list = D.buildList([
    { href: '/files/b.pdf' },
    { href: 'https://cdn.test/a/song.mp3#x' },
    { href: '/files/b.pdf' },
    { href: '/files/evil.exe' },
    { href: 'javascript:alert(1)' },
    { href: 'file:///etc/passwd.pdf' },
  ], page);
  assert.deepEqual(list.map((e) => e.href), ['https://cdn.test/a/song.mp3', 'https://comic.test/files/b.pdf']);
  assert.equal(list[0].name, 'song.mp3');
  assert.equal(list[0].path, '/a/song.mp3');
  assert.equal(list[0].host, 'cdn.test');
});

test('the list is capped at 200 files', () => {
  const many = Array.from({ length: 300 }, (_, i) => ({ href: `/f/${String(i).padStart(3, '0')}.jpg` }));
  assert.equal(D.buildList(many, 'https://x.test/').length, 200);
});

test('the queue runs one file at a time, in order', async () => {
  const order = [];
  let active = 0;
  let peak = 0;
  const q = D.createQueue(async (item) => {
    active += 1;
    peak = Math.max(peak, active);
    order.push(item.name);
    await new Promise((r) => setTimeout(r, 5));
    active -= 1;
    return { ok: true, saved: item.name };
  });
  q.add([{ name: 'a.pdf' }, { name: 'b.pdf' }, { name: 'c.pdf' }]);
  await new Promise((r) => setTimeout(r, 80));
  assert.deepEqual(order, ['a.pdf', 'b.pdf', 'c.pdf']);
  assert.equal(peak, 1);
  assert.equal(q.snapshot().every((i) => i.state === 'done'), true);
});

test('a refused file does not stop the queue, and sign-in is reported', async () => {
  const q = D.createQueue(async (item) => (item.name === 'bad.pdf' ? { ok: false, reason: 'not really a PDF' } : item.name === 'login.pdf' ? { ok: false, login: true, reason: 'sign-in' } : { ok: true, saved: item.name }));
  q.add([{ name: 'bad.pdf' }, { name: 'login.pdf' }, { name: 'good.pdf' }]);
  await new Promise((r) => setTimeout(r, 30));
  const states = Object.fromEntries(q.snapshot().map((i) => [i.name, i.state]));
  assert.deepEqual(states, { 'bad.pdf': 'refused', 'login.pdf': 'login', 'good.pdf': 'done' });
});

test('cancel stops the file in progress and the waiting ones, and keeps the finished ones', async () => {
  const q = D.createQueue(async (item, ctx) => {
    await new Promise((r) => setTimeout(r, 40));
    return { ok: true, saved: item.name };
  });
  const [a, b, c] = q.add([{ name: 'a.pdf' }, { name: 'b.pdf' }, { name: 'c.pdf' }]);
  await new Promise((r) => setTimeout(r, 60));
  q.cancelAll();
  await new Promise((r) => setTimeout(r, 80));
  const states = Object.fromEntries(q.snapshot().map((i) => [i.name, i.state]));
  assert.equal(states['a.pdf'], 'done');
  assert.equal(states['b.pdf'], 'cancelled');
  assert.equal(states['c.pdf'], 'cancelled');
});

test('the queue never keeps the cookie it was given once the file is done', async () => {
  const q = D.createQueue(async () => ({ ok: true, saved: 'x.pdf' }));
  q.add([{ name: 'x.pdf' }], { cookie: 'sid=secret' });
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(JSON.stringify(q.snapshot()).includes('secret'), false);
});

test('a WebP must be a RIFF WEBP with image data and not cut short', () => {
  const sha = (b) => D.sha256(b);
  assert.equal(D.checkDownload('webp', webp(), sha(webp())).ok, true);
  const cut = webp();
  cut.writeUInt32LE(5000, 4);
  assert.equal(D.checkDownload('webp', cut, sha(cut)).ok, false);
  const noData = webp();
  noData.write('JUNK', 12, 'latin1');
  assert.equal(D.checkDownload('webp', noData, sha(noData)).ok, false);
  assert.equal(D.checkDownload('webp', wav(), sha(wav())).ok, false);
  assert.equal(D.kindOfPath('/a/b.WEBP'), 'webp');
});

test('the first bytes tell the kind, and a disagreeing type drops the link', () => {
  for (const [kind, buf] of Object.entries(good)) assert.equal(D.kindOfHead(buf), kind, kind);
  assert.equal(D.kindOfHead(Buffer.from('<!doctype html><html>     ')), '');
  assert.equal(D.kindOfHead(Buffer.from('MZ' + 'x'.repeat(40))), '');
  assert.equal(D.kindOfProbe(jpg(), 'image/jpeg'), 'jpg');
  assert.equal(D.kindOfProbe(jpg(), 'application/octet-stream'), 'jpg');
  assert.equal(D.kindOfProbe(jpg(), ''), 'jpg');
  assert.equal(D.kindOfProbe(jpg(), 'application/pdf'), '');
  assert.equal(D.kindOfProbe(Buffer.from('hello world, not a file at all'), 'image/jpeg'), '');
});

test('hints name the kind: download name, type, and a query value', () => {
  const page = 'https://x.test/p';
  const list = D.buildList([
    { href: '/get?id=1', name: 'strip.mp4' },
    { href: '/blob/aaa', type: 'application/pdf' },
    { href: '/dl?file=song.mp3&x=1' },
    { href: '/dl?id=9' },
  ], page);
  assert.deepEqual(list.map((e) => e.kind).sort(), ['mp3', 'mp4', 'pdf']);
  assert.equal(list.find((e) => e.kind === 'mp4').name, 'strip.mp4');
});

test('extensionless links become candidates: media first, then the same site, then others; skip page-like and unknown files', () => {
  const page = 'https://www.comic.test/strip';
  const scan = D.buildScan([
    { href: 'https://other.test/go/1' },
    { href: 'https://cdn.comic.test/x/abc', media: true },
    { href: '/dl?id=42' },
    { href: '/about.html' },
    { href: '/files/prog.zip' },
    { href: '/getit.php' },
    { href: 'https://www.comic.test/strip#top' },
    { href: 'https://other.test/go/1' },
    { href: 'mailto:a@b.test' },
  ], page);
  assert.deepEqual(scan.candidates, ['https://cdn.comic.test/x/abc', 'https://www.comic.test/dl?id=42', 'https://www.comic.test/getit.php', 'https://other.test/go/1']);
  assert.equal(scan.list.length, 0);
});

test('only 60 candidates are probed and the rest are counted', () => {
  const links = Array.from({ length: 100 }, (_, i) => ({ href: `https://c.test/m/${i}`, media: true }));
  const scan = D.buildScan(links, 'https://x.test/');
  assert.equal(scan.candidates.length, 60);
  assert.equal(scan.skipped, 40);
});

test('the list is capped at 200 but reports the total', () => {
  const many = Array.from({ length: 300 }, (_, i) => ({ href: `/f/${String(i).padStart(3, '0')}.jpg` }));
  const scan = D.buildScan(many, 'https://x.test/');
  assert.equal(scan.list.length, 200);
  assert.equal(scan.total, 300);
});

function fakeDoc(nodes) {
  return {
    baseURI: 'https://p.test/dir/',
    querySelectorAll: () => nodes,
  };
}

function fakeNode(tag, attrs = {}) {
  return {
    tagName: tag,
    href: attrs.href,
    src: attrs.src || '',
    currentSrc: attrs.currentSrc || '',
    data: attrs.data || '',
    poster: attrs.poster || '',
    getAttribute: (n) => (attrs.attrs && attrs.attrs[n]) || null,
  };
}

test('the page scan does not stop at 300 other links', () => {
  const nodes = [];
  for (let i = 0; i < 1500; i += 1) nodes.push(fakeNode('A', { href: `https://p.test/page/${i}.html` }));
  nodes.push(fakeNode('A', { href: 'https://p.test/files/last.pdf' }));
  nodes.push(fakeNode('IMG', { src: 'https://cdn.test/i/abc', attrs: { srcset: 'https://cdn.test/i/abc-2x 2x' } }));
  nodes.push(fakeNode('A', { href: 'https://p.test/dl?id=1' }));
  nodes.push(fakeNode('A', { href: 'https://p.test/get', attrs: { download: 'x.mp3' } }));
  nodes.push(fakeNode('VIDEO', { currentSrc: 'https://cdn.test/v/1', poster: 'https://cdn.test/v/1-poster' }));
  const out = D.scanFn(Object.keys(D.EXT_KIND).map((e) => e.slice(1)), D.DYNAMIC_EXTS, fakeDoc(nodes));
  const hrefs = out.items.map((i) => i.href);
  assert.ok(hrefs.includes('https://p.test/files/last.pdf'));
  assert.ok(hrefs.includes('https://cdn.test/i/abc'));
  assert.ok(hrefs.includes('https://cdn.test/i/abc-2x'));
  assert.ok(hrefs.includes('https://cdn.test/v/1-poster'));
  assert.ok(hrefs.includes('https://p.test/dl?id=1'));
  assert.equal(hrefs.some((h) => h.endsWith('.html')), false, 'page links are not collected');
  const scan = D.buildScan(out.items, 'https://p.test/dir/');
  assert.deepEqual(scan.list.map((e) => e.name).sort(), ['last.pdf', 'x.mp3']);
  assert.equal(scan.candidates[0].startsWith('https://cdn.test/'), true);
});

test('the scan script is plain text that evaluates to a call', () => {
  const src = D.scanScript();
  assert.match(src, /^\(function scanFn/);
  assert.doesNotThrow(() => new Function(`return ${src}`));
});

test('frames are read together, a failing or slow frame is counted, and a failing main frame is reported', async () => {
  const frames = [{ id: 'm', main: true }, { id: 'a' }, { id: 'b' }, { id: 'c' }];
  const run = (f) => {
    if (f.id === 'b') return Promise.reject(new Error('gone'));
    if (f.id === 'c') return new Promise(() => {});
    return Promise.resolve({ items: [{ href: `https://x.test/${f.id}.pdf` }] });
  };
  const got = await D.collectFrames(frames, run, 50);
  assert.equal(got.items.length, 2);
  assert.equal(got.failed, 2);
  assert.equal(got.mainFailed, false);
  const bad = await D.collectFrames([{ id: 'm', main: true }], () => Promise.reject(new Error('x')), 50);
  assert.equal(bad.mainFailed, true);
  assert.equal(bad.failed, 0);
});
