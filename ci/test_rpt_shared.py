import glob
import importlib.util
import os
import random
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="rpt_shared_")
os.environ["NODECONTROL_CONFIG_DIR"] = os.path.join(WORK, "nc")


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


nc = load("nc_rpt_under_test", newest("nodecontrol_v[0-9]*.py"))
ncp = load("ncp_rpt_under_test", newest("nodecontrol_pi02w_v[0-9]*.py"))
h44 = load("h44_rpt_under_test", newest("44helper_v[0-9]*.py"))


def old_phone_next_free(taken, start, lo, hi):
    span = hi - lo + 1
    for k in range(span):
        c = str(lo + (start - lo + k) % span)
        if c not in taken:
            return c
    return ""


def old_pn_next_free(used, lo, hi, reserved):
    for n in range(lo, hi + 1):
        if str(n) not in used and str(n) not in reserved:
            return str(n)
    return ""


class _NcNumbers:
    mod = None

    def test_next_free_counts_up_from_the_phone_node_and_wraps_like_before(self):
        rnd = random.Random(11)
        lo, hi = self.mod._PHONE_NODE_MIN, self.mod._PHONE_NODE_MAX
        for _ in range(300):
            start = rnd.randint(lo, hi)
            taken = {str(rnd.randint(lo, hi)) for _ in range(rnd.choice((0, 5, 200, 900)))}
            with mock.patch.object(self.mod, "_phone_node", lambda s=start: str(s)):
                self.assertEqual(self.mod._phone_next_free(taken), old_phone_next_free(taken, start, lo, hi), (start, len(taken)))

    def test_next_free_with_every_number_taken_is_empty(self):
        taken = {str(n) for n in range(self.mod._PHONE_NODE_MIN, self.mod._PHONE_NODE_MAX + 1)}
        with mock.patch.object(self.mod, "_phone_node", lambda: "1500"):
            self.assertEqual(self.mod._phone_next_free(taken), "")

    def test_next_free_skips_to_the_end_and_wraps_to_the_start(self):
        taken = {str(n) for n in range(1500, 2000)}
        with mock.patch.object(self.mod, "_phone_node", lambda: "1500"):
            self.assertEqual(self.mod._phone_next_free(taken), "1000")

    def test_hand_nodes_are_the_live_numeric_sections(self):
        text = ("[general]\nx=1\n\n; [1500]\n[1234](node-main)\nrxchannel = Local/pseudo\n\n[1001]\n[functions1002]\n"
                "[nodes]\n1999 = radio@127.0.0.1/1999,NONE\n[ 1777 ]\n[node-main]\n")
        with mock.patch.object(self.mod, "_ph_read", lambda p: text), mock.patch.object(self.mod, "_ph_path", lambda n: "/x/" + n):
            got = self.mod._phone_hand_nodes()
        old = set(re.findall(r"^\s*\[(\d+)\]", "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(";")), re.M))
        self.assertEqual(old, {"1234", "1001"})
        self.assertEqual(got, old | {"1777"})

    def test_hand_nodes_ignore_the_dashboards_own_block(self):
        body = "[1001](node-main)\nrxchannel = Local/pseudo\n"
        text = "[general]\n\n[1234]\n\n" + self.mod._PH_BEGIN + "\n" + body + self.mod._PH_END + "\n"
        with mock.patch.object(self.mod, "_ph_read", lambda p: text), mock.patch.object(self.mod, "_ph_path", lambda n: "/x/" + n):
            self.assertEqual(self.mod._phone_hand_nodes(), {"1234"})


class FullNodeControllerNumbers(_NcNumbers, unittest.TestCase):
    mod = nc


class Pi02wNodeControllerNumbers(_NcNumbers, unittest.TestCase):
    mod = ncp
class HelperNumbers(unittest.TestCase):
    def test_next_free_matches_the_old_search(self):
        rnd = random.Random(5)
        lo, hi, res = h44._CFGR_PRIVATE_MIN, h44._CFGR_PRIVATE_MAX, h44._PN_RESERVED
        for _ in range(300):
            used = {str(rnd.randint(lo, hi)) for _ in range(rnd.choice((0, 3, 400, 990)))} | {"general", "nodes"}
            self.assertEqual(h44._pn_next_free(used), old_pn_next_free(used, lo, hi, res))
        self.assertEqual(h44._pn_next_free({str(n) for n in range(lo, hi + 1)}), "")
        self.assertNotIn(h44._pn_next_free(set()), res)

    def test_scan_counts_headers_nodes_lines_and_function_sections_as_used(self):
        lines = ["[general]", "x=1", "", "[nodes]", "1234 = radio@127.0.0.1/1234,NONE", "1001 = radio@127.0.0.1/1001,NONE", "",
                 "; >>> managed by something >>>", "[1005]", "rxchannel = USRP/127.0.0.1:34005:32005", "; <<< end <<<", "",
                 h44._PN_NOTE, "[1002](node-main)", "rxchannel = USRP/127.0.0.1:34002:32002", "", "[functions1003]", "1=ilink,1"]
        sc = h44._pn_scan(lines)
        self.assertEqual(sc["used"], {"1234", "1001", "1005", "1002", "1003"})
        self.assertEqual(sc["ports"], {34002, 32002})
        self.assertEqual(sorted(sc["ours"]), ["1002"])
        self.assertEqual(h44._pn_next_free(sc["used"]), "1000")

    def test_a_node_with_only_a_function_section_is_not_handed_out(self):
        lines = ["[general]"] + ["[functions%d]" % n for n in range(1000, 1003)]
        self.assertEqual(h44._pn_next_free(h44._pn_scan(lines)["used"]), "1003")


class SharedCopies(unittest.TestCase):
    def test_both_tools_carry_the_shared_functions(self):
        for mod in (nc, ncp, h44):
            self.assertTrue(callable(mod.rpt_scan))
            self.assertTrue(callable(mod.rpt_next_free))


if __name__ == "__main__":
    unittest.main(verbosity=2)
