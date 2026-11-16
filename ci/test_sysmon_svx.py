import glob
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="sysmon_svx_")
os.environ.setdefault("SYSMON_CONFIG_DIR", os.path.join(WORK, "cfg"))


def load():
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    path = sorted(glob.glob(os.path.join(ROOT, "sysmon_v[0-9]*.py")), key=key)[-1]
    spec = importlib.util.spec_from_file_location("svx_sm", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["svx_sm"] = mod
    spec.loader.exec_module(mod)
    return mod


SM = load()

BASE = """[GLOBAL]
LOGICS=SimplexLogic,UsrpLogic
LINKS=LinkToUsrp
CFG_DIR=svxlink.d

[SimplexLogic]
CALLSIGN=KD8PGK

[UsrpLogic]
CALLSIGN=KD8PGK
USRP_HOST=127.0.0.1
USRP_TX_PORT=32000
USRP_RX_PORT=34000

[LinkToUsrp]
CONNECT_LOGICS=SimplexLogic:9:USRP,UsrpLogic
DEFAULT_ACTIVE=1
"""

RPT = """[1900]
rxchannel=USRP/127.0.0.1:34000:32000 ; svx
[1999]
rxchannel=USRP/127.0.0.1:34001:32001

[nodes]
1900 = radio@127.0.0.1/1900,NONE
"""

EXT = "[radio]\nexten => 1900,1,Rpt(1900)\n"


class FakeHandler:
    def __init__(self):
        self.sent = None
        self.code = 200

    def send_json(self, obj, code=200):
        self.sent = obj
        self.code = code


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="svx_etc_", dir=WORK))
        (self.dir / "svxlink.d").mkdir()
        (self.dir / "svxlink.conf").write_text(BASE)
        (self.dir / "svxlink.d" / "UsrpLogic.conf").write_text("[UsrpLogic]\nUSRP_RX_PORT=34000\nUSRP_TX_PORT=32000\n")
        (self.dir / "node_info.json").write_text("{}\n")
        (self.dir / "notes.txt").write_text("x")
        self.p = [mock.patch.object(SM, "_SVX_ETC", self.dir),
                  mock.patch.object(SM, "_SVX_CONF", self.dir / "svxlink.conf"),
                  mock.patch.object(SM, "_SVX_PTY", self.dir / "dtmf_ctrl"),
                  mock.patch.object(SM, "_SVX_LOG", self.dir / "log")]
        for x in self.p:
            x.start()
        self.addCleanup(lambda: [x.stop() for x in self.p])
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def conf(self):
        return (self.dir / "svxlink.conf").read_text()


class Validate(Base):
    def test_clean_file_passes(self):
        self.assertEqual(SM._svx_validate("svxlink.conf", BASE), [])

    def test_inline_comment_is_refused(self):
        bad = BASE.replace("CALLSIGN=KD8PGK\n\n[Usrp", "CALLSIGN=KD8PGK # mine\n\n[Usrp", 1)
        out = SM._svx_validate("svxlink.conf", bad)
        self.assertTrue(any("comment after the value" in x for x in out), out)

    def test_hash_inside_quotes_is_fine(self):
        self.assertEqual(SM._svx_validate("svxlink.conf", BASE + 'AUTH_KEY="a #b"\n'), [])

    def test_numeric_macro_keys_and_device_ports_are_fine(self):
        extra = "\n[Macros]\n1=EchoLink:9999#\n03400=EchoLink:9999#\n\n[Rx1]\nSERIAL_PORT=/dev/ttyUSB0\nPTT_PORT=/dev/ttyS0\n"
        self.assertEqual(SM._svx_validate("svxlink.conf", BASE + extra), [])

    def test_hash_inside_a_word_is_fine(self):
        self.assertEqual(SM._svx_validate("svxlink.conf", BASE + "AUTH_KEY=ab#cd\n"), [])

    def test_missing_logic_section(self):
        out = SM._svx_validate("svxlink.conf", BASE.replace("LINKS=LinkToUsrp", "LINKS=LinkToUsrp,Gone"))
        self.assertTrue(any("[Gone]" in x for x in out), out)

    def test_missing_logic_from_logics(self):
        out = SM._svx_validate("svxlink.conf", BASE.replace("UsrpLogic\nLINKS", "UsrpLogic,Nope\nLINKS"))
        self.assertTrue(any("[Nope]" in x for x in out), out)

    def test_port_must_be_numeric(self):
        out = SM._svx_validate("svxlink.conf", BASE.replace("USRP_TX_PORT=32000", "USRP_TX_PORT=abc"))
        self.assertTrue(any("USRP_TX_PORT must be a number" in x for x in out), out)

    def test_bad_json(self):
        self.assertTrue(SM._svx_validate("node_info.json", "{nope"))
        self.assertEqual(SM._svx_validate("node_info.json", '{"a": 1}'), [])

    def test_empty_crlf_and_junk(self):
        self.assertTrue(SM._svx_validate("svxlink.conf", "  \n"))
        self.assertTrue(SM._svx_validate("svxlink.conf", BASE.replace("\n", "\r\n")))
        self.assertTrue(SM._svx_validate("svxlink.conf", BASE + "what is this\n"))
        self.assertTrue(SM._svx_validate("svxlink.conf", BASE + "[Broken\n"))

    def test_no_global(self):
        self.assertTrue(SM._svx_validate("svxlink.conf", "[Other]\nA=1\n"))


class Files(Base):
    def test_listing_and_path_rules(self):
        self.assertEqual(SM._svx_files(), ["node_info.json", "svxlink.conf", "svxlink.d/UsrpLogic.conf"])
        self.assertEqual(SM._svx_path("svxlink.conf"), self.dir / "svxlink.conf")
        for bad in ("../etc/passwd", "svxlink.d/../svxlink.conf", "/etc/passwd", "notes.txt", "", "nope.conf", None, 5):
            self.assertIsNone(SM._svx_path(bad), bad)

    def test_save_keeps_previous_and_restore_swaps(self):
        path = self.dir / "svxlink.conf"
        SM._svx_swap_write(path, BASE + "# one\n")
        bak = self.dir / "svxlink.conf.sysmon-bak"
        self.assertEqual(bak.read_text(), BASE)
        ok, _ = SM._svx_restore(path)
        self.assertTrue(ok)
        self.assertEqual(path.read_text(), BASE)
        self.assertEqual(bak.read_text(), BASE + "# one\n")
        ok, _ = SM._svx_restore(path)
        self.assertEqual(path.read_text(), BASE + "# one\n")

    def test_restore_without_backup(self):
        ok, msg = SM._svx_restore(self.dir / "svxlink.conf")
        self.assertFalse(ok)
        self.assertIn("no earlier version", msg)


class Connect(Base):
    ARGS = ("refl.example.net", "5300", "secret1", "240", "91,240+")

    def test_adds_the_reflector_sections_and_lists(self):
        new, call = SM._svx_connect_text(BASE, *self.ARGS)
        self.assertEqual(call, "KD8PGK")
        secs = SM._svx_parse(new)
        r = secs["ReflectorLogic"]
        self.assertEqual((r["HOSTS"], r["HOST_PORT"], r["CALLSIGN"], r["AUTH_KEY"], r["DEFAULT_TG"], r["MONITOR_TGS"]),
                         ("refl.example.net", "5300", "KD8PGK", "secret1", "240", "91,240+"))
        self.assertEqual(r["TG_SELECT_TIMEOUT"], "3600")
        self.assertEqual(secs["SvxCtrlLogic"]["DTMF_CTRL_PTY"], str(self.dir / "dtmf_ctrl"))
        self.assertEqual(secs["ReflectorLink"]["CONNECT_LOGICS"], "SvxCtrlLogic:9:TG,UsrpLogic,ReflectorLogic")
        self.assertEqual(secs["GLOBAL"]["LOGICS"], "SimplexLogic,UsrpLogic,ReflectorLogic,SvxCtrlLogic")
        self.assertEqual(secs["GLOBAL"]["LINKS"], "LinkToUsrp,ReflectorLink")
        self.assertEqual(SM._svx_validate("svxlink.conf", new), [])

    def test_running_again_changes_nothing(self):
        once, _ = SM._svx_connect_text(BASE, *self.ARGS)
        twice, _ = SM._svx_connect_text(once, *self.ARGS)
        self.assertEqual(once, twice)

    def test_changing_the_reflector_replaces_values(self):
        once, _ = SM._svx_connect_text(BASE, *self.ARGS)
        again, _ = SM._svx_connect_text(once, "127.0.0.1", "5301", "other", "0", "")
        r = SM._svx_parse(again)["ReflectorLogic"]
        self.assertEqual((r["HOSTS"], r["HOST_PORT"], r["AUTH_KEY"], r["DEFAULT_TG"]), ("127.0.0.1", "5301", "other", "0"))
        self.assertNotIn("MONITOR_TGS", r)
        self.assertEqual(again.count("[ReflectorLogic]"), 1)

    def test_no_callsign_stops(self):
        with self.assertRaises(ValueError):
            SM._svx_connect_text(BASE.replace("KD8PGK", "MYCALL"), *self.ARGS)

    def test_argument_checks(self):
        good = {"host": "refl.example.net", "port": "5300", "key": "k", "tg": "240", "monitor": "91,240+"}
        args, bad = SM._svx_connect_args(good, "")
        self.assertEqual((bad, args), ("", ("refl.example.net", "5300", "k", "240", "91,240+")))
        for field, value in (("host", "a b"), ("host", "x;rm"), ("port", "0"), ("port", "70000"), ("port", "x"),
                             ("key", 'a"b'), ("key", "a#b"), ("key", "a\nb"), ("tg", "x"), ("tg", "123456789"),
                             ("monitor", "91;2"), ("monitor", "+9")):
            args, bad = SM._svx_connect_args({**good, field: value}, "")
            self.assertTrue(bad, (field, value))

    def test_blank_password_keeps_the_current_one(self):
        args, bad = SM._svx_connect_args({"host": "h", "port": "1", "key": ""}, "kept")
        self.assertEqual((bad, args[2]), ("", "kept"))
        args, bad = SM._svx_connect_args({"host": "h", "port": "1", "key": ""}, "")
        self.assertIn("password", bad)


class Routes(Base):
    def post(self, data, root=True):
        h = FakeHandler()
        with mock.patch.object(SM.os, "geteuid", return_value=0 if root else 1000):
            SM._route_svx_post(h, data)
        return h

    def test_needs_root(self):
        self.assertFalse(self.post({"action": "read", "label": "svxlink.conf"}, root=False).sent["ok"])

    def test_read_save_restore(self):
        h = self.post({"action": "read", "label": "svxlink.conf"})
        self.assertTrue(h.sent["ok"])
        self.assertFalse(h.sent["has_backup"])
        h = self.post({"action": "save", "label": "svxlink.conf", "content": BASE.replace("KD8PGK", "W8ABC")})
        self.assertTrue(h.sent["ok"], h.sent)
        self.assertIn("W8ABC", self.conf())
        self.assertTrue(self.post({"action": "read", "label": "svxlink.conf"}).sent["has_backup"])
        self.assertTrue(self.post({"action": "restore", "label": "svxlink.conf"}).sent["ok"])
        self.assertIn("KD8PGK", self.conf())

    def test_save_refuses_a_bad_file_and_leaves_it(self):
        h = self.post({"action": "save", "label": "svxlink.conf", "content": BASE + "X=1 # no\n"})
        self.assertFalse(h.sent["ok"])
        self.assertEqual(h.code, 400)
        self.assertEqual(self.conf(), BASE)

    def test_unknown_file_and_action(self):
        self.assertEqual(self.post({"action": "read", "label": "../x"}).code, 400)
        self.assertEqual(self.post({"action": "nope"}).code, 400)

    def test_connect_writes_restarts_and_keeps_the_first_copy(self):
        ran = []
        with mock.patch.object(SM, "_run", side_effect=lambda cmd, timeout=5: ran.append(cmd) or ""):
            h = self.post({"action": "connect", "host": "127.0.0.1", "port": "5300", "key": "pw1", "tg": "0", "monitor": ""})
        self.assertTrue(h.sent["ok"], h.sent)
        self.assertEqual(SM._svx_parse(self.conf())["ReflectorLogic"]["AUTH_KEY"], "pw1")
        self.assertEqual((self.dir / "svxlink.conf.44helper-bak").read_text(), BASE)
        self.assertIn(["systemctl", "restart", "svxlink-usrp"], ran)

    def test_connect_with_a_bad_value_changes_nothing(self):
        h = self.post({"action": "connect", "host": "bad host", "port": "5300", "key": "pw1"})
        self.assertEqual(h.code, 400)
        self.assertEqual(self.conf(), BASE)

    def test_connect_keeps_the_stored_password_when_blank(self):
        with mock.patch.object(SM, "_run", return_value=""):
            self.post({"action": "connect", "host": "h.example", "port": "5300", "key": "first"})
            h = self.post({"action": "connect", "host": "h2.example", "port": "5300", "key": ""})
        self.assertTrue(h.sent["ok"], h.sent)
        r = SM._svx_parse(self.conf())["ReflectorLogic"]
        self.assertEqual((r["HOSTS"], r["AUTH_KEY"]), ("h2.example", "first"))


class Checks(Base):
    def run_checks(self, conf=None, log="", rpt=RPT, ext=EXT, reach=True, local="1900\n1999", ss="", ufw="", bind="4569",
                   unit="active", installed=True):
        if conf is not None:
            (self.dir / "svxlink.conf").write_text(conf)
        (self.dir / "log").write_text(log)
        rpt_path = self.dir / "rpt.conf"
        rpt_path.write_text(rpt)

        real = SM.read_path_file

        def fake_read(p):
            if str(p) == "/etc/asterisk/extensions.conf":
                return ext, None
            if str(p) == "/etc/asterisk/iax.conf":
                return f"[general]\nbindport={bind}\n", None
            return real(p)

        def fake_run(cmd, timeout=5):
            if cmd[:2] == ["asterisk", "-rx"]:
                return local
            if cmd[:2] == ["ss", "-ulnH"]:
                return ss
            if cmd[:2] == ["ufw", "status"]:
                return ufw
            return ""

        exists = mock.patch.object(Path, "exists", autospec=True,
                                   side_effect=lambda self_: True if str(self_) == str(SM._SVX_BIN) and installed
                                   else (False if str(self_) == str(SM._SVX_BIN) else os.path.lexists(self_)))
        conn = mock.MagicMock()
        sock = mock.patch.object(SM._socket, "create_connection",
                                 side_effect=(lambda *a, **k: conn) if reach else OSError("refused"))
        with mock.patch.object(SM, "_RPT_CONF", rpt_path), mock.patch.object(SM, "read_path_file", fake_read), \
                mock.patch.object(SM, "_run", fake_run), mock.patch.object(SM, "get_service_state", return_value=unit), \
                mock.patch.object(SM.shutil, "which", return_value="/usr/bin/x"), exists, sock:
            return SM._svx_checks()

    def row(self, res, enables):
        for r in res["rows"]:
            if r["enables"] == enables:
                return r
        self.fail(f"no row {enables}: {[r['enables'] for r in res['rows']]}")

    def test_not_installed(self):
        res = self.run_checks(installed=False)
        self.assertFalse(res["installed"])
        self.assertEqual(res["rows"][0]["status"], "fail")

    def test_clean_node_without_reflector(self):
        res = self.run_checks()
        self.assertEqual(self.row(res, "SvxLink service running")["status"], "pass")
        self.assertEqual(self.row(res, "Config reads cleanly")["status"], "pass")
        self.assertEqual(self.row(res, "Reflector settings")["status"], "info")
        self.assertEqual(self.row(res, "USRP ports mirror rpt.conf")["status"], "pass")
        self.assertEqual(self.row(res, "Bridge node loaded in Asterisk")["status"], "pass")
        self.assertEqual(self.row(res, "Dialplan line for the bridge")["status"], "pass")
        self.assertEqual(self.row(res, "Node line has a host and port")["status"], "pass")
        self.assertEqual(self.row(res, "Bridge ports closed to the network")["status"], "pass")

    def test_service_stopped(self):
        self.assertEqual(self.row(self.run_checks(unit="inactive"), "SvxLink service running")["status"], "fail")

    def test_connected_reflector_and_login(self):
        conf, _ = SM._svx_connect_text(BASE, "refl.example.net", "5300", "pw", "240", "")
        res = self.run_checks(conf=conf, log="ReflectorLogic: Authentication OK\nReflectorLogic: Selecting TG #240\n"
                                             "Activating link 'ReflectorLink'\n")
        self.assertEqual(self.row(res, "Reflector settings")["status"], "pass")
        self.assertEqual(self.row(res, "Reflector reachable")["status"], "pass")
        self.assertEqual(self.row(res, "Logged in to the reflector")["status"], "pass")
        tg = self.row(res, "Talkgroup now selected")
        self.assertEqual((tg["status"], tg["key"], tg["fix"]), ("info", "TG 240", "The reflector link is on."))

    def test_unreachable_and_login_failure(self):
        conf, _ = SM._svx_connect_text(BASE, "refl.example.net", "5300", "pw", "0", "")
        res = self.run_checks(conf=conf, reach=False,
                              log="ReflectorLogic: Authentication OK\nReflectorLogic: Disconnected from refl.example.net:5300\n")
        self.assertEqual(self.row(res, "Reflector reachable")["status"], "fail")
        self.assertEqual(self.row(res, "Logged in to the reflector")["status"], "fail")

    def test_no_login_line_is_a_warning(self):
        conf, _ = SM._svx_connect_text(BASE, "refl.example.net", "5300", "pw", "0", "")
        self.assertEqual(self.row(self.run_checks(conf=conf), "Logged in to the reflector")["status"], "warn")

    def test_missing_reflector_fields(self):
        conf = BASE + "\n[ReflectorLogic]\nHOSTS=h\n"
        r = self.row(self.run_checks(conf=conf), "Reflector settings")
        self.assertEqual(r["status"], "fail")
        self.assertIn("AUTH_KEY", r["fix"])

    def test_usrp_ports_not_in_rpt(self):
        res = self.run_checks(rpt=RPT.replace("34000:32000", "34005:32005"))
        self.assertEqual(self.row(res, "USRP ports mirror rpt.conf")["status"], "fail")
        self.assertNotIn("Bridge node loaded in Asterisk", [r["enables"] for r in res["rows"]])

    def test_bridge_node_not_loaded(self):
        self.assertEqual(self.row(self.run_checks(local="1999"), "Bridge node loaded in Asterisk")["status"], "fail")

    def test_dialplan_forms(self):
        old = self.row(self.run_checks(ext="exten => 1900,1,rpt,1900\n"), "Dialplan line for the bridge")
        self.assertEqual(old["status"], "fail")
        self.assertIn("Rpt(1900)", old["fix"])
        self.assertEqual(self.row(self.run_checks(ext="[radio]\n"), "Dialplan line for the bridge")["status"], "fail")

    def test_nodes_line(self):
        bad = self.row(self.run_checks(rpt=RPT.replace("radio@127.0.0.1/1900", "1900,NONE")), "Node line has a host and port")
        self.assertEqual(bad["status"], "fail")
        port = self.row(self.run_checks(bind="4570"), "Node line has a host and port")
        self.assertEqual(port["status"], "fail")
        self.assertIn("4570", port["fix"])
        ok = self.row(self.run_checks(bind="4570", rpt=RPT.replace("127.0.0.1/1900", "127.0.0.1:4570/1900")),
                      "Node line has a host and port")
        self.assertEqual(ok["status"], "pass")

    def test_firewall_rows(self):
        self.assertEqual(self.row(self.run_checks(ufw="34000/udp                 ALLOW       Anywhere\n"),
                                  "Bridge ports closed to the network")["status"], "fail")
        self.assertEqual(self.row(self.run_checks(ss="UNCONN 0 0 0.0.0.0:34000 0.0.0.0:*\n"),
                                  "Bridge ports closed to the network")["status"], "warn")
        self.assertEqual(self.row(self.run_checks(ss="UNCONN 0 0 127.0.0.1:34000 0.0.0.0:*\n"),
                                  "Bridge ports closed to the network")["status"], "pass")

    def test_control_device(self):
        conf, _ = SM._svx_connect_text(BASE, "r.example", "5300", "pw", "0", "")
        self.assertEqual(self.row(self.run_checks(conf=conf), "Control device for Node Controller")["status"], "warn")
        (self.dir / "dtmf_ctrl").write_text("")
        self.assertEqual(self.row(self.run_checks(conf=conf), "Control device for Node Controller")["status"], "pass")

    def test_log_health_counts_warnings(self):
        r = self.row(self.run_checks(log="x\n*** WARNING: a\nok\n*** ERROR: b\n"), "Warnings in the SvxLink log")
        self.assertEqual((r["status"], r["key"]), ("info", "2 in the last 200 lines"))

    def test_payload_counts_and_secret(self):
        conf, _ = SM._svx_connect_text(BASE, "r.example", "5300", "topsecret", "0", "")
        (self.dir / "svxlink.conf").write_text(conf)
        with mock.patch.object(SM, "_svx_checks", return_value=self.run_checks(conf=conf)):
            d = SM._build_svx_payload()
        self.assertTrue(d["ok"])
        self.assertTrue(d["reflector"]["key_set"])
        self.assertNotIn("topsecret", json.dumps(d))
        self.assertEqual(sum(d["count"].values()), len(d["checks"]))


class TabLists(unittest.TestCase):
    def test_svx_is_a_tab_and_the_old_list_gains_it_once(self):
        self.assertIn("svx", SM._ALL_TABS)
        with mock.patch.object(SM._cfg, "get", side_effect=lambda sec, key, fallback="": "overview,stfu,edit" if key == "enabled_tabs" else fallback):
            self.assertIn("svx", SM._get_enabled_tabs())
        with mock.patch.object(SM._cfg, "get", side_effect=lambda sec, key, fallback="": {"enabled_tabs": "overview,stfu,edit", "svx_tab": "1"}.get(key, fallback)):
            self.assertNotIn("svx", SM._get_enabled_tabs())

    def test_route_tables(self):
        src = Path(SM.__file__).read_text()
        self.assertIn('"/api/svx":                _route_svx_get', src)
        self.assertIn('"/api/svx":             _route_svx_post', src)


if __name__ == "__main__":
    unittest.main()
