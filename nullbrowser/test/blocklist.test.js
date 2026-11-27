const test = require('node:test');
const assert = require('node:assert/strict');
const BL = require('../src/blocklist');
const PU = require('../src/popups');

test('host names are cleaned from list syntax and bad ones are refused', () => {
  assert.equal(BL.cleanHost('||Ads.Example.com^$third-party'), 'ads.example.com');
  assert.equal(BL.cleanHost('*.tracker.net'), 'tracker.net');
  assert.equal(BL.cleanHost('https://x.example.com/path'), '');
  assert.equal(BL.cleanHost('x.example.com/path'), 'x.example.com');
  assert.equal(BL.cleanHost('localhost'), '');
  assert.equal(BL.cleanHost('com'), '');
  assert.equal(BL.cleanHost('bad host.com'), '');
  assert.equal(BL.cleanHost('10.0.0.5'), '10.0.0.5');
  assert.equal(BL.cleanHost('999.1.1.1'), '');
});

test('a listed host blocks itself and its subdomains, never its parent or a lookalike', () => {
  const l = BL.createBlocklist();
  l.addHost('ads.example.com');
  assert.equal(l.hostBlocked('ads.example.com'), 'ads.example.com');
  assert.equal(l.hostBlocked('x.y.ads.example.com'), 'ads.example.com');
  assert.equal(l.hostBlocked('example.com'), '');
  assert.equal(l.hostBlocked('www.example.com'), '');
  assert.equal(l.hostBlocked('badads.example.com'), '');
  assert.equal(l.hostBlocked('ads.example.com.evil.test'), '');
  assert.equal(l.removeHost('ads.example.com'), true);
  assert.equal(l.hostBlocked('ads.example.com'), '');
});

test('selectors that could break out of a rule, hide the whole page or run code are refused', () => {
  for (const ok of ['#promo', 'div.popup', 'div.a.b', 'body > div:nth-of-type(2)', 'div[role="dialog"]', 'iframe[src*="ads"]']) assert.equal(BL.validSelector(ok), ok, ok);
  for (const bad of ['', 'body', 'html', '*', ':root', 'a{color:red}', 'a;b', '@import url(x)', 'div\\41', 'a,b', 'div[x="1', 'div)', 'div <script>', 'div /* x */', 'a{', 'x'.repeat(600), 'div:has(url(x))']) assert.equal(BL.validSelector(bad), '', bad);
});

test('element rules apply to the host and its subdomains and make one block of CSS, built once per host', () => {
  const l = BL.createBlocklist();
  assert.equal(l.addElement('site.test', '#promo').added, true);
  assert.equal(l.addElement('site.test', '#promo').added, false);
  assert.equal(l.addElement('site.test', 'div.popup').added, true);
  assert.equal(l.addElement('other.test', '.x').added, true);
  assert.equal(l.addElement('site.test', 'a{x:y}').ok, false);
  const css = l.cssFor('www.site.test');
  assert.equal(css, '#promo{display:none!important}\ndiv.popup{display:none!important}');
  assert.equal(l.cssFor('www.site.test'), css);
  assert.equal(l.cssFor('example.org'), '');
  assert.equal(l.removeElement('site.test', '#promo'), true);
  assert.equal(l.cssFor('www.site.test'), 'div.popup{display:none!important}');
});

test('an imported list takes hosts, hosts-file lines, ||host^ and site##selector, and skips the rest', () => {
  const l = BL.createBlocklist();
  const r = l.importText(['! comment', '# another', '[Adblock Plus 2.0]', '', '0.0.0.0 evil.test', '127.0.0.1 localhost', '||ads.test^$third-party', 'plain.test', 'site.test##.overlay', '##.generic', '@@||ok.test^', '/ads/*.js', 'a b c'].join('\n'));
  assert.deepEqual([r.hosts, r.elements], [3, 1]);
  assert.equal(r.skipped >= 4, true);
  assert.equal(l.hostBlocked('evil.test'), 'evil.test');
  assert.equal(l.hostBlocked('ok.test'), '');
  assert.equal(l.cssFor('site.test'), '.overlay{display:none!important}');
});

test('the list stops growing at the limit', () => {
  const l = BL.createBlocklist();
  const lines = Array.from({ length: BL.MAX_RULES + 50 }, (_, i) => `h${i}.example.com`).join('\n');
  const r = l.importText(lines);
  assert.equal(r.hosts, BL.MAX_RULES);
  assert.equal(r.full, true);
  assert.equal(l.addHost('one-more.example.com').ok, false);
});

test('what a page reports about an element is cleaned before it is shown or used', () => {
  const item = PU.sanitizeItem({ kind: 'weird', tag: 'DIV\n', text: 'Win\u0000 a prize\n now'.repeat(30), selector: 'a{x:y}', frameHost: 'Ads.Example.com', hosts: ['evil.test', 'not a host', 'evil.test', 'x.test'], w: 1e9, h: -4, z: 1e12, fixed: 1 }, 'page.test');
  assert.equal(item.kind, 'overlay');
  assert.equal(item.tag.includes('\n'), false);
  assert.equal(item.text.length <= 80, true);
  assert.equal(/[\u0000-\u001f]/.test(item.text), false);
  assert.equal(item.selector, '');
  assert.equal(item.frameHost, 'ads.example.com');
  assert.equal(item.thirdParty, true);
  assert.deepEqual(item.hosts, ['evil.test', 'x.test']);
  assert.equal(item.w, 99999);
  assert.equal(item.h, 0);
  assert.equal(item.z, 2147483647);
  assert.equal(PU.sanitizeItem(null, 'x'), null);
});

test('the in-page scripts are plain text that evaluates to a call', () => {
  for (const src of [PU.call(PU.findFn, PU.describeFn), PU.call(PU.pickFn, PU.describeFn, 'abc'), PU.call(PU.cancelFn, 'abc'), PU.call(PU.outlineFn, '#x'), PU.call(PU.applyFn, 'a{b:c}')]) {
    assert.doesNotThrow(() => new Function(`return ${src}`));
  }
});
