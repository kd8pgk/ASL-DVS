import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nt_txrec_")
os.environ.setdefault("NODETALKER_CONFIG_DIR", os.path.join(WORK, "nt"))
os.environ.setdefault("NODETALKER_SUITELOG", os.path.join(WORK, "nt_suitelog.jsonl"))
os.environ.setdefault("NODETALKER_SUITELOG_FLAG", os.path.join(WORK, "nt_suitelog.on"))
os.environ.setdefault("NODERECORDER_CONFIG_DIR", os.path.join(WORK, "nr"))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:4]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


def load(name, pattern):
    spec = importlib.util.spec_from_file_location(name, newest(pattern))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


NT = load("nt_txrec_nodetalker", "nodetalker_v[0-9]*.py")
NR = load("nt_txrec_noderecorder", "noderecorder_v[0-9]*.py")


class FakeSocket:
    def __init__(self, fail_ports=()):
        self.sent = []
        self.fail_ports = set(fail_ports)

    def sendto(self, data, dest):
        if dest[1] in self.fail_ports:
            raise ConnectionRefusedError("nothing listens there")
        self.sent.append((data, dest))


class TxToRecorder(unittest.TestCase):
    def talker(self, **kw):
        t = NT.Talker()
        t.sock = FakeSocket(**kw)
        return t

    def test_every_transmit_packet_goes_to_asterisk_and_to_the_recorder(self):
        t = self.talker()
        pcm = bytes(range(256)) * 1 + bytes(64)
        t._packet(pcm, True)
        dests = [d for _p, d in t.sock.sent]
        self.assertEqual(dests, [("127.0.0.1", NT.TX_USRP_SEND), ("127.0.0.1", NT.RECORDER_FWD_PORT)])
        self.assertEqual(t.sock.sent[0][0], t.sock.sent[1][0])
        self.assertEqual(t.sock.sent[0][0][:4], b"USRP")
        self.assertEqual(t.sock.sent[0][0][NT.USRP_HEADER.size:], pcm)

    def test_the_recorder_reads_the_forwarded_packet_as_audio(self):
        t = self.talker()
        frame = bytes([1, 0, 2, 0]) * 80
        t._packet(frame, True)
        pcm, keyed = NR.usrp_payload(t.sock.sent[1][0])
        self.assertEqual(pcm, frame)
        self.assertTrue(keyed)

    def test_the_unkey_silence_is_forwarded_too_and_reads_as_unkeyed(self):
        t = self.talker()
        t._packet(NT.PCM_SILENCE, False)
        pcm, keyed = NR.usrp_payload(t.sock.sent[1][0])
        self.assertEqual(pcm, NT.PCM_SILENCE[:len(pcm)])
        self.assertFalse(keyed)

    def test_the_sequence_number_goes_up_by_one_and_is_the_same_in_both_copies(self):
        t = self.talker()
        t._packet(NT.PCM_SILENCE, True)
        t._packet(NT.PCM_SILENCE, True)
        seqs = [NT.USRP_HEADER.unpack_from(p)[1] for p, _d in t.sock.sent]
        self.assertEqual(seqs, [1, 1, 2, 2])

    def test_a_recorder_that_is_not_listening_never_stops_the_transmit(self):
        t = self.talker(fail_ports=(NT.RECORDER_FWD_PORT,))
        t._packet(NT.PCM_SILENCE, True)
        self.assertEqual([d for _p, d in t.sock.sent], [("127.0.0.1", NT.TX_USRP_SEND)])

    def test_asterisk_being_unreachable_still_forwards_to_the_recorder(self):
        t = self.talker(fail_ports=(NT.TX_USRP_SEND,))
        t._packet(NT.PCM_SILENCE, True)
        self.assertEqual([d for _p, d in t.sock.sent], [("127.0.0.1", NT.RECORDER_FWD_PORT)])

    def test_the_port_is_the_one_node_recorder_listens_on(self):
        self.assertEqual(NT.RECORDER_FWD_PORT, NR.FWD_PORT)


if __name__ == "__main__":
    unittest.main()
