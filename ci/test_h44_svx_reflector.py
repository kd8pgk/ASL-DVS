import glob
import importlib.util
import io
import os
import re
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
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


h44 = load("h44_svx_reflector_under_test", newest("44helper_v[0-9]*.py"))

SVXLINK_CONF = """[GLOBAL]
LOGICS=SimplexLogic,UsrpLogic
CFG_DIR=svxlink.d
LINKS=LinkToUsrp

[SimplexLogic]
TYPE=Simplex
CALLSIGN=AA1AA

[ReflectorLogic]
TYPE=Reflector
HOSTS=reflector-primary.example.org,reflector-secondary.example.org:5301
#HOST_PORT=5300
CALLSIGN="MYCALL"
#AUTH_KEY="Change this key now!"
#DEFAULT_TG=9
#MONITOR_TGS=9,240,24021+
#TG_SELECT_TIMEOUT=30

[UsrpLogic]
TYPE=Usrp
CALL=AA1AA

[ReflectorLink]
CONNECT_LOGICS=SimplexLogic:9:TG,ReflectorLogic
DEFAULT_ACTIVE=1
#TIMEOUT=300

[LinkToUsrp]
CONNECT_LOGICS=SimplexLogic:9:USRP,UsrpLogic
DEFAULT_ACTIVE=1
"""

REFLECTOR_CONF = """[GLOBAL]
TIMESTAMP_FORMAT="%c"
LISTEN_PORT=5300
#CERT_PKI_DIR=pki/

[SERVER_CERT]
#COMMON_NAME=svxreflector.example.org
#SUBJECT_ALT_NAME=DNS:public-hostname.example.org,IP:172.17.1.42

[USERS]
#SM0ABC-1=MyNodes

[PASSWORDS]
#MyNodes="Change this key now!"
"""


class FakeProc:
    def __init__(self, test):
        self.test = test
        self.calls = []

    def run(self, argv, **kw):
        self.calls.append(list(argv))
        out = ""
        if argv[:2] == ["systemctl", "restart"] and argv[2] == "svxlink-usrp" and self.test.login_line:
            with open(self.test.log, "a") as fh:
                fh.write(self.test.login_line + "\n")
        if argv[:2] == ["systemctl", "is-active"]:
            out = "active\n"
        if argv[:1] == ["ss"]:
            out = "LISTEN 0 5 0.0.0.0:5300 0.0.0.0:*\n"
        if argv[:2] == ["python3", "-c"]:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")


class ScriptBase(unittest.TestCase):
    login_line = "Mon: ReflectorLogic: Authentication OK"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="h44_refl_")
        self.conf = os.path.join(self.tmp, "svxlink.conf")
        self.rconf = os.path.join(self.tmp, "svxreflector.conf")
        self.rbin = os.path.join(self.tmp, "svxreflector")
        self.log = os.path.join(self.tmp, "svxlink.log")
        self.unit = os.path.join(self.tmp, "svxreflector.service")
        self.h44conf = os.path.join(self.tmp, "44helper.conf")
        self.cards = os.path.join(self.tmp, "cards")
        self.simpleusb = os.path.join(self.tmp, "simpleusb.conf")
        self.usbradio = os.path.join(self.tmp, "usbradio.conf")
        self.rptconf = os.path.join(self.tmp, "rpt.conf")
        for p, t in ((self.conf, SVXLINK_CONF), (self.rconf, REFLECTOR_CONF), (self.rbin, ""), (self.log, "")):
            with open(p, "w") as fh:
                fh.write(t)
        self.proc = FakeProc(self)

    def run_script(self, src, env):
        src = (src.replace('"/usr/local/etc/svxlink/svxlink.conf"', repr(self.conf))
               .replace('"/usr/local/etc/svxlink/svxreflector.conf"', repr(self.rconf))
               .replace('"/usr/local/bin/svxreflector"', repr(self.rbin))
               .replace('"/var/log/svxlink"', repr(self.log))
               .replace('"/var/lib/svxlink/dtmf_ctrl"', repr(os.path.join(self.tmp, "dtmf_ctrl")))
               .replace('"/var/lib/svxreflector/pki/"', repr(os.path.join(self.tmp, "pki") + "/"))
               .replace('"/etc/systemd/system/svxreflector.service"', repr(self.unit))
               .replace('"/var/lib/svxlink"', repr(self.tmp))
               .replace('"/etc/44helper/44helper.conf"', repr(self.h44conf))
               .replace('"/proc/asound/cards"', repr(self.cards))
               .replace('"/dev/hidraw*"', repr(os.path.join(self.tmp, "hidraw*")))
               .replace('"/sys/class/hidraw/"', repr(os.path.join(self.tmp, "sys") + "/"))
               .replace('"/etc/asterisk/simpleusb.conf"', repr(self.simpleusb))
               .replace('"/etc/asterisk/usbradio.conf"', repr(self.usbradio))
               .replace('"/etc/asterisk/rpt.conf"', repr(self.rptconf)))
        fake = types.ModuleType("subprocess")
        fake.run = self.proc.run
        out = io.StringIO()
        code = 0
        with mock.patch.dict(sys.modules, {"subprocess": fake}), mock.patch.dict(os.environ, env), \
                mock.patch("time.sleep", lambda s: None), redirect_stdout(out):
            try:
                exec(compile(src, "script", "exec"), {"__name__": "__main__"})
            except SystemExit as e:
                code = e.code or 0
        return code, out.getvalue()

    def read(self, p):
        with open(p) as fh:
            return fh.read()


CONN_ENV = {"HOST": "127.0.0.1", "PORT": "5300", "KEY": "TestKey123", "TG": "0", "MON": "91,240+"}


class ConnectStep(ScriptBase):
    def test_writes_the_three_parts_and_logs_in(self):
        code, out = self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        self.assertEqual(code, 0, out)
        t = self.read(self.conf)
        self.assertIn("LOGICS=SimplexLogic,UsrpLogic,ReflectorLogic,SvxCtrlLogic\n", t)
        self.assertIn("LINKS=LinkToUsrp,ReflectorLink\n", t)
        refl = t.split("[ReflectorLogic]")[1].split("\n[")[0]
        for line in ("HOSTS=127.0.0.1", "HOST_PORT=5300", 'CALLSIGN="AA1AA"', 'AUTH_KEY="TestKey123"', "DEFAULT_TG=0",
                     "MONITOR_TGS=91,240+", "TG_SELECT_TIMEOUT=3600"):
            self.assertIn(line + "\n", refl)
        self.assertNotIn("MYCALL", refl)
        self.assertIn("[SvxCtrlLogic]\nTYPE=Simplex\nRX=SvxCtrlRx\nTX=SvxCtrlTx\nCALLSIGN=AA1AA\nDTMF_CTRL_PTY=", t)
        self.assertIn("SHORT_IDENT_INTERVAL=0\nLONG_IDENT_INTERVAL=0", t)
        self.assertIn("[SvxCtrlRx]\nTYPE=Dummy", t)
        self.assertIn("[SvxCtrlTx]\nTYPE=Dummy", t)
        link = t.split("[ReflectorLink]")[1].split("\n[")[0]
        self.assertIn("CONNECT_LOGICS=SvxCtrlLogic:9:TG,UsrpLogic,ReflectorLogic\n", link)
        self.assertIn("#TIMEOUT=300", link)
        self.assertIn("[LinkToUsrp]\nCONNECT_LOGICS=SimplexLogic:9:USRP,UsrpLogic", t)
        self.assertTrue(os.path.exists(self.conf + ".44helper-bak"))
        self.assertIn("Logged in to the reflector.", out)
        self.assertIn(["systemctl", "restart", "svxlink-usrp"], self.proc.calls)

    def test_second_run_changes_nothing(self):
        self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        first = self.read(self.conf)
        code, out = self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        self.assertEqual(code, 0)
        self.assertEqual(self.read(self.conf), first)
        self.assertIn("already set", out)
        self.assertEqual(first.count("[SvxCtrlLogic]"), 1)
        self.assertEqual(first.count("ReflectorLink"), 2)

    def test_blank_monitor_comments_an_old_one_out(self):
        self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        self.run_script(h44._SVX_REFL_CONN_PY, dict(CONN_ENV, MON=""))
        refl = self.read(self.conf).split("[ReflectorLogic]")[1].split("\n[")[0]
        self.assertNotRegex(refl, r"(?m)^MONITOR_TGS=")
        self.assertIn("#MONITOR_TGS=91,240+", refl)

    def test_new_host_and_key_replace_the_old_ones(self):
        self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        self.run_script(h44._SVX_REFL_CONN_PY, dict(CONN_ENV, HOST="svx.example.org", KEY="OtherKey99", TG="240"))
        refl = self.read(self.conf).split("[ReflectorLogic]")[1].split("\n[")[0]
        self.assertIn("HOSTS=svx.example.org\n", refl)
        self.assertIn('AUTH_KEY="OtherKey99"\n', refl)
        self.assertIn("DEFAULT_TG=240\n", refl)
        self.assertNotIn("TestKey123", refl)

    def test_no_callsign_stops_without_writing(self):
        with open(self.conf, "w") as fh:
            fh.write(SVXLINK_CONF.replace("CALLSIGN=AA1AA", "CALLSIGN=MYCALL").replace("CALL=AA1AA", "CALL=N0CALL"))
        before = self.read(self.conf)
        code, out = self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        self.assertEqual(code, 1)
        self.assertIn("STOPPED", out)
        self.assertEqual(self.read(self.conf), before)
        self.assertEqual(self.proc.calls, [])

    def test_a_failed_login_is_reported(self):
        self.login_line = "Mon: ReflectorLogic: Authentication failed"
        code, out = self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        self.assertEqual(code, 1)
        self.assertIn("Not logged in yet", out)
        self.assertIn("Authentication failed", out)


TEST_ENV = {"CALL": "aa1aa", "KEY": "TestKey123"}


class TestReflectorStep(ScriptBase):
    def test_sets_users_passwords_and_certificate_name(self):
        code, out = self.run_script(h44._SVX_REFL_TEST_PY, TEST_ENV)
        self.assertEqual(code, 0, out)
        t = self.read(self.rconf)
        tag = "# 44helper: test reflector user (next line)"
        self.assertIn("[USERS]\n" + tag + "\nAA1AA=44helperNodes\n", t)
        self.assertIn("[PASSWORDS]\n" + tag + '\n44helperNodes="TestKey123"\n', t)
        self.assertIn("COMMON_NAME=localhost\n", t)
        self.assertIn("SUBJECT_ALT_NAME=DNS:localhost,IP:127.0.0.1\n", t)
        self.assertRegex(t, r"(?m)^CERT_PKI_DIR=.*pki/$")
        self.assertNotRegex(t, r"(?m)^[^#\n]*=[^\n]*;\s")
        unit = self.read(self.unit)
        self.assertIn("User=svxlink", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn(["systemctl", "restart", "svxreflector"], self.proc.calls)
        self.assertIn("listening on TCP 5300", out)

    def test_second_run_replaces_the_user_instead_of_adding_one(self):
        self.run_script(h44._SVX_REFL_TEST_PY, TEST_ENV)
        self.run_script(h44._SVX_REFL_TEST_PY, dict(TEST_ENV, KEY="NewKey456"))
        t = self.read(self.rconf)
        self.assertEqual(t.count("44helper: test reflector user"), 2)
        self.assertIn('44helperNodes="NewKey456"', t)
        self.assertNotIn("TestKey123", t)
        self.assertIn('#MyNodes="Change this key now!"', t)

    def test_bad_callsign_or_missing_program_stops(self):
        before = self.read(self.rconf)
        code, out = self.run_script(h44._SVX_REFL_TEST_PY, dict(TEST_ENV, CALL="a b"))
        self.assertEqual(code, 1)
        os.remove(self.rbin)
        code2, out2 = self.run_script(h44._SVX_REFL_TEST_PY, TEST_ENV)
        self.assertEqual(code2, 1)
        self.assertIn("run the build steps", out2)
        self.assertEqual(self.read(self.rconf), before)


WIRE_ENV = {"CALL": "KD8PGK", "TX": "32000", "RX": "34000"}


class WireStep(ScriptBase):
    def test_a_stock_radio_logic_is_taken_out_with_the_links_that_joined_it(self):
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, WIRE_ENV)
        self.assertEqual(code, 0, out)
        t = self.read(self.conf)
        self.assertIn("LOGICS=UsrpLogic\n", t)
        self.assertIn("LINKS=\n", t)
        self.assertIn("Radio logic taken out (ASL3 owns the radio): SimplexLogic", out)
        self.assertIn("Links that joined it taken out: LinkToUsrp", out)
        usrp = t.split("[UsrpLogic]")[1].split("\n[")[0]
        for line in ("CALL=KD8PGK", "USRP_HOST=127.0.0.1", "USRP_TX_PORT=32000", "USRP_RX_PORT=34000"):
            self.assertIn(line + "\n", usrp + "\n")
        self.assertIn("CALLSIGN=KD8PGK", t)
        self.assertTrue(os.path.exists(self.conf + ".44helper-bak"))
        with open(self.conf + ".44helper-bak") as fh:
            self.assertIn("LOGICS=SimplexLogic,UsrpLogic", fh.read())

    def test_a_node_already_wired_to_a_reflector_keeps_its_control_logic_and_reflector_link(self):
        self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, WIRE_ENV)
        self.assertEqual(code, 0, out)
        t = self.read(self.conf)
        self.assertIn("LOGICS=UsrpLogic,ReflectorLogic,SvxCtrlLogic\n", t)
        self.assertIn("LINKS=ReflectorLink\n", t)
        self.assertIn("[SvxCtrlLogic]\nTYPE=Simplex\nRX=SvxCtrlRx", t)

    def test_a_logic_with_a_dummy_receiver_is_not_a_radio(self):
        conf = SVXLINK_CONF.replace("[SimplexLogic]\nTYPE=Simplex\n", "[SimplexLogic]\nTYPE=Simplex\nRX=Dummy1\nTX=Dummy1\n") + "\n[Dummy1]\nTYPE=Dummy\n"
        with open(self.conf, "w") as fh:
            fh.write(conf)
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, WIRE_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("LOGICS=SimplexLogic,UsrpLogic\n", self.read(self.conf))
        self.assertNotIn("Radio logic taken out", out)

    def test_a_repeater_logic_is_a_radio_too(self):
        conf = SVXLINK_CONF.replace("LOGICS=SimplexLogic,UsrpLogic", "LOGICS=SimplexLogic,RepeaterLogic,UsrpLogic") + \
            "\n[RepeaterLogic]\nTYPE=Repeater\nRX=Rx1\nTX=Tx1\n\n[Rx1]\nTYPE=Local\n"
        with open(self.conf, "w") as fh:
            fh.write(conf)
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, WIRE_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("LOGICS=UsrpLogic\n", self.read(self.conf))
        self.assertIn("SimplexLogic, RepeaterLogic", out)

    def test_second_run_changes_nothing(self):
        self.run_script(h44._SVX_USRP_WIRE_PY, WIRE_ENV)
        once = self.read(self.conf)
        code, _out = self.run_script(h44._SVX_USRP_WIRE_PY, WIRE_ENV)
        self.assertEqual(code, 0)
        self.assertEqual(self.read(self.conf), once)

    def test_bad_input_changes_nothing(self):
        before = self.read(self.conf)
        for env in (dict(WIRE_ENV, TX="0"), dict(WIRE_ENV, RX="70000"), dict(WIRE_ENV, TX="x"),
                    dict(WIRE_ENV, TX="32000", RX="32000"), dict(WIRE_ENV, CALL="")):
            code, out = self.run_script(h44._SVX_USRP_WIRE_PY, env)
            self.assertEqual(code, 1, env)
            self.assertIn("STOPPED", out)
        self.assertEqual(self.read(self.conf), before)
        self.assertFalse(os.path.exists(self.conf + ".44helper-bak"))

    def test_the_step_asks_bridge_or_radio_and_the_guide_text_covers_both(self):
        step = {s["id"]: s for s in h44._SVXLINK_SCRIPTS["install"]["usrp"]}["usrp_logic_conf"]
        self.assertIn("bridge under ASL3", step["note"])
        self.assertIn("with its own radio", step["note"].lower())
        self.assertIn("LOGICS=UsrpLogic", h44._SVX_USRP_LOGIC_SNIPPET)
        self.assertIn("With a radio of its own", h44._SVX_USRP_LOGIC_SNIPPET)
        fields = {f["id"]: f for f in step["fields"]}
        self.assertEqual(fields["svx_use"]["default"], "bridge")
        self.assertEqual([o[0] for o in fields["svx_use"]["options"]], ["bridge", "radio"])
        for fid in ("svx_rtype", "svx_audio", "svx_rdev", "svx_sqlpin", "svx_pttpin", "svx_rrefl"):
            self.assertEqual(fields[fid]["show_if"], "svx_use=radio", fid)
        cmd, why = h44._step_command(step, {"callsign": "KD8PGK", "port": "32000", "rx_port": "34000",
                                            "svx_use": "bridge", "svx_rtype": "cm108", "svx_audio": "auto",
                                            "svx_rdev": "auto", "svx_sqlpin": "auto", "svx_pttpin": "auto",
                                            "svx_rrefl": "no"})
        self.assertEqual(why, "")
        self.assertIn("CALL='KD8PGK' TX='32000' RX='34000' USE='bridge' RTYPE='cm108'", cmd)

    def test_the_new_fields_are_checked(self):
        step = {s["id"]: s for s in h44._SVXLINK_SCRIPTS["install"]["usrp"]}["usrp_logic_conf"]
        good = {"callsign": "KD8PGK", "port": "32000", "rx_port": "34000", "svx_use": "radio", "svx_rtype": "serial",
                "svx_audio": "alsa:plughw:CARD=Device", "svx_rdev": "/dev/ttyUSB0", "svx_sqlpin": "CTS",
                "svx_pttpin": "DTRRTS", "svx_rrefl": "yes"}
        self.assertEqual(h44._step_command(step, good)[1], "")
        for k, bad in (("svx_use", "both"), ("svx_rtype", "usb"), ("svx_audio", "plughw:0"), ("svx_audio", "alsa:x;rm"),
                       ("svx_rdev", "ttyUSB0"), ("svx_rdev", "/dev/../etc/x y"), ("svx_sqlpin", "a b"),
                       ("svx_pttpin", "'x'"), ("svx_rrefl", "maybe")):
            self.assertNotEqual(h44._step_command(step, dict(good, **{k: bad}))[1], "", (k, bad))

    def test_the_page_draws_selects_and_hides_radio_fields_until_radio_is_chosen(self):
        with open(h44.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("function svxFieldVis(sel)", src)
        self.assertIn("'<select class=\"asl3-cmd-input\" id=\"svx-field-'", src)
        self.assertIn("hide = (ctl && String(ctl.default || '') === sp[1]) ? 'block' : 'none';", src)
        self.assertIn("style=\"display:' + hide + ';font-family", src)


RADIO_CONF = SVXLINK_CONF + """
[Rx1]
TYPE=Local
AUDIO_DEV=alsa:plughw:CARD=Old
SQL_DET=VOX
SERIAL_PORT=/dev/ttyS0

[Tx1]
TYPE=Local
AUDIO_DEV=alsa:plughw:CARD=Old
PTT_TYPE=Dummy
"""
CARDS_ONE = " 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0\n 1 [Device          ]: USB-Audio - USB Audio Device\n"
CARDS_TWO = CARDS_ONE + " 2 [Spare           ]: USB-Audio - USB PnP Sound Device\n"
RADIO_ENV = dict(WIRE_ENV, USE="radio", RTYPE="cm108", AUDIO="auto", RDEV="auto", SQLPIN="auto", PTTPIN="auto",
                 RREFL="no")


class WireRadio(ScriptBase):
    def setUp(self):
        super().setUp()
        with open(self.conf, "w") as fh:
            fh.write(RADIO_CONF)
        with open(self.cards, "w") as fh:
            fh.write(CARDS_ONE)
        self.hid = os.path.join(self.tmp, "hidraw0")
        with open(self.hid, "w") as fh:
            fh.write("")
        usb = os.path.join(self.tmp, "usb", "1-1.2", "1-1.2:1.3")
        os.makedirs(usb)
        os.makedirs(os.path.join(self.tmp, "sys", "hidraw0"))
        os.symlink(usb, os.path.join(self.tmp, "sys", "hidraw0", "device"))

    def section(self, text, name):
        return text.split("[" + name + "]")[1].split("\n[")[0]

    def test_cm108_radio_is_applied_with_auto_values(self):
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        self.assertEqual(code, 0, out)
        t = self.read(self.conf)
        self.assertIn("LOGICS=SimplexLogic,UsrpLogic\n", t)
        self.assertIn("LINKS=LinkToUsrp\n", t)
        link = self.section(t, "LinkToUsrp") + "\n"
        for line in ("CONNECT_LOGICS=SimplexLogic:9:USRP,UsrpLogic", "DEFAULT_ACTIVE=1", "TIMEOUT=0"):
            self.assertIn(line + "\n", link)
        rx = self.section(t, "Rx1")
        for line in ("AUDIO_DEV=alsa:plughw:CARD=Device", "SQL_DET=HIDRAW", "HID_DEVICE=" + self.hid, "HID_SQL_PIN=VOL_DN"):
            self.assertIn(line + "\n", rx + "\n")
        tx = self.section(t, "Tx1")
        for line in ("AUDIO_DEV=alsa:plughw:CARD=Device", "PTT_TYPE=Hidraw", "HID_DEVICE=" + self.hid, "HID_PTT_PIN=GPIO3"):
            self.assertIn(line + "\n", tx + "\n")
        self.assertIn("SvxLink is set up with its own radio.", out)
        self.assertIn("[svxlink]", self.read(self.h44conf))
        self.assertIn("use = radio", self.read(self.h44conf))

    def test_serial_and_gpio_radios_write_their_own_keys(self):
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, dict(RADIO_ENV, RTYPE="serial", RDEV="/dev/ttyUSB1",
                                                                 SQLPIN="DSR", PTTPIN="RTS"))
        self.assertEqual(code, 0, out)
        t = self.read(self.conf)
        self.assertIn("SQL_DET=SERIAL\n", self.section(t, "Rx1") + "\n")
        self.assertIn("SERIAL_PORT=/dev/ttyUSB1\n", self.section(t, "Rx1") + "\n")
        self.assertIn("SERIAL_PIN=DSR\n", self.section(t, "Rx1") + "\n")
        self.assertIn("PTT_TYPE=SerialPin\n", self.section(t, "Tx1") + "\n")
        self.assertIn("PTT_PORT=/dev/ttyUSB1\n", self.section(t, "Tx1") + "\n")
        self.assertIn("PTT_PIN=RTS\n", self.section(t, "Tx1") + "\n")
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, dict(RADIO_ENV, RTYPE="gpio"))
        self.assertEqual(code, 0, out)
        t = self.read(self.conf)
        for line in ("SQL_DET=GPIOD", "SQL_GPIOD_CHIP=/dev/gpiochip0", "SQL_GPIOD_LINE=22"):
            self.assertIn(line + "\n", self.section(t, "Rx1") + "\n")
        for line in ("PTT_TYPE=GPIOD", "PTT_GPIOD_CHIP=/dev/gpiochip0", "PTT_GPIOD_LINE=17"):
            self.assertIn(line + "\n", self.section(t, "Tx1") + "\n")

    def test_switching_to_bridge_and_back_keeps_the_radio_settings(self):
        self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        radio = self.read(self.conf)
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, WIRE_ENV)
        self.assertEqual(code, 0, out)
        bridge = self.read(self.conf)
        self.assertIn("LOGICS=UsrpLogic\n", bridge)
        self.assertIn("LINKS=\n", bridge)
        self.assertIn("SQL_DET=HIDRAW", bridge)
        self.assertIn("use = bridge", self.read(self.h44conf))
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read(self.conf), radio)
        self.assertTrue(os.path.exists(self.conf + ".44helper-prev"))

    def test_radio_run_twice_changes_nothing(self):
        self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        once = self.read(self.conf)
        code, _out = self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        self.assertEqual(code, 0)
        self.assertEqual(self.read(self.conf), once)

    def test_no_usb_sound_card_or_no_hid_device_stops_without_changes(self):
        before = self.read(self.conf)
        with open(self.cards, "w") as fh:
            fh.write(" 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0\n")
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        self.assertEqual(code, 1)
        self.assertIn("No USB sound card found", out)
        with open(self.cards, "w") as fh:
            fh.write(CARDS_ONE)
        os.remove(self.hid)
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        self.assertEqual(code, 1)
        self.assertIn("No /dev/hidraw device found", out)
        self.assertEqual(self.read(self.conf), before)
        self.assertFalse(os.path.exists(self.conf + ".44helper-bak"))

    def test_an_asterisk_node_on_the_same_usb_device_stops_it(self):
        with open(self.rptconf, "w") as fh:
            fh.write("[652705]\nrxchannel = SimpleUSB/652705\n")
        with open(self.simpleusb, "w") as fh:
            fh.write("[652705]\ndevstr = 1-1.2\n")
        before = self.read(self.conf)
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        self.assertEqual(code, 1, out)
        self.assertIn("uses the same USB device", out)
        self.assertEqual(self.read(self.conf), before)

    def test_an_empty_devstr_stops_it_with_one_usb_card_and_warns_with_two(self):
        with open(self.rptconf, "w") as fh:
            fh.write("[652705]\nrxchannel = SimpleUSB/652705\n")
        with open(self.simpleusb, "w") as fh:
            fh.write("[652705]\ndevstr = \n")
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        self.assertEqual(code, 1, out)
        self.assertIn("takes the only USB sound card", out)
        with open(self.cards, "w") as fh:
            fh.write(CARDS_TWO)
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("Make sure SvxLink uses a different one", out)

    def test_a_node_without_asterisk_radio_nodes_is_never_stopped(self):
        with open(self.rptconf, "w") as fh:
            fh.write("[1999]\nrxchannel = USRP/127.0.0.1:34001:32001\n")
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, RADIO_ENV)
        self.assertEqual(code, 0, out)

    def test_the_radio_can_join_the_reflector_link_and_leave_it(self):
        conf = RADIO_CONF.replace("CONNECT_LOGICS=SimplexLogic:9:TG,ReflectorLogic", "CONNECT_LOGICS=SvxCtrlLogic:9:TG,UsrpLogic,ReflectorLogic")
        with open(self.conf, "w") as fh:
            fh.write(conf)
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, dict(RADIO_ENV, RREFL="yes"))
        self.assertEqual(code, 0, out)
        self.assertIn("CONNECT_LOGICS=SvxCtrlLogic:9:TG,UsrpLogic,ReflectorLogic,SimplexLogic:9:TG",
                      self.section(self.read(self.conf), "ReflectorLink"))
        self.assertIn("The radio joins the reflector link.", out)
        code, out = self.run_script(h44._SVX_USRP_WIRE_PY, dict(RADIO_ENV, RREFL="no"))
        self.assertEqual(code, 0, out)
        self.assertIn("CONNECT_LOGICS=SvxCtrlLogic:9:TG,UsrpLogic,ReflectorLogic\n",
                      self.section(self.read(self.conf), "ReflectorLink") + "\n")

    def test_the_reflector_step_adds_the_radio_when_the_answer_says_so(self):
        with open(self.h44conf, "w") as fh:
            fh.write("[svxlink]\nuse = radio\nradio_reflector = yes\n")
        code, out = self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        self.assertEqual(code, 0, out)
        link = self.section(self.read(self.conf), "ReflectorLink")
        self.assertIn("CONNECT_LOGICS=SvxCtrlLogic:9:TG,UsrpLogic,ReflectorLogic,SimplexLogic:9:TG", link)
        again = self.read(self.conf)
        self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        self.assertEqual(self.read(self.conf), again)

    def test_the_reflector_step_is_unchanged_for_a_bridge(self):
        with open(self.h44conf, "w") as fh:
            fh.write("[svxlink]\nuse = bridge\nradio_reflector = yes\n")
        self.run_script(h44._SVX_REFL_CONN_PY, CONN_ENV)
        self.assertIn("CONNECT_LOGICS=SvxCtrlLogic:9:TG,UsrpLogic,ReflectorLogic\n",
                      self.section(self.read(self.conf), "ReflectorLink") + "\n")


class StepsAndFields(unittest.TestCase):
    def steps(self):
        return {s["id"]: s for s in h44._SVXLINK_SCRIPTS["install"]["usrp"]}

    def test_order(self):
        order = [(s["num"], s["id"]) for s in h44._SVXLINK_SCRIPTS["install"]["usrp"]][8:]
        self.assertEqual(order, [(9, "usrp_service_unit"), (10, "usrp_refl_test"), (11, "usrp_refl_conn"),
                                 (12, "configure_callsign"), (13, "install_cockpit"), (14, "enable_cockpit")])

    def test_fields_are_checked(self):
        st = self.steps()["usrp_refl_conn"]
        good = {"refl_host": "svx.example.org,b.example.org:5301", "refl_port": "5300", "refl_key": "Key-123.x",
                "refl_tg": "240", "refl_monitor": "91,240+,24021++"}
        cmd, why = h44._step_command(st, good)
        self.assertEqual(why, "")
        self.assertIn("HOST='svx.example.org,b.example.org:5301'", cmd)
        for k, bad in (("refl_host", "a b"), ("refl_host", "x;rm"), ("refl_key", "short"), ("refl_key", "has'quote"),
                       ("refl_tg", "2a"), ("refl_monitor", "91,,2"), ("refl_monitor", "9++++"), ("refl_port", "")):
            self.assertNotEqual(h44._step_command(st, dict(good, **{k: bad}))[1], "", (k, bad))
        self.assertEqual(h44._step_command(st, dict(good, refl_monitor=""))[1], "")

    def test_steps_are_not_package_jobs(self):
        for sid in ("usrp_refl_test", "usrp_refl_conn"):
            cmd = self.steps()[sid]["cmd"]
            self.assertFalse(h44._is_apt_mutating(cmd), sid)

    def test_build_deps_include_python3_yaml(self):
        self.assertIn("python3-yaml", h44._SVX_USRP_BUILD_DEPS)

    def test_config_group_covers_the_reflector(self):
        g = h44._CFGR_GROUPS["svx"]
        self.assertIn("/usr/local/etc/svxlink/svxreflector.conf", g["files"])
        self.assertIn("svxreflector", g["services"])


if __name__ == "__main__":
    unittest.main()
