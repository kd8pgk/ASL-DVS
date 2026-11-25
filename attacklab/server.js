#!/usr/bin/env node
const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { SLOW_TESTS, SLOW_IDS, createSlowLab } = require('./slowlab');

const EICAR = 'X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*';
const MB = 1024 * 1024;
const CAP = 512 * MB;

function args(argv) {
  const out = { port: 8088, host: '0.0.0.0', thirdParty: '', rate: 5, panel: 24 };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--port') out.port = Number(argv[(i += 1)]);
    else if (argv[i] === '--host') out.host = argv[(i += 1)];
    else if (argv[i] === '--third-party') out.thirdParty = argv[(i += 1)];
    else if (argv[i] === '--rate') out.rate = Number(argv[(i += 1)]);
    else if (argv[i] === '--panel') out.panel = Number(argv[(i += 1)]);
  }
  return out;
}

function lanAddresses() {
  const out = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const a of list || []) if (a.family === 'IPv4' && !a.internal) out.push(a.address);
  }
  return out;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

const TESTS = [
  { id: 'popups', kind: 'auto', title: 'Pop-up flood', expect: 'No pop-up page is ever fetched: the server sees 0 hits on /hit/popup.' },
  { id: 'permissions', kind: 'auto', title: 'Permission grab', expect: 'Camera, microphone, location, notifications and clipboard read are all denied.' },
  { id: 'schemes', kind: 'auto', title: 'Dangerous link types', expect: 'intent:, file:, content:, javascript: and data: navigations are all blocked; the page stays.' },
  { id: 'persist', kind: 'auto', title: 'Survives a restart?', expect: 'After closing and reopening the browser, the cookie, localStorage and IndexedDB set before are gone.' },
  { id: 'size-declared', kind: 'auto', title: 'Oversize file (size declared)', expect: 'A video that says it is 600 MB is refused before most of it is fetched.' },
  { id: 'size-stream', kind: 'auto', title: 'Oversize file (size hidden)', expect: 'A video that never says its size is cut off by 512 MB, not fetched to 600 MB.' },
  { id: 'redirects', kind: 'auto', title: 'Redirect loop', expect: 'The browser gives up on a long redirect chain instead of following all 30 hops.' },
  { id: 'clickfix', kind: 'auto', title: 'ClickFix copy trick', expect: 'The clipboard is off: the page cannot put text on it with execCommand("copy").' },
  { id: 'disguised', kind: 'look', title: 'Disguised files', expect: 'Each fake (program, script, web page, EICAR test file) is refused with an "is not really" notice; only the real PDF opens.' },
  { id: 'polyglot', kind: 'look', title: 'Polyglot PDF', expect: 'Known limit: a real %PDF- file that also carries script passes the type check. The PDF viewer is the last defense.' },
  { id: 'traversal', kind: 'look', title: 'Path in the file name', expect: 'A file named ../../../evil.pdf is saved under a safe name; nothing lands outside the browser.' },
  { id: 'certificate', kind: 'look', title: 'Bad certificate', expect: 'Android: refused. Desktop: on your own network, offered only as "trust for this session" with a fingerprint.' },
  { id: 'fullscreen', kind: 'look', title: 'Fake lock screen', expect: 'Back (or Esc) always gets you out; the page cannot trap you.' },
  { id: 'alerts', kind: 'look', title: 'Alert loop', expect: 'The browser stays usable; you can leave the page.' },
  { id: 'crash', kind: 'look', title: 'Memory bomb', expect: 'The page dies, the browser recovers, and its data is wiped.' },
  { id: 'leave-trap', kind: 'look', title: '"Leave site?" trap', expect: 'After one tap on the page, typing a new address (or closing the window) still leaves it; the page cannot hold you.' },
  { id: 'print-loop', kind: 'look', title: 'Print dialog loop', expect: 'A page calling print() over and over cannot lock the browser; you can still leave it.' },
  { id: 'page-files', kind: 'look', title: 'Files made by the page', expect: 'A program from a data: or blob: address, or an <a download> link, is refused; a fake PDF made in the page is refused as "not really"; only the real PDF made in the page is offered.' },
  { id: 'cpu', kind: 'look', title: 'Hidden miner (busy CPU)', expect: 'Desktop: the watchdog clears the site within about 20 s if you do not touch anything. Android: known gap, no CPU watchdog.' },
  ...SLOW_TESTS,
];

function createLab({ thirdParty = '', httpsPort = 0, rate = 5, panel = 24 } = {}) {
  const events = [];
  const marks = {};
  const streams = {};

  function ev(test, what, data = '', ua = '') {
    events.push({ t: Date.now(), test, what, data: String(data).slice(0, 200), ua: String(ua).slice(0, 200) });
    if (events.length > 5000) events.shift();
  }

  function of(test) {
    return events.filter((e) => e.test === test);
  }

  function last(test, what) {
    const list = of(test).filter((e) => e.what === what);
    return list.length ? list[list.length - 1] : null;
  }

  const slow = createSlowLab({ ev, of, rateKb: rate, panelKb: panel });

  function verdict(test) {
    if (SLOW_IDS.has(test) && !marks[test]) return slow.verdict(test);
    const list = of(test);
    const seen = (w) => list.some((e) => e.what === w);
    if (marks[test.id || test]) return marks[test.id || test];
    switch (test) {
      case 'popups':
        if (!seen('visited')) return { status: 'not run' };
        return seen('hit') ? { status: 'FAIL', note: `${list.filter((e) => e.what === 'hit').length} pop-up page(s) fetched` } : { status: 'pass' };
      case 'permissions': {
        const keys = ['camera', 'mic', 'geo', 'notify', 'clipread'];
        const got = Object.fromEntries(keys.map((k) => [k, last('permissions', k)]));
        if (!seen('visited')) return { status: 'not run' };
        const granted = keys.filter((k) => got[k] && /^granted/.test(got[k].data));
        if (granted.length) return { status: 'FAIL', note: `granted: ${granted.join(', ')}` };
        const missing = keys.filter((k) => !got[k]);
        if (missing.length) return { status: 'pending', note: `no answer yet: ${missing.join(', ')}` };
        return { status: 'pass', note: keys.map((k) => `${k}=${got[k].data}`).join(' ') };
      }
      case 'schemes': {
        const tried = ['intent', 'file', 'content', 'javascript', 'data'];
        if (!seen('visited')) return { status: 'not run' };
        const stayed = tried.filter((s) => list.some((e) => e.what === 'stayed' && e.data === s));
        if (seen('done') && stayed.length === tried.length) return { status: 'pass' };
        if (seen('done')) return { status: 'FAIL', note: `left the page on: ${tried.filter((s) => !stayed.includes(s)).join(', ')}` };
        return { status: 'pending', note: `stayed after: ${stayed.join(', ') || 'none yet'}` };
      }
      case 'persist': {
        const set = last('persist', 'set');
        const check = last('persist', 'check-cookie');
        if (!set) return { status: 'not run' };
        if (!check || check.t < set.t) return { status: 'pending', note: 'now close the browser completely, reopen it, and open the check page' };
        const ls = last('persist', 'check-ls');
        const idb = last('persist', 'check-idb');
        const kept = [];
        if (/nb_persist=1/.test(check.data)) kept.push('cookie');
        if (ls && ls.data === 'found') kept.push('localStorage');
        if (idb && idb.data === 'found') kept.push('IndexedDB');
        return kept.length ? { status: 'FAIL', note: `survived: ${kept.join(', ')}` } : { status: 'pass' };
      }
      case 'size-declared':
      case 'size-stream': {
        const s = streams[test];
        if (!s) return { status: 'not run', note: 'tap the link and say Open' };
        if (!s.done) return { status: 'pending', note: `${Math.round(s.sent / MB)} MB sent so far` };
        const limit = test === 'size-declared' ? 64 * MB : CAP + 64 * MB;
        return s.sent <= limit ? { status: 'pass', note: `stopped after ${Math.round(s.sent / MB)} MB` } : { status: 'FAIL', note: `took ${Math.round(s.sent / MB)} MB` };
      }
      case 'redirects': {
        const hops = list.filter((e) => e.what === 'hop').map((e) => Number(e.data));
        if (!hops.length) return { status: 'not run', note: 'tap the link and say Open' };
        const max = Math.max(...hops);
        return max >= 30 ? { status: 'FAIL', note: 'followed all 30 hops' } : { status: 'pass', note: `gave up after ${max} hop(s)` };
      }
      case 'clickfix': {
        const r = last('clickfix', 'copied');
        if (!r) return { status: 'not run', note: 'tap the button' };
        return r.data === 'true' ? { status: 'FAIL', note: 'the page wrote to the clipboard' } : { status: 'pass', note: 'the copy was refused' };
      }
      default: {
        const files = list.filter((e) => e.what === 'fetch').map((e) => e.data);
        return { status: 'look', note: files.length ? `fetched: ${[...new Set(files)].join(', ')}` : '' };
      }
    }
  }

  function page(title, body, script = '') {
    return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title>
<style>body{font-family:system-ui,sans-serif;background:#0d1117;color:#fff;margin:0;padding:16px;line-height:1.45}a{color:#22d4ff}h1{color:#ffd040;font-size:1.25rem}
.t{border:1px solid #2e4060;border-radius:6px;padding:10px;margin:8px 0}.k{font-size:.8rem;color:#aab8cc}.pass{color:#00ffb0}.FAIL{color:#ff3d5a}.pending,.look,.not.run{color:#aab8cc}
.gap{color:#ffd040}button{font:inherit;padding:8px 14px;margin:4px 4px 4px 0;border-radius:6px;border:1px solid #2e4060;background:#161e2e;color:#fff}
#lock{position:fixed;inset:0;background:#0b5394;color:#fff;display:none;align-items:center;justify-content:center;text-align:center;font-size:1.3rem;z-index:9}</style></head>
<body>${body}<script>function b(w,d){var i=new Image();i.src='/ev?t='+encodeURIComponent(T)+'&w='+encodeURIComponent(w)+'&d='+encodeURIComponent(d==null?'':d)+'&r='+Math.random();}</script>${script}</body></html>`;
  }

  function testPage(id) {
    const t = TESTS.find((x) => x.id === id);
    const head = `<h1>${esc(t.title)}</h1><p class="k">Expected: ${esc(t.expect)}</p><p><a href="/">&larr; all tests</a> · <a href="/results">results</a></p>`;
    const set = (js) => `<script>var T=${JSON.stringify(id)};b('visited');${js}</script>`;
    switch (id) {
      case 'popups':
        return page(t.title, `${head}<p>This page tries to open 22 pop-ups by itself (on load, in a loop and on a timer). Wait 5 seconds, then check the results.</p>`,
          set(`try{window.open('/hit/popup?n=load')}catch(e){}for(var i=0;i<20;i++){try{window.open('/hit/popup?n='+i,'w'+i,'width=300,height=300')}catch(e){}}setTimeout(function(){try{window.open('/hit/popup?n=timer')}catch(e){}},1500);`));
      case 'permissions':
        return page(t.title, `${head}<p>This page asks for everything at once. Nothing should appear except perhaps a refusal.</p>`,
          set(`function r(k,p){Promise.resolve().then(p).then(function(v){b(k,'granted '+(v||''))},function(e){b(k,'denied '+(e&&e.name||''))})}
if(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia){r('camera',function(){return navigator.mediaDevices.getUserMedia({video:true}).then(function(){return'video'})});r('mic',function(){return navigator.mediaDevices.getUserMedia({audio:true}).then(function(){return'audio'})})}else{b('camera','denied unsupported');b('mic','denied unsupported')}
if(navigator.geolocation){var g=false;navigator.geolocation.getCurrentPosition(function(){g=true;b('geo','granted')},function(e){g=true;b('geo','denied '+e.code)},{timeout:4000});setTimeout(function(){if(!g)b('geo','denied timeout')},5000)}else b('geo','denied unsupported');
if(window.Notification){Promise.resolve(Notification.requestPermission()).then(function(p){b('notify',p==='granted'?'granted':'denied '+p)},function(){b('notify','denied error')})}else b('notify','denied unsupported');
if(navigator.clipboard&&navigator.clipboard.readText){navigator.clipboard.readText().then(function(){b('clipread','granted')},function(e){b('clipread','denied '+e.name)})}else b('clipread','denied unsupported');`));
      case 'schemes':
        return page(t.title, `${head}<p>This page tries to send you to five dangerous kinds of address, one per second. Stay on this page; check the results after 7 seconds.</p><p id="s">trying…</p>`,
          set(`var L=[['intent','intent://evil#Intent;scheme=http;end'],['file','file:///etc/passwd'],['content','content://settings/system'],['javascript','javascript:alert(1)'],['data','data:text/html,<h1>escaped</h1>']];var i=0;function n(){if(i>=L.length){b('done');document.getElementById('s').textContent='done';return}var x=L[i++];try{location.href=x[1]}catch(e){}setTimeout(function(){b('stayed',x[0]);n()},1000)}n();`));
      case 'persist':
        return page(t.title, `${head}<p>Step 1: <a href="/t/persist-set">set the data</a>. Step 2: close the browser completely (on Android, swipe it away from recent apps), reopen it, and open this address again. Step 3: <a href="/t/persist-check">check</a>.</p>`, '');
      case 'size-declared':
        return page(t.title, `${head}<p><a href="/dl/huge.mp4">huge.mp4</a> (says 600 MB). Tap it, and if asked, say Open.</p>`, set(''));
      case 'size-stream':
        return page(t.title, `${head}<p><a href="/dl/endless.mp4">endless.mp4</a> (never says its size; sends 600 MB). Tap it, and if asked, say Open. It can take a minute on Wi-Fi.</p>`, set(''));
      case 'redirects':
        return page(t.title, `${head}<p><a href="/dl/loop.pdf?n=1">loop.pdf</a> redirects 30 times before the real file. Tap it, and if asked, say Open.</p>`, set(''));
      case 'clickfix':
        return page(t.title, `${head}<div class="t"><b>Verify you are human</b><p>Tap the button, then (in a real attack) you would be told to paste into a terminal. Here the text is harmless: <code>echo attacklab-test-only</code>.</p><button id="go">I am not a robot</button></div>`,
          set(`document.getElementById('go').onclick=function(){var a=document.createElement('textarea');a.value='echo attacklab-test-only';document.body.appendChild(a);a.select();var ok=false;try{ok=document.execCommand('copy')}catch(e){}a.remove();b('copied',ok)};`));
      case 'disguised':
        return page(t.title, `${head}<p>Tap each; say Open when asked. Every one except the control should be refused.</p><ul>
<li><a href="/dl/real.pdf">real.pdf</a> (control: a genuine PDF; should open)</li>
<li><a href="/dl/invoice.pdf">invoice.pdf</a> (a Windows program's header, sent as PDF)</li>
<li><a href="/dl/song.mp3">song.mp3</a> (a Linux program's header, sent as audio)</li>
<li><a href="/dl/movie.mp4">movie.mp4</a> (a shell script, sent as video)</li>
<li><a href="/dl/page.pdf">page.pdf</a> (a web page with script, sent as PDF)</li>
<li><a href="/dl/eicar.pdf">eicar.pdf</a> (the EICAR antivirus test string, sent as PDF)</li>
<li><a href="/dl/setup.exe">setup.exe</a> (a program; should be refused outright as a download)</li></ul>`, set(''));
      case 'polyglot':
        return page(t.title, `${head}<p><a href="/dl/polyglot.pdf">polyglot.pdf</a> starts like a PDF and carries a script. Expected to pass the type check; note what your PDF viewer does with it.</p>`, set(''));
      case 'traversal':
        return page(t.title, `${head}<p><a href="/dl/trav">this file</a> asks to be saved as <code>../../../evil.pdf</code>. Say Open; the viewer should show a plain name.</p>`, set(''));
      case 'certificate':
        return page(t.title, `${head}${httpsPort ? '<p><a id="c" href="#">open the self-signed https page</a></p>' : '<p>No https port (openssl was not found when the server started).</p>'}`,
          set(httpsPort ? `document.getElementById('c').href='https://'+location.hostname+':${httpsPort}/t/cert-ok';` : ''));
      case 'fullscreen':
        return page(t.title, `${head}<div id="lock"><div>&#9888; Your device is locked.<br>Call 1-800-000-0000 to unlock.<br><small>(test only)</small></div></div><button id="go">Play video</button>`,
          set(`document.getElementById('go').onclick=function(){var l=document.getElementById('lock');l.style.display='flex';try{document.documentElement.requestFullscreen()}catch(e){}b('locked')};history.pushState({},'','#1');history.pushState({},'','#2');window.onpopstate=function(){history.pushState({},'','#3')};`));
      case 'alerts':
        return page(t.title, `${head}<button id="go">Start the alert loop</button>`,
          set(`document.getElementById('go').onclick=function(){b('started');for(var i=0;i<50;i++){alert('Your computer is infected ('+i+')')}b('ended')};`));
      case 'crash':
        return page(t.title, `${head}<button id="go">Start eating memory</button>`,
          set(`document.getElementById('go').onclick=function(){b('started');var a=[];setInterval(function(){for(var i=0;i<50;i++)a.push(new Array(1e6).fill(Math.random()))},10)};`));
      case 'leave-trap':
        return page(t.title, `${head}<p>Tap the box once, then try to leave: type another address, press back, or close the window.</p><button id="go" style="width:100%;height:160px">tap me once</button>`,
          set(`addEventListener('beforeunload',function(e){b('blocked');e.preventDefault();e.returnValue='Stay?';return'Stay?'});document.getElementById('go').onclick=function(){b('armed')};`));
      case 'print-loop':
        return page(t.title, `${head}<button id="go">Start the print loop</button>`,
          set(`document.getElementById('go').onclick=function(){b('started');var n=0;function p(){if(n++>=20)return b('ended');try{window.print()}catch(e){}setTimeout(p,300)}p()};`));
      case 'page-files':
        return page(t.title, `${head}<p>Each button makes a file inside the page, with no server involved, and asks for it to be saved.</p>
<p><button id="dexe">program from a data: address</button></p>
<p><button id="bexe">program from a blob: address</button></p>
<p><a id="aexe" href="/dl/setup.exe" download="setup.exe">program by an &lt;a download&gt; link</a></p>
<p><button id="bfake">fake PDF from a blob: address</button></p>
<p><button id="breal">real PDF from a blob: address (control)</button></p>`,
          set(`function save(u,n){var a=document.createElement('a');a.href=u;a.download=n;document.body.appendChild(a);a.click();a.remove()}
function blob(bytes,type){return URL.createObjectURL(new Blob([bytes],{type:type}))}
var MZ=new Uint8Array([0x4d,0x5a,0x90,0,3,0,0,0,4,0,0,0,0xff,0xff,0,0]);
document.getElementById('dexe').onclick=function(){b('try','dexe');save('data:application/x-msdownload;base64,TVqQAAMAAAAEAAAA//8AAA==','tool.exe')};
document.getElementById('bexe').onclick=function(){b('try','bexe');save(blob(MZ,'application/x-msdownload'),'tool.exe')};
document.getElementById('bfake').onclick=function(){b('try','bfake');save(blob(MZ,'application/pdf'),'invoice.pdf')};
document.getElementById('breal').onclick=function(){b('try','breal');save(blob(${JSON.stringify(REAL_PDF)},'application/pdf'),'real.pdf')};`));
      case 'cpu':
        return page(t.title, `${head}<p>Starts a 40-second busy loop 2 seconds after loading. Do not touch anything until it ends.</p>`,
          set(`setTimeout(function(){b('started');var t=Date.now()+40000;while(Date.now()<t){}b('ended')},2000);`));
      default:
        return page('?', head);
    }
  }

  function resultsPage() {
    const rows = TESTS.map((t) => {
      const v = verdict(t.id);
      const cls = v.status === 'known gap' ? 'gap' : v.status;
      const markButtons = t.kind === 'look' ? `<form method="post" action="/mark" style="display:inline"><input type="hidden" name="t" value="${t.id}"><button name="s" value="pass">pass</button><button name="s" value="FAIL">fail</button><button name="s" value="clear">clear</button></form>` : '';
      return `<div class="t"><b><a href="/t/${t.id}">${esc(t.title)}</a></b> <span class="${esc(cls)}">${esc(v.status)}</span> <span class="k">${esc(v.note || '')}</span><div class="k">${esc(t.expect)}</div>${markButtons}</div>`;
    }).join('');
    return page('attacklab results', `<h1>Results</h1><p><a href="/">&larr; all tests</a> · <a href="/results.json">json</a> · <a href="/reset">reset</a></p>${rows}`, '<script>var T="";</script>');
  }

  function indexPage() {
    const list = TESTS.map((t) => `<div class="t"><a href="/t/${t.id}">${esc(t.title)}</a> <span class="k">${t.kind === 'auto' ? 'judged by the server' : 'you judge'}</span><div class="k">${esc(t.expect)}</div></div>`).join('');
    return page('attacklab', `<h1>attacklab</h1><p class="k">Harmless stand-ins only: no real malware. Every attack here is a test of the browser's own defenses.</p><p><a href="/results">results</a> · <a href="/reset">reset</a></p>${list}`, '<script>var T="";</script>');
  }

  function streamFile(req, res, id, total, declared, head) {
    const s = { sent: 0, done: false };
    streams[id] = s;
    const headers = { 'Content-Type': 'video/mp4' };
    if (declared) headers['Content-Length'] = total;
    res.writeHead(200, headers);
    const chunk = Buffer.alloc(256 * 1024);
    head.copy(chunk);
    let first = true;
    const finish = () => {
      s.done = true;
    };
    res.on('close', finish);
    const zero = Buffer.alloc(chunk.length);
    const pump = () => {
      if (s.done) return;
      let burst = 0;
      while (s.sent < total && burst < 2 * MB) {
        const n = Math.min(chunk.length, total - s.sent);
        const buf = first ? chunk.subarray(0, n) : zero.subarray(0, n);
        first = false;
        s.sent += n;
        burst += n;
        if (!res.write(buf)) {
          res.once('drain', () => setTimeout(pump, 40));
          return;
        }
      }
      if (s.sent < total) setTimeout(pump, 40);
      else res.end();
    };
    pump();
  }

  const MP4_HEAD = Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from('ftypisom'), Buffer.alloc(12)]);
  const REAL_PDF = '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n';

  function download(req, res, url) {
    const name = url.pathname.slice(4);
    const test = name === 'trav' ? 'traversal' : name === 'polyglot.pdf' ? 'polyglot' : 'disguised';
    if (!['huge.mp4', 'endless.mp4', 'loop.pdf'].includes(name)) ev(test, 'fetch', name, req.headers['user-agent']);
    const send = (type, body, extra = {}) => {
      res.writeHead(200, { 'Content-Type': type, 'Content-Length': Buffer.byteLength(body), ...extra });
      res.end(body);
    };
    switch (name) {
      case 'real.pdf': return send('application/pdf', REAL_PDF);
      case 'invoice.pdf': return send('application/pdf', Buffer.concat([Buffer.from('MZ'), Buffer.alloc(126), Buffer.from('PE\0\0')]));
      case 'song.mp3': return send('audio/mpeg', Buffer.concat([Buffer.from([0x7f, 0x45, 0x4c, 0x46, 2, 1, 1]), Buffer.alloc(57)]));
      case 'movie.mp4': return send('video/mp4', '#!/bin/sh\necho attacklab-test-only\n');
      case 'page.pdf': return send('application/pdf', '<!doctype html><script>alert("attacklab")</script>');
      case 'eicar.pdf': return send('application/pdf', EICAR);
      case 'setup.exe': return send('application/octet-stream', Buffer.concat([Buffer.from('MZ'), Buffer.alloc(62)]), { 'Content-Disposition': 'attachment; filename="setup.exe"' });
      case 'polyglot.pdf': return send('application/pdf', `${REAL_PDF}<script>alert("attacklab polyglot")</script>\n`);
      case 'trav': return send('application/pdf', REAL_PDF, { 'Content-Disposition': 'attachment; filename="../../../evil.pdf"' });
      case 'huge.mp4': return streamFile(req, res, 'size-declared', 600 * MB, true, MP4_HEAD);
      case 'endless.mp4': return streamFile(req, res, 'size-stream', 600 * MB, false, MP4_HEAD);
      case 'loop.pdf': {
        const n = Number(url.searchParams.get('n') || '1');
        ev('redirects', 'hop', n, req.headers['user-agent']);
        if (n < 30) {
          res.writeHead(302, { Location: `/dl/loop.pdf?n=${n + 1}` });
          return res.end();
        }
        return send('application/pdf', REAL_PDF);
      }
      default:
        res.writeHead(404);
        return res.end();
    }
  }

  function handle(req, res) {
    const url = new URL(req.url, 'http://x');
    const p = url.pathname;
    const html = (s, extra = {}) => {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', ...extra });
      res.end(s);
    };
    if (p === '/') return html(indexPage());
    if (p === '/results') return html(resultsPage());
    if (p === '/results.json') {
      res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      return res.end(JSON.stringify(Object.fromEntries(TESTS.map((t) => [t.id, { kind: t.kind, ...verdict(t.id) }])), null, 2));
    }
    if (p === '/reset') {
      events.length = 0;
      for (const k of Object.keys(marks)) delete marks[k];
      for (const k of Object.keys(streams)) delete streams[k];
      res.writeHead(302, { Location: '/results' });
      return res.end();
    }
    if (p === '/ev') {
      ev(url.searchParams.get('t') || '', url.searchParams.get('w') || '', url.searchParams.get('d') || '', req.headers['user-agent']);
      res.writeHead(200, { 'Content-Type': 'image/gif', 'Cache-Control': 'no-store' });
      return res.end(Buffer.from('R0lGODlhAQABAAAAACw=', 'base64'));
    }
    if (p === '/mark' && req.method === 'POST') {
      let body = '';
      req.on('data', (d) => {
        body += d;
        if (body.length > 1000) req.destroy();
      });
      return req.on('end', () => {
        const q = new URLSearchParams(body);
        const t = q.get('t');
        const s = q.get('s');
        if (TESTS.some((x) => x.id === t && x.kind === 'look')) {
          if (s === 'clear') delete marks[t];
          else if (s === 'pass' || s === 'FAIL') marks[t] = { status: s, note: 'marked by hand' };
        }
        res.writeHead(303, { Location: '/results' });
        res.end();
      });
    }
    if (p.startsWith('/hit/')) {
      ev('popups', 'hit', url.search, req.headers['user-agent']);
      return html('<!doctype html><title>pop-up</title><p>attacklab pop-up page (this should never load)</p>');
    }
    if (p === '/t/persist-set') {
      ev('persist', 'set', '', req.headers['user-agent']);
      return html(page('persist: set', '<h1>Data set</h1><p>A cookie, localStorage and an IndexedDB record are now stored. Close the browser completely, reopen it, then open <a href="/t/persist-check">the check page</a>.</p>',
        `<script>var T='persist';try{localStorage.setItem('nb_persist','1')}catch(e){}try{var r=indexedDB.open('attacklab',1);r.onupgradeneeded=function(){r.result.createObjectStore('s')};r.onsuccess=function(){var tx=r.result.transaction('s','readwrite');tx.objectStore('s').put('1','k')}}catch(e){}</script>`),
        { 'Set-Cookie': 'nb_persist=1; Path=/; Max-Age=86400' });
    }
    if (p === '/t/persist-check') {
      ev('persist', 'check-cookie', req.headers.cookie || '', req.headers['user-agent']);
      return html(page('persist: check', '<h1>Checked</h1><p>See the results page.</p>',
        `<script>var T='persist';var v=null;try{v=localStorage.getItem('nb_persist')}catch(e){}b('check-ls',v?'found':'gone');try{var r=indexedDB.open('attacklab',1);r.onupgradeneeded=function(){r.transaction.abort();b('check-idb','gone')};r.onsuccess=function(){var db=r.result;if(!db.objectStoreNames.contains('s')){b('check-idb','gone');return}var g=db.transaction('s').objectStore('s').get('k');g.onsuccess=function(){b('check-idb',g.result?'found':'gone')};g.onerror=function(){b('check-idb','gone')}};r.onerror=function(){b('check-idb','gone')}}catch(e){b('check-idb','gone')}</script>`));
    }
    if (p === '/t/cert-ok') return html(page('certificate', '<h1>You reached the self-signed page</h1><p>If this loaded without a warning you could not get past, that is a FAIL on Android.</p>'));
    if (slow.handle(req, res, url)) return undefined;
    if (p.startsWith('/t/')) {
      const id = p.slice(3);
      if (TESTS.some((t) => t.id === id)) return html(testPage(id));
    }
    if (p.startsWith('/dl/')) return download(req, res, url);
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    return res.end('not found');
  }

  return { handle, verdict, events, thirdParty };
}

function selfSigned(dir) {
  const key = path.join(dir, 'key.pem');
  const crt = path.join(dir, 'cert.pem');
  try {
    execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', crt, '-days', '2', '-subj', '/CN=attacklab'], { stdio: 'ignore' });
    return { key: fs.readFileSync(key), cert: fs.readFileSync(crt) };
  } catch {
    return null;
  }
}

function start(opts) {
  const tls = selfSigned(fs.mkdtempSync(path.join(os.tmpdir(), 'attacklab-')));
  const httpsPort = tls ? opts.port + 1 : 0;
  const lab = createLab({ thirdParty: opts.thirdParty, httpsPort, rate: opts.rate || 5, panel: opts.panel || 24 });
  const server = http.createServer(lab.handle);
  server.listen(opts.port, opts.host);
  let secure = null;
  if (tls) {
    secure = https.createServer(tls, lab.handle);
    secure.listen(httpsPort, opts.host);
  }
  return { lab, server, secure, httpsPort };
}

if (require.main === module) {
  const opts = args(process.argv.slice(2));
  const { httpsPort } = start(opts);
  const where = opts.host === '0.0.0.0' ? lanAddresses() : [opts.host];
  process.stdout.write(`attacklab: harmless stand-ins only, no real malware\n`);
  for (const a of where.length ? where : ['127.0.0.1']) process.stdout.write(`  open http://${a}:${opts.port}/ in the browser under test${httpsPort ? ` (self-signed https on ${httpsPort})` : ''}\n`);
  process.stdout.write('  results: /results   reset: /reset   Ctrl+C to stop\n');
}

module.exports = { createLab, start, TESTS, EICAR, CAP };
