import glob
import json
import importlib.util
import os
import re
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nc_services_")
os.environ["NODECONTROL_CONFIG_DIR"] = os.path.join(WORK, "nc")
os.environ["NODETALKER_SUITELOG"] = os.path.join(WORK, "suitelog.jsonl")
os.environ["NODETALKER_SUITELOG_FLAG"] = os.path.join(WORK, "suitelog.on")
os.environ.setdefault("NODETALKER_CONFIG_DIR", os.path.join(WORK, "nt"))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ncp = load("ncp_services_under_test", newest("nodecontrol_pi02w_v[0-9]*.py"))
ncf = load("ncf_services_under_test", newest("nodecontrol_v[0-9]*.py"))
nt = load("nt_services_for_nc", newest("nodetalker_v[0-9]*.py"))

NOW = 1000000.0


def block(unit, load="loaded", active="active", sub="running", since=3600, restarts="0"):
    return (f"Id={unit}.service\nLoadState={load}\nActiveState={active}\nSubState={sub}\nResult=success\n"
            f"ExecMainStatus=0\nNRestarts={restarts}\nActiveEnterTimestampMonotonic={int((NOW - since) * 1e6)}\n")


def systemd(**over):
    units = (("asterisk", "asterisk"), ("ab", "analog_bridge"), ("ab_cap", "Analog_Bridge"), ("mmdvm", "mmdvm_bridge"),
             ("stfu", "stfu"), ("m17", "usrp2m17"))
    out = []
    for key, unit in units:
        kw = over.get(key)
        out.append(block(unit, **kw) if kw else (block(unit, load="not-found", active="inactive", sub="dead")
                                                  if key == "ab_cap" else block(unit)))
    return "\n".join(out).strip()


class WriterTests:
    def setUp(self):
        self.path = os.path.join(WORK, "run", "services.json")
        self.text = systemd()
        self.reg_out = "register.allstarlink.org 27342 44.1.2.3:4569 180 Registered\n"
        patches = [
            mock.patch.object(self.mod, "SVC_STATUS_FILE", self.path),
            mock.patch.object(self.mod, "run", lambda cmd, timeout=10: (self.text, 0)),
            mock.patch.object(self.mod.time, "monotonic", lambda: NOW),
            mock.patch.object(self.mod._cfg, "asl_node", "27342", create=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with self.mod._asl_reg_lock:
            self.mod._asl_reg_info.update(state="registered", node="27342", at=NOW - 5, since=NOW - 5)
            self.mod._asl_reg_info.pop("changed", None)

    def write(self):
        self.mod._svc_file_write()
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_file_has_the_agreed_shape(self):
        d = self.write()
        self.assertEqual((d["version"], d["source"], d["host_version"]), (1, "nodecontrol", self.mod.VERSION))
        self.assertEqual(d["next_check_secs"], self.mod._SVC_CHECK_SEC)
        self.assertEqual([r["key"] for r in d["services"]], ["asterisk", "ab", "mmdvm", "stfu", "m17"])
        self.assertTrue(all(r["light"] == "on" for r in d["services"]))
        self.assertEqual(d["reg"]["state"], "registered")
        self.assertIsNone(d["reg"]["since"])
        self.assertAlmostEqual(d["checked_at"], time.time(), delta=5)

    def test_file_is_readable_by_everyone_and_replaced_whole(self):
        self.write()
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)
        self.assertEqual([f for f in os.listdir(os.path.dirname(self.path)) if f.endswith(".tmp")], [])

    def test_a_stopped_bridge_is_red_and_the_capital_a_unit_is_found(self):
        self.text = systemd(ab=dict(load="not-found", active="inactive", sub="dead"),
                            ab_cap=dict(active="failed", sub="failed"))
        d = self.write()
        ab = next(r for r in d["services"] if r["key"] == "ab")
        self.assertEqual((ab["light"], ab["unit"]), ("fail", "Analog_Bridge.service"))

    def test_registration_follows_the_node_and_asterisk(self):
        with mock.patch.object(self.mod._cfg, "asl_node", "1921", create=True):
            self.assertEqual(self.write()["reg"]["state"], "private")
        with mock.patch.object(self.mod._cfg, "asl_node", "", create=True):
            self.assertEqual(self.write()["reg"]["state"], "none")
        self.text = systemd(asterisk=dict(active="inactive", sub="dead"))
        self.assertEqual(self.write()["reg"]["state"], "unknown")

    def test_since_only_after_a_change(self):
        with self.mod._asl_reg_lock:
            self.mod._asl_reg_info.update(state="unregistered", changed=True, since=NOW - 120)
        d = self.write()
        self.assertEqual(d["reg"]["state"], "unregistered")
        self.assertAlmostEqual(d["reg"]["since"], time.time() - 120, delta=5)

    def test_check_marks_a_change_but_not_the_first_answer(self):
        with self.mod._asl_reg_lock:
            self.mod._asl_reg_info.update(state="unknown", node="", at=0.0, since=NOW)
            self.mod._asl_reg_info.pop("changed", None)
        with mock.patch.object(self.mod, "ami_command", lambda cmd, timeout=4: (self.reg_out, True)), \
                mock.patch.object(self.mod, "_asl_reg_write_status", lambda *a: None):
            self.assertEqual(self.mod._asl_reg_check(), "registered")
            self.assertFalse(self.mod._asl_reg_info.get("changed"))
            with mock.patch.object(self.mod, "ami_command", lambda cmd, timeout=4: (self.reg_out.replace("Registered", "Rejected"), True)):
                self.assertEqual(self.mod._asl_reg_check(), "unregistered")
            self.assertTrue(self.mod._asl_reg_info.get("changed"))

    def test_a_half_finished_sign_in_is_no_longer_registered(self):
        out = "register.allstarlink.org 27342 - 180 Request Sent\n"
        self.assertEqual(self.mod.reg_parse(out, "27342"), "unknown")


class NodeTalkerReadsItTests:
    def setUp(self):
        self.path = os.path.join(WORK, "run2", "services.json")
        self.text = systemd()
        patches = [
            mock.patch.object(self.mod, "SVC_STATUS_FILE", self.path),
            mock.patch.object(self.mod, "run", lambda cmd, timeout=10: (self.text, 0)),
            mock.patch.object(self.mod.time, "monotonic", lambda: NOW),
            mock.patch.object(self.mod._cfg, "asl_node", "27342", create=True),
            mock.patch.object(nt, "SVC_NC_FILE", self.path),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with self.mod._asl_reg_lock:
            self.mod._asl_reg_info.update(state="registered", node="27342", at=NOW - 5, since=NOW - 5)
        with nt._svc_lock:
            nt._svc_cache.update(t=-1e9, v=None)
            nt._svc_own_until["t"] = 0.0

    def test_what_node_controller_writes_node_talker_accepts(self):
        self.mod._svc_file_write()
        d = nt.svc_from_nc()
        self.assertEqual(d["source"], "nodecontrol")
        self.assertEqual([r["key"] for r in d["services"]], ["asterisk", "ab", "mmdvm", "stfu", "m17"])
        self.assertEqual(d["reg"]["state"], "registered")
        self.assertLess(d["age_s"], 5)

    def test_the_status_route_uses_it_and_shows_where_it_came_from(self):
        self.mod._svc_file_write()
        self.assertEqual(nt.svc_status()["source"], "nodecontrol")

    def test_both_tools_carry_the_same_function_text(self):
        for name in ("svc_table", "svc_uptime_text", "svc_unit_info", "svc_classify", "svc_rows", "reg_parse", "svc_reg_state"):
            self.assertEqual(getattr(self.mod, name).__code__.co_code, getattr(nt, name).__code__.co_code, name)

    def test_the_two_tools_judge_the_same_systemd_text_the_same_way(self):
        text = systemd(ab=dict(active="failed", sub="failed"), mmdvm=dict(since=60, restarts="5"))
        a = self.mod.svc_rows(lambda args: text, NOW)
        b = nt.svc_rows(lambda args: text, NOW)
        self.assertEqual(a, b)


class WriterPi02w(WriterTests, unittest.TestCase):
    mod = ncp


class WriterFull(WriterTests, unittest.TestCase):
    mod = ncf


class NodeTalkerReadsItPi02w(NodeTalkerReadsItTests, unittest.TestCase):
    mod = ncp


class NodeTalkerReadsItFull(NodeTalkerReadsItTests, unittest.TestCase):
    mod = ncf


class BuildsAgree(unittest.TestCase):
    def test_the_full_build_names_itself_and_the_pi02w_build_does(self):
        self.assertFalse(ncf.VERSION.endswith("-pi02w"))
        self.assertTrue(ncp.VERSION.endswith("-pi02w"))

    def test_both_builds_write_the_same_file_and_use_the_same_parser(self):
        for name in ("SVC_STATUS_FILE",):
            self.assertEqual(getattr(ncf, name), getattr(ncp, name))
        out = "register.allstarlink.org 27342 - 180 Request Sent\n"
        self.assertEqual(ncf.reg_parse(out, "27342"), ncp.reg_parse(out, "27342"))


if __name__ == "__main__":
    unittest.main()
