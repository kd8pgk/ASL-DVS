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

PILL = '<a class="ql hidden" data-ql="nodemon" data-ql-port="7777" href="#" target="_blank" rel="noopener">Nodemon</a>'
QL_ROW_TOOLS = {"nodetalker": "nodetalker_v[0-9]*.py"}


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
            self.assertEqual(self.src.count(PILL), 1)
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


for _key, _pattern in QL_ROW_TOOLS.items():
    globals()[f"QuickLinks_{_key}"] = make_case(_key, _pattern)


if __name__ == "__main__":
    unittest.main(verbosity=2)
