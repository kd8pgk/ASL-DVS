import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="rec_popups_")
os.environ["NODECONTROL_CONFIG_DIR"] = os.path.join(WORK, "nc")
os.environ["NODETALKER_CONFIG_DIR"] = os.path.join(WORK, "nt")


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


nc = load("nc_popups_under_test", newest("nodecontrol_v[0-9]*.py"))
ncp = load("ncp_popups_under_test", newest("nodecontrol_pi02w_v[0-9]*.py"))
nt = load("nt_popups_under_test", newest("nodetalker_v[0-9]*.py"))

HOLD = {"kind": "digital", "bridge": "1999", "target": "DMR|TGIF|3100", "name": "DMR rec", "nodes": ["1050"], "end": "2026-11-08T21:00"}
ASL_REC = {"name": "Net", "node": "1051", "end": "2026-11-08T22:00"}
DMR_REC = {"name": "DMR rec", "node": "1050", "end": "2026-11-08T21:00"}


def info(recs=(), bridges=(), busy=False):
    return {"ok": True, "busy": busy, "recordings": list(recs), "bridges": list(bridges), "next_bridge": {}}


class _NcPopups:
    mod = None

    def ask(self, action, data=None, status=None, busy=None):
        with mock.patch.object(self.mod, "recorder_info", lambda: status), mock.patch.object(self.mod, "recorder_busy", lambda: busy):
            return self.mod.rec_confirm_needed(action, data or {})

    def test_bridge_kind_follows_the_target(self):
        k = self.mod._rec_bridge_kind
        self.assertEqual(k("m17-connect", {}), "m17")
        self.assertEqual(k("dstar-connect", {}), "digital")
        self.assertEqual(k("switch-dmr-server", {}), "digital")
        self.assertEqual(k("quick-tune", {"mode": "ysf"}), "digital")
        self.assertEqual(k("tune", {"mode": "M17"}), "m17")
        self.assertEqual(k("switch-tab", {"page": "DMR"}), "digital")
        self.assertEqual(k("switch-tab", {"page": "ASL"}), "")
        self.assertEqual(k("asl-connect", {}), "")
        self.assertEqual(k("save-m17", {}), "")

    def test_reboot_and_shutdown_ask_during_any_recording(self):
        for action in ("reboot", "shutdown"):
            r = self.ask(action, status=info([ASL_REC]))
            self.assertEqual(r["kind"], "power")
            self.assertIn("Net on node 1051 (until 22:00)", r["message"])
            self.assertIn("partial file", r["message"])

    def test_phone_actions_ask_only_when_they_restart_asterisk(self):
        self.assertIsNotNone(self.ask("phone-apply", {"restart": True}, info([ASL_REC])))
        self.assertIsNone(self.ask("phone-apply", {"restart": False}, info([ASL_REC])))

    def test_nothing_to_ask_without_a_recording(self):
        self.assertIsNone(self.ask("reboot", status=info()))
        self.assertIsNone(self.ask("reboot", status=None))
        self.assertIsNone(self.ask("tune", {"mode": "DMR"}, info(bridges=[])))

    def test_tune_asks_only_for_the_bridge_that_is_held(self):
        s = info([DMR_REC], [HOLD])
        r = self.ask("quick-tune", {"mode": "DMR", "tg": "91"}, s)
        self.assertEqual(r["kind"], "digital")
        self.assertIn("until 21:00", r["message"])
        self.assertIn("keeps what was recorded", r["message"])
        self.assertIsNone(self.ask("m17-connect", {}, s))
        self.assertIsNone(self.ask("switch-tab", {"page": "ASL"}, s))
        self.assertIsNone(self.ask("asl-connect", {}, s))

    def test_older_recorder_without_the_new_fields(self):
        busy = {"entry": "Record now", "end": "2026-11-08T21:00", "state": "recording"}
        self.assertEqual(self.ask("reboot", status={"ok": True, "busy": True}, busy=busy)["kind"], "power")
        self.assertIsNone(self.ask("tune", {"mode": "DMR"}, status={"ok": True, "busy": True}, busy=busy))

    def test_dispatch_asks_first_then_goes_ahead_when_confirmed(self):
        sent = []

        class H:
            def send_json(self, body, code=200):
                sent.append((code, body))

        ran = []
        with mock.patch.dict(self.mod._POST_ACTIONS, {"reboot": lambda h, d: (ran.append(d), (True, "ok"))[1]}), \
                mock.patch.object(self.mod, "recorder_info", lambda: info([ASL_REC])), mock.patch.object(self.mod, "recorder_busy", lambda: None):
            with self.assertRaises(self.mod._EarlyReturn):
                self.mod.Handler._dispatch_action(H(), {"action": "reboot"})
            self.assertEqual(sent[-1][0], 409)
            self.assertTrue(sent[-1][1]["recording_confirm"])
            self.assertEqual(sent[-1][1]["confirm_kind"], "power")
            self.assertEqual(ran, [])
            self.assertEqual(self.mod.Handler._dispatch_action(H(), {"action": "reboot", "confirm_recording": True}), (True, "ok"))
            self.assertEqual(len(ran), 1)

    def test_links_on_the_main_node_are_not_locked_by_a_private_node_recording(self):
        sent = []

        class H:
            def send_json(self, body, code=200):
                sent.append((code, body))

        with mock.patch.dict(self.mod._POST_ACTIONS, {"asl-connect": lambda h, d: (True, "linked")}), \
                mock.patch.object(self.mod, "recorder_info", lambda: info([ASL_REC])), mock.patch.object(self.mod, "recorder_busy", lambda: None):
            self.assertEqual(self.mod.Handler._dispatch_action(H(), {"action": "asl-connect"}), (True, "linked"))
        self.assertEqual(sent, [])

    def test_the_main_node_lock_still_holds_for_a_busy_recorder(self):
        busy = {"entry": "Record now", "end": "", "state": "recording", "start": "x"}

        class H:
            def send_json(self, body, code=200):
                sent.append((code, body))

        sent = []
        with mock.patch.dict(self.mod._POST_ACTIONS, {"asl-connect": lambda h, d: (True, "linked")}), \
                mock.patch.object(self.mod, "recorder_info", lambda: {"ok": True, "busy": True}), mock.patch.object(self.mod, "recorder_busy", lambda: busy):
            with self.assertRaises(self.mod._EarlyReturn):
                self.mod.Handler._dispatch_action(H(), {"action": "asl-connect"})
        self.assertTrue(sent[-1][1]["recording_block"])

    def test_the_page_script_has_the_question_and_the_note(self):
        with open(self.mod.__file__, encoding="utf-8") as fh:
            text = fh.read()
        for needle in ("recConfirm", "recording_confirm", "confirm_recording", "recNote", "'reboot','shutdown'"):
            if needle == "'reboot','shutdown'":
                self.assertNotIn(needle, text)
            else:
                self.assertIn(needle, text)


class FullNodeControllerPopups(_NcPopups, unittest.TestCase):
    mod = nc


class Pi02wNodeControllerPopups(_NcPopups, unittest.TestCase):
    mod = ncp
class NodeTalkerPopups(unittest.TestCase):
    def ask(self, path, body=None, status=None, busy=None):
        with mock.patch.object(nt, "recorder_info", lambda: status), mock.patch.object(nt, "recorder_busy", lambda: busy):
            return nt.rec_confirm_needed(path, body or {})

    def test_restart_reboot_shutdown_and_setup_ask_during_any_recording(self):
        for path in ("/api/asterisk/restart", "/api/system/reboot", "/api/system/shutdown", "/api/setup/apply"):
            r = self.ask(path, status=info([ASL_REC]))
            self.assertEqual(r["kind"], "power")
            self.assertIn("Net on node 1051", r["message"])

    def test_tune_asks_only_for_the_bridge_that_is_held(self):
        s = info([DMR_REC], [HOLD])
        self.assertEqual(self.ask("/api/tune", {"mode": "DSTAR"}, s)["kind"], "digital")
        self.assertIsNone(self.ask("/api/tune", {"mode": "M17"}, s))
        self.assertIsNone(self.ask("/api/tune", {"mode": "ASL"}, s))
        self.assertIsNotNone(self.ask("/api/tune/disconnect", {}, s))
        self.assertIsNone(self.ask("/api/tune/disconnect", {}, info([ASL_REC])))

    def test_other_paths_never_ask(self):
        self.assertIsNone(self.ask("/api/connect", {}, info([ASL_REC], [HOLD])))
        self.assertIsNone(self.ask("/api/config", {}, info([ASL_REC], [HOLD])))

    def test_older_recorder_without_the_new_fields(self):
        busy = {"entry": "Record now", "end": "2026-11-08T21:00", "state": "recording"}
        self.assertEqual(self.ask("/api/system/reboot", status={"ok": True, "busy": True}, busy=busy)["kind"], "power")
        self.assertIsNone(self.ask("/api/tune", {"mode": "DMR"}, status={"ok": True, "busy": True}, busy=busy))

    def test_status_view_carries_the_recorder_fields(self):
        with mock.patch.object(nt, "recorder_info", lambda: dict(info([DMR_REC], [HOLD]), next_bridge={"name": "x", "start": "s"})):
            v = nt.recorder_view()
        self.assertEqual(v["bridges"][0]["kind"], "digital")
        self.assertEqual(v["next_bridge"]["name"], "x")
        with mock.patch.object(nt, "recorder_info", lambda: None):
            self.assertIsNone(nt.recorder_view())

    def test_moved_paths_are_no_longer_locked(self):
        for path in ("/api/asterisk/restart", "/api/system/reboot", "/api/system/shutdown", "/api/setup/apply"):
            self.assertNotIn(path, nt._RECORDING_BLOCKED)
        self.assertIn("/api/tune", nt._RECORDING_BLOCKED)

    def test_the_page_script_has_the_question_and_the_note(self):
        with open(nt.__file__, encoding="utf-8") as fh:
            text = fh.read()
        for needle in ("recAsk", "REC_ASK_PATHS", "confirm_recording", "rec-note", "rec-ask-go"):
            self.assertIn(needle, text)
        for gone in ("'sys-reboot'", "'sys-shutdown'", "'setup-restart'", "'setup-ok'"):
            self.assertNotIn(gone + ",", text.split("const REC_PATHS")[0].split("const REC_LOCK_IDS")[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
