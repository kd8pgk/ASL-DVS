import glob
import hashlib
import http.client
import json
import threading
import importlib.util
import io
import os
import re
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="instmon_tools_")
for key, sub in (("INSTMON_CONFIG_DIR", "config"), ("INSTMON_LIBRARY_DIR", "library"), ("INSTMON_SUITELOG", "run/suitelog.jsonl"),
                 ("INSTMON_SUITELOG_FLAG", "run/suitelog.on")):
    os.environ[key] = os.path.join(WORK, sub)
os.environ["INSTMON_RECORDER_STATUS_URL"] = "http://127.0.0.1:9/x"


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("instmon_tools_under_test", os.environ.get("INSTMON_TOOLS_FILE") or newest("instmon_v[0-9]*.py"))
im = importlib.util.module_from_spec(spec)
sys.modules["instmon_tools_under_test"] = im
spec.loader.exec_module(im)


def run_result(stdout="", stderr="", rc=0):
    return mock.Mock(returncode=rc, stdout=stdout, stderr=stderr)


class Boot(unittest.TestCase):
    def test_states_are_read_in_one_call(self):
        out = "Id=sysmon.service\nUnitFileState=enabled\n\nId=wifimon.service\nUnitFileState=disabled\n"
        with mock.patch.object(im.subprocess, "run", return_value=run_result(out)) as run:
            got = im._boot_states(["sysmon", "wifimon", "pibrary"])
        self.assertEqual(got, {"sysmon": "enabled", "wifimon": "disabled", "pibrary": ""})
        self.assertEqual(run.call_count, 1)
        self.assertEqual(im._boot_states([]), {})

    def test_refusals(self):
        self.assertEqual(im.set_boot("nope", True)[0], 400)
        self.assertEqual(im.set_boot("instmon", False)[0], 400)
        self.assertEqual(im.set_boot("sysmon", "yes")[0], 400)
        with mock.patch.object(im, "resolve_installed_target", return_value=os.path.join(WORK, "missing.py")):
            status, payload = im.set_boot("sysmon", True)
        self.assertEqual(status, 400)
        self.assertIn("not installed", payload["message"])

    def test_enable_and_disable(self):
        target = os.path.join(WORK, "sysmon_installed.py")
        open(target, "w").close()
        calls = []

        def fake(cmd, **kw):
            calls.append(cmd[:2])
            if cmd[1] == "show":
                return run_result(f"Id=sysmon.service\nUnitFileState={state[0]}\n")
            state[0] = "enabled" if cmd[1] == "enable" else "disabled"
            return run_result()

        state = ["disabled"]
        with mock.patch.object(im, "resolve_installed_target", return_value=target), \
                mock.patch.object(im.subprocess, "run", side_effect=fake):
            status, payload = im.set_boot("sysmon", True)
            self.assertEqual((status, payload["boot"]), (200, "enabled"))
            self.assertIn(["systemctl", "enable"], calls)
            status, payload = im.set_boot("sysmon", False)
            self.assertEqual((status, payload["boot"]), (200, "disabled"))
            self.assertIn("not start", payload["message"])

    def test_a_change_that_does_not_take_is_reported(self):
        target = os.path.join(WORK, "wifimon_installed.py")
        open(target, "w").close()

        def fake(cmd, **kw):
            if cmd[1] == "show":
                return run_result("Id=wifimon.service\nUnitFileState=masked\n")
            return run_result(stderr="Unit wifimon.service is masked.", rc=1)

        with mock.patch.object(im, "resolve_installed_target", return_value=target), \
                mock.patch.object(im.subprocess, "run", side_effect=fake):
            status, payload = im.set_boot("wifimon", True)
        self.assertEqual(status, 500)
        self.assertIn("masked", payload["message"])


class Journal(unittest.TestCase):
    def test_only_known_tools_and_lines_are_capped(self):
        self.assertEqual(im.service_journal("../etc")[0], 400)
        with mock.patch.object(im.subprocess, "run", return_value=run_result("2026-11-11 a\x1b[31mred\n")) as run:
            status, payload = im.service_journal("sysmon", "9999")
        self.assertEqual(status, 200)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:3], ["journalctl", "-u", "sysmon.service"])
        self.assertEqual(cmd[cmd.index("-n") + 1], str(im.JOURNAL_LINES_MAX))
        self.assertNotIn("\x1b", payload["text"])
        with mock.patch.object(im.subprocess, "run", return_value=run_result("x")) as run:
            im.service_journal("sysmon", "junk")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("-n") + 1], "120")

    def test_a_failing_journalctl_is_reported(self):
        with mock.patch.object(im.subprocess, "run", return_value=run_result(stderr="No journal files", rc=1)):
            status, payload = im.service_journal("sysmon")
        self.assertEqual(status, 500)
        self.assertIn("No journal files", payload["message"])


class Disk(unittest.TestCase):
    def test_summary_names_free_space(self):
        d = im.disk_summary()
        self.assertIn("free of", d["text"])
        self.assertIsInstance(d["low"], bool)
        low = mock.Mock(total=10 * 1024 ** 3, free=200 * 1024 ** 2)
        with mock.patch.object(im.shutil, "disk_usage", return_value=low):
            self.assertTrue(im.disk_summary()["low"])
        self.assertIn('id="home-disk"', im.disk_html())


class Restore(unittest.TestCase):
    def setUp(self):
        im.ensure_dirs()
        self.lib = im.LIB_SUBDIRS

    def zip_of(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in files.items():
                zf.writestr(name, data)
        return buf.getvalue()

    def test_adds_only_what_is_missing(self):
        with open(os.path.join(self.lib["scripts"], "same_v1.sh"), "w") as f:
            f.write("same\n")
        with open(os.path.join(self.lib["scripts"], "mine_v1.sh"), "w") as f:
            f.write("this node's copy\n")
        data = self.zip_of({
            "sysmon/sysmon_v9_9_9_20260101.py": "print('restored')\n",
            "scripts/same_v1.sh": "same\n",
            "scripts/mine_v1.sh": "the backup's copy\n",
            "../evil.py": "x",
            "sysmon/../../evil2.py": "x",
            "unknown/a.py": "x",
            "sysmon/.hidden.py": "x",
            "locks.json": "{}",
            "sysmon/sub/a.py": "x",
        })
        status, payload = im.backup_restore(data)
        self.assertEqual(status, 200)
        self.assertEqual(payload["added"], ["sysmon/sysmon_v9_9_9_20260101.py"])
        self.assertEqual(payload["same"], 1)
        self.assertEqual(payload["kept"], ["scripts/mine_v1.sh"])
        self.assertEqual(len(payload["skipped"]), 6)
        with open(os.path.join(self.lib["sysmon"], "sysmon_v9_9_9_20260101.py")) as f:
            self.assertEqual(f.read(), "print('restored')\n")
        with open(os.path.join(self.lib["scripts"], "mine_v1.sh")) as f:
            self.assertEqual(f.read(), "this node's copy\n")
        for bad in ("evil.py", "evil2.py"):
            for d in (WORK, os.path.dirname(im.LIBRARY_DIR), im.LIBRARY_DIR):
                self.assertFalse(os.path.exists(os.path.join(d, bad)))
        self.assertFalse(os.path.exists(os.path.join(self.lib["sysmon"], "sub")))
        self.assertIn("Restored 1 file", payload["message"])

    def test_a_backup_made_here_round_trips(self):
        name = "wifimon_v5_1_0_20260101.py"
        path = os.path.join(self.lib["wifimon"], name)
        with open(path, "w") as f:
            f.write("print('wifimon')\n")
        with open(path) as f:
            data = self.zip_of({"wifimon/" + name: f.read()})
        os.remove(path)
        status, payload = im.backup_restore(data)
        self.assertEqual((status, payload["added"]), (200, ["wifimon/" + name]))
        with open(path, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), hashlib.sha256(b"print('wifimon')\n").hexdigest())

    def test_bad_input_is_refused(self):
        self.assertEqual(im.backup_restore(b"not a zip")[0], 400)
        with mock.patch.object(im, "BACKUP_RESTORE_MAX_FILES", 2):
            self.assertEqual(im.backup_restore(self.zip_of({"scripts/a.sh": "1", "scripts/b.sh": "2", "scripts/c.sh": "3"}))[0], 400)
        with mock.patch.object(im, "MAX_UPLOAD_BYTES", 10):
            self.assertEqual(im.backup_restore(self.zip_of({"scripts/a.sh": "x" * 50}))[0], 400)


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = mock.patch.object(im, "_check_session", lambda token: True)
        cls.patch.start()
        cls.srv = im.http.server.ThreadingHTTPServer(("127.0.0.1", 0), im.InstmonHandler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.patch.stop()

    def post_zip(self, data, name="backup.zip", xrw=True):
        b = "XyZbound"
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                f"Content-Type: application/zip\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={b}"}
        if xrw:
            headers["X-Requested-With"] = "XMLHttpRequest"
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request("POST", "/api/backup/restore", body, headers)
        r = c.getresponse()
        out = (r.status, json.loads(r.read() or b"{}"))
        c.close()
        return out

    def test_restore_over_http(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("scripts/served_v1.sh", "echo hi\n")
        status, payload = self.post_zip(buf.getvalue())
        self.assertEqual(status, 200)
        self.assertEqual(payload["added"], ["scripts/served_v1.sh"])
        self.assertEqual(self.post_zip(buf.getvalue(), xrw=False)[0], 403)
        self.assertEqual(self.post_zip(buf.getvalue(), name="backup.tar")[0], 400)

    def test_journal_over_http(self):
        with mock.patch.object(im.subprocess, "run", return_value=run_result("hello\n")):
            c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
            c.request("GET", "/api/journal?service=sysmon&lines=50")
            r = c.getresponse()
            data = json.loads(r.read())
            c.close()
        self.assertEqual((r.status, data["text"], data["lines"]), (200, "hello\n", 50))


class AutoCheck(unittest.TestCase):
    def setUp(self):
        try:
            os.remove(im._AUTOCHECK_PATH)
        except OSError:
            pass

    def test_setting_is_saved(self):
        self.assertEqual(im.autocheck_set("yes")[0], 400)
        self.assertFalse(im.autocheck_get()["on"])
        self.assertEqual(im.autocheck_set(True)[0], 200)
        self.assertTrue(im.autocheck_get()["on"])
        self.assertEqual(im.autocheck_set(False)[1]["on"], False)

    def test_runs_once_a_day_and_only_when_on(self):
        with mock.patch.object(im, "gh_start_check", return_value=(True, "")) as start, \
                mock.patch.object(im, "full_update_running", return_value=False):
            self.assertFalse(im.autocheck_tick(now=1_000_000))
            im.autocheck_set(True)
            self.assertTrue(im.autocheck_tick(now=1_000_000))
            start.assert_called_once_with(auto=True)
            self.assertEqual(im.autocheck_get()["last"], 1_000_000)
            self.assertFalse(im.autocheck_tick(now=1_000_000 + 3600))
            self.assertTrue(im.autocheck_tick(now=1_000_000 + im.AUTOCHECK_EVERY_SEC))
        with mock.patch.object(im, "gh_start_check", return_value=(True, "")) as start, \
                mock.patch.object(im, "full_update_running", return_value=True):
            self.assertFalse(im.autocheck_tick(now=9_000_000))
            start.assert_not_called()

    def test_a_refused_start_is_tried_again(self):
        im.autocheck_set(True)
        with mock.patch.object(im, "gh_start_check", return_value=(False, "busy")), \
                mock.patch.object(im, "full_update_running", return_value=False):
            self.assertFalse(im.autocheck_tick(now=5_000_000))
        self.assertEqual(im.autocheck_get()["last"], 0.0)

    def test_the_daily_check_downloads_nothing(self):
        for auto, calls in ((True, 0), (False, 1)):
            with mock.patch.object(im, "_gh_collect_full", return_value=([], 0, [])), \
                    mock.patch.object(im, "_gh_fetch_missing") as fetch, \
                    mock.patch.object(im, "_docs_refresh_remote") as docs, \
                    mock.patch.object(im, "full_update_preview") as preview:
                im._gh_check_bg(None, auto)
            self.assertEqual((fetch.call_count, docs.call_count, preview.call_count), (calls, calls, 1), auto)

    def test_home_line_counts_updates(self):
        with im._gh_lock:
            saved = dict(im._gh_state)
            im._gh_state.update(phase="done", checked_at="2026-11-11 10:00",
                                entries=[{"status": "update"}, {"status": "missing"}, {"status": "up_to_date"}])
        try:
            u = im.gh_updates_summary()
            self.assertEqual(u["count"], 2)
            self.assertIn("2 update(s)", u["text"])
            with im._gh_lock:
                im._gh_state.update(entries=[{"status": "up_to_date"}])
            self.assertIn("up to date", im.gh_updates_summary()["text"])
            with im._gh_lock:
                im._gh_state.update(phase="checking")
            self.assertEqual(im.gh_updates_summary(), {"count": 0, "text": ""})
        finally:
            with im._gh_lock:
                im._gh_state.clear()
                im._gh_state.update(saved)


class Login(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = im.http.server.ThreadingHTTPServer(("127.0.0.1", 0), im.InstmonHandler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def call(self, method, path, body=None, xrw=True):
        headers = {"Content-Type": "application/json"}
        if xrw:
            headers["X-Requested-With"] = "XMLHttpRequest"
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request(method, path, body, headers)
        r = c.getresponse()
        out = (r.status, json.loads(r.read() or b"{}"))
        c.close()
        return out

    def test_login_needs_the_header_and_errors_carry_a_message(self):
        with mock.patch.object(im, "_verify_root_password", return_value=False), \
                mock.patch.object(im, "_record_auth_failure"):
            status, payload = self.call("POST", "/api/login", json.dumps({"password": "x"}), xrw=False)
            self.assertEqual(status, 403)
            self.assertIn("message", payload)
            status, payload = self.call("POST", "/api/login", json.dumps({"password": "x"}))
            self.assertEqual(status, 401)
            self.assertEqual(payload["message"], "Invalid password")
        with mock.patch.object(im, "_check_session", lambda token: True):
            status, payload = self.call("GET", "/api/no-such-route")
        self.assertEqual(status, 404)
        self.assertIn("message", payload)


class Page(unittest.TestCase):
    def card(self, **kw):
        c = {"name": "SysMon", "service": "sysmon", "port": 9999, "scheme": "http", "category": "sysmon",
             "state": "active", "listening": True, "version": "6.0.0", "installed": True, "user_stopped": False, "boot": "enabled"}
        c.update(kw)
        with mock.patch.object(im, "render_app_card_html", return_value=""), \
                mock.patch.object(im, "render_confgetter_card_html", return_value=""):
            return im.render_components_html([c])

    def test_card_has_log_and_boot_switch(self):
        html = self.card()
        self.assertIn('class="svc-log-btn" data-service="sysmon"', html)
        self.assertIn('class="boot-cb" data-service="sysmon" data-name="SysMon" checked', html)
        self.assertNotIn(" checked", self.card(boot="disabled").split('class="boot-cb"')[1].split(">")[0])
        self.assertNotIn("boot-cb", self.card(boot="static"))
        self.assertNotIn("boot-cb", self.card(installed=False))
        self.assertNotIn("svc-log-btn", self.card(installed=False))
        self.assertNotIn("boot-cb", self.card(category="instmon", service="instmon", name="instmon"))

    def test_page_has_the_new_controls(self):
        html = im.render_page()
        home = html[html.index('id="tabp-home"'):html.index('id="tabp-tools"')]
        files = html[html.index('id="tabp-files"'):html.index('id="tabp-disk"')]
        self.assertIn('id="home-disk"', home)
        self.assertIn('id="bk-restore-btn"', files)
        self.assertIn('id="svclog-overlay" hidden', html)
        self.assertIn('id="home-updates"', home)
        self.assertIn('id="autocheck-cb"', home)
        self.assertIn("'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},\n      body: JSON.stringify({password", html)
        for n in ("function svcLogOpen", "function bkRestore", "action: 'set_boot'", "homeDisk(data.disk)", "toolsInit();",
                  "action: 'gh_autocheck'", "homeUpdates(data.gh_updates)"):
            self.assertIn(n, html)

    def test_routes_and_action_are_registered(self):
        self.assertIn("/api/journal", im._GET_ROUTES)
        self.assertIn("/api/backup/restore", im._POST_ROUTES)
        self.assertIn("set_boot", im._ACTION_HANDLERS)
        self.assertIn("gh_autocheck", im._ACTION_HANDLERS)


class SessionsAndFullUpdate(unittest.TestCase):
    def setUp(self):
        im._revoke_all_sessions()

    def test_an_old_session_is_kept_while_a_full_update_runs(self):
        token = im._issue_session()
        with im._sessions_lock:
            im._sessions[token] = 1.0
        with mock.patch.object(im, "full_update_running", return_value=True):
            self.assertTrue(im._check_session(token))
            self.assertGreater(im._sessions[token], 1_000_000.0)
        with mock.patch.object(im, "full_update_running", return_value=False):
            self.assertTrue(im._check_session(token))

    def test_an_old_session_expires_when_no_update_runs(self):
        token = im._issue_session()
        with im._sessions_lock:
            im._sessions[token] = 1.0
        with mock.patch.object(im, "full_update_running", return_value=False):
            self.assertFalse(im._check_session(token))

    def test_a_login_during_an_update_does_not_drop_held_sessions(self):
        old = im._issue_session()
        with im._sessions_lock:
            im._sessions[old] = 1.0
        with mock.patch.object(im, "full_update_running", return_value=True):
            im._issue_session()
            self.assertIn(old, im._sessions)

    def test_starting_a_full_update_drops_sessions_that_already_ran_out(self):
        stale = im._issue_session()
        live = im._issue_session()
        with im._sessions_lock:
            im._sessions[stale] = 1.0
        im._prune_sessions()
        with mock.patch.object(im, "full_update_running", return_value=True):
            self.assertFalse(im._check_session(stale))
            self.assertTrue(im._check_session(live))

    def test_finishing_a_full_update_signs_everyone_out(self):
        tokens = [im._issue_session() for _ in range(3)]
        with mock.patch.object(im, "_fu_save"), mock.patch.object(im, "_gh_event"), \
                mock.patch.object(im, "_fu_refresh_plan"):
            im._fu_finish()
        for t in tokens:
            self.assertFalse(im._check_session(t))

    def test_no_session_means_no_logout_note(self):
        with mock.patch.object(im, "_fu_save"), mock.patch.object(im, "_gh_event"), \
                mock.patch.object(im, "_fu_refresh_plan"), mock.patch.object(im, "log_event") as log:
            im._fu_finish()
        self.assertFalse([c for c in log.call_args_list if "signed out" in str(c)])


if __name__ == "__main__":
    unittest.main(verbosity=1)
