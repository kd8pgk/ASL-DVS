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

FS = 8000
FRAME = 160
FRAME_BYTES = FRAME * 2
FRAME_SEC = 0.02
TX_PORT = 32018
TONE_HZ = 1000.0
TONE_AMP = 8000
TONE_FRAMES = 100


def tone_frame(start_index):
    return array.array("h", [round(TONE_AMP * math.sin(2 * math.pi * TONE_HZ * (start_index + i) / FS))
                             for i in range(FRAME)]).tobytes()


def parse_usrp(packet):
    if len(packet) < 32 or packet[:4] != b"USRP":
        return None
    keyup = packet[15] & 1 if len(packet) > 15 else 0
    return keyup, packet[32:]


class Capture:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", TX_PORT))
        self.sock.settimeout(0.2)
        self.packets = []
        self.stop_evt = threading.Event()
        self.thread = threading.Thread(target=self._run, name="tx-capture", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        while not self.stop_evt.is_set():
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            p = parse_usrp(data)
            if p is not None:
                self.packets.append((time.monotonic(), p[0], p[1]))

    def close(self):
        self.stop_evt.set()
        self.thread.join(2)
        self.sock.close()


def quarter_rms(payload, q):
    a = samples(payload)
    n = len(a) // 4
    part = a[q * n:(q + 1) * n]
    return math.sqrt(sum(v * v for v in part) / max(len(part), 1))


def samples(payload):
    a = array.array("h")
    a.frombytes(payload[: len(payload) - (len(payload) % 2)])
    return a


RPT_TEXT = """[general]

[50001](node-main)
rxchannel = USRP/127.0.0.1:34001:32001

; nodetalker: transmit node for Node Talker (remove it from the TX card)
[1921]
rxchannel = USRP/127.0.0.1:34018:32018
duplex = 0
hangtime = 0

[nodes]
1921 = radio@127.0.0.1/1921,NONE
"""


class TalkerTxBaseline(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        cls.node = ts.Node(max_listeners=3)
        with open(os.path.join(cls.node.dir, "nodetalker.conf"), "a", encoding="utf-8") as fh:
            fh.write("node = 50001\n")
        os.makedirs(os.path.join(cls.node.dir, "asterisk"), exist_ok=True)
        with open(os.path.join(cls.node.dir, "asterisk", "rpt_lstats_50001"), "w", encoding="utf-8") as fh:
            fh.write("1921 1 0 OUT 00:00:03\n")
        rpt = os.path.join(cls.node.dir, "rpt.conf")
        with open(rpt, "w", encoding="utf-8") as fh:
            fh.write(RPT_TEXT)
        cls._old_rpt = os.environ.get("NODETALKER_RPT_CONF")
        os.environ["NODETALKER_RPT_CONF"] = rpt
        cls.node.start()
        cls.cookie = ts.login()

    @classmethod
    def tearDownClass(cls):
        cls.node.stop()
        if cls._old_rpt is None:
            os.environ.pop("NODETALKER_RPT_CONF", None)
        else:
            os.environ["NODETALKER_RPT_CONF"] = cls._old_rpt
        out = {"node": "nodetalker", "version": os.path.basename(ts.NODE_FILE), "tx": cls.results}
        path = os.environ.get("NT_TX_BASELINE_OUT") or ""
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(out, fh, indent=2, sort_keys=True)

    def key_and_wait(self, ws):
        ws.send(1, b'{"op":"key"}')
        for _ in range(50):
            op, payload = ws.recv_frame()
            if op == 1:
                text = payload.decode("utf-8", "replace")
                if '"ev": "lock"' in text or '"ev":"lock"' in text:
                    continue
                return text
        raise AssertionError("no reply to key")

    def send_tone_and_release(self, pause_at=None):
        cap = Capture().start()
        ws = ts.talk_open(self.cookie)
        try:
            reply = self.key_and_wait(ws)
            self.assertIn('"keyed"', reply, reply)
            t0 = time.monotonic()
            for i in range(TONE_FRAMES):
                if pause_at is not None and i == pause_at:
                    time.sleep(0.4)
                    t0 = time.monotonic() - i * FRAME_SEC
                ws.send(2, tone_frame(i * FRAME))
                delay = t0 + (i + 1) * FRAME_SEC - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
            ws.send(1, b'{"op":"unkey"}')
            time.sleep(1.0)
            ws.sock.close()
        finally:
            cap.close()
        return cap.packets, None

    def test_tone_passes_at_unity_gain_and_unkey_sends_silence(self):
        pk, _ = self.send_tone_and_release()
        keyed = [p for p in pk if p[1] == 1]
        self.assertTrue(keyed, "no keyed packets")
        tail = [p for p in pk][-3:]
        self.assertTrue(all(p[1] == 0 for p in tail), "unkey did not send three unkeyed packets")
        audio = samples(b"".join(p[2] for p in pk if p[1] == 1))
        mid = audio[FRAME * 10:FRAME * 80]
        peak = max(abs(v) for v in mid)
        self.assertGreater(peak, 0.7 * TONE_AMP)
        self.assertLess(peak, 1.1 * TONE_AMP)
        TalkerTxBaseline.results["tone"] = {
            "keyed_packets": len(keyed),
            "unkey_packets": len(tail),
            "steady_peak_dbfs": round(20 * math.log10(peak / 32768.0), 2),
            "input_peak_dbfs": round(20 * math.log10(TONE_AMP / 32768.0), 2),
        }

    def test_mid_stream_pause_fades_out_and_back_in(self):
        pk, _ = self.send_tone_and_release(pause_at=40)
        frames = [p[2] for p in pk if p[1] == 1]
        self.assertTrue(frames)
        peaks = [max((abs(v) for v in samples(f)), default=0) for f in frames]
        gap = next((i for i in range(5, len(peaks)) if peaks[i] == 0 and peaks[i - 1] > 0), None)
        self.assertIsNotNone(gap, "no silent gap where the pause was")
        back = next((j for j in range(gap, len(peaks)) if peaks[j] > 0), None)
        self.assertIsNotNone(back, "the tone did not come back after the pause")
        before, after = frames[gap - 1], frames[back]
        out_ratio = quarter_rms(before, 0) / max(quarter_rms(before, 3), 1e-9)
        in_ratio = quarter_rms(after, 3) / max(quarter_rms(after, 0), 1e-9)
        self.assertGreater(out_ratio, 3.0, "the frame before the gap is not faded out")
        self.assertGreater(in_ratio, 3.0, "the frame after the gap is not faded in")
        steady = max(peaks[10:30])
        TalkerTxBaseline.results["pause"] = {
            "steady_peak_dbfs": round(20 * math.log10(steady / 32768.0), 2),
            "gap_frames": back - gap,
            "fade_out_first_to_last_quarter": round(out_ratio, 1),
            "fade_in_last_to_first_quarter": round(in_ratio, 1),
        }


if __name__ == "__main__":
    import unittest as u
    u.main(verbosity=2)
