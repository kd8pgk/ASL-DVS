import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="instmon_page_")
for key, sub in (("INSTMON_CONFIG_DIR", "config"), ("INSTMON_LIBRARY_DIR", "library"), ("INSTMON_SUITELOG", "run/suitelog.jsonl"),
                 ("INSTMON_SUITELOG_FLAG", "run/suitelog.on")):
    os.environ[key] = os.path.join(WORK, sub)
os.environ["INSTMON_RECORDER_STATUS_URL"] = "http://127.0.0.1:9/x"


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("instmon_page_under_test", newest("instmon_v[0-9]*.py"))
im = importlib.util.module_from_spec(spec)
sys.modules["instmon_page_under_test"] = im
spec.loader.exec_module(im)

TABS = ("home", "tools", "files", "disk", "system")
WHERE = {
    "home": ('id="home-tools"', 'data-action="gh_check"', 'id="fu-btn"', "Quick Links"),
    "tools": ('id="components"', 'class="no-confirm-banner"'),
    "files": ('id="cg-holder"', 'id="confputter-card"', 'id="usbimp-card"', 'id="library"', 'id="docs-card"', 'id="backup-btn"'),
    "disk": ('data-diskimg-key="format"', 'data-diskimg-key="backup"', 'data-diskimg-key="clone"', 'data-diskimg-key="restore"'),
    "system": ('id="quiet-btn"', 'id="restore-btn"', 'data-action="comms_restart"', 'data-action="reboot"', 'id="suitelog-card"'),
}


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = im.render_page()
        cls.panels = {}
        marks = [cls.html.index(f'id="tabp-{t}"') for t in TABS] + [cls.html.index('id="logdock"')]
        for i, t in enumerate(TABS):
            cls.panels[t] = cls.html[marks[i]:marks[i + 1]]

    def test_five_tabs_and_only_home_shown_at_first(self):
        for t in TABS:
            self.assertEqual(self.html.count(f'data-tab="{t}"'), 1, t)
            self.assertEqual(self.html.count(f'id="tabp-{t}"'), 1, t)
        self.assertIn('<div class="tabp" id="tabp-home">', self.html)
        for t in TABS[1:]:
            self.assertIn(f'<div class="tabp" id="tabp-{t}" hidden>', self.html)

    def test_every_card_is_in_its_tab_once(self):
        for tab, needles in WHERE.items():
            for n in needles:
                self.assertEqual(self.html.count(n), 1, n)
                self.assertIn(n, self.panels[tab], f"{n} belongs in {tab}")

    def test_log_is_docked_outside_the_tabs(self):
        dock = self.html[self.html.index('id="logdock"'):self.html.index('id="popup-overlay"')]
        for n in ('id="log"', 'id="log-copy-btn"', 'id="logdock-toggle"', 'id="logdock-last"'):
            self.assertEqual(self.html.count(n), 1, n)
            self.assertIn(n, dock)
        self.assertNotIn("Execution Log</div>", self.html)

    def test_update_banners_sit_above_the_tabs(self):
        self.assertLess(self.html.index('id="fu-banners"'), self.html.index('id="tabp-home"'))

    def test_page_script_has_the_tab_code(self):
        for n in ("function showTab(name, quiet)", "function placeCards()", "function homeTools()", "function logDock(open)",
                  "tabsInit();", "placeCards();", "instmon_tab"):
            self.assertIn(n, self.html)

    def test_uninstall_asks_and_start_stop_do_not(self):
        self.assertIn("if (!confirm(`Uninstall ${btn.dataset.name}?", self.html)
        self.assertIn("Start and Stop act at once, with no prompt. Uninstall asks first.", self.html)
        self.assertNotIn("NO CONFIRMATIONS", self.html)

    def test_long_help_is_behind_a_help_button(self):
        for card in ('id="confputter-card"', 'id="usbimp-card"', 'id="docs-card"', 'id="quiet-btn"'):
            start = self.html.index(card)
            chunk = self.html[start:start + 4000]
            self.assertIn('data-action="toggle_diskimg_help"', chunk, card)
            self.assertIn('class="diskimg-help', chunk, card)

    def test_status_answer_is_unchanged(self):
        status = im.build_status()
        section = im.render_components_section(status)
        self.assertIn('id="cg-card"', section)
        self.assertIn('id="available-card"', section)


if __name__ == "__main__":
    unittest.main(verbosity=1)
