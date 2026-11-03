import base64
import glob
import http.client
import json
import math
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE_FILE = sorted(glob.glob(os.path.join(ROOT, "nodetalker_v*.py")), key=lambda f: [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]])[-1]
STUB_BIN = os.path.join(ROOT, "ci", "fixtures", "servers", "bin")
PORT = int(os.environ.get("NT_TEST_PORT") or 18993)
UDP_PORT = int(os.environ.get("NT_TEST_UDP_PORT") or 16200)
PASSWORD = "stream-test-password"
FRAME_SEC = 0.02
FRAME_BYTES = 320
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SOAK_MIN = float(os.environ.get("NT_SOAK_MIN") or 0)

BOOT = '''
import importlib.util
import sys
path, password = sys.argv[1], sys.argv[2]
sys.argv = sys.argv[:1]
spec = importlib.util.spec_from_file_location("nodetalker_under_test", path)
mod = importlib.util.module_from_spec(spec)
sys.modules["nodetalker_under_test"] = mod
spec.loader.exec_module(mod)
mod._verify_root_password = lambda pw: bool(pw) and pw == password
sys.exit(mod.main())
'''


def http_req(method, path, body=None, headers=None, cookie="", timeout=10, xhr=True):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        h = dict(headers or {})
        data = None
        if cookie:
            h["Cookie"] = cookie
        if method == "POST":
            if xhr:
                h.setdefault("X-Requested-With", "XMLHttpRequest")
            h.setdefault("Content-Type", "application/json")
            data = json.dumps(body if body is not None else {})
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        conn.close()


def http_json(method, path, body=None, cookie="", headers=None):
    st, hd, raw = http_req(method, path, body=body, cookie=cookie, headers=headers)
    try:
        return st, hd, json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        return st, hd, {}


def login():
    st, hd, _ = http_json("POST", "/api/login", {"password": PASSWORD})
    if st != 200:
        raise RuntimeError(f"login failed: {st}")
    return hd["set-cookie"].split(";")[0]


def connect(timeout=10, rcvbuf=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if rcvbuf:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
    s.settimeout(timeout)
    s.connect(("127.0.0.1", PORT))
    return s


def read_head(s):
    buf = b""
    while b"\r\n\r\n" not in buf:
        c = s.recv(1)
        if not c:
            raise EOFError("closed before the headers ended")
        buf += c
        if len(buf) > 65536:
            raise ValueError("headers too long")
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    hd = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        hd[k.strip().lower()] = v.strip()
    return status, hd, rest


class Stream:
    def __init__(self, cookie, fmt="", rcvbuf=None, timeout=10):
        self.sock = connect(timeout, rcvbuf)
        q = f"?fmt={fmt}" if fmt else ""
        req = (f"GET /api/listen{q} HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\n"
               f"Cookie: {cookie}\r\nUser-Agent: nt-stream-test\r\n\r\n")
        self.sock.sendall(req.encode("ascii"))
        self.status, self.headers, self.pending = read_head(self.sock)

    def read(self, n=8192):
        if self.pending:
            out, self.pending = self.pending, b""
            return out
        return self.sock.recv(n)

    def collect(self, secs):
        end = time.monotonic() + secs
        got = len(self.pending)
        self.pending = b""
        while time.monotonic() < end:
            c = self.sock.recv(16384)
            if not c:
                break
            got += len(c)
        return got

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Feeder:
    def __init__(self, tone=False):
        if tone:
            samples = [int(8000 * math.sin(2 * math.pi * 1000 * i / 8000)) for i in range(FRAME_BYTES // 2)]
            self.frame = struct.pack(f"<{len(samples)}h", *samples)
        else:
            self.frame = bytes(FRAME_BYTES)
        self.stop_evt = threading.Event()
        self.thread = threading.Thread(target=self._run, name="test-feeder", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_evt.set()
        self.thread.join(2)

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t0 = time.monotonic()
        i = 0
        while not self.stop_evt.is_set():
            sock.sendto(self.frame, ("127.0.0.1", UDP_PORT))
            i += 1
            delay = t0 + i * FRAME_SEC - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        sock.close()


class WS:
    def __init__(self, sock, pending=b""):
        self.sock = sock
        self.buf = pending

    def _need(self, n):
        while len(self.buf) < n:
            c = self.sock.recv(65536)
            if not c:
                raise EOFError("closed")
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv_frame(self):
        b1, b2 = self._need(2)
        op = b1 & 0x0F
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._need(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._need(8))[0]
        return op, self._need(n)

    def send(self, op, payload=b"", mask=True, fin=True):
        b1 = (0x80 if fin else 0) | op
        n = len(payload)
        m = 0x80 if mask else 0
        if n < 126:
            hdr = bytes([b1, m | n])
        elif n < 65536:
            hdr = bytes([b1, m | 126]) + struct.pack(">H", n)
        else:
            hdr = bytes([b1, m | 127]) + struct.pack(">Q", n)
        if mask:
            key = os.urandom(4)
            body = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
            hdr += key
        else:
            body = payload
        self.sock.sendall(hdr + body)

    def close_code(self, secs):
        self.sock.settimeout(secs)
        try:
            while True:
                op, payload = self.recv_frame()
                if op == 8:
                    return struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 0
        except (EOFError, OSError):
            return None

    def closed_within(self, secs):
        self.sock.settimeout(secs)
        try:
            while True:
                if not self.sock.recv(4096):
                    return True
        except socket.timeout:
            return False
        except OSError:
            return True


def ws_handshake(cookie="", origin=None, upgrade=True, host=None):
    host = host or f"127.0.0.1:{PORT}"
    s = connect()
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    lines = ["GET /api/talk HTTP/1.1", f"Host: {host}"]
    if upgrade:
        lines += ["Upgrade: websocket", "Connection: Upgrade", f"Sec-WebSocket-Key: {key}",
                  "Sec-WebSocket-Version: 13"]
    if origin is not None:
        lines.append(f"Origin: {origin}")
    if cookie:
        lines.append(f"Cookie: {cookie}")
    s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
    status, hd, rest = read_head(s)
    return s, status, hd, key, rest


def talk_open(cookie):
    s, status, hd, key, rest = ws_handshake(cookie, origin=f"http://127.0.0.1:{PORT}")
    if status != 101:
        raise RuntimeError(f"talk handshake gave {status}")
    return WS(s, rest)


class Node:
    def __init__(self, max_listeners=3):
        self.dir = tempfile.mkdtemp(prefix="nt-stream-")
        with open(os.path.join(self.dir, "nodetalker.conf"), "w", encoding="utf-8") as f:
            f.write(f"[nodetalker]\nport = {PORT}\nudp_port = {UDP_PORT}\nhttps = false\n"
                    f"max_listeners = {max_listeners}\n")
        self.boot = os.path.join(self.dir, "boot.py")
        with open(self.boot, "w", encoding="utf-8") as f:
            f.write(BOOT)
        self.log_path = os.path.join(self.dir, "server.log")
        self.log = None
        self.proc = None

    def start(self):
        env = dict(os.environ)
        env.update(NODETALKER_CONFIG_DIR=self.dir, STUB_DIR=self.dir,
                   PATH=STUB_BIN + os.pathsep + os.environ.get("PATH", ""))
        self.log = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, self.boot, NODE_FILE, PASSWORD], cwd=ROOT, env=env,
                                     stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited at start; see {self.log_path}")
            try:
                if http_req("GET", "/api/health", timeout=2)[0] == 200:
                    return self
            except OSError:
                time.sleep(0.3)
        raise RuntimeError("server did not answer")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=10)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.log:
            self.log.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def fds(self):
        return len(os.listdir(f"/proc/{self.proc.pid}/fd"))

    def threads(self):
        return len(os.listdir(f"/proc/{self.proc.pid}/task"))

    def rss_kb(self):
        with open(f"/proc/{self.proc.pid}/status", encoding="ascii") as f:
            for ln in f:
                if ln.startswith("VmRSS:"):
                    return int(ln.split()[1])
        return 0


def open_slot_or_none(cookie):
    s = Stream(cookie, timeout=5)
    if s.status == 200:
        return s
    s.close()
    return None


class AuthAndEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = Node().start()
        cls.cookie = login()

    @classmethod
    def tearDownClass(cls):
        cls.node.stop()

    def test_listen_without_login_is_401(self):
        s = Stream("", timeout=5)
        self.assertEqual(s.status, 401)
        s.close()

    def test_wrong_password_is_401(self):
        st, _, body = http_json("POST", "/api/login", {"password": "not-the-password"})
        self.assertEqual(st, 401)
        self.assertFalse(body.get("ok"))

    def test_logout_revokes_the_session(self):
        cookie = login()
        st, _, _ = http_json("POST", "/api/logout", {}, cookie=cookie)
        self.assertEqual(st, 200)
        s = Stream(cookie, timeout=5)
        self.assertEqual(s.status, 401)
        s.close()

    def test_event_post_needs_login(self):
        st, _, _ = http_json("POST", "/api/listen/event", {"events": []})
        self.assertEqual(st, 401)

    def test_event_post_needs_the_xhr_header(self):
        st, _, body = http_req("POST", "/api/listen/event", body={"events": []}, cookie=self.cookie,
                               xhr=False)
        self.assertEqual(st, 403)

    def test_event_batch_is_capped_at_20(self):
        events = [{"action": "connect", "src": "user", "why": "button", "t": 0} for _ in range(25)]
        st, _, body = http_json("POST", "/api/listen/event", {"client": "android", "events": events},
                                cookie=self.cookie)
        self.assertEqual(st, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("n"), 20)

    def test_event_with_bad_shape_is_refused_not_crashed(self):
        st, _, body = http_json("POST", "/api/listen/event", {"events": "nope"}, cookie=self.cookie)
        self.assertEqual(st, 200, "the app keeps events until it gets a 200, so a bad batch must not be a 400")
        self.assertFalse(body.get("ok"))
        self.assertIn("message", body)
        st2, _, _ = http_json("GET", "/api/health")
        self.assertEqual(st2, 200)

    def test_event_skips_unknown_fields_and_keeps_the_good_ones(self):
        events = [{"action": "bogus", "src": "user"}, "junk", {"action": "disconnect", "src": "system",
                  "why": "not-a-reason"}]
        st, _, body = http_json("POST", "/api/listen/event", {"events": events}, cookie=self.cookie)
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("n"), 1)

    def test_health_still_answers_after_all_of_it(self):
        st, _, body = http_json("GET", "/api/health")
        self.assertEqual(st, 200)
        self.assertTrue(body.get("ok"))


class TalkHandshakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = Node().start()
        cls.cookie = login()

    @classmethod
    def tearDownClass(cls):
        cls.node.stop()

    def test_talk_without_login_is_401(self):
        s, status, _, _, _ = ws_handshake("", origin=f"http://127.0.0.1:{PORT}")
        s.close()
        self.assertEqual(status, 401)

    def test_talk_without_upgrade_is_400(self):
        s, status, _, _, _ = ws_handshake(self.cookie, origin=f"http://127.0.0.1:{PORT}", upgrade=False)
        s.close()
        self.assertEqual(status, 400)

    def test_talk_from_another_origin_is_403(self):
        s, status, _, _, _ = ws_handshake(self.cookie, origin="http://evil.example")
        s.close()
        self.assertEqual(status, 403)

    def test_talk_with_no_origin_is_403(self):
        s, status, _, _, _ = ws_handshake(self.cookie, origin=None)
        s.close()
        self.assertEqual(status, 403)

    def test_talk_accept_key_matches_rfc6455_example(self):
        sock = connect()
        req = (f"GET /api/talk HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
               f"Sec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1:{PORT}\r\n"
               f"Cookie: {self.cookie}\r\n\r\n")
        sock.sendall(req.encode("ascii"))
        status, hd, _ = read_head(sock)
        sock.close()
        self.assertEqual(status, 101)
        self.assertEqual(hd.get("sec-websocket-accept"), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_talk_answers_a_ping_with_a_pong(self):
        ws = talk_open(self.cookie)
        ws.send(9, b"abc")
        op, payload = ws.recv_frame()
        ws.sock.close()
        self.assertEqual(op, 10)
        self.assertEqual(payload, b"abc")

    def test_talk_takes_binary_audio_without_dropping(self):
        ws = talk_open(self.cookie)
        for _ in range(50):
            ws.send(2, bytes(FRAME_BYTES))
            time.sleep(FRAME_SEC)
        ws.send(9, b"still")
        op, payload = ws.recv_frame()
        ws.sock.close()
        self.assertEqual((op, payload), (10, b"still"))

    def test_talk_close_frame_ends_the_session(self):
        ws = talk_open(self.cookie)
        ws.send(8, b"")
        self.assertTrue(ws.closed_within(3))
        ws.sock.close()

    def test_unmasked_client_frame_closes_the_session(self):
        ws = talk_open(self.cookie)
        ws.send(2, bytes(FRAME_BYTES), mask=False)
        self.assertEqual(ws.close_code(3), 1002)
        ws.sock.close()

    def test_oversize_frame_is_refused_without_reading_it(self):
        ws = talk_open(self.cookie)
        ws.sock.sendall(bytes([0x82, 0x80 | 127]) + struct.pack(">Q", 65537) + os.urandom(4))
        self.assertEqual(ws.close_code(3), 1009)
        ws.sock.close()
        st, _, _ = http_json("GET", "/api/health")
        self.assertEqual(st, 200)

    def test_bad_data_opcode_does_not_take_the_server_down(self):
        ws = talk_open(self.cookie)
        ws.send(3, b"junk")
        ws.sock.close()
        st, _, _ = http_json("GET", "/api/health")
        self.assertEqual(st, 200)

    def test_listeners_and_talkers_do_not_block_each_other(self):
        ws = talk_open(self.cookie)
        s = Stream(self.cookie, timeout=5)
        self.assertEqual(s.status, 200)
        self.assertGreater(s.collect(1.0), 0)
        ws.send(9, b"both")
        op, payload = ws.recv_frame()
        ws.sock.close()
        s.close()
        self.assertEqual((op, payload), (10, b"both"))


class TalkIdleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = Node().start()
        cls.cookie = login()

    @classmethod
    def tearDownClass(cls):
        cls.node.stop()

    def test_idle_talk_survives_when_the_client_answers_pings(self):
        ws = talk_open(self.cookie)
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            ws.sock.settimeout(max(0.5, deadline - time.monotonic()))
            try:
                op, payload = ws.recv_frame()
            except socket.timeout:
                break
            if op == 9:
                ws.send(10, payload)
        ws.send(9, b"alive")
        ws.sock.settimeout(5)
        op, payload = ws.recv_frame()
        ws.sock.close()
        self.assertEqual((op, payload), (10, b"alive"))

    def test_idle_talk_without_pongs_is_dropped_by_the_node(self):
        ws = talk_open(self.cookie)
        start = time.monotonic()
        dropped = ws.closed_within(90)
        elapsed = time.monotonic() - start
        ws.sock.close()
        self.assertTrue(dropped)
        self.assertGreater(elapsed, 55)


class ListenStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = Node(max_listeners=3).start()
        cls.cookie = login()
        cls.feeder = Feeder(tone=True).start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.feeder.stop()
        cls.node.stop()

    def settle(self):
        time.sleep(0.5)

    def test_mulaw_headers(self):
        self.settle()
        s = Stream(self.cookie)
        try:
            self.assertEqual(s.status, 200)
            self.assertEqual(s.headers.get("x-audio-format"), "mulaw; rate=8000; channels=1")
            self.assertEqual(s.headers.get("connection"), "close")
        finally:
            s.close()

    def test_mulaw_rate_is_8000_bytes_per_second(self):
        self.settle()
        s = Stream(self.cookie)
        try:
            self.assertEqual(s.status, 200)
            got = s.collect(5)
        finally:
            s.close()
        self.assertGreater(got, 8000 * 5 * 0.85)
        self.assertLess(got, 8000 * 5 * 1.15)

    def test_s16_headers_and_rate(self):
        self.settle()
        s = Stream(self.cookie, fmt="s16")
        try:
            self.assertEqual(s.status, 200)
            self.assertEqual(s.headers.get("x-audio-format"), "s16le; rate=8000; channels=1")
            got = s.collect(3)
        finally:
            s.close()
        self.assertGreater(got, 16000 * 3 * 0.85)
        self.assertLess(got, 16000 * 3 * 1.15)

    def test_two_listeners_both_hear_the_audio(self):
        self.settle()
        a = Stream(self.cookie)
        b = Stream(self.cookie)
        try:
            ga = a.collect(3)
            gb = b.collect(3)
        finally:
            a.close()
            b.close()
        self.assertGreater(ga, 0)
        self.assertGreater(gb, 0)

    def test_slot_limit_gives_503_and_the_slots_come_back(self):
        self.settle()
        held = []
        try:
            held = [Stream(self.cookie) for _ in range(3)]
            self.assertTrue(all(s.status == 200 for s in held))
            s4 = Stream(self.cookie, timeout=5)
            try:
                self.assertEqual(s4.status, 503)
                body = s4.pending
                want = int(s4.headers.get("content-length", "0"))
                while len(body) < want:
                    c = s4.sock.recv(4096)
                    if not c:
                        break
                    body += c
            finally:
                s4.close()
            self.assertIn(b"listener slots", body)
            held[0].close()
            freed_at = time.monotonic()
            new = None
            while time.monotonic() - freed_at < 5 and new is None:
                new = open_slot_or_none(self.cookie)
                if new is None:
                    time.sleep(0.05)
            self.assertIsNotNone(new, "a closed listener did not free its slot within 5 s")
            new.close()
        finally:
            for s in held:
                s.close()

    def test_a_clean_disconnect_frees_its_slot_quickly(self):
        self.settle()
        held = []
        try:
            held = [Stream(self.cookie) for _ in range(3)]
            held[0].read(4096)
            held[0].close()
            t0 = time.monotonic()
            new = None
            while time.monotonic() - t0 < 2 and new is None:
                new = open_slot_or_none(self.cookie)
                if new is None:
                    time.sleep(0.005)
            self.assertIsNotNone(new)
            new.close()
            self.assertLess(time.monotonic() - t0, 1.0)
        finally:
            for s in held:
                s.close()

    def test_200_connect_and_disconnect_cycles_do_not_leak(self):
        self.settle()
        fd0, th0 = self.node.fds(), self.node.threads()
        busy = 0
        for _ in range(200):
            s = None
            for attempt in range(40):
                s = Stream(self.cookie)
                if s.status == 200:
                    break
                s.close()
                s = None
                busy += 1
                time.sleep(0.02)
            self.assertIsNotNone(s, "no slot within 0.8 s during the churn")
            try:
                s.read(4096)
            finally:
                s.close()
        time.sleep(1)
        self.assertLessEqual(self.node.fds(), fd0 + 3)
        self.assertLessEqual(self.node.threads(), th0 + 3)
        held = []
        try:
            held = [Stream(self.cookie) for _ in range(3)]
            self.assertTrue(all(s.status == 200 for s in held), "slots leaked during the churn")
        finally:
            for s in held:
                s.close()

class StalledListenerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = Node(max_listeners=3).start()
        cls.cookie = login()
        cls.feeder = Feeder(tone=True).start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.feeder.stop()
        cls.node.stop()

    def settle(self):
        time.sleep(0.5)

    def test_a_stalled_listener_is_dropped_within_60_seconds(self):
        self.settle()
        stop = threading.Event()
        drainers = []
        stalled = None
        got = None
        try:
            stalled = Stream(self.cookie, rcvbuf=4096, timeout=5)
            self.assertEqual(stalled.status, 200)

            def drain(s):
                s.sock.settimeout(1)
                while not stop.is_set():
                    try:
                        if not s.sock.recv(16384):
                            return
                    except socket.timeout:
                        continue
                    except OSError:
                        return

            for _ in range(2):
                s = Stream(self.cookie)
                t = threading.Thread(target=drain, args=(s,), daemon=True)
                t.start()
                drainers.append((s, t))
            started = time.monotonic()
            while time.monotonic() - started < 60 and got is None:
                got = open_slot_or_none(self.cookie)
                if got is None:
                    time.sleep(1)
            self.assertIsNotNone(got, "a stalled listener held its slot for 60 s")
        finally:
            stop.set()
            for s, t in drainers:
                t.join(2)
                s.close()
            if got is not None:
                got.close()
            if stalled is not None:
                stalled.close()



class ListenSilenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = Node().start()
        cls.cookie = login()

    @classmethod
    def tearDownClass(cls):
        cls.node.stop()

    def test_no_node_audio_still_streams_silence(self):
        s = Stream(self.cookie)
        self.assertEqual(s.status, 200)
        gaps = []
        got = 0
        last = time.monotonic()
        end = last + 12
        while time.monotonic() < end:
            c = s.sock.recv(8192)
            now = time.monotonic()
            if not c:
                self.fail("stream closed with no node audio")
            gaps.append(now - last)
            last = now
            got += len(c)
        s.close()
        self.assertLess(max(gaps), 1.0, f"stream went quiet for {max(gaps):.2f} s")
        self.assertGreater(got, 8000 * 12 * 0.85)

    def test_silent_node_audio_never_stalls_the_stream(self):
        feeder = Feeder(tone=False).start()
        try:
            time.sleep(0.5)
            s = Stream(self.cookie)
            self.assertEqual(s.status, 200)
            gaps = []
            last = time.monotonic()
            end = last + 20
            while time.monotonic() < end:
                c = s.sock.recv(8192)
                now = time.monotonic()
                if not c:
                    self.fail("stream closed while the node was sending silence")
                gaps.append(now - last)
                last = now
            s.close()
            self.assertLess(max(gaps), 1.0, f"stream went quiet for {max(gaps):.2f} s")
        finally:
            feeder.stop()


@unittest.skipUnless(SOAK_MIN > 0, "set NT_SOAK_MIN=<minutes> to run the soak")
class SoakTests(unittest.TestCase):
    def test_soak(self):
        node = Node(max_listeners=4).start()
        cookie = login()
        feeder = Feeder(tone=True).start()
        try:
            time.sleep(1)
            steady = [Stream(cookie) for _ in range(3)]
            stats = [{"got": 0, "max_gap": 0.0, "eof": False} for _ in steady]
            stop = threading.Event()

            def reader(i, s):
                s.sock.settimeout(5)
                last = time.monotonic()
                while not stop.is_set():
                    try:
                        c = s.sock.recv(16384)
                    except socket.timeout:
                        stats[i]["max_gap"] = max(stats[i]["max_gap"], time.monotonic() - last)
                        stats[i]["eof"] = True
                        return
                    now = time.monotonic()
                    if not c:
                        stats[i]["eof"] = True
                        return
                    stats[i]["max_gap"] = max(stats[i]["max_gap"], now - last)
                    stats[i]["got"] += len(c)
                    last = now

            threads = [threading.Thread(target=reader, args=(i, s), daemon=True) for i, s in enumerate(steady)]
            for t in threads:
                t.start()
            fd0, th0, rss0 = node.fds(), node.threads(), node.rss_kb()
            churn_ok = churn_fail = 0
            end = time.monotonic() + SOAK_MIN * 60
            next_sample = time.monotonic() + 30
            samples = []
            while time.monotonic() < end:
                s = open_slot_or_none(cookie)
                if s is None:
                    churn_fail += 1
                else:
                    churn_ok += 1
                    time.sleep(1)
                    s.close()
                time.sleep(4)
                if time.monotonic() >= next_sample:
                    samples.append((round(time.monotonic() - (end - SOAK_MIN * 60)), node.fds(),
                                    node.threads(), node.rss_kb()))
                    next_sample += 30
            stop.set()
            for t in threads:
                t.join(3)
            print(f"\nSOAK {SOAK_MIN} min: churn ok {churn_ok}, refused {churn_fail}")
            print(f"SOAK fds {fd0} -> {node.fds()}, threads {th0} -> {node.threads()}, "
                  f"rss {rss0} -> {node.rss_kb()} kB")
            for row in samples:
                print(f"SOAK t={row[0]}s fds={row[1]} threads={row[2]} rss={row[3]}kB")
            for i, st in enumerate(stats):
                print(f"SOAK listener {i}: bytes {st['got']}, max gap {st['max_gap']:.2f} s, eof {st['eof']}")
            for s in steady:
                s.close()
            self.assertFalse(any(st["eof"] for st in stats), "a steady listener was dropped")
            self.assertTrue(all(st["max_gap"] < 1.0 for st in stats), "a steady listener had a gap of 1 s or more")
            self.assertGreater(churn_ok, 0, "the churn never got a slot")
            self.assertLessEqual(node.fds(), fd0 + 5)
            self.assertLessEqual(node.threads(), th0 + 5)
            self.assertLess(node.rss_kb() - rss0, 20000)
        finally:
            feeder.stop()
            node.stop()


if __name__ == "__main__":
    unittest.main()
