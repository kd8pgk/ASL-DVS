#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import unittest

import test_servers as ts

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "pages_check.mjs")
CHROME = os.environ.get("ASL_TEST_CHROME") or None
PLAYWRIGHT_MODULE = os.environ.get("ASL_TEST_PLAYWRIGHT_MODULE") or None

SYSMON_FULL_TABS = {"asldvs", "console", "dvsm", "edit", "firewall", "hardware", "journal", "m17",
                    "net", "overview", "phone", "ports", "reg", "sdcard", "security", "services",
                    "stfu", "tune", "zello"}
SYSMON_PI02W_TABS = {"asldvs", "dvsm", "edit", "hardware", "journal", "m17", "overview", "phone",
                     "ports", "reg", "sdcard", "services", "stfu", "tune"}

NC_FULL_TABS = {"tab-asl", "tab-dmr", "tab-dstar", "tab-echo", "tab-edit", "tab-fcs", "tab-m17",
                "tab-nxdn", "tab-p25", "tab-phone", "tab-stfu", "tab-xlx", "tab-ysf"}
NC_PI02W_TABS = NC_FULL_TABS
NT_TABS = {"nav-connect", "nav-listen", "nav-setup"}
NR_TABS = {"nav-connect", "nav-record", "nav-setup"}

PAGE_CASES = {
    "sysmon": {"title": "System Monitor", "tabs": SYSMON_FULL_TABS,
               "click": ["overview", "services", "ports", "hardware", "journal", "dvsm"]},
    "sysmon_pi02w": {"title": "System Monitor", "tabs": SYSMON_PI02W_TABS,
                     "click": ["overview", "services", "ports", "hardware", "journal", "dvsm"]},
    "nodecontrol": {"title": "Node Controller", "tabs": None, "click": []},
    "nodecontrol_pi02w": {"title": "Node Controller", "tabs": None, "click": []},
    "nodetalker": {"title": "Node Talker", "tabs": None, "click": []},
    "noderecorder": {"title": "Node Recorder", "tabs": None, "click": []},
    "nodecontrol_login": {"server": "nodecontrol", "title": "Node Controller", "tabs": NC_FULL_TABS, "click": [], "login": True},
    "nodecontrol_pi02w_login": {"server": "nodecontrol_pi02w", "title": "Node Controller", "tabs": NC_PI02W_TABS, "click": [], "login": True},
    "nodetalker_login": {"server": "nodetalker", "title": "Node Talker", "tabs": NT_TABS, "click": [], "login": True},
    "noderecorder_login": {"server": "noderecorder", "title": "Node Recorder", "tabs": NR_TABS, "click": [], "login": True},
}


LOGIN_FORMS = {
    "nodecontrol": {"passwordSelector": "#login-pw", "submitSelector": "#login-btn",
                    "readySelector": "#login-screen.hidden", "tabSelector": '.tabs .tab[id^="tab-"]'},
    "nodecontrol_pi02w": {"passwordSelector": "#login-pw", "submitSelector": "#login-btn",
                          "readySelector": "#login-screen.hidden", "tabSelector": '.tabs .tab[id^="tab-"]'},
    "nodetalker": {"passwordSelector": "#pw", "submitSelector": "#login-btn",
                   "readySelector": "#nav:not(.hidden)", "tabSelector": "#nav button, #nav a"},
    "noderecorder": {"passwordSelector": "#pw", "submitSelector": "#login-btn",
                     "readySelector": "#nav:not(.hidden)", "tabSelector": "#nav button, #nav a"},
}


def run_check(url, clicks, login=None, tab_selector=None):
    if not shutil.which("node"):
        raise unittest.SkipTest("node is not installed")
    payload = {"url": url, "clickTabs": clicks, "chromePath": CHROME,
               "playwrightModule": PLAYWRIGHT_MODULE, "tabSelector": tab_selector}
    if login:
        payload["login"] = dict(login, password=os.environ.get("ASL_TEST_ROOT_PASSWORD", ""))
    payload = json.dumps(payload)
    r = subprocess.run(["node", CHECK], input=payload, capture_output=True, text=True, timeout=120)
    if r.returncode == 3:
        raise unittest.SkipTest("playwright is not installed (set ASL_TEST_PLAYWRIGHT_MODULE)")
    if r.returncode != 0:
        raise AssertionError(f"pages_check failed: {r.stderr[-600:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def make_page_case(key, expect):
    class PageCase(unittest.TestCase):
        server = None
        result = None

        @classmethod
        def setUpClass(cls):
            if os.geteuid() != 0:
                raise unittest.SkipTest("server tests run as root (the tools require root)")
            server_key = expect.get("server", key)
            cls.server = ts.Server(server_key)
            cls.server.start()
            spec = cls.server.spec
            url = f"{spec['scheme']}://127.0.0.1:{spec['port']}/"
            login = None
            try:
                if expect.get("login"):
                    if not os.environ.get("ASL_TEST_ROOT_PASSWORD"):
                        raise unittest.SkipTest("set ASL_TEST_ROOT_PASSWORD to test the logged-in pages")
                    login = LOGIN_FORMS[server_key]
                cls.result = run_check(url, expect["click"], login=login,
                                       tab_selector=(login or {}).get("tabSelector"))
            except BaseException:
                cls.tearDownClass()
                raise

        @classmethod
        def tearDownClass(cls):
            if cls.server:
                cls.server.stop()

        def test_page_loads_without_javascript_errors(self):
            self.assertEqual(self.result.get("navigationError"), None)
            self.assertEqual(self.result.get("pageErrors"), [], "uncaught JavaScript errors")
            self.assertEqual(self.result.get("consoleErrors"), [], "console errors")

        def test_title(self):
            self.assertEqual(self.result.get("title"), expect["title"])

        def test_tab_set_matches_build(self):
            if expect["tabs"] is None:
                self.skipTest("tabs are only rendered after login; blocked until the login suite runs")
            self.assertEqual(set(self.result.get("tabs", [])), expect["tabs"])

        def test_clicked_tabs_show_their_panel(self):
            missing = [t for t in expect["click"] if self.result.get(f"tab_{t}") != 1]
            self.assertEqual(missing, [], "tabs whose panel did not show")

    PageCase.__name__ = f"Page_{key}"
    PageCase.__qualname__ = f"Page_{key}"
    return PageCase


for _key, _expect in PAGE_CASES.items():
    globals()[f"Page_{_key}"] = make_page_case(_key, _expect)


if __name__ == "__main__":
    unittest.main(verbosity=2)
