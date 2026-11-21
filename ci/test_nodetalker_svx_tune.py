import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nt_svxtune_")
os.environ["NODETALKER_SUITELOG"] = os.path.join(WORK, "suitelog.jsonl")
os.environ["NODETALKER_SUITELOG_FLAG"] = os.path.join(WORK, "suitelog.on")
os.environ.setdefault("NODETALKER_CONFIG_DIR", os.path.join(WORK, "nt"))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:4]]
    return sorted(__import__("glob").glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("nt_svxtune_under_test", newest("nodetalker_v[0-9]*.py"))
nt = importlib.util.module_from_spec(spec)
sys.modules["nt_svxtune_under_test"] = nt
spec.loader.exec_module(nt)


class SvxFavorites(unittest.TestCase):
    def test_svx_is_a_mode(self):
        self.assertEqual(nt._mode_of("svx"), "SVX")
        self.assertIn("SVX", nt.FAV_MODES)

    def test_talkgroup_is_digits_from_1_to_9_digits(self):
        self.assertEqual(nt._norm_fav_core({"mode": "SVX", "num": "1234"})["num"], "1234")
        for bad in ("0", "abc", "1000000000", ""):
            with self.assertRaises(ValueError, msg=bad):
                nt._norm_fav_core({"mode": "SVX", "num": bad})

    def test_target_is_mode_and_talkgroup(self):
        self.assertEqual(nt.fav_target({"mode": "SVX", "num": "1234"}), "SVX|1234")


class SvxControl(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.patches = [
            mock.patch.object(nt, "_svx_ready", lambda: True),
            mock.patch.object(nt, "_svx_send", lambda cmd: (self.sent.append(cmd), True)[1]),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_connect_sends_the_talkgroup_like_node_controller(self):
        r = nt.svx_connect({"mode": "SVX", "num": "1234"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.sent, ["911234#"])

    def test_release_sends_910_then_9(self):
        r = nt.svx_release()
        self.assertTrue(r["ok"])
        self.assertEqual(self.sent, ["910#", "9#"])

    def test_connect_without_control_device_says_so(self):
        with mock.patch.object(nt, "_svx_ready", lambda: False):
            r = nt.svx_connect({"mode": "SVX", "num": "1234"})
        self.assertFalse(r["ok"])
        self.assertIn("control device", r["error"])
        self.assertEqual(self.sent, [])

    def test_tune_connect_routes_svx_to_the_control_device(self):
        r = nt._tune_connect_impl({"mode": "SVX", "num": "1234"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.sent, ["911234#"])

    def test_tune_disconnect_routes_svx_to_release(self):
        nt._tune_disconnect_impl({"mode": "SVX", "num": "1234"})
        self.assertEqual(self.sent, ["910#", "9#"])


class SendRefusesAnythingElse(unittest.TestCase):
    def test_only_9_commands_leave_the_process(self):
        with mock.patch.object(nt.os, "open") as opened:
            for cmd in ("8#", "91x#", "91234", "rm -rf /"):
                self.assertFalse(nt._svx_send(cmd), cmd)
            opened.assert_not_called()


class SavedList(unittest.TestCase):
    def test_reads_the_svx_section_of_asl_dvs_conf(self):
        path = os.path.join(WORK, "asl_dvs.conf")
        with open(path, "w") as fh:
            fh.write("[general]\nname=x|1\n\n[SVX]\nnetwork_url=https://x\n# comment\n"
                     "Local Chat|1234\nWorld|999999999\nBad|0\nNoNumber|abc\n")
        with mock.patch.object(nt, "ASL_DVS_CONF", path):
            self.assertEqual(nt._svx_saved_rows(), [("Local Chat", "1234"), ("World", "999999999")])
            rows = nt.tune_list("SVX")
        self.assertTrue(rows["ok"])
        self.assertEqual(rows["rows"], [["1234", "1234 · Local Chat", ""], ["999999999", "999999999 · World", ""]])

    def test_missing_file_is_an_empty_list(self):
        with mock.patch.object(nt, "ASL_DVS_CONF", os.path.join(WORK, "none.conf")):
            rows = nt.tune_list("SVX")
        self.assertEqual((rows["ok"], rows["found"], rows["rows"]), (True, False, []))


class SvxServices(unittest.TestCase):
    def test_svxlink_is_in_the_service_table(self):
        self.assertIn("svxlink", [r[0] for r in nt.svc_table_nt()])

    def test_unknown_action_is_refused(self):
        self.assertFalse(nt.svc_control({"key": "svxlink", "action": "reboot"})["ok"])

    def test_restart_goes_through_the_existing_restart(self):
        with mock.patch.object(nt, "svc_restart", return_value={"ok": True, "message": "r"}) as r:
            self.assertEqual(nt.svc_control({"key": "svxlink", "action": "restart"})["message"], "r")
        r.assert_called_once()

    def test_stop_and_start_only_for_svxlink(self):
        self.assertFalse(nt.svc_control({"key": "asterisk", "action": "stop"})["ok"])

    def test_start_and_stop_call_systemctl(self):
        for action in ("start", "stop"):
            with self.subTest(action=action), \
                 mock.patch.object(nt.os, "geteuid", return_value=0), \
                 mock.patch.object(nt, "service_states", return_value={"svxlink-usrp.service": "inactive"}), \
                 mock.patch.object(nt, "_systemctl", return_value=subprocess.CompletedProcess([], 0, "", "")) as sc:
                r = nt.svc_control({"key": "svxlink", "action": action})
            self.assertTrue(r["ok"], r)
            sc.assert_called_once_with(action, "svxlink-usrp.service", timeout=mock.ANY)

    def test_not_root_is_refused(self):
        with mock.patch.object(nt.os, "geteuid", return_value=1000):
            self.assertFalse(nt.svc_control({"key": "svxlink", "action": "start"})["ok"])


if __name__ == "__main__":
    unittest.main()
