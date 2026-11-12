#!/usr/bin/env python3
import glob
import json
import fcntl
import os
import pty
import select
import shutil
import subprocess
import tempfile
import termios
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUB_BIN = os.path.join(ROOT, "ci", "fixtures", "servers", "bin")
INSTALLER = sorted(glob.glob(os.path.join(ROOT, "install_all_v*.sh")))[-1]
BOOTSTRAP = os.path.join(ROOT, "bootstrap.sh")
UNINSTALLER = sorted(glob.glob(os.path.join(ROOT, "uninstall_all_v*.sh")))[-1]

NAMES = {"wifimon": "wifimon", "nodetalker": "nodetalker", "noderecorder": "noderecorder",
         "pibrary": "pibrary", "termon": "termon", "44helper": "44helper"}
LIB = {"wifimon": "wifimon", "nodetalker": "nodelisten", "noderecorder": "noderecorder",
       "pibrary": "pibrary", "termon": "termon", "44helper": "44helper"}


def skip_reason():
    if os.environ.get("ASL_TEST_INSTALL") != "1":
        return "set ASL_TEST_INSTALL=1 to run (the installer writes into the system folders)"
    if os.geteuid() != 0:
        return "installer tests run as root"
    return None


def fake_tool(name, version):
    return f'''#!/usr/bin/env python3
import os
import shutil
import sys

VERSION = "{version}"
NAME = "{name}"
STUB = os.environ["STUB_DIR"]


def mark(unit, kind, value):
    folder = os.path.join(STUB, "units")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, unit + "." + kind), "w") as fh:
        fh.write(value)


if "--install" in sys.argv:
    shutil.copyfile(os.path.abspath(__file__), "/usr/local/bin/" + NAME + ".py")
    mark(NAME, "state", "active")
    mark(NAME, "enabled", "enabled")
    print("fake install", NAME, VERSION)
elif "--uninstall" in sys.argv:
    try:
        os.unlink("/usr/local/bin/" + NAME + ".py")
    except FileNotFoundError:
        pass
    mark(NAME, "state", "inactive")
    mark(NAME, "enabled", "disabled")
    print("fake uninstall", NAME)
'''


class InstallerBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = skip_reason()
        if why:
            raise unittest.SkipTest(why)
        for name in NAMES.values():
            if os.path.lexists(f"/usr/local/bin/{name}.py"):
                raise unittest.SkipTest(f"{name} is already installed here; run on a clean machine")

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="asl-inst-")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.work = os.path.join(self.d, "work")
        self.lib = os.path.join(self.d, "lib")
        self.stub = os.path.join(self.d, "stub")
        for p in (self.work, self.lib, self.stub):
            os.makedirs(p)
        self.script = os.path.join(self.work, "install_all.sh")
        shutil.copyfile(INSTALLER, self.script)
        self.stopped = os.path.join(self.d, "stopped.json")
        self.quiet = os.path.join(self.d, "quiet.json")
        self.staged = []
        self.addCleanup(self.cleanup_system)

    def cleanup_system(self):
        for name in NAMES.values():
            path = f"/usr/local/bin/{name}.py"
            if os.path.lexists(path):
                os.unlink(path)
        for path in self.staged:
            if os.path.lexists(path):
                os.unlink(path)

    def put(self, key, version="9.9.9", name=None):
        base = name or f"{NAMES[key]}_v{version.replace('.', '_')}_20990101.py"
        folder = os.path.join(self.lib, LIB[key])
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, base)
        with open(path, "w") as fh:
            fh.write(fake_tool(NAMES[key], version))
        self.staged.append(os.path.join("/tmp", base))
        return path

    def state(self, unit, value=None, enabled=None):
        folder = os.path.join(self.stub, "units")
        os.makedirs(folder, exist_ok=True)
        if value is not None:
            with open(os.path.join(folder, unit + ".state"), "w") as fh:
                fh.write(value)
        if enabled is not None:
            with open(os.path.join(folder, unit + ".enabled"), "w") as fh:
                fh.write(enabled)

    def read_state(self, unit, kind="state"):
        try:
            with open(os.path.join(self.stub, "units", f"{unit}.{kind}")) as fh:
                return fh.read().strip()
        except FileNotFoundError:
            return ""

    def installed(self, key):
        return os.path.exists(f"/usr/local/bin/{NAMES[key]}.py")

    def install_old(self, key, version="9.9.0"):
        path = f"/usr/local/bin/{NAMES[key]}.py"
        with open(path, "w") as fh:
            fh.write(fake_tool(NAMES[key], version))
        os.chmod(path, 0o755)

    def environment(self, env=None):
        full = dict(os.environ, STUB_DIR=self.stub, INSTMON_LIBRARY_DIR=self.lib,
                    PATH=STUB_BIN + os.pathsep + os.environ.get("PATH", ""),
                    ASL_DVS_USER_STOPPED=self.stopped, ASL_DVS_QUIET_STATE=self.quiet)
        for var in ("INSTALL_TERMON", "INSTALL_NODETALKER", "INSTALL_NODELISTEN", "INSTALL_NODERECORDER",
                    "INSTALL_PIBRARY", "ASL_DVS_CHANNEL", "ASL_DVS_GIT_URL", "ASL_DVS_RAW_URL", "ASL_DVS_REPO"):
            full.pop(var, None)
        full.update(env or {})
        return full

    def run_installer(self, *args, env=None, timeout=300):
        r = subprocess.run(["bash", self.script, *args], cwd=self.work, env=self.environment(env),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr

    def sandbox_path(self, *missing):
        box = os.path.join(self.d, "path")
        os.makedirs(box, exist_ok=True)
        for folder in reversed(os.environ.get("PATH", "").split(os.pathsep)):
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                link = os.path.join(box, name)
                if os.path.lexists(link):
                    os.unlink(link)
                if name in missing or name in ("apt-get", "apt"):
                    continue
                os.symlink(os.path.join(folder, name), link)
        for name in ("ss", "openssl"):
            link = os.path.join(box, name)
            if name not in missing and not os.path.lexists(link):
                with open(link, "w") as fh:
                    fh.write("#!/bin/sh\nexit 0\n")
                os.chmod(link, 0o755)
        real = {name: shutil.which(name) or "/bin/true" for name in missing}
        lines = ["#!/bin/sh", 'echo "$@" >> "$STUB_DIR/apt.log"', 'case " $* " in *" install "*) ;; *) exit 0 ;; esac',
                 'for a in "$@"; do', '  case "$a" in']
        for name, target in real.items():
            pkg = "iproute2" if name == "ss" else name
            lines.append(f'    {pkg}) ln -sf "{target}" "{box}/{name}" ;;')
        lines += ["  esac", "done", "exit 0", ""]
        with open(os.path.join(box, "apt-get"), "w") as fh:
            fh.write("\n".join(lines))
        os.chmod(os.path.join(box, "apt-get"), 0o755)
        return STUB_BIN + os.pathsep + box

    def apt_log(self):
        try:
            with open(os.path.join(self.stub, "apt.log")) as fh:
                return fh.read()
        except FileNotFoundError:
            return ""

    def run_tty(self, *args, answers=(), env=None, missing=(), timeout=120, command=None):
        full = self.environment(env)
        full["PATH"] = self.sandbox_path(*missing)
        master, slave = pty.openpty()

        def attach():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        proc = subprocess.Popen(command or ["bash", self.script, *args], cwd=self.work, env=full, stdin=slave,
                                stdout=slave, stderr=slave, preexec_fn=attach, close_fds=True)
        os.close(slave)
        out = ""
        seen = 0
        todo = list(answers)
        end = time.time() + timeout
        try:
            while True:
                if time.time() > end:
                    proc.kill()
                    self.fail("the installer waited too long; output so far:\n" + out[-3000:])
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break
                    out += chunk.decode("utf-8", "replace")
                elif proc.poll() is not None:
                    break
                while todo and todo[0][0] in out[seen:]:
                    seen = out.index(todo[0][0], seen) + len(todo[0][0])
                    os.write(master, (todo[0][1] + "\n").encode())
                    todo.pop(0)
        finally:
            os.close(master)
        proc.wait(timeout=30)
        self.unanswered = [q for q, _ in todo]
        return proc.returncode, out.replace("\r\n", "\n")

    def git(self, repo, *args):
        subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.x",
                                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e.x"))

    def make_repo(self, files, stable):
        repo = os.path.join(self.d, "remote")
        os.makedirs(repo)
        self.git(repo, "init", "-q", "-b", "main")
        self.git(repo, "config", "uploadpack.allowFilter", "true")
        self.git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
        for name, body in files.items():
            with open(os.path.join(repo, name), "w") as fh:
                fh.write(body)
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "files")
        commit = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        tools = {}
        for key, name in stable.items():
            blob = subprocess.run(["git", "-C", repo, "rev-parse", f"HEAD:{name}"], capture_output=True, text=True).stdout.strip()
            tools[key] = {"file": name, "commit": commit, "blob": blob}
        os.makedirs(os.path.join(repo, "channels"))
        with open(os.path.join(repo, "channels", "stable.json"), "w") as fh:
            json.dump({"tools": tools}, fh)
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "stable list")
        return "file://" + repo

    def files(self):
        return {
            "wifimon_v9_9_9_20990101.py": fake_tool("wifimon", "9.9.9"),
            "nodetalker_v9_9_9_20990101.py": fake_tool("nodetalker", "9.9.9"),
            "pibrary_v9_9_9_20990101.py": fake_tool("pibrary", "9.9.9"),
            "termon_v9_9_9_20990101.py": fake_tool("termon", "9.9.9"),
        }

    def library(self, key):
        folder = os.path.join(self.lib, LIB[key])
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


class OptionalToolTests(InstallerBase):
    def test_terminal_monitor_is_skipped_unless_asked_for(self):
        self.put("wifimon")
        self.put("termon")
        rc, out = self.run_installer("--non-interactive", "--offline")
        self.assertEqual(rc, 0, out[-1500:])
        self.assertTrue(self.installed("wifimon"))
        self.assertFalse(self.installed("termon"))
        self.assertIn("Terminal Monitor is optional and not installed", out)

    def test_the_environment_variable_asks_for_it(self):
        self.put("wifimon")
        self.put("termon")
        rc, out = self.run_installer("--non-interactive", "--offline", env={"INSTALL_TERMON": "1"})
        self.assertEqual(rc, 0, out[-1500:])
        self.assertTrue(self.installed("termon"))
        self.assertEqual(self.read_state("termon"), "active")
        self.assertIn("Terminal Monitor installed, enabled, and restarted", out)

    def test_the_flag_asks_for_it_and_the_address_is_https(self):
        self.put("wifimon")
        self.put("termon")
        rc, out = self.run_installer("--non-interactive", "--offline", "--with-termon")
        self.assertEqual(rc, 0, out[-1500:])
        self.assertTrue(self.installed("termon"))
        self.assertIn("https://localhost:7878", out)

    def test_node_recorder_and_pibrary_are_optional_too(self):
        self.put("wifimon")
        self.put("noderecorder")
        self.put("pibrary")
        rc, out = self.run_installer("--non-interactive", "--offline", "--core")
        self.assertEqual(rc, 0, out[-1500:])
        self.assertFalse(self.installed("noderecorder"))
        self.assertFalse(self.installed("pibrary"))
        rc, out = self.run_installer("--non-interactive", "--offline", env={"INSTALL_PIBRARY": "yes"})
        self.assertEqual(rc, 0, out[-1500:])
        self.assertTrue(self.installed("pibrary"))
        self.assertFalse(self.installed("noderecorder"))

    def test_the_suite_installs_everything_except_terminal_monitor(self):
        for key in ("wifimon", "nodetalker", "noderecorder", "pibrary", "termon"):
            self.put(key)
        rc, out = self.run_installer("--non-interactive", "--offline", "--suite")
        self.assertEqual(rc, 0, out[-1500:])
        for key in ("wifimon", "nodetalker", "noderecorder", "pibrary"):
            self.assertTrue(self.installed(key), key)
        self.assertFalse(self.installed("termon"))

    def test_the_suite_with_the_flag_includes_terminal_monitor(self):
        for key in ("wifimon", "nodetalker", "noderecorder", "pibrary", "termon"):
            self.put(key)
        rc, out = self.run_installer("--non-interactive", "--offline", "--suite", "--with-termon")
        self.assertEqual(rc, 0, out[-1500:])
        for key in ("wifimon", "nodetalker", "noderecorder", "pibrary", "termon"):
            self.assertTrue(self.installed(key), key)

    def test_a_tool_that_is_already_installed_is_updated_without_asking(self):
        self.install_old("termon", "9.9.0")
        self.state("termon", "active", "enabled")
        self.put("termon", "9.9.9")
        rc, out = self.run_installer("--non-interactive", "--offline")
        self.assertEqual(rc, 0, out[-1500:])
        with open("/usr/local/bin/termon.py") as fh:
            self.assertIn('VERSION = "9.9.9"', fh.read())

    def test_nothing_found_still_fails_clearly(self):
        rc, out = self.run_installer("--non-interactive", "--offline", "--with-termon")
        self.assertNotEqual(rc, 0)
        self.assertIn("Nothing to install", out)


class StoppedByYouTests(InstallerBase):
    def setUp(self):
        super().setUp()
        self.install_old("wifimon", "9.9.0")
        self.put("wifimon", "9.9.9")

    def update(self):
        rc, out = self.run_installer("--non-interactive", "--offline")
        self.assertEqual(rc, 0, out[-1500:])
        with open("/usr/local/bin/wifimon.py") as fh:
            self.assertIn('VERSION = "9.9.9"', fh.read())
        return out

    def test_a_running_service_is_updated_and_stays_running(self):
        self.state("wifimon", "active", "enabled")
        out = self.update()
        self.assertEqual(self.read_state("wifimon"), "active")
        self.assertNotIn("left stopped", out)

    def test_a_service_you_stopped_with_instmon_stays_stopped(self):
        self.state("wifimon", "inactive", "enabled")
        with open(self.stopped, "w") as fh:
            json.dump({"services": {"wifimon": 1790000000}}, fh)
        out = self.update()
        self.assertEqual(self.read_state("wifimon"), "inactive")
        self.assertEqual(self.read_state("wifimon", "enabled"), "enabled")
        self.assertIn("installed and left stopped, as you had it", out)
        self.assertIn("wifimon is stopped, as you had it", out)
        self.assertNotIn("did not start cleanly", out)

    def test_a_disabled_service_stays_stopped_and_disabled(self):
        self.state("wifimon", "inactive", "disabled")
        out = self.update()
        self.assertEqual(self.read_state("wifimon"), "inactive")
        self.assertEqual(self.read_state("wifimon", "enabled"), "disabled")
        self.assertIn("left stopped", out)

    def test_a_crashed_service_counts_as_running(self):
        self.state("wifimon", "inactive", "enabled")
        out = self.update()
        self.assertEqual(self.read_state("wifimon"), "active")
        self.assertNotIn("left stopped", out)

    def test_a_service_that_quiet_system_paused_is_started(self):
        self.state("wifimon", "inactive", "disabled")
        with open(self.quiet, "w") as fh:
            json.dump({"job_id": "quiet", "stopped": [["service", "wifimon", "wifimon.service"]]}, fh)
        out = self.update()
        self.assertEqual(self.read_state("wifimon"), "active")
        self.assertNotIn("left stopped", out)

    def test_an_old_mark_on_a_running_service_is_ignored(self):
        self.state("wifimon", "active", "enabled")
        with open(self.stopped, "w") as fh:
            json.dump({"services": {"wifimon": 1790000000}}, fh)
        out = self.update()
        self.assertEqual(self.read_state("wifimon"), "active")
        self.assertNotIn("left stopped", out)

    def test_a_damaged_mark_file_is_ignored(self):
        self.state("wifimon", "active", "enabled")
        with open(self.stopped, "w") as fh:
            fh.write("not json")
        self.update()
        self.assertEqual(self.read_state("wifimon"), "active")

    def test_a_service_you_stopped_stays_stopped_for_optional_tools_too(self):
        self.install_old("termon", "9.9.0")
        self.state("termon", "inactive", "disabled")
        self.put("termon", "9.9.9")
        rc, out = self.run_installer("--non-interactive", "--offline")
        self.assertEqual(rc, 0, out[-1500:])
        self.assertEqual(self.read_state("termon"), "inactive")
        self.assertEqual(self.read_state("termon", "enabled"), "disabled")
        self.assertIn("Terminal Monitor installed and left stopped", out)


class DownloadOnlyTests(InstallerBase):
    def test_stable_downloads_what_is_listed_and_installs_nothing(self):
        url = self.make_repo(self.files(), {"wifimon": "wifimon_v9_9_9_20990101.py",
                                           "nodetalker": "nodetalker_v9_9_9_20990101.py"})
        rc, out = self.run_installer("--download-only", "--non-interactive", env={"ASL_DVS_GIT_URL": url})
        self.assertEqual(rc, 0, out[-2000:])
        self.assertEqual(self.library("wifimon"), ["wifimon_v9_9_9_20990101.py"])
        self.assertEqual(self.library("nodetalker"), ["nodetalker_v9_9_9_20990101.py"])
        self.assertEqual(self.library("termon"), [])
        self.assertEqual(self.library("pibrary"), [])
        self.assertIn("Terminal Monitor has no stable build yet — not downloaded", out)
        self.assertIn("nothing was installed or started", out)
        for key in NAMES:
            self.assertFalse(self.installed(key), key)
        self.assertEqual(self.read_state("wifimon"), "")

    def test_testing_downloads_the_newest_from_main(self):
        url = self.make_repo(self.files(), {"wifimon": "wifimon_v9_9_9_20990101.py"})
        rc, out = self.run_installer("--download-only", "--non-interactive",
                                     env={"ASL_DVS_GIT_URL": url, "ASL_DVS_CHANNEL": "testing"})
        self.assertEqual(rc, 0, out[-2000:])
        self.assertEqual(self.library("termon"), ["termon_v9_9_9_20990101.py"])
        self.assertEqual(self.library("pibrary"), ["pibrary_v9_9_9_20990101.py"])
        for key in NAMES:
            self.assertFalse(self.installed(key), key)

    def test_an_installed_tool_is_left_alone(self):
        url = self.make_repo(self.files(), {"wifimon": "wifimon_v9_9_9_20990101.py"})
        self.install_old("wifimon", "9.9.0")
        rc, out = self.run_installer("--download-only", "--non-interactive", env={"ASL_DVS_GIT_URL": url})
        self.assertEqual(rc, 0, out[-2000:])
        self.assertEqual(self.library("wifimon"), [])
        self.assertIn("wifimon is installed — not downloaded", out)
        with open("/usr/local/bin/wifimon.py") as fh:
            self.assertIn('VERSION = "9.9.0"', fh.read())

    def test_a_file_already_in_the_library_is_not_downloaded_again(self):
        url = self.make_repo(self.files(), {"wifimon": "wifimon_v9_9_9_20990101.py"})
        mine = self.put("wifimon", "9.9.1")
        rc, out = self.run_installer("--download-only", "--non-interactive", env={"ASL_DVS_GIT_URL": url})
        self.assertEqual(rc, 0, out[-2000:])
        self.assertEqual(self.library("wifimon"), [os.path.basename(mine)])
        self.assertIn("a file is already in the library", out)

    def test_a_listed_file_that_does_not_match_the_list_is_refused(self):
        url = self.make_repo(self.files(), {"wifimon": "wifimon_v9_9_9_20990101.py"})
        repo = url[len("file://"):]
        with open(os.path.join(repo, "channels", "stable.json")) as fh:
            data = json.load(fh)
        data["tools"]["wifimon"]["blob"] = "0" * 40
        with open(os.path.join(repo, "channels", "stable.json"), "w") as fh:
            json.dump(data, fh)
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "wrong blob")
        rc, out = self.run_installer("--download-only", "--non-interactive", env={"ASL_DVS_GIT_URL": url})
        self.assertEqual(self.library("wifimon"), [])
        self.assertIn("does not match the stable list", out)

    def test_it_fails_when_github_cannot_be_reached(self):
        rc, out = self.run_installer("--download-only", "--non-interactive",
                                     env={"ASL_DVS_GIT_URL": "file:///nonexistent/repo.git"})
        self.assertNotEqual(rc, 0)
        self.assertIn("Could not reach", out)
        self.assertEqual(self.library("wifimon"), [])

    def test_it_will_not_run_offline(self):
        rc, out = self.run_installer("--download-only", "--offline", "--non-interactive")
        self.assertNotEqual(rc, 0)
        self.assertIn("needs the network", out)


class FreshInstallTests(InstallerBase):
    SUITE = ("wifimon", "44helper", "nodetalker", "noderecorder", "pibrary")

    def stage_all(self):
        for key in self.SUITE + ("termon",):
            self.put(key)

    def test_a_fresh_node_gets_the_whole_suite_without_asking(self):
        self.stage_all()
        rc, out = self.run_installer("--non-interactive", "--offline")
        self.assertEqual(rc, 0, out[-1500:])
        self.assertIn("Fresh node: installing the whole suite", out)
        for key in self.SUITE:
            self.assertTrue(self.installed(key), key)
        self.assertFalse(self.installed("termon"))
        self.assertIn("Terminal Monitor is optional and not installed", out)

    def test_core_keeps_the_optional_tools_out(self):
        self.stage_all()
        rc, out = self.run_installer("--non-interactive", "--offline", "--core")
        self.assertEqual(rc, 0, out[-1500:])
        self.assertTrue(self.installed("wifimon"))
        self.assertTrue(self.installed("44helper"))
        for key in ("nodetalker", "noderecorder", "pibrary", "termon"):
            self.assertFalse(self.installed(key), key)

    def test_a_node_with_only_an_optional_tool_is_not_fresh(self):
        self.install_old("pibrary", "9.9.9")
        self.state("pibrary", "active", "enabled")
        self.put("wifimon")
        self.put("noderecorder")
        rc, out = self.run_installer("--non-interactive", "--offline")
        self.assertEqual(rc, 0, out[-1500:])
        self.assertIn("Existing installation detected", out)
        self.assertIn("Pibrary  (/usr/local/bin/pibrary.py)", out)
        self.assertNotIn("whole suite", out)
        self.assertTrue(self.installed("wifimon"))
        self.assertFalse(self.installed("noderecorder"))

    def test_a_fresh_node_downloads_the_suite_from_the_stable_list(self):
        url = self.make_repo(self.files(), {"wifimon": "wifimon_v9_9_9_20990101.py",
                                           "nodetalker": "nodetalker_v9_9_9_20990101.py",
                                           "pibrary": "pibrary_v9_9_9_20990101.py"})
        for key in ("wifimon", "nodetalker", "pibrary", "termon"):
            self.staged.append(f"/tmp/{key}_v9_9_9_20990101.py")
        rc, out = self.run_installer("--non-interactive", env={"ASL_DVS_GIT_URL": url})
        self.assertEqual(rc, 0, out[-2500:])
        for key in ("wifimon", "nodetalker", "pibrary"):
            self.assertTrue(self.installed(key), key)
        self.assertFalse(self.installed("termon"))
        self.assertIn("Node Recorder has no stable build yet", out)

    def test_enter_at_the_question_installs_the_suite_and_asks_about_terminal_monitor(self):
        self.stage_all()
        rc, out = self.run_tty("--offline", answers=[("Install the whole suite? [Y/n/c]: ", ""),
                                                    ("Install Terminal Monitor? [y/N]: ", "")])
        self.assertEqual(rc, 0, out[-2500:])
        self.assertEqual(self.unanswered, [])
        for key in self.SUITE:
            self.assertTrue(self.installed(key), key)
        self.assertFalse(self.installed("termon"))
        self.assertNotIn("Select wifimon version", out)
        self.assertIn("Offline: only the files on this Pi are used.", out)

    def test_yes_to_terminal_monitor_adds_it(self):
        self.stage_all()
        rc, out = self.run_tty("--offline", answers=[("Install the whole suite? [Y/n/c]: ", "y"),
                                                    ("Install Terminal Monitor? [y/N]: ", "y")])
        self.assertEqual(rc, 0, out[-2500:])
        self.assertTrue(self.installed("termon"))

    def test_c_asks_tool_by_tool(self):
        self.put("wifimon")
        self.put("pibrary")
        self.put("noderecorder")
        rc, out = self.run_tty("--offline", answers=[("Install the whole suite? [Y/n/c]: ", "c"),
                                                    ("Select wifimon version [a]: ", ""),
                                                    ("Install Node Recorder? [y/N]: ", "n"),
                                                    ("Install Pibrary? [y/N]: ", "y"),
                                                    ("Select Pibrary version [a]: ", "")])
        self.assertEqual(rc, 0, out[-2500:])
        self.assertEqual(self.unanswered, [])
        self.assertTrue(self.installed("wifimon"))
        self.assertTrue(self.installed("pibrary"))
        self.assertFalse(self.installed("noderecorder"))

    def test_n_quits_and_installs_nothing(self):
        self.stage_all()
        rc, out = self.run_tty("--offline", answers=[("Install the whole suite? [Y/n/c]: ", "n")])
        self.assertEqual(rc, 0, out[-1500:])
        self.assertIn("Aborted by user", out)
        for key in NAMES:
            self.assertFalse(self.installed(key), key)


class PrerequisiteTests(InstallerBase):
    def repo(self):
        for key in ("wifimon", "nodetalker", "pibrary", "termon"):
            self.staged.append(f"/tmp/{key}_v9_9_9_20990101.py")
        return self.make_repo(self.files(), {"wifimon": "wifimon_v9_9_9_20990101.py"})

    def test_missing_git_is_offered_and_installed_on_yes(self):
        url = self.repo()
        rc, out = self.run_tty("--core", env={"ASL_DVS_GIT_URL": url}, missing=("git",),
                               answers=[("Install git with apt? [Y/n]: ", ""),
                                        ("Select wifimon version [a]: ", ""),
                                        ("Install Node Talker? [y/N]: ", "n"),
                                        ("Install Node Recorder? [y/N]: ", "n"),
                                        ("Install Pibrary? [y/N]: ", "n"),
                                        ("Install Terminal Monitor? [y/N]: ", "n")])
        self.assertEqual(rc, 0, out[-2500:])
        self.assertEqual(self.unanswered, [])
        self.assertIn("git — needed for downloads from GitHub", out)
        self.assertIn("install -y -qq git", self.apt_log())
        self.assertTrue(self.installed("wifimon"))

    def test_no_to_git_uses_only_the_files_on_the_pi(self):
        url = self.repo()
        self.put("wifimon", "9.9.1")
        rc, out = self.run_tty("--core", env={"ASL_DVS_GIT_URL": url}, missing=("git",),
                               answers=[("Install git with apt? [Y/n]: ", "n"),
                                        ("Select wifimon version [a]: ", ""),
                                        ("Install Node Talker? [y/N]: ", "n"),
                                        ("Install Node Recorder? [y/N]: ", "n"),
                                        ("Install Pibrary? [y/N]: ", "n"),
                                        ("Install Terminal Monitor? [y/N]: ", "n")])
        self.assertEqual(rc, 0, out[-2500:])
        self.assertNotIn("install", self.apt_log())
        self.assertIn("Not installed: git", out)
        self.assertNotIn("git is needed to download", out)
        with open("/usr/local/bin/wifimon.py") as fh:
            self.assertIn('VERSION = "9.9.1"', fh.read())

    def test_several_missing_programs_are_one_question(self):
        self.put("wifimon")
        rc, out = self.run_tty("--core", "--offline", missing=("ss", "openssl"),
                               answers=[("Install iproute2 openssl with apt? [Y/n]: ", "y"),
                                        ("Select wifimon version [a]: ", "")])
        self.assertEqual(rc, 0, out[-2500:])
        self.assertEqual(self.unanswered, [])
        self.assertIn("install -y -qq iproute2 openssl", self.apt_log())
        self.assertIn("Installed: iproute2 openssl", out)

    def test_a_run_without_a_terminal_installs_git_as_before_and_only_warns_about_the_rest(self):
        url = self.repo()
        path = self.sandbox_path("git", "openssl")
        rc, out = self.run_installer("--non-interactive", "--core", env={"ASL_DVS_GIT_URL": url, "PATH": path})
        self.assertEqual(rc, 0, out[-2500:])
        self.assertIn("openssl is not installed", out)
        self.assertIn("install -y -qq git", self.apt_log())
        self.assertNotIn("openssl", self.apt_log())
        self.assertTrue(self.installed("wifimon"))


def fake_installer(version):
    return f'''#!/usr/bin/env bash
# install_all.sh  v{version}  (2099-01-01)
echo "FAKE INSTALLER {version} args:$*"
if [[ -t 0 ]]; then echo "stdin is a terminal"; fi
'''


class BootstrapTests(InstallerBase):
    OLD = "install_all_v7_4_0_20990101.sh"
    GOOD = "install_all_v7_6_0_20990101.sh"
    NEW = "install_all_v7_10_0_20990102.sh"

    def setUp(self):
        super().setUp()
        self.site = os.path.join(self.d, "site")
        self.commit = "c" * 40
        os.makedirs(os.path.join(self.site, "main", "channels"))
        os.makedirs(os.path.join(self.site, self.commit))
        self.write("main", "README.md", f"old `{self.GOOD}` and now `{self.NEW}`\n")
        self.write("main", self.NEW, fake_installer("7.10.0"))
        self.write(self.commit, self.GOOD, fake_installer("7.6.0"))
        self.write(self.commit, self.OLD, fake_installer("7.4.0"))

    def write(self, rev, name, body):
        with open(os.path.join(self.site, rev, name), "w") as fh:
            fh.write(body)

    def blob(self, rev, name):
        return subprocess.run(["git", "hash-object", os.path.join(self.site, rev, name)],
                              capture_output=True, text=True).stdout.strip()

    def stable(self, name, blob=None):
        entry = {"file": name, "commit": self.commit, "blob": blob or self.blob(self.commit, name), "version": "x"}
        with open(os.path.join(self.site, "main", "channels", "stable.json"), "w") as fh:
            json.dump({"channel": "stable", "tools": {"44helper": {"file": "44helper_v1_0_0_20990101.py"},
                                                      "install_all": entry}}, fh, indent=1, sort_keys=True)

    def run_bootstrap(self, *args, env=None):
        full = self.environment(dict({"ASL_DVS_RAW_URL": "file://" + self.site}, **(env or {})))
        with open(BOOTSTRAP) as fh:
            r = subprocess.run(["bash", "-s", "--", *args], cwd=self.work, env=full, stdin=fh,
                               capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def test_stable_runs_the_listed_installer_and_keeps_a_copy(self):
        self.stable(self.GOOD)
        rc, out = self.run_bootstrap()
        self.assertEqual(rc, 0, out)
        self.assertIn("FAKE INSTALLER 7.6.0", out)
        self.assertTrue(os.path.isfile(os.path.join(self.lib, "scripts", self.GOOD)))

    def test_a_stable_installer_older_than_the_first_suite_one_is_passed_over(self):
        self.stable(self.OLD)
        rc, out = self.run_bootstrap()
        self.assertEqual(rc, 0, out)
        self.assertIn("is older than 7.6.0", out)
        self.assertIn("FAKE INSTALLER 7.10.0", out)

    def test_testing_takes_the_newest_named_in_the_readme(self):
        self.stable(self.GOOD)
        rc, out = self.run_bootstrap(env={"ASL_DVS_CHANNEL": "testing"})
        self.assertEqual(rc, 0, out)
        self.assertIn("FAKE INSTALLER 7.10.0", out)

    def test_no_stable_list_falls_back_to_the_newest(self):
        rc, out = self.run_bootstrap()
        self.assertEqual(rc, 0, out)
        self.assertIn("FAKE INSTALLER 7.10.0", out)

    def test_a_file_that_does_not_match_the_stable_list_is_not_run(self):
        self.stable(self.GOOD, blob="0" * 40)
        rc, out = self.run_bootstrap()
        self.assertNotEqual(rc, 0)
        self.assertIn("does not match the stable list", out)
        self.assertNotIn("FAKE INSTALLER", out)

    def test_a_file_that_is_not_an_installer_is_not_run(self):
        self.write("main", self.NEW, "#!/usr/bin/env bash\necho FAKE INSTALLER\n")
        rc, out = self.run_bootstrap(env={"ASL_DVS_CHANNEL": "testing"})
        self.assertNotEqual(rc, 0)
        self.assertIn("is not an installer", out)
        self.assertNotIn("\nFAKE INSTALLER", out)

    def test_arguments_reach_the_installer(self):
        self.stable(self.GOOD)
        rc, out = self.run_bootstrap("--with-termon", "--core")
        self.assertEqual(rc, 0, out)
        self.assertIn("args:--with-termon --core", out)

    def test_no_network_fails_clearly(self):
        rc, out = self.run_bootstrap(env={"ASL_DVS_RAW_URL": "file:///nonexistent/site"})
        self.assertNotEqual(rc, 0)
        self.assertIn("Could not reach", out)

    def test_piped_in_from_a_terminal_session_the_installer_gets_the_terminal(self):
        self.stable(self.GOOD)
        env = {"ASL_DVS_RAW_URL": "file://" + self.site}
        rc, out = self.run_tty(env=env, command=["bash", "-c", f"cat '{BOOTSTRAP}' | bash"])
        self.assertEqual(rc, 0, out)
        self.assertIn("FAKE INSTALLER 7.6.0", out)
        self.assertIn("stdin is a terminal", out)


class UninstallerTests(InstallerBase):
    def setUp(self):
        super().setUp()
        self.script = os.path.join(self.d, "uninstall_all.sh")
        shutil.copyfile(UNINSTALLER, self.script)

    def test_terminal_monitor_is_uninstalled_with_its_own_command(self):
        self.install_old("termon", "9.9.0")
        self.state("termon", "active", "enabled")
        rc, out = self.run_installer()
        self.assertEqual(rc, 0, out[-1500:])
        self.assertIn("-- termon --", out)
        self.assertIn("running its own --uninstall", out)
        self.assertIn("termon uninstalled", out)
        self.assertFalse(self.installed("termon"))
        self.assertIn("termon_tls", out)

    def test_it_says_when_terminal_monitor_is_not_installed(self):
        rc, out = self.run_installer()
        self.assertEqual(rc, 0, out[-1500:])
        self.assertIn("Not installed at /usr/local/bin/termon.py, skipping", out)

    def test_the_banner_has_no_product_prefix(self):
        rc, out = self.run_installer()
        self.assertIn("== Suite — Mass Uninstall", out)
        self.assertNotIn("== ASL-DVS Suite", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
