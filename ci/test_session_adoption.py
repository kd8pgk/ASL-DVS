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
os.environ["PIBRARY_CONFIG_DIR"] = os.path.join(WORK, "pib/config")
os.environ["PIBRARY_STAGE_DIR"] = os.path.join(WORK, "pib/staged")


def load(pattern, name):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    path = sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


DEFAULT = {"issue": "_issue_session", "check": "_check_session", "revoke": "_revoke_all_sessions",
           "fail": "_record_auth_failure", "success": "_record_auth_success", "cookie": "_SESSION_COOKIE_NAME",
           "shadow": "_read_shadow_hash", "store": "_sessions", "clock": "time", "log": "log_event"}


def spec(**over):
    return dict(DEFAULT, **over)


def remaining_default(mod, ip):
    return mod._auth_lockout_remaining(ip)


MODULES = {
    "nodetalker": (load("nodetalker_v[0-9]*.py", "sa_nt"), "standard", spec()),
    "noderecorder": (load("noderecorder_v[0-9]*.py", "sa_nr"), "standard", spec()),
    "instmon": (load("instmon_v[0-9]*.py", "sa_im"), "strict", spec()),
    "pibrary": (load("pibrary_v[0-9]*.py", "sa_pib"), "standard", spec(shadow="_read_pass_hash")),
    "wifimon": (load("wifimon_v[0-9]*.py", "sa_wm"), "standard",
                spec(issue="_session_new", check="_session_touch", fail="_auth_record_failure",
                     success="_auth_record_success", cookie="_COOKIE_NAME", shadow="_root_shadow_hash",
                     clock="monotonic", log="log")),
    "44helper": (load("44helper_v[0-9]*.py", "sa_44"), "strict",
                 spec(fail="_login_record_failure", success="_login_record_success", log="log")),
}
T0 = 2_000_000.0


class Tool:
    def __init__(self, key, mod, tier, sp):
        self.key, self.mod, self.tier, self.sp = key, mod, tier, sp

    def fn(self, name):
        return getattr(self.mod, self.sp[name])

    def reset(self):
        store = getattr(self.mod, self.sp["store"])
        store.clear()
        getattr(self.mod, "_lock_state").clear()
        self.mod._stamp_cache[0] = 0.0
        if self.key == "44helper":
            self.mod._SESSION_STORE_DIR = os.path.join(WORK, "44run")
            self.mod._SESSION_STORE_FILE = self.mod._SESSION_STORE_DIR + "/sessions.json"

    def issue(self):
        token, age = self.fn("issue")()
        return token, age

    def check(self, token):
        return self.fn("check")(token)

    def clock(self, t):
        return mock.patch.object(self.mod.time, self.sp["clock"], lambda: t)

    def at(self, t, fn):
        with self.clock(t):
            return fn()

    def wait(self, ip):
        if self.key == "44helper":
            until = self.mod._login_is_locked(ip)
            return max(0.0, until - self.mod.time.time()) if until else 0.0
        if self.key == "wifimon":
            return self.mod._lockout_remaining(ip)
        return self.mod._auth_lockout_remaining(ip)

    def quiet(self):
        return mock.patch.object(self.mod, self.sp["log"])


class Adoption(unittest.TestCase):
    def each(self):
        for key, (mod, tier, sp) in MODULES.items():
            with self.subTest(tool=key):
                tool = Tool(key, mod, tier, sp)
                tool.reset()
                yield tool

    def test_policy_and_first_cookie_age(self):
        for t in self.each():
            token, age = t.at(T0, t.issue)
            self.assertEqual(age, 12 * 3600 if t.tier == "standard" else 2 * 3600)
            self.assertEqual(len(token), 64)

    def test_tokens_are_stored_only_as_hashes(self):
        for t in self.each():
            token, _ = t.issue()
            store = getattr(t.mod, t.sp["store"])
            self.assertNotIn(token, store)
            self.assertIn(t.mod.sess_digest(token), store)

    def test_standard_has_no_hard_cap_and_strict_has_one(self):
        for t in self.each():
            token, _ = t.at(T0, t.issue)
            last = True
            step, count = (40000, 30) if t.tier == "standard" else (3000, 20)
            for i in range(1, count):
                last = t.at(T0 + i * step, lambda: t.check(token))
                if not last:
                    break
            self.assertEqual(last, t.tier == "standard")

    def test_idle_expiry(self):
        for t in self.each():
            idle = 12 * 3600 if t.tier == "standard" else 2 * 3600
            token, _ = t.at(T0, t.issue)
            self.assertTrue(t.at(T0 + idle - 60, lambda: t.check(token)))
            token2, _ = t.at(T0, t.issue)
            self.assertFalse(t.at(T0 + idle + 60, lambda: t.check(token2)))

    def test_renew_hint_about_hourly(self):
        for t in self.each():
            token, _ = t.at(T0, t.issue)

            def probe(when):
                return t.at(when, lambda: (t.check(token), getattr(t.mod._sess_local, "renew", 0)))
            self.assertEqual(probe(T0 + 300), (True, 0))
            ok, age = probe(T0 + 3700)
            self.assertTrue(ok)
            self.assertGreater(age, 0)
            self.assertEqual(probe(T0 + 3800), (True, 0))

    def test_logout_ends_every_session(self):
        for t in self.each():
            tokens = [t.issue()[0] for _ in range(3)]
            self.assertEqual(t.fn("revoke")(), 3)
            for tok in tokens:
                self.assertFalse(t.check(tok))

    def test_a_password_change_ends_every_session(self):
        for t in self.each():
            with mock.patch.object(t.mod, t.sp["shadow"], return_value="$6$aaa"):
                t.mod._stamp_cache[0] = 0.0
                token, _ = t.issue()
                self.assertTrue(t.check(token))
            with mock.patch.object(t.mod, t.sp["shadow"], return_value="$6$bbb"):
                t.mod._stamp_cache[0] = 0.0
                self.assertFalse(t.check(token))

    def test_unknown_and_empty_tokens_fail(self):
        for t in self.each():
            self.assertFalse(t.check(""))
            self.assertFalse(t.check(None))
            self.assertFalse(t.check("x" * 64))

    def test_at_most_fifty_sessions(self):
        for t in self.each():
            tokens = [t.issue()[0] for _ in range(55)]
            self.assertEqual(len(getattr(t.mod, t.sp["store"])), 50)
            self.assertFalse(t.check(tokens[0]))
            self.assertTrue(t.check(tokens[-1]))

    def test_lockout_five_mistakes_then_doubling(self):
        for t in self.each():
            waits = []
            clock = [T0]
            with mock.patch.object(t.mod.time, t.sp["clock"], lambda: clock[0]), t.quiet():
                for _ in range(8):
                    t.fn("fail")("10.0.0.9")
                    waits.append(round(t.wait("10.0.0.9")))
                self.assertEqual(waits, [0, 0, 0, 0, 5, 10, 20, 40])
                clock[0] += 41
                self.assertEqual(t.wait("10.0.0.9"), 0)
                t.fn("success")("10.0.0.9")
                t.fn("fail")("10.0.0.9")
                self.assertEqual(t.wait("10.0.0.9"), 0)

    def test_lockout_is_capped_at_five_minutes(self):
        for t in self.each():
            with t.clock(T0), t.quiet():
                for _ in range(30):
                    t.fn("fail")("10.0.0.7")
                self.assertEqual(round(t.wait("10.0.0.7")), 300)

    def test_cookie_names_and_flags(self):
        for t in self.each():
            name = getattr(t.mod, t.sp["cookie"])
            plain = t.mod.sess_cookie(name, "tok", 100, False)
            self.assertTrue(plain.startswith(name + "=tok"))
            self.assertIn("HttpOnly", plain)
            self.assertIn("SameSite=Strict", plain)
            self.assertNotIn("Secure", plain)
            secure = t.mod.sess_cookie(name, "tok", 100, True)
            self.assertTrue(secure.startswith("__Host-" + name + "=tok"))
            self.assertIn("; Secure", secure)
            self.assertEqual(t.mod.sess_token_from("a=1; __Host-%s=tok" % name, name), "tok")

    def test_44helper_keeps_sessions_across_a_restart_on_the_same_boot_only(self):
        mod, _, sp = MODULES["44helper"]
        t = Tool("44helper", mod, "strict", sp)
        t.reset()
        with mock.patch.object(mod, "_boot_id", return_value="boot-1"):
            token, _ = mod._issue_session()
            self.assertTrue(os.path.isfile(mod._SESSION_STORE_FILE))
            mod._sessions.clear()
            mod._sessions_load()
            self.assertTrue(mod._check_session(token))
        mod._sessions.clear()
        with mock.patch.object(mod, "_boot_id", return_value="boot-2"):
            mod._sessions_load()
            self.assertFalse(mod._check_session(token))

    def test_44helper_has_no_second_logout_everywhere_route(self):
        with open(MODULES["44helper"][0].__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("logout_all", src)
        self.assertNotIn("Log out all devices", src)

if __name__ == "__main__":
    unittest.main()
