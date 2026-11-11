#!/usr/bin/env python3
import http.client
import json
import os
import ssl
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servers as ts

PW = os.environ.get("ASL_TEST_ROOT_PASSWORD", "")

EXPECT = {
    "nodecontrol": {"xfo": "DENY", "referrer": "", "csp": True, "login_guard": "json",
                    "local_api": True, "after_login": ("/api/action", "json")},
    "nodecontrol_pi02w": {"xfo": "DENY", "referrer": "", "csp": True, "login_guard": "json",
                          "local_api": True, "after_login": ("/api/action", "json")},
    "sysmon": {"xfo": "", "referrer": "", "csp": False, "login_guard": "json",
               "after_login": ("/api/config", "json")},
    "sysmon_pi02w": {"xfo": "", "referrer": "", "csp": False, "login_guard": "json",
                     "after_login": ("/api/config", "json")},
    "nodetalker": {"xfo": "SAMEORIGIN", "referrer": "", "csp": False, "login_guard": "xhr",
                   "proxy_loopback": True, "after_login": ("/api/logout", "xhr")},
    "amp_nodetalker": {"xfo": "SAMEORIGIN", "referrer": "", "csp": False, "login_guard": "xhr",
                       "proxy_loopback": True, "after_login": ("/api/logout", "xhr")},
    "noderecorder": {"xfo": "SAMEORIGIN", "referrer": "", "csp": False, "login_guard": "xhr",
                     "proxy_loopback": True, "after_login": ("/api/logout", "xhr")},
    "pibrary": {"xfo": "DENY", "referrer": "no-referrer", "csp": True, "login_guard": None},
    "instmon": {"xfo": "DENY", "referrer": "no-referrer", "csp": True, "login_guard": "xhr",
                "after_login": ("/api/action", "xhr")},
    "wifimon": {"xfo": "DENY", "referrer": "no-referrer", "csp": True, "login_guard": "xhr",
                "after_login": ("/api/logout", "xhr"), "control_proxy": "/api/radio"},
    "44helper": {"xfo": "DENY", "referrer": "no-referrer", "csp": True, "login_guard": "xhr",
                 "after_login": ("/api/logout", "xhr"), "terminal_proxy": True},
    "termon": {"xfo": "DENY", "referrer": "same-origin", "csp": True, "login_guard": "xhr",
               "after_login": ("/api/term/ticket", "xhr")},
}

KNOWN_GAPS = {
    "login_guard": "the login route takes a request with no X-Requested-With header",
}


def raw(server, method, path, body=None, headers=None, timeout=10):
    if server.spec["scheme"] == "https":
        conn = http.client.HTTPSConnection("127.0.0.1", server.spec["port"], timeout=timeout,
                                           context=ssl._create_unverified_context())
    else:
        conn = http.client.HTTPConnection("127.0.0.1", server.spec["port"], timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=dict(headers or {}))
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    finally:
        conn.close()


def login(server):
    st, h, b = server.request("POST", "/api/login", body=json.dumps({"password": PW}),
                              headers={"Content-Type": "application/json"}, timeout=15)
    if st != 200:
        raise AssertionError(f"login to {server.key} failed: {st} {b[:120]!r}")
    return h.get("Set-Cookie", "").split(";")[0]


def make_case(key):
    want = EXPECT[key]

    class SecurityCase(unittest.TestCase):
        server = None

        @classmethod
        def setUpClass(cls):
            if os.geteuid() != 0:
                raise unittest.SkipTest("security tests run as root (the tools require root)")
            cls.server = ts.Server(key)
            cls.server.start()

        @classmethod
        def tearDownClass(cls):
            if cls.server:
                cls.server.stop()

        def test_page_headers(self):
            st, h, _ = raw(self.server, "GET", "/")
            self.assertEqual(st, 200)
            self.assertEqual(h.get("X-Content-Type-Options", ""), "nosniff")
            self.assertEqual(h.get("X-Frame-Options", ""), want["xfo"])
            self.assertEqual(h.get("Referrer-Policy", ""), want["referrer"])
            csp = h.get("Content-Security-Policy", "")
            self.assertEqual(bool(csp), want["csp"], csp)
            if csp:
                self.assertIn("default-src 'self'", csp)

        def test_login_refuses_a_forged_shape(self):
            guard = want["login_guard"]
            if guard is None:
                self.skipTest(f"known gap in {key}: {KNOWN_GAPS['login_guard']}")
            body = json.dumps({"password": "not-the-password"})
            if guard == "xhr":
                st, _, b = raw(self.server, "POST", "/api/login", body, {"Content-Type": "application/json"})
                self.assertEqual(st, 403, b[:160])
            else:
                st, _, b = raw(self.server, "POST", "/api/login", body,
                               {"Content-Type": "text/plain", "X-Requested-With": "XMLHttpRequest"})
                self.assertEqual(st, 415, b[:160])

        def test_proxy_header_from_loopback_counts_as_outside(self):
            if not want.get("proxy_loopback"):
                self.skipTest("this tool does not treat a loopback proxy as outside")
            st, _, b = raw(self.server, "GET", self.server.spec["health"], None,
                           {"X-Forwarded-For": "203.0.113.9"})
            self.assertEqual(st, 403, b[:160])

        def test_local_api_needs_the_key(self):
            if not want.get("local_api"):
                self.skipTest("no local API in this tool")
            hdr = {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}
            body = json.dumps({"action": "status"})
            st, _, _ = raw(self.server, "POST", "/api/local/action", body, hdr)
            self.assertEqual(st, 403)
            st, _, _ = raw(self.server, "POST", "/api/local/action", body,
                           dict(hdr, **{"X-ASL-DVS-Local-Key": "0" * 64}))
            self.assertEqual(st, 403)

        def _cookie(self):
            if not PW:
                self.skipTest("set ASL_TEST_ROOT_PASSWORD (the root account must have that password)")
            if key == "pibrary":
                self.skipTest("Pibrary uses its own password file, not the root password")
            return login(self.server)

        def test_post_after_login_refuses_a_forged_shape(self):
            if not want.get("after_login"):
                self.skipTest("no logged-in check for this tool")
            cookie = self._cookie()
            path, guard = want["after_login"]
            if guard == "xhr":
                hdr = {"Cookie": cookie, "Content-Type": "application/json"}
                want_status = 403
            else:
                hdr = {"Cookie": cookie, "Content-Type": "text/plain", "X-Requested-With": "XMLHttpRequest"}
                want_status = 415
            st, _, b = raw(self.server, "POST", path, json.dumps({"action": "noop"}), hdr)
            self.assertEqual(st, want_status, b[:160])

        def test_control_refuses_a_proxy_header(self):
            if not want.get("control_proxy"):
                self.skipTest("no control gate in this tool")
            cookie = self._cookie()
            st, _, b = raw(self.server, "POST", want["control_proxy"], json.dumps({}),
                           {"Cookie": cookie, "Content-Type": "application/json",
                            "X-Requested-With": "XMLHttpRequest", "X-Forwarded-For": "203.0.113.9"})
            self.assertEqual(st, 403, b[:160])
            self.assertIn(b"proxy", b)

        def test_terminal_refuses_a_proxy_header(self):
            if not want.get("terminal_proxy"):
                self.skipTest("no terminal in this tool")
            cookie = self._cookie()
            st, _, b = raw(self.server, "GET", "/api/term/status", None,
                           {"Cookie": cookie, "Cf-Connecting-Ip": "203.0.113.9"})
            self.assertEqual(st, 200, b[:160])
            self.assertFalse(json.loads(b)["client_ok"])

    SecurityCase.__name__ = f"Security_{key}"
    SecurityCase.__qualname__ = f"Security_{key}"
    return SecurityCase


for _key in ts.SERVERS:
    globals()[f"Security_{_key}"] = make_case(_key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
