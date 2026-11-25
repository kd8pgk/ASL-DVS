const test = require('node:test');
const assert = require('node:assert/strict');
const S = require('../src/slow');

test('the meter turns slow on a dial-up rate and back on a fast one', () => {
  const m = S.createMeter();
  assert.equal(m.isSlow(), false);
  for (let i = 0; i < 3; i += 1) m.transfer(20000, 4000);
  assert.equal(m.isSlow(), true);
  assert.equal(m.rate(), 5000);
  m.transfer(500000, 1000);
  assert.equal(m.isSlow(), true, 'one fast sample is not enough');
  m.transfer(500000, 1000);
  assert.equal(m.isSlow(), false);
});

test('a long wait for the first byte turns slow on', () => {
  const m = S.createMeter();
  m.wait(4000);
  assert.equal(m.isSlow(), true);
});

test('small transfers are not measured', () => {
  const m = S.createMeter();
  for (let i = 0; i < 5; i += 1) m.transfer(2000, 2000);
  assert.equal(m.isSlow(), false);
  assert.equal(m.rate(), 0);
});

test('the mode overrides the meter', () => {
  assert.equal(S.isActive('on', false), true);
  assert.equal(S.isActive('off', true), false);
  assert.equal(S.isActive('auto', true), true);
  assert.equal(S.isActive('auto', false), false);
});

test('images go in viewing order: on screen top to bottom, then below, then above, extras last', () => {
  const report = {
    vh: 800,
    vw: 1000,
    items: [
      { src: 'banner', top: -900, x: 100, w: 800, h: 200 },
      { src: 'ad', top: 100, x: 880, w: 120, h: 600 },
      { src: 'icon', top: 10, x: 400, w: 32, h: 32 },
      { src: 'p1', top: 50, x: 200, w: 600, h: 500 },
      { src: 'p2', top: 600, x: 200, w: 600, h: 500 },
      { src: 'p3', top: 1200, x: 200, w: 600, h: 500 },
      { src: 'p4', top: 1800, x: 200, w: 600, h: 500 },
    ],
  };
  let queue = ['banner', 'ad', 'icon', 'p4', 'p3', 'p2', 'p1', 'unknown'].map((url, i) => ({ url, seq: i, late: false }));
  const order = [];
  while (queue.length) {
    const next = S.pickNext(queue, report);
    order.push(next.url);
    queue = queue.filter((e) => e !== next);
  }
  assert.deepEqual(order, ['p1', 'p2', 'p3', 'p4', 'banner', 'unknown', 'ad', 'icon']);
});

test('scrolling moves what is on screen to the front', () => {
  const items = [1, 2, 3, 4, 5, 6, 7].map((n) => ({ src: `p${n}`, top: (n - 7) * 600 + 100, x: 200, w: 600, h: 500 }));
  const queue = items.map((i, n) => ({ url: i.src, seq: n, late: false }));
  assert.equal(S.pickNext(queue, { vh: 800, vw: 1000, items }).url, 'p7');
});

test('a panel that failed once goes after everything else', () => {
  const items = [{ src: 'a', top: 10, x: 0, w: 900, h: 500 }, { src: 'b', top: 900, x: 0, w: 900, h: 500 }];
  const queue = [{ url: 'a', seq: 0, late: true }, { url: 'b', seq: 1, late: false }];
  assert.equal(S.pickNext(queue, { vh: 800, vw: 1000, items }).url, 'b');
});

test('without a report the page order is kept', () => {
  const queue = [{ url: 'x', seq: 2 }, { url: 'y', seq: 1 }];
  assert.equal(S.pickNext(queue, null).url, 'y');
});

test('the page image rule lets the in-memory images in', () => {
  assert.equal(S.addSchemeToCsp("img-src 'self' https:"), "img-src 'self' https: nbimg:");
  assert.equal(S.addSchemeToCsp("default-src 'self'; script-src 'self'"), "default-src 'self'; script-src 'self'; img-src 'self' nbimg:");
  assert.equal(S.addSchemeToCsp('script-src https:'), 'script-src https:');
  const h = S.cspHeaders({ 'Content-Security-Policy': ["img-src 'self'"], 'X-Other': ['1'] });
  assert.deepEqual(h['Content-Security-Policy'], ["img-src 'self' nbimg:"]);
  assert.equal(S.cspHeaders({ 'Content-Type': ['text/html'] }), null);
});

test('prefetch requests are recognised', () => {
  assert.equal(S.isPrefetch({ 'Sec-Purpose': 'prefetch' }), true);
  assert.equal(S.isPrefetch({ Purpose: 'prefetch' }), true);
  assert.equal(S.isPrefetch({ Accept: 'image/*' }), false);
});

test('a resumed range is read', () => {
  assert.deepEqual(S.parseContentRange('bytes 100-199/400'), { start: 100, end: 199, total: 400 });
  assert.deepEqual(S.parseContentRange('bytes 0-9/*'), { start: 0, end: 9, total: 0 });
  assert.equal(S.parseContentRange('garbage'), null);
});

test('retries wait longer each time, up to 32 seconds', () => {
  assert.deepEqual([1, 2, 3, 4, 5, 6].map(S.backoffMs), [2000, 4000, 8000, 16000, 32000, 32000]);
});

test('the next page link is found on the same site only', () => {
  const page = 'https://comic.test/strip/5';
  assert.equal(S.pickNextLink([{ rel: 'next', href: 'https://comic.test/strip/6' }], page), 'https://comic.test/strip/6');
  assert.equal(S.pickNextLink([{ rel: '', href: '/strip/6', text: 'Next ›' }], page), 'https://comic.test/strip/6');
  assert.equal(S.pickNextLink([{ rel: '', href: 'https://comic.test/strip/6', text: 'Next' }], page), 'https://comic.test/strip/6');
  assert.equal(S.pickNextLink([{ rel: '', href: 'https://comic.test/strip/6', text: '›' }], page), 'https://comic.test/strip/6');
  assert.equal(S.pickNextLink([{ rel: 'next', href: 'https://ads.test/x' }], page), '');
  assert.equal(S.pickNextLink([{ rel: '', href: 'https://comic.test/strip/4', text: 'Previous' }], page), '');
});

test('image addresses are read out of a page in order', () => {
  const html = '<img src="/a.png"><p><img alt=x src=\'b.jpg\'><img src=https://cdn.test/c.webp><img src="data:x"><img src="/a.png">';
  assert.deepEqual(S.imageUrlsIn(html, 'https://comic.test/s/1'), ['https://comic.test/a.png', 'https://comic.test/s/b.jpg', 'https://cdn.test/c.webp']);
});
