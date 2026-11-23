#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import importlib.util
import math
import os
import struct
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = sorted(glob.glob(os.path.join(ROOT, "nodetalker_v[0-9]*.py")))[-1]
spec = importlib.util.spec_from_file_location("nt_kc_under_test", path)
nt = importlib.util.module_from_spec(spec)
sys.modules["nt_kc_under_test"] = nt
spec.loader.exec_module(nt)


def loud():
    n = nt.FRAME_BYTES // 2
    return struct.pack("<%dh" % n, *[int(12000 * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(n)])


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Gate(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cfg = {"kerchunk_delay_ms": 1000, "kerchunk_quiet_sec": 0}
        real = nt._cfg_get
        for p in (mock.patch.object(nt.time, "monotonic", self.clock),
                  mock.patch.object(nt, "_cfg_get", side_effect=lambda k: self.cfg[k] if k in self.cfg else real(k))):
            p.start()
            self.addCleanup(p.stop)
        self.hub = nt.Hub()
        self.lst = nt._Listener("127.0.0.1", True)
        self.hub.listeners.add(self.lst)
        self.frame = loud()
        self.sent = 0

    def run_for(self, secs, talking):
        for _ in range(int(secs * 50)):
            if talking:
                self.hub.frames.append(self.frame)
            self.hub.tick()
            self.sent += sum(1 for x in self.lst.q if x != nt.PCM_SILENCE)
            self.lst.q.clear()
            self.clock.t += 0.02

    def talk(self, secs):
        before = self.sent
        self.run_for(secs, True)
        return self.sent - before

    def silence(self, secs):
        self.run_for(secs, False)

    def test_without_a_quiet_time_every_transmission_waits(self):
        self.silence(5)
        first = self.talk(2.0)
        self.silence(3)
        t0 = self.clock.t
        self.sent = 0
        self.hub.frames.append(self.frame)
        for _ in range(10):
            self.hub.tick()
            self.clock.t += 0.02
        self.assertEqual(self.sent + sum(1 for x in self.lst.q if x != nt.PCM_SILENCE), 0)
        self.assertGreater(first, 0)
        self.assertGreater(self.clock.t, t0)

    def test_a_kerchunk_after_a_quiet_spell_is_dropped_with_a_quiet_time_set(self):
        self.cfg["kerchunk_quiet_sec"] = 30
        self.silence(40)
        self.assertEqual(self.talk(0.2), 0)
        self.silence(3)
        self.assertEqual(self.sent, 0)

    def test_a_long_transmission_after_a_quiet_spell_still_plays(self):
        self.cfg["kerchunk_quiet_sec"] = 30
        self.silence(40)
        self.talk(2.0)
        self.silence(3)
        self.assertGreater(self.sent, 0)

    def test_a_reply_inside_the_quiet_time_plays_at_once(self):
        self.cfg["kerchunk_quiet_sec"] = 30
        self.silence(40)
        self.talk(2.0)
        self.silence(3)
        self.sent = 0
        self.talk(0.1)
        self.assertGreater(self.sent, 0)

    def test_a_short_reply_inside_the_quiet_time_is_not_treated_as_a_kerchunk(self):
        self.cfg["kerchunk_quiet_sec"] = 30
        self.silence(40)
        self.talk(2.0)
        self.silence(3)
        self.sent = 0
        n = self.talk(0.2)
        self.silence(2)
        self.assertGreater(n + self.sent, 0)

    def test_after_the_quiet_time_the_next_transmission_is_checked_again(self):
        self.cfg["kerchunk_quiet_sec"] = 10
        self.silence(40)
        self.talk(2.0)
        self.silence(15)
        self.sent = 0
        self.assertEqual(self.talk(0.2), 0)
        self.silence(3)
        self.assertEqual(self.sent, 0)

    def test_the_setting_is_validated(self):
        norm = nt.CONFIG_VALIDATORS["kerchunk_quiet_sec"] if hasattr(nt, "CONFIG_VALIDATORS") else None
        fn = norm or nt._norm_kc_quiet
        self.assertEqual(fn("0"), 0)
        self.assertEqual(fn("60"), 60)
        for bad in ("1", "4", "601", "x"):
            with self.assertRaises(ValueError):
                fn(bad)
        self.assertEqual(nt.DEFAULT_CONFIG["kerchunk_quiet_sec"], 0)
        self.assertTrue(nt.DEFAULT_CONFIG["jitter_adapt"])
        self.assertTrue(nt.DEFAULT_CONFIG["rx_plc"])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
