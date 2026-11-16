import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nc_svx_")


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


nc = load("nc_svx_under_test", newest("nodecontrol_v[0-9]*.py"))


class Base(unittest.TestCase):
    def setUp(self):
        m = nc
        self.calls = []
        self.sent = []
        self.ready = True
        self.saved = {}
        fakes = {
            "_dvs": lambda sub, arg=None: (self.calls.append((sub, arg)), (True, ""))[1],
            "_asterisk": lambda cmd: self.calls.append(("ast", cmd)),
            "_query_linked_nodes": lambda timeout=3: [],
            "_link_wait": lambda node: "linked",
            "_nodelisten_skip_set": lambda: set(),
            "_nodelisten_keep_set": lambda: set(),
            "_nodelisten_tx_relink": lambda: None,
            "_gateway_svc_enter": lambda page: True,
            "_gateway_svc_leave": lambda prev, nxt: None,
            "_cpuweight_apply_for_page": lambda page: None,
            "_phone_all_nodes": lambda: set(),
            "_phone_on": lambda: False,
            "_phone_hangup_all": lambda: None,
            "_log_teardown_survivors_async": lambda what: None,
            "_read_perm_links": lambda: frozenset(),
            "_svx_send": lambda cmd: (self.sent.append(cmd), True)[1],
            "_svx_ready": lambda: self.ready,
        }
        for name, fake in fakes.items():
            self.saved[name] = getattr(m, name)
            setattr(m, name, fake)
        self.saved_sleep = m.time.sleep
        m.time.sleep = lambda s: None
        self.saved_bridges = list(m._cfg.bridge_nodes)
        m.set_state(has_asl=True, has_dvs=True, has_m17=False, has_svx=True, page="ASL", status="",
                    current_fav=None, current_fav_node=None, echo_fav=None, svx_tg=None,
                    linked_node=None, linked_nodes=frozenset(), link_known=True)

    def tearDown(self):
        for name, real in self.saved.items():
            setattr(nc, name, real)
        nc.time.sleep = self.saved_sleep
        nc._cfg.bridge_nodes = self.saved_bridges

    def links(self):
        return [c[1] for c in self.calls if c[0] == "ast" and " ilink 3 " in c[1]]


class Shape(unittest.TestCase):
    def test_page_and_slot(self):
        self.assertEqual(nc.ALL_PAGES[:3], ("ASL", "ECHO", "SVX"))
        self.assertEqual(nc.BRIDGE_SLOT_SVX, 3)
        self.assertEqual(nc.BRIDGE_SLOT_LABELS[3], "SvxLink Bridge")
        self.assertEqual(nc.BRIDGE_SLOT_PAGES[nc.BRIDGE_SLOT_SVX], {"SVX"})
        self.assertIn("SVX", nc._PAGE_ENTER)
        self.assertEqual(nc.SVX_CTRL_PTY, "/var/lib/svxlink/dtmf_ctrl")

    def test_watchdog_counters_cover_every_slot(self):
        self.assertEqual(set(nc._bridge_slot_down_polls), set(nc.BRIDGE_SLOT_PAGES))
        self.assertEqual(set(nc._bridge_slot_last_reconnect), set(nc.BRIDGE_SLOT_PAGES))
        self.assertIn(nc.BRIDGE_SLOT_SVX, nc._bridge_slot_down_polls)

    def test_blank_slot_means_1900(self):
        saved = list(nc._cfg.bridge_nodes)
        try:
            nc._cfg.bridge_nodes[3] = ""
            self.assertEqual(nc._slot_node(3), "1900")
            nc._cfg.bridge_nodes[3] = "1905"
            self.assertEqual(nc._slot_node(3), "1905")
        finally:
            nc._cfg.bridge_nodes = saved


class TabFlow(Base):
    def test_entering_the_tab_links_the_bridge(self):
        nc._cfg.bridge_nodes[3] = ""
        self.assertEqual(nc._enter_page("SVX"), "")
        self.assertTrue(any(l.endswith(" 1900") for l in self.links()), self.calls)

    def test_watchdog_relinks_a_dropped_bridge_on_the_svx_tab(self):
        nc._cfg.bridge_nodes[3] = ""
        nc._enter_page("SVX")
        self.calls.clear()
        saved = (nc._BRIDGE_DOWN_THRESHOLD, nc._BRIDGE_RECONNECT_COOLDOWN)
        try:
            nc._BRIDGE_DOWN_THRESHOLD, nc._BRIDGE_RECONNECT_COOLDOWN = 1, 0
            nc._bridge_slot_last_reconnect[nc.BRIDGE_SLOT_SVX] = 0.0
            nc._bridge_watchdog(frozenset())
        finally:
            nc._BRIDGE_DOWN_THRESHOLD, nc._BRIDGE_RECONNECT_COOLDOWN = saved
        self.assertTrue(any(l.endswith(" 1900") for l in self.links()), self.calls)

    def test_blank_svx_slot_counts_1900_as_a_bridge_when_svxlink_is_installed(self):
        saved = nc._detect_svx
        try:
            nc._cfg.bridge_nodes[3] = ""
            nc._detect_svx = lambda: True
            self.assertIn("1900", nc._bridge_set())
            self.assertTrue(nc._is_bridge_node("1900"))
            self.assertIn("1900", nc._phone_reserved_nodes())
            nc._detect_svx = lambda: False
            self.assertNotIn("1900", nc._bridge_set())
            nc._cfg.bridge_nodes[3] = "1905"
            self.assertIn("1905", nc._bridge_set())
        finally:
            nc._detect_svx = saved

    def test_no_svxlink_no_bridge_link(self):
        nc.set_state(has_svx=False)
        nc._enter_page("SVX")
        self.assertFalse(any(l.endswith(" 1900") for l in self.links()))

    def test_connect_picks_the_talkgroup(self):
        ok, msg = nc.action_svx_connect("0240", "Chat")
        self.assertTrue(ok, msg)
        self.assertEqual(self.sent, ["91240#"])
        st = nc.get_state()
        self.assertEqual((st.page, st.svx_tg), ("SVX", "240"))
        self.assertIn("TG 240", st.status)

    def test_bad_talkgroup_refused(self):
        for bad in ("", "0", "abc", "1234567890", "-5", "12 3"):
            self.assertFalse(nc.action_svx_connect(bad, "x")[0], bad)
        self.assertEqual(self.sent, [])

    def test_not_ready_links_the_bridge_only(self):
        self.ready = False
        ok, msg = nc.action_svx_connect("240", "Chat")
        self.assertFalse(ok)
        self.assertIn("Connect to an SvxReflector", msg)
        self.assertEqual(self.sent, [])
        self.assertEqual(nc.get_state().page, "SVX")
        self.assertIsNone(nc.get_state().svx_tg)

    def test_no_svxlink_refused(self):
        nc.set_state(has_svx=False)
        ok, msg = nc.action_svx_connect("240", "Chat")
        self.assertFalse(ok)
        self.assertIn("not installed", msg)

    def test_disconnect_clears_then_turns_the_link_off(self):
        nc.action_svx_connect("240", "Chat")
        self.sent.clear()
        ok, msg = nc.action_svx_disconnect()
        self.assertTrue(ok)
        self.assertEqual(self.sent, ["910#", "9#"])
        self.assertIsNone(nc.get_state().svx_tg)

    def test_leaving_the_tab_releases_the_talkgroup(self):
        nc.action_svx_connect("240", "Chat")
        self.sent.clear()
        nc._enter_page("ASL")
        self.assertEqual(self.sent, ["910#", "9#"])
        self.assertIsNone(nc.get_state().svx_tg)

    def test_status_carries_the_svx_fields(self):
        nc.set_state(svx_nodes=[("Chat", "240")], svx_tg="240")
        st = nc.build_status()
        self.assertTrue(st["has_svx"])
        self.assertEqual(st["svx"], [{"name": "Chat", "tg": "240"}])
        self.assertEqual(st["svx_tg"], "240")
        self.assertTrue(st["svx_ready"])


class SendToThePty(unittest.TestCase):
    def setUp(self):
        self.saved = nc.SVX_CTRL_PTY
        self.master, slave = os.openpty()
        self.link = os.path.join(WORK, "dtmf_ctrl")
        if os.path.lexists(self.link):
            os.remove(self.link)
        os.symlink(os.ttyname(slave), self.link)
        self.slave = slave
        nc.SVX_CTRL_PTY = self.link

    def tearDown(self):
        nc.SVX_CTRL_PTY = self.saved
        os.close(self.master)
        os.close(self.slave)

    def test_writes_to_the_real_device(self):
        import select
        import termios
        attrs = termios.tcgetattr(self.slave)
        attrs[1] &= ~termios.OPOST
        termios.tcsetattr(self.slave, termios.TCSANOW, attrs)
        self.assertTrue(nc._svx_ready())
        self.assertTrue(nc._svx_send("91240#"))
        r, _, _ = select.select([self.master], [], [], 2)
        self.assertTrue(r, "nothing arrived at SvxLink's end")
        self.assertEqual(os.read(self.master, 64), b"91240#")

    def test_refuses_anything_but_a_link_command(self):
        for bad in ("*1#", "91240", "91;rm#", "", "8#"):
            self.assertFalse(nc._svx_send(bad), bad)

    def test_refuses_a_link_that_is_not_a_pty(self):
        os.remove(self.link)
        target = os.path.join(WORK, "plain")
        open(target, "w").close()
        os.symlink(target, self.link)
        self.assertFalse(nc._svx_send("91240#"))


class ConfFile(unittest.TestCase):
    def setUp(self):
        self.saved_conf = nc.ASL_DVS_CONF
        self.path = os.path.join(WORK, "asl_dvs.conf")
        nc.ASL_DVS_CONF = self.path
        self.saved_tabs = set(nc._cfg.enabled_tabs)
        if os.path.exists(self.path):
            os.remove(self.path)

    def tearDown(self):
        nc.ASL_DVS_CONF = self.saved_conf
        nc._apply_config({"enabled_tabs": sorted(self.saved_tabs)})

    def test_write_then_parse(self):
        nc.set_state(svx_nodes=[("Chat", "240"), ("North America", "9050")],
                     mode_net_urls=dict(nc.get_state().mode_net_urls, SVX="https://svx.example.org/"))
        ok, msg = nc._write_conf([], [], [])
        self.assertTrue(ok, msg)
        with open(self.path) as fh:
            text = fh.read()
        self.assertIn("\n[SVX]\n", text)
        self.assertIn("Chat|240\n", text)
        self.assertIn("network_url=https://svx.example.org/\n", text)
        self.assertRegex(text, r"(?m)^svx_tab=(on|off)$")
        rows, url = nc._svx_parse(self.path)
        self.assertEqual(rows, [("Chat", "240"), ("North America", "9050")])
        self.assertEqual(url, "https://svx.example.org/")
        ok, msg = nc._write_conf([], [], [])
        with open(self.path) as fh:
            self.assertEqual(fh.read().count("[SVX]"), 1)

    def test_parse_skips_bad_rows(self):
        with open(self.path, "w") as fh:
            fh.write("[SVX]\nGood|240\nBad|abc\nZero|0\n|5\n[ECHO]\nX|1\n")
        self.assertEqual(nc._svx_parse(self.path)[0], [("Good", "240")])

    def test_old_version_conf_without_svx_tab_shows_the_tab(self):
        with open(self.path, "w") as fh:
            fh.write("[CONFIG]\nasl_node=123456\nenabled_tabs=ASL,ECHO\n\n[SVX]\nChat|240\n")
        nc._try_load_conf_from(nc.Path(self.path))
        self.assertIn("SVX", nc._cfg.enabled_tabs)
        self.assertEqual(nc.get_state().svx_nodes, [("Chat", "240")])

    def test_svx_tab_off_is_respected(self):
        with open(self.path, "w") as fh:
            fh.write("[CONFIG]\nasl_node=123456\nenabled_tabs=ASL,ECHO\nsvx_tab=off\n")
        nc._try_load_conf_from(nc.Path(self.path))
        self.assertNotIn("SVX", nc._cfg.enabled_tabs)

    def test_save_svx_validates(self):
        self.assertFalse(nc.action_save_svx([{"name": "x", "tg": "abc"}])[0])
        ok, msg = nc.action_save_svx([{"name": "Chat", "tg": "0240"}, {"name": "", "tg": ""}, {"name": "", "tg": "91"}])
        self.assertTrue(ok, msg)
        self.assertEqual(nc.get_state().svx_nodes, [("Chat", "240"), ("TG 91", "91")])

    def test_save_favorite_no_duplicates(self):
        nc.set_state(svx_nodes=[("Chat", "240")])
        self.assertFalse(nc.action_save_svx_favorite("240", "again")[0])
        self.assertTrue(nc.action_save_svx_favorite("91", "TG 91")[0])
        self.assertEqual(nc.get_state().svx_nodes[-1], ("TG 91", "91"))


class PageText(unittest.TestCase):
    def test_tab_order_and_edit_pieces(self):
        with open(newest("nodecontrol_v[0-9]*.py")) as fh:
            src = fh.read()
        self.assertLess(src.index('id="tab-echo"'), src.index('id="tab-svx"'))
        self.assertLess(src.index('id="tab-svx"'), src.index('id="tab-dmr"'))
        self.assertIn('id="chk-SVX"', src)
        self.assertIn('for="cfg-bridge-node-3">SvxLink Bridge</label>', src)
        self.assertNotRegex(src, r'id="cfg-bridge-node-3"[^>]*disabled')
        for name in ("svx-connect", "svx-disc", "save-svx-favorite", "save-svx"):
            self.assertIn("'" + name + "'", src)

    def test_pi02w_build_has_no_svx_tab(self):
        with open(newest("nodecontrol_pi02w_v[0-9]*.py")) as fh:
            src = fh.read()
        self.assertNotIn('id="tab-svx"', src)


if __name__ == "__main__":
    unittest.main()
