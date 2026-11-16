import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


h44 = load("h44_groups_under_test", newest("44helper_v[0-9]*.py"))
ETC = "/usr/local/etc/svxlink"


class SvxGroupShape(unittest.TestCase):
    def test_group_is_defined_like_the_others(self):
        g = h44._CFGR_GROUPS["svx"]
        self.assertEqual(g["label"], "SvxLink USRP")
        self.assertEqual(g["markers"], [ETC + "/svxlink.conf"])
        self.assertIn(ETC + "/svxlink.conf", g["core"])
        self.assertIn(ETC + "/svxlink.d/UsrpLogic.conf", g["core"])
        self.assertEqual(g["services"], ["svxlink-usrp", "svxreflector"])
        self.assertEqual(g["files"], g["core"] + g["optional"])
        for key in ("label", "markers", "core", "optional", "globs", "services", "files"):
            for other in h44._CFGR_GROUPS.values():
                self.assertIn(key, other)

    def test_order_keeps_phone_last(self):
        order = list(h44._CFGR_GROUPS)
        self.assertEqual(order, ["asl3", "dvs", "m17", "svx", "phone"])

    def test_no_file_belongs_to_two_groups_by_accident(self):
        svx = set(h44._CFGR_GROUPS["svx"]["files"])
        for name, g in h44._CFGR_GROUPS.items():
            if name != "svx":
                self.assertFalse(svx & set(g["files"]), name)

    def test_paths_allowed(self):
        ok = h44._cfgr_path_allowed
        self.assertTrue(ok("svx", ETC + "/svxlink.conf"))
        self.assertTrue(ok("svx", ETC + "/svxlink.d/ModuleParrot.conf"))
        self.assertTrue(ok("svx", "/etc/systemd/system/svxlink-usrp.service"))
        self.assertFalse(ok("svx", ETC + "/svxlink.d/.hidden.conf"))
        self.assertFalse(ok("svx", ETC + "/svxlink.d/../../../shadow.conf"))
        self.assertFalse(ok("svx", ETC + "/svxlink.d/sub/x.conf"))
        self.assertFalse(ok("svx", "/etc/svxlink/svxlink.conf"))
        self.assertFalse(ok("svx", "/etc/asterisk/rpt.conf"))
        self.assertFalse(ok("asl3", ETC + "/svxlink.conf"))

    def test_installed_follows_the_marker(self):
        real = os.path.exists
        with mock.patch.object(h44.os.path, "exists", lambda p: p == ETC + "/svxlink.conf" or (real(p) and "svxlink" not in p)):
            self.assertTrue(h44._cfgr_installed()["svx"])
        with mock.patch.object(h44.os.path, "exists", lambda p: False):
            self.assertFalse(h44._cfgr_installed()["svx"])

    def test_status_lists_the_group(self):
        with mock.patch.object(h44, "_cfgr_port_clashes", lambda *a: ([], 0)), \
                mock.patch.object(h44, "_cfgr_gateway_pairs", lambda *a: ([], [])), \
                mock.patch.object(h44, "_cfgr_usrp_pairs", lambda *a: ([], [])), \
                mock.patch.object(h44, "_cfgr_ambe_state", lambda *a: ("", "")), \
                mock.patch.object(h44, "_cfgr_gateway_states", lambda: []), \
                mock.patch.object(h44, "_cfgr_ri_status", lambda: {}), \
                mock.patch.object(h44, "_fcr_status", lambda: {}), \
                mock.patch.object(h44, "_pn_status", lambda: {}), \
                mock.patch.object(h44, "_cfgr_list_points", lambda: []), \
                mock.patch.object(h44, "_cfgr_read_manifest", lambda d: None):
            st = h44.build_config_status()
        self.assertIn("svx", st["order"])
        self.assertEqual(st["groups_meta"]["svx"]["label"], "SvxLink USRP")
        self.assertEqual(st["groups_meta"]["svx"]["services"], ["svxlink-usrp", "svxreflector"])
        self.assertIn("svx", st["installed"])


class SvxSaveAndCompare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="h44_groups_")
        self.etc = os.path.join(self.tmp, "etc")
        os.makedirs(os.path.join(self.etc, "svxlink.d"))
        self.files = {
            os.path.join(self.etc, "svxlink.conf"): "[GLOBAL]\nLOGICS=SimplexLogic,UsrpLogic\n",
            os.path.join(self.etc, "svxlink.d", "UsrpLogic.conf"): "[UsrpLogic]\nUSRP_TX_PORT=32000\nUSRP_RX_PORT=34000\n",
            os.path.join(self.etc, "svxlink.d", "ModuleParrot.conf"): "[ModuleParrot]\nNAME=Parrot\n",
        }
        for p, t in self.files.items():
            with open(p, "w") as fh:
                fh.write(t)
        g = dict(h44._CFGR_GROUPS["svx"])
        g["core"] = [os.path.join(self.etc, "svxlink.conf"), os.path.join(self.etc, "svxlink.d", "UsrpLogic.conf")]
        g["optional"] = [os.path.join(self.etc, "svxlink.d", "ModuleEchoLink.conf")]
        g["globs"] = [(os.path.join(self.etc, "svxlink.d"), ".conf")]
        g["files"] = g["core"] + g["optional"]
        g["markers"] = [g["core"][0]]
        self.patches = [mock.patch.dict(h44._CFGR_GROUPS, {"svx": g}),
                        mock.patch.object(h44, "_CFGR_DIR", os.path.join(self.tmp, "lib"))]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        self.snap = os.path.join(self.tmp, "lib", "restore")

    def test_save_copies_core_optional_and_extra_module_files(self):
        m = h44._cfgr_take(self.snap, ["svx"], "Restore point", "restore")
        saved = m["groups"]["svx"]["files"]
        self.assertEqual(set(saved), set(self.files))
        self.assertEqual(m["groups"]["svx"]["missing"], [])
        for path, text in self.files.items():
            with open(h44._cfgr_store_path(self.snap, "svx", path)) as fh:
                self.assertEqual(fh.read(), text)

    def test_missing_core_file_is_reported_and_optional_is_not(self):
        os.remove(os.path.join(self.etc, "svxlink.d", "UsrpLogic.conf"))
        m = h44._cfgr_take(self.snap, ["svx"], "Restore point", "restore")
        self.assertEqual(m["groups"]["svx"]["missing"], [os.path.join(self.etc, "svxlink.d", "UsrpLogic.conf")])

    def test_changed_files_are_found(self):
        m = h44._cfgr_take(self.snap, ["svx"], "Restore point", "restore")
        self.assertEqual(h44._cfgr_changed_files(self.snap, m)["svx"], [])
        p = os.path.join(self.etc, "svxlink.d", "UsrpLogic.conf")
        with open(p, "a") as fh:
            fh.write("CALL=AA1AA\n")
        self.assertEqual(h44._cfgr_changed_files(self.snap, m)["svx"], [p])

    def test_installed_sees_the_real_marker_file(self):
        self.assertTrue(h44._cfgr_installed()["svx"])
        os.remove(os.path.join(self.etc, "svxlink.conf"))
        self.assertFalse(h44._cfgr_installed()["svx"])


class SvxRestart(unittest.TestCase):
    def test_restart_names_the_service_and_skips_it_when_absent(self):
        calls = []

        def fake(argv, **kw):
            calls.append(argv)
            return {"success": True, "output": "not-found\n"}

        with mock.patch.object(h44, "_run_argv", fake):
            r = h44._cfgr_act_restart({"groups": ["svx"]})
        self.assertTrue(any("svxlink-usrp" in a for a in calls))
        self.assertIn("svxlink-usrp: not on this node, skipped", r["output"])
        self.assertIn("svxreflector: not on this node, skipped", r["output"])


if __name__ == "__main__":
    unittest.main()
