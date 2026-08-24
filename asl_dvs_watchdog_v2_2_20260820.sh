#!/bin/bash
#
# asl_dvs_watchdog.sh  v2.2  (2026-08-20)
# External liveness watchdog for asl_dvs_dashboard.service (and, as of
# v2.2, any other Library-Card dashboard instance running the same
# /api/status contract)
# KD8PGK / Claude AI (Anthropic)  —  CC BY-NC 4.0
#
# v2.2: asl_dvs_dashboard v8.0 merged the M17 tab (USRP2M17 bridge) from
# the asl_dvs_m17_dashboard feature branch into the mainline dashboard —
# but ZELLO was deliberately left behind on that branch, not ported. That
# means the branch didn't go away: it's still a second, independently
# running dashboard process (its own port, its own systemd unit) carrying
# Zello support the mainline doesn't have. Before v8.0 there was only ever
# one dashboard instance to watch, so this script never needed to name
# more than one set of units. Now there are two live instances again, so
# this script gained instance naming:
#   ASL_DVS_WATCHDOG_INSTANCE   suffixes every installed filename/unit
#                                 (default: unset — unsuffixed, 100%
#                                 backward compatible with existing
#                                 single-instance installs)
# This lets --install be run twice on the same box, once per dashboard
# instance, without either install stepping on the other's binary, unit
# files, or timer. See the Usage block below for both invocations.
# The change is naming-only — the actual check logic (curl /api/status,
# retry once, restart on second failure) is identical for every instance;
# it doesn't know or care that one instance also happens to serve M17/Zello.
#
# v2.1: Bundled sysmon's Stage 5 regression suite (test_sysmon.py) into
# this file verbatim, exposed via a new `--test` flag, per explicit
# request to merge it into the watchdog. IMPORTANT — this is a direct
# merge as asked for, not an endorsement that it belongs here: the
# embedded suite exercises sysmon.py internals (load_config/save_config
# round-trip, the radio-restart lock, check_port_duplicates,
# get_services_details) and has no coverage of anything in THIS script
# (check/run_check/do_install/do_uninstall/do_status). Running --test
# tells you whether a sysmon build is healthy; it tells you nothing
# about whether the watchdog itself is healthy. It's bundled here
# purely for single-file delivery convenience, not because the watchdog
# depends on or is validated by it. See do_test() below for the actual
# extraction/execution mechanics.
#
# v2.0 REWORK NOTES:
# Previously this logic was split across three files (asl_dvs_watchdog.sh,
# asl_dvs_watchdog.service, asl_dvs_watchdog.timer) that had to be copied
# into place and wired up by hand. As of v2.0 it's a single self-installing
# file: the unit files are generated in-place by --install, and the check
# logic that used to be the entire script is now just the default
# (no-argument) code path. This matches the "Library Card" self-install
# convention used elsewhere in the suite (instmon components, wifimon,
# 44helper): a component script can install/uninstall itself, and
# install_asl_dvs just shells out to `bash <this file> --install` rather
# than reimplementing unit-writing logic for every component.
#
# Why a single file instead of the old three: fewer things to go stale
# against each other (unit content and check logic used to live in
# different files with no version linkage), fewer files to stage/deliver/
# track versions for, and it gets the same self-install treatment as
# every other Library Card component instead of being the one thing that
# still needed manual `cp` + `systemctl enable` steps.
#
# Reliability hardening item 4 of 6 (see asl_dvs_dashboard_reliability_plan.docx).
# Runs on a timer (asl_dvs_watchdog.timer), OUTSIDE the dashboard process
# itself -- an independent second line of defense against hangs that the
# in-process sd_notify heartbeat (asl_dvs_dashboard.py v7.781, WatchdogSec=30)
# might miss. Those two mechanisms don't overlap perfectly: the in-process
# heartbeat only proves _link_poll_loop is still ticking -- it says nothing
# about whether the HTTP thread pool itself is wedged. This script proves
# the HTTP side is actually answering requests, from outside the process,
# which the in-process heartbeat structurally cannot do.
#
# NOTE ON THE "STFU-visibility-class" enable/restart bug: several other
# self-installers in this suite (dashboard, sysmon, wifimon, 44helper) had
# a bug where re-running --install on an already-active persistent daemon
# was a no-op -- `systemctl enable --now` doesn't restart an already-active
# unit, so the OLD code stayed resident in memory even after a fresh binary
# was copied into place. That bug class doesn't apply here in the same way:
# this "service" is Type=oneshot, invoked fresh by the timer every
# OnUnitActiveSec, so there is no long-lived watchdog process that can go
# stale -- every firing re-execs whatever binary currently sits at
# ${BIN_PATH}. --install still runs one verification check immediately
# after writing the units, just to prove the new wiring actually works
# rather than relying on the next scheduled firing to find out.
#
# Usage:
#   sudo bash asl_dvs_watchdog.sh --install     install + enable + start (idempotent)
#   sudo bash asl_dvs_watchdog.sh --uninstall   stop + disable + remove everything
#   sudo bash asl_dvs_watchdog.sh --status      show timer/service state + recent log
#   sudo bash asl_dvs_watchdog.sh               run ONE check (this is what the
#                                                 installed .service unit executes)
#
# Mainline dashboard instance (unchanged from earlier versions):
#   sudo bash asl_dvs_watchdog.sh --install
#
# M17/Zello branch instance, installed alongside it on the same box —
# substitute that instance's real port/unit/instance name:
#   sudo ASL_DVS_WATCHDOG_INSTANCE=m17zello \
#        ASL_DVS_WATCHDOG_PORT=8990 \
#        ASL_DVS_WATCHDOG_TARGET=asl_dvs_m17_dashboard.service \
#        bash asl_dvs_watchdog.sh --install
# (--uninstall / --status / the no-arg check also take ASL_DVS_WATCHDOG_INSTANCE
# to target that same instance; omit it to operate on the mainline instance.)
#
# Installed layout (all written by --install; INSTANCE below is the value of
# ASL_DVS_WATCHDOG_INSTANCE, or nothing at all -- and no "-" separator -- when
# that var is unset, which reproduces the exact pre-v2.2 unsuffixed filenames):
#   /usr/local/bin/asl_dvs_watchdog[-INSTANCE].sh              this script
#   /etc/systemd/system/asl_dvs_watchdog[-INSTANCE].service    oneshot check
#   /etc/systemd/system/asl_dvs_watchdog[-INSTANCE].timer      OnBootSec=60 OnUnitActiveSec=45
#
# Env overrides (apply to BOTH the check path and unit generation in --install,
# so they stay in sync automatically -- no more hand-editing the .service file
# separately from the script like the old three-file layout required):
#   ASL_DVS_WATCHDOG_PORT      dashboard /api/status port  (default 8989)
#   ASL_DVS_WATCHDOG_TARGET    systemd unit to restart on failure (default
#                               asl_dvs_dashboard.service)
#   ASL_DVS_WATCHDOG_INSTANCE  suffixes the installed filenames/units so
#                               multiple dashboard instances can each have
#                               their own independent watchdog (default:
#                               unset -- unsuffixed, matches every install
#                               from before v2.2). Letters, digits, "_" and
#                               "-" only; anything else is rejected before
#                               it ever touches a path.
#
set -u

# ── Colour helpers (install/uninstall/status output only — never used on
#    the bare check path, which logs via `logger` for journald instead) ──
RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[0;33m'; CYN=$'\033[0;36m'; BLD=$'\033[1m'; RST=$'\033[0m'
ok()   { echo "${GRN}  ✔ ${RST}$*"; }
info() { echo "${CYN}  → ${RST}$*"; }
warn() { echo "${YEL}  ⚠ ${RST}$*"; }
die()  { echo "${RED}  ✘ ${RST}$*" >&2; exit 1; }
hdr()  { echo; echo "${BLD}${CYN}== $* ==${RST}"; }

# ── Config info header (kept verbatim in the stripped delivery copy) ──────────
SCRIPT_VERSION="2.2"
BUILD_DATE="20260820"

PORT="${ASL_DVS_WATCHDOG_PORT:-8989}"
URL="http://localhost:${PORT}/api/status"
TARGET_SERVICE="${ASL_DVS_WATCHDOG_TARGET:-asl_dvs_dashboard.service}"
CURL_TIMEOUT=5
RETRY_DELAY=5

# INSTANCE lets multiple dashboard processes (e.g. the mainline dashboard
# and the M17/Zello branch dashboard) each get their own independently
# installed/enabled/monitored watchdog on the same box -- see the v2.2
# header note and the Usage block above. Validated up front since it feeds
# straight into filesystem paths and unit names below: reject anything
# that isn't letters/digits/underscore/hyphen rather than silently doing
# something surprising with e.g. a stray "/" in it.
INSTANCE="${ASL_DVS_WATCHDOG_INSTANCE:-}"
if [[ -n "${INSTANCE}" && ! "${INSTANCE}" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "asl_dvs_watchdog: invalid ASL_DVS_WATCHDOG_INSTANCE '${INSTANCE}'" \
         "-- letters, digits, '_' and '-' only" >&2
    exit 1
fi
INSTANCE_SUFFIX=""
[[ -n "${INSTANCE}" ]] && INSTANCE_SUFFIX="-${INSTANCE}"

# Unsuffixed when INSTANCE is unset, so every pre-v2.2 single-instance
# install reproduces these exact same paths/unit names unchanged.
LOG_TAG="asl_dvs_watchdog${INSTANCE_SUFFIX}"
BIN_PATH="/usr/local/bin/asl_dvs_watchdog${INSTANCE_SUFFIX}.sh"
SERVICE_NAME="asl_dvs_watchdog${INSTANCE_SUFFIX}.service"
TIMER_NAME="asl_dvs_watchdog${INSTANCE_SUFFIX}.timer"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
TIMER_FILE="/etc/systemd/system/${TIMER_NAME}"

# ══════════════════════════════════════════════════════════════════════════════
# CHECK  (the original script's entire job — now just the default code path)
# ══════════════════════════════════════════════════════════════════════════════

check() {
    # -fsS: fail silently on HTTP error, suppress progress, keep real errors.
    # We only care about exit status here, hence -o /dev/null.
    curl -fsS --max-time "${CURL_TIMEOUT}" -o /dev/null "${URL}"
}

run_check() {
    if check; then
        exit 0
    fi

    # First check failed. Could be a brief stall under load rather than an
    # actual hang -- wait a moment and check once more before concluding the
    # dashboard is really down. This is the short-retry mitigation the
    # reliability plan calls for, to avoid restarting a service that was only
    # briefly slow.
    logger -t "${LOG_TAG}" "status check failed (timeout ${CURL_TIMEOUT}s), retrying once in ${RETRY_DELAY}s before restart"
    sleep "${RETRY_DELAY}"

    if check; then
        logger -t "${LOG_TAG}" "status check recovered on retry, no restart needed"
        exit 0
    fi

    logger -t "${LOG_TAG}" "status check failed twice in a row, restarting ${TARGET_SERVICE}"
    systemctl restart "${TARGET_SERVICE}"
}

# ══════════════════════════════════════════════════════════════════════════════
# SELF-INSTALL
# ══════════════════════════════════════════════════════════════════════════════
# Safe for unattended use (matches the audit bar install_asl_dvs applies to
# every delegated self-installer): no read/input prompts anywhere in this
# path, so it never hangs when called from a backgrounded subprocess with no
# tty (e.g. instmon's "Run Script" button, or install_asl_dvs itself when
# run non-interactively).

do_install() {
    [[ "${EUID}" -eq 0 ]] || die "Must be run as root.  Use: sudo bash asl_dvs_watchdog.sh --install"

    command -v systemctl &>/dev/null || die "systemctl not found — this installer requires systemd"
    command -v curl      &>/dev/null || die "curl not found — required for the liveness check itself. Install with: apt install curl"

    hdr "Installing asl_dvs_watchdog v${SCRIPT_VERSION}${INSTANCE:+ (instance: ${INSTANCE})}"

    # Resolve our own real path before copying — this script is commonly
    # invoked from a staged /tmp copy (install_asl_dvs's stage_and_select),
    # so $0 is NOT necessarily the final destination. Guard against the
    # degenerate case of installing over itself when it's already sitting
    # at BIN_PATH (e.g. `sudo /usr/local/bin/asl_dvs_watchdog.sh --install`
    # run a second time to pick up new env overrides).
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

    # enable --now on the TIMER (not the oneshot service — enabling a
    # oneshot directly doesn't give you recurring execution). Idempotent:
    # re-running this on an already-enabled/active timer is a harmless
    # no-op, unlike the persistent-daemon "STFU" bug class described in
    # the header comment above — there's no stale in-memory process here
    # to worry about restarting.
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

# ══════════════════════════════════════════════════════════════════════════════
# SELF-UNINSTALL
# ══════════════════════════════════════════════════════════════════════════════
# Also unattended-safe. Every step is written to no-op cleanly if the thing
# it's removing was never installed, so this is safe to run speculatively
# (e.g. from an installer's "clean slate" path) without pre-checking state.

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

# ══════════════════════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════════════════════

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

# ══════════════════════════════════════════════════════════════════════════════
# BUNDLED SYSMON REGRESSION SUITE  (test_sysmon.py, embedded verbatim)
# ══════════════════════════════════════════════════════════════════════════════
# See the v2.1 note at the top of this file: this suite tests sysmon.py,
# NOT this watchdog script. It's embedded here on explicit request for
# single-file delivery, not because the watchdog depends on it or is
# validated by it. --test extracts it to a tempdir and runs it exactly
# as documented in its own docstring: `python3 test_sysmon.py -v`,
# against whatever sysmon module you point it at.
#
# The heredoc below is single-quoted ('PYEOF') so none of the Python
# file's own $ / ` / \ characters get touched by bash expansion — this
# is a byte-for-byte embed, not a template.

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
  ASL_DVS_WATCHDOG_PORT       /api/status port to check      (default 8989)
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

# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
# The --install / --uninstall tokens below are matched literally (plain
# case patterns, not built from concatenation) so instmon's self-install
# substring detection can find them in this file unmodified. If this file
# is ever re-delivered through strip_delivery.py, the comment-stripping
# pass must preserve these tokens byte-for-byte — that's the same class of
# bug that was fixed in strip_delivery.py for instmon's own detection.
case "${1:-}" in
    --install)   do_install ;;
    --uninstall) do_uninstall ;;
    --status)    do_status ;;
    --test)      do_test "${2:-}" ;;
    "")          run_check ;;
    -h|--help)   usage ;;
    *)           echo "Unknown option: $1" >&2; usage; exit 1 ;;
esac
