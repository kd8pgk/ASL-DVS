import http.client
import http.server
import importlib.util
import io
import os
import socket
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("confio_under_test", os.path.join(ROOT, "shared", "confio.py"))
cf = importlib.util.module_from_spec(spec)
sys.modules["confio_under_test"] = cf
spec.loader.exec_module(cf)

LSTATS = ["RptNbr   Peer   Dir   Time  State", "1900  127.0.0.1  0  OUT  00:00:04  ESTABLISHED"]


class FakeAmi(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.seen = []
        self.follows = False
        self.refuse = False
        super().__init__(("127.0.0.1", 0), FakeAmiHandler)


class FakeAmiHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"Asterisk Call Manager/11.0.0\r\n")
        while True:
            block = []
            while True:
                raw = self.rfile.readline()
                if not raw:
                    return
                line = raw.decode().rstrip("\r\n")
                if not line:
                    break
                block.append(line)
            msg = dict(x.split(": ", 1) for x in block if ": " in x)
            self.server.seen.append(msg)
            aid = msg.get("ActionID", "")
            if msg.get("Action") == "Login":
                body = ["Response: " + ("Error" if self.server.refuse else "Success"), "ActionID: " + aid]
            elif msg.get("Action") == "Command":
                if self.server.follows:
                    body = ["Response: Follows", "Privilege: Command", "ActionID: " + aid] + LSTATS + ["--END COMMAND--"]
                else:
                    body = ["Response: Success", "ActionID: " + aid, "Message: Command output follows"] + ["Output: " + x for x in LSTATS]
            else:
                body = ["Response: Error", "ActionID: " + aid]
            self.wfile.write(("\r\n".join(body) + "\r\n\r\n").encode())


class Ami(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ami = FakeAmi()
        threading.Thread(target=self.ami.serve_forever, daemon=True).start()
        self.addCleanup(self.ami.server_close)
        self.addCleanup(self.ami.shutdown)
        self.conf = os.path.join(self.tmp.name, "manager.conf")
        with open(self.conf, "w") as f:
            f.write("[general]\nenabled = yes\n[admin]\nsecret = pw\n")
        self.cmd = cf.AmiCmd(self.conf, port=self.ami.server_address[1])

    def logins(self):
        return sum(1 for m in self.ami.seen if m.get("Action") == "Login")

    def test_message_and_reply_round_trip(self):
        self.assertEqual(cf.ami_msg(Action="Ping", ActionID="a"), b"Action: Ping\r\nActionID: a\r\n\r\n")
        raw = b"Response: Success\r\nActionID: b\r\n\r\nResponse: Success\r\nActionID: a\r\n\r\n"
        got = cf.ami_read_many(io.BytesIO(raw), ["a", "b"])
        self.assertEqual(set(got), {"a", "b"})
        self.assertIn("ActionID: a", cf.ami_read_for(io.BytesIO(raw), "a"))

    def test_a_reply_that_never_ends_is_refused(self):
        with self.assertRaises(OSError):
            cf.ami_read(io.BytesIO(b"Response: Success\r\n" + b"X: " + b"a" * 100 + b"\r\n"), max_bytes=50)

    def test_one_login_serves_many_commands(self):
        for _ in range(3):
            ok, out = self.cmd.run("rpt lstats 1")
            self.assertTrue(ok)
            self.assertIn("1900", out)
        self.assertEqual(self.logins(), 1)

    def test_the_older_follows_reply_is_read_too(self):
        self.ami.follows = True
        ok, out = self.cmd.run("rpt lstats 1")
        self.assertEqual((ok, out.splitlines()), (True, LSTATS))

    def test_a_dropped_connection_is_replaced_quietly(self):
        self.cmd.run("rpt lstats 1")
        self.cmd.sock.shutdown(socket.SHUT_RDWR)
        self.assertTrue(self.cmd.run("rpt lstats 1")[0])
        self.assertEqual(self.logins(), 2)

    def test_an_idle_connection_is_closed_and_reopened(self):
        self.cmd.idle_sec = 0.0
        self.cmd.run("rpt lstats 1")
        time.sleep(0.01)
        self.cmd.run("rpt lstats 1")
        self.assertEqual(self.logins(), 2)

    def test_a_refused_login_uses_the_fallback_and_is_not_retried_at_once(self):
        self.ami.refuse = True
        fallback = mock.Mock(return_value=(True, "cli"))
        for _ in range(2):
            self.assertEqual(cf.ami_or_cli(self.cmd, "rpt lstats 1", 3, fallback), (True, "cli"))
        self.assertEqual(fallback.call_count, 2)
        self.assertEqual(self.logins(), 1)

    def test_no_login_in_the_file_uses_the_fallback(self):
        with open(self.conf, "w") as f:
            f.write("[general]\nenabled = yes\n")
        fallback = mock.Mock(return_value=(True, "cli"))
        self.assertEqual(cf.ami_or_cli(self.cmd, "x", 3, fallback), (True, "cli"))
        self.assertEqual(self.ami.seen, [])

    def test_the_manager_wins_when_it_answers(self):
        fallback = mock.Mock(side_effect=AssertionError("no process"))
        self.assertTrue(cf.ami_or_cli(self.cmd, "rpt lstats 1", 3, fallback)[0])


class WarmLoop(unittest.TestCase):
    def test_it_works_while_asked_rests_when_not_and_wakes_on_a_new_ask(self):
        calls = []
        w = cf.Warm(lambda: calls.append(1), every=0.05, idle=0.5)
        th = threading.Thread(target=w.loop, daemon=True)
        th.start()
        self.assertEqual(calls, [])
        w.asked()
        end = time.time() + 5
        while time.time() < end and len(calls) < 3:
            time.sleep(0.02)
        self.assertGreaterEqual(len(calls), 3)
        time.sleep(0.8)
        n = len(calls)
        time.sleep(0.4)
        self.assertEqual(len(calls), n)
        w.asked()
        end = time.time() + 5
        while time.time() < end and len(calls) == n:
            time.sleep(0.02)
        self.assertGreater(len(calls), n)
        w.quit = True
        w.event.set()
        th.join(3)

    def test_a_failing_pass_is_logged_and_the_loop_goes_on(self):
        logs = []
        n = []

        def work():
            n.append(1)
            raise RuntimeError("boom")
        w = cf.Warm(work, every=0.02, idle=5)
        w.asked()
        th = threading.Thread(target=w.loop, args=(lambda m, lv: logs.append(m),), daemon=True)
        th.start()
        end = time.time() + 5
        while time.time() < end and len(n) < 3:
            time.sleep(0.02)
        w.quit = True
        w.event.set()
        th.join(3)
        self.assertGreaterEqual(len(n), 3)
        self.assertIn("RuntimeError", logs[0])

    def test_an_older_answer_is_taken_only_by_a_fast_read_while_the_loop_runs(self):
        w = cf.Warm(lambda: None, stale=8.0)
        stamp = time.monotonic() - 3
        w.on = True
        self.assertFalse(w.stale_ok(stamp))
        self.assertTrue(w.fast(lambda: w.stale_ok(stamp)))
        self.assertFalse(w.fast(lambda: w.stale_ok(time.monotonic() - 9)))
        self.assertFalse(w.stale_ok(stamp))
        w.on = False
        self.assertFalse(w.fast(lambda: w.stale_ok(stamp)))

    def test_a_fast_read_that_raises_still_ends_the_fast_mode(self):
        w = cf.Warm(lambda: None)
        w.on = True
        with self.assertRaises(ValueError):
            w.fast(lambda: (_ for _ in ()).throw(ValueError("x")))
        self.assertFalse(w.stale_ok(time.monotonic()))


class Caches(unittest.TestCase):
    def test_text_is_parsed_again_only_when_it_changes(self):
        cache = ["", None]
        parse = mock.Mock(side_effect=lambda t: t.upper())
        self.assertEqual(cf.text_cached(cache, "a", parse), "A")
        self.assertEqual(cf.text_cached(cache, "a", parse), "A")
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(cf.text_cached(cache, "b", parse), "B")
        self.assertEqual(parse.call_count, 2)

    def test_a_log_tail_is_read_again_only_when_the_file_changes(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "log")
        with open(path, "w") as f:
            f.write("one\ntwo\n")
        cache = [None, None]
        parse = mock.Mock(side_effect=lambda lines: list(lines))
        self.assertEqual(cf.tail_cached(cache, path, 1000, parse), ["one", "two"])
        cf.tail_cached(cache, path, 1000, parse)
        self.assertEqual(parse.call_count, 1)
        with open(path, "a") as f:
            f.write("three\n")
        self.assertEqual(cf.tail_cached(cache, path, 1000, parse)[-1], "three")
        self.assertEqual(parse.call_count, 2)
        self.assertEqual(cf.tail_cached([None, None], path, 6, parse), ["three"])

    def test_a_missing_file_raises_for_the_caller_to_handle(self):
        with self.assertRaises(OSError):
            cf.tail_cached([None, None], "/nonexistent/log", 10, list)


class Tags(unittest.TestCase):
    def test_tag_and_match(self):
        tag = cf.etag_of(b"abc")
        self.assertTrue(tag.startswith('W/"'))
        self.assertEqual(tag, cf.etag_of(b"abc"))
        self.assertNotEqual(tag, cf.etag_of(b"abd"))
        self.assertTrue(cf.etag_match(tag, tag))
        self.assertTrue(cf.etag_match("*", tag))
        self.assertTrue(cf.etag_match('"other", ' + tag[2:], tag))
        self.assertFalse(cf.etag_match('"other"', tag))
        self.assertFalse(cf.etag_match("", tag))

    def test_a_tag_can_ignore_ticking_keys(self):
        a = cf.etag_stable({"a": 1, "uptime": 5}, ("uptime",))
        b = cf.etag_stable({"a": 1, "uptime": 6}, ("uptime",))
        c = cf.etag_stable({"a": 2, "uptime": 5}, ("uptime",))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class WorkHeader(unittest.TestCase):
    def test_a_get_reply_says_how_long_the_server_worked(self):
        @cf.with_work_ms
        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                time.sleep(0.05)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        self.addCleanup(c.close)
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        self.assertGreaterEqual(int(r.getheader("X-Work-Ms")), 40)
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        self.assertEqual(len(r.msg.get_all("X-Work-Ms")), 1)
        c.request("POST", "/", body=b"x")
        r = c.getresponse()
        r.read()
        self.assertIsNone(r.getheader("X-Work-Ms"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
