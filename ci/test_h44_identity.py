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


if __name__ == "__main__":
    unittest.main()
