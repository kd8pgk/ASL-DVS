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


spec = importlib.util.spec_from_file_location("h44_fullsave_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_fullsave_under_test"] = h44
spec.loader.exec_module(h44)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.marks = os.path.join(self.d.name, "marks.json")
        self.snaps = os.path.join(self.d.name, "snaps")
        os.makedirs(self.snaps)
        self.bin = os.path.join(self.d.name, "confgetter.sh")
        for p in (mock.patch.object(h44, "_BLD_MARKS", self.marks), mock.patch.object(h44, "_FULL_SNAP_DIR", self.snaps),
                  mock.patch.object(h44, "_FULL_CONFGETTER", self.bin),
                  mock.patch.object(h44, "_bld_form_load", lambda: {"callsign": "KD8PGK"})):
            p.start()
            self.addCleanup(p.stop)


class SavePoint(Tmp):
    def test_the_name_and_it_is_made_once(self):
        self.assertRegex(h44._full_point_name("kd8pgk"), r"^Finished KD8PGK \d{4}-\d{2}-\d{2}$")
        self.assertRegex(h44._full_point_name(""), r"^Finished node ")
        self.assertTrue(h44._CFGR_NAME_RE.match(h44._full_point_name("W1AW/P")))
        made = []
        points = []

        def create(payload):
            made.append(payload["name"])
            points.append({"kind": "user", "label": payload["name"]})
            return {"success": True, "output": "created"}

        with mock.patch.object(h44, "_cfgr_act_create_point", create), mock.patch.object(h44, "_cfgr_list_points", lambda: list(points)):
            first = h44._full_save_point("KD8PGK")
            second = h44._full_save_point("KD8PGK")
        self.assertTrue(first["success"] and second["success"])
        self.assertEqual(len(made), 1)
        self.assertTrue(second["existing"])

    def test_a_failed_save_is_reported(self):
        with mock.patch.object(h44, "_cfgr_act_create_point", lambda p: {"success": False, "output": "nothing installed"}), \
                mock.patch.object(h44, "_cfgr_list_points", lambda: []):
            self.assertFalse(h44._full_save_point("KD8PGK")["success"])


class Snapshot(Tmp):
    def test_without_confgetter(self):
        res = h44._full_snapshot()
        self.assertFalse(res["success"])
        self.assertIn("not installed", res["output"])

    def test_runs_confgetter_and_names_the_new_file(self):
        with open(self.bin, "w") as f:
            f.write("#!/bin/sh\n")

        def run(argv, timeout=10):
            with open(os.path.join(self.snaps, "confgetter_node_20261117-120000.md"), "w") as f:
                f.write("x")
            return {"success": True, "output": "ok"}

        with mock.patch.object(h44, "_run_argv", run):
            res = h44._full_snapshot()
        self.assertTrue(res["success"])
        self.assertTrue(res["path"].endswith("confgetter_node_20261117-120000.md"))
        self.assertIn("confputter", res["output"])
        self.assertIn("Passwords are left out", res["output"])

    def test_a_failed_run_is_reported(self):
        with open(self.bin, "w") as f:
            f.write("x")
        with mock.patch.object(h44, "_run_argv", lambda argv, timeout=10: {"success": False, "output": "boom"}):
            self.assertFalse(h44._full_snapshot()["success"])


class BuildFinish(Tmp):
    def test_only_when_the_reboot_test_is_done(self):
        with mock.patch.object(h44, "_bld_finish_done", lambda p: False):
            for fn in (h44._bld_act_finish_save, h44._bld_act_finish_snapshot):
                res = fn({"profile": "travel"})
                self.assertFalse(res["success"])
                self.assertIn("Reboot test", res["message"])

    def test_save_records_the_name(self):
        with mock.patch.object(h44, "_bld_finish_done", lambda p: True), \
                mock.patch.object(h44, "_full_save_point", lambda c: {"success": True, "name": "Finished KD8PGK 2026-11-17", "output": "ok"}):
            res = h44._bld_act_finish_save({"profile": "magic"})
        self.assertTrue(res["success"])
        marks = h44._bld_marks_load()
        self.assertEqual(marks["finish_save_name"], "Finished KD8PGK 2026-11-17")
        self.assertIn("finish_save_at", marks)
        info = h44._bld_finish_info(True)
        self.assertEqual(info["save_name"], "Finished KD8PGK 2026-11-17")
        self.assertIn("passwords included", info["note"])

    def test_snapshot_records_the_name(self):
        with mock.patch.object(h44, "_bld_finish_done", lambda p: True), \
                mock.patch.object(h44, "_full_snapshot", lambda: {"success": True, "name": "confgetter_x_20261117-1.md", "path": "/p", "output": "ok"}):
            res = h44._bld_act_finish_snapshot({"profile": "travel"})
        self.assertTrue(res["success"])
        self.assertEqual(h44._bld_marks_load()["finish_snapshot_name"], "confgetter_x_20261117-1.md")

    def test_the_status_carries_the_finish_info_and_never_a_password(self):
        info = h44._bld_finish_info(False)
        self.assertFalse(info["done"])
        self.assertNotIn("password:", " ".join(str(v) for v in info.values()).lower())

    def test_actions_are_registered(self):
        for k in ("finish_save", "finish_snapshot"):
            self.assertIn(k, h44._BLD_ACTIONS)
        for k in ("full_save", "full_snapshot"):
            self.assertIn(k, h44._CFGR_ACTIONS)

    def test_the_config_tab_actions_carry_the_note(self):
        with mock.patch.object(h44, "_full_save_point", lambda c: {"success": True, "name": "n", "output": "ok"}):
            res = h44._cfgr_act_full_save({})
        self.assertIn("A snapshot is the same files", res["output"])


class Page(unittest.TestCase):
    def test_the_cards_and_the_note(self):
        for js in (h44._JS_BUILD, h44._JS_MAGIC):
            self.assertIn("FinishSave", js)
            self.assertIn("finish_snapshot", js)
        self.assertIn('id="@P@-finish"', h44._BLD_PANEL_TMPL)
        with open(h44.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("Save the full config", src)
        self.assertIn("cfgFullSnapshot", src)
        self.assertIn("They are not the same thing", src)


if __name__ == "__main__":
    unittest.main()
