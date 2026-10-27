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
        fill = self.h._fcr_fill_secrets
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


if __name__ == "__main__":
    unittest.main()
