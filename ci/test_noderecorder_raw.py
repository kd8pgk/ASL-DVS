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


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
