const crypto = require('node:crypto');
const path = require('node:path');

const MAX_SHOT_BYTES = 64 * 1024 * 1024;
const MIN_SHOT_BYTES = 1024;
const MAX_PAGES = 500;

function sha256(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

function checkPdf(buf, recordedSha) {
  if (!Buffer.isBuffer(buf)) return { ok: false, reason: 'the screenshot is empty' };
  if (buf.length < MIN_SHOT_BYTES) return { ok: false, reason: 'the screenshot is too small to be a PDF' };
  if (buf.length > MAX_SHOT_BYTES) return { ok: false, reason: 'the screenshot is too big' };
  if (buf.subarray(0, 5).toString('latin1') !== '%PDF-') return { ok: false, reason: 'the file does not start like a PDF' };
  if (!buf.subarray(Math.max(0, buf.length - 1024)).toString('latin1').includes('%%EOF')) return { ok: false, reason: 'the file does not end like a PDF' };
  const pages = (buf.toString('latin1').match(/\/Type\s*\/Page(?!s)/g) || []).length;
  if (pages < 1 || pages > MAX_PAGES) return { ok: false, reason: 'the screenshot has no readable page' };
  if (!recordedSha || sha256(buf) !== recordedSha) return { ok: false, reason: 'the file changed after it was made' };
  return { ok: true, pages };
}

function downloadsFromUserDirs(text, home) {
  const m = /^\s*XDG_DOWNLOAD_DIR\s*=\s*"?([^"\n]*)"?/m.exec(String(text || ''));
  if (!m || !m[1].trim()) return path.join(home, 'Downloads');
  const value = m[1].trim().replace(/\$HOME|\$\{HOME\}/g, home);
  if (!path.isAbsolute(value)) return path.join(home, 'Downloads');
  return value;
}

function shotName(date) {
  const p = (n) => String(n).padStart(2, '0');
  return `Null-Browser-${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}-${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}.pdf`;
}

function uniqueName(name, exists) {
  if (!exists(name)) return name;
  const ext = path.extname(name);
  const stem = name.slice(0, name.length - ext.length);
  for (let i = 2; i < 1000; i += 1) {
    const next = `${stem}-${i}${ext}`;
    if (!exists(next)) return next;
  }
  return null;
}

module.exports = { MAX_SHOT_BYTES, sha256, checkPdf, downloadsFromUserDirs, shotName, uniqueName };
