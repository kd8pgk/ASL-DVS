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


spec = importlib.util.spec_from_file_location("h44_magic_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_magic_under_test"] = h44
spec.loader.exec_module(h44)

SECRET = "TopSecretReflectorKey123"
CONF = f"""[GLOBAL]
LOGICS=UsrpLogic,ReflectorLogic
LINKS=ReflectorLink

[UsrpLogic]
TYPE=Usrp
USRP_HOST=127.0.0.1
USRP_RX_PORT=34000
USRP_TX_PORT=32000

[ReflectorLogic]
TYPE=Reflector
HOSTS=north.america.svxlink.net
HOST_PORT=35300
CALLSIGN="KD8PGK"
AUTH_KEY="{SECRET}"

[ReflectorLink]
CONNECT_LOGICS=UsrpLogic:9:0,ReflectorLogic
"""
RADIO_CONF = """[GLOBAL]
LOGICS=SimplexLogic,UsrpLogic
LINKS=LinkToUsrp

[SimplexLogic]
TYPE=Simplex
RX=Rx1
TX=Tx1

[Rx1]
TYPE=Local

[UsrpLogic]
TYPE=Usrp
"""
GOOD = {"mode": "half", "callsign": "KD8PGK", "node": "652701", "dmr_id": "3123456", "nxdn_id": "12345",
        "m17_node": "1917", "usb": "", "bypass": "", "svx_use": "bridge", "svx_host": "", "svx_port": "",
        "svx_tg": "0", "svx_mon": ""}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.p = lambda n: os.path.join(self.d.name, n)

    def write(self, name, text):
        path = self.p(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path


class Stages(unittest.TestCase):
    def ids(self, mode, profile="magic"):
        return [i for i, _ in h44._bld_stage_defs(mode, profile)]

    def test_travel_is_unchanged(self):
        self.assertNotIn("svx", self.ids("half", "travel"))
        self.assertEqual(self.ids("half", "travel"), [i for i, _ in h44._bld_stage_defs("half")])

    def test_magic_adds_svx_after_m17_in_every_mode(self):
        for m in ("half", "split", "full"):
            ids = self.ids(m)
            self.assertEqual(ids[ids.index("m17") + 1:ids.index("m17") + 4], ["svx", "svx_wire", "svx_reflector"], m)
            self.assertLess(ids.index("wiring"), ids.index("svx_checks"))
            self.assertLess(ids.index("svx_checks"), ids.index("radio"))

    def test_magic_keeps_the_tunnel_rules(self):
        self.assertLess(self.ids("half").index("tunnel"), self.ids("half").index("asl3"))
        self.assertGreater(self.ids("full").index("tunnel"), self.ids("full").index("svx_reflector"))
        self.assertIn("half", self.ids("half"))
        self.assertNotIn("half", self.ids("split"))


class Errors(unittest.TestCase):
    def errs(self, profile="magic", **kw):
        return h44._bld_form_errors(dict(GOOD, **kw), [], profile)

    def test_good_and_empty_reflector_are_fine(self):
        self.assertEqual(self.errs(), {})

    def test_svx_fields_ignored_by_travel(self):
        self.assertEqual(self.errs("travel", svx_host="bad host!", svx_port="x"), {})

    def test_reflector_pairs(self):
        self.assertEqual(self.errs(svx_host="north.america.svxlink.net", svx_port="35300"), {})
        self.assertIn("svx_port", self.errs(svx_host="example.org"))
        self.assertIn("svx_host", self.errs(svx_port="5300"))

    def test_bad_values(self):
        self.assertIn("svx_host", self.errs(svx_host="bad_host", svx_port="5300"))
        self.assertIn("svx_host", self.errs(svx_host="999.1.1.1", svx_port="5300"))
        self.assertIn("svx_port", self.errs(svx_host="example.org", svx_port="70000"))
        self.assertIn("svx_tg", self.errs(svx_tg="12a"))
        self.assertIn("svx_mon", self.errs(svx_mon="240,,+9"))
        self.assertEqual(self.errs(svx_mon="240,+91, 9"), {})

    def test_clean_normalises_use(self):
        self.assertEqual(h44._bld_form_clean({"svx_use": "evil"})["svx_use"], "bridge")
        self.assertEqual(h44._bld_form_clean({"svx_use": "radio"})["svx_use"], "radio")

    def test_no_password_field(self):
        for k in h44._BLD_FIELDS:
            self.assertNotRegex(k.replace("bypass", ""), r"pass|key|secret|token")


class Parsing(unittest.TestCase):
    def test_sections_and_quotes(self):
        sec = h44._bld_svx_parse(CONF)
        self.assertEqual(sec["ReflectorLogic"]["CALLSIGN"], "KD8PGK")
        self.assertEqual(sec["GLOBAL"]["LOGICS"], "UsrpLogic,ReflectorLogic")

    def test_radio_logic_found_only_with_a_real_receiver(self):
        self.assertEqual(h44._bld_svx_radio_logics(h44._bld_svx_parse(RADIO_CONF)), ["SimplexLogic"])
        self.assertEqual(h44._bld_svx_radio_logics(h44._bld_svx_parse(RADIO_CONF.replace("Rx1]\nTYPE=Local", "Rx1]\nTYPE=Dummy"))), [])
        self.assertEqual(h44._bld_svx_radio_logics(h44._bld_svx_parse(CONF)), [])

    def test_port_in(self):
        self.assertTrue(h44._bld_port_in(["34000/udp"], 34000, "udp"))
        self.assertTrue(h44._bld_port_in(["33000-35000/udp"], 34000, "udp"))
        self.assertFalse(h44._bld_port_in(["34000/tcp"], 34000, "udp"))
        self.assertFalse(h44._bld_port_in([], 34000, "udp"))


class Gather(Tmp):
    def gather(self, conf, form=None, active=True, pair=None, ext=True, nodes=True, log="connected", use=""):
        self.write("svxlink.conf", conf)
        self.write("extensions.conf", "exten => 1900,1,Rpt(1900)\n" if ext else "exten => 1900,1,rpt,1900\n")
        self.write("rpt.conf", "1900 = radio@127.0.0.1/1900,NONE\n" if nodes else "")
        pair = pair or {"node": "1900", "bridge": "SvxLink", "state": "ok"}
        with mock.patch.multiple(h44, _BLD_SVX_CONF=self.p("svxlink.conf"), _BLD_EXT=self.p("extensions.conf"),
                                 _BLD_RPT=self.p("rpt.conf")), \
                mock.patch.object(h44, "_ov_q", lambda a, t=6: (0 if active else 3, "")), \
                mock.patch.object(h44, "_cfgr_usrp_scan", lambda override=None: {"pairs": [pair], "unpaired": []}), \
                mock.patch.object(h44, "_bld_svx_log_state", lambda: log), \
                mock.patch.object(h44, "_bld_svx_use", lambda: use):
            return h44._bld_svx_gather(form or GOOD, True, [])

    def stage(self, sid, g, form=None, radio=None):
        return h44._bld_svx_stage(sid, g, form or GOOD, radio or {})

    def test_reflector_read_without_the_key(self):
        g = self.gather(CONF)
        self.assertEqual(g["reflector"], {"host": "north.america.svxlink.net", "port": "35300", "callsign": "KD8PGK", "key_set": True})
        self.assertNotIn(SECRET, json.dumps(g))

    def test_not_installed(self):
        g = dict(self.gather(CONF), installed=False)
        self.assertEqual(self.stage("svx", g)[0], "todo")
        self.assertEqual(self.stage("svx_wire", g)[0], "todo")

    def test_svx_installed_notes_the_service(self):
        self.assertIn("running", self.stage("svx", self.gather(CONF))[1])
        self.assertIn("not running", self.stage("svx", self.gather(CONF, active=False))[1])

    def test_wire_done_for_a_bridge(self):
        self.assertEqual(self.stage("svx_wire", self.gather(CONF))[0], "done")

    def test_wire_flags_radio_logic_under_a_bridge(self):
        st, why = self.stage("svx_wire", self.gather(RADIO_CONF))
        self.assertEqual(st, "todo")
        self.assertIn("SimplexLogic", why)

    def test_wire_allows_radio_logic_when_radio_is_chosen(self):
        st, _ = self.stage("svx_wire", self.gather(RADIO_CONF), dict(GOOD, svx_use="radio"))
        self.assertEqual(st, "done")

    def test_wire_radio_and_simpleusb_clash(self):
        st, why = self.stage("svx_wire", self.gather(RADIO_CONF), dict(GOOD, svx_use="radio"), {"simpleusb_stanza": True})
        self.assertEqual(st, "todo")
        self.assertIn("SimpleUSB", why)

    def test_wire_saved_answer_disagrees(self):
        st, why = self.stage("svx_wire", self.gather(CONF, use="radio"))
        self.assertEqual(st, "todo")
        self.assertIn("step 8", why)

    def test_wire_pair_and_dialplan_problems(self):
        st, why = self.stage("svx_wire", self.gather(CONF, pair={"node": "1900", "bridge": "SvxLink", "state": "mismatch"}))
        self.assertIn("does not match", why)
        st, why = self.stage("svx_wire", self.gather(CONF, ext=False, nodes=False))
        self.assertIn("exten", why)
        self.assertIn("[nodes]", why)
        st, why = self.stage("svx_wire", self.gather(CONF, pair={"node": "1901", "bridge": "SvxLink", "state": "ok"}))
        self.assertIn("1901", why)

    def test_reflector_stage(self):
        self.assertEqual(self.stage("svx_reflector", self.gather(CONF))[0], "done")
        self.assertEqual(self.stage("svx_reflector", self.gather(CONF.replace("north.america.svxlink.net", "")))[0], "warn")
        self.assertEqual(self.stage("svx_reflector", self.gather(CONF.replace("north.america.svxlink.net", "")),
                                    dict(GOOD, svx_host="x.example.org", svx_port="5300"))[0], "todo")
        st, why = self.stage("svx_reflector", self.gather(CONF.replace(f'AUTH_KEY="{SECRET}"', 'AUTH_KEY=""')))
        self.assertEqual(st, "todo")
        self.assertIn("password", why)
        st, why = self.stage("svx_reflector", self.gather(CONF), dict(GOOD, svx_host="other.example.org", svx_port="35300"))
        self.assertEqual(st, "todo")
        self.assertIn("other.example.org", why)
        self.assertEqual(self.stage("svx_reflector", self.gather(CONF), dict(GOOD, callsign="W1AW"))[0], "warn")

    def test_checks_stage(self):
        ok = self.gather(CONF)
        ok["reachable"] = True
        self.assertEqual(self.stage("svx_checks", ok)[0], "done")
        self.assertEqual(self.stage("svx_checks", self.gather(CONF, active=False))[0], "todo")
        self.assertEqual(self.stage("svx_checks", self.gather(CONF, log=""))[0], "warn")
        self.assertEqual(self.stage("svx_checks", self.gather(CONF, log="down"))[0], "warn")
        bad = self.gather(CONF.replace("TYPE=Usrp", "TYPE=Usrp # note"))
        self.assertEqual(self.stage("svx_checks", bad)[0], "todo")
        miss = self.gather(CONF.replace("LINKS=ReflectorLink", "LINKS=Nope"))
        self.assertEqual(self.stage("svx_checks", miss)[0], "todo")
        opened = self.gather(CONF)
        opened["udp_open"] = True
        self.assertEqual(self.stage("svx_checks", opened)[0], "warn")
        unreachable = self.gather(CONF)
        unreachable["reachable"] = False
        self.assertEqual(self.stage("svx_checks", unreachable)[0], "warn")


class Page(unittest.TestCase):
    def ids(self, html):
        return set(re.findall(r'id="([^"]+)"', html))

    def test_both_tabs_registered(self):
        tabs = {t[0]: t[1] for t in h44.TABS}
        self.assertEqual((tabs["build"], tabs["magic"]), ("Travel Node", "Magic Box"))
        self.assertIn("magic", h44._PANEL_RENDERERS)

    def test_panels_share_no_ids(self):
        a, b = self.ids(h44._render_build_panel()), self.ids(h44._render_magic_panel())
        self.assertEqual(a & b, set())

    def test_magic_panel_has_the_svx_rows_and_the_note(self):
        html = h44._render_magic_panel()
        for k in ("svx_use", "svx_host", "svx_port", "svx_tg", "svx_mon"):
            self.assertIn(f'id="mbx-{k}"', html)
        self.assertIn("Magic Box is made for the full build", html)
        self.assertIn("fewer functions", html)
        self.assertIn("your choice", html)
        self.assertNotIn("either build", html)
        self.assertIn('id="panel-magic"', html)
        self.assertIn('id="mbx-svx"', html)

    def test_pi02w_is_never_blocked(self):
        self.assertIn("Nothing is blocked", h44._JS_MAGIC)
        for mode in ("half", "split", "full"):
            self.assertEqual([i for i, _ in h44._bld_stage_defs(mode, "magic")].count("svx"), 1)

    def test_travel_panel_has_no_svx_rows(self):
        html = h44._render_build_panel()
        self.assertNotIn("svx_host", html)
        self.assertIn("Travel Node runs on either build", html)

    def test_no_template_tokens_left(self):
        for text in (h44._render_build_panel(), h44._render_magic_panel(), h44._JS_BUILD, h44._JS_MAGIC):
            self.assertNotRegex(text, r"@(P|F|TAB|PROFILE|FIELDS|NOTE|TITLE|SVXROWS|SVXCARD)@")

    def test_js_uses_each_tabs_own_ids_and_profile(self):
        self.assertIn("profile=magic", h44._JS_MAGIC)
        self.assertIn("profile=travel", h44._JS_BUILD)
        self.assertIn("mbx-", h44._JS_MAGIC)
        self.assertNotIn("bld-", h44._JS_MAGIC)
        self.assertIn("magicRefresh", h44._JS_MAGIC)
        self.assertIn("svx_host", h44._JS_MAGIC)
        self.assertNotIn("svx_host", h44._JS_BUILD)

    def test_every_js_id_exists_in_its_panel(self):
        for js, html in ((h44._JS_BUILD, h44._render_build_panel()), (h44._JS_MAGIC, h44._render_magic_panel())):
            ids = self.ids(html)
            pfx = "mbx" if "mbx-" in js else "bld"
            for m in re.finditer(r"getElementById\('(" + pfx + r"-[a-z_0-9-]+)'\)", js):
                if m.group(1) == pfx + "-svx" and pfx == "bld":
                    continue
                self.assertIn(m.group(1), ids, m.group(1))


class Status(Tmp):
    def test_magic_status_has_svx_and_no_secret(self):
        self.write("build.json", json.dumps(dict(GOOD, mode="full", svx_host="north.america.svxlink.net", svx_port="35300")))
        self.write("svxlink.conf", CONF)
        prods = [{"key": "svx", "state": "installed"}]
        with mock.patch.multiple(h44, _BLD_FILE=self.p("build.json"), _BLD_SVX_CONF=self.p("svxlink.conf"),
                                 _BLD_RPT=self.p("rpt.conf"), _BLD_SAVENODE=self.p("sn"), _BLD_SIMPLEUSB=self.p("su"),
                                 _BLD_MMDVM=self.p("m"), _BLD_M17INI=self.p("u"), _BLD_NODETALKER=self.p("nt"),
                                 _BLD_EXT=self.p("e"), WG0_CONF_PATH=self.p("wg")), \
                mock.patch.object(h44, "_bld_usb_cards", lambda: []), \
                mock.patch.object(h44, "_bld_machine", lambda: [{"key": "os", "label": "OS", "level": "ok", "detail": ""}]), \
                mock.patch.object(h44, "_detect_installed_products", lambda force=False: prods), \
                mock.patch.object(h44, "_wg0_interface_present", lambda: False), \
                mock.patch.object(h44, "_firewalld_zone_info_cached", lambda: None), \
                mock.patch.object(h44, "status_boot_order", lambda: {"done": False, "missing": ["x"]}), \
                mock.patch.object(h44, "_cfgr_usrp_pairs", lambda override=None: ([], [])), \
                mock.patch.object(h44, "_cfgr_usrp_scan", lambda override=None: {"pairs": [], "unpaired": []}), \
                mock.patch.object(h44, "_pn_status", lambda: {"available": False}), \
                mock.patch.object(h44, "_cfgr_snap_dir", lambda k, sid="": "x"), \
                mock.patch.object(h44, "_cfgr_read_manifest", lambda d: None), \
                mock.patch.object(h44, "_cfgr_load_preset", lambda p: None), \
                mock.patch.object(h44, "_ov_q", lambda a, t=6: (0, "")), \
                mock.patch.object(h44, "_bld_svx_log_state", lambda: "connected"), \
                mock.patch.object(h44, "_bld_tcp_reachable", lambda host, port: True):
            magic = h44.build_build_status("magic")
            travel = h44.build_build_status("travel")
        ids = [s["id"] for s in magic["stages"]]
        self.assertIn("svx_checks", ids)
        self.assertEqual(magic["profile"], "magic")
        self.assertIn("svx", magic)
        self.assertTrue(magic["svx"]["reflector"]["key_set"])
        self.assertNotIn(SECRET, json.dumps(magic))
        self.assertNotIn("svx", travel)
        self.assertNotIn("svx_checks", [s["id"] for s in travel["stages"]])
        by = {s["id"]: s for s in magic["stages"]}
        self.assertEqual(by["svx"]["state"], "done")
        self.assertEqual(by["svx_reflector"]["state"], "done")
        self.assertIn(by["svx_wire"]["state"], ("todo", "locked"))

    def test_board_detection(self):
        for model, zero2 in (("Raspberry Pi Zero 2 W Rev 1.0\x00", True), ("Raspberry Pi 4 Model B Rev 1.4\x00", False), ("", False)):
            with mock.patch.object(h44, "_BLD_MODEL", self.write("model", model)):
                self.assertEqual(h44._bld_board()["zero2"], zero2, model)
        with mock.patch.object(h44, "_BLD_MODEL", self.p("none")):
            self.assertEqual(h44._bld_board(), {"model": "", "zero2": False})

    def test_unknown_profile_falls_back_to_travel(self):
        with mock.patch.object(h44, "_bld_form_load", lambda: dict(GOOD)), \
                mock.patch.object(h44, "_bld_usb_cards", lambda: []), \
                mock.patch.object(h44, "_bld_machine", lambda: []), \
                mock.patch.object(h44, "_detect_installed_products", lambda force=False: []), \
                mock.patch.object(h44, "_wg0_interface_present", lambda: False), \
                mock.patch.object(h44, "_firewalld_zone_info_cached", lambda: None), \
                mock.patch.object(h44, "status_boot_order", lambda: {"done": False, "missing": []}), \
                mock.patch.object(h44, "_cfgr_usrp_pairs", lambda override=None: ([], [])), \
                mock.patch.object(h44, "_pn_status", lambda: {"available": False}), \
                mock.patch.object(h44, "_cfgr_snap_dir", lambda k, sid="": "x"), \
                mock.patch.object(h44, "_cfgr_read_manifest", lambda d: None), \
                mock.patch.object(h44, "_cfgr_load_preset", lambda p: None):
            st = h44.build_build_status("nope")
        self.assertEqual(st["profile"], "travel")

    def test_route_reads_the_profile(self):
        seen = []
        with mock.patch.object(h44, "build_build_status", lambda profile="travel": seen.append(profile) or {"stages": []}):
            h44._route_build_status({"profile": ["magic"]})
            h44._route_build_status({})
        self.assertEqual(seen, ["magic", "travel"])

    def test_save_keeps_svx_fields_and_profile_errors(self):
        path = self.p("b.json")
        with mock.patch.object(h44, "_BLD_FILE", path), mock.patch.object(h44, "_bld_usb_cards", lambda: []):
            r = h44._bld_act_form_save(dict(GOOD, profile="magic", svx_host="example.org", svx_port=""))
            self.assertIn("svx_port", r["errors"])
            self.assertEqual(json.load(open(path))["svx_host"], "example.org")
            r = h44._bld_act_form_save(dict(GOOD, profile="travel", svx_host="bad host"))
            self.assertEqual(r["errors"], {})


if __name__ == "__main__":
    unittest.main()
