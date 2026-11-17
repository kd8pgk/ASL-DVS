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


spec = importlib.util.spec_from_file_location("h44_iaxport_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_iaxport_under_test"] = h44
spec.loader.exec_module(h44)

IAX = "[general]\nbindport = 4569\nbindaddr = 0.0.0.0\n"
RPT = """[1999](node-main)
rxchannel = USRP/127.0.0.1:34001:32001
duplex = 0

[652705](node-main)
duplex = 1

[nodes]
652705 = radio@127.0.0.1/652705,NONE
1999 = radio@127.0.0.1:4574/1999,NONE
2000 = radio@10.1.1.1:4569/2000,NONE
"""


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.iax = os.path.join(self.d.name, "iax.conf")
        self.rpt = os.path.join(self.d.name, "rpt.conf")
        for path, text in ((self.iax, IAX), (self.rpt, RPT)):
            with open(path, "w") as f:
                f.write(text)
        for p in (mock.patch.object(h44, "_CFGR_IAX", self.iax), mock.patch.object(h44, "_CFGR_RPT", self.rpt)):
            p.start()
            self.addCleanup(p.stop)


class Helpers(Tmp):
    def test_port_checks(self):
        for good in ("1024", "4569", "4574", "65535"):
            self.assertTrue(h44._cfgr_port_ok(good), good)
        for bad in ("", "80", "1023", "65536", "45 69", "abcd", None, 4569):
            self.assertFalse(h44._cfgr_port_ok(bad), bad)

    def test_nodes_lines_follow_the_port_for_local_nodes_only(self):
        new, nodes = h44._cfgr_nodes_port(h44._cfgr_lines(RPT), "4574")
        text = "\n".join(new)
        self.assertEqual(nodes, ["652705"])
        self.assertIn("652705 = radio@127.0.0.1:4574/652705,NONE", text)
        self.assertIn("2000 = radio@10.1.1.1:4569/2000,NONE", text)

    def test_the_default_port_drops_the_suffix(self):
        new, nodes = h44._cfgr_nodes_port(h44._cfgr_lines(RPT), "4569")
        self.assertEqual(nodes, ["1999"])
        self.assertIn("1999 = radio@127.0.0.1/1999,NONE", "\n".join(new))

    def test_iax_set_changes_bindport_and_the_nodes_lines(self):
        changes, notes = h44._cfgr_iax_set("4574")
        self.assertIn("bindport = 4574", changes[self.iax][1].decode())
        self.assertIn("bindaddr = 0.0.0.0", changes[self.iax][1].decode())
        self.assertIn(self.rpt, changes)
        self.assertTrue(any("4569 -> 4574" in n or "bindport" in n for n in notes))

    def test_iax_set_without_rpt_leaves_rpt_alone(self):
        changes, _ = h44._cfgr_iax_set("4574", with_rpt=False)
        self.assertNotIn(self.rpt, changes)

    def test_nothing_to_do_when_it_matches(self):
        with open(self.iax, "w") as f:
            f.write("[general]\nbindport = 4574\n")
        with open(self.rpt, "w") as f:
            f.write(RPT.replace("652705 = radio@127.0.0.1/", "652705 = radio@127.0.0.1:4574/"))
        changes, _ = h44._cfgr_iax_set("4574")
        self.assertEqual(changes, {})

    def test_a_missing_bindport_line_is_added(self):
        with open(self.iax, "w") as f:
            f.write("[general]\nbindaddr = 0.0.0.0\n")
        changes, _ = h44._cfgr_iax_set("4574", with_rpt=False)
        self.assertIn("bindport = 4574", changes[self.iax][1].decode())

    def test_no_iax_conf_is_a_note(self):
        os.remove(self.iax)
        changes, notes = h44._cfgr_iax_set("4574", with_rpt=False)
        self.assertEqual(changes, {})
        self.assertIn("not found", notes[0])


class Preset(Tmp):
    def base(self, **kw):
        p = {"rpt": {"nodes": []}, "extensions": [], "modules": {}, "ini": {}}
        p.update(kw)
        return p

    def test_validation(self):
        self.assertIsNotNone(h44._cfgr_validate_preset(self.base(iax_port="4574")))
        self.assertIsNotNone(h44._cfgr_validate_preset(self.base()))
        for bad in ("80", "x", "70000", "", 4574):
            self.assertIsNone(h44._cfgr_validate_preset(self.base(iax_port=bad)), bad)

    def test_the_summary_names_the_port(self):
        self.assertEqual(h44._cfgr_preset_summary(self.base(iax_port="4574"))[0], "IAX port (iax.conf bindport): 4574")
        self.assertNotIn("IAX port", h44._cfgr_preset_summary(self.base())[0])

    def test_capture_carries_the_nodes_bindport(self):
        with open(self.iax, "w") as f:
            f.write("[general]\nbindport = 4574\n")
        p = self.base()
        with mock.patch.object(h44, "_cfgr_capture", lambda: (dict(p), [], [])):
            with tempfile.TemporaryDirectory() as d, mock.patch.object(h44, "_CFGR_DIR", d), \
                    mock.patch.object(h44, "_cfgr_ensure_root_dir", lambda: None):
                res = h44._cfgr_act_preset_capture({"preset": "travel_node"}, True)
                self.assertTrue(res["success"], res["output"])
                self.assertEqual(h44._cfgr_load_preset("travel_node")["iax_port"], "4574")

    def plan(self, p, port=""):
        n = os.path.join(self.d.name, "nope")
        with mock.patch.multiple(h44, _CFGR_EXT=n, _CFGR_MOD=n, _CFGR_ALLMON=n, _CFGR_ECHOLINK=n):
            return h44._cfgr_preset_plan(p, port)

    def test_the_preset_port_is_applied_to_iax_and_nodes(self):
        changes, _r, notes, warnings, err = self.plan(self.base(iax_port="4574"))
        self.assertEqual(err, "")
        self.assertIn("bindport = 4574", changes[self.iax][1].decode())
        self.assertIn("652705 = radio@127.0.0.1:4574/652705,NONE", changes[self.rpt][1].decode())
        self.assertTrue(any("Restart Asterisk" in w for w in warnings))

    def test_the_form_port_wins_over_the_preset(self):
        changes, *_ = self.plan(self.base(iax_port="4574"), "4580")
        self.assertIn("bindport = 4580", changes[self.iax][1].decode())

    def test_an_old_preset_without_a_port_leaves_iax_conf_alone(self):
        changes, *_ = self.plan(self.base())
        self.assertNotIn(self.iax, changes)

    def test_a_bad_override_is_ignored_by_the_plan_and_refused_by_the_action(self):
        changes, *_ = self.plan(self.base(iax_port="4574"), "80")
        self.assertIn("bindport = 4574", changes[self.iax][1].decode())
        with mock.patch.object(h44, "_cfgr_load_preset", lambda pid: self.base()):
            res = h44._cfgr_act_preset_apply({"preset": "travel_node", "iax_port": "80"}, False)
        self.assertFalse(res["success"])


class BuildForm(Tmp):
    def test_form_field_and_errors(self):
        self.assertIn("iax_port", h44._BLD_FIELDS)
        self.assertEqual(h44._BLD_DEFAULT["iax_port"], "")
        form = dict(h44._BLD_DEFAULT, callsign="KD8PGK", node="652701", dmr_id="3123456", mode="none")
        self.assertNotIn("iax_port", h44._bld_form_errors(form, []))
        for bad in ("80", "456", "99999", "45x9"):
            self.assertIn("iax_port", h44._bld_form_errors(dict(form, iax_port=bad), []), bad)
        self.assertNotIn("iax_port", h44._bld_form_errors(dict(form, iax_port="4574"), []))

    def test_the_field_is_on_both_tabs(self):
        self.assertIn("iax_port", h44._BLD_FIELDS_TRAVEL)
        self.assertIn("iax_port", h44._BLD_FIELDS_MAGIC)
        self.assertIn("-iax_port", h44._BLD_PANEL_TMPL)

    def test_the_step_is_after_apply_asl3_on_both_tabs(self):
        for profile in ("travel", "magic"):
            for mode in ("half", "split", "full", "none"):
                ids = [i for i, _ in h44._bld_stage_defs(mode, profile)]
                self.assertEqual(ids[ids.index("apply_asl3") + 1], "iax_port", (profile, mode))
        self.assertIn("iax_port", h44._BLD_RUNNABLE)
        self.assertIn("iax_port", h44._BLD_PREVIEWABLE)

    def test_state(self):
        self.assertEqual(h44._bld_iax_state({"iax_port": ""})[0], "done")
        self.assertEqual(h44._bld_iax_state({"iax_port": "4574"})[0], "todo")
        with open(self.iax, "w") as f:
            f.write("[general]\nbindport = 4574\n")
        with open(self.rpt, "w") as f:
            f.write(RPT.replace("652705 = radio@127.0.0.1/", "652705 = radio@127.0.0.1:4574/"))
        self.assertEqual(h44._bld_iax_state({"iax_port": "4574"})[0], "done")
        os.remove(self.iax)
        self.assertEqual(h44._bld_iax_state({"iax_port": "4574"})[0], "todo")

    def test_preview_changes_nothing_and_run_writes_with_a_copy_first(self):
        ok, lines = h44._bld_run_iax({"iax_port": "4574"}, True)
        self.assertTrue(ok)
        with open(self.iax) as f:
            self.assertIn("bindport = 4569", f.read())
        self.assertTrue(any(ln.startswith("+bindport = 4574") for ln in lines))
        writes = []
        with mock.patch.object(h44, "_cfgr_auto_point", lambda reason, groups: ("auto1", [])), \
                mock.patch.object(h44, "_cfgr_write_file", lambda path, data, uid, gid, mode: writes.append(path) or "written"):
            ok, lines = h44._bld_run_iax({"iax_port": "4574"}, False)
        self.assertTrue(ok)
        self.assertEqual(sorted(writes), sorted([self.iax, self.rpt]))
        self.assertTrue(any("automatic copy auto1" in ln for ln in lines))
        self.assertTrue(any("Restart Asterisk" in ln for ln in lines))

    def test_the_preset_step_gets_the_form_port(self):
        calls = []
        with mock.patch.object(h44, "_bld_cfg", lambda a, p=None: calls.append((a, p)) or {"success": True, "output": "ok"}):
            h44._bld_run_preset("travel", True, "4574")
        self.assertEqual(calls[0][1], {"preset": "travel_node", "iax_port": "4574"})


if __name__ == "__main__":
    unittest.main()
