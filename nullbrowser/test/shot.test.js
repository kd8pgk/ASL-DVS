const test = require('node:test');
const assert = require('node:assert/strict');
const S = require('../src/shot');
const { checkPdf } = S;

const pdf = (pages = 1) => Buffer.from(`%PDF-1.4\n${'<</Type /Page /Parent 2 0 R>>\n'.repeat(pages)}${' '.repeat(2000)}\n%%EOF\n`, 'latin1');

test('a PDF made by us passes, with its hash', () => {
  const b = pdf(2);
  assert.deepEqual(checkPdf(b, S.sha256(b)), { ok: true, pages: 2 });
});

test('a file that changed after it was made is refused', () => {
  const b = pdf();
  const sha = S.sha256(b);
  const changed = Buffer.from(b);
  changed[10] ^= 1;
  assert.equal(checkPdf(changed, sha).ok, false);
  assert.match(checkPdf(changed, sha).reason, /changed/);
});

test('a file without a recorded hash is refused', () => {
  assert.equal(checkPdf(pdf(), '').ok, false);
});

test('a program or a page dressed as a PDF is refused', () => {
  const mz = Buffer.concat([Buffer.from('MZ'), Buffer.alloc(4096)]);
  assert.match(checkPdf(mz, S.sha256(mz)).reason, /start like a PDF/);
  const html = Buffer.from(`%PDF-1.4 ${'<script>x</script>'.repeat(200)}`);
  assert.match(checkPdf(html, S.sha256(html)).reason, /end like a PDF|no readable page/);
});

test('an empty or huge file is refused', () => {
  assert.equal(checkPdf(Buffer.alloc(0), 'x').ok, false);
  assert.equal(checkPdf(Buffer.alloc(10), 'x').ok, false);
});

test('a PDF with no page is refused', () => {
  const b = Buffer.from(`%PDF-1.4\n/Type /Pages\n${' '.repeat(2000)}\n%%EOF\n`, 'latin1');
  assert.match(checkPdf(b, S.sha256(b)).reason, /no readable page/);
});

test('the Downloads folder comes from user-dirs.dirs, or the home folder', () => {
  assert.equal(S.downloadsFromUserDirs('XDG_DOWNLOAD_DIR="$HOME/Grabs"\n', '/home/me'), '/home/me/Grabs');
  assert.equal(S.downloadsFromUserDirs('XDG_DOWNLOAD_DIR="/data/dl"\n', '/home/me'), '/data/dl');
  assert.equal(S.downloadsFromUserDirs('XDG_DOCUMENTS_DIR="$HOME/Docs"\n', '/home/me'), '/home/me/Downloads');
  assert.equal(S.downloadsFromUserDirs('XDG_DOWNLOAD_DIR="relative"\n', '/home/me'), '/home/me/Downloads');
  assert.equal(S.downloadsFromUserDirs('', '/home/me'), '/home/me/Downloads');
});

test('the file name has no site name in it, and never overwrites', () => {
  const name = S.shotName(new Date(2026, 10, 26, 9, 5, 7));
  assert.equal(name, 'Null-Browser-2026-11-26-090507.pdf');
  const taken = new Set([name]);
  assert.equal(S.uniqueName(name, (n) => taken.has(n)), 'Null-Browser-2026-11-26-090507-2.pdf');
  assert.equal(S.uniqueName('a.pdf', () => false), 'a.pdf');
});
