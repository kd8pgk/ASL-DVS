const P = require('./policy');

const LH_PARTITION = 'lasthard';

function createSessions({ session, getNodes, log }) {
  const hardened = new WeakSet();
  const partitions = new Map();

  function nodeOfPartition(ses) {
    const hit = [...partitions].find(([, v]) => v === ses);
    return hit ? getNodes().find((n) => n.id === hit[0]) : null;
  }

  function allNodeHosts() {
    return getNodes().flatMap((n) => P.hostsOfNode(n));
  }

  function nodeSession(node) {
    const ses = session.fromPartition(`persist:node-${node.id}`);
    partitions.set(node.id, ses);
    harden(ses, 'node');
    return ses;
  }

  function lastHeardSession() {
    const ses = session.fromPartition(LH_PARTITION);
    harden(ses, 'lh');
    return ses;
  }

  const refusedSeen = new Set();

  function logRefused(kind, permission) {
    const k = `${kind}:${permission}`;
    if (refusedSeen.has(k)) return;
    refusedSeen.add(k);
    log(`permission refused: ${permission} (${kind} pages)`);
  }

  function harden(ses, kind) {
    if (hardened.has(ses)) return;
    hardened.add(ses);
    const hostsFor = () => {
      const n = kind === 'node' ? nodeOfPartition(ses) : null;
      return n ? P.hostsOfNode(n) : [];
    };
    ses.setPermissionRequestHandler((wc, permission, callback, details) => {
      const origin = (details && details.requestingUrl) || (wc && !wc.isDestroyed() ? wc.getURL() : '');
      const media = permission === 'media' && details ? details.mediaTypes : undefined;
      const ok = P.allowPermission(permission, origin, hostsFor(), media);
      if (!ok) logRefused(kind, permission);
      callback(ok);
    });
    ses.setPermissionCheckHandler((wc, permission, origin, details) => {
      const media = permission === 'media' && details ? details.mediaType : undefined;
      const ok = P.allowPermission(permission, origin, hostsFor(), media);
      if (!ok) logRefused(kind, permission);
      return ok;
    });
    ses.setDevicePermissionHandler(() => false);
    ses.setSpellCheckerEnabled(false);
    ses.webRequest.onBeforeRequest({ urls: ['<all_urls>'] }, (details, callback) => {
      let ok;
      if (kind === 'node') ok = P.allowRequest(details.url, hostsFor());
      else if (kind === 'lh') ok = P.allowLastHeardRequest(details.url, allNodeHosts());
      else ok = P.allowShellRequest(details.url);
      callback({ cancel: !ok });
    });
  }

  function nodePartition(id) {
    return partitions.get(id) || session.fromPartition(`persist:node-${id}`);
  }

  return { nodeSession, lastHeardSession, harden, allNodeHosts, nodePartition };
}

module.exports = { createSessions, LH_PARTITION };
