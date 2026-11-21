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


spec = importlib.util.spec_from_file_location("h44_values_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_values_under_test"] = h44
spec.loader.exec_module(h44)

BASE = dict(h44._BLD_DEFAULT, callsign="KD8PGK", node="652701", dmr_id="3123456", mode="none")


def row(fid, value, groups=(), label="x", n=0):
    return {"fid": fid, "groups": list(groups), "value": value, "rid": f"{fid}#{n}", "label": label, "file": "/f"}


def scan(rows, ami="match"):
    return {"rows": rows, "groups": {"ami": {"state": ami}}}


class Form(unittest.TestCase):
    def errs(self, **kw):
        return h44._bld_form_errors(dict(BASE, **kw), [])

    def test_everything_new_is_optional(self):
        self.assertEqual(self.errs(), {})

    def test_good_values(self):
        good = dict(pw_node="abc123", pw_bm="pa55word", pw_ami="s3cret", pw_el="elpw", el_node="123456", sysop="Mike", location="Toledo, OH",
                    qth="Home", lat="41.65", lon="-83.54", ta="Mike", pw_reflector="refl", pw_allmon="x1", pw_tgif="t", pw_iax="i",
                    pw_ircddb="d", pw_ircddb_remote="r")
        self.assertEqual(self.errs(**good), {})

    def test_bad_values_are_named(self):
        for k, v in (("pw_node", "has space"), ("pw_ami", "a=b"), ("el_node", "abc"), ("lat", "99"), ("lon", "-200"), ("ta", "a;b"),
                     ("pw_reflector", "a#b"), ("sysop", 'a"b')):
            self.assertIn(k, self.errs(lat="1", lon="1", **{k: v}) if k not in ("lat", "lon") else self.errs(**{k: v, "lat" if k == "lon" else "lon": "1"}), k)

    def test_latitude_and_longitude_come_together(self):
        self.assertIn("lon", self.errs(lat="41.6"))
        self.assertIn("lat", self.errs(lon="-83.5"))

    def test_fields_on_both_tabs(self):
        for k in h44._BLD_VALUE_FIELDS:
            self.assertIn(k, h44._BLD_FIELDS)
            self.assertIn(k, h44._BLD_FIELDS_MAGIC)
            self.assertIn("-" + k, h44._BLD_PANEL_TMPL + "".join(h44._BLD_SVX_ROWS))
            if k != "pw_reflector":
                self.assertIn(k, h44._BLD_FIELDS_TRAVEL)
        self.assertNotIn("pw_reflector", h44._BLD_FIELDS_TRAVEL)

    def test_the_form_round_trips_with_the_clear_values(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(h44, "_BLD_FILE", os.path.join(d, "build.json")):
                h44._bld_form_write(h44._bld_form_clean(dict(BASE, pw_node="Open-Sesame", sysop="Mike")))
                got = h44._bld_form_load()
                self.assertEqual(got["pw_node"], "Open-Sesame")
                self.assertEqual(oct(os.stat(os.path.join(d, "build.json")).st_mode & 0o777), "0o600")


class Locator(unittest.TestCase):
    def test_known_points(self):
        self.assertEqual(h44._bld_locator("41.65", "-83.54")[:4], "EN81")
        self.assertEqual(h44._bld_locator("51.5", "-0.12")[:4], "IO91")
        self.assertEqual(h44._bld_locator("", ""), "")
        self.assertEqual(h44._bld_locator("x", "1"), "")


class Plan(unittest.TestCase):
    def plan(self, step, form, rows, ami="match"):
        with mock.patch.object(h44, "_cfgr_identity_scan", lambda: scan(rows, ami)):
            return h44._bld_values_plan(step, dict(BASE, **form))

    def test_a_group_password_is_set_when_it_differs_or_is_missing(self):
        todo, _a, _b = self.plan("passwords", {"pw_node": "NEW"}, [row("savenode_pw", "old", ["node_pw"])])
        self.assertEqual(todo, [("ASL node password", {"group": "node_pw", "value": "NEW"})])
        todo, _a, _b = self.plan("passwords", {"pw_node": "NEW"}, [row("savenode_pw", "NEW", ["node_pw"])])
        self.assertEqual(todo, [])
        todo, _a, _b = self.plan("passwords", {"pw_node": "NEW"}, [])
        self.assertEqual(len(todo), 1)

    def test_alone_rows_are_set_one_by_one(self):
        rows = [row("el_pwd", "old", label="EchoLink password"), row("svx_el_pw", "old", label="SvxLink EchoLink password"),
                row("mb_dmr_pw", "bm", label="DMR network password")]
        todo, _a, _b = self.plan("passwords", {"pw_el": "elnew", "pw_bm": "bm"}, rows)
        got = sorted(t[1].get("rid", t[1].get("group")) for t in todo)
        self.assertEqual(got, ["bm_pw", "el_pwd#0", "svx_el_pw#0"])

    def test_missing_rows_are_named_not_fatal(self):
        _t, absent, _b = self.plan("passwords", {"pw_reflector": "k"}, [])
        self.assertEqual(absent, ["SvxLink reflector password"])

    def test_location_uses_the_computed_locator(self):
        rows = [row("svx_ni_loc", "AA00", n=0), row("svx_ni_lat", "0"), row("svx_ni_lon", "0")]
        todo, _a, _b = self.plan("location", {"lat": "41.65", "lon": "-83.54"}, rows)
        values = {t[1]["rid"].split("#")[0]: t[1]["value"] for t in todo}
        self.assertTrue(values["svx_ni_loc"].lower().startswith("en81"))
        self.assertEqual(values["svx_ni_lat"], "41.65")

    def test_blank_form_values_change_nothing(self):
        todo, _a, blank = self.plan("passwords", {}, [row("el_pwd", "old")])
        self.assertEqual(todo, [])
        self.assertIn("pw_el", blank)


class State(unittest.TestCase):
    def state(self, step, form, rows, profile="travel", marks=None):
        with mock.patch.object(h44, "_cfgr_identity_scan", lambda: scan(rows)), mock.patch.object(h44, "_bld_marks_load", lambda: marks or {}):
            return h44._bld_values_state(step, dict(BASE, **form), profile)

    def test_passwords_states(self):
        st, why = self.state("passwords", {}, [])
        self.assertEqual(st, "warn")
        self.assertIn("ASL node password", why)
        self.assertEqual(self.state("passwords", {"pw_node": "a", "pw_bm": "b"}, [row("savenode_pw", "a", ["node_pw"]), row("stfu_pw", "b", ["bm_pw"]),
                                                                              row("mb_dmr_pw", "b")])[0], "done")
        st, why = self.state("passwords", {"pw_node": "new"}, [row("savenode_pw", "old", ["node_pw"])])
        self.assertEqual(st, "todo")
        self.assertNotIn("new", why.replace("Not in the files yet: ASL node password.", ""))

    def test_magic_also_asks_for_the_reflector_password(self):
        self.assertIn("reflector", self.state("passwords", {"pw_node": "a", "pw_bm": "b"}, [row("savenode_pw", "a", ["node_pw"]), row("stfu_pw", "b", ["bm_pw"]),
                                                                                           row("mb_dmr_pw", "b")], "magic")[1])

    def test_allmon_is_open_until_set(self):
        rows = []
        self.assertEqual(self.state("passwords", {"pw_allmon": "x"}, rows)[0], "todo")
        self.assertNotEqual(self.state("passwords", {"pw_allmon": "x"}, rows, marks={"allmon_set_at": 5})[0], "todo")

    def test_location_blank_is_done(self):
        self.assertEqual(self.state("location", {}, [])[0], "done")
        self.assertEqual(self.state("location", {"sysop": "Mike"}, [row("svx_el_sysop", "old")])[0], "todo")


class Run(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.marks = os.path.join(self.d.name, "marks.json")
        self.file = os.path.join(self.d.name, "build.json")
        for p in (mock.patch.object(h44, "_BLD_MARKS", self.marks), mock.patch.object(h44, "_BLD_FILE", self.file)):
            p.start()
            self.addCleanup(p.stop)

    def run_it(self, form, rows, preview=False, ami="match", id_set=None, which="/usr/bin/allmon3-passwd", argv=None):
        calls = []

        def fake_set(payload, apply):
            calls.append((dict(payload), apply))
            return (id_set or (lambda p: {"success": True, "output": "ok " + p["value"]}))(payload)

        def fake_run(args, timeout=10):
            (argv if argv is not None else []).append(args)
            return {"success": True, "output": "done"}

        f = dict(BASE, **form)
        h44._bld_form_write(f)
        with mock.patch.object(h44, "_cfgr_identity_scan", lambda: scan(rows, ami)), mock.patch.object(h44, "_cfgr_act_id_set", fake_set), \
                mock.patch.object(h44.shutil, "which", lambda n: which), mock.patch.object(h44, "_run_argv", fake_run):
            ok, lines = h44._bld_run_values("passwords", f, preview)
        return ok, lines, calls

    def test_preview_changes_nothing(self):
        _ok, _l, calls = self.run_it({"pw_node": "new"}, [row("savenode_pw", "old", ["node_pw"])], preview=True)
        self.assertTrue(calls and all(c[1] is False for c in calls))

    def test_values_never_reach_the_output(self):
        _ok, lines, _c = self.run_it({"pw_node": "TOPSECRETVALUE"}, [row("savenode_pw", "old", ["node_pw"])])
        self.assertNotIn("TOPSECRETVALUE", "\n".join(lines))
        self.assertIn("<hidden>", "\n".join(lines))

    def test_a_missing_ami_secret_is_generated_and_kept_in_the_form(self):
        _ok, lines, calls = self.run_it({}, [], ami="not set")
        gen = h44._bld_form_load()["pw_ami"]
        self.assertEqual(len(gen), 24)
        self.assertEqual(calls[0][0], {"group": "ami", "value": gen})
        self.assertTrue(any("generated" in ln for ln in lines))

    def test_an_existing_ami_secret_is_not_replaced(self):
        _ok, _l, calls = self.run_it({}, [], ami="match")
        self.assertEqual(calls, [])
        self.assertEqual(h44._bld_form_load()["pw_ami"], "")

    def test_allmon_is_set_without_a_shell_then_forgotten(self):
        argv = []
        ok, lines, _c = self.run_it({"pw_allmon": "AdminPw1"}, [], argv=argv)
        self.assertTrue(ok)
        self.assertEqual(argv, [["allmon3-passwd", "--password", "AdminPw1", "admin"]])
        self.assertNotIn("AdminPw1", "\n".join(lines))
        self.assertEqual(h44._bld_form_load()["pw_allmon"], "")
        self.assertIn("allmon_set_at", h44._bld_marks_load())

    def test_allmon_without_the_tool_fails_and_keeps_waiting(self):
        ok, _l, _c = self.run_it({"pw_allmon": "AdminPw1"}, [], which=None)
        self.assertFalse(ok)
        self.assertEqual(h44._bld_form_load()["pw_allmon"], "AdminPw1")

    def test_a_failed_setter_fails_the_step(self):
        ok, _l, _c = self.run_it({"pw_node": "n"}, [row("savenode_pw", "o", ["node_pw"])], id_set=lambda p: {"success": False, "output": "bad"})
        self.assertFalse(ok)


class Wipe(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        p = mock.patch.object(h44, "_BLD_FILE", os.path.join(self.d.name, "build.json"))
        p.start()
        self.addCleanup(p.stop)

    def test_only_the_passwords_go(self):
        h44._bld_form_write(h44._bld_form_clean(dict(BASE, pw_node="a", pw_ami="b", pw_allmon="c", sysop="Mike", el_node="99", qth="Home")))
        self.assertTrue(h44._bld_wipe_secrets())
        got = h44._bld_form_load()
        for k in h44._BLD_SECRET_FIELDS:
            self.assertEqual(got[k], "", k)
        for k, v in (("callsign", "KD8PGK"), ("node", "652701"), ("sysop", "Mike"), ("el_node", "99"), ("qth", "Home")):
            self.assertEqual(got[k], v)
        self.assertFalse(h44._bld_wipe_secrets())

    def test_the_clear_action(self):
        h44._bld_form_write(h44._bld_form_clean(dict(BASE, pw_node="a")))
        self.assertIn("removed", h44._bld_act_clear_saved({})["message"])
        self.assertEqual(h44._bld_form_load()["pw_node"], "")
        self.assertIn("No passwords", h44._bld_act_clear_saved({})["message"])

    def test_the_status_wipes_when_the_reboot_test_is_done(self):
        h44._bld_form_write(h44._bld_form_clean(dict(BASE, pw_node="a")))
        with mock.patch.object(h44, "_BS_DIR", os.path.join(self.d.name, "saves")), mock.patch.object(h44, "_bld_reboot_state", lambda *a: ("done", "ok")), mock.patch.object(h44, "_bld_machine", lambda: []), \
                mock.patch.object(h44, "_detect_installed_products", lambda force=False: []), mock.patch.object(h44, "_bld_usb_cards", lambda: []), \
                mock.patch.object(h44, "_wg0_interface_present", lambda: False), mock.patch.object(h44, "_firewalld_zone_info_cached", lambda: None), \
                mock.patch.object(h44, "status_boot_order", lambda: {"done": True, "missing": []}), \
                mock.patch.object(h44, "_cfgr_usrp_pairs", lambda override=None: ([], [])), mock.patch.object(h44, "_pn_status", lambda: {"available": False}), \
                mock.patch.object(h44, "_cfgr_snap_dir", lambda k, sid="": "x"), mock.patch.object(h44, "_cfgr_read_manifest", lambda d: None), \
                mock.patch.object(h44, "_cfgr_identity_scan", lambda: {"rows": [], "groups": {}}), mock.patch.object(h44, "_cfgr_text", lambda p: None):
            st = h44.build_build_status()
        self.assertEqual(st["form"]["pw_node"], "")
        self.assertEqual(h44._bld_form_load()["pw_node"], "")
        saves = os.path.join(self.d.name, "saves")
        kept = [n for n in os.listdir(saves) if n.startswith("build-save-")]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(saves, kept[0])) as f:
            self.assertEqual(json.load(f)["values"]["pw_node"], "a")


class DoneWrites(unittest.TestCase):
    def status_at_done(self):
        with mock.patch.object(h44, "_BS_DIR", os.path.join(self.d.name, "saves")), mock.patch.object(h44, "_bld_reboot_state", lambda *a: ("done", "ok")), \
                mock.patch.object(h44, "_bld_machine", lambda: []), mock.patch.object(h44, "_detect_installed_products", lambda force=False: []), \
                mock.patch.object(h44, "_bld_usb_cards", lambda: []), mock.patch.object(h44, "_wg0_interface_present", lambda: False), \
                mock.patch.object(h44, "_firewalld_zone_info_cached", lambda: None), \
                mock.patch.object(h44, "status_boot_order", lambda: {"done": True, "missing": []}), \
                mock.patch.object(h44, "_cfgr_usrp_pairs", lambda override=None: ([], [])), mock.patch.object(h44, "_pn_status", lambda: {"available": False}), \
                mock.patch.object(h44, "_cfgr_snap_dir", lambda k, sid="": "x"), mock.patch.object(h44, "_cfgr_read_manifest", lambda d: None), \
                mock.patch.object(h44, "_cfgr_identity_scan", lambda: {"rows": [], "groups": {}}), mock.patch.object(h44, "_cfgr_text", lambda p: None):
            h44.build_build_status()
        return os.path.join(self.d.name, "saves")

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        p = mock.patch.object(h44, "_BLD_FILE", os.path.join(self.d.name, "build.json"))
        p.start()
        self.addCleanup(p.stop)

    def test_no_passwords_and_no_files_writes_both_once(self):
        h44._bld_form_write(h44._bld_form_clean(dict(BASE, sysop="Mike")))
        saves = self.status_at_done()
        self.assertEqual(len(os.listdir(saves)), 2)
        self.status_at_done()
        self.assertEqual(len(os.listdir(saves)), 2)

    def test_after_the_wipe_nothing_new_is_written(self):
        h44._bld_form_write(h44._bld_form_clean(dict(BASE, pw_node="a")))
        saves = self.status_at_done()
        before = sorted(os.listdir(saves))
        self.status_at_done()
        self.assertEqual(sorted(os.listdir(saves)), before)


class Prefill(unittest.TestCase):
    CAT = {"bookworm": {"std": [
        {"id": "configure_node_identity", "fields": [{"id": "callsign", "type": "text", "default": ""}, {"id": "dmrid", "type": "text", "default": ""},
                                                       {"id": "password", "type": "password", "default": ""}]},
        {"id": "usrp_refl_test", "fields": [{"id": "callsign", "type": "text", "default": ""}, {"id": "refl_key", "type": "text", "default": ""}]},
        {"id": "usrp_refl_conn", "fields": [{"id": "refl_key", "type": "text", "default": ""}, {"id": "refl_host", "type": "text", "default": ""},
                                            {"id": "refl_port", "type": "text", "default": "5300"}]},
        {"id": "allmon3_set_admin", "fields": [{"id": "username", "type": "text", "default": "admin"}, {"id": "password", "type": "password", "default": ""}]},
        {"id": "m17_asterisk_conf", "fields": [{"id": "node", "type": "text", "default": "1917"}]},
    ]}}

    def fill(self, **form):
        return h44._bld_prefill(self.CAT, dict(BASE, **form))["bookworm"]["std"]

    def test_known_fields_are_filled_where_empty(self):
        steps = self.fill(pw_bm="bmpw", pw_reflector="rk", svx_host="refl.example.org", svx_port="35300", pw_allmon="ap")
        f = {s["id"]: {x["id"]: x["default"] for x in s["fields"]} for s in steps}
        self.assertEqual(f["configure_node_identity"], {"callsign": "KD8PGK", "dmrid": "3123456", "password": "bmpw"})
        self.assertEqual(f["usrp_refl_conn"], {"refl_key": "rk", "refl_host": "refl.example.org", "refl_port": "5300"})
        self.assertEqual(f["allmon3_set_admin"], {"username": "admin", "password": "ap"})

    def test_the_test_reflector_is_not_filled_with_the_real_one(self):
        f = {s["id"]: {x["id"]: x["default"] for x in s["fields"]} for s in self.fill(pw_reflector="rk")}
        self.assertEqual(f["usrp_refl_test"]["refl_key"], "")

    def test_nothing_entered_changes_nothing(self):
        before = json.dumps(self.CAT)
        out = h44._bld_prefill(self.CAT, dict(h44._BLD_DEFAULT))
        self.assertEqual(json.dumps(out), before)

    def test_the_catalogue_itself_is_never_changed(self):
        before = json.dumps(self.CAT)
        self.fill(pw_bm="x")
        self.assertEqual(json.dumps(self.CAT), before)

    def test_the_real_routes_return_filled_json(self):
        with mock.patch.object(h44, "_bld_form_load", lambda: dict(BASE)):
            body = json.loads(h44._route_dvswitch_script({})[2])
        blob = json.dumps(body)
        self.assertIn("KD8PGK", blob)


class Leaks(unittest.TestCase):
    def test_the_report_has_no_passwords(self):
        form = dict(BASE, pw_node="LEAKCHECK1", pw_bm="LEAKCHECK2", pw_reflector="LEAKCHECK3", pw_allmon="LEAKCHECK4")
        st = {"form": form, "errors": {}, "stages": [{"id": "preflight", "label": "Preflight", "state": "done", "detail": ""}], "machine": [],
              "profile": "travel", "radio": {"cards": []}, "addrs": [], "tunnel_kind": "", "board": {"model": "Pi"}, "checked_at": "x"}
        with mock.patch.object(h44, "build_build_status", lambda profile="travel": st):
            text = h44.build_build_report("travel")
        self.assertNotIn("LEAKCHECK", text)


if __name__ == "__main__":
    unittest.main()
