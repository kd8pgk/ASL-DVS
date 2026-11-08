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


class PrivateNodes(unittest.TestCase):
    BASE = ("[general]\nx=1\n\n[nodes]\n1234 = radio@127.0.0.1/1234,NONE\n\n[node-main]\nduplex = 1\n\n"
            "[1234](node-main)\nrxchannel = Local/pseudo\n")

    def setUp(self):
        self.path = nr.RPT_CONF
        self.write(self.BASE)
        for name, val in (("main_node", lambda: "1234"), ("allmon_follow", lambda *a, **k: ""),
                          ("bridge_nodes", lambda *a, **k: {"digital": "1999", "m17": "1917"}),
                          ("iax_bindport", lambda: "4569"), ("rpt_links", lambda *a, **k: (False, []))):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)

    def write(self, text):
        with open(self.path, "w") as fh:
            fh.write(text)

    def read(self):
        with open(self.path) as fh:
            return fh.read()

    def test_first_node_is_1050_with_its_own_ports(self):
        r = nr.priv_add()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["node"], "1050")
        text = self.read()
        self.assertIn(nr.PRIV_NOTE + "\n[1050](node-main)\nrxchannel = USRP/127.0.0.1:34050:32050\n", text)
        self.assertIn("1050 = radio@127.0.0.1/1050,NONE", text)
        st = nr.priv_state()
        self.assertEqual([n["node"] for n in st["nodes"]], ["1050"])
        self.assertEqual(st["nodes"][0]["state"], "restart")
        self.assertEqual((st["nodes"][0]["in_port"], st["nodes"][0]["out_port"]), (34050, 32050))

    def test_state_is_ready_once_asterisk_knows_the_node(self):
        nr.priv_add()
        with mock.patch.object(nr, "rpt_links", lambda *a, **k: (True, [])):
            self.assertEqual(nr.priv_state()["nodes"][0]["state"], "ready")

    def test_nodes_count_up_and_skip_numbers_in_use(self):
        self.write(self.BASE + "\n[1050]\nrxchannel = Local/pseudo\n\n[functions1051]\n1=ilink,1\n")
        self.assertEqual(nr.priv_add()["node"], "1052")
        self.assertEqual(nr.priv_add()["node"], "1053")

    def test_ports_skip_ones_already_used(self):
        self.write(self.BASE + "\n[1999]\nrxchannel = USRP/127.0.0.1:34050:32050\n")
        nr.priv_add()
        self.assertIn("USRP/127.0.0.1:34051:32051", self.read())

    def test_at_most_five_nodes(self):
        for _ in range(nr.PRIV_MAX):
            self.assertTrue(nr.priv_add()["ok"])
        r = nr.priv_add()
        self.assertFalse(r["ok"])
        self.assertIn("at most 5", r["error"])
        self.assertFalse(nr.priv_state()["can_add"])

    def test_remove_one_leaves_the_others_and_the_rest_of_the_file(self):
        nr.priv_add()
        nr.priv_add()
        r = nr.priv_remove({"node": "1050"})
        self.assertTrue(r["ok"] and r["changed"], r)
        text = self.read()
        self.assertNotIn("[1050]", text)
        self.assertNotIn("1050 = radio", text)
        self.assertIn("[1051](node-main)", text)
        self.assertIn("1234 = radio@127.0.0.1/1234,NONE", text)

    def test_remove_all_restores_the_original_file(self):
        nr.priv_add()
        nr.priv_add()
        nr.priv_remove({"all": True})
        self.assertEqual(self.read(), self.BASE)

    def test_a_node_written_by_hand_is_never_removed(self):
        self.write(self.BASE + "\n[1050]\nrxchannel = Local/pseudo\n")
        r = nr.priv_remove({"node": "1050"})
        self.assertFalse(r["changed"])
        self.assertIn("[1050]", self.read())
        self.assertEqual(nr.priv_remove({"all": True})["changed"], False)

    def test_node_1921_is_left_alone(self):
        text = self.BASE + "\n" + nr.REC_NOTE + "\n[1921](node-main)\nrxchannel = USRP/127.0.0.1:34018:32018\n"
        self.write(text)
        nr.priv_add()
        nr.priv_remove({"all": True})
        self.assertEqual(self.read(), text)

    def test_needs_the_main_node(self):
        with mock.patch.object(nr, "main_node", lambda: ""):
            r = nr.priv_add()
        self.assertFalse(r["ok"])
        self.assertEqual(self.read(), self.BASE)

    def test_unreadable_rpt_conf_is_reported(self):
        os.remove(self.path)
        self.assertFalse(nr.priv_state()["ok"])
        self.assertFalse(nr.priv_add()["ok"])


def mk_entry(eid, node, start, end, target=None, days=None, enabled=True):
    raw = {"id": eid, "name": eid, "days": days if days is not None else [0, 1, 2, 3, 4, 5, 6], "start": start, "end": end,
           "target": target or {"mode": "ASL", "num": "2000"}, "format": "pcm", "node": node, "enabled": enabled}
    return nr.schedule_norm_entry(raw, check_target=False)


class NodeConflicts(unittest.TestCase):
    def test_overlap_on_different_nodes_is_not_a_conflict(self):
        a, b = mk_entry("a", "1050", "20:00", "21:00"), mk_entry("b", "1051", "20:30", "21:30")
        self.assertEqual(nr.schedule_conflicts([a, b]), [])

    def test_overlap_on_the_same_node_is_a_conflict(self):
        a, b = mk_entry("a", "1050", "20:00", "21:00"), mk_entry("b", "1050", "20:30", "21:30")
        self.assertEqual(len(nr.schedule_conflicts([a, b])), 1)

    def test_main_node_entries_still_conflict_with_each_other_only(self):
        a, b, c = mk_entry("a", "", "20:00", "21:00"), mk_entry("b", "", "20:30", "21:30"), mk_entry("c", "1050", "20:30", "21:30")
        names = nr.schedule_conflicts([a, b, c])
        self.assertEqual(len(names), 1)
        self.assertIn("a and b", names[0])

    def test_touching_windows_on_one_node_are_fine(self):
        a, b = mk_entry("a", "1050", "20:00", "21:00"), mk_entry("b", "1050", "21:00", "22:00")
        self.assertEqual(nr.schedule_conflicts([a, b]), [])

    def test_assign_reuses_a_free_node_and_skips_a_busy_one(self):
        a = mk_entry("a", "1050", "20:00", "21:00")
        new = mk_entry("n", "auto", "20:30", "21:30")
        self.assertEqual(nr.schedule_assign([a], new, ["1050", "1051"]), "1051")
        later = mk_entry("l", "auto", "22:00", "23:00")
        self.assertEqual(nr.schedule_assign([a], later, ["1050", "1051"]), "1050")
        self.assertIsNone(nr.schedule_assign([a], new, ["1050"]))

    def test_node_is_kept_and_validated(self):
        self.assertEqual(mk_entry("a", "1050", "20:00", "21:00")["node"], "1050")
        self.assertEqual(mk_entry("a", "", "20:00", "21:00")["node"], "")
        with self.assertRaises(ValueError):
            mk_entry("a", "12x4", "20:00", "21:00")
        self.assertEqual(mk_entry("a", "auto", "20:00", "21:00")["node"], "")


class ScheduleAssign(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nr_sched_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.pool = []
        for name, val in (("SCHEDULE_PATH", os.path.join(self.dir, "schedule.json")),
                          ("_tune_fav", lambda b: {"mode": b["mode"], "num": b["num"], "net": "", "label": ""}),
                          ("priv_pool", lambda: list(self.pool))):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)
        nr._sched_cache["key"] = None

    def save(self, eid, start, end, node="auto", mode="ASL"):
        return nr.schedule_set({"entry": {"id": eid, "name": eid, "days": [1], "start": start, "end": end,
                                          "target": {"mode": mode, "num": "2000"}, "format": "pcm", "node": node}})

    def test_without_private_nodes_entries_stay_on_the_main_node(self):
        r = self.save("a", "20:00", "21:00")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["entry"]["node"], "")
        self.assertIn("main node", r["message"])

    def test_auto_picks_first_free_private_node(self):
        self.pool = ["1050", "1051"]
        self.assertEqual(self.save("a", "20:00", "21:00")["entry"]["node"], "1050")
        self.assertEqual(self.save("b", "20:30", "21:30")["entry"]["node"], "1051")
        self.assertEqual(self.save("c", "22:00", "23:00")["entry"]["node"], "1050")

    def test_busy_nodes_suggest_a_new_one_until_the_cap(self):
        self.pool = ["1050"]
        self.save("a", "20:00", "21:00")
        r = self.save("b", "20:30", "21:30")
        self.assertFalse(r["ok"])
        self.assertTrue(r["need_node"])
        self.assertIn("Add another", r["error"])
        self.pool = ["105%d" % i for i in range(nr.PRIV_MAX)]
        for i, n in enumerate(self.pool[1:]):
            self.save("x%d" % i, "20:00", "21:00", node=n)
        r = self.save("z", "20:30", "21:30")
        self.assertFalse(r["ok"])
        self.assertFalse(r["need_node"])

    def test_digital_entries_stay_on_the_main_node(self):
        self.pool = ["1050"]
        r = self.save("d", "20:00", "21:00", mode="DMR")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["entry"]["node"], "")
        r = self.save("e", "22:00", "23:00", node="1050", mode="DMR")
        self.assertFalse(r["ok"])

    def test_explicit_node_must_be_one_of_ours(self):
        self.pool = ["1050"]
        self.assertFalse(self.save("a", "20:00", "21:00", node="1077")["ok"])
        self.assertTrue(self.save("a", "20:00", "21:00", node="1050")["ok"])


class FakeActions:
    log = []

    def __init__(self, node):
        self.node = node

    def connect(self, entry):
        FakeActions.log.append(("connect", self.node))
        return True, "", None

    def link_alive(self, entry):
        return True

    def healthy(self, entry):
        return True, ""

    def start(self, entry, window):
        FakeActions.log.append(("start", self.node))
        return True, "", "x.wav"

    def stop(self):
        FakeActions.log.append(("stop", self.node))
        return True, "", None

    def disconnect(self, entry):
        FakeActions.log.append(("disconnect", self.node))
        return True, "", None


class Lanes(unittest.TestCase):
    def test_two_nodes_record_at_the_same_time(self):
        now = nr.sched_now()
        start = (now - nr.timedelta(minutes=2)).strftime("%H:%M")
        end = (now + nr.timedelta(minutes=58)).strftime("%H:%M")
        entries = [mk_entry("a", "1050", start, end), mk_entry("b", "1051", start, end)]
        FakeActions.log = []
        with mock.patch.object(nr, "schedule_load", lambda: {"entries": entries, "error": ""}):
            lanes = [nr.Scheduler(real_actions=lambda n=n: FakeActions(n), node=n) for n in ("1050", "1051")]
            for ln in lanes:
                ln.state_path = os.path.join(WORK, "state_%s.json" % ln.node)
                ln.tick(now)
            deadline = nr.time.time() + 5
            while nr.time.time() < deadline and len([x for x in FakeActions.log if x[0] == "start"]) < 2:
                nr.time.sleep(0.05)
            self.assertEqual(sorted(x[1] for x in FakeActions.log if x[0] == "start"), ["1050", "1051"])
            self.assertTrue(all(ln.status()["state"] == "recording" for ln in lanes))
            for ln in lanes:
                ln.stop.set()
                ln.run_abort.set()
                ln.shutdown(5)
        self.assertEqual(sorted(x[1] for x in FakeActions.log if x[0] == "stop"), ["1050", "1051"])

    def test_a_lane_ignores_entries_of_other_nodes(self):
        now = nr.sched_now()
        start = (now - nr.timedelta(minutes=2)).strftime("%H:%M")
        end = (now + nr.timedelta(minutes=58)).strftime("%H:%M")
        entries = [mk_entry("a", "1051", start, end)]
        FakeActions.log = []
        with mock.patch.object(nr, "schedule_load", lambda: {"entries": entries, "error": ""}):
            ln = nr.Scheduler(real_actions=lambda: FakeActions("1050"), node="1050")
            ln.state_path = os.path.join(WORK, "state_other.json")
            ln.tick(now)
            nr.time.sleep(0.3)
        self.assertEqual(FakeActions.log, [])
        self.assertEqual(ln.status()["state"], "idle")


class PrivActionsTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.stream = mock.Mock()
        self.stream.engine.healthy.return_value = (True, "")
        entry = {"target": {"mode": "ASL", "num": "2000"}}
        self.entry = entry
        for name, val in (("priv_stream", lambda n: self.stream), ("rpt_links", lambda *a, **k: (True, [])),
                          ("ilink", lambda node, op, peer: (self.calls.append((node, op, peer)), (True, ""))[1]),
                          ("wait_link", lambda *a, **k: "up"),
                          ("_tune_fav", lambda b: {"mode": "ASL", "num": b["num"], "net": "", "label": ""})):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_links_in_local_monitor_mode_and_unlinks_with_a_plain_disconnect(self):
        a = nr.PrivActions("1050")
        ok, msg, _ = a.connect(self.entry)
        self.assertTrue(ok, msg)
        self.assertEqual(self.calls, [("1050", 8, "2000")])
        a.disconnect(self.entry)
        self.assertEqual(self.calls[-1], ("1050", 1, "2000"))

    def test_a_node_asterisk_does_not_know_yet_asks_for_a_restart(self):
        with mock.patch.object(nr, "rpt_links", lambda *a, **k: (False, [])):
            ok, msg, _ = nr.PrivActions("1050").connect(self.entry)
        self.assertFalse(ok)
        self.assertIn("restart Asterisk", msg)
        self.assertEqual(self.calls, [])

    def test_a_dropped_link_is_linked_again_and_counted_once(self):
        a = nr.PrivActions("1050")
        a.connect(self.entry)
        self.calls.clear()
        with mock.patch.object(nr, "_linked", lambda *a, **k: False):
            self.assertFalse(a.link_alive(self.entry))
        self.assertEqual(self.calls, [("1050", 8, "2000")])
        with mock.patch.object(nr, "_linked", lambda *a, **k: True):
            self.assertTrue(a.link_alive(self.entry))


class TwoEngines(unittest.TestCase):
    def test_two_recordings_write_two_files_and_are_marked_open(self):
        d = tempfile.mkdtemp(prefix="nr_eng_")
        self.addCleanup(shutil.rmtree, d, True)
        with mock.patch.object(nr, "storage_pick", lambda: {"ok": True, "path": d}):
            engines = [nr.RecordingEngine(nr.Hub(nr.RxClean(), None)) for _ in range(2)]
            entry = {"name": "t", "format": "pcm"}
            paths = []
            for i, e in enumerate(engines):
                ok, msg, name = e.start(dict(entry, name="t%d" % i), None)
                self.assertTrue(ok, msg)
                paths.append(os.path.join(d, name))
            self.assertTrue(set(paths) <= nr.open_paths())
            for e in engines:
                e.feed(b"\x01\x00" * nr.FRAME_SAMPLES)
            nr.time.sleep(0.3)
            self.assertEqual(nr.repair_recordings(d), 0)
            for e in engines:
                self.assertTrue(e.stop()[0])
        self.assertFalse(set(paths) & nr.open_paths())
        for p in paths:
            self.assertEqual(os.path.getsize(p), 44 + nr.FRAME_BYTES)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
