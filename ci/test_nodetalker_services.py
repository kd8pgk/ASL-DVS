import glob
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import json
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nt_services_")
os.environ["NODETALKER_SUITELOG"] = os.path.join(WORK, "suitelog.jsonl")
os.environ["NODETALKER_SUITELOG_FLAG"] = os.path.join(WORK, "suitelog.on")
os.environ.setdefault("NODETALKER_CONFIG_DIR", os.path.join(WORK, "nt"))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("nt_services_under_test", newest("nodetalker_v[0-9]*.py"))
nt = importlib.util.module_from_spec(spec)
sys.modules["nt_services_under_test"] = nt
spec.loader.exec_module(nt)

NOW = 1000000.0


def block(unit, load="loaded", active="active", sub="running", result="success", status="0", restarts="0", since=None):
    began = int((NOW - since) * 1e6) if since is not None else 0
    return (f"Id={unit}.service\nLoadState={load}\nActiveState={active}\nSubState={sub}\nResult={result}\n"
            f"ExecMainStatus={status}\nNRestarts={restarts}\nActiveEnterTimestampMonotonic={began}\n")


def shown(**per_unit):
    out = []
    for key, unit in (("asterisk", "asterisk"), ("ab", "analog_bridge"), ("mmdvm", "mmdvm_bridge"), ("stfu", "stfu"),
                      ("m17", "usrp2m17")):
        kw = per_unit.get(key, {})
        out.append(block(unit, **kw))
    return "\n".join(out)


def completed(stdout="", rc=0, stderr=""):
    return subprocess.CompletedProcess(["systemctl"], rc, stdout, stderr)


class Classify(unittest.TestCase):
    def c(self, **kw):
        kv = dict(item.split("=", 1) for item in block("x", **kw).splitlines())
        return nt.svc_classify(kv, NOW)

    def test_running_shows_how_long(self):
        self.assertEqual(self.c(since=30), ("on", "Running", True))
        self.assertEqual(self.c(since=300), ("on", "Running 5 min", True))
        self.assertEqual(self.c(since=3 * 3600 + 120), ("on", "Running 3 h 2 min", True))
        self.assertEqual(self.c(since=3 * 86400 + 4 * 3600), ("on", "Running 3 d 4 h", True))

    def test_restart_loop_is_amber(self):
        light, text, _ = self.c(since=60, restarts="4")
        self.assertEqual(light, "warn")
        self.assertIn("4 restarts", text)

    def test_old_restarts_do_not_matter_once_it_has_run_a_while(self):
        self.assertEqual(self.c(since=3600, restarts="9")[0], "on")

    def test_starting_reloading_stopping_are_amber(self):
        self.assertEqual(self.c(active="activating", sub="start")[:2], ("warn", "Starting..."))
        self.assertEqual(self.c(active="activating", sub="auto-restart", restarts="2")[0], "warn")
        self.assertEqual(self.c(active="reloading", sub="reload")[0], "warn")
        self.assertEqual(self.c(active="deactivating", sub="stop")[0], "warn")

    def test_failed_and_stopped_are_red(self):
        light, text, _ = self.c(active="failed", sub="failed", result="exit-code", status="1")
        self.assertEqual((light, text), ("fail", "Failed: exit code 1"))
        self.assertEqual(self.c(active="failed", sub="failed", result="signal", status="0")[1], "Failed: killed by a signal")
        self.assertEqual(self.c(active="failed", sub="failed", result="success", status="0")[1], "Failed")
        self.assertEqual(self.c(active="inactive", sub="dead")[:2], ("fail", "Stopped"))

    def test_not_installed_is_grey_and_not_restartable(self):
        self.assertEqual(self.c(load="not-found", active="inactive", sub="dead"), ("off", "Not installed", False))

    def test_no_answer_is_amber(self):
        self.assertEqual(nt.svc_classify({}, NOW)[0], "warn")


class Registration(unittest.TestCase):
    def test_parse(self):
        head = "Host                 Username   Perceived             Refresh  State\n"
        self.assertEqual(nt.reg_parse(head + "register.allstarlink.org 27342 44.1.2.3:4569 180 Registered\n", "27342"), "registered")
        self.assertEqual(nt.reg_parse(head + "register.allstarlink.org 27342 44.1.2.3:4569 180 Rejected\n", "27342"), "unregistered")
        self.assertEqual(nt.reg_parse(head + "register.allstarlink.org 27342 - 180 Request Sent\n", "27342"), "unknown")
        self.assertEqual(nt.reg_parse(head, "27342"), "unregistered")
        self.assertEqual(nt.reg_parse(head + "x 127342 y 180 Registered\n", "27342"), "unregistered")
        self.assertEqual(nt.reg_parse(head + "register.allstarlink.org 27342 44.1.2.3:4569 180 Unregistered\n", "27342"), "unregistered")
        self.assertEqual(nt.reg_parse(head + "register.allstarlink.org 27342 - 180 Auth. Sent\n", "27342"), "unknown")
        self.assertEqual(nt.reg_parse(head + "register.allstarlink.org 27342 - 180 No Authentication\n", "27342"), "unregistered")
        self.assertEqual(nt.reg_parse(head + "other.example.org 99999 - 180 Registered\n", "27342"), "unregistered")
        self.assertEqual(nt.reg_parse("27342 registered\n", "27342"), "registered")
        self.assertEqual(nt.reg_parse("", "27342"), "unknown")
        self.assertEqual(nt.reg_parse(head, ""), "unknown")

    def reg(self, node, on=True, out=(True, "")):
        with nt._svc_lock:
            nt._reg_cache.update(t=-1e9, node="", state="unknown", detail="", since=None)
        with mock.patch.object(nt, "main_node", lambda: node), mock.patch.object(nt, "ast_cli", lambda cmd, timeout=0: out):
            return nt.svc_registration(on)

    def test_private_and_missing_nodes_are_grey(self):
        self.assertEqual(self.reg("1921")["state"], "private")
        self.assertEqual(self.reg("1000")["state"], "private")
        self.assertEqual(self.reg("")["state"], "none")

    def test_asterisk_down_is_unknown_without_asking(self):
        called = []
        with mock.patch.object(nt, "main_node", lambda: "27342"), mock.patch.object(nt, "ast_cli", lambda *a, **k: called.append(1)):
            self.assertEqual(nt.svc_registration(False)["state"], "unknown")
        self.assertFalse(called)

    def test_states_and_the_change_time(self):
        row = "register.allstarlink.org 27342 44.1.2.3:4569 180 Registered\n"
        self.assertEqual(self.reg("27342", out=(True, row))["state"], "registered")
        self.assertIsNone(nt._reg_cache["since"])
        with nt._svc_lock:
            nt._reg_cache["t"] = 1.0
        with mock.patch.object(nt, "main_node", lambda: "27342"), \
                mock.patch.object(nt, "ast_cli", lambda cmd, timeout=0: (True, row.replace("Registered", "Rejected"))):
            r = nt.svc_registration(True)
        self.assertEqual(r["state"], "unregistered")
        self.assertTrue(r["since"])

    def test_asterisk_not_answering_is_amber(self):
        self.assertEqual(self.reg("27342", out=(False, ""))["state"], "unknown")


class Status(unittest.TestCase):
    def status(self, text, stfu_by_hand=None, node="27342", reg_out=(True, "x 27342 y 1 Registered\n")):
        with nt._svc_lock:
            nt._svc_cache.update(t=-1e9, v=None)
            nt._reg_cache.update(t=-1e9, node="", state="unknown", detail="", since=None)
        with mock.patch.object(nt, "_systemctl", lambda *a, **k: completed(text)), \
                mock.patch.object(nt, "SVC_NC_FILE", os.path.join(WORK, "no-such-services.json")), \
                mock.patch.object(nt.time, "monotonic", lambda: NOW), \
                mock.patch.object(nt, "svc_stfu_by_hand", lambda: stfu_by_hand), \
                mock.patch.object(nt, "main_node", lambda: node), \
                mock.patch.object(nt, "ast_cli", lambda cmd, timeout=0: reg_out):
            return nt.svc_status()

    def test_five_services_in_order(self):
        d = self.status(shown())
        self.assertEqual([r["key"] for r in d["services"]], ["asterisk", "ab", "mmdvm", "stfu", "m17"])
        self.assertEqual([r["unit"] for r in d["services"]],
                         ["asterisk.service", "analog_bridge.service", "mmdvm_bridge.service", "stfu.service", "usrp2m17.service"])
        self.assertTrue(all(r["light"] == "on" and r["restartable"] for r in d["services"]))
        self.assertEqual(d["reg"]["state"], "registered")
        self.assertEqual(d["source"], "nodetalker")

    def test_a_failed_bridge_and_a_missing_service(self):
        d = self.status(shown(ab=dict(active="failed", sub="failed", result="exit-code", status="3"),
                              stfu=dict(load="not-found", active="inactive", sub="dead")))
        rows = {r["key"]: r for r in d["services"]}
        self.assertEqual(rows["ab"]["light"], "fail")
        self.assertTrue(rows["ab"]["restartable"])
        self.assertEqual(rows["stfu"]["light"], "off")
        self.assertFalse(rows["stfu"]["restartable"])

    def test_asterisk_down_makes_registration_unknown(self):
        d = self.status(shown(asterisk=dict(active="inactive", sub="dead")))
        self.assertEqual(d["services"][0]["light"], "fail")
        self.assertEqual(d["reg"]["state"], "unknown")

    def test_stfu_started_by_hand(self):
        d = self.status(shown(stfu=dict(load="not-found", active="inactive", sub="dead")), stfu_by_hand=True)
        row = next(r for r in d["services"] if r["key"] == "stfu")
        self.assertEqual(row["light"], "on")
        self.assertFalse(row["restartable"])

    def test_systemd_giving_nothing_is_amber_not_red(self):
        d = self.status("")
        self.assertTrue(all(r["light"] == "warn" for r in d["services"]))

    def test_answers_are_cached_for_a_few_seconds(self):
        self.status(shown())
        calls = []
        with mock.patch.object(nt, "_systemctl", lambda *a, **k: calls.append(1) or completed("")), \
                mock.patch.object(nt, "SVC_NC_FILE", os.path.join(WORK, "no-such-services.json")), \
                mock.patch.object(nt.time, "monotonic", lambda: NOW + 1):
            nt.svc_status()
        self.assertFalse(calls)


class Restart(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.logs = []
        patches = [
            mock.patch.object(nt.os, "geteuid", lambda: 0),
            mock.patch.object(nt, "log_event", lambda m, level="info": self.logs.append(m)),
            mock.patch.object(nt, "service_states", lambda units: {u: "active" for u in units}),
            mock.patch.object(nt, "_lstats_invalidate", lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with nt._svc_lock:
            nt._svc_busy.clear()

    def run_restart(self, key, rc=0, err=""):
        def fake(*args, **kw):
            self.calls.append(args)
            return completed("", rc, err)
        with mock.patch.object(nt, "_systemctl", fake):
            return nt.svc_restart({"key": key})

    def test_only_the_five_services_can_be_restarted(self):
        for bad in ("", "nodetalker", "../asterisk", "asterisk.service", "sshd", None):
            r = nt.svc_restart({"key": bad})
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"], "Unknown service.")
        self.assertFalse(self.calls)

    def test_a_bridge_restarts_its_own_unit(self):
        r = self.run_restart("ab")
        self.assertTrue(r["ok"])
        self.assertEqual(self.calls, [("restart", "analog_bridge.service")])
        self.assertTrue(any("Analog Bridge restarted" in m for m in self.logs))

    def test_each_key_maps_to_its_unit(self):
        for key, unit in (("mmdvm", "mmdvm_bridge.service"), ("stfu", "stfu.service"), ("m17", "usrp2m17.service")):
            self.calls.clear()
            self.assertTrue(self.run_restart(key)["ok"])
            self.assertEqual(self.calls, [("restart", unit)])

    def test_asterisk_uses_the_existing_restart(self):
        with mock.patch.object(nt, "restart_asterisk", lambda: {"ok": True, "message": "Asterisk restarted."}):
            self.assertEqual(nt.svc_restart({"key": "asterisk"})["message"], "Asterisk restarted.")

    def test_failure_text_is_returned(self):
        r = self.run_restart("mmdvm", rc=1, err="Job failed")
        self.assertEqual(r, {"ok": False, "error": "Job failed"})

    def test_not_installed_and_not_root(self):
        with mock.patch.object(nt, "service_states", lambda units: {u: "missing" for u in units}):
            self.assertIn("not installed", self.run_restart("stfu")["error"])
        with mock.patch.object(nt.os, "geteuid", lambda: 1000):
            self.assertIn("root", self.run_restart("ab")["error"])
        self.assertFalse(self.calls)

    def test_a_second_restart_of_the_same_service_is_refused(self):
        with nt._svc_lock:
            nt._svc_busy["ab"] = 1.0
        self.assertIn("already restarting", self.run_restart("ab")["error"])
        self.assertEqual(self.run_restart("mmdvm")["ok"], True)

    def test_the_lock_is_released_after_a_failure(self):
        self.run_restart("ab", rc=1, err="x")
        self.assertNotIn("ab", nt._svc_busy)

    def test_a_recording_gets_the_question_with_the_service_name(self):
        rec = {"name": "Net night"}
        with mock.patch.object(nt, "recorder_info", lambda: {"x": 1}), mock.patch.object(nt, "_rec_list", lambda info: [rec]), \
                mock.patch.object(nt, "_rec_names", lambda recs: "Net night"):
            need = nt.rec_confirm_needed("/api/services/restart", {"key": "mmdvm"})
        self.assertEqual(need["kind"], "power")
        self.assertIn("Restarting MMDVM Bridge", need["message"])


class FromNodeController(unittest.TestCase):
    NOWE = 2000000.0

    def doc(self, **over):
        rows = [{"key": k, "label": l, "unit": units[0] + ".service", "light": "on", "detail": "Running",
                 "installed": True, "restartable": True} for k, l, units in nt.svc_table()]
        d = {"version": 1, "source": "nodecontrol", "host_version": "9.3.114-pi02w", "checked_at": self.NOWE - 8,
             "next_check_secs": 15.0, "reg": {"state": "registered", "node": "27342", "detail": "Registered", "since": None},
             "services": rows}
        d.update(over)
        return d

    def setUp(self):
        self.path = os.path.join(WORK, "services.json")
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        p = mock.patch.object(nt, "SVC_NC_FILE", self.path)
        p.start()
        self.addCleanup(p.stop)
        with nt._svc_lock:
            nt._svc_cache.update(t=-1e9, v=None)
            nt._svc_own_until["t"] = 0.0

    def put(self, doc):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(doc if isinstance(doc, str) else json.dumps(doc))

    def read(self, doc):
        self.put(doc)
        return nt.svc_from_nc(self.NOWE)

    def test_a_good_file_is_accepted(self):
        d = self.read(self.doc())
        self.assertEqual(d["source"], "nodecontrol")
        self.assertEqual(d["age_s"], 8.0)
        self.assertEqual(len(d["services"]), 5)
        self.assertEqual(d["reg"]["state"], "registered")

    def test_no_file_gives_none(self):
        self.assertIsNone(nt.svc_from_nc(self.NOWE))

    def test_old_future_and_nonsense_times_are_refused(self):
        for at in (self.NOWE - 100, self.NOWE + 60, "now", True, None):
            self.assertIsNone(self.read(self.doc(checked_at=at)), at)
        self.assertIsNotNone(self.read(self.doc(checked_at=self.NOWE - 40)))
        self.assertIsNone(self.read(self.doc(next_check_secs=0)))
        self.assertIsNone(self.read(self.doc(next_check_secs=99999)))

    def test_the_wait_follows_the_writers_own_interval(self):
        self.assertIsNotNone(self.read(self.doc(checked_at=self.NOWE - 100, next_check_secs=60.0)))
        self.assertIsNone(self.read(self.doc(checked_at=self.NOWE - 200, next_check_secs=60.0)))

    def test_wrong_version_or_source_or_shape_is_refused(self):
        for bad in (self.doc(version=2), self.doc(source="sysmon"), self.doc(reg=None), self.doc(services="x"),
                    self.doc(reg={"state": "great"}), [], "[1,2]", "not json", "{"):
            self.assertIsNone(self.read(bad), bad)

    def test_a_missing_extra_or_odd_service_row_is_refused(self):
        d = self.doc()
        self.assertIsNone(self.read(dict(d, services=d["services"][:4])))
        rows = [dict(r) for r in d["services"]]
        rows[1]["light"] = "purple"
        self.assertIsNone(self.read(dict(d, services=rows)))
        rows = [dict(r) for r in d["services"]]
        rows[2]["unit"] = "sshd.service"
        self.assertIsNone(self.read(dict(d, services=rows)))
        rows = [dict(r) for r in d["services"]]
        rows[0]["restartable"] = "yes"
        self.assertIsNone(self.read(dict(d, services=rows)))

    def test_labels_come_from_node_talker_and_text_is_cut(self):
        d = self.doc()
        rows = [dict(r) for r in d["services"]]
        rows[0]["label"] = "<script>x</script>"
        rows[0]["detail"] = "y" * 5000
        out = self.read(dict(d, services=rows))
        self.assertEqual(out["services"][0]["label"], "Asterisk")
        self.assertEqual(len(out["services"][0]["detail"]), 160)

    def test_the_capital_a_unit_is_allowed_for_analog_bridge_only(self):
        d = self.doc()
        rows = [dict(r) for r in d["services"]]
        rows[1]["unit"] = "Analog_Bridge.service"
        self.assertIsNotNone(self.read(dict(d, services=rows)))

    def test_big_files_and_links_are_refused(self):
        self.put(self.doc())
        with mock.patch.object(nt, "SVC_NC_MAX_BYTES", 50):
            self.assertIsNone(nt.svc_from_nc(self.NOWE))
        os.remove(self.path)
        target = os.path.join(WORK, "real.json")
        with open(target, "w") as fh:
            json.dump(self.doc(), fh)
        os.symlink(target, self.path)
        self.assertIsNone(nt.svc_from_nc(self.NOWE))

    def test_a_file_owned_by_someone_else_is_refused_when_running_as_root(self):
        self.put(self.doc())
        with mock.patch.object(nt.os, "geteuid", lambda: 0), \
                mock.patch.object(nt.os, "lstat", lambda p: types.SimpleNamespace(st_mode=0o100644, st_size=100, st_uid=1000)):
            self.assertIsNone(nt.svc_from_nc(self.NOWE))

    def test_since_is_kept_only_when_it_is_a_sane_time(self):
        d = self.doc(reg={"state": "unregistered", "node": "27342", "detail": "Not registered", "since": self.NOWE - 60})
        self.assertEqual(self.read(d)["reg"]["since"], self.NOWE - 60)
        d = self.doc(reg={"state": "unregistered", "node": "27342", "detail": "x", "since": self.NOWE + 9999})
        self.assertIsNone(self.read(d)["reg"]["since"])

    def test_status_prefers_the_file_then_falls_back(self):
        fresh = self.doc(checked_at=time.time() - 3)
        self.put(fresh)
        self.assertEqual(nt.svc_status()["source"], "nodecontrol")
        os.remove(self.path)
        with nt._svc_lock:
            nt._svc_cache.update(t=-1e9, v=None)
        with mock.patch.object(nt, "_systemctl", lambda *a, **k: completed(shown())), \
                mock.patch.object(nt, "main_node", lambda: "27342"), \
                mock.patch.object(nt, "ast_cli", lambda cmd, timeout=0: (True, "x 27342 y 1 Registered\n")), \
                mock.patch.object(nt, "svc_stfu_by_hand", lambda: None), \
                mock.patch.object(nt.time, "monotonic", lambda: NOW):
            self.assertEqual(nt.svc_status()["source"], "nodetalker")

    def test_after_a_restart_node_talker_looks_for_itself_for_a_while(self):
        self.put(self.doc(checked_at=time.time() - 3))
        with nt._svc_lock:
            nt._svc_own_until["t"] = nt.time.monotonic() + 20
            nt._svc_cache.update(t=-1e9, v=None)
        with mock.patch.object(nt, "_systemctl", lambda *a, **k: completed(shown())), \
                mock.patch.object(nt, "main_node", lambda: "27342"), \
                mock.patch.object(nt, "ast_cli", lambda cmd, timeout=0: (True, "x 27342 y 1 Registered\n")), \
                mock.patch.object(nt, "svc_stfu_by_hand", lambda: None):
            self.assertEqual(nt.svc_status()["source"], "nodetalker")

    def test_a_restart_starts_that_window(self):
        with mock.patch.object(nt.os, "geteuid", lambda: 0), mock.patch.object(nt, "log_event", lambda *a, **k: None), \
                mock.patch.object(nt, "service_states", lambda units: {u: "active" for u in units}), \
                mock.patch.object(nt, "_systemctl", lambda *a, **k: completed("")):
            nt._svc_own_until["t"] = 0.0
            self.assertTrue(nt.svc_restart({"key": "ab"})["ok"])
        self.assertGreater(nt._svc_own_until["t"], nt.time.monotonic() + 10)

    def test_footer_names_the_source(self):
        html = nt.render_page().decode("utf-8")
        for n in ("d.source === 'nodecontrol' ? 'Node Controller'", 'id="sv-age"', "' s old)'"):
            self.assertIn(n, html, n)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = nt.render_page().decode("utf-8")

    def test_the_card_sits_under_links_and_starts_open(self):
        h = self.html
        self.assertLess(h.index('id="cd-links"'), h.index('id="cd-svc"'))
        self.assertLess(h.index('id="cd-svc"'), h.index('id="cd-setup"'))
        card = h[h.index('id="cd-svc"'):h.index('id="cd-setup"')]
        self.assertIn('aria-expanded="true"', card)
        self.assertIn('<div class="fold-body" id="cb-svc">', card)
        self.assertNotIn("fold-body hidden", card)

    def test_registration_row_is_above_the_services(self):
        card = self.html[self.html.index('id="cd-svc"'):self.html.index('id="cd-setup"')]
        self.assertLess(card.index('id="sv-reg"'), card.index('id="sv-list"'))
        for n in ('id="sv-msg"', 'id="sv-src"', "Not installed"):
            self.assertIn(n, card)

    def test_restart_goes_through_the_recording_question(self):
        self.assertIn("'/api/services/restart'];", self.html)
        self.assertIn("/api/services/restart", nt._RECORDING_POWER)
        self.assertIn("/api/services/restart", nt._POST_ACTIONS)

    def test_script_wiring(self):
        for n in ("const FOLDS = ['svc',", "if (k === 'svc') svcPoll();", "setInterval(svcTick, 10000);",
                  "async function svcRestart(key, label)", "document.visibilityState !== 'visible' || !foldOpen('svc')",
                  "post('/api/services/restart', {key: key})", "api('/api/services')"):
            self.assertIn(n, self.html, n)

    def test_service_text_is_set_as_text_not_html(self):
        js = self.html[self.html.index("function svcRender(d)"):self.html.index("async function svcRestart")]
        self.assertNotIn("innerHTML = s", js)
        self.assertEqual(js.count("innerHTML"), 1)
        self.assertIn("det.textContent = detail;", js)

    def test_dots_use_the_sysmon_glow(self):
        for n in (".sv-dot.sv-on{", ".sv-dot.sv-warn{", ".sv-dot.sv-fail{", "box-shadow:0 0 8px var(--accent)"):
            self.assertIn(n, self.html)


if __name__ == "__main__":
    unittest.main()
