import glob
import importlib.util
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_install_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_install_under_test"] = h44
spec.loader.exec_module(h44)

FORM = {"mode": "half", "callsign": "KD8PGK", "node": "652701", "dmr_id": "3123456", "nxdn_id": "",
        "m17_node": "1917", "usb": "", "bypass": "", "svx_use": "bridge", "svx_host": "", "svx_port": "",
        "svx_tg": "0", "svx_mon": ""}
KEY = "yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk="
PUB = "xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg="
WG = f"[Interface]\nPrivateKey = {KEY}\nAddress = 44.1.2.3/32\n[Peer]\nPublicKey = {PUB}\nEndpoint = 1.2.3.4:51820\nAllowedIPs = 0.0.0.0/0\n"


def plan(sid, form=None, codename="bookworm", rpt=""):
    with mock.patch.object(h44, "_bld_codename", lambda: codename), \
            mock.patch.object(h44, "_bld_read", lambda path: rpt if path == h44._BLD_RPT else ""):
        return h44._bld_install_plan(sid, dict(FORM, **(form or {})))


class Plans(unittest.TestCase):
    def ids(self, sid, **kw):
        r = plan(sid, **kw)
        self.assertNotIsInstance(r, str, r)
        return [s["id"] for s in r[1]]

    def test_every_planned_step_exists_and_validates_for_every_system(self):
        for sid in ("asl3", "dvs", "m17", "svx"):
            r = plan(sid)
            self.assertNotIsInstance(r, str, r)
            spec_, steps = r
            self.assertTrue(steps)
            for st in steps:
                step = spec_["lookup"]("install", spec_["distro"], st["id"])
                self.assertIsNotNone(step, st["id"])
                self.assertFalse(step.get("manual"), st["id"])
                cmd, why = h44._step_command(step, st["fields"])
                self.assertEqual(why, "", st["id"])
                self.assertEqual(cmd, st["cmd"])
                self.assertNotIn("{{", cmd)

    def test_no_planned_step_needs_a_secret(self):
        for sid in ("asl3", "dvs", "m17", "svx"):
            for st in plan(sid)[1]:
                self.assertNotIn("password", st["fields"])
                self.assertNotIn("refl_key", st["fields"])

    def test_asl3_leaves_out_what_the_bundle_and_node_monitor_replace(self):
        ids = self.ids("asl3")
        for skipped in ("run_asl_menu", "allmon3_set_admin", "enable_allmon3", "install_cockpit", "install_appliance",
                        "asl3_save_restore"):
            self.assertNotIn(skipped, ids)
        self.assertIn("allmon3_delete_default", ids)
        self.assertIn("install_asl3_core", ids)

    def test_a_soft_step_is_only_the_default_account_removal(self):
        self.assertEqual([s["id"] for s in plan("asl3")[1] if s["soft"]], ["allmon3_delete_default"])
        for sid in ("dvs", "m17", "svx"):
            self.assertFalse([s for s in plan(sid)[1] if s["soft"]])

    def test_dvswitch_needs_bookworm(self):
        self.assertIsInstance(plan("dvs", codename="trixie"), str)
        self.assertIn("Bookworm", plan("dvs", codename="trixie"))
        ids = self.ids("dvs")
        self.assertNotIn("configure_node_identity", ids)
        self.assertNotIn("dv_save_restore", ids)

    def test_m17_skips_the_node_step_when_the_node_exists(self):
        self.assertIn("m17_asterisk_conf", self.ids("m17"))
        self.assertNotIn("m17_asterisk_conf", self.ids("m17", rpt="[1917](node-main)\nrxchannel = x\n"))
        self.assertIn("m17_asterisk_conf", self.ids("m17", rpt="[1918](node-main)\n"))
        self.assertIn("m17_restart_asterisk", self.ids("m17", rpt="[1917]\n"))

    def test_m17_fields_come_from_the_form(self):
        by = {s["id"]: s for s in plan("m17", {"m17_node": "1930"})[1]}
        self.assertEqual(by["m17_run_install"]["fields"], {"callsign": "KD8PGK"})
        self.assertEqual(by["m17_asterisk_conf"]["fields"], {"node": "1930"})

    def test_svx_uses_the_bridge_ports_and_the_form_answer(self):
        by = {s["id"]: s for s in plan("svx", {"svx_use": "radio"})[1]}
        f = by["usrp_logic_conf"]["fields"]
        self.assertEqual((f["rx_port"], f["port"], f["svx_use"], f["callsign"]), ("34000", "32000", "radio", "KD8PGK"))
        self.assertNotIn("usrp_refl_conn", by)
        self.assertNotIn("usrp_refl_test", by)

    def test_a_bad_field_stops_the_plan_before_anything_starts(self):
        r = plan("m17", {"callsign": "bad call!"})
        self.assertIsInstance(r, str)
        self.assertIn("Nothing was started", r)


class Worker(unittest.TestCase):
    def run_plan(self, steps, results, soft=()):
        spec_ = {"prefix": "asl3", "lookup": None, "valid": ("bookworm",), "distro": "bookworm", "name": "Test"}
        plan_ = [{"id": s, "num": i + 1, "title": s, "cmd": "c", "fields": {}, "soft": s in soft} for i, s in enumerate(steps)]
        started, appended = [], []

        def fake_dispatch(payload, lookup, prefix, valid):
            started.append(payload["step_id"])
            res = results[payload["step_id"]]
            return res if "job_key" not in res else {"job_key": "j_" + payload["step_id"], "status": "running"}

        def fake_status(key):
            if key.startswith("j_"):
                step = key[2:]
                res = results[step]
                return {"status": "done", "success": res["job_key"] == "ok", "output": "out of " + step + "\n"}
            return {"status": "running", "output": "".join(appended)}

        with mock.patch.object(h44, "_dispatch_tab_action", fake_dispatch), \
                mock.patch.object(h44, "_job_status", fake_status), \
                mock.patch.object(h44, "_job_append_output", lambda k, t: appended.append(t)), \
                mock.patch.object(h44.time, "sleep", lambda s: None):
            out = h44._bld_install_worker("build_x_y", spec_, plan_)
        return out, started, "".join(appended)

    def test_runs_every_step_in_order(self):
        out, started, text = self.run_plan(["a", "b", "c"], {k: {"job_key": "ok"} for k in "abc"})
        self.assertTrue(out["success"])
        self.assertEqual(started, ["a", "b", "c"])
        self.assertIn("out of b", text)
        self.assertTrue(out["output"].endswith("Done."))

    def test_stops_at_the_first_failure(self):
        out, started, _ = self.run_plan(["a", "b", "c"], {"a": {"job_key": "ok"}, "b": {"job_key": "bad"}, "c": {"job_key": "ok"}})
        self.assertFalse(out["success"])
        self.assertEqual(started, ["a", "b"])
        self.assertIn("safe to repeat", out["output"])

    def test_a_step_that_does_not_start_is_a_failure(self):
        out, started, text = self.run_plan(["a", "b"], {"a": {"success": False, "output": "masked services", "status": "done"},
                                                        "b": {"job_key": "ok"}})
        self.assertFalse(out["success"])
        self.assertEqual(started, ["a"])
        self.assertIn("masked services", text)

    def test_a_soft_failure_carries_on(self):
        out, started, _ = self.run_plan(["a", "b"], {"a": {"job_key": "bad"}, "b": {"job_key": "ok"}}, soft=("a",))
        self.assertTrue(out["success"])
        self.assertEqual(started, ["a", "b"])
        out, started, _ = self.run_plan(["a", "b"], {"a": {"success": False, "output": "x", "status": "done"}, "b": {"job_key": "ok"}}, soft=("a",))
        self.assertTrue(out["success"])

    def test_wait_times_out(self):
        with mock.patch.object(h44, "_job_status", lambda k: {"status": "running", "output": "x"}), \
                mock.patch.object(h44, "_job_append_output", lambda k, t: None), \
                mock.patch.object(h44.time, "sleep", lambda s: None):
            t = iter(range(0, 100000, 5000))
            with mock.patch.object(h44.time, "time", lambda: next(t)):
                st = h44._bld_wait_job("j", "b", 7200)
        self.assertTrue(st.get("timeout"))
        self.assertFalse(st["success"])


class Tunnel(unittest.TestCase):
    def names(self, mode):
        return [n for n, _ in h44._bld_tunnel_plan(dict(FORM, mode=mode), WG)]

    def test_steps_and_services_follow_the_mode(self):
        half = self.names("half")
        self.assertEqual(half[:3], ["Firewall prereq", "systemd-resolved prereq", "44NetConnect zone"])
        self.assertEqual(half[-3:], ["Write wg0.conf", "Attach wg0 to the zone", "Enable and start the tunnel"])
        self.assertIn("Inbound service iax2", half)
        self.assertNotIn("Inbound service echolink", half)
        self.assertNotIn("Inbound service echolink", self.names("split"))
        self.assertIn("Inbound service echolink", self.names("full"))
        self.assertNotIn("Inbound service rtcm", self.names("full"))

    def test_the_config_is_written_in_the_modes_shape(self):
        seen = []
        with mock.patch.dict(h44._PI_INSTALL_SIMPLE_ACTIONS, {"paste_config": lambda p: seen.append(p) or {"success": True}}):
            for mode, kind in (("half", "split"), ("split", "split"), ("full", "full")):
                steps = dict(h44._bld_tunnel_plan(dict(FORM, mode=mode), WG))
                steps["Write wg0.conf"]()
                self.assertEqual(seen[-1]["kind"], kind)
        self.assertEqual(seen[-1]["opts"], {"allowed": "rewrite"})
        self.assertIs(seen[-1]["backup_to_library"], True)
        self.assertEqual(seen[-1]["config_text"], WG)

    def test_the_worker_stops_at_the_first_failing_action(self):
        ran = []
        steps = [("one", lambda: ran.append(1) or {"success": True, "output": "ok1"}),
                 ("two", lambda: ran.append(2) or {"success": False, "output": "bad2"}),
                 ("three", lambda: ran.append(3) or {"success": True})]
        with mock.patch.object(h44, "_job_append_output", lambda k, t: None), \
                mock.patch.object(h44, "_job_status", lambda k: {"output": ""}):
            out = h44._bld_tunnel_worker("build_x_tunnel", steps)
        self.assertFalse(out["success"])
        self.assertEqual(ran, [1, 2])

    def test_an_exception_does_not_leak_text(self):
        def boom():
            raise ValueError("PrivateKey = SECRETVALUE")
        appended = []
        with mock.patch.object(h44, "_job_append_output", lambda k, t: appended.append(t)), \
                mock.patch.object(h44, "_job_status", lambda k: {"output": "".join(appended)}):
            out = h44._bld_tunnel_worker("build_x_tunnel", [("one", boom)])
        self.assertFalse(out["success"])
        self.assertNotIn("SECRETVALUE", out["output"])

    def test_lan_check(self):
        for ip in ("127.0.0.1", "192.168.1.5", "10.0.0.7", "172.16.4.4", "fe80::1"):
            self.assertTrue(h44._bld_client_ok(ip), ip)
        for ip in ("44.27.1.1", "8.8.8.8", "", "nonsense"):
            self.assertFalse(h44._bld_client_ok(ip), ip)


class Start(unittest.TestCase):
    def start(self, sid, payload=None, running="", **kw):
        started = []
        with mock.patch.object(h44, "_bld_running_job", lambda: running), \
                mock.patch.object(h44, "_start_python_job", lambda key, fn: started.append(key) or {"job_key": key}), \
                mock.patch.object(h44, "_bld_codename", lambda: "bookworm"), \
                mock.patch.object(h44, "_bld_read", lambda p: ""):
            res = h44._bld_start_long(sid, "travel", dict(FORM, **kw), dict({"_client_ip": "192.168.1.9"}, **(payload or {})))
        return res, started

    def test_install_starts_one_background_job(self):
        res, started = self.start("dvs")
        self.assertTrue(res["success"])
        self.assertEqual(started, ["build_travel_dvs"])
        self.assertEqual(res["job_key"], "build_travel_dvs")
        self.assertTrue(res["notes"])

    def test_only_one_build_job_at_a_time(self):
        res, started = self.start("asl3", running="build_travel_dvs")
        self.assertFalse(res["success"])
        self.assertEqual(started, [])

    def test_tunnel_needs_the_lan_and_a_config(self):
        self.assertFalse(self.start("tunnel", {"_client_ip": "44.27.0.1", "config_text": WG})[0]["success"])
        self.assertFalse(self.start("tunnel", {"_client_ip": "8.8.8.8", "config_text": WG})[0]["success"])
        self.assertIn("Paste", self.start("tunnel", {"config_text": "  "})[0]["message"])
        bad = self.start("tunnel", {"config_text": "not wireguard"})
        self.assertFalse(bad[0]["success"])
        self.assertEqual(bad[1], [])
        ok = self.start("tunnel", {"config_text": WG})
        self.assertTrue(ok[0]["success"])
        self.assertEqual(ok[1], ["build_travel_tunnel"])

    def test_the_config_never_comes_back_in_the_reply(self):
        res, _ = self.start("tunnel", {"config_text": WG})
        self.assertNotIn(KEY, str(res))
        res, _ = self.start("tunnel", {"config_text": "PrivateKey = SECRETVALUE junk"})
        self.assertNotIn("SECRETVALUE", str(res))


class RunStage(unittest.TestCase):
    def st(self, sid, state="todo", errors=None):
        return {"form": dict(FORM), "errors": errors or {}, "radio": {"cards": []},
                "stages": [{"id": sid, "label": "L", "state": state, "detail": "d"}]}

    def go(self, sid, state="todo", errors=None, **extra):
        with mock.patch.object(h44, "build_build_status", lambda profile="travel": self.st(sid, state, errors)), \
                mock.patch.object(h44, "_bld_start_long", lambda s, p, f, pl: {"success": True, "message": "started", "job_key": "k"}):
            return h44._bld_act_run_stage(dict({"stage": sid, "profile": "travel"}, **extra))

    def test_long_stages_start_a_job(self):
        for sid in h44._BLD_LONG:
            self.assertEqual(self.go(sid)["job_key"], "k", sid)

    def test_long_stages_refuse_locked_done_preview_and_a_bad_form(self):
        self.assertIn("waits", self.go("asl3", "locked")["message"])
        self.assertIn("Nothing to do", self.go("asl3", "done")["message"])
        self.assertIn("no preview", self.go("asl3", preview=True)["message"])
        self.assertIn("Fix the form", self.go("asl3", errors={"node": "required"})["message"])

    def test_the_long_stages_are_runnable_and_flagged(self):
        self.assertTrue(h44._BLD_LONG <= h44._BLD_RUNNABLE)
        self.assertFalse(h44._BLD_LONG & h44._BLD_PREVIEWABLE)
        for never in ("half", "fullx", "svx_reflector", "reboot", "preflight"):
            self.assertNotIn(never, h44._BLD_RUNNABLE)

    def test_the_post_route_passes_the_client_address(self):
        with open(newest("44helper_v[0-9]*.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('payload["_client_ip"] = self._client_ip()\n            result = _dispatch_build_action(payload)', src)


class JobInfo(unittest.TestCase):
    def test_latest_job_of_the_profile(self):
        jobs = {"build_travel_asl3": {"started_at": 1, "status": "done"}, "build_travel_dvs": {"started_at": 5, "status": "running"},
                "build_magic_svx": {"started_at": 9, "status": "running"}, "pi_x": {"started_at": 99, "status": "running"}}
        with mock.patch.dict(h44._JOBS, jobs, clear=True), \
                mock.patch.object(h44, "_job_status", lambda k: {"status": jobs[k]["status"], "success": None, "output": "x" * 7000}):
            info = h44._bld_job_info("travel")
            self.assertEqual((info["key"], info["stage"], info["status"]), ("build_travel_dvs", "dvs", "running"))
            self.assertEqual(len(info["output"]), 6000)
            self.assertEqual(h44._bld_job_info("magic")["stage"], "svx")
            self.assertEqual(h44._bld_running_job(), "build_travel_dvs")
        with mock.patch.dict(h44._JOBS, {}, clear=True):
            self.assertIsNone(h44._bld_job_info("travel"))
            self.assertEqual(h44._bld_running_job(), "")


class Nxdn(unittest.TestCase):
    M = {"fields": [{"id": "callsign", "label": "Callsign", "token": "@@C@@", "pattern": "^[A-Za-z0-9]{3,10}$", "upper": True},
                    {"id": "nxdn_id", "label": "NXDN ID", "token": "@@N@@", "pattern": "^[0-9]{1,5}$"}], "derived": []}

    def test_blank_nxdn_is_accepted(self):
        tokens, why = h44._fcr_tokens(self.M, {"values": {"callsign": "kd8pgk", "nxdn_id": ""}})
        self.assertEqual((why, tokens), ("", {"@@C@@": "KD8PGK", "@@N@@": ""}))
        tokens, why = h44._fcr_tokens(self.M, {"values": {"callsign": "kd8pgk"}})
        self.assertEqual(why, "")

    def test_a_bad_nxdn_and_a_blank_callsign_are_still_refused(self):
        self.assertIn("NXDN ID", h44._fcr_tokens(self.M, {"values": {"callsign": "kd8pgk", "nxdn_id": "123456"}})[1])
        self.assertIn("Callsign", h44._fcr_tokens(self.M, {"values": {"callsign": "", "nxdn_id": ""}})[1])

    def test_only_nxdn_is_optional(self):
        self.assertEqual(h44._FCR_OPTIONAL_FIELDS, frozenset({"nxdn_id"}))


class Page(unittest.TestCase):
    def test_both_pages_poll_and_send_the_tunnel_config(self):
        for js, fn in ((h44._JS_BUILD, "build"), (h44._JS_MAGIC, "magic")):
            self.assertIn(f"function {fn}Poll(", js)
            self.assertIn("/api/action_status?job_key=", js)
            self.assertIn("config_text", js)
            self.assertIn("isLong", js)
            self.assertIn("d.job.status === 'running'", js)

    def test_nxdn_is_labelled_optional(self):
        self.assertIn("NXDN ID (optional)", h44._render_build_panel())


if __name__ == "__main__":
    unittest.main()
