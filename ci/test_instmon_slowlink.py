import glob
import gzip
import http.client
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="instmon_slow_")
for key, sub in (("INSTMON_CONFIG_DIR", "config"), ("INSTMON_LIBRARY_DIR", "library"), ("INSTMON_SUITELOG", "run/suitelog.jsonl"),
                 ("INSTMON_SUITELOG_FLAG", "run/suitelog.on")):
    os.environ[key] = os.path.join(WORK, sub)
os.environ["INSTMON_RECORDER_STATUS_URL"] = "http://127.0.0.1:9/x"


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("instmon_slow_under_test", newest("instmon_v[0-9]*.py"))
im = importlib.util.module_from_spec(spec)
sys.modules["instmon_slow_under_test"] = im
spec.loader.exec_module(im)


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = mock.patch.object(im, "_check_session", lambda token: True)
        cls.patch.start()
        cls.srv = im.http.server.ThreadingHTTPServer(("127.0.0.1", 0), im.InstmonHandler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.patch.stop()

    def get(self, path, headers=None, conn=None):
        c = conn
        if c is None:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
            self.addCleanup(c.close)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        return r, body, c


class Compression(Served):
    def test_status_is_gzipped_when_the_browser_accepts_it(self):
        r, body, _ = self.get("/api/status", {"Accept-Encoding": "gzip, deflate"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", r.getheader("Vary"))
        data = json.loads(gzip.decompress(body))
        self.assertIn("components_html", data)
        self.assertLess(len(body), len(json.dumps(data)) / 3)

    def test_it_is_plain_without_the_header_or_with_q_zero(self):
        for hdr in ({}, {"Accept-Encoding": "gzip;q=0"}, {"Accept-Encoding": "identity"}, {"Accept-Encoding": "br"}):
            r, body, _ = self.get("/api/status", hdr)
            self.assertIsNone(r.getheader("Content-Encoding"), hdr)
            self.assertIn("components_html", json.loads(body))

    def test_small_replies_are_not_compressed(self):
        r, body, _ = self.get("/api/diskimg/job", {"Accept-Encoding": "gzip"})
        self.assertLess(len(body), im.GZIP_MIN_BYTES)
        self.assertIsNone(r.getheader("Content-Encoding"))

    def test_the_page_is_gzipped_and_much_smaller(self):
        r, body, _ = self.get("/", {"Accept-Encoding": "gzip"})
        self.assertEqual(r.getheader("Content-Encoding"), "gzip")
        page = gzip.decompress(body)
        self.assertIn(b"<html", page)
        self.assertLess(len(body), len(page) / 2.5)


class Revalidation(Served):
    def test_an_unchanged_reply_comes_back_as_304_without_a_body(self):
        r, body, c = self.get("/api/status", {"Accept-Encoding": "gzip"})
        tag = r.getheader("ETag")
        self.assertTrue(tag.startswith('W/"'))
        self.assertEqual(r.getheader("Cache-Control"), "private, no-cache")
        r2, body2, _ = self.get("/api/status", {"Accept-Encoding": "gzip", "If-None-Match": tag}, c)
        self.assertEqual(r2.status, 304)
        self.assertEqual(body2, b"")
        self.assertEqual(r2.getheader("ETag"), tag)

    def test_the_tag_is_the_same_whatever_the_encoding(self):
        a = self.get("/api/status", {"Accept-Encoding": "gzip"})[0].getheader("ETag")
        b = self.get("/api/status")[0].getheader("ETag")
        self.assertEqual(a, b)

    def test_a_changed_reply_or_a_wrong_tag_gets_the_full_reply(self):
        r, body, c = self.get("/api/status", {"If-None-Match": 'W/"nothing"'})
        self.assertEqual(r.status, 200)
        self.assertIn("components_html", json.loads(body))
        r3, _b3, _ = self.get("/api/status", {"If-None-Match": '"a", W/"b"'}, c)
        self.assertEqual(r3.status, 200)

    def test_star_and_strong_forms_match(self):
        tag = self.get("/api/status")[0].getheader("ETag")
        self.assertEqual(self.get("/api/status", {"If-None-Match": "*"})[0].status, 304)
        self.assertEqual(self.get("/api/status", {"If-None-Match": tag[2:]})[0].status, 304)
        self.assertEqual(self.get("/api/status", {"If-None-Match": '"x", ' + tag})[0].status, 304)

    def test_a_reply_that_must_not_be_stored_keeps_its_own_cache_header(self):
        r, _body, _ = self.get("/api/suitelog/status")
        self.assertEqual(r.getheader("Cache-Control"), "no-store")

    def test_a_missing_login_still_gets_401_not_304(self):
        with mock.patch.object(im, "_check_session", lambda token: False):
            tag = self.get("/api/status")[0].getheader("ETag")
            r, body, _ = self.get("/api/status", {"If-None-Match": tag or "*"})
        self.assertEqual(r.status, 401)


class KeepAlive(Served):
    def test_get_connections_stay_open_and_are_reused(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        self.addCleanup(c.close)
        r, _b, _ = self.get("/api/diskimg/job", conn=c)
        self.assertFalse(r.will_close)
        sock = c.sock
        r2, _b2, _ = self.get("/api/log?since=0", conn=c)
        self.assertEqual(r2.status, 200)
        self.assertIs(c.sock, sock)

    def test_post_replies_close_the_connection(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        self.addCleanup(c.close)
        c.request("POST", "/api/nope", body="{}", headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"})
        r = c.getresponse()
        r.read()
        self.assertTrue(r.will_close)

    def test_a_reply_without_a_length_closes_the_connection(self):
        h = im.InstmonHandler.__new__(im.InstmonHandler)
        h.wfile = io.BytesIO()
        h.request_version, h.command, h.path, h.requestline = "HTTP/1.1", "GET", "/x", "GET /x HTTP/1.1"
        h.client_address, h.close_connection = ("127.0.0.1", 1), False
        h.send_response(200)
        h.send_header("Content-Type", "text/plain")
        h.end_headers()
        self.assertIn(b"Connection: close", h.wfile.getvalue())
        self.assertTrue(h.close_connection)

    def test_a_reply_with_a_length_to_a_get_stays_open(self):
        h = im.InstmonHandler.__new__(im.InstmonHandler)
        h.wfile = io.BytesIO()
        h.request_version, h.command, h.path, h.requestline = "HTTP/1.1", "GET", "/x", "GET /x HTTP/1.1"
        h.client_address, h.close_connection = ("127.0.0.1", 1), False
        h.send_response(200)
        h.send_header("Content-Length", "0")
        h.end_headers()
        self.assertNotIn(b"Connection: close", h.wfile.getvalue())
        self.assertFalse(h.close_connection)


class LightPage(Served):
    def test_the_cookie_or_save_data_gives_a_page_without_the_fonts(self):
        full = self.get("/", {"Accept-Encoding": "gzip"})[1]
        for hdr in ({"Cookie": "instmon_slow=1"}, {"Cookie": "a=b; asl_slow=on"}, {"Save-Data": "on"}):
            r, body, _ = self.get("/", dict(hdr, **{"Accept-Encoding": "gzip"}))
            page = gzip.decompress(body)
            self.assertNotIn(b"@font-face", page)
            self.assertLess(len(body), len(full) * 0.8)
        self.assertIn(b"@font-face", gzip.decompress(full))

    def test_off_or_look_alike_shared_cookies_keep_the_fonts(self):
        for cookie in ("asl_slow=off", "asl_slow=", "xasl_slow=on"):
            r, body, _ = self.get("/", {"Cookie": cookie, "Accept-Encoding": "gzip"})
            self.assertIn(b"@font-face", gzip.decompress(body), cookie)

    def test_the_light_page_is_otherwise_the_same(self):
        a = im.render_page(False)
        b = im.render_page(True)
        self.assertEqual(re.sub(r"@font-face\{[^}]*\}\n?", "", a), b)


class PageScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = im._JS

    def test_every_poller_goes_through_the_shared_helper(self):
        for call in ("netPoll(pollLog, 2000)", "netPoll(refreshStatus, 5000, true)", "netPoll(pollDrives, 5000)",
                     "netPoll(pollDiskimgJob, 2000)", "netPoll(pollDiskimgBackups, 5000)", "netPoll(pollGateway, 15000)",
                     "netPoll(slPoll, 3000)"):
            self.assertIn(call, self.script)
        self.assertNotRegex(self.script, r"setInterval\(\(\) => \{ if \(!document\.hidden\) (pollLog|refreshStatus|pollDrives|pollDiskimgJob|pollDiskimgBackups|pollGateway|slPoll)\(")

    def test_the_helper_never_overlaps_requests_and_backs_off(self):
        self.assertIn("busy || Date.now() < next", self.script)
        self.assertIn("NET.sample(", self.script)
        self.assertIn("Math.ceil(NET.avg / 400)", self.script)

    def test_the_slow_link_control_is_on_the_page(self):
        self.assertIn('data-net-set="auto"', im._THEME_ROW)
        self.assertIn('data-net-set="on"', im._THEME_ROW)
        self.assertIn('data-net-set="off"', im._THEME_ROW)
        self.assertIn("instmon_slow=", self.script)
        self.assertIn("asl_slow=", self.script)
        self.assertIn("NET.read()", self.script)

    def test_unchanged_status_and_preview_are_not_redone(self):
        self.assertIn("tag === _statusTag", self.script)
        self.assertIn("lastPreview.key === previewKey", self.script)

    def test_hidden_cards_are_not_polled(self):
        self.assertIn("force !== true && !_elShown('diskimg-backups')", self.script)
        self.assertIn("_diskimgIdleSkip++ % 4", self.script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
