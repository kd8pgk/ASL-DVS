import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="h44_identity_")


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


h44 = load("h44_identity_under_test", newest("44helper_v[0-9]*.py"))

SAMPLE = {
    "/etc/asterisk/rpt.conf": "[nodes]\n123456 = radio@127.0.0.1/123456,NONE\n\n[123456]\nidrecording = |iAA1AA\n",
    "/etc/asterisk/echolink.conf": "[el0]\ncall = AA1AA-L\nnode = 99999\npwd = hunter2\n",
    "/opt/MMDVM_Bridge/MMDVM_Bridge.ini": "[General]\nCallsign=AA1AA\nId=123456701\n\n[DMR Network]\nPassword=secretpw\n",
    "/opt/Analog_Bridge/Analog_Bridge.ini": "[AMBE_AUDIO]\ngatewayDmrId = 1234567\nrepeaterID = 123456701\n",
}


class Fake:
    def __init__(self, files):
        self.files = {k: v for k, v in files.items()}
        self.written = {}

    def read(self, path):
        v = self.files.get(path)
        return None if v is None else v.encode("utf-8")

    def write(self, path, data, uid, gid, mode):
        self.files[path] = data.decode("utf-8")
        self.written[path] = self.files[path]
        return "written"


class Base(unittest.TestCase):
    def setUp(self):
        self.fs = Fake(SAMPLE)
        self.patches = [
            mock.patch.object(h44, "_cfgr_read", self.fs.read),
            mock.patch.object(h44, "_cfgr_write_file", self.fs.write),
            mock.patch.object(h44, "_cfgr_meta_of", lambda p: (None, None, 0o644)),
            mock.patch.object(h44, "_cfgr_auto_point", lambda reason, groups: ("test-point", [])),
            mock.patch.dict(h44.__dict__, {"_cfg": None}),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])


class CallsignStillWorks(Base):
    def test_preview_lists_every_file_and_writes_nothing(self):
        r = h44._cfgr_act_id_set({"group": "callsign", "callsign": "bb2bb"}, False)
        self.assertTrue(r["success"])
        self.assertGreaterEqual(r["changes"], 3)
        self.assertIn("MMDVM_Bridge.ini", r["output"])
        self.assertIn("Set the callsign to BB2BB", r["output"])
        self.assertEqual(self.fs.written, {})

    def test_apply_writes_the_files(self):
        r = h44._cfgr_act_id_set({"group": "callsign", "callsign": "BB2BB"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("Callsign=BB2BB", self.fs.files["/opt/MMDVM_Bridge/MMDVM_Bridge.ini"])
        self.assertIn("call = BB2BB-L", self.fs.files["/etc/asterisk/echolink.conf"])
        self.assertIn("|iBB2BB", self.fs.files["/etc/asterisk/rpt.conf"])
        self.assertIn("Automatic save point: test-point", r["output"])

    def test_old_action_names_still_answer(self):
        a = h44._cfgr_act_id_set_callsign({"callsign": "BB2BB"}, False)
        b = h44._cfgr_act_id_set({"group": "callsign", "callsign": "BB2BB"}, False)
        self.assertEqual(a, b)

    def test_bad_callsign_refused(self):
        for bad in ("", "AB", "ABCDEFGH", "ABCDE", "12345", "AA 1AA"):
            r = h44._cfgr_act_id_set({"group": "callsign", "callsign": bad}, False)
            self.assertFalse(r["success"], bad)

    def test_unknown_group_refused(self):
        r = h44._cfgr_act_id_set({"group": "nope", "value": "x"}, False)
        self.assertFalse(r["success"])
        self.assertEqual(self.fs.written, {})

    def test_actions_are_registered(self):
        with open(newest("44helper_v[0-9]*.py")) as fh:
            src = fh.read()
        for name in ("id_set_preview", "id_set", "id_set_callsign_preview", "id_set_callsign"):
            self.assertIn('"%s":' % name, src)
        self.assertIn('"id_set",', src)


class ExactTarget(Base):
    def test_target_limits_the_write_to_one_line(self):
        fd = {"fid": "x", "label": "x", "src": "ini", "file": "/opt/MMDVM_Bridge/MMDVM_Bridge.ini",
              "section": "dmr network", "key": "Password", "form": "plain", "kind": "secret"}
        lines = SAMPLE["/opt/MMDVM_Bridge/MMDVM_Bridge.ini"].splitlines(keepends=True)
        hit = h44._cfgr_setcall_file(fd, fd["file"], lines, "newpw", ("DMR Network", "Password"))
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["new"], "newpw")
        miss = h44._cfgr_setcall_file(fd, fd["file"], lines, "newpw", ("General", "Password"))
        self.assertEqual(miss, [])

    def test_no_target_behaves_as_before(self):
        fd = {"fid": "x", "label": "x", "src": "ini", "file": "/opt/MMDVM_Bridge/MMDVM_Bridge.ini",
              "section": "general", "key": "Callsign", "form": "plain", "kind": "value"}
        lines = SAMPLE["/opt/MMDVM_Bridge/MMDVM_Bridge.ini"].splitlines(keepends=True)
        self.assertEqual(len(h44._cfgr_setcall_file(fd, fd["file"], lines, "ZZ9ZZ")), 1)


class Masking(unittest.TestCase):
    def test_secret_values_are_masked(self):
        self.assertEqual(h44._cfgr_set_mask({"kind": "secret"}, "hunter2"), h44._CFGR_ID_MASK)
        self.assertEqual(h44._cfgr_set_mask({"kind": "value"}, "AA1AA"), "AA1AA")
        self.assertEqual(h44._cfgr_set_mask({"kind": "secret"}, ""), "")


DMR_FILES = dict(SAMPLE)
DMR_FILES.update({
    "/opt/MMDVM_Bridge/DVSwitch.ini": "[STFU]  ; Brandmeister Open DMR Terminal\nBMPassword = pw1\nUserID  = 1234567\nTalkerAlias = AA1AA\n",
    "/opt/YSFGateway/YSFGateway.ini": "[General]\nCallsign=AA1AA\nId=123456799\n",
    "/var/lib/dvswitch/dvs/var.txt": 'call_sign="AA1AA"\ndmr_id="1234567"\nrpt_id="123456701"\nrpt_id_2="123456702"\nrpt_id_3="123456703"\nrpt_id_now=\nbm_password="pw1"\n',
})
MB = "/opt/MMDVM_Bridge/MMDVM_Bridge.ini"
AB = "/opt/Analog_Bridge/Analog_Bridge.ini"
VAR = "/var/lib/dvswitch/dvs/var.txt"
YSF = "/opt/YSFGateway/YSFGateway.ini"
DVS = "/opt/MMDVM_Bridge/DVSwitch.ini"


class DmrBase(Base):
    def setUp(self):
        super().setUp()
        self.fs.files = dict(DMR_FILES)


class DmrId(DmrBase):
    def test_bad_input_refused(self):
        for bad in ("", "123456", "12345678", "12345a7"):
            self.assertFalse(h44._cfgr_act_id_set({"group": "dmr", "value": bad}, False)["success"], bad)
        self.assertEqual(self.fs.written, {})

    def test_preview_writes_nothing(self):
        r = h44._cfgr_act_id_set({"group": "dmr", "value": "7654321"}, False)
        self.assertTrue(r["success"])
        self.assertGreater(r["changes"], 0)
        self.assertEqual(self.fs.written, {})
        for name in ("mmdvm_bridge", "analog_bridge", "stfu", "ysfgateway"):
            self.assertIn(name, r["output"])

    def test_apply_keeps_suffixes(self):
        r = h44._cfgr_act_id_set({"group": "dmr", "value": "7654321"}, True)
        self.assertTrue(r["success"], r["output"])
        f = self.fs.files
        self.assertIn("Id=765432101", f[MB])
        self.assertIn("gatewayDmrId = 7654321", f[AB])
        self.assertIn("repeaterID = 765432101", f[AB])
        self.assertIn("UserID  = 7654321", f[DVS])
        self.assertIn("Id=765432199", f[YSF])
        self.assertIn('dmr_id="7654321"', f[VAR])
        self.assertIn('rpt_id="765432101"', f[VAR])
        self.assertIn('rpt_id_2="765432102"', f[VAR])
        self.assertIn('rpt_id_3="765432103"', f[VAR])
        self.assertIn("rpt_id_now=\n", f[VAR])
        self.assertIn("Callsign=AA1AA", f[MB])
        self.assertIn("Password=secretpw", f[MB])

    def test_non_numeric_old_value_is_skipped_and_named(self):
        self.fs.files[YSF] = "[General]\nCallsign=AA1AA\nId=notanumber\n"
        r = h44._cfgr_act_id_set({"group": "dmr", "value": "7654321"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("Id=notanumber", self.fs.files[YSF])
        self.assertIn("left alone", r["output"])

    def test_missing_file_is_skipped(self):
        del self.fs.files[VAR]
        r = h44._cfgr_act_id_set({"group": "dmr", "value": "7654321"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("Not on this node, skipped", r["output"])
        self.assertIn("Id=765432101", self.fs.files[MB])


class DmrSuffix(DmrBase):
    def test_bad_input_refused(self):
        for bad in ("1", "123", "ab", "1a"):
            self.assertFalse(h44._cfgr_act_id_set({"group": "dmr_full", "value": bad}, False)["success"], bad)

    def test_apply_changes_only_the_suffix(self):
        r = h44._cfgr_act_id_set({"group": "dmr_full", "value": "05"}, True)
        self.assertTrue(r["success"], r["output"])
        f = self.fs.files
        self.assertIn("Id=123456705", f[MB])
        self.assertIn("repeaterID = 123456705", f[AB])
        self.assertIn("gatewayDmrId = 1234567\n", f[AB])
        self.assertIn('rpt_id="123456705"', f[VAR])
        self.assertIn('rpt_id_2="123456702"', f[VAR])
        self.assertIn('rpt_id_3="123456703"', f[VAR])
        self.assertIn("Id=123456799", f[YSF])
        self.assertIn('dmr_id="1234567"', f[VAR])

    def test_empty_value_removes_the_suffix(self):
        r = h44._cfgr_act_id_set({"group": "dmr_full", "value": ""}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("Id=1234567\n", self.fs.files[MB])
        self.assertIn("(none)", r["output"])

    def test_var_line_that_is_not_the_nodes_own_id_is_left_alone(self):
        self.fs.files[VAR] = self.fs.files[VAR].replace('rpt_id="123456701"', 'rpt_id="999999901"')
        r = h44._cfgr_act_id_set({"group": "dmr_full", "value": "05"}, True)
        self.assertIn('rpt_id="999999901"', self.fs.files[VAR])
        self.assertIn("not the node's own ID", r["output"])

    def test_id_without_seven_digits_is_skipped(self):
        self.fs.files[AB] = "[AMBE_AUDIO]\ngatewayDmrId = 1234567\nrepeaterID = 12345\n"
        r = h44._cfgr_act_id_set({"group": "dmr_full", "value": "05"}, True)
        self.assertIn("repeaterID = 12345\n", self.fs.files[AB])
        self.assertIn("has no 7-digit DMR ID", r["output"])


class DmrRows(unittest.TestCase):
    def test_var_rpt_rows_are_read_by_the_card(self):
        fids = {fd["fid"] for fd in h44._CFGR_ID_FIELDS}
        self.assertTrue({"var_rpt_id", "var_rpt_id_2", "var_rpt_id_3"} <= fids)
        for fd in h44._CFGR_ID_FIELDS:
            if fd["fid"].startswith("var_rpt_id"):
                self.assertEqual(fd["groups"], ("dmr",))


if __name__ == "__main__":
    unittest.main()
