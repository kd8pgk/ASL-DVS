import glob
import importlib.util
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_apt_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_apt_under_test"] = h44
spec.loader.exec_module(h44)


def dpkg(*names):
    return {n: ("ii", "1.0") for n in names}


class Table(unittest.TestCase):
    def test_every_entry_is_well_formed(self):
        seen = set()
        for e in h44._BLD_APT:
            self.assertIn(e["group"], ("required", "recommended", "optional", "manager"), e["pkg"])
            self.assertRegex(e["pkg"], r"^[a-z0-9][a-z0-9+.-]+$")
            self.assertNotIn(e["pkg"], seen)
            seen.add(e["pkg"])
            self.assertTrue(e["by"] and e["why"], e["pkg"])
            if e.get("auto") is False:
                self.assertTrue(e["how"], e["pkg"])

    def test_the_risky_packages_are_never_installed_by_the_button(self):
        auto = {e["pkg"] for e in h44._BLD_APT if e.get("auto", True)}
        for risky in ("firewalld", "systemd-resolved", "network-manager", "wpasupplicant"):
            self.assertNotIn(risky, auto)

    def test_it_covers_what_wifimon_lists(self):
        with open(newest("wifimon_v[0-9]*.py"), encoding="utf-8") as f:
            src = f.read()
        wifimon = set(re.findall(r'"pkg": "([a-z0-9.+-]+)"', src))
        mine = {e["pkg"] for e in h44._BLD_APT}
        self.assertEqual(wifimon - mine, set())

    def test_sysmon_and_44helper_hints_are_in_the_list(self):
        pk = {e["pkg"] for e in h44._BLD_APT}
        for needed in ("mtr-tiny", "avahi-daemon", "libnss-mdns", "fail2ban", "usbutils", "alsa-utils", "psmisc", "traceroute",
                       "wireguard-tools", "iw", "iproute2", "iputils-ping", "openssl", "libraspberrypi-bin"):
            self.assertIn(needed, pk)


class Rows(unittest.TestCase):
    def rows(self, mode="half", pi=True, have=("iproute2",)):
        return {r["pkg"]: r for r in h44._bld_apt_rows(mode, pi, dpkg(*have))}

    def test_installed_is_read_from_dpkg(self):
        r = self.rows(have=("iproute2", "iw"))
        self.assertTrue(r["iproute2"]["installed"])
        self.assertTrue(r["iw"]["installed"])
        self.assertFalse(r["rfkill"]["installed"])

    def test_a_removed_or_half_installed_package_is_not_installed(self):
        rows = h44._bld_apt_rows("half", True, {"iw": ("rc", "1"), "rfkill": ("iU", "1"), "openssl": ("ii", "3")})
        by = {r["pkg"]: r["installed"] for r in rows}
        self.assertEqual((by["iw"], by["rfkill"], by["openssl"]), (False, False, True))

    def test_pi_packages_only_on_a_pi(self):
        self.assertIn("libraspberrypi-bin", self.rows(pi=True))
        self.assertNotIn("libraspberrypi-bin", self.rows(pi=False))
        self.assertNotIn("raspi-config", self.rows(pi=False))

    def test_tunnel_packages_only_with_a_tunnel(self):
        for mode in ("half", "split", "full"):
            self.assertIn("wireguard-tools", self.rows(mode=mode))
            self.assertIn("systemd-resolved", self.rows(mode=mode))
        self.assertNotIn("wireguard-tools", self.rows(mode="none"))
        self.assertNotIn("systemd-resolved", self.rows(mode="none"))

    def test_no_dpkg_means_everything_missing(self):
        self.assertFalse(any(r["installed"] for r in h44._bld_apt_rows("half", True, None)))

    def test_pi_detection(self):
        with mock.patch.object(h44, "_bld_board", lambda: {"model": "Raspberry Pi Zero 2 W Rev 1.0", "zero2": True}):
            self.assertTrue(h44._bld_is_pi())
        with mock.patch.object(h44, "_bld_board", lambda: {"model": "", "zero2": False}):
            self.assertFalse(h44._bld_is_pi())


class Pick(unittest.TestCase):
    def pick(self, scope, have=()):
        rows = h44._bld_apt_rows("half", True, dpkg(*have))
        return h44._bld_apt_pick(rows, scope)

    def test_scopes_widen(self):
        req, rec, allp = self.pick("required"), self.pick("recommended"), self.pick("all")
        self.assertTrue(set(req) < set(rec) < set(allp))
        self.assertIn("iw", req)
        self.assertNotIn("rfkill", req)
        self.assertIn("rfkill", rec)
        self.assertNotIn("fail2ban", rec)
        self.assertIn("fail2ban", allp)

    def test_installed_and_non_automatic_packages_are_left_out(self):
        req = self.pick("required", have=("iw", "openssl"))
        self.assertNotIn("iw", req)
        self.assertNotIn("openssl", req)
        for never in ("firewalld", "systemd-resolved", "network-manager", "wpasupplicant"):
            self.assertNotIn(never, self.pick("all"))

    def test_an_unknown_scope_means_required(self):
        self.assertEqual(self.pick("bogus"), self.pick("required"))

    def test_the_command(self):
        cmd = h44._bld_apt_cmd(["iw", "rfkill"])
        self.assertTrue(cmd.startswith("DEBIAN_FRONTEND=noninteractive apt-get update -qq && "))
        self.assertTrue(cmd.endswith(" iw rfkill"))
        self.assertIn("--force-confold", cmd)
        self.assertTrue(h44._is_apt_mutating(cmd))
        import subprocess
        self.assertEqual(subprocess.run(["sh", "-n", "-c", cmd], capture_output=True).returncode, 0)


class Action(unittest.TestCase):
    def go(self, payload=None, have=("iproute2",), running="", gate=None, mode="half"):
        started = []
        with mock.patch.object(h44, "_bld_running_job", lambda: running), \
                mock.patch.object(h44, "_bld_form_load", lambda: dict(h44._BLD_DEFAULT, mode=mode)), \
                mock.patch.object(h44, "_bld_board", lambda: {"model": "Raspberry Pi 4", "zero2": False}), \
                mock.patch.object(h44, "_installed_dpkg_all", lambda: dpkg(*have)), \
                mock.patch.object(h44, "_pkg_health_gate", lambda cmd: gate), \
                mock.patch.object(h44, "_start_unit_job", lambda key, cmd, **kw: started.append((key, cmd)) or {"job_key": key}):
            res = h44._bld_act_install_apt(dict({"profile": "travel"}, **(payload or {})))
        return res, started

    def test_starts_one_background_apt_job_for_the_missing_ones(self):
        res, started = self.go({"scope": "required"})
        self.assertTrue(res["success"])
        self.assertEqual(res["job_key"], "build_travel_apt")
        self.assertEqual(len(started), 1)
        cmd = started[0][1]
        self.assertIn("iw", cmd.split())
        self.assertNotIn("iproute2", cmd.split())
        self.assertNotIn("firewalld", cmd)

    def test_the_scope_changes_the_list(self):
        _r, a = self.go({"scope": "required"})
        _r, b = self.go({"scope": "all"})
        self.assertLess(len(a[0][1]), len(b[0][1]))
        self.assertIn("fail2ban", b[0][1])

    def test_nothing_missing_starts_nothing(self):
        every = [e["pkg"] for e in h44._BLD_APT]
        res, started = self.go(have=every)
        self.assertTrue(res["success"])
        self.assertEqual(started, [])
        self.assertIn("Nothing to install", res["message"])

    def test_refuses_while_another_build_job_runs(self):
        res, started = self.go(running="build_travel_dvs")
        self.assertFalse(res["success"])
        self.assertEqual(started, [])

    def test_a_broken_package_system_stops_it(self):
        res, started = self.go(gate={"success": False, "output": "line1\nline2\nbroken package"})
        self.assertFalse(res["success"])
        self.assertEqual(started, [])
        self.assertIn("Update tab", res["message"])
        self.assertIn("broken package", res["notes"])

    def test_no_tunnel_leaves_wireguard_out(self):
        _r, started = self.go({"scope": "required"}, mode="none")
        self.assertNotIn("wireguard-tools", started[0][1].split())
        _r, started = self.go({"scope": "required"}, mode="half")
        self.assertIn("wireguard-tools", started[0][1].split())

    def test_the_job_key_follows_the_tab_and_counts_as_a_build_job(self):
        res, _ = self.go({"profile": "magic"})
        self.assertEqual(res["job_key"], "build_magic_apt")
        with mock.patch.dict(h44._JOBS, {"build_travel_apt": {"status": "running", "started_at": 1}}, clear=True):
            self.assertEqual(h44._bld_running_job(), "build_travel_apt")


class Page(unittest.TestCase):
    def test_both_tabs_have_the_apt_table_scope_and_button(self):
        for js, html, fn, pfx in ((h44._JS_BUILD, h44._render_build_panel(), "build", "bld"),
                                  (h44._JS_MAGIC, h44._render_magic_panel(), "magic", "mbx")):
            for ident in ("apt", "apt-scope", "apt-btn", "suite-btn"):
                self.assertIn(f'id="{pfx}-{ident}"', html)
            self.assertIn(f"{fn}InstallApt(this)", html)
            self.assertIn("Both installs here are optional", html)
            self.assertIn(f"function {fn}InstallApt(", js)
            self.assertIn(f"function {fn}RenderApt(", js)
            self.assertIn("action: 'install_apt'", js)

    def test_the_status_carries_the_apt_list_and_it_is_not_a_step(self):
        with open(newest("44helper_v[0-9]*.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('out["apt"] = _bld_apt_state(form.get("mode", "half"))', src)
        for sid in ("apt", "install_apt", "suite"):
            self.assertNotIn(sid, [i for m in ("half", "split", "full", "none") for i, _ in h44._bld_stage_defs(m, "magic")])


if __name__ == "__main__":
    unittest.main()
