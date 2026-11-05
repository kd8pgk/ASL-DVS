import glob
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NR_FILE = sorted(glob.glob(os.path.join(ROOT, "noderecorder_v*.py")),
                 key=lambda f: [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]])[-1]
MAIN = "50001"

RPT_TEXT = """[general]
context=default

[50001](node-main)
rxchannel = USRP/127.0.0.1:34000:32000

[1921](node-main)
rxchannel = USRP/127.0.0.1:34018:32018
duplex = 0
hangtime = 0

[nodes]
1921 = radio@127.0.0.1/1921,NONE
"""

WORK = tempfile.mkdtemp(prefix="nr_listen_")
os.environ["NODERECORDER_CONFIG_DIR"] = os.path.join(WORK, "conf")
os.environ["NODERECORDER_RPT_CONF"] = os.path.join(WORK, "rpt.conf")
os.makedirs(os.environ["NODERECORDER_CONFIG_DIR"], exist_ok=True)
with open(os.environ["NODERECORDER_RPT_CONF"], "w") as fh:
    fh.write(RPT_TEXT)

spec = importlib.util.spec_from_file_location("noderecorder_under_test", NR_FILE)
nr = importlib.util.module_from_spec(spec)
sys.modules["noderecorder_under_test"] = nr
spec.loader.exec_module(nr)


def asl_target(num="55553"):
    return {"mode": "ASL", "num": num, "label": "Parrot"}


class Fake(unittest.TestCase):
    def setUp(self):
        with open(nr.RPT_CONF, "w") as fh:
            fh.write(RPT_TEXT)
        self.links = {}
        self.ilinks = []
        self.loaded = True
        self.patches = [
            mock.patch.object(nr, "RPT_CONF", os.environ["NODERECORDER_RPT_CONF"]),
            mock.patch.object(nr, "BACKUP_DIR", os.path.join(WORK, "backups")),
            mock.patch.object(nr, "main_node", lambda: MAIN),
            mock.patch.object(nr, "iax_bindport", lambda: "4569"),
            mock.patch.object(nr, "bridge_nodes", lambda: {"digital": "", "m17": ""}),
            mock.patch.object(nr, "nets_load", lambda: {}),
            mock.patch.object(nr, "log_event", lambda *a, **k: None),
            mock.patch.object(nr, "rpt_links", self._rpt_links),
            mock.patch.object(nr, "ilink", self._ilink),
            mock.patch.object(nr, "tune_value", lambda k: 0),
            mock.patch.object(nr, "ast_cli", lambda cmd, timeout=8: (self.loaded, "")),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        nr._listen["peer"] = ""

    def _rpt_links(self, node, max_age=2.0):
        return True, [{"node": n} for n in self.links.get(node, [])]

    def _ilink(self, node, op, peer):
        self.ilinks.append((node, op, peer))
        if op == 2 or op == 3:
            self.links.setdefault(node, []).append(peer)
        elif op in (1, 11):
            self.links[node] = [p for p in self.links.get(node, []) if p != peer]
        return True, ""

    def main_calls(self):
        return [c for c in self.ilinks if c[0] in (MAIN, nr.REC_NODE)]


class ScheduleVia(Fake):
    def test_default_is_main(self):
        e = nr.schedule_norm_entry({"name": "x", "target": asl_target(), "days": [0], "start": "10:00",
                                    "end": "11:00"}, check_target=False)
        self.assertEqual(e["via"], "main")

    def test_listen_accepts_asl_and_echolink(self):
        e = nr.schedule_norm_entry({"name": "x", "target": asl_target(), "via": "listen", "days": [0],
                                    "start": "10:00", "end": "11:00"}, check_target=False)
        self.assertEqual(e["via"], "listen")
        el = {"mode": "EchoLink", "num": "7", "label": "E"}
        e2 = nr.schedule_norm_entry({"name": "y", "target": el, "via": "listen", "days": [0],
                                     "start": "10:00", "end": "11:00"}, check_target=False)
        self.assertEqual(e2["via"], "listen")

    def test_listen_refuses_dvswitch_and_m17(self):
        for mode, num in (("DSTAR", "REF001C"), ("M17", "M17-XYZ")):
            with self.assertRaises(ValueError):
                nr.schedule_norm_entry({"name": "z", "target": {"mode": mode, "num": num}, "via": "listen",
                                        "days": [0], "start": "10:00", "end": "11:00"}, check_target=False)

    def test_bad_via_refused(self):
        with self.assertRaises(ValueError):
            nr.schedule_norm_entry({"name": "x", "target": asl_target(), "via": "both", "days": [0],
                                    "start": "10:00", "end": "11:00"}, check_target=False)


class Hubs(Fake):
    def test_listen_hub_has_its_own_rx_chain(self):
        self.assertIs(nr.HUB.rx, nr.RXC)
        self.assertIs(nr.HUB2.rx, nr.RXC2)
        self.assertIsNot(nr.RXC, nr.RXC2)
        self.assertTrue(nr.HUB.keyed_wake)
        self.assertFalse(nr.HUB2.keyed_wake)

    def test_listen_tick_uses_its_own_chain_and_leaves_keying_alone(self):
        class Rec:
            def __init__(self):
                self.got = []

            def feed(self, pcm):
                self.got.append(pcm)

        rec = Rec()
        hub = nr.HUB2
        seen = []
        rx = nr.RXC2
        with mock.patch.object(rx, "process", lambda frame, gain, db: seen.append("rxc2") or b"\x01\x00"), \
                mock.patch.object(nr.RXC, "process", lambda *a: seen.append("rxc1") or b""), \
                mock.patch.object(nr.KEYED, "wake", lambda now: seen.append("keyed")), \
                mock.patch.object(nr, "frame_db", lambda frame: -10.0):
            with hub.lock:
                hub.frames.append(b"\x00" * nr.FRAME_BYTES)
            hub.recorder = rec
            try:
                hub.tick()
            finally:
                hub.recorder = None
        self.assertEqual(seen, ["rxc2"])
        self.assertEqual(rec.got, [b"\x01\x00"])


class Setup(Fake):
    def test_enable_adds_listen_node_without_linking_it(self):
        r = nr.rec2_enable()
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.ilinks, [])
        with open(nr.RPT_CONF) as fh:
            text = fh.read()
        self.assertIn("[1922]", text)
        self.assertIn(f"rxchannel = USRP/127.0.0.1:{nr.REC2_USRP_IN}:{nr.REC2_USRP_OUT}", text)
        self.assertIn("1922 = radio@127.0.0.1/1922,NONE", text)
        self.assertIn("1921 = radio@127.0.0.1/1921,NONE", text)
        self.assertIn("[1921](node-main)", text)
        self.assertTrue(nr.rec2_state()["ready"])

    def test_enable_twice_changes_nothing(self):
        nr.rec2_enable()
        with open(nr.RPT_CONF) as fh:
            before = fh.read()
        r = nr.rec2_enable()
        self.assertTrue(r["ok"])
        self.assertFalse(r.get("changed", True))
        with open(nr.RPT_CONF) as fh:
            self.assertEqual(before, fh.read())

    def test_refuses_foreign_1922(self):
        with open(nr.RPT_CONF, "a") as fh:
            fh.write("\n[1922]\nrxchannel = USRP/127.0.0.1:1:2\n")
        r = nr.rec2_enable()
        self.assertFalse(r["ok"])
        self.assertFalse(nr.rec2_state()["ready"])

    def test_refuses_wrong_usrp_ports(self):
        with open(nr.RPT_CONF, "a") as fh:
            fh.write("\n; noderecorder: listen node for Node Recorder (receive only; it is never linked to the main node)\n[1922]\nrxchannel = USRP/127.0.0.1:1:2\n")
        r = nr.rec2_enable()
        self.assertFalse(r["ok"])


class Remove(Fake):
    def setUp(self):
        super().setUp()
        nr.rec2_enable()
        self.ilinks.clear()

    def _text(self):
        with open(nr.RPT_CONF) as fh:
            return fh.read()

    def test_remove_deletes_the_stanza_and_its_nodes_line_only(self):
        r = nr.rec2_disable()
        self.assertTrue(r["ok"], r)
        text = self._text()
        self.assertNotIn("[1922]", text)
        self.assertNotIn("1922 = radio@", text)
        self.assertIn("[1921](node-main)", text)
        self.assertIn("1921 = radio@127.0.0.1/1921,NONE", text)
        self.assertEqual(self.main_calls(), [])

    def test_remove_releases_a_station_it_is_receiving(self):
        nr.listen_connect(asl_target("55553"))
        self.ilinks.clear()
        r = nr.rec2_disable()
        self.assertTrue(r["ok"], r)
        self.assertIn(("1922", 1, "55553"), self.ilinks)
        self.assertEqual(nr._listen["peer"], "")
        self.assertEqual(self.main_calls(), [])

    def test_remove_refused_during_a_listen_recording(self):
        with mock.patch.object(nr.ENGINE, "hub", nr.HUB2):
            r = nr.rec2_disable()
        self.assertFalse(r["ok"])
        self.assertIn("A listen recording is running", r["error"])
        self.assertIn("[1922]", self._text())

    def test_remove_leaves_a_foreign_1922_alone(self):
        with open(nr.RPT_CONF, "w") as fh:
            fh.write(RPT_TEXT + "\n[1922]\nrxchannel = USRP/127.0.0.1:1:2\n")
        r = nr.rec2_disable()
        self.assertFalse(r["ok"])
        self.assertIn("[1922]", self._text())

    def test_remove_then_install_again(self):
        self.assertTrue(nr.rec2_disable()["ok"])
        self.assertFalse(nr.rec2_state()["ready"])
        self.assertTrue(nr.rec2_enable()["ok"])
        self.assertTrue(nr.rec2_state()["ready"])


class Listen(Fake):
    def setUp(self):
        super().setUp()
        nr.rec2_enable()
        self.ilinks.clear()

    def test_connect_links_only_the_station_in_receive_mode(self):
        ok, msg = nr.listen_connect(asl_target("55553"))
        self.assertTrue(ok, msg)
        self.assertEqual(self.ilinks, [("1922", 2, "55553")])
        self.assertEqual(self.main_calls(), [])
        self.assertTrue(nr.listen_linked(asl_target("55553")))

    def test_connect_drops_other_public_links_on_1922_only(self):
        self.links["1922"] = ["12345", nr.REC_NODE]
        ok, _ = nr.listen_connect(asl_target("55553"))
        self.assertTrue(ok)
        self.assertIn(("1922", 1, "12345"), self.ilinks)
        self.assertNotIn(("1922", 1, nr.REC_NODE), self.ilinks)
        self.assertEqual(self.main_calls(), [])

    def test_connect_refused_when_not_set_up(self):
        with open(nr.RPT_CONF, "w") as fh:
            fh.write(RPT_TEXT)
        ok, msg = nr.listen_connect(asl_target())
        self.assertFalse(ok)
        self.assertEqual(self.ilinks, [])
        self.assertIn("not set up", msg)

    def test_disconnect_releases_the_public_link(self):
        nr.listen_connect(asl_target("55553"))
        self.ilinks.clear()
        ok, _msg = nr.listen_disconnect(asl_target("55553"))
        self.assertTrue(ok)
        self.assertEqual(self.ilinks, [("1922", 1, "55553")])
        self.assertEqual(nr._listen["peer"], "")
        self.assertEqual(self.main_calls(), [])

    def test_disconnect_after_restart_still_releases_the_link(self):
        self.links["1922"] = ["55553"]
        nr._listen["peer"] = ""
        ok, _msg = nr.listen_disconnect(asl_target("55553"))
        self.assertTrue(ok)
        self.assertEqual(self.ilinks, [("1922", 1, "55553")])
        self.assertEqual(self.links["1922"], [])

    def test_disconnect_never_touches_private_nodes(self):
        self.links["1922"] = [nr.REC_NODE, "55553"]
        nr.listen_disconnect(asl_target("55553"))
        self.assertNotIn(("1922", 1, nr.REC_NODE), self.ilinks)
        self.assertEqual(self.main_calls(), [])

    def test_connect_refused_when_asterisk_has_not_loaded_1922(self):
        self.loaded = False
        ok, msg = nr.listen_connect(asl_target("55553"))
        self.assertFalse(ok)
        self.assertIn("restart Asterisk", msg)
        self.assertEqual(self.ilinks, [])

    def test_keeper_links_the_station_again_during_a_recording(self):
        nr.listen_connect(asl_target("55553"))
        self.links["1922"] = []
        self.ilinks.clear()
        with mock.patch.object(nr.ENGINE, "hub", nr.HUB2):
            nr.listen_keep_tick()
        self.assertEqual(self.ilinks, [("1922", 2, "55553")])
        self.assertEqual(self.main_calls(), [])

    def test_keeper_does_nothing_when_linked_or_not_recording(self):
        nr.listen_connect(asl_target("55553"))
        self.ilinks.clear()
        with mock.patch.object(nr.ENGINE, "hub", nr.HUB2):
            nr.listen_keep_tick()
        self.assertEqual(self.ilinks, [])
        self.links["1922"] = []
        with mock.patch.object(nr.ENGINE, "hub", None):
            nr.listen_keep_tick()
        self.assertEqual(self.ilinks, [])
        nr._listen["peer"] = ""
        with mock.patch.object(nr.ENGINE, "hub", nr.HUB2):
            nr.listen_keep_tick()
        self.assertEqual(self.ilinks, [])

    def test_listen_node_is_not_inheriting_the_main_template(self):
        nr.rec2_enable()
        with open(nr.RPT_CONF) as fh:
            text = fh.read()
        self.assertIn("\n[1922]\n", text)
        self.assertNotIn("[1922](", text)

    def test_listen_linked_false_after_drop(self):
        nr.listen_connect(asl_target("55553"))
        nr.listen_disconnect(asl_target("55553"))
        self.assertFalse(nr.listen_linked(asl_target("55553")))

    def test_real_actions_send_listen_entries_to_the_listen_node(self):
        entry = {"name": "n", "target": asl_target("55553"), "via": "listen"}
        actions = nr.RealActions()
        with mock.patch.object(nr, "tune_connect") as tc, mock.patch.object(nr, "tune_disconnect") as td:
            ok, _msg, _ = actions.connect(entry)
            self.assertTrue(ok)
            self.assertTrue(actions.link_alive(entry))
            actions.disconnect(entry)
            tc.assert_not_called()
            td.assert_not_called()
        self.assertEqual(self.main_calls(), [])
        self.assertEqual([c for c in self.ilinks if c[0] == "1922"],
                         [("1922", 2, "55553"), ("1922", 1, "55553")])

    def test_real_actions_keep_main_entries_on_the_main_node(self):
        entry = {"name": "m", "target": asl_target("55553")}
        actions = nr.RealActions()
        with mock.patch.object(nr, "tune_connect", return_value={"ok": True, "message": "x"}) as tc, \
                mock.patch.object(nr, "tune_disconnect", return_value={"ok": True, "message": "y"}) as td:
            actions.connect(entry)
            actions.disconnect(entry)
            tc.assert_called_once()
            td.assert_called_once()
        self.assertEqual([c for c in self.ilinks if c[0] == "1922"], [])


class Engine(Fake):
    def setUp(self):
        super().setUp()
        self.rec_dir = os.path.join(WORK, "recs")
        os.makedirs(self.rec_dir, exist_ok=True)
        extra = [
            mock.patch.object(nr, "storage_pick", lambda: {"ok": True, "path": self.rec_dir}),
            mock.patch.object(nr, "repair_recordings", lambda d: None),
            mock.patch.object(nr, "enc_sweep", lambda d: None),
            mock.patch.object(nr, "retention_enforce", lambda d, need: None),
            mock.patch.object(nr, "RECORD_RESERVE_BYTES", 0),
            mock.patch.object(nr, "ENGINE", nr.RecordingEngine()),
        ]
        for p in extra:
            p.start()
            self.addCleanup(p.stop)

    def _entry(self, via):
        e = {"name": "t", "format": "pcm", "target": asl_target(), "via": via}
        return e

    def test_listen_recording_attaches_to_listen_hub_only(self):
        eng = nr.ENGINE
        ok, msg, _ = eng.start(self._entry("listen"), None)
        try:
            self.assertTrue(ok, msg)
            self.assertIs(eng.hub, nr.HUB2)
            self.assertIs(nr.HUB2.recorder, eng)
            self.assertIsNone(nr.HUB.recorder)
        finally:
            eng.stop()
        self.assertIsNone(nr.HUB2.recorder)
        self.assertIsNone(eng.hub)

    def test_main_recording_attaches_to_main_hub(self):
        eng = nr.ENGINE
        ok, msg, _ = eng.start(self._entry("main"), None)
        try:
            self.assertTrue(ok, msg)
            self.assertIs(nr.HUB.recorder, eng)
            self.assertIsNone(nr.HUB2.recorder)
        finally:
            eng.stop()
        self.assertIsNone(nr.HUB.recorder)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
