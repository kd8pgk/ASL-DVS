import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nr_svxtune_")
os.environ["NODERECORDER_SUITELOG"] = os.path.join(WORK, "suitelog.jsonl")
os.environ["NODERECORDER_SUITELOG_FLAG"] = os.path.join(WORK, "suitelog.on")
os.environ.setdefault("NODERECORDER_CONFIG_DIR", os.path.join(WORK, "nr"))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:4]]
    return sorted(__import__("glob").glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("nr_svxtune_under_test", newest("noderecorder_v[0-9]*.py"))
nr = importlib.util.module_from_spec(spec)
sys.modules["nr_svxtune_under_test"] = nr
spec.loader.exec_module(nr)


class SvxFavorites(unittest.TestCase):
    def test_svx_is_a_mode(self):
        self.assertEqual(nr._mode_of("svx"), "SVX")
        self.assertIn("SVX", nr.FAV_MODES)

    def test_talkgroup_is_digits_from_1_to_9_digits(self):
        self.assertEqual(nr._norm_fav_core({"mode": "SVX", "num": "1234"})["num"], "1234")
        for bad in ("0", "abc", "1000000000", ""):
            with self.assertRaises(ValueError, msg=bad):
                nr._norm_fav_core({"mode": "SVX", "num": bad})

    def test_target_is_mode_and_talkgroup(self):
        self.assertEqual(nr.fav_target({"mode": "SVX", "num": "1234"}), "SVX|1234")


class SvxControl(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.patches = [
            mock.patch.object(nr, "_svx_ready", lambda: True),
            mock.patch.object(nr, "_svx_send", lambda cmd: (self.sent.append(cmd), True)[1]),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_connect_sends_the_talkgroup_like_node_controller(self):
        r = nr.svx_connect({"mode": "SVX", "num": "1234"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.sent, ["911234#"])

    def test_release_sends_910_then_9(self):
        r = nr.svx_release()
        self.assertTrue(r["ok"])
        self.assertEqual(self.sent, ["910#", "9#"])

    def test_connect_without_control_device_says_so(self):
        with mock.patch.object(nr, "_svx_ready", lambda: False):
            r = nr.svx_connect({"mode": "SVX", "num": "1234"})
        self.assertFalse(r["ok"])
        self.assertIn("control device", r["error"])
        self.assertEqual(self.sent, [])

    def test_tune_connect_routes_svx_to_the_control_device(self):
        r = nr._tune_connect_impl({"mode": "SVX", "num": "1234"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.sent, ["911234#"])

    def test_tune_disconnect_routes_svx_to_release(self):
        nr._tune_disconnect_impl({"mode": "SVX", "num": "1234"})
        self.assertEqual(self.sent, ["910#", "9#"])


class SendRefusesAnythingElse(unittest.TestCase):
    def test_only_9_commands_leave_the_process(self):
        with mock.patch.object(nr.os, "open") as opened:
            for cmd in ("8#", "91x#", "91234", "rm -rf /"):
                self.assertFalse(nr._svx_send(cmd), cmd)
            opened.assert_not_called()


class SavedList(unittest.TestCase):
    def test_reads_the_svx_section_of_asl_dvs_conf(self):
        path = os.path.join(WORK, "asl_dvs.conf")
        with open(path, "w") as fh:
            fh.write("[general]\nname=x|1\n\n[SVX]\nnetwork_url=https://x\n# comment\n"
                     "Local Chat|1234\nWorld|999999999\nBad|0\nNoNumber|abc\n")
        with mock.patch.object(nr, "DASH_CONF", path):
            self.assertEqual(nr._svx_saved_rows(), [("Local Chat", "1234"), ("World", "999999999")])
            rows = nr.tune_list("SVX")
        self.assertTrue(rows["ok"])
        self.assertEqual(rows["rows"], [["1234", "1234 · Local Chat", ""], ["999999999", "999999999 · World", ""]])

    def test_missing_file_is_an_empty_list(self):
        with mock.patch.object(nr, "DASH_CONF", os.path.join(WORK, "none.conf")):
            rows = nr.tune_list("SVX")
        self.assertEqual((rows["ok"], rows["found"], rows["rows"]), (True, False, []))


if __name__ == "__main__":
    unittest.main()
