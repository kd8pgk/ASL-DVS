#!/usr/bin/env python3
import glob
import importlib.util
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = sorted(glob.glob(os.path.join(ROOT, "nodemon_v*.py")))[-1]
spec = importlib.util.spec_from_file_location("nodemon_under_test", PATH)
nm = importlib.util.module_from_spec(spec)
sys.modules["nodemon_under_test"] = nm
spec.loader.exec_module(nm)

XSTAT = """Response: Success
Node: 654321
Conn: 1900      127.0.0.1           0           OUT        00:00:04            ESTABLISHED         
Conn: 45192     203.0.113.9         2           IN         00:12:30            ESTABLISHED         
LinkedNodes: T1900, R45192
Var: RPT_NUMLINKS=2
Var: RPT_LINKS=2,T1900,R45192
Var: RPT_NUMALINKS=2
Var: RPT_ALINKS=2,1900TU,45192RK
Var: RPT_ETXKEYED=1
Var: RPT_TXKEYED=1
Var: RPT_AUTOPATCHUP=0
Var: RPT_RXKEYED=0
parrot_ena: 0""".split("\n")

NO_LINKS = """Response: Success
Node: 654321
LinkedNodes: <NONE>
Var: RPT_ALINKS=0
Var: RPT_LINKS=0
Var: RPT_TXKEYED=0
Var: RPT_RXKEYED=0""".split("\n")

REGS = ["Response: Success", "Message: Command output follows",
        "Output: Host                                           Username    Perceived                            Refresh  State",
        "Output: register.allstarlink.org:443                   654321      203.0.113.9:4569                         179  Registered",
        "Output: (null)                                         1999        <Unregistered>                             0  Not Registered",
        "Output: 2 HTTP registrations."]

LOCAL = ["Response: Success", "Output:                          ", "Output: Node", "Output: ----", "Output: 654321", "Output: 1900"]

RPT = """[general]
x = 1

[nodes]
654321 = radio@127.0.0.1/654321,NONE
1900 = radio@127.0.0.1/1900,NONE

[node-main](!)
duplex = 0

[654321](node-main)
rxchannel = SimpleUSB/654321

[1999](node-main)
rxchannel = USRP/127.0.0.1:34001:32001

[1900](node-main)
rxchannel = USRP/127.0.0.1:34000:32000

[1921](node-main)
rxchannel = USRP/127.0.0.1:34018:32018
"""


class Parsers(unittest.TestCase):
    def test_xstat_links_modes_and_keying(self):
        r = nm.parse_xstat(XSTAT)
        by = {x["node"]: x for x in r["links"]}
        self.assertEqual(set(by), {"1900", "45192"})
        self.assertEqual(by["1900"]["mode"], "T")
        self.assertEqual(by["1900"]["mode_name"], "Transceive")
        self.assertEqual(by["1900"]["direction"], "OUT")
        self.assertEqual(by["1900"]["since"], "00:00:04")
        self.assertEqual(by["1900"]["state"], "ESTABLISHED")
        self.assertFalse(by["1900"]["keyed"])
        self.assertEqual(by["45192"]["mode_name"], "Monitor (receive only)")
        self.assertTrue(by["45192"]["keyed"])
        self.assertEqual(by["45192"]["reconnects"], 2)
        self.assertTrue(r["txkeyed"])
        self.assertFalse(r["rxkeyed"])

    def test_xstat_no_links(self):
        r = nm.parse_xstat(NO_LINKS)
        self.assertEqual(r["links"], [])
        self.assertFalse(r["txkeyed"])

    def test_a_node_still_connecting_is_listed(self):
        r = nm.parse_xstat(["Response: Success", "LinkedNodes: C1234", "Var: RPT_ALINKS=0"])
        self.assertEqual(len(r["links"]), 1)
        self.assertEqual(r["links"][0]["state"], "CONNECTING")
        self.assertEqual(r["links"][0]["mode_name"], "Connecting")

    def test_registrations(self):
        r = nm.parse_registrations(REGS)
        self.assertEqual(r["654321"]["state"], "Registered")
        self.assertEqual(r["654321"]["refresh"], 179)
        self.assertEqual(r["1999"]["state"], "Not Registered")
        self.assertEqual(r["1999"]["host"], "(null)")

    def test_localnodes(self):
        self.assertEqual(nm.parse_localnodes(LOCAL), ["654321", "1900"])


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rpt = os.path.join(self.tmp.name, "rpt.conf")
        with open(self.rpt, "w") as f:
            f.write(RPT)
        self.old = nm.RPT_CONF
        nm.RPT_CONF = self.rpt
        nm._config["main_node"] = ""

    def tearDown(self):
        nm.RPT_CONF = self.old
        self.tmp.cleanup()

    def test_public_private_and_bridge_kinds(self):
        p = nm.node_plan()
        self.assertTrue(p["ok"])
        self.assertEqual(p["main"], "654321")
        self.assertEqual(p["private"], ["1999", "1900", "1921"])
        self.assertEqual(p["kind"]["1900"][0], "svx")
        self.assertEqual(p["kind"]["1999"][0], "dvswitch")
        self.assertEqual(p["kind"]["1921"][0], "nodetalker")
        self.assertNotIn("654321", p["kind"])

    def test_missing_rpt_conf_is_reported(self):
        nm.RPT_CONF = os.path.join(self.tmp.name, "none.conf")
        p = nm.node_plan()
        self.assertFalse(p["ok"])
        self.assertIn("none.conf", p["error"])

    def test_main_node_setting_picks_another_public_node(self):
        with open(self.rpt, "a") as f:
            f.write("\n[777777](node-main)\nrxchannel = SimpleUSB/777777\n")
        nm._config["main_node"] = "777777"
        self.assertEqual(nm.node_plan()["main"], "777777")
        nm._config["main_node"] = "123"
        self.assertEqual(nm.node_plan()["main"], "654321")


LOG = """Mon Nov 16 10:52:16 2026: Activating link 'ReflectorLink' due to DEFAULT_ACTIVE
Mon Nov 16 10:52:16 2026: ReflectorLogic: Connecting to service 
Mon Nov 16 10:52:16 2026: NOTICE[ReflectorLogic]: Connected to 127.0.0.1:5300 (primary)
Mon Nov 16 10:52:16 2026: ReflectorLogic: Authentication OK
Mon Nov 16 10:54:44 2026: ReflectorLogic: Selecting TG #240
Mon Nov 16 10:54:46 2026: ReflectorLogic: Selecting TG #0
Mon Nov 16 10:54:48 2026: Deactivating link ReflectorLink
Mon Nov 16 10:58:54 2026: Activating link 'ReflectorLink' due to DTMF command
Mon Nov 16 10:58:54 2026: ReflectorLogic: Selecting TG #240
Mon Nov 16 10:58:54 2026: *** WARNING[ReflectorLogic]: Could not find audio clip 'talk_group' in context 'Core'
""".splitlines()


class Gateways(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (nm.SVX_CONF, nm.SVX_LOG, nm.M17_INI, nm.ABINFO_GLOB, dict(nm._unit_cache))
        nm._unit_cache.clear()

    def tearDown(self):
        nm.SVX_CONF, nm.SVX_LOG, nm.M17_INI, nm.ABINFO_GLOB = self.saved[:4]
        nm._unit_cache.clear()
        nm._unit_cache.update(self.saved[4])
        self.tmp.cleanup()

    def path(self, name, text):
        p = os.path.join(self.tmp.name, name)
        with open(p, "w") as f:
            f.write(text)
        return p

    def active(self, value):
        nm._unit_cache.update({n: (time.monotonic(), value) for n in (nm.UNIT_AB, nm.UNIT_M17, nm.UNIT_SVX)})

    def test_svx_events_follow_the_last_line_of_each_kind(self):
        ev = nm.svx_events(LOG)
        self.assertEqual(ev, {"state": "connected", "tg": "240", "host": "127.0.0.1:5300", "link": True})

    def test_svx_link_turned_off_and_tg_zero(self):
        self.assertFalse(nm.svx_events(LOG[:7])["link"])
        self.assertEqual(nm.svx_events(LOG[:6])["tg"], "0")

    def test_svx_disconnect_after_login_is_down(self):
        lines = LOG + ["Mon Nov 16 11:00:00 2026: ReflectorLogic: Disconnected from 127.0.0.1:5300: Connection refused"]
        ev = nm.svx_events(lines)
        self.assertEqual(ev["state"], "down")
        self.assertEqual(ev["host"], "127.0.0.1:5300")

    def test_read_svx_connected_on_a_talkgroup(self):
        nm.SVX_CONF = self.path("svxlink.conf", "[ReflectorLogic]\nHOSTS=north.america.svxlink.net\nHOST_PORT=35300\n")
        nm.SVX_LOG = self.path("svxlink", "\n".join(LOG) + "\n")
        self.active(True)
        g = nm.read_svx()
        self.assertEqual((g["state"], g["text"], g["detail"]), ("connected", "TG 240", "north.america.svxlink.net:35300"))

    def test_read_svx_unknown_without_log_and_down_when_stopped(self):
        nm.SVX_CONF = self.path("svxlink.conf", "[ReflectorLogic]\nHOSTS=h\n")
        nm.SVX_LOG = os.path.join(self.tmp.name, "nolog")
        self.active(True)
        self.assertEqual(nm.read_svx()["state"], "unknown")
        self.active(False)
        self.assertEqual(nm.read_svx()["state"], "down")
        nm.SVX_CONF = os.path.join(self.tmp.name, "none")
        self.assertEqual(nm.read_svx()["state"], "unknown")

    def test_read_svx_idle_on_tg_zero(self):
        nm.SVX_CONF = self.path("svxlink.conf", "[ReflectorLogic]\nHOSTS=h\n")
        nm.SVX_LOG = self.path("svxlink", "\n".join(LOG[:6]) + "\n")
        self.active(True)
        self.assertEqual(nm.read_svx()["state"], "idle")

    def test_only_root_owned_status_files_are_trusted(self):
        nm.ABINFO_GLOB = os.path.join(self.tmp.name, "ABInfo_*.json")
        self.path("ABInfo_34001.json", json.dumps({"last_tune": "3100@bm_server"}))
        self.active(True)
        with unittest.mock.patch.object(nm, "_root_owned", lambda path: False):
            self.assertEqual(nm.read_dvswitch()["state"], "unknown")
        self.assertEqual(nm._root_owned(os.path.join(self.tmp.name, "none")), False)

    def test_read_m17(self):
        nm.M17_INI = self.path("m.ini", "[M17 Network]\nAddress=m17.freestar.network\nName=M17-DMR C\n")
        self.active(True)
        g = nm.read_m17()
        self.assertEqual((g["state"], g["text"], g["detail"]), ("connected", "M17-DMR C", "m17.freestar.network"))
        self.active(False)
        self.assertEqual(nm.read_m17()["state"], "down")
        nm.M17_INI = os.path.join(self.tmp.name, "none")
        self.assertEqual(nm.read_m17()["state"], "unknown")

    def test_read_dvswitch(self):
        nm.ABINFO_GLOB = os.path.join(self.tmp.name, "ABInfo_*.json")
        owner = unittest.mock.patch.object(nm, "_root_owned", lambda path: True)
        owner.start()
        self.addCleanup(owner.stop)
        self.active(True)
        self.assertEqual(nm.read_dvswitch()["state"], "unknown")
        self.path("ABInfo_34001.json", json.dumps({"last_tune": "3100@bm_server"}))
        g = nm.read_dvswitch()
        self.assertEqual((g["state"], g["text"]), ("connected", "3100@bm_server"))
        self.active(False)
        self.assertEqual(nm.read_dvswitch()["state"], "down")


class FakeAmi(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, **kw):
        self.replies = kw
        self.seen = []
        self.cmds = []
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
            aid = msg.get("ActionID", "")
            self.server.seen.append(msg)
            if msg.get("Action") == "Login":
                ok = msg.get("Username") == "admin" and msg.get("Secret") == "pw"
                body = ["Response: " + ("Success" if ok else "Error"), "ActionID: " + aid,
                        "Message: " + ("Authentication accepted" if ok else "Authentication failed")]
            elif msg.get("Command") == "rpt localnodes":
                body = LOCAL[:1] + ["ActionID: " + aid] + LOCAL[1:]
            elif msg.get("Command") == "rpt show registrations":
                body = REGS[:1] + ["ActionID: " + aid] + REGS[1:]
            elif msg.get("Command", "").startswith("rpt cmd "):
                self.server.cmds.append(msg["Command"])
                body = ["Response: Success", "ActionID: " + aid, "Message: Command output follows"]
                if msg["Command"].endswith(" 777"):
                    body.append("Output: Unknown node number 777.")
            elif msg.get("Command") == "XStat":
                lines = self.server.replies.get(msg.get("Node"))
                body = (lines[:1] + ["ActionID: " + aid] + lines[1:]) if lines else \
                    ["Response: Error", "ActionID: " + aid, "Message: Node not found"]
            else:
                body = ["Response: Error", "ActionID: " + aid, "Message: Unknown"]
            self.wfile.write(("\r\n".join(body) + "\r\n\r\n").encode())


class LivePoll(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (nm.RPT_CONF, nm.AMI_CONF, nm.AMI_PORT, nm.SVX_CONF, nm.SVX_LOG, nm.M17_INI, nm.ABINFO_GLOB,
                      dict(nm._config), dict(nm._unit_cache))
        self.ami = FakeAmi(**{"654321": XSTAT, "1900": NO_LINKS})
        threading.Thread(target=self.ami.serve_forever, daemon=True).start()
        self.write("rpt.conf", RPT)
        self.write("manager.conf", "[general]\nenabled = yes\n[admin]\nsecret = pw\n")
        nm.RPT_CONF = os.path.join(self.tmp.name, "rpt.conf")
        nm.AMI_CONF = os.path.join(self.tmp.name, "manager.conf")
        nm.AMI_PORT = self.ami.server_address[1]
        nm.SVX_CONF = os.path.join(self.tmp.name, "svxlink.conf")
        nm.SVX_LOG = os.path.join(self.tmp.name, "svxlink")
        nm.M17_INI = os.path.join(self.tmp.name, "none.ini")
        nm.ABINFO_GLOB = os.path.join(self.tmp.name, "ABInfo_*.json")
        nm._config.update(poll_sec=1, main_node="")
        nm._unit_cache.update({n: (time.monotonic() + 1000, True) for n in (nm.UNIT_AB, nm.UNIT_M17, nm.UNIT_SVX)})
        self.write("svxlink.conf", "[ReflectorLogic]\nHOSTS=h\nHOST_PORT=5300\n")
        self.write("svxlink", "\n".join(LOG) + "\n")

    def tearDown(self):
        self.ami.shutdown()
        self.ami.server_close()
        (nm.RPT_CONF, nm.AMI_CONF, nm.AMI_PORT, nm.SVX_CONF, nm.SVX_LOG, nm.M17_INI, nm.ABINFO_GLOB) = self.saved[:7]
        nm._config.clear()
        nm._config.update(self.saved[7])
        nm._unit_cache.clear()
        nm._unit_cache.update(self.saved[8])
        self.tmp.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.tmp.name, name), "w") as f:
            f.write(text)

    def run_monitor(self):
        mon = nm.Monitor()
        old = nm.MON
        nm.MON = mon
        self.addCleanup(setattr, nm, "MON", old)
        threading.Thread(target=mon.loop, daemon=True).start()
        end = time.time() + 10
        while time.time() < end and not mon.state()["ok"] and mon.state()["error"] in ("starting", ""):
            time.sleep(0.05)
        return mon

    def test_status_joins_ami_registration_gateways_and_not_loaded(self):
        self.run_monitor()
        d = nm.build_status()
        self.assertTrue(d["ami"]["ok"], d["ami"])
        self.assertEqual(d["main"]["node"], "654321")
        self.assertTrue(d["main"]["loaded"])
        self.assertEqual(d["main"]["registration"]["state"], "Registered")
        links = {x["node"]: x for x in d["main"]["links"]}
        self.assertEqual(links["1900"]["bridge"], "SvxLink bridge")
        self.assertEqual(links["1900"]["gateway"]["text"], "TG 240")
        self.assertIsNone(links["45192"]["gateway"])
        priv = {x["node"]: x for x in d["private"]}
        self.assertTrue(priv["1900"]["loaded"])
        self.assertEqual(priv["1900"]["gateway"]["state"], "connected")
        self.assertFalse(priv["1999"]["loaded"])
        self.assertFalse(priv["1999"]["ok"])
        self.assertIn("not found", priv["1999"]["error"].lower())
        self.assertFalse(priv["1921"]["loaded"])
        self.assertNotIn("gateway", priv["1921"])

    def test_a_refused_login_shows_no_links(self):
        self.write("manager.conf", "[admin]\nsecret = wrong\n")
        mon = self.run_monitor()
        d = nm.build_status()
        self.assertFalse(mon.state()["ok"])
        self.assertIn("refused", d["ami"]["error"])
        self.assertEqual(d["main"]["links"], [])
        self.assertIsNone(d["main"]["registration"])
        self.assertFalse(d["main"]["ok"])

    def test_no_manager_login_is_reported(self):
        self.write("manager.conf", "[general]\nenabled = yes\n")
        self.run_monitor()
        self.assertIn("no AMI login", nm.build_status()["ami"]["error"])

    def test_asterisk_not_running_is_reported(self):
        port = nm.AMI_PORT
        self.ami.shutdown()
        self.ami.server_close()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        nm.AMI_PORT = s.getsockname()[1]
        s.close()
        self.assertNotEqual(port, nm.AMI_PORT)
        mon = self.run_monitor()
        self.assertFalse(mon.state()["ok"])
        self.assertIn("AMI", nm.build_status()["ami"]["error"])
        self.ami = FakeAmi()
        threading.Thread(target=self.ami.serve_forever, daemon=True).start()


class AmiCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (nm.RPT_CONF, nm.AMI_CONF, nm.AMI_PORT)
        self.ami = FakeAmi()
        threading.Thread(target=self.ami.serve_forever, daemon=True).start()
        for name, text in (("rpt.conf", RPT), ("manager.conf", "[admin]\nsecret = pw\n")):
            with open(os.path.join(self.tmp.name, name), "w") as f:
                f.write(text)
        nm.RPT_CONF = os.path.join(self.tmp.name, "rpt.conf")
        nm.AMI_CONF = os.path.join(self.tmp.name, "manager.conf")
        nm.AMI_PORT = self.ami.server_address[1]
        nm._config["main_node"] = ""

    def tearDown(self):
        self.ami.shutdown()
        self.ami.server_close()
        nm.RPT_CONF, nm.AMI_CONF, nm.AMI_PORT = self.saved
        self.tmp.cleanup()


class Commands(AmiCase):
    def line(self, **body):
        return nm.command_line(body)[0]

    def err(self, **body):
        line, why = nm.command_line(body)
        self.assertIsNone(line, line)
        return why

    def test_every_ilink_operation_of_rpt_conf_is_offered_except_the_unused_one(self):
        self.assertEqual(sorted(c["op"] for c in nm.COMMANDS), [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 15, 16, 17, 18])
        for c in nm.COMMANDS:
            self.assertIn(c["target"], ("node", "node0", "none"))
            self.assertTrue(c["label"] and c["group"])

    def test_lines_are_built_from_validated_parts(self):
        self.assertEqual(self.line(node="654321", op=3, target="1900"), "rpt cmd 654321 ilink 3 1900")
        self.assertEqual(self.line(node="654321", op="1", target="45192"), "rpt cmd 654321 ilink 1 45192")
        self.assertEqual(self.line(node="654321", op=6), "rpt cmd 654321 ilink 6")
        self.assertEqual(self.line(node="1900", op=16), "rpt cmd 1900 ilink 16")
        self.assertEqual(self.line(node="654321", op=9, target="0", text="Net starts at 8"),
                         "rpt cmd 654321 ilink 9 0 Net starts at 8")

    def test_bad_input_is_refused_before_asterisk_sees_it(self):
        self.assertIn("not a node", self.err(node="999", op=3, target="1900"))
        self.assertIn("not a node", self.err(node="654321; rpt", op=3, target="1900"))
        self.assertIn("Unknown command", self.err(node="654321", op=10, target="1"))
        self.assertIn("Unknown command", self.err(node="654321", op=99))
        self.assertIn("Pick a command", self.err(node="654321", op="x"))
        self.assertIn("Type or pick", self.err(node="654321", op=3, target=""))
        self.assertIn("Type or pick", self.err(node="654321", op=3, target="19 00"))
        self.assertIn("Type or pick", self.err(node="654321", op=3, target="0"))
        self.assertIn("itself", self.err(node="654321", op=3, target="654321"))
        self.assertIn("takes no node", self.err(node="654321", op=6, target="1900"))
        self.assertIn("message", self.err(node="654321", op=9, target="0", text=""))
        self.assertIn("message", self.err(node="654321", op=9, target="0", text='hi"; core stop now'))
        self.assertIn("message", self.err(node="654321", op=9, target="0", text="x" * 101))

    def test_a_command_goes_to_asterisk_and_is_logged(self):
        r = nm.run_command({"node": "654321", "op": 3, "target": "1900"}, "192.0.2.5")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.ami.cmds, ["rpt cmd 654321 ilink 3 1900"])
        self.assertIn("Connect: transceive", r["message"])
        with nm._log_lock:
            last = list(nm._log)[-1]
        self.assertIn("192.0.2.5", last["msg"])
        self.assertIn("rpt cmd 654321 ilink 3 1900", last["msg"])

    def test_asterisk_answering_with_text_is_an_error(self):
        with open(nm.RPT_CONF, "a") as f:
            f.write("\n[777](node-main)\nrxchannel = SimpleUSB/777\n")
        r = nm.run_command({"node": "654321", "op": 3, "target": "777"})
        self.assertFalse(r["ok"])
        self.assertIn("Unknown node number 777", r["error"])

    def test_no_manager_login_and_asterisk_down(self):
        with open(nm.AMI_CONF, "w") as f:
            f.write("[general]\nenabled = yes\n")
        r = nm.run_command({"node": "654321", "op": 6})
        self.assertFalse(r["ok"])
        self.assertIn("no AMI login", r["error"])
        with open(nm.AMI_CONF, "w") as f:
            f.write("[admin]\nsecret = pw\n")
        nm.AMI_PORT = 1
        r = nm.run_command({"node": "654321", "op": 6})
        self.assertFalse(r["ok"])
        self.assertIn("could not be reached", r["error"])


class SystemBar(AmiCase):
    def test_reboot_and_shutdown_start_the_right_command_after_a_pause(self):
        started = []
        done = threading.Event()

        class FakePopen:
            def __init__(self, cmd, **kw):
                started.append(cmd)
                done.set()

        with unittest.mock.patch.object(nm.subprocess, "Popen", FakePopen), \
                unittest.mock.patch.object(nm.time, "sleep", lambda s: None), \
                unittest.mock.patch.object(nm.os, "geteuid", lambda: 0):
            r = nm.system_power("reboot", "192.0.2.5")
            self.assertTrue(done.wait(3))
            self.assertEqual((r["ok"], r["message"]), (True, "Rebooting..."))
            done.clear()
            r = nm.system_power("shutdown", "192.0.2.5")
            self.assertTrue(done.wait(3))
            self.assertEqual(r["message"], "Shutting down...")
        self.assertEqual(started, [["reboot"], ["shutdown", "-h", "now"]])
        with nm._log_lock:
            lines = [x["msg"] for x in nm._log]
        self.assertTrue(any("System reboot requested from 192.0.2.5" in x for x in lines))

    def test_power_needs_root_and_a_known_action(self):
        with unittest.mock.patch.object(nm.os, "geteuid", lambda: 1000), \
                unittest.mock.patch.object(nm.subprocess, "Popen") as popen:
            self.assertFalse(nm.system_power("reboot")["ok"])
            self.assertIn("root", nm.system_power("reboot")["error"])
            self.assertFalse(nm.system_power("halt")["ok"])
            popen.assert_not_called()

    def snap(self, links):
        return {"nodes": {"654321": {"links": links}}, "ok": True, "error": "", "at": time.time(), "banner": "",
                "loaded": [], "regs": {}}

    def test_disconnect_all_drops_every_link_and_keeps_node_talkers_transmit_node(self):
        links = [{"node": "1900"}, {"node": "1921"}, {"node": "45192"}]
        with unittest.mock.patch.object(nm.MON, "state", lambda: self.snap(links)), \
                unittest.mock.patch.object(nm.time, "sleep", lambda s: None):
            r = nm.disconnect_all("192.0.2.5")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.ami.cmds, ["rpt cmd 654321 ilink 6", "rpt cmd 654321 ilink 3 1921"])
        self.assertIn("Disconnected every link on node 654321", r["message"])
        self.assertIn("Node Talker's transmit node 1921 was linked again", r["message"])

    def test_disconnect_all_with_no_transmit_node_only_drops(self):
        with unittest.mock.patch.object(nm.MON, "state", lambda: self.snap([{"node": "1900"}])):
            r = nm.disconnect_all()
        self.assertTrue(r["ok"])
        self.assertEqual(self.ami.cmds, ["rpt cmd 654321 ilink 6"])
        self.assertNotIn("Node Talker", r["message"])

    def test_disconnect_all_reports_a_failure_and_does_not_relink(self):
        nm.AMI_PORT = 1
        with unittest.mock.patch.object(nm.MON, "state", lambda: self.snap([{"node": "1921"}])):
            r = nm.disconnect_all()
        self.assertFalse(r["ok"])
        self.assertEqual(self.ami.cmds, [])

    def test_the_page_has_the_system_bar_and_its_routes_are_guarded(self):
        self.assertIn('id="sys-disc"', nm._HTML_TEMPLATE)
        self.assertIn('id="sys-reboot"', nm._HTML_TEMPLATE)
        self.assertIn('id="sys-shutdown"', nm._HTML_TEMPLATE)
        with open(PATH, encoding="utf-8") as fh:
            src = fh.read()
        post = src.split("    def do_POST(self):", 1)[1].split("class Server", 1)[0]
        self.assertLess(post.index("if not self._authed():"), post.index('"/api/system/reboot"'))
        self.assertLess(post.index("if not self._authed():"), post.index('"/api/disconnect-all"'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
