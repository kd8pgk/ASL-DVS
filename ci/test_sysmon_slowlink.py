import glob
import gzip
import http.client
import importlib.util
import io
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
WORK = tempfile.mkdtemp(prefix="sm_slow_")
os.environ.setdefault("SYSMON_CONFIG_DIR", os.path.join(WORK, "sm"))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("sm_slow_under_test", newest("sysmon_pi02w_v[0-9]*.py"))
sm = importlib.util.module_from_spec(spec)
sys.modules["sm_slow_under_test"] = sm
spec.loader.exec_module(sm)

LIST = {"ok": True, "ports": [{"port": 1000 + i, "name": "p%d" % i} for i in range(60)]}


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [mock.patch.object(sm, "_check_session", lambda token: True),
                       mock.patch.dict(sm._GET_ROUTES, {"/api/ports": lambda h: h.send_json(dict(LIST)),
                                                        "/api/reg/http": lambda h: h.send_json({"ok": True, "n": 1})})]
        for p in cls.patches:
            p.start()
        cls.srv = sm._ThreadingHTTPServer(("127.0.0.1", 0), sm.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for p in cls.patches:
            p.stop()

    def conn(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        self.addCleanup(c.close)
        return c

    def get(self, path, headers=None, conn=None):
        c = conn or self.conn()
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        return r, r.read(), c


class KeepAlive(Served):
    def test_gets_with_a_length_reuse_the_connection(self):
        c = self.conn()
        for path in ("/api/ping", "/api/ports", "/api/reg/http", "/api/ports"):
            r, _, _ = self.get(path, conn=c)
            self.assertEqual(r.status, 200, path)
            self.assertIsNone(r.getheader("Connection"), path)
        self.assertIsNotNone(c.sock)

    def test_a_not_modified_reply_keeps_the_connection_too(self):
        c = self.conn()
        r, _, _ = self.get("/api/ports", conn=c)
        r, body, _ = self.get("/api/ports", {"If-None-Match": r.getheader("ETag")}, conn=c)
        self.assertEqual((r.status, body), (304, b""))
        self.assertIsNone(r.getheader("Connection"))
        r, _, _ = self.get("/api/ping", conn=c)
        self.assertEqual(r.status, 200)

    def test_replies_without_a_length_close_it(self):
        r, _, _ = self.get("/no-such-page")
        self.assertEqual(r.status, 404)
        self.assertEqual(r.getheader("Connection"), "close")

    def test_a_post_closes_it(self):
        c = self.conn()
        c.request("POST", "/api/login", body=json.dumps({"password": "x"}), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.getheader("Connection"), "close")

    def test_the_end_headers_rule(self):
        for command, length, held, expect_close in (("GET", True, 1, False), ("GET", False, 1, True),
                                                    ("POST", True, 1, True), ("GET", True, 99, True)):
            h = sm.Handler.__new__(sm.Handler)
            h.wfile = io.BytesIO()
            h.request_version, h.command, h.path, h.requestline = "HTTP/1.1", command, "/x", command + " /x HTTP/1.1"
            h.client_address, h.close_connection = ("10.0.0.5", 1), False
            h.server = mock.Mock(_per_ip_lock=threading.Lock(), _per_ip={"10.0.0.5": held})
            h.send_response(200)
            if length:
                h.send_header("Content-Length", "0")
            h.end_headers()
            self.assertEqual(b"Connection: close" in h.wfile.getvalue(), expect_close, (command, length, held))
            self.assertEqual(h.close_connection, expect_close)

    def test_the_half_cap_boundary(self):
        h = sm.Handler.__new__(sm.Handler)
        h.client_address = ("10.0.0.5", 1)
        h.server = mock.Mock(_per_ip_lock=threading.Lock(), _per_ip={"10.0.0.5": sm._MAX_CONNS_PER_IP // 2})
        self.assertTrue(h._keep_alive_ok())
        h.server._per_ip["10.0.0.5"] += 1
        self.assertFalse(h._keep_alive_ok())


class Revalidation(Served):
    def test_a_get_reply_carries_an_etag_and_answers_304(self):
        for path in ("/api/ports", "/api/reg/http"):
            r, body, c = self.get(path)
            tag = r.getheader("ETag")
            self.assertTrue(tag, path)
            self.assertEqual(r.getheader("Cache-Control"), "no-store")
            r2, body2, _ = self.get(path, {"If-None-Match": tag}, conn=c)
            self.assertEqual((r2.status, body2), (304, b""), path)
            self.assertEqual(r2.getheader("ETag"), tag)
            r3, _, _ = self.get(path, {"If-None-Match": '"other"'}, conn=c)
            self.assertEqual(r3.status, 200)

    def test_gzip_is_kept_and_the_tag_does_not_depend_on_it(self):
        r, body, _ = self.get("/api/ports", {"Accept-Encoding": "gzip"})
        self.assertEqual(r.getheader("Content-Encoding"), "gzip")
        self.assertEqual(json.loads(gzip.decompress(body)), LIST)
        plain = self.get("/api/ports")[0]
        self.assertEqual(r.getheader("ETag"), plain.getheader("ETag"))

    def test_a_changed_reply_gets_a_new_tag(self):
        tag = self.get("/api/reg/http")[0].getheader("ETag")
        with mock.patch.dict(sm._GET_ROUTES, {"/api/reg/http": lambda h: h.send_json({"ok": True, "n": 2})}):
            r, body, _ = self.get("/api/reg/http", {"If-None-Match": tag})
        self.assertEqual(r.status, 200)
        self.assertNotEqual(r.getheader("ETag"), tag)

    def test_an_error_or_post_reply_has_no_tag(self):
        with mock.patch.object(sm, "_check_session", lambda token: False):
            r, _, _ = self.get("/api/ports", {"If-None-Match": "*"})
        self.assertEqual(r.status, 401)
        self.assertIsNone(r.getheader("ETag"))
        c = self.conn()
        c.request("POST", "/api/login", body=json.dumps({"password": "x"}), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.assertIsNone(r.getheader("ETag"))


class LightPage(Served):
    def page(self, headers):
        r, body, _ = self.get("/", dict(headers, **{"Accept-Encoding": "gzip"}))
        self.assertEqual(r.status, 200)
        return gzip.decompress(body), len(body)

    def test_the_cookie_or_save_data_gives_a_page_without_the_fonts(self):
        full, full_len = self.page({})
        self.assertIn(b"@font-face", full)
        for hdr in ({"Cookie": "asl_slow=on"}, {"Cookie": "a=b; asl_slow=on; c=d"}, {"Save-Data": "on"}):
            page, n = self.page(hdr)
            self.assertNotIn(b"@font-face", page, hdr)
            self.assertLess(n, full_len * 0.85, hdr)

    def test_off_auto_and_look_alike_cookies_keep_the_fonts(self):
        for cookie in ("asl_slow=off", "asl_slow=", "xasl_slow=on", "asl_slow=onn"):
            page, _ = self.page({"Cookie": cookie})
            self.assertIn(b"@font-face", page, cookie)

    def test_the_light_page_is_otherwise_the_same(self):
        self.assertEqual(re.sub(rb"@font-face\{[^}]*\}\n?", b"", sm._HTML_BYTES), sm._HTML_LITE_BYTES)
        self.assertEqual(gzip.decompress(sm._HTML_LITE_GZIP), sm._HTML_LITE_BYTES)

    def test_the_plain_page_without_gzip(self):
        r, body, _ = self.get("/", {"Cookie": "asl_slow=on"})
        self.assertIsNone(r.getheader("Content-Encoding"))
        self.assertNotIn(b"@font-face", body)


class PageScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = sm._HTML_BYTES.decode()

    def test_the_slow_link_switch_is_on_the_page(self):
        for mode in ("auto", "on", "off"):
            self.assertIn(f'data-net-set="{mode}"', self.html)
        self.assertIn('id="net-note"', self.html)
        self.assertIn("asl_slow=", self.html)

    def test_every_timer_goes_through_the_gate(self):
        for call in ('NET.gate("status", 5000, 4)', 'NET.gate("svc", 30000)', 'NET.gate("ports", 15000)',
                     'NET.gate("reg", 15000)', 'NET.gate("phone", 5000)'):
            self.assertIn(call, self.html)
        self.assertIn("NET.sample(performance.now() - t0)", self.html)

    def test_a_running_sd_card_test_is_not_slowed(self):
        self.assertIn("setInterval(sdTestPoll, 1500)", self.html)

    def test_only_lists_that_rarely_change_are_revalidated(self):
        self.assertIn('path.indexOf("/api/services?") === 0', self.html)
        self.assertNotIn('path === "/api/status" ||', self.html)

    def test_the_shared_cookie_is_the_one_the_other_tools_use(self):
        for pattern in ("nodecontrol_pi02w_v[0-9]*.py", "instmon_v[0-9]*.py", "nodetalker_v[0-9]*.py"):
            with open(newest(pattern)) as f:
                self.assertIn("asl_slow=", f.read(), pattern)


NODE_TEST = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const start = src.indexOf('const NET = {');
const end = src.indexOf('document.addEventListener("DOMContentLoaded", function () { NET.show(); });');
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
const code = src.slice(start, end) + `
out.t = {
  fresh: [NET.forced, NET.mult],
  slow: (function () { NET.sample(2000); NET.sample(2000); NET.sample(2000); return NET.mult; })(),
  cap: (function () { for (let i = 0; i < 30; i++) NET.sample(60000); return NET.mult; })(),
  factor: NET.factor(),
  capped: NET.factor(4),
  recover: (function () { for (let i = 0; i < 40; i++) NET.sample(20); return NET.mult; })(),
  setOn: (function () { NET.set('on'); return [NET.forced, document.cookie, NET.mult]; })(),
  off: (function () { NET.set('off'); NET.sample(5000); return [NET.forced, document.cookie, NET.mult]; })(),
  auto: (function () { NET.set('auto'); return [NET.forced, document.cookie]; })(),
  other: (function () { document.cookie = 'asl_slow=on; path=/'; NET.sample(10); return [NET.forced, NET.mult]; })(),
  gateHidden: (function () { document.visibilityState = 'hidden'; const r = NET.gate('x', 3000); document.visibilityState = 'visible'; return r; })(),
  gate: (function () { NET.active = clock.now; NET.next = {}; const a = NET.gate('k', 3000); const b = NET.gate('k', 3000); clock.now += 3000 * 8; const c = NET.gate('k', 3000); return [a, b, c]; })(),
  gateCap: (function () { NET.active = clock.now; NET.next = {}; NET.mult = 8; NET.gate('c', 5000, 4); return NET.next.c - clock.now; })(),
  idle: (function () { NET.active = clock.now - 130000; NET.mult = 3; return NET.factor(); })(),
};
`;
new Function('document', 'out', 'clock', 'performance', code)(document, out, clock, {now: () => 0});
console.log(JSON.stringify(out.t));
"""


class Behaviour(unittest.TestCase):
    def test_the_shared_helper_in_node(self):
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", sm._HTML_BYTES.decode(), re.S)
        work = tempfile.mkdtemp(prefix="sm_slow_js_")
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
        self.assertEqual(t["capped"], 4)
        self.assertEqual(t["recover"], 1)
        self.assertEqual(t["setOn"], ["on", "asl_slow=on", 6])
        self.assertEqual(t["off"], ["off", "asl_slow=off", 1])
        self.assertEqual(t["auto"], ["", ""])
        self.assertEqual(t["other"][0], "on")
        self.assertGreaterEqual(t["other"][1], 6)
        self.assertTrue(t["gateHidden"])
        self.assertEqual(t["gate"], [False, True, False])
        self.assertEqual(t["gateCap"], 5000 * 3)
        self.assertEqual(t["idle"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
