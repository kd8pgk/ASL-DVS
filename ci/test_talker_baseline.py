import array
import json
import math
import os
import socket
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_talker_stream as ts

ROOT = ts.ROOT
FS = 8000
FRAME = 160
FRAME_SEC = 0.02
CYCLE_SEC = 3.0
CYCLES = 4
WARM_CYCLES = 1
BASELINE_OUT = os.environ.get("NT_BASELINE_OUT") or ""


def tone_frames(hz, amp, secs, phase=0.0):
    out = []
    n = int(round(secs * FS))
    for i in range(n):
        out.append(int(round(amp * math.sin(2 * math.pi * hz * (i + phase) / FS))))
    return out


def signal_cycle(name):
    silent = [0] * int(FS * 1.0)
    if name == "tone":
        body = tone_frames(1000.0, 8000, 1.0)
        return silent + body + [0] * int(FS * 1.0)
    if name == "hum_tone":
        hum = tone_frames(60.0, 4000, 1.0)
        tn = tone_frames(1000.0, 8000, 1.0)
        return silent + [a + b for a, b in zip(hum, tn)] + [0] * int(FS * 1.0)
    if name == "hum_floor":
        return tone_frames(60.0, 1000, CYCLE_SEC)
    raise ValueError(name)


def to_frames(samples):
    out = []
    for i in range(0, len(samples) - FRAME + 1, FRAME):
        out.append(struct_pack(samples[i:i + FRAME]))
    return out


def struct_pack(vals):
    return array.array("h", vals).tobytes()


class Feeder:
    def __init__(self, cycle):
        self.frames = to_frames(cycle)
        self.stop_evt = threading.Event()
        self.t0 = None
        self.thread = threading.Thread(target=self._run, name="baseline-feeder", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_evt.set()
        self.thread.join(2)

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.t0 = time.monotonic()
        i = 0
        while not self.stop_evt.is_set():
            sock.sendto(self.frames[i % len(self.frames)], ("127.0.0.1", ts.UDP_PORT))
            i += 1
            delay = self.t0 + i * FRAME_SEC - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        sock.close()


class Reader:
    def __init__(self, stream):
        self.s = stream
        self.chunks = []
        self.stop_evt = threading.Event()
        self.thread = threading.Thread(target=self._run, name="baseline-reader", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_evt.set()
        self.thread.join(2)

    def _run(self):
        if self.s.pending:
            self.chunks.append((time.monotonic(), self.s.pending))
            self.s.pending = b""
        self.s.sock.settimeout(0.5)
        while not self.stop_evt.is_set():
            try:
                c = self.s.sock.recv(4096)
            except socket.timeout:
                continue
            if not c:
                break
            self.chunks.append((time.monotonic(), c))


def samples_of(chunks):
    raw = b"".join(c for _, c in chunks)
    raw = raw[: len(raw) - (len(raw) % 2)]
    a = array.array("h")
    a.frombytes(raw)
    return a


def goertzel_dbfs(x, hz):
    n = len(x)
    if n == 0:
        return -120.0
    k = int(round(n * hz / FS))
    w = 2.0 * math.pi * k / n
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for v in x:
        s0 = v + c * s1 - s2
        s2, s1 = s1, s0
    power = s1 * s1 + s2 * s2 - c * s1 * s2
    amp = 2.0 * math.sqrt(max(power, 0.0)) / n
    return 20.0 * math.log10(max(amp, 1e-9) / 32768.0)


def rms_dbfs(x):
    if not x:
        return -120.0
    return 20.0 * math.log10(max(math.sqrt(sum(v * v for v in x) / len(x)), 1e-9) / 32768.0)


def onset_latency(chunks, t_send, thr=0.1 * 32768):
    for t, c in chunks:
        if t < t_send:
            continue
        a = samples_of([(t, c)])
        for v in a:
            if abs(v) >= thr:
                return t - t_send
    return None


class TalkerBaseline(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        cls.node = ts.Node(max_listeners=3).start()
        cls.cookie = ts.login()

    @classmethod
    def tearDownClass(cls):
        cls.node.stop()
        out = {"node": "nodetalker", "version": os.path.basename(ts.NODE_FILE), "signals": cls.results}
        if BASELINE_OUT:
            with open(BASELINE_OUT, "w", encoding="utf-8") as fh:
                json.dump(out, fh, indent=2, sort_keys=True)

    def input_stats(self, name):
        x = array.array("h", signal_cycle(name))
        seg = x[FS * 1:]
        return {"input_rms_dbfs": round(rms_dbfs(seg), 2), "input_60hz_dbfs": round(goertzel_dbfs(seg, 60.0), 2),
                "input_1khz_dbfs": round(goertzel_dbfs(seg, 1000.0), 2)}

    def measure(self, name):
        cycle = signal_cycle(name)
        feeder = Feeder(cycle).start()
        time.sleep(0.5)
        stream = ts.Stream(self.cookie, fmt="s16")
        self.assertEqual(stream.status, 200)
        reader = Reader(stream).start()
        time.sleep(CYCLE_SEC * (CYCLES + WARM_CYCLES))
        reader.stop()
        feeder.stop()
        stream.close()
        return reader.chunks, feeder.t0

    def test_tone_level_and_latency(self):
        chunks, t0 = self.measure("tone")
        x = samples_of(chunks)
        self.assertGreater(len(x), FS * CYCLE_SEC * CYCLES * 0.8)
        seg = x[int(FS * 1.2):int(FS * 1.9)]
        level = goertzel_dbfs(seg, 1000.0)
        self.assertGreater(level, -30.0)
        lats = []
        for k in range(WARM_CYCLES, WARM_CYCLES + CYCLES):
            t_send = t0 + k * CYCLE_SEC + FS * 1.0 / FS
            lat = onset_latency(chunks, t_send)
            if lat is not None:
                lats.append(lat)
        self.assertTrue(lats, "no tone onset heard")
        TalkerBaseline.results["tone"] = {
            "tone_1khz_dbfs": round(level, 2),
            "input_1khz_dbfs": self.input_stats("tone")["input_1khz_dbfs"],
            "onset_latency_ms_median": round(sorted(lats)[len(lats) // 2] * 1000.0, 1),
        }

    def test_hum_is_reported_with_tone(self):
        chunks, t0 = self.measure("hum_tone")
        x = samples_of(chunks)
        self.assertGreater(len(x), FS * CYCLE_SEC * CYCLES * 0.8)
        seg = x[int(FS * 1.2):int(FS * 1.9)]
        hum = goertzel_dbfs(seg, 60.0)
        tone = goertzel_dbfs(seg, 1000.0)
        self.assertGreater(tone, -30.0)
        TalkerBaseline.results["hum_tone"] = {"tone_1khz_dbfs": round(tone, 2), "hum_60hz_dbfs": round(hum, 2),
                                              "input": self.input_stats("hum_tone")}

    def test_floor_on_hum_only_input(self):
        chunks, t0 = self.measure("hum_floor")
        x = samples_of(chunks)
        self.assertGreater(len(x), FS * CYCLE_SEC * CYCLES * 0.8)
        seg = x[FS * 3:]
        TalkerBaseline.results["hum_floor"] = {"rms_dbfs": round(rms_dbfs(seg), 2),
                                               "hum_60hz_dbfs": round(goertzel_dbfs(seg, 60.0), 2),
                                               "input": self.input_stats("hum_floor")}


if __name__ == "__main__":
    unittest.main(verbosity=2)
