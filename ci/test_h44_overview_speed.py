#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import configparser
import glob
import importlib.util
import os
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("h44_ov", sorted(glob.glob(os.path.join(ROOT, "44helper_v*.py")))[-1])
h = importlib.util.module_from_spec(spec)
sys.modules["h44_ov"] = h
spec.loader.exec_module(h)


class Overview(unittest.TestCase):
    def setUp(self):
        h._OV_SHARED.update(data=None, at=0.0)
        h._ASL_REG_CACHE.update(data=None, at=0.0)
        self.cfg = configparser.ConfigParser()

    def slow(self, secs):
        def fn(*a, **k):
            time.sleep(secs)
            return None
        return fn

    def patches(self, secs=0.2):
        names = ["_parse_wg0_conf", "_wg0_conf_perms_ok", "_wg_show_wg0", "_firewalld_zone_info_cached",
                 "_ov_endpoint_findings_cached", "_ov_health_findings"]
        stack = [mock.patch.object(h, n, side_effect=self.slow(secs)) for n in names]
        stack.append(mock.patch.object(h, "_detect_installed_products", side_effect=lambda *a, **k: (time.sleep(secs), [])[1]))
        stack.append(mock.patch.object(h, "asl_registration_info", side_effect=lambda: (time.sleep(secs), {"available": True, "entries": []})[1]))
        stack.append(mock.patch.object(h, "_wg0_interface_present", return_value=False))
        stack.append(mock.patch.object(h, "_run_self_check", return_value=[]))
        stack.append(mock.patch.object(h, "_system_text", return_value="t"))
        stack.append(mock.patch.object(h.shutil, "which", return_value="/usr/bin/asterisk"))
        return stack

    def run_with(self, fn):
        stack = self.patches()
        for p in stack:
            p.start()
        try:
            return fn()
        finally:
            for p in reversed(stack):
                p.stop()

    def test_the_checks_run_side_by_side(self):
        t = time.monotonic()
        self.run_with(lambda: h.build_overview_data(self.cfg))
        self.assertLess(time.monotonic() - t, 0.2 * 8 * 0.5)

    def test_a_second_ask_inside_four_seconds_costs_nothing(self):
        def go():
            a = h.overview_shared(self.cfg)
            t = time.monotonic()
            b = h.overview_shared(self.cfg)
            return a, b, time.monotonic() - t
        a, b, took = self.run_with(go)
        self.assertIs(a, b)
        self.assertLess(took, 0.05)

    def test_force_asks_again(self):
        def go():
            a = h.overview_shared(self.cfg)
            return a, h.overview_shared(self.cfg, force=True)
        a, b = self.run_with(go)
        self.assertIsNot(a, b)

    def test_asterisk_registrations_are_kept_until_forced(self):
        stack = self.patches(0.0)
        for p in stack:
            p.start()
        try:
            h._asl_reg_cached()
            h._asl_reg_cached()
            self.assertEqual(h.asl_registration_info.call_count, 1)
            h._asl_reg_cached(force=True)
            self.assertEqual(h.asl_registration_info.call_count, 2)
        finally:
            for p in reversed(stack):
                p.stop()

    def test_simultaneous_askers_share_one_build(self):
        out = []

        def go():
            ts = [threading.Thread(target=lambda: out.append(h.overview_shared(self.cfg))) for _ in range(4)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.run_with(go)
        self.assertEqual(len(out), 4)
        self.assertTrue(all(o is out[0] for o in out))

    def test_the_route_force_clears_the_asterisk_copy(self):
        h._cfg = self.cfg

        def go():
            h._route_overview({})
            h._route_overview({"force": ["1"]})
            return h.asl_registration_info.call_count
        self.assertEqual(self.run_with(go), 2)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
