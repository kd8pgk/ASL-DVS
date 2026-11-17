import glob
import importlib.util
import json
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


spec = importlib.util.spec_from_file_location("h44_defpresets_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_defpresets_under_test"] = h44
spec.loader.exec_module(h44)


class Defaults(unittest.TestCase):
    def test_both_defaults_are_valid_and_flagged(self):
        for pid in h44._CFGR_PRESETS:
            p = h44._cfgr_default_preset(pid)
            self.assertIsNotNone(p, pid)
            self.assertTrue(p["_default"])

    def test_what_each_default_holds(self):
        t = h44._cfgr_default_preset("travel_node")
        m = h44._cfgr_default_preset("magic_box")
        self.assertEqual(sorted(n["node"] for n in t["rpt"]["nodes"]), ["1917", "1999"])
        self.assertEqual(sorted(n["node"] for n in m["rpt"]["nodes"]), ["1900", "1917", "1999"])
        self.assertNotIn("svx", t)
        self.assertEqual(m["svx"]["UsrpLogic"]["USRP_RX_PORT"], "34000")
        self.assertEqual(t["iax_port"], "4574")
        self.assertEqual(m["iax_port"], "4574")
        self.assertEqual(t["extensions"], [])
        self.assertEqual(m["modules"]["chan_usrp"], "load")

    def test_node_talkers_own_node_and_identity_are_not_in_a_default(self):
        blob = h44._CFGR_DEFAULT_PRESETS_JSON
        for never in ("1921", "AUTH_KEY", "CALLSIGN", "CALL=", "idrecording", "redacted", "KD8PGK", "password", "secret"):
            self.assertNotIn(never.lower(), blob.lower(), never)
        for pid in h44._CFGR_PRESETS:
            for n in h44._cfgr_default_preset(pid)["rpt"]["nodes"]:
                self.assertRegex(n["nodes_line"], r"^\d+ = radio@127\.0\.0\.1:4574/\d+,NONE$")


class Loading(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        for p in (mock.patch.object(h44, "_CFGR_DIR", self.d.name), mock.patch.object(h44, "_cfgr_ensure_root_dir", lambda: None)):
            p.start()
            self.addCleanup(p.stop)

    def test_nothing_saved_means_the_default(self):
        self.assertTrue(h44._cfgr_load_preset("magic_box")["_default"])

    def test_a_saved_preset_replaces_the_default(self):
        p = h44._cfgr_default_preset("travel_node")
        p.pop("_default")
        p["iax_port"] = "4580"
        path = h44._cfgr_preset_path("travel_node")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            json.dump(p, f)
        got = h44._cfgr_load_preset("travel_node")
        self.assertNotIn("_default", got)
        self.assertEqual(got["iax_port"], "4580")

    def test_a_broken_saved_file_falls_back_to_the_default(self):
        path = h44._cfgr_preset_path("travel_node")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write("{nope")
        self.assertTrue(h44._cfgr_load_preset("travel_node")["_default"])

    def test_reset_removes_the_saved_file_and_says_so(self):
        path = h44._cfgr_preset_path("magic_box")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            json.dump({"x": 1}, f)
        res = h44._cfgr_act_preset_reset({"preset": "magic_box"})
        self.assertTrue(res["success"])
        self.assertFalse(os.path.exists(path))
        self.assertIn("already in use", h44._cfgr_act_preset_reset({"preset": "magic_box"})["output"])
        self.assertFalse(h44._cfgr_act_preset_reset({"preset": "nope"})["success"])

    def test_the_action_and_buttons_exist(self):
        with open(h44.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('"preset_reset": _cfgr_act_preset_reset', src)
        self.assertIn("cfgPresetReset(this,'magic_box')", src)
        self.assertIn("cfgPresetReset(this,'travel_node')", src)

    def test_the_build_step_names_where_the_preset_comes_from(self):
        plan = ({}, [], [], [], "")
        with mock.patch.object(h44, "_cfgr_preset_plan", lambda p, port="": plan):
            st, why = h44._bld_preset_state("travel")
        self.assertEqual(st, "done")
        self.assertIn("built-in default", why)


if __name__ == "__main__":
    unittest.main()
