const CRASH_WINDOW_MS = 60000;
const CRASH_COUNT = 2;
const FAKE_FILE_WINDOW_MS = 120000;
const FAKE_FILE_COUNT = 2;
const POPUP_CAP_WINDOW_MS = 30000;
const POPUP_CAP_COUNT = 3;
const FANOUT_WINDOW_MS = 10000;
const FANOUT_HOSTS = 15;
const CPU_IDLE_MS = 5000;
const CPU_PERCENT = 60;
const CPU_SAMPLES = 3;

function createWatchdog({ onFlag, now = Date.now }) {
  const crashes = new Map();
  const fakeFiles = new Map();
  const popupCaps = new Map();
  const cpuStreak = new Map();
  let fanoutSite = '';
  let fanoutStart = 0;
  let fanoutHosts = new Set();

  function prune(list, windowMs) {
    const t = now();
    while (list.length && t - list[0] > windowMs) list.shift();
  }

  function bump(map, site, windowMs, count, reason) {
    if (!site) return;
    const list = map.get(site) || [];
    list.push(now());
    prune(list, windowMs);
    map.set(site, list);
    if (list.length >= count) {
      map.set(site, []);
      onFlag(site, reason);
    }
  }

  function noteCrash(site) {
    bump(crashes, site, CRASH_WINDOW_MS, CRASH_COUNT, 'crashed repeatedly');
  }

  function noteFakeFile(site) {
    bump(fakeFiles, site, FAKE_FILE_WINDOW_MS, FAKE_FILE_COUNT, 'sent disguised files repeatedly');
  }

  function notePopupCapped(site) {
    bump(popupCaps, site, POPUP_CAP_WINDOW_MS, POPUP_CAP_COUNT, 'kept opening pop-ups after being capped');
  }

  function noteSubresource(site, host) {
    if (!site || !host) return;
    const t = now();
    if (site !== fanoutSite || t - fanoutStart > FANOUT_WINDOW_MS) {
      fanoutSite = site;
      fanoutStart = t;
      fanoutHosts = new Set();
    }
    fanoutHosts.add(host);
    if (fanoutHosts.size >= FANOUT_HOSTS) {
      fanoutHosts = new Set();
      fanoutStart = t;
      onFlag(site, 'contacted many different hosts at once');
    }
  }

  function noteCpu(site, idle, percent) {
    if (!site) return;
    if (!idle || percent < CPU_PERCENT) {
      cpuStreak.delete(site);
      return;
    }
    const n = (cpuStreak.get(site) || 0) + 1;
    if (n >= CPU_SAMPLES) {
      cpuStreak.set(site, 0);
      onFlag(site, 'used heavy CPU while idle');
    } else {
      cpuStreak.set(site, n);
    }
  }

  return { noteCrash, noteFakeFile, notePopupCapped, noteSubresource, noteCpu };
}

module.exports = {
  createWatchdog,
  CRASH_WINDOW_MS,
  CRASH_COUNT,
  FAKE_FILE_WINDOW_MS,
  FAKE_FILE_COUNT,
  POPUP_CAP_WINDOW_MS,
  POPUP_CAP_COUNT,
  FANOUT_WINDOW_MS,
  FANOUT_HOSTS,
  CPU_IDLE_MS,
  CPU_PERCENT,
  CPU_SAMPLES,
};
