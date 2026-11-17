import glob
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_heal_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_heal_under_test"] = h44
spec.loader.exec_module(h44)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.sysd = os.path.join(self.d.name, "systemd")
        os.makedirs(self.sysd)
        self.script = os.path.join(self.d.name, "heal.sh")
        with open(self.script, "w") as f:
            f.write(h44._boot_heal_text())
        self.fake = os.path.join(self.d.name, "systemctl")
        self.log = os.path.join(self.d.name, "calls.log")
        self.loaded = os.path.join(self.d.name, "loaded")
        with open(self.fake, "w") as f:
            f.write('#!/bin/bash\n'
                    'echo "$@" >> "%s"\n'
                    'if [ "$1" = show ]; then\n'
                    '  u="${@: -1}"\n'
                    '  grep -qx "$u" "%s" 2>/dev/null && echo loaded || echo not-found\n'
                    'fi\n'
                    'exit 0\n' % (self.log, self.loaded))
        os.chmod(self.fake, 0o755)

    def load(self, *units):
        with open(self.loaded, "w") as f:
            f.write("\n".join(units) + "\n")

    def heal(self):
        env = dict(os.environ, H44_SYSTEMD_DIR=self.sysd, H44_SYSTEMCTL=self.fake)
        return subprocess.run(["bash", self.script], env=env, capture_output=True, text=True)

    def reloads(self):
        try:
            with open(self.log) as f:
                return sum(1 for ln in f if ln.strip() == "daemon-reload")
        except OSError:
            return 0

    def dropin(self, unit):
        return os.path.join(self.sysd, unit + ".d", h44._BOOT_DROPIN_NAME)

    def read(self, path):
        with open(path) as f:
            return f.read()


class Script(Tmp):
    def test_it_is_valid_bash_and_never_fails(self):
        self.assertEqual(subprocess.run(["bash", "-n", self.script]).returncode, 0)
        self.assertEqual(self.heal().returncode, 0)

    def test_it_covers_every_dvswitch_and_asl_unit_with_the_exact_text(self):
        text = h44._boot_heal_text()
        found = dict(re.findall(r"^ensure (\S+) <<'H44_EOF'\n(.*?)H44_EOF\n", text, re.M | re.S))
        want = {u: h44._boot_dv_dropin_text(u) for u in (h44._NETCHECK_UNIT,) + h44._OV_DVS_UNITS}
        want.update({u: h44._BOOT_DV_DROPIN for u in h44._BOOT_ASL_UNITS})
        self.assertEqual(found, want)

    def test_a_first_run_writes_the_exact_files_and_reloads_once(self):
        units = ("netcheck.service", "stfu.service", "analog_bridge.service", "asl3-update-astdb.service")
        self.load(*units)
        self.assertEqual(self.heal().returncode, 0)
        for u in units:
            text = h44._boot_dv_dropin_text(u) if u not in h44._BOOT_ASL_UNITS else h44._BOOT_DV_DROPIN
            self.assertEqual(self.read(self.dropin(u)), text, u)
        self.assertEqual(self.reloads(), 1)

    def test_a_second_run_changes_and_reloads_nothing(self):
        self.load("stfu.service")
        self.heal()
        before = self.read(self.dropin("stfu.service"))
        self.heal()
        self.assertEqual(self.read(self.dropin("stfu.service")), before)
        self.assertEqual(self.reloads(), 1)

    def test_a_service_installed_later_gets_the_ordering(self):
        self.load("analog_bridge.service")
        self.heal()
        self.assertFalse(os.path.exists(self.dropin("stfu.service")))
        self.load("analog_bridge.service", "stfu.service")
        self.heal()
        self.assertEqual(self.read(self.dropin("stfu.service")), h44._boot_dv_dropin_text("stfu.service"))
        self.assertEqual(self.reloads(), 2)

    def test_a_unit_that_is_not_loaded_is_left_alone(self):
        self.load("stfu.service")
        self.heal()
        self.assertEqual(os.listdir(self.sysd), ["stfu.service.d"])

    def test_a_stale_drop_in_is_replaced(self):
        self.load("stfu.service")
        os.makedirs(os.path.dirname(self.dropin("stfu.service")))
        with open(self.dropin("stfu.service"), "w") as f:
            f.write("[Service]\nRestart=no\n")
        self.heal()
        self.assertEqual(self.read(self.dropin("stfu.service")), h44._boot_dv_dropin_text("stfu.service"))

    def test_nothing_loaded_writes_and_reloads_nothing(self):
        self.load()
        self.heal()
        self.assertEqual(os.listdir(self.sysd), [])
        self.assertEqual(self.reloads(), 0)

    def test_it_is_idempotent_with_the_python_check(self):
        self.load("stfu.service", "ysfgateway.service")
        self.heal()
        for u in ("stfu.service", "ysfgateway.service"):
            self.assertTrue(h44._boot_file_is(self.dropin(u), h44._boot_dv_dropin_text(u)), u)


class Hook(unittest.TestCase):
    def test_the_apt_hook_runs_the_script_after_dpkg_and_never_fails_apt(self):
        t = h44._BOOT_HEAL_APT
        self.assertTrue(t.startswith("DPkg::Post-Invoke {"))
        self.assertTrue(t.rstrip().endswith("};"))
        self.assertIn(h44._BOOT_HEAL_PATH, t)
        cmd = re.search(r'"(.*)";', t).group(1)
        self.assertIn("|| true", cmd)
        self.assertEqual(subprocess.run(["sh", "-n", "-c", cmd]).returncode, 0)

    def test_the_boot_unit_runs_the_heal_first_and_ignores_its_failure(self):
        self.assertIn(f"ExecStartPre=-{h44._BOOT_HEAL_PATH}\nExecStart={h44._BOOT_SCRIPT_PATH}", h44._boot_unit_text())

    def test_the_paths(self):
        self.assertEqual(h44._BOOT_HEAL_PATH, "/usr/local/sbin/44helper-bootheal")
        self.assertEqual(h44._BOOT_HEAL_APT_PATH, "/etc/apt/apt.conf.d/99-44helper-bootheal")


class Status(Tmp):
    def status(self, units, asl=(), heal_ok=False, hook_ok=False):
        def file_is(path, text):
            if path == h44._BOOT_HEAL_PATH:
                return heal_ok
            if path == h44._BOOT_HEAL_APT_PATH:
                return hook_ok
            return True

        with mock.patch.object(h44, "_boot_dv_units", lambda: list(units)), \
                mock.patch.object(h44, "_boot_asl_units", lambda: list(asl)), \
                mock.patch.object(h44, "_boot_file_is", file_is), \
                mock.patch.object(h44, "_boot_netcheck_required_by", lambda u: []), \
                mock.patch.object(h44, "_network_backend", lambda: {"manager": "unknown", "wait_unit": "", "wait_enabled": ""}), \
                mock.patch.object(h44, "_boot_last", lambda: ("", False)), \
                mock.patch.object(h44, "WG0_CONF_PATH", os.path.join(self.d.name, "nowg")):
            return h44.status_boot_order()

    def test_missing_without_the_lasting_fix(self):
        st = self.status(["stfu.service"])
        self.assertFalse(st["done"])
        self.assertTrue(any(m.startswith("the lasting fix") for m in st["missing"]))

    def test_one_half_is_not_enough(self):
        self.assertFalse(self.status(["stfu.service"], heal_ok=True)["done"])
        self.assertFalse(self.status(["stfu.service"], hook_ok=True)["done"])

    def test_done_with_both(self):
        self.assertTrue(self.status(["stfu.service"], heal_ok=True, hook_ok=True)["done"])

    def test_not_asked_for_where_there_is_no_dvswitch_or_asl3(self):
        self.assertTrue(self.status([])["done"])

    def test_asl3_alone_counts(self):
        self.assertFalse(self.status([], asl=["asl3-update-astdb.service"])["done"])


class Apply(Tmp):
    def run_apply(self):
        writes = []

        def fake_write(path, text, mode):
            writes.append((path, text, mode))

        with mock.patch.object(h44, "_require_root", lambda: None), \
                mock.patch.object(h44, "_boot_write", fake_write), \
                mock.patch.object(h44, "_boot_dv_units", lambda: ["stfu.service"]), \
                mock.patch.object(h44, "_boot_asl_units", lambda: []), \
                mock.patch.object(h44, "_boot_wg_unit", lambda: h44._BOOT_WG_UNIT), \
                mock.patch.object(h44, "WG0_CONF_PATH", os.path.join(self.d.name, "nowg")), \
                mock.patch.object(h44, "_daemon_reload", lambda: {"success": True, "output": ""}), \
                mock.patch.object(h44, "_network_backend", lambda: {"manager": "unknown", "wait_unit": "", "wait_enabled": ""}), \
                mock.patch.object(h44, "status_boot_order", lambda: {"done": True, "missing": []}):
            res = h44.action_boot_order_apply()
        return res, writes

    def test_the_heal_script_and_the_hook_are_written_with_the_right_modes(self):
        res, writes = self.run_apply()
        self.assertTrue(res["success"])
        by = {p: (t, m) for p, t, m in writes}
        self.assertEqual(by[h44._BOOT_HEAL_PATH], (h44._boot_heal_text(), 0o755))
        self.assertEqual(by[h44._BOOT_HEAL_APT_PATH], (h44._BOOT_HEAL_APT, 0o644))
        self.assertEqual(by[h44._boot_dropin_path("stfu.service")][0], h44._boot_dv_dropin_text("stfu.service"))
        self.assertIn("lasting fix", res["output"])


class Removal(Tmp):
    def paths(self):
        heal = os.path.join(self.d.name, "bootheal")
        hook = os.path.join(self.d.name, "hook")
        for p in (heal, hook):
            with open(p, "w") as f:
                f.write("x")
        return heal, hook

    def test_revert_removes_the_heal_and_the_hook(self):
        heal, hook = self.paths()
        with mock.patch.object(h44, "_require_root", lambda: None), \
                mock.patch.object(h44, "_BOOT_HEAL_PATH", heal), mock.patch.object(h44, "_BOOT_HEAL_APT_PATH", hook), \
                mock.patch.object(h44, "_daemon_reload", lambda: {"success": True, "output": ""}), \
                mock.patch.object(h44, "_netcheck_nonfatal_path", lambda: os.path.join(self.d.name, "nf")):
            res = h44.action_boot_order_revert()
        self.assertFalse(os.path.exists(heal))
        self.assertFalse(os.path.exists(hook))
        self.assertIn(heal, res["output"])

    def test_dvswitch_undo_removes_them_too_or_the_hook_would_undo_the_undo(self):
        heal, hook = self.paths()
        with mock.patch.object(h44, "_require_root", lambda: None), \
                mock.patch.object(h44, "_BOOT_HEAL_PATH", heal), mock.patch.object(h44, "_BOOT_HEAL_APT_PATH", hook), \
                mock.patch.object(h44, "action_netcheck_revert", lambda: {"success": True, "output": ""}), \
                mock.patch.object(h44, "_daemon_reload", lambda: {"success": True, "output": ""}):
            res = h44.action_dv_boot_undo()
        self.assertFalse(os.path.exists(heal))
        self.assertFalse(os.path.exists(hook))
        self.assertTrue(res["success"])


if __name__ == "__main__":
    unittest.main()
