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


spec = importlib.util.spec_from_file_location("h44_finish_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_finish_under_test"] = h44
spec.loader.exec_module(h44)

FORM = dict(h44._BLD_DEFAULT, callsign="KD8PGK", node="652701", dmr_id="3123456", nxdn_id="12345", mode="none")


def row(fid, groups, value, rid=None, label="x", file="/f"):
    return {"fid": fid, "groups": groups, "value": value, "rid": rid or fid + "#0", "label": label, "file": file}


class NoBundle(unittest.TestCase):
    def test_the_apply_steps_are_gone(self):
        for mode in ("half", "split", "full", "none"):
            for profile in ("travel", "magic"):
                ids = [i for i, _ in h44._bld_stage_defs(mode, profile)]
                for gone in ("apply_asl3", "apply_dvs", "apply_m17"):
                    self.assertNotIn(gone, ids)
        for name in ("_bld_run_apply", "_bld_applied", "_BLD_RUN_GROUP"):
            self.assertFalse(hasattr(h44, name), name)
        self.assertNotIn("bundle", h44._BLD_PANEL_TMPL.lower())

    def test_the_new_steps_and_what_runs(self):
        for sid in ("identity", "location", "passwords", "restart"):
            self.assertIn(sid, h44._BLD_RUNNABLE)
        for sid in ("identity", "location", "passwords"):
            self.assertIn(sid, h44._BLD_PREVIEWABLE)
        self.assertNotIn("restart", h44._BLD_PREVIEWABLE)
        for sid in ("registration", "ready"):
            self.assertNotIn(sid, h44._BLD_RUNNABLE)

    def test_order_at_the_end(self):
        for profile in ("travel", "magic"):
            ids = [i for i, _ in h44._bld_stage_defs("half", profile)]
            tail = ids[ids.index("radio"):]
            self.assertEqual(tail, ["radio", "restart", "registration", "ready", "save", "reboot"])
            self.assertLess(ids.index("identity"), ids.index("preset"))
            self.assertLess(ids.index("m17"), ids.index("identity"))


class Identity(unittest.TestCase):
    def state(self, rows, public=("652701",), rpt="x", form=None):
        with mock.patch.object(h44, "_cfgr_text", lambda p: rpt), \
                mock.patch.object(h44, "_cfgr_node_public", lambda t: list(public)), \
                mock.patch.object(h44, "_cfgr_identity_scan", lambda: {"rows": rows, "groups": {}}):
            return h44._bld_identity_state(form or FORM)

    GOOD = [row("rpt_call", ["callsign"], "KD8PGK"), row("mb_id", ["dmr"], "3123456"), row("mb_nxdn_id", [], "12345")]

    def test_done_when_everything_matches(self):
        self.assertEqual(self.state(self.GOOD)[0], "done")

    def test_each_mismatch_is_named(self):
        st, why = self.state([row("rpt_call", ["callsign"], "W1AW"), row("mb_id", ["dmr"], "3999999"), row("mb_nxdn_id", [], "1")], public=("111111",))
        self.assertEqual(st, "todo")
        for bit in ("node number", "callsign", "DMR ID", "NXDN ID"):
            self.assertIn(bit, why)

    def test_nxdn_is_optional(self):
        self.assertEqual(self.state(self.GOOD[:2], form=dict(FORM, nxdn_id=""))[0], "done")

    def test_waits_for_the_form_and_for_rpt_conf(self):
        self.assertIn("Preflight", self.state(self.GOOD, form=dict(FORM, callsign=""))[1])
        self.assertIn("rpt.conf", self.state(self.GOOD, rpt=None)[1])

    def run_it(self, rows, public, preview):
        calls = []

        def fake(payload, apply):
            calls.append((dict(payload), apply))
            return {"success": True, "output": "ok"}

        with mock.patch.object(h44, "_cfgr_text", lambda p: "x"), \
                mock.patch.object(h44, "_cfgr_node_public", lambda t: list(public)), \
                mock.patch.object(h44, "_cfgr_identity_scan", lambda: {"rows": rows, "groups": {}}), \
                mock.patch.object(h44, "_cfgr_act_id_set", fake):
            ok, lines = h44._bld_run_identity(FORM, preview)
        return ok, lines, calls

    def test_run_sets_node_callsign_dmr_and_nxdn(self):
        rows = [row("rpt_call", ["callsign"], "OLD"), row("mb_id", ["dmr"], "1111111"), row("mb_nxdn_id", [], "9", "mb_nxdn_id#0"),
                row("var_nxdn_id", [], "9", "var_nxdn_id#0")]
        ok, lines, calls = self.run_it(rows, ("111111",), False)
        self.assertTrue(ok)
        groups = [c[0]["group"] for c in calls]
        self.assertEqual(groups, ["node", "callsign", "dmr", "alone", "alone"])
        self.assertEqual(calls[0][0], {"group": "node", "node": "111111", "value": "652701"})
        self.assertTrue(all(c[1] is True for c in calls))
        self.assertIn("Restart", lines[-1])

    def test_preview_writes_nothing(self):
        _ok, _lines, calls = self.run_it([row("rpt_call", ["callsign"], "OLD")], ("652701",), True)
        self.assertTrue(calls and all(c[1] is False for c in calls))

    def test_nothing_to_change(self):
        _ok, lines, calls = self.run_it(self.GOOD, ("652701",), False)
        self.assertEqual(calls, [])
        self.assertIn("Nothing to change.", lines)

    def test_no_node_stanza_yet_leaves_the_node_alone(self):
        _ok, lines, calls = self.run_it(self.GOOD, (), False)
        self.assertEqual(calls, [])
        self.assertTrue(any("No node stanza" in ln for ln in lines))


class Restart(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.conf = os.path.join(self.d.name, "a.conf")
        with open(self.conf, "w") as f:
            f.write("x")
        self.marks = os.path.join(self.d.name, "marks.json")
        groups = {"asl3": {"files": [self.conf], "label": "ASL3", "services": ["asterisk"]}}
        for p in (mock.patch.object(h44, "_BLD_MARKS", self.marks), mock.patch.object(h44, "_CFGR_GROUPS", groups),
                  mock.patch.object(h44, "_cfgr_installed", lambda: {"asl3": True})):
            p.start()
            self.addCleanup(p.stop)

    def test_todo_until_restarted_after_the_last_change(self):
        self.assertEqual(h44._bld_restart_state()[0], "todo")
        calls = []
        with mock.patch.object(h44, "_cfgr_act_restart", lambda p: calls.append(p) or {"success": True, "output": "asterisk: restarted"}):
            ok, lines = h44._bld_run_restart()
        self.assertTrue(ok)
        self.assertEqual(calls, [{"groups": ["asl3"]}])
        self.assertEqual(h44._bld_restart_state()[0], "done")
        later = os.stat(self.conf).st_mtime + 50
        os.utime(self.conf, (later, later))
        self.assertEqual(h44._bld_restart_state()[0], "todo")

    def test_a_failed_restart_is_not_marked(self):
        with mock.patch.object(h44, "_cfgr_act_restart", lambda p: {"success": False, "output": "boom"}):
            ok, _ = h44._bld_run_restart()
        self.assertFalse(ok)
        self.assertNotIn("restarted_at", h44._bld_marks_load())

    def test_nothing_installed_is_done(self):
        with mock.patch.object(h44, "_cfgr_installed", lambda: {"asl3": False}):
            self.assertEqual(h44._bld_restart_state()[0], "done")

    def test_the_ready_mark_keeps_the_restart_mark(self):
        h44._bld_mark_set("restarted_at")
        h44._bld_mark_ready()
        got = h44._bld_marks_load()
        self.assertIn("restarted_at", got)
        self.assertIn("ready_at", got)


class Registration(unittest.TestCase):
    def state(self, entries, have=True):
        with mock.patch.object(h44.shutil, "which", lambda n: "/usr/sbin/asterisk" if have else None), \
                mock.patch.object(h44, "asl_registration_info", lambda: {"entries": entries}):
            return h44._bld_registration_state("652701")

    def test_states(self):
        self.assertEqual(self.state([{"node": "652701", "registered": True, "ip": "44.1.2.3", "port": 4574}])[0], "done")
        st, why = self.state([{"node": "652701", "registered": False, "ip": "", "port": ""}])
        self.assertEqual(st, "warn")
        self.assertIn("node password", why)
        self.assertEqual(self.state([])[0], "warn")
        self.assertEqual(self.state([], have=False)[0], "warn")


class Ready(unittest.TestCase):
    def state(self, restart="done", poke=True, mode="half", up=True, age=10.0):
        stages = [{"id": "restart", "state": restart}]
        with mock.patch.object(h44, "_cfgr_bindport", lambda: "4574"), mock.patch.object(h44, "_iax_bindaddr", lambda: "0.0.0.0"), \
                mock.patch.object(h44, "_iax_poke", lambda h, p, t=2.0: (poke, "x")):
            return h44._bld_ready_state(stages, mode, up, age, FORM)

    def test_done(self):
        st, why = self.state()
        self.assertEqual(st, "done")
        self.assertIn("4574", why)

    def test_each_blocker(self):
        self.assertIn("restart", self.state(restart="todo")[1])
        self.assertIn("IAX does not answer", self.state(poke=False)[1])
        self.assertIn("handshake", self.state(age=900.0)[1])
        self.assertIn("handshake", self.state(up=False)[1])
        self.assertEqual(self.state(mode="none", up=False, age=None)[0], "done")


class FreshNodePort(unittest.TestCase):
    def test_the_form_port_is_used_before_iax_conf_exists(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(h44, "_CFGR_IAX", os.path.join(d, "none.conf")), \
                    mock.patch.object(h44, "_bld_form_load", lambda: {"iax_port": "4574"}):
                self.assertEqual(h44._cfgr_bindport(), "4574")
            with mock.patch.object(h44, "_CFGR_IAX", os.path.join(d, "none.conf")), \
                    mock.patch.object(h44, "_bld_form_load", lambda: {"iax_port": "80"}):
                self.assertEqual(h44._cfgr_bindport(), "4569")
            iax = os.path.join(d, "iax.conf")
            with open(iax, "w") as f:
                f.write("[general]\nbindport = 4580\n")
            with mock.patch.object(h44, "_CFGR_IAX", iax), mock.patch.object(h44, "_bld_form_load", lambda: {"iax_port": "4574"}):
                self.assertEqual(h44._cfgr_bindport(), "4580")


class Js(unittest.TestCase):
    def test_the_new_steps_are_named_on_both_tabs(self):
        for js in (h44._JS_BUILD, h44._JS_MAGIC):
            for sid in ("identity:", "location:", "restart:", "registration:", "passwords:", "ready:"):
                self.assertIn(sid, js)
            self.assertNotIn("apply_asl3", js)


if __name__ == "__main__":
    unittest.main()
