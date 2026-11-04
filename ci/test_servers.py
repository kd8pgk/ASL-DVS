#!/usr/bin/env python3
import ast
import http.client
import json
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUB_BIN = os.path.join(ROOT, "ci", "fixtures", "servers", "bin")
ROOT_PW_ENV = "ASL_TEST_ROOT_PASSWORD"
SHARED_AUTH_STATE = "/run/asl_dvs/auth_session.json"

SERVERS = {
    "nodecontrol": {"file": "nodecontrol_v9_3_102_20261102.py", "port": 8989, "scheme": "http"},
    "nodecontrol_pi02w": {"file": "nodecontrol_pi02w_v9_3_107_20261102.py", "port": 8989, "scheme": "http"},
    "sysmon": {"file": "sysmon_v6_14_0_20261104.py", "port": 9999, "scheme": "http"},
    "sysmon_pi02w": {"file": "sysmon_pi02w_v6_14_0_20261104.py", "port": 9999, "scheme": "http"},
    "nodetalker": {"file": "nodetalker_v0_10_11_20261104.py", "port": 8993, "scheme": "https", "health": "/api/health"},
    "amp_nodetalker": {"file": "amp_nodetalker_v0_3_7_20261101.py", "port": 8993, "scheme": "https", "health": "/api/health"},
    "noderecorder": {"file": "noderecorder_v0_5_0_20261104.py", "port": 8995, "scheme": "https", "health": "/api/health"},
}
for _spec in SERVERS.values():
    _spec.setdefault("health", "/healthz")

ALWAYS_PUBLIC_PREFIXES = ("/static/", "/favicon")
ALWAYS_PUBLIC_PATHS = {"/", "/index.html", "/healthz", "/api/ping"}
PUBLIC_BY_DESIGN = {
    "nodecontrol": {"/api/event"},
    "nodecontrol_pi02w": {"/api/event"},
    "sysmon": {"/api/event"},
    "sysmon_pi02w": {"/api/event"},
    "nodetalker": {"/api/health", "/api/whoami"},
    "amp_nodetalker": {"/api/health", "/api/whoami"},
    "noderecorder": {"/api/health", "/api/whoami", "/api/recorder/status"},
}


def extract_routes(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    tables = {"GET": set(), "POST": set()}
    public = set()
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        if target is None or value is None:
            continue
        if (target.endswith("_ROUTES") or target.endswith("_ACTIONS")) and isinstance(value, ast.Dict):
            kind = "POST" if "POST" in target else "GET"
            for k in value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value.startswith("/"):
                    tables[kind].add(k.value)
        if target.startswith("_PUBLIC") and target.endswith("PATHS"):
            for c in ast.walk(value):
                if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.startswith("/"):
                    public.add(c.value)
    literals = {"GET": set(), "POST": set()}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("do_GET", "do_POST"):
            kind = "GET" if node.name == "do_GET" else "POST"
            for c in ast.walk(node):
                if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.startswith("/api/"):
                    literals[kind].add(c.value)
    return {
        "GET": sorted(tables["GET"] | literals["GET"]),
        "POST": sorted(tables["POST"] | literals["POST"]),
        "public": public,
    }


def free_port_or_fail(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
    except OSError:
        return
    else:
        raise RuntimeError(f"port {port} already answers; another server is running, stop it first")
    finally:
        s.close()


class Server:
    def __init__(self, key):
        self.key = key
        self.spec = SERVERS[key]
        self.stub_dir = tempfile.mkdtemp(prefix="asl-stub-")
        self.proc = None
        self.log_path = os.path.join(self.stub_dir, "server.log")
        self.log = None

    def env(self):
        env = dict(os.environ)
        env["STUB_DIR"] = self.stub_dir
        env["PATH"] = STUB_BIN + os.pathsep + env.get("PATH", "")
        return env

    def start(self, timeout=30):
        free_port_or_fail(self.spec["port"])
        try:
            os.remove(SHARED_AUTH_STATE)
        except FileNotFoundError:
            pass
        self.log = open(self.log_path, "w")
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, self.spec["file"])],
            cwd=ROOT, env=self.env(), stdout=self.log, stderr=subprocess.STDOUT,
            start_new_session=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"{self.key} exited at start; see {self.log_path}")
            try:
                self.request("GET", self.spec["health"], timeout=2)
                return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError(f"{self.key} did not answer on port {self.spec['port']}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=10)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.log:
            self.log.close()
        shutil.rmtree(self.stub_dir, ignore_errors=True)

    def request(self, method, path, body=None, headers=None, timeout=10):
        headers = dict(headers or {})
        if method == "POST":
            headers.setdefault("X-Requested-With", "XMLHttpRequest")
        if self.spec["scheme"] == "https":
            conn = http.client.HTTPSConnection("127.0.0.1", self.spec["port"], timeout=timeout,
                                               context=ssl._create_unverified_context())
        else:
            conn = http.client.HTTPConnection("127.0.0.1", self.spec["port"], timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, dict(resp.getheaders()), data
        finally:
            conn.close()


_ROUTE_CACHE = {}


def routes_for(key):
    if key not in _ROUTE_CACHE:
        _ROUTE_CACHE[key] = extract_routes(os.path.join(ROOT, SERVERS[key]["file"]))
    return _ROUTE_CACHE[key]


def is_public(key, path):
    return (path in ALWAYS_PUBLIC_PATHS or path.startswith(ALWAYS_PUBLIC_PREFIXES)
            or path in PUBLIC_BY_DESIGN.get(key, set()))


def make_case(key):
    class ServerCase(unittest.TestCase):
        server = None

        @classmethod
        def setUpClass(cls):
            if os.geteuid() != 0:
                raise unittest.SkipTest("server tests run as root (the tools require root)")
            cls.server = Server(key)
            cls.server.start()

        @classmethod
        def tearDownClass(cls):
            if cls.server:
                cls.server.stop()

        def test_public_endpoints_answer(self):
            status, _, body = self.server.request("GET", self.server.spec["health"])
            self.assertEqual(status, 200)
            self.assertIn(b'"ok"', body)

        def test_protected_get_routes_refuse_without_login(self):
            failures = []
            checked = 0
            for path in routes_for(key)["GET"]:
                if is_public(key, path):
                    continue
                checked += 1
                status, _, body = self.server.request("GET", path)
                if 200 <= status < 300 or status >= 500:
                    failures.append(f"GET {path} -> {status}")
            self.assertGreater(checked, 0)
            self.assertEqual(failures, [], f"{len(failures)} of {checked} protected GET routes leaked or failed")

        def test_protected_post_routes_refuse_without_login(self):
            failures = []
            checked = 0
            for path in routes_for(key)["POST"]:
                if is_public(key, path) or path == "/api/login" or path == "/api/logout":
                    continue
                checked += 1
                status, _, _ = self.server.request(
                    "POST", path, body=b"{}", headers={"Content-Type": "application/json"})
                if 200 <= status < 300 or status >= 500:
                    failures.append(f"POST {path} -> {status}")
            if checked == 0:
                self.skipTest("no protected POST routes in this build")
            self.assertEqual(failures, [], f"{len(failures)} of {checked} protected POST routes leaked or failed")

        def test_unknown_path_is_refused(self):
            status, _, _ = self.server.request("GET", "/api/no-such-route-xyz")
            self.assertIn(status, (401, 404))

        def test_login_rejects_wrong_password(self):
            status, _, body = self.server.request(
                "POST", "/api/login", body=json.dumps({"password": "definitely-wrong"}),
                headers={"Content-Type": "application/json"})
            self.assertIn(status, (401, 403, 429), body[:200])
            self.assertNotIn(status, (200, 204))
            self.assertIn("message", json.loads(body), "error replies must carry a message key")

        def test_login_rejects_empty_password(self):
            status, _, _ = self.server.request(
                "POST", "/api/login", body=json.dumps({"password": ""}),
                headers={"Content-Type": "application/json"})
            self.assertIn(status, (400, 401, 403, 429))

        def test_login_rejects_bad_json(self):
            status, _, _ = self.server.request(
                "POST", "/api/login", body=b"{not json",
                headers={"Content-Type": "application/json"})
            self.assertIn(status, (400, 403, 415, 429))

        def test_login_lockout_after_repeated_failures(self):
            codes = []
            for _ in range(6):
                status, _, _ = self.server.request(
                    "POST", "/api/login", body=json.dumps({"password": "wrong-again"}),
                    headers={"Content-Type": "application/json"})
                codes.append(status)
            self.assertIn(429, codes, f"no lockout after 6 wrong passwords: {codes}")

        def test_forged_cookie_is_refused(self):
            protected = [p for p in routes_for(key)["GET"] if not is_public(key, p)]
            if not protected:
                self.skipTest("no protected GET routes in this build")
            status, _, _ = self.server.request(
                "GET", protected[0], headers={"Cookie": "session=forged-0123456789abcdef"})
            self.assertIn(status, (401, 403))

    ServerCase.__name__ = f"Server_{key}"
    ServerCase.__qualname__ = f"Server_{key}"
    return ServerCase


for _key in SERVERS:
    globals()[f"Server_{_key}"] = make_case(_key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
