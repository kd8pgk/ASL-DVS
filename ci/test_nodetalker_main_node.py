import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nt_mainnode_")
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


nt = load("nt_main_node_under_test", newest("nodetalker_v*.py"))


class MainNode(unittest.TestCase):
    def with_values(self, stored, dash):
        cfg = {"node": stored}
        return (mock.patch.object(nt, "_cfg_get", lambda k: cfg.get(k, "")),
                mock.patch.object(nt, "dashboard_conf", lambda: {"asl_node": dash}))

    def test_dashboard_node_wins_over_a_stale_stored_node(self):
        a, b = self.with_values("652704", "652701")
        with a, b:
            self.assertEqual(nt.main_node(), "652701")

    def test_stored_node_is_used_when_there_is_no_dashboard(self):
        a, b = self.with_values("652704", "")
        with a, b:
            self.assertEqual(nt.main_node(), "652704")

    def test_empty_when_neither_is_set(self):
        a, b = self.with_values("", "")
        with a, b:
            self.assertEqual(nt.main_node(), "")


if __name__ == "__main__":
    unittest.main()
