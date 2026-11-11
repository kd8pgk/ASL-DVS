import glob
import importlib.util
import os
import re
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nt_links_")
os.environ["NODETALKER_SUITELOG"] = os.path.join(WORK, "suitelog.jsonl")
os.environ["NODETALKER_SUITELOG_FLAG"] = os.path.join(WORK, "suitelog.on")
os.environ.setdefault("NODETALKER_CONFIG_DIR", os.path.join(WORK, "nt"))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nt = load("nt_links_under_test", os.environ.get("NT_LINKS_FILE") or newest("nodetalker_v[0-9]*.py"))

NODE = "1000"
BRIDGE = "1999"
M17_BRIDGE = "1998"


def fav(mode, num, **kw):
    f = {"mode": mode, "num": num, "label": kw.pop("label", f"{mode} {num}"), "net": ""}
    f.update(kw)
    return f


class Links(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.bad = {}
        self.links = []
        self.links_ok = True
        self.sticky = set()
        self.ini_fails = False
        self.restart_rc = 0
        self.last_tune = None
        self.nc_status = None
        self.m17_now = ""
        self.saved = {}
        fakes = {
            "dvs": self.fake_dvs,
            "ilink": self.fake_ilink,
            "rpt_links": self.fake_links,
            "nc_running": lambda cached=False: False,
            "bridge_nodes": lambda max_age=30.0: {"digital": BRIDGE, "m17": M17_BRIDGE},
            "dvs_path": lambda: "/opt/MMDVM_Bridge/dvswitch.sh",
            "_gateway_up": lambda mode: (True, ""),
            "_systemctl": self.fake_systemctl,
            "_atomic_write": self.fake_write,
            "dash_call": lambda body, timeout=25: None,
            "dashboard_conf": lambda: {"asl_node": "", "port": 8989, "nets": []},
            "main_node": lambda: NODE,
            "perm_links": lambda node: frozenset(),
            "nets_load": lambda: [],
            "fav_load": lambda: [],
            "log_event": lambda *a, **k: None,
            "_m17_present": lambda: True,
            "callsign_now": lambda: ("N0CALL", "set"),
            "m17_lookup": lambda ref, module: ("1.2.3.4", ""),
            "_abinfo_last_tune": lambda: self.last_tune,
            "nc_dvs_current": lambda max_age=5.0: self.nc_status,
            "m17_current": lambda max_age=5.0: self.m17_now,
        }
        for name, fake in fakes.items():
            self.saved[name] = getattr(nt, name)
            setattr(nt, name, fake)
        self.saved_sleep = nt.time.sleep
        nt.time.sleep = lambda s: None
        nt._solo.update(mode="", target="", name="", bridge="")
        nt._dvs_now.update(mode="", dmr="")
        nt._links_good.update(t=-1e9, node="", links=[])
        nt._solo.update(tune="")
        nt._solo_at["t"] = None
        nt._tune_state_cache.update(t=-1e9, key=None, v="")

    def tearDown(self):
        for name, real in self.saved.items():
            setattr(nt, name, real)
        nt.time.sleep = self.saved_sleep

    def fake_dvs(self, sub, arg=None):
        self.calls.append((sub, arg))
        if sub == "mode":
            nt._dvs_now["dmr"] = ""
        if self.bad.get((sub, arg), self.bad.get(sub)):
            return False, "boom"
        return True, ""

    def fake_ilink(self, node, op, peer):
        self.calls.append(("ilink", op, peer))
        if op == 3 and peer not in self.links:
            self.links.append(peer)
        if op in (1, 11) and peer in self.links and peer not in self.sticky:
            self.links.remove(peer)
        return True, ""

    def fake_links(self, node, max_age=2.0):
        return self.links_ok, [{"node": n, "dir": "OUT", "time": "", "state": "ESTABLISHED"} for n in self.links]

    def fake_systemctl(self, *args, **kw):
        self.calls.append(("systemctl",) + args)
        return types.SimpleNamespace(returncode=self.restart_rc if args[0] == "restart" else 0, stdout="", stderr="unit failed")

    def fake_write(self, path, text, mode=0o644):
        if self.ini_fails and path == nt.M17_INI:
            raise OSError("read-only file system")
        self.calls.append(("write", path))

    def test_failed_mode_switch_stops_the_tune(self):
        self.bad["mode"] = True
        r = nt.solo_dvs(fav("P25", "10200"), NODE)
        self.assertFalse(r["ok"])
        self.assertIn("Could not switch DVSwitch to P25", r["error"])
        self.assertNotIn(("tune", "10200"), self.calls)
        self.assertEqual(nt._solo["target"], "")
        self.assertEqual(nt._dvs_now["mode"], "")
        self.bad.clear()
        self.calls.clear()
        self.assertTrue(nt.solo_dvs(fav("P25", "10200"), NODE)["ok"])
        self.assertIn(("mode", "P25"), self.calls)
        self.assertTrue(nt._solo["target"])

    def test_failed_disconnect_keeps_the_tuned_state(self):
        self.assertTrue(nt.solo_dvs(fav("NXDN", "65000"), NODE)["ok"])
        name = nt._solo["name"]
        self.bad[("tune", nt.DVS_DISCONNECT)] = True
        r = nt.tune_disconnect(None)
        self.assertFalse(r["ok"])
        self.assertIn("still tuned", r["error"])
        self.assertEqual(nt._solo["name"], name)
        self.assertIn(BRIDGE, self.links)
        self.bad.clear()
        r = nt.tune_disconnect(None)
        self.assertTrue(r["ok"])
        self.assertEqual(nt._solo["target"], "")
        self.assertNotIn(BRIDGE, self.links)

    def test_a_new_tune_goes_ahead_when_the_old_teardown_fails(self):
        self.assertTrue(nt.solo_dvs(fav("NXDN", "65000"), NODE)["ok"])
        self.bad[("tune", nt.DVS_DISCONNECT)] = True
        self.assertTrue(nt.solo_dvs(fav("NXDN", "65001"), NODE)["ok"])
        self.assertIn("65001", nt._solo["name"])

    def test_m17_disconnect_failures_are_reported(self):
        f = fav("M17", "M17-USA", module="A", ip="")
        self.assertTrue(nt.solo_m17(f, NODE)["ok"])
        self.ini_fails = True
        r = nt.tune_disconnect(None)
        self.assertFalse(r["ok"])
        self.assertIn("could not write", r["error"])
        self.assertEqual(nt._solo["mode"], "M17")
        self.ini_fails = False
        self.restart_rc = 1
        r = nt.tune_disconnect(None)
        self.assertFalse(r["ok"])
        self.assertIn("did not restart", r["error"])
        self.restart_rc = 0
        self.assertTrue(nt.tune_disconnect(None)["ok"])
        self.assertEqual(nt._solo["mode"], "")

    def test_a_link_asterisk_keeps_is_reported(self):
        self.links = ["2000", "2001"]
        self.sticky = {"2001"}
        self.assertEqual(nt.drop_peers(NODE, ["2000", "2001"]), ["2001"])
        r = nt.disconnect_links()
        self.assertFalse(r["ok"])
        self.assertIn("still lists 2001", r["error"])
        self.sticky = set()
        self.links = ["2000", "2001"]
        r = nt.disconnect_links()
        self.assertTrue(r["ok"])
        self.assertIn("2000, 2001", r["message"])
        self.assertEqual(self.links, [])

    def test_one_node_disconnect_is_checked(self):
        self.links = ["2000"]
        self.sticky = {"2000"}
        r = nt.tune_disconnect({"mode": "ASL", "num": "2000"})
        self.assertFalse(r["ok"])
        self.sticky = set()
        self.assertTrue(nt.tune_disconnect({"mode": "ASL", "num": "2000"})["ok"])

    def test_drop_check_gives_way_when_the_list_is_not_readable(self):
        self.links = ["2000"]
        self.links_ok = False
        self.assertEqual(nt.drop_peers(NODE, ["2000"]), [])

    def test_one_missed_link_query_keeps_the_last_list(self):
        good = [{"node": "2000", "dir": "OUT", "time": "", "state": "ESTABLISHED"}]
        self.assertEqual(nt.links_steady(NODE, True, good), (True, good))
        self.assertEqual(nt.links_steady(NODE, False, []), (True, good))
        self.assertEqual(nt.links_steady("1001", False, []), (False, []))
        nt._links_good["t"] -= nt.LINKS_HOLD_SEC + 1
        self.assertEqual(nt.links_steady(NODE, False, []), (False, []))

    def test_disconnect_all_forgets_the_mode_and_network(self):
        with open(nt.__file__, encoding="utf-8") as fh:
            src = fh.read()
        body = src.split("def _reset_run():", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('_dvs_now.update(mode="", dmr="")', body)

    def fresh(self):
        nt._tune_state_cache["t"] = -1e9

    def late(self):
        nt._solo_at["t"] -= nt.TUNE_GRACE_SEC + 1
        self.fresh()

    def test_solo_tune_is_pending_then_confirmed(self):
        self.assertEqual(nt.solo_tune_state(), "")
        self.assertTrue(nt.solo_dvs(fav("P25", "10200"), NODE)["ok"])
        self.assertEqual(nt.solo_tune_state(), "pending")
        self.last_tune = "10200"
        self.assertEqual(nt.solo_tune_state(), "pending")
        self.fresh()
        self.assertEqual(nt.solo_tune_state(), "confirmed")

    def test_solo_tune_that_never_confirms_is_marked(self):
        self.assertTrue(nt.solo_dvs(fav("NXDN", "65000"), NODE)["ok"])
        self.last_tune = "disconnect"
        self.late()
        self.assertEqual(nt.solo_tune_state(), "unconfirmed")
        self.assertEqual(nt.tune_state_now(False), "unconfirmed")
        self.last_tune = "65000"
        self.fresh()
        self.assertEqual(nt.solo_tune_state(), "confirmed")
        self.last_tune = None
        self.fresh()
        self.assertEqual(nt.solo_tune_state(), "unconfirmed")

    def test_solo_dstar_keeps_the_normal_look(self):
        self.assertTrue(nt.solo_dvs(fav("DSTAR", "REF001CL"), NODE)["ok"])
        self.last_tune = "other"
        self.late()
        self.assertEqual(nt.solo_tune_state(), "sent")

    def test_solo_m17_is_checked_against_its_ini(self):
        real_ini, real_active = nt.M17_INI, nt._svc_active
        nt.M17_INI = os.path.join(WORK, "USRP2M17.ini")
        active = [True]
        nt._svc_active = lambda svc: active[0]
        try:
            self.assertTrue(nt.solo_m17(fav("M17", "M17-USA", module="A", ip=""), NODE)["ok"])
            with open(nt.M17_INI, "w", encoding="utf-8") as fh:
                fh.write(nt._m17_ini_text("N0CALL", "M17-USA", "1.2.3.4", "A"))
            self.fresh()
            self.assertEqual(nt.solo_tune_state(), "confirmed")
            active[0] = False
            self.late()
            self.assertEqual(nt.solo_tune_state(), "unconfirmed")
        finally:
            nt.M17_INI, nt._svc_active = real_ini, real_active

    def test_state_saved_by_an_older_version_has_no_verdict(self):
        nt._solo.update(mode="P25", target="P25:10200", name="P25 10200", bridge=BRIDGE, tune="")
        self.assertEqual(nt.solo_tune_state(), "")

    def test_node_controller_verdict_is_passed_on(self):
        self.nc_status = {"page": "DMR", "fav": "3100", "server": "TGIF", "address": "", "state": "unconfirmed", "m17_state": ""}
        self.assertEqual(nt.tune_state_now(True), "unconfirmed")
        self.nc_status = {"page": "DMR", "fav": "3100", "server": "TGIF", "address": ""}
        self.assertEqual(nt.tune_state_now(True), "")
        self.nc_status = {"page": "DMR", "fav": "", "state": "confirmed"}
        self.assertEqual(nt.tune_state_now(True), "")
        self.nc_status = {"page": "M17", "fav": "", "state": "", "m17_state": "confirmed"}
        self.m17_now = "M17-USA|A"
        self.assertEqual(nt.tune_state_now(True), "confirmed")
        self.nc_status = {"page": "DMR", "fav": "3100", "state": "bogus"}
        self.m17_now = ""
        self.assertEqual(nt.tune_state_now(True), "")
        self.nc_status = None
        self.assertEqual(nt.tune_state_now(True), "")

    def test_link_line_marks_an_unconfirmed_talkgroup(self):
        self.assertTrue(nt.solo_dvs(fav("P25", "10200", label="North America"), NODE)["ok"])
        links = self.fake_links(NODE)[1]
        plain = nt.live_link(links, True, False, [])
        marked = nt.live_link(links, True, False, [], True)
        self.assertFalse(plain["label"].endswith("?"))
        self.assertEqual(marked["label"], plain["label"] + " ?")

    def test_page_marks_the_tuned_line(self):
        with open(nt.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("d.tuned_state === 'unconfirmed'", src)

    def test_node_talker_outwaits_node_controller(self):
        self.assertGreaterEqual(nt.NC_TUNE_TIMEOUT, 200)


if __name__ == "__main__":
    unittest.main(verbosity=1)
