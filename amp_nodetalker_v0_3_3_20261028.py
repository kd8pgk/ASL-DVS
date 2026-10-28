#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import array
import base64
import configparser
import glob
import hashlib
import hmac
import http.client
import ipaddress
import json
import math
import operator
import os
import pwd
import re
import secrets
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.3.3.1"
DATE_STR = "2026-10-28"
APP_NAME = "Node Talker for AMP"

INSTALL_BIN_PATH = "/usr/local/bin/amp_nodetalker.py"
INSTALL_DIR = "/usr/local/lib/asl_dvs/amp_nodetalker"
SERVICE_NAME = "amp_nodetalker.service"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/amp_nodetalker.service"
LEGACY_BIN_PATH = "/usr/local/bin/amp_nodelisten.py"
LEGACY_INSTALL_DIR = "/usr/local/lib/asl_dvs/amp_nodelisten"
LEGACY_SERVICE = "amp_nodelisten.service"
LEGACY_SERVICE_PATH = "/etc/systemd/system/amp_nodelisten.service"
_SYSTEMD_UNIT_DIR = "/etc/systemd/system"

CONFIG_DIR = os.environ.get("NODETALKER_CONFIG_DIR", "/etc/asl_dvs")
CONFIG_PATH = os.path.join(CONFIG_DIR, "amp_nodetalker.conf")
CONFIG_SECTION = "amp_nodetalker"
LEGACY_SECTION = "amp_nodelisten"
BACKUP_DIR = os.path.join(CONFIG_DIR, "amp_nodetalker_backups")
BACKUP_KEEP = 10

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

SYSTEMD_SERVICE_CONTENT = f"""[Unit]
Description=Node Talker for AMP: AMP node audio in the browser
After=network.target amp-server.service

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
Alias=amp_nodelisten.service
"""

MAX_JSON_BYTES = 64 * 1024
FRAME_SAMPLES = 160
FRAME_BYTES = FRAME_SAMPLES * 2
FRAME_SEC = 0.02
IN_QUEUE_MAX = 25
IN_QUEUE_TRIM = 10
LISTENER_QUEUE_MAX = 150
ACTIVE_DB = -50.0
ACTIVE_HOLD_SEC = 0.6

_START_TIME = time.time()

_log = deque(maxlen=400)
_log_lock = threading.Lock()
_log_seq = 0
_LOG_CTRL_RE = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]")


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


def log_event(message, level="info"):
    global _log_seq
    msg = _LOG_CTRL_RE.sub(" ", str(message))
    with _log_lock:
        _log_seq += 1
        _log.append({"id": _log_seq, "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "level": level, "msg": msg})
    try:
        print(f"[{level}] {msg}", flush=True)
    except Exception:
        pass


DEFAULT_CONFIG = {
    "port": 8993,
    "node": "",
    "amp_host": "127.0.0.1",
    "amp_iax_port": 0,
    "amp_http_port": 0,
    "amp_http_pwd": "",
    "amp_config": "",
    "amp_user": "nodelisten",
    "amp_secret": "",
    "amp_caller": "1921",
    "login_user": "",
    "max_listeners": 3,
    "public_listen": False,
    "https": True,
    "tot_sec": 120,
    "busy_lockout": True,
    "tune_enabled": False,
    "tx_gain_db": 0,
    "rx_gain_db": 0,
    "jitter_ms": 250,
    "tx_buffer_ms": 120,
    "allow_wan": False,
    "rx_hpf": True,
    "rx_agc": True,
    "rx_gate": 1,
}


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _norm_int(lo, hi, error):
    def norm(value):
        v = int(str(value).strip())
        if not lo <= v <= hi:
            raise ValueError(error)
        return v
    return norm


_norm_port = _norm_int(1024, 65535, "port must be 1024-65535")
_norm_listeners = _norm_int(1, 10, "max_listeners must be 1-10")
_norm_tot = _norm_int(30, 600, "tot_sec must be 30-600")
_norm_txbuf = _norm_int(40, 400, "tx_buffer_ms must be 40-400")
_norm_jitter = _norm_int(100, 1500, "jitter_ms must be 100-1500")


def _norm_node(value):
    v = str(value).strip()
    if v and not re.fullmatch(r"\d{1,7}", v):
        raise ValueError("node must be a node number")
    return v


def _norm_port0(value):
    v = int(str(value).strip() or 0)
    if v and not 1 <= v <= 65535:
        raise ValueError("AMP ports must be 1-65535, or 0 to read them from AMP")
    return v


def _norm_host(value):
    v = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,253}", v):
        raise ValueError("amp_host must be a host name or IPv4 address")
    return v


def _norm_word(name, pattern, error):
    def norm(value):
        v = str(value).strip()
        if not re.fullmatch(pattern, v):
            raise ValueError(f"{name} {error}")
        return v
    return norm


def _norm_amp_user(value):
    v = _norm_word("amp_user", r"[A-Za-z0-9_.-]{1,32}", "must be letters, digits, dot, dash or underscore (up to 32)")(value)
    if v == "radio":
        raise ValueError("amp_user can't be radio: AMP treats that as a public node")
    return v


def _norm_path(value):
    v = str(value).strip()
    if v and (not v.startswith("/") or any(c in v for c in "\r\n\0")):
        raise ValueError("amp_config must be an absolute path")
    return v


def _norm_secret(value):
    v = str(value).strip()
    if v and not re.fullmatch(r"[A-Za-z0-9]{16,64}", v):
        raise ValueError("amp_secret must be 16-64 letters and digits")
    return v


def _norm_gain(value):
    v = int(round(float(str(value).strip())))
    if not -12 <= v <= 12:
        raise ValueError("gains must be -12 to +12 dB")
    return v


_NORMALIZERS = {
    "port": _norm_port,
    "node": _norm_node,
    "amp_host": _norm_host,
    "amp_iax_port": _norm_port0,
    "amp_http_port": _norm_port0,
    "amp_http_pwd": _norm_word("amp_http_pwd", r"[!-~]{0,64}", "must be up to 64 printable characters without spaces"),
    "amp_config": _norm_path,
    "amp_user": _norm_amp_user,
    "amp_secret": _norm_secret,
    "amp_caller": _norm_word("amp_caller", r"\d{1,7}", "must be a node number (digits)"),
    "login_user": _norm_word("login_user", r"[a-z_][a-z0-9_.-]{0,31}|", "must be a Linux user name"),
    "max_listeners": _norm_listeners,
    "public_listen": _parse_bool,
    "https": _parse_bool,
    "tot_sec": _norm_tot,
    "busy_lockout": _parse_bool,
    "tune_enabled": _parse_bool,
    "tx_gain_db": _norm_gain,
    "rx_gain_db": _norm_gain,
    "jitter_ms": _norm_jitter,
    "tx_buffer_ms": _norm_txbuf,
    "allow_wan": _parse_bool,
    "rx_hpf": _parse_bool,
    "rx_agc": _parse_bool,
    "rx_gate": _norm_int(0, 2, "rx_gate must be 0, 1 or 2"),
}

_config = dict(DEFAULT_CONFIG)
_config_lock = threading.Lock()


def _cfg_get(key):
    with _config_lock:
        return _config[key]


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cp = configparser.ConfigParser()
    try:
        cp.read(CONFIG_PATH)
    except configparser.Error as exc:
        log_event(f"Config: {CONFIG_PATH} could not be read ({exc}); using defaults", "warn")
    sec = CONFIG_SECTION if cp.has_section(CONFIG_SECTION) else LEGACY_SECTION
    if cp.has_section(sec):
        for key, norm in _NORMALIZERS.items():
            if cp.has_option(sec, key):
                try:
                    cfg[key] = norm(cp.get(sec, key))
                except ValueError as exc:
                    log_event(f"Config: bad {key} ({exc}); using {DEFAULT_CONFIG[key]}", "warn")
    if not cfg["amp_secret"]:
        cfg["amp_secret"] = secrets.token_hex(12)
        try:
            save_config(cfg)
        except OSError as exc:
            log_event(f"Config: could not save the new AMP password ({exc})", "warn")
    with _config_lock:
        _config.clear()
        _config.update(cfg)
    return cfg


def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _atomic_write(path, data, mode=0o644, like=None):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if like is not None:
        atomic_write(path, data, new_mode=like.st_mode & 0o7777)
    else:
        atomic_write(path, data, mode=mode)


def save_config(cfg):
    body = [f"{key} = {'true' if cfg[key] is True else 'false' if cfg[key] is False else cfg[key]}" for key in DEFAULT_CONFIG]
    lines = [f"[{CONFIG_SECTION}]"] + body + ["", f"[{LEGACY_SECTION}]"] + body
    _atomic_write(CONFIG_PATH, "\n".join(lines) + "\n", 0o600)


_SECRET_KEYS = ("amp_secret",)
_HIDDEN_KEYS = ("amp_secret", "amp_http_pwd")
_AMP_KEYS = ("node", "amp_host", "amp_iax_port", "amp_http_port", "amp_http_pwd", "amp_config", "amp_user", "amp_caller")


def public_config(cfg):
    out = {k: v for k, v in cfg.items() if k not in _HIDDEN_KEYS}
    out["amp_http_pwd_set"] = bool(cfg["amp_http_pwd"])
    return out


def config_update(body):
    with _config_lock:
        old = dict(_config)
    cfg = dict(old)
    errors = []
    for key, norm in _NORMALIZERS.items():
        if key in body and key not in _SECRET_KEYS:
            try:
                cfg[key] = norm(body[key])
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    try:
        save_config(cfg)
    except OSError as exc:
        return {"ok": False, "error": f"could not save {CONFIG_PATH}: {exc}"}
    with _config_lock:
        _config.update(cfg)
    restart = any(cfg[k] != old[k] for k in ("port", "https"))
    msg = "Saved."
    if any(cfg[k] != old[k] for k in _AMP_KEYS):
        _amp_info_cache["t"] = -AMP_INFO_TTL
        AMP_LINK.redial("settings changed")
        msg += " Node Talker links to AMP again with the new setting."
    if restart:
        msg += " Node Talker restarts to use the new setting."
        if not _schedule_restart():
            msg += " (Restart it by hand: systemctl restart amp_nodetalker)"
    log_event(f"Config saved: {json.dumps(public_config(cfg))}", "ok")
    return {"ok": True, "message": msg.strip(), "restart": restart}


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
_crypt_lock = threading.Lock()


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
        with _crypt_lock:
            result = _libcrypt_handle.crypt(password.encode("utf-8", "surrogateescape"),
                                            stored_hash.encode("utf-8", "surrogateescape"))
            result = result.decode("utf-8", "surrogateescape") if result is not None else None
    except Exception as exc:
        log_event(f"_crypt_verify: crypt(3) call failed: {exc}", "warn")
        return False
    if result is None:
        return False
    return hmac.compare_digest(result, stored_hash)


def _usable_hash(account):
    stored = _read_shadow_hash(account)
    return bool(stored) and stored[0] not in ("!", "*")


def auth_account():
    acct = _cfg_get("login_user")
    if acct:
        return acct
    if _usable_hash("root"):
        return "root"
    return amp_info()["user"] or "root"


def _verify_root_password(password):
    if not password:
        return False
    acct = auth_account()
    try:
        import pam as _pam_mod
        return bool(_pam_mod.pam().authenticate(acct, password, service="login"))
    except ImportError:
        pass
    except Exception as exc:
        log_event(f"_verify_root_password: PAM check errored, trying shadow fallback: {exc}", "warn")
    try:
        stored = _read_shadow_hash(acct)
        if not stored or stored[0] in ("!", "*"):
            return False
        return _crypt_verify(password, stored)
    except Exception as exc:
        log_event(f"_verify_root_password: shadow fallback failed: {exc}", "warn")
        return False


def _root_backend_available():
    import importlib.util
    if importlib.util.find_spec("pam") is not None:
        return True
    return _usable_hash(auth_account())


_SESSION_COOKIE_NAME = "amp_nodetalker_session"
_SESSION_TTL_SEC = 12 * 3600
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
    now = time.time()
    with _sessions_lock:
        exp = _sessions.get(token)
        if exp is None or exp <= now:
            _sessions.pop(token, None)
            return False
        _sessions[token] = now + _SESSION_TTL_SEC
        return True


def _revoke_session(token):
    with _sessions_lock:
        _sessions.pop(token, None)


def _session_cookie_header(token, max_age):
    return f"{_SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"


_auth_failures = {}
_auth_failures_lock = threading.Lock()
AUTH_MAX_FAILURES = 5
AUTH_LOCKOUT_BASE_SEC = 5
AUTH_LOCKOUT_MAX_SEC = 300
AUTH_FORGET_SEC = 3600
AUTH_TRACK_MAX = 1000
WAN_FAIL_MAX = 20
WAN_FAIL_WINDOW_SEC = 600
_wan_failures = deque(maxlen=WAN_FAIL_MAX)


def _prune_auth(now):
    for ip in [k for k, r in _auth_failures.items() if now - r["last"] > AUTH_FORGET_SEC and r["locked_until"] <= now]:
        del _auth_failures[ip]
    while len(_auth_failures) > AUTH_TRACK_MAX:
        del _auth_failures[min(_auth_failures, key=lambda k: _auth_failures[k]["last"])]
    while _wan_failures and now - _wan_failures[0] > WAN_FAIL_WINDOW_SEC:
        _wan_failures.popleft()


def _auth_lockout_remaining(client_ip, wan=False):
    now = time.time()
    with _auth_failures_lock:
        _prune_auth(now)
        rec = _auth_failures.get(client_ip)
        wait = max(0, rec["locked_until"] - now) if rec else 0
        if wan and len(_wan_failures) >= WAN_FAIL_MAX:
            wait = max(wait, _wan_failures[0] + WAN_FAIL_WINDOW_SEC - now)
        return wait


def _record_auth_failure(client_ip, wan=False):
    now = time.time()
    with _auth_failures_lock:
        if wan:
            _wan_failures.append(now)
            if len(_wan_failures) == WAN_FAIL_MAX:
                log_event(f"Auth: {WAN_FAIL_MAX} failed internet logins in {WAN_FAIL_WINDOW_SEC // 60} min; "
                          "internet logins wait until that window ends", "warn")
        rec = _auth_failures.setdefault(client_ip, {"fails": 0, "locked_until": 0})
        rec["fails"] += 1
        rec["last"] = now
        _prune_auth(now)
        if rec["fails"] >= AUTH_MAX_FAILURES:
            backoff = min(AUTH_LOCKOUT_BASE_SEC * (2 ** (rec["fails"] - AUTH_MAX_FAILURES)),
                          AUTH_LOCKOUT_MAX_SEC)
            rec["locked_until"] = time.time() + backoff
            log_event(f"Auth: {client_ip} locked out for {backoff}s after {rec['fails']} failed attempts", "warn")


def _record_auth_success(client_ip):
    with _auth_failures_lock:
        _auth_failures.pop(client_ip, None)


_TAILNET = ipaddress.ip_network("100.64.0.0/10")
_PROXY_HEADERS = ("Forwarded", "X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP", "Tailscale-Funnel-Request")


def _parse_ip(text):
    try:
        ip = ipaddress.ip_address(str(text).strip().strip("[]"))
    except ValueError:
        return None
    return ip.ipv4_mapped or ip if ip.version == 6 else ip


def _is_lan(text):
    ip = _parse_ip(text)
    if ip is None:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or (ip.version == 4 and ip in _TAILNET)


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


def _http_responsive(port, tls=False):
    try:
        if tls:
            conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=5, context=ssl._create_unverified_context())
        else:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            resp.read()
            return resp.status == 200
        finally:
            conn.close()
    except Exception:
        return False


def _sd_watchdog_loop(port, tls=False):
    if not os.environ.get("NOTIFY_SOCKET"):
        return
    try:
        interval_usec = int(os.environ.get("WATCHDOG_USEC", "0"))
    except ValueError:
        interval_usec = 0
    period = (interval_usec / 1e6 / 2.0) if interval_usec > 0 else 30.0
    period = max(5.0, min(period, 300.0))
    log_event(f"systemd watchdog active, pinging every {period:.0f}s while healthy")
    warned = False
    while True:
        try:
            now = time.monotonic()
            pump_ok = now - HUB.pump_beat < 5.0 and now - TALKER.beat < 5.0 and now - AMP_LINK.beat < 15.0
            if pump_ok and _http_responsive(port, tls):
                _sd_notify("WATCHDOG=1")
                warned = False
            elif not warned:
                warned = True
                log_event("Health check failed (web server or audio pump); withholding the watchdog ping", "err")
        except Exception:
            pass
        time.sleep(period)


def _schedule_restart():
    if not os.environ.get("NOTIFY_SOCKET") or os.geteuid() != 0:
        return False
    try:
        subprocess.Popen(["systemd-run", "--quiet", "--collect", "--on-active=2",
                          "--unit=amp-nodetalker-selfrestart", "systemctl", "restart", SERVICE_NAME],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as exc:
        log_event(f"Restart scheduling failed: {exc}", "err")
        return False


def _ulaw_byte(s):
    sign = 0x80 if s < 0 else 0
    if s < 0:
        s = -s
    if s > 32635:
        s = 32635
    s += 0x84
    exponent = min(7, max(0, s.bit_length() - 8))
    mantissa = (s >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


ULAW_TABLE = bytes(_ulaw_byte(i - 65536 if i >= 32768 else i) for i in range(65536))
ULAW_SILENCE = bytes([ULAW_TABLE[0]]) * FRAME_SAMPLES
PCM_SILENCE = b"\x00" * FRAME_BYTES


def _samples(frame, code="h"):
    a = array.array(code)
    a.frombytes(frame)
    return a


def ulaw_encode(frame):
    return bytes(map(ULAW_TABLE.__getitem__, _samples(frame, "H")))


def frame_db(frame):
    a = _samples(frame)
    if not a:
        return -120.0
    ms = sum(x * x for x in a) / len(a)
    if ms <= 0:
        return -120.0
    return max(-120.0, 10.0 * math.log10(ms / (32768.0 * 32768.0)))


def tune_value(key):
    if not _cfg_get("tune_enabled"):
        return DEFAULT_CONFIG[key]
    return _cfg_get(key)


GAIN_KNEE = 29000
GAIN_SPAN = 32767 - GAIN_KNEE


def apply_gain(frame, gain_db):
    if not gain_db:
        return frame
    g = 10.0 ** (gain_db / 20.0)
    a = _samples(frame)
    for i, x in enumerate(a):
        v = x * g
        if v > GAIN_KNEE:
            v = GAIN_KNEE + GAIN_SPAN * math.tanh((v - GAIN_KNEE) / GAIN_SPAN)
        elif v < -GAIN_KNEE:
            v = -GAIN_KNEE - GAIN_SPAN * math.tanh((-v - GAIN_KNEE) / GAIN_SPAN)
        a[i] = int(round(v))
    return a.tobytes()


def fade_out(frame):
    a = _samples(frame)
    n = len(a)
    for i in range(n):
        a[i] = int(round(a[i] * (n - 1 - i) / n))
    return a.tobytes()


def peak_db(frame):
    a = _samples(frame)
    if not a:
        return -120.0
    pk = max(max(a), -min(a))
    return -120.0 if pk <= 0 else max(-120.0, 20.0 * math.log10(pk / 32768.0))


def _hp_section(q, fc=300.0, fs=8000.0):
    w = 2 * math.pi * fc / fs
    c, al = math.cos(w), math.sin(w) / (2 * q)
    a0 = 1 + al
    return ((1 + c) / 2 / a0, -(1 + c) / a0, (1 + c) / 2 / a0, -2 * c / a0, (1 - al) / a0)


HP_SECTIONS = (_hp_section(0.5412), _hp_section(1.3066))


def _dot(a, b):
    if hasattr(math, "sumprod"):
        return math.sumprod(a, b)
    return math.fsum(map(operator.mul, a, b))
AGC_TARGET_DB = -20.0
AGC_MIN_DB = -6.0
AGC_MAX_DB = 18.0
AGC_ACTIVE_DB = -45.0
GATE_DELAY = 4
RX_QUIET_DB = -65.0
GATE_RULES = {1: {"close_db": -55.0, "hold": 20, "r1": 0.3, "noise_db": -24.0, "frames": 4},
              2: {"close_db": -48.0, "hold": 12, "r1": 0.45, "noise_db": -30.0, "frames": 3}}
SPEECH_R1 = 0.55


class RxClean:
    def __init__(self):
        self.reset()
        self.busy_sec = 0.0
        self.load_pct = 0.0
        self._load_t = time.monotonic()

    def reset(self):
        self.z = (0.0,) * 8
        self.gain_db = 0.0
        self.level_s = None
        self.fast = 0
        self.idle = 999
        self.open = False
        self.quiet = 0
        self.noisy = 0
        self.tail = False
        self.calm = 0
        self.delay = deque()
        self.prev_g = 1.0

    def _filter(self, a, hpf):
        if not hpf:
            ys = [float(v) for v in a]
        else:
            (b0, b1, b2, a1, a2), (c0, c1, c2, d1, d2) = HP_SECTIONS
            x1, x2, w1, w2, p1, p2, y1, y2 = self.z
            ys = []
            for v in a:
                w = b0 * v + b1 * x1 + b2 * x2 - a1 * w1 - a2 * w2
                x2, x1, w2, w1 = x1, v, w1, w
                y = c0 * w + c1 * p1 + c2 * p2 - d1 * y1 - d2 * y2
                p2, p1, y2, y1 = p1, w, y1, y
                ys.append(y)
            self.z = (x1, x2, w1, w2, p1, p2, y1, y2)
        n = len(ys)
        ss = _dot(ys, ys)
        r1 = _dot(ys[1:], ys[:-1]) / ss if ss > 0 else 1.0
        db = 10.0 * math.log10(ss / n / 1073741824.0) if ss > 0 else -120.0
        return ys, db, r1

    def _agc(self, db, speechy):
        if not speechy:
            self.idle += 1
            return
        if self.idle > 50:
            self.fast = 25
        self.idle = 0
        p = 10.0 ** (db / 10.0)
        self.level_s = p if self.level_s is None else 0.85 * self.level_s + 0.15 * p
        want = AGC_TARGET_DB - 10.0 * math.log10(max(self.level_s, 1e-12))
        want = max(AGC_MIN_DB, min(AGC_MAX_DB, want))
        if want < self.gain_db:
            self.gain_db = max(want, self.gain_db - 1.5)
        else:
            self.gain_db = min(want, self.gain_db + (0.5 if self.fast > 0 else 0.06))
        if self.fast > 0:
            self.fast -= 1

    def _gate(self, db, r1, mode):
        r = GATE_RULES[mode]
        if db > r["noise_db"] and r1 < r["r1"]:
            self.noisy += 1
            self.calm = 0
        else:
            self.noisy = 0
            self.calm = self.calm + 1 if r1 > SPEECH_R1 and db > r["close_db"] + 3 else 0
            if self.tail and self.calm >= 3:
                self.tail = False
        hit = self.noisy >= r["frames"] and self.open
        if hit and not self.tail:
            self.tail = True
        if db < r["close_db"]:
            self.quiet += 1
            if self.quiet >= r["hold"]:
                self.open = False
                self.tail = False
        else:
            self.quiet = 0
            if db > r["close_db"] + 3 and not self.tail:
                self.open = True
        return self.open and not self.tail, hit

    def _out(self, pcm, keep, t0):
        self.delay.append((pcm, keep))
        if len(self.delay) <= GATE_DELAY:
            self._account(t0)
            return PCM_SILENCE
        pcm, keep = self.delay.popleft()
        nxt = self.delay[0][1] if self.delay else keep
        if keep and not nxt:
            pcm = fade_out(pcm)
        self._account(t0)
        return pcm if keep else PCM_SILENCE

    def process(self, frame, user_db, raw_db=0.0):
        t0 = time.perf_counter()
        hpf, agc, gate = _cfg_get("rx_hpf"), _cfg_get("rx_agc"), _cfg_get("rx_gate")
        if not (hpf or agc or gate):
            if self.delay or any(self.z) or self.gain_db:
                self.reset()
            out = apply_gain(frame, user_db)
            self._account(t0)
            return out
        if raw_db < RX_QUIET_DB:
            self.z = (0.0,) * 8
            self.idle += 1
            if not gate:
                self.delay.clear()
                self._account(t0)
                return PCM_SILENCE
            self._gate(-120.0, 1.0, gate)
            return self._out(PCM_SILENCE, False, t0)
        ys, db, r1 = self._filter(_samples(frame), hpf)
        speechy = db > AGC_ACTIVE_DB and r1 > 0.3
        if agc:
            self._agc(db, speechy)
        elif self.gain_db:
            self.gain_db = 0.0
        g1 = 10.0 ** ((self.gain_db + (user_db or 0)) / 20.0)
        g0, self.prev_g = self.prev_g, g1
        n = len(ys)
        if max(map(abs, ys), default=0.0) * max(g0, g1) <= GAIN_KNEE:
            if abs(g1 - g0) < 1e-6:
                out = array.array("h", map(round, map(g1.__mul__, ys)))
            else:
                step = (g1 - g0) / n
                out = array.array("h", [round(y * (g0 + step * i)) for i, y in enumerate(ys)])
        else:
            out = array.array("h", bytes(2 * n))
            for i, y in enumerate(ys):
                v = y * (g0 + (g1 - g0) * i / n)
                if v > GAIN_KNEE:
                    v = GAIN_KNEE + GAIN_SPAN * math.tanh((v - GAIN_KNEE) / GAIN_SPAN)
                elif v < -GAIN_KNEE:
                    v = -GAIN_KNEE - GAIN_SPAN * math.tanh((-v - GAIN_KNEE) / GAIN_SPAN)
                out[i] = int(round(v))
        pcm = out.tobytes()
        if not gate:
            if self.delay:
                self.delay.clear()
            self._account(t0)
            return pcm
        keep, hit = self._gate(db, r1, gate)
        if hit:
            for i in range(len(self.delay)):
                self.delay[i] = (self.delay[i][0], False)
        return self._out(pcm, keep, t0)

    def idle_tick(self):
        self.idle += 1
        if self.idle > 150 and (self.delay or self.open):
            self.delay.clear()
            self.open = False
            self.tail = False

    def _account(self, t0):
        now = time.perf_counter()
        self.busy_sec += now - t0
        if now - self._load_t >= 5.0:
            self.load_pct = round(100.0 * self.busy_sec / (now - self._load_t), 1)
            self.busy_sec = 0.0
            self._load_t = now


RXC = RxClean()


def paced_loop(step, what):
    nxt = time.monotonic()
    while True:
        nxt += FRAME_SEC
        delay = nxt - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        elif delay < -0.5:
            nxt = time.monotonic()
        try:
            step()
        except Exception as exc:
            log_event(f"{what} error: {exc}", "err")


class _Listener:
    __slots__ = ("q", "closed", "ip", "since", "pcm")

    def __init__(self, ip, pcm=False):
        self.q = deque(maxlen=LISTENER_QUEUE_MAX)
        self.closed = False
        self.ip = ip
        self.since = time.time()
        self.pcm = pcm


class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.inbuf = bytearray()
        self.frames = deque()
        self.listeners = set()
        self.packets = 0
        self.bytes_in = 0
        self.dropped = 0
        self.last_rx = 0.0
        self.level_db = -120.0
        self.peak_db = -120.0
        self.last_active = 0.0
        self.pump_beat = time.monotonic()
        self.rate_window = deque(maxlen=60)

    def feed(self, data):
        now = time.monotonic()
        with self.lock:
            self.packets += 1
            self.bytes_in += len(data)
            self.last_rx = now
            self.inbuf += data
            while len(self.inbuf) >= FRAME_BYTES:
                self.frames.append(bytes(self.inbuf[:FRAME_BYTES]))
                del self.inbuf[:FRAME_BYTES]
            while len(self.frames) > IN_QUEUE_MAX:
                self.frames.popleft()
                self.dropped += 1

    def add_listener(self, ip, pcm=False):
        with self.lock:
            if len(self.listeners) >= _cfg_get("max_listeners"):
                return None
            lst = _Listener(ip, pcm)
            self.listeners.add(lst)
        log_event(f"Listener connected from {ip}" + (" (16-bit)" if pcm else ""))
        return lst

    def remove_listener(self, lst):
        with self.cond:
            lst.closed = True
            self.listeners.discard(lst)
            self.cond.notify_all()
        log_event(f"Listener from {lst.ip} left after {int(time.time() - lst.since)}s")

    def audio_active(self):
        return time.monotonic() - self.last_active < ACTIVE_HOLD_SEC

    def wait_chunk(self, lst, timeout=5.0):
        with self.cond:
            if not lst.q and not lst.closed:
                self.cond.wait(timeout)
            if not lst.q:
                return b""
            chunk = b"".join(lst.q)
            lst.q.clear()
            return chunk

    def tick(self):
        now = time.monotonic()
        with self.lock:
            frame = self.frames.popleft() if self.frames else None
            if len(self.frames) > IN_QUEUE_TRIM:
                self.frames.popleft()
                self.dropped += 1
            have_listeners = bool(self.listeners)
        if frame is not None:
            db = frame_db(frame)
            self.level_db = db
            self.peak_db = max(db, self.peak_db - 1.0)
            if db > ACTIVE_DB:
                self.last_active = now
        else:
            self.level_db = -120.0
            self.peak_db = max(-120.0, self.peak_db - 1.0)
        if have_listeners:
            if frame is not None:
                pcm = RXC.process(frame, tune_value("rx_gain_db"), db)
            else:
                RXC.idle_tick()
                pcm = PCM_SILENCE
            enc = None
            with self.cond:
                for lst in self.listeners:
                    if lst.pcm:
                        lst.q.append(pcm)
                    else:
                        if enc is None:
                            enc = ULAW_SILENCE if pcm == PCM_SILENCE else ulaw_encode(pcm)
                        lst.q.append(enc)
                self.cond.notify_all()
        self.pump_beat = now

    def pump_loop(self):
        rate = {"t": time.monotonic(), "packets": 0}

        def count_rate():
            t = time.monotonic()
            if t - rate["t"] >= 1.0:
                self.rate_window.append(self.packets - rate["packets"])
                rate.update(t=t, packets=self.packets)

        def step():
            try:
                self.tick()
            finally:
                count_rate()

        paced_loop(step, "Audio pump")

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            n = len(self.listeners)
            listeners = [{"ip": x.ip, "secs": int(time.time() - x.since)} for x in self.listeners]
        return {
            "receiving": AMP_LINK.up(),
            "last_rx_age": round(now - self.last_rx, 1) if self.last_rx else None,
            "packets": self.packets,
            "packets_per_sec": self.rate_window[-1] if self.rate_window else 0,
            "dropped": self.dropped,
            "level_db": round(self.level_db, 1),
            "peak_db": round(self.peak_db, 1),
            "audio_active": self.audio_active(),
            "listeners": n,
            "listener_list": listeners,
            "max_listeners": _cfg_get("max_listeners"),
            "rx_load_pct": RXC.load_pct,
        }


HUB = Hub()


def build_status(full):
    st = HUB.snapshot()
    st.update({"version": VERSION, "node": _cfg_get("node"), "uptime": int(time.time() - _START_TIME),
               "jitter_ms": tune_value("jitter_ms")})
    st["node"] = main_node()
    st["link"] = AMP_LINK.snapshot()
    if full:
        ok, links, err = amp_links()
        st["links"], st["links_ok"], st["links_error"] = links, ok, err
        tx = tx_state(st["node"])
        tx.update(TALKER.state())
        st["tx"] = {k: tx.get(k) for k in ("node", "ready", "linked", "keyed", "who", "secs", "tot",
                                            "peak_db", "last_peak_db", "gaps", "last_gaps")}
    else:
        st.pop("listener_list", None)
        st.pop("rx_load_pct", None)
        st["link"] = {"state": st["link"]["state"]}
    return st


FAV_PATH = os.path.join(CONFIG_DIR, "amp_nodetalker_favorites.json")
FAV_MAX = 10
TLS_DIR = os.path.join(CONFIG_DIR, "amp_nodetalker_tls")
TLS_CERT = os.path.join(TLS_DIR, "cert.pem")
TLS_KEY = os.path.join(TLS_DIR, "key.pem")
TX_BUSY_GRACE_SEC = 1.0
TX_QUEUE_MAX = 50
TX_DEADMAN_SEC = 1.0
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
_CALL_TRIM = re.compile(r"[\x00-\x1f\x7f]")
_URI_RE = re.compile(r"^iax:[A-Za-z0-9_.-]{1,32}@\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?/(\d{1,7})(?:,[!-~]{0,64})?$")
LINK_WAIT_SEC = 15
AMP_PROCESS = "amp-server"
AMP_DEFAULT_AUTH = "/etc/ampersand/auth.txt"
AMP_INFO_TTL = 5.0
AMP_STATUS_TTL = 2.0
AMP_PING_SEC = 10.0
AMP_SILENT_SEC = 30.0
AMP_CALL_WAIT_SEC = 6.0
AMP_BACKOFF_MAX = 30.0

_probe_cache = {}


def port_open(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def port_open_cached(port, ttl=15.0):
    now = time.monotonic()
    hit = _probe_cache.get(port)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = port_open(port)
    _probe_cache[port] = (now, val)
    return val


_amp_info_cache = {"t": -AMP_INFO_TTL, "v": None}
_amp_info_lock = threading.Lock()


def _amp_args(argv):
    out = {}
    i = 1
    while i < len(argv):
        a = argv[i]
        key, eq, val = a.partition("=")
        if key in ("--config", "--httpport", "--httppwd", "--iaxport"):
            if not eq:
                i += 1
                val = argv[i] if i < len(argv) else ""
            out[key[2:]] = val
        i += 1
    return out


def _amp_processes():
    try:
        names = sorted((n for n in os.listdir("/proc") if n.isdigit()), key=int)
    except OSError:
        return []
    found = []
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/comm", "r", encoding="utf-8", errors="replace") as fh:
                if fh.read().strip() != AMP_PROCESS:
                    continue
            with open(f"/proc/{name}/cmdline", "rb") as fh:
                argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
            uid = os.stat(f"/proc/{name}").st_uid
        except OSError:
            continue
        found.append({"pid": int(name), "uid": uid, "args": _amp_args(argv)})
    return found


def _amp_process():
    procs = _amp_processes()
    want_cfg, want_port = _cfg_get("amp_config"), _cfg_get("amp_iax_port")
    for p in procs:
        if want_cfg and os.path.realpath(p["args"].get("config", "")) == os.path.realpath(want_cfg):
            return p, len(procs)
    for p in procs:
        if want_port and _port_or(p["args"].get("iaxport", "0"), 0) == want_port:
            return p, len(procs)
    return (procs[0] if procs else None), len(procs)


def _user_of(uid):
    try:
        pw = pwd.getpwuid(uid)
        return pw.pw_name, pw.pw_dir, pw.pw_gid
    except (KeyError, OverflowError):
        return "", "", None


def _amp_config_guess():
    homes = ["/root"] + sorted(glob.glob("/home/*"))
    for h in homes:
        p = os.path.join(h, "amp-server.json")
        if os.path.isfile(p):
            return p
    return ""


def _port_or(value, default):
    try:
        v = int(str(value).strip())
    except ValueError:
        return default
    return v if 0 < v < 65536 else default


def amp_info(max_age=AMP_INFO_TTL):
    now = time.monotonic()
    with _amp_info_lock:
        if _amp_info_cache["v"] is not None and now - _amp_info_cache["t"] < max_age:
            return dict(_amp_info_cache["v"])
    proc, count = _amp_process()
    info = {"running": proc is not None, "pid": proc["pid"] if proc else None, "count": count, "user": "", "uid": None, "gid": None,
            "config": "", "config_error": "", "node": "", "callsign": "", "iax_port": 4569, "http_port": 8080,
            "http_pwd": "", "auth_file": AMP_DEFAULT_AUTH}
    args = proc["args"] if proc else {}
    home = ""
    if proc:
        info["uid"] = proc["uid"]
        info["user"], home, info["gid"] = _user_of(proc["uid"])
    path = _cfg_get("amp_config") or args.get("config") or (os.path.join(home, "amp-server.json") if home else "") or _amp_config_guess()
    info["config"] = path
    cfg = {}
    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            if not isinstance(cfg, dict):
                cfg, info["config_error"] = {}, "not a JSON object"
        except (OSError, ValueError) as exc:
            info["config_error"] = str(exc)
    else:
        info["config_error"] = "AMP's configuration file was not found"
    info["node"] = str(cfg.get("node", "")).strip()
    info["callsign"] = str(cfg.get("callsign", "")).strip()[:16]
    info["iax_port"] = _port_or(args.get("iaxport", "0"), 0) or _port_or(cfg.get("iaxPort", ""), 4569)
    info["http_port"] = _port_or(args.get("httpport", ""), 8080)
    info["http_pwd"] = args.get("httppwd", "")
    if str(cfg.get("authFile", "")).strip():
        info["auth_file"] = str(cfg["authFile"]).strip()
    with _amp_info_lock:
        _amp_info_cache.update(t=now, v=dict(info))
    return info


def amp_target():
    info = amp_info()
    return {"host": _cfg_get("amp_host"), "iax_port": _cfg_get("amp_iax_port") or info["iax_port"],
            "http_port": _cfg_get("amp_http_port") or info["http_port"],
            "http_pwd": _cfg_get("amp_http_pwd") or info["http_pwd"],
            "node": _cfg_get("node") or info["node"], "user": _cfg_get("amp_user"),
            "secret": _cfg_get("amp_secret"), "caller": _cfg_get("amp_caller")}


def main_node():
    return amp_target()["node"]


def amp_http(method, path, body=None, timeout=4):
    t = amp_target()
    headers = {}
    if t["http_pwd"]:
        headers["Authorization"] = "Basic " + base64.b64encode(f"user:{t['http_pwd']}".encode("utf-8")).decode("ascii")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        conn = http.client.HTTPConnection(t["host"], t["http_port"], timeout=timeout)
        try:
            conn.request(method, path, data, headers)
            resp = conn.getresponse()
            raw = resp.read(256 * 1024)
        finally:
            conn.close()
    except (OSError, http.client.HTTPException) as exc:
        return None, f"AMP's web port {t['host']}:{t['http_port']} did not answer ({exc})"
    if resp.status == 401:
        return None, "AMP's web page wants a password: set it on the Setup tab (AMP link, Advanced)"
    if resp.status != 200:
        return None, f"AMP answered HTTP {resp.status}"
    if method == "POST":
        return {}, ""
    try:
        return json.loads(raw.decode("utf-8")), ""
    except (ValueError, UnicodeDecodeError):
        return None, "AMP sent something that is not JSON"


_amp_status = {"t": -AMP_STATUS_TTL, "ok": False, "calls": [], "error": "", "message": "", "stamp": 0}
_amp_status_lock = threading.Lock()


def amp_calls(max_age=AMP_STATUS_TTL):
    with _amp_status_lock:
        c = _amp_status
        if time.monotonic() - c["t"] < max_age:
            return c["ok"], list(c["calls"]), c["error"], c["message"]
    d, err = amp_http("GET", "/status", timeout=3)
    calls, msg, stamp = [], "", 0
    if isinstance(d, dict):
        for x in d.get("calls") or []:
            if not isinstance(x, dict):
                continue
            calls.append({"node": str(x.get("remoteNode", "")), "line": x.get("lineId"), "call": x.get("callId"),
                          "active": bool(x.get("rxActive")), "permanent": bool(x.get("permanent")),
                          "talker": _CALL_TRIM.sub(" ", str(x.get("talkerid", "")))[:40]})
        m = d.get("message")
        if isinstance(m, dict):
            msg = _CALL_TRIM.sub(" ", str(m.get("text", "")))[:160]
            stamp = m.get("stamp") if isinstance(m.get("stamp"), (int, float)) else 0
    ok = d is not None
    with _amp_status_lock:
        _amp_status.update(t=time.monotonic(), ok=ok, calls=calls, error=err, message=msg, stamp=stamp)
    return ok, list(calls), err, msg


def amp_message_stamp():
    with _amp_status_lock:
        return _amp_status["stamp"]


def _amp_status_invalidate():
    with _amp_status_lock:
        _amp_status["t"] = -AMP_STATUS_TTL


def amp_links():
    ok, calls, err, _ = amp_calls()
    me = _cfg_get("amp_caller")
    links = []
    for c in calls:
        if c["node"] == me:
            continue
        state = ("talking" + (": " + c["talker"] if c["talker"] else "")) if c["active"] else ("permanent" if c["permanent"] else "linked")
        links.append({"node": c["node"], "state": state})
    return ok, links, err


def _norm_fav(f):
    if not isinstance(f, dict):
        raise ValueError("bad favorite")
    num = str(f.get("num", "")).strip()
    if num.lower().startswith("iax:"):
        if not _URI_RE.match(num):
            raise ValueError("A direct address looks like iax:user@192.168.1.20:4569/12345,password")
    elif not num.isdigit() or int(num) <= 0 or len(num) > 7:
        raise ValueError("Node number must be digits (up to 7), or a direct iax: address")
    else:
        num = str(int(num))
    if fav_target({"num": num}) in (_cfg_get("amp_caller"), main_node()):
        raise ValueError(f"{fav_target({'num': num})} is this node or Node Talker itself, not a favorite")
    label = _CALL_TRIM.sub(" ", str(f.get("label", ""))).strip()[:40]
    return {"mode": "ASL", "num": num, "label": label or f"Node {fav_target({'num': num})}"}


def fav_target(f):
    m = _URI_RE.match(f["num"])
    return m.group(1) if m else f["num"]


def fav_name(f):
    return f"node {fav_target(f)}"


def fav_load():
    try:
        with open(FAV_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for f in data if isinstance(data, list) else []:
        try:
            out.append(_norm_fav(f))
        except ValueError:
            continue
    return out[:FAV_MAX]


def fav_save(items):
    if not isinstance(items, list):
        return {"ok": False, "error": "favorites must be a list"}
    if len(items) > FAV_MAX:
        return {"ok": False, "error": f"At most {FAV_MAX} favorites."}
    try:
        clean = [_norm_fav(f) for f in items]
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    seen = set()
    for f in clean:
        key = fav_target(f)
        if key in seen:
            return {"ok": False, "error": f"Node {key} is listed twice."}
        seen.add(key)
    try:
        _atomic_write(FAV_PATH, json.dumps(clean, indent=1) + "\n", 0o600)
    except OSError as exc:
        return {"ok": False, "error": f"Could not save: {exc}"}
    log_event(f"Favorites saved ({len(clean)})", "ok")
    return {"ok": True, "message": f"Saved {len(clean)} favorite(s).", "favs": clean}


def amp_favorites():
    d, err = amp_http("GET", "/favorites")
    out = []
    for x in d if isinstance(d, list) else []:
        if not isinstance(x, dict):
            continue
        try:
            out.append(_norm_fav({"num": str(x.get("n", "")), "label": str(x.get("l", ""))}))
        except ValueError:
            continue
    return out[:200], err


def wait_link(target, since, wait=LINK_WAIT_SEC):
    deadline = time.monotonic() + wait
    while True:
        ok, calls, _, msg = amp_calls(max_age=0)
        if any(c["node"] == target for c in calls):
            return "up", msg
        if amp_message_stamp() != since and target in msg and "fail" in msg.lower():
            return "down", msg
        if time.monotonic() >= deadline:
            return ("down" if ok else "unknown"), msg
        time.sleep(1)


def fav_connect(index):
    favs = fav_load()
    try:
        f = favs[int(index)]
    except (ValueError, TypeError, IndexError):
        return {"ok": False, "error": "Pick a favorite."}
    node = main_node()
    if not node:
        return {"ok": False, "error": "AMP's node number is not set (AMP's Configuration page)."}
    target = fav_target(f)
    ok, calls, err, _ = amp_calls(max_age=0)
    if not ok:
        return {"ok": False, "error": err}
    if any(c["node"] == target for c in calls):
        return {"ok": True, "message": f"Node {node} is already connected to {fav_name(f)}."}
    since = amp_message_stamp()
    _, err = amp_http("POST", "/status-pressed", {"action": "call", "node": f["num"]})
    if err:
        return {"ok": False, "error": err}
    log_event(f"Connect {fav_name(f)} from node {node}", "ok")
    state, msg = wait_link(target, since)
    _amp_status_invalidate()
    if state == "up":
        log_event(f"Node {node} linked to {fav_name(f)}", "ok")
        return {"ok": True, "message": f"Node {node} is connected to {fav_name(f)}."}
    if state == "unknown":
        return {"ok": True, "warn": True, "message": f"Connect sent to {fav_name(f)}, but AMP's status could not be read to check it."}
    log_event(f"Node {node} could not connect to {fav_name(f)}" + (f": {msg}" if msg else ""), "warn")
    if "fail" in msg.lower() and target in msg:
        return {"ok": False, "error": f"Node {node} did not connect to {fav_name(f)}. AMP says: {msg}"}
    return {"ok": False, "error": f"Node {node} did not connect to {fav_name(f)}: no link after {LINK_WAIT_SEC} s"
                                  + (f" (AMP says: {msg})" if msg else "") + ". Check the number; the node may be offline or refusing connections."}


def fav_disconnect(index=None):
    favs = fav_load()
    if index is not None:
        try:
            favs = [favs[int(index)]]
        except (ValueError, TypeError, IndexError):
            return {"ok": False, "error": "Pick a favorite."}
    targets = {fav_target(f) for f in favs}
    ok, calls, err, _ = amp_calls(max_age=0)
    if not ok:
        return {"ok": False, "error": err}
    hit = [c for c in calls if c["node"] in targets and c["node"] != _cfg_get("amp_caller")]
    if not hit:
        return {"ok": True, "message": "That favorite is not linked." if index is not None else "No favorite is linked."}
    for c in hit:
        _, err = amp_http("POST", "/status-pressed", {"action": "dropcall", "lineId": c["line"], "callId": c["call"]})
        if err:
            return {"ok": False, "error": err}
    _amp_status_invalidate()
    names = ", ".join(c["node"] for c in hit)
    log_event(f"Disconnect {names}", "ok")
    return {"ok": True, "message": f"Disconnected {names}."}


def _auth_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().split("\n")
    except FileNotFoundError:
        return None


def amp_auth_state(info=None):
    info = info or amp_info()
    path = info["auth_file"]
    try:
        lines = _auth_lines(path)
    except OSError as exc:
        return {"path": path, "exists": True, "ours": False, "error": str(exc)}
    if lines is None:
        return {"path": path, "exists": False, "ours": False, "error": ""}
    want = [_cfg_get("amp_user"), _cfg_get("amp_secret")]
    ours = any(ln.split()[:2] == want for ln in lines if ln.strip() and not ln.lstrip().startswith("#"))
    return {"path": path, "exists": True, "ours": ours, "error": ""}


_amp_setup_lock = threading.Lock()


def amp_setup():
    info = amp_info(max_age=0)
    if not info["config"] or info["config_error"]:
        return {"ok": False, "error": f"AMP's configuration file could not be read ({info['config'] or 'not found'}: "
                                      f"{info['config_error'] or 'missing'}). Start AMP once, or set its path in amp_nodetalker.conf (amp_config)."}
    user, secret = _cfg_get("amp_user"), _cfg_get("amp_secret")
    path = info["auth_file"]
    with _amp_setup_lock:
        try:
            lines = _auth_lines(path)
        except OSError as exc:
            return {"ok": False, "error": f"Could not read {path}: {exc}"}
        keep = [] if lines is None else [ln for ln in lines if not (ln.split()[:1] == [user] and not ln.lstrip().startswith("#"))]
        while keep and keep[-1].strip() == "":
            keep.pop()
        if lines is None:
            keep = ["# Ampersand ASL Server login file: one line per caller, user name then password"]
        new = keep + [f"{user} {secret}", ""]
        backup = ""
        try:
            if lines is not None:
                st = os.stat(path)
                os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
                backup = os.path.join(BACKUP_DIR, os.path.basename(path) + "." + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
                shutil.copy2(path, backup)
                olds = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith(os.path.basename(path) + "."))
                for f in olds[:-BACKUP_KEEP]:
                    _remove_quiet(os.path.join(BACKUP_DIR, f))
                _atomic_write(path, "\n".join(new), like=st)
            else:
                d = os.path.dirname(path)
                if d and not os.path.isdir(d):
                    os.makedirs(d, mode=0o755, exist_ok=True)
                _atomic_write(path, "\n".join(new), 0o600)
                if info["uid"] is not None:
                    try:
                        os.chown(path, info["uid"], info["gid"] if info["gid"] is not None else -1)
                    except OSError:
                        pass
            os.utime(info["config"])
        except OSError as exc:
            return {"ok": False, "error": f"Could not write {path}: {exc}"}
    log_event(f"AMP: added the {user} login to {path}" + (f" (backup {backup})" if backup else "") + "; AMP reloads it within a second", "ok")
    threading.Timer(2.0, AMP_LINK.redial, args=("set up",)).start()
    msg = f"Added Node Talker's login to {path}."
    if backup:
        msg += f" Backup: {backup}."
    if not info["running"]:
        msg += " AMP is not running: start it, and Node Talker links when it answers."
    else:
        msg += " Linking in a few seconds."
    return {"ok": True, "message": msg}


IAX_HDR = struct.Struct(">HHIBBBB")
IAX_T_VOICE, IAX_T_CONTROL, IAX_T_IAX, IAX_T_TEXT = 2, 4, 6, 7
IAX_NEW, IAX_PING, IAX_PONG, IAX_ACK, IAX_HANGUP, IAX_REJECT, IAX_ACCEPT, IAX_AUTHREQ, IAX_AUTHREP = 1, 2, 3, 4, 5, 6, 7, 8, 9
IAX_INVAL, IAX_LAGRQ, IAX_LAGRP, IAX_VNAK, IAX_CALLTOKEN = 10, 11, 12, 18, 40
IAX_C_ANSWER, IAX_C_UNKEY = 4, 13
CODEC_ULAW, CODEC_SLIN = 0x4, 0x40
IE_CALLED, IE_CALLING, IE_NAME, IE_USER, IE_CAPS, IE_FORMAT, IE_VERSION = 1, 2, 4, 6, 8, 9, 11
IE_CHALLENGE, IE_MD5, IE_CAUSE, IE_CAUSECODE, IE_CALLTOKEN = 15, 16, 22, 42, 54
_TALKER_RE = re.compile(r"^T \S+ TALKERID,(.*)$")


def _ies(data):
    out, i = {}, 0
    while i + 2 <= len(data):
        t, n = data[i], data[i + 1]
        out.setdefault(t, bytes(data[i + 2:i + 2 + n]))
        i += 2 + n
    return out


def _ie(t, v):
    if isinstance(v, str):
        v = v.encode("utf-8")
    return bytes([t, len(v)]) + v


def _swap16(b):
    a = _samples(b)
    a.byteswap()
    return a.tobytes()


ULAW_DECODE = []
for _b in range(256):
    _u = ~_b & 0xFF
    _t = (((_u & 0x0F) << 3) + 0x84) << ((_u & 0x70) >> 4)
    ULAW_DECODE.append(0x84 - _t if _u & 0x80 else _t - 0x84)


class AmpCall:
    def __init__(self, t):
        self.addr = (t["host"], t["iax_port"])
        self.node, self.user, self.secret, self.caller = t["node"], t["user"], t["secret"], t["caller"]
        self.lock = threading.Lock()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.2)
        self.src = secrets.randbelow(32000) + 1
        self.dst = 0
        self.oseq = self.iseq = 0
        self.t0 = time.monotonic()
        self.codec = 0
        self.state = "calling"
        self.error = ""
        self.heard = False
        self.started = time.monotonic()
        self.last_rx = time.monotonic()
        self.last_ping = time.monotonic()
        self.last_voice_ts = None
        self.pending = {}
        self.talker = ""
        self.talker_at = 0.0
        self.frames_in = 0

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _ms(self):
        return int((time.monotonic() - self.t0) * 1000) & 0xFFFFFFFF

    def _send(self, pkt):
        try:
            self.sock.sendto(pkt, self.addr)
        except OSError:
            pass

    def _full(self, ftype, sub, body=b"", ts=None, track=False):
        ts = self._ms() if ts is None else ts
        pkt = IAX_HDR.pack(0x8000 | self.src, self.dst, ts, self.oseq, self.iseq, ftype, sub) + body
        if track:
            self.pending[self.oseq] = [pkt, time.monotonic(), 0]
        if not (ftype == IAX_T_IAX and sub in (IAX_ACK, IAX_INVAL, IAX_VNAK)):
            self.oseq = (self.oseq + 1) & 0xFF
        self._send(pkt)

    def _ack(self, ts):
        self._send(IAX_HDR.pack(0x8000 | self.src, self.dst, ts, self.oseq, self.iseq, IAX_T_IAX, IAX_ACK))

    def _new(self, token=""):
        self.oseq = self.iseq = 0
        self.t0 = time.monotonic()
        self.pending.clear()
        num = ("3" + self.node) if self.node.startswith("3") else self.node
        body = (_ie(IE_VERSION, struct.pack(">H", 2)) + _ie(IE_CALLED, num) + _ie(IE_CALLING, self.caller)
                + _ie(IE_NAME, APP_NAME) + _ie(IE_USER, self.user)
                + _ie(IE_CAPS, struct.pack(">I", CODEC_ULAW | CODEC_SLIN)) + _ie(IE_FORMAT, struct.pack(">I", CODEC_SLIN))
                + _ie(IE_CALLTOKEN, token))
        self._full(IAX_T_IAX, IAX_NEW, body, track=True)

    def start(self):
        with self.lock:
            self._new()

    def hangup(self, why="Node Talker stopped"):
        with self.lock:
            if self.state in ("up", "calling", "auth"):
                self._full(IAX_T_IAX, IAX_HANGUP, _ie(IE_CAUSE, why) + _ie(IE_CAUSECODE, b"\x10"))
            self.state = "down"

    def send_voice(self, pcm):
        with self.lock:
            if self.state != "up":
                return False
            data = _swap16(pcm) if self.codec == CODEC_SLIN else ulaw_encode(pcm)
            ts = self._ms() // 20 * 20
            if self.last_voice_ts is not None and ts <= self.last_voice_ts:
                ts = self.last_voice_ts + 20
            if self.last_voice_ts is None or (ts >> 16) != (self.last_voice_ts >> 16):
                self._full(IAX_T_VOICE, self.codec, data, ts=ts)
            else:
                self._send(struct.pack(">HH", self.src & 0x7FFF, ts & 0xFFFF) + data)
            self.last_voice_ts = ts
            return True

    def unkey(self):
        with self.lock:
            if self.state == "up":
                self._full(IAX_T_CONTROL, IAX_C_UNKEY)
            self.last_voice_ts = None

    def service(self, on_voice):
        try:
            data, addr = self.sock.recvfrom(2048)
        except socket.timeout:
            data, addr = None, None
        except OSError:
            return
        out = []
        with self.lock:
            self._service(data, addr, out)
        for pcm in out:
            on_voice(pcm)

    def _service(self, data, addr, out):
        now = time.monotonic()
        for seq, rec in list(self.pending.items()):
            if now - rec[1] > 1.0:
                if rec[2] >= 5:
                    self.pending.pop(seq)
                    continue
                rec[1], rec[2] = now, rec[2] + 1
                p = bytearray(rec[0])
                p[2] |= 0x80
                p[9] = self.iseq
                self._send(bytes(p))
        if self.state == "up" and now - self.last_ping > AMP_PING_SEC:
            self.last_ping = now
            self._full(IAX_T_IAX, IAX_PING)
        if data is None or addr != self.addr or self.state == "down":
            return
        if not data[0] & 0x80:
            if self.state == "up" and len(data) > 4:
                self.last_rx = now
                pcm = self._pcm(data[4:])
                if pcm:
                    out.append(pcm)
            return
        if len(data) < 12:
            return
        srcc, dstc, ts, oseq, iseq, ftype, sub = IAX_HDR.unpack_from(data)
        if dstc & 0x7FFF != self.src:
            return
        srcc &= 0x7FFF
        body = data[12:]
        self.last_rx = now
        self.heard = True
        for seq in [s for s in self.pending if ((iseq - s - 1) & 0xFF) < 128]:
            self.pending.pop(seq)
        if ftype == IAX_T_IAX and sub == IAX_CALLTOKEN:
            self._new(_ies(body).get(IE_CALLTOKEN, b"").decode("latin-1"))
            return
        if ftype == IAX_T_IAX and sub == IAX_ACK:
            return
        if ftype == IAX_T_IAX and sub in (IAX_ACCEPT, IAX_AUTHREQ):
            self.dst = srcc
        if ftype == IAX_T_IAX and sub == IAX_VNAK:
            for rec in self.pending.values():
                self._send(rec[0])
            return
        if oseq == self.iseq:
            self.iseq = (self.iseq + 1) & 0xFF
        elif ((self.iseq - oseq) & 0xFF) < 128:
            self._ack(ts)
            return
        else:
            return
        if not (ftype == IAX_T_IAX and sub in (IAX_PING, IAX_LAGRQ)):
            self._ack(ts)
        self._frame(ftype, sub, ts, body, out)

    def _pcm(self, data):
        if self.codec == CODEC_SLIN and len(data) == FRAME_BYTES:
            self.frames_in += 1
            return _swap16(data)
        if self.codec == CODEC_ULAW and len(data) == FRAME_SAMPLES:
            self.frames_in += 1
            return array.array("h", map(ULAW_DECODE.__getitem__, data)).tobytes()
        return None

    def _frame(self, ftype, sub, ts, body, out):
        if ftype == IAX_T_IAX:
            if sub == IAX_AUTHREQ:
                ch = _ies(body).get(IE_CHALLENGE, b"").decode("latin-1")
                res = hashlib.md5((ch + self.secret).encode("latin-1")).hexdigest()
                self.state = "auth"
                self._full(IAX_T_IAX, IAX_AUTHREP, _ie(IE_MD5, res), track=True)
            elif sub == IAX_ACCEPT:
                f = _ies(body).get(IE_FORMAT)
                self.codec = struct.unpack(">I", f)[0] if f and len(f) == 4 else CODEC_SLIN
                if self.codec not in (CODEC_SLIN, CODEC_ULAW):
                    self._full(IAX_T_IAX, IAX_HANGUP, _ie(IE_CAUSE, "codec") + _ie(IE_CAUSECODE, b"\x10"))
                    self.state, self.error = "down", f"AMP picked a codec Node Talker can't use ({self.codec:#x})"
                    return
                self.state = "up"
                self.last_ping = time.monotonic()
            elif sub in (IAX_HANGUP, IAX_REJECT):
                cause = _CALL_TRIM.sub(" ", _ies(body).get(IE_CAUSE, b"").decode("latin-1", "replace")).strip()[:120]
                self.error = (("AMP refused the call" if sub == IAX_REJECT else "AMP hung up") + (f": {cause}" if cause else ""))
                self.state = "down"
            elif sub == IAX_PING:
                self._full(IAX_T_IAX, IAX_PONG, ts=ts)
            elif sub == IAX_LAGRQ:
                self._full(IAX_T_IAX, IAX_LAGRP, ts=ts)
        elif ftype == IAX_T_VOICE:
            if self.state == "up":
                pcm = self._pcm(body)
                if pcm:
                    out.append(pcm)
        elif ftype == IAX_T_TEXT:
            m = _TALKER_RE.match(body.rstrip(b"\0").decode("latin-1", "replace"))
            if m:
                self.talker = _CALL_TRIM.sub(" ", m.group(1)).strip()[:40]
                self.talker_at = time.monotonic()


class AmpLink:
    def __init__(self):
        self.lock = threading.Lock()
        self.call = None
        self.state = "down"
        self.error = ""
        self.since = 0.0
        self.wake = threading.Event()
        self.redial_why = ""
        self.backoff = 2.0
        self.beat = time.monotonic()
        self.target = None
        self.logged = ""

    def redial(self, why="reconnect"):
        self.redial_why = why
        self.wake.set()

    def snapshot(self):
        with self.lock:
            c = self.call
            talker = c.talker if c is not None and time.monotonic() - c.talker_at < 3.0 else ""
            return {"state": self.state, "error": self.error, "secs": int(time.monotonic() - self.since) if self.since else 0,
                    "codec": "16-bit" if c is not None and c.codec == CODEC_SLIN else "mu-law" if c is not None and c.codec == CODEC_ULAW else "",
                    "talker": talker}

    def send_voice(self, pcm):
        c = self.call
        return c is not None and c.send_voice(pcm)

    def unkey(self):
        c = self.call
        if c is not None:
            c.unkey()

    def up(self):
        return self.state == "up"

    def stop(self):
        c = self.call
        if c is not None:
            c.hangup()

    def _set(self, state, error=""):
        with self.lock:
            changed = state != self.state
            self.state, self.error = state, error
            if changed:
                self.since = time.monotonic()
        return changed

    def _nap(self, sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.beat = time.monotonic()
            if self.wake.wait(min(1.0, max(0.0, end - time.monotonic()))):
                break
        self.wake.clear()

    def run(self):
        while True:
            self.beat = time.monotonic()
            try:
                self._once()
            except Exception as exc:
                log_event(f"AMP link error: {exc}", "err")
                self._set("down", str(exc))
                self._nap(5)

    def _once(self):
        t = amp_target()
        if not t["node"]:
            self._set("down", "AMP's node number is not set yet (AMP's Configuration page)")
            self._nap(5)
            return
        call = AmpCall(t)
        with self.lock:
            self.call = call
            self.target = (t["host"], t["iax_port"], t["node"], t["user"], t["secret"], t["caller"])
        self._set("calling", "")
        call.start()
        last_target_check = time.monotonic()
        try:
            while True:
                self.beat = time.monotonic()
                call.service(HUB.feed)
                now = time.monotonic()
                if call.state == "up" and self.state != "up":
                    self._set("up")
                    self.backoff = 2.0
                    self.logged = ""
                    log_event(f"Linked to AMP node {t['node']} as {t['caller']} ({'16-bit' if call.codec == CODEC_SLIN else 'mu-law'})", "ok")
                if call.state == "down":
                    self._set("down", call.error or "AMP ended the call")
                    log_event(f"AMP link down: {self.error}", "warn")
                    break
                if call.state != "up" and now - call.started > AMP_CALL_WAIT_SEC:
                    err = (f"AMP did not accept Node Talker's login (user {t['user']}): Setup tab, AMP link, Set up for me"
                           if call.heard else f"No answer from AMP on {t['host']}:{t['iax_port']} (is amp-server running?)")
                    if self.logged != err:
                        self.logged = err
                        log_event(f"AMP link: {err}", "warn")
                    call.hangup("timeout")
                    self._set("down", err)
                    break
                if call.state == "up" and now - call.last_rx > AMP_SILENT_SEC:
                    call.hangup("no answer")
                    self._set("down", f"AMP stopped answering for {int(AMP_SILENT_SEC)} s")
                    log_event(f"AMP link: {self.error}", "warn")
                    break
                if self.wake.is_set():
                    self.wake.clear()
                    log_event(f"AMP link: redial ({self.redial_why})")
                    call.hangup(self.redial_why)
                    self._set("down", "")
                    self.backoff = 0.5
                    break
                if now - last_target_check > 5.0:
                    last_target_check = now
                    t2 = amp_target()
                    if (t2["host"], t2["iax_port"], t2["node"], t2["user"], t2["secret"], t2["caller"]) != self.target:
                        call.hangup("settings changed")
                        self._set("down", "")
                        self.backoff = 0.5
                        break
        finally:
            if TALKER.keyed:
                TALKER.drop(TALKER.owner)
            call.close()
        self._nap(self.backoff)
        self.backoff = min(AMP_BACKOFF_MAX, self.backoff * 2)


AMP_LINK = AmpLink()


def tx_state(main=None):
    snap = AMP_LINK.snapshot()
    up = snap["state"] == "up"
    return {"node": _cfg_get("amp_caller"), "main": main_node() if main is None else main, "ready": up, "linked": up,
            "link": snap["state"], "error": snap["error"]}


def amp_state():
    info = amp_info(max_age=0)
    t = amp_target()
    snap = AMP_LINK.snapshot()
    auth = amp_auth_state(info)
    return {"ok": True, "running": info["running"], "pid": info["pid"], "count": info["count"], "user": info["user"], "config": info["config"],
            "config_error": info["config_error"], "node": t["node"], "callsign": info["callsign"], "host": t["host"],
            "iax_port": t["iax_port"], "http_port": t["http_port"], "http_pwd_set": bool(t["http_pwd"]),
            "http_pwd_auto": bool(info["http_pwd"]) and not _cfg_get("amp_http_pwd"),
            "auth": auth, "login_user": t["user"], "caller": t["caller"], "link": snap,
            "local": t["host"] in ("127.0.0.1", "localhost", "::1")}


def _lan_ips():
    ips = set()
    try:
        r = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3)
        ips.update(x for x in r.stdout.split() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", x))
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    ips.add("127.0.0.1")
    return sorted(ips)


def ensure_tls_cert():
    if os.path.exists(TLS_CERT) and os.path.exists(TLS_KEY):
        return True
    openssl = shutil.which("openssl")
    if not openssl:
        log_event("openssl not found: can't create the HTTPS certificate", "err")
        return False
    host = socket.gethostname().split(".")[0]
    if not _HOSTNAME_RE.match(host):
        host = "nodetalker"
    try:
        os.makedirs(TLS_DIR, mode=0o700, exist_ok=True)
        os.chmod(TLS_DIR, 0o700)
    except OSError as exc:
        log_event(f"Can't create {TLS_DIR}: {exc}", "err")
        return False
    san = ",".join([f"DNS:{host}", f"DNS:{host}.local"] + [f"IP:{ip}" for ip in _lan_ips()])
    key_tmp, cert_tmp = TLS_KEY + ".tmp", TLS_CERT + ".tmp"
    cmd = [openssl, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
           "-keyout", key_tmp, "-out", cert_tmp, "-days", "3650", "-subj", f"/CN={host}",
           "-addext", f"subjectAltName={san}"]
    old_umask = os.umask(0o077)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        log_event(f"openssl failed: {exc}", "err")
        return False
    finally:
        os.umask(old_umask)
    if r.returncode != 0 or not (os.path.exists(key_tmp) and os.path.exists(cert_tmp)):
        log_event(f"openssl failed: {r.stderr.strip()[:300]}", "err")
        for p in (key_tmp, cert_tmp):
            _remove_quiet(p)
        return False
    os.chmod(key_tmp, 0o600)
    os.chmod(cert_tmp, 0o644)
    os.replace(key_tmp, TLS_KEY)
    os.replace(cert_tmp, TLS_CERT)
    log_event(f"Created a self-signed HTTPS certificate for {host} ({san})", "ok")
    return True


def _set_aside_tls():
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for p in (TLS_CERT, TLS_KEY):
        if os.path.exists(p):
            try:
                os.replace(p, f"{p}.{stamp}.bad")
            except OSError as exc:
                log_event(f"Can't move {p} aside: {exc}", "err")
                return False
    return True


def make_ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(TLS_CERT, TLS_KEY)
    return ctx


_REDIRECT_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]{1,253}(?::\d{1,5})?$|^\[[0-9A-Fa-f:.]{2,45}\](?::\d{1,5})?$")


def plain_redirect(sock):
    data = b""
    try:
        sock.settimeout(5)
        while b"\r\n\r\n" not in data and len(data) < 8192:
            chunk = sock.recv(2048)
            if not chunk:
                break
            data += chunk
    except OSError:
        return
    text = data.decode("latin-1", "replace")
    lines = text.split("\r\n")
    parts = lines[0].split(" ") if lines else []
    path = parts[1] if len(parts) >= 2 and parts[1].startswith("/") else "/"
    if any(c in path for c in "\r\n ") or path.startswith("//"):
        path = "/"
    host = ""
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        if k.strip().lower() == "host":
            host = v.strip()
            break
    if not _REDIRECT_HOST_RE.match(host):
        ips = [ip for ip in _lan_ips() if not ip.startswith("127.")] or ["127.0.0.1"]
        host = f"{ips[0]}:{_cfg_get('port')}"
    body = b"This page is served over HTTPS.\r\n"
    resp = (f"HTTP/1.1 301 Moved Permanently\r\nLocation: https://{host}{path}\r\n"
            f"Content-Type: text/plain\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode("latin-1") + body
    try:
        sock.sendall(resp)
    except OSError:
        pass


_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_MAX_PAYLOAD = 65536


class WebSocket:
    def __init__(self, handler):
        self.r = handler.rfile
        self.w = handler.wfile
        self.lock = threading.Lock()
        self.closed = False

    def _read(self, n):
        data = self.r.read(n)
        if data is None or len(data) < n:
            raise EOFError("closed")
        return data

    def recv(self):
        msg = bytearray()
        msg_op = None
        while True:
            b1, b2 = self._read(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            masked, n = b2 & 0x80, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            if n > WS_MAX_PAYLOAD or not masked:
                raise EOFError("bad frame")
            mask = self._read(4)
            payload = bytearray(self._read(n))
            for i in range(n):
                payload[i] ^= mask[i & 3]
            if op >= 8:
                if op == 9:
                    self.send(10, bytes(payload))
                    continue
                if op == 10:
                    continue
                return op, bytes(payload)
            if op != 0:
                msg_op = op
            msg += payload
            if len(msg) > WS_MAX_PAYLOAD:
                raise EOFError("message too big")
            if fin:
                return msg_op, bytes(msg)

    def send(self, op, payload=b""):
        n = len(payload)
        if n < 126:
            head = struct.pack(">BB", 0x80 | op, n)
        elif n < 65536:
            head = struct.pack(">BBH", 0x80 | op, 126, n)
        else:
            head = struct.pack(">BBQ", 0x80 | op, 127, n)
        with self.lock:
            if self.closed:
                return
            try:
                self.w.write(head + payload)
                self.w.flush()
            except OSError:
                self.closed = True

    def send_json(self, obj):
        self.send(1, json.dumps(obj).encode("utf-8"))


class Talker:
    def __init__(self):
        self.lock = threading.Lock()
        self.owner = None
        self.who = ""
        self.keyed = False
        self.sending = False
        self.releasing = False
        self.start = 0.0
        self.last_rx = 0.0
        self.q = deque()
        self.buf = bytearray()
        self.beat = time.monotonic()
        self.last_unkey = 0.0
        self.peak = -120.0
        self.last_peak = None
        self.gaps = 0
        self.last_gaps = None
        self.primed_once = False

    def _packet(self, payload, keyup):
        if keyup:
            AMP_LINK.send_voice(payload)

    def state(self):
        with self.lock:
            return {"keyed": self.keyed, "who": self.who if self.keyed else "",
                    "secs": round(time.monotonic() - self.start, 1) if self.keyed else 0,
                    "tot": _cfg_get("tot_sec"), "peak_db": round(self.peak, 1) if self.keyed else None,
                    "last_peak_db": self.last_peak, "gaps": self.gaps if self.keyed else None,
                    "last_gaps": self.last_gaps}

    def key(self, owner, who):
        if not AMP_LINK.up():
            return False, "not-ready"
        if (_cfg_get("busy_lockout") and HUB.audio_active()
                and time.monotonic() - self.last_unkey > TX_BUSY_GRACE_SEC):
            with self.lock:
                mine = self.keyed and self.owner is owner
            if not mine:
                return False, "busy"
        with self.lock:
            if self.keyed and self.owner is not owner:
                return False, "in-use"
            now = time.monotonic()
            self.owner, self.who = owner, who
            self.keyed, self.sending, self.releasing = True, False, False
            self.start = self.last_rx = now
            self.q.clear()
            self.buf = bytearray()
            self.peak = -120.0
            self.gaps = 0
            self.primed_once = False
        log_event(f"TX: {who} keyed AMP node {main_node()}", "ok")
        return True, ""

    def audio(self, owner, data):
        with self.lock:
            if not self.keyed or self.owner is not owner or self.releasing:
                return
            self.last_rx = time.monotonic()
            self.buf += data
            gain = tune_value("tx_gain_db")
            while len(self.buf) >= FRAME_BYTES:
                fr = apply_gain(bytes(self.buf[:FRAME_BYTES]), gain)
                del self.buf[:FRAME_BYTES]
                self.peak = max(self.peak, peak_db(fr))
                self.q.append(fr)
            while len(self.q) > TX_QUEUE_MAX:
                self.q.popleft()

    def release(self, owner):
        with self.lock:
            if self.keyed and self.owner is owner:
                self.releasing = True

    def drop(self, owner):
        with self.lock:
            mine = self.keyed and self.owner is owner
        if mine:
            self._unkey("closed")

    def _unkey(self, why):
        with self.lock:
            if not self.keyed:
                return
            owner, who = self.owner, self.who
            secs = time.monotonic() - self.start
            self.keyed = self.sending = self.releasing = False
            self.owner = None
            self.q.clear()
            self.last_unkey = time.monotonic()
            self.last_peak = round(self.peak, 1)
            self.last_gaps = self.gaps
            gaps = self.gaps
        AMP_LINK.unkey()
        log_event(f"TX: {who} unkeyed after {secs:.1f} s ({why})" + (f", {gaps} audio gap(s)" if gaps else ""),
                  "warn" if why in ("timeout", "deadman") or gaps else "ok")
        if owner is not None:
            owner.send_json({"ev": "unkeyed", "why": why, "secs": round(secs, 1)})

    def pacer_loop(self):
        def step():
            self.beat = time.monotonic()
            self._tick()

        paced_loop(step, "TX pacer")

    def _tick(self):
        now = time.monotonic()
        why = None
        frame = None
        with self.lock:
            if not self.keyed:
                return
            target = max(2, tune_value("tx_buffer_ms") // 20)
            if now - self.start > _cfg_get("tot_sec"):
                why = "timeout"
            elif not self.sending:
                if (len(self.q) >= target or (self.releasing and self.q)
                        or (not self.primed_once and now - self.start > target * FRAME_SEC + 0.3)):
                    self.sending = True
                    self.primed_once = True
                elif self.primed_once:
                    frame = PCM_SILENCE
                if self.releasing and not self.q:
                    why = "release"
                elif now - self.last_rx > TX_DEADMAN_SEC:
                    why = "deadman"
            if why is None and self.sending:
                if self.q:
                    frame = self.q.popleft()
                    if self.releasing and not self.q:
                        frame = fade_out(frame)
                elif self.releasing:
                    why = "release"
                elif now - self.last_rx > TX_DEADMAN_SEC:
                    why = "deadman"
                else:
                    self.gaps += 1
                    self.sending = False
                    frame = PCM_SILENCE
        if why:
            self._unkey(why)
        elif frame is not None:
            self._packet(frame, True)


TALKER = Talker()


_CSS = r"""@font-face{font-family:"Readex Pro";font-style:normal;font-weight:400;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2")}
@font-face{font-family:"Readex Pro";font-style:normal;font-weight:700;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2")}
:root{--bg:#0d1117;--card:#161e2e;--card2:#0d1117;--line:#2e4060;--line2:#3a5278;--text:#f0f8ff;--muted:#9fb0bf;
--soft:#c9d4de;--accent:#00ffb0;--accent-ink:#0d1117;--accent-dim:#005538;--amber:#ffd040;--amber-bg:#2a2000;--red:#ff3d5a;--red-line:#ff3d5a}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--text);font:15px/1.45 "Readex Pro",Arial,Helvetica,sans-serif}
body{display:flex;flex-direction:column;height:100vh;height:100dvh;overflow:hidden}
header{flex:none;display:flex;align-items:center;gap:10px;padding:calc(12px + env(safe-area-inset-top)) 16px 12px;border-bottom:2px solid var(--amber);background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);z-index:5;box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
header .hdr-left{display:flex;flex-direction:column;min-width:0}
header h1{font-size:1.21rem;margin:0;white-space:nowrap;color:var(--amber);letter-spacing:.1em;text-transform:uppercase;text-shadow:0 0 10px rgba(255,208,64,.9),0 0 30px rgba(255,208,64,.5),0 0 60px rgba(255,208,64,.2)}
header .logo-sub{font-size:.715rem;letter-spacing:.22em;text-transform:uppercase;color:var(--amber);margin-top:.1rem}

header .ver{color:var(--muted);font-size:12px}
header .sp{flex:1}
.pill{display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 12px;border:1px solid var(--line2);border-radius:999px;color:var(--text);text-decoration:none;background:transparent;cursor:pointer;font:inherit;font-size:13px;white-space:nowrap}
.pill:hover{border-color:var(--accent)}
main{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:14px max(16px,calc((100% - 608px) / 2)) 24px;overflow-wrap:anywhere}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.card h2{font-size:15px;margin:0 0 10px}
.card.fold{padding-top:4px;padding-bottom:4px}
.card.fold h2{margin:0}
.fold-btn{width:100%;min-height:44px;display:flex;align-items:center;gap:8px;padding:0;border:0;background:transparent;color:var(--text);font:inherit;font-size:15px;font-weight:700;text-align:left;cursor:pointer}
.fold-t{flex:none}
.fold-sum{flex:1;min-width:0;color:var(--muted);font-size:13px;font-weight:400;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fold-i{flex:none;width:14px;color:var(--muted);text-align:center}
.fold-body{padding:6px 0 10px}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}
button{font:inherit;color:var(--text)}
.btn{min-height:44px;padding:0 16px;border-radius:10px;border:1px solid var(--line2);background:#1b2633;cursor:pointer;font-weight:600}
.btn:hover{border-color:var(--accent)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.btn.danger{background:transparent;border-color:var(--red-line);color:var(--red)}
.btn:disabled{opacity:.45;cursor:default}
.btn.big{min-height:56px;font-size:17px;min-width:160px}
input,select{background:var(--card2);color:var(--text);border:1px solid var(--line2);border-radius:8px;padding:8px 10px;font:inherit;min-height:40px}
input[type=number]{width:110px}
input[type=range]{accent-color:var(--accent);min-height:28px;padding:0;border:0;background:transparent}
input[type=checkbox]{accent-color:var(--accent);width:20px;height:20px;min-height:0}
label{color:var(--soft)}
.muted{color:var(--muted)}
.small{font-size:13px}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
.big-num{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:28px;font-weight:700}
.meter{position:relative;height:12px;flex:1;min-width:140px;background:#1b2530;border-radius:6px;overflow:hidden}
.meter i{position:absolute;left:0;top:0;bottom:0;width:0;background:linear-gradient(90deg,#22c3a6,#22c3a6 70%,#e3a008 90%,#f2545b);transition:width .1s}
.dot{display:inline-block;width:11px;height:11px;border-radius:50%;background:#33404d;vertical-align:middle;margin-right:6px}
.dot.on{background:var(--accent);box-shadow:0 0 8px var(--accent)}
.dot.rx{background:var(--amber);box-shadow:0 0 8px var(--amber)}
.dot.tx{background:var(--red-line);box-shadow:0 0 8px var(--red-line)}
.dot.warn{background:#e3a008}.dot.err{background:var(--red-line)}
.msg{margin-top:8px;font-size:14px;min-height:1em;overflow-wrap:anywhere}
.msg.ok{color:var(--accent)}.msg.err{color:var(--red)}.msg.warn{color:var(--amber)}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{text-align:left;padding:6px 6px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
table.links{font-size:clamp(10.5px,3.1vw,14px);font-variant-numeric:tabular-nums}
table.links td,table.links th{padding:6px 3px;white-space:nowrap;overflow-wrap:normal}
table.links td:nth-child(2){width:100%;max-width:0;overflow:hidden;text-overflow:ellipsis}
.listen-row{flex-wrap:nowrap}
.listen-row .btn.big{min-width:112px;flex:none}
.listen-row input[type=range]{flex:1;min-width:0}
.vol-i{flex:none;width:22px;height:22px;color:var(--muted)}
th{color:var(--muted);font-weight:600;white-space:nowrap;overflow-wrap:normal}
code{background:var(--card2);border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:12px;word-break:break-all}
#log{max-height:260px;overflow:auto;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;background:var(--card2);border:1px solid var(--line);border-radius:8px;padding:8px}
#log .err{color:var(--red)}#log .warn{color:var(--amber)}#log .ok{color:var(--accent)}
.hidden{display:none !important}
#login-screen{display:none;position:fixed;inset:0;z-index:9999;align-items:center;justify-content:center;
padding:16px;background:rgba(5,8,14,.88);backdrop-filter:blur(3px)}
#login-screen.open{display:flex}
#login-card{background:#161e2e;border:1px solid #3a5278;border-radius:8px;padding:1.4rem 1.6rem;min-width:260px;max-width:90vw;
box-shadow:0 8px 40px rgba(0,0,0,.8);text-align:center;font-family:Arial,Helvetica,sans-serif}
#login-card h2{margin:0 0 1rem;font-family:Arial,Helvetica,sans-serif;font-size:1.05rem;font-weight:700;color:#ffd040;
letter-spacing:.06em;text-shadow:0 0 8px rgba(255,208,64,.5)}
#login-form{display:flex;flex-direction:column;gap:.6rem}
#pw{font-family:Arial,Helvetica,sans-serif;font-size:.9rem;min-height:0;background:#0a1020;color:#ffffff;border:1px solid #3a5278;
border-radius:4px;padding:.45rem .6rem;outline:none}
#pw:focus{border-color:#ffd040}
#login-card button{font-family:Arial,Helvetica,sans-serif;font-size:.8rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
background:transparent;color:#ffd040;border:1px solid #6b4800;border-radius:4px;padding:.32rem .85rem;cursor:pointer;transition:all .14s}
#login-card button:hover{filter:brightness(1.5);box-shadow:0 0 10px currentColor}
#login-card button:disabled{opacity:.4;cursor:default;filter:none;box-shadow:none}
#login-card #login-cancel{color:#22d4ff;border-color:#083a58;margin-top:.6rem}
#login-msg{min-height:1.1rem;font-size:.78rem;color:#ff3d5a;margin-top:.2rem}
#login-tls{max-width:300px;font-size:.78rem;color:#ff3d5a;margin-top:.4rem}#login-tls:empty{display:none}
nav.tabs{flex:none;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));background:var(--card);border-top:1px solid var(--line);padding:4px 6px calc(8px + env(safe-area-inset-bottom));z-index:5}
nav.tabs button{background:transparent;border:1px solid var(--line2);border-bottom:0;border-radius:5px 5px 0 0;min-height:52px;text-transform:uppercase;letter-spacing:.08em;font-weight:700;color:var(--muted);font-size:13px;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}
nav.tabs button[aria-current=page]{color:#22d4ff;border-color:#22d4ff;background:rgba(34,212,255,.12);box-shadow:0 0 10px rgba(34,212,255,.35)}
nav.tabs svg{width:22px;height:22px}
main.fit{padding-top:10px;padding-bottom:12px}
#tab-listen{min-height:100%;display:flex;flex-direction:column}
.lpanel{flex:1 0 auto;display:flex;flex-direction:column;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.lpanel>*{flex:none}
.lpanel .row{margin:0}
.lpanel .msg{margin-top:0;min-height:0}
.lpanel #listen-msg:empty{display:none}
.lstat{display:flex;align-items:center;gap:12px;font-size:13px;color:var(--soft);white-space:nowrap;overflow:hidden}
.lstat>span{flex:none;display:inline-flex;align-items:center}
.lstat #st-node{font-weight:700;color:var(--text)}
.lstat #st-feed-w{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis}
.lstat .dot{margin-right:4px}
.spec{flex:1 1 0;min-height:14px;display:flex;flex-direction:column;gap:4px}
.spec-box{position:relative;flex:1;min-height:0;border-radius:8px;overflow:hidden;background:#0a1016;border:1px solid var(--line)}
.spec-box canvas{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:pointer;touch-action:manipulation}
.spec-lo{position:absolute;left:0;top:0;bottom:0;width:7.5%;background:rgba(244,192,78,.10);border-right:1px dashed rgba(244,192,78,.45);pointer-events:none}
.spec-t{position:absolute;bottom:2px;transform:translateX(-50%);font:10px ui-monospace,Menlo,Consolas,monospace;color:var(--muted);pointer-events:none}
.spec.small .spec-box,.spec.off .spec-box{display:none}
.spec-meter{display:flex;align-items:center;gap:8px}
.spec-meter.tx #st-level{color:var(--red);font-weight:700}
.spec-meter.tx .meter i{background:linear-gradient(90deg,#f2545b,#f2545b 85%,#ffb3b6)}
.vu{margin:8px 0}
.vu-bar{position:relative;height:16px;border-radius:5px;overflow:hidden;
background:linear-gradient(90deg,#1b2530 0 90%,#14382f 90% 95%,#1b2530 95% 98.3%,#3a1518 98.3%)}
.vu-avg{position:absolute;left:0;top:0;bottom:0;width:0;background:var(--accent);opacity:.85}
.vu-pk{position:absolute;top:0;bottom:0;width:3px;left:0;background:var(--amber)}
.vu-hold{position:absolute;top:-2px;bottom:-2px;width:2px;left:0;background:var(--text)}
.vu-gr{position:relative;height:5px;margin-top:3px;border-radius:3px;background:#1b2530;overflow:hidden}
.vu-gr i{position:absolute;right:0;top:0;bottom:0;width:0;background:var(--amber)}
.vu-txt{display:flex;justify-content:space-between;gap:8px;font:12px ui-monospace,Menlo,Consolas,monospace;color:var(--soft);margin-top:3px}
.vu-scale{display:flex;justify-content:space-between;font:10px ui-monospace,Menlo,Consolas,monospace;color:var(--muted)}
.rep{margin:8px 0 4px;padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--card2)}
.rep h3{font-size:13px;margin:0 0 6px;color:var(--soft)}
.rep-strip{position:relative;height:56px;margin:2px 0 6px}
.rep-strip canvas{width:100%;height:100%;display:block;border-radius:6px;background:#0a1016}
.rep-strip .rep-lbl{position:absolute;left:6px;top:3px;font:10px ui-monospace,Menlo,Consolas,monospace;color:var(--muted)}
.rep-head{position:absolute;top:0;bottom:0;width:2px;left:0;background:var(--text);display:none}
.rep-n{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:4px 10px;font-size:13px;margin:4px 0}
.rep-n b{font-family:ui-monospace,Menlo,Consolas,monospace}
.rep-v{font-size:14px;font-weight:600;margin-top:6px}
.rep-v.ok{color:var(--accent)}.rep-v.warn{color:var(--amber)}.rep-v.err{color:var(--red)}
.chk{flex:none;padding:0 6px;border-radius:6px;background:var(--amber-bg);color:var(--amber);font:700 11px ui-monospace,Menlo,Consolas,monospace;cursor:pointer}
.chk-run{font-size:14px;margin:6px 0}
table.chk-t{table-layout:fixed}
table.chk-t td,table.chk-t th{padding:5px 3px;font-size:12px;white-space:normal;overflow-wrap:break-word}
table.chk-t thead th:first-child{width:40%}
table.chk-t td{font-family:ui-monospace,Menlo,Consolas,monospace}
.sug{display:flex;gap:8px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--line);font-size:14px}
.sug .t{flex:1}
.sug .btn{min-height:36px;padding:0 12px;font-size:13px}
.st-ok{color:var(--accent)}.st-warn{color:var(--amber)}.st-bad{color:var(--red)}
.spec-meter .meter{height:6px;min-width:0}
#ptt-card{display:flex;flex-direction:column;gap:4px;margin-bottom:2px}
#ptt{width:100%;height:80px;border-radius:16px;border:3px solid var(--line2);background:#1b2633;color:var(--text);font-size:19px;font-weight:700;cursor:pointer;padding:0 20px;
touch-action:none;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;display:flex;align-items:center;justify-content:space-between;gap:10px;overflow:hidden}
#ptt-label{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#ptt.ready{border-color:var(--accent)}
#ptt.busy{border-color:var(--amber)}
#ptt.talking{background:#4a1418;border-color:var(--red-line);box-shadow:0 0 0 6px rgba(242,84,91,.15)}
.ptt-line{font-size:12px;text-align:center;min-height:16px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
#ptt-msg:not(:empty)+#ptt-info{display:none}
#ptt:disabled{opacity:.45;cursor:default}
#ptt-time{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:15px;color:var(--soft)}
.sel-card{display:flex;flex-direction:column;gap:6px;background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:10px}
.tag{display:inline-block;padding:2px 8px;border:1px solid var(--accent);border-radius:7px;color:#7fd8c6;font-size:12px;font-weight:700;font-family:ui-monospace,Menlo,Consolas,monospace}
.fav-row{display:grid;grid-template-columns:110px 124px minmax(0,1fr) 44px;gap:6px;margin:6px 0}
.fav-row input,.fav-row select{min-width:0;width:100%}
.fav-row button{min-height:40px;border-radius:8px;border:1px solid var(--line2);background:transparent;color:var(--red);cursor:pointer}
@media (max-width:420px){header{gap:6px;padding:calc(10px + env(safe-area-inset-top)) 12px 10px}header .ver{display:none}.pill{padding:0 10px}}
@media (max-width:480px){.fav-row{grid-template-columns:92px 108px minmax(0,1fr) 40px}}
"""

_JS = r"""const $ = (id) => document.getElementById(id);
let loginWanted = false;
let authed = false, publicListen = false, ampWeb = null, tab = 'listen', lastLogId = 0, lastStatus = null;
let ctx = null, gainNode = null, ctrl = null, playing = false, nextT = 0;
let mediaDest = null, wakeLock = null, nodeLabel = '';
let pend = new Float32Array(1600), pendN = 0, peakLocal = 0, retryTimer = null;
let favs = [], favEdit = [], ampFavs = [], favMax = 10;
let ws = null, wsReady = false, wsRetry = null, talking = false, keyed = false, keyedAt = 0, totSec = 120;
let micPending = false, jitterSec = 0.25, ampDirty = false;
let capCtx = null, micStream = null, capSrc = null, capNode = null, capSink = null, workletReady = false, preKey = [], talkTimer = null;
let rs = null, frameSink = null, testing = false, testBuf = [];
const MIC_DEFAULTS = {agc: false, ns: true, ec: false, gain: 0, hp: true, lev: true, gate: 0, eq: false};
let mic = Object.assign({}, MIC_DEFAULTS);
try {
  const st = JSON.parse(localStorage.getItem('nlMic') || '{}');
  if (st && st.agc !== undefined && st.lev === undefined) st.agc = false;
  Object.assign(mic, st);
} catch (e) {}
const PLAY_DEFAULTS = {s16: true, smooth: true, auto: true, spec: true};
let play = Object.assign({}, PLAY_DEFAULTS);
try { Object.assign(play, JSON.parse(localStorage.getItem('nlPlay') || '{}')); } catch (e) {}
let streamPcm = false, oddByte = -1, ups = null, autoWait = null, starting = false;
let listenAt = 0, rxLastDb = -120, chk = null, chkUndo = {}, chkCfg = null;
let busNode = null, analyser = null, specBins = null, specRaf = 0, specLast = 0, busyText = '', pttState = 'off', ownUnkeyAt = -1e9;
let specMode = 'waterfall';
let hs = {out: '', mic: '', btn: 'listen'};
try { Object.assign(hs, JSON.parse(localStorage.getItem('nlHeadset') || '{}')); } catch (e) {}
let hsTx = false, outLost = 0, devCount = -1, lastDevChange = 0;
try { if (localStorage.getItem('nlSpec') === 'bars') specMode = 'bars'; } catch (e) {}

function sincKernels(phases, taps, half, fc, tAt, edgeIn) {
  const kern = [];
  for (let p = 0; p <= phases; p++) {
    const k = new Float32Array(taps), off = p / phases;
    let sum = 0;
    for (let i = 0; i < taps; i++) {
      const t = tAt(i, off), at = Math.abs(t);
      const sinc = t === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * t) / (Math.PI * t);
      const w = (edgeIn ? at > half : at >= half) ? 0 : 0.42 + 0.5 * Math.cos(Math.PI * t / half) + 0.08 * Math.cos(2 * Math.PI * t / half);
      k[i] = sinc * w; sum += k[i];
    }
    for (let i = 0; i < taps; i++) k[i] /= sum;
    kern.push(k);
  }
  return kern;
}

function makeResampler(inRate) {
  const ratio = inRate / 8000, half = Math.ceil(8 * ratio), taps = 2 * half + 1, phases = 32;
  const kern = sincKernels(phases, taps, half, 3400 / inRate, (i, off) => i - half - off, true);
  return {ratio: ratio, half: half, taps: taps, phases: phases, kern: kern,
    buf: new Float32Array(half), pos: half, out: new Int16Array(160), n: 0, hpX: 0, hpY: 0, peak: 0, dyn: makeDyn(),
    fss: 0, fpk: 0, flg: 1, fgg: 1};
}
function biquad(type, f0, q, gainDb) {
  const w = 2 * Math.PI * f0 / 8000, cs = Math.cos(w), al = Math.sin(w) / (2 * q), A = Math.pow(10, gainDb / 40);
  let b0, b1, b2, a0, a1, a2;
  if (type === 'hp') { b0 = (1 + cs) / 2; b1 = -(1 + cs); b2 = b0; a0 = 1 + al; a1 = -2 * cs; a2 = 1 - al; }
  else { b0 = 1 + al * A; b1 = -2 * cs; b2 = 1 - al * A; a0 = 1 + al / A; a1 = -2 * cs; a2 = 1 - al / A; }
  return {b0: b0 / a0, b1: b1 / a0, b2: b2 / a0, a1: a1 / a0, a2: a2 / a0, x1: 0, x2: 0, y1: 0, y2: 0};
}

function bq(f, x) {
  const y = f.b0 * x + f.b1 * f.x1 + f.b2 * f.x2 - f.a1 * f.y1 - f.a2 * f.y2;
  f.x2 = f.x1; f.x1 = x; f.y2 = f.y1; f.y1 = y;
  return y;
}

function makeDyn() {
  return {hp: biquad('hp', 300, 0.707, 0), pk: biquad('pk', 2500, 1.0, 4), env: 0, gg: 1, hold: 0, open: false,
    rms: 0, cg: 1, lg: 1};
}

const GATE = [null, {open: -45, floor: 0.18}, {open: -35, floor: 0.03}];

function dynProcess(d, v) {
  if (mic.eq) v = bq(d.pk, bq(d.hp, v));
  const a = v < 0 ? -v : v;
  const gs = GATE[Number(mic.gate) || 0];
  if (gs) {
    d.env = a > d.env ? d.env + (a - d.env) * 0.7 : d.env * 0.9975;
    const db = d.env > 1e-6 ? 20 * Math.log10(d.env) : -120;
    if (db > gs.open) { d.open = true; d.hold = 2000; }
    else if (db < gs.open - 6) { if (d.hold > 0) d.hold--; else d.open = false; }
    const want = d.open ? 1 : gs.floor;
    d.gg += (want - d.gg) * (want > d.gg ? 0.06 : 0.0016);
    v *= d.gg;
  }
  if (mic.lev) {
    d.rms += (v * v - d.rms) * 0.004;
    const lvl = d.rms > 1e-10 ? 10 * Math.log10(d.rms) : -100;
    const over = lvl + 24;
    const want = Math.pow(10, ((over > 0 ? -over * (2 / 3) : 0) + 9) / 20);
    d.cg += (want - d.cg) * (want < d.cg ? 0.0125 : 0.000625);
    v *= d.cg;
    const b = v < 0 ? -v : v, ceil = 0.89;
    if (b * d.lg > ceil) d.lg = ceil / b;
    else d.lg += (1 - d.lg) * 0.0025;
    v *= d.lg;
  }
  return v;
}

function makeUpsampler(outRate) {
  const half = 16, taps = 2 * half, phases = 64;
  const kern = sincKernels(phases, taps, half, 3700 / 8000, (i, off) => off + half - 1 - i, false);
  return {step: 8000 / outRate, half: half, taps: taps, phases: phases, kern: kern, buf: new Float32Array(taps), pos: half - 1};
}

function upsample(u, x) {
  const merged = new Float32Array(u.buf.length + x.length);
  merged.set(u.buf, 0); merged.set(x, u.buf.length);
  const out = [];
  let pos = u.pos;
  while (Math.floor(pos) + u.half < merged.length) {
    const base = Math.floor(pos), k = u.kern[Math.round((pos - base) * u.phases)], start = base - u.half + 1;
    let acc = 0;
    for (let i = 0; i < u.taps; i++) acc += merged[start + i] * k[i];
    out.push(acc);
    pos += u.step;
  }
  const keep = Math.max(0, Math.floor(pos) - u.half + 1);
  u.buf = merged.slice(keep);
  u.pos = pos - keep;
  return Float32Array.from(out);
}

function smoothFor(ac) { return play.smooth && ac.sampleRate !== 8000; }

function makeBuffer(ac, x8k, u) {
  let data = x8k, rate = 8000;
  if (smoothFor(ac)) { data = upsample(u || makeUpsampler(ac.sampleRate), x8k); rate = ac.sampleRate; }
  if (!data.length) return null;
  const ab = ac.createBuffer(1, data.length, rate);
  ab.copyToChannel(data, 0);
  return ab;
}

function playBack(ac, x8k) {
  const src = ac.createBufferSource();
  src.buffer = makeBuffer(ac, x8k) || ac.createBuffer(1, 1, 8000); src.connect(ac.destination); src.start();
  return src;
}

const AudioCtx = window.AudioContext || window.webkitAudioContext;
function newAudioCtx() { return new AudioCtx(); }
function peakDb(a) { return a > 0 ? 20 * Math.log10(a) : -120; }

const WORKLET_SRC = "class NlTap extends AudioWorkletProcessor{process(inputs){const c=inputs[0]&&inputs[0][0];if(c)this.port.postMessage(c.slice(0));return true}}registerProcessor('nl-tap',NlTap);";
const UL = new Float32Array(256);
for (let i = 0; i < 256; i++) {
  const u = ~i & 0xff, sign = u & 0x80, exp = (u >> 4) & 7, man = u & 0x0f;
  let s = (((man << 3) + 0x84) << exp) - 0x84;
  UL[i] = (sign ? -s : s) / 32768;
}

async function api(url, opts) {
  opts = opts || {};
  opts.headers = Object.assign({'X-Requested-With': 'XMLHttpRequest'}, opts.headers || {});
  if (opts.body && typeof opts.body !== 'string') {
    opts.body = JSON.stringify(opts.body);
    opts.headers['Content-Type'] = 'application/json';
  }
  let r;
  try { r = await fetch(url, opts); } catch (e) { return {ok: false, error: 'Node Talker is not answering.'}; }
  let d = {};
  try { d = await r.json(); } catch (e) { d = {ok: false, error: 'HTTP ' + r.status}; }
  if (r.status === 401 && url !== '/api/login' && authed) { authed = false; render(); }
  return d;
}

const post = (url, body) => api(url, {method: 'POST', body: body});
const TABS = ['connect', 'listen', 'setup'];

function note(id, cls, text) {
  const el = $(id);
  el.className = cls ? 'msg ' + cls : 'msg';
  el.textContent = text;
}

function setMsg(id, d) { note(id, d.warn ? 'warn' : d.ok ? 'ok' : 'err', d.ok ? (d.message || 'Done.') : (d.error || 'Failed.')); }
function fmtGain(v) { return (v > 0 ? '+' : '') + v + ' dB'; }

function addOption(sel, value, text) {
  const o = document.createElement('option');
  o.value = value; o.textContent = text;
  sel.appendChild(o);
}

function sendOp(op) { if (ws && ws.readyState === 1) ws.send(JSON.stringify({op: op})); }

const FOLDS = ['amp', 'cfg', 'fav', 'chk', 'lvl', 'mic', 'hs', 'play', 'log'];

function foldOpen(k) { return !$('cb-' + k).classList.contains('hidden'); }

function foldSet(k, open) {
  const b = $('cd-' + k).querySelector('.fold-btn');
  $('cb-' + k).classList.toggle('hidden', !open);
  b.setAttribute('aria-expanded', open ? 'true' : 'false');
  b.querySelector('.fold-i').textContent = open ? '▾' : '▸';
  if (!open) return;
  if (k === 'fav') loadAmpFavs();
  if (k === 'amp') loadAmp();
  if (k === 'log') pollLog();
  if (k === 'hs') hsDevices();
}

function sum(k, text) { $('sum-' + k).textContent = text; }

function micSummary() {
  const on = [];
  if (mic.lev) on.push('Leveler');
  if (Number(mic.gate)) on.push('Gate');
  sum('mic', on.concat(['gain ' + fmtGain(Number(mic.gain) || 0)]).join(' · '));
}

function playSummary() {
  const on = [];
  if (play.auto) on.push('Auto start');
  if (play.spec) on.push('Spectrum');
  if (!$('awake-row').classList.contains('hidden') && $('keep-awake').checked) on.push('Screen on');
  if (play.s16) on.push('16-bit');
  if (play.smooth) on.push('Smooth');
  sum('play', on.join(' · ') || 'All off');
}

function showTab(name) {
  if ((!authed && name !== 'listen') || TABS.indexOf(name) < 0) name = 'listen';
  tab = name;
  TABS.forEach((t) => {
    $('tab-' + t).classList.toggle('hidden', t !== name || !(authed || (t === 'listen' && publicListen)));
    const b = $('nav-' + t);
    if (t === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  if (name === 'connect') loadFavs();
  if (name === 'setup') { loadAmp(); loadConfig(); loadFavEditor(); micSummary(); playSummary(); if (chkShown && !chk) chkShow(chkShown); }
  if (name === 'listen') openTalk();
  document.querySelector('main').classList.toggle('fit', name === 'listen');
  specKick();
}

function render() {
  const anyView = authed || publicListen;
  const showLogin = !authed && (!publicListen || loginWanted);
  const wasOpen = $('login-screen').classList.contains('open');
  $('login-screen').classList.toggle('open', showLogin);
  $('login-open').classList.toggle('hidden', authed || !publicListen);
  $('login-cancel').classList.toggle('hidden', !publicListen);
  if (showLogin && !wasOpen) $('pw').focus();
  $('nav').classList.toggle('hidden', !authed);
  $('logout').classList.toggle('hidden', !authed);
  $('ptt-card').classList.toggle('hidden', !authed);
  if (!anyView) { TABS.forEach((t) => $('tab-' + t).classList.add('hidden')); return; }
  showTab(authed ? 'connect' : 'listen');
}

function openNamedTab(url, name) {
  let w = null;
  try { w = window.open('', name); } catch (e) {}
  if (!w) { window.open(url, name); return; }
  let blank = false;
  try { blank = w.location.href === 'about:blank'; } catch (e) {}
  if (blank) w.location.href = url;
  try { w.focus(); } catch (e) {}
}

async function whoami() {
  const d = await api('/api/whoami');
  authed = !!d.authed;
  publicListen = !!d.public_listen;
  ampWeb = d.amp_web || null;
  $('amp-web').href = 'http://' + location.hostname + ':' + (ampWeb || 8080) + '/';
  $('amp-web').classList.toggle('hidden', !ampWeb);
  const acct = d.account || 'root';
  $('pw').placeholder = 'Password for ' + acct;
  $('pw').setAttribute('aria-label', 'Password for ' + acct);
  if (!d.backend) $('login-msg').textContent = 'No password is set for ' + acct + ' on this Pi, so login cannot work.';
  render();
  autoListen();
}

async function login(ev) {
  ev.preventDefault();
  $('login-btn').disabled = true;
  $('login-msg').textContent = '';
  const d = await post('/api/login', {password: $('pw').value});
  $('login-btn').disabled = false;
  $('pw').value = '';
  if (d.ok) { authed = true; loginWanted = false; render(); autoListen(); loadFavs(); }
  else $('login-msg').textContent = d.error || 'Login failed.';
}

function openLogin() { loginWanted = true; render(); }

function cancelLogin() { loginWanted = false; $('login-msg').textContent = ''; render(); }

async function logout() {
  pttUp();
  if (ws) { try { ws.close(); } catch (e) {} }
  await post('/api/logout');
  authed = false;
  stopListen();
  render();
}

function fmtDb(db) { return db <= -119 ? '-inf' : ((Math.round(db) || 0) + ' dBFS'); }
function dbPct(db) { return Math.max(0, Math.min(100, (db + 60) / 60 * 100)); }
function fmtSecs(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }

function favNum(f) { return f.target && f.target !== f.num ? f.target + ' (direct)' : f.num; }

let linkedTargets = new Set();
function linkedFavs(d) {
  const links = (d && d.links) || [];
  const set = new Set(links.map((l) => l.node));
  return favs.filter((f) => set.has(f.target));
}

async function pollStatus() {
  if (!(authed || publicListen) || document.visibilityState === 'hidden' && !playing) return;
  const d = await api('/api/status');
  if (!d || d.ok === false) return;
  lastStatus = d;
  $('st-node').textContent = d.node || '(not set)';
  if ((d.node || '') !== nodeLabel) { nodeLabel = d.node || ''; setMediaInfo(); }
  $('st-listeners').textContent = d.listeners + ' / ' + d.max_listeners;
  const link = d.link || {};
  $('st-feed').className = 'dot ' + (d.receiving ? 'on' : link.state === 'calling' ? 'warn' : 'err');
  $('st-feed-t').textContent = d.receiving ? 'link' : link.state === 'calling' ? 'linking' : 'no link';
  $('st-feed-w').title = 'Link to AMP: ' + (d.receiving ? 'up' + (link.secs != null ? ' for ' + fmtSecs(link.secs) : '') + (link.codec ? ', ' + link.codec : '')
    + (d.last_rx_age != null ? '; audio ' + Math.round(d.last_rx_age) + ' s ago' : '') : (link.error || link.state || 'down'));
  $('st-active').className = 'dot ' + (d.audio_active ? 'rx' : '');
  if (!talking) $('st-level').textContent = fmtDb(d.peak_db);
  if (d.jitter_ms) jitterSec = d.jitter_ms / 1000;
  if (!playing && !talking) $('meter-bar').style.width = dbPct(d.peak_db) + '%';
  if (chk && chk.running) chkPoll(d);
  if (!authed) return;
  const tx = d.tx || {};
  $('s-tx').className = 'dot ' + (tx.keyed ? 'tx' : '');
  $('s-tx-w').title = tx.keyed ? 'Transmitting: ' + tx.who + ' ' + fmtSecs(tx.secs) : (tx.ready ? 'Nobody is transmitting' : 'Not linked to AMP');
  busyText = tx.keyed && !talking && !keyed && performance.now() - ownUnkeyAt > 2500 ? 'Busy: ' + tx.who + ' ' + fmtSecs(tx.secs)
    : (link.talker && d.audio_active && !talking && !keyed ? 'Busy: ' + link.talker : '');
  pttLabel();
  totSec = tx.tot || totSec;
  $('tune-txpk').textContent = tx.keyed && tx.peak_db != null ? fmtDb(tx.peak_db) + ' (now)'
    : (tx.last_peak_db != null ? fmtDb(tx.last_peak_db) + ' (last transmission)' : 'no transmission yet');
  $('tune-rxpk').textContent = fmtDb(d.peak_db);
  if (d.rx_load_pct != null) $('rx-load').textContent = d.rx_load_pct + ' % of one CPU core (last 5 s)';
  const gaps = tx.keyed ? tx.gaps : tx.last_gaps;
  $('tune-gaps').textContent = gaps == null ? '-' : (gaps ? gaps + ' (raise the TX buffer if this keeps happening)' : 'none');
  $('ptt-info').textContent = tx.ready ? ('AMP node ' + (d.node || '?') + ' · time-out ' + fmtSecs(totSec))
    : (link.error ? 'Not linked to AMP: ' + link.error : 'Linking to AMP...');
  const tb = $('s-links');
  tb.innerHTML = '';
  const links = d.links || [];
  links.forEach((l) => {
    const tr = document.createElement('tr');
    const f = favs.find((x) => x.target === l.node);
    [l.node, f ? f.label : '', l.state].forEach((v) => {
      const td = document.createElement('td'); td.textContent = v || ''; td.title = v || ''; tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  $('s-nolinks').classList.toggle('hidden', links.length > 0);
  $('s-links-err').textContent = 'Could not read the links from AMP: ' + (d.links_error || 'no answer');
  $('s-links-err').classList.toggle('hidden', d.links_ok !== false);
  linkedTargets = new Set(linkedFavs(d).map((f) => f.target));
  connectLabel();
  if (tab === 'setup' && foldOpen('amp')) ampLinkLine(link);
}

function flush() {
  if (!pendN || !ctx) return;
  if (smoothFor(ctx) && !ups) ups = makeUpsampler(ctx.sampleRate);
  const buf = makeBuffer(ctx, pend.subarray(0, pendN), ups);
  pendN = 0;
  if (!buf) return;
  const now = ctx.currentTime;
  if (nextT < now + 0.05 || nextT > now + jitterSec + 1.25) {
    if (chk && chk.running && nextT > 0 && playing && performance.now() - listenAt > 3000) chk.drops++;
    nextT = now + jitterSec;
  }
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(busNode);
  src.start(nextT);
  nextT += buf.duration;
  if (!talking) $('meter-bar').style.width = dbPct(peakDb(peakLocal)) + '%';
  peakLocal = 0;
}

const VU_MIN = -60;
let micTaps = [], vuMic = null, vuHold = {db: -120, t: 0};

function micFrame(st) {
  vuMic = st;
  micTaps.forEach((f) => f(st));
  if (talking) txMeter(st);
}

function vuPct(db) { return Math.max(0, Math.min(100, (db - VU_MIN) / -VU_MIN * 100)); }

function vuDraw(el, st) {
  const now = performance.now();
  if (st.pk > vuHold.db || now - vuHold.t > 1000) vuHold = {db: st.pk, t: now};
  el.querySelector('.vu-avg').style.width = vuPct(st.db) + '%';
  el.querySelector('.vu-pk').style.left = 'calc(' + vuPct(st.pk) + '% - 3px)';
  el.querySelector('.vu-hold').style.left = 'calc(' + vuPct(vuHold.db) + '% - 2px)';
  el.querySelector('.vu-gr i').style.width = Math.min(100, st.lim / 12 * 100) + '%';
  el.querySelector('.vu-num').textContent = 'peak ' + fmtDb(vuHold.db) + ' · avg ' + fmtDb(st.db);
  el.querySelector('.vu-lim').textContent = st.gate ? 'gate closed' : st.lim >= 0.5 ? 'limiting ' + st.lim.toFixed(1) + ' dB' : 'not limiting';
}

function vuRun(el, until) {
  el.classList.remove('hidden');
  const loop = () => {
    if (vuMic) vuDraw(el, vuMic);
    if (until()) requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

function txMeter(st) {
  $('spec-meter').classList.add('tx');
  $('meter-bar').style.width = dbPct(st.pk) + '%';
  $('st-level').textContent = 'TX ' + fmtDb(st.pk);
}

function rxMeterBack() {
  $('spec-meter').classList.remove('tx');
  $('st-level').textContent = '-';
}

function analyze(fr) {
  const act = fr.filter((f) => f.db > -45);
  const pw = (a) => a.length ? 10 * Math.log10(a.reduce((s, f) => s + Math.pow(10, f.db / 10), 0) / a.length) : -120;
  const sorted = fr.map((f) => f.db).sort((x, y) => x - y);
  const low = sorted.slice(0, Math.max(1, Math.floor(sorted.length / 10)));
  const noise = low.length ? 10 * Math.log10(low.reduce((s, d) => s + Math.pow(10, d / 10), 0) / low.length) : -120;
  const speech = pw(act);
  return {frames: fr.length, active: act.length, peak: fr.reduce((m, f) => Math.max(m, f.pk), -120), speech: speech,
    noise: noise, snr: act.length ? Math.min(60, speech - noise) : 0, limPct: act.length ? 100 * act.filter((f) => f.lim >= 0.5).length / act.length : 0,
    limAvg: act.length ? act.reduce((s2, f) => s2 + f.lim, 0) / act.length : 0,
    gatePct: act.length ? 100 * act.filter((f) => f.gate).length / act.length : 0};
}

function clampStep(x) { return Math.max(1, Math.min(12, Math.round(x))); }

function micVerdict(a) {
  if (a.active < 10) return {cls: 'err', text: 'Hardly anything was heard: check the microphone is allowed and not muted, and talk close to it.'};
  const room = 24 - (Number(mic.gain) || 0);
  if (a.peak > -1 || a.limPct > 30) {
    const d = clampStep(Math.max(a.peak + 4, a.limPct > 30 ? a.limAvg + 3 : 0));
    return {cls: 'warn', text: 'Too hot' + (a.limPct > 30 ? ' (the limiter worked ' + Math.round(a.limPct) + ' % of the time)' : '') + ': lower Mic gain by about ' + d + ' dB.', delta: -d};
  }
  if (a.speech < -30 || a.peak < -15) {
    const d = clampStep(Math.min(-18 - a.speech, -4 - a.peak));
    return {cls: 'warn', text: 'Quiet: raise Mic gain by about ' + Math.min(d, room) + ' dB' + (room < d ? ' (that is the most it goes; talk closer to the mic)' : '') + '.', delta: Math.min(d, room)};
  }
  if (a.snr < 15) return {cls: 'warn', text: 'Noisy: the background is only ' + Math.round(a.snr) + ' dB below your voice. Turn on Noise suppression or set Noise gate to Light, or move closer to the mic.'};
  return {cls: 'ok', text: 'Good: speech ' + fmtDb(a.speech) + ', peaks ' + fmtDb(a.peak) + '.'};
}

function repNumbers(el, rows) {
  el.innerHTML = '';
  rows.forEach(([k, v]) => { const d = document.createElement('div'); d.textContent = k + ' '; const b = document.createElement('b'); b.textContent = v; d.appendChild(b); el.appendChild(d); });
}

function stripDraw(cv, fr, len) {
  const r = window.devicePixelRatio || 1, w = Math.round(cv.clientWidth * r), h = Math.round(cv.clientHeight * r);
  cv.width = w; cv.height = h;
  const g = cv.getContext('2d'), y = (db) => h - vuPct(db) / 100 * h, n = Math.max(len || fr.length, 1);
  g.fillStyle = '#0a1016'; g.fillRect(0, 0, w, h);
  g.fillStyle = 'rgba(34,195,166,.16)'; g.fillRect(0, y(-3), w, y(-6) - y(-3));
  g.fillStyle = 'rgba(242,84,91,.18)'; g.fillRect(0, 0, w, y(-1));
  g.fillStyle = 'rgba(34,195,166,.75)';
  fr.forEach((f, i) => { const x = i / n * w; g.fillRect(x, y(f.db), Math.max(1, w / n), h - y(f.db)); });
  g.strokeStyle = '#f4c04e'; g.lineWidth = Math.max(1, r); g.beginPath();
  fr.forEach((f, i) => { const x = i / n * w; if (i) g.lineTo(x, y(f.pk)); else g.moveTo(x, y(f.pk)); });
  g.stroke();
}

function playhead(strip, src, ac, secs) {
  const head = strip.querySelector('.rep-head'), t0 = ac.currentTime;
  head.style.display = 'block';
  const loop = () => {
    const p = Math.min(1, (ac.currentTime - t0) / secs);
    head.style.left = (p * 100) + '%';
    if (p < 1 && ac.state !== 'closed') requestAnimationFrame(loop); else head.style.display = 'none';
  };
  requestAnimationFrame(loop);
}

let rfss = 0, rfpk = 0, rfx1 = 0, rfn = 0, rfprev = 0;

function accNew() { return {n: 0, act: 0, pw: 0, pk: -120, hist: new Array(121).fill(0), lim: 0, limSum: 0, gate: 0, clip: 0}; }

function accAdd(a, st) {
  a.n++;
  a.hist[Math.max(0, Math.min(120, Math.round(st.db) + 120))]++;
  if (st.pk > a.pk) a.pk = st.pk;
  if (st.pk >= -0.5) a.clip++;
  if (st.db > -45) {
    a.act++; a.pw += Math.pow(10, st.db / 10);
    if (st.lim >= 0.5) a.lim++;
    a.limSum += st.lim || 0;
    if (st.gate) a.gate++;
  }
}

function accSum(a) {
  let low = 0, tot = 0, pw = 0;
  for (let i = 30; i <= 120; i++) tot += a.hist[i];
  const want = Math.max(1, Math.floor(tot / 10));
  for (let i = 30; i <= 120 && low < want; i++) {
    const k = Math.min(a.hist[i], want - low);
    low += k; pw += k * Math.pow(10, (i - 120) / 10);
  }
  const speech = a.act ? 10 * Math.log10(a.pw / a.act) : -120, noise = low ? 10 * Math.log10(pw / low) : -120;
  return {secs: a.n * 0.02, actSecs: a.act * 0.02, speech: speech, peak: a.pk, noise: noise,
    snr: a.act && low ? Math.min(60, speech - noise) : null, limPct: a.act ? 100 * a.lim / a.act : 0,
    limAvg: a.act ? (a.limSum || 0) / a.act : 0,
    gatePct: a.act ? 100 * a.gate / a.act : 0, clipPct: a.n ? 100 * a.clip / a.n : 0};
}

function chkNew(mins) {
  return {running: true, v: 1, mins: mins, elapsed: 0, paused: 0, last: Date.now(), rx: accNew(), tx: accNew(),
    seg: null, rxTx: [], drops: 0, tails: 0, noisy: 0, hum: 0, humN: 0, load: 0, loadMax: 0, loadN: 0,
    txN: 0, txSecs: 0, keyedAt: 0, deadman: 0, timeout: 0, denied: 0, pend: false, srv: [], outDrops: 0, hsPtt: 0};
}

function chkSave() {
  try {
    if (chk) localStorage.setItem('nlCheck', JSON.stringify(chk));
    else localStorage.removeItem('nlCheck');
  } catch (e) {}
}

function chkRx(st) {
  rxLastDb = st.db;
  accAdd(chk.rx, st);
  if (st.db > -24 && st.r1 < 0.3) {
    if (++chk.noisy === 3) chk.tails++;
  } else chk.noisy = 0;
}

function chkWs(m) {
  if (m.ev === 'keyed') { chk.txN++; chk.keyedAt = Date.now(); }
  else if (m.ev === 'denied') chk.denied++;
  else if (m.ev === 'unkeyed') {
    if (chk.keyedAt) chk.txSecs += (Date.now() - chk.keyedAt) / 1000;
    chk.keyedAt = 0;
    if (m.why === 'deadman') chk.deadman++;
    if (m.why === 'timeout') chk.timeout++;
    chk.pend = true;
  }
}

function chkMic(st) {
  if (chk && chk.running && talking && keyed && !testing) accAdd(chk.tx, st);
}
micTaps.push(chkMic);

function chkPoll(d) {
  if (d.rx_load_pct != null) { chk.load += d.rx_load_pct; chk.loadN++; chk.loadMax = Math.max(chk.loadMax, d.rx_load_pct); }
  if (playing && d.audio_active) {
    if (!chk.seg) chk.seg = {s: 0, n: 0};
    if (d.level_db > -60) { chk.seg.s += Math.pow(10, d.level_db / 10); chk.seg.n++; }
    if (analyser && ctx && rxLastDb > -40) {
      const f = new Float32Array(analyser.frequencyBinCount);
      analyser.getFloatFrequencyData(f);
      const hz = ctx.sampleRate / 2 / f.length;
      let lo = 0, hi = 0;
      f.forEach((x, i) => { const p = Math.pow(10, x / 10), fq = i * hz; if (fq >= 50 && fq < 300) lo += p; else if (fq >= 300 && fq < 3400) hi += p; });
      if (hi > 1e-7) { chk.hum += Math.max(-60, Math.min(20, 10 * Math.log10(Math.max(lo, hi * 1e-6) / hi))); chk.humN++; }
    }
  }
  if (!(playing && d.audio_active) && chk.seg) {
    if (chk.seg.n >= 2 && chk.rxTx.length < 300) chk.rxTx.push(10 * Math.log10(chk.seg.s / chk.seg.n));
    chk.seg = null;
  }
  const tx = d.tx || {};
  if (chk.pend && !tx.keyed && tx.last_peak_db != null) { chk.srv.push({pk: tx.last_peak_db, gaps: tx.last_gaps || 0}); chk.pend = false; }
}

function chkTick() {
  if (!chk || !chk.running) return;
  const now = Date.now(), dt = now - chk.last;
  if (dt < 5000) chk.elapsed += dt; else chk.paused += dt;
  chk.last = now;
  const left = Math.max(0, chk.mins * 60000 - chk.elapsed);
  const txt = fmtSecs(chk.elapsed / 1000);
  $('chk-badge').textContent = 'CHECK ' + txt;
  sum('chk', 'Running ' + txt + ' / ' + chk.mins + ':00');
  $('chk-run').textContent = 'Running: ' + txt + ' of ' + chk.mins + ' min. Heard ' + Math.round(chk.rx.act * 0.02) + ' s of audio, ' +
    chk.txN + ' transmission(s) of yours.' + (chk.paused > 5000 ? ' Paused ' + fmtSecs(chk.paused / 1000) + ' (page closed or asleep).' : '');
  if (Math.floor(chk.elapsed / 1000) % 10 === 0) chkSave();
  if (!left) chkStop();
}

function chkUi() {
  const run = !!(chk && chk.running);
  $('chk-start').classList.toggle('hidden', run);
  $('chk-stop').classList.toggle('hidden', !run);
  $('chk-mins').disabled = run;
  $('chk-run').classList.toggle('hidden', !run);
  $('chk-badge').classList.toggle('hidden', !run);
}

function chkStart() {
  chk = chkNew(Number($('chk-mins').value) || 5);
  chkSave(); chkUi(); chkTick();
  note('chk-msg', '', '');
  if (!playing) startListen();
}

function chkSummary(c) {
  const rx = accSum(c.rx), tx = accSum(c.tx);
  const lv = c.rxTx.slice().sort((a, b) => a - b);
  return {at: Date.now(), mins: Math.round(c.elapsed / 6000) / 10, paused: Math.round(c.paused / 1000),
    rx: Object.assign(rx, {nTx: lv.length, spread: lv.length >= 2 ? lv[lv.length - 1] - lv[0] : null,
      quietest: lv.length ? lv[0] : null, loudest: lv.length ? lv[lv.length - 1] : null,
      hum: c.humN ? c.hum / c.humN : null, drops: c.drops, dropsMin: c.elapsed ? c.drops / (c.elapsed / 60000) : 0, tails: c.tails,
      load: c.loadN ? c.load / c.loadN : null, loadMax: c.loadN ? c.loadMax : null, outDrops: c.outDrops || 0, out: canSink() ? hsLabel('hs-out') : 'phone default'}),
    tx: Object.assign(tx, {nTx: c.txN, txSecs: Math.round(c.txSecs), deadman: c.deadman, timeout: c.timeout, denied: c.denied,
      gapTx: c.srv.filter((x) => x.gaps > 0).length, srvN: c.srv.length, srvPeak: c.srv.length ? Math.max(...c.srv.map((x) => x.pk)) : null, hsPtt: c.hsPtt || 0, mic: hsLabel('hs-mic')})};
}

async function chkStop() {
  if (!chk) return;
  const now = Date.now();
  if (now - chk.last < 5000) chk.elapsed += now - chk.last;
  chk.running = false;
  const r = chkSummary(chk);
  chk = null; chkSave(); chkUi();
  sum('chk', '');
  try {
    const prev = localStorage.getItem('nlCheckLast');
    if (prev) localStorage.setItem('nlCheckPrev', prev);
    localStorage.setItem('nlCheckLast', JSON.stringify(r));
  } catch (e) {}
  await chkShow(r);
}

const db0 = (x) => (x == null || x <= -119 ? '-' : Math.round(x) + ' dBFS');

function chkRows(r, p, side) {
  const R = r[side], P = p ? p[side] : null;
  const st = (ok, warn) => (ok ? 'st-ok' : warn ? 'st-warn' : 'st-bad');
  const rows = side === 'rx' ? [
    ['Listened', Math.round(R.secs) + ' s', P && Math.round(P.secs) + ' s', '', 'st-ok'],
    ['Speech level', db0(R.speech), P && db0(P.speech), '-24 to -14', R.actSecs < 5 ? '' : st(R.speech >= -24 && R.speech <= -14, R.speech >= -30 && R.speech <= -10)],
    ['Peak', db0(R.peak), P && db0(P.peak), 'below -1', st(R.peak < -1, R.peak < -0.2)],
    ['Stations, quietest to loudest', R.spread == null ? '-' : Math.round(R.spread) + ' dB', P && (P.spread == null ? '-' : Math.round(P.spread) + ' dB'), 'under 8 dB', R.spread == null ? '' : st(R.spread < 8, R.spread < 14)],
    ['Below 300 Hz (tones, hum)', R.hum == null ? '-' : Math.round(R.hum) + ' dB', P && (P.hum == null ? '-' : Math.round(P.hum) + ' dB'), 'under -25 dB', R.hum == null ? '' : st(R.hum < -25, R.hum < -15)],
    ['Dropouts', R.drops + (R.drops ? ' (' + R.dropsMin.toFixed(1) + '/min)' : ''), P && String(P.drops), 'none', st(R.dropsMin < 0.5, R.dropsMin < 2)],
    ['Squelch tails heard', String(R.tails), P && String(P.tails), 'none', st(R.tails === 0, R.tails < 3)],
    ['Pi load (avg / max)', R.load == null ? '-' : R.load.toFixed(1) + ' / ' + R.loadMax.toFixed(1) + ' %', P && (P.load == null ? '-' : P.load.toFixed(1) + ' %'), 'under 25 %', R.load == null ? '' : st(R.loadMax < 25, R.loadMax < 50)],
    ['Headset unplugged / output lost', R.outDrops == null ? '-' : String(R.outDrops), P && (P.outDrops == null ? '-' : String(P.outDrops)), 'none', R.outDrops == null ? '' : st(R.outDrops === 0, R.outDrops < 2)],
    ['Audio output', R.out || '-', P && (P.out || '-'), '', ''],
  ] : [
    ['Transmissions', R.nTx + (R.nTx ? ' (' + R.txSecs + ' s)' : ''), P && String(P.nTx), '', 'st-ok'],
    ['Speech level', db0(R.speech), P && db0(P.speech), '-24 to -12', R.actSecs < 0.4 ? '' : st(R.speech >= -24 && R.speech <= -12, R.speech >= -30 && R.speech <= -8)],
    ['Peak', db0(R.peak), P && db0(P.peak), '-8 to -1', R.actSecs < 0.4 ? '' : st(R.peak <= -1 && R.peak >= -8, R.peak < -0.2)],
    ['Voice above background', R.snr == null ? '-' : (R.snr >= 60 ? 'over 60' : Math.round(R.snr)) + ' dB', P && (P.snr == null ? '-' : Math.round(P.snr) + ' dB'), 'over 20 dB', R.snr == null ? '' : st(R.snr > 20, R.snr > 12)],
    ['Limiter working', Math.round(R.limPct) + ' %', P && Math.round(P.limPct) + ' %', 'under 20 %', R.actSecs < 0.4 ? '' : st(R.limPct < 20, R.limPct < 40)],
    ['Gate closed while talking', Math.round(R.gatePct) + ' %', P && Math.round(P.gatePct) + ' %', 'under 10 %', R.actSecs < 0.4 ? '' : st(R.gatePct < 10, R.gatePct < 20)],
    ['Transmissions with gaps', R.srvN ? R.gapTx + ' of ' + R.srvN : '-', P && (P.srvN ? P.gapTx + ' of ' + P.srvN : '-'), 'none', R.srvN ? st(R.gapTx === 0, R.gapTx / R.srvN < 0.25) : ''],
    ['Peak at the Pi (after TX gain)', db0(R.srvPeak), P && db0(P.srvPeak), 'below -1', R.srvPeak == null ? '' : st(R.srvPeak < -1, R.srvPeak < -0.2)],
    ['Microphone', R.mic || '-', P && (P.mic || '-'), '', ''],
    ['Headset-button transmissions', R.hsPtt == null ? '-' : String(R.hsPtt), P && (P.hsPtt == null ? '-' : String(P.hsPtt)), '', ''],
    ['Audio stopped / time-outs / refused', R.deadman + ' / ' + R.timeout + ' / ' + R.denied, P && (P.deadman + ' / ' + P.timeout + ' / ' + P.denied), '0 / 0 / 0', st(!R.deadman && !R.timeout && !R.denied, R.deadman < 2)],
  ];
  return rows;
}

function chkTable(id, rows, cmp) {
  const tb = $(id);
  tb.innerHTML = '';
  rows.forEach(([k, now, last, target, cls]) => {
    const tr = document.createElement('tr');
    [k, now].concat(cmp ? [last == null ? '-' : last] : []).concat([target]).forEach((v, i) => {
      const td = document.createElement(i ? 'td' : 'th'); td.textContent = v;
      if (i === 1 && cls) td.className = cls;
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
}

const JIT_STEPS = [150, 250, 500, 1000], TXB_STEPS = [60, 120, 200, 300];
const nextStep = (steps, v) => steps.find((x) => x > Number(v)) || null;

function chkSuggest(r, cfg) {
  const out = [], R = r.rx, T = r.tx, c = cfg || {};
  const mg = Number(mic.gain) || 0;
  const node = (text, change) => out.push({text: text, change: change && Object.assign({node: true}, change)});
  if (R.spread != null && R.spread >= 10 && c.rx_agc === false) node('Stations differed by ' + Math.round(R.spread) + ' dB: turn on Automatic level.', {rx_agc: true});
  if (R.actSecs >= 5 && R.speech < -28) {
    const d = clampStep(-20 - R.speech);
    node('Received speech averaged ' + db0(R.speech) + ': raise RX gain by ' + d + ' dB' + (c.rx_agc ? ' (Automatic level is already at its limit)' : '') + '.',
      {tune_enabled: true, rx_gain_db: Math.min(12, (Number(c.rx_gain_db) || 0) + d)});
  }
  if (R.clipPct > 1) node('Received audio hit full scale ' + R.clipPct.toFixed(1) + ' % of the time: lower RX gain by 3 dB' + (c.rx_agc ? '' : ' or turn on Automatic level') + '.',
    {tune_enabled: true, rx_gain_db: Math.max(-12, (Number(c.rx_gain_db) || 0) - 3)});
  if (R.hum != null && R.hum > -20 && c.rx_hpf === false) node('Strong sound below 300 Hz (CTCSS tones or hum): turn on Cut below 300 Hz.', {rx_hpf: true});
  if (R.tails >= 2 && !Number(c.rx_gate)) node(R.tails + ' squelch tails got through: set the Squelch-tail gate to Light.', {rx_gate: 1});
  else if (R.tails >= 3 && Number(c.rx_gate) === 1) node(R.tails + ' squelch tails got through Light: try Strong.', {rx_gate: 2});
  if (R.dropsMin >= 0.5) {
    const j = nextStep(JIT_STEPS, c.tune_enabled ? c.jitter_ms : 250);
    if (j) node(R.drops + ' dropouts: raise the Listen buffer to ' + (j / 1000) + ' s.', {tune_enabled: true, jitter_ms: j});
    else out.push({text: R.drops + ' dropouts even with the largest Listen buffer: the phone\'s connection is the problem (try Wi-Fi).'});
  }
  if (R.loadMax != null && R.loadMax > 40 && c.rx_hpf) node('The Pi spent up to ' + Math.round(R.loadMax) + ' % of a core on RX cleanup: turn off Cut below 300 Hz to save the most.', {rx_hpf: false});
  if (!T.nTx) out.push({text: 'You didn\'t transmit during the check, so there is nothing to say about your audio yet.'});
  else if (T.actSecs >= 0.4) {
    if (T.limPct > 30 || T.peak > -1) {
      const d = clampStep(Math.max(T.peak + 4, (T.limAvg || 0) + 3, 3));
      out.push({text: 'Your audio was limited ' + Math.round(T.limPct) + ' % of the time: lower Mic gain by ' + d + ' dB.', change: {mic: {gain: Math.max(-12, mg - d)}}});
    } else if (T.speech < -28) {
      const d = Math.min(clampStep(-18 - T.speech), 24 - mg);
      if (d > 0) out.push({text: 'Your speech averaged ' + db0(T.speech) + ': raise Mic gain by ' + d + ' dB.', change: {mic: {gain: mg + d}}});
    }
    if (T.snr != null && T.snr < 15) {
      if (!mic.ns) out.push({text: 'Your background was only ' + Math.round(T.snr) + ' dB below your voice: turn on Noise suppression.', change: {mic: {ns: true}}});
      else if (!Number(mic.gate)) out.push({text: 'Your background was only ' + Math.round(T.snr) + ' dB below your voice: set the Noise gate to Light.', change: {mic: {gate: 1}}});
    }
    if (T.gatePct > 15 && Number(mic.gate)) out.push({text: 'The noise gate closed ' + Math.round(T.gatePct) + ' % of the time while you talked: set it ' + (Number(mic.gate) === 2 ? 'to Light.' : 'Off.'), change: {mic: {gate: Number(mic.gate) - 1}}});
    if (T.srvPeak != null && T.srvPeak > -1 && c.tune_enabled && Number(c.tx_gain_db) > 0) node('Your audio reached ' + db0(T.srvPeak) + ' at the Pi: lower TX gain by 3 dB.', {tx_gain_db: Number(c.tx_gain_db) - 3});
    if (T.srvN && T.gapTx / T.srvN >= 0.25) {
      const b = nextStep(TXB_STEPS, c.tune_enabled ? c.tx_buffer_ms : 120);
      if (b) node(T.gapTx + ' of ' + T.srvN + ' transmissions had gaps: raise the TX buffer to ' + b + ' ms.', {tune_enabled: true, tx_buffer_ms: b});
    }
    if (T.deadman >= 2) out.push({text: T.deadman + ' transmissions stopped because your audio stopped arriving: the phone\'s connection dropped out. Wi-Fi is steadier than mobile data.'});
  }
  if (T.denied >= 2) out.push({text: 'Push-to-talk was refused ' + T.denied + ' times (the node was busy or someone else was transmitting).'});
  return out;
}

async function chkApply(i, s2, btn, undo) {
  const ch = s2.change;
  if (ch.mic) {
    if (!undo) chkUndo[i] = {mic: Object.assign({}, mic)};
    Object.assign(mic, undo ? chkUndo[i].mic : ch.mic);
    try { localStorage.setItem('nlMic', JSON.stringify(mic)); } catch (e) {}
    loadMicUi(); micSummary();
  } else {
    const keys = Object.keys(ch).filter((k) => k !== 'node');
    let body = {};
    if (undo) body = chkUndo[i].cfg;
    else {
      const d = await api('/api/config');
      chkUndo[i] = {cfg: {}};
      keys.forEach((k) => { chkUndo[i].cfg[k] = d.config ? d.config[k] : undefined; body[k] = ch[k]; });
    }
    const res = await post('/api/config', body);
    if (!res.ok) { note('chk-msg', 'err', res.error || 'Could not save.'); return; }
    loadConfig();
  }
  note('chk-msg', 'ok', undo ? 'Put back.' : 'Changed. Run another check to see the difference.');
  btn.textContent = undo ? 'Apply' : 'Undo';
  btn.onclick = () => chkApply(i, s2, btn, !undo);
}

let chkShown = null, chkCmp = false;

async function chkShow(r) {
  chkShown = r;
  if (!r) { $('chk-rep').classList.add('hidden'); return; }
  let prev = null;
  try { prev = JSON.parse(localStorage.getItem('nlCheckPrev') || 'null'); } catch (e) {}
  $('chk-cmp').disabled = !prev;
  ['chk-prev-h1', 'chk-prev-h2'].forEach((id) => $(id).classList.toggle('hidden', !(chkCmp && prev)));
  chkTable('chk-rx', chkRows(r, chkCmp && prev, 'rx'), chkCmp && !!prev);
  chkTable('chk-tx', chkRows(r, chkCmp && prev, 'tx'), chkCmp && !!prev);
  const cfgRes = authed ? await api('/api/config') : {};
  chkCfg = cfgRes.config || null;
  const sugs = chkSuggest(r, chkCfg), box = $('chk-sug');
  box.innerHTML = ''; chkUndo = {};
  if (!sugs.length) { const d = document.createElement('div'); d.className = 'sug'; d.textContent = 'Nothing to change: everything is in range.'; box.appendChild(d); }
  sugs.forEach((s2, i) => {
    const d = document.createElement('div'); d.className = 'sug';
    const t = document.createElement('div'); t.className = 't'; t.textContent = s2.text; d.appendChild(t);
    if (s2.change && (!s2.change.node || authed)) {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = 'Apply';
      b.onclick = () => chkApply(i, s2, b, false); d.appendChild(b);
    }
    box.appendChild(d);
  });
  const n = sugs.filter((x) => x.change).length;
  sum('chk', 'Last check: ' + (n ? n + ' thing' + (n > 1 ? 's' : '') + ' to change' : 'all good'));
  $('chk-rep').classList.remove('hidden');
}

function chkText() {
  const r = chkShown;
  if (!r) return '';
  const lines = ['Node Talker ' + document.querySelector('header .ver').textContent + ' audio check, ' + new Date(r.at).toLocaleString() + ', ' + r.mins + ' min'];
  ['rx', 'tx'].forEach((sd) => {
    lines.push(sd === 'rx' ? 'Receive:' : 'Transmit:');
    chkRows(r, null, sd).forEach(([k, v, , t]) => lines.push('  ' + k + ': ' + v + (t ? ' (target ' + t + ')' : '')));
  });
  lines.push('What to change:');
  document.querySelectorAll('#chk-sug .sug').forEach((e) => { const t = e.querySelector('.t') || e; lines.push('  - ' + t.textContent); });
  return lines.join('\n');
}

async function chkCopy() {
  const t = chkText();
  try { await navigator.clipboard.writeText(t); note('chk-msg', 'ok', 'Report copied.'); }
  catch (e) {
    const ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); note('chk-msg', 'ok', 'Report copied.'); } catch (x) { note('chk-msg', 'err', 'Could not copy.'); }
    ta.remove();
  }
}

function chkInit() {
  try { chk = JSON.parse(localStorage.getItem('nlCheck') || 'null'); } catch (e) { chk = null; }
  if (chk && (!chk.running || chk.v !== 1)) chk = null;
  if (chk) {
    const gap = Date.now() - chk.last;
    chk.paused += gap; chk.last = Date.now();
    if (chk.elapsed >= chk.mins * 60000) chkStop();
  }
  let last = null;
  try { last = JSON.parse(localStorage.getItem('nlCheckLast') || 'null'); } catch (e) {}
  if (!chk && last) chkShow(last);
  chkUi();
  setInterval(chkTick, 1000);
  $('chk-start').addEventListener('click', chkStart);
  $('chk-stop').addEventListener('click', chkStop);
  $('chk-copy').addEventListener('click', chkCopy);
  $('chk-cmp').addEventListener('click', () => { chkCmp = !chkCmp; $('chk-cmp').textContent = chkCmp ? 'Hide last check' : 'Compare with last check'; chkShow(chkShown); });
  $('chk-badge').addEventListener('click', () => { showTab('setup'); foldSet('chk', true); });
}

function pushSample(v) {
  rfss += v * v; if ((v < 0 ? -v : v) > rfpk) rfpk = v < 0 ? -v : v;
  rfx1 += v * rfprev;
  rfprev = v;
  if (++rfn === 160) {
    if (chk && chk.running) chkRx({db: rfss > 0 ? 10 * Math.log10(rfss / 160) : -120, pk: peakDb(rfpk), r1: rfss > 0 ? rfx1 / rfss : 1});
    rfss = 0; rfpk = 0; rfx1 = 0; rfn = 0;
  }
  pend[pendN++] = v;
  const a = v < 0 ? -v : v;
  if (a > peakLocal) peakLocal = a;
  if (pendN >= 800) flush();
}

function push(bytes) {
  if (!streamPcm) {
    for (let i = 0; i < bytes.length; i++) pushSample(UL[bytes[i]]);
    return;
  }
  const s16 = (lo, hi) => { const w = lo | (hi << 8); pushSample((w > 32767 ? w - 65536 : w) / 32768); };
  let i = 0;
  if (oddByte >= 0 && bytes.length) { s16(oddByte, bytes[0]); oddByte = -1; i = 1; }
  for (; i + 1 < bytes.length; i += 2) s16(bytes[i], bytes[i + 1]);
  if (i < bytes.length) oddByte = bytes[i];
}

function listenVolume() { return talking ? 0 : $('vol').value / 100; }

const SPEC_HZ = 4000, SPEC_FPS = 25;
const SPEC_PAL = (() => {
  const stops = [[0, 10, 16, 22], [70, 18, 52, 96], [140, 34, 195, 166], [200, 244, 192, 78], [255, 255, 92, 92]];
  const p = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    let k = 0;
    while (k < stops.length - 2 && i > stops[k + 1][0]) k++;
    const a = stops[k], b = stops[k + 1], t = (i - a[0]) / (b[0] - a[0]);
    for (let c = 0; c < 3; c++) p[i * 3 + c] = a[c + 1] + (b[c + 1] - a[c + 1]) * Math.max(0, Math.min(1, t));
  }
  return p;
})();

function specOn() { return !!play.spec && !!analyser && playing && tab === 'listen' && document.visibilityState === 'visible'; }

function specFit() {
  const wrap = $('spec-wrap'), box = $('spec-box');
  wrap.classList.toggle('off', !play.spec);
  if (!play.spec) return false;
  wrap.classList.remove('small');
  if (box.clientHeight < 40) { wrap.classList.add('small'); return false; }
  const cv = $('spec'), r = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(box.clientWidth * r)), h = Math.max(1, Math.round(box.clientHeight * r));
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; specClear(); }
  return true;
}

function specClear() {
  const cv = $('spec'), g = cv.getContext('2d');
  g.fillStyle = '#0a1016';
  g.fillRect(0, 0, cv.width, cv.height);
}

function specDraw() {
  const cv = $('spec'), g = cv.getContext('2d'), w = cv.width, h = cv.height;
  analyser.getByteFrequencyData(specBins);
  const top = Math.min(specBins.length, Math.ceil(SPEC_HZ / (ctx.sampleRate / 2) * specBins.length));
  const at = (x) => specBins[Math.min(top - 1, Math.floor(x / w * top))];
  if (specMode === 'bars') {
    g.fillStyle = '#0a1016';
    g.fillRect(0, 0, w, h);
    const step = Math.max(2, Math.floor(w / 96));
    for (let x = 0; x < w; x += step) {
      const v = at(x), bh = v / 255 * h;
      g.fillStyle = 'rgb(' + SPEC_PAL[v * 3] + ',' + SPEC_PAL[v * 3 + 1] + ',' + SPEC_PAL[v * 3 + 2] + ')';
      g.fillRect(x, h - bh, step - 1, bh);
    }
    return;
  }
  g.drawImage(cv, 0, 0, w, h - 1, 0, 1, w, h - 1);
  const row = g.createImageData(w, 1), px = row.data;
  for (let x = 0; x < w; x++) {
    const v = at(x), o = x * 4;
    px[o] = SPEC_PAL[v * 3]; px[o + 1] = SPEC_PAL[v * 3 + 1]; px[o + 2] = SPEC_PAL[v * 3 + 2]; px[o + 3] = 255;
  }
  g.putImageData(row, 0, 0);
}

function specLoop(t) {
  specRaf = 0;
  if (!specOn() || !specFit()) return;
  if (t - specLast >= 1000 / SPEC_FPS) { specLast = t; specDraw(); }
  specRaf = requestAnimationFrame(specLoop);
}

function specKick() {
  if (!specFit()) return;
  if (!specOn()) { if (!playing) specClear(); return; }
  if (!specRaf) specRaf = requestAnimationFrame(specLoop);
}

function specToggle() {
  specMode = specMode === 'bars' ? 'waterfall' : 'bars';
  try { localStorage.setItem('nlSpec', specMode); } catch (e) {}
  if (specFit()) specClear();
}

function makeCtx() {
  if (ctx) return true;
  if (!AudioCtx) { $('listen-msg').textContent = 'This browser cannot play live audio.'; return false; }
  ctx = newAudioCtx();
  gainNode = ctx.createGain();
  gainNode.gain.value = listenVolume();
  busNode = ctx.createGain();
  busNode.connect(gainNode);
  if (ctx.createAnalyser) {
    analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.5;
    analyser.minDecibels = -100;
    analyser.maxDecibels = -25;
    busNode.connect(analyser);
    specBins = new Uint8Array(analyser.frequencyBinCount);
  }
  const player = $('player');
  if (ctx.createMediaStreamDestination && player && 'srcObject' in player) {
    mediaDest = ctx.createMediaStreamDestination();
    gainNode.connect(mediaDest);
    player.srcObject = mediaDest.stream;
  } else {
    gainNode.connect(ctx.destination);
  }
  hsApplyOut();
  return true;
}

function autoWaitEnd() {
  if (!autoWait) return;
  document.removeEventListener('pointerdown', autoWait, true);
  document.removeEventListener('keydown', autoWait, true);
  autoWait = null;
}

async function autoListen() {
  if (playing || starting || autoWait || !play.auto || !(authed || publicListen) || !makeCtx()) return;
  await Promise.race([ctx.resume().catch(() => {}), sleep(400)]);
  if (playing || starting || autoWait) return;
  if (ctx.state === 'running') { startListen(); return; }
  note('listen-msg', 'warn', 'Tap anywhere to start listening (the browser holds sound until you do).');
  autoWait = (e) => {
    autoWaitEnd();
    if (e.target && e.target.closest && e.target.closest('#listen-btn')) return;
    if (!playing) startListen();
  };
  document.addEventListener('pointerdown', autoWait, true);
  document.addEventListener('keydown', autoWait, true);
}

async function startListen() {
  autoWaitEnd();
  if (starting) return;
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  if (!makeCtx()) return;
  starting = true;
  try {
    await ctx.resume();
    if (mediaDest) {
      try { await $('player').play(); }
      catch (e) { mediaDest = null; gainNode.disconnect(); gainNode.connect(ctx.destination); }
    }
  } finally { starting = false; }
  playing = true;
  listenAt = performance.now();
  specKick();
  setMediaState();
  wakeLockApply();
  nextT = 0; pendN = 0; oddByte = -1; ups = null;
  $('listen-btn').textContent = 'Stop';
  $('listen-btn').classList.remove('primary');
  note('listen-msg', '', 'Connecting...');
  ctrl = new AbortController();
  try {
    const r = await fetch('/api/listen' + (play.s16 ? '?fmt=s16' : ''), {signal: ctrl.signal, cache: 'no-store'});
    if (!r.ok) {
      let e = 'HTTP ' + r.status;
      try { const d = await r.json(); e = d.error || e; } catch (x) {}
      throw new Error(e);
    }
    streamPcm = /^s16le/.test(r.headers.get('X-Audio-Format') || '');
    oddByte = -1;
    note('listen-msg', 'ok', 'Listening.' + (streamPcm ? ' (16-bit)' : ''));
    const rd = r.body.getReader();
    for (;;) {
      const {value, done} = await rd.read();
      if (done) break;
      push(value);
    }
    if (playing) throw new Error('stream ended');
  } catch (e) {
    if (!playing) return;
    note('listen-msg', 'warn', 'Disconnected (' + e.message + '). Retrying in 3 s...');
    retryTimer = setTimeout(() => { if (playing) startListen(); }, 3000);
  }
}

function stopListen() {
  autoWaitEnd();
  playing = false;
  specKick();
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  if (ctrl) { ctrl.abort(); ctrl = null; }
  if (mediaDest) $('player').pause();
  if (ctx) ctx.suspend();
  setMediaState();
  wakeLockApply();
  $('listen-btn').textContent = 'Listen';
  $('listen-btn').classList.add('primary');
  note('listen-msg', '', '');
}

function toggleListen() { if (playing) stopListen(); else startListen(); }

function setMediaInfo() {
  if (!('mediaSession' in navigator) || typeof MediaMetadata === 'undefined') return;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: nodeLabel ? 'Node ' + nodeLabel : 'ASL node',
    artist: 'Node Talker',
    album: location.hostname,
  });
}

function setMediaState() {
  if (!('mediaSession' in navigator)) return;
  navigator.mediaSession.playbackState = playing ? 'playing' : 'paused';
}

function setupMediaSession() {
  if (!('mediaSession' in navigator)) return;
  setMediaInfo();
  const on = (action, fn) => { try { navigator.mediaSession.setActionHandler(action, fn); } catch (e) {} };
  on('play', () => hsAct('play'));
  on('pause', () => hsAct('pause'));
  on('stop', () => hsAct('stop'));
}

function hsAct(a) {
  if (hs.btn === 'off') return;
  if (hs.btn !== 'ptt') {
    if (a === 'play') { if (!playing) startListen(); } else if (playing) stopListen();
    return;
  }
  if (a === 'stop') { if (talking) pttUp(); return; }
  setTimeout(() => {
    if (!playing) { if (talking) pttUp(); return; }
    if (Date.now() - lastDevChange < 1500 || (mediaDest && $('player').paused)) { hsLost(); return; }
    if (talking) pttUp(); else hsPttDown();
  }, 400);
}

async function hsPttDown() {
  if (!authed || pttState === 'off') {
    note('ptt-msg', 'warn', 'Headset button: push-to-talk is not ready (log in, and set up transmit on the Setup tab).');
    return;
  }
  hsTx = true;
  if (chk && chk.running) chk.hsPtt = (chk.hsPtt || 0) + 1;
  await pttDown();
  if (!talking) hsTx = false;
  pttLabel();
}

function canSink() { const p = $('player'); return !!(p && typeof p.setSinkId === 'function'); }

async function hsApplyOut() {
  try {
    if (mediaDest && canSink()) await $('player').setSinkId(hs.out || '');
    else if (ctx && !mediaDest && typeof ctx.setSinkId === 'function') await ctx.setSinkId(hs.out || '');
  } catch (e) {
    note('hs-msg', 'warn', 'Could not switch to the chosen output (' + (e.message || e.name) + '); playing on the phone default.');
  }
}

function hsFill(id, devs, keep, dflt) {
  const sel = $(id);
  sel.innerHTML = '';
  addOption(sel, '', dflt);
  devs.forEach((d, i) => {
    if (d.deviceId && d.deviceId !== 'default' && d.deviceId !== 'communications') addOption(sel, d.deviceId, d.label || (id === 'hs-out' ? 'Output ' : 'Microphone ') + (i + 1));
  });
  if (keep && !Array.from(sel.options).some((o) => o.value === keep)) addOption(sel, keep, 'Saved device (not connected now)');
  sel.value = keep || '';
}

function hsLabel(id) {
  const sel = $(id);
  return sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex].textContent : '';
}

async function hsDevices() {
  const md = navigator.mediaDevices;
  $('hs-out-row').classList.toggle('hidden', !canSink());
  $('hs-out-note').classList.toggle('hidden', canSink());
  if (!md || !md.enumerateDevices) { $('hs-now').textContent = 'This browser does not list audio devices.'; return []; }
  let list = [];
  try { list = await md.enumerateDevices(); } catch (e) { return []; }
  hsFill('hs-out', list.filter((d) => d.kind === 'audiooutput'), hs.out, 'Phone default');
  hsFill('hs-mic', list.filter((d) => d.kind === 'audioinput'), hs.mic, 'Default (follows Android)');
  $('hs-names').classList.toggle('hidden', list.some((d) => d.label));
  $('hs-now').textContent = 'In use: output ' + (canSink() ? hsLabel('hs-out') : 'phone default') + ' · microphone ' + hsLabel('hs-mic');
  return list;
}

async function hsNames() {
  try {
    const st = await navigator.mediaDevices.getUserMedia({audio: true});
    st.getTracks().forEach((t) => t.stop());
  } catch (e) { note('hs-msg', 'warn', 'The browser did not allow the microphone, so it hides the device names.'); }
  hsDevices();
}

function hsSummary() {
  const b = {listen: 'Button: Listen', ptt: 'Button: push to talk', off: 'Button off'}[hs.btn] || 'Button: Listen';
  sum('hs', b + (hs.out ? ' · output chosen' : '') + (hs.mic ? ' · mic chosen' : ''));
}

function hsSave() {
  hs = {out: $('hs-out').value, mic: $('hs-mic').value, btn: $('hs-btn').value};
  try { localStorage.setItem('nlHeadset', JSON.stringify(hs)); } catch (e) {}
  note('hs-msg', '', '');
  hsSummary();
  hsApplyOut();
  hsDevices();
}

function hsLost() {
  if (talking) pttUp();
  if (chk && chk.running) chk.outDrops = (chk.outDrops || 0) + 1;
  outLost = Date.now();
  stopListen();
  note('listen-msg', 'warn', 'Headset unplugged or audio output changed. Tap Listen to play again (it restarts on its own when the headset comes back).');
}

async function hsDevChange() {
  lastDevChange = Date.now();
  const list = await hsDevices();
  const n = list.length;
  if (outLost && devCount >= 0 && n > devCount && Date.now() - outLost < 30 * 60000 && !playing) {
    outLost = 0;
    startListen();
  }
  devCount = n;
}

async function wakeLockApply() {
  const want = (playing || talking) && $('keep-awake').checked && document.visibilityState === 'visible';
  if (want && !wakeLock && 'wakeLock' in navigator) {
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
    } catch (e) { wakeLock = null; }
  } else if (!want && wakeLock) {
    try { await wakeLock.release(); } catch (e) {}
    wakeLock = null;
  }
}

function pttLabel() {
  const idle = pttState !== 'talking' && pttState !== 'keying';
  $('ptt-label').textContent = pttState === 'talking' ? (hsTx ? 'TALKING (headset)' : 'TALKING') : pttState === 'keying' ? 'Keying...' : (busyText || 'Hold to talk');
  $('ptt').classList.toggle('busy', idle && !!busyText);
}

function pttUi(state, text, cls) {
  const b = $('ptt');
  pttState = state;
  b.classList.toggle('talking', state === 'talking' || state === 'keying');
  b.classList.toggle('ready', state === 'ready');
  b.disabled = state === 'off';
  pttLabel();
  if (text !== undefined) note('ptt-msg', cls, text);
}

function openTalk(force) {
  if (!authed || (tab !== 'listen' && force !== true) || document.visibilityState === 'hidden') return;
  if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
  if (wsRetry) { clearTimeout(wsRetry); wsRetry = null; }
  if (!window.isSecureContext) {
    pttUi('off', 'Push-to-talk needs the https:// page (the browser only allows the microphone there).');
    return;
  }
  try { ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/talk'); }
  catch (e) { pttUi('off', 'Could not open the talk channel.'); return; }
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => { wsReady = true; pttUi('ready', ''); };
  ws.onmessage = (ev) => {
    let m = {};
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (chk && chk.running) chkWs(m);
    if (m.ev === 'keyed') {
      keyed = true; keyedAt = performance.now(); totSec = m.tot || totSec;
      preKey.forEach((f) => ws.send(f)); preKey = [];
      pttUi('talking', '');
      if (navigator.vibrate) navigator.vibrate(30);
    } else if (m.ev === 'denied') {
      const why = {busy: 'The node is busy (someone is talking). Try again when it is quiet.',
        'in-use': 'Someone else is transmitting from Node Talker.',
        'not-ready': 'Node Talker is not linked to AMP (Setup tab, AMP link).'}[m.why] || ('Refused: ' + m.why);
      endTalk(); pttUi('ready', why, 'warn');
    } else if (m.ev === 'unkeyed') {
      keyed = false; endTalk();
      const why = {timeout: 'Time-out: transmission stopped after ' + fmtSecs(m.secs) + '. Release and press again.',
        deadman: 'Audio stopped reaching the node, so it unkeyed.'}[m.why];
      pttUi('ready', why || '', why ? 'warn' : '');
      if (navigator.vibrate) navigator.vibrate([20, 40, 20]);
    }
  };
  ws.onclose = () => {
    wsReady = false;
    if (talking) { keyed = false; endTalk(); }
    pttUi('off', authed ? 'Talk channel closed. Reconnecting...' : '');
    if (authed && tab === 'listen') wsRetry = setTimeout(openTalk, 3000);
  };
}

function sendFrame(buf) {
  if (keyed && ws && ws.readyState === 1) ws.send(buf);
  else if (talking && preKey.length < 25) preKey.push(buf);
}

function feedMic(f32) {
  const r = rs;
  if (!r) return;
  const g = Math.pow(10, (Number(mic.gain) || 0) / 20);
  const merged = new Float32Array(r.buf.length + f32.length);
  merged.set(r.buf, 0);
  for (let i = 0; i < f32.length; i++) merged[r.buf.length + i] = f32[i] * g;
  let pos = r.pos;
  const hpA = 0.83, hpK = (1 + hpA) / (2 * hpA);
  while (pos + r.half + 1 < merged.length) {
    const base = Math.floor(pos);
    const k = r.kern[Math.round((pos - base) * r.phases)];
    const start = base - r.half;
    let acc = 0;
    for (let i = 0; i < r.taps; i++) acc += merged[start + i] * k[i];
    let v = acc;
    if (mic.hp && !mic.eq) { const y = hpA * (r.hpY + v - r.hpX); r.hpX = v; r.hpY = y; v = y * hpK; }
    v = dynProcess(r.dyn, v);
    const a = v < 0 ? -v : v;
    if (a > r.peak) r.peak = a;
    if (a > r.fpk) r.fpk = a;
    r.fss += v * v;
    if (r.dyn.lg < r.flg) r.flg = r.dyn.lg;
    if (r.dyn.gg < r.fgg) r.fgg = r.dyn.gg;
    v = v > 1 ? 1 : v < -1 ? -1 : v;
    r.out[r.n++] = Math.round(v * 32767);
    if (r.n === 160) {
      if (frameSink) frameSink(r.out.slice(0).buffer);
      micFrame({db: r.fss > 0 ? 10 * Math.log10(r.fss / 160) : -120, pk: peakDb(r.fpk),
        lim: -20 * Math.log10(r.flg), gate: !!GATE[Number(mic.gate) || 0] && r.fgg < 0.5});
      r.n = 0; r.fss = 0; r.fpk = 0; r.flg = 1; r.fgg = 1;
    }
    pos += r.ratio;
  }
  const keepFrom = Math.max(0, Math.floor(pos) - r.half);
  r.buf = merged.slice(keepFrom);
  r.pos = pos - keepFrom;
}

async function startMic(sink) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('This browser blocks the microphone here (use the https:// page).');
  if (!capCtx) capCtx = newAudioCtx();
  await capCtx.resume();
  const base = {echoCancellation: !!mic.ec, noiseSuppression: !!mic.ns, autoGainControl: !!mic.agc, channelCount: 1};
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: hs.mic ? Object.assign({deviceId: {exact: hs.mic}}, base) : base}); }
  catch (e) {
    if (!hs.mic || !/Overconstrained|NotFound/.test(e.name)) throw e;
    stream = await navigator.mediaDevices.getUserMedia({audio: base});
  }
  if (!talking && !testing) { stream.getTracks().forEach((t) => t.stop()); return; }
  micStream = stream;
  frameSink = sink;
  rs = makeResampler(capCtx.sampleRate);
  capSrc = capCtx.createMediaStreamSource(stream);
  capSink = capCtx.createGain();
  capSink.gain.value = 0;
  capSink.connect(capCtx.destination);
  if (capCtx.audioWorklet && window.AudioWorkletNode) {
    if (!workletReady) {
      const url = URL.createObjectURL(new Blob([WORKLET_SRC], {type: 'application/javascript'}));
      await capCtx.audioWorklet.addModule(url);
      workletReady = true;
    }
    capNode = new AudioWorkletNode(capCtx, 'nl-tap');
    capNode.port.onmessage = (e) => feedMic(e.data);
  } else {
    capNode = capCtx.createScriptProcessor(1024, 1, 1);
    capNode.onaudioprocess = (e) => feedMic(e.inputBuffer.getChannelData(0).slice(0));
  }
  capSrc.connect(capNode);
  capNode.connect(capSink);
}

const MIC_CHECKS = ['agc', 'ns', 'ec', 'hp', 'lev', 'eq'];

function saveMic() {
  mic = {gain: Number($('mic-gain').value), gate: Number($('mic-gate').value)};
  MIC_CHECKS.forEach((k) => { mic[k] = $('mic-' + k).checked; });
  try { localStorage.setItem('nlMic', JSON.stringify(mic)); } catch (e) {}
  $('mic-gain-v').textContent = fmtGain(mic.gain);
  micSummary();
}

function loadMicUi() {
  MIC_CHECKS.forEach((k) => { $('mic-' + k).checked = !!mic[k]; });
  $('mic-gain').value = mic.gain;
  $('mic-gain-v').textContent = fmtGain(mic.gain);
  $('mic-gate').value = String(Number(mic.gate) || 0);
  $('play-s16').checked = !!play.s16; $('play-smooth').checked = !!play.smooth; $('play-auto').checked = !!play.auto; $('play-spec').checked = !!play.spec;
}

function savePlay() {
  const was = play.s16;
  play = {s16: $('play-s16').checked, smooth: $('play-smooth').checked, auto: $('play-auto').checked, spec: $('play-spec').checked};
  specKick();
  try { localStorage.setItem('nlPlay', JSON.stringify(play)); } catch (e) {}
  ups = null;
  playSummary();
  if (playing && was !== play.s16) { stopListen(); startListen(); }
}

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

async function micTest() {
  if (testing || talking) return;
  testing = true; testBuf = [];
  const fr = [], tap = (st) => fr.push(st);
  $('mic-test').disabled = true;
  $('rep-mic').classList.add('hidden');
  const pc = newAudioCtx();
  try { pc.resume(); } catch (e) {}
  note('mic-test-msg', '', 'Recording 4 s: talk as you would on the air...');
  micTaps.push(tap);
  vuHold = {db: -120, t: 0};
  const done = () => { micTaps = micTaps.filter((f) => f !== tap); $('vu-mic').classList.add('hidden'); };
  try {
    await startMic((buf) => testBuf.push(new Int16Array(buf)));
  } catch (e) {
    testing = false; done(); $('mic-test').disabled = false; pc.close();
    note('mic-test-msg', 'err', 'Microphone: ' + (e.message || e.name));
    return;
  }
  vuRun($('vu-mic'), () => testing);
  await sleep(4000);
  stopMic(); testing = false; done();
  const n = testBuf.reduce((x, y) => x + y.length, 0);
  if (!n) { pc.close(); $('mic-test').disabled = false; note('mic-test-msg', '', 'Nothing was recorded.'); return; }
  const ch = new Float32Array(n);
  let o = 0;
  testBuf.forEach((f) => { for (let i = 0; i < f.length; i++) ch[o++] = f[i] / 32768; });
  const src = playBack(pc, ch);
  const an = analyze(fr), v = micVerdict(an);
  $('rep-mic').classList.remove('hidden');
  stripDraw($('rep-mic-c'), fr, 200);
  const rows = [['Peak', fmtDb(an.peak)], ['Speech', fmtDb(an.speech)], ['Background', an.noise < -90 ? 'silent' : fmtDb(an.noise)],
    ['Voice above background', an.snr >= 60 ? 'over 60 dB' : Math.round(an.snr) + ' dB'], ['Limiter working', Math.round(an.limPct) + ' %']];
  if (GATE[Number(mic.gate) || 0]) rows.push(['Gate closed while talking', Math.round(an.gatePct) + ' %']);
  repNumbers($('rep-mic-n'), rows);
  $('rep-mic-v').className = 'rep-v ' + v.cls;
  $('rep-mic-v').textContent = v.text;
  note('mic-test-msg', '', 'Playing back what the node would get.');
  playhead($('rep-mic-c').parentNode, src, pc, n / 8000);
  src.onended = () => { pc.close(); $('mic-test').disabled = false; };
}

function stopMic() {
  try { if (capSrc) capSrc.disconnect(); } catch (e) {}
  try { if (capNode) capNode.disconnect(); } catch (e) {}
  try { if (capSink) capSink.disconnect(); } catch (e) {}
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  capSrc = capNode = capSink = micStream = null;
  frameSink = null;
}

function endTalk() {
  if (talking) ownUnkeyAt = performance.now();
  talking = false;
  hsTx = false;
  rxMeterBack();
  preKey = [];
  stopMic();
  if (talkTimer) { clearInterval(talkTimer); talkTimer = null; }
  $('ptt-time').textContent = '';
  setTimeout(() => { if (gainNode && !talking) gainNode.gain.value = listenVolume(); }, 1000);
  if (playing && mediaDest && $('player').paused) $('player').play().catch(() => {});
  wakeLockApply();
}

async function pttDown(ev) {
  if (ev) ev.preventDefault();
  if (talking || testing) return;
  if (!wsReady) { openTalk(); return; }
  talking = true; keyed = false; preKey = [];
  if (gainNode) gainNode.gain.value = 0;
  pttUi('keying', '');
  ws.send(JSON.stringify({op: 'key'}));
  talkTimer = setInterval(() => {
    if (keyed) $('ptt-time').textContent = fmtSecs((performance.now() - keyedAt) / 1000) + ' / ' + fmtSecs(totSec);
  }, 250);
  wakeLockApply();
  micPending = true;
  try { await startMic(sendFrame); }
  catch (e) {
    sendOp('unkey');
    keyed = false; endTalk();
    pttUi('ready', 'Microphone: ' + (e.message || e.name), 'err');
  }
  micPending = false;
}

function pttUp(ev) {
  if (ev) ev.preventDefault();
  if (!talking) return;
  sendOp('unkey');
  keyed = false;
  endTalk();
  pttUi(wsReady ? 'ready' : 'off');
}

async function loadFavs() {
  const d = await api('/api/favorites');
  if (!d.ok) return;
  favs = d.favs || [];
  favMax = d.max || 10;
  const sel = $('c-fav'), keep = sel.value;
  sel.innerHTML = '';
  favs.forEach((f, i) => addOption(sel, String(i), favNum(f) + '  ·  ' + f.label));
  if (keep && Number(keep) < favs.length) sel.value = keep;
  $('c-empty').classList.toggle('hidden', favs.length > 0);
  $('c-pick').classList.toggle('hidden', favs.length === 0);
  showSelected();
}

function showSelected() {
  const f = favs[Number($('c-fav').value)];
  $('c-mode').textContent = f ? 'AllStar' : '';
  $('c-num').textContent = f ? favNum(f) : '';
  $('c-label').textContent = f ? f.label : '';
  connectLabel();
}

function selectedLinked() {
  const f = favs[Number($('c-fav').value)];
  return !!f && linkedTargets.has(f.target);
}

function connectLabel() {
  const b = $('c-connect'), on = selectedLinked();
  b.textContent = on ? 'Disconnect' : 'Connect';
  b.classList.toggle('primary', !on);
  b.classList.toggle('danger', on);
}

async function favConnect() {
  const i = $('c-fav').value;
  if (i === '') return;
  const off = selectedLinked();
  $('c-connect').disabled = true;
  note('c-msg', '', off ? 'Disconnecting...' : 'Connecting... (checking the link for up to 15 s)');
  try { setMsg('c-msg', await post(off ? '/api/disconnect' : '/api/connect', {index: Number(i)})); }
  finally { $('c-connect').disabled = false; }
  if (off) setTimeout(pollStatus, 1000); else pollStatus();
}

function ampLinkLine(l) {
  const st = l.state === 'up' ? 'Linked' + (l.secs != null ? ' for ' + fmtSecs(l.secs) : '') + (l.codec ? ' (' + l.codec + ' audio)' : '')
    : l.state === 'calling' ? 'Linking...' : 'Not linked' + (l.error ? ': ' + l.error : '');
  $('amp-link').textContent = st;
  sum('amp', l.state === 'up' ? 'Linked' : l.state === 'calling' ? 'Linking' : 'Not linked');
}

async function loadAmp() {
  const d = await api('/api/amp');
  if (!d.ok) { note('amp-msg', 'err', d.error || 'Could not read the AMP state.'); return; }
  $('amp-proc').textContent = d.running ? 'running (pid ' + d.pid + (d.user ? ', user ' + d.user : '') + ')'
    + (d.count > 1 ? '; ' + d.count + ' AMP servers run here: pick one by its Config path (Advanced)' : '') : 'not running on this Pi';
  $('amp-node').textContent = (d.node || '(not set in AMP)') + (d.callsign ? ' · ' + d.callsign : '');
  $('amp-cfg').textContent = (d.config || 'not found') + (d.config_error ? ' (' + d.config_error + ')' : '');
  const a = d.auth || {};
  $('amp-auth').textContent = a.path + ': ' + (a.error ? a.error : a.ours ? 'has Node Talker\'s login (' + d.login_user + ')'
    : a.exists ? 'Node Talker\'s login is not in it yet' : 'does not exist yet');
  $('amp-ports').textContent = d.host + ' · IAX ' + d.iax_port + ' · web ' + d.http_port
    + (d.http_pwd_set ? (d.http_pwd_auto ? ' (password read from AMP)' : ' (password set here)') : '');
  $('amp-caller').textContent = d.caller + ' (user ' + d.login_user + ')';
  $('amp-setup').disabled = !d.local;
  ampLinkLine(d.link || {});
  if (!ampDirty) {
    const c = (await api('/api/config')).config || {};
    $('amp-host').value = c.amp_host || '127.0.0.1';
    $('amp-iax').value = c.amp_iax_port || '';
    $('amp-http').value = c.amp_http_port || '';
    $('amp-pwd').value = '';
    $('amp-pwd').placeholder = c.amp_http_pwd_set ? '(set; type to change)' : 'auto';
    $('amp-callnum').value = c.amp_caller || '1921';
    $('amp-nodeset').value = c.node || '';
    $('amp-cfgpath').value = c.amp_config || '';
  }
}

async function ampSetup() {
  if (!confirm('Add Node Talker\'s login to AMP\'s login file? A backup is kept, and AMP reloads it by itself.')) return;
  note('amp-msg', '', 'Setting up...');
  setMsg('amp-msg', await post('/api/amp/setup', {}));
  loadAmp();
  setTimeout(loadAmp, 4000);
}

async function ampRedial() { setMsg('amp-msg', await post('/api/amp/redial', {})); setTimeout(loadAmp, 3000); }

async function ampSave() {
  const body = {amp_host: $('amp-host').value.trim(), amp_iax_port: $('amp-iax').value || 0, amp_http_port: $('amp-http').value || 0,
    amp_caller: $('amp-callnum').value.trim(), node: $('amp-nodeset').value.trim(), amp_config: $('amp-cfgpath').value.trim()};
  if ($('amp-pwd').value || $('amp-pwd-clear').checked) body.amp_http_pwd = $('amp-pwd-clear').checked ? '' : $('amp-pwd').value;
  const d = await post('/api/config', body);
  setMsg('amp-msg', d);
  if (d.ok) { ampDirty = false; $('amp-pwd-clear').checked = false; setTimeout(loadAmp, 3000); }
}

function favCopy(f) { return {mode: 'ASL', num: f.num, label: f.label}; }

async function loadFavEditor() {
  const d = await api('/api/favorites');
  if (!d.ok) return;
  favEdit = (d.favs || []).map(favCopy);
  favMax = d.max || 10;
  drawFavEditor();
  if (foldOpen('fav')) loadAmpFavs();
}

async function loadAmpFavs() {
  const dd = await api('/api/amp-favorites');
  ampFavs = dd.favs || [];
  const sel = $('fe-amp');
  sel.innerHTML = '';
  addOption(sel, '', ampFavs.length ? 'From AMP...' : (dd.ok ? 'No AMP favorites found' : 'AMP favorites: ' + (dd.error || 'no answer')));
  ampFavs.forEach((f, i) => addOption(sel, String(i), f.num + ' · ' + f.label));
}

function drawFavEditor() {
  const box = $('fe-rows');
  box.innerHTML = '';
  favEdit.forEach((f, i) => {
    const row = document.createElement('div'); row.className = 'fav-row';
    const n = document.createElement('input'); n.value = f.num; n.placeholder = 'Node number';
    n.setAttribute('aria-label', 'Node number ' + (i + 1)); n.autocapitalize = 'off'; n.spellcheck = false;
    n.oninput = () => { f.num = n.value.trim(); };
    const l = document.createElement('input'); l.value = f.label; l.maxLength = 40; l.placeholder = 'Name';
    l.setAttribute('aria-label', 'Name ' + (i + 1)); l.oninput = () => { f.label = l.value; };
    const x = document.createElement('button'); x.type = 'button'; x.textContent = '✕'; x.setAttribute('aria-label', 'Remove favorite ' + (i + 1));
    x.onclick = () => { favEdit.splice(i, 1); drawFavEditor(); };
    row.appendChild(n); row.appendChild(l); row.appendChild(x);
    box.appendChild(row);
  });
  $('fe-count').textContent = favEdit.length + ' / ' + favMax;
  $('fe-add').disabled = favEdit.length >= favMax;
  $('fe-amp-add').disabled = favEdit.length >= favMax;
}

function feAdd() { if (favEdit.length < favMax) { favEdit.push({mode: 'ASL', num: '', label: ''}); drawFavEditor(); } }
function feAddAmp() {
  const i = $('fe-amp').value;
  if (i === '' || favEdit.length >= favMax) return;
  favEdit.push(favCopy(ampFavs[Number(i)]));
  drawFavEditor();
}
async function feSave() {
  const d = await post('/api/favorites', {favs: favEdit});
  setMsg('fe-msg', d);
  if (d.ok) { favEdit = d.favs.map(favCopy); drawFavEditor(); loadFavs(); }
}

const CFG_NUM = ['port', 'max_listeners', 'tot_sec'], CFG_BOOL = ['public_listen', 'https', 'busy_lockout'];

async function loadConfig() {
  const d = await api('/api/config');
  if (!d.ok) return;
  CFG_NUM.forEach((k) => { $('cfg-' + k).value = d.config[k]; });
  CFG_BOOL.forEach((k) => { $('cfg-' + k).checked = !!d.config[k]; });
  sum('cfg', (d.config.https ? 'HTTPS' : 'HTTP') + ' · ' + d.config.max_listeners + ' listeners' + (d.config.public_listen ? ' · public' : ''));
  $('tune-on').checked = !!d.config.tune_enabled;
  $('tune-tx').value = d.config.tx_gain_db;
  $('tune-rx').value = d.config.rx_gain_db;
  $('tune-jit').value = String(d.config.jitter_ms);
  $('tune-txbuf').value = String(d.config.tx_buffer_ms);
  $('rx-hpf').checked = !!d.config.rx_hpf;
  $('rx-agc').checked = !!d.config.rx_agc;
  $('rx-gate').value = String(d.config.rx_gate);
  tuneUi();
  $('tune-ampweb').classList.toggle('hidden', !ampWeb);
  if (ampWeb) $('tune-ampweb-link').href = 'http://' + location.hostname + ':' + ampWeb + '/';
}

function tuneUi() {
  const on = $('tune-on').checked;
  const clean = [];
  if ($('rx-hpf').checked) clean.push('300 Hz cut');
  if ($('rx-agc').checked) clean.push('auto level');
  if ($('rx-gate').value !== '0') clean.push('gate ' + ($('rx-gate').value === '2' ? 'strong' : 'light'));
  sum('lvl', [on ? 'TX ' + fmtGain(Number($('tune-tx').value)) + ' · RX ' + fmtGain(Number($('tune-rx').value)) : '']
    .concat(clean).filter((x) => x).join(' · ') || 'Off (audio unchanged)');
  ['tune-tx', 'tune-rx', 'tune-jit', 'tune-txbuf'].forEach((id) => { $(id).disabled = !on; });
  $('tune-tx-v').textContent = fmtGain(Number($('tune-tx').value));
  $('tune-rx-v').textContent = fmtGain(Number($('tune-rx').value));
  $('tune-body').classList.toggle('muted', !on);
}

async function saveTune() {
  const body = {tune_enabled: $('tune-on').checked, tx_gain_db: $('tune-tx').value,
    rx_gain_db: $('tune-rx').value, jitter_ms: $('tune-jit').value, tx_buffer_ms: $('tune-txbuf').value,
    rx_hpf: $('rx-hpf').checked, rx_agc: $('rx-agc').checked, rx_gate: $('rx-gate').value};
  setMsg('tune-msg', await post('/api/config', body));
}

function tuneReset() {
  $('tune-tx').value = 0; $('tune-rx').value = 0; $('tune-jit').value = '250'; $('tune-txbuf').value = '120'; tuneUi();
}

async function saveConfig() {
  const body = {};
  CFG_NUM.forEach((k) => { body[k] = $('cfg-' + k).value; });
  CFG_BOOL.forEach((k) => { body[k] = $('cfg-' + k).checked; });
  const d = await post('/api/config', body);
  setMsg('cfg-msg', d);
  if (d.ok) publicListen = body.public_listen;
}

async function pollLog() {
  if (!authed || tab !== 'setup' || !foldOpen('log')) return;
  const d = await api('/api/log?since=' + lastLogId);
  if (!d.ok) return;
  const box = $('log');
  d.lines.forEach((l) => {
    const div = document.createElement('div');
    div.className = l.level;
    div.textContent = l.ts + '  ' + l.msg;
    box.appendChild(div);
    lastLogId = l.id;
  });
  while (box.childNodes.length > 400) box.removeChild(box.firstChild);
  if (d.lines.length) box.scrollTop = box.scrollHeight;
}

document.addEventListener('DOMContentLoaded', () => {
  $('login-form').addEventListener('submit', login);
  $('logout').addEventListener('click', logout);
  $('login-open').addEventListener('click', openLogin);
  $('login-cancel').addEventListener('click', cancelLogin);
  TABS.forEach((t) => $('nav-' + t).addEventListener('click', () => showTab(t)));
  $('listen-btn').addEventListener('click', toggleListen);
  $('vol').addEventListener('input', () => { if (gainNode) gainNode.gain.value = listenVolume(); });
  if ('wakeLock' in navigator) {
    $('awake-row').classList.remove('hidden');
    try { $('keep-awake').checked = localStorage.getItem('nlKeepAwake') === '1'; } catch (e) {}
  }
  $('keep-awake').addEventListener('change', () => {
    try { localStorage.setItem('nlKeepAwake', $('keep-awake').checked ? '1' : '0'); } catch (e) {}
    playSummary();
    wakeLockApply();
  });
  const p = $('ptt');
  p.addEventListener('pointerdown', (e) => { try { p.setPointerCapture(e.pointerId); } catch (x) {} pttDown(e); });
  p.addEventListener('pointerup', pttUp);
  p.addEventListener('pointercancel', pttUp);
  p.addEventListener('lostpointercapture', () => pttUp());
  p.addEventListener('contextmenu', (e) => e.preventDefault());
  p.addEventListener('keydown', (e) => { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) pttDown(e); });
  p.addEventListener('keyup', (e) => { if (e.key === ' ' || e.key === 'Enter') pttUp(e); });
  window.addEventListener('blur', () => { if (!micPending) pttUp(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') pttUp(); else { openTalk(); pollStatus(); }
    specKick();
    wakeLockApply();
  });
  $('c-fav').addEventListener('change', showSelected);
  $('c-connect').addEventListener('click', favConnect);
  $('amp-setup').addEventListener('click', ampSetup);
  $('amp-redial').addEventListener('click', ampRedial);
  $('amp-refresh').addEventListener('click', loadAmp);
  $('amp-save').addEventListener('click', ampSave);
  ['amp-host', 'amp-iax', 'amp-http', 'amp-pwd', 'amp-callnum', 'amp-nodeset', 'amp-cfgpath'].forEach((id) => $(id).addEventListener('input', () => { ampDirty = true; }));
  $('fe-add').addEventListener('click', feAdd);
  $('fe-amp-add').addEventListener('click', feAddAmp);
  $('fe-save').addEventListener('click', feSave);
  $('cfg-save').addEventListener('click', saveConfig);
  ['tune-on', 'tune-tx', 'tune-rx', 'rx-hpf', 'rx-agc', 'rx-gate'].forEach((id) => $(id).addEventListener('input', tuneUi));
  $('tune-save').addEventListener('click', saveTune);
  loadMicUi();
  chkInit();
  MIC_CHECKS.concat(['gain']).forEach((k) => $('mic-' + k).addEventListener('input', saveMic));
  $('mic-gate').addEventListener('change', saveMic);
  ['play-s16', 'play-smooth', 'play-auto', 'play-spec'].forEach((id) => $(id).addEventListener('change', savePlay));
  $('spec').addEventListener('click', specToggle);
  window.addEventListener('resize', specKick);
  $('mic-test').addEventListener('click', micTest);
  try { window.name = 'asl_dvs_listen_amp'; } catch (e) {}
  $('amp-web').addEventListener('click', (ev) => { ev.preventDefault(); openNamedTab($('amp-web').href, 'amp_web'); });
  $('tune-reset').addEventListener('click', tuneReset);
  FOLDS.forEach((k) => $('cd-' + k).querySelector('.fold-btn').addEventListener('click', () => foldSet(k, !foldOpen(k))));
  setupMediaSession();
  $('hs-btn').value = hs.btn;
  ['hs-out', 'hs-mic', 'hs-btn'].forEach((id) => $(id).addEventListener('change', hsSave));
  $('hs-names').addEventListener('click', hsNames);
  $('player').addEventListener('pause', () => { if (playing && mediaDest && $('player').paused) hsLost(); });
  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) navigator.mediaDevices.addEventListener('devicechange', hsDevChange);
  hsSummary();
  hsDevices().then((l) => { devCount = l.length; });
  pttUi('off', '');
  whoami().then(() => { if (authed) loadFavs(); });
  setInterval(pollStatus, 1500);
  setInterval(pollLog, 3000);
});
"""

_ICON_CONNECT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"></path><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"></path></svg>'
_ICON_LISTEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 14v-2a8 8 0 0 1 16 0v2"></path><rect x="3" y="14" width="4" height="6" rx="1.5"></rect><rect x="17" y="14" width="4" height="6" rx="1.5"></rect></svg>'
_ICON_SETUP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"></path><circle cx="16" cy="7" r="2"></circle><circle cx="10" cy="17" r="2"></circle></svg>'

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#161e2e">
<title>Node Talker</title>
<style>__CSS__</style>
</head>
<body>
<header><div class="hdr-left"><h1>Node Talker</h1><div class="logo-sub">AMP · web</div></div><span class="ver">AMP · v__VERSION__</span><span class="sp"></span>
<a id="amp-web" class="pill hidden" href="#" aria-label="Open AMP's web page">AMP</a>
<button id="login-open" class="pill hidden" type="button">Log In</button>
<button id="logout" class="pill hidden" type="button">Log Out</button></header>
<div id="login-screen">
<div id="login-card">
<h2>Node Talker Login</h2>
<form id="login-form">
<input type="password" id="pw" placeholder="Password" autocomplete="current-password" aria-label="Password" required>
<button id="login-btn" type="submit">Log In</button>
</form>
<div id="login-msg"></div>
<div id="login-tls">__TLS_NOTE__</div>
<button id="login-cancel" class="hidden" type="button">Cancel</button>
</div>
</div>
<main>

<section id="tab-connect" class="hidden">
<div class="card">
<h2>Links</h2>
<table class="links"><thead><tr><th>Node</th><th>Name</th><th>State</th></tr></thead><tbody id="s-links"></tbody></table>
<div id="s-nolinks" class="muted small" style="margin-top:8px">No links.</div>
<div id="s-links-err" class="msg warn hidden">Could not read the links from AMP.</div>
</div>
<div class="card">
<h2>Connect</h2>
<div id="c-empty" class="muted">No favorites yet. Add up to 10 on the Setup tab.</div>
<div id="c-pick">
<label for="c-fav">Favorite</label>
<select id="c-fav" style="width:100%;min-height:52px;margin-top:6px;font-size:16px"></select>
<div class="sel-card">
<div class="row" style="margin:0"><span class="tag" id="c-mode"></span><span class="big-num" id="c-num"></span></div>
<div class="muted" id="c-label"></div>
<button id="c-connect" class="btn primary big" type="button">Connect</button>
</div>
</div>
<div id="c-msg" class="msg"></div>
</div>
</section>

<section id="tab-listen" class="hidden">
<div class="lpanel">
<div class="row listen-row"><button id="listen-btn" class="btn primary big" type="button">Listen</button>
<svg class="vol-i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z"></path><path d="M16 9a4 4 0 0 1 0 6"></path></svg>
<input type="range" id="vol" min="0" max="200" value="100" aria-label="Volume"></div>
<div class="lstat"><span class="mono" id="st-node" title="Node">-</span>
<span id="st-feed-w"><span id="st-feed" class="dot"></span><span id="st-feed-t">link</span></span>
<span title="Lit while the node is passing audio"><span id="st-active" class="dot"></span>RX</span>
<span id="s-tx-w" title="Lit while someone transmits from Node Talker"><span id="s-tx" class="dot"></span>TX</span>
<span id="st-listeners" title="Listeners">-</span><span id="chk-badge" class="chk hidden" title="An audio check is running (Setup tab)"></span></div>
<div class="spec" id="spec-wrap">
<div class="spec-box" id="spec-box"><canvas id="spec" aria-label="Audio spectrum: tap to switch between waterfall and bars"></canvas>
<span class="spec-lo" aria-hidden="true"></span><span class="spec-t" style="left:7.5%">300</span><span class="spec-t" style="left:25%">1k</span>
<span class="spec-t" style="left:50%">2k</span><span class="spec-t" style="left:75%">3k</span></div>
<div class="spec-meter" id="spec-meter"><div class="meter"><i id="meter-bar"></i></div><span id="st-level" class="muted small mono">-inf</span></div>
</div>
<audio id="player" playsinline class="hidden"></audio>
<div id="listen-msg" class="msg"></div>
<div id="ptt-card">
<button id="ptt" type="button" disabled aria-label="Push to talk: hold to transmit"><span id="ptt-label">Hold to talk</span><span id="ptt-time"></span></button>
<div class="ptt-line"><span id="ptt-msg" class="msg"></span><span id="ptt-info" class="muted">-</span></div>
</div>
</div>
</section>

<section id="tab-setup" class="hidden">
<div class="card fold" id="cd-amp">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-amp"><span class="fold-t">AMP link</span><span class="fold-sum" id="sum-amp"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-amp">
<p class="muted small">Node Talker calls the AMP node like a private link: it hears everything the node passes, and
push-to-talk goes out to the radio and every link. AMP needs Node Talker's login in its login file once.</p>
<table>
<tr><th>Link</th><td id="amp-link">-</td></tr>
<tr><th>AMP</th><td id="amp-proc">-</td></tr>
<tr><th>Node</th><td id="amp-node">-</td></tr>
<tr><th>Config</th><td><code id="amp-cfg">-</code></td></tr>
<tr><th>Login file</th><td id="amp-auth">-</td></tr>
<tr><th>Address</th><td id="amp-ports">-</td></tr>
<tr><th>Calls in as</th><td id="amp-caller">-</td></tr>
</table>
<div class="row"><button id="amp-setup" class="btn primary" type="button">Set up for me</button>
<button id="amp-redial" class="btn" type="button">Link again</button>
<button id="amp-refresh" class="btn" type="button">Refresh</button></div>
<div id="amp-msg" class="msg"></div>
<details class="small"><summary>Advanced</summary>
<p class="muted small">Leave these empty to read them from AMP on this Pi.</p>
<div class="row"><label>Host <input id="amp-host" placeholder="127.0.0.1" style="width:150px"></label>
<label>IAX port <input type="number" id="amp-iax" min="0" max="65535" placeholder="auto"></label>
<label>Web port <input type="number" id="amp-http" min="0" max="65535" placeholder="auto"></label></div>
<div class="row"><label>AMP web password <input type="password" id="amp-pwd" autocomplete="off" placeholder="auto" style="width:170px"></label>
<label><input type="checkbox" id="amp-pwd-clear"> Clear it</label></div>
<div class="row"><label>Node <input id="amp-nodeset" inputmode="numeric" placeholder="from AMP" style="width:110px"></label>
<label>Calls in as <input id="amp-callnum" inputmode="numeric" style="width:110px"></label></div>
<div class="row"><label style="flex:1">Config path <input id="amp-cfgpath" placeholder="auto: amp-server.json" style="width:100%" autocapitalize="off" spellcheck="false"></label></div>
<div class="row"><button id="amp-save" class="btn" type="button">Save</button></div>
</details>
</div>
</div>

<div class="card fold" id="cd-cfg">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-cfg"><span class="fold-t">Settings</span><span class="fold-sum" id="sum-cfg"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-cfg">
<div class="row"><label>Web port <input type="number" id="cfg-port" min="1024" max="65535"></label>
<label>Max listeners <input type="number" id="cfg-max_listeners" min="1" max="10"></label>
<label>TX time-out (s) <input type="number" id="cfg-tot_sec" min="30" max="600"></label></div>
<div class="row"><label><input type="checkbox" id="cfg-https"> HTTPS (needed for the microphone)</label></div>
<div class="row"><label><input type="checkbox" id="cfg-busy_lockout"> Don't transmit while the node is busy</label></div>
<div class="row"><label><input type="checkbox" id="cfg-public_listen"> Listen without logging in</label></div>
<p class="muted small">HTTPS uses a certificate made on this Pi, so the browser shows a warning: accept it to continue. Changing a port or HTTPS restarts Node Talker.</p>
<div class="row"><button id="cfg-save" class="btn primary" type="button">Save</button></div>
<div id="cfg-msg" class="msg"></div>
</div>
</div>

<div class="card fold" id="cd-fav">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-fav"><span class="fold-t">Favorites</span><span class="fold-sum" id="fe-count"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-fav">
<p class="muted small">The Connect tab offers only these: AllStar node numbers, or a direct address such as
<code>iax:user@192.168.1.20:4569/12345,password</code> for a private node.</p>
<div id="fe-rows"></div>
<div class="row"><button id="fe-add" class="btn" type="button">Add row</button>
<select id="fe-amp" aria-label="AMP favorites"></select><button id="fe-amp-add" class="btn" type="button">Add</button></div>
<div class="row"><button id="fe-save" class="btn primary" type="button">Save favorites</button></div>
<div id="fe-msg" class="msg"></div>
</div>
</div>

<div class="card fold" id="cd-chk">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-chk"><span class="fold-t">Audio check</span><span class="fold-sum" id="sum-chk"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-chk">
<p class="muted small">Start a check, go to the Listen tab and use the node as usual: listen, talk, listen. Come back
for a report with averages and what to change. Only numbers are kept, never audio, and only in this browser.</p>
<div class="row"><label for="chk-mins" style="min-width:90px">Length</label>
<select id="chk-mins"><option value="2">2 min</option><option value="5" selected>5 min</option><option value="10">10 min</option><option value="15">15 min</option></select>
<button id="chk-start" class="btn primary" type="button">Start check</button><button id="chk-stop" class="btn hidden" type="button">Stop</button></div>
<div id="chk-run" class="chk-run hidden"></div>
<div id="chk-rep" class="hidden">
<h3 style="margin:10px 0 4px">Receive</h3>
<table class="chk-t"><thead><tr><th></th><th>Now</th><th id="chk-prev-h1" class="hidden">Last</th><th>Target</th></tr></thead><tbody id="chk-rx"></tbody></table>
<h3 style="margin:10px 0 4px">Transmit</h3>
<table class="chk-t"><thead><tr><th></th><th>Now</th><th id="chk-prev-h2" class="hidden">Last</th><th>Target</th></tr></thead><tbody id="chk-tx"></tbody></table>
<h3 style="margin:12px 0 2px">What to change</h3>
<div id="chk-sug"></div>
<div class="row"><button id="chk-cmp" class="btn" type="button">Compare with last check</button>
<button id="chk-copy" class="btn" type="button">Copy report</button></div>
<div id="chk-msg" class="msg"></div>
</div>
</div>
</div>

<div class="card fold" id="cd-lvl">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-lvl"><span class="fold-t">Audio levels</span><span class="fold-sum" id="sum-lvl"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-lvl">
<div class="row"><label><input type="checkbox" id="tune-on"> Adjust audio levels here</label></div>
<p class="muted small">Off: the gains and buffers below aren't used. These change only this page's path,
not the node or the radio.</p>
<div id="tune-body">
<div class="row"><label for="tune-tx" style="min-width:130px">Mic to node (TX)</label>
<input type="range" id="tune-tx" min="-12" max="12" step="1" style="flex:1"><span id="tune-tx-v" class="mono small">0 dB</span></div>
<div class="row"><label for="tune-rx" style="min-width:130px">Node to phone (RX)</label>
<input type="range" id="tune-rx" min="-12" max="12" step="1" style="flex:1"><span id="tune-rx-v" class="mono small">0 dB</span></div>
<div class="row"><label for="tune-jit" style="min-width:130px">Listen buffer</label>
<select id="tune-jit"><option value="150">0.15 s (Wi-Fi, fastest)</option><option value="250">0.25 s (default)</option>
<option value="500">0.5 s</option><option value="1000">1 s (weak signal)</option></select></div>
<div class="row"><label for="tune-txbuf" style="min-width:130px">TX buffer</label>
<select id="tune-txbuf"><option value="60">60 ms</option><option value="120">120 ms (default)</option>
<option value="200">200 ms</option><option value="300">300 ms (busy Wi-Fi)</option></select></div>
<table>
<tr><th>TX peak</th><td id="tune-txpk" class="mono">-</td></tr>
<tr><th>RX level</th><td id="tune-rxpk" class="mono">-</td></tr>
<tr><th>TX gaps</th><td id="tune-gaps" class="mono">-</td></tr>
</table>
<p class="muted small">Aim for TX peaks around -6 to -3 dBFS on normal speech, without reaching 0.</p>
</div>
<h2 style="margin-top:14px">RX cleanup: what listeners hear</h2>
<p class="muted small">Done once on the Pi for every listener; the node and other links are not changed. Separate from
"Adjust audio levels here" above.</p>
<div class="row"><label><input type="checkbox" id="rx-hpf"> Cut below 300 Hz (CTCSS tones and hum)</label></div>
<div class="row"><label><input type="checkbox" id="rx-agc"> Automatic level (brings quiet stations up, loud ones down a little)</label></div>
<div class="row"><label for="rx-gate" style="min-width:130px">Squelch-tail gate</label>
<select id="rx-gate"><option value="0">Off</option><option value="1">Light</option><option value="2">Strong (can clip hissy speech)</option></select></div>
<table><tr><th>Processing load</th><td id="rx-load" class="mono">-</td></tr></table>
<p id="tune-ampweb" class="small hidden">For the node's own levels (the radio's USB audio and the network meters)
use <a id="tune-ampweb-link" href="#" target="_blank" rel="noopener">AMP's web page</a>.</p>
<div class="row"><button id="tune-save" class="btn primary" type="button">Save</button>
<button id="tune-reset" class="btn" type="button">Reset to 0 dB</button></div>
<div id="tune-msg" class="msg"></div>
</div>
</div>

<div class="card fold" id="cd-mic">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-mic"><span class="fold-t">Microphone</span><span class="fold-sum" id="sum-mic"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-mic">
<p class="muted small">Saved in this browser only; each phone keeps its own. Browsers can't change the phone's own
mic volume, so the gain here is applied in the page.</p>
<div class="row"><label><input type="checkbox" id="mic-lev"> Leveler (keeps an even level and never clips)</label></div>
<div class="row"><label><input type="checkbox" id="mic-agc"> Automatic gain (the browser levels the mic; leave off with the leveler)</label></div>
<div class="row"><label><input type="checkbox" id="mic-ns"> Noise suppression</label></div>
<div class="row"><label><input type="checkbox" id="mic-ec"> Echo cancellation (rarely needed: listen audio is muted while you talk)</label></div>
<div class="row"><label><input type="checkbox" id="mic-hp"> Voice filter (cuts rumble below about 250 Hz)</label></div>
<div class="row"><label><input type="checkbox" id="mic-eq"> Radio voice (cuts below 300 Hz, lifts 2.5 kHz; leave off if the radio adds pre-emphasis)</label></div>
<div class="row"><label for="mic-gate" style="min-width:130px">Noise gate</label>
<select id="mic-gate"><option value="0">Off</option><option value="1">Light</option><option value="2">Strong</option></select></div>
<div class="row"><label for="mic-gain" style="min-width:130px">Mic gain</label>
<input type="range" id="mic-gain" min="-12" max="24" step="1" style="flex:1"><span id="mic-gain-v" class="mono small">0 dB</span></div>
<p class="muted small">With automatic gain on, the browser undoes most of the mic gain; turn it off for a fixed level.</p>
<div class="row"><button id="mic-test" class="btn" type="button">Test mic (4 s, plays back)</button></div>
<div class="vu hidden" id="vu-mic" aria-live="off">
<div class="vu-bar"><i class="vu-avg"></i><i class="vu-pk"></i><i class="vu-hold"></i></div>
<div class="vu-scale"><span>-60</span><span>-40</span><span>-20</span><span>-6 · -3</span><span>0 dBFS</span></div>
<div class="vu-gr" title="How much the leveler or limiter is turning you down"><i></i></div>
<div class="vu-txt"><span class="vu-num">-</span><span class="vu-lim">-</span></div>
</div>
<div id="mic-test-msg" class="msg"></div>
<div class="rep hidden" id="rep-mic">
<h3>Mic test report</h3>
<div class="rep-strip"><canvas id="rep-mic-c"></canvas><span class="rep-lbl">your level, 4 s</span><i class="rep-head"></i></div>
<div class="rep-n" id="rep-mic-n"></div>
<div class="rep-v" id="rep-mic-v"></div>
</div>
</div>
</div>

<div class="card fold" id="cd-hs">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-hs"><span class="fold-t">Headset / audio output</span><span class="fold-sum" id="sum-hs"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-hs">
<p class="muted small">For a wired, USB-C or Bluetooth headset. Saved in this browser only; each phone keeps its own.</p>
<div id="hs-out-row"><label for="hs-out">Audio output</label>
<select id="hs-out" style="width:100%;min-height:44px;margin-top:6px"></select></div>
<p class="muted small hidden" id="hs-out-note">This browser plays through whatever Android is using: plug in the headset, or pick the Bluetooth device in Android's sound settings, and Node Talker follows it.</p>
<div style="margin-top:10px"><label for="hs-mic">Microphone for push-to-talk</label>
<select id="hs-mic" style="width:100%;min-height:44px;margin-top:6px"></select></div>
<p class="muted small">Default follows Android: the headset mic when a headset is plugged in. With Bluetooth, picking the phone's own mic can keep the headset in music quality while you talk, on some phones.</p>
<div style="margin-top:10px"><label for="hs-btn">Headset button</label>
<select id="hs-btn" style="width:100%;min-height:44px;margin-top:6px">
<option value="listen">Listen on / off</option>
<option value="ptt">Push to talk: press to talk, press again to stop</option>
<option value="off">Off</option>
</select></div>
<p class="muted small">The button only reaches the page while Node Talker is playing. Push to talk uses the same transmit as the Talk button, with the same time-out; if the second press doesn't arrive, the time-out ends the transmission.</p>
<div class="row"><button id="hs-names" class="btn hidden" type="button">Show device names</button></div>
<div class="muted small" id="hs-now"></div>
<div id="hs-msg" class="msg"></div>
</div>
</div>

<div class="card fold" id="cd-play">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-play"><span class="fold-t">Playback</span><span class="fold-sum" id="sum-play"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-play">
<p class="muted small">Saved in this browser only; each phone keeps its own.</p>
<div class="row"><label><input type="checkbox" id="play-spec"> Show the spectrum on the Listen tab (tap it to switch waterfall / bars)</label></div>
<div class="row"><label><input type="checkbox" id="play-auto"> Start listening when the page opens (the browser may want one tap first)</label></div>
<div class="row hidden" id="awake-row"><label><input type="checkbox" id="keep-awake"> Keep the screen on while listening or talking</label></div>
<div class="row"><label><input type="checkbox" id="play-s16"> 16-bit audio (cleaner on quiet audio; 128 kbit/s instead of 64)</label></div>
<div class="row"><label><input type="checkbox" id="play-smooth"> Smooth playback (filtered upsampling, no sizzle)</label></div>
</div>
</div>

<div class="card fold" id="cd-log">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-log"><span class="fold-t">Log</span><span class="fold-sum" id="sum-log"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-log">
<div id="log"></div>
</div>
</div>

</section>
</main>
<nav class="tabs hidden" id="nav" aria-label="Main">
<button id="nav-connect" type="button">__ICON_CONNECT__Connect</button>
<button id="nav-listen" type="button">__ICON_LISTEN__Listen</button>
<button id="nav-setup" type="button">__ICON_SETUP__Setup</button>
</nav>
<script>__JS__</script>
</body>
</html>
"""


_page = None
_TLS_NOTE = ""


def render_page():
    global _page
    if _page is None:
        html = _HTML_TEMPLATE
        for key, val in (("__CSS__", _CSS), ("__JS__", _JS), ("__ICON_CONNECT__", _ICON_CONNECT), ("__ICON_LISTEN__", _ICON_LISTEN),
                         ("__ICON_SETUP__", _ICON_SETUP), ("__VERSION__", VERSION), ("__TLS_NOTE__", _TLS_NOTE)):
            html = html.replace(key, val)
        _page = html.encode("utf-8")
    return _page


def amp_redial():
    AMP_LINK.redial("asked from the page")
    return {"ok": True, "message": "Linking to AMP again..."}


_POST_ACTIONS = {
    "/api/config": (config_update, ()),
    "/api/amp/setup": (lambda b: amp_setup(), ()),
    "/api/amp/redial": (lambda b: amp_redial(), ()),
    "/api/favorites": (lambda b: fav_save(b.get("favs")), ()),
    "/api/connect": (lambda b: fav_connect(b.get("index")), ()),
    "/api/disconnect": (lambda b: fav_disconnect(b.get("index")), ()),
}
_OPEN_GET_PATHS = ("/", "/index.html", "/api/health", "/api/whoami")
_PUBLIC_LISTEN_PATHS = ("/api/status", "/api/listen")


class Handler(BaseHTTPRequestHandler):
    server_version = "amp_nodetalker/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 60
    disable_nagle_algorithm = True

    def log_message(self, fmt, *args):
        pass

    def _peer(self):
        return self.client_address[0] if self.client_address else "?"

    def _proxied(self):
        peer = _parse_ip(self._peer())
        return bool(peer is not None and peer.is_loopback and self.headers is not None
                    and any(h in self.headers for h in _PROXY_HEADERS))

    def _ip(self):
        if self._proxied():
            fwd = (self.headers.get("CF-Connecting-IP") or self.headers.get("X-Real-IP")
                   or self.headers.get("X-Forwarded-For", "").split(",")[-1]).strip()
            ip = _parse_ip(fwd)
            return str(ip) if ip is not None else "proxied"
        ip = _parse_ip(self._peer())
        return str(ip) if ip is not None else self._peer()

    def _wan(self):
        return self._proxied() or not _is_lan(self._peer())

    def _secure(self):
        if self.server.ssl_ctx is not None:
            return True
        return self._proxied() and self.headers.get("X-Forwarded-Proto", "").strip().lower() == "https"

    def _wan_refused(self):
        if _cfg_get("allow_wan") or not self._wan():
            return False
        self.close_connection = True
        self._json(403, {"ok": False, "error": "Node Talker is not open to the internet (allow_wan is off)."})
        return True

    def _token(self):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == _SESSION_COOKIE_NAME:
                return v
        return ""

    def _authed(self):
        return _check_session(self._token())

    def _head(self, code, ctype, headers):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()

    def _send(self, code, body, ctype, headers=None):
        self._head(code, ctype, dict(headers or {}, **{"Content-Length": str(len(body))}))
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj, headers=None):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json", headers)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if n < 0 or n > MAX_JSON_BYTES:
            self.close_connection = True
            return None
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return body if isinstance(body, dict) else None

    def _cookie(self, token, max_age):
        c = _session_cookie_header(token, max_age)
        return c + "; Secure" if self._secure() else c

    def do_GET(self):
        if self._wan_refused():
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        authed = self._authed()
        if path not in _OPEN_GET_PATHS and not authed:
            if not (path in _PUBLIC_LISTEN_PATHS and _cfg_get("public_listen")):
                self._json(401, {"ok": False, "error": "Log in first."})
                return
        try:
            if path in ("/", "/index.html"):
                self._send(200, render_page(), "text/html; charset=utf-8")
            elif path == "/api/health":
                self._json(200, {"ok": True, "version": VERSION})
            elif path == "/api/whoami":
                t = amp_target()
                local = t["host"] in ("127.0.0.1", "localhost")
                self._json(200, {"ok": True, "authed": authed, "public_listen": _cfg_get("public_listen"),
                                 "backend": _root_backend_available(), "account": auth_account(),
                                 "amp_web": t["http_port"] if local and port_open_cached(t["http_port"]) else None})
            elif path == "/api/status":
                self._json(200, dict(build_status(authed), ok=True))
            elif path == "/api/listen":
                self._stream((query.get("fmt") or [""])[0] == "s16")
            elif path == "/api/talk":
                self._talk()
            elif path == "/api/amp":
                self._json(200, amp_state())
            elif path == "/api/favorites":
                self._json(200, {"ok": True, "max": FAV_MAX, "main": main_node(),
                                 "favs": [dict(f, target=fav_target(f)) for f in fav_load()]})
            elif path == "/api/amp-favorites":
                favs, err = amp_favorites()
                self._json(200, {"ok": not err, "favs": favs, "error": err})
            elif path == "/api/config":
                with _config_lock:
                    cfg = dict(_config)
                self._json(200, {"ok": True, "config": public_config(cfg)})
            elif path == "/api/log":
                try:
                    since = int(query.get("since", ["0"])[0])
                except ValueError:
                    since = 0
                with _log_lock:
                    lines = [x for x in _log if x["id"] > since]
                self._json(200, {"ok": True, "lines": lines})
            else:
                self._json(404, {"ok": False, "error": "Not found."})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _stream(self, pcm=False):
        lst = HUB.add_listener(self._ip(), pcm)
        if lst is None:
            self.close_connection = True
            self._json(503, {"ok": False, "error": f"All {_cfg_get('max_listeners')} listener slots are in use."})
            return
        try:
            self._head(200, "application/octet-stream", {
                "X-Audio-Format": "s16le; rate=8000; channels=1" if pcm else "mulaw; rate=8000; channels=1",
                "Connection": "close"})
            self.close_connection = True
            self.connection.settimeout(15)
            while True:
                chunk = HUB.wait_chunk(lst)
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                elif time.monotonic() - HUB.pump_beat > 5.0:
                    break
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            pass
        finally:
            HUB.remove_listener(lst)

    def _talk(self):
        self.close_connection = True
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        key = self.headers.get("Sec-WebSocket-Key", "")
        if (self.headers.get("Upgrade", "").lower() != "websocket"
                or "upgrade" not in self.headers.get("Connection", "").lower() or not key):
            self._json(400, {"ok": False, "error": "WebSocket upgrade required."})
            return
        if origin not in (f"https://{host}", f"http://{host}"):
            self._json(403, {"ok": False, "error": "Wrong origin."})
            return
        accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.wfile.flush()
        self.connection.settimeout(60)
        ws = WebSocket(self)
        who = self._ip()
        stop = threading.Event()

        def pinger():
            while not stop.wait(20):
                ws.send(9, b"nl")

        threading.Thread(target=pinger, name="ws-ping", daemon=True).start()
        try:
            while True:
                op, data = ws.recv()
                if op == 8:
                    break
                if op == 2:
                    TALKER.audio(ws, data)
                elif op == 1:
                    try:
                        msg = json.loads(data.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("op") == "key":
                        ok, why = TALKER.key(ws, who)
                        ws.send_json({"ev": "keyed", "tot": _cfg_get("tot_sec")} if ok else {"ev": "denied", "why": why})
                    elif msg.get("op") == "unkey":
                        TALKER.release(ws)
        except (EOFError, OSError, socket.timeout, ValueError, struct.error):
            pass
        finally:
            stop.set()
            TALKER.drop(ws)
            ws.send(8, b"")
            ws.closed = True

    def do_POST(self):
        if self._wan_refused():
            return
        path = urllib.parse.urlsplit(self.path).path
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            self.close_connection = True
            self._json(403, {"ok": False, "error": "Missing X-Requested-With header."})
            return
        body = self._read_json()
        if body is None:
            self.close_connection = True
            self._json(400, {"ok": False, "error": "Bad JSON body."})
            return
        ip = self._ip()
        if path == "/api/login":
            wan = self._wan()
            if wan and not self._secure():
                self._json(403, {"ok": False, "error": "Log in from the internet only on the https:// page."})
                return
            wait = _auth_lockout_remaining(ip, wan)
            if wait > 0:
                self._json(429, {"ok": False, "error": f"Too many attempts. Try again in {int(wait) + 1} s."})
                return
            where = " (internet)" if wan else ""
            if _verify_root_password(str(body.get("password", ""))):
                _record_auth_success(ip)
                token = _issue_session()
                log_event(f"Login from {ip}{where}", "warn" if wan else "ok")
                self._json(200, {"ok": True}, {"Set-Cookie": self._cookie(token, _SESSION_TTL_SEC)})
            else:
                _record_auth_failure(ip, wan)
                log_event(f"Failed login from {ip}{where}", "warn")
                self._json(401, {"ok": False, "error": "Wrong password."})
            return
        if path == "/api/logout":
            _revoke_session(self._token())
            self._json(200, {"ok": True}, {"Set-Cookie": self._cookie("", 0)})
            return
        if not self._authed():
            self._json(401, {"ok": False, "error": "Log in first."})
            return
        action = _POST_ACTIONS.get(path)
        try:
            if action is None:
                self._json(404, {"ok": False, "error": "Not found."})
                return
            run, errors = action
            try:
                result = run(body)
            except errors as exc:
                result = {"ok": False, "error": str(exc)}
            self._json(200, result)
        except (BrokenPipeError, ConnectionResetError):
            pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32
    ssl_ctx = None

    def finish_request(self, request, client_address):
        if self.ssl_ctx is None:
            self.RequestHandlerClass(request, client_address, self)
            return
        try:
            request.settimeout(10)
            first = request.recv(1, socket.MSG_PEEK)
        except OSError:
            return
        if not first:
            return
        if first[0] != 0x16:
            plain_redirect(request)
            return
        try:
            tls = self.ssl_ctx.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return
        try:
            tls.settimeout(None)
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, socket.timeout, ssl.SSLError)):
            return
        log_event(f"Request error from {client_address[0] if client_address else '?'}: {exc}", "warn")


def run_server():
    global _TLS_NOTE
    migrate_legacy()
    load_config()
    port = _cfg_get("port")
    try:
        httpd = Server(("0.0.0.0", port), Handler)
    except OSError as exc:
        log_event(f"Cannot listen on port {port}: {exc}", "err")
        return 1
    if _cfg_get("https"):
        if ensure_tls_cert():
            try:
                httpd.ssl_ctx = make_ssl_context()
            except (ssl.SSLError, OSError) as exc:
                log_event(f"HTTPS certificate could not be loaded ({exc}); making a new one", "err")
                if _set_aside_tls() and ensure_tls_cert():
                    try:
                        httpd.ssl_ctx = make_ssl_context()
                    except (ssl.SSLError, OSError) as exc2:
                        log_event(f"The new HTTPS certificate could not be loaded either ({exc2}); serving plain HTTP", "err")
                else:
                    log_event("No new HTTPS certificate; serving plain HTTP (push-to-talk needs HTTPS)", "err")
        else:
            log_event("No HTTPS certificate; serving plain HTTP (push-to-talk needs HTTPS)", "err")
        if httpd.ssl_ctx is None:
            _TLS_NOTE = ("HTTPS is on in Setup but could not start, so this page is not encrypted and the password "
                         "is sent in plain text. See the Node Talker log.")
    threading.Thread(target=HUB.pump_loop, name="pump", daemon=True).start()
    threading.Thread(target=AMP_LINK.run, name="amp-link", daemon=True).start()
    threading.Thread(target=TALKER.pacer_loop, name="tx-pacer", daemon=True).start()
    threading.Thread(target=_sd_watchdog_loop, args=(port, httpd.ssl_ctx is not None), name="watchdog", daemon=True).start()
    scheme = "https" if httpd.ssl_ctx is not None else "http"
    t = amp_target()
    log_event(f"{APP_NAME} v{VERSION} on {scheme} port {port}; AMP node {t['node'] or '(not set)'} on "
              f"{t['host']}:{t['iax_port']} (IAX) and port {t['http_port']} (web), Node Talker calls in as {t['caller']}", "ok")
    _sd_notify("READY=1")

    def _on_term(signum, frame):
        threading.Thread(target=httpd.shutdown, name="shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, _on_term)
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _sd_notify("STOPPING=1")
        if TALKER.owner is not None:
            TALKER.drop(TALKER.owner)
        AMP_LINK.stop()
        httpd.server_close()
    return 0


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


def _systemctl(*args, timeout=120):
    try:
        return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["systemctl", *args], 1, "", f"systemctl {' '.join(args)} timed out after {timeout} s")
    except OSError as exc:
        return subprocess.CompletedProcess(["systemctl", *args], 1, "", f"systemctl {' '.join(args)}: {exc}")


LEGACY_DATA = (("amp_nodelisten.conf", "amp_nodetalker.conf"), ("amp_nodelisten_favorites.json", "amp_nodetalker_favorites.json"),
               ("amp_nodelisten_tls", "amp_nodetalker_tls"), ("amp_nodelisten_backups", "amp_nodetalker_backups"))
LEGACY_ASIDE = ".pre-nodetalker"


def migrate_legacy(say=None):
    for old_name, new_name in LEGACY_DATA:
        old, new = os.path.join(CONFIG_DIR, old_name), os.path.join(CONFIG_DIR, new_name)
        try:
            if os.path.islink(old):
                continue
            if os.path.isdir(old):
                if not os.path.lexists(new):
                    os.rename(old, new)
                    if say:
                        say(f"  [+] Moved {old} -> {new}")
                else:
                    continue
            elif os.path.isfile(old):
                if os.path.lexists(new) and os.path.getmtime(old) <= os.path.getmtime(new):
                    os.replace(old, old + LEGACY_ASIDE)
                    if say:
                        say(f"  [i] Kept {new}; the older {old} is now {old + LEGACY_ASIDE}")
                else:
                    os.replace(old, new)
                    if say:
                        say(f"  [+] Moved {old} -> {new}")
            if not os.path.lexists(old) and os.path.lexists(new):
                os.symlink(new_name, old)
        except OSError as exc:
            msg = f"Could not move {old} to {new}: {exc}"
            if say:
                say(f"  [!] {msg}")
            else:
                log_event(msg, "warn")


def _replace_link(path, target):
    tmp = f"{path}.{secrets.token_hex(4)}.tmp"
    os.symlink(target, tmp)
    os.replace(tmp, path)


def _legacy_unit_real():
    return os.path.isfile(LEGACY_SERVICE_PATH) and not os.path.islink(LEGACY_SERVICE_PATH)


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


def install_service():
    if os.geteuid() != 0:
        print("Error: installing needs root. Run with sudo.")
        sys.exit(1)
    current = os.path.realpath(__file__)
    print(f"Installing {APP_NAME} v{VERSION}...")
    os.makedirs(INSTALL_DIR, mode=0o755, exist_ok=True)
    os.chmod(INSTALL_DIR, 0o755)
    dest = os.path.join(INSTALL_DIR, os.path.basename(current))
    if current != dest:
        tmp = f"{dest}.{secrets.token_hex(4)}.tmp"
        shutil.copy2(current, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        print(f"  [+] Copied {os.path.basename(current)} -> {dest}")
    os.chmod(dest, 0o755)
    _replace_link(INSTALL_BIN_PATH, dest)
    print(f"  [+] Symlinked {INSTALL_BIN_PATH} -> {dest}")
    _write_launcher()
    migrate_legacy(print)
    if not os.path.exists(CONFIG_PATH):
        save_config(dict(DEFAULT_CONFIG))
        print(f"  [+] Wrote {CONFIG_PATH}")
    load_config()
    save_config(dict(_config))
    legacy = _legacy_unit_real()
    aside = LEGACY_SERVICE_PATH + LEGACY_ASIDE
    if legacy:
        _systemctl("disable", "--now", LEGACY_SERVICE)
        os.replace(LEGACY_SERVICE_PATH, aside)
        print(f"  [-] Stopped Node Listen for AMP ({LEGACY_SERVICE}); its unit is kept as {aside} until {SERVICE_NAME} runs")
    _atomic_write(SYSTEMD_SERVICE_PATH, SYSTEMD_SERVICE_CONTENT, 0o644)
    print(f"  [+] Wrote {SYSTEMD_SERVICE_PATH}")
    mark, msg = open_firewall_port(_cfg_get("port"))
    print(f"  [{mark}] {msg}")
    
    for args in (("daemon-reload",), ("enable", SERVICE_NAME)):
        r = _systemctl(*args)
        if r.returncode != 0:
            print(f"  [!] systemctl {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    r = _systemctl("restart", SERVICE_NAME)
    if r.returncode != 0:
        print(f"  [!] systemctl restart failed: {(r.stderr or r.stdout).strip()}")
        if legacy:
            _systemctl("disable", SERVICE_NAME)
            _remove_quiet(SYSTEMD_SERVICE_PATH)
            os.replace(aside, LEGACY_SERVICE_PATH)
            _systemctl("daemon-reload")
            r2 = _systemctl("enable", "--now", LEGACY_SERVICE)
            print(f"  [!] Put Node Listen for AMP back ({LEGACY_SERVICE}" + (" running)" if r2.returncode == 0 else ", but it did not start)"))
        else:
            print(f"      The previous version (if any) is still in {INSTALL_DIR}")
        sys.exit(1)
    print(f"  [+] {SERVICE_NAME} enabled and started (also answers to {LEGACY_SERVICE})")
    if not os.path.isfile(LEGACY_BIN_PATH) or os.path.islink(LEGACY_BIN_PATH):
        _replace_link(LEGACY_BIN_PATH, INSTALL_BIN_PATH)
    if legacy:
        _remove_quiet(aside)
    if os.path.isdir(LEGACY_INSTALL_DIR) and not os.path.islink(LEGACY_INSTALL_DIR):
        shutil.rmtree(LEGACY_INSTALL_DIR, ignore_errors=True)
        print(f"  [-] Removed {LEGACY_INSTALL_DIR}")
    for name in os.listdir(INSTALL_DIR):
        old = os.path.join(INSTALL_DIR, name)
        if old != dest and name.endswith(".py") and os.path.isfile(old) and not os.path.islink(old):
            os.remove(old)
            print(f"  [-] Removed the previous version {old}")
    info = amp_info(max_age=0)
    auth = amp_auth_state(info)
    if not info["running"]:
        print("  [i] amp-server is not running; Node Talker links to it when it starts.")
    elif auth["ours"]:
        print(f"  [i] AMP node {info['node'] or '(not set)'}: Node Talker's login is already in {auth['path']}")
    else:
        print(f"  [i] AMP node {info['node'] or '(not set)'}: Node Talker's login is not in {auth['path']} yet")
    print(f"Open http://<pi-address>:{_cfg_get('port')} , log in as {auth_account()}, then Setup tab, AMP link: Set up for me.")


def uninstall_service():
    if os.geteuid() != 0:
        print("Error: uninstalling needs root. Run with sudo.")
        sys.exit(1)
    print(f"Removing {APP_NAME}...")
    load_config()
    _systemctl("disable", "--now", SERVICE_NAME)
    legacy_ours = os.path.islink(LEGACY_BIN_PATH) and \
        os.path.realpath(LEGACY_BIN_PATH).startswith((os.path.realpath(INSTALL_DIR) + os.sep, os.path.realpath(INSTALL_BIN_PATH)))
    gone = [SYSTEMD_SERVICE_PATH, INSTALL_BIN_PATH] + ([LEGACY_BIN_PATH] if legacy_ours else [])
    if os.path.islink(LEGACY_SERVICE_PATH) and os.path.basename(os.readlink(LEGACY_SERVICE_PATH)) == SERVICE_NAME:
        gone.append(LEGACY_SERVICE_PATH)
    for p in gone:
        if os.path.lexists(p):
            os.remove(p)
            print(f"  [-] Removed {p}")
    _systemctl("daemon-reload")
    if os.path.isdir(INSTALL_DIR):
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        print(f"  [-] Removed {INSTALL_DIR}")
    _remove_launcher_if_unused()
    print(f"  Settings kept in {CONFIG_PATH} and {BACKUP_DIR}")
    auth = amp_auth_state()
    if auth["ours"]:
        print(f"  Node Talker's login ({_cfg_get('amp_user')}) stays in AMP's {auth['path']}; remove that line by hand if you like.")
    cp = configparser.ConfigParser()
    cp.read(CONFIG_PATH)
    sec = CONFIG_SECTION if cp.has_section(CONFIG_SECTION) else LEGACY_SECTION
    mark, msg = close_firewall_port(cp.getint(sec, "port", fallback=DEFAULT_CONFIG["port"]))
    print(f"  [{mark}] {msg}")


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{VERSION}: an AMP node's audio in the browser")
    parser.add_argument("--install", action="store_true", help="Install as a systemd service & start")
    parser.add_argument("--uninstall", action="store_true", help="Stop & remove the systemd service")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION} ({DATE_STR})")
    args = parser.parse_args()
    if args.install:
        install_service()
        return 0
    if args.uninstall:
        uninstall_service()
        return 0
    return run_server()


if __name__ == "__main__":
    sys.exit(main())
