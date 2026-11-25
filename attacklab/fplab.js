const FP_TESTS = [
  { id: 'fingerprint', kind: 'auto', title: 'Minimal info: what the browser tells a site', expect: 'One language, only the basic browser hints (no OS version, CPU type, model or full version list), no line speed or memory, the cross-site Referer cut to the site name, and nothing faked.' },
];

const FP_IDS = new Set(FP_TESTS.map((t) => t.id));

const HIGH = ['sec-ch-ua-platform-version', 'sec-ch-ua-arch', 'sec-ch-ua-bitness', 'sec-ch-ua-model', 'sec-ch-ua-full-version', 'sec-ch-ua-full-version-list', 'sec-ch-ua-wow64', 'sec-ch-ua-form-factors'];
const LINE = ['ect', 'rtt', 'downlink', 'save-data', 'device-memory', 'sec-ch-device-memory', 'sec-ch-viewport-width', 'sec-ch-dpr', 'dpr', 'viewport-width', 'sec-ch-prefers-color-scheme', 'sec-ch-prefers-reduced-motion'];
const ACCEPT_CH = 'Sec-CH-UA-Platform-Version, Sec-CH-UA-Arch, Sec-CH-UA-Bitness, Sec-CH-UA-Model, Sec-CH-UA-Full-Version-List, Sec-CH-UA-WoW64, Sec-CH-UA-Form-Factors, ECT, RTT, Downlink, Device-Memory, Sec-CH-Device-Memory, Sec-CH-DPR, Sec-CH-Viewport-Width, Sec-CH-Prefers-Color-Scheme';

function createFpLab({ ev, of }) {
  const pick = (headers, names) => names.filter((n) => headers[n] !== undefined).map((n) => `${n}=${String(headers[n]).slice(0, 60)}`);

  function record(req, step) {
    const h = req.headers;
    ev('fingerprint', `headers-${step}`, JSON.stringify({
      lang: h['accept-language'] || '',
      low: pick(h, ['sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform']),
      high: pick(h, HIGH),
      line: pick(h, LINE),
      referer: h.referer || '',
      ua: h['user-agent'] || '',
    }));
  }

  function page(port, otherHost, scheme) {
    const js = `var T='fingerprint';function b(w,d){try{fetch('/ev?t=fingerprint&w='+encodeURIComponent(w)+'&d='+encodeURIComponent(d)+'&r='+Math.random(),{cache:'no-store'})}catch(e){}}
var o={};try{o.languages=(navigator.languages||[]).join(',')}catch(e){o.languages='error'}
o.connection='connection' in navigator?(navigator.connection?JSON.stringify({type:navigator.connection.effectiveType,down:navigator.connection.downlink,rtt:navigator.connection.rtt,save:navigator.connection.saveData}):'present'):'absent';
o.deviceMemory='deviceMemory' in navigator?String(navigator.deviceMemory):'absent';
o.cores='hardwareConcurrency' in navigator?String(navigator.hardwareConcurrency):'absent';
o.battery='getBattery' in navigator?'present':'absent';
o.usb='usb' in navigator?'present':'absent';o.serial='serial' in navigator?'present':'absent';o.hid='hid' in navigator?'present':'absent';
o.ua=navigator.userAgent;
var hi=['platformVersion','architecture','bitness','model','fullVersionList','uaFullVersion','wow64','formFactors'];
var done=function(){b('script',JSON.stringify(o));b('done','1')};
var tests=[];
if(navigator.getBattery){tests.push(navigator.getBattery().then(function(x){o.batteryRead='level '+x.level},function(e){o.batteryRead='denied '+e.name}))}
if(navigator.userAgentData&&navigator.userAgentData.getHighEntropyValues){tests.push(navigator.userAgentData.getHighEntropyValues(hi).then(function(v){o.highEntropy=Object.keys(v).filter(function(k){return hi.indexOf(k)>=0&&v[k]!==undefined&&v[k]!==''&&!(Array.isArray(v[k])&&!v[k].length)}).join(',')},function(e){o.highEntropy='refused '+e.name}))}else{o.highEntropy='no userAgentData'}
Promise.all(tests).then(done,done);`;
    return `<!doctype html><html><head><meta charset="utf-8"><title>What the browser tells a site</title><meta name="referrer" content="unsafe-url"></head>
<body style="font-family:system-ui;background:#0d1117;color:#fff;padding:16px"><h1 style="color:#ffd040">What the browser tells a site</h1>
<p>Open this page over https (the lab's second port) so the browser hints can be sent at all. This page asked for every detailed hint (Accept-CH) and set its Referer policy to send the full address. Reload it once so the hints can be sent, then follow the link to another site.</p>
<p><a id="again" href="/fp/again" style="color:#22d4ff">1. load again (hints asked for)</a></p>
<p><a id="cross" href="${scheme}://${otherHost}:${port}/fp/cross?secret=abc123" style="color:#22d4ff">2. go to another site</a></p>
<script>${js}</script></body></html>`;
  }

  function handle(req, res, url, port, httpsPort) {
    const p = url.pathname;
    if (p === '/t/fingerprint' || p === '/fp/again') {
      record(req, p === '/t/fingerprint' ? 'first' : 'again');
      const otherHost = /^localhost(:|$)/i.test(String(req.headers.host || '')) ? '127.0.0.1' : 'localhost';
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Accept-CH': ACCEPT_CH, 'Critical-CH': 'Sec-CH-UA-Platform-Version, Sec-CH-UA-Model', 'Referrer-Policy': 'unsafe-url' });
      const secure = Boolean(req.socket && req.socket.encrypted);
      res.end(page(secure ? httpsPort : port, otherHost, secure ? 'https' : 'http'));
      return true;
    }
    if (p === '/fp/cross') {
      record(req, 'cross');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
      res.end('<!doctype html><title>other site</title><p>You are on another site. See the results page.</p>');
      return true;
    }
    return false;
  }

  function verdict() {
    const list = of('fingerprint');
    const get = (what) => {
      const e = [...list].reverse().find((x) => x.what === what);
      if (!e) return null;
      try {
        return JSON.parse(e.data);
      } catch {
        return null;
      }
    };
    const again = get('headers-again');
    const cross = get('headers-cross');
    const script = get('script');
    if (!get('headers-first')) return { status: 'not run' };
    if (!again || !script) return { status: 'pending', note: 'load the page again (link 1)' };
    if (!cross) return { status: 'pending', note: 'follow link 2 to another site' };
    const problems = [];
    if (/,/.test(again.lang)) problems.push(`languages sent: ${again.lang}`);
    if (again.high.length) problems.push(`detailed hints sent: ${again.high.join(' ')}`);
    if (again.line.length) problems.push(`line or device hints sent: ${again.line.join(' ')}`);
    if (cross.referer && cross.referer !== new URL(cross.referer).origin + '/') problems.push(`full Referer sent across sites: ${cross.referer}`);
    if (script.connection !== 'absent') problems.push(`navigator.connection: ${script.connection}`);
    if (script.deviceMemory !== 'absent') problems.push(`deviceMemory: ${script.deviceMemory}`);
    if (script.cores !== 'absent') problems.push(`hardwareConcurrency: ${script.cores}`);
    if (script.highEntropy && !/^(|refused.*|no userAgentData)$/.test(script.highEntropy)) problems.push(`high-entropy values given: ${script.highEntropy}`);
    if (script.batteryRead && /^level/.test(script.batteryRead)) problems.push('battery level readable');
    if (/,/.test(script.languages)) problems.push(`navigator.languages: ${script.languages}`);
    const note = `lang=${again.lang || '(none)'}; basic hints=${again.low.length}; referer across sites=${cross.referer || '(none)'}; ua=${(again.ua || '').slice(0, 60)}`;
    return problems.length ? { status: 'FAIL', note: `${problems.join('; ')} | ${note}` } : { status: 'pass', note };
  }

  return { handle, verdict };
}

module.exports = { FP_TESTS, FP_IDS, createFpLab };
