import glob
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="sess_adopt_")
os.environ["NODETALKER_SUITELOG"] = os.path.join(WORK, "nt_suitelog.jsonl")
os.environ["NODETALKER_SUITELOG_FLAG"] = os.path.join(WORK, "nt_suitelog.on")
os.environ["NODETALKER_CONFIG_DIR"] = os.path.join(WORK, "nt")
os.environ["NODERECORDER_CONFIG_DIR"] = os.path.join(WORK, "nr")
os.environ["NODERECORDER_RPT_CONF"] = os.path.join(WORK, "rpt.conf")
os.makedirs(os.environ["NODERECORDER_CONFIG_DIR"], exist_ok=True)
with open(os.environ["NODERECORDER_RPT_CONF"], "w") as fh:
    fh.write("[general]\n")
for key, sub in (("INSTMON_CONFIG_DIR", "im/config"), ("INSTMON_LIBRARY_DIR", "im/library"),
                 ("INSTMON_SUITELOG", "im/suitelog.jsonl"), ("INSTMON_SUITELOG_FLAG", "im/suitelog.on")):
    os.environ[key] = os.path.join(WORK, sub)
os.environ["INSTMON_RECORDER_STATUS_URL"] = "http://127.0.0.1:9/x"


def load(pattern, name):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    path = sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULES = {
    "nodetalker": (load("nodetalker_v[0-9]*.py", "sa_nt"), "standard"),
    "noderecorder": (load("noderecorder_v[0-9]*.py", "sa_nr"), "standard"),
    "instmon": (load("instmon_v[0-9]*.py", "sa_im"), "strict"),
}
T0 = 2_000_000.0


class Adoption(unittest.TestCase):
    def each(self):
        for key, (mod, tier) in MODULES.items():
            with self.subTest(tool=key):
                mod._sessions.clear()
                mod._lock_state.clear()
                mod._stamp_cache[0] = 0.0
                yield mod, tier

    @staticmethod
    def at(mod, t, running=False):
        patches = [mock.patch.object(mod.time, "time", lambda: t)]
        if hasattr(mod, "full_update_running"):
            patches.append(mock.patch.object(mod, "full_update_running", return_value=running))
        return patches

    def run_at(self, mod, t, fn):
        patches = self.at(mod, t)
        for p in patches:
            p.start()
        try:
            return fn()
        finally:
            for p in patches:
                p.stop()

    def test_policy_and_first_cookie_age(self):
        for mod, tier in self.each():
            token, age = self.run_at(mod, T0, mod._issue_session)
            self.assertEqual(age, 12 * 3600 if tier == "standard" else 2 * 3600)
            self.assertEqual(len(token), 64)

    def test_tokens_are_stored_only_as_hashes(self):
        for mod, _ in self.each():
            token, _ = mod._issue_session()
            self.assertNotIn(token, mod._sessions)
            self.assertIn(mod.sess_digest(token), mod._sessions)

    def test_standard_has_no_hard_cap_and_strict_has_one(self):
        for mod, tier in self.each():
            token, _ = self.run_at(mod, T0, mod._issue_session)
            last = True
            hours = 30 if tier == "standard" else 20
            for h in range(1, hours):
                last = self.run_at(mod, T0 + h * 3000 if tier == "strict" else T0 + h * 40000,
                                   lambda: mod._check_session(token))
                if not last:
                    break
            if tier == "standard":
                self.assertTrue(last)
            else:
                self.assertFalse(last)

    def test_idle_expiry(self):
        for mod, tier in self.each():
            token, _ = self.run_at(mod, T0, mod._issue_session)
            idle = 12 * 3600 if tier == "standard" else 2 * 3600
            self.assertTrue(self.run_at(mod, T0 + idle - 60, lambda: mod._check_session(token)))
            token2, _ = self.run_at(mod, T0, mod._issue_session)
            self.assertFalse(self.run_at(mod, T0 + idle + 60, lambda: mod._check_session(token2)))

    def test_renew_hint_about_hourly(self):
        for mod, _ in self.each():
            token, _ = self.run_at(mod, T0, mod._issue_session)

            def probe(t):
                return self.run_at(mod, t, lambda: (mod._check_session(token), getattr(mod._sess_local, "renew", 0)))
            self.assertEqual(probe(T0 + 300), (True, 0))
            ok, age = probe(T0 + 3700)
            self.assertTrue(ok)
            self.assertGreater(age, 0)
            self.assertEqual(probe(T0 + 3800), (True, 0))

    def test_logout_ends_every_session(self):
        for mod, _ in self.each():
            tokens = [mod._issue_session()[0] for _ in range(3)]
            self.assertEqual(mod._revoke_all_sessions(), 3)
            for t in tokens:
                self.assertFalse(mod._check_session(t))

    def test_a_password_change_ends_every_session(self):
        for mod, _ in self.each():
            with mock.patch.object(mod, "_read_shadow_hash", return_value="$6$aaa"):
                mod._stamp_cache[0] = 0.0
                token, _ = mod._issue_session()
                self.assertTrue(mod._check_session(token))
            with mock.patch.object(mod, "_read_shadow_hash", return_value="$6$bbb"):
                mod._stamp_cache[0] = 0.0
                self.assertFalse(mod._check_session(token))

    def test_unknown_and_empty_tokens_fail(self):
        for mod, _ in self.each():
            self.assertFalse(mod._check_session(""))
            self.assertFalse(mod._check_session(None))
            self.assertFalse(mod._check_session("x" * 64))

    def test_at_most_fifty_sessions(self):
        for mod, _ in self.each():
            tokens = [mod._issue_session()[0] for _ in range(55)]
            self.assertEqual(len(mod._sessions), 50)
            self.assertFalse(mod._check_session(tokens[0]))
            self.assertTrue(mod._check_session(tokens[-1]))

    def test_lockout_five_mistakes_then_doubling(self):
        for mod, _ in self.each():
            waits = []
            clock = [T0]
            with mock.patch.object(mod.time, "time", lambda: clock[0]), mock.patch.object(mod, "log_event"):
                for _ in range(8):
                    mod._record_auth_failure("10.0.0.9")
                    waits.append(round(mod._auth_lockout_remaining("10.0.0.9")))
                self.assertEqual(waits, [0, 0, 0, 0, 5, 10, 20, 40])
                clock[0] += 41
                self.assertEqual(mod._auth_lockout_remaining("10.0.0.9"), 0)
                mod._record_auth_success("10.0.0.9")
                mod._record_auth_failure("10.0.0.9")
                self.assertEqual(mod._auth_lockout_remaining("10.0.0.9"), 0)

    def test_lockout_is_capped_at_five_minutes(self):
        for mod, _ in self.each():
            with mock.patch.object(mod.time, "time", lambda: T0), mock.patch.object(mod, "log_event"):
                for _ in range(30):
                    mod._record_auth_failure("10.0.0.7")
                self.assertEqual(round(mod._auth_lockout_remaining("10.0.0.7")), 300)

    def test_cookie_names_and_flags(self):
        for key, (mod, _) in MODULES.items():
            with self.subTest(tool=key):
                plain = mod.sess_cookie(mod._SESSION_COOKIE_NAME, "tok", 100, False)
                self.assertTrue(plain.startswith(mod._SESSION_COOKIE_NAME + "=tok"))
                self.assertIn("HttpOnly", plain)
                self.assertIn("SameSite=Strict", plain)
                self.assertNotIn("Secure", plain)
                secure = mod.sess_cookie(mod._SESSION_COOKIE_NAME, "tok", 100, True)
                self.assertTrue(secure.startswith("__Host-" + mod._SESSION_COOKIE_NAME + "=tok"))
                self.assertIn("; Secure", secure)
                self.assertEqual(mod.sess_token_from("a=1; __Host-%s=tok" % mod._SESSION_COOKIE_NAME,
                                                     mod._SESSION_COOKIE_NAME), "tok")


if __name__ == "__main__":
    unittest.main()
