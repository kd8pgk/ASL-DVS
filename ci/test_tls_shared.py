import ast
import http.client
import os
import socket
import ssl
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(ROOT, "shared", "confio.py")

with open(SHARED, encoding="utf-8") as fh:
    _text = fh.read()
_tree = ast.parse(_text)
NAMES = [n.name for n in _tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("tls_")]
ns = {}
for _n in _tree.body:
    if isinstance(_n, ast.FunctionDef) and _n.name in NAMES:
        exec(compile(ast.get_source_segment(_text, _n), SHARED, "exec"), ns)

PORT_FOR_REDIRECT = 8123


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        secure = ns["tls_secure"](self.connection, self.headers, self.server.proxied)
        body = ("secure" if secure else "plain").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    ssl_ctx = None
    proxied = False
    plain_loopback = True

    def finish_request(self, request, client_address):
        ns["tls_finish_request"](self, request, client_address, PORT_FOR_REDIRECT, self.plain_loopback)

    def handle_error(self, request, client_address):
        pass


def start(tls_dir=None, enabled=True, **attrs):
    srv = Server(("127.0.0.1", 0), Handler)
    for k, v in attrs.items():
        setattr(srv, k, v)
    note = ns["tls_start"](srv, enabled, tls_dir, "testnode") if tls_dir else ""
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, note


def stop(srv):
    srv.shutdown()
    srv.server_close()


def get(srv, tls, path="/", headers=None):
    port = srv.server_address[1]
    if tls:
        conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=5, context=ssl._create_unverified_context())
    else:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        r = conn.getresponse()
        return r.status, r.getheader("Location"), r.read().decode()
    finally:
        conn.close()


class Standalone(unittest.TestCase):
    def test_every_function_runs_with_only_the_tls_functions_around_it(self):
        self.assertEqual(len(NAMES), 8)

    def test_used_by_lists_them_all(self):
        used = next(ast.literal_eval(n.value) for n in _tree.body if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", "") == "USED_BY" for t in n.targets))
        for name in NAMES:
            self.assertIn(name, used, name)


class Certificate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "tool_tls")
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def log(self, msg, level="info"):
        self.logs.append((level, msg))

    def test_made_once_with_private_modes(self):
        self.assertTrue(ns["tls_ensure_cert"](self.dir, "node", self.log))
        cert, key = os.path.join(self.dir, "cert.pem"), os.path.join(self.dir, "key.pem")
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(cert).st_mode), 0o644)
        before = os.stat(cert).st_mtime_ns
        self.assertTrue(ns["tls_ensure_cert"](self.dir, "node", self.log))
        self.assertEqual(os.stat(cert).st_mtime_ns, before)
        self.assertFalse([p for p in os.listdir(self.dir) if p.endswith(".tmp")])
        ns["tls_context"](self.dir)

    def test_context_needs_tls_1_2(self):
        ns["tls_ensure_cert"](self.dir, "node")
        self.assertEqual(ns["tls_context"](self.dir).minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_no_openssl_says_so_and_makes_nothing(self):
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = self.tmp.name
        try:
            self.assertFalse(ns["tls_ensure_cert"](self.dir, "node", self.log))
        finally:
            os.environ["PATH"] = old
        self.assertTrue(any("openssl not found" in m for _, m in self.logs))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "cert.pem")))

    def test_start_off_does_nothing(self):
        srv, note = start(self.dir, enabled=False)
        stop(srv)
        self.assertEqual(note, "")
        self.assertIsNone(srv.ssl_ctx)
        self.assertFalse(os.path.exists(self.dir))

    def test_start_without_openssl_falls_back_with_a_note(self):
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = self.tmp.name
        try:
            srv, note = start(self.dir)
        finally:
            os.environ["PATH"] = old
        try:
            self.assertIsNone(srv.ssl_ctx)
            self.assertIn("could not start", note)
            self.assertEqual(get(srv, False)[0], 200)
        finally:
            stop(srv)

    def test_a_bad_certificate_is_set_aside_and_remade(self):
        os.makedirs(self.dir, mode=0o700)
        for name in ("cert.pem", "key.pem"):
            with open(os.path.join(self.dir, name), "w") as fh:
                fh.write("not a certificate\n")
        srv, note = start(self.dir)
        try:
            self.assertEqual(note, "")
            self.assertIsNotNone(srv.ssl_ctx)
            self.assertEqual(len([p for p in os.listdir(self.dir) if p.endswith(".bad")]), 2)
            self.assertEqual(get(srv, True)[2], "secure")
        finally:
            stop(srv)


class Serving(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = os.path.join(cls.tmp.name, "tls")
        cls.srv, note = start(cls.dir)
        assert note == "" and cls.srv.ssl_ctx is not None

    @classmethod
    def tearDownClass(cls):
        stop(cls.srv)
        cls.tmp.cleanup()

    def test_tls_is_served_and_secure(self):
        self.assertEqual(get(self.srv, True), (200, None, "secure"))

    def test_plain_from_loopback_is_served_not_redirected(self):
        self.assertEqual(get(self.srv, False), (200, None, "plain"))

    def test_tls_keeps_the_connection_open(self):
        port = self.srv.server_address[1]
        conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=5, context=ssl._create_unverified_context())
        try:
            for _ in range(3):
                conn.request("GET", "/")
                self.assertEqual(conn.getresponse().read(), b"secure")
        finally:
            conn.close()

    def test_a_tunnel_header_makes_a_plain_request_secure_only_when_proxied(self):
        hdr = {"X-Forwarded-Proto": "https"}
        self.assertEqual(get(self.srv, False, headers=hdr)[2], "plain")
        self.srv.proxied = True
        try:
            self.assertEqual(get(self.srv, False, headers=hdr)[2], "secure")
            self.assertEqual(get(self.srv, False)[2], "plain")
        finally:
            self.srv.proxied = False

    def test_old_tls_is_refused(self):
        port = self.srv.server_address[1]
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.maximum_version = ssl.TLSVersion.TLSv1_1
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
                with ctx.wrap_socket(raw):
                    self.fail("TLS 1.1 was accepted")
        except (ssl.SSLError, OSError, ValueError):
            pass

    def test_junk_does_not_hurt_the_server(self):
        port = self.srv.server_address[1]
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(b"\x00\x01\x02\r\n\r\n")
            s.settimeout(5)
            try:
                s.recv(100)
            except OSError:
                pass
        self.assertEqual(get(self.srv, True)[0], 200)


class Redirect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv, _ = start(os.path.join(cls.tmp.name, "tls"), plain_loopback=False)

    @classmethod
    def tearDownClass(cls):
        stop(cls.srv)
        cls.tmp.cleanup()

    def test_plain_gets_a_301_to_https_with_the_path(self):
        status, loc, body = get(self.srv, False, "/api/x?a=1", {"Host": "node.local:8989"})
        self.assertEqual((status, loc), (301, "https://node.local:8989/api/x?a=1"))
        self.assertIn("HTTPS", body)

    def test_ipv6_host_is_kept(self):
        self.assertEqual(get(self.srv, False, "/", {"Host": "[fe80::1]:8989"})[1], "https://[fe80::1]:8989/")

    def test_a_bad_host_falls_back_to_the_nodes_own_address(self):
        loc = get(self.srv, False, "/", {"Host": "evil.com/x y"})[1]
        self.assertTrue(loc.startswith("https://") and loc.endswith(":%d/" % PORT_FOR_REDIRECT), loc)
        self.assertNotIn("evil", loc)

    def test_a_double_slash_path_cannot_become_another_site(self):
        self.assertEqual(get(self.srv, False, "//evil.com/", {"Host": "node:1"})[1], "https://node:1/")

    def test_tls_is_still_served(self):
        self.assertEqual(get(self.srv, True)[2], "secure")


class PlainServer(unittest.TestCase):
    def test_without_https_everything_is_plain(self):
        srv, note = start()
        try:
            self.assertEqual(note, "")
            self.assertEqual(get(srv, False), (200, None, "plain"))
        finally:
            stop(srv)


if __name__ == "__main__":
    unittest.main()
