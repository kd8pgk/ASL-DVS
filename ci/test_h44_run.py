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


spec = importlib.util.spec_from_file_location("h44_run_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_run_under_test"] = h44
spec.loader.exec_module(h44)

FORM = {"mode": "half", "callsign": "KD8PGK", "node": "652701", "dmr_id": "3123456", "nxdn_id": "12345",
        "m17_node": "1917", "usb": "1-1.3", "bypass": "", "svx_use": "bridge", "svx_host": "", "svx_port": "",
        "svx_tg": "0", "svx_mon": ""}
CARDS = [{"card": 1, "name": "A", "usbid": "0d8c:013c", "devstr": "1-1.2", "radio_chip": "C-Media"},
         {"card": 2, "name": "B", "usbid": "0c76:1607", "devstr": "1-1.3", "radio_chip": "JMTek"}]
USB = """[general]
foo = 1

[652701](node-main,hotspotradio-usb)
devstr =
rxboost = 0

[1999]
devstr = keep
"""


def status(state="todo", sid="apply_asl3", errors=None, form=None):
    return {"form": dict(FORM, **(form or {})), "errors": errors or {}, "radio": {"cards": CARDS},
            "stages": [{"id": sid, "label": "Label " + sid, "state": state, "detail": "why"}]}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.p = lambda n: os.path.join(self.d.name, n)

    def write(self, name, text):
        path = self.p(name)
        with open(path, "w") as f:
            f.write(text)
        return path


class DevstrEdit(unittest.TestCase):
    def test_replaces_only_this_nodes_line(self):
        out = h44._bld_devstr_edit(USB, "652701", "1-1.3")
        self.assertIn("[652701](node-main,hotspotradio-usb)\ndevstr = 1-1.3\nrxboost = 0", out)
        self.assertIn("[1999]\ndevstr = keep", out)
        self.assertTrue(out.endswith("\n"))

    def test_inserts_when_absent(self):
        out = h44._bld_devstr_edit("[652701]\nrxboost = 0\n", "652701", "1-1.3")
        self.assertEqual(out, "[652701]\ndevstr = 1-1.3\nrxboost = 0\n")

    def test_unknown_node(self):
        self.assertIsNone(h44._bld_devstr_edit(USB, "111111", "1-1.3"))

    def test_no_trailing_newline_kept(self):
        self.assertFalse(h44._bld_devstr_edit("[652701]\ndevstr =", "652701", "x").endswith("\n"))


class GroupFilter(unittest.TestCase):
    def ready(self, groups, errors=()):
        m = {"files": [{"path": "/a", "group": "asl3"}, {"path": "/b", "group": "dvs"}]}
        rows = [{"path": "/a", "group": "asl3", "status": "changed", "data": b""},
                {"path": "/b", "group": "dvs", "status": "changed", "data": b""}]
        payload = {"groups": groups} if groups is not None else {}
        with mock.patch.object(h44, "_fcr_load", lambda: (m, {})), \
                mock.patch.object(h44, "_fcr_tokens", lambda m_, p: ({}, "")), \
                mock.patch.object(h44, "_fcr_group_state", lambda: {}), \
                mock.patch.object(h44, "_fcr_plan", lambda m_, t, s: (list(rows), list(errors))):
            return h44._fcr_ready(payload)

    def test_no_filter_keeps_everything(self):
        self.assertEqual([r["path"] for r in self.ready(None)[3]], ["/a", "/b"])

    def test_filter_to_one_group(self):
        self.assertEqual([r["path"] for r in self.ready(["dvs"])[3]], ["/b"])

    def test_other_groups_errors_do_not_block(self):
        self.assertEqual(self.ready(["asl3"], ["/b: damaged"])[4], "")
        self.assertIn("damaged", self.ready(["dvs"], ["/b: damaged"])[4])


class Refusals(unittest.TestCase):
    def run_stage(self, st, **payload):
        with mock.patch.object(h44, "build_build_status", lambda profile="travel": st):
            return h44._bld_act_run_stage(dict({"stage": "apply_asl3", "profile": "travel"}, **payload))

    def test_unknown_and_unrunnable(self):
        self.assertFalse(self.run_stage(status(), stage="tunnel")["success"])
        self.assertFalse(self.run_stage(status(), stage="nope")["success"])
        self.assertIn("no preview", self.run_stage(status(sid="boot"), stage="boot", preview=True)["message"])

    def test_locked_done_and_missing(self):
        self.assertIn("waits", self.run_stage(status("locked"))["message"])
        self.assertIn("Nothing to do", self.run_stage(status("done"))["message"])
        self.assertIn("not part", self.run_stage(status(sid="boot"))["message"])

    def test_apply_needs_a_clean_form(self):
        r = self.run_stage(status(errors={"node": "required"}))
        self.assertFalse(r["success"])
        self.assertIn("node", r["message"])

    def test_every_runnable_stage_is_known(self):
        ids = {i for m in ("half", "split", "full") for p in ("travel", "magic") for i, _ in h44._bld_stage_defs(m, p)}
        self.assertTrue(h44._BLD_RUNNABLE <= ids)
        self.assertTrue(h44._BLD_PREVIEWABLE <= h44._BLD_RUNNABLE)
        for never in ("preflight", "half", "fullx", "svx_reflector", "reboot"):
            self.assertNotIn(never, h44._BLD_RUNNABLE)


class Dispatch(Tmp):
    def go(self, sid, preview=False, cfg=None, staged=True, **extra):
        calls = []

        def fake_cfg(action, payload=None):
            calls.append((action, dict(payload or {})))
            return (cfg or {}).get(action, {"success": True, "output": action + " ok"})

        st = status(sid=sid, form=extra.pop("form", None))
        with mock.patch.object(h44, "build_build_status", lambda profile="travel": st), \
                mock.patch.object(h44, "_bld_cfg", fake_cfg), \
                mock.patch.object(h44, "_fcr_load", lambda: (({"files": []}, {}) if staged else (None, None))), \
                mock.patch.object(h44, "_pn_status", lambda: {"old_ext": True, "nodes_fixable": False, "refs_fixable": True}), \
                mock.patch.object(h44, "action_boot_order_apply", lambda: {"success": True, "output": "boot ok"}):
            res = h44._bld_act_run_stage({"stage": sid, "profile": "travel", "preview": preview})
        return res, calls

    def test_apply_filters_to_its_group_and_uses_the_form(self):
        res, calls = self.go("apply_dvs")
        self.assertTrue(res["success"])
        action, payload = calls[-1]
        self.assertEqual(action, "bundle_apply")
        self.assertEqual(payload["groups"], ["dvs"])
        self.assertIs(payload["confirm"], True)
        self.assertEqual(payload["values"], {"callsign": "KD8PGK", "node": "652701", "dmr_id": "3123456", "nxdn_id": "12345"})
        self.assertNotIn("bundle_fetch", [c[0] for c in calls])

    def test_restart_hint_points_at_the_config_tab(self):
        res, _ = self.go("apply_asl3", cfg={"bundle_apply": {"success": True, "output": "ok\nUse the Restart buttons below when ready."}})
        self.assertIn("Use Restart services on the Config tab when ready.", res["notes"])
        self.assertNotIn("buttons below", "\n".join(res["notes"]))

    def test_apply_fetches_only_when_not_staged(self):
        _res, calls = self.go("apply_asl3", staged=False)
        self.assertEqual([c[0] for c in calls], ["bundle_fetch", "bundle_apply"])

    def test_failed_fetch_writes_nothing(self):
        res, calls = self.go("apply_asl3", staged=False, cfg={"bundle_fetch": {"success": False, "output": "no network"}})
        self.assertFalse(res["success"])
        self.assertEqual([c[0] for c in calls], ["bundle_fetch"])

    def test_preview_never_confirms(self):
        res, calls = self.go("apply_m17", preview=True)
        self.assertEqual(calls[-1][0], "bundle_preview")
        self.assertNotIn("confirm", calls[-1][1])
        self.assertIn("nothing was changed", res["message"])

    def test_boot_and_save(self):
        res, calls = self.go("boot")
        self.assertTrue(res["success"])
        self.assertIn("boot ok", res["notes"])
        res, calls = self.go("save")
        self.assertEqual(calls[-1][0], "save_restore")

    def test_wiring_runs_only_what_can_be_fixed(self):
        _res, calls = self.go("wiring")
        self.assertEqual([c[0] for c in calls], ["pn_fix_ext", "pn_fix_refs"])
        _res, calls = self.go("wiring", preview=True)
        self.assertEqual([c[0] for c in calls], ["pn_fix_ext_preview", "pn_fix_refs_preview"])

    def test_svx_wire_adds_the_bridge_then_the_fixers(self):
        res, calls = self.go("svx_wire")
        self.assertEqual([c[0] for c in calls], ["svx_bridge", "pn_fix_ext"])
        self.assertIn("SVXLink tab", "\n".join(res["notes"]))

    def test_failure_is_reported(self):
        res, _ = self.go("wiring", cfg={"pn_fix_ext": {"success": False, "output": "bad"}})
        self.assertFalse(res["success"])
        self.assertIn("failed", res["message"])

    def test_long_output_is_cut(self):
        big = {"success": True, "output": "\n".join(str(i) for i in range(500))}
        res, _ = self.go("boot", cfg={})
        with mock.patch.object(h44, "action_boot_order_apply", lambda: big), \
                mock.patch.object(h44, "build_build_status", lambda profile="travel": status(sid="boot")):
            res = h44._bld_act_run_stage({"stage": "boot"})
        self.assertEqual(len(res["notes"]), h44._BLD_RUN_MAX_LINES + 1)
        self.assertIn("more line", res["notes"][-1])

    def test_exceptions_do_not_leak(self):
        with mock.patch.object(h44, "build_build_status", lambda profile="travel": status(sid="boot")), \
                mock.patch.object(h44, "action_boot_order_apply", mock.Mock(side_effect=ValueError("secret detail"))):
            res = h44._bld_act_run_stage({"stage": "boot"})
        self.assertFalse(res["success"])
        self.assertNotIn("secret detail", res["message"])


class Radio(Tmp):
    def go(self, form, preview, cards=CARDS, usb=USB):
        path = self.write("simpleusb.conf", usb)
        with mock.patch.object(h44, "_BLD_SIMPLEUSB", path), \
                mock.patch.object(h44, "_BLD_SAVENODE", self.p("none")), \
                mock.patch.object(h44, "_cfgr_auto_point", lambda reason, groups: ("auto1", [])):
            res = h44._bld_run_radio(dict(FORM, **form), cards, preview)
        return res, path

    def test_preview_changes_nothing(self):
        (ok, lines), path = self.go({}, True)
        self.assertTrue(ok)
        with open(path) as f:
            self.assertEqual(f.read(), USB)
        self.assertTrue(any("+devstr = 1-1.3" in ln for ln in lines))

    def test_run_writes_the_pick(self):
        (ok, lines), path = self.go({}, False)
        self.assertTrue(ok)
        with open(path) as f:
            self.assertIn("devstr = 1-1.3", f.read())
        self.assertIn("auto1", "\n".join(lines))

    def test_refusals(self):
        self.assertFalse(self.go({"usb": ""}, False)[0][0])
        self.assertFalse(self.go({"usb": "9-9"}, False)[0][0])
        self.assertFalse(self.go({"node": "111111"}, False)[0][0])

    def test_already_set(self):
        (ok, lines), _ = self.go({}, False, usb=USB.replace("devstr =\nrxboost", "devstr = 1-1.3\nrxboost"))
        self.assertTrue(ok)
        self.assertIn("Nothing to change", lines[0])


class StatusRunInfo(unittest.TestCase):
    def test_run_only_on_open_runnable_rows(self):
        with mock.patch.object(h44, "_BLD_FILE", "/nonexistent/build.json"), \
                mock.patch.object(h44, "_bld_usb_cards", lambda: []), \
                mock.patch.object(h44, "_bld_machine", lambda: []), \
                mock.patch.object(h44, "_detect_installed_products", lambda force=False: [{"key": "asl3", "state": "installed"}]), \
                mock.patch.object(h44, "_wg0_interface_present", lambda: False), \
                mock.patch.object(h44, "_firewalld_zone_info_cached", lambda: None), \
                mock.patch.object(h44, "status_boot_order", lambda: {"done": False, "missing": ["x"]}), \
                mock.patch.object(h44, "_cfgr_usrp_pairs", lambda override=None: ([], [])), \
                mock.patch.object(h44, "_pn_status", lambda: {"available": False}), \
                mock.patch.object(h44, "_cfgr_snap_dir", lambda k, sid="": "x"), \
                mock.patch.object(h44, "_cfgr_read_manifest", lambda d: None), \
                mock.patch.object(h44, "_cfgr_load_preset", lambda p: None):
            st = h44.build_build_status("travel")
        for s in st["stages"]:
            if "run" in s:
                self.assertIn(s["id"], h44._BLD_RUNNABLE)
                self.assertIn(s["state"], ("todo", "warn"))
                self.assertEqual(s["run"]["preview"], s["id"] in h44._BLD_PREVIEWABLE)
        self.assertNotIn("run", {s["id"]: s for s in st["stages"]}["asl3"])


class Page(unittest.TestCase):
    def test_both_pages_get_run_buttons_and_an_output_box(self):
        for js, html, pfx, fn in ((h44._JS_BUILD, h44._render_build_panel(), "bld", "build"),
                                  (h44._JS_MAGIC, h44._render_magic_panel(), "mbx", "magic")):
            self.assertIn(f"function {fn}Run(", js)
            self.assertIn(f"function {fn}RunButtons(", js)
            self.assertIn(f'id="{pfx}-run-out"', html)
            self.assertIn("run_stage", js)
            self.assertIn("confirm(", js)

    def test_run_is_refused_with_unsaved_form(self):
        self.assertIn("Save the form first", h44._JS_BUILD)


if __name__ == "__main__":
    unittest.main()
