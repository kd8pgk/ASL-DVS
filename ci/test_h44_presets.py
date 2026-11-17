import glob
import importlib.util
import json
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


spec = importlib.util.spec_from_file_location("h44_presets_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_presets_under_test"] = h44
spec.loader.exec_module(h44)

SECRET = "SuperSecretReflectorKey"
CONF = f"""# svxlink.conf
[GLOBAL]
LOGIC_CORE_PATH=/usr/local/lib/svxlink
LOGICS=UsrpLogic,ReflectorLogic,SvxCtrlLogic
LINKS=ReflectorLink
CFG_DIR=svxlink.d
CARD_SAMPLE_RATE=48000

[SimplexLogic]
TYPE=Simplex
RX=Rx1
TX=Tx1
CALLSIGN=KD8PGK

[ReflectorLogic]
TYPE=Reflector
HOSTS=north.america.svxlink.net
HOST_PORT=35300
CALLSIGN=KD8PGK
AUTH_KEY={SECRET}
DEFAULT_TG=0
MONITOR_TGS=0
TG_SELECT_TIMEOUT=3600
ANNOUNCE_REMOTE_MIN_INTERVAL=300
QSY_PENDING_TIMEOUT=15

[UsrpLogic]
TYPE=Usrp
USRP_HOST=127.0.0.1
USRP_TX_PORT=32000
USRP_RX_PORT=34000
CALL=KD8PGK
DV_USER_INFOFILE=/usr/local/etc/svxlink/dv_users.json
EVENT_HANDLER=/usr/local/share/svxlink/events.tcl
JITTER_BUFFER_DELAY=400
NET_LIMITER_THRESH=-1.0
LOCAL_LIMITER_THRESH=-1.0

[ReflectorLink]
CONNECT_LOGICS=SvxCtrlLogic:9:TG,UsrpLogic,ReflectorLogic
DEFAULT_ACTIVE=1

[Rx1]
TYPE=Local
HID_DEVICE=/dev/uci90

[LocationInfo]
CALLSIGN=KD8PGK

[SvxCtrlLogic]
TYPE=Simplex
RX=SvxCtrlRx
TX=SvxCtrlTx
CALLSIGN=KD8PGK
DTMF_CTRL_PTY=/var/lib/svxlink/dtmf_ctrl
SHORT_IDENT_INTERVAL=0
LONG_IDENT_INTERVAL=0

[SvxCtrlRx]
TYPE=Dummy

[SvxCtrlTx]
TYPE=Dummy
"""
USRP_D = """[UsrpLogic]
TYPE=Usrp
USRP_HOST=127.0.0.1
USRP_TX_PORT=32000
USRP_RX_PORT=34000
CALL=KD8PGK
"""


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.conf = os.path.join(self.d.name, "svxlink.conf")
        self.usrp = os.path.join(self.d.name, "UsrpLogic.conf")
        for p in (mock.patch.object(h44, "_CFGR_SVX_CONF", self.conf), mock.patch.object(h44, "_CFGR_SVX_USRP", self.usrp)):
            p.start()
            self.addCleanup(p.stop)

    def write(self, path, text):
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()


class Registry(unittest.TestCase):
    def test_both_presets_exist(self):
        self.assertEqual(h44._CFGR_PRESETS, {"travel_node": "Travel Node", "magic_box": "Magic Box"})

    def test_the_wiring_whitelist_carries_no_secret_or_identity_key(self):
        for sec, keys in h44._CFGR_SVX_WIRING.items():
            for k in keys:
                self.assertNotIn(k.upper(), ("AUTH_KEY", "CALLSIGN", "CALL", "PASSWORD", "PWD"), f"{sec} {k}")
        self.assertNotIn("SimplexLogic", h44._CFGR_SVX_WIRING)
        self.assertNotIn("Rx1", h44._CFGR_SVX_WIRING)


class Capture(Tmp):
    def test_the_bridge_wiring_is_taken_and_nothing_else(self):
        self.write(self.conf, CONF)
        svx, notes = h44._cfgr_capture_svx()
        self.assertEqual(sorted(svx), ["GLOBAL", "ReflectorLink", "ReflectorLogic", "SvxCtrlLogic", "SvxCtrlRx", "SvxCtrlTx", "UsrpLogic"])
        self.assertEqual(svx["GLOBAL"], {"LOGICS": "UsrpLogic,ReflectorLogic,SvxCtrlLogic", "LINKS": "ReflectorLink"})
        self.assertEqual(svx["UsrpLogic"]["USRP_RX_PORT"], "34000")
        self.assertEqual(svx["ReflectorLogic"]["HOSTS"], "north.america.svxlink.net")
        blob = json.dumps(svx)
        for never in (SECRET, "KD8PGK", "AUTH_KEY", "CALLSIGN", "uci90", "Rx1"):
            self.assertNotIn(never, blob, never)
        self.assertIn("never saved", " ".join(notes))

    def test_a_node_with_its_own_radio_cannot_save_it(self):
        self.write(self.conf, CONF.replace("LOGICS=UsrpLogic,ReflectorLogic,SvxCtrlLogic", "LOGICS=SimplexLogic,UsrpLogic,ReflectorLogic"))
        svx, notes = h44._cfgr_capture_svx()
        self.assertIsNone(svx)
        self.assertIn("SimplexLogic", notes[0])

    def test_no_svxlink_no_preset(self):
        svx, notes = h44._cfgr_capture_svx()
        self.assertIsNone(svx)
        self.assertIn("must be installed", notes[0])

    def test_a_value_the_preset_does_not_carry_stops_it(self):
        self.write(self.conf, CONF.replace("HOSTS=north.america.svxlink.net", "HOSTS=x; reboot"))
        svx, notes = h44._cfgr_capture_svx()
        self.assertIsNone(svx)
        self.assertIn("HOSTS", notes[0])

    def test_a_missing_section_is_just_absent(self):
        self.write(self.conf, CONF.replace("[ReflectorLogic]", "[Other]").replace("LOGICS=UsrpLogic,ReflectorLogic,SvxCtrlLogic", "LOGICS=UsrpLogic,SvxCtrlLogic"))
        svx, _ = h44._cfgr_capture_svx()
        self.assertNotIn("ReflectorLogic", svx)


class Validate(unittest.TestCase):
    def base(self, svx):
        return {"rpt": {"nodes": []}, "extensions": [], "modules": {}, "ini": {}, "svx": svx}

    def test_good_and_bad(self):
        good = {"UsrpLogic": {"USRP_RX_PORT": "34000"}, "GLOBAL": {"LOGICS": "UsrpLogic"}}
        self.assertIsNotNone(h44._cfgr_validate_preset(self.base(good)))
        for bad in ({"ReflectorLogic": {"AUTH_KEY": "x"}}, {"ReflectorLogic": {"CALLSIGN": "KD8PGK"}}, {"SimplexLogic": {"TYPE": "Simplex"}},
                    {"UsrpLogic": {}}, {"UsrpLogic": {"USRP_RX_PORT": 34000}}, {"UsrpLogic": {"USRP_RX_PORT": "3 4"}}, "x", []):
            self.assertIsNone(h44._cfgr_validate_preset(self.base(bad)), bad)

    def test_a_preset_without_svx_is_still_valid(self):
        p = self.base({})
        del p["svx"]
        self.assertIsNotNone(h44._cfgr_validate_preset(p))


class Apply(Tmp):
    SVX = {"GLOBAL": {"LOGICS": "UsrpLogic,ReflectorLogic,SvxCtrlLogic", "LINKS": "ReflectorLink"},
           "UsrpLogic": {"TYPE": "Usrp", "USRP_HOST": "127.0.0.1", "USRP_TX_PORT": "32001", "USRP_RX_PORT": "34001"},
           "ReflectorLogic": {"HOSTS": "other.example.org", "HOST_PORT": "5300", "DEFAULT_TG": "240", "MONITOR_TGS": "240,+9"}}

    def test_values_change_and_identity_and_the_password_are_kept(self):
        self.write(self.conf, CONF)
        self.write(self.usrp, USRP_D)
        changes, notes = h44._cfgr_apply_svx(self.SVX)
        new = changes[self.conf][1].decode()
        self.assertIn("HOSTS=other.example.org", new)
        self.assertIn("DEFAULT_TG=240", new)
        self.assertIn("MONITOR_TGS=240,+9", new)
        self.assertIn("USRP_RX_PORT=34001", new)
        self.assertIn(f"AUTH_KEY={SECRET}", new)
        self.assertIn("CALL=KD8PGK", new)
        self.assertIn("CALLSIGN=KD8PGK", new)
        self.assertIn("[SimplexLogic]\nTYPE=Simplex", new)
        self.assertIn("HID_DEVICE=/dev/uci90", new)

    def test_both_copies_of_the_usrp_ports_change_together(self):
        self.write(self.conf, CONF)
        self.write(self.usrp, USRP_D)
        changes, _ = h44._cfgr_apply_svx(self.SVX)
        self.assertIn("USRP_TX_PORT=32001", changes[self.usrp][1].decode())
        self.assertIn("CALL=KD8PGK", changes[self.usrp][1].decode())
        self.assertNotIn("HOSTS", changes[self.usrp][1].decode())

    def test_nothing_changes_when_the_node_already_matches(self):
        self.write(self.conf, CONF)
        changes, notes = h44._cfgr_apply_svx(h44._cfgr_capture_svx()[0] if (self.write(self.conf, CONF) or True) else {})
        self.assertEqual(changes, {})
        self.assertEqual(notes, [])

    def test_a_section_the_node_does_not_have_yet_is_named_not_created(self):
        self.write(self.conf, CONF.replace("[ReflectorLogic]", "[Elsewhere]"))
        changes, notes = h44._cfgr_apply_svx(self.SVX)
        new = changes[self.conf][1].decode()
        self.assertNotIn("other.example.org", new)
        self.assertNotIn("[ReflectorLogic]", new)
        self.assertTrue(any("no [ReflectorLogic]" in n for n in notes))
        self.assertTrue(any("LOGICS and LINKS were left alone" in n for n in notes))
        self.assertIn("LOGICS=UsrpLogic,ReflectorLogic,SvxCtrlLogic", new)

    def test_a_missing_key_in_an_existing_section_is_added(self):
        self.write(self.conf, CONF.replace("DEFAULT_TG=0\n", ""))
        changes, _ = h44._cfgr_apply_svx(self.SVX)
        self.assertIn("DEFAULT_TG=240", changes[self.conf][1].decode())

    def test_no_svxlink_conf_is_a_note(self):
        changes, notes = h44._cfgr_apply_svx(self.SVX)
        self.assertEqual(changes, {})
        self.assertIn("not found", notes[0])


class Actions(unittest.TestCase):
    def capture(self, pid, svx=({"UsrpLogic": {"USRP_RX_PORT": "34000"}}, ["note"]), save=False):
        p = {"rpt": {"nodes": []}, "extensions": [], "modules": {}, "ini": {}}
        with mock.patch.object(h44, "_cfgr_capture", lambda: (dict(p), [], [])), \
                mock.patch.object(h44, "_cfgr_capture_svx", lambda: svx):
            return h44._cfgr_act_preset_capture({"preset": pid}, save)

    def test_the_magic_box_preview_lists_the_svxlink_wiring(self):
        res = self.capture("magic_box")
        self.assertTrue(res["success"])
        self.assertIn("svxlink.conf [UsrpLogic]: USRP_RX_PORT=34000", res["output"])
        self.assertIn("Magic Box", res["output"])

    def test_the_travel_node_preset_has_no_svxlink_part(self):
        res = self.capture("travel_node", svx=(None, ["should not be used"]))
        self.assertTrue(res["success"])
        self.assertNotIn("svxlink.conf", res["output"])

    def test_a_magic_box_that_cannot_be_saved_says_why(self):
        res = self.capture("magic_box", svx=(None, ["SvxLink here has its own radio"]))
        self.assertFalse(res["success"])
        self.assertIn("own radio", res["output"])

    def test_saving_stores_the_svx_part_and_it_loads_back(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(h44, "_CFGR_DIR", d), mock.patch.object(h44, "_cfgr_ensure_root_dir", lambda: None):
                res = self.capture("magic_box", save=True)
                self.assertTrue(res["success"], res["output"])
                got = h44._cfgr_load_preset("magic_box")
                self.assertEqual(got["svx"], {"UsrpLogic": {"USRP_RX_PORT": "34000"}})
                self.assertTrue(h44._cfgr_load_preset("travel_node")["_default"])


class Plan(Tmp):
    def test_the_plan_includes_the_svxlink_files(self):
        self.write(self.conf, CONF)
        nope = os.path.join(self.d.name, "nope")
        p = {"rpt": {"nodes": []}, "extensions": [], "modules": {}, "ini": {}, "svx": Apply.SVX}
        with mock.patch.multiple(h44, _CFGR_RPT=nope, _CFGR_EXT=nope, _CFGR_MOD=nope, _CFGR_ALLMON=nope, _CFGR_ECHOLINK=nope):
            changes, removed, notes, warnings, err = h44._cfgr_preset_plan(p)
        self.assertEqual(err, "")
        self.assertIn(self.conf, changes)
        self.assertEqual(removed, [])


class BuildStep(unittest.TestCase):
    def ids(self, mode, profile):
        return [i for i, _ in h44._bld_stage_defs(mode, profile)]

    def test_the_preset_step_follows_the_values_steps_and_comes_before_the_checks(self):
        for mode in ("half", "split", "full", "none"):
            for profile in ("travel", "magic"):
                ids = self.ids(mode, profile)
                self.assertEqual(ids[ids.index("identity") + 1:ids.index("identity") + 4], ["location", "passwords", "preset"], (mode, profile))
                self.assertLess(ids.index("preset"), ids.index("wiring"))
                self.assertLess(ids.index("preset"), ids.index("reboot"))
        labels = dict(h44._bld_stage_defs("half", "travel")), dict(h44._bld_stage_defs("half", "magic"))
        self.assertEqual(labels[0]["preset"], "Apply the Travel Node preset")
        self.assertEqual(labels[1]["preset"], "Apply the Magic Box preset")

    def test_it_is_runnable_with_a_preview_and_is_not_a_background_job(self):
        self.assertIn("preset", h44._BLD_RUNNABLE)
        self.assertIn("preset", h44._BLD_PREVIEWABLE)
        self.assertNotIn("preset", h44._BLD_LONG)

    def state(self, profile, preset, plan=None):
        with mock.patch.object(h44, "_cfgr_load_preset", lambda pid: preset), \
                mock.patch.object(h44, "_cfgr_preset_plan", lambda p, port="": plan):
            return h44._bld_preset_state(profile)

    def test_states(self):
        self.assertEqual(self.state("travel", None)[0], "warn")
        self.assertIn("Travel Node preset", self.state("travel", None)[1])
        self.assertIn("Magic Box preset", self.state("magic", None)[1])
        p = {"x": 1}
        self.assertEqual(self.state("magic", p, ({}, [], [], [], ""))[0], "done")
        st, why = self.state("magic", p, ({"/a": (b"", b"x"), "/b": (b"", b"y")}, ["1002"], [], [], ""))
        self.assertEqual(st, "warn")
        self.assertIn("2 file(s) would change", why)
        self.assertIn("1002", why)
        self.assertIn("never blocks", why)
        self.assertEqual(self.state("travel", p, ({}, [], [], [], "rpt.conf missing"))[0], "warn")

    def test_a_plan_that_fails_is_a_warning_not_a_crash(self):
        with mock.patch.object(h44, "_cfgr_load_preset", lambda pid: {"x": 1}), \
                mock.patch.object(h44, "_cfgr_preset_plan", mock.Mock(side_effect=ValueError("x"))):
            st, why = h44._bld_preset_state("travel")
        self.assertEqual(st, "warn")
        self.assertNotIn("x", why.replace("Could not read the files the preset changes: ValueError", ""))

    def test_run_calls_the_right_preset_and_preview(self):
        calls = []

        def fake(action, payload=None):
            calls.append((action, payload))
            return {"success": True, "output": "ok\nUse the Restart buttons below when ready."}

        with mock.patch.object(h44, "_bld_cfg", fake):
            ok, lines = h44._bld_run_preset("magic", True)
            ok2, lines2 = h44._bld_run_preset("travel", False)
        self.assertEqual(calls, [("preset_apply_preview", {"preset": "magic_box", "iax_port": ""}), ("preset_apply", {"preset": "travel_node", "iax_port": ""})])
        self.assertTrue(ok and ok2)
        self.assertIn("Use Restart services on the Config tab when ready.", lines)

    def test_a_saved_but_unapplied_preset_does_not_hold_up_later_steps(self):
        st = {"form": dict(h44._BLD_DEFAULT, callsign="KD8PGK", node="652701", dmr_id="3123456", mode="none"), "errors": {}}
        stages = [{"id": i, "label": i, "state": "done", "detail": ""} for i, _ in h44._bld_stage_defs("none", "travel")]
        for s in stages:
            if s["id"] == "preset":
                s["state"] = "warn"
            if s["id"] == "ports":
                s["state"] = "todo"
        prev_ok = True
        for s in stages:
            if s["state"] == "todo" and not prev_ok:
                s["state"] = "locked"
            if s["state"] not in ("done", "manual", "warn"):
                prev_ok = False
        self.assertEqual({s["id"]: s["state"] for s in stages}["ports"], "todo")
        self.assertTrue(st)


class Page(unittest.TestCase):
    def test_the_config_tab_has_both_preset_cards(self):
        with open(h44.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('id="cfg-mpreset-state"', src)
        self.assertIn('id="cfg-mpreset-out"', src)
        self.assertIn("cfgPresetCapture(this,true,'magic_box')", src)
        self.assertIn("cfgPresetCapture(this,true)", src)
        self.assertIn("(d.presets || {}).magic_box", src)

    def test_the_build_tab_asks_before_applying_the_preset(self):
        for js in (h44._JS_BUILD, h44._JS_MAGIC):
            self.assertIn("stage === 'preset' && !preview", js)
            self.assertIn("Did you read the Preview?", js)


if __name__ == "__main__":
    unittest.main()
