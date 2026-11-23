import glob
import gzip
import http.client
import importlib.util
import json
import os
import re
import socket
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nt_speed_")
os.environ["NODETALKER_SUITELOG"] = os.path.join(WORK, "suitelog.jsonl")
os.environ["NODETALKER_SUITELOG_FLAG"] = os.path.join(WORK, "suitelog.on")
os.environ["NODETALKER_CONFIG_DIR"] = os.path.join(WORK, "nt")


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


PATH = newest("nodetalker_v[0-9]*.py")
spec = importlib.util.spec_from_file_location("nt_speed_under_test", PATH)
nt = importlib.util.module_from_spec(spec)
sys.modules["nt_speed_under_test"] = nt
spec.loader.exec_module(nt)

LSTATS = ["RptNbr   Peer   Dir   Time  State", "1900  127.0.0.1  0  OUT  00:00:04  ESTABLISHED"]


class FakeAmi(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.seen = []
        self.output = list(LSTATS)
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
                ok = not self.server.refuse
                body = ["Response: " + ("Success" if ok else "Error"), "ActionID: " + aid]
            elif msg.get("Action") == "Command":
                if self.server.follows:
                    body = ["Response: Follows", "Privilege: Command", "ActionID: " + aid] + self.server.output + ["--END COMMAND--"]
                else:
                    body = ["Response: Success", "ActionID: " + aid, "Message: Command output follows"] + \
                        ["Output: " + x for x in self.server.output]
            else:
                body = ["Response: Error", "ActionID: " + aid]
            self.wfile.write(("\r\n".join(body) + "\r\n\r\n").encode())


class AmiCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ami = FakeAmi()
        threading.Thread(target=self.ami.serve_forever, daemon=True).start()
        self.addCleanup(self.ami.server_close)
        self.addCleanup(self.ami.shutdown)
        conf = os.path.join(self.tmp.name, "manager.conf")
        with open(conf, "w") as f:
            f.write("[general]\nenabled = yes\n[admin]\nsecret = pw\n")
        self.saved = (nt.AMI_CONF, nt.AMI_PORT, nt.AMICMD)
        nt.AMI_CONF, nt.AMI_PORT = conf, self.ami.server_address[1]
        nt.AMICMD = nt.AmiCmd(conf, port=nt.AMI_PORT)
        self.addCleanup(lambda: (setattr(nt, "AMI_CONF", self.saved[0]), setattr(nt, "AMI_PORT", self.saved[1]),
                                 setattr(nt, "AMICMD", self.saved[2])))

    def logins(self):
        return sum(1 for m in self.ami.seen if m.get("Action") == "Login")

    def test_a_command_goes_over_one_kept_login(self):
        for _ in range(3):
            ok, out = nt.AMICMD.run("rpt lstats 1")
            self.assertTrue(ok)
            self.assertIn("1900", out)
        self.assertEqual(self.logins(), 1)
        self.assertEqual(sum(1 for m in self.ami.seen if m.get("Action") == "Command"), 3)

    def test_the_older_follows_reply_is_read_too(self):
        self.ami.follows = True
        ok, out = nt.AMICMD.run("rpt lstats 1")
        self.assertTrue(ok)
        self.assertEqual(out.splitlines(), LSTATS)

    def test_links_are_read_through_the_manager_not_a_process(self):
        nt._lstats_invalidate()
        with mock.patch.object(nt, "ast_cli", side_effect=AssertionError("no process")):
            ok, links = nt.rpt_links("1", max_age=0)
        self.assertTrue(ok)
        self.assertEqual(links, [{"node": "1900", "dir": "OUT", "time": "00:00:04", "state": "ESTABLISHED"}])

    def test_a_dropped_connection_is_replaced_quietly(self):
        nt.AMICMD.run("rpt lstats 1")
        nt.AMICMD.sock.shutdown(socket.SHUT_RDWR)
        ok, _ = nt.AMICMD.run("rpt lstats 1")
        self.assertTrue(ok)
        self.assertEqual(self.logins(), 2)

    def test_a_refused_login_falls_back_to_the_command_line_and_is_not_retried_at_once(self):
        self.ami.refuse = True
        with mock.patch.object(nt, "ast_cli", return_value=(True, "\n".join(LSTATS))) as cli:
            self.assertEqual(nt.ast_cli_fast("rpt lstats 1")[0], True)
            self.assertEqual(nt.ast_cli_fast("rpt lstats 1")[0], True)
        self.assertEqual(cli.call_count, 2)
        self.assertEqual(self.logins(), 1)

    def test_no_manager_login_means_the_command_line(self):
        with open(nt.AMI_CONF, "w") as f:
            f.write("[general]\nenabled = yes\n")
        with mock.patch.object(nt, "ast_cli", return_value=(True, "x")) as cli:
            self.assertEqual(nt.ast_cli_fast("rpt lstats 1"), (True, "x"))
        cli.assert_called_once()
        self.assertEqual(self.ami.seen, [])

    def test_an_idle_connection_is_not_kept_for_ever(self):
        nt.AMICMD.run("rpt lstats 1")
        nt.AMICMD.idle_sec = 0.0
        time.sleep(0.01)
        nt.AMICMD.run("rpt lstats 1")
        self.assertEqual(self.logins(), 2)


class FastReads(unittest.TestCase):
    def setUp(self):
        self.saved = (nt.WARM.on, dict(nt._lstats_cache), dict(nt._recorder_cache))
        self.addCleanup(self.restore)

    def restore(self):
        nt.WARM.on = self.saved[0]
        nt._lstats_cache.clear()
        nt._lstats_cache.update(self.saved[1])
        nt._recorder_cache.clear()
        nt._recorder_cache.update(self.saved[2])
        nt.WARM.local.fast = False

    def test_the_status_request_does_not_start_a_process_for_a_slightly_old_link_list(self):
        nt.WARM.on = True
        nt._lstats_cache.update(t=time.monotonic() - 4.0, node="1", ok=True, links=[{"node": "9"}])
        with mock.patch.object(nt, "ast_cli_fast", side_effect=AssertionError("must not run")):
            self.assertEqual(nt.WARM.fast(nt.rpt_links, "1"), (True, [{"node": "9"}]))
        with mock.patch.object(nt, "ast_cli_fast", return_value=(True, "")) as cli:
            self.assertEqual(nt.rpt_links("1"), (True, []))
        cli.assert_called_once()

    def test_an_action_still_gets_a_fresh_read(self):
        nt.WARM.on = True
        nt._lstats_cache.update(t=time.monotonic(), node="1", ok=True, links=[{"node": "9"}])
        nt._lstats_invalidate()
        with mock.patch.object(nt, "ast_cli_fast", return_value=(True, "")) as cli:
            nt.WARM.fast(nt.rpt_links, "1")
        cli.assert_called_once()

    def test_the_recorder_is_not_asked_again_on_the_request_path(self):
        nt.WARM.on = True
        nt._recorder_cache.update(t=time.monotonic() - 4.0, v={"state": "x"}, info=None)
        with mock.patch.object(nt.urllib.request, "urlopen", side_effect=AssertionError("must not run")):
            self.assertEqual(nt.WARM.fast(nt.recorder_busy), {"state": "x"})

    def test_an_action_wakes_the_refresher(self):
        nt.WARM.event.clear()
        nt._lstats_invalidate()
        self.assertTrue(nt.WARM.event.is_set())

    def test_the_rpt_conf_parse_is_kept_while_the_text_is_the_same(self):
        path = os.path.join(WORK, "rpt.conf")
        with open(path, "w") as f:
            f.write("[1]\nrxchannel = x\n")
        old = nt.RPT_CONF
        nt.RPT_CONF = path
        self.addCleanup(setattr, nt, "RPT_CONF", old)
        with mock.patch.object(nt, "parse_rpt", wraps=nt.parse_rpt) as parse:
            nt._rpt_parse_cache[:] = ["", None]
            a = nt.read_rpt(shared=True)
            b = nt.read_rpt(shared=True)
            self.assertIs(a, b)
            self.assertEqual(parse.call_count, 1)
            nt.read_rpt()
            self.assertEqual(parse.call_count, 2)
            with open(path, "a") as f:
                f.write("[2]\n")
            nt.read_rpt(shared=True)
            self.assertEqual(parse.call_count, 3)


class Served(unittest.TestCase):
    uptime = [100]

    @classmethod
    def setUpClass(cls):
        def fake_status(full):
            return {"ok": True, "node": "1", "uptime": cls.uptime[0], "last_rx_age": 3.4, "listener_list": [{"ip": "x", "secs": cls.uptime[0]}],
                    "peak_db": -90.0}
        cls.patches = [mock.patch.object(nt, "_check_session", lambda token: True),
                       mock.patch.object(nt, "_cfg_get", lambda key: True if key == "allow_wan" else None),
                       mock.patch.object(nt, "build_status", fake_status)]
        for p in cls.patches:
            p.start()
        cls.srv = nt.Server(("127.0.0.1", 0), nt.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for p in cls.patches:
            p.stop()

    def get(self, path, headers=None, conn=None):
        c = conn
        if c is None:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
            self.addCleanup(c.close)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        return r, r.read(), c


class StatusReply(Served):
    def test_a_ticking_clock_does_not_change_the_tag(self):
        r, body, c = self.get("/api/status")
        tag = r.getheader("ETag")
        self.assertTrue(tag)
        self.assertEqual(json.loads(body)["uptime"], 100)
        Served.uptime[0] = 101
        r2, body2, _ = self.get("/api/status", {"If-None-Match": tag}, conn=c)
        self.assertEqual((r2.status, body2), (304, b""))
        self.assertEqual(json.loads(r2.getheader("X-Volatile"))["uptime"], 101)
        self.assertEqual(r2.getheader("ETag"), tag)

    def test_a_real_change_gets_a_new_tag_and_the_full_body_still_has_every_field(self):
        tag = self.get("/api/status")[0].getheader("ETag")
        with mock.patch.object(nt, "build_status", lambda full: {"ok": True, "node": "2", "uptime": 5, "last_rx_age": None,
                                                                 "listener_list": [], "peak_db": -90.0}):
            r, body, _ = self.get("/api/status", {"If-None-Match": tag})
        self.assertEqual(r.status, 200)
        self.assertNotEqual(r.getheader("ETag"), tag)
        d = json.loads(body)
        for key in ("uptime", "last_rx_age", "listener_list"):
            self.assertIn(key, d)

    def test_the_reply_says_how_long_the_server_worked(self):
        r, _, _ = self.get("/api/status")
        self.assertRegex(r.getheader("X-Work-Ms"), r"^\d+$")

    def test_the_status_and_whoami_keep_the_refresher_awake(self):
        nt.WARM.t = -1e9
        self.get("/api/status")
        self.assertLess(time.monotonic() - nt.WARM.t, 5)
        nt.WARM.t = -1e9
        self.get("/api/whoami")
        self.assertLess(time.monotonic() - nt.WARM.t, 5)


class PageReply(Served):
    def test_the_page_is_revalidated_not_stored_and_not_resent(self):
        r, body, c = self.get("/", {"Accept-Encoding": "gzip"})
        tag = r.getheader("ETag")
        self.assertEqual((r.status, r.getheader("Cache-Control")), (200, "no-cache"))
        self.assertIn(b"<!DOCTYPE html>", gzip.decompress(body))
        r2, body2, _ = self.get("/", {"Accept-Encoding": "gzip", "If-None-Match": tag}, conn=c)
        self.assertEqual((r2.status, body2), (304, b""))
        self.assertEqual(r2.getheader("Cache-Control"), "no-cache")
        r3, _, _ = self.get("/", {"Accept-Encoding": "gzip", "If-None-Match": '"other"'}, conn=c)
        self.assertEqual(r3.status, 200)

    def test_each_variant_has_its_own_tag(self):
        a = self.get("/", {"Accept-Encoding": "gzip"})[0].getheader("ETag")
        b = self.get("/", {"Accept-Encoding": "gzip", "Cookie": "asl_slow=on"})[0].getheader("ETag")
        c = self.get("/")[0].getheader("ETag")
        self.assertEqual(len({a, b, c}), 3)

    def test_json_replies_stay_uncached(self):
        r, _, _ = self.get("/api/status")
        self.assertEqual(r.getheader("Cache-Control"), "no-store")


class PageScript(unittest.TestCase):
    js = nt._JS

    def test_the_page_discounts_the_servers_own_work_when_it_judges_the_link(self):
        self.assertIn("X-Work-Ms", self.js)
        self.assertIn("NET.sample(Math.max(0, performance.now() - t0 - lastSrvMs))", self.js)

    def test_a_not_modified_status_gets_its_ticking_values_from_the_header(self):
        self.assertIn("r.headers.get('X-Volatile')", self.js)
        self.assertIn("Object.assign(JSON.parse(_tags[url].text), vol || {})", self.js)

    def test_the_status_is_polled_faster(self):
        self.assertIn("pollEvery(pollStatus, 1000, 2500)", self.js)

    def test_unchanged_text_and_the_links_table_are_not_written_again(self):
        self.assertIn("function put(id, v)", self.js)
        body = self.js.split("async function pollStatus() {", 1)[1].split("let jitAdapt", 1)[0]
        self.assertGreater(body.count("put('"), 10)
        self.assertIn("linkSig !== linksSig", body)
        self.assertNotIn("$('st-node').textContent", body)

    def test_the_fast_timers_rest_in_a_hidden_tab(self):
        for name in ("function gapTick() {", "function availUi() {"):
            self.assertIn(name + "\n  if (document.visibilityState === 'hidden') return;", self.js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
