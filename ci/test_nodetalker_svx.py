import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nt_svx_")
os.environ["NODETALKER_SUITELOG"] = os.path.join(WORK, "suitelog.jsonl")
os.environ["NODETALKER_SUITELOG_FLAG"] = os.path.join(WORK, "suitelog.on")
os.environ.setdefault("NODETALKER_CONFIG_DIR", os.path.join(WORK, "nt"))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:4]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("nt_svx_under_test", newest("nodetalker_v[0-9]*.py"))
nt = importlib.util.module_from_spec(spec)
sys.modules["nt_svx_under_test"] = nt
spec.loader.exec_module(nt)

LOG = """Mon Nov 16 10:52:16 2026: Activating link 'ReflectorLink' due to DEFAULT_ACTIVE
Mon Nov 16 10:52:16 2026: ReflectorLogic: Connecting to service 
Mon Nov 16 10:52:16 2026: ReflectorLogic: Authentication OK
Mon Nov 16 10:54:44 2026: ReflectorLogic: Selecting TG #240
Mon Nov 16 10:54:46 2026: ReflectorLogic: Selecting TG #0
Mon Nov 16 10:54:48 2026: Deactivating link ReflectorLink
Mon Nov 16 10:58:54 2026: Activating link 'ReflectorLink' due to DTMF command
Mon Nov 16 10:58:54 2026: ReflectorLogic: Selecting TG #240
Mon Nov 16 10:58:54 2026: *** WARNING[ReflectorLogic]: Could not find audio clip 'talk_group' in context 'Core'
""".splitlines()


class SvxReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "svxlink")
        self.saved = (nt.SVX_LOG, dict(nt._svx_cache))
        nt.SVX_LOG = self.log
        nt._svx_cache.update(t=-1e9, v="")

    def tearDown(self):
        nt.SVX_LOG = self.saved[0]
        nt._svx_cache.clear()
        nt._svx_cache.update(self.saved[1])
        self.tmp.cleanup()

    def write(self, lines):
        with open(self.log, "w") as fh:
            fh.write("\n".join(lines) + "\n")

    def text(self, active=True):
        with mock.patch.object(nt, "_svc_active", lambda svc: active):
            return nt.svx_text()

    def test_events_follow_the_last_line_of_each_kind(self):
        self.assertEqual(nt.svx_events(LOG), {"state": "connected", "tg": "240", "link": True})
        self.assertFalse(nt.svx_events(LOG[:6])["link"])
        self.assertEqual(nt.svx_events(LOG[:5])["tg"], "0")
        down = LOG + ["Mon Nov 16 11:00:00 2026: ReflectorLogic: Disconnected from 127.0.0.1:5300: Connection refused"]
        self.assertEqual(nt.svx_events(down)["state"], "down")

    def test_every_situation_has_its_own_text(self):
        self.write(LOG)
        self.assertEqual(self.text(), "TG 240")
        self.write(LOG[:5])
        self.assertEqual(self.text(), "no talkgroup")
        self.write(LOG[:6])
        self.assertEqual(self.text(), "reflector link off")
        self.write(LOG + ["Mon Nov 16 11:00:00 2026: ReflectorLogic: Disconnected from h:5300: refused"])
        self.assertEqual(self.text(), "reflector not connected")
        self.write(["Mon Nov 16 11:00:00 2026: nothing about reflectors"])
        self.assertEqual(self.text(), "talkgroup unknown")
        os.unlink(self.log)
        self.assertEqual(self.text(), "talkgroup unknown")
        self.assertEqual(self.text(active=False), "SvxLink stopped")

    def test_the_answer_is_kept_for_a_few_seconds(self):
        self.write(LOG)
        with mock.patch.object(nt, "_svc_active", lambda svc: True):
            self.assertEqual(nt.svx_now(), "TG 240")
            self.write(LOG[:5])
            self.assertEqual(nt.svx_now(), "TG 240")
            nt._svx_cache["t"] = -1e9
            self.assertEqual(nt.svx_now(), "no talkgroup")


class BridgeFinder(unittest.TestCase):
    def find(self, usrp, dash=("", "", "")):
        nt._bridge_cache.update(t=-60.0, v=None)
        with mock.patch.object(nt, "_usrp_nodes", lambda: usrp), \
                mock.patch.object(nt, "favcfg", lambda: {}), \
                mock.patch.object(nt, "_ini_read", lambda path: {}), \
                mock.patch.object(nt, "dashboard_conf", lambda: {"bridge_list": list(dash), "asl_node": "", "port": 8989,
                                                                  "callsign": "", "bridges": set(), "favs": [], "nets": []}):
            got = nt.bridge_nodes(0)
        nt._bridge_cache.update(t=-60.0, v=None)
        return got

    def test_the_svx_bridge_is_the_node_on_ports_34000_and_32000(self):
        got = self.find({frozenset((34000, 32000)): "1900", frozenset((34001, 32001)): "1999"})
        self.assertEqual((got["svx"], got["svx_src"]), ("1900", "rpt.conf"))
        self.assertEqual(got["digital"], "1999")

    def test_the_node_is_found_on_other_numbers_too(self):
        got = self.find({frozenset((34000, 32000)): "1555"})
        self.assertEqual(got["svx"], "1555")

    def test_node_controllers_third_slot_is_used_when_rpt_conf_has_no_match(self):
        got = self.find({}, ("1999", "1917", "1801"))
        self.assertEqual((got["svx"], got["svx_src"]), ("1801", "Node Controller"))

    def test_the_default_applies_only_when_that_node_exists_and_otherwise_nothing(self):
        got = self.find({frozenset((40000, 40001)): "1900"})
        self.assertEqual((got["svx"], got["svx_src"]), ("1900", "default"))
        got = self.find({})
        self.assertEqual((got["svx"], got["svx_src"]), ("", ""))


class Badge(unittest.TestCase):
    def live(self, links, svx="1900", text="TG 240"):
        bridges = {"digital": "1999", "m17": "1917", "svx": svx}
        with mock.patch.object(nt, "bridge_nodes", lambda max_age=30.0: bridges), \
                mock.patch.object(nt, "svx_now", lambda: text), \
                mock.patch.object(nt, "astdb_name", lambda n: ""):
            return nt.live_link(links, True, False, [])

    def test_linked_to_the_svx_bridge_alone_shows_svx_and_the_talkgroup(self):
        got = self.live([{"node": "1900", "state": "ESTABLISHED"}])
        self.assertEqual(got, {"state": "connected", "mode": "SVX", "label": "TG 240", "tag": ""})

    def test_each_situation_text_is_the_label(self):
        for text in ("no talkgroup", "reflector not connected", "reflector link off", "talkgroup unknown", "SvxLink stopped"):
            got = self.live([{"node": "1900", "state": "ESTABLISHED"}], text=text)
            self.assertEqual((got["mode"], got["label"]), ("SVX", text))

    def test_connecting_is_shown(self):
        got = self.live([{"node": "1900", "state": "CONNECTING"}])
        self.assertEqual((got["state"], got["mode"]), ("linking", "SVX"))

    def test_an_allstar_node_stays_the_main_badge_and_svx_goes_in_the_tag(self):
        got = self.live([{"node": "45192", "state": "ESTABLISHED"}, {"node": "1900", "state": "ESTABLISHED"}])
        self.assertEqual((got["mode"], got["label"], got["tag"]), ("ASL", "Node 45192", "SVX TG 240"))

    def test_without_an_svx_bridge_1900_is_an_ordinary_node_as_before(self):
        got = self.live([{"node": "1900", "state": "ESTABLISHED"}], svx="")
        self.assertEqual((got["mode"], got["label"]), ("ASL", "Node 1900"))

    def test_the_svx_bridge_is_not_listed_as_an_allstar_node(self):
        got = self.live([{"node": "45192", "state": "ESTABLISHED"}, {"node": "1900", "state": "ESTABLISHED"}])
        self.assertNotIn("1900", got["label"])

    def test_the_other_bridges_still_work(self):
        bridges = {"digital": "1999", "m17": "1917", "svx": "1900"}
        with mock.patch.object(nt, "bridge_nodes", lambda max_age=30.0: bridges), \
                mock.patch.object(nt, "astdb_name", lambda n: ""):
            got = nt.live_link([{"node": "1999", "state": "ESTABLISHED"}], True, False, [])
        self.assertNotEqual(got["mode"], "SVX")

    def test_the_badge_is_lime_like_node_controllers_svx_tab(self):
        with open(newest("nodetalker_v[0-9]*.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('.lk-badge[data-mode="SVX"]{border-color:rgb(212,255,0)!important;color:rgb(212,255,0)!important}', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
