const MAX_BYTES = 512 * 1024 * 1024;

const KIND_LABEL = { pdf: 'PDF', audio: 'audio', video: 'video' };
const APP_LABEL = { pdf: 'your PDF viewer', audio: 'your music player', video: 'your video player' };

const EXT_KIND = {
  pdf: 'pdf',
  mp3: 'audio', m4a: 'audio', aac: 'audio', ogg: 'audio', oga: 'audio', opus: 'audio', flac: 'audio', wav: 'audio',
  mp4: 'video', m4v: 'video', webm: 'video', mkv: 'video', mov: 'video', ogv: 'video',
};

function kindOfMime(mime) {
  const m = String(mime || '').toLowerCase().split(';')[0].trim();
  if (m === 'application/pdf' || m === 'application/x-pdf') return 'pdf';
  if (m.startsWith('audio/')) return 'audio';
  if (m.startsWith('video/')) return 'video';
  return null;
}

function kindOfName(name) {
  const m = /\.([a-z0-9]{2,5})$/i.exec(String(name || ''));
  return m ? EXT_KIND[m[1].toLowerCase()] || null : null;
}

function classify(mime, name) {
  const byMime = kindOfMime(mime);
  if (byMime) return byMime;
  const generic = !mime || /^(application\/octet-stream|binary\/octet-stream)$/i.test(String(mime).split(';')[0].trim());
  return generic ? kindOfName(name) : null;
}

function sniff(buf) {
  const b = Buffer.isBuffer(buf) ? buf : Buffer.from(buf || []);
  const at = (i, s) => b.length >= i + s.length && b.toString('latin1', i, i + s.length) === s;
  if (at(0, '%PDF-')) return 'pdf';
  if (b.length >= 4 && b[0] === 0x1a && b[1] === 0x45 && b[2] === 0xdf && b[3] === 0xa3) return 'av';
  if (at(4, 'ftyp')) {
    const brand = b.toString('latin1', 8, 12);
    return /^(M4A |M4B |M4P )$/.test(brand) ? 'audio' : 'av';
  }
  if (at(0, 'OggS')) return 'av';
  if (at(0, 'fLaC')) return 'audio';
  if (at(0, 'RIFF') && at(8, 'WAVE')) return 'audio';
  if (at(0, 'ID3')) return 'audio';
  if (b.length >= 2 && b[0] === 0xff && (b[1] & 0xe0) === 0xe0) return 'audio';
  if (at(4, 'moov') || at(4, 'mdat') || at(4, 'free') || at(4, 'wide')) return 'av';
  return null;
}

function contentMatches(kind, buf) {
  const s = sniff(buf);
  if (!s) return false;
  if (kind === 'pdf') return s === 'pdf';
  if (kind === 'audio') return s === 'audio' || s === 'av';
  if (kind === 'video') return s === 'av';
  return false;
}

function safeName(name) {
  const n = String(name || '').replace(/[\\/\0]/g, '_').replace(/^\.+/, '').replace(/[^\w.\- ()[\]]/g, '_').slice(-120);
  return n || 'file';
}

function size(bytes) {
  const n = Number(bytes) || 0;
  if (n <= 0) return '';
  if (n < 1024) return `${n} bytes`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function question(name, kind, bytes) {
  const s = size(bytes);
  return `Open ${name} (${KIND_LABEL[kind]}${s ? `, ${s}` : ''}) in ${APP_LABEL[kind]}?`;
}

module.exports = { MAX_BYTES, KIND_LABEL, kindOfMime, kindOfName, classify, sniff, contentMatches, safeName, size, question };
