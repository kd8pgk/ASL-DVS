import glob
import importlib.util
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_ports_svx_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_ports_svx_under_test"] = h44
spec.loader.exec_module(h44)

CONF = """[GLOBAL]
LOGICS=UsrpLogic,ReflectorLogic

[ReflectorLogic]
TYPE=Reflector
HOSTS=north.america.svxlink.net
HOST_PORT=35300
CALLSIGN="KD8PGK"
#HOSTS=ignored.example.org
"""


def with_conf(text):
    return mock.patch.object(h44, "_cfgr_read", lambda p: text.encode() if p == h44._CFGR_SVX_CONF and text is not None else None)


class Reference(unittest.TestCase):
    def row(self, label):
        for r in h44._PORTS_REFERENCE:
            if r[0] == label:
                return r
        self.fail(label)

    def test_the_svxlink_ports_are_listed_with_roles(self):
        want = {
            "SvxLink USRP (SvxLink listen)": ("34000", "udp", "loopback-only", True),
            "SvxLink USRP (ASL listen)": ("32000", "udp", "loopback-only", False),
            "SvxReflector (test server, TCP)": ("5300", "tcp", "loopback-only", True),
            "SvxReflector (test server, UDP)": ("5300", "udp", "loopback-only", True),
            "EchoLink (TCP)": ("5200", "tcp", "peer-inbound", False),
        }
        for label, (port, proto, role, risky) in want.items():
            r = self.row(label)
            self.assertEqual((r[1], r[2], r[4]), (port, proto, risky), label)
            self.assertEqual(h44._port_role(port, proto)[1], role, label)

    def test_every_new_row_has_a_role_and_the_system_is_svxlink_or_allstar(self):
        for r in h44._PORTS_REFERENCE:
            if "SvxLink" in r[0] or "SvxReflector" in r[0] or r[0] == "EchoLink (TCP)":
                system, role = h44._port_role(r[1], r[2])
                self.assertNotEqual(role, h44._PORT_ROLE_OTHER, r[0])
                self.assertIn(system, ("SvxLink", "AllStarLink / SVXLink"), r[0])

    def test_the_usrp_ports_are_never_a_valid_exposure(self):
        self.assertEqual(h44._port_verdict("loopback-only", True, True), "over-exposed")
        self.assertEqual(h44._port_verdict("loopback-only", False, True), "OK")
        self.assertEqual(h44._port_verdict("peer-inbound", False, True), "needed-but-not-open")

    def test_the_services_tab_knows_the_units_and_ports(self):
        units = {u for _l, u, _g, _f in h44._SERVICE_UNIT_DEFS}
        self.assertIn("svxlink-usrp.service", units)
        self.assertIn("svxreflector.service", units)
        ports = {(p, pr) for _l, p, pr, _g, _f in h44._SERVICE_PORT_DEFS}
        self.assertTrue({(34000, "udp"), (32000, "udp"), (5300, "tcp"), (5300, "udp")} <= ports)


class ReflectorTargets(unittest.TestCase):
    def test_the_reflector_host_and_port_come_from_svxlink_conf(self):
        with with_conf(CONF):
            self.assertEqual(h44._svx_reflector_targets(), [("north.america.svxlink.net", "35300")])

    def test_a_host_with_its_own_port_and_a_second_host(self):
        text = CONF.replace("HOSTS=north.america.svxlink.net", "HOSTS=a.example.org,b.example.org:5301")
        with with_conf(text):
            self.assertEqual(h44._svx_reflector_targets(), [("a.example.org", "35300"), ("b.example.org", "5301")])

    def test_the_default_port_is_5300(self):
        with with_conf(CONF.replace("HOST_PORT=35300\n", "")):
            self.assertEqual(h44._svx_reflector_targets(), [("north.america.svxlink.net", "5300")])

    def test_the_local_test_reflector_is_not_an_outbound_row(self):
        with with_conf(CONF.replace("north.america.svxlink.net", "127.0.0.1")):
            self.assertEqual(h44._svx_reflector_targets(), [])

    def test_no_conf_or_no_section_gives_nothing(self):
        with with_conf(None):
            self.assertEqual(h44._svx_reflector_targets(), [])
        with with_conf("[GLOBAL]\nLOGICS=UsrpLogic\n"):
            self.assertEqual(h44._svx_reflector_targets(), [])

    def test_a_bad_port_is_ignored(self):
        with with_conf(CONF.replace("north.america.svxlink.net", "x.example.org:99999")):
            self.assertEqual(h44._svx_reflector_targets(), [])

    def test_the_rows_are_outbound_only_tcp_and_udp(self):
        with with_conf(CONF):
            rows = h44._svx_reflector_rows()
        self.assertEqual([(r[1], r[2], r[5], r[6]) for r in rows],
                         [("35300", "tcp", "SvxLink", "outbound-only"), ("35300", "udp", "SvxLink", "outbound-only")])
        self.assertIn("north.america.svxlink.net:35300", rows[0][3])


class Status(unittest.TestCase):
    def build(self, conf, running=(), zone=None):
        cfg = h44.configparser.ConfigParser()
        cfg.read_dict({"server": {"port": "9997"}, "tunnels": {"tunnel.pi.mode": "pi"}})
        groups = {"SVXLink": [{"label": x, "active": True} for x in running]}
        with with_conf(conf), \
                mock.patch.object(h44, "build_services_status", lambda c: {"groups": groups}), \
                mock.patch.object(h44, "_firewalld_zone_info", lambda: zone), \
                mock.patch.object(h44, "_ref_port_listening", lambda port, proto: False):
            return {(r["label"], r["proto"]): r for r in h44.build_ports_status(cfg)["rows"]}

    def test_the_reflector_row_shows_up_and_is_running_with_the_service(self):
        rows = self.build(CONF, running=("SvxLink (USRP build, svxlink-usrp)",))
        r = rows[("SvxLink reflector, outbound (north.america.svxlink.net)", "tcp")]
        self.assertEqual((r["port"], r["role"], r["running"], r["verdict"]), ("35300", "outbound-only", True, "OK"))

    def test_the_reflector_row_is_not_running_when_svxlink_is_stopped(self):
        rows = self.build(CONF, running=())
        r = rows[("SvxLink reflector, outbound (north.america.svxlink.net)", "udp")]
        self.assertEqual((r["running"], r["verdict"]), (False, "not-listening"))

    def test_opening_the_reflector_port_inbound_is_over_exposed(self):
        rows = self.build(CONF, running=("SvxLink",), zone={"ports": ["35300/tcp", "34000/udp"], "services": []})
        self.assertEqual(rows[("SvxLink reflector, outbound (north.america.svxlink.net)", "tcp")]["verdict"], "over-exposed")
        self.assertEqual(rows[("SvxLink USRP (SvxLink listen)", "udp")]["verdict"], "over-exposed")
        self.assertTrue(rows[("SvxLink USRP (SvxLink listen)", "udp")]["mismatch"])

    def test_the_echolink_tcp_port_needed_but_not_open_when_listening(self):
        cfg = h44.configparser.ConfigParser()
        cfg.read_dict({"server": {"port": "9997"}, "tunnels": {"tunnel.pi.mode": "pi"}})
        with with_conf(CONF), mock.patch.object(h44, "build_services_status", lambda c: {"groups": {}}), \
                mock.patch.object(h44, "_firewalld_zone_info", lambda: {"ports": [], "services": []}), \
                mock.patch.object(h44, "_ref_port_listening", lambda port, proto: port == "5200"):
            rows = {(r["label"], r["proto"]): r for r in h44.build_ports_status(cfg)["rows"]}
        self.assertEqual(rows[("EchoLink (TCP)", "tcp")]["verdict"], "needed-but-not-open")

    def test_without_a_conf_there_are_no_outbound_rows(self):
        rows = self.build(None)
        self.assertFalse([k for k in rows if k[0].startswith("SvxLink reflector, outbound")])


if __name__ == "__main__":
    unittest.main()
