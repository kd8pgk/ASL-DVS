import collections
import configparser
import glob
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_page_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_page_under_test"] = h44
spec.loader.exec_module(h44)
h44._cfg = configparser.ConfigParser()
PAGE = h44.render_page(h44._cfg)

GUARDED_OPTIONAL_IDS = {
    "pi-aip-out-split": "only one of the two tunnel tabs has it; the code tests it before use",
    "pi-refl-out-full": "only one of the two tunnel tabs has it; the code tests it before use",
}
NOT_FUNCTIONS = {"fn", "replace"}
BUILTINS = {"confirm", "alert", "if", "return", "event", "this", "document", "window", "String", "encodeURIComponent", "parseInt", "JSON", "fetch",
            "setTimeout", "Number", "Math", "prompt", "stopPropagation", "preventDefault", "getElementById", "stopImmediatePropagation", "closest",
            "querySelector", "click", "focus", "select", "toggle", "remove", "add", "indexOf", "slice", "join", "split", "push", "trim", "toLowerCase",
            "toUpperCase", "test", "match", "stringify", "parse"}


def page_ids():
    ids = set(re.findall(r"""\bid=\\?["']([A-Za-z][\w:.-]*)\\?["']""", PAGE))
    ids |= set(re.findall(r"""\.id\s*=\s*['"]([\w:.-]+)['"]""", PAGE))
    return ids


def defined_functions(with_window=True):
    out = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", PAGE))
    out |= set(re.findall(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*function", PAGE))
    if with_window:
        out |= set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", PAGE))
    return out


class Ids(unittest.TestCase):
    def test_every_element_the_script_looks_up_by_name_exists(self):
        ids = page_ids()
        refs = set(re.findall(r"""getElementById\(\s*['"]([\w:.-]+)['"]\s*\)""", PAGE))
        missing = sorted(r for r in refs if r not in ids and r not in GUARDED_OPTIONAL_IDS)
        self.assertEqual(missing, [], "ids the script uses that the page does not have")

    def test_the_allowed_missing_ids_are_still_needed(self):
        ids = page_ids()
        refs = set(re.findall(r"""getElementById\(\s*['"]([\w:.-]+)['"]\s*\)""", PAGE))
        for k in GUARDED_OPTIONAL_IDS:
            self.assertIn(k, refs, f"{k} is no longer used: remove it from the list")
            self.assertNotIn(k, ids, f"{k} exists now: remove it from the list")

    def test_ids_are_not_defined_twice_in_the_html_part(self):
        body = PAGE.split("<script", 1)[0]
        counts = collections.Counter(re.findall(r"""\bid="([A-Za-z][\w:.-]*)\"""", body))
        self.assertEqual(sorted(k for k, n in counts.items() if n > 1), [])

    def test_the_build_tabs_have_the_same_parts_and_magic_adds_the_svxlink_ones(self):
        travel = {k.replace("bld-", "") for k in page_ids() if k.startswith("bld-")}
        magic = {k.replace("mbx-", "") for k in page_ids() if k.startswith("mbx-")}
        self.assertEqual(sorted(travel - magic), [])
        extra = sorted(magic - travel)
        self.assertTrue(all("svx" in k or k.endswith("pw_reflector") for k in extra), extra)


class Handlers(unittest.TestCase):
    def test_every_function_an_inline_handler_calls_exists(self):
        defs = defined_functions()
        called = set()
        for m in re.finditer(r"""\bon(?:click|change|input|submit|keydown|keyup|focus|blur)=\\?["']([^"']*)""", PAGE):
            called |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*\(", m.group(1)))
        missing = sorted(c for c in called if c not in defs and c not in BUILTINS and c not in NOT_FUNCTIONS)
        self.assertEqual(missing, [], "functions called from the page's buttons and fields that are not defined")

    def test_every_tab_button_has_a_panel(self):
        ids = page_ids()
        targets = set(re.findall(r"""switchTab\(\s*\\?['"]([\w-]+)\\?['"]""", PAGE))
        missing = sorted(t for t in targets if f"panel-{t}" not in ids and f"tbtn-{t}" not in ids)
        self.assertEqual(missing, [])

    def test_no_page_function_is_defined_and_never_named(self):
        unused = []
        for d in sorted(defined_functions(with_window=False)):
            if len(re.findall(r"(?<![\w$])" + re.escape(d) + r"(?![\w$])", PAGE)) == 1:
                unused.append(d)
        self.assertEqual(unused, [])


class Script(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_every_script_block_parses(self):
        blocks = re.findall(r"<script[^>]*>(.*?)</script>", PAGE, re.S)
        self.assertTrue(blocks)
        with tempfile.TemporaryDirectory() as d:
            for i, b in enumerate(blocks):
                path = os.path.join(d, f"b{i}.js")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(b)
                r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[:500])


if __name__ == "__main__":
    unittest.main()
