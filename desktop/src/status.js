const { homeTarget, lanTarget, awayTarget } = require('./node');
const { tcpProbe } = require('./route');

const INTERVAL_MS = 15000;

function targetsFor(node, page) {
  return [homeTarget(node, page), lanTarget(node, page), awayTarget(node, page)].filter(Boolean);
}

function createMonitor({ getNodes, getPages, onChange, probe = tcpProbe, interval = INTERVAL_MS, setTimer = setInterval, clearTimer = clearInterval }) {
  const up = new Map();
  let timer = null;
  let running = false;
  let again = false;

  async function reachable(node, page) {
    for (const t of targetsFor(node, page)) {
      if (await probe(t)) return true;
    }
    return false;
  }

  async function refresh() {
    if (running) {
      again = true;
      return;
    }
    running = true;
    try {
      const nodes = getNodes();
      const pages = getPages();
      const jobs = [];
      for (const n of nodes) for (const p of pages) jobs.push(reachable(n, p).then((ok) => [`${n.id}:${p.id}`, ok]));
      const results = await Promise.all(jobs);
      const next = new Map(results);
      let changed = next.size !== up.size;
      for (const [k, v] of next) if (up.get(k) !== v) changed = true;
      up.clear();
      for (const [k, v] of next) up.set(k, v);
      if (changed) onChange(snapshot());
    } finally {
      running = false;
      if (again) {
        again = false;
        refresh();
      }
    }
  }

  function snapshot() {
    return { down: [...up].filter(([, v]) => v === false).map(([k]) => k), known: [...up.keys()] };
  }

  function isDown(key) {
    return up.get(key) === false;
  }

  function start() {
    if (timer) return;
    refresh();
    timer = setTimer(refresh, interval);
    if (timer && typeof timer.unref === 'function') timer.unref();
  }

  function stop() {
    if (timer) clearTimer(timer);
    timer = null;
  }

  return { refresh, snapshot, isDown, start, stop };
}

module.exports = { createMonitor, targetsFor, INTERVAL_MS };
