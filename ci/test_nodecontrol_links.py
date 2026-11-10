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
        self.failing = {}
        self.linked = []
        self.gateway_ok = True
        self.link_result = "linked"
        self.ab = None
        self.svc = {}
        self.saved = {}
        fakes = {
            "_dvs": self.fake_dvs,
            "_asterisk": lambda cmd: self.calls.append(("ast", cmd)),
            "_query_linked_nodes": lambda timeout=3: list(self.linked),
            "_link_wait": lambda node: self.link_result,
            "_nodelisten_skip_set": lambda: set(),
            "_read_abinfo": lambda: self.ab,
            "_svc_public": lambda: dict(self.svc),
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
                    linked_node=None, linked_nodes=frozenset(), link_known=True,
                    current_dvs_mode="")
        m._fav_gone_polls = 0
        m._tune_seen = ("", "", 0.0)
        m.set_state(tune_state="", tune_expect=("", ""))

    def tearDown(self):
        for name, real in self.saved.items():
            setattr(self.mod, name, real)
        self.mod.time.sleep = self.saved_sleep

    def fake_dvs(self, sub, arg=None):
        self.calls.append((sub, arg))
        if sub == "mode":
            self.mod._invalidate_dmr_net_tune()
        hit = self.failing.get((sub, arg), self.failing.get(sub))
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
        self.failing[("tune", "5.6.7.8:42000")] = True
        ok, msg = m.action_tune("YSF", "5.6.7.8:42000", "B")
        self.assertFalse(ok)
        self.assertIn("failed", msg)
        self.assertIsNone(self.st().current_fav)
        self.assertEqual(self.st().page, "YSF")

    def test_tune_timeout_clears_and_says_so(self):
        m = self.mod
        m._enter_page("P25")
        m.action_tune("P25", "10200", "NA")
        self.failing[("tune", "10100")] = TIMEOUT
        ok, msg = m.action_tune("P25", "10100", "WW")
        self.assertFalse(ok)
        self.assertIn("taking longer", msg)
        self.assertIsNone(self.st().current_fav)

    def test_failed_mode_on_tab_entry_is_retried_by_the_tune(self):
        m = self.mod
        self.failing["mode"] = True
        self.assertEqual(m._enter_page("P25"), "")
        self.assertEqual(self.st().current_dvs_mode, "")
        self.failing.clear()
        self.calls.clear()
        self.assertTrue(m.action_tune("P25", "10200", "NA")[0])
        self.assertIn(("mode", "P25"), self.calls)
        self.assertEqual(self.st().current_dvs_mode, "P25")

    def test_failed_mode_at_tune_time_fails_the_tune(self):
        m = self.mod
        m._enter_page("DMR")
        m.action_tune("DMR", "3100", "USA")
        m.set_state(page="YSF", current_dvs_mode="DMR")
        self.failing["mode"] = True
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
        self.failing[("tune", m.TG_DISCONNECT)] = True
        ok, msg = m.action_tune("NXDN", m.TG_DISCONNECT, "")
        self.assertFalse(ok)
        self.assertEqual(self.st().current_fav, "65000")
        self.failing.clear()
        self.assertTrue(m.action_tune("NXDN", m.TG_DISCONNECT, "")[0])
        self.assertIsNone(self.st().current_fav)

    def test_dstar_and_xlx_failures(self):
        m = self.mod
        self.assertTrue(m.action_dstar_connect("REF001", "C", "REF001 C")[0])
        fav = self.st().current_fav
        self.assertEqual(self.st().current_dvs_mode, "DSTAR")
        self.failing[("tune", m.TG_DISCONNECT)] = TIMEOUT
        ok, msg = m.action_dstar_disconnect()
        self.assertFalse(ok)
        self.assertEqual(self.st().current_fav, fav)
        self.failing.clear()
        self.failing[("tune", m._dstar_link_str("REF030", "C"))] = True
        self.assertFalse(m.action_dstar_connect("REF030", "C", "REF030 C")[0])
        self.assertIsNone(self.st().current_fav)
        self.failing.clear()
        self.assertTrue(m.action_xlx_connect("XLX307 D", "XLX307", "D")[0])
        self.failing["mode"] = True
        self.assertFalse(m.action_xlx_connect("XLX334 A", "XLX334", "A")[0])
        self.assertIsNone(self.st().current_fav)
        self.failing.clear()
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
        self.failing[("tune", "pw@other.example:62031")] = True
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

    def test_asl_connect_that_does_not_link_is_not_stored(self):
        m = self.mod
        self.link_result = "failed"
        ok, msg = m.action_asl_connect("2000", "X")
        self.assertFalse(ok)
        self.assertIn("did not link", msg)
        self.assertIsNone(self.st().current_fav)
        self.assertIsNone(m.build_status()["current_fav"])

    def test_asl_connect_that_links_shows_at_once(self):
        m = self.mod
        self.assertEqual(m.action_asl_connect("2000", "X"), (True, "Connected X (2000)"))
        self.assertEqual(m.build_status()["current_fav"], "2000")
        self.assertEqual(m.action_get_keyed()["linked_node"], "2000")

    def test_asl_connect_still_connecting_is_kept_but_not_shown(self):
        m = self.mod
        self.link_result = "connecting"
        ok, msg = m.action_asl_connect("2000", "X")
        self.assertFalse(ok)
        self.assertIn("not answered", msg)
        self.assertEqual(self.st().current_fav, "2000")
        self.assertIsNone(m.build_status()["current_fav"])

    def test_connect_with_asterisk_silent_is_sent_unchecked(self):
        m = self.mod
        self.link_result = "unknown"
        ok, msg = m.action_echo_connect("123456", "E")
        self.assertTrue(ok)
        self.assertIn("could not be checked", msg)
        self.assertEqual(self.st().echo_fav, "123456")

    def test_echo_connect_failure_and_success(self):
        m = self.mod
        self.link_result = "failed"
        ok, msg = m.action_echo_connect("123456", "E")
        self.assertFalse(ok)
        self.assertIsNone(self.st().echo_fav)
        self.link_result = "linked"
        self.assertTrue(m.action_echo_connect("123456", "E")[0])
        self.assertEqual(m.build_status()["echo_fav"], "123456")
        self.assertEqual(m.action_get_keyed()["echo_node"], "123456")
        self.assertTrue(m.action_echo_disconnect()[0])
        self.assertIsNone(m.build_status()["echo_fav"])

    def test_link_wait_reads_the_link_list(self):
        m = self.mod
        wait = self.saved["_link_wait"]
        real = m._link_states

        def run(seq):
            it = iter(seq)
            last = [seq[-1]]
            m._link_states = lambda: next(it, last[0])
            try:
                return wait("2000")
            finally:
                m._link_states = real

        self.assertEqual(run([{}, {"2000": "C"}, {"2000": "T"}]), "linked")
        self.assertEqual(run([{"2000": "R"}]), "linked")
        self.assertEqual(run([{"2000": "C"}, {}]), "failed")
        self.assertEqual(run([{"2001": "T"}]), "failed")
        self.assertEqual(run([{"2000": "C"}]), "connecting")
        self.assertEqual(run([None]), "unknown")
        self.assertEqual(run([None, None, {"2000": "T"}]), "linked")

    def test_a_dropped_link_is_cleared_after_two_polls(self):
        m = self.mod
        m.action_asl_connect("2000", "X")
        m._fav_link_check(frozenset({"2000"}))
        m._fav_link_check(frozenset())
        self.assertEqual(self.st().current_fav, "2000")
        m._fav_link_check(frozenset({"2000"}))
        m._fav_link_check(frozenset())
        self.assertEqual(self.st().current_fav, "2000")
        m._fav_link_check(frozenset())
        self.assertIsNone(self.st().current_fav)
        self.assertIsNone(self.st().current_fav_node)
        m.action_echo_connect("123456", "E")
        m._fav_link_check(frozenset({"3123456"}))
        self.assertEqual(self.st().echo_fav, "123456")
        m._fav_link_check(frozenset())
        m._fav_link_check(frozenset())
        self.assertIsNone(self.st().echo_fav)

    def test_a_talkgroup_is_not_touched_by_the_link_check(self):
        m = self.mod
        m._enter_page("DMR")
        m.action_tune("DMR", "3100", "USA")
        for _ in range(4):
            m._fav_link_check(frozenset())
        self.assertEqual(self.st().current_fav, "3100")

    def test_the_shown_link_is_the_real_one(self):
        m = self.mod
        m.set_state(page="ASL", current_fav="2000", current_fav_node="2000",
                    linked_node="2001", linked_nodes=frozenset({"2001"}))
        self.assertEqual(m.build_status()["current_fav"], "2001")
        m.set_state(linked_nodes=frozenset({"2000", "2001"}))
        self.assertEqual(m.build_status()["current_fav"], "2000")
        m.set_state(linked_node=None, linked_nodes=frozenset())
        self.assertIsNone(m.build_status()["current_fav"])
        m.set_state(page="ECHO", current_fav=None, echo_fav="123456",
                    linked_nodes=frozenset({"3000099", "2001"}))
        self.assertEqual(m.build_status()["echo_fav"], "99")
        m.set_state(linked_nodes=frozenset({"2001"}))
        self.assertIsNone(m.build_status()["echo_fav"])
        m.set_state(page="DMR", current_fav="3100", echo_fav=None)
        self.assertEqual(m.build_status()["current_fav"], "3100")

    def test_unknown_link_state_is_reported(self):
        m = self.mod
        m.set_state(page="ASL", current_fav="2000", current_fav_node="2000",
                    linked_node=None, linked_nodes=frozenset(), link_known=False)
        s = m.build_status()
        self.assertIs(s["link_known"], False)
        self.assertIsNone(s["current_fav"])
        self.assertIs(m.action_get_keyed()["link_known"], False)
        self.assertEqual(self.st().current_fav, "2000")

    def test_poll_reads_connected_and_connecting_links(self):
        m = self.mod
        real = m.ami_command
        out = "RPT_RXKEYED=0\nRPT_ALINKS=3,2000TU,2001CU,1999TU\n"
        m.ami_command = lambda *a, **k: (out, True)
        m._cfg.bridge_nodes[0] = "1999"
        try:
            keyed, first, bridge, bridges, linked, present = m._poll_asl_state()
            self.assertEqual(linked, frozenset({"2000"}))
            self.assertEqual(present, frozenset({"2000", "2001"}))
            self.assertEqual(bridges, frozenset({"1999"}))
            m.ami_command = lambda *a, **k: ("", False)
            self.assertIsNone(m._poll_asl_state())
        finally:
            m.ami_command = real

    def test_page_shows_unknown_and_follows_the_echo_link(self):
        with open(self.mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for needle in ("function indUnknown(mode)", "d.link_known===false", "d.echo_node", "_lastLinkKnown"):
            self.assertIn(needle, src)

    def test_echo_disconnect_from_the_page_drops_every_link(self):
        m = self.mod
        m.action_echo_connect("123456", "E")
        self.linked = ["3123456", "2001", "3000099"]
        self.calls.clear()
        self.assertTrue(m.action_echo_disconnect(drop_all=True)[0])
        dropped = [c[1].split()[-1] for c in self.calls if c[0] == "ast" and " ilink 1 " in c[1]]
        self.assertEqual(dropped, ["3123456", "2001", "3000099"])
        self.assertIsNone(self.st().echo_fav)
        m.action_echo_connect("123456", "E")
        self.calls.clear()
        self.assertTrue(m.action_echo_disconnect()[0])
        dropped = [c[1].split()[-1] for c in self.calls if c[0] == "ast" and " ilink 1 " in c[1]]
        self.assertEqual(dropped, ["3123456"])

    def late(self):
        page, fav, since = self.mod._tune_seen
        self.mod._tune_seen = (page, fav, since - self.mod._TUNE_GRACE_SEC - 1)

    def test_tune_is_pending_then_confirmed_by_the_bridge(self):
        m = self.mod
        m._enter_page("P25")
        self.assertEqual(m._tune_check(), "")
        m.action_tune("P25", "10200", "NA")
        self.assertEqual(m._tune_check(), "pending")
        self.assertEqual(m.build_status()["tune_state"], "pending")
        self.ab = {"last_tune": "10200"}
        self.assertEqual(m._tune_check(), "confirmed")
        self.assertEqual(m.build_status()["tune_state"], "confirmed")
        self.assertEqual(m.action_get_abinfo()["tune_state"], "confirmed")

    def test_tune_that_never_confirms_becomes_unconfirmed(self):
        m = self.mod
        m._enter_page("NXDN")
        m.action_tune("NXDN", "65000", "WW")
        self.ab = {"last_tune": "disconnect"}
        self.assertEqual(m._tune_check(), "pending")
        self.late()
        self.assertEqual(m._tune_check(), "unconfirmed")
        self.assertEqual(self.st().current_fav, "65000")
        self.ab = {"last_tune": "65000"}
        self.assertEqual(m._tune_check(), "confirmed")

    def test_a_change_made_elsewhere_is_noticed(self):
        m = self.mod
        m._enter_page("DMR")
        m.action_tune("DMR", "3100", "USA")
        self.ab = {"last_tune": "3100"}
        self.assertEqual(m._tune_check(), "confirmed")
        self.late()
        self.ab = {"last_tune": "91"}
        self.assertEqual(m._tune_check(), "unconfirmed")
        self.assertEqual(m.build_status()["current_fav"], "3100")
        self.assertEqual(m.build_status()["tune_state"], "unconfirmed")

    def test_stopped_bridge_or_missing_file_is_not_confirmed(self):
        m = self.mod
        m._enter_page("YSF")
        m.action_tune("YSF", "1.2.3.4:42000", "A")
        self.ab = {"last_tune": "1.2.3.4:42000"}
        self.svc = {"ab": "inactive"}
        self.assertEqual(m._tune_check(), "pending")
        self.late()
        self.assertEqual(m._tune_check(), "unconfirmed")
        self.svc = {"ab": "active"}
        self.assertEqual(m._tune_check(), "confirmed")
        self.ab = None
        self.assertEqual(m._tune_check(), "unconfirmed")

    def test_fcs_compares_the_tune_string(self):
        m = self.mod
        m._enter_page("FCS")
        self.assertTrue(m.action_tune("FCS", "FCS00102", "Room")[0])
        self.ab = {"last_tune": "900102"}
        self.assertEqual(m._tune_check(), "confirmed")

    def test_nothing_changes_while_a_link_action_runs(self):
        m = self.mod
        m._enter_page("P25")
        m.action_tune("P25", "10200", "NA")
        self.ab = {"last_tune": "10200"}
        self.assertEqual(m._tune_check(), "confirmed")
        self.late()
        self.ab = {"last_tune": "disconnect"}
        m._link_enter()
        try:
            self.assertEqual(m._tune_check(), "confirmed")
        finally:
            m._link_exit()
        self.assertEqual(m._tune_check(), "unconfirmed")

    def test_dstar_and_xlx_never_show_unconfirmed(self):
        m = self.mod
        m.action_dstar_connect("REF001", "C", "REF001 C")
        self.ab = {"last_tune": "something else"}
        self.late()
        self.assertEqual(m._tune_check(), "pending")
        self.late()
        self.assertEqual(m._tune_check(), "sent")
        self.ab = {"last_tune": "REF001CL"}
        self.assertEqual(m._tune_check(), "confirmed")
        m.action_xlx_connect("XLX307 D", "XLX307", "D")
        self.ab = None
        m._tune_check()
        self.late()
        self.assertEqual(m._tune_check(), "sent")

    def test_dstar_gateway_link_expects_cqcqcq(self):
        m = self.mod
        real = (m._ircddb_rc_settings, m._ircddb_rc_link)
        m._ircddb_rc_settings = lambda: {"port": 1}
        m._ircddb_rc_link = lambda target: (True, "")
        try:
            self.assertTrue(m.action_dstar_connect("W1ABC", "B", "W1ABC B")[0])
        finally:
            m._ircddb_rc_settings, m._ircddb_rc_link = real
        self.assertEqual(self.st().tune_expect[1], "CQCQCQ")
        self.ab = {"last_tune": "CQCQCQ"}
        self.assertEqual(m._tune_check(), "confirmed")

    def test_m17_is_checked_against_its_ini_and_service(self):
        m = self.mod
        real = m.M17_INI_PATH
        m.M17_INI_PATH = os.path.join(WORK, "USRP2M17.ini")
        try:
            m._enter_page("M17")
            m.action_m17_connect("R", "M17-USA", "1.2.3.4", "A")
            with open(m.M17_INI_PATH, "w", encoding="utf-8") as fh:
                fh.write(m._m17_ini_content("N0CALL", "M17-USA", "1.2.3.4", "A"))
            self.assertEqual(m._tune_check(), "confirmed")
            self.svc = {"m17": "inactive"}
            self.late()
            self.assertEqual(m._tune_check(), "unconfirmed")
            self.svc = {}
            with open(m.M17_INI_PATH, "w", encoding="utf-8") as fh:
                fh.write(m._m17_ini_placeholder("N0CALL"))
            self.assertEqual(m._tune_check(), "unconfirmed")
        finally:
            m.M17_INI_PATH = real

    def test_asl_and_idle_tabs_have_no_tune_state(self):
        m = self.mod
        m.action_asl_connect("2000", "X")
        self.assertEqual(m._tune_check(), "")
        self.assertEqual(m.build_status()["tune_state"], "")
        m._enter_page("DMR")
        m.set_state(tune_state="confirmed")
        self.assertEqual(m.build_status()["tune_state"], "")
        self.assertEqual(m._tune_check(), "")
        self.assertEqual(self.st().tune_state, "")

    def test_page_uses_the_server_verdict(self):
        with open(self.mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for needle in ("function tunePendingDone(state,name)", "d.tune_state", "ind-unconfirmed", "_tuneState!=='unconfirmed'"):
            self.assertIn(needle, src)
        self.assertNotIn("age>10000", src)

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
