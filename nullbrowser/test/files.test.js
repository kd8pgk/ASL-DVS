const test = require('node:test');
const assert = require('node:assert/strict');
const F = require('../src/files');

test('only PDF, audio and video are handed on; the type comes from the server, or the name when the server does not say', () => {
  assert.equal(F.classify('application/pdf', 'x.bin'), 'pdf');
  assert.equal(F.classify('audio/mpeg; charset=x', 'a'), 'audio');
  assert.equal(F.classify('video/mp4', 'a'), 'video');
  assert.equal(F.classify('application/octet-stream', 'talk.MP3'), 'audio');
  assert.equal(F.classify('', 'film.webm'), 'video');
  assert.equal(F.classify('application/octet-stream', 'setup.exe'), null);
  assert.equal(F.classify('application/zip', 'x.pdf'), null, 'a stated type that is not a document wins over the name');
  assert.equal(F.classify('text/html', 'x.pdf'), null);
});

test('the content must match: a PDF starts %PDF-, audio and video have their own signatures', () => {
  const pdf = Buffer.from('%PDF-1.7\n...');
  const mp3 = Buffer.from([0x49, 0x44, 0x33, 4, 0, 0]);
  const frame = Buffer.from([0xff, 0xfb, 0x90, 0x00]);
  const mp4 = Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from('ftypisom'), Buffer.alloc(8)]);
  const m4a = Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from('ftypM4A '), Buffer.alloc(8)]);
  const webm = Buffer.from([0x1a, 0x45, 0xdf, 0xa3, 1, 2]);
  const wav = Buffer.concat([Buffer.from('RIFF'), Buffer.alloc(4), Buffer.from('WAVEfmt ')]);
  const html = Buffer.from('<!doctype html><script>');
  assert.equal(F.contentMatches('pdf', pdf), true);
  assert.equal(F.contentMatches('pdf', html), false);
  assert.equal(F.contentMatches('pdf', mp4), false);
  for (const b of [mp3, frame, m4a, wav, webm, mp4]) assert.equal(F.contentMatches('audio', b), true);
  for (const b of [mp4, webm]) assert.equal(F.contentMatches('video', b), true);
  assert.equal(F.contentMatches('video', mp3), false);
  assert.equal(F.contentMatches('audio', html), false);
  assert.equal(F.contentMatches('audio', Buffer.alloc(0)), false);
});

test('the question names the file, its kind, its size and the app', () => {
  assert.equal(F.question('report.pdf', 'pdf', 2202009), 'Open report.pdf (PDF, 2.1 MB) in your PDF viewer?');
  assert.equal(F.question('a.mp3', 'audio', 0), 'Open a.mp3 (audio) in your music player?');
  assert.equal(F.question('b.mp4', 'video', 500), 'Open b.mp4 (video, 500 bytes) in your video player?');
});

test('saved names cannot climb out of the RAM folder or hide', () => {
  assert.equal(F.safeName('../../etc/passwd'), '_.._etc_passwd');
  assert.equal(F.safeName('a/b\\c.pdf'), 'a_b_c.pdf');
  assert.equal(F.safeName('...hidden.pdf'), 'hidden.pdf');
  assert.equal(F.safeName(''), 'file');
  assert.ok(!F.safeName('../x').includes('/'));
});
