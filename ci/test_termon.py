#!/usr/bin/env python3
import glob
import http.client
import importlib.util
import json
import os
import re
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = sorted(glob.glob(os.path.join(ROOT, "termon_v*.py")),
              key=lambda f: [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]])[-1]
WORK = tempfile.mkdtemp(prefix="termon-test-")
os.environ["TERMON_CONFIG_DIR"] = os.path.join(WORK, "config")
os.environ["TERMON_LOCK"] = os.path.join(WORK, "termon.lock")
os.environ["TERMON_RPT_CONF"] = os.path.join(WORK, "rpt.conf")
os.makedirs(os.environ["TERMON_CONFIG_DIR"], exist_ok=True)

spec = importlib.util.spec_from_file_location("termon_under_test", FILE)
tm = importlib.util.module_from_spec(spec)
sys.modules["termon_under_test"] = tm
spec.loader.exec_module(tm)

GOOD_PW = "correct horse"


def fake_verify(account, password):
    return password == GOOD_PW


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = ""

    def request(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPSConnection("127.0.0.1", self.port, timeout=10,
                                           context=ssl._create_unverified_context())
        hdr = dict(headers or {})
        if self.cookie:
            hdr.setdefault("Cookie", self.cookie)
        if method == "POST":
            hdr.setdefault("X-Requested-With", "XMLHttpRequest")
            hdr.setdefault("Content-Type", "application/json")
        if host is not None:
            hdr["Host"] = host
        try:
            conn.request(method, path, body=json.dumps(body) if isinstance(body, (dict, list)) else body,
                         headers=hdr)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, dict(resp.getheaders()), data
        finally:
            conn.close()

    def json(self, method, path, body=None, **kw):
        st, h, data = self.request(method, path, body, **kw)
        try:
            return st, h, json.loads(data.decode("utf-8"))
        except ValueError:
            return st, h, {}

    def login(self, pw=GOOD_PW):
        st, h, j = self.json("POST", "/api/login", {"password": pw})
        if st == 200:
            self.cookie = h["Set-Cookie"].split(";")[0]
        return st, h, j


def raw_exchange(port, payload):
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    tls = ssl._create_unverified_context().wrap_socket(sock)
    try:
        tls.sendall(payload)
        out = b""
        while True:
            try:
                chunk = tls.recv(4096)
            except (OSError, ssl.SSLError):
                break
            if not chunk:
                break
            out += chunk
        return out
    finally:
        tls.close()


class TermonBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = mock.patch.object(tm, "_verify_account_password", fake_verify)
        cls.patch.start()
        tm._init_names(tm.load_config())
        tm.BACKEND = tm.Privileged()
        assert tm.ensure_tls_cert()
        cls.server = tm.LimitedServer(("127.0.0.1", 0), tm.Handler, ssl_ctx=tm.make_ssl_context())
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        tm._close_all_sessions()
        cls.server.shutdown()
        cls.server.server_close()
        cls.patch.stop()

    def setUp(self):
        with tm._auth_lock:
            tm._auth_state.clear()
            tm._global_fails.clear()
        with tm._sess_lock:
            tm._sessions.clear()
        tm._close_all_sessions()
        with tm._pty_lock:
            tm._ptys.clear()
        self.c = Client(self.port)


class HostAndMethodTests(TermonBase):
    def test_ip_host_is_allowed(self):
        st, _, _ = self.c.request("GET", "/api/health")
        self.assertEqual(st, 200)

    def test_rebinding_name_is_refused(self):
        for host in ("evil.example.com", "evil.example.com:7878", "127.0.0.1.evil.example.com", ""):
            st, _, _ = self.c.request("GET", "/api/health", host=host)
            self.assertEqual(st, 403, host)

    def test_duplicate_host_header_is_refused(self):
        out = raw_exchange(self.port, b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nHost: evil.example\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.0 403"), out[:60])

    def test_saved_name_is_allowed(self):
        self.c.login()
        st, _, j = self.c.json("POST", "/api/setup/hosts", {"hosts": "magicbox", "confirm": True})
        if os.geteuid() != 0:
            self.assertEqual(st, 403)
            return
        self.assertEqual(st, 200, j)
        try:
            st, _, _ = self.c.request("GET", "/api/health", host="magicbox:7878")
            self.assertEqual(st, 200)
        finally:
            tm._EXTRA_HOSTS = frozenset()

    def test_other_methods_get_405_with_headers(self):
        for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "FOO"):
            out = raw_exchange(self.port, f"{method} / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
            self.assertTrue(out.startswith(b"HTTP/1.0 405"), (method, out[:60]))
            head = out.split(b"\r\n\r\n", 1)[0].lower()
            self.assertIn(b"allow: get, post", head, method)
            self.assertIn(b"x-content-type-options: nosniff", head, method)
            self.assertIn(b"content-security-policy:", head, method)

    def test_other_method_with_bad_host_is_refused(self):
        out = raw_exchange(self.port, b"PUT / HTTP/1.1\r\nHost: evil.example\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.0 403"), out[:60])

    def test_transfer_encoding_is_refused(self):
        body = b"0\r\n\r\n"
        out = raw_exchange(self.port, b"POST /api/login HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Requested-With: XMLHttpRequest\r\n"
                           b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n" + body)
        self.assertTrue(out.startswith(b"HTTP/1.0 501"), out[:60])

    def test_duplicate_content_length_is_refused(self):
        out = raw_exchange(self.port, b"POST /api/login HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Requested-With: XMLHttpRequest\r\n"
                           b"Content-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}")
        self.assertTrue(out.startswith(b"HTTP/1.0 400"), out[:60])

    def test_content_length_must_be_plain_digits(self):
        for value in ("1_0", " 2", "+2", "-1", "0x2"):
            out = raw_exchange(self.port, (f"POST /api/login HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Requested-With: XMLHttpRequest\r\n"
                                           f"Content-Type: application/json\r\nContent-Length:{value}\r\n\r\n{{}}").encode())
            self.assertTrue(out.startswith(b"HTTP/1.0 400"), (value, out[:60]))

    def test_errors_use_the_message_key(self):
        st, _, j = self.c.json("POST", "/api/login", {"password": "wrong"})
        self.assertEqual(st, 401)
        self.assertIn("message", j)
        self.assertNotIn("error", j)

    def test_post_needs_x_requested_with(self):
        st, _, j = self.c.json("POST", "/api/login", {"password": GOOD_PW}, headers={"X-Requested-With": ""})
        self.assertEqual(st, 403, j)

    def test_cross_site_post_is_refused(self):
        st, _, _ = self.c.json("POST", "/api/login", {"password": GOOD_PW}, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(st, 403)
        st, _, _ = self.c.json("POST", "/api/login", {"password": GOOD_PW}, headers={"Origin": "https://evil.example"})
        self.assertEqual(st, 403)

    def test_proxy_header_is_refused(self):
        st, _, _ = self.c.request("GET", "/api/health", headers={"X-Forwarded-For": "203.0.113.9"})
        self.assertEqual(st, 403)


class HeaderTests(TermonBase):
    def test_page_csp_uses_a_nonce_and_no_unsafe_inline_script(self):
        st, h, body = self.c.request("GET", "/")
        self.assertEqual(st, 200)
        csp = h["Content-Security-Policy"]
        script_src = re.search(r"script-src ([^;]*)", csp).group(1)
        self.assertNotIn("unsafe-inline", script_src)
        nonce = re.search(r"'nonce-([^']+)'", script_src).group(1)
        html = body.decode("utf-8")
        self.assertIn(f'<script nonce="{nonce}">', html)
        self.assertEqual(html.count("<script"), 3)
        self.assertEqual(len(re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*nonce=)", html)), 0)
        self.assertNotIn("__NONCE__", html)
        self.assertNotRegex(html, r"\son(click|load|error)=")
        self.assertIn("object-src 'none'", csp)

    def test_nonce_changes_each_time(self):
        a = self.c.request("GET", "/")[1]["Content-Security-Policy"]
        b = self.c.request("GET", "/")[1]["Content-Security-Policy"]
        self.assertNotEqual(a, b)

    def test_every_reply_has_the_security_headers(self):
        for path in ("/", "/api/health", "/api/nothing", "/static/xterm.js"):
            st, h, _ = self.c.request("GET", path)
            for name in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Content-Security-Policy",
                         "Cross-Origin-Resource-Policy"):
                self.assertIn(name, h, (path, st, name))
            self.assertEqual(h["X-Frame-Options"], "DENY")
            self.assertEqual(h["Referrer-Policy"], "same-origin")

    def test_session_cookie_is_host_prefixed_and_secure(self):
        st, h, _ = self.c.login()
        self.assertEqual(st, 200)
        cookie = h["Set-Cookie"]
        self.assertTrue(cookie.startswith("__Host-termon_session="), cookie)
        for part in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(part, cookie)
        self.assertNotIn("Max-Age", cookie)
        self.assertNotIn("Expires", cookie)

    def test_plain_http_to_the_tls_port_gets_nothing(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        with self.assertRaises((http.client.HTTPException, OSError)):
            conn.request("GET", "/api/health")
            conn.getresponse().read()
        conn.close()


class LoginTests(TermonBase):
    def test_password_with_a_nul_is_refused(self):
        st, _, _ = self.c.json("POST", "/api/login", {"password": GOOD_PW + "\0junk"})
        self.assertEqual(st, 400)

    def test_lockout_after_five_failures(self):
        codes = [self.c.json("POST", "/api/login", {"password": "no"})[0] for _ in range(6)]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5], 429)
        self.assertEqual(self.c.login()[0], 429)

    def test_ipv6_source_rotation_shares_one_lockout(self):
        key = tm._lock_key("2001:db8:1:2::1")
        for host in ("2001:db8:1:2::2", "2001:db8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::1%eth0"):
            self.assertEqual(tm._lock_key(host), key)
        self.assertNotEqual(tm._lock_key("2001:db8:1:3::1"), key)
        for i in range(tm.AUTH_MAX_FAILURES):
            tm._record_fail(f"2001:db8:1:2::{i + 1:x}")
        self.assertGreater(tm._lock_remaining("2001:db8:1:2:dead:beef:0:1"), 0)
        self.assertEqual(tm._lock_remaining("2001:db8:1:3::1"), 0)

    def test_mapped_ipv4_uses_the_ipv4_key(self):
        self.assertEqual(tm._lock_key("::ffff:192.168.1.5"), tm._lock_key("192.168.1.5"))

    def test_lockout_time_grows_and_is_capped(self):
        ip = "192.168.1.9"
        for _ in range(tm.AUTH_MAX_FAILURES + 12):
            tm._record_fail(ip)
        self.assertLessEqual(tm._lock_remaining(ip), tm.AUTH_LOCKOUT_MAX_SEC)
        self.assertGreater(tm.AUTH_LOCKOUT_MAX_SEC, 300)
        self.assertGreater(tm._lock_remaining(ip), 300)

    def test_global_delay_starts_after_many_failures_from_many_sources(self):
        self.assertEqual(tm._global_delay(), 0.0)
        for i in range(tm.GLOBAL_FAIL_LIMIT):
            tm._record_fail(f"10.0.{i}.1")
        self.assertEqual(tm._global_delay(), tm.GLOBAL_FAIL_DELAY_SEC)
        self.assertEqual(tm._lock_remaining("10.0.200.1"), 0)

    def test_tracking_table_is_capped(self):
        with mock.patch.object(tm, "AUTH_TRACK_MAX", 50):
            for i in range(200):
                tm._record_fail(f"10.1.{i // 250}.{i % 250}")
            self.assertLessEqual(len(tm._auth_state), 50)

    def test_session_ends_with_logout(self):
        self.assertEqual(self.c.login()[0], 200)
        self.assertTrue(self.c.json("GET", "/api/whoami")[2]["logged_in"])
        self.c.json("POST", "/api/logout", {})
        self.assertFalse(self.c.json("GET", "/api/whoami")[2]["logged_in"])


class TerminalTests(TermonBase):
    def open_shell(self, c):
        st, _, t = c.json("POST", "/api/term/ticket", {})
        self.assertEqual(st, 200, t)
        st, _, o = c.json("POST", "/api/term/open", {"ticket": t["ticket"], "kind": "shell", "rows": 24, "cols": 80})
        self.assertEqual(st, 200, o)
        return o["sid"]

    def read_until(self, sid, needle, timeout=15):
        sess = tm._ptys[sid]
        deadline = time.time() + timeout
        seen = b""
        while time.time() < deadline:
            with sess.cond:
                seen = b"".join(d for _, d in sess.ring)
                if needle in seen:
                    return seen
                sess.cond.wait(0.3)
        self.fail(f"{needle!r} not seen in {seen[-300:]!r}")

    def test_shell_has_a_controlling_tty_and_its_own_session(self):
        self.c.login()
        sid = self.open_shell(self.c)
        sess = tm._ptys[sid]
        st, _, _ = self.c.json("POST", "/api/term/input", {"sid": sid, "data": "echo T=$(ps -o tty= -p $$ | tr -d ' ') S=$(ps -o sid= -p $$ | tr -d ' ') ; echo DO''NE\n"})
        self.assertEqual(st, 200)
        out = self.read_until(sid, b"\r\nDONE").decode("utf-8", "replace")
        self.assertRegex(out, r"T=pts/\d+")
        self.assertIn(f"S={sess.pid}", out)
        self.assertEqual(os.getsid(sess.pid), sess.pid)

    def test_child_does_not_inherit_the_listening_socket(self):
        self.c.login()
        sid = self.open_shell(self.c)
        sess = tm._ptys[sid]
        deadline = time.time() + 10
        while time.time() < deadline and not os.path.isdir(f"/proc/{sess.pid}/fd"):
            time.sleep(0.1)
        time.sleep(1)
        sockets = [f for f in os.listdir(f"/proc/{sess.pid}/fd")
                   if os.readlink(f"/proc/{sess.pid}/fd/{f}").startswith("socket:")]
        self.assertEqual(sockets, [])

    def test_service_variables_are_not_passed_to_the_shell(self):
        with mock.patch.dict(os.environ, {"NOTIFY_SOCKET": "/run/x", "INVOCATION_ID": "abc", "LISTEN_FDS": "3"}):
            self.c.login()
            sid = self.open_shell(self.c)
        self.c.json("POST", "/api/term/input", {"sid": sid, "data": "env | grep -c -E 'NOTIFY_SOCKET|INVOCATION_ID|LISTEN_' ; echo EN''D\n"})
        out = self.read_until(sid, b"\r\nEND").decode("utf-8", "replace")
        self.assertRegex(re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", out), r"\r0\r\nEND")

    def test_opening_again_replaces_only_that_logins_terminal(self):
        a, b = Client(self.port), Client(self.port)
        a.login()
        b.login()
        sid_a = self.open_shell(a)
        sid_b = self.open_shell(b)
        self.assertTrue(tm._ptys[sid_a].alive)
        self.assertTrue(tm._ptys[sid_b].alive)
        sid_a2 = self.open_shell(a)
        self.assertNotIn(sid_a, tm._ptys)
        self.assertTrue(tm._ptys[sid_b].alive)
        self.assertTrue(tm._ptys[sid_a2].alive)

    def test_other_login_cannot_reach_a_terminal(self):
        a, b = Client(self.port), Client(self.port)
        a.login()
        b.login()
        sid_a = self.open_shell(a)
        st, _, _ = b.json("POST", "/api/term/input", {"sid": sid_a, "data": "x"})
        self.assertEqual(st, 404)
        st, _, _ = b.json("POST", "/api/term/close", {"sid": sid_a})
        self.assertEqual(st, 404)
        self.assertTrue(tm._ptys[sid_a].alive)

    def test_terminal_count_is_capped(self):
        clients = [Client(self.port) for _ in range(tm.MAX_SESSIONS + 1)]
        for c in clients:
            c.login()
        for c in clients[:tm.MAX_SESSIONS]:
            self.open_shell(c)
        st, _, t = clients[-1].json("POST", "/api/term/ticket", {})
        st, _, o = clients[-1].json("POST", "/api/term/open", {"ticket": t["ticket"], "kind": "shell"})
        self.assertEqual(st, 409, o)
        self.assertIn("message", o)

    def test_logout_closes_the_terminal(self):
        self.c.login()
        sid = self.open_shell(self.c)
        sess = tm._ptys.get(sid)
        self.c.json("POST", "/api/logout", {})
        deadline = time.time() + 10
        while time.time() < deadline and sess.alive:
            time.sleep(0.2)
        self.assertFalse(sess.alive)

    def test_ticket_is_single_use(self):
        self.c.login()
        st, _, t = self.c.json("POST", "/api/term/ticket", {})
        body = {"ticket": t["ticket"], "kind": "shell"}
        self.assertEqual(self.c.json("POST", "/api/term/open", body)[0], 200)
        self.assertEqual(self.c.json("POST", "/api/term/open", body)[0], 403)

    def test_opening_and_closing_is_written_to_the_audit_log(self):
        with mock.patch.object(tm, "audit") as audit:
            self.c.login()
            sid = self.open_shell(self.c)
            sess = tm._ptys[sid]
            self.c.json("POST", "/api/term/close", {"sid": sid})
            deadline = time.time() + 10
            while time.time() < deadline and sess.alive:
                time.sleep(0.2)
            time.sleep(0.5)
        lines = [c.args[0] for c in audit.call_args_list]
        self.assertTrue(any("signed in from 127.0.0.1" in x for x in lines), lines)
        self.assertTrue(any("opened from 127.0.0.1" in x for x in lines), lines)
        self.assertTrue(any("closed after" in x for x in lines), lines)


class InstallCodeTests(unittest.TestCase):
    def test_apt_runs_without_a_shell(self):
        calls = []

        class FakeProc:
            stdout = iter(["ok\n"])

            def wait(self):
                return 0

        def fake_popen(cmd, **kw):
            calls.append(cmd)
            return FakeProc()

        with mock.patch.object(tm.subprocess, "Popen", fake_popen), mock.patch.object(tm.shutil, "which", return_value="/usr/bin/htop"):
            with tm._job_lock:
                tm._job.update(id=99, pkg="htop", state="running", output="", code=None)
            tm._run_install(99, "htop")
        self.assertEqual(len(calls), 2)
        for cmd in calls:
            self.assertIsInstance(cmd, list)
            self.assertNotIn("sh", cmd)
            self.assertNotIn("-c", cmd)
        self.assertEqual(calls[1][-1], "htop")
        self.assertEqual(tm._job_view()["state"], "ok")

    def test_failed_update_stops_the_install(self):
        calls = []

        class FakeProc:
            stdout = iter([])

            def wait(self):
                return 100

        with mock.patch.object(tm.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd) or FakeProc()):
            with tm._job_lock:
                tm._job.update(id=100, pkg="btop", state="running", output="", code=None)
            tm._run_install(100, "btop")
        self.assertEqual(len(calls), 1)
        self.assertEqual(tm._job_view()["state"], "failed")

    def test_unit_name_pattern_is_anchored(self):
        for name in ("termon.service", "termon-test.service", "termon-port-restart.service"):
            self.assertTrue(tm._UNIT_NAME_RE.match(name), name)
        for name in ("termonitor.service", "termon.service.d", "termon", "xtermon.service", "termon.timer",
                     "termon/../x.service", "termon-.service\n"):
            self.assertFalse(tm._UNIT_NAME_RE.match(name), name)

    def test_remove_existing_leaves_other_units_alone(self):
        folder = tempfile.mkdtemp(prefix="units-", dir=WORK)
        mine = os.path.join(folder, "termon.service")
        other = os.path.join(folder, "termonitor.service")
        foreign = os.path.join(folder, "termon-helper.service")
        with open(mine, "w") as f:
            f.write("[Service]\nExecStart=/usr/bin/python3 /usr/local/bin/termon.py\n")
        with open(other, "w") as f:
            f.write("[Service]\nExecStart=/usr/bin/other\n")
        with open(foreign, "w") as f:
            f.write("[Service]\nExecStart=/usr/bin/somethingelse\n")

        class R:
            stdout = "termon.service enabled\ntermonitor.service enabled\n"

        calls = []
        with mock.patch.object(tm, "_UNIT_DIRS", (folder,)), \
                mock.patch.object(tm, "_systemctl", lambda *a: calls.append(a) or R()), \
                mock.patch.object(tm, "_kill_other_termons", lambda: 0), \
                mock.patch.object(tm, "INSTALL_BIN_PATH", os.path.join(folder, "bin")), \
                mock.patch.object(tm, "INSTALL_DIR", os.path.join(folder, "lib")):
            tm._remove_existing()
        self.assertFalse(os.path.exists(mine))
        self.assertTrue(os.path.exists(other))
        self.assertTrue(os.path.exists(foreign))
        disabled = [a[-1] for a in calls if a[0] == "disable"]
        self.assertEqual(disabled, ["termon.service"])


class PtyForkTests(unittest.TestCase):
    def test_no_fork_in_the_threaded_server(self):
        with open(FILE, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("pty.fork", text)
        self.assertNotIn("os.fork", text)
        self.assertNotIn("preexec_fn", text)
        self.assertNotIn("shell=True", text)
        self.assertNotRegex(text, r'\["sh", "-c"')


class ConfigTests(unittest.TestCase):
    def test_https_defaults_on_and_round_trips(self):
        self.assertTrue(tm.load_config()["https"])
        cfg = tm.load_config()
        cfg["https"] = False
        tm.save_config(cfg)
        try:
            self.assertFalse(tm.load_config()["https"])
        finally:
            cfg["https"] = True
            tm.save_config(cfg)
        self.assertTrue(tm.load_config()["https"])

    def test_host_header_parser(self):
        ok = ("127.0.0.1", "127.0.0.1:7878", "[::1]", "[::1]:7878", "localhost:7878", "192.168.0.5")
        bad = ("", "a b", "[::1", "::1", "[fe80::1%eth0]", "evil.example", "1.2.3.4:abc", "x" * 400)
        for v in ok:
            self.assertTrue(tm._host_ok([v]), v)
        for v in bad:
            self.assertFalse(tm._host_ok([v]), v)
        self.assertFalse(tm._host_ok([]))
        self.assertFalse(tm._host_ok(["127.0.0.1", "127.0.0.1"]))


def run(*cmd):
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True)


def make_user(name, shell="/bin/bash", system=False):
    if system:
        r = run("useradd", "--system", "--no-create-home", "--user-group", "--shell", "/usr/sbin/nologin", name)
    else:
        r = run("useradd", "-m", "-s", shell, name)
    if r.returncode != 0:
        raise unittest.SkipTest(f"cannot create test user: {r.stderr.strip()}")


def drop_user(name):
    run("userdel", "-r", name)


class SplitModeTests(TermonBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sock = os.path.join(WORK, "helper.sock")
        cls.priv = tm.Privileged()
        cls.priv.split = True
        cls.helper = tm.HelperServer(cls.sock, cls.priv)
        cls.helper.bind()
        threading.Thread(target=cls.helper.serve_forever, daemon=True).start()
        cls.remote = tm.RemoteBackend(cls.sock)

    @classmethod
    def tearDownClass(cls):
        tm.BACKEND = tm.Privileged()
        try:
            cls.helper.sock.close()
        except OSError:
            pass
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        tm.BACKEND = self.remote

    def open_shell(self, c):
        st, _, t = c.json("POST", "/api/term/ticket", {})
        st, _, o = c.json("POST", "/api/term/open", {"ticket": t["ticket"], "kind": "shell", "rows": 24, "cols": 80})
        self.assertEqual(st, 200, o)
        return o["sid"]

    def test_sign_in_and_a_shell_through_the_helper(self):
        self.assertEqual(self.c.login()[0], 200)
        self.assertEqual(self.c.login("wrong")[0], 401)
        self.c.login()
        sid = self.open_shell(self.c)
        sess = tm._ptys[sid]
        self.c.json("POST", "/api/term/input", {"sid": sid, "data": "echo AB''C\n"})
        deadline = time.time() + 15
        while time.time() < deadline:
            with sess.cond:
                if b"ABC\r\n" in b"".join(d for _, d in sess.ring):
                    break
                sess.cond.wait(0.3)
        else:
            self.fail("no output through the helper")
        self.c.json("POST", "/api/term/close", {"sid": sid})
        deadline = time.time() + 10
        while time.time() < deadline and sess.alive:
            time.sleep(0.2)
        self.assertFalse(sess.alive)
        self.assertIsNotNone(sess.exit_code)

    def test_setup_reports_the_account(self):
        self.c.login()
        st, _, j = self.c.json("GET", "/api/setup")
        self.assertEqual(st, 200)
        self.assertTrue(j["helper"])
        self.assertEqual(j["account"]["account"], "root")
        self.assertTrue(j["account"]["split"])

    def test_helper_down_gives_503(self):
        tm.BACKEND = tm.RemoteBackend(os.path.join(WORK, "nothing.sock"))
        st, _, j = self.c.json("POST", "/api/login", {"password": GOOD_PW})
        self.assertEqual(st, 503, j)
        self.assertIn("helper", j["message"])

    def test_helper_only_signals_its_own_children(self):
        import subprocess
        outsider = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            self.remote.signal(outsider.pid, "KILL")
            time.sleep(0.3)
            self.assertIsNone(outsider.poll())
        finally:
            outsider.kill()
            outsider.wait()

    def test_helper_refuses_unknown_requests_and_programs(self):
        with self.assertRaises(tm.PrivError):
            self.remote._call("rm-rf", {})
        with self.assertRaises(tm.PrivError) as ctx:
            self.remote.spawn("monitor", "bash", 24, 80)
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(tm.PrivError):
            self.remote.spawn("exec", "x", 24, 80)

    def test_helper_never_takes_a_command_line_from_the_web_side(self):
        info = self.remote.spawn("shell", None, 24, 80)
        try:
            self.assertGreater(info["pid"], 1)
            deadline = time.time() + 10
            argv = []
            while time.time() < deadline:
                with open(f"/proc/{info['pid']}/cmdline", "rb") as fh:
                    argv = fh.read().split(b"\0")
                if argv[0] == b"bash":
                    break
                time.sleep(0.1)
            self.assertEqual(argv[:2], [b"bash", b"-l"])
        finally:
            self.remote.signal(info["pid"], "KILL")
            os.close(info["fd"])
            self.remote.wait(info["pid"])

    def test_socket_is_not_open_to_everyone(self):
        self.assertEqual(os.stat(self.sock).st_mode & 0o077, 0)


class ShellUserTests(TermonBase):
    USER = "termontst"

    @classmethod
    def setUpClass(cls):
        if os.geteuid() != 0:
            raise unittest.SkipTest("needs root to create a test user")
        super().setUpClass()
        make_user(cls.USER)

    def setUp(self):
        super().setUp()
        cfg = tm.load_config()
        cfg["shell_user"] = ""
        tm.save_config(cfg)

    @classmethod
    def tearDownClass(cls):
        try:
            tm.BACKEND.set_shell_user("", GOOD_PW)
        except tm.PrivError:
            pass
        drop_user(cls.USER)
        super().tearDownClass()

    def test_shell_runs_as_that_user_with_a_tty_and_no_root_group(self):
        self.c.login()
        st, _, j = self.c.json("POST", "/api/setup/shell_user", {"user": self.USER, "password": GOOD_PW, "confirm": True})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["account"], self.USER)
        self.assertEqual(self.c.json("GET", "/api/whoami")[2]["logged_in"], False)
        self.assertEqual(tm.load_config()["shell_user"], self.USER)
        self.c.login()
        st, _, t = self.c.json("POST", "/api/term/ticket", {})
        st, _, o = self.c.json("POST", "/api/term/open", {"ticket": t["ticket"], "kind": "shell"})
        self.assertEqual(st, 200, o)
        self.assertIn(self.USER, o["label"])
        sid = o["sid"]
        sess = tm._ptys[sid]
        self.c.json("POST", "/api/term/input", {"sid": sid, "data": "echo U=$(id -u) G=$(id -g) H=$HOME T=$(tty) ; echo DO''NE\n"})
        deadline = time.time() + 15
        seen = b""
        while time.time() < deadline:
            with sess.cond:
                seen = b"".join(d for _, d in sess.ring)
                if b"\r\nDONE" in seen:
                    break
                sess.cond.wait(0.3)
        import pwd
        pw = pwd.getpwnam(self.USER)
        text = seen.decode("utf-8", "replace")
        self.assertIn(f"U={pw.pw_uid} G={pw.pw_gid} H={pw.pw_dir} T=/dev/pts/", text)
        st = os.stat(f"/proc/{sess.pid}")
        self.assertEqual(st.st_uid, pw.pw_uid)
        self.assertEqual(os.getsid(sess.pid), sess.pid)

    def test_monitor_runs_as_that_user(self):
        import pwd
        tm.BACKEND.set_shell_user(self.USER, GOOD_PW)
        info = tm.BACKEND.spawn("monitor", "top", 24, 80) if tm.shutil.which("top") else None
        if info is None:
            self.skipTest("top is not installed")
        try:
            want = pwd.getpwnam(self.USER).pw_uid
            deadline = time.time() + 10
            while time.time() < deadline and os.stat(f"/proc/{info['pid']}").st_uid != want:
                time.sleep(0.1)
            self.assertEqual(os.stat(f"/proc/{info['pid']}").st_uid, want)
        finally:
            tm.BACKEND.signal(info["pid"], "KILL")
            os.close(info["fd"])
            tm.BACKEND.wait(info["pid"])

    def test_wrong_password_is_refused_and_counts_as_a_failure(self):
        self.c.login()
        for _ in range(tm.AUTH_MAX_FAILURES):
            st, _, _ = self.c.json("POST", "/api/setup/shell_user", {"user": self.USER, "password": "no", "confirm": True})
            self.assertIn(st, (401, 429))
        st, _, _ = self.c.json("POST", "/api/setup/shell_user", {"user": self.USER, "password": GOOD_PW, "confirm": True})
        self.assertEqual(st, 429)
        self.assertEqual(tm.load_config()["shell_user"], "")

    def test_refused_accounts(self):
        for user, code in (("nobody-here-xyz", 400), ("daemon", 400), ("Bad Name", 400)):
            with self.assertRaises(tm.PrivError) as ctx:
                tm.BACKEND.set_shell_user(user, GOOD_PW)
            self.assertEqual(ctx.exception.code, code, user)
        self.assertEqual(tm.load_config()["shell_user"], "")

    def test_root_can_be_chosen_again(self):
        tm.BACKEND.set_shell_user(self.USER, GOOD_PW)
        res = tm.BACKEND.set_shell_user("root", GOOD_PW)
        self.assertEqual(res["account"], "root")
        self.assertEqual(tm.load_config()["shell_user"], "")

    def test_sudo_state_is_one_of_the_known_values(self):
        self.assertIn(tm._sudo_state(self.USER), ("none", "password", "nopasswd", "unknown"))
        self.assertEqual(tm._sudo_state("root"), "root")

    def test_web_user_cannot_also_be_the_shell_account(self):
        tm.BACKEND.set_shell_user(self.USER, GOOD_PW)
        with self.assertRaises(tm.PrivError):
            tm.BACKEND.set_web_user(self.USER)
        with self.assertRaises(tm.PrivError):
            tm.BACKEND.set_web_user("root")


class WebUserTests(TermonBase):
    NAME = "termonwebtst"

    @classmethod
    def setUpClass(cls):
        if os.geteuid() != 0:
            raise unittest.SkipTest("needs root to create a test user")
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        drop_user(cls.NAME)

    def test_web_user_is_created_as_a_system_account_and_the_unit_follows(self):
        import pwd
        unit = os.path.join(WORK, "termon.service")
        with open(unit, "w") as f:
            f.write("old")
        with mock.patch.object(tm, "SYSTEMD_SERVICE_PATH", unit), \
                mock.patch.object(tm, "_systemctl", lambda *a: mock.Mock(returncode=0, stdout="", stderr="")), \
                mock.patch.object(tm, "_restart_later", lambda: None):
            self.assertTrue(tm.BACKEND.set_web_user(self.NAME))
        pw = pwd.getpwnam(self.NAME)
        self.assertTrue(pw.pw_shell.endswith(("nologin", "false")))
        self.assertGreater(pw.pw_uid, 0)
        with open(unit) as f:
            body = f.read()
        self.assertIn(f"User={self.NAME}\n", body)
        self.assertIn("NoNewPrivileges=yes", body)
        self.assertIn("Requires=termon-helper.service", body)
        self.assertEqual(tm.load_config()["web_user"], self.NAME)
        self.assertEqual(os.stat(tm.TLS_KEY).st_uid, pw.pw_uid)
        self.assertEqual(os.stat(tm.TLS_KEY).st_mode & 0o777, 0o600)

    def test_login_accounts_are_not_accepted_as_the_web_user(self):
        with self.assertRaises(tm.PrivError):
            tm.BACKEND.set_web_user("bin") if False else tm.BACKEND.set_web_user("Bad Name")

    def test_unit_files_are_hardened(self):
        web = tm._web_unit_text("termon")
        for line in ("User=termon", "NoNewPrivileges=yes", "CapabilityBoundingSet=", "ProtectSystem=strict",
                     "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX", "Type=notify"):
            self.assertIn(line + ("\n" if not line.endswith("=") else ""), web + "\n")
        helper = tm._helper_unit_text()
        self.assertIn("--helper", helper)
        self.assertIn("KillMode=control-group", helper)
        self.assertNotIn("User=", helper)


class SessionLimitTests(TermonBase):
    def tearDown(self):
        tm._BIND_IP = False

    def test_a_session_ends_at_the_absolute_limit_even_while_in_use(self):
        with mock.patch.object(tm, "SESSION_MAX_SEC", 1), mock.patch.object(tm, "SESSION_TTL_SEC", 100):
            tok = tm._issue_session("127.0.0.1")
            deadline = time.time() + 0.8
            while time.time() < deadline:
                self.assertTrue(tm._session_valid(tok))
                time.sleep(0.2)
            time.sleep(0.5)
            self.assertFalse(tm._session_valid(tok))
            self.assertNotIn(tm._digest(tok), tm._sessions)

    def test_the_idle_limit_still_applies(self):
        with mock.patch.object(tm, "SESSION_TTL_SEC", 1):
            tok = tm._issue_session("127.0.0.1")
            self.assertTrue(tm._session_valid(tok))
            time.sleep(1.3)
            self.assertFalse(tm._session_valid(tok))

    def test_watching_the_stream_does_not_extend_the_idle_limit(self):
        with mock.patch.object(tm, "SESSION_TTL_SEC", 1):
            tok = tm._issue_session("127.0.0.1")
            for _ in range(5):
                time.sleep(0.3)
                tm._session_valid(tok, touch=False)
            self.assertFalse(tm._session_valid(tok, touch=False))

    def test_sign_out_everywhere_ends_every_login_and_terminal(self):
        a, b = Client(self.port), Client(self.port)
        a.login()
        b.login()
        st, _, t = b.json("POST", "/api/term/ticket", {})
        st, _, o = b.json("POST", "/api/term/open", {"ticket": t["ticket"], "kind": "shell"})
        sess = tm._ptys[o["sid"]]
        st, h, _ = a.json("POST", "/api/logout_all", {})
        self.assertEqual(st, 200)
        self.assertIn("Max-Age=0", h["Set-Cookie"])
        self.assertFalse(a.json("GET", "/api/whoami")[2]["logged_in"])
        self.assertFalse(b.json("GET", "/api/whoami")[2]["logged_in"])
        deadline = time.time() + 10
        while time.time() < deadline and sess.alive:
            time.sleep(0.2)
        self.assertFalse(sess.alive)

    def test_binding_is_off_by_default_and_ends_a_session_used_from_elsewhere_when_on(self):
        self.assertFalse(tm._BIND_IP)
        tok = tm._issue_session("10.0.0.1")
        self.assertTrue(tm._session_valid(tok, ip="10.0.0.2"))
        tm._BIND_IP = True
        self.assertTrue(tm._session_valid(tok, ip="10.0.0.1"))
        self.assertFalse(tm._session_valid(tok, ip="10.0.0.2"))
        self.assertFalse(tm._session_valid(tok, ip="10.0.0.1"))

    def test_binding_uses_the_ipv6_prefix_and_ipv4_mapping(self):
        tm._BIND_IP = True
        tok = tm._issue_session("2001:db8:5:6::10")
        self.assertTrue(tm._session_valid(tok, ip="2001:db8:5:6:aaaa:bbbb:cccc:dddd"))
        tok2 = tm._issue_session("192.168.1.7")
        self.assertTrue(tm._session_valid(tok2, ip="::ffff:192.168.1.7"))
        tok3 = tm._issue_session("2001:db8:5:6::10")
        self.assertFalse(tm._session_valid(tok3, ip="2001:db8:5:7::10"))

    def test_switch_in_setup_changes_behaviour_and_is_saved(self):
        self.c.login()
        st, _, j = self.c.json("POST", "/api/setup/options", {"bind_session_ip": True, "confirm": True})
        self.assertEqual(st, 200, j)
        self.assertTrue(tm._BIND_IP)
        self.assertTrue(tm.load_config()["bind_session_ip"])
        self.assertTrue(self.c.json("GET", "/api/setup")[2]["options"]["bind_session_ip"])
        with tm._sess_lock:
            for rec in tm._sessions.values():
                rec[2] = "203.0.113.50"
        self.assertEqual(self.c.json("GET", "/api/setup")[0], 401)
        self.c.login()
        st, _, j = self.c.json("POST", "/api/setup/options", {"bind_session_ip": False, "confirm": True})
        self.assertEqual(st, 200)
        self.assertFalse(tm._BIND_IP)
        self.assertFalse(tm.load_config()["bind_session_ip"])

    def test_option_input_is_checked(self):
        self.c.login()
        for body in ({"bind_session_ip": "yes", "confirm": True}, {"bind_session_ip": True}, {"confirm": True}):
            self.assertEqual(self.c.json("POST", "/api/setup/options", body)[0], 400, body)
        with self.assertRaises(tm.PrivError):
            tm.BACKEND.set_option("shell_user", "root")


class CertificateTests(TermonBase):
    def fingerprint_with_openssl(self):
        r = run("openssl", "x509", "-in", tm.TLS_CERT, "-noout", "-fingerprint", "-sha256")
        return r.stdout.strip().split("=", 1)[1]

    def test_fingerprint_matches_openssl_and_setup(self):
        self.assertEqual(tm._cert_fingerprint(), self.fingerprint_with_openssl())
        self.c.login()
        st, _, j = self.c.json("GET", "/api/setup")
        self.assertEqual(j["cert"], {"https": True, "sha256": tm._cert_fingerprint()})

    def test_certificate_download_needs_a_login(self):
        self.assertEqual(self.c.request("GET", "/api/cert.pem")[0], 401)
        self.c.login()
        st, h, body = self.c.request("GET", "/api/cert.pem")
        self.assertEqual(st, 200)
        self.assertIn("attachment", h["Content-Disposition"])
        self.assertTrue(body.startswith(b"-----BEGIN CERTIFICATE-----"))
        self.assertNotIn(b"PRIVATE KEY", body)
        with open(tm.TLS_CERT, "rb") as fh:
            self.assertEqual(body, fh.read())

    def test_new_certificate_replaces_the_old_one_and_keeps_the_key_private(self):
        old = tm._cert_fingerprint()
        self.c.login()
        with mock.patch.object(tm, "_restart_later", lambda: None):
            st, _, j = self.c.json("POST", "/api/setup/cert", {"confirm": True})
        self.assertEqual(st, 200, j)
        self.assertNotEqual(j["sha256"], old)
        self.assertEqual(j["sha256"], tm._cert_fingerprint())
        self.assertEqual(os.stat(tm.TLS_KEY).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.exists(tm.TLS_KEY + ".old"))
        self.assertFalse(os.path.exists(tm.TLS_CERT + ".old"))

    def test_a_failed_replacement_keeps_the_old_certificate(self):
        old = tm._cert_fingerprint()
        with mock.patch.object(tm, "ensure_tls_cert", lambda: False):
            with self.assertRaises(tm.PrivError) as ctx:
                tm.BACKEND.regen_cert()
        self.assertEqual(ctx.exception.code, 500)
        self.assertEqual(tm._cert_fingerprint(), old)
        self.assertTrue(os.path.exists(tm.TLS_KEY))

    def test_regeneration_needs_confirmation(self):
        self.c.login()
        self.assertEqual(self.c.json("POST", "/api/setup/cert", {})[0], 400)

    def test_new_routes_need_a_login(self):
        for path in ("/api/logout_all", "/api/setup/options", "/api/setup/cert"):
            self.assertEqual(self.c.json("POST", path, {"confirm": True})[0], 401, path)


class QuietBeforeSignInTests(TermonBase):
    def test_health_and_whoami_say_nothing_but_the_basics(self):
        st, h, j = self.c.json("GET", "/api/health")
        self.assertEqual((st, j), (200, {"ok": True}))
        st, _, j = self.c.json("GET", "/api/whoami")
        self.assertEqual(j, {"ok": True, "logged_in": False})
        self.c.login()
        self.assertEqual(self.c.json("GET", "/api/whoami")[2], {"ok": True, "logged_in": True})

    def test_page_and_headers_do_not_name_the_version(self):
        st, h, body = self.c.request("GET", "/")
        text = body.decode("utf-8")
        self.assertNotIn(tm.VERSION, text)
        self.assertNotIn("termon", h.get("Server", "").lower())
        self.assertNotIn("Python", h.get("Server", ""))
        st, h, _ = self.c.request("GET", "/api/nothing")
        self.assertNotIn("Python", h.get("Server", ""))

    def test_version_comes_after_sign_in(self):
        self.c.login()
        self.assertEqual(self.c.json("GET", "/api/setup")[2]["version"], tm.VERSION)

    def test_error_replies_do_not_name_the_software(self):
        out = raw_exchange(self.port, b"FOO / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        self.assertNotIn(b"Python", out)
        self.assertNotIn(b"BaseHTTP", out)


class FilePermissionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="perm-", dir=WORK)
        self.file = os.path.join(self.dir, "t.py")
        with open(self.file, "w") as f:
            f.write("x = 1\n")
        os.chmod(self.file, 0o644)
        os.chmod(self.dir, 0o755)

    def test_root_owned_and_closed_to_others_is_fine(self):
        if os.geteuid() != 0:
            self.skipTest("needs root")
        self.assertEqual(tm._file_problem(self.file), "")

    def test_a_file_others_can_write_is_refused(self):
        os.chmod(self.file, 0o666)
        self.assertIn("can be changed", tm._file_problem(self.file))
        os.chmod(self.file, 0o664)
        self.assertIn("can be changed", tm._file_problem(self.file))

    def test_a_folder_others_can_write_is_refused(self):
        os.chmod(self.dir, 0o777)
        self.assertIn("can be changed", tm._file_problem(self.file))

    def test_a_symlink_is_judged_by_its_target(self):
        if os.geteuid() != 0:
            self.skipTest("needs root")
        link = os.path.join(self.dir, "link.py")
        os.symlink(self.file, link)
        os.chmod(self.file, 0o666)
        self.assertIn("can be changed", tm._file_problem(link))

    def test_a_file_owned_by_someone_else_is_refused(self):
        if os.geteuid() != 0:
            self.skipTest("needs root")
        os.chown(self.file, 65534, 65534)
        self.assertIn("does not belong to root", tm._file_problem(self.file))

    def test_install_source_rules(self):
        if os.geteuid() != 0:
            self.skipTest("needs root")
        self.assertEqual(tm._install_source_problem(self.file), "")
        os.chmod(self.file, 0o666)
        self.assertIn("changed", tm._install_source_problem(self.file))
        os.chmod(self.file, 0o644)
        os.chown(self.file, 12345, 12345)
        with mock.patch.dict(os.environ, {"SUDO_UID": ""}):
            self.assertIn("12345", tm._install_source_problem(self.file))
        with mock.patch.dict(os.environ, {"SUDO_UID": "12345"}):
            self.assertEqual(tm._install_source_problem(self.file), "")
        with mock.patch.dict(os.environ, {"SUDO_UID": "999"}):
            self.assertIn("12345", tm._install_source_problem(self.file))

    def test_install_refuses_a_file_others_can_write_before_touching_anything(self):
        if os.geteuid() != 0:
            self.skipTest("needs root")
        import subprocess
        copy = os.path.join(self.dir, "termon_copy.py")
        shutil.copyfile(FILE, copy)
        os.chmod(copy, 0o666)
        with mock.patch.dict(os.environ, {"SUDO_UID": ""}):
            r = subprocess.run([sys.executable, copy, "--install"], capture_output=True, text=True,
                               env=dict(os.environ, TERMON_CONFIG_DIR=os.path.join(self.dir, "cfg")))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Refusing to install", r.stderr + r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "cfg", "termon.conf")))

    def test_the_helper_unit_gives_the_stop_a_time_limit(self):
        self.assertIn("TimeoutStopSec=10\n", tm._helper_unit_text())


class LeftoverTests(unittest.TestCase):
    def setUp(self):
        self.priv = tm.Privileged()
        self.priv.pids_path = os.path.join(WORK, "pids-%d.json" % time.time_ns())

    def start_sleeper(self):
        import subprocess
        p = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def test_spawned_terminals_are_recorded_and_forgotten(self):
        info = self.priv.spawn("shell", None, 24, 80)
        try:
            with open(self.priv.pids_path) as f:
                table = json.load(f)
            self.assertIn(str(info["pid"]), table)
            self.assertEqual(table[str(info["pid"])], tm._proc_start(info["pid"]))
        finally:
            self.priv.signal(info["pid"], "KILL")
            os.close(info["fd"])
            self.priv.wait(info["pid"])
        with open(self.priv.pids_path) as f:
            self.assertEqual(json.load(f), {})

    def test_a_new_helper_ends_what_an_old_one_left(self):
        p = self.start_sleeper()
        with open(self.priv.pids_path, "w") as f:
            json.dump({str(p.pid): tm._proc_start(p.pid)}, f)
        self.assertEqual(self.priv.kill_leftovers(), 1)
        p.wait(timeout=5)
        self.assertIsNotNone(p.returncode)

    def test_a_reused_process_number_is_left_alone(self):
        p = self.start_sleeper()
        with open(self.priv.pids_path, "w") as f:
            json.dump({str(p.pid): "1"}, f)
        self.assertEqual(self.priv.kill_leftovers(), 0)
        time.sleep(0.3)
        self.assertIsNone(p.poll())

    def test_garbage_in_the_file_is_ignored(self):
        for text in ("not json", "[1,2]", '{"x": "1", "0": "5", "1": "5"}'):
            with open(self.priv.pids_path, "w") as f:
                f.write(text)
            self.assertEqual(self.priv.kill_leftovers(), 0)

    def test_a_terminal_ends_when_the_web_side_goes_away(self):
        info = self.priv.spawn("shell", None, 24, 80)
        os.close(info["fd"])
        code = self.priv.wait(info["pid"])
        self.assertIsNotNone(code)
        self.assertFalse(os.path.exists(f"/proc/{info['pid']}"))


def tearDownModule():
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
