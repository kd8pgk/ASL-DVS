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


spec = importlib.util.spec_from_file_location("h44_build_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_build_under_test"] = h44
spec.loader.exec_module(h44)

CARD1 = {"card": 1, "name": "USB Audio Device", "usbid": "0d8c:013c", "devstr": "1-1.2", "radio_chip": "C-Media"}
CARD2 = {"card": 2, "name": "Other", "usbid": "0c76:1607", "devstr": "1-1.3", "radio_chip": "JMTek"}
GOOD = {"mode": "half", "callsign": "KD8PGK", "node": "652701", "dmr_id": "3123456", "nxdn_id": "12345",
        "m17_node": "1917", "usb": "", "bypass": ""}


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


class FormRules(unittest.TestCase):
    def errs(self, **kw):
        return h44._bld_form_errors(dict(GOOD, **kw), [])

    def test_good_form_has_no_errors(self):
        self.assertEqual(self.errs(), {})

    def test_required_fields(self):
        e = self.errs(callsign="", node="", dmr_id="", nxdn_id="")
        self.assertEqual(sorted(e), ["callsign", "dmr_id", "node"])

    def test_nxdn_is_optional_but_checked_when_given(self):
        self.assertEqual(self.errs(nxdn_id=""), {})
        self.assertIn("nxdn_id", self.errs(nxdn_id="123456"))

    def test_patterns(self):
        self.assertIn("callsign", self.errs(callsign="K8"))
        self.assertIn("node", self.errs(node="12"))
        self.assertIn("dmr_id", self.errs(dmr_id="123456"))
        self.assertIn("nxdn_id", self.errs(nxdn_id="123456"))

    def test_m17_node_rules(self):
        self.assertIn("m17_node", self.errs(m17_node="2000"))
        self.assertIn("m17_node", self.errs(m17_node="1999"))
        self.assertIn("m17_node", self.errs(m17_node="1921"))
        self.assertNotIn("m17_node", self.errs(m17_node="1917"))

    def test_bypass_only_in_full_mode(self):
        self.assertIn("bypass", self.errs(bypass="1.2.3.4"))
        self.assertEqual(self.errs(mode="full", bypass="1.2.3.4 example.org, 62031"), {})

    def test_bypass_bad_tokens(self):
        for bad in ("999.1.1.1", "70000", "bad_host", "-x.org", "a..b"):
            self.assertIn("bypass", self.errs(mode="full", bypass=bad), bad)

    def test_bypass_limit(self):
        many = " ".join(f"h{i}.example.org" for i in range(21))
        self.assertIn("bypass", self.errs(mode="full", bypass=many))

    def test_usb_pick_rules(self):
        self.assertEqual(h44._bld_form_errors(dict(GOOD), [CARD1]), {})
        self.assertIn("usb", h44._bld_form_errors(dict(GOOD), [CARD1, CARD2]))
        self.assertEqual(h44._bld_form_errors(dict(GOOD, usb="1-1.3"), [CARD1, CARD2]), {})
        self.assertIn("usb", h44._bld_form_errors(dict(GOOD, usb="9-9"), [CARD1]))

    def test_no_card_is_not_an_error(self):
        self.assertEqual(h44._bld_form_errors(dict(GOOD), []), {})


class FormStore(Tmp):
    def test_clean_uppercases_and_drops_unknown(self):
        f = h44._bld_form_clean({"callsign": " kd8pgk ", "mode": "bogus", "evil": "x", "node": 5})
        self.assertEqual(f["callsign"], "KD8PGK")
        self.assertEqual(f["mode"], "half")
        self.assertNotIn("evil", f)
        self.assertEqual(f["node"], "")

    def test_roundtrip_and_mode_0600(self):
        with mock.patch.object(h44, "_BLD_FILE", self.p("etc/build.json")):
            h44._bld_form_write(dict(GOOD))
            self.assertEqual(h44._bld_form_load()["node"], "652701")
            self.assertEqual(os.stat(self.p("etc/build.json")).st_mode & 0o777, 0o600)

    def test_load_missing_or_garbage(self):
        with mock.patch.object(h44, "_BLD_FILE", self.p("none.json")):
            self.assertEqual(h44._bld_form_load(), h44._BLD_DEFAULT)
        path = self.write("bad.json", "{not json")
        with mock.patch.object(h44, "_BLD_FILE", path):
            self.assertEqual(h44._bld_form_load(), h44._BLD_DEFAULT)
        path = self.write("odd.json", json.dumps({"node": 5, "callsign": "X1Y", "zzz": "q"}))
        with mock.patch.object(h44, "_BLD_FILE", path):
            f = h44._bld_form_load()
        self.assertEqual((f["node"], f["callsign"]), ("", "X1Y"))

    def test_no_secrets_field_exists(self):
        for k in h44._BLD_FIELDS:
            self.assertNotRegex(k.replace("bypass", ""), r"pass|key|secret|token|config")

    def test_save_action_and_reset(self):
        path = self.p("etc/build.json")
        with mock.patch.object(h44, "_BLD_FILE", path), mock.patch.object(h44, "_bld_usb_cards", lambda: []):
            r = h44._bld_act_form_save(dict(GOOD, evil="x"))
            self.assertTrue(r["success"])
            self.assertEqual(r["errors"], {})
            self.assertTrue(os.path.exists(path))
            self.assertTrue(h44._bld_act_form_reset({})["success"])
            self.assertFalse(os.path.exists(path))
            self.assertTrue(h44._bld_act_form_reset({})["success"])

    def test_save_reports_remaining_errors(self):
        with mock.patch.object(h44, "_BLD_FILE", self.p("b.json")), mock.patch.object(h44, "_bld_usb_cards", lambda: []):
            r = h44._bld_act_form_save({"callsign": "K"})
            self.assertTrue(r["success"])
            self.assertIn("callsign", r["errors"])
            self.assertIn("Still to fix", r["message"])


class UsbCards(Tmp):
    def build(self, cards):
        asound, usb = self.p("asound"), self.p("usb")
        lines = []
        for i, (usbid, bus, dev, dstr, name) in enumerate(cards):
            lines.append(f" {i} [Device{i}        ]: USB-Audio - {name}")
            lines.append(f"                      {name} at usb-3f980000.usb-1.2, full speed")
            self.write(f"asound/card{i}/usbid", usbid + "\n")
            self.write(f"asound/card{i}/usbbus", f"{bus:03d}/{dev:03d}\n")
            self.write(f"usb/{dstr}/busnum", f"{bus}\n")
            self.write(f"usb/{dstr}/devnum", f"{dev}\n")
        self.write("asound/cards", "\n".join(lines) + "\n")
        return mock.patch.multiple(h44, _BLD_ASOUND=asound, _BLD_USB_SYS=usb)

    def test_two_cards_map_to_sysfs_names(self):
        with self.build([("0d8c:013c", 1, 5, "1-1.2", "USB Audio Device"), ("0c76:1607", 1, 6, "1-1.3", "Other")]):
            cards = h44._bld_usb_cards()
        self.assertEqual([c["devstr"] for c in cards], ["1-1.2", "1-1.3"])
        self.assertEqual([c["radio_chip"] for c in cards], ["C-Media", "JMTek"])

    def test_non_radio_vendor_has_no_chip(self):
        with self.build([("1234:5678", 1, 5, "1-1.2", "Headset")]):
            self.assertEqual(h44._bld_usb_cards()[0]["radio_chip"], "")

    def test_onboard_card_without_usbid_is_skipped(self):
        self.write("asound/cards", " 0 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones\n")
        with mock.patch.multiple(h44, _BLD_ASOUND=self.p("asound"), _BLD_USB_SYS=self.p("usb")):
            self.assertEqual(h44._bld_usb_cards(), [])

    def test_no_asound_at_all(self):
        with mock.patch.multiple(h44, _BLD_ASOUND=self.p("nope"), _BLD_USB_SYS=self.p("nope2")):
            self.assertEqual(h44._bld_usb_cards(), [])


RPT = """[1999](node-main)
rxchannel = USRP/127.0.0.1:34001:32001
[652701](node-main)
rxchannel = SimpleUSB/652701
[1921](node-main)
rxchannel = USRP/127.0.0.1:34018:32018
[1001](node-main)
rxchannel = Local/pseudo
"""


class Radio(Tmp):
    def radio(self, form, cards, rpt=RPT, usb=None, nt=False):
        self.write("rpt.conf", rpt)
        paths = {"_BLD_RPT": self.p("rpt.conf"), "_BLD_SAVENODE": self.p("savenode.conf"),
                 "_BLD_SIMPLEUSB": self.p("simpleusb.conf"), "_BLD_NODETALKER": self.p("nt.py")}
        if usb is not None:
            self.write("simpleusb.conf", usb)
        if nt:
            self.write("nt.py", "")
        with mock.patch.multiple(h44, **paths):
            return h44._bld_radio(form, cards)

    def test_reads_rxchannel_devstr_and_extras(self):
        r = self.radio(GOOD, [CARD1], usb="[652701](node-main)\ndevstr = \n", nt=True)
        self.assertEqual((r["rxchannel"], r["devstr"], r["nodetalker"], r["stanza_1921"]), ("SimpleUSB/652701", "", True, True))
        self.assertEqual(r["phone_nodes"], ["1001"])

    def test_node_falls_back_to_savenode(self):
        self.write("savenode.conf", "NODE=652701\n")
        r = self.radio(dict(GOOD, node=""), [])
        self.assertEqual(r["node"], "652701")

    def test_state_no_node_or_stanza(self):
        r = self.radio(dict(GOOD, node=""), [])
        self.assertEqual(h44._bld_radio_state(r)[0], "todo")
        r = self.radio(GOOD, [], rpt="[1999]\nrxchannel = x\n")
        self.assertEqual(h44._bld_radio_state(r)[0], "todo")

    def test_state_not_simpleusb_warns(self):
        r = self.radio(GOOD, [CARD1], rpt="[652701](node-main)\nrxchannel = Local/pseudo\n")
        self.assertEqual(h44._bld_radio_state(r)[0], "warn")

    def test_no_card_warns_and_devstr_stays_empty(self):
        r = self.radio(GOOD, [], usb="[652701]\ndevstr =\n")
        st, why = h44._bld_radio_state(r)
        self.assertEqual(st, "warn")
        self.assertIn("devstr stays empty", why)

    def test_one_card_empty_devstr_is_done(self):
        r = self.radio(GOOD, [CARD1], usb="[652701]\ndevstr =\n")
        self.assertEqual(h44._bld_radio_state(r)[0], "done")

    def test_two_cards_need_a_pick_then_match(self):
        r = self.radio(GOOD, [CARD1, CARD2], usb="[652701]\ndevstr =\n")
        self.assertEqual(h44._bld_radio_state(r)[0], "todo")
        r = self.radio(dict(GOOD, usb="1-1.3"), [CARD1, CARD2], usb="[652701]\ndevstr =\n")
        self.assertEqual(h44._bld_radio_state(r)[0], "todo")
        r = self.radio(dict(GOOD, usb="1-1.3"), [CARD1, CARD2], usb="[652701]\ndevstr = 1-1.3\n")
        self.assertEqual(h44._bld_radio_state(r)[0], "done")


class Stages(unittest.TestCase):
    def ids(self, mode):
        return [i for i, _ in h44._bld_stage_defs(mode)]

    def test_half_order(self):
        self.assertEqual(self.ids("half"), ["preflight", "tunnel", "asl3", "apply_asl3", "iax_port", "dvs", "apply_dvs", "m17",
                                            "apply_m17", "half", "ports", "boot", "wiring", "radio", "preset", "save", "reboot"])

    def test_split_has_no_half_stage(self):
        self.assertNotIn("half", self.ids("split"))
        self.assertEqual(self.ids("split")[1], "tunnel")

    def test_full_puts_tunnel_after_the_systems(self):
        ids = self.ids("full")
        self.assertEqual(ids[:8], ["preflight", "asl3", "apply_asl3", "iax_port", "dvs", "apply_dvs", "m17", "apply_m17"])
        self.assertEqual(ids[8:10], ["tunnel", "fullx"])
        self.assertNotIn("half", ids)

    def test_every_mode_ends_the_same(self):
        for m in ("half", "split", "full"):
            self.assertEqual(self.ids(m)[-7:], ["ports", "boot", "wiring", "radio", "preset", "save", "reboot"])

    def test_no_tunnel_mode_leaves_every_tunnel_step_out(self):
        for profile in ("travel", "magic"):
            ids = [i for i, _ in h44._bld_stage_defs("none", profile)]
            for gone in ("tunnel", "half", "fullx"):
                self.assertNotIn(gone, ids)
            self.assertEqual(ids[0], "preflight")
            self.assertEqual(ids[-6:] if profile == "travel" else [i for i in ids[-7:] if i != "svx_checks"],
                             ["boot", "wiring", "radio", "preset", "save", "reboot"])
            self.assertIn("asl3", ids)

    def test_no_tunnel_is_a_valid_mode(self):
        self.assertEqual(h44._bld_form_clean({"mode": "none"})["mode"], "none")
        self.assertIn("none", h44._BLD_MODES)
        self.assertEqual(h44._bld_form_errors(dict(GOOD, mode="none"), []), {})
        self.assertIn("bypass", h44._bld_form_errors(dict(GOOD, mode="none", bypass="1.2.3.4"), []))

    def test_ports_come_after_the_tunnels(self):
        ids = self.ids("full")
        self.assertEqual(ids[ids.index("fullx") + 1], "ports")
        ids = self.ids("half")
        self.assertEqual(ids[ids.index("half") + 1], "ports")
        ids = self.ids("split")
        self.assertGreater(ids.index("ports"), ids.index("apply_m17"))


class Applied(Tmp):
    def test_asl3_apply_needs_the_node_stanza(self):
        self.write("rpt.conf", "[652701](node-main)\nrxchannel = SimpleUSB/652701\n")
        with mock.patch.object(h44, "_BLD_RPT", self.p("rpt.conf")):
            self.assertTrue(h44._bld_applied("apply_asl3", GOOD, "652701")[0])
            self.assertFalse(h44._bld_applied("apply_asl3", GOOD, "111111")[0])
            self.assertFalse(h44._bld_applied("apply_asl3", GOOD, "")[0])

    def test_dvs_apply_needs_callsign_and_id(self):
        self.write("m.ini", "[General]\nCallsign=KD8PGK\nId=3123456\n")
        with mock.patch.object(h44, "_BLD_MMDVM", self.p("m.ini")):
            self.assertTrue(h44._bld_applied("apply_dvs", GOOD, "652701")[0])
            self.assertFalse(h44._bld_applied("apply_dvs", dict(GOOD, dmr_id="3999999"), "652701")[0])
            self.assertFalse(h44._bld_applied("apply_dvs", dict(GOOD, callsign="W1AW"), "652701")[0])

    def test_m17_apply_needs_callsign(self):
        self.write("u.ini", "[General]\nCallsign=KD8PGK\n")
        with mock.patch.object(h44, "_BLD_M17INI", self.p("u.ini")):
            self.assertTrue(h44._bld_applied("apply_m17", GOOD, "652701")[0])
            self.assertFalse(h44._bld_applied("apply_m17", dict(GOOD, callsign=""), "652701")[0])


class Status(Tmp):
    def status(self, installed=(), form=None, wg="", up=False, age=None, boot_done=False, restore=False, machine=None):
        self.write("build.json", json.dumps(form or GOOD))
        prods = [{"key": k, "state": "installed"} for k in installed]
        patches = dict(_BLD_FILE=self.p("build.json"), _BLD_RPT=self.p("rpt.conf"), _BLD_SAVENODE=self.p("sn"),
                       _BLD_SIMPLEUSB=self.p("su"), _BLD_MMDVM=self.p("m.ini"), _BLD_M17INI=self.p("u.ini"),
                       _BLD_NODETALKER=self.p("nt"), WG0_CONF_PATH=self.p("wg0.conf"))
        if wg:
            self.write("wg0.conf", wg)
        with mock.patch.multiple(h44, **patches), \
                mock.patch.object(h44, "_bld_usb_cards", lambda: []), \
                mock.patch.object(h44, "_bld_machine", lambda: machine or [{"key": "os", "label": "OS", "level": "ok", "detail": ""}]), \
                mock.patch.object(h44, "_detect_installed_products", lambda force=False: prods), \
                mock.patch.object(h44, "_wg0_interface_present", lambda: up), \
                mock.patch.object(h44, "_bld_hs_age", lambda: age), \
                mock.patch.object(h44, "_firewalld_zone_info_cached", lambda: {"ports": []} if up else None), \
                mock.patch.object(h44, "status_boot_order", lambda: {"done": boot_done, "missing": [] if boot_done else ["x"]}), \
                mock.patch.object(h44, "_cfgr_usrp_pairs", lambda override=None: (["a"], [])), \
                mock.patch.object(h44, "_pn_status", lambda: {"available": True, "nodes_issues": [], "refs_issues": [], "old_ext": False}), \
                mock.patch.object(h44, "_cfgr_snap_dir", lambda k, sid="": "x"), \
                mock.patch.object(h44, "_cfgr_read_manifest", lambda d: {} if restore else None), \
                mock.patch.object(h44, "_cfgr_load_preset", lambda p: None):
            return h44.build_build_status()

    def by_id(self, st):
        return {s["id"]: s for s in st["stages"]}

    def test_fresh_node_everything_after_preflight_waits(self):
        st = self.status()
        s = self.by_id(st)
        self.assertEqual(s["preflight"]["state"], "done")
        self.assertEqual(s["tunnel"]["state"], "todo")
        self.assertEqual(s["asl3"]["state"], "locked")
        self.assertEqual(s["reboot"]["state"], "manual")

    def test_bad_form_keeps_preflight_open(self):
        st = self.status(form=dict(GOOD, callsign=""))
        self.assertEqual(self.by_id(st)["preflight"]["state"], "todo")
        self.assertIn("callsign", st["errors"])

    def test_machine_failure_blocks_preflight(self):
        st = self.status(machine=[{"key": "swap", "label": "Swap", "level": "fail", "detail": "off"}])
        self.assertEqual(self.by_id(st)["preflight"]["state"], "todo")
        st = self.status(machine=[{"key": "os", "label": "OS", "level": "warn", "detail": "trixie"}])
        self.assertEqual(self.by_id(st)["preflight"]["state"], "done")

    def test_tunnel_done_with_fresh_handshake(self):
        wg = "[Interface]\nAddress = 44.1.2.3/32\n# 44helper-routing-begin\nTable = 4445\n# 44helper-routing-end\n"
        st = self.status(wg=wg, up=True, age=30.0)
        self.assertEqual(self.by_id(st)["tunnel"]["state"], "done")
        st = self.status(wg=wg, up=True, age=900.0)
        self.assertEqual(self.by_id(st)["tunnel"]["state"], "todo")
        self.assertIn("handshake", self.by_id(st)["tunnel"]["detail"])

    def test_installed_systems_unlock_in_order(self):
        wg = "[Interface]\nAddress = 44.1.2.3/32\n# 44helper-routing-begin\nTable = 4445\n# 44helper-routing-end\n"
        st = self.status(installed=("asl3",), wg=wg, up=True, age=5.0)
        s = self.by_id(st)
        self.assertEqual(s["asl3"]["state"], "done")
        self.assertEqual(s["apply_asl3"]["state"], "todo")
        self.assertEqual(s["dvs"]["state"], "locked")

    def test_no_tunnel_status_has_no_tunnel_steps_and_the_systems_come_first(self):
        st = self.status(form=dict(GOOD, mode="none"))
        ids = [x["id"] for x in st["stages"]]
        self.assertEqual(ids[:3], ["preflight", "asl3", "apply_asl3"])
        self.assertNotIn("tunnel", ids)
        self.assertEqual(self.by_id(st)["asl3"]["state"], "todo")

    def test_full_mode_does_not_need_the_tunnel_first(self):
        st = self.status(form=dict(GOOD, mode="full"))
        s = self.by_id(st)
        self.assertEqual(s["asl3"]["state"], "todo")
        self.assertEqual(s["tunnel"]["state"], "locked")
        self.assertNotIn("half", s)
        self.assertIn("fullx", s)

    def test_save_and_boot_follow_the_node(self):
        st = self.status(boot_done=True, restore=True)
        s = self.by_id(st)
        self.assertEqual(s["boot"]["state"], "done")
        self.assertIn("Restore point saved", s["save"]["detail"])

    def test_payload_has_no_secret_keys(self):
        st = self.status()
        blob = json.dumps(st).lower()
        for word in ("privatekey", "password", "secret"):
            self.assertNotIn(word, blob)


class Dispatch(unittest.TestCase):
    def test_unknown_action(self):
        r = h44._dispatch_build_action({"action": "nope"})
        self.assertFalse(r["success"])
        self.assertIn("message", r)

    def test_needs_root(self):
        with mock.patch.object(h44.os, "geteuid", lambda: 1000):
            r = h44._dispatch_build_action({"action": "form_reset"})
        self.assertFalse(r["success"])
        self.assertIn("root", r["message"])

    def test_wg_check_needs_text(self):
        self.assertFalse(h44._bld_act_wg_check({"config_text": "  "})["success"])

    def test_wg_check_rejects_bad_config_and_never_echoes_it(self):
        r = h44._bld_act_wg_check({"config_text": "this is not a wireguard config PrivateKey=SECRETVALUE"})
        self.assertFalse(r["success"])
        self.assertNotIn("SECRETVALUE", json.dumps(r))

    def test_routes_registered(self):
        self.assertIn("/api/build/status", h44._GET_ROUTES)
        self.assertEqual(h44._GET_ROUTES["/api/build/status"], h44._route_build_status)

    def test_tab_registered_and_panel_present(self):
        self.assertIn("build", [t[0] for t in h44.TABS])
        self.assertIn("build", h44._PANEL_RENDERERS)
        self.assertIn('id="panel-build"', h44._render_build_panel())
        self.assertIn(("build", "Travel Node"), [(t[0], t[1]) for t in h44.TABS])
        self.assertIn("either build", h44._render_build_panel())


class Machine(unittest.TestCase):
    def test_rows_have_levels(self):
        rows = h44._bld_machine()
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["level"], ("ok", "warn", "fail"))
            self.assertTrue(r["label"])


if __name__ == "__main__":
    unittest.main()
