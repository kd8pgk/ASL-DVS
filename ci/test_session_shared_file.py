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


NC = load("nodecontrol_pi02w_v[0-9]*.py", "ss_nc")
SM = load("sysmon_pi02w_v[0-9]*.py", "ss_sm")
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
    def setUp(self):
        put({"sessions": {}, "failures": {}, "locked": {}})
        for mod in (NC, SM):
            mod._stamp_cache[0] = 0.0

    def at(self, t):
        return [mock.patch.object(NC.time, "time", lambda: t), mock.patch.object(SM.time, "time", lambda: t)]

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
        for mod, path in ((NC, "nodecontrol_pi02w_v[0-9]*.py"), (SM, "sysmon_pi02w_v[0-9]*.py")):
            self.assertEqual(mod._SESSION_COOKIE_NAME, "asl_dvs_session")
            with open(mod.__file__, encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn("def _require_auth(self)", src)
            self.assertIn('"/api/login"', src)

    def test_a_login_on_either_tool_opens_the_other(self):
        token, age = NC._issue_session()
        self.assertEqual(age, 12 * 3600)
        self.assertTrue(SM._check_session(token))
        token2, _ = SM._issue_session()
        self.assertTrue(NC._check_session(token2))

    def test_the_file_never_holds_a_raw_token(self):
        token, _ = NC._issue_session()
        self.assertNotIn(token, SHARED_FILE.read_text())
        self.assertIn(NC.sess_digest(token), raw()["sessions"])

    def test_the_old_layout_is_kept_with_numbers_for_every_session(self):
        NC._issue_session()
        d = raw()
        for key in ("sessions", "failures", "locked"):
            self.assertIn(key, d)
        self.assertTrue(all(isinstance(v, (int, float)) for v in d["sessions"].values()))

    def test_an_old_version_rewriting_the_file_keeps_the_new_sessions(self):
        token, _ = NC._issue_session()
        old_version_rewrite(T0 - 10 ** 9)
        self.assertTrue(SM._check_session(token))
        self.assertIn("meta", raw())

    def test_a_session_written_by_an_old_version_is_accepted_and_moved(self):
        legacy = "ab" * 32
        d = raw()
        d["sessions"][legacy] = 4_000_000_000.0
        put(d)
        self.assertTrue(NC._check_session(legacy))
        after = raw()
        self.assertNotIn(legacy, after["sessions"])
        self.assertIn(NC.sess_digest(legacy), after["sessions"])
        self.assertTrue(SM._check_session(legacy))

    def test_an_expired_old_session_is_refused(self):
        legacy = "cd" * 32
        d = raw()
        d["sessions"][legacy] = 5.0
        put(d)
        self.assertFalse(NC._check_session(legacy))

    def test_any_logout_ends_every_session_including_old_ones(self):
        legacy = "ef" * 32
        a, _ = NC._issue_session()
        b, _ = SM._issue_session()
        d = raw()
        d["sessions"][legacy] = 4_000_000_000.0
        put(d)
        self.assertEqual(SM._revoke_all_sessions(), 3)
        for t in (a, b, legacy):
            self.assertFalse(NC._check_session(t))
            self.assertFalse(SM._check_session(t))

    def test_standard_tier_idle_and_no_cap(self):
        token, _ = self.run_at(T0, NC._issue_session)
        self.assertTrue(self.run_at(T0 + 12 * 3600 - 60, lambda: SM._check_session(token)))
        self.assertTrue(self.run_at(T0 + 24 * 3600 - 120, lambda: NC._check_session(token)))
        token2, _ = self.run_at(T0, NC._issue_session)
        self.assertFalse(self.run_at(T0 + 12 * 3600 + 60, lambda: NC._check_session(token2)))

    def test_cookie_renew_about_hourly(self):
        for mod in (NC, SM):
            token, _ = self.run_at(T0, mod._issue_session)

            def probe(t):
                return self.run_at(t, lambda: (mod._check_session(token), getattr(mod._sess_local, "renew", 0)))
            self.assertEqual(probe(T0 + 300), (True, 0))
            ok, age = probe(T0 + 3700)
            self.assertTrue(ok)
            self.assertGreater(age, 0)

    def test_a_password_change_ends_every_session(self):
        for mod in (NC, SM):
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
            mod = NC if i % 2 == 0 else SM
            self.run_at(T0, lambda: mod._login_record_failure("10.1.1.1"))
            until = self.run_at(T0, lambda: SM._login_is_locked("10.1.1.1"))
            waits.append(round(until - T0) if until else 0)
        self.assertEqual(waits, [0, 0, 0, 0, 5, 10, 20, 40])
        self.assertEqual(self.run_at(T0 + 100, lambda: NC._login_is_locked("10.1.1.1")), None)

    def test_a_lock_set_by_an_old_version_is_honoured_and_a_new_one_is_visible_to_it(self):
        d = raw()
        d["locked"]["10.2.2.2"] = T0 + 900
        put(d)
        self.assertIsNotNone(self.run_at(T0, lambda: NC._login_is_locked("10.2.2.2")))
        for _ in range(5):
            self.run_at(T0, lambda: SM._login_record_failure("10.3.3.3"))
        self.assertGreater(raw()["locked"]["10.3.3.3"], T0)

    def test_a_good_login_clears_both_views(self):
        d = raw()
        d["failures"]["10.4.4.4"] = [T0]
        d["locked"]["10.4.4.4"] = T0 + 100
        put(d)
        NC._login_record_success("10.4.4.4")
        d = raw()
        self.assertNotIn("10.4.4.4", d["locked"])
        self.assertNotIn("10.4.4.4", d["failures"])


if __name__ == "__main__":
    unittest.main()
