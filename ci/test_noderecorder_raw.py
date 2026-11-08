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
        self.problems = []
        for name, val in (("SCHEDULE_PATH", os.path.join(self.dir, "schedule.json")),
                          ("_tune_fav", lambda b: {"mode": b["mode"], "num": b["num"], "net": "", "label": ""}),
                          ("priv_pool", lambda: list(self.pool))):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)
        nr._sched_cache["key"] = None

    def save(self, eid, start, end, node="auto", mode="ASL", num="2000"):
        with mock.patch.object(nr, "bridge_preflight", lambda f: self.problems):
            return nr.schedule_set({"entry": {"id": eid, "name": eid, "days": [1], "start": start, "end": end,
                                              "target": {"mode": mode, "num": num}, "format": "pcm", "node": node}})

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

    def test_digital_entries_can_take_a_private_node(self):
        self.pool = ["1050"]
        r = self.save("d", "20:00", "21:00", mode="DMR", num="3100")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["entry"]["node"], "1050")
        self.assertIn("bridge", r["message"])

    def test_digital_entry_that_cannot_be_tuned_is_refused(self):
        self.pool = ["1050"]
        self.problems = ["dvswitch.sh was not found, so DMR can't be tuned here"]
        r = self.save("d", "20:00", "21:00", mode="DMR", num="3100")
        self.assertFalse(r["ok"])
        self.assertIn("dvswitch.sh", r["error"])

    def test_different_digital_targets_clash_on_the_bridge_whatever_the_node(self):
        self.pool = ["1050", "1051", "1052"]
        self.assertTrue(self.save("d", "20:00", "21:00", mode="DMR", num="3100")["ok"])
        r = self.save("e", "20:30", "21:30", mode="DMR", num="91")
        self.assertFalse(r["ok"])
        self.assertIn("bridge", r["error"])
        self.assertNotIn("Add another", r["error"])
        self.assertTrue(self.save("f", "20:30", "21:30", mode="DMR", num="3100")["ok"])
        self.assertTrue(self.save("g", "20:30", "21:30", mode="M17", num="M17-ABC")["ok"])

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


class BridgeHolds(unittest.TestCase):
    def setUp(self):
        self.tunes, self.parks = [], []
        self.main_links = []
        self.fav = {"mode": "DMR", "num": "3100", "net": "TGIF", "label": ""}
        for name, val in (("bridge_nodes", lambda *a, **k: {"digital": "1999", "m17": "1917"}),
                          ("main_node", lambda: "1234"), ("nc_running", lambda *a, **k: False),
                          ("rpt_links", lambda node, **k: (True, list(self.main_links) if node == "1234" else [])),
                          ("bridge_tune", lambda kind, f: (self.tunes.append((kind, nr.fav_target(f))), "")[1]),
                          ("bridge_park", lambda kind, f: self.parks.append(kind))):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(nr._solo, {"mode": "", "target": "", "name": "", "bridge": ""})
        p.start()
        self.addCleanup(p.stop)
        nr._bridge_use["digital"] = nr._bridge_use["m17"] = None
        self.addCleanup(lambda: nr._bridge_use.update(digital=None, m17=None))

    def f(self, num="3100"):
        return dict(self.fav, num=num)

    def link_main_to_bridge(self):
        self.main_links = [{"node": "1999", "dir": "OUT", "time": "", "state": "ESTABLISHED"}]

    def test_free_bridge_is_tuned_then_parked_by_the_last_user(self):
        ok, res = nr.bridge_acquire(self.f(), {"name": "A"}, "1050")
        self.assertEqual((ok, res), (True, "1999"))
        self.assertEqual(len(self.tunes), 1)
        ok, res = nr.bridge_acquire(self.f(), {"name": "B"}, "1051")
        self.assertTrue(ok)
        self.assertEqual(len(self.tunes), 1)
        nr.bridge_release(self.f(), "1050")
        self.assertEqual(self.parks, [])
        nr.bridge_release(self.f(), "1051")
        self.assertEqual(self.parks, ["digital"])

    def test_another_target_is_refused_while_a_recording_holds_the_bridge(self):
        nr.bridge_acquire(self.f(), {"name": "A"}, "1050")
        ok, res = nr.bridge_acquire(self.f("91"), {"name": "B"}, "1051")
        self.assertFalse(ok)
        self.assertIn("recording A", res)

    def test_m17_and_digital_are_separate_bridges(self):
        nr.bridge_acquire(self.f(), {"name": "A"}, "1050")
        m17 = {"mode": "M17", "num": "M17-ABC", "module": "A", "label": ""}
        ok, res = nr.bridge_acquire(m17, {"name": "B"}, "1051")
        self.assertEqual((ok, res), (True, "1917"))

    def test_a_live_tune_by_someone_else_makes_the_recording_skip(self):
        self.link_main_to_bridge()
        nr._solo.update(mode="DMR", target=nr.fav_target(self.f("91")), name="DMR TGIF 91", bridge="1999")
        ok, res = nr.bridge_acquire(self.f(), {"name": "A"}, "1050")
        self.assertFalse(ok)
        self.assertIn("live tune", res)
        self.assertEqual(self.tunes, [])

    def test_the_same_live_tune_is_shared_and_left_alone(self):
        self.link_main_to_bridge()
        nr._solo.update(mode="DMR", target=nr.fav_target(self.f()), name="DMR TGIF 3100", bridge="1999")
        ok, _ = nr.bridge_acquire(self.f(), {"name": "A"}, "1050")
        self.assertTrue(ok)
        self.assertEqual(self.tunes, [])
        nr.bridge_release(self.f(), "1050")
        self.assertEqual(self.parks, [])

    def test_a_taken_bridge_is_not_parked_over_the_new_tune(self):
        nr.bridge_acquire(self.f(), {"name": "A"}, "1050")
        nr.bridge_release(self.f(), "1050", taken=True)
        self.assertEqual(self.parks, [])

    def test_tune_guard_asks_before_taking_a_held_bridge(self):
        nr.bridge_acquire(self.f(), {"name": "A"}, "1050")
        nr.bridge_set_end(self.f(), "2026-11-08T21:00")
        b = {"mode": "DMR", "num": "91", "net": "TGIF"}
        with mock.patch.object(nr, "_tune_fav", lambda x: dict(x, label="")):
            r = nr.tune_connect(b)
            self.assertTrue(r["need_confirm"])
            self.assertIn("until 21:00", r["error"])
            self.assertIsNone(nr._tune_guard(dict(b, force=True)))
            self.assertIsNone(nr._tune_guard(dict(b, num="3100")))
            self.assertIsNone(nr._tune_guard({"mode": "ASL", "num": "2000"}))

    def test_preflight_names_what_is_missing(self):
        with mock.patch.object(nr, "dvs_path", lambda: ""), mock.patch.object(nr, "nets_load", lambda: []):
            problems = nr.bridge_preflight(self.f())
        self.assertEqual(len(problems), 2)
        with mock.patch.object(nr, "dvs_path", lambda: "/x/dvswitch.sh"), mock.patch.object(nr, "nets_load", lambda: [{"name": "TGIF"}]):
            self.assertEqual(nr.bridge_preflight(self.f()), [])
        with mock.patch.object(nr, "bridge_nodes", lambda *a, **k: {"digital": "", "m17": ""}), \
                mock.patch.object(nr, "dvs_path", lambda: "/x"), mock.patch.object(nr, "nets_load", lambda: [{"name": "TGIF"}]):
            self.assertIn("bridge node", nr.bridge_preflight(self.f())[0])

    def test_load_warning_only_above_the_threshold(self):
        with mock.patch.object(nr.os, "getloadavg", lambda: (4.5, 1.0, 1.0)):
            self.assertIn("4.5", nr.load_warning())
        with mock.patch.object(nr.os, "getloadavg", lambda: (3.9, 1.0, 1.0)):
            self.assertEqual(nr.load_warning(), "")


class DigitalActions(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.main_links = []
        self.stream = mock.Mock()
        self.parks = []
        self.entry = {"name": "DMR rec", "target": {"mode": "DMR", "num": "3100", "net": "TGIF"}}
        for name, val in (("priv_stream", lambda n: self.stream), ("bridge_nodes", lambda *a, **k: {"digital": "1999", "m17": "1917"}),
                          ("main_node", lambda: "1234"), ("nc_running", lambda *a, **k: False),
                          ("rpt_links", lambda node, **k: (True, list(self.main_links) if node == "1234" else [])),
                          ("ilink", lambda node, op, peer: (self.calls.append((node, op, peer)), (True, ""))[1]),
                          ("wait_link", lambda *a, **k: "up"), ("_linked", lambda *a, **k: True),
                          ("bridge_preflight", lambda f: []), ("bridge_tune", lambda kind, f: ""),
                          ("bridge_park", lambda kind, f: self.parks.append(kind)),
                          ("_tune_fav", lambda b: {"mode": b["mode"], "num": b["num"], "net": b.get("net", ""), "label": ""})):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(nr._solo, {"mode": "", "target": "", "name": "", "bridge": ""})
        p.start()
        self.addCleanup(p.stop)
        nr._bridge_use["digital"] = nr._bridge_use["m17"] = None
        self.addCleanup(lambda: nr._bridge_use.update(digital=None, m17=None))

    def test_links_the_private_node_to_the_bridge_and_lets_go_after(self):
        a = nr.PrivActions("1050")
        ok, msg, _ = a.connect(self.entry)
        self.assertTrue(ok, msg)
        self.assertEqual(self.calls, [("1050", 8, "1999")])
        self.assertTrue(nr.bridge_holds())
        a.disconnect(self.entry)
        self.assertEqual(self.calls[-1], ("1050", 1, "1999"))
        self.assertEqual(self.parks, ["digital"])
        self.assertEqual(nr.bridge_holds(), [])

    def test_a_live_tune_on_the_main_node_stops_the_recording_and_keeps_the_bridge(self):
        a = nr.PrivActions("1050")
        a.connect(self.entry)
        self.main_links = [{"node": "1999", "dir": "OUT", "time": "", "state": "ESTABLISHED"}]
        nr._solo.update(mode="DMR", target="DMR|TGIF|91", name="DMR TGIF 91", bridge="1999")
        self.assertEqual(a.link_alive(self.entry), "taken")
        a.disconnect(self.entry)
        self.assertEqual(self.parks, [])

    def test_a_refused_tune_fails_the_window_without_linking(self):
        with mock.patch.object(nr, "bridge_tune", lambda kind, f: "DMR network TGIF did not answer"):
            ok, msg, _ = nr.PrivActions("1050").connect(self.entry)
        self.assertFalse(ok)
        self.assertIn("TGIF", msg)
        self.assertIn("this recording is skipped", msg)
        self.assertEqual(self.calls, [])
        self.assertEqual(nr.bridge_holds(), [])

    def test_missing_pieces_stop_the_window_before_any_tune(self):
        with mock.patch.object(nr, "bridge_preflight", lambda f: ["dvswitch.sh was not found"]):
            ok, msg, _ = nr.PrivActions("1050").connect(self.entry)
        self.assertFalse(ok)
        self.assertIn("dvswitch.sh", msg)

    def test_run_sequence_ends_with_bridge_taken_and_keeps_the_file(self):
        class A(FakeActions):
            taken = "DMR TGIF 91"

            def link_alive(self, entry):
                return "taken"
        FakeActions.log = []
        abort = nr.threading.Event()
        res = nr.run_sequence({"name": "x", "format": "pcm", "target": {}}, A("1050"), nr.time.time() + 60, abort,
                              lambda *a, **k: None, nr.time.time, lambda s: nr.time.sleep(0.01),
                              timeouts={"connect": 5, "start": 5, "stop": 5, "disconnect": 5})
        self.assertEqual(res["result"], "bridge_taken")
        self.assertIn("DMR TGIF 91", res["detail"])
        self.assertIn(("stop", "1050"), FakeActions.log)


class Scripted(FakeActions):
    script = []
    seen = []

    def __init__(self, node):
        super().__init__(node)
        self.plan = Scripted.script.pop(0) if Scripted.script else {}
        self.checks = 0

    def connect(self, entry):
        Scripted.seen.append(dict(entry))
        if not self.plan.get("connect", True):
            return False, "Asterisk does not know node yet", None
        return True, "", None

    def link_alive(self, entry):
        self.checks += 1
        drop = self.plan.get("drop_after")
        return not (drop is not None and self.checks > drop)


class SecondPart(unittest.TestCase):
    def setUp(self):
        for name, val in (("LINK_CHECK_SEC", 0.05), ("RETRY_SEC", 0.3), ("RETRY_MAX", 20)):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)
        Scripted.script, Scripted.seen, FakeActions.log = [], [], []
        self.now = nr.sched_now()
        start = (self.now - nr.timedelta(minutes=2)).strftime("%H:%M")
        end = (self.now + nr.timedelta(minutes=58)).strftime("%H:%M")
        self.entries = [mk_entry("a", "1050", start, end)]
        p = mock.patch.object(nr, "schedule_load", lambda: {"entries": self.entries, "error": ""})
        p.start()
        self.addCleanup(p.stop)
        self.removed = []
        p = mock.patch.object(nr, "_special_remove", lambda eid: self.removed.append(eid))
        p.start()
        self.addCleanup(p.stop)
        self.lane = nr.Scheduler(real_actions=lambda: Scripted("1050"), node="1050")
        self.lane.state_path = os.path.join(WORK, "state_part_%s.json" % id(self))
        self.lane.sleep = lambda s: nr.time.sleep(min(s, 0.05))
        self.addCleanup(self.finish)

    def finish(self):
        self.lane.stop.set()
        self.lane.run_abort.set()
        self.lane.shutdown(5)

    def drive(self, until, secs=15):
        end = nr.time.time() + secs
        while nr.time.time() < end:
            self.lane.tick(self.now)
            if until():
                return True
            nr.time.sleep(0.05)
        return False

    def test_a_dropped_link_starts_a_second_part_while_the_window_is_open(self):
        Scripted.script = [{"drop_after": 1}, {}]
        self.assertTrue(self.drive(lambda: len(Scripted.seen) >= 2))
        self.assertNotIn("part", Scripted.seen[0])
        self.assertEqual(Scripted.seen[1]["part"], 2)
        first = self.lane.results[0]
        self.assertEqual(first["result"], "link_lost")
        self.assertIn("trying again", first["detail"])
        self.assertEqual(self.lane.done, {})

    def test_a_first_connect_failure_is_not_retried(self):
        Scripted.script = [{"connect": False}]
        self.assertTrue(self.drive(lambda: self.lane.done))
        nr.time.sleep(0.6)
        self.lane.tick(self.now)
        self.assertEqual(len(Scripted.seen), 1)

    def test_asterisk_still_down_is_tried_again_and_the_part_number_skips_failures(self):
        Scripted.script = [{"drop_after": 1}, {"connect": False}, {}]
        self.assertTrue(self.drive(lambda: len(Scripted.seen) >= 3))
        self.assertEqual(Scripted.seen[2]["part"], 2)
        self.assertEqual(self.lane.done, {})

    def test_it_gives_up_after_the_retry_limit(self):
        Scripted.script = [{"drop_after": 1}, {"connect": False}, {"connect": False}]
        with mock.patch.object(nr, "RETRY_MAX", 3):
            self.assertTrue(self.drive(lambda: self.lane.done))
        self.assertEqual(len(Scripted.seen), 3)

    def test_no_second_part_when_the_window_is_nearly_over(self):
        end = (self.now + nr.timedelta(minutes=1)).strftime("%H:%M")
        start = (self.now - nr.timedelta(minutes=30)).strftime("%H:%M")
        self.entries = [mk_entry("a", "1050", start, end)]
        Scripted.script = [{"drop_after": 1}]
        self.assertTrue(self.drive(lambda: self.lane.done))
        self.assertEqual(len(Scripted.seen), 1)

    def test_a_stop_by_hand_is_not_retried(self):
        Scripted.script = [{}]
        self.assertTrue(self.drive(lambda: self.lane.state == "recording"))
        self.lane.stop_by_hand()
        self.assertTrue(self.drive(lambda: self.lane.state == "idle" and self.lane.done))
        nr.time.sleep(0.5)
        self.lane.tick(self.now)
        self.assertEqual(len(Scripted.seen), 1)

    def test_a_special_is_kept_until_its_last_part(self):
        raw = {"id": "sp", "name": "sp", "days": [], "start": self.entries[0]["start"], "end": self.entries[0]["end"],
               "target": {"mode": "ASL", "num": "2000"}, "format": "pcm", "node": "1050", "kind": "special",
               "date": self.now.strftime("%Y-%m-%d"), "enabled": True}
        self.entries = [nr.schedule_norm_entry(raw, check_target=False)]
        Scripted.script = [{"drop_after": 1}, {"drop_after": 1}]
        self.assertTrue(self.drive(lambda: len(Scripted.seen) >= 2))
        self.assertEqual(self.removed, [])

    def test_the_part_count_survives_a_restart(self):
        Scripted.script = [{"drop_after": 1}, {}]
        self.assertTrue(self.drive(lambda: len(Scripted.seen) >= 2))
        self.lane._state_save()
        again = nr.Scheduler(real_actions=lambda: Scripted("1050"), node="1050")
        again.state_path = self.lane.state_path
        again._state_load()
        self.assertEqual(again.parts["a"]["began"], self.lane.parts["a"]["began"])
        self.assertGreaterEqual(again.parts["a"]["began"], 1)

    def test_the_second_part_gets_its_own_file_name(self):
        d = tempfile.mkdtemp(prefix="nr_part_")
        self.addCleanup(shutil.rmtree, d, True)
        with mock.patch.object(nr, "storage_pick", lambda: {"ok": True, "path": d}):
            e = nr.RecordingEngine(nr.Hub(nr.RxClean(), None))
            ok, _msg, name = e.start({"name": "Net", "format": "pcm", "part": 2}, None)
            self.assertTrue(ok)
            e.stop()
        self.assertIn("Net-part-2", name)


class Gate1921(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.events = []
        self.state = {"node": "1921", "main": "1234", "ready": True, "linked": False, "owner": "recorder", "wanted": False}
        for name, val in (("rec_node_state", lambda *a, **k: dict(self.state)), ("talker_active", lambda: False),
                          ("main_node", lambda: "1234"),
                          ("rpt_links", lambda node, **k: (True, [{"node": "1921", "dir": "OUT", "time": "", "state": "ESTABLISHED"}]
                                                         if self.state["linked"] else [])),
                          ("ilink", lambda node, op, peer: (self.calls.append((node, op, peer)), (True, ""))[1])):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_idle_node_is_left_unlinked(self):
        self.assertIsNone(nr.link_keeper_step(True))
        self.assertEqual(self.calls, [])

    def test_a_left_over_link_is_dropped_when_nothing_records_the_main_node(self):
        self.state["linked"] = True
        self.assertIsNone(nr.link_keeper_step(True))
        self.assertEqual(self.calls, [("1234", 1, "1921")])

    def test_it_is_linked_while_the_main_node_records_and_relinked_if_it_drops(self):
        self.state["wanted"] = True
        self.assertIs(nr.link_keeper_step(None), False)
        self.assertEqual(self.calls, [("1234", 3, "1921")])
        self.state["linked"] = True
        self.calls.clear()
        self.assertIs(nr.link_keeper_step(False), True)
        self.assertEqual(self.calls, [])

    def test_node_talker_owning_the_node_is_never_touched(self):
        self.state.update(owner="talker", linked=True)
        self.assertEqual(nr.link_keeper_step("keep"), "keep")
        self.assertEqual(self.calls, [])
        self.state.update(owner="recorder", wanted=False)
        with mock.patch.object(nr, "talker_active", lambda: True):
            self.assertIsNone(nr.link_keeper_step(True))
        self.assertEqual(self.calls, [])

    def test_a_node_that_is_not_set_up_is_skipped(self):
        self.state.update(ready=False, wanted=True)
        self.assertEqual(nr.link_keeper_step("keep"), "keep")
        self.assertEqual(self.calls, [])

    def test_the_main_node_actions_link_before_recording_and_release_after(self):
        self.state["wanted"] = True
        order = []
        with mock.patch.object(nr.ENGINE, "start", lambda e, w: (order.append("engine start"), (True, "", "x.wav"))[1]), \
                mock.patch.object(nr.ENGINE, "stop", lambda: (order.append("engine stop"), (True, "", None))[1]):
            a = nr.RealActions()
            self.assertTrue(a.start({"name": "x", "format": "pcm"}, None)[0])
            self.assertEqual(self.calls, [("1234", 3, "1921")])
            self.state["linked"] = True
            self.assertTrue(a.stop()[0])
        self.assertEqual(self.calls[-1], ("1234", 1, "1921"))
        self.assertEqual(order, ["engine start", "engine stop"])

    def test_record_now_uses_the_same_link(self):
        self.state["wanted"] = True
        with mock.patch.object(nr.ENGINE, "start", lambda e, w: (True, "", "x.wav")):
            nr.CurrentLinkActions().start({"name": "x", "format": "pcm"}, None)
        self.assertEqual(self.calls, [("1234", 3, "1921")])

    def test_main_recording_follows_the_main_lane_and_ignores_dry_runs(self):
        for status, want in (({"state": "idle", "current": None}, False),
                             ({"state": "recording", "current": {"dry_run": False}}, True),
                             ({"state": "connecting", "current": {"dry_run": False}}, True),
                             ({"state": "recording", "current": {"dry_run": True}}, False)):
            with mock.patch.object(nr.SCHED, "status", lambda s=status: s):
                self.assertEqual(nr.main_recording(), want, status)

    def test_private_node_recordings_do_not_count(self):
        with mock.patch.object(nr.SCHED, "status", lambda: {"state": "idle", "current": None}), \
                mock.patch.object(nr, "lanes_status", lambda: [{"name": "Net", "node": "1050"}]):
            self.assertFalse(nr.main_recording())


class TestTune(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.recording = False
        self.known = True
        self.state = "up"
        self.preflight = []
        self.acquire = (True, "1999")
        self.stream = mock.Mock()
        self.stream.recording = lambda: self.recording
        self.stream.hub.packets = 0
        self.asl = mk_entry("a", "", "20:00", "21:00")
        self.dmr = mk_entry("d", "1050", "20:00", "21:00", target={"mode": "DMR", "num": "3100", "net": "TGIF"})
        self.entries = [self.asl, self.dmr]
        for name, val in (("schedule_load", lambda: {"entries": self.entries, "error": ""}), ("priv_pool", lambda: ["1050", "1051"]),
                          ("priv_stream", lambda n: self.stream), ("lane_of", lambda n: None),
                          ("rpt_links", lambda *a, **k: (self.known, [])), ("wait_link", lambda *a, **k: self.state),
                          ("_linked", lambda *a, **k: self.state == "up"),
                          ("ilink", lambda node, op, peer: (self.log.append(("ilink", node, op, peer)), (True, ""))[1]),
                          ("bridge_preflight", lambda f: self.preflight),
                          ("bridge_acquire", lambda f, e, n: (self.log.append(("acquire", n)), self.acquire)[1]),
                          ("bridge_release", lambda f, n, taken=False: self.log.append(("release", n))),
                          ("_tune_fav", lambda b: {"mode": b["mode"], "num": b["num"], "net": b.get("net", ""), "label": ""}),
                          ("TEST_HOLD_SEC", 0.0)):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_an_asl_target_is_linked_held_and_let_go(self):
        r = nr.priv_test_tune({"id": "a", "node": "auto"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["node"], "1050")
        self.assertEqual(self.log, [("ilink", "1050", 8, "2000"), ("ilink", "1050", 1, "2000")])
        self.assertEqual([s["step"] for s in r["steps"]], ["link", "hold", "release"])

    def test_a_digital_target_tunes_the_bridge_first_and_gives_it_back(self):
        r = nr.priv_test_tune({"id": "d", "node": "auto"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.log, [("acquire", "1050"), ("ilink", "1050", 8, "1999"), ("ilink", "1050", 1, "1999"), ("release", "1050")])
        self.assertEqual([s["step"] for s in r["steps"]], ["check", "tune", "link", "hold", "release"])

    def test_missing_pieces_stop_it_before_any_tune(self):
        self.preflight = ["dvswitch.sh was not found, so DMR can't be tuned here"]
        r = nr.priv_test_tune({"id": "d"})
        self.assertFalse(r["ok"])
        self.assertIn("dvswitch.sh", r["error"])
        self.assertEqual(self.log, [])

    def test_a_bridge_in_use_is_not_touched(self):
        self.acquire = (False, "the digital bridge is in use by a live tune (DMR TGIF 91)")
        r = nr.priv_test_tune({"id": "d"})
        self.assertFalse(r["ok"])
        self.assertIn("live tune", r["error"])
        self.assertEqual(self.log, [("acquire", "1050")])

    def test_a_link_that_does_not_come_up_is_reported_and_cleaned_up(self):
        self.state = "down"
        r = nr.priv_test_tune({"id": "d"})
        self.assertFalse(r["ok"])
        self.assertEqual(self.log[-2:], [("ilink", "1050", 1, "1999"), ("release", "1050")])
        self.assertEqual(r["steps"][-1]["step"], "release")

    def test_a_dropped_link_while_holding_fails_the_test(self):
        with mock.patch.object(nr, "_linked", lambda *a, **k: False):
            r = nr.priv_test_tune({"id": "a"})
        self.assertFalse(r["ok"])
        self.assertIn("dropped", r["error"])

    def test_it_skips_a_recording_node_and_says_so_when_none_is_free(self):
        self.recording = True
        r = nr.priv_test_tune({"id": "a"})
        self.assertFalse(r["ok"])
        self.assertIn("recording", r["error"])
        self.assertEqual(self.log, [])
        self.recording = False
        self.known = False
        self.assertIn("restart Asterisk", nr.priv_test_tune({"id": "a", "node": "1051"})["error"])

    def test_a_node_that_is_not_ours_is_refused(self):
        r = nr.priv_test_tune({"id": "a", "node": "1077"})
        self.assertFalse(r["ok"])
        self.assertIn("not one of", r["error"])

    def test_unknown_entry_and_no_nodes(self):
        self.assertFalse(nr.priv_test_tune({"id": "zz"})["ok"])
        with mock.patch.object(nr, "priv_pool", lambda: []):
            self.assertIn("Add one", nr.priv_test_tune({"id": "a"})["error"])

    def test_only_one_test_at_a_time(self):
        self.assertTrue(nr._test_tune_lock.acquire(blocking=False))
        try:
            r = nr.priv_test_tune({"id": "a"})
        finally:
            nr._test_tune_lock.release()
        self.assertFalse(r["ok"])
        self.assertIn("already running", r["error"])
        self.assertEqual(self.log, [])

    def test_the_entrys_own_node_is_preferred(self):
        r = nr.priv_test_tune({"id": "d", "node": "auto"})
        self.assertEqual(r["node"], "1050")
        self.entries = [mk_entry("e", "1051", "20:00", "21:00")]
        self.assertEqual(nr.priv_test_tune({"id": "e", "node": "auto"})["node"], "1051")


class NextBridge(unittest.TestCase):
    def test_lists_the_soonest_digital_window_within_the_notice_time(self):
        now = nr.sched_now()
        soon = (now + nr.timedelta(minutes=10)).strftime("%H:%M")
        later = (now + nr.timedelta(minutes=20)).strftime("%H:%M")
        far = (now + nr.timedelta(minutes=90)).strftime("%H:%M")
        end = lambda s: (nr.datetime.strptime(s, "%H:%M") + nr.timedelta(minutes=30)).strftime("%H:%M")
        entries = [mk_entry("a", "1050", later, end(later), target={"mode": "DMR", "num": "91", "net": "TGIF"}),
                   mk_entry("b", "1051", soon, end(soon), target={"mode": "M17", "num": "M17-ABC", "module": "A"}),
                   mk_entry("c", "1052", soon, end(soon)),
                   mk_entry("d", "1053", far, end(far), target={"mode": "DMR", "num": "3100", "net": "TGIF"})]
        with mock.patch.object(nr, "schedule_load", lambda: {"entries": entries, "error": ""}):
            nb = nr.next_bridge_window()
        self.assertEqual((nb["name"], nb["kind"], nb["node"]), ("b", "m17", "1051"))
        self.assertEqual(nb["start"][11:16], soon)

    def test_empty_when_nothing_digital_is_near(self):
        now = nr.sched_now()
        far = (now + nr.timedelta(minutes=90)).strftime("%H:%M")
        entries = [mk_entry("d", "1053", far, "23:59", target={"mode": "DMR", "num": "3100", "net": "TGIF"}),
                   mk_entry("e", "1050", far, "23:59")]
        with mock.patch.object(nr, "schedule_load", lambda: {"entries": entries, "error": ""}):
            self.assertEqual(nr.next_bridge_window(), {})


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
