const zlib = require('node:zlib');

const SLOW_TESTS = [
  { id: 'slow-order', kind: 'auto', title: 'Slow line: comic in viewing order', expect: 'With Slow on, the ten panels arrive one at a time, top to bottom (the banner above them may come first), and the side ad comes after the last panel.' },
  { id: 'slow-resume', kind: 'auto', title: 'Slow line: dropped panel resumes', expect: 'Panel 4 is cut off halfway on its first try; the browser asks again from the byte it stopped at, not from the start.' },
  { id: 'slow-scroll', kind: 'auto', title: 'Slow line: scrolling moves the queue', expect: 'Scrolled to panel 7 while panel 1 loads, the next panel fetched is the one on screen (7 or 8), not panel 2.' },
  { id: 'slow-extras', kind: 'auto', title: 'Slow line: fonts and prefetch skipped', expect: 'With Slow on, the web font and the prefetched page on the comic page are never fetched.' },
  { id: 'slow-textonly', kind: 'auto', title: 'Images off: text only', expect: 'With Images off, no image on the text-only page is fetched, and the page text still arrives.' },
  { id: 'slow-ahead', kind: 'auto', title: 'Read ahead: next page ready', expect: 'With Read ahead on, page 2 and its three images are fetched once while page 1 is open, and opening page 2 fetches no image again.' },
];

const SLOW_IDS = new Set(SLOW_TESTS.map((t) => t.id));

function png(bytes, seed) {
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(zlib.crc32(td) >>> 0);
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(1, 0);
  ihdr.writeUInt32BE(1, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const idat = zlib.deflateSync(Buffer.from([0, (seed * 37) & 255, (seed * 91) & 255, 200]));
  const head = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr)]);
  const tail = Buffer.concat([chunk('IDAT', idat), chunk('IEND', Buffer.alloc(0))]);
  const pad = Math.max(0, bytes - head.length - tail.length - 12 - 6);
  const text = Buffer.concat([Buffer.from('Fill\0', 'latin1'), Buffer.alloc(pad, 120)]);
  return Buffer.concat([head, chunk('tEXt', text), tail]);
}

function createSlowLab({ ev, of, rateKb = 5, panelKb = 24 }) {
  const rate = Math.max(1, rateKb) * 1024;
  const images = new Map();
  const dropped = new Set();

  const imageOf = (name) => {
    if (!images.has(name)) {
      const kb = /^(p|s)\d+$/.test(name) ? panelKb : /^a2-/.test(name) ? Math.max(4, panelKb / 2) : 6;
      images.set(name, png(kb * 1024, name.length + name.charCodeAt(name.length - 1)));
    }
    return images.get(name);
  };

  function beaconScript(test) {
    return `<script>var T=${JSON.stringify(test)};function b(w,d){try{fetch('/ev?t='+encodeURIComponent(T)+'&w='+encodeURIComponent(w)+'&d='+encodeURIComponent(d==null?'':d)+'&r='+Math.random(),{cache:'no-store'})}catch(e){}}b('visited');</script>`;
  }

  function shell(title, test, body, head = '') {
    return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title>${head}
<style>body{font-family:system-ui,sans-serif;background:#0d1117;color:#fff;margin:0;padding:0 16px;line-height:1.45}a{color:#22d4ff}h1{color:#ffd040;font-size:1.25rem}
.wrap{display:flex;gap:16px}.strip{flex:1;max-width:640px}.strip img{display:block;width:600px;height:560px;margin:0 0 40px;background:#1a2233}.side{width:120px}.side img{width:120px;height:600px}
.banner{display:block;width:600px;height:90px}.k{color:#aab8cc;font-size:.85rem}</style></head><body>${beaconScript(test)}${body}</body></html>`;
  }

  function comic(test, prefix, next) {
    const panels = Array.from({ length: 10 }, (_, i) => `<img alt="Panel ${i + 1}" id="${prefix}${i + 1}" src="/s/img/${prefix}${i + 1}.png?t=${test}">`).join('');
    const head = test === 'slow-order' ? `<link rel="prefetch" href="/s/prefetched?t=${test}"><style>@font-face{font-family:Lab;src:url(/s/font.woff2?t=${test})}body{font-family:Lab,system-ui}</style>` : '';
    return shell(`Comic ${test}`, test, `<h1>Slow line comic</h1><p class="k">Text arrives first. The panels below load one at a time, top to bottom.</p>
<img class="banner" alt="Banner" src="/s/img/banner-${prefix}.png?t=${test}">
<div class="wrap"><div class="strip">${panels}</div><div class="side"><img alt="Side ad" src="/s/img/ad-${prefix}.png?t=${test}"></div></div>
${next ? `<p><a id="next" rel="next" href="${next}">Next ›</a></p>` : ''}${test === 'slow-scroll' ? "<script>addEventListener('scroll',function f(){var p=document.getElementById('s7');if(p&&p.getBoundingClientRect().top<innerHeight){b('scrolled');removeEventListener('scroll',f)}})</script>" : ''}`, head);
  }

  function testPage(id) {
    switch (id) {
      case 'slow-order':
      case 'slow-resume':
      case 'slow-extras':
        return comic('slow-order', 'p', '');
      case 'slow-scroll':
        return comic('slow-scroll', 's', '');
      case 'slow-textonly':
        return shell('Text only', 'slow-textonly', `<h1>Text only</h1><p id="txt">This paragraph is the page text. Turn Images off in the Line row first.</p>${[1, 2, 3, 4].map((n) => `<img alt="Picture ${n}" src="/s/img/txt${n}.png?t=slow-textonly" width="300" height="200">`).join('')}<div style="width:300px;height:100px;background:url(/s/img/txtbg.png?t=slow-textonly)"></div>`);
      case 'slow-ahead':
        return shell('Page 1', 'slow-ahead', `<h1>Page 1</h1><p>Turn Read ahead on in the Line row, wait for "Next page ready", then follow Next.</p><img alt="Page 1 art" src="/s/img/a1-1.png?t=slow-ahead" width="300" height="200"><p><a id="next" href="/s/page2">Next</a></p>`);
      default:
        return '';
    }
  }

  function sendThrottled(req, res, name, test) {
    const body = imageOf(name);
    const etag = `"${name}-${body.length}"`;
    const range = /^bytes=(\d+)-$/.exec(String(req.headers.range || ''));
    let start = 0;
    let status = 200;
    const headers = { 'Content-Type': 'image/png', 'Accept-Ranges': 'bytes', ETag: etag, 'Cache-Control': 'no-store' };
    if (range && (!req.headers['if-range'] || req.headers['if-range'] === etag)) {
      start = Number(range[1]);
      if (start >= body.length) {
        res.writeHead(416, { 'Content-Range': `bytes */${body.length}` });
        return res.end();
      }
      status = 206;
      headers['Content-Range'] = `bytes ${start}-${body.length - 1}/${body.length}`;
    }
    headers['Content-Length'] = body.length - start;
    ev(test, start > 0 ? 'range' : 'img', `${name}${start > 0 ? `@${start}` : ''}`, req.headers['user-agent']);
    res.writeHead(status, headers);
    const dropAt = name === 'p4' && start === 0 && !dropped.has(name) ? Math.floor(body.length / 2) : -1;
    let at = start;
    const step = Math.max(256, Math.floor(rate / 10));
    const tick = () => {
      if (res.destroyed) return;
      if (dropAt >= 0 && at >= dropAt) {
        dropped.add(name);
        ev(test, 'dropped', `${name}@${at}`);
        res.socket.destroy();
        return;
      }
      const end = Math.min(body.length, at + step, dropAt >= 0 ? dropAt : Infinity);
      res.write(body.subarray(at, end));
      at = end;
      if (at >= body.length) {
        ev(test, 'complete', name);
        return res.end();
      }
      setTimeout(tick, 100);
    };
    tick();
    return undefined;
  }

  function handle(req, res, url) {
    const p = url.pathname;
    const test = url.searchParams.get('t') || '';
    if (p.startsWith('/t/') && SLOW_IDS.has(p.slice(3))) {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
      res.end(testPage(p.slice(3)));
      return true;
    }
    if (!p.startsWith('/s/')) return false;
    const m = /^\/s\/img\/([a-z0-9-]+)\.png$/.exec(p);
    if (m) {
      sendThrottled(req, res, m[1], test || (m[1].startsWith('a2-') || m[1].startsWith('a1-') ? 'slow-ahead' : ''));
      return true;
    }
    if (p === '/s/font.woff2') {
      ev(test || 'slow-order', 'font');
      res.writeHead(200, { 'Content-Type': 'font/woff2' });
      res.end(Buffer.alloc(64));
      return true;
    }
    if (p === '/s/prefetched') {
      ev(test || 'slow-order', 'prefetch');
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end('<!doctype html><p>prefetched</p>');
      return true;
    }
    if (p === '/s/page2') {
      ev('slow-ahead', 'page2', req.headers['sec-purpose'] || req.headers['sec-fetch-mode'] || '');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
      res.end(shell('Page 2', 'slow-ahead-2', `<h1>Page 2</h1>${[1, 2, 3].map((n) => `<img alt="Page 2 art ${n}" src="/s/img/a2-${n}.png" width="300" height="200">`).join('')}`));
      return true;
    }
    res.writeHead(404);
    res.end();
    return true;
  }

  function verdict(id) {
    const list = of(id === 'slow-resume' || id === 'slow-extras' ? 'slow-order' : id);
    const firsts = (re) => list.filter((e) => e.what === 'img' && re.test(e.data)).map((e) => e.data);
    switch (id) {
      case 'slow-order': {
        const seen = firsts(/./);
        if (!seen.length) return { status: 'not run' };
        const panels = seen.filter((n) => /^p\d+$/.test(n));
        const complete = list.filter((e) => e.what === 'complete' && /^p\d+$/.test(e.data)).length;
        if (complete < 10) return { status: 'pending', note: `${complete} of 10 panels complete` };
        const inOrder = panels.every((n, i) => Number(n.slice(1)) === i + 1);
        const ad = seen.findIndex((n) => n.startsWith('ad-'));
        const lastPanel = seen.findIndex((n) => n === 'p10');
        const extrasLast = ad === -1 || ad > lastPanel;
        return inOrder && extrasLast ? { status: 'pass', note: `order: ${seen.join(', ')}` } : { status: 'FAIL', note: `order: ${seen.join(', ')}` };
      }
      case 'slow-resume': {
        const drop = list.find((e) => e.what === 'dropped');
        if (!drop) return { status: 'not run' };
        const resumed = list.find((e) => e.what === 'range' && e.data.startsWith('p4@'));
        const restarted = list.filter((e) => e.what === 'img' && e.data === 'p4').length > 1;
        if (resumed) return { status: 'pass', note: `cut at ${drop.data}, resumed at ${resumed.data}` };
        if (restarted) return { status: 'FAIL', note: 'started panel 4 again from the first byte' };
        return { status: 'pending', note: 'waiting for the retry' };
      }
      case 'slow-scroll': {
        const scrolled = list.find((e) => e.what === 'scrolled');
        if (!scrolled) return { status: 'not run', note: 'scroll to panel 7 while panel 1 loads' };
        const after = list.filter((e) => e.what === 'img' && e.t > scrolled.t && /^s\d+$/.test(e.data));
        if (!after.length) return { status: 'pending' };
        return ['s7', 's8'].includes(after[0].data) ? { status: 'pass', note: `next after scrolling: ${after[0].data}` } : { status: 'FAIL', note: `next after scrolling: ${after[0].data}` };
      }
      case 'slow-extras': {
        if (!list.some((e) => e.what === 'visited')) return { status: 'not run' };
        const got = list.filter((e) => e.what === 'font' || e.what === 'prefetch').map((e) => e.what);
        return got.length ? { status: 'FAIL', note: `fetched: ${[...new Set(got)].join(', ')}` } : { status: 'pass', note: 'no font, no prefetch' };
      }
      case 'slow-textonly': {
        if (!list.some((e) => e.what === 'visited')) return { status: 'not run' };
        const imgs = list.filter((e) => e.what === 'img' || e.what === 'range');
        return imgs.length ? { status: 'FAIL', note: `${imgs.length} image request(s)` } : { status: 'pass', note: 'text arrived, no image fetched' };
      }
      case 'slow-ahead': {
        const page2 = list.filter((e) => e.what === 'page2');
        const a2 = list.filter((e) => e.what === 'img' && e.data.startsWith('a2-'));
        const opened = of('slow-ahead-2').some((e) => e.what === 'visited');
        if (!page2.length) return { status: 'not run' };
        if (!opened) return { status: 'pending', note: `${a2.length} of 3 page 2 images read ahead; now open page 2` };
        const counts = {};
        for (const e of a2) counts[e.data] = (counts[e.data] || 0) + 1;
        const once = ['a2-1', 'a2-2', 'a2-3'].every((n) => counts[n] === 1);
        return once ? { status: 'pass', note: `page 2 fetched ${page2.length} time(s); each image once` } : { status: 'FAIL', note: `image fetches: ${JSON.stringify(counts)}` };
      }
      default:
        return null;
    }
  }

  return { handle, verdict };
}

module.exports = { SLOW_TESTS, SLOW_IDS, createSlowLab, png };
