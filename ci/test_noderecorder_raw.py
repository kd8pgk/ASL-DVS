import glob
import importlib.util
import json
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


class SuiteLog(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(WORK, "suitelog.jsonl")
        self.flag = os.path.join(WORK, "suitelog.on")
        self.patches = [
            mock.patch.object(nr, "SUITELOG_PATH", self.path),
            mock.patch.object(nr, "SUITELOG_FLAG", self.flag),
            mock.patch.object(nr, "_sl_flag", {"at": -10.0, "salt": None}),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        for f in (self.path, self.flag):
            if os.path.exists(f):
                os.remove(f)

    def rows(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path) as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]

    def test_no_rows_when_the_flag_is_off(self):
        nr.log_event("Recording started: /x", "ok")
        nr.log_event("a warning", "warn")
        self.assertEqual(self.rows(), [])

    def test_warn_err_and_ok_rows_when_the_flag_is_on(self):
        with open(self.flag, "w") as fh:
            fh.write("salt-x")
        nr.log_event("Recording started", "ok")
        nr.log_event("Waiting for node audio", "info")
        nr.log_event("UDP receive error", "err")
        rows = self.rows()
        self.assertEqual([r["data"]["level"] for r in rows], ["ok", "err"])
        self.assertTrue(all(r["kind"] == "log" and r["src"] == "noderecorder" for r in rows))
        self.assertEqual(rows[0]["v"], nr.VERSION)

    def test_suite_log_functions_match_the_shared_copy(self):
        with open(os.path.join(ROOT, "shared", "confio.py")) as fh:
            conf = fh.read()
        with open(NR_FILE) as fh:
            src = fh.read()
        for name in ("suitelog_redact", "suitelog_append", "suitelog_rows", "suitelog_flag"):
            start = conf.index("\ndef %s(" % name) + 1
            m = re.compile(r"\n(?=def |class |[A-Z_]+ = )").search(conf, start + 1)
            body = conf[start:(m.start() + 1 if m else len(conf))]
            self.assertIn(body, src, name)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
