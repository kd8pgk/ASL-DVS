import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_suite_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_suite_under_test"] = h44
spec.loader.exec_module(h44)

FORM = dict(h44._BLD_DEFAULT, callsign="KD8PGK", node="652701", dmr_id="3123456")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.units = os.path.join(self.d.name, "units")
        self.docs = os.path.join(self.d.name, "docs")
        os.makedirs(self.units)
        self.patches = [mock.patch.object(h44, "_BLD_UNIT_DIRS", (self.units,)), mock.patch.object(h44, "_BLD_MANUALS_DIR", self.docs)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def unit(self, name):
        open(os.path.join(self.units, name + ".service"), "w").close()


class State(Tmp):
    def installed(self):
        return {t["key"]: t["installed"] for t in h44._bld_suite_state()}

    def test_nothing_installed(self):
        self.assertEqual(set(self.installed().values()), {False})

    def test_units_and_manuals_are_read(self):
        for u in ("nodecontrol", "sysmon", "nodemon"):
            self.unit(u)
        os.makedirs(self.docs)
        open(os.path.join(self.docs, "a.pdf"), "w").close()
        got = self.installed()
        self.assertEqual([k for k, v in got.items() if v], ["dashboard", "sysmon", "nodemon", "manuals"])

    def test_an_empty_manuals_folder_counts_as_missing(self):
        os.makedirs(self.docs)
        self.assertFalse(self.installed()["manuals"])

    def test_44helper_and_terminal_monitor_are_not_in_the_list(self):
        keys = [t["key"] for t in h44._bld_suite_state()]
        for never in ("44helper", "termon"):
            self.assertNotIn(never, keys)
        self.assertEqual(keys, ["instmon", "dashboard", "sysmon", "wifimon", "nodetalker", "noderecorder", "pibrary", "nodemon", "manuals"])


class Build(unittest.TestCase):
    def test_auto_follows_the_board(self):
        with mock.patch.object(h44, "_bld_board", lambda: {"model": "Zero 2", "zero2": True}):
            self.assertEqual(h44._bld_suite_build({"suite_build": "auto"}), "pi02w")
        with mock.patch.object(h44, "_bld_board", lambda: {"model": "Pi 4", "zero2": False}):
            self.assertEqual(h44._bld_suite_build({"suite_build": "auto"}), "full")
            self.assertEqual(h44._bld_suite_build({}), "full")

    def test_a_pick_wins(self):
        with mock.patch.object(h44, "_bld_board", lambda: {"model": "Zero 2", "zero2": True}):
            self.assertEqual(h44._bld_suite_build({"suite_build": "full"}), "full")
        with mock.patch.object(h44, "_bld_board", lambda: {"model": "Pi 4", "zero2": False}):
            self.assertEqual(h44._bld_suite_build({"suite_build": "pi02w"}), "pi02w")

    def test_form_clean_normalises_the_suite_fields(self):
        f = h44._bld_form_clean({"suite_build": "evil", "suite_channel": "nightly"})
        self.assertEqual((f["suite_build"], f["suite_channel"]), ("auto", "stable"))
        f = h44._bld_form_clean({"suite_build": "full", "suite_channel": "testing"})
        self.assertEqual((f["suite_build"], f["suite_channel"]), ("full", "testing"))


class Command(unittest.TestCase):
    def cmd(self, form=None, tools=("nodetalker", "manuals")):
        with mock.patch.object(h44, "_bld_board", lambda: {"model": "Pi 4", "zero2": False}):
            return h44._bld_suite_cmd(dict(FORM, **(form or {})), list(tools))

    def script(self, *a, **kw):
        import shlex
        parts = shlex.split(self.cmd(*a, **kw))
        self.assertEqual(parts[:2], ["bash", "-c"])
        self.assertEqual(len(parts), 3)
        return parts[2]

    def test_it_runs_under_bash_because_the_unit_job_uses_sh(self):
        self.assertTrue(self.cmd().startswith("bash -c "))

    def test_shape(self):
        c = self.script()
        self.assertTrue(c.startswith("set -o pipefail; "))
        self.assertIn("curl -fsSL 'https://raw.githubusercontent.com/kd8pgk/ASL-DVS/main/bootstrap.sh'", c)
        self.assertIn("wget -q -O - ", c)
        self.assertIn("bash -s -- --non-interactive --action=components --tools=nodetalker,manuals --build=full", c)
        self.assertIn("ASL_DVS_CHANNEL=stable AUTO_CALLSIGN=KD8PGK AUTO_NODE=652701", c)

    def test_only_valid_identity_reaches_the_shell(self):
        c = self.script({"callsign": "x; rm -rf /", "node": "1 2"})
        self.assertNotIn("AUTO_", c)
        self.assertNotIn("rm -rf", c)
        c = self.script({"suite_channel": "x; reboot"})
        self.assertIn("ASL_DVS_CHANNEL=stable", c)
        self.assertNotIn("reboot", c)

    def test_channel_is_passed(self):
        self.assertIn("ASL_DVS_CHANNEL=testing", self.script({"suite_channel": "testing"}))

    def test_the_command_is_valid_shell(self):
        import subprocess
        self.assertEqual(subprocess.run(["bash", "-n", "-c", self.cmd()], capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(["sh", "-n", "-c", self.cmd()], capture_output=True).returncode, 0)

    def test_node_talker_brings_avahi_first_and_a_failure_does_not_stop_the_suite(self):
        c = self.script(tools=("nodetalker",))
        self.assertTrue(c.startswith("set -o pipefail; dpkg -s avahi-daemon"))
        self.assertIn("apt-get install -y -qq avahi-daemon; }; if command -v curl", c)
        self.assertNotIn("avahi-daemon; } &&", c)
        self.assertLess(c.index("avahi-daemon"), c.index("curl -fsSL"))

    def test_without_node_talker_no_avahi_is_installed(self):
        self.assertNotIn("avahi", self.script(tools=("sysmon", "wifimon")))

    def test_the_avahi_step_is_valid_shell_and_runs_only_when_missing(self):
        import subprocess
        import tempfile
        c = self.script(tools=("nodetalker",))
        head = c.split("; if command -v curl")[0]
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "bin")
            os.makedirs(stub)
            log = os.path.join(d, "log")
            for name, body in (("dpkg", "exit 1"), ("apt-get", 'echo "apt-get $*" >> %s' % log)):
                with open(os.path.join(stub, name), "w") as f:
                    f.write("#!/bin/sh\n" + body + "\n")
                os.chmod(os.path.join(stub, name), 0o755)
            env = dict(os.environ, PATH=stub + os.pathsep + os.environ.get("PATH", ""))
            subprocess.run(["bash", "-c", head], env=env, capture_output=True, check=True)
            with open(log) as f:
                self.assertIn("apt-get install -y -qq avahi-daemon", f.read())
            with open(os.path.join(stub, "dpkg"), "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.remove(log)
            subprocess.run(["bash", "-c", head], env=env, capture_output=True, check=True)
            self.assertFalse(os.path.exists(log))


class Action(Tmp):
    def go(self, installed_units=(), form=None, running="", conf=True, profile="travel"):
        for u in installed_units:
            self.unit(u)
        started = []
        confpath = os.path.join(self.d.name, "asl_dvs.conf")
        if conf:
            open(confpath, "w").close()
        with mock.patch.object(h44, "_bld_form_load", lambda: dict(FORM, **(form or {}))), \
                mock.patch.object(h44, "_bld_running_job", lambda: running), \
                mock.patch.object(h44, "_BLD_ASLDVS_CONF", confpath), \
                mock.patch.object(h44, "_bld_board", lambda: {"model": "Pi 4", "zero2": False}), \
                mock.patch.object(h44, "_start_unit_job", lambda key, cmd, **kw: started.append((key, cmd)) or {"job_key": key}):
            res = h44._bld_act_install_suite({"profile": profile})
        return res, started

    ALL = ("instmon", "nodecontrol", "sysmon", "wifimon", "nodetalker", "noderecorder", "pibrary", "nodemon")

    def test_starts_one_background_job_for_the_missing_tools_only(self):
        res, started = self.go(installed_units=("nodecontrol", "sysmon", "instmon", "wifimon"))
        self.assertTrue(res["success"])
        self.assertEqual(res["job_key"], "build_travel_suite")
        self.assertEqual(len(started), 1)
        cmd = started[0][1]
        self.assertIn("--tools=nodetalker,noderecorder,pibrary,nodemon,manuals", cmd)
        for installed in ("instmon,", "dashboard", "sysmon", "wifimon"):
            self.assertNotIn(installed, cmd.split("--tools=")[1].split(" ")[0])
        self.assertNotIn("44helper", cmd.split("--tools=")[1].split(" ")[0])
        self.assertNotIn("termon", cmd)

    def test_everything_installed_starts_nothing(self):
        os.makedirs(self.docs)
        open(os.path.join(self.docs, "m.pdf"), "w").close()
        res, started = self.go(installed_units=self.ALL)
        self.assertTrue(res["success"])
        self.assertEqual(started, [])
        self.assertIn("already installed", res["message"])

    def test_refuses_while_another_build_job_runs(self):
        res, started = self.go(running="build_travel_dvs")
        self.assertFalse(res["success"])
        self.assertEqual(started, [])

    def test_a_new_node_needs_the_identity_first(self):
        res, started = self.go(form={"callsign": "", "node": ""}, conf=False)
        self.assertFalse(res["success"])
        self.assertIn("callsign and node", res["message"])
        self.assertEqual(started, [])

    def test_a_node_with_a_config_does_not(self):
        res, started = self.go(form={"callsign": "", "node": ""}, conf=True)
        self.assertTrue(res["success"])
        self.assertNotIn("AUTO_", started[0][1])

    def test_the_job_key_follows_the_tab(self):
        res, _ = self.go(profile="magic")
        self.assertEqual(res["job_key"], "build_magic_suite")

    def test_the_suite_job_counts_as_the_one_build_job(self):
        with mock.patch.dict(h44._JOBS, {"build_travel_suite": {"status": "running", "started_at": 1}}, clear=True):
            self.assertEqual(h44._bld_running_job(), "build_travel_suite")


class Page(unittest.TestCase):
    def test_both_tabs_have_the_suite_card_and_fields(self):
        for js, html, fn, pfx in ((h44._JS_BUILD, h44._render_build_panel(), "build", "bld"),
                                  (h44._JS_MAGIC, h44._render_magic_panel(), "magic", "mbx")):
            for ident in ("suite_build", "suite_channel", "suite", "suite-btn"):
                self.assertIn(f'id="{pfx}-{ident}"', html)
            self.assertIn(f"{fn}InstallSuite(this)", html)
            self.assertIn(f"function {fn}InstallSuite(", js)
            self.assertIn(f"function {fn}RenderSuite(", js)
            self.assertIn("action: 'install_suite'", js)
            self.assertIn("suite_build", js)

    def test_the_status_carries_the_suite(self):
        with open(newest("44helper_v[0-9]*.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('out["suite"] = {"tools": _bld_suite_state()', src)


if __name__ == "__main__":
    unittest.main()
