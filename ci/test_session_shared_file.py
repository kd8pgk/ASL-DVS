import glob
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="sess_shared_")
os.environ["NODECONTROL_CONFIG_DIR"] = os.path.join(WORK, "nc")
os.environ["NODETALKER_CONFIG_DIR"] = os.path.join(WORK, "nt")
os.environ.setdefault("SYSMON_CONFIG_DIR", os.path.join(WORK, "sm"))
SHARED_DIR = Path(WORK) / "run"
SHARED_FILE = SHARED_DIR / "auth_session.json"


def load(pattern, name):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    path = sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    mod._SHARED_AUTH_DIR = SHARED_DIR
    mod._SHARED_AUTH_FILE = SHARED_FILE
    return mod


NC_PI = load("nodecontrol_pi02w_v[0-9]*.py", "ss_nc")
SM_PI = load("sysmon_pi02w_v[0-9]*.py", "ss_sm")
NC_FULL = load("nodecontrol_v[0-9]*.py", "ss_ncf")
SM_FULL = load("sysmon_v[0-9]*.py", "ss_smf")
NM = load("nodemon_v[0-9]*.py", "ss_nm")
NT = load("nodetalker_v[0-9]*.py", "ss_nt")
T0 = 3_000_000.0


def raw():
    return json.loads(SHARED_FILE.read_text())


def put(data):
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    SHARED_FILE.write_text(json.dumps(data))


def old_version_rewrite(now):
    d = raw()
    d["sessions"] = {t: exp for t, exp in d["sessions"].items() if exp > now}
    d["failures"] = {ip: [t for t in hits if now - t < 300] for ip, hits in d["failures"].items()}
    SHARED_FILE.write_text(json.dumps(d))


class SharedFile(unittest.TestCase):
    NC = NC_PI
    SM = SM_PI

    def setUp(self):
        put({"sessions": {}, "failures": {}, "locked": {}})
        for mod in (self.NC, self.SM):
            mod._stamp_cache[0] = 0.0

    def at(self, t):
        return [mock.patch.object(self.NC.time, "time", lambda: t), mock.patch.object(self.SM.time, "time", lambda: t)]

    def run_at(self, t, fn):
        patches = self.at(t)
        for p in patches:
            p.start()
        try:
            return fn()
        finally:
            for p in patches:
                p.stop()

    def test_names_the_security_tab_looks_for_are_kept(self):
        for mod in (self.NC, self.SM):
            self.assertEqual(mod._SESSION_COOKIE_NAME, "asl_dvs_session")
            with open(mod.__file__, encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn("def _require_auth(self)", src)
            self.assertIn('"/api/login"', src)

    def test_a_login_on_either_tool_opens_the_other(self):
        token, age = self.NC._issue_session()
        self.assertEqual(age, 12 * 3600)
        self.assertTrue(self.SM._check_session(token))
        token2, _ = self.SM._issue_session()
        self.assertTrue(self.NC._check_session(token2))

    def test_the_file_never_holds_a_raw_token(self):
        token, _ = self.NC._issue_session()
        self.assertNotIn(token, SHARED_FILE.read_text())
        self.assertIn(self.NC.sess_digest(token), raw()["sessions"])

    def test_the_old_layout_is_kept_with_numbers_for_every_session(self):
        self.NC._issue_session()
        d = raw()
        for key in ("sessions", "failures", "locked"):
            self.assertIn(key, d)
        self.assertTrue(all(isinstance(v, (int, float)) for v in d["sessions"].values()))

    def test_an_old_version_rewriting_the_file_keeps_the_new_sessions(self):
        token, _ = self.NC._issue_session()
        old_version_rewrite(T0 - 10 ** 9)
        self.assertTrue(self.SM._check_session(token))
        self.assertIn("meta", raw())

    def test_a_session_written_by_an_old_version_is_accepted_and_moved(self):
        legacy = "ab" * 32
        d = raw()
        d["sessions"][legacy] = 4_000_000_000.0
        put(d)
        self.assertTrue(self.NC._check_session(legacy))
        after = raw()
        self.assertNotIn(legacy, after["sessions"])
        self.assertIn(self.NC.sess_digest(legacy), after["sessions"])
        self.assertTrue(self.SM._check_session(legacy))

    def test_an_expired_old_session_is_refused(self):
        legacy = "cd" * 32
        d = raw()
        d["sessions"][legacy] = 5.0
        put(d)
        self.assertFalse(self.NC._check_session(legacy))

    def test_any_logout_ends_every_session_including_old_ones(self):
        legacy = "ef" * 32
        a, _ = self.NC._issue_session()
        b, _ = self.SM._issue_session()
        d = raw()
        d["sessions"][legacy] = 4_000_000_000.0
        put(d)
        self.assertEqual(self.SM._revoke_all_sessions(), 3)
        for t in (a, b, legacy):
            self.assertFalse(self.NC._check_session(t))
            self.assertFalse(self.SM._check_session(t))

    def test_standard_tier_idle_and_no_cap(self):
        token, _ = self.run_at(T0, self.NC._issue_session)
        self.assertTrue(self.run_at(T0 + 12 * 3600 - 60, lambda: self.SM._check_session(token)))
        self.assertTrue(self.run_at(T0 + 24 * 3600 - 120, lambda: self.NC._check_session(token)))
        token2, _ = self.run_at(T0, self.NC._issue_session)
        self.assertFalse(self.run_at(T0 + 12 * 3600 + 60, lambda: self.NC._check_session(token2)))

    def test_cookie_renew_about_hourly(self):
        for mod in (self.NC, self.SM):
            token, _ = self.run_at(T0, mod._issue_session)

            def probe(t):
                return self.run_at(t, lambda: (mod._check_session(token), getattr(mod._sess_local, "renew", 0)))
            self.assertEqual(probe(T0 + 300), (True, 0))
            ok, age = probe(T0 + 3700)
            self.assertTrue(ok)
            self.assertGreater(age, 0)

    def test_a_password_change_ends_every_session(self):
        for mod in (self.NC, self.SM):
            with mock.patch.object(mod, "_read_shadow_hash", return_value="$6$aaa"):
                mod._stamp_cache[0] = 0.0
                token, _ = mod._issue_session()
                self.assertTrue(mod._check_session(token))
            with mock.patch.object(mod, "_read_shadow_hash", return_value="$6$bbb"):
                mod._stamp_cache[0] = 0.0
                self.assertFalse(mod._check_session(token))

    def test_lockout_is_shared_and_doubles(self):
        waits = []
        for i in range(8):
            mod = self.NC if i % 2 == 0 else self.SM
            self.run_at(T0, lambda: mod._login_record_failure("10.1.1.1"))
            until = self.run_at(T0, lambda: self.SM._login_is_locked("10.1.1.1"))
            waits.append(round(until - T0) if until else 0)
        self.assertEqual(waits, [0, 0, 0, 0, 5, 10, 20, 40])
        self.assertEqual(self.run_at(T0 + 100, lambda: self.NC._login_is_locked("10.1.1.1")), None)

    def test_a_lock_set_by_an_old_version_is_honoured_and_a_new_one_is_visible_to_it(self):
        d = raw()
        d["locked"]["10.2.2.2"] = T0 + 900
        put(d)
        self.assertIsNotNone(self.run_at(T0, lambda: self.NC._login_is_locked("10.2.2.2")))
        for _ in range(5):
            self.run_at(T0, lambda: self.SM._login_record_failure("10.3.3.3"))
        self.assertGreater(raw()["locked"]["10.3.3.3"], T0)

    def test_a_good_login_clears_both_views(self):
        d = raw()
        d["failures"]["10.4.4.4"] = [T0]
        d["locked"]["10.4.4.4"] = T0 + 100
        put(d)
        self.NC._login_record_success("10.4.4.4")
        d = raw()
        self.assertNotIn("10.4.4.4", d["locked"])
        self.assertNotIn("10.4.4.4", d["failures"])



class SharedFileFull(SharedFile):
    NC = NC_FULL
    SM = SM_FULL

    def test_the_console_probe_does_not_extend_a_session(self):
        token, _ = self.run_at(T0, self.SM._issue_session)
        self.assertTrue(self.run_at(T0 + 11 * 3600, lambda: self.SM._check_session(token, touch=False)))
        self.assertTrue(self.run_at(T0 + 11 * 3600 + 30, lambda: self.SM._check_session(token, touch=False)))
        self.assertFalse(self.run_at(T0 + 12 * 3600 + 60, lambda: self.SM._check_session(token, touch=False)))

    def test_a_normal_request_does_extend_it(self):
        token, _ = self.run_at(T0, self.SM._issue_session)
        self.assertTrue(self.run_at(T0 + 11 * 3600, lambda: self.SM._check_session(token)))
        self.assertTrue(self.run_at(T0 + 12 * 3600 + 60, lambda: self.SM._check_session(token)))

    def test_the_console_uses_the_probe_that_does_not_touch(self):
        with open(self.SM.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("lambda: _check_session(token, touch=False)", src)


class FourTools(unittest.TestCase):
    TOOLS = (("NC", NC_PI), ("SM", SM_PI), ("NCF", NC_FULL), ("SMF", SM_FULL), ("NM", NM), ("NT", NT))

    def setUp(self):
        put({"sessions": {}, "failures": {}, "locked": {}})
        for _, mod in self.TOOLS:
            mod._stamp_cache[0] = 0.0

    def run_at(self, t, fn):
        patches = [mock.patch.object(mod.time, "time", lambda: t) for _, mod in self.TOOLS]
        for p in patches:
            p.start()
        try:
            return fn()
        finally:
            for p in patches:
                p.stop()

    def fail(self, mod, ip):
        if mod in (NM, NT):
            return mod._record_auth_failure(ip)
        return mod._login_record_failure(ip)

    def wait(self, mod, ip):
        if mod in (NM, NT):
            return mod._auth_lockout_remaining(ip)
        until = mod._login_is_locked(ip)
        return max(0.0, until - mod.time.time()) if until else 0.0

    def test_all_four_use_one_cookie_name_and_the_standard_tier(self):
        for name, mod in self.TOOLS:
            with self.subTest(tool=name):
                self.assertEqual(mod._SESSION_COOKIE_NAME, "asl_dvs_session")
                self.assertEqual(mod._SESS_POLICY, mod.sess_policy("standard"))

    def test_a_login_on_any_tool_opens_every_other_tool(self):
        for name, issuer in self.TOOLS:
            token, age = issuer._issue_session()
            self.assertEqual(age, 12 * 3600)
            for other, mod in self.TOOLS:
                with self.subTest(issued=name, checked=other):
                    self.assertTrue(mod._check_session(token))

    def test_any_logout_ends_every_session_on_every_tool(self):
        for name, mod in self.TOOLS:
            with self.subTest(logout=name):
                put({"sessions": {}, "failures": {}, "locked": {}})
                tokens = [m._issue_session()[0] for _, m in self.TOOLS]
                self.assertEqual(mod._revoke_all_sessions(), len(tokens))
                for _, other in self.TOOLS:
                    for t in tokens:
                        self.assertFalse(other._check_session(t))

    def test_tokens_are_only_kept_as_hashes(self):
        for name, mod in (("NM", NM), ("NT", NT)):
            token, _ = mod._issue_session()
            self.assertNotIn(token, SHARED_FILE.read_text())
            self.assertIn(mod.sess_digest(token), raw()["sessions"])
            self.assertIn(mod.sess_digest(token), raw()["meta"])

    def test_a_root_password_change_ends_every_session(self):
        for name, mod in (("NM", NM), ("NT", NT)):
            with mock.patch.object(mod, "_read_shadow_hash", return_value="$6$aaa"):
                mod._stamp_cache[0] = 0.0
                token, _ = mod._issue_session()
                self.assertTrue(mod._check_session(token))
            for _, other in self.TOOLS:
                with mock.patch.object(other, "_read_shadow_hash", return_value="$6$bbb"):
                    other._stamp_cache[0] = 0.0
                    self.assertFalse(other._check_session(token))

    def test_the_session_expires_after_twelve_idle_hours_and_has_no_hard_cap(self):
        for name, mod in (("NM", NM), ("NT", NT)):
            token, _ = self.run_at(T0, mod._issue_session)
            self.assertTrue(self.run_at(T0 + 12 * 3600 - 60, lambda: NC_PI._check_session(token)))
            self.assertTrue(self.run_at(T0 + 24 * 3600 - 120, lambda: mod._check_session(token)))
            dead, _ = self.run_at(T0, mod._issue_session)
            self.assertFalse(self.run_at(T0 + 12 * 3600 + 60, lambda: mod._check_session(dead)))

    def test_the_cookie_is_refreshed_about_hourly(self):
        for name, mod in (("NM", NM), ("NT", NT)):
            token, _ = self.run_at(T0, mod._issue_session)

            def probe(t):
                return self.run_at(t, lambda: (mod._check_session(token), getattr(mod._sess_local, "renew", 0)))
            self.assertEqual(probe(T0 + 300), (True, 0))
            ok, age = probe(T0 + 3700)
            self.assertTrue(ok)
            self.assertGreater(age, 0)

    def test_failed_logins_on_different_tools_count_together(self):
        order = [NM, NT, NC_PI, SM_FULL, NM, NT, NC_FULL, SM_PI]
        waits = []
        for mod in order:
            self.run_at(T0, lambda: self.fail(mod, "10.1.1.1"))
            waits.append(round(self.run_at(T0, lambda: self.wait(NT, "10.1.1.1"))))
        self.assertEqual(waits, [0, 0, 0, 0, 5, 10, 20, 40])
        for name, mod in self.TOOLS:
            with self.subTest(tool=name):
                self.assertGreater(self.run_at(T0, lambda: self.wait(mod, "10.1.1.1")), 0)
                self.assertEqual(self.run_at(T0 + 100, lambda: self.wait(mod, "10.1.1.1")), 0)

    def test_a_good_login_clears_the_count_everywhere(self):
        for _ in range(3):
            self.run_at(T0, lambda: self.fail(NM, "10.5.5.5"))
        NT._record_auth_success("10.5.5.5")
        for _ in range(4):
            self.run_at(T0, lambda: self.fail(NT, "10.5.5.5"))
        self.assertEqual(self.run_at(T0, lambda: self.wait(NM, "10.5.5.5")), 0)

    def test_a_lock_written_by_an_older_version_is_honoured(self):
        d = raw()
        d["locked"]["10.2.2.2"] = T0 + 900
        put(d)
        for _, mod in (("NM", NM), ("NT", NT)):
            self.assertGreater(self.run_at(T0, lambda: mod._auth_lockout_remaining("10.2.2.2")), 0)

    def test_a_lock_set_here_is_visible_to_an_older_version(self):
        for _ in range(5):
            self.run_at(T0, lambda: NT._record_auth_failure("10.3.3.3"))
        self.assertGreater(raw()["locked"]["10.3.3.3"], T0)

    def test_internet_logins_have_their_own_limit(self):
        for i in range(20):
            self.run_at(T0, lambda: NM._record_auth_failure("203.0.113.%d" % i, True))
        self.assertGreater(self.run_at(T0, lambda: NT._auth_lockout_remaining("203.0.113.99", True)), 0)
        self.assertEqual(self.run_at(T0, lambda: NT._auth_lockout_remaining("203.0.113.99", False)), 0)

    def test_the_layout_other_tools_read_is_kept(self):
        NM._issue_session()
        NT._issue_session()
        d = raw()
        for key in ("sessions", "failures", "locked", "meta"):
            self.assertIn(key, d)
        self.assertTrue(all(isinstance(v, (int, float)) for v in d["sessions"].values()))
        self.assertEqual(len(d["sessions"]), 2)

    def test_node_monitor_binds_its_own_sessions_to_an_address_when_asked(self):
        token, _ = NM._issue_session("10.9.9.9")
        self.assertTrue(NM._check_session(token, "10.9.9.9"))
        self.assertFalse(NM._check_session(token, "10.8.8.8"))
        self.assertFalse(NM._check_session(token, "10.9.9.9"))

    def test_a_session_from_another_tool_is_not_bound_to_an_address(self):
        token, _ = NT._issue_session()
        self.assertTrue(NM._check_session(token, "10.8.8.8"))

    def test_node_monitor_keeps_at_most_ten_sessions_per_address(self):
        tokens = [NM._issue_session("10.7.7.7")[0] for _ in range(12)]
        live = [t for t in tokens if NM._check_session(t)]
        self.assertEqual(live, tokens[-10:])

    def test_the_alive_probe_of_sysmon_still_does_not_extend_a_shared_session(self):
        token, _ = self.run_at(T0, NT._issue_session)
        self.assertTrue(self.run_at(T0 + 11 * 3600, lambda: SM_FULL._check_session(token, touch=False)))
        self.assertFalse(self.run_at(T0 + 12 * 3600 + 60, lambda: SM_FULL._check_session(token, touch=False)))


if __name__ == "__main__":
    unittest.main()
