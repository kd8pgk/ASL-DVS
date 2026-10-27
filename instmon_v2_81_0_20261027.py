#!/usr/bin/env python3

import argparse
import collections
import fcntl
import fnmatch
import hashlib
import hmac 
import io
import html 
import http .client 
import http .server 
import ipaddress
import json 
import os 
import py_compile 
import pwd
import re
import secrets
import shlex
import shutil
import stat
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
VERSION ="2.81.0"
DATE_STR ="2026-10-27"

INSTALLER_SCRIPT_GLOBS =("install_all*.sh","install_asl_dvs*.sh")
UNINSTALLER_SCRIPT_GLOBS =("uninstall_all*.sh","uninstall_asl_dvs*.sh")

INTERACTIVE_ONLY_SCRIPT_GLOBS =("wifi_menu*.sh","wifi-menu*.sh")

SCRIPT_TIMEOUT_SEC =int (os .environ .get ("INSTMON_SCRIPT_TIMEOUT_SEC","600"))
MAX_UPLOAD_BYTES =int (os .environ .get ("INSTMON_MAX_UPLOAD_MB","50"))*1024 *1024 
REBOOT_SHUTDOWN_DELAY_SEC =int (os .environ .get ("INSTMON_REBOOT_SHUTDOWN_DELAY_SEC","2"))

INSTALL_BIN_PATH ="/usr/local/bin/instmon.py"
INSTALL_DIR = "/usr/local/lib/asl_dvs/instmon"
SYSTEMD_SERVICE_PATH ="/etc/systemd/system/instmon.service"

_LAUNCHER_PATH = "/usr/local/bin/asl_dvs_launch.py"
_SYSTEMD_UNIT_DIR = "/etc/systemd/system"
_LAUNCHER_CODE = '''#!/usr/bin/env python3
import os
import runpy
import sys

_OFF = "/etc/asl_dvs/launch_no_"
_AGAIN = "ASL_DVS_LAUNCH"

if _AGAIN in os.environ:
    if os.environ.pop(_AGAIN) == "arena":
        os.environ.pop("MALLOC_ARENA_MAX", None)
else:
    flags = []
    env = dict(os.environ)
    env[_AGAIN] = ""
    if sys.flags.optimize < 2 and not os.path.exists(_OFF + "optimize"):
        flags.append("-OO")
    if "MALLOC_ARENA_MAX" not in env and not os.path.exists(_OFF + "arena_cap"):
        env["MALLOC_ARENA_MAX"] = "2"
        env[_AGAIN] = "arena"
    if (flags or env[_AGAIN]) and sys.executable:
        try:
            os.execve(sys.executable, [sys.executable] + flags + sys.argv, env)
        except OSError:
            pass

def _trim_loop():
    import time
    time.sleep(60)
    try:
        import ctypes
        trim = ctypes.CDLL("libc.so.6").malloc_trim
    except (ImportError, OSError, AttributeError):
        return
    trim.argtypes = [ctypes.c_size_t]
    while True:
        trim(0)
        time.sleep(300)

if not os.path.exists(_OFF + "trim"):
    import threading
    threading.Thread(target=_trim_loop, name="mem-trim", daemon=True).start()

target = os.path.realpath(sys.argv[1])
name = os.path.splitext(os.path.basename(target))[0]
sys.argv = [target] + sys.argv[2:]
sys.path.insert(0, os.path.dirname(target))
if name.isidentifier():
    runpy.run_module(name, run_name="__main__", alter_sys=True)
else:
    import importlib.util
    spec = importlib.util.spec_from_file_location("__main__", target)
    main = importlib.util.module_from_spec(spec)
    sys.modules["__main__"] = main
    spec.loader.exec_module(main)
'''

SYSTEMD_SERVICE_CONTENT ="""[Unit]
Description=instmon Web Installer & Component Manager
After=network.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/instmon.py
Restart=always
RestartSec=3s
TimeoutStartSec=600
WatchdogSec=60s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

LIBRARY_DIR =os .environ .get ("INSTMON_LIBRARY_DIR","/etc/asl_dvs/instmon_library")
CONFIG_DIR =os .environ .get ("INSTMON_CONFIG_DIR","/etc/asl_dvs")
DOCS_DIR = os.path.join(LIBRARY_DIR, "docs")
APP_DIR = os.path.join(LIBRARY_DIR, "apps")
SNAP_DIR = os.path.join(LIBRARY_DIR, "snapshots")
CONFGETTER_BIN = "/usr/local/bin/confgetter.sh"
CONFGETTER_KEEP = 10
CONFPUTTER_BIN = "/usr/local/bin/confputter.py"
PUT_BACKUP_DIR = "/var/lib/confputter/backups"
EDITED_DIR = os.path.join(SNAP_DIR, "edited")
CP_MAX_UPLOAD = 3000000
CP_TIMEOUT_SEC = 180
CONFIG_NAME =os .environ .get ("INSTMON_CONFIG_NAME","asl_dvs.conf")
NODELISTEN_CONFIGS =(("nodetalker_favorites*.conf","nodetalker_favorites.conf"),("nodelisten_favorites*.conf","nodetalker_favorites.conf"),
("nodetalker*.conf","nodetalker.conf"),("nodelisten*.conf","nodetalker.conf"))
LIVE_CONFIGS =(CONFIG_NAME ,"nodetalker.conf","nodetalker_favorites.conf")
NL_LEGACY_NAMES ={"nodetalker.conf":"nodelisten.conf","nodetalker_favorites.conf":"nodelisten_favorites.conf"}

def _nl_live_name (name ):
    old =NL_LEGACY_NAMES .get (name )
    if old and not os .path .exists (os .path .join (CONFIG_DIR ,name )):
        p =os .path .join (CONFIG_DIR ,old )
        if os .path .isfile (p )and not os .path .islink (p ):
            return old 
    return name 

def live_configs ():
    out =[]
    for n in LIVE_CONFIGS :
        n =_nl_live_name (n )
        if n not in out and os .path .isfile (os .path .join (CONFIG_DIR ,n )):
            out .append (n )
    return out 

def config_dest_name (name ):
    low =os .path .basename (name or "").lower ()
    for pattern ,live in NODELISTEN_CONFIGS :
        if fnmatch .fnmatch (low ,pattern ):
            return _nl_live_name (live )
    return CONFIG_NAME 

HOME_SCAN_DIR =os .environ .get ("INSTMON_HOME_SCAN_DIR",os .path .expanduser ("~"))
HOME_SCAN_ENABLED =os .environ .get ("INSTMON_HOME_SCAN_ENABLED","1")!="0"
WIFI_MENU_HOME_DIR = os.environ.get("INSTMON_WIFI_MENU_HOME", "")
WIFI_MENU_HOME_NAME = "wifi_menu.sh"
WIFI_MENU_OLD_DIRS = ("/home/pi",)

_AUTH_ACCOUNT = "root"

def _read_shadow_hash(account):
    try:
        with open("/etc/shadow", "r") as fh:
            for line in fh:
                parts = line.rstrip("\n").split(":")
                if len(parts) >= 2 and parts[0] == account:
                    return parts[1]
    except Exception as exc:
        log_event(f"_read_shadow_hash: {exc}", "warn")
    return None

_libcrypt_handle = None

def _crypt_verify(password, stored_hash):
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

_SESSION_COOKIE_NAME = "instmon_session"
_SESSION_TTL_SEC = 12 * 3600
_auth_log_lock = threading.Lock()
_auth_log_state = {}

_sessions = {}
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
    "fsfreeze": "Freeze filesystem during copy",
    "pv": "Throttle speed",
    "ddrescue": "Resilient clone (ddrescue)",
}

def _diskimg_check_dependencies():
    missing_required = [t for t in _DISKIMG_REQUIRED_TOOLS if not shutil.which(t)]
    missing_optional = {t: feat for t, feat in _DISKIMG_OPTIONAL_TOOLS.items() if not shutil.which(t)}
    return {
        "ok": not missing_required and not missing_optional,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
    }

def _get_boot_disk():
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
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,MODEL,TRAN,TYPE,RM,MOUNTPOINT,FSTYPE,UUID"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
        log_event(f"_lsblk_json: lsblk query failed: {exc}", "warn")
        return None

def _disk_mountpoints(node):
    points = []
    mp = node.get("mountpoint")
    if mp:
        points.append(mp)
    for child in node.get("children") or []:
        points.extend(_disk_mountpoints(child))
    return points

def _disk_read_only(name):
    try:
        with open(f"/sys/block/{name}/ro", "r") as f:
            return f.read().strip() == "1"
    except OSError:
        return False

def _list_usb_drives():
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
            "fs_uuids": [c.get("uuid") for c in (node.get("children") or [node]) if c.get("uuid")],
        })
    return drives

def fmt_bytes(n):
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

def _diskimg_mount_all(disk_name):
    data = _lsblk_json()
    if data is None:
        return None, "lsblk query failed"
    node = next((n for n in data.get("blockdevices") or [] if n.get("name") == disk_name), None)
    if node is None:
        return None, "Drive not found"
    parts = node.get("children") or [node]
    mounted, already, skipped, errors = [], [], [], []
    for p in parts:
        fstype = (p.get("fstype") or "").lower()
        name = p.get("name") or ""
        dev_path = p.get("path") or f"/dev/{name}"
        if not fstype:
            continue
        if p.get("mountpoint"):
            already.append(f"{dev_path} at {p['mountpoint']}")
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            skipped.append(f"{dev_path} (bad name)")
            continue
        opts = "nosuid,nodev"
        if fstype in ("ntfs", "ntfs3"):
            mtype = _usbimport_ntfs_type()
            if mtype is None:
                skipped.append(f"{dev_path} (NTFS driver not installed)")
                continue
        elif fstype in _USBIMPORT_PLAIN_FS:
            mtype = fstype
        else:
            skipped.append(f"{dev_path} ({fstype})")
            continue
        mountpoint = os.path.join(_DISKIMG_MOUNT_ROOT, name)
        try:
            os.makedirs(mountpoint, exist_ok=True)
            res = subprocess.run(
                ["mount", "-t", mtype, "-o", opts, dev_path, mountpoint],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{dev_path}: {exc}")
            continue
        if res.returncode != 0:
            detail = (res.stderr or res.stdout or "").strip().replace("\n", " ")[:200]
            errors.append(f"{dev_path}: {detail or 'mount failed'}")
            try:
                os.rmdir(mountpoint)
            except OSError:
                pass
            continue
        mounted.append(f"{dev_path} at {mountpoint}")
    return {"mounted": mounted, "already": already, "skipped": skipped, "errors": errors}, None

def _diskimg_job_running():
    with _diskimg_job_lock:
        return _diskimg_job is not None and _diskimg_job.get("state") == "running"

_DISKIMG_LASTJOB_PATH = os.path.join(CONFIG_DIR, "instmon_diskimg_lastjob.json")

def _diskimg_lastjob_write(info):
    tmp = _DISKIMG_LASTJOB_PATH + ".tmp"
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(tmp, "w") as fh:
            json.dump(info, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, _DISKIMG_LASTJOB_PATH)
    except (OSError, TypeError, ValueError) as exc:
        log_event(f"Could not record the disk-image job state: {exc}", "warn")

def _diskimg_lastjob_recover():
    global _diskimg_job
    try:
        with open(_DISKIMG_LASTJOB_PATH, "r") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return
    if not isinstance(info, dict) or info.get("state") not in ("starting", "running"):
        return
    job_id = str(info.get("id") or "")
    kind = info.get("kind") or "job"
    if not re.fullmatch(r"[0-9a-f]{16}", job_id):
        return
    unit = f"instmon-diskimg-{job_id}.service"
    stopped_note = ""
    try:
        r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
        if (r.stdout or "").strip() == "active":
            subprocess.run(["systemctl", "stop", unit], capture_output=True, timeout=30)
            stopped_note = " The copy was still running on its own and has been stopped."
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    started = info.get("started") or time.time()
    when = datetime.fromtimestamp(started).strftime("%H:%M:%S")
    message = (f"instmon restarted while this {kind} was running (started {when}).{stopped_note} "
               "The destination is incomplete -- start it again.")
    log_event(f"STARTUP RECOVERY: disk-image {kind} {job_id} was interrupted by an instmon restart.{stopped_note}", "err")
    dest = info.get("dest") or ""
    if kind == "backup" and dest.endswith(_DISKIMG_PART_SUFFIX):
        _diskimg_remove_partial_backup(dest)
    with _diskimg_job_lock:
        if _diskimg_job is None:
            _diskimg_job = {
                "id": job_id, "kind": kind, "state": "failed", "phase": "done",
                "source": info.get("source") or "", "dest": dest,
                "bytes_done": 0, "bytes_total": info.get("bytes_total") or 0,
                "started": started, "finished": time.time(), "message": message,
                "proc": None, "unit_name": None, "cancelled": False,
                "verify_bytes_done": 0, "quiesced": False, "quiesce_stopped": [],
                "backend": info.get("backend") or "dd", "progress_format": "dd",
                "command_display": info.get("command_display") or "",
                "console": [f"[{when}] Started {kind}: {info.get('source') or '?'} -> {dest or '?'}",
                            f"[{datetime.now().strftime('%H:%M:%S')}] failed: {message}"],
            }
    info.update(state="failed", message=message, finished=time.time())
    _diskimg_lastjob_write(info)

def _diskimg_busy_reason():
    with _diskimg_job_lock:
        job = _diskimg_job
        if job is None:
            return None
        if job.get("state") == "running":
            return f"A disk-image {job.get('kind') or 'job'} is running -- wait for it to finish (or stop it) first."
        if job.get("quiesced") and job.get("phase") != "done":
            return "Node services are being restarted after a disk-image job -- try again in a moment."
    return None

_DISKIMG_PART_SUFFIX = ".part"
_FAT_MAX_FILE_BYTES = 4 * 1024 ** 3 - 1

def _diskimg_mount_fstype(mountpoint):
    try:
        r = subprocess.run(["findmnt", "-no", "FSTYPE", "--target", mountpoint],
                           capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    return (r.stdout or "").strip().splitlines()[0].lower() if (r.stdout or "").strip() else ""

def _diskimg_fat_limit_reason(mountpoint, size_bytes, drive_path):
    fstype = _diskimg_mount_fstype(mountpoint)
    if fstype in ("vfat", "msdos", "fat") and size_bytes > _FAT_MAX_FILE_BYTES:
        return (f"{drive_path} is formatted FAT32, which can't hold a file over 4 GB, and this image is "
                f"{fmt_bytes(size_bytes)} -- format the drive as ext4 or exFAT on the Full Format card first.")
    return None

def _diskimg_clear_stale_parts(backup_dir):
    with _diskimg_job_lock:
        active = _diskimg_job.get("dest") if (_diskimg_job is not None and _diskimg_job.get("state") == "running") else None
    try:
        names = os.listdir(backup_dir)
    except OSError:
        return
    for name in names:
        if not (name.endswith(".img" + _DISKIMG_PART_SUFFIX) or name.endswith(_DISKIMG_ENCRYPTED_SUFFIX + _DISKIMG_PART_SUFFIX)):
            continue
        full = os.path.join(backup_dir, name)
        if full == active or os.path.islink(full) or not os.path.isfile(full):
            continue
        try:
            os.remove(full)
            log_event(f"Deleted an unfinished backup left by an interrupted job: {name}", "warn")
        except OSError as exc:
            log_event(f"Could not delete the unfinished backup {name}: {exc}", "warn")

_DISKIMG_BACKUP_DIRNAME = "instmon-backups"
_DD_PROGRESS_RE = re.compile(rb"(\d+)\s+bytes")

_PV_PROGRESS_RE = re.compile(rb"([\d.]+)\s*([KMGT]?i?B)\b")
_PV_UNIT_MULTIPLIERS = {
    "B": 1,
    "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4,
    "kiB": 1024,
    "KB": 1000, "kB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "TB": 1000 ** 4,
}
_DDRESCUE_PROGRESS_RE = re.compile(rb"rescued:\s*([\d.]+)\s*([kKMGT]?i?B)")
_ANSI_ESCAPE_RE = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]")
_DDRESCUE_STATUS_LINE_RE = re.compile(
    rb"(ipos:|opos:|non-tried:|non-trimmed:|non-scraped:|bad-sector:|rescued:|"
    rb"time since last successful read|^\s*(Copying|Trimming|Scraping|Retrying|Finished|Press Ctrl-C|GNU ddrescue))")

def _diskimg_parse_meter_bytes(amount_bytes, unit_bytes):
    try:
        amount = float(amount_bytes)
    except ValueError:
        return None
    unit = unit_bytes.decode("ascii", "replace")
    return int(amount * _PV_UNIT_MULTIPLIERS.get(unit, 1))

_diskimg_job = None
_diskimg_job_lock = threading.Lock()

_DISKIMG_CONSOLE_MAX_LINES = 300

def _diskimg_console_append(job_id, text):
    ts = datetime.now().strftime("%H:%M:%S")
    with _diskimg_job_lock:
        if _diskimg_job is None or _diskimg_job["id"] != job_id:
            return
        console = _diskimg_job.setdefault("console", [])
        console.append(f"[{ts}] {text}")
        del console[:-_DISKIMG_CONSOLE_MAX_LINES]

def _diskimg_command_display(cmd):
    if len(cmd) == 3 and cmd[0] == "bash" and cmd[1] == "-c":
        return cmd[2]
    if len(cmd) > 3 and cmd[-3] == "bash" and cmd[-2] == "-c":
        return " ".join(shlex.quote(a) for a in cmd[:-3]) + " bash -c:\n" + cmd[-1]
    return " ".join(shlex.quote(a) for a in cmd)

_DISKIMG_RUN_DIR = "/run" if os.path.isdir("/run") else tempfile.gettempdir()
_HASH_TOOLS = {"sha256": "sha256sum", "blake2b": "b2sum"}
_HASH_HEX_LEN = {"sha256": 64, "blake2b": 128}

def _diskimg_hash_path(job_id):
    return os.path.join(_DISKIMG_RUN_DIR, f"instmon-diskimg-{job_id}.hash")

def _diskimg_hash_cleanup(hash_path):
    if not hash_path:
        return
    for suffix in ("", ".tmp", ".fifo"):
        try:
            os.remove(hash_path + suffix)
        except OSError:
            pass

def _diskimg_hasher_shell(algo, in_path_expr, out_path):
    tool = _HASH_TOOLS.get(algo)
    if tool and shutil.which(tool):
        return f"{tool} < {in_path_expr} | cut -d' ' -f1 > {shlex.quote(out_path)}"
    py = ("import hashlib,sys;h=hashlib.new(sys.argv[1]);"
          "[h.update(b) for b in iter(lambda: sys.stdin.buffer.read(4194304), b'')];print(h.hexdigest())")
    return (" ".join(shlex.quote(a) for a in [sys.executable or "python3", "-c", py, algo])
            + f" < {in_path_expr} > {shlex.quote(out_path)}")

def _diskimg_hashed_stream_command(mode, src, dst, unit_name, hash_path, algo,
                                   best_effort=False, direct_io=False, rate_mb=None, count_bytes=None):
    q = shlex.quote
    in_conv = (" conv=sync,noerror" if best_effort else "") + (f" count={int(count_bytes)} iflag=count_bytes" if count_bytes else "")
    out_flags = "iflag=fullblock conv=fsync status=none" + (" oflag=direct" if direct_io else "")
    openssl = " ".join(q(a) for a in ["openssl", "enc"] + _OPENSSL_ENC_ARGS + ["-pass", f"env:{_DISKIMG_PASS_ENV_VAR}"])
    stages = [f"dd if={q(src)} bs=4M status=progress{in_conv}"]
    if rate_mb:
        stages.append(f"pv -q -L {int(rate_mb)}m")
    if mode == "encrypt":
        stages.append(openssl + " -e")
    stages.append('tee "$fifo"')
    if mode == "decrypt":
        stages.append(openssl + " -d")
    stages.append(f"dd of={q(dst)} bs=4M {out_flags}")
    tmp = hash_path + ".tmp"
    script = (
        "set -o pipefail\n"
        f"fifo={q(hash_path + '.fifo')}\n"
        'rm -f "$fifo"; mkfifo -m 600 "$fifo" || exit 1\n'
        "trap 'rm -f \"$fifo\"' EXIT\n"
        f'{_diskimg_hasher_shell(algo, chr(34) + "$fifo" + chr(34), tmp)} &\n'
        "hp=$!\n"
        + " | ".join(stages) + "\n"
        "rc=$?\n"
        'wait "$hp"; hrc=$?\n'
        'if [ "$rc" -eq 0 ] && [ "$hrc" -ne 0 ]; then echo "checksum process failed (exit $hrc)" >&2; rc=1; fi\n'
        f'if [ "$rc" -eq 0 ]; then mv -f {q(tmp)} {q(hash_path)}; else rm -f {q(tmp)}; fi\n'
        'exit "$rc"\n'
    )
    cmd = ["bash", "-c", script]
    if mode in ("encrypt", "decrypt") or not shutil.which("systemd-run"):
        return cmd, False
    return ["systemd-run", "--quiet", "--pipe", "--collect", f"--unit={unit_name}"] + cmd, True

def _diskimg_read_hash_file(path, algo):
    try:
        with open(path, "r", errors="replace") as fh:
            words = fh.read(4096).split()
    except OSError:
        return None
    want = _HASH_HEX_LEN.get(algo)
    if words and want and re.fullmatch(r"[0-9a-f]{%d}" % want, words[0]):
        return words[0]
    return None

def _diskimg_drop_cache(fileobj):
    try:
        os.fsync(fileobj.fileno())
    except OSError:
        pass
    try:
        os.posix_fadvise(fileobj.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    except (AttributeError, OSError):
        pass

def _diskimg_hash_readback(job_id, path, nbytes, algo):
    hasher = _VERIFY_HASHERS.get(algo, hashlib.sha256)()
    try:
        with open(path, "rb") as fh:
            _diskimg_drop_cache(fh)
            remaining = nbytes
            while remaining > 0:
                with _diskimg_job_lock:
                    if _diskimg_job is None or _diskimg_job["id"] != job_id:
                        return "cancelled", "Job no longer active."
                    if _diskimg_job.get("cancelled"):
                        return "cancelled", "Stopped -- the copy on disk is unaffected."
                chunk = fh.read(min(_VERIFY_CHUNK_SIZE, remaining))
                if not chunk:
                    return "error", f"{path} ended {fmt_bytes(remaining)} earlier than expected."
                hasher.update(chunk)
                remaining -= len(chunk)
                with _diskimg_job_lock:
                    if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                        _diskimg_job["verify_bytes_done"] = nbytes - remaining
            _diskimg_drop_cache(fh)
    except OSError as exc:
        return "error", f"Could not read {path}: {exc}"
    return "ok", hasher.hexdigest()

_DISKIMG_SIDECAR_SUFFIX = ".json"

def _diskimg_read_sidecar(image_path):
    try:
        with open(image_path + _DISKIMG_SIDECAR_SUFFIX, "r") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    algo = data.get("algo")
    digest = data.get("hash")
    if algo not in _HASH_HEX_LEN or not isinstance(digest, str) \
            or not re.fullmatch(r"[0-9a-f]{%d}" % _HASH_HEX_LEN[algo], digest):
        return None
    try:
        data["size"] = int(data.get("size"))
    except (TypeError, ValueError):
        return None
    return data

def _diskimg_write_sidecar(image_path, data):
    target = image_path + _DISKIMG_SIDECAR_SUFFIX
    tmp = target + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        return None
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return str(exc)

def _diskimg_remove_sidecar(image_path):
    try:
        os.remove(image_path + _DISKIMG_SIDECAR_SUFFIX)
    except OSError:
        pass

def _diskimg_settle(dest):
    try:
        subprocess.run(["partprobe", dest], capture_output=True, timeout=20)
        if shutil.which("udevadm"):
            subprocess.run(["udevadm", "settle", "--timeout=10"], capture_output=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        pass
    time.sleep(0.5)

_MIB = 1024 * 1024

def _blkid_probe(dev):
    try:
        res = subprocess.run(["blkid", "-p", "-o", "export", dev], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {}
    out = {}
    for line in (res.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def _diskimg_pttype(dev, lsblk_value=None):
    return (lsblk_value or _blkid_probe(dev).get("PTTYPE") or "").lower()

def _diskimg_copy_extent(disk_path, disk_size):
    try:
        out = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,START,SIZE,TYPE,PTTYPE", disk_path],
                             capture_output=True, text=True, timeout=10, check=True)
        tree = json.loads(out.stdout)
        disk = (tree.get("blockdevices") or [None])[0]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError, IndexError):
        return disk_size, None
    if not disk or _diskimg_pttype(disk_path, disk.get("pttype")) != "dos":
        return disk_size, None
    ends = []
    for c in disk.get("children") or []:
        try:
            if c.get("type") == "part" and c.get("start") is not None:
                ends.append(int(c["start"]) * 512 + int(c.get("size") or 0))
        except (TypeError, ValueError):
            return disk_size, None
    if not ends:
        return disk_size, None
    end = min(disk_size, -(-max(ends) // _MIB) * _MIB)
    if end <= 0 or end >= disk_size:
        return disk_size, None
    return end, f"Only the partitions are copied -- {fmt_bytes(end)} of the {fmt_bytes(disk_size)} disk."

def _diskimg_low_priority(cmd, detached):
    if detached and cmd[:1] == ["systemd-run"]:
        return cmd[:1] + ["-p", "Nice=10", "-p", "IOSchedulingClass=best-effort", "-p", "IOSchedulingPriority=7"] + cmd[1:]
    prefix = []
    if shutil.which("nice"):
        prefix += ["nice", "-n", "10"]
    if shutil.which("ionice"):
        prefix += ["ionice", "-c2", "-n7"]
    return prefix + cmd

def _diskimg_partition_ids(dest):
    out = subprocess.run(["lsblk", "-J", "-o", "NAME,PATH,TYPE", dest],
                         capture_output=True, text=True, timeout=10, check=True)
    disk = (json.loads(out.stdout).get("blockdevices") or [None])[0] or {}
    parts = []
    for c in disk.get("children") or []:
        if c.get("type") != "part" or not c.get("path"):
            continue
        probe = _blkid_probe(c["path"])
        parts.append((c["path"], (probe.get("TYPE") or "").lower(), (probe.get("PART_ENTRY_UUID") or "").lower()))
    return _diskimg_pttype(dest), parts

_RELABEL_FILES = ("cmdline.txt", "etc/fstab")

def _diskimg_new_disk_ids(dest):
    for tool in ("lsblk", "mount", "umount", "partprobe"):
        if not shutil.which(tool):
            return False, f"'{tool}' is not installed"
    _diskimg_settle(dest)
    try:
        pttype, before = _diskimg_partition_ids(dest)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return False, f"could not read the partition table: {exc}"
    if pttype == "dos":
        if not shutil.which("sfdisk"):
            return False, "sfdisk (package fdisk) is not installed"
        new_id = secrets.randbits(32) or 1
        res = subprocess.run(["sfdisk", "--disk-id", dest, f"0x{new_id:08x}"], capture_output=True, text=True, timeout=30)
        label = f"disk ID 0x{new_id:08x}"
    elif pttype == "gpt":
        if not shutil.which("sgdisk"):
            return False, "the drive uses GPT and sgdisk (package gdisk) is not installed"
        res = subprocess.run(["sgdisk", "-G", dest], capture_output=True, text=True, timeout=30)
        label = "new GPT disk and partition GUIDs"
    else:
        return False, "the drive has no partition table"
    if res.returncode != 0:
        return False, f"could not change the disk ID: {(res.stderr or res.stdout).strip()}"
    _diskimg_settle(dest)
    try:
        _pt, after = _diskimg_partition_ids(dest)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return False, f"the disk ID was changed, but the new partition IDs could not be read ({exc}) -- check cmdline.txt and fstab on the copy before booting it"
    old_by_path = {path: pu for path, _fs, pu in before}
    mapping = {old_by_path[path]: pu for path, _fs, pu in after
               if old_by_path.get(path) and pu and old_by_path[path] != pu}
    if not mapping:
        return False, "the partition IDs did not change"
    edited, problems = [], []
    os.makedirs(_DISKIMG_MOUNT_ROOT, exist_ok=True)
    for path, fstype, _pu in after:
        if fstype not in ("vfat", "ext2", "ext3", "ext4"):
            continue
        mp = os.path.join(_DISKIMG_MOUNT_ROOT, "relabel-" + os.path.basename(path))
        try:
            os.makedirs(mp, exist_ok=True)
            m = subprocess.run(["mount", "-t", fstype, "-o", "nosuid,nodev", path, mp],
                               capture_output=True, text=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError) as exc:
            problems.append(f"{path}: {exc}")
            continue
        if m.returncode != 0:
            problems.append(f"{path}: {(m.stderr or m.stdout).strip()}")
            try:
                os.rmdir(mp)
            except OSError:
                pass
            continue
        try:
            for rel in _RELABEL_FILES:
                target = os.path.join(mp, rel)
                if os.path.islink(target) or not os.path.isfile(target):
                    continue
                try:
                    with open(target, "r", errors="surrogateescape") as fh:
                        text = fh.read()
                    new_text = text
                    for old, new in mapping.items():
                        new_text = re.sub(re.escape(old), new, new_text, flags=re.IGNORECASE)
                    if new_text == text:
                        continue
                    tmp = target + ".instmon-tmp"
                    try:
                        with open(tmp, "w", errors="surrogateescape") as fh:
                            fh.write(new_text)
                            fh.flush()
                            os.fsync(fh.fileno())
                        os.replace(tmp, target)
                    except OSError:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                        if len(new_text.encode("utf-8", "surrogateescape")) != len(text.encode("utf-8", "surrogateescape")):
                            raise
                        with open(target, "r+", errors="surrogateescape") as fh:
                            fh.write(new_text)
                            fh.flush()
                            os.fsync(fh.fileno())
                    edited.append(f"{rel} on {os.path.basename(path)}")
                except OSError as exc:
                    problems.append(f"{rel} on {os.path.basename(path)}: {exc}")
        finally:
            subprocess.run(["sync"], capture_output=True, timeout=60)
            subprocess.run(["umount", mp], capture_output=True, timeout=30)
            try:
                os.rmdir(mp)
            except OSError:
                pass
    message = f"Gave the copy {label}"
    message += f" and updated {', '.join(edited)}." if edited else " (no cmdline.txt or fstab on it referred to the old IDs)."
    if problems:
        return False, message + " Problems: " + "; ".join(problems) + " -- check the copy before booting it."
    return True, message

def _diskimg_unmount_all(mountpoints):
    errors = []
    for mp in sorted(mountpoints, key=len, reverse=True):
        try:
            result = subprocess.run(["umount", mp], capture_output=True, text=True, timeout=20)
            if result.returncode != 0:
                errors.append(f"{mp}: {(result.stderr or result.stdout).strip()}")
                continue
        except (subprocess.TimeoutExpired, OSError) as exc:
            errors.append(f"{mp}: {exc}")
            continue
        if os.path.dirname(os.path.normpath(mp)) == _DISKIMG_MOUNT_ROOT:
            try:
                os.rmdir(mp)
            except OSError:
                pass
    return errors

def _diskimg_power_off(drive):
    name = drive.get("name") or ""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return False, "bad drive name"
    if shutil.which("udisksctl"):
        try:
            r = subprocess.run(["udisksctl", "power-off", "-b", drive["path"], "--no-user-interaction"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return True, "powered off"
        except (subprocess.TimeoutExpired, OSError):
            pass
    try:
        with open(f"/sys/block/{name}/device/delete", "w") as fh:
            fh.write("1\n")
        return True, "removed from the system"
    except OSError as exc:
        return False, str(exc)

def _diskimg_expand_to_fill(dest):
    for tool in ("parted", "partprobe", "lsblk", "blkid", "e2fsck", "resize2fs"):
        if not shutil.which(tool):
            return False, f"'{tool}' is not installed"

    def settle():
        _diskimg_settle(dest)

    settle()
    try:
        out = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,START,SIZE,TYPE,PTTYPE", dest],
                             capture_output=True, text=True, timeout=10, check=True)
        tree = json.loads(out.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return False, f"could not read the partition table: {exc}"
    disks = tree.get("blockdevices") or []
    if not disks:
        return False, "the drive was not found"
    disk = disks[0]
    parts = [c for c in disk.get("children") or [] if c.get("type") == "part" and c.get("start") is not None]
    if not parts:
        return False, "no partitions found on the drive"
    last = max(parts, key=lambda c: int(c.get("start") or 0))
    m = re.search(r"(\d+)$", last.get("name") or "")
    part_path = last.get("path")
    if not m or not part_path:
        return False, "could not identify the last partition"
    number = int(m.group(1))
    pttype = _diskimg_pttype(dest, disk.get("pttype"))
    if pttype == "dos" and number > 4:
        return False, "the last partition is a logical partition, which isn't expanded here"
    try:
        disk_size = int(disk.get("size") or 0)
        part_end = int(last["start"]) * 512 + int(last.get("size") or 0)
    except (TypeError, ValueError):
        return False, "could not read partition sizes"
    if disk_size - part_end < 2 * _MIB:
        return True, "The last partition already fills the drive."
    fstype = (_blkid_probe(part_path).get("TYPE") or "").lower()
    if fstype not in ("ext2", "ext3", "ext4"):
        return False, f"the last partition is '{fstype or 'unknown'}' -- only ext2/3/4 can be expanded here"
    if pttype == "gpt":
        if not shutil.which("sgdisk"):
            return False, "the drive uses GPT and sgdisk (package gdisk) is not installed"
        g = subprocess.run(["sgdisk", "-e", dest], capture_output=True, text=True, timeout=30)
        if g.returncode != 0:
            return False, f"sgdisk -e failed: {(g.stderr or g.stdout).strip()}"
        settle()
    resize = subprocess.run(["parted", "-s", dest, "unit", "s", "resizepart", str(number), "100%"],
                            capture_output=True, text=True, timeout=60)
    if resize.returncode != 0:
        resize = subprocess.run(["parted", "---pretend-input-tty", dest, "unit", "s", "resizepart", str(number), "100%"],
                                input="Yes\n", capture_output=True, text=True, timeout=60)
        if resize.returncode != 0:
            return False, f"parted resizepart failed: {(resize.stderr or resize.stdout).strip()}"
    settle()
    fsck = subprocess.run(["e2fsck", "-f", "-y", part_path], capture_output=True, text=True, timeout=1800)
    if fsck.returncode not in (0, 1):
        return False, (f"the partition was grown, but e2fsck -f -y exited {fsck.returncode}, so the filesystem "
                       "was left at its old size -- check the drive before using it")
    grow = subprocess.run(["resize2fs", part_path], capture_output=True, text=True, timeout=1800)
    if grow.returncode != 0:
        return False, f"the partition was grown, but resize2fs failed: {(grow.stderr or grow.stdout).strip()}"
    return True, f"Expanded {part_path} to fill the drive ({fmt_bytes(disk_size - int(last['start']) * 512)})."

_WIPE_BLOCK_SIZE = 4 * 1024 * 1024

_QUICK_WIPE_BYTES = 16 * 1024 * 1024

def _diskimg_format_wipe_bytes(size_bytes, quick=False):
    if quick:
        return max(_WIPE_BLOCK_SIZE, min(size_bytes, _QUICK_WIPE_BYTES))
    return size_bytes

def _diskimg_wipe_command(dst, size_bytes, unit_name, quick=False):
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

def _diskimg_dd_command(src, dst, unit_name, best_effort=False, direct_io=False, count_bytes=None):
    conv = "fsync,sync,noerror" if best_effort else "fsync"
    dd_cmd = ["dd", f"if={src}", f"of={dst}", "bs=4M", "status=progress", f"conv={conv}"]
    if count_bytes:
        dd_cmd += [f"count={int(count_bytes)}", "iflag=count_bytes"]
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

_DISKIMG_PASS_ENV_VAR = "INSTMON_DISKIMG_PASS"
_DISKIMG_ENCRYPTED_SUFFIX = ".img.enc"
_OPENSSL_ENC_ARGS = ["-aes-256-cbc", "-pbkdf2", "-salt"]

def _diskimg_pipeline_command(mode, src, dst, best_effort=False):
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

def _diskimg_throttled_dd_command(src, dst, rate_mb, unit_name, best_effort=False, direct_io=False, count_bytes=None):
    in_conv = (" conv=sync,noerror" if best_effort else "") + (f" count={int(count_bytes)} iflag=count_bytes" if count_bytes else "")
    out_flags = "status=none conv=fsync" + (" oflag=direct" if direct_io else "")
    script = (
        f"set -o pipefail; dd if={shlex.quote(src)} bs=4M status=progress{in_conv} | "
        f"pv -q -L {int(rate_mb)}m | "
        f"dd of={shlex.quote(dst)} bs=4M {out_flags}"
    )
    return ["bash", "-c", script], False

_DISKIMG_MAPFILE_SUFFIX = ".ddrescue.map"

def _diskimg_ddrescue_mapfile_path(job_id):
    return os.path.join(CONFIG_DIR, f"instmon_diskimg_{job_id}{_DISKIMG_MAPFILE_SUFFIX}")

def _diskimg_ddrescue_command(src, dst, mapfile_path, unit_name, count_bytes=None):
    ddrescue_cmd = ["ddrescue", "-d", "-b", "4MiB"] + ([f"--size={int(count_bytes)}"] if count_bytes else []) + [src, dst, mapfile_path]
    if shutil.which("systemd-run"):
        return (
            ["systemd-run", "--quiet", "--pipe", "--collect", f"--unit={unit_name}"] + ddrescue_cmd,
            True,
        )
    log_event("systemd-run not found -- disk-image job will run undetached "
              "and will NOT survive an instmon restart", "warn")
    return ddrescue_cmd, False

_RPICLONE_COMMIT = "e640eff1caa29e70bb3beaea21afb36ad6311313"
_RPICLONE_FILES = (
    ("rpi-clone", "5594dca9129c95154c1f2e28c496feb7f4e49e5a5c356534b1341871970e74ca"),
    ("rpi-clone-setup", "bd6adaa1584f4ac58b8520dccca51d49abb1b548cc8c39986b73f460acc5369c"),
)
_RPICLONE_SCRIPT_NAME = "rpi-clone install"
_RPICLONE_MOUNTS = ("/mnt/clone", "/mnt/clone-src")
_RPICLONE_HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")

def _rpiclone_status():
    path = shutil.which("rpi-clone")
    if not path:
        return {"installed": False, "version": None, "path": None}
    version = None
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                m = re.match(r"version=([\w.]+)", line)
                if m:
                    version = m.group(1)
                    break
    except OSError:
        pass
    return {"installed": True, "version": version, "path": path}

def _rpiclone_install_script():
    base = f"https://raw.githubusercontent.com/geerlingguy/rpi-clone/{_RPICLONE_COMMIT}"
    lines = [
        "#!/bin/bash",
        "set -euo pipefail",
        "export DEBIAN_FRONTEND=noninteractive",
        f'echo "=== rpi-clone install (headless, pinned to {_RPICLONE_COMMIT[:12]}) ==="',
        'need=""',
        "for pair in rsync:rsync parted:parted fdisk:fdisk sfdisk:fdisk findmnt:util-linux column:bsdextrautils fsck.vfat:dosfstools; do",
        '  cmd="${pair%%:*}"; pkg="${pair#*:}"',
        '  if ! command -v "$cmd" >/dev/null 2>&1; then echo "missing $cmd (package $pkg)"; need="$need $pkg"; fi',
        "done",
        'if [ -n "$need" ]; then',
        '  echo "--- apt-get update ---"',
        "  apt-get update -q",
        '  echo "--- apt-get install$need ---"',
        "  apt-get install -y --no-install-recommends -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold $need",
        "else",
        '  echo "All packages rpi-clone needs are already installed."',
        "fi",
        'tmp="$(mktemp -d)"',
        "trap 'rm -rf \"$tmp\"' EXIT",
        'fetch() { if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 3 -o "$1" "$2"; else wget -q -O "$1" "$2"; fi; }',
    ]
    for name, digest in _RPICLONE_FILES:
        lines += [
            f'echo "--- downloading {name} ---"',
            f'fetch "$tmp/{name}" "{base}/{name}"',
            f'echo "{digest}  $tmp/{name}" | sha256sum -c -',
        ]
    lines += [
        "install -m 755 -o root -g root " + " ".join(f'"$tmp/{n}"' for n, _d in _RPICLONE_FILES) + " /usr/local/sbin/",
        'echo "Installed: $(grep -m1 \'^version=\' /usr/local/sbin/rpi-clone) in /usr/local/sbin"',
        'echo "=== rpi-clone install done -- File sync (rpi-clone) is now on the Clone card ==="',
    ]
    return "\n".join(lines) + "\n"

def _rpiclone_args(force=False, hostname=None):
    args = ["-U"]
    if force:
        args.append("-f")
    if hostname:
        args += ["-s", hostname]
    return args

_RPICLONE_BOOT_DIRS = ("/boot/firmware", "/boot")

def _rpiclone_boot_mounted():
    try:
        with open("/proc/mounts", "r") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) >= 3 and parts[1] in _RPICLONE_BOOT_DIRS and parts[2] == "vfat":
            return parts[1]
    return None

def _rpiclone_fstab_has(mountpoint):
    try:
        with open("/etc/fstab", "r") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and not parts[0].startswith("#") and parts[1] == mountpoint:
                    return True
    except OSError:
        pass
    return False

def _rpiclone_prepare_boot():
    mp = _rpiclone_boot_mounted()
    if mp:
        return True, mp
    for d in _RPICLONE_BOOT_DIRS:
        if os.path.isdir(d):
            try:
                os.listdir(d)
            except OSError:
                pass
    mp = _rpiclone_boot_mounted()
    if mp:
        return True, mp
    for d in _RPICLONE_BOOT_DIRS:
        if _rpiclone_fstab_has(d):
            try:
                subprocess.run(["mount", d], capture_output=True, text=True, timeout=20)
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue
            mp = _rpiclone_boot_mounted()
            if mp:
                log_event(f"rpi-clone: mounted the boot partition at {mp} so rpi-clone can find it.", "info")
                return True, mp
    return False, ("This Pi's boot partition isn't mounted as vfat at /boot/firmware or /boot, and rpi-clone needs it "
                   "there to find the boot device. Mount it (for example: mount /boot/firmware) and try again, or use "
                   "the Standard (dd) copy method.")

def _diskimg_rpiclone_command(dst, unit_name, extra_args):
    cmd = ["bash", "-c", 'ls /boot/firmware /boot >/dev/null 2>&1; exec rpi-clone "$@"', "rpi-clone",
           os.path.basename(dst)] + list(extra_args or ["-U"])
    if shutil.which("systemd-run"):
        return (
            ["systemd-run", "--quiet", "--pipe", "--collect", f"--unit={unit_name}"] + cmd,
            True,
        )
    log_event("systemd-run not found -- disk-image job will run undetached "
              "and will NOT survive an instmon restart", "warn")
    return cmd, False

def _rpiclone_cleanup_mounts():
    for mp in _RPICLONE_MOUNTS:
        try:
            if subprocess.run(["findmnt", mp], capture_output=True, timeout=10).returncode == 0:
                subprocess.run(["umount", "-R", mp], capture_output=True, timeout=30)
                log_event(f"rpi-clone: unmounted leftover {mp}", "info")
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            log_event(f"rpi-clone: could not unmount {mp}: {exc}", "warn")

def _diskimg_freeze(action):
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
            algo = params.get("verify_algo") if params.get("verify_algo") in _HASH_HEX_LEN else "sha256"
            full = _disk_size_bytes(boot_disk) or 0
            extent, extent_note = _diskimg_copy_extent(src_path, full) if full else (0, None)
            count = extent if (extent and extent < full) else None
            if backend != "ddrescue":
                cmd, _detached = _diskimg_hashed_stream_command(
                    "encrypt" if encrypt else "plain", src_path, dest_display + _DISKIMG_PART_SUFFIX,
                    "instmon-diskimg-<job>", os.path.join(_DISKIMG_RUN_DIR, "instmon-diskimg-<job>.hash"), algo,
                    best_effort=best_effort, rate_mb=throttle_rate_mb if (throttle_rate_mb and not encrypt) else None,
                    count_bytes=count,
                )
            elif backend == "ddrescue":
                cmd, _detached = _diskimg_ddrescue_command(
                    src_path, dest_display, "<job-id>.ddrescue.map", "instmon-diskimg-<job>", count_bytes=count,
                )
            elif throttle_rate_mb:
                cmd, _detached = _diskimg_throttled_dd_command(
                    src_path, dest_display, throttle_rate_mb, "instmon-diskimg-<job>", best_effort=best_effort,
                )
            else:
                cmd, _detached = _diskimg_dd_command(src_path, dest_display, "instmon-diskimg-<job>", best_effort=best_effort)
            return (
                _diskimg_command_display(cmd),
                ((extent_note + " ") if extent_note else "")
                + "Exact filename/timestamp and mount path are finalized when the job actually starts.",
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
            backend = params.get("backend") if params.get("backend") in ("dd", "ddrescue", "rpiclone") else "dd"
            throttle_rate_mb = params.get("throttle_rate_mb")
            if backend == "rpiclone":
                host = (params.get("rpi_hostname") or "").strip()
                if host and not _RPICLONE_HOST_RE.fullmatch(host):
                    return None, "Hostname for the clone: letters, digits and dashes only, up to 63 characters."
                cmd, _detached = _diskimg_rpiclone_command(
                    match["path"], "instmon-diskimg-<job>", _rpiclone_args(bool(params.get("rpi_force")), host or None),
                )
                note = None if _rpiclone_status()["installed"] else "rpi-clone is not installed -- press Install rpi-clone first."
                return _diskimg_command_display(cmd), note
            full = _disk_size_bytes(boot_disk) or 0
            extent, extent_note = _diskimg_copy_extent(src_path, full) if full else (0, None)
            count = extent if (extent and extent < full) else None
            if backend == "ddrescue":
                cmd, _detached = _diskimg_ddrescue_command(
                    src_path, match["path"], "<job-id>.ddrescue.map", "instmon-diskimg-<job>", count_bytes=count,
                )
            elif params.get("verify"):
                algo = params.get("verify_algo") if params.get("verify_algo") in _HASH_HEX_LEN else "sha256"
                cmd, _detached = _diskimg_hashed_stream_command(
                    "plain", src_path, match["path"], "instmon-diskimg-<job>",
                    os.path.join(_DISKIMG_RUN_DIR, "instmon-diskimg-<job>.hash"), algo,
                    best_effort=best_effort, direct_io=direct_io, rate_mb=throttle_rate_mb, count_bytes=count,
                )
            elif throttle_rate_mb:
                cmd, _detached = _diskimg_throttled_dd_command(
                    src_path, match["path"], throttle_rate_mb, "instmon-diskimg-<job>",
                    best_effort=best_effort, direct_io=direct_io, count_bytes=count,
                )
            else:
                cmd, _detached = _diskimg_dd_command(
                    src_path, match["path"], "instmon-diskimg-<job>", best_effort=best_effort, direct_io=direct_io,
                    count_bytes=count,
                )
            return _diskimg_command_display(cmd), extent_note

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
            sidecar = _diskimg_read_sidecar(backup["path"])
            if sidecar or params.get("verify"):
                algo = sidecar["algo"] if sidecar else (params.get("verify_algo") if params.get("verify_algo") in _HASH_HEX_LEN else "sha256")
                cmd, _detached = _diskimg_hashed_stream_command(
                    "decrypt" if backup.get("encrypted") else "plain", backup["path"], match["path"],
                    "instmon-diskimg-<job>", os.path.join(_DISKIMG_RUN_DIR, "instmon-diskimg-<job>.hash"), algo,
                    rate_mb=throttle_rate_mb if not backup.get("encrypted") else None,
                )
                note = (f"The backup is checked against its saved {algo} checksum as it is read." if sidecar
                        else "This backup has no saved checksum, so it can't be checked for damage.")
                return _diskimg_command_display(cmd), note
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
    with _diskimg_job_lock:
        if _diskimg_job is None:
            return None
        job = dict(_diskimg_job)
        job.pop("proc", None)
        return job

def _diskimg_reader_thread(job_id):
    quiesced = False
    frozen = False
    with _diskimg_job_lock:
        if _diskimg_job is not None and _diskimg_job["id"] == job_id:
            quiesced = bool(_diskimg_job.get("quiesced"))
            frozen = bool(_diskimg_job.get("frozen"))
    try:
        _diskimg_reader_thread_body(job_id)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        log_event(f"Disk-image job {job_id} stopped on an internal error: {detail}", "err")
        with _diskimg_job_lock:
            if _diskimg_job is not None and _diskimg_job["id"] == job_id and _diskimg_job.get("state") == "running":
                _diskimg_job["state"] = "failed"
                _diskimg_job["finished"] = time.time()
                _diskimg_job["message"] = f"Stopped on an internal error ({detail}). Check the destination before using it."
                _diskimg_job["proc"] = None
        _diskimg_console_append(job_id, f"failed: internal error ({detail})")
    finally:
        with _diskimg_job_lock:
            if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                frozen = bool(_diskimg_job.get("frozen"))
        with _diskimg_job_lock:
            snap = dict(_diskimg_job) if (_diskimg_job is not None and _diskimg_job["id"] == job_id) else None
        if snap is not None and not snap.get("quiesced"):
            _diskimg_lastjob_write({"id": job_id, "kind": snap.get("kind"), "state": snap.get("state"),
                                    "message": snap.get("message"), "finished": snap.get("finished")})
        if quiesced:
            try:
                _diskimg_finish_quiesce(job_id, frozen)
            except Exception as exc:
                try:
                    log_event(f"Unquiesce after job {job_id} errored: {exc} -- "
                              "services may still be stopped; a reboot is recommended.", "err")
                except Exception:
                    pass

def _diskimg_finish_quiesce(job_id, frozen=False):
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
    with _diskimg_job_lock:
        snap = dict(_diskimg_job) if (_diskimg_job is not None and _diskimg_job["id"] == job_id) else None
    if snap is not None:
        _diskimg_lastjob_write({"id": job_id, "kind": snap.get("kind"), "state": snap.get("state"),
                                "message": snap.get("message"), "finished": snap.get("finished")})

_RPICLONE_DEST_ERR_RE = re.compile(
    rb"Bad message|Input/output error|Structure needs cleaning|Read-only file system")
_RPICLONE_DEST_ERR_SHOWN = 10
_RPICLONE_DEST_ERR_LIMIT = 20

def _diskimg_stop_running_copy(job_id):
    with _diskimg_job_lock:
        job = _diskimg_job
        if job is None or job["id"] != job_id:
            return
        proc, unit_name = job.get("proc"), job.get("unit_name")
    try:
        if unit_name:
            subprocess.run(["systemctl", "stop", f"{unit_name}.service"], capture_output=True, timeout=30)
        elif proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
    except Exception as exc:
        log_event(f"Disk-image job {job_id}: could not stop the copy: {exc}", "warn")

def _diskimg_reader_thread_body(job_id):
    with _diskimg_job_lock:
        job = _diskimg_job
        if job is None or job["id"] != job_id:
            return
        proc = job["proc"]
        progress_format = job.get("progress_format", "dd")
    buf = b""
    last_nonprogress_line = ""
    rpiclone_aborted = False
    dest_errors = 0
    dest_error_stop = False
    stream = proc.stdout
    read_some = getattr(stream, "read1", None) or (lambda n: stream.read(n))
    try:
        while True:
            chunk = read_some(4096)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts[-1]
            for piece in parts[:-1]:
                if progress_format == "ddrescue":
                    piece = _ANSI_ESCAPE_RE.sub(b"", piece)
                if not piece.strip():
                    continue
                if progress_format == "rpiclone":
                    parsed = None
                    if b"Aborting" in piece:
                        rpiclone_aborted = True
                    if _RPICLONE_DEST_ERR_RE.search(piece):
                        dest_errors += 1
                        if dest_errors == _RPICLONE_DEST_ERR_LIMIT and not dest_error_stop:
                            dest_error_stop = True
                            _diskimg_console_append(job_id, f"Stopping: {dest_errors} write errors on the destination.")
                            log_event(f"Disk-image job {job_id}: rpi-clone hit {dest_errors} write errors on the destination -- stopping it.", "err")
                            threading.Thread(target=_diskimg_stop_running_copy, args=(job_id,), daemon=True).start()
                        if dest_errors > _RPICLONE_DEST_ERR_SHOWN:
                            continue
                elif progress_format == "pv":
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
                    continue
                else:
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
        elif dest_error_stop:
            job["finished"] = time.time()
            job["state"] = "failed"
            job["message"] = (
                f"Stopped after {dest_errors} write errors on {job['dest']} (for example \"Bad message\" or "
                "\"Input/output error\"). The filesystem on that card is damaged, or the card is failing. Run the clone "
                "again with Force re-initialize ticked, which makes a fresh filesystem, or Full Format the card first. "
                "If it happens again on a freshly formatted card, replace the card."
            )
        elif progress_format == "rpiclone" and returncode == 0 and rpiclone_aborted:
            job["finished"] = time.time()
            job["state"] = "failed"
            job["message"] = "rpi-clone stopped without cloning (it printed \"Aborting!\") -- see the console above for why."
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
        hash_path = job.get("hash_path")
        hash_algo = job.get("hash_algo") or verify_algo
        expect_hash = job.get("expect_hash")
        expand_requested = bool(job.get("expand_requested"))
        new_ids_requested = bool(job.get("new_ids_requested"))

    stream_hash = _diskimg_read_hash_file(hash_path, hash_algo) if (hash_path and copy_ok) else None
    _diskimg_hash_cleanup(hash_path)

    root_frozen = False
    with _diskimg_job_lock:
        still_frozen = _diskimg_job is not None and _diskimg_job["id"] == job_id and bool(_diskimg_job.get("frozen"))
        if still_frozen:
            _diskimg_job["phase"] = "thawing"
    if still_frozen:
        _diskimg_console_append(job_id, "Copy finished -- thawing the root filesystem...")
        thaw_ok, thaw_message = _diskimg_freeze("unfreeze")
        _diskimg_console_append(job_id, thaw_message)
        with _diskimg_job_lock:
            if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                if thaw_ok:
                    _diskimg_job["frozen"] = False
                _diskimg_job["phase"] = "copying"
        if not thaw_ok:
            root_frozen = True
            log_event(f"Disk-image job {job_id}: {thaw_message} -- will retry when the job ends.", "err")

    if mapfile_path:
        try:
            os.remove(mapfile_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log_event(f"Disk-image {job_id}: could not remove ddrescue mapfile {mapfile_path}: {exc}", "warn")

    if progress_format == "rpiclone":
        _rpiclone_cleanup_mounts()

    if not copy_ok:
        if kind == "backup":
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

    final_state, final_message = "done", "Completed successfully."

    if kind == "restore" and expect_hash:
        if stream_hash is None:
            final_message += " Could not check the backup against its saved checksum."
            _diskimg_console_append(job_id, "Could not check the backup against its saved checksum.")
        elif stream_hash != expect_hash:
            final_state = "failed"
            final_message = ("The backup file doesn't match the checksum saved when it was made -- it is damaged, "
                             "so this restore can't be trusted. Don't use the destination drive.")
            _diskimg_console_append(job_id, final_message)
        else:
            final_message += f" The backup matched its saved {hash_algo} checksum."
            _diskimg_console_append(job_id, f"The backup matched its saved {hash_algo} checksum.")

    if final_state == "done" and verify_requested:
        with _diskimg_job_lock:
            if _diskimg_job is None or _diskimg_job["id"] != job_id:
                return
            _diskimg_job["phase"] = "verifying"
            _diskimg_job["verify_bytes_done"] = 0
        if stream_hash:
            log_event(f"Disk-image {kind} copy done -- reading {dest} back to verify ...", "info")
            _diskimg_console_append(job_id, f"Copy complete -- reading the destination back from the drive and comparing {hash_algo} checksums...")
            res, value = _diskimg_hash_readback(job_id, dest, bytes_total, hash_algo)
            if res == "ok" and value == stream_hash:
                result, verify_message = "ok", f"Verified -- the data read back from the drive matches what was copied ({hash_algo} {value[:12]}...)."
            elif res == "ok":
                result, verify_message = "mismatch", (
                    f"CHECKSUM MISMATCH -- the data read back from the drive differs from what was copied ({hash_algo}). "
                    "The drive may be failing or the copy is corrupt.")
            else:
                result, verify_message = res, value
        else:
            log_event(f"Disk-image {kind} copy done -- verifying {src} == {dest} ...", "info")
            _diskimg_console_append(job_id, f"Copy complete -- verifying (re-reading both sides and comparing {verify_algo} checksums)...")
            result, verify_message = _diskimg_verify_copy(job_id, src, dest, bytes_total, algo=verify_algo)
            if result == "mismatch" and kind in ("backup", "clone"):
                verify_message += (" The source is this Pi's live disk, which keeps changing unless Pause node services "
                                   "and Freeze filesystem were ticked, so this can be a false alarm with the resilient backend.")
        if result == "mismatch":
            final_state, final_message = "failed", verify_message
        elif result == "cancelled":
            final_state, final_message = "cancelled", verify_message
        elif result == "error":
            final_message = f"{final_message} Verification could not run: {verify_message}"
        else:
            final_message = f"{final_message} {verify_message}"
        _diskimg_console_append(job_id, verify_message)

    shrunk = False
    if final_state == "done" and kind == "backup" and shrink_requested:
        with _diskimg_job_lock:
            if _diskimg_job is None or _diskimg_job["id"] != job_id:
                return
            _diskimg_job["phase"] = "shrinking"
        log_event(f"Disk-image backup copy/verify done -- shrinking {dest} ...", "info")
        _diskimg_console_append(job_id, "Copy complete -- shrinking image to its minimum size...")
        shrink_ok, shrink_message, new_size = _diskimg_shrink_image(dest)
        shrunk = shrink_ok
        final_message += f" {shrink_message}" if shrink_ok else f" Shrink skipped: {shrink_message}"
        _diskimg_console_append(job_id, shrink_message)
        if shrink_ok:
            with _diskimg_job_lock:
                if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                    _diskimg_job["bytes_total"] = new_size
                    _diskimg_job["bytes_done"] = new_size

    if final_state == "done" and kind == "format":
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

    if final_state == "done" and root_frozen and (expand_requested or new_ids_requested):
        final_message += " Expand and New disk IDs were skipped because the root filesystem could not be thawed."
        expand_requested = new_ids_requested = False

    if final_state == "done" and kind in ("clone", "restore") and expand_requested:
        with _diskimg_job_lock:
            if _diskimg_job is None or _diskimg_job["id"] != job_id:
                return
            _diskimg_job["phase"] = "expanding"
        _diskimg_console_append(job_id, "Expanding the last partition to fill the drive...")
        try:
            exp_ok, exp_message = _diskimg_expand_to_fill(dest)
        except Exception as exc:
            exp_ok, exp_message = False, f"unexpected error: {exc}"
        _diskimg_console_append(job_id, exp_message if exp_ok else f"Not expanded: {exp_message}")
        final_message += f" {exp_message}" if exp_ok else f" Not expanded: {exp_message}."

    if final_state == "done" and kind in ("clone", "restore") and new_ids_requested:
        with _diskimg_job_lock:
            if _diskimg_job is None or _diskimg_job["id"] != job_id:
                return
            _diskimg_job["phase"] = "relabeling"
        _diskimg_console_append(job_id, "Giving the copy new disk IDs so it can't be confused with this Pi's own disk...")
        try:
            ids_ok, ids_message = _diskimg_new_disk_ids(dest)
        except Exception as exc:
            ids_ok, ids_message = False, f"unexpected error: {exc}"
        _diskimg_console_append(job_id, ids_message if ids_ok else f"New disk IDs: {ids_message}")
        final_message += f" {ids_message}" if ids_ok else (
            f" New disk IDs failed: {ids_message}. Don't leave the copy plugged in when this Pi reboots.")

    sidecar = None
    if final_state == "done" and kind == "backup":
        file_hash = stream_hash if (stream_hash and not shrunk) else None
        if file_hash is None:
            with _diskimg_job_lock:
                if _diskimg_job is None or _diskimg_job["id"] != job_id:
                    return
                _diskimg_job["phase"] = "checksumming"
                _diskimg_job["verify_bytes_done"] = 0
            _diskimg_console_append(job_id, f"Taking a {hash_algo} checksum of the finished backup...")
            try:
                file_size = os.path.getsize(dest)
            except OSError as exc:
                file_size = None
                res, value = "error", str(exc)
            if file_size is not None:
                with _diskimg_job_lock:
                    if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                        _diskimg_job["bytes_total"] = file_size
                res, value = _diskimg_hash_readback(job_id, dest, file_size, hash_algo)
            if res == "ok":
                file_hash = value
            elif res == "cancelled":
                final_state, final_message = "cancelled", "Cancelled while saving the checksum."
            else:
                final_message += f" No checksum was saved: {value}"
                _diskimg_console_append(job_id, f"No checksum was saved: {value}")
        if final_state == "done" and file_hash:
            try:
                image_size = os.path.getsize(dest)
            except OSError:
                image_size = None
            sidecar = {
                "format": "instmon-diskimg-backup", "version": 1,
                "image": os.path.basename(dest[:-len(_DISKIMG_PART_SUFFIX)] if dest.endswith(_DISKIMG_PART_SUFFIX) else dest),
                "size": image_size, "algo": hash_algo, "hash": file_hash,
                "source": src, "source_size": bytes_total if not shrunk else None,
                "host": socket.gethostname(), "created": datetime.now().isoformat(timespec="seconds"),
                "encrypted": dest.endswith(_DISKIMG_ENCRYPTED_SUFFIX + _DISKIMG_PART_SUFFIX) or dest.endswith(_DISKIMG_ENCRYPTED_SUFFIX),
                "shrunk": shrunk, "instmon": VERSION,
            }

    if kind == "backup" and dest.endswith(_DISKIMG_PART_SUFFIX):
        if final_state == "done":
            final_path = dest[:-len(_DISKIMG_PART_SUFFIX)]
            try:
                file_fd = os.open(dest, os.O_RDONLY)
                try:
                    os.fsync(file_fd)
                finally:
                    os.close(file_fd)
                os.replace(dest, final_path)
                dir_fd = os.open(os.path.dirname(final_path), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
                with _diskimg_job_lock:
                    if _diskimg_job is not None and _diskimg_job["id"] == job_id:
                        _diskimg_job["dest"] = final_path
                dest = final_path
                if sidecar:
                    side_err = _diskimg_write_sidecar(final_path, sidecar)
                    if side_err:
                        final_message += f" The checksum file could not be written: {side_err}"
                    else:
                        _diskimg_console_append(job_id, f"Saved {os.path.basename(final_path)}{_DISKIMG_SIDECAR_SUFFIX} ({sidecar['algo']} {sidecar['hash'][:12]}...).")
            except OSError as exc:
                final_state = "failed"
                final_message = f"The backup was written but could not be renamed from {os.path.basename(dest)}: {exc}"
        if final_state != "done":
            outcome = _diskimg_remove_partial_backup(dest)
            if outcome == "deleted":
                final_message += " The unfinished backup file was deleted."
            elif outcome:
                final_message += f" Could not delete the unfinished backup file ({outcome})."

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
        try:
            subprocess.run(["partprobe", dest], capture_output=True, timeout=15)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            log_event(f"partprobe {dest} failed (copy itself still succeeded): {exc}", "warn")

def _diskimg_start_job(*args, **kwargs):
    ok, result = _diskimg_start_job_inner(*args, **kwargs)
    if not ok:
        _diskimg_lastjob_write({"state": "not_started", "message": result})
    return ok, result

def _diskimg_start_job_inner(
    kind, source_desc, dest_desc, src_path, dst_path, bytes_total,
    shrink_requested=False, verify_requested=False,
    encrypt_passphrase=None, decrypt_passphrase=None,
    fs_type=None, quiesce_requested=False,
    best_effort_requested=False, direct_io_requested=False,
    verify_algo="sha256", backend="dd", throttle_rate_mb=None,
    freeze_requested=False, quick_requested=False, rpiclone_args=None,
    hash_algo=None, expect_hash=None, expand_requested=False,
    copy_bytes=None, new_ids_requested=False,
):
    global _diskimg_job

    quiesce_requested = bool(quiesce_requested) and kind in ("backup", "clone")
    quiesce_stopped_public = []
    quiesce_console = []
    frozen_ok = False

    backend = backend if (backend in ("dd", "ddrescue") and kind in ("backup", "clone")) or (backend == "rpiclone" and kind == "clone") else "dd"
    if backend == "rpiclone":
        verify_requested = False
        freeze_requested = False
    best_effort_requested = bool(best_effort_requested) and kind in ("backup", "clone") and backend == "dd"
    direct_io_requested = bool(direct_io_requested) and kind == "clone" and backend == "dd"
    freeze_requested = bool(freeze_requested) and quiesce_requested and kind in ("backup", "clone")
    quick_requested = bool(quick_requested) and kind == "format"
    verify_algo = verify_algo if verify_algo in _VERIFY_HASHERS else "sha256"
    throttle_requested = (
        bool(throttle_rate_mb) and kind in ("backup", "clone", "restore")
        and backend == "dd" and not (encrypt_passphrase or decrypt_passphrase)
    )
    progress_format = backend if backend in ("ddrescue", "rpiclone") else "dd"
    hash_algo = hash_algo if hash_algo in _HASH_HEX_LEN else verify_algo
    expand_requested = bool(expand_requested) and (kind == "restore" or (kind == "clone" and backend != "rpiclone"))
    new_ids_requested = bool(new_ids_requested) and (kind == "restore" or (kind == "clone" and backend != "rpiclone"))
    copy_bytes = int(copy_bytes) if (copy_bytes and kind in ("backup", "clone") and backend != "rpiclone") else None
    use_stream_hash = (
        (kind == "backup" and backend == "dd")
        or (kind == "clone" and backend == "dd" and bool(verify_requested))
        or (kind == "restore" and (bool(expect_hash) or bool(verify_requested)))
    )

    job_id = secrets.token_hex(8)
    unit_name = f"instmon-diskimg-{job_id}"
    _diskimg_lastjob_write({"id": job_id, "kind": kind, "state": "starting", "source": source_desc,
                            "dest": dest_desc, "bytes_total": bytes_total, "backend": backend,
                            "started": time.time()})
    hash_path = _diskimg_hash_path(job_id) if use_stream_hash else None

    if quiesce_requested:
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
                quiesce_console = list(_diskimg_job.get("console") or [])

        if freeze_requested:
            freeze_ok, freeze_message = _diskimg_freeze("freeze")
            _diskimg_console_append(job_id, freeze_message)
            if freeze_ok:
                frozen_ok = True
            else:
                log_event(f"Disk-image {kind}: fsfreeze -f / failed, continuing without it: {freeze_message}", "warn")
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
        elif hash_path:
            stream_mode = "encrypt" if encrypt_passphrase else ("decrypt" if decrypt_passphrase else "plain")
            cmd, detached = _diskimg_hashed_stream_command(
                stream_mode, src_path, dst_path, unit_name, hash_path, hash_algo,
                best_effort=best_effort_requested, direct_io=direct_io_requested,
                rate_mb=throttle_rate_mb if throttle_requested else None, count_bytes=copy_bytes,
            )
        elif encrypt_passphrase:
            cmd, detached = _diskimg_pipeline_command("encrypt", src_path, dst_path, best_effort=best_effort_requested), False
        elif decrypt_passphrase:
            cmd, detached = _diskimg_pipeline_command("decrypt", src_path, dst_path), False
        elif backend == "rpiclone":
            cmd, detached = _diskimg_rpiclone_command(dst_path, unit_name, rpiclone_args)
        elif backend == "ddrescue":
            mapfile_path = _diskimg_ddrescue_mapfile_path(job_id)
            cmd, detached = _diskimg_ddrescue_command(src_path, dst_path, mapfile_path, unit_name, count_bytes=copy_bytes)
        elif throttle_requested:
            cmd, detached = _diskimg_throttled_dd_command(
                src_path, dst_path, throttle_rate_mb, unit_name,
                best_effort=best_effort_requested, direct_io=direct_io_requested, count_bytes=copy_bytes,
            )
            log_event(f"Disk-image {kind}: bandwidth-throttled copy runs undetached (pv pipeline) -- "
                      "will NOT survive an instmon restart", "warn")
        else:
            cmd, detached = _diskimg_dd_command(
                src_path, dst_path, unit_name,
                best_effort=best_effort_requested, direct_io=direct_io_requested, count_bytes=copy_bytes,
            )
        cmd = _diskimg_low_priority(cmd, detached)
        if passphrase:
            env = dict(os.environ)
            env[_DISKIMG_PASS_ENV_VAR] = passphrase
        command_display = _diskimg_command_display(cmd)
        popen_error = None
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        except OSError as exc:
            popen_error = f"Could not start {cmd[0]}: {exc}"
            if quiesce_requested and _diskimg_job is not None and _diskimg_job["id"] == job_id:
                _diskimg_job = None
        finally:
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
                "quiesced": bool(quiesce_requested),
                "quiesce_stopped": quiesce_stopped_public,
                "quiesce_results": None,
                "quiesce_restore_ok": None,
                "frozen": frozen_ok,
                "backend": backend,
                "best_effort_requested": best_effort_requested,
                "direct_io_requested": direct_io_requested,
                "verify_algo": verify_algo if (bool(verify_requested) and kind != "format") else None,
                "throttle_rate_mb": throttle_rate_mb if throttle_requested else None,
                "progress_format": progress_format,
                "mapfile_path": mapfile_path,
                "hash_path": hash_path,
                "hash_algo": hash_algo,
                "expect_hash": expect_hash,
                "expand_requested": expand_requested,
                "new_ids_requested": new_ids_requested,
                "console": quiesce_console + [
                    f"[{datetime.now().strftime('%H:%M:%S')}] Starting {kind}: {source_desc} -> {dest_desc}",
                    f"[{datetime.now().strftime('%H:%M:%S')}] $ {command_display}",
                ],
            }

    if popen_error is not None:
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
    with _diskimg_job_lock:
        job = _diskimg_job
        if job is None or job.get("state") != "running":
            return False, "No disk-image job is currently running."
        if job.get("cancelled"):
            return True, "Stop already requested -- waiting for the job to wind down."
        if job.get("phase") == "quiescing":
            return False, "Node services are still being stopped -- this finishes shortly. Cancel once the copy has started."
        if job.get("phase") == "unquiescing":
            return False, "The job has finished and services are being restarted -- this finishes on its own shortly."
        if job.get("phase") == "thawing":
            return False, "The job has finished and the filesystem is being thawed -- this finishes on its own shortly."
        if job.get("phase") == "shrinking":
            return False, "The backup copy is already complete and is now being shrunk -- this finishes on its own shortly and can't be cancelled mid-step."
        if job.get("phase") == "formatting":
            return False, "The drive has been wiped and is now being partitioned and formatted -- this finishes on its own shortly and cannot be stopped mid-step."
        if job.get("phase") == "expanding":
            return False, "The copy is complete and the drive is being expanded -- this finishes on its own shortly and can't be stopped mid-step."
        if job.get("phase") == "relabeling":
            return False, "The copy is complete and is getting new disk IDs -- this finishes on its own shortly and can't be stopped mid-step."
        job["cancelled"] = True
        proc, unit_name, phase = job["proc"], job["unit_name"], job.get("phase")
        cancel_kind = job.get("kind")
    if phase == "verifying":
        return True, "Cancel requested -- verification will stop shortly. The copy on disk is unaffected."
    if phase == "checksumming":
        return True, "Cancel requested -- the backup will be discarded."
    try:
        if unit_name:
            subprocess.run(["systemctl", "stop", f"{unit_name}.service"], capture_output=True, timeout=10)
        elif proc is not None:
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
    try:
        if os.path.basename(os.path.dirname(path)) != _DISKIMG_BACKUP_DIRNAME:
            return ""
        if not (path.endswith(".img") or path.endswith(".img.enc")
                or path.endswith(".img" + _DISKIMG_PART_SUFFIX) or path.endswith(".img.enc" + _DISKIMG_PART_SUFFIX)):
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
                "checksum": os.path.isfile(full + _DISKIMG_SIDECAR_SUFFIX),
            })
    results.sort(key=lambda e: e["mtime"], reverse=True)
    return results

_VERIFY_CHUNK_SIZE = 4 * 1024 * 1024
_VERIFY_HASHERS = {"sha256": hashlib.sha256, "blake2b": hashlib.blake2b}

def _diskimg_verify_copy(job_id, src_path, dst_path, expected_bytes, algo="sha256"):
    hasher_factory = _VERIFY_HASHERS.get(algo, hashlib.sha256)
    try:
        src_hash = hasher_factory()
        dst_hash = hasher_factory()
        remaining = expected_bytes
        with open(src_path, "rb") as sf, open(dst_path, "rb") as df:
            _diskimg_drop_cache(df)
            while remaining > 0:
                with _diskimg_job_lock:
                    if _diskimg_job is None or _diskimg_job["id"] != job_id:
                        return "cancelled", "Job no longer active."
                    if _diskimg_job.get("cancelled"):
                        return "cancelled", "Verification cancelled -- the copy on disk is unaffected."
                chunk_size = min(_VERIFY_CHUNK_SIZE, remaining)
                s_chunk = sf.read(chunk_size)
                d_chunk = df.read(chunk_size)
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

_SHRINK_REQUIRED_TOOLS = ("losetup", "partprobe", "blkid", "e2fsck", "resize2fs", "dumpe2fs", "parted")

def _diskimg_shrink_image(image_path):
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

        fstype = subprocess.run(
            ["blkid", "-o", "value", "-s", "TYPE", part_path],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if fstype not in ("ext2", "ext3", "ext4"):
            return False, f"last partition is '{fstype or 'unknown'}', not ext2/3/4 (only that family is resizable here)", None

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
        new_fs_bytes -= new_fs_bytes % sector_size
        size_sectors = new_fs_bytes // sector_size
        end_sector = start_sector + size_sectors - 1

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

    try:
        with open(image_path, "r+b") as f:
            f.truncate(new_image_size)
    except OSError as exc:
        return False, f"resize succeeded but truncating the file failed: {exc}", None

    return True, f"Shrunk to {fmt_bytes(new_image_size)}.", new_image_size

_DISKIMG_FORMAT_FS_TOOLS = {
    "ext4": "mkfs.ext4",
    "fat32": "mkfs.vfat",
    "exfat": "mkfs.exfat",
}

def _diskimg_partition_and_format(dest, fs_type, quick=False):
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

_DISKIMG_SCHEDULE_PATH = os.path.join(CONFIG_DIR, "instmon_diskimg_schedule.json")
_DISKIMG_SCHED_SUFFIX = ".sched.img"
_diskimg_schedule_lock = threading.Lock()

_DISKIMG_SCHEDULE_DEFAULTS = {
    "enabled": False,
    "interval_hours": 24,
    "dest_device": "",
    "retention": 5,
    "shrink": False,
    "verify": False,
    "quiesce": False,
    "label": "auto",
    "last_run_at": None,
    "last_run_status": None,
    "last_run_message": None,
    "last_skip_at": None,
    "last_skip_message": None,
    "last_quiesce_restore_ok": None,
    "dest_uuid": None,
}

def _diskimg_schedule_load():
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
    try:
        retention = max(1, int(retention))
    except (TypeError, ValueError):
        retention = 5
    on_drive = sorted(
        (b for b in _diskimg_list_backups()
         if b["drive"] == dest_drive_path and b["name"].endswith(_DISKIMG_SCHED_SUFFIX)),
        key=lambda b: b["mtime"], reverse=True,
    )
    for stale in on_drive[retention:]:
        try:
            os.remove(stale["path"])
            _diskimg_remove_sidecar(stale["path"])
            log_event(f"Scheduled backup retention: deleted old backup {stale['name']}", "info")
        except OSError as exc:
            log_event(f"Scheduled backup retention: could not delete {stale['name']}: {exc}", "warn")

def _diskimg_schedule_watch_job(job_id, dest_drive_path):
    restore_ok = None
    while True:
        with _diskimg_job_lock:
            job = _diskimg_job
            if job is None or job["id"] != job_id:
                return
            state, message = job["state"], job["message"]
            phase, quiesced = job.get("phase"), job.get("quiesced")
            restore_ok = job.get("quiesce_restore_ok")
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

DISKIMG_BOOT_GRACE = 900

def _diskimg_uptime() -> float:
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return float(DISKIMG_BOOT_GRACE)

def _diskimg_schedule_tick():
    cfg = _diskimg_schedule_load()
    if not cfg.get("enabled"):
        return
    try:
        interval_sec = max(0.1, float(cfg.get("interval_hours") or 24)) * 3600
    except (TypeError, ValueError):
        interval_sec = 24 * 3600
    last_run_at = cfg.get("last_run_at")
    if last_run_at is not None and (time.time() - last_run_at) < interval_sec:
        return

    def skip(reason):
        if cfg.get("last_skip_message") != reason:
            log_event(f"Scheduled backup not started: {reason}", "warn")
        cfg["last_skip_at"] = time.time()
        cfg["last_skip_message"] = reason
        _diskimg_schedule_save(cfg)

    up = _diskimg_uptime()
    if up < DISKIMG_BOOT_GRACE:
        skip(f"the node booted {int(up // 60)} min ago; scheduled backups wait {DISKIMG_BOOT_GRACE // 60} min after boot "
             "so the network, the tunnel and the radio services can start first")
        return

    with _diskimg_job_lock:
        job_running = _diskimg_job is not None and _diskimg_job.get("state") == "running"
    if job_running:
        skip("A disk-image job (manual or scheduled) is already running.")
        return
    if full_update_running():
        skip("Full Update is running.")
        return
    with _running_installs_lock:
        installing = sorted(_running_installs)
    if installing:
        skip(f"An install is running ({', '.join(installing)}).")
        return

    boot_disk = _get_boot_disk()
    if not boot_disk:
        skip("Could not determine this Pi's boot disk.")
        return
    src_path = f"/dev/{boot_disk}"

    dest_device = cfg.get("dest_device")
    dest_uuid = cfg.get("dest_uuid")
    if not dest_device and not dest_uuid:
        skip("No destination drive configured.")
        return
    drives = _list_usb_drives()
    if dest_uuid:
        match = next((d for d in drives if dest_uuid in (d.get("fs_uuids") or [])), None)
        if match is None:
            skip(f"The backup drive (filesystem {dest_uuid}, last seen as {dest_device or '?'}) is not currently attached.")
            return
        if match["path"] != dest_device:
            cfg["dest_device"] = match["path"]
            dest_device = match["path"]
    else:
        match = next((d for d in drives if d["path"] == dest_device or d["name"] == dest_device), None)
        if match is None:
            skip(f"Configured destination drive '{dest_device}' is not currently attached.")
            return
        if match.get("fs_uuids"):
            cfg["dest_uuid"] = match["fs_uuids"][0]
            log_event(f"Scheduled backup: remembering the backup drive by its filesystem UUID ({cfg['dest_uuid']}).", "info")
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
    copy_size, _extent_note = _diskimg_copy_extent(src_path, src_size)
    if match["size"] < copy_size:
        skip(f"Configured destination drive '{dest_device}' is smaller than the boot disk's partitions.")
        return

    mountpoint, _we_mounted = _diskimg_ensure_mounted(match["name"])
    if mountpoint is None:
        skip(f"Could not find or mount a writable filesystem on {match['path']}.")
        return
    _diskimg_clear_stale_parts(os.path.join(mountpoint, _DISKIMG_BACKUP_DIRNAME))
    try:
        free = shutil.disk_usage(mountpoint).free
    except OSError as exc:
        skip(f"Could not check free space on {mountpoint}: {exc}")
        return
    if free < copy_size:
        skip(f"Not enough free space on {match['path']} ({fmt_bytes(free)} free, need {fmt_bytes(copy_size)}).")
        return
    fat_reason = _diskimg_fat_limit_reason(mountpoint, copy_size, match["path"])
    if fat_reason:
        skip(fat_reason)
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
    fname = f"{hostname}_{stamp}" + (f"_{label}" if label else "") + _DISKIMG_SCHED_SUFFIX
    dest_path = os.path.join(backup_dir, fname)

    quiesce = bool(cfg.get("quiesce"))
    if quiesce:
        locks_ok, lock_reason = _quiesce_check_package_locks()
        if not locks_ok:
            skip(lock_reason)
            return

    subprocess.run(["sync"], capture_output=True, timeout=30)
    part_path = dest_path + _DISKIMG_PART_SUFFIX
    ok, result = _diskimg_start_job(
        "backup", src_path, part_path, src_path, part_path, copy_size,
        copy_bytes=copy_size if copy_size < src_size else None,
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
"nodelisten":os .path .join (LIBRARY_DIR ,"nodelisten"),
"watchdog":os .path .join (LIBRARY_DIR ,"watchdog"),
"instmon":os .path .join (LIBRARY_DIR ,"instmon"),
"scripts":os .path .join (LIBRARY_DIR ,"scripts"),
"config":os .path .join (LIBRARY_DIR ,"config"),
"confgetter":os .path .join (LIBRARY_DIR ,"confgetter"),
"confputter":os .path .join (LIBRARY_DIR ,"confputter"),
}

ALLOWED_EXT ={
"dashboard":(".py",),
"sysmon":(".py",),
"wifimon":(".py",),
"44helper":(".py",),
"nodelisten":(".py",),
"watchdog":(".sh",),
"instmon":(".py",),
"scripts":(".sh",),
"config":(".conf",),
"confgetter":(".sh",),
"confputter":(".py",),
}

COMPONENTS =[
{
"name":"Dashboard",
"service":"nodecontrol",
"legacy_services":("asl_dvs_dashboard",),
"port":8989 ,

"install_link":"/usr/local/bin/nodecontrol.py",
"legacy_links":("/usr/local/bin/asl_dvs_dashboard.py",),
"unit_paths":{"nodecontrol":("/usr/local/bin/nodecontrol.py","/usr/local/lib/asl_dvs/nodecontrol")},
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
"install_link":"/usr/local/bin/44helper.py",
"legacy_links":("/opt/44helper/asl_dvs_m17_44helper.py",),
"category":"44helper",
},
{
"name":"Node Talker",
"service":"nodetalker",
"legacy_services":("nodelisten",),
"port":8993 ,
"install_link":"/usr/local/bin/nodetalker.py",
"legacy_links":("/usr/local/bin/nodelisten.py",),
"unit_paths":{"nodetalker":("/usr/local/bin/nodetalker.py","/usr/local/lib/asl_dvs/nodetalker")},
"category":"nodelisten",
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

NO_CARD_CATEGORIES =("watchdog",)

HOME_SCAN_PATTERN_MAP =[
("watchdog",["asl_dvs_watchdog*.sh"]),
("dashboard",["nodecontrol*.py","asl_dvs_dashboard*.py"]),
("sysmon",["sysmon*.py","asl_dvs_sysmon*.py","asl_dvs_m17_sysmon*.py","sysmon_svx*.py"]),
("wifimon",["wifimon*.py"]),
("44helper",["44helper*.py","asl_dvs_m17_44helper*.py"]),
("nodelisten",["nodetalker*.py","nodelisten*.py"]),
("instmon",["instmon*.py"]),
("config",["asl_dvs*.conf","sysmon*.conf","wifimon*.conf","nodetalker*.conf","nodelisten*.conf"]),
("scripts",["install_all*.sh","uninstall_all*.sh","install_asl_dvs*.sh","uninstall_asl_dvs*.sh","wifi_menu*.sh","wifi-menu*.sh","asl_dvs*.sh"]),
("confgetter",["confgetter*.sh"]),
("confputter",["confputter*.py"]),
]

_NAME_GLOB_ALIASES ={
"asl_dvs_dashboard*.py":"nodecontrol*.py",
"asl_dvs_m17_44helper*.py":"44helper*.py",
"install_asl_dvs*.sh":"install_all*.sh",
"uninstall_asl_dvs*.sh":"uninstall_all*.sh",
"nodelisten*.py":"nodetalker*.py",
}

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


LOCKS_PATH = os.path.join(CONFIG_DIR, "instmon_locks.json")
_locks_mutex = threading.Lock()

def _locks_read():
    try:
        with open(LOCKS_PATH) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for cat, names in data.items():
        if cat in LIB_SUBDIRS and isinstance(names, list):
            out[cat] = {n for n in names if isinstance(n, str)}
    return out

def lib_locked(category, name):
    return bool(category) and bool(name) and os.path.basename(name) in _locks_read().get(category, set())

def lib_locked_path(path):
    d, n = os.path.split(os.path.realpath(path))
    for cat, cdir in LIB_SUBDIRS.items():
        if os.path.realpath(cdir) == d:
            return lib_locked(cat, n)
    return False

def lib_lock_set(category, name, locked, confirm=False):
    if category not in LIB_SUBDIRS:
        return 400, {"error": f"Unknown category '{category}'"}
    target = safe_join(LIB_SUBDIRS[category], name or "")
    if target is None or not os.path.isfile(target):
        return 404, {"error": f"Library file not found: {name}"}
    name = os.path.basename(target)
    if not locked and not confirm:
        return 400, {"error": f"Unlocking {name} needs confirmation."}
    with _locks_mutex:
        locks = _locks_read()
        names = locks.setdefault(category, set())
        if locked:
            names.add(name)
        else:
            names.discard(name)
        ensure_dirs()
        payload = {c: sorted(v) for c, v in sorted(locks.items()) if v}
        compare_before_write(LOCKS_PATH, json.dumps(payload, indent=2).encode("utf-8"))
    if locked:
        log_event(f"Locked {name} in the {category} library: it can't be deleted or overwritten", "ok")
        return 200, {"message": f"{name} is locked: it can't be deleted or overwritten until you unlock it.", "level": "ok"}
    log_event(f"Unlocked {name} in the {category} library", "warn")
    return 200, {"message": f"{name} is unlocked: it can be deleted or overwritten again.", "level": "warn"}

def _locked_msg(name):
    return f"{name} is locked in the library -- uncheck Lock on its row first (it asks to confirm)."

def _stage_library_file(category, filename, filedata, force=False, source="upload"):
    if category not in LIB_SUBDIRS:
        return 400, {"error": f"Unknown category '{category}'"}
    if not filename or filedata is None:
        return 400, {"error": "No file provided"}
    filename = os.path.basename(filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT[category]:
        return 400, {"error": f"'{ext}' not allowed for category '{category}' (expected {ALLOWED_EXT[category]})"}

    expected_patterns = dict(HOME_SCAN_PATTERN_MAP).get(category, [])
    name_matches = any(fnmatch.fnmatch(filename.lower(), g.lower()) for g in expected_patterns)
    if expected_patterns and not name_matches and not force:
        return 400, {
            "error": f"'{filename}' doesn't look like a {category} file -- expected a name matching {' / '.join(expected_patterns)}.",
            "mismatch": True,
            "expected": expected_patterns,
        }
    if expected_patterns and not name_matches and force:
        log_event(f"{'Imported' if source == 'usb' else 'Uploaded'} {filename} to {category} library despite naming mismatch (forced)", "warn")

    ensure_dirs()
    dest = safe_join(LIB_SUBDIRS[category], filename)
    if dest is None:
        return 400, {"error": "Invalid filename"}
    if os.path.isfile(dest) and lib_locked(category, filename) and file_sha256(dest) != hashlib.sha256(filedata).hexdigest():
        log_event(f"Refused to overwrite locked {filename} in the {category} library", "warn")
        return 409, {"error": _locked_msg(filename)}
    wrote, reason = compare_before_write(dest, filedata)
    verb = "Imported from USB:" if source == "usb" else "Uploaded"
    log_event(f"{verb} {filename} to {category} library ({reason})", "ok")
    message = f"Staged {filename} in the {category} library." if wrote else f"{filename} already staged (unchanged)."
    return 200, {"name": filename, "wrote": wrote, "reason": reason, "message": message, "level": "ok" if wrote else "info"}

_USBIMPORT_MOUNT_ROOT = "/mnt/instmon-usbimport"
_USBIMPORT_MAX_ENTRIES = 500
_USBIMPORT_EXTS = tuple(sorted({e for _exts in ALLOWED_EXT.values() for e in _exts} | {".pdf"}))
_USBIMPORT_SKIP_NAMES = ("system volume information", "lost+found", "$recycle.bin")
_USBIMPORT_PLAIN_FS = ("vfat", "exfat", "ext2", "ext3", "ext4")
_usbimport_lock = threading.Lock()

def _usbimport_valid_drive(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        return None
    for d in _list_usb_drives():
        if d["name"] == name and not d["is_boot_disk"]:
            return d
    return None

def _kernel_has_fs(fstype):
    try:
        with open("/proc/filesystems", "r") as f:
            return any(line.split()[-1:] == [fstype] for line in f if line.strip())
    except OSError:
        return False

def _usbimport_ntfs_type():
    if _kernel_has_fs("ntfs3"):
        return "ntfs3"
    if shutil.which("mount.ntfs-3g") or os.path.exists("/sbin/mount.ntfs-3g"):
        return "ntfs-3g"
    return None

def _usbimport_mount(name):
    data = _lsblk_json()
    if data is None:
        return None, False, "lsblk query failed"
    node = next((n for n in data.get("blockdevices") or [] if n.get("name") == name), None)
    if node is None:
        return None, False, "Drive not found"
    cand = _find_mount_or_mountable_partition(node)
    if cand is None:
        return None, False, "No mountable filesystem found on this drive"
    dev_path, existing_mp, fstype = cand
    if existing_mp:
        return existing_mp, False, None
    fstype = (fstype or "").lower()
    if fstype in ("ntfs", "ntfs3"):
        mtype = _usbimport_ntfs_type()
        if mtype is None:
            return None, False, "NTFS driver not installed (apt install ntfs-3g)"
    elif fstype in _USBIMPORT_PLAIN_FS:
        mtype = fstype
    else:
        return None, False, f"Unsupported filesystem '{fstype}'"
    opts = "ro,nosuid,nodev,noexec" + (",noload" if mtype in ("ext3", "ext4") else "")
    mountpoint = os.path.join(_USBIMPORT_MOUNT_ROOT, name)
    try:
        os.makedirs(mountpoint, exist_ok=True)
        res = subprocess.run(
            ["mount", "-t", mtype, "-o", opts, dev_path, mountpoint],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_event(f"USB import: mount of {dev_path} failed: {exc}", "err")
        return None, False, "Mount failed"
    if res.returncode != 0:
        detail = (res.stderr or "").strip().replace("\n", " ")[:200]
        log_event(f"USB import: mount of {dev_path} ({mtype}) failed: {detail}", "err")
        return None, False, f"Mount failed: {detail}" if detail else "Mount failed"
    return mountpoint, True, None

def _usbimport_umount(mountpoint):
    try:
        subprocess.run(["umount", mountpoint], capture_output=True, timeout=20, check=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log_event(f"USB import: umount of {mountpoint} failed: {exc}", "warn")
        return
    try:
        os.rmdir(mountpoint)
    except OSError:
        pass

def _usbimport_resolve(mountpoint, rel):
    rel = (rel or "").replace("\\", "/")
    if "\x00" in rel:
        return None
    parts = [p for p in rel.split("/") if p]
    if any(p in (".", "..") for p in parts):
        return None
    base = os.path.realpath(mountpoint)
    full = os.path.realpath(os.path.join(base, *parts))
    if full != base and not full.startswith(base + os.sep):
        return None
    return full

def _usbimport_run(name, fn):
    drive = _usbimport_valid_drive(name)
    if drive is None:
        return 404, {"error": "Drive not found or not eligible"}
    job = _diskimg_job_snapshot()
    if job is not None and not job.get("finished"):
        return 409, {"error": "A disk-image job is running -- wait for it to finish.", "level": "warn"}
    with _usbimport_lock:
        mountpoint, mounted, err = _usbimport_mount(name)
        if mountpoint is None:
            return 400, {"error": err or "Mount failed"}
        try:
            return fn(mountpoint)
        finally:
            if mounted:
                _usbimport_umount(mountpoint)

def _usbimport_browse(mountpoint, rel):
    full = _usbimport_resolve(mountpoint, rel)
    if full is None or not os.path.isdir(full):
        return 400, {"error": "Invalid path"}
    dirs, files, truncated = [], [], False
    try:
        with os.scandir(full) as it:
            for e in it:
                lname = e.name.lower()
                if e.name.startswith((".", "$")) or lname in _USBIMPORT_SKIP_NAMES:
                    continue
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        dirs.append(e.name)
                    elif e.is_file(follow_symlinks=False) and os.path.splitext(lname)[1] in _USBIMPORT_EXTS:
                        st = e.stat(follow_symlinks=False)
                        files.append({"name": e.name, "size": st.st_size, "mtime": int(st.st_mtime)})
                except OSError:
                    continue
                if len(dirs) + len(files) >= _USBIMPORT_MAX_ENTRIES:
                    truncated = True
                    break
    except OSError as exc:
        return 500, {"error": f"Could not read directory: {exc}"}
    dirs.sort(key=str.lower)
    files.sort(key=lambda f: f["name"].lower())
    base = os.path.realpath(mountpoint)
    relpath = "" if full == base else os.path.relpath(full, base).replace(os.sep, "/")
    return 200, {"path": relpath, "dirs": dirs, "files": files, "truncated": truncated}

def _usbimport_import(mountpoint, rel, category, force):
    full = _usbimport_resolve(mountpoint, rel)
    if full is None:
        return 400, {"error": "Invalid path"}
    is_pdf = os.path.splitext(full)[1].lower() == ".pdf"
    max_bytes = DOCS_MAX_BYTES if is_pdf else MAX_UPLOAD_BYTES
    fd = None
    try:
        fd = os.open(full, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return 400, {"error": "Not a regular file"}
        if is_pdf:
            limit_msg = f"File too large (limit {DOCS_MAX_BYTES // (1024 * 1024)}MB for a manual)"
        else:
            limit_msg = f"File too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)}MB -- set INSTMON_MAX_UPLOAD_MB to change)"
        if st.st_size > max_bytes:
            return 400, {"error": limit_msg}
        with os.fdopen(fd, "rb") as f:
            fd = None
            data = f.read(max_bytes + 1)
        if len(data) > max_bytes:
            return 400, {"error": limit_msg}
    except OSError as exc:
        return 404, {"error": f"Could not read file: {exc.strerror or exc}"}
    finally:
        if fd is not None:
            os.close(fd)
    if is_pdf:
        return docs_stage(os.path.basename(full), data)
    return _stage_library_file(category, os.path.basename(full), data, force, "usb")

def systemctl_is_active (service ):
    try :
        result =subprocess .run (
        ["systemctl","is-active",service ],
        capture_output =True ,text =True ,timeout =3 ,
        )
        return result .stdout .strip ()or "unknown"
    except (FileNotFoundError ,subprocess .TimeoutExpired ):
        return "unknown"

_QUIESCE_TIER0_GLOB = "asl_dvs_watchdog*.timer"

_QUIESCE_NEVER_STOP_CATEGORIES = ("instmon", "watchdog", "sysmon")

_QUIESCE_TIER2_EXTRA = [("SVXLink", "svxlink.service")]

_QUIESCE_STATE_PATH = os.path.join(CONFIG_DIR, "instmon_quiesce_state.json")
QUIESCE_STOP_TIMEOUT_SEC = int(os.environ.get("INSTMON_QUIESCE_STOP_TIMEOUT_SEC", "15"))

_QUIESCE_STOP_RECHECK_TRIES = 3
_QUIESCE_STOP_RECHECK_DELAY = 2.0

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

QUIET_JOB_ID = "quiet-system"
_QUIET_KEEP_CATEGORIES = ("instmon", "watchdog", "wifimon")

def _quiesce_list_timer_units(glob_pattern=_QUIESCE_TIER0_GLOB):
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
    resolved = []

    for unit in _quiesce_list_timer_units():
        resolved.append((0, unit.rsplit(".", 1)[0], unit))

    keep = _QUIET_KEEP_CATEGORIES if scope == "quiet" else _QUIESCE_NEVER_STOP_CATEGORIES
    for comp in COMPONENTS:
        if comp["category"] in keep:
            continue
        unit = unit_of(comp)
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
        if pid.isdigit() and os.path.isdir(f"/proc/{pid}"):
            return False, "unattended-upgrades is currently running. Try again once it finishes."
    except (OSError, ValueError):
        pass

    for unit in _QUIESCE_APT_UNITS:
        if systemctl_is_active(unit) == "active":
            return False, f"{unit} is currently running. Try again once it finishes."

    return True, ""

def _quiesce_active_connections():
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
    return os.path.exists(_QUIESCE_STATE_PATH)

def _quiesce_stop_one(unit):
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
    def _console(text):
        if console_job_id:
            _diskimg_console_append(console_job_id, text)

    with _quiesce_lock:
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
    except Exception as exc:
        try:
            log_event(f"Unquiesce: unexpected error: {exc}", "err")
        except Exception:
            pass
        return False, []

def _quiesce_format_results(results):
    if not results:
        return ""
    failed = [f"{l}" for l, _u, ok, _s in results if not ok]
    if not failed:
        return f"All {len(results)} service(s) restarted."
    return (f"{len(results) - len(failed)} of {len(results)} service(s) restarted -- "
            f"still down: {', '.join(failed)}. Reboot recommended.")

_WATCHDOG_LOCK_TIMEOUT = 15.0

def _sd_notify(message):
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.connect(addr)
            sock.sendall(message.encode("utf-8"))
        return True
    except (OSError, ValueError):
        return False

def _instmon_responsive():
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
    unit = f"instmon-diskimg-{job_id}.service"
    try:
        r = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, text=True, timeout=5)
        if (r.stdout or "").strip() != "active":
            return False
    except Exception:
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
        log_event(f"Quiet System was on when instmon restarted{age} -- restoring "
                  f"{len(stopped)} service(s) now.", "warn")
    else:
        log_event(
            f"STARTUP RECOVERY: a previous instmon process left {len(stopped)} service(s) "
            f"stopped for disk-image job {state.get('job_id')}{age} -- restarting them now.",
            "err",
        )

    if state.get("job_id") and state.get("job_id") != QUIET_JOB_ID:
        try:
            _quiesce_stop_orphaned_job(state["job_id"])
        except Exception as exc:
            log_event(f"STARTUP RECOVERY: orphan check failed: {exc}", "err")

    pending = _quiesce_startup_queue(state.get("job_id"), stopped, state.get("started_at"))
    if pending:
        threading.Thread(target=_quiesce_startup_watch, args=(pending,),
                         name="quiesce-recover", daemon=True).start()

QUIESCE_RECOVER_WAIT_SEC = int(os.environ.get("INSTMON_QUIESCE_RECOVER_WAIT_SEC", "300"))
QUIESCE_RECOVER_POLL_SEC = 10

def _systemd_queued_jobs():
    try:
        r = subprocess.run(["systemctl", "list-jobs", "--no-legend", "--plain"],
                           capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return set()
    units = set()
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            units.add(parts[1])
    return units

def _quiesce_unit_names(unit):
    return {unit} if "." in unit else {unit, unit + ".service"}

def _quiesce_startup_queue(job_id, stopped, started_at=None):
    with _quiesce_lock:
        queued = _systemd_queued_jobs()
        pending, failed = [], []
        for tier, label, unit in list(reversed(stopped)):
            if systemctl_is_active(unit) == "active":
                log_event(f"STARTUP RECOVERY: {label} ({unit}) is already running", "info")
                continue
            if queued & _quiesce_unit_names(unit):
                log_event(f"STARTUP RECOVERY: {label} ({unit}) already has a start job queued -- "
                          "leaving it to systemd", "info")
                pending.append((tier, label, unit))
                continue
            try:
                r = subprocess.run(["systemctl", "start", "--no-block", unit],
                                   capture_output=True, text=True, timeout=15)
                start_ok = r.returncode == 0
                detail = ((r.stderr or "").strip().splitlines() or [""])[0]
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
                start_ok, detail = False, f"error: {exc}"
            if start_ok:
                log_event(f"STARTUP RECOVERY: start queued for {label} ({unit})", "info")
                pending.append((tier, label, unit))
            else:
                log_event(f"STARTUP RECOVERY: {label} ({unit}) could not be started: "
                          f"{detail or 'systemctl start failed'}", "err")
                failed.append((tier, label, unit))
        if failed:
            _quiesce_state_write(job_id, list(reversed(failed)), started_at=started_at)
        else:
            _quiesce_state_clear()
    if failed:
        log_event(
            "STARTUP RECOVERY INCOMPLETE -- these services did NOT come back: "
            + ", ".join(f"{l} ({u})" for _t, l, u in failed)
            + ". The node may be off the air. A reboot is recommended.",
            "err",
        )
    if not pending:
        if not failed:
            log_event("STARTUP RECOVERY: all services are running. Node is back on the air.", "ok")
        return []
    log_event(f"STARTUP RECOVERY: waiting up to {QUIESCE_RECOVER_WAIT_SEC // 60} min for "
              f"{len(pending)} service(s) to start (at boot some wait for the network).", "info")
    return pending

def _quiesce_startup_watch(pending):
    end = time.monotonic() + QUIESCE_RECOVER_WAIT_SEC
    while True:
        states = {unit: systemctl_is_active(unit) for _t, _l, unit in pending}
        if all(st == "active" for st in states.values()) or time.monotonic() >= end:
            break
        time.sleep(QUIESCE_RECOVER_POLL_SEC)
    queued = _systemd_queued_jobs()
    results = []
    for _t, label, unit in pending:
        st = states.get(unit, "unknown")
        ok = st in ("active", "activating", "reloading")
        if not ok and queued & _quiesce_unit_names(unit):
            st += ", start job still queued"
        results.append((label, unit, ok, st))
        if not ok:
            log_event(f"STARTUP RECOVERY: {label} ({unit}) is not running (now {st})", "err")
    if all(ok for _l, _u, ok, _s in results):
        log_event(f"STARTUP RECOVERY: {_quiesce_format_results(results)} Node is back on the air.", "ok")
        return
    failed = [f"{l} ({u})" for l, u, k, _s in results if not k]
    log_event(
        f"STARTUP RECOVERY INCOMPLETE -- these services did NOT come back within "
        f"{QUIESCE_RECOVER_WAIT_SEC // 60} min: " + ", ".join(failed)
        + ". The node may be off the air. A reboot is recommended.",
        "err",
    )

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
    subprocess .run (["systemctl","restart",unit_of (comp )],capture_output =True ,text =True ,timeout =10 )
    time .sleep (1.5 )
    state =systemctl_is_active (unit_of (comp ))
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
    ["systemctl","restart",unit_of (comp )],
    capture_output =True ,text =True ,timeout =10 ,
    )
    result ["restarted"]=True 
    if restart .returncode !=0 :
        err_tail =(restart .stderr or restart .stdout or "unknown error").strip ()[:200 ]
        log_event (f"systemctl restart {unit_of (comp )} failed: {err_tail }","err")
        result ["message"]=f"{unit_of (comp )} failed to restart: {err_tail }.{rollback_suffix ()}"
        result ["level"]="err"
        return result 

    time .sleep (1.5 )
    state =systemctl_is_active (unit_of (comp ))
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

def _cli_env ():
    env =os .environ .copy ()
    env ["PYTHONUNBUFFERED"]="1"
    return env

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

def unit_of(comp):
    names = [comp["service"]] + list(comp.get("legacy_services", ()))
    if len(names) > 1:
        for n in names:
            if os.path.exists(os.path.join(_SYSTEMD_UNIT_DIR, n + ".service")):
                return n
    return comp["service"]

def installed_link(comp):
    paths = [comp["install_link"]] + list(comp.get("legacy_links", ()))
    if len(paths) > 1:
        unit = os.path.join(_SYSTEMD_UNIT_DIR, unit_of(comp) + ".service")
        try:
            with open(unit, errors="replace") as fh:
                unit_text = fh.read()
        except OSError:
            unit_text = ""
        for p in paths:
            if p in unit_text:
                return p
        for p in paths:
            if os.path.lexists(p):
                return p
    return paths[0]

def resolve_installed_target (comp ):

    return os .path .realpath (installed_link (comp ))

def delink_install_paths(comp):
    for link in [comp["install_link"]] + list(comp.get("legacy_links", ())):
        if not os.path.islink(link):
            continue
        target = os.path.realpath(link)
        tmp = link + ".delink.tmp"
        try:
            if os.path.isfile(target):
                shutil.copy2(target, tmp)
                os.replace(tmp, link)
                log_event(f"Replaced the symlink {link} with a plain copy of {os.path.basename(target)} before --install", "info")
            else:
                os.remove(link)
                log_event(f"Removed the dangling symlink {link} before --install", "info")
        except OSError as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            log_event(f"Could not replace the symlink {link} before --install: {exc}", "warn")

def retire_other_units(comp, script_path):
    names = [comp["service"]] + list(comp.get("legacy_services", ()))
    if len(names) < 2:
        return
    try:
        with open(script_path, errors="replace") as fh:
            text = fh.read()
    except OSError:
        return
    if not any(n + ".service" in text for n in names):
        return
    for n in names:
        unit = os.path.join(_SYSTEMD_UNIT_DIR, n + ".service")
        if n + ".service" in text or not os.path.exists(unit):
            continue
        try:
            subprocess.run(["systemctl", "disable", "--now", n + ".service"],
                           capture_output=True, text=True, timeout=30)
            os.remove(unit)
            for path in comp.get("unit_paths", {}).get(n, ()):
                if os.path.islink(path) or os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True, text=True, timeout=30)
            log_event(f"Retired {n}.service: {os.path.basename(script_path)} installs {comp['name']} under another name", "info")
        except (OSError, subprocess.TimeoutExpired) as exc:
            log_event(f"Could not retire {n}.service before --install: {exc}", "warn")

def prepare_install(comp, script_path):
    delink_install_paths(comp)
    retire_other_units(comp, script_path)

def _delink_shell(comp):
    parts = []
    for link in [comp["install_link"]] + list(comp.get("legacy_links", ())):
        q = shlex.quote(link)
        tq = shlex.quote(link + ".delink.tmp")
        parts.append(f'if [ -L {q} ]; then t=$(readlink -f {q}); '
                     f'if [ -f "$t" ] && cp -p "$t" {tq}; then mv -f {tq} {q}; else rm -f {q}; fi; fi')
    return "; ".join(parts)

def _version_sort_key (ver ):
    if not ver or ver =="?":
        return (-1 ,)
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
            elif cat in ("confgetter","confputter"):
                entry ["version"]=read_installed_version (full )or "?"
                target =CONFGETTER_BIN if cat =="confgetter" else CONFPUTTER_BIN
                entry ["installed"]=(file_sha256 (full )==file_sha256 (target ))
            elif cat =="config":
                live_cfg =os .path .join (CONFIG_DIR ,config_dest_name (name ))
                entry ["installed"]=(file_sha256 (full )==file_sha256 (live_cfg ))
                entry ["version"]="config"
            else :
                entry ["installed"]=None 
                entry ["version"]="script"
            out [cat ].append (entry )
        if cat in INSTALLABLE_CATEGORIES or cat in ("confgetter","confputter"):
            out [cat ].sort (key =lambda e :_version_sort_key (e ["version"]),reverse =True )
        else :
            out [cat ].sort (key =lambda e :e ["mtime_epoch"],reverse =True )
    return out 

def build_status ():
    components =[]
    for comp in COMPONENTS :
        state =systemctl_is_active (unit_of (comp ))
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
    "app":app_status (),
    "confgetter":confgetter_status (),
    "confputter":confputter_status (),
    "config":{
    "name":CONFIG_NAME ,
    "installed":os .path .isfile (os .path .join (CONFIG_DIR ,CONFIG_NAME )),
    "live":live_configs (),
    },
    }

def is_installer_script (name ):

    return any (fnmatch .fnmatch (name .lower (),g )for g in INSTALLER_SCRIPT_GLOBS )

def is_uninstaller_script (name ):

    return any (fnmatch .fnmatch (name .lower (),g )for g in UNINSTALLER_SCRIPT_GLOBS )

def is_interactive_only_script (name ):

    return any (fnmatch .fnmatch (name .lower (),g .lower ())for g in INTERACTIVE_ONLY_SCRIPT_GLOBS )

GITHUB_REPO =os .environ .get ("INSTMON_GITHUB_REPO","kd8pgk/ASL-DVS").strip ("/")
GITHUB_BRANCH =os .environ .get ("INSTMON_GITHUB_BRANCH","main")
GITHUB_RAW_BASE =f"https://raw.githubusercontent.com/{GITHUB_REPO }/{GITHUB_BRANCH }"
GITHUB_API_LIST_URL =(f"https://api.github.com/repos/{GITHUB_REPO }/contents"
f"?ref={urllib .parse .quote (GITHUB_BRANCH ,safe ='')}")
GITHUB_TIMEOUT_SEC =int (os .environ .get ("INSTMON_GITHUB_TIMEOUT_SEC","15"))
GITHUB_RETRIES = max(0, int(os.environ.get("INSTMON_GITHUB_RETRIES", "2")))
GITHUB_MAX_DOWNLOAD_SEC = int(os.environ.get("INSTMON_GITHUB_MAX_DOWNLOAD_SEC", "1800"))
GITHUB_LIST_MAX_BYTES =1024 *1024 
GITHUB_FILE_MAX_BYTES =MAX_UPLOAD_BYTES 
GITHUB_MAX_ENTRIES =1000 

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
    pass

_gh_lock =threading .Lock ()
_gh_state ={
"phase":"idle",
"checked_at":None ,
"error":None ,
"entries":[],
"skipped":0 ,
"busy":set (),
"event_seq":0 ,
"event_msg":"",
"event_level":"info",
"gen":0 ,
"started_at":None ,
}

GH_CHECK_LIMIT_SEC =int (os .environ .get ("INSTMON_GH_CHECK_LIMIT_SEC","240"))

_gh_version_cache ={}
_GH_VERSION_CACHE_MAX =200 
_gh_last_cands = []

def _gh_event (message ,level ):
    log_event (message ,level )
    with _gh_lock :
        _gh_state ["event_seq"]+=1 
        _gh_state ["event_msg"]=message 
        _gh_state ["event_level"]=level 

def _gh_kind_for_name (name ):
    lname =name .lower ()
    for category ,globs in HOME_SCAN_PATTERN_MAP :
        for g in globs :
            if fnmatch .fnmatch (lname ,g .lower ()):
                return category ,_NAME_GLOB_ALIASES .get (g ,g ).lower ()
    return None ,None 

def _git_blob_id (data ):
    return hashlib .sha1 (b"blob %d\x00"%len (data )+data ).hexdigest ()

def _gh_local_blob_id (path ):
    try :
        with open (path ,"rb")as f :
            return _git_blob_id (f .read ())
    except OSError :
        return None 

def _gh_source_label ():
    if channel_get ()=="stable":
        return f"{GITHUB_REPO } (stable channel)"
    return f"{GITHUB_REPO } ({GITHUB_BRANCH }, testing channel)"

_CHANNEL_PREF_PATH =os .path .join (CONFIG_DIR ,"instmon_channel.json")
_CHANNELS =("stable","testing")
GITHUB_STABLE_URL =GITHUB_RAW_BASE +"/channels/stable.json"

def channel_get ():
    try :
        with open (_CHANNEL_PREF_PATH )as fh :
            val =json .load (fh ).get ("channel")
    except (OSError ,ValueError ,AttributeError ):
        return "stable"
    return val if val in _CHANNELS else "stable"

def channel_set (choice ,confirm =False ):
    if choice not in _CHANNELS :
        return False ,f"Unknown channel: {choice !r}","err"
    if choice =="testing"and not confirm :
        return False ,"Switching to Testing needs confirmation.","warn"
    ensure_dirs ()
    compare_before_write (_CHANNEL_PREF_PATH ,json .dumps ({"channel":choice },indent =2 ).encode ("utf-8"))
    with _gh_lock :
        was_checking =_gh_state ["phase"]=="checking"
        _gh_state ["gen"]+=1 
        _gh_state .update (phase ="idle",error =None ,entries =[],skipped =0 ,checked_at =None ,started_at =None )
    _gh_last_cands [:]=[]
    if was_checking :
        log_event ("The running GitHub check was stopped -- the channel changed","warn")
    full_update_preview ()
    if choice =="stable":
        log_event ("Update channel set to Stable (default)","ok")
        return True ,"Channel: Stable. Updates come from the stable list. Press Check GitHub.","ok"
    log_event ("Update channel set to Testing (main branch)","warn")
    return True ,"Channel: Testing. Updates come straight from main, before they are proven. Press Check GitHub.","warn"

def channel_status ():
    return {"channel":channel_get ()}

def _gh_entry_url (entry ):
    return entry .get ("url")or _gh_file_url (entry ["name"])

def _gh_stable_cands ():
    try :
        raw =_gh_fetch_impl (GITHUB_STABLE_URL ,GITHUB_LIST_MAX_BYTES )
    except GhRejected as exc :
        if "404"in str (exc ):
            raise GhRejected ("this repo has no stable list (channels/stable.json) yet -- switch to Testing to update")
        raise 
    try :
        data =json .loads (raw .decode ("utf-8"))
    except (UnicodeDecodeError ,json .JSONDecodeError )as exc :
        raise GhRejected (f"the stable list could not be read ({exc })")
    tools =data .get ("tools")if isinstance (data ,dict )else None 
    if not isinstance (tools ,dict ):
        raise GhRejected ("the stable list has no tools section")
    out =[]
    skipped =0 
    for stem ,t in sorted (tools .items ()):
        if not isinstance (t ,dict ):
            continue 
        name ,blob ,commit =t .get ("file"),t .get ("blob"),t .get ("commit")
        category ,glob =_gh_kind_for_name (name )if isinstance (name ,str )else (None ,None )
        reason =None 
        if category is None or category not in GH_CATEGORIES :
            continue 
        if not _GH_NAME_RE .match (name ):
            reason ="file name has characters instmon refuses"
        elif os .path .splitext (name )[1 ].lower ()not in ALLOWED_EXT .get (category ,()):
            reason =f"not allowed in the {category } library"
        elif not isinstance (blob ,str )or not _GH_SHA1_RE .match (blob ):
            reason ="no file id"
        elif not isinstance (commit ,str )or not _GH_SHA1_RE .match (commit ):
            reason ="no commit id"
        if reason :
            skipped +=1 
            log_event (f"Stable list: skipped {name }: {reason }","warn")
            continue 
        out .append ({"name":name ,"category":category ,"glob":glob ,"blob":blob ,"size":None ,
        "url":f"https://raw.githubusercontent.com/{GITHUB_REPO }/{commit }/{urllib .parse .quote (name )}"})
    return out ,skipped 

class _GhRetry(Exception):
    pass

def _gh_fetch_once(url, headers, ctx, deadline, shown, max_bytes, chunks, total):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT_SEC, context=ctx) as resp:
        if not resp.geturl().lower().startswith("https://"):
            raise GhRejected("GitHub redirected the download off HTTPS")
        if total and resp.getcode() != 206:
            chunks.clear()
            total = 0
        length = resp.headers.get("Content-Length")
        expect = int(length) if length and length.isdigit() else None
        if expect is not None and total + expect > max_bytes:
            raise GhRejected(f"{shown} is larger than the {max_bytes // 1024} KB limit")
        got = 0
        while True:
            if time.monotonic() > deadline:
                raise GhRejected(f"download of {shown} took longer than {GITHUB_MAX_DOWNLOAD_SEC // 60} minutes "
                                 "-- the connection to GitHub is too slow")
            chunk = resp.read(65536)
            if not chunk:
                break
            got += len(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise GhRejected(f"{shown} is larger than the {max_bytes // 1024} KB limit")
            chunks.append(chunk)
        if expect is not None and got < expect:
            raise _GhRetry(f"the connection to GitHub dropped during {shown} ({total // 1024} KB received)")
    return total

def _gh_fetch_https(url, max_bytes):
    if not url.lower().startswith("https://"):
        raise GhRejected("the GitHub address must start with https://")
    if not _GH_REPO_RE.match(GITHUB_REPO):
        raise GhRejected(f"'{GITHUB_REPO}' is not an owner/repo name")
    shown = url.split("?", 1)[0].rsplit("/", 1)[-1] or url
    ctx = ssl.create_default_context()
    deadline = time.monotonic() + GITHUB_MAX_DOWNLOAD_SEC
    chunks, total, last = [], 0, ""
    tries = GITHUB_RETRIES + 1
    for attempt in range(tries):
        if attempt:
            time.sleep(2 * attempt)
        headers = {
            "User-Agent": f"instmon/{VERSION}",
            "Accept": "application/vnd.github+json" if "api.github.com" in url else "*/*",
            "Cache-Control": "no-cache",
        }
        if total:
            headers["Range"] = f"bytes={total}-"
        try:
            _gh_fetch_once(url, headers, ctx, deadline, shown, max_bytes, chunks, total)
            return b"".join(chunks)
        except GhRejected:
            raise
        except _GhRetry as exc:
            last = str(exc)
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and total:
                chunks.clear()
                last = f"GitHub refused to resume {shown}"
            elif exc.code == 404:
                raise GhRejected(f"{shown} was not found on GitHub (HTTP 404) -- check the repo name and branch")
            elif exc.code in (403, 429):
                raise GhRejected("GitHub's hourly limit for this node was reached -- try again later "
                                 f"(HTTP {exc.code})")
            elif exc.code >= 500:
                last = f"GitHub answered HTTP {exc.code} for {shown}"
            else:
                raise GhRejected(f"GitHub answered HTTP {exc.code} for {shown}")
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise GhRejected(f"GitHub's certificate could not be verified ({reason})")
            if isinstance(reason, (socket.timeout, TimeoutError)):
                last = f"GitHub did not answer within {GITHUB_TIMEOUT_SEC}s"
            else:
                last = f"cannot reach GitHub -- is this node online? ({reason})"
        except (socket.timeout, TimeoutError):
            last = f"GitHub stopped sending {shown} -- nothing arrived for {GITHUB_TIMEOUT_SEC}s"
        except (OSError, http.client.HTTPException) as exc:
            last = f"the connection to GitHub dropped during {shown} ({exc})"
        except ValueError as exc:
            raise GhRejected(f"download of {shown} failed: {exc}")
        total = sum(len(c) for c in chunks)
    raise GhRejected(f"{last} (tried {tries} times)")

_gh_fetch_impl =_gh_fetch_https 

def _gh_file_url (name ):
    return GITHUB_RAW_BASE +"/"+urllib .parse .quote (name )

GITHUB_API_DOCS_URL = (f"https://api.github.com/repos/{GITHUB_REPO}/contents/docs"
                       f"?ref={urllib.parse.quote(GITHUB_BRANCH, safe='')}")
DOCS_MAX_BYTES = 64 * 1024 * 1024
_DOCS_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,123}\.pdf$')
_docs_lock = threading.Lock()
_docs_state = {"phase": "idle", "error": None, "msg": "", "checked_at": None}
_DOCS_FETCHED_PATH = os.path.join(CONFIG_DIR, "instmon_manuals_fetched")
_DOCS_FIRST_FETCH_DELAYS = (5, 60, 120, 300)
_DOCS_DELETED_PATH = os.path.join(CONFIG_DIR, "instmon_manuals_deleted.json")
_docs_remote = []
_docs_deleted_lock = threading.Lock()

def _docs_deleted():
    try:
        with open(_DOCS_DELETED_PATH) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    return {n for n in data if isinstance(n, str)} if isinstance(data, list) else set()

def _docs_mark_deleted(add=(), remove=()):
    with _docs_deleted_lock:
        names = _docs_deleted()
        new = (names | set(add)) - set(remove)
        if new == names:
            return
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            tmp = _DOCS_DELETED_PATH + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(sorted(new), fh)
            os.replace(tmp, _DOCS_DELETED_PATH)
        except OSError as exc:
            log_event(f"Manuals: could not write {_DOCS_DELETED_PATH}: {exc}", "warn")

def _docs_pending(cands):
    deleted = _docs_deleted()
    out = []
    for c in cands:
        dest = safe_join(DOCS_DIR, c["name"])
        if dest is None:
            continue
        if not os.path.isfile(dest):
            if c["name"] not in deleted:
                out.append({"name": c["name"], "why": "new"})
        elif _gh_local_blob_id(dest) != c["blob"]:
            out.append({"name": c["name"], "why": "changed"})
    return out

def _docs_refresh_remote():
    try:
        _docs_remote[:] = _docs_parse_listing(_gh_fetch_impl(GITHUB_API_DOCS_URL, GITHUB_LIST_MAX_BYTES))
    except GhRejected as exc:
        log_event(f"Manuals: could not read GitHub's docs list: {exc}", "warn")

def docs_list():
    out = []
    try:
        names = sorted(os.listdir(DOCS_DIR))
    except OSError:
        return out
    for n in names:
        full = os.path.join(DOCS_DIR, n)
        if not _DOCS_NAME_RE.match(n) or not os.path.isfile(full) or os.path.islink(full):
            continue
        st = os.stat(full)
        out.append({"name": n, "size": st.st_size,
                    "date": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return out

def docs_path(name):
    if not isinstance(name, str) or not _DOCS_NAME_RE.match(name):
        return None
    full = safe_join(DOCS_DIR, name)
    if full is None or not os.path.isfile(full) or os.path.islink(full):
        return None
    return full

def _docs_parse_listing(raw):
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GhRejected(f"GitHub's docs list could not be read ({exc})")
    if not isinstance(data, list):
        raise GhRejected("GitHub did not return a list for the docs folder")
    out = []
    for item in data[:GITHUB_MAX_ENTRIES]:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        name, blob, size = item.get("name"), item.get("sha"), item.get("size")
        if not isinstance(name, str) or not _DOCS_NAME_RE.match(name):
            continue
        if not isinstance(blob, str) or not _GH_SHA1_RE.match(blob):
            continue
        if not isinstance(size, int) or size <= 0 or size > DOCS_MAX_BYTES:
            log_event(f"Manuals: skipped {name}: size {size} is outside the {DOCS_MAX_BYTES // 1048576} MB limit", "warn")
            continue
        out.append({"name": name, "blob": blob, "size": size})
    return out

def _docs_mark_fetched():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(_DOCS_FETCHED_PATH, "w") as fh:
            fh.write(datetime.now().strftime("%Y-%m-%d %H:%M") + "\n")
    except OSError as exc:
        log_event(f"Manuals: could not write {_DOCS_FETCHED_PATH}: {exc}", "warn")

def _docs_fetch(say=log_event, skip_deleted=False):
    got, same, failed = [], 0, []
    cands = _docs_parse_listing(_gh_fetch_impl(GITHUB_API_DOCS_URL, GITHUB_LIST_MAX_BYTES))
    _docs_remote[:] = cands
    deleted = _docs_deleted() if skip_deleted else set()
    os.makedirs(DOCS_DIR, exist_ok=True)
    for c in cands:
        dest = safe_join(DOCS_DIR, c["name"])
        if dest is None:
            continue
        if c["name"] in deleted and not os.path.isfile(dest):
            continue
        if os.path.isfile(dest) and _gh_local_blob_id(dest) == c["blob"]:
            same += 1
            continue
        try:
            data = _gh_fetch_impl(_gh_file_url("docs/" + c["name"]), DOCS_MAX_BYTES)
            if _git_blob_id(data) != c["blob"]:
                raise GhRejected("the download does not match GitHub's file list")
            if not data.startswith(b"%PDF-"):
                raise GhRejected("not a PDF file")
        except GhRejected as exc:
            if _gh_is_network_error(exc):
                raise
            failed.append(c["name"])
            say(f"Manuals: {c['name']} not saved: {exc}", "warn")
            continue
        tmp = f"{dest}.{os.getpid()}.tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest)
        got.append(c["name"])
        say(f"Manuals: saved {c['name']} ({len(data) // 1024} KB)", "ok")
    _docs_mark_deleted(remove=got)
    _docs_mark_fetched()
    return got, same, failed

def _docs_summary(got, same, failed):
    parts = [f"{len(got)} downloaded", f"{same} already up to date"]
    if failed:
        parts.append(f"{len(failed)} failed (see log)")
    return ", ".join(parts) + "."

def _docs_claim():
    with _docs_lock:
        if _docs_state["phase"] == "fetching":
            return False
        _docs_state.update(phase="fetching", error=None, msg="")
        return True

def _docs_fetch_bg(skip_deleted=False):
    try:
        got, same, failed = _docs_fetch(skip_deleted=skip_deleted)
    except Exception as exc:
        msg = str(exc) if isinstance(exc, GhRejected) else f"unexpected error: {exc}"
        with _docs_lock:
            _docs_state.update(phase="error", error=msg, msg="",
                               checked_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
        log_event(f"Manuals: GitHub fetch failed: {msg}", "err")
        return None
    msg = _docs_summary(got, same, failed)
    with _docs_lock:
        _docs_state.update(phase="done", error=None, msg=msg,
                           checked_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
    log_event("Manuals: " + msg, "warn" if failed else "ok")
    _fu_refresh_plan()
    return got, same, failed

def _docs_first_fetch_loop():
    for delay in _DOCS_FIRST_FETCH_DELAYS:
        time.sleep(delay)
        if os.path.exists(_DOCS_FETCHED_PATH):
            return
        if not _docs_claim():
            continue
        log_event(f"Manuals: first download from {_gh_source_label()}", "info")
        if _docs_fetch_bg() is not None:
            return
    log_event("Manuals: could not reach GitHub -- press Get from GitHub on the Manuals card, "
              "or run a Full Update, once the node is online", "warn")

def docs_start_first_fetch():
    if os.path.exists(_DOCS_FETCHED_PATH):
        return
    threading.Thread(target=_docs_first_fetch_loop, daemon=True).start()

def docs_install_fetch():
    print("\nDownloading the manuals from GitHub...")
    def say(msg, level):
        print(f"  [{'+' if level == 'ok' else '!'}] {msg.split(': ', 1)[-1]}")
    try:
        got, same, failed = _docs_fetch(say)
    except Exception as exc:
        print(f"  [!] Manuals not downloaded ({exc}). instmon downloads them when it starts and GitHub can be reached.")
        return
    print(f"  [+] Manuals: {_docs_summary(got, same, failed)} Open them on instmon's Manuals card.")

def docs_stage(filename, data, source="usb"):
    stem = os.path.splitext(filename)[0]
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:120] + ".pdf"
    if not _DOCS_NAME_RE.match(name):
        return 400, {"error": f"'{filename}' can't be used as a manual's name"}
    if not data.startswith(b"%PDF-"):
        return 400, {"error": f"'{filename}' is not a PDF file"}
    os.makedirs(DOCS_DIR, exist_ok=True)
    dest = safe_join(DOCS_DIR, name)
    if dest is None:
        return 400, {"error": "invalid file name"}
    shown = name if name == filename else f"{filename} (saved as {name})"
    if os.path.isfile(dest) and not os.path.islink(dest) and _gh_local_blob_id(dest) == _git_blob_id(data):
        return 200, {"ok": True, "name": name, "level": "info",
                     "message": f"{shown} is already in Manuals -- nothing to do."}
    tmp = dest + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, dest)
    _docs_mark_deleted(remove=[name])
    _fu_refresh_plan()
    how = "uploaded" if source == "upload" else "imported from USB"
    log_event(f"Manuals: {how} {shown} ({len(data) // 1024} KB)", "ok")
    return 200, {"ok": True, "name": name, "level": "ok",
                 "message": f"{'Uploaded' if source == 'upload' else 'Imported'} {shown} into Manuals -- open it from the Manuals card."}

def docs_delete(name):
    full = docs_path(name)
    if full is None:
        return 404, {"error": "No such manual"}
    try:
        os.remove(full)
    except OSError as exc:
        return 500, {"error": f"Could not delete {name}: {exc}"}
    _docs_mark_deleted(add=[name])
    _fu_refresh_plan()
    log_event(f"Manuals: deleted {name}", "info")
    return 200, {"ok": True, "message": f"Deleted {name} from Manuals.", "level": "info"}

def docs_start_fetch():
    if not _docs_claim():
        return False, "The manuals are already being fetched."
    log_event(f"Manuals: fetching the docs folder from {_gh_source_label()}", "info")
    threading.Thread(target=_docs_fetch_bg, daemon=True).start()
    return True, "Getting the manuals from GitHub..."

def docs_status():
    with _docs_lock:
        state = dict(_docs_state)
    state["docs"] = docs_list()
    return state

GITHUB_API_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=15"
APP_MAX_BYTES = 32 * 1024 * 1024
APP_LIST_MAX_BYTES = 2 * 1024 * 1024
APP_PACKAGE = "io.github.kd8pgk.nodetalker"
_APP_TAG_RE = re.compile(r'^android-v(\d{1,3})\.(\d{1,3})\.(\d{1,4})$')
_APP_NAME_RE = re.compile(r'^NodeTalker-(\d{1,3}\.\d{1,3}\.\d{1,4})(-debug)?\.apk$')
_app_lock = threading.Lock()
_app_state = {"phase": "idle", "error": None, "msg": "", "checked_at": None, "latest": None}
_APP_FETCHED_PATH = os.path.join(CONFIG_DIR, "instmon_app_fetched")
_APP_FIRST_FETCH_DELAYS = (20, 90, 180, 360)

def _app_vkey(version):
    return tuple(int(x) for x in version.split("."))

def _app_parse_releases(raw):
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GhRejected(f"GitHub's release list could not be read ({exc})")
    if not isinstance(data, list):
        raise GhRejected("GitHub did not return a release list")
    best = None
    for rel in data[:GITHUB_MAX_ENTRIES]:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        tag = rel.get("tag_name")
        tm = _APP_TAG_RE.match(tag) if isinstance(tag, str) else None
        if not tm:
            continue
        version = ".".join(tm.groups())
        for asset in rel.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            name, size = asset.get("name"), asset.get("size")
            nm = _APP_NAME_RE.match(name) if isinstance(name, str) else None
            if not nm or nm.group(1) != version:
                continue
            if not isinstance(size, int) or size <= 0 or size > APP_MAX_BYTES:
                continue
            digest = asset.get("digest")
            sha = None
            if isinstance(digest, str) and digest.startswith("sha256:") and re.fullmatch(r"[0-9a-fA-F]{64}", digest[7:]):
                sha = digest[7:].lower()
            if best is None or _app_vkey(version) > _app_vkey(best["version"]):
                best = {"version": version, "tag": tag, "name": name, "size": size, "sha256": sha,
                        "url": f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/{urllib.parse.quote(name)}"}
            break
    return best

def _app_check_apk(data):
    if not data.startswith(b"PK\x03\x04"):
        raise GhRejected("not an APK file")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "AndroidManifest.xml" not in names or "classes.dex" not in names:
                raise GhRejected("not an APK file (no manifest or code)")
            manifest = zf.read("AndroidManifest.xml")
    except zipfile.BadZipFile:
        raise GhRejected("the download is not a valid APK file")
    if APP_PACKAGE.encode("utf-16-le") not in manifest and APP_PACKAGE.encode("ascii") not in manifest:
        raise GhRejected("the APK is not Node Talker Mobile")

def app_list():
    out = []
    try:
        names = os.listdir(APP_DIR)
    except OSError:
        return out
    for n in names:
        m = _APP_NAME_RE.match(n)
        full = os.path.join(APP_DIR, n)
        if not m or not os.path.isfile(full) or os.path.islink(full):
            continue
        st = os.stat(full)
        out.append({"name": n, "version": m.group(1), "size": st.st_size,
                    "date": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    out.sort(key=lambda e: _app_vkey(e["version"]), reverse=True)
    return out

def app_path(name):
    if not isinstance(name, str) or not _APP_NAME_RE.match(name):
        return None
    full = safe_join(APP_DIR, name)
    if full is None or not os.path.isfile(full) or os.path.islink(full):
        return None
    return full

def _app_mark_fetched():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(_APP_FETCHED_PATH, "w") as fh:
            fh.write(datetime.now().strftime("%Y-%m-%d %H:%M") + "\n")
    except OSError as exc:
        log_event(f"Node Talker Mobile: could not write {_APP_FETCHED_PATH}: {exc}", "warn")

def _app_fetch(say=log_event):
    rel = _app_parse_releases(_gh_fetch_impl(GITHUB_API_RELEASES_URL, APP_LIST_MAX_BYTES))
    with _app_lock:
        _app_state["latest"] = None if rel is None else {"version": rel["version"], "name": rel["name"]}
    if rel is None:
        raise GhRejected("GitHub has no Node Talker Mobile release yet")
    os.makedirs(APP_DIR, exist_ok=True)
    dest = safe_join(APP_DIR, rel["name"])
    if dest is None:
        raise GhRejected("the release file name is not allowed")
    if os.path.isfile(dest) and os.path.getsize(dest) == rel["size"]:
        _app_mark_fetched()
        return rel, False
    data = _gh_fetch_impl(rel["url"], APP_MAX_BYTES)
    if len(data) != rel["size"]:
        raise GhRejected("the download does not match GitHub's release size")
    if rel["sha256"] and hashlib.sha256(data).hexdigest() != rel["sha256"]:
        raise GhRejected("the download does not match GitHub's checksum")
    _app_check_apk(data)
    tmp = f"{dest}.{os.getpid()}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, dest)
    for old in app_list():
        if old["name"] != rel["name"]:
            try:
                os.remove(os.path.join(APP_DIR, old["name"]))
            except OSError:
                pass
    _app_mark_fetched()
    say(f"Node Talker Mobile: saved {rel['name']} ({len(data) // 1024} KB)", "ok")
    return rel, True

def _app_claim():
    with _app_lock:
        if _app_state["phase"] == "fetching":
            return False
        _app_state.update(phase="fetching", error=None, msg="")
        return True

def _app_fetch_bg():
    try:
        rel, got = _app_fetch()
    except Exception as exc:
        msg = str(exc) if isinstance(exc, GhRejected) else f"unexpected error: {exc}"
        with _app_lock:
            _app_state.update(phase="error", error=msg, msg="",
                              checked_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
        log_event(f"Node Talker Mobile: GitHub fetch failed: {msg}", "err")
        return None
    msg = (f"Downloaded {rel['name']}." if got else f"{rel['name']} is already the newest.")
    with _app_lock:
        _app_state.update(phase="done", error=None, msg=msg,
                          checked_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
    log_event("Node Talker Mobile: " + msg, "ok")
    return rel

def app_start_fetch():
    if not _app_claim():
        return False, "Node Talker Mobile is already being fetched."
    log_event(f"Node Talker Mobile: checking {_gh_source_label()} for the newest release", "info")
    threading.Thread(target=_app_fetch_bg, daemon=True).start()
    return True, "Getting Node Talker Mobile from GitHub..."

def app_delete(name):
    full = app_path(name)
    if full is None:
        return 404, {"error": "No such app file"}
    try:
        os.remove(full)
    except OSError as exc:
        return 500, {"error": f"Could not delete {name}: {exc}"}
    log_event(f"Node Talker Mobile: deleted {name}", "info")
    return 200, {"ok": True, "message": f"Deleted {name}.", "level": "info"}

def app_status():
    with _app_lock:
        state = dict(_app_state)
    state["files"] = app_list()
    return state

def _app_first_fetch_loop():
    for delay in _APP_FIRST_FETCH_DELAYS:
        time.sleep(delay)
        if os.path.exists(_APP_FETCHED_PATH):
            return
        if not _app_claim():
            continue
        log_event(f"Node Talker Mobile: first download from {_gh_source_label()}", "info")
        if _app_fetch_bg() is not None:
            return
    log_event("Node Talker Mobile: could not reach GitHub -- press Check on its row in Components "
              "once the node is online", "warn")

def app_start_first_fetch():
    if os.path.exists(_APP_FETCHED_PATH):
        return
    threading.Thread(target=_app_first_fetch_loop, daemon=True).start()

def _gh_parse_listing (raw ):
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
    m = re.search(r"-([A-Za-z0-9]+)\s*$", version or "")
    return m.group(1).lower() if m else ""

def _gh_local_files (category ,glob ):
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
    for _n ,ver ,_key ,full in local :
        if ver and _gh_local_blob_id (full )==cand ["blob"]:
            return ver 
    if cand ["blob"]in _gh_version_cache :
        cached =_gh_version_cache [cand ["blob"]]
        if cached is None :
            raise GhRejected ("no version line found in the file")
        return cached 
    data =_gh_fetch_impl (_gh_entry_url (cand ),GITHUB_FILE_MAX_BYTES )
    if _git_blob_id (data )!=cand ["blob"]:
        raise GhRejected ("the download did not match GitHub's file list (changed mid-check?)")
    try :
        text =data .decode ("utf-8")
    except UnicodeDecodeError :
        raise GhRejected ("not UTF-8 text")
    ver ,_si ,_su =_scan_header_text (text )
    if len (_gh_version_cache )>=_GH_VERSION_CACHE_MAX :
        _gh_version_cache .clear ()
    _gh_version_cache [cand ["blob"]]=ver or None 
    if not ver :
        raise GhRejected ("no version line found in the file")
    return ver 

def _gh_version_known (cand ,local ):
    if cand ["blob"]in _gh_version_cache :
        return True 
    return any (ver and _gh_local_blob_id (full )==cand ["blob"]for _n ,ver ,_key ,full in local )

def _build_other (category ,version ,name =""):
    if category not in ("sysmon","dashboard"):
        return False
    wanted =_build_wanted_variant ()or ""
    variant =_gh_variant (version )
    if not variant and "_"+BUILD_PI02W_SUFFIX +"_"in (name or "").lower ():
        variant =BUILD_PI02W_SUFFIX
    return variant !=wanted

def _gh_other_build (entry ):
    return _build_other (entry .get ("category"),entry .get ("version"),entry .get ("name",""))

def _gh_compare (entry ):
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
    entries ,skipped ,cands =_gh_collect_full ()
    _gh_last_cands [:]=cands 
    return entries ,skipped 

def _gh_collect_full (gen =None ):
    def progress (msg ):
        if gen is not None and _gh_state ["gen"]==gen :
            log_event (msg ,"info")
    if channel_get ()=="stable":
        cands ,skipped =_gh_stable_cands ()
        progress (f"GitHub: the stable list has {len (cands )} file(s)")
    else :
        raw =_gh_fetch_impl (GITHUB_API_LIST_URL ,GITHUB_LIST_MAX_BYTES )
        cands ,skipped =_gh_parse_listing (raw )
        progress (f"GitHub: main lists {len (cands )} file(s)")
    listed =[dict (c )for c in cands ]
    newest ={}
    for n ,cand in enumerate (cands ,1 ):
        local =_gh_local_files (cand ["category"],cand ["glob"])
        if gen is not None and not _gh_version_known (cand ,local ):
            progress (f"GitHub: reading {cand ['name']} ({n } of {len (cands )})")
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
    return entries ,skipped ,listed 

def _gh_is_network_error(exc):
    text = str(exc)
    return any(s in text for s in ("reach GitHub", "hourly limit", "did not answer",
                                   "stopped sending", "connection to GitHub", "refused to resume"))

def _gh_check_current (gen ):
    return _gh_state ["gen"]==gen and _gh_state ["phase"]=="checking"

def _gh_check_bg (gen =None ):
    started =time .monotonic ()
    try :
        entries ,skipped ,listed =_gh_collect_full (gen )
    except Exception as exc :
        msg =str (exc )if isinstance (exc ,GhRejected )else f"unexpected error: {exc }"
        with _gh_lock :
            if gen is not None and not _gh_check_current (gen ):
                return 
            _gh_state ["phase"]="error"
            _gh_state ["error"]=msg 
            _gh_state ["entries"]=[]
            _gh_state ["checked_at"]=datetime .now ().strftime ("%Y-%m-%d %H:%M")
        _gh_event (f"GitHub check failed: {msg }","err")
        return 
    with _gh_lock :
        if gen is not None and not _gh_check_current (gen ):
            stale =True 
        else :
            stale =False 
            _gh_last_cands [:]=listed 
            _gh_state ["phase"]="done"
            _gh_state ["error"]=None 
            _gh_state ["entries"]=entries 
            _gh_state ["skipped"]=skipped 
            _gh_state ["checked_at"]=datetime .now ().strftime ("%Y-%m-%d %H:%M")
    if stale :
        log_event ("An earlier GitHub check finished late -- its result was not used","info")
        return 
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
    _gh_event ("GitHub check: "+", ".join (parts )+f". ({time .monotonic ()-started :.0f}s)",level )
    _docs_refresh_remote()
    full_update_preview()

def _gh_check_timeout (gen ):
    with _gh_lock :
        if not _gh_check_current (gen ):
            return 
        _gh_state ["gen"]+=1 
        msg =(f"GitHub did not finish answering within {GH_CHECK_LIMIT_SEC //60 } min -- "
        "check this node's internet connection, then press Check GitHub again")
        _gh_state .update (phase ="error",error =msg ,entries =[],started_at =None ,
        checked_at =datetime .now ().strftime ("%Y-%m-%d %H:%M"))
    _gh_event (f"GitHub check failed: {msg }","err")

def gh_start_check ():
    with _gh_lock :
        if _gh_state ["phase"]=="checking":
            return False ,"A GitHub check is already running."
        if _gh_state ["busy"]:
            return False ,"A GitHub download is running -- wait for it to finish."
        _gh_state ["gen"]+=1 
        gen =_gh_state ["gen"]
        _gh_state ["phase"]="checking"
        _gh_state ["error"]=None 
        _gh_state ["started_at"]=time .monotonic ()
    log_event (f"GitHub check started ({_gh_source_label ()})","info")
    timer =threading .Timer (GH_CHECK_LIMIT_SEC ,_gh_check_timeout ,args =(gen ,))
    timer .daemon =True 
    timer .start ()
    threading .Thread (target =_gh_check_bg ,args =(gen ,),daemon =True ).start ()
    return True ,"Checking GitHub -- results appear in each library group."

def _gh_verify_content (entry ,data ):
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
    name =entry ["name"]
    category =entry ["category"]
    if _gh_kind_for_name (name )!=(category ,entry ["glob"])or category not in GH_CATEGORIES :
        raise GhRejected (f"{name } does not belong in the {category } library")
    if not _GH_NAME_RE .match (name ):
        raise GhRejected ("invalid file name")
    data =_gh_fetch_impl (_gh_entry_url (entry ),GITHUB_FILE_MAX_BYTES )
    _gh_verify_content (entry ,data )

    current =_gh_compare (dict (entry ))
    if current ["status"]=="up_to_date":
        return f"{name } is already in the {category } library -- nothing to do.","info"
    older_ok =entry .get ("allow_older")and channel_get ()=="stable"and current ["status"]=="newer_local"
    if current ["status"]not in _GH_UPDATABLE and not older_ok :
        raise GhRejected (current ["message"])

    ensure_dirs ()
    dest =safe_join (LIB_SUBDIRS [category ],name )
    if dest is None :
        raise GhRejected ("invalid file name")
    if os .path .isfile (dest )and lib_locked (category ,name )and _gh_local_blob_id (dest )!=entry ["blob"]:
        raise GhRejected (_locked_msg (name ))
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

def gh_start_update (name ,allow_older =False ):
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
        older_ok =allow_older and channel_get ()=="stable"and entry .get ("status")=="newer_local"
        if entry .get ("status")not in _GH_UPDATABLE and not older_ok :
            label =_GH_LABELS .get (entry .get ("status"),("?",""))[0 ]
            return 400 ,f"{name }: {label } -- nothing to update.","warn"
        _gh_state ["busy"].add (name )
        entry =dict (entry ,allow_older =bool (older_ok ))
    log_event (f"GitHub update started: {name }","info")
    threading .Thread (target =_gh_update_bg ,args =(entry ,),daemon =True ).start ()
    return 200 ,f"Downloading {name } -- it is checked before it is saved.","info"

def _gh_group_html (category ):
    with _gh_lock :
        if _gh_state ["phase"]!="done":
            return ""
        entries =[dict (e )for e in _gh_state ["entries"]if e ["category"]==category and not _gh_other_build (e )]
        busy =set (_gh_state ["busy"])
    if not entries :
        return ""
    stable =channel_get ()=="stable"
    rows =[]
    for e in entries :
        label ,cls =_GH_LABELS .get (e .get ("status"),("?",""))
        name =esc (e ["name"])
        if e ["name"]in busy :
            action ='<span class="small muted">Downloading&hellip;</span>'
        elif e .get ("status")in _GH_UPDATABLE :
            action =(f'<button data-action="gh_update" data-category="{esc (category )}" '
            f'data-name="{name }">Update</button>')
        elif stable and e .get ("status")=="newer_local":
            label ,cls ="Ahead of stable",""
            action =(f'<button data-action="gh_update" data-older="1" data-category="{esc (category )}" '
            f'data-name="{name }" title="Put this older stable file in the library; nothing installs until you press Install">Get stable</button>')
        else :
            action ="<span></span>"
        rows .append (
        f'<div class="gh-row" title="{esc (e .get ("message",""))}">'
        f'<span class="gh-tag {cls }">{esc (label )}</span>'
        f'<span>{"Stable"if stable else "GitHub"} v{esc (e ["version"])}</span>'
        f'<span class="small muted">{name }</span>'
        "<span></span>"
        f'{action }</div>')
    return '<div class="gh-rows">'+"".join (rows )+"</div>"

def _gh_summary_html ():
    with _gh_lock :
        phase =_gh_state ["phase"]
        err =_gh_state ["error"]
        when =_gh_state ["checked_at"]
        entries =[e for e in _gh_state ["entries"]if not _gh_other_build (e )]
        skipped =_gh_state ["skipped"]
    src =esc (_gh_source_label ())
    if phase =="idle":
        return f'<span class="muted">Not checked yet. Source: {src }</span>'
    if phase =="checking":
        return f'<span class="muted">Checking {src }&hellip; (progress is in the log below)</span>'
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
        _quiet_arm_timer(60)
        return
    log_event(f"Quiet System: auto-restore after {QUIET_AUTO_RESTORE_SEC // 60} min", "warn")
    quiet_restore()

def quiet_start():
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
    with _quiesce_lock:
        state = _quiesce_state_read()
        if not state or state.get("job_id") != QUIET_JOB_ID:
            return
        names = {service, service + ".service"}
        for c in COMPONENTS:
            if c["service"] == service:
                for n in c.get("legacy_services", ()):
                    names.update((n, n + ".service"))
        kept = [e for e in state.get("stopped") or [] if e[2] not in names]
        if len(kept) != len(state.get("stopped") or []):
            _quiesce_state_write(QUIET_JOB_ID, kept, started_at=state.get("started_at"))

_DT_MODEL_PATH = os.environ.get("INSTMON_DT_MODEL_PATH", "/proc/device-tree/model")
_BUILD_PREF_PATH = os.path.join(CONFIG_DIR, "instmon_build.json")
BUILD_PI02W_SUFFIX = "pi02w"
_BUILD_CHOICES = ("fork", "full")

def is_pi02w():
    try:
        with open(_DT_MODEL_PATH, "rb") as fh:
            model = fh.read(256).decode("utf-8", "replace")
    except OSError:
        return False
    return "Zero 2" in model

def build_pref_get():
    try:
        with open(_BUILD_PREF_PATH) as fh:
            val = json.load(fh).get("pi02w_build")
    except (OSError, ValueError, AttributeError):
        return "fork"
    return val if val in _BUILD_CHOICES else "fork"

def build_pref_set(choice):
    if choice not in _BUILD_CHOICES:
        return False, f"Unknown build choice: {choice!r}", "err"
    if not is_pi02w():
        return False, "This isn't a Pi Zero 2 W -- the build choice only applies there.", "warn"
    ensure_dirs()
    compare_before_write(_BUILD_PREF_PATH, json.dumps({"pi02w_build": choice}, indent=2).encode("utf-8"))
    label = "Pi02w fork (default)" if choice == "fork" else "Full build (override)"
    log_event(f"Pi Zero 2 W build set to: {label}", "ok" if choice == "fork" else "warn")
    full_update_preview()
    return True, f"Pi Zero 2 W build: {label}. Full Update installs this build of SysMon and the Dashboard.", "ok"

def build_choice_status():
    pi02w = is_pi02w()
    return {"pi02w": pi02w, "choice": build_pref_get() if pi02w else "full"}

def _build_wanted_variant():
    if not is_pi02w():
        return None
    return BUILD_PI02W_SUFFIX if build_pref_get() == "fork" else ""

FU_ORDER = ("44helper", "wifimon", "nodelisten", "dashboard", "sysmon", "watchdog", "instmon")
FU_START_TIMEOUT_SEC = int(os.environ.get("INSTMON_FU_START_TIMEOUT_SEC", "60"))
FU_SELF_GUARD_SEC = 90
_FU_STATE_PATH = os.path.join(CONFIG_DIR, "instmon_full_update.json")

_FU_DEFAULT_STEM = {
    "dashboard": "nodecontrol",
    "sysmon": "sysmon",
    "wifimon": "wifimon",
    "44helper": "44helper",
    "nodelisten": "nodetalker",
    "watchdog": "asl_dvs_watchdog",
    "instmon": "instmon",
}
_FU_STEM_RE = re.compile(r"^(?P<stem>.+?)_v\d+(?:[._]\d+)*(?:_\d{8})?(?:[._-].*)?\.(?:py|sh)$", re.IGNORECASE)

_FU_ACTIONABLE = ("update", "switch")

_fu_lock = threading.Lock()
_fu_state = {
    "running": False, "phase": "", "current": "", "error": "", "banner": False,
    "updated": [], "skipped": [], "attention": [], "scripts": [], "manuals": [], "instmon_pending": None,
    "plan": None, "plan_at": "", "wait_end": 0.0, "wait_what": "", "stopping": False, "in_progress": None,
}
_fu_stop_ev = threading.Event()
_FU_JOB_UNIT = "instmon-fu-job"
_FU_JOB_LOG = os.path.join(CONFIG_DIR, "instmon_fu_job.log")
_FU_NO_STOP_PHASES = ("instmon", "recovering")

def full_update_running():
    with _fu_lock:
        return _fu_state["running"]

def _fu_set(**kw):
    with _fu_lock:
        _fu_state.update(kw)

def _fu_save():
    with _fu_lock:
        payload = {k: v for k, v in _fu_state.items() if k not in ("plan", "plan_at", "wait_end", "wait_what")}
    try:
        ensure_dirs()
        compare_before_write(_FU_STATE_PATH, json.dumps(payload, indent=2).encode("utf-8"))
    except Exception as exc:
        log_event(f"Full Update: could not save state: {exc}", "warn")

def full_update_snapshot():
    with _fu_lock:
        snap = json.loads(json.dumps(_fu_state))
    end = snap.pop("wait_end", 0.0)
    left = int(end - time.monotonic() + 0.999) if end else 0
    snap["wait_left"] = max(0, left) if snap.get("running") and snap.get("wait_what") else 0
    return snap

def _fu_wait_begin(secs, what):
    _fu_set(wait_end=time.monotonic() + secs, wait_what=what)

def _fu_wait_end():
    _fu_set(wait_end=0.0, wait_what="")

_FU_STEM_ALIASES = (("asl_dvs_dashboard", "nodecontrol"), ("asl_dvs_m17_44helper", "44helper"), ("nodelisten", "nodetalker"))

def _fu_stem_of_name(name):
    m = _FU_STEM_RE.match(name)
    stem = (m.group("stem") if m else os.path.splitext(name)[0]).lower()
    for old, new in _FU_STEM_ALIASES:
        if stem == old or stem.startswith(old + "_"):
            return new + stem[len(old):]
    return stem

def _fu_installed_stem(comp, target, version):
    base = os.path.basename(target)
    if _FU_STEM_RE.match(base):
        return _fu_stem_of_name(base)
    stem = _FU_DEFAULT_STEM[comp["category"]]
    m = re.search(r"-([A-Za-z0-9]+)\s*$", version or "")
    return f"{stem}_{m.group(1).lower()}" if m else stem

def _fu_wanted_stem(inst_stem, cat, cands):
    wanted = _build_wanted_variant()
    if wanted is None:
        return inst_stem
    suffix = "_" + BUILD_PI02W_SUFFIX
    base = inst_stem[:-len(suffix)] if inst_stem.endswith(suffix) else inst_stem
    if wanted:
        fork = base + suffix
        if any(c["category"] == cat and _fu_stem_of_name(c["name"]) == fork for c in cands):
            return fork
    return base

def _fu_build_label(stem):
    return "Pi02w fork" if stem.endswith("_" + BUILD_PI02W_SUFFIX) else "full"

def _fu_plan(cands):
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
        inst_stem = _fu_installed_stem(comp, target, inst_ver)
        stem = _fu_wanted_stem(inst_stem, cat, cands)
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
            elif channel_get() == "stable":
                row.update(status="not_on_github", note=f"no stable build of {stem} yet")
            else:
                row.update(status="not_on_github", note=f"no {stem} build on GitHub")
            continue
        row.update(file=best["name"], version=best["version"], entry=best)
        if stem != inst_stem:
            row.update(status="switch", note=f"{_fu_build_label(inst_stem)} v{inst_ver} -> "
                                             f"{_fu_build_label(stem)} v{best['version']}")
            if problems:
                row.update(status="error", note=f"couldn't read {problems[0]}")
            continue
        if _gh_local_blob_id(target) == best["blob"]:
            row.update(status="current", note="same file as GitHub")
        elif _version_sort_key(best["version"]) > _version_sort_key(inst_ver):
            row.update(status="update", note=f"v{inst_ver} -> v{best['version']}")
        elif _version_sort_key(best["version"]) == _version_sort_key(inst_ver):
            row.update(status="current", note=f"same version (v{inst_ver})")
        else:
            row.update(status="newer_installed",
                       note=(f"installed v{inst_ver} is ahead of stable v{best['version']} -- left alone"
                             if channel_get() == "stable" else f"installed v{inst_ver} is newer than GitHub"))
        if problems and row["status"] != "update":
            row.update(status="error", note=f"couldn't read {problems[0]}")
    return rows

def _fu_publish_plan(rows, scripts):
    public = [{k: v for k, v in r.items() if k != "entry"} for r in rows]
    _fu_set(plan={"components": public, "scripts": [e["name"] for e in scripts],
                  "manuals": _docs_pending(_docs_remote),
                  "updates": sum(1 for r in rows if r["status"] in _FU_ACTIONABLE)},
            plan_at=datetime.now().strftime("%Y-%m-%d %H:%M"))

def _fu_stage(entry):
    data = _gh_fetch_impl(_gh_entry_url(entry), GITHUB_FILE_MAX_BYTES)
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

def _fu_job_active():
    return systemctl_is_active(_FU_JOB_UNIT + ".service") in ("active", "activating", "deactivating", "reloading")

def _fu_job_log_drain(pos, final=False):
    try:
        with open(_FU_JOB_LOG, "rb") as fh:
            fh.seek(pos)
            data = fh.read()
    except OSError:
        return pos
    if not final:
        data = data[:data.rfind(b"\n") + 1]
    for line in data.decode("utf-8", "replace").splitlines():
        log_event(line, "info")
    return pos + len(data)

def _fu_job_stop():
    for args in (["systemctl", "stop", _FU_JOB_UNIT + ".service"],
                 ["systemctl", "reset-failed", _FU_JOB_UNIT + ".service"]):
        try:
            subprocess.run(args, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass

def _fu_run_cli(script_path, flag, stoppable=True):
    if not shutil.which("systemd-run"):
        return _fu_run_cli_direct(script_path, flag)
    label = f"{os.path.basename(script_path)} {flag}"
    _fu_job_stop()
    try:
        ensure_dirs()
        open(_FU_JOB_LOG, "w").close()
        proc = subprocess.Popen(["systemd-run", "--quiet", "--wait", "--collect", f"--unit={_FU_JOB_UNIT}",
                                 "--service-type=exec", "--setenv=PYTHONUNBUFFERED=1",
                                 "-p", f"StandardOutput=append:{_FU_JOB_LOG}", "-p", "StandardError=inherit",
                                 "-p", f"RuntimeMaxSec={SCRIPT_TIMEOUT_SEC}",
                                 _interp_for(script_path), script_path, flag],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except OSError as exc:
        log_event(f"Could not run {label}: {exc}", "err")
        return None
    pos, stop_sent = 0, False
    deadline = time.monotonic() + SCRIPT_TIMEOUT_SEC + 30
    while proc.poll() is None:
        pos = _fu_job_log_drain(pos)
        if stoppable and not stop_sent and _fu_stop_ev.is_set():
            stop_sent = True
            log_event(f"Full Update: stopping {label}", "warn")
            threading.Thread(target=_fu_job_stop, daemon=True).start()
        if time.monotonic() > deadline:
            proc.kill()
            _fu_job_stop()
            _fu_job_log_drain(pos, final=True)
            log_event(f"{label} timed out ({SCRIPT_TIMEOUT_SEC}s), killed", "err")
            return None
        time.sleep(0.5)
    _fu_job_log_drain(pos, final=True)
    err = (proc.stderr.read() or "").strip()
    if err:
        log_event(f"{label}: {err[:300]}", "warn")
    return proc.returncode

def _fu_run_cli_direct(script_path, flag):
    try:
        proc = subprocess.Popen([_interp_for(script_path), script_path, flag],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                env=_cli_env())
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

def _fu_wait_healthy(comp, what="start and answer", stoppable=True):
    deadline = time.time() + FU_START_TIMEOUT_SEC
    state = "unknown"
    _fu_wait_begin(FU_START_TIMEOUT_SEC, what)
    try:
        while time.time() < deadline:
            if stoppable and _fu_stop_ev.is_set():
                return False, "stopped by you"
            state = systemctl_is_active(unit_of(comp))
            if state == "active" and (comp["port"] is None or port_open(comp["port"])):
                return True, state
            time.sleep(2)
    finally:
        _fu_wait_end()
    if state == "active":
        return False, f"running but not answering on port {comp['port']}"
    return False, state

FU_STABLE_SEC = int(os.environ.get("INSTMON_FU_STABLE_SEC", "60"))
FU_STABLE_POLL_SEC = 3.0

def _unit_nrestarts(unit):
    try:
        r = subprocess.run(["systemctl", "show", "-p", "NRestarts", "--value", unit],
                           capture_output=True, text=True, timeout=10)
        return int((r.stdout or "").strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None

def _http_alive(port):
    for scheme in ("http", "https"):
        if scheme == "http":
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        else:
            conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=5,
                                               context=ssl._create_unverified_context())
        try:
            conn.request("GET", "/healthz")
            conn.getresponse().read(4096)
            return True
        except (http.client.BadStatusLine, http.client.RemoteDisconnected, ssl.SSLError, ConnectionResetError):
            continue
        except (OSError, http.client.HTTPException):
            return False
        finally:
            conn.close()
    return False

def _watch_steady(comp, secs=None, stop_ev=None):
    secs = FU_STABLE_SEC if secs is None else secs
    unit = unit_of(comp)
    base = _unit_nrestarts(unit)
    deadline = time.monotonic() + secs
    http_fails = 0
    while time.monotonic() < deadline:
        time.sleep(min(FU_STABLE_POLL_SEC, max(0.0, deadline - time.monotonic())))
        if stop_ev is not None and stop_ev.is_set():
            return False, "stopped by you"
        state = systemctl_is_active(unit)
        if state != "active":
            return False, f"stopped running within {secs}s ({state})"
        n = _unit_nrestarts(unit)
        if base is not None and n is not None and n > base:
            return False, f"restarted {n - base} time(s) within {secs}s"
        if comp.get("port"):
            if port_open(comp["port"]) and _http_alive(comp["port"]):
                http_fails = 0
            else:
                http_fails += 1
                if http_fails >= 3:
                    return False, f"stopped answering on port {comp['port']}"
    return True, f"steady for {secs}s"

def _post_install_watch(comp):
    ok, why = _watch_steady(comp)
    if ok:
        log_event(f"{comp['name']}: {why} after the install", "ok")
    else:
        log_event(f"{comp['name']}: {why} after the install -- check it; the previous version "
                  f"is in its library if you want to go back", "err")

def _fu_update_one(comp, row, new_path):
    name = comp["name"]
    target = resolve_installed_target(comp)
    if not script_has_self_uninstall(target):
        return "skipped", "installed file has no --uninstall -- left alone"
    _staged, old_name, _note, stage_err = stage_installed_copy_if_missing(comp)
    if stage_err:
        return "skipped", f"couldn't save a copy of the installed version ({stage_err}) -- left alone"
    old_path = os.path.join(LIB_SUBDIRS[comp["category"]], old_name)
    old_ver, new_ver = row["installed_version"], row["version"]
    _fu_set(in_progress={"category": comp["category"], "name": name, "old_path": old_path,
                         "old_ver": old_ver, "new_ver": new_ver})
    _fu_save()

    _fu_set(current=f"{name}: uninstalling v{old_ver}")
    log_event(f"Full Update: {name}: uninstalling v{old_ver}", "info")
    rc = _fu_run_cli(installed_link(comp), "--uninstall")
    quiet_forget(comp["service"])
    if _fu_stop_ev.is_set():
        ok, state = False, "stopped by you"
    else:
        if rc != 0:
            log_event(f"Full Update: {name}: --uninstall exited {rc}; installing the new file anyway", "warn")
        ok, state = _fu_try_new(comp, row, new_path)
    if ok:
        if row.get("status") == "switch":
            log_event(f"Full Update: {name} switched: {row['note']}", "ok")
            return "updated", row["note"]
        log_event(f"Full Update: {name} updated v{old_ver} -> v{new_ver}", "ok")
        return "updated", f"v{old_ver} -> v{new_ver}"
    return _fu_put_back(comp, old_path, old_ver,
                        "stopped by you" if state == "stopped by you" else f"v{new_ver} failed ({state})")

def _fu_try_new(comp, row, new_path):
    name, new_ver = comp["name"], row["version"]
    _fu_set(current=f"{name}: installing v{new_ver}")
    log_event(f"Full Update: {name}: installing {os.path.basename(new_path)}", "info")
    prepare_install(comp, new_path)
    rc = _fu_run_cli(new_path, "--install")
    if _fu_stop_ev.is_set():
        return False, "stopped by you"
    if rc == 0:
        _fu_set(current=f"{name}: v{new_ver} installed")
        log_event(f"Full Update: {name}: waiting up to {FU_START_TIMEOUT_SEC}s for v{new_ver} to start and answer", "info")
    ok, state = _fu_wait_healthy(comp, f"v{new_ver} to start and answer") if rc == 0 else (False, f"--install exited {rc}")
    if ok and comp["category"] != "instmon" and FU_STABLE_SEC > 0:
        _fu_set(current=f"{name}: v{new_ver} is up")
        log_event(f"Full Update: {name}: v{new_ver} is up; watching it for {FU_STABLE_SEC}s to make sure it stays up "
                  "(the Full Update card counts it down)", "info")
        _fu_wait_begin(FU_STABLE_SEC, f"v{new_ver} to stay up")
        try:
            ok, state = _watch_steady(comp, stop_ev=_fu_stop_ev)
        finally:
            _fu_wait_end()
    return ok, state

def _fu_put_back(comp, old_path, old_ver, reason):
    name = comp["name"]
    log_event(f"Full Update: {name}: {reason} -- putting v{old_ver} back", "err")
    _fu_set(current=f"{name}: rolling back to v{old_ver}")
    prepare_install(comp, old_path)
    rc = _fu_run_cli(old_path, "--install", stoppable=False)
    if rc == 0:
        log_event(f"Full Update: {name}: waiting up to {FU_START_TIMEOUT_SEC}s for v{old_ver} to start and answer", "info")
    ok, state = (_fu_wait_healthy(comp, f"v{old_ver} to start and answer", stoppable=False) if rc == 0
                 else (False, f"--install exited {rc}"))
    if ok:
        log_event(f"Full Update: {name} rolled back to v{old_ver}", "warn")
        return "skipped", f"{reason}; rolled back to v{old_ver}"
    log_event(f"Full Update: {name} NEEDS ATTENTION -- v{old_ver} didn't come back either ({state})", "err")
    return "attention", f"{reason}; putting v{old_ver} back also failed ({state}) -- not running"

def _fu_arm_instmon_guard(old_path):
    comp = next(c for c in COMPONENTS if c["category"] == "instmon")
    check = (f"timeout 5 bash -c '</dev/tcp/127.0.0.1/{PORT}' || "
             f"{{ {_delink_shell(comp)}; {_interp_for(old_path)} {shlex.quote(old_path)} --install; }}")
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
    if not error and _fu_stop_ev.is_set():
        error = "stopped by you"
    _fu_set(running=False, phase="done", current="", error=error, banner=True, stopping=False, in_progress=None)
    _fu_save()
    snap = full_update_snapshot()
    parts = [f"{len(snap['updated'])} updated"]
    if snap["skipped"]:
        parts.append(f"{len(snap['skipped'])} skipped")
    if snap["attention"]:
        parts.append(f"{len(snap['attention'])} NEED ATTENTION")
    if snap["scripts"]:
        parts.append(f"{len(snap['scripts'])} script(s) added to the library")
    if snap.get("manuals"):
        parts.append(f"{len(snap['manuals'])} manual(s) updated")
    level = "err" if (snap["attention"] or error) else ("warn" if snap["skipped"] else "ok")
    for r in snap["skipped"]:
        log_event(f"  skipped {r['name']}: {r['note']}", "warn")
    for r in snap["attention"]:
        log_event(f"  NEEDS ATTENTION {r['name']}: {r['note']}", "err")
    _gh_event("Full Update finished" + (f" ({error})" if error else "") + ": " + ", ".join(parts) + ".", level)
    _fu_refresh_plan()

def _fu_manuals(skipped):
    _fu_set(phase="manuals", current="checking the manuals")
    if not _docs_claim():
        skipped.append({"name": "Manuals", "note": "a Get from GitHub was already running -- left to finish"})
        _fu_set(skipped=list(skipped))
        return
    result = _docs_fetch_bg(skip_deleted=True)
    if result is None:
        with _docs_lock:
            err = _docs_state["error"]
        skipped.append({"name": "Manuals", "note": f"not checked: {err}"})
    else:
        got, _same, failed = result
        if failed:
            skipped.append({"name": "Manuals", "note": f"{', '.join(failed)} not saved (see log)"})
        _fu_set(manuals=[{"name": n, "note": "new or changed on GitHub"} for n in got])
        log_event(f"Full Update: manuals: {_docs_summary(got, _same, failed)}", "warn" if failed else "ok")
    _fu_set(skipped=list(skipped))

def _wifi_menu_homes():
    if WIFI_MENU_HOME_DIR:
        try:
            st = os.stat(WIFI_MENU_HOME_DIR)
        except OSError:
            return []
        return [(os.path.realpath(WIFI_MENU_HOME_DIR), st.st_uid, st.st_gid)]
    out, seen = [], set()
    for p in pwd.getpwall():
        if not 1000 <= p.pw_uid < 60000:
            continue
        if os.path.basename(p.pw_shell or "") in ("", "nologin", "false"):
            continue
        home = os.path.realpath(p.pw_dir or "/")
        if home == "/" or home in seen or not os.path.isdir(home):
            continue
        seen.add(home)
        out.append((home, p.pw_uid, p.pw_gid))
    return out

def _fu_wifi_menu_home(entries):
    entry = next((e for e in entries if e["category"] == "scripts"
                  and is_interactive_only_script(e["name"])
                  and e.get("blob") and e.get("status") != "error"), None)
    if entry is None:
        return
    name = entry["name"]
    lib_path = safe_join(LIB_SUBDIRS["scripts"], name)
    if lib_path is None or _gh_local_blob_id(lib_path) != entry["blob"]:
        log_event(f"Full Update: {name}: the library copy is not the current file -- no copy put in the home folders", "warn")
        return
    stock = {entry["blob"]} | {_gh_local_blob_id(full) for _n, _v, _k, full in _gh_local_files("scripts", entry["glob"])}
    stock.discard(None)
    try:
        with open(lib_path, "rb") as f:
            data = f.read()
    except OSError as exc:
        log_event(f"Full Update: {name}: couldn't read the library copy: {exc}", "warn")
        return
    scan_dir = os.path.realpath(HOME_SCAN_DIR)
    homes = _wifi_menu_homes()
    if not homes:
        where = WIFI_MENU_HOME_DIR or "a login account's home folder"
        log_event(f"Full Update: {name}: no {where} found -- no {WIFI_MENU_HOME_NAME} copy made", "info")
    done, failed = set(), set()
    for home, uid, gid in homes:
        if home == scan_dir:
            log_event(f"Full Update: {name}: {home} is the folder instmon scans for new files -- "
                      f"no {WIFI_MENU_HOME_NAME} copy made there", "info")
            continue
        dest = os.path.join(home, WIFI_MENU_HOME_NAME)
        try:
            dest_blob = _gh_local_blob_id(dest)
            if dest_blob is not None and dest_blob not in stock:
                log_event(f"Full Update: {name}: {dest} has been changed by hand -- left alone", "warn")
                done.add(home)
                continue
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o755)
            if os.geteuid() == 0:
                os.chown(tmp, uid, gid)
            os.replace(tmp, dest)
            done.add(home)
        except OSError as exc:
            failed.add(home)
            log_event(f"Full Update: {name}: couldn't put {WIFI_MENU_HOME_NAME} in {home}: {exc}", "warn")
            try:
                os.unlink(dest + ".tmp")
            except OSError:
                pass
    old_dirs = {scan_dir} | {os.path.realpath(d) for d in WIFI_MENU_OLD_DIRS}
    for d in sorted((done | old_dirs) - failed):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for other in names:
            path = os.path.join(d, other)
            if other == WIFI_MENU_HOME_NAME or not is_interactive_only_script(other):
                continue
            if os.path.isfile(path) and not os.path.islink(path) and _gh_local_blob_id(path) in stock:
                try:
                    os.remove(path)
                except OSError as exc:
                    log_event(f"Full Update: {name}: couldn't remove the old copy {path}: {exc}", "warn")

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
    plan = [r for r in rows if r["status"] in _FU_ACTIONABLE]
    skipped = [{"name": r["name"], "note": r["note"]} for r in rows if r["status"] == "error"]
    _fu_set(skipped=list(skipped))
    if not plan and not scripts:
        log_event("Full Update: every tool is already current", "ok")
        _fu_wifi_menu_home(entries)
        _fu_manuals(skipped)
        _fu_finish()
        return

    done_scripts, staged = [], []
    _fu_set(phase="downloading")
    for row in plan:
        if _fu_stop_ev.is_set():
            break
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
        if _fu_stop_ev.is_set():
            break
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
    _fu_wifi_menu_home(entries)
    if not _fu_stop_ev.is_set():
        _fu_manuals(skipped)
    if not staged or _fu_stop_ev.is_set():
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
        if _fu_stop_ev.is_set():
            skipped.append({"name": comp["name"], "note": "not updated: Full Update was stopped"})
            _fu_set(skipped=list(skipped))
            continue
        _fu_set(phase="updating")
        with _running_installs_lock:
            _running_installs.add(comp["service"])
        try:
            outcome, note = _fu_update_one(comp, row, path)
        finally:
            with _running_installs_lock:
                _running_installs.discard(comp["service"])
            _fu_set(in_progress=None)
            _fu_save()
        {"updated": updated, "skipped": skipped, "attention": attention}[outcome].append(
            {"name": comp["name"], "note": note})
        _fu_set(updated=list(updated), skipped=list(skipped), attention=list(attention))

    if quiet_status()["on"]:
        _fu_set(phase="restoring", current="restarting what was paused")
        quiet_restore()

    if instmon_job is None:
        _fu_finish()
        return
    if _fu_stop_ev.is_set():
        skipped.append({"name": "instmon", "note": "not updated: Full Update was stopped"})
        _fu_set(skipped=list(skipped))
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
    with _fu_lock:
        if _fu_state.get("stopping"):
            stop_now = True
        else:
            _fu_state["phase"] = "instmon"
            stop_now = False
    if stop_now:
        skipped.append({"name": "instmon", "note": "not updated: Full Update was stopped"})
        _fu_set(skipped=list(skipped))
        try:
            subprocess.run(["systemctl", "stop", "instmon-update-guard.timer"],
                           capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        _fu_finish()
        return
    _fu_set(phase="instmon", current=f"instmon: installing v{row['version']}",
            instmon_pending={"from": row["installed_version"], "to": row["version"]})
    _fu_save()
    log_event(f"Full Update: instmon: installing v{row['version']} -- this page reconnects when it restarts", "info")
    prepare_install(comp, path)
    rc = _fu_run_cli(path, "--install", stoppable=False)
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
        _fu_state.update(running=True, phase="starting", current="", error="", banner=False, stopping=False,
                         updated=[], skipped=[], attention=[], scripts=[], manuals=[], instmon_pending=None,
                         in_progress=None)
        _fu_stop_ev.clear()
    threading.Thread(target=_fu_run_bg, daemon=True).start()
    return 200, "Full Update started -- progress shows on the GitHub Updates card and in the log.", "info"

def _fu_refresh_plan():
    with _fu_lock:
        if _fu_state["plan"] is None or _fu_state["running"]:
            return
    full_update_preview()

def full_update_preview():
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
        for key in ("phase", "error", "banner", "updated", "skipped", "attention", "scripts", "manuals", "instmon_pending"):
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
        job = saved.get("in_progress")
        comp = None
        if isinstance(job, dict):
            comp = next((c for c in COMPONENTS if c["category"] == job.get("category")), None)
        if comp is None:
            _fu_finish("instmon restarted in the middle of the update")
            return
        with _fu_lock:
            _fu_state.update(running=True, phase="recovering", current=f"{comp['name']}: checking it after the restart")
        threading.Thread(target=_fu_recover_bg, args=(comp, job), name="fu-recover", daemon=True).start()

def _fu_recover_bg(comp, job):
    try:
        _fu_recover(comp, job)
    except Exception as exc:
        log_event(f"Full Update: recovery error: {exc}", "err")
        _fu_finish(f"instmon restarted in the middle of the update; recovery error: {exc}")

def _fu_recover(comp, job):
    name = comp["name"]
    old_ver, new_ver = str(job.get("old_ver") or "?"), str(job.get("new_ver") or "?")
    log_event(f"Full Update: instmon restarted while it was updating {name} -- checking {name}", "warn")
    with _running_installs_lock:
        _running_installs.add(comp["service"])
    try:
        if _fu_job_active():
            log_event(f"Full Update: {name}: its install step is still running -- waiting for it to finish", "info")
            _fu_set(current=f"{name}: waiting for its install step to finish")
            end = time.monotonic() + SCRIPT_TIMEOUT_SEC + 30
            while _fu_job_active() and time.monotonic() < end:
                time.sleep(2)
        _fu_job_stop()
        target = resolve_installed_target(comp)
        installed = bool(target) and os.path.isfile(target) and os.path.isfile(
            os.path.join(_SYSTEMD_UNIT_DIR, unit_of(comp) + ".service"))
        if installed:
            _fu_set(current=f"{name}: checking that it runs")
            ok, state = _fu_wait_healthy(comp, f"{name} to answer", stoppable=False)
        else:
            ok, state = False, "not installed"
        if ok:
            ver = str(read_installed_version(target) or "?")
            bucket = "updated" if ver == new_ver else "skipped"
            note = (f"v{old_ver} -> v{ver} (finished while instmon restarted)" if bucket == "updated"
                    else f"instmon restarted mid-update; v{ver} is running")
            log_event(f"Full Update: {name}: v{ver} is installed and answering", "ok")
        else:
            old_path = job.get("old_path")
            if not (isinstance(old_path, str) and os.path.isfile(old_path)):
                bucket, note = "attention", f"{state} after instmon restarted, and v{old_ver} isn't in the library to put back"
                log_event(f"Full Update: {name} NEEDS ATTENTION -- {note}", "err")
            else:
                bucket, note = _fu_put_back(comp, old_path, old_ver, f"{state} after instmon restarted")
    finally:
        with _running_installs_lock:
            _running_installs.discard(comp["service"])
    with _fu_lock:
        _fu_state.setdefault(bucket, []).append({"name": name, "note": note})
    if quiet_status()["on"]:
        quiet_restore()
    _fu_finish("instmon restarted in the middle of the update")

def full_update_stop():
    with _fu_lock:
        if not _fu_state["running"]:
            return 409, "Full Update isn't running.", "info"
        if _fu_state["phase"] in _FU_NO_STOP_PHASES:
            return 409, "Full Update can't be stopped at this step -- let it finish.", "warn"
        if _fu_state.get("stopping"):
            return 200, "Full Update is already stopping.", "info"
        _fu_state["stopping"] = True
        current = _fu_state.get("current") or ""
    _fu_stop_ev.set()
    log_event("Full Update: Stop pressed" + (f" during: {current}" if current else "")
              + " -- the tool being updated goes back to the version it had; the rest are skipped", "warn")
    return 200, "Stopping: the tool being updated goes back to the version it had; the rest are skipped.", "warn"

def full_update_dismiss():
    _fu_set(banner=False)
    _fu_save()

def _fu_status_payload():
    snap = full_update_snapshot()
    return {"quiet": quiet_status(), "full_update": snap, "build": build_choice_status(),
            "channel": channel_status()}

_CG_SNAP_RE =re .compile (r'^confgetter_[A-Za-z0-9_.-]+_\d{8}-\d{6}\.md$')
_cg_lock =threading .Lock ()
_cg_state ={"running":False ,"started_at":None }

def cg_snapshots ():
    try :
        names =os .listdir (SNAP_DIR )
    except OSError :
        return []
    out =[]
    for name in names :
        full =cg_snap_path (name )
        if full is None :
            continue
        try :
            st =os .stat (full )
        except OSError :
            continue
        out .append ({
        "name":name ,
        "size":st .st_size ,
        "mtime":datetime .fromtimestamp (st .st_mtime ).strftime ("%Y-%m-%d %H:%M"),
        "mtime_epoch":st .st_mtime ,
        })
    out .sort (key =lambda e :e ["mtime_epoch"],reverse =True )
    return out

def cg_snap_path (name ):
    if not isinstance (name ,str )or not _CG_SNAP_RE .match (name ):
        return None
    full =safe_join (SNAP_DIR ,name )
    if full is None or os .path .islink (os .path .join (SNAP_DIR ,name ))or not os .path .isfile (full ):
        return None
    return full

def confgetter_status ():
    with _cg_lock :
        state =dict (_cg_state )
    installed =os .path .isfile (CONFGETTER_BIN )
    state ["installed"]=installed
    state ["version"]=(read_installed_version (CONFGETTER_BIN )or "?")if installed else None
    state ["snapshots"]=cg_snapshots ()
    return state

def cg_install (name ):
    src =safe_join (LIB_SUBDIRS ["confgetter"],name or "")
    if src is None or not os .path .isfile (src ):
        return 404 ,{"error":f"Not in the Config getter library: {name }"}
    try :
        with open (src ,"rb")as fh :
            data =fh .read ()
    except OSError as exc :
        return 500 ,{"error":f"Could not read {name }: {exc }"}
    if not data .startswith (b"#!")or b"bash"not in data .split (b"\n",1 )[0 ]:
        return 400 ,{"error":f"{name } does not start with a bash #! line"}
    err =check_bash_syntax (src )
    if err :
        return 400 ,{"error":f"{name } failed the syntax check: {err }"}
    folder =os .path .dirname (CONFGETTER_BIN )
    try :
        os .makedirs (folder ,exist_ok =True )
        fd ,tmp =tempfile .mkstemp (prefix =".confgetter.",suffix =".tmp",dir =folder )
        try :
            with os .fdopen (fd ,"wb")as fh :
                fh .write (data )
                fh .flush ()
                os .fchmod (fh .fileno (),0o755 )
                os .fsync (fh .fileno ())
            os .replace (tmp ,CONFGETTER_BIN )
        except BaseException :
            try :
                os .unlink (tmp )
            except OSError :
                pass
            raise
    except OSError as exc :
        return 500 ,{"error":f"Could not install {name }: {exc }"}
    with _file_meta_cache_lock :
        _file_meta_cache .clear ()
    ver =read_installed_version (CONFGETTER_BIN )or "?"
    log_event (f"Config getter: installed {name } (v{ver }) as {CONFGETTER_BIN }","ok")
    return 200 ,{"message":f"Installed {name } (v{ver }). Press Run to take a snapshot.","level":"ok"}

def cg_uninstall ():
    with _cg_lock :
        if _cg_state ["running"]:
            return 409 ,{"error":"Config getter is running -- wait for it to finish."}
    if not os .path .lexists (CONFGETTER_BIN ):
        return 404 ,{"error":"Config getter is not installed."}
    try :
        os .remove (CONFGETTER_BIN )
    except OSError as exc :
        return 500 ,{"error":f"Could not remove {CONFGETTER_BIN }: {exc }"}
    log_event (f"Config getter: removed {CONFGETTER_BIN } (snapshots and library files kept)","info")
    return 200 ,{"message":"Config getter uninstalled. Its snapshots and library files are kept.","level":"info"}

def cg_delete (name ):
    full =cg_snap_path (name )
    if full is None :
        return 404 ,{"error":"No such snapshot"}
    try :
        os .remove (full )
    except OSError as exc :
        return 500 ,{"error":f"Could not delete {name }: {exc }"}
    log_event (f"Config getter: deleted snapshot {name }","info")
    return 200 ,{"message":f"Deleted {name }.","level":"info"}

def _cg_run_bg ():
    log_event ("Config getter: taking a config snapshot","info")
    try :
        proc =subprocess .Popen (
        ["bash",CONFGETTER_BIN ,"--out",SNAP_DIR ,"--keep",str (CONFGETTER_KEEP )],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,
        text =True ,bufsize =1 ,
        )
        for line in proc .stdout :
            log_event (line .rstrip ("\n"),"info")
        proc .wait (timeout =SCRIPT_TIMEOUT_SEC )
        if proc .returncode ==0 :
            log_event ("Config getter: snapshot done -- download it from the Config getter card","ok")
        else :
            log_event (f"Config getter: exited {proc .returncode }","err")
    except subprocess .TimeoutExpired :
        proc .kill ()
        log_event (f"Config getter: timed out after {SCRIPT_TIMEOUT_SEC }s","err")
    except Exception as exc :
        log_event (f"Config getter failed: {exc }","err")
    finally :
        with _cg_lock :
            _cg_state ["running"]=False

def cg_start_run ():
    if not os .path .isfile (CONFGETTER_BIN ):
        return 409 ,{"error":"Config getter is not installed -- press Install on it in its library first."}
    with _cg_lock :
        if _cg_state ["running"]:
            return 409 ,{"error":"Config getter is already running."}
        _cg_state ["running"]=True
        _cg_state ["started_at"]=datetime .now ().strftime ("%Y-%m-%d %H:%M")
    try :
        os .makedirs (SNAP_DIR ,mode =0o700 ,exist_ok =True )
        threading .Thread (target =_cg_run_bg ,daemon =True ).start ()
    except Exception as exc :
        with _cg_lock :
            _cg_state ["running"]=False
        return 500 ,{"error":f"Could not start Config getter: {exc }"}
    return 200 ,{"message":"Config getter started -- the Execution Log shows its progress.","level":"info"}

_CP_EDITED_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.md$")
_CP_TAG_RE = re.compile(r"^<redacted:[0-9a-f]{8}>$")
_CP_BACKUP_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
_cp_lock = threading.Lock()

def cp_edited_path(name):
    if not isinstance(name, str) or not _CP_EDITED_RE.match(name):
        return None
    full = safe_join(EDITED_DIR, name)
    if full is None or os.path.islink(os.path.join(EDITED_DIR, name)) or not os.path.isfile(full):
        return None
    return full

def cp_edited_list():
    try:
        names = os.listdir(EDITED_DIR)
    except OSError:
        return []
    out = []
    for name in names:
        full = cp_edited_path(name)
        if full is None:
            continue
        try:
            st = os.stat(full)
        except OSError:
            continue
        out.append({"name": name, "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "mtime_epoch": st.st_mtime})
    out.sort(key=lambda e: e["mtime_epoch"], reverse=True)
    return out

def cp_resolve(sel):
    if not isinstance(sel, str) or ":" not in sel:
        return None, ""
    kind, name = sel.split(":", 1)
    if kind == "snapshot":
        return cg_snap_path(name), name
    if kind == "edited":
        return cp_edited_path(name), name
    return None, ""

def cp_last_backup():
    try:
        ids = sorted(n for n in os.listdir(PUT_BACKUP_DIR) if _CP_BACKUP_RE.match(n))
    except OSError:
        return None
    for bid in reversed(ids):
        try:
            with open(os.path.join(PUT_BACKUP_DIR, bid, "manifest.json"), encoding="utf-8") as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        return {"id": bid, "created": m.get("created", ""), "files": len(m.get("files", {})),
                "undone": bool(m.get("undone"))}
    return None

def confputter_status():
    installed = os.path.isfile(CONFPUTTER_BIN)
    return {"installed": installed,
            "version": (read_installed_version(CONFPUTTER_BIN) or "?") if installed else None,
            "running": _cp_lock.locked(),
            "snapshots": cg_snapshots()[:15],
            "edited": cp_edited_list(),
            "last_backup": cp_last_backup()}

def cp_install(name):
    src = safe_join(LIB_SUBDIRS["confputter"], name or "")
    if src is None or not os.path.isfile(src):
        return 404, {"error": f"Not in the Config putter library: {name}"}
    try:
        with open(src, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return 500, {"error": f"Could not read {name}: {exc}"}
    first = data.split(b"\n", 1)[0]
    if not first.startswith(b"#!") or b"python" not in first:
        return 400, {"error": f"{name} does not start with a python #! line"}
    if not read_installed_version(src):
        return 400, {"error": f"{name} has no VERSION line"}
    err = check_python_syntax(src)
    if err:
        return 400, {"error": f"{name} failed the syntax check: {err}"}
    folder = os.path.dirname(CONFPUTTER_BIN)
    try:
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".confputter.", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fchmod(fh.fileno(), 0o755)
                os.fsync(fh.fileno())
            os.replace(tmp, CONFPUTTER_BIN)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        return 500, {"error": f"Could not install {name}: {exc}"}
    with _file_meta_cache_lock:
        _file_meta_cache.clear()
    ver = read_installed_version(CONFPUTTER_BIN) or "?"
    log_event(f"Config putter: installed {name} (v{ver}) as {CONFPUTTER_BIN}", "ok")
    return 200, {"message": f"Installed {name} (v{ver}). Pick a snapshot and press Preview.", "level": "ok"}

def cp_uninstall():
    if _cp_lock.locked():
        return 409, {"error": "Config putter is running -- wait for it to finish."}
    if not os.path.lexists(CONFPUTTER_BIN):
        return 404, {"error": "Config putter is not installed."}
    try:
        os.remove(CONFPUTTER_BIN)
    except OSError as exc:
        return 500, {"error": f"Could not remove {CONFPUTTER_BIN}: {exc}"}
    log_event(f"Config putter: removed {CONFPUTTER_BIN} (snapshots and backups kept)", "info")
    return 200, {"message": "Config putter uninstalled. Snapshots, uploaded copies and backups are kept.", "level": "info"}

def cp_run(args, secrets=None):
    if not os.path.isfile(CONFPUTTER_BIN):
        return 409, {"error": "Config putter is not installed -- press Install on it in its library first."}
    if not _cp_lock.acquire(blocking=False):
        return 409, {"error": "Config putter is already running."}
    sec_path = None
    try:
        cmd = ["python3", CONFPUTTER_BIN, "--json"] + args
        if secrets:
            fd, sec_path = tempfile.mkstemp(prefix="confputter_", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(secrets, fh)
            cmd += ["--secrets-file", sec_path]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CP_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            return 504, {"error": "Config putter took too long and was stopped."}
        except OSError as exc:
            return 500, {"error": f"Could not run Config putter: {exc}"}
        try:
            res = json.loads(proc.stdout)
        except ValueError:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            return 500, {"error": "Config putter gave no result: " + " | ".join(tail)}
        return 200, res
    finally:
        if sec_path:
            try:
                os.unlink(sec_path)
            except OSError:
                pass
        _cp_lock.release()

def cp_preview(body):
    path, name = cp_resolve(body.get("snapshot"))
    if path is None:
        return 404, {"error": "No such snapshot"}
    args = ["--preview", "--snapshot", path]
    if body.get("keep_comments") is False:
        args.append("--no-keep-comments")
    status, res = cp_run(args)
    if status != 200:
        return status, res
    if not res.get("ok"):
        return 400, {"error": res.get("error", "The snapshot could not be read.")}
    log_event(f"Config putter: previewed {name}", "info")
    return 200, {"plan": res, "message": "Preview ready -- nothing was changed.", "level": "info"}

def cp_apply(body):
    if body.get("confirm") is not True:
        return 400, {"error": "This action requires confirm:true in the request body"}
    path, name = cp_resolve(body.get("snapshot"))
    if path is None:
        return 404, {"error": "No such snapshot"}
    only = body.get("only")
    if (not isinstance(only, list) or not 1 <= len(only) <= 400
            or not all(isinstance(p, str) and p.startswith("/") and len(p) < 300 for p in only)):
        return 400, {"error": "Tick at least one file."}
    secrets = body.get("secrets") or {}
    if not isinstance(secrets, dict) or len(secrets) > 200:
        return 400, {"error": "The secret values are not valid."}
    for tag, value in secrets.items():
        if (not isinstance(tag, str) or not _CP_TAG_RE.match(tag) or not isinstance(value, str)
                or len(value) > 500 or any(c in value for c in "\r\n\0")):
            return 400, {"error": "A secret value is too long, has a line break in it, or is not for a known tag."}
    args = ["--apply", "--snapshot", path]
    for p in only:
        args += ["--only", p]
    if body.get("keep_comments") is False:
        args.append("--no-keep-comments")
    status, res = cp_run(args, secrets or None)
    if status != 200:
        return status, res
    if res.get("error") and not res.get("written"):
        return 400, {"error": res["error"]}
    level = "ok" if res.get("ok") else "err"
    log_event(f"Config putter: wrote {len(res.get('written', []))} file(s) from {name}; backup {res.get('backup', '-')}", level)
    for bad in res.get("failed", []):
        log_event(f"Config putter: could not write {bad.get('path')}: {bad.get('error')}", "err")
    return 200, {"result": res, "message": res.get("message") or "Done.", "level": level}

def cp_undo(body):
    if body.get("confirm") is not True:
        return 400, {"error": "This action requires confirm:true in the request body"}
    status, res = cp_run(["--undo"])
    if status != 200:
        return status, res
    if not res.get("ok"):
        return 400, {"error": res.get("error", "Nothing to undo.")}
    log_event(f"Config putter: undid backup {res.get('backup')} ({len(res.get('restored', []))} file(s) put back)", "ok")
    return 200, {"result": res, "message": f"Undid backup {res.get('backup')}.", "level": "ok"}

def cp_delete_edited(name):
    full = cp_edited_path(name)
    if full is None:
        return 404, {"error": "No such uploaded copy"}
    try:
        os.remove(full)
    except OSError as exc:
        return 500, {"error": f"Could not delete {name}: {exc}"}
    log_event(f"Config putter: deleted uploaded copy {name}", "info")
    return 200, {"message": f"Deleted {name}.", "level": "info"}

def cp_save_upload(name, data):
    name = os.path.basename(name or "")
    if not _CP_EDITED_RE.match(name):
        return 400, {"error": "The file name may use letters, digits, . _ - and must end in .md"}
    if not data or len(data) > CP_MAX_UPLOAD:
        return 400, {"error": f"The file is empty or larger than {CP_MAX_UPLOAD // 1000000} MB"}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return 400, {"error": "The file is not text"}
    if not any(ln.startswith("# Node config snapshot:") for ln in text.split("\n", 40)[:40]):
        return 400, {"error": "This is not a Config getter snapshot (no '# Node config snapshot:' heading)."}
    try:
        os.makedirs(EDITED_DIR, mode=0o700, exist_ok=True)
        os.chmod(EDITED_DIR, 0o700)
        fd, tmp = tempfile.mkstemp(prefix=".up.", suffix=".tmp", dir=EDITED_DIR)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, os.path.join(EDITED_DIR, name))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        return 500, {"error": f"Could not save {name}: {exc}"}
    log_event(f"Config putter: uploaded copy {name} ({human_size(len(data))})", "ok")
    return 200, {"name": name, "message": f"Uploaded {name}. Pick it in the list and press Preview.", "level": "ok"}

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
    prepare_install (comp ,script_path )
    try :
        proc =subprocess .Popen (
        [_interp_for (script_path ),script_path ,"--install"],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,
        text =True ,bufsize =1 ,env =_cli_env (),
        )
        for line in proc .stdout :
            log_event (line .rstrip ("\n"),"info")
        proc .wait (timeout =SCRIPT_TIMEOUT_SEC )
        if proc .returncode ==0 :
            log_event (f"Install finished OK: {script_name } ({comp ['name']})","ok")
            quiet_forget (comp ["service"])
            if comp ["category"]!="instmon"and FU_STABLE_SEC >0 :
                threading .Thread (target =_post_install_watch ,args =(comp ,),daemon =True ).start ()
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

    script_path =installed_link (comp )
    log_event (f"Uninstalling {comp ['name']} -- running its own --uninstall...","info")
    try :
        proc =subprocess .Popen (
        [_interp_for (script_path ),script_path ,"--uninstall"],
        stdout =subprocess .PIPE ,stderr =subprocess .STDOUT ,
        text =True ,bufsize =1 ,env =_cli_env (),
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

def render_app_card_html (app ):
    if not app :
        return ""
    files =app .get ("files")or []
    latest =app .get ("latest")or {}
    cur =files [0 ]if files else None 
    busy =app .get ("phase")=="fetching"
    if cur is None :
        badge ,bcls ="NOT DOWNLOADED","b-src"
    elif latest .get ("version")and _app_vkey (latest ["version"])>_app_vkey (cur ["version"]):
        badge ,bcls =f"NEWER ON GITHUB: {latest ['version']}","b-src"
    else :
        badge ,bcls ="IN LIBRARY","b-inst"
    if busy :
        note ="Getting Node Talker Mobile from GitHub..."
    elif app .get ("phase")=="error":
        note ="Last fetch failed: "+str (app .get ("error")or "?")
    elif app .get ("msg"):
        note =(f"{app ['checked_at']}: "if app .get ("checked_at")else "")+app ["msg"]
    elif cur is None :
        note ="No app file yet. It downloads when instmon can reach GitHub -- press Check to try now."
    else :
        note =""
    ver =f'<span class="ver">v{esc (cur ["version"])}</span>'if cur else ""
    dis =" disabled"if busy else ""
    dl_btn =""
    del_btn =""
    if cur :
        name =esc (cur ["name"])
        dl_btn =(f'<a class="btn b-go" href="/api/app/file?name={urllib .parse .quote (cur ["name"])}&amp;download=1" '
        f'download="{name }">Download APK</a>')
        del_btn =f'<button class="b-del" data-action="app_delete" data-name="{name }"{dis }>Delete</button>'
    size =f' &middot; {human_size (cur ["size"])}'if cur else ""
    return f"""
  <div class="card" id="app-card">
    <div class="row comp-row">
      <b>Node Talker Mobile</b>
      {ver }
      <span class="badge {bcls }">{esc (badge )}</span>
      <span class="muted small">Android app{size } &middot; kept in the library, not installed on the Pi</span>
    </div>
    <div class="row btn-row">
      {dl_btn }
      <button data-action="app_fetch"{dis }>Check GitHub</button>
      {del_btn }
    </div>
    <div class="small muted">{esc (note )}</div>
    <div class="small muted">On the phone: open this page, log in and tap Download APK. Android asks once to allow
    installs from the browser, then installs the app. Updates install over the old one.</div>
  </div>"""

def render_confgetter_card_html (cg ,library =None ):
    if cg is None :
        return ""
    running =cg .get ("running")
    installed =cg .get ("installed")
    if running :
        badge ,bcls ="RUNNING","b-inst"
    elif installed :
        badge ,bcls ="INSTALLED","b-inst"
    else :
        badge ,bcls ="NOT INSTALLED","b-src"
    ver =f'<span class="ver">v{esc (cg ["version"])}</span>'if installed else ""
    run_dis =""if installed and not running else " disabled"
    run_title =(' title="Install it from its library below first"'if not installed else
    (' title="Already running"'if running else ""))
    un_btn =(f'<button class="b-del" data-action="cg_uninstall"{" disabled"if running else ""}>Uninstall</button>'
    if installed else "")
    snaps =cg .get ("snapshots")or []
    rows =[]
    for sn in snaps :
        name =esc (sn ["name"])
        rows .append (f"""
    <div class="librow">
      <div class="librow-top"><span>{name }</span></div>
      <div class="librow-actions">
        <a class="btn b-go" href="/api/confgetter/file?name={urllib .parse .quote (sn ["name"])}" download="{name }">Download</a>
        <button class="b-del" data-action="cg_delete" data-name="{name }">Delete</button>
      </div>
      <div class="librow-bot small muted"><span>{esc (sn ['mtime'])}</span><span>&middot;</span><span>{esc (human_size (sn ['size']))}</span></div>
    </div>""")
    if not rows :
        rows .append ('<div class="small muted" style="padding:.4rem .2rem">-- no snapshots yet --</div>')
    nested =""
    if library is not None :
        nested =render_library_group_html ("Library","confgetter",library .get ("confgetter",[]),"install_confgetter",nested =True )
    return f"""
  <div class="card" id="cg-card">
    <div class="row comp-row">
      <b>Config getter</b>
      {ver }
      <span class="badge {bcls }">{badge }</span>
      <span class="muted small">confgetter.sh &middot; runs on demand, no service</span>
    </div>
    <div class="row btn-row">
      <button class="b-start" data-action="cg_run"{run_dis }{run_title }>Run</button>
      {un_btn }
    </div>
    <div class="small muted">Copies the node's config files (ASL3, DVSwitch, USRP2M17, firewall, 44Net Connect) into one Markdown
    file for Claude. Passwords, keys and tokens are replaced with &lt;redacted:...&gt; on the node; secret files are never copied.
    The newest {CONFGETTER_KEEP } snapshots are kept.</div>
    <div class="card libgrp-nested">
      <div class="libgrp-hdr"><b>Snapshots ({len (snaps )})</b></div>
      <div class="librows">{''.join (rows )}</div>
    </div>
    {nested }
  </div>"""

def render_components_html (components ,library =None ,app =None ,cg =None ):
    cards =[]
    for c in components :
        if c ["category"]in NO_CARD_CATEGORIES :
            continue 
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
                lib_entries =[e for e in library .get (c ["category"],[])
                if e .get ("installed")is True or not _build_other (c ["category"],e .get ("version"),e .get ("name",""))]
                nested_lib_html =render_library_group_html (
                title ,c ["category"],lib_entries ,action_label ,nested =True ,
                )

        cards .append (f"""
  <div class="card">
    <div class="row comp-row">
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
    cards .append (render_app_card_html (app ))
    cards .append (render_confgetter_card_html (cg ,library ))
    return "".join (cards )

def render_library_group_html (title ,category ,entries ,action_label ,nested =False ):
    rows =[]
    locked_names =_locks_read ().get (category ,set ())
    for e in entries :

        name =esc (e ["name"])
        is_locked =e ["name"]in locked_names 
        lock_html =(f'<label class="lib-lock small" title="Locked: this file can\'t be deleted or overwritten. Uncheck to unlock (asks first).">'
        f'<input type="checkbox" class="lib-lock-cb" data-category="{category }" data-name="{name }"{" checked"if is_locked else ""}> Lock</label>')
        del_btn =(f'<button class="b-del" data-action="delete" data-category="{category }" data-name="{name }" disabled title="Locked -- uncheck Lock to delete">Delete</button>'
        if is_locked else 
        f'<button class="b-del" data-action="delete" data-category="{category }" data-name="{name }">Delete</button>')

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
        {del_btn }
        {lock_html }
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
    if category =="config":
        live =live_configs ()
        if live :
            rows .append ('<div class="librow libgrp-upload"><span class="small muted">Copy the active config into the library:</span>'
            +''.join (f'<button data-action="save_alternate" data-name="{esc (n )}">Save {esc (n )}</button>'for n in live )
            +'</div>')
    card_cls ="card libgrp libgrp-nested collapsed"if nested else "card libgrp collapsed"
    upload_html =f"""
    <div class="librow libgrp-upload libgrp-upload-top">
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
    {upload_html }
    {''.join (rows )}
    </div>
  </div>"""

_LIBRARY_GROUPS: list [tuple [str ,str ,str ]]=[
    ("Dashboard","dashboard","install"),
    ("SysMon","sysmon","install"),
    ("wifimon","wifimon","install"),
    ("44helper","44helper","install"),
    ("Node Talker","nodelisten","install"),
    ("Watchdog","watchdog","install"),
    ("instmon","instmon","install"),
    ("Scripts (.sh)","scripts","run_script"),
    ("Configuration","config","install_config"),
    ("Config getter","confgetter","install_confgetter"),
    ("Config putter","confputter","install_confputter"),
]

_LIBRARY_GROUPS_BY_CATEGORY: dict [str ,tuple [str ,str ,str ]]={
    category :(title ,category ,action_label )
    for title ,category ,action_label in _LIBRARY_GROUPS
    if category in INSTALLABLE_CATEGORIES and category not in NO_CARD_CATEGORIES 
}

_ORPHAN_LIBRARY_GROUPS: list [tuple [str ,str ,str ]]=[
    (title ,category ,action_label )
    for title ,category ,action_label in _LIBRARY_GROUPS
    if (category not in INSTALLABLE_CATEGORIES or category in NO_CARD_CATEGORIES )and category !="confgetter"
]

_RTF_UP =0x0001
_RTF_GATEWAY =0x0002
_RTF_REJECT =0x0200
ROUTER_PROBE_TIMEOUT =1.5
ROUTER_PROBE_TTL =30.0
_ROUTER_SCHEMES =(("http",80),("https",443))

def _route_hex_to_ip(value):
    return socket.inet_ntoa(struct.pack("=L", int(value, 16)))

def parse_default_gateway(route_text):
    defaults = []
    connected = []
    for line in (route_text or "").splitlines():
        cols = line.split()
        if len(cols) < 8:
            continue
        try:
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
    return "".join (
    render_library_group_html (title ,category ,library [category ],action_label )
    for title ,category ,action_label in _ORPHAN_LIBRARY_GROUPS 
    )

_CSS_BASE = """@font-face{font-family:"Readex Pro";font-style:normal;font-weight:400;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2")}
@font-face{font-family:"Readex Pro";font-style:normal;font-weight:700;font-display:swap;src:url(data:font/woff2;base64,d09GMgABAAAAAC8EABAAAAAAZgwAAC6kAAE0ewAAAAAAAAAAAAAAAAAAAAAAAAAAGoEAG7JWHIYsBmA/U1RBVEAAg2wRCAr5SN8hATYCJAOHaAuDfAAEIAWEFgcgDAcb1VWjoqz2ppjBcR42Dh6G22YUJZRzqOw/HHBDBvSJr0SENNWA0/FS21vVOrY1VBsiq4rXRpewDA8/JyHOzI9XxI9jP/GS6iy1IzQ5RSsP9fvxO3vf+ypAE5Fk6lEt6nSiVkswnelUEt5JYvsDP7feH2OwDdjYRmyDZcCCkaMWRWzkkHJEhIpK23kqBnaAlacYfWHcWad3Z51eev7vN9cnFeDkziDv0GLeNZOXm7Qza0X0udDf6S/mvuCF5Yn/Qz7vzPvNth7voC2JLabQamoFaUZNQx6iynNpa1RWtFTU2tK2TE/LTNCKMiVDJZoG0SAWxBaxHMO+LJLn2JP8EbNbsPQbKWn1CwV2khK+AQWoZA6bq9Y+pCLaJu6n7NSB2Wz7fSh2Q7RlTcmW7f0EZCbgxP+zabYz3ux78vGGUMrLIfWAVbjlppr9u97R7EQn2Tra1YGkQ+lAYLNyMLfy4wDbCZcAIJ0uL7IDSBWWANDnpelTNenapOc2RdekqMIDufxledAVg5ArkVF4rMqGGkpV+2k6tL6aUoXDKITu9vQJder8r2nT/x6l7zx6UagVLhO1kuJMZqmbT3chFF2rcDlUJOfcaRCKQaIM47Eh5jzy7MterLgiiwyxO99eK/c4Q1NCMA/jBaFpRghhRDDCu67P7RqbC+Y6sAmjAAPeuL0pBNAOzAQKDIQRwswOkSYLIkcHRKcuKO99gvDhLhBLCC0DFOEGAR2MQQmGeyYqIeV6het8D2lfacaFjx+0kojmtmRZciZQvmwuqwHKd0Wt9UCBBsymjNNHm+vBE6jBi4IZ9GthT268mmff7IC4xO68P/lvnonRnw+ZC7OujzKWHyoKd6GeKFodpbp0lYUd7ZXe+NjHo74b6Uj6+dzr+MNhQesSKKw9qVVONaXaePadS1fAf+i/X3iiOReii9Q6v66uG+ullzmNOEzQ1Ynryqbe63U3AnRtaU6HEgjhAbTAieXFe8colB0jeP7FC13w/OdsUkRycnRqEYJEScCmQyhmkkoiJ1TLVSFMVajTqJ1e57+0GbZZkh32SrHfARlGjMpywilO51yQ65oxBTzsnXJg0uEZR9mx1fOLa/wdyv6B4yNujqM4R+QCETf+YzwfSJ7Ew6WDJxRsHFw8fAJCktFuDm/CUcceu2vTEY417vzLtHQsbevkENpwJm/m6PbMjvXWyE3zil+3w9mBYtfIblR0gLZ3XuY9MrJDGOF6esTiNZ4DE83+aZBk5M7YDuTPLbeTh8bg4vWlhhIZSxO5Ng7GZrgheclUFuJYeiHmBdmFTv0NEtX80WkMiAOzcAZTXxPytbU3YjEyPHDYoGxOJP6kzKRffdiox9Nsnh6EtDCg7EXJFILVuCWJTwojMe+5BwuWaXUcBzuh7QpjaggGCfPVrubdUkJS1XFnElxdPs0H5Tw26ngYzCE+p5NZxzgmW81pIirySWoOwzYrfELETuMAHV9kxCk5LEQzirlBc4fhsUefYhq9Rr3vZ7ab5pOqKw7gNC+HzKcSFEVRFJXaT6JGGIoEGZkbNHcYHhUuAX6eotoYbMkcwsXDJyAkqaJnxNCKFSdeAj0DYzHtlRnZAlY2SVIUKDSeS5FiJco/qpxVtVjjQqcdGVxwa0LBxsHFwycgJAnl09QDYVX4ZkVU0cBsc8w1z3wLLLbE0nDZKszACiutsjrcRqsA2Ge/Aw465LBjH51crnGZ5oVBbkdMe1bG02lXieDSwhNKoQ+wJXOAi4dPQEhSRQ/F0IoVJ14CPQMjEzMLK5ukdspKsjEUaC6E8VyKFCvJpVFVhqD8pASSBq7Do0yOAoQQQggf4/hvLdEM+kOavr3ZZLIHc6PqvAf6Nn2aeD07KpmeLNEDMUwrVpx4CfQMjEzMLKxskiYHG4AILkWKlSgf7QlJDcUNmjsMjz36BNSESLOu4Ml3YBb1IDORQ9NY46wmLVq1/WeEFzQQSBCIYG58gD5gAFDa0YAG7as6DpHjAEhCGY+trTxaDHIdGBzKBdgm3wGDltYI8JMireV3OTqG/U347D0neacV8ODurtFZON1YRVZ/Wd4Pd3fGptKG7amzw/kZBwGYoHhiaWqq4mbHvlV2oKbJmTIsCMazanNsF2Un7amf2lmwy9EGixneQOq7wtne7LSn7WCnsSu4Ce3ZEM5Yk/Ky97rxVDBNz1xlDqk5FJ/xj9NLVZjDMSLA0e5ElxrTx2QbnM5XHJXjlZdces/5zmcHwZw97+DKp+F/NGS2ElDUgUVzKWGJVXkmR07LyIuhjLsVQ5oOShu1/mYnLrRQT+iwB+eSQxgkkoCS2YSt0SuNfV/0ThmATQ6sOnoUtLlMUsnwowXfzU2Dtxr6F4ue2lcZaJivkpOmEyNbmF14yTeKtuXbjiBOBrHrZn7bM6ENzlNQKnFEncMm3kuSmzxTH1xaRwMG7xKOLd31YbWHAAFLYMTgVrZzELu2rQU0+Fjn4wdCvZbq09NZuGUrv/l/4djC4b61QtPf6rweyw5LoCZJwoI3orc+L+KbHpXJefkbi2j6Jem2Uj1ajkcaBsRWyQrDLB02ibTc2HH1XW48Phc4H14f9UWwQhBDq1ZIYzaHKdFyXQE3h1oRCNsz3YVG3Tc4bijSGE5902NbUJyvHWePEe3RVLTA9AQKGliwRSIoETiTjVE/vinOr2WofEXGZVMkjmM5n+Doi1+0ZUkm01mPCr32dRVAuEj+sZrNbmCzAotPf6r145dkrbuoAJ/LqDfvm8vm75HG7bCnT2O6dXEC+f+DoUVMBIB2f3xZ4HRS/n6ivdkITMqKAWmcWnsw9pgnR/IHVhmzjn4pQONGpRs3qm/9Ag+BBdpRYNEFI2FL4EfHTiNNNr0cXayGbVbvhFManXVWi/MuaIWihfDgxpMnNCwsPi/eED5I0MjIBCgoAtDR4QUJwhKslU8IISLGJrm/jQgpyWTEkduBQqi4U1MojHQaWyRcBB+R9BdFPJ2NomdAZWQwk40wS4KRTK4U0qTSk93GSpMFK5tecsg07owgV358t0AZlHJQrIIUlfRWRZRq20+NBh4aKdXEIM22TIs2RO301UEvneSaQC8TSTCJWF1KcBgcMISXgDwXLiRQwnwGGoFvUXDw3HgRUJkbP1JUUr87RV3DDSi4AQUsCMCADl8EwWs+SbQEiHjmSRA/gW8keg/FP4xT7554nJVAlN7JUJZ6OtkOgQdwwMMH7mCBDDa8lfIj/gxvmMi0WYMdQ0BGdQ5K8w1UoaWePn0zSBAKaKDPsFwu1RpN1G3YDpre56pbP/LEC38EBQiyqbr16NWn36DpZ5Ttd2AXTu5+a8xDTzyFeDqA0jdyEg5i/xBKz8jgqH4IsLrnjqEvCAMSpo3j4c3+iJjCU8/zu6czjKmabBArVnQwkYyHA0tw8wXOjGNg5vE5mer50udJ1Y06KJiY/0JQeNDAdHFQ36AcB/f+zs46D1nEzWM5CsZ5oNXNcyBAAVEU87rVo7T+QmXs4+aiYgZS1Z3MY+EuI0vcq8TMhY5X6YPFbyfmDra+l2w4GHyNDS5/nZ70dBvIwF390A2+NjDvo+/j3eMx8R7xnvFYwf3d6/DhukawfVbfUAeOf/ztC8j+rqqiCFzfNZTUQvmOWjSjE1PQ/3DmD211zTBfUAEEr9X0VJ9aiQkIPICCGzBAw/0lji8e21v9QrOdcSMYeOYDzhFG8mNmC6gn9wKFJFAym6Sr9CSzn46DMHIMdwOnduijMiaPUrRDFJR+kQ7JfokSIA2GqbbsRyb3h8iu7gqEBK/CR9CiWUuBMQCP4u5jjQiObM/P6v0NpEBxqumJEUgGOdyERB0g6DpFrMOaJYLy57PPsBCocAZlkdW8BgAenrn7J9TMIBwiE7j5yScmzzidUGxSV+y6dB/uTTJ0aS+j3EG50xxgdbro2EeVeOv4N0EFLAD/f85twjqsRyS3V2skUL+o1GZhpa+jwFBuEFMKCsCORhZesTTHgSAAF76sbEWGqBQxE5TwB6QQRH8718CrVhCCrKDjQWggYqh+mqGiTPG1jcKisYJZHJaAQ/oagKEUoq17QGYFsoIwtp4VH37/lv54MvdJ/6MrgPAHpjsG4rz199QT231rnwdeGnPVqOP2+t5mhw3bb4utnnrsiZ2uQWDhePFBRuHHH12QYAxMbCISUjJyIdTCaISLdMoBpz034oNoOnpGZslSpLLLlmOcXHkKlCpXoVK1Go2aNGvR7oQ7TvrZJjvc89B937nrhvdumuyiZ4645Q+3/WSNtT564brdPvnGFJesN2SDXdzn0X9sNAxPeCQERL5oAgSi8sbCx8ElxPMjAZVQCkoRxKrEiaGVIFa8RAZJLKxssqRJl8EkX5FC45VweaRYg1p16rUq0+a8C85AIBkQAP4B4jeIJoCut2DAU4D6Nqi6ASgJUQi3Rq0Hiqqqv4gMXUMAqKCJEpRLJcWl16YjGikCbCIre02N4kh2UtXvxRf9TUY0YXqAQpe2cxXkjKhtRLZMG6GNe9jEO8qntGEDo4xPgUatYLjJbnrGiCHTmnsvrSPeUTRH7wXlPozhcCkqwfIoD7B0dopdSmSyxc9uo5DRFPXGB8FrPTScC/AP4WDe1VFCYhNDI4gs6o5B9BTZ0KLgYLSXBRT44BWnY4hENFhAJZHlH6V6zRkRQAxAW0IUf5WoEFkjiUe8hJu83ESATrS58dFJaExAYrQXNkbxWiJoxa7cWExbRAxHQ8PAQIcDh7PbPQ3mfP1VAp0iFlEYFF9i1oLg4Lk8XlnUPTq7LCUK7dUCuMYPx/l7xphwEDHQ66a+rglW6Ba/y6O0ITWQw7SypK4q8tByqaIj3CmkiiwviASp2z2higRzSjZYVS/aJ+D9yMFMbjmZAC+gnmCIMVrck3bqmc9zGxj9qGdgkC1ygndhZsBtH4F29jerlU+fj2EL9MVEE/CebF/aYf4L9eC5A8aO6VQlSVKjpZAwqeSxEN0ZLBrdaKqTmEqa7qb0BKNQoVx5YEF8vkDemFMws4UNE8Qx6OZUpGydDS6YdNMgln+OSZEFvzDH1UyZAW9GLOby6cbCqGeQZ5xMO7ePyCo142IdPqA08OJyH9Si2lpSMFopr9iX7Pl3C3kF2Me3v2M2HVXGSh9jZOR0nicZU+J1AOLrCcoF/W2mzEiNOeGadGXGAbVbLmR4Pm/bTj1C29CQY4lPTQ4Qv6PsfFULkT86mLKIdmKAXRqjQQQWCSRTM5jyFxut4jb/U493Rc0FV2lcWRnB1pr9cTpkwwdXGNXakqurPirVVanXRiSvurDqw118x7QUp6plgisjMAudutBBNSes1E+xdGkCmoUKDSL5ViVehmfOjP1xMV/RKOmTUXJXuRUAPvpZDSU3yzeCdzIehR13HxLCaihdeVT57B6ind5iid1QbJ15fCA3hHJdFlpmJdMLNvZJW9rcpUxmBdPFcrD1uV5A4oFbfw0UmzXl3EOUb1AZAlx5g5eNh4I0IV1kOx6FE5D0RW1MRpx3w1uYSCmJ1n0yFprHugmiDu8ePJWLaxZpXq0m5DOJ/HKES7sfH+2VrR4WQBCs2ScdjvAih11IXWXM+NN0z74qW1mq9VOaUnIXFaDKm9HRzojzTkUfm09LPQBWb8H56lft5GFmTzKWbFQtJbjC+NOxTX4wrtRzA++FODuTUHhf1Cxnzoe+v/039AtJIbW0Fwj1nhuTy8H4MngPszGOgBV/LksrOGdIWABrdvkxhCTU4Qyx1ecLRR5mk2tYAR3lLxKIafVu7CVUnlgozQH0B9PFa+A2XyiZrq+wxoGcbWSK2caT1cS4beNFTUVRhRe38JtKS3KLi6nnzatxcQgfbSuKfs+O8LbxGDOsggIi3lZYXxhER1rhs7LbOB6VjXYP0GB5cJFuDtvLUdDoBWaUfVU2cz72cu4XZVKAaz9hAEAkWE0bc/RQxd2n+dHzOrx7M8ecJ+s7sm1KCA0QXYE68tr1ooDRID2YvAwS0jjQLKIMHGmxKkzjKgi01c2DLHgTo6fys3Xpha9rzIyISG7VFURD2ogVDMaRdLAaSityIcHyadCICdkO5qMEgrG2opuIFv156YFXayuvc6ESoFzUOVuFzu2NaiC57pVUqp7hN4tbrwweG6hWdB5VofUmKod9V07qEezwWqGRw0JXSdzjT5vbrb7TDDmqTronwcY7eqdoUV1c81TzoL0wP/wq5KFCVcyu1lWV81uXog9d+2gd7bx+OfagX+TU7CRxbKO6MwF2/UyFMdywHzm541yjax2liEpUoMyTo/nEc62TE0kpDtuph4lih4tu2rtA9OuHn0cB0DhelY01eEkoyG+FnnVGMASQ24vdulVZulxJAwIRC1rKdzF6grUM8o8Z8dFIlXzTSY7f4kfLWwCwCHjwUxhDzdI+nvdnOdsneGAIi0KYfiMt5qT2zrXY6lL48JxLRddwkmh6PvLgYtFcYhM7iKuwjqziZI+0VIRXYInsYZYH2Rc2J5CKZu473h1/hQVHW7LEAXhHvZ1o1rqcUsD5aPFORrvXaycdJqoSTNI9nBHiUgyfxpsmbjrT+mHRrQTrcTSPaLBFs3BgryzTH/O03OrrFjyLk3EBrS2NqwDA4EKVn4J1XaZwIUOFxGQB3C6RU+TChupHeJdKg8h/Y22z/Bv+cP8Ff0qqkrsVQjCI7xRsib5uFUUUXzpZUMjide9ewpsHVHrmFxkCw4AKKjZw9tIv5zS8wPPj0QsohifV8wrbAWO6MnZRLqKNY/rsAgAGpsd7jf4qQZjFH4AUQq1+DFH9dOPYpwX2nZE7sFVp9YmmutT3aW8LkgWVyGNR8sloIZFk6eBU7lh3GNmB5FzHqY5q1BEdYV+Oo/TGHHaCs8TnoJxgULRqQ/+6cvh8DVf6x/B8XLEYMGHBzrt14yDxVkzhvjotqojh2gVjjxX5zs4RvM3+ZMgwuHDXcxjPRZJgHVwuAvONTrop1cKsyKQlTQxP2s/uEE3XTZBHQ2Y3bQukoA3EVwzmjMSPmiFzYuDIn/VYgo9w2rPAv4Cg7jy1pd0e4vU3hiPT2x7CFsi9Q+mFVbM0Zgq5VECAKkkhkdEWm3xmLIxQuzIWMNR561lGxgylB11Lm6DVR3/wQzOYPtzbSJtmTTTz/nF6yqyieNIrJ2lJxriQKBY2ekMjB0nDfHYrBnnd2U5v5c7Y2H/AfUpv+NTuTnAdXbrQQIrmgXqMvsiqWxn1ghO8DETtPKISnrvYRgM7ipohZsDLYjx8cX2hcTMtqxiBf0DCODiaSt3k7pVmtjO1yzW4mTLjk8hC/PktY9xFPek4eEedRNGI5jR1snrvliKNpEo3cafSNPxE3UE4+ZFiWjPkKGqaDFgFPEWxB22F04EiaSTmw/U0+kKhQSYdmS6mSSdawVT7tLf/Qmwd05XzhlNkT8qCPMjWFIiqSxRUcdz5j2G+Apl58IQB0Rl7pfnHCWI8T0j8eE9+KwFfC/DNoylDn0sOLVbMcTzPaBxNleoZLspTCq3KYRRWZOsfRaKp9xacIeaQwBcfxHTFl7282hA7ZLkRE+o8n4GghhgJ3XA9u4msHMP/NwIoIwtIIzv6i0sJHx8bTuU8/hoo+lzcAU1PgqYHPF+O+M0xz6BNpy0wz3k9B583sDtgWSsbnKPh1mKROjkiJtregL5iUPEtIRqeXReWS41YM3e55CU/oGFt8KKeyTRFiB9rv6wdFmPt/WEuV1i/PTW8r6RoUGNXjaemq25Xtj9N5oeKTHRNsDU0JMhWmkwPZXYzyel9E9OlpYHgHBWmTFXl5Su7U1KVU/Pyp6hSJ7U55ogT6c8CLXJ5oOVZIl08fy5w2Z2GTiKbMb9z9NXCxOXJC4eCZ9fMdrwqt4/m4ufVzqsJXLZ4GazCZg5qiorUfampEX2lRTM1GVHlwZnqPZV1ynRBmNTCqAxOlsuZSdOTmDKmrruWRks7Oc1K80PhDIrGnLQOGeBGt48W3guXE1ZeXgm2+e2r2+cvWz+F4I4V6IiNY78WlUmIweRAUwQ1vmfJoiW16WpO2sMMJty9Kp0/ruDbjhHe9ABUVnOx80jRLH7ksteKFV9W1wDu5uLR4Tv5ngtxJu4piWFUxMfrPOeW3iE9GQ0f3CqwLlSVcfPw6KrJCKbWwx5JZLyAJVh7v8bl0vTbUzngKlIirj6N5kR9hHKkrBPrg/l0q1TGXsFwi8WGYME3mixakZuphpmsT8k3DKHmkzE8POdoqK4iJqZcp4+pqYjV9b9Guhv8eVmB1Ayuf0P5KhoGSHJFZGCibz0qoX4i1kNZPb5qstOj3IpN/x/qWENNVFxpoi6uokZrWPnpp73aXYHnszdOnEUrN9Po0y4wuyAeWznXotJVtCp0JXINfedMMuHlAsYM/apMwSDdJE+wjO/QmMq7EixV5S9ThdLg49Vkosh3tKU6h/sHxxRiMZZN0sBb/tiy1GV3+TDF3TloSumy79mxWUBfz+Xvkwo2D++xJ3cNmCA4YGTfgOsE4dKRKmbvp6iX3a5dgSPw4NbIrqqGeXhdJ8FVNmHfjErKjHLKnte9Ij1JHhTXXllRv/3WSO/wAvbyefDxfqR/743bYbTBc7jJ0x3XZB/001LOiC+Ad4GLNu/MPXU26pTiuM9KH0M5aJvb3kXplq4mNjW/Hz22FIpN4gsi4dU94/PfTYqw6ouEmrT4Mh5W5RCGmBTiH7fkUGKGPEsX+30u3OBD+LSdRHti30g3J24wBMP3WHW6MNSkEP92eRw55sJKv4Ali+nC+qNSiTDRylNxW14aq38xciwEnrPbYJroiBWUm2yFokhrozG+E5LB7vfKvplAeLmTRH9i36jOsOtCHIFFSBb5SpGnn7DWNb6gcGJkkiKZUh2UKGuDASwvgeyQmqWenUt/Wp+Cy6FzbrON1ebYLodDO6nKVDvI0z2SSMfSebz0R1LJo3QIxaZMNBu7Uh3GronmFHO7ip5ddSrvMVWw8ItQ4LWIRztufZ9dRZ2gAiLWUGuMhfCDrzUbeTo/IzO6Mnvo2VLPjk8B/+kSyah+vu6xVPZYx+eJSyb9LQARJrndqO+wakQFRnOuWKVKFYUlLS5kCqjpjFR5t6L8bXVkRlpMJaPL6tT1t9tSprNU3/N53ylZLOVDPv97VUuPl261cOVCFknXRD0CemxOr9E00R4nLLdYi0UxkXlCvZlbhMUPB+TGIJTAjZvoovqjUikv0cRVsjNe2qrk+utEhCp5mCw9TRnO/9wnb73QgSNN2kxiptHEuZMH8wch6nlCN29yRNMnR6BM/eWNPOduYZmdKbM06RLaUx0JkxqMpuDalyktbKx7x4qXiYIym7GKF18u7PlNLP2tV8hv/k0i+a0JzM/WxuI3zLRzZdo0hchlNg5FsajqdX7aLY8p2jSaGBzkIbJ9UohExI+Vyw6WHBI8dw4CbsZOMpgsr4eIFlVhkRzdkhqCe2MHy+VUYfC/qQ2kcKy+i/BkVeSEz/9dSkjPhp5dOPK2yeluBjN+psFEXoEen7bV+TqOJnr5/IeWuvuD9BRqfIZS7DLrhyJC64V+sumPKTFDkfJ5fAoKgDl//N1rils3HpveY7J22dOYiJWe0Y1daXbU/WNmBq/kC8bz/2Iet+WLWPilBTq4OuU1tl6J8aDv0vT92xWY1lfjS9NYIYYqo5bqoWknVZsMIWmcjsbUwpZcXuKYWDKm4/HTf5SKH6Udlp1ab8YiKWb7KpNRPrCzMaWwWeYV3fp9XoDIO+wPjrHWFNtlT+Ni1Sa9QE/J9KYa3btWvCWf56Zd0wV1DuL4qwmz4+Zljd4mFJOeHZDs2WSh+Kdufx6IBWKTOxTRRRm/pwRxvTWvp+Ao2NY1Hm8M7Cy1nqWMto4XRcpSyQbulsxC+O4GhVD6egoWv25p/3XrrzqWBn6lqSNTi2WwAyv5a3lcXewxIsPKFXQkCmdnW+7wp/sw5vOF3eKPaz6aoqrqolMSSoRRNg1r10cmyZGeGJIXo410FUVeb5+5fCa0rBha8f/AnLI58C82OkMlK9RbhhTKFxK/oOk3Kdoh8jL32m83zkphw5sfSXv7ppdOm7PnFxKM7CRtLcrOqMMWtuKairK2HiC1t9BPN1FhbuM2tfkm83TdhvDk6+yYu6Ks8rrT619klVeeOw4zn3fSkQxQHGrA934Nqy38bUYR9fATUu5zUBUGlqqpfUeKPPO0fn0wc5BfHZwUFsI2XxJGhsaq9W3RbVZF8PkEbC71FZt7L8jvYnDg/mK4ME2ZJJaYQ0IlliSJMjRJIrOGhEjNNrEqi3aMzTlCC/iOxbkMdmxhX5ZxXVMTE2leiP/VWDA/wdBQUWNoSkgwNtVUGBvgtlLDz1hsDF56sahusUC5bNsyiGVnXPqRNFXXQKZ4w+q/LPXjZKM12VmhXBdXrI7OjaX/wkrQWKtXbqHY8pdBMDZrsikse1JK4i8cetCDUQaz8y7bR5AXwSvefOQhG71g15cXn+ubw4khaex/ufZQk6muIw7y1DmoP0Pqrs2hGfqKts86A1SMvTtuVV7ZHANTwqIeD2KM4Zj+5fveW4ok6oULEjYzv9vIrHzL1FdotdUmo6G+LQH44YUCk0GYpyHQ8pVFAa7131gH76zg2xjml0zLI50pSyiKKY6Lroiz6dpb9JbZTPw+VtDpLwxW0B4Gc58XHIGT5Km1Sy77pGEaQIwyt4YbC2KEsY0L846kFv7Ai4jLqlYm6qqVcVkRvJGC7v7vjWphijrGWNiqsQwGHRwIpA4OB9MOLaUGLjlIVVHTHX7+joxAaobD38+RDtejvh85cc1odopEUePjosq1VkNrmyFJU8A36YTZKi7eEGjmpNY7d2Q2MF/vDGaufcNkXJnHou26CtewymSlNDsiSuxMVqhVNoXYGRUhyU5ShpbTTonEp2lBT8WiJ9AMHI8D8vRWg7Mu2jsYtN6ZZY7XV+II3mM+5OR7yeG/JymU0cb4EFFN1x5T4KE82I0Vv2PJUqkSsv8BX0JvgPfBO/Wzxk8cynuIzWjLzF7S5hGyJZSX/Qj4a225tkMR7xcQV15J8plQeWM3OW3//Wr4xpNh9nMpUumz/AM2kXyX+BOFKY+pO1/m799Gm3b2590MzmSEGZtrhhOepuzCtFhxfopGw/2pWGr9zurDKyZGJXoYY8WRhgSVcFwiS5RGWk72nUCiLPclzwCt56AId6L0DS9xQAQncWIDo5fJ3TOT9U8tM8QeqxX9amcyo+Rg2cdlNusZohTKZbLvUYrfYTL5KGUNqZVIHPQll/kS+2HIk3urWWr9R0LktvhE6f0N8ZIIg04prDKwpIb0wnStOD9ZI7xHme5L6aQQl1N8OwF9a2TR7RGYihOPSUU/CcWPZCIE9kuvej3IuEXeLqCwbnEZb7cI2FMPL4fy/+cQerG9MdZtVi22n9A7U4UVP5IKP/Js5j3sSbMJfdgebZhC7J3Y40dZ6WPpk756x+qxvPp9C40S85VM+8B/k9b4LlmTy1IbXRp1frQyND3X+NW4MiT6IBSPyURPsfQRWHibnclaAmmMtynh41hhhqK9qULTelyX5voRdtwVPEsRCFOf8Sv8LFUoSHkGG13eA0hXRljegMZjIEaTNyWfRZje4jPnU0eeJn9aDHYwTJPblvWOMAANHSNzO0auLe7N7WUuxk/P0M7ecb3gPodGtq2lfrTB+urAn4XrqGQhqO8uylkEEd/NfDLziFRFhSd7C3uBdXRC0tSfZ8/qfibd5mblxeceq6nOHc2Lg+Kj4+zukeqa3BHyu0HzokHttegkFjMgQQKFqhPdom5J9zdqKEx3FVb6cZol0zBcJCPamGIjEWwUY0oUksFyG5SB9hqKv21M++fePkmZHztiOB1RSWyC1HDKk93ibultFoD9+ETx9CXOKatWTAfZ8cuDF0+EhbsYhEsC5uyDF6MeLOCS8c8uN4aSmbfBtP3V/DDSz34PmpgP9hyP+fWSgzXnwGE4Qtv1xGvnz3nxHUeRziPQE5Qf34lI+5HceK8uLPvJHhszPGwL2lQOm/nLZjjTA66hnBlhLpdqML09/dii3jOGBvtUWV6GotlkFEwyFhVEhAuOMpm+LGTxV5U+kSuSm0PFmREKXklihlMdxnz3gP9b0MKF0TERfUT6C46OnK1Iiq/qiMwu3xDZWhO7qtTAr7ZZawUmhc7rcibfsDOTYcKTkmiIMCFEiKNcnUthhgTbpKxhMJpsBxesqlAb/73tHx6ZUapIVDlZCTGXptg86+h+P/xNoXzGoX2tDkPs2m3nsaldWkt5vC2zNZNRUjyrXcZ+d0UqNDDzOOm6pfOktXpnVmwFCz7H/BIXnqlRjI9NjHCVagwrR4cXKROfpUTNgtweQdoGh7/v5u+zgn6Yj78qDg1NLg2xK9IoCcKJGbkDr45RODUBhEhlRQbDSrfYA4JCE7P40/wUOQEW8czU8QfsTKZgApXQ1lyZFWykmeyREqk+U7yen1X09k8C+TXdGKBODZElKpWhjtIQmOGbPBBRUho5kJISOSBkrE5O6Y8orQkRqhuzLsaliSyIiWKv6/Sk8PSBLxRVrhgCtS0zgJrVSvXtilfWPDf5abJiq2QOh6wqNg4Bh10HiY2tlNntgbhYBFIdNieg3piadbpGo0HfIHfWqM4R6PX8cWpDYmODTp+oSg9VpKvVlJquUIVlKpRK8GRmhmYmcHP0xPCqH95OFDxkc3HcyO+Kei5wvV5jcd/hhS8BOz00SSK1yEI4bJMoFJQkschlUqvkDnH5zv+PRHqzztd33a/y4P7bDWmnNi3fBBmXZ66auZI3Y9UMSEixd5lNXakOJjDtX5EgJ65x7fMeNGiDkHp83NMHRetUTk6pG1jeWzqxrGBNZi0E1sUUqDTOyEhNDsyYgnPegM581U1lSYkzt7i84oestJLi7MzEN34fSP4BpI9+lI+kAH/Shx2bcrKLysbl5J0rLs4bX1IM8djiubHi9N7qytCooG9mkgkvFson6pMJZdEKZ8xXtTeRPaCOsLZPKBaGX6EdE4z7WTTbgbuRxsLvJuzMYOPWVMOxsGTKSa6ZQ16PXXXwRCLRFFvWGJlkrgyZ1VnwcQM96MisIGZQ1xAxMZBRablXzTGRjGepThLbSE6IajpWztAw/95lYtADXDfNlYzx7OMG11bXV64rxB22/fB43XRZ94MVngjhxQJ4odvb+7kX+D9P/3M6zFZXVLoKKsuriguKKioKx4PkfN/XvnhM7y+nUcuW0IJay2iB5YO0JfT+Miq1/J07Tw8sGwCdofdV78sHPa96oMo7cUrWfnPWvq/kvh+LYYd3byXltzlhSsY+c8Z+0Gn6/uz7FNv/Z795dObymTD5MrGzAPMCfxFLjme0jLeVp/pWF7449+1mnG9CYDMSz8z8Dn6ouv3qw2xbOOArv2vpe9iyYV2gA9lIA9vQwTVhbHo4zS9k2y2/8DXkJeiSh9xfNqZ5Gb/TnHV/ClvGRpbeHnFZ1HaVzBkVKXOmKsPCUpRSZ1SEPCdFpawgZh0JCjqSRSS2XwySnBIfVTlUcmdElMxpV4WpU1TvRVRFnXJi9hG6ZEFgvXOXgsSnoblR8qNI8FUk/kHMf0KVXKMd3ookVzPh77YQmogvl+9FwGz+ts5auXc2bDeFWhtZk6ElfcG8btfjrbhgcSYD/s5mNZCZLPcGNrvBncV0a2DZiQYfXwORaCASDKAdT5TWByd5EMJF43BRcQ6NL67hYQPeRxSeg3cb84P0zvLUclj2CWvzu/wT3qvOn+BlrEuX6cLJAsa4hxYsnO+lI2LuaYlsh4h3ilHQaLEb4HzzU0pk240WWPmGZy9PUXgbtL8TT6/Om1ZNXWAKhr/Xcfea2dyoM1zePiuXbd7LTfdt9yWTuD9xMP9PmT0hoAPn40Yu1VuSIkniVZ8rsd53oERITxDAUjODfCYEGeoySgVc1y9myb9MASAwAANVXQyLXQgny4sfpg2Cu+cBPxBwv+UjWChJDvMbYwUqLviXigOGdBeCyQRlKvU0CMpeFhYY1cSrAxYmKD0NIkIWFvwvJLxHwwvgeyvcdm8ZQCro4REIgY6SibWjbkj0DQaUhSnG2C7AEW/zsNvBoecbDlvmRSLWIGoG4QkqXDhKuhQcW1YEFr3bpA95bV6CgpKaIGoOjI6o1AE1JbVA1ByY2yQMLUZjJwFZ8RYGxJGO7uMzEHKGAzR54ypck6u55MwCGOOR5ezHLzLO0x42rmXcHhRMKDNAHBAznTTLnsXZizn2meugeQ6Z74gFDjxeKFE++bn8yHpGiDyeUUVg3UcAwVlyDbyUvL/VnAztPnu1uLb4hR8fM2sYYgYZBnHGVpsvQPFNq2sYHhP8TVqV70Dhmc314h1Hk1FDSjFw+Ao63+yEct6/BNYv80a5AAj4Kynlsj9Zo8D1Vlf8xa9cS6+k19Ib6e1z+Q7Mv/P09Tjy9MPpP31w45b3X2DIep9iul92A64ClDdnT5KXtrIao3VXc0nXYlrbK5ygrIr0LC/1r75O2EB8BFKQwRXfaAIOfydlcb9Cz3IRgYip8GQs71Y9y0tnrk6zl1mN2cYX/YQEu+TL4cleMlfmy6bRAYavxUQsoz9Xfniyl8xN5iOB6IwG2TmIjYN93QRxIEkJfD+JWAD+7JB5cZlzoIUXSkGWvWSuzFcAFrLoooPsJXMJYu7ZiqqM9JTKRVo3ymDT6aAa0xewuB5wOCD92wrKXQXKmbvGS3a0lQdoqfSidwmSHzYAVj+qY6gpiEY8VHZyQl+u4WRcpJWHhCmNiF4nTlZklfuR5Qw78tOyy4tDJ8j62KQYL6sTdSg4oBrUu7LDwgnB/vlOdIxk7H6DxdMD/5Th/ute24r64n72jSOxIY/XLq7dpol2LwujqGZfis/6CLMtz/qbwOzInb6FQy8e+RVfcEX5nbRNceUE66olOismYfMbiSGjE2Koj81dC61AhQAx88fOBbXoI0H7f4Cb2yvA+2fVLgA+/3XX9rX9y7719cUABAYKIMDfiRCPBK7//aBBXK+rH7UQ9SjYNllPXdrjnD1Iuu1w0OA8dF4HOFm17/EG6fHqKGUDbsixVcR9Qaw4w+pZFu27hNTmk+TyLs3iZVDwqfd7Ev/Ow+5/Mjb3Ve7Vi7HK2YX2Lfswbae9uMDWcILNdaaP1YXMZePguThzMkkpmYXeNZTZxZxECeEAIpXunG0CK5NDbuw+WgzSFuYooucME1+D/deNAxbYAhDpx8mlzz1vkboWPfP4tU8iuMfzrnQqEqTWcYf8AqoWIh1/9ItsRsbSXkXHXrcZ5Ju5mF1HVDVzeehN4d8lyM3AaiJ2pRTNJmqC4CzHCxcttQQpwcty1DRipxMnNsJMJU49NmcqOQKdp4VZP9E4J4yGdvBPPIiB8WEBsodH0u9stcS0Y6mCtPRS5uLmEN/+ILRpMMXCz9IxyHbkhLCcE12HyLNBZHcRZZAwA7CxjRAeWoY5uFyH/TfH/hUYsiBy3irhigo/0XBMcHcfkfiX9JwjOjhQ9Qtp47D9fQj5h0ehKIlWenQyqxJShaBOotBklDFMzRJaPUGG8bW+tPX0JYCILUmnwCPH7Jp0B68yVZJGBJhA+KF8Fc/Ct/BSvNnzIH+QSl3WFhmUby4wTpt2BhTSmgMB/in+K13sKay8ruu3mckNUmN1m1egP4JiX38UTxf6u1EZ64/GCPR3RwtjD4ygRA6HALRHZn8EGHE1o8g9hYg/n5hCr0GjCZpVqVCpFYuKglIUlkyVyoSld6VIKes0CYdmDYlVO7ykxUrURlalBo+1WEWk0mrV2K1oofdQhSqycJtiIUo0qBOqABdPkRa2d1uiRpV6oZo1eeNd22IbTDdY7RxSCjGeqhEjlZ07G8WAfueXs527ogTOhj5Yle1QjyWdvRx2Gk7GLSZoFFDBjR0sKlIvxgz4gZUr0qZWKzcAKams6a/ztf9PmwMA) format("woff2")}
:root{
  --bg:#0d1117;--surface:#161e2e;--surface2:#1e2a3f;
  --border:#2e4060;--border2:#3a5278;
  --amber:#ffd040;--amber-dim:#6b4800;
  --green:#00ffb0;--green-dim:#005538;
  --red:#ff3d5a;--red-dim:#6b0e20;
  --blue:#22d4ff;--blue-dim:#083a58;
  --purple:#d466ff;--purple-dim:#52087a;
  --teal:#00ffe5;--teal-dim:#004840;
  --orange:#ffaa22;--orange-dim:#703800;
  --lime:#d4ff00;--lime-dim:#425200;
  --pink:#ff44cc;--pink-dim:#700050;
  --fcs:#00c4a0;--fcs-dim:#004840;
  --text:#ffffff;--text-bright:#f0f8ff;--muted:#ffffff;
  --sans:"Readex Pro",Arial,Helvetica,sans-serif;
  --mono:ui-monospace,Menlo,Consolas,"DejaVu Sans Mono",monospace;
  --fs-xs:.66rem;--fs-sm:.72rem;--fs-base:.8rem;--fs-md:.9rem;--fs-lg:1rem;--fs-logo:1.21rem;
  --red2:#ff3d5a;
  --panel:var(--surface);
  --line:var(--border2);
  --fg:var(--text);
  --cyn:var(--blue);
  --grn:var(--green);
  --yel:var(--amber);
}
button,input,select{font-family:var(--sans)}
textarea,pre,code{font-family:var(--mono)!important}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);
  font-size:var(--fs-md);line-height:1.5;min-height:100vh;padding-bottom:2.5rem}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
"""

_CSS_LAYOUT = """
/* ── Title bar ── */
header{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);
  border-bottom:2px solid var(--amber);padding:.45rem 1rem;
  display:flex;align-items:center;justify-content:space-between;gap:.5rem;
  position:sticky;top:0;z-index:100;
  box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
.hdr-left{display:flex;flex-direction:column;min-width:0}
.hdr-right{display:flex;flex-direction:column;align-items:flex-end;flex-shrink:0;white-space:nowrap}
.logo{font-family:var(--sans);font-size:var(--fs-logo);font-weight:700;color:var(--amber);
  letter-spacing:.1em;text-shadow:0 0 10px rgba(255,208,64,.9),0 0 30px rgba(255,208,64,.5),0 0 60px rgba(255,208,64,.2)}
.logo-sub{font-size:var(--fs-xs);letter-spacing:.22em;text-transform:uppercase;color:var(--amber);margin-top:.1rem}
.hdr-meta{font-family:var(--sans);font-size:var(--fs-xs);color:#ffffff;letter-spacing:.04em;margin-top:.15rem}

/* ── Layout ── */
.wrap{max-width:860px;margin:0 auto;padding:1rem;display:flex;flex-direction:column;gap:.55rem}
.hdr{color:#ffffff;font-family:var(--sans);font-weight:700;font-size:var(--fs-sm);
  letter-spacing:.24em;text-transform:uppercase;margin:1.2rem 0 .45rem;
  padding-bottom:.25rem;border-bottom:1px solid var(--border)}
"""

_CSS_COMPONENTS = """.card{background:var(--surface);border:1px solid var(--border2);border-radius:0 6px 6px 6px;
  padding:.7rem .9rem;margin-bottom:.6rem;box-shadow:0 4px 20px rgba(0,0,0,.35)}
.row{display:flex;flex-wrap:wrap;gap:.4rem .9rem;align-items:center}
.badge{font-family:var(--sans);font-size:var(--fs-xs);padding:.08rem .5rem;border-radius:4px;
  border:1px solid;font-weight:700;letter-spacing:.05em;text-transform:uppercase}
.b-inst{color:var(--grn);border-color:var(--green-dim);background:rgba(0,255,176,.07);text-shadow:0 0 8px rgba(0,255,176,.4)}
.b-src{color:var(--muted);border-color:var(--border2)}
.b-run{color:var(--grn);border-color:var(--green-dim);background:rgba(0,255,176,.07);text-shadow:0 0 8px rgba(0,255,176,.4)}
.b-stop{color:var(--red);border-color:var(--red-dim);background:rgba(255,61,90,.08);text-shadow:0 0 8px rgba(255,61,90,.4)}
.b-start{color:var(--grn);border-color:var(--green-dim);background:rgba(0,255,176,.07);text-shadow:0 0 8px rgba(0,255,176,.4)}
button,a.btn{font-family:var(--sans);font-size:var(--fs-base);font-weight:700;letter-spacing:.04em;
  text-transform:uppercase;background:transparent;color:var(--cyn);
  border:1px solid var(--blue-dim);border-radius:4px;padding:.32rem .85rem;cursor:pointer;
  transition:all .14s}
button:hover,a.btn:hover{filter:brightness(1.5);box-shadow:0 0 10px currentColor}
a.btn{display:inline-block;text-decoration:none;line-height:normal}
.doc-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto;gap:.3rem .5rem;align-items:center;margin-top:.35rem}
.doc-row .doc-name{overflow-wrap:anywhere}
.doc-row .doc-meta{display:block}
@media (max-width:600px){.doc-row{grid-template-columns:repeat(3,auto);justify-content:start}.doc-row .doc-name{grid-column:1/-1}}
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
.small{font-size:var(--fs-sm)}
.btn-row{margin-top:.5rem;padding-top:.5rem;border-top:1px solid var(--border)}
.no-confirm-banner{font-family:var(--sans);font-size:var(--fs-sm);font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;color:var(--red);border:1px solid var(--red-dim);border-radius:4px;
  background:rgba(255,61,90,.08);padding:.35rem .7rem;margin-bottom:.6rem;text-shadow:0 0 8px rgba(255,61,90,.4)}
"""

_CSS_LIBRARY = """.libgrp{margin-bottom:.9rem}
.libgrp-hdr{display:flex;align-items:center;justify-content:space-between;gap:.6rem;margin-bottom:.3rem;color:var(--cyn)}
.libgrp.collapsed .librows{display:none}
.lib-toggle{font-size:var(--fs-sm);padding:.2rem .6rem}
.librow{display:flex;flex-direction:column;gap:.25rem;
  padding:.55rem .7rem;border-bottom:1px solid var(--border);transition:background .1s}
.librow:last-child{border-bottom:none}
.librow:hover{background:var(--surface2)}
.librow-top{display:flex;flex-wrap:wrap;gap:.4rem .9rem;align-items:center}
.librow-actions{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
.lib-lock{display:inline-flex;gap:.3rem;align-items:center;cursor:pointer;margin-left:.2rem}
.lib-lock input{margin:0}
.librow-bot{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center}
.ver{font-family:var(--sans);color:var(--yel);font-weight:700;min-width:5.5rem;text-shadow:0 0 6px rgba(255,208,64,.35)}
input[type=file]{color:var(--muted);font-size:var(--fs-base);max-width:100%}
/* Library card nested inside its component's card (see
   render_components_html's nested_lib_html): indented as a subordinate
   block rather than a full sibling card, so it doesn't read as a
   second independent card boxed inside the first one. */
.libgrp-nested{margin:1.3rem 0 0 1.1rem;background:var(--bg);
  border:1px solid var(--border);border-left:2px solid var(--border2);
  border-radius:0 4px 4px 0;padding:.5rem .6rem .1rem}
.libgrp-nested .libgrp-hdr{font-size:var(--fs-md)}
/* Per-category upload row appended inside each library group's .librows
   (replaces the old standalone global "Upload" card). Dashed top border
   sets it apart from the real version entries above it, since it's an
   action row rather than a library entry. */
.libgrp-upload{flex-direction:row;flex-wrap:wrap;align-items:center;gap:.5rem;
  border-top:1px dashed var(--border2);border-bottom:none;padding-top:.6rem}
.libgrp-upload input[type=file]{flex:1;min-width:8rem}
.libgrp-upload-top{border-top:none;border-bottom:1px dashed var(--border2);padding-top:.55rem;padding-bottom:.6rem}
/* GitHub status rows: sit between a library group's header and its
   rows so they stay visible while the group is collapsed. */
.gh-rows{display:flex;flex-direction:column;gap:.3rem;margin:.1rem 0 .4rem}
.gh-row{display:flex;flex-wrap:wrap;gap:.35rem .6rem;align-items:center;font-size:var(--fs-base)}
.gh-tag{font-family:var(--sans);font-size:var(--fs-sm);padding:.1rem .45rem;border-radius:3px;border:1px solid var(--border2);color:var(--muted)}
.gh-tag.gh-upd{color:var(--grn);border-color:var(--grn)}
.gh-tag.gh-warn{color:var(--yel);border-color:var(--yel)}
.gh-tag.gh-err{color:var(--red);border-color:var(--red-dim)}
.gh-row button{font-size:var(--fs-sm);padding:.2rem .6rem}
.librow-top>span,.gh-row>span,.comp-row>span{min-width:0;overflow-wrap:anywhere}
@media(min-width:561px){
.comp-row{display:grid;grid-template-columns:7rem 9.5rem 6rem minmax(0,1fr);gap:.2rem .9rem;align-items:center}
.comp-row .ver{min-width:0}
.comp-row>:nth-child(5){grid-column:4;grid-row:2}
.librow-top{display:grid;grid-template-columns:10rem minmax(0,1fr) 6rem;gap:.4rem .9rem;align-items:center}
.librow-top .ver{min-width:0}
.gh-row{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1.2fr) minmax(0,5.5rem) minmax(0,4.8rem);gap:.2rem .6rem;align-items:center}
.gh-row>:nth-child(3){grid-column:1/-1;grid-row:2}
.gh-row>:nth-child(4){grid-column:3;grid-row:1}
.gh-row>:nth-child(5){grid-column:4;grid-row:1}
.comp-row .badge,.librow-top .badge,.gh-row .gh-tag{justify-self:start}
.gh-row>:nth-child(5){justify-self:end}
}
@media(max-width:560px){.gh-row>span:empty{display:none}}
/* v2.37.0 Quiet System + Full Update */
.fu-banner{border:1px solid var(--amber-dim);background:rgba(255,208,64,.08);color:var(--yel);
  border-radius:6px;padding:.55rem .8rem;margin-bottom:.6rem;display:flex;flex-wrap:wrap;
  gap:.4rem .9rem;align-items:center;font-family:var(--sans);font-size:var(--fs-base)}
.fu-banner.ok{border-color:var(--green-dim);background:rgba(0,255,176,.06);color:var(--grn)}
.fu-banner.err{border-color:var(--red-dim);background:rgba(255,61,90,.08);color:var(--red)}
.fu-banner ul{margin:.2rem 0 0 1.1rem;color:var(--fg)}
.fu-table{width:100%;border-collapse:collapse;margin-top:.45rem;font-size:var(--fs-base)}
.fu-table td{padding:.22rem .4rem;border-top:1px solid var(--border)}
#fu-progress{font-family:var(--sans);font-size:var(--fs-base);color:var(--cyn);margin-top:.35rem}
"""

_CSS_LOG = """#log{background:#070b10;border:1px solid var(--border2);border-radius:0 6px 6px 6px;
  padding:.6rem .8rem;margin-top:.5rem;white-space:pre-wrap;
  font-family:var(--mono);font-size:var(--fs-base);max-height:450px;overflow:auto;display:block;
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
  padding:1rem 1.6rem; font-family:var(--sans); font-size:var(--fs-md); line-height:1.4;
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
  font-family:var(--sans); font-size:var(--fs-md);
  color:var(--cyn); letter-spacing:.08em;
  text-shadow:0 0 8px rgba(34,212,255,.4);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
#uf-close{
  font-family:var(--sans); font-size:var(--fs-md); color:var(--fg);
  cursor:pointer; padding:.15rem .55rem; border:1px solid var(--border2);
  border-radius:3px; transition:all .14s;
}
#uf-toolbar{
  display:flex; align-items:center; gap:.4rem;
  padding:.38rem 1rem; background:#131c2d;
  border-bottom:1px solid var(--border); flex-shrink:0;
}
#uf-path{
  font-family:var(--sans); font-size:var(--fs-sm); color:var(--fg);
  flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
#uf-textarea{
  flex:1; background:#0a1020; color:#ffffff;
  font-family:var(--sans); font-size:var(--fs-base); line-height:1.65;
  border:none; outline:none; padding:.8rem 1rem;
  resize:none; tab-size:4; white-space:pre; overflow:auto; min-height:0;
}
/* Toolbar Copy button (moved here from the header row, v2.14.0) --
   small and understated relative to Save, since Save is the primary
   action; sits next to the file path/status rather than beside Save
   so it doesn't read as a second equally-weighted primary action. */
#uf-toolbar button{
  font-family:var(--sans); font-size:var(--fs-sm); color:var(--fg);
  cursor:pointer; padding:.1rem .5rem; border:1px solid var(--border2);
  border-radius:3px; background:transparent; flex-shrink:0;
}
"""

_CSS_LOGIN = """
#logout-btn{margin-top:.3rem;font-size:var(--fs-xs);padding:.2rem .6rem}

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
#login-card h2{font-family:var(--sans);color:var(--amber);font-size:var(--fs-lg);
  letter-spacing:.06em;margin-bottom:1rem;text-shadow:0 0 8px rgba(255,208,64,.5)}
#login-card form{display:flex;flex-direction:column;gap:.6rem}
#login-pw{font-family:var(--sans);font-size:var(--fs-md);background:#0a1020;
  color:var(--fg);border:1px solid var(--line);border-radius:4px;
  padding:.45rem .6rem;outline:none}
#login-pw:focus{border-color:var(--amber)}
#login-card button[type=submit]{color:var(--amber);border-color:var(--amber-dim)}
#login-err{min-height:1.1rem;font-size:var(--fs-base);color:var(--red);margin-top:.2rem}
#login-card .muted{font-size:var(--fs-sm);margin-top:.4rem}
#login-screen,#login{flex-direction:column;gap:18px;padding:40px 16px 56px}
.welcome{font-size:1.1rem;font-weight:700;color:var(--text-bright);letter-spacing:.02em;text-wrap:balance;max-width:44ch}
.welcome b{color:var(--amber);font-weight:700;text-shadow:0 0 12px rgba(255,208,64,.5)}
.splash-license{position:absolute;left:0;right:0;bottom:14px;text-align:center;font-size:var(--fs-xs);letter-spacing:.04em;color:var(--muted)}
.splash-license a{color:var(--blue)}
"""

_CSS_DISKIMG = """
/* Disk Image & Clone: command-preview fields and terminal-style
   console (v2.9.0) -- same idea as 44helper's .asl3-cmd-input /
   .asl3-console, restyled with instmon's own CSS vars rather than
   copying helper's palette. */
.diskimg-cmd{width:100%;box-sizing:border-box;font-family:var(--sans);
  font-size:var(--fs-sm);background:#0a1020;color:var(--yel);
  border:1px solid var(--border2);border-radius:4px;
  padding:.35rem .55rem;margin-top:.3rem}
.diskimg-cmd.placeholder{color:var(--muted);font-style:italic}
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
.diskimg-offair{background:#3a1414;border:1px solid #c0392b;color:var(--red);
  border-radius:4px;padding:.35rem .55rem;margin:.35rem 0;
  font-weight:600;letter-spacing:.02em;text-align:center}
.diskimg-cmd-note{font-size:var(--fs-sm);color:var(--muted);margin-top:.15rem}
/* v2.21.0: the honest-limits line under Backup/Clone. Deliberately
   always visible rather than tucked into the checkbox tooltip -- the
   thing people misremember about this feature is what it guarantees. */
.popup-actions{display:flex;gap:.5rem;justify-content:center;margin-top:.7rem;flex-wrap:wrap}
.popup-actions button{font-size:var(--fs-base);padding:.3rem .8rem}
.diskimg-quiesce-note{font-size:var(--fs-sm);color:var(--muted);
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
  white-space:pre-wrap;word-break:break-all;font-family:var(--sans);
  font-size:var(--fs-base);max-height:220px;overflow-y:auto}
.diskimg-console.placeholder{color:var(--muted);font-style:italic}
.diskimg-console .log-ok{color:var(--grn)}
.diskimg-console .log-err{color:var(--red)}
.diskimg-console .log-warn{color:var(--yel)}

/* Per-card hide/show (v2.15.0) -- default collapsed, toggled via a
   small button pinned to the card's own top-right corner rather than
   inline in a header row, per explicit request. Extra top padding on
   .diskimg-card (vs. plain .card) leaves room so the button never
   overlaps the card's own first line of content when expanded. */
.diskimg-card,.diskimg-intro{position:relative;padding-top:2.1rem}
.diskimg-corner{position:absolute;top:.55rem;right:.7rem;z-index:2;display:flex;gap:.35rem}
.diskimg-toggle,.diskimg-help-toggle{
  font-family:var(--sans);font-size:var(--fs-xs);color:var(--fg);
  cursor:pointer;padding:.15rem .55rem;border:1px solid var(--border2);
  border-radius:3px;background:transparent;
}
.diskimg-card.collapsed .diskimg-card-body{display:none}
/* v2.66.0: numbered steps, and help text that stays hidden until the
   card's Help button is pressed. */
.diskimg-card.collapsed .diskimg-help-toggle{display:none}
.card:not(.help-open) .diskimg-help{display:none}
.diskimg-help{margin:.3rem 0}
.diskimg-copy-row{justify-content:flex-end;margin-top:.4rem}
.diskimg-copy-row button{font-size:var(--fs-sm);padding:.15rem .55rem}
.diskimg-step{display:flex;align-items:center;gap:.45rem;margin:.75rem 0 .3rem;
  font-size:var(--fs-base);font-weight:700;color:var(--amber)}
.diskimg-step:first-child{margin-top:0}
.diskimg-step-n{display:inline-flex;align-items:center;justify-content:center;
  width:1.3rem;height:1.3rem;border-radius:50%;background:var(--amber);
  color:#070b10;font-size:var(--fs-sm);flex-shrink:0}
.diskimg-step-body{margin-left:1.75rem}
.diskimg-sub{font-size:var(--fs-base);font-weight:700;color:var(--text-bright);
  margin:.9rem 0 .3rem;padding-top:.5rem;border-top:1px solid var(--border2)}
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

let _pollLogBusy = false;
async function pollLog() {
  if (_pollLogBusy) return;
  _pollLogBusy = true;
  try {
    const r = await fetch(`/api/log?since=${lastLogId}`);
    const data = await r.json();
    for (const entry of data.entries) {
      if (typeof entry.id === 'number' && entry.id <= lastLogId) continue;
      logLine(entry);
    }
  } catch (e) { /* server restarting or unreachable, ignore this tick */ }
  finally { _pollLogBusy = false; }
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
  newer_installed: 'NEWER HERE', unknown: 'UNKNOWN', error: 'ERROR', switch: 'SWITCH',
};

// v2.38.0 Pi Zero 2 W build choice (shown only on a Pi Zero 2 W).
function renderChannelChoice(ch) {
  const el = document.getElementById('channel-choice');
  if (!el || !ch) return;
  const sel = ch.channel === 'testing' ? 'testing' : 'stable';
  if (el.dataset.choice === sel) return;
  el.dataset.choice = sel;
  el.innerHTML = `<b>Update channel:</b>
    <label><input type="radio" name="channel-choice" value="stable" ${sel === 'stable' ? 'checked' : ''}> Stable (default)</label>
    <label><input type="radio" name="channel-choice" value="testing" ${sel === 'testing' ? 'checked' : ''}> Testing (opt-in)</label>
    <span class="small muted">Stable gets each tool's build after four newer releases and 3 days on testing, or 14 days as the newest. Testing gets every build as soon as it is merged.</span>`;
  el.querySelectorAll('input[name="channel-choice"]').forEach(r => r.addEventListener('change', async () => {
    const choice = r.value;
    const msg = choice === 'testing'
      ? 'Switch to the TESTING channel? You get every build as soon as it is merged, before it has been proven on other nodes. Nothing changes until you check and update.'
      : 'Go back to the STABLE channel (default)? Tools newer than stable stay as they are; use Get stable on a row to go back to the stable build.';
    if (!confirm(msg)) { delete el.dataset.choice; renderChannelChoice(ch); return; }
    delete el.dataset.choice;
    await postAction({action: 'gh_channel', channel: choice, confirm: true});
    await refreshStatus();
  }));
}

function renderBuildChoice(build) {
  const el = document.getElementById('build-choice');
  if (!el) return;
  if (!build || !build.pi02w) { el.style.display = 'none'; el.innerHTML = ''; return; }
  el.style.display = '';
  const sel = build.choice === 'full' ? 'full' : 'fork';
  if (el.dataset.choice === sel) return;
  el.dataset.choice = sel;
  el.innerHTML = `<b>Pi Zero 2 W build:</b>
    <label><input type="radio" name="build-choice" value="fork" ${sel === 'fork' ? 'checked' : ''}> Pi02w fork (default)</label>
    <label><input type="radio" name="build-choice" value="full" ${sel === 'full' ? 'checked' : ''}> Full build (override)</label>
    <span class="small muted">Full Update installs this build of SysMon and the Dashboard, and switches them if the other one is installed.</span>`;
  el.querySelectorAll('input[name="build-choice"]').forEach(r => r.addEventListener('change', async () => {
    const choice = r.value;
    const msg = choice === 'full'
      ? 'Use the FULL build of SysMon and the Dashboard on this Pi Zero 2 W? It uses more memory. Nothing changes until you run Full Update.'
      : 'Go back to the Pi02w fork (default) of SysMon and the Dashboard? Nothing changes until you run Full Update.';
    if (!confirm(msg)) { delete el.dataset.choice; renderBuildChoice(build); return; }
    delete el.dataset.choice;
    await postAction({action: 'build_pref', choice: choice});
  }));
}

function _fuList(title, items) {
  if (!items || !items.length) return '';
  return `<div><b>${title}</b><ul>${items.map(r => `<li>${escHtml(r.name)}: ${escHtml(r.note)}</li>`).join('')}</ul></div>`;
}

let _fuProgText = '';
let _fuWaitWhat = '';
let _fuWaitEnd = 0;
function _fuProgTick() {
  const prog = document.getElementById('fu-progress');
  if (!prog) return;
  let t = _fuProgText;
  if (t && _fuWaitEnd) {
    const left = Math.max(0, Math.ceil((_fuWaitEnd - Date.now()) / 1000));
    t += ` -- waiting for ${_fuWaitWhat}: ${left}s left`;
  }
  prog.textContent = t;
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
    const any = (fu.updated || []).length + (fu.skipped || []).length + (fu.attention || []).length + (fu.scripts || []).length + (fu.manuals || []).length;
    banners.push(`<div class="fu-banner ${cls}"><div style="flex:1">
      <b>Full Update finished${fu.error ? ' -- ' + escHtml(fu.error) : ''}</b>
      ${_fuList('Updated', fu.updated)}${_fuList('Skipped', fu.skipped)}
      ${_fuList('NEEDS ATTENTION', fu.attention)}${_fuList('Scripts', fu.scripts)}${_fuList('Manuals', fu.manuals)}
      ${any ? '' : '<div>Nothing needed updating.</div>'}
      </div><button data-action="fu_dismiss">Dismiss</button></div>`);
  }
  const bEl = document.getElementById('fu-banners');
  if (bEl) bEl.innerHTML = banners.join('');

  _fuProgText = running ? `Full Update running: ${fu.phase}${fu.current ? ' -- ' + fu.current : ''}` : '';
  _fuWaitWhat = running && fu.wait_left > 0 ? (fu.wait_what || '') : '';
  _fuWaitEnd = _fuWaitWhat ? Date.now() + fu.wait_left * 1000 : 0;
  _fuProgTick();
  const planEl = document.getElementById('fu-plan');
  const plan = fu && fu.plan;
  if (planEl) {
    planEl.innerHTML = !plan ? '' : '<table class="fu-table">' + plan.components.map(c =>
      `<tr><td>${escHtml(c.name)}</td><td><span class="gh-tag ${c.status === 'update' || c.status === 'switch' ? 'gh-upd' : ''}">${_FU_STATUS[c.status] || escHtml(c.status)}</span></td>` +
      `<td>${escHtml(c.note)}</td><td class="muted">${escHtml(c.file)}</td></tr>`).join('') +
      plan.scripts.map(n => `<tr><td>Script</td><td><span class="gh-tag gh-upd">NEW</span></td><td>goes to the Scripts library (not run)</td><td class="muted">${escHtml(n)}</td></tr>`).join('') +
      (plan.manuals || []).map(d => `<tr><td>Manual</td><td><span class="gh-tag gh-upd">${d.why === 'changed' ? 'CHANGED' : 'NEW'}</span></td><td>goes to the Manuals card</td><td class="muted">${escHtml(d.name)}</td></tr>`).join('') +
      '</table>';
  }
  const stopBtn = document.getElementById('fu-stop-btn');
  if (stopBtn) {
    const canStop = running && !['instmon', 'recovering'].includes(fu.phase);
    stopBtn.style.display = canStop ? '' : 'none';
    stopBtn.disabled = !!fu.stopping;
    stopBtn.textContent = fu.stopping ? 'Stopping...' : 'Stop Full Update';
  }
  const fuBtn = document.getElementById('fu-btn');
  if (fuBtn) fuBtn.disabled = running || !(plan && (plan.updates || plan.scripts.length || (plan.manuals || []).length));
  const qb = document.getElementById('quiet-btn');
  if (qb) qb.disabled = running || !!(quiet && (quiet.on || quiet.other));
  const rb = document.getElementById('restore-btn');
  if (rb) rb.disabled = running || !(quiet && quiet.on);
  // While Full Update runs every other button waits (the server refuses
  // them anyway); only buttons disabled here are re-enabled afterwards.
  document.querySelectorAll('button[data-action], #diskimg-refresh-btn, #backup-btn').forEach(b => {
    if (['fu_dismiss', 'fu_stop', 'full_update', 'quiet', 'restore', 'toggle_lib', 'toggle_diskimg_card', 'toggle_diskimg_help', 'copy_diskimg_console', 'go', 'router',
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
    if (typeof cpUpdateStatus === 'function') cpUpdateStatus(data.confputter);
    const ghEl = document.getElementById('gh-summary');
    if (ghEl && typeof data.gh_summary_html === 'string') ghEl.innerHTML = data.gh_summary_html;
    if (typeof data.gh_event_seq === 'number') {
      if (_ghSeenSeq !== null && data.gh_event_seq !== _ghSeenSeq && data.gh_event_msg) {
        showPopup(data.gh_event_msg, data.gh_event_level || 'info');
      }
      _ghSeenSeq = data.gh_event_seq;
    }
    renderQuietFullUpdate(data.quiet, data.full_update);
    renderBuildChoice(data.build);
    renderChannelChoice(data.channel);
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
      const unmountBtn = d.is_boot_disk ? '' : diskimgMountBtn(d);
      const label = escHtml(d.model) || (d.tran === 'usb' ? 'USB drive' : 'removable drive');
      return `<div class="row" style="justify-content:space-between">
        <span>${escHtml(d.path)} &middot; ${fmtBytes(d.size)} &middot; ${label}${badges.length ? ' &middot; ' + badges.join(' ') : ''}</span>
        <span class="small muted">${mountText}${unmountBtn}</span>
      </div>`;
    }).join('');
  }
  el.innerHTML = html;
  ['backup', 'clone', 'restore'].forEach(k => renderDiskimgDriveStrip(k, drives));
  renderRpicloneStatus(data.rpiclone);
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

function diskimgMountBtn(d) {
  const busy = !!(_diskimgCurrentJob && _diskimgCurrentJob.state === 'running');
  const dis = busy ? ' disabled title="A disk-image job is running."' : '';
  const mounted = d.mounted_at && d.mounted_at.length;
  return (mounted
    ? ` <button class="b-danger" data-action="diskimg_unmount" data-dest="${escHtml(d.path)}"${dis}>Unmount</button>`
    : ` <button data-action="diskimg_mount" data-dest="${escHtml(d.path)}"${dis}>Mount</button>`)
    + ` <button data-action="diskimg_eject" data-dest="${escHtml(d.path)}"${dis} title="Unmount, flush and power off the drive so it is safe to unplug.">Eject</button>`;
}

function renderRpicloneStatus(rc) {
  const st = document.getElementById('diskimg-rpiclone-status');
  const btn = document.getElementById('diskimg-rpiclone-install-btn');
  const sel = document.getElementById('diskimg-clone-backend');
  const opt = sel ? sel.querySelector('option[value="rpiclone"]') : null;
  const installed = !!(rc && rc.installed);
  if (st) st.textContent = installed ? `rpi-clone ${rc.version || ''} installed` : 'rpi-clone: not installed';
  if (btn) btn.textContent = installed ? 'Reinstall rpi-clone' : 'Install rpi-clone';
  if (opt) {
    opt.disabled = !installed;
    opt.textContent = installed ? 'File sync (rpi-clone)' : 'File sync (rpi-clone) -- not installed';
  }
  if (sel && !installed && sel.value === 'rpiclone') { sel.value = 'dd'; applyCloneBackend(); scheduleDiskimgPreview('clone'); }
}

function applyCloneBackend() {
  const sel = document.getElementById('diskimg-clone-backend');
  const rpi = !!sel && sel.value === 'rpiclone';
  ['diskimg-clone-verify', 'diskimg-clone-verify-algo', 'diskimg-clone-best-effort', 'diskimg-clone-direct-io', 'diskimg-clone-throttle'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.disabled = rpi;
    if (rpi) { if (el.type === 'checkbox') el.checked = false; else if (id === 'diskimg-clone-throttle') el.value = ''; }
  });
  const q = document.getElementById('diskimg-clone-quiesce');
  const fr = document.getElementById('diskimg-clone-freeze');
  if (fr) {
    fr.disabled = rpi || !(q && q.checked);
    if (fr.disabled) fr.checked = false;
  }
  ['diskimg-clone-rpi-force', 'diskimg-clone-rpi-host'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = !rpi;
  });
  ['diskimg-clone-expand', 'diskimg-clone-new-ids'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = rpi;
  });
}

function renderDiskimgDriveStrip(key, drives) {
  const el = document.getElementById('diskimg-strip-' + key);
  if (!el) return;
  const usable = drives.filter(d => !d.is_boot_disk);
  if (!usable.length) {
    el.innerHTML = '<span class="muted">No drives attached. Plug one in -- an SD card in a USB adapter counts.</span>';
    return;
  }
  el.innerHTML = usable.map(d => {
    const mounted = d.mounted_at && d.mounted_at.length;
    const label = escHtml(d.model) || (d.tran === 'usb' ? 'USB drive' : 'removable drive');
    const state = mounted ? `mounted at ${escHtml(d.mounted_at.join(', '))}` : 'not mounted';
    return `<div class="row" style="justify-content:space-between">
      <span>${escHtml(d.path)} &middot; ${fmtBytes(d.size)} &middot; ${label}${d.read_only ? ' &middot; <span class="log-err">write-protected</span>' : ''}</span>
      <span class="small muted">${state}${diskimgMountBtn(d)}</span>
    </div>`;
  }).join('');
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
  const mounted = drives.filter(d => !d.is_boot_disk && !d.read_only && d.mounted_at && d.mounted_at.length);
  sel.innerHTML = (usable.length
    ? usable.map(d => `<option value="${escHtml(d.path)}">${escHtml(d.path)} (${fmtBytes(d.size)})</option>`).join('')
    : '<option value="">No usable (unmounted) drives attached</option>')
    + mounted.map(d => `<option value="" disabled>${escHtml(d.path)} (${fmtBytes(d.size)}, mounted -- unmount first)</option>`).join('');
  if (usable.some(d => d.path === prev)) sel.value = prev;
  else sel.selectedIndex = 0;
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
    wireButtons();
    usbimpApplyDrives((data.drives || []).filter((d) => !d.is_boot_disk)
      .map((d) => ({name: d.name, model: d.model, size: d.size})), false);
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
const _DISKIMG_UNSTOPPABLE_PHASES = ['quiescing', 'thawing', 'unquiescing', 'shrinking', 'formatting', 'expanding', 'relabeling'];

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
  const done = (phase === 'verifying' || phase === 'checksumming') ? (job.verify_bytes_done || 0) : (job.bytes_done || 0);
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
  if (phase === 'expanding') return {label: 'Expanding to fill the drive', pct: null, cls: 'indet'};
  if (phase === 'relabeling') return {label: 'Giving the copy new disk IDs', pct: null, cls: 'indet'};
  if (phase === 'checksumming') {
    if (!total) return {label: 'Saving checksum', pct: null, cls: 'indet'};
    return {label: 'Saving checksum', pct: diskimgPct(job.verify_bytes_done || 0, total), cls: ''};
  }
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
    if (job.backend === 'rpiclone') badges.push('rpi-clone file sync');
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
      const meterDone = (phase === 'verifying' || phase === 'checksumming') ? (job.verify_bytes_done || 0) : (job.bytes_done || 0);
      const flushing = bar.label === 'Flushing to disk';
      let line = bar.label;
      if (hasPct) line += ` &middot; ${fmtPct(bar.pct)}%`;
      if (hasPct && job.bytes_total) line += ` &middot; ${fmtBytesFine(meterDone)} of ${fmtBytesFine(job.bytes_total)}`;
      if (!hasPct) line += ' &mdash; no percentage is available for this step';
      html += `<div class="small muted">${line}</div>`;
      // How long: always the elapsed time; time left once there is a
      // window of samples to base it on.
      let timing = `Elapsed ${elapsedTxt}`;
      if (hasPct && !flushing && (phase === 'copying' || phase === 'verifying' || phase === 'checksumming')) {
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
      if (trk.id === job.id && hasPct && !flushing && (phase === 'copying' || phase === 'verifying' || phase === 'checksumming')) {
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
    body.verify_algo = (document.getElementById('diskimg-backup-verify-algo') || {}).value || 'sha256';
    body.backend = (document.getElementById('diskimg-backup-backend') || {}).value || 'dd';
    const bThrottle = (document.getElementById('diskimg-backup-throttle') || {}).value || '';
    body.throttle_rate_mb = bThrottle ? Number(bThrottle) : null;
  } else if (kind === 'clone') {
    cmdElId = 'diskimg-clone-cmd';
    body.dest_device = (document.getElementById('diskimg-clone-dest') || {}).value || '';
    body.quiesce = (document.getElementById('diskimg-clone-quiesce') || {}).checked || false;
    body.best_effort = (document.getElementById('diskimg-clone-best-effort') || {}).checked || false;
    body.direct_io = (document.getElementById('diskimg-clone-direct-io') || {}).checked || false;
    body.verify = (document.getElementById('diskimg-clone-verify') || {}).checked || false;
    body.verify_algo = (document.getElementById('diskimg-clone-verify-algo') || {}).value || 'sha256';
    body.backend = (document.getElementById('diskimg-clone-backend') || {}).value || 'dd';
    body.rpi_force = (document.getElementById('diskimg-clone-rpi-force') || {}).checked || false;
    body.rpi_hostname = ((document.getElementById('diskimg-clone-rpi-host') || {}).value || '').trim();
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
    body.verify = (document.getElementById('diskimg-restore-verify') || {}).checked || false;
    body.verify_algo = (document.getElementById('diskimg-restore-verify-algo') || {}).value || 'sha256';
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
        const encBadge = (b.encrypted ? ' &middot; <span class="log-warn">encrypted</span>' : '')
          + (b.checksum ? ' &middot; <span class="log-ok">checksum saved</span>' : ' &middot; <span class="muted">no checksum</span>');
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
  const d = new Date(), p2 = n => String(n).padStart(2, '0');
  const ts = `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
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

_JS_CONFPUTTER = r"""
var CP_STATE = null;
var CP_PLAN = null;
var CP_SNAP = '';
var CP_SIG = '';
var CP_SECRETS = {};
var CP_CHECKED = {};

function cpEsc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function cpMsg(text, ok) {
  var el = document.getElementById('cp-msg');
  if (!el) return;
  el.textContent = text || '';
  el.style.color = ok === true ? 'var(--grn)' : ok === false ? 'var(--red)' : '';
}

async function cpCall(body) {
  var r = await fetch('/api/action', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}, body: JSON.stringify(body)});
  var data = {};
  try { data = await r.json(); } catch (e) {}
  data._ok = r.ok;
  return data;
}

function cpUpdateStatus(st) {
  if (!st) return;
  CP_STATE = st;
  var badge = document.getElementById('cp-badge');
  var ver = document.getElementById('cp-ver');
  var sel = document.getElementById('cp-snap');
  if (!badge || !ver || !sel) return;
  badge.textContent = st.running ? 'RUNNING' : (st.installed ? 'INSTALLED' : 'NOT INSTALLED');
  badge.className = 'badge ' + (st.installed ? 'b-inst' : 'b-src');
  ver.textContent = st.installed ? 'v' + st.version : '';
  var items = [];
  (st.snapshots || []).forEach(function(s) { items.push({value: 'snapshot:' + s.name, label: s.name + ' (' + s.mtime + ')'}); });
  (st.edited || []).forEach(function(s) { items.push({value: 'edited:' + s.name, label: 'uploaded: ' + s.name + ' (' + s.mtime + ')'}); });
  var sig = items.map(function(i) { return i.value + '|' + i.label; }).join(';');
  if (sig !== CP_SIG) {
    var keep = sel.value;
    CP_SIG = sig;
    sel.innerHTML = items.length ? items.map(function(i) { return '<option value="' + cpEsc(i.value) + '">' + cpEsc(i.label) + '</option>'; }).join('') : '<option value="">-- no snapshots yet --</option>';
    if (keep && items.some(function(i) { return i.value === keep; })) sel.value = keep;
  }
  var busy = !st.installed || st.running;
  var pb = document.getElementById('cp-preview-btn');
  if (pb) pb.disabled = busy || !sel.value;
  var undo = document.getElementById('cp-undo-btn');
  if (undo) {
    var lb = st.last_backup;
    undo.style.display = lb && !lb.undone ? '' : 'none';
    undo.textContent = lb ? 'Undo last restore (' + lb.created + ')' : 'Undo last restore';
    undo.disabled = busy;
  }
  var un = document.getElementById('cp-uninstall-btn');
  if (un) un.style.display = st.installed ? '' : 'none';
  cpOnSelect();
}

function cpOnSelect() {
  var sel = document.getElementById('cp-snap');
  var del = document.getElementById('cp-del-edited');
  if (del && sel) del.style.display = sel.value.indexOf('edited:') === 0 ? '' : 'none';
}

function cpCount() {
  var n = Object.keys(CP_CHECKED).filter(function(p) { return CP_CHECKED[p]; }).length;
  var el = document.getElementById('cp-count');
  if (el) el.textContent = n + ' file(s) ticked';
}

function cpRenderPlan() {
  var box = document.getElementById('cp-plan');
  if (!box) return;
  var p = CP_PLAN;
  if (!p) { box.innerHTML = ''; return; }
  var nl = String.fromCharCode(10);
  var s = p.snapshot || {};
  var h = '<div class="small muted">Snapshot from <b>' + cpEsc(s.host) + '</b>, taken ' + cpEsc(s.taken) + ' by ' + cpEsc(s.made_by) + '</div>';
  (p.warnings || []).forEach(function(w) { h += '<div class="small" style="color:var(--yel)">' + cpEsc(w) + '</div>'; });
  var files = p.files || [];
  var act = files.filter(function(f) { return f.status !== 'skipped'; });
  var skipped = files.filter(function(f) { return f.status === 'skipped'; });
  h += '<div style="margin:.4rem 0">';
  act.forEach(function(f) {
    h += '<div class="librow"><div class="librow-top"><label><input type="checkbox" class="cp-chk" data-path="' + cpEsc(f.path) + '"' +
      (CP_CHECKED[f.path] ? ' checked' : '') + (f.status === 'same' ? ' disabled' : '') + '> ' + cpEsc(f.path) + '</label>' +
      '<span class="badge ' + (f.status === 'same' ? 'b-inst' : 'b-src') + '">' + cpEsc(f.status.toUpperCase()) + '</span>' +
      (f.careful ? '<span class="badge b-src" style="color:var(--yel)">CAREFUL</span>' : '') + '</div>' +
      '<div class="librow-bot small muted"><span>' + cpEsc(f.group) + '</span><span>&middot;</span><span>' + cpEsc(f.note) + '</span>' +
      (f.status !== 'same' ? '<span>&middot;</span><span>+' + f.added + ' -' + f.removed + ' lines</span>' : '') + '</div>';
    if (f.diff && f.diff.length) h += '<details class="small"><summary>Show changes</summary><pre style="white-space:pre-wrap;margin:.3rem 0">' + cpEsc(f.diff.join(nl)) + '</pre></details>';
    h += '</div>';
  });
  if (!act.length) h += '<div class="small muted">Nothing in this snapshot can be restored here.</div>';
  h += '</div>';
  if (skipped.length) {
    h += '<details class="small muted"><summary>' + skipped.length + ' file(s) not restored</summary>' +
      skipped.map(function(f) { return '<div>' + cpEsc(f.path) + ': ' + cpEsc(f.note) + '</div>'; }).join('') + '</details>';
  }
  var secs = p.secrets || [];
  if (secs.length) {
    h += '<div class="small" style="margin:.5rem 0 .2rem">This node does not have these passwords or keys. Type them, or leave a box empty to write it empty and set it by hand. ' +
      'They travel over plain HTTP: type them only on a trusted LAN or VPN.</div>';
    secs.forEach(function(x, i) {
      h += '<div class="librow"><div class="small muted">' + x.where.map(cpEsc).join('<br>') + (x.count > x.where.length ? '<br>and ' + (x.count - x.where.length) + ' more' : '') + '</div>' +
        '<input type="password" class="cp-sec" data-tag="' + cpEsc(x.tag) + '" autocomplete="new-password" placeholder="value" style="max-width:100%"></div>';
    });
  }
  if ((p.restart || []).length) h += '<div class="small muted">After a restore, restart: ' + p.restart.map(cpEsc).join(', ') + ' (the Restart comms button above covers the radio services).</div>';
  h += '<div class="row btn-row"><button class="b-go" onclick="cpApply()">Restore ticked files</button><span class="small muted" id="cp-count"></span></div>';
  box.innerHTML = h;
  box.querySelectorAll('.cp-chk').forEach(function(el) {
    el.addEventListener('change', function() { CP_CHECKED[el.dataset.path] = el.checked; cpCount(); });
  });
  box.querySelectorAll('.cp-sec').forEach(function(el) {
    el.addEventListener('input', function() { CP_SECRETS[el.dataset.tag] = el.value; });
  });
  cpCount();
}

function cpShowResult(r) {
  var box = document.getElementById('cp-plan');
  if (!box) return;
  var h = '<div style="margin:.4rem 0">';
  (r.written || r.restored || []).forEach(function(p) { h += '<div class="small">' + (r.restored ? 'put back ' : 'wrote ') + cpEsc(p) + '</div>'; });
  (r.removed || []).forEach(function(p) { h += '<div class="small">removed ' + cpEsc(p) + '</div>'; });
  (r.kept || []).forEach(function(p) { h += '<div class="small" style="color:var(--yel)">left alone (changed since): ' + cpEsc(p) + '</div>'; });
  (r.failed || []).forEach(function(f) { h += '<div class="small" style="color:var(--red)">FAILED ' + cpEsc(f.path) + ': ' + cpEsc(f.error) + '</div>'; });
  if ((r.unresolved || []).length) {
    h += '<div class="small" style="color:var(--yel)">Written with an empty secret: set these by hand:</div>' +
      r.unresolved.map(function(u) { return '<div class="small">' + cpEsc(u.path) + ': ' + cpEsc(u.key) + '</div>'; }).join('');
  }
  if ((r.restart || []).length) h += '<div class="small muted">Restart: ' + r.restart.map(cpEsc).join(', ') + '</div>';
  h += '</div>';
  box.innerHTML = h;
}

async function cpPreview() {
  var sel = document.getElementById('cp-snap');
  if (!sel || !sel.value) { cpMsg('Pick a snapshot first.', false); return; }
  cpMsg('Reading the snapshot...');
  var r = await cpCall({action: 'cp_preview', snapshot: sel.value, keep_comments: document.getElementById('cp-keep').checked});
  if (!r.plan) { cpMsg(r.message || r.error || 'Preview failed.', false); return; }
  CP_PLAN = r.plan;
  CP_SNAP = sel.value;
  CP_SECRETS = {};
  CP_CHECKED = {};
  (r.plan.files || []).forEach(function(f) { CP_CHECKED[f.path] = !!f.checked; });
  cpMsg('Preview ready. Nothing was changed.', true);
  cpRenderPlan();
}

async function cpApply() {
  if (!CP_PLAN) return;
  var only = Object.keys(CP_CHECKED).filter(function(p) { return CP_CHECKED[p]; });
  if (!only.length) { cpMsg('Tick at least one file.', false); return; }
  var typed = {};
  Object.keys(CP_SECRETS).forEach(function(t) { if (CP_SECRETS[t]) typed[t] = CP_SECRETS[t]; });
  var missing = (CP_PLAN.secrets || []).filter(function(x) { return !typed[x.tag]; }).length;
  var nl = String.fromCharCode(10);
  var text = 'Restore ' + only.length + ' file(s) from ' + CP_SNAP.split(':')[1] + '?' + nl + nl +
    'The files they replace are saved first (Undo last restore).' +
    (missing ? nl + missing + ' secret value(s) are not given: those are written empty.' : '') +
    ((CP_PLAN.restart || []).length ? nl + 'Restart afterwards: ' + CP_PLAN.restart.join(', ') : '');
  if (!confirm(text)) return;
  cpMsg('Restoring...');
  var r = await cpCall({action: 'cp_apply', snapshot: CP_SNAP, only: only, secrets: typed, keep_comments: document.getElementById('cp-keep').checked, confirm: true});
  CP_SECRETS = {};
  if (!r.result) { cpMsg(r.message || r.error || 'Restore failed.', false); return; }
  cpMsg(r.message, r.result.ok);
  CP_PLAN = null;
  cpShowResult(r.result);
  refreshStatus();
}

async function cpUndo() {
  var lb = CP_STATE && CP_STATE.last_backup;
  if (!lb) return;
  if (!confirm('Put back the files saved before the restore of ' + lb.created + ' (' + lb.files + ' file(s))? Files changed since then are left alone.')) return;
  cpMsg('Undoing...');
  var r = await cpCall({action: 'cp_undo', confirm: true});
  if (!r.result) { cpMsg(r.message || r.error || 'Undo failed.', false); return; }
  cpMsg(r.message, true);
  CP_PLAN = null;
  cpShowResult(r.result);
  refreshStatus();
}

async function cpUninstall() {
  if (!confirm('Uninstall Config putter? Removes /usr/local/bin/confputter.py. Snapshots, uploaded copies and backups are kept.')) return;
  var r = await cpCall({action: 'cp_uninstall', confirm: true});
  cpMsg(r.message || r.error, r._ok);
  refreshStatus();
}

async function cpDeleteEdited() {
  var sel = document.getElementById('cp-snap');
  if (!sel || sel.value.indexOf('edited:') !== 0) return;
  var name = sel.value.slice(7);
  if (!confirm('Delete the uploaded copy ' + name + '?')) return;
  var r = await cpCall({action: 'cp_delete_edited', name: name});
  cpMsg(r.message || r.error, r._ok);
  refreshStatus();
}

async function cpUpload() {
  var inp = document.getElementById('cp-file');
  if (!inp || !inp.files || !inp.files[0]) { cpMsg('Choose a .md file first.', false); return; }
  var fd = new FormData();
  fd.append('file', inp.files[0]);
  var r = await fetch('/api/confputter/upload', {method: 'POST', headers: {'X-Requested-With': 'XMLHttpRequest'}, body: fd});
  var data = {};
  try { data = await r.json(); } catch (e) {}
  cpMsg(data.message || data.error || (r.ok ? 'Uploaded.' : 'Upload failed.'), r.ok);
  if (r.ok) {
    inp.value = '';
    await refreshStatus();
    var sel = document.getElementById('cp-snap');
    if (sel && data.name) sel.value = 'edited:' + data.name;
    cpOnSelect();
  }
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
  document.querySelectorAll('input.lib-lock-cb').forEach(cb => {
    if (cb._wired) return;
    cb._wired = true;
    cb.addEventListener('change', async () => {
      const on = cb.checked;
      if (!on && !confirm(`Unlock ${cb.dataset.name}? It can then be deleted or overwritten.`)) { cb.checked = true; return; }
      cb.disabled = true;
      await postAction({action: 'lib_lock', category: cb.dataset.category, name: cb.dataset.name, locked: on, confirm: !on});
      await refreshStatus();
    });
  });
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
      if (action === 'toggle_diskimg_help') {
        // v2.66.0: local UI-only toggle for the card's help text.
        const card = btn.closest('.card');
        if (!card) return;
        const open = card.classList.toggle('help-open');
        btn.textContent = open ? 'Hide Help' : 'Help';
        return;
      }
      if (action === 'copy_diskimg_console') {
        // v2.67.0: copies that card's console, one line per entry.
        const el = document.getElementById(btn.dataset.target);
        const text = el && !el.classList.contains('placeholder') ? collectLogText(el) : '';
        await copyTextWithVerify(text, 'Log copied');
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
        const cur = _diskimgCurrentJob;
        if (cur && cur.kind === btn.dataset.kind && cur.state !== 'running'
            && !confirm('Reset this card? Its result and console are cleared, and its options go back to their defaults.')) return;
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
          const nlCfg = /^node(listen|talker)/i.test(btn.dataset.name || '');
          if (!confirm(`Install ${btn.dataset.name} as the active ${nlCfg ? 'Node Talker ' : ''}config? This will restart ${nlCfg ? 'Node Talker' : 'the Dashboard'} if it's installed.`)) { btn.disabled = false; return; }
          await postAction({action: 'install_config', name: btn.dataset.name});
        } else if (action === 'gh_check') {
          await postAction({action: 'gh_check'});
        } else if (action === 'quiet') {
          if (!confirm('Quiet the system? Pauses SysMon, the Dashboard, 44helper, Node Talker and the watchdog timer (whichever are running) until you press Restore -- auto-restore after 30 min. Radio, Asterisk, the bridges, Allmon3, SSH and wifimon stay up.')) { btn.disabled = false; return; }
          await postAction({action: 'quiet'});
        } else if (action === 'restore') {
          await postAction({action: 'restore'});
        } else if (action === 'fu_dismiss') {
          await postAction({action: 'fu_dismiss'});
        } else if (action === 'fu_stop') {
          if (!confirm('Stop Full Update? The tool being updated now goes back to the version it had (from its library), the tools not reached yet are skipped, and the paused web tools are restarted. This can take a couple of minutes.')) { btn.disabled = false; return; }
          await postAction({action: 'fu_stop', confirm: true});
        } else if (action === 'full_update') {
          const p = _fuState && _fuState.plan;
          const comps = p ? p.components.filter(c => c.status === 'update' || c.status === 'switch').map(c => `  ${c.name}: ${c.note}`) : [];
          const scr = p ? p.scripts.map(n => `  ${n} (Scripts library only, not run)`) : [];
          const man = p ? (p.manuals || []).map(d => `  ${d.name} (${d.why})`) : [];
          if (!confirm('Full Update from GitHub?\\n\\n' + (comps.length ? 'One at a time:\\n' + comps.join('\\n') + '\\n\\n' : '') +
                       (scr.length ? 'New scripts:\\n' + scr.join('\\n') + '\\n\\n' : '') +
                       (man.length ? 'Manuals:\\n' + man.join('\\n') + '\\n\\n' : '') +
                       'GitHub is checked again first. The web tools are paused, each component is uninstalled and the new version installed; one that fails is put back and skipped. Then the manuals that are new or changed on GitHub are downloaded. instmon goes last -- this page reconnects after it restarts.')) { btn.disabled = false; return; }
          await postAction({action: 'full_update', confirm: true});
        } else if (action === 'gh_update') {
          if (btn.dataset.older === '1') {
            if (!confirm(`Get the stable build ${btn.dataset.name}? It is OLDER than the newest file in the ${btn.dataset.category} library. It goes into the library, checked first; nothing installs until you press Install on it.`)) { btn.disabled = false; return; }
            await postAction({action: 'gh_update', name: btn.dataset.name, confirm: true, allow_older: true});
          } else {
          if (!confirm(`Download ${btn.dataset.name} from GitHub into the ${btn.dataset.category} library? It is checked before it is saved, and nothing runs or installs until you press its button.`)) { btn.disabled = false; return; }
          await postAction({action: 'gh_update', name: btn.dataset.name, confirm: true});
          }
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
        } else if (action === 'rpiclone_install') {
          if (!confirm('Install rpi-clone? This installs any missing packages it needs (rsync, parted, fdisk, dosfstools ...) with apt, then downloads a fixed, checksum-checked rpi-clone from GitHub into /usr/local/sbin. No prompts -- output goes to the Execution Log.')) { btn.disabled = false; return; }
          await postAction({action: 'rpiclone_install', confirm: true});
        } else if (action === 'install_confgetter') {
          if (!confirm(`Install ${btn.dataset.name} as /usr/local/bin/confgetter.sh? It only reads config files when you press Run.`)) { btn.disabled = false; return; }
          await postAction({action: 'install_confgetter', name: btn.dataset.name, confirm: true});
        } else if (action === 'install_confputter') {
          if (!confirm(`Install ${btn.dataset.name} as /usr/local/bin/confputter.py? It only writes config files when you choose files and press Restore on the Config putter card.`)) { btn.disabled = false; return; }
          await postAction({action: 'install_confputter', name: btn.dataset.name, confirm: true});
        } else if (action === 'cg_run') {
          await postAction({action: 'cg_run'});
        } else if (action === 'cg_uninstall') {
          if (!confirm('Uninstall Config getter? Removes /usr/local/bin/confgetter.sh. Its snapshots and library files are kept.')) { btn.disabled = false; return; }
          await postAction({action: 'cg_uninstall', confirm: true});
        } else if (action === 'cg_delete') {
          if (!confirm(`Delete snapshot ${btn.dataset.name}?`)) { btn.disabled = false; return; }
          await postAction({action: 'cg_delete', name: btn.dataset.name});
        } else if (action === 'app_fetch') {
          await postAction({action: 'app_fetch'});
        } else if (action === 'app_delete') {
          if (!confirm(`Delete ${btn.dataset.name} from the library?`)) { btn.disabled = false; return; }
          await postAction({action: 'app_delete', name: btn.dataset.name});
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
          if (msg) msg.textContent = r.ok ? (/\\.pdf$/i.test(data.name || '') ? `Added to Manuals: ${data.name}` : `Staged: ${data.name}`) : (data.error || 'Upload failed');
          showPopup(data.message || data.error || (r.ok ? 'Uploaded.' : 'Upload failed'), data.level || (r.ok ? 'ok' : 'err'));
          if (r.ok) { fileInput.value = ''; _pendingUploadFiles.delete(cat); }
          if (r.ok && /\\.pdf$/i.test(data.name || '')) docsLoad();
        } else if (action === 'save_alternate') {
          await postAction({action: 'save_alternate', name: btn.dataset.name || ''});
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
        } else if (action === 'diskimg_eject') {
          const dest = btn.dataset.dest;
          if (!confirm(`Eject ${dest}? It is unmounted, flushed and powered off. Unplug and plug it back in to use it again.`)) { btn.disabled = false; return; }
          await postDiskimg('/api/diskimg/eject', {confirm: true, dest_device: dest});
        } else if (action === 'diskimg_mount') {
          const dest = btn.dataset.dest;
          if (!confirm(`Mount every partition on ${dest} under /mnt/instmon-diskimg? Unmount it again before pulling it out, or before Clone/Restore/Format.`)) { btn.disabled = false; return; }
          await postDiskimg('/api/diskimg/mount', {confirm: true, dest_device: dest});
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
          const rpiForceEl = document.getElementById('diskimg-clone-rpi-force');
          const rpiForce = backend === 'rpiclone' && !!rpiForceEl && rpiForceEl.checked;
          const rpiHostEl = document.getElementById('diskimg-clone-rpi-host');
          const rpiHost = backend === 'rpiclone' && rpiHostEl ? rpiHostEl.value.trim() : '';
          if (backend === 'rpiclone') {
            if (!confirm(`Clone this Pi onto ${dest} with rpi-clone? A first clone onto ${dest}${rpiForce ? ' -- and Force re-initialize, which is ticked --' : ' (or Force re-initialize)'} ERASES everything on it; a later clone onto the same card only syncs the changes.`)) { btn.disabled = false; return; }
            if (cQuiesce && !confirm(offAirWarning())) { btn.disabled = false; return; }
          } else {
          if (!confirm(`Clone this Pi's whole boot disk directly onto ${dest}? This ERASES everything currently on ${dest} and cannot be undone.`)) { btn.disabled = false; return; }
          if (cQuiesce && !confirm(offAirWarning())) { btn.disabled = false; return; }
          if (bestEffort && !confirm('Continue past read errors is ticked -- an unreadable source sector will be padded with nulls and the clone will still report success. Continue?')) { btn.disabled = false; return; }
          if (!confirm(`Really sure? ${dest} will become a byte-for-byte copy of this Pi's boot disk.`)) { btn.disabled = false; return; }
          }
          const cExpandEl = document.getElementById('diskimg-clone-expand');
          const cNewIdsEl = document.getElementById('diskimg-clone-new-ids');
          await postDiskimg('/api/diskimg/clone/start', {
            expand: !!(cExpandEl && cExpandEl.checked), new_ids: !!(cNewIdsEl && cNewIdsEl.checked),
            confirm: true, dest_device: dest, verify: verify, verify_algo: verifyAlgo, quiesce: cQuiesce,
            freeze: freeze, best_effort: bestEffort, direct_io: directIo, backend: backend,
            throttle_rate_mb: throttleRateMb, rpi_force: rpiForce, rpi_hostname: rpiHost,
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
          const expandEl = document.getElementById('diskimg-restore-expand');
          const expand = expandEl ? expandEl.checked : false;
          if (!confirm(`Restore ${imgName} onto ${dest}? This ERASES everything currently on ${dest} and cannot be undone.`)) { btn.disabled = false; return; }
          if (!confirm(`Really sure? ${dest} will become a byte-for-byte copy of that backup image.`)) { btn.disabled = false; return; }
          await postDiskimg('/api/diskimg/restore/start', {
            confirm: true, name: imgName, drive: imgDrive, dest_device: dest, verify: verify,
            verify_algo: verifyAlgo, passphrase: passphrase, throttle_rate_mb: throttleRateMb, expand: expand,
            new_ids: !!((document.getElementById('diskimg-restore-new-ids') || {}).checked),
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
  const url = typeof input === 'string' ? input : ((input && input.url) || '');
  // v2.72.0: once the login is lost, stop sending -- the page is reloading.
  if (_authLostReloading && url.startsWith('/api/') && url !== '/api/login') {
    return new Response('{"error":"Authentication required"}', {status: 401, headers: {'Content-Type': 'application/json'}});
  }
  const resp = await _rawFetch(input, init);
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
 ['diskimg-backup-best-effort', 'change'], ['diskimg-backup-backend', 'change'], ['diskimg-backup-throttle', 'change'],
 ['diskimg-backup-verify-algo', 'change']]
  .forEach(([id, evt]) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener(evt, () => scheduleDiskimgPreview('backup'));
  });
['diskimg-clone-dest', 'diskimg-clone-quiesce', 'diskimg-clone-best-effort', 'diskimg-clone-direct-io', 'diskimg-clone-backend', 'diskimg-clone-throttle', 'diskimg-clone-rpi-force', 'diskimg-clone-verify', 'diskimg-clone-verify-algo'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', () => scheduleDiskimgPreview('clone'));
});
(function() {
  const el = document.getElementById('diskimg-clone-rpi-host');
  if (el) el.addEventListener('input', () => scheduleDiskimgPreview('clone'));
})();
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
['diskimg-restore-image', 'diskimg-restore-dest', 'diskimg-restore-throttle', 'diskimg-restore-verify', 'diskimg-restore-verify-algo'].forEach(id => {
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
['diskimg-clone-backend', 'diskimg-clone-quiesce'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', applyCloneBackend);
});
applyCloneBackend();

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
  setInterval(() => { if (!document.hidden && _fuWaitEnd) _fuProgTick(); }, 1000);
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
  usbimportInit();
  docsInit();
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

_JS_USBIMPORT = """// USB import card. Every string from the drive (names, models) goes in via
// textContent, never innerHTML.
let _usbimpPath = '';
let _usbimpSig = null;
function usbimpMsg(t) { const m = document.getElementById('usbimp-msg'); if (m) m.textContent = t || ''; }
function usbimpClear() {
  const l = document.getElementById('usbimp-list'); if (l) l.textContent = '';
  const p = document.getElementById('usbimp-path'); if (p) p.textContent = '';
  const u = document.getElementById('usbimp-up'); if (u) u.disabled = true;
  _usbimpPath = '';
}
async function usbimpLoadDrives(force) {
  let data;
  try { const r = await fetch('/api/usbimport/drives'); data = await r.json(); } catch (e) { return; }
  usbimpApplyDrives(data.drives || [], force);
}
function usbimpApplyDrives(drives, force) {
  const sel = document.getElementById('usbimp-drive');
  if (!sel) return;
  const sig = JSON.stringify(drives);
  if (!force && sig === _usbimpSig) return;
  _usbimpSig = sig;
  const prev = sel.value;
  sel.textContent = '';
  if (!drives.length) {
    const o = document.createElement('option');
    o.value = ''; o.textContent = 'No USB drive detected';
    sel.appendChild(o);
    usbimpClear(); usbimpMsg('');
    return;
  }
  drives.forEach((d) => {
    const o = document.createElement('option');
    o.value = d.name;
    o.textContent = d.name + ' - ' + (d.model || 'USB drive') + ' (' + fmtBytes(d.size) + ')';
    sel.appendChild(o);
  });
  if (drives.some((d) => d.name === prev)) { sel.value = prev; if (force) usbimpBrowse(_usbimpPath); }
  else { sel.value = drives[0].name; usbimpClear(); usbimpBrowse(''); }
}
async function usbimpBrowse(path) {
  const sel = document.getElementById('usbimp-drive');
  const list = document.getElementById('usbimp-list');
  if (!sel || !sel.value || !list) return;
  usbimpMsg('Reading drive...');
  let r, data;
  try {
    r = await fetch('/api/usbimport/browse?drive=' + encodeURIComponent(sel.value) + '&path=' + encodeURIComponent(path || ''));
    data = await r.json();
  } catch (e) { usbimpMsg('Request failed'); return; }
  if (!r.ok) { list.textContent = ''; usbimpMsg(data.error || 'Browse failed'); return; }
  _usbimpPath = data.path || '';
  document.getElementById('usbimp-path').textContent = '/' + _usbimpPath;
  document.getElementById('usbimp-up').disabled = !_usbimpPath;
  list.textContent = '';
  (data.dirs || []).forEach((n) => {
    const row = document.createElement('div');
    row.className = 'row';
    const b = document.createElement('button');
    b.textContent = '[dir] ' + n;
    b.addEventListener('click', () => usbimpBrowse((_usbimpPath ? _usbimpPath + '/' : '') + n));
    row.appendChild(b);
    list.appendChild(row);
  });
  (data.files || []).forEach((f) => {
    const row = document.createElement('div');
    row.className = 'row';
    row.style.marginTop = '.25rem';
    const nm = document.createElement('span');
    nm.textContent = f.name;
    const sz = document.createElement('span');
    sz.className = 'small muted';
    sz.textContent = fmtBytes(f.size);
    const b = document.createElement('button');
    b.textContent = 'Import';
    b.addEventListener('click', () => usbimpImport(f.name, b));
    row.appendChild(nm); row.appendChild(sz); row.appendChild(b);
    list.appendChild(row);
  });
  if (!(data.dirs || []).length && !(data.files || []).length) {
    const e = document.createElement('div');
    e.className = 'small muted';
    e.textContent = 'No importable files (.py, .sh, .conf, .pdf) here.';
    list.appendChild(e);
  }
  usbimpMsg(data.truncated ? 'Listing truncated -- too many entries in this folder.' : '');
}
async function usbimpImport(name, btn) {
  const drive = document.getElementById('usbimp-drive').value;
  const cat = document.getElementById('usbimp-cat').value;
  const path = (_usbimpPath ? _usbimpPath + '/' : '') + name;
  async function go(force) {
    const r = await fetch('/api/usbimport/import', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify({drive: drive, path: path, category: cat, force: force})
    });
    let data = {};
    try { data = await r.json(); } catch (e) {}
    return {r, data};
  }
  btn.disabled = true;
  usbimpMsg('Importing...');
  try {
    let {r, data} = await go(false);
    if (!r.ok && data.mismatch) {
      if (confirm((data.error || 'Filename does not match this category.') + '\\n\\nImport anyway?')) {
        ({r, data} = await go(true));
      } else { usbimpMsg('Import cancelled.'); return; }
    }
    usbimpMsg(r.ok ? 'Staged: ' + data.name : (data.error || 'Import failed'));
    showPopup(data.message || data.error || (r.ok ? 'Imported.' : 'Import failed'), data.level || (r.ok ? 'ok' : 'err'));
    if (r.ok) { refreshStatus(); if (/\\.pdf$/i.test(name)) docsLoad(); }
  } catch (e) {
    usbimpMsg('Import failed');
  } finally {
    btn.disabled = false;
  }
}
function usbimportInit() {
  const sel = document.getElementById('usbimp-drive');
  if (!sel) return;
  sel.addEventListener('change', () => { usbimpClear(); usbimpBrowse(''); });
  document.getElementById('usbimp-refresh').addEventListener('click', () => usbimpLoadDrives(true));
  document.getElementById('usbimp-up').addEventListener('click', () => {
    const parts = _usbimpPath.split('/'); parts.pop(); usbimpBrowse(parts.join('/'));
  });
}
"""

_JS_DOCS = """// Manuals card. File names go in via textContent and encodeURIComponent.
let _docsTimer = null;
function docsRender(data) {
  const list = document.getElementById('docs-list');
  const msg = document.getElementById('docs-msg');
  const btn = document.getElementById('docs-fetch');
  if (!list) return;
  const busy = data.phase === 'fetching';
  btn.disabled = busy;
  if (busy) msg.textContent = 'Getting the manuals from GitHub...';
  else if (data.phase === 'error') msg.textContent = 'Last fetch failed: ' + (data.error || '?');
  else if (data.msg) msg.textContent = (data.checked_at ? data.checked_at + ': ' : '') + data.msg;
  else msg.textContent = '';
  list.textContent = '';
  const docs = data.docs || [];
  if (!docs.length) {
    const e = document.createElement('div');
    e.className = 'small muted';
    e.textContent = 'No manuals yet. They download when instmon can reach GitHub -- press Get from GitHub to try now.';
    list.appendChild(e);
  }
  docs.forEach((d) => {
    const row = document.createElement('div');
    row.className = 'doc-row';
    const cell = document.createElement('div');
    cell.className = 'doc-name';
    const nm = document.createElement('span');
    nm.textContent = d.name.replace(/\\.pdf$/i, '').replace(/[_]+/g, ' ');
    const meta = document.createElement('span');
    meta.className = 'small muted doc-meta';
    meta.textContent = fmtBytes(d.size) + ' \u00b7 ' + d.date;
    const url = '/api/docs/file?name=' + encodeURIComponent(d.name);
    const open = document.createElement('a');
    open.className = 'btn'; open.href = url; open.target = '_blank'; open.rel = 'noopener';
    open.textContent = 'Open';
    const dl = document.createElement('a');
    dl.className = 'btn'; dl.href = url + '&download=1'; dl.download = d.name;
    dl.textContent = 'Download';
    const del = document.createElement('button');
    del.className = 'b-del'; del.textContent = 'Delete';
    del.addEventListener('click', () => docsDelete(d.name, del));
    cell.appendChild(nm); cell.appendChild(meta);
    row.appendChild(cell); row.appendChild(open); row.appendChild(dl); row.appendChild(del);
    list.appendChild(row);
  });
  if (_docsTimer) { clearTimeout(_docsTimer); _docsTimer = null; }
  if (busy) _docsTimer = setTimeout(docsLoad, 2000);
}
async function docsLoad() {
  try { const r = await fetch('/api/docs'); if (r.ok) docsRender(await r.json()); } catch (e) {}
}
async function docsFetch() {
  const btn = document.getElementById('docs-fetch');
  btn.disabled = true;
  try {
    const r = await fetch('/api/docs/fetch', {method: 'POST', headers: {'X-Requested-With': 'XMLHttpRequest'}});
    let data = {};
    try { data = await r.json(); } catch (e) {}
    if (!r.ok) showPopup(data.message || data.error || 'Could not start the fetch', data.level || 'err');
  } catch (e) {}
  docsLoad();
}
async function docsDelete(name, btn) {
  if (!confirm('Delete ' + name + ' from Manuals?')) return;
  btn.disabled = true;
  try {
    const r = await fetch('/api/docs/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify({name: name})
    });
    let data = {};
    try { data = await r.json(); } catch (e) {}
    showPopup(data.message || data.error || (r.ok ? 'Deleted.' : 'Delete failed'), data.level || (r.ok ? 'info' : 'err'));
  } catch (e) {}
  docsLoad();
}
function docsInit() {
  const btn = document.getElementById('docs-fetch');
  if (!btn) return;
  btn.addEventListener('click', docsFetch);
  docsLoad();
}
"""

_JS = (
    _JS_LOG_POLL
    + _JS_STATUS_TOAST
    + _JS_EDITOR
    + _JS_ACTIONS
    + _JS_USBIMPORT
    + _JS_DOCS
    + _JS_CONFPUTTER
    + _JS_AUTH
    + _JS_INIT
)

def render_page ():
    status =build_status ()
    quicklinks_html =render_quicklinks_html ()
    components_html =render_components_html (status ["components"],status ["library"],status ["app"],status ["confgetter"])
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
<title>Install Monitor</title>
<style>
{css}</style>
</head>
<body>
<header>
  <div class="hdr-left">
    <div class="logo">Install Monitor</div>
    <div class="logo-sub">Installer &amp; Component Manager</div>
  </div>
  <div class="hdr-right">
    <span id="hdr-version">v{version}</span>
    <span class="hdr-meta">{date} &middot; port {port}</span>
    <button id="logout-btn" onclick="doLogout()">Log Out</button>
  </div>
</header>
<div id="login-screen">
  <div class="welcome">Welcome to the <b>KD8PGK</b> Install Monitor</div>
  <div class="splash-license">Install Monitor · <a href="https://creativecommons.org/licenses/by-nc/4.0/" target="_blank" rel="noopener">CC BY-NC 4.0</a></div>
  <div id="login-card">
    <h2>Install Monitor</h2>
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
    <button class="b-danger" id="fu-stop-btn" data-action="fu_stop" style="display:none">Stop Full Update</button>
    <span id="gh-summary" class="small">{github_html}</span>
  </div>
  <div class="small muted" style="margin-top:.35rem">
    Full Update: pauses the web tools, downloads and checks every newer file first, then uninstalls the old and
    installs the new one component at a time (instmon last). A component that fails is put back, skipped and
    listed at the end. New install scripts only go to the Scripts library -- they are never run for you.
    Stop Full Update puts the tool it is on back to the version it had and skips the rest.</div>
  <div id="channel-choice" class="row small" style="margin-top:.35rem"></div>
  <div id="build-choice" class="row small" style="display:none;margin-top:.35rem"></div>
  <div id="fu-progress"></div>
  <div id="fu-plan"></div>
  <div class="row" style="margin-top:.6rem">
    <button class="b-comms" id="quiet-btn" data-action="quiet">Quiet System</button>
    <button id="restore-btn" data-action="restore" disabled>Restore</button>
    <span class="small muted">Before a big upload or install on a small Pi: pauses SysMon, the Dashboard, 44helper,
    Node Talker and the watchdog timer. Radio, Asterisk, the bridges, Allmon3, SSH and wifimon stay up.</span>
  </div>
</div>

<div class="hdr">Components</div>
<div class="no-confirm-banner">NO CONFIRMATIONS -- Stop and Uninstall act immediately, no prompt.</div>
<div id="components">{components_html}
</div>

<div class="card" id="cp-card">
  <div class="row comp-row">
    <b>Config putter</b>
    <span class="ver" id="cp-ver"></span>
    <span class="badge b-src" id="cp-badge">NOT INSTALLED</span>
    <span class="muted small">confputter.py &middot; runs on demand, no service</span>
  </div>
  <div class="small muted">Puts the files of a Config getter snapshot back on this node: to undo a bad edit, to apply a copy
  you or Claude corrected, or to rebuild a wiped node. Pick a snapshot and press Preview: nothing is written until you
  tick files and press Restore. The files it replaces are saved first (Undo last restore). Passwords and keys are not in a
  snapshot: each one keeps the value this node has now, and you type any it does not have. Firewall and WireGuard files
  are marked CAREFUL and left unticked. System files (network, hosts, ssh, Wi-Fi) are never restored.</div>
  <div class="row btn-row">
    <select id="cp-snap" title="Snapshot to restore from" onchange="cpOnSelect()" style="max-width:100%;min-width:0"><option value="">Loading&hellip;</option></select>
    <button id="cp-preview-btn" onclick="cpPreview()" disabled>Preview</button>
    <button class="b-del" id="cp-undo-btn" onclick="cpUndo()" style="display:none">Undo last restore</button>
    <button class="b-del" id="cp-uninstall-btn" onclick="cpUninstall()" style="display:none">Uninstall</button>
  </div>
  <label class="small muted"><input type="checkbox" id="cp-keep" checked> Keep this node's comment lines when the copy has none (a copy with the comments stripped)</label>
  <div class="row">
    <input type="file" id="cp-file" accept=".md">
    <button onclick="cpUpload()">Upload corrected copy</button>
    <button class="b-del" id="cp-del-edited" onclick="cpDeleteEdited()" style="display:none">Delete uploaded copy</button>
  </div>
  <div class="small muted" id="cp-msg"></div>
  <div id="cp-plan"></div>
</div>

<div class="card" id="usbimp-card">
  <div style="font-weight:700;color:var(--text-bright);margin-bottom:.3rem">Import from USB Drive</div>
  <div class="small muted" style="margin-bottom:.4rem">
    Copies .py / .sh / .conf files from an attached USB drive into the library below. Same extension,
    name-match and size rules as a browser upload. A .pdf goes to Manuals, whatever group is picked.
    The drive is read-only; files on it are never changed or removed.</div>
  <div class="row">
    <select id="usbimp-drive" title="Attached USB drives"><option value="">Loading drives&hellip;</option></select>
    <select id="usbimp-cat" title="Library category to import into">
      <option value="scripts" selected>Scripts (.sh)</option>
      <option value="config">Config (.conf)</option>
      <option value="dashboard">Dashboard (.py)</option>
      <option value="sysmon">SysMon (.py)</option>
      <option value="wifimon">WiFiMon (.py)</option>
      <option value="44helper">44helper (.py)</option>
      <option value="nodelisten">Node Talker (.py)</option>
      <option value="watchdog">Watchdog (.sh)</option>
      <option value="instmon">InstMon (.py)</option>
      <option value="confgetter">Config getter (.sh)</option>
      <option value="confputter">Config putter (.py)</option>
    </select>
    <button id="usbimp-refresh">Refresh</button>
    <button id="usbimp-up" disabled>Up</button>
    <span class="small muted" id="usbimp-path"></span>
  </div>
  <div id="usbimp-list" style="margin-top:.5rem"></div>
  <div class="small muted" id="usbimp-msg" style="margin-top:.3rem"></div>
</div>

<div class="hdr">Scripts &amp; Configuration Library</div>
<div class="small muted" style="margin-bottom:.4rem">
  Run shell scripts or manage alternative configuration files. Per-component version
  libraries (Dashboard, SysMon, etc.) now live inside their component's card above.</div>
<div id="library">{library_html}
</div>

<div class="hdr">Manuals</div>
<div class="card diskimg-card collapsed" id="docs-card">
  <div class="diskimg-corner">
    <button class="diskimg-toggle" data-action="toggle_diskimg_card" data-key="docs">Show</button>
  </div>
  <div class="diskimg-card-body">
  <div class="row">
    <button id="docs-fetch">Get from GitHub</button>
    <span class="small muted" id="docs-msg"></span>
  </div>
  <div class="row" style="margin-top:.4rem">
    <input type="file" id="file-docs" data-category="docs" accept=".pdf,application/pdf">
    <button data-action="upload" data-category="docs">Upload PDF</button>
    <span id="upmsg-docs" class="small muted"></span>
  </div>
  <div class="small muted" style="margin-top:.35rem">
    The install, user and configuration manuals (PDF) from the docs folder on GitHub, and any other PDF you
    upload here or import from a USB drive. They download when instmon is installed, and a Full Update
    fetches any that are new or changed on GitHub. Open shows one in a new tab in the browser's own PDF reader;
    Download saves it. Get from GitHub only fetches files that are new or changed.</div>
  <div id="docs-list" style="margin-top:.5rem"></div>
  </div>
</div>

<div class="hdr">Backup &amp; Export</div>  <!-- [PHASE 3] -->
<div class="card">
  <div class="row">
    <button id="backup-btn" style="background:var(--grn);color:#070b10;border-color:var(--grn)">Download Full Backup (ZIP)</button>
    <span class="small muted">Archive all files in the library directory.</span>
  </div>
</div>

<div class="hdr">Disk Image &amp; Clone</div>
<div class="card diskimg-intro">
  <div class="diskimg-corner">
    <button class="diskimg-help-toggle" data-action="toggle_diskimg_help">Help</button>
  </div>
  <div class="diskimg-help small muted">
    Images/formats the Pi's whole boot disk or an attached USB drive
    (including an SD card in a USB adapter). Not the same as Backup
    &amp; Export above, which archives instmon's own library directory.
    Attached drives refresh automatically every 5s.</div>
  <div id="diskimg-deps" class="small">Checking dependencies&hellip;</div>
  <div class="row" style="justify-content:flex-end">
    <button id="diskimg-refresh-btn">Refresh Now</button>
  </div>
</div>

<div class="hdr">Full Format</div>
<div class="card danger-card diskimg-card collapsed" data-diskimg-key="format">
  <div class="diskimg-corner">
    <button class="diskimg-help-toggle" data-action="toggle_diskimg_help">Help</button>
    <button class="diskimg-toggle" data-action="toggle_diskimg_card" data-key="format">Show</button>
  </div>
  <div class="diskimg-card-body">
  <div class="diskimg-help small muted">
    Wipes the destination drive completely (zero-fill), then writes a
    fresh GPT partition table with a single partition and formats it.
    Use this to prep a blank SD card/USB drive from scratch -- not for
    the Pi's own boot disk, which is never selectable here. Tick Quick
    format to skip the full zero-fill and clear only the start of the
    drive (old partition table and filesystem headers) -- much faster,
    but the rest of the old data stays on the drive, so it is not a
    secure erase.</div>
  <div class="diskimg-step"><span class="diskimg-step-n">1</span>Pick drive</div>
  <div class="diskimg-step-body">
    <div id="diskimg-drives-table" class="small muted">Loading attached drives&hellip;</div>
    <div class="row" style="margin-top:.4rem">
      <select id="diskimg-format-dest"><option value="">Loading drives&hellip;</option></select>
    </div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">2</span>Options</div>
  <div class="diskimg-step-body">
    <div class="row">
      <select id="diskimg-format-fs">
        <option value="ext4" selected>ext4 (recommended)</option>
        <option value="fat32">FAT32</option>
        <option value="exfat">exFAT</option>
      </select>
      <label class="small muted" style="white-space:nowrap" title="Clears only the start of the drive (old partition table and filesystem headers), then partitions and formats. Takes seconds instead of the drive's full write time. NOT a secure erase: the rest of the old data stays on the drive."><input type="checkbox" id="diskimg-format-quick"> Quick format</label>
    </div>
    <div class="diskimg-help small muted">ext4: Linux-native, journaled (safer against corruption if the card is pulled without unmounting), no file-size limit -- best choice for a drive that lives on this Pi or is read from other Linux tools. FAT32: read/write on virtually anything, but individual files over 4GB will fail to write -- a problem if this drive will ever hold a raw disk-image backup. exFAT: no practical file-size limit and reads/writes on Windows/macOS/Linux, but not journaled.</div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">3</span>Check</div>
  <div class="diskimg-step-body">
    <div id="diskimg-format-prereqs" class="small">Pick a destination drive to check prerequisites.</div>
    <input type="text" id="diskimg-format-cmd" class="diskimg-cmd placeholder" readonly value="Pick a destination drive to preview the command">
    <div id="diskimg-format-cmd-note" class="diskimg-cmd-note"></div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">4</span>Run</div>
  <div class="diskimg-step-body">
    <div class="row">
      <button class="b-danger" data-action="diskimg_format_start">Format</button>
      <button class="b-danger" data-action="diskimg_stop" data-kind="format" disabled title="Nothing is running on this card.">Stop</button>
      <button data-action="diskimg_reset" data-kind="format" title="Clear this card's last result and put its options back to their defaults for another try.">Reset</button>
    </div>
    <div id="diskimg-job-format" style="margin-top:.5rem"></div>
    <div id="diskimg-console-format" class="diskimg-console placeholder">(no job running)</div>
    <div class="row diskimg-copy-row">
      <button data-action="copy_diskimg_console" data-target="diskimg-console-format">&#9111; Copy Log</button>
    </div>
  </div>
  </div>
</div>

<div class="hdr">Backup</div>
<div class="card diskimg-card collapsed" data-diskimg-key="backup">
  <div class="diskimg-corner">
    <button class="diskimg-help-toggle" data-action="toggle_diskimg_help">Help</button>
    <button class="diskimg-toggle" data-action="toggle_diskimg_card" data-key="backup">Show</button>
  </div>
  <div class="diskimg-card-body">
  <div class="diskimg-step"><span class="diskimg-step-n">1</span>Destination</div>
  <div class="diskimg-step-body">
    <div id="diskimg-strip-backup" class="small muted" style="margin-bottom:.4rem">Loading attached drives&hellip;</div>
    <div class="row">
      <select id="diskimg-backup-dest"><option value="">Loading drives&hellip;</option></select>
      <input type="text" id="diskimg-backup-label" placeholder="optional label" style="max-width:10rem">
    </div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">2</span>Options</div>
  <div class="diskimg-step-body">
    <div class="row">
      <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-backup-shrink"> Shrink to fit</label>
      <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-backup-verify"> Verify after copy</label>
      <select id="diskimg-backup-verify-algo" title="Hash algorithm for Verify after copy">
        <option value="sha256" selected>sha256</option>
        <option value="blake2b">blake2b (faster)</option>
      </select>
      <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-backup-encrypt"> Encrypt</label>
      <input type="password" id="diskimg-backup-passphrase" placeholder="passphrase" style="max-width:9rem" autocomplete="new-password">
    </div>
    <div class="diskimg-help small muted">Shrink to fit: after copying, shrink the last partition's filesystem to its minimum size and truncate the file to match (smaller backup, slower -- needs resize2fs/parted; skipped automatically if the disk layout doesn't support it). Verify after copy: a checksum is taken of everything as it is copied, then the backup is read back from the drive and compared (slower, catches a failing drive or silent corruption dd's own exit code wouldn't); blake2b is faster than sha256 at the same integrity guarantee for this use. Every backup also saves its checksum in a .json file next to it, which Restore uses to check the backup isn't damaged. Encrypt: AES-256 encrypts the backup file with the given passphrase (openssl enc, PBKDF2) -- there's no way to recover it without that passphrase, so keep it somewhere safe; can't be combined with Shrink to fit or Verify after copy.</div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">3</span>Safety and speed</div>
  <div class="diskimg-step-body">
    <div class="row">
      <label class="small muted diskimg-quiesce" style="white-space:nowrap" title="Stops the watchdog, the suite dashboards, Asterisk and the bridges while the copy runs, so far fewer writes are in flight. The node is OFF THE AIR for the whole job. The image is still crash-consistent, not a filesystem snapshot."><input type="checkbox" id="diskimg-backup-quiesce"> Pause node services during copy</label>
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
    <div class="diskimg-quiesce-note diskimg-help">Pausing services reduces in-flight writes; it is not a filesystem snapshot. The image stays crash-consistent &mdash; ext4 replays its journal on the first boot of a restored card. sysmon keeps running so the node stays observable.</div>
    <div class="diskimg-help small muted">Freeze filesystem during copy: pauses writes to this Pi's own root filesystem for the duration of the copy so the image is crash-consistent without needing a real snapshot; only offered alongside Pause node services. Continue past read errors: skips and nulls-out unreadable sectors on the source instead of aborting -- off by default, since a failed backup is a clearer signal than a silently incomplete one. Resilient (ddrescue): retries bad sectors instead of skipping them; can't be combined with Encrypt or a bandwidth throttle. Bandwidth throttle: caps the copy's write speed to go easier on a small/shared-bus board -- runs as a shell pipeline that does not currently survive an instmon restart. On a normal Raspberry Pi OS card only the partitions are copied, not the empty space after them, so backups are smaller and faster. Copies run at low disk and CPU priority so the node stays responsive.</div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">4</span>Check</div>
  <div class="diskimg-step-body">
    <textarea id="diskimg-backup-cmd" class="diskimg-cmd placeholder" readonly rows="1" spellcheck="false">Pick a destination drive to preview the command</textarea>
    <div id="diskimg-backup-cmd-note" class="diskimg-cmd-note"></div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">5</span>Run</div>
  <div class="diskimg-step-body">
    <div class="row">
      <button class="b-danger" data-action="diskimg_backup_start">Create Backup</button>
      <button class="b-danger" data-action="diskimg_stop" data-kind="backup" disabled title="Nothing is running on this card.">Stop</button>
      <button data-action="diskimg_reset" data-kind="backup" title="Clear this card's last result and put its options back to their defaults for another try.">Reset</button>
    </div>
    <div id="diskimg-job-backup" style="margin-top:.5rem"></div>
    <div id="diskimg-console-backup" class="diskimg-console placeholder">(no job running)</div>
    <div class="row diskimg-copy-row">
      <button data-action="copy_diskimg_console" data-target="diskimg-console-backup">&#9111; Copy Log</button>
    </div>
  </div>
  <div class="diskimg-sub">Existing Backups</div>
  <div id="diskimg-backups" class="small muted">Loading&hellip;</div>
  <div class="diskimg-sub">Scheduled Backups</div>
  <div class="row">
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-sched-enabled"> Enabled</label>
    <span class="small muted">every</span>
    <input type="number" id="diskimg-sched-interval" min="1" max="720" step="1" style="max-width:5rem" value="24">
    <span class="small muted">hours to</span>
    <select id="diskimg-sched-dest"><option value="">Loading drives&hellip;</option></select>
  </div>
  <div class="row" style="margin-top:.3rem">
    <span class="small muted" title="Only backups made by the schedule (.sched.img) are deleted. Backups you made yourself are never touched.">keep newest scheduled</span>
    <input type="number" id="diskimg-sched-retention" min="1" max="50" step="1" style="max-width:5rem" value="5">
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-sched-shrink"> Shrink to fit</label>
    <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-sched-verify"> Verify after copy</label>
    <label class="small muted diskimg-quiesce" style="white-space:nowrap" title="UNATTENDED: the node goes off the air on its own, at the scheduled time, with nobody watching. Services are restarted automatically when the job ends."><input type="checkbox" id="diskimg-sched-quiesce"> Pause node services during copy</label>
    <input type="text" id="diskimg-sched-label" placeholder="label" style="max-width:8rem" value="auto">
  </div>
  <div class="row" style="margin-top:.3rem">
    <button data-action="diskimg_schedule_save">Save Schedule</button>
  </div>
  <div id="diskimg-schedule-status" class="small muted" style="margin-top:.3rem">Loading schedule&hellip;</div>
  </div>
</div>

<div class="hdr">Clone</div>
<div class="card diskimg-card collapsed" data-diskimg-key="clone">
  <div class="diskimg-corner">
    <button class="diskimg-help-toggle" data-action="toggle_diskimg_help">Help</button>
    <button class="diskimg-toggle" data-action="toggle_diskimg_card" data-key="clone">Show</button>
  </div>
  <div class="diskimg-card-body">
  <div class="diskimg-help small muted">Direct copy, no backup file -- for a spare drive plugged in right now (e.g. an SD card in a USB adapter). Destination must be unmounted first.</div>
  <div class="diskimg-step"><span class="diskimg-step-n">1</span>Destination</div>
  <div class="diskimg-step-body">
    <div id="diskimg-strip-clone" class="small muted" style="margin-bottom:.4rem">Loading attached drives&hellip;</div>
    <div class="row">
      <select id="diskimg-clone-dest"><option value="">Loading drives&hellip;</option></select>
    </div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">2</span>Copy method</div>
  <div class="diskimg-step-body">
    <div class="row">
      <select id="diskimg-clone-backend" title="Copy backend">
        <option value="dd" selected>Standard (dd)</option>
        <option value="ddrescue">Resilient (ddrescue)</option>
        <option value="rpiclone" disabled>File sync (rpi-clone) -- not installed</option>
      </select>
      <span class="small muted" id="diskimg-rpiclone-status">rpi-clone: checking&hellip;</span>
      <button data-action="rpiclone_install" id="diskimg-rpiclone-install-btn">Install rpi-clone</button>
    </div>
    <div class="row" style="margin-top:.3rem">
      <label class="small muted" style="white-space:nowrap" title="rpi-clone -f: repartition the destination and copy everything, even if it already holds a matching clone."><input type="checkbox" id="diskimg-clone-rpi-force" disabled> Force re-initialize</label>
      <input type="text" id="diskimg-clone-rpi-host" placeholder="hostname for the clone (optional)" style="max-width:14rem" maxlength="63" disabled>
    </div>
    <div class="diskimg-help small muted">File sync (rpi-clone): copies files instead of every block, so the destination only needs room for the space actually used, and cloning again onto the same card only copies what changed. The first clone onto a card (or Force re-initialize) partitions it and erases it. The clone gets its own partition IDs, and a new hostname if you enter one. No percentage is shown -- watch the console. Install rpi-clone downloads a fixed, checksum-checked version from GitHub and installs the packages it needs, with no prompts; its output goes to the Execution Log. Verify, Freeze, Continue past read errors, Direct I/O and the throttle don't apply to it.</div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">3</span>Options</div>
  <div class="diskimg-step-body">
    <div class="row">
      <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-clone-verify"> Verify after copy</label>
      <select id="diskimg-clone-verify-algo" title="Hash algorithm for Verify after copy">
        <option value="sha256" selected>sha256</option>
        <option value="blake2b">blake2b (faster)</option>
      </select>
      <label class="small muted diskimg-quiesce" style="white-space:nowrap" title="Stops the watchdog, the suite dashboards, Asterisk and the bridges while the copy runs, so far fewer writes are in flight. The node is OFF THE AIR for the whole job. The image is still crash-consistent, not a filesystem snapshot."><input type="checkbox" id="diskimg-clone-quiesce"> Pause node services during copy</label>
      <label class="small muted" style="white-space:nowrap" title="Sub-option of Pause node services -- freezes the root filesystem for the copy so the image is crash-consistent without a snapshot. Requires Pause node services to be ticked."><input type="checkbox" id="diskimg-clone-freeze" disabled> Freeze filesystem during copy</label>
    </div>
    <div class="row" style="margin-top:.3rem">
      <label class="small muted" style="white-space:nowrap" title="Continue past a read error on the source instead of aborting the clone. Skipped sectors are padded with nulls."><input type="checkbox" id="diskimg-clone-best-effort"> Continue past read errors</label>
      <label class="small muted" style="white-space:nowrap" title="Bypass the page cache on the write side -- steadier write behavior on a small/shared-bus board."><input type="checkbox" id="diskimg-clone-direct-io"> Direct I/O</label>
      <label class="small muted" style="white-space:nowrap" title="After the copy, grow the last partition and its ext4 filesystem to use the whole destination drive."><input type="checkbox" id="diskimg-clone-expand" checked> Expand to fill drive</label>
      <label class="small muted" style="white-space:nowrap" title="Give the copy its own disk and partition IDs, and update its cmdline.txt and fstab to match, so this Pi can't boot from the copy by mistake if it is left plugged in."><input type="checkbox" id="diskimg-clone-new-ids" checked> New disk IDs</label>
      <select id="diskimg-clone-throttle" title="Bandwidth throttle">
        <option value="" selected>No throttle</option>
        <option value="5">5 MB/s</option>
        <option value="10">10 MB/s</option>
        <option value="20">20 MB/s</option>
      </select>
    </div>
    <div class="diskimg-quiesce-note diskimg-help">Pausing services reduces in-flight writes; it is not a filesystem snapshot. The image stays crash-consistent &mdash; ext4 replays its journal on the first boot of a restored card. sysmon keeps running so the node stays observable.</div>
    <div class="diskimg-help small muted">Freeze filesystem during copy: pauses writes to this Pi's own root filesystem for the duration of the copy; only offered alongside Pause node services. Continue past read errors: skips and nulls-out unreadable sectors on the source instead of aborting -- off by default. Direct I/O: bypasses the page cache on the write side; offered here since Clone's destination is always a raw block device. Resilient (ddrescue): retries bad sectors instead of skipping them; can't be combined with Continue past read errors, Direct I/O, or a bandwidth throttle. Bandwidth throttle: caps the copy's write speed -- runs as a shell pipeline that does not currently survive an instmon restart. Expand to fill drive: grows the copy's last partition to use the whole destination. New disk IDs: gives the copy its own disk and partition IDs and updates its cmdline.txt and fstab, so a copy left plugged in can't be booted by mistake. On a normal Raspberry Pi OS card only the partitions are copied, not the empty space after them, so a destination only needs to be as big as the partitions. Copies run at low disk and CPU priority so the node stays responsive.</div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">4</span>Check</div>
  <div class="diskimg-step-body">
    <textarea id="diskimg-clone-cmd" class="diskimg-cmd placeholder" readonly rows="1" spellcheck="false">Pick a destination drive to preview the command</textarea>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">5</span>Run</div>
  <div class="diskimg-step-body">
    <div class="row">
      <button class="b-danger" data-action="diskimg_clone_start">Clone Now</button>
      <button class="b-danger" data-action="diskimg_stop" data-kind="clone" disabled title="Nothing is running on this card.">Stop</button>
      <button data-action="diskimg_reset" data-kind="clone" title="Clear this card's last result and put its options back to their defaults for another try.">Reset</button>
    </div>
    <div id="diskimg-job-clone" style="margin-top:.5rem"></div>
    <div id="diskimg-console-clone" class="diskimg-console placeholder">(no job running)</div>
    <div class="row diskimg-copy-row">
      <button data-action="copy_diskimg_console" data-target="diskimg-console-clone">&#9111; Copy Log</button>
    </div>
  </div>
  </div>
</div>

<div class="hdr">Restore</div>
<div class="card diskimg-card collapsed" data-diskimg-key="restore">
  <div class="diskimg-corner">
    <button class="diskimg-help-toggle" data-action="toggle_diskimg_help">Help</button>
    <button class="diskimg-toggle" data-action="toggle_diskimg_card" data-key="restore">Show</button>
  </div>
  <div class="diskimg-card-body">
  <div class="diskimg-help small muted">
    Writes to a spare drive only -- never onto the disk this Pi is currently running from. Destination must be unmounted first. Backups marked "encrypted" below need their passphrase entered here; Verify after copy and Bandwidth throttle aren't supported for those. A backup with a saved checksum is checked as it is read; if it doesn't match, the restore is marked failed. Expand to fill drive grows the last partition afterward -- leave it on for a backup made with Shrink to fit, or the restored node keeps only its shrunk size. New disk IDs gives the restored drive its own IDs and updates its cmdline.txt and fstab to match.</div>
  <div class="diskimg-step"><span class="diskimg-step-n">1</span>Pick backup</div>
  <div class="diskimg-step-body">
    <div class="row">
      <select id="diskimg-restore-image"><option value="">No backups available</option></select>
    </div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">2</span>Destination</div>
  <div class="diskimg-step-body">
    <div id="diskimg-strip-restore" class="small muted" style="margin-bottom:.4rem">Loading attached drives&hellip;</div>
    <div class="row">
      <select id="diskimg-restore-dest"><option value="">Loading drives&hellip;</option></select>
    </div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">3</span>Options</div>
  <div class="diskimg-step-body">
    <div class="row">
      <input type="password" id="diskimg-restore-passphrase" placeholder="passphrase (if encrypted)" style="max-width:12rem" autocomplete="new-password">
      <label class="small muted" style="white-space:nowrap"><input type="checkbox" id="diskimg-restore-verify"> Verify after copy</label>
      <select id="diskimg-restore-verify-algo" title="Hash algorithm for Verify after copy">
        <option value="sha256" selected>sha256</option>
        <option value="blake2b">blake2b (faster)</option>
      </select>
      <label class="small muted" style="white-space:nowrap" title="After the restore, grow the last partition and its ext4 filesystem to use the whole drive. Needed for a backup made with Shrink to fit."><input type="checkbox" id="diskimg-restore-expand" checked> Expand to fill drive</label>
      <label class="small muted" style="white-space:nowrap" title="Give the restored drive its own disk and partition IDs, and update its cmdline.txt and fstab to match, so it can't be confused with this Pi's own disk."><input type="checkbox" id="diskimg-restore-new-ids" checked> New disk IDs</label>
      <select id="diskimg-restore-throttle" title="Bandwidth throttle (unencrypted backups only)">
        <option value="" selected>No throttle</option>
        <option value="5">5 MB/s</option>
        <option value="10">10 MB/s</option>
        <option value="20">20 MB/s</option>
      </select>
    </div>
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">4</span>Check</div>
  <div class="diskimg-step-body">
    <input type="text" id="diskimg-restore-cmd" class="diskimg-cmd placeholder" readonly value="Pick a backup and destination drive to preview the command">
  </div>
  <div class="diskimg-step"><span class="diskimg-step-n">5</span>Run</div>
  <div class="diskimg-step-body">
    <div class="row">
      <button class="b-danger" data-action="diskimg_restore_start">Restore</button>
      <button class="b-danger" data-action="diskimg_stop" data-kind="restore" disabled title="Nothing is running on this card.">Stop</button>
      <button data-action="diskimg_reset" data-kind="restore" title="Clear this card's last result and put its options back to their defaults for another try.">Reset</button>
    </div>
    <div id="diskimg-job-restore" style="margin-top:.5rem"></div>
    <div id="diskimg-console-restore" class="diskimg-console placeholder">(no job running)</div>
    <div class="row diskimg-copy-row">
      <button data-action="copy_diskimg_console" data-target="diskimg-console-restore">&#9111; Copy Log</button>
    </div>
  </div>
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
"lib_lock":lambda self ,body :self ._action_lib_lock (body ),
"run_script":lambda self ,body :self ._action_run_script (body ),
"rpiclone_install":lambda self ,body :self ._action_rpiclone_install (body ),
"save_alternate":lambda self ,body :self ._action_save_alternate (body ),
"comms_restart":lambda self ,body :self ._action_comms_restart (body ),
"reboot":lambda self ,body :self ._action_reboot (body ),
"shutdown":lambda self ,body :self ._action_shutdown (body ),
"gh_check":lambda self ,body :self ._action_gh_check (body ),
"gh_update":lambda self ,body :self ._action_gh_update (body ),
"quiet":lambda self ,body :self ._action_quiet (body ),
"restore":lambda self ,body :self ._action_restore (body ),
"full_update":lambda self ,body :self ._action_full_update (body ),
"fu_dismiss":lambda self ,body :self ._action_fu_dismiss (body ),
"fu_stop":lambda self ,body :self ._action_fu_stop (body ),
"build_pref":lambda self ,body :self ._action_build_pref (body ),
"gh_channel":lambda self ,body :self ._action_gh_channel (body ),
"app_fetch":lambda self ,body :self ._action_app_fetch (body ),
"app_delete":lambda self ,body :self ._action_app_delete (body ),
"install_confgetter":lambda self ,body :self ._action_cg (body ,"install"),
"cg_run":lambda self ,body :self ._action_cg (body ,"run"),
"cg_uninstall":lambda self ,body :self ._action_cg (body ,"uninstall"),
"cg_delete":lambda self ,body :self ._action_cg (body ,"delete"),
"install_confputter":lambda self ,body :self ._action_cp (body ,"install"),
"cp_uninstall":lambda self ,body :self ._action_cp (body ,"uninstall"),
"cp_preview":lambda self ,body :self ._action_cp (body ,"preview"),
"cp_apply":lambda self ,body :self ._action_cp (body ,"apply"),
"cp_undo":lambda self ,body :self ._action_cp (body ,"undo"),
"cp_delete_edited":lambda self ,body :self ._action_cp (body ,"delete_edited"),
}

_ACTIONS_DURING_FULL_UPDATE = ("fu_dismiss", "fu_stop")

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
"/api/usbimport/drives":lambda self :self ._route_usbimport_drives (),
"/api/docs":lambda self :self ._send_json (200 ,docs_status (),extra_headers =[("Cache-Control","no-store")]),
"/api/docs/file":lambda self :self ._route_docs_file (),
"/api/app/file":lambda self :self ._route_app_file (),
"/api/confgetter/file":lambda self :self ._route_cg_file (),
"/api/usbimport/browse":lambda self :self ._route_usbimport_browse (),
"/api/diskimg/drives":lambda self :self ._route_diskimg_drives (),
"/api/diskimg/job":lambda self :self ._route_diskimg_job (),
"/api/diskimg/backup/list":lambda self :self ._route_diskimg_backup_list (),
"/api/diskimg/backup/download":lambda self :self ._route_diskimg_backup_download (),
"/api/diskimg/schedule":lambda self :self ._route_diskimg_schedule_get (),
}

_POST_ROUTES ={
"/api/upload":lambda self :self .handle_upload (),
"/api/confputter/upload":lambda self :self ._route_cp_upload (),
"/api/usbimport/import":lambda self :self .handle_usbimport_import (),
"/api/docs/fetch":lambda self :self .handle_docs_fetch (),
"/api/docs/delete":lambda self :self .handle_docs_delete (),
"/api/action":lambda self :self .handle_action (),
"/api/file":lambda self :self .handle_file_write (),
"/api/diskimg/preview":lambda self :self .handle_diskimg_preview (),
"/api/diskimg/backup/start":lambda self :self .handle_diskimg_backup_start (),
"/api/diskimg/backup/delete":lambda self :self .handle_diskimg_backup_delete (),
"/api/diskimg/job/cancel":lambda self :self .handle_diskimg_job_cancel (),
"/api/diskimg/job/reset":lambda self :self .handle_diskimg_job_reset (),
"/api/diskimg/unmount":lambda self :self .handle_diskimg_unmount (),
"/api/diskimg/mount":lambda self :self .handle_diskimg_mount (),
"/api/diskimg/eject":lambda self :self .handle_diskimg_eject (),
"/api/diskimg/format/start":lambda self :self .handle_diskimg_format_start (),
"/api/diskimg/clone/start":lambda self :self .handle_diskimg_clone_start (),
"/api/diskimg/restore/start":lambda self :self .handle_diskimg_restore_start (),
"/api/diskimg/schedule":lambda self :self .handle_diskimg_schedule_set (),
}

class InstmonHandler (http .server .BaseHTTPRequestHandler ):
    server_version =f"instmon/{VERSION }"
    timeout =60 

    def send_response (self ,code ,message =None ):
        super ().send_response (code ,message )
        self .send_header ("X-Content-Type-Options","nosniff")
        self .send_header ("Referrer-Policy","no-referrer")
        if getattr (self ,"_pdf_response",False ):
            return
        self .send_header ("X-Frame-Options","DENY")
        self .send_header (
        "Content-Security-Policy",
        "default-src 'self'; frame-ancestors 'none'; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
        )

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
        now = time.time()
        with _auth_log_lock:
            last, suppressed = _auth_log_state.get(client_ip, (0.0, 0))
            if now - last >= 60:
                _auth_log_state[client_ip] = (now, 0)
                note = f" -- {suppressed} more from this browser in the last minute were not logged" if suppressed else ""
                log_event(f"HTTP 401: Authentication required ({self.command} {self.path}) from {client_ip}{note}", "err")
            else:
                _auth_log_state[client_ip] = (last, suppressed + 1)
        self._send_json(401, {"error": "Authentication required"})

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
        "components_html":render_components_html (status ["components"],status ["library"],status ["app"],status ["confgetter"]),
        "library_html":render_library_html (status ["library"]),
        **_gh_status_payload (),
        **_fu_status_payload (),
        })

    def _route_gateway(self):
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
        boot_disk = _get_boot_disk()
        self._send_json(200, {
            "drives": _list_usb_drives(),
            "boot_disk_detected": bool(boot_disk),
            "deps": _diskimg_check_dependencies(),
            "rpiclone": _rpiclone_status(),
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

    def handle_diskimg_eject(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        if not body.get("confirm"):
            self._error_json(400, "Eject requires confirm:true in the request body")
            return
        dest_device = body.get("dest_device")
        match = next(
            (d for d in _list_usb_drives() if dest_device and (d["path"] == dest_device or d["name"] == dest_device)),
            None,
        )
        if match is None:
            self._error_json(400, f"'{dest_device}' is not a currently attached USB drive")
            return
        if match["is_boot_disk"]:
            self._error_json(400, "Refusing to eject the boot disk -- that's this Pi's own root filesystem")
            return
        busy = _diskimg_busy_reason()
        if busy:
            self._error_json(409, busy)
            return
        try:
            subprocess.run(["sync"], capture_output=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log_event(f"Eject {match['path']}: sync failed: {exc}", "warn")
        errors = _diskimg_unmount_all(match.get("mounted_at") or [])
        if errors:
            self._error_json(500, "Could not unmount, so the drive was not ejected: " + "; ".join(errors))
            return
        ok, how = _diskimg_power_off(match)
        if not ok:
            log_event(f"Eject {match['path']}: unmounted, but could not power it off: {how}", "warn")
            self._send_json(200, {"message": f"Unmounted {match['path']} -- safe to remove (it could not be powered off: {how}).", "level": "warn"})
            return
        log_event(f"Ejected {match['path']} ({how})", "info")
        self._send_json(200, {"message": f"Ejected {match['path']} -- safe to unplug.", "level": "ok"})

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

        cfg = _diskimg_schedule_load()
        drive = next((d for d in _list_usb_drives() if dest_device and (d["path"] == dest_device or d["name"] == dest_device)), None)
        if drive is not None:
            if enabled and not drive.get("fs_uuids"):
                self._error_json(400, f"{drive['path']} has no filesystem -- format it on the Full Format card first.")
                return
            cfg["dest_uuid"] = (drive.get("fs_uuids") or [None])[0]
        elif dest_device != cfg.get("dest_device"):
            cfg["dest_uuid"] = None
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
        copy_size, _extent_note = _diskimg_copy_extent(src_path, src_size)
        if match["size"] < copy_size:
            self._error_json(
                400,
                f"{match['path']} ({fmt_bytes(match['size'])}) is smaller than the boot disk's partitions "
                f"({fmt_bytes(copy_size)}) -- a raw image needs a destination at least as large",
            )
            return

        mountpoint, _we_mounted = _diskimg_ensure_mounted(match["name"])
        if mountpoint is None:
            self._error_json(500, f"Could not find or mount a writable filesystem on {match['path']}")
            return
        if _diskimg_busy_reason() is None:
            _diskimg_clear_stale_parts(os.path.join(mountpoint, _DISKIMG_BACKUP_DIRNAME))
        try:
            free = shutil.disk_usage(mountpoint).free
        except OSError as exc:
            self._error_json(500, f"Could not check free space on {mountpoint}: {exc}")
            return
        if free < copy_size:
            self._error_json(
                400,
                f"Not enough free space on {match['path']} ({fmt_bytes(free)} free, need {fmt_bytes(copy_size)})",
            )
            return
        fat_reason = _diskimg_fat_limit_reason(mountpoint, copy_size, match["path"])
        if fat_reason:
            self._error_json(400, fat_reason)
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
        subprocess.run(["sync"], capture_output=True, timeout=30)
        part_path = dest_path + _DISKIMG_PART_SUFFIX
        ok, result = _diskimg_start_job(
            "backup", src_path, part_path, src_path, part_path, copy_size,
            copy_bytes=copy_size if copy_size < src_size else None,
            shrink_requested=shrink, verify_requested=verify,
            encrypt_passphrase=passphrase if encrypt else None,
            quiesce_requested=quiesce,
            best_effort_requested=best_effort, backend=backend,
            throttle_rate_mb=throttle_rate_mb, freeze_requested=freeze,
            verify_algo=verify_algo,
        )
        passphrase = None
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
        _diskimg_remove_sidecar(match["path"])
        log_event(f"Deleted disk-image backup: {match['name']}", "warn")
        self._send_json(200, {"message": f"Deleted {match['name']}.", "level": "ok"})

    def handle_diskimg_job_cancel(self):
        ok, message = _diskimg_cancel_job()
        if not ok:
            self._error_json(409, message)
            return
        self._send_json(200, {"message": message, "level": "warn"})

    def handle_diskimg_job_reset(self):
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
        if _diskimg_job_running():
            self._error_json(409, "A disk-image job is running -- wait for it to finish before unmounting.")
            return
        try:
            subprocess.run(["sync"], capture_output=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log_event(f"Unmount {match['path']}: sync failed: {exc}", "warn")
        errors = _diskimg_unmount_all(mountpoints)
        if errors:
            log_event(f"Unmount {match['path']}: {'; '.join(errors)}", "warn")
            self._error_json(500, "Could not unmount: " + "; ".join(errors))
            return
        log_event(f"Unmounted {match['path']} ({', '.join(mountpoints)})", "info")
        self._send_json(200, {"message": f"Unmounted {match['path']} -- safe to remove.", "level": "ok"})

    def handle_diskimg_mount(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        if not body.get("confirm"):
            self._error_json(400, "Mount requires confirm:true in the request body")
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
            self._error_json(400, "Refusing to mount the boot disk -- it is this Pi's own root filesystem")
            return
        if _diskimg_job_running():
            self._error_json(409, "A disk-image job is running -- wait for it to finish before mounting.")
            return
        result, err = _diskimg_mount_all(match["name"])
        if result is None:
            self._error_json(500, f"Could not mount {match['path']}: {err}")
            return
        parts = []
        if result["mounted"]:
            parts.append("mounted " + ", ".join(result["mounted"]))
        if result["already"]:
            parts.append("already mounted " + ", ".join(result["already"]))
        if result["skipped"]:
            parts.append("skipped " + ", ".join(result["skipped"]))
        if result["errors"]:
            parts.append("failed " + "; ".join(result["errors"]))
        if not parts:
            self._error_json(400, f"{match['path']} has no filesystem to mount -- format it first.")
            return
        summary = f"{match['path']}: " + "; ".join(parts)
        if result["errors"]:
            log_event(f"Mount {summary}", "err" if not result["mounted"] else "warn")
            self._send_json(200 if result["mounted"] else 500,
                            {"message": summary, "level": "warn" if result["mounted"] else "err"})
            return
        log_event(f"Mount {summary}", "info")
        self._send_json(200, {"message": summary, "level": "ok" if result["mounted"] or result["already"] else "warn"})

    def handle_diskimg_format_start(self):
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
        if not _get_boot_disk():
            self._error_json(409, "Could not determine this Pi's boot disk -- refusing to start a format until this resolves.")
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
        if backend not in ("dd", "ddrescue", "rpiclone"):
            self._error_json(400, "Unknown 'backend' -- must be 'dd', 'ddrescue' or 'rpiclone'")
            return
        rpiclone_args = None
        if backend == "rpiclone":
            if not _rpiclone_status()["installed"]:
                self._error_json(400, "rpi-clone is not installed -- press Install rpi-clone on the Clone card first.")
                return
            if body.get("freeze"):
                self._error_json(400, "Freeze filesystem can't be used with File sync (rpi-clone) -- it would hang rpi-clone. Untick it.")
                return
            rpi_host = (body.get("rpi_hostname") or "").strip()
            if rpi_host and not _RPICLONE_HOST_RE.fullmatch(rpi_host):
                self._error_json(400, "Hostname for the clone: letters, digits and dashes only, up to 63 characters.")
                return
            rpiclone_args = _rpiclone_args(bool(body.get("rpi_force")), rpi_host or None)
            boot_ok, boot_detail = _rpiclone_prepare_boot()
            if not boot_ok:
                self._error_json(409, boot_detail)
                return
            verify = best_effort = direct_io = False
            body["throttle_rate_mb"] = None
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
        copy_size, _extent_note = _diskimg_copy_extent(src_path, src_size)
        if backend != "rpiclone" and match["size"] < copy_size:
            self._error_json(
                400,
                f"{match['path']} ({fmt_bytes(match['size'])}) is smaller than the boot disk's partitions "
                f"({fmt_bytes(copy_size)}) -- a raw clone needs a destination at least as large",
            )
            return
        expand = bool(body.get("expand")) and backend != "rpiclone"
        new_ids = bool(body.get("new_ids")) and backend != "rpiclone"

        quiesce = bool(body.get("quiesce"))
        subprocess.run(["sync"], capture_output=True, timeout=30)
        ok, result = _diskimg_start_job(
            "clone", src_path, match["path"], src_path, match["path"],
            0 if backend == "rpiclone" else copy_size,
            copy_bytes=copy_size if copy_size < src_size else None,
            expand_requested=expand, new_ids_requested=new_ids,
            verify_requested=verify, quiesce_requested=quiesce,
            best_effort_requested=best_effort, direct_io_requested=direct_io,
            backend=backend, throttle_rate_mb=throttle_rate_mb,
            freeze_requested=freeze, verify_algo=verify_algo,
            rpiclone_args=rpiclone_args,
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
                + (" Using File sync (rpi-clone): no percentage is shown, watch the console." if backend == "rpiclone" else "")
                + (f" Throttled to {throttle_rate_mb:g} MB/s." if throttle_rate_mb else "")
                + (f" Copying {fmt_bytes(copy_size)} (the partitions) of the {fmt_bytes(src_size)} disk." if (backend != "rpiclone" and copy_size < src_size) else "")
                + (" The copy then gets new disk IDs." if new_ids else "")
                + (" Its last partition is then expanded to fill the drive." if expand else "")
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
        sidecar = _diskimg_read_sidecar(image["path"])
        if sidecar and sidecar["size"] != image["size"]:
            self._error_json(400, (f"{image['name']} is {fmt_bytes(image['size'])}, but its checksum file says it should be "
                                   f"{fmt_bytes(sidecar['size'])} -- the backup is damaged or incomplete."))
            return
        expand = bool(body.get("expand"))
        new_ids = bool(body.get("new_ids"))

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
            hash_algo=sidecar["algo"] if sidecar else verify_algo,
            expect_hash=sidecar["hash"] if sidecar else None,
            expand_requested=expand, new_ids_requested=new_ids,
        )
        passphrase = None
        if not ok:
            self._error_json(409, result)
            return
        self._send_json(200, {
            "message": (
                f"Restore started: {image['name']} -> {match['path']}. This can take a long time -- watch the progress panel."
                + (" It will be decrypted on the way out." if image["encrypted"] else "")
                + (" The backup is checked against its saved checksum as it is read." if sidecar else "")
                + (" The last partition is expanded to fill the drive afterward." if expand else "")
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
                    dirs [:]=[d for d in dirs if os .path .join (root ,d )not in (DOCS_DIR ,APP_DIR ,SNAP_DIR )]
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
        if lib_locked_path (target ):
            log_event (f"Refused to save an edit to locked {filename }","warn")
            self ._error_json (409 ,_locked_msg (os .path .basename (target )))
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
        if filename and filedata is not None and os .path .splitext (filename )[1 ].lower ()==".pdf":
            status ,payload =docs_stage (os .path .basename (filename ),filedata ,"upload")
            if status !=200 :
                self ._error_json (status ,payload ["error"])
                return 
            self ._send_json (status ,payload )
            return 
        if category =="docs":
            self ._error_json (400 ,"Only PDF files go in Manuals.")
            return 
        status ,payload =_stage_library_file (category ,filename ,filedata ,force ,"upload")
        if status !=200 and not payload .get ("mismatch"):
            self ._error_json (status ,payload ["error"])
            return 
        self ._send_json (status ,payload )

    def _route_docs_file(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        name = query.get("name", [""])[0]
        full = docs_path(name)
        if full is None:
            self._error_json(404, "No such manual")
            return
        disposition = "attachment" if query.get("download", [""])[0] == "1" else "inline"
        try:
            size = os.path.getsize(full)
            fh = open(full, "rb")
        except OSError as exc:
            self._error_json(500, f"Could not read {name}: {exc}")
            return
        with fh:
            self._pdf_response = True
            try:
                self.send_response(200)
            finally:
                self._pdf_response = False
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'{disposition}; filename="{name}"')
            self.send_header("Cache-Control", "private, no-cache")
            self.end_headers()
            try:
                shutil.copyfileobj(fh, self.wfile, 65536)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def handle_docs_delete(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 4096:
            self._error_json(400, "Missing or oversized request body")
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        name = body.get("name") if isinstance(body, dict) else None
        status, payload = docs_delete(name)
        if status != 200:
            self._error_json(status, payload["error"])
            return
        self._send_json(200, payload)

    def handle_docs_fetch(self):
        ok, message = docs_start_fetch()
        if ok:
            self._send_json(200, {"ok": True, "message": message, "level": "info"})
        else:
            self._send_json(409, {"error": message, "message": message, "level": "warn"})

    def _route_usbimport_drives(self):
        drives = [
            {"name": d["name"], "model": d["model"], "size": d["size"]}
            for d in _list_usb_drives() if not d["is_boot_disk"]
        ]
        self._send_json(200, {"drives": drives})

    def _route_usbimport_browse(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        name = query.get("drive", [""])[0]
        rel = query.get("path", [""])[0]
        status, payload = _usbimport_run(name, lambda mp: _usbimport_browse(mp, rel))
        if status != 200:
            self._error_json(status, payload["error"])
            return
        self._send_json(200, payload)

    def handle_usbimport_import(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 8192:
            self._error_json(400, "Missing or oversized request body")
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error_json(400, "Malformed JSON body")
            return
        if not isinstance(body, dict):
            self._error_json(400, "Malformed JSON body")
            return
        name = body.get("drive")
        rel = body.get("path")
        category = body.get("category")
        force = body.get("force") is True
        if not isinstance(rel, str) or not rel or not isinstance(category, str):
            self._error_json(400, "Missing 'path' or 'category'")
            return
        status, payload = _usbimport_run(name, lambda mp: _usbimport_import(mp, rel, category, force))
        if status != 200 and not payload.get("mismatch"):
            self._error_json(status, payload["error"])
            return
        self._send_json(status, payload)

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
        busy =_diskimg_busy_reason ()
        if busy :
            self ._send_json (409 ,{"error":busy ,"message":f"Not now: {busy }","level":"warn"})
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
        busy =_diskimg_busy_reason ()
        if busy :
            self ._send_json (409 ,{"error":busy ,"message":f"Not now: {busy }","level":"warn"})
            return 

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

    def _service_action (self ,body ,verb ,refuse ,fail_verb ,done ,levels ):

        service =body .get ("service","")
        comp =next ((c for c in COMPONENTS if c ["service"]==service ),None )
        if comp is None :
            self ._error_json (400 ,f"Unknown service '{service }'")
            return 
        if comp ["category"]=="instmon":
            self ._error_json (400 ,refuse )
            return 
        try :
            subprocess .run (["systemctl",verb ,unit_of (comp )],capture_output =True ,text =True ,timeout =10 )
        except (FileNotFoundError ,subprocess .TimeoutExpired )as exc :
            self ._error_json (500 ,f"Could not {fail_verb } {comp ['name']}: {exc }")
            return 
        time .sleep (0.5 )
        state =systemctl_is_active (unit_of (comp ))
        log_event (f"{done .capitalize ()} {comp ['name']} (now {state })",levels [0 ]if state =="active"else levels [1 ])
        self ._send_json (200 ,{
        "service":service ,
        "state":state ,
        "message":f"{comp ['name']} {done } (now {state }).",
        "level":"info",
        })

    def _action_start (self ,body ):
        self ._service_action (body ,"restart","instmon cannot start/restart itself from its own panel.","start","started",("info","warn"))

    def _action_stop (self ,body ):
        self ._service_action (body ,"stop","instmon cannot stop itself.","stop","stopped",("warn","info"))

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

        dest_name =config_dest_name (name )
        dest =os .path .join (CONFIG_DIR ,dest_name )
        is_nl =dest_name !=CONFIG_NAME 
        if dest_name in ("nodetalker.conf","nodelisten.conf")and b"[nodetalker]"not in data and b"[nodelisten]"not in data :
            self ._error_json (400 ,f"{name } has no [nodetalker] or [nodelisten] section -- it is not a Node Talker settings file.")
            return 
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

            _dash_comp =next ((c for c in COMPONENTS if c ["category"]==("nodelisten"if is_nl else "dashboard")),None )
            comp =None 
            if _dash_comp and os .path .isfile (resolve_installed_target (_dash_comp )):
                comp =_dash_comp 
            tool ="Node Talker"if is_nl else "The Dashboard"
            if comp is None :
                try :
                    wrote ,reason =compare_before_write (dest ,data )
                except OSError as exc :
                    self ._error_json (500 ,f"Install failed writing {dest }: {exc }")
                    return 
                log_event (f"Install config {name } -> {dest } ({reason })","ok"if wrote else "info")
                message =(f"Config {name } installed as {dest_name }. {tool } is not currently installed -- apply it manually."
                if wrote else f"{name } is already the active config (unchanged).")
                self ._send_json (200 ,{"wrote":wrote ,"reason":reason ,"message":message ,"level":"warn"if wrote else "info"})
                return 

            result =install_file_with_verification (data ,dest ,comp )
            if result ["reason"]=="error":
                self ._error_json (500 ,result ["message"])
                return 

            log_event (f"Install config {name } -> {dest } ({result ['reason']})","ok"if result ["wrote"]else "info")
            if result ["wrote"]:
                result ["message"]=f"Config {name } installed as {dest_name }. {result ['message']}"
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
        if lib_locked (category ,name ):
            log_event (f"Refused to delete locked {name } from the {category } library","warn")
            self ._error_json (409 ,_locked_msg (name ))
            return 
        os .remove (target )
        log_event (f"Deleted {name } from {category } library","warn")
        self ._send_json (200 ,{"deleted":name ,"message":f"Deleted {name } from the library.","level":"warn"})

    def _action_lib_lock (self ,body ):
        locked =body .get ("locked")
        if not isinstance (locked ,bool ):
            self ._error_json (400 ,"Say locked: true or false")
            return 
        code ,payload =lib_lock_set (body .get ("category"),body .get ("name"),locked ,body .get ("confirm")is True )
        if code !=200 :
            self ._error_json (code ,payload ["error"])
            return 
        self ._send_json (200 ,payload )

    def _action_rpiclone_install(self, body):
        if not body.get("confirm"):
            self._error_json(400, "Installing rpi-clone requires confirm:true in the request body")
            return
        if _diskimg_job_running():
            self._error_json(409, "A disk-image job is running -- wait for it to finish before installing rpi-clone.")
            return
        name = _RPICLONE_SCRIPT_NAME
        with _running_scripts_lock:
            if name in _running_scripts:
                self._send_json(409, {"error": f"{name} is already running",
                                      "message": f"{name} is already running -- watch the log below.", "level": "warn"})
                return
            _running_scripts.add(name)
        path = os.path.join(CONFIG_DIR, "instmon_rpiclone_install.sh")
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(path, "w") as f:
                f.write(_rpiclone_install_script())
            os.chmod(path, 0o700)
        except OSError as exc:
            with _running_scripts_lock:
                _running_scripts.discard(name)
            self._error_json(500, f"Could not write the rpi-clone install script: {exc}")
            return
        threading.Thread(target=run_script_bg, args=(path, name), daemon=True).start()
        self._send_json(200, {"started": name,
                              "message": "Installing rpi-clone -- watch the Execution Log for its output.",
                              "level": "info"})

    def _action_run_script (self ,body ):
        if not body .get ("confirm"):
            self ._error_json (400 ,"Running a script requires confirm:true in the request body")
            return 
        busy =_diskimg_busy_reason ()
        if busy :
            self ._send_json (409 ,{"error":busy ,"message":f"Not now: {busy }","level":"warn"})
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

    def _action_app_fetch (self ,body ):
        ok ,msg =app_start_fetch ()
        self ._send_json (200 if ok else 409 ,{"message":msg ,"level":"info"if ok else "warn"})

    def _action_app_delete (self ,body ):
        status ,payload =app_delete (body .get ("name"))
        if status !=200 :
            self ._error_json (status ,payload ["error"])
            return 
        self ._send_json (200 ,payload )

    def _action_cg (self ,body ,op ):
        if op in ("install","uninstall")and not body .get ("confirm"):
            self ._error_json (400 ,"This action requires confirm:true in the request body")
            return
        if op =="install":
            status ,payload =cg_install (body .get ("name"))
        elif op =="run":
            status ,payload =cg_start_run ()
        elif op =="uninstall":
            status ,payload =cg_uninstall ()
        else :
            status ,payload =cg_delete (body .get ("name"))
        if status !=200 :
            self ._send_json (status ,{"error":payload ["error"],"message":payload ["error"],"level":"warn"if status ==409 else "err"})
            return
        self ._send_json (200 ,payload )

    def _route_cg_file (self ):
        query =urllib .parse .parse_qs (urllib .parse .urlparse (self .path ).query )
        name =query .get ("name",[""])[0 ]
        full =cg_snap_path (name )
        if full is None :
            self ._error_json (404 ,"No such snapshot")
            return
        try :
            size =os .path .getsize (full )
            fh =open (full ,"rb")
        except OSError as exc :
            self ._error_json (500 ,f"Could not read {name }: {exc }")
            return
        with fh :
            self .send_response (200 )
            self .send_header ("Content-Type","text/markdown; charset=utf-8")
            self .send_header ("Content-Length",str (size ))
            self .send_header ("Content-Disposition",f'attachment; filename="{name }"')
            self .send_header ("Cache-Control","private, no-store")
            self .end_headers ()
            try :
                shutil .copyfileobj (fh ,self .wfile ,65536 )
            except (BrokenPipeError ,ConnectionResetError ):
                pass
        log_event (f"Config getter: downloaded {name }","info")

    def _action_cp (self ,body ,op ):
        if op in ("install","uninstall")and not body .get ("confirm"):
            self ._error_json (400 ,"This action requires confirm:true in the request body")
            return
        if op =="install":
            status ,payload =cp_install (body .get ("name"))
        elif op =="uninstall":
            status ,payload =cp_uninstall ()
        elif op =="preview":
            status ,payload =cp_preview (body )
        elif op =="apply":
            status ,payload =cp_apply (body )
        elif op =="undo":
            status ,payload =cp_undo (body )
        else :
            status ,payload =cp_delete_edited (body .get ("name"))
        if status !=200 :
            self ._send_json (status ,{"error":payload ["error"],"message":payload ["error"],"level":"warn"if status ==409 else "err"})
            return
        self ._send_json (200 ,payload )

    def _route_cp_upload (self ):
        content_type =self .headers .get ("Content-Type","")
        m =re .search (r'boundary=([^;]+)',content_type )
        if not m or "multipart/form-data"not in content_type :
            self ._error_json (400 ,"Expected multipart/form-data upload")
            return
        length =int (self .headers .get ("Content-Length",0 ))
        if length <=0 or length >CP_MAX_UPLOAD +65536 :
            self ._error_json (400 ,"Upload missing or too large")
            return
        fields =parse_multipart (self .rfile .read (length ),m .group (1 ).strip ('"'))
        filename ,filedata =fields .get ("file",(None ,None ))
        status ,payload =cp_save_upload (filename ,filedata )
        if status !=200 :
            self ._error_json (status ,payload ["error"])
            return
        self ._send_json (200 ,payload )

    def _route_app_file (self ):
        query =urllib .parse .parse_qs (urllib .parse .urlparse (self .path ).query )
        name =query .get ("name",[""])[0 ]
        full =app_path (name )
        if full is None :
            self ._error_json (404 ,"No such app file")
            return 
        try :
            size =os .path .getsize (full )
            fh =open (full ,"rb")
        except OSError as exc :
            self ._error_json (500 ,f"Could not read {name }: {exc }")
            return 
        with fh :
            self .send_response (200 )
            self .send_header ("Content-Type","application/vnd.android.package-archive")
            self .send_header ("Content-Length",str (size ))
            self .send_header ("Content-Disposition",f'attachment; filename="{name }"')
            self .send_header ("Cache-Control","private, no-cache")
            self .end_headers ()
            try :
                shutil .copyfileobj (fh ,self .wfile ,65536 )
            except (BrokenPipeError ,ConnectionResetError ):
                pass 
        log_event (f"Downloaded app: {name }","info")

    def _action_gh_check (self ,body ):
        ok ,msg =gh_start_check ()
        self ._send_json (200 if ok else 409 ,{"message":msg ,"level":"info"if ok else "warn"})

    def _action_gh_update (self ,body ):
        if not body .get ("confirm"):
            self ._error_json (400 ,"A GitHub update requires confirm:true in the request body")
            return 
        code ,msg ,level =gh_start_update (body .get ("name"),body .get ("allow_older")is True )
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

    def _action_fu_stop(self, body):
        if not body.get("confirm"):
            self._error_json(400, "Stopping Full Update requires confirm:true in the request body")
            return
        code, msg, level = full_update_stop()
        self._send_json(code, {"message": msg, "level": level})

    def _action_fu_dismiss(self, body):
        full_update_dismiss()
        self._send_json(200, {"message": "", "level": "info"})

    def _action_gh_channel(self, body):
        ok, msg, level = channel_set(body.get("channel"), body.get("confirm") is True)
        self._send_json(200 if ok else 400, {"message": msg, "level": level})

    def _action_build_pref(self, body):
        ok, msg, level = build_pref_set(body.get("choice"))
        self._send_json(200 if ok else 409, {"message": msg, "level": level})

    def _action_save_alternate (self ,body =None ):
        live_name =(body or {}).get ("name")or CONFIG_NAME 
        if live_name not in LIVE_CONFIGS and live_name not in NL_LEGACY_NAMES .values ():
            self ._error_json (400 ,f"Unknown config '{live_name }'")
            return 
        live_cfg =os .path .join (CONFIG_DIR ,live_name )
        if not os .path .isfile (live_cfg ):
            self ._error_json (404 ,f"No active config at {live_cfg }")
            return 
        stamp =datetime .now ().strftime ("%Y%m%d_%H%M%S")
        base ,ext =os .path .splitext (live_name )
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

    def _schedule_power (self ,what ,unit ,verb ,message ):
        busy =_diskimg_busy_reason ()
        if busy :
            self ._send_json (409 ,{"error":busy ,"message":f"Not now: {busy }","level":"warn"})
            return 
        log_event (f"System {what } requested from instmon UI","warn")
        try :
            subprocess .run ([
            "systemd-run","--quiet","--collect",f"--on-active={REBOOT_SHUTDOWN_DELAY_SEC }",
            f"--unit={unit }","systemctl",verb ,
            ],check =True ,timeout =10 )
        except (FileNotFoundError ,subprocess .TimeoutExpired ,subprocess .CalledProcessError )as exc :
            log_event (f"{what .capitalize ()} request failed: {exc }","err")
            self ._error_json (500 ,f"Could not schedule {what }: {exc }")
            return 
        self ._send_json (200 ,{
        "message":message ,
        "level":"warn",
        })

    def _action_reboot (self ,body ):
        self ._schedule_power ("reboot","instmon-reboot","reboot",
        f"Rebooting in ~{REBOOT_SHUTDOWN_DELAY_SEC }s. This page (and everything else on the node) will be unreachable until it comes back up.")

    def _action_shutdown (self ,body ):
        self ._schedule_power ("shutdown","instmon-shutdown","poweroff",
        f"Shutting down in ~{REBOOT_SHUTDOWN_DELAY_SEC }s. You'll need physical/console access (or a smart PDU) to power it back on.")

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

def _write_launcher() -> None:
    tmp = _LAUNCHER_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(_LAUNCHER_CODE)
    os.chmod(tmp, 0o755)
    os.replace(tmp, _LAUNCHER_PATH)
    print(f"  [+] Wrote launcher {_LAUNCHER_PATH}")

def _pyc_for(src: str) -> list:
    name = os.path.splitext(os.path.basename(src))[0]
    return _glob_pyc(os.path.dirname(src), name)

def _glob_pyc(dir_path: str, name: str = "*") -> list:
    import glob as _g
    return _g.glob(os.path.join(dir_path, "__pycache__", f"{name}.*.pyc"))

def _prune_pyc(dir_path: str) -> None:
    for pyc in _glob_pyc(dir_path):
        name = os.path.basename(pyc).split(".", 1)[0]
        if not os.path.exists(os.path.join(dir_path, name + ".py")):
            try:
                os.remove(pyc)
            except OSError:
                pass

def _remove_launcher_if_unused() -> None:
    if not os.path.exists(_LAUNCHER_PATH):
        return
    unit_dir = _SYSTEMD_UNIT_DIR
    try:
        names = os.listdir(unit_dir)
    except OSError:
        return
    for n in names:
        p = os.path.join(unit_dir, n)
        try:
            if os.path.isfile(p) and _LAUNCHER_PATH in open(p, errors="replace").read():
                return
        except OSError:
            continue
    try:
        os.remove(_LAUNCHER_PATH)
    except FileNotFoundError:
        return
    print(f"  [-] Removed {_LAUNCHER_PATH} (no other service uses it)")

def firewall_backend():
    import shutil
    import subprocess
    try:
        if shutil.which("firewall-cmd") and subprocess.run(
                ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=10).stdout.strip() == "running":
            return "firewalld"
        if shutil.which("ufw") and "Status: active" in subprocess.run(
                ["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout:
            return "ufw"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "none"

def open_firewall_port(port, proto="tcp"):
    import re
    import subprocess
    spec = "%d/%s" % (port, proto)
    backend = firewall_backend()
    if backend == "firewalld":
        zone = subprocess.run(["firewall-cmd", "--get-default-zone"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        check = ["firewall-cmd", "--zone=" + zone, "--query-port=" + spec]
        target = subprocess.run(["firewall-cmd", "--zone=" + zone, "--get-target"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        if target == "ACCEPT" or subprocess.run(check, capture_output=True, text=True,
                                                timeout=10).stdout.strip() == "yes":
            return "=", "%s is already open in firewalld zone %s" % (spec, zone)
        subprocess.run(["firewall-cmd", "--zone=" + zone, "--add-port=" + spec],
                       capture_output=True, text=True, timeout=10)
        subprocess.run(["firewall-cmd", "--permanent", "--zone=" + zone, "--add-port=" + spec],
                       capture_output=True, text=True, timeout=10)
        if subprocess.run(check, capture_output=True, text=True, timeout=10).stdout.strip() == "yes":
            return "+", "opened %s in firewalld zone %s (now and after a reboot)" % (spec, zone)
        return "!", "could not open %s in firewalld zone %s" % (spec, zone)
    if backend == "ufw":
        allow = r"^%d/%s\s+ALLOW" % (port, proto)
        status = subprocess.run(["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout
        if "Default: allow (incoming)" in status or re.search(allow, status, re.M):
            return "=", "%s is already open in ufw" % spec
        subprocess.run(["ufw", "allow", spec], capture_output=True, text=True, timeout=10)
        status = subprocess.run(["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout
        if re.search(allow, status, re.M):
            return "+", "opened %s in ufw" % spec
        return "!", "could not open %s in ufw" % spec
    return "=", "no active firewall (ufw or firewalld), so %s is not blocked" % spec

def close_firewall_port(port, proto="tcp"):
    import re
    import subprocess
    spec = "%d/%s" % (port, proto)
    backend = firewall_backend()
    if backend == "firewalld":
        zone = subprocess.run(["firewall-cmd", "--get-default-zone"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        check = ["firewall-cmd", "--zone=" + zone, "--query-port=" + spec]
        was_open = subprocess.run(check, capture_output=True, text=True, timeout=10).stdout.strip() == "yes"
        subprocess.run(["firewall-cmd", "--zone=" + zone, "--remove-port=" + spec],
                       capture_output=True, text=True, timeout=10)
        subprocess.run(["firewall-cmd", "--permanent", "--zone=" + zone, "--remove-port=" + spec],
                       capture_output=True, text=True, timeout=10)
        if subprocess.run(check, capture_output=True, text=True, timeout=10).stdout.strip() == "yes":
            return "!", "could not close %s in firewalld zone %s" % (spec, zone)
        if was_open:
            return "-", "closed %s in firewalld zone %s" % (spec, zone)
        return "=", "%s was not open in firewalld zone %s" % (spec, zone)
    if backend == "ufw":
        allow = r"^%d/%s\s+ALLOW" % (port, proto)
        status = subprocess.run(["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout
        if not re.search(allow, status, re.M):
            return "=", "%s was not open in ufw" % spec
        subprocess.run(["ufw", "--force", "delete", "allow", spec], capture_output=True, text=True, timeout=10)
        status = subprocess.run(["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout
        if re.search(allow, status, re.M):
            return "!", "could not close %s in ufw" % spec
        if "Default: allow (incoming)" in status:
            return "!", "closed %s in ufw, but ufw's default allows incoming traffic, so it stays reachable" % spec
        return "-", "closed %s in ufw" % spec
    return "=", "no active firewall (ufw or firewalld), so there is no %s rule to close" % spec


def install_service ()->None :
    if os .geteuid ()!=0 :
        print ("Error: Installation requires root privileges. Run with 'sudo'.")
        sys .exit (1 )

    current_script = os.path.realpath(__file__)

    print ("Installing instmon...")

    os.makedirs(INSTALL_DIR, exist_ok=True)
    dest = os.path.join(INSTALL_DIR, os.path.basename(current_script))
    if current_script != dest:
        tmp = dest + ".tmp"
        shutil.copy2(current_script, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        print(f"  [+] Copied {os.path.basename(current_script)} -> {dest}")
    os.chmod(dest, 0o755)

    was_plain = os.path.isfile(INSTALL_BIN_PATH) and not os.path.islink(INSTALL_BIN_PATH)
    tmp_link = INSTALL_BIN_PATH + ".tmp"
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(dest, tmp_link)
    os.replace(tmp_link, INSTALL_BIN_PATH)
    print(f"  [+] Symlinked {INSTALL_BIN_PATH} -> {dest}")
    if was_plain:
        for pyc in _pyc_for(INSTALL_BIN_PATH):
            try:
                os.remove(pyc)
            except OSError:
                pass
        print(f"  [-] Replaced the old plain copy at {INSTALL_BIN_PATH}")

    for name in os.listdir(INSTALL_DIR):
        old = os.path.join(INSTALL_DIR, name)
        if old != dest and name.endswith(".py") and os.path.isfile(old) and not os.path.islink(old):
            os.remove(old)
            print(f"  [-] Removed the previous version {old}")
    _prune_pyc(INSTALL_DIR)
    _write_launcher()

    with open (SYSTEMD_SERVICE_PATH ,"w")as f :
        f .write (SYSTEMD_SERVICE_CONTENT )
    print (f"  [+] Created service file at {SYSTEMD_SERVICE_PATH }")

    mark, msg = open_firewall_port(PORT)
    print(f"  [{mark}] {msg}")
    
    subprocess .run (["systemctl","daemon-reload"],check =True )
    subprocess .run (["systemctl","enable","instmon.service"],check =True )

    docs_install_fetch()

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

    target = None
    if os.path.lexists(INSTALL_BIN_PATH):
        if os.path.islink(INSTALL_BIN_PATH):
            target = os.path.realpath(INSTALL_BIN_PATH)
        os.remove(INSTALL_BIN_PATH)
        print(f"  [-] Removed {INSTALL_BIN_PATH}")
    for pyc in _pyc_for(INSTALL_BIN_PATH):
        try:
            os.remove(pyc)
        except FileNotFoundError:
            pass
    if target and os.path.dirname(target) == INSTALL_DIR and os.path.isfile(target):
        os.remove(target)
        print(f"  [-] Removed {target}")
        for pyc in _pyc_for(target):
            try:
                os.remove(pyc)
            except FileNotFoundError:
                pass
    for d in (os.path.join(INSTALL_DIR, "__pycache__"), INSTALL_DIR, os.path.dirname(INSTALL_DIR)):
        try:
            os.rmdir(d)
        except OSError:
            pass
    _remove_launcher_if_unused()

    mark, msg = close_firewall_port(PORT)
    print(f"  [{mark}] {msg}")

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
    _diskimg_lastjob_recover ()
    full_update_resume_at_startup ()
    docs_start_first_fetch()
    app_start_first_fetch()

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
    _sd_notify ("READY=1")
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
