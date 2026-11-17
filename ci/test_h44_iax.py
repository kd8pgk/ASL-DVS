import glob
import importlib.util
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import sys
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_iax_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_iax_under_test"] = h44
spec.loader.exec_module(h44)


def responder(reply):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    seen = []

    def run():
        sock.settimeout(3)
        try:
            data, addr = sock.recvfrom(512)
            seen.append(data)
            if reply is not None:
                sock.sendto(reply, addr)
        except OSError:
            pass
        finally:
            sock.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return sock.getsockname()[1], seen, t


class Poke(unittest.TestCase):
    def test_a_pong_passes_and_the_poke_is_an_iax_poke(self):
        port, seen, t = responder(struct.pack("!HHIBBBB", 0x8002, 1, 5, 0, 1, 6, 3))
        ok, msg = h44._iax_poke("127.0.0.1", port, 2)
        t.join()
        self.assertTrue(ok, msg)
        self.assertIn("PONG", msg)
        self.assertEqual(seen[0][10:12], bytes([6, 30]))
        self.assertTrue(seen[0][0] & 0x80)

    def test_silence_fails(self):
        port, _, t = responder(None)
        ok, msg = h44._iax_poke("127.0.0.1", port, 0.3)
        t.join()
        self.assertFalse(ok)
        self.assertIn("No answer", msg)

    def test_a_reply_that_is_not_iax_fails(self):
        port, _, t = responder(b"hello world!!")
        ok, _ = h44._iax_poke("127.0.0.1", port, 2)
        t.join()
        self.assertFalse(ok)


class Check(unittest.TestCase):
    def run_check(self, listening, poke, bind="0.0.0.0", port="4569"):
        with mock.patch.object(h44, "_cfgr_bindport", lambda: port), \
                mock.patch.object(h44, "_iax_bindaddr", lambda: bind), \
                mock.patch.object(h44, "_local_port_listening", lambda p, proto="tcp": listening), \
                mock.patch.object(h44, "_iax_poke", lambda h, p, t=2.0: (poke, f"{h}:{p}")), \
                mock.patch.object(h44, "_firewalld_zone_info", lambda: {"ports": [], "services": ["iax2"]}), \
                mock.patch.object(h44, "_half_q", lambda argv, timeout=8: (0, "out of " + argv[-1])):
            return h44.build_iax_check()

    def test_pass_and_the_asterisk_commands_are_shown(self):
        r = self.run_check(True, True)
        self.assertTrue(r["success"])
        for c in ("settings", "peers", "registry", "channels", "netstats"):
            self.assertIn(f"== iax2 show {c} ==", r["output"])
        self.assertIn("127.0.0.1:4569", r["output"])

    def test_not_listening_fails(self):
        r = self.run_check(False, False)
        self.assertFalse(r["success"])
        self.assertIn("is NOT bound", r["output"])

    def test_a_tunnel_only_bindaddr_is_the_target(self):
        r = self.run_check(True, True, bind="44.1.2.3", port="4568")
        self.assertIn("44.1.2.3:4568", r["output"])
        self.assertIn("NOT open for 4568/udp", r["output"])


class Table(unittest.TestCase):
    def test_the_row_follows_the_bound_port(self):
        cfg = h44.configparser.ConfigParser()
        with mock.patch.object(h44, "_cfgr_bindport", lambda: "4568"):
            rows = h44.build_ports_status(cfg)["rows"]
        iax = [r for r in rows if r["label"] == "IAX2"]
        self.assertEqual([r["port"] for r in iax], ["4568"])
        self.assertEqual(iax[0]["role"], "peer-inbound")

    def test_the_route_and_the_button_exist(self):
        self.assertIn("/api/ports/iax", h44._GET_ROUTES)
        self.assertIn("iaxCheck(this)", h44._render_ports_panel())
        with open(h44.__file__, encoding="utf-8") as f:
            self.assertIn("function iaxCheck", f.read())


class PageScript(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_every_page_script_parses(self):
        js = "\n".join(getattr(h44, n) for n in dir(h44) if n.startswith("_JS_") and isinstance(getattr(h44, n), str))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "page.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write(js)
            r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[:600])


if __name__ == "__main__":
    unittest.main()
