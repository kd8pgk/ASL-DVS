import configparser
import glob
import importlib.util
import json
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


spec = importlib.util.spec_from_file_location("h44_tabs_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_tabs_under_test"] = h44
spec.loader.exec_module(h44)
h44._cfg = configparser.ConfigParser()

TAB_REFRESH = {
    "router_install": ["refreshRouterInstall"], "full_tunnel": ["refreshPiInstall:full", "refreshFullX"], "split_tunnel": ["refreshPiInstall:split"],
    "nodes": ["refreshNodes"], "services": ["refreshServices"], "ports": ["refreshPorts"], "actions_log": ["refreshActionsLog"],
    "asl3": ["refreshAsl3"], "dvswitch": ["refreshDvswitch"], "svxlink": ["refreshSvxlink"], "m17": ["refreshM17"], "amp": ["refreshAmp"],
    "cloudflare": ["refreshCF"], "claude-remote": ["refreshCr"], "update": ["refreshUpdate"], "system_opt": ["refreshSystemOpt"],
    "config": ["refreshConfig"],
}
NAMES = sorted({x.split(":")[0] for v in TAB_REFRESH.values() for x in v})


def run_node(script: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr[:800])
    return json.loads(r.stdout)


def harness(body: str) -> str:
    stubs = "var calls = [];\n" + "".join(f"function {n}(a) {{ calls.push('{n}' + (a ? ':' + a : '')); }}\n" for n in NAMES)
    dom = """
var document = {querySelectorAll: function() { return []; }, getElementById: function() { return null; }};
var __guard = [];
function guardOnTab(id) { __guard.push(id); }
"""
    return dom + stubs + h44._JS_TABS.replace("\\\\", "\\") + "\n" + body


@unittest.skipUnless(shutil.which("node"), "node not installed")
class FirstOpen(unittest.TestCase):
    def test_a_tab_loads_its_data_once_when_first_opened(self):
        for tab, want in TAB_REFRESH.items():
            out = run_node(harness(f"clickTab('{tab}'); clickTab('{tab}'); clickTab('overview'); clickTab('{tab}'); console.log(JSON.stringify(calls));"))
            self.assertEqual(sorted(out), sorted(want), tab)

    def test_tabs_with_their_own_refresh_on_every_open_are_not_loaded_twice(self):
        for tab in ("overview", "build", "magic", "boot"):
            out = run_node(harness(f"clickTab('{tab}'); clickTab('{tab}'); console.log(JSON.stringify(calls));"))
            self.assertEqual(out, [], tab)

    def test_opening_one_tab_does_not_load_the_others(self):
        out = run_node(harness("clickTab('asl3'); clickTab('m17'); console.log(JSON.stringify(calls));"))
        self.assertEqual(sorted(out), ["refreshAsl3", "refreshM17"])

    def test_the_guard_hook_still_runs_on_every_open(self):
        out = run_node(harness("clickTab('asl3'); clickTab('asl3'); console.log(JSON.stringify(__guard));"))
        self.assertEqual(out, ["asl3", "asl3"])


class Startup(unittest.TestCase):
    def init_calls(self):
        m = re.search(r"function _startApp\(\) \{(.*?)\n\}", h44._JS_INIT, re.S)
        self.assertIsNotNone(m)
        return re.findall(r"\b([A-Za-z_$][\w$]*)\(", m.group(1))

    def test_startup_loads_only_the_first_tab_and_the_live_updates(self):
        calls = [c for c in self.init_calls() if c not in ("setInterval",)]
        self.assertEqual(calls, ["evStart", "termInit", "clickTab", "refreshOverview", "startQuietPolling"])

    def test_every_tab_the_startup_used_to_load_is_loaded_on_first_open(self):
        for name in NAMES:
            self.assertIn(name, h44._JS_TABS)

    def test_every_page_tab_is_known(self):
        ids = {t[0] for t in h44.TABS}
        self.assertTrue(set(TAB_REFRESH) <= ids)
        self.assertEqual(sorted(ids - set(TAB_REFRESH)), ["boot", "build", "magic", "overview"])

    def test_the_refresh_functions_all_exist_in_the_page(self):
        page = h44.render_page(h44._cfg)
        for n in NAMES:
            self.assertRegex(page, rf"function {n}\(")


if __name__ == "__main__":
    unittest.main()
