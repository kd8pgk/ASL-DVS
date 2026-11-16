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
               .replace('"/var/lib/svxlink"', repr(self.tmp)))
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
