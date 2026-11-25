const ALLOWED_PERMISSIONS = new Set(['media', 'clipboard-sanitized-write', 'speaker-selection']);

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
];

const SWITCHES = [
  'disable-background-networking',
  'disable-component-update',
  'disable-default-apps',
  'disable-sync',
  'disable-domain-reliability',
  'disable-client-side-phishing-detection',
  'disable-breakpad',
  'no-pings',
  'no-default-browser-check',
];

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
  'proxy-server',
  'user-data-dir',
  'enable-logging',
  'renderer-cmd-prefix',
  'utility-cmd-prefix',
  'gpu-launcher',
];

function unsafeSwitches(argv) {
  const found = [];
  for (const a of argv) {
    const m = /^--?([a-z][a-z0-9-]*)(=|$)/i.exec(String(a));
    if (m && UNSAFE_SWITCHES.includes(m[1].toLowerCase())) found.push(m[1].toLowerCase());
  }
  return found;
}

function sandboxOff(argv) {
  return argv.some((a) => /^--?no-sandbox$/i.test(String(a)));
}

function originHost(origin) {
  try {
    return new URL(origin).hostname.replace(/^\[|\]$/g, '').toLowerCase();
  } catch {
    return '';
  }
}

function audioOnly(types) {
  if (typeof types === 'string') return types === 'audio';
  return Array.isArray(types) && types.length > 0 && types.every((t) => t === 'audio');
}

function allowPermission(permission, origin, hosts, media) {
  if (!ALLOWED_PERMISSIONS.has(permission)) return false;
  if (!hosts.includes(originHost(origin))) return false;
  if (permission === 'media') return audioOnly(media);
  return true;
}

function allowRequest(url, hosts) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return false;
  }
  if (u.protocol === 'data:' || u.protocol === 'blob:') return true;
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(u.protocol)) return false;
  if (u.pathname.toLowerCase() === '/favicon.ico') return false;
  return hosts.includes(u.hostname.replace(/^\[|\]$/g, '').toLowerCase());
}

function allowShellRequest(url) {
  return /^(file|data):/i.test(url);
}

const NEVER_IDLE = new Set(['talker']);

function neverIdle(pageId) {
  return NEVER_IDLE.has(pageId);
}

const LAST_HEARD_NAMES = { talker: 'nt_lh', controller: 'asl_dvs_lh' };

function isLastHeardWindow(pageId, frameName) {
  return Object.prototype.hasOwnProperty.call(LAST_HEARD_NAMES, pageId) && LAST_HEARD_NAMES[pageId] === frameName;
}

function isPrivateHost(host) {
  const h = String(host || '').toLowerCase().replace(/^\[|\]$/g, '');
  if (!h) return true;
  if (h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.local') || h.endsWith('.internal') || h.endsWith('.lan') || h.endsWith('.home.arpa')) return true;
  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    return a === 0 || a === 10 || a === 127 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127) || a >= 224;
  }
  if (h.includes(':')) {
    if (h === '::' || h === '::1') return true;
    const mapped = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/.exec(h);
    if (mapped) return isPrivateHost(mapped[1]);
    return /^f[cd]/.test(h) || /^fe[89ab]/.test(h);
  }
  if (!h.includes('.')) return true;
  return false;
}

function lastHeardOk(url, nodeHosts) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return false;
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
  if (u.username || u.password || String(url).length > 2048) return false;
  const host = u.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  return !isPrivateHost(host) || nodeHosts.includes(host);
}

function allowLastHeardRequest(url, nodeHosts) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return false;
  }
  if (u.protocol === 'data:' || u.protocol === 'blob:') return true;
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(u.protocol)) return false;
  const host = u.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  return !isPrivateHost(host) || nodeHosts.includes(host);
}

function hostsOfNode(node) {
  return [node.host, node.lanIp, node.awayHost].filter(Boolean).map((h) => h.toLowerCase());
}

module.exports = {
  sandboxOff,
  ALLOWED_PERMISSIONS,
  DISABLED_FEATURES,
  SWITCHES,
  UNSAFE_SWITCHES,
  unsafeSwitches,
  allowPermission,
  allowRequest,
  allowShellRequest,
  NEVER_IDLE,
  neverIdle,
  LAST_HEARD_NAMES,
  isLastHeardWindow,
  isPrivateHost,
  lastHeardOk,
  allowLastHeardRequest,
  hostsOfNode,
};
