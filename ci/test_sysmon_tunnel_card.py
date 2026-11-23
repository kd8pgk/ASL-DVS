import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WG = "interface: wg0\n  public key: x\n\npeer: y\n  endpoint: 1.2.3.4:51820\n  latest handshake: 12 seconds ago\n  transfer: 1.20 MiB received, 340 KiB sent\n"


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class Card:
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tunnel_card_")
        self.conf = os.path.join(self.dir, "wg0.conf")

    def info(self, present, conf_text=None, wg=WG):
        if conf_text is not None:
            with open(self.conf, "w") as fh:
                fh.write(conf_text)
        real_isdir, real_path = os.path.isdir, self.mod.Path

        def fake_path(p):
            return real_path(self.conf if str(p) == "/etc/wireguard/wg0.conf" else p)
        with mock.patch.object(self.mod.os.path, "isdir", lambda p: present if p == "/sys/class/net/wg0" else real_isdir(p)), \
                mock.patch.object(self.mod, "Path", fake_path), \
                mock.patch.object(self.mod, "_run", lambda cmd, timeout=5: wg):
            return self.mod._tunnel_card_info()

    def test_no_wireguard_hides_the_card(self):
        self.assertIsNone(self.info(False))

    def test_up(self):
        r = self.info(True, "[Interface]\nAddress = 44.1.2.3/32\nPrivateKey = k\n")
        self.assertEqual(r, {"present": True, "address": "44.1.2.3/32", "handshake": "12 seconds ago",
                             "transfer": "1.20 MiB received, 340 KiB sent"})

    def test_conf_only_shows_not_present(self):
        r = self.info(False, "[Interface]\nAddress = 44.1.2.3/32\n", wg="")
        self.assertEqual(r, {"present": False, "address": "44.1.2.3/32", "handshake": "", "transfer": ""})

    def test_up_without_a_handshake_yet(self):
        r = self.info(True, "[Interface]\nAddress = 44.1.2.3/32\n", wg="interface: wg0\n")
        self.assertTrue(r["present"])
        self.assertEqual(r["handshake"], "")


class Pi02w(Card, unittest.TestCase):
    mod = load("sm_tunnel_pi02w", newest("sysmon_pi02w_v[0-9]*.py"))


class Full(Card, unittest.TestCase):
    mod = load("sm_tunnel_full", newest("sysmon_v[0-9]*.py"))


if __name__ == "__main__":
    unittest.main()
