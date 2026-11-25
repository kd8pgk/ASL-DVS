const DISABLED_FEATURES = [
  'Translate',
  'MediaRouter',
  'OptimizationHints',
  'OptimizationGuideModelDownloading',
  'AutofillServerCommunication',
  'CertificateTransparencyComponentUpdater',
  'InterestFeedContentSuggestions',
  'PrivacySandboxSettings4',
  'NetworkTimeServiceQuerying',
  'Prerender2',
  'SpareRendererForSitePerProcess',
  'DnsOverHttpsUpgrade',
  'AsyncDns',
];

const SWITCHES = [
  'disable-background-networking',
  'disable-component-update',
  'disable-default-apps',
  'disable-sync',
  'disable-domain-reliability',
  'disable-client-side-phishing-detection',
  'disable-breakpad',
  'disable-gpu-shader-disk-cache',
  'disable-gpu-program-cache',
  'no-pings',
  'no-default-browser-check',
  'dns-over-https-mode=off',
];

const JS_FLAGS = '--jitless';
const FAST_JS_ARG = '--nb-fast-js';

function relaunchArgv(argv, on) {
  const kept = (argv || []).filter((a) => a !== FAST_JS_ARG);
  if (on) kept.push(FAST_JS_ARG);
  return kept;
}

const UNSAFE_SWITCHES = [
  'remote-debugging-port',
  'remote-debugging-pipe',
  'remote-debugging-address',
  'remote-allow-origins',
  'inspect',
  'inspect-brk',
  'inspect-port',
  'js-flags',
  'load-extension',
  'disable-extensions-except',
  'disable-web-security',
  'ignore-certificate-errors',
  'allow-running-insecure-content',
  'host-rules',
  'host-resolver-rules',
  'user-data-dir',
  'enable-logging',
  'renderer-cmd-prefix',
  'utility-cmd-prefix',
  'gpu-launcher',
];

const PAGE_SCHEMES = new Set(['http:', 'https:']);
const SUBRESOURCE_SCHEMES = new Set(['http:', 'https:', 'ws:', 'wss:', 'data:', 'blob:']);

const MULTI_SUFFIXES = new Set([
  'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'me.uk', 'ltd.uk', 'plc.uk', 'net.uk',
  'com.au', 'net.au', 'org.au', 'edu.au', 'gov.au', 'asn.au', 'id.au',
  'co.nz', 'org.nz', 'net.nz', 'govt.nz', 'ac.nz',
  'co.jp', 'ne.jp', 'or.jp', 'ac.jp', 'go.jp',
  'com.br', 'net.br', 'org.br', 'gov.br',
  'co.za', 'org.za', 'gov.za',
  'co.in', 'net.in', 'org.in', 'gov.in', 'ac.in',
  'com.cn', 'net.cn', 'org.cn', 'gov.cn',
  'com.mx', 'org.mx', 'gob.mx',
  'co.kr', 'or.kr', 'go.kr',
  'com.tw', 'org.tw', 'gov.tw',
  'com.hk', 'org.hk', 'gov.hk',
  'com.sg', 'org.sg', 'gov.sg',
  'com.ar', 'gob.ar', 'com.tr', 'gov.tr', 'co.il', 'org.il', 'gov.il',
  'github.io', 'gitlab.io', 'netlify.app', 'vercel.app', 'pages.dev', 'herokuapp.com',
  'blogspot.com', 'appspot.com', 'web.app', 'firebaseapp.com', 'azurewebsites.net', 'cloudfront.net',
]);

function unsafeSwitches(argv) {
  const found = [];
  for (const a of argv) {
    const m = /^--?([a-z][a-z0-9-]*)(=|$)/i.exec(String(a));
    if (m && UNSAFE_SWITCHES.includes(m[1].toLowerCase())) found.push(m[1].toLowerCase());
  }
  return found;
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^\[|\]$/g, '').toLowerCase();
  } catch {
    return '';
  }
}

function isIp(host) {
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.includes(':');
}

function isPrivateHost(host) {
  const h = String(host || '').toLowerCase().replace(/^\[|\]$/g, '');
  if (!h) return true;
  if (h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.local') || h.endsWith('.internal') || h.endsWith('.lan') || h.endsWith('.home.arpa')) return true;
  if (!h.includes('.') && !h.includes(':')) return true;
  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    return a === 0 || a === 10 || a === 127 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127) || a >= 224;
  }
  if (h.includes(':')) {
    if (h === '::' || h === '::1') return true;
    return /^(fc|fd|fe8|fe9|fea|feb)/.test(h) || h.startsWith('::ffff:');
  }
  return false;
}

function siteOf(host) {
  const h = String(host || '').toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '');
  if (!h || isIp(h)) return h;
  const parts = h.split('.');
  if (parts.length <= 2) return h;
  const last2 = parts.slice(-2).join('.');
  if (MULTI_SUFFIXES.has(last2)) return parts.slice(-3).join('.');
  return last2;
}

function isThirdParty(requestUrl, topUrl) {
  const top = hostOf(topUrl);
  const req = hostOf(requestUrl);
  if (!top || !req) return false;
  return siteOf(top) !== siteOf(req);
}

function normalizeInput(text) {
  const t = String(text || '').trim();
  if (!t) return { blank: true };
  if (t === 'about:blank') return { blank: true };
  if (/\s/.test(t)) return { error: 'Type a web address, for example example.com. There is no search box.' };
  let candidate = t;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(t) || /^[^/:]+:\d+(\/|$)/.test(t)) candidate = `https://${t}`;
  let u;
  try {
    u = new URL(candidate);
  } catch {
    return { error: 'That is not a web address.' };
  }
  if (!PAGE_SCHEMES.has(u.protocol)) return { error: `${u.protocol.replace(/:$/, '')} addresses are not opened here.` };
  if (!u.hostname) return { error: 'That is not a web address.' };
  if (u.username || u.password) return { error: 'Addresses with a user name or password in them are not opened here.' };
  return { url: u.toString() };
}

function httpsUpgrade(url, allowHttp) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.protocol !== 'http:') return null;
  const host = u.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (isPrivateHost(host)) return null;
  if (allowHttp && allowHttp.has(host)) return null;
  u.protocol = 'https:';
  return u.toString();
}

function allowPageUrl(url) {
  if (url === 'about:blank') return true;
  try {
    return PAGE_SCHEMES.has(new URL(url).protocol);
  } catch {
    return false;
  }
}

function allowSubresource(url) {
  try {
    return SUBRESOURCE_SCHEMES.has(new URL(url).protocol);
  } catch {
    return false;
  }
}

function certTrustable(host) {
  return isPrivateHost(host);
}

function stripCookieHeaders(headers) {
  const out = {};
  let removed = false;
  for (const [k, v] of Object.entries(headers || {})) {
    if (k.toLowerCase() === 'set-cookie') {
      removed = true;
      continue;
    }
    out[k] = v;
  }
  return { headers: out, removed };
}

function chromiumUserAgent(ua) {
  return String(ua || '').replace(/\s+\S*[Ee]lectron\/\S+/g, '').replace(/\s+null-browser\/\S+/gi, '').replace(/\s+Null Browser\/\S+/g, '').replace(/\s{2,}/g, ' ').trim();
}

module.exports = {
  DISABLED_FEATURES,
  SWITCHES,
  JS_FLAGS,
  FAST_JS_ARG,
  relaunchArgv,
  UNSAFE_SWITCHES,
  unsafeSwitches,
  hostOf,
  isPrivateHost,
  siteOf,
  isThirdParty,
  normalizeInput,
  httpsUpgrade,
  allowPageUrl,
  allowSubresource,
  certTrustable,
  stripCookieHeaders,
  chromiumUserAgent,
};
