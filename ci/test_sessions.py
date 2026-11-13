import ast
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(ROOT, "shared", "confio.py")

with open(SHARED, encoding="utf-8") as fh:
    _text = fh.read()
_tree = ast.parse(_text)
NAMES = [n.name for n in _tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith(("sess_", "lock_"))]
ns = {}
for _n in _tree.body:
    if isinstance(_n, ast.FunctionDef) and _n.name in NAMES:
        exec(compile(ast.get_source_segment(_text, _n), SHARED, "exec"), ns)

H = 3600.0
DAY = 24 * H


class Standalone(unittest.TestCase):
    def test_every_function_runs_with_only_the_session_functions_around_it(self):
        self.assertGreaterEqual(len(NAMES), 17)
        store = {}
        pol = ns["sess_policy"]("standard")
        token, age = ns["sess_new"](store, pol, 0.0)
        self.assertTrue(ns["sess_check"](store, token, pol, 1.0)[0])

    def test_used_by_lists_them_all_and_no_tool_carries_them_yet(self):
        used = next(ast.literal_eval(n.value) for n in _tree.body if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", "") == "USED_BY" for t in n.targets))
        for name in NAMES:
            self.assertIn(name, used, name)


class Policy(unittest.TestCase):
    def test_the_two_tiers(self):
        std, strict = ns["sess_policy"]("standard"), ns["sess_policy"]("strict")
        self.assertEqual((std["idle"], std["absolute"]), (12 * 3600, 0))
        self.assertEqual((strict["idle"], strict["absolute"]), (2 * 3600, 12 * 3600))
        self.assertEqual((std["renew"], strict["renew"], std["max"]), (3600, 3600, 50))

    def test_an_unknown_tier_is_refused(self):
        for bad in ("", "loose", None, "Standard"):
            with self.assertRaises(ValueError):
                ns["sess_policy"](bad)


class Sessions(unittest.TestCase):
    def setUp(self):
        self.std = ns["sess_policy"]("standard")
        self.strict = ns["sess_policy"]("strict")
        self.store = {}

    def new(self, pol=None, now=0.0, **kw):
        return ns["sess_new"](self.store, pol or self.std, now, **kw)

    def check(self, token, now, pol=None, **kw):
        return ns["sess_check"](self.store, token, pol or self.std, now, **kw)

    def test_a_token_is_random_and_only_its_hash_is_kept(self):
        a, _ = self.new()
        b, _ = self.new()
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), 64)
        self.assertNotIn(a, self.store)
        self.assertIn(ns["sess_digest"](a), self.store)
        self.assertNotIn(a, json.dumps(self.store))

    def test_a_good_token_passes_and_others_do_not(self):
        token, _ = self.new()
        self.assertEqual(self.check(token, 10.0)[0], True)
        for bad in ("", None, "x" * 64, token[:-1], token + "0"):
            self.assertFalse(self.check(bad, 10.0)[0], bad)

    def test_idle_time_slides_with_use(self):
        token, age = self.new()
        self.assertEqual(age, 12 * 3600)
        now = 0.0
        for _ in range(10):
            now += 11 * H
            self.assertTrue(self.check(token, now)[0])
        self.assertFalse(self.check(token, now + 12 * H)[0])

    def test_an_idle_session_ends_and_is_removed(self):
        token, _ = self.new()
        self.assertFalse(self.check(token, 12 * H + 1)[0])
        self.assertEqual(self.store, {})

    def test_a_probe_does_not_extend_the_session(self):
        token, _ = self.new()
        for hour in range(1, 12):
            self.assertTrue(self.check(token, hour * H, touch=False)[0])
        self.assertFalse(self.check(token, 12 * H + 1, touch=False)[0])

    def test_standard_has_no_hard_cap(self):
        token, _ = self.new()
        now = 0.0
        for _ in range(20):
            now += 10 * H
            self.assertTrue(self.check(token, now)[0])
        self.assertGreater(now, 7 * DAY)

    def test_strict_idles_at_two_hours_and_stops_at_twelve(self):
        token, age = self.new(self.strict)
        self.assertEqual(age, 2 * 3600)
        now = 0.0
        while now + 1.5 * H < 12 * H:
            now += 1.5 * H
            self.assertTrue(self.check(token, now, self.strict)[0], now)
        self.assertFalse(self.check(token, 12 * H, self.strict)[0])

    def test_strict_idle_ends_it_after_two_hours_without_use(self):
        token, _ = self.new(self.strict)
        self.assertFalse(self.check(token, 2 * H + 1, self.strict)[0])

    def test_the_cookie_age_never_outlives_the_hard_cap(self):
        token, _ = self.new(self.strict)
        for hour in (1.5, 3, 4.5, 6, 7.5, 9, 10.5):
            self.assertTrue(self.check(token, hour * H, self.strict)[0])
        ok, _renew, age = self.check(token, 11.5 * H - 1, self.strict)
        self.assertTrue(ok)
        self.assertEqual(age, 12 * H - (11.5 * H - 1))
        self.assertLess(age, 2 * H)

    def test_the_cookie_is_renewed_about_hourly_while_in_use(self):
        token, _ = self.new()
        flags = []
        for minute in (1, 30, 59, 61, 90, 119, 121, 200):
            flags.append(self.check(token, minute * 60.0)[1])
        self.assertEqual(flags, [False, False, False, True, False, False, True, True])

    def test_a_probe_never_asks_for_a_new_cookie(self):
        token, _ = self.new()
        self.assertEqual(self.check(token, 5 * H, touch=False)[1:], (False, 12 * 3600 - 5 * 3600))

    def test_changing_the_password_ends_the_session(self):
        stamp = ns["sess_stamp"]("$6$old$hash")
        token, _ = self.new(stamp=stamp)
        self.assertTrue(self.check(token, 1.0, stamp=stamp)[0])
        self.assertFalse(self.check(token, 2.0, stamp=ns["sess_stamp"]("$6$new$hash"))[0])
        self.assertEqual(self.store, {})

    def test_an_unreadable_password_hash_is_not_checked(self):
        token, _ = self.new(stamp=ns["sess_stamp"]("$6$old$hash"))
        self.assertTrue(self.check(token, 1.0, stamp=None)[0])

    def test_the_stamp_does_not_reveal_the_hash(self):
        stamp = ns["sess_stamp"]("$6$salt$secrethashvalue")
        self.assertEqual(len(stamp), 32)
        self.assertNotIn("secrethashvalue", stamp)
        self.assertEqual(ns["sess_stamp"](None), ns["sess_stamp"](""))

    def test_address_binding_is_optional(self):
        token, _ = self.new(ip="10.0.0.5")
        self.assertTrue(self.check(token, 1.0)[0])
        self.assertTrue(self.check(token, 2.0, ip="10.0.0.5")[0])
        self.assertFalse(self.check(token, 3.0, ip="10.0.0.9")[0])
        self.assertEqual(self.store, {})

    def test_logout_ends_every_session(self):
        tokens = [self.new(now=float(i))[0] for i in range(4)]
        self.assertEqual(ns["sess_drop_all"](self.store), 4)
        for t in tokens:
            self.assertFalse(self.check(t, 10.0)[0])
        self.assertEqual(ns["sess_drop_all"](self.store), 0)

    def test_one_session_can_be_dropped(self):
        a, _ = self.new()
        b, _ = self.new()
        self.assertTrue(ns["sess_drop"](self.store, a))
        self.assertFalse(ns["sess_drop"](self.store, a))
        self.assertFalse(ns["sess_drop"](self.store, None))
        self.assertTrue(self.check(b, 1.0)[0])

    def test_at_most_fifty_and_the_oldest_goes_first(self):
        tokens = [self.new(now=float(i))[0] for i in range(60)]
        self.assertEqual(len(self.store), 50)
        self.assertFalse(self.check(tokens[0], 100.0)[0])
        self.assertFalse(self.check(tokens[9], 100.0)[0])
        self.assertTrue(self.check(tokens[10], 100.0)[0])
        self.assertTrue(self.check(tokens[59], 100.0)[0])

    def test_expired_sessions_are_cleared_when_a_new_one_starts(self):
        for i in range(5):
            self.new(now=float(i))
        self.new(now=13 * H)
        self.assertEqual(len(self.store), 1)


class Restart(unittest.TestCase):
    def setUp(self):
        self.pol = ns["sess_policy"]("standard")

    def test_sessions_survive_a_restart_in_the_same_boot(self):
        store = {}
        a, _ = ns["sess_new"](store, self.pol, 1000.0, stamp="s", ip="")
        data = json.loads(json.dumps(ns["sess_dump"](store, "boot-1")))
        again = {}
        self.assertEqual(ns["sess_load"](again, data, "boot-1", 2000.0), 1)
        self.assertTrue(ns["sess_check"](again, a, self.pol, 2000.0, stamp="s")[0])

    def test_a_new_boot_starts_empty(self):
        store = {}
        ns["sess_new"](store, self.pol, 1000.0)
        data = ns["sess_dump"](store, "boot-1")
        again = {}
        self.assertEqual(ns["sess_load"](again, data, "boot-2", 2000.0), 0)
        self.assertEqual(again, {})

    def test_expired_sessions_are_not_restored(self):
        store = {}
        ns["sess_new"](store, self.pol, 0.0)
        data = ns["sess_dump"](store, "b")
        self.assertEqual(ns["sess_load"]({}, data, "b", 13 * H), 0)

    def test_the_file_holds_hashes_and_never_the_token(self):
        store = {}
        token, _ = ns["sess_new"](store, self.pol, 0.0)
        self.assertNotIn(token, json.dumps(ns["sess_dump"](store, "b")))

    def test_a_damaged_file_loads_nothing_and_does_not_fail(self):
        good = {"idle": 1e9, "abs": 0, "born": 0, "renew": 0, "stamp": "", "ip": ""}
        key = "a" * 64
        for bad in (None, [], "x", {}, {"v": 2, "boot": "b", "sessions": {}}, {"v": 1, "boot": "b", "sessions": []},
                    {"v": 1, "boot": "b", "sessions": {"short": good}},
                    {"v": 1, "boot": "b", "sessions": {key: dict(good, idle="soon")}},
                    {"v": 1, "boot": "b", "sessions": {key: dict(good, idle=True)}},
                    {"v": 1, "boot": "b", "sessions": {key: dict(good, stamp=5)}},
                    {"v": 1, "boot": "b", "sessions": {key: "x"}},
                    {"v": 1, "boot": "b", "sessions": {key: {"idle": 1e9}}}):
            store = {}
            self.assertEqual(ns["sess_load"](store, bad, "b", 0.0), 0, bad)
            self.assertEqual(store, {}, bad)

    def test_extra_fields_in_the_file_are_dropped(self):
        key = "b" * 64
        rec = {"idle": 1e9, "abs": 0, "born": 0, "renew": 0, "stamp": "", "ip": "", "admin": True}
        store = {}
        self.assertEqual(ns["sess_load"](store, {"v": 1, "boot": "b", "sessions": {key: rec}}, "b", 0.0), 1)
        self.assertNotIn("admin", store[key])


class Cookies(unittest.TestCase):
    def test_the_cookie_flags(self):
        c = ns["sess_cookie"]("nodetalker_session", "tok", 43200, False)
        self.assertEqual(c, "nodetalker_session=tok; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200")

    def test_on_tls_it_is_secure_and_host_prefixed(self):
        c = ns["sess_cookie"]("nodetalker_session", "tok", 600, True)
        self.assertTrue(c.startswith("__Host-nodetalker_session=tok;"))
        self.assertIn("; Secure", c)
        self.assertIn("Path=/", c)
        self.assertNotIn("Domain", c)

    def test_clearing_and_negative_ages(self):
        self.assertIn("Max-Age=0", ns["sess_cookie_clear"]("x_session", False))
        self.assertIn("Max-Age=0", ns["sess_cookie"]("x_session", "t", -5, False))
        self.assertTrue(ns["sess_cookie_clear"]("x_session", True).startswith("__Host-x_session=;"))

    def test_reading_the_token_back(self):
        f = ns["sess_token_from"]
        self.assertEqual(f("a=1; nodetalker_session=abc; asl_slow=on", "nodetalker_session"), "abc")
        self.assertEqual(f("__Host-nodetalker_session=xyz", "nodetalker_session"), "xyz")
        self.assertIsNone(f("xnodetalker_session=abc", "nodetalker_session"))
        self.assertIsNone(f("nodetalker_session=", "nodetalker_session"))
        self.assertIsNone(f("", "nodetalker_session"))
        self.assertIsNone(f(None, "nodetalker_session"))


class Lockout(unittest.TestCase):
    def setUp(self):
        self.state = {}

    def fail(self, ip="1.2.3.4", now=0.0, wan=False):
        return ns["lock_fail"](self.state, ip, now, wan)

    def test_four_mistakes_are_free_then_the_wait_doubles_to_five_minutes(self):
        waits = [self.fail(now=float(i)) for i in range(12)]
        self.assertEqual(waits[:4], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(waits[4:9], [5.0, 10.0, 20.0, 40.0, 80.0])
        self.assertEqual(waits[9:], [160.0, 300.0, 300.0])

    def test_the_wait_counts_down_and_ends(self):
        for i in range(5):
            self.fail(now=float(i))
        self.assertAlmostEqual(ns["lock_wait"](self.state, "1.2.3.4", 5.0), 4.0)
        self.assertEqual(ns["lock_wait"](self.state, "1.2.3.4", 100.0), 0.0)

    def test_a_good_login_forgets_the_mistakes(self):
        for i in range(5):
            self.fail(now=float(i))
        ns["lock_ok"](self.state, "1.2.3.4")
        self.assertEqual(ns["lock_wait"](self.state, "1.2.3.4", 5.0), 0.0)
        self.assertEqual(self.fail(now=6.0), 0.0)

    def test_addresses_are_independent(self):
        for i in range(6):
            self.fail("1.1.1.1", float(i))
        self.assertGreater(ns["lock_wait"](self.state, "1.1.1.1", 6.0), 0)
        self.assertEqual(ns["lock_wait"](self.state, "2.2.2.2", 6.0), 0.0)

    def test_twenty_failures_from_the_internet_block_all_internet_logins_for_ten_minutes(self):
        for i in range(20):
            self.fail("8.8.8.%d" % i, float(i), wan=True)
        self.assertGreater(ns["lock_wait"](self.state, "9.9.9.9", 21.0, wan=True), 500)
        self.assertEqual(ns["lock_wait"](self.state, "9.9.9.9", 21.0, wan=False), 0.0)
        self.assertEqual(ns["lock_wait"](self.state, "9.9.9.9", 700.0, wan=True), 0.0)

    def test_old_records_are_forgotten_and_the_table_is_bounded(self):
        self.fail("5.5.5.5", 0.0)
        self.fail("6.6.6.6", 4000.0)
        self.assertNotIn("5.5.5.5", self.state["ip"])
        for i in range(1100):
            self.fail("10.%d.%d.1" % (i // 250, i % 250), 5000.0 + i)
        self.assertLessEqual(len(self.state["ip"]), 1000)

    def test_a_very_long_run_of_mistakes_cannot_overflow(self):
        for i in range(2000):
            wait = self.fail(now=float(i))
        self.assertLessEqual(wait, 300.0)


if __name__ == "__main__":
    unittest.main()
