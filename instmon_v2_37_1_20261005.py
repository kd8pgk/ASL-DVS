#!/usr/bin/env python3

"""instmon v2.37.1 (2026-10-05) - KD8PGK Web Installer & Component Manager

Full version history: see CHANGELOG.md. This docstring intentionally
stays short now -- it used to carry the entire changelog inline (see
CHANGELOG.md's own note, and its v1.26.0 entry, for why that moved).
"""

import argparse
import base64
import collections
import fcntl
import fnmatch
import hashlib
import hmac 
import html 
import http .client 
import http .server 
import ipaddress
import json 
import os 
import py_compile 
import re
import secrets
import shlex
import shutil
import signal
import socket
import ssl
import struct
import subprocess 
import sys 
import threading 
import time 
import urllib .error 
import urllib .parse 
import urllib .request 
import tempfile 
import zipfile 
from collections import deque 
from datetime import datetime 


PORT =8990 
VERSION ="2.37.1"
DATE_STR ="2026-10-05"  # v2.37.1 Pi Zero 2 W sysmon build: Check GitHub keeps the full and the Pi02w sysmon builds apart -- both match sysmon*.py, so they were one kind and only one of them showed (or a false "same version, different file" conflict); the kind now also carries the VERSION suffix ("6.13.67-pi02w" -> pi02w), so each build gets its own row and is compared only with library copies of the same build. Previous: v2.37.0 Quiet System + Full Update: Quiet System / Restore (GitHub Updates card) pause SysMon, the Dashboard, 44helper and the watchdog timer(s) through the quiesce core with a new "quiet" scope -- never Asterisk, the bridges, Allmon3, wifimon or instmon -- share its state file (so a restart of instmon restores them, and a disk-image job and Quiet System can never overlap), auto-restore after 30 min (INSTMON_QUIET_AUTO_RESTORE_SEC), and drop a component that a later Install/Uninstall already restarted; Full Update (next to Check GitHub) reads the same GitHub listing, picks for every installed component the newest GitHub build of the same variant (file-name stem, or the VERSION suffix such as -pi02w), downloads and checks every file first with the GitHub Update checks, then pauses the web tools and, one component at a time (44helper, wifimon, Dashboard, SysMon, Watchdog), saves a library copy of the installed file, runs its --uninstall, runs the new file's --install and waits for the service and port; a failure puts the saved copy back and the component is skipped (or listed NEEDS ATTENTION if that fails too) and the run carries on; newer install scripts go to the Scripts library only, never run; Restore, then instmon last -- replaced in place by its own --install, with a transient instmon-update-guard timer that reinstalls the old copy if port 8990 is silent 90 s later; results are saved to instmon_full_update.json and the restarted instmon reports them; summary as a popup, in the log and as a banner until dismissed; while it runs every other action, upload, editor save and disk-image job answers 409. Check GitHub now also works out the Full Update list from the same listing (no extra GitHub request). Previous: v2.36.1 Login refresh: when a session expires or instmon is reinstalled/restarted, the page now reloads itself instead of popping the login box over the stale page (which mangled the text and, after login, restarted every poll timer a second time); the "Session expired" message is carried across the reload via sessionStorage and shown on the fresh login box; a once-only guard means a burst of 401s reloads once, and the boot-time login (fresh page, not logged in) never reloads, so no loop. Previous: v2.36.0 GitHub updates: Check GitHub reads the file list of kd8pgk/ASL-DVS (main) straight from GitHub -- no manifest or checksums to maintain -- shows the newest GitHub copy of each tool in its library group, Update downloads, checks (same file GitHub listed, version, shebang, syntax, --install support) and stages it in its own library folder; uninstall_asl_dvs*.sh added to Scripts with a double confirm. Previous: wifimon card now points at the wifimon v5 web dashboard (port 8991, plain HTTP, Go button); M17 Dashboard and SVX Dashboard cards removed (component, library group + upload box, library folder, home-folder sweep pattern, and the M17 branch of config install). Previous: v2.30.2 Progress audit: reader uses read1() (was a blocking read(256) => 4 s+ batches, nothing for short jobs), throttled copies report via the read-side dd (pv prints nothing when stderr is a pipe), ddrescue status is captured (it writes to stdout, which was /dev/null) and its kB unit parsed, one-decimal %, bytes done/total, elapsed, windowed time-left, stall warning


INSTALLER_SCRIPT_GLOB ="install_asl_dvs*.sh"
UNINSTALLER_SCRIPT_GLOB ="uninstall_asl_dvs*.sh"






INTERACTIVE_ONLY_SCRIPT_GLOBS =("wifi_menu*.sh","wifi-menu*.sh")


SCRIPT_TIMEOUT_SEC =int (os .environ .get ("INSTMON_SCRIPT_TIMEOUT_SEC","600"))
MAX_UPLOAD_BYTES =int (os .environ .get ("INSTMON_MAX_UPLOAD_MB","50"))*1024 *1024 
REBOOT_SHUTDOWN_DELAY_SEC =int (os .environ .get ("INSTMON_REBOOT_SHUTDOWN_DELAY_SEC","2"))


INSTALL_BIN_PATH ="/usr/local/bin/instmon.py"
SYSTEMD_SERVICE_PATH ="/etc/systemd/system/instmon.service"

SYSTEMD_SERVICE_CONTENT ="""[Unit]
Description=instmon Web Installer & Component Manager
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/instmon.py
Restart=always
RestartSec=3s
WatchdogSec=60s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


LIBRARY_DIR =os .environ .get ("INSTMON_LIBRARY_DIR","/etc/asl_dvs/instmon_library")
CONFIG_DIR =os .environ .get ("INSTMON_CONFIG_DIR","/etc/asl_dvs")
CONFIG_NAME =os .environ .get ("INSTMON_CONFIG_NAME","asl_dvs.conf")






HOME_SCAN_DIR =os .environ .get ("INSTMON_HOME_SCAN_DIR",os .path .expanduser ("~"))
HOME_SCAN_ENABLED =os .environ .get ("INSTMON_HOME_SCAN_ENABLED","1")!="0"


# ---------------------------------------------------------------------
# Root-password authentication core (replaces the old generated/env
# Basic-Auth credential pair entirely -- see v1.29.0 changelog above).
# New code below uses normal Python spacing, not this file's
# space-before-paren house style.
# ---------------------------------------------------------------------

_AUTH_ACCOUNT = "root"

def _read_shadow_hash(account):
    """Read the encrypted-password field for `account` straight out of
    /etc/shadow with plain file I/O -- no `spwd` involved, since that
    module is gone on Python 3.13+ (PEP 594). Requires root to read.
    Returns None on any failure to read/parse."""
    try:
        with open("/etc/shadow", "r") as fh:
            for line in fh:
                parts = line.rstrip("\n").split(":")
                if len(parts) >= 2 and parts[0] == account:
                    return parts[1]
    except Exception as exc:
        log_event(f"_read_shadow_hash: {exc}", "warn")
    return None

_libcrypt_handle = None  # cached ctypes.CDLL, or False if none could be loaded

def _crypt_verify(password, stored_hash):
    """crypt(3)-based hash verification via ctypes against the system's
    real libcrypt -- used instead of the stdlib `crypt` module, which is
    also gone on Python 3.13+ (PEP 594)."""
    global _libcrypt_handle
    if _libcrypt_handle is None:
        import ctypes
        import ctypes.util
        found = None
        for name in ("libcrypt.so.1", "libcrypt.so.2", "libcrypt.so",
                     ctypes.util.find_library("crypt"), "libc.so.6"):
            if not name:
                continue
            try:
                lib = ctypes.CDLL(name)
                lib.crypt.restype  = ctypes.c_char_p
                lib.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
                found = lib
                break
            except (OSError, AttributeError):
                continue
        _libcrypt_handle = found if found is not None else False
        if _libcrypt_handle is False:
            log_event("_crypt_verify: no usable libcrypt found on this system", "warn")
    if _libcrypt_handle is False:
        return False
    try:
        result = _libcrypt_handle.crypt(password.encode("utf-8", "surrogateescape"),
                                         stored_hash.encode("utf-8", "surrogateescape"))
    except Exception as exc:
        log_event(f"_crypt_verify: crypt(3) call failed: {exc}", "warn")
        return False
    if result is None:
        return False
    return hmac.compare_digest(result.decode("utf-8", "surrogateescape"), stored_hash)

def _verify_root_password(password):
    """True iff `password` is the box's current root password. Tries PAM
    first, falls back to /etc/shadow + ctypes-libcrypt. Never raises --
    any failure to check is a failed login, fails closed."""
    if not password:
        return False
    try:
        import pam as _pam_mod
        return bool(_pam_mod.pam().authenticate(_AUTH_ACCOUNT, password, service="login"))
    except ImportError:
        pass
    except Exception as exc:
        log_event(f"_verify_root_password: PAM check errored, trying shadow fallback: {exc}", "warn")
    try:
        stored = _read_shadow_hash(_AUTH_ACCOUNT)
        if not stored or stored[0] in ("!", "*"):
            return False
        return _crypt_verify(password, stored)
    except Exception as exc:
        log_event(f"_verify_root_password: shadow fallback failed: {exc}", "warn")
        return False

# ---------------------------------------------------------------------
# Independent in-memory session store. Deliberately NOT the shared
# /run/asl_dvs SSO file the dashboard/sysmon pair use -- this app's
# session is its own, with its own cookie name, and never touches
# /run/asl_dvs in any way.
# ---------------------------------------------------------------------

_SESSION_COOKIE_NAME = "instmon_session"
_SESSION_TTL_SEC = 12 * 3600  # sliding, refreshed on every authed request

_sessions = {}   # token -> expiry (float, time.time())
_sessions_lock = threading.Lock()

def _issue_session():
    token = secrets.token_hex(32)
    now = time.time()
    with _sessions_lock:
        for t in [tk for tk, exp in _sessions.items() if exp <= now]:
            _sessions.pop(t, None)
        _sessions[token] = now + _SESSION_TTL_SEC
    return token

def _check_session(token):
    if not token:
        return False
    with _sessions_lock:
        exp = _sessions.get(token)
        if exp is None or exp <= time.time():
            _sessions.pop(token, None)
            return False
        _sessions[token] = time.time() + _SESSION_TTL_SEC
        return True

def _revoke_session(token):
    with _sessions_lock:
        _sessions.pop(token, None)

def _session_cookie_header(token, max_age):
    return f"{_SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"

def _clear_session_cookie_header():
    return f"{_SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"


# ---------------------------------------------------------------------
# Disk Image & Clone (Stage 1: drive discovery only -- no write paths
# exist yet). Boot-disk resolution and attached-USB-drive listing for
# the dashboard's "Disk Image & Clone" card: backing up the Pi's own
# boot disk to a USB drive, cloning it directly onto a spare drive, and
# restoring a saved image onto a spare drive -- never onto the disk the
# Pi is currently running from. New code below uses normal Python
# spacing, not this file's space-before-paren house style -- same
# convention as the root-password auth block above.
# ---------------------------------------------------------------------

# Every external binary the Disk Image & Clone feature can shell out
# to. "required" tools are needed for Backup/Clone/Restore themselves
# (dd does the imaging, lsblk/findmnt resolve the boot disk and list
# drives, mount is used to reach a Backup destination's filesystem,
# partprobe re-reads a partition table after a Clone/Restore write and
# after losetup below). "optional" tools each gate exactly one
# checkbox and are looked up by the feature name they belong to --
# missing one of these disables that checkbox's feature, not the whole
# card. Checked with shutil.which() so a red pass/fail line can flag a
# missing tool up front in the UI, instead of only failing mid-job.
_DISKIMG_REQUIRED_TOOLS = ("dd", "lsblk", "findmnt", "mount", "umount", "partprobe")
_DISKIMG_OPTIONAL_TOOLS = {
    "losetup": "Shrink to fit",
    "blkid": "Shrink to fit",
    "e2fsck": "Shrink to fit",
    "resize2fs": "Shrink to fit",
    "dumpe2fs": "Shrink to fit",
    "parted": "Shrink to fit / Full Format",
    "openssl": "Encrypt",
    "mkfs.ext4": "Full Format (ext4)",
    "mkfs.vfat": "Full Format (FAT32)",
    "mkfs.exfat": "Full Format (exFAT)",
    # v2.26.0 Stages 1/5/6: each of these gates exactly one Backup/Clone
    # checkbox, same as every entry above -- missing the binary disables
    # that one option, not the feature it lives on.
    "fsfreeze": "Freeze filesystem during copy",
    "pv": "Throttle speed",
    "ddrescue": "Resilient clone (ddrescue)",
}


def _diskimg_check_dependencies():
    """Pass/fail dependency check for every binary the Disk Image &
    Clone feature can shell out to. Never raises."""
    missing_required = [t for t in _DISKIMG_REQUIRED_TOOLS if not shutil.which(t)]
    missing_optional = {t: feat for t, feat in _DISKIMG_OPTIONAL_TOOLS.items() if not shutil.which(t)}
    return {
        "ok": not missing_required and not missing_optional,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
    }


def _get_boot_disk():
    """Return the whole-disk device name (e.g. 'mmcblk0', 'sda') backing
    the root filesystem, or None if it can't be determined. Every
    destructive disk-image action (clone/restore) must fail closed --
    refuse to run at all -- when this returns None, since without it
    there is no way to tell the boot disk from a spare. Never raises."""
    try:
        result = subprocess.run(
            ["findmnt", "-no", "SOURCE", "/"],
            capture_output=True, text=True, timeout=5,
        )
        root_src = result.stdout.strip() if result.returncode == 0 else ""
        if not root_src:
            return None
        result2 = subprocess.run(
            ["lsblk", "-no", "PKNAME", root_src],
            capture_output=True, text=True, timeout=5,
        )
        pkname = result2.stdout.strip() if result2.returncode == 0 else ""
        return pkname or None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        log_event(f"_get_boot_disk: could not resolve boot disk: {exc}", "warn")
        return None


def _lsblk_json():
    """Whole `lsblk -J` tree (disks with nested partition children), or
    None on any failure to run/parse it. Never raises."""
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,MODEL,TRAN,TYPE,RM,MOUNTPOINT,FSTYPE"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
        log_event(f"_lsblk_json: lsblk query failed: {exc}", "warn")
        return None


def _disk_mountpoints(node):
    """Every mountpoint of `node` and its partition children, recursively
    -- a whole disk is only safe to treat as unmounted if nothing under
    it is mounted anywhere, not just the disk node itself."""
    points = []
    mp = node.get("mountpoint")
    if mp:
        points.append(mp)
    for child in node.get("children") or []:
        points.extend(_disk_mountpoints(child))
    return points


def _disk_read_only(name):
    """True if the kernel currently reports this whole-disk device as
    read-only -- covers a physically write-protect-locked SD card in a
    reader that honors the lock tab. False (not "unknown") on any read
    failure, since the write attempt itself is still the authoritative
    check; this is a pre-flight UI hint, not the enforcement point."""
    try:
        with open(f"/sys/block/{name}/ro", "r") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def _list_usb_drives():
    """Attached USB-transport whole disks (SD-card-via-USB-adapter
    readers included -- they enumerate identically to a flash drive),
    each annotated with size/model/mount state/read-only state/whether
    it's the Pi's own boot disk. Empty multi-slot-reader entries
    (SIZE=0, no card inserted) are omitted. Never raises -- any failure
    to query drives returns an empty list rather than propagating."""
    data = _lsblk_json()
    if data is None:
        return []
    boot_disk = _get_boot_disk()
    drives = []
    for node in data.get("blockdevices") or []:
        if node.get("type") != "disk":
            continue
        try:
            size = int(node.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size <= 0:
            continue
        tran = (node.get("tran") or "").lower()
        removable = str(node.get("rm")).lower() in ("1", "true")
        if tran != "usb" and not removable:
            continue
        name = node.get("name") or ""
        drives.append({
            "name": name,
            "path": node.get("path") or f"/dev/{name}",
            "size": size,
            "model": (node.get("model") or "").strip(),
            "tran": tran or None,
            "removable": removable,
            "mounted_at": _disk_mountpoints(node),
            "read_only": _disk_read_only(name),
            "is_boot_disk": bool(boot_disk) and name == boot_disk,
        })
    return drives


def fmt_bytes(n):
    """Human-readable byte size for log/error messages (server-side
    counterpart to the frontend's fmtBytes())."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _disk_size_bytes(name):
    """Whole-disk capacity in bytes for a device by lsblk NAME (a block
    device's own stat() st_size is unreliable for this -- lsblk is the
    same source of truth _list_usb_drives() already uses). None if the
    device can't be found or lsblk can't be queried."""
    data = _lsblk_json()
    if data is None:
        return None
    node = next((n for n in data.get("blockdevices") or [] if n.get("name") == name), None)
    if node is None:
        return None
    try:
        return int(node.get("size") or 0)
    except (TypeError, ValueError):
        return None


def _find_mount_or_mountable_partition(disk_node):
    """For a whole disk being used as a Backup destination (needs a
    mounted filesystem to receive a file -- unlike Clone/Restore, which
    write the raw block device directly): pick its data partition,
    preferring one that's already mounted. Returns (device_path,
    existing_mountpoint_or_None, fstype) or None if nothing on this disk
    has a recognized filesystem at all (e.g. a blank/unpartitioned
    drive)."""
    children = disk_node.get("children") or []
    candidates = children if children else [disk_node]
    best = None
    for c in candidates:
        fstype = c.get("fstype")
        if not fstype:
            continue
        mp = c.get("mountpoint")
        cand = (c.get("path") or "", mp, fstype)
        if mp:
            return cand
        if best is None:
            best = cand
    return best


_DISKIMG_MOUNT_ROOT = "/mnt/instmon-diskimg"


def _diskimg_ensure_mounted(disk_name):
    """Ensure `disk_name` (an lsblk NAME) has a mounted, writable data
    partition available for Backup to write a file onto, mounting it
    ourselves under _DISKIMG_MOUNT_ROOT if nothing is mounted yet.
    Returns (mountpoint, we_mounted_it) or (None, False) if no usable
    filesystem could be found or mounted. Never raises."""
    data = _lsblk_json()
    if data is None:
        return None, False
    node = next((n for n in data.get("blockdevices") or [] if n.get("name") == disk_name), None)
    if node is None:
        return None, False
    cand = _find_mount_or_mountable_partition(node)
    if cand is None:
        return None, False
    dev_path, existing_mp, _fstype = cand
    if existing_mp:
        return existing_mp, False
    mountpoint = os.path.join(_DISKIMG_MOUNT_ROOT, disk_name)
    try:
        os.makedirs(mountpoint, exist_ok=True)
        subprocess.run(["mount", dev_path, mountpoint], check=True, capture_output=True, timeout=15)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log_event(f"_diskimg_ensure_mounted: could not mount {dev_path} at {mountpoint}: {exc}", "err")
        return None, False
    return mountpoint, True


# --- dd job engine (Stage 2). Backup/Clone/Restore all share this --
# one disk-image job at a time, system-wide, same one-job discipline as
# _running_installs. -----------------------------------------------

_DISKIMG_BACKUP_DIRNAME = "instmon-backups"
_DD_PROGRESS_RE = re.compile(rb"(\d+)\s+bytes")

# v2.26.0 Stages 5/6: the throttled-pipeline (pv) and resilient
# (ddrescue) backends each write a completely different progress format
# to stderr than plain dd's "N bytes ..." line above -- one regex per
# backend, picked by job["progress_format"] in
# _diskimg_reader_thread_body, never assumed to match dd's.
_PV_PROGRESS_RE = re.compile(rb"([\d.]+)\s*([KMGT]?i?B)\b")
_PV_UNIT_MULTIPLIERS = {
    "B": 1,
    "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4,
    "kiB": 1024,
    "KB": 1000, "kB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "TB": 1000 ** 4,
}
# ddrescue's status block includes a "rescued: <amount> <unit>B" field --
# the actual bytes recovered so far, which is what a progress bar wants
# (as opposed to "ipos", the current read position, which can be ahead
# of what's actually been successfully copied when sectors are being
# retried).
_DDRESCUE_PROGRESS_RE = re.compile(rb"rescued:\s*([\d.]+)\s*([kKMGT]?i?B)")
# v2.30.2: ddrescue writes its whole multi-line status block (with ANSI
# cursor-up escapes) to STDOUT once a second, and prints kilobytes with a
# lowercase k ("41943 kB"). Neither was handled: stdout went to /dev/null
# and the unit regex only knew an uppercase K. The block's lines are noise
# to the job console; only real error text ("ddrescue: ...") is kept.
_ANSI_ESCAPE_RE = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]")
_DDRESCUE_STATUS_LINE_RE = re.compile(
    rb"(ipos:|opos:|non-tried:|non-trimmed:|non-scraped:|bad-sector:|rescued:|"
    rb"time since last successful read|^\s*(Copying|Trimming|Scraping|Retrying|Finished|Press Ctrl-C|GNU ddrescue))")


def _diskimg_parse_meter_bytes(amount_bytes, unit_bytes):
    """Shared byte-amount parser for the pv and ddrescue progress
    regexes above -- both report a human "<number> <unit>" pair, not a
    raw byte count the way dd's status=progress line does. Never
    raises: an amount that doesn't parse as a float is treated as no
    progress update rather than crashing the reader thread."""
    try:
        amount = float(amount_bytes)
    except ValueError:
        return None
    unit = unit_bytes.decode("ascii", "replace")
    return int(amount * _PV_UNIT_MULTIPLIERS.get(unit, 1))


_diskimg_job = None
_diskimg_job_lock = threading.Lock()

# Terminal-style feedback for the Disk Image & Clone card (v2.9.0),
# same idea as 44helper's per-step .asl3-console: a small rolling log
# of meaningful lines (command launched, real dd/openssl error text,
# phase changes, final result) -- NOT a mirror of dd's own
# once-a-second progress output, which stays in the compact
# percent/rate/ETA line the job panel already had. Capped so a very
# long-running job's console can't grow without bound.
_DISKIMG_CONSOLE_MAX_LINES = 300


def _diskimg_console_append(job_id, text):
    """Append one line to the current job's console, tagged with a
    wall-clock timestamp like the main execution log. No-op if the job
    has since ended/been replaced (job_id no longer matches) so a
    slow-to-arrive line from a superseded job never lands on the wrong
    console. Must be called with _diskimg_job_lock NOT already held by
    the caller -- it takes the lock itself."""
    ts = datetime.now().strftime("%H:%M:%S")
    with _diskimg_job_lock:
        if _diskimg_job is None or _diskimg_job["id"] != job_id:
            return
        console = _diskimg_job.setdefault("console", [])
        console.append(f"[{ts}] {text}")
        del console[:-_DISKIMG_CONSOLE_MAX_LINES]


def _diskimg_command_display(cmd):
    """Human-readable, copy-pasteable rendering of an argv list for the
    command-preview field -- shlex-quoted so it's accurate shell
    syntax, not just str(list). The bash -c pipeline case (see
    _diskimg_pipeline_command()) already carries its own fully-quoted
    script as argv[2]; showing that script directly reads far better
    than re-quoting 'bash -c <whole script as one quoted blob>'."""
    if len(cmd) == 3 and cmd[0] == "bash" and cmd[1] == "-c":
        return cmd[2]
    return " ".join(shlex.quote(a) for a in cmd)


_WIPE_BLOCK_SIZE = 4 * 1024 * 1024  # 4 MiB, matches the dd bs= used everywhere else in this feature

# v2.30.0 Quick format: how much of the start of the drive the wipe phase
# zeroes instead of the whole thing. 16 MiB covers the MBR/primary GPT,
# the usual 1 MiB partition-start gap, and any old filesystem's
# superblock/journal header sitting at the start of the old first
# partition. The tail (old backup GPT) is cleared by wipefs in
# _diskimg_partition_and_format().
_QUICK_WIPE_BYTES = 16 * 1024 * 1024


def _diskimg_format_wipe_bytes(size_bytes, quick=False):
    """Bytes the wipe phase of a Format job will zero -- the job's
    bytes_total, so the progress bar's percentage means something for a
    Quick format too. Full format: the whole drive."""
    if quick:
        return max(_WIPE_BLOCK_SIZE, min(size_bytes, _QUICK_WIPE_BYTES))
    return size_bytes


def _diskimg_wipe_command(dst, size_bytes, unit_name, quick=False):
    """argv for a whole-disk zero-wipe of `dst` (Full Format's first
    phase, v2.10.0 Stage 2) -- same systemd-run --pipe --collect
    detaching pattern as _diskimg_dd_command() below. Bounded with an
    explicit count= (rather than letting dd run from /dev/zero until
    it hits ENOSPC at the physical end of the device) so a full,
    successful wipe exits 0 like every other job phase instead of
    looking like a failure; this leaves under one block (4MiB) at the
    very tail not explicitly zeroed, which is harmless here since the
    very next phase writes a fresh GPT partition table -- including
    its backup header, which lives in that same tail region -- over
    whatever was there. Returns (argv, detached: bool).

    quick (v2.30.0): zero only the first _QUICK_WIPE_BYTES of the drive
    (old MBR/GPT and any filesystem header at the start) instead of the
    whole thing -- seconds rather than the drive's full write time. The
    rest of the old data stays on the drive, so this is NOT a secure
    erase. size_bytes is capped, so it need not be the drive's size."""
    if quick:
        count = max(1, min(size_bytes, _QUICK_WIPE_BYTES) // _WIPE_BLOCK_SIZE)
    else:
        count = max(1, size_bytes // _WIPE_BLOCK_SIZE)
    dd_cmd = ["dd", "if=/dev/zero", f"of={dst}", f"bs={_WIPE_BLOCK_SIZE}", f"count={count}", "status=progress", "conv=fsync"]
    if shutil.which("systemd-run"):
        return (
            ["systemd-run", "--quiet", "--pipe", "--collect", f"--unit={unit_name}"] + dd_cmd,
            True,
        )
    log_event("systemd-run not found -- disk-image job will run undetached "
              "and will NOT survive an instmon restart", "warn")
    return dd_cmd, False


def _diskimg_dd_command(src, dst, unit_name, best_effort=False, direct_io=False):
    """argv for the copy, wrapped in a detached `systemd-run --pipe
    --collect` transient unit when systemd-run is available, so the
    copy survives an instmon.service restart the same way
    install_service()'s self-restart fix does -- the dd process runs as
    its own unit, not a child of instmon's cgroup, while --pipe still
    forwards its stderr (status=progress output) back to this process
    for the reader thread below. Falls back to a plain, non-detached
    subprocess when systemd-run isn't on PATH (e.g. a non-systemd
    dev/test environment) -- logged, since that job would NOT survive
    an instmon restart. Returns (argv, detached: bool).

    best_effort (v2.26.0 Stage 2): adds conv=sync,noerror so a read
    error on the source is padded with nulls and skipped rather than
    aborting the whole copy -- sync is required alongside noerror, not
    optional, or a skipped block shifts every later block out of
    alignment. Only ever offered for Backup/Clone, where the source is
    this Pi's own live boot disk.

    direct_io (v2.26.0 Stage 3): adds oflag=direct so writes bypass the
    page cache instead of buffering in RAM before hitting the
    destination -- steadier write behavior on a small/shared-bus board
    like a Pi Zero 2W. Only offered for Clone for now: Clone's
    destination is always a raw block device, while Backup/Restore's
    file-based endpoint (a file on a mounted vfat/exfat/ext4 drive) has
    not been confirmed to tolerate O_DIRECT alignment."""
    conv = "fsync,sync,noerror" if best_effort else "fsync"
    dd_cmd = ["dd", f"if={src}", f"of={dst}", "bs=4M", "status=progress", f"conv={conv}"]
    if direct_io:
        dd_cmd.append("oflag=direct")
    if shutil.which("systemd-run"):
        return (
            ["systemd-run", "--quiet", "--pipe", "--collect", f"--unit={unit_name}"] + dd_cmd,
            True,
        )
    log_event("systemd-run not found -- disk-image job will run undetached "
              "and will NOT survive an instmon restart", "warn")
    return dd_cmd, False


# --- optional encryption (v2.4). Backup can encrypt its output;
# Restore can decrypt an encrypted backup on the way back out. Both are
# a dd<->openssl pipeline instead of plain dd -- see
# _diskimg_pipeline_command() below for why that pipeline never runs
# through the systemd-run --pipe --collect wrapping the plain dd path
# uses. ------------------------------------------------------------

_DISKIMG_PASS_ENV_VAR = "INSTMON_DISKIMG_PASS"
_DISKIMG_ENCRYPTED_SUFFIX = ".img.enc"
_OPENSSL_ENC_ARGS = ["-aes-256-cbc", "-pbkdf2", "-salt"]


def _diskimg_pipeline_command(mode, src, dst, best_effort=False):
    """argv for an encrypt (mode="encrypt", used by Backup) or decrypt
    (mode="decrypt", used by Restore of a .img.enc backup) pipeline:
    dd piped through, or from, `openssl enc`, with the passphrase read
    by openssl from the INSTMON_DISKIMG_PASS environment variable
    (-pass env:...) -- never appearing on openssl's own argv, this
    process's argv, or any log line. `set -o pipefail` makes a dd
    failure (e.g. a source read error) fail the whole pipeline's exit
    code too, not get silently masked by openssl succeeding on
    truncated input.

    best_effort (v2.26.0 Stage 2) only ever applies to mode="encrypt"
    (Backup is the only kind that ever combines encrypt with a live
    source disk read) -- adds conv=sync,noerror to the read-side dd so
    a source error is padded and skipped rather than aborting the
    whole pipeline, same rationale as _diskimg_dd_command()'s
    best_effort. Not offered for mode="decrypt": Restore always reads
    a backup file already on disk, not the live boot disk, so there is
    nothing to be resilient against here.

    Always returns a plain argv, never wrapped in the systemd-run
    --pipe --collect transient-unit detaching _diskimg_dd_command()
    uses for a plain copy: getting the passphrase into that unit's own
    environment would mean either putting it on systemd-run's own argv
    (--setenv=...) or relying on environment inheritance systemd-run
    does not do by default for a transient unit -- both worse than the
    job simply not surviving an instmon restart, which is the same
    tradeoff already accepted whenever systemd-run isn't available at
    all (see _diskimg_dd_command() above)."""
    openssl_common = ["openssl", "enc"] + _OPENSSL_ENC_ARGS + ["-pass", f"env:{_DISKIMG_PASS_ENV_VAR}"]
    if mode == "encrypt":
        conv = " conv=sync,noerror" if best_effort else ""
        script = (
            f"set -o pipefail; dd if={shlex.quote(src)} bs=4M status=progress{conv} | "
            + " ".join(shlex.quote(a) for a in openssl_common + ["-e", "-out", dst])
        )
    else:
        script = (
            "set -o pipefail; "
            + " ".join(shlex.quote(a) for a in openssl_common + ["-d", "-in", src])
            + f" | dd of={shlex.quote(dst)} bs=4M status=progress conv=fsync"
        )
    return ["bash", "-c", script]


# --- alternate copy backends (v2.26.0 Stages 5/6). Both are opt-in
# checkboxes on Backup/Clone/Restore alongside the plain dd path above,
# not a replacement for it -- see _diskimg_start_job for the precedence
# between encrypt/decrypt, ddrescue, throttle, and plain dd. --------

def _diskimg_throttled_dd_command(src, dst, rate_mb, unit_name, best_effort=False, direct_io=False):
    """argv for a bandwidth-limited copy: dd | pv -L <rate> | dd
    (v2.26.0 Stage 5) -- the same bash -c pipeline shape as
    _diskimg_pipeline_command()'s openssl path, for the same reason: a
    shell pipeline can't be expressed as a single argv. `set -o
    pipefail` so a read-side dd failure fails the whole pipeline's exit
    code, not just the write side.

    Progress (v2.30.2): the READ-side dd runs status=progress and pv runs
    -q. Before this, pv's own meter was the progress source, but pv only
    draws it when stderr is a terminal (it is a pipe here), so a
    throttled job reported nothing until it finished. The read-side dd
    counts bytes as the pipe accepts them, which pv's rate limit paces,
    so it runs at most one 4 MiB block ahead of what is written --
    the same dd format the plain copy path already parses.

    Always returns detached=False: unlike _diskimg_dd_command(), this
    is NOT wrapped in systemd-run --pipe --collect. Whether a bash -c
    pipeline can be wrapped the same way a plain dd argv is has not
    been tested here -- the encrypt/decrypt pipeline above avoids that
    wrapping for a specific, different reason (the passphrase's own
    environment), not because pipes as a category can't be wrapped, so
    this is left unwrapped as the conservative default pending that
    test, not a confirmed limitation. Logged by the caller, same as
    the systemd-run-not-found case elsewhere in this feature, since a
    throttled job will NOT survive an instmon restart either way right
    now."""
    in_conv = " conv=sync,noerror" if best_effort else ""
    out_flags = "status=none conv=fsync" + (" oflag=direct" if direct_io else "")
    script = (
        f"set -o pipefail; dd if={shlex.quote(src)} bs=4M status=progress{in_conv} | "
        f"pv -q -L {int(rate_mb)}m | "
        f"dd of={shlex.quote(dst)} bs=4M {out_flags}"
    )
    return ["bash", "-c", script], False


_DISKIMG_MAPFILE_SUFFIX = ".ddrescue.map"


def _diskimg_ddrescue_mapfile_path(job_id):
    """Per-job ddrescue mapfile path, alongside this feature's other
    per-job state (CONFIG_DIR) -- ddrescue requires a mapfile argument
    to run at all; instmon doesn't use it to resume an interrupted
    rescue today, it exists purely because the tool needs one, and is
    removed with the job's other cleanup once the job reaches a
    terminal state (see _diskimg_reader_thread_body)."""
    return os.path.join(CONFIG_DIR, f"instmon_diskimg_{job_id}{_DISKIMG_MAPFILE_SUFFIX}")


def _diskimg_ddrescue_command(src, dst, mapfile_path, unit_name):
    """argv for a resilient copy via GNU ddrescue instead of dd
    (v2.26.0 Stage 6) -- retries bad sectors non-destructively instead
    of dd's abort-on-error (or, with best_effort, skip-and-pad)
    behavior. -d bypasses the page cache, same rationale as
    _diskimg_dd_command()'s direct_io; -b matches the 4 MiB block size
    used everywhere else in this feature. Only ever offered for
    Backup/Clone (D-4, same restriction as best_effort/freeze): the
    source being resilient against is this Pi's own live boot disk.
    Never combined with encrypt -- ddrescue writes to its destination
    with retries and seeks, which a downstream openssl pipe consumer
    couldn't follow the way it follows dd's strictly sequential
    output; see the encrypt/ddrescue mutual-exclusion check in the
    Backup handler. Same systemd-run --pipe --collect detaching
    pattern as _diskimg_dd_command() -- see that function's docstring
    for the rationale. Returns (argv, detached: bool)."""
    ddrescue_cmd = ["ddrescue", "-d", "-b", "4MiB", src, dst, mapfile_path]
    if shutil.which("systemd-run"):
        return (
            ["systemd-run", "--quiet", "--pipe", "--collect", f"--unit={unit_name}"] + ddrescue_cmd,
            True,
        )
    log_event("systemd-run not found -- disk-image job will run undetached "
              "and will NOT survive an instmon restart", "warn")
    return ddrescue_cmd, False


def _diskimg_freeze(action):
    """(ok, message) for `fsfreeze -f /` (action="freeze") or
    `fsfreeze -u /` (action="unfreeze") (v2.26.0 Stage 1). Only ever
    called around the copy phase of an already-quiesced Backup/Clone --
    freeze right after _quiesce_services succeeds and before the copy
    starts, unfreeze before _unquiesce_services runs (see
    _diskimg_start_job and _diskimg_finish_quiesce). Freezing pauses
    new writes to the root filesystem so the raw block-level image dd
    or ddrescue takes of the boot disk is crash-consistent, without
    needing the filesystem unmounted -- it can't be, this Pi is running
    from it. Reads are not blocked by a freeze, only writes are, so
    instmon's own operation during the copy phase (console/progress
    updates are in-memory only by this point -- _quiesce_state_write
    already finished during the earlier stop phase) is unaffected.
    subprocess.run() directly, no systemd-run wrapping: this needs to
    complete synchronously before/after the copy phase, not run as its
    own detached unit. Never raises."""
    flag = "f" if action == "freeze" else "u"
    try:
        result = subprocess.run(
            ["fsfreeze", f"-{flag}", "/"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, f"fsfreeze -{flag} /: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, f"fsfreeze -{flag} / returned {result.returncode}" + (f": {detail}" if detail else "")
    return True, "Root filesystem frozen for the copy." if action == "freeze" else "Root filesystem thawed."


def _quiesce_command_preview():
    """The quiesce step as it would appear in a command preview
    (v2.19.0). Built from _quiesce_resolve_units(), the same function
    the real quiesce walks, so the preview cannot drift from what
    actually gets stopped -- the v2.9.0 rule for the dd preview,
    applied to this step too.

    Returns (display_text, unit_count). Renders as one `systemctl stop`
    line per tier rather than one big line, because the tier split IS
    the design (the watchdog has to go first or it undoes the quiesce)
    and flattening it would hide that from anyone reading the preview
    to check what the button will do."""
    units = _quiesce_resolve_units()
    if not units:
        return "# (no suite services are currently running -- nothing to stop)", 0
    tier_names = {0: "watchdog timers", 1: "suite web tools", 2: "comms"}
    lines = []
    for tier in (0, 1, 2):
        names = [u for t, _l, u in units if t == tier]
        if not names:
            continue
        lines.append(f"# {tier_names[tier]}")
        lines.append("systemctl stop " + " ".join(shlex.quote(n) for n in names))
    lines.append("sync")
    return "\n".join(lines), len(units)


def _diskimg_build_command_preview(kind, params):
    """Wrapper (v2.19.0) that prepends the quiesce step to the base
    preview when the Backup/Clone card has the quiesce box ticked. The
    restart half is deliberately not shown: it is the same list in
    reverse and printing it twice makes the preview harder to scan,
    not clearer."""
    command, note_or_error = _diskimg_build_command_preview_base(kind, params)
    if command is None or not params.get("quiesce") or kind not in ("backup", "clone"):
        return command, note_or_error
    try:
        quiesce_text, count = _quiesce_command_preview()
    except Exception as exc:
        return command, f"(Could not preview the quiesce step: {exc}) " + (note_or_error or "")
    combined = quiesce_text + "\n\n" + command
    extra = (f"{count} service(s) will be stopped first and restarted afterward -- "
             "the node is off the air for the whole job.") if count else ""
    note = (note_or_error + " " + extra).strip() if note_or_error else extra
    return combined, (note or None)


def _diskimg_build_command_preview_base(kind, params):
    """Best-effort, side-effect-free preview of the exact dd/openssl
    command a Backup/Clone/Restore action would launch for the
    options currently selected in the UI (v2.9.0) -- built from the
    very same _diskimg_dd_command()/_diskimg_pipeline_command()
    functions the real job uses, so the preview can never drift out of
    sync with what actually runs. Never mounts a drive, writes a file,
    or starts a subprocess -- only resolves things already knowable
    without side effects (attached drive list, boot disk, existing
    backup files). Returns (command_display_or_None, note_or_error);
    the note is shown as a small caveat alongside a successful
    preview, the error is shown in place of the command when one
    can't be built yet. Never raises -- always safe to call on every
    keystroke."""
    try:
        if kind == "backup":
            boot_disk = _get_boot_disk()
            if not boot_disk:
                return None, "Could not determine this Pi's boot disk yet."
            src_path = f"/dev/{boot_disk}"
            dest_device = params.get("dest_device")
            if not dest_device:
                return None, "Pick a destination drive to preview the command."
            match = next(
                (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
                None,
            )
            if match is None:
                return None, f"'{dest_device}' is not a currently attached USB drive."
            label = re.sub(r"[^A-Za-z0-9_-]+", "_", (params.get("label") or "").strip())[:40]
            encrypt = bool(params.get("encrypt"))
            best_effort = bool(params.get("best_effort"))
            backend = params.get("backend") if params.get("backend") in ("dd", "ddrescue") else "dd"
            throttle_rate_mb = params.get("throttle_rate_mb")
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            hostname = socket.gethostname()
            ext = _DISKIMG_ENCRYPTED_SUFFIX if encrypt else ".img"
            fname = f"{hostname}_{stamp}" + (f"_{label}" if label else "") + ext
            dest_display = os.path.join(f"<mount of {match['path']}>", _DISKIMG_BACKUP_DIRNAME, fname)
            # Same precedence as _diskimg_start_job: encrypt beats
            # backend/throttle (this preview never claims to combine
            # them, since the real job doesn't either).
            if encrypt:
                cmd = _diskimg_pipeline_command("encrypt", src_path, dest_display, best_effort=best_effort)
            elif backend == "ddrescue":
                cmd, _detached = _diskimg_ddrescue_command(
                    src_path, dest_display, "<job-id>.ddrescue.map", "instmon-diskimg-<job>",
                )
            elif throttle_rate_mb:
                cmd, _detached = _diskimg_throttled_dd_command(
                    src_path, dest_display, throttle_rate_mb, "instmon-diskimg-<job>", best_effort=best_effort,
                )
            else:
                cmd, _detached = _diskimg_dd_command(src_path, dest_display, "instmon-diskimg-<job>", best_effort=best_effort)
            return (
                _diskimg_command_display(cmd),
                "Exact filename/timestamp and mount path are finalized when the job actually starts.",
            )

        if kind == "clone":
            boot_disk = _get_boot_disk()
            if not boot_disk:
                return None, "Could not determine this Pi's boot disk yet."
            src_path = f"/dev/{boot_disk}"
            dest_device = params.get("dest_device")
            if not dest_device:
                return None, "Pick a destination drive to preview the command."
            match = next(
                (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
                None,
            )
            if match is None:
                return None, f"'{dest_device}' is not a currently attached USB drive."
            best_effort = bool(params.get("best_effort"))
            direct_io = bool(params.get("direct_io"))
            backend = params.get("backend") if params.get("backend") in ("dd", "ddrescue") else "dd"
            throttle_rate_mb = params.get("throttle_rate_mb")
            if backend == "ddrescue":
                cmd, _detached = _diskimg_ddrescue_command(
                    src_path, match["path"], "<job-id>.ddrescue.map", "instmon-diskimg-<job>",
                )
            elif throttle_rate_mb:
                cmd, _detached = _diskimg_throttled_dd_command(
                    src_path, match["path"], throttle_rate_mb, "instmon-diskimg-<job>",
                    best_effort=best_effort, direct_io=direct_io,
                )
            else:
                cmd, _detached = _diskimg_dd_command(
                    src_path, match["path"], "instmon-diskimg-<job>", best_effort=best_effort, direct_io=direct_io,
                )
            return _diskimg_command_display(cmd), None

        if kind == "format":
            dest_device = params.get("dest_device")
            if not dest_device:
                return None, "Pick a destination drive to preview the command."
            match = next(
                (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
                None,
            )
            if match is None:
                return None, f"'{dest_device}' is not a currently attached USB drive."
            if match["is_boot_disk"]:
                return None, "Refusing to use the boot disk as a format target."
            quick = bool(params.get("quick"))
            cmd, _detached = _diskimg_wipe_command(match["path"], match["size"], "instmon-diskimg-<job>", quick=quick)
            if quick:
                return (
                    _diskimg_command_display(cmd),
                    "Quick format: this only zeroes the first 16 MiB -- wipefs, a fresh GPT and mkfs run right after, and aren't shown as a second live command line. Not a secure erase.",
                )
            return (
                _diskimg_command_display(cmd),
                "This is the wipe step only -- partitioning (fresh GPT) and mkfs run right after, and aren't shown as a second live command line.",
            )

        if kind == "restore":
            name = params.get("name")
            drive = params.get("drive")
            dest_device = params.get("dest_device")
            if not name:
                return None, "Pick a backup to preview the command."
            backup = next(
                (b for b in _diskimg_list_backups() if b["name"] == name and (drive is None or b["drive"] == drive)),
                None,
            )
            if backup is None:
                return None, "That backup could not be found on any currently attached drive."
            if not dest_device:
                return None, "Pick a destination drive to preview the command."
            match = next(
                (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
                None,
            )
            if match is None:
                return None, f"'{dest_device}' is not a currently attached USB drive."
            throttle_rate_mb = params.get("throttle_rate_mb")
            if backup.get("encrypted"):
                cmd = _diskimg_pipeline_command("decrypt", backup["path"], match["path"])
            elif throttle_rate_mb:
                cmd, _detached = _diskimg_throttled_dd_command(
                    backup["path"], match["path"], throttle_rate_mb, "instmon-diskimg-<job>",
                )
            else:
                cmd, _detached = _diskimg_dd_command(backup["path"], match["path"], "instmon-diskimg-<job>")
            return _diskimg_command_display(cmd), None

        return None, f"Unknown kind '{kind}'."
    except Exception as exc:
        log_event(f"_diskimg_build_command_preview({kind}): {exc}", "warn")
        return None, "Could not build a preview right now."


def _diskimg_job_snapshot():
    """A JSON-safe copy of the current job (drops the live Popen handle),
    or None if no job has ever run this process lifetime."""
    with _diskimg_job_lock:
        if _diskimg_job is None:
            return None
        job = dict(_diskimg_job)
        job.pop("proc", None)
        return job


def _diskimg_reader_thread(job_id):
    """Thin outermost wrapper around the real reader body (v2.18.0).

    The ONLY reason this wrapper exists is the quiesce finally block.
    _diskimg_reader_thread_body() has half a dozen `return` statements
    scattered through it -- four of them inside `with
    _diskimg_job_lock:` blocks that fire when the job id no longer
    matches -- and every one of them must still restore the node's
    services. Wrapping the body in a separate function instead of
    threading a try/finally through its existing nesting makes that
    structurally impossible to get wrong: there is exactly one way out
    of the body, and it passes through this finally.

    Note this covers the ordinary ends only -- success, dd failure,
    cancel, verify mismatch, an unexpected exception. A SIGKILL, an OOM
    kill or a power cut runs no finally at all; those are the startup
    sweep's job (_quiesce_startup_sweep, v2.17.0)."""
    quiesced = False
    frozen = False
    with _diskimg_job_lock:
        if _diskimg_job is not None and _diskimg_job["id"] == job_id:
            quiesced = bool(_diskimg_job.get("quiesced"))
            frozen = bool(_diskimg_job.get("frozen"))
    try:
        _diskimg_reader_thread_body(job_id)
    finally:
        if quiesced:
            try:
                _diskimg_finish_quiesce(job_id, frozen)
            except Exception as exc:  # never let this thread die silently quiesced
                try:
                    log_event(f"Unquiesce after job {job_id} errored: {exc} -- "
                              "services may still be stopped; a reboot is recommended.", "err")
                except Exception:
                    pass


def _diskimg_finish_quiesce(job_id, frozen=False):
    """Restore services at the end of a quiesced job and fold the
    outcome into the job's own message. The job's terminal state has
    already been decided by the body and is never overwritten here: a
    backup that copied and verified cleanly is still a successful
    backup even if a service failed to come back. That failure becomes
    a warning appended to the message (D-6), not a failed job.

    frozen (v2.26.0 Stage 1): thaw the root filesystem BEFORE
    restarting services below, not after -- a frozen fs blocks writes,
    and several of the services being restarted here will want to
    write (logs, state files, sockets) as soon as they come up. A thaw
    failure is folded into the message the same D-6 way an unquiesce
    failure is (a warning on an otherwise-successful job), since the
    copy itself is already safely on disk either way."""
    if frozen:
        with _diskimg_job_lock:
            if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                _diskimg_job["phase"] = "thawing"
        _diskimg_console_append(job_id, "Thawing root filesystem...")
        thaw_ok, thaw_message = _diskimg_freeze("unfreeze")
        _diskimg_console_append(job_id, thaw_message)
        if not thaw_ok:
            log_event(f"Disk-image job {job_id}: {thaw_message} -- a reboot is recommended.", "err")
            with _diskimg_job_lock:
                if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                    _diskimg_job["message"] = (_diskimg_job.get("message") or "").rstrip()
                    _diskimg_job["message"] += ("  " if _diskimg_job["message"] else "") + f"WARNING: {thaw_message} A reboot is recommended."

    with _diskimg_job_lock:
        if _diskimg_job is not None and _diskimg_job["id"] == job_id:
            _diskimg_job["phase"] = "unquiescing"
    _diskimg_console_append(job_id, "Restoring node services...")

    ok, results = _unquiesce_services(console_job_id=job_id)
    summary = _quiesce_format_results(results)

    with _diskimg_job_lock:
        if _diskimg_job is None or _diskimg_job["id"] != job_id:
            return
        _diskimg_job["phase"] = "done"
        _diskimg_job["quiesce_results"] = [
            {"label": l, "unit": u, "ok": k, "state": s} for l, u, k, s in results
        ]
        _diskimg_job["quiesce_restore_ok"] = ok
        if summary:
            _diskimg_job["message"] = (_diskimg_job.get("message") or "").rstrip()
            _diskimg_job["message"] += ("  " if _diskimg_job["message"] else "") + summary
    log_event(f"Disk-image job {job_id}: {summary}", "ok" if ok else "err")


def _diskimg_reader_thread_body(job_id):
    with _diskimg_job_lock:
        job = _diskimg_job
        if job is None or job["id"] != job_id:
            return
        proc = job["proc"]
        # v2.26.0 Stages 5/6: which regex/parser this job's backend
        # writes to stderr -- picked once here rather than re-read from
        # the job dict on every chunk, since it never changes mid-job.
        progress_format = job.get("progress_format", "dd")
    buf = b""
    last_nonprogress_line = ""
    # v2.30.2: read1() returns as soon as ANY bytes are available. The old
    # proc.stderr.read(256) on Popen's default BufferedReader blocks until
    # a full 256 bytes have piled up -- about four dd progress lines, so
    # the bar moved in 4 s+ steps at best, and a job that finished inside
    # that window (a Quick format) never reported anything at all.
    stream = proc.stdout
    read_some = getattr(stream, "read1", None) or (lambda n: stream.read(n))
    try:
        while True:
            chunk = read_some(4096)
            if not chunk:
                break
            buf += chunk
            # dd's status=progress (and pv's meter, and ddrescue's
            # status block) all write \r-terminated updates, not \n --
            # split on either so a plain readline() (which only breaks
            # on \n) never sits on data that already arrived.
            parts = re.split(rb"[\r\n]", buf)
            buf = parts[-1]
            for piece in parts[:-1]:
                if progress_format == "ddrescue":
                    piece = _ANSI_ESCAPE_RE.sub(b"", piece)
                if not piece.strip():
                    continue
                if progress_format == "pv":
                    m = _PV_PROGRESS_RE.search(piece)
                    parsed = _diskimg_parse_meter_bytes(m.group(1), m.group(2)) if m else None
                elif progress_format == "ddrescue":
                    m = _DDRESCUE_PROGRESS_RE.search(piece)
                    parsed = _diskimg_parse_meter_bytes(m.group(1), m.group(2)) if m else None
                else:
                    m = _DD_PROGRESS_RE.search(piece)
                    parsed = int(m.group(1)) if m else None
                if parsed is not None:
                    with _diskimg_job_lock:
                        if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                            _diskimg_job["bytes_done"] = parsed
                elif progress_format == "ddrescue" and _DDRESCUE_STATUS_LINE_RE.search(piece):
                    continue  # part of the status block, not an error
                else:
                    # Not a progress line -- most likely dd's own error
                    # text ("No space left on device", a permission
                    # error, a bad destination, ...) or systemd-run's own
                    # complaint if the unit itself couldn't start. Kept
                    # so a failure message says WHY, not just an exit
                    # code -- an "audit the error messages" hardening
                    # pass item. Also echoed to the console (v2.9.0) --
                    # unlike the once-a-second progress line, real error
                    # text like this is rare enough that showing every
                    # line doesn't flood the box.
                    try:
                        last_nonprogress_line = piece.decode("utf-8", "replace").strip()
                        if last_nonprogress_line:
                            _diskimg_console_append(job_id, last_nonprogress_line)
                    except Exception:
                        pass
    except Exception as exc:
        log_event(f"Disk-image progress reader error: {exc}", "warn")
    returncode = proc.wait()
    copy_ok = False
    with _diskimg_job_lock:
        if _diskimg_job is None or _diskimg_job["id"] != job_id:
            return
        job = _diskimg_job
        job["proc"] = None
        if job.get("cancelled"):
            job["finished"] = time.time()
            job["state"] = "cancelled"
            job["message"] = "Cancelled -- the destination is left partial and unusable."
        elif returncode != 0:
            job["finished"] = time.time()
            job["state"] = "failed"
            tool_label = job.get("backend") or "dd"
            job["message"] = (
                f"{tool_label} exited with code {returncode}: {last_nonprogress_line}"
                if last_nonprogress_line else f"{tool_label} exited with code {returncode}."
            )
        else:
            if job["bytes_total"]:
                job["bytes_done"] = job["bytes_total"]
            copy_ok = True
        kind, state, message = job["kind"], job["state"], job["message"]
        src, dest, bytes_total = job["source"], job["dest"], job["bytes_total"]
        verify_requested, shrink_requested = job.get("verify_requested"), job.get("shrink_requested")
        verify_algo = job.get("verify_algo") or "sha256"
        fs_type = job.get("fs_type")
        quick = bool(job.get("quick"))
        mapfile_path = job.get("mapfile_path")

    # v2.26.0 Stage 6: clean up the ddrescue mapfile (if this job used
    # one) now that the copy has reached a terminal outcome one way or
    # another -- best-effort, same FileNotFoundError-tolerant shape as
    # _quiesce_state_clear().
    if mapfile_path:
        try:
            os.remove(mapfile_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log_event(f"Disk-image {job_id}: could not remove ddrescue mapfile {mapfile_path}: {exc}", "warn")

    if not copy_ok:
        if kind == "backup":
            # v2.30.0: a Backup whose copy was cancelled or failed leaves a
            # truncated .img (or .img.enc) in instmon-backups/, which
            # _diskimg_list_backups() would then offer to Restore. Remove it.
            outcome = _diskimg_remove_partial_backup(dest)
            if outcome == "deleted":
                if state == "cancelled":
                    message = "Cancelled -- the partial backup file was deleted."
                else:
                    message = f"{message} The partial backup file was deleted."
            elif outcome:
                message = f"{message} Could not delete the partial backup file ({outcome}) -- delete it manually before restoring."
            if outcome:
                with _diskimg_job_lock:
                    if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                        _diskimg_job["message"] = message
        level = "warn" if state == "cancelled" else "err"
        log_event(f"Disk-image {kind} {state}: {message}", level)
        _diskimg_console_append(job_id, f"{state}: {message}")
        return

    # Copy succeeded. Run any requested post-copy steps -- verify, then
    # (backup only) shrink -- before finalizing to a terminal state.
    # Each step keeps the job "running" with "phase" set accordingly so
    # the UI's job panel stays live throughout, potentially long as
    # both steps can be.
    final_state, final_message = "done", "Completed successfully."

    if verify_requested:
        with _diskimg_job_lock:
            if _diskimg_job is None or _diskimg_job["id"] != job_id:
                return
            _diskimg_job["phase"] = "verifying"
        log_event(f"Disk-image {kind} copy done -- verifying {src} == {dest} ...", "info")
        _diskimg_console_append(job_id, f"Copy complete -- verifying (re-reading and comparing {verify_algo} checksums)...")
        result, verify_message = _diskimg_verify_copy(job_id, src, dest, bytes_total, algo=verify_algo)
        if result == "mismatch":
            final_state, final_message = "failed", verify_message
        elif result == "cancelled":
            final_state, final_message = "cancelled", verify_message
        elif result == "error":
            final_message = f"Completed successfully. Verification could not run: {verify_message}"
        else:
            final_message = f"Completed successfully. {verify_message}"
        _diskimg_console_append(job_id, verify_message)

    if final_state == "done" and kind == "backup" and shrink_requested:
        with _diskimg_job_lock:
            if _diskimg_job is None or _diskimg_job["id"] != job_id:
                return
            _diskimg_job["phase"] = "shrinking"
        log_event(f"Disk-image backup copy/verify done -- shrinking {dest} ...", "info")
        _diskimg_console_append(job_id, "Copy complete -- shrinking image to its minimum size...")
        shrink_ok, shrink_message, new_size = _diskimg_shrink_image(dest)
        final_message += f" {shrink_message}" if shrink_ok else f" Shrink skipped: {shrink_message}"
        _diskimg_console_append(job_id, shrink_message)
        if shrink_ok:
            with _diskimg_job_lock:
                if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                    _diskimg_job["bytes_total"] = new_size
                    _diskimg_job["bytes_done"] = new_size

    if final_state == "done" and kind == "format":
        # v2.30.0: a cancel that lands in the gap between the wipe exiting
        # and this point must still be honoured. Once the phase flips to
        # "formatting" below, _diskimg_cancel_job() refuses instead.
        cancelled_before_format = False
        with _diskimg_job_lock:
            if _diskimg_job is None or _diskimg_job["id"] != job_id:
                return
            if _diskimg_job.get("cancelled"):
                cancelled_before_format = True
            else:
                _diskimg_job["phase"] = "formatting"
        if cancelled_before_format:
            final_state = "cancelled"
            final_message = "Cancelled before partitioning -- the drive was wiped but has no new partition table or filesystem."
        else:
            wipe_word = "Quick wipe" if quick else "Wipe"
            log_event(f"Disk-image format: {wipe_word.lower()} of {dest} done -- partitioning and formatting as {fs_type} ...", "info")
            _diskimg_console_append(job_id, f"{wipe_word} complete -- writing a fresh GPT partition table and formatting as {fs_type}...")
            fmt_ok, fmt_message = _diskimg_partition_and_format(dest, fs_type, quick=quick)
            if not fmt_ok:
                final_state, final_message = "failed", fmt_message
            else:
                final_message = f"Completed successfully. {fmt_message}"
            _diskimg_console_append(job_id, fmt_message)

    with _diskimg_job_lock:
        if _diskimg_job is None or _diskimg_job["id"] != job_id:
            return
        job = _diskimg_job
        job["phase"] = "done"
        job["finished"] = time.time()
        job["state"] = final_state
        job["message"] = final_message
        kind, state, message, dest = job["kind"], job["state"], job["message"], job["dest"]

    level = "ok" if state == "done" else ("warn" if state == "cancelled" else "err")
    log_event(f"Disk-image {kind} {state}: {message}", level)
    _diskimg_console_append(job_id, f"{state}: {message}")
    if state == "done" and kind in ("clone", "restore", "format"):
        # A raw disk-to-disk write leaves the kernel's view of the
        # destination's partition table stale (it read the old one, if
        # any, at attach time) -- reread it so the new partitions show
        # up without needing to unplug/replug the drive. Best-effort: a
        # failure here doesn't change the copy's own success.
        try:
            subprocess.run(["partprobe", dest], capture_output=True, timeout=15)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            log_event(f"partprobe {dest} failed (copy itself still succeeded): {exc}", "warn")


def _diskimg_start_job(
    kind, source_desc, dest_desc, src_path, dst_path, bytes_total,
    shrink_requested=False, verify_requested=False,
    encrypt_passphrase=None, decrypt_passphrase=None,
    fs_type=None, quiesce_requested=False,
    best_effort_requested=False, direct_io_requested=False,
    verify_algo="sha256", backend="dd", throttle_rate_mb=None,
    freeze_requested=False, quick_requested=False,
):
    """Launch a dd-based (or, with a passphrase, dd<->openssl pipeline)
    disk-image job. Refuses to start a second job while one is already
    running -- there is still only ever one disk-image job
    system-wide, across all four cards (Format/Backup/Clone/Restore).
    shrink_requested only ever applies to kind="backup"; verify_requested
    applies to backup/clone/restore, but is mutually exclusive with
    either passphrase argument (checked by callers, not here -- see
    handle_diskimg_backup_start()/handle_diskimg_restore_start() for
    why) and is never set for kind="format" (there's nothing
    meaningful to verify a zero-wipe against). encrypt_passphrase only
    ever applies to kind="backup", decrypt_passphrase only to
    kind="restore"; at most one of the two is ever set. fs_type only
    applies to kind="format" (v2.10.0 Stage 2) -- consumed by the
    post-copy partition+mkfs step in _diskimg_reader_thread, not by
    the dd command itself. The passphrase itself is used only to build
    this one subprocess's environment below and is never written into
    the job dict, a log line, or any argv -- its only representation
    on disk or in a process listing is inside that one subprocess's
    own environment (visible only to root, same as this whole app
    already requires to touch disk devices at all).

    v2.26.0 additions, all normalized (not trusted from the caller) the
    same way quiesce_requested already is just below -- each is a
    no-op outside the kind/combination it's meaningful for, rather
    than an error, since the UI is expected to just not offer them
    outside that context:
    best_effort_requested/freeze_requested -- backup/clone only (D-4:
        same "source is the live boot disk" restriction as quiesce).
        freeze_requested additionally requires quiesce_requested --
        it's offered in the UI as a sub-option of Pause node services.
    direct_io_requested -- clone only (Backup/Restore's file-based
        endpoint hasn't been confirmed to tolerate O_DIRECT).
    backend="ddrescue" -- backup/clone only, and mutually exclusive
        with best_effort/direct_io (ddrescue is its own resilience
        strategy) and with encrypt (checked by the caller, same as
        the existing encrypt-vs-shrink/verify checks).
    throttle_rate_mb -- backup/clone/restore, but never combined with
        encrypt/decrypt (a 3-stage pipe) or backend="ddrescue"
        (ddrescue doesn't stream sequentially the way a pipe needs).
    verify_algo -- "sha256" (default) or "blake2b"; irrelevant unless
        verify_requested is also set.
    quick_requested (v2.30.0) -- format only: the wipe phase zeroes just
        the start of the drive (bytes_total should then be
        _diskimg_format_wipe_bytes(size, True)), and the partition+mkfs
        step also runs wipefs. Not a secure erase.

    Returns (ok, job_id_or_error_message)."""
    global _diskimg_job

    # quiesce (v2.18.0) only ever applies where the SOURCE is the live
    # boot disk, i.e. backup and clone (D-4). Restore reads a file and
    # writes a spare drive; format touches a spare drive only -- taking
    # the node off the air for either would buy nothing.
    quiesce_requested = bool(quiesce_requested) and kind in ("backup", "clone")
    quiesce_stopped_public = []
    quiesce_console = []
    frozen_ok = False

    backend = backend if backend in ("dd", "ddrescue") and kind in ("backup", "clone") else "dd"
    best_effort_requested = bool(best_effort_requested) and kind in ("backup", "clone") and backend != "ddrescue"
    direct_io_requested = bool(direct_io_requested) and kind == "clone" and backend != "ddrescue"
    freeze_requested = bool(freeze_requested) and quiesce_requested and kind in ("backup", "clone")
    quick_requested = bool(quick_requested) and kind == "format"
    verify_algo = verify_algo if verify_algo in _VERIFY_HASHERS else "sha256"
    throttle_requested = (
        bool(throttle_rate_mb) and kind in ("backup", "clone", "restore")
        and backend != "ddrescue" and not (encrypt_passphrase or decrypt_passphrase)
    )
    # v2.30.2: throttled copies now report through the read-side dd, so
    # only ddrescue needs its own parser.
    progress_format = "ddrescue" if backend == "ddrescue" else "dd"

    job_id = secrets.token_hex(8)
    unit_name = f"instmon-diskimg-{job_id}"

    if quiesce_requested:
        # Publish a placeholder job FIRST, so the UI's 5s poll can see
        # the quiescing phase while it happens -- stopping Asterisk and
        # the bridges is not instant, and a job that appears only once
        # dd starts would leave the panel blank for that whole window.
        with _diskimg_job_lock:
            if _diskimg_job is not None and _diskimg_job.get("state") == "running":
                return False, "A disk-image job is already running -- wait for it to finish or cancel it first."
            _diskimg_job = {
                "id": job_id, "kind": kind, "state": "running", "phase": "quiescing",
                "source": source_desc, "dest": dest_desc,
                "bytes_done": 0, "bytes_total": bytes_total,
                "started": time.time(), "finished": None, "message": "",
                "proc": None, "unit_name": None, "cancelled": False,
                "shrink_requested": False, "verify_requested": False,
                "verify_bytes_done": 0, "encrypted": False, "fs_type": None,
                "command_display": "",
                "quiesced": False, "quiesce_stopped": [], "quiesce_results": None,
                "quiesce_restore_ok": None,
                "frozen": False, "backend": "dd",
                "best_effort_requested": False, "direct_io_requested": False,
                "verify_algo": None, "throttle_rate_mb": None,
                "progress_format": "dd", "mapfile_path": None,
                "quick": False,
                "console": [
                    f"[{datetime.now().strftime('%H:%M:%S')}] Preparing {kind}: {source_desc} -> {dest_desc}",
                ],
            }

        # NOTE: the job lock is deliberately NOT held across the two
        # calls below. Stopping services can take tens of seconds, and
        # _diskimg_job_snapshot() (the UI's 5s poll) needs that lock --
        # holding it here would freeze the job panel during exactly the
        # phase the user most wants to watch.
        ok, reason = _quiesce_check_package_locks()
        if not ok:
            _diskimg_console_append(job_id, f"Pre-flight failed: {reason}")
            with _diskimg_job_lock:
                if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                    _diskimg_job = None
            log_event(f"Disk-image {kind} not started: {reason}", "warn")
            return False, reason

        ok, stopped, message = _quiesce_services(job_id, console_job_id=job_id)
        if not ok:
            # _quiesce_services has already restored anything it
            # stopped before failing (D-5) -- nothing is left down.
            with _diskimg_job_lock:
                if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                    _diskimg_job = None
            log_event(f"Disk-image {kind} not started: {message}", "err")
            return False, message

        quiesce_stopped_public = [{"tier": t, "label": l, "unit": u} for t, l, u in stopped]
        with _diskimg_job_lock:
            if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                _diskimg_job["quiesced"] = True
                _diskimg_job["quiesce_stopped"] = quiesce_stopped_public
                # Keep the quiescing transcript -- the dict built below
                # replaces this one entirely, and losing the record of
                # what was stopped would gut the console exactly when a
                # node fails to come back.
                quiesce_console = list(_diskimg_job.get("console") or [])

        # v2.26.0 Stage 1: freeze AFTER services are stopped (so nothing
        # still-running has a write in flight when the freeze lands)
        # and BEFORE the copy starts. A freeze failure does NOT abort
        # the job -- the image stays crash-consistent without it, same
        # as before this feature existed, so this fails open with a
        # console warning rather than throwing away a job that already
        # paid the cost of quiescing.
        if freeze_requested:
            freeze_ok, freeze_message = _diskimg_freeze("freeze")
            _diskimg_console_append(job_id, freeze_message)
            if freeze_ok:
                frozen_ok = True
            else:
                log_event(f"Disk-image {kind}: fsfreeze -f / failed, continuing without it: {freeze_message}", "warn")
            # Re-capture the transcript now that the freeze line landed
            # on it -- same reason quiesce_stopped_public was captured
            # above: the dict built below replaces this placeholder
            # wholesale, so anything not carried forward here is lost.
            with _diskimg_job_lock:
                if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                    quiesce_console = list(_diskimg_job.get("console") or [])

    with _diskimg_job_lock:
        if not quiesce_requested and _diskimg_job is not None and _diskimg_job.get("state") == "running":
            return False, "A disk-image job is already running -- wait for it to finish or cancel it first."
        passphrase = encrypt_passphrase or decrypt_passphrase
        env = None
        mapfile_path = None
        if kind == "format":
            cmd, detached = _diskimg_wipe_command(dst_path, bytes_total, unit_name, quick=quick_requested)
        elif encrypt_passphrase:
            cmd, detached = _diskimg_pipeline_command("encrypt", src_path, dst_path, best_effort=best_effort_requested), False
        elif decrypt_passphrase:
            cmd, detached = _diskimg_pipeline_command("decrypt", src_path, dst_path), False
        elif backend == "ddrescue":
            mapfile_path = _diskimg_ddrescue_mapfile_path(job_id)
            cmd, detached = _diskimg_ddrescue_command(src_path, dst_path, mapfile_path, unit_name)
        elif throttle_requested:
            cmd, detached = _diskimg_throttled_dd_command(
                src_path, dst_path, throttle_rate_mb, unit_name,
                best_effort=best_effort_requested, direct_io=direct_io_requested,
            )
            log_event(f"Disk-image {kind}: bandwidth-throttled copy runs undetached (pv pipeline) -- "
                      "will NOT survive an instmon restart", "warn")
        else:
            cmd, detached = _diskimg_dd_command(
                src_path, dst_path, unit_name,
                best_effort=best_effort_requested, direct_io=direct_io_requested,
            )
        if passphrase:
            env = dict(os.environ)
            env[_DISKIMG_PASS_ENV_VAR] = passphrase
        command_display = _diskimg_command_display(cmd)
        popen_error = None
        proc = None
        try:
            # start_new_session=True (v2.26.0 Stage 5): puts the child
            # in its own process group regardless of backend. Matters
            # for the two bash -c pipeline forms (encrypt/decrypt above,
            # throttled-pv below) -- a pipeline's stages are separate
            # processes under the same shell, and terminate()-ing just
            # the shell's own PID would leave them running orphaned. No
            # effect on a detached systemd-run job (that unit already
            # manages its own process group) or on a plain single dd.
            # v2.30.2: stdout is merged into the same pipe the reader
            # already parses (stderr=STDOUT, reader reads proc.stdout).
            # It used to be /dev/null, which silently discarded ddrescue's
            # whole progress display -- ddrescue writes it to stdout. dd,
            # pv and openssl write nothing to stdout in these commands.
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        except OSError as exc:
            # Do NOT return from inside the lock here: if we quiesced,
            # the services still have to come back, and
            # _unquiesce_services -> _diskimg_console_append takes this
            # same non-reentrant lock. Record it and handle it below.
            popen_error = f"Could not start {cmd[0]}: {exc}"
            if quiesce_requested and _diskimg_job is not None and _diskimg_job["id"] == job_id:
                _diskimg_job = None
        finally:
            # Drop this function's own reference to the passphrase (and
            # the env dict holding it) as soon as it's no longer
            # needed -- Popen() has already either read it into the
            # child's environment or failed to start.
            passphrase = None
            env = None
        if popen_error is None:
            _diskimg_job = {
                "id": job_id,
                "kind": kind,
                "state": "running",
                "source": source_desc,
                "dest": dest_desc,
                "bytes_done": 0,
                "bytes_total": bytes_total,
                "started": time.time(),
                "finished": None,
                "message": "",
                "proc": proc,
                "unit_name": unit_name if detached else None,
                "cancelled": False,
                "phase": "copying",
                "shrink_requested": bool(shrink_requested) and kind == "backup",
                "verify_requested": bool(verify_requested) and kind != "format",
                "verify_bytes_done": 0,
                "encrypted": bool(encrypt_passphrase or decrypt_passphrase),
                "fs_type": fs_type if kind == "format" else None,
                "quick": quick_requested,
                "command_display": command_display,
                # Carried forward from the quiescing placeholder above,
                # since this dict replaces it wholesale.
                "quiesced": bool(quiesce_requested),
                "quiesce_stopped": quiesce_stopped_public,
                "quiesce_results": None,
                "quiesce_restore_ok": None,
                # v2.26.0 additions -- see _diskimg_start_job's docstring
                # for what each is restricted to.
                "frozen": frozen_ok,
                "backend": backend,
                "best_effort_requested": best_effort_requested,
                "direct_io_requested": direct_io_requested,
                "verify_algo": verify_algo if (bool(verify_requested) and kind != "format") else None,
                "throttle_rate_mb": throttle_rate_mb if throttle_requested else None,
                "progress_format": progress_format,
                "mapfile_path": mapfile_path,
                "console": quiesce_console + [
                    f"[{datetime.now().strftime('%H:%M:%S')}] Starting {kind}: {source_desc} -> {dest_desc}",
                    f"[{datetime.now().strftime('%H:%M:%S')}] $ {command_display}",
                ],
            }

    if popen_error is not None:
        # Outside the job lock, so the unquiesce path may safely take it.
        if quiesce_requested:
            log_event(f"Disk-image {kind} failed to start after quiescing -- restoring services", "err")
            restore_ok, results = _unquiesce_services()
            summary = _quiesce_format_results(results)
            if summary:
                popen_error += f"  Services restored: {summary}"
            if not restore_ok:
                popen_error += "  A reboot is recommended."
        return False, popen_error

    threading.Thread(target=_diskimg_reader_thread, args=(job_id,), daemon=True).start()
    log_event(f"Disk-image {kind} started: {source_desc} -> {dest_desc}", "info")
    return True, job_id


def _diskimg_cancel_job():
    """Cancel whichever disk-image job is currently running, however it
    was launched -- stop the transient systemd unit if it was detached,
    else terminate() the direct child. Returns (ok, message)."""
    with _diskimg_job_lock:
        job = _diskimg_job
        if job is None or job.get("state") != "running":
            return False, "No disk-image job is currently running."
        if job.get("cancelled"):
            # v2.30.1: a stop is already in flight (the job is winding down
            # -- deleting a partial backup, or waiting on verify to notice
            # the flag). A second click, or a second browser tab, must not
            # re-send SIGTERM / systemctl stop.
            return True, "Stop already requested -- waiting for the job to wind down."
        if job.get("phase") == "quiescing":
            # Services are being stopped right now. There is no dd to
            # terminate yet, and interrupting mid-sequence would leave
            # the node half down with nothing tracking it. The sequence
            # is short and self-limiting (each stop is bounded by
            # QUIESCE_STOP_TIMEOUT_SEC), and if it fails it restores
            # itself -- so wait it out and cancel the copy instead.
            return False, "Node services are still being stopped -- this finishes shortly. Cancel once the copy has started."
        if job.get("phase") == "unquiescing":
            return False, "The job has finished and services are being restarted -- this finishes on its own shortly."
        if job.get("phase") == "thawing":
            # v2.26.0 Stage 1: same situation as "unquiescing" below --
            # the copy has already finished, thaw is a single quick
            # syscall with nothing to terminate(), and unquiescing
            # follows it automatically either way.
            return False, "The job has finished and the filesystem is being thawed -- this finishes on its own shortly."
        if job.get("phase") == "shrinking":
            # The copy is already done and on disk -- shrinking runs a
            # short, synchronous sequence of tool calls (e2fsck,
            # resize2fs, parted) with nothing to terminate() and no
            # transient unit of its own, so there's no way to interrupt
            # it safely mid-step without risking the partition table.
            # It finishes on its own shortly either way.
            return False, "The backup copy is already complete and is now being shrunk -- this finishes on its own shortly and can't be cancelled mid-step."
        if job.get("phase") == "formatting":
            # v2.30.0: partition + mkfs run synchronously inside the reader
            # thread with no process handle and nothing that polls the
            # cancel flag. Setting the flag here used to be silently
            # ignored (the job still ended "done"), so refuse honestly,
            # same as shrinking.
            return False, "The drive has been wiped and is now being partitioned and formatted -- this finishes on its own shortly and cannot be stopped mid-step."
        job["cancelled"] = True
        proc, unit_name, phase = job["proc"], job["unit_name"], job.get("phase")
        cancel_kind = job.get("kind")
    if phase == "verifying":
        # _diskimg_verify_copy() itself polls the "cancelled" flag just
        # set above between chunks and will stop on its own within one
        # chunk -- there's no subprocess to terminate() for this phase,
        # and the copy already on disk is unaffected either way.
        return True, "Cancel requested -- verification will stop shortly. The copy on disk is unaffected."
    try:
        if unit_name:
            subprocess.run(["systemctl", "stop", f"{unit_name}.service"], capture_output=True, timeout=10)
        elif proc is not None:
            # v2.26.0 Stage 5: kill the whole process group, not just
            # proc's own PID -- a bash -c pipeline (encrypt/decrypt
            # above, throttled-pv) forks additional processes that
            # start_new_session=True (see the Popen call above) put in
            # this same group. Falls back to plain terminate() if the
            # group kill can't be sent (process already gone, no
            # permission, etc.) rather than raising.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
    except Exception as exc:
        log_event(f"Disk-image cancel: {exc}", "warn")
    if cancel_kind == "backup":
        return True, "Cancel requested -- the partial backup file will be deleted."
    return True, "Cancel requested -- the destination will be left partial."


def _diskimg_remove_partial_backup(path):
    """v2.30.0: delete the truncated output file of a Backup whose copy
    was cancelled or failed, so it cannot show up in Restore's list.
    Deliberately narrow: only a regular (non-symlink) *.img / *.img.enc
    file sitting directly inside an instmon-backups/ directory -- never
    an arbitrary path. Returns "deleted", "" (nothing there / refused),
    or a short error string for an OSError."""
    try:
        if os.path.basename(os.path.dirname(path)) != _DISKIMG_BACKUP_DIRNAME:
            return ""
        if not (path.endswith(".img") or path.endswith(".img.enc")):
            return ""
        if os.path.islink(path) or not os.path.isfile(path):
            return ""
        os.remove(path)
        return "deleted"
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return str(exc)


def _diskimg_reset_job(kind):
    """v2.30.0: the Reset button's server half. Marks the finished job
    dismissed (rather than clearing _diskimg_job) so GET /api/diskimg/job
    stops returning it -- the panel stays empty across page reloads and
    other browsers -- while everything that reads the raw job, notably
    _diskimg_schedule_watch_job(), is untouched. Only dismisses a job of
    the card's own kind; anything else is a no-op success so the card's
    form can still reset. Returns (ok, message)."""
    with _diskimg_job_lock:
        job = _diskimg_job
        if job is None or job.get("dismissed") or job.get("kind") != kind:
            return True, "Card reset."
        if job.get("state") == "running":
            return False, "A disk-image job is still running -- stop it or wait for it to finish first."
        if job.get("quiesced") and job.get("phase") != "done":
            return False, "Node services are still being restarted -- try again in a moment."
        job["dismissed"] = True
    return True, "Card reset."


def _diskimg_list_backups():
    """Every *.img or *.img.enc (v2.4: an openssl-encrypted backup --
    see _diskimg_pipeline_command()) under instmon-backups/ on every
    currently attached and mounted USB drive, newest first -- not just
    the drive Backup last wrote to, since Restore (Stage 4) needs to
    see images that might live on a different drive than whichever is
    plugged in now."""
    results = []
    for d in _list_usb_drives():
        mountpoints = d.get("mounted_at") or []
        if not mountpoints:
            continue
        backup_dir = os.path.join(mountpoints[0], _DISKIMG_BACKUP_DIRNAME)
        if not os.path.isdir(backup_dir):
            continue
        try:
            names = os.listdir(backup_dir)
        except OSError:
            continue
        for name in names:
            encrypted = name.endswith(_DISKIMG_ENCRYPTED_SUFFIX)
            if not (encrypted or name.endswith(".img")):
                continue
            full = os.path.join(backup_dir, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            results.append({
                "name": name, "path": full, "drive": d["path"],
                "size": st.st_size, "mtime": st.st_mtime, "encrypted": encrypted,
            })
    results.sort(key=lambda e: e["mtime"], reverse=True)
    return results


# --- integrity verification (v2.2). Optional post-copy step, available
# on Backup, Clone, and Restore alike: stream both sides of a completed
# copy and confirm they're byte-for-byte identical via sha256 (or,
# v2.26.0 Stage 4, blake2b) rather than trusting dd's exit code alone --
# dd returning 0 says the write syscalls succeeded, not that a flaky
# USB reader/cable or a failing destination drive didn't silently
# corrupt something along the way. --

_VERIFY_CHUNK_SIZE = 4 * 1024 * 1024
_VERIFY_HASHERS = {"sha256": hashlib.sha256, "blake2b": hashlib.blake2b}


def _diskimg_verify_copy(job_id, src_path, dst_path, expected_bytes, algo="sha256"):
    """Stream exactly expected_bytes from src_path and dst_path in
    lockstep (bounding the read is what makes this safe to use for
    Clone/Restore too, where the destination's own true device size can
    be larger than what was actually written), hashing each side and
    comparing at the end. Checks for a cancel request on the job
    between chunks so a slow verify on a large image can still be
    interrupted -- unlike dd, there's no subprocess to terminate() here,
    so this loop is the only thing that can act on a cancel during this
    phase. Returns (result, message) where result is one of "ok",
    "mismatch" (confirmed data difference -- treated as a real failure
    by the caller), "cancelled", or "error" (verification itself could
    not complete, e.g. a read error -- distinct from a confirmed
    mismatch, and not itself treated as the job having failed).

    algo (v2.26.0 Stage 4): "sha256" (default) or "blake2b" -- both
    stdlib hashlib, both C-backed, so this is not a stdlib-only
    exception; blake2b is offered as a faster option since verify's
    real cost at this feature's 4 MiB chunk size is the double
    sequential disk read, not hash CPU, so the win is real but modest.
    An unrecognized algo falls back to sha256 rather than raising."""
    hasher_factory = _VERIFY_HASHERS.get(algo, hashlib.sha256)
    try:
        src_hash = hasher_factory()
        dst_hash = hasher_factory()
        remaining = expected_bytes
        with open(src_path, "rb") as sf, open(dst_path, "rb") as df:
            while remaining > 0:
                with _diskimg_job_lock:
                    if _diskimg_job is None or _diskimg_job["id"] != job_id:
                        return "cancelled", "Job no longer active."
                    if _diskimg_job.get("cancelled"):
                        return "cancelled", "Verification cancelled -- the copy on disk is unaffected."
                chunk_size = min(_VERIFY_CHUNK_SIZE, remaining)
                s_chunk = sf.read(chunk_size)
                d_chunk = df.read(chunk_size)
                # A short read (fewer bytes than asked for, on either
                # side) this far from expected_bytes means that side's
                # actual content is shorter than the copy was supposed
                # to be -- a real problem, but a different one than a
                # confirmed byte mismatch, so it's kept distinct.
                if len(s_chunk) < chunk_size or len(d_chunk) < chunk_size:
                    return "error", "Source or destination ended earlier than expected during verification."
                src_hash.update(s_chunk)
                dst_hash.update(d_chunk)
                remaining -= len(s_chunk)
                with _diskimg_job_lock:
                    if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                        _diskimg_job["verify_bytes_done"] = expected_bytes - remaining
    except OSError as exc:
        return "error", f"Verification could not run: {exc}"
    if src_hash.hexdigest() != dst_hash.hexdigest():
        return "mismatch", (
            f"CHECKSUM MISMATCH -- the destination does not match the source ({algo} differs). "
            "The destination may be corrupt."
        )
    return "ok", f"Verified -- {algo} matches ({src_hash.hexdigest()[:12]}...)."


# --- shrink-to-fit (v2.1). Optional post-Backup step: shrink the last
# partition's filesystem to its minimum size and truncate the .img file
# to match, PiShrink-style. Only ever runs after a Backup has already
# completed successfully -- never touches Clone or Restore. ------------

_SHRINK_REQUIRED_TOOLS = ("losetup", "partprobe", "blkid", "e2fsck", "resize2fs", "dumpe2fs", "parted")


def _diskimg_shrink_image(image_path):
    """Best-effort shrink of a just-completed backup .img: resize2fs -M
    the last partition's filesystem down to its minimum, shrink that
    partition's table entry to match with parted, then truncate the
    file to the new end of the partition table. Refuses cleanly --
    leaving the original file completely untouched -- for any layout
    other than "last partition is ext2/3/4", or if a required tool is
    missing, or if any step fails; this is meant for the plain
    boot(FAT)+root(ext4) layout instmon's own Backup produces, not
    arbitrary images. The file is truncated only as the very last step,
    after every earlier step has already succeeded and the loop device
    has been detached, so a failure partway through can never leave a
    still-good backup corrupted or truncated. Returns (ok, message,
    new_size_or_None)."""
    for tool in _SHRINK_REQUIRED_TOOLS:
        if not shutil.which(tool):
            return False, f"'{tool}' is not installed", None

    loop_dev = None
    try:
        try:
            result = subprocess.run(
                ["losetup", "-fP", "--show", image_path],
                capture_output=True, text=True, timeout=20, check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            return False, f"losetup failed: {exc}", None
        loop_dev = result.stdout.strip()
        if not loop_dev:
            return False, "losetup returned no loop device", None

        # losetup -fP alone does not reliably create partition device
        # nodes for the newly-attached loop device -- partprobe is
        # required. Its stderr can carry a harmless "udevadm: not
        # found" warning where no udev is running; that is not itself
        # a failure, so it is discarded rather than checked.
        subprocess.run(["partprobe", loop_dev], capture_output=True, timeout=20)
        time.sleep(0.2)

        try:
            lsblk_result = subprocess.run(
                ["lsblk", "-J", "-b", "-o", "NAME,PATH,START,SIZE,TYPE", loop_dev],
                capture_output=True, text=True, timeout=10, check=True,
            )
            tree = json.loads(lsblk_result.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
            return False, f"could not enumerate partitions: {exc}", None
        devices = tree.get("blockdevices") or []
        parts = (devices[0].get("children") if devices else None) or []
        if not parts:
            return False, "no partitions found on the image", None
        last = parts[-1]
        part_path, start_sector = last.get("path"), last.get("start")
        if not part_path or start_sector is None:
            return False, "could not read the last partition's start sector", None
        part_number = len(parts)

        # lsblk's own FSTYPE column depends on udev database population
        # and comes back null in a plain-kernel/no-udev environment --
        # blkid reads the filesystem superblock directly instead, and
        # is reliable regardless.
        fstype = subprocess.run(
            ["blkid", "-o", "value", "-s", "TYPE", part_path],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if fstype not in ("ext2", "ext3", "ext4"):
            return False, f"last partition is '{fstype or 'unknown'}', not ext2/3/4 (only that family is resizable here)", None

        # e2fsck -f -y is required before resize2fs will touch the
        # filesystem, and also catches a corrupt filesystem before it's
        # shrunk further. Exit code 1 ("errors corrected, filesystem
        # now clean") is e2fsck's own documented non-fatal outcome, not
        # a reason to refuse.
        fsck = subprocess.run(["e2fsck", "-f", "-y", part_path], capture_output=True, text=True, timeout=300)
        if fsck.returncode not in (0, 1):
            return False, f"e2fsck -f -y exited {fsck.returncode} -- refusing to shrink a filesystem that may still be inconsistent", None

        resize = subprocess.run(["resize2fs", "-M", part_path], capture_output=True, text=True, timeout=300)
        if resize.returncode != 0:
            return False, f"resize2fs -M failed: {resize.stderr.strip()}", None

        dump = subprocess.run(["dumpe2fs", "-h", part_path], capture_output=True, text=True, timeout=15)
        block_count = block_size = None
        for line in dump.stdout.splitlines():
            if line.startswith("Block count:"):
                block_count = int(line.split(":", 1)[1].strip())
            elif line.startswith("Block size:"):
                block_size = int(line.split(":", 1)[1].strip())
        if not block_count or not block_size:
            return False, "could not read the shrunk filesystem's new size from dumpe2fs", None

        sector_size = 512
        new_fs_bytes = block_count * block_size
        new_fs_bytes -= new_fs_bytes % sector_size  # never round up past what resize2fs actually produced
        size_sectors = new_fs_bytes // sector_size
        end_sector = start_sector + size_sectors - 1

        # `parted -s`/`--script` alone prints an unanswered "Shrinking a
        # partition can cause data loss, are you sure?" prompt and does
        # NOT apply the resize (confirmed by direct testing) --
        # --pretend-input-tty plus a piped "Yes\n" is the only technique
        # found that actually applies it non-interactively.
        parted_proc = subprocess.run(
            ["parted", "---pretend-input-tty", loop_dev, "unit", "s", "resizepart", str(part_number), f"{end_sector}s"],
            input="Yes\n", capture_output=True, text=True, timeout=30,
        )
        if parted_proc.returncode != 0:
            return False, f"parted resizepart failed: {(parted_proc.stderr or parted_proc.stdout).strip()}", None

        new_image_size = (end_sector + 1) * sector_size
    finally:
        if loop_dev:
            subprocess.run(["losetup", "-d", loop_dev], capture_output=True, timeout=15)

    # Truncate only now -- every earlier step already succeeded and the
    # loop device is detached, so shrinking the file can't confuse a
    # still-attached loop device's view of it.
    try:
        with open(image_path, "r+b") as f:
            f.truncate(new_image_size)
    except OSError as exc:
        return False, f"resize succeeded but truncating the file failed: {exc}", None

    return True, f"Shrunk to {fmt_bytes(new_image_size)}.", new_image_size


# --- Full Format (v2.10.0 Stage 2): wipe (dd, handled by the same job
# engine as Backup/Clone/Restore) then partition+mkfs -- the latter is
# a short synchronous post-copy step, same shape as Backup's existing
# shrink phase above. -------------------------------------------------

_DISKIMG_FORMAT_FS_TOOLS = {
    "ext4": "mkfs.ext4",
    "fat32": "mkfs.vfat",
    "exfat": "mkfs.exfat",
}


def _diskimg_partition_and_format(dest, fs_type, quick=False):
    """Wipe-then-format's post-copy step: write a fresh GPT label with
    a single whole-disk partition onto `dest` (already zero-wiped by
    the job's dd phase), then mkfs it as fs_type
    ("ext4"/"fat32"/"exfat"). Mirrors _diskimg_shrink_image()'s own
    pattern of partprobe + lsblk -J to find the resulting partition's
    real device path, rather than guessing a naming convention (sdX1
    vs mmcblkXp1 vs nvmeXnYp1) by string concatenation. Returns (ok,
    message). Never raises.

    quick (v2.30.0): the job's dd phase only zeroed the start of the
    drive, so also run wipefs -a on the whole drive (clears a stale
    backup GPT at the tail) and on the new partition (clears signatures
    a previous filesystem left in the same spot) before mkfs. Best
    effort: the head zero and mkfs -F already cover the common case, so
    a missing or failing wipefs is logged, not fatal."""
    def _wipefs(target):
        if not quick or not shutil.which("wipefs"):
            return
        try:
            wipe_proc = subprocess.run(
                ["wipefs", "-a", target], capture_output=True, text=True, timeout=30,
            )
            if wipe_proc.returncode != 0:
                log_event(f"Quick format: wipefs -a {target} failed (continuing): "
                          f"{(wipe_proc.stderr or wipe_proc.stdout).strip()}", "warn")
        except (subprocess.TimeoutExpired, OSError) as exc:
            log_event(f"Quick format: wipefs -a {target} failed (continuing): {exc}", "warn")

    mkfs_tool = _DISKIMG_FORMAT_FS_TOOLS.get(fs_type)
    if mkfs_tool is None:
        return False, f"Unknown filesystem type '{fs_type}'"
    for tool in ("parted", "partprobe", "lsblk", mkfs_tool):
        if not shutil.which(tool):
            return False, f"'{tool}' is not installed"

    _wipefs(dest)

    try:
        parted_proc = subprocess.run(
            ["parted", "-s", dest, "mklabel", "gpt", "mkpart", "primary", "0%", "100%"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"parted failed: {exc}"
    if parted_proc.returncode != 0:
        return False, f"parted failed: {(parted_proc.stderr or parted_proc.stdout).strip()}"

    try:
        subprocess.run(["partprobe", dest], capture_output=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        pass
    time.sleep(0.2)

    try:
        lsblk_result = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,PATH,TYPE", dest],
            capture_output=True, text=True, timeout=10, check=True,
        )
        tree = json.loads(lsblk_result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
        return False, f"Partition table written, but could not enumerate the new partition: {exc}"
    devices = tree.get("blockdevices") or []
    parts = (devices[0].get("children") if devices else None) or []
    if not parts:
        return False, "Partition table written, but no partition was found afterward."
    part_path = parts[0].get("path")
    if not part_path:
        return False, "Partition table written, but the new partition has no device path."

    _wipefs(part_path)

    mkfs_cmd = {
        "ext4": [mkfs_tool, "-F", part_path],
        "fat32": [mkfs_tool, "-F", "32", part_path],
        "exfat": [mkfs_tool, part_path],
    }[fs_type]
    try:
        mkfs_proc = subprocess.run(mkfs_cmd, capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"{mkfs_tool} failed: {exc}"
    if mkfs_proc.returncode != 0:
        return False, f"{mkfs_tool} failed: {(mkfs_proc.stderr or mkfs_proc.stdout).strip()}"
    return True, f"Partitioned (GPT) and formatted {part_path} as {fs_type}." + (" (Quick format.)" if quick else "")


# --- scheduled/automatic backups (v2.3). A background thread (started
# from run(), so it only runs when instmon is actually serving -- never
# during unit/smoke tests, which call these functions directly instead)
# wakes once a minute and, if enabled and due, starts a Backup job the
# same way handle_diskimg_backup_start() does, then prunes older
# backups on that drive down to a configured retention count. -------

_DISKIMG_SCHEDULE_PATH = os.path.join(CONFIG_DIR, "instmon_diskimg_schedule.json")
_diskimg_schedule_lock = threading.Lock()

_DISKIMG_SCHEDULE_DEFAULTS = {
    "enabled": False,
    "interval_hours": 24,
    "dest_device": "",
    "retention": 5,
    "shrink": False,
    "verify": False,
    # v2.25.0 (quiesce Stage 6). Default OFF, and stays off unless
    # someone deliberately ticks it: an unattended quiesce takes the
    # node off the air at 03:00 with nobody watching, which is a
    # materially bigger commitment than ticking the same box on a
    # manual backup you are sitting in front of.
    "quiesce": False,
    "label": "auto",
    "last_run_at": None,
    "last_run_status": None,
    "last_run_message": None,
    "last_skip_at": None,
    "last_skip_message": None,
    "last_quiesce_restore_ok": None,
}


def _diskimg_schedule_load():
    """Current schedule config, merged over the defaults above so an
    older config file (or a hand-edited/partial one) never crashes this
    -- any key it doesn't recognize is dropped, any key it's missing
    keeps its default. Never raises."""
    cfg = dict(_DISKIMG_SCHEDULE_DEFAULTS)
    with _diskimg_schedule_lock:
        try:
            with open(_DISKIMG_SCHEDULE_PATH, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            if isinstance(on_disk, dict):
                cfg.update({k: v for k, v in on_disk.items() if k in cfg})
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as exc:
            log_event(f"Could not read disk-image schedule config, using defaults: {exc}", "warn")
    return cfg


def _diskimg_schedule_save(cfg):
    with _diskimg_schedule_lock:
        try:
            compare_before_write(_DISKIMG_SCHEDULE_PATH, json.dumps(cfg, indent=2).encode("utf-8"))
        except OSError as exc:
            log_event(f"Could not save disk-image schedule config: {exc}", "err")


def _diskimg_schedule_prune(dest_drive_path, retention):
    """Keep only the newest `retention` backups on dest_drive_path,
    deleting older ones -- prunes every backup on that drive, not just
    ones this schedule itself created, since retention is a per-drive
    setting the user configures ("keep the newest N backups on this
    drive"). Best-effort: a delete failure is logged, not raised, since
    the backup that was just made succeeding is what matters most."""
    try:
        retention = max(1, int(retention))
    except (TypeError, ValueError):
        retention = 5
    on_drive = sorted(
        (b for b in _diskimg_list_backups() if b["drive"] == dest_drive_path),
        key=lambda b: b["mtime"], reverse=True,
    )
    for stale in on_drive[retention:]:
        try:
            os.remove(stale["path"])
            log_event(f"Scheduled backup retention: deleted old backup {stale['name']}", "info")
        except OSError as exc:
            log_event(f"Scheduled backup retention: could not delete {stale['name']}: {exc}", "warn")


def _diskimg_schedule_watch_job(job_id, dest_drive_path):
    """Runs in its own thread for the lifetime of one scheduled Backup
    job: waits for it to leave "running", records the result into the
    schedule config (so the UI has something to show and so
    last_run_at anchors the next interval), and prunes old backups on
    success. Deliberately reloads the config fresh rather than reusing
    whatever was passed to _diskimg_schedule_tick() -- the user may have
    changed settings (e.g. retention) while this job was still running."""
    restore_ok = None
    while True:
        with _diskimg_job_lock:
            job = _diskimg_job
            if job is None or job["id"] != job_id:
                return  # job slot reused/cleared -- nothing left to record
            state, message = job["state"], job["message"]
            phase, quiesced = job.get("phase"), job.get("quiesced")
            restore_ok = job.get("quiesce_restore_ok")
        # v2.25.0: a quiesced job reaches its terminal STATE before the
        # finally block has finished restarting services -- the restart
        # outcome is appended to the message afterwards. Waiting for the
        # phase to settle too is what keeps "Allmon3 never came back"
        # out of the gap between those two moments and in the schedule
        # card, which is the only place anyone will see it at 03:00.
        if state != "running" and not (quiesced and phase != "done"):
            break
        time.sleep(2)
    cfg = _diskimg_schedule_load()
    cfg["last_run_at"] = time.time()
    cfg["last_run_status"] = state
    cfg["last_run_message"] = message
    cfg["last_quiesce_restore_ok"] = restore_ok
    cfg["last_skip_at"] = None
    cfg["last_skip_message"] = None
    _diskimg_schedule_save(cfg)
    level = "ok" if state == "done" else "warn"
    if restore_ok is False:
        level = "err"
    log_event(f"Scheduled backup finished: {state} -- {message}", level)
    if restore_ok is False:
        log_event("Scheduled backup: NODE SERVICES DID NOT ALL RESTART -- a reboot is recommended.", "err")
    if state == "done":
        _diskimg_schedule_prune(dest_drive_path, cfg.get("retention"))


def _diskimg_schedule_tick():
    """Called once a minute by _diskimg_scheduler_loop(). If enabled and
    due, starts a Backup job identical in shape to what
    handle_diskimg_backup_start() would start for a manual click, with
    the same validation -- any check that would reject a manual Backup
    (boot disk unresolved, destination absent/unusable/undersized, no
    free space) instead skips this tick and records why, so the UI can
    explain a schedule that hasn't been running rather than looking
    like it's silently doing nothing. A skip does NOT count as a run --
    it doesn't touch last_run_at, so the next tick tries again (with
    logging throttled to once per distinct reason, not once a minute)
    rather than waiting out a full interval for a merely-unplugged
    drive."""
    cfg = _diskimg_schedule_load()
    if not cfg.get("enabled"):
        return
    try:
        interval_sec = max(0.1, float(cfg.get("interval_hours") or 24)) * 3600
    except (TypeError, ValueError):
        interval_sec = 24 * 3600
    last_run_at = cfg.get("last_run_at")
    if last_run_at is not None and (time.time() - last_run_at) < interval_sec:
        return  # not due yet

    def skip(reason):
        if cfg.get("last_skip_message") != reason:
            log_event(f"Scheduled backup not started: {reason}", "warn")
        cfg["last_skip_at"] = time.time()
        cfg["last_skip_message"] = reason
        _diskimg_schedule_save(cfg)

    with _diskimg_job_lock:
        job_running = _diskimg_job is not None and _diskimg_job.get("state") == "running"
    if job_running:
        skip("A disk-image job (manual or scheduled) is already running.")
        return

    boot_disk = _get_boot_disk()
    if not boot_disk:
        skip("Could not determine this Pi's boot disk.")
        return
    src_path = f"/dev/{boot_disk}"

    dest_device = cfg.get("dest_device")
    if not dest_device:
        skip("No destination drive configured.")
        return
    match = next(
        (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
        None,
    )
    if match is None:
        skip(f"Configured destination drive '{dest_device}' is not currently attached.")
        return
    if match["is_boot_disk"]:
        skip(f"Configured destination drive '{dest_device}' is this Pi's boot disk.")
        return
    if match["read_only"]:
        skip(f"Configured destination drive '{dest_device}' is write-protected.")
        return

    src_size = _disk_size_bytes(boot_disk)
    if not src_size:
        skip("Could not determine the boot disk's size.")
        return
    if match["size"] < src_size:
        skip(f"Configured destination drive '{dest_device}' is smaller than the boot disk.")
        return

    mountpoint, _we_mounted = _diskimg_ensure_mounted(match["name"])
    if mountpoint is None:
        skip(f"Could not find or mount a writable filesystem on {match['path']}.")
        return
    try:
        free = shutil.disk_usage(mountpoint).free
    except OSError as exc:
        skip(f"Could not check free space on {mountpoint}: {exc}")
        return
    if free < src_size:
        skip(f"Not enough free space on {match['path']} ({fmt_bytes(free)} free, need {fmt_bytes(src_size)}).")
        return

    backup_dir = os.path.join(mountpoint, _DISKIMG_BACKUP_DIRNAME)
    try:
        os.makedirs(backup_dir, exist_ok=True)
    except OSError as exc:
        skip(f"Could not create {backup_dir}: {exc}")
        return

    label = re.sub(r"[^A-Za-z0-9_-]+", "_", (cfg.get("label") or "").strip())[:40]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    hostname = socket.gethostname()
    fname = f"{hostname}_{stamp}" + (f"_{label}" if label else "") + ".img"
    dest_path = os.path.join(backup_dir, fname)

    quiesce = bool(cfg.get("quiesce"))
    if quiesce:
        # Checked here as well as inside _diskimg_start_job so an
        # apt/dpkg run becomes a throttled SKIP -- the tick retries in a
        # minute rather than burning the whole interval. A manual click
        # gets an error instead, because a person is there to read it.
        locks_ok, lock_reason = _quiesce_check_package_locks()
        if not locks_ok:
            skip(lock_reason)
            return

    subprocess.run(["sync"], capture_output=True, timeout=30)
    ok, result = _diskimg_start_job(
        "backup", src_path, dest_path, src_path, dest_path, src_size,
        shrink_requested=bool(cfg.get("shrink")), verify_requested=bool(cfg.get("verify")),
        quiesce_requested=quiesce,
    )
    if not ok:
        skip(result)
        return

    cfg["last_skip_at"] = None
    cfg["last_skip_message"] = None
    _diskimg_schedule_save(cfg)
    log_event(f"Scheduled backup started: {src_path} -> {dest_path}", "info")
    threading.Thread(target=_diskimg_schedule_watch_job, args=(result, match["path"]), daemon=True).start()


def _diskimg_scheduler_loop():
    while True:
        try:
            _diskimg_schedule_tick()
        except Exception as exc:
            log_event(f"Disk-image scheduler tick error: {exc}", "err")
        time.sleep(60)


LIB_SUBDIRS ={
"dashboard":os .path .join (LIBRARY_DIR ,"dashboard"),
"sysmon":os .path .join (LIBRARY_DIR ,"sysmon"),
"wifimon":os .path .join (LIBRARY_DIR ,"wifimon"),
"44helper":os .path .join (LIBRARY_DIR ,"44helper"),
"watchdog":os .path .join (LIBRARY_DIR ,"watchdog"),
"instmon":os .path .join (LIBRARY_DIR ,"instmon"),
"scripts":os .path .join (LIBRARY_DIR ,"scripts"),
"config":os .path .join (LIBRARY_DIR ,"config"),
}


ALLOWED_EXT ={
"dashboard":(".py",),
"sysmon":(".py",),
"wifimon":(".py",),
"44helper":(".py",),
"watchdog":(".sh",),
"instmon":(".py",),
"scripts":(".sh",),
"config":(".conf",),
}


COMPONENTS =[
{
"name":"Dashboard",
"service":"asl_dvs_dashboard",
"port":8989 ,


"install_link":"/usr/local/bin/asl_dvs_dashboard.py",
"category":"dashboard",
},
{
"name":"SysMon",
"service":"sysmon",
"port":9999 ,
"install_link":"/usr/local/bin/sysmon.py",
"category":"sysmon",
},
{
"name":"wifimon",
"service":"wifimon",
"port":8991 ,
"install_link":"/usr/local/bin/wifimon.py",
"category":"wifimon",
},
{
"name":"44helper",
"service":"44helper",
"port":9997 ,
"install_link":"/opt/44helper/asl_dvs_m17_44helper.py",
"category":"44helper",
},
{
"name":"Watchdog",










"service":"asl_dvs_watchdog.timer",
"port":None ,
"install_link":"/usr/local/bin/asl_dvs_watchdog.sh",
"category":"watchdog",
},
{
"name":"instmon",
"service":"instmon",
"port":PORT ,
"install_link":INSTALL_BIN_PATH ,
"category":"instmon",
},
]




INSTALLABLE_CATEGORIES ={c ["category"]for c in COMPONENTS }










HOME_SCAN_PATTERN_MAP =[
("watchdog",["asl_dvs_watchdog*.sh"]),
("dashboard",["asl_dvs_dashboard*.py"]),
("sysmon",["sysmon*.py","asl_dvs_sysmon*.py","asl_dvs_m17_sysmon*.py","sysmon_svx*.py"]),
("wifimon",["wifimon*.py"]),
("44helper",["asl_dvs_m17_44helper*.py","44helper*.py"]),
("instmon",["instmon*.py"]),
("config",["asl_dvs*.conf","sysmon*.conf","wifimon*.conf"]),
("scripts",["install_asl_dvs*.sh","uninstall_asl_dvs*.sh","wifi_menu*.sh","wifi-menu*.sh","asl_dvs*.sh"]),
]










COMMS_RESTART_SERVICES =[
("Asterisk","asterisk.service"),
("Analog_Bridge","analog_bridge.service"),
("MMDVM_Bridge","mmdvm_bridge.service"),
("STFU","stfu.service"),
("Allmon3","allmon3.service"),
]






COMMS_RESTART_PAUSE_SEC =3 


LOG_MAX_LINES =500 
_log =deque (maxlen =LOG_MAX_LINES )
_log_lock =threading .Lock ()
_log_seq =0 


_running_scripts =set ()
_running_scripts_lock =threading .Lock ()


_running_installs =set ()
_running_installs_lock =threading .Lock ()

_LOG_CONTROL_CHARS_RE =re .compile (r'[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]')

_auth_failures ={}
_auth_failures_lock =threading .Lock ()
AUTH_MAX_FAILURES =5 
AUTH_LOCKOUT_BASE_SEC =5 
AUTH_LOCKOUT_MAX_SEC =300 


def _auth_lockout_remaining (client_ip ):
    with _auth_failures_lock :
        rec =_auth_failures .get (client_ip )
        if not rec :
            return 0 
        return max (0 ,rec ["locked_until"]-time .time ())


def _record_auth_failure (client_ip ):
    with _auth_failures_lock :
        rec =_auth_failures .setdefault (client_ip ,{"fails":0 ,"locked_until":0 })
        rec ["fails"]+=1 
        if rec ["fails"]>=AUTH_MAX_FAILURES :
            backoff =min (
            AUTH_LOCKOUT_BASE_SEC *(2 **(rec ["fails"]-AUTH_MAX_FAILURES )),
            AUTH_LOCKOUT_MAX_SEC ,
            )
            rec ["locked_until"]=time .time ()+backoff 
            log_event (
            f"Auth: {client_ip } locked out for {backoff }s after {rec ['fails']} failed attempts",
            "warn",
            )


def _record_auth_success (client_ip ):
    with _auth_failures_lock :
        _auth_failures .pop (client_ip ,None )


def log_event (message ,level ="info"):
    global _log_seq 
    message =_LOG_CONTROL_CHARS_RE .sub (" ",str (message ))
    with _log_lock :
        _log_seq +=1 
        _log .append ({
        "id":_log_seq ,
        "ts":datetime .now ().strftime ("%Y-%m-%d %H:%M:%S"),
        "level":level ,
        "msg":message ,
        })


def ensure_dirs ():
    for path in LIB_SUBDIRS .values ():
        os .makedirs (path ,exist_ok =True )


def safe_join (base_dir ,filename ):
    base_real =os .path .realpath (base_dir )
    candidate =os .path .realpath (os .path .join (base_dir ,os .path .basename (filename )))
    if candidate ==base_real or not candidate .startswith (base_real +os .sep ):
        return None 
    return candidate 


def _file_sha256_uncached (path ):
    if not os .path .isfile (path ):
        return None 
    h =hashlib .sha256 ()
    with open (path ,"rb")as f :
        for chunk in iter (lambda :f .read (65536 ),b""):
            h .update (chunk )
    return h .hexdigest ()


def _category_for_home_file (name ):
    lname =name .lower ()
    for category ,globs in HOME_SCAN_PATTERN_MAP :
        if any (fnmatch .fnmatch (lname ,g .lower ())for g in globs ):
            return category 
    return None 


def scan_home_for_new_code ():
    moved =[]
    if not HOME_SCAN_ENABLED :
        return moved 

    ensure_dirs ()
    try :
        names =os .listdir (HOME_SCAN_DIR )
    except OSError as exc :
        log_event (f"Home-dir scan skipped ({HOME_SCAN_DIR }): {exc }","warn")
        return moved 

    for name in sorted (names ):
        full =os .path .join (HOME_SCAN_DIR ,name )
        if not os .path .isfile (full )or os .path .islink (full ):
            continue 

        category =_category_for_home_file (name )
        if category is None :
            continue 

        ext =os .path .splitext (name )[1 ].lower ()
        if ext not in ALLOWED_EXT .get (category ,()):
            continue 

        dest_dir =LIB_SUBDIRS [category ]
        dest =os .path .join (dest_dir ,name )

        if os .path .exists (dest ):
            if _file_sha256_uncached (dest )==_file_sha256_uncached (full ):
                continue 
            base ,ext2 =os .path .splitext (name )
            dest =os .path .join (dest_dir ,f"{base }__homescan_{int (time .time ())}{ext2 }")

        try :
            os .makedirs (dest_dir ,exist_ok =True )
            shutil .move (full ,dest )
        except OSError as exc :
            log_event (f"Home-dir scan: failed to move {name }: {exc }","err")
            continue 

        staged_name =os .path .basename (dest )
        moved .append ((name ,category ,staged_name ))
        log_event (f"Home-dir scan: found {name } -> staged to library/{category }/{staged_name }","ok")

    if moved :
        with _file_meta_cache_lock :
            _file_meta_cache .clear ()

    return moved 


def compare_before_write (dest_path ,data_bytes ):
    dest_dir =os .path .dirname (dest_path )
    if dest_dir :
        os .makedirs (dest_dir ,exist_ok =True )
    if os .path .isfile (dest_path ):
        with open (dest_path ,"rb")as f :
            existing =f .read ()
        if existing ==data_bytes :
            return False ,"unchanged (skipped write)"
    # A fixed dest_path + ".tmp" name is shared by every concurrent
    # writer targeting the same dest_path -- two uploads/edits racing
    # on the same filename can interleave writes into that one tmp
    # file before either os.replace() runs. tempfile.mkstemp() gives
    # each call its own uniquely-named tmp file in the same directory
    # (so os.replace() stays an atomic same-filesystem rename), created
    # with the 0600 mode already applied at open time -- no separate
    # os.chmod() needed.
    base =os .path .basename (dest_path )
    fd ,tmp_path =tempfile .mkstemp (prefix =base +".",suffix =".tmp",dir =dest_dir or ".")
    try :
        os .fchmod (fd ,0o600 )
        with os .fdopen (fd ,"wb")as f :
            f .write (data_bytes )
        os .replace (tmp_path ,dest_path )
    except BaseException :
        try :
            os .unlink (tmp_path )
        except OSError :
            pass 
        raise 
    return True ,"written"


def systemctl_is_active (service ):
    try :
        result =subprocess .run (
        ["systemctl","is-active",service ],
        capture_output =True ,text =True ,timeout =3 ,
        )
        return result .stdout .strip ()or "unknown"
    except (FileNotFoundError ,subprocess .TimeoutExpired ):
        return "unknown"


# =====================================================================
# Quiesce for Backup/Clone (v2.16.0, Stage 1 of the quiesce plan)
#
# Optionally stop the node's own services for the duration of a disk
# image Backup or Clone, so far fewer writes are in flight while dd
# reads the live boot disk. This is NOT a filesystem snapshot: the
# image stays crash-consistent (ext4 replays its journal on first boot
# of a restored card). It reduces in-flight writes; it does not
# eliminate them.
#
# Deliberately an ALLOW-LIST, never "list every running unit and exempt
# a few". A running Pi has dbus, systemd-logind, systemd-udevd, polkit,
# user@0 and friends in that list, and stopping systemd-udevd would
# break the very partprobe/lsblk calls this feature depends on. The
# allow-list is built from the two curated lists this file already
# maintains for other purposes (COMPONENTS, COMMS_RESTART_SERVICES),
# so it can never drift away from what the suite actually installs.
#
# THREE TIERS, stopped 0 -> 1 -> 2 and restarted 2 -> 1 -> 0:
#
#   Tier 0  asl_dvs_watchdog*.timer  -- FIRST, because the watchdog
#           fires every 45s and issues `systemctl restart` on a target
#           it finds down; leave it running and it simply undoes the
#           quiesce mid-copy. Globbed, not hardcoded:
#           ASL_DVS_WATCHDOG_INSTANCE means a node can have several
#           (e.g. the M17/Zello branch's own). Restarted LAST, so its
#           first tick lands well after the dashboard is up rather
#           than during the dashboard's own startup window -- exactly
#           the false-alarm case asl_dvs_watchdog.sh v2.4 fixed.
#
#   Tier 1  the suite's web tools. They are Asterisk *clients*, so
#           they go down before Asterisk does; dropping Asterisk first
#           would just spray connection errors into the journal for
#           the few seconds before these stop anyway -- noise in
#           exactly the log you would be reading if the backup went
#           wrong. instmon itself is NEVER in any tier.
#
#   Tier 2  comms: Asterisk, the bridges, Allmon3, SVXLink. Restarted
#           first on the way back up, so the web tools find a live
#           Asterisk on their first poll instead of failing once and
#           waiting out a retry interval.
#
# Every tier is filtered to units that are actually active at quiesce
# time, so only what was really running is ever restarted.
# =====================================================================

_QUIESCE_TIER0_GLOB = "asl_dvs_watchdog*.timer"

# COMPONENTS categories that are never stopped by a quiesce (v2.21.0):
#
#   instmon   -- stopping the process running this code would end the
#                job it is trying to protect.
#   watchdog  -- already covered by the tier-0 glob above, which also
#                catches instance-suffixed copies (see
#                ASL_DVS_WATCHDOG_INSTANCE) that this single COMPONENTS
#                entry does not know about.
#   sysmon    -- deliberate carve-out. A disk image is the longest,
#                highest-risk operation instmon performs, and sysmon is
#                the only live view of temperature, voltage and disk
#                during it. It is a read-mostly monitor: its write
#                volume is irrelevant next to Asterisk and the bridges,
#                so stopping it costs visibility and buys essentially
#                nothing.
_QUIESCE_NEVER_STOP_CATEGORIES = ("instmon", "watchdog", "sysmon")

# Tier 2 is COMMS_RESTART_SERVICES plus SVXLink. SVXLink is not in that
# list because the Comms SERV Restart button predates 44helper's
# SVXLink support; it is included here only when actually active (see
# _quiesce_resolve_units), so a node without it is unaffected.
_QUIESCE_TIER2_EXTRA = [("SVXLink", "svxlink.service")]

_QUIESCE_STATE_PATH = os.path.join(CONFIG_DIR, "instmon_quiesce_state.json")
QUIESCE_STOP_TIMEOUT_SEC = int(os.environ.get("INSTMON_QUIESCE_STOP_TIMEOUT_SEC", "15"))

# After `systemctl stop` hits our client-side timeout, poll this many
# times at this interval before calling it a failure. The timeout kills
# the systemctl *client*, not the systemd *job* -- a slow-but-working
# stop and a wedged unit look identical at the moment the client dies,
# and only re-checking is-active tells them apart.
_QUIESCE_STOP_RECHECK_TRIES = 3
_QUIESCE_STOP_RECHECK_DELAY = 2.0

# apt/dpkg lock files. These are PERMANENT files -- they exist on every
# Debian system whether or not apt is running, so os.path.exists() is
# meaningless here. apt holds an flock() on them; the only correct test
# is to try to take that lock ourselves, non-blocking.
_QUIESCE_APT_LOCKS = (
    "/var/lib/dpkg/lock-frontend",
    "/var/lib/dpkg/lock",
    "/var/cache/apt/archives/lock",
    "/var/lib/apt/lists/lock",
)
_QUIESCE_APT_UNITS = (
    "unattended-upgrades.service",
    "apt-daily.service",
    "apt-daily-upgrade.service",
)
_QUIESCE_UU_PIDFILE = "/run/unattended-upgrades.pid"

_quiesce_lock = threading.Lock()

# v2.37.0 Quiet System: the same quiesce machinery with a narrower set --
# the watchdog timer(s) plus the suite's web tools, never Asterisk or the
# bridges (tier 2), never instmon, and never wifimon (it runs the Wi-Fi
# fallback; stopping it could cut a headless Pi off). Unlike a disk image,
# sysmon IS stopped -- freeing its memory is the point on a Pi Zero 2 W.
QUIET_JOB_ID = "quiet-system"
_QUIET_KEEP_CATEGORIES = ("instmon", "watchdog", "wifimon")


def _quiesce_list_timer_units(glob_pattern=_QUIESCE_TIER0_GLOB):
    """Every currently-active timer unit whose NAME matches the glob.
    This is a unit-name match via systemd, not a shell glob over a
    directory -- a node may have several watchdog timers installed
    under different ASL_DVS_WATCHDOG_INSTANCE suffixes and we need all
    of them. Returns a list of unit names, sorted for stable ordering
    (so the stop order and the command preview always agree)."""
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--type=timer", "--state=active",
             "--plain", "--no-legend", "--no-pager"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        log_event(f"Quiesce: could not list timer units: {exc}", "warn")
        return []
    if result.returncode != 0:
        return []
    names = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        if fnmatch.fnmatch(unit, glob_pattern):
            names.append(unit)
    return sorted(set(names))


def _quiesce_resolve_units(scope="diskimg"):
    """The full quiesce set as [(tier, label, unit)], in STOP order
    (tier 0 first). Only units systemctl reports as active are
    included, so _unquiesce_services() can never start something that
    was already down before the job began. instmon is excluded
    unconditionally -- stopping the process running this code would
    end the job it is trying to protect."""
    resolved = []

    for unit in _quiesce_list_timer_units():
        resolved.append((0, unit.rsplit(".", 1)[0], unit))

    keep = _QUIET_KEEP_CATEGORIES if scope == "quiet" else _QUIESCE_NEVER_STOP_CATEGORIES
    for comp in COMPONENTS:
        if comp["category"] in keep:
            continue
        unit = comp["service"]
        if not unit.endswith(".service") and not unit.endswith(".timer"):
            unit = unit + ".service"
        if systemctl_is_active(unit) == "active":
            resolved.append((1, comp["name"], unit))

    if scope == "quiet":
        return resolved

    for label, unit in list(COMMS_RESTART_SERVICES) + _QUIESCE_TIER2_EXTRA:
        if systemctl_is_active(unit) == "active":
            resolved.append((2, label, unit))

    return resolved


def _quiesce_check_package_locks():
    """(ok, reason). Refuse to quiesce while apt/dpkg is mid-run --
    stopping services underneath a package upgrade is how you get a
    half-configured dpkg database, and the resulting image would carry
    that damage forward into every restore."""
    for path in _QUIESCE_APT_LOCKS:
        if not os.path.exists(path):
            continue
        fd = None
        try:
            fd = os.open(path, os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                return False, f"A package manager is running (lock held on {path}). Try again once apt/dpkg finishes."
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            # Cannot open it at all -- do not invent a blocker out of a
            # permissions or filesystem quirk; the unit checks below
            # still cover the common unattended-upgrades case.
            pass
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    try:
        with open(_QUIESCE_UU_PIDFILE, "r") as fh:
            pid = fh.read().strip()
        # A stale pidfile left behind by a crashed run is a known
        # unattended-upgrades failure mode, so the file existing is not
        # itself proof anything is running -- check the process.
        if pid.isdigit() and os.path.isdir(f"/proc/{pid}"):
            return False, "unattended-upgrades is currently running. Try again once it finishes."
    except (OSError, ValueError):
        pass

    for unit in _QUIESCE_APT_UNITS:
        if systemctl_is_active(unit) == "active":
            return False, f"{unit} is currently running. Try again once it finishes."

    return True, ""


def _quiesce_active_connections():
    """Best-effort description of what this quiesce is about to drop
    (v2.23.0). Purely informational -- it never blocks or fails a
    quiesce, it just turns "why did 652701 drop at 14:20?" into a line
    in the console instead of an afternoon in the journal.

    Deliberately not a pre-flight gate: the operator has already been
    told the node goes off the air and has confirmed it twice. Turning
    an active QSO into a hard refusal would mean a backup that can
    never run on a busy node.

    Returns a list of human-readable lines, empty if Asterisk isn't
    there, isn't an app_rpt build, or anything at all goes wrong."""
    if not shutil.which("asterisk"):
        return []
    def _rx(cmd):
        try:
            r = subprocess.run(["asterisk", "-rx", cmd],
                               capture_output=True, text=True, timeout=8)
            return r.stdout if r.returncode == 0 else ""
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ""

    lines = []
    try:
        local = _rx("rpt localnodes")
        nodes = re.findall(r"^\s*(\d{3,7})\s*$", local, re.MULTILINE)
        for node in nodes[:8]:
            out = _rx(f"rpt nodes {node}")
            # app_rpt prints a table of connected node numbers; pull the
            # numeric ones and drop the node's own entry.
            conns = [n for n in re.findall(r"\b(\d{4,7})\b", out) if n != node]
            conns = sorted(set(conns))
            if conns:
                lines.append(f"node {node}: {len(conns)} connection(s) -- {', '.join(conns[:20])}"
                             + (" ..." if len(conns) > 20 else ""))
            else:
                lines.append(f"node {node}: no connections")
    except Exception:
        return []
    return lines


def _quiesce_state_write(job_id, stopped, started_at=None):
    """Persist what we have stopped so far. Written after EVERY
    individual stop, not once at the end, so a hard kill between two
    stops still leaves an accurate record for the startup sweep to
    recover from. 0600 via compare_before_write(), which is the single
    choke point the v1.28.11 audit hardened for temp-file modes."""
    payload = json.dumps({
        "job_id": job_id,
        "started_at": started_at or time.time(),
        "stopped": [[tier, label, unit] for tier, label, unit in stopped],
    }, indent=2).encode("utf-8")
    try:
        ensure_dirs()
        compare_before_write(_QUIESCE_STATE_PATH, payload)
    except Exception as exc:
        log_event(f"Quiesce: could not write state file: {exc}", "err")


def _quiesce_state_read():
    """The persisted quiesce state, or None. A malformed file is
    treated as absent AND deleted -- this is read on the startup path
    (Stage 2) and must never be able to block instmon from booting."""
    try:
        with open(_QUIESCE_STATE_PATH, "r") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log_event(f"Quiesce: unreadable state file, discarding it: {exc}", "warn")
        _quiesce_state_clear()
        return None
    if not isinstance(data, dict) or not isinstance(data.get("stopped"), list):
        log_event("Quiesce: malformed state file, discarding it", "warn")
        _quiesce_state_clear()
        return None
    stopped = []
    for entry in data["stopped"]:
        if isinstance(entry, (list, tuple)) and len(entry) == 3:
            stopped.append((entry[0], entry[1], entry[2]))
    data["stopped"] = stopped
    return data


def _quiesce_state_clear():
    try:
        os.remove(_QUIESCE_STATE_PATH)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log_event(f"Quiesce: could not remove state file: {exc}", "warn")


def _quiesce_is_active():
    """True if a quiesce is currently recorded as in effect."""
    return os.path.exists(_QUIESCE_STATE_PATH)


def _quiesce_stop_one(unit):
    """(ok, detail) for one unit. Distinguishes 'the systemctl client
    timed out but the unit did stop' from 'the unit is wedged' -- see
    _QUIESCE_STOP_RECHECK_TRIES."""
    try:
        result = subprocess.run(
            ["systemctl", "stop", unit],
            capture_output=True, text=True, timeout=QUIESCE_STOP_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        for _ in range(_QUIESCE_STOP_RECHECK_TRIES):
            time.sleep(_QUIESCE_STOP_RECHECK_DELAY)
            if systemctl_is_active(unit) != "active":
                return True, f"stopped (systemctl client timed out after {QUIESCE_STOP_TIMEOUT_SEC}s, but the unit did stop)"
        return False, f"still active {QUIESCE_STOP_TIMEOUT_SEC}s after `systemctl stop` -- unit appears wedged"
    except (FileNotFoundError, OSError) as exc:
        return False, f"could not run systemctl: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        return False, f"systemctl stop returned {result.returncode}" + (f": {detail[0]}" if detail else "")
    if systemctl_is_active(unit) == "active":
        return False, "systemctl stop succeeded but the unit is still active"
    return True, "stopped"


def _quiesce_services(job_id, console_job_id=None, scope="diskimg"):
    """Stop the quiesce set in tier order. Returns (ok, stopped,
    message).

    ANY failure aborts: whatever has already been stopped is restarted
    immediately and ok=False is returned, so a caller never proceeds
    into dd with the node half-quiesced. On success, ends with a sync()
    -- the point of stopping the services was to stop them dirtying the
    page cache, so the flush belongs AFTER they are down, not before.
    """
    def _console(text):
        if console_job_id:
            _diskimg_console_append(console_job_id, text)

    with _quiesce_lock:
        # v2.37.0: one quiesce at a time. Quiet System and a disk-image
        # job share the state file; a second one would overwrite the
        # first one's record of what to restart.
        held = _quiesce_state_read()
        if held is not None and held.get("job_id") != job_id:
            who = "Quiet System" if held.get("job_id") == QUIET_JOB_ID else "a disk-image job"
            return False, [], f"Services are already paused by {who} -- restore them first."
        units = _quiesce_resolve_units(scope)
        if not units:
            _console("Quiesce: nothing to stop (no suite services are running).")
            log_event("Quiesce: nothing to stop -- no suite services active", "info")
            _quiesce_state_write(job_id, [])
            return True, [], "No suite services were running; nothing to stop."

        _console(f"Quiesce: stopping {len(units)} unit(s) -- the node will be off the air until this job finishes.")
        log_event(f"Quiesce: stopping {len(units)} unit(s) for job {job_id}", "warn")

        # v2.23.0: record what is about to be dropped, before dropping
        # it. Informational only -- see _quiesce_active_connections().
        try:
            for line in (_quiesce_active_connections() if scope != "quiet" else []):
                _console(f"  dropping: {line}")
                log_event(f"Quiesce dropping: {line}", "warn")
        except Exception:
            pass

        stopped = []
        for tier, label, unit in units:
            ok, detail = _quiesce_stop_one(unit)
            if ok:
                stopped.append((tier, label, unit))
                _quiesce_state_write(job_id, stopped)
                _console(f"  [tier {tier}] {label} ({unit}): {detail}")
                log_event(f"Quiesce: stopped {label} ({unit})", "info")
                continue
            # Abort. Roll back everything already stopped, in the
            # normal reverse-tier restart order.
            _console(f"  [tier {tier}] {label} ({unit}): FAILED -- {detail}")
            log_event(f"Quiesce: {label} ({unit}) failed to stop: {detail} -- aborting and restoring", "err")
            _console("Quiesce aborted -- restarting whatever was already stopped.")
            restore_ok, _results = _unquiesce_services(console_job_id=console_job_id, _already_locked=True)
            msg = f"Could not stop {label} ({unit}): {detail}." + (" Nothing was imaged." if scope != "quiet" else "")
            if not restore_ok:
                msg += " WARNING: not every service came back -- check the log; a reboot is recommended."
            return False, [], msg

        try:
            subprocess.run(["sync"], capture_output=True, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            log_event(f"Quiesce: sync after stop failed: {exc}", "warn")
        _console(f"Quiesce complete -- {len(stopped)} unit(s) stopped, buffers flushed.")
        return True, stopped, f"{len(stopped)} service(s) stopped."


def _unquiesce_services(console_job_id=None, _already_locked=False):
    """Restart everything the persisted state says we stopped, in
    reverse tier order (2 -> 1 -> 0). Returns (ok, results) where
    results is [(label, unit, ok, state)].

    Contract, because this is the recovery path and everything else
    depends on it holding:
      * IDEMPOTENT -- safe to call any number of times; a no-op when no
        state file exists.
      * NEVER RAISES -- catches everything, logs, and returns.
      * Safe from any thread.
      * Clears the state file only when every unit actually came back,
        so a partial recovery is retried by the next startup sweep
        instead of being silently forgotten.
    """
    def _console(text):
        if console_job_id:
            try:
                _diskimg_console_append(console_job_id, text)
            except Exception:
                pass

    def _run():
        try:
            state = _quiesce_state_read()
        except Exception as exc:
            log_event(f"Quiesce: could not read state during restore: {exc}", "err")
            return False, []
        if state is None:
            return True, []
        stopped = state.get("stopped") or []
        if not stopped:
            _quiesce_state_clear()
            return True, []

        _console(f"Unquiesce: restarting {len(stopped)} unit(s).")
        log_event(f"Unquiesce: restarting {len(stopped)} unit(s)", "info")

        results = []
        # Simply walk the recorded stop order backwards. That is the
        # exact mirror -- tier 2 first, tier 0 last, and reversed
        # within each tier too -- without needing to re-derive the
        # tiers from a state file that may have been written by an
        # older version.
        for tier, label, unit in list(reversed(stopped)):
            try:
                r = subprocess.run(["systemctl", "start", unit],
                                   capture_output=True, text=True, timeout=30)
                start_ok = r.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
                log_event(f"Unquiesce: {label} ({unit}) start errored: {exc}", "err")
                results.append((label, unit, False, f"error: {exc}"))
                _console(f"  [tier {tier}] {label} ({unit}): FAILED -- {exc}")
                continue
            state_now = systemctl_is_active(unit)
            ok = start_ok and state_now in ("active", "activating")
            results.append((label, unit, ok, state_now))
            _console(f"  [tier {tier}] {label} ({unit}): {'restarted' if ok else 'FAILED (now ' + state_now + ')'}")
            log_event(
                f"Unquiesce: {label} ({unit}) -> {'restarted' if ok else 'FAILED to start'} (now {state_now})",
                "ok" if ok else "err",
            )

        all_ok = all(ok for _l, _u, ok, _s in results)
        if all_ok:
            _quiesce_state_clear()
            _console("Unquiesce complete -- all services restarted. Node is back on the air.")
        else:
            failed = ", ".join(f"{l} ({u})" for l, u, ok, _s in results if not ok)
            _console(f"Unquiesce INCOMPLETE -- did not come back: {failed}. Reboot recommended.")
            log_event(f"Unquiesce incomplete -- still down: {failed}. Reboot recommended.", "err")
        return all_ok, results

    try:
        if _already_locked:
            return _run()
        with _quiesce_lock:
            return _run()
    except Exception as exc:  # last-ditch: this function must never raise
        try:
            log_event(f"Unquiesce: unexpected error: {exc}", "err")
        except Exception:
            pass
        return False, []


def _quiesce_format_results(results):
    """One-line human summary of _unquiesce_services() results, for a
    job message / popup."""
    if not results:
        return ""
    failed = [f"{l}" for l, _u, ok, _s in results if not ok]
    if not failed:
        return f"All {len(results)} service(s) restarted."
    return (f"{len(results) - len(failed)} of {len(results)} service(s) restarted -- "
            f"still down: {', '.join(failed)}. Reboot recommended.")


# ---------------------------------------------------------------------
# systemd watchdog (v2.22.0)
#
# Closes the one hole the quiesce recovery story had. The reader
# thread's finally covers every ordinary end; Restart=always plus the
# startup sweep covers a crash, a SIGKILL, an OOM kill and a power cut,
# because a dead instmon is back within seconds and the sweep runs.
# What neither covered is instmon HANGING: still alive, so systemd
# never restarts it, so the sweep never runs, so a quiesced node stays
# off the air indefinitely. On a radio node that is the worst outcome
# this feature can produce.
#
# The ping is deliberately NOT a bare "this thread still runs" tick,
# which would keep reporting healthy through exactly the deadlock it is
# supposed to catch. It is gated on actually acquiring
# _diskimg_job_lock -- the lock every disk-image code path takes and
# releases quickly, and the one a wedged job would be holding. If it
# cannot be taken within _WATCHDOG_LOCK_TIMEOUT, this process has
# stopped being able to do its job, the ping stops, and systemd
# restarts it into the startup sweep.
#
# WatchdogSec= alone is enough for systemd to provide $NOTIFY_SOCKET;
# Type=notify is not required.
# ---------------------------------------------------------------------

_WATCHDOG_LOCK_TIMEOUT = 15.0


def _sd_notify(message):
    """Send one datagram to systemd's notify socket. Best-effort and
    silent: a missing or unusable socket just means this instance is
    not being watchdogged (run by hand, an older unit file without
    WatchdogSec, a non-systemd box), which is not an error."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]  # abstract namespace
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.connect(addr)
            sock.sendall(message.encode("utf-8"))
        return True
    except (OSError, ValueError):
        return False


def _instmon_responsive():
    """True if this process can still do disk-image work. See the note
    above for why the job lock is the thing being tested."""
    acquired = _diskimg_job_lock.acquire(timeout=_WATCHDOG_LOCK_TIMEOUT)
    if not acquired:
        return False
    _diskimg_job_lock.release()
    return True


def _sd_watchdog_loop():
    if not os.environ.get("NOTIFY_SOCKET"):
        return
    try:
        interval_usec = int(os.environ.get("WATCHDOG_USEC", "0"))
    except ValueError:
        interval_usec = 0
    # systemd's own guidance: ping at half the configured interval.
    period = (interval_usec / 1e6 / 2.0) if interval_usec > 0 else 30.0
    period = max(5.0, min(period, 300.0))
    log_event(f"systemd watchdog active -- pinging every {period:.0f}s while responsive", "info")
    warned = False
    while True:
        try:
            if _instmon_responsive():
                _sd_notify("WATCHDOG=1")
                warned = False
            elif not warned:
                warned = True
                # Log once, then stay quiet: if this is real, systemd
                # kills us shortly and the message needs to be in the
                # journal, not repeated every cycle.
                log_event(
                    "instmon appears wedged (disk-image lock unavailable for "
                    f"{_WATCHDOG_LOCK_TIMEOUT:.0f}s) -- withholding the systemd watchdog ping so "
                    "systemd restarts this service. Any quiesced services will be restored on startup.",
                    "err",
                )
        except Exception:
            pass
        time.sleep(period)


def _quiesce_stop_orphaned_job(job_id):
    """Stop a detached disk-image unit left running by a previous
    instmon process (v2.22.0).

    _diskimg_dd_command wraps dd in a `systemd-run --pipe --collect`
    transient unit precisely so the copy survives an instmon restart.
    That is right when instmon restarts mid-copy for an unrelated
    reason -- but the reader thread does NOT survive, and it is the
    reader thread that reads dd's progress, runs verify and shrink,
    sets the terminal state and restores services. An orphaned copy is
    therefore one nothing will ever finish, verify, or report: it will
    keep writing gigabytes to a USB drive with nobody watching, and the
    job panel will never show it ending.

    So the sweep stops it and says so plainly, rather than leaving a
    half-finished image being written by a ghost."""
    unit = f"instmon-diskimg-{job_id}.service"
    try:
        r = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, text=True, timeout=5)
        if (r.stdout or "").strip() != "active":
            return False
    except Exception:
        # Broad on purpose. This runs on the startup path before the
        # socket binds, so ANYTHING raised here would stop instmon from
        # coming up at all -- and it would do so while services are
        # stopped, which is the exact state this code exists to escape.
        return False
    log_event(
        f"STARTUP RECOVERY: the previous process's disk-image copy ({unit}) is still running "
        "with nothing tracking it -- stopping it. Its destination is INCOMPLETE and unusable; "
        "start the job again once the node is back.",
        "err",
    )
    try:
        subprocess.run(["systemctl", "stop", unit], capture_output=True, timeout=30)
    except Exception as exc:
        log_event(f"STARTUP RECOVERY: could not stop {unit}: {exc}", "err")
    return True


def _quiesce_startup_sweep():
    """Called once from run(), BEFORE the socket binds.

    This is the whole recovery story. There is deliberately no deadline
    watchdog thread counting down against the job: the reader thread's
    finally block handles every ordinary end (success, dd failure,
    cancel, verify mismatch, an exception), and for everything it
    cannot handle -- SIGKILL, OOM, power loss, an unhandled crash --
    instmon is Restart=always, so the process is back within seconds
    and lands here. v2.22.0 added the last case: a HUNG instmon, which
    would otherwise never restart and so never reach this function, is
    now restarted by systemd's own watchdog (see _sd_watchdog_loop). A node left off the
    air is the worst failure this feature has, so this function is
    loud: it logs at err level, not info, and it says what to do if a
    service will not come back.

    Anything found here means the previous process died mid-job. The dd
    itself may well have survived (it runs in a detached systemd-run
    transient unit), but its reader thread did not, so nothing else is
    ever going to restore these services."""
    state = _quiesce_state_read()
    if state is None:
        return
    stopped = state.get("stopped") or []
    if not stopped:
        _quiesce_state_clear()
        return

    age = ""
    try:
        started = float(state.get("started_at") or 0)
        if started:
            age = f" (quiesced {int(time.time() - started)}s ago)"
    except (TypeError, ValueError):
        pass
    if state.get("job_id") == QUIET_JOB_ID:
        # v2.37.0: Quiet System never outlives the instmon that set it.
        log_event(f"Quiet System was on when instmon restarted{age} -- restoring "
                  f"{len(stopped)} service(s) now.", "warn")
    else:
        log_event(
            f"STARTUP RECOVERY: a previous instmon process left {len(stopped)} service(s) "
            f"stopped for disk-image job {state.get('job_id')}{age} -- restarting them now.",
            "err",
        )

    # Order matters: kill the orphaned copy FIRST. Restoring services
    # while a ghost dd is still reading the boot disk would put the
    # writes back exactly where they were being avoided, and the image
    # is unusable regardless since nothing will finalize it.
    if state.get("job_id") and state.get("job_id") != QUIET_JOB_ID:
        try:
            _quiesce_stop_orphaned_job(state["job_id"])
        except Exception as exc:
            log_event(f"STARTUP RECOVERY: orphan check failed: {exc}", "err")

    ok, results = _unquiesce_services()
    if ok:
        log_event(f"STARTUP RECOVERY: {_quiesce_format_results(results)} Node is back on the air.", "ok")
        return
    failed = [f"{l} ({u})" for l, u, k, _s in results if not k]
    log_event(
        "STARTUP RECOVERY INCOMPLETE -- these services did NOT come back: "
        + (", ".join(failed) if failed else "(none reported)")
        + ". The node may be off the air. A reboot is recommended.",
        "err",
    )


# ============ end quiesce core (v2.16.0) =============================


def port_open (port ,host ="127.0.0.1",timeout =0.5 ):
    if port is None :
        return None 
    try :
        with socket .create_connection ((host ,port ),timeout =timeout ):
            return True 
    except OSError :
        return False 


def attempt_rollback (dest_path ,backup_path ,comp ):

    if not os .path .isfile (backup_path ):
        return False ,None ,None 
    try :
        shutil .copy2 (backup_path ,dest_path )
    except OSError :
        return False ,None ,None 
    subprocess .run (["systemctl","restart",comp ["service"]],capture_output =True ,text =True ,timeout =10 )
    time .sleep (1.5 )
    state =systemctl_is_active (comp ["service"])
    listening =port_open (comp ["port"])
    log_event (f"Rolled back {comp ['name']} to previous version (now {state })","warn")
    return True ,state ,listening 


ROLLBACK_HISTORY_DEPTH =int (os .environ .get ("INSTMON_ROLLBACK_HISTORY_DEPTH","3"))


def _rotate_backups (dest_path ,depth =ROLLBACK_HISTORY_DEPTH ):

    if depth <1 :
        return 
    for n in range (depth ,1 ,-1 ):
        src =dest_path +(".prev"if n ==2 else f".prev{n -1 }")
        dst =dest_path +f".prev{n }"
        if os .path .isfile (src ):
            try :
                os .replace (src ,dst )
            except OSError :
                pass 


def install_file_with_verification (data ,dest_path ,comp ):

    had_existing =os .path .isfile (dest_path )
    backup_path =dest_path +".prev"
    try :
        if had_existing :
            _rotate_backups (dest_path )
            shutil .copy2 (dest_path ,backup_path )
        wrote ,reason =compare_before_write (dest_path ,data )
    except OSError as exc :
        return {
        "wrote":False ,"reason":"error","restarted":False ,
        "active":None ,"listening":None ,
        "message":f"Failed writing {dest_path }: {exc }","level":"err",
        }

    result ={"wrote":wrote ,"reason":reason ,"restarted":False ,"active":None ,"listening":None }
    if not wrote :
        result ["message"]="Already installed (unchanged) -- no restart needed."
        result ["level"]="info"
        return result 

    def rollback_suffix ():
        if not had_existing :
            return " No previous version was available to roll back to."
        rolled_back ,rb_state ,_ =attempt_rollback (dest_path ,backup_path ,comp )
        if rolled_back and rb_state =="active":
            return " Rolled back to the previous version, which is running again."
        elif rolled_back :
            return f" Attempted rollback, but the previous version is now '{rb_state }' too -- check manually."
        return " Rollback attempt failed -- check manually."

    restart =subprocess .run (
    ["systemctl","restart",comp ["service"]],
    capture_output =True ,text =True ,timeout =10 ,
    )
    result ["restarted"]=True 
    if restart .returncode !=0 :
        err_tail =(restart .stderr or restart .stdout or "unknown error").strip ()[:200 ]
        log_event (f"systemctl restart {comp ['service']} failed: {err_tail }","err")
        result ["message"]=f"{comp ['service']} failed to restart: {err_tail }.{rollback_suffix ()}"
        result ["level"]="err"
        return result 


    time .sleep (1.5 )
    state =systemctl_is_active (comp ["service"])
    listening =port_open (comp ["port"])
    result ["active"]=state 
    result ["listening"]=listening 

    if state =="active"and listening :
        log_event (f"{comp ['name']} restarted OK, listening on port {comp ['port']}","ok")
        result ["message"]=f"{comp ['name']} restarted and is listening on port {comp ['port']}."
        result ["level"]="ok"
    elif state =="active":
        log_event (f"{comp ['name']} restarted, active but not yet listening on port {comp ['port']}","warn")
        result ["message"]=f"{comp ['name']} is active but not yet listening on port {comp ['port']} (may still be starting)."
        result ["level"]="warn"
    else :
        log_event (f"{comp ['name']} restarted but is now '{state }'","err")
        result ["message"]=f"{comp ['name']} is now '{state }' after restart.{rollback_suffix ()}"
        result ["level"]="err"

    return result 


def _scan_file_header_uncached (path ):

    if not os .path .isfile (path ):
        return None ,False ,False 
    try :
        with open (path ,"r",encoding ="utf-8",errors ="replace")as f :
            content =f .read ()
    except OSError :
        return None ,False ,False 
    return _scan_header_text (content )


def _scan_header_text (content ):
    # Same version / self-install detection as a library file, but on
    # text already in memory -- used for GitHub downloads before they
    # are ever written to the library.
    m =re .search (r'^\s*VERSION\s*=\s*"([^"]+)"',content ,re .MULTILINE )
    version =m .group (1 )if m else None 
    self_install =('add_argument("--install"'in content )and ("def install_service"in content )
    self_uninstall =('add_argument("--uninstall"'in content )and ("def uninstall_service"in content )

    
    
    
    
    
    if version is None :
        m =re .search (r'^\s*SCRIPT_VERSION\s*=\s*"([^"]+)"',content ,re .MULTILINE )
        version =m .group (1 )if m else None 
    if version is None :
        m =re .search (r'^\s*APP_VERSION\s*=\s*"([^"]+)"',content ,re .MULTILINE )
        version =m .group (1 )if m else None 
    if version is None :
        m =re .search (r'^\s*#\s*Version\s*:\s*([0-9]+(?:\.[0-9]+)*)',content ,re .MULTILINE |re .IGNORECASE )
        version =m .group (1 )if m else None 
    if version is None :
        # Last resort, first 10 lines only: a title comment naming the
        # file and its version, e.g. "# install_asl_dvs.sh  v6.3  (date)".
        # Changelog lines ("# v5.3: ...") don't match -- a file name must
        # come first.
        head ="\n".join (content .split ("\n",10 )[:10 ])
        m =re .search (r'^#\s*[A-Za-z0-9._-]+\.(?:sh|py)\s+v([0-9]+(?:\.[0-9]+)*)\b',head ,re .MULTILINE )
        version =m .group (1 )if m else None 
    if not self_install :
        self_install =("--install)"in content )and ("do_install"in content )
    if not self_uninstall :
        self_uninstall =("--uninstall)"in content )and ("do_uninstall"in content )

    return version ,self_install ,self_uninstall 


def _interp_for (path ):
    
    
    return "bash"if path .lower ().endswith (".sh")else "python3"


# Bounded LRU rather than a plain dict -- library entries get renamed,
# force-uploaded past a mismatch, or replaced by newer versions over a
# node's uptime, and every distinct path this has ever stat()'d stays
# keyed here forever otherwise. OrderedDict gives cheap move-to-end on
# hit and a cheap oldest-first evict on overflow without pulling in a
# real LRU library for what's a small, single-purpose cache.
_FILE_META_CACHE_MAX =2000 
_file_meta_cache =collections .OrderedDict ()
_file_meta_cache_lock =threading .Lock ()


def _file_meta (path ):

    try :
        st =os .stat (path )
    except OSError :
        return None ,None ,False ,False 
    stamp =(st .st_mtime ,st .st_size )
    with _file_meta_cache_lock :
        cached =_file_meta_cache .get (path )
        if cached and cached [0 ]==stamp :
            _file_meta_cache .move_to_end (path )
            return cached [1 ],cached [2 ],cached [3 ],cached [4 ]
    sha =_file_sha256_uncached (path )
    ver ,self_install ,self_uninstall =_scan_file_header_uncached (path )
    with _file_meta_cache_lock :
        _file_meta_cache [path ]=(stamp ,sha ,ver ,self_install ,self_uninstall )
        _file_meta_cache .move_to_end (path )
        while len (_file_meta_cache )>_FILE_META_CACHE_MAX :
            _file_meta_cache .popitem (last =False )
    return sha ,ver ,self_install ,self_uninstall 


def file_sha256 (path ):
    sha ,_ver ,_self_install ,_self_uninstall =_file_meta (path )
    return sha 


def read_installed_version (path ):
    _sha ,ver ,_self_install ,_self_uninstall =_file_meta (path )
    return ver 


def script_has_self_install (path ):

    _sha ,_ver ,self_install ,_self_uninstall =_file_meta (path )
    return self_install 


def script_has_self_uninstall (path ):

    _sha ,_ver ,_self_install ,self_uninstall =_file_meta (path )
    return self_uninstall 


def check_python_syntax (path ):

    tmp_cfile =None 
    try :
        with tempfile .NamedTemporaryFile (suffix =".pyc",delete =False )as tmp :
            tmp_cfile =tmp .name 
        py_compile .compile (path ,cfile =tmp_cfile ,doraise =True )
        return None 
    except py_compile .PyCompileError as exc :
        return str (getattr (exc ,"msg",exc ))
    except (SyntaxError ,ValueError )as exc :
        return str (exc )
    except OSError as exc :
        return f"Could not check syntax: {exc }"
    finally :
        if tmp_cfile and os .path .exists (tmp_cfile ):
            try :
                os .remove (tmp_cfile )
            except OSError :
                pass 


def check_bash_syntax (path ):
    try :
        result =subprocess .run (
        ["bash","-n",path ],capture_output =True ,text =True ,timeout =10 ,
        )
        if result .returncode !=0 :
            return result .stderr .strip ()or f"bash -n exited {result .returncode }"
        return None 
    except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
        return f"Could not check syntax: {exc }"


def check_script_syntax (path ):
    
    
    
    
    if path .lower ().endswith (".sh"):
        return check_bash_syntax (path )
    return check_python_syntax (path )


def human_size (num_bytes ):
    for unit in ("B","KB","MB","GB"):
        if num_bytes <1024 :
            return f"{num_bytes :.0f} {unit }"if unit =="B"else f"{num_bytes :.1f} {unit }"
        num_bytes /=1024 
    return f"{num_bytes :.1f} TB"


def resolve_installed_target (comp ):

    return os .path .realpath (comp ["install_link"])


def _version_sort_key (ver ):
    if not ver or ver =="?":
        return (-1 ,)
    # Strip a leading v/V ("v2.0" -> "2.0") before parsing. Without this,
    # the leading "v2" segment has no digit at position 0 so re.match
    # fails and the whole segment parses as 0 -- "v2.0" -> (0, 0), which
    # sorts *before* "0.9" -> (0, 9). Only the very first segment can
    # carry the prefix, so this only needs to strip once at the start
    # of the whole string, not per-segment.
    if ver and ver [0 ]in ("v","V"):
        ver =ver [1 :]
    parts =[]
    for p in ver .split ("."):
        m =re .match (r"\d+",p )
        parts .append (int (m .group ())if m else 0 )
    return tuple (parts )


def scan_library ():
    ensure_dirs ()
    out ={cat :[]for cat in LIB_SUBDIRS }
    for cat ,dir_path in LIB_SUBDIRS .items ():
        try :
            names =os .listdir (dir_path )
        except OSError :
            names =[]
        for name in names :
            full =os .path .join (dir_path ,name )
            if not os .path .isfile (full ):
                continue 
            stat =os .stat (full )
            entry ={
            "name":name ,
            "size":human_size (stat .st_size ),
            "mtime":datetime .fromtimestamp (stat .st_mtime ).strftime ("%Y-%m-%d %H:%M"),
            "mtime_epoch":stat .st_mtime ,
            "category":cat ,
            }
            if cat in INSTALLABLE_CATEGORIES :
                ver =read_installed_version (full )
                entry ["version"]=ver or "?"
                comp =next ((c for c in COMPONENTS if c ["category"]==cat ),None )
                if comp :
                    entry ["installed"]=(file_sha256 (full )==file_sha256 (resolve_installed_target (comp )))
                else :
                    entry ["installed"]=False 
            elif cat =="config":
                live_cfg =os .path .join (CONFIG_DIR ,CONFIG_NAME )
                entry ["installed"]=(file_sha256 (full )==file_sha256 (live_cfg ))
                entry ["version"]="config"
            else :
                entry ["installed"]=None 
                entry ["version"]="script"
            out [cat ].append (entry )
        if cat in INSTALLABLE_CATEGORIES :
            out [cat ].sort (key =lambda e :_version_sort_key (e ["version"]),reverse =True )
        else :
            out [cat ].sort (key =lambda e :e ["mtime_epoch"],reverse =True )
    return out 


def build_status ():
    components =[]
    for comp in COMPONENTS :
        state =systemctl_is_active (comp ["service"])
        listening =port_open (comp ["port"])
        installed_target =resolve_installed_target (comp )
        components .append ({
        "name":comp ["name"],
        "service":comp ["service"],
        "port":comp ["port"],
        "category":comp ["category"],
        "state":state ,
        "listening":listening ,
        "version":read_installed_version (installed_target )or "?",


        "installed":os .path .isfile (installed_target ),
        })
    return {
    "components":components ,
    "library":scan_library (),
    "config":{
    "name":CONFIG_NAME ,
    "installed":os .path .isfile (os .path .join (CONFIG_DIR ,CONFIG_NAME )),
    },
    }


def is_installer_script (name ):

    return fnmatch .fnmatch (name .lower (),INSTALLER_SCRIPT_GLOB .lower ())


def is_uninstaller_script (name ):

    return fnmatch .fnmatch (name .lower (),UNINSTALLER_SCRIPT_GLOB .lower ())


def is_interactive_only_script (name ):

    return any (fnmatch .fnmatch (name .lower (),g .lower ())for g in INTERACTIVE_ONLY_SCRIPT_GLOBS )


# =====================================================================
# GitHub updates (v2.32.0 - v2.36.0)
#
# Check GitHub asks GitHub for the list of files in the suite's public
# repo (one api.github.com request -- nothing to maintain in the repo),
# keeps the files whose names match a library naming pattern, reads
# each one's version from inside the file, and compares the newest
# GitHub copy of each kind with the newest local copy in its own
# library folder. A file already in the library (same git blob id) is
# never downloaded again. Update downloads one file, checks it (same
# file GitHub listed, version line, shebang, syntax, --install support)
# and only then writes it into that library folder with
# compare_before_write(). Nothing is ever installed from here -- the
# library card's own Install button does that. Never downgrades, never
# touches config.
#
# The file-name -> category rule is HOME_SCAN_PATTERN_MAP, first match
# wins -- the same table the home-folder sweep and uploads use, so a
# GitHub file can only land in the folder a manual upload would use.
# =====================================================================

GITHUB_REPO =os .environ .get ("INSTMON_GITHUB_REPO","kd8pgk/ASL-DVS").strip ("/")
GITHUB_BRANCH =os .environ .get ("INSTMON_GITHUB_BRANCH","main")
GITHUB_RAW_BASE =f"https://raw.githubusercontent.com/{GITHUB_REPO }/{GITHUB_BRANCH }"
GITHUB_API_LIST_URL =(f"https://api.github.com/repos/{GITHUB_REPO }/contents"
f"?ref={urllib .parse .quote (GITHUB_BRANCH ,safe ='')}")
GITHUB_TIMEOUT_SEC =int (os .environ .get ("INSTMON_GITHUB_TIMEOUT_SEC","15"))
GITHUB_LIST_MAX_BYTES =1024 *1024 
GITHUB_FILE_MAX_BYTES =MAX_UPLOAD_BYTES 
GITHUB_MAX_ENTRIES =1000 

# Config files are per-node and never come from GitHub.
GH_CATEGORIES =tuple (c for c in LIB_SUBDIRS if c !="config")

_GH_REPO_RE =re .compile (r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')
_GH_NAME_RE =re .compile (r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
_GH_SHA1_RE =re .compile (r'^[0-9a-f]{40}$')

_GH_LABELS ={
"up_to_date":("Up to date",""),
"update":("Update available","gh-upd"),
"missing":("Not in library","gh-upd"),
"newer_local":("Library is newer",""),
"conflict":("Same version, different file","gh-warn"),
"error":("Error","gh-err"),
}
_GH_UPDATABLE =("update","missing")


class GhRejected (Exception ):
    """A download or check that failed. The message is shown to the user."""


_gh_lock =threading .Lock ()
_gh_state ={
"phase":"idle",       # idle | checking | done | error
"checked_at":None ,
"error":None ,
"entries":[],         # newest GitHub file of each kind, with its status
"skipped":0 ,         # tool-named files that could not be used (reasons in the log)
"busy":set (),        # file names being downloaded right now
"event_seq":0 ,       # bumped on every finished check/update (page popup)
"event_msg":"",
"event_level":"info",
}

# git blob id -> version read from that file. A blob id names exact file
# content, so a file read once is never downloaded again just to learn
# its version. Bounded; cleared if it ever grows past the cap.
_gh_version_cache ={}
_GH_VERSION_CACHE_MAX =200 
_gh_last_cands = []  # v2.37.0: last parsed GitHub listing (Full Update)


def _gh_event (message ,level ):
    # Caller must NOT hold _gh_lock.
    log_event (message ,level )
    with _gh_lock :
        _gh_state ["event_seq"]+=1 
        _gh_state ["event_msg"]=message 
        _gh_state ["event_level"]=level 


def _gh_kind_for_name (name ):
    """(category, glob) for a file name, first match in
    HOME_SCAN_PATTERN_MAP wins. (None, None) if nothing matches."""
    lname =name .lower ()
    for category ,globs in HOME_SCAN_PATTERN_MAP :
        for g in globs :
            if fnmatch .fnmatch (lname ,g .lower ()):
                return category ,g .lower ()
    return None ,None 


def _git_blob_id (data ):
    """The id GitHub shows for a file's content (git's blob sha-1)."""
    return hashlib .sha1 (b"blob %d\x00"%len (data )+data ).hexdigest ()


def _gh_local_blob_id (path ):
    try :
        with open (path ,"rb")as f :
            return _git_blob_id (f .read ())
    except OSError :
        return None 


def _gh_source_label ():
    return f"{GITHUB_REPO } ({GITHUB_BRANCH })"


def _gh_fetch_https (url ,max_bytes ):
    """Download one URL. Certificate checking stays ON (unlike the LAN
    router probe). Returns bytes; raises GhRejected with a
    plain-language reason on any failure."""
    if not url .lower ().startswith ("https://"):
        raise GhRejected ("the GitHub address must start with https://")
    if not _GH_REPO_RE .match (GITHUB_REPO ):
        raise GhRejected (f"'{GITHUB_REPO }' is not an owner/repo name")
    shown =url .split ("?",1 )[0 ].rsplit ("/",1 )[-1 ]or url 
    req =urllib .request .Request (url ,headers ={
    "User-Agent":f"instmon/{VERSION }",
    "Accept":"application/vnd.github+json"if "api.github.com"in url else "*/*",
    "Cache-Control":"no-cache",
    })
    ctx =ssl .create_default_context ()
    deadline =time .monotonic ()+GITHUB_TIMEOUT_SEC *4 
    try :
        with urllib .request .urlopen (req ,timeout =GITHUB_TIMEOUT_SEC ,context =ctx )as resp :
            if not resp .geturl ().lower ().startswith ("https://"):
                raise GhRejected ("GitHub redirected the download off HTTPS")
            length =resp .headers .get ("Content-Length")
            if length and length .isdigit ()and int (length )>max_bytes :
                raise GhRejected (f"{shown } is larger than the {max_bytes //1024 } KB limit")
            chunks =[]
            total =0 
            while True :
                if time .monotonic ()>deadline :
                    raise GhRejected (f"download of {shown } took too long")
                chunk =resp .read (65536 )
                if not chunk :
                    break 
                total +=len (chunk )
                if total >max_bytes :
                    raise GhRejected (f"{shown } is larger than the {max_bytes //1024 } KB limit")
                chunks .append (chunk )
            return b"".join (chunks )
    except GhRejected :
        raise 
    except urllib .error .HTTPError as exc :
        if exc .code ==404 :
            raise GhRejected (f"{shown } was not found on GitHub (HTTP 404) -- check the repo name and branch")
        if exc .code in (403 ,429 ):
            raise GhRejected ("GitHub's hourly limit for this node was reached -- try again later "
            f"(HTTP {exc .code })")
        raise GhRejected (f"GitHub answered HTTP {exc .code } for {shown }")
    except urllib .error .URLError as exc :
        reason =getattr (exc ,"reason",exc )
        if isinstance (reason ,ssl .SSLError ):
            raise GhRejected (f"GitHub's certificate could not be verified ({reason })")
        raise GhRejected (f"cannot reach GitHub -- is this node online? ({reason })")
    except (socket .timeout ,TimeoutError ):
        raise GhRejected (f"GitHub did not answer within {GITHUB_TIMEOUT_SEC }s")
    except (OSError ,http .client .HTTPException ,ValueError )as exc :
        raise GhRejected (f"download of {shown } failed: {exc }")


# Swappable for tests (no network in the test harness).
_gh_fetch_impl =_gh_fetch_https 


def _gh_file_url (name ):
    return GITHUB_RAW_BASE +"/"+urllib .parse .quote (name )


def _gh_parse_listing (raw ):
    """Tool files from GitHub's folder listing:
    ([{name, category, glob, blob, size}], skipped_count).
    Files that match no library naming pattern (PDFs, LICENSE, ...) are
    ignored silently; tool-named files that can't be used are logged."""
    try :
        data =json .loads (raw .decode ("utf-8"))
    except (UnicodeDecodeError ,json .JSONDecodeError )as exc :
        raise GhRejected (f"GitHub's file list could not be read ({exc })")
    if not isinstance (data ,list ):
        raise GhRejected ("GitHub did not return a file list -- check the repo name and branch")
    if len (data )>GITHUB_MAX_ENTRIES :
        raise GhRejected (f"the repo lists more than {GITHUB_MAX_ENTRIES } files")
    out =[]
    skipped =0 
    for item in data :
        if not isinstance (item ,dict )or item .get ("type")!="file":
            continue 
        name =item .get ("name")
        if not isinstance (name ,str ):
            continue 
        category ,glob =_gh_kind_for_name (name )
        if category is None or category not in GH_CATEGORIES :
            continue 
        reason =None 
        ext =os .path .splitext (name )[1 ].lower ()
        blob =item .get ("sha")
        size =item .get ("size")
        if not _GH_NAME_RE .match (name ):
            reason ="file name has characters instmon refuses"
        elif ext not in ALLOWED_EXT .get (category ,()):
            reason =f"'{ext }' files are not allowed in the {category } library"
        elif not isinstance (blob ,str )or not _GH_SHA1_RE .match (blob ):
            reason ="GitHub gave no file id"
        elif not isinstance (size ,int )or size <=0 :
            reason ="empty file"
        elif size >GITHUB_FILE_MAX_BYTES :
            reason =f"larger than the {GITHUB_FILE_MAX_BYTES //1024 } KB limit"
        if reason :
            skipped +=1 
            log_event (f"GitHub: skipped {name }: {reason }","warn")
            continue 
        out .append ({"name":name ,"category":category ,"glob":glob ,"blob":blob ,"size":size })
    return out ,skipped 


def _gh_variant(version):
    """v2.37.1: the build a version line names -- "6.13.67-pi02w" is the
    Pi Zero 2 W build, "6.13.67" the plain one. Two builds of one tool
    share a file pattern, so the pattern alone can't tell them apart."""
    m = re.search(r"-([A-Za-z0-9]+)\s*$", version or "")
    return m.group(1).lower() if m else ""


def _gh_local_files (category ,glob ):
    """[(name, version, sort_key, path)] for library files of the same
    kind (same category AND same first-match pattern) as a GitHub file."""
    out =[]
    d =LIB_SUBDIRS [category ]
    try :
        names =os .listdir (d )
    except OSError :
        return out 
    for n in names :
        full =os .path .join (d ,n )
        if not os .path .isfile (full ):
            continue 
        if _gh_kind_for_name (n )!=(category ,glob ):
            continue 
        ver =read_installed_version (full )
        out .append ((n ,ver ,_version_sort_key (ver ),full ))
    return out 


def _gh_version_of (cand ,local ):
    """Version of a GitHub file: from an identical library file, the
    cache, or (last resort) by downloading it. Raises GhRejected."""
    for _n ,ver ,_key ,full in local :
        if ver and _gh_local_blob_id (full )==cand ["blob"]:
            return ver 
    if cand ["blob"]in _gh_version_cache :
        cached =_gh_version_cache [cand ["blob"]]
        if cached is None :
            raise GhRejected ("no version line found in the file")
        return cached 
    data =_gh_fetch_impl (_gh_file_url (cand ["name"]),GITHUB_FILE_MAX_BYTES )
    if _git_blob_id (data )!=cand ["blob"]:
        raise GhRejected ("the download did not match GitHub's file list (changed mid-check?)")
    try :
        text =data .decode ("utf-8")
    except UnicodeDecodeError :
        raise GhRejected ("not UTF-8 text")
    ver ,_si ,_su =_scan_header_text (text )
    if len (_gh_version_cache )>=_GH_VERSION_CACHE_MAX :
        _gh_version_cache .clear ()
    # Remember "no version" too, so the same file is not fetched again.
    _gh_version_cache [cand ["blob"]]=ver or None 
    if not ver :
        raise GhRejected ("no version line found in the file")
    return ver 


def _gh_compare (entry ):
    """Fill in status / local_name / local_version / message for one
    GitHub file against the library as it is right now."""
    variant =_gh_variant (entry .get ("version"))
    local =[l for l in _gh_local_files (entry ["category"],entry ["glob"])if _gh_variant (l [1 ])==variant ]
    entry ["local_name"]=None 
    entry ["local_version"]=None 
    for n ,ver ,_key ,full in local :
        if _gh_local_blob_id (full )==entry ["blob"]:
            entry ["status"]="up_to_date"
            entry ["local_name"]=n 
            entry ["local_version"]=ver 
            entry ["message"]=f"already in the library as {n }"
            return entry 
    if not local :
        entry ["status"]="missing"
        entry ["message"]="no copy of this file in the library yet"
        return entry 
    newest =max (local ,key =lambda t :t [2 ])
    entry ["local_name"]=newest [0 ]
    entry ["local_version"]=newest [1 ]
    rkey =_version_sort_key (entry ["version"])
    if rkey >newest [2 ]:
        entry ["status"]="update"
        entry ["message"]=f"library newest is v{newest [1 ]or '?'}"
    elif rkey <newest [2 ]:
        entry ["status"]="newer_local"
        entry ["message"]=f"library has v{newest [1 ]} -- GitHub is older, not offered"
    else :
        entry ["status"]="conflict"
        entry ["message"]=(f"library {newest [0 ]} has the same version but different content -- "
        "not updated (never reuse a version number)")
    return entry 


def _gh_collect ():
    """(entries, skipped): the newest GitHub file of each kind, compared."""
    raw =_gh_fetch_impl (GITHUB_API_LIST_URL ,GITHUB_LIST_MAX_BYTES )
    cands ,skipped =_gh_parse_listing (raw )
    # v2.37.0: Full Update plans from this same listing.
    _gh_last_cands[:] = [dict(c) for c in cands]
    newest ={}
    for cand in cands :
        local =_gh_local_files (cand ["category"],cand ["glob"])
        try :
            ver =_gh_version_of (cand ,local )
        except GhRejected as exc :
            if _gh_is_network_error (exc ):
                raise 
            skipped +=1 
            log_event (f"GitHub: skipped {cand ['name']}: {exc }","warn")
            continue 
        cand ["version"]=ver 
        kind =(cand ["category"],cand ["glob"],_gh_variant (ver ))
        if kind not in newest or _version_sort_key (ver )>_version_sort_key (newest [kind ]["version"]):
            newest [kind ]=cand 
    entries =[_gh_compare (e )for e in sorted (newest .values (),key =lambda e :(e ["category"],e ["name"]))]
    return entries ,skipped 


def _gh_is_network_error(exc):
    text = str(exc)
    return "reach GitHub" in text or "hourly limit" in text or "did not answer" in text


def _gh_check_bg ():
    try :
        entries ,skipped =_gh_collect ()
    except Exception as exc :
        msg =str (exc )if isinstance (exc ,GhRejected )else f"unexpected error: {exc }"
        with _gh_lock :
            _gh_state ["phase"]="error"
            _gh_state ["error"]=msg 
            _gh_state ["entries"]=[]
            _gh_state ["checked_at"]=datetime .now ().strftime ("%Y-%m-%d %H:%M")
        _gh_event (f"GitHub check failed: {msg }","err")
        return 
    with _gh_lock :
        _gh_state ["phase"]="done"
        _gh_state ["error"]=None 
        _gh_state ["entries"]=entries 
        _gh_state ["skipped"]=skipped 
        _gh_state ["checked_at"]=datetime .now ().strftime ("%Y-%m-%d %H:%M")
    counts =collections .Counter (e ["status"]for e in entries )
    ups =counts ["update"]+counts ["missing"]
    level ="ok"
    parts =[f"{ups } update(s) available"]
    if counts ["up_to_date"]:
        parts .append (f"{counts ['up_to_date']} up to date")
    if counts ["newer_local"]:
        parts .append (f"{counts ['newer_local']} where the library is newer")
    if counts ["conflict"]:
        parts .append (f"{counts ['conflict']} same-version conflict(s)")
        level ="warn"
    if skipped :
        parts .append (f"{skipped } file(s) skipped (see log)")
        level ="warn"
    _gh_event ("GitHub check: "+", ".join (parts )+".",level )
    full_update_preview()


def gh_start_check ():
    with _gh_lock :
        if _gh_state ["phase"]=="checking":
            return False ,"A GitHub check is already running."
        if _gh_state ["busy"]:
            return False ,"A GitHub download is running -- wait for it to finish."
        _gh_state ["phase"]="checking"
        _gh_state ["error"]=None 
    log_event (f"GitHub check started ({_gh_source_label ()})","info")
    threading .Thread (target =_gh_check_bg ,daemon =True ).start ()
    return True ,"Checking GitHub -- results appear in each library group."


def _gh_verify_content (entry ,data ):
    """Every check a download must pass before it is written. Raises
    GhRejected with the reason."""
    if _git_blob_id (data )!=entry ["blob"]:
        raise GhRejected ("the download does not match the file GitHub listed -- it was damaged, "
        "or the file changed on GitHub since the check (press Check GitHub again)")
    if not data :
        raise GhRejected ("the file is empty")
    if b"\x00"in data :
        raise GhRejected ("the file contains binary data")
    try :
        text =data .decode ("utf-8")
    except UnicodeDecodeError :
        raise GhRejected ("the file is not UTF-8 text")
    first =text .split ("\n",1 )[0 ].strip ()
    ext =os .path .splitext (entry ["name"])[1 ].lower ()
    if ext ==".sh":
        if not re .match (r'^#!.*\bbash\b',first ):
            raise GhRejected ("first line is not a bash #! line")
    elif ext ==".py":
        if not re .match (r'^#!.*\bpython3?\b',first ):
            raise GhRejected ("first line is not a python #! line")
    else :
        raise GhRejected (f"'{ext }' files are not handled")

    ver ,self_install ,_self_uninstall =_scan_header_text (text )
    if ver is None :
        raise GhRejected ("no version line found in the file")
    if ver !=entry ["version"]:
        raise GhRejected (f"the file says v{ver } but the check found v{entry ['version']} -- press Check GitHub again")
    if entry ["category"]in INSTALLABLE_CATEGORIES and not self_install :
        raise GhRejected ("the file has no --install support, so the Install button could not use it")

    fd ,tmp_path =tempfile .mkstemp (prefix ="instmon_gh_",suffix =ext )
    try :
        with os .fdopen (fd ,"wb")as f :
            f .write (data )
        err =check_script_syntax (tmp_path )
    finally :
        try :
            os .unlink (tmp_path )
        except OSError :
            pass 
    if err :
        raise GhRejected (f"syntax check failed: {err }")


def _gh_apply (entry ):
    """Download, check and stage one file. Returns (message, level)."""
    name =entry ["name"]
    category =entry ["category"]
    # Re-check the kind rule here too -- state could in theory be stale.
    if _gh_kind_for_name (name )!=(category ,entry ["glob"])or category not in GH_CATEGORIES :
        raise GhRejected (f"{name } does not belong in the {category } library")
    if not _GH_NAME_RE .match (name ):
        raise GhRejected ("invalid file name")
    data =_gh_fetch_impl (_gh_file_url (name ),GITHUB_FILE_MAX_BYTES )
    _gh_verify_content (entry ,data )

    # The library may have changed since the check: compare again now.
    current =_gh_compare (dict (entry ))
    if current ["status"]=="up_to_date":
        return f"{name } is already in the {category } library -- nothing to do.","info"
    if current ["status"]not in _GH_UPDATABLE :
        raise GhRejected (current ["message"])

    ensure_dirs ()
    dest =safe_join (LIB_SUBDIRS [category ],name )
    if dest is None :
        raise GhRejected ("invalid file name")
    wrote ,reason =compare_before_write (dest ,data )
    with _file_meta_cache_lock :
        _file_meta_cache .clear ()
    if not wrote :
        return f"{name } is already in the {category } library ({reason }).","info"
    nxt ="run it from there when you're ready"if category =="scripts"else "press Install on it to use it"
    return (f"Downloaded {name } (v{entry ['version']}) into the {category } library -- {nxt }.","ok")


def _gh_update_bg (entry ):
    name =entry ["name"]
    try :
        msg ,level =_gh_apply (entry )
    except GhRejected as exc :
        msg ,level =f"GitHub update of {name } refused: {exc }","err"
    except Exception as exc :
        msg ,level =f"GitHub update of {name } failed (unexpected): {exc }","err"
    refreshed =_gh_compare (dict (entry ))
    with _gh_lock :
        _gh_state ["busy"].discard (name )
        _gh_state ["entries"]=[refreshed if e ["name"]==name else e for e in _gh_state ["entries"]]
    _gh_event (msg ,level )


def gh_start_update (name ):
    """(http_code, message, level)."""
    if not isinstance (name ,str )or not name :
        return 400 ,"No file name given.","err"
    with _gh_lock :
        if _gh_state ["phase"]=="checking":
            return 409 ,"A GitHub check is running -- wait for it to finish.","warn"
        entry =next ((e for e in _gh_state ["entries"]if e ["name"]==name ),None )
        if entry is None :
            return 404 ,f"{name } is not in the last GitHub check -- press Check GitHub first.","warn"
        if name in _gh_state ["busy"]:
            return 409 ,f"{name } is already downloading.","warn"
        if entry .get ("status")not in _GH_UPDATABLE :
            label =_GH_LABELS .get (entry .get ("status"),("?",""))[0 ]
            return 400 ,f"{name }: {label } -- nothing to update.","warn"
        _gh_state ["busy"].add (name )
        entry =dict (entry )
    log_event (f"GitHub update started: {name }","info")
    threading .Thread (target =_gh_update_bg ,args =(entry ,),daemon =True ).start ()
    return 200 ,f"Downloading {name } -- it is checked before it is saved.","info"


def _gh_group_html (category ):
    """Status rows for one library group; empty until a check has run."""
    with _gh_lock :
        if _gh_state ["phase"]!="done":
            return ""
        entries =[dict (e )for e in _gh_state ["entries"]if e ["category"]==category ]
        busy =set (_gh_state ["busy"])
    if not entries :
        return ""
    rows =[]
    for e in entries :
        label ,cls =_GH_LABELS .get (e .get ("status"),("?",""))
        name =esc (e ["name"])
        if e ["name"]in busy :
            action ='<span class="small muted">Downloading&hellip;</span>'
        elif e .get ("status")in _GH_UPDATABLE :
            action =(f'<button data-action="gh_update" data-category="{esc (category )}" '
            f'data-name="{name }">Update</button>')
        else :
            action =""
        rows .append (
        f'<div class="gh-row" title="{esc (e .get ("message",""))}">'
        f'<span class="gh-tag {cls }">{esc (label )}</span>'
        f'<span>GitHub v{esc (e ["version"])}</span>'
        f'<span class="small muted">{name }</span>'
        f'{action }</div>')
    return '<div class="gh-rows">'+"".join (rows )+"</div>"


def _gh_summary_html ():
    with _gh_lock :
        phase =_gh_state ["phase"]
        err =_gh_state ["error"]
        when =_gh_state ["checked_at"]
        entries =list (_gh_state ["entries"])
        skipped =_gh_state ["skipped"]
    src =esc (_gh_source_label ())
    if phase =="idle":
        return f'<span class="muted">Not checked yet. Source: {src }</span>'
    if phase =="checking":
        return f'<span class="muted">Checking {src }&hellip;</span>'
    if phase =="error":
        return f'<span style="color:var(--red)">Last check ({esc (when or "")}) failed: {esc (err or "")}</span>'
    ups =sum (1 for e in entries if e .get ("status")in _GH_UPDATABLE )
    text =f"Checked {esc (when or '')}: {ups } update(s) available of {len (entries )} file(s)"
    if skipped :
        text +=f", {skipped } skipped (see log)"
    text +=". Update buttons are in each library group."
    return f'<span>{text }</span> <span class="muted">Source: {src }</span>'


def _gh_status_payload ():
    with _gh_lock :
        seq =_gh_state ["event_seq"]
        msg =_gh_state ["event_msg"]
        level =_gh_state ["event_level"]
    return {
    "gh_summary_html":_gh_summary_html (),
    "gh_event_seq":seq ,
    "gh_event_msg":msg ,
    "gh_event_level":level ,
    }


# =====================================================================
# Quiet System + Full Update (v2.37.0)
#
# Quiet System pauses the suite's web tools and the watchdog timer(s)
# (see QUIET_JOB_ID above) through the quiesce core, so a small Pi has
# memory and CPU for uploads and installs. It shares the quiesce state
# file, so the startup sweep restores it if instmon restarts, and it
# auto-restores after QUIET_AUTO_RESTORE_SEC.
#
# Full Update: read GitHub's file list, pick for every INSTALLED
# component the newest GitHub build of the same variant (a Pi02w sysmon
# stays on Pi02w builds) and every newer install script, download and
# check them all (the same checks as the GitHub Update button) before
# anything changes, then Quiet System and, one component at a time,
# save a library copy of the installed file, run its --uninstall, run
# the new file's --install and wait for the service. A failure puts the
# saved copy back and the component is skipped; the run carries on and
# ends with Restore and a summary. instmon goes last, after Restore.
# =====================================================================

QUIET_AUTO_RESTORE_SEC = int(os.environ.get("INSTMON_QUIET_AUTO_RESTORE_SEC", "1800"))

_quiet_timer = None
_quiet_timer_lock = threading.Lock()


def quiet_status():
    state = None
    if _quiesce_is_active():
        state = _quiesce_state_read()
    if not state:
        return {"on": False, "other": False, "since": "", "stopped": [],
                "auto_restore_min": QUIET_AUTO_RESTORE_SEC // 60}
    mine = state.get("job_id") == QUIET_JOB_ID
    since = ""
    try:
        since = datetime.fromtimestamp(float(state.get("started_at") or 0)).strftime("%H:%M")
    except (TypeError, ValueError, OSError):
        pass
    return {"on": mine, "other": not mine, "since": since,
            "stopped": [label for _t, label, _u in state.get("stopped") or []],
            "auto_restore_min": QUIET_AUTO_RESTORE_SEC // 60}


def _quiet_arm_timer(delay):
    global _quiet_timer
    with _quiet_timer_lock:
        if _quiet_timer:
            _quiet_timer.cancel()
        _quiet_timer = None
        if QUIET_AUTO_RESTORE_SEC > 0:
            _quiet_timer = threading.Timer(max(delay, 1), _quiet_auto_restore)
            _quiet_timer.daemon = True
            _quiet_timer.start()


def _quiet_auto_restore():
    if full_update_running():
        _quiet_arm_timer(60)  # Full Update restores at its own end
        return
    log_event(f"Quiet System: auto-restore after {QUIET_AUTO_RESTORE_SEC // 60} min", "warn")
    quiet_restore()


def quiet_start():
    """(ok, message, level)."""
    job = _diskimg_job_snapshot()
    if job and job.get("state") == "running":
        return False, "A disk-image job is running -- Quiet System is not needed (or wait for it).", "warn"
    if _quiesce_is_active():
        st = quiet_status()
        if st["on"]:
            return False, "The system is already quiet.", "info"
        return False, "Services are already paused by a disk-image job.", "warn"
    ok, stopped, message = _quiesce_services(QUIET_JOB_ID, scope="quiet")
    if not ok:
        return False, f"Quiet System failed: {message}", "err"
    _quiet_arm_timer(QUIET_AUTO_RESTORE_SEC)
    names = ", ".join(label for _t, label, _u in stopped) or "nothing was running"
    log_event(f"Quiet System on: {names}", "warn")
    return True, (f"System quiet: {names}. Press Restore when you're done "
                  f"(auto-restore in {QUIET_AUTO_RESTORE_SEC // 60} min)."), "ok"


def quiet_restore():
    """(ok, message, level)."""
    global _quiet_timer
    st = quiet_status()
    if not st["on"]:
        return False, "The system isn't quiet -- nothing to restore.", "info"
    with _quiet_timer_lock:
        if _quiet_timer:
            _quiet_timer.cancel()
        _quiet_timer = None
    ok, results = _unquiesce_services()
    summary = _quiesce_format_results(results) or "Nothing needed restarting."
    log_event(f"Quiet System restored: {summary}", "ok" if ok else "err")
    return ok, f"Restored. {summary}", "ok" if ok else "err"


def quiet_forget(service):
    """An Install/Uninstall already restarted (or removed) this service,
    so Restore must not touch it again."""
    with _quiesce_lock:
        state = _quiesce_state_read()
        if not state or state.get("job_id") != QUIET_JOB_ID:
            return
        names = {service, service + ".service"}
        kept = [e for e in state.get("stopped") or [] if e[2] not in names]
        if len(kept) != len(state.get("stopped") or []):
            _quiesce_state_write(QUIET_JOB_ID, kept, started_at=state.get("started_at"))


# --- Full Update -----------------------------------------------------

# One component at a time, in this order; instmon last because its own
# --install restarts this process.
FU_ORDER = ("44helper", "wifimon", "dashboard", "sysmon", "watchdog", "instmon")
FU_START_TIMEOUT_SEC = int(os.environ.get("INSTMON_FU_START_TIMEOUT_SEC", "60"))
FU_SELF_GUARD_SEC = 90
_FU_STATE_PATH = os.path.join(CONFIG_DIR, "instmon_full_update.json")

# Name stem of a plain build, for an installed file whose own name
# carries none (e.g. /usr/local/bin/wifimon.py). A VERSION suffix such as
# "6.13.67-pi02w" adds "_pi02w".
_FU_DEFAULT_STEM = {
    "dashboard": "asl_dvs_dashboard",
    "sysmon": "sysmon",
    "wifimon": "wifimon",
    "44helper": "asl_dvs_m17_44helper",
    "watchdog": "asl_dvs_watchdog",
    "instmon": "instmon",
}
_FU_STEM_RE = re.compile(r"^(?P<stem>.+?)_v\d+(?:[._]\d+)*(?:_\d{8})?(?:[._-].*)?\.(?:py|sh)$", re.IGNORECASE)

_fu_lock = threading.Lock()
_fu_state = {
    "running": False, "phase": "", "current": "", "error": "", "banner": False,
    "updated": [], "skipped": [], "attention": [], "scripts": [], "instmon_pending": None,
    "plan": None, "plan_at": "",
}


def full_update_running():
    with _fu_lock:
        return _fu_state["running"]


def _fu_set(**kw):
    with _fu_lock:
        _fu_state.update(kw)


def _fu_save():
    with _fu_lock:
        payload = {k: v for k, v in _fu_state.items() if k not in ("plan", "plan_at")}
    try:
        ensure_dirs()
        compare_before_write(_FU_STATE_PATH, json.dumps(payload, indent=2).encode("utf-8"))
    except Exception as exc:
        log_event(f"Full Update: could not save state: {exc}", "warn")


def full_update_snapshot():
    with _fu_lock:
        return json.loads(json.dumps(_fu_state))


def _fu_stem_of_name(name):
    m = _FU_STEM_RE.match(name)
    return (m.group("stem") if m else os.path.splitext(name)[0]).lower()


def _fu_installed_stem(comp, target, version):
    base = os.path.basename(target)
    if _FU_STEM_RE.match(base):
        return _fu_stem_of_name(base)
    stem = _FU_DEFAULT_STEM[comp["category"]]
    m = re.search(r"-([A-Za-z0-9]+)\s*$", version or "")
    return f"{stem}_{m.group(1).lower()}" if m else stem


def _fu_plan(cands):
    """For every COMPONENTS entry in FU_ORDER: what Full Update would do.
    cands come from _gh_parse_listing(). Versions are read the same way
    the GitHub check reads them (library copy, cache, or a download)."""
    rows = []
    for cat in FU_ORDER:
        comp = next((c for c in COMPONENTS if c["category"] == cat), None)
        if comp is None:
            continue
        row = {"category": cat, "name": comp["name"], "status": "", "note": "",
               "installed_version": "", "file": "", "version": ""}
        rows.append(row)
        target = resolve_installed_target(comp)
        if not os.path.isfile(target):
            row.update(status="not_installed", note="not installed -- left alone")
            continue
        inst_ver = read_installed_version(target)
        row["installed_version"] = inst_ver or "?"
        if not inst_ver:
            row.update(status="unknown", note="installed file has no version line -- update it by hand")
            continue
        stem = _fu_installed_stem(comp, target, inst_ver)
        best = None
        problems = []
        for cand in cands:
            if cand["category"] != cat or _fu_stem_of_name(cand["name"]) != stem:
                continue
            try:
                ver = _gh_version_of(cand, _gh_local_files(cand["category"], cand["glob"]))
            except GhRejected as exc:
                if _gh_is_network_error(exc):
                    raise
                log_event(f"Full Update: skipped {cand['name']}: {exc}", "warn")
                problems.append(f"{cand['name']}: {exc}")
                continue
            if best is None or _version_sort_key(ver) > _version_sort_key(best["version"]):
                best = dict(cand, version=ver)
        if best is None:
            if problems:
                row.update(status="error", note=f"couldn't read {problems[0]}")
            else:
                row.update(status="not_on_github", note=f"no {stem} build on GitHub")
            continue
        row.update(file=best["name"], version=best["version"], entry=best)
        if _gh_local_blob_id(target) == best["blob"]:
            row.update(status="current", note="same file as GitHub")
        elif _version_sort_key(best["version"]) > _version_sort_key(inst_ver):
            row.update(status="update", note=f"v{inst_ver} -> v{best['version']}")
        elif _version_sort_key(best["version"]) == _version_sort_key(inst_ver):
            row.update(status="current", note=f"same version (v{inst_ver})")
        else:
            row.update(status="newer_installed", note=f"installed v{inst_ver} is newer than GitHub")
        if problems and row["status"] != "update":
            # A GitHub file of this kind couldn't be read -- it may be the
            # newer one, so don't call this component current.
            row.update(status="error", note=f"couldn't read {problems[0]}")
    return rows


def _fu_publish_plan(rows, scripts):
    public = [{k: v for k, v in r.items() if k != "entry"} for r in rows]
    _fu_set(plan={"components": public, "scripts": [e["name"] for e in scripts],
                  "updates": sum(1 for r in rows if r["status"] == "update")},
            plan_at=datetime.now().strftime("%Y-%m-%d %H:%M"))


def _fu_stage(entry):
    """Download, check (same checks as the GitHub Update button) and
    write one component file into its library folder. Returns the path."""
    data = _gh_fetch_impl(_gh_file_url(entry["name"]), GITHUB_FILE_MAX_BYTES)
    _gh_verify_content(entry, data)
    ensure_dirs()
    dest = safe_join(LIB_SUBDIRS[entry["category"]], entry["name"])
    if dest is None:
        raise GhRejected("invalid file name")
    if os.path.isfile(dest) and _gh_local_blob_id(dest) != entry["blob"]:
        raise GhRejected(f"the library already has a different {entry['name']} -- left alone")
    compare_before_write(dest, data)
    with _file_meta_cache_lock:
        _file_meta_cache.clear()
    return dest


def _fu_run_cli(script_path, flag):
    """Run a component file's own --install / --uninstall and wait.
    Output goes to the log. Returns the exit code, None if it never ran."""
    try:
        proc = subprocess.Popen([_interp_for(script_path), script_path, flag],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except OSError as exc:
        log_event(f"Could not run {os.path.basename(script_path)} {flag}: {exc}", "err")
        return None
    try:
        for line in proc.stdout:
            log_event(line.rstrip("\n"), "info")
        proc.wait(timeout=SCRIPT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        proc.kill()
        log_event(f"{os.path.basename(script_path)} {flag} timed out ({SCRIPT_TIMEOUT_SEC}s), killed", "err")
        return None
    return proc.returncode


def _fu_wait_healthy(comp):
    deadline = time.time() + FU_START_TIMEOUT_SEC
    state = "unknown"
    while time.time() < deadline:
        state = systemctl_is_active(comp["service"])
        if state == "active" and (comp["port"] is None or port_open(comp["port"])):
            return True, state
        time.sleep(2)
    if state == "active":
        return False, f"running but not answering on port {comp['port']}"
    return False, state


def _fu_update_one(comp, row, new_path):
    """('updated' | 'skipped' | 'attention', note)."""
    name = comp["name"]
    target = resolve_installed_target(comp)
    if not script_has_self_uninstall(target):
        return "skipped", "installed file has no --uninstall -- left alone"
    _staged, old_name, _note, stage_err = stage_installed_copy_if_missing(comp)
    if stage_err:
        return "skipped", f"couldn't save a copy of the installed version ({stage_err}) -- left alone"
    old_path = os.path.join(LIB_SUBDIRS[comp["category"]], old_name)
    old_ver, new_ver = row["installed_version"], row["version"]

    _fu_set(current=f"{name}: uninstalling v{old_ver}")
    log_event(f"Full Update: {name}: uninstalling v{old_ver}", "info")
    rc = _fu_run_cli(comp["install_link"], "--uninstall")
    if rc != 0:
        log_event(f"Full Update: {name}: --uninstall exited {rc}; installing the new file anyway", "warn")
    quiet_forget(comp["service"])

    _fu_set(current=f"{name}: installing v{new_ver}")
    log_event(f"Full Update: {name}: installing {os.path.basename(new_path)}", "info")
    rc = _fu_run_cli(new_path, "--install")
    ok, state = _fu_wait_healthy(comp) if rc == 0 else (False, f"--install exited {rc}")
    if ok:
        log_event(f"Full Update: {name} updated v{old_ver} -> v{new_ver}", "ok")
        return "updated", f"v{old_ver} -> v{new_ver}"

    reason = f"v{new_ver} failed ({state})"
    log_event(f"Full Update: {name}: {reason} -- putting v{old_ver} back", "err")
    _fu_set(current=f"{name}: rolling back to v{old_ver}")
    rc = _fu_run_cli(old_path, "--install")
    ok, state = _fu_wait_healthy(comp) if rc == 0 else (False, f"--install exited {rc}")
    if ok:
        log_event(f"Full Update: {name} rolled back to v{old_ver}", "warn")
        return "skipped", f"{reason}; rolled back to v{old_ver}"
    log_event(f"Full Update: {name} NEEDS ATTENTION -- v{old_ver} didn't come back either ({state})", "err")
    return "attention", f"{reason}; putting v{old_ver} back also failed ({state}) -- not running"


def _fu_arm_instmon_guard(old_path):
    """A transient systemd timer, outside this process (which is about to
    restart): if the new instmon isn't answering on its port after
    FU_SELF_GUARD_SEC, reinstall the saved old copy."""
    check = (f"timeout 5 bash -c '</dev/tcp/127.0.0.1/{PORT}' || "
             f"{_interp_for(old_path)} {shlex.quote(old_path)} --install")
    for args in (["systemctl", "stop", "instmon-update-guard.timer", "instmon-update-guard.service"],
                 ["systemctl", "reset-failed", "instmon-update-guard.service"]):
        try:
            subprocess.run(args, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        r = subprocess.run(["systemd-run", "--quiet", "--collect", f"--on-active={FU_SELF_GUARD_SEC}",
                            "--unit=instmon-update-guard", "bash", "-c", check],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return r.returncode == 0, (r.stderr or "").strip()[:200]


def _fu_finish(error=""):
    _fu_set(running=False, phase="done", current="", error=error, banner=True)
    _fu_save()
    snap = full_update_snapshot()
    parts = [f"{len(snap['updated'])} updated"]
    if snap["skipped"]:
        parts.append(f"{len(snap['skipped'])} skipped")
    if snap["attention"]:
        parts.append(f"{len(snap['attention'])} NEED ATTENTION")
    if snap["scripts"]:
        parts.append(f"{len(snap['scripts'])} script(s) added to the library")
    level = "err" if (snap["attention"] or error) else ("warn" if snap["skipped"] else "ok")
    for r in snap["skipped"]:
        log_event(f"  skipped {r['name']}: {r['note']}", "warn")
    for r in snap["attention"]:
        log_event(f"  NEEDS ATTENTION {r['name']}: {r['note']}", "err")
    _gh_event("Full Update finished" + (f" ({error})" if error else "") + ": " + ", ".join(parts) + ".", level)


def _fu_run():
    _fu_set(phase="checking", current="reading GitHub's file list")
    log_event(f"Full Update started ({_gh_source_label()})", "info")
    try:
        entries, _sk = _gh_collect()
        rows = _fu_plan(list(_gh_last_cands))
    except GhRejected as exc:
        _fu_finish(f"couldn't read GitHub: {exc} -- nothing was changed")
        return
    with _gh_lock:
        _gh_state.update(phase="done", error=None, entries=entries,
                         checked_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
    scripts = [e for e in entries if e["category"] == "scripts" and e.get("status") in _GH_UPDATABLE]
    _fu_publish_plan(rows, scripts)
    plan = [r for r in rows if r["status"] == "update"]
    skipped = [{"name": r["name"], "note": r["note"]} for r in rows if r["status"] == "error"]
    _fu_set(skipped=list(skipped))
    if not plan and not scripts:
        log_event("Full Update: everything is already current -- nothing to do", "ok")
        _fu_finish()
        return

    done_scripts, staged = [], []
    _fu_set(phase="downloading")
    for row in plan:
        _fu_set(current=f"downloading {row['file']}")
        try:
            path = _fu_stage(row["entry"])
        except GhRejected as exc:
            log_event(f"Full Update: {row['name']}: {row['file']} skipped -- {exc}", "err")
            skipped.append({"name": row["name"], "note": f"{row['file']}: {exc}"})
            continue
        log_event(f"Full Update: downloaded and checked {row['file']}", "ok")
        staged.append((row, path))
    for entry in scripts:
        _fu_set(current=f"downloading {entry['name']}")
        try:
            msg, _lvl = _gh_apply(entry)
        except GhRejected as exc:
            log_event(f"Full Update: script {entry['name']} skipped -- {exc}", "err")
            skipped.append({"name": entry["name"], "note": str(exc)})
            continue
        log_event(f"Full Update: {msg}", "ok")
        done_scripts.append({"name": entry["name"], "note": "added to the Scripts library (not run)"})
    with _gh_lock:
        _gh_state["entries"] = [_gh_compare(dict(e)) for e in _gh_state["entries"]]
    _fu_set(skipped=list(skipped), scripts=done_scripts)
    if not staged:
        _fu_finish()
        return

    already_quiet = quiet_status()["on"]
    if not already_quiet:
        _fu_set(phase="quieting", current="pausing the web tools and watchdog")
        ok, msg, _lvl = quiet_start()
        if not ok:
            log_event(f"Full Update: {msg} -- updating without Quiet System", "warn")

    updated, attention = [], []
    instmon_job = None
    for row, path in staged:
        comp = next(c for c in COMPONENTS if c["category"] == row["category"])
        if comp["category"] == "instmon":
            instmon_job = (comp, row, path)
            continue
        _fu_set(phase="updating")
        with _running_installs_lock:
            _running_installs.add(comp["service"])
        try:
            outcome, note = _fu_update_one(comp, row, path)
        finally:
            with _running_installs_lock:
                _running_installs.discard(comp["service"])
        {"updated": updated, "skipped": skipped, "attention": attention}[outcome].append(
            {"name": comp["name"], "note": note})
        _fu_set(updated=list(updated), skipped=list(skipped), attention=list(attention))

    if quiet_status()["on"]:
        _fu_set(phase="restoring", current="restarting what was paused")
        quiet_restore()

    if instmon_job is None:
        _fu_finish()
        return

    comp, row, path = instmon_job
    _staged, old_name, _note, stage_err = stage_installed_copy_if_missing(comp)
    guard_ok, guard_err = (False, stage_err) if stage_err else \
        _fu_arm_instmon_guard(os.path.join(LIB_SUBDIRS["instmon"], old_name))
    if not guard_ok:
        skipped.append({"name": "instmon", "note": f"couldn't set up its rollback ({guard_err}) -- left alone"})
        _fu_set(skipped=list(skipped))
        _fu_finish()
        return
    # instmon is replaced in place by its own --install (an --uninstall
    # would stop this process before the new one went in). Results are
    # saved first: the restart ends this process and the new instmon
    # reads them back (full_update_resume_at_startup).
    _fu_set(phase="instmon", current=f"instmon: installing v{row['version']}",
            instmon_pending={"from": row["installed_version"], "to": row["version"]})
    _fu_save()
    log_event(f"Full Update: instmon: installing v{row['version']} -- this page reconnects when it restarts", "info")
    rc = _fu_run_cli(path, "--install")
    if rc != 0:
        try:
            subprocess.run(["systemctl", "stop", "instmon-update-guard.timer"],
                           capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        skipped.append({"name": "instmon", "note": f"--install exited {rc}; still on v{row['installed_version']}"})
        _fu_set(skipped=list(skipped), instmon_pending=None)
        _fu_finish()
        return
    # Its --install schedules the restart a couple of seconds out; still
    # here well after that means it didn't happen.
    time.sleep(45)
    skipped.append({"name": "instmon", "note": f"v{row['version']} installed; takes effect when instmon restarts"})
    _fu_set(skipped=list(skipped), instmon_pending=None)
    _fu_finish()


def _fu_run_bg():
    try:
        _fu_run()
    except Exception as exc:
        log_event(f"Full Update: unexpected error: {exc}", "err")
        if quiet_status()["on"]:
            quiet_restore()
        _fu_finish(f"unexpected error: {exc}")


def full_update_start():
    """(http_code, message, level)."""
    job = _diskimg_job_snapshot()
    if job and job.get("state") == "running":
        return 409, "A disk-image job is running -- wait for it to finish.", "warn"
    if quiet_status()["other"]:
        return 409, "Services are paused by a disk-image job -- wait for it to finish.", "warn"
    with _gh_lock:
        if _gh_state["phase"] == "checking" or _gh_state["busy"]:
            return 409, "A GitHub check or download is running -- wait for it to finish.", "warn"
    with _running_installs_lock:
        busy = sorted(_running_installs)
    with _running_scripts_lock:
        busy += sorted(_running_scripts)
    if busy:
        return 409, f"Wait for {', '.join(busy)} to finish first.", "warn"
    with _fu_lock:
        if _fu_state["running"]:
            return 409, "Full Update is already running.", "warn"
        _fu_state.update(running=True, phase="starting", current="", error="", banner=False,
                         updated=[], skipped=[], attention=[], scripts=[], instmon_pending=None)
    threading.Thread(target=_fu_run_bg, daemon=True).start()
    return 200, "Full Update started -- progress shows on the GitHub Updates card and in the log.", "info"


def full_update_preview():
    """After a GitHub check: work out what Full Update would do, so its
    button and list are ready. Same listing, versions already cached."""
    try:
        rows = _fu_plan(list(_gh_last_cands))
    except Exception as exc:
        log_event(f"Full Update preview failed: {exc}", "warn")
        return
    with _gh_lock:
        scripts = [e for e in _gh_state["entries"] if e["category"] == "scripts" and e.get("status") in _GH_UPDATABLE]
    _fu_publish_plan(rows, scripts)


def full_update_resume_at_startup():
    try:
        with open(_FU_STATE_PATH) as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        return
    if not isinstance(saved, dict):
        return
    with _fu_lock:
        for key in ("phase", "error", "banner", "updated", "skipped", "attention", "scripts", "instmon_pending"):
            if key in saved:
                _fu_state[key] = saved[key]
        _fu_state["running"] = False
    pending = saved.get("instmon_pending")
    if pending:
        with _fu_lock:
            if _version_sort_key(VERSION) == _version_sort_key(str(pending.get("to"))):
                _fu_state["updated"].append({"name": "instmon", "note": f"v{pending.get('from')} -> v{VERSION}"})
            else:
                _fu_state["skipped"].append({"name": "instmon", "note": f"the new version didn't take; running v{VERSION}"})
            _fu_state["instmon_pending"] = None
        _fu_finish()
    elif saved.get("phase") not in ("done", ""):
        _fu_finish("instmon restarted in the middle of the update")


def full_update_dismiss():
    _fu_set(banner=False)
    _fu_save()


def _fu_status_payload():
    snap = full_update_snapshot()
    return {"quiet": quiet_status(), "full_update": snap}


def run_script_bg (script_path ,script_name ,env_overrides =None ):

    if env_overrides :
        shown =" ".join (f"{k }={v }"for k ,v in env_overrides .items ())
        log_event (f"Running script: {script_name } ({shown })","info")
    else :
        log_event (f"Running script: {script_name }","info")
    try :
        env =os .environ .copy ()
        if env_overrides :
            env .update (env_overrides )
        proc =subprocess .Popen (
        ["bash",script_path ],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,
        text =True ,bufsize =1 ,env =env ,
        )
        for line in proc .stdout :
            log_event (line .rstrip ("\n"),"info")
        proc .wait (timeout =SCRIPT_TIMEOUT_SEC )
        if proc .returncode ==0 :
            log_event (f"Script finished OK: {script_name }","ok")
        else :
            log_event (f"Script exited {proc .returncode }: {script_name }","err")
    except subprocess .TimeoutExpired :
        proc .kill ()
        log_event (f"Script timed out ({SCRIPT_TIMEOUT_SEC }s), killed: {script_name }","err")
    except Exception as exc :
        log_event (f"Script failed to run: {script_name }: {exc }","err")
    finally :
        with _running_scripts_lock :
            _running_scripts .discard (script_name )


def run_self_install_bg (script_path ,script_name ,comp ):

    log_event (f"Installing {script_name } ({comp ['name']}) -- running its own --install...","info")
    try :
        proc =subprocess .Popen (
        [_interp_for (script_path ),script_path ,"--install"],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,
        text =True ,bufsize =1 ,
        )
        for line in proc .stdout :
            log_event (line .rstrip ("\n"),"info")
        proc .wait (timeout =SCRIPT_TIMEOUT_SEC )
        if proc .returncode ==0 :
            log_event (f"Install finished OK: {script_name } ({comp ['name']})","ok")
            quiet_forget (comp ["service"])
        else :
            log_event (f"Install exited {proc .returncode }: {script_name } ({comp ['name']})","err")
    except subprocess .TimeoutExpired :
        proc .kill ()
        log_event (f"Install timed out ({SCRIPT_TIMEOUT_SEC }s), killed: {script_name } ({comp ['name']})","err")
    except Exception as exc :
        log_event (f"Install failed to run: {script_name } ({comp ['name']}): {exc }","err")
    finally :
        with _running_installs_lock :
            _running_installs .discard (comp ["service"])


def stage_installed_copy_if_missing (comp ):

    target =resolve_installed_target (comp )
    target_hash =file_sha256 (target )
    if target_hash is None :
        return False ,None ,"",f"could not hash the installed {comp ['name']} file at {target }"

    lib_dir =LIB_SUBDIRS [comp ["category"]]
    ensure_dirs ()
    try :
        existing_names =os .listdir (lib_dir )
    except OSError as exc :
        return False ,None ,"",f"could not read the {comp ['category']} library dir: {exc }"

    for existing_name in existing_names :
        full =os .path .join (lib_dir ,existing_name )
        if os .path .isfile (full )and file_sha256 (full )==target_hash :
            return False ,existing_name ,f"already present in the library as {existing_name }",None 

    base_name =os .path .basename (target )
    candidate =base_name 
    n =2 
    while os .path .exists (os .path .join (lib_dir ,candidate )):
        stem ,ext =os .path .splitext (base_name )
        candidate =f"{stem }_{n }{ext }"
        n +=1 

    try :
        shutil .copy2 (target ,os .path .join (lib_dir ,candidate ))
    except OSError as exc :
        return False ,None ,"",f"could not stage a library copy before uninstall: {exc }"

    log_event (f"Staged installed {comp ['name']} file into the library as {candidate } before uninstall","info")
    return True ,candidate ,f"staged a library copy as {candidate }",None 


def run_self_uninstall_bg (comp ):

    script_path =comp ["install_link"]
    log_event (f"Uninstalling {comp ['name']} -- running its own --uninstall...","info")
    try :
        proc =subprocess .Popen (
        [_interp_for (script_path ),script_path ,"--uninstall"],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,
        text =True ,bufsize =1 ,
        )
        for line in proc .stdout :
            log_event (line .rstrip ("\n"),"info")
        proc .wait (timeout =SCRIPT_TIMEOUT_SEC )
        if proc .returncode ==0 :
            log_event (f"Uninstall finished OK: {comp ['name']}","ok")
            quiet_forget (comp ["service"])
        else :
            log_event (f"Uninstall exited {proc .returncode }: {comp ['name']}","err")
    except subprocess .TimeoutExpired :
        proc .kill ()
        log_event (f"Uninstall timed out ({SCRIPT_TIMEOUT_SEC }s), killed: {comp ['name']}","err")
    except Exception as exc :
        log_event (f"Uninstall failed to run: {comp ['name']}: {exc }","err")
    finally :
        with _running_installs_lock :
            _running_installs .discard (comp ["service"])


BADGE_BY_STATE ={
"active":("RUNNING","b-run"),
"inactive":("STOPPED","b-stop"),
"failed":("FAILED","b-stop"),
"unknown":("UNKNOWN","b-src"),
}


def esc (s ):

    return html .escape (str (s ),quote =True )


def render_components_html (components ,library =None ):
    cards =[]
    for c in components :
        label ,cls =BADGE_BY_STATE .get (c ["state"],("UNKNOWN","b-src"))
        if c ["port"]is None :
            port_note ="no web UI"
        else :
            port_note =f'port {c ["port"]}'if c ["listening"]else f'port {c ["port"]} (not listening)'


        is_self =c ["category"]=="instmon"

        uninstall_btn =(
        f'<button data-action="uninstall" data-service="{c ["service"]}" '
        f'data-category="{c ["category"]}" data-name="{esc (c ["name"])}"'
        +(" disabled class=\"b-self-locked\" title=\"instmon cannot uninstall itself\""if is_self else "")
        +'>Uninstall</button>'
        if c ["installed"]else ""
        )

        if c ["port"]is None :
            go_btn =""
        else :
            go_disabled =""if c ["listening"]else " disabled"
            go_cls =" class=\"b-go\""if c ["listening"]else ""
            go_btn =(
            f'<button data-action="go" data-port="{c ["port"]}"{go_cls}{go_disabled}>Go</button>'
            )

        nested_lib_html =""
        if library is not None :
            group =_LIBRARY_GROUPS_BY_CATEGORY .get (c ["category"])
            if group is not None :
                title ,_cat ,action_label =group
                nested_lib_html =render_library_group_html (
                title ,c ["category"],library .get (c ["category"],[]),action_label ,nested =True ,
                )

        cards .append (f"""
  <div class="card">
    <div class="row">
      <b>{c ['name']}</b>
      <span class="ver">v{c ['version']}</span>
      <span class="badge {cls }">{label }</span>
      <span class="small" style="color:var(--grn)">{port_note }</span>
      <span class="muted small">{c ['service']}</span>
    </div>
    <div class="row btn-row">
      <button class="b-start{' b-self-locked'if is_self else ''}" data-action="start" data-service="{c ['service']}" data-name="{esc (c ['name'])}"{' disabled title="instmon cannot start/restart itself from its own panel"'if is_self else ''}>Start</button>
      <button{' class="b-self-locked" disabled title="instmon cannot stop itself"'if is_self else ''} data-action="stop" data-service="{c ['service']}" data-name="{esc (c ['name'])}">Stop</button>
      {uninstall_btn }
      {go_btn }
    </div>
    {nested_lib_html }
  </div>""")
    return "".join (cards )


def render_library_group_html (title ,category ,entries ,action_label ,nested =False ):
    rows =[]
    for e in entries :


        name =esc (e ["name"])

        if e ["installed"]is True :
            badge ,bcls ="INSTALLED","b-inst"
        elif e ["installed"]is False :
            badge ,bcls ="ALT","b-src"
        else :
            badge ,bcls ="READY","b-inst"


        installer_attr =""
        interactive_only =False 
        if category =="scripts":
            if is_interactive_only_script (e ["name"]):
                interactive_only =True 
                run_label ,run_btn_style ="",""
            elif is_uninstaller_script (e ["name"]):
                run_label ="Run Uninstall"
                run_btn_style =' class="b-del"'
                installer_attr =' data-uninstaller="1"'
            elif is_installer_script (e ["name"]):
                run_label ="Install"
                run_btn_style =' style="background:var(--grn);color:#070b10;border-color:var(--grn)"'
                installer_attr =' data-installer="1"'
            else :
                run_label ="Run Script"
                run_btn_style =""
        elif category =="config":
            run_label ,run_btn_style ="Install Config",""
        else :


            run_label ,run_btn_style ="Install",""

        run_btn =(
        '<span class="small muted" title="Menu-driven script -- run by hand over SSH instead">Interactive -- run via SSH</span>'
        if interactive_only else 
        f'<button data-action="{action_label }" data-category="{category }" data-name="{name }"{installer_attr }{run_btn_style }>{run_label }</button>'
        )

        rows .append (f"""
    <div class="librow">
      <div class="librow-top">
        <span class="ver">{esc (e ['version'])}</span>
        <span>{name }</span>
        <span class="badge {bcls }">{badge }</span>
      </div>
      <div class="librow-actions">
        {run_btn }
        <button data-action="edit" data-category="{category }" data-name="{name }">Edit</button>
        <button data-action="download" data-category="{category }" data-name="{name }">Download</button>  <!-- [PHASE 3] -->
        <button class="b-del" data-action="delete" data-category="{category }" data-name="{name }">Delete</button>
      </div>
      <div class="librow-bot small muted">
        <span>Source: library</span>
        <span>&middot;</span>
        <span>{esc (e ['mtime'])}</span>
        <span>&middot;</span>
        <span>{esc (e ['size'])}</span>
      </div>
    </div>""")
    if not rows :
        rows .append ('<div class="small muted" style="padding:.4rem .2rem">-- empty --</div>')
    card_cls ="card libgrp libgrp-nested collapsed"if nested else "card libgrp collapsed"
    # Per-category upload widget -- replaces the old single global "Upload"
    # card (with its category dropdown). Each library group gets its own
    # scoped file input + button, since the category is already fixed by
    # which group this is; no dropdown needed. Lives inside .librows (so
    # it collapses/expands with the rest of the group) and carries its
    # own msg span rather than sharing one global #upmsg.
    upload_html =f"""
    <div class="librow libgrp-upload">
      <input type="file" id="file-{category}" data-category="{category}">
      <button data-action="upload" data-category="{category}">Upload &amp; stage</button>
      <span id="upmsg-{category}" class="small muted"></span>
    </div>"""
    return f"""
  <div class="{card_cls}" data-libcat="{category}">
    <div class="libgrp-hdr">
      <b>{esc (title )}</b>
      <button class="lib-toggle" data-action="toggle_lib" data-category="{category}">Show</button>
    </div>
    {_gh_group_html (category )}
    <div class="librows">
    {''.join (rows )}
    {upload_html }
    </div>
  </div>"""


_LIBRARY_GROUPS: list [tuple [str ,str ,str ]]=[
    ("Dashboard","dashboard","install"),
    ("SysMon","sysmon","install"),
    ("wifimon","wifimon","install"),
    ("44helper","44helper","install"),
    ("Watchdog","watchdog","install"),
    ("instmon","instmon","install"),
    ("Scripts (.sh)","scripts","run_script"),
    ("Configuration","config","install_config"),
]

_LIBRARY_GROUPS_BY_CATEGORY: dict [str ,tuple [str ,str ,str ]]={
    category :(title ,category ,action_label )
    for title ,category ,action_label in _LIBRARY_GROUPS
    if category in INSTALLABLE_CATEGORIES 
}

_ORPHAN_LIBRARY_GROUPS: list [tuple [str ,str ,str ]]=[
    (title ,category ,action_label )
    for title ,category ,action_label in _LIBRARY_GROUPS
    if category not in INSTALLABLE_CATEGORIES 
]


# ---- Router quick link: gateway detection (Stage 1 helpers) ----------------
# Nothing here touches the network at import time. parse_default_gateway()
# takes /proc/net/route text, probe_router_ui() takes the ip/schemes/timeout,
# and the cache takes an injectable prober and clock, so each piece can be
# tested without a live router.
_RTF_UP =0x0001
_RTF_GATEWAY =0x0002
_RTF_REJECT =0x0200
ROUTER_PROBE_TIMEOUT =1.5
ROUTER_PROBE_TTL =30.0
_ROUTER_SCHEMES =(("http",80),("https",443))


def _route_hex_to_ip(value):
    # /proc/net/route prints each address as the kernel's raw u32 in host
    # byte order; packing it back in native order restores the wire bytes
    # on little- and big-endian machines alike.
    return socket.inet_ntoa(struct.pack("=L", int(value, 16)))


def parse_default_gateway(route_text):
    """Return the gateway in use from /proc/net/route text, or None.

    Only up, non-reject default routes with a real gateway count, so a
    VPN device-only default (WireGuard, gateway 0.0.0.0) is ignored. With
    several candidates the lowest metric wins, ties going to the first
    listed. /proc/net/route is the main table, so fwmark policy tables
    are not involved. Result: {"ip", "iface", "lan"} where lan is the
    interface's connected network holding the gateway as "a.b.c.d/nn",
    or None if no such route is listed.
    """
    defaults = []
    connected = []
    for line in (route_text or "").splitlines():
        cols = line.split()
        if len(cols) < 8:
            continue
        try:
            # The header row fails the hex parse here and is skipped.
            iface = cols[0]
            dest = _route_hex_to_ip(cols[1])
            gw = _route_hex_to_ip(cols[2])
            flags = int(cols[3], 16)
            metric = int(cols[6])
            mask = _route_hex_to_ip(cols[7])
        except (ValueError, struct.error, OSError):
            continue
        if not flags & _RTF_UP or flags & _RTF_REJECT:
            continue
        if dest == "0.0.0.0" and mask == "0.0.0.0":
            if flags & _RTF_GATEWAY and gw != "0.0.0.0":
                defaults.append((metric, len(defaults), iface, gw))
        elif gw == "0.0.0.0":
            connected.append((iface, dest, mask))
    if not defaults:
        return None
    _metric, _order, iface, gw = min(defaults)
    gw_addr = ipaddress.ip_address(gw)
    best = None
    for c_iface, c_dest, c_mask in connected:
        if c_iface != iface:
            continue
        try:
            net = ipaddress.ip_network(f"{c_dest}/{c_mask}", strict=False)
        except ValueError:
            continue
        if gw_addr in net and (best is None or net.prefixlen > best.prefixlen):
            best = net
    return {"ip": gw, "iface": iface, "lan": str(best) if best else None}


def read_default_gateway():
    try:
        with open("/proc/net/route") as fh:
            return parse_default_gateway(fh.read())
    except OSError:
        return None


def client_on_gateway_lan(client_ip, gw):
    """True only if client_ip is inside the gateway interface's network.

    Unknown network, unparseable address, or a loopback / port-forwarded /
    remote viewer all give False, so the caller hides the button.
    """
    if not gw or not gw.get("lan"):
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return addr in ipaddress.ip_network(gw["lan"])
    except ValueError:
        return False


def probe_router_ui(ip, timeout=ROUTER_PROBE_TIMEOUT, schemes=_ROUTER_SCHEMES):
    """Return the router's web UI URL on ip, or None.

    Tries each (scheme, port) in order with a plain GET / and never reads
    the body. 200-399 counts as displayable, and so do 401/403 since a
    login-protected UI still renders in the browser. A refused connection,
    404, 5xx or non-HTTP reply moves on to the next scheme; a timeout ends
    the probe at once (a dead or firewalled host would only time out again).
    HTTPS skips certificate checks -- this is reachability only and sends
    nothing but the GET.
    """
    for scheme, port in schemes:
        conn = None
        try:
            if scheme == "https":
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                conn = http.client.HTTPSConnection(ip, port, timeout=timeout, context=ctx)
            else:
                conn = http.client.HTTPConnection(ip, port, timeout=timeout)
            conn.request("GET", "/", headers={
                "User-Agent": "instmon-router-probe",
                "Accept": "text/html",
                "Connection": "close",
            })
            status = conn.getresponse().status
        except TimeoutError:
            return None
        except (OSError, http.client.HTTPException):
            continue
        finally:
            if conn is not None:
                conn.close()
        if 200 <= status < 400 or status in (401, 403):
            default_port = 443 if scheme == "https" else 80
            if port == default_port:
                return f"{scheme}://{ip}/"
            return f"{scheme}://{ip}:{port}/"
    return None


_router_probe_cache = {}
_router_probe_lock = threading.Lock()


def cached_router_probe(ip, ttl=ROUTER_PROBE_TTL, prober=probe_router_ui, clock=time.monotonic):
    """probe_router_ui() with a per-ip cache, negative results included.

    A dead gateway costs a full probe timeout, so a miss is cached for the
    same ttl as a hit -- the browser can poll freely without hammering the
    router. The probe runs outside the lock; two simultaneous first calls
    may both probe, which is harmless.
    """
    now = clock()
    with _router_probe_lock:
        hit = _router_probe_cache.get(ip)
        if hit and now - hit[0] < ttl:
            return hit[1]
    url = prober(ip)
    stamp = clock()
    with _router_probe_lock:
        _router_probe_cache[ip] = (stamp, url)
        for old_ip in [k for k, v in _router_probe_cache.items() if stamp - v[0] > ttl * 10]:
            del _router_probe_cache[old_ip]
    return url


ROUTER_LINK ="@router"

QUICKLINKS =[
# (label, target, enabled) -- shortcuts. target is a str path (reverse-proxy
# shortcut on plain HTTP/port 80), an int port (opened as http://host:port,
# same as a component's Go button), or ROUTER_LINK -- the one dynamic entry:
# it ships hidden and pollGateway() reveals it only while the gateway in use
# is known, on the viewer's LAN, and serving a page (see /api/gateway).
# No service/port tracking here on purpose: these aren't COMPONENTS entries,
# just fixed links. Display order here is the order shown in the row.
("Allmon3","/allmon3",True ),
("DVSwitch","/dvswitch",True ),
("Cockpit",9090 ,True ),
("USRP2M17","/m17",True ),
("Router",ROUTER_LINK,True ),
]


def render_quicklinks_html ():
    btns =[]
    for label ,target ,enabled in QUICKLINKS :
        if target ==ROUTER_LINK :
            # Manages its own visibility (CSS .b-router + JS), so `enabled`
            # doesn't apply. No href/url until pollGateway() supplies one.
            btns .append (
            f'<button id="router-link" data-action="router" class="b-go b-router">{esc (label )}</button>'
            )
            continue 
        cls =" class=\"b-go\""if enabled else ""
        disabled =""if enabled else " disabled"
        attr ="data-port"if isinstance (target ,int )else "data-path"
        btns .append (
        f'<button data-action="go" {attr }="{target }"{cls}{disabled}>{esc (label )}</button>'
        )
    return "".join (btns )


def render_library_html (library ):
    """Render only the orphan (non-component) library groups -- scripts
    and config -- for the standalone library section. The matched groups
    (dashboard, sysmon, etc.) are rendered nested inside their component
    cards by render_components_html() instead."""
    return "".join (
    render_library_group_html (title ,category ,library [category ],action_label )
    for title ,category ,action_label in _ORPHAN_LIBRARY_GROUPS 
    )



_CSS_BASE = """:root{
  /* ── palette matched to asl_dvs_dashboard ── */
  --bg:#0d1117; --surface:#161e2e; --surface2:#1e2a3f;
  --border:#2e4060; --border2:#3a5278;
  --amber:#ffd040; --amber-dim:#6b4800;
  --green:#00ffb0; --green-dim:#005538;
  --red2:#ff3d5a; --red-dim:#6b0e20;
  --blue:#22d4ff; --blue-dim:#083a58;
  --text:#d0dff0; --text-bright:#f0f8ff;
  --mono:Arial,Helvetica,sans-serif;
  --sans:Arial,Helvetica,sans-serif;
  /* aliases -- kept so existing var(--cyn)/var(--grn)/var(--yel)/var(--red)
     references sprinkled through inline styles and JS-built markup pick
     up the matched palette without every call site needing a rename */
  --panel:var(--surface); --line:var(--border2);
  --fg:var(--text); --muted:#ffffff;
  --cyn:var(--blue); --grn:var(--green); --yel:var(--amber); --red:var(--red2);
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);
  font-size:.9rem;line-height:1.5;min-height:100vh;padding-bottom:2.5rem}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
"""

_CSS_LAYOUT = """
/* ── Title bar ── */
header{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--amber);padding:.5rem 1rem;
  display:flex;align-items:center;justify-content:space-between;gap:.5rem;
  position:sticky;top:0;z-index:100;
  box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
.hdr-left{display:flex;flex-direction:column;min-width:0}
.hdr-right{display:flex;flex-direction:column;align-items:flex-end;flex-shrink:0;white-space:nowrap}
.logo{font-family:var(--mono);font-size:1.15rem;font-weight:700;color:var(--amber);
  letter-spacing:.08em;text-shadow:0 0 10px rgba(255,208,64,.9),0 0 30px rgba(255,208,64,.5),0 0 60px rgba(255,208,64,.2)}
.logo-sub{font-size:.68rem;letter-spacing:.18em;text-transform:uppercase;color:#5a7898;margin-top:.15rem}
  letter-spacing:.06em;text-shadow:0 0 8px rgba(255,208,64,.5)}
.hdr-meta{font-family:var(--mono);font-size:.68rem;color:#5a7898;letter-spacing:.04em;margin-top:.15rem}

/* ── Layout ── */
.wrap{max-width:860px;margin:0 auto;padding:1rem;display:flex;flex-direction:column;gap:.55rem}
.hdr{color:#5a7898;font-family:var(--mono);font-weight:700;font-size:.7rem;
  letter-spacing:.24em;text-transform:uppercase;margin:1.2rem 0 .45rem;
  padding-bottom:.25rem;border-bottom:1px solid var(--border)}
"""

_CSS_COMPONENTS = """.card{background:var(--surface);border:1px solid var(--border2);border-radius:0 6px 6px 6px;
  padding:.7rem .9rem;margin-bottom:.6rem;box-shadow:0 4px 20px rgba(0,0,0,.35)}
.row{display:flex;flex-wrap:wrap;gap:.4rem .9rem;align-items:center}
.badge{font-family:var(--mono);font-size:.66rem;padding:.08rem .5rem;border-radius:4px;
  border:1px solid;font-weight:700;letter-spacing:.05em;text-transform:uppercase}
.b-inst{color:var(--grn);border-color:var(--green-dim);background:rgba(0,255,176,.07);text-shadow:0 0 8px rgba(0,255,176,.4)}
.b-src{color:var(--muted);border-color:var(--border2)}
.b-run{color:var(--grn);border-color:var(--green-dim);background:rgba(0,255,176,.07);text-shadow:0 0 8px rgba(0,255,176,.4)}
.b-stop{color:var(--red);border-color:var(--red-dim);background:rgba(255,61,90,.08);text-shadow:0 0 8px rgba(255,61,90,.4)}
.b-start{color:var(--grn);border-color:var(--green-dim);background:rgba(0,255,176,.07);text-shadow:0 0 8px rgba(0,255,176,.4)}
button{font-family:var(--mono);font-size:.8rem;font-weight:700;letter-spacing:.04em;
  text-transform:uppercase;background:transparent;color:var(--cyn);
  border:1px solid var(--blue-dim);border-radius:4px;padding:.32rem .85rem;cursor:pointer;
  transition:all .14s}
button:hover{filter:brightness(1.5);box-shadow:0 0 10px currentColor}
button:active{transform:scale(.95)}
button.b-del{color:var(--red);border-color:var(--red-dim)}
button:disabled{opacity:.4;cursor:default;filter:none;box-shadow:none}
button.b-danger{color:var(--red);border-color:var(--red2);background:rgba(255,61,90,.1);
  text-shadow:0 0 8px rgba(255,61,90,.5)}
button.b-comms{color:var(--amber);border-color:var(--amber-dim);background:rgba(255,208,64,.08);
  text-shadow:0 0 8px rgba(255,208,64,.4)}
button.b-go{color:var(--amber);border-color:var(--amber-dim);background:rgba(255,61,90,.15);
  text-shadow:0 0 8px rgba(255,208,64,.4)}
button.b-self-locked{text-decoration:line-through}
/* Router quick link: hidden until pollGateway() confirms a usable gateway.
   Base display:none + .open, the same pattern as the overlays -- never a
   [hidden] attribute or .hidden class that a later button rule could beat. */
button.b-router{display:none}
button.b-router.open{display:inline-block}
.danger-card{border-color:var(--red-dim)}
.muted{color:var(--muted)}
.small{font-size:.74rem}
.btn-row{margin-top:.5rem;padding-top:.5rem;border-top:1px solid var(--border)}
.no-confirm-banner{font-family:var(--mono);font-size:.72rem;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;color:var(--red);border:1px solid var(--red-dim);border-radius:4px;
  background:rgba(255,61,90,.08);padding:.35rem .7rem;margin-bottom:.6rem;text-shadow:0 0 8px rgba(255,61,90,.4)}
"""

_CSS_LIBRARY = """.libgrp{margin-bottom:.9rem}
.libgrp-hdr{display:flex;align-items:center;justify-content:space-between;gap:.6rem;margin-bottom:.3rem;color:var(--cyn)}
.libgrp.collapsed .librows{display:none}
.lib-toggle{font-size:.75rem;padding:.2rem .6rem}
.librow{display:flex;flex-direction:column;gap:.25rem;
  padding:.55rem .7rem;border-bottom:1px solid var(--border);transition:background .1s}
.librow:last-child{border-bottom:none}
.librow:hover{background:var(--surface2)}
.librow-top{display:flex;flex-wrap:wrap;gap:.4rem .9rem;align-items:center}
.librow-actions{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
.librow-bot{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center}
.ver{font-family:var(--mono);color:var(--yel);font-weight:700;min-width:5.5rem;text-shadow:0 0 6px rgba(255,208,64,.35)}
input[type=file]{color:var(--muted);font-size:.78rem;max-width:100%}
/* Library card nested inside its component's card (see
   render_components_html's nested_lib_html): indented as a subordinate
   block rather than a full sibling card, so it doesn't read as a
   second independent card boxed inside the first one. */
.libgrp-nested{margin:1.3rem 0 0 1.1rem;background:var(--bg);
  border:1px solid var(--border);border-left:2px solid var(--border2);
  border-radius:0 4px 4px 0;padding:.5rem .6rem .1rem}
.libgrp-nested .libgrp-hdr{font-size:.85rem}
/* Per-category upload row appended inside each library group's .librows
   (replaces the old standalone global "Upload" card). Dashed top border
   sets it apart from the real version entries above it, since it's an
   action row rather than a library entry. */
.libgrp-upload{flex-direction:row;flex-wrap:wrap;align-items:center;gap:.5rem;
  border-top:1px dashed var(--border2);border-bottom:none;padding-top:.6rem}
.libgrp-upload input[type=file]{flex:1;min-width:8rem}
/* GitHub status rows: sit between a library group's header and its
   rows so they stay visible while the group is collapsed. */
.gh-rows{display:flex;flex-direction:column;gap:.3rem;margin:.1rem 0 .4rem}
.gh-row{display:flex;flex-wrap:wrap;gap:.35rem .6rem;align-items:center;font-size:.78rem}
.gh-tag{font-family:var(--mono);font-size:.7rem;padding:.1rem .45rem;border-radius:3px;border:1px solid var(--border2);color:var(--muted)}
.gh-tag.gh-upd{color:var(--grn);border-color:var(--grn)}
.gh-tag.gh-warn{color:var(--yel);border-color:var(--yel)}
.gh-tag.gh-err{color:var(--red);border-color:var(--red-dim)}
.gh-row button{font-size:.75rem;padding:.2rem .6rem}
/* v2.37.0 Quiet System + Full Update */
.fu-banner{border:1px solid var(--amber-dim);background:rgba(255,208,64,.08);color:var(--yel);
  border-radius:6px;padding:.55rem .8rem;margin-bottom:.6rem;display:flex;flex-wrap:wrap;
  gap:.4rem .9rem;align-items:center;font-family:var(--mono);font-size:.8rem}
.fu-banner.ok{border-color:var(--green-dim);background:rgba(0,255,176,.06);color:var(--grn)}
.fu-banner.err{border-color:var(--red-dim);background:rgba(255,61,90,.08);color:var(--red)}
.fu-banner ul{margin:.2rem 0 0 1.1rem;color:var(--fg)}
.fu-table{width:100%;border-collapse:collapse;margin-top:.45rem;font-size:.78rem}
.fu-table td{padding:.22rem .4rem;border-top:1px solid var(--border)}
#fu-progress{font-family:var(--mono);font-size:.8rem;color:var(--cyn);margin-top:.35rem}
"""

_CSS_LOG = """#log{background:#070b10;border:1px solid var(--border2);border-radius:0 6px 6px 6px;
  padding:.6rem .8rem;margin-top:.5rem;white-space:pre-wrap;
  font-family:var(--mono);font-size:.78rem;max-height:450px;overflow:auto;display:block;
  box-shadow:0 4px 20px rgba(0,0,0,.35)}
.log-ok{color:var(--grn)}
.log-err{color:var(--red)}
.log-warn{color:var(--yel)}

/* Feedback popup -- centered overlay card, auto-dismisses itself.
   Replaces the old bottom-right corner toast stack. Missing selectors
   here (#popup-overlay / #popup-overlay.open) restored -- same
   display:none-base + .open{display:flex} pattern already used
   correctly by #login-screen below; without them this whole overlay
   never actually got position:fixed/backdrop/centering and just sat
   inline in the page instead of acting as a modal. */
#popup-overlay{
  display:none; position:fixed; inset:0; z-index:1200;
  align-items:center; justify-content:center;
  background:rgba(0,0,0,.55);
}
#popup-overlay.open{display:flex}
.popup-box{
  background:#1a2438; border:1px solid var(--border2); border-radius:8px;
  padding:1rem 1.6rem; font-family:var(--mono); font-size:.92rem; line-height:1.4;
  color:var(--text-bright); box-shadow:0 8px 40px rgba(0,0,0,.8);
  max-width:80vw; text-align:center;
  opacity:0; transform:scale(.92); transition:opacity .16s ease, transform .16s ease;
}
.popup-show{opacity:1; transform:scale(1)}
.popup-ok{border-color:var(--green-dim); color:var(--grn); box-shadow:0 0 24px rgba(0,255,176,.25)}
.popup-warn{border-color:var(--amber-dim); color:var(--yel); box-shadow:0 0 24px rgba(255,208,64,.25)}
.popup-err{border-color:var(--red-dim); color:var(--red); box-shadow:0 0 24px rgba(255,61,90,.25)}
.popup-info{border-color:var(--blue-dim); color:var(--cyn); box-shadow:0 0 24px rgba(34,212,255,.25)}

"""

_CSS_EDITOR = """/* Editor Overlay (Stage 8/9, Library Card Rework Plan) -- replaces
   the old centered-dialog editor pattern with sysmon's full-screen
   uf-overlay/uf-box shape (confirmed by reading
   sysmon_v6_2_3_20260808.py: #uf-overlay/#uf-box/#uf-hdr/#uf-toolbar/
     - var(--teal) -> var(--cyn) throughout; instmon doesn't define
       --teal, and --cyn is already this file's accent color for the
       old editor's header text, so this keeps the same visual role
       instmon already had rather than introducing a new color.
     - No #uf-promoted-bar and no Restart/Reload-Daemon buttons --
       those are unit-file-specific concepts (systemd override paths,
       daemon-reload) that don't apply to instmon's generic
       library-file editor.
     - Dropped sysmon's position:sticky + compensating 3.5rem
       textarea top-padding on #uf-hdr/#uf-toolbar: that combination
       exists in sysmon because its editor is reused in several
       scroll contexts; instmon's #uf-box is a plain flex column
       (header, toolbar, then a flex:1 textarea) where the header and
       toolbar are already pinned above the one scrollable child by
       the flex layout itself, so sticky positioning has nothing to
       do and the padding hack it was compensating for isn't needed
       either.
*/
#uf-overlay{
  display:none; position:fixed; inset:0;
  background:rgba(0,0,0,.8); backdrop-filter:blur(4px);
  z-index:500; align-items:center; justify-content:center; padding:0;
}
#uf-overlay.open{display:flex}
#uf-box{
  background:var(--surface); border:1px solid var(--border2);
  border-radius:0; width:100vw; height:100vh; max-width:none;
  height:100dvh; max-height:100dvh;
  display:flex; flex-direction:column; box-shadow:none;
}
#uf-hdr{
  background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--cyn); padding:.55rem 1rem;
  display:flex; align-items:center; justify-content:space-between;
  flex-shrink:0; box-shadow:0 2px 0 rgba(34,212,255,.15);
}
#uf-title{
  font-family:var(--mono); font-size:.858rem;
  color:var(--cyn); letter-spacing:.08em;
  text-shadow:0 0 8px rgba(34,212,255,.4);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
#uf-close{
  font-family:var(--mono); font-size:.858rem; color:var(--fg);
  cursor:pointer; padding:.15rem .55rem; border:1px solid var(--border2);
  border-radius:3px; transition:all .14s;
}
#uf-toolbar{
  display:flex; align-items:center; gap:.4rem;
  padding:.38rem 1rem; background:#131c2d;
  border-bottom:1px solid var(--border); flex-shrink:0;
}
#uf-path{
  font-family:var(--mono); font-size:.715rem; color:var(--fg);
  flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
#uf-textarea{
  flex:1; background:#0a1020; color:#c8d8e8;
  font-family:var(--mono); font-size:.836rem; line-height:1.65;
  border:none; outline:none; padding:.8rem 1rem;
  resize:none; tab-size:4; white-space:pre; overflow:auto; min-height:0;
}
/* Toolbar Copy button (moved here from the header row, v2.14.0) --
   small and understated relative to Save, since Save is the primary
   action; sits next to the file path/status rather than beside Save
   so it doesn't read as a second equally-weighted primary action. */
#uf-toolbar button{
  font-family:var(--mono); font-size:.7rem; color:var(--fg);
  cursor:pointer; padding:.1rem .5rem; border:1px solid var(--border2);
  border-radius:3px; background:transparent; flex-shrink:0;
}
"""

_CSS_LOGIN = """
#logout-btn{margin-top:.3rem;font-size:.68rem;padding:.2rem .6rem}

/* Login overlay -- base display:none + .open{display:flex} (never a
   .hidden class) so a bare class rule can't lose a specificity fight
   against this ID selector regardless of source order. */
#login-screen{display:none;position:fixed;inset:0;z-index:9999;
  align-items:center;justify-content:center;
  background:rgba(5,8,14,.88);backdrop-filter:blur(3px)}
#login-screen.open{display:flex}
#login-card{background:var(--panel);border:1px solid var(--line);
  border-radius:8px;padding:1.4rem 1.6rem;min-width:260px;max-width:90vw;
  box-shadow:0 8px 40px rgba(0,0,0,.8);text-align:center}
#login-card h2{font-family:var(--mono);color:var(--amber);font-size:1.05rem;
  letter-spacing:.06em;margin-bottom:1rem;text-shadow:0 0 8px rgba(255,208,64,.5)}
#login-card form{display:flex;flex-direction:column;gap:.6rem}
#login-pw{font-family:var(--mono);font-size:.9rem;background:#0a1020;
  color:var(--fg);border:1px solid var(--line);border-radius:4px;
  padding:.45rem .6rem;outline:none}
#login-pw:focus{border-color:var(--amber)}
#login-card button[type=submit]{color:var(--amber);border-color:var(--amber-dim)}
#login-err{min-height:1.1rem;font-size:.78rem;color:var(--red);margin-top:.2rem}
#login-card .muted{font-size:.72rem;margin-top:.4rem}
"""

_CSS_DISKIMG = """
/* Disk Image & Clone: command-preview fields and terminal-style
   console (v2.9.0) -- same idea as 44helper's .asl3-cmd-input /
   .asl3-console, restyled with instmon's own CSS vars rather than
   copying helper's palette. */
.diskimg-cmd{width:100%;box-sizing:border-box;font-family:var(--mono);
  font-size:.74rem;background:#0a1020;color:var(--yel);
  border:1px solid var(--border2);border-radius:4px;
  padding:.35rem .55rem;margin-top:.3rem}
.diskimg-cmd.placeholder{color:var(--muted);opacity:.55;font-style:italic}
/* Backup/Clone use a <textarea> for this field rather than an <input>,
   because the quiesce step (v2.20.0) makes the preview multi-line.
   These rules make a rows="1" textarea sit flush with the single-line
   <input> the Format/Restore cards still use, so the four cards look
   identical until there is genuinely more to show. */
textarea.diskimg-cmd{resize:vertical;line-height:1.35;overflow-x:auto;
  white-space:pre;display:block}
/* Quiesce (v2.20.0). The checkbox label is tinted so it reads as the
   one option on these cards with an on-air consequence, and the job
   banner is deliberately the loudest thing in the panel. */
.diskimg-quiesce{color:var(--yel)!important;opacity:.95}
.diskimg-offair{background:#3a1414;border:1px solid #c0392b;color:#ffb3a7;
  border-radius:4px;padding:.35rem .55rem;margin:.35rem 0;
  font-weight:600;letter-spacing:.02em;text-align:center}
.diskimg-cmd-note{font-size:.7rem;color:var(--muted);opacity:.7;margin-top:.15rem}
/* v2.21.0: the honest-limits line under Backup/Clone. Deliberately
   always visible rather than tucked into the checkbox tooltip -- the
   thing people misremember about this feature is what it guarantees. */
.popup-actions{display:flex;gap:.5rem;justify-content:center;margin-top:.7rem;flex-wrap:wrap}
.popup-actions button{font-size:.8rem;padding:.3rem .8rem}
.diskimg-quiesce-note{font-size:.7rem;color:var(--muted);opacity:.75;
  margin-top:.3rem;line-height:1.4;border-left:2px solid var(--border2);padding-left:.5rem}
/* Progress bar (v2.30.0). .indet is the moving-stripes form used for
   steps with no true percentage (quiescing, shrinking, mkfs, ...). */
.diskimg-bar{height:.85rem;background:#0a1020;border:1px solid var(--border2);
  border-radius:4px;overflow:hidden;margin:.4rem 0 .2rem}
.diskimg-bar-fill{height:100%;background:var(--blue)}
.diskimg-bar-fill.ok{background:var(--green)}
.diskimg-bar-fill.warn{background:var(--amber)}
.diskimg-bar-fill.err{background:var(--red2)}
.diskimg-bar-fill.indet{width:100%;background-color:var(--blue-dim);
  background-image:repeating-linear-gradient(45deg,var(--blue-dim) 0,var(--blue-dim) .6rem,var(--blue) .6rem,var(--blue) 1.2rem);
  background-size:1.7rem 1.7rem;animation:diskimg-bar-stripes 1s linear infinite}
@keyframes diskimg-bar-stripes{from{background-position:0 0}to{background-position:1.7rem 0}}
@media (prefers-reduced-motion:reduce){.diskimg-bar-fill.indet{animation:none}}
.diskimg-console{background:#070b10;border:1px solid var(--border2);
  border-radius:4px;padding:.5rem .6rem;margin-top:.4rem;
  white-space:pre-wrap;word-break:break-all;font-family:var(--mono);
  font-size:.76rem;max-height:220px;overflow-y:auto}
.diskimg-console.placeholder{color:var(--muted);opacity:.55;font-style:italic}
.diskimg-console .log-ok{color:var(--grn)}
.diskimg-console .log-err{color:var(--red)}
.diskimg-console .log-warn{color:var(--yel)}

/* Per-card hide/show (v2.15.0) -- default collapsed, toggled via a
   small button pinned to the card's own top-right corner rather than
   inline in a header row, per explicit request. Extra top padding on
   .diskimg-card (vs. plain .card) leaves room so the button never
   overlaps the card's own first line of content when expanded. */
.diskimg-card{position:relative;padding-top:2.1rem}
.diskimg-toggle{
  position:absolute;top:.55rem;right:.7rem;z-index:2;
  font-family:var(--mono);font-size:.68rem;color:var(--fg);
  cursor:pointer;padding:.15rem .55rem;border:1px solid var(--border2);
  border-radius:3px;background:transparent;
}
.diskimg-card.collapsed .diskimg-card-body{display:none}
"""

_CSS = (
    _CSS_BASE
    + _CSS_LAYOUT
    + _CSS_COMPONENTS
    + _CSS_LIBRARY
    + _CSS_LOG
    + _CSS_EDITOR
    + _CSS_LOGIN
    + _CSS_DISKIMG
)



_JS_LOG_POLL = """let lastLogId = 0;
const MAX_CLIENT_LOG_LINES = 500;

function logLine(entry) {
  const el = document.getElementById('log');
  const cls = entry.level === 'ok' ? 'log-ok' : entry.level === 'err' ? 'log-err' : entry.level === 'warn' ? 'log-warn' : '';
  const span = document.createElement('div');
  if (cls) span.className = cls;
  span.textContent = `[${entry.ts}] ${entry.msg}`;
  el.appendChild(span);
  // Mirror the server's LOG_MAX_LINES cap on the client side too --
  // otherwise a long-running open tab appends log lines to the DOM
  // forever (server-side history is capped, but the browser never
  // was), and the tab eventually bogs down and needs a reload.
  while (el.childNodes.length > MAX_CLIENT_LOG_LINES) {
    el.removeChild(el.firstChild);
  }
  el.scrollTop = el.scrollHeight;
  lastLogId = entry.id;
}

async function pollLog() {
  try {
    const r = await fetch(`/api/log?since=${lastLogId}`);
    const data = await r.json();
    for (const entry of data.entries) logLine(entry);
  } catch (e) { /* server restarting or unreachable, ignore this tick */ }
}

"""

_JS_STATUS_TOAST = """// Library cards default closed on every render; this Set tracks which
// categories the user has explicitly opened, so that state survives the
// innerHTML replacement that happens on each refreshStatus() tick.
const _libOpen = new Set();

// Per-category upload widgets now live inside #components/#library, both
// of which get replaced wholesale on every refreshStatus() tick (every
// 5s). A File the user has picked but not yet uploaded would otherwise
// vanish out from under them on the next poll. This Map holds the most
// recently picked File per category; restoreUploadSelections() (called
// from wireButtons() after every render) writes it back into the fresh
// input via DataTransfer.
const _pendingUploadFiles = new Map();

function restoreUploadSelections() {
  _pendingUploadFiles.forEach((file, cat) => {
    const input = document.getElementById('file-' + cat);
    if (!input) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
  });
}

function applyLibraryCollapseState() {
  document.querySelectorAll('.libgrp').forEach(card => {
    const cat = card.dataset.libcat;
    const open = _libOpen.has(cat);
    card.classList.toggle('collapsed', !open);
    const btn = card.querySelector('.lib-toggle');
    if (btn) btn.textContent = open ? 'Hide' : 'Show';
  });
}

// Last GitHub check/update result the page has seen; null until the
// first poll so a result from before this page load is not re-shown.
let _ghSeenSeq = null;

// v2.37.0 Quiet System + Full Update
let _fuState = null;
const _FU_STATUS = {
  update: 'UPDATE', current: 'CURRENT', not_installed: 'NOT INSTALLED', not_on_github: 'NOT ON GITHUB',
  newer_installed: 'NEWER HERE', unknown: 'UNKNOWN', error: 'ERROR',
};

function _fuList(title, items) {
  if (!items || !items.length) return '';
  return `<div><b>${title}</b><ul>${items.map(r => `<li>${escHtml(r.name)}: ${escHtml(r.note)}</li>`).join('')}</ul></div>`;
}

function renderQuietFullUpdate(quiet, fu) {
  _fuState = fu;
  const running = !!(fu && fu.running);
  const banners = [];
  if (quiet && quiet.on) {
    banners.push(`<div class="fu-banner"><span>System quiet since ${escHtml(quiet.since)}:
      ${quiet.stopped.length ? escHtml(quiet.stopped.join(', ')) + ' paused' : 'nothing was running'}.
      Auto-restore after ${quiet.auto_restore_min} min.</span>
      ${running ? '' : '<button data-action="restore">Restore</button>'}</div>`);
  }
  if (fu && fu.banner && !running) {
    const bad = (fu.attention || []).length || fu.error;
    const cls = bad ? 'err' : ((fu.skipped || []).length ? '' : 'ok');
    const any = (fu.updated || []).length + (fu.skipped || []).length + (fu.attention || []).length + (fu.scripts || []).length;
    banners.push(`<div class="fu-banner ${cls}"><div style="flex:1">
      <b>Full Update finished${fu.error ? ' -- ' + escHtml(fu.error) : ''}</b>
      ${_fuList('Updated', fu.updated)}${_fuList('Skipped', fu.skipped)}
      ${_fuList('NEEDS ATTENTION', fu.attention)}${_fuList('Scripts', fu.scripts)}
      ${any ? '' : '<div>Nothing needed updating.</div>'}
      </div><button data-action="fu_dismiss">Dismiss</button></div>`);
  }
  const bEl = document.getElementById('fu-banners');
  if (bEl) bEl.innerHTML = banners.join('');

  const prog = document.getElementById('fu-progress');
  if (prog) prog.textContent = running ? `Full Update running: ${fu.phase}${fu.current ? ' -- ' + fu.current : ''}` : '';
  const planEl = document.getElementById('fu-plan');
  const plan = fu && fu.plan;
  if (planEl) {
    planEl.innerHTML = !plan ? '' : '<table class="fu-table">' + plan.components.map(c =>
      `<tr><td>${escHtml(c.name)}</td><td><span class="gh-tag ${c.status === 'update' ? 'gh-upd' : ''}">${_FU_STATUS[c.status] || escHtml(c.status)}</span></td>` +
      `<td>${escHtml(c.note)}</td><td class="muted">${escHtml(c.file)}</td></tr>`).join('') +
      plan.scripts.map(n => `<tr><td>Script</td><td><span class="gh-tag gh-upd">NEW</span></td><td>goes to the Scripts library (not run)</td><td class="muted">${escHtml(n)}</td></tr>`).join('') +
      '</table>';
  }
  const fuBtn = document.getElementById('fu-btn');
  if (fuBtn) fuBtn.disabled = running || !(plan && (plan.updates || plan.scripts.length));
  const qb = document.getElementById('quiet-btn');
  if (qb) qb.disabled = running || !!(quiet && (quiet.on || quiet.other));
  const rb = document.getElementById('restore-btn');
  if (rb) rb.disabled = running || !(quiet && quiet.on);
  // While Full Update runs every other button waits (the server refuses
  // them anyway); only buttons disabled here are re-enabled afterwards.
  document.querySelectorAll('button[data-action], #diskimg-refresh-btn, #backup-btn').forEach(b => {
    if (['fu_dismiss', 'full_update', 'quiet', 'restore', 'toggle_lib', 'toggle_diskimg_card', 'go', 'router',
         'download', 'diskimg_backup_download'].includes(b.dataset.action)) return;
    if (running && !b.disabled) { b.disabled = true; b.dataset.fuDisabled = '1'; }
    else if (!running && b.dataset.fuDisabled) { b.disabled = false; delete b.dataset.fuDisabled; }
  });
}

async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    document.getElementById('components').innerHTML = data.components_html;
    document.getElementById('library').innerHTML = data.library_html;
    const ghEl = document.getElementById('gh-summary');
    if (ghEl && typeof data.gh_summary_html === 'string') ghEl.innerHTML = data.gh_summary_html;
    if (typeof data.gh_event_seq === 'number') {
      if (_ghSeenSeq !== null && data.gh_event_seq !== _ghSeenSeq && data.gh_event_msg) {
        showPopup(data.gh_event_msg, data.gh_event_level || 'info');
      }
      _ghSeenSeq = data.gh_event_seq;
    }
    renderQuietFullUpdate(data.quiet, data.full_update);
    applyLibraryCollapseState();
    wireButtons();
  } catch (e) { /* ignore this tick */ }
}

// Router quick link. The button ships hidden; this shows it only while
// /api/gateway says the gateway in use is known, on this viewer's LAN, and
// serving a page. Anything else -- ok:false, a failed fetch, bad JSON, or a
// url that isn't a plain http(s)://ipv4/ address -- hides it again. The
// url is stored on the button so the click can open it synchronously.
const _ROUTER_URL_RE = new RegExp('^https?://[0-9.]+(:[0-9]+)?/$');
async function pollGateway() {
  const btn = document.getElementById('router-link');
  if (!btn) return;
  let url = '';
  let ip = '';
  try {
    const r = await fetch('/api/gateway', {cache: 'no-store'});
    if (r.ok) {
      const d = await r.json();
      if (d && d.ok === true && typeof d.url === 'string' && _ROUTER_URL_RE.test(d.url)) {
        url = d.url;
        ip = typeof d.ip === 'string' ? d.ip : '';
      }
    }
  } catch (e) { /* hide below */ }
  if (url) {
    btn.dataset.url = url;
    btn.title = ip ? 'Open the router at ' + ip : 'Open the router';
    btn.classList.add('open');
  } else {
    btn.classList.remove('open');
    delete btn.dataset.url;
    btn.removeAttribute('title');
  }
}

// Disk Image & Clone (Stage 1: drive discovery only). Escapes any
// attacker-controlled string (lsblk MODEL/mountpoint text comes from
// the attached device itself) before it goes into innerHTML.
function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function fmtBytes(n) {
  if (typeof n !== 'number' || n < 0) return '?';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function renderDiskimgDeps(el, deps) {
  if (!deps) { el.innerHTML = ''; return; }
  if (deps.ok) {
    el.innerHTML = `<span class="log-ok">&#10003; PASS</span> <span class="muted">-- all disk-image dependencies installed (dd, lsblk, findmnt, mount, umount, partprobe, losetup, blkid, e2fsck, resize2fs, dumpe2fs, parted, openssl, mkfs.ext4, mkfs.vfat, mkfs.exfat).</span>`;
    return;
  }
  const parts = [];
  if (deps.missing_required && deps.missing_required.length) {
    parts.push(`<span class="log-err">missing (required): ${deps.missing_required.map(escHtml).join(', ')}</span>`);
  }
  if (deps.missing_optional && Object.keys(deps.missing_optional).length) {
    const byFeature = {};
    for (const [tool, feat] of Object.entries(deps.missing_optional)) {
      (byFeature[feat] = byFeature[feat] || []).push(tool);
    }
    const bits = Object.entries(byFeature).map(([feat, tools]) => `${escHtml(feat)} needs ${tools.map(escHtml).join(', ')}`);
    parts.push(`<span class="log-warn">missing (optional): ${bits.join('; ')}</span>`);
  }
  el.innerHTML = `<span class="log-err">&#10007; FAIL</span> ${parts.join(' &middot; ')}`;
}

// v2.13.0 Stage 4: single canonical drive table (moved from the
// shared panel onto the Full Format card, since that's where the
// Unmount action and prerequisite checks live) listing every
// detected drive -- including the boot disk itself, badged as the
// system drive rather than hidden -- with mount status and an
// Unmount button on any mounted, non-boot-disk row.
let _diskimgLastDrives = [];
// v2.20.0: remembered so offAirWarning() can estimate how long the node
// will be down. The boot disk is in this list badged SYSTEM DRIVE
// (v2.13.0), so its size is already on hand -- no extra request.
let _diskimgLastDrivesBootSize = 0;

function renderDrives(el, data) {
  const drives = data.drives || [];
  _diskimgLastDrives = drives;
  const bootRow = drives.filter(d => d.is_boot_disk)[0];
  if (bootRow && bootRow.size) _diskimgLastDrivesBootSize = bootRow.size;
  let html = '';
  if (!data.boot_disk_detected) {
    html += `<div class="log-err" style="margin-bottom:.4rem">Could not determine this Pi's boot disk -- imaging actions stay disabled until this resolves.</div>`;
  }
  if (!drives.length) {
    html += `<div class="muted">No drives detected. Plug one in -- an SD card in a USB adapter is detected the same as a flash drive.</div>`;
  } else {
    html += drives.map(d => {
      const badges = [];
      if (d.is_boot_disk) badges.push('<span class="log-warn">SYSTEM DRIVE</span>');
      if (d.read_only) badges.push('<span class="log-err">write-protected</span>');
      const mounted = d.mounted_at && d.mounted_at.length;
      const mountText = mounted ? `mounted at ${escHtml(d.mounted_at.join(', '))}` : 'not mounted';
      const unmountBtn = (mounted && !d.is_boot_disk)
        ? ` <button class="b-danger" data-action="diskimg_unmount" data-dest="${escHtml(d.path)}">Unmount</button>`
        : '';
      const label = escHtml(d.model) || (d.tran === 'usb' ? 'USB drive' : 'removable drive');
      return `<div class="row" style="justify-content:space-between">
        <span>${escHtml(d.path)} &middot; ${fmtBytes(d.size)} &middot; ${label}${badges.length ? ' &middot; ' + badges.join(' ') : ''}</span>
        <span class="small muted">${mountText}${unmountBtn}</span>
      </div>`;
    }).join('');
  }
  el.innerHTML = html;
  const depsEl = document.getElementById('diskimg-deps');
  if (depsEl) renderDiskimgDeps(depsEl, data.deps);
  populateDiskimgDestSelect('diskimg-backup-dest', drives);
  populateDiskimgDestSelect('diskimg-sched-dest', drives);
  populateDiskimgRawDestSelect('diskimg-clone-dest', drives);
  populateDiskimgRawDestSelect('diskimg-restore-dest', drives);
  populateDiskimgFormatDestSelect('diskimg-format-dest', drives);
  renderDiskimgFormatPrereqs(drives);
  // Populate* above can change a select's value programmatically
  // (setting .value doesn't fire 'change'), so the command-preview
  // fields need an explicit nudge here too, not just from their own
  // input/change listeners.
  scheduleDiskimgPreview('backup');
  scheduleDiskimgPreview('clone');
  scheduleDiskimgPreview('restore');
  scheduleDiskimgPreview('format');
}

function populateDiskimgDestSelect(selId, drives) {
  const sel = document.getElementById(selId);
  if (!sel) return;
  const prev = sel.value;
  const usable = drives.filter(d => !d.is_boot_disk);
  sel.innerHTML = usable.length
    ? usable.map(d => `<option value="${escHtml(d.path)}">${escHtml(d.path)} (${fmtBytes(d.size)}${d.read_only ? ', write-protected' : ''})</option>`).join('')
    : '<option value="">No usable drives attached</option>';
  if (usable.some(d => d.path === prev)) sel.value = prev;
}

// Clone/Restore both write the raw destination device directly, so
// unlike Backup's destination (which just needs a mounted filesystem to
// drop a file onto) a mounted destination here is excluded outright,
// not just flagged -- writing under an in-use filesystem's mount is
// exactly the self-overwrite-shaped risk this whole feature exists to
// avoid. Shared by both the Clone and Restore destination selects.
function populateDiskimgRawDestSelect(selId, drives) {
  const sel = document.getElementById(selId);
  if (!sel) return;
  const prev = sel.value;
  const usable = drives.filter(d => !d.is_boot_disk && !d.read_only && !(d.mounted_at && d.mounted_at.length));
  sel.innerHTML = usable.length
    ? usable.map(d => `<option value="${escHtml(d.path)}">${escHtml(d.path)} (${fmtBytes(d.size)})</option>`).join('')
    : '<option value="">No usable (unmounted) drives attached</option>';
  if (usable.some(d => d.path === prev)) sel.value = prev;
}

// Full Format's destination select is deliberately NOT filtered down
// to "usable" drives the way Clone/Restore's is above -- the whole
// point of the prerequisites/Unmount workflow (v2.13.0 Stage 4) is to
// let someone pick a currently-mounted (or otherwise not-yet-ready)
// drive, see exactly which check fails, and fix it (e.g. Unmount)
// without the drive disappearing from the dropdown in the meantime.
// Only the boot disk is excluded outright -- that's never a valid
// format target under any circumstance.
function populateDiskimgFormatDestSelect(selId, drives) {
  const sel = document.getElementById(selId);
  if (!sel) return;
  const prev = sel.value;
  const usable = drives.filter(d => !d.is_boot_disk);
  sel.innerHTML = usable.length
    ? usable.map(d => {
        const bits = [];
        if (d.read_only) bits.push('write-protected');
        if (d.mounted_at && d.mounted_at.length) bits.push('mounted');
        return `<option value="${escHtml(d.path)}">${escHtml(d.path)} (${fmtBytes(d.size)}${bits.length ? ', ' + bits.join(', ') : ''})</option>`;
      }).join('')
    : '<option value="">No non-boot drives attached</option>';
  if (usable.some(d => d.path === prev)) sel.value = prev;
}

// Four pass/fail prerequisite checks for whichever drive is currently
// selected in the Format destination dropdown, derived entirely from
// the same drive-list data the table above renders -- no separate
// drive-detection call. The Format button stays disabled until all
// four pass; a failing "Unmounted" check gets its own inline Unmount
// button so fixing it doesn't require scrolling back up to the table.
function renderDiskimgFormatPrereqs(drives) {
  const el = document.getElementById('diskimg-format-prereqs');
  const btn = document.querySelector('[data-action="diskimg_format_start"]');
  if (!el) return;
  const destSel = document.getElementById('diskimg-format-dest');
  const dest = destSel ? destSel.value : '';
  if (!dest) {
    el.innerHTML = '<span class="muted">Pick a destination drive to check prerequisites.</span>';
    if (btn) btn.disabled = true;
    return;
  }
  const match = drives.find(d => d.path === dest || d.name === dest);
  const checks = [
    ['Attached', !!match],
    ['Not boot disk', !!match && !match.is_boot_disk],
    ['Not write-protected', !!match && !match.read_only],
    ['Unmounted', !!match && !(match.mounted_at && match.mounted_at.length)],
  ];
  const allPass = checks.every(([, ok]) => ok);
  let html = checks.map(([label, ok]) =>
    `<span class="${ok ? 'log-ok' : 'log-err'}">${ok ? '&#10003;' : '&#10007;'} ${label}</span>`
  ).join(' &middot; ');
  if (match && !match.is_boot_disk && match.mounted_at && match.mounted_at.length) {
    html += ` <button class="b-danger" data-action="diskimg_unmount" data-dest="${escHtml(match.path)}">Unmount</button>`;
  }
  el.innerHTML = html;
  if (btn) btn.disabled = !allPass;
}

async function pollDrives() {
  const el = document.getElementById('diskimg-drives-table');
  if (!el) return;
  try {
    const r = await fetch('/api/diskimg/drives');
    const data = await r.json();
    renderDrives(el, data);
  } catch (e) { /* server restarting or unreachable, ignore this tick */ }
}

// v2.20.0: the extra confirm shown when "Pause node services during
// copy" is ticked. The estimate is deliberately conservative (a slow
// USB2 path is closer to 10MB/s than the 25-30MB/s a good reader
// manages) -- an operator who is told 45 minutes and gets 20 is fine;
// one who is told 20 and loses the node for 45 is not.
const _QUIESCE_EST_BYTES_PER_SEC = 10 * 1024 * 1024;

function offAirEstimate() {
  const job = _diskimgLastDrivesBootSize || 0;
  if (!job) return null;
  return Math.round(job / _QUIESCE_EST_BYTES_PER_SEC);
}

function offAirWarning() {
  const secs = offAirEstimate();
  const eta = secs ? ` Expect roughly ${fmtDuration(secs)} of downtime.` : '';
  return 'PAUSE NODE SERVICES is ticked.\\n\\n'
    + 'Asterisk, the bridges, the dashboards and the watchdog will be STOPPED for the '
    + 'whole job. The node will be OFF THE AIR and any connected nodes will drop.'
    + eta + '\\n\\n'
    + 'They are restarted automatically when the job ends, however it ends.\\n\\nContinue?';
}

function fmtDuration(sec) {
  if (typeof sec !== 'number' || sec < 0 || !isFinite(sec)) return '?';
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return h > 0 ? `${h}h${m}m` : m > 0 ? `${m}m${s}s` : `${s}s`;
}

// Terminal-style feedback boxes (v2.9.0, split per-card in v2.10.0
// Stage 1) -- same idea as 44helper's .asl3-console: a rolling log of
// meaningful lines rather than the once-a-second dd progress line
// (that stays in the compact percent/rate/ETA display below).
// Classifies the three state-tagged lines the backend appends
// ("done: ...", "failed: ...", "cancelled: ...") for color, everything
// else plain. Takes an element id now instead of a fixed single
// #diskimg-console, so each of the 4 cards (format/backup/clone/
// restore) can have its own.
function renderDiskimgConsoleInto(elId, job) {
  const el = document.getElementById(elId);
  if (!el) return;
  const lines = (job && job.console) || [];
  if (!lines.length) {
    el.className = 'diskimg-console placeholder';
    el.textContent = '(no job running)';
    return;
  }
  el.className = 'diskimg-console';
  el.innerHTML = lines.map(line => {
    const m = line.match(/\\] (done|failed|cancelled): /);
    const cls = m ? (m[1] === 'done' ? 'log-ok' : m[1] === 'failed' ? 'log-err' : 'log-warn') : '';
    return `<div class="${cls}">${escHtml(line)}</div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

// Per-card job-panel renderer (v2.10.0 Stage 1; progress bar and the
// per-card Stop/Reset buttons in v2.30.0) -- parameterized by element
// id so each of the 4 cards can host its own progress display.
const _DISKIMG_KIND_LABELS = {backup: 'Backup', clone: 'Clone', restore: 'Restore', format: 'Format'};
// Phases with no dd process to interrupt. Mirrors the refusals in
// _diskimg_cancel_job(), so Stop is disabled exactly where the server
// would say no.
const _DISKIMG_UNSTOPPABLE_PHASES = ['quiescing', 'thawing', 'unquiescing', 'shrinking', 'formatting'];

// Live-progress tracking (v2.30.2). One sample per job poll, kept for
// the job that is running: gives a rate over roughly the last minute
// (the server's figure is a whole-job average, which a fast page-cache
// burst at the start makes wildly optimistic) and notices when the
// byte counter has stopped moving.
let _diskimgTrack = {id: null, phase: null, pts: [], lastDone: -1, lastChangeAt: 0};

function diskimgTrackJob(job) {
  if (!job || job.state !== 'running') return;
  const now = Date.now();
  const phase = job.phase || 'copying';
  const done = phase === 'verifying' ? (job.verify_bytes_done || 0) : (job.bytes_done || 0);
  const t = _diskimgTrack;
  if (t.id !== job.id || t.phase !== phase) {
    t.id = job.id; t.phase = phase; t.pts = []; t.lastDone = -1; t.lastChangeAt = now;
  }
  if (done !== t.lastDone) { t.lastDone = done; t.lastChangeAt = now; }
  t.pts.push({t: now, d: done});
  while (t.pts.length > 2 && now - t.pts[0].t > 60000) t.pts.shift();
}

// bytes/sec over the tracked window, or null until there is enough of
// a window (>= 4 s) to mean anything.
function diskimgWindowRate(jobId) {
  const t = _diskimgTrack;
  if (t.id !== jobId || t.pts.length < 2) return null;
  const a = t.pts[0], b = t.pts[t.pts.length - 1];
  const dt = (b.t - a.t) / 1000;
  if (dt < 4) return null;
  const rate = (b.d - a.d) / dt;
  return rate > 0 ? rate : null;
}

// Byte counts with enough digits that the number visibly moves on every
// poll even at a few MB/s (fmtBytes' one decimal at GB scale only
// changes every ~100 MB).
function fmtBytesFine(n) {
  if (typeof n !== 'number' || n < 0) return '?';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : (i >= 3 ? 2 : 1))} ${units[i]}`;
}

function fmtPct(p) { return p >= 100 ? '100' : p.toFixed(1); }

// What the bar shows right now: {label, pct, cls}. pct === null means
// indeterminate (moving stripes) -- used for steps that have no true
// percentage, rather than faking one. pct carries one decimal so a big,
// slow drive's bar and number still visibly move (whole percents can sit
// still for minutes). While a copy is running it is capped at 99.9: dd
// counts bytes into the page cache, so it can report everything written
// a while before the final fsync finishes.
function diskimgPct(n, d) { return Math.min(99.9, Math.floor(1000 * n / d) / 10); }

function diskimgBarState(job) {
  const total = job.bytes_total || 0;
  const done = job.bytes_done || 0;
  if (job.state !== 'running') {
    const frac = total ? Math.max(0, Math.min(100, Math.floor(1000 * done / total) / 10)) : 100;
    if (job.state === 'done') return {label: 'Done', pct: 100, cls: 'ok'};
    if (job.state === 'cancelled') return {label: 'Stopped', pct: frac, cls: 'warn'};
    return {label: 'Failed', pct: frac, cls: 'err'};
  }
  const phase = job.phase || 'copying';
  // v2.30.1: once a stop has been requested the live numbers are stale
  // (dd is already dead, or verify is about to notice) -- say so.
  if (job.cancelled) return {label: 'Stopping', pct: null, cls: 'indet'};
  if (phase === 'quiescing') return {label: 'Stopping node services', pct: null, cls: 'indet'};
  if (phase === 'thawing') return {label: 'Thawing filesystem', pct: null, cls: 'indet'};
  if (phase === 'unquiescing') return {label: 'Restarting node services', pct: null, cls: 'indet'};
  if (phase === 'shrinking') return {label: 'Shrinking image', pct: null, cls: 'indet'};
  if (phase === 'formatting') return {label: 'Partitioning and formatting', pct: null, cls: 'indet'};
  if (phase === 'verifying') {
    const vdone = job.verify_bytes_done || 0;
    if (!total) return {label: 'Verifying', pct: null, cls: 'indet'};
    return {label: 'Verifying', pct: diskimgPct(vdone, total), cls: ''};
  }
  let verb = 'Copying';
  if (job.kind === 'format') verb = job.quick ? 'Clearing old partition data' : 'Wiping drive';
  else if (job.kind === 'restore') verb = 'Restoring';
  else if (job.kind === 'clone') verb = 'Cloning';
  if (!total) return {label: verb, pct: null, cls: 'indet'};
  if (done >= total) return {label: 'Flushing to disk', pct: 99.9, cls: ''};
  return {label: verb, pct: diskimgPct(done, total), cls: ''};
}

function renderDiskimgJobInto(elId, job) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!job) { el.innerHTML = ''; return; }
  const kindLabel = _DISKIMG_KIND_LABELS[job.kind] || job.kind;
  const stateCls = job.state === 'done' ? 'log-ok' : job.state === 'failed' ? 'log-err' : job.state === 'cancelled' ? 'log-warn' : '';
  let html = `<div class="row" style="justify-content:space-between">
    <span>${kindLabel}: ${escHtml(job.source)} &rarr; ${escHtml(job.dest)}</span>
    <span class="${stateCls}">${escHtml(job.state)}</span>
  </div>`;
  // v2.20.0: the node is off the air for as long as this banner is up.
  // Deliberately the first thing in the panel and deliberately loud --
  // an operator who wanders off mid-backup should be able to tell at a
  // glance, from across the room, that the node is still down.
  if (job.quiesced && job.state === 'running') {
    html += `<div class="diskimg-offair">NODE SERVICES STOPPED &mdash; off the air until this job finishes.</div>`;
  }
  const bar = diskimgBarState(job);
  const hasPct = bar.pct !== null;
  html += `<div class="diskimg-bar" role="progressbar" aria-label="${escHtml(kindLabel)} progress" aria-valuemin="0" aria-valuemax="100"${hasPct ? ' aria-valuenow="' + bar.pct + '"' : ''}><div class="diskimg-bar-fill ${bar.cls}"${hasPct ? ' style="width:' + bar.pct + '%"' : ''}></div></div>`;
  const elapsedTxt = (typeof job.elapsed_sec === 'number') ? fmtDuration(job.elapsed_sec) : '?';
  if (job.state === 'running') {
    const phase = job.phase || 'copying';
    // v2.26.0: a quick one-line summary of which of the optional
    // behaviours are actually active on this job -- easy to lose track
    // of otherwise, since they're spread across rows of checkboxes.
    const badges = [];
    if (job.frozen) badges.push('frozen');
    if (job.backend === 'ddrescue') badges.push('ddrescue');
    if (job.best_effort_requested) badges.push('best effort');
    if (job.direct_io_requested) badges.push('direct I/O');
    if (job.throttle_rate_mb) badges.push(`throttled ${job.throttle_rate_mb}MB/s`);
    if (job.kind === 'format' && job.quick) badges.push('quick format');
    if (badges.length) {
      html += `<div class="small muted">${badges.join(' &middot; ')}</div>`;
    }
    if (job.cancelled) {
      html += `<div class="small muted">Stopping &mdash; waiting for the job to wind down&hellip;</div>`;
    } else {
      const meterDone = phase === 'verifying' ? (job.verify_bytes_done || 0) : (job.bytes_done || 0);
      const flushing = bar.label === 'Flushing to disk';
      let line = bar.label;
      if (hasPct) line += ` &middot; ${fmtPct(bar.pct)}%`;
      if (hasPct && job.bytes_total) line += ` &middot; ${fmtBytesFine(meterDone)} of ${fmtBytesFine(job.bytes_total)}`;
      if (!hasPct) line += ' &mdash; no percentage is available for this step';
      html += `<div class="small muted">${line}</div>`;
      // How long: always the elapsed time; time left once there is a
      // window of samples to base it on.
      let timing = `Elapsed ${elapsedTxt}`;
      if (hasPct && !flushing && (phase === 'copying' || phase === 'verifying')) {
        const rate = diskimgWindowRate(job.id);
        const left = job.bytes_total ? job.bytes_total - meterDone : null;
        if (rate && left !== null && left > 0) {
          timing += ` &middot; about ${fmtDuration(left / rate)} left &middot; ${fmtBytes(rate)}/s`;
        } else {
          timing += ' &middot; estimating time left&hellip;';
        }
      }
      html += `<div class="small muted">${timing}</div>`;
      const trk = _diskimgTrack;
      if (trk.id === job.id && hasPct && !flushing && (phase === 'copying' || phase === 'verifying')) {
        const idle = (Date.now() - trk.lastChangeAt) / 1000;
        if (idle >= 30) {
          html += `<div class="small log-warn">No progress reported for ${fmtDuration(idle)} &mdash; the drive may be stalled or very slow.</div>`;
        }
      }
      const notes = {
        quiescing: 'Stopping node services (watchdog, dashboards, then Asterisk and the bridges) before the copy starts&hellip;',
        thawing: 'Copy finished &mdash; thawing the root filesystem&hellip;',
        unquiescing: 'Copy finished &mdash; restarting node services (comms first, watchdog last)&hellip;',
        shrinking: 'Copy complete -- shrinking image to its minimum size (resize2fs + parted). This can take a few minutes and cannot be stopped mid-step.',
        formatting: 'Wipe complete -- writing a fresh GPT partition table and creating the filesystem. This only takes a moment and cannot be stopped mid-step.',
        verifying: `Copy complete -- re-reading and comparing ${escHtml(job.verify_algo || 'sha256')} checksums.`,
      };
      if (notes[phase]) html += `<div class="small muted">${notes[phase]}</div>`;
    }
  } else {
    if (job.message) html += `<div class="small muted">${escHtml(job.message)}</div>`;
    if (typeof job.elapsed_sec === 'number') html += `<div class="small muted">Total time ${elapsedTxt}</div>`;
  }
  el.innerHTML = html;
}

// Dispatch (v2.10.0 Stage 1): there's still only one disk-image job
// system-wide (dd is heavy -- see _diskimg_start_job's "already
// running" guard on the backend), so only the card matching
// job.kind ever shows live progress/console; the other three fall
// back to their idle "(no job running)" placeholder. This is what
// makes the 4-card split feel independent while keeping the
// one-job-at-a-time safety property unchanged.
const _DISKIMG_KINDS = ['format', 'backup', 'clone', 'restore'];
let _diskimgCurrentJob = null;

function renderDiskimgJob(job) {
  _diskimgCurrentJob = job || null;
  diskimgTrackJob(job);
  _DISKIMG_KINDS.forEach(kind => {
    const active = (job && job.kind === kind) ? job : null;
    renderDiskimgJobInto('diskimg-job-' + kind, active);
    renderDiskimgConsoleInto('diskimg-console-' + kind, active);
  });
  syncDiskimgCardButtons();
}

// Stop/Reset live in each card's action row (v2.30.0), not in the job
// panel, so a 2s panel re-render can never swallow a click. Stop is
// enabled only for this card's own running job in a stoppable phase;
// Reset only when this card's job is not running or still restarting
// node services (the server enforces the same rules).
function syncDiskimgCardButtons() {
  const job = _diskimgCurrentJob;
  _DISKIMG_KINDS.forEach(kind => {
    const stopBtn = document.querySelector('button[data-action="diskimg_stop"][data-kind="' + kind + '"]');
    const resetBtn = document.querySelector('button[data-action="diskimg_reset"][data-kind="' + kind + '"]');
    const mine = (job && job.kind === kind) ? job : null;
    const running = !!mine && mine.state === 'running';
    const settling = !!mine && mine.state !== 'running' && !!mine.quiesced && mine.phase !== 'done';
    if (stopBtn) {
      // v2.30.1: cancelled is set the moment the server accepts a stop,
      // but the job can stay "running" for a few seconds while it winds
      // down. Keep Stop disabled and say what is happening rather than
      // re-enabling it as if nothing had been clicked.
      const stopping = running && !!mine.cancelled;
      const stoppable = running && !stopping && !_DISKIMG_UNSTOPPABLE_PHASES.includes(mine.phase);
      stopBtn.disabled = !stoppable;
      stopBtn.textContent = stopping ? 'Stopping...' : 'Stop';
      if (stoppable) stopBtn.title = 'Stop the running job.';
      else if (stopping) stopBtn.title = 'Stop requested -- waiting for the job to wind down.';
      else if (running) stopBtn.title = 'This step cannot be stopped mid-way -- it finishes on its own shortly.';
      else if (job && job.state === 'running') stopBtn.title = 'A ' + (_DISKIMG_KIND_LABELS[job.kind] || job.kind) + ' job is running on its own card.';
      else stopBtn.title = 'Nothing is running on this card.';
    }
    if (resetBtn) {
      resetBtn.disabled = running || settling;
      resetBtn.title = running ? 'Stop the job first.' : settling ? 'Node services are still being restarted.' : 'Clear the last result on this card and put its options back to their defaults for another try.';
    }
  });
}

// Puts one card's own options back to their HTML defaults (drive and
// image pickers excepted, see below). Only touches
// elements whose id starts with diskimg-<kind>- (so the Backup card's
// schedule form and backups list, which live inside it, are left
// alone), and skips the read-only command previews, which are rebuilt
// from the options anyway.
function resetDiskimgCardForm(kind) {
  const prefix = 'diskimg-' + kind + '-';
  document.querySelectorAll('[id^="' + prefix + '"]').forEach(el => {
    if (el.classList.contains('diskimg-cmd')) return;
    if (el.tagName === 'INPUT') {
      if (el.type === 'checkbox') el.checked = el.defaultChecked;
      else if (el.type === 'text' || el.type === 'password' || el.type === 'number') el.value = el.defaultValue;
      else return;
    } else if (el.tagName === 'SELECT') {
      // v2.30.1: which drive / which backup image is a target, not an
      // option. Snapping it back to the first entry would silently
      // re-point a destructive action (and lose the drive you were
      // about to retry with), so leave those alone.
      if (el.id.endsWith('-dest') || el.id.endsWith('-image')) return;
      const idx = Array.from(el.options).findIndex(o => o.defaultSelected);
      el.selectedIndex = idx >= 0 ? idx : 0;
    } else {
      return;
    }
    // Fire the card's own change handlers (freeze/backend enable rules,
    // format prerequisites) so dependent controls settle too.
    el.dispatchEvent(new Event('change', {bubbles: true}));
  });
  scheduleDiskimgPreview(kind);
  if (kind === 'format') renderDiskimgFormatPrereqs(_diskimgLastDrives);
}

async function resetDiskimgCard(kind) {
  let r = null;
  let data = {};
  try {
    r = await fetch('/api/diskimg/job/reset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify({kind: kind}),
    });
    try { data = await r.json(); } catch (e) {}
  } catch (e) {
    showPopup('Reset failed: could not reach the server.', 'err');
    return false;
  }
  if (!r.ok) {
    showPopup(data.error || data.message || `Reset failed (${r.status})`, 'err');
    return false;
  }
  resetDiskimgCardForm(kind);
  renderDiskimgJobInto('diskimg-job-' + kind, null);
  renderDiskimgConsoleInto('diskimg-console-' + kind, null);
  showPopup((_DISKIMG_KIND_LABELS[kind] || kind) + ' card reset.', 'ok');
  return true;
}

// Done-popup tracking (v2.9.0): fires showPopup() the moment a job
// transitions from 'running' to a terminal state while this page was
// actually watching it -- not for a job that was already finished
// before the page loaded (isNewJob + not-running-yet leaves
// _diskimgSeenRunning false, so the very next terminal read stays
// silent), and only once per job even though polling continues.
let _diskimgLastJobId = null;
let _diskimgLastJobState = null;
let _diskimgSeenRunning = false;

async function pollDiskimgJob() {
  try {
    const r = await fetch('/api/diskimg/job');
    const data = await r.json();
    const job = data.job;
    if (job) {
      const isNewJob = job.id !== _diskimgLastJobId;
      if (isNewJob) {
        _diskimgSeenRunning = (job.state === 'running');
      } else if (job.state === 'running') {
        _diskimgSeenRunning = true;
      } else if (_diskimgSeenRunning && job.state !== _diskimgLastJobState) {
        const kindLabel = {backup: 'Backup', clone: 'Clone', restore: 'Restore', format: 'Format'}[job.kind] || job.kind;
        let level = job.state === 'done' ? 'ok' : job.state === 'cancelled' ? 'warn' : 'err';
        let text = `${kindLabel} ${job.state}: ${job.message || ''}`.trim();
        // v2.20.0: a job whose copy succeeded but whose services did
        // not all come back must NOT read as a clean green success --
        // the copy is fine, the node is not.
        if (job.quiesced && job.quiesce_restore_ok === false) {
          // Sticky + actionable: the node is off the air and the fix is
          // one click away rather than on another card (v2.24.0).
          offerRebootAfterFailedRestart(
            text + ' -- NODE SERVICES DID NOT ALL RESTART. A reboot is recommended.');
        } else {
          showPopup(text, level);
        }
        _diskimgSeenRunning = false;
      }
      _diskimgLastJobId = job.id;
      _diskimgLastJobState = job.state;
    }
    renderDiskimgJob(job);
    wireButtons();
  } catch (e) { /* ignore this tick */ }
}

// Command-preview fields (v2.9.0), same idea as 44helper's editable
// command line -- here read-only, since instmon builds these
// server-side from validated, currently-attached-drive state rather
// than letting the operator hand-edit a raw dd invocation.
let _diskimgPreviewTimers = {};

async function updateDiskimgPreview(kind) {
  const body = {kind};
  let cmdElId, noteElId = null;
  if (kind === 'backup') {
    cmdElId = 'diskimg-backup-cmd'; noteElId = 'diskimg-backup-cmd-note';
    body.dest_device = (document.getElementById('diskimg-backup-dest') || {}).value || '';
    body.label = (document.getElementById('diskimg-backup-label') || {}).value || '';
    body.encrypt = (document.getElementById('diskimg-backup-encrypt') || {}).checked || false;
    body.quiesce = (document.getElementById('diskimg-backup-quiesce') || {}).checked || false;
    body.best_effort = (document.getElementById('diskimg-backup-best-effort') || {}).checked || false;
    body.backend = (document.getElementById('diskimg-backup-backend') || {}).value || 'dd';
    const bThrottle = (document.getElementById('diskimg-backup-throttle') || {}).value || '';
    body.throttle_rate_mb = bThrottle ? Number(bThrottle) : null;
  } else if (kind === 'clone') {
    cmdElId = 'diskimg-clone-cmd';
    body.dest_device = (document.getElementById('diskimg-clone-dest') || {}).value || '';
    body.quiesce = (document.getElementById('diskimg-clone-quiesce') || {}).checked || false;
    body.best_effort = (document.getElementById('diskimg-clone-best-effort') || {}).checked || false;
    body.direct_io = (document.getElementById('diskimg-clone-direct-io') || {}).checked || false;
    body.backend = (document.getElementById('diskimg-clone-backend') || {}).value || 'dd';
    const cThrottle = (document.getElementById('diskimg-clone-throttle') || {}).value || '';
    body.throttle_rate_mb = cThrottle ? Number(cThrottle) : null;
  } else if (kind === 'format') {
    cmdElId = 'diskimg-format-cmd'; noteElId = 'diskimg-format-cmd-note';
    body.dest_device = (document.getElementById('diskimg-format-dest') || {}).value || '';
    body.quick = (document.getElementById('diskimg-format-quick') || {}).checked || false;
  } else if (kind === 'restore') {
    cmdElId = 'diskimg-restore-cmd';
    const imgVal = (document.getElementById('diskimg-restore-image') || {}).value || '';
    const sepIdx = imgVal.indexOf('::');
    body.name = sepIdx >= 0 ? imgVal.slice(0, sepIdx) : imgVal;
    body.drive = sepIdx >= 0 ? imgVal.slice(sepIdx + 2) : '';
    body.dest_device = (document.getElementById('diskimg-restore-dest') || {}).value || '';
    const rThrottle = (document.getElementById('diskimg-restore-throttle') || {}).value || '';
    body.throttle_rate_mb = rThrottle ? Number(rThrottle) : null;
  } else {
    return;
  }
  const cmdEl = document.getElementById(cmdElId);
  if (!cmdEl) return;
  const noteEl = noteElId ? document.getElementById(noteElId) : null;
  try {
    const r = await fetch('/api/diskimg/preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (data.command) {
      cmdEl.value = data.command;
      cmdEl.classList.remove('placeholder');
    } else {
      cmdEl.value = data.error || 'Could not build a preview.';
      cmdEl.classList.add('placeholder');
    }
    // v2.20.0: the quiesce step makes this preview multi-line. The
    // Backup/Clone fields are <textarea>, so grow them to fit rather
    // than showing only the first line; they sit at rows=1 and look
    // exactly like the single-line <input> the other two cards use
    // until there is actually more to show.
    if (cmdEl.tagName === 'TEXTAREA') {
      cmdEl.rows = Math.min(14, (cmdEl.value.match(/\\n/g) || []).length + 1);
    }
    if (noteEl) noteEl.textContent = data.note || '';
  } catch (e) { /* leave whatever was last shown */ }
}

function scheduleDiskimgPreview(kind) {
  clearTimeout(_diskimgPreviewTimers[kind]);
  _diskimgPreviewTimers[kind] = setTimeout(() => updateDiskimgPreview(kind), 350);
}

function renderDiskimgBackups(backups) {
  const el = document.getElementById('diskimg-backups');
  if (el) {
    if (!backups.length) {
      el.innerHTML = '<span class="muted">No backups found on any attached drive.</span>';
    } else {
      el.innerHTML = backups.map(b => {
        const age = new Date(b.mtime * 1000).toLocaleString();
        const encBadge = b.encrypted ? ' &middot; <span class="log-warn">encrypted</span>' : '';
        return `<div class="row" style="justify-content:space-between">
          <span>${escHtml(b.name)} &middot; ${fmtBytes(b.size)} &middot; ${escHtml(b.drive)} &middot; ${age}${encBadge}</span>
          <span>
            <button data-action="diskimg_backup_download" data-name="${escHtml(b.name)}" data-drive="${escHtml(b.drive)}">Download</button>
            <button class="b-danger" data-action="diskimg_backup_delete" data-name="${escHtml(b.name)}" data-drive="${escHtml(b.drive)}">Delete</button>
          </span>
        </div>`;
      }).join('');
    }
  }
  populateDiskimgRestoreSelect(backups);
  scheduleDiskimgPreview('restore');
  wireButtons();
}

// Restore's source-image <select> encodes name+drive together (a name
// alone doesn't uniquely identify a backup -- the same hostname/
// timestamp-derived filename could in principle exist on two different
// attached drives) using a delimiter neither field can practically
// contain (backup filenames come from our own hostname_timestamp[_label]
// .img pattern; device paths look like /dev/sdb).
function populateDiskimgRestoreSelect(backups) {
  const sel = document.getElementById('diskimg-restore-image');
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = backups.length
    ? backups.map(b => `<option value="${escHtml(b.name)}::${escHtml(b.drive)}">${escHtml(b.name)} (${fmtBytes(b.size)}${b.encrypted ? ', encrypted' : ''})</option>`).join('')
    : '<option value="">No backups available</option>';
  if (backups.some(b => `${b.name}::${b.drive}` === prev)) sel.value = prev;
}

async function pollDiskimgBackups() {
  const el = document.getElementById('diskimg-backups');
  if (!el) return;
  try {
    const r = await fetch('/api/diskimg/backup/list');
    const data = await r.json();
    renderDiskimgBackups(data.backups || []);
  } catch (e) { /* ignore this tick */ }
}

// The schedule's form fields (enabled/interval/dest/retention/shrink/
// verify/label) are only ever populated from the server once, right
// after login -- not on every poll -- so editing the form isn't
// fighting a background refresh every few seconds. Only the read-only
// status line below the form (last run / next run / last skip reason)
// updates on each poll.
let _diskimgScheduleFormLoaded = false;

function populateDiskimgScheduleForm(sched) {
  const set = (id, value, isCheckbox) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (isCheckbox) el.checked = !!value; else el.value = value;
  };
  set('diskimg-sched-enabled', sched.enabled, true);
  set('diskimg-sched-interval', sched.interval_hours);
  set('diskimg-sched-retention', sched.retention);
  set('diskimg-sched-shrink', sched.shrink, true);
  set('diskimg-sched-verify', sched.verify, true);
  set('diskimg-sched-quiesce', sched.quiesce, true);
  set('diskimg-sched-label', sched.label || '');
  const destSel = document.getElementById('diskimg-sched-dest');
  if (destSel && sched.dest_device) {
    // The drive may not be attached/listed yet (drives list loads
    // independently) -- add it as an extra option so a configured-but-
    // currently-unplugged destination still shows correctly rather
    // than silently reverting to the first option.
    if (![...destSel.options].some(o => o.value === sched.dest_device)) {
      const opt = document.createElement('option');
      opt.value = sched.dest_device;
      opt.textContent = `${sched.dest_device} (not currently attached)`;
      destSel.appendChild(opt);
    }
    destSel.value = sched.dest_device;
  }
}

function renderDiskimgScheduleStatus(sched) {
  const el = document.getElementById('diskimg-schedule-status');
  if (!el) return;
  const parts = [];
  if (!sched.enabled) {
    parts.push('Disabled.');
  } else {
    parts.push(sched.next_run_at ? `Next run: ${new Date(sched.next_run_at * 1000).toLocaleString()}` : 'Next run: as soon as due.');
  }
  if (sched.last_run_at) {
    const cls = sched.last_run_status === 'done' ? 'log-ok' : sched.last_run_status === 'failed' ? 'log-err' : 'log-warn';
    parts.push(`Last run ${new Date(sched.last_run_at * 1000).toLocaleString()}: <span class="${cls}">${escHtml(sched.last_run_status)}</span> -- ${escHtml(sched.last_run_message || '')}`);
  }
  if (sched.last_quiesce_restore_ok === false) {
    // v2.25.0: nobody is watching the job panel at 03:00, so a
    // scheduled run whose services did not come back has to be visible
    // on the schedule card itself -- this is the only place it will be
    // seen the next morning.
    parts.push('<span class="log-err">Last scheduled run left node services STOPPED -- a reboot is recommended.</span>');
  }
  if (sched.last_skip_message) {
    parts.push(`<span class="log-warn">Waiting: ${escHtml(sched.last_skip_message)}</span>`);
  }
  el.innerHTML = parts.map(p => `<div>${p}</div>`).join('');
}

async function pollDiskimgSchedule() {
  try {
    const r = await fetch('/api/diskimg/schedule');
    const data = await r.json();
    const sched = data.schedule;
    if (!sched) return;
    if (!_diskimgScheduleFormLoaded) {
      populateDiskimgScheduleForm(sched);
      _diskimgScheduleFormLoaded = true;
    }
    renderDiskimgScheduleStatus(sched);
  } catch (e) { /* ignore this tick */ }
}

async function postDiskimg(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  const level = data.level || (r.ok ? 'ok' : 'err');
  const message = data.message || data.error || (r.ok ? 'Done.' : `Request failed (${r.status})`);
  showPopup(message, level);
  return data;
}

// Echoes a popup's message into the execution log as its own line,
// without touching lastLogId -- this is a client-side mirror only, not
// a real server log entry, so it must not disturb the /api/log poll
// cursor (which would otherwise skip real entries).
function echoToLog(message, level) {
  const el = document.getElementById('log');
  if (!el) return;
  const cls = level === 'ok' ? 'log-ok' : level === 'err' ? 'log-err' : level === 'warn' ? 'log-warn' : '';
  const span = document.createElement('div');
  if (cls) span.className = cls;
  const ts = new Date().toISOString().replace('T', ' ').slice(0, 19);
  span.textContent = `[${ts}] ${message}`;
  el.appendChild(span);
  while (el.childNodes.length > MAX_CLIENT_LOG_LINES) {
    el.removeChild(el.firstChild);
  }
  el.scrollTop = el.scrollHeight;
}

let _popupTimer = null;

function showPopup(message, level) {
  if (!message) return;
  const cls = {ok: 'popup-ok', warn: 'popup-warn', err: 'popup-err', info: 'popup-info'}[level] || 'popup-info';
  const overlay = document.getElementById('popup-overlay');
  const box = document.getElementById('popup-box');
  box.className = `popup-box ${cls}`;
  box.textContent = message;
  overlay.classList.add('open');
  requestAnimationFrame(() => box.classList.add('popup-show'));
  echoToLog(message, level);
  clearTimeout(_popupTimer);
  _popupTimer = setTimeout(() => {
    box.classList.remove('popup-show');
    setTimeout(() => overlay.classList.remove('open'), 200);
  }, 2500);
}

function dismissPopup() {
  clearTimeout(_popupTimer);
  const overlay = document.getElementById('popup-overlay');
  const box = document.getElementById('popup-box');
  if (!overlay || !box) return;
  box.classList.remove('popup-show');
  setTimeout(() => overlay.classList.remove('open'), 200);
}

// v2.24.0: a popup that does NOT auto-dismiss and carries actions.
// Used for exactly one thing today -- a quiesced job whose services did
// not all come back. The ordinary 2.5s popup is wrong there: the node
// is off the air, the operator may be looking away, and the remedy
// (reboot) lives on a different card they would have to go find. This
// keeps the message on screen until acknowledged and puts the remedy
// under the cursor.
function showStickyPopup(message, level, actions) {
  if (!message) return;
  const cls = {ok: 'popup-ok', warn: 'popup-warn', err: 'popup-err', info: 'popup-info'}[level] || 'popup-info';
  const overlay = document.getElementById('popup-overlay');
  const box = document.getElementById('popup-box');
  if (!overlay || !box) return;
  clearTimeout(_popupTimer);
  box.className = `popup-box ${cls}`;
  box.textContent = '';
  const msg = document.createElement('div');
  msg.textContent = message;
  box.appendChild(msg);
  const row = document.createElement('div');
  row.className = 'popup-actions';
  (actions || []).forEach(a => {
    const b = document.createElement('button');
    b.textContent = a.label;
    if (a.cls) b.className = a.cls;
    b.addEventListener('click', () => { dismissPopup(); if (a.onClick) a.onClick(); });
    row.appendChild(b);
  });
  const dismiss = document.createElement('button');
  dismiss.textContent = 'Dismiss';
  dismiss.addEventListener('click', dismissPopup);
  row.appendChild(dismiss);
  box.appendChild(row);
  overlay.classList.add('open');
  requestAnimationFrame(() => box.classList.add('popup-show'));
  echoToLog(message, level);
}

// The reboot offered here is the same server-side action the System &
// Comms card's Reboot button uses -- same route, same confirms, no
// second code path to keep in sync.
function offerRebootAfterFailedRestart(message) {
  showStickyPopup(message, 'err', [{
    label: 'Reboot now',
    cls: 'b-danger',
    onClick: async () => {
      if (!confirm('Reboot this Pi now? Every service on it -- including this instmon page -- goes unreachable until it finishes booting back up.')) return;
      if (!confirm('Really sure? This is a full node reboot.')) return;
      await postAction({action: 'reboot'});
    },
  }]);
}

async function postAction(body) {
  const r = await fetch('/api/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
    body: JSON.stringify(body)
  });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  const level = data.level || (r.ok ? 'ok' : 'err');
  const message = data.message || data.error || (r.ok ? 'Done.' : `Request failed (${r.status})`);
  showPopup(message, level);
  return data;
}

"""

_JS_EDITOR = """// Editor functions
// Editor overlay JS (Stage 8/9, Library Card Rework Plan). _editCategory
// and _editName track which library file is open, since uf-overlay's
// buttons (onclick="ufSave()" etc.) don't carry that context on their
// own the way the old per-open closures did.
let _editCategory = '';
let _editName = '';

function ufSetStatus(msg, ok) {
  const el = document.getElementById('uf-status');
  if (!el) return;
  el.textContent = msg || '';
  el.style.color = ok === true ? 'var(--grn)' : ok === false ? 'var(--red)' : 'var(--fg)';
}

function closeEditor() {
  document.getElementById('uf-overlay').classList.remove('open');
  _editCategory = '';
  _editName = '';
}

function ufOverlayClick(e) {
  if (e.target === document.getElementById('uf-overlay')) closeEditor();
}

async function ufCopy() {
  // Mirrors sysmon's _copyWithVerify(): try the async Clipboard API
  // first, fall back to a hidden-textarea execCommand('copy') for
  // browsers/contexts that block navigator.clipboard, then read the
  // clipboard back to confirm the write actually landed in full --
  // some mobile browsers silently truncate large clipboard writes.
  const ta = document.getElementById('uf-textarea');
  if (!ta || !ta.value) { showPopup('Nothing to copy', 'err'); return; }
  await copyTextWithVerify(ta.value, 'Copied');
}

// Shared copy-then-verify helper (v2.14.0) -- extracted from ufCopy()
// so the Execution Log's Copy button can reuse the exact same
// clipboard-write + hidden-textarea fallback + read-back-to-verify
// sequence instead of duplicating it.
async function copyTextWithVerify(text, okMessage) {
  if (!text) { showPopup('Nothing to copy', 'err'); return; }
  let wrote = false;
  try {
    await navigator.clipboard.writeText(text);
    wrote = true;
  } catch (e) {
    const tmp = document.createElement('textarea');
    tmp.value = text;
    tmp.style.position = 'fixed';
    tmp.style.left = '-9999px';
    tmp.setAttribute('readonly', '');
    document.body.appendChild(tmp);
    tmp.focus();
    tmp.setSelectionRange(0, tmp.value.length);
    try { document.execCommand('copy'); wrote = true; } catch (e2) { wrote = false; }
    document.body.removeChild(tmp);
  }
  if (!wrote) { showPopup('Copy failed', 'err'); return; }
  try {
    const check = await navigator.clipboard.readText();
    if (check === text) {
      showPopup(okMessage, 'ok');
    } else {
      showPopup(`Copy may be incomplete (${check.length} of ${text.length} characters) -- try again, or use a desktop browser if this persists.`, 'warn');
    }
  } catch (e) {
    // Clipboard readText() isn't available/permitted everywhere the
    // write above just succeeded on (notably some mobile browsers) --
    // that's not a failure, just an unconfirmed success.
    showPopup(`${okMessage} -- could not confirm on this browser`, 'info');
  }
}

// Execution Log's own Copy button (v2.14.0). Deliberately walks
// #log's direct child nodes and joins their textContent with a
// newline rather than using innerText: #log's content is a mix of a
// raw startup text node (which already has its own embedded newline)
// and per-entry <div>s appended by logLine(), and textContent alone
// would run every line together with no separators at all. This also
// avoids innerText's dependency on live layout/visibility -- a copy
// button shouldn't behave differently depending on whether the log
// happens to be scrolled or hidden behind something at the moment
// it's clicked.
function collectLogText(el) {
  return Array.from(el.childNodes).map(n => n.textContent).join('\\n');
}

async function copyExecutionLog() {
  const el = document.getElementById('log');
  const text = el ? collectLogText(el) : '';
  await copyTextWithVerify(text, 'Log copied');
}

async function ufSave() {
  if (!_editName) return;
  const newContent = document.getElementById('uf-textarea').value;
  const btn = document.getElementById('uf-save-btn');
  if (btn) btn.disabled = true;
  ufSetStatus('Saving...');
  try {
    const saveRes = await fetch('/api/file', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify({file: _editName, category: _editCategory, content: newContent})
    });
    const saveData = await saveRes.json();
    if (!saveRes.ok) {
      ufSetStatus(`Save failed: ${saveData.error || saveRes.status}`, false);
      return;
    }
    ufSetStatus(`Saved (${saveData.reason})`, true);
    await refreshStatus();
    setTimeout(closeEditor, 900);
  } catch (e) {
    ufSetStatus('Save error: ' + e.message, false);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function openEditor(category, name) {
  _editCategory = category;
  _editName = name;
  document.getElementById('uf-title').textContent = `Edit: ${name}`;
  document.getElementById('uf-path').textContent = `${category}/${name}`;
  document.getElementById('uf-textarea').value = '';
  ufSetStatus('Loading...');
  document.getElementById('uf-overlay').classList.add('open');

  try {
    const r = await fetch(`/api/file?file=${encodeURIComponent(name)}&category=${encodeURIComponent(category)}`);
    if (!r.ok) {
      const data = await r.json();
      ufSetStatus(`Failed to load: ${data.error || r.status}`, false);
      return;
    }
    const text = await r.text();
    document.getElementById('uf-textarea').value = text;
    ufSetStatus('');
  } catch (e) {
    ufSetStatus('Error: ' + e.message, false);
  }
}

"""

_JS_ACTIONS = """function wireButtons() {
  document.querySelectorAll('input[type=file][data-category]').forEach(inp => {
    if (inp._wired) return;
    inp._wired = true;
    inp.addEventListener('change', () => {
      const cat = inp.dataset.category;
      if (inp.files.length) { _pendingUploadFiles.set(cat, inp.files[0]); }
      else { _pendingUploadFiles.delete(cat); }
    });
  });
  restoreUploadSelections();
  document.querySelectorAll('button[data-action]').forEach(btn => {
    if (btn._wired) return;
    btn._wired = true;
    btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      if (action === 'toggle_lib') {
        // Local UI-only toggle -- no server round-trip, so skip the
        // postAction/refreshStatus flow below entirely.
        const cat = btn.dataset.category;
        if (_libOpen.has(cat)) { _libOpen.delete(cat); } else { _libOpen.add(cat); }
        applyLibraryCollapseState();
        return;
      }
      if (action === 'toggle_diskimg_card') {
        // Local UI-only toggle (v2.15.0) -- unlike the library cards
        // above, these 4 cards' own outer markup is server-rendered
        // once and never replaced wholesale by polling (only specific
        // child divs inside them get their innerHTML swapped), so
        // there's no need for a tracked-state Set reapplied on every
        // refresh -- toggling the class directly on this click is
        // enough and stays put.
        const card = btn.closest('.diskimg-card');
        if (!card) return;
        const open = card.classList.toggle('collapsed') === false;
        btn.textContent = open ? 'Hide' : 'Show';
        return;
      }
      if (action === 'diskimg_stop') {
        // v2.30.0: handled before the generic disable/finally below --
        // this button's enabled state belongs to syncDiskimgCardButtons(),
        // not to a blanket re-enable after the click.
        const kind = btn.dataset.kind;
        const label = _DISKIMG_KIND_LABELS[kind] || kind;
        const cur = _diskimgCurrentJob;
        let msg = `Stop the running ${label}? The destination will be left partial and unusable.`;
        if (cur && cur.phase === 'verifying') msg = `Stop verifying this ${label}? The copy already on disk is kept as is.`;
        else if (kind === 'backup') msg = 'Stop the running Backup? The partial backup file will be deleted.';
        else if (kind === 'format') msg = 'Stop the running Format? The drive will be left partly wiped, without a usable partition, until it is formatted again.';
        if (!confirm(msg)) return;
        btn.disabled = true;
        btn.textContent = 'Stopping...';
        try {
          await postDiskimg('/api/diskimg/job/cancel', {});
        } finally {
          await pollDiskimgJob();
          syncDiskimgCardButtons();
        }
        return;
      }
      if (action === 'diskimg_reset') {
        btn.disabled = true;
        try {
          await resetDiskimgCard(btn.dataset.kind);
        } finally {
          await pollDiskimgJob();
          syncDiskimgCardButtons();
        }
        return;
      }
      if (action === 'router') {
        // Local, synchronous open (so popup blockers allow it) of the url
        // pollGateway() stored. noopener: this is another device's page.
        if (btn.dataset.url) { window.open(btn.dataset.url, '_blank', 'noopener'); }
        return;
      }
      btn.disabled = true;
      try {
        if (action === 'install') {
          if (!confirm(`Install ${btn.dataset.name}? This will restart its service.`)) { btn.disabled = false; return; }
          await postAction({action: 'install', category: btn.dataset.category, name: btn.dataset.name, confirm: true});
        } else if (action === 'uninstall') {
          // No confirmation -- see the "NO CONFIRMATIONS" banner above
          // the Components card. Stops and removes the service (unit,
          // symlink, and installed files) immediately.
          await postAction({action: 'uninstall', category: btn.dataset.category});
        } else if (action === 'start') {
          // No confirmation -- fires immediately, see the banner above
          // the Components card. Starts the service if stopped, or
          // restarts it if already running.
          await postAction({action: 'start', service: btn.dataset.service});
        } else if (action === 'stop') {
          // No confirmation -- fires immediately, see the banner above
          // the Components card.
          await postAction({action: 'stop', service: btn.dataset.service});
        } else if (action === 'go') {
          if (btn.dataset.path) {
            window.open(`http://${location.hostname}${btn.dataset.path}`, '_blank');
          } else {
            window.open(`http://${location.hostname}:${btn.dataset.port}`, '_blank');
          }
          btn.disabled = false;
        } else if (action === 'install_config') {
          if (!confirm(`Install ${btn.dataset.name} as the active config? This will restart the Dashboard if it's installed.`)) { btn.disabled = false; return; }
          await postAction({action: 'install_config', name: btn.dataset.name});
        } else if (action === 'gh_check') {
          await postAction({action: 'gh_check'});
        } else if (action === 'quiet') {
          if (!confirm('Quiet the system? Pauses SysMon, the Dashboard, 44helper and the watchdog timer (whichever are running) until you press Restore -- auto-restore after 30 min. Radio, Asterisk, the bridges, Allmon3, SSH and wifimon stay up.')) { btn.disabled = false; return; }
          await postAction({action: 'quiet'});
        } else if (action === 'restore') {
          await postAction({action: 'restore'});
        } else if (action === 'fu_dismiss') {
          await postAction({action: 'fu_dismiss'});
        } else if (action === 'full_update') {
          const p = _fuState && _fuState.plan;
          const comps = p ? p.components.filter(c => c.status === 'update').map(c => `  ${c.name}: ${c.note}`) : [];
          const scr = p ? p.scripts.map(n => `  ${n} (Scripts library only, not run)`) : [];
          if (!confirm('Full Update from GitHub?\\n\\n' + (comps.length ? 'One at a time:\\n' + comps.join('\\n') + '\\n\\n' : '') +
                       (scr.length ? 'New scripts:\\n' + scr.join('\\n') + '\\n\\n' : '') +
                       'GitHub is checked again first. The web tools are paused, each component is uninstalled and the new version installed; one that fails is put back and skipped. instmon goes last -- this page reconnects after it restarts.')) { btn.disabled = false; return; }
          await postAction({action: 'full_update', confirm: true});
        } else if (action === 'gh_update') {
          if (!confirm(`Download ${btn.dataset.name} from GitHub into the ${btn.dataset.category} library? It is checked before it is saved, and nothing runs or installs until you press its button.`)) { btn.disabled = false; return; }
          await postAction({action: 'gh_update', name: btn.dataset.name, confirm: true});
        } else if (action === 'run_script') {
          if (btn.dataset.uninstaller === '1') {
            if (!confirm(`Run ${btn.dataset.name}? This removes the ASL-DVS stack from this node.`)) { btn.disabled = false; return; }
            if (!confirm('Really sure? Services and installed files will be removed.')) { btn.disabled = false; return; }
            await postAction({action: 'run_script', name: btn.dataset.name, confirm: true});
          } else if (btn.dataset.installer === '1') {
            // Full-stack shell installer: same confirm bar as the
            // per-component Install/Reinstall buttons, since it can
            // restart both the Dashboard and SysMon services.
            if (!confirm(`Run ${btn.dataset.name}? This installs/updates the Dashboard and SysMon services and may restart them. Runs non-interactively -- no terminal prompts.`)) { btn.disabled = false; return; }
            // Only needed for a bare node with no existing config and
            // no legacy dvswitch.conf to migrate -- leave blank for
            // an update or a migratable config and the script won't
            // touch them. Cancelling either prompt aborts the whole
            // run; leaving a prompt blank just omits that one var.
            const callsign = prompt('Callsign for first-run setup (leave blank if not needed):', '');
            if (callsign === null) { btn.disabled = false; return; }
            const node = prompt('Node number for first-run setup (leave blank if not needed):', '');
            if (node === null) { btn.disabled = false; return; }
            const body = {action: 'run_script', name: btn.dataset.name, confirm: true};
            if (callsign.trim()) body.auto_callsign = callsign.trim();
            if (node.trim()) body.auto_node = node.trim();
            await postAction(body);
          } else {
            if (!confirm(`Run ${btn.dataset.name}? This executes the script with instmon's own privileges.`)) { btn.disabled = false; return; }
            await postAction({action: 'run_script', name: btn.dataset.name, confirm: true});
          }
        } else if (action === 'edit') {
          await openEditor(btn.dataset.category, btn.dataset.name);
        } else if (action === 'download') {  // [PHASE 3]
          window.location.href = '/api/download?file=' + encodeURIComponent(btn.dataset.name) + '&category=' + encodeURIComponent(btn.dataset.category);
        } else if (action === 'delete') {
          if (!confirm(`Delete ${btn.dataset.name} from the library?`)) { btn.disabled = false; return; }
          await postAction({action: 'delete', category: btn.dataset.category, name: btn.dataset.name});
        } else if (action === 'upload') {
          const cat = btn.dataset.category;
          const fileInput = document.getElementById('file-' + cat);
          const msg = document.getElementById('upmsg-' + cat);
          if (!fileInput || !fileInput.files.length) {
            if (msg) msg.textContent = 'Choose a file first.';
            btn.disabled = false;
            return;
          }
          async function doUpload(force) {
            const fd = new FormData();
            fd.append('category', cat);
            fd.append('file', fileInput.files[0]);
            if (force) fd.append('force', '1');
            const r = await fetch('/api/upload', {method: 'POST', headers: {'X-Requested-With': 'XMLHttpRequest'}, body: fd});
            const data = await r.json();
            return {r, data};
          }
          if (msg) msg.textContent = 'Uploading...';
          let {r, data} = await doUpload(false);
          if (!r.ok && data.mismatch) {
            const proceed = confirm(
              (data.error || 'Filename does not match this category.') +
              '\\n\\nUpload anyway?'
            );
            if (proceed) {
              ({r, data} = await doUpload(true));
            } else {
              if (msg) msg.textContent = 'Upload cancelled.';
              btn.disabled = false;
              return;
            }
          }
          if (msg) msg.textContent = r.ok ? `Staged: ${data.name}` : (data.error || 'Upload failed');
          showPopup(data.message || data.error || (r.ok ? 'Uploaded.' : 'Upload failed'), data.level || (r.ok ? 'ok' : 'err'));
          if (r.ok) { fileInput.value = ''; _pendingUploadFiles.delete(cat); }
        } else if (action === 'save_alternate') {
          await postAction({action: 'save_alternate'});
        } else if (action === 'comms_restart') {
          if (!confirm('Stop Asterisk, Analog_Bridge, MMDVM_Bridge, STFU, and Allmon3, pause 3s, then start them back up? All active calls/links on this node will drop for the duration.')) { btn.disabled = false; return; }
          await postAction({action: 'comms_restart'});
        } else if (action === 'reboot') {
          if (!confirm('Reboot this Pi? Every service on it -- including this instmon page -- goes unreachable until it finishes booting back up.')) { btn.disabled = false; return; }
          if (!confirm('Really sure? This is a full node reboot, not just instmon.')) { btn.disabled = false; return; }
          await postAction({action: 'reboot'});
        } else if (action === 'shutdown') {
          if (!confirm('Shut down this Pi? It will power off and stay off until someone power-cycles it in person (or via a smart PDU).')) { btn.disabled = false; return; }
          if (!confirm('Really sure? There is no remote way to turn it back on from this page once it powers off.')) { btn.disabled = false; return; }
          await postAction({action: 'shutdown'});
        } else if (action === 'diskimg_backup_start') {
          const destSel = document.getElementById('diskimg-backup-dest');
          const dest = destSel && destSel.value;
          if (!dest) { alert('Pick a destination drive first.'); btn.disabled = false; return; }
          const labelEl = document.getElementById('diskimg-backup-label');
          const label = labelEl ? labelEl.value : '';
          const shrinkEl = document.getElementById('diskimg-backup-shrink');
          const shrink = shrinkEl ? shrinkEl.checked : false;
          const verifyEl = document.getElementById('diskimg-backup-verify');
          const verify = verifyEl ? verifyEl.checked : false;
          const verifyAlgoEl = document.getElementById('diskimg-backup-verify-algo');
          const verifyAlgo = verifyAlgoEl ? verifyAlgoEl.value : 'sha256';
          const encryptEl = document.getElementById('diskimg-backup-encrypt');
          const encrypt = encryptEl ? encryptEl.checked : false;
          const passphraseEl = document.getElementById('diskimg-backup-passphrase');
          const passphrase = passphraseEl ? passphraseEl.value : '';
          const freezeEl = document.getElementById('diskimg-backup-freeze');
          const freeze = freezeEl ? freezeEl.checked : false;
          const bestEffortEl = document.getElementById('diskimg-backup-best-effort');
          const bestEffort = bestEffortEl ? bestEffortEl.checked : false;
          const backendEl = document.getElementById('diskimg-backup-backend');
          const backend = backendEl ? backendEl.value : 'dd';
          const throttleEl = document.getElementById('diskimg-backup-throttle');
          const throttleRateMb = throttleEl && throttleEl.value ? Number(throttleEl.value) : null;
          if (encrypt && !passphrase) { alert('Enter a passphrase to encrypt this backup.'); btn.disabled = false; return; }
          if (encrypt && (shrink || verify)) { alert('Encrypt cannot be combined with Shrink to fit or Verify after copy -- turn those off first.'); btn.disabled = false; return; }
          if (encrypt && backend === 'ddrescue') { alert('Encrypt cannot be combined with the resilient (ddrescue) backend -- turn one off first.'); btn.disabled = false; return; }
          if (encrypt && throttleRateMb) { alert('Encrypt cannot be combined with a bandwidth throttle yet -- turn one off first.'); btn.disabled = false; return; }
          const quiesceEl = document.getElementById('diskimg-backup-quiesce');
          const quiesce = quiesceEl ? quiesceEl.checked : false;
          if (!confirm(`Back up this Pi's whole boot disk onto ${dest}? This can take a long time and keeps running in the background.`)) { btn.disabled = false; return; }
          if (quiesce && !confirm(offAirWarning())) { btn.disabled = false; return; }
          if (encrypt && !confirm("There is no way to recover this backup without the passphrase you just entered -- if it's lost, the backup is unusable. Continue?")) { btn.disabled = false; return; }
          if (bestEffort && !confirm('Continue past read errors is ticked -- an unreadable source sector will be padded with nulls and the backup will still report success. Continue?')) { btn.disabled = false; return; }
          if (!confirm('Really sure? Do not unplug the destination drive while this runs.')) { btn.disabled = false; return; }
          await postDiskimg('/api/diskimg/backup/start', {
            confirm: true, dest_device: dest, label: label, shrink: shrink, verify: verify,
            verify_algo: verifyAlgo, encrypt: encrypt, passphrase: passphrase, quiesce: quiesce,
            freeze: freeze, best_effort: bestEffort, backend: backend, throttle_rate_mb: throttleRateMb,
          });
          if (passphraseEl) passphraseEl.value = '';
        } else if (action === 'diskimg_backup_download') {
          window.location.href = '/api/diskimg/backup/download?name=' + encodeURIComponent(btn.dataset.name) + '&drive=' + encodeURIComponent(btn.dataset.drive);
        } else if (action === 'diskimg_backup_delete') {
          if (!confirm(`Delete backup ${btn.dataset.name}?`)) { btn.disabled = false; return; }
          await postDiskimg('/api/diskimg/backup/delete', {name: btn.dataset.name, drive: btn.dataset.drive});
        } else if (action === 'diskimg_unmount') {
          const dest = btn.dataset.dest;
          if (!confirm(`Unmount ${dest}? Any open files on it will be closed.`)) { btn.disabled = false; return; }
          await postDiskimg('/api/diskimg/unmount', {confirm: true, dest_device: dest});
        } else if (action === 'diskimg_format_start') {
          const destSel = document.getElementById('diskimg-format-dest');
          const dest = destSel && destSel.value;
          if (!dest) { alert('Pick a destination drive first.'); btn.disabled = false; return; }
          const fsSel = document.getElementById('diskimg-format-fs');
          const fsType = fsSel ? fsSel.value : 'ext4';
          const quickEl = document.getElementById('diskimg-format-quick');
          const quick = quickEl ? quickEl.checked : false;
          if (quick) {
            if (!confirm(`Quick-format ${dest} as ${fsType}? The old partition table and filesystem headers on ${dest} will be cleared and everything on it will become inaccessible. This cannot be undone.`)) { btn.disabled = false; return; }
            if (!confirm(`Really sure? ${dest} will end up as a single empty ${fsType} partition. Quick format is NOT a secure erase -- old data beyond the start of the drive stays on it and can be recovered with recovery tools.`)) { btn.disabled = false; return; }
          } else {
            if (!confirm(`Completely wipe ${dest}, then partition and format it as ${fsType}? This ERASES everything currently on ${dest} and cannot be undone.`)) { btn.disabled = false; return; }
            if (!confirm(`Really sure? ${dest} will end up as a single empty ${fsType} partition with nothing recoverable from what's on it now.`)) { btn.disabled = false; return; }
          }
          await postDiskimg('/api/diskimg/format/start', {confirm: true, dest_device: dest, fs_type: fsType, quick: quick});
        } else if (action === 'diskimg_clone_start') {
          const destSel = document.getElementById('diskimg-clone-dest');
          const dest = destSel && destSel.value;
          if (!dest) { alert('Pick a destination drive first.'); btn.disabled = false; return; }
          const verifyEl = document.getElementById('diskimg-clone-verify');
          const verify = verifyEl ? verifyEl.checked : false;
          const verifyAlgoEl = document.getElementById('diskimg-clone-verify-algo');
          const verifyAlgo = verifyAlgoEl ? verifyAlgoEl.value : 'sha256';
          const cQuiesceEl = document.getElementById('diskimg-clone-quiesce');
          const cQuiesce = cQuiesceEl ? cQuiesceEl.checked : false;
          const freezeEl = document.getElementById('diskimg-clone-freeze');
          const freeze = freezeEl ? freezeEl.checked : false;
          const bestEffortEl = document.getElementById('diskimg-clone-best-effort');
          const bestEffort = bestEffortEl ? bestEffortEl.checked : false;
          const directIoEl = document.getElementById('diskimg-clone-direct-io');
          const directIo = directIoEl ? directIoEl.checked : false;
          const backendEl = document.getElementById('diskimg-clone-backend');
          const backend = backendEl ? backendEl.value : 'dd';
          const throttleEl = document.getElementById('diskimg-clone-throttle');
          const throttleRateMb = throttleEl && throttleEl.value ? Number(throttleEl.value) : null;
          if (backend === 'ddrescue' && throttleRateMb) { alert('The resilient (ddrescue) backend cannot be combined with a bandwidth throttle -- turn one off first.'); btn.disabled = false; return; }
          if (!confirm(`Clone this Pi's whole boot disk directly onto ${dest}? This ERASES everything currently on ${dest} and cannot be undone.`)) { btn.disabled = false; return; }
          if (cQuiesce && !confirm(offAirWarning())) { btn.disabled = false; return; }
          if (bestEffort && !confirm('Continue past read errors is ticked -- an unreadable source sector will be padded with nulls and the clone will still report success. Continue?')) { btn.disabled = false; return; }
          if (!confirm(`Really sure? ${dest} will become a byte-for-byte copy of this Pi's boot disk.`)) { btn.disabled = false; return; }
          await postDiskimg('/api/diskimg/clone/start', {
            confirm: true, dest_device: dest, verify: verify, verify_algo: verifyAlgo, quiesce: cQuiesce,
            freeze: freeze, best_effort: bestEffort, direct_io: directIo, backend: backend,
            throttle_rate_mb: throttleRateMb,
          });
        } else if (action === 'diskimg_restore_start') {
          const imgSel = document.getElementById('diskimg-restore-image');
          const destSel = document.getElementById('diskimg-restore-dest');
          const imgVal = imgSel && imgSel.value;
          const dest = destSel && destSel.value;
          if (!imgVal) { alert('Pick a backup to restore first.'); btn.disabled = false; return; }
          if (!dest) { alert('Pick a destination drive first.'); btn.disabled = false; return; }
          const sepIdx = imgVal.indexOf('::');
          const imgName = imgVal.slice(0, sepIdx);
          const imgDrive = imgVal.slice(sepIdx + 2);
          const verifyEl = document.getElementById('diskimg-restore-verify');
          const verify = verifyEl ? verifyEl.checked : false;
          const verifyAlgoEl = document.getElementById('diskimg-restore-verify-algo');
          const verifyAlgo = verifyAlgoEl ? verifyAlgoEl.value : 'sha256';
          const passphraseEl = document.getElementById('diskimg-restore-passphrase');
          const passphrase = passphraseEl ? passphraseEl.value : '';
          const throttleEl = document.getElementById('diskimg-restore-throttle');
          const throttleRateMb = throttleEl && throttleEl.value ? Number(throttleEl.value) : null;
          if (!confirm(`Restore ${imgName} onto ${dest}? This ERASES everything currently on ${dest} and cannot be undone.`)) { btn.disabled = false; return; }
          if (!confirm(`Really sure? ${dest} will become a byte-for-byte copy of that backup image.`)) { btn.disabled = false; return; }
          await postDiskimg('/api/diskimg/restore/start', {
            confirm: true, name: imgName, drive: imgDrive, dest_device: dest, verify: verify,
            verify_algo: verifyAlgo, passphrase: passphrase, throttle_rate_mb: throttleRateMb,
          });
          if (passphraseEl) passphraseEl.value = '';
        } else if (action === 'diskimg_schedule_save') {
          const enabled = document.getElementById('diskimg-sched-enabled').checked;
          const interval_hours = parseFloat(document.getElementById('diskimg-sched-interval').value);
          const dest_device = document.getElementById('diskimg-sched-dest').value;
          const retention = parseInt(document.getElementById('diskimg-sched-retention').value, 10);
          const shrink = document.getElementById('diskimg-sched-shrink').checked;
          const verify = document.getElementById('diskimg-sched-verify').checked;
          const schedQuiesce = document.getElementById('diskimg-sched-quiesce').checked;
          const label = document.getElementById('diskimg-sched-label').value;
          if (enabled && !dest_device) { alert('Pick a destination drive first.'); btn.disabled = false; return; }
          if (enabled && !confirm(`Enable scheduled backups every ${interval_hours}h to ${dest_device}, keeping the newest ${retention}? This will automatically write to (and prune old backups from) that drive whenever it's plugged in at the scheduled time, with no further confirmation.`)) { btn.disabled = false; return; }
          if (enabled && schedQuiesce && !confirm('UNATTENDED PAUSE is ticked.\\n\\nEvery scheduled backup will stop Asterisk, the bridges, the dashboards and the watchdog on its own, at the scheduled time, with nobody watching. The node will be OFF THE AIR for the whole job each time.\\n\\nServices are restarted automatically when the job ends.\\n\\nContinue?')) { btn.disabled = false; return; }
          await postDiskimg('/api/diskimg/schedule', {confirm: true, enabled, interval_hours, dest_device, retention, shrink, verify, quiesce: schedQuiesce, label});
          pollDiskimgSchedule();
        }
        await pollDiskimgJob();
        await refreshStatus();
        await pollDrives();
        await pollDiskimgBackups();
      } finally {
        btn.disabled = false;
      }
    });
  });
  const saveBtn = document.getElementById('save-alt-btn');
  if (saveBtn && !saveBtn._wired) {
    saveBtn._wired = true;
    saveBtn.addEventListener('click', async () => {
      saveBtn.disabled = true;
      await postAction({action: 'save_alternate'});
      await refreshStatus();
      saveBtn.disabled = false;
    });
  }
}

"""

_JS_AUTH = """// Fetch wrapper: any 401 from an /api/* call (other than the login
// call itself) means the session cookie is missing/expired -- show the
// login screen instead of letting the app keep polling into failures.
const _rawFetch = window.fetch.bind(window);
window.fetch = async function(input, init) {
  const resp = await _rawFetch(input, init);
  const url = typeof input === 'string' ? input : ((input && input.url) || '');
  if (resp.status === 401 && url.startsWith('/api/') && url !== '/api/login') {
    _onAuthLost();
  }
  return resp;
};

// v2.36.1: a login lost mid-session reloads the page instead of opening
// the login box over the stale page (mangled text, and _startApp() would
// run a second time after login, doubling every poll timer). The message
// rides across the reload in sessionStorage and the boot probe below shows
// it. Guarded so a burst of 401s reloads once; the boot probe's own 401
// uses _rawFetch and never comes through here, so there's no reload loop.
let _authLostReloading = false;
const _AUTH_MSG_KEY = 'instmon_auth_msg';
function _onAuthLost() {
  if (_authLostReloading) return;
  _authLostReloading = true;
  try { sessionStorage.setItem(_AUTH_MSG_KEY, 'Session expired. Please log in again.'); } catch (e) {}
  location.reload();
}

function _takeAuthMsg() {
  let msg = '';
  try {
    msg = sessionStorage.getItem(_AUTH_MSG_KEY) || '';
    sessionStorage.removeItem(_AUTH_MSG_KEY);
  } catch (e) {}
  return msg;
}

function showLoginScreen(msg) {
  const scr = document.getElementById('login-screen');
  const err = document.getElementById('login-err');
  if (err) err.textContent = msg || '';
  if (scr) scr.classList.add('open');
  const pw = document.getElementById('login-pw');
  if (pw) { pw.value = ''; pw.focus(); }
}

function hideLoginScreen() {
  const scr = document.getElementById('login-screen');
  if (scr) scr.classList.remove('open');
}

async function _doLogin(ev) {
  ev.preventDefault();
  const pw = document.getElementById('login-pw');
  const btn = document.getElementById('login-btn');
  const err = document.getElementById('login-err');
  const password = pw ? pw.value : '';
  if (btn) btn.disabled = true;
  if (err) err.textContent = '';
  try {
    const r = await _rawFetch('/api/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: password}),
    });
    const data = await r.json();
    if (r.ok && data.ok) {
      hideLoginScreen();
      _startApp();
    } else {
      if (err) err.textContent = (data && data.error) || 'Login failed.';
    }
  } catch (e) {
    if (err) err.textContent = 'Login failed: ' + e;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function doLogout() {
  try {
    await fetch('/api/logout', {method: 'POST', headers: {'X-Requested-With': 'XMLHttpRequest'}});
  } catch (e) {
    // ignore -- reload happens regardless
  }
  location.reload();
}
"""

_JS_INIT = """// [PHASE 3] Backup button
document.getElementById('backup-btn').addEventListener('click', function() {
  window.location.href = '/api/backup';
});

// Disk Image & Clone: manual on-demand drive refresh (Stage 5) -- the
// 5s auto-poll already covers most cases, but this gives an immediate
// re-check right after physically plugging something in, rather than
// waiting out the rest of the interval.
document.getElementById('diskimg-refresh-btn').addEventListener('click', async function() {
  this.disabled = true;
  try {
    await pollDrives();
    await pollDiskimgBackups();
  } finally {
    this.disabled = false;
  }
});

// Command-preview fields (v2.9.0): refresh on any input that changes
// what would actually run. Text/password-ish inputs use 'input' (live
// as you type), selects and checkboxes use 'change'.
[['diskimg-backup-dest', 'change'], ['diskimg-backup-label', 'input'], ['diskimg-backup-encrypt', 'change'], ['diskimg-backup-quiesce', 'change'],
 ['diskimg-backup-best-effort', 'change'], ['diskimg-backup-backend', 'change'], ['diskimg-backup-throttle', 'change']]
  .forEach(([id, evt]) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener(evt, () => scheduleDiskimgPreview('backup'));
  });
['diskimg-clone-dest', 'diskimg-clone-quiesce', 'diskimg-clone-best-effort', 'diskimg-clone-direct-io', 'diskimg-clone-backend', 'diskimg-clone-throttle'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', () => scheduleDiskimgPreview('clone'));
});
(function() {
  const el = document.getElementById('diskimg-format-dest');
  if (el) el.addEventListener('change', () => {
    scheduleDiskimgPreview('format');
    renderDiskimgFormatPrereqs(_diskimgLastDrives);
  });
})();
(function() {
  const el = document.getElementById('diskimg-format-quick');
  if (el) el.addEventListener('change', () => scheduleDiskimgPreview('format'));
})();
['diskimg-restore-image', 'diskimg-restore-dest', 'diskimg-restore-throttle'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', () => scheduleDiskimgPreview('restore'));
});

// v2.26.0: backend=ddrescue implies its own resilience strategy and
// can't be combined with best-effort/direct-io/throttle -- disable
// (not hide, so it's clear why) those controls whenever ddrescue is
// selected on Backup/Clone, and re-enable them otherwise. Mirrors the
// same mutual-exclusion the server enforces in _diskimg_start_job/the
// handler validation, so the UI never shows an unchecked-but-ignored
// state or lets a request get built that the server would reject.
function _wireDdrescueExclusions(prefix) {
  const backendEl = document.getElementById(`diskimg-${prefix}-backend`);
  if (!backendEl) return;
  const dependents = ['best-effort', 'direct-io', 'throttle']
    .map(suffix => document.getElementById(`diskimg-${prefix}-${suffix}`))
    .filter(Boolean);
  const apply = () => {
    const isDdrescue = backendEl.value === 'ddrescue';
    dependents.forEach(el => {
      el.disabled = isDdrescue;
      if (isDdrescue && el.type === 'checkbox') el.checked = false;
      if (isDdrescue && el.tagName === 'SELECT') el.value = '';
    });
  };
  backendEl.addEventListener('change', () => { apply(); scheduleDiskimgPreview(prefix); });
  apply();
}
_wireDdrescueExclusions('backup');
_wireDdrescueExclusions('clone');

// v2.26.0 Stage 1: the freeze checkbox is a sub-option of quiesce --
// keep it disabled and unchecked whenever quiesce itself is off, on
// both Backup and Clone.
function _wireFreezeDependsOnQuiesce(prefix) {
  const quiesceEl = document.getElementById(`diskimg-${prefix}-quiesce`);
  const freezeEl = document.getElementById(`diskimg-${prefix}-freeze`);
  if (!quiesceEl || !freezeEl) return;
  const apply = () => {
    freezeEl.disabled = !quiesceEl.checked;
    if (!quiesceEl.checked) freezeEl.checked = false;
  };
  quiesceEl.addEventListener('change', apply);
  apply();
}
_wireFreezeDependsOnQuiesce('backup');
_wireFreezeDependsOnQuiesce('clone');

function _startApp() {
  applyLibraryCollapseState();
  wireButtons();
  // Skip poll ticks while the tab isn't visible -- no point hitting
  // the server every 2s/5s for a background tab, especially on the
  // travel node where bandwidth/battery can be tight. Catches up
  // immediately with one poll of each as soon as the tab becomes
  // visible again, rather than waiting out the rest of the interval.
  setInterval(() => { if (!document.hidden) pollLog(); }, 2000);
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 5000);
  setInterval(() => { if (!document.hidden) pollDrives(); }, 5000);
  // Job progress polls faster than everything else -- this is the one
  // panel someone is likely watching live while a multi-GB copy runs.
  setInterval(() => { if (!document.hidden) pollDiskimgJob(); }, 2000);
  setInterval(() => { if (!document.hidden) pollDiskimgBackups(); }, 5000);
  // Router button: the server caches its probe for 30s, so 15s is plenty.
  setInterval(() => { if (!document.hidden) pollGateway(); }, 15000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) { pollLog(); refreshStatus(); pollDrives(); pollDiskimgJob(); pollDiskimgBackups(); pollGateway(); }
  });
  pollLog();
  pollDrives();
  pollDiskimgJob();
  pollDiskimgBackups();
  pollGateway();
}

// Boot-time auth probe: reaching /api/whoami with a 200 IS the proof of
// a live session (the route itself sits behind the normal auth gate).
// Uses _rawFetch, not the wrapped fetch, so a 401 here shows a plain
// login screen rather than a spurious "session expired" message.
_rawFetch('/api/whoami').then((r) => {
  const msg = _takeAuthMsg();
  if (r.ok) { hideLoginScreen(); _startApp(); }
  else { showLoginScreen(msg); }
}).catch(() => { showLoginScreen(_takeAuthMsg()); });
"""

_JS = (
    _JS_LOG_POLL
    + _JS_STATUS_TOAST
    + _JS_EDITOR
    + _JS_ACTIONS
    + _JS_AUTH
    + _JS_INIT
)


def render_page ():
    status =build_status ()
    quicklinks_html =render_quicklinks_html ()
    components_html =render_components_html (status ["components"],status ["library"])
    library_html =render_library_html (status ["library"])
    log_html ="-- System ready --\n"+f"instmon v{VERSION } ({DATE_STR }) backend online, {len (status ['components'])} component(s) tracked."
    return HTML_TEMPLATE .format (
    version =VERSION ,
    date =DATE_STR ,
    port =PORT ,
    css =_CSS ,
    script =_JS ,
    quicklinks_html =quicklinks_html ,
    components_html =components_html ,
    library_html =library_html ,
    github_html =_gh_summary_html (),
    log_html =log_html ,
    )


HTML_TEMPLATE ="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ASL-DVS Install Monitor &mdash; instmon</title>
<style>
{css}</style>
</head>
<body>
<header>
  <div class="hdr-left">
    <div class="logo">ASL-DVS Install Monitor</div>
    <div class="logo-sub">Node Software Installer &amp; Component Manager</div>
  </div>
  <div class="hdr-right">
    <span id="hdr-version">v{version}</span>
    <span class="hdr-meta">{date} &middot; port {port}</span>
    <button id="logout-btn" onclick="doLogout()">Log Out</button>
  </div>
</header>
<div id="login-screen">
  <div id="login-card">
    <h2>instmon Login</h2>
    <form onsubmit="_doLogin(event)">
      <input id="login-pw" type="password" autocomplete="current-password" placeholder="Root password" required>
      <button id="login-btn" type="submit">Log In</button>
    </form>
    <div id="login-err"></div>
  </div>
</div>
<div class="wrap">

<div id="fu-banners"></div>

<div class="hdr">Quick Links</div>
<div class="card">
  <div class="row">{quicklinks_html}
  </div>
</div>

<div class="hdr">GitHub Updates</div>
<div class="card">
  <div class="row">
    <button data-action="gh_check">Check GitHub</button>
    <button class="b-comms" id="fu-btn" data-action="full_update" disabled>Full Update</button>
    <span id="gh-summary" class="small">{github_html}</span>
  </div>
  <div class="small muted" style="margin-top:.35rem">
    Full Update: pauses the web tools, downloads and checks every newer file first, then uninstalls the old and
    installs the new one component at a time (instmon last). A component that fails is put back, skipped and
    listed at the end. New install scripts only go to the Scripts library -- they are never run for you.</div>
  <div id="fu-progress"></div>
  <div id="fu-plan"></div>
  <div class="row" style="margin-top:.6rem">
    <button class="b-comms" id="quiet-btn" data-action="quiet">Quiet System</button>
    <button id="restore-btn" data-action="restore" disabled>Restore</button>
    <span class="small muted">Before a big upload or install on a small Pi: pauses SysMon, the Dashboard, 44helper
    and the watchdog timer. Radio, Asterisk, the bridges, Allmon3, SSH and wifimon stay up.</span>
  </div>
</div>

<div class="hdr">Components</div>
<div class="no-confirm-banner">NO CONFIRMATIONS -- Stop and Uninstall act immediately, no prompt.</div>
<div id="components">{components_html}
</div>

<div class="hdr">Scripts &amp; Configuration Library</div>
<div class="small muted" style="margin-bottom:.4rem">
  Run shell scripts or manage alternative configuration files. Per-component version
  libraries (Dashboard, SysMon, etc.) now live inside their component's card above.</div>
<div id="library">{library_html}
</div>

<div class="hdr">Backup &amp; Export</div>  <!-- [PHASE 3] -->
<div class="card">
  <div class="row">
    <button id="backup-btn" style="background:var(--grn);color:#070b10;border-color:var(--grn)">Download Full Backup (ZIP)</button>
    <span class="small muted">Archive all files in the library directory.</span>
  </div>
</div>

<div class="hdr">Disk Image &amp; Clone</div>  <!-- v2.10.0-2.12.0: broken into 4 cards (Full Format, Backup, Clone, Restore) sharing one drives/deps panel and one job engine; each card gets its own command-preview field, its own rolling terminal console, and shows an idle placeholder whenever the running job (if any) belongs to a different card -->
<div class="card">
  <div class="small muted" style="margin-bottom:.4rem">
    Images/formats the Pi's whole boot disk or an attached USB drive
    (including an SD card in a USB adapter). Not the same as Backup
    &amp; Export above, which archives instmon's own library directory.</div>
  <div id="diskimg-deps" class="small">Checking dependencies&hellip;</div>
  <div class="row" style="justify-content:space-between">
    <span class="small muted">Attached drives refresh automatically every 5s.</span>
    <button id="diskimg-refresh-btn">Refresh Now</button>
  </div>
</div>

<div class="hdr">Full Format</div>
<div class="card danger-card diskimg-card collapsed" data-diskimg-key="format">
  <button class="diskimg-toggle" data-action="toggle_diskimg_card" data-key="format">Show</button>
  <div class="diskimg-card-body">
  <div class="small muted" style="margin-bottom:.4rem">
    Wipes the destination drive completely (zero-fill), then writes a
    fresh GPT partition table with a single partition and formats it.
    Use this to prep a blank SD card/USB drive from scratch -- not for
    the Pi's own boot disk, which is never selectable here. Tick Quick
    format to skip the full zero-fill and clear only the start of the
    drive (old partition table and filesystem headers) -- much faster,
    but the rest of the old data stays on the drive, so it is not a
    secure erase.</div>
  <div class="small muted" style="margin:.2rem 0 .2rem">Attached Drives</div>
  <div id="diskimg-drives-table" class="small muted">Loading attached drives&hellip;</div>
  <div class="row" style="margin-top:.6rem">
    <select id="diskimg-format-dest"><option value="">Loading drives&hellip;</option></select>
    <select id="diskimg-format-fs">
      <option value="ext4" selected>ext4 (recommended)</option>
      <option value="fat32">FAT32</option>
      <option value="exfat">exFAT</option>
    </select>
    <label class="small muted" style="white-space:nowrap" title="Clears only the start of the drive (old partition table and filesystem headers), then partitions and formats. Takes seconds instead of the drive's full write time. NOT a secure erase: the rest of the old data stays on the drive."><input type="checkbox" id="diskimg-format-quick"> Quick format</label>
    <button class="b-danger" data-action="diskimg_format_start">Format</button>
    <button class="b-danger" data-action="diskimg_stop" data-kind="format" disabled title="Nothing is running on this card.">Stop</button>
    <button data-action="diskimg_reset" data-kind="format" title="Clear this card's last result and put its options back to their defaults for another try.">Reset</button>
  </div>
  <div id="diskimg-format-prereqs" class="small" style="margin-top:.3rem">Pick a destination drive to check prerequisites.</div>
  <div class="small muted">ext4: Linux-native, journaled (safer against corruption if the card is pulled without unmounting), no file-size limit -- best choice for a drive that lives on this Pi or is read from other Linux tools. FAT32: read/write on virtually anything, but individual files over 4GB will fail to write -- a problem if this drive will ever hold a raw disk-image backup. exFAT: no practical file-size limit and reads/writes on Windows/macOS/Linux, but not journaled.</div>
  <input type="text" id="diskimg-format-cmd" class="diskimg-cmd placeholder" readonly value="Pick a destination drive to preview the command">
  <div id="diskimg-format-cmd-note" class="diskimg-cmd-note"></div>

  <div id="diskimg-job-format" style="margin-top:.5rem"></div>
  <div id="diskimg-console-format" class="diskimg-console placeholder">(no job running)</div>
  </div>
</div>

<div class="hdr">Backup</div>
<div class="card diskimg-card collapsed" data-diskimg-key="backup">
  <button class="diskimg-toggle" data-action="toggle_diskimg_card" data-key="backup">Show</button>
  <div class="diskimg-card-body">
  <div class="row" style="margin-top:.5rem">
    <select id="diskimg-backup-dest"><option value="">Loading drives&hellip;</option></select>
    <input type="text" id="diskimg-backup-label" placeholder="optional label" style="max-width:10rem">
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-backup-shrink"> Shrink to fit</label>
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-backup-verify"> Verify after copy</label>
    <select id="diskimg-backup-verify-algo" title="Hash algorithm for Verify after copy">
      <option value="sha256" selected>sha256</option>
      <option value="blake2b">blake2b (faster)</option>
    </select>
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-backup-encrypt"> Encrypt</label>
    <label class="small muted diskimg-quiesce" style="white-space:nowrap" title="Stops the watchdog, the suite dashboards, Asterisk and the bridges while the copy runs, so far fewer writes are in flight. The node is OFF THE AIR for the whole job. The image is still crash-consistent, not a filesystem snapshot."><input type="checkbox" id="diskimg-backup-quiesce"> Pause node services during copy</label>
    <input type="password" id="diskimg-backup-passphrase" placeholder="passphrase" style="max-width:9rem" autocomplete="new-password">
    <button class="b-danger" data-action="diskimg_backup_start">Create Backup</button>
    <button class="b-danger" data-action="diskimg_stop" data-kind="backup" disabled title="Nothing is running on this card.">Stop</button>
    <button data-action="diskimg_reset" data-kind="backup" title="Clear this card's last result and put its options back to their defaults for another try.">Reset</button>
  </div>
  <div class="row" style="margin-top:.3rem">
    <label class="small muted" style="white-space:nowrap" title="Sub-option of Pause node services -- freezes the root filesystem for the copy so the image is crash-consistent without a snapshot. Requires Pause node services to be ticked."><input type="checkbox" id="diskimg-backup-freeze" disabled> Freeze filesystem during copy</label>
    <label class="small muted" style="white-space:nowrap" title="Continue past a read error on the source instead of aborting the backup. Skipped sectors are padded with nulls."><input type="checkbox" id="diskimg-backup-best-effort"> Continue past read errors</label>
    <select id="diskimg-backup-backend" title="Copy backend">
      <option value="dd" selected>Standard (dd)</option>
      <option value="ddrescue">Resilient (ddrescue)</option>
    </select>
    <select id="diskimg-backup-throttle" title="Bandwidth throttle">
      <option value="" selected>No throttle</option>
      <option value="5">5 MB/s</option>
      <option value="10">10 MB/s</option>
      <option value="20">20 MB/s</option>
    </select>
  </div>
  <textarea id="diskimg-backup-cmd" class="diskimg-cmd placeholder" readonly rows="1" spellcheck="false">Pick a destination drive to preview the command</textarea>
  <div class="diskimg-quiesce-note">Pausing services reduces in-flight writes; it is not a filesystem snapshot. The image stays crash-consistent &mdash; ext4 replays its journal on the first boot of a restored card. sysmon keeps running so the node stays observable.</div>
  <div id="diskimg-backup-cmd-note" class="diskimg-cmd-note"></div>
  <div class="small muted">Shrink to fit: after copying, shrink the last partition's filesystem to its minimum size and truncate the file to match (smaller backup, slower -- needs resize2fs/parted; skipped automatically if the disk layout doesn't support it). Verify after copy: re-reads both sides and compares checksums before declaring success (slower, catches silent corruption dd's own exit code wouldn't); blake2b is faster than sha256 at the same integrity guarantee for this use. Encrypt: AES-256 encrypts the backup file with the given passphrase (openssl enc, PBKDF2) -- there's no way to recover it without that passphrase, so keep it somewhere safe; can't be combined with Shrink to fit or Verify after copy. Freeze filesystem during copy: pauses writes to this Pi's own root filesystem for the duration of the copy so the image is crash-consistent without needing a real snapshot; only offered alongside Pause node services. Continue past read errors: skips and nulls-out unreadable sectors on the source instead of aborting -- off by default, since a failed backup is a clearer signal than a silently incomplete one. Resilient (ddrescue): retries bad sectors instead of skipping them; can't be combined with Encrypt or a bandwidth throttle. Bandwidth throttle: caps the copy's write speed to go easier on a small/shared-bus board -- runs as a shell pipeline that does not currently survive an instmon restart.</div>
  <div id="diskimg-job-backup" style="margin-top:.5rem"></div>
  <div id="diskimg-console-backup" class="diskimg-console placeholder">(no job running)</div>
  <div class="small muted" style="margin:.6rem 0 .2rem">Existing Backups</div>
  <div id="diskimg-backups" class="small muted">Loading&hellip;</div>
  <div class="small muted" style="margin:.6rem 0 .2rem">Scheduled Backups</div>
  <div class="row">
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-sched-enabled"> Enabled</label>
    <span class="small muted">every</span>
    <input type="number" id="diskimg-sched-interval" min="1" max="720" step="1" style="max-width:5rem" value="24">
    <span class="small muted">hours to</span>
    <select id="diskimg-sched-dest"><option value="">Loading drives&hellip;</option></select>
  </div>
  <div class="row" style="margin-top:.3rem">
    <span class="small muted">keep newest</span>
    <input type="number" id="diskimg-sched-retention" min="1" max="50" step="1" style="max-width:5rem" value="5">
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-sched-shrink"> Shrink to fit</label>
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-sched-verify"> Verify after copy</label>
    <label class="small muted diskimg-quiesce" style="white-space:nowrap" title="UNATTENDED: the node goes off the air on its own, at the scheduled time, with nobody watching. Services are restarted automatically when the job ends."><input type="checkbox" id="diskimg-sched-quiesce"> Pause node services during copy</label>
    <input type="text" id="diskimg-sched-label" placeholder="label" style="max-width:8rem" value="auto">
    <button data-action="diskimg_schedule_save">Save Schedule</button>
  </div>
  <div id="diskimg-schedule-status" class="small muted" style="margin-top:.3rem">Loading schedule&hellip;</div>
  </div>
</div>

<div class="hdr">Clone</div>
<div class="card diskimg-card collapsed" data-diskimg-key="clone">
  <button class="diskimg-toggle" data-action="toggle_diskimg_card" data-key="clone">Show</button>
  <div class="diskimg-card-body">
  <div class="row">
    <select id="diskimg-clone-dest"><option value="">Loading drives&hellip;</option></select>
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-clone-verify"> Verify after copy</label>
    <select id="diskimg-clone-verify-algo" title="Hash algorithm for Verify after copy">
      <option value="sha256" selected>sha256</option>
      <option value="blake2b">blake2b (faster)</option>
    </select>
    <label class="small muted diskimg-quiesce" style="white-space:nowrap" title="Stops the watchdog, the suite dashboards, Asterisk and the bridges while the copy runs, so far fewer writes are in flight. The node is OFF THE AIR for the whole job. The image is still crash-consistent, not a filesystem snapshot."><input type="checkbox" id="diskimg-clone-quiesce"> Pause node services during copy</label>
    <button class="b-danger" data-action="diskimg_clone_start">Clone Now</button>
    <button class="b-danger" data-action="diskimg_stop" data-kind="clone" disabled title="Nothing is running on this card.">Stop</button>
    <button data-action="diskimg_reset" data-kind="clone" title="Clear this card's last result and put its options back to their defaults for another try.">Reset</button>
    <span class="small muted">Direct copy, no backup file -- for a spare drive plugged in right now (e.g. an SD card in a USB adapter). Destination must be unmounted first.</span>
  </div>
  <div class="row" style="margin-top:.3rem">
    <label class="small muted" style="white-space:nowrap" title="Sub-option of Pause node services -- freezes the root filesystem for the copy so the image is crash-consistent without a snapshot. Requires Pause node services to be ticked."><input type="checkbox" id="diskimg-clone-freeze" disabled> Freeze filesystem during copy</label>
    <label class="small muted" style="white-space:nowrap" title="Continue past a read error on the source instead of aborting the clone. Skipped sectors are padded with nulls."><input type="checkbox" id="diskimg-clone-best-effort"> Continue past read errors</label>
    <label class="small muted" style="white-space:nowrap" title="Bypass the page cache on the write side -- steadier write behavior on a small/shared-bus board."><input type="checkbox" id="diskimg-clone-direct-io"> Direct I/O</label>
    <select id="diskimg-clone-backend" title="Copy backend">
      <option value="dd" selected>Standard (dd)</option>
      <option value="ddrescue">Resilient (ddrescue)</option>
    </select>
    <select id="diskimg-clone-throttle" title="Bandwidth throttle">
      <option value="" selected>No throttle</option>
      <option value="5">5 MB/s</option>
      <option value="10">10 MB/s</option>
      <option value="20">20 MB/s</option>
    </select>
  </div>
  <textarea id="diskimg-clone-cmd" class="diskimg-cmd placeholder" readonly rows="1" spellcheck="false">Pick a destination drive to preview the command</textarea>
  <div class="diskimg-quiesce-note">Pausing services reduces in-flight writes; it is not a filesystem snapshot. The image stays crash-consistent &mdash; ext4 replays its journal on the first boot of a restored card. sysmon keeps running so the node stays observable.</div>
  <div class="small muted">Freeze filesystem during copy: pauses writes to this Pi's own root filesystem for the duration of the copy; only offered alongside Pause node services. Continue past read errors: skips and nulls-out unreadable sectors on the source instead of aborting -- off by default. Direct I/O: bypasses the page cache on the write side; offered here since Clone's destination is always a raw block device. Resilient (ddrescue): retries bad sectors instead of skipping them; can't be combined with Continue past read errors, Direct I/O, or a bandwidth throttle. Bandwidth throttle: caps the copy's write speed -- runs as a shell pipeline that does not currently survive an instmon restart.</div>
  <div id="diskimg-job-clone" style="margin-top:.5rem"></div>
  <div id="diskimg-console-clone" class="diskimg-console placeholder">(no job running)</div>
  </div>
</div>

<div class="hdr">Restore</div>
<div class="card diskimg-card collapsed" data-diskimg-key="restore">
  <button class="diskimg-toggle" data-action="toggle_diskimg_card" data-key="restore">Show</button>
  <div class="diskimg-card-body">
  <div class="row">
    <select id="diskimg-restore-image"><option value="">No backups available</option></select>
    <select id="diskimg-restore-dest"><option value="">Loading drives&hellip;</option></select>
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-restore-verify"> Verify after copy</label>
    <select id="diskimg-restore-verify-algo" title="Hash algorithm for Verify after copy">
      <option value="sha256" selected>sha256</option>
      <option value="blake2b">blake2b (faster)</option>
    </select>
    <input type="password" id="diskimg-restore-passphrase" placeholder="passphrase (if encrypted)" style="max-width:12rem" autocomplete="new-password">
    <select id="diskimg-restore-throttle" title="Bandwidth throttle (unencrypted backups only)">
      <option value="" selected>No throttle</option>
      <option value="5">5 MB/s</option>
      <option value="10">10 MB/s</option>
      <option value="20">20 MB/s</option>
    </select>
    <button class="b-danger" data-action="diskimg_restore_start">Restore</button>
    <button class="b-danger" data-action="diskimg_stop" data-kind="restore" disabled title="Nothing is running on this card.">Stop</button>
    <button data-action="diskimg_reset" data-kind="restore" title="Clear this card's last result and put its options back to their defaults for another try.">Reset</button>
  </div>
  <input type="text" id="diskimg-restore-cmd" class="diskimg-cmd placeholder" readonly value="Pick a backup and destination drive to preview the command">
  <div class="small muted" style="margin-top:.3rem">
    Writes to a spare drive only -- never onto the disk this Pi is currently running from. Destination must be unmounted first. Backups marked "encrypted" below need their passphrase entered here; Verify after copy and Bandwidth throttle aren't supported for those.</div>
  <div id="diskimg-job-restore" style="margin-top:.5rem"></div>
  <div id="diskimg-console-restore" class="diskimg-console placeholder">(no job running)</div>
  </div>
</div>

<div class="hdr">System &amp; Comms</div>
<div class="card danger-card">
  <div class="row">
    <button class="b-comms" data-action="comms_restart">Comms SERV Restart</button>
    <span class="small muted">Full stop, 3s pause, then start: Asterisk, Analog_Bridge, MMDVM_Bridge, STFU, Allmon3.</span>
  </div>
  <div class="row" style="margin-top:.5rem">
    <button class="b-danger" data-action="reboot">Reboot Pi</button>
    <button class="b-danger" data-action="shutdown">Shutdown Pi</button>
    <span class="small muted">Affects the whole node, not just instmon -- this page (and every other service on it) goes unreachable until it's back up. Shutdown needs physical/console access (or a smart PDU) to power back on.</span>
  </div>
</div>

<div class="hdr">Execution Log</div>
<div class="row" style="justify-content:flex-end;margin-bottom:.3rem">
  <button id="log-copy-btn" onclick="copyExecutionLog()">&#9111; Copy Log</button>
</div>
<div id="log">{log_html}</div>

</div>

<div id="popup-overlay"><div id="popup-box" class="popup-box"></div></div>

<!-- Editor Overlay (Stage 8/9, Library Card Rework Plan) -- replaces
     the old centered-dialog editor with the full-screen uf-overlay/
     uf-box pattern; see the CSS block above for what was adapted vs.
     dropped from sysmon's version. -->
<div id="uf-overlay" onclick="ufOverlayClick(event)">
  <div id="uf-box">
    <div id="uf-hdr">
      <span id="uf-title">Edit</span>
      <div id="uf-hdr-right">
        <button id="uf-save-btn" style="background:var(--cyn);color:#070b10;border-color:var(--cyn)" onclick="ufSave()">Save</button>
        <span id="uf-close" onclick="closeEditor()">&times;</span>
      </div>
    </div>
    <div id="uf-toolbar">
      <span id="uf-path">&mdash;</span>
      <span id="uf-status"></span>
      <button id="uf-copy-btn" onclick="ufCopy()">&#9111; Copy</button>
    </div>
    <textarea id="uf-textarea" spellcheck="false"></textarea>
  </div>
</div>

<script>
{script}</script>
</body>
</html>
"""


_ACTION_HANDLERS ={
"install":lambda self ,body :self ._action_install (body ),
"uninstall":lambda self ,body :self ._action_uninstall (body ),
"start":lambda self ,body :self ._action_start (body ),
"stop":lambda self ,body :self ._action_stop (body ),
"install_config":lambda self ,body :self ._action_install_config (body ),
"delete":lambda self ,body :self ._action_delete (body ),
"run_script":lambda self ,body :self ._action_run_script (body ),
"save_alternate":lambda self ,body :self ._action_save_alternate (),
"comms_restart":lambda self ,body :self ._action_comms_restart (body ),
"reboot":lambda self ,body :self ._action_reboot (body ),
"shutdown":lambda self ,body :self ._action_shutdown (body ),
"gh_check":lambda self ,body :self ._action_gh_check (body ),
"gh_update":lambda self ,body :self ._action_gh_update (body ),
"quiet":lambda self ,body :self ._action_quiet (body ),
"restore":lambda self ,body :self ._action_restore (body ),
"full_update":lambda self ,body :self ._action_full_update (body ),
"fu_dismiss":lambda self ,body :self ._action_fu_dismiss (body ),
}

# v2.37.0: the only actions accepted while Full Update runs.
_ACTIONS_DURING_FULL_UPDATE = ("fu_dismiss",)


_GET_ROUTES ={
"/":lambda self :self ._route_index (),
"/index.html":lambda self :self ._route_index (),
"/api/status":lambda self :self ._route_status (),
"/api/gateway":lambda self :self ._route_gateway (),
"/api/log":lambda self :self ._route_log (),
"/api/file":lambda self :self ._route_file (),
"/api/download":lambda self :self .handle_download (),
"/api/backup":lambda self :self .handle_backup (),
"/api/whoami":lambda self :self ._send_json (200 ,{"ok":True }),
"/api/diskimg/drives":lambda self :self ._route_diskimg_drives (),
"/api/diskimg/job":lambda self :self ._route_diskimg_job (),
"/api/diskimg/backup/list":lambda self :self ._route_diskimg_backup_list (),
"/api/diskimg/backup/download":lambda self :self ._route_diskimg_backup_download (),
"/api/diskimg/schedule":lambda self :self ._route_diskimg_schedule_get (),
}

_POST_ROUTES ={
"/api/upload":lambda self :self .handle_upload (),
"/api/action":lambda self :self .handle_action (),
"/api/file":lambda self :self .handle_file_write (),
"/api/diskimg/preview":lambda self :self .handle_diskimg_preview (),
"/api/diskimg/backup/start":lambda self :self .handle_diskimg_backup_start (),
"/api/diskimg/backup/delete":lambda self :self .handle_diskimg_backup_delete (),
"/api/diskimg/job/cancel":lambda self :self .handle_diskimg_job_cancel (),
"/api/diskimg/job/reset":lambda self :self .handle_diskimg_job_reset (),
"/api/diskimg/unmount":lambda self :self .handle_diskimg_unmount (),
"/api/diskimg/format/start":lambda self :self .handle_diskimg_format_start (),
"/api/diskimg/clone/start":lambda self :self .handle_diskimg_clone_start (),
"/api/diskimg/restore/start":lambda self :self .handle_diskimg_restore_start (),
"/api/diskimg/schedule":lambda self :self .handle_diskimg_schedule_set (),
}


class InstmonHandler (http .server .BaseHTTPRequestHandler ):
    server_version =f"instmon/{VERSION }"

    def send_response (self ,code ,message =None ):
        super ().send_response (code ,message )
        self .send_header ("X-Frame-Options","DENY")
        self .send_header ("X-Content-Type-Options","nosniff")
        self .send_header (
        "Content-Security-Policy",
        "default-src 'self'; frame-ancestors 'none'; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
        )
        self .send_header ("Referrer-Policy","no-referrer")


    def _send_json (self ,status ,payload ,extra_headers=None ):
        body =json .dumps (payload ).encode ("utf-8")
        self .send_response (status )
        self .send_header ("Content-Type","application/json; charset=utf-8")
        self .send_header ("Content-Length",str (len (body )))
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self .end_headers ()
        self .wfile .write (body )

    def _send_html (self ,status ,html ):
        body =html .encode ("utf-8")
        self .send_response (status )
        self .send_header ("Content-Type","text/html; charset=utf-8")
        self .send_header ("Content-Length",str (len (body )))
        self .end_headers ()
        self .wfile .write (body )

    def _error_json (self ,status ,message ):
        log_event (f"HTTP {status }: {message } ({self .command } {self .path })","err")
        self ._send_json (status ,{"error":message })

    def _session_token(self):
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(_SESSION_COOKIE_NAME + "="):
                return part[len(_SESSION_COOKIE_NAME) + 1:]
        return None

    def _require_auth(self):
        client_ip = self.client_address[0]
        remaining = _auth_lockout_remaining(client_ip)
        if remaining > 0:
            retry_after = int(remaining) + 1
            body = f"Too many failed login attempts. Try again in {retry_after}s.".encode()
            self.send_response(429)
            self.send_header("Retry-After", str(retry_after))
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._error_json(401, "Authentication required")


    def _find_library_file (self ,filename ,category =None ):
        if category and category in LIB_SUBDIRS :
            candidate =safe_join (LIB_SUBDIRS [category ],filename )
            return candidate if candidate and os .path .isfile (candidate )else None 
        for dir_path in LIB_SUBDIRS .values ():
            candidate =safe_join (dir_path ,filename )
            if candidate and os .path .isfile (candidate ):
                return candidate 
        return None 


    def _route_index (self ):
        self ._send_html (200 ,render_page ())

    def _route_status (self ):
        status =build_status ()
        self ._send_json (200 ,{
        "components_html":render_components_html (status ["components"],status ["library"]),
        "library_html":render_library_html (status ["library"]),
        **_gh_status_payload (),
        **_fu_status_payload (),
        })

    def _route_gateway(self):
        # Router quick link. {"ok": true, "url", "ip"} only when the gateway
        # in use is known, the viewer is on its LAN, and its web UI answers
        # a probe; anything else is {"ok": false} and the button stays
        # hidden. The LAN check runs first and costs nothing, so viewers
        # arriving by port-forward or VPN never trigger a probe. The
        # answer depends on who is asking, so it must never be cached.
        gw = read_default_gateway()
        url = None
        if gw and client_on_gateway_lan(self.client_address[0], gw):
            url = cached_router_probe(gw["ip"])
        payload = {"ok": True, "url": url, "ip": gw["ip"]} if url else {"ok": False}
        self._send_json(200, payload, extra_headers=[("Cache-Control", "no-store")])

    def _route_log (self ):
        since =0 
        if "?"in self .path :
            m =re .search (r"since=(\d+)",self .path )
            if m :
                since =int (m .group (1 ))
        with _log_lock :
            entries =[e for e in _log if e ["id"]>since ]
        self ._send_json (200 ,{"entries":entries })

    def _route_diskimg_drives(self):
        # Stage 1: read-only. Resolved fresh on every call (never cached)
        # since a drive can be plugged/unplugged/swapped between polls --
        # see _get_boot_disk()/_list_usb_drives() docstrings. Dependency
        # check is equally cheap (shutil.which() only) so it rides along
        # on the same 5s poll rather than needing its own endpoint.
        boot_disk = _get_boot_disk()
        self._send_json(200, {
            "drives": _list_usb_drives(),
            "boot_disk_detected": bool(boot_disk),
            "deps": _diskimg_check_dependencies(),
        })

    def _route_diskimg_job(self):
        job = _diskimg_job_snapshot()
        if job is None or job.get("dismissed"):
            self._send_json(200, {"job": None})
            return
        elapsed = (job.get("finished") or time.time()) - job["started"]
        rate = job["bytes_done"] / elapsed if elapsed > 0 else 0
        remaining = (job["bytes_total"] - job["bytes_done"]) if job.get("bytes_total") else None
        eta = (remaining / rate) if (rate > 0 and remaining is not None and remaining > 0) else None
        payload = dict(job)
        payload["elapsed_sec"] = elapsed
        payload["rate_bytes_per_sec"] = rate
        payload["eta_sec"] = eta
        self._send_json(200, {"job": payload})

    def _route_diskimg_backup_list(self):
        self._send_json(200, {"backups": _diskimg_list_backups()})

    def _route_diskimg_backup_download(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        name = query.get("name", [None])[0]
        drive = query.get("drive", [None])[0]
        if not name:
            self._error_json(400, "Missing 'name' parameter")
            return
        match = next(
            (b for b in _diskimg_list_backups() if b["name"] == name and (drive is None or b["drive"] == drive)),
            None,
        )
        if match is None:
            self._error_json(404, "Backup file not found on any currently attached drive")
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f"attachment; filename=\"{match['name']}\"")
            self.send_header("Content-Length", str(match["size"]))
            self.end_headers()
            with open(match["path"], "rb") as f:
                shutil.copyfileobj(f, self.wfile)
            log_event(f"Downloaded disk-image backup: {match['name']}", "info")
        except Exception as exc:
            self._error_json(500, f"Error downloading backup: {exc}")

    def _route_diskimg_schedule_get(self):
        cfg = _diskimg_schedule_load()
        next_run_at = None
        if cfg.get("enabled"):
            try:
                interval_sec = max(0.1, float(cfg.get("interval_hours") or 24)) * 3600
            except (TypeError, ValueError):
                interval_sec = 24 * 3600
            next_run_at = (cfg["last_run_at"] + interval_sec) if cfg.get("last_run_at") else time.time()
        cfg["next_run_at"] = next_run_at
        self._send_json(200, {"schedule": cfg})

    def handle_diskimg_schedule_set(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        enabled = bool(body.get("enabled"))
        if enabled and not body.get("confirm"):
            self._error_json(400, "Enabling scheduled backups requires confirm:true in the request body")
            return

        try:
            interval_hours = float(body.get("interval_hours", 24))
        except (TypeError, ValueError):
            self._error_json(400, "'interval_hours' must be a number")
            return
        if not (1 <= interval_hours <= 720):
            self._error_json(400, "'interval_hours' must be between 1 and 720 (30 days)")
            return

        try:
            retention = int(body.get("retention", 5))
        except (TypeError, ValueError):
            self._error_json(400, "'retention' must be a whole number")
            return
        if not (1 <= retention <= 50):
            self._error_json(400, "'retention' must be between 1 and 50")
            return

        dest_device = (body.get("dest_device") or "").strip()
        if enabled and not dest_device:
            self._error_json(400, "A destination drive is required to enable scheduled backups")
            return

        label = re.sub(r"[^A-Za-z0-9_-]+", "_", (body.get("label") or "").strip())[:40]

        # Deliberately does NOT require dest_device to be currently
        # attached -- this is a schedule for a drive that will be
        # plugged in later (e.g. overnight), not an immediate action.
        # _diskimg_schedule_tick() records why a run was skipped if the
        # drive isn't there when a run comes due.
        cfg = _diskimg_schedule_load()
        cfg["enabled"] = enabled
        cfg["interval_hours"] = interval_hours
        cfg["dest_device"] = dest_device
        cfg["retention"] = retention
        cfg["shrink"] = bool(body.get("shrink"))
        cfg["verify"] = bool(body.get("verify"))
        cfg["quiesce"] = bool(body.get("quiesce"))
        cfg["label"] = label
        _diskimg_schedule_save(cfg)
        log_event(
            f"Disk-image schedule updated: enabled={enabled} interval={interval_hours}h "
            f"dest={dest_device or '(none)'} retention={retention} quiesce={cfg['quiesce']}",
            "info",
        )
        self._send_json(200, {"message": "Schedule saved.", "level": "ok", "schedule": cfg})

    def handle_diskimg_preview(self):
        # v2.9.0: side-effect-free "what command would this run" preview
        # for the command-line fields on the Backup/Clone/Restore rows.
        # Always 200 -- an unresolved preview (no drive picked yet, boot
        # disk not detected, etc.) is a normal, frequent state while
        # someone is mid-selection, not an error worth a 4xx/5xx status.
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json(200, {"command": None, "error": "Malformed JSON body"})
            return
        kind = body.get("kind")
        command, note_or_error = _diskimg_build_command_preview(kind, body)
        if command is None:
            self._send_json(200, {"command": None, "error": note_or_error})
        else:
            self._send_json(200, {"command": command, "note": note_or_error})

    def handle_diskimg_backup_start(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        if not body.get("confirm"):
            self._error_json(400, "Disk-image backup requires confirm:true in the request body")
            return
        dest_device = body.get("dest_device")
        if not dest_device:
            self._error_json(400, "Missing 'dest_device'")
            return
        label = re.sub(r"[^A-Za-z0-9_-]+", "_", (body.get("label") or "").strip())[:40]
        shrink = bool(body.get("shrink"))
        verify = bool(body.get("verify"))
        encrypt = bool(body.get("encrypt"))
        passphrase = body.get("passphrase") or ""
        best_effort = bool(body.get("best_effort"))
        backend = body.get("backend") or "dd"
        if backend not in ("dd", "ddrescue"):
            self._error_json(400, "Unknown 'backend' -- must be 'dd' or 'ddrescue'")
            return
        throttle_rate_mb = body.get("throttle_rate_mb")
        if throttle_rate_mb is not None:
            try:
                throttle_rate_mb = float(throttle_rate_mb)
            except (TypeError, ValueError):
                throttle_rate_mb = None
            if not throttle_rate_mb or throttle_rate_mb <= 0:
                self._error_json(400, "'throttle_rate_mb' must be a positive number")
                return
        freeze = bool(body.get("freeze"))
        verify_algo = body.get("verify_algo") or "sha256"
        if verify_algo not in _VERIFY_HASHERS:
            self._error_json(400, "Unknown 'verify_algo' -- must be 'sha256' or 'blake2b'")
            return
        if encrypt and not passphrase:
            self._error_json(400, "A passphrase is required to encrypt this backup")
            return
        if encrypt and shrink:
            self._error_json(400, "Shrink to fit can't be combined with encryption -- shrinking needs to inspect the unencrypted disk image, which an encrypted backup no longer is")
            return
        if encrypt and verify:
            self._error_json(400, "Verify after copy isn't supported for encrypted backups -- turn off one or the other")
            return
        if encrypt and backend == "ddrescue":
            self._error_json(400, "The resilient (ddrescue) backend can't be combined with encryption -- ddrescue writes with seeks and retries that a streaming openssl pipe can't follow. Turn off one or the other.")
            return
        if encrypt and throttle_rate_mb:
            self._error_json(400, "Bandwidth throttle isn't supported for encrypted backups yet -- turn off one or the other")
            return
        if backend == "ddrescue" and throttle_rate_mb:
            self._error_json(400, "Bandwidth throttle isn't supported with the resilient (ddrescue) backend -- ddrescue doesn't stream sequentially the way the throttle pipeline needs. Turn off one or the other.")
            return

        boot_disk = _get_boot_disk()
        if not boot_disk:
            self._error_json(409, "Could not determine this Pi's boot disk -- refusing to start a backup until this resolves.")
            return
        src_path = f"/dev/{boot_disk}"

        match = next(
            (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
            None,
        )
        if match is None:
            self._error_json(400, f"'{dest_device}' is not a currently attached USB drive")
            return
        if match["is_boot_disk"]:
            self._error_json(400, "Refusing to use the boot disk as a backup destination")
            return
        if match["read_only"]:
            self._error_json(400, f"{match['path']} is write-protected")
            return

        src_size = _disk_size_bytes(boot_disk)
        if not src_size:
            self._error_json(500, "Could not determine the boot disk's size")
            return
        if match["size"] < src_size:
            self._error_json(
                400,
                f"{match['path']} ({fmt_bytes(match['size'])}) is smaller than the boot disk "
                f"({fmt_bytes(src_size)}) -- a raw image needs a destination at least as large",
            )
            return

        mountpoint, _we_mounted = _diskimg_ensure_mounted(match["name"])
        if mountpoint is None:
            self._error_json(500, f"Could not find or mount a writable filesystem on {match['path']}")
            return
        try:
            free = shutil.disk_usage(mountpoint).free
        except OSError as exc:
            self._error_json(500, f"Could not check free space on {mountpoint}: {exc}")
            return
        if free < src_size:
            self._error_json(
                400,
                f"Not enough free space on {match['path']} ({fmt_bytes(free)} free, need {fmt_bytes(src_size)})",
            )
            return

        backup_dir = os.path.join(mountpoint, _DISKIMG_BACKUP_DIRNAME)
        try:
            os.makedirs(backup_dir, exist_ok=True)
        except OSError as exc:
            self._error_json(500, f"Could not create {backup_dir}: {exc}")
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        hostname = socket.gethostname()
        ext = _DISKIMG_ENCRYPTED_SUFFIX if encrypt else ".img"
        fname = f"{hostname}_{stamp}" + (f"_{label}" if label else "") + ext
        dest_path = os.path.join(backup_dir, fname)

        quiesce = bool(body.get("quiesce"))
        # The pre-job sync stays where it is; _quiesce_services() runs
        # its own sync AFTER the services are down, which is the one
        # that actually matters when quiescing.
        subprocess.run(["sync"], capture_output=True, timeout=30)
        ok, result = _diskimg_start_job(
            "backup", src_path, dest_path, src_path, dest_path, src_size,
            shrink_requested=shrink, verify_requested=verify,
            encrypt_passphrase=passphrase if encrypt else None,
            quiesce_requested=quiesce,
            best_effort_requested=best_effort, backend=backend,
            throttle_rate_mb=throttle_rate_mb, freeze_requested=freeze,
            verify_algo=verify_algo,
        )
        passphrase = None  # done with it in this scope either way
        if not ok:
            self._error_json(409, result)
            return
        self._send_json(200, {
            "message": (
                f"Backup started: {src_path} -> {dest_path}. This can take a long time -- watch the progress panel."
                + (" Node services were stopped -- the node is off the air until this finishes." if quiesce else "")
                + (" The filesystem will be frozen for the copy." if (quiesce and freeze) else "")
                + (" Output will be AES-256 encrypted." if encrypt else "")
                + (" It will be verified against the source afterward." if verify else "")
                + (" It will also be shrunk to its minimum size afterward." if shrink else "")
                + (" Using the resilient (ddrescue) backend." if backend == "ddrescue" else "")
                + (" Continuing past read errors (best effort)." if (best_effort and backend != "ddrescue") else "")
                + (f" Throttled to {throttle_rate_mb:g} MB/s." if throttle_rate_mb else "")
            ),
            "level": "ok",
            "job_id": result,
        })

    def handle_diskimg_backup_delete(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        name = body.get("name")
        drive = body.get("drive")
        if not name:
            self._error_json(400, "Missing 'name'")
            return
        match = next(
            (b for b in _diskimg_list_backups() if b["name"] == name and (drive is None or b["drive"] == drive)),
            None,
        )
        if match is None:
            self._error_json(404, "Backup file not found on any currently attached drive")
            return
        try:
            os.remove(match["path"])
        except OSError as exc:
            self._error_json(500, f"Could not delete {match['name']}: {exc}")
            return
        log_event(f"Deleted disk-image backup: {match['name']}", "warn")
        self._send_json(200, {"message": f"Deleted {match['name']}.", "level": "ok"})

    def handle_diskimg_job_cancel(self):
        ok, message = _diskimg_cancel_job()
        if not ok:
            self._error_json(409, message)
            return
        self._send_json(200, {"message": message, "level": "warn"})

    def handle_diskimg_job_reset(self):
        # v2.30.0: Reset button. Body {"kind": "format"|"backup"|"clone"|"restore"}.
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        kind = body.get("kind")
        if kind not in ("format", "backup", "clone", "restore"):
            self._error_json(400, "Missing or unknown 'kind'")
            return
        ok, message = _diskimg_reset_job(kind)
        if not ok:
            self._error_json(409, message)
            return
        self._send_json(200, {"message": message, "level": "ok"})

    def handle_diskimg_unmount(self):
        # v2.13.0 Stage 4: unmount every mountpoint currently reported
        # for a drive -- lets someone clear the "Unmounted" prerequisite
        # for Full Format (or Clone/Restore, which already silently
        # require it) without leaving the browser. Never touches the
        # boot disk under any circumstance.
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        if not body.get("confirm"):
            self._error_json(400, "Unmount requires confirm:true in the request body")
            return
        dest_device = body.get("dest_device")
        if not dest_device:
            self._error_json(400, "Missing 'dest_device'")
            return
        match = next(
            (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
            None,
        )
        if match is None:
            self._error_json(400, f"'{dest_device}' is not a currently attached USB drive")
            return
        if match["is_boot_disk"]:
            self._error_json(400, "Refusing to unmount the boot disk -- that's this Pi's own root filesystem")
            return
        mountpoints = match.get("mounted_at") or []
        if not mountpoints:
            self._send_json(200, {"message": f"{match['path']} is already unmounted.", "level": "ok"})
            return
        errors = []
        for mp in mountpoints:
            try:
                result = subprocess.run(["umount", mp], capture_output=True, text=True, timeout=20)
                if result.returncode != 0:
                    errors.append(f"{mp}: {(result.stderr or result.stdout).strip()}")
            except (subprocess.TimeoutExpired, OSError) as exc:
                errors.append(f"{mp}: {exc}")
        if errors:
            log_event(f"Unmount {match['path']}: {'; '.join(errors)}", "warn")
            self._error_json(500, "Could not unmount: " + "; ".join(errors))
            return
        log_event(f"Unmounted {match['path']} ({', '.join(mountpoints)})", "info")
        self._send_json(200, {"message": f"Unmounted {match['path']}.", "level": "ok"})

    def handle_diskimg_format_start(self):
        # v2.10.0 Stage 2: full wipe + fresh GPT + mkfs of the
        # destination drive. Same attached/not-boot-disk/not-write-
        # protected/unmounted gates as Clone -- Format is at least as
        # destructive (Clone at least leaves a byte-for-byte copy of
        # something; Format leaves an empty, freshly-labeled disk).
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        if not body.get("confirm"):
            self._error_json(400, "Disk-image format requires confirm:true in the request body")
            return
        dest_device = body.get("dest_device")
        if not dest_device:
            self._error_json(400, "Missing 'dest_device'")
            return
        fs_type = body.get("fs_type")
        if fs_type not in _DISKIMG_FORMAT_FS_TOOLS:
            self._error_json(400, f"Missing or unknown 'fs_type' -- must be one of {sorted(_DISKIMG_FORMAT_FS_TOOLS)}")
            return

        match = next(
            (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
            None,
        )
        if match is None:
            self._error_json(400, f"'{dest_device}' is not a currently attached USB drive")
            return
        if match["is_boot_disk"]:
            self._error_json(400, "Refusing to use the boot disk as a format target")
            return
        if match["read_only"]:
            self._error_json(400, f"{match['path']} is write-protected")
            return
        if match["mounted_at"]:
            self._error_json(
                400,
                f"{match['path']} is currently mounted ({', '.join(match['mounted_at'])}) "
                "-- unmount it before formatting it",
            )
            return

        quick = bool(body.get("quick"))
        subprocess.run(["sync"], capture_output=True, timeout=30)
        ok, result = _diskimg_start_job(
            "format", "/dev/zero", match["path"], "/dev/zero", match["path"],
            _diskimg_format_wipe_bytes(match["size"], quick),
            fs_type=fs_type, quick_requested=quick,
        )
        if not ok:
            self._error_json(409, result)
            return
        self._send_json(200, {
            "message": (
                (
                    f"Quick format started: the start of {match['path']} will be cleared, then it is partitioned (GPT) and formatted as {fs_type}. "
                    "Not a secure erase -- watch the progress panel."
                ) if quick else (
                    f"Format started: {match['path']} will be wiped, then partitioned (GPT) and formatted as {fs_type}. "
                    "This can take a long time -- watch the progress panel."
                )
            ),
            "level": "ok",
            "job_id": result,
        })

    def handle_diskimg_clone_start(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        if not body.get("confirm"):
            self._error_json(400, "Disk-image clone requires confirm:true in the request body")
            return
        dest_device = body.get("dest_device")
        if not dest_device:
            self._error_json(400, "Missing 'dest_device'")
            return
        verify = bool(body.get("verify"))
        best_effort = bool(body.get("best_effort"))
        direct_io = bool(body.get("direct_io"))
        backend = body.get("backend") or "dd"
        if backend not in ("dd", "ddrescue"):
            self._error_json(400, "Unknown 'backend' -- must be 'dd' or 'ddrescue'")
            return
        throttle_rate_mb = body.get("throttle_rate_mb")
        if throttle_rate_mb is not None:
            try:
                throttle_rate_mb = float(throttle_rate_mb)
            except (TypeError, ValueError):
                throttle_rate_mb = None
            if not throttle_rate_mb or throttle_rate_mb <= 0:
                self._error_json(400, "'throttle_rate_mb' must be a positive number")
                return
        freeze = bool(body.get("freeze"))
        verify_algo = body.get("verify_algo") or "sha256"
        if verify_algo not in _VERIFY_HASHERS:
            self._error_json(400, "Unknown 'verify_algo' -- must be 'sha256' or 'blake2b'")
            return
        if backend == "ddrescue" and throttle_rate_mb:
            self._error_json(400, "Bandwidth throttle isn't supported with the resilient (ddrescue) backend -- ddrescue doesn't stream sequentially the way the throttle pipeline needs. Turn off one or the other.")
            return

        boot_disk = _get_boot_disk()
        if not boot_disk:
            self._error_json(409, "Could not determine this Pi's boot disk -- refusing to start a clone until this resolves.")
            return
        src_path = f"/dev/{boot_disk}"

        match = next(
            (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
            None,
        )
        if match is None:
            self._error_json(400, f"'{dest_device}' is not a currently attached USB drive")
            return
        if match["is_boot_disk"]:
            self._error_json(400, "Refusing to use the boot disk as a clone destination")
            return
        if match["read_only"]:
            self._error_json(400, f"{match['path']} is write-protected")
            return
        if match["mounted_at"]:
            self._error_json(
                400,
                f"{match['path']} is currently mounted ({', '.join(match['mounted_at'])}) "
                "-- unmount it before cloning onto it",
            )
            return

        src_size = _disk_size_bytes(boot_disk)
        if not src_size:
            self._error_json(500, "Could not determine the boot disk's size")
            return
        if match["size"] < src_size:
            self._error_json(
                400,
                f"{match['path']} ({fmt_bytes(match['size'])}) is smaller than the boot disk "
                f"({fmt_bytes(src_size)}) -- a raw clone needs a destination at least as large",
            )
            return

        quiesce = bool(body.get("quiesce"))
        subprocess.run(["sync"], capture_output=True, timeout=30)
        ok, result = _diskimg_start_job(
            "clone", src_path, match["path"], src_path, match["path"], src_size,
            verify_requested=verify, quiesce_requested=quiesce,
            best_effort_requested=best_effort, direct_io_requested=direct_io,
            backend=backend, throttle_rate_mb=throttle_rate_mb,
            freeze_requested=freeze, verify_algo=verify_algo,
        )
        if not ok:
            self._error_json(409, result)
            return
        self._send_json(200, {
            "message": (
                f"Clone started: {src_path} -> {match['path']}. This can take a long time -- watch the progress panel."
                + (" Node services were stopped -- the node is off the air until this finishes." if quiesce else "")
                + (" The filesystem will be frozen for the copy." if (quiesce and freeze) else "")
                + (" It will be verified against the source afterward." if verify else "")
                + (" Using the resilient (ddrescue) backend." if backend == "ddrescue" else "")
                + (" Continuing past read errors (best effort)." if (best_effort and backend != "ddrescue") else "")
                + (" Using direct I/O." if (direct_io and backend != "ddrescue") else "")
                + (f" Throttled to {throttle_rate_mb:g} MB/s." if throttle_rate_mb else "")
            ),
            "level": "ok",
            "job_id": result,
        })

    def handle_diskimg_restore_start(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        if not body.get("confirm"):
            self._error_json(400, "Disk-image restore requires confirm:true in the request body")
            return
        dest_device = body.get("dest_device")
        name = body.get("name")
        drive = body.get("drive")
        if not dest_device:
            self._error_json(400, "Missing 'dest_device'")
            return
        if not name:
            self._error_json(400, "Missing 'name' (the backup image to restore)")
            return
        verify = bool(body.get("verify"))
        passphrase = body.get("passphrase") or ""
        verify_algo = body.get("verify_algo") or "sha256"
        if verify_algo not in _VERIFY_HASHERS:
            self._error_json(400, "Unknown 'verify_algo' -- must be 'sha256' or 'blake2b'")
            return
        throttle_rate_mb = body.get("throttle_rate_mb")
        if throttle_rate_mb is not None:
            try:
                throttle_rate_mb = float(throttle_rate_mb)
            except (TypeError, ValueError):
                throttle_rate_mb = None
            if not throttle_rate_mb or throttle_rate_mb <= 0:
                self._error_json(400, "'throttle_rate_mb' must be a positive number")
                return

        image = next(
            (b for b in _diskimg_list_backups() if b["name"] == name and (drive is None or b["drive"] == drive)),
            None,
        )
        if image is None:
            self._error_json(404, "Backup file not found on any currently attached drive")
            return
        if image["encrypted"] and not passphrase:
            self._error_json(400, f"{image['name']} is encrypted -- a passphrase is required to restore it")
            return
        if image["encrypted"] and verify:
            self._error_json(400, "Verify after copy isn't supported when restoring an encrypted backup -- turn off one or the other")
            return
        if image["encrypted"] and throttle_rate_mb:
            self._error_json(400, "Bandwidth throttle isn't supported when restoring an encrypted backup yet -- turn off one or the other")
            return

        # Belt-and-suspenders: even though a mounted destination is
        # already rejected below (and the drive holding this image is
        # necessarily mounted, or _diskimg_list_backups() couldn't have
        # found it there), never allow restoring an image onto the very
        # disk it's currently stored on.
        boot_disk = _get_boot_disk()
        if not boot_disk:
            self._error_json(409, "Could not determine this Pi's boot disk -- refusing to start a restore until this resolves.")
            return

        match = next(
            (d for d in _list_usb_drives() if d["path"] == dest_device or d["name"] == dest_device),
            None,
        )
        if match is None:
            self._error_json(400, f"'{dest_device}' is not a currently attached USB drive")
            return
        if match["is_boot_disk"]:
            self._error_json(400, "Refusing to write onto the boot disk -- restore always targets a different, spare drive")
            return
        if match["path"] == image["drive"]:
            self._error_json(400, f"{image['name']} is stored on {match['path']} itself -- pick a different destination drive")
            return
        if match["read_only"]:
            self._error_json(400, f"{match['path']} is write-protected")
            return
        if match["mounted_at"]:
            self._error_json(
                400,
                f"{match['path']} is currently mounted ({', '.join(match['mounted_at'])}) "
                "-- unmount it before restoring onto it",
            )
            return
        if match["size"] < image["size"]:
            self._error_json(
                400,
                f"{match['path']} ({fmt_bytes(match['size'])}) is smaller than {image['name']} "
                f"({fmt_bytes(image['size'])}) -- the destination needs to be at least as large",
            )
            return

        subprocess.run(["sync"], capture_output=True, timeout=30)
        ok, result = _diskimg_start_job(
            "restore", image["path"], match["path"], image["path"], match["path"], image["size"],
            verify_requested=verify,
            decrypt_passphrase=passphrase if image["encrypted"] else None,
            throttle_rate_mb=throttle_rate_mb, verify_algo=verify_algo,
        )
        passphrase = None  # done with it in this scope either way
        if not ok:
            self._error_json(409, result)
            return
        self._send_json(200, {
            "message": (
                f"Restore started: {image['name']} -> {match['path']}. This can take a long time -- watch the progress panel."
                + (" It will be decrypted on the way out." if image["encrypted"] else "")
                + (" It will be verified against the source afterward." if verify else "")
                + (f" Throttled to {throttle_rate_mb:g} MB/s." if throttle_rate_mb else "")
            ),
            "level": "ok",
            "job_id": result,
        })

    def _route_file (self ):
        query =urllib .parse .parse_qs (urllib .parse .urlparse (self .path ).query )
        file_names =query .get ("file",[])
        if not file_names :
            self ._error_json (400 ,"Missing 'file' parameter")
            return 
        filename =file_names [0 ]
        category =query .get ("category",[None ])[0 ]
        target =self ._find_library_file (filename ,category )
        if target is None :
            self ._error_json (404 ,f"File '{filename }' not found in library")
            return 
        try :
            with open (target ,"r",encoding ="utf-8")as f :
                content =f .read ()
            self .send_response (200 )
            self .send_header ("Content-Type","text/plain; charset=utf-8")
            self .send_header ("Content-Length",str (len (content .encode ("utf-8"))))
            self .end_headers ()
            self .wfile .write (content .encode ("utf-8"))
        except Exception as exc :
            self ._error_json (500 ,f"Error reading file: {exc }")

    def _check_csrf (self ):
        return self .headers .get ("X-Requested-With")=="XMLHttpRequest"

    def do_GET (self ):
        parsed_path =self .path .split ("?",1 )[0 ]
        if parsed_path not in ("/","/index.html"):
            if not _check_session(self._session_token()):
                self._require_auth()
                return
        handler_fn =_GET_ROUTES .get (parsed_path )
        if handler_fn is None :
            self ._error_json (404 ,"Not found")
            return
        handler_fn (self )


    def do_POST (self ):
        if self.path == "/api/login":
            self._handle_login()
            return
        if self.path == "/api/logout":
            if not _check_session(self._session_token()):
                self._require_auth()
                return
            _revoke_session(self._session_token())
            self._send_json(200, {"ok": True}, extra_headers=[("Set-Cookie", _clear_session_cookie_header())])
            return
        if not _check_session(self._session_token()):
            self._require_auth()
            return
        if not self ._check_csrf ():
            self ._error_json (403 ,"Missing or invalid X-Requested-With header")
            return
        # v2.37.0: uploads, the editor and disk-image jobs wait for Full
        # Update; /api/action applies its own narrower rule.
        if full_update_running() and self.path != "/api/action":
            self._send_json(409, {"error": "Full Update is running",
                                  "message": "Full Update is running -- wait for it to finish.", "level": "warn"})
            return
        handler_fn =_POST_ROUTES .get (self .path )
        if handler_fn is None :
            self ._error_json (404 ,"Not found")
            return
        handler_fn (self )

    def _handle_login(self):
        client_ip = self.client_address[0]
        remaining = _auth_lockout_remaining(client_ip)
        if remaining > 0:
            retry_after = int(remaining) + 1
            self._send_json(429, {"ok": False, "error": f"Too many failed login attempts. Try again in {retry_after}s."},
                             extra_headers=[("Retry-After", str(retry_after))])
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        password = body.get("password") or ""
        if _verify_root_password(password):
            _record_auth_success(client_ip)
            token = _issue_session()
            self._send_json(200, {"ok": True},
                             extra_headers=[("Set-Cookie", _session_cookie_header(token, _SESSION_TTL_SEC))])
        else:
            _record_auth_failure(client_ip)
            self._send_json(401, {"ok": False, "error": "Invalid password"})


    def handle_download (self ):
        query =urllib .parse .parse_qs (urllib .parse .urlparse (self .path ).query )
        file_names =query .get ("file",[])
        if not file_names :
            self ._error_json (400 ,"Missing 'file' parameter")
            return 
        filename =file_names [0 ]
        category =query .get ("category",[None ])[0 ]
        target =self ._find_library_file (filename ,category )
        if target is None :
            self ._error_json (404 ,f"File '{filename }' not found in library")
            return 
        try :
            self .send_response (200 )
            ext =os .path .splitext (filename )[1 ].lower ()
            ctype ="application/octet-stream"
            if ext ==".py":
                ctype ="text/x-python"
            elif ext ==".sh":
                ctype ="text/x-sh"
            elif ext ==".conf":
                ctype ="text/plain"
            self .send_header ("Content-Type",ctype )
            self .send_header ("Content-Disposition",f"attachment; filename=\"{filename }\"")
            self .end_headers ()
            with open (target ,"rb")as f :
                shutil .copyfileobj (f ,self .wfile )
            log_event (f"Downloaded file: {filename }","info")
        except Exception as exc :
            self ._error_json (500 ,f"Error downloading file: {exc }")


    def handle_backup (self ):
        try :

            tmp_file =tempfile .NamedTemporaryFile (prefix ="instmon_backup_",suffix =".zip",delete =False )
            tmp_path =tmp_file .name 
            tmp_file .close ()


            with zipfile .ZipFile (tmp_path ,'w',zipfile .ZIP_DEFLATED )as zf :
                for root ,dirs ,files in os .walk (LIBRARY_DIR ):
                    for file in files :
                        full_path =os .path .join (root ,file )
                        rel_path =os .path .relpath (full_path ,LIBRARY_DIR )
                        zf .write (full_path ,arcname =rel_path )

            stamp =datetime .now ().strftime ("%Y%m%d_%H%M%S")
            self .send_response (200 )
            self .send_header ("Content-Type","application/zip")
            self .send_header ("Content-Disposition",f"attachment; filename=\"instmon_backup_{stamp }.zip\"")
            self .send_header ("Content-Length",str (os .path .getsize (tmp_path )))
            self .end_headers ()

            with open (tmp_path ,"rb")as f :
                shutil .copyfileobj (f ,self .wfile )

            os .unlink (tmp_path )
            log_event (f"Full backup downloaded ({stamp })","ok")
        except Exception as exc :
            self ._error_json (500 ,f"Error creating backup: {exc }")


    def handle_file_write (self ):
        length =int (self .headers .get ("Content-Length",0 ))
        try :
            body =json .loads (self .rfile .read (length )or b"{}")
        except json .JSONDecodeError :
            self ._error_json (400 ,"Malformed JSON body")
            return 

        filename =body .get ("file")
        content =body .get ("content")
        category =body .get ("category")
        if not filename or content is None :
            self ._error_json (400 ,"Missing 'file' or 'content'")
            return 

        target =self ._find_library_file (filename ,category )
        if target is None :
            self ._error_json (404 ,f"File '{filename }' not found in library")
            return 

        ext =os .path .splitext (filename )[1 ].lower ()
        if ext in (".py",".sh"):
            tmp_check =None 
            try :
                with tempfile .NamedTemporaryFile (mode ="w",suffix =ext ,delete =False ,encoding ="utf-8")as tf :
                    tf .write (content )
                    tmp_check =tf .name 
                syntax_err =check_script_syntax (tmp_check )
            finally :
                if tmp_check and os .path .exists (tmp_check ):
                    try :
                        os .remove (tmp_check )
                    except OSError :
                        pass 
            if syntax_err :
                log_event (f"Rejected edit to {filename }: syntax error -- {syntax_err }","warn")
                self ._error_json (400 ,f"Syntax check failed, not saved: {syntax_err }")
                return 

        try :
            wrote ,reason =compare_before_write (target ,content .encode ("utf-8"))
            if wrote :
                log_event (f"Edited file: {filename } in library","ok")
            self ._send_json (200 ,{"wrote":wrote ,"reason":reason })
        except Exception as exc :
            self ._error_json (500 ,f"Error writing file: {exc }")


    def handle_upload (self ):
        content_type =self .headers .get ("Content-Type","")
        m =re .search (r'boundary=([^;]+)',content_type )
        if not m or "multipart/form-data"not in content_type :
            self ._error_json (400 ,"Expected multipart/form-data upload")
            return 
        boundary =m .group (1 ).strip ('"')
        length =int (self .headers .get ("Content-Length",0 ))
        if length <=0 or length >MAX_UPLOAD_BYTES :
            self ._error_json (400 ,f"Upload missing or too large (limit {MAX_UPLOAD_BYTES //(1024 *1024 )}MB -- set INSTMON_MAX_UPLOAD_MB to change)")
            return 
        raw =self .rfile .read (length )
        fields =parse_multipart (raw ,boundary )

        category =fields .get ("category",(None ,b""))[1 ].decode (errors ="replace")
        filename ,filedata =fields .get ("file",(None ,None ))
        force =fields .get ("force",(None ,b""))[1 ].decode (errors ="replace")=="1"
        if category not in LIB_SUBDIRS :
            self ._error_json (400 ,f"Unknown category '{category }'")
            return 
        if not filename or filedata is None :
            self ._error_json (400 ,"No file provided")
            return 
        filename =os .path .basename (filename )
        ext =os .path .splitext (filename )[1 ].lower ()
        if ext not in ALLOWED_EXT [category ]:
            self ._error_json (400 ,f"'{ext }' not allowed for category '{category }' (expected {ALLOWED_EXT [category ]})")
            return 

        expected_patterns =dict (HOME_SCAN_PATTERN_MAP ).get (category ,[])
        name_matches =any (fnmatch .fnmatch (filename .lower (),g .lower ())for g in expected_patterns )
        if expected_patterns and not name_matches and not force :
            self ._send_json (400 ,{
            "error":f"'{filename }' doesn't look like a {category } file -- expected a name matching {' / '.join (expected_patterns )}.",
            "mismatch":True ,
            "expected":expected_patterns ,
            })
            return 
        if expected_patterns and not name_matches and force :
            log_event (f"Uploaded {filename } to {category } library despite naming mismatch (forced)","warn")

        ensure_dirs ()
        dest =safe_join (LIB_SUBDIRS [category ],filename )
        if dest is None :
            self ._error_json (400 ,"Invalid filename")
            return 
        wrote ,reason =compare_before_write (dest ,filedata )
        log_event (f"Uploaded {filename } to {category } library ({reason })","ok")
        message =f"Staged {filename } in the {category } library."if wrote else f"{filename } already staged (unchanged)."
        self ._send_json (200 ,{"name":filename ,"wrote":wrote ,"reason":reason ,"message":message ,"level":"ok"if wrote else "info"})


    def handle_action (self ):
        length =int (self .headers .get ("Content-Length",0 ))
        try :
            body =json .loads (self .rfile .read (length )or b"{}")
        except json .JSONDecodeError :
            self ._error_json (400 ,"Malformed JSON body")
            return 

        action =body .get ("action")
        if full_update_running() and action not in _ACTIONS_DURING_FULL_UPDATE:
            self._send_json(409, {"error": "Full Update is running",
                                  "message": "Full Update is running -- wait for it to finish.", "level": "warn"})
            return
        handler_fn =_ACTION_HANDLERS .get (action )
        if handler_fn is None :
            self ._error_json (400 ,f"Unknown action '{action }'")
            return 
        handler_fn (self ,body )


    def _action_install (self ,body ):

        if not body .get ("confirm"):
            self ._error_json (400 ,"This action runs a script's own --install and requires confirm:true in the request body")
            return 

        category =body .get ("category")
        name =body .get ("name")
        comp =next ((c for c in COMPONENTS if c ["category"]==category ),None )
        if comp is None :
            self ._error_json (400 ,f"No installable component for category '{category }'")
            return 
        src =safe_join (LIB_SUBDIRS [category ],name or "")
        if src is None or not os .path .isfile (src ):
            self ._error_json (404 ,f"Library file not found: {name }")
            return 

        with _running_installs_lock :
            if comp ["service"]in _running_installs :
                self ._send_json (409 ,{
                "error":f"An install for {comp ['name']} is already in progress",
                "message":f"Another install for {comp ['name']} is already in progress -- wait for it to finish.",
                "level":"warn",
                })
                return 
            _running_installs .add (comp ["service"])


        if not script_has_self_install (src ):
            with _running_installs_lock :
                _running_installs .discard (comp ["service"])
            msg =f"{name } doesn't support self-install (--install / install_service() not found in the file) -- Install stopped. Nothing was run."
            log_event (msg ,"err")
            self ._send_json (400 ,{"error":msg ,"message":msg ,"level":"err"})
            return 

        syntax_err =check_script_syntax (src )
        if syntax_err :
            with _running_installs_lock :
                _running_installs .discard (comp ["service"])
            log_event (f"Install blocked: syntax error in {name }: {syntax_err }","err")
            self ._send_json (400 ,{
            "error":f"Syntax error in {name } -- install blocked",
            "detail":syntax_err ,
            "message":f"Install blocked: {name } has a syntax error. Nothing was run.",
            "level":"err",
            })
            return 

        thread =threading .Thread (
        target =run_self_install_bg ,args =(src ,name ,comp ),daemon =True ,
        )
        thread .start ()
        self ._send_json (200 ,{
        "started":name ,
        "message":f"Installing {name } -- {comp ['name']} will restart itself once its own --install finishes. Watch the log below for output.",
        "level":"info",
        })


    def _action_uninstall (self ,body ):

        category =body .get ("category")
        comp =next ((c for c in COMPONENTS if c ["category"]==category ),None )
        if comp is None :
            self ._error_json (400 ,f"No installable component for category '{category }'")
            return 

        target =resolve_installed_target (comp )
        if comp ["category"]=="instmon":
            self ._error_json (400 ,"instmon cannot uninstall itself.")
            return 
        if not os .path .isfile (target ):
            self ._error_json (400 ,f"{comp ['name']} is not currently installed -- nothing to uninstall.")
            return 

        if not script_has_self_uninstall (target ):
            msg =f"{comp ['name']}'s installed file doesn't support self-uninstall (--uninstall / uninstall_service() not found) -- Uninstall stopped. Nothing was run."
            log_event (msg ,"err")
            self ._send_json (400 ,{"error":msg ,"message":msg ,"level":"err"})
            return 


        with _running_installs_lock :
            if comp ["service"]in _running_installs :
                self ._send_json (409 ,{
                "error":f"An install/uninstall for {comp ['name']} is already in progress",
                "message":f"Another install/uninstall for {comp ['name']} is already in progress -- wait for it to finish.",
                "level":"warn",
                })
                return 
            _running_installs .add (comp ["service"])


        staged ,staged_name ,stage_note ,stage_err =stage_installed_copy_if_missing (comp )
        if stage_err :
            with _running_installs_lock :
                _running_installs .discard (comp ["service"])
            log_event (f"Uninstall blocked for {comp ['name']}: {stage_err }","err")
            self ._send_json (500 ,{
            "error":stage_err ,
            "message":f"Uninstall blocked: {stage_err }. Nothing was uninstalled.",
            "level":"err",
            })
            return 

        thread =threading .Thread (
        target =run_self_uninstall_bg ,args =(comp ,),daemon =True ,
        )
        thread .start ()
        self ._send_json (200 ,{
        "started":comp ["service"],
        "message":f"Uninstalling {comp ['name']} ({stage_note }) -- watch the log below for output.",
        "level":"info",
        })


    def _action_start (self ,body ):

        service =body .get ("service","")
        comp =next ((c for c in COMPONENTS if c ["service"]==service ),None )
        if comp is None :
            self ._error_json (400 ,f"Unknown service '{service }'")
            return 
        if comp ["category"]=="instmon":
            self ._error_json (400 ,"instmon cannot start/restart itself from its own panel.")
            return 
        try :
            subprocess .run (["systemctl","restart",service ],capture_output =True ,text =True ,timeout =10 )
        except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
            self ._error_json (500 ,f"Could not start {comp ['name']}: {exc }")
            return 
        time .sleep (0.5 )
        state =systemctl_is_active (service )
        log_event (f"Started {comp ['name']} (now {state })","info"if state =="active"else "warn")
        self ._send_json (200 ,{
        "service":service ,
        "state":state ,
        "message":f"{comp ['name']} started (now {state }).",
        "level":"info",
        })


    def _action_stop (self ,body ):

        service =body .get ("service","")
        comp =next ((c for c in COMPONENTS if c ["service"]==service ),None )
        if comp is None :
            self ._error_json (400 ,f"Unknown service '{service }'")
            return 
        if comp ["category"]=="instmon":
            self ._error_json (400 ,"instmon cannot stop itself.")
            return 
        try :
            subprocess .run (["systemctl","stop",service ],capture_output =True ,text =True ,timeout =10 )
        except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
            self ._error_json (500 ,f"Could not stop {comp ['name']}: {exc }")
            return 
        time .sleep (0.5 )
        state =systemctl_is_active (service )
        log_event (f"Stopped {comp ['name']} (now {state })","warn"if state =="active"else "info")
        self ._send_json (200 ,{
        "service":service ,
        "state":state ,
        "message":f"{comp ['name']} stopped (now {state }).",
        "level":"info",
        })


    def _action_install_config (self ,body ):
        name =body .get ("name")
        src =safe_join (LIB_SUBDIRS ["config"],name or "")
        if src is None or not os .path .isfile (src ):
            self ._error_json (404 ,f"Library config not found: {name }")
            return 
        try :
            with open (src ,"rb")as f :
                data =f .read ()
        except OSError as exc :
            self ._error_json (500 ,f"Could not read {name }: {exc }")
            return 

        dest =os .path .join (CONFIG_DIR ,CONFIG_NAME )
        with _running_installs_lock :
            if dest in _running_installs :
                self ._send_json (409 ,{
                "error":f"An install to {dest } is already in progress",
                "message":"Another config install is already in progress -- wait for it to finish.",
                "level":"warn",
                })
                return 
            _running_installs .add (dest )

        try :


            _dash_comp =next ((c for c in COMPONENTS if c ["category"]=="dashboard"),None )
            comp =None 
            if _dash_comp and os .path .isfile (resolve_installed_target (_dash_comp )):
                comp =_dash_comp 
            if comp is None :
                try :
                    wrote ,reason =compare_before_write (dest ,data )
                except OSError as exc :
                    self ._error_json (500 ,f"Install failed writing {dest }: {exc }")
                    return 
                log_event (f"Install config {name } -> {dest } ({reason })","ok"if wrote else "info")
                message =(f"Config {name } installed as {CONFIG_NAME }. The Dashboard is not currently installed -- apply it manually."
                if wrote else f"{name } is already the active config (unchanged).")
                self ._send_json (200 ,{"wrote":wrote ,"reason":reason ,"message":message ,"level":"warn"if wrote else "info"})
                return 

            result =install_file_with_verification (data ,dest ,comp )
            if result ["reason"]=="error":
                self ._error_json (500 ,result ["message"])
                return 

            log_event (f"Install config {name } -> {dest } ({result ['reason']})","ok"if result ["wrote"]else "info")
            if result ["wrote"]:
                result ["message"]=f"Config {name } installed as {CONFIG_NAME }. {result ['message']}"
            else :
                result ["message"]=f"{name } is already the active config (unchanged) -- no restart needed."
            self ._send_json (200 ,result )
        finally :
            with _running_installs_lock :
                _running_installs .discard (dest )


    def _action_delete (self ,body ):
        category =body .get ("category")
        name =body .get ("name")
        if category not in LIB_SUBDIRS :
            self ._error_json (400 ,f"Unknown category '{category }'")
            return 
        target =safe_join (LIB_SUBDIRS [category ],name or "")
        if target is None or not os .path .isfile (target ):
            self ._error_json (404 ,f"Library file not found: {name }")
            return 
        os .remove (target )
        log_event (f"Deleted {name } from {category } library","warn")
        self ._send_json (200 ,{"deleted":name ,"message":f"Deleted {name } from the library.","level":"warn"})


    def _action_run_script (self ,body ):
        if not body .get ("confirm"):
            self ._error_json (400 ,"Running a script requires confirm:true in the request body")
            return 
        name =body .get ("name")
        target =safe_join (LIB_SUBDIRS ["scripts"],name or "")
        if target is None or not os .path .isfile (target ):
            self ._error_json (404 ,f"Script not found: {name }")
            return 


        with _running_scripts_lock :
            if name in _running_scripts :
                self ._send_json (409 ,{
                "error":f"{name } is already running",
                "message":f"{name } is already running -- wait for it to finish before running it again.",
                "level":"warn",
                })
                return 
            _running_scripts .add (name )


        env_overrides ={}
        for field ,envvar in (
        ("auto_callsign","AUTO_CALLSIGN"),
        ("auto_node","AUTO_NODE"),
        ("auto_label","AUTO_LABEL"),
        ):
            val =body .get (field )
            if val :
                env_overrides [envvar ]=str (val )

        thread =threading .Thread (
        target =run_script_bg ,args =(target ,name ,env_overrides or None ),daemon =True ,
        )
        thread .start ()
        self ._send_json (200 ,{"started":name ,"message":f"Running {name } -- watch the log below for output.","level":"info"})


    def _action_gh_check (self ,body ):
        ok ,msg =gh_start_check ()
        self ._send_json (200 if ok else 409 ,{"message":msg ,"level":"info"if ok else "warn"})

    def _action_gh_update (self ,body ):
        if not body .get ("confirm"):
            self ._error_json (400 ,"A GitHub update requires confirm:true in the request body")
            return 
        code ,msg ,level =gh_start_update (body .get ("name"))
        self ._send_json (code ,{"message":msg ,"level":level })


    def _action_quiet(self, body):
        ok, msg, level = quiet_start()
        self._send_json(200 if ok else 409, {"message": msg, "level": level})

    def _action_restore(self, body):
        ok, msg, level = quiet_restore()
        self._send_json(200 if ok else 409, {"message": msg, "level": level})

    def _action_full_update(self, body):
        if not body.get("confirm"):
            self._error_json(400, "Full Update requires confirm:true in the request body")
            return
        code, msg, level = full_update_start()
        self._send_json(code, {"message": msg, "level": level})

    def _action_fu_dismiss(self, body):
        full_update_dismiss()
        self._send_json(200, {"message": "", "level": "info"})


    def _action_save_alternate (self ):
        live_cfg =os .path .join (CONFIG_DIR ,CONFIG_NAME )
        if not os .path .isfile (live_cfg ):
            self ._error_json (404 ,f"No active config at {live_cfg }")
            return 
        stamp =datetime .now ().strftime ("%Y%m%d_%H%M%S")
        base ,ext =os .path .splitext (CONFIG_NAME )
        alt_name =f"{base }_{stamp }{ext }"
        ensure_dirs ()
        dest =os .path .join (LIB_SUBDIRS ["config"],alt_name )
        shutil .copy2 (live_cfg ,dest )
        log_event (f"Saved active config as alternate: {alt_name }","ok")
        self ._send_json (200 ,{"name":alt_name ,"message":f"Saved active config as {alt_name }.","level":"ok"})


    def _action_comms_restart (self ,body ):
        
        
        
        
        
        
        
        stop_results =[]
        for label ,unit in COMMS_RESTART_SERVICES :
            try :
                r =subprocess .run (["systemctl","stop",unit ],capture_output =True ,text =True ,timeout =15 )
                stop_ok =r .returncode ==0 
            except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
                stop_ok =False 
                log_event (f"Comms restart: {label } ({unit }) stop errored: {exc }","err")
            else :
                log_event (f"Comms restart: {label } ({unit }) stopped"if stop_ok 
                else f"Comms restart: {label } ({unit }) stop FAILED (rc={r .returncode })",
                "info"if stop_ok else "err")
            stop_results .append ((label ,unit ,stop_ok ))

        log_event (f"Comms restart: pausing {COMMS_RESTART_PAUSE_SEC }s before bringing services back up...","info")
        time .sleep (COMMS_RESTART_PAUSE_SEC )

        results =[]
        for label ,unit ,stop_ok in stop_results :
            try :
                r =subprocess .run (["systemctl","start",unit ],capture_output =True ,text =True ,timeout =15 )
                start_ok =r .returncode ==0 
            except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
                log_event (f"Comms restart: {label } ({unit }) start errored: {exc }","err")
                results .append ((label ,False ,str (exc )))
                continue 
            state =systemctl_is_active (unit )
            ok =start_ok and state =="active"
            results .append ((label ,ok ,state ))
            log_event (f"Comms restart: {label } ({unit }) -> {'started'if ok else 'FAILED to start'} (now {state })",
            "ok"if ok else "err")

        failed =[label for label ,ok ,_ in results if not ok ]
        summary =", ".join (f"{label } {'ok'if ok else 'FAILED'}"for label ,ok ,_ in results )
        verb =f"full stop -> {COMMS_RESTART_PAUSE_SEC }s pause -> start"
        if failed :
            message =f"Comms SERV Restart ({verb }): {summary }. Check the log below for {', '.join (failed )}."
            level ="err"
        else :
            message =f"Comms SERV Restart ({verb }): all clear -- {summary }."
            level ="ok"
        self ._send_json (200 if not failed else 207 ,{
        "results":[{"service":label ,"ok":ok ,"state":state }for label ,ok ,state in results ],
        "message":message ,
        "level":level ,
        })


    def _action_reboot (self ,body ):
        log_event ("System reboot requested from instmon UI","warn")
        try :
            
            
            
            
            
            
            
            
            subprocess .run ([
            "systemd-run","--quiet","--collect",f"--on-active={REBOOT_SHUTDOWN_DELAY_SEC }",
            "--unit=instmon-reboot","systemctl","reboot",
            ],check =True ,timeout =10 )
        except (FileNotFoundError ,subprocess .TimeoutExpired ,subprocess .CalledProcessError )as exc :
            log_event (f"Reboot request failed: {exc }","err")
            self ._error_json (500 ,f"Could not schedule reboot: {exc }")
            return 
        self ._send_json (200 ,{
        "message":f"Rebooting in ~{REBOOT_SHUTDOWN_DELAY_SEC }s. This page (and everything else on the node) will be unreachable until it comes back up.",
        "level":"warn",
        })


    def _action_shutdown (self ,body ):
        log_event ("System shutdown requested from instmon UI","warn")
        try :
            subprocess .run ([
            "systemd-run","--quiet","--collect",f"--on-active={REBOOT_SHUTDOWN_DELAY_SEC }",
            "--unit=instmon-shutdown","systemctl","poweroff",
            ],check =True ,timeout =10 )
        except (FileNotFoundError ,subprocess .TimeoutExpired ,subprocess .CalledProcessError )as exc :
            log_event (f"Shutdown request failed: {exc }","err")
            self ._error_json (500 ,f"Could not schedule shutdown: {exc }")
            return 
        self ._send_json (200 ,{
        "message":f"Shutting down in ~{REBOOT_SHUTDOWN_DELAY_SEC }s. You'll need physical/console access (or a smart PDU) to power it back on.",
        "level":"warn",
        })


    def log_message (self ,format ,*args ):
        return 


def parse_multipart (raw ,boundary ):
    boundary_bytes =("--"+boundary ).encode ()
    parts =raw .split (boundary_bytes )
    result ={}
    for part in parts :
        part =part .strip (b"\r\n")
        if not part or part ==b"--":
            continue 
        if b"\r\n\r\n"not in part :
            continue 
        header_blob ,value =part .split (b"\r\n\r\n",1 )
        value =value [:-2 ]if value .endswith (b"\r\n")else value 
        headers =header_blob .decode (errors ="replace")
        name_match =re .search (r'name="([^"]+)"',headers )
        if not name_match :
            continue 
        filename_match =re .search (r'filename="([^"]*)"',headers )
        field_name =name_match .group (1 )
        filename =filename_match .group (1 )if filename_match else None 
        result [field_name ]=(filename ,value )
    return result 


def install_service ()->None :
    if os .geteuid ()!=0 :
        print ("Error: Installation requires root privileges. Run with 'sudo'.")
        sys .exit (1 )

    current_script =os .path .abspath (__file__ )

    print ("Installing instmon...")

    if current_script !=INSTALL_BIN_PATH :
        shutil .copy2 (current_script ,INSTALL_BIN_PATH )
        print (f"  [+] Copied script to {INSTALL_BIN_PATH }")
    os .chmod (INSTALL_BIN_PATH ,0o755 )

    with open (SYSTEMD_SERVICE_PATH ,"w")as f :
        f .write (SYSTEMD_SERVICE_CONTENT )
    print (f"  [+] Created service file at {SYSTEMD_SERVICE_PATH }")

    subprocess .run (["systemctl","daemon-reload"],check =True )
    subprocess .run (["systemctl","enable","instmon.service"],check =True )
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    subprocess .run ([
    "systemd-run","--quiet","--collect","--on-active=2",
    "--unit=instmon-selfrestart",
    "systemctl","restart","instmon.service",
    ],check =True )
    print ("  [+] Enabled instmon.service; restart scheduled in ~2s")
    print (f"\nInstallation complete! instmon will be listening on port {PORT } shortly.")
    print ("View logs anytime using:")
    print ("  journalctl -u instmon -f")
    print ("\nNote: instmon serves plaintext HTTP only (no built-in TLS).")
    print ("Keep it on a trusted LAN/VPN, or put a TLS-terminating reverse")
    print ("proxy in front of it if it needs to be reachable from anywhere less trusted.")


def uninstall_service ()->None :
    if os .geteuid ()!=0 :
        print ("Error: Uninstallation requires root privileges. Run with 'sudo'.")
        sys .exit (1 )

    print ("Uninstalling instmon...")

    subprocess .run (["systemctl","disable","--now","instmon.service"],stderr =subprocess .DEVNULL )
    print ("  [-] Stopped and disabled instmon.service")

    if os .path .exists (SYSTEMD_SERVICE_PATH ):
        os .remove (SYSTEMD_SERVICE_PATH )
        print (f"  [-] Removed {SYSTEMD_SERVICE_PATH }")

    subprocess .run (["systemctl","daemon-reload"],stderr =subprocess .DEVNULL )

    if os .path .exists (INSTALL_BIN_PATH ):
        os .remove (INSTALL_BIN_PATH )
        print (f"  [-] Removed {INSTALL_BIN_PATH }")

    print ("\nUninstallation complete.")
    print ("Note: the library/config/install directories under "
    f"{LIBRARY_DIR } were left in place -- remove manually if desired.")


class InstmonServer (http .server .ThreadingHTTPServer ):
    allow_reuse_address =True 
    daemon_threads =True 


def run ():
    ensure_dirs ()
    log_event (f"instmon v{VERSION } starting on port {PORT }","info")
    log_event (
    "Serving plaintext HTTP only (no built-in TLS). Keep this on a "
    "trusted LAN/VPN, or put a TLS-terminating reverse proxy in front "
    "of it if reachable from anywhere less trusted.",
    "info",
    )
    if os .geteuid ()!=0 :
        log_event (
        "Not running as root -- component install/uninstall, service "
        "restarts, and reboot/shutdown will fail with permission errors.",
        "warn",
        )

    _quiesce_startup_sweep ()
    full_update_resume_at_startup ()

    if HOME_SCAN_ENABLED :
        moved =scan_home_for_new_code ()
        if moved :
            log_event (f"Home-dir scan: staged {len (moved )} new file(s) from {HOME_SCAN_DIR }","ok")
        else :
            log_event (f"Home-dir scan: nothing new in {HOME_SCAN_DIR }","info")

    threading.Thread(target=_sd_watchdog_loop, daemon=True).start()

    threading.Thread(target=_diskimg_scheduler_loop, daemon=True).start()
    log_event("Disk-image scheduler thread started (checks once a minute).", "info")

    server_address =("",PORT )
    httpd =InstmonServer (server_address ,InstmonHandler )
    print (f"Starting instmon web installer v{VERSION } on port {PORT }...")
    try :
        httpd .serve_forever ()
    except KeyboardInterrupt :
        print ("\nShutting down instmon server.")
        httpd .server_close ()
        sys .exit (0 )


if __name__ =="__main__":
    parser =argparse .ArgumentParser (description ="instmon - KD8PGK Web Installer & Component Manager")
    parser .add_argument ("--install",action ="store_true",help ="Install instmon as a systemd service & start")
    parser .add_argument ("--uninstall",action ="store_true",help ="Stop & remove instmon systemd service")
    args =parser .parse_args ()

    if args .install :
        install_service ()
    elif args .uninstall :
        uninstall_service ()
    else :
        run ()