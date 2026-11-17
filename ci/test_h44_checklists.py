import copy
import glob
import importlib.util
import json
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ROOT, "ci", "golden", "h44_checklists.json")
NOW = 1_800_000_000.0


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_checklists_under_test", os.environ.get("H44_UNDER_TEST") or newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_checklists_under_test"] = h44
spec.loader.exec_module(h44)

PROBE_DVS_OK = {"installed": True, "active": True, "dmr": "in", "units": ["mmdvm_bridge.service"]}
PROBE_REG_OK = {"available": True, "why": "", "ips": ["44.1.2.3"], "has44": True, "registered": True, "cmd": "rpt show registrations"}


def base_world():
    return {
        "wg_rc": 0, "wg_out": "PUBKEY\t%d" % (NOW - 30), "rules": "", "dns_rc": 0, "dns_out": "44.1.1.1 allstarlink.org",
        "table": "default dev wg0 scope link", "main44": "44.0.0.0/9 dev wg0\n44.128.0.0/10 dev wg0\ndefault dev wg0",
        "md_dev": "eth0", "wg_text": "x", "perm": True, "active": True, "wg0": True, "conflicts": [],
        "route_default": ("eth0", "192.168.1.5", "r"), "routes": {}, "lan_ip": "192.168.1.5", "tools": {80: "Dashboard", 9997: "44helper"},
        "tcp_ok": True, "specs": [(1100, ["a"], "main"), (1101, ["b"], "src44")], "zone": "44NetConnect", "covered": True,
        "rp": {"all": "2", "wg0": "2"}, "dvs": dict(PROBE_DVS_OK), "usrp": {"installed": True, "active": True},
        "reg": dict(PROBE_REG_OK), "el": {"enabled": True, "entries": 120}, "myip": {"ip": "44.1.2.3"},
    }


def half_ctx(mode="permanent", ref_age=10, up_age=None, **v):
    values = {"gw_dev": "eth0", "gw_via": "192.168.1.1", "fwmark": "", "endpoint": "", "iax_port": "4569", "addr44": "44.1.2.3",
              "use_uid_rule": False, "asterisk_uid": None, "echolink": True, "ports": ["4569/udp"], "zone": "44NetConnect", "lan_ip": "192.168.1.5"}
    values.update(v)
    return {"values": values, "baseline": {"tools": [80], "dvs": {"active": True, "dmr": "in"}, "usrp": {"active": True},
                                           "reg": {"available": True}, "el": {"entries": 50}},
            "ref": NOW - ref_age, "up_at": NOW - (ref_age if up_age is None else up_age), "mode": mode, "bypass": {"hosts": [], "ports": [], "resolved": {}}}


def fx_ctx(mode="permanent", ref_age=10, up_age=None, **v):
    ctx = half_ctx(mode, ref_age, ref_age + 5000 if up_age is None else up_age, **v)
    ctx["bypass"] = {"hosts": [], "ports": [], "resolved": {}}
    return ctx


def mocks(w):
    def hq(argv, timeout=8, input_text=None):
        if argv[:4] == ["wg", "show", "wg0", "latest-handshakes"]:
            return w["wg_rc"], w["wg_out"]
        if argv[:4] == ["ip", "-4", "rule", "show"]:
            return 0, w["rules"]
        if argv[:2] == ["getent", "ahostsv4"]:
            return w["dns_rc"], w["dns_out"]
        if argv[:5] == ["ip", "-4", "route", "show", "table"]:
            return 0, w["table"]
        if argv[:5] == ["ip", "-4", "route", "show", "dev"]:
            return 0, w["main44"]
        return 0, ""

    return dict(
        _half_q=hq, _half_main_default=lambda: {"dev": w["md_dev"]}, _half_wg_text=lambda path=None: w["wg_text"],
        _half_conf_is_permanent=lambda text: w["perm"], _systemctl_is_active=lambda unit: w["active"],
        _wg0_interface_present=lambda: w["wg0"], _half_direct_conflicts=lambda: list(w["conflicts"]),
        _half_route_dev=lambda args: w["routes"].get(tuple(args), w["route_default"]), _half_lan_ip=lambda dev: w["lan_ip"],
        _half_tool_ports=lambda: dict(w["tools"]), _half_tcp_ok=lambda host, port: w["tcp_ok"], _half_rule_specs=lambda v: list(w["specs"]),
        _fw_zone_of_iface=lambda iface="wg0": w["zone"], _half_port_covered=lambda zone, pp: w["covered"],
        _half_rp_value=lambda scope: w["rp"].get(scope, ""), _half_probe_dvs=lambda: dict(w["dvs"]), _half_probe_usrp=lambda: dict(w["usrp"]),
        _half_probe_reg=lambda addr: dict(w["reg"]), _half_probe_el=lambda enabled: dict(w["el"]), check_myip=lambda: dict(w["myip"]),
    )


def route(w, args, dev, src="192.168.1.5"):
    w["routes"][tuple(args)] = (dev, src, "r")


def half_scenarios():
    out = []

    def add(name, fn=None, **ctx):
        w = base_world()
        w["rules"] = "1100:\n1101:\n"
        route(w, ["1.1.1.1"], "eth0")
        route(w, ["1.1.1.1", "ipproto", "udp", "sport", "4569"], "wg0", "44.1.2.3")
        route(w, ["1.1.1.1", "ipproto", "udp", "sport", "5198"], "wg0")
        route(w, ["192.168.1.1", "ipproto", "tcp", "sport", "80"], "eth0")
        route(w, ["10.0.0.9"], "eth0")
        if fn:
            fn(w)
        out.append((name, w, ctx))

    add("all_good")
    add("all_good_testing", mode="testing")
    add("wg_down", lambda w: w.update(wg_rc=1))
    add("wg_no_contact_early", lambda w: w.update(wg_out="PUBKEY\t0"))
    add("wg_no_contact_late", lambda w: w.update(wg_out=""), ref_age=120)
    add("wg_stale", lambda w: w.update(wg_out="PUBKEY\t%d" % (NOW - 600)))
    add("wg_age_180", lambda w: w.update(wg_out="PUBKEY\t%d" % (NOW - 180)))
    add("wg_age_181", lambda w: w.update(wg_out="PUBKEY\t%d" % (NOW - 181)))
    add("early_59", lambda w: w.update(wg_out=""), ref_age=59)
    add("early_60", lambda w: w.update(wg_out=""), ref_age=60)
    add("late_359", lambda w: w.update(reg={"available": True, "why": "", "ips": ["203.0.113.9"], "has44": False}), ref_age=359)
    add("late_360", lambda w: w.update(reg={"available": True, "why": "", "ips": ["203.0.113.9"], "has44": False}), ref_age=360)
    add("wg_no_contact_up_old", lambda w: w.update(wg_out=""), ref_age=20, up_age=500)
    add("wg_no_contact_up_new", lambda w: w.update(wg_out=""), ref_age=500, up_age=20)
    add("not_half_full_rules", lambda w: w.update(rules="1100:\n1101:\nlookup 51820"))
    add("not_half_wg_default", lambda w: w.update(md_dev="wg0"))
    add("not_half_testing", lambda w: w.update(perm=False), mode="testing")
    add("not_half_service_down", lambda w: w.update(active=False))
    add("conflicts", lambda w: w.update(conflicts=["rule A", "rule B"]))
    add("internet_via_wg", lambda w: route(w, ["1.1.1.1"], "wg0"))
    add("internet_unknown", lambda w: route(w, ["1.1.1.1"], ""))
    add("dns_fail", lambda w: w.update(dns_rc=2, dns_out=""))
    add("browser_ok", None)
    add("browser_via_wg", lambda w: route(w, ["10.0.0.9"], "wg0"))
    add("tool_not_answering", lambda w: w.update(tcp_ok=False))
    add("tool_reply_wrong_dev", lambda w: route(w, ["192.168.1.1", "ipproto", "tcp", "sport", "80"], "wg0"))
    add("no_tools", lambda w: w.update(tcp_ok=True), gw_via="")
    add("table_missing_default", lambda w: w.update(table=""))
    add("fwmark_good", lambda w: (route(w, ["44.0.0.1"], "wg0"), route(w, ["198.51.100.1", "mark", "51820"], "eth0")), fwmark="51820", endpoint="198.51.100.1")
    add("fwmark_bad", lambda w: route(w, ["44.0.0.1"], "eth0"), fwmark="51820", endpoint="198.51.100.1")
    add("fwmark_endpoint_in_wg", lambda w: (route(w, ["44.0.0.1"], "wg0"), route(w, ["198.51.100.1", "mark", "51820"], "wg0")),
        fwmark="51820", endpoint="198.51.100.1")
    add("nofwmark_routes_missing", lambda w: w.update(main44="default dev wg0"))
    add("nofwmark_testing_missing", lambda w: w.update(table=""), mode="testing")
    add("rules_missing", lambda w: w.update(rules="1100:\n"))
    add("rules_missing_testing", lambda w: w.update(rules=""), mode="testing")
    add("iax_wrong", lambda w: route(w, ["1.1.1.1", "ipproto", "udp", "sport", "4569"], "eth0", ""))
    add("uid_rule_bad", lambda w: route(w, ["1.1.1.1", "uid", "114"], "eth0"), use_uid_rule=True, asterisk_uid=114)
    add("uid_rule_good", lambda w: route(w, ["1.1.1.1", "uid", "114"], "wg0"), use_uid_rule=True, asterisk_uid=114)
    add("echolink_bad", lambda w: route(w, ["1.1.1.1", "ipproto", "udp", "sport", "5198"], "eth0"))
    add("ports_closed", lambda w: w.update(covered=False, zone=""))
    add("rp_strict", lambda w: w.update(rp={"all": "1", "wg0": "1"}))
    add("rp_unreadable", lambda w: w.update(rp={}))
    add("ports_closed_testing", lambda w: w.update(covered=False), mode="testing")
    add("dvs_missing", lambda w: w.update(dvs={"installed": False, "active": False, "dmr": "", "units": []}))
    add("dvs_stopped", lambda w: w.update(dvs={"installed": True, "active": False, "dmr": "", "units": ["x"]}))
    add("dvs_lost_master", lambda w: w.update(dvs={"installed": True, "active": True, "dmr": "out", "units": ["x"]}))
    add("dvs_no_login_lines", lambda w: w.update(dvs={"installed": True, "active": True, "dmr": "", "units": ["x"]}))
    add("usrp_missing", lambda w: w.update(usrp={"installed": False, "active": False}))
    add("usrp_stopped", lambda w: w.update(usrp={"installed": True, "active": False}))
    add("reg_not_installed", lambda w: w.update(reg={"available": False, "why": "not installed", "ips": [], "has44": False}))
    add("reg_not_running", lambda w: w.update(reg={"available": False, "why": "not running", "ips": [], "has44": False}))
    add("reg_other_early", lambda w: w.update(reg={"available": True, "why": "", "ips": ["203.0.113.9"], "has44": False}))
    add("reg_other_late", lambda w: w.update(reg={"available": True, "why": "", "ips": ["203.0.113.9"], "has44": False}), ref_age=900)
    add("reg_nothing", lambda w: w.update(reg={"available": True, "why": "no registration shown", "ips": [], "has44": False}))
    add("el_off", lambda w: w.update(el={"enabled": False, "entries": None}))
    add("el_unreadable", lambda w: w.update(el={"enabled": True, "entries": None}))
    add("el_empty_early", lambda w: w.update(el={"enabled": True, "entries": 0}))
    add("el_empty_late", lambda w: w.update(el={"enabled": True, "entries": 0}), ref_age=900)
    add("everything_broken", lambda w: w.update(wg_rc=1, rules="", dns_rc=1, dns_out="", conflicts=["x"], covered=False, tcp_ok=False,
                                                 dvs={"installed": True, "active": False, "dmr": "", "units": ["x"]},
                                                 usrp={"installed": True, "active": False},
                                                 reg={"available": False, "why": "not running", "ips": [], "has44": False},
                                                 el={"enabled": True, "entries": 0}), ref_age=900)
    return out


def fx_scenarios():
    out = []

    def add(name, fn=None, **ctx):
        w = base_world()
        w["rules"] = "from all fwmark 0xca6c lookup 51820\nfrom all lookup main suppress_prefixlength 0\n"
        route(w, ["1.1.1.1"], "wg0", "44.1.2.3")
        route(w, ["1.1.1.1", "from", "192.168.1.5"], "eth0")
        route(w, ["192.168.1.1", "ipproto", "tcp", "sport", "80"], "eth0")
        route(w, ["10.0.0.9"], "eth0")
        if fn:
            fn(w)
        out.append((name, w, ctx))

    add("all_good")
    add("all_good_testing", mode="testing")
    add("wg_down", lambda w: w.update(wg_rc=1))
    add("wg_no_contact_early", lambda w: w.update(wg_out="PUBKEY\t0"), ref_age=20)
    add("wg_no_contact_late", lambda w: w.update(wg_out=""), ref_age=120)
    add("wg_stale", lambda w: w.update(wg_out="PUBKEY\t%d" % (NOW - 600)))
    add("wg_age_180", lambda w: w.update(wg_out="PUBKEY\t%d" % (NOW - 180)))
    add("wg_age_181", lambda w: w.update(wg_out="PUBKEY\t%d" % (NOW - 181)))
    add("early_59", lambda w: w.update(wg_out=""), ref_age=59)
    add("early_60", lambda w: w.update(wg_out=""), ref_age=60)
    add("late_359", lambda w: w.update(reg={"available": True, "why": "", "ips": ["203.0.113.9"], "has44": False}), ref_age=359)
    add("late_360", lambda w: w.update(reg={"available": True, "why": "", "ips": ["203.0.113.9"], "has44": False}), ref_age=360)
    add("wg_no_contact_ref_new", lambda w: w.update(wg_out=""), ref_age=20, up_age=9000)
    add("wg_no_contact_ref_old", lambda w: w.update(wg_out=""), ref_age=500, up_age=20)
    add("full_rules_missing", lambda w: w.update(rules=""))
    add("full_rules_no_suppress", lambda w: w.update(rules="lookup 51820"))
    add("internet_not_in_tunnel", lambda w: route(w, ["1.1.1.1"], "eth0"))
    add("myip_good", None)
    add("myip_wrong", lambda w: w.update(myip={"ip": "203.0.113.9"}))
    add("myip_fail", lambda w: w.update(myip={"output": "timed out"}))
    add("myip_fail_no_output", lambda w: w.update(myip={}))
    add("no_lan_address", None, lan_ip="", gw_dev="")
    add("lan_reply_wrong", lambda w: route(w, ["1.1.1.1", "from", "192.168.1.5"], "wg0"))
    add("bypass_empty", None)
    add("bypass_good", lambda w: (route(w, ["198.51.100.7"], "eth0"), route(w, ["1.1.1.1", "ipproto", "udp", "dport", "5060"], "eth0")))
    add("bypass_bad", lambda w: (route(w, ["198.51.100.7"], "wg0"), route(w, ["1.1.1.1", "ipproto", "udp", "dport", "5060"], "wg0")))
    add("dns_fail", lambda w: w.update(dns_rc=2, dns_out=""))
    add("browser_no_route", lambda w: route(w, ["10.0.0.9"], ""))
    add("tool_not_answering", lambda w: w.update(tcp_ok=False))
    add("tool_reply_wrong_dev", lambda w: route(w, ["192.168.1.1", "ipproto", "tcp", "sport", "80"], "wg0"))
    add("no_tools_running", None, gw_via="")
    add("dvs_missing", lambda w: w.update(dvs={"installed": False, "active": False, "dmr": "", "units": []}))
    add("dvs_stopped", lambda w: w.update(dvs={"installed": True, "active": False, "dmr": "", "units": ["x"]}))
    add("dvs_lost_master", lambda w: w.update(dvs={"installed": True, "active": True, "dmr": "out", "units": ["x"]}))
    add("dvs_no_login_lines", lambda w: w.update(dvs={"installed": True, "active": True, "dmr": "", "units": ["x"]}))
    add("usrp_missing", lambda w: w.update(usrp={"installed": False, "active": False}))
    add("usrp_stopped", lambda w: w.update(usrp={"installed": True, "active": False}))
    add("reg_not_installed", lambda w: w.update(reg={"available": False, "why": "not installed", "ips": [], "has44": False}))
    add("reg_not_running", lambda w: w.update(reg={"available": False, "why": "not running", "ips": [], "has44": False}))
    add("reg_other_early", lambda w: w.update(reg={"available": True, "why": "", "ips": ["203.0.113.9"], "has44": False}))
    add("reg_other_late", lambda w: w.update(reg={"available": True, "why": "", "ips": ["203.0.113.9"], "has44": False}), ref_age=900)
    add("el_off", lambda w: w.update(el={"enabled": False, "entries": None}))
    add("el_unreadable", lambda w: w.update(el={"enabled": True, "entries": None}))
    add("el_empty_early", lambda w: w.update(el={"enabled": True, "entries": 0}))
    add("el_empty_late", lambda w: w.update(el={"enabled": True, "entries": 0}), ref_age=900)
    return out


def run(kind, name, w, ctx_args):
    ctx = (half_ctx if kind == "half" else fx_ctx)(**ctx_args)
    if kind == "fx" and name.startswith("bypass_") and name != "bypass_empty":
        ctx["bypass"] = {"hosts": ["sip.example.org"], "ports": [5060], "resolved": {"sip.example.org": ["198.51.100.7"]}}
    fn = h44._half_check_list if kind == "half" else h44._fx_check_list
    client = "10.0.0.9" if name.startswith(("browser", "all_good", "tool", "no_tools")) or name == "everything_broken" else ""
    if kind == "half" and name == "no_tools":
        client = ""
    with mock.patch.multiple(h44, **mocks(w)), mock.patch.object(h44.time, "time", lambda: NOW):
        return fn(ctx, client)


def collect():
    got = {}
    for kind, scen in (("half", half_scenarios()), ("fx", fx_scenarios())):
        for name, w, ctx_args in scen:
            got[f"{kind}:{name}"] = run(kind, name, copy.deepcopy(w), ctx_args)
    return got


class Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = collect()
        if os.environ.get("H44_WRITE_GOLDEN") == "1":
            with open(GOLDEN, "w", encoding="utf-8") as f:
                json.dump(cls.got, f, indent=1, sort_keys=True)
                f.write("\n")
        with open(GOLDEN, encoding="utf-8") as f:
            cls.want = json.load(f)

    def test_the_same_scenarios_are_recorded(self):
        self.assertEqual(sorted(self.got), sorted(self.want))

    def test_every_scenario_gives_exactly_what_was_recorded(self):
        for key in sorted(self.want):
            self.assertEqual(self.got[key], self.want[key], key)

    def test_each_list_has_its_numbered_checks_in_order(self):
        for key, results in self.got.items():
            ns = [r["n"] for r in results]
            self.assertEqual(ns, sorted(ns), key)
            self.assertEqual(len(ns), len(set(ns)), key)
            self.assertEqual(ns[0], 1, key)
        half = {r["n"] for r in self.got["half:all_good"]}
        fx = {r["n"] for r in self.got["fx:all_good"]}
        self.assertEqual(half, set(range(1, 15)))
        self.assertEqual(fx, set(range(1, 13)))

    def test_every_result_has_the_same_shape(self):
        for key, results in self.got.items():
            for r in results:
                self.assertEqual(sorted(r), ["group", "hint", "level", "n", "text", "title"], key)
                self.assertIn(r["level"], ("pass", "fail", "skip", "wait"), key)

    def test_the_all_good_cases_pass(self):
        for key in ("half:all_good", "fx:all_good"):
            levels = {r["level"] for r in self.got[key]}
            self.assertTrue(levels <= {"pass", "skip"}, (key, levels))

    def test_the_broken_cases_fail_where_they_should(self):
        by = lambda key, n: next(r for r in self.got[key] if r["n"] == n)
        self.assertEqual(by("half:wg_down", 1)["level"], "fail")
        self.assertEqual(by("half:wg_no_contact_early", 1)["level"], "wait")
        self.assertEqual(by("half:conflicts", 3)["level"], "fail")
        self.assertEqual(by("half:dns_fail", 5)["level"], "fail")
        self.assertEqual(by("half:reg_other_early", 13)["level"], "wait")
        self.assertEqual(by("half:reg_other_late", 13)["level"], "fail")
        self.assertEqual(by("fx:internet_not_in_tunnel", 3)["level"], "fail")
        self.assertEqual(by("fx:myip_wrong", 4)["level"], "fail")
        self.assertEqual(by("fx:bypass_bad", 6)["level"], "fail")
        self.assertEqual(by("fx:el_empty_early", 12)["level"], "wait")


if __name__ == "__main__":
    unittest.main()
