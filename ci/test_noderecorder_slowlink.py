import glob
import gzip
import http.client
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nr_slow_")
os.environ["NODERECORDER_CONFIG_DIR"] = os.path.join(WORK, "conf")
os.environ["NODERECORDER_RPT_CONF"] = os.path.join(WORK, "rpt.conf")
os.makedirs(os.environ["NODERECORDER_CONFIG_DIR"], exist_ok=True)
with open(os.environ["NODERECORDER_RPT_CONF"], "w") as fh:
    fh.write("[general]\n")


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("nr_slow_under_test", newest("noderecorder_v[0-9]*.py"))
nr = importlib.util.module_from_spec(spec)
sys.modules["nr_slow_under_test"] = nr
spec.loader.exec_module(nr)

BIG = {"ok": True, "rows": [{"name": "row %d" % i, "value": i * 7} for i in range(80)]}
SMALL = {"ok": True, "n": 1}


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [mock.patch.object(nr, "_check_session", lambda token: True),
                       mock.patch.object(nr, "_cfg_get", lambda key: True if key == "allow_wan" else None),
                       mock.patch.object(nr, "build_status", lambda full=True: dict(BIG)),
                       mock.patch.object(nr, "storage_view", lambda: dict(SMALL))]
        for p in cls.patches:
            p.start()
        cls.srv = nr.Server(("127.0.0.1", 0), nr.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for p in cls.patches:
            p.stop()

    def get(self, path, headers=None, conn=None):
        c = conn
        if c is None:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
            self.addCleanup(c.close)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        return r, r.read(), c


class Compression(Served):
    def test_a_large_reply_is_gzipped_when_accepted(self):
        r, body, _ = self.get("/api/status", {"Accept-Encoding": "gzip, deflate"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", r.getheader("Vary"))
        self.assertEqual(json.loads(gzip.decompress(body)), BIG)
        self.assertLess(len(body), len(json.dumps(BIG)) / 2)

    def test_it_is_plain_without_the_header_or_with_q_zero(self):
        for hdr in ({}, {"Accept-Encoding": "gzip;q=0"}, {"Accept-Encoding": "identity"}, {"Accept-Encoding": "br"}):
            r, body, _ = self.get("/api/status", hdr)
            self.assertIsNone(r.getheader("Content-Encoding"), hdr)
            self.assertEqual(json.loads(body), BIG)

    def test_small_replies_are_not_compressed(self):
        r, body, _ = self.get("/api/storage", {"Accept-Encoding": "gzip"})
        self.assertIsNone(r.getheader("Content-Encoding"))
        self.assertEqual(json.loads(body), SMALL)

    def test_an_error_reply_is_never_compressed_or_tagged(self):
        with mock.patch.object(nr, "_check_session", lambda token: False):
            r, body, _ = self.get("/api/status", {"Accept-Encoding": "gzip"})
        self.assertEqual(r.status, 401)
        self.assertIsNone(r.getheader("ETag"))
        self.assertIn("message", json.loads(body))

    def test_the_connection_is_reused(self):
        r, _, c = self.get("/api/storage")
        r, _, c = self.get("/api/status", conn=c)
        self.assertEqual(r.status, 200)
        self.assertIsNotNone(c.sock)


class Revalidation(Served):
    def test_a_get_reply_carries_an_etag_and_answers_304(self):
        for path in ("/api/status", "/api/storage"):
            r, _, c = self.get(path)
            tag = r.getheader("ETag")
            self.assertTrue(tag, path)
            self.assertEqual(r.getheader("Cache-Control"), "no-store")
            r2, body2, _ = self.get(path, {"If-None-Match": tag}, conn=c)
            self.assertEqual((r2.status, body2), (304, b""), path)
            self.assertEqual(r2.getheader("ETag"), tag)
            r3, _, _ = self.get(path, {"If-None-Match": "*"}, conn=c)
            self.assertEqual(r3.status, 304)
            r4, _, _ = self.get(path, {"If-None-Match": '"other"'}, conn=c)
            self.assertEqual(r4.status, 200)

    def test_the_tag_is_the_same_with_and_without_gzip(self):
        a = self.get("/api/status", {"Accept-Encoding": "gzip"})[0].getheader("ETag")
        b = self.get("/api/status")[0].getheader("ETag")
        self.assertEqual(a, b)

    def test_a_changed_reply_gets_a_new_tag(self):
        tag = self.get("/api/storage")[0].getheader("ETag")
        with mock.patch.object(nr, "storage_view", lambda: {"ok": True, "n": 2}):
            r, body, _ = self.get("/api/storage", {"If-None-Match": tag})
        self.assertEqual(r.status, 200)
        self.assertNotEqual(r.getheader("ETag"), tag)
        self.assertEqual(json.loads(body)["n"], 2)

    def test_the_page_is_not_a_json_reply(self):
        r, _, _ = self.get("/")
        self.assertIsNone(r.getheader("ETag"))


class Page(Served):
    def page(self, headers):
        r, body, _ = self.get("/", dict(headers, **{"Accept-Encoding": "gzip"}))
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Content-Encoding"), "gzip")
        return gzip.decompress(body), len(body)

    def test_the_page_is_gzipped(self):
        full, packed = self.page({})
        self.assertEqual(full, nr.render_page())
        self.assertLess(packed, len(full) / 2)
        r, body, _ = self.get("/")
        self.assertIsNone(r.getheader("Content-Encoding"))
        self.assertEqual(body, nr.render_page())

    def test_the_cookie_or_save_data_gives_a_page_without_the_fonts(self):
        full, packed_full = self.page({})
        self.assertIn(b"@font-face", full)
        for hdr in ({"Cookie": "asl_slow=on"}, {"Cookie": "a=b; asl_slow=on; c=d"}, {"Save-Data": "on"}):
            page, packed = self.page(hdr)
            self.assertNotIn(b"@font-face", page, hdr)
            self.assertLess(packed, packed_full * 0.85, hdr)

    def test_off_auto_and_look_alike_cookies_keep_the_fonts(self):
        for cookie in ("asl_slow=off", "asl_slow=", "xasl_slow=on", "asl_slow=onn"):
            page, _ = self.page({"Cookie": cookie})
            self.assertIn(b"@font-face", page, cookie)

    def test_the_light_page_is_otherwise_the_same(self):
        self.assertEqual(re.sub(rb"@font-face\{[^}]*\}\n?", b"", nr.render_page()), nr.render_page(True))

    def test_the_session_cookie_is_still_read_beside_the_slow_cookie(self):
        h = nr.Handler.__new__(nr.Handler)
        h.headers = {"Cookie": "asl_slow=on; " + nr._SESSION_COOKIE_NAME + "=abc"}
        self.assertEqual(h._token(), "abc")


class PageScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = nr.render_page().decode()

    def test_the_slow_link_switch_is_on_the_page(self):
        for mode in ("auto", "on", "off"):
            self.assertIn(f'data-net-set="{mode}"', self.html)
        self.assertIn('id="net-note"', self.html)
        self.assertIn("asl_slow=", self.html)

    def test_the_polls_follow_the_rules(self):
        self.assertIn("}, NET.delay(ms));", self.html)
        self.assertIn("NET.gate('hl', 30000)", self.html)
        self.assertIn("NET.gate('conv', 2000)", self.html)
        self.assertIn("NET.sample(performance.now() - t0)", self.html)
        self.assertIn("api('/api/status', {tag: true})", self.html)
        self.assertIn("api('/api/whoami', {tag: true})", self.html)

    def test_the_health_beat_and_the_other_calls_are_not_changed(self):
        self.assertIn("setInterval(beat, 5000)", self.html)
        self.assertIn("pollEvery(pollStatus, 1500);", self.html)
        self.assertNotRegex(self.html, r"NET\.(gate|delay)\([^)]*beat")
        for name in ("/api/log", "/api/schedule", "/api/storage", "/api/recorder/status"):
            self.assertNotRegex(self.html, r"\{tag: true\}[^\n]*" + re.escape(name))

    def test_the_shared_cookie_is_the_one_the_other_tools_use(self):
        for pattern in ("nodecontrol_pi02w_v[0-9]*.py", "instmon_v[0-9]*.py", "nodetalker_v[0-9]*.py"):
            with open(newest(pattern)) as f:
                self.assertIn("asl_slow=", f.read(), pattern)


NODE_TEST = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const start = src.indexOf('const NET = {');
const end = src.indexOf("document.addEventListener('DOMContentLoaded', function () { NET.show(); });");
if (start < 0 || end < 0) { console.log('NOFIND'); process.exit(2); }
const jar = {};
const document = {
  visibilityState: 'visible',
  get cookie() { return Object.entries(jar).map(([k, v]) => k + '=' + v).join('; '); },
  set cookie(s) {
    const first = s.split(';')[0];
    const i = first.indexOf('=');
    const k = first.slice(0, i), v = first.slice(i + 1);
    if (/max-age=0/.test(s)) delete jar[k]; else jar[k] = v;
  },
  addEventListener() {},
  getElementById() { return {textContent: ''}; },
  querySelectorAll() { return []; },
};
const clock = {now: 1000000};
Date.now = () => clock.now;
const out = {};
const state = {busy: false};
const code = src.slice(start, end) + `
function pollBusy() { return state.busy; }

out.t = {
  fresh: [NET.forced, NET.mult],
  slow: (function () { NET.sample(2000); NET.sample(2000); NET.sample(2000); return NET.mult; })(),
  cap: (function () { for (let i = 0; i < 30; i++) NET.sample(60000); return NET.mult; })(),
  factor: NET.factor(),
  busy: (function () { state.busy = true; const f = NET.factor(); state.busy = false; return f; })(),
  delay: NET.delay(1500),
  recover: (function () { for (let i = 0; i < 40; i++) NET.sample(20); return NET.mult; })(),
  setOn: (function () { NET.set('on'); return [NET.forced, document.cookie, NET.mult]; })(),
  off: (function () { NET.set('off'); NET.sample(5000); return [NET.forced, document.cookie, NET.mult]; })(),
  auto: (function () { NET.set('auto'); return [NET.forced, document.cookie]; })(),
  other: (function () { document.cookie = 'asl_slow=on; path=/'; NET.sample(10); return [NET.forced, NET.mult]; })(),
  gateHidden: (function () { document.visibilityState = 'hidden'; const r = NET.gate('x', 3000); document.visibilityState = 'visible'; return r; })(),
  gate: (function () { NET.active = clock.now; NET.next = {}; const a = NET.gate('k', 3000); const b = NET.gate('k', 3000); clock.now += 3000 * 8; const c = NET.gate('k', 3000); return [a, b, c]; })(),
  idle: (function () { NET.active = clock.now - 130000; return NET.factor(); })(),
};
`;
new Function('document', 'out', 'clock', 'state', 'performance', code)(document, out, clock, state, {now: () => 0});
console.log(JSON.stringify(out.t));
"""


class Behaviour(unittest.TestCase):
    def test_the_shared_helper_in_node(self):
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", nr.render_page().decode(), re.S)
        work = tempfile.mkdtemp(prefix="nr_slow_js_")
        js, runner = os.path.join(work, "page.js"), os.path.join(work, "run.js")
        with open(js, "w") as f:
            f.write("\n;\n".join(scripts))
        with open(runner, "w") as f:
            f.write(NODE_TEST)
        r = subprocess.run(["node", runner, js], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(t["fresh"], ["", 1])
        self.assertGreater(t["slow"], 1)
        self.assertEqual(t["cap"], 8)
        self.assertEqual(t["factor"], 8)
        self.assertEqual(t["busy"], 1)
        self.assertEqual(t["delay"], 12000)
        self.assertEqual(t["recover"], 1)
        self.assertEqual(t["setOn"], ["on", "asl_slow=on", 6])
        self.assertEqual(t["off"], ["off", "asl_slow=off", 1])
        self.assertEqual(t["auto"], ["", ""])
        self.assertEqual(t["other"][0], "on")
        self.assertGreaterEqual(t["other"][1], 6)
        self.assertTrue(t["gateHidden"])
        self.assertEqual(t["gate"], [False, True, False])
        self.assertEqual(t["idle"], 2 * t["other"][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
