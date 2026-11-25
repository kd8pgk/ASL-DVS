const test = require('node:test');
const assert = require('node:assert/strict');
const B = require('../src/bookmarks');

test('a Netscape bookmarks export is parsed into title and url, folders included', () => {
  const html = `<!DOCTYPE NETSCAPE-Bookmark-file-1>
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
<DT><A HREF="https://example.com/" ADD_DATE="1">Example &amp; Co</A>
<DT><H3>Folder</H3>
<DL><p>
<DT><A HREF="http://foo.test/page">Foo</A>
</DL><p>
</DL><p>`;
  const found = B.parseBookmarks(html);
  assert.deepEqual(found, [
    { url: 'https://example.com/', title: 'Example & Co' },
    { url: 'http://foo.test/page', title: 'Foo' },
  ]);
});

test('non-http(s) links, duplicates and entries with no readable title', () => {
  const html = `
<A HREF="javascript:alert(1)">evil</A>
<A HREF="ftp://files.test/x">ftp</A>
<A HREF="https://a.test/">first</A>
<A HREF="https://a.test/">second time, same url</A>
<A HREF="https://b.test/"><b>bold</b> text</A>
<A HREF="https://c.test/"></A>`;
  const found = B.parseBookmarks(html);
  assert.deepEqual(found, [
    { url: 'https://a.test/', title: 'first' },
    { url: 'https://b.test/', title: 'bold text' },
    { url: 'https://c.test/', title: 'https://c.test/' },
  ]);
});

test('a url in single quotes or unquoted is still read, and a bad url is skipped', () => {
  const html = `<a href='https://q.test/'>q</a> <a href=https://u.test/>u</a> <a href="not a url">x</a>`;
  const found = B.parseBookmarks(html);
  assert.deepEqual(found, [
    { url: 'https://q.test/', title: 'q' },
    { url: 'https://u.test/', title: 'u' },
  ]);
});

test('the list is capped, and a very long title is cut down', () => {
  const many = Array.from({ length: B.MAX_BOOKMARKS + 50 }, (_, i) => `<a href="https://site${i}.test/">s${i}</a>`).join('\n');
  assert.equal(B.parseBookmarks(many).length, B.MAX_BOOKMARKS);

  const longTitle = 'x'.repeat(500);
  const found = B.parseBookmarks(`<a href="https://long.test/">${longTitle}</a>`);
  assert.equal(found[0].title.length, 200);
});

test('only the first MAX_FILE_BYTES of a huge file are scanned', () => {
  const pad = ' '.repeat(B.MAX_FILE_BYTES);
  const html = `${pad}<a href="https://late.test/">late</a>`;
  assert.deepEqual(B.parseBookmarks(html), []);
});
