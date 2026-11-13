#!/usr/bin/env python3
import ast
import glob
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = {
    "nodetalker": "pw", "noderecorder": "pw", "instmon": "login-pw",
    "nodecontrol": "login-pw", "nodecontrol_pi02w": "login-pw", "sysmon": "login-pw", "sysmon_pi02w": "login-pw", "pibrary": "login-pw",
    "wifimon": "login-pw", "44helper": "login-pw",
}


def shared():
    with open(os.path.join(ROOT, "shared", "confio.py"), encoding="utf-8") as f:
        src = f.read()
    ns = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name in ("login_ui_html", "login_ui_inject"):
            exec(ast.get_source_segment(src, node), ns)
    return ns


def tool_file(key):
    found = sorted(glob.glob(os.path.join(ROOT, key + "_v*.py")))
    return found[-1]


class EyeFunctions(unittest.TestCase):
    def setUp(self):
        self.ns = shared()

    def test_inject_before_last_body(self):
        page = "<html><body><p>a</p></body></html>"
        out = self.ns["login_ui_inject"](page, "pw")
        self.assertTrue(out.startswith("<html><body><p>a</p><style>"))
        self.assertTrue(out.endswith("</script></body></html>"))
        self.assertEqual(out.count("</body>"), 1)

    def test_last_body_only(self):
        page = "<body>x '</body>' y</body>"
        out = self.ns["login_ui_inject"](page, "pw")
        self.assertTrue(out.startswith("<body>x '</body>' y<style>"))

    def test_no_body_is_unchanged(self):
        self.assertEqual(self.ns["login_ui_inject"]("<p>x</p>", "pw"), "<p>x</p>")

    def test_nonce_on_both_tags(self):
        out = self.ns["login_ui_html"]("pw", "abc")
        self.assertIn('<style nonce="abc">', out)
        self.assertIn('<script nonce="abc">', out)
        self.assertNotIn("nonce", self.ns["login_ui_html"]("pw"))

    def test_id_is_json_quoted(self):
        out = self.ns["login_ui_html"]('a"b</script>')
        self.assertNotIn("</script>a", out)
        self.assertEqual(out.count("</script>"), 1)

    def test_script_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        out = self.ns["login_ui_html"]("pw")
        js = re.search(r"<script>(.*)</script>", out, re.S).group(1)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
        try:
            r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.remove(f.name)

    def test_button_never_submits_and_hides_again(self):
        js = self.ns["login_ui_html"]("pw")
        self.assertIn("b.type='button'", js)
        self.assertIn("'submit'", js)
        self.assertIn("pagehide", js)


class EveryToolUsesIt(unittest.TestCase):
    def test_each_tool_wraps_its_login_page(self):
        for key, field in TOOLS.items():
            with self.subTest(tool=key):
                with open(tool_file(key), encoding="utf-8") as f:
                    src = f.read()
                self.assertIn("def login_ui_html(", src)
                self.assertIn("def login_ui_inject(", src)
                self.assertRegex(src, r'login_ui_inject\s*\([^\n]*"%s"|login_ui_inject\s*\(\s*(?:HTML|_HTML_SRC)' % re.escape(field)
                                 if key not in ("nodecontrol", "nodecontrol_pi02w") else r'"login-pw"\)\.encode')
                self.assertIn('id="%s"' % field, src)


if __name__ == "__main__":
    unittest.main()
