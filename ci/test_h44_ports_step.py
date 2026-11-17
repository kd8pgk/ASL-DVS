import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_ports_step_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_ports_step_under_test"] = h44
spec.loader.exec_module(h44)

ALL = {"asl3": "installed", "dvs": "installed", "usrp2m17": "installed", "svx": "installed"}


def zone(ports=(), services=(), accept=False):
    return {"ports": list(ports), "services": list(services), "accept": accept}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)

    def unit(self, name):
        open(os.path.join(self.d.name, name), "w").close()


class Plan(Tmp):
    def plan(self, mode="half", installed=None, cockpit=True, units=()):
        for u in units:
            self.unit(u + ".service")
        with mock.patch.object(h44, "_BLD_UNIT_DIRS", (self.d.name,)):
            return h44._bld_ports_plan(mode, ALL if installed is None else installed, cockpit)

    def specs(self, zone, **kw):
        rows, _ = self.plan(**kw)
        return [r["spec"] for r in rows if r["zone"] == zone]

    def test_ssh_cockpit_and_44helper_are_always_in_the_lan_zone(self):
        lan = self.specs("lan", installed={})
        self.assertEqual(lan, ["22/tcp", "9090/tcp", "9997/tcp"])
        self.assertNotIn("9090/tcp", self.specs("lan", installed={}, cockpit=False))

    def test_only_installed_tools_get_a_port(self):
        lan = self.specs("lan", installed={}, units=("nodecontrol", "nodetalker", "termon", "nodemon"))
        for port in ("8989", "8993", "7878", "7777"):
            self.assertIn(port + "/tcp", lan)
        for port in ("9999", "8990", "8991", "8995", "9000"):
            self.assertNotIn(port + "/tcp", lan)

    def test_peer_ports_follow_the_systems_and_the_mode(self):
        self.assertEqual(self.specs("tunnel", mode="half"), ["4569/udp", "5198-5199/udp", "5200/tcp"])
        self.assertEqual(self.specs("tunnel", mode="full"), ["4569/udp", "5198-5199/udp", "5200/tcp"])
        self.assertEqual(self.specs("tunnel", mode="split"), ["4569/udp"])
        self.assertEqual(self.specs("tunnel", installed={}), [])
        self.assertEqual(self.specs("tunnel", installed={"svx": "installed"}), ["5198-5199/udp", "5200/tcp"])
        self.assertEqual(self.specs("tunnel", installed={"dvs": "installed", "usrp2m17": "installed"}), [])

    def test_no_loopback_or_management_only_port_is_ever_planned_for_the_tunnel(self):
        tun = self.specs("tunnel")
        loop = [k for k, (_n, role) in h44._PORT_ROLES.items() if role == "loopback-only"]
        for spec in tun + self.specs("lan"):
            self.assertNotIn(spec, loop)
        for spec in tun:
            self.assertIn(h44._PORT_ROLES.get(spec, ("", ""))[1], ("peer-inbound",), spec)

    def test_systems_with_nothing_inbound_say_so(self):
        _rows, notes = self.plan()
        text = " ".join(notes)
        self.assertIn("DVSwitch: nothing inbound", text)
        self.assertIn("USRP2M17: nothing inbound", text)
        self.assertIn("SvxLink: nothing inbound", text)
        self.assertEqual(self.plan(installed={})[1], [])

    def test_the_suite_ports_match_the_ports_reference(self):
        for _unit, port, name in h44._BLD_SUITE_PORTS:
            self.assertTrue(1 <= port <= 65535, name)
        self.assertEqual(len({p for _u, p, _n in h44._BLD_SUITE_PORTS}), len(h44._BLD_SUITE_PORTS))


class Open(unittest.TestCase):
    def test_exact_range_service_and_accept(self):
        z = zone(ports=["8989/tcp", "5198-5199/udp"], services=["ssh", "cockpit"])
        for spec in ("8989/tcp", "5198-5199/udp", "5198/udp", "22/tcp", "9090/tcp"):
            self.assertTrue(h44._bld_zone_open(z, spec), spec)
        for spec in ("8989/udp", "5200/tcp", "4569/udp", "5197-5199/udp"):
            self.assertFalse(h44._bld_zone_open(z, spec), spec)
        self.assertTrue(h44._bld_zone_open(zone(services=["iax2"]), "4569/udp"))
        self.assertTrue(h44._bld_zone_open(zone(accept=True), "1/tcp"))


class Gather(Tmp):
    def gather(self, lan, tun, running=True, mode="half", installed=None):
        def fake_q(argv, timeout=6):
            if argv[1] == "--state":
                return (0 if running else -1), ""
            if argv[1] == "--get-default-zone":
                return 0, "public\n"
            return 0, ""
        zones = {"public": lan, h44.FIREWALLD_ZONE: tun}
        with mock.patch.object(h44, "_BLD_UNIT_DIRS", (self.d.name,)), \
                mock.patch.object(h44, "_ov_q", fake_q), \
                mock.patch.object(h44, "_bld_zone_state", lambda z: zones[z]):
            return h44._bld_ports_gather(mode, ALL if installed is None else installed)

    GOOD_LAN = ["22/tcp", "9090/tcp", "9997/tcp"]

    def test_done_when_everything_is_open(self):
        self.unit("cockpit.socket")
        g = self.gather(zone(self.GOOD_LAN), zone(["4569/udp", "5198-5199/udp", "5200/tcp"]))
        self.assertEqual(g["missing"], [])
        self.assertEqual(h44._bld_ports_stage(g)[0], "done")

    def test_missing_ports_make_it_open(self):
        self.unit("cockpit.socket")
        g = self.gather(zone(["22/tcp"]), zone([]))
        st, why = h44._bld_ports_stage(g)
        self.assertEqual(st, "todo")
        self.assertIn("to open", why)
        self.assertEqual([r["spec"] for r in g["missing"]][:3], ["9090/tcp", "9997/tcp", "4569/udp"])

    def test_exposures_are_a_warning_not_a_block(self):
        self.unit("cockpit.socket")
        g = self.gather(zone(self.GOOD_LAN + ["34000/udp"]), zone(["4569/udp", "5198-5199/udp", "5200/tcp", "8989/tcp"]))
        self.assertEqual(g["missing"], [])
        st, why = h44._bld_ports_stage(g)
        self.assertEqual(st, "warn")
        self.assertIn("8989/tcp is open to the tunnel side", why)
        self.assertTrue(any("34000/udp" in x for x in g["exposed"]))

    def test_no_firewall_running(self):
        g = self.gather(zone(), zone(), running=False)
        self.assertEqual(h44._bld_ports_stage(g)[0], "warn")
        self.assertEqual(g["missing"], [])

    def test_an_accept_zone_is_open_and_not_flagged(self):
        g = self.gather(zone(accept=True), zone(accept=True))
        self.assertEqual((g["missing"], g["exposed"]), ([], []))


class Run(Tmp):
    def run_ports(self, g, preview, results=None):
        calls = []

        def fake_run(argv, timeout=20):
            calls.append(argv)
            return (results or {}).get(" ".join(argv), {"success": True, "output": ""})

        with mock.patch.object(h44, "_bld_ports_gather", lambda m, i: g), mock.patch.object(h44, "_run_argv", fake_run):
            out = h44._bld_run_ports(preview, "half", {})
        return out, calls

    G = {"running": True, "default_zone": "public", "notes": ["note"], "exposed": ["8989/tcp is open to the tunnel side"],
         "rows": [], "missing": [{"zone": "lan", "spec": "9997/tcp", "why": "44helper"},
                                 {"zone": "tunnel", "spec": "4569/udp", "why": "IAX2"}]}

    def test_preview_changes_nothing(self):
        (ok, lines), calls = self.run_ports(self.G, True)
        self.assertTrue(ok)
        self.assertEqual(calls, [])
        self.assertIn("would open 9997/tcp (44helper) in zone public", lines)
        self.assertIn(f"would open 4569/udp (IAX2) in zone {h44.FIREWALLD_ZONE}", lines)

    def test_run_opens_now_and_permanently_in_the_right_zone_only(self):
        (ok, lines), calls = self.run_ports(self.G, False)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 4)
        self.assertIn(["firewall-cmd", "--zone=public", "--add-port=9997/tcp"], calls)
        self.assertIn(["firewall-cmd", "--permanent", "--zone=public", "--add-port=9997/tcp"], calls)
        self.assertIn(["firewall-cmd", f"--zone={h44.FIREWALLD_ZONE}", "--add-port=4569/udp"], calls)
        self.assertNotIn(["firewall-cmd", f"--zone={h44.FIREWALLD_ZONE}", "--add-port=9997/tcp"], calls)
        self.assertTrue(any(ln.startswith("Not changed") for ln in lines))
        self.assertFalse(any("--remove" in " ".join(c) for c in calls))

    def test_a_failure_is_reported(self):
        (ok, lines), _ = self.run_ports(self.G, False, {"firewall-cmd --permanent --zone=public --add-port=9997/tcp": {"success": False, "output": "denied"}})
        self.assertFalse(ok)
        self.assertTrue(any("FAILED to open 9997/tcp" in ln and "denied" in ln for ln in lines))

    def test_nothing_to_open(self):
        g = dict(self.G, missing=[], exposed=[])
        (ok, lines), calls = self.run_ports(g, False)
        self.assertTrue(ok)
        self.assertEqual(calls, [])
        self.assertIn("Every needed port is already open.", lines)

    def test_no_firewalld(self):
        (ok, lines), calls = self.run_ports(dict(self.G, running=False), False)
        self.assertTrue(ok)
        self.assertEqual(calls, [])

    def test_the_step_is_runnable_with_a_preview(self):
        self.assertIn("ports", h44._BLD_RUNNABLE)
        self.assertIn("ports", h44._BLD_PREVIEWABLE)
        self.assertNotIn("ports", h44._BLD_LONG)


if __name__ == "__main__":
    unittest.main()
