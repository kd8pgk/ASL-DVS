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


if __name__ == "__main__":
    unittest.main(verbosity=2)
