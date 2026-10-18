#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
