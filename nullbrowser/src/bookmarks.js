const MAX_BOOKMARKS = 500;
const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_TITLE = 200;

function unescapeHtml(s) {
  return String(s || '')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/gi, "'")
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&');
}

function hrefOf(tag) {
  const m = /\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(tag || '');
  return m ? unescapeHtml(m[1] || m[2] || m[3] || '').trim() : '';
}

function isPageUrl(url) {
  try {
    return /^https?:$/i.test(new URL(url).protocol);
  } catch {
    return false;
  }
}

function titleOf(inner, fallback) {
  const t = unescapeHtml(String(inner || '').replace(/<[^>]*>/g, '')).replace(/\s+/g, ' ').trim();
  return (t || fallback).slice(0, MAX_TITLE);
}

function parseBookmarks(html) {
  const out = [];
  const seen = new Set();
  const text = String(html || '').slice(0, MAX_FILE_BYTES);
  const re = /<a\b([^>]*)>([\s\S]*?)<\/a>/gi;
  let m;
  while (out.length < MAX_BOOKMARKS && (m = re.exec(text))) {
    const url = hrefOf(m[1]);
    if (!url || !isPageUrl(url) || seen.has(url)) continue;
    seen.add(url);
    out.push({ url, title: titleOf(m[2], url) });
  }
  return out;
}

module.exports = { MAX_BOOKMARKS, MAX_FILE_BYTES, parseBookmarks };
