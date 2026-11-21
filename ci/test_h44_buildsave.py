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


spec = importlib.util.spec_from_file_location("h44_buildsave_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_buildsave_under_test"] = h44
spec.loader.exec_module(h44)

FORM = dict(h44._BLD_DEFAULT, callsign="KD8PGK", node="652701", dmr_id="3123456", mode="half", iax_port="4574", sysop="Mike", location="Toledo, OH",
            pw_node="NodePw1", pw_bm="BmPw1", pw_ami="AmiPw1", pw_allmon="AllmonPw1", pw_el="ElPw1", pw_reflector="ReflPw1", el_enable="1", el_call="KD8PGK-L",
            stfu_master="3104.master.brandmeister.network", usb="1-1.2")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.dir = os.path.join(self.d.name, "saves")
        self.form = dict(FORM)
        for p in (mock.patch.object(h44, "_BS_DIR", self.dir), mock.patch.object(h44, "_bld_form_load", lambda: dict(self.form))):
            p.start()
            self.addCleanup(p.stop)

    def read(self, name):
        with open(os.path.join(self.dir, name)) as f:
            return json.load(f)


class Files(Tmp):
    def test_both_files_are_written_and_private(self):
        names, err = h44._bs_write("travel")
        self.assertEqual(err, "")
        self.assertEqual(len(names), 2)
        kinds = sorted(re.match(r"build-(\w+)-", n).group(1) for n in names)
        self.assertEqual(kinds, ["save", "snapshot"])
        for n in names:
            self.assertEqual(oct(os.stat(os.path.join(self.dir, n)).st_mode & 0o777), "0o600")
        self.assertEqual(oct(os.stat(self.dir).st_mode & 0o777), "0o700")

    def test_the_snapshot_has_no_password_and_the_save_has_them(self):
        names, _ = h44._bs_write("travel")
        snap = next(n for n in names if "snapshot" in n)
        save = next(n for n in names if "save-" in n and "snapshot" not in n)
        sv = self.read(snap)["values"]
        for k in h44._BLD_SECRET_FIELDS:
            self.assertNotIn(k, sv, k)
        for secret in ("NodePw1", "BmPw1", "AmiPw1", "ElPw1", "ReflPw1", "AllmonPw1"):
            with open(os.path.join(self.dir, snap)) as f:
                self.assertNotIn(secret, f.read())
        full = self.read(save)["values"]
        self.assertEqual(full["pw_node"], "NodePw1")
        self.assertEqual(full["pw_reflector"], "ReflPw1")

    def test_the_allmon_password_and_the_usb_pick_are_never_saved(self):
        names, _ = h44._bs_write("travel")
        for n in names:
            values = self.read(n)["values"]
            self.assertNotIn("pw_allmon", values)
            self.assertNotIn("usb", values)
            with open(os.path.join(self.dir, n)) as f:
                self.assertNotIn("AllmonPw1", f.read())

    def test_the_document_shape(self):
        names, _ = h44._bs_write("magic")
        doc = self.read(names[0])
        self.assertEqual(doc["format"], "44helper-build")
        self.assertEqual(doc["version"], 1)
        self.assertEqual(doc["profile"], "magic")
        self.assertEqual(doc["values"]["callsign"], "KD8PGK")

    def test_unchanged_values_write_nothing_twice(self):
        h44._bs_write("travel")
        names, err = h44._bs_write("travel")
        self.assertEqual((names, err), ([], ""))
        self.assertEqual(len(h44._bs_list()), 2)
        self.form["sysop"] = "Mike M"
        names, _ = h44._bs_write("travel")
        self.assertEqual(len(names), 2)

    def test_only_the_newest_five_of_each_are_kept(self):
        for i in range(7):
            self.form["sysop"] = f"S{i}"
            with mock.patch.object(h44.time, "strftime", lambda f, i=i: f"20261117-00000{i}"):
                h44._bs_write("travel")
        files = h44._bs_list()
        self.assertEqual(len([f for f in files if f["kind"] == "save"]), 5)
        self.assertEqual(len([f for f in files if f["kind"] == "snapshot"]), 5)

    def test_a_write_error_is_reported(self):
        with mock.patch.object(h44.os, "makedirs", side_effect=OSError("read-only")):
            names, err = h44._bs_write("travel")
        self.assertEqual(names, [])
        self.assertIn("Could not write", err)


class Names(Tmp):
    def test_only_the_listed_pattern_is_served(self):
        names, _ = h44._bs_write("travel")
        self.assertIsNotNone(h44._bs_path(names[0]))
        for bad in ("../etc/passwd", "build-save-X.json", "x/../build-save-KD8PGK-20261117-000000.json", "", None, 5,
                    "build-save-KD8PGK-20261117-000000.json.tmp"):
            self.assertIsNone(h44._bs_path(bad), bad)

    def test_a_symlink_is_not_served(self):
        os.makedirs(self.dir)
        target = os.path.join(self.d.name, "secret.json")
        with open(target, "w") as f:
            f.write("{}")
        os.symlink(target, os.path.join(self.dir, "build-save-KD8PGK-20261117-000000.json"))
        self.assertIsNone(h44._bs_path("build-save-KD8PGK-20261117-000000.json"))
        self.assertEqual(h44._bs_list(), [])

    def test_the_download_route(self):
        names, _ = h44._bs_write("travel")
        code, ctype, body = h44._route_build_save({"name": [names[0]]})
        self.assertEqual((code, ctype), (200, "application/json"))
        self.assertEqual(json.loads(body)["format"], "44helper-build")
        self.assertEqual(h44._route_build_save({"name": ["../../etc/shadow"]})[0], 404)
        self.assertIn("/api/build/save", h44._GET_ROUTES)


class Loading(Tmp):
    def doc(self, kind="save", **over):
        d = {"format": "44helper-build", "version": 1, "kind": kind, "profile": "magic",
             "values": {"callsign": "w1aw", "node": "123456", "dmr_id": "3111111", "pw_node": "p1", "sysop": "Ann", "mode": "none"}}
        d.update(over)
        return json.dumps(d)

    def load(self, text, profile="travel"):
        return h44._bld_act_save_load({"profile": profile, "text": text})

    def test_a_save_fills_everything_including_passwords(self):
        res = self.load(self.doc("save"))
        self.assertTrue(res["success"], res)
        v = res["values"]
        self.assertEqual((v["callsign"], v["node"], v["pw_node"], v["sysop"], v["mode"]), ("W1AW", "123456", "p1", "Ann", "none"))
        self.assertEqual(res["kind"], "save")

    def test_a_snapshot_never_touches_the_password_fields(self):
        res = self.load(self.doc("snapshot"))
        self.assertTrue(res["success"])
        for k in h44._BLD_SECRET_FIELDS:
            self.assertNotIn(k, res["values"])
        self.assertTrue(any("no passwords" in n for n in res["notes"]))
        self.assertEqual(res["values"]["callsign"], "W1AW")

    def test_fields_the_tab_does_not_have_are_left_out_with_a_note(self):
        d = json.loads(self.doc("save"))
        d["values"].update(svx_host="refl.example.org", pw_reflector="rk")
        res = self.load(json.dumps(d), "travel")
        self.assertNotIn("svx_host", res["values"])
        self.assertTrue(any("svx_host" in n for n in res["notes"]))
        res = self.load(json.dumps(d), "magic")
        self.assertEqual(res["values"]["svx_host"], "refl.example.org")

    def test_unknown_keys_are_ignored_and_allmon_is_dropped(self):
        d = json.loads(self.doc("save"))
        d["values"].update(future_field="x", pw_allmon="AllmonPw1", usb="1-1")
        res = self.load(json.dumps(d))
        self.assertTrue(res["success"])
        self.assertNotIn("future_field", res["values"])
        self.assertNotIn("pw_allmon", res["values"])
        self.assertNotIn("usb", res["values"])
        self.assertTrue(any("future_field" in n for n in res["notes"]))

    def test_refusals(self):
        for text, why in (("not json", "JSON"), ('{"a": 1}', "not a Build Save"), (self.doc(kind="other"), "readable values"),
                          (self.doc(version=2), "not a Build Save"), (self.doc(format="x"), "not a Build Save"),
                          ("x" * 40000, "too large"), (json.dumps([1]), "not a Build Save")):
            res = self.load(text)
            self.assertFalse(res["success"], why)
            self.assertIn(why, res["message"])

    def test_bad_values_are_named_and_nothing_is_returned(self):
        d = json.loads(self.doc("save"))
        d["values"].update(dmr_id="12", el_call="NOPE", pw_node="has space")
        res = self.load(json.dumps(d))
        self.assertFalse(res["success"])
        for k in ("dmr_id", "el_call", "pw_node"):
            self.assertIn(k, res["message"])
        self.assertNotIn("values", res)

    def test_non_string_values_are_refused(self):
        d = json.loads(self.doc("save"))
        d["values"]["node"] = 123456
        self.assertFalse(self.load(json.dumps(d))["success"])

    def test_a_round_trip_through_the_files_on_the_node(self):
        names, _ = h44._bs_write("magic")
        save = next(n for n in names if "snapshot" not in n)
        res = h44._bld_act_save_load({"profile": "magic", "name": save})
        self.assertTrue(res["success"], res)
        for k in ("callsign", "node", "dmr_id", "iax_port", "sysop", "location", "pw_node", "pw_bm", "pw_ami", "pw_el", "pw_reflector", "el_call"):
            self.assertEqual(res["values"][k], FORM[k], k)
        self.assertNotIn("pw_allmon", res["values"])
        snap = next(n for n in names if "snapshot" in n)
        res = h44._bld_act_save_load({"profile": "magic", "name": snap})
        self.assertNotIn("pw_node", res["values"])
        self.assertEqual(res["values"]["callsign"], "KD8PGK")

    def test_a_file_that_is_not_on_this_node(self):
        self.assertFalse(h44._bld_act_save_load({"profile": "travel", "name": "build-save-X-20261117-000000.json"})["success"])


class Steps(Tmp):
    def test_the_actions_and_the_status(self):
        for k in ("save_write", "save_load"):
            self.assertIn(k, h44._BLD_ACTIONS)
        res = h44._bld_act_save_write({"profile": "travel"})
        self.assertTrue(res["success"])
        again = h44._bld_act_save_write({"profile": "travel"})
        self.assertIn("Nothing new", again["message"])

    def test_the_wipe_writes_a_build_save_first(self):
        self.assertIn("passwords included", h44._BS_NOTE)
        names, _ = h44._bs_write("travel")
        self.assertTrue(names)

    def test_the_card_and_functions_are_on_both_tabs(self):
        for js in (h44._JS_BUILD, h44._JS_MAGIC):
            for fn in ("SaveNow", "SaveLoad", "SaveFile", "SaveDownload", "RenderSaves"):
                self.assertIn(fn, js)
            self.assertIn("contains your passwords", js)
        self.assertIn('id="@P@-saves"', h44._BLD_PANEL_TMPL)

    def test_the_whole_file_full_save_of_0_1_63_is_gone(self):
        for name in ("_full_save_point", "_full_snapshot", "_cfgr_act_full_save", "_bld_act_finish_save"):
            self.assertFalse(hasattr(h44, name), name)
        with open(h44.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("confgetter.sh", src)
        self.assertNotIn("Save the full config", src)

    def test_the_config_tab_names_match(self):
        with open(h44.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("Create Config Save", src)
        self.assertIn('label="Config Saves"', src)
        self.assertNotIn("Create save point", src)


if __name__ == "__main__":
    unittest.main()
