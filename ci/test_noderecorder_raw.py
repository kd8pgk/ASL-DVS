import glob
import importlib.util
import os
import random
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NR_FILE = sorted(glob.glob(os.path.join(ROOT, "noderecorder_v*.py")),
                 key=lambda f: [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]])[-1]
WORK = tempfile.mkdtemp(prefix="nr_raw_")
os.environ["NODERECORDER_CONFIG_DIR"] = os.path.join(WORK, "conf")
os.environ["NODERECORDER_RPT_CONF"] = os.path.join(WORK, "rpt.conf")
os.makedirs(os.environ["NODERECORDER_CONFIG_DIR"], exist_ok=True)
with open(os.environ["NODERECORDER_RPT_CONF"], "w") as fh:
    fh.write("[general]\n")

spec = importlib.util.spec_from_file_location("noderecorder_raw_under_test", NR_FILE)
nr = importlib.util.module_from_spec(spec)
sys.modules["noderecorder_raw_under_test"] = nr
spec.loader.exec_module(nr)

RAW = {"rx_hpf": False, "rx_agc": False, "rx_gate": 0, "rx_notch_hz": 0.0}


def raw_cfg(key):
    return RAW.get(key, nr.DEFAULT_CONFIG.get(key))


def tone(hz, amp=8000, n=nr.FRAME_SAMPLES):
    import math
    import array
    a = array.array("h", [round(amp * math.sin(2 * math.pi * hz * (i / 8000.0))) for i in range(n)])
    return a.tobytes()


class RawPath(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(nr, "_cfg_get", raw_cfg)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.rx = nr.RxClean()

    def test_random_speech_like_frames_pass_through_bit_exact(self):
        rnd = random.Random(7)
        for _ in range(200):
            frame = bytes(rnd.getrandbits(8) for _ in range(nr.FRAME_BYTES))
            out = self.rx.process(frame, 0.0, nr.frame_db(frame))
            self.assertEqual(out, frame)

    def test_tone_frames_pass_through_bit_exact(self):
        for hz in (100.0, 300.0, 1000.0, 2500.0):
            frame = tone(hz)
            self.assertEqual(self.rx.process(frame, 0.0, nr.frame_db(frame)), frame)

    def test_silence_passes_through_as_silence(self):
        frame = b"\x00" * nr.FRAME_BYTES
        self.assertEqual(self.rx.process(frame, 0.0, -120.0), frame)


def mk_entry(eid, start, end, kind="regular", target=None, **extra):
    raw = {"id": eid, "name": eid, "days": [0, 1, 2, 3, 4, 5, 6], "start": start, "end": end,
           "target": target or {"mode": "ASL", "num": "2000"}, "format": "pcm", "kind": kind,
           "date": nr.sched_now().strftime("%Y-%m-%d") if kind == "special" else "", "enabled": True}
    raw.update(extra)
    if kind == "special":
        raw["days"] = []
    return nr.schedule_norm_entry(raw, check_target=False)


class CallLogActions:
    def __init__(self):
        self.calls = []

    def connect(self, entry):
        self.calls.append("connect")
        return True, "", None

    def link_alive(self, entry):
        return True

    def healthy(self, entry):
        self.calls.append("healthy")
        return True, ""

    def start(self, entry, window):
        self.calls.append("start")
        return True, "", "f.wav"

    def stop(self):
        self.calls.append("stop")
        return True, "", None

    def disconnect(self, entry):
        self.calls.append("disconnect")
        return True, "", None


def run_fake(entry):
    import threading
    clock = [0.0]
    states = []

    def sleep(sec):
        clock[0] += max(sec, 1.0)

    act = CallLogActions()
    res = nr.run_sequence(entry, act, 5.0, threading.Event(), lambda s, file=None: states.append(s), lambda: clock[0], sleep)
    return res, act.calls, states


class RecordFlag(unittest.TestCase):
    def test_record_defaults_to_on_and_old_entries_load(self):
        self.assertIs(mk_entry("a", "20:00", "21:00")["record"], True)
        self.assertIs(mk_entry("a", "20:00", "21:00", record=False)["record"], False)
        self.assertIs(mk_entry("a", "20:00", "21:00", record="false")["record"], False)
        raw = {"id": "o", "name": "o", "days": [1], "start": "20:00", "end": "21:00", "target": {"mode": "ASL", "num": "2000"}, "format": "pcm"}
        self.assertIs(nr.schedule_norm_entry(raw, check_target=False)["record"], True)

    def test_the_link_mode_is_gone_and_an_old_monitor_entry_becomes_transceive(self):
        e = mk_entry("a", "20:00", "21:00", link_mode="monitor")
        self.assertNotIn("link_mode", e)
        self.assertFalse(hasattr(nr, "link_op"))

    def test_the_scheduler_connects_without_a_link_mode(self):
        seen = []
        with mock.patch.object(nr, "tune_connect", lambda b: (seen.append(b), {"ok": True, "message": "ok"})[1]):
            nr.RealActions().connect(mk_entry("a", "20:00", "21:00", link_mode="monitor"))
        self.assertNotIn("link_mode", seen[0])
        self.assertEqual(seen[0]["num"], "2000")

    def test_a_recording_window_starts_and_stops_the_recorder(self):
        res, calls, states = run_fake(mk_entry("a", "20:00", "21:00"))
        self.assertEqual(res["result"], "ok")
        self.assertEqual(calls[0], "connect")
        self.assertIn("start", calls)
        self.assertIn("stop", calls)
        self.assertEqual(calls[-1], "disconnect")
        self.assertIn("recording", states)

    def test_a_link_only_window_links_and_unlinks_without_recording(self):
        res, calls, states = run_fake(mk_entry("a", "20:00", "21:00", record=False))
        self.assertEqual(res["result"], "ok")
        self.assertEqual(res["detail"], "linked, not recorded")
        self.assertEqual(calls, ["connect", "disconnect"])
        self.assertIn("linked", states)
        self.assertNotIn("recording", states)
        self.assertFalse(any(s["step"] in ("start", "stop") for s in res["steps"]))

    def test_an_asl_link_uses_the_mode(self):
        ops = []
        patches = {"dashboard_conf": lambda: {"asl_node": "9999"}, "teardown": lambda *a, **k: [],
                   "ilink": lambda node, op, peer: (ops.append((node, op, peer)), (True, ""))[1],
                   "_link_outcome": lambda f, n, via: {"ok": True}, "_leave": lambda *a: None}
        f = {"mode": "ASL", "num": "2000", "net": "", "label": ""}
        with mock.patch.multiple(nr, **patches):
            nr.node_connect(f, "1234", 8)
            nr.node_connect(f, "1234")
        self.assertEqual(ops, [("1234", 8, "2000"), ("1234", 3, "2000")])

    def test_the_bridge_watchdog_relinks_in_the_same_mode(self):
        with mock.patch.object(nr, "TUNED_PATH", os.path.join(WORK, "tuned.json")):
            nr._solo_set(mode="DMR", target="DMR|TGIF|91", name="DMR TGIF 91", bridge="1999", op=8)
            self.assertEqual(int(nr._solo["op"] or 3), 8)
            nr._solo_set(mode="DMR", target="t", name="n", bridge="1999")
            self.assertEqual(int(nr._solo["op"] or 3), 3)
            nr._solo_set()


class FakeActions:
    log = []

    def __init__(self):
        self.plan = FakeActions.script.pop(0) if FakeActions.script else {}
        self.checks = 0

    script = []
    seen = []

    def connect(self, entry):
        FakeActions.seen.append(dict(entry))
        if not self.plan.get("connect", True):
            return False, "Asterisk is still starting", None
        return True, "", None

    def link_alive(self, entry):
        self.checks += 1
        drop = self.plan.get("drop_after")
        return not (drop is not None and self.checks > drop)

    def healthy(self, entry):
        return True, ""

    def start(self, entry, window):
        return True, "", "x.wav"

    def stop(self):
        return True, "", None

    def disconnect(self, entry):
        return True, "", None


class SecondPart(unittest.TestCase):
    def setUp(self):
        for name, val in (("LINK_CHECK_SEC", 0.05), ("RETRY_SEC", 0.3), ("RETRY_MAX", 20),
                          ("SCHEDULE_STATE_PATH", os.path.join(WORK, "state_%s.json" % id(self)))):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)
        FakeActions.script, FakeActions.seen = [], []
        self.now = nr.sched_now()
        self.start_hm = (self.now - nr.timedelta(minutes=2)).strftime("%H:%M")
        self.end_hm = (self.now + nr.timedelta(minutes=58)).strftime("%H:%M")
        self.entries = [mk_entry("a", self.start_hm, self.end_hm)]
        p = mock.patch.object(nr, "schedule_load", lambda: {"entries": self.entries, "error": ""})
        p.start()
        self.addCleanup(p.stop)
        self.removed = []
        p = mock.patch.object(nr, "_special_remove", lambda eid: self.removed.append(eid))
        p.start()
        self.addCleanup(p.stop)
        self.sched = nr.Scheduler(real_actions=FakeActions)
        self.sched.sleep = lambda s: nr.time.sleep(min(s, 0.05))
        self.addCleanup(self.finish)

    def finish(self):
        self.sched.stop.set()
        self.sched.run_abort.set()
        self.sched.shutdown(5)

    def drive(self, until, secs=15):
        end = nr.time.time() + secs
        while nr.time.time() < end:
            self.sched.tick(self.now)
            if until():
                return True
            nr.time.sleep(0.05)
        return False

    def test_a_dropped_link_starts_a_second_part_while_the_window_is_open(self):
        FakeActions.script = [{"drop_after": 1}, {}]
        self.assertTrue(self.drive(lambda: len(FakeActions.seen) >= 2))
        self.assertNotIn("part", FakeActions.seen[0])
        self.assertEqual(FakeActions.seen[1]["part"], 2)
        first = self.sched.results[0]
        self.assertEqual(first["result"], "link_lost")
        self.assertIn("trying again", first["detail"])
        self.assertEqual(self.sched.done, {})

    def test_a_first_connect_failure_is_not_retried(self):
        FakeActions.script = [{"connect": False}]
        self.assertTrue(self.drive(lambda: self.sched.done))
        nr.time.sleep(0.6)
        self.sched.tick(self.now)
        self.assertEqual(len(FakeActions.seen), 1)

    def test_asterisk_still_down_is_tried_again_and_part_numbers_skip_failures(self):
        FakeActions.script = [{"drop_after": 1}, {"connect": False}, {}]
        self.assertTrue(self.drive(lambda: len(FakeActions.seen) >= 3))
        self.assertEqual(FakeActions.seen[2]["part"], 2)
        self.assertEqual(self.sched.done, {})

    def test_it_gives_up_after_the_retry_limit(self):
        FakeActions.script = [{"drop_after": 1}, {"connect": False}, {"connect": False}]
        with mock.patch.object(nr, "RETRY_MAX", 3):
            self.assertTrue(self.drive(lambda: self.sched.done))
        self.assertEqual(len(FakeActions.seen), 3)

    def test_no_second_part_when_the_window_is_nearly_over(self):
        end = (self.now + nr.timedelta(minutes=1)).strftime("%H:%M")
        start = (self.now - nr.timedelta(minutes=30)).strftime("%H:%M")
        self.entries = [mk_entry("a", start, end)]
        FakeActions.script = [{"drop_after": 1}]
        self.assertTrue(self.drive(lambda: self.sched.done))
        self.assertEqual(len(FakeActions.seen), 1)

    def test_a_stop_by_hand_is_not_retried(self):
        FakeActions.script = [{}]
        self.assertTrue(self.drive(lambda: self.sched.state == "recording"))
        self.sched.stop_by_hand()
        self.assertTrue(self.drive(lambda: self.sched.state == "idle" and self.sched.done))
        nr.time.sleep(0.5)
        self.sched.tick(self.now)
        self.assertEqual(len(FakeActions.seen), 1)

    def test_a_special_is_kept_until_its_last_part(self):
        self.entries = [mk_entry("sp", self.start_hm, self.end_hm, kind="special")]
        FakeActions.script = [{"drop_after": 1}, {"drop_after": 1}]
        self.assertTrue(self.drive(lambda: len(FakeActions.seen) >= 2))
        self.assertEqual(self.removed, [])

    def test_the_part_count_survives_a_restart(self):
        FakeActions.script = [{"drop_after": 1}, {}]
        self.assertTrue(self.drive(lambda: len(FakeActions.seen) >= 2))
        self.sched._state_save()
        again = nr.Scheduler(real_actions=FakeActions)
        again._state_load()
        self.assertGreaterEqual(again.parts["a"]["began"], 1)

    def test_the_second_part_gets_its_own_file_name(self):
        d = tempfile.mkdtemp(prefix="nr_part_")
        self.addCleanup(shutil.rmtree, d, True)
        with mock.patch.object(nr, "storage_pick", lambda: {"ok": True, "path": d}):
            e = nr.ENGINE
            ok, _msg, name = e.start({"name": "Net", "format": "pcm", "part": 2}, None)
            self.assertTrue(ok)
            e.stop()
        self.assertIn("Net-part-2", name)


class OldPrivateNodes(unittest.TestCase):
    BASE = ("[general]\nx=1\n\n[nodes]\n1234 = radio@127.0.0.1/1234,NONE\n1921 = radio@127.0.0.1/1921,NONE\n"
            "1050 = radio@127.0.0.1/1050,NONE\n1051 = radio@127.0.0.1/1051,NONE\n\n[node-main]\nduplex = 1\n\n"
            "[1234](node-main)\nrxchannel = Local/pseudo\n\n" + nr.REC_NOTE + "\n[1921](node-main)\nrxchannel = USRP/127.0.0.1:34018:32018\n\n"
            + nr.OLD_PRIV_NOTE + "\n[1050](node-main)\nrxchannel = USRP/127.0.0.1:34050:32050\nduplex = 0\n\n"
            + nr.OLD_PRIV_NOTE + "\n[1051](node-main)\nrxchannel = USRP/127.0.0.1:34051:32051\nduplex = 0\n")

    def setUp(self):
        self.path = nr.RPT_CONF
        self.write(self.BASE)
        p = mock.patch.object(nr, "allmon_follow", lambda *a, **k: "")
        p.start()
        self.addCleanup(p.stop)

    def write(self, text):
        with open(self.path, "w") as fh:
            fh.write(text)

    def read(self):
        with open(self.path) as fh:
            return fh.read()

    def test_it_finds_the_nodes_an_older_version_added(self):
        self.assertEqual(nr.old_private_nodes(), ["1050", "1051"])

    def test_removing_them_leaves_1921_and_the_rest_alone(self):
        r = nr.old_private_remove()
        self.assertTrue(r["ok"] and r["changed"], r)
        text = self.read()
        self.assertNotIn("[1050]", text)
        self.assertNotIn("[1051]", text)
        self.assertNotIn("1050 = radio", text)
        self.assertNotIn("1051 = radio", text)
        self.assertIn("[1921](node-main)", text)
        self.assertIn("1921 = radio@127.0.0.1/1921,NONE", text)
        self.assertIn("1234 = radio@127.0.0.1/1234,NONE", text)
        self.assertEqual(nr.old_private_nodes(), [])

    def test_a_node_written_by_hand_is_never_removed(self):
        self.write(self.BASE.replace(nr.OLD_PRIV_NOTE + "\n[1050]", "; mine\n[1050]"))
        nr.old_private_remove()
        self.assertIn("[1050]", self.read())
        self.assertNotIn("[1051]", self.read())

    def test_nothing_to_remove_changes_nothing(self):
        self.write("[general]\nx=1\n")
        r = nr.old_private_remove()
        self.assertTrue(r["ok"])
        self.assertFalse(r["changed"])
        self.assertEqual(self.read(), "[general]\nx=1\n")

    def test_an_unreadable_rpt_conf_is_reported(self):
        os.remove(self.path)
        self.assertEqual(nr.old_private_nodes(), [])
        self.assertFalse(nr.old_private_remove()["ok"])

    def test_leftover_per_node_state_files_are_deleted(self):
        keep = os.path.join(nr.CONFIG_DIR, "schedule_state.json")
        gone = os.path.join(nr.CONFIG_DIR, "schedule_state_1050.json")
        for f in (keep, gone):
            with open(f, "w") as fh:
                fh.write("{}")
        nr.drop_old_lane_state()
        self.assertTrue(os.path.exists(keep))
        self.assertFalse(os.path.exists(gone))
        os.remove(keep)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
