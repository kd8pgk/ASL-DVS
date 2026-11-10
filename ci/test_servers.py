#!/usr/bin/env python3
import ast
import base64
import hashlib
import http.client
import json
import os
import shutil
import signal
import socket
import secrets
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
    "nodecontrol": {"file": "nodecontrol_v9_3_104_20261108.py", "port": 8989, "scheme": "http"},
    "nodecontrol_pi02w": {"file": "nodecontrol_pi02w_v9_3_108_20261108.py", "port": 8989, "scheme": "http"},
    "sysmon": {"file": "sysmon_v6_13_95_20261028.py", "port": 9999, "scheme": "http"},
    "sysmon_pi02w": {"file": "sysmon_pi02w_v6_13_83_20261028.py", "port": 9999, "scheme": "http"},
    "nodetalker": {"file": "nodetalker_v0_10_33_20261110.py", "port": 8993, "scheme": "https", "health": "/api/health"},
    "amp_nodetalker": {"file": "amp_nodetalker_v0_3_7_20261101.py", "port": 8993, "scheme": "https", "health": "/api/health"},
    "noderecorder": {"file": "noderecorder_v0_15_0_20261110.py", "port": 8995, "scheme": "https", "health": "/api/health"},
    "pibrary": {"file": "pibrary_v0_16_1_20261104.py", "port": 9000, "scheme": "http", "health": "/api/health",
                "dirs_env": {"PIBRARY_CONFIG_DIR": "config", "PIBRARY_STAGE_DIR": "staged"}, "login_password": True},
    "instmon": {"file": "instmon_v2_99_0_20261110.py", "port": 8990, "scheme": "http", "health": "/",
                "health_expect": b"<html", "error_keys": ("error",),
                "dirs_env": {"INSTMON_CONFIG_DIR": "config", "INSTMON_LIBRARY_DIR": "library"},
                "files_env": {"INSTMON_SUITELOG": "run/suitelog.jsonl", "INSTMON_SUITELOG_FLAG": "run/suitelog.on",
                              "INSTMON_RECORDER_STATUS_URL": None}},
    "wifimon": {"file": "wifimon_v5_49_0_20261107.py", "port": 8991, "scheme": "http", "health": "/api/whoami",
                "health_expect": b'"version"', "error_keys": ("error",)},
    "44helper": {"file": "44helper_v0_1_19_20261108.py", "port": 9997, "scheme": "http",
                 "error_keys": ("output",)},
    "termon": {"file": "termon_v0_2_4_20261109.py", "port": 7878, "scheme": "https", "health": "/api/health",
               "no_launcher": True,
               "dirs_env": {"TERMON_CONFIG_DIR": "config"},
               "files_env": {"TERMON_LOCK": "run/termon.lock", "TERMON_RPT_CONF": "run/rpt.conf"}},
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
    "pibrary": {"/api/health", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"},
    "instmon": {"/suitelog"},
    "wifimon": {"/api/whoami", "/api/countries"},
    "44helper": set(),
    "termon": {"/api/health", "/api/whoami"},
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
        for var, sub in self.spec.get("dirs_env", {}).items():
            path = os.path.join(self.stub_dir, sub)
            os.makedirs(path, exist_ok=True)
            env[var] = path
        for var, sub in self.spec.get("files_env", {}).items():
            if sub is None:
                env[var] = "http://127.0.0.1:9/none"
                continue
            path = os.path.join(self.stub_dir, sub)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            env[var] = path
        return env

    def seed_login(self):
        if not self.spec.get("login_password"):
            return None
        password = secrets.token_urlsafe(18)
        salt = os.urandom(16)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
        stored = "scrypt$16384$8$1$%s$%s" % (base64.b64encode(salt).decode("ascii"), base64.b64encode(dk).decode("ascii"))
        config = os.path.join(self.stub_dir, self.spec["dirs_env"]["PIBRARY_CONFIG_DIR"])
        os.makedirs(config, exist_ok=True)
        with open(os.path.join(config, "pibrary.auth"), "w") as f:
            f.write(stored + "\n")
        return password

    def start(self, timeout=30):
        free_port_or_fail(self.spec["port"])
        try:
            os.remove(SHARED_AUTH_STATE)
        except FileNotFoundError:
            pass
        self.seed_login()
        self.log = open(self.log_path, "w")
        self.proc = subprocess.Popen(
            [sys.executable] + self.launcher_args() + [os.path.join(ROOT, self.spec["file"])],
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

    def launcher_args(self):
        if os.environ.get("ASL_TEST_VIA_LAUNCHER") != "1" or self.spec.get("no_launcher"):
            return []
        with open(os.path.join(ROOT, self.spec["file"]), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_LAUNCHER_CODE" for t in node.targets):
                path = os.path.join(self.stub_dir, "asl_dvs_launch.py")
                with open(path, "w") as out:
                    out.write(node.value.value)
                return [path]
        raise RuntimeError(f"{self.key}: no _LAUNCHER_CODE to start through")

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
            self.assertIn(self.server.spec.get("health_expect", b'"ok"'), body)

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
            keys = self.server.spec.get("error_keys", ("message",))
            self.assertTrue(any(k in json.loads(body) for k in keys), f"error replies must carry one of {keys}")

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

        def test_zz_login_lockout_after_repeated_failures(self):
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
