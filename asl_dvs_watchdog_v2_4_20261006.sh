#!/bin/bash
# asl_dvs_watchdog.sh  v2.4  (2026-10-06)
set -u

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[0;33m'; CYN=$'\033[0;36m'; BLD=$'\033[1m'; RST=$'\033[0m'
ok()   { echo "${GRN}  ✔ ${RST}$*"; }
info() { echo "${CYN}  → ${RST}$*"; }
warn() { echo "${YEL}  ⚠ ${RST}$*"; }
die()  { echo "${RED}  ✘ ${RST}$*" >&2; exit 1; }
hdr()  { echo; echo "${BLD}${CYN}== $* ==${RST}"; }

SCRIPT_VERSION="2.4"
BUILD_DATE="20261005"

PORT="${ASL_DVS_WATCHDOG_PORT:-8989}"
URL="http://localhost:${PORT}/api/ping"
TARGET_SERVICE="${ASL_DVS_WATCHDOG_TARGET:-asl_dvs_dashboard.service}"
CURL_TIMEOUT=5
RETRY_DELAY=5

INSTANCE="${ASL_DVS_WATCHDOG_INSTANCE:-}"
if [[ -n "${INSTANCE}" && ! "${INSTANCE}" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "asl_dvs_watchdog: invalid ASL_DVS_WATCHDOG_INSTANCE '${INSTANCE}'" \
         "-- letters, digits, '_' and '-' only" >&2
    exit 1
fi
INSTANCE_SUFFIX=""
[[ -n "${INSTANCE}" ]] && INSTANCE_SUFFIX="-${INSTANCE}"

LOG_TAG="asl_dvs_watchdog${INSTANCE_SUFFIX}"
BIN_PATH="/usr/local/bin/asl_dvs_watchdog${INSTANCE_SUFFIX}.sh"
SERVICE_NAME="asl_dvs_watchdog${INSTANCE_SUFFIX}.service"
TIMER_NAME="asl_dvs_watchdog${INSTANCE_SUFFIX}.timer"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
TIMER_FILE="/etc/systemd/system/${TIMER_NAME}"


check() {
    local code
    code="$(curl -sS --max-time "${CURL_TIMEOUT}" -o /dev/null -w '%{http_code}' "${URL}" 2>/dev/null)"
    [[ "${code}" =~ ^[1-4][0-9][0-9]$ ]]
}

run_check() {
    if check; then
        exit 0
    fi

    logger -t "${LOG_TAG}" "status check failed (timeout ${CURL_TIMEOUT}s), retrying once in ${RETRY_DELAY}s before restart"
    sleep "${RETRY_DELAY}"

    if check; then
        logger -t "${LOG_TAG}" "status check recovered on retry, no restart needed"
        exit 0
    fi

    logger -t "${LOG_TAG}" "status check failed twice in a row, restarting ${TARGET_SERVICE}"
    systemctl restart "${TARGET_SERVICE}"
}


do_install() {
    [[ "${EUID}" -eq 0 ]] || die "Must be run as root.  Use: sudo bash asl_dvs_watchdog.sh --install"

    command -v systemctl &>/dev/null || die "systemctl not found — this installer requires systemd"
    command -v curl      &>/dev/null || die "curl not found — required for the liveness check itself. Install with: apt install curl"

    hdr "Installing asl_dvs_watchdog v${SCRIPT_VERSION}${INSTANCE:+ (instance: ${INSTANCE})}"

    local self
    self="$(readlink -f "$0" 2>/dev/null || echo "$0")"
    if [[ "${self}" == "${BIN_PATH}" ]]; then
        info "Already running from ${BIN_PATH} — skipping self-copy"
    else
        install -m 0755 "${self}" "${BIN_PATH}" || die "Failed to install binary to ${BIN_PATH}"
        ok "Installed: ${BIN_PATH}"
    fi

    info "Writing service unit…"
    cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=ASL-DVS Dashboard external watchdog check
After=${TARGET_SERVICE}
Requisite=${TARGET_SERVICE}

[Service]
Type=oneshot
Environment=ASL_DVS_WATCHDOG_PORT=${PORT}
Environment=ASL_DVS_WATCHDOG_TARGET=${TARGET_SERVICE}
ExecStart=${BIN_PATH}
EOF
    ok "Service unit: ${SERVICE_FILE}"

    info "Writing timer unit…"
    cat > "${TIMER_FILE}" <<EOF
[Unit]
Description=Run ASL-DVS Dashboard watchdog check periodically

[Timer]
OnBootSec=60
OnUnitActiveSec=45
AccuracySec=5
Unit=${SERVICE_NAME}

[Install]
WantedBy=timers.target
EOF
    ok "Timer unit: ${TIMER_FILE}"

    systemctl daemon-reload || die "systemctl daemon-reload failed"
    ok "systemd daemon reloaded"

    systemctl enable --now "${TIMER_NAME}" || die "Failed to enable+start ${TIMER_NAME}"
    ok "${TIMER_NAME} enabled and started"

    info "Running one verification check now…"
    if systemctl start "${SERVICE_NAME}"; then
        ok "Verification check ran cleanly (see: journalctl -t ${LOG_TAG} -n 10)"
    else
        warn "Verification check reported a failure — this can be normal on a fresh"
        warn "install if ${TARGET_SERVICE} isn't up yet. Check: journalctl -t ${LOG_TAG} -n 10"
    fi

    echo
    ok "Install complete.${INSTANCE:+ (instance: ${INSTANCE})}"
    info "Watching: ${URL}  →  restarts ${TARGET_SERVICE} on repeated failure"
    if [[ -n "${INSTANCE}" ]]; then
        info "Status:   sudo ASL_DVS_WATCHDOG_INSTANCE=${INSTANCE} bash ${BIN_PATH} --status"
    else
        info "Status:   sudo bash asl_dvs_watchdog.sh --status"
    fi
}


do_uninstall() {
    [[ "${EUID}" -eq 0 ]] || die "Must be run as root.  Use: sudo bash asl_dvs_watchdog.sh --uninstall"

    hdr "Uninstalling asl_dvs_watchdog${INSTANCE:+ (instance: ${INSTANCE})}"

    systemctl stop "${TIMER_NAME}"   2>/dev/null && ok "Stopped ${TIMER_NAME}"   || info "${TIMER_NAME} was not running"
    systemctl disable "${TIMER_NAME}" 2>/dev/null && ok "Disabled ${TIMER_NAME}" || info "${TIMER_NAME} was not enabled"
    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true

    if [[ -f "${TIMER_FILE}" ]]; then
        rm -f "${TIMER_FILE}"
        ok "Removed ${TIMER_FILE}"
    fi
    if [[ -f "${SERVICE_FILE}" ]]; then
        rm -f "${SERVICE_FILE}"
        ok "Removed ${SERVICE_FILE}"
    fi

    systemctl daemon-reload || warn "systemctl daemon-reload failed — units may still show as loaded"
    systemctl reset-failed "${SERVICE_NAME}" 2>/dev/null || true

    if [[ -f "${BIN_PATH}" ]]; then
        rm -f "${BIN_PATH}"
        ok "Removed ${BIN_PATH}"
    else
        info "${BIN_PATH} not present — nothing to remove"
    fi

    echo
    ok "Uninstall complete. ${TARGET_SERVICE} itself was left untouched."
}


do_status() {
    hdr "asl_dvs_watchdog status${INSTANCE:+ (instance: ${INSTANCE})}"
    info "Watching ${URL}  →  restarts ${TARGET_SERVICE} on repeated failure"
    echo "  ${BLD}Timer:${RST}"
    systemctl status "${TIMER_NAME}" --no-pager -l 2>&1 | sed 's/^/  /' || info "${TIMER_NAME} not installed"
    echo
    echo "  ${BLD}Last check (service):${RST}"
    systemctl status "${SERVICE_NAME}" --no-pager -l 2>&1 | sed 's/^/  /' || info "${SERVICE_NAME} not installed"
    echo
    echo "  ${BLD}Recent log:${RST}"
    journalctl -t "${LOG_TAG}" -n 10 --no-pager 2>&1 | sed 's/^/  /'
}


_SYSMON_TEST_SRC() {
    cat <<'PYEOF'
"""
test_sysmon.py — Stage 5 regression suite (reliability plan item 6 of 6)

Stdlib-only, single file, zero pip dependencies — matches the fleet's own
house style. Run with:

    python3 test_sysmon.py -v

Covers the four areas called out in sysmon_reliability_plan.docx:
  1. load_config / save_config round-trip (incl. the v6.5.7 fsync path)
  2. radio-restart lock (start_radio_stack_restart / _RADIO_RESTART_LOCK)
  3. port-conflict detection (check_port_duplicates)
  4. get_services_details batched path (incl. its per-unit fallback)

No test here touches the real system: every subprocess-shaped call goes
through sysmon's own `_run()`/`subprocess.run` seam, which every test
patches (and restores in tearDown). CONFIG_FILE is patched to a tempfile
dir for every config test, so nothing here ever touches
/etc/sysmon/sysmon.conf.
"""
import configparser
import importlib
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Set this to the filename under test (no .py).
MODULE_NAME = "sysmon_v6_5_7"

sys.path.insert(0, str(Path(__file__).parent))
sysmon = importlib.import_module(MODULE_NAME)

# Captured before any test patches sysmon.time.sleep — `time` is a
# singleton module, so patching sysmon.time.sleep patches this file's
# time.sleep too. Poll loops below use this reference instead.
_real_sleep = time.sleep


class _Patcher:
    """Minimal manual monkeypatch: setattr now, restore on tearDown.
    Avoids a pytest/mock dependency while keeping call sites terse."""

    def __init__(self):
        self._saved = []  # list of (obj, attr, original_value)

    def set(self, obj, attr, value):
        self._saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, value)

    def undo(self):
        for obj, attr, original in reversed(self._saved):
            setattr(obj, attr, original)
        self._saved.clear()


_SS_HEADER = "Netid  State   Recv-Q  Send-Q   Local Address:Port   Peer Address:Port"


# ---------------------------------------------------------------------------
# 1. load_config / save_config round-trip
# ---------------------------------------------------------------------------

class TestConfigRoundTrip(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sysmon_test_"))
        self.conf_path = self.tmpdir / "sysmon.conf"
        self.patcher = _Patcher()
        self.patcher.set(sysmon, "CONFIG_FILE", self.conf_path)
        self._orig_cfg = sysmon._cfg

    def tearDown(self):
        sysmon._cfg = self._orig_cfg
        self.patcher.undo()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_missing_file_returns_defaults(self):
        cfg = sysmon.load_config(self.conf_path)
        self.assertIsInstance(cfg, configparser.ConfigParser)
        for section in sysmon._DEFAULT_CONFIG:
            self.assertTrue(cfg.has_section(section))

    def test_save_creates_file_and_is_loadable(self):
        ok = sysmon.save_config({"identity.callsign": "KD8PGK"}, path=self.conf_path)
        self.assertTrue(ok)
        self.assertTrue(self.conf_path.exists())

        reloaded = sysmon.load_config(self.conf_path)
        self.assertEqual(reloaded.get("identity", "callsign", fallback=""), "KD8PGK")

    def test_save_dotted_key_and_dict_value_both_apply(self):
        ok = sysmon.save_config(
            {
                "identity.node": "652701",
                "services": {"pinned": "asterisk.service,dvswitch.service"},
            },
            path=self.conf_path,
        )
        self.assertTrue(ok)
        reloaded = sysmon.load_config(self.conf_path)
        self.assertEqual(reloaded.get("identity", "node", fallback=""), "652701")
        self.assertEqual(
            reloaded.get("services", "pinned", fallback=""),
            "asterisk.service,dvswitch.service",
        )

    def test_save_is_atomic_no_tmp_left_behind(self):
        sysmon.save_config({"identity.callsign": "KD8PGK"}, path=self.conf_path)
        tmp = self.conf_path.with_suffix(".tmp")
        # os.replace() should have moved .tmp onto the real path — nothing
        # left over even though save_config fsyncs before the rename.
        self.assertFalse(tmp.exists())
        self.assertTrue(self.conf_path.exists())

    def test_save_survives_unwritable_parent(self):
        # Point at a path whose parent can never be created (a file, not
        # a dir, in the way) — save_config must catch and return False,
        # not raise, matching its documented contract.
        blocker = self.tmpdir / "not_a_dir"
        blocker.write_text("x")
        bad_path = blocker / "sysmon.conf"
        ok = sysmon.save_config({"identity.callsign": "X"}, path=bad_path)
        self.assertFalse(ok)

    def test_atomic_write_helper_round_trips_arbitrary_content(self):
        target = self.tmpdir / "some_file.conf"
        sysmon._atomic_write(target, "hello\nworld\n")
        self.assertEqual(target.read_text(), "hello\nworld\n")
        self.assertFalse(target.with_suffix(target.suffix + ".tmp").exists())


# ---------------------------------------------------------------------------
# 2. Radio-restart lock
# ---------------------------------------------------------------------------

class TestRadioRestartLock(unittest.TestCase):

    def setUp(self):
        self.patcher = _Patcher()
        self._reset_lock_state()

    def tearDown(self):
        self.patcher.undo()
        self._reset_lock_state()

    def _reset_lock_state(self):
        if sysmon._RADIO_RESTART_LOCK.locked():
            sysmon._RADIO_RESTART_LOCK.release()
        sysmon._radio_restart_update(
            phase="idle", driver="", started_at=0.0, finished_at=0.0,
            last_ok=None, last_msg="", unload_ok=None,
        )

    def _wait_for_idle(self, timeout_s=2.5):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not sysmon.radio_stack_restarting():
                return True
            _real_sleep(0.05)
        return False

    def test_unknown_driver_rejected_without_touching_lock(self):
        ok, msg = sysmon.start_radio_stack_restart("not_a_real_driver")
        self.assertFalse(ok)
        self.assertIn("unknown driver", msg)
        self.assertFalse(sysmon._RADIO_RESTART_LOCK.locked())

    def test_successful_restart_updates_state_and_releases_lock(self):
        driver = next(iter(sysmon._RADIO_TUNE_DRIVERS))

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        self.patcher.set(sysmon.subprocess, "run", lambda *a, **kw: R())
        self.patcher.set(sysmon.time, "sleep", lambda *a, **kw: None)

        ok, msg = sysmon.start_radio_stack_restart(driver)
        self.assertTrue(ok)
        self.assertIn("restart started", msg)

        self.assertTrue(self._wait_for_idle(),
                         "restart thread did not reach idle phase in time")

        snap = sysmon._radio_restart_snapshot()
        self.assertEqual(snap["phase"], "idle")
        self.assertTrue(snap["last_ok"])
        self.assertFalse(sysmon._RADIO_RESTART_LOCK.locked())

    def test_concurrent_restart_rejected_while_lock_held(self):
        driver = next(iter(sysmon._RADIO_TUNE_DRIVERS))
        # Hold the lock exactly like a real in-flight restart would,
        # without spawning the background thread or touching subprocess.
        self.assertTrue(sysmon._RADIO_RESTART_LOCK.acquire(blocking=False))
        try:
            ok, msg = sysmon.start_radio_stack_restart(driver)
            self.assertFalse(ok)
            self.assertIn("already in progress", msg)
        finally:
            sysmon._RADIO_RESTART_LOCK.release()

    def test_failed_subprocess_marks_last_ok_false_and_still_releases_lock(self):
        driver = next(iter(sysmon._RADIO_TUNE_DRIVERS))

        class R:
            returncode = 1
            stdout = ""
            stderr = "asterisk: command failed"

        self.patcher.set(sysmon.subprocess, "run", lambda *a, **kw: R())
        self.patcher.set(sysmon.time, "sleep", lambda *a, **kw: None)

        ok, _ = sysmon.start_radio_stack_restart(driver)
        self.assertTrue(ok)  # restart *started* fine; failure is async

        self.assertTrue(self._wait_for_idle(),
                         "restart thread did not reach idle phase in time")

        snap = sysmon._radio_restart_snapshot()
        self.assertFalse(snap["last_ok"])
        self.assertIn("failed", snap["last_msg"].lower())
        # the finally: block must release the lock even on failure
        self.assertFalse(sysmon._RADIO_RESTART_LOCK.locked())


# ---------------------------------------------------------------------------
# 3. Port-conflict detection
# ---------------------------------------------------------------------------

class TestCheckPortDuplicates(unittest.TestCase):

    def setUp(self):
        self.patcher = _Patcher()

    def tearDown(self):
        self.patcher.undo()

    def test_no_output_returns_empty(self):
        self.patcher.set(sysmon, "_run", lambda *a, **kw: "")
        self.assertEqual(sysmon.check_port_duplicates(), {})

    def test_no_conflicts_returns_empty(self):
        raw = "\n".join([
            _SS_HEADER,
            'tcp    LISTEN  0   128   0.0.0.0:8989   0.0.0.0:*   users:(("dash",pid=100,fd=3))',
            'udp    UNCONN  0   0     0.0.0.0:9999   0.0.0.0:*   users:(("sysmon",pid=200,fd=3))',
        ])
        self.patcher.set(sysmon, "_run", lambda *a, **kw: raw)
        self.assertEqual(sysmon.check_port_duplicates(), {})

    def test_two_pids_on_same_port_flagged(self):
        raw = "\n".join([
            _SS_HEADER,
            'tcp    LISTEN  0   128   0.0.0.0:34001   0.0.0.0:*   users:(("asterisk",pid=100,fd=3))',
            'tcp    LISTEN  0   128   0.0.0.0:34001   0.0.0.0:*   users:(("rogue",pid=999,fd=5))',
        ])
        self.patcher.set(sysmon, "_run", lambda *a, **kw: raw)
        result = sysmon.check_port_duplicates()
        self.assertIn("tcp:34001", result)
        pids = {p["pid"] for p in result["tcp:34001"]}
        self.assertEqual(pids, {100, 999})

    def test_same_pid_twice_not_flagged_as_conflict(self):
        # e.g. a process holding both an IPv4 and IPv6 listener on one
        # port is not a real conflict — dedup is by pid within the key.
        raw = "\n".join([
            _SS_HEADER,
            'tcp    LISTEN  0   128   0.0.0.0:8989   0.0.0.0:*   users:(("dash",pid=100,fd=3))',
            'tcp    LISTEN  0   128   [::]:8989      [::]:*      users:(("dash",pid=100,fd=4))',
        ])
        self.patcher.set(sysmon, "_run", lambda *a, **kw: raw)
        self.assertEqual(sysmon.check_port_duplicates(), {})

    def test_tcp_and_udp_on_same_port_number_are_distinct_keys(self):
        raw = "\n".join([
            _SS_HEADER,
            'tcp    LISTEN  0   128   0.0.0.0:5000   0.0.0.0:*   users:(("a",pid=1,fd=3))',
            'tcp    LISTEN  0   128   0.0.0.0:5000   0.0.0.0:*   users:(("b",pid=2,fd=3))',
            'udp    UNCONN  0   0     0.0.0.0:5000   0.0.0.0:*   users:(("c",pid=3,fd=3))',
        ])
        self.patcher.set(sysmon, "_run", lambda *a, **kw: raw)
        result = sysmon.check_port_duplicates()
        self.assertIn("tcp:5000", result)
        self.assertNotIn("udp:5000", result)  # only one udp pid on 5000


# ---------------------------------------------------------------------------
# 4. get_services_details batched path
# ---------------------------------------------------------------------------

class TestGetServicesDetails(unittest.TestCase):

    def setUp(self):
        self.patcher = _Patcher()

    def tearDown(self):
        self.patcher.undo()

    def test_invalid_unit_name_short_circuits_without_subprocess(self):
        calls = []
        self.patcher.set(sysmon, "_run",
                          lambda *a, **kw: (calls.append(a), "")[1])
        result = sysmon.get_services_details(["../not a unit"])
        self.assertEqual(result["../not a unit"]["error"], "invalid unit name")
        self.assertEqual(calls, [])  # never shelled out for a name that can't be valid

    def test_duplicate_units_deduped(self):
        # both list-unit-files and show should only ever be asked about
        # "asterisk.service" once, even though it's requested twice.
        seen_cmds = []

        def fake_run(cmd, timeout=5):
            seen_cmds.append(cmd)
            if "list-unit-files" in cmd:
                return "asterisk.service enabled"
            if "show" in cmd:
                return (
                    "Description=Asterisk PBX\n"
                    "ActiveState=active\n"
                    "UnitFileState=enabled\n"
                    "MainPID=1234\n"
                    "NRestarts=0\n"
                    "ExecMainStatus=0\n"
                    "CanReload=yes\n"
                )
            return ""

        self.patcher.set(sysmon, "_run", fake_run)
        result = sysmon.get_services_details(["asterisk.service", "asterisk.service"])
        self.assertEqual(list(result.keys()), ["asterisk.service"])
        list_files_calls = [c for c in seen_cmds if "list-unit-files" in c]
        self.assertEqual(len(list_files_calls), 1)
        self.assertEqual(list_files_calls[0].count("asterisk.service"), 1)

    def test_not_installed_unit_gets_not_inst_state(self):
        def fake_run(cmd, timeout=5):
            if "list-unit-files" in cmd:
                return ""  # nothing installed
            return ""

        self.patcher.set(sysmon, "_run", fake_run)
        result = sysmon.get_services_details(["ghost.service"])
        self.assertEqual(result["ghost.service"]["state"], "not-inst")
        self.assertFalse(result["ghost.service"]["installed"])

    def test_batched_show_parses_multiple_blocks_and_enriches_with_ps(self):
        units = ["asterisk.service", "dvswitch.service"]

        def fake_run(cmd, timeout=5):
            if "list-unit-files" in cmd:
                return "asterisk.service enabled\ndvswitch.service enabled"
            if cmd[:2] == ["systemctl", "show"] and len(cmd) > 3 and \
               all(u in cmd for u in units):
                block_a = (
                    "Description=Asterisk PBX\nActiveState=active\n"
                    "UnitFileState=enabled\nMainPID=100\nNRestarts=0\n"
                    "ExecMainStatus=0\nCanReload=yes\n"
                )
                block_b = (
                    "Description=DVSwitch\nActiveState=active\n"
                    "UnitFileState=enabled\nMainPID=200\nNRestarts=1\n"
                    "ExecMainStatus=0\nCanReload=no\n"
                )
                return block_a + "\n\n" + block_b
            if cmd[0] == "ps":
                return "100  1.5  20480\n200  0.5  10240\n"
            return ""

        self.patcher.set(sysmon, "_run", fake_run)
        result = sysmon.get_services_details(units)

        self.assertEqual(result["asterisk.service"]["pid"], 100)
        self.assertEqual(result["asterisk.service"]["cpu_pct"], 1.5)
        self.assertEqual(result["asterisk.service"]["rss_mb"], 20.0)
        self.assertEqual(result["dvswitch.service"]["pid"], 200)
        self.assertEqual(result["dvswitch.service"]["nrestarts"], 1)
        self.assertFalse(result["dvswitch.service"]["can_reload"])

    def test_batched_show_falls_back_to_per_unit_on_block_mismatch(self):
        # If systemd's batched output doesn't split into exactly one
        # block per requested unit, get_services_details must fall back
        # to querying each unit individually rather than mis-mapping data.
        units = ["a.service", "b.service"]
        single_calls = []

        def fake_run(cmd, timeout=5):
            if "list-unit-files" in cmd:
                return "a.service enabled\nb.service enabled"
            if cmd[:2] == ["systemctl", "show"]:
                if len(cmd) > 3 and all(u in cmd for u in units):
                    # deliberately return only ONE block for TWO units
                    return "Description=A\nActiveState=active\nMainPID=1\n"
                single_calls.append(cmd[-1])
                unit = cmd[-1]
                return f"Description={unit}\nActiveState=active\nMainPID=5\n"
            return ""

        self.patcher.set(sysmon, "_run", fake_run)
        result = sysmon.get_services_details(units)

        self.assertEqual(sorted(single_calls), units)
        self.assertEqual(result["a.service"]["pid"], 5)
        self.assertEqual(result["b.service"]["pid"], 5)

    def test_get_service_detail_single_unit_convenience_wrapper(self):
        def fake_run(cmd, timeout=5):
            if "list-unit-files" in cmd:
                return "x.service enabled"
            if cmd[:2] == ["systemctl", "show"]:
                return "Description=X\nActiveState=active\nMainPID=42\n"
            return ""

        self.patcher.set(sysmon, "_run", fake_run)
        detail = sysmon.get_service_detail("x.service")
        self.assertEqual(detail["pid"], 42)
        self.assertEqual(detail["unit"], "x.service")


if __name__ == "__main__":
    unittest.main(verbosity=2)
PYEOF
}

do_test() {
    local sysmon_src="${1:-}"
    command -v python3 &>/dev/null || die "python3 not found — required to run the embedded suite"

    local tmpdir
    tmpdir="$(mktemp -d /tmp/asl_dvs_watchdog_test.XXXXXX)" || die "mktemp failed"
    _SYSMON_TEST_SRC > "${tmpdir}/test_sysmon.py"

    if [[ -z "${sysmon_src}" ]]; then
        warn "This suite tests sysmon.py internals, not the watchdog itself."
        warn "It's bundled here only because merging it into this file was explicitly requested."
        echo
        info "Extracted to: ${tmpdir}/test_sysmon.py"
        info "It expects a module named sysmon_v6_5_7.py (see MODULE_NAME inside the"
        info "extracted file) importable from that same directory."
        echo
        info "Usage:  sudo bash asl_dvs_watchdog.sh --test /path/to/sysmon_v6_5_7.py"
        return 0
    fi

    [[ -f "${sysmon_src}" ]] || die "sysmon module not found: ${sysmon_src}"
    cp "${sysmon_src}" "${tmpdir}/sysmon_v6_5_7.py" || die "Failed to stage sysmon module into ${tmpdir}"

    hdr "Running bundled sysmon regression suite against $(basename "${sysmon_src}")"
    warn "Reminder: this validates sysmon.py, not asl_dvs_watchdog.sh."
    ( cd "${tmpdir}" && python3 test_sysmon.py -v )
    local rc=$?
    info "Test tempdir left at ${tmpdir} for inspection (not auto-cleaned)."
    return "${rc}"
}

usage() {
    cat <<EOF
asl_dvs_watchdog.sh v${SCRIPT_VERSION}

  --install     install + enable + start (idempotent, safe unattended)
  --uninstall   stop + disable + remove everything this script installed
  --status      show timer/service state and recent log lines
  --test [PATH] extract + run the bundled sysmon regression suite
                (tests sysmon.py, NOT this watchdog — see v2.1 note above)
                PATH = path to a sysmon module to test against; omit to
                just extract the suite and print usage
  (no args)     run ONE check — this is what the installed unit executes

Env vars (see v2.2 header note for the multi-instance rationale):
  ASL_DVS_WATCHDOG_PORT       /api/ping port to check        (default 8989)
  ASL_DVS_WATCHDOG_TARGET     unit to restart on failure      (default asl_dvs_dashboard.service)
  ASL_DVS_WATCHDOG_INSTANCE   suffixes installed filenames/units so a second
                               dashboard instance (e.g. the M17/Zello branch)
                               can have its own independent watchdog. Unset
                               = unsuffixed, same names as every pre-v2.2
                               install. Must match the same value across
                               --install/--uninstall/--status/no-args for a
                               given instance.

EOF
}

case "${1:-}" in
    --install)   do_install ;;
    --uninstall) do_uninstall ;;
    --status)    do_status ;;
    --test)      do_test "${2:-}" ;;
    "")          run_check ;;
    -h|--help)   usage ;;
    *)           echo "Unknown option: $1" >&2; usage; exit 1 ;;
esac
