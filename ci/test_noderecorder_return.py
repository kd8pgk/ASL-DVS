import glob
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import unittest
from datetime import timedelta
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="nr_return_")
os.environ["NODERECORDER_CONFIG_DIR"] = os.path.join(WORK, "nr")


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:4]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("nr_return_under_test", newest("noderecorder_v[0-9]*.py"))
nr = importlib.util.module_from_spec(spec)
sys.modules["nr_return_under_test"] = nr
spec.loader.exec_module(nr)

HOME = {"mode": "ASL", "num": "2000"}
OTHER = {"mode": "ASL", "num": "3000"}
SVX_TG = {"mode": "SVX", "num": "240"}


def mk_entry(eid, start, end, target=None, **extra):
    raw = {"id": eid, "name": eid, "days": [0, 1, 2, 3, 4, 5, 6], "start": start, "end": end,
           "target": target or dict(OTHER), "format": "pcm", "kind": "regular", "date": "", "enabled": True}
    raw.update(extra)
    return nr.schedule_norm_entry(raw, check_target=False)


class WithReturnFile(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(WORK, "return_%s.json" % id(self))
        p = mock.patch.object(nr, "RETURN_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)

    def write(self, enabled, target):
        with open(self.path, "w") as f:
            json.dump({"version": 1, "enabled": enabled, "target": target}, f)


class Store(WithReturnFile):
    def test_there_is_no_return_link_until_one_is_saved(self):
        self.assertEqual(nr.return_load(), {"enabled": False, "target": None})
        self.assertEqual(nr.return_view()["name"], "")

    def test_turning_it_on_needs_a_link(self):
        d = nr.return_set({"enabled": True, "target": {"mode": "ASL", "num": ""}})
        self.assertFalse(d["ok"])
        self.assertIn("Pick the link", d["error"])
        self.assertFalse(os.path.exists(self.path))

    def test_a_link_is_checked_like_a_schedule_target(self):
        for bad in ({"mode": "SVX", "num": "abc"}, {"mode": "NOPE", "num": "1"}, {"mode": "ASL", "num": "12x"}):
            d = nr.return_set({"enabled": True, "target": bad})
            self.assertFalse(d["ok"], bad)
        self.assertFalse(os.path.exists(self.path))

    def test_a_good_link_is_saved_and_named(self):
        d = nr.return_set({"enabled": True, "target": dict(HOME, label="Home hub", junk="x")})
        self.assertTrue(d["ok"], d)
        self.assertEqual(nr.return_load(), {"enabled": True, "target": {"mode": "ASL", "num": "2000", "label": "Home hub"}})
        self.assertEqual(d["name"], "ASL 2000")
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o644")

    def test_svxlink_can_be_the_return_link(self):
        self.assertTrue(nr.return_set({"enabled": True, "target": dict(SVX_TG)})["ok"])
        self.assertEqual(nr.return_load()["target"]["mode"], "SVX")
        self.assertEqual(nr.return_view()["name"], "SVX 240")

    def test_turning_it_off_keeps_the_link_for_later(self):
        nr.return_set({"enabled": True, "target": dict(HOME)})
        d = nr.return_set({"enabled": False})
        self.assertTrue(d["ok"])
        got = nr.return_load()
        self.assertFalse(got["enabled"])
        self.assertEqual((got["target"]["mode"], got["target"]["num"]), ("ASL", "2000"))

    def test_a_broken_file_means_no_return_link(self):
        with open(self.path, "w") as f:
            f.write("{nope")
        self.assertEqual(nr.return_load(), {"enabled": False, "target": None})

    def test_a_file_that_is_on_without_a_link_is_off(self):
        self.write(True, None)
        self.assertFalse(nr.return_load()["enabled"])

    def test_the_post_route_and_the_schedule_view_carry_it(self):
        fn, errors = nr._POST_ACTIONS["/api/schedule/return"]
        self.assertIs(fn, nr.return_set)
        self.assertIn(ValueError, errors)
        nr.return_set({"enabled": True, "target": dict(HOME)})
        with mock.patch.object(nr, "schedule_load", lambda: {"entries": [], "error": ""}):
            v = nr.schedule_view()
        self.assertEqual((v["return"]["target"]["mode"], v["return"]["target"]["num"]), ("ASL", "2000"))
        self.assertTrue(v["return"]["enabled"])


class Decision(WithReturnFile):
    def setUp(self):
        super().setUp()
        self.now = nr.sched_now().replace(second=0, microsecond=0)
        self.entries = []
        p = mock.patch.object(nr, "schedule_load", lambda: {"entries": self.entries, "error": ""})
        p.start()
        self.addCleanup(p.stop)
        self.run_entry = mk_entry("run", (self.now - timedelta(minutes=30)).strftime("%H:%M"), (self.now + timedelta(minutes=1)).strftime("%H:%M"))
        self.entries = [self.run_entry]

    def at(self, minutes, **kw):
        s = self.now + timedelta(minutes=minutes)
        return mk_entry(kw.pop("eid", "next"), s.strftime("%H:%M"), (s + timedelta(minutes=30)).strftime("%H:%M"), **kw)

    def decide(self, blocked=""):
        return nr.return_decision(self.run_entry, self.now, None, blocked)

    def test_nothing_without_a_return_link(self):
        self.assertEqual(self.decide()[0], "none")
        self.write(False, dict(HOME))
        self.assertEqual(self.decide()[0], "none")

    def test_it_goes_back_when_nothing_else_is_near(self):
        self.write(True, dict(HOME))
        self.assertEqual(self.decide(), ("go", "ASL 2000"))

    def test_a_hand_stop_a_shutdown_or_a_special_means_no_return(self):
        self.write(True, dict(HOME))
        for why in ("stopped by hand", "Node Recorder is stopping", "a special recording took over"):
            self.assertEqual(self.decide(why), ("skip", why))

    def test_the_same_link_is_kept(self):
        self.write(True, dict(OTHER))
        action, text = self.decide()
        self.assertEqual(action, "keep")
        self.assertIn("ASL 3000", text)

    def test_a_recording_that_starts_within_ten_minutes_is_not_interrupted_by_a_return(self):
        self.write(True, dict(HOME))
        self.entries.append(self.at(5, target=dict(SVX_TG)))
        action, text = self.decide()
        self.assertEqual(action, "skip")
        self.assertIn("within 10 minutes", text)

    def test_back_to_back_recordings_do_not_return_in_between(self):
        self.write(True, dict(HOME))
        self.entries.append(self.at(1, eid="b2b"))
        self.assertEqual(self.decide()[0], "skip")

    def test_one_that_starts_later_does_not_stop_the_return(self):
        self.write(True, dict(HOME))
        self.entries.append(self.at(40))
        self.assertEqual(self.decide()[0], "go")

    def test_an_entry_that_is_off_does_not_count(self):
        self.write(True, dict(HOME))
        self.entries.append(self.at(5, enabled=False))
        self.assertEqual(self.decide()[0], "go")

    def test_a_special_that_starts_soon_counts(self):
        self.write(True, dict(HOME))
        s = self.now + timedelta(minutes=4)
        self.entries.append(mk_entry("sp", s.strftime("%H:%M"), (s + timedelta(minutes=20)).strftime("%H:%M"), kind="special",
                                     date=s.strftime("%Y-%m-%d"), days=[]))
        self.assertEqual(self.decide()[0], "skip")

    def test_the_window_of_the_recording_that_just_ended_does_not_block_its_own_return(self):
        self.write(True, dict(HOME))
        self.assertEqual(self.decide()[0], "go")


class Ending(WithReturnFile):
    def setUp(self):
        super().setUp()
        for name, val in (("LINK_CHECK_SEC", 0.05), ("SCHEDULE_STATE_PATH", os.path.join(WORK, "state_%s.json" % id(self)))):
            p = mock.patch.object(nr, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.calls = []
        self.give_ok = True
        self.now = nr.sched_now()
        near_end = (self.now + timedelta(minutes=1)).strftime("%H:%M")
        self.short = mk_entry("a", (self.now - timedelta(minutes=30)).strftime("%H:%M"), near_end)
        self.long = mk_entry("a", (self.now - timedelta(minutes=2)).strftime("%H:%M"), (self.now + timedelta(minutes=58)).strftime("%H:%M"))
        self.entries = [self.short]
        test = self

        class Act(nr.RealActions):
            def connect(self, entry):
                test.calls.append("connect")
                return True, "", None

            def link_alive(self, entry):
                return True

            def healthy(self, entry):
                return True, ""

            def start(self, entry, window):
                test.calls.append("start")
                return True, "", "x.wav"

            def stop(self):
                test.calls.append("stop")
                return True, "", None

        self.Act = Act
        for name, fn in (("schedule_load", lambda: {"entries": self.entries, "error": ""}),
                         ("_special_remove", lambda eid: None),
                         ("tune_disconnect", lambda t: self.calls.append("drop") or {"ok": True}),
                         ("tune_connect", self.fake_connect)):
            p = mock.patch.object(nr, name, fn)
            p.start()
            self.addCleanup(p.stop)
        self.sched = nr.Scheduler(real_actions=Act)
        self.sched.sleep = lambda s: time.sleep(min(s, 0.05))
        self.addCleanup(self.finish)

    def fake_connect(self, target):
        self.calls.append("return:" + target["num"])
        return {"ok": self.give_ok, "message": "" if self.give_ok else "Asterisk is busy"}

    def finish(self):
        self.sched.stop.set()
        self.sched.run_abort.set()
        self.sched.shutdown(5)

    def drive(self, until, secs=15):
        end = time.time() + secs
        while time.time() < end:
            self.sched.tick(self.now)
            if until():
                return True
            time.sleep(0.05)
        return False

    def finished(self):
        return self.sched.state == "idle" and bool(self.sched.done)

    def test_it_returns_to_the_link_after_the_recording(self):
        self.write(True, dict(HOME))
        self.assertTrue(self.drive(self.finished))
        self.assertEqual(self.calls, ["connect", "start", "stop", "drop", "return:2000"])
        self.assertEqual(self.sched.results[-1]["result"], "ok")

    def test_nothing_changes_when_it_is_off(self):
        self.write(False, dict(HOME))
        self.assertTrue(self.drive(self.finished))
        self.assertEqual(self.calls, ["connect", "start", "stop", "drop"])

    def test_the_same_link_is_not_dropped_and_not_linked_again(self):
        self.write(True, dict(OTHER))
        self.assertTrue(self.drive(self.finished))
        self.assertEqual(self.calls, ["connect", "start", "stop"])

    def test_the_next_recording_takes_over_when_it_starts_soon(self):
        self.write(True, dict(HOME))
        s = self.now + timedelta(minutes=6)
        self.entries.append(mk_entry("b", s.strftime("%H:%M"), (s + timedelta(minutes=30)).strftime("%H:%M")))
        self.assertTrue(self.drive(self.finished))
        self.assertEqual(self.calls, ["connect", "start", "stop", "drop"])

    def test_a_failed_return_is_reported_but_the_recording_stays_ok(self):
        self.write(True, dict(HOME))
        self.give_ok = False
        self.assertTrue(self.drive(self.finished))
        row = self.sched.results[-1]
        self.assertEqual(row["result"], "ok")
        self.assertIn("return link failed: Asterisk is busy", row["detail"])

    def test_a_stop_by_hand_leaves_the_link_to_the_user(self):
        self.write(True, dict(HOME))
        self.entries = [self.long]
        self.assertTrue(self.drive(lambda: self.sched.state == "recording"))
        self.sched.stop_by_hand()
        self.assertTrue(self.drive(lambda: self.sched.state == "idle" and self.sched.done))
        self.assertEqual(self.calls, ["connect", "start", "stop", "drop"])

    def test_a_hand_stop_still_drops_the_link_even_when_it_is_the_return_link(self):
        self.write(True, dict(OTHER))
        self.entries = [self.long]
        self.assertTrue(self.drive(lambda: self.sched.state == "recording"))
        self.sched.stop_by_hand()
        self.assertTrue(self.drive(lambda: self.sched.state == "idle" and self.sched.done))
        self.assertEqual(self.calls, ["connect", "start", "stop", "drop"])

    def test_a_shutdown_does_not_return(self):
        self.write(True, dict(HOME))
        self.sched.stop.set()
        self.assertFalse(self.sched._keep_link(self.short))
        self.write(True, dict(OTHER))
        self.assertFalse(self.sched._keep_link(self.short))

    def test_record_now_never_returns(self):
        self.write(True, dict(HOME))
        engine = mock.Mock()
        engine.healthy.return_value = (True, "")
        engine.start.return_value = (True, "", "m.wav")
        engine.stop.return_value = (True, "", None)
        with mock.patch.object(nr, "ENGINE", engine), mock.patch.object(nr, "schedule_load", lambda: {"entries": [], "error": ""}):
            window = (self.now, self.now + timedelta(minutes=5))
            ok, _ = self.sched.start_manual(dict(self.short, id="manual", name="manual"), window)
            self.assertTrue(ok)
            self.assertTrue(self.drive(lambda: self.sched.state == "recording"))
            self.sched.stop_by_hand()
            self.assertTrue(self.drive(lambda: self.sched.state == "idle" and self.sched.thread is not None and not self.sched.thread.is_alive()))
        self.assertNotIn("return:2000", self.calls)

    def test_the_state_shows_the_return(self):
        self.assertIn("returning", nr._JS)


class DryRun(WithReturnFile):
    def body(self):
        now = nr.sched_now()
        return {"entry": {"name": "dry", "days": [0, 1, 2, 3, 4, 5, 6], "start": (now + timedelta(hours=2)).strftime("%H:%M"),
                          "end": (now + timedelta(hours=3)).strftime("%H:%M"), "target": dict(OTHER), "format": "pcm"}}

    def test_the_dry_run_shows_the_return_step(self):
        self.write(True, dict(HOME))
        with mock.patch.object(nr, "schedule_load", lambda: {"entries": [], "error": ""}), \
                mock.patch.object(nr, "_tune_fav", side_effect=lambda t: dict(t, label=t.get("label", ""))), \
                mock.patch.object(nr, "fav_name", lambda f: f"{f['mode']} {f['num']}"), \
                mock.patch.object(nr, "fav_target", lambda f: f["mode"] + f["num"]):
            d = nr.schedule_dry_run(self.body())
        self.assertEqual(d["steps"][-1]["step"], "return")
        self.assertIn("would return to ASL 2000", d["steps"][-1]["msg"])

    def test_no_return_step_when_it_is_off(self):
        self.write(False, dict(HOME))
        with mock.patch.object(nr, "schedule_load", lambda: {"entries": [], "error": ""}):
            d = nr.schedule_dry_run(self.body())
        self.assertNotIn("return", [s["step"] for s in d["steps"]])


class Page(unittest.TestCase):
    def test_the_card_sits_under_the_schedule_card_on_the_schedule_tab(self):
        html = nr._HTML_TEMPLATE
        tab = html.split('<section id="tab-connect"', 1)[1].split("</section>", 1)[0]
        self.assertLess(tab.index('id="cd-sched"'), tab.index('id="cd-return"'))
        for ident in ("rl-on", "rl-mode", "rl-pick", "rl-num", "rl-net", "rl-mod", "rl-save", "rl-msg", "rl-now"):
            self.assertIn(f'id="{ident}"', tab)
        self.assertIn('type="checkbox" id="rl-on"', tab)

    def test_the_script_saves_and_shows_it(self):
        js = nr._JS
        self.assertIn("'/api/schedule/return'", js)
        self.assertIn("rlShow(d.return)", js)
        self.assertIn("SVX: {num: 'Talkgroup'}", js)
        self.assertIn("'SVX'", js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
