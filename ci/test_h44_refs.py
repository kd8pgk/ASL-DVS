import glob
import importlib.util
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_refs_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_refs_under_test"] = h44
spec.loader.exec_module(h44)

RPT = """[events-main](!)
statpost = 1

[events]
x = 1

[events-652706](events-main,events-hotspotradio-usb)

[node-main](!)
events = events
functions = functions
morse = morse

[functions]
a = b

[morse]
c = d

[652705](node-main)
rxchannel = SimpleUSB/652705
events = events-652705
duplex = 0

[1999](node-main)
rxchannel = USRP/127.0.0.1:34001:32001
"""


def lines(text):
    return h44._cfgr_lines(text)


class Refs(unittest.TestCase):
    def test_a_node_pointing_at_a_misnamed_section_is_found_and_the_section_renamed(self):
        r = h44._pn_refs_check(lines(RPT))
        self.assertEqual(len(r["issues"]), 1)
        self.assertIn("[652705] events = events-652705: there is no [events-652705] section", r["issues"][0])
        self.assertEqual(len(r["fixes"]), 1)
        self.assertIn("[events-652706] renamed to [events-652705]", r["fixes"][0])
        self.assertEqual(r["unfixable"], [])
        out = h44._cfgr_join(r["lines"])
        self.assertIn("[events-652705](events-main,events-hotspotradio-usb)\n", out)
        self.assertNotIn("events-652706", out)
        self.assertEqual(out.count("\n"), RPT.count("\n"))

    def test_a_clean_file_has_nothing_to_report_or_change(self):
        ok = RPT.replace("[events-652706]", "[events-652705]")
        r = h44._pn_refs_check(lines(ok))
        self.assertEqual((r["issues"], r["fixes"], r["unfixable"]), ([], [], []))
        self.assertEqual(r["lines"], lines(ok))

    def test_no_candidate_is_named_for_hand_fixing_and_nothing_is_renamed(self):
        r = h44._pn_refs_check(lines(RPT.replace("[events-652706]", "[sounds-1]")))
        self.assertEqual(r["fixes"], [])
        self.assertEqual(len(r["unfixable"]), 1)
        self.assertIn("add a [events-652705] section", r["unfixable"][0])
        self.assertEqual(r["lines"], lines(RPT.replace("[events-652706]", "[sounds-1]")))

    def test_a_section_that_is_used_by_another_node_is_not_taken(self):
        two = RPT + "\n[1998](node-main)\nevents = events-652706\n"
        r = h44._pn_refs_check(lines(two))
        self.assertEqual(r["fixes"], [])
        self.assertEqual(len(r["unfixable"]), 1)

    def test_a_far_name_is_never_renamed_to_match(self):
        r = h44._pn_refs_check(lines(RPT.replace("[events-652706]", "[events-111111]")))
        self.assertEqual(r["fixes"], [])

    def test_the_template_name_alone_is_never_a_candidate(self):
        text = "[events-main](!)\nq = 1\n\n[1999](node-main)\nevents = events-1999\n\n[node-main](!)\nx=1\n"
        r = h44._pn_refs_check(lines(text))
        self.assertEqual(r["fixes"], [])

    def test_commented_lines_are_not_references(self):
        r = h44._pn_refs_check(lines(RPT.replace("events = events-652705", ";events = events-652705")))
        self.assertEqual(r["issues"], [])

    def test_a_trailing_comment_does_not_hide_the_name(self):
        r = h44._pn_refs_check(lines(RPT.replace("events = events-652705", "events = events-652705 ; mine")))
        self.assertEqual(len(r["issues"]), 1)

    def test_the_card_gets_the_issue_and_the_fix_flag(self):
        got = {}
        orig_read = h44._cfgr_read

        def fake_read(path):
            if path == h44._CFGR_RPT:
                return RPT.encode()
            return None
        h44._cfgr_read = fake_read
        try:
            got = h44._pn_status()
        finally:
            h44._cfgr_read = orig_read
        self.assertEqual(len(got["refs_issues"]), 1)
        self.assertTrue(got["refs_fixable"])

    def test_the_fix_action_previews_and_is_listed_as_changing_rpt_conf(self):
        self.assertIn("pn_fix_refs", h44._CFGR_RI_CHANGING)
        self.assertIn("pn_fix_refs_preview", h44._CFGR_ACTIONS)
        self.assertIn("pn_fix_refs", h44._CFGR_ACTIONS)
        orig = h44._cfgr_read
        h44._cfgr_read = lambda path: RPT.encode() if path == h44._CFGR_RPT else None
        try:
            r = h44._cfgr_act_pn_fix_refs({}, False)
        finally:
            h44._cfgr_read = orig
        self.assertTrue(r["success"])
        self.assertIn("-[events-652706](events-main,events-hotspotradio-usb)", r["output"])
        self.assertIn("+[events-652705](events-main,events-hotspotradio-usb)", r["output"])

    def test_the_page_has_the_row_and_the_buttons(self):
        with open(h44.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('id="cfg-pn-fixrefs"', src)
        self.assertIn("pn_fix_refs_preview", src)
        self.assertIn("pn.refs_issues", src)


if __name__ == "__main__":
    unittest.main()
