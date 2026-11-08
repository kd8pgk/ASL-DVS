#!/usr/bin/env python3
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_servers as ts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUB_BIN = os.path.join(ROOT, "ci", "fixtures", "servers", "bin")
LAUNCHER = "/usr/local/bin/asl_dvs_launch.py"
UNIT_DIR = "/etc/systemd/system"

TOOLS = [(ts.SERVERS[key]["file"], unit, f"/usr/local/bin/{unit}.py") for key, unit in (
    ("nodecontrol_pi02w", "nodecontrol"),
    ("sysmon_pi02w", "sysmon"),
    ("instmon", "instmon"),
    ("wifimon", "wifimon"),
    ("44helper", "44helper"),
    ("nodetalker", "nodetalker"),
    ("noderecorder", "noderecorder"),
    ("pibrary", "pibrary"),
)]


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

    def test_termon_install_then_uninstall(self):
        file = ts.SERVERS["termon"]["file"]
        unit_path = os.path.join(UNIT_DIR, "termon.service")
        link = "/usr/local/bin/termon.py"
        if os.path.exists(unit_path) or os.path.lexists(link):
            self.skipTest("termon is already installed here; run on a clean machine")
        other = os.path.join(UNIT_DIR, "termonitor.service")
        with open(other, "w") as f:
            f.write("[Service]\nExecStart=/usr/bin/other\n")
        try:
            self.run_cli(file, "--install")
            with open(unit_path) as f:
                body = f.read()
            self.assertIn("Type=notify", body)
            self.assertIn("ExecStart=/usr/bin/python3 /usr/local/bin/termon.py", body)
            self.assertTrue(os.path.isfile(os.path.realpath(link)))
            self.run_cli(file, "--uninstall")
            self.assertFalse(os.path.exists(unit_path))
            self.assertFalse(os.path.lexists(link))
            self.assertTrue(os.path.exists(other), "an unrelated unit whose name starts with termon must stay")
        finally:
            for path in (other, unit_path, link):
                if os.path.lexists(path):
                    os.unlink(path)
            shutil.rmtree("/usr/local/lib/asl_dvs/termon", ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
