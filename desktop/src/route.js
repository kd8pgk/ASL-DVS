const net = require('node:net');
const { homeTarget, lanTarget, awayTarget } = require('./node');

const HOME_MS = 1500;
const KEEP_MS = 30000;

function tcpProbe(target, timeout = HOME_MS) {
  return new Promise((resolve) => {
    const s = net.connect({ host: target.host, port: target.port });
    let done = false;
    const end = (ok) => {
      if (done) return;
      done = true;
      s.destroy();
      resolve(ok);
    };
    s.setTimeout(timeout, () => end(false));
    s.once('connect', () => end(true));
    s.once('error', () => end(false));
  });
}

function createRouter({ probe = tcpProbe, now = Date.now } = {}) {
  const seen = new Map();

  async function pick(node, page) {
    const home = homeTarget(node, page);
    const lan = lanTarget(node, page);
    const away = awayTarget(node, page);
    if (!lan && !away) return home;
    const key = `${node.id}:${page.id}`;
    const hit = seen.get(key);
    if (hit && now() - hit.at < KEEP_MS) return hit.target;
    let target = home;
    if (!(await probe(home))) {
      if (lan && (await probe(lan))) target = lan;
      else if (away) target = away;
    }
    seen.set(key, { at: now(), target });
    return target;
  }

  function forget(nodeId) {
    for (const k of [...seen.keys()]) if (k.startsWith(`${nodeId}:`)) seen.delete(k);
  }

  return { pick, forget };
}

module.exports = { createRouter, tcpProbe, HOME_MS, KEEP_MS };
