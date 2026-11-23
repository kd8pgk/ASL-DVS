import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


INI = """[M17 NETWORK]
Callsign=OLDCALL
Address=0.0.0.0
LocalPort=17000

[USRP NETWORK]
Callsign=DONTTOUCH
"""


class SetCallsign(unittest.TestCase):
    def run_for(self, pattern, name):
        mod = load(name, newest(pattern))
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, True))
        ini = Path(d) / "USRP2M17.ini"
        ini.write_text(INI)
        restarts = []
        with mock.patch.object(mod, "_M17_INI_CANDIDATES", [ini]), \
                mock.patch.object(mod, "_run", lambda cmd, timeout=0: restarts.append(cmd) or ""):
            res = mod._m17_set_callsign("KD8PGK")
        return res, ini.read_text(), restarts

    def check(self, pattern, name):
        res, text, restarts = self.run_for(pattern, name)
        self.assertTrue(res["ok"], res)
        self.assertIn("Callsign=KD8PGK\n", text)
        self.assertIn("[USRP NETWORK]\nCallsign=DONTTOUCH\n", text)
        self.assertIn("LocalPort=17000", text)
        self.assertEqual(restarts, [["systemctl", "restart", "usrp2m17"]])

    def test_full_build(self):
        self.check("sysmon_v[0-9]*.py", "sm_full_m17")

    def test_pi02w_build(self):
        self.check("sysmon_pi02w_v*.py", "sm_pi_m17")

    def test_bad_callsign_is_refused_and_file_untouched(self):
        mod = load("sm_bad_m17", newest("sysmon_v[0-9]*.py"))
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, True))
        ini = Path(d) / "USRP2M17.ini"
        ini.write_text(INI)
        with mock.patch.object(mod, "_M17_INI_CANDIDATES", [ini]):
            res = mod._m17_set_callsign("x; rm")
        self.assertFalse(res["ok"])
        self.assertEqual(ini.read_text(), INI)

    def test_missing_callsign_line_is_refused(self):
        mod = load("sm_nokey_m17", newest("sysmon_v[0-9]*.py"))
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, True))
        ini = Path(d) / "USRP2M17.ini"
        ini.write_text("[M17 NETWORK]\nAddress=0.0.0.0\n")
        with mock.patch.object(mod, "_M17_INI_CANDIDATES", [ini]):
            res = mod._m17_set_callsign("KD8PGK")
        self.assertFalse(res["ok"])
        self.assertIn("No Callsign line", res["message"])


if __name__ == "__main__":
    unittest.main()
