import glob
import importlib.util
import os
import re
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nr_links_")
os.environ["NODERECORDER_CONFIG_DIR"] = os.path.join(WORK, "conf")
os.environ["NODERECORDER_RPT_CONF"] = os.path.join(WORK, "rpt.conf")
os.makedirs(os.environ["NODERECORDER_CONFIG_DIR"], exist_ok=True)
with open(os.environ["NODERECORDER_RPT_CONF"], "w") as fh:
    fh.write("[general]\n")


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("nr_links_under_test", newest("noderecorder_v[0-9]*.py"))
nr = importlib.util.module_from_spec(spec)
sys.modules["nr_links_under_test"] = nr
spec.loader.exec_module(nr)

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
        self.logged = []
        self.saved = {}
        fakes = {
            "_svc_active": lambda svc: True,
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
            "log_event": lambda msg, kind="info": self.logged.append(msg),
            "_m17_present": lambda: True,
            "callsign_now": lambda: ("N0CALL", "set"),
            "m17_lookup": lambda ref, module: ("1.2.3.4", ""),
            "nc_dvs_current": lambda max_age=5.0: None,
            "m17_current": lambda max_age=5.0: "",
        }
        for name, fake in fakes.items():
            self.saved[name] = getattr(nr, name)
            setattr(nr, name, fake)
        self.saved_sleep = nr.time.sleep
        nr.time.sleep = lambda s: None
        nr._solo.update(mode="", target="", name="", bridge="", op="")
        nr._dvs_now.update(mode="", dmr="")

    def tearDown(self):
        for name, real in self.saved.items():
            setattr(nr, name, real)
        nr.time.sleep = self.saved_sleep

    def fake_dvs(self, sub, arg=None):
        self.calls.append((sub, arg))
        if sub == "mode":
            nr._dvs_now["dmr"] = ""
        if self.bad.get((sub, arg), self.bad.get(sub)):
            return False, "boom"
        return True, ""

    def fake_ilink(self, node, op, peer):
        self.calls.append(("ilink", op, peer))
        if op in (3, 8) and peer not in self.links:
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
        if self.ini_fails and path == nr.M17_INI:
            raise OSError("read-only file system")
        self.calls.append(("write", path))

    def test_failed_mode_switch_stops_the_tune(self):
        self.bad["mode"] = True
        r = nr.solo_dvs(fav("P25", "10200"), NODE)
        self.assertFalse(r["ok"])
        self.assertIn("Could not switch DVSwitch to P25", r["error"])
        self.assertNotIn(("tune", "10200"), self.calls)
        self.assertEqual(nr._solo["target"], "")
        self.assertEqual(nr._dvs_now["mode"], "")
        self.bad.clear()
        self.calls.clear()
        self.assertTrue(nr.solo_dvs(fav("P25", "10200"), NODE)["ok"])
        self.assertIn(("mode", "P25"), self.calls)
        self.assertTrue(nr._solo["target"])

    def test_failed_disconnect_keeps_the_tuned_state(self):
        self.assertTrue(nr.solo_dvs(fav("NXDN", "65000"), NODE)["ok"])
        name = nr._solo["name"]
        self.bad[("tune", nr.DVS_DISCONNECT)] = True
        r = nr.tune_disconnect(None)
        self.assertFalse(r["ok"])
        self.assertIn("still tuned", r["error"])
        self.assertEqual(nr._solo["name"], name)
        self.assertIn(BRIDGE, self.links)
        self.bad.clear()
        r = nr.tune_disconnect(None)
        self.assertTrue(r["ok"])
        self.assertEqual(nr._solo["target"], "")
        self.assertNotIn(BRIDGE, self.links)

    def test_a_new_tune_goes_ahead_when_the_old_teardown_fails(self):
        self.assertTrue(nr.solo_dvs(fav("NXDN", "65000"), NODE)["ok"])
        self.bad[("tune", nr.DVS_DISCONNECT)] = True
        self.assertTrue(nr.solo_dvs(fav("NXDN", "65001"), NODE)["ok"])
        self.assertIn("65001", nr._solo["name"])

    def test_m17_disconnect_failures_are_reported(self):
        f = fav("M17", "M17-USA", module="A", ip="")
        self.assertTrue(nr.solo_m17(f, NODE)["ok"])
        self.ini_fails = True
        r = nr.tune_disconnect(None)
        self.assertFalse(r["ok"])
        self.assertIn("could not write", r["error"])
        self.assertEqual(nr._solo["mode"], "M17")
        self.ini_fails = False
        self.restart_rc = 1
        r = nr.tune_disconnect(None)
        self.assertFalse(r["ok"])
        self.assertIn("did not restart", r["error"])
        self.restart_rc = 0
        self.assertTrue(nr.tune_disconnect(None)["ok"])
        self.assertEqual(nr._solo["mode"], "")

    def test_a_link_asterisk_keeps_is_reported(self):
        self.links = ["2000", "2001"]
        self.sticky = {"2001"}
        self.assertEqual(nr.drop_peers(NODE, ["2000", "2001"]), ["2001"])
        r = nr.disconnect_links()
        self.assertFalse(r["ok"])
        self.assertIn("still lists 2001", r["error"])
        self.sticky = set()
        self.links = ["2000", "2001"]
        r = nr.disconnect_links()
        self.assertTrue(r["ok"])
        self.assertIn("2000, 2001", r["message"])
        self.assertEqual(self.links, [])

    def test_one_node_disconnect_is_checked(self):
        self.links = ["2000"]
        self.sticky = {"2000"}
        r = nr.tune_disconnect({"mode": "ASL", "num": "2000"})
        self.assertFalse(r["ok"])
        self.assertIn("still lists 2000", r["error"])
        self.sticky = set()
        self.assertTrue(nr.tune_disconnect({"mode": "ASL", "num": "2000"})["ok"])

    def test_one_favorite_disconnect_is_checked(self):
        self.links = ["2000"]
        self.sticky = {"2000"}
        nr.fav_load = lambda: [fav("ASL", "2000")]
        r = nr.fav_disconnect(0)
        self.assertFalse(r["ok"])
        self.assertIn("still lists 2000", r["error"])

    def test_drop_check_gives_way_when_the_list_is_not_readable(self):
        self.links = ["2000"]
        self.links_ok = False
        self.assertEqual(nr.drop_peers(NODE, ["2000"]), [])

    def test_disconnect_all_forgets_the_mode_and_network(self):
        with open(nr.__file__, encoding="utf-8") as fh:
            src = fh.read()
        body = src.split("def _reset_run():", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('_dvs_now.update(mode="", dmr="")', body)

    def test_the_link_choice_still_reaches_the_bridge_link(self):
        self.assertTrue(nr.solo_dvs(fav("NXDN", "65000"), NODE, op=8)["ok"])
        self.assertIn(("ilink", 8, BRIDGE), self.calls)
        self.assertNotIn(("ilink", 3, BRIDGE), self.calls)
        self.assertEqual(str(nr._solo["op"]), "8")

    def link_script(self, script):
        seq = iter(script)
        last = [script[0]]

        def links(node, max_age=2.0):
            try:
                last[0] = next(seq)
            except StopIteration:
                pass
            ok, state = last[0]
            return ok, ([] if state is None else [{"node": "55555", "dir": "OUT", "time": "", "state": state}])
        nr.rpt_links = links

    def test_link_wait_is_up_as_soon_as_the_node_is_established(self):
        self.link_script([(True, None), (True, "CONNECTING"), (True, "ESTABLISHED")])
        self.assertEqual(nr.wait_link(NODE, "55555"), "up")

    def test_link_wait_fails_early_when_a_connecting_node_drops(self):
        calls = [0]
        self.link_script([(True, "CONNECTING"), (True, None)])
        real = nr.rpt_links

        def counted(node, max_age=2.0):
            calls[0] += 1
            return real(node, max_age)
        nr.rpt_links = counted
        self.assertEqual(nr.wait_link(NODE, "55555"), "down")
        self.assertEqual(calls[0], 2)

    def test_link_wait_gives_up_on_an_absent_node_after_five_seconds(self):
        calls = [0]

        def absent(node, max_age=2.0):
            calls[0] += 1
            return True, []
        nr.rpt_links = absent
        self.assertEqual(nr.wait_link(NODE, "55555"), "down")
        self.assertEqual(calls[0], nr.LINK_WAIT_MIN_STEPS)

    def test_link_wait_keeps_trying_while_the_node_is_connecting(self):
        self.link_script([(True, "CONNECTING")])
        self.assertEqual(nr.wait_link(NODE, "55555"), "connecting")

    def test_link_wait_is_unknown_when_asterisk_never_answers(self):
        self.link_script([(False, None)])
        self.assertEqual(nr.wait_link(NODE, "55555"), "unknown")

    def test_the_waits_match_node_talker_and_node_controller(self):
        self.assertEqual((nr.LINK_WAIT_SEC, nr.LINK_WAIT_STEP_SEC, nr.LINK_WAIT_MIN_STEPS), (10, 0.5, 10))
        self.assertEqual((nr.DROP_CHECK_TRIES, nr.DROP_CHECK_STEP_SEC), (6, 0.5))

    def test_ulaw_matches_node_controller_for_every_sample(self):
        def reference(s):
            sign = 0x80 if s < 0 else 0
            if s < 0:
                s = -s
            s = min(s, 32635) + 0x84
            exponent = min(7, max(0, s.bit_length() - 8))
            return ~(sign | (exponent << 4) | ((s >> (exponent + 3)) & 0x0F)) & 0xFF
        for i in range(-32768, 32768):
            self.assertEqual(nr._ulaw_byte(i), reference(i))

    def test_the_recorder_outwaits_node_controller(self):
        self.assertGreaterEqual(nr.NC_TUNE_TIMEOUT, 200)


if __name__ == "__main__":
    unittest.main(verbosity=1)
