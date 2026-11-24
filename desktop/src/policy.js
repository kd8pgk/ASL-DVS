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
  return hosts.includes(u.hostname.replace(/^\[|\]$/g, '').toLowerCase());
}

function allowShellRequest(url) {
  return /^(file|data):/i.test(url);
}

function hostsOfNode(node) {
  return [node.host, node.lanIp, node.awayHost].filter(Boolean).map((h) => h.toLowerCase());
}

module.exports = {
  ALLOWED_PERMISSIONS,
  DISABLED_FEATURES,
  SWITCHES,
  UNSAFE_SWITCHES,
  unsafeSwitches,
  allowPermission,
  allowRequest,
  allowShellRequest,
  hostsOfNode,
};
