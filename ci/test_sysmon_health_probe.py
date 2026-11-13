import importlib.util
import glob
import os
import socket
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=lambda p: [int(x) for x in os.path.basename(p).split("_")[1:5] if x.isdigit()])[-1]


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
    except OSError:
        return ""
    return "" if ip.startswith("127.") else ip


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HealthProbe:
    pattern = ""
    name = ""

    @classmethod
    def setUpClass(cls):
        cls.lan = lan_address()
        if not cls.lan:
            raise unittest.SkipTest("this machine has no network address besides loopback")
        cls.mod = load(newest(cls.pattern), cls.name)

    def serve(self, tls):
        mod = self.mod
        srv = mod._ThreadingHTTPServer((self.lan, 0), mod.Handler)
        tmp = tempfile.mkdtemp()
        if tls:
            self.assertEqual(mod.tls_start(srv, True, os.path.join(tmp, "tls"), "sysmon", mod._tls_log), "")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        return srv

    def probe(self, srv, tls):
        mod = self.mod
        mod._PROBE_EVERY = 0.05
        mod._http_ok_at = 0.0
        threading.Thread(target=mod._health_probe_loop, args=(self.lan, srv.server_address[1], tls), daemon=True).start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if mod._http_ok_at:
                return True
            time.sleep(0.05)
        return False

    def test_a_server_bound_to_the_nodes_address_with_https_is_seen_alive(self):
        srv = self.serve(True)
        self.assertTrue(self.probe(srv, True))

    def test_a_plain_server_bound_to_the_nodes_address_is_seen_alive(self):
        srv = self.serve(False)
        self.assertTrue(self.probe(srv, False))


class FullBuild(HealthProbe, unittest.TestCase):
    pattern = "sysmon_v[0-9]*.py"
    name = "smp_full"


if __name__ == "__main__":
    unittest.main()
