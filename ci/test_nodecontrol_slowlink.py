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
WORK = tempfile.mkdtemp(prefix="nc_slow_")
os.environ["NODECONTROL_CONFIG_DIR"] = os.path.join(WORK, "nc")
os.environ["NODETALKER_CONFIG_DIR"] = os.path.join(WORK, "nt")


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("ncp_slow_under_test", newest("nodecontrol_pi02w_v[0-9]*.py"))
ncp = importlib.util.module_from_spec(spec)
sys.modules["ncp_slow_under_test"] = ncp
spec.loader.exec_module(ncp)

KEYED = {"keyed": False, "linked_node": "1999", "link_known": True}
REC = {"ok": True, "recording": None, "override_log": [], "recordings": [], "bridges": [], "next_bridge": {}}


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [mock.patch.object(ncp, "_check_session", lambda token: True),
                       mock.patch.object(ncp, "action_get_keyed", lambda: dict(KEYED)),
                       mock.patch.object(ncp, "recording_view", lambda: dict(REC))]
        for p in cls.patches:
            p.start()
        cls.srv = ncp._QuietThreadingHTTPServer(("127.0.0.1", 0), ncp.Handler)
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
        for path in ("/api/ping", "/api/keyed", "/api/recording", "/api/keyed"):
            r, _, _ = self.get(path, conn=c)
            self.assertEqual(r.status, 200, path)
            self.assertIsNone(r.getheader("Connection"), path)
        self.assertIsNotNone(c.sock)

    def test_a_not_modified_reply_keeps_the_connection_too(self):
        c = self.conn()
        r, _, _ = self.get("/api/keyed", conn=c)
        tag = r.getheader("ETag")
        r, body, _ = self.get("/api/keyed", {"If-None-Match": tag}, conn=c)
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
        body = json.dumps({"password": "x"})
        c.request("POST", "/api/login", body=body, headers={"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.getheader("Connection"), "close")

    def test_a_busy_client_is_not_kept_open(self):
        h = ncp.Handler.__new__(ncp.Handler)
        h.client_address = ("10.0.0.5", 1)
        h.server = mock.Mock(_per_ip_lock=threading.Lock(), _per_ip_count={"10.0.0.5": ncp._MAX_CONCURRENT_CONNECTIONS_PER_IP // 2})
        self.assertTrue(h._keep_alive_ok())
        h.server._per_ip_count["10.0.0.5"] += 1
        self.assertFalse(h._keep_alive_ok())

    def test_the_end_headers_rule(self):
        for command, length, held, expect_close in (("GET", True, 1, False), ("GET", False, 1, True),
                                                    ("POST", True, 1, True), ("GET", True, 99, True)):
            h = ncp.Handler.__new__(ncp.Handler)
            h.wfile = io.BytesIO()
            h.request_version, h.command, h.path, h.requestline = "HTTP/1.1", command, "/x", command + " /x HTTP/1.1"
            h.client_address, h.close_connection = ("10.0.0.5", 1), False
            h.server = mock.Mock(_per_ip_lock=threading.Lock(), _per_ip_count={"10.0.0.5": held})
            h.send_response(200)
            if length:
                h.send_header("Content-Length", "0")
            h.end_headers()
            self.assertEqual(b"Connection: close" in h.wfile.getvalue(), expect_close, (command, length, held))
            self.assertEqual(h.close_connection, expect_close)


class Revalidation(Served):
    def test_keyed_and_recording_carry_an_etag_and_answer_304(self):
        for path in ("/api/keyed", "/api/recording"):
            r, body, _ = self.get(path)
            tag = r.getheader("ETag")
            self.assertTrue(tag, path)
            self.assertEqual(r.getheader("Cache-Control"), "no-store")
            self.assertEqual(r.status, 200)
            r2, body2, _ = self.get(path, {"If-None-Match": tag})
            self.assertEqual((r2.status, body2), (304, b""), path)
            self.assertEqual(r2.getheader("ETag"), tag)
            r3, _, _ = self.get(path, {"If-None-Match": '"other"'})
            self.assertEqual(r3.status, 200)

    def test_a_changed_reply_gets_a_new_tag(self):
        r, _, _ = self.get("/api/keyed")
        tag = r.getheader("ETag")
        with mock.patch.object(ncp, "action_get_keyed", lambda: dict(KEYED, keyed=True)):
            r2, body, _ = self.get("/api/keyed", {"If-None-Match": tag})
        self.assertEqual(r2.status, 200)
        self.assertNotEqual(r2.getheader("ETag"), tag)
        self.assertTrue(json.loads(body)["keyed"])

    def test_a_reply_without_a_login_is_never_304(self):
        with mock.patch.object(ncp, "_check_session", lambda token: False):
            r, _, _ = self.get("/api/keyed", {"If-None-Match": "*"})
        self.assertEqual(r.status, 401)


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
            self.assertLess(n, full_len * 0.8, hdr)

    def test_off_auto_and_look_alike_cookies_keep_the_fonts(self):
        for cookie in ("asl_slow=off", "asl_slow=", "xasl_slow=on", "asl_slow=onn"):
            page, _ = self.page({"Cookie": cookie})
            self.assertIn(b"@font-face", page, cookie)

    def test_the_light_page_is_otherwise_the_same(self):
        self.assertEqual(re.sub(rb"@font-face\{[^}]*\}\n?", b"", ncp._HTML_BYTES), ncp._HTML_LITE_BYTES)
        self.assertEqual(gzip.decompress(ncp._HTML_LITE_GZIP), ncp._HTML_LITE_BYTES)

    def test_the_plain_page_without_gzip(self):
        r, body, _ = self.get("/", {"Cookie": "asl_slow=on"})
        self.assertIsNone(r.getheader("Content-Encoding"))
        self.assertNotIn(b"@font-face", body)


class PageScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = ncp._HTML_BYTES.decode()

    def test_the_slow_link_switch_is_on_the_page(self):
        for mode in ("auto", "on", "off"):
            self.assertIn(f'data-net-set="{mode}"', self.html)
        self.assertIn('id="net-note"', self.html)

    def test_the_shared_cookie_is_the_one_instmon_writes(self):
        self.assertIn("asl_slow=", self.html)
        with open(newest("instmon_v[0-9]*.py")) as f:
            instmon = f.read()
        self.assertIn("asl_slow=", instmon)
        self.assertIn("asl_slow=on", instmon)

    def test_every_poll_follows_the_rules(self):
        self.assertIn("NET.gate('rec',3000)", self.html)
        self.assertIn("NET.delay(5000)", self.html)
        self.assertIn("Math.min(NET.mult,4)", self.html)
        self.assertIn("(_lastKeyed||busy)?1000", self.html)
        self.assertIn("if(!document.hidden)await refresh()", self.html)
        self.assertIn("if(document.hidden){_keyedTimer=setTimeout(pollKeyed,2000);return}", self.html)
        self.assertIn("visibilitychange", self.html)

    def test_a_304_reuses_the_last_reply_so_a_tab_change_still_repaints(self):
        self.assertIn("r.status===304&&_keyedData", self.html)
        self.assertIn("r.status===304&&_recData", self.html)

    def test_the_status_poll_is_the_probe(self):
        self.assertIn("NET.sample(performance.now()-t0)", self.html)


NODE_TEST = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const start = src.indexOf('const NET=');
const end = src.indexOf("document.addEventListener('DOMContentLoaded',function(){NET.show()});");
if (start < 0 || end < 0) { console.log('NOFIND'); process.exit(2); }
const jar = {};
const document = {
  hidden: false,
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
  recover: (function () { for (let i = 0; i < 40; i++) NET.sample(20); return NET.mult; })(),
  setOn: (function () { NET.set('on'); return [NET.forced, document.cookie, NET.mult]; })(),
  onSample: (function () { NET.sample(10); return NET.mult; })(),
  readFromCookie: (function () { NET.forced = ''; NET.read(); return NET.forced; })(),
  setOff: (function () { NET.set('off'); return [NET.forced, document.cookie, NET.mult]; })(),
  offSample: (function () { NET.sample(5000); return NET.mult; })(),
  setAuto: (function () { NET.set('auto'); return [NET.forced, document.cookie]; })(),
  other: (function () { document.cookie = 'asl_slow=on; path=/'; NET.sample(10); return [NET.forced, NET.mult]; })(),
  delayBusy: (function () { NET.mult = 4; return NET.delay(5000); })(),
  delayIdle: (function () { NET.active = clock.now - 130000; return NET.delay(5000); })(),
  gateHidden: (function () { document.hidden = true; const r = NET.gate('x', 3000); document.hidden = false; return r; })(),
  gate: (function () { NET.active = clock.now; NET.mult = 3; NET.next = {}; const a = NET.gate('k', 3000); const b = NET.gate('k', 3000); clock.now += 6001; const c = NET.gate('k', 3000); return [a, b, c]; })(),
};
`;
new Function('document', 'out', 'clock', 'performance', 'localStorage', code)(document, out, clock, {now: () => 0}, undefined);
console.log(JSON.stringify(out.t));
"""


class Behaviour(unittest.TestCase):
    def test_the_shared_helper_in_node(self):
        script = re.findall(r"<script>(.*?)</script>", ncp._HTML_BYTES.decode(), re.S)
        work = tempfile.mkdtemp(prefix="nc_slow_js_")
        js = os.path.join(work, "page.js")
        runner = os.path.join(work, "run.js")
        with open(js, "w") as f:
            f.write("\n;\n".join(script))
        with open(runner, "w") as f:
            f.write(NODE_TEST)
        r = subprocess.run(["node", runner, js], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(t["fresh"], ["", 1])
        self.assertGreater(t["slow"], 1)
        self.assertEqual(t["cap"], 8)
        self.assertEqual(t["recover"], 1)
        self.assertEqual(t["setOn"], ["on", "asl_slow=on", 6])
        self.assertGreaterEqual(t["onSample"], 6)
        self.assertEqual(t["readFromCookie"], "on")
        self.assertEqual(t["setOff"], ["off", "asl_slow=off", 1])
        self.assertEqual(t["offSample"], 1)
        self.assertEqual(t["setAuto"], ["", ""])
        self.assertEqual(t["other"][0], "on")
        self.assertGreaterEqual(t["other"][1], 6)
        self.assertEqual(t["delayBusy"], 20000)
        self.assertEqual(t["delayIdle"], 40000)
        self.assertTrue(t["gateHidden"])
        self.assertEqual(t["gate"], [False, True, False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
