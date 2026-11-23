import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nr_home_")
os.environ.setdefault("NODERECORDER_CONFIG_DIR", os.path.join(WORK, "nr"))


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


nr = load("nr_home_under_test", newest("noderecorder_v*.py"))


class HomeChannel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nr_home_case_")
        self.patch = mock.patch.object(nr, "HOME_PATH", os.path.join(self.tmp, "home_channel.json"))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_save_and_load_round_trip(self):
        r = nr.home_save({"mode": "ASL", "num": "1234", "label": "Home"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(nr.home_load(), {"mode": "ASL", "num": "1234", "net": "", "module": "", "label": "Home"})

    def test_empty_mode_turns_it_off(self):
        nr.home_save({"mode": "ASL", "num": "1234"})
        r = nr.home_save({"mode": ""})
        self.assertTrue(r["ok"])
        self.assertIsNone(nr.home_load())

    def test_invalid_channel_is_refused_and_nothing_is_written(self):
        r = nr.home_save({"mode": "NOPE", "num": "1"})
        self.assertFalse(r["ok"])
        self.assertIsNone(nr.home_load())

    def test_after_a_recording_the_home_channel_is_connected(self):
        nr.home_save({"mode": "ASL", "num": "1234", "label": "Home"})
        actions = nr.RealActions()
        entry = {"target": {"mode": "STFU", "num": "3100"}}
        with mock.patch.object(nr, "tune_disconnect", return_value={"ok": True}) as dis, \
                mock.patch.object(nr, "tune_connect", return_value={"ok": True}) as con:
            ok, msg, _ = actions.disconnect(entry)
        self.assertTrue(ok)
        self.assertIn("connected the home channel Home", msg)
        dis.assert_called_once_with(entry["target"])
        self.assertEqual(con.call_args[0][0]["num"], "1234")

    def test_recording_the_home_channel_itself_does_not_reconnect(self):
        nr.home_save({"mode": "ASL", "num": "1234"})
        actions = nr.RealActions()
        with mock.patch.object(nr, "tune_disconnect", return_value={"ok": True}), \
                mock.patch.object(nr, "tune_connect") as con:
            ok, msg, _ = actions.disconnect({"target": {"mode": "ASL", "num": "1234"}})
        self.assertTrue(ok)
        con.assert_not_called()

    def test_without_a_home_channel_the_node_is_disconnected_as_before(self):
        actions = nr.RealActions()
        with mock.patch.object(nr, "tune_disconnect", return_value={"ok": True}) as dis, \
                mock.patch.object(nr, "tune_connect") as con:
            ok, msg, _ = actions.disconnect({"target": {"mode": "STFU", "num": "3100"}})
        self.assertTrue(ok)
        dis.assert_called_once()
        con.assert_not_called()


if __name__ == "__main__":
    unittest.main()
