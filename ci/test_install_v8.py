import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import glob

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTALLER = sorted(glob.glob(os.path.join(ROOT, "install_all_v8_*.sh")))[-1]
TUNNEL = sorted(glob.glob(os.path.join(ROOT, "tunnel_remove_v*.sh")))[-1]
WIFI = sorted(glob.glob(os.path.join(ROOT, "wifi_menu_v*.sh")))[-1]

TOOLS = [
    "instmon_v9_9_9_20260101.py",
    "nodecontrol_v9_9_9_20260101.py",
    "sysmon_v9_9_9_20260101.py",
    "wifimon_v9_9_9_20260101.py",
    "44helper_v9_9_9_20260101.py",
    "nodetalker_v9_9_9_20260101.py",
    "noderecorder_v9_9_9_20260101.py",
    "nodemon_v9_9_9_20260101.py",
    "pibrary_v9_9_9_20260101.py",
    "termon_v9_9_9_20260101.py",
    "piper_dashboard_v9_9_9_20260101.py",
]
PORTS = [8990, 8989, 9999, 8991, 9997, 8993, 8995, 7777, 9000, 7878, 8765]

FAKE = '''#!/usr/bin/env python3
import os, sys
VERSION = "9.9.9"
with open(os.environ["ASL_TEST_LOG"], "a") as f:
    f.write(os.path.basename(__file__) + " " + " ".join(sys.argv[1:]) + "\\n")
sys.exit(0)
'''


@unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "needs root: the installer refuses to run without it")
class InstallAllV8(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="install_all_v8_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "repo")
        os.makedirs(self.work)
        shutil.copy(INSTALLER, self.work)
        shutil.copy(TUNNEL, self.work)
        shutil.copy(WIFI, self.work)
        for name in TOOLS:
            p = os.path.join(self.work, name)
            with open(p, "w") as f:
                f.write(FAKE)
        self.model = os.path.join(self.tmp, "model")
        with open(self.model, "w") as f:
            f.write("Raspberry Pi 5 Model B\0")
        self.log = os.path.join(self.tmp, "calls.log")
        self.stubs = os.path.join(self.tmp, "bin")
        os.makedirs(self.stubs)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = dict(os.environ)
        self.env.update({
            "ASL_DVS_ETC": os.path.join(self.tmp, "etc"),
            "INSTMON_LIBRARY_DIR": os.path.join(self.tmp, "etc", "instmon_library"),
            "SYSMON_CONF_DIR": os.path.join(self.tmp, "sysmon"),
            "ASL_DVS_HOME_DIR": self.home,
            "ASL_DVS_MODEL_FILE": self.model,
            "ASL_TEST_LOG": self.log,
            "PATH": self.stubs + os.pathsep + self.env.get("PATH", ""),
        })

    def stub(self, name, body):
        p = os.path.join(self.stubs, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(p, stat.S_IRWXU)

    def run_installer(self, *args):
        return subprocess.run(["bash", os.path.join(self.work, os.path.basename(INSTALLER)), *args],
                              env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def test_unknown_option_is_refused(self):
        r = self.run_installer("--bogus")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Unknown option", r.stderr + r.stdout)

    def test_legacy_flags_are_ignored_with_a_warning(self):
        r = self.run_installer("--offline", "--tools=dashboard", "--no-manuals")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("--tools=dashboard is no longer used", r.stdout)
        self.assertIn("--no-manuals is no longer used", r.stdout)

    def test_every_tool_is_installed_with_instmon_first(self):
        r = self.run_installer("--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = self.calls()
        self.assertEqual(len(lines), len(TOOLS))
        self.assertTrue(lines[0].startswith("instmon_"), lines[0])
        self.assertEqual(sorted(l.split()[0] for l in lines), sorted(TOOLS))
        self.assertTrue(all(l.endswith("--install") for l in lines))

    def test_directories_are_created(self):
        r = self.run_installer("--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for d in (os.path.join(self.tmp, "etc"), os.path.join(self.tmp, "sysmon"),
                  os.path.join(self.tmp, "etc", "instmon_library", "dashboard"),
                  os.path.join(self.tmp, "etc", "instmon_library", "piper_dashboard")):
            self.assertTrue(os.path.isdir(d), d)

    def test_no_manuals_folder_is_made(self):
        self.run_installer("--offline")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "etc", "instmon_library", "docs")))

    def test_ufw_branch_opens_every_port(self):
        self.stub("ufw", 'if [ "$1" = status ]; then echo "Status: active"; exit 0; fi\n'
                         'echo "ufw $*" >> "$ASL_TEST_LOG.fw"; exit 0')
        r = self.run_installer("--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.log + ".fw") as f:
            allowed = f.read().splitlines()
        for port in PORTS:
            self.assertIn("ufw allow %d/tcp" % port, allowed)

    def test_firewalld_branch_opens_every_port_permanently(self):
        self.stub("firewall-cmd", 'case "$1" in --state) echo running ;; --get-default-zone) echo public ;;'
                                  ' --reload) exit 0 ;; --permanent) echo "$*" >> "$ASL_TEST_LOG.fw" ;; esac; exit 0')
        r = self.run_installer("--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.log + ".fw") as f:
            opened = f.read()
        for port in PORTS:
            self.assertIn("--add-port=%d/tcp" % port, opened)
        self.assertIn("--zone=public", opened)

    def test_no_firewall_opens_nothing_and_says_so(self):
        r = self.run_installer("--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("No firewall is running", r.stdout)

    def test_home_folder_gets_the_two_scripts(self):
        r = self.run_installer("--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for name in ("wifi_menu_v3_1_20261011.sh", "tunnel_remove_v1_0_0_20261123.sh"):
            p = os.path.join(self.home, name)
            self.assertTrue(os.path.isfile(p), p)
            self.assertTrue(os.access(p, os.X_OK), p)

    def test_a_missing_file_offline_is_reported_and_fails(self):
        os.remove(os.path.join(self.work, "termon_v9_9_9_20260101.py"))
        r = self.run_installer("--offline")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Terminal Monitor: no file found", r.stdout)
        self.assertIn("Not finished", r.stdout)

    def test_auto_callsign_seeds_both_configs(self):
        self.env["AUTO_CALLSIGN"] = "kd8pgk"
        self.env["AUTO_NODE"] = "652701"
        r = self.run_installer("--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.tmp, "etc", "asl_dvs.conf")) as f:
            dash = f.read()
        self.assertIn("asl_node=652701", dash)
        self.assertIn("callsign=KD8PGK", dash)
        with open(os.path.join(self.tmp, "sysmon", "sysmon.conf")) as f:
            sysm = f.read()
        self.assertIn("callsign = KD8PGK", sysm)
        self.assertIn("node = 652701", sysm)

    def test_existing_configs_are_kept(self):
        os.makedirs(os.path.join(self.tmp, "etc"))
        os.makedirs(os.path.join(self.tmp, "sysmon"))
        with open(os.path.join(self.tmp, "etc", "asl_dvs.conf"), "w") as f:
            f.write("keep me\n")
        with open(os.path.join(self.tmp, "sysmon", "sysmon.conf"), "w") as f:
            f.write("keep me too\n")
        self.env["AUTO_CALLSIGN"] = "KD8PGK"
        self.env["AUTO_NODE"] = "652701"
        self.run_installer("--offline")
        with open(os.path.join(self.tmp, "etc", "asl_dvs.conf")) as f:
            self.assertEqual(f.read(), "keep me\n")

    def test_no_identity_non_interactive_warns_and_writes_nothing(self):
        r = self.run_installer("--offline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("No callsign or node number set", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "etc", "asl_dvs.conf")))


if __name__ == "__main__":
    unittest.main()
