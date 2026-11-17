import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nm_links_")
os.environ.setdefault("NODETALKER_CONFIG_DIR", os.path.join(WORK, "nt"))
os.environ.setdefault("NODETALKER_SUITELOG", os.path.join(WORK, "nt_suitelog.jsonl"))
os.environ.setdefault("NODETALKER_SUITELOG_FLAG", os.path.join(WORK, "nt_suitelog.on"))
os.environ.setdefault("NODERECORDER_CONFIG_DIR", os.path.join(WORK, "nr"))

LABELS = {
    "nodetalker": "Node Mon",

    "noderecorder": "Node Mon",

    "sysmon": "Node Mon",

    "sysmon_pi02w": "Nodemon",

    "nodecontrol": "Nodemon",

    "nodecontrol_pi02w": "Nodemon",
}
PILL = '<a class="ql hidden" data-ql="nodemon" data-ql-port="7777" href="#" target="_blank" rel="noopener">{}</a>'
QL_ROW_TOOLS = {"nodetalker": "nodetalker_v[0-9]*.py", "noderecorder": "noderecorder_v[0-9]*.py"}


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:4]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


def load(name, pattern):
    spec = importlib.util.spec_from_file_location(name + "_under_test", newest(pattern))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name + "_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def make_case(key, pattern):
    class QuickLinkCase(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.mod = load(key, pattern)
            with open(newest(pattern), encoding="utf-8") as fh:
                cls.src = fh.read()

        def test_the_page_has_the_nodemon_button_and_no_allmon3_button(self):
            self.assertEqual(self.src.count(PILL.format(LABELS[key])), 1)
            self.assertNotIn('data-ql="allmon3"', self.src)
            self.assertNotIn(">Allmon3</a>", self.src)

        def test_the_button_is_first_in_the_row_and_the_others_stay(self):
            row = self.src.split('<div id="ql-row" class="ql-row hidden">', 1)[1].split("</div>", 1)[0]
            tags = re.findall(r'data-ql="(\w+)"', row)
            self.assertEqual(tags, ["nodemon", "dvswitch", "cockpit"])

        def test_the_web_page_list_no_longer_probes_allmon3(self):
            self.assertEqual([n for n, _p in self.mod.WEB_PAGES], ["dvswitch"])
            self.assertEqual(self.mod.NODEMON_PORT, 7777)

        def test_the_links_reply_says_whether_node_monitor_answers(self):
            for up in (True, False):
                self.mod._links_cache.update(t=-1e9, v={})
                with mock.patch.object(self.mod, "port_open", lambda port, *a, **k: up and port == 7777), \
                        mock.patch.object(self.mod, "page_answers", lambda path, *a, **k: False):
                    got = self.mod.quick_links()
                self.assertEqual(got["nodemon"], up)
                self.assertFalse(got["cockpit"])
                self.assertNotIn("allmon3", got)
                self.assertIn("dvswitch", got)
            self.mod._links_cache.update(t=-1e9, v={})

        def test_the_page_shows_a_link_by_port_when_the_reply_says_it_answers(self):
            self.assertIn("q.dataset.qlPath ? base + q.dataset.qlPath : base + ':' + q.dataset.qlPort + '/'", self.src)
            self.assertIn("const on = !!L[q.dataset.ql];", self.src)

    QuickLinkCase.__name__ = f"QuickLinks_{key}"
    QuickLinkCase.__qualname__ = f"QuickLinks_{key}"
    return QuickLinkCase


STATIC_BAR_TOOLS = {"sysmon": "sysmon_v[0-9]*.py", "sysmon_pi02w": "sysmon_pi02w_v[0-9]*.py"}


def make_bar_case(key, pattern):
    class BarCase(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            with open(newest(pattern), encoding="utf-8") as fh:
                cls.src = fh.read()
            cls.bar = cls.src.split('<div id="ql-bar">', 1)[1].split("</div>", 1)[0]

        def test_the_bar_has_the_nodemon_button_first_and_no_allmon3(self):
            ids = re.findall(r'<a id="(lnk-[a-z0-9]+)"', self.bar)
            self.assertEqual(ids[:2], ["lnk-nodemon", "lnk-dvswitch"])
            self.assertNotIn("lnk-allmon3", self.src)
            self.assertNotIn(">Allmon3</a>", self.bar)
            self.assertEqual(ids[2:], ["lnk-cockpit", "lnk-m17", "lnk-wifimon", "lnk-dashboard"])

        def test_the_button_opens_node_monitor(self):
            m = re.search(r'<a id="lnk-nodemon" class="ql-btn" href="([^"]+)" target="_blank" rel="noopener"\s+title="([^"]+)">([^<]+)</a>', self.bar)
            self.assertIsNotNone(m)
            self.assertEqual(m.groups(), ("http://localhost:7777/", "Node Monitor", LABELS[key]))

        def test_the_page_points_it_at_this_nodes_port_7777(self):
            self.assertIn('const qlPorts = {"lnk-nodemon": 7777, "lnk-cockpit": 9090, "lnk-wifimon": 8991};', self.src)
            self.assertNotIn("8080", self.src.split("const qlPorts", 1)[1].split(";", 1)[0])

    BarCase.__name__ = f"QuickBar_{key}"
    BarCase.__qualname__ = f"QuickBar_{key}"
    return BarCase


GROUP_TOOLS = {"nodecontrol": "nodecontrol_v[0-9]*.py", "nodecontrol_pi02w": "nodecontrol_pi02w_v[0-9]*.py"}


def make_group_case(key, pattern):
    class GroupCase(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            with open(newest(pattern), encoding="utf-8") as fh:
                cls.src = fh.read()
            cls.group = cls.src.split('<div class="ql-group ql-left">', 1)[1].split("</div>", 1)[0]

        def test_the_left_group_has_nodemon_first_then_dvswitch_and_cockpit(self):
            labels = re.findall(r">([^<]+)</a>", self.group)
            self.assertEqual(labels, [LABELS[key], "DVSwitch", "Cockpit"])

        def test_the_button_opens_node_monitor_by_port(self):
            self.assertIn('<a class="ql" data-ql-port="7777" href="#" target="_blank" rel="noopener">%s</a>' % LABELS[key], self.group)
            self.assertNotIn('data-ql-path="/allmon3"', self.src)
            self.assertNotIn(">Allmon3</a>", self.src)

        def test_the_page_builds_the_address_from_the_port(self):
            self.assertIn("document.querySelectorAll('.ql[data-ql-path],.ql[data-ql-port]').forEach(a => {", self.src)
            self.assertIn("a.href = a.dataset.qlPath ? `http://${host}${a.dataset.qlPath}`", self.src)

    GroupCase.__name__ = f"QuickGroup_{key}"
    GroupCase.__qualname__ = f"QuickGroup_{key}"
    return GroupCase


for _key, _pattern in GROUP_TOOLS.items():
    globals()[f"QuickGroup_{_key}"] = make_group_case(_key, _pattern)


for _key, _pattern in STATIC_BAR_TOOLS.items():
    globals()[f"QuickBar_{_key}"] = make_bar_case(_key, _pattern)


for _key, _pattern in QL_ROW_TOOLS.items():
    globals()[f"QuickLinks_{_key}"] = make_case(_key, _pattern)


if __name__ == "__main__":
    unittest.main(verbosity=2)
