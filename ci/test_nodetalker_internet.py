#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import http.client
import http.server
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nt_net_")
os.environ["NODETALKER_SUITELOG"] = os.path.join(WORK, "suitelog.jsonl")
os.environ["NODETALKER_SUITELOG_FLAG"] = os.path.join(WORK, "suitelog.on")
os.environ["NODETALKER_CONFIG_DIR"] = os.path.join(WORK, "nt")


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("nt_net_under_test", newest("nodetalker_v[0-9]*.py"))
nt = importlib.util.module_from_spec(spec)
sys.modules["nt_net_under_test"] = nt
spec.loader.exec_module(nt)


class FakeCloudflared(http.server.BaseHTTPRequestHandler):
    ready = 1
    quick = "calm-river-1234.trycloudflare.com"
    ok = True

    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.ok:
            return self.reply(200, {"hello": "not cloudflared"})
        if self.path == "/ready":
            return self.reply(200 if self.ready else 503, {"status": 200 if self.ready else 503, "readyConnections": self.ready})
        if self.path == "/quicktunnel":
            return self.reply(200, {"hostname": self.quick}) if self.quick is not None else self.reply(404, {})
        self.reply(404, {})


class Config(unittest.TestCase):
    def test_the_fixed_address_is_cleaned_and_checked(self):
        norm = nt._norm_public_host
        self.assertEqual(norm(""), "")
        self.assertEqual(norm(None), "")
        self.assertEqual(norm(" Node.Example.com "), "node.example.com")
        self.assertEqual(norm("https://node.example.com/"), "node.example.com")
        for bad in ("node", "http://node.example.com", "a b.example.com", "node.example.com:8993", "-x.example.com", "x.example.c", "node.example.com/path"):
            with self.assertRaises(ValueError, msg=bad):
                norm(bad)

    def test_defaults(self):
        self.assertFalse(nt.DEFAULT_CONFIG["allow_wan"])
        self.assertEqual(nt.DEFAULT_CONFIG["public_hostname"], "")


class Tunnel(unittest.TestCase):
    def setUp(self):
        FakeCloudflared.ready, FakeCloudflared.quick, FakeCloudflared.ok = 1, "calm-river-1234.trycloudflare.com", True
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeCloudflared)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        for p in (mock.patch.object(nt, "CF_METRICS_PORTS", (self.srv.server_address[1],)),
                  mock.patch.object(nt, "_svc_active", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        nt._tunnel_cache.update(t=-1e9, v=None)
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def test_a_running_quick_tunnel_gives_its_address(self):
        t = nt.tunnel_probe(force=True)
        self.assertEqual(t, {"running": True, "ready": True, "quick_host": "calm-river-1234.trycloudflare.com"})

    def test_a_named_tunnel_has_no_quick_address(self):
        FakeCloudflared.quick = None
        t = nt.tunnel_probe(force=True)
        self.assertTrue(t["ready"])
        self.assertEqual(t["quick_host"], "")

    def test_a_tunnel_with_no_connection_is_running_but_not_ready(self):
        FakeCloudflared.ready = 0
        t = nt.tunnel_probe(force=True)
        self.assertEqual((t["running"], t["ready"]), (True, False))

    def test_an_odd_address_is_not_trusted(self):
        for bad in ("evil.example.com", "a.trycloudflare.com.evil.com", "x y.trycloudflare.com", ""):
            FakeCloudflared.quick = bad
            self.assertEqual(nt.tunnel_probe(force=True)["quick_host"], "", bad)

    def test_something_else_on_the_port_is_ignored(self):
        FakeCloudflared.ok = False
        self.assertEqual(nt.tunnel_probe(force=True), {"running": False, "ready": False, "quick_host": ""})

    def test_the_service_counts_when_there_is_no_metrics_port(self):
        self.srv.shutdown()
        self.srv.server_close()
        with mock.patch.object(nt, "_svc_active", return_value=True):
            t = nt.tunnel_probe(force=True)
        self.assertEqual((t["running"], t["ready"]), (True, False))

    def test_the_answer_is_kept_for_a_few_seconds(self):
        a = nt.tunnel_probe(force=True)
        FakeCloudflared.ready = 0
        self.assertIs(nt.tunnel_probe(), a)


class Status(unittest.TestCase):
    def setUp(self):
        self.cfg = {"allow_wan": True, "public_listen": False, "public_hostname": ""}
        real = nt._cfg_get
        for p in (mock.patch.object(nt, "_cfg_get", side_effect=lambda k: self.cfg[k] if k in self.cfg else real(k)),
                  mock.patch.object(nt, "tunnel_probe", return_value={"running": True, "ready": True, "quick_host": ""})):
            p.start()
            self.addCleanup(p.stop)
        nt._net_events.clear()
        nt._net_proxy.update(seen=0.0, secure=0.0)

    def test_a_fixed_address_wins_over_a_quick_one(self):
        self.cfg["public_hostname"] = "node.example.com"
        with mock.patch.object(nt, "tunnel_probe", return_value={"running": True, "ready": True, "quick_host": "a-b.trycloudflare.com"}):
            d = nt.net_status()
        self.assertEqual((d["url"], d["url_kind"]), ("https://node.example.com", "domain"))

    def test_a_quick_address_is_marked_and_warned_about(self):
        with mock.patch.object(nt, "tunnel_probe", return_value={"running": True, "ready": True, "quick_host": "a-b.trycloudflare.com"}):
            d = nt.net_status()
        self.assertEqual((d["url"], d["url_kind"]), ("https://a-b.trycloudflare.com", "quick"))
        self.assertTrue(any("quick tunnel" in w for w in d["warnings"]))

    def test_no_address_yet(self):
        d = nt.net_status()
        self.assertEqual((d["url"], d["url_kind"]), ("", ""))

    def test_logins_are_counted_for_a_day(self):
        nt.net_note_login(True, "1.2.3.4")
        nt.net_note_login(False, "5.6.7.8")
        nt.net_note_login(False, "5.6.7.9")
        d = nt.net_status()
        self.assertEqual((d["logins_ok"], d["logins_failed"]), (1, 2))
        self.assertEqual(d["last_login"]["ip"], "1.2.3.4")
        self.assertEqual(d["last_failure"]["ip"], "5.6.7.9")
        nt._net_events.appendleft((1.0, True, "old"))
        self.assertEqual(nt.net_status()["logins_ok"], 1)

    def test_listening_without_a_login_is_warned_about_only_when_the_internet_is_open(self):
        self.cfg["public_listen"] = True
        self.assertTrue(any("without logging in" in w for w in nt.net_status()["warnings"]))
        self.cfg["allow_wan"] = False
        self.assertFalse(any("without logging in" in w for w in nt.net_status()["warnings"]))

    def test_a_missing_tunnel_is_warned_about(self):
        with mock.patch.object(nt, "tunnel_probe", return_value={"running": False, "ready": False, "quick_host": ""}):
            self.assertTrue(any("no tunnel" in w for w in nt.net_status()["warnings"]))

    def test_plain_http_through_the_proxy_is_warned_about(self):
        nt.net_note_proxy(False)
        self.assertTrue(any("without https" in w for w in nt.net_status()["warnings"]))
        nt.net_note_proxy(True)
        self.assertFalse(any("without https" in w for w in nt.net_status()["warnings"]))


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = {"allow_wan": True, "public_listen": False}
        real = nt._cfg_get
        cls.authed = False
        cls.patches = [mock.patch.object(nt, "_cfg_get", side_effect=lambda k: cls.cfg[k] if k in cls.cfg else real(k)),
                       mock.patch.object(nt, "_check_session", lambda token: cls.authed),
                       mock.patch.object(nt, "_verify_root_password", lambda pw: pw == "pw"),
                       mock.patch.object(nt, "tunnel_probe", return_value={"running": True, "ready": True, "quick_host": ""})]
        for p in cls.patches:
            p.start()
        cls.srv = nt.Server(("127.0.0.1", 0), nt.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for p in cls.patches:
            p.stop()

    def setUp(self):
        type(self).authed = False
        self.cfg.update(allow_wan=True, public_listen=False)
        nt._net_events.clear()
        nt._net_proxy.update(seen=0.0, secure=0.0)

    def call(self, method, path, body=None, ip="9.9.9.1", https=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        self.addCleanup(c.close)
        h = {"CF-Connecting-IP": ip, "X-Requested-With": "XMLHttpRequest"}
        if https:
            h["X-Forwarded-Proto"] = "https"
        raw = None
        if body is not None:
            raw = json.dumps(body)
            h["Content-Type"] = "application/json"
        c.request(method, path, body=raw, headers=h)
        r = c.getresponse()
        data = r.read()
        try:
            return r, json.loads(data)
        except ValueError:
            return r, data


class Internet(Served):
    def test_the_internet_page_needs_a_login(self):
        r, d = self.call("GET", "/api/internet")
        self.assertEqual(r.status, 401)

    def test_a_logged_in_user_gets_the_status(self):
        type(self).authed = True
        r, d = self.call("GET", "/api/internet")
        self.assertEqual(r.status, 200)
        self.assertTrue(d["ok"])
        self.assertTrue(d["tunnel"]["ready"])
        self.assertTrue(d["allow_wan"])

    def test_requests_through_the_proxy_are_refused_while_the_setting_is_off(self):
        self.cfg["allow_wan"] = False
        r, d = self.call("POST", "/api/login", {"password": "pw"})
        self.assertEqual(r.status, 403)
        self.assertIn("allow_wan", d["error"])
        self.assertEqual(nt._net_events, nt.deque(maxlen=200))

    def test_a_good_login_over_https_is_counted_and_the_cookie_is_secure(self):
        r, d = self.call("POST", "/api/login", {"password": "pw"}, ip="9.9.9.2")
        self.assertEqual(r.status, 200)
        cookie = r.getheader("Set-Cookie")
        self.assertIn("Secure", cookie)
        self.assertTrue(cookie.startswith("__Host-"))
        self.assertEqual([(e[1], e[2]) for e in nt._net_events], [(True, "9.9.9.2")])

    def test_a_wrong_password_is_counted_by_the_visitors_address(self):
        r, d = self.call("POST", "/api/login", {"password": "no"}, ip="9.9.9.3")
        self.assertEqual(r.status, 401)
        self.assertEqual([(e[1], e[2]) for e in nt._net_events], [(False, "9.9.9.3")])

    def test_a_login_over_plain_http_from_the_internet_is_refused_and_not_counted(self):
        r, d = self.call("POST", "/api/login", {"password": "pw"}, ip="9.9.9.4", https=False)
        self.assertEqual(r.status, 403)
        self.assertIn("https", d["error"])
        self.assertEqual(len(nt._net_events), 0)

    def test_repeated_failures_make_that_address_wait(self):
        codes = [self.call("POST", "/api/login", {"password": "no"}, ip="9.9.9.5")[0].status for _ in range(7)]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertIn(429, codes[5:])
        r, d = self.call("POST", "/api/login", {"password": "pw"}, ip="9.9.9.6")
        self.assertEqual(r.status, 200)

    def test_the_proxy_is_noted_with_and_without_https(self):
        self.call("GET", "/api/health", ip="9.9.9.7", https=False)
        self.assertGreater(nt._net_proxy["seen"], 0)
        self.assertEqual(nt._net_proxy["secure"], 0.0)
        self.call("GET", "/api/health", ip="9.9.9.7")
        self.assertGreater(nt._net_proxy["secure"], 0)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
