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

    def run_cli(self, file, flag, first_on_path=None):
        path = STUB_BIN + os.pathsep + os.environ.get("PATH", "")
        if first_on_path:
            path = first_on_path + os.pathsep + path
        env = dict(os.environ, STUB_DIR=self.stub, PATH=path)
        r = subprocess.run([sys.executable, os.path.join(ROOT, file), flag], cwd=self.stub, env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, f"{file} {flag} exited {r.returncode}:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
        return r.stdout

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
        import pwd
        file = ts.SERVERS["termon"]["file"]
        web_unit = os.path.join(UNIT_DIR, "termon.service")
        helper_unit = os.path.join(UNIT_DIR, "termon-helper.service")
        link = "/usr/local/bin/termon.py"
        if os.path.exists(web_unit) or os.path.exists(helper_unit) or os.path.lexists(link):
            self.skipTest("termon is already installed here; run on a clean machine")
        had_user = True
        try:
            pwd.getpwnam("termon")
        except KeyError:
            had_user = False
        other = os.path.join(UNIT_DIR, "termonitor.service")
        with open(other, "w") as f:
            f.write("[Service]\nExecStart=/usr/bin/other\n")
        fw_dir = tempfile.mkdtemp(prefix="asl-fw-")
        shutil.copy(os.path.join(ROOT, "ci", "fixtures", "firewall", "bin", "ufw"), os.path.join(fw_dir, "ufw"))
        ufw_rules = os.path.join(self.stub, "ufw", "rules")
        try:
            out = self.run_cli(file, "--install", first_on_path=fw_dir)
            self.assertIn("Firewall: opened 7878/tcp in ufw", out)
            with open(ufw_rules) as f:
                self.assertEqual(f.read().split(), ["7878/tcp"])
            with open(web_unit) as f:
                web = f.read()
            with open(helper_unit) as f:
                helper = f.read()
            self.assertIn("Type=notify", web)
            self.assertIn("User=termon\n", web)
            self.assertIn("NoNewPrivileges=yes", web)
            self.assertIn("ExecStart=/usr/bin/python3 /usr/local/bin/termon.py\n", web)
            self.assertIn("ExecStart=/usr/bin/python3 /usr/local/bin/termon.py --helper\n", helper)
            self.assertNotIn("User=", helper)
            pw = pwd.getpwnam("termon")
            self.assertGreater(pw.pw_uid, 0)
            self.assertTrue(pw.pw_shell.endswith(("nologin", "false")))
            self.assertTrue(os.path.isfile(os.path.realpath(link)))
            key = "/etc/asl_dvs/termon_tls/key.pem"
            self.assertEqual(os.stat(key).st_uid, pw.pw_uid)
            self.assertEqual(os.stat(key).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat("/etc/asl_dvs/termon.conf").st_mode & 0o777, 0o644)
            out = self.run_cli(file, "--uninstall", first_on_path=fw_dir)
            self.assertIn("Firewall: closed 7878/tcp in ufw", out)
            with open(ufw_rules) as f:
                self.assertEqual(f.read().split(), [])
            self.assertFalse(os.path.exists(web_unit))
            self.assertFalse(os.path.exists(helper_unit))
            self.assertFalse(os.path.lexists(link))
            self.assertTrue(os.path.exists(other), "an unrelated unit whose name starts with termon must stay")
        finally:
            shutil.rmtree(fw_dir, ignore_errors=True)
            for path in (other, web_unit, helper_unit, link):
                if os.path.lexists(path):
                    os.unlink(path)
            shutil.rmtree("/usr/local/lib/asl_dvs/termon", ignore_errors=True)
            shutil.rmtree("/etc/asl_dvs/termon_tls", ignore_errors=True)
            if os.path.exists("/etc/asl_dvs/termon.conf"):
                os.unlink("/etc/asl_dvs/termon.conf")
            if not had_user:
                subprocess.run(["userdel", "termon"], capture_output=True)

    def test_the_mass_uninstaller_removes_termon_and_closes_its_port(self):
        import glob
        file = ts.SERVERS["termon"]["file"]
        web_unit = os.path.join(UNIT_DIR, "termon.service")
        helper_unit = os.path.join(UNIT_DIR, "termon-helper.service")
        link = "/usr/local/bin/termon.py"
        if os.path.exists(web_unit) or os.path.exists(helper_unit) or os.path.lexists(link):
            self.skipTest("termon is already installed here; run on a clean machine")
        had_user = True
        try:
            import pwd
            pwd.getpwnam("termon")
        except KeyError:
            had_user = False
        fw_dir = tempfile.mkdtemp(prefix="asl-fw-")
        shutil.copy(os.path.join(ROOT, "ci", "fixtures", "firewall", "bin", "ufw"), os.path.join(fw_dir, "ufw"))
        ufw_rules = os.path.join(self.stub, "ufw", "rules")
        script = sorted(glob.glob(os.path.join(ROOT, "uninstall_all_v*.sh")))[-1]
        try:
            self.run_cli(file, "--install", first_on_path=fw_dir)
            with open(ufw_rules) as f:
                self.assertEqual(f.read().split(), ["7878/tcp"])
            env = dict(os.environ, STUB_DIR=self.stub, PATH=fw_dir + os.pathsep + STUB_BIN + os.pathsep + os.environ.get("PATH", ""))
            r = subprocess.run(["bash", script], cwd=self.stub, env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-1500:])
            self.assertIn("termon uninstalled", r.stdout)
            self.assertFalse(os.path.exists(web_unit))
            self.assertFalse(os.path.exists(helper_unit))
            self.assertFalse(os.path.lexists(link))
            with open(ufw_rules) as f:
                self.assertEqual(f.read().split(), [])
            self.assertTrue(os.path.isdir("/etc/asl_dvs/termon_tls"), "the certificate stays, as the message says")
        finally:
            shutil.rmtree(fw_dir, ignore_errors=True)
            for path in (web_unit, helper_unit, link):
                if os.path.lexists(path):
                    os.unlink(path)
            shutil.rmtree("/usr/local/lib/asl_dvs/termon", ignore_errors=True)
            shutil.rmtree("/etc/asl_dvs/termon_tls", ignore_errors=True)
            if os.path.exists("/etc/asl_dvs/termon.conf"):
                os.unlink("/etc/asl_dvs/termon.conf")
            if not had_user:
                subprocess.run(["userdel", "termon"], capture_output=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
