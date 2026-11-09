#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "check_repo.py")
PROMOTE = os.path.join(HERE, "promote.py")
DAY = 86400
T0 = 1790000000

RULES = {
    "lag": 4, "soak_days": 3, "fallback_days": 14,
    "cosmetic_since": "2026-09-01T00:00:00Z",
    "floors": {"bar": "2.0.0"},
    "aliases": {"oldfoo": "foo"},
}

PAGE = '''#!/usr/bin/env python3
VERSION = "{ver}"
_LAUNCHER_CODE = r"""launcher"""
PAGE = r"""<!DOCTYPE html><html><body><script>
function hi() {{ return "{text}"; }}
{extra}
</script></body></html>"""

def main():
    return {code}
'''


def tool_text(ver, text="hello", code="1", extra=""):
    return PAGE.format(ver=ver, text=text, code=code, extra=extra)


class Repo:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.write("channels/rules.json", json.dumps(RULES))
        self.write("channels/overrides.json", json.dumps({"hold": {}, "hotfix": {}}))
        self.write("README.md", "files\n")
        self.commit("base", T0 - DAY)

    def git(self, *args, env=None):
        e = dict(os.environ)
        if env:
            e.update(env)
        r = subprocess.run(["git", *args], cwd=self.path, capture_output=True, text=True, env=e)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        return r.stdout

    def write(self, rel, text):
        p = os.path.join(self.path, rel)
        os.makedirs(os.path.dirname(p) or self.path, exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def rm(self, rel):
        os.unlink(os.path.join(self.path, rel))

    def commit(self, msg, ts):
        self.git("add", "-A")
        d = f"@{int(ts)} +0000"
        self.git("commit", "-q", "-m", msg, env={"GIT_COMMITTER_DATE": d, "GIT_AUTHOR_DATE": d})

    def build(self, stem, ver, ts, prev=None, text="hello", code="1", extra=""):
        name = f"{stem}_v{ver.split('-')[0].replace('.', '_')}_20261001.py"
        if prev:
            self.rm(prev)
        self.write(name, tool_text(ver, text, code, extra))
        with open(os.path.join(self.path, "README.md")) as f:
            readme = f.read()
        if prev:
            readme = readme.replace(prev, name)
        else:
            readme += f"`{name}`\n"
        self.write("README.md", readme)
        clog = f"changelogs/{stem}.md"
        self.write(clog, f"# log\n\nCurrent file: `{name}`. Newest first.\n\n## {ver} (2026-10-01)\n\n- x\n")
        if ts is not None:
            self.commit(f"{stem} {ver}", ts)
        return name

    def promote(self, now_ts, overrides=None):
        if overrides is not None:
            self.write("channels/overrides.json", json.dumps(overrides))
            self.commit("overrides", T0 - DAY / 2)
        now = subprocess.run([sys.executable, "-c",
                              f"import datetime;print(datetime.datetime.fromtimestamp({now_ts},"
                              "datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))"],
                             capture_output=True, text=True).stdout.strip()
        r = subprocess.run([sys.executable, PROMOTE, "--now", now, "--print"], cwd=self.path,
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        body = r.stdout[r.stdout.index("{"):]
        return json.loads(body)["tools"]

    def check(self):
        r = subprocess.run([sys.executable, CHECK, "--base", "main"], cwd=self.path,
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr


def series(repo, stem, versions, start, step=DAY):
    prev = None
    for i, v in enumerate(versions):
        prev = repo.build(stem, v, start + i * step, prev)
    return prev


class PromoteTests(unittest.TestCase):
    def setUp(self):
        self.r = Repo()

    def tearDown(self):
        self.r.tmp.cleanup()

    def test_lag_of_four(self):
        series(self.r, "foo", ["1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4", "1.0.5"], T0)
        tools = self.r.promote(T0 + 6 * DAY)
        self.assertEqual(tools["foo"]["version"], "1.0.1")
        self.assertEqual(tools["foo"]["reason"], "count")

    def test_soak_holds_back(self):
        series(self.r, "foo", ["1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4"], T0, step=3600)
        self.assertNotIn("foo", self.r.promote(T0 + DAY))
        self.assertEqual(self.r.promote(T0 + 3 * DAY + 1)["foo"]["version"], "1.0.0")

    def test_cosmetic_does_not_count_or_promote(self):
        prev = series(self.r, "foo", ["1.0.0", "1.0.1", "1.0.2", "1.0.3"], T0)
        self.r.build("foo", "1.0.3.1", T0 + 4 * DAY, prev)
        self.assertNotIn("foo", self.r.promote(T0 + 10 * DAY))
        tools = self.r.promote(T0 + 3 * DAY + 14 * DAY + 1)
        self.assertEqual(tools["foo"]["version"], "1.0.3")
        self.assertEqual(tools["foo"]["reason"], "age")

    def test_fallback_needs_gap(self):
        series(self.r, "foo", ["1.0.0"], T0)
        self.assertNotIn("foo", self.r.promote(T0 + 13 * DAY))
        self.assertEqual(self.r.promote(T0 + 14 * DAY)["foo"]["version"], "1.0.0")

    def test_fallback_survives_later_builds(self):
        prev = series(self.r, "foo", ["1.0.0"], T0)
        self.r.build("foo", "1.0.1", T0 + 20 * DAY, prev)
        self.assertEqual(self.r.promote(T0 + 21 * DAY)["foo"]["version"], "1.0.0")

    def test_hold_and_hotfix(self):
        series(self.r, "foo", ["1.0.0", "1.0.1", "1.0.2", "1.0.3", "1.0.4", "1.0.5"], T0)
        tools = self.r.promote(T0 + 6 * DAY, {"hold": {"foo": ["1.0.1"]}, "hotfix": {}})
        self.assertEqual(tools["foo"]["version"], "1.0.0")
        tools = self.r.promote(T0 + 6 * DAY, {"hold": {}, "hotfix": {"foo": ["1.0.5"]}})
        self.assertEqual(tools["foo"]["version"], "1.0.5")
        self.assertEqual(tools["foo"]["reason"], "hotfix")

    def test_floor(self):
        series(self.r, "bar", ["1.9.0", "1.9.1", "1.9.2", "1.9.3", "1.9.4", "2.0.0"], T0)
        self.assertNotIn("bar", self.r.promote(T0 + 10 * DAY))
        self.assertEqual(self.r.promote(T0 + 5 * DAY + 14 * DAY)["bar"]["version"], "2.0.0")

    def test_old_name_counts_but_is_not_promoted(self):
        prev = series(self.r, "oldfoo", ["1.0.0", "1.0.1"], T0)
        series_prev = self.r.build("foo", "1.0.2", T0 + 2 * DAY, prev)
        prev = self.r.build("foo", "1.0.3", T0 + 3 * DAY, series_prev)
        prev = self.r.build("foo", "1.0.4", T0 + 4 * DAY, prev)
        self.r.build("foo", "1.0.5", T0 + 5 * DAY, prev)
        tools = self.r.promote(T0 + 6 * DAY)
        self.assertNotIn("foo", tools)

    def test_blob_matches_file(self):
        series(self.r, "foo", ["1.0.0"], T0)
        t = self.r.promote(T0 + 15 * DAY)["foo"]
        blob = self.r.git("rev-parse", f"{t['commit']}:{t['file']}").strip()
        self.assertEqual(t["blob"], blob)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.prev = series(self.r, "foo", ["1.0.0"], T0)
        self.r.git("checkout", "-q", "-b", "pr")

    def tearDown(self):
        self.r.tmp.cleanup()

    def assertCheck(self, ok, needle=None):
        rc, out = self.r.check()
        self.assertEqual(rc == 0, ok, out)
        if needle:
            self.assertIn(needle, out)

    def test_good_release(self):
        self.r.build("foo", "1.0.1", T0 + DAY, self.prev, code="2")
        self.assertCheck(True)

    def test_changed_in_place(self):
        self.r.write(self.prev, tool_text("1.0.0", code="2"))
        self.r.commit("x", T0 + DAY)
        self.assertCheck(False, "changed in place")

    def test_cosmetic_text_only(self):
        self.r.build("foo", "1.0.0.1", T0 + DAY, self.prev, text="hi there")
        self.assertCheck(True, "cosmetic check passed")

    def test_cosmetic_with_code_change(self):
        self.r.build("foo", "1.0.0.1", T0 + DAY, self.prev, code="2")
        self.assertCheck(False, "make it a release")

    def test_cosmetic_wrong_number(self):
        self.r.build("foo", "1.0.0.2", T0 + DAY, self.prev, text="x")
        self.assertCheck(False, "must follow")

    def in_place(self, ver, text="hello", code="1"):
        self.r.write(self.prev, tool_text(ver, text, code))
        self.r.write("changelogs/foo.md", f"# log\n\nCurrent file: `{self.prev}`. Newest first.\n\n## {ver} (2026-10-02)\n\n- x\n")
        self.r.commit("in place", T0 + DAY)

    def test_cosmetic_in_place(self):
        self.in_place("1.0.0.1", text="hi there")
        self.assertCheck(True, "file name kept")

    def test_cosmetic_in_place_skips_number(self):
        self.in_place("1.0.0.2", text="hi there")
        self.assertCheck(False, "next four-part number")

    def test_cosmetic_in_place_code_change(self):
        self.in_place("1.0.0.1", code="2")
        self.assertCheck(False, "make it a release")

    def test_not_newer(self):
        self.r.build("foo", "0.9.0", T0 + DAY, self.prev)
        self.assertCheck(False, "not newer")

    def test_two_parts(self):
        self.r.build("foo", "1.1", T0 + DAY, self.prev)
        self.assertCheck(False, "three parts")

    def test_version_mismatch(self):
        name = self.r.build("foo", "1.0.1", None, self.prev)
        self.r.write(name, tool_text("1.0.9"))
        self.r.commit("x", T0 + DAY)
        self.assertCheck(False, "file name says")

    def test_pi02w_suffix(self):
        self.r.build("baz_pi02w", "1.0.0", T0 + DAY)
        self.assertCheck(False, "-pi02w")

    def test_changelog_and_readme(self):
        name = self.r.build("foo", "1.0.1", None, self.prev)
        self.r.write("README.md", "files\n")
        self.r.write("changelogs/foo.md", "# log\n\nCurrent file: `x`.\n\n## 1.0.0\n")
        self.r.commit("x", T0 + DAY)
        rc, out = self.r.check()
        self.assertNotEqual(rc, 0)
        self.assertIn(f"README.md does not list {name}", out)
        self.assertIn("Current file", out)
        self.assertIn("top entry", out)

    def test_page_js_error(self):
        self.r.build("foo", "1.0.1", T0 + DAY, self.prev, extra="function (")
        self.assertCheck(False, "page JavaScript does not parse")

    def test_pyflakes(self):
        self.r.build("foo", "1.0.1", T0 + DAY, self.prev, code="undefined_name")
        self.assertCheck(False, "pyflakes")

    def test_comment_refused(self):
        self.r.build("foo", "1.0.1", T0 + DAY, self.prev, code="1  # why")
        self.assertCheck(False, "has a comment")

    def test_docstring_refused(self):
        name = self.r.build("foo", "1.0.1", None, self.prev)
        path = os.path.join(self.r.path, name)
        with open(path) as f:
            text = f.read()
        self.r.write(name, text.replace("def main():\n", 'def main():\n    """Explain."""\n'))
        self.r.commit("docstring", T0 + DAY)
        self.assertCheck(False, "has a docstring")

    def test_shebang_and_coding_lines_allowed(self):
        name = self.r.build("foo", "1.0.1", None, self.prev)
        path = os.path.join(self.r.path, name)
        with open(path) as f:
            text = f.read()
        self.r.write(name, text.replace("#!/usr/bin/env python3\n", "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n"))
        self.r.commit("coding line", T0 + DAY)
        self.assertCheck(True)

    def test_unused_page_function_noted(self):
        self.r.build("foo", "1.0.1", T0 + DAY, self.prev, extra="function neverCalled() { return 1; }")
        self.assertCheck(True, "neverCalled")

    def test_page_function_built_from_a_prefix_not_noted(self):
        self.r.build("foo", "1.0.1", T0 + DAY, self.prev,
                     extra="function asl3Run() { return 1; }\nconst t = '<b onclick=\"{prefix}Run()\">';")
        rc, out = self.r.check()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("asl3Run", out)

    def test_replaced_file_named_in_docs_noted(self):
        self.r.write("docs/src/foo_summary/summary.html", f"<p>Source: {self.prev}</p>")
        self.r.commit("doc", T0 + DAY / 2)
        self.r.build("foo", "1.0.1", T0 + DAY, self.prev, code="2")
        self.assertCheck(True, "still name it")

    def test_launcher_drift(self):
        self.r.build("foo", "1.0.1", None, self.prev)
        self.r.build("qux", "1.0.0", None)
        self.r.write("qux_v1_0_0_20261001.py",
                     tool_text("1.0.0").replace('r"""launcher"""', 'r"""other"""'))
        self.r.commit("x", T0 + DAY)
        self.assertCheck(False, "launcher text differs")

    def test_stable_json_blocked(self):
        self.r.write("channels/stable.json", "{}\n")
        self.r.commit("x", T0 + DAY)
        self.assertCheck(False, "written only by the promotion workflow")

    def test_bad_overrides(self):
        self.r.write("channels/overrides.json", json.dumps({"hold": {"foo": "1.0.0"}}))
        self.r.commit("x", T0 + DAY)
        self.assertCheck(False, "overrides.json")


    def android(self, ver, log_ver=None, extra="x"):
        self.r.write("android/app/build.gradle.kts", f'val appVersion = "{ver}"\n')
        self.r.write("android/app/src/Main.kt", extra + "\n")
        v = log_ver or ver
        self.r.write("changelogs/nodetalker_android.md", f"# log\n\nCurrent version: `{v}`.\n\n## {v} (2026-10-01)\n\n- x\n")

    def test_android_first_and_bump(self):
        self.android("0.1.0")
        self.r.commit("a", T0 + DAY)
        self.assertCheck(True)
        self.r.git("checkout", "-q", "main")
        self.r.git("merge", "-q", "pr")
        self.r.git("checkout", "-q", "pr")
        self.android("0.1.0", extra="y")
        self.r.commit("b", T0 + 2 * DAY)
        self.assertCheck(False, "not newer than 0.1.0")
        self.android("0.1.1", extra="y")
        self.r.commit("c", T0 + 3 * DAY)
        self.assertCheck(True)

    def test_android_changelog(self):
        self.android("0.1.0", log_ver="0.0.9")
        self.r.commit("a", T0 + DAY)
        self.assertCheck(False, "Current version")

    def test_android_bad_version(self):
        self.android("0.1")
        self.r.commit("a", T0 + DAY)
        self.assertCheck(False, "must be X.Y.Z")

    def shared(self, tool_def):
        self.r.write("shared/confio.py", SHARED_REF)
        name = self.r.build("foo", "1.0.1", None, self.prev)
        self.r.write(name, tool_text("1.0.1") + tool_def)
        self.r.commit("shared", T0 + DAY)

    def test_shared_copy_matches(self):
        self.shared("\n\ndef helper():\n    return 1\n")
        self.assertCheck(True)

    def test_shared_copy_drift(self):
        self.shared("\n\ndef helper():\n    return 2\n")
        self.assertCheck(False, "differs from shared/confio.py")

    def test_shared_copy_missing(self):
        self.shared("")
        self.assertCheck(False, "must carry helper")


SHARED_REF = 'USED_BY = {"helper": ("foo",)}\n\n\ndef helper():\n    return 1\n'


def load_confio():
    import importlib.util
    spec = importlib.util.spec_from_file_location("confio", os.path.join(HERE, "..", "shared", "confio.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.path = os.path.join(self.dir, "x.conf")
        self.aw = load_confio().atomic_write

    def tearDown(self):
        self.tmp.cleanup()

    def mode(self):
        return os.stat(self.path).st_mode & 0o7777

    def leftovers(self):
        return [f for f in os.listdir(self.dir) if f.endswith(".tmp")]

    def read(self):
        with open(self.path, "rb") as f:
            return f.read()

    def test_new_file_private(self):
        self.assertTrue(self.aw(self.path, "a=1\n"))
        self.assertEqual(self.read(), b"a=1\n")
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(self.leftovers(), [])

    def test_new_file_mode(self):
        self.aw(self.path, b"a", new_mode=0o644)
        self.assertEqual(self.mode(), 0o644)

    def test_keeps_existing_mode(self):
        self.aw(self.path, "a", new_mode=0o640)
        os.chmod(self.path, 0o640)
        self.aw(self.path, "b")
        self.assertEqual(self.read(), b"b")
        self.assertEqual(self.mode(), 0o640)

    def test_mode_forces(self):
        self.aw(self.path, "a", new_mode=0o644)
        self.aw(self.path, "b", mode=0o600)
        self.assertEqual(self.mode(), 0o600)

    def test_skip_same(self):
        self.aw(self.path, "a")
        os.utime(self.path, (1000, 1000))
        self.assertFalse(self.aw(self.path, "a", skip_same=True))
        self.assertEqual(os.stat(self.path).st_mtime, 1000)
        self.assertTrue(self.aw(self.path, "b", skip_same=True))
        self.assertEqual(self.read(), b"b")

    def test_symlink_not_followed(self):
        target = os.path.join(self.dir, "target")
        with open(target, "w") as f:
            f.write("keep")
        os.symlink(target, self.path)
        self.aw(self.path, "new")
        self.assertFalse(os.path.islink(self.path))
        self.assertEqual(self.read(), b"new")
        with open(target) as f:
            self.assertEqual(f.read(), "keep")

    def test_bad_data_leaves_file(self):
        self.aw(self.path, "old")
        with self.assertRaises(TypeError):
            self.aw(self.path, 12345)
        self.assertEqual(self.read(), b"old")
        self.assertEqual(self.leftovers(), [])

    def test_failed_replace_leaves_file(self):
        self.aw(self.path, "old")
        real = os.replace

        def boom(*a, **k):
            raise OSError("disk gone")
        os.replace = boom
        try:
            with self.assertRaises(OSError):
                self.aw(self.path, "new")
        finally:
            os.replace = real
        self.assertEqual(self.read(), b"old")
        self.assertEqual(self.leftovers(), [])


SECRETS = ["abc123", "mypass", "amipass", "sippass", "elpass", "urlpass", "commented", "bmpass", "WGPRIV",
           "WGPSK", "allpass", "jsonpass", "wifipass", "varpass", "eyJTOKEN", "SHADOWLINE", "KEYFILE", "TGIFPW", "FREEDMRPW",
           "someone@example.com", "61:20:3d"]


def load_helper44():
    import glob
    import importlib.util
    path = sorted(glob.glob(os.path.join(HERE, "..", "44helper_v*.py")))[-1]
    spec = importlib.util.spec_from_file_location("helper44_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["helper44_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


BUNDLE_DIR = os.path.join(HERE, "..", "configs", "pi02w")
VALUES = {"callsign": "w1test", "node": "654321", "dmr_id": "3123456", "nxdn_id": "12345"}


STEP_SAMPLES = {"callsign": "W1TEST", "dmrid": "3123456", "port": "8080", "rx_port": "34001", "branch": "main",
                "username": "admin", "version": "20260610", "node": "1234", "hubpassword": "", "authmode": "OPEN",
                "allowlist": "", "cruser": "pi", "crfolder": "~/claude-remote", "password": "Secret1"}
STEP_TABLES = ("_ASL3_SCRIPTS", "_DVSWITCH_SCRIPTS", "_SVXLINK_SCRIPTS", "_M17_SCRIPTS", "_AMP_SCRIPTS",
               "_CF_SCRIPTS", "_CR_SCRIPTS")


class Helper44StepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = load_helper44()

    def steps(self):
        for table in STEP_TABLES:
            for mode, per in getattr(self.h, table).items():
                for distro, steps in per.items():
                    for step in steps:
                        yield table, mode, distro, step

    def test_every_field_has_a_rule(self):
        missing = sorted({f"{t}:{s['id']}:{f['id']}" for t, _, _, s in self.steps()
                          for f in s.get("fields") or [] if f["id"] not in self.h._STEP_FIELD_RULES})
        self.assertEqual(missing, [], "a field with no rule makes its step unrunnable from the page")

    def test_template_markers_match_fields(self):
        bad = []
        for t, _, _, s in self.steps():
            tmpl = s.get("cmd_template")
            if not tmpl:
                continue
            marks = set(re.findall(r"\{\{(\w+)\}\}", tmpl))
            fields = {f["id"] for f in s.get("fields") or []}
            if marks != fields:
                bad.append(f"{t}:{s['id']} markers {sorted(marks)} fields {sorted(fields)}")
        self.assertEqual(bad, [])

    def test_step_ids_unique_per_list(self):
        for table in STEP_TABLES:
            for mode, per in getattr(self.h, table).items():
                for distro, steps in per.items():
                    ids = [s["id"] for s in steps]
                    self.assertEqual(len(ids), len(set(ids)), f"{table} {mode} {distro}")

    def test_samples_pass_every_rule(self):
        for fid, (rx, _) in self.h._STEP_FIELD_RULES.items():
            self.assertIn(fid, STEP_SAMPLES)
            self.assertTrue(rx.fullmatch(STEP_SAMPLES[fid]), fid)

    def test_templates_build_with_good_values(self):
        for t, _, _, s in self.steps():
            if not s.get("cmd_template"):
                continue
            fields = {f["id"]: STEP_SAMPLES[f["id"]] for f in s["fields"]}
            cmd, why = self.h._step_command(s, fields)
            self.assertEqual(why, "", f"{t}:{s['id']}")
            self.assertNotIn("{{", cmd, f"{t}:{s['id']}")

    def test_bad_value_refused(self):
        for t, _, _, s in self.steps():
            if any(f["id"] == "callsign" for f in s.get("fields") or []):
                fields = {f["id"]: STEP_SAMPLES[f["id"]] for f in s["fields"]}
                fields["callsign"] = "W1TEST; reboot"
                cmd, why = self.h._step_command(s, fields)
                self.assertEqual(cmd, "")
                self.assertIn("use 3 to 16", why)
                return
        self.fail("no step with a callsign field found")

    def test_changed_command_refused_before_anything_runs(self):
        step = self.h._ASL3_SCRIPTS["install"]["bookworm"][0]
        r = self.h._dispatch_tab_action({"mode": "install", "distro": "bookworm", "step_id": step["id"],
                                         "command_text": step["cmd"] + " ; echo changed"},
                                        self.h._asl3_lookup_step, "asl3")
        self.assertFalse(r["success"])
        self.assertEqual(r["output"], self.h._STEP_CHANGED_MSG)

    def test_unknown_step_and_distro_refused(self):
        r = self.h._dispatch_tab_action({"mode": "install", "distro": "bookworm", "step_id": "no_such_step",
                                         "command_text": "true"}, self.h._asl3_lookup_step, "asl3")
        self.assertIn("Unknown step_id", r["output"])
        r = self.h._dispatch_tab_action({"mode": "install", "distro": "jessie", "step_id": "prereqs",
                                         "command_text": "true"}, self.h._asl3_lookup_step, "asl3")
        self.assertIn("Unknown distro", r["output"])


class BundleTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        self.h = load_helper44()
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {}
        for name, val in (("_CFGR_DIR", os.path.join(self.tmp.name, "lib")),
                          ("_FCR_DIR", os.path.join(self.tmp.name, "lib", "bundle", "pi02w"))):
            self.saved[name] = getattr(self.h, name)
            setattr(self.h, name, val)
        self.served = {}
        for root, _dirs, files in os.walk(BUNDLE_DIR):
            for n in files:
                full = os.path.join(root, n)
                with open(full, "rb") as f:
                    self.served[os.path.relpath(full, BUNDLE_DIR)] = f.read()
        self.sha = hashlib.sha256
        self.fetched_urls = []

        def fake_get(url, max_bytes, timeout=20):
            self.fetched_urls.append(url)
            rel = url.split("/configs/pi02w/", 1)[1]
            if rel not in self.served:
                raise OSError("404")
            return self.served[rel]
        self.patch("http_get", fake_get)

    def patch(self, name, val):
        self.saved.setdefault(name, getattr(self.h, name))
        setattr(self.h, name, val)

    def tearDown(self):
        for name, val in self.saved.items():
            setattr(self.h, name, val)
        self.tmp.cleanup()

    def products(self, installed):
        def fake(force=False):
            return [{"key": k, "state": "installed" if k in installed else "absent"} for k in ("asl3", "dvs", "usrp2m17")]
        self.patch("_detect_installed_products", fake)

    def test_repo_bundle_is_valid(self):
        import re
        m = json.loads(self.served["manifest.json"])
        self.assertIsNone(self.h._fcr_manifest_error(m))
        tokens = {f["token"] for f in m["fields"]} | {d["token"] for d in m["derived"]}
        for e in m["files"]:
            data = self.served[e["file"]]
            self.assertEqual(self.sha(data).hexdigest(), e["sha256"], e["path"])
            self.assertEqual(len(data), e["size"], e["path"])
            text = data.decode()
            self.assertFalse(set(re.findall(r"@@[A-Z0-9_]+@@", text)) - tokens, e["path"])
            for word in ("KD8PGK", "652701", "3214544", "11738", "Jim "):
                self.assertNotIn(word, text, e["path"] + " " + word)

    def test_fetch_stages_and_rejects_tampering(self):
        res = self.h._fcr_fetch("main")
        self.assertTrue(res["success"], res["output"])
        self.assertIsNotNone(self.h._fcr_load()[0])
        self.assertTrue(all(u.startswith("https://raw.githubusercontent.com/kd8pgk/ASL-DVS/main/configs/pi02w/")
                            for u in self.fetched_urls))
        first = json.loads(self.served["manifest.json"])["files"][0]
        self.served[first["file"]] = self.served[first["file"]] + b"x"
        res = self.h._fcr_fetch("main")
        self.assertFalse(res["success"])
        self.assertIn("checksum", res["output"])
        self.assertIsNotNone(self.h._fcr_load()[0])

    def test_fetch_rejects_bad_ref_and_bad_manifest(self):
        self.assertFalse(self.h._fcr_fetch("../x")["success"])
        m = json.loads(self.served["manifest.json"])
        m["files"][0]["path"] = "/etc/shadow"
        self.served["manifest.json"] = json.dumps(m).encode()
        res = self.h._fcr_fetch("main")
        self.assertFalse(res["success"])
        self.assertIn("not a file this card may change", res["output"])
        self.assertIsNone(self.h._fcr_load()[0])

    def test_values_are_checked(self):
        m = json.loads(self.served["manifest.json"])
        tokens, err = self.h._fcr_tokens(m, {"values": VALUES})
        self.assertEqual(err, "")
        self.assertEqual(tokens["@@CALLSIGN@@"], "W1TEST")
        self.assertEqual(tokens["@@NODE_2@@"], "654322")
        bad = dict(VALUES, callsign="no way")
        self.assertIsNone(self.h._fcr_tokens(m, {"values": bad})[0])
        self.assertIsNone(self.h._fcr_tokens(m, {"values": dict(VALUES, node="12")})[0])
        self.assertIsNone(self.h._fcr_tokens(m, {})[0])

    def test_secrets_kept_from_current_file(self):
        fill = self.h.fill_secrets
        bundle = ("[general]\nsecret = <redacted:aaaaaaaa>\nregister => 1:<redacted:bbbbbbbb>@host.org\n"
                  "[DMR Network]\nPassword=<redacted:cccccccc>\n[Other]\nPassword=<redacted:dddddddd>\n"
                  ";secret = <redacted:eeeeeeee>\n")
        current = ("[general]\nsecret=abc\nregister => 1:pw1@host.org\n[DMR Network]\nPassword=one\n"
                   "[Other]\nPassword=two\n")
        text, resolved, unresolved = fill(bundle, current)
        self.assertIn("secret = abc", text)
        self.assertIn("register => 1:pw1@host.org", text)
        self.assertIn("[DMR Network]\nPassword=one", text)
        self.assertIn("[Other]\nPassword=two", text)
        self.assertNotIn("<redacted:", text)
        self.assertEqual(unresolved, [])
        text, resolved, unresolved = fill(bundle, None)
        self.assertNotIn("<redacted:", text)
        self.assertEqual(len(unresolved), 4)
        self.assertEqual(sorted(u["tag"] for u in unresolved)[:2], ["<redacted:aaaaaaaa>", "<redacted:bbbbbbbb>"])
        self.assertEqual(resolved, 0)
        text, _r, unresolved = fill("[a]\nx=<redacted:11111111>\nx=<redacted:22222222>\n", "[a]\nx=first\nx=second\n")
        self.assertIn("x=first\nx=second", text)

    def staged_apply(self, installed, current):
        self.products(installed)
        self.assertTrue(self.h._fcr_fetch("main")["success"])
        written = {}
        self.patch("_cfgr_read", lambda path: current.get(path))
        self.patch("_cfgr_meta_of", lambda path: (None, None, 0o644))
        self.patch("_cfgr_auto_point", lambda reason, groups: ("auto1", []))

        def fake_write(path, data, uid, gid, mode):
            written[path] = data
            return "written"
        self.patch("_cfgr_write_file", fake_write)
        return written

    def test_apply_needs_confirm(self):
        written = self.staged_apply({"asl3", "dvs", "usrp2m17"}, {})
        res = self.h._fcr_act_apply({"values": VALUES})
        self.assertFalse(res["success"])
        self.assertEqual(written, {})

    def test_apply_fills_identity_and_keeps_secrets(self):
        current = {"/opt/MMDVM_Bridge/MMDVM_Bridge.ini": b"[DMR Network]\nPassword=sekrit\n"}
        written = self.staged_apply({"asl3", "dvs", "usrp2m17"}, current)
        res = self.h._fcr_act_apply({"values": VALUES, "confirm": True})
        self.assertTrue(res["success"], res["output"])
        self.assertEqual(sorted(res["restart_groups"]), ["asl3", "dvs", "m17"])
        m = json.loads(self.served["manifest.json"])
        self.assertEqual(sorted(written), sorted(e["path"] for e in m["files"]))
        for path, data in written.items():
            text = data.decode()
            self.assertNotIn("@@", text, path)
            self.assertNotIn("<redacted:", text, path)
        self.assertIn("[654321](node-main)", written["/etc/asterisk/rpt.conf"].decode())
        self.assertIn("654322", written["/etc/asterisk/rpt.conf"].decode())
        self.assertIn("Callsign=W1TEST", written["/opt/MMDVM_Bridge/MMDVM_Bridge.ini"].decode())
        self.assertIn("Password=sekrit", written["/opt/MMDVM_Bridge/MMDVM_Bridge.ini"].decode())
        self.assertIn("set them by hand", res["output"])

    def test_groups_not_installed_are_skipped(self):
        written = self.staged_apply({"asl3"}, {})
        res = self.h._fcr_act_apply({"values": VALUES, "confirm": True})
        self.assertTrue(res["success"], res["output"])
        self.assertEqual(res["restart_groups"], ["asl3"])
        self.assertTrue(all(p.startswith("/etc/") for p in written))
        self.assertIn("/opt/USRP2M17/USRP2M17.ini: skipped (not installed)", res["output"])
        self.assertTrue(self.h._fcr_status()["staged"])

    def test_preview_changes_nothing(self):
        written = self.staged_apply({"asl3", "dvs", "usrp2m17"}, {})
        res = self.h._fcr_act_preview({"values": VALUES})
        self.assertTrue(res["success"], res["output"])
        self.assertIn("Nothing was changed", res["output"])
        self.assertEqual(written, {})


class ConfputterTests(unittest.TestCase):
    FILES = {
        "etc/asterisk/rpt.conf": "; node comment\n[general]\nsecret = s3cr3t\n\n; another comment\nnode = 1234\n",
        "etc/asterisk/iax.conf": "[general]\nregister => 1999:regpw@register.example.org\n",
        "opt/MMDVM_Bridge/MMDVM_Bridge.ini": "[DMR Network]\nPassword=bmpw\nAddress=host.example.org\n",
        "etc/asl_dvs/phone.json": json.dumps({"password": "phonepw", "email": "me@example.org", "x": 1}),
        "etc/asl_dvs/favs.conf": "[DMR_SERVERS]\nTGIF|tgifpw|tgif.network:62031|https://t.example.org\n",
        "etc/firewalld/zones/z.xml": "<zone/>\n",
        "etc/hosts": "127.0.0.1 localhost\n",
        "etc/asl_dvs/instmon_locks.json": "{}",
    }

    def setUp(self):
        import glob
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "node")
        self.out = os.path.join(self.tmp.name, "snaps")
        self.backups = os.path.join(self.tmp.name, "backups")
        self.getter = sorted(glob.glob(os.path.join(HERE, "..", "confgetter_v*.sh")))[-1]
        self.putter = sorted(glob.glob(os.path.join(HERE, "..", "confputter_v*.py")))[-1]
        self.write_tree(self.FILES)
        r = subprocess.run(["bash", self.getter, "--out", self.out], capture_output=True, text=True,
                           env=dict(os.environ, CONFGETTER_ROOT=self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        snaps = [f for f in os.listdir(self.out) if f.endswith(".md")]
        self.snap = os.path.join(self.out, snaps[0])

    def tearDown(self):
        self.tmp.cleanup()

    def write_tree(self, files):
        for rel, text in files.items():
            p = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)

    def read(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return f.read()

    def run_put(self, *args, snap=None, ok=True):
        env = dict(os.environ, CONFPUTTER_ROOT=self.root, CONFPUTTER_BACKUPS=self.backups)
        r = subprocess.run([sys.executable, self.putter, "--json", *args] + (["--snapshot", snap or self.snap]
                           if "--undo" not in args and "--list-backups" not in args else []),
                           capture_output=True, text=True, env=env)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def status(self, res):
        return {f["path"]: f["status"] for f in res["files"]}

    def test_unchanged_node_is_all_same(self):
        res = self.run_put("--preview")
        st = self.status(res)
        for p in ("/etc/asterisk/rpt.conf", "/etc/asterisk/iax.conf", "/opt/MMDVM_Bridge/MMDVM_Bridge.ini",
                  "/etc/asl_dvs/phone.json", "/etc/asl_dvs/favs.conf", "/etc/firewalld/zones/z.xml"):
            self.assertEqual(st[p], "same", p)
        self.assertEqual(st["/etc/hosts"], "skipped")
        self.assertEqual(st["/etc/asl_dvs/instmon_locks.json"], "skipped")
        self.assertEqual(res["secrets"], [])
        self.assertTrue(res["snapshot"]["host_match"])

    def test_same_node_fix_keeps_secrets_and_undoes(self):
        self.write_tree({"etc/asterisk/rpt.conf": "; node comment\n[general]\nsecret = newer\n\n; another comment\nnode = 9999\n",
                         "opt/MMDVM_Bridge/MMDVM_Bridge.ini": "[DMR Network]\nPassword=changed\nAddress=wrong\n"})
        res = self.run_put("--preview")
        self.assertEqual(self.status(res)["/etc/asterisk/rpt.conf"], "changed")
        self.assertEqual(res["secrets"], [])
        before = {p: self.read(p) for p in self.FILES}
        done = self.run_put("--apply")
        self.assertEqual(sorted(done["written"]), ["/etc/asterisk/rpt.conf", "/opt/MMDVM_Bridge/MMDVM_Bridge.ini"])
        self.assertIn("node = 1234", self.read("etc/asterisk/rpt.conf"))
        self.assertIn("secret = newer", self.read("etc/asterisk/rpt.conf"))
        self.assertIn("Password=changed", self.read("opt/MMDVM_Bridge/MMDVM_Bridge.ini"))
        self.assertIn("Address=host.example.org", self.read("opt/MMDVM_Bridge/MMDVM_Bridge.ini"))
        again = self.status(self.run_put("--preview"))
        self.assertEqual(again["/etc/asterisk/rpt.conf"], "same")
        self.assertEqual(again["/opt/MMDVM_Bridge/MMDVM_Bridge.ini"], "same")
        undo = self.run_put("--undo")
        self.assertEqual(sorted(undo["restored"]), sorted(done["written"]))
        for p, text in before.items():
            self.assertEqual(self.read(p), text, p)
        self.assertFalse(self.run_put("--undo", ok=False)["ok"])

    def test_wiped_node_needs_typed_secrets(self):
        for rel in self.FILES:
            os.unlink(os.path.join(self.root, rel))
        res = self.run_put("--preview")
        self.assertEqual(self.status(res)["/etc/asterisk/rpt.conf"], "new")
        self.assertGreaterEqual(len(res["secrets"]), 5)
        values = {x["tag"]: "typed-" + x["tag"][10:14] for x in res["secrets"]}
        sf = os.path.join(self.tmp.name, "secrets.json")
        with open(sf, "w") as f:
            json.dump(values, f)
        done = self.run_put("--apply", "--secrets-file", sf)
        self.assertFalse(done["unresolved"])
        text = self.read("etc/asterisk/rpt.conf")
        self.assertIn("node = 1234", text)
        self.assertNotIn("<redacted:", text)
        self.assertIn("secret = typed-", text)
        self.assertIn("register => 1999:typed-", self.read("etc/asterisk/iax.conf"))
        phone = json.loads(self.read("etc/asl_dvs/phone.json"))
        self.assertEqual(phone["x"], 1)
        self.assertTrue(phone["password"].startswith("typed-"))
        self.assertEqual(os.stat(os.path.join(self.root, "etc/asterisk/rpt.conf")).st_mode & 0o777, 0o644)

    def test_unfilled_secrets_are_written_empty_and_listed(self):
        os.unlink(os.path.join(self.root, "etc/asterisk/iax.conf"))
        done = self.run_put("--apply", "--only", "/etc/asterisk/iax.conf")
        self.assertEqual([u["path"] for u in done["unresolved"]], ["/etc/asterisk/iax.conf"])
        self.assertEqual(self.read("etc/asterisk/iax.conf"), "[general]\nregister => 1999:@register.example.org\n")

    def test_stripped_copy_keeps_node_comments(self):
        with open(self.snap, encoding="utf-8") as f:
            text = f.read()
        stripped = "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith(";"))
        stripped = "> Test copy: whole-line comments removed.\n\n" + stripped
        copy = os.path.join(self.tmp.name, "stripped.md")
        with open(copy, "w", encoding="utf-8") as f:
            f.write(stripped)
        res = self.run_put("--preview", snap=copy)
        self.assertEqual(self.status(res)["/etc/asterisk/rpt.conf"], "same")
        self.assertTrue(any("Edited copy" in w for w in res["warnings"]))
        edited = stripped.replace("node = 1234", "node = 4321")
        with open(copy, "w", encoding="utf-8") as f:
            f.write(edited)
        self.run_put("--apply", "--only", "/etc/asterisk/rpt.conf", snap=copy)
        self.assertEqual(self.read("etc/asterisk/rpt.conf"),
                         "; node comment\n[general]\nsecret = s3cr3t\n\n; another comment\nnode = 4321\n")
        flat = self.run_put("--preview", "--no-keep-comments", snap=copy)
        self.assertEqual(self.status(flat)["/etc/asterisk/rpt.conf"], "comments")

    def test_policy_refuses_unsafe_paths(self):
        with open(self.snap, encoding="utf-8") as f:
            text = f.read()
        evil = text.replace("### /etc/hosts", "### /etc/shadow").replace("### /etc/firewalld/zones/z.xml", "### /etc/asterisk/../shadow")
        evil += "\n### /etc/asterisk/custom/README.md\n\n```\nhello\n```\n"
        copy = os.path.join(self.tmp.name, "evil.md")
        with open(copy, "w", encoding="utf-8") as f:
            f.write(evil)
        res = self.run_put("--preview", snap=copy)
        st = self.status(res)
        self.assertEqual(st["/etc/shadow"], "skipped")
        self.assertEqual(st["/etc/asterisk/../shadow"], "skipped")
        self.assertEqual(st["/etc/asterisk/custom/README.md"], "skipped")
        done = self.run_put("--apply", "--only", "/etc/shadow", snap=copy, ok=False)
        self.assertEqual(done["written"], [])

    def test_trimmed_file_is_refused(self):
        with open(self.snap, encoding="utf-8") as f:
            text = f.read()
        marked = text.replace("| /etc/asterisk/rpt.conf |", "| /etc/asterisk/rpt.conf |", 1)
        lines = marked.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("| /etc/asterisk/rpt.conf |"):
                cols = ln.strip().strip("|").split("|")
                cols[7] = " trimmed to 200000 bytes "
                lines[i] = "|" + "|".join(cols) + "|"
        copy = os.path.join(self.tmp.name, "trim.md")
        with open(copy, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        res = self.run_put("--preview", snap=copy)
        self.assertEqual(self.status(res)["/etc/asterisk/rpt.conf"], "skipped")

    def test_bad_input_is_refused(self):
        bad = os.path.join(self.tmp.name, "notasnapshot.md")
        with open(bad, "w") as f:
            f.write("# just a note\n")
        self.assertFalse(self.run_put("--preview", snap=bad, ok=False)["ok"])
        sf = os.path.join(self.tmp.name, "s.json")
        with open(sf, "w") as f:
            json.dump({"<redacted:aaaaaaaa>": "line\nbreak"}, f)
        self.assertFalse(self.run_put("--apply", "--secrets-file", sf, ok=False)["ok"])
        with open(sf, "w") as f:
            json.dump({"not a tag": "x"}, f)
        self.assertFalse(self.run_put("--apply", "--secrets-file", sf, ok=False)["ok"])

    def test_backups_are_private_and_kept_to_ten(self):
        for i in range(12):
            self.write_tree({"etc/asterisk/rpt.conf": "[general]\nnode = %d\n" % i})
            self.run_put("--apply", "--only", "/etc/asterisk/rpt.conf")
        ids = sorted(os.listdir(self.backups))
        self.assertEqual(len(ids), 10)
        self.assertEqual(os.stat(self.backups).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(self.backups, ids[-1])).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(self.backups, ids[-1], "manifest.json")).st_mode & 0o777, 0o600)
        self.assertEqual(len(self.run_put("--list-backups")["backups"]), 10)

    def test_diff_does_not_show_secrets(self):
        self.write_tree({"etc/asterisk/rpt.conf": "[general]\nsecret = reallysecret\nnode = 7\n",
                         "etc/asl_dvs/phone.json": json.dumps({"password": "phonepw2", "email": "me@example.org", "x": 2})})
        res = self.run_put("--preview")
        text = json.dumps(res)
        for word in ("reallysecret", "phonepw2", "me@example.org"):
            self.assertNotIn(word, text)


def load_instmon(env):
    import glob
    import importlib.util
    for k, v in env.items():
        os.environ[k] = v
    path = sorted(glob.glob(os.path.join(HERE, "..", "instmon_v*.py")))[-1]
    spec = importlib.util.spec_from_file_location("instmon_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["instmon_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class InstmonConfputterTests(unittest.TestCase):
    def setUp(self):
        import glob
        import shutil
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.root = os.path.join(t, "node")
        self.envkeys = ("INSTMON_LIBRARY_DIR", "INSTMON_CONFIG_DIR", "CONFPUTTER_ROOT", "CONFPUTTER_BACKUPS",
                        "CONFGETTER_ROOT")
        self.saved_env = {k: os.environ.get(k) for k in self.envkeys}
        self.m = load_instmon({"INSTMON_LIBRARY_DIR": os.path.join(t, "lib"), "INSTMON_CONFIG_DIR": os.path.join(t, "cfg"),
                               "CONFPUTTER_ROOT": self.root, "CONFPUTTER_BACKUPS": os.path.join(t, "bk")})
        self.m.CONFPUTTER_BIN = os.path.join(t, "bin", "confputter.py")
        self.m.PUT_BACKUP_DIR = os.path.join(t, "bk")
        self.m.ensure_dirs()
        os.makedirs(os.path.join(self.root, "etc/asterisk"))
        with open(os.path.join(self.root, "etc/asterisk/rpt.conf"), "w") as f:
            f.write("; comment\n[general]\nsecret = pw1\nnode = 1234\n")
        r = subprocess.run(["bash", sorted(glob.glob(os.path.join(HERE, "..", "confgetter_v*.sh")))[-1], "--out",
                            self.m.SNAP_DIR], capture_output=True, text=True,
                           env=dict(os.environ, CONFGETTER_ROOT=self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.name = [f for f in os.listdir(self.m.SNAP_DIR) if f.endswith(".md")][0]
        self.putter = sorted(glob.glob(os.path.join(HERE, "..", "confputter_v*.py")))[-1]
        shutil.copy(self.putter, self.m.LIB_SUBDIRS["confputter"])
        self.libname = os.path.basename(self.putter)

    def tearDown(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def rpt(self):
        with open(os.path.join(self.root, "etc/asterisk/rpt.conf")) as f:
            return f.read()

    def install(self):
        code, _ = self.m.cp_install(self.libname)
        self.assertEqual(code, 200)

    def test_install_run_and_uninstall(self):
        self.assertFalse(self.m.confputter_status()["installed"])
        self.assertEqual(self.m.cp_preview({"snapshot": "snapshot:" + self.name})[0], 409)
        self.assertEqual(self.m.cp_install("../../etc/passwd")[0], 404)
        self.install()
        self.assertEqual(os.stat(self.m.CONFPUTTER_BIN).st_mode & 0o777, 0o755)
        st = self.m.confputter_status()
        self.assertTrue(st["installed"])
        self.assertEqual(st["version"], "1.0.0")
        self.assertEqual([x["name"] for x in st["snapshots"]], [self.name])
        self.assertEqual(self.m.scan_library()["confputter"][0]["installed"], True)
        self.assertEqual(self.m.cp_uninstall()[0], 200)
        self.assertFalse(os.path.exists(self.m.CONFPUTTER_BIN))
        self.assertEqual(self.m.cp_uninstall()[0], 404)

    def test_install_refuses_bad_files(self):
        lib = self.m.LIB_SUBDIRS["confputter"]
        with open(os.path.join(lib, "confputter_bad.py"), "w") as f:
            f.write("#!/usr/bin/env python3\nVERSION = '1'\nif x y:\n")
        with open(os.path.join(lib, "confputter_notpy.py"), "w") as f:
            f.write("#!/bin/bash\nVERSION = '1'\n")
        self.assertEqual(self.m.cp_install("confputter_bad.py")[0], 400)
        self.assertEqual(self.m.cp_install("confputter_notpy.py")[0], 400)

    def test_preview_apply_undo(self):
        self.install()
        code, body = self.m.cp_preview({"snapshot": "snapshot:" + self.name})
        self.assertEqual(code, 200)
        st = {f["path"]: f["status"] for f in body["plan"]["files"]}
        self.assertEqual(st["/etc/asterisk/rpt.conf"], "same")
        with open(os.path.join(self.root, "etc/asterisk/rpt.conf"), "w") as f:
            f.write("; comment\n[general]\nsecret = pw2\nnode = 9\n")
        self.assertEqual(self.m.cp_apply({"snapshot": "snapshot:" + self.name, "only": ["/etc/asterisk/rpt.conf"]})[0], 400)
        code, body = self.m.cp_apply({"snapshot": "snapshot:" + self.name, "only": ["/etc/asterisk/rpt.conf"],
                                      "confirm": True})
        self.assertEqual(code, 200, body)
        self.assertTrue(body["result"]["ok"])
        self.assertEqual(self.rpt(), "; comment\n[general]\nsecret = pw2\nnode = 1234\n")
        last = self.m.confputter_status()["last_backup"]
        self.assertEqual(last["files"], 1)
        self.assertFalse(last["undone"])
        self.assertEqual(self.m.cp_undo({})[0], 400)
        code, body = self.m.cp_undo({"confirm": True})
        self.assertEqual(code, 200, body)
        self.assertEqual(self.rpt(), "; comment\n[general]\nsecret = pw2\nnode = 9\n")
        self.assertTrue(self.m.confputter_status()["last_backup"]["undone"])

    def test_apply_checks_its_input(self):
        self.install()
        snap = "snapshot:" + self.name
        good = {"snapshot": snap, "only": ["/etc/asterisk/rpt.conf"], "confirm": True}
        self.assertEqual(self.m.cp_apply(dict(good, snapshot="snapshot:../x"))[0], 404)
        self.assertEqual(self.m.cp_apply(dict(good, snapshot="other:" + self.name))[0], 404)
        self.assertEqual(self.m.cp_apply(dict(good, only=[]))[0], 400)
        self.assertEqual(self.m.cp_apply(dict(good, only=["etc/relative"]))[0], 400)
        self.assertEqual(self.m.cp_apply(dict(good, secrets={"not a tag": "x"}))[0], 400)
        self.assertEqual(self.m.cp_apply(dict(good, secrets={"<redacted:aaaaaaaa>": "a\nb"}))[0], 400)
        self.assertEqual(self.m.cp_apply(dict(good, secrets={"<redacted:aaaaaaaa>": "x" * 501}))[0], 400)
        code, _ = self.m.cp_apply(dict(good, only=["/etc/shadow"]))
        self.assertEqual(code, 400)

    def test_secret_file_is_private_and_removed(self):
        self.install()
        seen = []
        real = subprocess.run

        def spy(cmd, **kw):
            path = cmd[cmd.index("--secrets-file") + 1]
            seen.append((path, os.stat(path).st_mode & 0o777))
            return real(cmd, **kw)
        self.m.subprocess = type("S", (), {"run": staticmethod(spy), "TimeoutExpired": subprocess.TimeoutExpired,
                                           "Popen": subprocess.Popen, "PIPE": subprocess.PIPE,
                                           "STDOUT": subprocess.STDOUT})
        code, _ = self.m.cp_apply({"snapshot": "snapshot:" + self.name, "only": ["/etc/asterisk/rpt.conf"],
                                   "secrets": {"<redacted:aaaaaaaa>": "typed"}, "confirm": True})
        self.assertEqual(code, 200)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], 0o600)
        self.assertFalse(os.path.exists(seen[0][0]))

    def test_busy_is_refused(self):
        self.install()
        self.m._cp_lock.acquire()
        try:
            self.assertTrue(self.m.confputter_status()["running"])
            self.assertEqual(self.m.cp_preview({"snapshot": "snapshot:" + self.name})[0], 409)
            self.assertEqual(self.m.cp_uninstall()[0], 409)
        finally:
            self.m._cp_lock.release()

    def test_upload_of_an_edited_copy(self):
        self.install()
        with open(os.path.join(self.m.SNAP_DIR, self.name), "rb") as f:
            data = f.read()
        code, body = self.m.cp_save_upload("../evil.md", data)
        self.assertEqual((code, body["name"]), (200, "evil.md"))
        self.assertTrue(os.path.isfile(os.path.join(self.m.EDITED_DIR, "evil.md")))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.m.EDITED_DIR), "evil.md")))
        self.assertEqual(self.m.cp_delete_edited("evil.md")[0], 200)
        self.assertEqual(self.m.cp_save_upload("notes.txt", data)[0], 400)
        self.assertEqual(self.m.cp_save_upload("edited.md", b"# just a note\n")[0], 400)
        self.assertEqual(self.m.cp_save_upload("edited.md", b"")[0], 400)
        self.assertEqual(self.m.cp_save_upload("edited.md", b"\xff\xfe")[0], 400)
        self.assertEqual(self.m.cp_save_upload("edited.md", b"x" * (self.m.CP_MAX_UPLOAD + 1))[0], 400)
        code, body = self.m.cp_save_upload("edited.md", data)
        self.assertEqual(code, 200, body)
        full = os.path.join(self.m.EDITED_DIR, "edited.md")
        self.assertEqual(os.stat(full).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.m.EDITED_DIR).st_mode & 0o777, 0o700)
        self.assertEqual([e["name"] for e in self.m.confputter_status()["edited"]], ["edited.md"])
        self.assertEqual(self.m.cp_preview({"snapshot": "edited:edited.md"})[0], 200)
        os.symlink(full, os.path.join(self.m.EDITED_DIR, "link.md"))
        self.assertIsNone(self.m.cp_edited_path("link.md"))
        self.assertEqual(self.m.cp_delete_edited("../x")[0], 404)
        self.assertEqual(self.m.cp_delete_edited("edited.md")[0], 200)
        self.assertEqual(self.m.cp_delete_edited("edited.md")[0], 404)

    def test_card_is_on_the_page_below_config_getter(self):
        html = self.m.render_page()
        self.assertIn('id="confputter-card"', html)
        self.assertLess(html.index('id="cg-card"') if 'id="cg-card"' in html else html.index('id="components"'),
                        html.index('id="confputter-card"'))
        self.assertLess(html.index('id="confputter-card"'), html.index('id="usbimp-card"'))
        self.assertIn("function cpApply", html)
        self.assertIn("Config putter", self.m.render_library_html(self.m.scan_library()))


class ConfgetterFixtureTests(unittest.TestCase):
    PATH = os.path.join(HERE, "fixtures", "confgetter_sample.md")

    def setUp(self):
        with open(self.PATH, encoding="utf-8") as f:
            self.text = f.read()

    def test_is_a_snapshot(self):
        self.assertIn("# Node config snapshot:", self.text)
        self.assertIn("## Manifest", self.text)
        self.assertIn("<redacted:", self.text)

    def test_no_identifiers(self):
        import re
        for word in ("KD8PGK", "magicbox", "652701", "400353", "2376", "450008", "41.7333", "321454", "utz3A2vW",
                     "SJUy5ALC", "Jim "):
            self.assertNotIn(word, self.text, word)
        emails = [m for m in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[a-z]{2,}", self.text)
                  if not m.startswith("wg-quick@")]
        self.assertEqual(emails, [])
        macs = [m for m in re.findall(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", self.text) if m != "00:00:00:00:00:00"]
        self.assertEqual(macs, [])
        ips = set(re.findall(r"(?<![0-9.])\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?![0-9.])", self.text))
        allowed = ("127.", "0.0.0.0", "255.255.255.255", "224.0.0.251", "198.51.100.")
        self.assertEqual(sorted(i for i in ips if not i.startswith(allowed)), [])


class ConfgetterTests(unittest.TestCase):
    def setUp(self):
        import glob
        import hashlib
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "node")
        self.out = os.path.join(self.tmp.name, "snaps")
        self.script = sorted(glob.glob(os.path.join(HERE, "..", "confgetter_v*.sh")))[-1]
        stock = "[general]\nfoo=1\n"
        files = {
            "etc/asterisk/iax.conf": "[general]\nsecret = abc123\nregister => 1999:mypass@register.allstarlink.org\n",
            "etc/asterisk/manager.conf": "[admin]\nsecret=amipass\n",
            "etc/asterisk/dup.conf": "[x]\nsecret = abc123\n",
            "etc/asterisk/pjsip.conf": "[u]\npassword=sippass\n",
            "etc/asterisk/echolink.conf": "[el0]\npwd = elpass\ncall = KD8PGK-L\n",
            "etc/asterisk/rpt.conf": "[1999]\nstatpost_url=http://s/?node=1999&pass=urlpass\n;secret = commented\n",
            "etc/asterisk/stock.conf": stock,
            "etc/asterisk/stock2.conf": stock + "bar=2\n",
            "opt/MMDVM_Bridge/MMDVM_Bridge.ini": "[DMR Network]\nPassword=bmpass\nCallsign=KD8PGK\n",
            "etc/wireguard/wg0.conf": "[Interface]\nPrivateKey = WGPRIV\n[Peer]\nPublicKey = WGPUB\nPresharedKey = WGPSK\n",
            "etc/allmon3/allmon3.ini": "[1999]\nuser=admin\npass=allpass\n",
            "etc/asl_dvs/phone.json": json.dumps({"sip": {"secret": "jsonpass", "user": "u"}}),
            "etc/NetworkManager/system-connections/home.nmconnection": "[wifi-security]\npsk=wifipass\n",
            "var/lib/dvswitch/dvs/var.txt": "bm_password=varpass\ncall_sign=KD8PGK\n",
            "etc/dvswitch/auth.key": "KEYFILE\n",
            "etc/asl_dvs/favorites.conf": ("[DMR_SERVERS]\n# name|password|address:port|network_url\n"
                                           "TGIF|TGIFPW|tgif.network:62031|https://tgif.network/activetg.php\n"
                                           "\n[DMR_SERVERS]\nFreeDMR|FREEDMRPW|freedmr.org:62031|https://freedmr.org\n"
                                           "\n[ASL]\nEast Coast|45192|rx=-3\n"),
            "etc/asl_dvs/contact.json": json.dumps({"email": "someone@example.com", "callsign": "KD8PGK"}),
            "etc/asl_dvs/mac.conf": "hwaddr = 88:a2:9e:61:20:3d\n",
            "etc/dvswitch/big.ini": "x" * 250000,
            "etc/shadow": "root:SHADOWLINE:1:0\n",
            "etc/systemd/system/cloudflared.service": "[Service]\nExecStart=/usr/bin/cloudflared --token eyJTOKEN run\n",
            "var/lib/dpkg/status": ("Package: asl3\nConffiles:\n /etc/asterisk/stock.conf %s\n /etc/asterisk/stock2.conf %s\n\n"
                                    % (hashlib.md5(stock.encode()).hexdigest(), hashlib.md5(stock.encode()).hexdigest())),
        }
        for rel, text in files.items():
            p = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)
        with open(os.path.join(self.root, "etc/dvswitch/blob.ini"), "wb") as f:
            f.write(b"abc\0def")
        os.symlink(os.path.join(self.root, "etc/shadow"), os.path.join(self.root, "etc/dvswitch/evil.ini"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self, *args):
        env = dict(os.environ, CONFGETTER_ROOT=self.root)
        r = subprocess.run(["bash", self.script, "--out", self.out, *args], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        snaps = sorted(f for f in os.listdir(self.out) if f.startswith("confgetter_") and f.endswith(".md"))
        with open(os.path.join(self.out, snaps[-1])) as f:
            return f.read(), snaps

    def test_secrets_redacted(self):
        text, _ = self.run_it()
        for s in SECRETS:
            self.assertNotIn(s, text, s)
        self.assertIn("WGPUB", text)
        self.assertIn("KD8PGK", text)
        self.assertIn("TGIF|<redacted:", text)
        self.assertIn("FreeDMR|<redacted:", text)
        self.assertIn("East Coast|45192|rx=-3", text)
        self.assertIn("hwaddr = 88:a2:9e:xx:xx:xx", text)
        self.assertIn("<redacted:", text)

    def test_redaction_count_and_same_tag(self):
        import re
        text, _ = self.run_it()
        body = text.split("## Manifest", 1)[1]
        header = int(re.search(r"Secrets: (\d+) values replaced", text).group(1))
        self.assertEqual(header, len(re.findall(r"<redacted:[0-9a-f]{8}>", body)))
        iax = re.search(r"### /etc/asterisk/iax.conf\n\n```\n\[general\]\nsecret = (<redacted:[0-9a-f]{8}>)", text).group(1)
        dup = re.search(r"### /etc/asterisk/dup.conf\n\n```\n\[x\]\nsecret = (<redacted:[0-9a-f]{8}>)", text).group(1)
        self.assertEqual(iax, dup)

    def test_files_and_skips(self):
        text, _ = self.run_it()
        self.assertIn("### /etc/asterisk/rpt.conf", text)
        self.assertIn("### /etc/asterisk/stock2.conf", text)
        self.assertNotIn("### /etc/asterisk/stock.conf", text)
        self.assertIn("| /etc/asterisk/stock.conf | same as the package default |", text)
        self.assertIn("| /etc/dvswitch/auth.key | secret or backup file, never copied |", text)
        self.assertIn("| /etc/dvswitch/blob.ini | binary file |", text)
        self.assertIn("| /etc/dvswitch/evil.ini | points outside the config folders, never copied |", text)
        self.assertIn("trimmed to 200000 bytes", text)
        self.assertIn("unit file /etc/systemd/system/cloudflared.service", text)

    def test_private_and_retention(self):
        os.makedirs(self.out)
        for i in range(3):
            p = os.path.join(self.out, "confgetter_old_2026010%d-000000.md" % i)
            with open(p, "w") as f:
                f.write("old")
            os.utime(p, (1000 + i, 1000 + i))
        _, snaps = self.run_it("--keep", "2")
        self.assertEqual(len(snaps), 2)
        self.assertIn("confgetter_old_20260102-000000.md", snaps)
        newest = [s for s in snaps if "old" not in s][0]
        self.assertEqual(os.stat(os.path.join(self.out, newest)).st_mode & 0o777, 0o600)
        self.assertEqual([f for f in os.listdir(self.out) if f.endswith(".tmp")], [])


class NodeTalkerCardTests(unittest.TestCase):
    CARDS = {
        "cd-setup": ["cfg-port", "cfg-udp_port", "cfg-https", "cfg-public_listen", "setup-save"],
        "cd-rx": ["cfg-max_listeners", "cfg-kerchunk_delay_ms", "play-spec", "hs-out", "ap-out", "hs-names",
                  "tune-on-rx", "tune-rx", "tune-jit", "rx-hpf", "rx-agc", "rx-gate", "rx-notch", "rx-save", "rxh-verdict", "rxh-rows", "nd-select"],
        "cd-tx": ["tune-on", "tune-tx", "tune-txbuf", "cfg-tot_sec", "cfg-busy_lockout", "ptt-hold", "ptt-gap",
                  "hs-mic", "hs-btn", "mic-gain", "mic-test", "tx-add", "tune-save"],
        "cd-chk": ["test-on-check", "test-on-balance", "test-on-tone_rx", "test-on-tone_tx", "test-on-mic", "test-on-node",
                   "test-on-kerchunk", "tests-save", "chk-start", "chk-stop", "chk-mins", "exp-tone", "exp-bal",
                   "chk-rx", "rx-bal-msg", "chk-tx", "tx-bal-msg", "rx-auto", "rx-auto-msg", "tx-auto", "tx-auto-msg",
                   "tone-start", "tone-hz", "tone-sec", "tone-rep", "tone-msg", "tx-tone-start", "tx-tone-hz", "tx-tone-sec",
                   "tx-tone-rep", "tx-link-node", "tx-link-connect", "tx-link-disconnect", "node-test"],
        "cd-data": ["data-dl", "data-msg"],
    }

    def setUp(self):
        import glob
        path = sorted(glob.glob(os.path.join(HERE, "..", "nodetalker_v*.py")))[-1]
        with open(path, encoding="utf-8") as fh:
            self.text = fh.read()
        self.cards = [(m.start(), m.group(1)) for m in re.finditer(r'<div class="card fold" id="(cd-[a-z]+)">', self.text)]

    def owner(self, element_id):
        pos = self.text.index('id="%s"' % element_id)
        return max((c for c in self.cards if c[0] < pos), key=lambda c: c[0])[1]

    def test_settings_sit_in_their_cards(self):
        for card, ids in self.CARDS.items():
            for element_id in ids:
                self.assertEqual(self.owner(element_id), card, element_id)

    def test_audio_check_and_expanded_test_share_one_start(self):
        self.assertNotIn('id="cd-exp"', self.text)
        self.assertNotIn('id="exp-start"', self.text)
        self.assertEqual(self.owner("chk-start"), "cd-chk")

    def test_tone_link_route_is_writable_only_locally(self):
        self.assertIn('"/api/tonetest/link"', self.text)
        self.assertIn('"/api/tonetest/stop", "/api/tonetest/link") and self._wan()', self.text)

    def test_status_polling_slows_down_only_when_settled(self):
        self.assertIn("pollEvery(pollStatus, 1500, 5000);", self.text)
        self.assertIn("pollEvery(pollLog, 3000, 10000);", self.text)

    def test_first_open_setup_popup_is_wired(self):
        self.assertIn('setup_mark(True)', self.text)
        self.assertIn('"/api/setup/apply": (lambda b: setup_apply(), (OSError,)),', self.text)
        self.assertIn('<dialog id="setup-dlg"', self.text)
        self.assertIn('setupCheck();', self.text)

    def test_no_clipboard_copies_of_data(self):
        for gone in ('id="chk-copy"', 'id="chk-copy-card"', 'id="kc-copy"', 'id="kc-json"', 'id="rxh-dl"', 'id="chk-export"',
                     "function addCopyAll", "function copyCard", "function kcCopy"):
            self.assertNotIn(gone, self.text)
        self.assertIn("async function dataDownload()", self.text)

    def test_mic_test_records_20_seconds(self):
        self.assertIn("Test mic (20 s, plays back)", self.text)
        self.assertIn("Recording 20 s", self.text)


def load_nodetalker():
    import glob
    import importlib.util
    path = sorted(glob.glob(os.path.join(HERE, "..", "nodetalker_v*.py")))[-1]
    spec = importlib.util.spec_from_file_location("nodetalker_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    old = {k: os.environ.get(k) for k in ("NODETALKER_SUITELOG", "NODETALKER_SUITELOG_FLAG")}
    tmp = tempfile.mkdtemp()
    os.environ["NODETALKER_SUITELOG"] = os.path.join(tmp, "suitelog.jsonl")
    os.environ["NODETALKER_SUITELOG_FLAG"] = os.path.join(tmp, "suitelog.on")
    try:
        spec.loader.exec_module(mod)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return mod


def suitelog_env(case, nt, collecting=True, seg=None):
    d = tempfile.mkdtemp()
    case.addCleanup(shutil.rmtree, d, True)
    path, flag = os.path.join(d, "suitelog.jsonl"), os.path.join(d, "suitelog.on")
    if collecting:
        with open(flag, "w") as fh:
            fh.write("saltsalt")
    for name, value in (("SUITELOG_PATH", path), ("SUITELOG_FLAG", flag)) + ((("SUITELOG_SEG", seg),) if seg else ()):
        p = mock.patch.object(nt, name, value)
        p.start()
        case.addCleanup(p.stop)
    nt._sl_flag.update(at=-10.0, salt=None)
    nt._sl_ino["ino"] = None
    nt._kc_cache["rows"] = None
    return path, flag


class NodeTalkerBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def setUp(self):
        nt = self.nt
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = {"tx": {"defined": False, "ours": False, "ready": False},
                      "stanzas": [{"name": "1999", "outstream": ""}], "links": []}
        self.calls = []
        patches = {
            "SETUP_PATH": os.path.join(self.tmp.name, "setup.json"),
            "log_event": lambda *a, **k: None,
            "main_node": lambda: "1999",
            "tx_state": lambda main=None: dict(self.state["tx"]),
            "read_rpt": lambda: ([], self.state["stanzas"]),
            "_is_ours": lambda v: "--feed" in (v or ""),
            "tx_enable": lambda: self.calls.append("tx") or {"ok": True, "message": "tx"},
            "hook_enable": lambda n: self.calls.append("feed") or {"ok": True, "message": "feed"},
            "restart_asterisk": lambda: self.calls.append("restart") or {"ok": True, "message": "restart"},
            "ilink": lambda node, op, peer: self.calls.append(("ilink", op, peer)) or (True, ""),
            "rpt_links": lambda node, max_age=2.0: (True, [{"node": n} for n in self.state["links"]]),
            "bridge_nodes": lambda *a: {},
            "tuned_now": lambda running: "",
            "nc_running": lambda cached=False: False,
        }
        for name, value in patches.items():
            p = mock.patch.object(nt, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(nt.TALKER, "state", lambda: {"keyed": False})
        p.start()
        self.addCleanup(p.stop)
        nt.TONE_LINK["node"] = ""
        self.addCleanup(lambda: nt.TONE_LINK.update(node=""))

    def test_setup_lists_missing_steps_and_apply_runs_them(self):
        nt = self.nt
        nt.setup_mark(True)
        plan = nt.setup_plan()
        self.assertTrue(plan["pending"])
        self.assertEqual([s["id"] for s in plan["steps"]], ["tx", "feed"])
        self.assertTrue(nt.setup_apply()["ok"])
        self.assertEqual(self.calls, ["tx", "feed", "restart"])
        self.assertFalse(nt.setup_pending())

    def test_setup_clears_itself_when_nothing_is_missing(self):
        nt = self.nt
        self.state["tx"] = {"defined": True, "ours": True, "ready": True}
        self.state["stanzas"] = [{"name": "1999", "outstream": "python3,x,--feed,6200"}]
        nt.setup_mark(True)
        self.assertEqual(nt.setup_plan()["steps"], [])
        self.assertFalse(nt.setup_pending())

    def test_setup_is_blocked_by_a_foreign_feed(self):
        nt = self.nt
        self.state["stanzas"] = [{"name": "1999", "outstream": "/usr/bin/broadcastify"}]
        nt.setup_mark(True)
        self.assertTrue(nt.setup_plan()["blocked"])
        self.assertFalse(nt.setup_apply()["ok"])
        self.assertEqual(self.calls, [])

    def test_setup_reads_nothing_when_not_pending(self):
        nt = self.nt
        with mock.patch.object(nt, "tx_state", side_effect=AssertionError("read while not pending")):
            self.assertFalse(nt.setup_plan()["pending"])

    def test_tone_link_connect_takes_node_numbers_only(self):
        nt = self.nt
        for bad in ("12a", "12345678", "1921", "1999", "", "45001 x"):
            self.assertFalse(nt.tone_link_set({"action": "connect", "node": bad})["ok"], bad)
        self.assertTrue(nt.tone_link_set({"action": "connect", "node": "45001"})["ok"])
        self.assertEqual(nt.TONE_LINK["node"], "45001")
        self.assertIn(("ilink", 3, "45001"), self.calls)

    def test_tone_link_disconnect_only_drops_a_linked_node(self):
        nt = self.nt
        self.assertFalse(nt.tone_link_set({"action": "disconnect", "node": "45001"})["ok"])
        self.assertFalse(nt.tone_link_set({"action": "disconnect", "node": "4500; x"})["ok"])
        self.assertEqual(self.calls, [])
        self.state["links"] = ["45001"]
        self.assertTrue(nt.tone_link_set({"action": "disconnect", "node": "45001"})["ok"])
        self.assertEqual(self.calls, [("ilink", 1, "45001")])

    def test_transmit_node_comment_old_and_new_are_recognised(self):
        nt = self.nt
        for note, ours in [(nt.TX_NOTES[0], True), (nt.TX_NOTES[1], True), ("; someone else's node", False)]:
            lines, stanzas = nt.parse_rpt("\n".join(["[1999]", "duplex = 1", "", note, "[1921]", "rxchannel = USRP/127.0.0.1:34018:32018"]))
            s, _ = nt._tx_stanza(lines, stanzas)
            self.assertEqual(nt._tx_ours(lines, s), ours, note)
        self.assertIn("Node Talker", nt.TX_NOTE)

    def test_feed_comment_old_and_new_are_removed_with_the_line(self):
        nt = self.nt
        for note in nt.HOOK_NOTES:
            text = "\n".join(["[1999]", note, "outstreamcmd = /usr/bin/python3,/usr/local/bin/nodetalker,--feed,6200", "duplex = 1"])
            lines, stanzas = nt.parse_rpt(text)
            with mock.patch.object(nt, "_is_ours", lambda v: "--feed" in (v or "")):
                left, changed = nt._remove_ours(lines, stanzas)
            self.assertTrue(changed)
            self.assertEqual([ln for ln in left if ln.strip()], ["[1999]", "duplex = 1"], note)
        self.assertIn("Node Talker", nt.HOOK_NOTE)

    def test_tone_link_guard_allows_only_the_target_for_tx(self):
        nt = self.nt
        nt.TONE_LINK["node"] = "45001"
        self.state["links"] = ["1921", "45001"]
        self.assertEqual(nt.tone_link_block(tx=True), "")
        self.assertNotEqual(nt.tone_link_block(tx=False), "")
        self.state["links"] = ["1921", "45001", "77777"]
        self.assertIn("77777", nt.tone_link_block(tx=True))


NETSTATS_SAMPLE = """                               -------- LOCAL ---------------------  -------- REMOTE --------------------
Channel               RTT  Jit  Del  Lost   %  Drop  OOO  Kbytes  Jit  Del  Lost   %  Drop  OOO  Kbytes
IAX2/10.1.2.3:4569-1   42   12   60     3   1%     0    1      80    0    0     0   0%     0    0      70
IAX2/node2-7           Unknown 5 60 0 0% 0 0 12 0 0 0 0% 0 0 9
1 IAX channel(s) shown
"""


class RxHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def setUp(self):
        nt = self.nt
        self.rxh = nt.RxHealth()
        p = mock.patch.object(nt, "SUITELOG_PATH", os.devnull)
        p.start()
        self.addCleanup(p.stop)

    def verdict(self, net_ok=True):
        nt = self.nt
        return nt.rxh_verdict(nt.rxh_sum(self.rxh.window()), {"ok": net_ok, "why": ""})

    def feed(self, n, gap=0.02, start=100.0):
        t = start
        for _ in range(n):
            self.rxh.note_packet(t)
            t += gap
        return t

    def test_netstats_parser_reads_local_columns(self):
        rows = self.nt.parse_netstats(NETSTATS_SAMPLE)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["rtt"], rows[0]["jit"], rows[0]["lost"], rows[0]["drop"], rows[0]["ooo"]), (42, 12, 3, 0, 1))
        self.assertIsNone(rows[1]["rtt"])

    def test_netstats_loss_counts_only_new_frames(self):
        rows = self.nt.parse_netstats(NETSTATS_SAMPLE)
        self.rxh.note_net(rows)
        self.assertEqual(self.rxh.cur["net_lost"], 0)
        rows[0]["lost"] += 5
        self.rxh.note_net(rows)
        self.assertEqual(self.rxh.cur["net_lost"], 5)
        self.assertEqual(self.rxh.cur["net_peers"], 2)

    def test_clean_audio_is_clean(self):
        self.feed(200)
        v = self.verdict()
        self.assertEqual(v["state"], "clean")

    def test_idle_without_audio(self):
        self.assertEqual(self.verdict()["state"], "idle")

    def test_gap_with_a_healthy_pi_is_the_network(self):
        t = self.feed(50)
        self.feed(50, start=t + 0.3)
        v = self.verdict()
        self.assertEqual(v["state"], "network")
        pi = next(r for r in v["rows"] if r["layer"] == "This Pi")
        self.assertEqual(pi["level"], "ok")

    def test_a_gap_longer_than_a_transmission_end_is_not_counted(self):
        t = self.feed(50)
        self.feed(50, start=t + 2.0)
        self.assertEqual(self.verdict()["state"], "clean")

    def test_pi_problem_wins_over_network(self):
        t = self.feed(50)
        self.feed(50, start=t + 0.3)
        self.rxh.note_tick(10.0)
        self.rxh.note_tick(10.3)
        self.assertEqual(self.verdict()["state"], "pi")

    def test_input_overflow_blames_the_pi(self):
        self.feed(50)
        self.rxh.note_drops(2, 0)
        self.assertEqual(self.verdict()["state"], "pi")

    def test_iax_loss_is_the_network(self):
        self.feed(50)
        rows = self.nt.parse_netstats(NETSTATS_SAMPLE)
        self.rxh.note_net(rows)
        rows[0]["lost"] += 2
        self.rxh.note_net(rows)
        self.assertEqual(self.verdict()["state"], "network")

    def test_slow_listener_with_clean_upstream_is_the_listener(self):
        self.feed(50)
        self.rxh.note_write(1.2)
        v = self.verdict()
        self.assertEqual(v["state"], "listener")
        self.assertIn("Not the Pi", v["text"])

    def test_client_underruns_with_clean_upstream_is_the_listener(self):
        self.feed(50)
        self.rxh.note_client(3, 1, 400)
        self.assertEqual(self.verdict()["state"], "listener")

    def test_unreadable_netstats_is_reported_not_blamed(self):
        self.feed(50)
        v = self.verdict(net_ok=False)
        self.assertEqual(v["state"], "clean")
        self.assertEqual(v["rows"][0]["level"], "warn")

    def test_phone_probe_and_network_log_are_kept_and_shown(self):
        nt = self.nt
        with mock.patch.object(nt, "RXH", self.rxh):
            nt.rxh_client({"client": "android", "probe_ms": 1500,
                           "net_log": "wifi>cell 12:03:11;bad entry;cell>wifi 12:04:00"})
        c = self.rxh.cur["clients"]["android"]
        self.assertEqual(c["probe_ms"], 1500)
        self.assertEqual(c["net_log"], "wifi>cell 12:03:11;cell>wifi 12:04:00")
        text = nt._rxh_phone_text(c)
        self.assertIn("network: wifi to cell at 12:03:11, cell to wifi at 12:04:00", text)
        self.assertIn("last report to the node took 1500 ms", text)

    def test_net_log_keeps_only_the_newest_valid_entries(self):
        nt = self.nt
        raw = ";".join(f"wifi>cell 00:00:{i:02d}" for i in range(20)) + ";<script>"
        kept = nt._net_log_clean(raw).split(";")
        self.assertEqual(len(kept), nt.RXH_NET_LOG_MAX)
        self.assertEqual(kept[-1], "wifi>cell 00:00:19")
        self.assertEqual(nt._net_log_clean(None), "")

    def test_client_report_is_checked_and_clamped(self):
        nt = self.nt
        with mock.patch.object(nt, "RXH", self.rxh):
            self.assertTrue(nt.rxh_client({"under": 2, "reset": 0, "silence_ms": 5})["ok"])
            with self.assertRaises(ValueError):
                nt.rxh_client({"under": "x"})
            nt.rxh_client({"under": 10 ** 12})
        self.assertLessEqual(self.rxh.cur["cl_under"], 2 + nt.RXH_CLIENT_MAX)

    def test_minute_rollover_keeps_history(self):
        self.feed(10)
        self.rxh.cur["t"] -= 60
        self.rxh.note_packet(500.0)
        self.assertEqual(len(self.rxh.buckets), 1)
        self.assertEqual(self.rxh.buckets[0]["pkts"], 10)


FIELD_FIXTURE = os.path.join(HERE, "fixtures", "rxhealth_field_20261102.json")

NETSTATS_LINKS = """                               -------- LOCAL ---------------------  -------- REMOTE --------------------
Channel               RTT  Jit  Del  Lost   %  Drop  OOO  Kbytes  Jit  Del  Lost   %  Drop  OOO  Kbytes
IAX2/10.1.2.3:4569-1   42   12   60     3   1%     0    1      80    0    0     0   0%     0    0      70
IAX2/node2-7           30    5   60     0   0%     0    0      12    0    0     0   0%     0    0       9
IAX2/45001-3          900  300   60    40  20%     6    2      30    0    0     0   0%     0    0      20
"""


class RxHealthFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()
        with open(FIELD_FIXTURE, encoding="utf-8") as fh:
            cls.cases = json.load(fh)["rows"]

    EXPECT = {"12:14": "network", "12:46": "pi", "13:30": "clean", "14:06": "listener", "14:11": "listener",
              "15:10": "listener", "15:52": "network", "18:36": "network", "17:33": "network"}

    def test_real_pi_minutes_get_the_right_verdict(self):
        nt = self.nt
        seen = set()
        for case in self.cases:
            key = case["at"][:5]
            seen.add(key)
            v = nt.rxh_verdict(nt.rxh_sum([case["row"]]), {"ok": True, "why": ""})
            self.assertEqual(v["state"], self.EXPECT[key], f"{case['at']}: {case['note']}")
        self.assertEqual(seen, set(self.EXPECT))

    def test_a_clean_real_minute_has_no_bad_row(self):
        nt = self.nt
        case = next(c for c in self.cases if c["at"].startswith("13:30"))
        v = nt.rxh_verdict(nt.rxh_sum([case["row"]]), {"ok": True, "why": ""})
        self.assertEqual([r["layer"] for r in v["rows"] if r["level"] == "bad"], [])

    def test_trim_after_a_gap_is_not_blamed_on_the_pi(self):
        nt = self.nt
        case = next(c for c in self.cases if c["at"].startswith("17:33"))
        v = nt.rxh_verdict(nt.rxh_sum([case["row"]]), {"ok": True, "why": ""})
        pi = next(r for r in v["rows"] if r["layer"] == "This Pi")
        self.assertEqual(pi["level"], "ok")

    def test_old_rows_without_the_new_fields_still_sum(self):
        nt = self.nt
        agg = nt.rxh_sum([c["row"] for c in self.cases])
        self.assertGreater(agg["net_lost"], 0)
        self.assertEqual(agg["links"], {})
        self.assertEqual(agg["clients"], {})


class RxHealthLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def setUp(self):
        self.rxh = self.nt.RxHealth()
        p = mock.patch.object(self.nt, "SUITELOG_PATH", os.devnull)
        p.start()
        self.addCleanup(p.stop)

    def test_link_key_drops_the_call_number(self):
        nt = self.nt
        self.assertEqual(nt.link_key("IAX2/10.1.2.3:4569-12"), "IAX2/10.1.2.3:4569")
        self.assertEqual(nt.link_key("IAX2/node2-7"), "IAX2/node2")
        self.assertEqual(nt.link_key("IAX2/45001-3"), "IAX2/45001")
        self.assertEqual(nt.link_key("IAX2/plain"), "IAX2/plain")

    def test_link_key_with_a_bare_trailing_dash(self):
        self.assertEqual(self.nt.link_key("IAX2/108.61.191.101:4569-"), "IAX2/108.61.191.101:4569")

    def test_loopback_link_is_not_a_peer(self):
        rows = [{"chan": "IAX2/127.0.0.1:4569-1", "lost": 0, "drop": 0, "ooo": 0, "jit": 5, "rtt": 0},
                {"chan": "IAX2/10.1.2.3:4569-2", "lost": 0, "drop": 0, "ooo": 0, "jit": 5, "rtt": 20}]
        self.rxh.note_net(rows)
        self.assertEqual(self.rxh.cur["net_peers"], 1)
        self.assertEqual(list(self.rxh.cur["links"]), ["IAX2/10.1.2.3:4569"])

    def test_rtt_of_1000_is_a_placeholder(self):
        rows = [{"chan": "IAX2/10.1.2.3:4569-2", "lost": 0, "drop": 0, "ooo": 0, "jit": 5, "rtt": 1000}]
        self.rxh.note_net(rows)
        self.assertEqual(self.rxh.cur["net_rtt_max"], 0)
        self.assertEqual(self.rxh.cur["links"]["IAX2/10.1.2.3:4569"]["rtt"], 0)
        rows[0]["rtt"] = 80
        self.rxh.note_net(rows)
        self.assertEqual(self.rxh.cur["net_rtt_max"], 80)

    def test_loss_is_kept_per_link(self):
        nt = self.nt
        rows = nt.parse_netstats(NETSTATS_LINKS)
        self.rxh.note_net(rows)
        for r in rows:
            if r["chan"].startswith("IAX2/45001"):
                r["lost"] += 25
                r["drop"] += 4
                r["jit"] = 700
        rows[0]["lost"] += 1
        self.rxh.note_net(rows)
        links = self.rxh.cur["links"]
        self.assertEqual(links["IAX2/45001"]["lost"], 25)
        self.assertEqual(links["IAX2/45001"]["drop"], 4)
        self.assertEqual(links["IAX2/45001"]["jit"], 700)
        self.assertEqual(links["IAX2/10.1.2.3:4569"]["lost"], 1)
        self.assertEqual(links["IAX2/node2"]["lost"], 0)
        self.assertEqual(self.rxh.cur["net_lost"], 26)

    def test_a_new_call_to_the_same_peer_keeps_one_link(self):
        nt = self.nt
        self.rxh.note_net(nt.parse_netstats(NETSTATS_LINKS))
        again = nt.parse_netstats(NETSTATS_LINKS.replace("45001-3", "45001-9"))
        again[2]["lost"] = 5
        self.rxh.note_net(again)
        self.assertEqual(self.rxh.cur["links"]["IAX2/45001"]["lost"], 0)

    def test_only_the_worst_links_are_kept(self):
        nt = self.nt
        rows = [{"chan": f"IAX2/n{i}-1", "rtt": 5, "jit": 1, "lost": 0, "pct": 0, "drop": 0, "ooo": 0} for i in range(12)]
        self.rxh.note_net(rows)
        for i, r in enumerate(rows):
            r["lost"] = i
        self.rxh.note_net(rows)
        links = self.rxh.cur["links"]
        self.assertEqual(len(links), nt.RXH_LINKS_MAX)
        self.assertIn("IAX2/n11", links)
        self.assertNotIn("IAX2/n1", links)

    def test_verdict_names_the_worst_link(self):
        nt = self.nt
        rows = nt.parse_netstats(NETSTATS_LINKS)
        self.rxh.note_packet(100.0)
        self.rxh.note_net(rows)
        rows[2]["lost"] += 30
        rows[1]["lost"] += 2
        self.rxh.note_net(rows)
        v = nt.rxh_verdict(nt.rxh_sum(self.rxh.window()), {"ok": True, "why": ""})
        row = next(r for r in v["rows"] if r["layer"].startswith("Outside"))
        self.assertIn("IAX2/45001", row["text"])
        self.assertIn("2 of 3 links", row["text"])

    def test_links_merge_across_minutes(self):
        nt = self.nt
        a = {"links": {"IAX2/a": {"lost": 3, "drop": 0, "ooo": 1, "jit": 10, "rtt": 50}}}
        b = {"links": {"IAX2/a": {"lost": 4, "drop": 1, "ooo": 0, "jit": 30, "rtt": 40}, "IAX2/b": {"lost": 0, "drop": 0, "ooo": 0, "jit": 1, "rtt": 2}}}
        agg = nt.rxh_sum([a, b])
        self.assertEqual(agg["links"]["IAX2/a"], {"lost": 7, "drop": 1, "ooo": 1, "jit": 30, "rtt": 50})
        self.assertEqual(set(agg["links"]), {"IAX2/a", "IAX2/b"})

    def test_minute_row_in_the_suite_log_carries_the_links_and_clients(self):
        nt = self.nt
        path, _ = suitelog_env(self, nt)
        row = self.rxh._new(1000)
        row["pkts"] = 5
        row["links"] = {"IAX2/a": {"lost": 1, "drop": 0, "ooo": 0, "jit": 2, "rtt": 3}}
        row["clients"] = {"android": {"under": 1, "reset": 0, "silence_ms": 5, "under_local": 0, "stall_ms": 900,
                                      "out_stalls": 0, "out_ms": 0}}
        nt._rxh_write(row)
        got = list(nt.suitelog_rows(path, ("rxh",)))[0]
        self.assertEqual((got["src"], got["v"]), ("nodetalker", nt.VERSION))
        self.assertEqual(got["data"]["links"]["IAX2/a"]["lost"], 1)
        self.assertEqual(got["data"]["clients"]["android"]["stall_ms"], 900)

    def test_nothing_is_written_while_collection_is_stopped(self):
        nt = self.nt
        path, _ = suitelog_env(self, nt, collecting=False)
        nt._rxh_write({"t": 1})
        self.assertFalse(os.path.exists(path))
        rep = nt.rxh_report()
        self.assertTrue(rep["ok"])

    def test_the_report_reads_the_suite_log(self):
        nt = self.nt
        suitelog_env(self, nt)
        for i in range(3):
            nt._rxh_write({"t": i, "pkts": i})
        self.assertEqual([r["t"] for r in nt.rxh_report()["rows"]], [0, 1, 2])

    def test_file_rotates_at_its_limit(self):
        nt = self.nt
        path, _ = suitelog_env(self, nt, seg=300)
        for i in range(10):
            nt._rxh_write({"t": i, "pad": "x" * 40})
        self.assertTrue(os.path.exists(path + ".1"))
        self.assertLess(os.path.getsize(path), 600)


class RxHealthClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def setUp(self):
        self.rxh = self.nt.RxHealth()
        p = mock.patch.object(self.nt, "RXH", self.rxh)
        p.start()
        self.addCleanup(p.stop)

    def test_client_name_comes_from_the_report_then_the_user_agent(self):
        nt = self.nt
        self.assertEqual(nt.rxh_client_name("android", ""), "android")
        self.assertEqual(nt.rxh_client_name("browser", "Dalvik/2.1"), "browser")
        self.assertEqual(nt.rxh_client_name("", "Mozilla/5.0 (X11)"), "browser")
        self.assertEqual(nt.rxh_client_name("", "Dalvik/2.1.0 (Linux; Android 14)"), "android")
        self.assertEqual(nt.rxh_client_name("<script>", "curl/8"), "other")
        self.assertEqual(nt.rxh_client_name(None, None), "other")

    def test_phone_network_report_is_kept_and_explained(self):
        nt = self.nt
        nt.rxh_client({"client": "android", "under": 2, "reset": 0, "silence_ms": 400, "reconn": 2, "why": "timeout",
                       "ttfb_ms": 900, "gap_ms": 5200, "net_chg": 1, "net": "wifi", "metered": 0, "vpn": 0, "psave": 1,
                       "idle": 0, "rssi_min": -78, "link_mbps": 24, "mhz": 2437})
        nt.rxh_client({"client": "android", "net": "cell", "link_mbps": 12, "rssi_min": 0, "why": "<b>"})
        agg = nt.rxh_sum(self.rxh.window())
        c = agg["clients"]["android"]
        self.assertEqual((c["reconn"], c["net_chg"], c["ttfb_ms"], c["gap_ms"]), (2, 1, 900, 5200))
        self.assertEqual((c["rssi_weak"], c["mhz"], c["link_mbps"], c["why"]), (78, 2437, 12, "timeout"))
        self.assertEqual((c["wifi"], c["cell"], c["psave"]), (1, 1, 1))
        text = nt._rxh_client_text(agg["clients"])
        for bit in ("mobile data", "-78 dBm", "2437 MHz", "reconnected 2x (last: timeout)", "5200 ms", "battery saver"):
            self.assertIn(bit, text)

    def test_phone_fields_are_optional_and_junk_is_ignored(self):
        nt = self.nt
        nt.rxh_client({"client": "android", "under": 1, "net": ["x"], "rssi_min": "bad", "psave": 7, "why": 5})
        c = self.rxh.cur["clients"]["android"]
        self.assertEqual((c["wifi"], c["cell"], c["rssi_weak"], c["psave"], c["why"]), (0, 0, 0, 1, ""))

    def test_report_is_kept_per_device_and_in_the_totals(self):
        nt = self.nt
        nt.rxh_client({"client": "android", "under": 3, "reset": 1, "silence_ms": 700, "under_local": 2, "stall_ms": 1300})
        nt.rxh_client({"client": "browser", "under": 1, "reset": 0, "silence_ms": 100})
        cur = self.rxh.cur
        self.assertEqual(cur["cl_under"], 4)
        self.assertEqual(cur["cl_under_local"], 2)
        self.assertEqual(cur["cl_stall_ms_max"], 1300)
        self.assertEqual(cur["clients"]["android"]["under"], 3)
        self.assertEqual(cur["clients"]["android"]["under_local"], 2)
        self.assertEqual(cur["clients"]["browser"]["under"], 1)

    def test_a_report_without_a_client_is_other_and_older_apps_still_work(self):
        nt = self.nt
        self.assertTrue(nt.rxh_client({"under": 1, "reset": 0, "silence_ms": 5})["ok"])
        self.assertEqual(self.rxh.cur["clients"]["other"]["under"], 1)

    def test_report_values_are_checked_and_clamped(self):
        nt = self.nt
        for key in ("under_local", "stall_ms"):
            with self.assertRaises(ValueError):
                nt.rxh_client({"client": "android", key: "x"})
        nt.rxh_client({"client": "android", "stall_ms": 10 ** 12, "under_local": -5})
        a = self.rxh.cur["clients"]["android"]
        self.assertEqual(a["stall_ms"], nt.RXH_CLIENT_MAX)
        self.assertEqual(a["under_local"], 0)

    def test_the_apps_report_keys_are_all_accepted(self):
        import re
        nt = self.nt
        text = ""
        for name in ("PlayStats.kt", "NetInfo.kt"):
            path = os.path.join(HERE, "..", "android", "app", "src", "main", "java", "io", "github", "kd8pgk", "nodetalker", name)
            with open(path, encoding="utf-8") as fh:
                text += fh.read()
        keys = set(re.findall(r'\\"(\w+)\\":', text))
        self.assertTrue(keys, "no keys found in PlayStats.json()")
        self.assertEqual(keys - set(nt.RXH_CLIENT_KEYS), set())

    def test_the_app_marks_its_listen_stream(self):
        path = os.path.join(HERE, "..", "android", "app", "src", "main", "java", "io", "github", "kd8pgk", "nodetalker", "ListenService.kt")
        with open(path, encoding="utf-8") as fh:
            self.assertIn("/api/listen?fmt=s16&client=android", fh.read())

    def test_the_page_names_itself_in_its_report(self):
        path = sorted(glob.glob(os.path.join(HERE, "..", "nodetalker_v*.py")))[-1]
        with open(path, encoding="utf-8") as fh:
            self.assertIn("client: 'browser'", fh.read())

    def test_listener_underruns_with_audio_waiting_blame_the_phone_itself(self):
        nt = self.nt
        self.rxh.note_packet(100.0)
        nt.rxh_client({"client": "android", "under": 2, "reset": 0, "silence_ms": 200, "under_local": 2, "stall_ms": 0})
        v = nt.rxh_verdict(nt.rxh_sum(self.rxh.window()), {"ok": True, "why": ""})
        self.assertEqual(v["state"], "listener")
        self.assertIn("phone itself", v["text"])
        row = next(r for r in v["rows"] if r["layer"].startswith("Phone"))
        self.assertIn("android", row["text"])

    def test_starved_underruns_blame_the_phones_connection(self):
        nt = self.nt
        self.rxh.note_packet(100.0)
        nt.rxh_client({"client": "android", "under": 2, "reset": 0, "silence_ms": 900, "under_local": 0, "stall_ms": 1800})
        v = nt.rxh_verdict(nt.rxh_sum(self.rxh.window()), {"ok": True, "why": ""})
        self.assertEqual(v["state"], "listener")
        self.assertIn("connection", v["text"])
        self.assertNotIn("phone itself", v["text"])

    def test_a_network_verdict_also_mentions_a_phone_problem(self):
        nt = self.nt
        self.rxh.note_packet(100.0)
        self.rxh.note_packet(100.3)
        nt.rxh_client({"client": "android", "under": 1, "reset": 0, "silence_ms": 90, "under_local": 0, "stall_ms": 500})
        v = nt.rxh_verdict(nt.rxh_sum(self.rxh.window()), {"ok": True, "why": ""})
        self.assertEqual(v["state"], "network")
        self.assertIn("phone also", v["text"])


class RxHealthSendQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def pair(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        cli = socket.create_connection(srv.getsockname())
        conn, _ = srv.accept()
        srv.close()
        self.addCleanup(cli.close)
        self.addCleanup(conn.close)
        return conn, cli

    def test_unsent_bytes_show_a_stalled_receiver(self):
        nt = self.nt
        conn, cli = self.pair()
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        cli.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        conn.setblocking(False)
        self.assertEqual(nt.sock_unsent(conn), 0)
        sent = 0
        try:
            while sent < 2000000:
                sent += conn.send(b"x" * 4096)
        except BlockingIOError:
            pass
        waiting = nt.sock_unsent(conn)
        self.assertGreater(waiting, 0)
        conn.setblocking(True)
        cli.settimeout(2)
        got = 0
        while got < sent:
            got += len(cli.recv(65536))
        time.sleep(0.2)
        self.assertEqual(nt.sock_unsent(conn), 0)

    def test_unsent_is_none_when_the_socket_cannot_say(self):
        nt = self.nt

        class Dead:
            def fileno(self):
                raise OSError("closed")

        self.assertIsNone(nt.sock_unsent(Dead()))

    def test_unsent_bytes_become_milliseconds_of_audio(self):
        nt = self.nt
        self.assertEqual(nt.rxh_outq_ms(8000, False), 1000)
        self.assertEqual(nt.rxh_outq_ms(8000, True), 500)
        self.assertEqual(nt.rxh_outq_ms(0, False), 0)

    def test_a_stall_is_counted_once_per_episode(self):
        nt = self.nt
        rxh = nt.RxHealth()
        state = {"on": False}
        for ms in (0, 100, 600, 900, 700, 200, 50, 800):
            state["on"] = nt.rxh_outq_note(rxh, "android", ms, state["on"])
        a = rxh.cur["clients"]["android"]
        self.assertEqual(a["out_stalls"], 2)
        self.assertEqual(a["out_ms"], 900)
        self.assertEqual(rxh.cur["out_stalls"], 2)
        self.assertEqual(rxh.cur["out_ms_max"], 900)

    def test_the_sampler_sees_a_stall_while_the_send_is_blocked(self):
        nt = self.nt
        conn, cli = self.pair()
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        cli.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        conn.setblocking(False)
        try:
            while True:
                conn.send(b"x" * 4096)
        except BlockingIOError:
            pass
        lst = nt._Listener("10.0.0.9", False)
        lst.sock = conn
        lst.client = "android"
        rxh = nt.RxHealth()
        with mock.patch.object(nt, "rxh_outq_ms", lambda unsent, pcm: 2000 if unsent else 0):
            nt.rxh_outq_sample(rxh, [lst])
            nt.rxh_outq_sample(rxh, [lst])
        self.assertTrue(lst.stalled)
        self.assertEqual(rxh.cur["clients"]["android"]["out_stalls"], 1)
        self.assertEqual(rxh.cur["out_ms_max"], 2000)

    def test_the_sampler_skips_listeners_without_a_socket(self):
        nt = self.nt
        rxh = nt.RxHealth()
        nt.rxh_outq_sample(rxh, [nt._Listener("10.0.0.9", False)])
        self.assertEqual(rxh.cur, None)

    def test_a_stalled_send_queue_blames_the_listeners_connection(self):
        nt = self.nt
        rxh = nt.RxHealth()
        rxh.note_packet(100.0)
        nt.rxh_outq_note(rxh, "android", 1500, False)
        v = nt.rxh_verdict(nt.rxh_sum(rxh.window()), {"ok": True, "why": ""})
        self.assertEqual(v["state"], "listener")
        row = next(r for r in v["rows"] if r["layer"] == "Pi to listener")
        self.assertEqual(row["level"], "bad")
        self.assertIn("1500", row["text"])


def load_wifimon():
    import importlib.util
    path = sorted(glob.glob(os.path.join(HERE, "..", "wifimon_v*.py")))[-1]
    spec = importlib.util.spec_from_file_location("wifimon_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    with mock.patch("signal.signal"):
        spec.loader.exec_module(mod)
    return mod


WIFI_SAMPLE = {"v": 1, "at": 0, "iface": "wlan0", "linked": True, "bssid_id": "a1b2c3d4", "band": "2.4 GHz", "channel": 6,
               "signal_dbm": -58, "noise_dbm": -92, "rx_bitrate": 65.0, "tx_bitrate": 72.2, "tx_packets": 1000,
               "tx_retries": 100, "tx_failed": 0, "beacon_loss": 0, "connected_secs": 600, "power_save": False,
               "blips": 0, "drops": 0, "chip_stalls": 0}


class WifimonLinkFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wm = load_wifimon()
        cls.nt = load_nodetalker()

    def fast(self, **kw):
        d = {"iface": "wlan0", "linked": True, "bssid": "aa:bb:cc:dd:ee:ff", "ssid_iw": "HomeNet", "freq_mhz": 2437,
             "signal_dbm": -61.0, "noise_dbm": -90.0, "rx_bitrate": 58.5, "tx_bitrate": 65.0, "tx_packets": 4000,
             "tx_retries": 300, "tx_failed": 2, "beacon_loss": 1, "connected_secs": 120, "mac": "11:22:33:44:55:66"}
        d.update(kw)
        return d

    def test_station_dump_gives_the_packet_count(self):
        out = self.wm._parse_station_dump("Station aa:bb (on wlan0)\n\tconnected time:\t120 seconds\n\ttx packets:\t5000\n"
                                          "\ttx retries:\t300\n\ttx failed:\t2\n\tbeacon loss:\t1\n")
        self.assertEqual(out["tx_packets"], 5000)
        self.assertEqual(out["tx_retries"], 300)

    def test_snapshot_carries_link_numbers_and_nothing_private(self):
        wm = self.wm
        snap = wm._wifi_link_snapshot(self.fast(), {"blips": 3, "drops": 1, "chip_stalls": 0}, {"power_save": True}, now=1000.0)
        self.assertEqual(snap["v"], 1)
        self.assertEqual(snap["at"], 1000.0)
        self.assertTrue(snap["linked"])
        self.assertEqual(snap["signal_dbm"], -61.0)
        self.assertEqual(snap["tx_retries"], 300)
        self.assertEqual((snap["blips"], snap["drops"]), (3, 1))
        self.assertEqual(snap["band"], "2.4 GHz")
        self.assertEqual(snap["channel"], 6)
        text = json.dumps(snap)
        for private in ("HomeNet", "aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"):
            self.assertNotIn(private, text)
        self.assertEqual(len(snap["bssid_id"]), 8)

    def test_same_access_point_keeps_the_same_id_and_another_changes_it(self):
        wm = self.wm
        a = wm._wifi_link_snapshot(self.fast(), {}, {}, now=1.0)["bssid_id"]
        b = wm._wifi_link_snapshot(self.fast(), {}, {}, now=2.0)["bssid_id"]
        c = wm._wifi_link_snapshot(self.fast(bssid="aa:bb:cc:dd:ee:00"), {}, {}, now=3.0)["bssid_id"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_snapshot_when_not_linked_has_no_link_numbers(self):
        snap = self.wm._wifi_link_snapshot({"iface": "wlan0", "linked": False}, {"blips": 1}, {}, now=5.0)
        self.assertFalse(snap["linked"])
        self.assertIsNone(snap["signal_dbm"])
        self.assertEqual(snap["blips"], 1)

    def test_file_is_written_whole_and_world_readable(self):
        wm = self.wm
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "run", "wifi_link.json")
        with mock.patch.object(wm, "WIFI_LINK_FILE", path):
            wm._wifi_link_write({"v": 1, "at": 1.0, "linked": True})
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["linked"], True)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_an_unwritable_run_directory_does_not_stop_the_collector(self):
        wm = self.wm
        with mock.patch.object(wm, "WIFI_LINK_FILE", "/proc/nope/wifi_link.json"):
            wm._wifi_link_write({"v": 1})

    def test_publish_uses_the_last_collected_numbers(self):
        wm = self.wm
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "wifi_link.json")
        with mock.patch.object(wm, "WIFI_LINK_FILE", path):
            wm._wifi_link_publish(self.fast())
            with open(path, encoding="utf-8") as fh:
                got = json.load(fh)
        self.assertEqual(got["tx_packets"], 4000)
        self.assertIn("blips", got)

    def test_every_key_node_talker_reads_is_written_by_wifimon(self):
        snap = self.wm._wifi_link_snapshot(self.fast(), {"blips": 0, "drops": 0, "chip_stalls": 0}, {"power_save": False}, now=1.0)
        self.assertEqual(set(self.nt.WIFI_LINK_KEYS) - set(snap), set())


class LinkLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def setUp(self):
        nt = self.nt
        nt._link_log.update(node=None, seen=None, gone={})
        self.links = []
        self.ok = True
        self.log = []
        favs = [{"mode": "ASL", "num": "45192", "label": "Allstar Hub"}]
        for q in (mock.patch.object(nt, "main_node", return_value="1999"),
                  mock.patch.object(nt, "rpt_links", side_effect=lambda node, max_age=2.0: (self.ok, list(self.links))),
                  mock.patch.object(nt, "bridge_nodes", return_value={"digital": "1950", "m17": "1951"}),
                  mock.patch.object(nt, "fav_load", return_value=favs),
                  mock.patch.object(nt, "astdb_name", side_effect=lambda n: {"2000": "Some Repeater"}.get(n, "")),
                  mock.patch.object(nt, "nc_running", return_value=False),
                  mock.patch.object(nt, "log_event", side_effect=lambda m, level="info": self.log.append((level, m)))):
            q.start()
            self.addCleanup(q.stop)

    def link(self, node, state="ESTABLISHED"):
        return {"node": node, "dir": "OUT", "time": "00:00:01", "state": state}

    def tick(self, n=1):
        for _ in range(n):
            self.nt.link_log_tick()

    def test_the_first_look_names_the_links_already_up(self):
        self.links = [self.link("45192"), self.link("2000")]
        self.tick()
        self.assertEqual(self.log, [("info", "Links now: Allstar Hub (node 45192), Some Repeater (node 2000)")])

    def test_no_links_at_the_start_logs_nothing(self):
        self.tick(2)
        self.assertEqual(self.log, [])

    def test_a_new_link_is_logged_with_its_name(self):
        self.tick()
        self.links = [self.link("45192")]
        self.tick()
        self.assertEqual(self.log, [("ok", "Link connected: Allstar Hub (node 45192)")])
        self.tick(3)
        self.assertEqual(len(self.log), 1)

    def test_a_link_that_is_connecting_then_connected(self):
        self.tick()
        self.links = [self.link("2000", "CONNECTING")]
        self.tick()
        self.links = [self.link("2000", "ESTABLISHED")]
        self.tick()
        self.assertEqual(self.log, [("info", "Link connecting: Some Repeater (node 2000)"),
                                    ("ok", "Link connected: Some Repeater (node 2000)")])

    def test_a_disconnect_is_logged_once_after_two_looks(self):
        self.links = [self.link("45192")]
        self.tick()
        self.log.clear()
        self.links = []
        self.tick()
        self.assertEqual(self.log, [])
        self.tick(3)
        self.assertEqual(self.log, [("info", "Link disconnected: Allstar Hub (node 45192)")])

    def test_a_one_look_gap_is_not_a_disconnect(self):
        self.links = [self.link("45192")]
        self.tick()
        self.log.clear()
        self.links = []
        self.tick()
        self.links = [self.link("45192")]
        self.tick(3)
        self.assertEqual(self.log, [])

    def test_a_link_that_never_connected_says_so(self):
        self.tick()
        self.links = [self.link("2000", "CONNECTING")]
        self.tick()
        self.links = []
        self.tick(2)
        self.assertEqual(self.log[-1], ("warn", "Link to Some Repeater (node 2000) did not connect"))

    def test_names_for_unknown_transmit_and_bridge_nodes(self):
        self.tick()
        self.links = [self.link("3000"), self.link("1921"), self.link("1950"), self.link("1951")]
        self.tick()
        self.assertEqual([m for _, m in self.log],
                         ["Link connected: node 3000", "Link connected: transmit node 1921",
                          "Link connected: digital bridge node 1950", "Link connected: M17 bridge node 1951"])

    def test_a_failed_look_changes_nothing(self):
        self.links = [self.link("45192")]
        self.tick()
        self.log.clear()
        self.ok = False
        self.links = []
        self.tick(5)
        self.assertEqual(self.log, [])
        self.ok = True
        self.links = [self.link("45192")]
        self.tick()
        self.assertEqual(self.log, [])

    def test_a_different_main_node_starts_again_quietly(self):
        nt = self.nt
        self.links = [self.link("45192")]
        self.tick()
        self.log.clear()
        with mock.patch.object(nt, "main_node", return_value="2999"):
            self.links = [self.link("2000")]
            self.tick()
        self.assertEqual(self.log, [("info", "Links now: Some Repeater (node 2000)")])


class PttLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def setUp(self):
        self.nt._ptt_log_times.clear()
        self.log = []
        q = mock.patch.object(self.nt, "log_event", side_effect=lambda m, level="info": self.log.append((level, m)))
        q.start()
        self.addCleanup(q.stop)

    def test_a_message_is_logged_with_its_level(self):
        nt = self.nt
        self.assertEqual(nt.ptt_log({"text": "Talk channel: refused. Retrying...", "level": "warn"}), {"ok": True, "n": 1})
        nt.ptt_log({"text": "Could not key", "level": "err"})
        nt.ptt_log({"text": "Opening the talk channel...", "level": "weird"})
        self.assertEqual(self.log, [("warn", "Talk button: Talk channel: refused. Retrying..."),
                                    ("err", "Talk button: Could not key"),
                                    ("info", "Talk button: Opening the talk channel...")])

    def test_control_characters_are_removed_and_the_length_is_capped(self):
        nt = self.nt
        nt.ptt_log({"text": "a\nb\x00c\x1b[31m" + "x" * 900})
        msg = self.log[0][1]
        self.assertNotIn("\n", msg)
        self.assertNotIn("\x00", msg)
        self.assertNotIn("\x1b", msg)
        self.assertEqual(len(msg), len("Talk button: ") + nt.PTT_LOG_MAX)

    def test_an_empty_or_bad_request_is_refused(self):
        nt = self.nt
        for bad in ({"text": ""}, {"text": "   "}, {}):
            with self.assertRaises(ValueError):
                nt.ptt_log(bad)
        with self.assertRaises(ValueError):
            nt.ptt_log("x")

    def test_a_flood_is_held_to_the_limit_a_minute(self):
        nt = self.nt
        sent = [nt.ptt_log({"text": f"m{i}"})["n"] for i in range(nt.PTT_LOG_PER_MIN + 10)]
        self.assertEqual(sum(sent), nt.PTT_LOG_PER_MIN)
        self.assertEqual(len(self.log), nt.PTT_LOG_PER_MIN)

    def test_the_route_is_registered_and_the_page_calls_it(self):
        nt = self.nt
        with open(nt.__file__, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('"/api/ptt/log": (ptt_log', text)
        self.assertIn("'/api/ptt/log'", text)


class ListenEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def setUp(self):
        self.path, _ = suitelog_env(self, self.nt)
        q = mock.patch.object(self.nt, "log_event")
        self.log = q.start()
        self.addCleanup(q.stop)

    def rows(self):
        return [r["data"] for r in self.nt.suitelog_rows(self.path, ("listen",))]

    def test_an_event_is_logged_and_written(self):
        nt = self.nt
        ev = {"action": "disconnect", "src": "system", "why": "process_killed", "t": int(time.time() * 1000),
              "detail": {"exit": "low_memory", "screen": 0, "fg": 0, "doze": 1, "net": "cell"}}
        self.assertEqual(nt.listen_event({"client": "android", "events": [ev]}), {"ok": True, "n": 1})
        row = self.rows()[0]
        self.assertEqual((row["client"], row["src"], row["action"], row["why"]), ("android", "system", "disconnect", "process_killed"))
        self.assertEqual(row["detail"]["exit"], "low_memory")
        self.assertIn("t", row)
        msg = self.log.call_args[0][0]
        for bit in ("disconnect", "android", "system", "process killed", "exit low_memory"):
            self.assertIn(bit, msg)

    def test_bad_events_are_dropped_and_unknown_reasons_become_other(self):
        nt = self.nt
        evs = [{"action": "connect", "src": "node", "why": "button"}, {"action": "poke", "src": "user"}, "x",
               {"action": "connect", "src": "user", "why": "<script>", "detail": {"err": "a<b>c;d" * 200, "up": "x", "vis": True,
                                                                              "screen": 10 ** 12, "zzz": 1}}]
        self.assertEqual(nt.listen_event({"client": "browser", "events": evs})["n"], 1)
        row = self.rows()[0]
        self.assertEqual(row["why"], "other")
        self.assertEqual(len(row["detail"]["err"]), nt.LISTEN_STR_MAX)
        self.assertNotIn("<", row["detail"]["err"])
        self.assertEqual(row["detail"]["screen"], nt.RXH_CLIENT_MAX)
        self.assertNotIn("zzz", row["detail"])
        self.assertNotIn("up", row["detail"])
        self.assertNotIn("vis", row["detail"])

    def test_events_must_be_a_list_and_a_batch_is_capped(self):
        nt = self.nt
        with self.assertRaises(ValueError):
            nt.listen_event({"events": "x"})
        evs = [{"action": "connect", "src": "user", "why": "button"}] * (nt.LISTEN_EVENTS_MAX + 5)
        self.assertEqual(nt.listen_event({"events": evs})["n"], nt.LISTEN_EVENTS_MAX)

    def test_a_far_off_phone_time_is_not_kept(self):
        self.nt.listen_event({"events": [{"action": "connect", "src": "user", "why": "button", "t": 1000}]})
        self.assertNotIn("t", self.rows()[0])

    def test_listen_events_wait_for_collection_to_start(self):
        nt = self.nt
        os.unlink(os.path.join(os.path.dirname(self.path), "suitelog.on"))
        nt._sl_flag.update(at=-10.0, salt=None)
        nt.listen_event({"events": [{"action": "connect", "src": "user", "why": "button"}]})
        self.assertEqual(self.rows(), [])

    def test_the_route_exists_and_the_page_names_every_start_and_stop(self):
        nt = self.nt
        with open(nt.__file__, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('"/api/listen/event": (listen_event', text)
        import re
        self.assertEqual(re.findall(r"\b(?:start|stop)Listen\(\)", text), [])
        for why in re.findall(r"(?:start|stop)Listen\('(?:system|user)', '(\w+)'\)", text):
            self.assertTrue(why == "retry" or why in nt.LISTEN_WHY, why)

    def test_page_events_are_system_only_and_known(self):
        nt = self.nt
        evs = [{"action": "page", "src": "system", "why": w, "detail": {"hid": 90, "gap": 20}}
               for w in ("page_hidden", "page_shown", "page_frozen", "page_resumed", "page_unload", "resumed_dead")]
        evs.append({"action": "page", "src": "user", "why": "page_hidden"})
        self.assertEqual(nt.listen_event({"client": "browser", "events": evs})["n"], 6)
        rows = self.rows()
        self.assertEqual([r["why"] for r in rows], ["page_hidden", "page_shown", "page_frozen", "page_resumed", "page_unload", "resumed_dead"])
        self.assertEqual(rows[1]["detail"], {"hid": 90, "gap": 20})

    def test_talk_events_keep_the_reason_and_log_failures_as_warnings(self):
        nt = self.nt
        evs = [{"action": "talk_fail", "src": "system", "why": "tls",
                "detail": {"err": "the certificate does not match pi", "n": 3, "code": 403, "net": "wifi"}},
               {"action": "talk_up", "src": "system", "why": "reconnected", "detail": {"secs": 42, "n": 3}},
               {"action": "talk_fail", "src": "system", "why": "new_reason_from_a_newer_app", "detail": {"n": 1}}]
        self.assertEqual(nt.listen_event({"client": "android", "events": evs})["n"], 3)
        rows = self.rows()
        self.assertEqual([(r["action"], r["why"]) for r in rows],
                         [("talk_fail", "tls"), ("talk_up", "reconnected"), ("talk_fail", "other")])
        self.assertEqual(rows[0]["detail"], {"err": "the certificate does not match pi", "n": 3, "code": 403, "net": "wifi"})
        self.assertEqual(rows[1]["detail"], {"secs": 42, "n": 3})
        self.assertEqual([c[0][1] for c in self.log.call_args_list], ["warn", "ok", "warn"])
        self.assertIn("talk_fail", self.log.call_args_list[0][0][0])
        self.assertIn("tls", self.log.call_args_list[0][0][0])

    def test_a_long_error_keeps_the_whole_address(self):
        nt = self.nt
        err = ("failed to connect to MagicBox.local (192.168.0.50, fe80:0:0:0:a2b:cff:fe00:1%wlan0): "
               "failed to connect to MagicBox.local/192.168.0.50 (port 8993) from /192.168.0.168 (port 40000) after 3000ms")
        nt.listen_event({"client": "android", "events": [{"action": "talk_fail", "src": "system", "why": "connect", "detail": {"err": err, "n": 1}}]})
        self.assertIn(err, self.log.call_args[0][0])
        kept = self.rows()[0]["detail"]["err"]
        self.assertIn("failed to connect to MagicBox.local", kept)
        self.assertIn("(port 8993)", kept)
        self.assertNotIn("192.168.0.50", kept)
        self.assertIn("ip:", kept)

    def test_the_app_talk_reports_agree_with_the_node(self):
        nt = self.nt
        base = os.path.join(HERE, "..", "android", "app", "src", "main", "java", "io", "github", "kd8pgk", "nodetalker")
        with open(os.path.join(base, "SocketErrors.kt"), encoding="utf-8") as fh:
            errs = fh.read()
        reasons = re.findall(r'const val [A-Z]+ = "(\w+)"', errs)
        self.assertIn("tls", reasons)
        for why in reasons:
            self.assertIn(why, nt.LISTEN_WHY)
        for why in set(reasons) - {"login"}:
            self.assertIn(why, nt._RXH_CLIENT_WHY)
        with open(os.path.join(base, "ListenService.kt"), encoding="utf-8") as fh:
            svc = fh.read()
        actions = re.findall(r'ListenLog\.talk\(this, "(\w+)"', svc)
        self.assertEqual(sorted(set(actions)), ["talk_fail", "talk_up"])
        for action in actions:
            self.assertIn(action, nt.LISTEN_ACTIONS)
        for why in re.findall(r'ListenLog\.talk\(this, "\w+", "(\w+)"', svc):
            self.assertIn(why, nt.LISTEN_WHY)
        keys = set(re.findall(r'\.put\("(err|n|code|secs)"', svc))
        self.assertEqual(keys, {"err", "n", "code", "secs"})
        self.assertEqual(keys - set(nt.LISTEN_DETAIL_NUM) - set(nt.LISTEN_DETAIL_STR), set())

    def test_the_page_declares_each_function_once(self):
        import collections
        names = re.findall(r"^(?:async )?function (\w+)", self.nt._JS, re.M)
        self.assertTrue(names)
        self.assertEqual({k: v for k, v in collections.Counter(names).items() if v > 1}, {})

    def test_every_app_call_the_page_makes_exists_in_the_app(self):
        nt = self.nt
        base = os.path.join(HERE, "..", "android", "app", "src", "main", "java", "io", "github", "kd8pgk", "nodetalker")
        with open(nt.__file__, encoding="utf-8") as fh:
            page = fh.read()
        with open(os.path.join(base, "TalkerActivity.kt"), encoding="utf-8") as fh:
            app = fh.read()
        offered = set(re.findall(r"@JavascriptInterface\s+fun (\w+)\(", app))
        used = set(re.findall(r"NodeTalkerApp\.(\w+)", page)) | set(re.findall(r"appCall\('(\w+)'", page))
        self.assertIn("copyText", used)
        self.assertEqual(used - offered, set())

    def test_the_app_spectrum_and_the_page_agree(self):
        import re
        nt = self.nt
        base = os.path.join(HERE, "..", "android", "app", "src", "main", "java", "io", "github", "kd8pgk", "nodetalker")
        with open(os.path.join(base, "Spectrum.kt"), encoding="utf-8") as fh:
            spec = fh.read()
        with open(os.path.join(base, "TalkerActivity.kt"), encoding="utf-8") as fh:
            talker = fh.read()
        with open(nt.__file__, encoding="utf-8") as fh:
            page = fh.read()
        bars = int(re.search(r"const val BARS = (\d+)", spec).group(1))
        lo = float(re.search(r"const val DB_LO = (-?[\d.]+)", spec).group(1))
        hi = float(re.search(r"const val DB_HI = (-?[\d.]+)", spec).group(1))
        self.assertEqual(int(re.search(r"const val N = (\d+)", spec).group(1)) // 2 % bars, 0)
        self.assertIn("analyser.minDecibels = %d;" % int(lo), page)
        self.assertIn("analyser.maxDecibels = %d;" % int(hi), page)
        self.assertIn("new Uint8Array(%d)" % bars, page)
        self.assertIn("fun specWanted(on: Boolean)", talker)
        self.assertIn("window.ntAppSpec", talker)
        self.assertIn("window.ntAppSpec = (", page)
        self.assertIn("NodeTalkerApp.specWanted(want)", page)

    def test_the_apps_event_keys_are_accepted(self):
        import re
        nt = self.nt
        base = os.path.join(HERE, "..", "android", "app", "src", "main", "java", "io", "github", "kd8pgk", "nodetalker")
        with open(os.path.join(base, "ListenLog.kt"), encoding="utf-8") as fh:
            text = fh.read()
        keys = set(re.findall(r'd\.put\("(\w+)"', text))
        self.assertTrue(keys)
        self.assertEqual(keys - set(nt.LISTEN_DETAIL_NUM) - set(nt.LISTEN_DETAIL_STR), set())
        with open(os.path.join(base, "ListenService.kt"), encoding="utf-8") as fh:
            svc = fh.read()
        for why in re.findall(r'logEnd\("(?:user|system)", "(\w+)"', svc):
            self.assertIn(why, nt.LISTEN_WHY)
        with open(os.path.join(base, "Bluetooth.kt"), encoding="utf-8") as fh:
            bt = fh.read()
        for why in re.findall(r'"(?:system|user)", "(\w+)"', bt):
            self.assertIn(why, nt.LISTEN_WHY)


LAUNCH_TARGET = '''import json, os, sys, threading
print(json.dumps({"pid": os.getpid(), "optimize": sys.flags.optimize, "argv": sys.argv[1:],
                  "arena": os.environ.get("MALLOC_ARENA_MAX"), "again": os.environ.get("ASL_DVS_LAUNCH"),
                  "name": __name__, "doc": (lambda: None).__doc__,
                  "trim": any(t.name == "mem-trim" for t in threading.enumerate())}))
'''


def launcher_code():
    import ast
    path = sorted(glob.glob(os.path.join(HERE, "..", "instmon_v*.py")))[-1]
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_LAUNCHER_CODE" for t in node.targets):
            return node.value.value
    raise AssertionError("no _LAUNCHER_CODE in instmon")


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.off = os.path.join(self.tmp.name, "launch_no_")
        code = launcher_code()
        self.assertIn('_OFF = "/etc/asl_dvs/launch_no_"', code)
        self.launcher = os.path.join(self.tmp.name, "launch.py")
        with open(self.launcher, "w") as f:
            f.write(code.replace('"/etc/asl_dvs/launch_no_"', repr(self.off)))

    def tearDown(self):
        self.tmp.cleanup()

    def run_target(self, name="target_tool.py", *flags):
        for flag in flags:
            open(self.off + flag, "w").close()
        target = os.path.join(self.tmp.name, name)
        with open(target, "w") as f:
            f.write(LAUNCH_TARGET)
        env = {k: v for k, v in os.environ.items() if k not in ("MALLOC_ARENA_MAX", "ASL_DVS_LAUNCH")}
        p = subprocess.Popen([sys.executable, self.launcher, target, "a1", "a2"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err)
        return p.pid, json.loads(out.strip().splitlines()[-1])

    def test_rerun_keeps_pid_and_applies_savers(self):
        pid, d = self.run_target()
        self.assertEqual(d["pid"], pid, "the re-run must keep the process ID for systemd")
        self.assertEqual(d["optimize"], 2)
        self.assertIsNone(d["doc"])
        self.assertIsNone(d["arena"], "the arena cap must not pass to child processes")
        self.assertIsNone(d["again"])
        self.assertTrue(d["trim"])
        self.assertEqual(d["argv"], ["a1", "a2"])
        self.assertEqual(d["name"], "__main__")

    def test_name_that_is_not_an_identifier(self):
        _, d = self.run_target("44target_v1.py")
        self.assertEqual(d["name"], "__main__")
        self.assertEqual(d["argv"], ["a1", "a2"])

    def test_off_switches(self):
        pid, d = self.run_target("target_tool.py", "optimize", "arena_cap", "trim")
        self.assertEqual(d["pid"], pid)
        self.assertEqual(d["optimize"], 0)
        self.assertFalse(d["trim"])

    def test_launcher_is_identical_in_every_tool(self):
        import ast
        texts = set()
        for path in glob.glob(os.path.join(HERE, "..", "*_v*.py")):
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_LAUNCHER_CODE"
                                                        for t in node.targets):
                    texts.add(node.value.value)
        self.assertEqual(len(texts), 1)


class SuiteLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def kc(self, i, label="", secs=0.5):
        return {"id": str(1000 + i), "secs": secs, "peak": -20.0, "kerchunk": secs < 0.8, "label": label,
                "source": "audio", "keyed_secs": None, "who": ""}

    def test_redaction_tags_addresses_and_hides_secrets(self):
        nt = self.nt
        text = ("Listener from 192.168.0.168 mac aa:bb:cc:dd:ee:ff at 12:34:56 v0.10.11 lo 127.0.0.1 ::1 "
                "v6 2001:db8::1 password=hunter2 token: \"abc def\" Authorization: Bearer xyz.123 ssid=\"My Net\"")
        got = nt.suitelog_redact(text, "salt1")
        for bit in ("192.168.0.168", "aa:bb:cc", "hunter2", "abc def", "xyz.123", "My Net", "2001:db8"):
            self.assertNotIn(bit, got)
        for bit in ("12:34:56", "v0.10.11", "127.0.0.1", " ::1 "):
            self.assertIn(bit, got)
        self.assertEqual(got, nt.suitelog_redact(text, "salt1"))
        self.assertNotEqual(got, nt.suitelog_redact(text, "salt2"))
        a = nt.suitelog_redact("a 10.1.2.3 b 10.1.2.3 c 10.1.2.4", "s")
        t1, t2, t3 = [w for w in a.split() if w.startswith("ip:")]
        self.assertEqual(t1, t2)
        self.assertNotEqual(t1, t3)

    def test_rows_come_back_in_order_across_both_segments(self):
        nt = self.nt
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "s.jsonl")
        rotated = [nt.suitelog_append(path, {"kind": "a", "n": i}, None, 200) for i in range(12)]
        self.assertTrue(any(rotated))
        with open(path, "a") as fh:
            fh.write("not json\n")
        rows = list(nt.suitelog_rows(path))
        ns = [r["n"] for r in rows]
        self.assertEqual(ns, sorted(ns))
        self.assertEqual(ns[-1], 11)
        self.assertEqual(len(list(nt.suitelog_rows(path, ("b",)))), 0)
        self.assertTrue(all("t" in r for r in rows))

    def test_a_held_lock_does_not_stall_the_writer(self):
        import fcntl
        nt = self.nt
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "s.jsonl")
        held = os.open(path + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, held)
        fcntl.flock(held, fcntl.LOCK_EX)
        t0 = time.monotonic()
        nt.suitelog_append(path, {"kind": "a", "n": 1}, None, 100000)
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual([r["n"] for r in nt.suitelog_rows(path)], [1])

    def test_the_total_stays_inside_two_segments_and_no_line_is_torn(self):
        import threading
        nt = self.nt
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "s.jsonl")

        def writer(k):
            for i in range(300):
                nt.suitelog_append(path, {"kind": "w", "k": k, "i": i, "pad": "x" * 30}, None, 6000)

        ts = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        for name in (path, path + ".1"):
            self.assertLess(os.path.getsize(name), 6000 + 200)
            with open(name) as fh:
                for ln in fh:
                    json.loads(ln)

    def test_the_flag_gives_the_salt(self):
        nt = self.nt
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        flag = os.path.join(d, "on")
        self.assertIsNone(nt.suitelog_flag(flag))
        with open(flag, "w") as fh:
            fh.write("abc123\n")
        self.assertEqual(nt.suitelog_flag(flag), "abc123")

    def test_kerchunk_bursts_are_written_even_when_collection_is_stopped(self):
        nt = self.nt
        path, _ = suitelog_env(self, nt, collecting=False)
        nt._kc_write_row(self.kc(1))
        nt._kc_write_row(self.kc(2, "kerchunk"))
        self.assertEqual([r["kind"] for r in nt.suitelog_rows(path)], ["kc", "kc"])
        nt._kc_cache["rows"] = None
        self.assertEqual([r["id"] for r in nt._kc_rows()], ["1001", "1002"])
        self.assertEqual(nt._kc_rows()[1]["label"], "kerchunk")

    def test_labels_and_reset_are_rows_and_rebuild_the_table(self):
        nt = self.nt
        path, _ = suitelog_env(self, nt)
        for i in range(3):
            nt._kc_write_row(self.kc(i))
        self.assertTrue(nt._kc_set_label("1001", "real"))
        self.assertFalse(nt._kc_set_label("9999", "real"))
        nt._kc_cache["rows"] = None
        self.assertEqual([r["label"] for r in nt._kc_rows()], ["", "real", ""])
        self.assertEqual(nt.kerchunk_label({"id": "1002", "label": "kerchunk"})["message"], "Saved.")
        self.assertEqual(nt.kerchunk_reset()["message"], "Reset.")
        nt._kc_cache["rows"] = None
        self.assertEqual(nt._kc_rows(), [])
        nt._kc_write_row(self.kc(7))
        nt._kc_cache["rows"] = None
        self.assertEqual([r["id"] for r in nt._kc_rows()], ["1007"])
        kinds = [r["kind"] for r in nt.suitelog_rows(path)]
        self.assertIn("kc_label", kinds)
        self.assertIn("kc_reset", kinds)

    def test_the_old_csv_is_imported_once_and_kept_as_imported(self):
        nt = self.nt
        path, _ = suitelog_env(self, nt, collecting=False)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        csv_path = os.path.join(d, "nodetalker_bursts.csv")
        with open(csv_path, "w") as fh:
            fh.write("id,secs,peak_db,kerchunk,label,source,keyed_secs,who\n"
                     "1500,0.40,-20.0,1,kerchunk,keyed,0.35,45192\n"
                     "1600,2.10,-18.5,0,real,audio,,\n"
                     "bad line\n")
        with mock.patch.object(nt, "KERCHUNK_LOG_PATH", csv_path):
            nt._kc_init()
            rows = nt._kc_rows()
            self.assertEqual([(r["id"], r["label"], r["source"], r["keyed_secs"], r["who"]) for r in rows],
                             [("1500", "kerchunk", "keyed", 0.35, "45192"), ("1600", "real", "audio", None, "")])
            self.assertTrue(os.path.exists(csv_path + ".imported"))
            self.assertFalse(os.path.exists(csv_path))
            nt._kc_init()
            self.assertEqual(len(nt._kc_rows()), 2)
        nt._kc_cache["rows"] = None
        self.assertEqual(len(nt._kc_rows()), 2)

    def test_a_rotation_by_another_writer_does_not_lose_the_bursts(self):
        nt = self.nt
        path, _ = suitelog_env(self, nt, seg=2000)
        for i in range(3):
            nt._kc_write_row(self.kc(i))
        for i in range(60):
            nt._rxh_write({"t": i, "pad": "x" * 60})
        self.assertTrue(os.path.exists(path + ".1"))
        nt._kc_write_row(self.kc(9))
        for i in range(80):
            nt._rxh_write({"t": i, "pad": "x" * 60})
        nt._kc_write_row(self.kc(10))
        if os.path.exists(path + ".1"):
            os.unlink(path + ".1")
        nt._kc_cache["rows"] = None
        ids = [r["id"] for r in nt._kc_rows()]
        self.assertIn("1010", ids)
        self.assertEqual(ids[-1], "1010")
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids))

    def test_the_tab_data_still_reads_from_the_store(self):
        nt = self.nt
        suitelog_env(self, nt, collecting=False)
        nt._kc_write_row(self.kc(1, secs=0.3))
        nt._kc_write_row(self.kc(2, secs=2.0))
        got = nt.kerchunk_status()
        self.assertTrue(got["ok"])
        self.assertEqual(got["kerchunks_total"], 1)
        self.assertEqual(len(got["bursts"]), 2)


class InstmonSuiteLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp0 = tempfile.mkdtemp()
        cls.m = load_instmon({"INSTMON_LIBRARY_DIR": os.path.join(cls.tmp0, "lib"),
                              "INSTMON_CONFIG_DIR": os.path.join(cls.tmp0, "cfg")})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp0, True)

    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.d = d
        self.path = os.path.join(d, "run", "suitelog.jsonl")
        self.flag = os.path.join(d, "run", "suitelog.on")
        self.col = self.m.SuiteCollector(self.path, self.flag, 100000)
        p = mock.patch.object(self.m.SuiteCollector, "_launch")
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(self.m, "log_event")
        q.start()
        self.addCleanup(q.stop)

    def rows(self, kinds=None):
        return list(self.m.suitelog_rows(self.path, kinds))

    def test_start_writes_the_flag_with_a_salt_and_a_header_and_stop_removes_it(self):
        st = self.col.start()
        self.assertTrue(st["running"])
        salt = self.m.suitelog_flag(self.flag)
        self.assertTrue(salt and len(salt) >= 8)
        head = self.rows(("mark",))[0]
        self.assertEqual(head["data"]["event"], "collection_start")
        self.assertEqual(head["data"]["instmon"], self.m.VERSION)
        self.assertEqual(self.col.start()["since"], st["since"])
        st = self.col.stop()
        self.assertFalse(st["running"])
        self.assertIsNone(self.m.suitelog_flag(self.flag))
        self.assertEqual([r["data"]["event"] for r in self.rows(("mark",))], ["collection_start", "collection_stop"])

    def test_nothing_is_written_when_stopped(self):
        self.assertFalse(self.col.emit("journal:x", "info", "hello"))
        self.assertFalse(os.path.exists(self.path))

    def test_lines_are_redacted_and_cleaned(self):
        self.col.start()
        self.col.emit("journal:nodetalker", "info", "Listener connected from 192.168.0.168 \x1b[31mred\x1b[0m password=abc")
        row = self.rows(("log",))[0]
        self.assertNotIn("192.168.0.168", row["msg"])
        self.assertNotIn("abc", row["msg"])
        self.assertNotIn("\x1b", row["msg"])
        self.assertEqual((row["src"], row["lvl"]), ("journal:nodetalker", "info"))
        self.col.emit("journal:x", "info", "y" * 5000)
        self.assertEqual(len(self.rows(("log",))[-1]["msg"]), self.m.SL_LINE_MAX)

    def test_repeated_lines_collapse_into_one_row_with_a_count(self):
        self.col.start()
        for i in range(6):
            self.col.emit("journal:wifimon", "info", "[Nov  4 08:03:%02d] link flapping" % i, now=1000.0 + i)
        self.col.emit("journal:wifimon", "info", "something else", now=1010.0)
        logs = self.rows(("log",))
        self.assertEqual([r["msg"] for r in logs], ["[Nov  4 08:03:00] link flapping", "[Nov  4 08:03:00] link flapping",
                                                    "something else"])
        rep = logs[1]
        self.assertEqual((rep["n"], rep["rep"]), (6, True))

    def test_a_run_is_summarised_after_the_repeat_window(self):
        self.col.start()
        for i in range(3):
            self.col.emit("journal:a", "info", "same", now=2000.0 + i)
        self.col.flush_runs(now=2000.0 + self.m.SL_REPEAT_SEC + 1)
        self.assertEqual([r.get("n") for r in self.rows(("log",))], [None, 3])

    def test_a_chatty_source_is_limited_but_warnings_and_other_sources_are_not(self):
        self.col.start()
        big = "x" * 900
        sent = [self.col.emit("journal:chatty", "info", "%s %d" % (big, i), now=3000.0) for i in range(200)]
        self.assertIn(False, sent)
        self.assertTrue(self.col.emit("journal:chatty", "err", "boom", now=3000.0))
        self.assertTrue(self.col.emit("journal:quiet", "info", "fine", now=3000.0))
        self.assertTrue(self.col.emit("journal:chatty", "info", "next minute", now=3061.0))
        drops = self.rows(("drop",))
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0]["src"], "journal:chatty")
        self.assertGreater(drops[0]["n"], 0)
        self.assertEqual(self.col.status()["dropped"], drops[0]["n"])

    def test_journal_lines_become_rows(self):
        self.col.start()
        j = lambda **kw: json.dumps(kw)
        self.assertTrue(self.col.ingest_journal(j(MESSAGE="up", PRIORITY="6", _SYSTEMD_UNIT="nodetalker.service")))
        self.assertTrue(self.col.ingest_journal(j(MESSAGE=list(b"bytes msg"), PRIORITY="3", SYSLOG_IDENTIFIER="asterisk")))
        self.assertFalse(self.col.ingest_journal("not json"))
        self.assertFalse(self.col.ingest_journal(j(MESSAGE=5)))
        rows = self.rows(("log",))
        self.assertEqual([(r["src"], r["lvl"], r["msg"]) for r in rows],
                         [("journal:nodetalker", "info", "up"), ("journal:asterisk", "err", "bytes msg")])

    def test_kernel_lines_are_kept_by_severity_or_keyword(self):
        self.col.start()
        k = lambda msg, pr: self.col.ingest_journal(json.dumps({"MESSAGE": msg, "PRIORITY": pr}), kernel=True)
        self.assertTrue(k("brcmfmac: firmware crashed", "6"))
        self.assertTrue(k("Under-voltage detected!", "6"))
        self.assertTrue(k("something bad", "4"))
        self.assertFalse(k("eth0: link is up", "6"))
        self.assertFalse(k("debug chatter reset", "7"))
        self.assertEqual({r["src"] for r in self.rows(("log",))}, {"kernel"})

    def test_a_file_is_followed_from_its_last_lines_then_new_lines_and_rotation(self):
        self.col.start()
        log = os.path.join(self.d, "full")
        with open(log, "w") as fh:
            fh.write("".join("line %d\n" % i for i in range(80)))
        self.col.tail_once([log])
        got = [r["msg"] for r in self.rows(("log",))]
        self.assertEqual(len(got), self.m.SL_TAIL_FIRST)
        self.assertEqual(got[-1], "line 79")
        with open(log, "a") as fh:
            fh.write("new one\nERROR bad thing\n")
        self.col.tail_once([log])
        last = self.rows(("log",))[-2:]
        self.assertEqual([(r["msg"], r["lvl"]) for r in last], [("new one", "info"), ("ERROR bad thing", "err")])
        os.replace(log, log + ".1")
        with open(log, "w") as fh:
            fh.write("after rotation\n")
        self.col.tail_once([log])
        self.assertEqual(self.rows(("log",))[-1]["msg"], "after rotation")
        with open(log, "w") as fh:
            fh.write("shorter\n")
        self.col.tail_once([log])
        self.assertEqual(self.rows(("log",))[-1]["msg"], "shorter")
        self.col.tail_once([os.path.join(self.d, "missing")])

    def test_wifi_samples_keep_only_the_useful_fields(self):
        self.col.start()
        wf = os.path.join(self.d, "wifi_link.json")
        with open(wf, "w") as fh:
            json.dump({"v": 1, "linked": True, "band": "2.4 GHz", "channel": 1, "signal_dbm": -41, "ssid": "My Net",
                       "bssid_id": "a1b2", "tx_packets": 100, "tx_retries": 9}, fh)
        with mock.patch.object(self.m, "SL_WIFI_FILE", wf):
            self.assertTrue(self.col.sample_wifi())
        row = self.rows(("wifi",))[0]
        self.assertEqual(row["data"], {"linked": True, "band": "2.4 GHz", "channel": 1, "signal_dbm": -41,
                                       "tx_packets": 100, "tx_retries": 9})
        with mock.patch.object(self.m, "SL_WIFI_FILE", os.path.join(self.d, "none")):
            self.assertFalse(self.col.sample_wifi())

    def test_clear_keeps_only_the_kerchunk_rows(self):
        self.col.start()
        self.col.emit("journal:a", "info", "bye")
        for r in ({"kind": "kc_base", "data": {}}, {"kind": "kc", "data": {"id": "1"}},
                  {"kind": "kc_label", "data": {"id": "1", "label": "real"}}):
            self.m.suitelog_append(self.path, dict(r, src="nodetalker"), None, 100000)
        st = self.col.clear()
        self.assertEqual([r["kind"] for r in self.rows()], ["kc_base", "kc", "kc_label"])
        self.assertEqual(st["written"], 0)

    def test_a_held_lock_does_not_stall_the_writer(self):
        import fcntl
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        held = os.open(self.path + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, held)
        fcntl.flock(held, fcntl.LOCK_EX)
        t0 = time.monotonic()
        self.m.suitelog_append(self.path, {"kind": "a", "src": "x", "data": {"n": 1}}, None, 100000)
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual([r["data"]["n"] for r in self.rows(("a",))], [1])

    def test_the_total_is_held_to_two_segments(self):
        col = self.m.SuiteCollector(self.path, self.flag, 4000)
        col.start()
        for i in range(400):
            col.emit("journal:a", "info", "row %d %s" % (i, "z" * 50), now=5000.0 + i * 61)
        self.assertLessEqual(col.size(), 2 * 4000 + 400)
        self.assertEqual(col.status()["cap"], 8000)

    def test_a_flag_left_by_a_restart_is_resumed_with_the_same_salt(self):
        os.makedirs(os.path.dirname(self.flag))
        with open(self.flag, "w") as fh:
            fh.write("oldsalt99\n")
        self.assertTrue(self.col.resume_if_flagged())
        self.assertTrue(self.col.status()["running"])
        self.col.emit("journal:a", "info", "from 10.9.8.7")
        self.assertEqual(self.m.suitelog_flag(self.flag), "oldsalt99")
        self.assertIn(self.m.suitelog_redact("from 10.9.8.7", "oldsalt99"), self.rows(("log",))[-1]["msg"])
        self.col.stop()
        self.assertFalse(self.col.resume_if_flagged())

    def test_download_sends_both_segments_with_the_right_length(self):
        import io
        self.col.start()
        for i in range(5):
            self.col.emit("journal:a", "info", "row %d" % i, now=7000.0 + i * 61)
        os.replace(self.path, self.path + ".1")
        self.col.emit("journal:a", "info", "newest", now=8000.0)

        class Fake:
            def __init__(self):
                self.out = io.BytesIO()
                self.headers = {}
                self.wfile = self.out

            def send_response(self, code):
                self.code = code

            def send_header(self, k, v):
                self.headers[k] = v

            def end_headers(self):
                pass

        fake = Fake()
        with mock.patch.object(self.m, "SUITELOG", self.col):
            self.m.InstmonHandler._route_suitelog_download(fake)
        body = fake.out.getvalue()
        self.assertEqual(fake.code, 200)
        self.assertEqual(int(fake.headers["Content-Length"]), len(body))
        self.assertIn("attachment", fake.headers["Content-Disposition"])
        lines = [json.loads(ln) for ln in body.decode().splitlines() if ln.strip()]
        self.assertEqual(lines[-1]["msg"], "newest")
        self.assertEqual(lines[0]["kind"], "mark")

    def fill(self, n=40):
        self.col.start()
        base = time.time() + 1.0
        for i in range(n):
            lvl = "err" if i % 10 == 0 else "warn" if i % 5 == 0 else "info"
            self.col.emit("journal:nodetalker" if i % 2 else "journal:wifimon", lvl, "msg number %d" % i, now=base + i * 30)
        self.col._write({"kind": "rxh", "src": "nodetalker", "data": {"t": 1, "pkts": 3000, "net_lost": 7, "out_stalls": 2,
                                                                  "cl_under": 1, "gaps": 0}}, base + 40 * 30)
        return base

    def test_query_filters_orders_and_limits(self):
        base = self.fill()
        q = self.col.query
        allrows = q(limit=500)
        self.assertEqual(allrows["matched"], 42)
        self.assertEqual(allrows["rows"][0]["t"], max(r["t"] for r in allrows["rows"]))
        self.assertEqual(q(newest_first=False, limit=500)["rows"][0]["kind"], "mark")
        self.assertEqual(q(limit=5)["shown"], 5)
        self.assertTrue(q(limit=5)["truncated"])
        errs = q(levels=("err",), limit=500)
        self.assertEqual({r["lvl"] for r in errs["rows"]}, {"err"})
        self.assertEqual(errs["matched"], 4)
        one = q(srcs=("journal:wifimon",), limit=500)
        self.assertEqual({r["src"] for r in one["rows"]}, {"journal:wifimon"})
        self.assertEqual(q(text="NUMBER 7", limit=500)["matched"], 1)
        win = q(since=int((base + 60) * 1000), until=int((base + 150) * 1000), limit=500)
        self.assertTrue(win["rows"])
        self.assertTrue(all(base * 1000 + 60000 - 2 <= r["t"] <= base * 1000 + 150000 + 2 for r in win["rows"]))
        self.assertEqual(q(kinds=("rxh",))["matched"], 1)
        self.assertEqual(q(limit="x")["ok"], True)

    def test_query_reads_the_tail_for_a_recent_window_and_both_segments(self):
        col = self.m.SuiteCollector(self.path, self.flag, 3000)
        col.start()
        for i in range(120):
            col.emit("journal:a", "info", "row %03d %s" % (i, "q" * 40), now=1800000000.0 + i * 61)
        self.assertTrue(os.path.exists(self.path + ".1"))
        late = col.query(since=int((1800000000.0 + 100 * 61) * 1000), limit=500, newest_first=False)
        self.assertEqual(late["rows"][-1]["msg"], "row 119 " + "q" * 40)
        self.assertTrue(all("row" in r["msg"] for r in late["rows"][:3]))
        every = col.query(limit=500)
        self.assertGreater(every["matched"], late["matched"])
        self.assertLess(late["scanned"], every["scanned"] + 1)

    def test_query_builds_a_minute_strip(self):
        self.fill()
        d = self.col.query(strip=True, limit=500)
        self.assertTrue(d["strip"])
        self.assertEqual(sum(b["n"] for b in d["strip"]), 42)
        self.assertTrue(any(b.get("rxh", {}).get("net_lost") == 7 for b in d["strip"]))
        self.assertTrue(any(b["err"] for b in d["strip"]))
        self.assertEqual([b["m"] for b in d["strip"]], sorted(b["m"] for b in d["strip"]))

    def test_sources_are_counted_and_cached(self):
        self.fill()
        d = self.col.scan_sources(force=True)
        by = {a["src"]: a for a in d["sources"]}
        self.assertEqual(by["journal:wifimon"]["rows"], 20)
        self.assertEqual(by["journal:nodetalker"]["rows"], 20)
        self.assertEqual(by["nodetalker"]["rows"], 1)
        self.assertGreater(by["journal:wifimon"]["err"], 0)
        self.assertIn("rxh", {k["kind"] for k in d["kinds"]})
        self.col.emit("journal:late", "info", "x", now=1800001000.0)
        self.assertNotIn("journal:late", {a["src"] for a in self.col.scan_sources()["sources"]})
        self.assertIn("journal:late", {a["src"] for a in self.col.scan_sources(force=True)["sources"]})

    def test_coverage_names_seen_silent_missing_and_unreadable_sources(self):
        self.fill()
        logf = os.path.join(self.d, "seen.log")
        gone = os.path.join(self.d, "gone.log")
        quiet = os.path.join(self.d, "quiet.log")
        for p in (logf, quiet):
            with open(p, "w") as fh:
                fh.write("x\n")
        self.col.ingest_file_line(logf, "hello")
        with mock.patch.object(self.m, "SL_FILES", (logf, gone, quiet, os.path.join(self.d, "nomatch*"))), \
                mock.patch.object(self.m, "SL_UNITS", ("nodetalker", "wifimon", "ghost", "sleeper")), \
                mock.patch.object(self.m.SuiteCollector, "unit_states",
                                  staticmethod(lambda: {"nodetalker": ("loaded", "active"), "wifimon": ("loaded", "active"),
                                                        "sleeper": ("loaded", "active")})), \
                mock.patch.object(self.m.SuiteCollector, "unit_list", lambda self_: ["nodetalker", "wifimon", "ghost", "sleeper"]):
            early = {r["src"]: r["state"] for r in self.col.coverage(force=True)["rows"]}
            late = {r["src"]: r["state"] for r in self.col.coverage(now=self.col.since + 3600, force=True)["rows"]}
        self.assertEqual(early["journal:nodetalker"], "seen")
        self.assertEqual(early["journal:ghost"], "not installed")
        self.assertEqual(early["journal:sleeper"], "waiting")
        self.assertEqual(late["journal:sleeper"], "silent")
        self.assertEqual(early["file:" + logf], "seen")
        self.assertEqual(early["file:" + quiet], "waiting")
        self.assertEqual(late["file:" + quiet], "silent")
        self.assertEqual(early["file:" + gone], "not found")
        self.assertEqual(early["rows:rxh"], "seen")
        self.assertEqual(early["kernel"], "quiet")
        self.assertEqual(early["rows:listen"], "waiting")

    def test_a_time_limit_stops_collection_and_says_why(self):
        st = self.col.start(hours=2)
        self.assertEqual(st["until"], int(self.col.until))
        self.assertAlmostEqual(self.col.until - self.col.since, 7200, delta=2)
        self.assertTrue(os.path.exists(self.flag + ".until"))
        self.assertIsNone(self.col.guard_once(now=self.col.since + 3600, mem_kb=500000))
        self.assertEqual(self.col.guard_once(now=self.col.since + 7201, mem_kb=500000), "time")
        self.assertFalse(self.col.running())
        self.assertIn("2 hours", self.col.status()["last_stop"]["reason"])
        self.assertFalse(os.path.exists(self.flag + ".until"))
        self.assertEqual(self.rows(("mark",))[-1]["data"]["reason"], "auto-stop after 2 hours")

    def test_no_limit_when_hours_is_zero_and_the_default_is_twelve(self):
        self.col.start(hours=0)
        self.assertEqual(self.col.status()["until"], 0)
        self.col.stop()
        self.col.start()
        self.assertAlmostEqual(self.col.until - self.col.since, 12 * 3600, delta=2)
        self.col.stop()
        self.col.start(hours="junk")
        self.assertAlmostEqual(self.col.until - self.col.since, 12 * 3600, delta=2)

    def test_low_memory_stops_collection(self):
        self.col.start()
        self.assertEqual(self.col.guard_once(mem_kb=self.m.SL_MEM_FLOOR_KB - 1), "memory")
        self.assertFalse(self.col.running())
        self.assertIn("low memory", self.col.status()["last_stop"]["reason"])
        self.assertIsNone(self.col.guard_once(mem_kb=1))

    def test_a_restart_keeps_the_deadline(self):
        self.col.start(hours=1)
        until = self.col.until
        other = self.m.SuiteCollector(self.path, self.flag, 100000)
        with mock.patch.object(self.m.SuiteCollector, "_launch"):
            self.assertTrue(other.resume_if_flagged())
        self.assertAlmostEqual(other.until, until, delta=1)

    def test_throttle_flags_are_named(self):
        f = self.m.SuiteCollector.throttle_flags
        self.assertEqual(f(0), [])
        self.assertEqual(f(0x50005), ["under-voltage now", "throttled now", "under-voltage since boot",
                                      "throttled since boot"])

    def test_a_snapshot_has_the_health_numbers(self):
        with mock.patch.object(self.m.subprocess, "run") as run:
            def fake(cmd, **kw):
                class R:
                    stdout = ""
                r = R()
                if cmd[0] == "vcgencmd":
                    r.stdout = "throttled=0x50000\n"
                elif cmd[0] == "systemctl":
                    n = len(cmd) - 2
                    r.stdout = "\n".join(["active"] * n)
                return r
            run.side_effect = fake
            snap = self.col.snapshot()
        self.assertEqual(snap["throttled"]["raw"], "0x50000")
        self.assertIn("under-voltage since boot", snap["throttled"]["flags"])
        self.assertIn("/run", snap["disk"])
        self.assertIn("load", snap)
        self.assertTrue(snap["services"])
        self.col.start()
        self.col.emit("system", "info", "", kind="snap", data={"load": [0.1, 0.2, 0.3]})
        self.assertEqual(self.rows(("snap",))[0]["data"]["load"], [0.1, 0.2, 0.3])

    def test_the_viewer_page_has_copy_and_download_choices(self):
        m = self.m
        page = m.SUITELOG_PAGE
        for ident in ("a-copy-text", "a-copy-json", "a-dl-text", "a-dl-json", "a-dl-all", "f-around", "cov", "chips",
                      "strip", "f-live"):
            self.assertIn('id="%s"' % ident, page)
        self.assertIn("/api/suitelog/download", page)
        self.assertIn("execCommand('copy')", page)
        for path in ("/suitelog", "/api/suitelog/query", "/api/suitelog/sources", "/api/suitelog/coverage"):
            self.assertIn(path, m._GET_ROUTES)
        self.assertIn("sl-hours", m.HTML_TEMPLATE)
        self.assertIn("/suitelog", m.HTML_TEMPLATE)
        self.assertNotIn("innerHTML = r", page)

    def test_the_start_route_reads_the_hours(self):
        import io
        seen = []

        class Fake:
            headers = {"Content-Length": "14"}
            rfile = io.BytesIO(b'{"hours": 3.5}')

            def _send_json(self, code, payload):
                seen.append((code, payload))

        with mock.patch.object(self.m, "SUITELOG", self.col):
            self.m.InstmonHandler._route_suitelog_start(Fake())
        self.assertAlmostEqual(self.col.until - self.col.since, 3.5 * 3600, delta=2)
        self.assertEqual(seen[0][0], 200)

    def test_the_card_does_not_poll_before_login(self):
        m = self.m
        js = m._JS_SUITELOG
        self.assertNotIn("addEventListener('load'", js)
        self.assertNotIn("slPoll();\nsetInterval", js)
        start = m._JS.index("function _startApp()")
        body = m._JS[start:m._JS.index("\n}\n", start)]
        self.assertIn("slStart();", body)
        self.assertEqual(m._JS.count("slStart();"), 1)

    def test_the_card_and_routes_are_in_the_page(self):
        m = self.m
        self.assertIn("/api/suitelog/status", m._GET_ROUTES)
        self.assertIn("/api/suitelog/download", m._GET_ROUTES)
        for name in ("start", "stop", "clear"):
            self.assertIn("/api/suitelog/" + name, m._POST_ROUTES)
        for ident in ("sl-start", "sl-stop", "sl-dl", "sl-clear"):
            self.assertIn('id="%s"' % ident, m.HTML_TEMPLATE)
        self.assertIn("slAct", m._JS)


class RxHealthWifiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nt = load_nodetalker()

    def setUp(self):
        self.rxh = self.nt.RxHealth()
        p = mock.patch.object(self.nt, "SUITELOG_PATH", os.devnull)
        p.start()
        self.addCleanup(p.stop)

    def sample(self, **kw):
        d = dict(WIFI_SAMPLE)
        d.update(kw)
        return d

    def verdict(self):
        nt = self.nt
        return nt.rxh_verdict(nt.rxh_sum(self.rxh.window()), {"ok": True, "why": ""}, self.rxh.wifi_state())

    def wifi_row(self, v):
        return next(r for r in v["rows"] if r["layer"].startswith("This Pi's Wi-Fi"))

    def test_read_link_file_fresh_stale_missing_and_bad(self):
        nt = self.nt
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "wifi_link.json")
        with mock.patch.object(nt, "WIFI_LINK_PATH", path):
            self.assertEqual(nt.read_wifi_link(100.0), (None, "absent"))
            with open(path, "w") as fh:
                fh.write("not json")
            self.assertEqual(nt.read_wifi_link(100.0)[1], "unreadable")
            with open(path, "w") as fh:
                json.dump(dict(WIFI_SAMPLE, at=100.0), fh)
            got, why = nt.read_wifi_link(110.0)
            self.assertEqual((got["signal_dbm"], why), (-58, ""))
            self.assertEqual(nt.read_wifi_link(100.0 + nt.WIFI_STALE_SEC + 5)[1], "stale")
            with open(path, "w") as fh:
                json.dump(dict(WIFI_SAMPLE, at=100.0, v=99), fh)
            self.assertEqual(nt.read_wifi_link(110.0)[1], "unsupported")

    def test_first_sample_sets_the_baseline_only(self):
        self.rxh.note_wifi(self.sample(), None)
        cur = self.rxh.cur
        self.assertEqual((cur["wifi_retries"], cur["wifi_failed"], cur["wifi_beacon"]), (0, 0, 0))
        self.assertEqual(cur["wifi_samples"], 1)
        self.assertEqual(cur["wifi_weak"], 58)
        self.assertEqual(cur["wifi_rate_min"], 72)

    def test_counters_are_kept_as_changes(self):
        self.rxh.note_wifi(self.sample(), None)
        self.rxh.note_wifi(self.sample(tx_packets=1500, tx_retries=160, tx_failed=2, beacon_loss=1, blips=1, drops=1,
                                       chip_stalls=1, signal_dbm=-74, tx_bitrate=11.0), None)
        cur = self.rxh.cur
        self.assertEqual(cur["wifi_tx_pkts"], 500)
        self.assertEqual(cur["wifi_retries"], 60)
        self.assertEqual((cur["wifi_failed"], cur["wifi_beacon"]), (2, 1))
        self.assertEqual((cur["wifi_blips"], cur["wifi_drops"], cur["wifi_stalls"]), (1, 1, 1))
        self.assertEqual(cur["wifi_weak"], 74)
        self.assertEqual(cur["wifi_rate_min"], 11)

    def test_a_counter_that_restarts_is_not_a_negative_change(self):
        self.rxh.note_wifi(self.sample(tx_retries=5000, tx_packets=90000), None)
        self.rxh.note_wifi(self.sample(tx_retries=10, tx_packets=50, connected_secs=3), None)
        cur = self.rxh.cur
        self.assertEqual((cur["wifi_retries"], cur["wifi_tx_pkts"]), (0, 0))
        self.assertEqual(cur["wifi_rejoins"], 1)

    def test_a_new_access_point_is_a_roam_not_a_rejoin(self):
        self.rxh.note_wifi(self.sample(), None)
        self.rxh.note_wifi(self.sample(bssid_id="ffffffff", connected_secs=2), None)
        self.assertEqual(self.rxh.cur["wifi_roams"], 1)
        self.assertEqual(self.rxh.cur["wifi_rejoins"], 0)

    def test_not_linked_counts_as_down(self):
        self.rxh.note_wifi(self.sample(), None)
        self.rxh.note_wifi(self.sample(linked=False, signal_dbm=None, tx_bitrate=None, bssid_id=None), None)
        self.assertEqual(self.rxh.cur["wifi_down"], 1)

    def test_wifi_that_is_not_in_use_is_not_a_fault(self):
        self.rxh.note_packet(100.0)
        self.rxh.note_packet(100.3)
        for _ in range(3):
            self.rxh.note_wifi(self.sample(linked=False, signal_dbm=None, tx_bitrate=None, bssid_id=None), None)
        v = self.verdict()
        row = self.wifi_row(v)
        self.assertEqual(row["level"], "info")
        self.assertIn("not connected", row["text"])
        self.assertIn("Ethernet", row["text"])
        self.assertEqual(v["state"], "network")

    def test_losing_the_wifi_link_during_the_window_is_a_fault(self):
        self.rxh.note_packet(100.0)
        self.rxh.note_packet(100.3)
        self.rxh.note_wifi(self.sample(), None)
        self.rxh.note_wifi(self.sample(linked=False, signal_dbm=None, tx_bitrate=None, bssid_id=None), None)
        v = self.verdict()
        self.assertEqual(self.wifi_row(v)["level"], "bad")
        self.assertEqual(v["state"], "wifi")

    def test_no_file_is_reported_not_blamed(self):
        self.rxh.note_packet(100.0)
        self.rxh.note_wifi(None, "absent")
        v = self.verdict()
        row = self.wifi_row(v)
        self.assertEqual(row["level"], "info")
        self.assertIn("wifimon", row["text"])
        self.assertEqual(v["state"], "clean")

    def test_a_healthy_link_is_ok_and_shows_its_numbers(self):
        self.rxh.note_packet(100.0)
        self.rxh.note_wifi(self.sample(), None)
        self.rxh.note_wifi(self.sample(tx_packets=2000, tx_retries=200), None)
        row = self.wifi_row(self.verdict())
        self.assertEqual(row["level"], "ok")
        self.assertIn("-58 dBm", row["text"])
        self.assertIn("10 %", row["text"])

    def test_a_weak_signal_alone_does_not_change_a_clean_verdict(self):
        self.rxh.note_packet(100.0)
        self.rxh.note_wifi(self.sample(signal_dbm=-84), None)
        v = self.verdict()
        self.assertEqual(self.wifi_row(v)["level"], "bad")
        self.assertEqual(v["state"], "clean")

    def test_wifi_trouble_with_a_gap_blames_the_pis_wifi_not_the_internet(self):
        self.rxh.note_packet(100.0)
        self.rxh.note_packet(100.3)
        self.rxh.note_wifi(self.sample(), None)
        self.rxh.note_wifi(self.sample(beacon_loss=3, tx_failed=4), None)
        v = self.verdict()
        self.assertEqual(v["state"], "wifi")
        self.assertIn("Wi-Fi", v["text"])
        self.assertIn("Not the Pi's software", v["text"])

    def test_the_pi_still_comes_before_its_wifi(self):
        self.rxh.note_packet(100.0)
        self.rxh.note_drops(2, 0)
        self.rxh.note_wifi(self.sample(), None)
        self.rxh.note_wifi(self.sample(blips=2), None)
        self.assertEqual(self.verdict()["state"], "pi")

    def test_wifi_trouble_with_a_listener_stall_is_the_pis_wifi(self):
        self.rxh.note_packet(100.0)
        self.rxh.note_outq("android", 1500, True)
        self.rxh.note_wifi(self.sample(), None)
        self.rxh.note_wifi(self.sample(tx_packets=3000, tx_retries=1700), None)
        v = self.verdict()
        self.assertEqual(self.wifi_row(v)["level"], "bad")
        self.assertEqual(v["state"], "wifi")

    def feed_baseline(self, retries, failed, minutes=10, pkts=1000):
        for i in range(minutes):
            self.rxh.buckets.append(dict(self.rxh._new(1000 + i * 60), wifi_tx_pkts=pkts, wifi_retries=retries,
                                         wifi_failed=failed))
        for i in range(self.nt.RXH_WINDOW_MIN - 1):
            self.rxh.buckets.append(self.rxh._new(2000 + i * 60))

    def window_row(self, retries, failed, pkts=1000):
        self.rxh.note_wifi(self.sample(tx_packets=1000, tx_retries=0, tx_failed=0), None)
        self.rxh.note_wifi(self.sample(tx_packets=1000 + pkts, tx_retries=retries, tx_failed=failed), None)
        return self.wifi_row(self.verdict())

    def test_usual_retries_are_not_a_fault(self):
        self.feed_baseline(250, 30)
        r = self.window_row(300, 30)
        self.assertEqual(r["level"], "ok")
        self.assertIn("usual 25 %", r["text"])

    def test_retries_far_above_usual_are_a_fault(self):
        self.feed_baseline(250, 30)
        self.assertEqual(self.window_row(550, 30)["level"], "bad")

    def test_no_baseline_does_not_flag_moderate_retries(self):
        self.assertEqual(self.window_row(450, 0)["level"], "ok")

    def test_very_high_retries_are_a_fault_without_a_baseline(self):
        self.assertEqual(self.window_row(800, 0)["level"], "bad")

    def test_failed_sends_at_their_usual_rate_are_ok(self):
        self.feed_baseline(250, 30)
        self.assertEqual(self.window_row(250, 30)["level"], "ok")

    def test_failed_sends_well_above_usual_are_a_fault(self):
        self.feed_baseline(250, 30)
        self.assertEqual(self.window_row(250, 150)["level"], "bad")

    def test_band_and_channel_are_recorded_and_shown(self):
        self.rxh.note_wifi(self.sample(band="5 GHz", channel=149), None)
        self.assertEqual((self.rxh.cur["wifi_band"], self.rxh.cur["wifi_chan"]), ("5 GHz", 149))
        self.assertIn("5 GHz ch 149", self.wifi_row(self.verdict())["text"])
        self.assertIn("band", self.nt.WIFI_LINK_KEYS)
        self.assertIn("channel", self.nt.WIFI_LINK_KEYS)

    def test_few_packets_do_not_make_a_retry_percentage(self):
        self.rxh.note_packet(100.0)
        self.rxh.note_wifi(self.sample(tx_packets=10, tx_retries=1), None)
        self.rxh.note_wifi(self.sample(tx_packets=20, tx_retries=9), None)
        self.assertEqual(self.wifi_row(self.verdict())["level"], "ok")

    def test_wifi_numbers_merge_across_minutes(self):
        nt = self.nt
        a = {"wifi_retries": 5, "wifi_weak": 60, "wifi_rate_min": 54, "wifi_tx_pkts": 100}
        b = {"wifi_retries": 7, "wifi_weak": 75, "wifi_rate_min": 11, "wifi_tx_pkts": 50}
        c = {"wifi_rate_min": 0}
        agg = nt.rxh_sum([a, b, c])
        self.assertEqual((agg["wifi_retries"], agg["wifi_tx_pkts"]), (12, 150))
        self.assertEqual((agg["wifi_weak"], agg["wifi_rate_min"]), (75, 11))

    def test_real_minutes_without_wifi_fields_still_get_a_verdict(self):
        nt = self.nt
        with open(FIELD_FIXTURE, encoding="utf-8") as fh:
            case = json.load(fh)["rows"][0]
        v = nt.rxh_verdict(nt.rxh_sum([case["row"]]), {"ok": True, "why": ""}, {"ok": None, "why": "absent"})
        self.assertEqual(v["state"], "network")


class InstmonTermonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp0 = tempfile.mkdtemp()
        cls.m = load_instmon({"INSTMON_LIBRARY_DIR": os.path.join(cls.tmp0, "lib"),
                              "INSTMON_CONFIG_DIR": os.path.join(cls.tmp0, "cfg")})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp0, True)

    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.path = os.path.join(d, "stopped.json")
        for target, value in (("_USER_STOPPED_PATH", self.path),):
            p = mock.patch.object(self.m, target, value)
            p.start()
            self.addCleanup(p.stop)
        q = mock.patch.object(self.m, "log_event")
        q.start()
        self.addCleanup(q.stop)

    def termon(self):
        return next(c for c in self.m.COMPONENTS if c["category"] == "termon")

    def termon_file(self):
        import glob
        return sorted(glob.glob(os.path.join(HERE, "..", "termon_v*.py")))[-1]

    def test_registry_entry_is_complete(self):
        m, c = self.m, self.termon()
        self.assertEqual((c["name"], c["service"], c["port"], c["scheme"]), ("Terminal Monitor", "termon", 7878, "https"))
        self.assertEqual(c["install_link"], "/usr/local/bin/termon.py")
        for table in (m.LIB_SUBDIRS, m.ALLOWED_EXT, m._FU_DEFAULT_STEM):
            self.assertIn("termon", table)
        self.assertIn("termon", m.FU_ORDER)
        self.assertIn("termon", m.INSTALLABLE_CATEGORIES)
        self.assertIn("termon", m.GH_CATEGORIES)
        self.assertIn("termon", [g[1] for g in m._LIBRARY_GROUPS])
        self.assertLess(m.FU_ORDER.index("termon"), m.FU_ORDER.index("instmon"))
        self.assertEqual(m.ALLOWED_EXT["termon"], (".py",))
        for other in m.COMPONENTS:
            if other is not c:
                self.assertEqual(other.get("scheme", "http"), "http", other["name"])

    def test_termon_files_are_recognised_by_name_and_by_content(self):
        m = self.m
        path = self.termon_file()
        name = os.path.basename(path)
        self.assertEqual(m._gh_kind_for_name(name), ("termon", "termon*.py"))
        self.assertEqual(m._fu_stem_of_name(name), "termon")
        with open(path, encoding="utf-8") as fh:
            version, self_install, self_uninstall = m._scan_header_text(fh.read())
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertTrue(self_install)
        self.assertTrue(self_uninstall)

    def test_nothing_else_claims_termon_files(self):
        for name in ("sysmon_v1_0_0_20261101.py", "nodetalker_v0_1_0_20261101.py", "instmon_v2_93_0_20261109.py"):
            self.assertNotEqual(self.m._gh_kind_for_name(name)[0], "termon")

    def test_markers_are_written_read_and_cleared(self):
        m = self.m
        self.assertEqual(m.user_stopped_read(), {})
        m.user_stopped_mark("wifimon")
        m.user_stopped_mark("termon")
        self.assertTrue(m.user_stopped_is("wifimon"))
        self.assertTrue(m.user_stopped_is("termon"))
        self.assertFalse(m.user_stopped_is("sysmon"))
        with open(self.path) as fh:
            self.assertEqual(sorted(json.load(fh)["services"]), ["termon", "wifimon"])
        m.user_stopped_clear("wifimon")
        self.assertEqual(sorted(m.user_stopped_read()), ["termon"])
        before = os.stat(self.path).st_mtime_ns
        m.user_stopped_clear("never-marked")
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)

    def test_a_damaged_marker_file_reads_as_empty(self):
        for text in ("not json", "[1]", '{"services": 5}', '{"services": {"a": "x", "b": 3, "7": 1}}'):
            with open(self.path, "w") as fh:
                fh.write(text)
            got = self.m.user_stopped_read()
            self.assertEqual(got, {"b": 3, "7": 1} if "b" in text else {}, text)

    def run_action(self, service, verb, fail_verb, state):
        m = self.m
        sent = []
        fake = mock.Mock()
        fake._send_json = lambda code, obj: sent.append((code, obj))
        fake._error_json = lambda code, msg: sent.append((code, {"error": msg}))
        with mock.patch.object(m.subprocess, "run", return_value=mock.Mock(returncode=0)), \
                mock.patch.object(m, "systemctl_is_active", return_value=state), \
                mock.patch.object(m.time, "sleep", lambda s: None):
            m.InstmonHandler._service_action(fake, {"service": service}, verb, "refuse", fail_verb, "done", ("info", "warn"))
        return sent

    def test_stop_marks_and_start_clears(self):
        m = self.m
        self.run_action("wifimon", "stop", "stop", "inactive")
        self.assertTrue(m.user_stopped_is("wifimon"))
        self.run_action("wifimon", "restart", "start", "active")
        self.assertFalse(m.user_stopped_is("wifimon"))

    def test_a_stop_that_did_not_stop_is_not_recorded_and_a_failed_start_keeps_the_mark(self):
        m = self.m
        self.run_action("wifimon", "stop", "stop", "active")
        self.assertFalse(m.user_stopped_is("wifimon"))
        m.user_stopped_mark("wifimon")
        self.run_action("wifimon", "restart", "start", "failed")
        self.assertTrue(m.user_stopped_is("wifimon"))

    def test_instmon_cannot_be_marked(self):
        sent = self.run_action("instmon", "stop", "stop", "inactive")
        self.assertEqual(sent[0][0], 400)
        self.assertFalse(self.m.user_stopped_is("instmon"))

    def test_termon_can_be_stopped_and_started_from_instmon(self):
        self.run_action("termon", "stop", "stop", "inactive")
        self.assertTrue(self.m.user_stopped_is("termon"))

    def test_quiet_system_stops_are_not_user_stops(self):
        with mock.patch.object(self.m.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")), \
                mock.patch.object(self.m, "systemctl_is_active", return_value="inactive"):
            ok, _msg = self.m._quiesce_stop_one("wifimon.service")
        self.assertTrue(ok)
        self.assertEqual(self.m.user_stopped_read(), {})

    def card(self, **kw):
        c = {"name": "Terminal Monitor", "service": "termon", "port": 7878, "scheme": "https", "category": "termon",
             "state": "inactive", "listening": False, "version": "0.2.2", "installed": True, "user_stopped": True}
        c.update(kw)
        with mock.patch.object(self.m, "render_app_card_html", return_value=""), \
                mock.patch.object(self.m, "render_confgetter_card_html", return_value=""):
            return self.m.render_components_html([c])

    def test_card_says_stopped_by_you_and_opens_https(self):
        html = self.card(listening=True, state="active", user_stopped=False)
        self.assertIn('data-scheme="https"', html)
        self.assertNotIn("stopped by you", html)
        html = self.card()
        self.assertIn("stopped by you", html)
        html = self.card(state="active", user_stopped=True)
        self.assertNotIn("stopped by you", html)

    def test_go_button_picks_the_scheme_from_the_card(self):
        with open(os.path.join(HERE, "..", os.path.basename(self.m.__file__)), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("btn.dataset.scheme === 'https' ? 'https' : 'http'", src)

    def test_install_and_uninstall_success_clear_the_mark(self):
        m = self.m
        comp = self.termon()
        m.user_stopped_mark("termon")

        class Proc:
            returncode = 0
            stdout = iter(["ok\n"])

            def wait(self, timeout=None):
                return 0

        with mock.patch.object(m.subprocess, "Popen", lambda *a, **k: Proc()), \
                mock.patch.object(m, "installed_link", lambda c: "/usr/local/bin/termon.py"), \
                mock.patch.object(m, "quiet_forget", lambda s: None), \
                mock.patch.object(m, "prepare_install", lambda c, p: None), \
                mock.patch.object(m, "FU_STABLE_SEC", 0):
            m.run_self_install_bg("/usr/local/bin/termon.py", "termon.py", comp)
        self.assertFalse(m.user_stopped_is("termon"))
        m.user_stopped_mark("termon")
        Proc.stdout = iter(["ok\n"])
        with mock.patch.object(m.subprocess, "Popen", lambda *a, **k: Proc()), \
                mock.patch.object(m, "installed_link", lambda c: "/usr/local/bin/termon.py"), \
                mock.patch.object(m, "quiet_forget", lambda s: None):
            m.run_self_uninstall_bg(comp)
        self.assertFalse(m.user_stopped_is("termon"))


class InstmonFetchMissingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp0 = tempfile.mkdtemp()
        cls.m = load_instmon({"INSTMON_LIBRARY_DIR": os.path.join(cls.tmp0, "lib"),
                              "INSTMON_CONFIG_DIR": os.path.join(cls.tmp0, "cfg")})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp0, True)

    def setUp(self):
        m = self.m
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.d = d
        self.lib = {}
        for cat in ("termon", "pibrary", "wifimon", "sysmon"):
            self.lib[cat] = os.path.join(d, "lib", cat)
            os.makedirs(self.lib[cat])
        self.installed = {}
        self.net = {}
        self.events = []
        patches = [
            mock.patch.dict(m.LIB_SUBDIRS, self.lib),
            mock.patch.object(m, "_FETCHED_PATH", os.path.join(d, "fetched.json")),
            mock.patch.object(m, "_gh_fetch_impl", lambda url, limit, head=None: self.net[url]),
            mock.patch.object(m, "resolve_installed_target", lambda comp: self.installed.get(comp["category"], "/nonexistent/x")),
            mock.patch.object(m, "recorder_busy", lambda: None),
            mock.patch.object(m, "channel_get", lambda: self.channel),
            mock.patch.object(m, "_build_wanted_variant", lambda: self.variant),
            mock.patch.object(m, "log_event", lambda msg, level="info": self.events.append((level, msg))),
            mock.patch.object(m, "_gh_event", lambda msg, level: self.events.append((level, msg))),
            mock.patch.object(m, "FETCH_MISSING_MAX", 8),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.channel = "testing"
        self.variant = None
        with m._gh_lock:
            m._gh_state["busy"].clear()
            m._gh_state["entries"] = []

    def file(self, name, ver):
        return (f'#!/usr/bin/env python3\nimport argparse\nVERSION = "{ver}"\n\n'
                'def install_service():\n    pass\n\n\ndef uninstall_service():\n    pass\n\n\n'
                'ap = argparse.ArgumentParser()\nap.add_argument("--install", action="store_true")\n'
                'ap.add_argument("--uninstall", action="store_true")\n').encode()

    def entry(self, name, category, ver, glob=None, status="missing"):
        data = self.file(name, ver)
        self.net[name] = data
        return {"name": name, "category": category, "glob": glob or f"{category}*.py", "blob": self.m._git_blob_id(data),
                "version": ver, "status": status, "url": name}

    def listed(self, entry):
        return os.listdir(self.lib[entry["category"]])

    def test_a_missing_tool_is_downloaded_and_nothing_is_installed(self):
        m = self.m
        e = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2")
        with mock.patch.object(m.subprocess, "run", side_effect=AssertionError("nothing may be run")), \
                mock.patch.object(m.subprocess, "Popen", side_effect=AssertionError("nothing may be run")):
            got = m._gh_fetch_missing([e])
        self.assertEqual(got, [e["name"]])
        self.assertEqual(self.listed(e), [e["name"]])
        rec = m._fetched_read()[e["name"]]
        self.assertEqual((rec["category"], rec["version"], rec["channel"], rec["build"]), ("termon", "0.2.2", "testing", "full"))
        self.assertTrue(any("Download only" in msg for _l, msg in self.events))

    def test_an_installed_tool_is_left_to_the_normal_update_path(self):
        e = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2")
        real = os.path.join(self.d, "termon.py")
        __import__("pathlib").Path(real).write_bytes(b"x")
        self.installed["termon"] = real
        self.assertEqual(self.m._gh_fetch_missing([e]), [])
        self.assertEqual(self.listed(e), [])

    def test_other_status_values_and_instmon_itself_are_not_fetched(self):
        e1 = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2", status="up_to_date")
        e2 = self.entry("termon_v0_2_1_20261109.py", "termon", "0.2.1", status="conflict")
        self.assertEqual(self.m._gh_fetch_missing([e1, e2]), [])
        self.assertEqual(self.listed(e1), [])

    def test_the_other_build_is_skipped(self):
        self.variant = ""
        e = self.entry("sysmon_pi02w_v6_13_83_20261028.py", "sysmon", "6.13.83-pi02w")
        self.assertEqual(self.m._gh_fetch_missing([e]), [])
        self.variant = "pi02w"
        self.assertEqual(self.m._gh_fetch_missing([e]), [e["name"]])
        self.assertEqual(self.m._fetched_read()[e["name"]]["build"], "pi02w")

    def test_nothing_is_downloaded_while_a_recording_runs(self):
        e = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2")
        with mock.patch.object(self.m, "recorder_busy", lambda: {"entry": "x"}):
            self.assertEqual(self.m._gh_fetch_missing([e]), [])
        self.assertEqual(self.listed(e), [])

    def test_the_number_of_downloads_per_check_is_capped(self):
        e1 = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2")
        e2 = self.entry("pibrary_v0_16_1_20261104.py", "pibrary", "0.16.1")
        with mock.patch.object(self.m, "FETCH_MISSING_MAX", 1):
            self.assertEqual(len(self.m._gh_fetch_missing([e1, e2])), 1)
        with mock.patch.object(self.m, "FETCH_MISSING_MAX", 0):
            self.assertEqual(self.m._gh_fetch_missing([e1, e2]), [])

    def test_a_bad_download_is_refused_and_the_next_one_still_goes(self):
        m = self.m
        bad = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2")
        self.net[bad["name"]] = self.net[bad["name"]] + b"# changed on the way\n"
        good = self.entry("pibrary_v0_16_1_20261104.py", "pibrary", "0.16.1")
        got = m._gh_fetch_missing([bad, good])
        self.assertEqual(got, [good["name"]])
        self.assertEqual(self.listed(bad), [])
        self.assertTrue(any(lvl == "warn" and "termon_v0_2_2" in msg for lvl, msg in self.events))

    def test_a_newer_download_replaces_only_the_copy_it_fetched_before(self):
        m = self.m
        old = self.entry("termon_v0_2_1_20261109.py", "termon", "0.2.1")
        m._gh_fetch_missing([old])
        mine = os.path.join(self.lib["termon"], "termon_v0_1_0_20261101.py")
        __import__("pathlib").Path(mine).write_bytes(self.file("x", "0.1.0"))
        new = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2", status="update")
        m._gh_fetch_missing([new])
        self.assertEqual(sorted(self.listed(new)), ["termon_v0_1_0_20261101.py", "termon_v0_2_2_20261109.py"])
        self.assertEqual(sorted(m._fetched_read()), ["termon_v0_2_2_20261109.py"])

    def test_a_copy_that_matches_the_installed_file_is_kept(self):
        m = self.m
        old = self.entry("termon_v0_2_1_20261109.py", "termon", "0.2.1")
        m._gh_fetch_missing([old])
        real = os.path.join(self.d, "termon.py")
        shutil.copyfile(os.path.join(self.lib["termon"], old["name"]), real)
        self.installed["termon"] = real
        os.unlink(real)
        shutil.copyfile(os.path.join(self.lib["termon"], old["name"]), real)
        new = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2", status="update")
        m._fetched_record(new)
        with open(os.path.join(self.lib["termon"], new["name"]), "wb") as fh:
            fh.write(self.net[new["name"]])
        m._fetched_prune(new)
        self.assertIn(old["name"], self.listed(new))

    def test_a_locked_copy_is_kept(self):
        m = self.m
        old = self.entry("termon_v0_2_1_20261109.py", "termon", "0.2.1")
        m._gh_fetch_missing([old])
        new = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2", status="update")
        with mock.patch.object(m, "lib_locked", lambda cat, name: name == old["name"]):
            m._gh_fetch_missing([new])
        self.assertIn(old["name"], self.listed(new))

    def test_switching_to_stable_fetches_the_stable_build_and_drops_the_testing_copy(self):
        m = self.m
        testing = self.entry("termon_v0_2_3_20261110.py", "termon", "0.2.3")
        m._gh_fetch_missing([testing])
        self.channel = "stable"
        stable = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2", status="newer_local")
        got = m._gh_fetch_missing([stable])
        self.assertEqual(got, [stable["name"]])
        self.assertEqual(self.listed(stable), [stable["name"]])
        self.assertEqual(m._fetched_read()[stable["name"]]["channel"], "stable")

    def test_a_newer_library_file_you_added_yourself_is_not_replaced_by_an_older_stable_one(self):
        m = self.m
        mine = os.path.join(self.lib["termon"], "termon_v0_2_3_20261110.py")
        __import__("pathlib").Path(mine).write_bytes(self.file("x", "0.2.3"))
        self.channel = "stable"
        stable = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2", status="newer_local")
        self.assertEqual(m._gh_fetch_missing([stable]), [])
        self.assertEqual(self.listed(stable), ["termon_v0_2_3_20261110.py"])

    def test_a_damaged_record_file_reads_as_empty(self):
        for text in ("nope", "[]", '{"files": 3}', '{"files": {"a": 1, "b": {"x": 1}}}'):
            with open(self.m._FETCHED_PATH, "w") as fh:
                fh.write(text)
            self.assertEqual(self.m._fetched_read(), {"b": {"x": 1}} if "b" in text else {}, text)

    def test_the_check_downloads_after_it_finishes_and_a_failure_does_not_break_it(self):
        m = self.m
        e = self.entry("termon_v0_2_2_20261109.py", "termon", "0.2.2")
        with mock.patch.object(m, "_gh_collect_full", lambda gen=None: ([e], 0, [e])), \
                mock.patch.object(m, "_docs_refresh_remote", lambda: None), \
                mock.patch.object(m, "full_update_preview", lambda: None):
            with m._gh_lock:
                m._gh_state["phase"] = "checking"
                gen = m._gh_state["gen"]
            m._gh_check_bg(gen)
            self.assertEqual(self.listed(e), [e["name"]])
            with mock.patch.object(m, "_gh_fetch_missing", side_effect=RuntimeError("boom")):
                with m._gh_lock:
                    m._gh_state["phase"] = "checking"
                m._gh_check_bg(gen)
            self.assertEqual(m._gh_state["phase"], "done")
            self.assertTrue(any("failed: boom" in msg for _l, msg in self.events))

    def comp_row(self, category, installed, name="Tool"):
        return {"name": name, "service": category, "port": 7878, "category": category, "installed": installed,
                "state": "inactive", "listening": False, "version": "?"}

    def test_the_available_card_lists_only_tools_that_are_not_installed(self):
        m = self.m
        rows = [self.comp_row("termon", False, "Terminal Monitor"), self.comp_row("pibrary", True, "Pibrary"),
                self.comp_row("instmon", False, "instmon")]
        html = m.render_available_card_html(rows, {"termon": []})
        self.assertIn("Available, not installed", html)
        self.assertIn("Terminal Monitor", html)
        self.assertNotIn("Pibrary", html)
        self.assertNotIn(">instmon<", html)
        self.assertEqual(m.render_available_card_html([self.comp_row("pibrary", True)], {}), "")

    def test_a_downloaded_tool_gets_an_install_button_and_others_say_why_not(self):
        m = self.m
        lib = {"termon": [{"name": "termon_v0_2_2_20261109.py", "version": "0.2.2", "installed": False}], "pibrary": []}
        rows = [self.comp_row("termon", False, "Terminal Monitor"), self.comp_row("pibrary", False, "Pibrary")]
        html = m.render_available_card_html(rows, lib)
        self.assertIn('data-action="install" data-category="termon" data-name="termon_v0_2_2_20261109.py"', html)
        self.assertEqual(html.count('data-action="install"'), 1)
        self.assertIn("Downloaded v0.2.2", html)
        self.assertIn("Press Check GitHub", html)
        with m._gh_lock:
            m._gh_state["checked_at"] = "2026-11-09 08:00"
        self.channel = "stable"
        self.assertIn("No stable build on GitHub yet", m.render_available_card_html(rows, lib))
        self.channel = "testing"
        self.assertIn("No build on GitHub", m.render_available_card_html(rows, lib))
        with m._gh_lock:
            m._gh_state["checked_at"] = None

    def test_the_card_names_the_channel_and_build(self):
        rows = [self.comp_row("termon", False, "Terminal Monitor")]
        self.assertIn("Testing channel", self.m.render_available_card_html(rows, {}))
        self.channel = "stable"
        self.variant = "pi02w"
        html = self.m.render_available_card_html(rows, {})
        self.assertIn("Stable channel", html)
        self.assertIn("Pi Zero 2 W fork build", html)

    def test_the_other_builds_files_are_not_offered_as_the_install(self):
        self.variant = ""
        lib = {"sysmon": [{"name": "sysmon_pi02w_v6_13_83_20261028.py", "version": "6.13.83-pi02w", "installed": False}]}
        html = self.m.render_available_card_html([self.comp_row("sysmon", False, "SysMon")], lib)
        self.assertNotIn('data-action="install"', html)

    def test_the_card_is_part_of_the_page_sections(self):
        m = self.m
        status = {"components": [self.comp_row("termon", False, "Terminal Monitor")], "library": {}, "app": None, "confgetter": None}
        with mock.patch.object(m, "render_components_html", return_value="<!--c-->"):
            html = m.render_components_section(status)
        self.assertTrue(html.index("available-card") < html.index("<!--c-->"))


if __name__ == "__main__":
    unittest.main()
