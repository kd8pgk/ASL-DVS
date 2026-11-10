import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nc_links_")
os.environ["NODECONTROL_CONFIG_DIR"] = os.path.join(WORK, "nc")


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


nc = load("nc_links_under_test", newest("nodecontrol_v[0-9]*.py"))
ncp = load("ncp_links_under_test", newest("nodecontrol_pi02w_v[0-9]*.py"))

TIMEOUT = "__timeout__"


class _Links:
    mod = None

    def setUp(self):
        m = self.mod
        self.calls = []
        self.fail = {}
        self.linked = []
        self.gateway_ok = True
        self.saved = {}
        fakes = {
            "_dvs": self.fake_dvs,
            "_asterisk": lambda cmd: self.calls.append(("ast", cmd)),
            "_query_linked_nodes": lambda timeout=3: list(self.linked),
            "_svc_restart": lambda name: self.calls.append(("restart", name)),
            "_gateway_svc_enter": lambda page: self.gateway_ok,
            "_gateway_svc_leave": lambda prev, nxt: None,
            "_cpuweight_apply_for_page": lambda page: None,
            "_write_m17_ini": self.fake_ini,
            "_phone_all_nodes": lambda: set(),
            "_phone_on": lambda: False,
            "_phone_hangup_all": lambda: None,
            "_nodelisten_keep_set": lambda: set(),
            "_nodelisten_tx_relink": lambda: None,
            "_log_teardown_survivors_async": lambda what: None,
            "_read_perm_links": lambda: frozenset(),
        }
        for name, fake in fakes.items():
            self.saved[name] = getattr(m, name)
            setattr(m, name, fake)
        self.saved_sleep = m.time.sleep
        m.time.sleep = lambda s: None
        m.set_state(has_asl=True, has_dvs=True, has_m17=True, page="ASL", status="",
                    current_fav=None, current_fav_node=None, echo_fav=None,
                    linked_node=None, current_dvs_mode="")

    def tearDown(self):
        for name, real in self.saved.items():
            setattr(self.mod, name, real)
        self.mod.time.sleep = self.saved_sleep

    def fake_dvs(self, sub, arg=None):
        self.calls.append((sub, arg))
        if sub == "mode":
            self.mod._invalidate_dmr_net_tune()
        hit = self.fail.get((sub, arg), self.fail.get(sub))
        if hit == TIMEOUT:
            return False, self.mod._DVS_TIMEOUT
        if hit:
            return False, "boom"
        return True, ""

    def fake_ini(self, content):
        self.calls.append(("m17ini", "DISCONNECTED" in content))
        return True, ""

    def st(self):
        return self.mod.get_state()

    def dvs_calls(self):
        return [c for c in self.calls if c[0] in ("mode", "tune")]

    def test_failed_tune_clears_the_stored_talkgroup(self):
        m = self.mod
        self.assertEqual(m._enter_page("YSF"), "")
        self.assertTrue(m.action_tune("YSF", "1.2.3.4:42000", "A")[0])
        self.assertEqual(self.st().current_fav, "1.2.3.4:42000")
        self.fail[("tune", "5.6.7.8:42000")] = True
        ok, msg = m.action_tune("YSF", "5.6.7.8:42000", "B")
        self.assertFalse(ok)
        self.assertIn("failed", msg)
        self.assertIsNone(self.st().current_fav)
        self.assertEqual(self.st().page, "YSF")

    def test_tune_timeout_clears_and_says_so(self):
        m = self.mod
        m._enter_page("P25")
        m.action_tune("P25", "10200", "NA")
        self.fail[("tune", "10100")] = TIMEOUT
        ok, msg = m.action_tune("P25", "10100", "WW")
        self.assertFalse(ok)
        self.assertIn("taking longer", msg)
        self.assertIsNone(self.st().current_fav)

    def test_failed_mode_on_tab_entry_is_retried_by_the_tune(self):
        m = self.mod
        self.fail["mode"] = True
        self.assertEqual(m._enter_page("P25"), "")
        self.assertEqual(self.st().current_dvs_mode, "")
        self.fail.clear()
        self.calls.clear()
        self.assertTrue(m.action_tune("P25", "10200", "NA")[0])
        self.assertIn(("mode", "P25"), self.calls)
        self.assertEqual(self.st().current_dvs_mode, "P25")

    def test_failed_mode_at_tune_time_fails_the_tune(self):
        m = self.mod
        m._enter_page("DMR")
        m.action_tune("DMR", "3100", "USA")
        m.set_state(page="YSF", current_dvs_mode="DMR")
        self.fail["mode"] = True
        self.calls.clear()
        ok, msg = m.action_tune("YSF", "1.2.3.4:42000", "A")
        self.assertFalse(ok)
        self.assertIn("Mode switch to YSF", msg)
        self.assertNotIn(("tune", "1.2.3.4:42000"), self.calls)
        self.assertIsNone(self.st().current_fav)
        self.assertEqual(self.st().current_dvs_mode, "")

    def test_gateway_that_does_not_start_fails_the_tab_switch(self):
        m = self.mod
        self.gateway_ok = False
        ok, msg = m.action_switch_tab("YSF")
        self.assertFalse(ok)
        self.assertIn("did not", msg)
        self.assertEqual(self.dvs_calls(), [])
        ok, _ = m.action_tune("P25", "10200", "NA")
        self.assertFalse(ok)
        self.gateway_ok = True
        self.assertEqual(m.action_switch_tab("YSF"), (True, m._PAGE_ENTER["YSF"]["msg"]))

    def test_failed_disconnect_keeps_the_talkgroup(self):
        m = self.mod
        m._enter_page("NXDN")
        m.action_tune("NXDN", "65000", "WW")
        self.fail[("tune", m.TG_DISCONNECT)] = True
        ok, msg = m.action_tune("NXDN", m.TG_DISCONNECT, "")
        self.assertFalse(ok)
        self.assertEqual(self.st().current_fav, "65000")
        self.fail.clear()
        self.assertTrue(m.action_tune("NXDN", m.TG_DISCONNECT, "")[0])
        self.assertIsNone(self.st().current_fav)

    def test_dstar_and_xlx_failures(self):
        m = self.mod
        self.assertTrue(m.action_dstar_connect("REF001", "C", "REF001 C")[0])
        fav = self.st().current_fav
        self.assertEqual(self.st().current_dvs_mode, "DSTAR")
        self.fail[("tune", m.TG_DISCONNECT)] = TIMEOUT
        ok, msg = m.action_dstar_disconnect()
        self.assertFalse(ok)
        self.assertEqual(self.st().current_fav, fav)
        self.fail.clear()
        self.fail[("tune", m._dstar_link_str("REF030", "C"))] = True
        self.assertFalse(m.action_dstar_connect("REF030", "C", "REF030 C")[0])
        self.assertIsNone(self.st().current_fav)
        self.fail.clear()
        self.assertTrue(m.action_xlx_connect("XLX307 D", "XLX307", "D")[0])
        self.fail["mode"] = True
        self.assertFalse(m.action_xlx_connect("XLX334 A", "XLX334", "A")[0])
        self.assertIsNone(self.st().current_fav)
        self.fail.clear()
        self.assertTrue(m.action_xlx_connect("XLX307 D", "XLX307", "D")[0])
        self.assertTrue(m.action_xlx_disconnect()[0])
        self.assertIsNone(self.st().current_fav)

    def test_failed_dmr_network_switch_clears_the_talkgroup(self):
        m = self.mod
        m.set_state(dmr_servers=[{"name": "TGIF", "password": "pw", "address": "tgif.network:62031", "net_url": ""},
                                 {"name": "Other", "password": "pw", "address": "other.example:62031", "net_url": ""}])
        m._enter_page("DMR")
        self.assertTrue(m.action_switch_dmr_server("TGIF")[0])
        m.action_tune("DMR", "3100", "USA")
        self.assertEqual(self.st().current_fav, "3100")
        self.fail[("tune", "pw@other.example:62031")] = True
        self.assertFalse(m.action_switch_dmr_server("Other")[0])
        self.assertIsNone(self.st().current_fav)
        self.assertEqual(self.st().active_dmr_server, "TGIF")

    def test_disconnect_all_resets_m17_and_clears_first(self):
        m = self.mod
        m._enter_page("M17")
        self.assertTrue(m.action_m17_connect("R", "M17-USA", "1.2.3.4", "A")[0])
        seen = []
        real = m._hard_restart_stack
        m._hard_restart_stack = lambda st: seen.append(self.st().current_fav)
        try:
            self.calls.clear()
            m.action_disconnect_all()
        finally:
            m._hard_restart_stack = real
        self.assertEqual(seen, [None])
        self.assertIn(("m17ini", True), self.calls)
        self.assertIn(("restart", m.M17_SERVICE), self.calls)
        m._enter_page("DMR")
        self.calls.clear()
        m._hard_restart_stack = lambda st: None
        try:
            m.action_disconnect_all()
        finally:
            m._hard_restart_stack = real
        self.assertNotIn(("restart", m.M17_SERVICE), self.calls)

    def test_asl_disconnect_from_the_page_drops_every_link(self):
        m = self.mod
        self.linked = ["2000", "2001", "2002"]
        m.set_state(page="ASL", current_fav="2000", current_fav_node="2000", linked_node="2000")
        self.assertTrue(m.action_asl_disconnect_current(drop_all=True)[0])
        dropped = [c[1].split()[-1] for c in self.calls if c[0] == "ast" and " ilink 1 " in c[1]]
        self.assertEqual(dropped, ["2000", "2001", "2002"])
        self.assertIsNone(self.st().current_fav)
        self.assertIsNone(self.st().linked_node)

    def test_asl_disconnect_of_one_node_leaves_the_rest(self):
        m = self.mod
        self.linked = ["2000", "2001", "2002"]
        m.set_state(page="ASL", current_fav="2001", current_fav_node="2001", linked_node="2001")
        self.assertTrue(m.action_asl_disconnect_current()[0])
        dropped = [c[1].split()[-1] for c in self.calls if c[0] == "ast" and " ilink 1 " in c[1]]
        self.assertEqual(dropped, ["2001"])

    def test_asl_and_echo_connect_enter_their_tab_first(self):
        m = self.mod
        m._enter_page("DMR")
        m.action_tune("DMR", "3100", "USA")
        self.calls.clear()
        self.assertTrue(m.action_asl_connect("2000", "X")[0])
        self.assertIn(("tune", m.TG_DISCONNECT), self.calls)
        self.assertEqual(self.st().page, "ASL")
        self.assertEqual(self.st().current_fav, "2000")
        m._enter_page("M17")
        m.action_m17_connect("R", "M17-USA", "1.2.3.4", "A")
        self.calls.clear()
        self.assertTrue(m.action_echo_connect("123456", "E")[0])
        self.assertIn(("m17ini", True), self.calls)
        self.assertEqual(self.st().page, "ECHO")
        self.assertEqual(self.st().echo_fav, "123456")
        self.calls.clear()
        self.assertTrue(m.action_echo_connect("654321", "F")[0])
        self.assertEqual(self.dvs_calls(), [])

    def test_page_waits_longer_than_the_server(self):
        with open(self.mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        ms = int(re.search(r"const DVS_MODE_TUNE_MS = (\d+);", src).group(1))
        server = (2 * self.mod._DVS_TUNE_TIMEOUT_SEC + self.mod._DVS_MODE_TIMEOUT_SEC) * 1000
        self.assertGreater(ms, server)


class FullBuild(_Links, unittest.TestCase):
    mod = nc


class Pi02wBuild(_Links, unittest.TestCase):
    mod = ncp


if __name__ == "__main__":
    unittest.main(verbosity=1)
