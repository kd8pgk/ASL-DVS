#!/usr/bin/env python3
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUB_BIN = os.path.join(ROOT, "ci", "fixtures", "servers", "bin")
LAUNCHER = "/usr/local/bin/asl_dvs_launch.py"
UNIT_DIR = "/etc/systemd/system"

TOOLS = [
    ("nodecontrol_pi02w_v9_3_107_20261102.py", "nodecontrol", "/usr/local/bin/nodecontrol.py"),
    ("sysmon_pi02w_v6_13_83_20261028.py", "sysmon", "/usr/local/bin/sysmon.py"),
    ("instmon_v2_91_1_20261105.py", "instmon", "/usr/local/bin/instmon.py"),
    ("wifimon_v5_48_0_20261102.py", "wifimon", "/usr/local/bin/wifimon.py"),
    ("44helper_v0_1_17_20261103.py", "44helper", "/usr/local/bin/44helper.py"),
    ("nodetalker_v0_10_20_20261105.py", "nodetalker", "/usr/local/bin/nodetalker.py"),
    ("noderecorder_v0_5_12_20261105.py", "noderecorder", "/usr/local/bin/noderecorder.py"),
    ("pibrary_v0_16_1_20261104.py", "pibrary", "/usr/local/bin/pibrary.py"),
]


def launcher_code(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_LAUNCHER_CODE" for t in node.targets):
            return node.value.value
    raise AssertionError(f"{path}: no _LAUNCHER_CODE")


def skip_reason():
    if os.environ.get("ASL_TEST_INSTALL") != "1":
        return "set ASL_TEST_INSTALL=1 to run (it installs into this machine's system folders)"
    if os.geteuid() != 0:
        return "install tests run as root"
    return None


class InstallUninstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = skip_reason()
        if why:
            raise unittest.SkipTest(why)
        for _, unit, link in TOOLS:
            if os.path.exists(os.path.join(UNIT_DIR, unit + ".service")) or os.path.lexists(link):
                raise unittest.SkipTest(f"{unit} is already installed here; run on a clean machine")
        cls.stub = tempfile.mkdtemp(prefix="asl-install-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "stub", ""), ignore_errors=True)

    def run_cli(self, file, flag):
        env = dict(os.environ, STUB_DIR=self.stub, PATH=STUB_BIN + os.pathsep + os.environ.get("PATH", ""))
        r = subprocess.run([sys.executable, os.path.join(ROOT, file), flag], cwd=self.stub, env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, f"{file} {flag} exited {r.returncode}:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")

    def test_install_then_uninstall_every_tool(self):
        code = launcher_code(os.path.join(ROOT, TOOLS[0][0]))
        for file, unit, link in TOOLS:
            with self.subTest(install=unit):
                self.run_cli(file, "--install")
                unit_path = os.path.join(UNIT_DIR, unit + ".service")
                self.assertTrue(os.path.isfile(unit_path), unit_path)
                with open(unit_path) as f:
                    body = f.read()
                self.assertIn(LAUNCHER, body)
                self.assertIn("Type=notify", body)
                self.assertTrue(os.path.lexists(link), link)
                self.assertTrue(os.path.isfile(os.path.realpath(link)))
                with open(LAUNCHER) as f:
                    self.assertEqual(f.read(), code)
        for i, (file, unit, link) in enumerate(reversed(TOOLS)):
            with self.subTest(uninstall=unit):
                self.run_cli(file, "--uninstall")
                self.assertFalse(os.path.exists(os.path.join(UNIT_DIR, unit + ".service")))
                self.assertFalse(os.path.lexists(link), link)
                last = i == len(TOOLS) - 1
                self.assertEqual(os.path.exists(LAUNCHER), not last,
                                 "the launcher stays while another unit uses it, and goes with the last one")


if __name__ == "__main__":
    unittest.main(verbosity=2)
