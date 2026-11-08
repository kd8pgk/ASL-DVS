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


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
