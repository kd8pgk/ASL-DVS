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


spec = importlib.util.spec_from_file_location("h44_stfuel_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_stfuel_under_test"] = h44
spec.loader.exec_module(h44)

BASE = dict(h44._BLD_DEFAULT, callsign="KD8PGK", node="652701", dmr_id="3123456", mode="none")
DVSINI = """[General]
Logging = 1

[STFU]                          ; Brandmeister Open DMR Terminal (ODMRT) Protocol
BMAddress = 3104.master.brandmeister.network   ; server
BMPort = 54006                  ; port
BMPassword = keepme
UserID  = 3123456
TalkerAlias = KD8PGK
StartTG = 3166                  ; Startup talk group
LogLevel = 3

[ASL]
address = 127.0.0.1
"""
ELCONF = """[el0]
call = INVALID
pwd = keepme
name = YOUR NAME
qth = INVALID
email = INVALID
node = 000000
lat = 0.0
lon = 0.0
power = 0
astnode = 1999
context = radio-secure
server1 = nasouth.echolink.org
"""
MODS = """[modules]
autoload = yes
noload  = chan_echolink.so               ; Echolink Channel Driver
load = chan_usrp.so
"""
SVX = """[GLOBAL]
LOGICS=SimplexLogic

[SimplexLogic]
TYPE=Simplex
MODULES=ModuleHelp,ModuleParrot
CALLSIGN=KD8PGK
"""
SVXEL = """[ModuleEchoLink]
CALLSIGN=OLD
SYSOPNAME=Old
LOCATION=Old
PASSWORD=keepme
"""


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.p = lambda n: os.path.join(self.d.name, n)
        for name, text in (("dvs.ini", DVSINI), ("el.conf", ELCONF), ("modules.conf", MODS), ("svx.conf", SVX), ("svxel.conf", SVXEL)):
            with open(self.p(name), "w") as f:
                f.write(text)
        for p in (mock.patch.object(h44, "_BLD_DVSINI", self.p("dvs.ini")), mock.patch.object(h44, "_CFGR_ECHOLINK", self.p("el.conf")),
                  mock.patch.object(h44, "_BLD_MODULES", self.p("modules.conf")), mock.patch.object(h44, "_CFGR_SVX_CONF", self.p("svx.conf")),
                  mock.patch.object(h44, "_CFGR_SVX_EL", self.p("svxel.conf"))):
            p.start()
            self.addCleanup(p.stop)

    def read(self, name):
        with open(self.p(name)) as f:
            return f.read()

    @staticmethod
    def write_bytes(path, data):
        with open(path, "wb") as f:
            f.write(data)
        return "written"

    def apply(self, changes):
        for path, (_o, new) in changes.items():
            with open(path, "wb") as f:
                f.write(new)


class Form(unittest.TestCase):
    def errs(self, **kw):
        return h44._bld_form_errors(dict(BASE, **kw), [])

    def test_all_optional_and_defaults(self):
        self.assertEqual(self.errs(), {})
        self.assertEqual(h44._BLD_DEFAULT["el_owner"], "auto")
        self.assertEqual(h44._BLD_DEFAULT["el_enable"], "")

    def test_good_values(self):
        good = dict(el_enable="1", el_owner="asl3", el_call="KD8PGK-L", el_name="Mike", el_qth="Toledo", el_email="me@example.org", el_power="2",
                    el_height="1", el_gain="3", el_dir="0", el_freq="146.52", el_tone="100.0", stfu_master="3104.master.brandmeister.network",
                    stfu_port="54006", stfu_tg="3166", stfu_log="3")
        self.assertEqual(self.errs(**good), {})

    def test_bad_values_are_named(self):
        for k, v in (("el_call", "KD8PGK"), ("el_call", "KD8PGK-X"), ("el_email", "nope"), ("el_power", "12"), ("el_dir", "9"), ("el_freq", "abc"),
                     ("stfu_port", "99999"), ("stfu_port", "abc"), ("stfu_log", "6"), ("stfu_tg", "x"), ("stfu_other", "bad host"), ("el_enable", "yes"),
                     ("el_owner", "both")):
            self.assertIn(k, self.errs(**{k: v}), (k, v))

    def test_other_master_needs_an_address(self):
        self.assertIn("stfu_other", self.errs(stfu_master="other"))
        self.assertEqual(self.errs(stfu_master="other", stfu_other="3105.master.example.org"), {})

    def test_the_call_is_upper_cased_and_the_owner_defaults(self):
        got = h44._bld_form_clean(dict(BASE, el_call="kd8pgk-l", el_owner=""))
        self.assertEqual(got["el_call"], "KD8PGK-L")
        self.assertEqual(got["el_owner"], "auto")

    def test_fields_and_panel_rows_on_both_tabs(self):
        for k in h44._BLD_EL_FIELDS + h44._BLD_STFU_FIELDS:
            self.assertIn(k, h44._BLD_FIELDS)
            self.assertIn(k, h44._BLD_FIELDS_TRAVEL)
            self.assertIn(k, h44._BLD_FIELDS_MAGIC)
            self.assertIn("-" + k, h44._BLD_PANEL_TMPL)
        self.assertIn("3104.master.brandmeister.network", h44._BLD_PANEL_TMPL)
        self.assertNotIn("@STFUMASTERS@", h44._BLD_PANEL_TMPL)


class StfuSteps(Tmp):
    FORM = dict(BASE, stfu_master="3105.master.example.org", stfu_port="54007", stfu_tg="91", stfu_log="2")

    def installed(self, yes=True):
        return mock.patch.object(h44, "_bld_stfu_installed", lambda: yes)

    def test_wanted_values_and_the_other_master(self):
        self.assertEqual(h44._bld_stfu_wanted(self.FORM), {"BMAddress": "3105.master.example.org", "BMPort": "54007", "StartTG": "91", "LogLevel": "2"})
        self.assertEqual(h44._bld_stfu_wanted(dict(BASE, stfu_master="other", stfu_other="x.example.org"))["BMAddress"], "x.example.org")
        self.assertEqual(h44._bld_stfu_wanted(BASE), {})

    def test_install_state(self):
        with self.installed(False):
            self.assertEqual(h44._bld_stfu_state()[0], "warn")
        with self.installed(True):
            self.assertEqual(h44._bld_stfu_state()[0], "done")

    def test_setup_states(self):
        with self.installed(False):
            self.assertEqual(h44._bld_stfu_setup_state(self.FORM)[0], "warn")
        with self.installed(True):
            self.assertEqual(h44._bld_stfu_setup_state(BASE)[0], "warn")
            self.assertEqual(h44._bld_stfu_setup_state(self.FORM)[0], "todo")
            self.assertEqual(h44._bld_stfu_setup_state(dict(BASE, stfu_tg="3166", stfu_log="3", stfu_port="54006"))[0], "warn")
            self.assertEqual(h44._bld_stfu_setup_state(dict(BASE, stfu_master="3104.master.brandmeister.network", stfu_tg="3166"))[0], "done")

    def test_run_changes_only_the_stfu_keys(self):
        with self.installed(True), mock.patch.object(h44, "_cfgr_auto_point", lambda r, g: ("auto1", [])), \
                mock.patch.object(h44, "_cfgr_write_file", lambda path, data, uid, gid, mode: self.write_bytes(path, data)):
            ok, lines = h44._bld_run_stfu(self.FORM, False)
        self.assertTrue(ok)
        text = self.read("dvs.ini")
        for want in ("BMAddress = 3105.master.example.org", "BMPort = 54007", "StartTG = 91", "LogLevel = 2"):
            self.assertIn(want, text)
        for keep in ("BMPassword = keepme", "UserID  = 3123456", "TalkerAlias = KD8PGK", "[ASL]", "Logging = 1"):
            self.assertIn(keep, text)
        self.assertTrue(any("automatic copy auto1" in ln for ln in lines))

    def test_preview_writes_nothing_and_a_missing_install_refuses(self):
        with self.installed(True):
            ok, lines = h44._bld_run_stfu(self.FORM, True)
        self.assertTrue(ok)
        self.assertEqual(self.read("dvs.ini"), DVSINI)
        self.assertTrue(any("+BMAddress" in ln for ln in lines))
        with self.installed(False):
            ok, lines = h44._bld_run_stfu(self.FORM, False)
        self.assertFalse(ok)

    def test_nothing_entered_changes_nothing(self):
        with self.installed(True):
            ok, lines = h44._bld_run_stfu(BASE, False)
        self.assertTrue(ok)
        self.assertEqual(self.read("dvs.ini"), DVSINI)


class StfuInstall(unittest.TestCase):
    def go(self, installed=False, dvs="installed", gate=None, busy=None):
        started = []
        with mock.patch.object(h44, "_bld_stfu_installed", lambda: installed), \
                mock.patch.object(h44, "_detect_installed_products", lambda force=False: [{"key": "dvs", "state": dvs}]), \
                mock.patch.object(h44, "_pkg_health_gate", lambda cmd: gate), mock.patch.object(h44, "_bld_running_job", lambda: busy), \
                mock.patch.object(h44, "_start_unit_job", lambda key, cmd: started.append((key, cmd))):
            res = h44._bld_act_install_stfu({"profile": "magic"})
        return res, started

    def test_starts_the_apt_job(self):
        res, started = self.go()
        self.assertTrue(res["success"])
        self.assertEqual(res["job_key"], "build_magic_stfu")
        self.assertIn("apt-get install -y", started[0][1])
        self.assertTrue(started[0][1].rstrip().endswith("stfu"))

    def test_refusals(self):
        self.assertIn("already", self.go(installed=True)[0]["message"])
        self.assertIn("DVSwitch", self.go(dvs="absent")[0]["message"])
        res, started = self.go(gate={"output": "broken"})
        self.assertFalse(res["success"])
        self.assertEqual(started, [])
        self.assertFalse(self.go(busy="x")[0]["success"])

    def test_the_action_is_registered(self):
        self.assertIn("install_stfu", h44._BLD_ACTIONS)


class EchoOwner(unittest.TestCase):
    def test_owner_rules(self):
        on = dict(BASE, el_enable="1")
        self.assertEqual(h44._bld_el_owner(BASE, "travel"), "")
        self.assertEqual(h44._bld_el_owner(on, "travel"), "asl3")
        self.assertEqual(h44._bld_el_owner(dict(on, el_owner="svx"), "travel"), "asl3")
        self.assertEqual(h44._bld_el_owner(dict(on, el_owner="svx", svx_use="bridge"), "magic"), "asl3")
        self.assertEqual(h44._bld_el_owner(dict(on, el_owner="svx", svx_use="radio"), "magic"), "svx")
        self.assertEqual(h44._bld_el_owner(dict(on, el_owner="auto", svx_use="radio"), "magic"), "asl3")


class EchoSteps(Tmp):
    ON = dict(BASE, el_enable="1", el_call="KD8PGK-L", el_name="Mike", el_qth="Toledo", el_email="me@example.org", el_node="123456", pw_el="pw",
              lat="41.65", lon="-83.54", el_power="2", sysop="Mike M", location="Toledo, OH")

    def test_off_changes_nothing(self):
        self.assertEqual(h44._bld_el_changes(BASE, "travel"), ({}, []))
        self.assertEqual(h44._bld_echolink_state(BASE, "travel")[0], "done")
        ok, lines = h44._bld_run_echolink(BASE, "travel", False)
        self.assertTrue(ok)
        self.assertEqual(self.read("el.conf"), ELCONF)

    def test_asl3_owner_writes_echolink_conf_and_loads_the_module(self):
        with open(self.p("svx.conf"), "w") as f:
            f.write(SVX.replace("ModuleParrot", "ModuleParrot,ModuleEchoLink"))
        changes, _n = h44._bld_el_changes(self.ON, "travel")
        self.apply(changes)
        el = self.read("el.conf")
        for want in ("call = KD8PGK-L", "name = Mike", "qth = Toledo", "email = me@example.org", "node = 123456", "astnode = 652701",
                     "lat = 41.65", "lon = -83.54", "power = 2", "context = radio-secure"):
            self.assertIn(want, el)
        self.assertIn("pwd = keepme", el)
        self.assertIn("server1 = nasouth.echolink.org", el)
        mods = self.read("modules.conf")
        self.assertEqual(h44._cfgr_module_state(h44._cfgr_lines(mods), "chan_echolink"), "load")
        self.assertIn("load = chan_usrp.so", mods)
        self.assertNotIn("ModuleEchoLink", self.read("svx.conf"))
        self.assertIn("ModuleHelp,ModuleParrot", self.read("svx.conf"))
        self.assertEqual(self.read("svxel.conf"), SVXEL)

    def test_svx_owner_writes_the_module_and_switches_asterisk_off(self):
        with open(self.p("modules.conf"), "w") as f:
            f.write(MODS.replace("noload  = chan_echolink.so", "load = chan_echolink.so"))
        form = dict(self.ON, el_owner="svx", svx_use="radio")
        changes, _n = h44._bld_el_changes(form, "magic")
        self.apply(changes)
        svxel = self.read("svxel.conf")
        for want in ("CALLSIGN=KD8PGK-L", "SYSOPNAME=Mike M", "LOCATION=Toledo, OH", "PASSWORD=keepme"):
            self.assertIn(want, svxel)
        self.assertIn("MODULES=ModuleHelp,ModuleParrot,ModuleEchoLink", self.read("svx.conf"))
        self.assertEqual(h44._cfgr_module_state(h44._cfgr_lines(self.read("modules.conf")), "chan_echolink"), "noload")
        self.assertEqual(self.read("el.conf"), ELCONF)

    def test_never_both(self):
        for form, profile in ((self.ON, "travel"), (dict(self.ON, el_owner="svx", svx_use="radio"), "magic")):
            changes, _n = h44._bld_el_changes(form, profile)
            self.apply(changes)
            asterisk_on = h44._cfgr_module_state(h44._cfgr_lines(self.read("modules.conf")), "chan_echolink") == "load"
            svx_on = "ModuleEchoLink" in self.read("svx.conf")
            self.assertNotEqual(asterisk_on, svx_on, profile)

    def test_states(self):
        self.assertEqual(h44._bld_echolink_state(self.ON, "travel")[0], "todo")
        changes, _n = h44._bld_el_changes(self.ON, "travel")
        self.apply(changes)
        self.assertEqual(h44._bld_echolink_state(self.ON, "travel")[0], "done")
        st, why = h44._bld_echolink_state(dict(self.ON, el_node="", pw_el=""), "travel")
        self.assertEqual(st, "warn")
        self.assertIn("password", why)

    def test_run_preview_then_apply(self):
        ok, lines = h44._bld_run_echolink(self.ON, "travel", True)
        self.assertTrue(ok)
        self.assertEqual(self.read("el.conf"), ELCONF)
        self.assertTrue(any("EchoLink runs in ASL3" in ln for ln in lines))
        with mock.patch.object(h44, "_cfgr_auto_point", lambda r, g: ("auto2", [])), \
                mock.patch.object(h44, "_cfgr_write_file", lambda path, data, uid, gid, mode: self.write_bytes(path, data)):
            ok, lines = h44._bld_run_echolink(self.ON, "travel", False)
        self.assertTrue(ok)
        self.assertIn("call = KD8PGK-L", self.read("el.conf"))
        self.assertTrue(any("automatic copy auto2" in ln for ln in lines))

    def test_live_detection(self):
        self.assertFalse(h44._bld_el_live())
        with open(self.p("modules.conf"), "w") as f:
            f.write(MODS.replace("noload  = chan_echolink.so", "load = chan_echolink.so"))
        self.assertTrue(h44._bld_el_live())
        with open(self.p("modules.conf"), "w") as f:
            f.write(MODS)
        with open(self.p("svx.conf"), "w") as f:
            f.write(SVX.replace("ModuleParrot", "ModuleParrot,ModuleEchoLink"))
        self.assertTrue(h44._bld_el_live())

    def test_the_steps_are_runnable_on_both_tabs(self):
        for sid in ("stfu_setup", "echolink"):
            self.assertIn(sid, h44._BLD_RUNNABLE)
            self.assertIn(sid, h44._BLD_PREVIEWABLE)
        for profile in ("travel", "magic"):
            ids = [i for i, _ in h44._bld_stage_defs("half", profile)]
            self.assertEqual(ids[ids.index("passwords") + 1:ids.index("passwords") + 4], ["stfu_setup", "echolink", "preset"])
            self.assertEqual(ids[ids.index("dvs") + 1], "stfu")


if __name__ == "__main__":
    unittest.main()
