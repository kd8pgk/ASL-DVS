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


spec = importlib.util.spec_from_file_location("h44_rest_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_rest_under_test"] = h44
spec.loader.exec_module(h44)


def stage(sid, state, detail="d"):
    return {"id": sid, "label": "L-" + sid, "state": state, "detail": detail}


def status(*pairs):
    return {"form": {}, "stages": [stage(i, s) for i, s in pairs]}


class Reboot(unittest.TestCase):
    def state(self, others_done=True, up=True, age=5.0, marks=None, btime=2000, line="x boot abc boot: ready after 5s: ok", wg=True):
        with mock.patch.object(h44, "_bld_marks_load", lambda: marks or {}), \
                mock.patch.object(h44, "_bt_btime", lambda: btime), \
                mock.patch.object(h44, "_bld_boot_ready_line", lambda: line), \
                mock.patch.object(h44.os.path, "exists", lambda p: wg if p == h44.WG0_CONF_PATH else True):
            return h44._bld_reboot_state(others_done, up, age)

    def test_before_the_mark(self):
        self.assertEqual(self.state(others_done=False)[0], "manual")
        self.assertEqual(self.state(others_done=True)[0], "todo")

    def test_marked_but_not_yet_rebooted(self):
        st, why = self.state(marks={"ready_at": 5000}, btime=2000)
        self.assertEqual(st, "manual")
        self.assertIn("Reboot now", why)

    def test_rebooted_and_ready_is_done(self):
        st, why = self.state(marks={"ready_at": 1000}, btime=2000)
        self.assertEqual(st, "done")
        self.assertIn("ready after 5s", why)

    def test_rebooted_but_not_ready_or_no_handshake_warns(self):
        self.assertEqual(self.state(marks={"ready_at": 1000}, line="")[0], "warn")
        self.assertEqual(self.state(marks={"ready_at": 1000}, age=999.0)[0], "warn")
        self.assertEqual(self.state(marks={"ready_at": 1000}, up=False)[0], "warn")
        self.assertEqual(self.state(marks={"ready_at": 1000}, up=False, wg=False)[0], "done")

    def test_ready_line_reading(self):
        lines = ["t boot abc boot: not ready after 180s (network=1)", "t boot abc late: ready 300s later; started again: x"]
        with mock.patch.object(h44, "_bt_boot_id", lambda: "abc"), mock.patch.object(h44, "_bt_boot_log_lines", lambda b: (lines, lines)):
            self.assertIn("ready 300s later", h44._bld_boot_ready_line())
        with mock.patch.object(h44, "_bt_boot_id", lambda: "abc"), mock.patch.object(h44, "_bt_boot_log_lines", lambda b: (lines[:1], lines[:1])):
            self.assertEqual(h44._bld_boot_ready_line(), "")
        with mock.patch.object(h44, "_bt_boot_id", lambda: "abc"), mock.patch.object(h44, "_bt_boot_log_lines", lambda b: ([], [])):
            self.assertEqual(h44._bld_boot_ready_line(), "")

    def test_mark_file_is_private_and_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "etc", "marks.json")
            with mock.patch.object(h44, "_BLD_MARKS", path):
                self.assertEqual(h44._bld_marks_load(), {})
                h44._bld_mark_ready()
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
                self.assertIsInstance(h44._bld_marks_load()["ready_at"], int)
            with open(path, "w") as f:
                f.write("[1]")
            with mock.patch.object(h44, "_BLD_MARKS", path):
                self.assertEqual(h44._bld_marks_load(), {})


class RestWorker(unittest.TestCase):
    def runnable(self, *ids):
        return mock.patch.object(h44, "_BLD_RUNNABLE", h44._BLD_RUNNABLE | frozenset(ids))

    def run_rest(self, statuses, results=None, payload=None):
        seq = iter(statuses)
        last = [statuses[-1]]
        ran = []

        def fake_status(profile):
            try:
                last[0] = next(seq)
            except StopIteration:
                pass
            return last[0]

        def fake_inline(sid, profile, st, pl, key):
            ran.append(sid)
            return (results or {}).get(sid, {"success": True, "message": "ok"})

        appended = []
        with mock.patch.object(h44, "build_build_status", fake_status), \
                mock.patch.object(h44, "_bld_inline", fake_inline), \
                mock.patch.object(h44, "_job_append_output", lambda k, t: appended.append(t)), \
                mock.patch.object(h44, "_job_status", lambda k: {"output": "".join(appended)}):
            out = h44._bld_rest_worker("build_travel_rest", "travel", payload or {})
        return out, ran

    def test_runs_open_steps_in_order_until_done(self):
        with self.runnable("a", "b"):
            out, ran = self.run_rest([status(("a", "todo"), ("b", "locked")), status(("a", "done"), ("b", "todo")),
                                      status(("a", "done"), ("b", "done"))])
        self.assertEqual(ran, ["a", "b"])
        self.assertTrue(out["success"])
        self.assertTrue(out["output"].endswith("Every step is done."))

    def test_stops_at_a_step_that_has_its_own_tab(self):
        out, ran = self.run_rest([status(("half", "todo"), ("boot", "locked"))])
        self.assertEqual(ran, [])
        self.assertIn("own tab", out["output"])
        self.assertTrue(out["success"])

    def test_warn_does_not_hold_the_run_back(self):
        with self.runnable("zz"):
            out, ran = self.run_rest([status(("a", "warn"), ("zz", "todo")), status(("a", "warn"), ("zz", "done"))])
        self.assertEqual(ran, ["zz"])

    def test_stops_on_a_failure(self):
        with self.runnable("a", "b"):
            out, ran = self.run_rest([status(("a", "todo"), ("b", "locked"))], {"a": {"success": False, "message": "bad", "notes": ["why"]}})
        self.assertFalse(out["success"])
        self.assertEqual(ran, ["a"])
        self.assertIn("why", out["output"])
        self.assertIn("did not finish", out["output"])

    def test_stops_when_a_step_makes_no_progress(self):
        with self.runnable("a"):
            out, ran = self.run_rest([status(("a", "todo"))])
        self.assertEqual(ran, ["a"])
        self.assertFalse(out["success"])
        self.assertIn("still open", out["output"])

    def test_a_locked_first_open_step_stops(self):
        out, ran = self.run_rest([status(("a", "locked"))])
        self.assertEqual(ran, [])
        self.assertIn("waits", out["output"])

    def test_after_the_reboot_mark_it_says_reboot(self):
        st = status(("a", "done"), ("reboot", "manual"))
        st["stages"][1]["detail"] = "Marked ready at 2026-11-17 04:00:00. Reboot now."
        out, _ = self.run_rest([st])
        self.assertIn("Reboot now", out["output"])
        self.assertTrue(out["success"])

    def test_limit(self):
        with self.runnable("a", "b"):
            seq = [status(("a" if i % 2 == 0 else "b", "todo")) for i in range(100)]
            out, ran = self.run_rest(seq)
        self.assertLessEqual(len(ran), h44._BLD_REST_MAX)
        self.assertIn("too many", out["output"])


class Start(unittest.TestCase):
    def start(self, pre="done", running=""):
        started = []
        st = status(("preflight", pre))
        with mock.patch.object(h44, "build_build_status", lambda p: st), \
                mock.patch.object(h44, "_bld_running_job", lambda: running), \
                mock.patch.object(h44, "_start_python_job", lambda key, fn: started.append(key) or {}):
            res = h44._bld_act_run_rest({"profile": "magic", "config_text": "SECRETCONF", "_client_ip": "192.168.1.5"})
        return res, started

    def test_starts_one_job(self):
        res, started = self.start()
        self.assertTrue(res["success"])
        self.assertEqual(started, ["build_magic_rest"])
        self.assertNotIn("SECRETCONF", json.dumps(res))

    def test_needs_the_preflight_and_a_free_slot(self):
        self.assertFalse(self.start(pre="todo")[0]["success"])
        self.assertFalse(self.start(running="build_travel_dvs")[0]["success"])

    def test_inline_runs_long_steps_without_a_nested_job(self):
        st = {"form": {"callsign": "KD8PGK"}}
        with mock.patch.object(h44, "_bld_long_prepare", lambda sid, f, p: ("", lambda key: {"success": True}, "x", [])), \
                mock.patch.object(h44, "_start_python_job", side_effect=AssertionError("nested job")):
            self.assertTrue(h44._bld_inline("asl3", "travel", st, {}, "build_travel_rest")["success"])
        with mock.patch.object(h44, "_bld_long_prepare", lambda sid, f, p: ("no config", None, "", [])):
            r = h44._bld_inline("tunnel", "travel", st, {}, "k")
            self.assertEqual((r["success"], r["message"]), (False, "no config"))
        with mock.patch.object(h44, "_bld_act_run_stage", lambda pl: {"success": True, "message": "q"}):
            self.assertEqual(h44._bld_inline("boot", "travel", st, {}, "k")["message"], "q")


class Locking(unittest.TestCase):
    def test_warn_passes_the_lock_on_but_todo_does_not(self):
        with open(newest("44helper_v[0-9]*.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('if s["state"] not in ("done", "manual", "warn"):', src)


class Report(unittest.TestCase):
    def report(self, profile="travel"):
        st = {"form": {"mode": "full", "callsign": "KD8PGK", "node": "652701", "dmr_id": "3123456", "nxdn_id": "", "m17_node": "1917",
                       "usb": "", "bypass": "", "svx_use": "bridge", "svx_host": "x.example.org", "svx_port": "5300", "svx_tg": "0", "svx_mon": ""},
              "board": {"model": "Raspberry Pi Zero 2 W"}, "tunnel_kind": "full",
              "stages": [stage("preflight", "done"), stage("asl3", "todo", "not installed"), stage("radio", "warn", "no card")],
              "radio": {"node": "652701", "rxchannel": "SimpleUSB/652701", "devstr": "", "simpleusb_stanza": True, "nodetalker": True,
                        "stanza_1921": True, "cards": [], "phone_nodes": ["1001"]}}
        if profile == "magic":
            st["svx"] = {"installed": True, "active": True, "use": "bridge", "log": "connected", "reachable": True, "udp_open": False,
                         "reflector": {"host": "x.example.org", "port": "5300", "callsign": "KD8PGK", "key_set": True}}
        with mock.patch.object(h44, "build_build_status", lambda p: st), \
                mock.patch.object(h44, "_cfgr_usrp_pairs", lambda override=None: (["SvxLink pair"], ["a warning"])), \
                mock.patch.object(h44, "_bt_versions", lambda: {"44helper": "0.1.50"}), \
                mock.patch.object(h44, "_bt_boot_id", lambda: "abc"), \
                mock.patch.object(h44, "_bt_boot_log_lines", lambda b: ([], ["t boot abc boot: ready after 4s: ok"])):
            return h44.build_build_report(profile)

    def test_sections_and_content(self):
        t = self.report()
        for part in ("Travel Node", "Steps", "Still to do: L-asl3", "Warnings: L-radio", "Radio", "USRP pairs", "Tool versions", "This boot",
                     "ok: SvxLink pair", "WARN: a warning", "Phone nodes: 1001", "Raspberry Pi Zero 2 W", "ready after 4s"):
            self.assertIn(part, t)
        self.assertNotIn("SvxLink\n", t)

    def test_magic_report_has_the_svxlink_block_without_the_key(self):
        t = self.report("magic")
        self.assertIn("Magic Box", t)
        self.assertIn("password set", t)
        self.assertIn("x.example.org:5300", t)

    def test_route(self):
        with mock.patch.object(h44, "build_build_report", lambda p="travel": "text " + p):
            st, ct, body = h44._route_build_report({"profile": ["magic"]})
        self.assertEqual((st, ct.split(";")[0], body), (200, "text/plain", b"text magic"))
        with mock.patch.object(h44, "build_build_report", mock.Mock(side_effect=ValueError("secret"))):
            st, _ct, body = h44._route_build_report({})
        self.assertEqual(st, 500)
        self.assertNotIn(b"secret", body)
        self.assertIn("/api/build/report", h44._GET_ROUTES)


class Page(unittest.TestCase):
    def test_buttons_and_functions(self):
        for js, html, fn, pfx in ((h44._JS_BUILD, h44._render_build_panel(), "build", "bld"),
                                  (h44._JS_MAGIC, h44._render_magic_panel(), "magic", "mbx")):
            self.assertIn(f"{fn}RunRest(this)", html)
            self.assertIn(f"{fn}Report(this)", html)
            self.assertIn(f'id="{pfx}-report"', html)
            self.assertIn(f"function {fn}RunRest(", js)
            self.assertIn(f"function {fn}Report(", js)
            self.assertIn("/api/build/report?profile=", js)
            self.assertIn("action: 'run_rest'", js)

    def test_reboot_is_runnable_only_as_a_mark(self):
        self.assertIn("reboot", h44._BLD_RUNNABLE)
        self.assertNotIn("reboot", h44._BLD_LONG)
        self.assertNotIn("reboot", h44._BLD_PREVIEWABLE)


if __name__ == "__main__":
    unittest.main()
