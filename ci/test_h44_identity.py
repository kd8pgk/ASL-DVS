import glob
import json
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


ALLMON = "/etc/allmon3/allmon3.ini"
MANAGER = "/etc/asterisk/manager.conf"
SEC_FILES = dict(DMR_FILES)
SEC_FILES.update({
    ALLMON: "[123456]\nhost=127.0.0.1\nuser=amiuser\npass=oldami\n\n[1999]\nhost=127.0.0.1\nuser=amiuser\npass=oldami\n\n[1917]\nhost=127.0.0.1\nuser=amiuser\npass=oldami\n",
    MANAGER: "[general]\nenabled = yes\n\n[amiuser]\nsecret = oldami\nread = all\n\n[otheruser]\nsecret = keepme\n",
})


class SecBase(Base):
    def setUp(self):
        super().setUp()
        self.fs.files = dict(SEC_FILES)


class WriteFailure(SecBase):
    def test_a_failed_write_puts_the_earlier_files_back(self):
        real = self.fs.write
        calls = []

        def flaky(path, data, uid, gid, mode):
            calls.append(path)
            if path == MANAGER and len([c for c in calls if c == MANAGER]) == 1:
                return "NOT written: disk full"
            return real(path, data, uid, gid, mode)

        with mock.patch.object(h44, "_cfgr_write_file", flaky):
            r = h44._cfgr_act_id_set({"group": "ami", "value": "n3wAMI"}, True)
        self.assertFalse(r["success"])
        self.assertEqual(self.fs.files[ALLMON], SEC_FILES[ALLMON])
        self.assertEqual(self.fs.files[MANAGER], SEC_FILES[MANAGER])
        self.assertIn("put back", r["output"])


class BmPassword(SecBase):
    def test_bad_input_refused(self):
        for bad in ("", "has space", 'q"uote', "q'uote", "dol$lar", "back`tick", "back\\slash", "x" * 65):
            self.assertFalse(h44._cfgr_act_id_set({"group": "bm_pw", "value": bad}, False)["success"], bad)

    def test_apply_writes_both_files_and_masks_the_output(self):
        r = h44._cfgr_act_id_set({"group": "bm_pw", "value": "n3wBMpass"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("BMPassword = n3wBMpass", self.fs.files[DVS])
        self.assertIn('bm_password="n3wBMpass"', self.fs.files[VAR])
        self.assertNotIn("n3wBMpass", r["output"])
        self.assertNotIn("pw1", r["output"])
        self.assertIn(h44._CFGR_ID_MASK, r["output"])
        self.assertIn("stfu", r["output"])
        self.assertIn("Password=secretpw", self.fs.files[MB])

    def test_preview_writes_nothing(self):
        r = h44._cfgr_act_id_set({"group": "bm_pw", "value": "n3wBMpass"}, False)
        self.assertTrue(r["success"])
        self.assertEqual(self.fs.written, {})
        self.assertNotIn("n3wBMpass", r["output"])

    def test_note_when_the_dmr_network_password_holds_the_old_one(self):
        self.fs.files[MB] = self.fs.files[MB].replace("Password=secretpw", "Password=pw1")
        r = h44._cfgr_act_id_set({"group": "bm_pw", "value": "n3wBMpass"}, True)
        self.assertIn("holds the old BrandMeister password", r["output"])
        self.assertIn("Password=pw1", self.fs.files[MB])

    def test_no_note_when_they_differ(self):
        r = h44._cfgr_act_id_set({"group": "bm_pw", "value": "n3wBMpass"}, False)
        self.assertNotIn("holds the old BrandMeister password", r["output"])


class AmiSecret(SecBase):
    def test_bad_input_refused(self):
        for bad in ("", "has space", "semi;colon", "ha#sh", "per%cent", "eq=ual", "dol$lar", "x" * 65):
            self.assertFalse(h44._cfgr_act_id_set({"group": "ami", "value": bad}, False)["success"], bad)

    def test_apply_writes_every_allmon_section_and_the_manager_user(self):
        r = h44._cfgr_act_id_set({"group": "ami", "value": "n3wAMI"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertEqual(self.fs.files[ALLMON].count("pass=n3wAMI"), 3)
        self.assertNotIn("oldami", self.fs.files[ALLMON])
        self.assertIn("secret = n3wAMI", self.fs.files[MANAGER])
        self.assertNotIn("n3wAMI", r["output"])
        self.assertNotIn("oldami", r["output"])
        self.assertIn("allmon3", r["output"])
        self.assertIn("asterisk", r["output"])

    def test_manager_user_not_in_allmon_is_left_alone(self):
        h44._cfgr_act_id_set({"group": "ami", "value": "n3wAMI"}, True)
        self.assertIn("secret = keepme", self.fs.files[MANAGER])

    def test_other_keys_are_untouched(self):
        h44._cfgr_act_id_set({"group": "ami", "value": "n3wAMI"}, True)
        self.assertIn("user=amiuser", self.fs.files[ALLMON])
        self.assertIn("read = all", self.fs.files[MANAGER])

    def test_missing_allmon_still_writes_manager_for_every_user(self):
        del self.fs.files[ALLMON]
        r = h44._cfgr_act_id_set({"group": "ami", "value": "n3wAMI"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("secret = n3wAMI", self.fs.files[MANAGER])
        self.assertIn("secret = n3wAMI\n", self.fs.files[MANAGER].split("[otheruser]")[1])


REGS = "/etc/asterisk/rpt_http_registrations.conf"
SAVENODE = "/etc/asterisk/savenode.conf"
NODE_FILES = dict(SEC_FILES)
NODE_FILES.update({
    REGS: "[general]\nregister_interval = 180 ; every 3 minutes\n\n[registrations]\n;register => 123456:commentedpw@register.allstarlink.org\nregister => 123456:oldnodepw@register.allstarlink.org ; main\n",
    SAVENODE: "NODE=123456\nPASSWORD=oldnodepw\nENABLE=1\n",
})


class NodeBase(Base):
    def setUp(self):
        super().setUp()
        self.fs.files = dict(NODE_FILES)


class NodePassword(NodeBase):
    def test_bad_input_refused(self):
        for bad in ("", "has space", "co:lon", "a@t", "semi;colon", 'q"uote', "q'uote", "dol$lar", "x" * 65):
            self.assertFalse(h44._cfgr_act_id_set({"group": "node_pw", "value": bad}, False)["success"], bad)
        self.assertEqual(self.fs.written, {})

    def test_one_node_writes_registration_and_savenode(self):
        r = h44._cfgr_act_id_set({"group": "node_pw", "value": "n3wNodePw"}, True)
        self.assertTrue(r["success"], r["output"])
        reg = self.fs.files[REGS]
        self.assertIn("register => 123456:n3wNodePw@register.allstarlink.org ; main", reg)
        self.assertIn(";register => 123456:commentedpw@register.allstarlink.org", reg)
        self.assertIn("PASSWORD=n3wNodePw", self.fs.files[SAVENODE])
        self.assertIn("NODE=123456", self.fs.files[SAVENODE])
        for text in (r["output"],):
            self.assertNotIn("n3wNodePw", text)
            self.assertNotIn("oldnodepw", text)
        self.assertIn("asterisk", r["output"])
        self.assertIn("allstarlink.org", r["output"])

    def test_preview_writes_nothing(self):
        r = h44._cfgr_act_id_set({"group": "node_pw", "value": "n3wNodePw"}, False)
        self.assertTrue(r["success"])
        self.assertEqual(self.fs.written, {})

    def test_several_nodes_ask_which(self):
        self.fs.files[REGS] += "register => 654321:otherpw@register.allstarlink.org\n"
        r = h44._cfgr_act_id_set({"group": "node_pw", "value": "n3wNodePw"}, False)
        self.assertFalse(r["success"])
        self.assertIn("123456", r["output"])
        self.assertIn("654321", r["output"])
        self.assertEqual(self.fs.written, {})

    def test_chosen_node_changes_only_its_own_line(self):
        self.fs.files[REGS] += "register => 654321:otherpw@register.allstarlink.org\n"
        r = h44._cfgr_act_id_set({"group": "node_pw", "value": "n3wNodePw", "node": "654321"}, True)
        self.assertTrue(r["success"], r["output"])
        reg = self.fs.files[REGS]
        self.assertIn("register => 654321:n3wNodePw@register.allstarlink.org", reg)
        self.assertIn("123456:oldnodepw@", reg)
        self.assertEqual(self.fs.files[SAVENODE], NODE_FILES[SAVENODE])
        self.assertIn("savenode.conf holds node 123456", r["output"])

    def test_unregistered_node_refused(self):
        r = h44._cfgr_act_id_set({"group": "node_pw", "value": "n3wNodePw", "node": "999999"}, False)
        self.assertFalse(r["success"])
        self.assertIn("999999", r["output"])

    def test_missing_savenode_is_noted_and_registration_still_written(self):
        del self.fs.files[SAVENODE]
        r = h44._cfgr_act_id_set({"group": "node_pw", "value": "n3wNodePw"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("123456:n3wNodePw@", self.fs.files[REGS])
        self.assertIn("savenode.conf is not on this node", r["output"])

    def test_other_files_untouched(self):
        h44._cfgr_act_id_set({"group": "node_pw", "value": "n3wNodePw"}, True)
        self.assertEqual(set(self.fs.written), {REGS, SAVENODE})


IAX = "/etc/asterisk/iax.conf"
IAXRPT = "/etc/asterisk/custom/iax/iaxrpt-users.conf"
IRCDDB = "/etc/ircddbgateway"
ECHO = "/etc/asterisk/echolink.conf"
ALONE_FILES = dict(NODE_FILES)
ALONE_FILES[MB] = ALONE_FILES[MB] + "\n[NXDN]\nId=12345\n"
ALONE_FILES[VAR] = ALONE_FILES[VAR] + 'tgif_password="tgifold"\nnxdn_id="12345"\n'
ALONE_FILES[IAX] = "[general]\nbindport=4569\n\n[iaxrpt]\ntype=user\nsecret=iaxold1\n\n[iaxclient]\ntype=user\nsecret=iaxold2\n"
ALONE_FILES[IAXRPT] = "[iaxrpt]\ntype=user\nsecret=iaxold3\n"
ALONE_FILES[IRCDDB] = "gatewayCallsign=AA1AA\nircddbPassword=ircold\nremotePassword=remold\n"


class AloneBase(Base):
    def setUp(self):
        super().setUp()
        self.fs.files = dict(ALONE_FILES)

    def rid(self, fid, file=None):
        for r in h44._cfgr_identity_scan()["rows"]:
            if r["fid"] == fid and (file is None or r["file"] == file):
                return r["rid"]
        self.fail("no row " + fid)

    def go(self, fid, value, apply=True, file=None):
        return h44._cfgr_act_id_set({"group": "alone", "rid": self.rid(fid, file), "value": value}, apply)


class StandsAlone(AloneBase):
    def test_rows_are_flagged_settable(self):
        rows = {r["fid"]: r["settable"] for r in h44._cfgr_identity_scan()["rows"]}
        for fid in ("el_node", "el_pwd", "iax_secret", "mb_dmr_pw", "mb_nxdn_id", "stfu_ta", "var_tgif_pw",
                    "ircddb_pw", "ircddb_remote_pw", "var_nxdn_id"):
            self.assertTrue(rows[fid], fid)
        self.assertFalse(rows["mb_call"])

    def test_unknown_or_unsettable_row_refused(self):
        self.assertFalse(h44._cfgr_act_id_set({"group": "alone", "rid": "mb_call#0", "value": "X1X"}, True)["success"])
        self.assertFalse(h44._cfgr_act_id_set({"group": "alone", "rid": "nope#0", "value": "x"}, True)["success"])
        self.assertFalse(h44._cfgr_act_id_set({"group": "alone", "rid": "", "value": "x"}, True)["success"])
        self.assertEqual(self.fs.written, {})

    def test_stale_rid_refused(self):
        r = h44._cfgr_act_id_set({"group": "alone", "rid": "el_pwd#7", "value": "newpw"}, True)
        self.assertFalse(r["success"])
        self.assertIn("Reload", r["output"])

    def test_bad_input_refused_per_row(self):
        cases = {"el_node": ("12ab", "12345678", ""), "el_pwd": ("a b", "a;b", 'a"b'),
                 "iax_secret": ("a b", "a$b", "a;b"), "mb_dmr_pw": ("a b", "a#b", "a'b"),
                 "mb_nxdn_id": ("123456", "12a", ""), "stfu_ta": ("", "a;b", "x" * 31),
                 "var_tgif_pw": ("a b", "a$b", "a`b"), "ircddb_pw": ("a b", 'a"b', "a\\b"),
                 "ircddb_remote_pw": ("a b", "a'b", "")}
        for fid, bads in cases.items():
            for bad in bads:
                self.assertFalse(self.go(fid, bad, False)["success"], (fid, bad))
        self.assertEqual(self.fs.written, {})

    def test_echolink_node_and_password(self):
        r = self.go("el_node", "88888")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("node = 88888", self.fs.files[ECHO])
        r = self.go("el_pwd", "newelpw")
        self.assertIn("pwd = newelpw", self.fs.files[ECHO])
        self.assertIn("call = AA1AA-L", self.fs.files[ECHO])
        self.assertNotIn("newelpw", r["output"])
        self.assertNotIn("hunter2", r["output"])

    def test_each_iax_row_changes_only_its_own_line(self):
        rows = [r for r in h44._cfgr_identity_scan()["rows"] if r["fid"] == "iax_secret"]
        self.assertEqual(len(rows), 3)
        r = h44._cfgr_act_id_set({"group": "alone", "rid": rows[0]["rid"], "value": "brandnew"}, True)
        self.assertTrue(r["success"], r["output"])
        before = {k: v for k, v in ALONE_FILES.items() if k in (IAX, IAXRPT)}
        changed = [k for k in (IAX, IAXRPT) if self.fs.files[k] != before[k]]
        self.assertEqual(changed, [rows[0]["file"]])
        self.assertEqual(self.fs.files[rows[0]["file"]].count("brandnew"), 1)
        self.assertEqual(sum(self.fs.files[k].count("secret=iaxold") for k in (IAX, IAXRPT)), 2)

    def test_same_section_name_in_two_files_is_separate(self):
        rpt_rows = [r for r in h44._cfgr_identity_scan()["rows"] if r["fid"] == "iax_secret" and "iaxrpt" in r["where"]]
        self.assertEqual({r["file"] for r in rpt_rows}, {IAX, IAXRPT})
        row = next(r for r in rpt_rows if r["file"] == IAXRPT)
        h44._cfgr_act_id_set({"group": "alone", "rid": row["rid"], "value": "fileonly"}, True)
        self.assertIn("secret=fileonly", self.fs.files[IAXRPT])
        self.assertIn("secret=iaxold1", self.fs.files[IAX])

    def test_dmr_network_password_only(self):
        r = self.go("mb_dmr_pw", "dmrnewpw")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("Password=dmrnewpw", self.fs.files[MB])
        self.assertIn("mmdvm_bridge", r["output"])
        self.assertNotIn("dmrnewpw", r["output"])
        self.assertIn("BMPassword = pw1", self.fs.files[DVS])

    def test_nxdn_id_also_writes_var_txt(self):
        r = self.go("mb_nxdn_id", "54321")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("[NXDN]\nId=54321", self.fs.files[MB])
        self.assertIn('nxdn_id="54321"', self.fs.files[VAR])
        self.assertIn("Id=123456701", self.fs.files[MB])

    def test_var_nxdn_row_alone_changes_only_var_txt(self):
        self.go("var_nxdn_id", "11111")
        self.assertIn('nxdn_id="11111"', self.fs.files[VAR])
        self.assertIn("[NXDN]\nId=12345", self.fs.files[MB])

    def test_talker_alias_keeps_spaces(self):
        r = self.go("stfu_ta", "My Node 1")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("TalkerAlias = My Node 1", self.fs.files[DVS])
        self.assertIn("My Node 1", r["output"])
        self.assertIn("stfu", r["output"])

    def test_tgif_password_has_no_restart(self):
        r = self.go("var_tgif_pw", "tgifnew")
        self.assertTrue(r["success"], r["output"])
        self.assertIn('tgif_password="tgifnew"', self.fs.files[VAR])
        self.assertNotIn("Restart these", r["output"])

    def test_ircddb_passwords(self):
        r = self.go("ircddb_pw", "ircnew")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("ircddbPassword=ircnew", self.fs.files[IRCDDB])
        self.assertIn("remotePassword=remold", self.fs.files[IRCDDB])
        self.go("ircddb_remote_pw", "remnew")
        self.assertIn("remotePassword=remnew", self.fs.files[IRCDDB])
        self.assertIn("ircddbgatewayd", r["output"])

    def test_preview_writes_nothing_and_masks(self):
        r = self.go("el_pwd", "newelpw", apply=False)
        self.assertTrue(r["success"])
        self.assertEqual(self.fs.written, {})
        self.assertNotIn("newelpw", r["output"])
        self.assertIn("the line below", r["output"])


class InlineComments(DmrBase):
    def setUp(self):
        super().setUp()
        self.fs.files[AB] = ("[AMBE_AUDIO]\ngatewayDmrId = 1234567                  ; ID to use when transmitting\n"
                             "repeaterID = 123456701                  ; ID of source repeater\n")
        self.fs.files[DVS] = ("[STFU]                          ; Brandmeister Open DMR Terminal\n"
                              "BMPassword = pw1           ; Your Brandmeister password\n"
                              "UserID  = 1234567               ; Your DMR ID\n"
                              "TalkerAlias = N0CALL Name City  ; Max 27 characters\n")

    def test_the_card_reads_the_value_without_the_comment(self):
        rows = {r["fid"]: r["raw"] for r in h44._cfgr_identity_scan()["rows"]}
        self.assertEqual(rows["ab_gw_id"], "1234567")
        self.assertEqual(rows["ab_rpt_id"], "123456701")
        self.assertEqual(rows["stfu_id"], "1234567")
        self.assertEqual(rows["stfu_pw"], "pw1")
        self.assertEqual(rows["stfu_ta"], "N0CALL Name City")

    def test_dmr_groups_match_when_only_comments_differ(self):
        g = h44._cfgr_identity_scan()["groups"]
        self.assertEqual(g["dmr"]["state"], "match")
        self.assertEqual(g["bm_pw"]["state"], "match")

    def test_dmr_id_is_written_and_the_comment_kept(self):
        r = h44._cfgr_act_id_set({"group": "dmr", "value": "7654321"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("gatewayDmrId = 7654321                  ; ID to use when transmitting", self.fs.files[AB])
        self.assertIn("repeaterID = 765432101                  ; ID of source repeater", self.fs.files[AB])
        self.assertIn("UserID  = 7654321               ; Your DMR ID", self.fs.files[DVS])
        self.assertNotIn("left alone", r["output"])

    def test_suffix_is_written_and_the_comment_kept(self):
        h44._cfgr_act_id_set({"group": "dmr_full", "value": "05"}, True)
        self.assertIn("repeaterID = 123456705                  ; ID of source repeater", self.fs.files[AB])

    def test_bm_password_keeps_the_comment_and_sees_the_old_value(self):
        self.fs.files[MB] = self.fs.files[MB].replace("Password=secretpw", "Password=pw1")
        r = h44._cfgr_act_id_set({"group": "bm_pw", "value": "n3wBMpass"}, True)
        self.assertIn("BMPassword = n3wBMpass           ; Your Brandmeister password", self.fs.files[DVS])
        self.assertIn("holds the old BrandMeister password", r["output"])

    def test_talker_alias_row_keeps_the_comment(self):
        rid = next(r["rid"] for r in h44._cfgr_identity_scan()["rows"] if r["fid"] == "stfu_ta")
        r = h44._cfgr_act_id_set({"group": "alone", "rid": rid, "value": "My Node"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("TalkerAlias = My Node  ; Max 27 characters", self.fs.files[DVS])

    def test_callsign_values_without_comments_are_unchanged(self):
        r = h44._cfgr_act_id_set({"group": "callsign", "callsign": "BB2BB"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("Callsign=BB2BB\n", self.fs.files[MB])
ASLDVS = "/etc/asl_dvs/asl_dvs.conf"
NT = "/etc/asl_dvs/nodetalker.conf"
NL = "/etc/asl_dvs/nodelisten.conf"
SYSMON = "/etc/sysmon/sysmon.conf"
EXT = "/etc/asterisk/extensions.conf"
RPT = "/etc/asterisk/rpt.conf"
SIMPLEUSB = "/etc/asterisk/simpleusb.conf"
WEBINI = "/etc/allmon3/web.ini"
RENAME_FILES = dict(NODE_FILES)
RENAME_FILES.update({
    RPT: "[general]\nx = 1\n\n[nodes]\n123456 = radio@127.0.0.1/123456,NONE\n1999 = radio@127.0.0.1/1999,NONE\n\n"
         "[123456](node-main)\nrxchannel = SimpleUSB/123456\nidrecording = |iAA1AA\nnote_pass = see 123456 pass\n\n"
         "[1999](node-main)\nrxchannel = USRP/127.0.0.1:34008:32008\n",
    ALLMON: "[123456]\nhost=127.0.0.1\nuser=amiuser\npass=oldami\n\n[1999]\nhost=127.0.0.1\nuser=amiuser\npass=oldami\n",
    ECHO: "[el0]\ncall = AA1AA-L\nastnode = 123456\nnode = 99999\npwd = hunter2\n",
    EXT: "[globals]\nNODE = 123456\nHOMENPA = 330\n\n[radio-secure]\nexten => 123456,1,rpt,123456\nexten => 1999,1,rpt,1999\n",
    ASLDVS: "[CONFIG]\nasl_node=123456\nbridge_node=1999\nport=8989\n",
    NT: "[nodetalker]\nport = 8993\nnode = 123456\n",
    NL: "[nodetalker]\nport = 8993\nnode = 123456\n\n[nodelisten]\nport = 8993\nnode = 123456\n",
    SYSMON: "[identity]\ncallsign = AA1AA\nnode = 123456\nlabel = Radio Node 123456\n",
    SIMPLEUSB: "[123456](node-main)\ndevstr = x\n",
    WEBINI: "CONFIG_HEADER_TITLE = Allmon3 123456 Radio Node\n",
})


class RenameBase(Base):
    def setUp(self):
        super().setUp()
        self.fs.files = dict(RENAME_FILES)

    def rename(self, value, apply=True, node=None):
        p = {"group": "node", "value": value}
        if node:
            p["node"] = node
        return h44._cfgr_act_id_set(p, apply)


class NodeRename(RenameBase):
    def test_bad_new_number_refused(self):
        for bad in ("", "123", "12345678", "12ab56", "1500", "1000", "1999"):
            self.assertFalse(self.rename(bad, False)["success"], bad)
        self.assertEqual(self.fs.written, {})

    def test_same_number_refused(self):
        self.assertFalse(self.rename("123456", False)["success"])

    def test_number_already_used_refused(self):
        self.fs.files[ALLMON] += "\n[654321]\nhost=x\nuser=u\npass=p\n"
        r = self.rename("654321", True)
        self.assertFalse(r["success"])
        self.assertIn("already used", r["output"])
        self.assertEqual(self.fs.written, {})

    def test_preview_writes_nothing_and_lists_leftovers(self):
        r = self.rename("654321", False)
        self.assertTrue(r["success"], r["output"])
        self.assertEqual(self.fs.written, {})
        self.assertIn("rpt.conf", r["output"])
        self.assertIn("rxchannel = SimpleUSB/123456", r["output"])
        self.assertIn("label = Radio Node 123456", r["output"])
        self.assertIn("simpleusb.conf", r["output"])
        self.assertIn("web.ini", r["output"])
        self.assertIn("(line hidden: may hold a secret)", r["output"])
        self.assertNotIn("oldnodepw", r["output"])
        self.assertNotIn("oldami", r["output"])
        self.assertIn("allstarlink.org", r["output"])

    def test_apply_renames_every_listed_line(self):
        r = self.rename("654321", True)
        self.assertTrue(r["success"], r["output"])
        f = self.fs.files
        self.assertIn("[654321](node-main)\nrxchannel = SimpleUSB/123456", f[RPT])
        self.assertIn("654321 = radio@127.0.0.1/654321,NONE", f[RPT])
        self.assertNotIn("123456 = radio", f[RPT])
        self.assertIn("1999 = radio@127.0.0.1/1999,NONE", f[RPT])
        self.assertIn("register => 654321:oldnodepw@register.allstarlink.org ; main", f[REGS])
        self.assertIn(";register => 123456:commentedpw@", f[REGS])
        self.assertIn("NODE=654321\nPASSWORD=oldnodepw", f[SAVENODE])
        self.assertIn("[654321]\nhost=127.0.0.1", f[ALLMON])
        self.assertIn("[1999]\nhost", f[ALLMON])
        self.assertIn("astnode = 654321", f[ECHO])
        self.assertIn("node = 99999", f[ECHO])
        self.assertIn("NODE = 654321", f[EXT])
        self.assertIn("exten => 654321,1,rpt,654321", f[EXT])
        self.assertIn("exten => 1999,1,rpt,1999", f[EXT])
        self.assertIn("asl_node=654321", f[ASLDVS])
        self.assertIn("node = 654321", f[NT])
        self.assertEqual(f[NL].count("node = 654321"), 2)
        self.assertIn("node = 654321\nlabel = Radio Node 123456", f[SYSMON])
        self.assertEqual(f[SIMPLEUSB], RENAME_FILES[SIMPLEUSB])
        self.assertEqual(f[WEBINI], RENAME_FILES[WEBINI])
        self.assertNotIn("oldnodepw", r["output"])
        for name in ("asterisk", "allmon3", "nodecontrol", "nodetalker", "nodelisten", "sysmon"):
            self.assertIn(name, r["output"])

    def test_two_public_nodes_ask_which(self):
        self.fs.files[RPT] += "\n[222222](node-main)\nrxchannel = SimpleUSB/222222\n"
        r = self.rename("654321", False)
        self.assertFalse(r["success"])
        self.assertIn("123456", r["output"])
        self.assertIn("222222", r["output"])
        r = self.rename("654321", True, node="222222")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("[654321](node-main)", self.fs.files[RPT])
        self.assertIn("[123456](node-main)", self.fs.files[RPT])
        self.assertEqual(self.fs.files[SAVENODE], RENAME_FILES[SAVENODE])
        self.assertEqual(self.fs.files[ASLDVS], RENAME_FILES[ASLDVS])

    def test_private_or_unknown_node_refused_as_the_old_one(self):
        self.assertFalse(self.rename("654321", False, node="1999")["success"])
        self.assertFalse(self.rename("654321", False, node="999999")["success"])

    def test_missing_tool_files_are_skipped(self):
        for path in (NT, NL, SYSMON, ASLDVS):
            del self.fs.files[path]
        r = self.rename("654321", True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("Not on this node, skipped", r["output"])
        self.assertIn("[654321](node-main)", self.fs.files[RPT])

    def test_no_stanza_in_rpt_conf_changes_nothing(self):
        self.fs.files[RPT] = "[nodes]\n123456 = radio@127.0.0.1/123456,NONE\n[123456]\n"
        self.fs.files[RPT] = self.fs.files[RPT].replace("[123456]", "[1999]")
        r = self.rename("654321", True)
        self.assertFalse(r["success"])
        self.assertEqual(self.fs.written, {})

    def test_a_failed_write_puts_everything_back(self):
        real = self.fs.write
        calls = []

        def flaky(path, data, uid, gid, mode):
            calls.append(path)
            if path == NL and calls.count(NL) == 1:
                return "NOT written: disk full"
            return real(path, data, uid, gid, mode)

        with mock.patch.object(h44, "_cfgr_write_file", flaky):
            r = self.rename("654321", True)
        self.assertFalse(r["success"])
        for path, text in RENAME_FILES.items():
            self.assertEqual(self.fs.files[path], text, path)
        self.assertIn("put back", r["output"])

    def test_the_helpers_own_node_is_updated(self):
        import configparser
        cfg = configparser.ConfigParser()
        cfg["identity"] = {"callsign": "AA1AA", "node": "123456"}
        saved = []
        with mock.patch.dict(h44.__dict__, {"_cfg": cfg}), mock.patch.object(h44, "save_config", lambda c: saved.append(c.get("identity", "node"))):
            r = self.rename("654321", True)
        self.assertTrue(r["success"], r["output"])
        self.assertEqual(cfg.get("identity", "node"), "654321")
        self.assertEqual(saved, ["654321"])


SVX = "/usr/local/etc/svxlink/svxlink.conf"
SVXU = "/usr/local/etc/svxlink/svxlink.d/UsrpLogic.conf"
SVXE = "/usr/local/etc/svxlink/svxlink.d/ModuleEchoLink.conf"
SVX_FILES = dict(DMR_FILES)
SVX_FILES.update({
    SVX: ("[GLOBAL]\nLOGICS=SimplexLogic,UsrpLogic\nLINKS=LinkToUsrp\n\n[SimplexLogic]\nTYPE=Simplex\nCALLSIGN=AA1AA\n\n"
          "[RepeaterLogic]\nTYPE=Repeater\nCALLSIGN=AA1AA\n\n[ReflectorLogic]\nTYPE=Reflector\n"
          "HOSTS=reflector.example.org\nCALLSIGN=\"AA1AA\"\n#AUTH_KEY=\"Change this key now!\"\n\n"
          "[UsrpLogic]\nTYPE=Usrp\nUSRP_HOST=127.0.0.1\nUSRP_TX_PORT=32000\nUSRP_RX_PORT=34000\nCALL=AA1AA\n#DMRID=1234567\n\n"
          "[NetRx]\nTYPE=Net\nAUTH_KEY=\"Change this key now!\"\n\n[LocationInfo]\nCALLSIGN=AA1AA\n"),
    SVXU: "[UsrpLogic]\nTYPE=Usrp\nUSRP_HOST=127.0.0.1\nUSRP_TX_PORT=32000\nUSRP_RX_PORT=34000\nCALL=AA1AA\n#DMRID=1234567\n",
    SVXE: "[ModuleEchoLink]\nNAME=EchoLink\nCALLSIGN=AA1AA-L\nPASSWORD=MyPass\nSYSOPNAME=MyName\nLOCATION=[Svx] Fq, MyTown\n",
})


class SvxBase(Base):
    def setUp(self):
        super().setUp()
        self.fs.files = dict(SVX_FILES)

    def rows(self):
        return {r["fid"]: r for r in h44._cfgr_identity_scan()["rows"]}


class SvxReadRows(SvxBase):
    def test_every_field_is_read_from_the_right_place(self):
        r = self.rows()
        self.assertEqual(r["svx_simplex_call"]["raw"], "AA1AA")
        self.assertEqual(r["svx_repeater_call"]["raw"], "AA1AA")
        self.assertEqual(r["svx_reflector_call"]["raw"], "AA1AA")
        self.assertEqual(r["svx_usrp_call"]["raw"], "AA1AA")
        self.assertEqual(r["svx_usrp_call"]["file"], SVX)
        self.assertEqual(r["svx_usrp_call_d"]["file"], SVXU)
        self.assertEqual(r["svx_el_call"]["raw"], "AA1AA-L")
        self.assertEqual(r["svx_el_call"]["value"], "AA1AA")
        self.assertEqual(r["svx_el_pw"]["raw"], "MyPass")
        self.assertEqual(r["svx_el_pw"]["kind"], "secret")
        self.assertEqual(r["svx_el_sysop"]["raw"], "MyName")
        self.assertEqual(r["svx_el_location"]["raw"], "[Svx] Fq, MyTown")

    def test_commented_out_lines_give_no_row(self):
        r = self.rows()
        self.assertNotIn("svx_usrp_dmrid", r)
        self.assertNotIn("svx_usrp_dmrid_d", r)
        self.assertNotIn("svx_refl_key", r)

    def test_active_dmrid_and_reflector_key_are_read(self):
        self.fs.files[SVX] = self.fs.files[SVX].replace("#DMRID=1234567", "DMRID=1234567").replace(
            '#AUTH_KEY="Change this key now!"\n\n[UsrpLogic]', 'AUTH_KEY="reflkey"\n\n[UsrpLogic]')
        self.fs.files[SVXU] = self.fs.files[SVXU].replace("#DMRID=1234567", "DMRID=1234567")
        r = self.rows()
        self.assertEqual(r["svx_usrp_dmrid"]["raw"], "1234567")
        self.assertEqual(r["svx_usrp_dmrid_d"]["raw"], "1234567")
        self.assertEqual(r["svx_refl_key"]["raw"], "reflkey")
        self.assertEqual(r["svx_refl_key"]["kind"], "secret")
        self.assertEqual(h44._cfgr_identity_scan()["groups"]["dmr"]["state"], "match")

    def test_other_sections_auth_key_is_not_taken_for_the_reflector(self):
        self.assertNotIn("svx_refl_key", self.rows())

    def test_location_info_callsign_is_not_read(self):
        self.fs.files[SVX] = self.fs.files[SVX].replace("[LocationInfo]\nCALLSIGN=AA1AA", "[LocationInfo]\nCALLSIGN=ZZ9ZZ")
        self.assertEqual(h44._cfgr_identity_scan()["groups"]["callsign"]["state"], "match")

    def test_callsign_group_matches_with_quotes_and_suffix(self):
        self.assertEqual(h44._cfgr_identity_scan()["groups"]["callsign"]["state"], "match")

    def test_the_two_usrplogic_copies_are_flagged_when_they_differ(self):
        self.fs.files[SVXU] = self.fs.files[SVXU].replace("CALL=AA1AA", "CALL=BB2BB")
        d = h44._cfgr_identity_scan()
        self.assertEqual(d["groups"]["callsign"]["state"], "differs")
        tags = {r["fid"]: r["tags"].get("callsign") for r in d["rows"]}
        self.assertNotEqual(tags["svx_usrp_call"], tags["svx_usrp_call_d"])

    def test_stock_template_callsign_shows_as_differs(self):
        self.fs.files[SVXE] = self.fs.files[SVXE].replace("CALLSIGN=AA1AA-L", "CALLSIGN=MYCALL-L")
        self.assertEqual(h44._cfgr_identity_scan()["groups"]["callsign"]["state"], "differs")

    def test_no_svxlink_files_means_no_svxlink_rows(self):
        for p in (SVX, SVXU, SVXE):
            del self.fs.files[p]
        self.assertFalse([f for f in self.rows() if f.startswith("svx_")])

    def test_stands_alone_rows_are_settable(self):
        r = self.rows()
        for fid in ("svx_el_pw", "svx_el_sysop", "svx_el_location"):
            self.assertTrue(r[fid]["settable"], fid)

    def test_values_are_masked_until_revealed(self):
        pub = {r["fid"]: r for r in h44._cfgr_identity_public(False)["rows"]}
        self.assertEqual(pub["svx_el_pw"]["raw"], h44._CFGR_ID_MASK)
        self.assertEqual(pub["svx_simplex_call"]["raw"], h44._CFGR_ID_MASK)
        rev = {r["fid"]: r for r in h44._cfgr_identity_public(True)["rows"]}
        self.assertEqual(rev["svx_el_pw"]["raw"], "MyPass")


class SvxSectionWrites(SvxBase):
    def test_callsign_set_everywhere_writes_svxlink_and_keeps_quotes_and_suffix(self):
        r = h44._cfgr_act_id_set({"group": "callsign", "callsign": "BB2BB"}, True)
        self.assertTrue(r["success"], r["output"])
        f = self.fs.files
        self.assertIn("[SimplexLogic]\nTYPE=Simplex\nCALLSIGN=BB2BB", f[SVX])
        self.assertIn("[RepeaterLogic]\nTYPE=Repeater\nCALLSIGN=BB2BB", f[SVX])
        self.assertIn('CALLSIGN="BB2BB"', f[SVX])
        self.assertIn("USRP_RX_PORT=34000\nCALL=BB2BB", f[SVX])
        self.assertIn("CALL=BB2BB", f[SVXU])
        self.assertIn("CALLSIGN=BB2BB-L", f[SVXE])
        self.assertIn("[LocationInfo]\nCALLSIGN=AA1AA", f[SVX])
        self.assertIn("PASSWORD=MyPass", f[SVXE])
        self.assertIn("svxlink-usrp", r["output"])

    def test_dmr_id_writes_an_active_dmrid_and_leaves_a_commented_one(self):
        r = h44._cfgr_act_id_set({"group": "dmr", "value": "7654321"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("#DMRID=1234567", self.fs.files[SVX])
        self.assertIn("#DMRID=1234567", self.fs.files[SVXU])
        self.fs.files[SVXU] = self.fs.files[SVXU].replace("#DMRID=1234567", "DMRID=1234567")
        r = h44._cfgr_act_id_set({"group": "dmr", "value": "1112223"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("\nDMRID=1112223", self.fs.files[SVXU])
        self.assertIn("svxlink-usrp", r["output"])

    def test_a_node_without_svxlink_lists_it_as_skipped_and_still_works(self):
        for p in (SVX, SVXU, SVXE):
            del self.fs.files[p]
        r = h44._cfgr_act_id_set({"group": "callsign", "callsign": "BB2BB"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("Callsign=BB2BB", self.fs.files[MB])
        self.assertNotIn("svxlink-usrp", r["output"].split("Restart these")[-1])


class SvxStandsAlone(SvxBase):
    def setUp(self):
        super().setUp()
        self.fs.files[SVX] = self.fs.files[SVX].replace(
            '#AUTH_KEY="Change this key now!"\n\n[UsrpLogic]', 'AUTH_KEY="oldreflkey"\n\n[UsrpLogic]')

    def go(self, fid, value, apply=True):
        return h44._cfgr_act_id_set({"group": "alone", "rid": self.rows()[fid]["rid"], "value": value}, apply)

    def test_bad_input_refused(self):
        cases = {"svx_el_pw": ("", "a b", "a#b", 'a"b'), "svx_el_sysop": ("", "a#b", "x" * 41),
                 "svx_el_location": ("", 'a"b', "x" * 28), "svx_refl_key": ("", "a b", "a'b", "x" * 65)}
        for fid, bads in cases.items():
            for bad in bads:
                self.assertFalse(self.go(fid, bad, False)["success"], (fid, bad))
        self.assertEqual(self.fs.written, {})

    def test_echolink_password_only(self):
        r = self.go("svx_el_pw", "newsvxpw")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("PASSWORD=newsvxpw\n", self.fs.files[SVXE])
        self.assertIn("CALLSIGN=AA1AA-L", self.fs.files[SVXE])
        self.assertIn("SYSOPNAME=MyName", self.fs.files[SVXE])
        self.assertNotIn("newsvxpw", r["output"])
        self.assertNotIn("MyPass", r["output"])
        self.assertIn("svxlink-usrp", r["output"])
        self.assertEqual(set(self.fs.written), {SVXE})

    def test_sysop_name_and_location_keep_spaces_and_brackets(self):
        r = self.go("svx_el_sysop", "  Jane Doe ")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("SYSOPNAME=Jane Doe\n", self.fs.files[SVXE])
        r = self.go("svx_el_location", "[Svx] 146.52, Anytown")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("LOCATION=[Svx] 146.52, Anytown\n", self.fs.files[SVXE])
        self.assertIn("PASSWORD=MyPass", self.fs.files[SVXE])

    def test_reflector_key_keeps_its_quotes_and_leaves_other_sections(self):
        r = self.go("svx_refl_key", "newreflkey")
        self.assertTrue(r["success"], r["output"])
        self.assertIn('AUTH_KEY="newreflkey"', self.fs.files[SVX])
        self.assertIn('[NetRx]\nTYPE=Net\nAUTH_KEY="Change this key now!"', self.fs.files[SVX])
        self.assertNotIn("newreflkey", r["output"])
        self.assertNotIn("oldreflkey", r["output"])

    def test_commented_reflector_key_has_no_row_to_set(self):
        self.fs.files = dict(SVX_FILES)
        self.assertNotIn("svx_refl_key", self.rows())

    def test_preview_writes_nothing(self):
        r = self.go("svx_el_pw", "newsvxpw", apply=False)
        self.assertTrue(r["success"])
        self.assertEqual(self.fs.written, {})


RPT_WIRED = ("[nodes]\n123456 = radio@127.0.0.1/123456,NONE\n1900 = radio@127.0.0.1/1900,NONE\n\n"
             "[123456](node-main)\nrxchannel = SimpleUSB/123456\n\n"
             "[1900](node-main)\nrxchannel = USRP/127.0.0.1:34000:32000\n")


class SvxWiring(SvxBase):
    def setUp(self):
        super().setUp()
        self.fs.files = {"/etc/asterisk/rpt.conf": RPT_WIRED, SVX: SVX_FILES[SVX], SVXU: SVX_FILES[SVXU]}

    def test_mirror_image_ports_pair_up(self):
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertEqual(ok, ["SvxLink ↔ node 1900 (34000/32000)"])
        self.assertEqual(warn, [])

    def test_swapped_ports_are_caught(self):
        for p in (SVX, SVXU):
            self.fs.files[p] = self.fs.files[p].replace("USRP_TX_PORT=32000", "USRP_TX_PORT=34000").replace(
                "USRP_RX_PORT=34000", "USRP_RX_PORT=32000", 1)
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertEqual(ok, [])
        self.assertTrue(any("no bridge listens on 34000" in w for w in warn), warn)
        self.assertTrue(any("SvxLink" in w and "has no rpt.conf node" in w for w in warn), warn)

    def test_wrong_send_port_is_a_mismatch(self):
        for p in (SVX, SVXU):
            self.fs.files[p] = self.fs.files[p].replace("USRP_TX_PORT=32000", "USRP_TX_PORT=32999")
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertEqual(ok, [])
        self.assertTrue(any("expects SvxLink to send to 32000, but it sends to 32999" in w for w in warn), warn)

    def test_no_node_for_svxlink_is_reported(self):
        self.fs.files["/etc/asterisk/rpt.conf"] = RPT_WIRED.split("[1900]")[0]
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertTrue(any("USRP_RX_PORT/USRP_TX_PORT 34000/32000 has no rpt.conf node" in w for w in warn), warn)

    def test_two_copies_that_differ_are_flagged(self):
        self.fs.files[SVX] = self.fs.files[SVX].replace("USRP_RX_PORT=34000", "USRP_RX_PORT=41233")
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertEqual(ok, ["SvxLink ↔ node 1900 (34000/32000)"])
        self.assertTrue(any("two [UsrpLogic] copies differ" in w and "41233" in w for w in warn), warn)

    def test_only_one_copy_is_enough(self):
        del self.fs.files[SVX]
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertEqual(ok, ["SvxLink ↔ node 1900 (34000/32000)"])
        self.assertEqual(warn, [])

    def test_host_other_than_loopback_is_flagged(self):
        for p in (SVX, SVXU):
            self.fs.files[p] = self.fs.files[p].replace("USRP_HOST=127.0.0.1", "USRP_HOST=10.0.0.5")
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertTrue(any("USRP_HOST is 10.0.0.5" in w for w in warn), warn)

    def test_no_svxlink_changes_nothing(self):
        self.fs.files = {"/etc/asterisk/rpt.conf": RPT_WIRED}
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertEqual(ok, [])
        self.assertEqual(len(warn), 1)
        self.assertIn("no bridge listens on 34000", warn[0])

    def test_svxlink_listen_port_is_in_the_clash_check(self):
        found = h44._cfgr_listeners()
        self.assertIn(("34000", "SvxLink", "SvxLink svxlink.d/UsrpLogic.conf [UsrpLogic] USRP_RX_PORT"), found)
        self.fs.files[AB] = "[USRP]\naddress = 127.0.0.1\ntxPort = 32001\nrxPort = 34000\n"
        clashes, _n = h44._cfgr_port_clashes()
        self.assertTrue(any("34000" in c and "SvxLink" in c for c in clashes), clashes)

    def test_other_bridges_still_pair(self):
        self.fs.files["/etc/asterisk/rpt.conf"] += "\n[1999](node-main)\nrxchannel = USRP/127.0.0.1:34001:32001\n"
        self.fs.files[AB] = "[USRP]\naddress = 127.0.0.1\ntxPort = 32001\nrxPort = 34001\n"
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertEqual(sorted(ok), ["Analog_Bridge ↔ node 1999 (34001/32001)", "SvxLink ↔ node 1900 (34000/32000)"])
        self.assertEqual(warn, [])


class SvxSysmonCompare(SvxWiring):
    def verify(self, theirs):
        line = "USRP-PAIRS-JSON:" + h44.json.dumps(theirs)
        with mock.patch.object(h44.os.path, "exists", lambda p: True), \
                mock.patch.object(h44, "_run_argv", lambda argv, **kw: {"success": True, "output": line}):
            return h44._cfgr_act_usrp_verify({})

    def test_sysmon_seeing_no_bridge_for_the_svxlink_node_is_agreement(self):
        r = self.verify({"version": "6.13.88-pi02w", "unpaired": [],
                         "pairs": [{"node": "1900", "a": "34000", "b": "32000", "bridge": "", "state": "no_bridge"}]})
        self.assertTrue(r["success"], r["output"])
        self.assertIn("SysMon agrees", r["output"])
        self.assertIn("SysMon does not read SvxLink", r["output"])
        self.assertIn("node 1900", r["output"])
        self.assertIn("paired: SvxLink ↔ node 1900", r["output"])

    def test_a_real_disagreement_is_still_reported(self):
        r = self.verify({"version": "6.13.88-pi02w", "unpaired": [], "pairs": []})
        self.assertFalse(r["success"])
        self.assertIn("SysMon DISAGREES", r["output"])

    def test_no_svxlink_gives_no_svxlink_note(self):
        self.fs.files = {"/etc/asterisk/rpt.conf": RPT_WIRED}
        r = self.verify({"version": "x", "unpaired": [],
                         "pairs": [{"node": "1900", "a": "34000", "b": "32000", "bridge": "", "state": "no_bridge"}]})
        self.assertTrue(r["success"], r["output"])
        self.assertNotIn("does not read SvxLink", r["output"])


RPT_BARE = ("[general]\nx = 1\n\n[nodes]\n123456 = radio@127.0.0.1/123456,NONE\n\n[node-main](!)\nduplex = 1\n\n"
            "[123456](node-main)\nrxchannel = SimpleUSB/123456\n")
EXT_BARE = "[globals]\nHOMENPA = 330\n\n[radio-secure]\nexten => 123456,1,rpt,123456\n"
MOD_BARE = "[modules]\nautoload = no\nnoload  = chan_usrp.so                   ; USRP Channel Module\n"
SVX_STOCK = SVX_FILES[SVX].replace("USRP_TX_PORT=32000", "USRP_TX_PORT=41234").replace("USRP_RX_PORT=34000", "USRP_RX_PORT=41233")
SVXU_STOCK = SVX_FILES[SVXU].replace("USRP_TX_PORT=32000", "USRP_TX_PORT=41234").replace("USRP_RX_PORT=34000", "USRP_RX_PORT=41233")


class SvxBridge(SvxBase):
    def setUp(self):
        super().setUp()
        self.fs.files = {"/etc/asterisk/rpt.conf": RPT_BARE, "/etc/asterisk/extensions.conf": EXT_BARE,
                         "/etc/asterisk/modules.conf": MOD_BARE, SVX: SVX_STOCK, SVXU: SVXU_STOCK}
        p = mock.patch.object(h44, "_cfgr_installed", lambda: {g: g in ("asl3", "svx") for g in h44._CFGR_GROUPS})
        p.start()
        self.addCleanup(p.stop)

    def go(self, apply=True, **kw):
        return h44._cfgr_act_svx_bridge(dict(kw), apply)

    def test_preview_writes_nothing_and_shows_both_sides(self):
        r = self.go(False)
        self.assertTrue(r["success"], r["output"])
        self.assertEqual(self.fs.written, {})
        self.assertEqual(r["node"], "1900")
        for text in ("[1900](node-main)", "rxchannel = USRP/127.0.0.1:34000:32000", "USRP_RX_PORT=34000",
                     "USRP_TX_PORT=32000", "1900 = radio@127.0.0.1/1900,NONE", "exten => 1900,1,Rpt(1900)"):
            self.assertIn(text, r["output"])
        self.assertIn(SVXU, r["changes"])
        self.assertIn(SVX, r["changes"])

    def test_apply_wires_both_ends_and_the_check_then_passes(self):
        r = self.go(True)
        self.assertTrue(r["success"], r["output"])
        f = self.fs.files
        self.assertIn("[1900](node-main)\nrxchannel = USRP/127.0.0.1:34000:32000", f["/etc/asterisk/rpt.conf"])
        self.assertIn("exten => 1900,1,Rpt(1900)", f["/etc/asterisk/extensions.conf"])
        self.assertNotIn("1,rpt,1900", f["/etc/asterisk/extensions.conf"])
        self.assertRegex(f["/etc/asterisk/modules.conf"], r"(?m)^load\s*=\s*chan_usrp\.so")
        for p in (SVX, SVXU):
            self.assertIn("USRP_HOST=127.0.0.1\nUSRP_TX_PORT=32000\nUSRP_RX_PORT=34000", f[p])
            self.assertIn("CALL=AA1AA", f[p])
        self.assertIn("[SimplexLogic]\nTYPE=Simplex\nCALLSIGN=AA1AA", f[SVX])
        ok, warn = h44._cfgr_usrp_pairs()
        self.assertEqual(ok, ["SvxLink ↔ node 1900 (34000/32000)"])
        self.assertEqual(warn, [])
        self.assertIn("svx", r["restart_groups"])
        self.assertIn("asl3", r["restart_groups"])
        self.assertIn("Restart svxlink-usrp", r["output"])
        self.assertIn("closed in the firewall", r["output"])

    def test_running_it_again_changes_nothing(self):
        self.go(True)
        self.fs.written.clear()
        r = self.go(True)
        self.assertTrue(r["success"])
        self.assertEqual(r["changes"], [])
        self.assertIn("already wired to node 1900", r["output"])
        self.assertEqual(self.fs.written, {})

    def test_1900_taken_uses_the_next_free_node(self):
        self.fs.files["/etc/asterisk/rpt.conf"] += "\n[1900](node-main)\nrxchannel = Local/pseudo\n"
        r = self.go(False)
        self.assertTrue(r["success"], r["output"])
        self.assertNotEqual(r["node"], "1900")
        self.assertIn("Node 1900 is already in rpt.conf", r["output"])

    def test_ports_taken_use_the_next_free_pair(self):
        self.fs.files["/etc/asterisk/rpt.conf"] += "\n[1050](node-main)\nrxchannel = USRP/127.0.0.1:34000:32050\n"
        r = self.go(True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("rxchannel = USRP/127.0.0.1:34001:32001", self.fs.files["/etc/asterisk/rpt.conf"])
        self.assertIn("USRP_RX_PORT=34001", self.fs.files[SVXU])
        self.assertIn("USRP_TX_PORT=32001", self.fs.files[SVXU])
        self.assertIn("34001/32001 are used", r["output"])

    def test_a_typed_node_is_used_and_a_public_one_refused(self):
        r = self.go(False, node="1905")
        self.assertEqual(r["node"], "1905")
        self.assertFalse(self.go(False, node="123456")["success"])
        self.assertFalse(self.go(False, node="2000")["success"])

    def test_no_svxlink_is_refused(self):
        del self.fs.files[SVX]
        del self.fs.files[SVXU]
        r = self.go(True)
        self.assertFalse(r["success"])
        self.assertIn("SvxLink tab", r["output"])
        self.assertEqual(self.fs.written, {})

    def test_no_rpt_conf_is_refused(self):
        del self.fs.files["/etc/asterisk/rpt.conf"]
        self.assertFalse(self.go(True)["success"])
        self.assertEqual(self.fs.written, {})

    def test_only_the_svxlink_d_copy_is_enough(self):
        del self.fs.files[SVX]
        r = self.go(True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("USRP_RX_PORT=34000", self.fs.files[SVXU])

    def test_missing_port_lines_are_added_under_the_header(self):
        self.fs.files[SVXU] = "[UsrpLogic]\nTYPE=Usrp\nCALL=AA1AA\n#USRP_TX_PORT=1\n"
        del self.fs.files[SVX]
        r = self.go(True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("[UsrpLogic]\nUSRP_HOST=127.0.0.1\nUSRP_TX_PORT=32000\nUSRP_RX_PORT=34000\nTYPE=Usrp", self.fs.files[SVXU])
        self.assertIn("#USRP_TX_PORT=1", self.fs.files[SVXU])

    def test_set_ports_leaves_other_sections_alone(self):
        text = "[Other]\nUSRP_TX_PORT=1\n\n[UsrpLogic]\nUSRP_TX_PORT=2\nUSRP_RX_PORT=3\nUSRP_HOST=x\n\n[After]\nUSRP_RX_PORT=9\n"
        out = h44._cfgr_svx_set_ports(text, 34000, 32000)
        self.assertIn("[Other]\nUSRP_TX_PORT=1", out)
        self.assertIn("[After]\nUSRP_RX_PORT=9", out)
        self.assertIn("[UsrpLogic]\nUSRP_TX_PORT=32000\nUSRP_RX_PORT=34000\nUSRP_HOST=127.0.0.1", out)
        self.assertEqual(h44._cfgr_svx_set_ports("[X]\na=1\n", 1, 2), "[X]\na=1\n")


class SvxStep8Defaults(unittest.TestCase):
    def step(self):
        return next(s for s in h44._SVXLINK_SCRIPTS["install"]["usrp"] if s["id"] == "usrp_logic_conf")

    def test_defaults_are_the_mirror_image_of_node_1900(self):
        f = {x["id"]: x for x in self.step()["fields"]}
        self.assertEqual(f["port"]["default"], str(h44._CFGR_SVX_BRIDGE_RX))
        self.assertEqual(f["rx_port"]["default"], str(h44._CFGR_SVX_BRIDGE_TX))
        self.assertEqual((f["port"]["default"], f["rx_port"]["default"]), ("32000", "34000"))
        self.assertIn("ASL3 node", f["port"]["label"])
        self.assertIn("ASL3 node", f["rx_port"]["label"])

    def test_default_command_uses_the_same_ports(self):
        st = self.step()
        self.assertIn("TX='32000' RX='34000'", st["cmd"])
        cmd, why = h44._step_command(st, {"callsign": "AA1AA", "port": "32000", "rx_port": "34000"})
        self.assertEqual(why, "")
        self.assertIn("CALL='AA1AA' TX='32000' RX='34000'", cmd)

    def test_other_ports_can_still_be_entered(self):
        cmd, why = h44._step_command(self.step(), {"callsign": "AA1AA", "port": "41234", "rx_port": "41233"})
        self.assertEqual(why, "")
        self.assertIn("TX='41234' RX='41233'", cmd)

    def test_step_8_and_the_bridge_button_agree(self):
        self.assertEqual(h44._CFGR_SVX_BRIDGE_NODE, "1900")
        self.assertIn("1900", self.step()["note"])


NI = "/usr/local/etc/svxlink/node_info.json"
NI_STOCK = '{\n  "nodeLocation": "MyTownOrArea",\n  "nodeClass": "one of repeater|simplex|hotspot|bridge",\n  "hidden": false,\n  "sysop": "CALL1 CALL2",\n  "toneToTalkgroup": {"136.5": 0, "88.5": 999, "123.0": 9990},\n  "qth": [\n    {\n      "name": "My QTH Name",\n      "pos": {\n        "lat": 60.12345,\n        "long": 17.12345,\n        "loc": "AA88BB"\n      },\n      "rx": {\n        "A": {\n          "name": "Rx1",\n          "freq": 433.450,\n          "sqlType": "CTCSS",\n          "ctcssFreq": [136.5,88.5,123.0],\n          "ant": [\n            {\n              "comment": "Yagi south",\n              "height": 50,\n              "dir": 180\n            },\n            {\n              "comment": "Yagi north",\n              "height": 50,\n              "dir": 0\n            }\n          ]\n        },\n        "B": {\n          "name": "Rx2",\n          "freq": 145.500,\n          "sqlType": "COS",\n          "ant": [\n            {\n              "comment": "Diamond X310 Omni",\n              "height": 10\n            }\n          ]\n        }\n      },\n      "tx": {\n        "A": {\n          "name": "Tx1",\n          "freq": 433.450,\n          "pwr": 20,\n          "ctcssFreq": 136.5,\n          "ant": [\n            {\n              "comment": "Yagi south",\n              "height": 50,\n              "dir": 180\n            },\n            {\n              "comment": "Yagi north",\n              "height": 50,\n              "dir": 0\n            }\n          ]\n        }\n      }\n    }\n  ]\n}\n'
SVX_WITH_NI = SVX_FILES[SVX].replace("[UsrpLogic]", "#NODE_INFO_FILE=/usr/local/etc/svxlink/node_info.json\n\n[UsrpLogic]", 1)


class SvxNodeInfo(SvxBase):
    def setUp(self):
        super().setUp()
        self.fs.files = dict(SVX_FILES)
        self.fs.files[SVX] = SVX_WITH_NI
        self.fs.files[NI] = NI_STOCK

    def go(self, fid, value, apply=True):
        return h44._cfgr_act_id_set({"group": "alone", "rid": self.rows()[fid]["rid"], "value": value}, apply)

    def doc(self):
        return json.loads(self.fs.files[NI])

    def test_rows_are_read_and_settable(self):
        r = self.rows()
        self.assertEqual(r["svx_ni_loc"]["raw"], "AA88BB")
        self.assertEqual(r["svx_ni_loc"]["where"], "qth[0].pos.loc")
        self.assertEqual(r["svx_ni_hidden"]["raw"], "no")
        for fid in h44._CFGR_SVX_NI:
            self.assertTrue(r[fid]["settable"], fid)
            self.assertEqual(r[fid]["groups"], ["alone"])

    def test_bad_input_refused(self):
        cases = {"svx_ni_class": ("router",), "svx_ni_hidden": ("maybe",), "svx_ni_lat": ("91", "45.1234567", "x"),
                 "svx_ni_lon": ("181", "-180.5"), "svx_ni_loc": ("ZZ99", "EN8", "EN81x"), "svx_ni_sysop": ("a\"b",),
                 "svx_ni_location": ('a"b', "x" * 41)}
        for fid, bads in cases.items():
            for bad in bads:
                self.assertFalse(self.go(fid, bad, False)["success"], (fid, bad))
        self.assertEqual(self.fs.written, {})

    def test_first_write_replaces_the_sample_with_a_clean_bridge_entry(self):
        r = self.go("svx_ni_loc", "en81XM")
        self.assertTrue(r["success"], r["output"])
        d = self.doc()
        self.assertEqual(d["qth"][0]["pos"]["loc"], "EN81xm")
        self.assertEqual(d["nodeClass"], "bridge")
        self.assertNotIn("rx", d["qth"][0])
        self.assertNotIn("tx", d["qth"][0])
        self.assertNotIn("toneToTalkgroup", d)
        self.assertNotIn("MyTownOrArea", self.fs.files[NI])
        self.assertIn("sample", r["output"])
        self.assertIn("svxlink-usrp", r["output"])

    def test_node_info_file_is_switched_on_only_when_the_position_is_set(self):
        self.go("svx_ni_location", "Toledo, OH")
        self.assertIn("#NODE_INFO_FILE=", self.fs.files[SVX])
        r = self.go("svx_ni_lat", "41.65", False)
        self.assertIn("stays off", r["output"])
        self.go("svx_ni_lat", "41.65")
        self.assertIn("#NODE_INFO_FILE=", self.fs.files[SVX])
        r = self.go("svx_ni_lon", "-83.53")
        self.assertTrue(r["success"], r["output"])
        self.assertIn("\nNODE_INFO_FILE=/usr/local/etc/svxlink/node_info.json\n", self.fs.files[SVX])
        self.assertIn("switched on", r["output"])
        d = self.doc()
        self.assertEqual((d["nodeLocation"], d["qth"][0]["pos"]["lat"], d["qth"][0]["pos"]["long"]), ("Toledo, OH", 41.65, -83.53))

    def test_types_are_kept_and_later_writes_keep_other_fields(self):
        self.go("svx_ni_hidden", "YES")
        self.go("svx_ni_sysop", "aa1aa")
        self.go("svx_ni_class", "Hotspot")
        d = self.doc()
        self.assertIs(d["hidden"], True)
        self.assertEqual(d["sysop"], "AA1AA")
        self.assertEqual(d["nodeClass"], "hotspot")

    def test_a_file_that_is_not_json_is_left_alone(self):
        self.fs.files[NI] = "{not json"
        r = h44._cfgr_act_id_set({"group": "alone", "rid": "svx_ni_loc#0", "value": "EN81"}, True)
        self.assertFalse(r["success"])
        self.assertEqual(self.fs.written, {})

    def test_a_clean_file_keeps_extra_fields(self):
        self.fs.files[NI] = json.dumps({"nodeLocation": "X", "nodeClass": "repeater", "hidden": False, "sysop": "AA1AA",
                                        "qth": [{"name": "Hill", "pos": {"lat": 41.0, "long": -83.0, "loc": "EN81"},
                                                 "rx": {"A": {"freq": 146.52}}}]})
        self.go("svx_ni_qth", "Big Hill")
        d = self.doc()
        self.assertEqual(d["qth"][0]["name"], "Big Hill")
        self.assertEqual(d["qth"][0]["rx"], {"A": {"freq": 146.52}})
        self.assertEqual(d["nodeClass"], "repeater")


EXT_OLD = ("[globals]\nHOMENPA = 330\n\n[radio-secure]\nexten => _XXXX!,1,Set(NODENUM=${CALLERID(num)})\n"
           "exten => 1900,1,rpt,1900\nexten => 1917,1,rpt,1917 ; 44helper M17\nexten => 1999,1,Rpt(1999)\n\n[other]\n"
           "exten => 1500,1,rpt,1500\n")


class ExtenLineFix(SvxBase):
    def setUp(self):
        super().setUp()
        self.fs.files = {"/etc/asterisk/rpt.conf": RPT_BARE + "\n[1900](node-main)\nrxchannel = USRP/127.0.0.1:34000:32000\n",
                         "/etc/asterisk/extensions.conf": EXT_OLD, "/etc/asterisk/modules.conf": MOD_BARE}
        p = mock.patch.object(h44, "_cfgr_installed", lambda: {g: g == "asl3" for g in h44._CFGR_GROUPS})
        p.start()
        self.addCleanup(p.stop)

    def test_new_lines_use_rpt_in_brackets(self):
        self.assertEqual(h44._pn_ext_line("1900"), "exten => 1900,1,Rpt(1900)")

    def test_status_names_the_old_lines_in_radio_secure_only(self):
        self.assertEqual(h44._pn_status()["old_ext"], ["1900", "1917"])

    def test_fix_changes_only_the_old_form_and_keeps_comments(self):
        r = h44._cfgr_act_pn_fix_ext({}, False)
        self.assertTrue(r["success"])
        self.assertEqual(self.fs.written, {})
        self.assertIn("1900, 1917", r["output"])
        r = h44._cfgr_act_pn_fix_ext({}, True)
        self.assertTrue(r["success"], r["output"])
        t = self.fs.files["/etc/asterisk/extensions.conf"]
        self.assertIn("exten => 1900,1,Rpt(1900)\n", t)
        self.assertIn("exten => 1917,1,Rpt(1917) ; 44helper M17\n", t)
        self.assertIn("exten => 1999,1,Rpt(1999)\n", t)
        self.assertIn("[other]\nexten => 1500,1,rpt,1500", t)
        self.assertIn("exten => _XXXX!,1,Set(NODENUM=${CALLERID(num)})", t)
        self.assertEqual(h44._pn_status()["old_ext"], [])
        again = h44._cfgr_act_pn_fix_ext({}, True)
        self.assertEqual(again["changes"], [])

    def test_add_node_repairs_its_own_old_line(self):
        self.fs.files["/etc/asterisk/rpt.conf"] = RPT_BARE
        r = h44._cfgr_act_pn_add({"node": "1900", "kind": "plain"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertIn("exten => 1900,1,Rpt(1900)", self.fs.files["/etc/asterisk/extensions.conf"])
        self.assertIn("changed to Rpt(1900)", r["output"])

    def test_remove_node_removes_either_form(self):
        lines = self.fs.files["/etc/asterisk/rpt.conf"].replace("[1900](node-main)", h44._PN_NOTE + "\n[1900](node-main)")
        self.fs.files["/etc/asterisk/rpt.conf"] = lines.replace("[nodes]\n", "[nodes]\n1900 = radio@127.0.0.1/1900,NONE\n")
        r = h44._cfgr_act_pn_remove({"node": "1900"}, True)
        self.assertTrue(r["success"], r["output"])
        self.assertNotIn("exten => 1900", self.fs.files["/etc/asterisk/extensions.conf"])

    def test_m17_script_repairs_and_undo_restores(self):
        src = h44._M17_CONF_PY
        ns = {"__name__": "x"}
        with mock.patch.object(sys, "argv", ["m17", "apply"]):
            exec(compile(src.split("\nif mode == ")[0], "m17", "exec"), ns)
        ns["node"] = "1917"
        new, notes = ns["apply_ext"]("[radio-secure]\nexten => 1917,1,rpt,1917\n")
        self.assertIn("exten => 1917,1,Rpt(1917) ; 44helper M17 (was: exten => 1917,1,rpt,1917)", new)
        self.assertIn("Rpt(1917)", notes[0])
        back, _ = ns["undo_ext"](new)
        self.assertIn("exten => 1917,1,rpt,1917", back)
        self.assertNotIn("Rpt(1917)", back)
        fresh, _ = ns["apply_ext"]("[radio-secure]\nexten => _XXXX!,1,Set(X=1)\n")
        self.assertIn("exten => 1917,1,Rpt(1917) ; 44helper M17", fresh)
        same, n2 = ns["apply_ext"](fresh)
        self.assertEqual(same, fresh)
        self.assertEqual(n2, ["extension already there"])


RPT_MESSY = ("[general]\nx = 1\n\n[nodes]\n1921 = radio@127.0.0.1:4574/1921,NONE\n1921 = /1921,NONE\n\n"
             "; samples\n;1001 = radio@1.2.3.4:4568/1001,NONE\n\n652705 = :4569/652705,NONE\n\n; more text\n;\n\n"
             "1999 = :4569/1999,NONE\n1917 = radio@127.0.0.1:4574/1917,NONE ; 44helper M17\n"
             "1900 = radio@127.0.0.1:4574/1900,NONE\n2000 = /2000,NONE\n\n[node-main](!)\nduplex = 1\n\n"
             "[652705](node-main)\nrxchannel = SimpleUSB/652705\n\n[1999](node-main)\nrxchannel = USRP/127.0.0.1:34001:32001\n\n"
             "[1917](node-main)\nrxchannel = USRP/127.0.0.1:34008:32008\n\n[1921](node-main)\nrxchannel = USRP/127.0.0.1:34018:32018\n\n"
             "[1900](node-main)\nrxchannel = USRP/127.0.0.1:34000:32000\n")
IAX_4574 = "[general]\nbindport = 4574\n"


class NodesLineTidy(SvxBase):
    def setUp(self):
        super().setUp()
        self.fs.files = {"/etc/asterisk/rpt.conf": RPT_MESSY, "/etc/asterisk/iax.conf": IAX_4574,
                         "/etc/asterisk/extensions.conf": EXT_BARE.replace("rpt,123456", "Rpt(123456)"),
                         "/etc/asterisk/modules.conf": MOD_BARE}
        p = mock.patch.object(h44, "_cfgr_installed", lambda: {g: g == "asl3" for g in h44._CFGR_GROUPS})
        p.start()
        self.addCleanup(p.stop)

    def nodes_lines(self, text):
        sec = text.split("[nodes]\n", 1)[1].split("\n[node-main]", 1)[0]
        return [x for x in sec.splitlines() if x and not x.startswith(";")]

    def test_status_names_each_problem(self):
        st = h44._pn_status()
        text = " | ".join(st["nodes_issues"])
        self.assertIn("1921: 2 lines for this node", text)
        self.assertIn("652705: it has no host", text)
        self.assertIn("652705: its port is 4569, but Asterisk listens on 4574", text)
        self.assertIn("1999: it has no host", text)
        self.assertIn("2000: not a node on this server", text)
        self.assertNotIn("1900:", text)
        self.assertTrue(st["nodes_fixable"])

    def test_fix_rewrites_local_lines_in_one_ordered_block(self):
        r = h44._cfgr_act_pn_fix_nodes({}, False)
        self.assertTrue(r["success"])
        self.assertEqual(self.fs.written, {})
        r = h44._cfgr_act_pn_fix_nodes({}, True)
        self.assertTrue(r["success"], r["output"])
        t = self.fs.files["/etc/asterisk/rpt.conf"]
        self.assertEqual(self.nodes_lines(t), [
            "652705 = radio@127.0.0.1:4574/652705,NONE",
            "1900 = radio@127.0.0.1:4574/1900,NONE",
            "1917 = radio@127.0.0.1:4574/1917,NONE ; 44helper M17",
            "1921 = radio@127.0.0.1:4574/1921,NONE",
            "1999 = radio@127.0.0.1:4574/1999,NONE",
            "2000 = /2000,NONE"])
        self.assertIn(";1001 = radio@1.2.3.4:4568/1001,NONE", t)
        self.assertIn("; more text", t)
        self.assertNotIn("\n\n\n", t)
        self.assertIn("2000: not a node on this server", r["output"])
        st = h44._pn_status()
        self.assertFalse(st["nodes_fixable"])
        self.assertEqual(st["nodes_issues"], ["[nodes] 2000: it has no host",
                                              "[nodes] 2000: not a node on this server, so its address is not known "
                                              "here; fix it by hand"])
        again = h44._cfgr_act_pn_fix_nodes({}, True)
        self.assertEqual(again["changes"], [])

    def test_node_talker_line_is_the_one_it_writes(self):
        h44._cfgr_act_pn_fix_nodes({}, True)
        lines = self.fs.files["/etc/asterisk/rpt.conf"].splitlines()
        self.assertEqual([x for x in lines if x.startswith("1921 ")], ["1921 = radio@127.0.0.1:4574/1921,NONE"])

    def test_missing_line_for_a_local_node_is_added(self):
        self.fs.files["/etc/asterisk/rpt.conf"] = RPT_MESSY.replace("1900 = radio@127.0.0.1:4574/1900,NONE\n", "")
        self.assertIn("[nodes] 1900: node [1900] has no [nodes] line, so links to it fail",
                      h44._pn_status()["nodes_issues"])
        h44._cfgr_act_pn_fix_nodes({}, True)
        self.assertIn("1900 = radio@127.0.0.1:4574/1900,NONE", self.nodes_lines(self.fs.files["/etc/asterisk/rpt.conf"]))

    def test_add_node_tidies_while_it_writes(self):
        r = h44._cfgr_act_pn_add({"node": "1500", "kind": "plain"}, True)
        self.assertTrue(r["success"], r["output"])
        got = self.nodes_lines(self.fs.files["/etc/asterisk/rpt.conf"])
        self.assertEqual(got[:6], ["652705 = radio@127.0.0.1:4574/652705,NONE",
                                   "1500 = radio@127.0.0.1:4574/1500,NONE",
                                   "1900 = radio@127.0.0.1:4574/1900,NONE",
                                   "1917 = radio@127.0.0.1:4574/1917,NONE ; 44helper M17",
                                   "1921 = radio@127.0.0.1:4574/1921,NONE",
                                   "1999 = radio@127.0.0.1:4574/1999,NONE"])
        self.assertIn("[nodes] tidied as well", r["output"])

    def test_remove_node_tidies_while_it_writes(self):
        self.fs.files["/etc/asterisk/rpt.conf"] = RPT_MESSY.replace("[1900](node-main)", h44._PN_NOTE + "\n[1900](node-main)")
        r = h44._cfgr_act_pn_remove({"node": "1900"}, True)
        self.assertTrue(r["success"], r["output"])
        got = self.nodes_lines(self.fs.files["/etc/asterisk/rpt.conf"])
        self.assertNotIn("1900 = radio@127.0.0.1:4574/1900,NONE", got)
        self.assertIn("652705 = radio@127.0.0.1:4574/652705,NONE", got)

    def test_clean_file_is_left_alone(self):
        clean = ("[general]\n\n[nodes]\n652705 = radio@127.0.0.1/652705,NONE\n1999 = radio@127.0.0.1/1999,NONE\n\n"
                 "[652705]\nrxchannel = SimpleUSB/652705\n\n[1999]\nrxchannel = Local/pseudo\n")
        t = h44._pn_nodes_tidy(clean.splitlines(), "4569")
        self.assertEqual(t["issues"], [])
        self.assertEqual(t["lines"], clean.splitlines())

    def test_managed_block_is_not_touched(self):
        text = ("[nodes]\n652705 = radio@127.0.0.1/652705,NONE\n; BEGIN ASL-DVS PHONE (managed)\n1800 = /1800,NONE\n"
                "; END ASL-DVS PHONE\n\n[652705]\nrxchannel = SimpleUSB/652705\n")
        lines = text.splitlines()
        with mock.patch.object(h44, "_cfgr_managed_mask",
                               lambda ls: [x.startswith("; BEGIN") or x == "1800 = /1800,NONE" or x.startswith("; END")
                                           for x in ls]):
            t = h44._pn_nodes_tidy(lines, "4569")
        self.assertEqual(t["lines"], lines)
        self.assertEqual(t["issues"], [])


if __name__ == "__main__":
    unittest.main()
