#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import re
import sys
import unittest

ROOT = __file__.rsplit("/ci/", 1)[0]


def src(pattern):
    paths = sorted(glob.glob(ROOT + "/" + pattern))
    assert len(paths) == 1, (pattern, paths)
    return open(paths[0], encoding="utf-8").read()


class QuickLinks(unittest.TestCase):
    def test_no_allmon3_quick_link(self):
        for pat in ("instmon_v*.py", "nodecontrol_pi02w_v*.py", "nodecontrol_v[0-9]*.py",
                    "sysmon_pi02w_v*.py", "sysmon_v[0-9]*.py", "nodetalker_v*.py",
                    "noderecorder_v*.py", "nodemon_v*.py"):
            s = src(pat)
            self.assertNotIn('("Allmon3","/allmon3"', s, pat)
            self.assertNotIn('>Allmon3</a>', s, pat)

    def test_instmon_links(self):
        s = src("instmon_v*.py")
        self.assertIn('("Node Mon",7777 ,True )', s)
        self.assertIn("""scheme =' data-scheme="https"'if target in (7777 ,9090 )""", s)
        for name in ("SysMon", "Node Talker", "Node Recorder", "Node Monitor"):
            m = re.search(r'"name":"%s",\n(?:.*\n)*?"port":\d+ ?,\n"scheme":"https"' % re.escape(name), s)
            self.assertTrue(m, name)

    def test_node_controller_links(self):
        for pat in ("nodecontrol_pi02w_v*.py", "nodecontrol_v[0-9]*.py"):
            s = src(pat)
            self.assertIn("a.dataset.qlPort === '7777' || a.dataset.qlPort === '9090'", s, pat)
            self.assertIn("btn.href = `https://${window.location.hostname}:${d.port}/`", s, pat)
            self.assertIn("a.href = `https://${window.location.hostname}:${d.port}/`", s, pat)

    def test_sysmon_links(self):
        for pat in ("sysmon_pi02w_v*.py", "sysmon_v[0-9]*.py"):
            s = src(pat)
            self.assertIn('id === "lnk-nodemon" || id === "lnk-cockpit"', s, pat)
            self.assertIn('id="lnk-cockpit" class="ql-btn" href="https://localhost:9090/"', s, pat)
            self.assertIn('id="lnk-nodemon" class="ql-btn" href="https://localhost:7777/"', s, pat)

    def test_talker_and_recorder_links(self):
        for pat in ("nodetalker_v*.py", "noderecorder_v*.py"):
            s = src(pat)
            self.assertIn("q.dataset.qlPort === '7777' || q.dataset.qlPort === '9090' ? 'https://' : 'http://'", s, pat)
            self.assertIn("Open https://<pi-address>", s, pat)
        self.assertIn("$('tune-sysmon-link').href = 'https://'", src("nodetalker_v*.py"))

    def test_nodemon_links(self):
        s = src("nodemon_v*.py")
        body = s[s.index("TOOL_LINKS = ("):s.index(")\nWEB_PAGES")]
        for key, scheme in (("nodecontrol", "http"), ("sysmon", "https"), ("instmon", "http"), ("wifimon", "http"),
                            ("44helper", "http"), ("nodetalker", "https"), ("noderecorder", "https"),
                            ("pibrary", "http"), ("termon", "https"), ("cockpit", "https")):
            self.assertRegex(body, r'\("%s", "[^"]+", \d+, "%s"' % (key, scheme))
        self.assertIn("Open https://<node-address>", s)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
