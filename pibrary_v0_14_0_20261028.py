#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import base64
import configparser
import errno
import hashlib
import hmac
import http.client
import http.server
import io
import ipaddress
import json
import os
import struct
import zlib
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime

VERSION = "0.14.0"
DATE_STR = "2026-10-28"
APP_NAME = "Pibrary"

INSTALL_BIN_PATH = "/usr/local/bin/pibrary.py"
INSTALL_DIR = "/usr/local/lib/pibrary"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/pibrary.service"
SERVICE_NAME = "pibrary.service"
STAGED_DIR = os.environ.get("PIBRARY_STAGE_DIR", os.path.join(INSTALL_DIR, "staged"))
ROLLBACK_DIR = os.path.join(STAGED_DIR, "rollback")

CONFIG_DIR = os.environ.get("PIBRARY_CONFIG_DIR", "/etc/pibrary")
CONFIG_NAME = os.environ.get("PIBRARY_CONFIG_NAME", "pibrary.conf")
CONFIG_PATH = os.path.join(CONFIG_DIR, CONFIG_NAME)
CONFIG_SECTION = "pibrary"

_LAUNCHER_PATH = "/usr/local/bin/asl_dvs_launch.py"
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
_SYSTEMD_UNIT_DIR = "/etc/systemd/system"

MAX_JSON_BYTES = 64 * 1024

SYSTEMD_SERVICE_CONTENT = f"""[Unit]
Description=Pibrary Media Library Dashboard
After=network.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 {_LAUNCHER_PATH} {INSTALL_BIN_PATH}
Restart=always
RestartSec=3s
TimeoutStartSec=60
WatchdogSec=60s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

PORT = 9000
_BOOT_CFG_PORT = None
_START_TIME = time.time()


LOG_MAX_LINES = 500
_log = deque(maxlen=LOG_MAX_LINES)
_log_lock = threading.Lock()
_log_seq = 0
_LOG_CONTROL_CHARS_RE = re.compile(r'[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]')


def log_event(message, level="info"):
    global _log_seq
    message = _LOG_CONTROL_CHARS_RE.sub(" ", str(message))
    with _log_lock:
        _log_seq += 1
        _log.append({
            "id": _log_seq,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "msg": message,
        })


DEFAULT_CONFIG = {
    "port": 9000,
    "auth_enabled": False,
    "library_root": "/srv/pibrary/media",
    "extra_roots": [],
    "max_streams": 3,
    "allow_write": False,
    "tab_side": "left",
    "max_upload_mb": 2048,
    "allow_update": False,
    "usb_uuid": "",
    "sd_root": "/srv/pibrary/media",
    "allowed_hosts": [],
    "notify_url": "",
    "notify_level": "all",
    "heartbeat_url": "",
    "heartbeat_min": 5,
    "auto_import": False,
    "revert_port": 0,
    "revert_deadline": 0,
    "log_file": True,
}

_cfg = dict(DEFAULT_CONFIG)
_cfg_lock = threading.RLock()


def _parse_bool(value):
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    raise ValueError("must be true or false")


def _norm_port(value):
    port = int(str(value).strip())
    if not 1 <= port <= 65535:
        raise ValueError("must be 1-65535")
    return port


def _norm_streams(value):
    n = int(str(value).strip())
    if not 1 <= n <= 10:
        raise ValueError("must be 1-10")
    return n


def _norm_path(value):
    s = str(value).strip()
    if not s.startswith("/"):
        raise ValueError("must be an absolute path")
    if "\x00" in s or "\n" in s or "\r" in s or "," in s:
        raise ValueError("contains an invalid character")
    return os.path.normpath(s)


def _norm_roots(value):
    if isinstance(value, str):
        items = re.split(r"[,\n]", value)
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ValueError("must be a list of paths")
    out = []
    for item in items:
        if not str(item).strip():
            continue
        p = _norm_path(item)
        if p not in out:
            out.append(p)
    return out


def _norm_side(value):
    s = str(value).strip().lower()
    if s not in ("left", "right"):
        raise ValueError("must be left or right")
    return s


def _norm_upload_mb(value):
    n = int(str(value).strip())
    if not 1 <= n <= 102400:
        raise ValueError("must be 1-102400")
    return n


def _norm_usb_uuid(value):
    s = str(value).strip()
    if s and not re.match(r"^[A-Za-z0-9_-]{1,64}$", s):
        raise ValueError("invalid drive id")
    return s


_HOST_LABEL = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
_HOST_RE = re.compile(r"^(\*\.)?%s(\.%s)*$" % (_HOST_LABEL, _HOST_LABEL))


def _norm_hosts(value):
    if isinstance(value, str):
        items = re.split(r"[,\s]+", value)
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ValueError("must be a list of host names")
    out = []
    for item in items:
        h = str(item).strip().lower().rstrip(".")
        if not h:
            continue
        if h != "*" and (len(h) > 253 or not _HOST_RE.match(h)):
            raise ValueError(f"invalid host name: {h}")
        if h not in out:
            out.append(h)
    return out


def _norm_url(value):
    s = str(value).strip()
    if not s:
        return ""
    if len(s) > 400 or any(c.isspace() for c in s) or not re.match(r"^https?://[^/\s]+", s, re.I):
        raise ValueError("must be an http:// or https:// address (or empty)")
    return s


def _norm_notify_level(value):
    s = str(value).strip().lower()
    if s not in ("all", "warn", "err"):
        raise ValueError("must be all, warn or err")
    return s


def _norm_minutes(value):
    n = int(str(value).strip())
    if not 1 <= n <= 60:
        raise ValueError("must be 1-60 minutes")
    return n


def _norm_int0(value):
    n = int(str(value).strip() or "0")
    if not 0 <= n < 2 ** 40:
        raise ValueError("out of range")
    return n


_INTERNAL_CFG_KEYS = ("usb_uuid", "sd_root", "revert_port", "revert_deadline")
_FILE_ONLY_CFG_KEYS = ("allowed_hosts",)


_NORMALIZERS = {
    "port": _norm_port,
    "auth_enabled": _parse_bool,
    "library_root": _norm_path,
    "extra_roots": _norm_roots,
    "max_streams": _norm_streams,
    "allow_write": _parse_bool,
    "tab_side": _norm_side,
    "max_upload_mb": _norm_upload_mb,
    "allow_update": _parse_bool,
    "usb_uuid": _norm_usb_uuid,
    "sd_root": _norm_path,
    "allowed_hosts": _norm_hosts,
    "notify_url": _norm_url,
    "notify_level": _norm_notify_level,
    "heartbeat_url": _norm_url,
    "heartbeat_min": _norm_minutes,
    "auto_import": _parse_bool,
    "revert_port": _norm_int0,
    "revert_deadline": _norm_int0,
    "log_file": _parse_bool,
}


def _cfg_get(key):
    with _cfg_lock:
        return _cfg[key]


def load_config():
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(CONFIG_PATH)
    except (configparser.Error, OSError) as exc:
        log_event(f"Config read failed ({CONFIG_PATH}): {exc}", "warn")
        return
    if not parser.has_section(CONFIG_SECTION):
        return
    loaded = dict(DEFAULT_CONFIG)
    for key, norm in _NORMALIZERS.items():
        if parser.has_option(CONFIG_SECTION, key):
            try:
                loaded[key] = norm(parser.get(CONFIG_SECTION, key))
            except (ValueError, TypeError) as exc:
                log_event(f"Config: bad value for {key} ({exc}); using default", "warn")
    if loaded["allow_write"] and not loaded["auth_enabled"]:
        log_event("Config: allow_write ignored while auth_enabled is false", "warn")
        loaded["allow_write"] = False
    if loaded["allow_update"] and not loaded["auth_enabled"]:
        log_event("Config: allow_update ignored while auth_enabled is false", "warn")
        loaded["allow_update"] = False
    if loaded["auto_import"] and not loaded["auth_enabled"]:
        log_event("Config: auto_import ignored while auth_enabled is false", "warn")
        loaded["auto_import"] = False
    with _cfg_lock:
        _cfg.clear()
        _cfg.update(loaded)


def save_config(cfg):
    parser = configparser.ConfigParser(interpolation=None)
    parser[CONFIG_SECTION] = {
        "port": str(cfg["port"]),
        "auth_enabled": "true" if cfg["auth_enabled"] else "false",
        "library_root": cfg["library_root"],
        "extra_roots": ",".join(cfg["extra_roots"]),
        "max_streams": str(cfg["max_streams"]),
        "allow_write": "true" if cfg["allow_write"] else "false",
        "tab_side": cfg["tab_side"],
        "max_upload_mb": str(cfg["max_upload_mb"]),
        "allow_update": "true" if cfg["allow_update"] else "false",
        "usb_uuid": cfg["usb_uuid"],
        "sd_root": cfg["sd_root"],
        "allowed_hosts": ",".join(cfg["allowed_hosts"]),
        "notify_url": cfg["notify_url"],
        "notify_level": cfg["notify_level"],
        "heartbeat_url": cfg["heartbeat_url"],
        "heartbeat_min": str(cfg["heartbeat_min"]),
        "auto_import": "true" if cfg["auto_import"] else "false",
        "revert_port": str(cfg["revert_port"]),
        "revert_deadline": str(cfg["revert_deadline"]),
        "log_file": "true" if cfg["log_file"] else "false",
    }
    buf = io.StringIO()
    parser.write(buf)
    _atomic_write(CONFIG_PATH, buf.getvalue().encode("utf-8"), 0o644)
    _note_sd_write("config")
    try:
        _drive_config_copy(cfg)
    except Exception as exc:
        log_event(f"Config copy on the library drive failed: {exc}", "warn")


def config_update(body):
    if not isinstance(body, dict):
        return False, "Body must be a JSON object"
    with _cfg_lock:
        new = dict(_cfg)
        for key, raw in body.items():
            if key not in _NORMALIZERS:
                return False, f"Unknown setting: {key}"
            if key in _INTERNAL_CFG_KEYS:
                return False, f"{key} is managed by the Storage card"
            if key in _FILE_ONLY_CFG_KEYS:
                return False, f"{key} can only be changed in {CONFIG_PATH}"
            try:
                new[key] = _NORMALIZERS[key](raw)
            except (ValueError, TypeError) as exc:
                return False, f"{key}: {exc}"
        if new["library_root"] != _cfg["library_root"] and (_cfg["usb_uuid"] or _mig_running()):
            return False, "Library root is managed by the Storage card (switch to the SD card first)"
        if new["allow_write"] and not new["auth_enabled"]:
            return False, "allow_write requires login to be enabled"
        if new["allow_update"] and not new["auth_enabled"]:
            return False, "allow_update requires login to be enabled"
        if new["auto_import"] and not new["auth_enabled"]:
            return False, "auto_import requires login to be enabled"
        turned_on = new["auth_enabled"] and not _cfg["auth_enabled"]
        turned_off = _cfg["auth_enabled"] and not new["auth_enabled"]
        if turned_on and not _auth_backend_available():
            return False, "Cannot enable login: root password hash is not readable (run as root)"
        try:
            save_config(new)
        except OSError as exc:
            return False, f"Cannot write {CONFIG_PATH}: {exc}"
        changed = [k for k in new if new[k] != _cfg[k]]
        _cfg.update(new)
    if "library_root" in changed or "extra_roots" in changed:
        with _scan_lock:
            _scan_cache.clear()
        _ensure_media_dirs()
    if turned_off:
        with _sessions_lock:
            _sessions.clear()
    if changed:
        log_event("Config saved: " + ", ".join(changed), "ok")
    if turned_on:
        _keep_arm("auth", KEEP_SEC, "Require login was turned on",
                  {"auth_enabled": False, "allow_write": False, "allow_update": False, "auto_import": False})
    return True, {"changed": changed, "auth_turned_on": turned_on}


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
                lib.crypt.restype = ctypes.c_char_p
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


def _root_backend_available():
    try:
        __import__("pam")
        return True
    except ImportError:
        pass
    stored = _read_shadow_hash(_AUTH_ACCOUNT)
    return bool(stored) and stored[0] not in ("!", "*")


_SESSION_COOKIE_NAME = "pibrary_session"
_SESSION_TTL_SEC = 12 * 3600
_COOKIE_RENEW_SEC = 3600

_sessions = {}
_sessions_lock = threading.Lock()


def _issue_session():
    token = secrets.token_hex(32)
    now = time.time()
    with _sessions_lock:
        for t in [tk for tk, ent in _sessions.items() if ent[0] <= now]:
            _sessions.pop(t, None)
        _sessions[token] = [now + _SESSION_TTL_SEC, now]
    return token


def _check_session(token):
    if not token:
        return False
    with _sessions_lock:
        ent = _sessions.get(token)
        if ent is None or ent[0] <= time.time():
            _sessions.pop(token, None)
            return False
        ent[0] = time.time() + _SESSION_TTL_SEC
        return True


def _session_cookie_due(token):
    now = time.time()
    with _sessions_lock:
        ent = _sessions.get(token)
        if ent is None or now - ent[1] < _COOKIE_RENEW_SEC:
            return False
        ent[1] = now
        return True


def _session_valid(token):
    with _sessions_lock:
        return token in _sessions


def _revoke_session(token):
    with _sessions_lock:
        _sessions.pop(token, None)


def _session_cookie_header(token, max_age):
    return f"{_SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"


def _clear_session_cookie_header():
    return f"{_SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"


_auth_failures = {}
_auth_failures_lock = threading.Lock()
AUTH_MAX_FAILURES = 5
AUTH_LOCKOUT_BASE_SEC = 5
AUTH_LOCKOUT_MAX_SEC = 300


def _auth_lockout_remaining(client_ip):
    with _auth_failures_lock:
        rec = _auth_failures.get(client_ip)
        if not rec:
            return 0
        return max(0, rec["locked_until"] - time.time())


def _record_auth_failure(client_ip):
    with _auth_failures_lock:
        rec = _auth_failures.setdefault(client_ip, {"fails": 0, "locked_until": 0})
        rec["fails"] += 1
        if rec["fails"] >= AUTH_MAX_FAILURES:
            backoff = min(
                AUTH_LOCKOUT_BASE_SEC * (2 ** (rec["fails"] - AUTH_MAX_FAILURES)),
                AUTH_LOCKOUT_MAX_SEC,
            )
            rec["locked_until"] = time.time() + backoff
            log_event(
                f"Auth: {client_ip} locked out for {backoff}s after {rec['fails']} failed attempts",
                "warn",
            )


def _record_auth_success(client_ip):
    with _auth_failures_lock:
        _auth_failures.pop(client_ip, None)


def _host_allowed(host_header):
    host = str(host_header or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        end = host.find("]")
        if end < 0:
            return False
        name = host[1:end]
    elif host.count(":") == 1:
        name = host.split(":", 1)[0]
    else:
        name = host
    name = name.rstrip(".")
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    full = socket.gethostname().lower().rstrip(".")
    short = full.split(".", 1)[0]
    if name in ("localhost", full, short, short + ".local") or name.endswith(".localhost"):
        return True
    for h in _cfg_get("allowed_hosts"):
        if h == "*" or name == h or (h.startswith("*.") and name.endswith(h[1:])):
            return True
    return False


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


def _pibrary_responsive():
    try:
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        try:
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            resp.read()
            return resp.status == 200
        finally:
            conn.close()
    except Exception:
        return False


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
            if _pibrary_responsive():
                _sd_notify("WATCHDOG=1")
                warned = False
            elif not warned:
                warned = True
                log_event("HTTP health probe failed -- withholding the systemd watchdog ping", "err")
        except Exception:
            pass
        time.sleep(period)


def _schedule_restart():
    if not os.environ.get("NOTIFY_SOCKET") or os.geteuid() != 0:
        return False
    try:
        subprocess.Popen([
            "systemd-run", "--quiet", "--collect", "--on-active=2",
            "--unit=pibrary-selfrestart", "systemctl", "restart", SERVICE_NAME,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as exc:
        log_event(f"Restart scheduling failed: {exc}", "err")
        return False


def _read_text(path):
    try:
        with open(path, "r") as fh:
            return fh.read()
    except OSError:
        return None


def _meminfo():
    info = {}
    text = _read_text("/proc/meminfo")
    if not text:
        return info
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].rstrip(":") in (
                "MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
            try:
                info[parts[0].rstrip(":")] = int(parts[1]) * 1024
            except ValueError:
                pass
    return info


def _disk_usage(path):
    entry = {"path": path, "exists": os.path.isdir(path), "total": None, "free": None}
    try:
        st = os.statvfs(path)
        entry["total"] = st.f_blocks * st.f_frsize
        entry["free"] = st.f_bavail * st.f_frsize
    except OSError:
        pass
    return entry


def build_status():
    temp = None
    raw = _read_text("/sys/class/thermal/thermal_zone0/temp")
    if raw:
        try:
            temp = int(raw.strip()) / 1000.0
        except ValueError:
            pass
    sys_uptime = None
    raw = _read_text("/proc/uptime")
    if raw:
        try:
            sys_uptime = float(raw.split()[0])
        except (ValueError, IndexError):
            pass
    model = None
    try:
        with open("/proc/device-tree/model", "rb") as fh:
            model = fh.read().replace(b"\x00", b"").decode("utf-8", "replace").strip()
    except OSError:
        pass
    try:
        load = list(os.getloadavg())
    except OSError:
        load = None
    with _cfg_lock:
        roots = [_cfg["library_root"]] + list(_cfg["extra_roots"])
    return {
        "app": APP_NAME,
        "version": VERSION,
        "date": DATE_STR,
        "port": PORT,
        "hostname": socket.gethostname(),
        "model": model,
        "kernel": os.uname().release,
        "python": sys.version.split()[0],
        "process_uptime": time.time() - _START_TIME,
        "system_uptime": sys_uptime,
        "load": load,
        "cpu_temp_c": temp,
        "memory": _meminfo(),
        "disks": _status_disks(roots),
        "storage": _storage_brief(),
        "streams": _streams_brief(),
        "sd_writes": _sd_writes_snapshot(),
        "positions": _pos_brief(),
        "power": _power_snapshot(),
        "drive_health": _smart_snapshot(),
        "notify": {"set": bool(_cfg_get("notify_url")), "heartbeat": bool(_cfg_get("heartbeat_url")),
                   "last_error": _notify_state["last_error"], "sent": _notify_state["sent"],
                   "heartbeat_ok": _notify_state["hb_ok"]},
        "auth_enabled": _cfg_get("auth_enabled"),
    }


def config_snapshot():
    with _cfg_lock:
        cfg = dict(_cfg)
    return {
        "config": cfg,
        "config_path": CONFIG_PATH,
        "active_port": PORT,
        "restart_required": cfg["port"] != (_BOOT_CFG_PORT if _BOOT_CFG_PORT is not None else PORT),
        "restart_possible": bool(os.environ.get("NOTIFY_SOCKET")) and os.geteuid() == 0,
        "password_set": _password_set(),
    }


def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write(path, data, mode=None, new_mode=0o600, skip_same=False):
    import os
    import secrets
    import stat
    path = os.fspath(path)
    if isinstance(data, str):
        data = data.encode("utf-8")
    folder = os.path.dirname(path) or "."
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        st = None
    if st is not None and not stat.S_ISREG(st.st_mode):
        st = None
    if skip_same and st is not None:
        try:
            with open(path, "rb") as fh:
                if fh.read() == data:
                    return False
        except OSError:
            pass
    tmp = os.path.join(folder, ".%s.%s.tmp" % (os.path.basename(path), secrets.token_hex(6)))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        if st is not None and os.geteuid() == 0:
            os.fchown(fd, st.st_uid, st.st_gid)
        if mode is not None:
            os.fchmod(fd, mode)
        elif st is not None:
            os.fchmod(fd, stat.S_IMODE(st.st_mode))
        else:
            os.fchmod(fd, new_mode)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.close(fd)
    try:
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass
    return True


def _atomic_write(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    atomic_write(path, data, mode=mode)


PW_MIN_LEN = 8
PW_MAX_LEN = 256


def _pass_path():
    return os.path.join(CONFIG_DIR, "pibrary.auth")


def _hash_password(password):
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1,
                        maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt$16384$8$1$%s$%s" % (base64.b64encode(salt).decode("ascii"),
                                        base64.b64encode(dk).decode("ascii"))


def _verify_pw_hash(password, stored):
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.strip().split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        if n > 2 ** 20 or r > 32 or p > 16:
            return False
        salt = base64.b64decode(salt_b64)
        want = base64.b64decode(hash_b64)
        got = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                             maxmem=128 * 1024 * 1024, dklen=len(want))
    except (ValueError, TypeError, OverflowError, MemoryError):
        return False
    return hmac.compare_digest(got, want)


def _read_pass_hash():
    text = _read_text(_pass_path())
    text = text.strip() if text else ""
    return text or None


def _password_set():
    return _read_pass_hash() is not None


def _verify_login(password):
    if not password:
        return False
    stored = _read_pass_hash()
    if stored:
        return _verify_pw_hash(password, stored)
    return _verify_root_password(password)


def _auth_backend_available():
    return _password_set() or _root_backend_available()


def password_change(body):
    if not isinstance(body, dict):
        return False, "Body must be a JSON object"
    stored = _read_pass_hash()
    if stored and not _verify_pw_hash(str(body.get("current") or ""), stored):
        return False, "Current password is incorrect"
    if body.get("clear"):
        if not stored:
            return False, "No password is set"
        if _cfg_get("auth_enabled") and not _root_backend_available():
            return False, "Cannot clear: login would have no password to fall back on"
        try:
            os.unlink(_pass_path())
        except OSError as exc:
            return False, f"Cannot remove {_pass_path()}: {exc}"
        _fsync_dir(CONFIG_DIR)
        log_event("Pibrary password cleared", "warn")
        if _cfg_get("auth_enabled"):
            _keep_arm("password", KEEP_SEC, "The Pibrary password was cleared (login uses the root password)",
                      {"old": stored})
        return True, "cleared"
    new = body.get("new")
    if not isinstance(new, str) or not PW_MIN_LEN <= len(new) <= PW_MAX_LEN:
        return False, f"New password must be {PW_MIN_LEN}-{PW_MAX_LEN} characters"
    if new != body.get("confirm"):
        return False, "New password and confirmation do not match"
    try:
        _atomic_write(_pass_path(), (_hash_password(new) + "\n").encode("ascii"), 0o600)
        _note_sd_write("password")
    except (OSError, ValueError, MemoryError) as exc:
        return False, f"Cannot save password: {exc}"
    log_event("Pibrary password set", "ok")
    if _cfg_get("auth_enabled"):
        _keep_arm("password", KEEP_SEC, "The Pibrary password was changed", {"old": stored})
    return True, "set"


MEDIA_TYPES = {
    "movie": {"dir": "movies", "label": "Movies",
              "exts": (".mp4", ".m4v", ".webm", ".ogv", ".mkv", ".mov"),
              "warn": (".mkv", ".mov")},
    "audio": {"dir": "audio", "label": "Audio",
              "exts": (".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac", ".weba")},
    "pdf": {"dir": "pdf", "label": "PDF", "exts": (".pdf",)},
}

_MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg",
    ".mkv": "video/x-matroska", ".mov": "video/quicktime",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav", ".flac": "audio/flac",
    ".weba": "audio/webm", ".pdf": "application/pdf",
}

LIST_CAP = 5000
SCAN_TTL_SEC = 30
RESERVE_BYTES = 100 * 1024 * 1024

_scan_cache = {}
_scan_lock = threading.Lock()
_streams_active = 0
_streams_lock = threading.Lock()
_upload_lock = threading.Lock()


def _media_roots():
    with _cfg_lock:
        return [_cfg["library_root"]] + list(_cfg["extra_roots"])


def _sweep_parts(base):
    removed = 0
    for dirpath, _dirnames, filenames in os.walk(base, followlinks=False):
        for fn in filenames:
            if fn.startswith(".upload-") and fn.endswith(".part"):
                try:
                    os.unlink(os.path.join(dirpath, fn))
                    removed += 1
                except OSError:
                    pass
    if removed:
        log_event(f"Removed {removed} leftover partial file(s) under {base}", "info")


def _ensure_media_dirs(sweep=False):
    if not _library_online():
        return
    root = _cfg_get("library_root")
    for spec in MEDIA_TYPES.values():
        d = os.path.join(root, spec["dir"])
        try:
            os.makedirs(d, exist_ok=True)
        except OSError as exc:
            log_event(f"Media dir {d}: {exc}", "warn")
            continue
        if sweep:
            _sweep_parts(d)


def _make_id(idx, rel):
    raw = f"{idx}:{rel}".encode("utf-8", "surrogateescape")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _resolve_id(kind, token):
    spec = MEDIA_TYPES.get(kind)
    if not spec or not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8", "surrogateescape")
        idx_s, rel = raw.split(":", 1)
        idx = int(idx_s)
    except (ValueError, TypeError):
        return None
    roots = _media_roots()
    if not 0 <= idx < len(roots) or not rel or rel.startswith("/") or "\x00" in rel:
        return None
    if ".." in rel.split("/"):
        return None
    base = os.path.realpath(os.path.join(roots[idx], spec["dir"]))
    full = os.path.realpath(os.path.join(base, rel))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        return None
    if os.path.splitext(full)[1].lower() not in spec["exts"]:
        return None
    return full


ART_EXTS = (".jpg", ".jpeg", ".png", ".webp")
ART_NAMES = ("cover", "folder", "front", "album", "poster")
ART_MAX_BYTES = 10 * 1024 * 1024
_ART_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _resolve_art(kind, token):
    spec = MEDIA_TYPES.get(kind)
    if not spec or not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8", "surrogateescape")
        idx_s, rel = raw.split(":", 1)
        idx = int(idx_s)
    except (ValueError, TypeError):
        return None
    roots = _media_roots()
    if not 0 <= idx < len(roots) or not rel or rel.startswith("/") or "\x00" in rel or ".." in rel.split("/"):
        return None
    base = os.path.realpath(os.path.join(roots[idx], spec["dir"]))
    full = os.path.realpath(os.path.join(base, rel))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        return None
    if os.path.splitext(full)[1].lower() not in ART_EXTS:
        return None
    try:
        if os.path.getsize(full) > ART_MAX_BYTES:
            return None
    except OSError:
        return None
    return full


def _scan_type(kind):
    spec = MEDIA_TYPES[kind]
    items = []
    dirs = []
    dir_art = {}
    truncated = False
    for idx, root in enumerate(_media_roots()):
        if idx == 0 and not _library_online():
            continue
        base = os.path.join(root, spec["dir"])
        if not os.path.isdir(base):
            continue
        art_of_dir = {}
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            if idx == 0 and len(dirs) < LIST_CAP:
                for d in dirnames:
                    dirs.append(os.path.relpath(os.path.join(dirpath, d), base))
            stems, named = {}, None
            for fn in filenames:
                stem, ext = os.path.splitext(fn)
                if ext.lower() in ART_EXTS and not fn.startswith("."):
                    stems.setdefault(stem.lower(), fn)
            for nm in ART_NAMES:
                if nm in stems:
                    named = stems[nm]
                    break
            if named:
                img_rel = os.path.relpath(os.path.join(dirpath, named), base)
                art_of_dir[dirpath] = img_rel
                drel = os.path.relpath(dirpath, base)
                if drel != ".":
                    dir_art.setdefault(drel, _make_id(idx, img_rel))
            parent_art = art_of_dir.get(os.path.dirname(dirpath)) if dirpath != base else None
            for fn in filenames:
                if fn.startswith("."):
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext not in spec["exts"]:
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                rel = os.path.relpath(full, base)
                same = stems.get(os.path.splitext(fn)[0].lower())
                art_rel = (os.path.relpath(os.path.join(dirpath, same), base) if same
                           else art_of_dir.get(dirpath) or parent_art)
                items.append({
                    "id": _make_id(idx, rel), "name": fn, "rel": rel, "root": idx,
                    "size": st.st_size, "mtime": int(st.st_mtime), "added": int(max(st.st_ctime, 0)),
                    "warn": ext in spec.get("warn", ()),
                    "art": _make_id(idx, art_rel) if art_rel else None,
                })
                if len(items) >= LIST_CAP:
                    truncated = True
                    break
            if truncated:
                break
        if truncated:
            break
    items.sort(key=lambda i: i["rel"].lower())
    dirs.sort(key=str.lower)
    return items, truncated, dirs, dir_art


def lib_list(kind, refresh=False):
    now = time.time()
    with _scan_lock:
        ent = _scan_cache.get(kind)
        if ent and not refresh and now - ent[0] < SCAN_TTL_SEC:
            return ent
    items, truncated, dirs, dir_art = _scan_type(kind)
    ent = (now, items, truncated, dirs, dir_art)
    with _scan_lock:
        _scan_cache[kind] = ent
    return ent


def _invalidate_scan(kind):
    with _scan_lock:
        _scan_cache.pop(kind, None)


FILEOP_MAX_ITEMS = 500
TRASH_DAYS = 30
_fileop_lock = threading.Lock()


def _fileop_gate(kind):
    spec = MEDIA_TYPES.get(kind)
    if not spec:
        return 400, "Unknown media type", None
    if not _cfg_get("allow_write"):
        return 403, "File changes are disabled (enable Allow uploads in Config)", None
    if not _library_online():
        return 503, _offline_reason(), None
    if _migrating():
        return 503, "A library copy is in progress; try again when it finishes", None
    return 200, None, os.path.join(_cfg_get("library_root"), spec["dir"])


def _name_error(name):
    name = str(name or "")
    if (not name or name in (".", "..") or name.startswith(".") or "/" in name or "\\" in name
            or len(name.encode("utf-8", "surrogateescape")) > 200
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        return "Invalid name (no / \\ or control characters, not starting with a dot, max 200 bytes)"
    fstype = _mount_fstype(USB_MOUNT) if _cfg_get("usb_uuid") else None
    if fstype in _NON_POSIX_FS and _BAD_NAME_RE.search(name):
        return f"Name not allowed on the {fstype} library drive (no < > : \" \\ | ? * and no trailing space or dot)"
    return None


def _lib_path(base, rel, allow_base=False):
    rel = str(rel or "")
    if rel == "":
        return os.path.realpath(base) if allow_base else None
    if rel.startswith("/") or "\x00" in rel or "\\" in rel or len(rel) > 2048:
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        return None
    real_base = os.path.realpath(base)
    full = os.path.join(real_base, *parts)
    if os.path.realpath(full) != full or not full.startswith(real_base + os.sep):
        return None
    return full


def _rel_of(base, full):
    return os.path.relpath(full, os.path.realpath(base)).replace(os.sep, "/")


def lib_mkdir(kind, parent, name):
    status, err, base = _fileop_gate(kind)
    if status != 200:
        return status, {"error": err}
    err = _name_error(name)
    if err:
        return 400, {"error": err}
    pdir = _lib_path(base, parent, allow_base=True)
    if pdir is None or not os.path.isdir(pdir):
        return 404, {"error": "That folder does not exist on the library drive"}
    full = os.path.join(pdir, name)
    with _fileop_lock:
        try:
            os.mkdir(full, 0o755)
        except FileExistsError:
            return 409, {"error": f"'{name}' already exists"}
        except OSError as exc:
            return 500, {"error": f"Cannot create the folder: {exc}"}
        _fsync_dir(pdir)
    _invalidate_scan(kind)
    rel = _rel_of(base, full)
    log_event(f"Created folder {kind}/{rel}", "ok")
    return 200, {"ok": True, "rel": rel}


def lib_rename(kind, rel, name):
    status, err, base = _fileop_gate(kind)
    if status != 200:
        return status, {"error": err}
    err = _name_error(name)
    if err:
        return 400, {"error": err}
    full = _lib_path(base, rel)
    if full is None or not os.path.lexists(full) or os.path.islink(full):
        return 404, {"error": "Not found on the library drive"}
    is_dir = os.path.isdir(full)
    if not is_dir:
        old_ext = os.path.splitext(full)[1].lower()
        if os.path.splitext(name)[1].lower() != old_ext:
            return 400, {"error": f"The extension must stay {old_ext} (renaming does not convert files)"}
    target = os.path.join(os.path.dirname(full), name)
    if target == full:
        return 200, {"ok": True, "moved": []}
    with _fileop_lock:
        if os.path.lexists(target) and os.path.normcase(target) != os.path.normcase(full):
            return 409, {"error": f"'{name}' already exists in this folder"}
        try:
            os.rename(full, target)
        except OSError as exc:
            return 500, {"error": f"Rename failed: {exc}"}
        _fsync_dir(os.path.dirname(full))
    _invalidate_scan(kind)
    old_rel, new_rel = _rel_of(base, full), _rel_of(base, target)
    log_event(f"Renamed {kind}/{old_rel} -> {new_rel}", "ok")
    return 200, {"ok": True, "moved": [[old_rel, new_rel, is_dir]]}


def lib_move(kind, items, dest):
    status, err, base = _fileop_gate(kind)
    if status != 200:
        return status, {"error": err}
    if not isinstance(items, list) or not items:
        return 400, {"error": "Nothing selected"}
    if len(items) > FILEOP_MAX_ITEMS:
        return 400, {"error": f"Select at most {FILEOP_MAX_ITEMS} items at a time"}
    ddir = _lib_path(base, dest, allow_base=True)
    if ddir is None or not os.path.isdir(ddir):
        return 404, {"error": "The destination folder does not exist"}
    moved, problems = [], []
    with _fileop_lock:
        for rel in items:
            full = _lib_path(base, rel)
            if full is None or not os.path.lexists(full) or os.path.islink(full):
                problems.append(f"{rel}: not found")
                continue
            is_dir = os.path.isdir(full)
            if is_dir and (ddir == full or ddir.startswith(full + os.sep)):
                problems.append(f"{rel}: cannot move a folder into itself")
                continue
            target = os.path.join(ddir, os.path.basename(full))
            if target == full:
                continue
            if os.path.lexists(target):
                problems.append(f"{rel}: '{os.path.basename(full)}' already exists there")
                continue
            try:
                os.rename(full, target)
            except OSError as exc:
                problems.append(f"{rel}: {exc}")
                continue
            moved.append([_rel_of(base, full), _rel_of(base, target), is_dir])
            _fsync_dir(os.path.dirname(full))
        _fsync_dir(ddir)
    _invalidate_scan(kind)
    if moved:
        log_event(f"Moved {len(moved)} item(s) in {kind} to /{_rel_of(base, ddir) if ddir != os.path.realpath(base) else ''}", "ok")
    return 200, {"ok": True, "moved": moved, "problems": problems[:20]}


def _trash_root():
    return os.path.join(_cfg_get("library_root"), ".pibrary", "trash")


def _trash_entries():
    root = _trash_root()
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for tid in names:
        d = os.path.join(root, tid)
        try:
            with open(os.path.join(d, "meta.json"), "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get("kind") not in MEDIA_TYPES:
            continue
        if not meta.get("name") or "/" in str(meta["name"]) or str(meta["name"]) in (".", ".."):
            continue
        item = os.path.join(d, str(meta.get("name") or ""))
        size = 0
        try:
            if os.path.isdir(item):
                for dp, _dn, fns in os.walk(item):
                    for fn in fns:
                        try:
                            size += os.lstat(os.path.join(dp, fn)).st_size
                        except OSError:
                            pass
            else:
                size = os.lstat(item).st_size
        except OSError:
            continue
        out.append({"id": tid, "kind": meta["kind"], "rel": str(meta.get("rel") or ""),
                    "name": str(meta.get("name") or ""), "dir": bool(meta.get("dir")),
                    "ts": int(meta.get("ts") or 0), "size": size, "_path": d, "_item": item})
    out.sort(key=lambda e: e["ts"], reverse=True)
    return out


def lib_trash(kind, items):
    status, err, base = _fileop_gate(kind)
    if status != 200:
        return status, {"error": err}
    if not isinstance(items, list) or not items:
        return 400, {"error": "Nothing selected"}
    if len(items) > FILEOP_MAX_ITEMS:
        return 400, {"error": f"Select at most {FILEOP_MAX_ITEMS} items at a time"}
    trashed, removed, problems = 0, 0, []
    with _fileop_lock:
        for rel in items:
            full = _lib_path(base, rel)
            if full is None or not os.path.lexists(full) or os.path.islink(full):
                problems.append(f"{rel}: not found")
                continue
            is_dir = os.path.isdir(full)
            try:
                if is_dir and not os.listdir(full):
                    os.rmdir(full)
                    removed += 1
                    continue
                tid = "%d-%s" % (int(time.time() * 1000), secrets.token_hex(4))
                tdir = os.path.join(_trash_root(), tid)
                os.makedirs(tdir, mode=0o755)
                meta = {"kind": kind, "rel": _rel_of(base, full), "name": os.path.basename(full),
                        "dir": is_dir, "ts": int(time.time())}
                _atomic_write(os.path.join(tdir, "meta.json"), json.dumps(meta).encode("utf-8"), 0o644)
                try:
                    os.rename(full, os.path.join(tdir, os.path.basename(full)))
                except OSError:
                    shutil.rmtree(tdir, ignore_errors=True)
                    raise
                trashed += 1
            except OSError as exc:
                problems.append(f"{rel}: {exc}")
            finally:
                _fsync_dir(os.path.dirname(full))
    _invalidate_scan(kind)
    if trashed or removed:
        log_event(f"Trash: {trashed} item(s) from {kind} moved to the trash"
                  + (f", {removed} empty folder(s) removed" if removed else ""), "ok")
    return 200, {"ok": True, "trashed": trashed, "removed": removed, "problems": problems[:20]}


def trash_list(kind):
    status, err, _base = _fileop_gate(kind)
    if status != 200:
        return status, {"error": err, "items": []}
    items = [{k: v for k, v in e.items() if not k.startswith("_")} for e in _trash_entries() if e["kind"] == kind]
    return 200, {"ok": True, "items": items, "days": TRASH_DAYS}


def trash_restore(kind, ids):
    status, err, base = _fileop_gate(kind)
    if status != 200:
        return status, {"error": err}
    if not isinstance(ids, list) or not ids:
        return 400, {"error": "Nothing selected"}
    by_id = {e["id"]: e for e in _trash_entries() if e["kind"] == kind}
    restored, problems = [], []
    with _fileop_lock:
        for tid in ids:
            e = by_id.get(str(tid))
            if e is None:
                problems.append("an item is no longer in the trash")
                continue
            dest = _lib_path(base, e["rel"])
            if dest is None:
                problems.append(f"{e['rel']}: invalid original path")
                continue
            if os.path.lexists(dest):
                problems.append(f"{e['rel']}: something with that name exists again; rename or move it first")
                continue
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.rename(e["_item"], dest)
                _fsync_dir(os.path.dirname(dest))
                shutil.rmtree(e["_path"], ignore_errors=True)
                restored.append(e["rel"])
            except OSError as exc:
                problems.append(f"{e['rel']}: {exc}")
    _invalidate_scan(kind)
    if restored:
        log_event(f"Trash: restored {len(restored)} item(s) to {kind}", "ok")
    return 200, {"ok": True, "restored": restored, "problems": problems[:20]}


def trash_empty(kind, ids=None):
    status, err, _base = _fileop_gate(kind)
    if status != 200:
        return status, {"error": err}
    want = None if ids is None else {str(i) for i in ids}
    n = 0
    with _fileop_lock:
        for e in _trash_entries():
            if e["kind"] == kind and (want is None or e["id"] in want):
                shutil.rmtree(e["_path"], ignore_errors=True)
                n += 1
    if n:
        log_event(f"Trash: permanently deleted {n} item(s) from {kind}", "warn")
    return 200, {"ok": True, "deleted": n}


def _trash_sweep():
    if not _library_online() or _migrating():
        return
    cutoff = time.time() - TRASH_DAYS * 86400
    n = 0
    with _fileop_lock:
        for e in _trash_entries():
            if e["ts"] and e["ts"] < cutoff:
                shutil.rmtree(e["_path"], ignore_errors=True)
                n += 1
    if n:
        log_event(f"Trash: emptied {n} item(s) older than {TRASH_DAYS} days", "info")


DUPES_QUICK = 1024 * 1024
_dupes = {}


def _quick_hash(path, size):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        if size <= 2 * DUPES_QUICK:
            h.update(fh.read())
        else:
            h.update(fh.read(DUPES_QUICK))
            fh.seek(size - DUPES_QUICK)
            h.update(fh.read(DUPES_QUICK))
    return h.hexdigest()


def dupes_start(kind):
    if kind not in MEDIA_TYPES:
        return 400, {"error": "Unknown media type"}, False
    if _mig_running():
        return 409, {"error": "A storage job is running"}, False
    _ts, items, _trunc, _dirs, _art = lib_list(kind, refresh=True)
    by_size = {}
    for it in items:
        if it["size"] > 0:
            by_size.setdefault(it["size"], []).append(it)
    cands = [g for g in by_size.values() if len(g) > 1]
    nfiles = sum(len(g) for g in cands)
    if not nfiles:
        _dupes[kind] = {"ts": int(time.time()), "groups": [], "scanned": len(items)}
        return 200, {"ok": True, "started": False, "groups": 0}, False
    _mig_set(running=True, kind="dupes", phase="checking", done=False, error="", message="", failed=[],
             cancel=False, files_total=nfiles, files_done=0,
             bytes_total=sum(min(i["size"], 2 * DUPES_QUICK) for g in cands for i in g), bytes_done=0,
             skipped=0, current="", no_cancel=False, result="")
    try:
        threading.Thread(target=_run_dupes_job, args=(kind, cands, len(items)), daemon=True).start()
    except Exception as exc:
        _mig_set(running=False, done=True, phase="done", error=f"Could not start the job: {exc}")
        raise
    return 200, {"ok": True, "started": True, "files": nfiles}, True


def _run_dupes_job(kind, cands, scanned):
    try:
        groups, done = [], 0
        for g in cands:
            if _mig_cancelled():
                raise InterruptedError("cancelled")
            quick = {}
            for it in g:
                p = _resolve_id(kind, it["id"])
                done += 1
                _mig_set(files_done=done, current=it["name"])
                if not p:
                    continue
                try:
                    qh = _quick_hash(p, it["size"])
                except OSError as exc:
                    if exc.errno in _FAULT_ERRNOS:
                        raise
                    continue
                _mig_inc("bytes_done", min(it["size"], 2 * DUPES_QUICK))
                quick.setdefault(qh, []).append((it, p))
            for sub in quick.values():
                if len(sub) < 2:
                    continue
                full = {}
                for it, p in sub:
                    if it["size"] <= 2 * DUPES_QUICK:
                        key = "q"
                    else:
                        _mig_set(phase="verifying", current=it["name"])
                        try:
                            key = _sha256_file(p, _mig_cancelled)
                        except OSError:
                            continue
                    full.setdefault(key, []).append(it)
                for same in full.values():
                    if len(same) > 1:
                        same.sort(key=lambda i: (i["mtime"], i["rel"].lower()))
                        groups.append([{"id": i["id"], "rel": i["rel"], "name": i["name"], "size": i["size"],
                                        "mtime": i["mtime"], "root": i.get("root", 0)} for i in same])
                _mig_set(phase="checking")
        wasted = sum(grp[0]["size"] * (len(grp) - 1) for grp in groups)
        _dupes[kind] = {"ts": int(time.time()), "groups": groups, "scanned": scanned}
        msg = (f"Found {len(groups)} group(s) of identical files; {_fmt_bytes(wasted)} could be freed"
               if groups else f"No duplicates among {scanned} file(s)")
        _mig_set(message=msg + ".")
        log_event(f"Duplicates in {kind}: {msg}", "ok")
    except InterruptedError:
        _mig_set(error="Cancelled.")
    except OSError as exc:
        _mig_set(error=f"A drive stopped responding ({exc}); the search was stopped.")
        log_event(f"Duplicate search stopped: {exc}", "err")
    except Exception as exc:
        _mig_set(error=f"Job failed: {exc}")
        log_event(f"Duplicate search failed: {exc}", "err")
    finally:
        _mig_set(running=False, done=True, phase="done")
        _storage_op_lock.release()


def _trash_sweep_loop():
    time.sleep(120)
    while True:
        try:
            _trash_sweep()
        except Exception as exc:
            log_event(f"Trash sweep error: {exc}", "err")
        time.sleep(3600)


STREAM_STALL_SEC = int(os.environ.get("PIBRARY_STREAM_STALL_SEC", "300"))
STREAM_SEND_TIMEOUT_SEC = 5
_stream_table = {}
_stream_seq = 0


def _stream_acquire(kind="", item_id="", name=""):
    global _streams_active, _stream_seq
    with _streams_lock:
        if _streams_active >= _cfg_get("max_streams"):
            return None
        _stream_seq += 1
        _stream_table[_stream_seq] = {"kind": kind, "id": item_id, "name": name,
                                      "since": time.time(), "stalled_since": None}
        _streams_active += 1
        return _stream_seq


def _stream_release(token):
    global _streams_active
    with _streams_lock:
        if _stream_table.pop(token, None) is not None:
            _streams_active = max(0, _streams_active - 1)


def _stream_stall(token, stalled):
    now = time.time()
    with _streams_lock:
        e = _stream_table.get(token)
        if e is None:
            return 0.0
        if not stalled:
            e["stalled_since"] = None
            return 0.0
        if e["stalled_since"] is None:
            e["stalled_since"] = now
        return now - e["stalled_since"]


def _send_stream(sock, data, token):
    view = memoryview(data)
    sent = 0
    while sent < len(view):
        try:
            n = sock.send(view[sent:])
        except socket.timeout:
            if _stream_stall(token, True) >= STREAM_STALL_SEC:
                log_event("Closed an idle stream (the player stopped reading for %ds)" % STREAM_STALL_SEC, "warn")
                return False
            continue
        except OSError:
            return False
        if n <= 0:
            return False
        sent += n
        _stream_stall(token, False)
    return True


def _streams_snapshot():
    now = time.time()
    out = []
    with _streams_lock:
        for e in _stream_table.values():
            st = e["stalled_since"]
            idle = int(now - st) if st is not None else 0
            out.append({"kind": e["kind"], "id": e["id"], "name": e["name"],
                        "active_secs": int(now - e["since"]), "stalled": st is not None,
                        "idle_secs": idle,
                        "remaining": max(0, STREAM_STALL_SEC - idle) if st is not None else None})
    return out


def _streams_brief():
    snap = _streams_snapshot()
    rem = [s["remaining"] for s in snap if s["stalled"]]
    return {"active": len(snap), "max": _cfg_get("max_streams"),
            "idle": len(rem), "next_close": min(rem) if rem else None}


def _parse_range(header, size):
    m = re.match(r"^bytes=(\d*)-(\d*)$", header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    if m.group(1) == "":
        n = int(m.group(2))
        if n == 0 or size == 0:
            return False
        return max(0, size - n), size - 1
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) != "" else size - 1
    end = min(end, size - 1)
    if start >= size or start > end:
        return False
    return start, end


def _validate_upload(kind, name, size, subdir=""):
    spec = MEDIA_TYPES.get(kind)
    if not spec:
        return 400, "Unknown media type", None
    if not _cfg_get("allow_write"):
        return 403, "Uploads are disabled (enable Allow uploads in Config)", None
    if not _library_online():
        return 503, _offline_reason(), None
    if _migrating():
        return 503, "A library copy is in progress; uploads are paused", None
    name = str(name or "")
    if (not name or len(name.encode("utf-8", "surrogateescape")) > 200 or name.startswith(".") or "/" in name or "\\" in name
            or name != os.path.basename(name) or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        return 400, "Invalid file name", None
    ext = os.path.splitext(name)[1].lower()
    if ext not in spec["exts"]:
        return 400, f"'{ext or name}' not allowed for {spec['label']} (allowed: {' '.join(spec['exts'])})", None
    fstype = _mount_fstype(USB_MOUNT) if _cfg_get("usb_uuid") else None
    if fstype in _NON_POSIX_FS and _BAD_NAME_RE.search(name):
        return 400, (f"Name not allowed on the {fstype} library drive "
                     "(no < > : \" \\ | ? * and no trailing space or dot)"), None
    if size <= 0:
        return 400, "Empty or missing file size", None
    limit_mb = _effective_max_upload_mb()
    if size > limit_mb * 1024 * 1024:
        return 413, f"File exceeds the {limit_mb} MB upload limit", None
    target = os.path.join(_cfg_get("library_root"), spec["dir"])
    if subdir:
        sub = _lib_path(target, subdir)
        if sub is None or not os.path.isdir(sub):
            return 400, "That folder does not exist on the library drive", None
        target = sub
    try:
        os.makedirs(target, exist_ok=True)
        st = os.statvfs(target)
    except OSError as exc:
        return 500, f"Library directory unavailable: {exc}", None
    if size + RESERVE_BYTES > st.f_bavail * st.f_frsize:
        return 507, (f"The library drive is full ({_fmt_bytes(st.f_bavail * st.f_frsize)} free, "
                     f"needs {_fmt_bytes(size + RESERVE_BYTES)} incl. a safety margin)"), None
    return 200, None, (target, os.path.join(target, name))


def _commit_upload(tmp, final, force):
    if force:
        os.replace(tmp, final)
    else:
        try:
            os.link(tmp, final)
        except FileExistsError:
            raise
        except OSError:
            if os.path.lexists(final):
                raise FileExistsError(final)
            os.replace(tmp, final)
        else:
            os.unlink(tmp)
    _fsync_dir(os.path.dirname(final))


SELF_MAX_BYTES = 5 * 1024 * 1024
SELF_KEEP = 3
SELF_INSTALL_TIMEOUT_SEC = 120
SELF_GUARD_SEC = 120
_SELF_NAME_RE = re.compile(r"^pibrary.*\.py$", re.I)
_VERSION_RE = re.compile(r'^VERSION = "([0-9]+(?:\.[0-9]+)*)"', re.M)
_self_lock = threading.Lock()


def _ver_tuple(version):
    try:
        return tuple(int(p) for p in str(version).split("."))
    except ValueError:
        return None


def _cmp_version(version):
    got, run = _ver_tuple(version), _ver_tuple(VERSION)
    if got is None or run is None:
        return "unknown"
    return "newer" if got > run else ("same" if got == run else "older")


def _validate_self_name(name):
    name = str(name or "")
    if (not name or name.startswith(".") or "/" in name or "\\" in name
            or name != os.path.basename(name)
            or len(name.encode("utf-8", "surrogateescape")) > 200
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        return "Invalid file name"
    if not name.lower().endswith(".py"):
        return "Only .py files are accepted"
    return None


def _self_validate_file(path):
    try:
        size = os.path.getsize(path)
        if size <= 0 or size > SELF_MAX_BYTES:
            return "File size out of range", None
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"Cannot read file: {exc}", None
    try:
        compile(text, path, "exec")
    except SyntaxError as exc:
        return f"Python syntax error: {exc.msg} (line {exc.lineno})", None
    except (ValueError, RecursionError, MemoryError) as exc:
        return f"Cannot check syntax: {exc}", None
    m = _VERSION_RE.search(text)
    if not (m and 'APP_NAME = "Pibrary"' in text and "def install_service" in text
            and '"--install"' in text):
        return "Not a Pibrary file (missing VERSION, APP_NAME, install_service or --install)", None
    return None, m.group(1)


def self_list():
    out = []
    try:
        names = os.listdir(_staged_dir())
    except OSError:
        return out
    for fn in names:
        if fn.startswith(".") or not fn.lower().endswith(".py"):
            continue
        full = os.path.join(_staged_dir(), fn)
        try:
            st = os.lstat(full)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        ver, sha = None, ""
        try:
            with open(full, "rb") as fh:
                raw = fh.read(SELF_MAX_BYTES + 1)
            sha = hashlib.sha256(raw).hexdigest()
            m = _VERSION_RE.search(raw.decode("utf-8", "replace"))
            ver = m.group(1) if m else None
        except OSError:
            pass
        out.append({"name": fn, "version": ver, "size": st.st_size, "mtime": int(st.st_mtime),
                    "sha": sha, "cmp": _cmp_version(ver)})
    out.sort(key=lambda e: e["mtime"], reverse=True)
    return out


def _prune_staged():
    for entry in self_list()[SELF_KEEP:]:
        try:
            os.unlink(os.path.join(_staged_dir(), entry["name"]))
        except OSError:
            pass


def _sweep_staged():
    try:
        for fn in os.listdir(_staged_dir()):
            if fn.startswith(".upload-") and fn.endswith(".part"):
                try:
                    os.unlink(os.path.join(_staged_dir(), fn))
                except OSError:
                    pass
    except OSError:
        pass


def _file_version(path):
    try:
        with open(path, "rb") as fh:
            m = _VERSION_RE.search(fh.read(SELF_MAX_BYTES + 1).decode("utf-8", "replace"))
        return m.group(1) if m else None
    except OSError:
        return None


def _arm_update_guard(rollback_path, target_version):
    port = _cfg_get("port")
    probe = ("import json,sys,urllib.request as u\n"
             "try:\n"
             " r=u.urlopen('http://127.0.0.1:%d/api/health',timeout=5)\n"
             " d=json.load(r)\n"
             " sys.exit(0 if r.status==200 and d.get('version')==%r else 1)\n"
             "except Exception:\n"
             " sys.exit(1)\n" % (port, str(target_version)))
    check = "%s -c %s || { %s %s --install; }" % (
        shlex.quote(sys.executable), shlex.quote(probe), shlex.quote(sys.executable),
        shlex.quote(rollback_path))
    for args in (["systemctl", "stop", "pibrary-update-guard.timer", "pibrary-update-guard.service"],
                 ["systemctl", "reset-failed", "pibrary-update-guard.service"]):
        try:
            subprocess.run(args, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        r = subprocess.run(["systemd-run", "--quiet", "--collect", "--on-active=%d" % SELF_GUARD_SEC,
                            "--unit=pibrary-update-guard", "bash", "-c", check],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return r.returncode == 0, (r.stderr or "").strip()[:200]


def _run_self_install(path, name, arm_guard=True):
    try:
        log_event(f"Installing {name} -- running its own --install...", "info")
        if arm_guard:
            target = _file_version(path)
            if not target:
                log_event("Update aborted: cannot read the staged file's version", "err")
                return
            current = os.path.realpath(__file__)
            os.makedirs(ROLLBACK_DIR, exist_ok=True)
            for fn in os.listdir(ROLLBACK_DIR):
                try:
                    os.unlink(os.path.join(ROLLBACK_DIR, fn))
                except OSError:
                    pass
            rollback = os.path.join(ROLLBACK_DIR, os.path.basename(current))
            tmp = rollback + ".tmp"
            shutil.copy2(current, tmp)
            os.chmod(tmp, 0o755)
            os.replace(tmp, rollback)
            _note_sd_write("rollback")
            ok, err = _arm_update_guard(rollback, target)
            if not ok:
                log_event(f"Update aborted: could not arm the rollback guard ({err or 'systemd-run failed'})", "err")
                return
            log_event(f"Rollback guard armed ({SELF_GUARD_SEC}s): reinstalls v{VERSION} unless /api/health "
                      f"reports v{target}", "info")
        proc = subprocess.Popen([sys.executable, path, "--install"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        killer = threading.Timer(SELF_INSTALL_TIMEOUT_SEC, proc.kill)
        killer.start()
        try:
            for line in proc.stdout:
                log_event(line.rstrip("\n"), "info")
            proc.wait(timeout=10)
        finally:
            killer.cancel()
        if proc.returncode == 0:
            _note_sd_write("install")
            log_event(f"Install finished OK: {name}. The service restarts in a few seconds.", "ok")
            notify(f"Update installed: {name}; Pibrary restarts now (rollback guard armed)", "info")
        else:
            log_event(f"Install exited {proc.returncode}: {name}", "err")
            notify(f"Update FAILED: {name} exited {proc.returncode}; still running v{VERSION}", "err")
    except Exception as exc:
        log_event(f"Install failed to run: {name}: {exc}", "err")
        notify(f"Update FAILED to run: {name}: {exc}", "err")
    finally:
        _self_lock.release()


USB_MOUNT = os.environ.get("PIBRARY_USB_MOUNT", "/mnt/pibrary-usb")
IMPORT_ROOT = os.environ.get("PIBRARY_IMPORT_ROOT", "/mnt/pibrary-import")
NEW_MOUNT = os.environ.get("PIBRARY_NEW_MOUNT", "/mnt/pibrary-new")
FMT_MOUNT = os.environ.get("PIBRARY_FMT_MOUNT", "/mnt/pibrary-fmt")
_TEST_ALLOW_LOOP = os.environ.get("PIBRARY_TEST_ALLOW_LOOP") == "1"
USB_SUBDIR = "pibrary"
STORAGE_POLL_SEC = 15
IMPORT_MAX_MOUNTS = 2
IMPORT_SCAN_CAP = 5000
IMPORT_WALK_CAP = 200000
IMPORT_SELECT_CAP = 500
FAT_MAX_FILE = 4 * 1024 ** 3 - 1
_USB_FS_OK = ("ext4", "ext3", "ext2", "vfat", "exfat", "ntfs")
_BAD_NAME_RE = re.compile(r'[<>:"\\|?*\x00-\x1f]|[ .]$')
_NON_POSIX_FS = ("vfat", "msdos", "exfat", "ntfs", "ntfs3", "fuseblk")
_IMPORT_SKIP = ("system volume information", "lost+found", "$recycle.bin")
_UUID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

class _LockedSet:
    def __init__(self):
        self._s = set()
        self._l = threading.Lock()

    def add(self, x):
        with self._l:
            self._s.add(x)

    def discard(self, x):
        with self._l:
            self._s.discard(x)

    def clear(self):
        with self._l:
            self._s.clear()

    def __contains__(self, x):
        with self._l:
            return x in self._s

    def snapshot(self):
        with self._l:
            return list(self._s)


class _LockedDict:
    def __init__(self):
        self._d = {}
        self._l = threading.Lock()

    def __setitem__(self, k, v):
        with self._l:
            self._d[k] = v

    def get(self, k, default=None):
        with self._l:
            return self._d.get(k, default)


_storage_op_lock = threading.Lock()
_storage_ejected = _LockedSet()
_storage_seen = {}
_storage_labels = _LockedDict()
_missing_counts = {}
_mig_lock = threading.Lock()
_imp_cache = {}
_imp_lock = threading.Lock()


def _is_mount(path):
    return os.path.ismount(path)


def _safe_name(uuid):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(uuid))


def _import_path(uuid):
    return os.path.join(IMPORT_ROOT, _safe_name(uuid))


def _library_online():
    if not _cfg_get("usb_uuid"):
        return True
    return _is_mount(USB_MOUNT)


def _library_state():
    uuid = _cfg_get("usb_uuid")
    if not uuid or _is_mount(USB_MOUNT):
        return "online"
    if _fault_get("lib"):
        return "error"
    return "ejected" if uuid in _storage_ejected else "offline"


def _storage_brief():
    out = {"mode": "usb" if _cfg_get("usb_uuid") else "sd", "state": _library_state(),
           "root": _cfg_get("library_root")}
    out.update(_lib_fault_info())
    return out


def _status_disks(roots):
    out = [_disk_usage("/")]
    for i, r in enumerate(roots):
        if i == 0 and not _library_online():
            out.append({"path": r, "exists": False, "total": None, "free": None, "offline": True})
        else:
            out.append(_disk_usage(r))
    return out


def _mount_info(mountpoint):
    text = _read_text("/proc/mounts") or ""
    for line in text.splitlines():
        p = line.split()
        if len(p) >= 4 and p[1] == mountpoint:
            return p[2], set(p[3].split(",")), p[0]
    return None


def _mount_fstype(mountpoint):
    info = _mount_info(mountpoint)
    return info[0] if info else None


def _effective_max_upload_mb():
    mb = _cfg_get("max_upload_mb")
    if _cfg_get("usb_uuid") and _mount_fstype(USB_MOUNT) in ("vfat", "msdos"):
        mb = min(mb, 4095)
    return mb


def _lsblk_json():
    try:
        r = subprocess.run(["lsblk", "-J", "-b", "-o",
                            "NAME,PATH,TYPE,TRAN,RM,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINT,MODEL,SERIAL"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def _detect_usb_drives(data=None):
    data = data if data is not None else _lsblk_json()
    out = []
    if not data:
        return out
    for disk in data.get("blockdevices") or []:
        if str(disk.get("tran") or "").lower() != "usb":
            continue
        nodes = [c for c in (disk.get("children") or []) if c.get("type") == "part"] or [disk]
        for n in nodes:
            fstype = str(n.get("fstype") or "").lower()
            fstype = {"ntfs3": "ntfs", "ntfs-3g": "ntfs", "msdos": "vfat"}.get(fstype, fstype)
            if not fstype or fstype in ("swap", "crypto_luks", "lvm2_member", "linux_raid_member"):
                continue
            try:
                size = int(n.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            out.append({
                "uuid": str(n.get("uuid") or ""), "label": str(n.get("label") or ""),
                "fstype": fstype, "size": size,
                "path": str(n.get("path") or ("/dev/" + str(n.get("name") or ""))),
                "mountpoint": str(n.get("mountpoint") or ""), "disk": str(disk.get("name") or ""),
            })
    return out


def _drive_note(d):
    if not d["uuid"] or not _UUID_RE.match(d["uuid"]):
        return "Drive has no usable UUID"
    if d["fstype"] not in _USB_FS_OK:
        return f"Filesystem '{d['fstype']}' is not supported"
    mp = d["mountpoint"]
    if mp in ("/", "/boot", "/boot/firmware"):
        return "System drive"
    if mp and mp != USB_MOUNT and not mp.startswith(IMPORT_ROOT + "/"):
        return f"Already mounted at {mp}; unmount it first"
    return None


_SYSTEM_MOUNTS = ("/", "/boot", "/boot/firmware", "/usr", "/var", "/home", "[SWAP]")
_FMT_LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
_FMT_TOOLS = ("wipefs", "sfdisk", "mkfs.ext4", "udevadm", "blkid", "mount", "umount")


def _usb_disks(data=None):
    data = data if data is not None else _lsblk_json()
    out = []
    for disk in (data or {}).get("blockdevices") or []:
        tran = str(disk.get("tran") or "").lower()
        if not (tran == "usb" or (_TEST_ALLOW_LOOP and disk.get("type") == "loop")):
            continue
        if disk.get("type") not in ("disk", "loop"):
            continue
        parts = []
        for n in [c for c in (disk.get("children") or []) if c.get("type") == "part"] or [disk]:
            parts.append({"path": str(n.get("path") or ("/dev/" + str(n.get("name") or ""))),
                          "fstype": str(n.get("fstype") or "").lower(), "label": str(n.get("label") or ""),
                          "uuid": str(n.get("uuid") or ""), "mountpoint": str(n.get("mountpoint") or ""),
                          "size": int(n.get("size") or 0) if str(n.get("size") or "0").isdigit() else 0})
        name = str(disk.get("name") or "")
        size = int(disk.get("size") or 0) if str(disk.get("size") or "0").isdigit() else 0
        model = str(disk.get("model") or "").strip()
        serial = str(disk.get("serial") or "").strip()
        fp = hashlib.sha256(f"{name}|{size}|{serial}|{model}".encode("utf-8", "replace")).hexdigest()[:16]
        out.append({"name": name, "path": str(disk.get("path") or ("/dev/" + name)), "size": size,
                    "model": model, "serial": serial, "fp": fp, "parts": parts})
    return out


def _format_block_reason(disk):
    lib = _cfg_get("usb_uuid")
    for p in disk["parts"]:
        if lib and p["uuid"] == lib:
            return "This is the library drive; replace it or switch to the SD card first"
        mp = p["mountpoint"]
        if mp in _SYSTEM_MOUNTS:
            return "System disk" if mp != "[SWAP]" else "In use as swap"
        if mp and not mp.startswith(IMPORT_ROOT + "/"):
            return f"Mounted at {mp}; unmount it first"
    if not re.match(r"^[A-Za-z0-9]+$", disk["name"]):
        return "Unexpected device name"
    return None


def _kernel_has_fs(name):
    text = _read_text("/proc/filesystems") or ""
    return any(line.split()[-1] == name for line in text.splitlines() if line.strip())


def _ntfs_type():
    if _kernel_has_fs("ntfs3"):
        return "ntfs3"
    if shutil.which("mount.ntfs-3g") or shutil.which("ntfs-3g"):
        return "ntfs-3g"
    return None


def _mount_args(fstype, ro):
    t = fstype
    opts = ["nosuid", "nodev", "noexec", "noatime", "ro" if ro else "rw"]
    if fstype in ("ext3", "ext4") and ro:
        opts.append("noload")
    if fstype in ("vfat", "exfat"):
        opts += ["uid=0", "gid=0", "umask=022"]
    elif fstype == "ntfs":
        t = _ntfs_type()
        if t is None:
            return None
        opts += ["uid=0", "gid=0", "umask=022"]
    return t, ",".join(opts)


def _do_mount(drive, mountpoint, ro):
    args = _mount_args(drive["fstype"], ro)
    if args is None:
        return False, "NTFS driver not available (apt install ntfs-3g)"
    t, opts = args
    try:
        os.makedirs(mountpoint, exist_ok=True)
        r = subprocess.run(["mount", "-t", t, "-o", opts, drive["path"], mountpoint],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"mount failed: {exc}"
    if r.returncode != 0:
        return False, "mount failed: " + ((r.stderr or r.stdout or "").strip()[:200] or f"exit {r.returncode}")
    info = _mount_info(mountpoint)
    if not _is_mount(mountpoint) or info is None:
        return False, "mount did not take effect"
    if not ro and "rw" not in info[1]:
        _do_umount(mountpoint)
        return False, "mounted read-only (dirty filesystem?); run fsck on another computer"
    return True, None


def _do_umount(mountpoint, lazy=False):
    try:
        if not lazy:
            subprocess.run(["sync"], capture_output=True, timeout=120)
        r = subprocess.run(["umount"] + (["-l"] if lazy else []) + [mountpoint],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"umount failed: {exc}"
    if r.returncode != 0:
        return False, "umount failed: " + ((r.stderr or r.stdout or "").strip()[:200] or "busy")
    return True, None


_sd_writes = {}
_sd_writes_lock = threading.Lock()


def _note_sd_write(kind):
    with _sd_writes_lock:
        _sd_writes[kind] = _sd_writes.get(kind, 0) + 1


def _sd_writes_snapshot():
    with _sd_writes_lock:
        return dict(_sd_writes)


def _staged_dir():
    if _cfg_get("usb_uuid") and _is_mount(USB_MOUNT):
        return os.path.join(_cfg_get("library_root"), ".pibrary", "staged")
    return STAGED_DIR


def _persist_dir(sub):
    if _cfg_get("usb_uuid") and not _is_mount(USB_MOUNT):
        return None
    return os.path.join(_cfg_get("library_root"), ".pibrary", sub)


def _usb_scan():
    data = _lsblk_json()
    if data is None:
        return None
    return _detect_usb_drives(data)


def _missing_twice(key, missing):
    if not missing:
        _missing_counts.pop(key, None)
        return False
    _missing_counts[key] = _missing_counts.get(key, 0) + 1
    return _missing_counts[key] >= 2


def _lib_space():
    if not _library_online():
        return None, None
    try:
        st = os.statvfs(_cfg_get("library_root"))
    except OSError:
        return None, None
    return st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize


def _storage_log(key, state, msg, level="info"):
    if _storage_seen.get(key) != state:
        _storage_seen[key] = state
        log_event(msg, level)


_FAULT_ERRNOS = {errno.EIO, errno.ENODEV, errno.ENXIO, errno.ESTALE, errno.ENOTCONN}
PROBE_TIMEOUT_SEC = 5
FAULT_MAX_TRIES = 3
FAULT_WINDOW_SEC = 600
_faults = {}
_faults_lock = threading.Lock()
_probe_stuck = _LockedSet()


def _probe_path(path, mountpoint):
    if path in _probe_stuck:
        return "not responding (an earlier check is still waiting)"
    result = {}

    def work():
        try:
            try:
                os.listdir(path)
            except (FileNotFoundError, NotADirectoryError):
                os.listdir(mountpoint)
            os.statvfs(mountpoint)
            result["ok"] = True
        except OSError as exc:
            result["err"] = exc
        finally:
            _probe_stuck.discard(path)

    _probe_stuck.add(path)
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(PROBE_TIMEOUT_SEC)
    if t.is_alive():
        return f"not responding after {PROBE_TIMEOUT_SEC}s"
    exc = result.get("err")
    if exc is not None and exc.errno in _FAULT_ERRNOS:
        return os.strerror(exc.errno)
    return None


def _mount_health(mountpoint, drive, probe):
    info = _mount_info(mountpoint)
    if info is None:
        return None
    src = info[2]
    if src.startswith("/dev/"):
        if not os.path.exists(src):
            return f"device {src} disappeared"
        if drive is not None and drive.get("path") and os.path.realpath(drive["path"]) != os.path.realpath(src):
            return f"drive reconnected as {drive['path']}"
    return _probe_path(probe, mountpoint)


def _fault_record(key, msg):
    now = time.time()
    with _faults_lock:
        f = _faults.setdefault(key, {"msg": "", "since": now, "times": [], "active": False})
        if not f["active"]:
            f["since"] = now
        f["msg"] = msg
        f["active"] = True
        f["times"] = [t for t in f["times"] if now - t < FAULT_WINDOW_SEC] + [now]
        return len(f["times"])


def _fault_get(key):
    with _faults_lock:
        f = _faults.get(key)
        return dict(f) if f and f["active"] else None


def _fault_resolve(key):
    with _faults_lock:
        f = _faults.get(key)
        if not f or not f["active"]:
            return False
        f["active"] = False
        return True


def _fault_clear(key):
    with _faults_lock:
        return _faults.pop(key, None) is not None


def _lib_fault_info():
    f = _fault_get("lib")
    uuid = _cfg_get("usb_uuid")
    if not f or not uuid:
        return {"fault": None, "gave_up": False}
    return {"fault": f["msg"], "gave_up": uuid in _storage_ejected}


def _offline_reason():
    f = _lib_fault_info()
    if f["fault"]:
        return (f"The USB library drive has an error ({f['fault']}); "
                + ("auto-remount stopped: check power, then replug it or press Mount" if f["gave_up"]
                   else "reconnecting"))
    return "The USB library drive is not connected"


def _lib_fault(why, drive=None):
    lib = _cfg_get("usb_uuid")
    n = _fault_record("lib", why)
    _do_umount(USB_MOUNT, lazy=True)
    with _scan_lock:
        _scan_cache.clear()
    _storage_seen["lib"] = "fault"
    log_event(f"Library drive error ({why}); unmounted it (power or cable problem?)", "err")
    if n >= FAULT_MAX_TRIES and lib:
        _storage_ejected.add(lib)
        log_event(f"Library drive failed {n} times in {FAULT_WINDOW_SEC // 60} min; auto-remount stopped. "
                  "Fix power (powered hub for SSD/HDD), then replug it or press Mount.", "err")


def _imp_fault(name, why):
    n = _fault_record("imp-" + name, why)
    mp = os.path.join(IMPORT_ROOT, name)
    _do_umount(mp, lazy=True)
    with _imp_lock:
        _imp_cache.clear()
    try:
        os.rmdir(mp)
    except OSError:
        pass
    log_event(f"Import drive {_storage_labels.get(name, name)} error ({why}); unmounted it", "err")
    if n >= FAULT_MAX_TRIES:
        _storage_ejected.add(name)
        log_event(f"Import drive {_storage_labels.get(name, name)} failed {n} times; auto-mount stopped "
                  "until it is replugged or Mount is pressed", "err")


def _storage_tick():
    if os.geteuid() != 0:
        return
    if not _storage_op_lock.acquire(blocking=False):
        return
    handed_off = False
    try:
        drives = _usb_scan()
        if drives is None:
            _storage_log("scan", "fail", "USB scan failed (lsblk); leaving all mounts untouched", "warn")
            return
        if _storage_seen.get("scan") == "fail":
            log_event("USB scan recovered", "info")
        _storage_seen["scan"] = "ok"
        by_uuid = {d["uuid"]: d for d in drives if d["uuid"]}
        for d in drives:
            if d["uuid"]:
                _storage_labels[_safe_name(d["uuid"])] = d["label"] or d["uuid"]
        for u in _storage_ejected.snapshot():
            if _missing_twice("ej-" + u, u not in by_uuid):
                _storage_ejected.discard(u)
                _missing_counts.pop("ej-" + u, None)
                if _autoimp.pop(_safe_name(u), None) is not None:
                    _led(None)
        lib = _cfg_get("usb_uuid")
        if lib:
            d = by_uuid.get(lib)
            mounted = _is_mount(USB_MOUNT)
            if mounted:
                why = _mount_health(USB_MOUNT, d, _cfg_get("library_root"))
                if why:
                    _lib_fault(why, d)
                    mounted = _is_mount(USB_MOUNT)
            if d is not None:
                _missing_twice("lib", False)
                if not mounted and lib not in _storage_ejected and _drive_note(d) is None:
                    ok, err = _do_mount(d, USB_MOUNT, ro=False)
                    with _scan_lock:
                        _scan_cache.clear()
                    why = _mount_health(USB_MOUNT, d, _cfg_get("library_root")) if ok else None
                    if why:
                        _lib_fault(why, d)
                    elif ok:
                        if _fault_resolve("lib"):
                            log_event("Library drive recovered and remounted", "ok")
                        _storage_log("lib", "up", f"Library drive mounted at {USB_MOUNT}", "ok")
                        _ensure_media_dirs(sweep=True)
                    else:
                        _storage_log("lib", "fail", f"Library drive mount failed: {err}", "err")
                elif mounted:
                    _storage_log("lib", "up", "Library drive online", "ok")
            elif _missing_twice("lib", True):
                if mounted:
                    _do_umount(USB_MOUNT, lazy=True)
                    with _scan_lock:
                        _scan_cache.clear()
                _storage_log("lib", "gone",
                             "Library drive was removed" if mounted else "Library drive is not connected", "warn")
        names = sorted(os.listdir(IMPORT_ROOT)) if os.path.isdir(IMPORT_ROOT) else []
        present = {_safe_name(u) for u in by_uuid}
        by_name = {_safe_name(u): dd for u, dd in by_uuid.items()}
        for n in names:
            mp = os.path.join(IMPORT_ROOT, n)
            if not _is_mount(mp):
                continue
            if _missing_twice("imp-" + n, n not in present):
                _do_umount(mp, lazy=True)
                with _imp_lock:
                    _imp_cache.clear()
                try:
                    os.rmdir(mp)
                except OSError:
                    pass
                log_event(f"Import drive {_storage_labels.get(n, n)} removed", "info")
                if _autoimp.pop(n, None) is not None:
                    _led(None)
                continue
            why = _mount_health(mp, by_name.get(n), mp)
            if why:
                _imp_fault(n, why)
            elif _fault_resolve("imp-" + n):
                log_event(f"Import drive {_storage_labels.get(n, n)} recovered", "ok")
        if lib:
            names = sorted(os.listdir(IMPORT_ROOT)) if os.path.isdir(IMPORT_ROOT) else []
            count = sum(1 for n in names if _is_mount(os.path.join(IMPORT_ROOT, n)))
            for d in drives:
                u = d["uuid"]
                if count >= IMPORT_MAX_MOUNTS:
                    break
                if (not u or u == lib or u in _storage_ejected or d["mountpoint"]
                        or _drive_note(d) is not None or _is_mount(_import_path(u))):
                    continue
                ok, err = _do_mount(d, _import_path(u), ro=True)
                with _imp_lock:
                    _imp_cache.clear()
                if ok:
                    count += 1
                    log_event(f"Import drive {d['label'] or u} mounted read-only", "ok")
                else:
                    _storage_log("imp-" + u, "fail", f"Import drive {d['label'] or u}: {err}", "err")
            handed_off = _autoimport_check()
    except Exception as exc:
        log_event(f"Storage watcher error: {exc}", "err")
    finally:
        if not handed_off:
            _storage_op_lock.release()


def _storage_watch_loop():
    while True:
        _storage_tick()
        time.sleep(STORAGE_POLL_SEC)


AUTOIMP_DIR = "PIBRARY-IMPORT"
AUTOIMP_SETTLE_SEC = 10
AUTOIMP_MAX_FILES = 5000
_AUTOIMP_TAB_DIRS = {"movies": "movie", "movie": "movie", "videos": "movie", "video": "movie", "films": "movie",
                     "audio": "audio", "music": "audio", "podcasts": "audio", "audiobooks": "audio",
                     "pdf": "pdf", "pdfs": "pdf", "documents": "pdf", "books": "pdf"}
_autoimp = {}
_LED = {"path": None, "orig": None}


def _led(mode):
    p = _LED["path"]
    if p is None:
        p = next((os.path.join("/sys/class/leds", n) for n in ("ACT", "led0")
                  if os.path.isdir(os.path.join("/sys/class/leds", n))), "")
        _LED["path"] = p
    if not p:
        return
    try:
        if _LED["orig"] is None:
            m = re.search(r"\[([^\]]+)\]", _read_text(os.path.join(p, "trigger")) or "")
            _LED["orig"] = m.group(1) if m else "mmc0"

        def put(name, value):
            with open(os.path.join(p, name), "w") as fh:
                fh.write(value)

        if mode is None:
            put("trigger", _LED["orig"])
        elif mode == "busy":
            put("trigger", "heartbeat")
        elif mode == "done":
            put("trigger", "default-on")
        elif mode == "error":
            put("trigger", "timer")
            put("delay_on", "100")
            put("delay_off", "100")
    except OSError as exc:
        log_event(f"Activity LED not available: {exc}", "info")


def _find_marker(mp):
    try:
        for n in os.listdir(mp):
            full = os.path.join(mp, n)
            if n.lower() == AUTOIMP_DIR.lower() and os.path.isdir(full) and not os.path.islink(full):
                return full
    except OSError:
        pass
    return None


def _autoimport_check():
    if not _cfg_get("auto_import") or not _cfg_get("usb_uuid") or not _library_online() or _mig_running():
        return False
    now = time.time()
    for name in _import_mounts():
        st = _autoimp.get(name)
        if st and st["state"] in ("running", "done", "failed", "none"):
            continue
        marker = _find_marker(os.path.join(IMPORT_ROOT, name))
        if not marker:
            _autoimp[name] = {"state": "none", "since": now}
            continue
        if st is None:
            _autoimp[name] = {"state": "seen", "since": now}
            log_event(f"Auto-import: {_storage_labels.get(name, name)} has a {AUTOIMP_DIR} folder; "
                      f"starting in {AUTOIMP_SETTLE_SEC}s", "info")
            _led("busy")
            continue
        if now - st["since"] < AUTOIMP_SETTLE_SEC:
            continue
        return _autoimport_start(name, marker)
    return False


def _autoimport_plan(name, marker):
    lib_root = _cfg_get("library_root")
    rec_path = os.path.join(lib_root, ".pibrary", "autoimport", name + ".json")
    record = {}
    try:
        with open(rec_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            record = {str(k): v for k, v in raw.items() if isinstance(v, list) and len(v) == 2}
    except (OSError, ValueError):
        pass
    fat = (_mount_fstype(USB_MOUNT) in ("vfat", "msdos"))
    ext_kind = {ext: k for k, spec in MEDIA_TYPES.items() for ext in spec["exts"]}
    today = time.strftime("%Y-%m-%d")
    pairs, done_rels, already, problems, pyfiles, planned = [], [], [], [], [], set()
    for dirpath, dirnames, filenames in os.walk(marker, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d.lower() not in _IMPORT_SKIP)
        for fn in sorted(filenames):
            if fn.startswith(".") or len(pairs) >= AUTOIMP_MAX_FILES:
                continue
            full = os.path.join(dirpath, fn)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            rel = os.path.relpath(full, marker).replace(os.sep, "/")
            parts = rel.split("/")
            if len(parts) == 1 and _SELF_NAME_RE.match(fn):
                pyfiles.append(full)
                continue
            kind = ext_kind.get(os.path.splitext(fn)[1].lower())
            if not kind:
                continue
            stamp = [st.st_size, int(st.st_mtime)]
            if record.get(rel) == stamp:
                already.append(rel)
                continue
            top = _AUTOIMP_TAB_DIRS.get(parts[0].lower()) if len(parts) > 1 else None
            sub = parts[1:] if top == kind else ["Imported", today] + (parts if top is None else parts[1:])
            bad = next((p for p in sub if _name_error(p)), None)
            if bad is not None:
                problems.append(f"{rel}: name not allowed on the library drive")
                continue
            if fat and st.st_size > FAT_MAX_FILE:
                problems.append(f"{rel}: over the 4 GB FAT32 limit")
                continue
            dst = os.path.join(lib_root, MEDIA_TYPES[kind]["dir"], *sub)
            if _same_file(dst, st.st_size, st.st_mtime):
                already.append(rel)
                continue
            if os.path.lexists(dst) or dst in planned:
                stem, ext = os.path.splitext(dst)
                i, dup = 2, False
                while True:
                    cand = f"{stem} ({i}){ext}"
                    if cand not in planned:
                        if not os.path.lexists(cand):
                            break
                        if _same_file(cand, st.st_size, st.st_mtime):
                            dup = True
                            break
                    i += 1
                if dup:
                    already.append(rel)
                    continue
                dst = cand
            planned.add(dst)
            pairs.append((full, dst, st.st_size, st.st_mtime))
            done_rels.append((rel, stamp))
    return pairs, done_rels, already, problems, pyfiles, rec_path, record


def _autoimport_record(rec_path, record, marker, rels):
    for rel, stamp in rels:
        record[rel] = stamp
    try:
        _atomic_write(rec_path, json.dumps(record).encode("utf-8"), 0o644)
    except OSError as exc:
        log_event(f"Auto-import: could not save the import record: {exc}", "warn")


def _autoimport_stage(pyfiles):
    staged = []
    for full in pyfiles:
        err, ver = _self_validate_file(full)
        if err:
            log_event(f"Auto-import: {os.path.basename(full)} not staged: {err}", "warn")
            continue
        dst_dir = _staged_dir()
        try:
            os.makedirs(dst_dir, exist_ok=True)
            tmp = os.path.join(dst_dir, ".upload-%s.part" % secrets.token_hex(6))
            shutil.copyfile(full, tmp)
            os.replace(tmp, os.path.join(dst_dir, os.path.basename(full)))
            staged.append(f"{os.path.basename(full)} (v{ver})")
        except OSError as exc:
            log_event(f"Auto-import: staging {os.path.basename(full)} failed: {exc}", "warn")
    if staged:
        _prune_staged()
        log_event("Auto-import: staged " + ", ".join(staged) + " (not installed; install from Config)", "ok")
    return staged


def _autoimport_eject(name):
    mp = os.path.join(IMPORT_ROOT, name)
    ok, _err = _do_umount(mp)
    if not ok:
        ok, _err = _do_umount(mp, lazy=True)
    if ok:
        _storage_ejected.add(name)
        try:
            os.rmdir(mp)
        except OSError:
            pass
        with _imp_lock:
            _imp_cache.clear()
    return ok


def _autoimport_start(name, marker):
    label = _storage_labels.get(name, name)
    st = _autoimp[name]
    try:
        pairs, done_rels, already, problems, pyfiles, rec_path, record = _autoimport_plan(name, marker)
    except OSError as exc:
        st["state"] = "failed"
        _led("error")
        log_event(f"Auto-import from {label} failed: {exc}", "err")
        notify(f"Auto-import from {label} FAILED: {exc}", "err")
        return False
    tail = ((f", {len(already)} already imported" if already else "")
            + (f", {len(problems)} not copied (first: {problems[0]})" if problems else ""))
    if not pairs:
        _autoimport_record(rec_path, record, marker, [])
        staged = _autoimport_stage(pyfiles)
        ej = _autoimport_eject(name)
        st["state"] = "done"
        _led("done")
        msg = (f"Auto-import from {label}: nothing new{tail}"
               + (f"; update {', '.join(staged)} staged (not installed)" if staged else "")
               + ("; drive ejected, safe to unplug" if ej else ""))
        log_event(msg, "ok")
        notify(msg, "info")
        return False
    total = sum(p[2] for p in pairs)
    try:
        free = _free_bytes(_cfg_get("library_root"))
    except OSError:
        free = 0
    if total + RESERVE_BYTES > free:
        st["state"] = "failed"
        _led("error")
        msg = (f"Auto-import from {label} not started: needs {_fmt_bytes(total)}, "
               f"only {_fmt_bytes(free)} free on the library drive")
        log_event(msg, "err")
        notify(msg, "err")
        return False
    st["state"] = "running"
    t0 = time.time()

    def finalize():
        _autoimport_record(rec_path, record, marker, done_rels)
        staged = _autoimport_stage(pyfiles)
        for k in MEDIA_TYPES:
            _invalidate_scan(k)
        ej = _autoimport_eject(name)
        st["state"] = "done"
        _led("done")
        mins = max(1, int(round((time.time() - t0) / 60)))
        msg = (f"Auto-import from {label}: {len(pairs)} file(s), {_fmt_bytes(total)} in {mins} min{tail}"
               + (f"; update {', '.join(staged)} staged (not installed)" if staged else "")
               + ("; drive ejected, safe to unplug" if ej else "; could not eject the drive"))
        notify(msg, "info")
        return msg

    def on_fail():
        st["state"] = "failed"
        _led("error")
        for k in MEDIA_TYPES:
            _invalidate_scan(k)
        err = _mig_snapshot().get("error") or "unknown error"
        notify(f"Auto-import from {label} FAILED: {err}", "err")

    log_event(f"Auto-import from {label}: copying {len(pairs)} file(s), {_fmt_bytes(total)}"
              + (f" ({len(already)} already imported)" if already else ""), "info")
    _start_copy_job("autoimport", pairs, finalize, on_fail, verify=True)
    return True


def _mig_blank():
    return {"running": False, "kind": "", "phase": "", "files_total": 0, "files_done": 0,
            "bytes_total": 0, "bytes_done": 0, "current": "", "failed": [], "skipped": 0,
            "error": "", "message": "", "done": False, "cancel": False, "no_cancel": False, "result": ""}


_mig = _mig_blank()


def _mig_set(**kw):
    with _mig_lock:
        _mig.update(kw)


def _mig_inc(key, n):
    with _mig_lock:
        _mig[key] += n


def _mig_cancelled():
    with _mig_lock:
        return _mig["cancel"]


def _mig_running():
    with _mig_lock:
        return _mig["running"]


def _migrating():
    with _mig_lock:
        return _mig["running"] and _mig["kind"] in ("to-usb", "to-sd", "replace")


def _start_copy_job(kind, pairs, finalize=None, on_fail=None, verify=False):
    _mig_set(running=True, kind=kind, phase="starting", done=False, error="", message="", failed=[],
             cancel=False, files_total=len(pairs), files_done=0, bytes_total=sum(p[2] for p in pairs),
             bytes_done=0, skipped=0, current="", no_cancel=False, result="")
    try:
        threading.Thread(target=_run_copy_job, args=(kind, pairs, finalize, on_fail, verify),
                         daemon=True).start()
    except Exception as exc:
        _mig_set(running=False, done=True, phase="done", error=f"Could not start the copy job: {exc}")
        raise


def _mig_snapshot():
    with _mig_lock:
        d = dict(_mig)
        d["failed_total"] = len(_mig["failed"])
        d["failed"] = list(_mig["failed"])[:20]
    return d


def _media_files(root):
    out = []
    for spec in MEDIA_TYPES.values():
        base = os.path.join(root, spec["dir"])
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames[:] = [x for x in dirnames if not x.startswith(".")]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode):
                    out.append((full, os.path.relpath(full, root), st.st_size, st.st_mtime))
    return out


def _dest_problems(files, fstype):
    if fstype not in _NON_POSIX_FS:
        return []
    out = []
    for _full, rel, size, _mt in files:
        if any(_BAD_NAME_RE.search(part) for part in rel.split(os.sep)):
            out.append(f"{rel}: name not allowed on {fstype}")
        elif fstype in ("vfat", "msdos") and size > FAT_MAX_FILE:
            out.append(f"{rel}: over the 4 GB FAT32 limit")
    return out


def _same_file(dst, size, mtime):
    try:
        st = os.stat(dst)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_size == size and abs(st.st_mtime - mtime) <= 2.5


def _sha256_file(path, cancel_check=None):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            if cancel_check is not None and cancel_check():
                raise InterruptedError("cancelled")
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _copy_file_atomic(src, dst, mtime, verify=False):
    directory = os.path.dirname(dst)
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, ".upload-%s.part" % secrets.token_hex(6))
    try:
        digest = hashlib.sha256() if verify else None
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while True:
                if _mig_cancelled():
                    raise InterruptedError("cancelled")
                chunk = fi.read(1024 * 1024)
                if not chunk:
                    break
                fo.write(chunk)
                if digest is not None:
                    digest.update(chunk)
                _mig_inc("bytes_done", len(chunk))
            fo.flush()
            os.fsync(fo.fileno())
            if verify and hasattr(os, "posix_fadvise"):
                try:
                    os.posix_fadvise(fo.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                except OSError:
                    pass
        if verify:
            _mig_set(phase="verifying")
            got = _sha256_file(tmp, _mig_cancelled)
            _mig_set(phase="copying")
            if got != digest.hexdigest():
                raise OSError("checksum mismatch after copy")
        os.replace(tmp, dst)
        try:
            os.utime(dst, (mtime, mtime))
        except OSError:
            pass
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    _fsync_dir(directory)


def _run_copy_job(kind, pairs, finalize=None, on_fail=None, verify=False):
    succeeded = False
    try:
        _mig_set(running=True, kind=kind, phase="copying", files_total=len(pairs), files_done=0,
                 bytes_total=sum(p[2] for p in pairs), bytes_done=0, failed=[], skipped=0,
                 error="", message="", done=False, current="")
        failed = []
        skipped = 0
        drive_lost = None
        for i, (src, dst, size, mtime) in enumerate(pairs):
            if _mig_cancelled():
                break
            _mig_set(current=os.path.basename(dst))
            if _same_file(dst, size, mtime):
                skipped += 1
                _mig_inc("bytes_done", size)
                _mig_set(files_done=i + 1, skipped=skipped)
                continue
            try:
                _copy_file_atomic(src, dst, mtime, verify)
                got = os.path.getsize(dst)
                if got != size:
                    raise OSError(f"size mismatch ({got} != {size})")
            except InterruptedError:
                break
            except OSError as exc:
                failed.append(f"{os.path.basename(dst)}: {exc}")
                if exc.errno in _FAULT_ERRNOS:
                    drive_lost = exc
                    _mig_set(files_done=i + 1, failed=list(failed))
                    break
            _mig_set(files_done=i + 1, failed=list(failed))
        if drive_lost is not None:
            _mig_set(error=f"A drive stopped responding ({os.strerror(drive_lost.errno)}); the job was stopped. "
                           "Nothing was switched; finished files are kept. Check power and cable.")
            log_event(f"{kind}: stopped, a drive stopped responding: {drive_lost}", "err")
        elif _mig_cancelled():
            _mig_set(error="Cancelled. Nothing was switched; finished files are kept.")
            log_event(f"{kind}: cancelled", "warn")
        elif failed:
            _mig_set(error=f"{len(failed)} file(s) failed; nothing was switched.")
            log_event(f"{kind}: {len(failed)} file(s) failed (first: {failed[0]})", "err")
        else:
            msg = f"Copied {len(pairs) - skipped} file(s)" + (f", {skipped} already present" if skipped else "")
            if finalize is not None:
                extra = finalize()
                if extra:
                    msg += ". " + extra
            _mig_set(message=msg + ".")
            log_event(f"{kind}: {msg}", "ok")
            succeeded = True
    except Exception as exc:
        _mig_set(error=f"Job failed: {exc}")
        log_event(f"{kind}: job failed: {exc}", "err")
    finally:
        if not succeeded and on_fail is not None:
            try:
                on_fail()
            except Exception as exc:
                log_event(f"{kind}: cleanup failed: {exc}", "err")
        _mig_set(running=False, done=True, phase="done")
        _storage_op_lock.release()


def _cfg_apply_internal(updates):
    with _cfg_lock:
        new = dict(_cfg)
        for key, raw in updates.items():
            new[key] = _NORMALIZERS[key](raw)
        try:
            save_config(new)
        except OSError as exc:
            return False, f"Cannot write {CONFIG_PATH}: {exc}"
        _cfg.update(new)
    with _scan_lock:
        _scan_cache.clear()
    return True, None


def _finalize_use_usb(uuid, old_root):
    ok, err = _cfg_apply_internal({"usb_uuid": uuid, "sd_root": old_root,
                                   "library_root": os.path.join(USB_MOUNT, USB_SUBDIR)})
    if not ok:
        raise OSError(err)
    _storage_ejected.discard(uuid)
    log_event(f"Library moved to USB drive ({USB_MOUNT}/{USB_SUBDIR})", "ok")
    return "Library is now on the USB drive"


def _finalize_use_sd():
    sd_root = _cfg_get("sd_root")
    if _is_mount(USB_MOUNT):
        if _upload_lock.locked() or _streams_active > 0:
            raise OSError("The drive is in use (an upload or stream is active); nothing was switched")
        _pos_flush()
        ok, err = _do_umount(USB_MOUNT)
        if not ok:
            raise OSError(f"{err}; nothing was switched")
    ok, err = _cfg_apply_internal({"usb_uuid": "", "library_root": sd_root})
    if not ok:
        raise OSError(err)
    _fault_clear("lib")
    log_event(f"Library moved back to the SD card ({sd_root})", "ok")
    return "Library is back on the SD card"


def _free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def _unmount_unless_library():
    if not _cfg_get("usb_uuid") and _is_mount(USB_MOUNT):
        _do_umount(USB_MOUNT)


def _conflicts(files, dest_root):
    out = []
    for _src, rel, size, mt in files:
        dst = os.path.join(dest_root, rel)
        if os.path.lexists(dst) and not _same_file(dst, size, mt):
            out.append(rel)
    return out


def storage_use_drive(uuid, copy, overwrite=False, verify=False):
    if _cfg_get("usb_uuid"):
        return 409, {"error": "A library drive is already set; switch to the SD card first"}, False
    if _upload_lock.locked():
        return 409, {"error": "An upload is in progress; try again when it finishes"}, False
    if not _UUID_RE.match(uuid or ""):
        return 400, {"error": "Invalid drive"}, False
    d = {x["uuid"]: x for x in _detect_usb_drives() if x["uuid"]}.get(uuid)
    if d is None:
        return 404, {"error": "Drive not found; rescan"}, False
    note = _drive_note(d)
    if note:
        return 400, {"error": note}, False
    if d["mountpoint"].startswith(IMPORT_ROOT + "/"):
        ok, err = _do_umount(d["mountpoint"])
        if not ok:
            return 409, {"error": err}, False
    if _is_mount(USB_MOUNT) and d["mountpoint"] != USB_MOUNT:
        return 409, {"error": f"Another drive is mounted at {USB_MOUNT}"}, False
    mounted_here = False
    if not _is_mount(USB_MOUNT):
        ok, err = _do_mount(d, USB_MOUNT, ro=False)
        if not ok:
            return 500, {"error": err}, False
        mounted_here = True
    result = _use_drive_prepare(d, uuid, copy, overwrite, verify, mounted_here)
    if result[0] >= 400 and mounted_here and _is_mount(USB_MOUNT):
        _do_umount(USB_MOUNT)
    return result


def _use_drive_prepare(d, uuid, copy, overwrite, verify, mounted_here):
    base = os.path.join(USB_MOUNT, USB_SUBDIR)
    try:
        for spec in MEDIA_TYPES.values():
            os.makedirs(os.path.join(base, spec["dir"]), exist_ok=True)
    except OSError as exc:
        return 500, {"error": f"Cannot create folders on the drive: {exc}"}, False
    old_root = _cfg_get("library_root")
    files = _media_files(old_root) if copy else []
    if files:
        problems = _dest_problems(files, _mount_fstype(USB_MOUNT) or d["fstype"])
        if problems:
            return 400, {"error": f"{len(problems)} file(s) cannot be stored on this filesystem",
                         "problems": problems[:20]}, False
        conflicts = _conflicts(files, base)
        if conflicts and not overwrite:
            return 409, {"error": f"{len(conflicts)} file(s) already exist on the drive with different content "
                                  "(tick Overwrite conflicts to replace them)",
                         "problems": conflicts[:20], "conflicts": len(conflicts)}, False
        total = sum(f[2] for f in files)
        try:
            free = _free_bytes(USB_MOUNT)
        except OSError as exc:
            return 500, {"error": f"Cannot read drive free space: {exc}"}, False
        if total + RESERVE_BYTES > free:
            return 507, {"error": f"Not enough space on the drive ({total} bytes needed)"}, False
        pairs = [(src, os.path.join(base, rel), size, mt) for src, rel, size, mt in files]
        _start_copy_job("to-usb", pairs, lambda: _finalize_use_usb(uuid, old_root),
                        _unmount_unless_library if mounted_here else None, bool(verify))
        return 200, {"ok": True, "started": True, "files": len(files), "bytes": total}, True
    try:
        _finalize_use_usb(uuid, old_root)
    except OSError as exc:
        return 500, {"error": str(exc)}, False
    return 200, {"ok": True, "switched": True}, False


def storage_use_sd(copy_back, overwrite=False, verify=False):
    if not _cfg_get("usb_uuid"):
        return 409, {"error": "Already using the SD card"}, False
    if _upload_lock.locked() or _streams_active > 0:
        return 409, {"error": "The drive is in use (an upload or stream is active); try again in a moment"}, False
    sd_root = _cfg_get("sd_root")
    usb_root = _cfg_get("library_root")
    if copy_back:
        if not _library_online():
            return 409, {"error": _offline_reason() + "; cannot copy back"}, False
        files = _media_files(usb_root)
        if files:
            conflicts = _conflicts(files, sd_root)
            if conflicts and not overwrite:
                return 409, {"error": f"{len(conflicts)} file(s) already exist on the SD card with different "
                                      "content (tick Overwrite conflicts to replace them)",
                             "problems": conflicts[:20], "conflicts": len(conflicts)}, False
            total = sum(f[2] for f in files)
            try:
                os.makedirs(sd_root, exist_ok=True)
                free = _free_bytes(sd_root)
            except OSError as exc:
                return 500, {"error": f"SD library folder unavailable: {exc}"}, False
            if total + RESERVE_BYTES > free:
                return 507, {"error": f"Not enough space on the SD card ({total} bytes needed)"}, False
            pairs = [(src, os.path.join(sd_root, rel), size, mt) for src, rel, size, mt in files]
            _start_copy_job("to-sd", pairs, _finalize_use_sd, None, bool(verify))
            return 200, {"ok": True, "started": True, "files": len(files), "bytes": total}, True
    try:
        _finalize_use_sd()
    except OSError as exc:
        return 409, {"error": str(exc)}, False
    return 200, {"ok": True, "switched": True}, False


def _run_purge_job(pairs):
    try:
        deleted = kept = freed = 0
        drive_lost = None
        for i, (src, dst, size) in enumerate(pairs):
            if _mig_cancelled():
                break
            _mig_set(current=os.path.basename(src))
            try:
                same = _sha256_file(src, _mig_cancelled) == _sha256_file(dst, _mig_cancelled)
            except InterruptedError:
                break
            except OSError as exc:
                if exc.errno in _FAULT_ERRNOS:
                    drive_lost = exc
                    break
                same = False
            if same:
                try:
                    os.unlink(src)
                    deleted += 1
                    freed += size
                except OSError:
                    kept += 1
            else:
                kept += 1
            _mig_inc("bytes_done", size)
            _mig_set(files_done=i + 1)
        sd_root = _cfg_get("sd_root")
        for spec in MEDIA_TYPES.values():
            base = os.path.join(sd_root, spec["dir"])
            for dirpath, _dn, _fn in os.walk(base, topdown=False):
                if dirpath != base:
                    try:
                        os.rmdir(dirpath)
                    except OSError:
                        pass
        if drive_lost is not None:
            _mig_set(error=f"Stopped after deleting {deleted} verified file(s): a drive stopped responding "
                           f"({os.strerror(drive_lost.errno)}). Nothing unverified was deleted.")
        elif _mig_cancelled():
            _mig_set(error=f"Cancelled after deleting {deleted} verified file(s).")
        else:
            _mig_set(message=f"Deleted {deleted} verified original(s) ({freed} bytes freed)"
                             + (f"; kept {kept} that did not verify" if kept else "") + ".")
        log_event(f"purge: deleted {deleted}, kept {kept}, freed {freed} bytes", "ok")
    except Exception as exc:
        _mig_set(error=f"Job failed: {exc}")
        log_event(f"purge: job failed: {exc}", "err")
    finally:
        _mig_set(running=False, done=True, phase="done")
        _storage_op_lock.release()


def storage_purge_originals():
    if not _cfg_get("usb_uuid") or not _library_online():
        return 409, {"error": "The library drive must be online"}, False
    sd_root = _cfg_get("sd_root")
    usb_root = _cfg_get("library_root")
    if os.path.realpath(sd_root) == os.path.realpath(usb_root):
        return 409, {"error": "SD and library folders are the same"}, False
    pairs, unmatched = [], 0
    for src, rel, size, mtime in _media_files(sd_root):
        dst = os.path.join(usb_root, rel)
        if _same_file(dst, size, mtime):
            pairs.append((src, dst, size))
        else:
            unmatched += 1
    if not pairs:
        return 200, {"ok": True, "deleted": 0, "kept": unmatched, "freed": 0}, False
    _mig_set(running=True, kind="purge", phase="verifying", done=False, error="", message="", failed=[],
             cancel=False, files_total=len(pairs), files_done=0, bytes_total=sum(p[2] for p in pairs),
             bytes_done=0, skipped=0, current="", no_cancel=False, result="")
    try:
        threading.Thread(target=_run_purge_job, args=(pairs,), daemon=True).start()
    except Exception as exc:
        _mig_set(running=False, done=True, phase="done", error=f"Could not start the job: {exc}")
        raise
    return 200, {"ok": True, "started": True, "files": len(pairs), "unmatched": unmatched}, True


def storage_eject(uuid):
    if not _UUID_RE.match(uuid or ""):
        return 400, {"error": "Invalid drive"}, False
    if _mig_running():
        return 409, {"error": "A copy job is running"}, False
    if uuid == _cfg_get("usb_uuid"):
        mp = USB_MOUNT
        if not _is_mount(mp) and _fault_get("lib"):
            _storage_ejected.add(uuid)
            _fault_clear("lib")
            log_event("Library drive marked ejected (it had an I/O error); safe to unplug", "ok")
            return 200, {"ok": True}, False
    else:
        mp = _import_path(uuid)
        if not _is_mount(mp):
            d = {x["uuid"]: x for x in _detect_usb_drives() if x["uuid"]}.get(uuid)
            mp = USB_MOUNT if d and d["mountpoint"] == USB_MOUNT else None
    if mp is None or not _is_mount(mp):
        return 409, {"error": "That drive is not mounted by Pibrary"}, False
    if mp == USB_MOUNT and (_upload_lock.locked() or _streams_active > 0):
        return 409, {"error": "The drive is in use (an upload or stream is active)"}, False
    dead = _mount_health(mp, None, mp)
    if mp == USB_MOUNT and not dead:
        _pos_flush()
        _log_file_flush()
    ok, err = _do_umount(mp, lazy=bool(dead))
    if not ok:
        return 409, {"error": err}, False
    _fault_clear("lib" if mp == USB_MOUNT else "imp-" + _safe_name(uuid))
    _storage_ejected.add(uuid)
    with _scan_lock:
        _scan_cache.clear()
    with _imp_lock:
        _imp_cache.clear()
    if mp != USB_MOUNT:
        try:
            os.rmdir(mp)
        except OSError:
            pass
    log_event(f"Ejected drive {_storage_labels.get(_safe_name(uuid), uuid)}; safe to unplug", "ok")
    return 200, {"ok": True}, False


def storage_mount(uuid):
    if not _UUID_RE.match(uuid or ""):
        return 400, {"error": "Invalid drive"}, False
    d = {x["uuid"]: x for x in _detect_usb_drives() if x["uuid"]}.get(uuid)
    if d is None:
        return 404, {"error": "Drive not found; rescan"}, False
    note = _drive_note(d)
    if note:
        return 400, {"error": note}, False
    _storage_ejected.discard(uuid)
    is_lib = uuid == _cfg_get("usb_uuid")
    fkey = "lib" if is_lib else "imp-" + _safe_name(uuid)
    _fault_clear(fkey)
    if is_lib:
        mp = USB_MOUNT
        if _is_mount(mp):
            return 200, {"ok": True}, False
        ok, err = _do_mount(d, mp, ro=False)
    else:
        mp = _import_path(uuid)
        if _is_mount(mp):
            return 200, {"ok": True}, False
        names = os.listdir(IMPORT_ROOT) if os.path.isdir(IMPORT_ROOT) else []
        if sum(1 for n in names if _is_mount(os.path.join(IMPORT_ROOT, n))) >= IMPORT_MAX_MOUNTS:
            return 409, {"error": f"At most {IMPORT_MAX_MOUNTS} import drives can be mounted"}, False
        ok, err = _do_mount(d, mp, ro=True)
    with _scan_lock:
        _scan_cache.clear()
    with _imp_lock:
        _imp_cache.clear()
    if not ok:
        return 500, {"error": err}, False
    why = _mount_health(mp, d, _cfg_get("library_root") if is_lib else mp)
    if why:
        if is_lib:
            _lib_fault(why, d)
        else:
            _imp_fault(_safe_name(uuid), why)
        return 500, {"error": f"Mounted, but the drive does not respond ({why}); check power and cable"}, False
    if is_lib:
        _ensure_media_dirs(sweep=True)
    return 200, {"ok": True}, False


_FMT_STEPS = ("unmounting", "erasing old signatures", "creating a GPT partition table",
              "waiting for the new partition", "creating the ext4 filesystem", "verifying")


def _run_cmd(args, timeout, stdin_text=None, log_output=False):
    log_event("Running: " + " ".join(shlex.quote(a) for a in args), "info")
    try:
        r = subprocess.run(args, input=stdin_text, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{args[0]} timed out after {timeout}s")
    except OSError as exc:
        raise RuntimeError(f"{args[0]}: {exc}")
    if log_output:
        for line in (r.stdout or "").splitlines()[-8:]:
            if line.strip():
                log_event(f"{args[0]}: {line.strip()}", "info")
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError(f"{args[0]} failed: " + (msg[-1][:200] if msg else f"exit {r.returncode}"))
    return r.stdout or ""


def _partition_path(disk_path):
    return disk_path + ("p1" if disk_path[-1:].isdigit() else "1")


def storage_format(name, fp, label, confirm):
    if confirm != "FORMAT":
        return 400, {"error": "Type FORMAT to confirm"}, False
    if not _FMT_LABEL_RE.match(label or ""):
        return 400, {"error": "Label: 1-16 letters, digits, _ or -"}, False
    if _mig_running():
        return 409, {"error": "A storage job is running"}, False
    missing = [t for t in _FMT_TOOLS if not shutil.which(t)]
    if missing:
        return 500, {"error": "Missing tools: " + " ".join(missing) + " (apt install fdisk e2fsprogs util-linux)"}, False
    data = _lsblk_json()
    if data is None:
        return 500, {"error": "Cannot list drives (lsblk failed)"}, False
    disk = next((x for x in _usb_disks(data) if x["name"] == name), None)
    if disk is None:
        return 404, {"error": "Drive not found; rescan"}, False
    if disk["fp"] != fp:
        return 409, {"error": "The drive list changed (drives were plugged or renamed); rescan and try again"}, False
    why = _format_block_reason(disk)
    if why:
        return 409, {"error": why}, False
    _mig_set(running=True, kind="format", phase="formatting", done=False, error="", message="", failed=[],
             cancel=False, files_total=len(_FMT_STEPS), files_done=0, bytes_total=0, bytes_done=0,
             skipped=0, current=_FMT_STEPS[0], no_cancel=False, result="")
    try:
        threading.Thread(target=_run_format_job, args=(disk, label), daemon=True).start()
    except Exception as exc:
        _mig_set(running=False, done=True, phase="done", error=f"Could not start the job: {exc}")
        raise
    desc = (disk["model"] or disk["name"]) + f" ({disk['path']})"
    log_event(f"Formatting {desc} as ext4, label {label}", "warn")
    return 200, {"ok": True, "started": True}, True


def _run_format_job(disk, label):
    desc = (disk["model"] or disk["name"]) + f" ({disk['path']})"
    erased = False

    def step(i):
        _mig_set(files_done=i, current=_FMT_STEPS[i])

    try:
        step(0)
        for p in disk["parts"]:
            mp = p["mountpoint"]
            if mp.startswith(IMPORT_ROOT + "/"):
                ok, err = _do_umount(mp)
                if not ok:
                    ok, err = _do_umount(mp, lazy=True)
                if not ok:
                    raise RuntimeError(err)
                try:
                    os.rmdir(mp)
                except OSError:
                    pass
        with _imp_lock:
            _imp_cache.clear()
        if _mig_cancelled():
            _mig_set(error="Cancelled before anything was erased.")
            log_event(f"Format of {desc} cancelled; nothing was erased", "warn")
            return
        _mig_set(no_cancel=True)
        erased = True
        step(1)
        for p in disk["parts"]:
            if p["path"] != disk["path"]:
                _run_cmd(["wipefs", "-a", p["path"]], 60)
        _run_cmd(["wipefs", "-a", disk["path"]], 60)
        step(2)
        _run_cmd(["sfdisk", "--wipe", "always", disk["path"]], 120, stdin_text="label: gpt\n,,L\n")
        step(3)
        part = _partition_path(disk["path"])
        try:
            _run_cmd(["udevadm", "settle", "--timeout=10"], 20)
        except RuntimeError:
            pass
        for _i in range(20):
            if os.path.exists(part):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"{part} did not appear after partitioning")
        step(4)
        _run_cmd(["mkfs.ext4", "-F", "-L", label, "-m", "0",
                  "-E", "lazy_itable_init=1,lazy_journal_init=1", part], 900, log_output=True)
        step(5)
        try:
            _run_cmd(["udevadm", "settle", "--timeout=10"], 20)
        except RuntimeError:
            pass
        info = {}
        for line in _run_cmd(["blkid", "-o", "export", part], 30).splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info[k.strip()] = v.strip()
        if info.get("TYPE") != "ext4" or not info.get("UUID"):
            raise RuntimeError(f"blkid does not report a new ext4 filesystem on {part}")
        os.makedirs(FMT_MOUNT, exist_ok=True)
        if _is_mount(FMT_MOUNT):
            _do_umount(FMT_MOUNT, lazy=True)
        _run_cmd(["mount", "-t", "ext4", "-o", "nosuid,nodev,noexec,noatime", part, FMT_MOUNT], 60)
        try:
            why = _probe_path(FMT_MOUNT, FMT_MOUNT)
        finally:
            ok, err = _do_umount(FMT_MOUNT)
        try:
            os.rmdir(FMT_MOUNT)
        except OSError:
            pass
        if why:
            raise RuntimeError(f"the new filesystem does not respond ({why})")
        step(len(_FMT_STEPS) - 1)
        _mig_set(files_done=len(_FMT_STEPS), result=info["UUID"],
                 message=f"Formatted {desc} as ext4 (label {label}, UUID {info['UUID']}).")
        log_event(f"Formatted {desc} as ext4 (label {label}, UUID {info['UUID']})", "ok")
    except Exception as exc:
        tail = " The drive may be half-formatted: format it again." if erased else " Nothing was erased."
        _mig_set(error=f"Format failed: {exc}.{tail}")
        log_event(f"Format of {desc} failed: {exc}", "err")
    finally:
        _mig_set(running=False, done=True, phase="done", no_cancel=False)
        _storage_op_lock.release()


def _dir_has_media(root):
    for spec in MEDIA_TYPES.values():
        base = os.path.join(root, spec["dir"])
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames[:] = [x for x in dirnames if not x.startswith(".")]
            if any(not f.startswith(".") and os.path.splitext(f)[1].lower() in spec["exts"] for f in filenames):
                return True
    return False


def _old_library_healthy():
    return (bool(_cfg_get("usb_uuid")) and _is_mount(USB_MOUNT)
            and _mount_health(USB_MOUNT, None, _cfg_get("library_root")) is None)


def _replace_cleanup():
    if _is_mount(NEW_MOUNT):
        ok, _err = _do_umount(NEW_MOUNT)
        if not ok:
            _do_umount(NEW_MOUNT, lazy=True)
    try:
        os.rmdir(NEW_MOUNT)
    except OSError:
        pass


def storage_replace(uuid, source, overwrite=False, verify=False):
    old = _cfg_get("usb_uuid")
    if not old:
        return 409, {"error": "No USB library drive is set; use 'Use this drive' instead"}, False
    if not _UUID_RE.match(uuid or "") or uuid == old:
        return 400, {"error": "Choose a different drive"}, False
    if source not in ("old", "sd", "none"):
        return 400, {"error": "Unknown copy source"}, False
    if _mig_running():
        return 409, {"error": "A storage job is running"}, False
    if _upload_lock.locked():
        return 409, {"error": "An upload is in progress; try again when it finishes"}, False
    _replace_cleanup()
    d = {x["uuid"]: x for x in _detect_usb_drives() if x["uuid"]}.get(uuid)
    if d is None:
        return 404, {"error": "Drive not found; rescan"}, False
    note = _drive_note(d)
    if note:
        return 400, {"error": note}, False
    if d["mountpoint"] == USB_MOUNT:
        return 409, {"error": f"That drive is mounted at {USB_MOUNT}"}, False
    if source == "old" and not _old_library_healthy():
        return 409, {"error": "The current library drive is not readable; choose SD card or Nothing"}, False
    src_root = _cfg_get("library_root") if source == "old" else _cfg_get("sd_root")
    if d["mountpoint"].startswith(IMPORT_ROOT + "/"):
        ok, err = _do_umount(d["mountpoint"])
        if not ok:
            return 409, {"error": err}, False
        try:
            os.rmdir(d["mountpoint"])
        except OSError:
            pass
        with _imp_lock:
            _imp_cache.clear()
        d = dict(d, mountpoint="")
    _replace_cleanup()
    ok, err = _do_mount(d, NEW_MOUNT, ro=False)
    if not ok:
        return 500, {"error": err}, False
    try:
        why = _mount_health(NEW_MOUNT, d, NEW_MOUNT)
        if why:
            raise OSError(f"The new drive does not respond ({why}); check power and cable")
        base = os.path.join(NEW_MOUNT, USB_SUBDIR)
        for spec in MEDIA_TYPES.values():
            os.makedirs(os.path.join(base, spec["dir"]), exist_ok=True)
        files = _media_files(src_root) if source != "none" else []
        if files:
            problems = _dest_problems(files, _mount_fstype(NEW_MOUNT) or d["fstype"])
            if problems:
                _replace_cleanup()
                return 400, {"error": f"{len(problems)} file(s) cannot be stored on this filesystem",
                             "problems": problems[:20]}, False
            conflicts = _conflicts(files, base)
            if conflicts and not overwrite:
                _replace_cleanup()
                return 409, {"error": f"{len(conflicts)} file(s) already exist on the new drive with different "
                                      "content (tick Overwrite conflicts to replace them)",
                             "problems": conflicts[:20], "conflicts": len(conflicts)}, False
            total = sum(f[2] for f in files)
            if total + RESERVE_BYTES > _free_bytes(NEW_MOUNT):
                _replace_cleanup()
                return 507, {"error": f"Not enough space on the new drive ({total} bytes needed)"}, False
            pairs = [(src, os.path.join(base, rel), size, mt) for src, rel, size, mt in files]
            _start_copy_job("replace", pairs, lambda: _finalize_replace(uuid, d, old, source),
                            _replace_cleanup, bool(verify))
            log_event(f"Replacing the library drive: copying {len(files)} file(s) from the "
                      f"{'old drive' if source == 'old' else 'SD card'}", "info")
            return 200, {"ok": True, "started": True, "files": len(files), "bytes": total}, True
        msg = _finalize_replace(uuid, d, old, source)
        return 200, {"ok": True, "switched": True, "message": msg}, False
    except OSError as exc:
        _replace_cleanup()
        return 500, {"error": str(exc)}, False


def _finalize_replace(new_uuid, new_drive, old_uuid, source):
    if _upload_lock.locked() or _streams_active > 0:
        raise OSError("The library drive is in use (an upload or stream is active); nothing was switched. "
                      "Copied files stay on the new drive; press Replace again to finish")
    old_ok = _old_library_healthy()
    new_lib = os.path.join(NEW_MOUNT, USB_SUBDIR)
    if old_ok:
        _pos_flush()
        _pos_merge_file(os.path.join(_cfg_get("library_root"), ".pibrary", "positions", POS_FILE),
                        os.path.join(new_lib, ".pibrary", "positions", POS_FILE))
    ok, err = _do_umount(NEW_MOUNT)
    if not ok:
        raise OSError(f"{err}; nothing was switched")
    if _is_mount(USB_MOUNT):
        ok, err = _do_umount(USB_MOUNT, lazy=not old_ok)
        if not ok:
            raise OSError(f"Cannot unmount the old drive ({err}); nothing was switched")
    old_drive = None
    if old_ok:
        old_drive = {x["uuid"]: x for x in _detect_usb_drives() if x["uuid"]}.get(old_uuid)

    def rollback(reason):
        if _is_mount(USB_MOUNT):
            _do_umount(USB_MOUNT, lazy=True)
        back = old_drive is not None and _do_mount(old_drive, USB_MOUNT, ro=False)[0]
        with _scan_lock:
            _scan_cache.clear()
        raise OSError(f"{reason}; the old drive " + ("is still the library" if back
                      else "could not be remounted (the watcher retries)") + ". Nothing was switched")

    ok, err = _do_mount(new_drive, USB_MOUNT, ro=False)
    if not ok:
        rollback(f"The new drive did not mount ({err})")
    why = _mount_health(USB_MOUNT, new_drive, os.path.join(USB_MOUNT, USB_SUBDIR))
    if why:
        rollback(f"The new drive does not respond ({why})")
    ok, err = _cfg_apply_internal({"usb_uuid": new_uuid, "library_root": os.path.join(USB_MOUNT, USB_SUBDIR)})
    if not ok:
        rollback(err)
    _fault_clear("lib")
    _storage_ejected.discard(new_uuid)
    _storage_ejected.add(old_uuid)
    with _pos_lock:
        _pos_state.update(where=None, data={}, dirty=False, warned=False)
    with _imp_lock:
        _imp_cache.clear()
    _storage_seen["lib"] = "up"
    _ensure_media_dirs(sweep=True)
    try:
        os.rmdir(NEW_MOUNT)
    except OSError:
        pass
    old_name = _storage_labels.get(_safe_name(old_uuid), old_uuid)
    new_name = new_drive.get("label") or new_uuid
    log_event(f"Library replaced: {old_name} -> {new_name}. The old drive is unmounted"
              + (" and safe to unplug" if old_ok else "") + "; nothing on it was changed.", "ok")
    return f"The library is now on {new_name}"


def storage_snapshot():
    uuid = _cfg_get("usb_uuid")
    out = []
    seen = set()
    for d in _detect_usb_drives():
        note = _drive_note(d)
        u = d["uuid"]
        seen.add(u)
        imp_mounted = bool(u) and _is_mount(_import_path(u))
        lib_mounted = bool(uuid) and u == uuid and _is_mount(USB_MOUNT)
        ours = (lib_mounted or imp_mounted or d["mountpoint"] == USB_MOUNT
                or d["mountpoint"].startswith(IMPORT_ROOT + "/"))
        if note and not ours:
            role = "unsupported"
        elif uuid:
            role = "library" if u == uuid else "import"
        else:
            role = "candidate"
        out.append({"uuid": u, "label": d["label"], "fstype": d["fstype"], "size": d["size"],
                    "path": d["path"], "role": role, "note": None if ours else note,
                    "mounted": ours, "eject": ours, "ejected": u in _storage_ejected})
    if uuid and uuid not in seen:
        out.append({"uuid": uuid, "label": "(not connected)", "fstype": "", "size": 0, "path": "",
                    "role": "library", "note": None, "mounted": False, "eject": False,
                    "ejected": uuid in _storage_ejected})
    lib = {"mode": "usb" if uuid else "sd", "state": _library_state(), "root": _cfg_get("library_root"),
           "sd_root": _cfg_get("sd_root"), "uuid": uuid, "free": None, "total": None, "fstype": None}
    lib.update(_lib_fault_info())
    if _library_online():
        try:
            st = os.statvfs(_cfg_get("library_root"))
            lib["free"], lib["total"] = st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize
        except OSError:
            pass
        if uuid:
            lib["fstype"] = _mount_fstype(USB_MOUNT)
    if not _cfg_get("auth_enabled"):
        reason = "Storage management requires login to be enabled (entry 2, then Save)."
    elif os.geteuid() != 0:
        reason = "Storage management needs Pibrary running as root."
    else:
        reason = None
    disks = []
    for x in _usb_disks():
        why = _format_block_reason(x)
        disks.append({"name": x["name"], "path": x["path"], "size": x["size"], "model": x["model"],
                      "fp": x["fp"], "can_format": why is None, "why": why,
                      "parts": [{"path": p["path"], "fstype": p["fstype"], "label": p["label"],
                                 "mountpoint": p["mountpoint"]} for p in x["parts"]]})
    sources = {"old": _old_library_healthy(), "sd": bool(uuid) and _dir_has_media(_cfg_get("sd_root"))}
    return {"can_manage": reason is None, "reason": reason, "library": lib, "drives": out,
            "disks": disks, "replace_sources": sources,
            "job": _mig_snapshot(), "allow_write": _cfg_get("allow_write")}


def _import_mounts():
    if not os.path.isdir(IMPORT_ROOT):
        return []
    return [n for n in sorted(os.listdir(IMPORT_ROOT)) if _is_mount(os.path.join(IMPORT_ROOT, n))]


def _scan_import(kind):
    spec = MEDIA_TYPES[kind]
    items, truncated, seen = [], False, 0
    for name in _import_mounts():
        base = os.path.join(IMPORT_ROOT, name)
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames[:] = [x for x in dirnames
                           if not x.startswith(".") and x.lower() not in _IMPORT_SKIP]
            for fn in filenames:
                seen += 1
                if seen > IMPORT_WALK_CAP:
                    truncated = True
                    break
                if fn.startswith(".") or os.path.splitext(fn)[1].lower() not in spec["exts"]:
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                rel = os.path.relpath(full, base)
                raw = f"{name}:{rel}".encode("utf-8", "surrogateescape")
                items.append({"id": base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="),
                              "name": fn, "rel": rel, "drive": _storage_labels.get(name, name),
                              "size": st.st_size, "mtime": int(st.st_mtime)})
                if len(items) >= IMPORT_SCAN_CAP:
                    truncated = True
                    break
            if truncated:
                break
        if truncated:
            break
    items.sort(key=lambda i: (i["drive"].lower(), i["rel"].lower()))
    return items, truncated


def import_list(kind, refresh=False):
    key = (kind, tuple(_import_mounts()))
    now = time.time()
    with _imp_lock:
        ent = _imp_cache.get(key)
        if ent and not refresh and now - ent[0] < SCAN_TTL_SEC:
            return ent
    items, truncated = _scan_import(kind)
    ent = (now, items, truncated)
    with _imp_lock:
        for k in [k for k in _imp_cache if k[1] != key[1] or k[0] == kind]:
            _imp_cache.pop(k, None)
        _imp_cache[key] = ent
    return ent


def _resolve_import_id(kind, token):
    spec = MEDIA_TYPES.get(kind)
    if not spec or not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8", "surrogateescape")
        name, rel = raw.split(":", 1)
    except (ValueError, TypeError):
        return None
    if not _UUID_RE.match(name) or not rel or rel.startswith("/") or "\x00" in rel:
        return None
    if ".." in rel.split("/"):
        return None
    base = os.path.join(IMPORT_ROOT, name)
    if not _is_mount(base):
        return None
    real_base = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base, rel))
    if not full.startswith(real_base + os.sep) or not os.path.isfile(full):
        return None
    if os.path.splitext(full)[1].lower() not in spec["exts"]:
        return None
    return full


def _media_name_error(name, spec):
    if (not name or len(name.encode("utf-8", "surrogateescape")) > 200 or name.startswith(".")
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        return "invalid file name"
    if os.path.splitext(name)[1].lower() not in spec["exts"]:
        return "extension not allowed for this tab"
    return None


def storage_import_copy(kind, tokens, overwrite):
    spec = MEDIA_TYPES.get(kind)
    if not spec:
        return 400, {"error": "Unknown media type"}, False
    if not _library_online():
        return 409, {"error": _offline_reason()}, False
    if not isinstance(tokens, list) or not tokens:
        return 400, {"error": "Nothing selected"}, False
    if len(tokens) > IMPORT_SELECT_CAP:
        return 400, {"error": f"Select at most {IMPORT_SELECT_CAP} files at a time"}, False
    dest_dir = os.path.join(_cfg_get("library_root"), spec["dir"])
    try:
        os.makedirs(dest_dir, exist_ok=True)
        free = _free_bytes(dest_dir)
    except OSError as exc:
        return 500, {"error": f"Library folder unavailable: {exc}"}, False
    fat = (_mount_fstype(USB_MOUNT) in ("vfat", "msdos")) if _cfg_get("usb_uuid") else False
    pairs, problems, names = [], [], set()
    for token in tokens:
        full = _resolve_import_id(kind, str(token))
        if full is None:
            problems.append("a selected file is no longer available")
            continue
        name = os.path.basename(full)
        err = _media_name_error(name, spec)
        if err:
            problems.append(f"{name}: {err}")
            continue
        if name in names:
            problems.append(f"{name}: duplicate name in the selection")
            continue
        names.add(name)
        try:
            st = os.stat(full)
        except OSError as exc:
            problems.append(f"{name}: {exc}")
            continue
        if fat and st.st_size > FAT_MAX_FILE:
            problems.append(f"{name}: over the 4 GB FAT32 limit")
            continue
        dst = os.path.join(dest_dir, name)
        if os.path.lexists(dst) and not _same_file(dst, st.st_size, st.st_mtime) and not overwrite:
            problems.append(f"{name}: a different file with this name exists (tick Overwrite)")
            continue
        pairs.append((full, dst, st.st_size, st.st_mtime))
    if not pairs:
        return 400, {"error": "Nothing to import", "problems": problems[:20]}, False
    if sum(p[2] for p in pairs) + RESERVE_BYTES > free:
        return 507, {"error": "Not enough free space on the library drive"}, False
    _start_copy_job("import", pairs, lambda: _invalidate_scan(kind))
    return 200, {"ok": True, "started": True, "files": len(pairs), "problems": problems[:20]}, True


POS_FILE = "positions.json"
POS_MAX_ENTRIES = 5000
POS_TOMB_SEC = 30 * 86400
POS_BATCH_MAX = 200
POS_FLUSH_SEC = 60
POS_FILE_MAX = 4 * 1024 * 1024
_POS_KEY_RE = re.compile(r"^(movie|audio):.{1,1024}:\d{1,15}$", re.S)
_pos_lock = threading.Lock()
_pos_state = {"where": None, "data": {}, "dirty": False, "warned": False}


def _pos_where():
    uuid = _cfg_get("usb_uuid")
    if not uuid:
        return None, "Positions stay in each browser while the library is on the SD card."
    if not _library_online():
        return None, _offline_reason() + "; positions stay in each browser until it is back."
    d = _persist_dir("positions")
    if d is None or not os.path.realpath(d).startswith(os.path.realpath(USB_MOUNT) + os.sep):
        return None, "The library drive is not available."
    return (uuid, os.path.join(d, POS_FILE)), None


def _pos_clean(key, e):
    if not isinstance(key, str) or len(key) > 2100 or not _POS_KEY_RE.match(key) or not isinstance(e, dict):
        return None

    def num(v, hi):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < hi

    ts = e.get("ts")
    if not num(ts, 1e13) or ts <= 0:
        return None
    if e.get("del"):
        return {"del": True, "ts": int(ts)}
    out = {"ts": int(ts), "kind": key.split(":", 1)[0]}
    for f in ("t", "d"):
        if not num(e.get(f), 1e7):
            return None
        out[f] = int(e[f])
    for f in ("name", "rel"):
        v = e.get(f, "")
        if not isinstance(v, str) or len(v) > 1024:
            return None
        out[f] = v
    if e.get("played") is True:
        out["played"] = True
    if num(e.get("size"), 1e15):
        out["size"] = int(e["size"])
    if isinstance(e.get("id"), str) and len(e["id"]) <= 2048:
        out["id"] = e["id"]
    return out


def _pos_prune(data):
    now_ms = time.time() * 1000
    live = [k for k, e in data.items() if not e.get("del")]
    if len(live) > POS_MAX_ENTRIES:
        live.sort(key=lambda k: data[k]["ts"])
        for k in live[:len(live) - POS_MAX_ENTRIES]:
            del data[k]
    tombs = sorted((k for k, e in data.items() if e.get("del")), key=lambda k: data[k]["ts"])
    for i, k in enumerate(tombs):
        if now_ms - data[k]["ts"] > POS_TOMB_SEC * 1000 or len(tombs) - i > POS_MAX_ENTRIES:
            del data[k]


def _pos_read_file(path):
    data = {}
    try:
        if os.path.getsize(path) <= POS_FILE_MAX:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                for k, e in raw.items():
                    c = _pos_clean(k, e)
                    if c is not None:
                        data[k] = c
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log_event(f"Positions file {path} unreadable ({exc}); ignoring it", "warn")
    return data


def _pos_load(where):
    if _pos_state["where"] == where:
        return
    data = _pos_read_file(where[1])
    _pos_prune(data)
    _pos_state.update(where=where, data=data, dirty=False, warned=False)


def _pos_merge_file(src, dst):
    a = _pos_read_file(src)
    if not a:
        return
    b = _pos_read_file(dst)
    for k, e in a.items():
        if k not in b or e["ts"] > b[k]["ts"]:
            b[k] = e
    _pos_prune(b)
    try:
        _atomic_write(dst, json.dumps(b, separators=(",", ":")).encode("utf-8"), 0o644)
    except OSError as exc:
        log_event(f"Could not copy resume positions to the new drive: {exc}", "warn")


def _pos_count(data):
    return sum(1 for e in data.values() if not e.get("del"))


def positions_get():
    where, reason = _pos_where()
    if where is None:
        return {"available": False, "reason": reason}
    with _pos_lock:
        _pos_load(where)
        data = dict(_pos_state["data"])
    return {"available": True, "positions": data, "count": _pos_count(data)}


def positions_post(body):
    entries = body.get("positions")
    if not isinstance(entries, dict):
        return 400, {"error": "positions must be an object"}
    if len(entries) > POS_BATCH_MAX:
        return 400, {"error": f"At most {POS_BATCH_MAX} positions per request"}
    where, reason = _pos_where()
    if where is None:
        return 200, {"ok": False, "available": False, "reason": reason}
    accepted = rejected = 0
    with _pos_lock:
        _pos_load(where)
        data = _pos_state["data"]
        for k, e in entries.items():
            c = _pos_clean(k, e)
            if c is None:
                rejected += 1
                continue
            cur = data.get(k)
            if cur is None or c["ts"] > cur["ts"]:
                data[k] = c
                accepted += 1
        if accepted:
            _pos_prune(data)
            _pos_state["dirty"] = True
    return 200, {"ok": True, "available": True, "accepted": accepted, "rejected": rejected}


def _pos_flush():
    with _pos_lock:
        where = _pos_state["where"]
        if not _pos_state["dirty"] or where is None:
            return
        cur, _reason = _pos_where()
        if cur != where:
            return
        blob = json.dumps(_pos_state["data"], separators=(",", ":")).encode("utf-8")
        try:
            _atomic_write(where[1], blob, 0o644)
        except OSError as exc:
            if not _pos_state["warned"]:
                _pos_state["warned"] = True
                log_event(f"Could not save resume positions to the library drive: {exc}", "warn")
            return
        _pos_state["dirty"] = False
        _pos_state["warned"] = False


def _pos_flush_loop():
    while True:
        time.sleep(POS_FLUSH_SEC)
        try:
            _pos_flush()
        except Exception as exc:
            log_event(f"Positions flush error: {exc}", "err")


def _pos_brief():
    where, reason = _pos_where()
    with _pos_lock:
        loaded = where is not None and _pos_state["where"] == where
        count = _pos_count(_pos_state["data"]) if loaded else None
        pending = bool(_pos_state["dirty"])
    return {"available": where is not None, "reason": reason, "count": count, "pending": pending}


POWER_POLL_SEC = 15
SMART_POLL_SEC = 600
NOTIFY_REPEAT_SEC = 3600
_THROTTLE_BITS = {0: "under-voltage", 1: "CPU frequency capped", 2: "throttled", 3: "soft temperature limit"}
_power_state = {"available": None, "raw": None, "now": [], "boot": [], "ts": 0}
_smart_cache = {}
_alerts = {}
_alerts_lock = threading.Lock()
_notify_state = {"last_error": None, "sent": 0, "hb_ok": None, "last_sent": {}}
_notify_q = deque(maxlen=50)
_notify_event = threading.Event()


def _fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _read_throttled():
    if not shutil.which("vcgencmd"):
        return None
    try:
        r = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"throttled=(0x[0-9a-fA-F]+)", r.stdout or "")
    return int(m.group(1), 16) if m else None


def _power_poll():
    v = _read_throttled()
    if v is None:
        _power_state.update(available=False, raw=None, now=[], boot=[], ts=int(time.time()))
        return
    now = [t for bit, t in _THROTTLE_BITS.items() if v & (1 << bit)]
    boot = [t for bit, t in _THROTTLE_BITS.items() if v & (1 << (bit + 16))]
    _power_state.update(available=True, raw=hex(v), now=now, boot=boot, ts=int(time.time()))


def _power_snapshot():
    return dict(_power_state)


def _disk_of(dev):
    name = os.path.basename(os.path.realpath(dev))
    parent = os.path.basename(os.path.dirname(os.path.realpath(os.path.join("/sys/class/block", name))))
    if parent != "block" and os.path.exists(os.path.join("/sys/class/block", parent)):
        return parent
    return name


def _smart_read(disk):
    if not shutil.which("smartctl"):
        return {"disk": disk, "available": False, "reason": "smartctl is not installed (apt install smartmontools)"}
    last = "no answer"
    for extra in ([], ["-d", "sat"]):
        try:
            r = subprocess.run(["smartctl", "-j", "-i", "-H", "-A"] + extra + ["/dev/" + disk],
                               capture_output=True, text=True, timeout=40)
            d = json.loads(r.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            last = str(exc)[:120]
            continue
        if not isinstance(d, dict):
            continue
        nv = d.get("nvme_smart_health_information_log") or {}
        if "smart_status" not in d and "temperature" not in d and not nv:
            msgs = [m.get("string", "") for m in ((d.get("smartctl") or {}).get("messages") or []) if isinstance(m, dict)]
            last = (msgs[0] if msgs else "no SMART data")[:120]
            continue
        out = {"disk": disk, "available": True, "model": str(d.get("model_name") or "")[:60],
               "passed": (d.get("smart_status") or {}).get("passed"),
               "temp_c": (d.get("temperature") or {}).get("current"),
               "hours": (d.get("power_on_time") or {}).get("hours"),
               "reallocated": None, "pending": None, "media_errors": None, "wear_pct": None,
               "ts": int(time.time())}
        for a in ((d.get("ata_smart_attributes") or {}).get("table") or []):
            try:
                aid, raw = int(a.get("id")), int((a.get("raw") or {}).get("value") or 0)
            except (TypeError, ValueError, AttributeError):
                continue
            if aid == 5:
                out["reallocated"] = raw
            elif aid == 197:
                out["pending"] = raw
            elif aid == 198:
                out["media_errors"] = raw
        if nv:
            out["media_errors"] = nv.get("media_errors")
            out["wear_pct"] = nv.get("percentage_used")
        return out
    return {"disk": disk, "available": False, "reason": f"not available through this USB adapter ({last})"}


def _watched_disks():
    out = {}
    mounts = []
    if _cfg_get("usb_uuid"):
        mounts.append(("library", USB_MOUNT))
    mounts += [("import", os.path.join(IMPORT_ROOT, n)) for n in _import_mounts()]
    for role, mp in mounts:
        info = _mount_info(mp)
        if info and info[2].startswith("/dev/"):
            out.setdefault(_disk_of(info[2]), role)
    return out


def _smart_poll():
    watched = _watched_disks()
    for disk, role in watched.items():
        r = _smart_read(disk)
        r["role"] = role
        _smart_cache[disk] = r
    for disk in [k for k in _smart_cache if k not in watched]:
        _smart_cache.pop(disk, None)


def _smart_snapshot():
    return [dict(v) for v in list(_smart_cache.values())]


def _space_alerts(found):
    GB = 1024 ** 3
    lib_dev = None
    if _library_online():
        try:
            root = _cfg_get("library_root")
            st = os.statvfs(root)
            lib_dev = os.stat(root).st_dev
            free, total = st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize
            if total:
                msg = f"{_fmt_bytes(free)} free of {_fmt_bytes(total)}"
                if free < max(total * 0.02, 1 * GB):
                    found["space-lib"] = ("err", "The library drive is almost full: " + msg)
                elif free < max(total * 0.10, 5 * GB):
                    found["space-lib"] = ("warn", "The library drive is getting full: " + msg)
        except OSError:
            pass
    try:
        st = os.statvfs("/")
        free, total = st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize
        if total and free < total * 0.10 and os.stat("/").st_dev != lib_dev:
            found["space-sd"] = ("warn", f"The SD card is low on space: {_fmt_bytes(free)} free "
                                         "(swap and the system journal can fill it)")
    except OSError:
        pass


def _compute_alerts():
    found = {}
    p = _power_state
    if p.get("available"):
        if "under-voltage" in p["now"]:
            found["power-now"] = ("err", "Under-voltage now: the power supply cannot keep up "
                                         "(use a stronger supply / a powered USB hub for the SSD)")
        elif "under-voltage" in p["boot"]:
            found["power-boot"] = ("warn", "The power dipped since the last boot (under-voltage). "
                                           "Use a stronger supply or a powered USB hub for the SSD.")
        others = [x for x in p["now"] if x != "under-voltage"]
        if others:
            found["throttle-now"] = ("warn", "The Pi is " + ", ".join(others) + " (heat or power)")
    f = _lib_fault_info()
    if f["fault"]:
        found["drive-fault"] = ("err", "Library drive error: " + f["fault"]
                                + ("; auto-remount stopped" if f["gave_up"] else "; reconnecting"))
    elif _cfg_get("usb_uuid") and not _library_online():
        found["drive-offline"] = ("warn", _offline_reason())
    for s in list(_smart_cache.values()):
        if not s.get("available"):
            continue
        name = f"The {s.get('role', 'USB')} drive ({s['disk']})"
        if s.get("passed") is False:
            found["smart-" + s["disk"]] = ("err", name + " reports a SMART health FAILURE: back it up and replace it")
            continue
        probs = []
        if s.get("reallocated"):
            probs.append(f"{s['reallocated']} reallocated sectors")
        if s.get("pending"):
            probs.append(f"{s['pending']} pending sectors")
        if s.get("media_errors"):
            probs.append(f"{s['media_errors']} media errors")
        if (s.get("wear_pct") or 0) >= 90:
            probs.append(f"{s['wear_pct']}% worn out")
        if (s.get("temp_c") or 0) >= 60:
            probs.append(f"{s['temp_c']} C hot")
        if probs:
            found["smart-" + s["disk"]] = ("warn", name + ": " + ", ".join(probs))
    _space_alerts(found)
    return found


def _update_alerts():
    found = _compute_alerts()
    now = int(time.time())
    with _alerts_lock:
        for aid, (level, text) in found.items():
            cur = _alerts.get(aid)
            if cur is None or cur["level"] != level:
                _alerts[aid] = {"id": aid, "level": level, "text": text, "since": now}
                log_event("Alert: " + text, "err" if level == "err" else "warn")
                notify(("Problem: " if level == "err" else "Warning: ") + text, level, key=aid + ":" + level)
            else:
                cur["text"] = text
        for aid in [a for a in _alerts if a not in found]:
            old = _alerts.pop(aid)
            log_event("Resolved: " + old["text"], "ok")
            if old["level"] == "err":
                notify("Resolved: " + old["text"], "info", key=aid + ":ok")


def alerts_list():
    with _alerts_lock:
        items = [dict(a) for a in _alerts.values()]
    items.sort(key=lambda a: (a["level"] != "err", a["since"]))
    return items


def _health_loop():
    time.sleep(30)
    last_smart = 0.0
    while True:
        try:
            _power_poll()
            if time.time() - last_smart >= SMART_POLL_SEC:
                last_smart = time.time()
                _smart_poll()
            _update_alerts()
        except Exception as exc:
            log_event(f"Health check error: {exc}", "err")
        time.sleep(POWER_POLL_SEC)


_NOTIFY_RANK = {"info": 0, "warn": 1, "err": 2}
_NOTIFY_MIN = {"all": 0, "warn": 1, "err": 2}


def notify(text, level="info", key=None):
    url = _cfg_get("notify_url")
    if not url or _NOTIFY_RANK.get(level, 0) < _NOTIFY_MIN.get(_cfg_get("notify_level"), 0):
        return
    now = time.time()
    if key:
        last = _notify_state["last_sent"].get(key)
        if last and now - last < NOTIFY_REPEAT_SEC:
            return
        _notify_state["last_sent"][key] = now
    _notify_q.append((url, text, level))
    _notify_event.set()


def _ntfy_send(url, text, level):
    title = f"Pibrary on {socket.gethostname()}".encode("ascii", "replace").decode("ascii")
    req = urllib.request.Request(url, data=str(text).encode("utf-8"), method="POST", headers={
        "Title": title,
        "Priority": {"err": "high", "warn": "default"}.get(level, "low"),
        "Tags": {"err": "rotating_light", "warn": "warning"}.get(level, "information_source"),
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read(256)
            return 200 <= r.status < 300, None if 200 <= r.status < 300 else f"HTTP {r.status}"
    except Exception as exc:
        return False, str(exc)[:200]


def _notify_loop():
    while True:
        _notify_event.wait()
        _notify_event.clear()
        while True:
            try:
                url, text, level = _notify_q.popleft()
            except IndexError:
                break
            ok, err = _ntfy_send(url, text, level)
            if ok:
                _notify_state["sent"] += 1
                _notify_state["last_error"] = None
            elif _notify_state["last_error"] != err:
                _notify_state["last_error"] = err
                log_event(f"Notification failed: {err}", "warn")


def _heartbeat_loop():
    time.sleep(30)
    while True:
        url = _cfg_get("heartbeat_url")
        if url and _pibrary_responsive():
            err = None
            try:
                with urllib.request.urlopen(url, timeout=15) as r:
                    r.read(256)
                    ok = 200 <= r.status < 300
                    if not ok:
                        err = f"HTTP {r.status}"
            except Exception as exc:
                ok, err = False, str(exc)[:200]
            if ok != _notify_state["hb_ok"]:
                log_event("Heartbeat ping OK" if ok else f"Heartbeat ping failed: {err}", "ok" if ok else "warn")
            _notify_state["hb_ok"] = ok
        elif not url:
            _notify_state["hb_ok"] = None
        time.sleep(max(1, int(_cfg_get("heartbeat_min"))) * 60)


KEEP_SEC = 120
PORT_KEEP_SEC = 180
_keep = {}
_keep_lock = threading.Lock()


def _keep_arm(kind, seconds, text, data):
    with _keep_lock:
        old = _keep.get(kind)
        if old is not None:
            data = old["data"]
        _keep[kind] = {"deadline": time.time() + seconds, "text": text, "data": data}
    log_event(f"{text}: confirm with Keep within {seconds // 60} min {seconds % 60}s or it is undone", "warn")


def keep_list():
    now = time.time()
    with _keep_lock:
        return [{"kind": k, "text": v["text"], "remaining": max(0, int(v["deadline"] - now)),
                 "needs_password": k in ("auth", "password")} for k, v in _keep.items()]


def _keep_revert(kind, data, why):
    if kind == "auth":
        ok, err = _cfg_apply_internal(data)
        if ok:
            with _sessions_lock:
                _sessions.clear()
    elif kind == "password":
        try:
            if data.get("old"):
                _atomic_write(_pass_path(), (data["old"] + "\n").encode("ascii"), 0o600)
            else:
                try:
                    os.unlink(_pass_path())
                except FileNotFoundError:
                    pass
            ok, err = True, None
        except OSError as exc:
            ok, err = False, str(exc)
    elif kind == "port":
        ok, err = _cfg_apply_internal({"port": data["old"], "revert_port": 0, "revert_deadline": 0})
        if ok:
            _schedule_restart()
    else:
        return
    if ok:
        log_event(f"Undone ({why}): {kind} change reverted", "warn")
        notify(f"A {kind} change was undone ({why})", "warn")
    else:
        log_event(f"Could not undo the {kind} change: {err}", "err")


def keep_confirm(kind, password, undo=False):
    with _keep_lock:
        ent = _keep.get(kind)
    if ent is None:
        return 404, {"error": "Nothing is waiting for confirmation"}
    if undo:
        with _keep_lock:
            _keep.pop(kind, None)
        _keep_revert(kind, ent["data"], "undone by hand")
        return 200, {"ok": True, "undone": True}
    if kind in ("auth", "password") and not _verify_login(password or ""):
        return 403, {"error": "That is not the current password; the change is undone when the timer runs out"}
    with _keep_lock:
        _keep.pop(kind, None)
    if kind == "port":
        _cfg_apply_internal({"revert_port": 0, "revert_deadline": 0})
    log_event(f"Kept the {kind} change", "ok")
    return 200, {"ok": True, "kept": True}


def _keep_loop():
    while True:
        time.sleep(2)
        now = time.time()
        with _keep_lock:
            due = [(k, v) for k, v in _keep.items() if v["deadline"] <= now]
            for k, _v in due:
                _keep.pop(k, None)
        for k, v in due:
            _keep_revert(k, v["data"], "not confirmed in time")


_BACKUP_SKIP = ("revert_port", "revert_deadline")
DRIVE_BACKUP_NAME = "config-backup.json"
PROBE_MOUNT = os.environ.get("PIBRARY_PROBE_MOUNT", "/mnt/pibrary-probe")
_found_backups = {}


def _json_safe_cfg(cfg):
    return {k: cfg[k] for k in _NORMALIZERS if k not in _BACKUP_SKIP and k in cfg}


def config_backup_data(include_password=False):
    with _cfg_lock:
        cfg = dict(_cfg)
    data = {"kind": "pibrary-config", "app": APP_NAME, "version": VERSION,
            "date": datetime.now().isoformat(timespec="seconds"), "hostname": socket.gethostname(),
            "config": _json_safe_cfg(cfg)}
    if include_password and cfg.get("auth_enabled"):
        h = _read_pass_hash()
        if h:
            data["password_hash"] = h
    return data


def _drive_config_copy(cfg):
    if not cfg.get("usb_uuid") or not _library_online():
        return
    d = os.path.join(cfg["library_root"], ".pibrary")
    if not os.path.realpath(d).startswith(os.path.realpath(USB_MOUNT) + os.sep):
        return
    data = {"kind": "pibrary-config", "app": APP_NAME, "version": VERSION,
            "date": datetime.now().isoformat(timespec="seconds"), "hostname": socket.gethostname(),
            "config": _json_safe_cfg(cfg)}
    _atomic_write(os.path.join(d, DRIVE_BACKUP_NAME), json.dumps(data, indent=1).encode("utf-8"), 0o644)


def _restore_plan(data, restore_storage, restore_password):
    if not isinstance(data, dict) or data.get("kind") != "pibrary-config" or not isinstance(data.get("config"), dict):
        raise ValueError("This is not a Pibrary config backup")
    with _cfg_lock:
        new = dict(_cfg)
    changes, problems = [], []
    for k, v in data["config"].items():
        if k not in _NORMALIZERS or k in _BACKUP_SKIP:
            continue
        if k in ("usb_uuid", "sd_root") and not restore_storage:
            continue
        try:
            nv = _NORMALIZERS[k](v if isinstance(v, (list, tuple)) else ("" if v is None else str(v).lower()
                                  if isinstance(v, bool) else str(v)))
        except (ValueError, TypeError) as exc:
            problems.append(f"{k}: {exc}")
            continue
        if nv != new.get(k):
            changes.append({"key": k, "from": new.get(k), "to": nv})
            new[k] = nv
    for k in ("allow_write", "allow_update", "auto_import"):
        if new.get(k) and not new.get("auth_enabled"):
            new[k] = False
    if new.get("usb_uuid") and restore_storage:
        new["library_root"] = os.path.join(USB_MOUNT, USB_SUBDIR)
    pw = None
    if restore_password:
        h = str(data.get("password_hash") or "")
        if h.startswith("scrypt$") and len(h) < 400 and "\n" not in h:
            pw = h
        elif h:
            problems.append("password: not a valid hash in the backup")
    return new, changes, problems, pw


def config_restore(body):
    source = str(body.get("source") or "file")
    if source == "drive":
        data = _found_backups.get(str(body.get("uuid") or ""))
        if data is None:
            return 404, {"error": "That backup is no longer available; search the USB drives again"}, False
    else:
        data = body.get("data")
    try:
        new, changes, problems, pw = _restore_plan(data, bool(body.get("restore_storage")),
                                                   bool(body.get("restore_password")))
    except ValueError as exc:
        return 400, {"error": str(exc)}, False
    info = {"version": data.get("version"), "date": data.get("date"), "hostname": data.get("hostname"),
            "has_password": bool(data.get("password_hash"))}
    if body.get("preview"):
        return 200, {"ok": True, "preview": True, "changes": changes, "problems": problems, "from": info}, False
    if str(body.get("confirm") or "") != "RESTORE":
        return 400, {"error": "Type RESTORE to confirm"}, False
    if _mig_running():
        return 409, {"error": "A storage job is running; try again when it finishes"}, False
    if new.get("auth_enabled") and not (pw or _password_set() or _root_backend_available()):
        return 409, {"error": "The backup turns login on, but there would be no password; tick Restore password"
                              " or set a password first"}, False
    turned_on = bool(new.get("auth_enabled")) and not _cfg_get("auth_enabled")
    with _cfg_lock:
        old = dict(_cfg)
        try:
            save_config(new)
        except OSError as exc:
            return 500, {"error": f"Cannot write {CONFIG_PATH}: {exc}"}, False
        _cfg.update(new)
    if pw:
        try:
            _atomic_write(_pass_path(), (pw + "\n").encode("ascii"), 0o600)
            _note_sd_write("password")
        except OSError as exc:
            problems.append(f"password: {exc}")
    if new["library_root"] != old["library_root"] or new["extra_roots"] != old["extra_roots"]:
        with _scan_lock:
            _scan_cache.clear()
        _ensure_media_dirs()
    if old["auth_enabled"] and not new["auth_enabled"]:
        with _sessions_lock:
            _sessions.clear()
    log_event(f"Config restored from a backup ({info['date']}, v{info['version']}): {len(changes)} change(s)"
              + (", password restored" if pw else ""), "warn")
    if turned_on:
        _keep_arm("auth", KEEP_SEC, "Require login was turned on by the restore",
                  {"auth_enabled": False, "allow_write": False, "allow_update": False, "auto_import": False})
    return 200, {"ok": True, "changes": len(changes), "problems": problems,
                 "restart_required": new["port"] != PORT}, turned_on


def find_drive_backups():
    if os.geteuid() != 0:
        return 409, {"error": "Searching drives needs Pibrary running as root"}
    found = []
    _found_backups.clear()
    for d in _detect_usb_drives():
        if _drive_note(d) is not None:
            continue
        mp = d["mountpoint"]
        mounted_here = False
        try:
            if not mp:
                if _is_mount(PROBE_MOUNT):
                    _do_umount(PROBE_MOUNT, lazy=True)
                ok, _err = _do_mount(d, PROBE_MOUNT, ro=True)
                if not ok:
                    continue
                mp, mounted_here = PROBE_MOUNT, True
            path = os.path.join(mp, USB_SUBDIR, ".pibrary", DRIVE_BACKUP_NAME)
            if mp == USB_MOUNT:
                path = os.path.join(_cfg_get("library_root"), ".pibrary", DRIVE_BACKUP_NAME)
            try:
                if os.path.getsize(path) > 256 * 1024:
                    continue
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("kind") == "pibrary-config":
                _found_backups[d["uuid"]] = data
                found.append({"uuid": d["uuid"], "label": d["label"] or d["uuid"], "date": data.get("date"),
                              "version": data.get("version"), "hostname": data.get("hostname")})
        finally:
            if mounted_here:
                _do_umount(PROBE_MOUNT)
                try:
                    os.rmdir(PROBE_MOUNT)
                except OSError:
                    pass
    return 200, {"ok": True, "found": found}


LOG_FILE_MAX = 1024 * 1024
LOG_FILE_KEEP = 5
_logfile = {"seq": 0, "warned": False}


def _log_file_dir():
    if not _cfg_get("log_file") or not _cfg_get("usb_uuid") or not _library_online():
        return None
    d = os.path.join(_cfg_get("library_root"), ".pibrary", "logs")
    if not os.path.realpath(d).startswith(os.path.realpath(USB_MOUNT) + os.sep):
        return None
    return d


def _log_file_flush():
    d = _log_file_dir()
    if d is None:
        return
    with _log_lock:
        entries = [e for e in _log if e["id"] > _logfile["seq"]]
    if not entries:
        return
    path = os.path.join(d, "pibrary.log")
    text = "".join(f"[{e['ts']}] {e['level']} {e['msg']}\n" for e in entries)
    try:
        os.makedirs(d, exist_ok=True)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size and size + len(text) > LOG_FILE_MAX:
            for i in range(LOG_FILE_KEEP - 1, 0, -1):
                src = path if i == 1 else f"{path}.{i - 1}"
                if os.path.exists(src):
                    os.replace(src, f"{path}.{i}")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        _logfile["seq"] = entries[-1]["id"]
        _logfile["warned"] = False
    except OSError as exc:
        if not _logfile["warned"]:
            _logfile["warned"] = True
            log_event(f"Could not write the log file on the library drive: {exc}", "warn")


def _log_file_loop():
    while True:
        time.sleep(10)
        try:
            _log_file_flush()
        except Exception:
            pass


def log_file_text(max_bytes=2 * 1024 * 1024):
    d = os.path.join(_cfg_get("library_root"), ".pibrary", "logs")
    parts = []
    for name in ("pibrary.log.1", "pibrary.log"):
        try:
            with open(os.path.join(d, name), "rb") as fh:
                parts.append(fh.read())
        except OSError:
            pass
    blob = b"".join(parts)
    return blob[-max_bytes:] if blob else None


def system_reboot(confirm):
    if confirm != "REBOOT":
        return 400, {"error": "Type REBOOT to confirm"}
    if not _cfg_get("auth_enabled"):
        return 403, {"error": "Rebooting needs login to be enabled"}
    if os.geteuid() != 0:
        return 409, {"error": "Rebooting needs Pibrary running as root"}
    if _mig_running():
        return 409, {"error": "A storage job is running; wait for it or cancel it first"}
    try:
        _pos_flush()
        log_event("Rebooting the Pi (requested from the web page)", "warn")
        _log_file_flush()
    except Exception:
        pass
    notify("Rebooting the Pi (requested from the web page)", "warn")
    try:
        subprocess.Popen(["systemd-run", "--quiet", "--collect", "--on-active=3", "--unit=pibrary-reboot",
                          "systemctl", "reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        threading.Timer(3, lambda: subprocess.call(["systemctl", "reboot"])).start()
    return 200, {"ok": True}


_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def access_info(client, host):
    try:
        ip = ipaddress.ip_address(str(client).split("%", 1)[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
    except ValueError:
        ip = None
    if ip is None:
        via, warn = "unknown", False
    elif ip.is_loopback:
        via, warn = "this Pi itself", False
    elif ip.version == 4 and ip in _CGNAT:
        via, warn = "Tailscale or another VPN (100.64.0.0/10)", False
    elif ip.is_private or ip.is_link_local:
        via, warn = "the local network or a VPN", False
    else:
        via, warn = "the INTERNET (public address): plain HTTP is not safe here, use a VPN such as Tailscale", True
    return {"client": str(client), "host": str(host or ""), "via": via, "public": warn,
            "host_listed": bool(host) and _host_allowed(host)}


_CSS = r"""@font-face{font-family:"Readex Pro";font-style:normal;font-weight:400;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2")}
@font-face{font-family:"Readex Pro";font-style:normal;font-weight:700;font-display:swap;src:url(data:font/woff2;base64,d09GMgABAAAAAC8EABAAAAAAZgwAAC6kAAE0ewAAAAAAAAAAAAAAAAAAAAAAAAAAGoEAG7JWHIYsBmA/U1RBVEAAg2wRCAr5SN8hATYCJAOHaAuDfAAEIAWEFgcgDAcb1VWjoqz2ppjBcR42Dh6G22YUJZRzqOw/HHBDBvSJr0SENNWA0/FS21vVOrY1VBsiq4rXRpewDA8/JyHOzI9XxI9jP/GS6iy1IzQ5RSsP9fvxO3vf+ypAE5Fk6lEt6nSiVkswnelUEt5JYvsDP7feH2OwDdjYRmyDZcCCkaMWRWzkkHJEhIpK23kqBnaAlacYfWHcWad3Z51eev7vN9cnFeDkziDv0GLeNZOXm7Qza0X0udDf6S/mvuCF5Yn/Qz7vzPvNth7voC2JLabQamoFaUZNQx6iynNpa1RWtFTU2tK2TE/LTNCKMiVDJZoG0SAWxBaxHMO+LJLn2JP8EbNbsPQbKWn1CwV2khK+AQWoZA6bq9Y+pCLaJu6n7NSB2Wz7fSh2Q7RlTcmW7f0EZCbgxP+zabYz3ux78vGGUMrLIfWAVbjlppr9u97R7EQn2Tra1YGkQ+lAYLNyMLfy4wDbCZcAIJ0uL7IDSBWWANDnpelTNenapOc2RdekqMIDufxledAVg5ArkVF4rMqGGkpV+2k6tL6aUoXDKITu9vQJder8r2nT/x6l7zx6UagVLhO1kuJMZqmbT3chFF2rcDlUJOfcaRCKQaIM47Eh5jzy7MterLgiiwyxO99eK/c4Q1NCMA/jBaFpRghhRDDCu67P7RqbC+Y6sAmjAAPeuL0pBNAOzAQKDIQRwswOkSYLIkcHRKcuKO99gvDhLhBLCC0DFOEGAR2MQQmGeyYqIeV6het8D2lfacaFjx+0kojmtmRZciZQvmwuqwHKd0Wt9UCBBsymjNNHm+vBE6jBi4IZ9GthT268mmff7IC4xO68P/lvnonRnw+ZC7OujzKWHyoKd6GeKFodpbp0lYUd7ZXe+NjHo74b6Uj6+dzr+MNhQesSKKw9qVVONaXaePadS1fAf+i/X3iiOReii9Q6v66uG+ullzmNOEzQ1Ynryqbe63U3AnRtaU6HEgjhAbTAieXFe8colB0jeP7FC13w/OdsUkRycnRqEYJEScCmQyhmkkoiJ1TLVSFMVajTqJ1e57+0GbZZkh32SrHfARlGjMpywilO51yQ65oxBTzsnXJg0uEZR9mx1fOLa/wdyv6B4yNujqM4R+QCETf+YzwfSJ7Ew6WDJxRsHFw8fAJCktFuDm/CUcceu2vTEY417vzLtHQsbevkENpwJm/m6PbMjvXWyE3zil+3w9mBYtfIblR0gLZ3XuY9MrJDGOF6esTiNZ4DE83+aZBk5M7YDuTPLbeTh8bg4vWlhhIZSxO5Ng7GZrgheclUFuJYeiHmBdmFTv0NEtX80WkMiAOzcAZTXxPytbU3YjEyPHDYoGxOJP6kzKRffdiox9Nsnh6EtDCg7EXJFILVuCWJTwojMe+5BwuWaXUcBzuh7QpjaggGCfPVrubdUkJS1XFnElxdPs0H5Tw26ngYzCE+p5NZxzgmW81pIirySWoOwzYrfELETuMAHV9kxCk5LEQzirlBc4fhsUefYhq9Rr3vZ7ab5pOqKw7gNC+HzKcSFEVRFJXaT6JGGIoEGZkbNHcYHhUuAX6eotoYbMkcwsXDJyAkqaJnxNCKFSdeAj0DYzHtlRnZAlY2SVIUKDSeS5FiJco/qpxVtVjjQqcdGVxwa0LBxsHFwycgJAnl09QDYVX4ZkVU0cBsc8w1z3wLLLbE0nDZKszACiutsjrcRqsA2Ge/Aw465LBjH51crnGZ5oVBbkdMe1bG02lXieDSwhNKoQ+wJXOAi4dPQEhSRQ/F0IoVJ14CPQMjEzMLK5ukdspKsjEUaC6E8VyKFCvJpVFVhqD8pASSBq7Do0yOAoQQQggf4/hvLdEM+kOavr3ZZLIHc6PqvAf6Nn2aeD07KpmeLNEDMUwrVpx4CfQMjEzMLKxskiYHG4AILkWKlSgf7QlJDcUNmjsMjz36BNSESLOu4Ml3YBb1IDORQ9NY46wmLVq1/WeEFzQQSBCIYG58gD5gAFDa0YAG7as6DpHjAEhCGY+trTxaDHIdGBzKBdgm3wGDltYI8JMireV3OTqG/U347D0neacV8ODurtFZON1YRVZ/Wd4Pd3fGptKG7amzw/kZBwGYoHhiaWqq4mbHvlV2oKbJmTIsCMazanNsF2Un7amf2lmwy9EGixneQOq7wtne7LSn7WCnsSu4Ce3ZEM5Yk/Ky97rxVDBNz1xlDqk5FJ/xj9NLVZjDMSLA0e5ElxrTx2QbnM5XHJXjlZdces/5zmcHwZw97+DKp+F/NGS2ElDUgUVzKWGJVXkmR07LyIuhjLsVQ5oOShu1/mYnLrRQT+iwB+eSQxgkkoCS2YSt0SuNfV/0ThmATQ6sOnoUtLlMUsnwowXfzU2Dtxr6F4ue2lcZaJivkpOmEyNbmF14yTeKtuXbjiBOBrHrZn7bM6ENzlNQKnFEncMm3kuSmzxTH1xaRwMG7xKOLd31YbWHAAFLYMTgVrZzELu2rQU0+Fjn4wdCvZbq09NZuGUrv/l/4djC4b61QtPf6rweyw5LoCZJwoI3orc+L+KbHpXJefkbi2j6Jem2Uj1ajkcaBsRWyQrDLB02ibTc2HH1XW48Phc4H14f9UWwQhBDq1ZIYzaHKdFyXQE3h1oRCNsz3YVG3Tc4bijSGE5902NbUJyvHWePEe3RVLTA9AQKGliwRSIoETiTjVE/vinOr2WofEXGZVMkjmM5n+Doi1+0ZUkm01mPCr32dRVAuEj+sZrNbmCzAotPf6r145dkrbuoAJ/LqDfvm8vm75HG7bCnT2O6dXEC+f+DoUVMBIB2f3xZ4HRS/n6ivdkITMqKAWmcWnsw9pgnR/IHVhmzjn4pQONGpRs3qm/9Ag+BBdpRYNEFI2FL4EfHTiNNNr0cXayGbVbvhFManXVWi/MuaIWihfDgxpMnNCwsPi/eED5I0MjIBCgoAtDR4QUJwhKslU8IISLGJrm/jQgpyWTEkduBQqi4U1MojHQaWyRcBB+R9BdFPJ2NomdAZWQwk40wS4KRTK4U0qTSk93GSpMFK5tecsg07owgV358t0AZlHJQrIIUlfRWRZRq20+NBh4aKdXEIM22TIs2RO301UEvneSaQC8TSTCJWF1KcBgcMISXgDwXLiRQwnwGGoFvUXDw3HgRUJkbP1JUUr87RV3DDSi4AQUsCMCADl8EwWs+SbQEiHjmSRA/gW8keg/FP4xT7554nJVAlN7JUJZ6OtkOgQdwwMMH7mCBDDa8lfIj/gxvmMi0WYMdQ0BGdQ5K8w1UoaWePn0zSBAKaKDPsFwu1RpN1G3YDpre56pbP/LEC38EBQiyqbr16NWn36DpZ5Ttd2AXTu5+a8xDTzyFeDqA0jdyEg5i/xBKz8jgqH4IsLrnjqEvCAMSpo3j4c3+iJjCU8/zu6czjKmabBArVnQwkYyHA0tw8wXOjGNg5vE5mer50udJ1Y06KJiY/0JQeNDAdHFQ36AcB/f+zs46D1nEzWM5CsZ5oNXNcyBAAVEU87rVo7T+QmXs4+aiYgZS1Z3MY+EuI0vcq8TMhY5X6YPFbyfmDra+l2w4GHyNDS5/nZ70dBvIwF390A2+NjDvo+/j3eMx8R7xnvFYwf3d6/DhukawfVbfUAeOf/ztC8j+rqqiCFzfNZTUQvmOWjSjE1PQ/3DmD211zTBfUAEEr9X0VJ9aiQkIPICCGzBAw/0lji8e21v9QrOdcSMYeOYDzhFG8mNmC6gn9wKFJFAym6Sr9CSzn46DMHIMdwOnduijMiaPUrRDFJR+kQ7JfokSIA2GqbbsRyb3h8iu7gqEBK/CR9CiWUuBMQCP4u5jjQiObM/P6v0NpEBxqumJEUgGOdyERB0g6DpFrMOaJYLy57PPsBCocAZlkdW8BgAenrn7J9TMIBwiE7j5yScmzzidUGxSV+y6dB/uTTJ0aS+j3EG50xxgdbro2EeVeOv4N0EFLAD/f85twjqsRyS3V2skUL+o1GZhpa+jwFBuEFMKCsCORhZesTTHgSAAF76sbEWGqBQxE5TwB6QQRH8718CrVhCCrKDjQWggYqh+mqGiTPG1jcKisYJZHJaAQ/oagKEUoq17QGYFsoIwtp4VH37/lv54MvdJ/6MrgPAHpjsG4rz199QT231rnwdeGnPVqOP2+t5mhw3bb4utnnrsiZ2uQWDhePFBRuHHH12QYAxMbCISUjJyIdTCaISLdMoBpz034oNoOnpGZslSpLLLlmOcXHkKlCpXoVK1Go2aNGvR7oQ7TvrZJjvc89B937nrhvdumuyiZ4645Q+3/WSNtT564brdPvnGFJesN2SDXdzn0X9sNAxPeCQERL5oAgSi8sbCx8ElxPMjAZVQCkoRxKrEiaGVIFa8RAZJLKxssqRJl8EkX5FC45VweaRYg1p16rUq0+a8C85AIBkQAP4B4jeIJoCut2DAU4D6Nqi6ASgJUQi3Rq0Hiqqqv4gMXUMAqKCJEpRLJcWl16YjGikCbCIre02N4kh2UtXvxRf9TUY0YXqAQpe2cxXkjKhtRLZMG6GNe9jEO8qntGEDo4xPgUatYLjJbnrGiCHTmnsvrSPeUTRH7wXlPozhcCkqwfIoD7B0dopdSmSyxc9uo5DRFPXGB8FrPTScC/AP4WDe1VFCYhNDI4gs6o5B9BTZ0KLgYLSXBRT44BWnY4hENFhAJZHlH6V6zRkRQAxAW0IUf5WoEFkjiUe8hJu83ESATrS58dFJaExAYrQXNkbxWiJoxa7cWExbRAxHQ8PAQIcDh7PbPQ3mfP1VAp0iFlEYFF9i1oLg4Lk8XlnUPTq7LCUK7dUCuMYPx/l7xphwEDHQ66a+rglW6Ba/y6O0ITWQw7SypK4q8tByqaIj3CmkiiwviASp2z2higRzSjZYVS/aJ+D9yMFMbjmZAC+gnmCIMVrck3bqmc9zGxj9qGdgkC1ygndhZsBtH4F29jerlU+fj2EL9MVEE/CebF/aYf4L9eC5A8aO6VQlSVKjpZAwqeSxEN0ZLBrdaKqTmEqa7qb0BKNQoVx5YEF8vkDemFMws4UNE8Qx6OZUpGydDS6YdNMgln+OSZEFvzDH1UyZAW9GLOby6cbCqGeQZ5xMO7ePyCo142IdPqA08OJyH9Si2lpSMFopr9iX7Pl3C3kF2Me3v2M2HVXGSh9jZOR0nicZU+J1AOLrCcoF/W2mzEiNOeGadGXGAbVbLmR4Pm/bTj1C29CQY4lPTQ4Qv6PsfFULkT86mLKIdmKAXRqjQQQWCSRTM5jyFxut4jb/U493Rc0FV2lcWRnB1pr9cTpkwwdXGNXakqurPirVVanXRiSvurDqw118x7QUp6plgisjMAudutBBNSes1E+xdGkCmoUKDSL5ViVehmfOjP1xMV/RKOmTUXJXuRUAPvpZDSU3yzeCdzIehR13HxLCaihdeVT57B6ind5iid1QbJ15fCA3hHJdFlpmJdMLNvZJW9rcpUxmBdPFcrD1uV5A4oFbfw0UmzXl3EOUb1AZAlx5g5eNh4I0IV1kOx6FE5D0RW1MRpx3w1uYSCmJ1n0yFprHugmiDu8ePJWLaxZpXq0m5DOJ/HKES7sfH+2VrR4WQBCs2ScdjvAih11IXWXM+NN0z74qW1mq9VOaUnIXFaDKm9HRzojzTkUfm09LPQBWb8H56lft5GFmTzKWbFQtJbjC+NOxTX4wrtRzA++FODuTUHhf1Cxnzoe+v/039AtJIbW0Fwj1nhuTy8H4MngPszGOgBV/LksrOGdIWABrdvkxhCTU4Qyx1ecLRR5mk2tYAR3lLxKIafVu7CVUnlgozQH0B9PFa+A2XyiZrq+wxoGcbWSK2caT1cS4beNFTUVRhRe38JtKS3KLi6nnzatxcQgfbSuKfs+O8LbxGDOsggIi3lZYXxhER1rhs7LbOB6VjXYP0GB5cJFuDtvLUdDoBWaUfVU2cz72cu4XZVKAaz9hAEAkWE0bc/RQxd2n+dHzOrx7M8ecJ+s7sm1KCA0QXYE68tr1ooDRID2YvAwS0jjQLKIMHGmxKkzjKgi01c2DLHgTo6fys3Xpha9rzIyISG7VFURD2ogVDMaRdLAaSityIcHyadCICdkO5qMEgrG2opuIFv156YFXayuvc6ESoFzUOVuFzu2NaiC57pVUqp7hN4tbrwweG6hWdB5VofUmKod9V07qEezwWqGRw0JXSdzjT5vbrb7TDDmqTronwcY7eqdoUV1c81TzoL0wP/wq5KFCVcyu1lWV81uXog9d+2gd7bx+OfagX+TU7CRxbKO6MwF2/UyFMdywHzm541yjax2liEpUoMyTo/nEc62TE0kpDtuph4lih4tu2rtA9OuHn0cB0DhelY01eEkoyG+FnnVGMASQ24vdulVZulxJAwIRC1rKdzF6grUM8o8Z8dFIlXzTSY7f4kfLWwCwCHjwUxhDzdI+nvdnOdsneGAIi0KYfiMt5qT2zrXY6lL48JxLRddwkmh6PvLgYtFcYhM7iKuwjqziZI+0VIRXYInsYZYH2Rc2J5CKZu473h1/hQVHW7LEAXhHvZ1o1rqcUsD5aPFORrvXaycdJqoSTNI9nBHiUgyfxpsmbjrT+mHRrQTrcTSPaLBFs3BgryzTH/O03OrrFjyLk3EBrS2NqwDA4EKVn4J1XaZwIUOFxGQB3C6RU+TChupHeJdKg8h/Y22z/Bv+cP8Ff0qqkrsVQjCI7xRsib5uFUUUXzpZUMjide9ewpsHVHrmFxkCw4AKKjZw9tIv5zS8wPPj0QsohifV8wrbAWO6MnZRLqKNY/rsAgAGpsd7jf4qQZjFH4AUQq1+DFH9dOPYpwX2nZE7sFVp9YmmutT3aW8LkgWVyGNR8sloIZFk6eBU7lh3GNmB5FzHqY5q1BEdYV+Oo/TGHHaCs8TnoJxgULRqQ/+6cvh8DVf6x/B8XLEYMGHBzrt14yDxVkzhvjotqojh2gVjjxX5zs4RvM3+ZMgwuHDXcxjPRZJgHVwuAvONTrop1cKsyKQlTQxP2s/uEE3XTZBHQ2Y3bQukoA3EVwzmjMSPmiFzYuDIn/VYgo9w2rPAv4Cg7jy1pd0e4vU3hiPT2x7CFsi9Q+mFVbM0Zgq5VECAKkkhkdEWm3xmLIxQuzIWMNR561lGxgylB11Lm6DVR3/wQzOYPtzbSJtmTTTz/nF6yqyieNIrJ2lJxriQKBY2ekMjB0nDfHYrBnnd2U5v5c7Y2H/AfUpv+NTuTnAdXbrQQIrmgXqMvsiqWxn1ghO8DETtPKISnrvYRgM7ipohZsDLYjx8cX2hcTMtqxiBf0DCODiaSt3k7pVmtjO1yzW4mTLjk8hC/PktY9xFPek4eEedRNGI5jR1snrvliKNpEo3cafSNPxE3UE4+ZFiWjPkKGqaDFgFPEWxB22F04EiaSTmw/U0+kKhQSYdmS6mSSdawVT7tLf/Qmwd05XzhlNkT8qCPMjWFIiqSxRUcdz5j2G+Apl58IQB0Rl7pfnHCWI8T0j8eE9+KwFfC/DNoylDn0sOLVbMcTzPaBxNleoZLspTCq3KYRRWZOsfRaKp9xacIeaQwBcfxHTFl7282hA7ZLkRE+o8n4GghhgJ3XA9u4msHMP/NwIoIwtIIzv6i0sJHx8bTuU8/hoo+lzcAU1PgqYHPF+O+M0xz6BNpy0wz3k9B583sDtgWSsbnKPh1mKROjkiJtregL5iUPEtIRqeXReWS41YM3e55CU/oGFt8KKeyTRFiB9rv6wdFmPt/WEuV1i/PTW8r6RoUGNXjaemq25Xtj9N5oeKTHRNsDU0JMhWmkwPZXYzyel9E9OlpYHgHBWmTFXl5Su7U1KVU/Pyp6hSJ7U55ogT6c8CLXJ5oOVZIl08fy5w2Z2GTiKbMb9z9NXCxOXJC4eCZ9fMdrwqt4/m4ufVzqsJXLZ4GazCZg5qiorUfampEX2lRTM1GVHlwZnqPZV1ynRBmNTCqAxOlsuZSdOTmDKmrruWRks7Oc1K80PhDIrGnLQOGeBGt48W3guXE1ZeXgm2+e2r2+cvWz+F4I4V6IiNY78WlUmIweRAUwQ1vmfJoiW16WpO2sMMJty9Kp0/ruDbjhHe9ABUVnOx80jRLH7ksteKFV9W1wDu5uLR4Tv5ngtxJu4piWFUxMfrPOeW3iE9GQ0f3CqwLlSVcfPw6KrJCKbWwx5JZLyAJVh7v8bl0vTbUzngKlIirj6N5kR9hHKkrBPrg/l0q1TGXsFwi8WGYME3mixakZuphpmsT8k3DKHmkzE8POdoqK4iJqZcp4+pqYjV9b9Guhv8eVmB1Ayuf0P5KhoGSHJFZGCibz0qoX4i1kNZPb5qstOj3IpN/x/qWENNVFxpoi6uokZrWPnpp73aXYHnszdOnEUrN9Po0y4wuyAeWznXotJVtCp0JXINfedMMuHlAsYM/apMwSDdJE+wjO/QmMq7EixV5S9ThdLg49Vkosh3tKU6h/sHxxRiMZZN0sBb/tiy1GV3+TDF3TloSumy79mxWUBfz+Xvkwo2D++xJ3cNmCA4YGTfgOsE4dKRKmbvp6iX3a5dgSPw4NbIrqqGeXhdJ8FVNmHfjErKjHLKnte9Ij1JHhTXXllRv/3WSO/wAvbyefDxfqR/743bYbTBc7jJ0x3XZB/001LOiC+Ad4GLNu/MPXU26pTiuM9KH0M5aJvb3kXplq4mNjW/Hz22FIpN4gsi4dU94/PfTYqw6ouEmrT4Mh5W5RCGmBTiH7fkUGKGPEsX+30u3OBD+LSdRHti30g3J24wBMP3WHW6MNSkEP92eRw55sJKv4Ali+nC+qNSiTDRylNxW14aq38xciwEnrPbYJroiBWUm2yFokhrozG+E5LB7vfKvplAeLmTRH9i36jOsOtCHIFFSBb5SpGnn7DWNb6gcGJkkiKZUh2UKGuDASwvgeyQmqWenUt/Wp+Cy6FzbrON1ebYLodDO6nKVDvI0z2SSMfSebz0R1LJo3QIxaZMNBu7Uh3GronmFHO7ip5ddSrvMVWw8ItQ4LWIRztufZ9dRZ2gAiLWUGuMhfCDrzUbeTo/IzO6Mnvo2VLPjk8B/+kSyah+vu6xVPZYx+eJSyb9LQARJrndqO+wakQFRnOuWKVKFYUlLS5kCqjpjFR5t6L8bXVkRlpMJaPL6tT1t9tSprNU3/N53ylZLOVDPv97VUuPl261cOVCFknXRD0CemxOr9E00R4nLLdYi0UxkXlCvZlbhMUPB+TGIJTAjZvoovqjUikv0cRVsjNe2qrk+utEhCp5mCw9TRnO/9wnb73QgSNN2kxiptHEuZMH8wch6nlCN29yRNMnR6BM/eWNPOduYZmdKbM06RLaUx0JkxqMpuDalyktbKx7x4qXiYIym7GKF18u7PlNLP2tV8hv/k0i+a0JzM/WxuI3zLRzZdo0hchlNg5FsajqdX7aLY8p2jSaGBzkIbJ9UohExI+Vyw6WHBI8dw4CbsZOMpgsr4eIFlVhkRzdkhqCe2MHy+VUYfC/qQ2kcKy+i/BkVeSEz/9dSkjPhp5dOPK2yeluBjN+psFEXoEen7bV+TqOJnr5/IeWuvuD9BRqfIZS7DLrhyJC64V+sumPKTFDkfJ5fAoKgDl//N1rils3HpveY7J22dOYiJWe0Y1daXbU/WNmBq/kC8bz/2Iet+WLWPilBTq4OuU1tl6J8aDv0vT92xWY1lfjS9NYIYYqo5bqoWknVZsMIWmcjsbUwpZcXuKYWDKm4/HTf5SKH6Udlp1ab8YiKWb7KpNRPrCzMaWwWeYV3fp9XoDIO+wPjrHWFNtlT+Ni1Sa9QE/J9KYa3btWvCWf56Zd0wV1DuL4qwmz4+Zljd4mFJOeHZDs2WSh+Kdufx6IBWKTOxTRRRm/pwRxvTWvp+Ao2NY1Hm8M7Cy1nqWMto4XRcpSyQbulsxC+O4GhVD6egoWv25p/3XrrzqWBn6lqSNTi2WwAyv5a3lcXewxIsPKFXQkCmdnW+7wp/sw5vOF3eKPaz6aoqrqolMSSoRRNg1r10cmyZGeGJIXo410FUVeb5+5fCa0rBha8f/AnLI58C82OkMlK9RbhhTKFxK/oOk3Kdoh8jL32m83zkphw5sfSXv7ppdOm7PnFxKM7CRtLcrOqMMWtuKairK2HiC1t9BPN1FhbuM2tfkm83TdhvDk6+yYu6Ks8rrT619klVeeOw4zn3fSkQxQHGrA934Nqy38bUYR9fATUu5zUBUGlqqpfUeKPPO0fn0wc5BfHZwUFsI2XxJGhsaq9W3RbVZF8PkEbC71FZt7L8jvYnDg/mK4ME2ZJJaYQ0IlliSJMjRJIrOGhEjNNrEqi3aMzTlCC/iOxbkMdmxhX5ZxXVMTE2leiP/VWDA/wdBQUWNoSkgwNtVUGBvgtlLDz1hsDF56sahusUC5bNsyiGVnXPqRNFXXQKZ4w+q/LPXjZKM12VmhXBdXrI7OjaX/wkrQWKtXbqHY8pdBMDZrsikse1JK4i8cetCDUQaz8y7bR5AXwSvefOQhG71g15cXn+ubw4khaex/ufZQk6muIw7y1DmoP0Pqrs2hGfqKts86A1SMvTtuVV7ZHANTwqIeD2KM4Zj+5fveW4ok6oULEjYzv9vIrHzL1FdotdUmo6G+LQH44YUCk0GYpyHQ8pVFAa7131gH76zg2xjml0zLI50pSyiKKY6Lroiz6dpb9JbZTPw+VtDpLwxW0B4Gc58XHIGT5Km1Sy77pGEaQIwyt4YbC2KEsY0L846kFv7Ai4jLqlYm6qqVcVkRvJGC7v7vjWphijrGWNiqsQwGHRwIpA4OB9MOLaUGLjlIVVHTHX7+joxAaobD38+RDtejvh85cc1odopEUePjosq1VkNrmyFJU8A36YTZKi7eEGjmpNY7d2Q2MF/vDGaufcNkXJnHou26CtewymSlNDsiSuxMVqhVNoXYGRUhyU5ShpbTTonEp2lBT8WiJ9AMHI8D8vRWg7Mu2jsYtN6ZZY7XV+II3mM+5OR7yeG/JymU0cb4EFFN1x5T4KE82I0Vv2PJUqkSsv8BX0JvgPfBO/Wzxk8cynuIzWjLzF7S5hGyJZSX/Qj4a225tkMR7xcQV15J8plQeWM3OW3//Wr4xpNh9nMpUumz/AM2kXyX+BOFKY+pO1/m799Gm3b2590MzmSEGZtrhhOepuzCtFhxfopGw/2pWGr9zurDKyZGJXoYY8WRhgSVcFwiS5RGWk72nUCiLPclzwCt56AId6L0DS9xQAQncWIDo5fJ3TOT9U8tM8QeqxX9amcyo+Rg2cdlNusZohTKZbLvUYrfYTL5KGUNqZVIHPQll/kS+2HIk3urWWr9R0LktvhE6f0N8ZIIg04prDKwpIb0wnStOD9ZI7xHme5L6aQQl1N8OwF9a2TR7RGYihOPSUU/CcWPZCIE9kuvej3IuEXeLqCwbnEZb7cI2FMPL4fy/+cQerG9MdZtVi22n9A7U4UVP5IKP/Js5j3sSbMJfdgebZhC7J3Y40dZ6WPpk756x+qxvPp9C40S85VM+8B/k9b4LlmTy1IbXRp1frQyND3X+NW4MiT6IBSPyURPsfQRWHibnclaAmmMtynh41hhhqK9qULTelyX5voRdtwVPEsRCFOf8Sv8LFUoSHkGG13eA0hXRljegMZjIEaTNyWfRZje4jPnU0eeJn9aDHYwTJPblvWOMAANHSNzO0auLe7N7WUuxk/P0M7ecb3gPodGtq2lfrTB+urAn4XrqGQhqO8uylkEEd/NfDLziFRFhSd7C3uBdXRC0tSfZ8/qfibd5mblxeceq6nOHc2Lg+Kj4+zukeqa3BHyu0HzokHttegkFjMgQQKFqhPdom5J9zdqKEx3FVb6cZol0zBcJCPamGIjEWwUY0oUksFyG5SB9hqKv21M++fePkmZHztiOB1RSWyC1HDKk93ibultFoD9+ETx9CXOKatWTAfZ8cuDF0+EhbsYhEsC5uyDF6MeLOCS8c8uN4aSmbfBtP3V/DDSz34PmpgP9hyP+fWSgzXnwGE4Qtv1xGvnz3nxHUeRziPQE5Qf34lI+5HceK8uLPvJHhszPGwL2lQOm/nLZjjTA66hnBlhLpdqML09/dii3jOGBvtUWV6GotlkFEwyFhVEhAuOMpm+LGTxV5U+kSuSm0PFmREKXklihlMdxnz3gP9b0MKF0TERfUT6C46OnK1Iiq/qiMwu3xDZWhO7qtTAr7ZZawUmhc7rcibfsDOTYcKTkmiIMCFEiKNcnUthhgTbpKxhMJpsBxesqlAb/73tHx6ZUapIVDlZCTGXptg86+h+P/xNoXzGoX2tDkPs2m3nsaldWkt5vC2zNZNRUjyrXcZ+d0UqNDDzOOm6pfOktXpnVmwFCz7H/BIXnqlRjI9NjHCVagwrR4cXKROfpUTNgtweQdoGh7/v5u+zgn6Yj78qDg1NLg2xK9IoCcKJGbkDr45RODUBhEhlRQbDSrfYA4JCE7P40/wUOQEW8czU8QfsTKZgApXQ1lyZFWykmeyREqk+U7yen1X09k8C+TXdGKBODZElKpWhjtIQmOGbPBBRUho5kJISOSBkrE5O6Y8orQkRqhuzLsaliSyIiWKv6/Sk8PSBLxRVrhgCtS0zgJrVSvXtilfWPDf5abJiq2QOh6wqNg4Bh10HiY2tlNntgbhYBFIdNieg3piadbpGo0HfIHfWqM4R6PX8cWpDYmODTp+oSg9VpKvVlJquUIVlKpRK8GRmhmYmcHP0xPCqH95OFDxkc3HcyO+Kei5wvV5jcd/hhS8BOz00SSK1yEI4bJMoFJQkschlUqvkDnH5zv+PRHqzztd33a/y4P7bDWmnNi3fBBmXZ66auZI3Y9UMSEixd5lNXakOJjDtX5EgJ65x7fMeNGiDkHp83NMHRetUTk6pG1jeWzqxrGBNZi0E1sUUqDTOyEhNDsyYgnPegM581U1lSYkzt7i84oestJLi7MzEN34fSP4BpI9+lI+kAH/Shx2bcrKLysbl5J0rLs4bX1IM8djiubHi9N7qytCooG9mkgkvFson6pMJZdEKZ8xXtTeRPaCOsLZPKBaGX6EdE4z7WTTbgbuRxsLvJuzMYOPWVMOxsGTKSa6ZQ16PXXXwRCLRFFvWGJlkrgyZ1VnwcQM96MisIGZQ1xAxMZBRablXzTGRjGepThLbSE6IajpWztAw/95lYtADXDfNlYzx7OMG11bXV64rxB22/fB43XRZ94MVngjhxQJ4odvb+7kX+D9P/3M6zFZXVLoKKsuriguKKioKx4PkfN/XvnhM7y+nUcuW0IJay2iB5YO0JfT+Miq1/J07Tw8sGwCdofdV78sHPa96oMo7cUrWfnPWvq/kvh+LYYd3byXltzlhSsY+c8Z+0Gn6/uz7FNv/Z795dObymTD5MrGzAPMCfxFLjme0jLeVp/pWF7449+1mnG9CYDMSz8z8Dn6ouv3qw2xbOOArv2vpe9iyYV2gA9lIA9vQwTVhbHo4zS9k2y2/8DXkJeiSh9xfNqZ5Gb/TnHV/ClvGRpbeHnFZ1HaVzBkVKXOmKsPCUpRSZ1SEPCdFpawgZh0JCjqSRSS2XwySnBIfVTlUcmdElMxpV4WpU1TvRVRFnXJi9hG6ZEFgvXOXgsSnoblR8qNI8FUk/kHMf0KVXKMd3ookVzPh77YQmogvl+9FwGz+ts5auXc2bDeFWhtZk6ElfcG8btfjrbhgcSYD/s5mNZCZLPcGNrvBncV0a2DZiQYfXwORaCASDKAdT5TWByd5EMJF43BRcQ6NL67hYQPeRxSeg3cb84P0zvLUclj2CWvzu/wT3qvOn+BlrEuX6cLJAsa4hxYsnO+lI2LuaYlsh4h3ilHQaLEb4HzzU0pk240WWPmGZy9PUXgbtL8TT6/Om1ZNXWAKhr/Xcfea2dyoM1zePiuXbd7LTfdt9yWTuD9xMP9PmT0hoAPn40Yu1VuSIkniVZ8rsd53oERITxDAUjODfCYEGeoySgVc1y9myb9MASAwAANVXQyLXQgny4sfpg2Cu+cBPxBwv+UjWChJDvMbYwUqLviXigOGdBeCyQRlKvU0CMpeFhYY1cSrAxYmKD0NIkIWFvwvJLxHwwvgeyvcdm8ZQCro4REIgY6SibWjbkj0DQaUhSnG2C7AEW/zsNvBoecbDlvmRSLWIGoG4QkqXDhKuhQcW1YEFr3bpA95bV6CgpKaIGoOjI6o1AE1JbVA1ByY2yQMLUZjJwFZ8RYGxJGO7uMzEHKGAzR54ypck6u55MwCGOOR5ezHLzLO0x42rmXcHhRMKDNAHBAznTTLnsXZizn2meugeQ6Z74gFDjxeKFE++bn8yHpGiDyeUUVg3UcAwVlyDbyUvL/VnAztPnu1uLb4hR8fM2sYYgYZBnHGVpsvQPFNq2sYHhP8TVqV70Dhmc314h1Hk1FDSjFw+Ao63+yEct6/BNYv80a5AAj4Kynlsj9Zo8D1Vlf8xa9cS6+k19Ib6e1z+Q7Mv/P09Tjy9MPpP31w45b3X2DIep9iul92A64ClDdnT5KXtrIao3VXc0nXYlrbK5ygrIr0LC/1r75O2EB8BFKQwRXfaAIOfydlcb9Cz3IRgYip8GQs71Y9y0tnrk6zl1mN2cYX/YQEu+TL4cleMlfmy6bRAYavxUQsoz9Xfniyl8xN5iOB6IwG2TmIjYN93QRxIEkJfD+JWAD+7JB5cZlzoIUXSkGWvWSuzFcAFrLoooPsJXMJYu7ZiqqM9JTKRVo3ymDT6aAa0xewuB5wOCD92wrKXQXKmbvGS3a0lQdoqfSidwmSHzYAVj+qY6gpiEY8VHZyQl+u4WRcpJWHhCmNiF4nTlZklfuR5Qw78tOyy4tDJ8j62KQYL6sTdSg4oBrUu7LDwgnB/vlOdIxk7H6DxdMD/5Th/ute24r64n72jSOxIY/XLq7dpol2LwujqGZfis/6CLMtz/qbwOzInb6FQy8e+RVfcEX5nbRNceUE66olOismYfMbiSGjE2Koj81dC61AhQAx88fOBbXoI0H7f4Cb2yvA+2fVLgA+/3XX9rX9y7719cUABAYKIMDfiRCPBK7//aBBXK+rH7UQ9SjYNllPXdrjnD1Iuu1w0OA8dF4HOFm17/EG6fHqKGUDbsixVcR9Qaw4w+pZFu27hNTmk+TyLs3iZVDwqfd7Ev/Ow+5/Mjb3Ve7Vi7HK2YX2Lfswbae9uMDWcILNdaaP1YXMZePguThzMkkpmYXeNZTZxZxECeEAIpXunG0CK5NDbuw+WgzSFuYooucME1+D/deNAxbYAhDpx8mlzz1vkboWPfP4tU8iuMfzrnQqEqTWcYf8AqoWIh1/9ItsRsbSXkXHXrcZ5Ju5mF1HVDVzeehN4d8lyM3AaiJ2pRTNJmqC4CzHCxcttQQpwcty1DRipxMnNsJMJU49NmcqOQKdp4VZP9E4J4yGdvBPPIiB8WEBsodH0u9stcS0Y6mCtPRS5uLmEN/+ILRpMMXCz9IxyHbkhLCcE12HyLNBZHcRZZAwA7CxjRAeWoY5uFyH/TfH/hUYsiBy3irhigo/0XBMcHcfkfiX9JwjOjhQ9Qtp47D9fQj5h0ehKIlWenQyqxJShaBOotBklDFMzRJaPUGG8bW+tPX0JYCILUmnwCPH7Jp0B68yVZJGBJhA+KF8Fc/Ct/BSvNnzIH+QSl3WFhmUby4wTpt2BhTSmgMB/in+K13sKay8ruu3mckNUmN1m1egP4JiX38UTxf6u1EZ64/GCPR3RwtjD4ygRA6HALRHZn8EGHE1o8g9hYg/n5hCr0GjCZpVqVCpFYuKglIUlkyVyoSld6VIKes0CYdmDYlVO7ykxUrURlalBo+1WEWk0mrV2K1oofdQhSqycJtiIUo0qBOqABdPkRa2d1uiRpV6oZo1eeNd22IbTDdY7RxSCjGeqhEjlZ07G8WAfueXs527ogTOhj5Yle1QjyWdvRx2Gk7GLSZoFFDBjR0sKlIvxgz4gZUr0qZWKzcAKams6a/ztf9PmwMA) format("woff2")}
:root{
  --bg:#0d1117; --surface:#161e2e; --surface2:#1e2a3f;
  --border:#2e4060; --border2:#3a5278;
  --amber:#ffd040;--amber-dim:#6b4800;
  --green:#00ffb0; --green-dim:#005538;
  --red:#ff3d5a; --red-dim:#6b0e20;
  --blue:#22d4ff; --blue-dim:#083a58;
  --text:#ffffff; --muted:#aab8cc;
  --sans:"Readex Pro",Arial,Helvetica,sans-serif;
  --mono:ui-monospace,Menlo,Consolas,"DejaVu Sans Mono",monospace;
  --fs-xs:.66rem;--fs-sm:.72rem;--fs-base:.8rem;--fs-md:.9rem;--fs-lg:1rem;--fs-logo:1.21rem;
  --inputbg:#0a1020; --logbg:#070b10; --popbg:#1a2438; --hdr1:#0f1a2e; --hdr2:#161e2e;
}
html[data-theme="light"]{
  --bg:#f3f5f9; --surface:#ffffff; --surface2:#e6ebf3; --border:#c3cddd; --border2:#a6b3c9;
  --amber:#8a5a00; --amber-dim:#ecd48f; --green:#007a55; --green-dim:#b4e5d2;
  --red:#b3122f; --red-dim:#f0b8c2; --blue:#0a6a8f; --blue-dim:#bde0ef;
  --text:#14202e; --muted:#4a5a72; --inputbg:#ffffff; --logbg:#eef1f6; --popbg:#ffffff;
  --hdr1:#e3e9f3; --hdr2:#f3f6fb;
}
html[data-theme="light"] .logo{text-shadow:none}
html[data-theme="light"] video{background:#000}
html[data-size="s"]{font-size:14px}
html[data-size="l"]{font-size:19px}
html[data-density="compact"] .card{padding:.45rem .7rem;gap:.35rem}
html[data-density="compact"] .item{padding:.12rem .3rem}
html[data-density="compact"] .entry+.entry{padding-top:.4rem;margin-top:.1rem}
html[data-density="compact"] .wrap{padding:.5rem}

button,input,select{font-family:var(--sans)}
textarea,pre,code{font-family:var(--mono)!important}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:var(--fs-md);
  line-height:1.5;min-height:100vh;padding-bottom:2.5rem}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
header{background:linear-gradient(90deg,var(--hdr1),var(--hdr2) 50%,var(--hdr1));
  border-bottom:2px solid var(--amber);padding:.3rem 1rem;display:flex;align-items:center;
  justify-content:space-between;gap:.5rem;position:sticky;top:0;z-index:100;
  box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
.hdr-left{display:flex;flex-direction:column;min-width:0}
.hdr-right{display:flex;flex-direction:row;align-items:center;gap:.5rem;flex-shrink:0;white-space:nowrap}
.logo{font-size:var(--fs-logo);font-weight:700;color:var(--amber);letter-spacing:.08em;line-height:1.2;
  text-shadow:0 0 10px rgba(255,208,64,.9),0 0 30px rgba(255,208,64,.5)}
.logo-sub{font-size:var(--fs-xs);letter-spacing:.22em;text-transform:uppercase;color:var(--amber);margin-top:.1rem}
.hdr-meta{font-size:var(--fs-xs);letter-spacing:.04em;color:var(--muted)}
#logout-btn{display:none;margin-top:0;font-size:var(--fs-xs);padding:.2rem .6rem}
.wrap{max-width:1000px;margin:0 auto;padding:1rem}
.layout{display:flex;align-items:flex-start;--navw:7rem;--navgap:.8rem;--gutter:1rem}
.layout[data-side=left]{padding-left:calc(var(--navw) + var(--navgap))}
.layout[data-side=right]{padding-right:calc(var(--navw) + var(--navgap))}
/* the tab rail is pinned to the margin; --navtop is the header height, set from JS */
nav#tabs{display:flex;flex-direction:column;gap:.3rem;width:var(--navw);position:fixed;z-index:90;
  top:var(--navtop,4.6rem);max-height:calc(100vh - var(--navtop,4.6rem) - .5rem);overflow-y:auto}
.layout[data-side=left] nav#tabs{left:max(var(--gutter),calc((100% - 1000px) / 2 + var(--gutter)))}
.layout[data-side=right] nav#tabs{right:max(var(--gutter),calc((100% - 1000px) / 2 + var(--gutter)))}
body.has-mini nav#tabs{max-height:calc(100vh - var(--navtop,4.6rem) - 8.5rem)}
.content{flex:1;min-width:0;display:flex;flex-direction:column;gap:.55rem}
button.tab{width:100%;background:var(--surface);color:var(--text);border:1px solid var(--border2);
  border-radius:6px;padding:.55rem .7rem;cursor:pointer;font-size:var(--fs-md);text-align:left}
button.tab.active{background:var(--surface2);color:var(--amber);border-color:var(--amber-dim)}
.layout[data-side=left] button.tab.active{border-left:4px solid var(--amber)}
.layout[data-side=right] button.tab.active{border-right:4px solid var(--amber);text-align:right}
.layout[data-side=right] button.tab{text-align:right}
.panel{display:none;flex-direction:column;gap:.55rem}
.panel.active{display:flex}
.hdr{font-weight:700;font-size:var(--fs-sm);letter-spacing:.24em;text-transform:uppercase;
  margin:1.2rem 0 .1rem;padding-bottom:.25rem;border-bottom:1px solid var(--border)}
.card{background:var(--surface);border:1px solid var(--border2);border-radius:6px;
  padding:.8rem 1rem;display:flex;flex-direction:column;gap:.55rem}
.row{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
.small{font-size:var(--fs-base)}
.muted{color:var(--muted)}
button{background:var(--surface2);color:var(--text);border:1px solid var(--border2);
  border-radius:4px;padding:.35rem .8rem;cursor:pointer;font-family:var(--sans);font-size:var(--fs-md)}
button:hover:not(:disabled){border-color:var(--amber)}
button:disabled{opacity:.5;cursor:default}
.fld{display:flex;flex-direction:column;gap:.2rem}
.fld.chk{flex-direction:row;align-items:center;gap:.5rem}
input[type=text],input[type=number],input[type=password],textarea,select{background:var(--inputbg);
  color:var(--text);border:1px solid var(--border2);border-radius:4px;padding:.4rem .55rem;
  font-family:var(--sans);font-size:var(--fs-md);outline:none;width:100%}
select{width:auto}
input[type=file]{color:var(--text);font-size:var(--fs-md);max-width:100%}
input:focus,textarea:focus,select:focus{border-color:var(--amber)}
.kv{display:grid;grid-template-columns:minmax(8rem,14rem) 1fr;gap:.25rem .8rem}
.kv .k{color:var(--muted)}
.kv .v{word-break:break-word}
.banner{background:var(--amber-dim);border:1px solid var(--amber);border-radius:4px;
  padding:.4rem .7rem;font-size:var(--fs-base)}
.prog{height:.5rem;background:var(--inputbg);border:1px solid var(--border2);border-radius:4px;overflow:hidden}
.bar{height:100%;width:0;background:var(--green)}
.item{display:flex;gap:.6rem;align-items:baseline;padding:.35rem .4rem;
  border-bottom:1px solid var(--border);cursor:pointer}
.item:hover{background:var(--surface2)}
.item.playing{color:var(--amber)}
.item .nm{flex:1;min-width:0;word-break:break-all}
.item .sz,.item .dt{color:var(--muted);white-space:nowrap;font-size:var(--fs-base)}
.warnb{font-size:var(--fs-xs);color:var(--amber);border:1px solid var(--amber-dim);
  border-radius:3px;padding:0 .3rem;white-space:nowrap}
.phdr{display:flex;gap:.5rem;align-items:center;margin-bottom:.25rem}
.selfrow{display:flex;gap:.6rem;align-items:center;padding:.35rem .4rem;border-bottom:1px solid var(--border);flex-wrap:wrap}
.selfrow .nm{flex:1;min-width:10rem;word-break:break-all}
.selfrow .sz,.selfrow .dt{color:var(--muted);white-space:nowrap;font-size:var(--fs-base)}
.selfrow button{padding:.15rem .6rem;font-size:var(--fs-base)}
.improw{display:flex;gap:.5rem;align-items:baseline;padding:.25rem .4rem;border-bottom:1px solid var(--border)}
.improw .nm{flex:1;min-width:0;word-break:break-all}
.improw .sz{color:var(--muted);font-size:var(--fs-base);white-space:nowrap}
.warnb.ok{color:var(--green);border-color:var(--green-dim)}
.ptitle{flex:1;min-width:0;font-size:var(--fs-md);color:var(--amber);word-break:break-all}
video{width:100%;max-height:60vh;background:#000;border-radius:4px}
audio{width:100%}
#log{background:var(--logbg);border:1px solid var(--border2);border-radius:6px;
  padding:.6rem .8rem;white-space:pre-wrap;font-size:var(--fs-base);max-height:350px;overflow:auto}
.log-ok{color:var(--green)}
.log-err{color:var(--red)}
.log-warn{color:var(--amber)}
#popup-overlay{display:none;position:fixed;inset:0;z-index:1200;align-items:center;
  justify-content:center;background:rgba(0,0,0,.55)}
#popup-overlay.open{display:flex}
.popup-box{background:var(--popbg);border:1px solid var(--border2);border-radius:8px;
  padding:1rem 1.6rem;font-size:var(--fs-md);line-height:1.4;box-shadow:0 8px 40px rgba(0,0,0,.8);
  max-width:80vw;text-align:center}
.popup-ok{border-color:var(--green-dim);color:var(--green)}
.popup-warn{border-color:var(--amber-dim);color:var(--amber)}
.popup-err{border-color:var(--red-dim);color:var(--red)}
.popup-info{border-color:var(--blue-dim);color:var(--blue)}
#login-screen{display:none;position:fixed;inset:0;z-index:9999;align-items:center;
  justify-content:center;background:rgba(5,8,14,.88);backdrop-filter:blur(3px)}
#login-screen.open{display:flex}
#login-card{background:var(--surface);border:1px solid var(--border2);border-radius:8px;
  padding:1.4rem 1.6rem;min-width:260px;max-width:90vw;box-shadow:0 8px 40px rgba(0,0,0,.8);
  text-align:center}
#login-card h2{color:var(--amber);font-size:var(--fs-lg);letter-spacing:.06em;margin-bottom:1rem}
#login-card form{display:flex;flex-direction:column;gap:.6rem}
#login-card button[type=submit]{color:var(--amber);border-color:var(--amber-dim)}
#login-err{min-height:1.1rem;font-size:var(--fs-base);color:var(--red);margin-top:.2rem}
@media (max-width:600px){
  .wrap{padding:.5rem}
  .layout{--navw:3.9rem;--navgap:.4rem;--gutter:.5rem}
  button.tab{padding:.5rem .2rem;font-size:var(--fs-sm);text-align:center !important;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .kv{grid-template-columns:1fr}
  .item .dt{display:none}
}
.entry{display:flex;gap:.7rem;align-items:flex-start;padding:.2rem 0}
.entry+.entry{border-top:1px solid var(--border);padding-top:.7rem;margin-top:.3rem}
.num{min-width:1.7rem;height:1.7rem;border-radius:50%;background:var(--amber-dim);color:var(--amber);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:var(--fs-base);flex-shrink:0}
.ebody{flex:1;min-width:0;display:flex;flex-direction:column;gap:.45rem}
.etitle{font-weight:700}
.tag{font-size:var(--fs-xs);font-weight:400;border:1px solid var(--border2);border-radius:3px;padding:0 .35rem;margin-left:.4rem;white-space:nowrap}
.tag.now{color:var(--blue);border-color:var(--blue-dim)}
.tag.save{color:var(--amber);border-color:var(--amber-dim)}
.lock{color:var(--amber);font-size:var(--fs-base)}
.entry.locked .ebody>*:not(.etitle):not(.lock){opacity:.45;pointer-events:none}
button.primary{color:var(--amber);border-color:var(--amber-dim);font-weight:700}
.lnkbtn{background:var(--surface2);color:var(--text);border:1px solid var(--border2);border-radius:4px;padding:.1rem .5rem;font-size:var(--fs-sm);text-decoration:none;cursor:pointer;white-space:nowrap}
.lnkbtn:hover{border-color:var(--amber)}
.smallbtn{font-size:var(--fs-xs);padding:.2rem .6rem;margin-top:.3rem}
.viewpanel{position:fixed;top:4.2rem;right:.6rem;z-index:150;background:var(--surface);border:1px solid var(--border2);border-radius:8px;padding:.8rem 1rem;display:flex;flex-direction:column;gap:.5rem;box-shadow:0 8px 30px rgba(0,0,0,.5);min-width:15rem}
.viewpanel label{display:flex;justify-content:space-between;align-items:center;gap:.8rem}
.ext{display:none}
html[data-mview="grid"] .listbox{display:grid;grid-template-columns:repeat(auto-fill,minmax(10.5rem,1fr));gap:.5rem}
html[data-mview="grid"] .listbox>.item{flex-direction:column;align-items:flex-start;gap:.3rem;border:1px solid var(--border2);border-radius:6px;padding:.6rem;background:var(--surface2)}
html[data-mview="grid"] .listbox .ext{display:flex;align-items:center;justify-content:center;width:100%;height:3.2rem;border-radius:4px;background:var(--amber-dim);color:var(--amber);font-weight:700;letter-spacing:.1em}
html[data-mview="grid"] .listbox>.item .nm{font-size:var(--fs-base)}
#toasts{position:fixed;bottom:1rem;right:1rem;display:flex;flex-direction:column;gap:.4rem;z-index:1300}
.toast{background:var(--popbg);border:1px solid var(--border2);border-radius:6px;padding:.5rem .9rem;font-size:var(--fs-md);box-shadow:0 4px 18px rgba(0,0,0,.5);max-width:85vw}
.toast.ok{border-color:var(--green-dim);color:var(--green)}
.toast.warn{border-color:var(--amber-dim);color:var(--amber)}
.toast.info{border-color:var(--blue-dim);color:var(--blue)}
#logbar{align-items:center}
#logbar .fld.chk{gap:.25rem}
@media (max-width:600px){.viewpanel{left:.6rem;right:.6rem;top:3.8rem}}
.crumbs{display:flex;flex-wrap:wrap;align-items:center;gap:.2rem;font-size:var(--fs-md)}
.crumb{background:none;border:1px solid transparent;border-radius:4px;padding:.1rem .4rem;color:var(--blue);font-size:var(--fs-md)}
button.crumb:hover:not(:disabled){border-color:var(--border2)}
.crumb.cur{color:var(--amber);font-weight:700}
.crumbsep{color:var(--muted)}
.item.folder .nm{font-weight:700}
html[data-mview="grid"] .listbox>.item.folder .ext{background:var(--blue-dim);color:var(--blue)}
.gsearch{position:relative;flex:1;max-width:24rem;min-width:0}
.gsearch input{width:100%}
.gsres{position:absolute;top:calc(100% + .3rem);left:0;right:0;z-index:160;background:var(--popbg);border:1px solid var(--border2);border-radius:6px;box-shadow:0 8px 30px rgba(0,0,0,.5);max-height:65vh;overflow:auto;padding:.3rem 0}
.gshdr{font-size:var(--fs-xs);letter-spacing:.18em;text-transform:uppercase;color:var(--muted);padding:.35rem .7rem .15rem}
.gsitem{display:flex;flex-direction:column;padding:.3rem .7rem;cursor:pointer}
.gsitem:hover,.gsitem.sel{background:var(--surface2)}
.gsitem .gn{word-break:break-all}
.gsitem .gp{font-size:var(--fs-sm);color:var(--muted);word-break:break-all}
.gsnone{padding:.4rem .7rem;font-size:var(--fs-base);color:var(--muted)}
@media (max-width:600px){.logo-sub,.hdr-meta{display:none}.gsres{position:fixed;left:.5rem;right:.5rem;top:3.6rem}}
.mini{position:fixed;left:0;right:0;bottom:0;z-index:140;background:var(--surface);border-top:2px solid var(--amber-dim);box-shadow:0 -6px 24px rgba(0,0,0,.45);padding:.4rem .8rem;display:flex;flex-direction:column;gap:.3rem}
.mini-row{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;max-width:1000px;width:100%;margin:0 auto}
.mini-row button{padding:.2rem .6rem;font-size:var(--fs-base)}
.mini audio{max-width:1000px;width:100%;margin:0 auto;height:2.2rem}
.mp-title{flex:1;min-width:8rem;color:var(--amber);font-size:var(--fs-md);cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mp-title:hover{text-decoration:underline}
body.has-mini{padding-bottom:8.5rem}
body.has-mini #toasts{bottom:7.5rem}
.queuepanel{position:fixed;right:.6rem;bottom:7.2rem;z-index:150;width:min(30rem,calc(100vw - 1.2rem));max-height:55vh;display:flex;flex-direction:column;gap:.4rem;background:var(--surface);border:1px solid var(--border2);border-radius:8px;padding:.6rem .8rem;box-shadow:0 8px 30px rgba(0,0,0,.5)}
.qplist{overflow:auto;min-height:0}
.qrow{display:flex;gap:.35rem;align-items:center;padding:.2rem .1rem;border-bottom:1px solid var(--border)}
.qrow .qn{flex:1;min-width:0;cursor:pointer;word-break:break-all;font-size:var(--fs-base)}
.qrow.cur .qn{color:var(--amber);font-weight:700}
.qrow button{padding:.05rem .45rem;font-size:var(--fs-sm)}
.cont{display:flex;flex-direction:column;gap:.25rem}
.cont .crow{display:flex;gap:.5rem;align-items:center;padding:.2rem .4rem;border:1px solid var(--border);border-radius:4px}
.cont .crow .nm{flex:1;min-width:0;word-break:break-all;font-size:var(--fs-base)}
.cont .crow .pp{color:var(--muted);font-size:var(--fs-sm);white-space:nowrap}
.cont .crow button{padding:.1rem .5rem;font-size:var(--fs-sm)}
@media (max-width:600px){#mp-shuffle,#mp-repeat{display:none}.queuepanel{bottom:8.5rem}}
.edbar button{padding:.2rem .6rem;font-size:var(--fs-base)}
.edbar>.row{gap:.35rem}
input.selcb{flex-shrink:0;width:1rem;height:1rem;margin:0 .2rem 0 0;cursor:pointer}
html[data-mview="grid"] .listbox>.item input.selcb{position:absolute}
html[data-mview="grid"] .listbox>.item{position:relative}
.trashbox{border-color:var(--amber-dim)}
.pickov{position:fixed;inset:0;z-index:1250;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center}
.pickbox{background:var(--popbg);border:1px solid var(--border2);border-radius:8px;padding:.8rem 1rem;width:min(32rem,calc(100vw - 1.5rem));max-height:75vh;display:flex;flex-direction:column;gap:.5rem;box-shadow:0 8px 40px rgba(0,0,0,.8)}
.pklist{overflow:auto;min-height:0}
.pkrow{padding:.35rem .5rem;border-bottom:1px solid var(--border);cursor:pointer;word-break:break-all;font-size:var(--fs-md)}
.pkrow:hover{background:var(--surface2);color:var(--amber)}
/* v0.12: phone layout. Below 600px the tab rail becomes a bar fixed at the bottom. */
button.tab .ti{display:none}
header{padding-top:calc(.3rem + env(safe-area-inset-top, 0px))}
header .smallbtn{margin-top:0}
.viewpanel{top:var(--navtop,3rem)}
/* v0.12.1: search bar at the top of the content; fold (Show / Hide) headings */
.gsbar{max-width:none;width:100%;flex:none}
.gsbar .gsres{position:absolute;top:calc(100% + .3rem);left:0;right:0}
.hdr.fold{display:flex;align-items:center;gap:.5rem;cursor:pointer;user-select:none}
.hdr.fold:hover{color:var(--amber)}
.hdr .foldbtn,.hdr .foldextra{font-size:var(--fs-xs);letter-spacing:normal;text-transform:none;font-weight:400;
  padding:.1rem .6rem;min-height:0}
.hdr .foldbtn{margin-left:auto}
.foldnote{font-size:var(--fs-xs);letter-spacing:normal;text-transform:none;font-weight:400;color:var(--amber)}
.ratesel{padding:.15rem .3rem;font-size:var(--fs-base)}
.ext img.art{width:100%;height:100%;object-fit:cover;border-radius:4px;display:block}
html[data-mview="grid"] .listbox>.item .ext:has(img.art){height:7rem;overflow:hidden;background:none}
.fthumb{width:1.6rem;height:1.6rem;object-fit:cover;border-radius:3px;flex-shrink:0;align-self:center}
html[data-mview="grid"] .fthumb{display:none}
.rthumb{width:1.6rem;height:1.6rem;object-fit:cover;border-radius:3px;flex-shrink:0;align-self:center}
.mp-art{width:2.2rem;height:2.2rem;object-fit:cover;border-radius:3px;flex-shrink:0}
.sleepbtn.on{color:var(--amber);border-color:var(--amber-dim)}
.alerts{display:flex;flex-direction:column;gap:.35rem}
.alerts:empty{display:none}
.alerts .banner{display:flex;gap:.6rem;align-items:center}
.alerts .banner span{flex:1}
.banner-err{background:var(--red-dim);border-color:var(--red)}
.recent{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:.8rem}
.recent .rcol{display:flex;flex-direction:column;gap:.15rem;min-width:0}
.recent .rhead{display:flex;align-items:center;gap:.5rem;font-weight:700;font-size:var(--fs-base)}
.recent .rhead .lnkbtn{margin-left:auto}
.recent .rrow{display:flex;gap:.5rem;align-items:baseline;padding:.25rem .3rem;border-bottom:1px solid var(--border);cursor:pointer}
.recent .rrow:hover{background:var(--surface2);color:var(--amber)}
.recent .rrow .nm{flex:1;min-width:0;word-break:break-all;font-size:var(--fs-base)}
.recent .rrow .dt,.recent .rrow .sz{color:var(--muted);font-size:var(--fs-sm);white-space:nowrap}
@media (max-width:600px){
  .layout[data-side]{padding-left:0;padding-right:0}
  .layout[data-side] nav#tabs{top:auto;bottom:0;left:0;right:0;width:auto;max-height:none;overflow:visible;
    flex-direction:row;gap:0;z-index:145;background:var(--surface);border-top:2px solid var(--amber-dim);
    box-shadow:0 -4px 16px rgba(0,0,0,.35);padding:0 0 env(safe-area-inset-bottom, 0px)}
  .layout[data-side] button.tab{flex:1;min-width:0;width:auto;border:0;border-radius:0;background:transparent;
    padding:.35rem .1rem .3rem;font-size:var(--fs-xs);display:flex;flex-direction:column;align-items:center;gap:.1rem}
  .layout[data-side] button.tab .ti{display:block;line-height:0}
  .layout[data-side] button.tab .tl{max-width:100%;overflow:hidden;text-overflow:ellipsis}
  .layout[data-side] button.tab.active{border:0;border-top:3px solid var(--amber);background:var(--surface2);color:var(--amber)}
  body{padding-bottom:calc(4rem + env(safe-area-inset-bottom, 0px))}
  body.has-mini{padding-bottom:calc(13rem + env(safe-area-inset-bottom, 0px))}
  .mini{bottom:calc(3.35rem + env(safe-area-inset-bottom, 0px))}
  #toasts{bottom:calc(4.2rem + env(safe-area-inset-bottom, 0px))}
  body.has-mini #toasts{bottom:calc(12rem + env(safe-area-inset-bottom, 0px))}
  .queuepanel{bottom:calc(12rem + env(safe-area-inset-bottom, 0px))}
  button{min-height:2.2rem}
  .lnkbtn{padding:.35rem .6rem;font-size:var(--fs-base)}
  html:not([data-mview="grid"]) .listbox>.item{flex-wrap:wrap;padding:.55rem .4rem;row-gap:.35rem}
  html:not([data-mview="grid"]) .listbox>.item .nm{flex:1 1 55%}
  input.selcb{width:1.3rem;height:1.3rem}
}
"""


_JS = r"""// Fetch wrapper: a 401 from any /api/ call except login means the session is
// missing or expired; reload so the boot probe shows the login screen.
const _rawFetch = window.fetch.bind(window);
window.fetch = async function(input, init) {
  const resp = await _rawFetch(input, init);
  const url = typeof input === 'string' ? input : ((input && input.url) || '');
  if (resp.status === 401 && url.startsWith('/api/') && url !== '/api/login') {
    _onAuthLost();
  }
  return resp;
};

let _authLostReloading = false;
const _AUTH_MSG_KEY = 'pibrary_auth_msg';
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
  if (btn) btn.disabled = true;
  if (err) err.textContent = '';
  try {
    const r = await _rawFetch('/api/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pw ? pw.value : ''}),
    });
    const data = await r.json();
    if (r.ok && data.ok) {
      hideLoginScreen();
      _bootAfterLogin();
    } else if (err) {
      err.textContent = (data && data.error) || 'Login failed.';
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
  } catch (e) {}
  location.reload();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  return {ok: r.ok, status: r.status, data: data};
}

let _popupTimer = null;
function popup(msg, level) {
  if (!level || level === 'ok' || level === 'info') { toast(msg, level || 'info'); return; }
  const ov = document.getElementById('popup-overlay');
  const box = document.getElementById('popup-box');
  box.className = 'popup-box popup-' + level;
  box.textContent = msg;
  ov.classList.add('open');
  if (_popupTimer) clearTimeout(_popupTimer);
  _popupTimer = setTimeout(function() { ov.classList.remove('open'); }, 2600);
}

function fmtBytes(n) {
  if (n === null || n === undefined) return 'n/a';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(i ? 1 : 0) + ' ' + u[i];
}
function fmtDur(s) {
  if (s === null || s === undefined) return 'n/a';
  s = Math.floor(s);
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return (d ? d + 'd ' : '') + (d || h ? h + 'h ' : '') + m + 'm ' + (s % 60) + 's';
}
function fmtDate(ts) {
  try { return new Date(ts * 1000).toISOString().slice(0, 10); } catch (e) { return ''; }
}

// ---- tab registry. Config is appended in code so it is always last.
const TAB_DEFS = [
  {id: 'status', label: 'Status'},
  {id: 'movie', label: 'Movies', media: true},
  {id: 'audio', label: 'Audio', media: true},
  {id: 'pdf', label: 'PDF', media: true},
];
const ALL_TABS = TAB_DEFS.concat([{id: 'config', label: 'Config'}]);
const RENDER_CAP = 500;
const _M = {};
const _I = {};
let _curTab = 'status';
let _appStarted = false;
let _authOn = false;

function applySide(side) {
  document.getElementById('layout').dataset.side = (side === 'right') ? 'right' : 'left';
}

function buildMediaPanel(kind) {
  const sec = document.createElement('section');
  sec.id = 'tab-' + kind;
  sec.className = 'panel';
  sec.innerHTML =
    '<div class="card">' +
    '<div class="row"><input type="file" id="file-' + kind + '" multiple>' +
    '<button id="upbtn-' + kind + '">Upload</button>' +
    '<button id="upcancel-' + kind + '" disabled>Cancel</button>' +
    '<button id="impbtn-' + kind + '">Import from USB</button></div>' +
    '<div class="prog"><div class="bar" id="upbar-' + kind + '"></div></div>' +
    '<div class="small" id="upmsg-' + kind + '"></div>' +
    '<div class="small muted" id="upinfo-' + kind + '"></div></div>' +
    '<div class="card" id="imp-' + kind + '" style="display:none">' +
    '<div class="small muted" id="impinfo-' + kind + '"></div>' +
    '<div class="row"><button id="impall-' + kind + '">Select all</button>' +
    '<button id="impnone-' + kind + '">Clear</button>' +
    '<label class="fld chk"><input type="checkbox" id="impover-' + kind + '">' +
    '<span>Overwrite different files</span></label>' +
    '<button id="impgo-' + kind + '">Import selected</button>' +
    '<button id="impcancel-' + kind + '" disabled>Cancel</button>' +
    '<button id="impref-' + kind + '">Rescan</button></div>' +
    '<div class="prog"><div class="bar" id="impbar-' + kind + '"></div></div>' +
    '<div class="small" id="impmsg-' + kind + '"></div>' +
    '<div class="small muted" id="impnote-' + kind + '"></div>' +
    '<div id="implist-' + kind + '"></div></div>' +
    '<div class="card">' +
    '<div class="row"><input type="text" id="flt-' + kind + '" placeholder="Filter" style="max-width:14rem">' +
    '<select id="sort-' + kind + '"><option value="name">Name</option>' +
    '<option value="size">Size</option><option value="date">Date modified</option>' +
    '<option value="added">Recently added</option></select>' +
    '<button id="dir-' + kind + '" title="Reverse the order">Asc</button>' +
    '<button id="fmode-' + kind + '" title="Switch between folders and one flat list">Folders</button>' +
    '<select id="pf-' + kind + '" title="Show by play state"><option value="all">All</option>' +
    '<option value="unplayed">Unplayed</option><option value="progress">In progress</option>' +
    '<option value="played">Played</option></select>' +
    '<button id="ref-' + kind + '">Refresh</button>' +
    '<span class="small muted" id="cnt-' + kind + '"></span></div>' +
    '<div class="row small edbar" id="ed-' + kind + '" style="display:none">' +
    '<button id="sel-' + kind + '" title="Choose files and folders to rename, move or delete">Select</button>' +
    '<button id="mkd-' + kind + '">New folder</button>' +
    '<span class="row" id="eds-' + kind + '" style="display:none">' +
    '<span id="edn-' + kind + '">0 selected</span>' +
    '<button id="eda-' + kind + '" title="Select everything shown">All</button>' +
    '<button id="edc-' + kind + '">None</button>' +
    '<button id="edr-' + kind + '">Rename</button>' +
    '<button id="edm-' + kind + '">Move to...</button>' +
    '<button id="edd-' + kind + '">Delete</button>' +
    '<button id="edp-' + kind + '" title="Mark the selected files as played">Mark played</button>' +
    '<button id="edu-' + kind + '" title="Remove the played marks / resume positions of the selected files">Mark unplayed</button></span>' +
    '<span style="flex:1"></span><button id="dpb-' + kind + '" title="Find identical files">Duplicates</button>' +
    '<button id="trb-' + kind + '">Trash</button></div>' +
    '<div class="card trashbox" id="trash-' + kind + '" style="display:none"></div>' +
    '<div class="card trashbox" id="dupes-' + kind + '" style="display:none">' +
    '<div class="row"><span class="etitle">Duplicates</span><span class="small muted">identical content, any name' +
    '</span><span style="flex:1"></span><button id="dps-' + kind + '">Search</button>' +
    '<button id="dpc-' + kind + '">Close</button></div>' +
    '<div class="prog"><div class="bar" id="dpbar-' + kind + '"></div></div>' +
    '<div class="small" id="dpmsg-' + kind + '"></div>' +
    '<div id="dplist-' + kind + '"></div></div>' +
    '<div class="prog"><div class="bar" id="fbar-' + kind + '"></div></div>' +
    '<div class="small muted" id="ftxt-' + kind + '"></div>' +
    '<div id="player-' + kind + '"></div>' +
    '<div class="cont" id="cont-' + kind + '"></div>' +
    '<div class="crumbs" id="crumbs-' + kind + '"></div>' +
    '<div class="listbox" id="list-' + kind + '"></div></div>';
  _M[kind] = {items: [], view: [], meta: null, playing: null, loading: null,
              dir: lsGet('cwd.' + kind) || '', flat: lsGet('fmode.' + kind) === 'flat',
              selMode: false, sel: new Set(), shown: []};
  sec.querySelector('#sel-' + kind).addEventListener('click', function() {
    const st = _M[kind];
    st.selMode = !st.selMode;
    st.sel.clear();
    renderList(kind);
  });
  sec.querySelector('#mkd-' + kind).addEventListener('click', function() { edMkdir(kind); });
  sec.querySelector('#eda-' + kind).addEventListener('click', function() {
    _M[kind].shown.forEach(function(k) { _M[kind].sel.add(k); });
    renderList(kind);
  });
  sec.querySelector('#edc-' + kind).addEventListener('click', function() { _M[kind].sel.clear(); renderList(kind); });
  sec.querySelector('#edr-' + kind).addEventListener('click', function() { edRename(kind); });
  sec.querySelector('#edm-' + kind).addEventListener('click', function() { edMove(kind); });
  sec.querySelector('#edd-' + kind).addEventListener('click', function() { edDelete(kind); });
  sec.querySelector('#edp-' + kind).addEventListener('click', function() { edMarkPlayed(kind, true); });
  sec.querySelector('#edu-' + kind).addEventListener('click', function() { edMarkPlayed(kind, false); });
  const svPf = lsGet('pf.' + kind);
  if (svPf) sec.querySelector('#pf-' + kind).value = svPf;
  sec.querySelector('#pf-' + kind).addEventListener('change', function() {
    lsSet('pf.' + kind, this.value);
    renderList(kind);
  });
  sec.querySelector('#trb-' + kind).addEventListener('click', function() { toggleTrash(kind); });
  sec.querySelector('#dpb-' + kind).addEventListener('click', function() {
    const box = $('dupes-' + kind);
    const open = box.style.display === 'none';
    box.style.display = open ? '' : 'none';
    if (open) loadDupes(kind);
  });
  sec.querySelector('#dpc-' + kind).addEventListener('click', function() { $('dupes-' + kind).style.display = 'none'; });
  sec.querySelector('#dps-' + kind).addEventListener('click', function() { dupesScan(kind); });
  sec.querySelector('#trash-' + kind).addEventListener('click', function(ev) {
    const b = ev.target.closest('[data-act]');
    if (b) trashAct(kind, b.dataset.act, b.dataset.id);
  });
  sec.querySelector('#upbtn-' + kind).addEventListener('click', function() { startUpload(kind); });
  sec.querySelector('#upcancel-' + kind).addEventListener('click', cancelUpload);
  sec.querySelector('#ref-' + kind).addEventListener('click', function() { loadList(kind, true); });
  _I[kind] = {items: [], sel: new Set(), meta: null};
  sec.querySelector('#impbtn-' + kind).addEventListener('click', function() { toggleImport(kind); });
  sec.querySelector('#impref-' + kind).addEventListener('click', function() { loadImport(kind, true); });
  sec.querySelector('#impall-' + kind).addEventListener('click', function() { impSelectAll(kind, true); });
  sec.querySelector('#impnone-' + kind).addEventListener('click', function() { impSelectAll(kind, false); });
  sec.querySelector('#impgo-' + kind).addEventListener('click', function() { importSelected(kind); });
  sec.querySelector('#impcancel-' + kind).addEventListener('click', storCancel);
  sec.querySelector('#flt-' + kind).addEventListener('input', function() {
    lsSet('flt.' + kind, this.value);
    renderList(kind);
  });
  sec.querySelector('#sort-' + kind).addEventListener('change', function() {
    lsSet('sort.' + kind, this.value);
    renderList(kind);
  });
  sec.querySelector('#dir-' + kind).addEventListener('click', function() {
    const mode = sec.querySelector('#sort-' + kind).value;
    const cur = lsGet('dir.' + kind + '.' + mode) || (mode === 'name' ? 'asc' : 'desc');
    lsSet('dir.' + kind + '.' + mode, cur === 'asc' ? 'desc' : 'asc');
    renderList(kind);
  });
  const svSort = lsGet('sort.' + kind);
  if (svSort) sec.querySelector('#sort-' + kind).value = svSort;
  const svFlt = lsGet('flt.' + kind);
  if (svFlt) sec.querySelector('#flt-' + kind).value = svFlt;
  sec.querySelector('#fmode-' + kind).addEventListener('click', function() {
    const st = _M[kind];
    st.flat = !st.flat;
    lsSet('fmode.' + kind, st.flat ? 'flat' : 'folders');
    renderList(kind);
  });
  sec.querySelector('#crumbs-' + kind).addEventListener('click', function(ev) {
    const b = ev.target.closest('[data-path]');
    if (b) setDir(kind, b.dataset.path);
  });
  sec.querySelector('#list-' + kind).addEventListener('change', function(ev) {
    const cb = ev.target.closest('input.selcb');
    if (!cb) return;
    if (cb.checked) _M[kind].sel.add(cb.dataset.key); else _M[kind].sel.delete(cb.dataset.key);
    updateEdBar(kind);
  });
  sec.querySelector('#list-' + kind).addEventListener('click', function(ev) {
    if (ev.target.closest('button, a, input')) return;
    const row = ev.target.closest('.item');
    if (!row) return;
    if (row.dataset.dir !== undefined) {
      const st = _M[kind];
      setDir(kind, (st.dir ? st.dir + '/' : '') + row.dataset.dir);
    } else openItem(kind, parseInt(row.dataset.idx, 10));
  });
  return sec;
}

// small line icons for the phone tab bar (shown below 600px only)
const TAB_ICONS = {
  status: '<circle cx="10" cy="10" r="7.5"/><path d="M10 9v5M10 6.2v.1"/>',
  movie: '<rect x="2.5" y="4.5" width="15" height="11" rx="1.5"/><path d="M8.5 7.5v5l4-2.5z"/>',
  audio: '<path d="M7.5 15V5l9-1.8v10"/><circle cx="5.5" cy="15" r="2"/><circle cx="14.5" cy="13.2" r="2"/>',
  pdf: '<path d="M5 2.5h7l3.5 3.5v11.5h-10.5z"/><path d="M12 2.5V6h3.5M7.5 10h5M7.5 13h5"/>',
  config: '<path d="M3 6h8M15 6h2M3 14h2M9 14h8"/><circle cx="13" cy="6" r="2"/><circle cx="7" cy="14" r="2"/>',
};
function buildTabs() {
  const nav = document.getElementById('tabs');
  const content = document.getElementById('content');
  const logHdr = document.getElementById('log-hdr');
  ALL_TABS.forEach(function(t) {
    const b = document.createElement('button');
    b.className = 'tab';
    b.dataset.tab = t.id;
    b.title = t.label;
    const ic = document.createElement('span');
    ic.className = 'ti';
    ic.innerHTML = '<svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" ' +
                   'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
                   (TAB_ICONS[t.id] || '') + '</svg>';
    const lb = document.createElement('span');
    lb.className = 'tl';
    lb.textContent = t.label;
    b.appendChild(ic);
    b.appendChild(lb);
    b.addEventListener('click', function() { showTab(t.id); });
    nav.appendChild(b);
    if (t.media) content.insertBefore(buildMediaPanel(t.id), logHdr);
  });
}

function closePlayer(kind) {
  clearPlayer(kind);
  _M[kind].playing = null;
  renderList(kind);
}

function _tabActivated(id) {
  if (id === 'status') { pollStatus(); loadRecent(); }
  else if (_M[id]) loadList(id, false);
  else if (id === 'config') { loadConfig(); loadSelf(); loadStorage(); }
}

// ---- Show / Hide headings: every card starts hidden except where noted. With "Remember open
// cards" (View panel) the state is kept per browser.
function makeFold(hdr, bodies, open, onToggle) {
  if (!hdr || hdr._setOpen) return;
  const key = 'fold.' + (hdr.id || (hdr.textContent.trim().split(/\s+/)[0] || 'x').toLowerCase());
  if (lsGet('foldmem') === '1') {
    const saved = lsGet(key);
    if (saved !== null) open = saved === '1';
  }
  hdr.classList.add('fold');
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'foldbtn';
  hdr.appendChild(btn);
  function set(o) {
    hdr._open = !!o;
    bodies.forEach(function(b) { if (b) b.style.display = o ? '' : 'none'; });
    btn.textContent = o ? 'Hide' : 'Show';
    btn.setAttribute('aria-expanded', o ? 'true' : 'false');
    if (lsGet('foldmem') === '1') lsSet(key, o ? '1' : '0');
    if (onToggle) onToggle(!!o);
  }
  hdr.addEventListener('click', function(ev) {
    const b = ev.target.closest('button');
    if (b && b !== btn) return;  // other buttons in the heading (e.g. Copy) do their own thing
    set(!hdr._open);
  });
  hdr._setOpen = set;
  set(open);
}
let _sysOpen = false;
let _recentOpen = true;
function initFolds() {
  makeFold($('st-new-hdr'), [$('recent-card')], true, function(o) { _recentOpen = o; if (o) loadRecent(); });
  makeFold($('st-sys-hdr'), [$('st-sys-hdr').nextElementSibling], false, function(o) { _sysOpen = o; if (o) pollStatus(); });
  document.querySelectorAll('#tab-config > .hdr').forEach(function(h) {
    const body = h.nextElementSibling;
    if (body && body.classList.contains('card')) makeFold(h, [body], false);
  });
  makeFold($('log-hdr'), [$('logbar'), $('log')], false, function(o) { if (o) renderLog(); });
}
function openEntry(n) {
  // open the Config section that holds entry n and bring it into view
  const ent = $('ent-' + n);
  const card = ent && ent.closest('.card');
  const h = card && card.previousElementSibling;
  if (h && h._setOpen && !h._open) h._setOpen(true);
  if (ent) ent.scrollIntoView({block: 'center', behavior: 'smooth'});
}

// ---- Status: newest files per tab (by date added)
let _recentBusy = false;
async function loadRecent() {
  // not before login: a 401 here would make the fetch wrapper reload the page
  if (!_appStarted || _recentBusy || !_recentOpen || document.hidden || _curTab !== 'status') return;
  _recentBusy = true;
  try {
    const r = await fetch('/api/lib/recent?n=5');
    const d = await r.json();
    const box = $('recent-box');
    const wrap = document.createElement('div');
    wrap.className = 'recent';
    TAB_DEFS.filter(function(t) { return t.media; }).forEach(function(t) {
      const col = document.createElement('div');
      col.className = 'rcol';
      const h = document.createElement('div');
      h.className = 'rhead';
      const hl = document.createElement('span');
      hl.textContent = t.label;
      h.appendChild(hl);
      const all = document.createElement('button');
      all.className = 'lnkbtn';
      all.textContent = 'Show all';
      all.title = 'Open ' + t.label + ' sorted by Recently added';
      all.addEventListener('click', function() { showRecentTab(t.id); });
      h.appendChild(all);
      col.appendChild(h);
      const list = (d.recent && d.recent[t.id]) || [];
      list.forEach(function(it) {
        const row = document.createElement('div');
        row.className = 'rrow';
        row.title = it.rel;
        if (it.art) row.appendChild(artImg(t.id, it.art, 'rthumb'));
        const nm = document.createElement('span');
        nm.className = 'nm';
        nm.textContent = it.rel;
        row.appendChild(nm);
        const dt = document.createElement('span');
        dt.className = 'dt';
        dt.textContent = fmtDate(it.added || it.mtime);
        row.appendChild(dt);
        const sz = document.createElement('span');
        sz.className = 'sz';
        sz.textContent = fmtBytes(it.size);
        row.appendChild(sz);
        row.addEventListener('click', function() { gsOpen(t.id, it.id); });
        col.appendChild(row);
      });
      if (!list.length) {
        const e = document.createElement('div');
        e.className = 'small muted';
        e.textContent = d.offline ? (d.offline_reason || 'Library drive offline') : 'No files yet.';
        col.appendChild(e);
      }
      wrap.appendChild(col);
    });
    box.className = '';
    box.replaceChildren(wrap);
  } catch (e) {}
  finally { _recentBusy = false; }
}
function showRecentTab(kind) {
  const st = _M[kind];
  st.flat = true;
  lsSet('fmode.' + kind, 'flat');
  $('flt-' + kind).value = '';
  lsSet('flt.' + kind, '');
  $('sort-' + kind).value = 'added';
  lsSet('sort.' + kind, 'added');
  lsSet('dir.' + kind + '.added', 'desc');
  showTab(kind);
  renderList(kind);
}

function showTab(id) {
  if (!ALL_TABS.some(function(t) { return t.id === id; })) id = 'status';
  if (_curTab === 'movie' && id !== 'movie') closePlayer('movie');
  _curTab = id;
  lsSet('tab', id);
  document.querySelectorAll('button.tab').forEach(function(b) {
    b.classList.toggle('active', b.dataset.tab === id);
  });
  document.querySelectorAll('.panel').forEach(function(p) {
    p.classList.toggle('active', p.id === 'tab-' + id);
  });
  try { history.replaceState(null, '', '#' + id); } catch (e) {}
  if (_appStarted) _tabActivated(id);
}

// ---- log
let lastLogId = 0;
const MAX_CLIENT_LOG_LINES = 500;
function logLine(entry) {
  _logAll.push(entry);
  while (_logAll.length > MAX_CLIENT_LOG_LINES) _logAll.shift();
  if (logPass(entry)) logAppend(entry);
  lastLogId = entry.id;
}
let _pollLogBusy = false;
async function pollLog() {
  if (_pollLogBusy || document.hidden) return;
  _pollLogBusy = true;
  try {
    const r = await fetch('/api/log?since=' + lastLogId);
    const data = await r.json();
    for (const entry of data.entries) {
      if (typeof entry.id === 'number' && entry.id <= lastLogId) continue;
      logLine(entry);
    }
  } catch (e) {}
  finally { _pollLogBusy = false; }
}

// ---- status
function addKv(grid, k, v) {
  const a = document.createElement('div');
  a.className = 'k';
  a.textContent = k;
  const b = document.createElement('div');
  b.className = 'v';
  b.textContent = v;
  grid.appendChild(a);
  grid.appendChild(b);
}
let _pollStatusBusy = false;
async function pollStatus() {
  if (!_appStarted || _pollStatusBusy || document.hidden || _curTab !== 'status' || !_sysOpen) return;
  _pollStatusBusy = true;
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    const g = document.createElement('div');
    g.className = 'kv';
    addKv(g, 'Host', s.hostname + (s.model ? ' (' + s.model + ')' : ''));
    addKv(g, 'Kernel / Python', s.kernel + ' / ' + s.python);
    addKv(g, 'System uptime', fmtDur(s.system_uptime));
    addKv(g, 'Pibrary uptime', fmtDur(s.process_uptime));
    addKv(g, 'Load (1/5/15)', s.load ? s.load.map(function(x) { return x.toFixed(2); }).join(' / ') : 'n/a');
    addKv(g, 'CPU temp', s.cpu_temp_c === null ? 'n/a' : s.cpu_temp_c.toFixed(1) + ' C');
    const m = s.memory || {};
    if (m.MemTotal) addKv(g, 'Memory', fmtBytes(m.MemAvailable) + ' free of ' + fmtBytes(m.MemTotal));
    if (m.SwapTotal) addKv(g, 'Swap', fmtBytes(m.SwapFree) + ' free of ' + fmtBytes(m.SwapTotal));
    (s.disks || []).forEach(function(d) {
      addKv(g, 'Disk ' + d.path, d.exists
        ? fmtBytes(d.free) + ' free of ' + fmtBytes(d.total)
        : (d.offline ? 'offline (USB drive not connected)'
           : (d.total === null ? 'missing' : fmtBytes(d.free) + ' free (not a directory)')));
    });
    if (s.storage) addKv(g, 'Library storage', (s.storage.mode === 'usb' ? 'USB drive' : 'SD card') +
      ' - ' + s.storage.state + ' (' + s.storage.root + ')' +
      (s.storage.fault ? ' | drive error: ' + s.storage.fault +
        (s.storage.gave_up ? ' (auto-remount stopped: fix power, then replug or press Mount)' : ' (reconnecting)') : ''));
    if (s.streams) addKv(g, 'Streams', s.streams.active + ' active of ' + s.streams.max +
      (s.streams.idle ? ', ' + s.streams.idle + ' paused (next closes in ' + fmtClock(s.streams.next_close) + ')' : ''));
    const w = s.sd_writes || {};
    addKv(g, 'SD card writes this boot', Object.keys(w).length
      ? Object.keys(w).map(function(k) { return k + ' ' + w[k]; }).join(', ') : 'none');
    const ac = s.access || {};
    if (ac.via) addKv(g, 'Access', (ac.public ? 'WARNING: ' : '') + 'via ' + ac.via + ' (from ' + ac.client +
      ', address ' + ac.host + (ac.host_listed ? '' : ' - not an allowed host!') + ')');
    const pw = s.power || {};
    addKv(g, 'Power', pw.available === false ? 'n/a (vcgencmd not found)'
      : (pw.raw === undefined || pw.raw === null) ? 'checking...'
      : ((pw.now && pw.now.length ? 'NOW: ' + pw.now.join(', ') : 'OK now') +
         (pw.boot && pw.boot.length ? ' | since boot: ' + pw.boot.join(', ') : '') + ' (' + pw.raw + ')'));
    (s.drive_health || []).forEach(function(h) {
      addKv(g, 'Drive health ' + h.disk + ' (' + h.role + ')', !h.available ? h.reason
        : [h.passed === false ? 'SMART FAILED' : (h.passed ? 'SMART passed' : 'SMART n/a'),
           h.temp_c !== null && h.temp_c !== undefined ? h.temp_c + ' C' : '',
           h.hours !== null && h.hours !== undefined ? h.hours + ' h on' : '',
           h.reallocated ? h.reallocated + ' reallocated' : '', h.pending ? h.pending + ' pending' : '',
           h.media_errors ? h.media_errors + ' media errors' : '',
           h.wear_pct !== null && h.wear_pct !== undefined ? h.wear_pct + '% worn' : ''].filter(Boolean).join(', '));
    });
    const nt = s.notify || {};
    addKv(g, 'Notifications', nt.set ? ('ntfy on, ' + nt.sent + ' sent' + (nt.last_error ? ', last error: ' + nt.last_error : ''))
      : 'off (Config entry 13)');
    addKv(g, 'Heartbeat', !nt.heartbeat ? 'off (Config entry 14)'
      : (nt.heartbeat_ok === null || nt.heartbeat_ok === undefined ? 'waiting for the first ping'
         : (nt.heartbeat_ok ? 'OK' : 'failing (see the log)')));
    const ps = s.positions || {};
    addKv(g, 'Resume positions', ps.available
      ? 'shared, on the library drive' + (ps.count !== null && ps.count !== undefined ? ' (' + ps.count + ')' : '') +
        (ps.pending ? ', saving soon' : '')
      : 'this browser only' + (ps.reason ? ': ' + ps.reason : ''));
    addKv(g, 'Login', s.auth_enabled ? 'enabled' : 'disabled');
    document.getElementById('status-grid').replaceChildren(g);
  } catch (e) {}
  finally { _pollStatusBusy = false; }
}

// ---- media lists
function loadList(kind, refresh) {
  // one request per tab at a time; callers that need the data can await the shared promise
  const st = _M[kind];
  if (st.loading) return st.loading;
  st.loading = (async function() {
    try {
      const r = await fetch('/api/lib/list?type=' + kind + '&refresh=' + (refresh ? 1 : 0));
      const d = await r.json();
      if (!r.ok) { $('cnt-' + kind).textContent = d.error || 'List failed'; return; }
      st.items = d.items;
      st.meta = d;
      st.loadedAt = Date.now();
      applyUploadState(kind);
      renderList(kind);
      updateFree(kind, d);
    } catch (e) {}
    finally { st.loading = null; }
  })();
  return st.loading;
}

function setDir(kind, path) {
  const st = _M[kind];
  st.dir = path || '';
  st.sel.clear();
  lsSet('cwd.' + kind, st.dir);
  renderList(kind);
}

function upDirRel(kind) {
  // uploads go into the folder being viewed, when that folder is on the library drive
  const st = _M[kind];
  if (st.flat || !st.dir || !st.meta) return '';
  return (st.meta.dirs || []).indexOf(st.dir) >= 0 ? st.dir : '';
}

function upDir(kind) {
  const st = _M[kind];
  if (!st.dir) return;
  const k = st.dir.lastIndexOf('/');
  setDir(kind, k >= 0 ? st.dir.slice(0, k) : '');
}

function renderCrumbs(kind, cwd, show) {
  const box = $('crumbs-' + kind);
  box.style.display = show ? '' : 'none';
  if (!show) { box.replaceChildren(); return; }
  const frag = document.createDocumentFragment();
  const parts = cwd ? cwd.split('/') : [];
  function crumb(text, path, current) {
    const b = document.createElement(current ? 'span' : 'button');
    b.className = current ? 'crumb cur' : 'crumb';
    b.textContent = text;
    if (!current) b.dataset.path = path;
    frag.appendChild(b);
  }
  const label = (TAB_DEFS.find(function(t) { return t.id === kind; }) || {label: kind}).label;
  crumb(label, '', !parts.length);
  parts.forEach(function(p, i) {
    const sep = document.createElement('span');
    sep.className = 'crumbsep';
    sep.textContent = '/';
    frag.appendChild(sep);
    crumb(p, parts.slice(0, i + 1).join('/'), i === parts.length - 1);
  });
  box.replaceChildren(frag);
}

function applyUploadState(kind) {
  const d = _M[kind].meta;
  const can = !!d.can_upload && !_uploading;
  const sub = upDirRel(kind);
  document.getElementById('file-' + kind).disabled = !can;
  document.getElementById('upbtn-' + kind).disabled = !can;
  document.getElementById('upinfo-' + kind).textContent = d.offline
    ? ((d.offline_reason || ('USB library drive is ' + d.state)) +
       ': the list and uploads are unavailable until it is back.')
    : (d.migrating ? 'Uploads are paused while the library is being copied.'
    : (d.can_upload
      ? ('Uploads to ' + d.upload_dir + (sub ? '/' + sub : '') + ' | allowed: ' + d.exts.join(' ') +
         ' | max ' + d.max_upload_mb + ' MB')
      : 'Uploads disabled: tick "Allow uploads" in Config (requires login).'));
  document.getElementById('file-' + kind).accept = d.exts.join(',');
}

function renderList(kind) {
  const st = _M[kind];
  const q = $('flt-' + kind).value.trim().toLowerCase();
  const mode = $('sort-' + kind).value;
  const folders = !st.flat;
  let cwd = folders ? st.dir : '';
  const ownDirs = new Set((st.meta && st.meta.dirs) || []);
  if (cwd && st.meta) {
    // the remembered folder may be gone: fall back to its deepest existing ancestor
    while (cwd && !ownDirs.has(cwd) && !st.items.some(function(i) { return i.rel.startsWith(cwd + '/'); })) {
      const k = cwd.lastIndexOf('/');
      cwd = k >= 0 ? cwd.slice(0, k) : '';
    }
    if (cwd !== st.dir) { st.dir = cwd; lsSet('cwd.' + kind, cwd); }
  }
  const pre = cwd ? cwd + '/' : '';
  const under = pre ? st.items.filter(function(i) { return i.rel.startsWith(pre); }) : st.items;
  let v = [];
  const dmap = {};
  if (!folders || q) {
    v = under.filter(function(i) { return !q || i.rel.slice(pre.length).toLowerCase().indexOf(q) >= 0; });
  } else {
    under.forEach(function(i) {
      const r = i.rel.slice(pre.length);
      const k = r.indexOf('/');
      if (k < 0) { v.push(i); return; }
      const name = r.slice(0, k);
      const e = dmap[name] || (dmap[name] = {name: name, count: 0, size: 0, played: 0});
      e.count++;
      e.size += i.size;
      if (posState(kind, i) === 'played') e.played++;
    });
    ownDirs.forEach(function(dname) {
      // folders on the library drive show up even when empty
      if (!dname.startsWith(pre)) return;
      const r = dname.slice(pre.length);
      if (!r || r.indexOf('/') >= 0 || dmap[r]) return;
      dmap[r] = {name: r, count: 0, size: 0, played: 0};
    });
  }
  const pf = $('pf-' + kind).value;
  if (pf !== 'all') v = v.filter(function(i) { const s = posState(kind, i); return pf === 'unplayed' ? s !== 'played' : s === pf; });
  const sel = st.selMode && !!(st.meta && st.meta.can_edit);
  st.shown = [];
  function selBox(row, key) {
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'selcb';
    cb.dataset.key = key;
    cb.checked = st.sel.has(key);
    row.insertBefore(cb, row.firstChild);
    st.shown.push(key);
  }
  const dirs = Object.keys(dmap).sort(function(a, b) {
    const x = a.toLowerCase(), y = b.toLowerCase();
    return x < y ? -1 : (x > y ? 1 : 0);
  }).map(function(n) { return dmap[n]; });
  $('fmode-' + kind).textContent = folders ? 'Folders' : 'Flat';
  $('flt-' + kind).placeholder = (folders && cwd) ? 'Filter this folder' : 'Filter';
  renderCrumbs(kind, cwd, folders);
  const cmp = {
    name: function(a, b) { return a.rel.toLowerCase() < b.rel.toLowerCase() ? -1 : 1; },
    size: function(a, b) { return a.size - b.size; },
    date: function(a, b) { return a.mtime - b.mtime; },
    added: function(a, b) { return (a.added || 0) - (b.added || 0); },
  };
  const dir = lsGet('dir.' + kind + '.' + mode) || (mode === 'name' ? 'asc' : 'desc');
  v.sort(function(a, b) { const r = (cmp[mode] || cmp.name)(a, b); return dir === 'asc' ? r : -r; });
  $('dir-' + kind).textContent = dir === 'asc' ? 'Asc' : 'Desc';
  st.view = v;
  const frag = document.createDocumentFragment();
  dirs.forEach(function(dd) {
    const row = document.createElement('div');
    row.className = 'item folder';
    row.dataset.dir = dd.name;
    const ex = document.createElement('span');
    ex.className = 'ext';
    ex.textContent = 'DIR';
    const dart = st.meta && st.meta.dir_art && st.meta.dir_art[pre + dd.name];
    if (dart) { ex.textContent = ''; ex.appendChild(artImg(kind, dart)); }
    row.appendChild(ex);
    if (dart) row.appendChild(artImg(kind, dart, 'fthumb'));
    const nm = document.createElement('span');
    nm.className = 'nm';
    nm.textContent = dd.name + '/';
    row.appendChild(nm);
    const dt = document.createElement('span');
    dt.className = 'dt';
    dt.textContent = dd.count + (dd.count === 1 ? ' file' : ' files') + (dd.played ? ', ' + dd.played + ' played' : '');
    row.appendChild(dt);
    const sz = document.createElement('span');
    sz.className = 'sz';
    sz.textContent = fmtBytes(dd.size);
    row.appendChild(sz);
    if (st.meta && st.meta.can_edit && ownDirs.has(pre + dd.name)) {
      const del = document.createElement('button');
      del.className = 'lnkbtn';
      del.textContent = 'Delete folder';
      del.title = 'Move this folder and everything in it to the trash';
      del.addEventListener('click', function(ev) { ev.stopPropagation(); edDeleteFolder(kind, pre + dd.name, dd.count, dd.size); });
      row.appendChild(del);
    }
    if (sel && ownDirs.has(pre + dd.name)) selBox(row, 'd:' + pre + dd.name);
    frag.appendChild(row);
  });
  v.slice(0, RENDER_CAP).forEach(function(it, idx) {
    const url = '/api/lib/file?type=' + kind + '&id=' + encodeURIComponent(it.id);
    const row = document.createElement('div');
    row.className = 'item' + (st.playing === it.id ? ' playing' : '');
    row.dataset.idx = idx;
    const ex = document.createElement('span');
    ex.className = 'ext';
    ex.textContent = (it.name.split('.').pop() || '').toUpperCase().slice(0, 5);
    if (it.art && lsGet('mview') === 'grid') { ex.textContent = ''; ex.appendChild(artImg(kind, it.art)); }
    row.appendChild(ex);
    const nm = document.createElement('span');
    nm.className = 'nm';
    nm.textContent = it.rel.slice(pre.length);
    row.appendChild(nm);
    if (it.warn) {
      const w = document.createElement('span');
      w.className = 'warnb';
      w.textContent = 'may not play';
      row.appendChild(w);
    }
    const ps = posState(kind, it);
    if (ps) {
      const pb = document.createElement('span');
      pb.className = 'warnb' + (ps === 'played' ? ' ok' : '');
      const pe = _pos[kind + ':' + it.rel + ':' + it.size];
      pb.textContent = ps === 'played' ? 'played' : 'at ' + fmtTime(pe.t);
      row.appendChild(pb);
    }
    const dt = document.createElement('span');
    dt.className = 'dt';
    dt.textContent = fmtDate(mode === 'added' ? (it.added || it.mtime) : it.mtime);
    row.appendChild(dt);
    const sz = document.createElement('span');
    sz.className = 'sz';
    sz.textContent = fmtBytes(it.size);
    row.appendChild(sz);
    if (kind === 'audio') {
      [['Next', 'Play after the current track', true], ['+Queue', 'Add to the end of the queue', false]].forEach(function(b) {
        const x = document.createElement('button');
        x.className = 'lnkbtn';
        x.textContent = b[0];
        x.title = b[1];
        x.addEventListener('click', function(ev) { ev.stopPropagation(); qAdd(it, b[2]); });
        row.appendChild(x);
      });
    }
    const dl = document.createElement('a');
    dl.className = 'lnkbtn';
    dl.textContent = 'Download';
    dl.href = url + '&download=1';
    dl.setAttribute('download', it.name);
    row.appendChild(dl);
    const cp = document.createElement('button');
    cp.className = 'lnkbtn';
    cp.textContent = 'Copy link';
    cp.addEventListener('click', function(ev) { ev.stopPropagation(); copyText(location.origin + url); });
    row.appendChild(cp);
    if (sel && it.root === 0) selBox(row, 'f:' + it.rel);
    frag.appendChild(row);
  });
  const box = $('list-' + kind);
  if (!v.length && !dirs.length) {
    const e = document.createElement('div');
    e.className = 'small muted';
    e.textContent = st.items.length ? (q ? 'No matches.' : 'This folder is empty.')
                                    : 'No files yet. Upload above or copy files into the folder.';
    box.replaceChildren(e);
  } else {
    box.replaceChildren(frag);
  }
  let total = 0;
  st.items.forEach(function(i) { total += i.size; });
  let cnt = (dirs.length ? dirs.length + (dirs.length === 1 ? ' folder, ' : ' folders, ') : '') +
            v.length + ' of ' + st.items.length + ' files, ' + fmtBytes(total) + ' total';
  if (folders && q) cnt += ' | searching ' + (cwd ? cwd + '/' : 'all folders');
  if (v.length > RENDER_CAP) cnt += ' (showing first ' + RENDER_CAP + ', use the filter)';
  if (st.meta && st.meta.truncated) cnt += ' | scan capped at ' + st.meta.cap + ' files';
  $('cnt-' + kind).textContent = cnt;
  renderContinue(kind);
  updateEdBar(kind);
  if (st.meta) applyUploadState(kind);
}

function clearPlayer(kind) {
  const box = document.getElementById('player-' + kind);
  box.querySelectorAll('video,audio').forEach(function(m) {
    posRecord(m, true);  // the pause event fires after src is gone, so save now
    m._pp = null;
    m.pause();
    m.removeAttribute('src');
    m.load();
  });
  box.replaceChildren();
}

function openItem(kind, idx) {
  const st = _M[kind];
  const it = st.view[idx];
  if (!it) return;
  const url = '/api/lib/file?type=' + kind + '&id=' + encodeURIComponent(it.id);
  if (kind === 'pdf') { window.open(url, '_blank', 'noopener'); return; }
  if (kind === 'audio') {
    // audio plays in the mini-player: the current view becomes the queue
    if (st.view.length > Q_MAX) qPlayList(st.view.slice(idx, idx + Q_MAX), 0);
    else qPlayList(st.view, idx);
    return;
  }
  clearPlayer(kind);
  st.playing = it.id;
  const box = $('player-' + kind);
  const title = document.createElement('div');
  title.className = 'ptitle';
  title.textContent = it.rel;
  const badge = document.createElement('span');
  badge.className = 'warnb';
  badge.id = 'sbadge-' + kind;
  badge.style.display = 'none';
  const restart = document.createElement('button');
  restart.textContent = 'Start over';
  restart.style.display = 'none';
  const el = document.createElement('video');
  el.controls = true;
  el.autoplay = true;
  el.preload = 'metadata';
  posAttach(el, kind, it);
  posWire(el, function(t) {
    restart.style.display = '';
    toast('Resumed at ' + fmtTime(t), 'info');
  });
  restart.addEventListener('click', function() {
    if (el._pp) posForget(el._pp.key);
    el.currentTime = 0;
    restart.style.display = 'none';
  });
  el.addEventListener('playing', function() { el.dataset.started = '1'; });
  el.addEventListener('play', function() {
    const a = $('mp-audio');
    if (!a.paused) a.pause();
    msMeta(it, 'movie');
    msState('playing');
  });
  el.addEventListener('pause', function() { msState('paused'); });
  el.addEventListener('timeupdate', function() { msPos(el); });
  el.addEventListener('error', function() {
    title.textContent = it.rel + ' (the browser could not play this file)';
  });
  if (it.art) el.poster = artUrl(kind, it.art);
  el.src = url;
  applyRate(el, 'movie');
  const hdr = document.createElement('div');
  hdr.className = 'phdr';
  const closeBtn = document.createElement('button');
  closeBtn.textContent = 'Close';
  closeBtn.addEventListener('click', function() { closePlayer(kind); });
  hdr.appendChild(title);
  hdr.appendChild(badge);
  hdr.appendChild(restart);
  hdr.appendChild(rateSelect('movie', el));
  const sl = document.createElement('button');
  sl.className = 'sleepbtn';
  sl.title = 'Sleep timer';
  sl.addEventListener('click', sleepCycle);
  hdr.appendChild(sl);
  if ((el.remote && typeof el.remote.prompt === 'function') || typeof el.webkitShowPlaybackTargetPicker === 'function') {
    const castBtn = document.createElement('button');
    castBtn.textContent = 'Cast';
    castBtn.addEventListener('click', function() { castMedia(el); });
    hdr.appendChild(castBtn);
  }
  hdr.appendChild(closeBtn);
  box.appendChild(hdr);
  box.appendChild(el);
  sleepLabels();
  renderList(kind);
}

// ---- uploads (raw body over XHR, one file at a time)
let _uploading = false;
let _upCancel = false;
let _upXhr = null;

function upMsg(kind, text) { document.getElementById('upmsg-' + kind).textContent = text; }

function setUpBusy(kind, busy) {
  const can = !!(_M[kind].meta && _M[kind].meta.can_upload);
  $('upbtn-' + kind).disabled = busy || !can;
  $('upcancel-' + kind).disabled = !busy;
  $('file-' + kind).disabled = busy || !can;
  if (!busy) $('upbar-' + kind).style.width = '0';
}

function cancelUpload() {
  _upCancel = true;
  if (_upXhr) _upXhr.abort();
}

async function precheck(kind, f, sub) {
  try {
    const r = await fetch('/api/lib/precheck?type=' + kind + '&name=' + encodeURIComponent(f.name) +
                          '&dir=' + encodeURIComponent(sub || '') + '&size=' + f.size);
    const d = await r.json();
    return {ok: !!d.ok, error: d.error || ('HTTP ' + r.status), exists: !!d.exists};
  } catch (e) {
    return {ok: false, error: 'Network error'};
  }
}

function xhrUpload(kind, file, force, prefix, sub) {
  return new Promise(function(resolve) {
    const xhr = new XMLHttpRequest();
    _upXhr = xhr;
    const bar = document.getElementById('upbar-' + kind);
    xhr.open('POST', '/api/lib/upload?type=' + kind + '&name=' + encodeURIComponent(file.name) +
                     '&dir=' + encodeURIComponent(sub || '') + '&force=' + (force ? 1 : 0));
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    const t0 = Date.now();
    xhr.upload.onprogress = function(e) {
      if (!e.lengthComputable) return;
      const pct = e.loaded / e.total * 100;
      bar.style.width = pct + '%';
      const sec = (Date.now() - t0) / 1000;
      upMsg(kind, (prefix ? prefix + ' ' : '') + file.name + ' ' + pct.toFixed(0) + '% (' +
                  fmtBytes(sec > 0 ? e.loaded / sec : 0) + '/s)');
    };
    xhr.onload = function() {
      let d = {};
      try { d = JSON.parse(xhr.responseText); } catch (e) {}
      if (xhr.status === 401) { _onAuthLost(); resolve({ok: false, error: 'Session expired'}); return; }
      resolve(xhr.status === 200 ? {ok: true} : {ok: false, error: d.error || ('HTTP ' + xhr.status)});
    };
    xhr.onerror = function() { resolve({ok: false, error: 'Network error'}); };
    xhr.onabort = function() { resolve({ok: false, error: 'Cancelled', cancelled: true}); };
    xhr.send(file);
  });
}

async function startUpload(kind) {
  const input = document.getElementById('file-' + kind);
  const files = Array.from(input.files || []);
  if (!files.length) { upMsg(kind, 'Choose a file first.'); return; }
  if (_uploading) { upMsg(kind, 'An upload is already running.'); return; }
  _uploading = true;
  _upCancel = false;
  setUpBusy(kind, true);
  const sub = upDirRel(kind);
  let done = 0;
  let lastErr = '';
  try {
    for (let i = 0; i < files.length; i++) {
      if (_upCancel) break;
      const f = files[i];
      const pre = await precheck(kind, f, sub);
      if (!pre.ok) { lastErr = f.name + ': ' + pre.error; upMsg(kind, lastErr); continue; }
      let force = false;
      if (pre.exists) {
        if (!confirm('Overwrite ' + f.name + '?')) { lastErr = 'Skipped ' + f.name; upMsg(kind, lastErr); continue; }
        force = true;
      }
      const res = await xhrUpload(kind, f, force, files.length > 1 ? (i + 1) + '/' + files.length : '', sub);
      if (res.ok) done++;
      else { lastErr = f.name + ': ' + res.error; upMsg(kind, lastErr); if (res.cancelled) break; }
    }
  } finally {
    _uploading = false;
    _upCancel = false;
    _upXhr = null;
    input.value = '';
    setUpBusy(kind, false);
  }
  if (done) {
    upMsg(kind, 'Uploaded ' + done + ' file(s).' + (lastErr ? ' Last problem: ' + lastErr : ''));
    popup('Uploaded ' + done + ' file(s)', 'ok');
  }
  await loadList(kind, true);
}

// ---- config
let _cfgSnap = null;
function $(id) { return document.getElementById(id); }

function toast(msg, level) {
  const box = $('toasts');
  const t = document.createElement('div');
  t.className = 'toast ' + (level || 'info');
  t.textContent = msg;
  box.appendChild(t);
  while (box.childNodes.length > 4) box.removeChild(box.firstChild);
  setTimeout(function() { if (t.parentNode) t.parentNode.removeChild(t); }, 2600);
}

function applyView() {
  const h = document.documentElement;
  let t = lsGet('theme') || 'dark';
  const shown = t;
  if (t === 'auto') t = (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
  h.dataset.theme = t;
  h.dataset.size = lsGet('size') || 'm';
  h.dataset.density = lsGet('density') || 'comfortable';
  h.dataset.mview = lsGet('mview') || 'list';
  $('vp-theme').value = shown;
  $('vp-size').value = h.dataset.size;
  $('vp-density').value = h.dataset.density;
  $('vp-mview').value = h.dataset.mview;
  placeNav();
}

function placeNav() {
  // the pinned tab rail starts just below the sticky header, whose height depends on text size / width
  const hdr = document.querySelector('header');
  if (hdr) document.documentElement.style.setProperty('--navtop', (hdr.offsetHeight + 12) + 'px');
}
window.addEventListener('resize', placeNav);
// the header can grow after load (Log Out button appears, text wraps, fonts, rotation): follow it
if (window.ResizeObserver) {
  try { new ResizeObserver(function() { placeNav(); }).observe(document.querySelector('header')); } catch (e) {}
}
window.addEventListener('orientationchange', function() { setTimeout(placeNav, 300); });
window.addEventListener('load', placeNav);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(placeNav).catch(function() {});

const _logAll = [];
function logPass(e) {
  if (!$('lg-' + e.level) && e.level !== 'info') return true;
  const box = $('lg-' + (e.level || 'info'));
  if (box && !box.checked) return false;
  const q = $('lg-filter').value.trim().toLowerCase();
  return !q || e.msg.toLowerCase().indexOf(q) >= 0;
}
function logAppend(e) {
  const el = $('log');
  const div = document.createElement('div');
  if (e.level === 'ok') div.className = 'log-ok';
  else if (e.level === 'err') div.className = 'log-err';
  else if (e.level === 'warn') div.className = 'log-warn';
  div.textContent = '[' + e.ts + '] ' + e.msg;
  el.appendChild(div);
  while (el.childNodes.length > MAX_CLIENT_LOG_LINES) el.removeChild(el.firstChild);
  el.scrollTop = el.scrollHeight;
}
function renderLog() {
  $('log').replaceChildren();
  _logAll.forEach(function(e) { if (logPass(e)) logAppend(e); });
}
function downloadLog() {
  const text = _logAll.map(function(e) { return '[' + e.ts + '] ' + e.level + ' ' + e.msg; }).join('\n') + '\n';
  const url = URL.createObjectURL(new Blob([text], {type: 'text/plain'}));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'pibrary-log-' + new Date().toISOString().slice(0, 10) + '.txt';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
}
function lsGet(k) { try { return localStorage.getItem('pibrary.' + k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem('pibrary.' + k, v); } catch (e) {} }
function fmtClock(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }

const ENTRY_OF = {auth_enabled: 2, allow_write: 3, allow_update: 4, library_root: 6, extra_roots: 7,
                  max_upload_mb: 8, max_streams: 9, port: 10, tab_side: 11,
                  notify_url: 13, notify_level: 13, heartbeat_url: 14, heartbeat_min: 14, auto_import: 15,
                  log_file: 17};
const ENTRY_LABEL = {auth_enabled: 'Require login', allow_write: 'Allow uploads',
                     allow_update: 'Allow software update', library_root: 'Library root',
                     extra_roots: 'Extra roots', max_upload_mb: 'Max upload size',
                     max_streams: 'Max concurrent streams', port: 'Port', tab_side: 'Tab side',
                     notify_url: 'Notifications', notify_level: 'Notifications',
                     heartbeat_url: 'Heartbeat', heartbeat_min: 'Heartbeat', auto_import: 'Auto-import',
                     log_file: 'Log file'};
let _cfgBase = null;
let _cfgDirty = false;

function entryError(msg) {
  const low = (msg || '').toLowerCase();
  const m = /^(\w+):/.exec(msg || '');
  let key = m && ENTRY_OF[m[1]] ? m[1] : null;
  if (!key) {
    Object.keys(ENTRY_OF).forEach(function(k) {
      if (!key && (low.indexOf(k) >= 0 || low.indexOf(k.replace('_', ' ')) >= 0)) key = k;
    });
  }
  if (key) return 'Entry ' + ENTRY_OF[key] + ' (' + ENTRY_LABEL[key] + '): ' + msg.replace(/^\w+:\s*/, '');
  return msg;
}

function cfgValues() {
  return {
    auth_enabled: $('cfg-auth_enabled').checked,
    allow_write: $('cfg-allow_write').checked,
    allow_update: $('cfg-allow_update').checked,
    tab_side: $('cfg-side-right').checked ? 'right' : 'left',
    port: $('cfg-port').value,
    library_root: $('cfg-library_root').value,
    max_streams: $('cfg-max_streams').value,
    max_upload_mb: $('cfg-max_upload_mb').value,
    extra_roots: $('cfg-extra_roots').value,
    notify_url: $('cfg-notify_url').value.trim(),
    notify_level: $('cfg-notify_level').value,
    heartbeat_url: $('cfg-heartbeat_url').value.trim(),
    heartbeat_min: $('cfg-heartbeat_min').value,
    auto_import: $('cfg-auto_import').checked,
    log_file: $('cfg-log_file').checked,
  };
}

function cfgApplyDeps() {
  const auth = $('cfg-auth_enabled').checked;
  ['allow_write', 'allow_update', 'auto_import'].forEach(function(k) {
    const c = $('cfg-' + k);
    if (!auth) c.checked = false;
    c.disabled = !auth;
  });
  const sc = _cfgSnap ? _cfgSnap.config : {};
  const savedAuth = !!sc.auth_enabled;
  const savedUpd = savedAuth && !!sc.allow_update;
  $('ent-5').classList.toggle('locked', !savedAuth);
  $('lock-5').style.display = savedAuth ? 'none' : '';
  $('ent-12').classList.toggle('locked', !savedUpd);
  $('lock-12').style.display = savedUpd ? 'none' : '';
  $('cfg-library_root').disabled = !!sc.usb_uuid;
  $('cfg-firstrun').style.display = savedAuth ? 'none' : '';
}

function cfgSetDirty() {
  _cfgDirty = !!_cfgBase && JSON.stringify(cfgValues()) !== _cfgBase;
  $('cfg-dirty').textContent = _cfgDirty ? 'Unsaved changes' : '';
  $('cfg-dirty-hdr').textContent = _cfgDirty ? 'unsaved changes' : '';
  $('cfg-save').disabled = !_cfgDirty;
  const fin = $('ent-fin').closest('.card').previousElementSibling;
  if (_cfgDirty && fin && fin._setOpen && !fin._open) fin._setOpen(true);
  document.querySelectorAll('#self-list .inst-btn').forEach(function(b) {
    b.disabled = _cfgDirty || b.dataset.can !== '1' || _selfBusy;
    b.title = _cfgDirty ? 'Save or discard your changes first' : '';
  });
}

function onCfgEdit() { cfgApplyDeps(); cfgSetDirty(); }

function updateFree(kind, d) {
  const bar = $('fbar-' + kind);
  const txt = $('ftxt-' + kind);
  if (d.free === null || d.free === undefined || !d.total) {
    bar.style.width = '0';
    txt.textContent = d.offline ? 'Library drive offline' : '';
    return;
  }
  const used = (d.total - d.free) / d.total * 100;
  bar.style.width = used + '%';
  bar.style.background = used > 90 ? 'var(--red)' : 'var(--green)';
  txt.textContent = 'Library volume: ' + fmtBytes(d.free) + ' free of ' + fmtBytes(d.total);
}

function stepItem(kind, delta) {
  const st = _M[kind];
  const cur = st.view.findIndex(function(x) { return x.id === st.playing; });
  if (cur >= 0 && cur + delta >= 0 && cur + delta < st.view.length) openItem(kind, cur + delta);
}

function copyText(text, okMsg, what) {
  // plain HTTP has no clipboard API, so fall back to a hidden textarea + execCommand
  okMsg = okMsg || 'Link copied';
  what = what || 'link';
  function fallback() {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
    if (ok) popup(okMsg, 'ok');
    else if (text.length < 2000) window.prompt('Copy this ' + what + ':', text);
    else popup('Copy failed in this browser; use Download instead.', 'warn');
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(function() { popup(okMsg, 'ok'); }, fallback);
  } else fallback();
}
// ---- alerts banner (power, drive, space): dismissed alerts stay hidden until they change
const _ALERT_DISMISS_KEY = 'pibrary.alerts.dismissed';
function alertKey(a) { return a.id + '|' + a.level + '|' + a.since; }
function alertDismissed() {
  try { return JSON.parse(sessionStorage.getItem(_ALERT_DISMISS_KEY) || '[]'); } catch (e) { return []; }
}
let _pollAlertsBusy = false;
async function pollAlerts() {
  if (!_appStarted || _pollAlertsBusy || document.hidden) return;
  _pollAlertsBusy = true;
  try {
    const r = await fetch('/api/alerts');
    if (!r.ok) return;
    const d = await r.json();
    const gone = alertDismissed();
    const frag = document.createDocumentFragment();
    (d.alerts || []).forEach(function(a) {
      if (gone.indexOf(alertKey(a)) >= 0) return;
      const b = document.createElement('div');
      b.className = 'banner' + (a.level === 'err' ? ' banner-err' : '');
      const t = document.createElement('span');
      t.textContent = a.text;
      b.appendChild(t);
      const x = document.createElement('button');
      x.className = 'lnkbtn';
      x.textContent = 'Dismiss';
      x.addEventListener('click', function() {
        const list = alertDismissed();
        list.push(alertKey(a));
        try { sessionStorage.setItem(_ALERT_DISMISS_KEY, JSON.stringify(list.slice(-50))); } catch (e) {}
        b.remove();
      });
      b.appendChild(x);
      frag.appendChild(b);
    });
    $('alerts').replaceChildren(frag);
  } catch (e) {}
  finally { _pollAlertsBusy = false; }
}
async function notifyTest() {
  const res = await apiPost('/api/notify/test', {url: $('cfg-notify_url').value.trim()});
  popup(res.ok ? 'Test sent: check your phone' : (res.data.error || ('Failed (' + res.status + ')')), res.ok ? 'ok' : 'err');
}

// ---- config backup / restore
let _bk = null;  // {source: 'file'|'drive', data?, uuid?}
function bkDownload() {
  const a = document.createElement('a');
  a.href = '/api/config/backup' + ($('bk-withpw').checked ? '?password=1' : '');
  a.download = '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
async function bkPreview(src) {
  _bk = src;
  const res = await apiPost('/api/config/restore', Object.assign({preview: true,
    restore_storage: $('bk-storage').checked, restore_password: $('bk-pw').checked}, src));
  const box = $('bk-preview');
  if (!res.ok) { box.textContent = errText(res); $('bk-apply-row').style.display = 'none'; return; }
  const d = res.data;
  const f = d.from || {};
  const lines = ['Backup from ' + (f.hostname || '?') + ', ' + (f.date || '?') + ', v' + (f.version || '?') +
                 (f.has_password ? ', includes the password' : '') + ': ' +
                 (d.changes.length ? d.changes.length + ' change(s):' : 'no changes.')];
  d.changes.forEach(function(c) {
    lines.push('  ' + c.key + ': ' + JSON.stringify(c.from) + ' -> ' + JSON.stringify(c.to));
  });
  (d.problems || []).forEach(function(p) { lines.push('  skipped: ' + p); });
  box.style.whiteSpace = 'pre-wrap';
  box.textContent = lines.join('\n');
  $('bk-apply-row').style.display = '';
  $('bk-pw').disabled = !f.has_password;
}
async function bkCheckFile() {
  const f = $('bk-file').files && $('bk-file').files[0];
  if (!f) { popup('Choose a backup file first', 'warn'); return; }
  let data;
  try { data = JSON.parse(await f.text()); } catch (e) { popup('That file is not valid JSON', 'err'); return; }
  bkPreview({source: 'file', data: data});
}
async function bkFind() {
  $('bk-found').textContent = 'Searching the USB drives...';
  const res = await apiPost('/api/config/find-backups', {});
  const box = $('bk-found');
  if (!res.ok) { box.textContent = errText(res); return; }
  const frag = document.createDocumentFragment();
  (res.data.found || []).forEach(function(b) {
    const row = document.createElement('div');
    row.className = 'selfrow';
    const nm = document.createElement('span');
    nm.className = 'nm';
    nm.textContent = b.label + ': backup from ' + (b.hostname || '?') + ', ' + (b.date || '?') + ', v' + (b.version || '?');
    row.appendChild(nm);
    const go = document.createElement('button');
    go.textContent = 'Check';
    go.addEventListener('click', function() { $('bk-storage').checked = true; bkPreview({source: 'drive', uuid: b.uuid}); });
    row.appendChild(go);
    frag.appendChild(row);
  });
  if (!(res.data.found || []).length) frag.appendChild(document.createTextNode('No backup found on the USB drives.'));
  box.replaceChildren(frag);
}
async function bkApply() {
  if (!_bk) return;
  const res = await apiPost('/api/config/restore', Object.assign({confirm: $('bk-confirm').value.trim(),
    restore_storage: $('bk-storage').checked, restore_password: $('bk-pw').checked}, _bk));
  $('bk-confirm').value = '';
  $('bk-apply').disabled = true;
  if (!res.ok) { popup(errText(res), 'err'); return; }
  popup('Restored ' + res.data.changes + ' setting(s)' + (res.data.restart_required ? '; restart to use the new port' : ''), 'ok');
  $('bk-apply-row').style.display = 'none';
  $('bk-preview').textContent = '';
  pollKeep();
  loadConfig();
  loadStorage();
}

function copyLog() {
  const lines = _logAll.filter(logPass).map(function(e) { return '[' + e.ts + '] ' + e.level + ' ' + e.msg; });
  if (!lines.length) { toast('No log lines to copy.', 'info'); return; }
  copyText(lines.join('\n') + '\n', 'Copied ' + lines.length + ' log line(s)', 'log');
}

let _pollStreamsBusy = false;
async function pollStreams() {
  if (_pollStreamsBusy || document.hidden) return;
  const kinds = Object.keys(_M).filter(function(k) { return _M[k].playing; });
  if (!kinds.length) return;
  _pollStreamsBusy = true;
  try {
    const r = await fetch('/api/streams');
    const d = await r.json();
    kinds.forEach(function(k) {
      const b = $('sbadge-' + k);
      if (!b) return;
      const mine = d.streams.filter(function(s) { return s.kind === k && s.id === _M[k].playing; });
      const stalled = mine.filter(function(s) { return s.stalled; });
      const media = k === 'audio' ? $('mp-audio') : document.querySelector('#player-' + k + ' video');
      if (stalled.length) {
        b.textContent = 'Paused: closes in ' + fmtClock(Math.min.apply(null, stalled.map(function(s) { return s.remaining; })));
        b.style.display = '';
      } else if (!mine.length && media && media.paused && !media.ended && media.dataset.started) {
        b.textContent = 'Connection closed: press play to resume';
        b.style.display = '';
      } else {
        b.style.display = 'none';
      }
    });
  } catch (e) {}
  finally { _pollStreamsBusy = false; }
}

async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const d = await r.json();
    _cfgSnap = d;
    const c = d.config;
    $('cfg-auth_enabled').checked = !!c.auth_enabled;
    $('cfg-allow_write').checked = !!c.allow_write;
    $('cfg-allow_update').checked = !!c.allow_update;
    $('cfg-side-left').checked = c.tab_side !== 'right';
    $('cfg-side-right').checked = c.tab_side === 'right';
    ['port', 'library_root', 'max_streams', 'max_upload_mb'].forEach(function(k) {
      $('cfg-' + k).value = c[k];
    });
    $('cfg-extra_roots').value = (c.extra_roots || []).join('\n');
    $('cfg-notify_url').value = c.notify_url || '';
    $('cfg-notify_level').value = c.notify_level || 'all';
    $('cfg-heartbeat_url').value = c.heartbeat_url || '';
    $('cfg-heartbeat_min').value = c.heartbeat_min || 5;
    $('cfg-auto_import').checked = !!c.auto_import;
    $('cfg-log_file').checked = !!c.log_file;
    $('bk-find-row').style.display = c.usb_uuid ? 'none' : '';
    $('cfg-path').textContent = d.config_path;
    $('cfg-restart-banner').style.display = d.restart_required ? 'block' : 'none';
    $('cfg-restart').style.display = (d.restart_required && d.restart_possible) ? '' : 'none';
    $('cfg-pw-cur-wrap').style.display = d.password_set ? '' : 'none';
    $('cfg-pw-clear').style.display = d.password_set ? '' : 'none';
    $('cfg-pw-state').textContent =
      d.password_set ? 'A Pibrary password is set.' : 'No Pibrary password set (login uses the root account password).';
    $('noauth-banner').style.display = c.auth_enabled ? 'none' : '';
    _authOn = !!c.auth_enabled;
    applySide(c.tab_side);
    cfgApplyDeps();
    _cfgBase = JSON.stringify(cfgValues());
    cfgSetDirty();
  } catch (e) {}
}
async function saveConfig() {
  const res = await apiPost('/api/config', cfgValues());
  if (res.ok) {
    popup(res.data.changed && res.data.changed.length ? 'Saved' : 'No changes', 'ok');
    pollKeep();
    await loadConfig();
    loadStorage();
    loadSelf();
    pollLog();
  } else {
    const emsg = entryError(res.data.error || ('Save failed (' + res.status + ')'));
    popup(emsg, 'err');
    const en = /^Entry (\d+)/.exec(emsg);
    if (en) openEntry(parseInt(en[1], 10));
  }
}
async function restartService() {
  const res = await apiPost('/api/restart', {});
  if (res.ok && res.data.port_change) {
    // the new port must be confirmed from a page on it, or the old port comes back by itself
    const url = location.protocol + '//' + location.hostname + ':' + res.data.new_port + '/';
    const b = $('cfg-restart-banner');
    b.style.display = 'block';
    b.replaceChildren();
    b.appendChild(document.createTextNode('Restarting on port ' + res.data.new_port + '. Within ' +
      Math.round(res.data.keep_sec / 60) + ' minutes open '));
    const a = document.createElement('a');
    a.href = url;
    a.textContent = url;
    b.appendChild(a);
    b.appendChild(document.createTextNode(' and press Keep there, or port ' + location.port +
      ' comes back automatically.'));
    popup('Restarting on the new port: open ' + url + ' and press Keep', 'warn');
    return;
  }
  popup(res.ok ? 'Restarting; reload in a few seconds' : (res.data.error || 'Restart failed'),
        res.ok ? 'warn' : 'err');
}

// ---- safe changes: Keep / Undo banner for changes that could cut off remote access
let _keepAt = 0;
let _keepItems = [];
let _pollKeepBusy = false;
async function pollKeep() {
  if (!_appStarted || _pollKeepBusy) return;
  _pollKeepBusy = true;
  try {
    const r = await fetch('/api/keep');
    if (r.ok) {
      const d = await r.json();
      const before = JSON.stringify(_keepItems.map(function(k) { return k.kind; }));
      _keepItems = d.pending || [];
      _keepAt = Date.now();
      if (before !== JSON.stringify(_keepItems.map(function(k) { return k.kind; }))) renderKeep();
      else tickKeep();
    }
  } catch (e) {}
  finally { _pollKeepBusy = false; }
}
function renderKeep() {
  const box = $('keepbar');
  const frag = document.createDocumentFragment();
  _keepItems.forEach(function(k) {
    const b = document.createElement('div');
    b.className = 'banner banner-err keepitem';
    b.dataset.kind = k.kind;
    const t = document.createElement('span');
    t.className = 'keeptext';
    b.appendChild(t);
    let pw = null;
    if (k.needs_password) {
      pw = document.createElement('input');
      pw.type = 'password';
      pw.placeholder = 'Password';
      pw.autocomplete = 'current-password';
      pw.style.maxWidth = '10rem';
      b.appendChild(pw);
    }
    const keep = document.createElement('button');
    keep.textContent = 'Keep';
    keep.className = 'primary';
    keep.addEventListener('click', async function() {
      const res = await apiPost('/api/keep', {kind: k.kind, password: pw ? pw.value : ''});
      popup(res.ok ? 'Kept' : (res.data.error || 'Failed'), res.ok ? 'ok' : 'err');
      pollKeep();
    });
    b.appendChild(keep);
    const undo = document.createElement('button');
    undo.textContent = 'Undo now';
    undo.addEventListener('click', async function() {
      const res = await apiPost('/api/keep', {kind: k.kind, undo: true});
      popup(res.ok ? 'Undone' : (res.data.error || 'Failed'), res.ok ? 'warn' : 'err');
      pollKeep();
      if (k.kind === 'port') waitForRestart();
      else loadConfig();
    });
    b.appendChild(undo);
    frag.appendChild(b);
  });
  box.replaceChildren(frag);
  tickKeep();
}
function tickKeep() {
  const gone = (Date.now() - _keepAt) / 1000;
  document.querySelectorAll('#keepbar .keepitem').forEach(function(b) {
    const k = _keepItems.find(function(x) { return x.kind === b.dataset.kind; });
    if (!k) return;
    const left = Math.max(0, k.remaining - gone);
    b.querySelector('.keeptext').textContent = k.text + '. Press Keep within ' + fmtClock(left) +
      (k.needs_password ? ' (enter the password)' : '') + ', or it is undone automatically.';
  });
}

function pwFields() {
  return {
    cur: document.getElementById('cfg-pw-cur'),
    nw: document.getElementById('cfg-pw-new'),
    cf: document.getElementById('cfg-pw-confirm'),
  };
}
function pwReset() {
  const f = pwFields();
  f.cur.value = ''; f.nw.value = ''; f.cf.value = '';
}
async function setPassword() {
  const f = pwFields();
  const res = await apiPost('/api/password', {current: f.cur.value, new: f.nw.value, confirm: f.cf.value});
  if (res.ok) { popup('Password set', 'ok'); pwReset(); pollKeep(); await loadConfig(); pollLog(); }
  else popup(res.data.error || ('Failed (' + res.status + ')'), 'err');
}
async function clearPassword() {
  if (!confirm('Clear the Pibrary password?')) return;
  const f = pwFields();
  const res = await apiPost('/api/password', {current: f.cur.value, clear: true});
  if (res.ok) { popup('Password cleared', 'ok'); pwReset(); pollKeep(); await loadConfig(); pollLog(); }
  else popup(res.data.error || ('Failed (' + res.status + ')'), 'err');
}

// ---- software update (upload, stage, install)
let _selfBusy = false;
function selfMsg(t) { document.getElementById('self-msg').textContent = t; }

async function loadSelf() {
  try {
    const r = await fetch('/api/self/list');
    const d = await r.json();
    document.getElementById('self-state').textContent = 'Running v' + d.running + '. ' +
      (d.allowed ? ('Newest ' + d.keep + ' staged files are kept in ' + d.dir + '.' +
                    (d.can_install ? '' : ' Install is unavailable: not running as a root systemd service.'))
                 : (d.reason || ''));
    document.getElementById('self-file').disabled = !d.allowed || _selfBusy;
    document.getElementById('self-up').disabled = !d.allowed || _selfBusy;
    const box = document.getElementById('self-list');
    box.replaceChildren();
    d.items.forEach(function(it) {
      const row = document.createElement('div');
      row.className = 'selfrow';
      const nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = it.name + (it.version ? '  (v' + it.version + ')' : '');
      row.appendChild(nm);
      const b = document.createElement('span');
      b.className = 'warnb' + (it.cmp === 'newer' ? ' ok' : '');
      b.textContent = it.cmp === 'same' ? 'same as running' : it.cmp;
      row.appendChild(b);
      const dt = document.createElement('span');
      dt.className = 'dt';
      dt.textContent = fmtDate(it.mtime);
      row.appendChild(dt);
      const sz = document.createElement('span');
      sz.className = 'sz';
      sz.textContent = fmtBytes(it.size);
      row.appendChild(sz);
      const inst = document.createElement('button');
      inst.textContent = 'Install';
      inst.className = 'inst-btn';
      inst.dataset.can = d.can_install ? '1' : '0';
      inst.disabled = !d.can_install || _selfBusy || _cfgDirty;
      inst.addEventListener('click', function() { selfInstall(it); });
      row.appendChild(inst);
      const del = document.createElement('button');
      del.textContent = 'Delete';
      del.disabled = _selfBusy;
      del.addEventListener('click', function() { selfDelete(it); });
      row.appendChild(del);
      box.appendChild(row);
    });
    if (d.allowed && !d.items.length) {
      const e = document.createElement('div');
      e.className = 'small muted';
      e.textContent = 'Nothing staged.';
      box.appendChild(e);
    }
  } catch (e) {}
}

function selfUpload() {
  const input = document.getElementById('self-file');
  const f = input.files && input.files[0];
  if (!f) { selfMsg('Choose a file first.'); return; }
  if (!/\.py$/i.test(f.name)) { selfMsg('Only .py files are accepted.'); return; }
  if (f.size > 5 * 1024 * 1024) { selfMsg('File too large (limit 5 MB).'); return; }
  let force = false;
  if (!/^pibrary.*\.py$/i.test(f.name)) {
    if (!confirm(f.name + " doesn't look like a Pibrary file (expected Pibrary*.py). Stage it anyway?")) return;
    force = true;
  }
  _selfBusy = true;
  document.getElementById('self-up').disabled = true;
  const bar = document.getElementById('self-bar');
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/self/upload?name=' + encodeURIComponent(f.name) + '&force=' + (force ? 1 : 0));
  xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
  xhr.setRequestHeader('Content-Type', 'application/octet-stream');
  function finish(text) {
    _selfBusy = false;
    bar.style.width = '0';
    input.value = '';
    selfMsg(text);
    loadSelf();
  }
  xhr.upload.onprogress = function(e) {
    if (e.lengthComputable) bar.style.width = (e.loaded / e.total * 100) + '%';
  };
  xhr.onload = function() {
    let d = {};
    try { d = JSON.parse(xhr.responseText); } catch (e) {}
    if (xhr.status === 401) { _onAuthLost(); return; }
    finish(xhr.status === 200 ? (d.message || 'Staged.') : (d.error || ('HTTP ' + xhr.status)));
  };
  xhr.onerror = function() { finish('Network error'); };
  xhr.send(f);
}

async function selfInstall(it) {
  const msg = it.cmp === 'newer'
    ? ('Install ' + it.name + '? Pibrary will restart.')
    : ('This is ' + (it.cmp === 'same' ? 'the same version as' : 'not newer than') +
       ' the running version. Install ' + it.name + ' anyway? Pibrary will restart.');
  const pw = $('self-pw').value;
  if (!pw) { selfMsg('Enter your password above Install first.'); $('self-pw').focus(); return; }
  if (!confirm(msg)) return;
  const res = await apiPost('/api/self/install', {name: it.name, sha: it.sha, confirm: true, password: pw});
  $('self-pw').value = '';
  if (res.ok) {
    selfMsg('Installing... watch the log. This page reloads when Pibrary is back.');
    waitForRestart();
  } else {
    selfMsg(res.data.error || ('Install failed (' + res.status + ')'));
  }
}

async function selfDelete(it) {
  if (!confirm('Delete staged file ' + it.name + '?')) return;
  const res = await apiPost('/api/self/delete', {name: it.name});
  selfMsg(res.ok ? 'Deleted ' + it.name : (res.data.error || 'Delete failed'));
  loadSelf();
}

function waitForRestart() {
  let sawDown = false;
  let tries = 0;
  const t = setInterval(async function() {
    tries++;
    try {
      const r = await _rawFetch('/api/health', {cache: 'no-store'});
      if (r.ok && sawDown) { clearInterval(t); location.reload(); }
    } catch (e) { sawDown = true; }
    if (tries > 90) {
      clearInterval(t);
      selfMsg(sawDown ? 'Pibrary did not come back within 3 minutes; reload the page or check the service.'
                      : 'No restart seen within 3 minutes; check the log for the install result.');
    }
  }, 2000);
}

// ---- storage (USB library drive) and import
let _jobTimer = null;
function jobText(j) {
  if (j.running && j.kind === 'format') {
    return 'Format: step ' + Math.min(j.files_done + 1, j.files_total) + ' of ' + j.files_total + ' - ' +
           j.current + (j.no_cancel ? ' (cannot be cancelled now)' : '');
  }
  if (j.running) {
    return (j.kind || 'job') + (j.phase === 'verifying' ? ' (verifying checksums)' : '') + ': ' + j.files_done + '/' + j.files_total + ' files, ' +
           fmtBytes(j.bytes_done) + ' of ' + fmtBytes(j.bytes_total) + (j.current ? ' - ' + j.current : '');
  }
  let t = j.error ? j.error : (j.message || '');
  if (j.failed && j.failed.length) {
    t += ' ' + j.failed.slice(0, 3).join('; ') + (j.failed_total > 3 ? ' ...' : '');
  }
  return t;
}
function trackJob(barId, msgId, onDone) {
  if (_jobTimer) clearInterval(_jobTimer);
  async function tick() {
    try {
      const r = await fetch('/api/storage/job');
      const j = await r.json();
      const bar = document.getElementById(barId);
      const msg = document.getElementById(msgId);
      if (bar) bar.style.width = (j.bytes_total ? Math.min(100, j.bytes_done / j.bytes_total * 100)
                                                : (j.running ? 0 : (j.done ? 100 : 0))) + '%';
      if (msg) msg.textContent = jobText(j);
      const cb = document.getElementById('stor-cancel');
      if (cb) cb.disabled = !j.running || !!j.no_cancel;
      if (!j.running) {
        clearInterval(_jobTimer);
        _jobTimer = null;
        if (onDone) onDone(j);
      }
    } catch (e) {}
  }
  tick();
  _jobTimer = setInterval(tick, 1000);
}
function storMsg(t) { document.getElementById('stor-msg').textContent = t; }
function errText(res) {
  return (res.data.error || ('Failed (' + res.status + ')')) +
         (res.data.problems ? ': ' + res.data.problems.slice(0, 5).join('; ') : '');
}
async function loadStorage() {
  try {
    const r = await fetch('/api/storage/list');
    const d = await r.json();
    const L = d.library;
    document.getElementById('stor-state').textContent =
      'Library: ' + (L.mode === 'usb' ? 'USB drive (' + L.state + ')' : 'SD card') + ' at ' + L.root +
      (L.free !== null ? ' | ' + fmtBytes(L.free) + ' free of ' + fmtBytes(L.total) : '') +
      (L.fstype ? ' | ' + L.fstype : '') + (d.can_manage ? '' : ' | ' + d.reason) +
      (L.fault ? ' | DRIVE ERROR: ' + L.fault + (L.gave_up
        ? '. Auto-remount stopped: use a powered hub / check the cable, then replug the drive or press Mount.'
        : '. Unmounted; it is remounted automatically when it answers again.') : '');
    const busy = !!d.job.running;
    const box = document.getElementById('stor-drives');
    box.replaceChildren();
    d.drives.forEach(function(dr) {
      const row = document.createElement('div');
      row.className = 'selfrow';
      const nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = (dr.label || dr.uuid) + (dr.fstype ? '  ' + dr.fstype : '') +
                       (dr.size ? '  ' + fmtBytes(dr.size) : '') + (dr.note ? '  (' + dr.note + ')' : '');
      row.appendChild(nm);
      const b = document.createElement('span');
      b.className = 'warnb' + (dr.role === 'library' ? ' ok' : '');
      b.textContent = dr.role + (dr.mounted ? ', mounted' : (dr.ejected ? ', ejected' : ''));
      row.appendChild(b);
      function btn(text, fn, disabled) {
        const x = document.createElement('button');
        x.textContent = text;
        x.disabled = !d.can_manage || busy || !!disabled;
        x.addEventListener('click', fn);
        row.appendChild(x);
      }
      if (dr.role === 'candidate') {
        btn('Use this drive', function() { storUse(dr); });
        if (dr.eject) btn('Eject', function() { storEject(dr); });
        else btn('Import only', function() { storMount(dr); });
      } else if (dr.role === 'library' || dr.role === 'import') {
        if (dr.eject || dr.mounted) btn('Eject', function() { storEject(dr); });
        else btn('Mount', function() { storMount(dr); }, !dr.path);
        if (dr.role === 'import' && !dr.note) btn('Replace library with this drive', function() { storReplace(dr); });
      }
      box.appendChild(row);
    });
    _storMode = L.mode;
    const rs = d.replace_sources || {};
    $('rep-row').style.display = L.mode === 'usb' ? '' : 'none';
    $('rep-src-old').disabled = !rs.old;
    $('rep-src-sd').disabled = !rs.sd;
    const rcur = document.querySelector('input[name=rep-src]:checked');
    if (!rcur || rcur.disabled) $(rs.old ? 'rep-src-old' : 'rep-src-none').checked = true;
    renderDisks(d, busy);
    if (!d.drives.length) {
      const e = document.createElement('div');
      e.className = 'small muted';
      e.textContent = 'No USB drive detected. Use an OTG adapter; powered hub for hard disks.';
      box.appendChild(e);
    }
    document.getElementById('stor-sd').style.display = L.mode === 'usb' ? '' : 'none';
    document.getElementById('stor-purge').style.display = L.mode === 'usb' ? '' : 'none';
    document.getElementById('stor-sd').disabled = !d.can_manage || busy;
    document.getElementById('stor-purge').disabled = !d.can_manage || busy || !d.allow_write || L.state !== 'online';
    document.getElementById('stor-cancel').disabled = !busy || !!d.job.no_cancel;
    if (busy && !_jobTimer) trackJob('stor-bar', 'stor-msg', function() { loadStorage(); });
  } catch (e) {}
}
function afterJob() { loadStorage(); }

let _storMode = 'sd';
let _fmtDisk = null;
function partsText(x) {
  return (x.parts || []).map(function(p) {
    return p.path.split('/').pop() + (p.fstype ? ' ' + p.fstype : ' (no filesystem)') +
           (p.label ? ' "' + p.label + '"' : '') + (p.mountpoint ? ' at ' + p.mountpoint : '');
  }).join(', ');
}
function renderDisks(d, busy) {
  const box = $('stor-disks');
  box.replaceChildren();
  (d.disks || []).forEach(function(x) {
    const row = document.createElement('div');
    row.className = 'selfrow';
    const nm = document.createElement('span');
    nm.className = 'nm';
    nm.textContent = (x.model || x.name) + '  ' + fmtBytes(x.size) + '  ' + x.path + '  - ' + partsText(x) +
                     (x.why ? '  (' + x.why + ')' : '');
    row.appendChild(nm);
    const b = document.createElement('button');
    b.textContent = 'Format as ext4...';
    b.disabled = !d.can_manage || busy || !x.can_format;
    b.title = x.why || 'Erase this drive and create one ext4 partition';
    b.addEventListener('click', function() { fmtOpen(x); });
    row.appendChild(b);
    box.appendChild(row);
  });
  if (!(d.disks || []).length) {
    const e = document.createElement('div');
    e.className = 'small muted';
    e.textContent = 'No USB disk detected.';
    box.appendChild(e);
  }
}
function fmtOpen(x) {
  _fmtDisk = x;
  $('fmt-desc').textContent = 'Drive: ' + (x.model || x.name) + ', ' + fmtBytes(x.size) + ', ' + x.path +
                              '. On it now: ' + (partsText(x) || 'nothing recognised') + '.';
  $('fmt-label').value = 'PIBRARY';
  $('fmt-confirm').value = '';
  $('fmt-go').disabled = true;
  $('fmt-panel').style.display = '';
  $('fmt-confirm').focus();
}
function fmtClose() {
  _fmtDisk = null;
  $('fmt-panel').style.display = 'none';
}
async function fmtSubmit() {
  const x = _fmtDisk;
  if (!x || $('fmt-confirm').value.trim() !== 'FORMAT') return;
  const res = await apiPost('/api/storage/format', {disk: x.name, fp: x.fp, label: $('fmt-label').value.trim(),
                                                    confirm: $('fmt-confirm').value.trim()});
  fmtClose();
  if (res.ok && res.data.started) {
    storMsg('Formatting ' + (x.model || x.name) + '...');
    trackJob('stor-bar', 'stor-msg', function(j) {
      loadStorage();
      if (!j.error && j.result) {
        toast('Formatted. Next: ' + (_storMode === 'usb' ? '"Replace library with this drive"'
                                                         : '"Use this drive"') + ' in the drive list.', 'ok');
      }
    });
  } else { storMsg(errText(res)); loadStorage(); }
}
function repSource() {
  const r = document.querySelector('input[name=rep-src]:checked');
  return r ? r.value : 'none';
}
async function storReplace(dr) {
  const src = repSource();
  const what = src === 'old' ? 'Media is copied from the current library drive first.'
             : (src === 'sd' ? 'Media is copied from the SD card first.'
                             : 'Nothing is copied; the new drive is used as it is.');
  if (!confirm('Replace the library drive with ' + (dr.label || dr.uuid) + '?\n' + what +
               '\nThe old drive is unmounted afterwards; nothing on it is changed.')) return;
  const res = await apiPost('/api/storage/replace', {uuid: dr.uuid, source: src,
    overwrite: $('stor-overwrite').checked, verify: $('stor-verify').checked});
  if (res.ok && res.data.started) {
    storMsg('Copying ' + res.data.files + ' file(s) to the new drive...');
    trackJob('stor-bar', 'stor-msg', afterJob);
  } else if (res.ok) { storMsg(res.data.message || 'Library replaced.'); loadStorage(); }
  else { storMsg(errText(res)); loadStorage(); }
}
async function storUse(dr) {
  const copy = $('stor-copy').checked;
  if (!confirm('Use ' + (dr.label || dr.uuid) + ' as the library drive?' +
               (copy ? ' Existing media on the SD card will be copied to it first.' : ''))) return;
  const res = await apiPost('/api/storage/use', {uuid: dr.uuid, copy: copy,
    overwrite: $('stor-overwrite').checked, verify: $('stor-verify').checked});
  if (res.ok && res.data.started) {
    storMsg('Copying ' + res.data.files + ' file(s)...');
    trackJob('stor-bar', 'stor-msg', afterJob);
  } else if (res.ok) { storMsg('Library is now on the USB drive.'); loadStorage(); }
  else { storMsg(errText(res)); loadStorage(); }
}
async function storSd() {
  if (!confirm('Switch the library back to the SD card?')) return;
  const copyBack = confirm('Also copy the media from the USB drive to the SD card?\n' +
                           'OK = copy, Cancel = switch without copying.');
  const res = await apiPost('/api/storage/use-sd', {copy_back: copyBack,
    overwrite: $('stor-overwrite').checked, verify: $('stor-verify').checked});
  if (res.ok && res.data.started) { storMsg('Copying...'); trackJob('stor-bar', 'stor-msg', afterJob); }
  else if (res.ok) { storMsg('Library is back on the SD card.'); loadStorage(); }
  else { storMsg(errText(res)); loadStorage(); }
}
async function storEject(dr) {
  const res = await apiPost('/api/storage/eject', {uuid: dr.uuid});
  storMsg(res.ok ? 'Ejected; safe to unplug.' : errText(res));
  loadStorage();
}
async function storMount(dr) {
  const res = await apiPost('/api/storage/mount', {uuid: dr.uuid});
  storMsg(res.ok ? 'Mounted.' : errText(res));
  loadStorage();
}
async function storPurge() {
  if (!confirm('Delete the SD card originals that were copied to the USB drive?\n' +
               'Each file is verified by checksum first; only exact copies are deleted.')) return;
  const res = await apiPost('/api/storage/purge', {});
  if (res.ok && res.data.started) { storMsg('Verifying checksums...'); trackJob('stor-bar', 'stor-msg', afterJob); }
  else if (res.ok) storMsg('Deleted ' + res.data.deleted + ' file(s)' +
                           (res.data.kept ? '; kept ' + res.data.kept + ' that are not on the drive' : '') + '.');
  else storMsg(errText(res));
  loadStorage();
}
async function storCancel() { await apiPost('/api/storage/cancel', {}); }

function impMsg(kind, t) { document.getElementById('impmsg-' + kind).textContent = t; }
async function toggleImport(kind) {
  const p = document.getElementById('imp-' + kind);
  const open = p.style.display === 'none';
  p.style.display = open ? '' : 'none';
  if (open) loadImport(kind, true);
}
async function loadImport(kind, refresh) {
  try {
    const r = await fetch('/api/import/list?type=' + kind + '&refresh=' + (refresh ? 1 : 0));
    const d = await r.json();
    const st = _I[kind];
    st.items = d.items || [];
    st.meta = d;
    st.sel = new Set();
    document.getElementById('impinfo-' + kind).textContent =
      (d.drives && d.drives.length ? 'Import drives: ' + d.drives.join(', ')
                                   : 'No import drive mounted. Insert a second USB drive after choosing a library drive.') +
      (d.can_import ? '' : ' | ' + d.reason) + (d.truncated ? ' | list capped' : '');
    document.getElementById('impgo-' + kind).disabled = !d.can_import;
    renderImport(kind);
  } catch (e) {}
}
function renderImport(kind) {
  const st = _I[kind];
  const frag = document.createDocumentFragment();
  st.items.slice(0, RENDER_CAP).forEach(function(it) {
    const row = document.createElement('label');
    row.className = 'improw';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = st.sel.has(it.id);
    cb.addEventListener('change', function() {
      if (cb.checked) st.sel.add(it.id); else st.sel.delete(it.id);
    });
    const nm = document.createElement('span');
    nm.className = 'nm';
    nm.textContent = it.drive + ': ' + it.rel;
    const sz = document.createElement('span');
    sz.className = 'sz';
    sz.textContent = fmtBytes(it.size);
    row.appendChild(cb);
    row.appendChild(nm);
    row.appendChild(sz);
    frag.appendChild(row);
  });
  const box = document.getElementById('implist-' + kind);
  if (!st.items.length) {
    const e = document.createElement('div');
    e.className = 'small muted';
    e.textContent = 'No matching files on the import drives.';
    box.replaceChildren(e);
  } else box.replaceChildren(frag);
}
function impSelectAll(kind, on) {
  const st = _I[kind];
  st.sel = new Set();
  if (on) st.items.slice(0, Math.min(RENDER_CAP, (st.meta && st.meta.select_cap) || 500))
    .forEach(function(it) { st.sel.add(it.id); });
  renderImport(kind);
}
async function importSelected(kind) {
  const ids = Array.from(_I[kind].sel);
  if (!ids.length) { impMsg(kind, 'Select files first.'); return; }
  const res = await apiPost('/api/import/copy',
    {type: kind, ids: ids, overwrite: document.getElementById('impover-' + kind).checked});
  if (res.ok && res.data.started) {
    document.getElementById('impcancel-' + kind).disabled = false;
    impMsg(kind, 'Importing ' + res.data.files + ' file(s)...');
    $('impnote-' + kind).textContent = (res.data.problems && res.data.problems.length)
      ? 'Skipped: ' + res.data.problems.slice(0, 5).join('; ') : '';
    trackJob('impbar-' + kind, 'impmsg-' + kind, function() {
      document.getElementById('impcancel-' + kind).disabled = true;
      loadList(kind, true);
    });
  } else impMsg(kind, errText(res));
}

function fmtTime(s) {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), sec = ('0' + (s % 60)).slice(-2);
  return h ? h + ':' + ('0' + m).slice(-2) + ':' + sec : m + ':' + sec;
}

function castMedia(el) {
  if (_authOn) { toast('Cast devices cannot log in, so casting only works while login is off.', 'warn'); return; }
  if (el.remote && typeof el.remote.prompt === 'function') {
    el.remote.prompt().catch(function(e) { toast('No cast target: ' + (e && e.name), 'warn'); });
  } else if (typeof el.webkitShowPlaybackTargetPicker === 'function') el.webkitShowPlaybackTargetPicker();
}

// ---- resume positions (this browser only), keyed by kind:rel:size because ids shift with the roots
const POS_MIN_SEC = 180;
const POS_MAX = 2000;
let _pos = {};
try { _pos = JSON.parse(lsGet('pos') || '{}') || {}; } catch (e) { _pos = {}; }
function posKey(kind, it) { return kind + ':' + it.rel + ':' + it.size; }
function posSave() {
  const keys = Object.keys(_pos);
  if (keys.length > POS_MAX) {
    keys.sort(function(a, b) { return (_pos[b].ts || 0) - (_pos[a].ts || 0); });
    keys.slice(POS_MAX).forEach(function(k) { delete _pos[k]; });
  }
  lsSet('pos', JSON.stringify(_pos));
}
function posForget(key) {
  if (_pos[key]) {
    delete _pos[key];
    posSave();
    posMarkDirty(key, {del: true, ts: Date.now()});
    posSchedule(2000);
  }
}

// ---- sync with the library drive (shared by all browsers; newest ts wins, deletions are tombstones)
const POS_PUSH_MS = 30000;
const POS_BATCH = 200;
const POS_BEACON_BATCH = 40;
let _posSrv = {available: false, reason: '', count: null};
let _posDirty = {};
try { _posDirty = JSON.parse(lsGet('posdirty') || '{}') || {}; } catch (e) { _posDirty = {}; }
let _posPushTimer = null;
let _posPushAt = 0;
let _posSyncBusy = false;
function posDirtySave() {
  const keys = Object.keys(_posDirty);
  if (keys.length > POS_MAX * 2) {
    keys.sort(function(a, b) { return (_posDirty[b].ts || 0) - (_posDirty[a].ts || 0); });
    keys.slice(POS_MAX * 2).forEach(function(k) { delete _posDirty[k]; });
  }
  lsSet('posdirty', JSON.stringify(_posDirty));
}
function posMarkDirty(key, entry) {
  _posDirty[key] = entry;
  posDirtySave();
}
function posSchedule(ms) {
  if (!_posSrv.available) return;
  const at = Date.now() + ms;
  if (_posPushTimer && _posPushAt <= at) return;
  if (_posPushTimer) clearTimeout(_posPushTimer);
  _posPushAt = at;
  _posPushTimer = setTimeout(function() { _posPushTimer = null; posPush(false); }, ms);
}
async function posPush(leaving) {
  if (!_posSrv.available) return;
  const keys = Object.keys(_posDirty);
  if (!keys.length) return;
  const batch = {};
  keys.slice(0, leaving ? POS_BEACON_BATCH : POS_BATCH).forEach(function(k) { batch[k] = _posDirty[k]; });
  try {
    // keepalive lets the last save finish while the page is closing (sendBeacon cannot send the CSRF header)
    const r = await fetch('/api/positions', {
      method: 'POST', keepalive: !!leaving,
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
      body: JSON.stringify({positions: batch}),
    });
    if (leaving) return;
    const d = await r.json();
    if (r.ok && d.ok) {
      Object.keys(batch).forEach(function(k) { if (_posDirty[k] === batch[k]) delete _posDirty[k]; });
      posDirtySave();
      if (Object.keys(_posDirty).length) posSchedule(1000);
    } else if (d && d.available === false) {
      _posSrv = {available: false, reason: d.reason || '', count: null};
    }
  } catch (e) {}
}
async function posSync() {
  if (_posSyncBusy) return;
  _posSyncBusy = true;
  try {
    const r = await fetch('/api/positions', {cache: 'no-store'});
    if (!r.ok) return;
    const d = await r.json();
    _posSrv = {available: !!d.available, reason: d.reason || '', count: d.count === undefined ? null : d.count};
    if (!d.available) return;
    const srv = d.positions || {};
    let changed = false;
    Object.keys(srv).forEach(function(k) {
      const s = srv[k], l = _pos[k], dl = _posDirty[k];
      const mine = Math.max(l ? (l.ts || 0) : 0, dl ? (dl.ts || 0) : 0);
      if (!s || !(s.ts > mine)) return;
      if (s.del) { if (l) { delete _pos[k]; changed = true; } }
      else { _pos[k] = s; changed = true; }
      if (dl) delete _posDirty[k];
    });
    // anything this browser has that the drive lacks (or has older) goes up
    Object.keys(_pos).forEach(function(k) {
      const s = srv[k];
      if (!s || (_pos[k].ts || 0) > s.ts) _posDirty[k] = _pos[k];
    });
    if (changed) { posSave(); renderContinue('movie'); }
    posDirtySave();
    if (Object.keys(_posDirty).length) posSchedule(1000);
  } catch (e) {}
  finally { _posSyncBusy = false; }
}
function posSyncInit() {
  posSync();
  setInterval(posSync, 300000);
  document.addEventListener('visibilitychange', function() {
    if (document.hidden) posPush(true); else posSync();
  });
  window.addEventListener('pagehide', function() { posPush(true); });
}
function posAttach(el, kind, it) {
  // ready stays false until loadedmetadata has applied the resume seek (so t=0 never overwrites it)
  el._pp = {kind: kind, it: it, key: posKey(kind, it), last: 0, ready: false};
}
function posRecord(el, force) {
  const p = el._pp;
  if (!p || !p.ready) return;
  const d = el.duration;
  if (!isFinite(d) || d < POS_MIN_SEC) return;
  const now = Date.now();
  if (!force && now - p.last < 5000) return;
  p.last = now;
  const t = el.currentTime;
  if (t > d - Math.max(30, d * 0.05)) { posSetPlayed(p.key, p.kind, p.it, d); return; }
  if (t < 10) return;
  _pos[p.key] = {t: Math.floor(t), d: Math.floor(d), ts: now, kind: p.kind, id: p.it.id,
                 name: p.it.name, rel: p.it.rel, size: p.it.size};
  posSave();
  posMarkDirty(p.key, _pos[p.key]);
  posSchedule(force ? 2000 : POS_PUSH_MS);
}
function posSetPlayed(key, kind, it, d) {
  // finished (the last 5% / 30 s): a "played" marker replaces the resume position
  const cur = _pos[key];
  if (cur && cur.played) return;
  _pos[key] = {t: 0, d: Math.floor(d || 0), ts: Date.now(), kind: kind, id: it.id, name: it.name,
               rel: it.rel, size: it.size, played: true};
  posSave();
  posMarkDirty(key, _pos[key]);
  posSchedule(2000);
}
function posState(kind, it) {
  // -> 'played' | 'progress' | '' for a list item
  const e = _pos[kind + ':' + it.rel + ':' + it.size];
  return !e ? '' : (e.played ? 'played' : (e.t > 0 ? 'progress' : ''));
}
function posWire(el, onResume) {
  el.addEventListener('loadedmetadata', function() {
    const p = el._pp;
    if (!p) return;
    const s = _pos[p.key];
    if (s && !s.played && s.t > 0 && isFinite(el.duration) && s.t < el.duration - 30) {
      try { el.currentTime = s.t; } catch (e) {}
      if (onResume) onResume(s.t);
    }
    p.ready = true;
  });
  el.addEventListener('timeupdate', function() { posRecord(el, false); });
  el.addEventListener('pause', function() { posRecord(el, true); });
  el.addEventListener('ended', function() {
    const p = el._pp;
    if (p && isFinite(el.duration) && el.duration >= POS_MIN_SEC) posSetPlayed(p.key, p.kind, p.it, el.duration);
  });
}
function posFlushAll() {
  document.querySelectorAll('video, audio').forEach(function(el) { posRecord(el, true); });
}
function renderContinue(kind) {
  const box = $('cont-' + kind);
  if (!box) return;
  const list = kind !== 'movie' ? [] : Object.keys(_pos).map(function(k) { return _pos[k]; })
    .filter(function(e) { return e && e.kind === 'movie' && !e.played && e.t > 0; })
    .sort(function(a, b) { return (b.ts || 0) - (a.ts || 0); }).slice(0, 5);
  box.style.display = list.length ? '' : 'none';
  if (!list.length) { box.replaceChildren(); return; }
  const frag = document.createDocumentFragment();
  const h = document.createElement('div');
  h.className = 'small muted';
  h.textContent = 'Continue watching';
  frag.appendChild(h);
  list.forEach(function(e) {
    const row = document.createElement('div');
    row.className = 'crow';
    const nm = document.createElement('span');
    nm.className = 'nm';
    nm.textContent = e.rel;
    row.appendChild(nm);
    const pp = document.createElement('span');
    pp.className = 'pp';
    pp.textContent = fmtTime(e.t) + ' / ' + fmtTime(e.d);
    row.appendChild(pp);
    const go = document.createElement('button');
    go.textContent = 'Resume';
    go.addEventListener('click', function() { contOpen(kind, e); });
    row.appendChild(go);
    const x = document.createElement('button');
    x.textContent = 'Forget';
    x.addEventListener('click', function() { posForget(posKey(kind, e)); renderContinue(kind); });
    row.appendChild(x);
    frag.appendChild(row);
  });
  box.replaceChildren(frag);
}
async function contOpen(kind, e) {
  const st = _M[kind];
  await (st.loading || (st.meta ? null : loadList(kind, false)));
  const it = st.items.find(function(x) { return x.rel === e.rel && x.size === e.size; }) ||
             st.items.find(function(x) { return x.id === e.id; });
  if (!it) { toast('That file is no longer in the library.', 'warn'); return; }
  openById(kind, it.id);
}

// ---- Media Session (lock screen / headset keys)
let _msLast = 0;
function msOk() { return 'mediaSession' in navigator; }
function msMeta(it, kind) {
  if (!msOk()) return;
  try {
    const parts = it.rel.split('/');
    const meta = {title: it.name, artist: parts.length > 1 ? parts[parts.length - 2] : '', album: 'Pibrary'};
    if (it.art && kind) meta.artwork = [{src: location.origin + artUrl(kind, it.art), sizes: '512x512'}];
    navigator.mediaSession.metadata = new MediaMetadata(meta);
  } catch (e) {}
}
function artUrl(kind, art) { return '/api/lib/art?type=' + kind + '&id=' + encodeURIComponent(art); }
function artImg(kind, art, cls) {
  const im = document.createElement('img');
  im.className = cls || 'art';
  im.loading = 'lazy';
  im.alt = '';
  im.src = artUrl(kind, art);
  im.addEventListener('error', function() { im.remove(); });
  return im;
}
function msState(s) {
  if (!msOk()) return;
  try { navigator.mediaSession.playbackState = s; } catch (e) {}
}
function msPos(el) {
  if (!msOk() || typeof navigator.mediaSession.setPositionState !== 'function') return;
  const now = Date.now();
  if (now - _msLast < 1000) return;
  _msLast = now;
  const d = el.duration;
  if (!isFinite(d) || d <= 0) return;
  try {
    navigator.mediaSession.setPositionState({duration: d, playbackRate: el.playbackRate || 1,
                                             position: Math.min(Math.max(el.currentTime, 0), d)});
  } catch (e) {}
}
function movieVideo() { return document.querySelector('#player-movie video'); }
function activeMedia() {
  const v = movieVideo();
  if (v && !v.paused) return v;
  if (mpActive()) return $('mp-audio');
  return v;
}
function msInit() {
  if (!msOk()) return;
  function step(delta) {
    const v = movieVideo();
    if (v && !v.paused) stepItem('movie', delta);
    else if (delta > 0) qNext(false);
    else qPrev();
  }
  const h = {
    play: function() { const m = activeMedia(); if (m) m.play().catch(function() {}); },
    pause: function() { const m = activeMedia(); if (m) m.pause(); },
    previoustrack: function() { step(-1); },
    nexttrack: function() { step(1); },
    seekbackward: function(d) {
      const m = activeMedia();
      if (m) m.currentTime = Math.max(0, m.currentTime - ((d && d.seekOffset) || 10));
    },
    seekforward: function(d) {
      const m = activeMedia();
      if (m && isFinite(m.duration)) m.currentTime = Math.min(m.duration, m.currentTime + ((d && d.seekOffset) || 10));
    },
    seekto: function(d) {
      const m = activeMedia();
      if (m && d && typeof d.seekTime === 'number') m.currentTime = d.seekTime;
    },
  };
  Object.keys(h).forEach(function(k) {
    try { navigator.mediaSession.setActionHandler(k, h[k]); } catch (e) {}
  });
}

// ---- audio queue (saved in this browser)
const Q_MAX = 1000;
const _Q = {items: [], orig: null, pos: -1, shuffle: false, repeat: 'off'};
function qEntry(it) { return {id: it.id, rel: it.rel, name: it.name, size: it.size, art: it.art || null}; }
function qCur() { return _Q.pos >= 0 ? (_Q.items[_Q.pos] || null) : null; }
function qSave() {
  lsSet('queue', JSON.stringify({items: _Q.items, orig: _Q.orig, pos: _Q.pos,
                                 shuffle: _Q.shuffle, repeat: _Q.repeat}));
}
function qLoad() {
  try {
    const d = JSON.parse(lsGet('queue') || 'null');
    if (!d || !Array.isArray(d.items)) return;
    const ok = function(x) { return x && typeof x.id === 'string' && typeof x.rel === 'string'; };
    _Q.items = d.items.filter(ok).slice(0, Q_MAX);
    _Q.shuffle = !!d.shuffle && Array.isArray(d.orig);
    _Q.orig = _Q.shuffle ? d.orig.filter(ok).slice(0, Q_MAX) : null;
    _Q.repeat = ['off', 'all', 'one'].indexOf(d.repeat) >= 0 ? d.repeat : 'off';
    _Q.pos = (typeof d.pos === 'number' && d.pos >= 0 && d.pos < _Q.items.length) ? d.pos
           : (_Q.items.length ? 0 : -1);
  } catch (e) {}
}
function qShuffleApply() {
  // shuffle once; the current track stays first and the old order is kept in orig
  _Q.orig = _Q.items.slice();
  const cur = qCur();
  const rest = _Q.items.filter(function(x, i) { return i !== _Q.pos; });
  for (let i = rest.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const tmp = rest[i]; rest[i] = rest[j]; rest[j] = tmp;
  }
  _Q.items = cur ? [cur].concat(rest) : rest;
  _Q.pos = cur ? 0 : -1;
}
function qUnshuffle() {
  const cur = qCur();
  const ids = new Set(_Q.items.map(function(x) { return x.id; }));
  const back = (_Q.orig || []).filter(function(x) { return ids.has(x.id); });
  const seen = new Set(back.map(function(x) { return x.id; }));
  _Q.items.forEach(function(x) { if (!seen.has(x.id)) back.push(x); });
  _Q.items = back;
  _Q.orig = null;
  _Q.pos = cur ? _Q.items.findIndex(function(x) { return x.id === cur.id; }) : -1;
}
function qPlayList(list, idx) {
  _Q.items = list.map(qEntry);
  _Q.pos = idx;
  _Q.orig = null;
  if (_Q.shuffle) qShuffleApply();
  mpPlay(true);
}
function qAdd(it, next) {
  const cur = qCur();
  if (cur && cur.id === it.id) { toast('Already playing.', 'info'); return; }
  const i = _Q.items.findIndex(function(x) { return x.id === it.id; });
  if (i >= 0) { _Q.items.splice(i, 1); if (i < _Q.pos) _Q.pos--; }
  if (_Q.items.length >= Q_MAX) { toast('The queue is full (' + Q_MAX + ' tracks).', 'warn'); return; }
  const e = qEntry(it);
  if (next && _Q.pos >= 0) _Q.items.splice(_Q.pos + 1, 0, e); else _Q.items.push(e);
  if (_Q.orig) {
    _Q.orig = _Q.orig.filter(function(x) { return x.id !== it.id; });
    _Q.orig.push(e);
  }
  if (_Q.pos < 0) {
    _Q.pos = _Q.items.indexOf(e);
    mpPlay(true);
    return;
  }
  qSave();
  renderQueue();
  toast((next ? 'Plays next: ' : 'Added to queue: ') + it.name, 'ok');
}
function qRemove(i) {
  if (i === _Q.pos || i < 0 || i >= _Q.items.length) return;
  const e = _Q.items.splice(i, 1)[0];
  if (i < _Q.pos) _Q.pos--;
  if (_Q.orig) _Q.orig = _Q.orig.filter(function(x) { return x.id !== e.id; });
  qSave();
  renderQueue();
}
function qMove(i, d) {
  const j = i + d;
  if (i < 0 || j < 0 || i >= _Q.items.length || j >= _Q.items.length) return;
  const tmp = _Q.items[i]; _Q.items[i] = _Q.items[j]; _Q.items[j] = tmp;
  if (_Q.pos === i) _Q.pos = j; else if (_Q.pos === j) _Q.pos = i;
  qSave();
  renderQueue();
}
function qJump(i) {
  if (i < 0 || i >= _Q.items.length) return;
  _Q.pos = i;
  mpPlay(true);
}
function qClear() {
  const cur = qCur();
  _Q.items = cur ? [cur] : [];
  _Q.pos = cur ? 0 : -1;
  _Q.orig = (_Q.shuffle && cur) ? [cur] : null;
  qSave();
  renderQueue();
}
function qNext(auto) {
  const a = $('mp-audio');
  if (!_Q.items.length) return;
  if (auto && _sleep.mode === -1) { sleepClear(); toast('Sleep timer: stopped at the end of the track', 'info'); return; }
  if (auto && _Q.repeat === 'one') { a.currentTime = 0; a.play().catch(function() {}); return; }
  if (_Q.pos + 1 < _Q.items.length) _Q.pos++;
  else if (_Q.repeat === 'all') _Q.pos = 0;
  else { if (!auto) toast('End of the queue.', 'info'); return; }
  mpPlay(true);
}
function qPrev() {
  const a = $('mp-audio');
  if (a.currentTime > 3 || !_Q.items.length) { a.currentTime = 0; return; }
  if (_Q.pos > 0) _Q.pos--;
  else if (_Q.repeat === 'all') _Q.pos = _Q.items.length - 1;
  else { a.currentTime = 0; return; }
  mpPlay(true);
}

// ---- playback speed (remembered per browser, separately for audio and video)
const RATES = [0.75, 1, 1.25, 1.5, 1.75, 2];
function rateOf(kind) {
  const r = parseFloat(lsGet('rate.' + kind) || '1');
  return RATES.indexOf(r) >= 0 ? r : 1;
}
function applyRate(el, kind) {
  const r = rateOf(kind);
  try {
    el.defaultPlaybackRate = r;
    el.playbackRate = r;
    if ('preservesPitch' in el) el.preservesPitch = true;
  } catch (e) {}
}
function rateSelect(kind, el) {
  const s = document.createElement('select');
  s.title = 'Playback speed';
  s.className = 'ratesel';
  RATES.forEach(function(r) {
    const o = document.createElement('option');
    o.value = String(r);
    o.textContent = r + 'x';
    s.appendChild(o);
  });
  s.value = String(rateOf(kind));
  s.addEventListener('change', function() { lsSet('rate.' + kind, s.value); applyRate(el, kind); });
  return s;
}

// ---- sleep timer: Off -> 15 -> 30 -> 60 min -> end of track; fades out over 10 s, then pauses
const SLEEP_STEPS = [0, 15, 30, 60, -1];
const _sleep = {mode: 0, until: 0, fading: false};
function sleepClear() {
  _sleep.mode = 0;
  _sleep.until = 0;
  _sleep.fading = false;
  sleepLabels();
}
function sleepCycle() {
  const i = SLEEP_STEPS.indexOf(_sleep.mode);
  const next = SLEEP_STEPS[(i + 1) % SLEEP_STEPS.length];
  _sleep.mode = next;
  _sleep.until = next > 0 ? Date.now() + next * 60000 : 0;
  sleepLabels();
  toast(next === 0 ? 'Sleep timer off' : (next < 0 ? 'Sleep timer: at the end of this track'
                                                   : 'Sleep timer: ' + next + ' minutes'), 'info');
}
function sleepLabels() {
  const txt = _sleep.mode === 0 ? 'Sleep' : (_sleep.mode < 0 ? 'Sleep: end of track'
              : 'Sleep ' + fmtClock(Math.max(0, (_sleep.until - Date.now()) / 1000)));
  document.querySelectorAll('.sleepbtn').forEach(function(b) {
    b.textContent = txt;
    b.classList.toggle('on', _sleep.mode !== 0);
  });
}
function sleepTick() {
  if (_sleep.mode > 0) {
    sleepLabels();
    if (!_sleep.fading && Date.now() >= _sleep.until) {
      const m = activeMedia();
      if (!m || m.paused) { sleepClear(); return; }
      _sleep.fading = true;
      const v0 = m.volume;
      let i = 0;
      const t = setInterval(function() {
        i++;
        m.volume = Math.max(0, v0 * (1 - i / 20));
        if (i >= 20) {
          clearInterval(t);
          m.pause();
          m.volume = v0;
          sleepClear();
          toast('Sleep timer: paused', 'info');
        }
      }, 500);
    }
  }
}

// ---- mini-player
function mpActive() { return $('mini').style.display !== 'none'; }
function mpShow(on) {
  $('mini').style.display = on ? '' : 'none';
  document.body.classList.toggle('has-mini', !!on);
  if (!on) $('queuepanel').style.display = 'none';
}
function mpButtons() {
  $('mp-shuffle').textContent = _Q.shuffle ? 'Shuffle on' : 'Shuffle off';
  $('mp-repeat').textContent = 'Repeat ' + _Q.repeat;
  $('mp-play').textContent = $('mp-audio').paused ? 'Play' : 'Pause';
}
function mpPlay(autoplay) {
  const a = $('mp-audio');
  const it = qCur();
  if (!it) { mpClose(); return; }
  posRecord(a, true);
  posAttach(a, 'audio', it);
  $('mp-restart').style.display = 'none';
  $('sbadge-audio').style.display = 'none';
  delete a.dataset.started;
  a.preload = autoplay ? 'metadata' : 'none';
  a.src = '/api/lib/file?type=audio&id=' + encodeURIComponent(it.id);
  applyRate(a, 'audio');
  $('mp-title').textContent = it.rel;
  const ma = $('mp-art');
  if (it.art) { ma.src = artUrl('audio', it.art); ma.style.display = ''; }
  else { ma.removeAttribute('src'); ma.style.display = 'none'; }
  mpShow(true);
  if (autoplay) a.play().catch(function() {});
  msMeta(it, 'audio');
  _M.audio.playing = it.id;
  renderList('audio');
  renderQueue();
  mpButtons();
  qSave();
}
function mpClose() {
  const a = $('mp-audio');
  posRecord(a, true);
  a._pp = null;
  a.pause();
  a.removeAttribute('src');
  a.load();
  _Q.items = [];
  _Q.orig = null;
  _Q.pos = -1;
  qSave();
  mpShow(false);
  _M.audio.playing = null;
  renderList('audio');
  if (msOk()) {
    try { navigator.mediaSession.metadata = null; navigator.mediaSession.playbackState = 'none'; } catch (e) {}
  }
}
function renderQueue() {
  if ($('queuepanel').style.display === 'none') return;
  const box = $('qp-list');
  const frag = document.createDocumentFragment();
  const n = _Q.items.length;
  _Q.items.forEach(function(e, i) {
    const row = document.createElement('div');
    row.className = 'qrow' + (i === _Q.pos ? ' cur' : '');
    row.dataset.i = i;
    const nm = document.createElement('span');
    nm.className = 'qn';
    nm.dataset.act = 'jump';
    nm.title = e.rel;
    nm.textContent = (i + 1) + '. ' + e.name;
    row.appendChild(nm);
    [['Up', 'up', i === 0], ['Down', 'down', i === n - 1], ['Remove', 'rm', i === _Q.pos]].forEach(function(b) {
      const x = document.createElement('button');
      x.textContent = b[0];
      x.dataset.act = b[1];
      x.disabled = b[2];
      row.appendChild(x);
    });
    frag.appendChild(row);
  });
  if (!n) {
    const e = document.createElement('div');
    e.className = 'small muted';
    e.textContent = 'The queue is empty.';
    frag.appendChild(e);
  }
  box.replaceChildren(frag);
  $('qp-info').textContent = n + (n === 1 ? ' track' : ' tracks') + (_Q.shuffle ? ', shuffled' : '') +
                             (_Q.repeat !== 'off' ? ', repeat ' + _Q.repeat : '');
}
function toggleQueue() {
  const p = $('queuepanel');
  const open = p.style.display === 'none';
  p.style.display = open ? '' : 'none';
  if (!open) return;
  renderQueue();
  const cur = $('qp-list').querySelector('.qrow.cur');
  if (cur) cur.scrollIntoView({block: 'nearest'});
}
function mpRestore() {
  qLoad();
  if (qCur()) mpPlay(false);
  else { _Q.items = []; _Q.orig = null; _Q.pos = -1; }
  mpButtons();
}
function mpInit() {
  const a = $('mp-audio');
  const rs = rateSelect('audio', a);
  rs.id = 'mp-rate';
  $('mp-rate').replaceWith(rs);
  $('mp-sleep').addEventListener('click', sleepCycle);
  setInterval(sleepTick, 1000);
  posWire(a, function(t) {
    $('mp-restart').style.display = '';
    toast('Resumed at ' + fmtTime(t), 'info');
  });
  a.addEventListener('ended', function() { qNext(true); });
  a.addEventListener('playing', function() { a.dataset.started = '1'; });
  a.addEventListener('play', function() {
    const v = movieVideo();
    if (v && !v.paused) v.pause();
    const it = qCur();
    if (it) msMeta(it, 'audio');
    mpButtons();
    msState('playing');
  });
  a.addEventListener('pause', function() { mpButtons(); msState('paused'); });
  a.addEventListener('timeupdate', function() { msPos(a); });
  a.addEventListener('error', function() {
    const it = qCur();
    if (it && a.getAttribute('src')) $('mp-title').textContent = it.rel + ' (could not play: missing or unsupported)';
  });
  $('mp-play').addEventListener('click', function() {
    if (a.paused) a.play().catch(function() {}); else a.pause();
  });
  $('mp-prev').addEventListener('click', qPrev);
  $('mp-next').addEventListener('click', function() { qNext(false); });
  $('mp-close').addEventListener('click', mpClose);
  $('mp-queue').addEventListener('click', toggleQueue);
  $('qp-close').addEventListener('click', toggleQueue);
  $('qp-clear').addEventListener('click', qClear);
  $('mp-shuffle').addEventListener('click', function() {
    _Q.shuffle = !_Q.shuffle;
    if (_Q.shuffle) qShuffleApply(); else qUnshuffle();
    qSave();
    mpButtons();
    renderQueue();
  });
  $('mp-repeat').addEventListener('click', function() {
    _Q.repeat = {off: 'all', all: 'one', one: 'off'}[_Q.repeat] || 'off';
    qSave();
    mpButtons();
    renderQueue();
  });
  $('mp-restart').addEventListener('click', function() {
    if (a._pp) posForget(a._pp.key);
    a.currentTime = 0;
    $('mp-restart').style.display = 'none';
  });
  $('mp-title').addEventListener('click', function() {
    const it = qCur();
    if (it) revealItem('audio', it.id);
  });
  $('qp-list').addEventListener('click', function(ev) {
    const b = ev.target.closest('[data-act]');
    const row = ev.target.closest('.qrow');
    if (!b || !row || b.disabled) return;
    const i = parseInt(row.dataset.i, 10);
    const act = b.dataset.act;
    if (act === 'jump') qJump(i);
    else if (act === 'up') qMove(i, -1);
    else if (act === 'down') qMove(i, 1);
    else if (act === 'rm') qRemove(i);
  });
  if ((a.remote && typeof a.remote.prompt === 'function') || typeof a.webkitShowPlaybackTargetPicker === 'function') {
    $('mp-cast').style.display = '';
    $('mp-cast').addEventListener('click', function() { castMedia(a); });
  }
  msInit();
  window.addEventListener('pagehide', posFlushAll);
  document.addEventListener('visibilitychange', function() { if (document.hidden) posFlushAll(); });
}

// ---- file management (library drive only: rename, move, new folder, trash)
function tabLabel(kind) { return (TAB_DEFS.find(function(t) { return t.id === kind; }) || {label: kind}).label; }
function edMarkPlayed(kind, on) {
  const st = _M[kind];
  const rels = Array.from(st.sel).filter(function(k) { return k[0] === 'f'; }).map(function(k) { return k.slice(2); });
  if (!rels.length) { toast('Select files first (folders are not marked).', 'info'); return; }
  const now = Date.now();
  let n = 0;
  rels.forEach(function(rel) {
    const it = st.items.find(function(x) { return x.rel === rel && x.root === 0; });
    if (!it) return;
    const key = kind + ':' + it.rel + ':' + it.size;
    if (on) {
      if (_pos[key] && _pos[key].played) return;
      _pos[key] = {t: 0, d: 0, ts: now, kind: kind, id: it.id, name: it.name, rel: it.rel, size: it.size, played: true};
      _posDirty[key] = _pos[key];
    } else {
      if (!_pos[key]) return;
      delete _pos[key];
      _posDirty[key] = {del: true, ts: now};
    }
    n++;
  });
  posSave();
  posDirtySave();
  posSchedule(2000);
  toast((on ? 'Marked ' : 'Unmarked ') + n + ' file(s)', 'ok');
  renderList(kind);
}
function updateEdBar(kind) {
  const st = _M[kind];
  const can = !!(st.meta && st.meta.can_edit);
  $('ed-' + kind).style.display = can ? '' : 'none';
  if (!can) { st.selMode = false; st.sel.clear(); }
  $('sel-' + kind).textContent = st.selMode ? 'Done' : 'Select';
  $('eds-' + kind).style.display = st.selMode ? '' : 'none';
  const n = st.sel.size;
  $('edn-' + kind).textContent = n + ' selected';
  $('edr-' + kind).disabled = n !== 1;
  $('edm-' + kind).disabled = !n;
  $('edd-' + kind).disabled = !n;
}
function selRels(kind) { return Array.from(_M[kind].sel).map(function(k) { return k.slice(2); }); }
function makeId(rel) {
  // same as the server's _make_id(0, rel): urlsafe base64 of "0:<rel>" without padding
  const b = new TextEncoder().encode('0:' + rel);
  let s = '';
  b.forEach(function(c) { s += String.fromCharCode(c); });
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function remapAfterMove(kind, pairs) {
  // pairs: [[old_rel, new_rel, is_dir]]; resume positions, the queue and the playing item follow
  if (!pairs || !pairs.length) return;
  function mapRel(rel) {
    for (let i = 0; i < pairs.length; i++) {
      const p = pairs[i];
      if (p[2] ? (rel === p[0] || rel.startsWith(p[0] + '/')) : rel === p[0]) return p[1] + rel.slice(p[0].length);
    }
    return null;
  }
  const now = Date.now();
  let posChanged = false;
  Object.keys(_pos).forEach(function(k) {
    const e = _pos[k];
    if (!e || e.kind !== kind) return;
    const nr = mapRel(e.rel);
    if (nr === null) return;
    const ne = Object.assign({}, e, {rel: nr, name: nr.split('/').pop(), id: makeId(nr), ts: now});
    delete _pos[k];
    posMarkDirty(k, {del: true, ts: now});
    const nk = kind + ':' + nr + ':' + e.size;
    _pos[nk] = ne;
    posMarkDirty(nk, ne);
    posChanged = true;
  });
  if (posChanged) { posSave(); posSchedule(2000); }
  if (kind === 'audio') {
    [_Q.items, _Q.orig || []].forEach(function(list) {
      list.forEach(function(e) {
        const nr = mapRel(e.rel);
        if (nr !== null) { e.rel = nr; e.name = nr.split('/').pop(); e.id = makeId(nr); }
      });
    });
    const cur = qCur();
    if (cur && mpActive()) { $('mp-title').textContent = cur.rel; _M.audio.playing = cur.id; }
    qSave();
    renderQueue();
  }
  ['movie', 'audio'].forEach(function(k) {
    const el = k === 'movie' ? movieVideo() : $('mp-audio');
    if (k === kind && el && el._pp) {
      const nr = mapRel(el._pp.it.rel);
      if (nr !== null) {
        el._pp.it = Object.assign({}, el._pp.it, {rel: nr, name: nr.split('/').pop(), id: makeId(nr)});
        el._pp.key = k + ':' + nr + ':' + el._pp.it.size;
        if (k === 'movie') _M.movie.playing = el._pp.it.id;
      }
    }
  });
}
function edReport(res, okText) {
  const p = (res.data && res.data.problems) || [];
  if (!res.ok) { popup(errText(res), 'err'); return; }
  if (p.length) popup(okText + ' Problems: ' + p.slice(0, 4).join('; ') + (p.length > 4 ? ' ...' : ''), 'warn');
  else toast(okText, 'ok');
}
async function edAfter(kind) {
  _M[kind].sel.clear();
  await loadList(kind, true);
  if ($('trash-' + kind).style.display !== 'none') loadTrash(kind);
}
async function edMkdir(kind) {
  const st = _M[kind];
  const where = upDirRel(kind) || (st.flat ? '' : '');
  const name = prompt('New folder in ' + tabLabel(kind) + (where ? '/' + where : '') + ':', '');
  if (!name || !name.trim()) return;
  const res = await apiPost('/api/lib/mkdir', {type: kind, dir: where, name: name.trim()});
  edReport(res, 'Created folder ' + name.trim());
  if (res.ok) await edAfter(kind);
}
async function edRename(kind) {
  const st = _M[kind];
  const key = Array.from(st.sel)[0];
  if (!key) return;
  const rel = key.slice(2);
  const cur = rel.split('/').pop();
  const name = prompt('Rename "' + cur + '" to:', cur);
  if (!name || !name.trim() || name.trim() === cur) return;
  const res = await apiPost('/api/lib/rename', {type: kind, rel: rel, name: name.trim()});
  if (res.ok) remapAfterMove(kind, res.data.moved);
  edReport(res, 'Renamed to ' + name.trim());
  if (res.ok) await edAfter(kind);
}
function edMove(kind) {
  const rels = selRels(kind);
  if (!rels.length) return;
  const dirsSel = Array.from(_M[kind].sel).filter(function(k) { return k[0] === 'd'; }).map(function(k) { return k.slice(2); });
  pickFolder(kind, dirsSel, async function(dest) {
    const res = await apiPost('/api/lib/move', {type: kind, items: rels, dest: dest});
    if (res.ok) remapAfterMove(kind, res.data.moved);
    edReport(res, 'Moved ' + ((res.data && res.data.moved) || []).length + ' item(s) to ' +
                  tabLabel(kind) + (dest ? '/' + dest : ''));
    if (res.ok) await edAfter(kind);
  });
}
async function edDelete(kind) {
  const rels = selRels(kind);
  if (!rels.length) return;
  const days = (_M[kind].meta && _M[kind].meta.trash_days) || 30;
  if (!confirm('Move ' + rels.length + ' item(s) to the trash?\nYou can restore them from Trash for ' + days +
               ' days. Empty folders are simply removed.')) return;
  const res = await apiPost('/api/lib/trash', {type: kind, items: rels});
  edReport(res, 'Moved ' + ((res.data && res.data.trashed) || 0) + ' item(s) to the trash' +
                ((res.data && res.data.removed) ? ', removed ' + res.data.removed + ' empty folder(s)' : '') + '.');
  if (res.ok) await edAfter(kind);
}

async function edDeleteFolder(kind, rel, count, size) {
  const days = (_M[kind].meta && _M[kind].meta.trash_days) || 30;
  const msg = count
    ? 'Move the folder "' + rel + '" and its ' + count + ' file(s) (' + fmtBytes(size) + ') to the trash?\n' +
      'Subfolders go with it. You can restore it from Trash for ' + days + ' days.'
    : 'Remove the folder "' + rel + '"? It has no media files' +
      ' (if it still holds other files, it goes to the trash instead).';
  if (!confirm(msg)) return;
  const res = await apiPost('/api/lib/trash', {type: kind, items: [rel]});
  const d = res.data || {};
  edReport(res, d.removed ? 'Empty folder removed.' : 'Folder "' + rel + '" moved to the trash.');
  if (res.ok) await edAfter(kind);
}

let _pick = null;
function pickFolder(kind, exclude, cb) {
  const dirs = [''].concat(((_M[kind].meta && _M[kind].meta.dirs) || []).filter(function(d) {
    return !exclude.some(function(x) { return d === x || d.startsWith(x + '/'); });
  }));
  _pick = {kind: kind, dirs: dirs, cb: cb};
  $('pk-title').textContent = 'Move ' + _M[kind].sel.size + ' item(s) to:';
  $('pk-filter').value = '';
  renderPicker();
  $('picker').style.display = '';
  $('pk-filter').focus();
}
function renderPicker() {
  if (!_pick) return;
  const q = $('pk-filter').value.trim().toLowerCase();
  const frag = document.createDocumentFragment();
  let n = 0;
  _pick.dirs.forEach(function(d) {
    if (q && d.toLowerCase().indexOf(q) < 0) return;
    if (n++ >= 500) return;
    const row = document.createElement('div');
    row.className = 'pkrow';
    row.dataset.dir = d;
    row.textContent = tabLabel(_pick.kind) + (d ? ' / ' + d.split('/').join(' / ') : '  (top level)');
    frag.appendChild(row);
  });
  if (!n) {
    const e = document.createElement('div');
    e.className = 'small muted';
    e.textContent = 'No matching folder. Create one with New folder first.';
    frag.appendChild(e);
  }
  $('pk-list').replaceChildren(frag);
}
function closePicker() { _pick = null; $('picker').style.display = 'none'; }

function toggleTrash(kind) {
  const box = $('trash-' + kind);
  const open = box.style.display === 'none';
  box.style.display = open ? '' : 'none';
  if (open) loadTrash(kind);
}
async function loadTrash(kind) {
  const box = $('trash-' + kind);
  try {
    const r = await fetch('/api/lib/trash/list?type=' + kind);
    const d = await r.json();
    const frag = document.createDocumentFragment();
    const items = d.items || [];
    const hdr = document.createElement('div');
    hdr.className = 'row';
    const t = document.createElement('span');
    t.className = 'etitle';
    t.textContent = 'Trash: ' + items.length + ' item(s)';
    hdr.appendChild(t);
    const note = document.createElement('span');
    note.className = 'small muted';
    note.textContent = r.ok ? 'emptied automatically after ' + (d.days || 30) + ' days' : (d.error || 'unavailable');
    hdr.appendChild(note);
    const sp = document.createElement('span');
    sp.style.flex = '1';
    hdr.appendChild(sp);
    if (items.length) {
      const all = document.createElement('button');
      all.textContent = 'Empty trash';
      all.dataset.act = 'emptyall';
      all.style.color = 'var(--red)';
      hdr.appendChild(all);
    }
    const close = document.createElement('button');
    close.textContent = 'Close';
    close.dataset.act = 'close';
    hdr.appendChild(close);
    frag.appendChild(hdr);
    items.forEach(function(e) {
      const row = document.createElement('div');
      row.className = 'selfrow';
      const nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = e.rel + (e.dir ? '/' : '');
      row.appendChild(nm);
      const dt = document.createElement('span');
      dt.className = 'dt';
      dt.textContent = 'deleted ' + fmtDate(e.ts);
      row.appendChild(dt);
      const sz = document.createElement('span');
      sz.className = 'sz';
      sz.textContent = fmtBytes(e.size);
      row.appendChild(sz);
      [['Restore', 'restore'], ['Delete now', 'purge']].forEach(function(b) {
        const x = document.createElement('button');
        x.textContent = b[0];
        x.dataset.act = b[1];
        x.dataset.id = e.id;
        row.appendChild(x);
      });
      frag.appendChild(row);
    });
    box.replaceChildren(frag);
  } catch (e) {}
}
// ---- duplicates: oldest copy kept by default, the others ticked (library drive copies only)
async function dupesScan(kind) {
  const res = await apiPost('/api/lib/dupes/scan', {type: kind});
  if (!res.ok) { $('dpmsg-' + kind).textContent = errText(res); return; }
  if (!res.data.started) { loadDupes(kind); return; }
  trackJob('dpbar-' + kind, 'dpmsg-' + kind, function() { loadDupes(kind); });
}
async function loadDupes(kind) {
  const box = $('dplist-' + kind);
  try {
    const r = await fetch('/api/lib/dupes?type=' + kind);
    const d = await r.json();
    const res = d.result;
    if (!res) {
      box.replaceChildren();
      $('dpmsg-' + kind).textContent = 'Press Search to look for identical files (it reads each candidate file).';
      return;
    }
    const frag = document.createDocumentFragment();
    if (!res.groups.length) {
      $('dpmsg-' + kind).textContent = 'No duplicates among ' + res.scanned + ' file(s) (searched ' + fmtDate(res.ts) + ').';
      box.replaceChildren();
      return;
    }
    let wasted = 0;
    res.groups.forEach(function(g, gi) {
      wasted += g[0].size * (g.length - 1);
      const h = document.createElement('div');
      h.className = 'small muted';
      h.style.marginTop = '.4rem';
      h.textContent = g.length + ' identical copies, ' + fmtBytes(g[0].size) + ' each';
      frag.appendChild(h);
      let kept = false;
      g.forEach(function(it) {
        const row = document.createElement('label');
        row.className = 'improw';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'dpcb';
        cb.dataset.rel = it.rel;
        cb.disabled = it.root !== 0;
        if (!cb.disabled && kept) cb.checked = true;
        if (!kept) kept = true;
        row.appendChild(cb);
        const nm = document.createElement('span');
        nm.className = 'nm';
        nm.textContent = it.rel + (it.root !== 0 ? '  (extra root, read-only)' : '');
        row.appendChild(nm);
        const dt = document.createElement('span');
        dt.className = 'sz';
        dt.textContent = fmtDate(it.mtime);
        row.appendChild(dt);
        frag.appendChild(row);
      });
    });
    const go = document.createElement('button');
    go.textContent = 'Move ticked to the trash';
    go.style.marginTop = '.5rem';
    go.addEventListener('click', function() { dupesTrash(kind); });
    frag.appendChild(go);
    $('dpmsg-' + kind).textContent = res.groups.length + ' group(s); ' + fmtBytes(wasted) + ' could be freed (searched ' +
      fmtDate(res.ts) + '). The oldest copy of each group is kept unless you change the ticks.';
    box.replaceChildren(frag);
  } catch (e) {}
}
async function dupesTrash(kind) {
  const rels = Array.from(document.querySelectorAll('#dplist-' + kind + ' input.dpcb:checked')).map(function(c) { return c.dataset.rel; });
  if (!rels.length) { toast('Nothing ticked.', 'info'); return; }
  if (!confirm('Move ' + rels.length + ' duplicate file(s) to the trash? You can restore them from Trash.')) return;
  const res = await apiPost('/api/lib/trash', {type: kind, items: rels});
  edReport(res, 'Moved ' + ((res.data && res.data.trashed) || 0) + ' duplicate(s) to the trash.');
  if (res.ok) {
    $('dplist-' + kind).replaceChildren();
    $('dpmsg-' + kind).textContent = 'Done. Search again to refresh the list.';
    await edAfter(kind);
  }
}

async function trashAct(kind, act, id) {
  if (act === 'close') { $('trash-' + kind).style.display = 'none'; return; }
  let res;
  if (act === 'restore') {
    res = await apiPost('/api/lib/trash/restore', {type: kind, ids: [id]});
    edReport(res, 'Restored ' + ((res.data && res.data.restored) || []).length + ' item(s).');
  } else if (act === 'purge') {
    if (!confirm('Permanently delete this item? This cannot be undone.')) return;
    res = await apiPost('/api/lib/trash/empty', {type: kind, ids: [id]});
    edReport(res, 'Deleted permanently.');
  } else if (act === 'emptyall') {
    if (!confirm('Permanently delete everything in the ' + tabLabel(kind) + ' trash? This cannot be undone.')) return;
    res = await apiPost('/api/lib/trash/empty', {type: kind, all: true});
    edReport(res, 'Trash emptied (' + ((res.data && res.data.deleted) || 0) + ' item(s)).');
  } else return;
  loadTrash(kind);
  if (act === 'restore') loadList(kind, true);
}

async function revealItem(kind, id) {
  // switch to the tab and show the file's folder; -> index in the view, or -1
  showTab(kind);
  const st = _M[kind];
  await (st.loading || (st.meta ? null : loadList(kind, false)));
  const it = st.items.find(function(x) { return x.id === id; });
  if (!it) { toast('That file is no longer in the list.', 'warn'); return -1; }
  $('flt-' + kind).value = '';
  lsSet('flt.' + kind, '');
  if (!st.flat) {
    const k = it.rel.lastIndexOf('/');
    st.dir = k > 0 ? it.rel.slice(0, k) : '';
    lsSet('cwd.' + kind, st.dir);
  }
  renderList(kind);
  return st.view.findIndex(function(x) { return x.id === id; });
}
async function openById(kind, id) {
  const idx = await revealItem(kind, id);
  if (idx >= 0 && kind !== 'pdf') openItem(kind, idx);
}

// ---- global search (client side, over the tab lists; the server caches each scan for 30s)
const GS_PER_KIND = 25;
const GS_MAX_AGE_MS = 60000;
let _gsSeq = 0;
let _gsTimer = null;
let _gsFirst = null;
function gsHide() { $('gs-results').style.display = 'none'; }
function gsSchedule() {
  if (_gsTimer) clearTimeout(_gsTimer);
  _gsTimer = setTimeout(gsRun, 150);
}
async function gsRun() {
  if (_gsTimer) { clearTimeout(_gsTimer); _gsTimer = null; }
  const q = $('gs-input').value.trim().toLowerCase();
  const seq = ++_gsSeq;
  const box = $('gs-results');
  _gsFirst = null;
  if (q.length < 2) { box.replaceChildren(); gsHide(); return; }
  const kinds = TAB_DEFS.filter(function(t) { return t.media; });
  await Promise.all(kinds.map(function(t) {
    const st = _M[t.id];
    return (!st.meta || Date.now() - (st.loadedAt || 0) > GS_MAX_AGE_MS) ? loadList(t.id, false) : null;
  }));
  if (seq !== _gsSeq) return;
  const words = q.split(/\s+/).filter(Boolean);
  const frag = document.createDocumentFragment();
  let first = null;
  kinds.forEach(function(t) {
    const hits = _M[t.id].items.filter(function(i) {
      const s = i.rel.toLowerCase();
      return words.every(function(w) { return s.indexOf(w) >= 0; });
    });
    if (!hits.length) return;
    const h = document.createElement('div');
    h.className = 'gshdr';
    h.textContent = t.label + ' (' + hits.length + ')';
    frag.appendChild(h);
    hits.slice(0, GS_PER_KIND).forEach(function(it) {
      const row = document.createElement('div');
      row.className = 'gsitem';
      row.dataset.kind = t.id;
      row.dataset.id = it.id;
      const n = document.createElement('span');
      n.className = 'gn';
      n.textContent = it.name;
      row.appendChild(n);
      const k = it.rel.lastIndexOf('/');
      if (k > 0) {
        const p = document.createElement('span');
        p.className = 'gp';
        p.textContent = it.rel.slice(0, k) + '/';
        row.appendChild(p);
      }
      if (!first) { first = row; row.classList.add('sel'); }
      frag.appendChild(row);
    });
    if (hits.length > GS_PER_KIND) {
      const more = document.createElement('div');
      more.className = 'gsnone';
      more.textContent = (hits.length - GS_PER_KIND) + ' more; add a word to narrow it down';
      frag.appendChild(more);
    }
  });
  if (!first) {
    const none = document.createElement('div');
    none.className = 'gsnone';
    none.textContent = 'No matches.';
    frag.appendChild(none);
  }
  _gsFirst = first;
  box.replaceChildren(frag);
  box.style.display = '';
}
async function gsOpen(kind, id) {
  gsHide();
  $('gs-input').blur();
  // PDFs open in a new window: do it before any await so the popup blocker sees the click
  if (kind === 'pdf') window.open('/api/lib/file?type=pdf&id=' + encodeURIComponent(id), '_blank', 'noopener');
  await openById(kind, id);
}

// ---- boot
function _startApp() {
  if (_appStarted) return;
  _appStarted = true;
  pollLog();
  mpRestore();
  posSyncInit();
  _tabActivated(_curTab);
  setInterval(function() { pollStatus(); }, 5000);
  setInterval(loadRecent, 60000);
  pollAlerts();
  setInterval(pollAlerts, 30000);
  pollKeep();
  setInterval(pollKeep, 5000);
  setInterval(tickKeep, 1000);
  setInterval(pollLog, 2000);
  setInterval(pollStreams, 2000);
}

async function _bootAfterLogin() {
  try {
    const r = await _rawFetch('/api/whoami');
    if (r.ok) {
      const d = await r.json();
      _authOn = !!d.auth_enabled;
      if (d.hostname) $('logo').title = 'Pibrary on ' + d.hostname;
      document.getElementById('logout-btn').style.display = d.auth_enabled ? 'inline-block' : 'none';
      placeNav();
      applySide(d.tab_side);
      $('noauth-banner').style.display = d.auth_enabled ? 'none' : '';
      hideLoginScreen();
      _startApp();
    } else if (r.status === 401) {
      showLoginScreen(_takeAuthMsg());
    }
  } catch (e) {
    showLoginScreen('Cannot reach server.');
  }
}

document.addEventListener('keydown', function(ev) {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const t = ev.target && ev.target.tagName;
  const typing = t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT';
  const kind = _curTab;
  if (ev.key === 'Escape' && $('viewpanel').style.display !== 'none') { $('viewpanel').style.display = 'none'; return; }
  if (ev.key === 'Escape' && $('queuepanel').style.display !== 'none') { $('queuepanel').style.display = 'none'; return; }
  if (ev.key === 'Escape' && $('keyhelp').style.display !== 'none') { toggleKeys(false); return; }
  if (ev.key === 'Escape' && $('picker').style.display !== 'none') { closePicker(); return; }
  if ($('picker').style.display !== 'none') return;
  const video = kind === 'movie' ? movieVideo() : null;
  const audio = mpActive() ? $('mp-audio') : null;
  if (ev.key === 'Escape') {
    if (!document.fullscreenElement && !typing && video) closePlayer('movie');
    return;
  }
  if (typing) return;
  if (ev.key === 's') { ev.preventDefault(); $('gs-input').focus(); return; }
  if (ev.key === '?') { ev.preventDefault(); toggleKeys(); return; }
  if (ev.key === 'q' && audio) { toggleQueue(); return; }
  const media = video || audio;
  if (ev.key === ' ' && media && t !== 'BUTTON' && t !== 'A') {
    ev.preventDefault();
    if (media.paused) media.play().catch(function() {}); else media.pause();
    return;
  }
  if ((ev.key === 'n' || ev.key === 'p') && media) {
    if (video) stepItem('movie', ev.key === 'n' ? 1 : -1);
    else if (ev.key === 'n') qNext(false);
    else qPrev();
    return;
  }
  if (!_M[kind]) return;
  if (ev.key === '/') { ev.preventDefault(); $('flt-' + kind).focus(); return; }
  if (ev.key === 'Backspace' && !_M[kind].flat && _M[kind].dir) { ev.preventDefault(); upDir(kind); return; }
});

buildTabs();
initFolds();
mpInit();
document.getElementById('cfg-save').addEventListener('click', saveConfig);
document.getElementById('cfg-path').textContent = '';
document.getElementById('cfg-reload').addEventListener('click', loadConfig);
document.getElementById('cfg-restart').addEventListener('click', restartService);
document.getElementById('cfg-pw-set').addEventListener('click', setPassword);
document.getElementById('cfg-pw-clear').addEventListener('click', clearPassword);
document.getElementById('self-up').addEventListener('click', selfUpload);
document.getElementById('stor-rescan').addEventListener('click', loadStorage);
document.getElementById('stor-sd').addEventListener('click', storSd);
document.getElementById('stor-purge').addEventListener('click', storPurge);
document.getElementById('stor-cancel').addEventListener('click', storCancel);
$('fmt-confirm').addEventListener('input', function() { $('fmt-go').disabled = this.value.trim() !== 'FORMAT'; });
$('fmt-go').addEventListener('click', fmtSubmit);
$('pk-close').addEventListener('click', closePicker);
$('pk-filter').addEventListener('input', renderPicker);
$('pk-list').addEventListener('click', function(ev) {
  const row = ev.target.closest('.pkrow');
  if (!row || !_pick) return;
  const cb = _pick.cb;
  const dest = row.dataset.dir;
  closePicker();
  cb(dest);
});
$('picker').addEventListener('click', function(ev) { if (ev.target === this) closePicker(); });
$('fmt-cancel').addEventListener('click', fmtClose);
['left', 'right'].forEach(function(s) {
  document.getElementById('cfg-side-' + s).addEventListener('change', function() {
    const other = document.getElementById('cfg-side-' + (s === 'left' ? 'right' : 'left'));
    if (this.checked) other.checked = false;
    else this.checked = true;
  });
});
['cfg-auth_enabled', 'cfg-allow_write', 'cfg-allow_update', 'cfg-port', 'cfg-library_root',
 'cfg-extra_roots', 'cfg-max_streams', 'cfg-max_upload_mb', 'cfg-side-left', 'cfg-side-right',
 'cfg-notify_url', 'cfg-notify_level', 'cfg-heartbeat_url', 'cfg-heartbeat_min', 'cfg-auto_import',
 'cfg-log_file'].forEach(function(id) {
  $(id).addEventListener('input', onCfgEdit);
  $(id).addEventListener('change', onCfgEdit);
});
$('view-btn').addEventListener('click', function() {
  const p = $('viewpanel');
  p.style.display = p.style.display === 'none' ? '' : 'none';
});
$('vp-close').addEventListener('click', function() { $('viewpanel').style.display = 'none'; });
$('vp-foldmem').checked = lsGet('foldmem') === '1';
$('vp-foldmem').addEventListener('change', function() {
  lsSet('foldmem', this.checked ? '1' : '0');
  toast(this.checked ? 'Open / closed cards are now remembered in this browser'
                     : 'Cards start hidden again on every page load', 'info');
});
function toggleKeys(on) {
  const k = $('keyhelp');
  k.style.display = (on === undefined ? k.style.display === 'none' : on) ? '' : 'none';
}
$('vp-keys').addEventListener('click', function() { $('viewpanel').style.display = 'none'; toggleKeys(true); });
$('kh-close').addEventListener('click', function() { toggleKeys(false); });
$('keyhelp').addEventListener('click', function(ev) { if (ev.target === this) toggleKeys(false); });
[['vp-theme', 'theme'], ['vp-size', 'size'], ['vp-density', 'density'], ['vp-mview', 'mview']].forEach(function(p) {
  $(p[0]).addEventListener('change', function() {
    lsSet(p[1], this.value);
    applyView();
    if (p[1] === 'mview') Object.keys(_M).forEach(function(k) { if (_M[k].meta) renderList(k); });
  });
});
['lg-info', 'lg-ok', 'lg-warn', 'lg-err'].forEach(function(id) { $(id).addEventListener('change', renderLog); });
$('lg-filter').addEventListener('input', renderLog);
$('lg-dl').addEventListener('click', downloadLog);
$('lg-copy').addEventListener('click', function(ev) { ev.stopPropagation(); copyLog(); });
$('cfg-notify-test').addEventListener('click', notifyTest);
$('bk-download').addEventListener('click', bkDownload);
$('bk-check').addEventListener('click', bkCheckFile);
$('bk-find').addEventListener('click', bkFind);
$('bk-apply').addEventListener('click', bkApply);
$('bk-confirm').addEventListener('input', function() { $('bk-apply').disabled = this.value.trim() !== 'RESTORE'; });
['bk-storage', 'bk-pw'].forEach(function(id) {
  $(id).addEventListener('change', function() { if (_bk) bkPreview(_bk); });
});
$('lg-file').addEventListener('click', function(ev) {
  ev.stopPropagation();
  const a = document.createElement('a');
  a.href = '/api/log/file';
  a.download = '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
});
$('sys-reboot-confirm').addEventListener('input', function() { $('sys-reboot').disabled = this.value.trim() !== 'REBOOT'; });
$('sys-reboot').addEventListener('click', async function() {
  const res = await apiPost('/api/system/reboot', {confirm: $('sys-reboot-confirm').value.trim()});
  $('sys-reboot-confirm').value = '';
  $('sys-reboot').disabled = true;
  if (res.ok) { popup('Rebooting the Pi; this page reconnects when it is back', 'warn'); waitForRestart(); }
  else popup(res.data.error || ('Failed (' + res.status + ')'), 'err');
});
$('lg-clear').addEventListener('click', function() { _logAll.length = 0; $('log').replaceChildren(); });
$('gs-input').addEventListener('input', gsSchedule);
$('gs-input').addEventListener('focus', function() { if (this.value.trim().length >= 2) gsRun(); });
$('gs-input').addEventListener('keydown', function(ev) {
  if (ev.key === 'Escape') {
    ev.stopPropagation();
    this.value = '';
    gsHide();
    this.blur();
  } else if (ev.key === 'Enter') {
    ev.preventDefault();
    (async function() {
      if (_gsTimer || !_gsFirst) await gsRun();
      if (_gsFirst) gsOpen(_gsFirst.dataset.kind, _gsFirst.dataset.id);
    })();
  }
});
$('gs-results').addEventListener('click', function(ev) {
  const r = ev.target.closest('.gsitem');
  if (r) gsOpen(r.dataset.kind, r.dataset.id);
});
document.addEventListener('click', function(ev) {
  if (!ev.target.closest('.gsearch')) gsHide();
});
applyView();
showTab((location.hash || '#' + (lsGet('tab') || 'status')).slice(1));
_bootAfterLogin();
"""

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Pibrary</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" type="image/png" href="/icon-192.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#0f1a2e">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Pibrary">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<script>(function(){try{var h=document.documentElement,g=function(k,d){return localStorage.getItem('pibrary.'+k)||d};var t=g('theme','dark');if(t==='auto'){t=(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark'}h.dataset.theme=t;h.dataset.size=g('size','m');h.dataset.density=g('density','comfortable');h.dataset.mview=g('mview','list')}catch(e){}})();</script>
<style>
%%CSS%%</style>
</head>
<body>
<header>
  <div class="hdr-left">
    <div class="logo" id="logo" title="Pibrary">Pibrary</div>
    <div class="logo-sub">Media library</div>
  </div>
  <div class="hdr-right">
    <span class="hdr-meta" title="%%DATE%%">v%%VERSION%% &middot; port %%PORT%%</span>
    <button id="view-btn" class="smallbtn">View</button>
    <button id="logout-btn" onclick="doLogout()">Log Out</button>
  </div>
</header>
<div id="login-screen">
  <div id="login-card">
    <h2>Pibrary Login</h2>
    <form onsubmit="_doLogin(event)">
      <input id="login-pw" type="password" autocomplete="current-password" placeholder="Password" required>
      <button id="login-btn" type="submit">Log In</button>
    </form>
    <div id="login-err"></div>
  </div>
</div>
<div id="viewpanel" class="viewpanel" style="display:none">
  <div class="etitle">View <span class="small muted">(this browser only)</span></div>
  <label><span>Theme</span><select id="vp-theme"><option value="dark">Dark</option><option value="light">Light</option><option value="auto">Auto</option></select></label>
  <label><span>Text size</span><select id="vp-size"><option value="s">Small</option><option value="m">Medium</option><option value="l">Large</option></select></label>
  <label><span>Density</span><select id="vp-density"><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
  <label><span>Media view</span><select id="vp-mview"><option value="list">List</option><option value="grid">Grid</option></select></label>
  <label><span>Remember open cards</span><input type="checkbox" id="vp-foldmem"></label>
  <button id="vp-keys">Keyboard shortcuts (?)</button>
  <button id="vp-close">Close</button>
</div>
<div id="toasts"></div>
<div id="keyhelp" class="pickov" style="display:none">
  <div class="pickbox">
    <div class="row"><span class="etitle">Keyboard shortcuts</span><span style="flex:1"></span>
      <button id="kh-close">Close</button></div>
    <div class="kv small">
      <div class="k">s</div><div class="v">search all media</div>
      <div class="k">/</div><div class="v">filter the current tab</div>
      <div class="k">space</div><div class="v">play / pause (the movie on Movies, else the mini-player)</div>
      <div class="k">n / p</div><div class="v">next / previous (movie list or audio queue)</div>
      <div class="k">q</div><div class="v">open the audio queue</div>
      <div class="k">Backspace</div><div class="v">up one folder</div>
      <div class="k">Esc</div><div class="v">close the movie, the queue, panels and this help</div>
      <div class="k">?</div><div class="v">this help</div>
    </div>
  </div>
</div>
<div id="picker" class="pickov" style="display:none">
  <div class="pickbox">
    <div class="row"><span class="etitle" id="pk-title">Move to</span><span style="flex:1"></span>
      <button id="pk-close">Cancel</button></div>
    <input type="text" id="pk-filter" placeholder="Filter folders" autocomplete="off">
    <div id="pk-list" class="pklist"></div>
  </div>
</div>
<div id="mini" class="mini" style="display:none">
  <div class="mini-row">
    <button id="mp-prev" title="Previous (p)">Prev</button>
    <button id="mp-play" title="Play / pause (space)">Play</button>
    <button id="mp-next" title="Next (n)">Next</button>
    <img id="mp-art" class="mp-art" alt="" style="display:none">
    <span id="mp-title" class="mp-title" title="Show in Audio"></span>
    <span id="sbadge-audio" class="warnb" style="display:none"></span>
    <button id="mp-restart" style="display:none">Start over</button>
    <button id="mp-shuffle" title="Shuffle the queue">Shuffle off</button>
    <button id="mp-repeat" title="Repeat mode">Repeat off</button>
    <select id="mp-rate" class="ratesel" title="Playback speed"></select>
    <button id="mp-sleep" class="sleepbtn" title="Sleep timer">Sleep</button>
    <button id="mp-queue" title="Queue (q)">Queue</button>
    <button id="mp-cast" style="display:none">Cast</button>
    <button id="mp-close" title="Stop and clear the queue">Close</button>
  </div>
  <audio id="mp-audio" controls preload="metadata"></audio>
</div>
<div id="queuepanel" class="queuepanel" style="display:none">
  <div class="row"><span class="etitle">Queue</span><span class="small muted" id="qp-info"></span>
    <span style="flex:1"></span><button id="qp-clear" title="Remove everything except the current track">Clear</button>
    <button id="qp-close">Close</button></div>
  <div id="qp-list" class="qplist"></div>
</div>
<div id="popup-overlay"><div id="popup-box" class="popup-box"></div></div>
<div class="wrap">
  <div class="layout" id="layout" data-side="left">
    <nav id="tabs"></nav>
    <div class="content" id="content">
      <div class="gsearch gsbar">
        <input type="text" id="gs-input" placeholder="Search all media (s)" autocomplete="off" enterkeyhint="search"
               aria-label="Search all media">
        <div id="gs-results" class="gsres" style="display:none"></div>
      </div>
      <div id="keepbar" class="alerts"></div>
      <div id="alerts" class="alerts"></div>
      <div id="noauth-banner" class="banner" style="display:none">Login is off: anyone who can reach this address can use Pibrary. Set a password (entry 1) and turn on Require login (entry 2) in Config.</div>

      <section id="tab-status" class="panel">
        <div class="hdr" id="st-new-hdr">Newest files</div>
        <div class="card" id="recent-card"><div id="recent-box" class="small muted">Loading&hellip;</div></div>
        <div class="hdr" id="st-sys-hdr">System</div>
        <div class="card"><div id="status-grid" class="small muted">Loading&hellip;</div></div>
      </section>

      <section id="tab-config" class="panel">
        <div id="cfg-firstrun" class="banner" style="display:none">First run: set a password (1), tick Require login (2), then press Save at the bottom. Entries 5 and 12 unlock once login is enabled and saved.</div>

        <div class="hdr">Access</div>
        <div class="card">
          <div class="entry" id="ent-1"><span class="num">1</span><div class="ebody">
            <div class="etitle">Password <span class="tag now">applies immediately</span></div>
            <div class="small muted" id="cfg-pw-state"></div>
            <label class="fld" id="cfg-pw-cur-wrap" style="display:none"><span>Current password</span>
              <input type="password" id="cfg-pw-cur" autocomplete="current-password"></label>
            <label class="fld"><span>New password (8 or more characters)</span>
              <input type="password" id="cfg-pw-new" autocomplete="new-password"></label>
            <label class="fld"><span>Confirm new password</span>
              <input type="password" id="cfg-pw-confirm" autocomplete="new-password"></label>
            <div class="row">
              <button id="cfg-pw-set">Set password</button>
              <button id="cfg-pw-clear" style="display:none">Clear password</button>
            </div>
            <div class="small muted">Stored as a scrypt hash in pibrary.auth next to the config file (mode 0600).
              SSH recovery: delete that file, or set auth_enabled = false in the config.</div>
          </div></div>
          <div class="entry" id="ent-2"><span class="num">2</span><div class="ebody">
            <label class="fld chk"><input type="checkbox" id="cfg-auth_enabled">
              <span>Require login <span class="tag save">saved with Save</span></span></label>
            <div class="small muted">Uses the Pibrary password from entry 1, or the root account password if none is set.</div>
          </div></div>
          <div class="entry" id="ent-3"><span class="num">3</span><div class="ebody">
            <label class="fld chk"><input type="checkbox" id="cfg-allow_write">
              <span>Allow uploads <span class="tag save">saved with Save</span></span></label>
            <div class="small muted">Needs entry 2. Also gates imports, file deletion and the SD-originals cleanup.</div>
          </div></div>
          <div class="entry" id="ent-4"><span class="num">4</span><div class="ebody">
            <label class="fld chk"><input type="checkbox" id="cfg-allow_update">
              <span>Allow software update <span class="tag save">saved with Save</span></span></label>
            <div class="small muted">Needs entry 2. An uploaded update runs as root.</div>
          </div></div>
        </div>

        <div class="hdr">Library location</div>
        <div class="card">
          <div class="entry" id="ent-5"><span class="num">5</span><div class="ebody">
            <div class="etitle">Library storage <span class="tag now">applies immediately</span></div>
            <div class="lock" id="lock-5" style="display:none">Locked: turn on entry 2 and Save first.</div>
            <div class="small muted" id="stor-state"></div>
            <div id="stor-drives"></div>
            <div class="row small" id="rep-row" style="display:none">
              <span>Replace library drive: copy media from</span>
              <label class="fld chk"><input type="radio" name="rep-src" id="rep-src-old" value="old"><span>Old drive</span></label>
              <label class="fld chk"><input type="radio" name="rep-src" id="rep-src-sd" value="sd"><span>SD card</span></label>
              <label class="fld chk"><input type="radio" name="rep-src" id="rep-src-none" value="none"><span>Nothing</span></label>
            </div>
            <label class="fld chk"><input type="checkbox" id="stor-copy" checked>
              <span>Copy existing media from the SD card when choosing a library drive</span></label>
            <label class="fld chk"><input type="checkbox" id="stor-overwrite">
              <span>Overwrite conflicts (files that already exist with different content)</span></label>
            <label class="fld chk"><input type="checkbox" id="stor-verify">
              <span>Verify copies with a checksum (slower)</span></label>
            <div class="row">
              <button id="stor-rescan">Rescan</button>
              <button id="stor-sd">Use SD card</button>
              <button id="stor-purge">Delete SD originals</button>
              <button id="stor-cancel" disabled>Cancel job</button>
            </div>
            <div class="prog"><div class="bar" id="stor-bar"></div></div>
            <div class="small" id="stor-msg"></div>
            <div class="etitle" style="margin-top:.4rem">Format a USB drive as ext4
              <span class="tag" style="color:var(--red);border-color:var(--red-dim)">erases it</span></div>
            <div id="stor-disks"></div>
            <div id="fmt-panel" class="card" style="display:none;border-color:var(--red-dim)">
              <div class="small" id="fmt-desc"></div>
              <div class="small" style="color:var(--red)">This erases everything on the drive. ext4 cannot be read
                by Windows or macOS without extra software.</div>
              <label class="fld"><span>Volume label (1-16 letters, digits, _ or -)</span>
                <input type="text" id="fmt-label" maxlength="16" value="PIBRARY" style="max-width:12rem"></label>
              <label class="fld"><span>Type FORMAT to confirm</span>
                <input type="text" id="fmt-confirm" autocomplete="off" style="max-width:12rem"></label>
              <div class="row"><button id="fmt-cancel">Cancel</button><span style="flex:1"></span>
                <button id="fmt-go" disabled style="color:var(--red);border-color:var(--red-dim)">Format</button></div>
            </div>
          </div></div>
          <div class="entry" id="ent-6"><span class="num">6</span><div class="ebody">
            <label class="fld"><span>Library root <span class="tag save">saved with Save</span></span>
              <input type="text" id="cfg-library_root"></label>
            <div class="small muted">movies/, audio/ and pdf/ live inside. Read-only while a USB library drive is in use (entry 5).</div>
          </div></div>
          <div class="entry" id="ent-7"><span class="num">7</span><div class="ebody">
            <label class="fld"><span>Extra roots, one per line <span class="tag save">saved with Save</span></span>
              <textarea id="cfg-extra_roots" rows="3"></textarea></label>
          </div></div>
        </div>

        <div class="hdr">Limits</div>
        <div class="card">
          <div class="entry" id="ent-8"><span class="num">8</span><div class="ebody">
            <label class="fld"><span>Max upload size (MB) <span class="tag save">saved with Save</span></span>
              <input type="number" id="cfg-max_upload_mb" min="1" max="102400"></label>
            <div class="small muted">FAT32 drives cap this at 4095 MB automatically.</div>
          </div></div>
          <div class="entry" id="ent-9"><span class="num">9</span><div class="ebody">
            <label class="fld"><span>Max concurrent streams <span class="tag save">saved with Save</span></span>
              <input type="number" id="cfg-max_streams" min="1" max="10"></label>
          </div></div>
        </div>

        <div class="hdr">Network and look</div>
        <div class="card">
          <div class="entry" id="ent-10"><span class="num">10</span><div class="ebody">
            <div id="cfg-restart-banner" class="banner" style="display:none">
              The saved port differs from the running port. Restart the service to apply it.</div>
            <label class="fld"><span>Port <span class="tag save">saved with Save</span></span>
              <input type="number" id="cfg-port" min="1" max="65535"></label>
            <div class="small muted">Reachable by IP address, this hostname and hostname.local. Other names
              (a DNS or VPN name) must be listed in allowed_hosts in the config file, then restart.</div>
          </div></div>
          <div class="entry" id="ent-11"><span class="num">11</span><div class="ebody">
            <div class="fld"><span>Tab side <span class="tag save">saved with Save</span></span>
              <div class="row">
                <label class="fld chk"><input type="checkbox" id="cfg-side-left"><span>L</span></label>
                <label class="fld chk"><input type="checkbox" id="cfg-side-right"><span>R</span></label>
              </div></div>
          </div></div>
        </div>

        <div class="hdr">Maintenance</div>
        <div class="card">
          <div class="entry" id="ent-12"><span class="num">12</span><div class="ebody">
            <div class="etitle">Software update <span class="tag now">applies immediately</span></div>
            <div class="lock" id="lock-12" style="display:none">Locked: turn on entries 2 and 4 and Save first.</div>
            <div class="small muted" id="self-state"></div>
            <div class="row"><input type="file" id="self-file" accept=".py">
              <button id="self-up">Upload &amp; stage</button></div>
            <div class="prog"><div class="bar" id="self-bar"></div></div>
            <div class="small" id="self-msg"></div>
            <label class="fld"><span>Password (asked again for every install)</span>
              <input type="password" id="self-pw" autocomplete="current-password" style="max-width:16rem"></label>
            <div id="self-list"></div>
            <div class="small muted">Install restarts Pibrary, so it is disabled while settings have unsaved changes.</div>
          </div></div>
        </div>

        <div class="hdr">Remote</div>
        <div class="card">
          <div class="entry" id="ent-13"><span class="num">13</span><div class="ebody">
            <label class="fld"><span>Notifications: ntfy address <span class="tag save">saved with Save</span></span>
              <input type="text" id="cfg-notify_url" placeholder="https://ntfy.sh/your-secret-topic" autocomplete="off"></label>
            <div class="row">
              <label class="fld chk"><span>Send</span>
                <select id="cfg-notify_level"><option value="all">everything (also starts, imports, updates)</option>
                  <option value="warn">warnings and problems</option><option value="err">problems only</option></select></label>
              <button id="cfg-notify-test">Send a test</button>
            </div>
            <div class="small muted">Install the free ntfy app on your phone and subscribe to a hard-to-guess topic name;
              put the same address here. Power dips, drive errors, low space, failed updates, finished imports and
              restarts are sent (at most once an hour per problem).</div>
          </div></div>
          <div class="entry" id="ent-14"><span class="num">14</span><div class="ebody">
            <label class="fld"><span>Heartbeat address <span class="tag save">saved with Save</span></span>
              <input type="text" id="cfg-heartbeat_url" placeholder="https://hc-ping.com/your-uuid" autocomplete="off"></label>
            <label class="fld"><span>Ping every (minutes)</span>
              <input type="number" id="cfg-heartbeat_min" min="1" max="60" style="max-width:7rem"></label>
            <div class="small muted">Pibrary calls this address regularly while it works. A service such as healthchecks.io
              alerts you when the pings stop (the Pi is off, hung or offline) - Pibrary cannot report that itself.</div>
          </div></div>
          <div class="entry" id="ent-15"><span class="num">15</span><div class="ebody">
            <label class="fld chk"><input type="checkbox" id="cfg-auto_import">
              <span>Auto-import drives with a PIBRARY-IMPORT folder <span class="tag save">saved with Save</span></span></label>
            <div class="small muted">Needs entry 2 and a USB library drive. Prepare a drive (exFAT) on a PC with a top-level
              folder PIBRARY-IMPORT containing Movies/, Audio/ and PDF/ (kept as they are) and/or loose files (sorted into
              &lt;tab&gt;/Imported/&lt;date&gt;/). A Pibrary*.py at its top is staged as an update (never installed by itself).
              On site just plug it in: the green activity LED blinks while copying, stays on when done (safe to unplug)
              and blinks fast on an error. The drive is never changed, existing files are never overwritten, files
              already imported are skipped, and you get a notification when it is finished.</div>
          </div></div>
          <div class="entry" id="ent-16"><span class="num">16</span><div class="ebody">
            <div class="etitle">Reboot the Pi <span class="tag now">applies immediately</span></div>
            <div class="row">
              <input type="text" id="sys-reboot-confirm" placeholder="type REBOOT" autocomplete="off" style="max-width:9rem">
              <button id="sys-reboot" disabled>Reboot</button>
            </div>
            <div class="small muted">Needs login. Takes about a minute; this page reconnects by itself. Changes to
              Require login, the password and the port must be confirmed with Keep (a banner at the top) within a few
              minutes, or they are undone - so a mistake cannot lock you out of a remote Pi.</div>
          </div></div>
          <div class="entry" id="ent-17"><span class="num">17</span><div class="ebody">
            <label class="fld chk"><input type="checkbox" id="cfg-log_file">
              <span>Keep a log file on the library drive <span class="tag save">saved with Save</span></span></label>
            <div class="small muted">&lt;library&gt;/.pibrary/logs/pibrary.log, 1 MB each, the newest 5 kept, written every 10 s
              and at shutdown. Only with a USB library drive (never on the SD card). "File" next to the log downloads it.</div>
          </div></div>
          <div class="entry" id="ent-18"><span class="num">18</span><div class="ebody">
            <div class="etitle">Backup and restore settings <span class="tag now">applies immediately</span></div>
            <div class="row">
              <button id="bk-download">Download backup</button>
              <label class="fld chk"><input type="checkbox" id="bk-withpw"><span>include the password (login must be on)</span></label>
            </div>
            <div class="row"><input type="file" id="bk-file" accept=".json,application/json">
              <button id="bk-check">Check file</button></div>
            <div class="row" id="bk-find-row"><button id="bk-find">Look for a backup on the USB drives</button>
              <span class="small muted">for a fresh SD card: every save also copies the settings to the library drive</span></div>
            <div id="bk-found"></div>
            <div id="bk-preview" class="small"></div>
            <div class="row" id="bk-apply-row" style="display:none">
              <label class="fld chk"><input type="checkbox" id="bk-storage"><span>also restore the library drive</span></label>
              <label class="fld chk"><input type="checkbox" id="bk-pw"><span>restore the password</span></label>
              <input type="text" id="bk-confirm" placeholder="type RESTORE" autocomplete="off" style="max-width:9rem">
              <button id="bk-apply" disabled>Restore</button>
            </div>
          </div></div>
        </div>

        <div class="hdr">Finish <span class="foldnote" id="cfg-dirty-hdr"></span></div>
        <div class="card">
          <div class="entry" id="ent-fin"><span class="num">19</span><div class="ebody">
            <div class="small muted">Config file: <span id="cfg-path"></span></div>
            <div class="row">
              <span class="small" id="cfg-dirty"></span>
              <button id="cfg-reload">Discard changes</button>
              <button id="cfg-restart" style="display:none">Restart now</button>
              <span style="flex:1;min-width:2rem"></span>
              <button id="cfg-save" class="primary" disabled>Save</button>
            </div>
          </div></div>
        </div>
      </section>

      <div class="hdr" id="log-hdr">Log <button id="lg-copy" class="foldextra" title="Copy the log lines that pass the filter">Copy</button>
        <button id="lg-file" class="foldextra" title="Download the log file kept on the library drive">File</button></div>
      <div class="row small" id="logbar">
        <label class="fld chk"><input type="checkbox" id="lg-info" checked><span>info</span></label>
        <label class="fld chk"><input type="checkbox" id="lg-ok" checked><span>ok</span></label>
        <label class="fld chk"><input type="checkbox" id="lg-warn" checked><span>warn</span></label>
        <label class="fld chk"><input type="checkbox" id="lg-err" checked><span>err</span></label>
        <input type="text" id="lg-filter" placeholder="Filter log" style="max-width:12rem">
        <button id="lg-dl">Download</button><button id="lg-clear">Clear view</button>
      </div>
      <div id="log"></div>
    </div>
  </div>
</div>
<script>
__JS__</script>
</body>
</html>
"""


def render_page():
    return (_HTML_TEMPLATE
            .replace("%%CSS%%", _CSS)
            .replace("__JS__", _JS)
            .replace("%%VERSION%%", VERSION)
            .replace("%%DATE%%", DATE_STR)
            .replace("%%PORT%%", str(PORT)))


MANIFEST = {
    "name": "Pibrary", "short_name": "Pibrary", "start_url": "/", "scope": "/",
    "display": "standalone", "background_color": "#0d1117", "theme_color": "#0f1a2e",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}
_ICON_SIZES = {"/icon-192.png": 192, "/icon-512.png": 512, "/apple-touch-icon.png": 180}
_icon_cache = {}
_icon_lock = threading.Lock()


def _png_rgb(width, height, rows):
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _icon_png(size):
    with _icon_lock:
        if size in _icon_cache:
            return _icon_cache[size]
        bg, fg, ring = bytes((0x0d, 0x11, 0x17)), bytes((0xff, 0xd0, 0x40)), bytes((0x2e, 0x40, 0x60))
        x0, x1 = int(size * 0.36), int(size * 0.70)
        y0, y1 = int(size * 0.30), int(size * 0.70)
        mid, half = (y0 + y1) / 2.0, (y1 - y0) / 2.0
        r_out, r_in = size * 0.40, size * 0.37
        cx = cy = size / 2.0
        rows = []
        for y in range(size):
            row = bytearray(bg * size)
            dy = y + 0.5 - cy
            if abs(dy) < r_out:
                xo = (r_out * r_out - dy * dy) ** 0.5
                xi = (r_in * r_in - dy * dy) ** 0.5 if abs(dy) < r_in else 0.0
                for a, b in ((cx - xo, cx - xi), (cx + xi, cx + xo)):
                    for x in range(max(0, int(a)), min(size, int(b) + 1)):
                        row[x * 3:x * 3 + 3] = ring
            if y0 <= y <= y1:
                span = (1.0 - abs(y + 0.5 - mid) / half) * (x1 - x0)
                xe = min(size, x0 + int(span))
                if xe > x0:
                    row[x0 * 3:xe * 3] = fg * (xe - x0)
            rows.append(bytes(row))
        png = _png_rgb(size, size, rows)
        _icon_cache[size] = png
        return png


class PibraryHandler(http.server.BaseHTTPRequestHandler):
    server_version = f"pibrary/{VERSION}"
    timeout = 60

    def send_response(self, code, message=None):
        super().send_response(code, message)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if getattr(self, "_pdf_response", False):
            return
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; font-src 'self' data:; frame-ancestors 'none'; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
        )

    def _send_json(self, status, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        renew = getattr(self, "_renew_token", None)
        self._renew_token = None
        if (renew and _session_valid(renew)
                and not any(k.lower() == "set-cookie" for k, _v in (extra_headers or []))):
            self.send_header("Set-Cookie", _session_cookie_header(renew, _SESSION_TTL_SEC))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error_json(self, status, message):
        log_event(f"HTTP {status}: {message} ({self.command} {self.path})", "err")
        self._send_json(status, {"error": message})

    def _session_token(self):
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(_SESSION_COOKIE_NAME + "="):
                return part[len(_SESSION_COOKIE_NAME) + 1:]
        return None

    def _authed(self):
        if not _cfg_get("auth_enabled"):
            return True
        token = self._session_token()
        if not _check_session(token):
            return False
        if _session_cookie_due(token):
            self._renew_token = token
        return True

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

    def _check_csrf(self):
        return self.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _read_json(self, max_bytes=MAX_JSON_BYTES):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if length < 0 or length > max_bytes:
            self._error_json(413, "Body too large or invalid length")
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._error_json(400, "Malformed JSON body")
            return None
        if not isinstance(body, dict):
            self._error_json(400, "Body must be a JSON object")
            return None
        return body


    def _route_index(self):
        self._send_html(200, render_page())

    def _route_health(self):
        self._send_json(200, {"ok": True, "version": VERSION})

    def _route_manifest(self):
        body = json.dumps(MANIFEST).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/manifest+json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _route_icon(self):
        body = _icon_png(_ICON_SIZES[self.path.split("?", 1)[0]])
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=604800")
        self.end_headers()
        self.wfile.write(body)

    def _route_favicon(self):
        self.send_response(204)
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()

    def _route_whoami(self):
        self._send_json(200, {"ok": True, "auth_enabled": _cfg_get("auth_enabled"),
                              "tab_side": _cfg_get("tab_side"), "hostname": socket.gethostname()})

    def _route_alerts(self):
        self._send_json(200, {"alerts": alerts_list()})

    def _post_notify_test(self):
        body = self._read_json()
        if body is None:
            return
        url = str(body.get("url") or "").strip() or _cfg_get("notify_url")
        try:
            url = _norm_url(url)
        except ValueError as exc:
            self._error_json(400, f"Notification address {exc}")
            return
        if not url:
            self._error_json(400, "Enter an ntfy address first (e.g. https://ntfy.sh/your-topic)")
            return
        ok, err = _ntfy_send(url, f"Test from Pibrary v{VERSION}: notifications work.", "info")
        if ok:
            log_event("Test notification sent", "ok")
            self._send_json(200, {"ok": True})
        else:
            self._error_json(502, f"Sending failed: {err}")

    def _route_lib_art(self):
        q = self._query()
        kind = q.get("type", [""])[0]
        full = _resolve_art(kind, q.get("id", [""])[0])
        if full is None:
            self._error_json(404, "No such image")
            return
        try:
            with open(full, "rb") as fh:
                body = fh.read(ART_MAX_BYTES + 1)
        except OSError as exc:
            self._error_json(500, f"Could not read the image: {exc}")
            return
        self.send_response(200)
        self.send_header("Content-Type", _ART_MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _route_lib_recent(self):
        q = self._query()
        try:
            n = max(1, min(20, int(q.get("n", ["5"])[0])))
        except ValueError:
            n = 5
        recent = {}
        for kind in MEDIA_TYPES:
            _ts, items, _trunc, _dirs, _art = lib_list(kind)
            recent[kind] = sorted(items, key=lambda i: (i.get("added") or 0, i.get("mtime") or 0),
                                  reverse=True)[:n]
        online = _library_online()
        self._send_json(200, {"ok": True, "recent": recent, "offline": not online,
                              "offline_reason": None if online else _offline_reason()})

    def _route_status(self):
        st = build_status()
        st["access"] = access_info(self.client_address[0], self.headers.get("Host"))
        self._send_json(200, st)

    def _route_log(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        try:
            since = int(query.get("since", ["0"])[0])
        except ValueError:
            since = 0
        with _log_lock:
            entries = [e for e in _log if e["id"] > since]
        self._send_json(200, {"entries": entries})

    def _route_config(self):
        self._send_json(200, config_snapshot())

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)

    def _route_lib_list(self):
        q = self._query()
        kind = q.get("type", [""])[0]
        spec = MEDIA_TYPES.get(kind)
        if not spec:
            self._error_json(400, "Unknown media type")
            return
        ts, items, truncated, dirs, dir_art = lib_list(kind, q.get("refresh", ["0"])[0] == "1")
        can_edit = _cfg_get("allow_write") and _library_online() and not _migrating()
        self._send_json(200, {
            "items": items, "truncated": truncated, "scanned_at": int(ts), "cap": LIST_CAP,
            "dirs": dirs, "dir_art": dir_art, "can_edit": can_edit, "trash_days": TRASH_DAYS,
            "can_upload": can_edit,
            "offline": not _library_online(), "state": _library_state(), "migrating": _migrating(),
            "offline_reason": None if _library_online() else _offline_reason(),
            "free": _lib_space()[0], "total": _lib_space()[1],
            "upload_dir": os.path.join(_cfg_get("library_root"), spec["dir"]),
            "exts": list(spec["exts"]), "max_upload_mb": _effective_max_upload_mb(),
        })

    def _route_lib_precheck(self):
        q = self._query()
        try:
            size = int(q.get("size", ["0"])[0])
        except ValueError:
            size = 0
        status, err, ctx = _validate_upload(q.get("type", [""])[0], q.get("name", [""])[0], size,
                                            q.get("dir", [""])[0])
        if status != 200:
            self._send_json(status, {"ok": False, "error": err})
            return
        self._send_json(200, {"ok": True, "exists": os.path.lexists(ctx[1])})

    def _route_lib_file(self):
        q = self._query()
        kind = q.get("type", [""])[0]
        item_id = q.get("id", [""])[0]
        full = _resolve_id(kind, item_id)
        if full is None:
            self._error_json(404, "No such file")
            return
        ctype = _MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        try:
            size = os.path.getsize(full)
            fh = open(full, "rb")
        except OSError as exc:
            self._error_json(500, f"Could not read file: {exc}")
            return
        token = _stream_acquire(kind, item_id, os.path.basename(full))
        if token is None:
            fh.close()
            self._error_json(503, "Too many active streams")
            return
        try:
            rng = _parse_range(self.headers.get("Range", ""), size) if self.headers.get("Range") else None
            if rng is False:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start, end = rng if rng else (0, size - 1)
            length = (end - start + 1) if size else 0
            self._pdf_response = (kind == "pdf")
            try:
                self.send_response(206 if rng else 200)
            finally:
                self._pdf_response = False
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            disp = "attachment" if q.get("download", ["0"])[0] == "1" else "inline"
            self.send_header("Content-Disposition",
                             disp + "; filename*=UTF-8''" + urllib.parse.quote(os.path.basename(full)))
            self.send_header("Cache-Control", "private, no-cache")
            self.end_headers()
            fh.seek(start)
            sock = self.connection
            sock.settimeout(STREAM_SEND_TIMEOUT_SEC)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(65536, remaining))
                if not chunk:
                    break
                if not _send_stream(sock, chunk, token):
                    break
                remaining -= len(chunk)
        except OSError:
            pass
        finally:
            fh.close()
            _stream_release(token)

    def _respond(self, result):
        status, payload = result
        try:
            if status >= 400 and not ({"mismatch", "exists", "needs_confirm"} & set(payload)):
                log_event(f"HTTP {status}: {payload.get('error', 'Error')} ({self.command} {self.path})", "err")
            self._send_json(status, payload)
        except OSError:
            pass

    def _lib_body(self):
        body = self._read_json(256 * 1024)
        if body is None:
            return None
        return body, str(body.get("type") or "")

    def _post_lib_mkdir(self):
        got = self._lib_body()
        if got:
            body, kind = got
            self._respond(lib_mkdir(kind, str(body.get("dir") or ""), str(body.get("name") or "").strip()))

    def _post_lib_rename(self):
        got = self._lib_body()
        if got:
            body, kind = got
            self._respond(lib_rename(kind, str(body.get("rel") or ""), str(body.get("name") or "").strip()))

    def _post_lib_move(self):
        got = self._lib_body()
        if got:
            body, kind = got
            items = body.get("items")
            items = [str(x) for x in items] if isinstance(items, list) else None
            self._respond(lib_move(kind, items, str(body.get("dest") or "")))

    def _post_lib_trash(self):
        got = self._lib_body()
        if got:
            body, kind = got
            items = body.get("items")
            items = [str(x) for x in items] if isinstance(items, list) else None
            self._respond(lib_trash(kind, items))

    def _route_dupes(self):
        kind = self._query().get("type", [""])[0]
        ent = _dupes.get(kind)
        self._send_json(200, {"ok": True, "result": ent})

    def _post_dupes_scan(self):
        got = self._lib_body()
        if got:
            _body, kind = got
            self._storage_locked(lambda: dupes_start(kind))

    def _route_trash_list(self):
        status, payload = trash_list(self._query().get("type", [""])[0])
        self._send_json(status, payload)

    def _post_trash_restore(self):
        got = self._lib_body()
        if got:
            body, kind = got
            self._respond(trash_restore(kind, body.get("ids")))

    def _post_trash_empty(self):
        got = self._lib_body()
        if got:
            body, kind = got
            ids = body.get("ids")
            if body.get("all"):
                ids = None
            elif not isinstance(ids, list) or not ids:
                self._error_json(400, "Nothing selected")
                return
            self._respond(trash_empty(kind, ids))

    def _post_lib_upload(self):
        q = self._query()
        kind = q.get("type", [""])[0]
        name = q.get("name", [""])[0]
        force = q.get("force", ["0"])[0] == "1"
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = 0
        status, err, ctx = _validate_upload(kind, name, length, q.get("dir", [""])[0])
        if status != 200:
            self._error_json(status, err)
            return
        target, final = ctx
        if not force and os.path.lexists(final):
            self._send_json(409, {"error": "File exists", "exists": True})
            return
        if not _upload_lock.acquire(blocking=False):
            self._error_json(503, "Another upload is in progress")
            return
        try:
            result = self._store_upload(kind, name, length, target, final, force)
        finally:
            _upload_lock.release()
        if result:
            self._respond(result)

    def _store_upload(self, kind, name, length, target, final, force):
        tmp = os.path.join(target, ".upload-%s.part" % secrets.token_hex(6))
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            remaining = length
            with os.fdopen(fd, "wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ConnectionError("client closed before the upload finished")
                    fh.write(chunk)
                    remaining -= len(chunk)
                fh.flush()
                os.fsync(fh.fileno())
            _commit_upload(tmp, final, force)
        except FileExistsError:
            return 409, {"error": "File exists", "exists": True}
        except (ConnectionError, TimeoutError) as exc:
            log_event(f"Upload of {name} interrupted: {exc}", "warn")
            return None
        except OSError as exc:
            return (507 if exc.errno == errno.ENOSPC else 500), {"error": f"Upload failed: {exc}"}
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        _invalidate_scan(kind)
        log_event(f"Uploaded {kind}/{name} ({length} bytes)", "ok")
        return 200, {"ok": True, "name": name, "size": length}

    def _post_password(self):
        client_ip = self.client_address[0]
        remaining = _auth_lockout_remaining(client_ip)
        if remaining > 0:
            self._send_json(429, {"error": f"Too many failed attempts. Try again in {int(remaining) + 1}s."})
            return
        body = self._read_json()
        if body is None:
            return
        ok, result = password_change(body)
        if not ok:
            if result == "Current password is incorrect":
                _record_auth_failure(client_ip)
            self._error_json(400, result)
            return
        _record_auth_success(client_ip)
        with _sessions_lock:
            _sessions.clear()
        extra = []
        if _cfg_get("auth_enabled"):
            extra.append(("Set-Cookie", _session_cookie_header(_issue_session(), _SESSION_TTL_SEC)))
        self._send_json(200, {"ok": True, "result": result}, extra_headers=extra)

    def _self_gate(self, need_root=False):
        if not _cfg_get("auth_enabled"):
            self._error_json(403, "Software update requires login to be enabled")
            return False
        if not _cfg_get("allow_update"):
            self._error_json(403, "Software update is disabled (tick Allow software update in Config)")
            return False
        if need_root and (os.geteuid() != 0 or not os.environ.get("NOTIFY_SOCKET")):
            self._error_json(409, "Install needs Pibrary running as a root systemd service")
            return False
        return True

    def _route_self_list(self):
        reason = None
        if not _cfg_get("auth_enabled"):
            reason = "Software update requires login to be enabled."
        elif not _cfg_get("allow_update"):
            reason = "Software update is disabled: tick Allow software update above and Save."
        allowed = reason is None
        can_install = allowed and os.geteuid() == 0 and bool(os.environ.get("NOTIFY_SOCKET"))
        self._send_json(200, {
            "running": VERSION, "allowed": allowed, "reason": reason, "can_install": can_install,
            "items": self_list() if allowed else [], "keep": SELF_KEEP, "dir": _staged_dir(),
            "max_mb": SELF_MAX_BYTES // (1024 * 1024),
        })

    def _post_self_upload(self):
        q = self._query()
        name = q.get("name", [""])[0]
        force = q.get("force", ["0"])[0] == "1"
        if not self._self_gate():
            return
        err = _validate_self_name(name)
        if err:
            self._error_json(400, err)
            return
        if not _SELF_NAME_RE.match(name) and not force:
            self._send_json(400, {"error": f"'{name}' doesn't look like a Pibrary file (expected Pibrary*.py)",
                                  "mismatch": True})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = 0
        if length <= 0 or length > SELF_MAX_BYTES:
            self._error_json(413, f"File missing or over the {SELF_MAX_BYTES // (1024 * 1024)} MB limit")
            return
        if not _self_lock.acquire(blocking=False):
            self._error_json(503, "Another update operation is in progress")
            return
        try:
            result = self._store_self_upload(name, length)
        finally:
            _self_lock.release()
        if result:
            self._respond(result)

    def _store_self_upload(self, name, length):
        tmp = os.path.join(_staged_dir(), ".upload-%s.part" % secrets.token_hex(6))
        try:
            os.makedirs(_staged_dir(), exist_ok=True)
            free = os.statvfs(_staged_dir())
            if length + 10 * 1024 * 1024 > free.f_bavail * free.f_frsize:
                return 507, {"error": "Not enough free space for the update"}
            digest = hashlib.sha256()
            remaining = length
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ConnectionError("client closed before the upload finished")
                    fh.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                fh.flush()
                os.fsync(fh.fileno())
            err, ver = _self_validate_file(tmp)
            if err:
                log_event(f"Rejected {name}: {err}", "warn")
                return 400, {"error": err}
            final = os.path.join(_staged_dir(), name)
            if os.path.isfile(final):
                with open(final, "rb") as fh:
                    same = hashlib.sha256(fh.read()).hexdigest() == digest.hexdigest()
                if same:
                    return 200, {"ok": True, "wrote": False, "name": name, "version": ver,
                                 "message": f"{name} already staged (unchanged)."}
            _commit_upload(tmp, final, True)
            _prune_staged()
            log_event(f"Staged {name} (v{ver}) for install", "ok")
            return 200, {"ok": True, "wrote": True, "name": name, "version": ver,
                         "message": f"Staged {name} (v{ver})."}
        except (ConnectionError, TimeoutError) as exc:
            log_event(f"Upload of {name} interrupted: {exc}", "warn")
            return None
        except OSError as exc:
            return (507 if exc.errno == errno.ENOSPC else 500), {"error": f"Upload failed: {exc}"}
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _post_self_install(self):
        if not self._self_gate(need_root=True):
            return
        body = self._read_json()
        if body is None:
            return
        name = str((body or {}).get("name") or "")
        want_sha = str((body or {}).get("sha") or "")
        if _validate_self_name(name):
            self._error_json(400, "Invalid file name")
            return
        path = os.path.join(_staged_dir(), name)
        if not os.path.isfile(path) or os.path.islink(path):
            self._error_json(404, "No such staged file")
            return
        client_ip = self.client_address[0]
        remaining = _auth_lockout_remaining(client_ip)
        if remaining > 0:
            self._send_json(429, {"error": f"Too many failed attempts. Try again in {int(remaining) + 1}s."})
            return
        if not _verify_login(str(body.get("password") or "")):
            _record_auth_failure(client_ip)
            self._error_json(403, "Password is incorrect (enter it in entry 12 to install)")
            return
        _record_auth_success(client_ip)
        if not _self_lock.acquire(blocking=False):
            self._error_json(503, "Another update operation is in progress")
            return
        started = False
        try:
            result = None
            err, ver = _self_validate_file(path)
            if err:
                result = (400, {"error": err})
            else:
                try:
                    with open(path, "rb") as fh:
                        cur_sha = hashlib.sha256(fh.read()).hexdigest()
                except OSError as exc:
                    cur_sha = None
                    result = (500, {"error": f"Cannot read staged file: {exc}"})
                if result is None and want_sha and cur_sha != want_sha:
                    result = (409, {"error": "The staged file changed since it was listed; refresh and retry"})
                if result is None:
                    cmp = _cmp_version(ver)
                    if cmp != "newer" and not body.get("confirm"):
                        result = (409, {"error": f"v{ver} is not newer than the running v{VERSION}",
                                        "needs_confirm": True, "cmp": cmp})
                    else:
                        threading.Thread(target=_run_self_install, args=(path, name), daemon=True).start()
                        started = True
                        result = (200, {"ok": True, "started": True})
        finally:
            if not started:
                _self_lock.release()
        self._respond(result)

    def _post_self_delete(self):
        if not self._self_gate():
            return
        body = self._read_json()
        if body is None:
            return
        name = str((body or {}).get("name") or "")
        if _validate_self_name(name):
            self._error_json(400, "Invalid file name")
            return
        path = os.path.join(_staged_dir(), name)
        if not os.path.isfile(path) or os.path.islink(path):
            self._error_json(404, "No such staged file")
            return
        if not _self_lock.acquire(blocking=False):
            self._error_json(503, "Another update operation is in progress")
            return
        try:
            try:
                os.unlink(path)
                _fsync_dir(_staged_dir())
                log_event(f"Deleted staged {name}", "info")
                result = (200, {"ok": True})
            except OSError as exc:
                result = (500, {"error": f"Delete failed: {exc}"})
        finally:
            _self_lock.release()
        self._respond(result)

    def _storage_gate(self, need_write=False, need_root=True):
        if not _cfg_get("auth_enabled"):
            self._error_json(403, "Storage actions require login to be enabled")
            return False
        if need_root and os.geteuid() != 0:
            self._error_json(409, "Storage actions need Pibrary running as root")
            return False
        if need_write and not _cfg_get("allow_write"):
            self._error_json(403, "Tick Allow uploads in Config first")
            return False
        return True

    def _storage_locked(self, fn):
        if not _storage_op_lock.acquire(blocking=False):
            self._error_json(503, "Another storage operation is in progress")
            return
        started = False
        try:
            status, payload, started = fn()
        except Exception as exc:
            log_event(f"Storage action failed: {exc}", "err")
            status, payload, started = 500, {"error": f"Storage error: {exc}"}, False
        finally:
            if not started:
                _storage_op_lock.release()
        self._respond((status, payload))

    def _route_config_backup(self):
        data = config_backup_data(self._query().get("password", ["0"])[0] == "1")
        body = json.dumps(data, indent=1).encode("utf-8")
        name = f"pibrary-config-{datetime.now().strftime('%Y-%m-%d')}.json"
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", f"attachment; filename={name}")
        self.end_headers()
        self.wfile.write(body)
        log_event("Config backup downloaded" + (" (with password hash)" if "password_hash" in data else ""), "info")

    def _post_config_restore(self):
        body = self._read_json(512 * 1024)
        if body is None:
            return
        status, payload, turned_on = config_restore(body)
        extra = [("Set-Cookie", _session_cookie_header(_issue_session(), _SESSION_TTL_SEC))] if turned_on else None
        if status >= 400:
            self._respond((status, payload))
        else:
            self._send_json(status, payload, extra_headers=extra)

    def _post_find_backups(self):
        if self._read_json() is None:
            return
        if not _storage_op_lock.acquire(blocking=False):
            self._error_json(503, "A storage operation is in progress; try again in a moment")
            return
        try:
            result = find_drive_backups()
        finally:
            _storage_op_lock.release()
        self._respond(result)

    def _route_log_file(self):
        blob = log_file_text()
        if blob is None:
            self._error_json(404, "No log file on the library drive (it needs a USB library and Config entry 17)")
            return
        name = f"pibrary-log-{datetime.now().strftime('%Y-%m-%d')}.txt"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", f"attachment; filename={name}")
        self.end_headers()
        self.wfile.write(blob)

    def _route_keep(self):
        self._send_json(200, {"pending": keep_list()})

    def _post_keep(self):
        body = self._read_json()
        if body is None:
            return
        client_ip = self.client_address[0]
        remaining = _auth_lockout_remaining(client_ip)
        if remaining > 0:
            self._send_json(429, {"error": f"Too many failed attempts. Try again in {int(remaining) + 1}s."})
            return
        kind = str(body.get("kind") or "")
        status, payload = keep_confirm(kind, str(body.get("password") or ""), bool(body.get("undo")))
        if status == 403:
            _record_auth_failure(client_ip)
        self._respond((status, payload))

    def _post_reboot(self):
        body = self._read_json()
        if body is None:
            return
        self._respond(system_reboot(str(body.get("confirm") or "")))

    def _route_positions(self):
        self._send_json(200, positions_get())

    def _post_positions(self):
        body = self._read_json(512 * 1024)
        if body is None:
            return
        self._respond(positions_post(body))

    def _route_streams(self):
        self._send_json(200, {"streams": _streams_snapshot(), "stall_limit": STREAM_STALL_SEC,
                              "active": _streams_active, "max": _cfg_get("max_streams")})

    def _route_storage_list(self):
        self._send_json(200, storage_snapshot())

    def _route_storage_job(self):
        self._send_json(200, _mig_snapshot())

    def _route_import_list(self):
        q = self._query()
        kind = q.get("type", [""])[0]
        if kind not in MEDIA_TYPES:
            self._error_json(400, "Unknown media type")
            return
        reason = None
        if not _cfg_get("auth_enabled"):
            reason = "Importing requires login to be enabled."
        elif not _cfg_get("allow_write"):
            reason = "Importing requires Allow uploads in Config."
        elif not _library_online():
            reason = _offline_reason() + "."
        ts, items, truncated = import_list(kind, q.get("refresh", ["0"])[0] == "1")
        drives = sorted({i["drive"] for i in items} | {_storage_labels.get(n, n) for n in _import_mounts()})
        self._send_json(200, {"can_import": reason is None, "reason": reason, "items": items,
                              "truncated": truncated, "drives": drives, "cap": IMPORT_SCAN_CAP,
                              "select_cap": IMPORT_SELECT_CAP})

    def _post_storage_use(self):
        if not self._storage_gate():
            return
        body = self._read_json()
        if body is None:
            return
        self._storage_locked(lambda: storage_use_drive(
            str(body.get("uuid") or ""), bool(body.get("copy", True)),
            bool(body.get("overwrite", False)), bool(body.get("verify", False))))

    def _post_storage_use_sd(self):
        if not self._storage_gate():
            return
        body = self._read_json()
        if body is None:
            return
        self._storage_locked(lambda: storage_use_sd(
            bool(body.get("copy_back", False)), bool(body.get("overwrite", False)),
            bool(body.get("verify", False))))

    def _post_storage_eject(self):
        if not self._storage_gate():
            return
        body = self._read_json()
        if body is None:
            return
        self._storage_locked(lambda: storage_eject(str(body.get("uuid") or "")))

    def _post_storage_mount(self):
        if not self._storage_gate():
            return
        body = self._read_json()
        if body is None:
            return
        self._storage_locked(lambda: storage_mount(str(body.get("uuid") or "")))

    def _post_storage_purge(self):
        if not self._storage_gate(need_write=True, need_root=False):
            return
        self._storage_locked(storage_purge_originals)

    def _post_storage_replace(self):
        if not self._storage_gate():
            return
        body = self._read_json()
        if body is None:
            return
        self._storage_locked(lambda: storage_replace(
            str(body.get("uuid") or ""), str(body.get("source") or "old"),
            bool(body.get("overwrite", False)), bool(body.get("verify", False))))

    def _post_storage_format(self):
        if not self._storage_gate():
            return
        body = self._read_json()
        if body is None:
            return
        self._storage_locked(lambda: storage_format(
            str(body.get("disk") or ""), str(body.get("fp") or ""),
            str(body.get("label") or "PIBRARY"), str(body.get("confirm") or "")))

    def _post_storage_cancel(self):
        if not self._storage_gate(need_root=False):
            return
        _mig_set(cancel=True)
        self._send_json(200, {"ok": True})

    def _post_import_copy(self):
        if not self._storage_gate(need_write=True, need_root=False):
            return
        body = self._read_json(512 * 1024)
        if body is None:
            return
        self._storage_locked(lambda: storage_import_copy(
            str(body.get("type") or ""), body.get("ids"), bool(body.get("overwrite", False))))


    def _post_config(self):
        body = self._read_json()
        if body is None:
            return
        ok, result = config_update(body)
        if not ok:
            self._error_json(400, result)
            return
        extra = []
        if result["auth_turned_on"]:
            extra.append(("Set-Cookie", _session_cookie_header(_issue_session(), _SESSION_TTL_SEC)))
        self._send_json(200, {"ok": True, "changed": result["changed"]}, extra_headers=extra)

    def _post_restart(self):
        if not os.environ.get("NOTIFY_SOCKET") or os.geteuid() != 0:
            self._error_json(409, "Restart unavailable (not running as a root systemd service)")
            return
        new_port = _cfg_get("port")
        port_change = new_port != PORT and _BOOT_CFG_PORT is not None and PORT == _BOOT_CFG_PORT
        if port_change:
            ok, err = _cfg_apply_internal({"revert_port": PORT,
                                           "revert_deadline": int(time.time()) + PORT_KEEP_SEC})
            if not ok:
                self._error_json(500, err)
                return
        if _schedule_restart():
            log_event("Service restart scheduled" + (f" (new port {new_port}; confirm within "
                                                     f"{PORT_KEEP_SEC // 60} min or port {PORT} comes back)"
                                                     if port_change else ""), "warn")
            self._send_json(200, {"ok": True, "port_change": port_change, "new_port": new_port,
                                  "keep_sec": PORT_KEEP_SEC})
        else:
            self._error_json(409, "Restart unavailable (not running as a root systemd service)")

    def _handle_login(self):
        client_ip = self.client_address[0]
        if not _cfg_get("auth_enabled"):
            self._send_json(200, {"ok": True})
            return
        remaining = _auth_lockout_remaining(client_ip)
        if remaining > 0:
            retry_after = int(remaining) + 1
            self._send_json(429, {"ok": False,
                                  "error": f"Too many failed login attempts. Try again in {retry_after}s."},
                            extra_headers=[("Retry-After", str(retry_after))])
            return
        body = self._read_json()
        if body is None:
            return
        password = body.get("password") if isinstance(body, dict) else ""
        if _verify_login(password or ""):
            _record_auth_success(client_ip)
            token = _issue_session()
            self._send_json(200, {"ok": True},
                            extra_headers=[("Set-Cookie", _session_cookie_header(token, _SESSION_TTL_SEC))])
        else:
            _record_auth_failure(client_ip)
            self._send_json(401, {"ok": False, "error": "Invalid password"})

    def _host_ok(self):
        if _host_allowed(self.headers.get("Host")):
            return True
        self._error_json(403, "Host not allowed (add it to allowed_hosts in the config file)")
        return False

    def do_GET(self):
        if not self._host_ok():
            return
        path = self.path.split("?", 1)[0]
        if path not in _OPEN_GET_PATHS and not self._authed():
            self._require_auth()
            return
        handler_fn = _GET_ROUTES.get(path)
        if handler_fn is None:
            self._error_json(404, "Not found")
            return
        handler_fn(self)

    def do_POST(self):
        if not self._host_ok():
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/login":
            self._handle_login()
            return
        if path == "/api/logout":
            token = self._session_token()
            if token:
                _revoke_session(token)
            self._send_json(200, {"ok": True},
                            extra_headers=[("Set-Cookie", _clear_session_cookie_header())])
            return
        if not self._authed():
            self._require_auth()
            return
        if not self._check_csrf():
            self._error_json(403, "Missing or invalid X-Requested-With header")
            return
        handler_fn = _POST_ROUTES.get(path)
        if handler_fn is None:
            self._error_json(404, "Not found")
            return
        handler_fn(self)

    def log_message(self, format, *args):
        return


_OPEN_GET_PATHS = ("/", "/index.html", "/api/health", "/favicon.ico", "/manifest.webmanifest",
                   "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png")

_GET_ROUTES = {
    "/": PibraryHandler._route_index,
    "/index.html": PibraryHandler._route_index,
    "/api/health": PibraryHandler._route_health,
    "/favicon.ico": PibraryHandler._route_favicon,
    "/manifest.webmanifest": PibraryHandler._route_manifest,
    "/icon-192.png": PibraryHandler._route_icon,
    "/icon-512.png": PibraryHandler._route_icon,
    "/apple-touch-icon.png": PibraryHandler._route_icon,
    "/api/whoami": PibraryHandler._route_whoami,
    "/api/status": PibraryHandler._route_status,
    "/api/log": PibraryHandler._route_log,
    "/api/config": PibraryHandler._route_config,
    "/api/lib/list": PibraryHandler._route_lib_list,
    "/api/lib/precheck": PibraryHandler._route_lib_precheck,
    "/api/lib/trash/list": PibraryHandler._route_trash_list,
    "/api/lib/dupes": PibraryHandler._route_dupes,
    "/api/lib/recent": PibraryHandler._route_lib_recent,
    "/api/lib/art": PibraryHandler._route_lib_art,
    "/api/alerts": PibraryHandler._route_alerts,
    "/api/keep": PibraryHandler._route_keep,
    "/api/config/backup": PibraryHandler._route_config_backup,
    "/api/log/file": PibraryHandler._route_log_file,
    "/api/lib/file": PibraryHandler._route_lib_file,
    "/api/self/list": PibraryHandler._route_self_list,
    "/api/streams": PibraryHandler._route_streams,
    "/api/storage/list": PibraryHandler._route_storage_list,
    "/api/storage/job": PibraryHandler._route_storage_job,
    "/api/import/list": PibraryHandler._route_import_list,
    "/api/positions": PibraryHandler._route_positions,
}

_POST_ROUTES = {
    "/api/config": PibraryHandler._post_config,
    "/api/restart": PibraryHandler._post_restart,
    "/api/password": PibraryHandler._post_password,
    "/api/lib/upload": PibraryHandler._post_lib_upload,
    "/api/lib/mkdir": PibraryHandler._post_lib_mkdir,
    "/api/lib/rename": PibraryHandler._post_lib_rename,
    "/api/lib/move": PibraryHandler._post_lib_move,
    "/api/lib/trash": PibraryHandler._post_lib_trash,
    "/api/lib/trash/restore": PibraryHandler._post_trash_restore,
    "/api/lib/trash/empty": PibraryHandler._post_trash_empty,
    "/api/lib/dupes/scan": PibraryHandler._post_dupes_scan,
    "/api/self/upload": PibraryHandler._post_self_upload,
    "/api/self/install": PibraryHandler._post_self_install,
    "/api/self/delete": PibraryHandler._post_self_delete,
    "/api/storage/use": PibraryHandler._post_storage_use,
    "/api/storage/use-sd": PibraryHandler._post_storage_use_sd,
    "/api/storage/eject": PibraryHandler._post_storage_eject,
    "/api/storage/mount": PibraryHandler._post_storage_mount,
    "/api/storage/purge": PibraryHandler._post_storage_purge,
    "/api/storage/cancel": PibraryHandler._post_storage_cancel,
    "/api/storage/replace": PibraryHandler._post_storage_replace,
    "/api/storage/format": PibraryHandler._post_storage_format,
    "/api/import/copy": PibraryHandler._post_import_copy,
    "/api/positions": PibraryHandler._post_positions,
    "/api/notify/test": PibraryHandler._post_notify_test,
    "/api/keep": PibraryHandler._post_keep,
    "/api/system/reboot": PibraryHandler._post_reboot,
    "/api/config/restore": PibraryHandler._post_config_restore,
    "/api/config/find-backups": PibraryHandler._post_find_backups,
}


class PibraryServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


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


def _write_launcher():
    _atomic_write(_LAUNCHER_PATH, _LAUNCHER_CODE, 0o755)
    print(f"  [+] Wrote launcher {_LAUNCHER_PATH}")


def _remove_launcher_if_unused():
    if not os.path.exists(_LAUNCHER_PATH):
        return
    try:
        names = os.listdir(_SYSTEMD_UNIT_DIR)
    except OSError:
        return
    for n in names:
        p = os.path.join(_SYSTEMD_UNIT_DIR, n)
        try:
            if os.path.isfile(p):
                with open(p, errors="replace") as fh:
                    if _LAUNCHER_PATH in fh.read():
                        return
        except OSError:
            continue
    try:
        os.remove(_LAUNCHER_PATH)
    except FileNotFoundError:
        return
    print(f"  [-] Removed {_LAUNCHER_PATH} (no other service uses it)")


def install_service():
    if os.geteuid() != 0:
        print("Error: Installation requires root privileges. Run with 'sudo'.")
        sys.exit(1)

    current_script = os.path.realpath(__file__)
    print("Installing Pibrary...")

    os.makedirs(INSTALL_DIR, exist_ok=True)
    dest = os.path.join(INSTALL_DIR, os.path.basename(current_script))
    if current_script != dest:
        tmp = dest + ".tmp"
        shutil.copy2(current_script, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        print(f"  [+] Copied {os.path.basename(current_script)} -> {dest}")
    os.chmod(dest, 0o755)

    tmp_link = INSTALL_BIN_PATH + ".tmp"
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(dest, tmp_link)
    os.replace(tmp_link, INSTALL_BIN_PATH)
    print(f"  [+] Symlinked {INSTALL_BIN_PATH} -> {dest}")

    for name in os.listdir(INSTALL_DIR):
        old = os.path.join(INSTALL_DIR, name)
        if old != dest and name.endswith(".py") and os.path.isfile(old) and not os.path.islink(old):
            os.remove(old)
            print(f"  [-] Removed the previous version {old}")
    shutil.rmtree(os.path.join(INSTALL_DIR, "__pycache__"), ignore_errors=True)

    load_config()
    if not os.path.exists(CONFIG_PATH):
        save_config(_cfg)
        print(f"  [+] Wrote default config {CONFIG_PATH}")
    _ensure_media_dirs()
    print(f"  [+] Library root {_cfg['library_root']} (movies/ audio/ pdf/)")

    _write_launcher()
    _atomic_write(SYSTEMD_SERVICE_PATH, SYSTEMD_SERVICE_CONTENT, 0o644)
    print(f"  [+] Created service file at {SYSTEMD_SERVICE_PATH}")
    mark, msg = open_firewall_port(_cfg["port"])
    print(f"  [{mark}] {msg}")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", SERVICE_NAME], check=True)
    subprocess.run([
        "systemd-run", "--quiet", "--collect", "--on-active=2",
        "--unit=pibrary-selfrestart", "systemctl", "restart", SERVICE_NAME,
    ], check=True)
    print(f"  [+] Enabled {SERVICE_NAME}; restart scheduled in ~2s")
    print(f"\nInstallation complete! Pibrary will be listening on port {_cfg['port']} shortly.")
    print("View logs anytime using:")
    print("  journalctl -u pibrary -f")
    print("\nNote: Pibrary serves plaintext HTTP only (no built-in TLS).")


def uninstall_service():
    if os.geteuid() != 0:
        print("Error: Uninstallation requires root privileges. Run with 'sudo'.")
        sys.exit(1)

    print("Uninstalling Pibrary...")
    subprocess.run(["systemctl", "disable", "--now", SERVICE_NAME], stderr=subprocess.DEVNULL)
    print(f"  [-] Stopped and disabled {SERVICE_NAME}")

    if os.path.exists(SYSTEMD_SERVICE_PATH):
        os.remove(SYSTEMD_SERVICE_PATH)
        print(f"  [-] Removed {SYSTEMD_SERVICE_PATH}")
    subprocess.run(["systemctl", "daemon-reload"], stderr=subprocess.DEVNULL)

    target = None
    if os.path.lexists(INSTALL_BIN_PATH):
        if os.path.islink(INSTALL_BIN_PATH):
            target = os.path.realpath(INSTALL_BIN_PATH)
        os.remove(INSTALL_BIN_PATH)
        print(f"  [-] Removed {INSTALL_BIN_PATH}")
    if target and os.path.dirname(target) == INSTALL_DIR and os.path.isfile(target):
        os.remove(target)
        print(f"  [-] Removed {target}")
    shutil.rmtree(os.path.join(INSTALL_DIR, "__pycache__"), ignore_errors=True)
    shutil.rmtree(STAGED_DIR, ignore_errors=True)
    try:
        os.rmdir(INSTALL_DIR)
    except OSError:
        pass
    _remove_launcher_if_unused()
    load_config()
    mark, msg = close_firewall_port(_cfg["port"])
    print(f"  [{mark}] {msg}")

    print("\nUninstallation complete.")
    print(f"Note: {CONFIG_DIR} and the media library were left in place -- remove manually if desired.")


def run(port_override=None):
    global PORT, _BOOT_CFG_PORT
    load_config()
    _BOOT_CFG_PORT = _cfg["port"]
    PORT = port_override or _cfg["port"]
    log_event(f"Pibrary v{VERSION} starting on port {PORT}", "info")
    log_event("Serving plaintext HTTP only (no built-in TLS). Keep this on a trusted LAN/VPN.", "info")
    if not _cfg["auth_enabled"]:
        log_event("Login is DISABLED -- anyone on the network can reach this dashboard.", "warn")
    if os.geteuid() != 0:
        log_event("Not running as root -- service restart and root-password login are unavailable.", "warn")
    if _cfg["usb_uuid"] and _is_mount(USB_MOUNT):
        why = _mount_health(USB_MOUNT, None, _cfg["library_root"])
        if why and os.geteuid() == 0:
            _lib_fault(why)
    _ensure_media_dirs(sweep=True)
    _sweep_staged()
    threading.Thread(target=_storage_watch_loop, daemon=True).start()
    threading.Thread(target=_pos_flush_loop, daemon=True).start()
    threading.Thread(target=_trash_sweep_loop, daemon=True).start()
    threading.Thread(target=_notify_loop, daemon=True).start()
    threading.Thread(target=_health_loop, daemon=True).start()
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    threading.Thread(target=_keep_loop, daemon=True).start()
    threading.Thread(target=_log_file_loop, daemon=True).start()
    notify(f"Pibrary v{VERSION} started", "info")

    old_port = _cfg["revert_port"]
    try:
        httpd = PibraryServer(("", PORT), PibraryHandler)
    except OSError as exc:
        if not old_port or old_port == PORT:
            raise
        log_event(f"Port {PORT} cannot be used ({exc}); going back to port {old_port}", "err")
        notify(f"Port {PORT} could not be used ({exc}); back on port {old_port}", "err")
        _cfg_apply_internal({"port": old_port, "revert_port": 0, "revert_deadline": 0})
        PORT = _BOOT_CFG_PORT = old_port
        old_port = 0
        httpd = PibraryServer(("", PORT), PibraryHandler)
    if old_port and old_port != PORT and not port_override:
        left = max(60, int(_cfg["revert_deadline"] - time.time()))
        _keep_arm("port", left, f"The port changed from {old_port} to {PORT}", {"old": old_port})
    elif old_port:
        _cfg_apply_internal({"revert_port": 0, "revert_deadline": 0})
    threading.Thread(target=_sd_watchdog_loop, daemon=True).start()

    def _on_sigterm(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)
    _sd_notify("READY=1")
    print(f"Starting Pibrary v{VERSION} on port {PORT}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Pibrary server.")
    finally:
        try:
            _pos_flush()
            log_event("Pibrary stopping", "info")
            _log_file_flush()
        except Exception:
            pass
        httpd.server_close()
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pibrary - media library dashboard (Pi Zero 2W)")
    parser.add_argument("--install", action="store_true", help="Install Pibrary as a systemd service & start")
    parser.add_argument("--uninstall", action="store_true", help="Stop & remove the Pibrary systemd service")
    parser.add_argument("--port", type=int, default=None, help="Override the configured port for this run")
    parser.add_argument("--config", default=None, help="Path to the INI config file")
    args = parser.parse_args()

    if args.config:
        CONFIG_PATH = os.path.abspath(args.config)
        CONFIG_DIR = os.path.dirname(CONFIG_PATH)

    if args.install:
        install_service()
    elif args.uninstall:
        uninstall_service()
    else:
        run(args.port)
