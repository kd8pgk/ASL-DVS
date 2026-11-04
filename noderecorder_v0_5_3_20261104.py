#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import array
import configparser
import glob
import hmac
import http.client
import ipaddress
import json
import math
import operator
import os
import queue
import re
import secrets
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


VERSION = "0.5.3"
DATE_STR = "2026-11-04"
APP_NAME = "Node Recorder"
PORT = 8995

INSTALL_BIN_PATH = "/usr/local/bin/noderecorder.py"
INSTALL_DIR = "/usr/local/lib/asl_dvs/noderecorder"
SERVICE_NAME = "noderecorder.service"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/noderecorder.service"
_SYSTEMD_UNIT_DIR = "/etc/systemd/system"

CONFIG_DIR = os.environ.get("NODERECORDER_CONFIG_DIR", "/etc/asl_dvs/noderecorder")
CONFIG_PATH = os.path.join(CONFIG_DIR, "noderecorder.conf")
CONFIG_SECTION = "noderecorder"
BACKUP_DIR = os.path.join(CONFIG_DIR, "noderecorder_backups")
BACKUP_KEEP = 10
RESTORE_PATH = os.path.join(CONFIG_DIR, "noderecorder_restore.json")
RESTORE_MAX_AGE_SEC = 1800
RPT_CONF = os.environ.get("NODERECORDER_RPT_CONF", "/etc/asterisk/rpt.conf")

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


def service_content(run_path):
    return f"""[Unit]
Description=Node Recorder: ASL node audio in the browser
After=network.target asterisk.service

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 {_LAUNCHER_PATH} {run_path}
Restart=always
RestartSec=3s
TimeoutStartSec=60
WatchdogSec=60s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
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
    "node": "",
    "max_listeners": 3,
    "public_listen": False,
    "https": True,
    "tune_enabled": False,
    "rx_gain_db": 0,
    "jitter_ms": 250,
    "allow_wan": False,
    "rx_hpf": True,
    "rx_agc": True,
    "rx_gate": 1,
    "schedule_dry_run": False,
    "record_path": "",
    "record_max_mb": 4096,
    "record_convert": True,
    "record_encoder": "lame",
    "record_kbps": 32,
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


_norm_listeners = _norm_int(1, 10, "max_listeners must be 1-10")
_norm_jitter = _norm_int(100, 1500, "jitter_ms must be 100-1500")


def _norm_node(value):
    v = str(value).strip()
    if v and not re.fullmatch(r"\d{1,7}", v):
        raise ValueError("node must be a node number")
    return v


def _norm_dirpath(value):
    v = str(value).strip()
    if not v:
        return ""
    if len(v) > 200 or "%" in v or _CALL_TRIM.search(v) or not v.startswith("/"):
        raise ValueError("the recordings folder must be a full path starting with /")
    v = os.path.normpath(v)
    if v == "/" or v.startswith(("/proc", "/sys", "/dev", "/boot", "/etc/asterisk")):
        raise ValueError("pick a folder on a drive, not a system folder")
    return v


MP3_KBPS = (24, 32, 48, 64)


def _norm_kbps(value):
    try:
        v = int(str(value).strip())
    except ValueError:
        v = 0
    if v not in MP3_KBPS:
        raise ValueError("the quality must be " + ", ".join(str(k) for k in MP3_KBPS) + " kbps")
    return v


def _norm_encoder(value):
    v = str(value).strip().lower()
    if v not in ("lame", "sox", "shine", "opus", "flac"):
        raise ValueError("the encoder must be lame, sox, shine, opus or flac")
    return v


def _norm_gain(value):
    try:
        v = int(round(float(str(value).strip())))
    except OverflowError:
        raise ValueError("gains must be -12 to +12 dB")
    if not -12 <= v <= 12:
        raise ValueError("gains must be -12 to +12 dB")
    return v


_NORMALIZERS = {
    "node": _norm_node,
    "max_listeners": _norm_listeners,
    "public_listen": _parse_bool,
    "https": _parse_bool,
    "tune_enabled": _parse_bool,
    "rx_gain_db": _norm_gain,
    "jitter_ms": _norm_jitter,
    "allow_wan": _parse_bool,
    "rx_hpf": _parse_bool,
    "rx_agc": _parse_bool,
    "rx_gate": _norm_int(0, 2, "rx_gate must be 0, 1 or 2"),
    "schedule_dry_run": _parse_bool,
    "record_path": _norm_dirpath,
    "record_max_mb": _norm_int(100, 2000000, "record_max_mb must be 100-2000000"),
    "record_convert": _parse_bool,
    "record_encoder": _norm_encoder,
    "record_kbps": _norm_kbps,
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
    sec = CONFIG_SECTION
    if cp.has_section(sec):
        for key, norm in _NORMALIZERS.items():
            if cp.has_option(sec, key):
                try:
                    cfg[key] = norm(cp.get(sec, key))
                except ValueError as exc:
                    log_event(f"Config: bad {key} ({exc}); using {DEFAULT_CONFIG[key]}", "warn")
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
    lines = [f"[{CONFIG_SECTION}]"] + body
    _atomic_write(CONFIG_PATH, "\n".join(lines) + "\n", 0o644)


def config_update(body):
    with _config_lock:
        old = dict(_config)
    cfg = dict(old)
    errors = []
    for key, norm in _NORMALIZERS.items():
        if key in body:
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
    restart = cfg["https"] != old["https"]
    msg = "Saved."
    if restart:
        msg += " Node Recorder restarts to use the new setting."
        if not _schedule_restart():
            msg += " (Restart it by hand: systemctl restart noderecorder)"
    log_event(f"Config saved: {json.dumps({k: cfg[k] for k in DEFAULT_CONFIG})}", "ok")
    return {"ok": True, "message": msg.strip(), "restart": restart}


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
    import importlib.util
    if importlib.util.find_spec("pam") is not None:
        return True
    stored = _read_shadow_hash(_AUTH_ACCOUNT)
    return bool(stored) and stored[0] not in ("!", "*")


_SESSION_COOKIE_NAME = "noderecorder_session"
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
            pump_ok = time.monotonic() - HUB.pump_beat < 5.0
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
                          "--unit=noderecorder-selfrestart", "systemctl", "restart", SERVICE_NAME],
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


_active_gain = {"target": None, "rx_gain_db": None, "tx_gain_db": None}


def tune_value(key):
    if key in ("rx_gain_db", "tx_gain_db"):
        ov = _active_gain.get(key)
        if ov is not None:
            return ov
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
    if not a:
        return frame
    if max(max(a), -min(a)) * g <= GAIN_KNEE:
        return array.array("h", map(round, map(g.__mul__, a))).tobytes()
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


def fade_in(frame):
    a = _samples(frame)
    n = len(a)
    for i in range(n):
        a[i] = int(round(a[i] * (i + 1) / n))
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
GATE_PREROLL = 2


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
        self.r2 = 1.0
        self.out_keep = False

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
        self.r2 = _dot(ys[2:], ys[:-2]) / ss if ss > 0 else 1.0
        db = 10.0 * math.log10(max(ss / n / 1073741824.0, 1e-30)) if ss > 0 else -120.0
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


        flat = abs(r1) < r["r1"] and abs(self.r2) < r["r1"]
        if db > r["noise_db"] and flat:
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
        was, self.out_keep = self.out_keep, keep
        if keep and not was:
            pcm = fade_in(pcm)
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
        was_open = self.open
        keep, hit = self._gate(db, r1, gate)
        if hit:
            for i in range(len(self.delay)):
                self.delay[i] = (self.delay[i][0], False)
        elif keep and not was_open:
            for i in range(max(0, len(self.delay) - GATE_PREROLL), len(self.delay)):
                self.delay[i] = (self.delay[i][0], True)
        return self._out(pcm, keep, t0)

    def idle_tick(self):
        self.idle += 1
        if self.idle > 150 and (self.delay or self.open):
            self.delay.clear()
            self.open = False
            self.tail = False
            self.out_keep = False

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


def udp_socket(port=None):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if port is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
        except OSError:
            sock.close()
            raise
    return sock


class _Listener:
    __slots__ = ("q", "closed", "ip", "since", "pcm")

    def __init__(self, ip, pcm=False):
        self.q = deque(maxlen=LISTENER_QUEUE_MAX)
        self.closed = False
        self.ip = ip
        self.since = time.time()
        self.pcm = pcm


AMI_CONF = os.environ.get("NODERECORDER_AMI_CONF", "/etc/asterisk/manager.conf")
AMI_HOST = "127.0.0.1"
AMI_PORT = 5038
AMI_POLL_SEC = 0.25
AMI_RETRY_SEC = 10.0
AMI_IDLE_SEC = 20.0
AMI_REPLY_SEC = 5.0
AMI_MAX_BYTES = 1000000


class AmiRefused(Exception):
    pass


def ami_credentials(conf_path, user="", secret=""):
    if user and secret:
        return user, secret
    try:
        with open(conf_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return "", ""
    name = ""
    word = ""
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and "]" in line:
            if name and word and section.lower() != "general":
                return name, word
            section = line[1:line.index("]")].strip()
            name = section
            word = ""
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            if k.strip().lower() == "secret":
                word = v.strip()
    if name and word and section.lower() != "general":
        return name, word
    return "", ""


def _ami_msg(**fields):
    return ("".join(f"{k}: {v}\r\n" for k, v in fields.items()) + "\r\n").encode("utf-8")


def _ami_read(fh):
    lines = []
    size = 0
    while True:
        raw = fh.readline(65536)
        if not raw:
            raise OSError("AMI closed the connection")
        size += len(raw)
        if size > AMI_MAX_BYTES:
            raise OSError("AMI sent too much without finishing a reply")
        ln = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not ln:
            if lines:
                return lines
            continue
        lines.append(ln)


def _ami_read_for(fh, action_id):
    end = time.monotonic() + AMI_REPLY_SEC
    while True:
        lines = _ami_read(fh)
        if f"ActionID: {action_id}" in lines:
            return lines
        if time.monotonic() > end:
            raise OSError("AMI did not answer in time")


def _ami_parse_keyed(lines):
    rx, links = False, []
    for ln in lines:
        if ln.startswith("Var: RPT_RXKEYED="):
            rx = ln.split("=", 1)[1].strip() == "1"
        elif ln.startswith("Var: RPT_ALINKS="):
            for item in ln.split("=", 1)[1].strip().split(",")[1:]:
                item = item.strip()
                if len(item) >= 3 and item[-1] == "K" and item[:-2] != REC_NODE:
                    links.append(item[:-2])
    return rx or bool(links), ("local" if rx else (links[0] if links else ""))


class KeyedWatch:
    def __init__(self):
        self.lock = threading.Lock()
        self.wake_event = threading.Event()
        self.wake_at = -1e9
        self.ok = False
        self.error = "not started"
        self.refused = None
        self.keyed = False
        self.fresh = False
        self.partial = False
        self.who = ""
        self.key_at = 0.0
        self.unkey_at = -1e9

    def state(self):
        with self.lock:
            return {"ok": self.ok, "error": "" if self.ok else self.error, "keyed": self.keyed,
                    "who": self.who if self.keyed else ""}

    def wake(self, now):
        self.wake_at = now
        self.wake_event.set()

    def _wanted(self, now):
        return self.keyed or now - self.wake_at < AMI_IDLE_SEC

    def update(self, keyed, who, now):
        with self.lock:
            first, self.fresh = self.fresh, False
            if keyed and not self.keyed:
                self.keyed, self.who, self.key_at = True, who, now
                self.partial = first
            elif not keyed and self.keyed:
                self.keyed, self.unkey_at = False, now
                self.partial = False

    def _down(self, error):
        with self.lock:
            was = self.ok
            self.ok, self.error, self.keyed, self.partial = False, error, False, False
        if was:
            log_event(f"Key-up state from Asterisk lost ({error}); activity uses audio again", "warn")

    def _session(self, node, user, secret):
        sock = socket.create_connection((AMI_HOST, AMI_PORT), timeout=5)
        try:
            fh = sock.makefile("rb")
            if not fh.readline(256).startswith(b"Asterisk Call Manager"):
                raise ValueError("that port is not the Asterisk manager")
            sock.sendall(_ami_msg(Action="Login", Username=user, Secret=secret, Events="off", ActionID="ntlogin"))
            reply = _ami_read_for(fh, "ntlogin")
            if "Response: Success" not in reply:
                if "Response: Error" in reply:
                    raise AmiRefused("Asterisk refused the AMI login")
                raise ValueError("the manager gave no answer to the login")
            with self.lock:
                self.fresh = True
            n = 0
            while True:
                n += 1
                if n % 20 == 0 and node != main_node():
                    return
                aid = f"nt{n}"
                sock.sendall(_ami_msg(Action="RptStatus", Command="XStat", Node=node, ActionID=aid))
                lines = _ami_read_for(fh, aid)
                if not any(ln.startswith("Var: RPT_RXKEYED=") for ln in lines):
                    raise ValueError(f"XStat for node {node} did not report RPT_RXKEYED")
                keyed, who = _ami_parse_keyed(lines)
                with self.lock:
                    first = not self.ok
                    self.ok, self.error = True, ""
                if first:
                    log_event(f"Key-up state from Asterisk (AMI {AMI_HOST}:{AMI_PORT}): activity follows key-ups", "ok")
                self.update(keyed, who, time.monotonic())
                if not self._wanted(time.monotonic()):
                    return
                time.sleep(AMI_POLL_SEC)
        finally:
            sock.close()

    def loop(self):
        while True:
            if self.ok and not self._wanted(time.monotonic()):
                self.wake_event.clear()
                if not self._wanted(time.monotonic()):
                    self.wake_event.wait()
                continue
            node = main_node()
            user, secret = ami_credentials(AMI_CONF)
            if not user or not secret:
                self._down(f"no AMI login found in {AMI_CONF}")
            elif self.refused == (user, secret):
                self._down(f"Asterisk refused the AMI login for {user} in {AMI_CONF}")
            else:
                try:
                    self._session(node, user, secret)
                    continue
                except AmiRefused as exc:
                    self.refused = (user, secret)
                    self._down(f"{exc} for {user} in {AMI_CONF}")
                except (OSError, ValueError) as exc:
                    self._down(f"AMI {AMI_HOST}:{AMI_PORT}: {exc}")
            time.sleep(AMI_RETRY_SEC)

KEYED = KeyedWatch()


class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.inbuf = bytearray()
        self.frames = deque()
        self.listeners = set()
        self.packets = 0
        self.dropped = 0
        self.dropped_over = 0
        self.dropped_trim = 0
        self.last_rx = 0.0
        self.level_db = -120.0
        self.peak_db = -120.0
        self.last_active = 0.0
        self.usrp_keyed = False
        self.recorder = None
        self.pump_beat = time.monotonic()
        self.rate_window = deque(maxlen=60)
        self.udp_errors = {}

    def feed(self, data):
        now = time.monotonic()
        with self.lock:
            self.packets += 1
            self.last_rx = now
            self.inbuf += data
            while len(self.inbuf) >= FRAME_BYTES:
                self.frames.append(bytes(self.inbuf[:FRAME_BYTES]))
                del self.inbuf[:FRAME_BYTES]
            while len(self.frames) > IN_QUEUE_MAX:
                self.frames.popleft()
                self.dropped += 1
                self.dropped_over += 1

    def note_usrp(self, keyed):
        self.usrp_keyed = keyed

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
        now = time.monotonic()
        heard = self.usrp_keyed or now - self.last_active < ACTIVE_HOLD_SEC
        if KEYED.ok:
            return heard or KEYED.keyed or now - KEYED.unkey_at < ACTIVE_HOLD_SEC
        return heard

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
                self.dropped_trim += 1
            have_listeners = bool(self.listeners)
        if frame is not None:
            db = frame_db(frame)
            self.level_db = db
            self.peak_db = max(db, self.peak_db - 1.0)
            if db > ACTIVE_DB:
                KEYED.wake(now)
                self.last_active = now
        else:
            self.level_db = -120.0
            self.peak_db = max(-120.0, self.peak_db - 1.0)
        rec = self.recorder
        if have_listeners or rec is not None:
            if frame is not None:
                pcm = RXC.process(frame, tune_value("rx_gain_db"), db)
            else:
                RXC.idle_tick()
                pcm = PCM_SILENCE
            if have_listeners:
                self._deliver(pcm)
            if rec is not None:
                rec.feed(pcm)
        self.pump_beat = now

    def _deliver(self, pcm):
        with self.cond:
            enc = None
            for lst in self.listeners:
                if lst.pcm:
                    lst.q.append(pcm)
                else:
                    if enc is None:
                        enc = ULAW_SILENCE if pcm == PCM_SILENCE else ulaw_encode(pcm)
                    lst.q.append(enc)
            if self.listeners:
                self.cond.notify_all()

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
            "receiving": self.last_rx > 0 and now - self.last_rx < 3.0,
            "last_rx_age": round(now - self.last_rx, 1) if self.last_rx else None,
            "packets": self.packets,
            "packets_per_sec": self.rate_window[-1] if self.rate_window else 0,
            "dropped": self.dropped,
            "dropped_over": self.dropped_over,
            "dropped_trim": self.dropped_trim,
            "level_db": round(self.level_db, 1),
            "peak_db": round(self.peak_db, 1),
            "audio_active": self.audio_active(),
            "listeners": n,
            "listener_list": listeners,
            "max_listeners": _cfg_get("max_listeners"),
            "udp_error": "; ".join(self.udp_errors.values()),
            "rx_load_pct": RXC.load_pct,
        }


HUB = Hub()


_STANZA_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:\(([^)]*)\))?")


def _squash(text):
    return text.replace(" ", "")


def _is_node_name(name):
    return re.fullmatch(r"\d+", name) is not None


def _find_stanza(stanzas, name):
    return next((s for s in stanzas if s["name"] == name), None)


def _strip_comment(value):
    return value.split(";", 1)[0].strip()


def parse_rpt(text):
    lines = text.split("\n")
    stanzas = []
    cur = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith(";"):
            continue
        m = _STANZA_RE.match(line)
        if m:
            cur = {"name": m.group(1).strip(), "templates": [t.strip() for t in (m.group(2) or "").split(",") if t.strip()],
                   "header": i}
            stanzas.append(cur)
    return lines, stanzas


def read_rpt():
    with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
        return parse_rpt(fh.read())


def _backup_rpt():
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, "rpt.conf." + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    shutil.copy2(RPT_CONF, dest)
    olds = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("rpt.conf."))
    for f in olds[:-BACKUP_KEEP]:
        _remove_quiet(os.path.join(BACKUP_DIR, f))
    return dest


def _write_rpt(lines):
    st = os.stat(RPT_CONF)
    backup = _backup_rpt()
    _atomic_write(RPT_CONF, "\n".join(lines), like=st)
    return backup


def _write_failed(exc):
    return {"ok": False, "error": f"Could not write {RPT_CONF}: {exc}"}


ALLMON3_INI = "/etc/allmon3/allmon3.ini"


def allmon_follow(add, remove, main=""):
    try:
        with open(ALLMON3_INI, encoding="utf-8", errors="replace") as fh:
            old = fh.read()
    except OSError:
        return ""
    new, notes = allmon3_sync(old, add, remove, main or main_node() or "")
    if not notes:
        return ""
    if new != old:
        try:
            atomic_write(ALLMON3_INI, new)
        except OSError as exc:
            return f" allmon3.ini not updated: {exc}."
        log_event("; ".join(notes), "ok")
    return " " + "; ".join(notes) + ". Restart Allmon3 to see it."


def _changed(backup, message):
    return {"ok": True, "changed": True, "backup": backup, "message": f"{message} Backup: {backup}"}


_rpt_lock = threading.Lock()


def restart_asterisk():
    try:
        r = subprocess.run(["systemctl", "restart", "asterisk"], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"systemctl failed: {exc}"}
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout).strip() or f"exit {r.returncode}"}
    log_event("Asterisk restarted from Node Recorder", "ok")
    return {"ok": True, "message": "Asterisk restarted. Audio should arrive within a few seconds of the node hearing anything."}


RESET_UNITS = (("md380-emu", "md380-emu"), ("Analog_Bridge", "analog_bridge"), ("MMDVM_Bridge", "mmdvm_bridge"),
               ("USRP2M17", "usrp2m17"), ("Asterisk", "asterisk"))
RESET_DISCONNECT_SEC = 5.0
RESET_UNIT_SEC = 90
_reset_lock = threading.Lock()
_reset = {"running": False, "steps": [], "message": "", "level": "", "started": 0.0, "finished": 0.0}


def _reset_installed():
    states = service_states([u + ".service" for _l, u in RESET_UNITS])
    return [label for label, u in RESET_UNITS if states.get(u + ".service") != "missing"]


def disconnect_all_status(_body=None):
    with _reset_lock:
        d = {k: _reset[k] for k in ("running", "message", "level", "started", "finished")}
        d["steps"] = [dict(x) for x in _reset["steps"]]
    d.update(ok=True, installed=_reset_installed())
    return d


def _reset_step(i, **kw):
    with _reset_lock:
        _reset["steps"][i].update(kw)


def _reset_run():
    _reset_step(0, state="running")
    stopped = []
    _reset_step(0, state="ok", note=("stopped the " + " and the ".join(stopped)) if stopped else "nothing was running")
    _reset_step(1, state="running")
    box = {}

    def drop():
        try:
            box["r"] = tune_disconnect()
        except Exception as exc:
            box["r"] = {"ok": False, "error": str(exc)}

    t = threading.Thread(target=drop, daemon=True)
    t.start()
    t.join(RESET_DISCONNECT_SEC)
    if t.is_alive():
        _reset_step(1, state="warn", note=f"no answer within {RESET_DISCONNECT_SEC:.0f} s -- restarting anyway")
    else:
        r = box.get("r") or {}
        _reset_step(1, state="ok" if r.get("ok") else "warn",
                    note=r.get("message") or r.get("error") or ("done" if r.get("ok") else "failed -- restarting anyway"))
    if _solo["target"]:
        _solo_set()
    states = service_states([u + ".service" for _l, u in RESET_UNITS])
    done, failed, missing = [], [], []
    for i, (label, unit) in enumerate(RESET_UNITS, 2):
        if states.get(unit + ".service") == "missing":
            _reset_step(i, state="skipped", note="not installed")
            missing.append(label)
            continue
        _reset_step(i, state="running")
        r = _systemctl("restart", unit + ".service", timeout=RESET_UNIT_SEC)
        if r.returncode == 0:
            _reset_step(i, state="ok", note="restarted")
            done.append(label)
            log_event(f"Disconnect All: {label} restarted", "ok")
        else:
            why = (r.stderr or r.stdout).strip() or f"exit {r.returncode}"
            _reset_step(i, state="failed", note=why)
            failed.append(label)
            log_event(f"Disconnect All: {label} did not restart: {why}", "err")
    _lstats_invalidate()
    _links_cache["t"] = -1e9
    parts = []
    if done:
        parts.append("restarted " + ", ".join(done))
    if failed:
        parts.append("FAILED: " + ", ".join(failed))
    if missing:
        parts.append("not installed: " + ", ".join(missing))
    return "Disconnect All finished: " + ("; ".join(parts) or "nothing to restart") + ".", "err" if failed else "ok"


def _reset_bg():
    try:
        message, level = _reset_run()
    except Exception as exc:
        message, level = f"Disconnect All stopped on an error: {exc}", "err"
    log_event(message, "warn" if level == "err" else "ok")
    with _reset_lock:
        for x in _reset["steps"]:
            if x["state"] in ("pending", "running"):
                x["state"] = "failed" if x["state"] == "running" else "skipped"
        _reset.update(running=False, message=message, level=level, finished=time.time())


def disconnect_all(_body=None):
    if os.geteuid() != 0:
        return {"ok": False, "error": "root required to restart the services"}
    with _reset_lock:
        if _reset["running"]:
            return {"ok": False, "error": "Disconnect All is already running."}
        steps = [{"name": "Stop TX and tests", "state": "pending", "note": ""},
                 {"name": "Disconnect", "state": "pending", "note": ""}]
        steps += [{"name": label, "state": "pending", "note": ""} for label, _u in RESET_UNITS]
        _reset.update(running=True, steps=steps, message="", level="", started=time.time(), finished=0.0)
    log_event("Disconnect All: emergency reset requested from Node Recorder", "warn")
    threading.Thread(target=_reset_bg, daemon=True).start()
    return {"ok": True, "message": "Disconnect All started."}


def page_answers(path, port=80, timeout=0.5):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("HEAD", path)
        return conn.getresponse().status < 400
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


_links_cache = {"t": -1e9, "v": {}}


def quick_links():
    now = time.monotonic()
    if now - _links_cache["t"] < LINK_TTL_SEC:
        return _links_cache["v"]
    v = {name: page_answers(path) for name, path in WEB_PAGES}
    v["cockpit"] = port_open(COCKPIT_PORT)
    _links_cache.update(t=now, v=v)
    return v


def system_power(what):
    cmd, message = POWER_CMDS[what]
    if os.geteuid() != 0:
        return {"ok": False, "error": f"root required for {what}"}
    log_event(f"System {what} requested from Node Recorder", "warn")

    def go():
        time.sleep(1)
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log_event(f"System {what} failed: {exc}", "err")

    threading.Thread(target=go, daemon=True).start()
    return {"ok": True, "message": message}


PI_SAMPLE_SEC = 10
PI_THROTTLE_NOW = {0: "under-voltage", 1: "frequency capped", 2: "throttled", 3: "soft temperature limit"}
PI_THROTTLE_SINCE = {16: "under-voltage", 17: "frequency capped", 18: "throttled", 19: "soft temperature limit"}
_pi_lock = threading.Lock()
_pi_state = {"temp_c": None, "throttled": None, "now": [], "since_boot": []}


def pi_read_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", encoding="ascii") as fh:
            return round(int(fh.read().strip()) / 1000.0, 1)
    except (OSError, ValueError):
        return None


def pi_read_throttled():
    try:
        r = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"0x([0-9a-fA-F]+)", r.stdout or "")
    return int(m.group(1), 16) if m else None


def pi_flags(bits):
    if bits is None:
        return [], []
    now = [name for b, name in PI_THROTTLE_NOW.items() if bits & (1 << b)]
    since = [name for b, name in PI_THROTTLE_SINCE.items() if bits & (1 << b)]
    return now, since


def pi_sample():
    bits = pi_read_throttled()
    now, since = pi_flags(bits)
    temp = pi_read_temp()
    with _pi_lock:
        _pi_state.update(temp_c=temp, throttled=bits, now=now, since_boot=since)


def pi_loop():
    while True:
        try:
            pi_sample()
        except Exception:
            pass
        time.sleep(PI_SAMPLE_SEC)


def pi_snapshot():
    with _pi_lock:
        s = dict(_pi_state)
    return {"temp_c": s["temp_c"], "throttled": s["throttled"], "now": list(s["now"]), "since_boot": list(s["since_boot"])}


def build_status(full):
    st = HUB.snapshot()
    st.update({"version": VERSION, "node": _cfg_get("node"), "uptime": int(time.time() - _START_TIME),
               "jitter_ms": tune_value("jitter_ms"), "usrp_forward": True})
    if full:
        st["pi"] = pi_snapshot()
        node = main_node()
        st["node"] = node
        ok, links = rpt_links(node)
        st["links"], st["links_ok"] = links, ok
        nc = nc_running(cached=True)
        st["control"] = "nc" if nc else "solo"
        favs = fav_load()
        st["m17"] = m17_current() if nc and _has_m17(favs) else ""
        st["tuned"] = (nc_dvs_target(favs) if _has_dvs(favs) else "") if nc else solo_status(node)
        st["tuned_now"] = tuned_now(nc)
        st["link"] = live_link(links, ok, nc, favs)
        st["default_mode"] = _default_tune_mode(nc)
        st["rec_node"] = rec_node_state(node)
        st["talker"] = {"installed": talker_installed(), "active": talker_active()}
    else:
        st.pop("listener_list", None)
        st.pop("udp_error", None)
        st.pop("rx_load_pct", None)
    return st


AST_BIN = os.environ.get("NODERECORDER_ASTERISK", "asterisk")
DASH_CONF = os.environ.get("NODERECORDER_DASH_CONF", "/etc/asl_dvs/asl_dvs.conf")
FAV_PATH = os.path.join(CONFIG_DIR, "noderecorder_favorites.json")
FAV_CONF_PATH = os.path.join(CONFIG_DIR, "noderecorder_favorites.conf")
TUNED_PATH = os.path.join(CONFIG_DIR, "noderecorder_tuned.json")
FAV_MAX = 15
FAV_JSON_MAX = 10
DMR_NET_MAX = 10
DVS_MODES = ("DMR", "STFU", "YSF", "P25", "NXDN", "DSTAR")
FAV_MODES = ("ASL", "EchoLink") + DVS_MODES + ("M17",)
DVS_SEARCH_PATHS = tuple(p for p in (os.environ.get("NODERECORDER_DVSWITCH", ""), "/opt/MMDVM_Bridge/dvswitch.sh",
                                     "/usr/local/sbin/dvswitch.sh", "/var/lib/dvswitch/dvswitch.sh") if p)
DVS_TIMEOUT = {"mode": 40, "tune": 40}
DVS_OTHER_TIMEOUT = 10
DVS_SETTLE_SEC = 0.4
DVS_DISCONNECT = "disconnect"
DSTAR_UNLINK = "       U"
DSTAR_BASE_LEN = 6
GATEWAY_SERVICES = {"YSF": "ysfgateway.service", "P25": "p25gateway.service", "NXDN": "nxdngateway.service",
                    "DSTAR": "ircddbgatewayd.service", "STFU": "stfu.service"}
GATEWAY_WAIT_SEC = 5.0
AB_INI = os.environ.get("NODERECORDER_AB_INI", "/opt/Analog_Bridge/Analog_Bridge.ini")
M17_INI = os.environ.get("NODERECORDER_M17_INI", "/opt/USRP2M17/USRP2M17.ini")
M17_HOSTS = os.environ.get("NODERECORDER_M17_HOSTS", "/var/lib/mmdvm/M17Hosts.json")
M17_SERVICE = "usrp2m17"
M17_NET_PORTS = (17010, 17000)
M17_USRP_PORTS = (32008, 34008)
M17_GAIN_DB = 3
DEFAULT_BRIDGES = ("1999", "1917")
BLANK_NAME, BLANK_ADDR = "blank", "000000"
_DMR_ADDR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}:\d{1,5}$")
_CALLSIGN_RE = re.compile(r"^[A-Z0-9][A-Z0-9/-]{2,9}$")
TLS_DIR = os.path.join(CONFIG_DIR, "noderecorder_tls")
TLS_CERT = os.path.join(TLS_DIR, "cert.pem")
TLS_KEY = os.path.join(TLS_DIR, "key.pem")
REC_NODE = "1921"
REC_USRP_OUT = 32018
REC_USRP_IN = 34018
TALKER_NOTE = "; nodetalker: transmit node for Node Talker (remove it from the TX card)"
TALKER_NOTES = (TALKER_NOTE, "; nodelisten: transmit node for the Node Listen page (remove it from that page)")
REC_NOTE = "; noderecorder: receive node for Node Recorder (remove it from the Node Recorder page)"
TALKER_SERVICE = "nodetalker.service"
TALKER_UNIT = os.environ.get("NODERECORDER_TALKER_UNIT", "/etc/systemd/system/nodetalker.service")
FWD_PORT = 9995
IAX_CONF = os.environ.get("NODERECORDER_IAX_CONF", "/etc/asterisk/iax.conf")
LOCAL_KEY_PATH = os.environ.get("NODERECORDER_LOCAL_KEY", "/etc/asl_dvs/local_api.key")
SYSMON_PORT = 9999
INSTMON_PORT = 8990
COCKPIT_PORT = 9090
WEB_PAGES = (("allmon3", "/allmon3/"), ("dvswitch", "/dvswitch/"))
LINK_TTL_SEC = 30.0
POWER_CMDS = {"reboot": (["reboot"], "Rebooting…"), "shutdown": (["shutdown", "-h", "now"], "Shutting down…")}
_REC_NODES_LINE_RE = re.compile(r"^\s*" + REC_NODE + r"\s*=\s*radio@127\.0\.0\.1(?::\d+)?/" + REC_NODE + r",NONE\s*$")
USRP_HEADER = struct.Struct(">4s7i")
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
_CALL_TRIM = re.compile(r"[\x00-\x1f\x7f]")
_M17_REF_RE = re.compile(r"[A-Z0-9][A-Z0-9-]{0,15}")
M17_STATUS_TTL = 5.0
LINK_WAIT_SEC = 15


def iax_bindport():
    base = os.path.dirname(IAX_CONF)

    def scan(path, depth, sec):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return None
        found = None
        for raw in text.splitlines():
            ln = raw.split(";", 1)[0].strip()
            m = re.match(r'^#(?:try)?include\s+"?([^"\s]+)"?', ln)
            if m and depth < 2:
                pat = m.group(1) if m.group(1).startswith("/") else os.path.join(base, m.group(1))
                for inc in sorted(glob.glob(pat)):
                    r = scan(inc, depth + 1, sec)
                    if r:
                        found = r
                continue
            m = re.match(r"^\[([^\]]+)\]", ln)
            if m:
                sec = m.group(1).strip().lower()
                continue
            if sec == "general":
                m = re.match(r"^bindport\s*=>?\s*(\d{1,5})\b", ln, re.I)
                if m:
                    found = m.group(1)
        return found

    return scan(IAX_CONF, 0, "") or "4569"


def rec_nodes_line():
    port = iax_bindport()
    host = "127.0.0.1" if port == "4569" else f"127.0.0.1:{port}"
    return f"{REC_NODE} = radio@{host}/{REC_NODE},NONE"


def ast_cli(command, timeout=8):
    try:
        r = subprocess.run([AST_BIN, "-rx", command], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, out


def ilink(node, op, peer):
    r = ast_cli(f"rpt cmd {node} ilink {op} {peer}")
    _lstats_invalidate()
    return r


_lstats_cache = {"t": 0.0, "node": "", "ok": False, "links": []}
_lstats_lock = threading.Lock()


def rpt_links(node, max_age=2.0):
    if not node:
        return False, []
    with _lstats_lock:
        c = _lstats_cache
        if c["node"] == node and time.monotonic() - c["t"] < max_age:
            return c["ok"], list(c["links"])
    ok, out = ast_cli(f"rpt lstats {node}", timeout=6)
    links = []
    if ok:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0].isdigit():
                links.append({"node": parts[0], "dir": parts[3],
                              "time": parts[4] if len(parts) > 4 else "",
                              "state": parts[5] if len(parts) > 5 else ""})
    with _lstats_lock:
        _lstats_cache.update(t=time.monotonic(), node=node, ok=ok, links=links)
    return ok, links


def _lstats_invalidate():
    with _lstats_lock:
        _lstats_cache["t"] = 0.0


MODE_LABEL = {"DSTAR": "D-STAR"}


def _file_key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _label(value, fallback):
    s = _CALL_TRIM.sub(" ", str(value or "")).replace("|", "/").strip().lstrip("#;").strip()[:40]
    return s or fallback


def _server_key(name):
    return name.upper().replace(" ", "_").replace("+", "PLUS")


def _mode_of(value):
    m = str(value or "").strip().upper().replace("-", "")
    if m.startswith("ECHO"):
        return "EchoLink"
    if m in ("ASL", "M17") or m in DVS_MODES:
        return m
    raise ValueError(f"Unknown mode {str(value)[:20]!r}")


def _mode_safe(f):
    try:
        return _mode_of(f.get("mode", "ASL") or "ASL")
    except (ValueError, AttributeError):
        return None


def _clean_tg(value, mode):
    tg = str(value or "").strip()
    if not tg:
        raise ValueError(f"{MODE_LABEL.get(mode, mode)}: the talkgroup or address is empty")
    if len(tg) > 64 or _CALL_TRIM.search(tg) or "|" in tg:
        raise ValueError(f"{MODE_LABEL.get(mode, mode)} {tg[:20]}: up to 64 characters, with no | or control characters")
    return tg


def dstar_tune_str(value):
    tg = str(value or "").strip().upper()
    if " " in tg:
        base, _, mod = tg.rpartition(" ")
        if len(mod) == 1 and mod.isalpha():
            tg = base.strip().ljust(DSTAR_BASE_LEN) + mod + "L"
    elif len(tg) >= 2 and tg[-1] != "L":
        tg += "L"
    elif 5 <= len(tg) < 8:
        tg = tg[:-2].strip().ljust(DSTAR_BASE_LEN) + tg[-2] + "L"
    m = re.fullmatch(r"([A-Z0-9]{3,6}) *([A-Z])L", tg)
    if not m:
        raise ValueError(f"D-STAR {str(value).strip()[:20]}: a reflector or gateway and its module, for example REF001 C")
    return m.group(1).ljust(DSTAR_BASE_LEN) + m.group(2) + "L"


def _norm_m17_fav(f):
    ref, _, mod = str(f.get("num", "")).strip().upper().partition(" ")
    mod = mod.strip() or str(f.get("module", "")).strip().upper() or "@ALL"
    if mod == "ALL":
        mod = "@ALL"
    if not _M17_REF_RE.fullmatch(ref):
        raise ValueError("M17 reflector must look like M17-USA (letters, digits and dashes, up to 16)")
    if mod != "@ALL" and not re.fullmatch(r"[A-Z]", mod):
        raise ValueError(f"M17 module for {ref} must be a letter A-Z or @ALL")
    out = {"mode": "M17", "num": ref, "module": mod, "label": _label(f.get("label"), f"M17 {ref} {mod}")}
    ip = str(f.get("ip", "") or "").strip()
    if ip and ip != BLANK_ADDR and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", ip):
        out["ip"] = ip
    return out


def _norm_gain_opt(value):
    if value is None or str(value).strip() == "":
        return None
    return _norm_gain(value)


def _norm_fav(f, nets=None):
    out = _norm_fav_core(f, nets)
    if isinstance(f, dict):
        for k in ("rx_gain_db", "tx_gain_db"):
            g = _norm_gain_opt(f.get(k))
            if g is not None:
                out[k] = g
    return out


def _norm_fav_core(f, nets=None):
    if not isinstance(f, dict):
        raise ValueError("bad favorite")
    mode = _mode_of(f.get("mode", "ASL") or "ASL")
    if mode == "M17":
        return _norm_m17_fav(f)
    if mode in DVS_MODES:
        tg = _clean_tg(f.get("num"), mode)
        if mode == "DSTAR":
            tg = dstar_tune_str(tg)
        out = {"mode": mode, "num": tg}
        if mode == "DMR":
            net = str(f.get("net", "") or "").strip()
            if not net:
                raise ValueError(f"DMR {tg}: pick its network")
            if nets is not None:
                hit = next((n for n in nets if n["name"].lower() == net.lower()), None)
                if hit is None:
                    raise ValueError(f"DMR {tg}: network {net} is not in the DMR network list")
                net = hit["name"]
            out["net"] = net
        out["label"] = _label(f.get("label"), fav_name(out))
        return out
    num = str(f.get("num", "")).strip()
    if not num.isdigit() or int(num) <= 0 or len(num) > (6 if mode == "EchoLink" else 7):
        raise ValueError(f"{mode} number must be digits ({'up to 6' if mode == 'EchoLink' else 'up to 7'})")
    if mode == "ASL" and num == REC_NODE:
        raise ValueError(f"Node {REC_NODE} is the transmit node, not a favorite")
    return {"mode": mode, "num": str(int(num)), "label": _label(f.get("label"), f"{mode} {int(num)}")}


def _norm_net(n):
    if not isinstance(n, dict):
        raise ValueError("bad DMR network")
    name = _CALL_TRIM.sub(" ", str(n.get("name", "") or "")).strip()
    if not name or len(name) > 24 or any(c in name for c in "|[]#;="):
        raise ValueError("A DMR network needs a name: up to 24 characters, with no | [ ] # ; =")
    addr = str(n.get("address", "") or "").strip()
    if not _DMR_ADDR_RE.fullmatch(addr) or not 0 < int(addr.rsplit(":", 1)[1]) < 65536:
        raise ValueError(f"{name}: the address must be host:port, for example tgif.network:62031")
    pw = str(n.get("password", "") or "").strip()
    if not pw:
        raise ValueError(f"{name}: the network needs its password")
    if len(pw) > 64 or _CALL_TRIM.search(pw) or "|" in pw:
        raise ValueError(f"{name}: the password must be up to 64 characters, with no |")
    url = str(n.get("url", "") or "").strip()
    if url and (not url.startswith(("http://", "https://")) or len(url) > 200 or "|" in url or _CALL_TRIM.search(url)):
        raise ValueError(f"{name}: the network link must start with http:// or https://")
    return {"name": name, "password": pw, "address": addr, "url": url}


def nets_public(nets):
    return [{"name": n["name"], "address": n["address"], "url": n["url"], "has_password": bool(n["password"])} for n in nets]


def fav_target(f):
    if f["mode"] == "M17":
        return f"{f['num']}|{f['module']}"
    if f["mode"] in DVS_MODES:
        return f"{f['mode']}|{f.get('net', '')}|{f['num']}"
    return f["num"] if f["mode"] == "ASL" else "3" + f["num"].zfill(6)


def fav_name(f):
    if f["mode"] == "DMR":
        return f"DMR {f.get('net', '')} {f['num']}"
    if f["mode"] == "DSTAR":
        return "D-STAR " + " ".join(f["num"].split())
    return f"{f['mode']} {f['num']}" + (f" {f['module']}" if f["mode"] == "M17" else "")


def _fav_section(f):
    if f["mode"] == "DMR":
        return "DMR_" + _server_key(f["net"])
    return {"ASL": "ASL", "EchoLink": "ECHO"}.get(f["mode"], f["mode"])


_GAIN_TOKEN_RE = re.compile(r"(rx|tx)=(-?\d+)")


def _fav_gain_tail(f):
    return "".join(f"|{k[:2]}={f[k]}" for k in ("rx_gain_db", "tx_gain_db") if k in f)


def _fav_line(f):
    if f["mode"] == "M17":
        return f"{f['label']}|{f['num']}|{f['module']}|{f.get('ip', '')}" + _fav_gain_tail(f)
    return f"{f['label']}|{f['num']}" + _fav_gain_tail(f)


def parse_fav_conf(text, fav_limit=FAV_MAX, net_limit=DMR_NET_MAX):
    nets, cfg, bad, rows = [], {}, [], []
    section = ""
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and "]" in line and "|" not in line:
            section = line[1:line.index("]")].strip().upper()
            continue
        if section == "CONFIG":
            if "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip().lower()] = v.strip()
            continue
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if section == "DMR_SERVERS":
            if len(parts) < 3:
                continue
            try:
                n = _norm_net({"name": parts[0], "password": parts[1], "address": parts[2],
                               "url": parts[3] if len(parts) > 3 else ""})
            except ValueError as exc:
                bad.append(f"line {no}: {exc}")
                continue
            if any(x["name"].lower() == n["name"].lower() for x in nets):
                bad.append(f"line {no}: network {n['name']} is listed twice")
            elif len(nets) < net_limit:
                nets.append(n)
            continue
        gains = {}
        kept = []
        for p in parts:
            m = _GAIN_TOKEN_RE.fullmatch(p)
            if m:
                gains[m.group(1) + "_gain_db"] = m.group(2)
            else:
                kept.append(p)
        parts = kept
        if len(parts) < 2:
            continue
        name, val = parts[0], parts[1]
        if not name or name.lower() == BLANK_NAME or val in ("", BLANK_ADDR):
            continue
        if section.startswith("DMR_"):
            f = {"mode": "DMR", "num": val, "label": name, "key": section[4:]}
        elif section in ("ASL", "ECHO"):
            f = {"mode": "ASL" if section == "ASL" else "EchoLink", "num": val, "label": name}
        elif section in DVS_MODES and section != "DMR":
            f = {"mode": section, "num": val, "label": name}
        elif section == "M17":
            if len(parts) >= 4:
                f = {"mode": "M17", "num": parts[1], "module": parts[2] or "@ALL", "ip": parts[3], "label": name}
            else:
                f = {"mode": "M17", "num": name, "module": "@ALL", "ip": val, "label": name}
        else:
            continue
        f.update(gains)
        rows.append((no, f))
    keys = {_server_key(n["name"]): n["name"] for n in nets}
    favs, seen, more = [], set(), 0
    for no, f in rows:
        if "key" in f:
            key = f.pop("key")
            if key not in keys:
                bad.append(f"line {no}: [DMR_{key}] has no network in [DMR_SERVERS]")
                continue
            f["net"] = keys[key]
        try:
            f = _norm_fav(f, nets)
        except ValueError as exc:
            bad.append(f"line {no}: {exc}")
            continue
        t = fav_target(f)
        if t in seen:
            continue
        seen.add(t)
        if len(favs) < fav_limit:
            favs.append(f)
        else:
            more += 1
    return {"favs": favs, "nets": nets, "cfg": cfg, "bad": bad, "more": more}


def render_fav_conf(favs, nets, cfg):
    out = ["# noderecorder_favorites.conf: Node Recorder favorites in Node Controller's asl_dvs.conf format.",
           "# The Connect tab lists the favorites in the order they appear here.", "",
           "[CONFIG]"]
    for k in ("callsign", "bridge_nodes"):
        out.append(f"{k}={cfg.get(k, '')}")
    out += ["", "[DMR_SERVERS]", "# name|password|address:port|network_url"]
    for n in nets:
        out.append(f"{n['name']}|{n['password']}|{n['address']}|{n['url']}")
    section = None
    for f in favs:
        sec = _fav_section(f)
        if sec != section:
            out += ["", f"[{sec}]"]
            section = sec
        out.append(_fav_line(f))
    return "\n".join(out) + "\n"


_dash_cache = {"key": None, "v": None}


def dashboard_conf():
    key = _file_key(DASH_CONF)
    if key is not None and key == _dash_cache["key"]:
        return _dash_cache["v"]
    out = {"asl_node": "", "port": 8989, "bridges": set(), "bridge_list": [], "callsign": "", "favs": [], "nets": []}
    try:
        with open(DASH_CONF, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return out
    d = parse_fav_conf(text, fav_limit=200, net_limit=50)
    cfg = d["cfg"]
    if cfg.get("asl_node", "").isdigit():
        out["asl_node"] = cfg["asl_node"]
    if cfg.get("port", "").isdigit():
        out["port"] = int(cfg["port"])
    listed = cfg.get("bridge_nodes") or cfg.get("bridge_node") or ""
    out["bridge_list"] = [x.strip() for x in listed.split(",")]
    for k in ("bridge_node", "bridge_nodes"):
        out["bridges"].update(x.strip() for x in cfg.get(k, "").split(",") if x.strip())
    call = cfg.get("callsign", "").strip().upper()
    out["callsign"] = call if _CALLSIGN_RE.fullmatch(call) else ""
    out["favs"] = [f for f in d["favs"] if not (f["mode"] == "ASL" and f["num"] in out["bridges"])]
    out["nets"] = d["nets"]
    _dash_cache.update(key=key, v=out)
    return out


def main_node():
    n = _cfg_get("node")
    return n or dashboard_conf()["asl_node"]


_fav_lock = threading.RLock()
_fav_cache = {"key": None, "data": None}


def _json_favs():
    try:
        with open(FAV_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for f in data if isinstance(data, list) else []:
        if not isinstance(f, dict) or _mode_safe(f) not in ("ASL", "EchoLink", "M17"):
            continue
        try:
            out.append(_norm_fav(f))
        except ValueError:
            continue
    return out[:FAV_JSON_MAX]


def _write_fav_doc(favs, nets, cfg):
    with _fav_lock:
        _atomic_write(FAV_CONF_PATH, render_fav_conf(favs, nets, cfg), 0o600)
        _fav_cache["key"] = None
        mirror = []
        for f in favs:
            if f["mode"] in ("ASL", "EchoLink", "M17") and len(mirror) < FAV_JSON_MAX:
                mirror.append({k: f[k] for k in ("mode", "num", "module", "label") if k in f})
        try:
            _atomic_write(FAV_PATH, json.dumps(mirror, indent=1) + "\n", 0o644)
        except OSError as exc:
            log_event(f"Could not write {FAV_PATH} (the copy for older versions): {exc}", "warn")


def fav_doc():
    with _fav_lock:
        key = _file_key(FAV_CONF_PATH)
        if key is None:
            old = _json_favs()
            if old or os.path.exists(FAV_PATH):
                try:
                    _write_fav_doc(old, [], {})
                    log_event(f"Favorites moved to {FAV_CONF_PATH} ({len(old)})", "ok")
                except OSError as exc:
                    return {"favs": old, "nets": [], "cfg": {}, "bad": [], "more": 0, "error": str(exc)}
            key = _file_key(FAV_CONF_PATH)
            if key is None:
                return {"favs": [], "nets": [], "cfg": {}, "bad": [], "more": 0}
        if key == _fav_cache["key"]:
            return _fav_cache["data"]
        try:
            with open(FAV_CONF_PATH, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            return {"favs": _json_favs(), "nets": [], "cfg": {}, "bad": [], "more": 0, "error": str(exc)}
        data = parse_fav_conf(text)
        for b in data["bad"][:5]:
            log_event(f"Favorites file: skipped {b}", "warn")
        if data["more"]:
            log_event(f"Favorites file: {data['more']} favorite(s) past the first {FAV_MAX} skipped", "warn")
        _fav_cache.update(key=key, data=data)
        return data


def fav_load():
    return fav_doc()["favs"]


def nets_load():
    return fav_doc()["nets"]


def favcfg():
    return fav_doc()["cfg"]


def nets_save(rows):
    if not isinstance(rows, list):
        return {"ok": False, "error": "networks must be a list"}
    if len(rows) > DMR_NET_MAX:
        return {"ok": False, "error": f"At most {DMR_NET_MAX} DMR networks."}
    with _fav_lock:
        doc = fav_doc()
        old = {n["name"]: n for n in doc["nets"]}
        clean, renames = [], {}
        try:
            for r in rows:
                if not isinstance(r, dict):
                    raise ValueError("bad DMR network")
                orig = str(r.get("orig", "") or "")
                pw = str(r.get("password", "") or "")
                if not pw.strip() and orig in old:
                    pw = old[orig]["password"]
                n = _norm_net(dict(r, password=pw))
                if orig in old and orig != n["name"]:
                    renames[orig] = n["name"]
                clean.append(n)
            names, keys = set(), set()
            for n in clean:
                if n["name"].lower() in names or _server_key(n["name"]) in keys:
                    raise ValueError(f"Network {n['name']} is listed twice.")
                names.add(n["name"].lower())
                keys.add(_server_key(n["name"]))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        favs = [dict(f, net=renames.get(f["net"], f["net"])) if f["mode"] == "DMR" else f for f in doc["favs"]]
        used = next((f for f in favs if f["mode"] == "DMR" and f["net"] not in {n["name"] for n in clean}), None)
        if used is not None:
            return {"ok": False, "error": f"Favorite {used['label']} uses network {used['net']}: remove that favorite first."}
        try:
            _write_fav_doc(favs, clean, doc["cfg"])
        except OSError as exc:
            return {"ok": False, "error": f"Could not save: {exc}"}
    _dvs_now["dmr"] = ""
    log_event(f"DMR networks saved ({len(clean)})", "ok")
    return {"ok": True, "message": f"Saved {len(clean)} DMR network(s).", "nets": nets_public(clean)}


def nets_import():
    dash = dashboard_conf()["nets"]
    if not dash:
        return {"ok": False, "error": f"No DMR networks found in {DASH_CONF}."}
    with _fav_lock:
        doc = fav_doc()
        nets = list(doc["nets"])
        have = {n["name"].lower() for n in nets} | {_server_key(n["name"]) for n in nets}
        added = []
        for n in dash:
            if n["name"].lower() in have or _server_key(n["name"]) in have or len(nets) >= DMR_NET_MAX:
                continue
            nets.append(n)
            added.append(n["name"])
            have.update((n["name"].lower(), _server_key(n["name"])))
        if not added:
            return {"ok": True, "message": "Every Node Controller DMR network is already in the list (or the list is full).",
                    "nets": nets_public(nets)}
        try:
            _write_fav_doc(doc["favs"], nets, doc["cfg"])
        except OSError as exc:
            return {"ok": False, "error": f"Could not save: {exc}"}
    log_event(f"DMR networks copied from Node Controller: {', '.join(added)}", "ok")
    return {"ok": True, "message": f"Copied {len(added)} DMR network(s) from Node Controller: {', '.join(added)}.",
            "nets": nets_public(nets)}


def _norm_bridge(value, what):
    v = str(value or "").strip()
    if not v:
        return ""
    if not v.isdigit() or len(v) > 7 or int(v) <= 0:
        raise ValueError(f"{what} must be a node number")
    if v == REC_NODE:
        raise ValueError(f"Node {REC_NODE} is the transmit node, not a bridge node")
    if v == main_node():
        raise ValueError(f"Node {v} is the main node, not a bridge node")
    return str(int(v))


def _norm_callsign(value):
    c = str(value or "").strip().upper()
    if c and not _CALLSIGN_RE.fullmatch(c):
        raise ValueError("The callsign must be 3 to 10 letters, digits, / or -")
    return c


def digital_save(body):
    try:
        d = _norm_bridge(body.get("digital_bridge"), "The digital bridge node")
        m = _norm_bridge(body.get("m17_bridge"), "The M17 bridge node")
        call = _norm_callsign(body.get("callsign"))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if d and d == m:
        return {"ok": False, "error": "The digital and M17 bridge nodes must differ."}
    with _fav_lock:
        doc = fav_doc()
        cfg = dict(doc["cfg"], callsign=call, bridge_nodes=f"{d},{m}" if d or m else "")
        try:
            _write_fav_doc(doc["favs"], doc["nets"], cfg)
        except OSError as exc:
            return {"ok": False, "error": f"Could not save: {exc}"}
    _bridge_cache["t"] = -60.0
    log_event("Digital settings saved", "ok")
    return {"ok": True, "message": "Saved."}


def _ini_read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None
    out, sec = {}, ""
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and "]" in line:
            sec = line[1:line.index("]")].strip().lower()
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            out.setdefault(sec, {})[k.strip().lower()] = v.strip()
    return out


def _ports_of(d, sec, a, b):
    try:
        return frozenset((int(d[sec][a]), int(d[sec][b])))
    except (KeyError, ValueError, TypeError):
        return None


_USRP_RX_RE = re.compile(r"^\s*rxchannel\s*=>?\s*USRP/[^:\s]+:(\d+):(\d+)", re.I)


def _usrp_nodes():
    try:
        lines, stanzas = read_rpt()
    except OSError:
        return {}
    out = {}
    for i, s in enumerate(stanzas):
        if not _is_node_name(s["name"]) or s["name"] == REC_NODE:
            continue
        end = stanzas[i + 1]["header"] if i + 1 < len(stanzas) else len(lines)
        for ln in lines[s["header"] + 1:end]:
            m = _USRP_RX_RE.match(ln.split(";", 1)[0])
            if m:
                out.setdefault(frozenset((int(m.group(1)), int(m.group(2)))), s["name"])
    return out


_bridge_cache = {"t": -60.0, "v": None}


def bridge_nodes(max_age=30.0):
    if _bridge_cache["v"] is not None and time.monotonic() - _bridge_cache["t"] < max_age:
        return _bridge_cache["v"]
    setv = ([x.strip() for x in str(favcfg().get("bridge_nodes", "")).split(",")] + ["", ""])[:2]
    usrp = _usrp_nodes()
    ab = _ini_read(AB_INI) or {}
    m17 = _ini_read(M17_INI) or {}
    dash = dashboard_conf()["bridge_list"]
    ports = (_ports_of(ab, "usrp", "txport", "rxport") or frozenset((32001, 34001)),
             _ports_of(m17, "usrp network", "dstport", "localport") or frozenset(M17_USRP_PORTS))
    out = {}
    for i, kind in enumerate(("digital", "m17")):
        if setv[i].isdigit():
            node, src = setv[i], "set here"
        elif ports[i] in usrp:
            node, src = usrp[ports[i]], "rpt.conf"
        elif len(dash) > i and dash[i].isdigit():
            node, src = dash[i], "Node Controller"
        elif DEFAULT_BRIDGES[i] in usrp.values():
            node, src = DEFAULT_BRIDGES[i], "default"
        else:
            node, src = "", ""
        out[kind], out[kind + "_src"] = node, src
    _bridge_cache.update(t=time.monotonic(), v=out)
    return out


def callsign_now():
    call = str(favcfg().get("callsign", "")).strip().upper()
    if _CALLSIGN_RE.fullmatch(call):
        return call, "set here"
    ini = (_ini_read(M17_INI) or {}).get("m17 network", {})
    call = str(ini.get("callsign", "")).strip().upper()
    if _CALLSIGN_RE.fullmatch(call):
        return call, "USRP2M17.ini"
    call = dashboard_conf()["callsign"]
    if call:
        return call, "Node Controller"
    return "", ""


def port_open(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


_probe_cache = {}


def port_open_cached(port, ttl=15.0):
    now = time.monotonic()
    hit = _probe_cache.get(port)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = port_open(port)
    _probe_cache[port] = (now, val)
    return val


def _read_local_key():
    try:
        with open(LOCAL_KEY_PATH, "r", encoding="ascii") as fh:
            return fh.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def local_key():
    key = _read_local_key()
    if len(key) >= 32:
        return key
    key = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(LOCAL_KEY_PATH), exist_ok=True)
        fd = os.open(LOCAL_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(key + "\n")
        return key
    except FileExistsError:
        return _read_local_key()
    except OSError:
        return ""


def dash_call(body, timeout=25):
    port = dashboard_conf()["port"]
    key = local_key()
    if not key or not port_open(port):
        return None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            conn.request("POST", "/api/local/action", json.dumps(body),
                         {"Content-Type": "application/json", "X-ASL-DVS-Local-Key": key})
            resp = conn.getresponse()
            raw = resp.read()
        finally:
            conn.close()
    except (OSError, http.client.HTTPException):
        return None
    if resp.status in (404, 405):
        return None
    answered = f"Node Controller answered HTTP {resp.status}"
    try:
        d = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        d = None
    if not isinstance(d, dict):
        return {"ok": False, "error": answered}
    msg = str(d.get("message", ""))
    return {"ok": bool(d.get("ok")), "message": msg, "error": msg or answered}


def _connect_node():
    node = main_node()
    return (node, "") if node else (None, "Set the node on the Setup tab first.")


_m17_status = {"t": -M17_STATUS_TTL, "v": ""}


def m17_current(max_age=M17_STATUS_TTL):
    now = time.monotonic()
    if now - _m17_status["t"] < max_age:
        return _m17_status["v"]
    r = dash_call({"action": "m17-status"}, timeout=3)
    v = r["message"].strip().upper() if r and r["ok"] else ""
    _m17_status.update(t=now, v=v)
    return v


def _has_m17(favs):
    return any(f["mode"] == "M17" for f in favs)


def _m17_error(r):
    if r is None:
        return "M17 goes through Node Controller, which is not running."
    err = r["error"]
    if err.startswith("Unknown local action"):
        err = "this version can't connect M17 for Node Recorder; update Node Controller."
    return f"Node Controller: {err}"


def nc_running(cached=False):
    port = dashboard_conf()["port"]
    return port_open_cached(port, ttl=5.0) if cached else port_open(port)


def dvs_path():
    return next((p for p in DVS_SEARCH_PATHS if os.path.isfile(p)), "")


_dvs_now = {"mode": "", "dmr": ""}


def dvs(sub, arg=None):
    path = dvs_path()
    if not path:
        return False, "dvswitch.sh was not found"
    if sub == "mode":
        _dvs_now["dmr"] = ""
    cmd = ["bash", path, sub] + ([str(arg)] if arg is not None else [])
    tmo = DVS_TIMEOUT.get(sub, DVS_OTHER_TIMEOUT)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=tmo)
    except subprocess.TimeoutExpired:
        return False, f"dvswitch.sh {sub} took longer than {tmo} s; it may still finish"
    except OSError as exc:
        return False, str(exc)
    return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()


def _svc_active(svc):
    return _systemctl("is-active", "--quiet", svc, timeout=10).returncode == 0


def _gateway_up(mode):
    svc = GATEWAY_SERVICES.get(mode)
    if not svc or _svc_active(svc):
        return True, ""
    r = _systemctl("start", svc, timeout=30)
    deadline = time.monotonic() + GATEWAY_WAIT_SEC
    while True:
        if _svc_active(svc):
            log_event(f"Started {svc} for {MODE_LABEL.get(mode, mode)}", "ok")
            return True, ""
        if time.monotonic() >= deadline:
            return False, f"{svc} did not start: {(r.stderr or r.stdout or 'not active').strip()[:160]}"
        time.sleep(0.25)


def service_states(units):
    r = _systemctl("show", "-p", "Id,LoadState,ActiveState", *units, timeout=15)
    out = {u: "unknown" for u in units}
    for block in (r.stdout or "").split("\n\n"):
        kv = dict(ln.split("=", 1) for ln in block.splitlines() if "=" in ln)
        unit = kv.get("Id", "")
        if unit in out:
            out[unit] = "missing" if kv.get("LoadState") == "not-found" else kv.get("ActiveState", "unknown")
    return out


def _linked(node, peer, max_age=0):
    _, links = rpt_links(node, max_age=max_age)
    return any(l["node"] == peer for l in links)


_tune_lock = threading.Lock()
_solo = {"mode": "", "target": "", "name": "", "bridge": ""}


def _solo_set(**kw):
    _solo.update(mode="", target="", name="", bridge="")
    _solo.update({k: str(v) for k, v in kw.items() if k in _solo})
    try:
        _atomic_write(TUNED_PATH, json.dumps(_solo) + "\n", 0o644)
    except OSError as exc:
        log_event(f"Could not write {TUNED_PATH}: {exc}", "warn")


def _solo_load():
    try:
        with open(TUNED_PATH, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return
    if isinstance(d, dict):
        _solo.update({k: str(d.get(k, "") or "")[:80] for k in _solo})


def _m17_ini_text(callsign, name, addr, module):
    return (
        "[M17 Network]\n"
        f"Callsign={callsign}\n"
        f"Address={addr}\n"
        f"Name={name} {module}\n"
        f"LocalPort={M17_NET_PORTS[0]}\n"
        f"DstPort={M17_NET_PORTS[1]}\n"
        f"GainAdjustdB={M17_GAIN_DB}\n"
        "Daemon=1\n"
        "Debug=0\n"
        "\n"
        "[USRP Network]\n"
        "Address=127.0.0.1\n"
        f"DstPort={M17_USRP_PORTS[0]}\n"
        f"LocalPort={M17_USRP_PORTS[1]}\n"
        f"GainAdjustdB={M17_GAIN_DB}\n"
        "Debug=0\n"
        "\n"
        "[Log]\n"
        "DisplayLevel=0\n"
        "FileLevel=0\n"
        "FilePath=/var/log/usrp\n"
        "FileRoot=USRP2M17\n"
    )


def _m17_park():
    try:
        _atomic_write(M17_INI, _m17_ini_text(callsign_now()[0], "DISCONNECTED", "0.0.0.0", "A"), 0o644)
    except OSError as exc:
        log_event(f"Could not write {M17_INI}: {exc}", "warn")
        return
    _systemctl("restart", M17_SERVICE, timeout=30)


def _m17_present():
    return os.path.isfile(M17_INI) or os.path.isfile("/opt/USRP2M17/USRP2M17")


def m17_lookup(ref, module):
    try:
        with open(M17_HOSTS, "r", encoding="utf-8", errors="replace") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return "", ""
    for e in (doc.get("reflectors") if isinstance(doc, dict) else None) or []:
        if not isinstance(e, dict) or str(e.get("designator", "")).strip().upper() != ref:
            continue
        if e.get("port") not in (None, "") and str(e.get("port")) != "17000":
            continue
        addr = str(e.get("dns") or "").strip() or str(e.get("ipv4") or "").strip()
        mods = e.get("modules")
        pub = {str(x).strip().upper()[:1] for x in mods} if isinstance(mods, list) else \
            set(re.sub(r"[^A-Z]", "", mods.upper())) if isinstance(mods, str) else set()
        if pub and module != "@ALL" and module not in pub:
            return "", f"{ref} does not publish module {module} (it has {', '.join(sorted(pub))})"
        return addr, ""
    return "", ""


PRIVATE_MAX = 1999
LINK_DROP_PACING_SEC = 0.25
LINK_DROP_MAX = 16
GUARD_SEC = 5.0
GUARD_POLLS = 2
GUARD_COOLDOWN_SEC = 8.0
NO_LINK_LIST = "Asterisk did not list the node's links (rpt lstats), so nothing was changed."


def is_private(peer):
    return str(peer).isdigit() and int(peer) <= PRIVATE_MAX


def perm_links(node):
    try:
        lines, stanzas = read_rpt()
    except OSError:
        return frozenset()
    for i, s in enumerate(stanzas):
        if s["name"] != node:
            continue
        end = stanzas[i + 1]["header"] if i + 1 < len(stanzas) else len(lines)
        for ln in lines[s["header"] + 1:end]:
            k, sep, v = _strip_comment(ln).partition("=")
            if sep and k.strip().lower() == "nodes":
                return frozenset(x for x in re.split(r"[,\s>]+", v.strip()) if x.isdigit())
    return frozenset()


def drop_link(node, peer, perms=None):
    perms = perm_links(node) if perms is None else perms
    perm = peer in perms
    ilink(node, 11 if perm else 1, peer)
    return perm


def teardown(node, keep=(), what="Connect"):
    ok, links = rpt_links(node, max_age=0)
    if not ok:
        return None
    b = bridge_nodes()
    bridges = {b["digital"], b["m17"]} - {""}
    keep = set(keep) | {REC_NODE}
    perms = perm_links(node)
    dropped = []
    for l in links:
        peer = l["node"]
        if peer in keep or (peer not in bridges and is_private(peer)):
            continue
        if len(dropped) >= LINK_DROP_MAX:
            log_event(f"{what}: more than {LINK_DROP_MAX} links; the rest are left to the guard", "warn")
            break
        perm = drop_link(node, peer, perms)
        dropped.append(peer + (" (permanent)" if perm else ""))
        time.sleep(LINK_DROP_PACING_SEC)
    if dropped:
        log_event(f"{what}: dropped {', '.join(dropped)}", "info")
    return dropped


def _leave(node, next_kind):
    mode, bridge = _solo["mode"], _solo["bridge"]
    if mode in DVS_MODES:
        if mode == "DSTAR":
            dvs("tune", DSTAR_UNLINK)
        if next_kind != "dvs":
            dvs("tune", DVS_DISCONNECT)
            if bridge:
                ilink(node, 1, bridge)
    elif mode == "M17" and next_kind != "m17":
        _m17_park()
        if bridge:
            ilink(node, 1, bridge)
    if mode:
        _solo_set()


def _busy():
    return {"ok": False, "error": "Another connect or disconnect is still running; try again in a moment."}


_asl_keep = {"v": ""}
_guard = {"armed": False, "up": {}, "down": 0, "multi": 0, "left_alone": frozenset(), "last": {}}


def _guard_owner(node):
    return bool(node) and not (nc_running(cached=True) and node == dashboard_conf()["asl_node"])


def _guard_drop(node, peers, why):
    if not _tune_lock.acquire(blocking=False):
        return
    try:
        perms = perm_links(node)
        for peer in peers[:LINK_DROP_MAX]:
            perm = drop_link(node, peer, perms)
            log_event(f"Guard: dropped {peer}{' (permanent, ilink 11)' if perm else ''}: {why}", "warn")
            time.sleep(LINK_DROP_PACING_SEC)
    finally:
        _tune_lock.release()


def guard_tick():
    g = _guard
    node = main_node()
    if not _guard_owner(node):
        g.update(armed=False, up={}, down=0, multi=0, left_alone=frozenset())
        return
    if not g["armed"]:
        return
    ok, links = rpt_links(node, max_age=2.0)
    if not ok:
        return
    peers = [l["node"] for l in links]
    b = bridge_nodes()
    bridges = {b["digital"], b["m17"]} - {""}
    own = _solo["bridge"] if _solo["target"] else ""
    now = time.monotonic()
    for peer in list(g["up"]):
        if peer == own or peer not in peers:
            del g["up"][peer]
    for peer in peers:
        if peer not in bridges or peer == own:
            continue
        g["up"][peer] = g["up"].get(peer, 0) + 1
        if g["up"][peer] >= GUARD_POLLS and now - g["last"].get(peer, -1e9) >= GUARD_COOLDOWN_SEC:
            g["last"][peer], g["up"][peer] = now, 0
            _guard_drop(node, [peer], f"bridge node linked, but {'it is not the bridge of ' + _solo['name'] if own else 'nothing digital is tuned'}")
    if own and own not in peers:
        g["down"] += 1
        if g["down"] >= GUARD_POLLS and now - g["last"].get("watchdog", -1e9) >= GUARD_COOLDOWN_SEC \
                and _tune_lock.acquire(blocking=False):
            try:
                g["last"]["watchdog"], g["down"] = now, 0
                ok, out = ilink(node, 3, own)
                log_event(f"Guard: bridge node {own} for {_solo['name']} was not linked; linking it again"
                          + ("" if ok else f" failed: {out.strip()[:120]}"), "warn")
            finally:
                _tune_lock.release()
    else:
        g["down"] = 0
    public = [p for p in peers if p != REC_NODE and p not in bridges and not is_private(p)]
    if own or len(public) <= 1:
        g["multi"] = 0
        if len(public) <= 1:
            g["left_alone"] = frozenset()
        return
    if frozenset(public) == g["left_alone"]:
        g["multi"] = 0
        return
    g["multi"] += 1
    if g["multi"] < GUARD_POLLS:
        return
    g["multi"] = 0
    keep = _asl_keep["v"] if _asl_keep["v"] in public else public[0]
    favs = {fav_target(f) for f in fav_load() if f["mode"] in ("ASL", "EchoLink")}
    extra = [p for p in public if p != keep and p in favs]
    if not extra:
        g["left_alone"] = frozenset(public)
        log_event(f"Guard: more than one link ({', '.join(public)}), but none of the extras is a favorite; left alone", "info")
        return
    _guard_drop(node, extra, f"more than one link, keeping {keep}")


def guard_loop():
    while True:
        time.sleep(GUARD_SEC)
        try:
            guard_tick()
        except Exception as exc:
            log_event(f"Guard error: {exc}", "err")


def _hide(text, secret):
    return (text or "").replace(secret, "***") if secret else (text or "")


NC_NET_MISSING = "dmr-network-missing"
_nc_dvs_status = {"t": -M17_STATUS_TTL, "v": None}


def _nc_old(r):
    return r is not None and r["error"].startswith("Unknown local action")


def nc_dvs(f, node, net_action=None):
    dash_node = dashboard_conf()["asl_node"]
    if not dash_node:
        return {"ok": False, "error": "DVSwitch goes through Node Controller; set its node first."}
    if node != dash_node:
        return {"ok": False, "error": f"DVSwitch goes through Node Controller's node {dash_node}, but Node Recorder's node is {node}. "
                                      f"Send node {dash_node}'s audio here (Setup tab, Receive) to use it."}
    body = {"action": "dvs-tune", "mode": f["mode"], "tg": f["num"], "name": f["label"]}
    net = None
    if f["mode"] == "DMR":
        net = next((n for n in nets_load() if n["name"] == f.get("net")), None)
        if net is None:
            return {"ok": False, "error": f"DMR network {f.get('net')} is not in the network list (Setup tab, Digital card)."}
        body["net"] = {"name": net["name"], "address": net["address"], "password": net["password"], "url": net["url"]}
        if net_action == "once":
            body["once"] = True
        elif net_action == "add":
            r = dash_call({"action": "dmr-server-add", "net": body["net"]}, timeout=30)
            if r is None:
                return {"ok": False, "error": "Node Controller is not answering."}
            if not r["ok"]:
                return {"ok": False, "error": "this version of Node Controller can't take networks from Node Recorder; update it."
                        if _nc_old(r) else f"Node Controller: {r['error']}"}
            log_event(f"Added DMR network {net['name']} to Node Controller", "ok")
    r = dash_call(body, timeout=100)
    _nc_dvs_status["t"] = -M17_STATUS_TTL
    _lstats_invalidate()
    if r is None:
        return {"ok": False, "error": "Node Controller is not answering."}
    if not r["ok"]:
        if _nc_old(r):
            return {"ok": False, "error": "Node Controller is running, but this version can't tune DVSwitch for Node Recorder: update Node Controller."}
        if r["error"].startswith(NC_NET_MISSING) and net is not None:
            return {"ok": False, "need_net": True, "warn": True, "net": net["name"],
                    "error": f"Node Controller doesn't have DMR network {net['name']} ({net['address']})."}
        return {"ok": False, "error": f"Node Controller: {r['error']}"}
    log_event(f"Tuned {fav_name(f)} through Node Controller", "ok")
    return {"ok": True, "message": f"{r['message'] or 'Tuned'} (through Node Controller)"}


def nc_dvs_current(max_age=M17_STATUS_TTL):
    now = time.monotonic()
    if now - _nc_dvs_status["t"] < max_age:
        return _nc_dvs_status["v"]
    r = dash_call({"action": "dvs-status"}, timeout=3)
    v = None
    if r is not None and r["ok"]:
        try:
            v = json.loads(r["message"])
        except ValueError:
            v = None
    _nc_dvs_status.update(t=now, v=v if isinstance(v, dict) else None)
    return _nc_dvs_status["v"]


def nc_dvs_target(favs, max_age=M17_STATUS_TTL):
    d = nc_dvs_current(max_age)
    if not d or not d.get("fav"):
        return ""
    nets = {n["name"]: n for n in nets_load()}
    for f in favs:
        if f["mode"] != d.get("page") or f["num"] != d["fav"]:
            continue
        if f["mode"] == "DMR":
            n = nets.get(f.get("net"))
            if not n or (n["name"].lower() != str(d.get("server", "")).lower()
                         and n["address"].lower() != str(d.get("address", "")).lower()):
                continue
        return fav_target(f)
    return ""


def _has_dvs(favs):
    return any(f["mode"] in DVS_MODES for f in favs)


def solo_dvs(f, node, net_action=None):
    label = MODE_LABEL.get(f["mode"], f["mode"])
    if nc_running():
        return nc_dvs(f, node, net_action)
    if not dvs_path():
        return {"ok": False, "error": f"dvswitch.sh was not found, so {label} can't be tuned here."}
    b = bridge_nodes(0)
    bridge = b["digital"]
    if not bridge:
        return {"ok": False, "error": "No digital bridge node was found: set it on the Setup tab (Digital card)."}
    net = None
    if f["mode"] == "DMR":
        net = next((n for n in nets_load() if n["name"] == f.get("net")), None)
        if net is None:
            return {"ok": False, "error": f"DMR network {f.get('net')} is not in the network list (Setup tab, Digital card)."}
    if not _tune_lock.acquire(timeout=1.0):
        return _busy()
    try:
        dropped = teardown(node, {bridge}, f"Tune {fav_name(f)}")
        if dropped is None:
            return {"ok": False, "error": NO_LINK_LIST}
        _guard["armed"] = True
        _asl_keep["v"] = ""
        _leave(node, "dvs")
        ok, why = _gateway_up(f["mode"])
        if not ok:
            return {"ok": False, "error": why}
        if not _linked(node, bridge):
            ok, out = ilink(node, 3, bridge)
            if not ok:
                return {"ok": False, "error": f"Asterisk refused to link bridge node {bridge}: {out.strip()[:160] or 'no answer'}"}
        dvs("tune", DVS_DISCONNECT)
        time.sleep(DVS_SETTLE_SEC)
        if _dvs_now["mode"] != f["mode"]:
            ok, out = dvs("mode", f["mode"])
            _dvs_now["mode"] = f["mode"] if ok else ""
            if not ok:
                log_event(f"dvswitch.sh mode {f['mode']} failed: {out[:160]}", "warn")
            time.sleep(DVS_SETTLE_SEC)
        if net is not None:
            tune = f"{net['password']}@{net['address']}"
            if _dvs_now["dmr"] != tune:
                ok, out = dvs("tune", tune)
                if not ok:
                    return {"ok": False, "error": f"Could not join DMR network {net['name']}: {_hide(out, net['password'])[:160]}"}
                _dvs_now["dmr"] = tune
                log_event(f"Joined DMR network {net['name']} ({net['address']})", "ok")
                time.sleep(1.0)
        ok, out = dvs("tune", f["num"])
        if not ok:
            return {"ok": False, "error": f"Tune to {fav_name(f)} failed: {out[:160] or 'no answer from dvswitch.sh'}"}
        _solo_set(mode=f["mode"], target=fav_target(f), name=fav_name(f), bridge=bridge)
    finally:
        _tune_lock.release()
    log_event(f"Tuned {fav_name(f)}; bridge node {bridge} linked to node {node}"
              + (f" (dropped {', '.join(dropped)})" if dropped else ""), "ok")
    return {"ok": True, "message": f"Tuned {fav_name(f)}. Bridge node {bridge} is linked to node {node}."}


def solo_m17(f, node):
    if not _m17_present():
        return {"ok": False, "error": "USRP2M17 was not found, so M17 can't be tuned here."}
    b = bridge_nodes(0)
    bridge = b["m17"]
    if not bridge:
        return {"ok": False, "error": "No M17 bridge node was found: set it on the Setup tab (Digital card)."}
    call = callsign_now()[0]
    if not call:
        return {"ok": False, "error": "M17 needs your callsign: set it on the Setup tab (Digital card)."}
    addr, err = m17_lookup(f["num"], f["module"])
    if err:
        return {"ok": False, "error": err}
    addr = addr or f.get("ip", "")
    if not addr:
        return {"ok": False, "error": f"{f['num']} is not in {M17_HOSTS} and its favorite has no address."}
    if not _tune_lock.acquire(timeout=1.0):
        return _busy()
    try:
        dropped = teardown(node, {bridge}, f"Tune {fav_name(f)}")
        if dropped is None:
            return {"ok": False, "error": NO_LINK_LIST}
        _guard["armed"] = True
        _asl_keep["v"] = ""
        _leave(node, "m17")
        if dvs_path():
            dvs("tune", DVS_DISCONNECT)
        try:
            _atomic_write(M17_INI, _m17_ini_text(call, f["num"], addr, f["module"]), 0o644)
        except OSError as exc:
            return {"ok": False, "error": f"Could not write {M17_INI}: {exc}"}
        r = _systemctl("restart", M17_SERVICE, timeout=30)
        if r.returncode != 0:
            return {"ok": False, "error": f"{M17_SERVICE} did not restart: {(r.stderr or r.stdout).strip()[:160]}"}
        if not _linked(node, bridge):
            ok, out = ilink(node, 3, bridge)
            if not ok:
                return {"ok": False, "error": f"Asterisk refused to link bridge node {bridge}: {out.strip()[:160] or 'no answer'}"}
        _solo_set(mode="M17", target=fav_target(f), name=fav_name(f), bridge=bridge)
    finally:
        _tune_lock.release()
    log_event(f"Tuned {fav_name(f)} ({addr}); bridge node {bridge} linked to node {node}"
              + (f" (dropped {', '.join(dropped)})" if dropped else ""), "ok")
    return {"ok": True, "message": f"Tuned {fav_name(f)}. Bridge node {bridge} is linked to node {node}."}


def solo_disconnect(node):
    if not _tune_lock.acquire(timeout=1.0):
        return _busy()
    try:
        name = _solo["name"]
        _leave(node, "off")
    finally:
        _tune_lock.release()
    log_event(f"Disconnected {name}", "ok")
    return name


_handover_noted = {"v": False}


def solo_status(node):
    if not _solo["target"]:
        return ""
    if nc_running(cached=True):
        if not _handover_noted["v"]:
            _handover_noted["v"] = True
            log_event(f"Node Controller is running; it now does the tuning ({_solo['name']} was tuned here)", "info")
        _solo_set()
        return ""
    _handover_noted["v"] = False
    ok, links = rpt_links(node)
    if ok and not any(l["node"] == _solo["bridge"] for l in links):
        return ""
    return _solo["target"]


def digital_info():
    b = bridge_nodes(0)
    call, call_src = callsign_now()
    cfg = favcfg()
    setv = ([x.strip() for x in str(cfg.get("bridge_nodes", "")).split(",")] + ["", ""])[:2]
    m17_unit = M17_SERVICE + ".service"
    states = service_states(sorted(set(GATEWAY_SERVICES.values())) + [m17_unit])
    services = {MODE_LABEL.get(m, m): states.get(s, "unknown") for m, s in GATEWAY_SERVICES.items()}
    services["USRP2M17"] = states.get(m17_unit, "unknown")
    return {"ok": True, "control": "nc" if nc_running() else "solo", "dvswitch": dvs_path(),
            "analog_bridge": os.path.isfile(AB_INI), "m17": _m17_present(), "m17_hosts": os.path.isfile(M17_HOSTS),
            "services": services, "bridges": b,
            "set": {"digital_bridge": setv[0], "m17_bridge": setv[1], "callsign": str(cfg.get("callsign", ""))},
            "callsign": call, "callsign_src": call_src, "nets": nets_public(nets_load()), "net_max": DMR_NET_MAX,
            "dash_nets": len(dashboard_conf()["nets"]), "tuned": _solo["name"] if _solo["target"] else "",
            "file": FAV_CONF_PATH}


def m17_connect(f, node):
    if not nc_running():
        return solo_m17(f, node)
    dash_node = dashboard_conf()["asl_node"]
    if not dash_node:
        return {"ok": False, "error": "M17 goes through Node Controller; set its node first."}
    if node != dash_node:
        return {"ok": False, "error": f"M17 goes through Node Controller's node {dash_node}, but Node Recorder's node is {node}. "
                                      f"Send node {dash_node}'s audio here (Setup tab, Receive) to use M17."}
    r = dash_call({"action": "m17-connect", "reflector": f["num"], "module": f["module"], "name": f["label"]}, timeout=40)
    _lstats_invalidate()
    _m17_status["t"] = -M17_STATUS_TTL
    if r is None or not r["ok"]:
        return {"ok": False, "error": _m17_error(r)}
    log_event(f"Connect {fav_name(f)} through Node Controller", "ok")
    return {"ok": True, "message": f"{r['message'] or 'Connected'} (through Node Controller)"}


def wait_link(node, target, wait=LINK_WAIT_SEC):
    deadline = time.monotonic() + wait
    while True:
        ok, links = rpt_links(node, max_age=0)
        hit = next((l for l in links if l["node"] == target), None)
        if hit is not None and hit["state"].upper() in ("", "ESTABLISHED"):
            return "up"
        if time.monotonic() >= deadline:
            return "unknown" if not ok else "connecting" if hit else "down"
        time.sleep(1)


def _link_outcome(f, node, via):
    name = fav_name(f)
    state = wait_link(node, fav_target(f))
    if state == "up":
        log_event(f"Node {node} linked to {name}{via}", "ok")
        return {"ok": True, "message": f"Node {node} is connected to {name}{via}."}
    if state == "unknown":
        return {"ok": True, "warn": True,
                "message": f"Connect sent to {name}{via}, but Asterisk did not list the links (rpt lstats), so it could not be checked."}
    if state == "connecting":
        log_event(f"Node {node}: {name} has not answered after {LINK_WAIT_SEC} s; still trying", "warn")
        return {"ok": False, "warn": True,
                "error": f"{name} has not answered after {LINK_WAIT_SEC} s; node {node} is still trying. It may be offline or busy."}
    log_event(f"Node {node} could not connect to {name}", "warn")
    return {"ok": False, "error": f"Node {node} did not connect to {name}: no link after {LINK_WAIT_SEC} s. "
                                  "Check the number; the node may be offline or refusing connections."}


def _set_active(f, r):
    if isinstance(r, dict) and r.get("ok"):
        t = fav_target(f)
        saved = next((x for x in fav_load() if fav_target(x) == t), f)
        _active_gain.update(target=t, rx_gain_db=saved.get("rx_gain_db"), tx_gain_db=saved.get("tx_gain_db"))
    return r


def _clear_active(target, r):
    if isinstance(r, dict) and r.get("ok") and (target is None or _active_gain["target"] == target):
        _active_gain.update(target=None, rx_gain_db=None, tx_gain_db=None)
    return r


def _fav_at(favs, index):
    try:
        i = int(index)
    except (ValueError, TypeError, OverflowError):
        return None
    return favs[i] if 0 <= i < len(favs) else None


def node_connect(f, node):
    if node == dashboard_conf()["asl_node"]:
        r = dash_call({"action": "connect", "mode": f["mode"], "node": f["num"], "name": f["label"]})
        if r is not None:
            _lstats_invalidate()
            if not r["ok"]:
                return {"ok": False, "error": f"Node Controller: {r['error']}"}
            log_event(f"Connect {fav_name(f)} through Node Controller", "ok")
            return _link_outcome(f, node, " (through Node Controller)")
    if not _tune_lock.acquire(timeout=1.0):
        return _busy()
    try:
        dropped = teardown(node, {fav_target(f)}, f"Connect {fav_name(f)}")
        if dropped is None:
            return {"ok": False, "error": NO_LINK_LIST}
        _guard["armed"] = True
        if _solo["mode"]:
            _leave(node, "asl")
        _asl_keep["v"] = fav_target(f)
        ok, out = ilink(node, 3, fav_target(f))
    finally:
        _tune_lock.release()
    if not ok:
        return {"ok": False, "error": f"Asterisk refused: {out.strip()[:200] or 'no answer'}"}
    log_event(f"Connect {fav_name(f)} from node {node}", "ok")
    return _link_outcome(f, node, "")


def fav_disconnect(index=None):
    if index is None:
        return _clear_active(None, _fav_disconnect_impl(index))
    f = _fav_at(fav_load(), index)
    if f is None:
        return _fav_disconnect_impl(index)
    return _clear_active(fav_target(f), _fav_disconnect_impl(index))


def _fav_disconnect_impl(index=None):
    node, err = _connect_node()
    if not node:
        return {"ok": False, "error": err}
    favs = fav_load()
    if index is not None:
        f = _fav_at(favs, index)
        if f is None:
            return {"ok": False, "error": "Pick a favorite."}
        favs = [f]
    targets = {fav_target(f): f for f in favs}
    _, links = rpt_links(node, max_age=0)
    hit = [l["node"] for l in links if l["node"] in targets]
    done = []
    if _solo["target"] and _solo["target"] in targets and not nc_running():
        name = solo_disconnect(node)
        if isinstance(name, dict):
            return name
        done.append(name)
        _lstats_invalidate()
    if not done and _has_dvs(favs) and nc_running():
        tgt = nc_dvs_target(fav_load(), 0)
        if tgt in targets:
            r = dash_call({"action": "dvs-disconnect"}, timeout=60)
            _nc_dvs_status["t"] = -M17_STATUS_TTL
            if r is None or not r["ok"]:
                return {"ok": False, "error": "Node Controller is not answering." if r is None else f"Node Controller: {r['error']}"}
            _lstats_invalidate()
            done.append(fav_name(targets[tgt]))
            log_event(f"Disconnect {done[0]} through Node Controller", "ok")
    m17 = m17_current(0) if _has_m17(favs) and not done else ""
    if m17 in targets:
        r = dash_call({"action": "m17-disconnect"})
        _m17_status["t"] = -M17_STATUS_TTL
        if r is None or not r["ok"]:
            return {"ok": False, "error": _m17_error(r)}
        _lstats_invalidate()
        done.append(fav_name(targets[m17]))
        log_event(f"Disconnect {done[0]} through Node Controller", "ok")
    if not hit:
        return {"ok": True, "message": f"Disconnected {done[0]}." if done else ("That favorite is not linked." if index is not None else "No favorite is linked.")}
    drop_peers(node, hit)
    return {"ok": True, "message": f"Disconnected {', '.join(done + hit)}."}


def disconnect_links(_body=None):
    fav = fav_disconnect(None)
    tune = tune_disconnect(None)
    bad = [r["error"] for r in (fav, tune) if not r["ok"]]
    said = [r["message"] for r in (fav, tune) if r["ok"] and r["message"] not in ("No favorite is linked.", "Nothing is tuned.")]
    node, err = _connect_node()
    if node:
        ok, links = rpt_links(node, max_age=0)
        if not ok:
            bad.append(NO_LINK_LIST)
        else:
            hit = [l["node"] for l in links if l["node"] != REC_NODE]
            if hit:
                drop_peers(node, hit)
                said.append(f"Disconnected {', '.join(hit)}.")
    if bad:
        return {"ok": False, "error": " ".join(bad)}
    return {"ok": True, "message": " ".join(said) or "Nothing is linked."}


def drop_peers(node, hit):
    via = node == dashboard_conf()["asl_node"]
    for peer in hit:
        r = dash_call({"action": "disconnect", "node": peer}) if via else None
        if r is None:
            via = False
            drop_link(node, peer)
    _lstats_invalidate()
    if _asl_keep["v"] in hit:
        _asl_keep["v"] = ""
    log_event(f"Disconnect {', '.join(hit)} from node {node}" + (" through Node Controller" if via else ""), "ok")


MMDVM_DIR = os.environ.get("NODERECORDER_MMDVM_DIR", "/var/lib/mmdvm")
TUNE_LIST_FILES = {
    "YSF": (("YSFHosts.txt", "/opt/YSFGateway"),),
    "P25": (("P25Hosts.txt", "/opt/P25Gateway"),),
    "NXDN": (("NXDNHosts.txt", "/opt/NXDNGateway"),),
    "STFU": (("TGList_BM.txt", ""),),
    "DSTAR": (("DPlus_Hosts.txt", ""), ("DExtra_Hosts.txt", ""), ("DCS_Hosts.txt", "")),
}
TUNE_TEXT_MAX = 64
ASTDB_PATH = os.environ.get("NODERECORDER_ASTDB", "/var/lib/asterisk/astdb.txt")
ASL_STATS_URL = "https://stats.allstarlink.org/stats/{}"
SEARCH_MIN = 2
SEARCH_MAX = 200
ECHODB_TTL = 300.0
_echodb = {"t": -1e9, "rows": [], "ok": False}
_echodb_lock = threading.Lock()
_DSTAR_REF_RE = re.compile(r"(REF|XRF|DCS)\d{3}")
_tune_lists = {}
_tune_lists_lock = threading.Lock()


def _host_url(addr):
    addr = str(addr or "").strip()
    if not addr or not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", addr):
        return ""
    return "http://" + (f"[{addr}]" if ":" in addr else addr) + "/"


def _list_text(value):
    return _CALL_TRIM.sub(" ", str(value or "")).strip()[:TUNE_TEXT_MAX]


def _ysf_rows(lines):
    rows, seen = [], set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        p = [_list_text(x) for x in line.split(";")]
        if len(p) < 5 or not re.fullmatch(r"\d{1,5}", p[0]) or not p[1] or not p[4].isdigit():
            continue
        addr = p[3]
        if not addr or any(c.isspace() for c in addr) or not 0 < int(p[4]) < 65536:
            continue
        value = f"{addr}:{int(p[4])}"
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        link = next((x for x in p[6:] if re.fullmatch(r"https?://\S+", x)), "") or _host_url(addr)
        rows.append([value, f"{p[0]} · {p[1]}", link])
    return rows


def _tg_host_rows(lines):
    rows, seen = [], set()
    for raw in lines:
        p = raw.replace("\t", " ").split()
        if len(p) < 3 or p[0].startswith("#") or not p[0].isdigit() or len(p[0]) > 8 or not p[2].isdigit():
            continue
        tg = str(int(p[0]))
        if tg in seen:
            continue
        seen.add(tg)
        rows.append([tg, f"{tg} · {_list_text(p[1])}", _host_url(p[1])])
    return sorted(rows, key=lambda r: int(r[0]))


def _stfu_rows(lines):
    rows, seen = [], set()
    for raw in lines:
        p = [x.strip() for x in raw.split(";")]
        if len(p) < 3 or not p[0].isdigit() or len(p[0]) > 8 or p[1] != "0":
            continue
        tg = str(int(p[0]))
        if tg in seen:
            continue
        seen.add(tg)
        rows.append([tg, f"{tg} · {_list_text(p[2]) or 'TG' + tg}", ""])
    return sorted(rows, key=lambda r: int(r[0]))


def _dstar_rows(lines):
    rows = []
    for raw in lines:
        p = raw.replace("\t", " ").split()
        if len(p) < 2 or not _DSTAR_REF_RE.fullmatch(p[0].upper()):
            continue
        rows.append([p[0].upper(), f"{p[0].upper()} · {_list_text(p[1])}", _host_url(p[1])])
    return rows


def _m17_rows(text):
    try:
        doc = json.loads(text)
    except ValueError:
        return []
    rows, seen = [], set()
    for e in (doc.get("reflectors") if isinstance(doc, dict) else None) or []:
        if not isinstance(e, dict):
            continue
        rid = _list_text(e.get("designator")).upper()
        if not _M17_REF_RE.fullmatch(rid) or rid in seen:
            continue
        if e.get("port") not in (None, "") and str(e.get("port")) != "17000":
            continue
        if not (str(e.get("dns") or "").strip() or str(e.get("ipv4") or "").strip()):
            continue
        seen.add(rid)
        name = _list_text(e.get("name")) or _list_text(e.get("sponsor"))
        url = _list_text(e.get("url")) if str(e.get("url") or "").startswith(("http://", "https://")) else ""
        mods = e.get("modules")
        mods = "".join(sorted({str(x).strip().upper()[:1] for x in mods if str(x).strip()[:1].isalpha()})) \
            if isinstance(mods, list) else re.sub(r"[^A-Z]", "", mods.upper()) if isinstance(mods, str) else ""
        rows.append([rid, rid + (f" · {name}" if name and name.upper() != rid else ""), url, mods])
    return sorted(rows, key=lambda r: r[0])


def _tune_paths(mode):
    if mode == "M17":
        return [M17_HOSTS]
    out = []
    for name, alt in TUNE_LIST_FILES[mode]:
        cands = [os.path.join(MMDVM_DIR, name)] + ([os.path.join(alt, name)] if alt else [])
        out.append(next((p for p in cands if os.path.isfile(p)), ""))
    return [p for p in out if p]


def tune_list(mode):
    try:
        mode = _mode_of(mode)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if mode not in TUNE_LIST_FILES and mode != "M17":
        return {"ok": True, "mode": mode, "found": False, "rows": [], "files": []}
    paths = _tune_paths(mode)
    key = []
    for p in paths:
        try:
            st = os.stat(p)
            key.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    with _tune_lists_lock:
        hit = _tune_lists.get(mode)
        if hit and hit[0] == key:
            return hit[1]
    rows = []
    for p, _m, _s in key:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                if mode == "M17":
                    rows += _m17_rows(fh.read())
                elif mode == "YSF":
                    rows += _ysf_rows(fh)
                elif mode == "STFU":
                    rows += _stfu_rows(fh)
                elif mode == "DSTAR":
                    rows += _dstar_rows(fh)
                else:
                    rows += _tg_host_rows(fh)
        except OSError:
            continue
    out = {"ok": True, "mode": mode, "found": bool(rows), "rows": rows,
           "files": [os.path.basename(p) for p, _m, _s in key]}
    with _tune_lists_lock:
        _tune_lists[mode] = (key, out)
    return out


def _astdb_rows():
    try:
        with open(ASTDB_PATH, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                p = [_list_text(x) for x in raw.strip().split("|")]
                if not p[0].isdigit() or len(p[0]) > 7 or raw.lstrip().startswith(("#", ";")):
                    continue
                num = str(int(p[0]))
                text = " · ".join(x for x in [num] + p[1:4] if x)
                yield num, text, ASL_STATS_URL.format(num)
    except OSError:
        return


def _echodb_rows():
    with _echodb_lock:
        now = time.monotonic()
        if now - _echodb["t"] >= ECHODB_TTL:
            ok, out = ast_cli("echolink dbdump", timeout=10)
            rows, seen = [], set()
            if ok and "no such command" not in out.lower():
                for raw in out.splitlines():
                    p = raw.split("|", 2)
                    if len(p) < 2 or not p[0].strip().isdigit() or len(p[0].strip()) > 6:
                        continue
                    num = str(int(p[0].strip()))
                    if num == "0" or num in seen:
                        continue
                    seen.add(num)
                    rows.append((num, f"{num} · {_list_text(p[1])[:24]}", ""))
                rows.sort(key=lambda r: int(r[0]))
            _echodb.update(t=now, rows=rows, ok=bool(rows))
        return _echodb["rows"], _echodb["ok"]


def tune_search(mode, q):
    try:
        mode = _mode_of(mode)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if mode not in ("ASL", "EchoLink"):
        return {"ok": False, "error": f"{mode} has a list; it is not searched here."}
    q = _CALL_TRIM.sub(" ", str(q or "")).strip().lower()[:40]
    if mode == "ASL":
        found, rows = os.path.isfile(ASTDB_PATH), _astdb_rows()
        what = os.path.basename(ASTDB_PATH)
    else:
        rows, found = _echodb_rows()
        what = "echolink dbdump"
    out = {"ok": True, "mode": mode, "found": found, "file": what, "min": SEARCH_MIN, "count": 0, "rows": []}
    if not found or len(q) < SEARCH_MIN:
        return out
    skip = {v for k, v in bridge_nodes().items() if k in ("digital", "m17") and v} | {REC_NODE}
    words = q.split()
    pre = words[0].lstrip("0") or "0" if len(words) == 1 and words[0].isdigit() else None
    for r in rows:
        if mode == "ASL" and r[0] in skip:
            continue
        if pre is not None:
            if not r[0].startswith(pre):
                continue
        elif not all(w in r[1].lower() for w in words):
            continue
        out["count"] += 1
        if len(out["rows"]) < SEARCH_MAX:
            out["rows"].append(list(r))
    return out


def _tune_fav(b):
    if not isinstance(b, dict):
        raise ValueError("Pick a mode and a station.")
    mode = _mode_of(b.get("mode"))
    num = str(b.get("num", "") or "").strip()
    if not num:
        raise ValueError("Type or pick a node, talkgroup, room or reflector first.")
    if mode == "ASL" and num.isdigit() and str(int(num)) in {v for k, v in bridge_nodes().items() if k in ("digital", "m17") and v}:
        raise ValueError(f"Node {int(num)} is a bridge node; pick a mode to tune it.")
    mod = str(b.get("module", "") or "").strip().upper()
    f = {"mode": mode, "num": num, "net": b.get("net", ""), "label": b.get("label", "")}
    if mode == "DSTAR" and mod and " " not in num and not num.upper().endswith("L"):
        f["num"] = f"{num} {mod}"
    if mode == "M17":
        f["module"] = mod
    return _norm_fav(f, nets_load())


def _tune_connect_impl(b):
    try:
        f = _tune_fav(b)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    node, err = _connect_node()
    if not node:
        return {"ok": False, "error": err}
    if f["mode"] == "M17":
        return m17_connect(f, node)
    if f["mode"] in ("ASL", "EchoLink"):
        return node_connect(f, node)
    act = b.get("net_action")
    return solo_dvs(f, node, act if act in ("add", "once") else None)


def tune_connect(b):
    r = _tune_connect_impl(b)
    try:
        f = _tune_fav(b)
    except ValueError:
        return r
    return _set_active(f, r)


def tune_disconnect(b=None):
    if b is None:
        return _clear_active(None, _tune_disconnect_impl(b))
    try:
        target = fav_target(_tune_fav(b))
    except ValueError:
        return _tune_disconnect_impl(b)
    return _clear_active(target, _tune_disconnect_impl(b))


def _tune_disconnect_impl(b=None):
    node, err = _connect_node()
    if not node:
        return {"ok": False, "error": err}
    if isinstance(b, dict) and _mode_safe(b) in ("ASL", "EchoLink") and b.get("num"):
        try:
            f = _tune_fav(b)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        ok, links = rpt_links(node, max_age=0)
        if not ok:
            return {"ok": False, "error": NO_LINK_LIST}
        if not any(l["node"] == fav_target(f) for l in links):
            return {"ok": True, "message": f"{fav_name(f)} is not linked."}
        drop_peers(node, [fav_target(f)])
        return {"ok": True, "message": f"Disconnected {fav_name(f)}."}
    if not nc_running():
        if not _solo["target"]:
            return {"ok": True, "message": "Nothing is tuned."}
        name = solo_disconnect(node)
        if isinstance(name, dict):
            return name
        _lstats_invalidate()
        return {"ok": True, "message": f"Disconnected {name}."}
    done = []
    d = nc_dvs_current(0)
    if d and d.get("fav"):
        r = dash_call({"action": "dvs-disconnect"}, timeout=60)
        _nc_dvs_status["t"] = -M17_STATUS_TTL
        if r is None or not r["ok"]:
            return {"ok": False, "error": "Node Controller is not answering." if r is None else f"Node Controller: {r['error']}"}
        done.append(tuned_text(d))
    m17 = m17_current(0)
    if m17:
        r = dash_call({"action": "m17-disconnect"})
        _m17_status["t"] = -M17_STATUS_TTL
        if r is None or not r["ok"]:
            return {"ok": False, "error": _m17_error(r)}
        done.append(f"M17 {m17}")
    _lstats_invalidate()
    if not done:
        return {"ok": True, "message": "Nothing is tuned."}
    log_event(f"Disconnect {', '.join(done)} through Node Controller", "ok")
    return {"ok": True, "message": f"Disconnected {', '.join(done)}."}


def tuned_text(d):
    if not d or not d.get("fav"):
        return ""
    page = str(d.get("page", "") or "")
    net = f" {d.get('server')}" if page == "DMR" and d.get("server") else ""
    return f"{MODE_LABEL.get(page, page)}{net} {d['fav']}".strip()[:TUNE_TEXT_MAX * 2]


def _dvs_label(d):
    net = str(d.get("server", "") or "") if str(d.get("page", "") or "") == "DMR" else ""
    return f"{net} {d.get('fav', '')}".strip()


_astdb_names = {"key": None, "map": {}}


def astdb_name(num):
    key = _file_key(ASTDB_PATH)
    if _astdb_names["key"] != key:
        m = {}
        for n, text, _ in _astdb_rows():
            m[n] = " · ".join(text.split(" · ")[1:3])
        _astdb_names.update(key=key, map=m)
    return _astdb_names["map"].get(str(int(num)), "") if str(num).isdigit() else ""


def _bridge_tune(n, nc, dvs, m17_now, dig, m17):
    if nc:
        if n == m17 and m17_now:
            return "M17", m17_now
        if n == dig and dvs.get("fav"):
            return str(dvs.get("page", "") or ""), _dvs_label(dvs)
        return "", ""
    if _solo["target"] and _solo["bridge"] == n:
        return _solo["mode"], _solo["name"]
    return "", ""


def live_link(links, links_ok, nc, favs):
    if not links_ok:
        return {"state": "unreachable", "mode": "", "label": "", "tag": ""}
    if not links:
        return {"state": "none", "mode": "", "label": "", "tag": ""}
    bridges = bridge_nodes(5.0)
    dig, m17 = bridges.get("digital", ""), bridges.get("m17", "")
    linked = {l["node"] for l in links}
    linked_bridge = bool(linked & {dig, m17} - {""})
    dvs = (nc_dvs_current() or {}) if nc and dig in linked else {}
    m17_now = m17_current() if nc and m17 in linked else ""
    infra = {REC_NODE, dig, m17} - {""}

    bridge = None
    for l in links:
        if l["node"] in (dig, m17):
            mode, label = _bridge_tune(l["node"], nc, dvs, m17_now, dig, m17)
            if label:
                m = MODE_LABEL.get(mode, mode).upper()
                text = label[len(m):].strip() if label.upper().split()[:1] == [m] else label
                bridge = (m, text, "linking" if str(l.get("state", "")).upper().startswith("CONN") else "connected")
                break

    asl = [l for l in links if l["node"] not in infra]
    if asl:
        num = asl[0]["node"]
        fav = next((f for f in favs if fav_target(f) == num), None)
        name = (fav or {}).get("label") or astdb_name(num) or f"Node {num}"
        mode = ((fav or {}).get("mode") or "ASL").upper()
        mode = {"ECHOLINK": "ECHO"}.get(mode, mode)
        state = "linking" if str(asl[0].get("state", "")).upper().startswith("CONN") else "connected"
        tag = f"{bridge[0]} {bridge[1]}" if bridge else ""
        return {"state": state, "mode": mode, "label": name, "tag": tag}
    if bridge:
        return {"state": bridge[2], "mode": bridge[0], "label": bridge[1], "tag": ""}
    if linked_bridge:
        return {"state": "idle", "mode": "", "label": "Bridge linked, nothing tuned", "tag": ""}
    return {"state": "noasl", "mode": "", "label": "No ASL node linked", "tag": ""}


def _default_tune_mode(nc):
    if nc:
        page = str((nc_dvs_current() or {}).get("page", "") or "")
        if page:
            return page
    return _solo["mode"] or ""


def tuned_now(nc):
    if not nc:
        return _solo["name"] if _solo["target"] else ""
    m17 = m17_current()
    return " · ".join(x for x in (tuned_text(nc_dvs_current()), f"M17 {m17}" if m17 else "") if x)


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
        host = "noderecorder"
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


def usrp_payload(data):
    if len(data) < USRP_HEADER.size or data[:4] != b"USRP":
        return b"", None
    fields = USRP_HEADER.unpack_from(data)
    pcm = data[USRP_HEADER.size:USRP_HEADER.size + FRAME_BYTES] if fields[5] == 0 else b""
    return pcm, bool(fields[3])


_talker_cache = {"t": 0.0, "active": False}


def talker_installed():
    return os.path.exists(TALKER_UNIT)


def talker_active():
    now = time.monotonic()
    if now - _talker_cache["t"] >= 2.0:
        try:
            active = _svc_active(TALKER_SERVICE)
        except Exception:
            active = False
        _talker_cache.update(t=now, active=active)
    return _talker_cache["active"]


def talker_idle():
    return not talker_active()


def usrp_loop(port, gate):
    while True:
        if gate is not None and not gate():
            time.sleep(2.0)
            continue
        try:
            sock = udp_socket(port)
        except OSError as exc:
            HUB.udp_errors[port] = f"cannot listen on 127.0.0.1:{port}: {exc}"
            log_event(HUB.udp_errors[port] + "; retrying in 10s", "err")
            time.sleep(10)
            continue
        HUB.udp_errors.pop(port, None)
        sock.settimeout(1.0)
        log_event(f"Waiting for node audio on 127.0.0.1:{port}/udp")
        try:
            while gate is None or gate():
                try:
                    data = sock.recv(8192)
                except socket.timeout:
                    continue
                pcm, keyed = usrp_payload(data)
                if keyed is not None:
                    HUB.note_usrp(keyed)
                if pcm:
                    HUB.feed(pcm)
        except OSError as exc:
            log_event(f"UDP receive error: {exc}", "err")
        finally:
            sock.close()
        time.sleep(1)


def _rec_stanza(lines, stanzas):
    for i, s in enumerate(stanzas):
        if s["name"] == REC_NODE:
            end = stanzas[i + 1]["header"] if i + 1 < len(stanzas) else len(lines)
            return s, end
    return None, None


def _rec_note(lines, s):
    h = s["header"]
    return lines[h - 1].strip() if h > 0 else ""


def _rec_owner(lines, s):
    note = _rec_note(lines, s)
    if note == REC_NOTE:
        return "recorder"
    if note in TALKER_NOTES:
        return "talker"
    return ""


def _has_line(lines, want):
    want = _squash(want)
    return any(_squash(ln.strip()) == want for ln in lines)


def _put_nodes_line(lines, nodes_line):
    new = [ln for ln in lines if not _REC_NODES_LINE_RE.match(ln)]
    _, stanzas = parse_rpt("\n".join(new))
    nodes_st = next((x for x in stanzas if x["name"].lower() == "nodes"), None)
    if nodes_st is not None:
        new.insert(nodes_st["header"] + 1, nodes_line)
    else:
        new += ["[nodes]", nodes_line, ""]
    return new


def rec_node_state(main=None):
    out = {"node": REC_NODE, "main": main_node() if main is None else main, "defined": False, "owner": "",
           "nodes_line": False, "ready": False, "linked": None,
           "rxchannel": f"USRP/127.0.0.1:{REC_USRP_IN}:{REC_USRP_OUT}"}
    try:
        lines, stanzas = read_rpt()
    except OSError as exc:
        out["error"] = f"Could not read {RPT_CONF}: {exc}"
        return out
    s, end = _rec_stanza(lines, stanzas)
    if s is not None:
        out["defined"] = True
        out["owner"] = _rec_owner(lines, s)
        body = _squash("\n".join(lines[s["header"]:end]))
        out["rx_ok"] = f"rxchannel={out['rxchannel']}" in body
    out["nodes_line"] = _has_line(lines, rec_nodes_line())
    out["ready"] = out["defined"] and out.get("rx_ok", False) and bool(out["main"]) and out["nodes_line"]
    if out["ready"]:
        ok, links = rpt_links(out["main"])
        out["linked"] = any(l["node"] == REC_NODE for l in links) if ok else None
    return out


def rec_node_enable():
    main = main_node()
    if not main:
        return {"ok": False, "error": "Set the node first (the Dashboard's node number)."}
    with _rpt_lock:
        lines, stanzas = read_rpt()
        s, _ = _rec_stanza(lines, stanzas)
        if s is not None:
            owner = _rec_owner(lines, s)
            if owner == "talker":
                return {"ok": True, "changed": False,
                        "message": f"Node {REC_NODE} belongs to Node Talker. Node Recorder records from it."}
            if owner != "recorder":
                return {"ok": False, "error": f"rpt.conf already has a [{REC_NODE}] node that Node Recorder didn't add. Remove it or pick another node."}
            want = rec_nodes_line()
            if _has_line(lines, want):
                return {"ok": True, "changed": False, "message": f"Node {REC_NODE} is already set up."}
            try:
                backup = _write_rpt(_put_nodes_line(lines, want))
            except OSError as exc:
                return _write_failed(exc)
            log_event(f"rpt.conf: fixed the [nodes] line for node {REC_NODE}: {want} (backup {backup})", "ok")
            return _changed(backup, f"Fixed the [nodes] line for node {REC_NODE} ({want}). Restart Asterisk.")
        main_st = _find_stanza(stanzas, main)
        if main_st is None:
            return {"ok": False, "error": f"Node {main} is not in {RPT_CONF}."}
        tpl = f"({','.join(main_st['templates'])})" if main_st["templates"] else ""
        block = ["", REC_NOTE, f"[{REC_NODE}]{tpl}", f"rxchannel = USRP/127.0.0.1:{REC_USRP_IN}:{REC_USRP_OUT}",
                 "duplex = 0", "hangtime = 0", "althangtime = 0", "holdofftelem = 1", "telemdefault = 0",
                 "nounkeyct = 1", "idrecording = |t(0,0,10,0)"]
        new = list(lines)
        while new and new[-1].strip() == "":
            new.pop()
        new += block + [""]
        try:
            backup = _write_rpt(_put_nodes_line(new, rec_nodes_line()))
        except OSError as exc:
            return _write_failed(exc)
    log_event(f"rpt.conf: added node {REC_NODE} for node {main} (backup {backup})", "ok")
    return _changed(backup, f"Added node {REC_NODE}. Restart Asterisk, then Node Recorder links it to node {main}."
                    + allmon_follow([REC_NODE], [], main))


def rec_node_unlink(why):
    main = main_node()
    if not main:
        return
    ok, links = rpt_links(main, max_age=0)
    if ok and any(l["node"] == REC_NODE for l in links):
        ilink(main, 1, REC_NODE)
        log_event(f"Unlinked node {REC_NODE} from node {main} ({why})", "ok")


def rec_node_disable():
    with _rpt_lock:
        lines, stanzas = read_rpt()
        s, end = _rec_stanza(lines, stanzas)
        owner = _rec_owner(lines, s) if s is not None else ""
        if owner == "recorder" and talker_installed():
            new = list(lines)
            new[s["header"] - 1] = TALKER_NOTE
            try:
                backup = _write_rpt(new)
            except OSError as exc:
                return _write_failed(exc)
            log_event(f"rpt.conf: handed node {REC_NODE} to Node Talker (backup {backup})", "ok")
            return _changed(backup, f"Node {REC_NODE} stays in rpt.conf for Node Talker.")
    if owner != "recorder":
        return {"ok": True, "changed": False, "message": f"Node Recorder has no node {REC_NODE} in rpt.conf."}
    rec_node_unlink("node removed")
    with _rpt_lock:
        lines, stanzas = read_rpt()
        s, end = _rec_stanza(lines, stanzas)
        drop = set()
        if s is not None and _rec_owner(lines, s) == "recorder":
            drop.update(range(s["header"] - 1, end))
        for i, ln in enumerate(lines):
            if _REC_NODES_LINE_RE.match(ln):
                drop.add(i)
        if not drop:
            return {"ok": True, "changed": False, "message": f"Node Recorder has no node {REC_NODE} in rpt.conf."}
        new = [ln for i, ln in enumerate(lines) if i not in drop]
        while len(new) > 1 and new[-1].strip() == "" and new[-2].strip() == "":
            new.pop()
        try:
            backup = _write_rpt(new)
        except OSError as exc:
            return _write_failed(exc)
    log_event(f"rpt.conf: removed node {REC_NODE} (backup {backup})", "ok")
    return _changed(backup, f"Removed node {REC_NODE}. Restart Asterisk for it to take effect."
                    + allmon_follow([], [REC_NODE]))


def link_keeper_loop():
    last = None
    while True:
        time.sleep(20)
        try:
            if talker_active():
                last = None
                continue
            st = rec_node_state()
            if not st["ready"] or st["linked"] is None or st["owner"] != "recorder":
                continue
            if st["linked"]:
                if last is False:
                    log_event(f"Node {REC_NODE} is linked to node {st['main']} again", "ok")
                last = True
                continue
            ok, out = ilink(st["main"], 3, REC_NODE)
            if last is not False:
                log_event(f"Node {REC_NODE} was not linked to node {st['main']}; linking it"
                          + ("" if ok else f" failed: {out.strip()[:120]}"), "warn")
            last = False
        except Exception as exc:
            log_event(f"Link keeper error: {exc}", "err")


PIBRARY_CONF = os.environ.get("NODERECORDER_PIBRARY_CONF", "/etc/pibrary/pibrary.conf")
PROC_MOUNTS = os.environ.get("NODERECORDER_PROC_MOUNTS", "/proc/mounts")
SYS_BLOCK = os.environ.get("NODERECORDER_SYS_BLOCK", "/sys/class/block")
RECORD_DEFAULT_ROOT = "/srv/pibrary/media"
RECORD_SUBDIR = os.path.join("audio", "recordings")
RECORD_RESERVE_BYTES = 50 * 1024 * 1024
RECORD_QUEUE_FRAMES = 500
RECORD_SYNC_SEC = 10.0
RECORD_HEADER_SEC = 10.0
RECORD_CLOSE_SEC = 20.0
_REC_NAME_RE = re.compile(r"^\d{8}-\d{6}_[A-Za-z0-9._-]{1,48}\.(wav|mp3|opus|flac)$")
ENCODE_JOB_SEC = 7200
ENCODER_INSTALL_SEC = 900


def pibrary_storage():
    out = {"root": "", "usb_uuid": ""}
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(PIBRARY_CONF)
    except configparser.Error:
        return out
    if cp.has_section("pibrary"):
        out["root"] = cp.get("pibrary", "library_root", fallback="").strip()
        out["usb_uuid"] = cp.get("pibrary", "usb_uuid", fallback="").strip()
    return out


def _mount_table():
    rows = []
    try:
        with open(PROC_MOUNTS, "r", encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                p = ln.split()
                if len(p) >= 3:
                    rows.append((p[0], p[1].replace("\\040", " "), p[2]))
    except OSError:
        pass
    return rows


def _dev_kind(dev):
    if not dev.startswith("/dev/"):
        return "other"
    name = os.path.basename(os.path.realpath(dev))
    if name.startswith("mmcblk"):
        return "sd"
    try:
        real = os.path.realpath(os.path.join(SYS_BLOCK, name))
    except OSError:
        return "other"
    return "usb" if "/usb" in real else "other"


def _existing_ancestor(path):
    p = os.path.realpath(path)
    while p and not os.path.exists(p) and p != "/":
        p = os.path.dirname(p)
    return p or "/"


def fs_kind(path):
    real = _existing_ancestor(path)
    best = None
    for dev, mp, _fs in _mount_table():
        if real == mp or real.startswith(mp.rstrip("/") + "/") or mp == "/":
            if best is None or len(mp) >= len(best[1]):
                best = (dev, mp)
    if best is None:
        return "other", "", ""
    return _dev_kind(best[0]), best[1], best[0]


def usb_mounts():
    seen, out = set(), []
    for dev, mp, _fs in _mount_table():
        if mp not in seen and _dev_kind(dev) == "usb":
            seen.add(mp)
            out.append(mp)
    return out


def storage_pick():
    pib = pibrary_storage()
    pib_root = pib["root"]
    usb = usb_mounts()
    own = _cfg_get("record_path")
    out = {"recorder_path": own, "pibrary_root": pib_root,
           "pibrary_path": os.path.join(pib_root, RECORD_SUBDIR) if pib_root else "",
           "usb_mounts": usb, "path": "", "source": "", "kind": "", "mount": "", "ok": False, "reason": "", "conflict": False}
    if own:
        path, source = own, "the Recordings folder setting"
        out["conflict"] = bool(out["pibrary_path"]) and os.path.normpath(out["pibrary_path"]) != os.path.normpath(own)
    else:
        base = pib_root or RECORD_DEFAULT_ROOT
        if fs_kind(base)[0] == "usb":
            path, source = os.path.join(base, RECORD_SUBDIR), "the Pibrary library on a USB drive"
        elif usb:
            path, source = os.path.join(usb[0], "pibrary", RECORD_SUBDIR), f"the USB drive at {usb[0]}"
        else:
            path = os.path.join(base, RECORD_SUBDIR)
            source = "the Pibrary library" if pib_root else "the default folder"
    kind, mount, _dev = fs_kind(path)
    out.update(path=path, source=source, kind=kind, mount=mount)
    if kind == "sd" and usb:
        out["reason"] = (f"{path} is on the SD card while a USB drive ({usb[0]}) is mounted, and recordings never go to the SD card "
                         "when a USB drive is available. Point the Recordings folder at the USB drive, or leave it empty.")
        return out
    out["ok"] = True
    return out


def recordings_list(d):
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if _REC_NAME_RE.match(n):
            p = os.path.join(d, n)
            if os.path.isfile(p) and not os.path.islink(p):
                try:
                    out.append((n, os.path.getsize(p)))
                except OSError:
                    pass
    out.sort()
    return out


def retention_enforce(d, need):
    cap_mb = int(_cfg_get("record_max_mb"))
    files = recordings_list(d)
    budget = cap_mb * 1024 * 1024 - need
    total = sum(f[1] for f in files)
    removed = 0
    with _enc_lock:
        busy = set(_enc["pending"])
    for name, size in files:
        if total <= budget:
            break
        if os.path.join(d, name) in busy:
            continue
        try:
            os.remove(os.path.join(d, name))
        except OSError as exc:
            log_event(f"Retention: could not remove {name}: {exc}", "warn")
            continue
        total -= size
        removed += 1
        log_event(f"Retention: removed the oldest recording {name} to stay within {cap_mb} MB", "info")
    if total > budget and need:
        log_event(f"Retention: this window alone needs more than the {cap_mb} MB cap allows", "warn")
    return removed


def storage_view():
    pick = storage_pick()
    path = pick["path"]
    out = dict(pick, ok=True, cap_mb=int(_cfg_get("record_max_mb")), free=None, total=None, files=0, bytes=0)
    out["usable"] = pick["ok"]
    out["ok"] = True
    try:
        st = os.statvfs(_existing_ancestor(path))
        out["free"], out["total"] = st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize
    except OSError:
        pass
    files = recordings_list(path)
    out["files"], out["bytes"] = len(files), sum(f[1] for f in files)
    return out


def wav_header(fmt, data_bytes, samples):
    if fmt == "ulaw":
        body = struct.pack("<HHIIHHH", 7, 1, 8000, 8000, 1, 8, 0)
        return (b"RIFF" + struct.pack("<I", 50 + data_bytes) + b"WAVEfmt " + struct.pack("<I", 18) + body
                + b"fact" + struct.pack("<II", 4, samples) + b"data" + struct.pack("<I", data_bytes))
    body = struct.pack("<HHIIHH", 1, 1, 8000, 16000, 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVEfmt " + struct.pack("<I", 16) + body + b"data" + struct.pack("<I", data_bytes)


def repair_recording(path):
    try:
        with open(path, "r+b") as fh:
            head = fh.read(96)
            if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return False
            pos, tag, data_off, size_pos = 12, None, None, None
            while pos + 8 <= len(head):
                cid = head[pos:pos + 4]
                csz = struct.unpack_from("<I", head, pos + 4)[0]
                if cid == b"fmt " and pos + 10 <= len(head):
                    tag = struct.unpack_from("<H", head, pos + 8)[0]
                elif cid == b"data":
                    data_off, size_pos = pos + 8, pos + 4
                    break
                pos += 8 + csz + (csz & 1)
            if tag not in (1, 7) or data_off is None:
                return False
            fmt = "ulaw" if tag == 7 else "pcm"
            if data_off != len(wav_header(fmt, 0, 0)):
                return False
            actual = os.fstat(fh.fileno()).st_size - data_off
            if fmt == "pcm":
                actual -= actual % 2
            if struct.unpack_from("<I", head, size_pos)[0] == actual:
                return False
            fh.seek(0)
            fh.write(wav_header(fmt, actual, actual if fmt == "ulaw" else actual // 2))
            fh.flush()
            os.fsync(fh.fileno())
            return True
    except OSError:
        return False


def repair_recordings(d):
    fixed = 0
    for name, _size in recordings_list(d):
        if not name.endswith(".wav"):
            continue
        if repair_recording(os.path.join(d, name)):
            fixed += 1
            log_event(f"Repaired the header of {name} (it was not closed cleanly)", "warn")
    return fixed


def _ulaw_decode_table():
    out = array.array("h")
    for b in range(256):
        c = ~b & 0xFF
        t = (((c & 0x0F) << 3) + 0x84) << ((c & 0x70) >> 4)
        out.append(0x84 - t if c & 0x80 else t - 0x84)
    return out


ULAW_DECODE = _ulaw_decode_table()


def _enc_lame(exe, kbps, out):
    return [exe, "--quiet", "-r", "-s", "8", "--signed", "--little-endian", "--bitwidth", "16", "-m", "m",
            "--resample", "16", "--cbr", "-b", str(kbps), "-", out], "raw"


def _enc_sox(exe, kbps, out):
    return [exe, "-q", "-t", "raw", "-r", "8000", "-e", "signed-integer", "-b", "16", "-c", "1", "-",
            "-t", "mp3", "-r", "16000", "-C", str(kbps), out], "raw"


def _enc_shine(exe, kbps, out):
    return [exe, "-q", "-m", "-b", str(kbps), "-", out], "wav"


def _enc_opus(exe, kbps, out):
    return [exe, "--quiet", "--raw", "--raw-rate", "8000", "--raw-chan", "1", "--raw-bits", "16",
            "--bitrate", str(kbps), "-", out], "raw"


def _enc_flac(exe, kbps, out):
    return [exe, "--silent", "-f", "--force-raw-format", "--endian=little", "--sign=signed", "--channels=1",
            "--bps=16", "--sample-rate=8000", "-o", out, "-"], "raw"


ENCODERS = {
    "lame": {"label": "lame (MP3)", "bin": "lame", "pkgs": "lame", "ext": ".mp3", "kbps": True, "build": _enc_lame,
             "note": "Recommended. Small (about 1 MB), well tested on the Pi, and the MP3 plays in every browser and phone. "
                     "Voice is resampled to 16 kHz mono."},
    "sox": {"label": "sox (MP3)", "bin": "sox", "pkgs": "sox libsox-fmt-mp3", "ext": ".mp3", "kbps": True, "build": _enc_sox,
            "note": "Also makes MP3, but needs the extra libsox-fmt-mp3 package. Choose it if sox is already on the node for other jobs."},
    "shine": {"label": "shine (MP3)", "bin": "shineenc", "pkgs": "shineenc", "ext": ".mp3", "kbps": True, "build": _enc_shine,
              "note": "A fixed-point MP3 encoder: the lightest on the CPU of the Pi Zero 2 W. It keeps the 8 kHz rate, "
                      "so a few players may not play the file, and it is not in every repository."},
    "opus": {"label": "opusenc (Opus)", "bin": "opusenc", "pkgs": "opus-tools", "ext": ".opus", "kbps": True, "build": _enc_opus,
             "note": "Much smaller files for the same voice quality (24 kbps sounds good). Pibrary plays .opus, "
                     "but not every phone or player does."},
    "flac": {"label": "flac (FLAC)", "bin": "flac", "pkgs": "flac", "ext": ".flac", "kbps": False, "build": _enc_flac,
             "note": "Lossless: nothing is lost, and the file is about half the size of the WAV. "
                     "The quality setting does not apply."},
}
ENCODER_IDS = tuple(ENCODERS)


def encoder_path(key=None):
    return shutil.which(ENCODERS[key or _cfg_get("record_encoder")]["bin"])


_enc_versions = {}


def encoder_version(key):
    exe = encoder_path(key)
    if not exe or key == "shine":
        return ""
    try:
        stamp = (exe, os.stat(exe).st_mtime_ns)
    except OSError:
        return ""
    hit = _enc_versions.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    flag = "-V" if key == "flac" else "--version"
    ver = ""
    try:
        r = subprocess.run([exe, flag], capture_output=True, text=True, timeout=10)
        text = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        ver = text[0].split(" (http")[0].strip()[:60] if text else ""
    except (OSError, subprocess.TimeoutExpired):
        ver = ""
    _enc_versions[key] = (stamp, ver)
    return ver


def wav_layout(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(96)
            size = os.fstat(fh.fileno()).st_size
    except OSError:
        return None
    if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return None
    pos, tag = 12, None
    while pos + 8 <= len(head):
        cid = head[pos:pos + 4]
        csz = struct.unpack_from("<I", head, pos + 4)[0]
        if cid == b"fmt " and pos + 10 <= len(head):
            tag = struct.unpack_from("<H", head, pos + 8)[0]
        elif cid == b"data":
            if tag not in (1, 7):
                return None
            return ("ulaw" if tag == 7 else "pcm"), pos + 8, max(0, size - (pos + 8))
        pos += 8 + csz + (csz & 1)
    return None


def _enc_stderr(f):
    try:
        f.seek(0)
        return f.read(65536).decode("utf-8", "replace").strip()
    except (OSError, ValueError):
        return ""


def encode_file(wav, key, kbps):
    enc = ENCODERS[key]
    exe = encoder_path(key)
    if not exe:
        return False, f"{enc['bin']} is not installed"
    lay = wav_layout(wav)
    if lay is None:
        return False, "not a recording Node Recorder wrote"
    fmt, off, nbytes = lay
    if fmt == "pcm":
        nbytes -= nbytes % 2
    if nbytes <= 0:
        return False, "the recording holds no audio"
    base = wav[:-4]
    out = base + enc["ext"]
    n = 1
    while os.path.exists(out):
        n += 1
        out = f"{base}-{n}{enc['ext']}"
    tmp = out + ".part"
    cmd, mode = enc["build"](exe, kbps, tmp)
    nice = shutil.which("nice")
    if nice:
        cmd = [nice, "-n", "19"] + cmd
    errf = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errf)
    except OSError as exc:
        errf.close()
        return False, f"could not run {enc['bin']}: {exc}"
    timer = threading.Timer(ENCODE_JOB_SEC, proc.kill)
    timer.start()
    err = ""
    try:
        if mode == "wav":
            data_len = nbytes * 2 if fmt == "ulaw" else nbytes
            proc.stdin.write(b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVEfmt "
                             + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
                             + b"data" + struct.pack("<I", data_len))
        with open(wav, "rb") as fh:
            fh.seek(off)
            left = nbytes
            while left > 0:
                chunk = fh.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
                if fmt == "ulaw":
                    pcm = array.array("h", map(ULAW_DECODE.__getitem__, chunk))
                    if sys.byteorder == "big":
                        pcm.byteswap()
                    chunk = pcm.tobytes()
                proc.stdin.write(chunk)
        proc.stdin.close()
        rc = proc.wait()
        err = _enc_stderr(errf)
    except (OSError, ValueError) as exc:
        proc.kill()
        proc.wait()
        _remove_quiet(tmp)
        detail = _enc_stderr(errf)
        return False, f"conversion failed: {exc}" + (f" ({detail[:200]})" if detail else "")
    finally:
        timer.cancel()
        errf.close()
    try:
        ok = rc == 0 and os.path.getsize(tmp) > 0
    except OSError:
        ok = False
    if not ok:
        _remove_quiet(tmp)
        return False, f"{enc['bin']} failed" + (f": {err[:200]}" if err else f" (exit {rc})")
    try:
        os.replace(tmp, out)
        os.remove(wav)
    except OSError as exc:
        _remove_quiet(tmp)
        return False, f"could not finish {os.path.basename(wav)}: {exc}"
    return True, os.path.basename(out)


_enc = {"q": queue.Queue(), "pending": set(), "current": "", "done": 0, "failed": 0, "last": "", "thread": None}
_enc_lock = threading.Lock()


def _enc_worker():
    while True:
        wav = _enc["q"].get()
        with _enc_lock:
            _enc["current"] = os.path.basename(wav)
        try:
            if _cfg_get("record_convert") and os.path.isfile(wav):
                ok, msg = encode_file(wav, _cfg_get("record_encoder"), _cfg_get("record_kbps"))
                name = os.path.basename(wav)
                with _enc_lock:
                    _enc["done" if ok else "failed"] += 1
                    _enc["last"] = f"{name} -> {msg}" if ok else f"{name}: {msg}"
                if ok:
                    log_event(f"Converted {name} to {msg} (the WAV was deleted)", "ok")
                else:
                    log_event(f"Could not convert {name}: {msg} (the WAV was kept)", "warn")
        finally:
            with _enc_lock:
                _enc["pending"].discard(wav)
                _enc["current"] = ""


def enc_enqueue(wav):
    if not _cfg_get("record_convert") or not wav.endswith(".wav") or not encoder_path():
        return False
    with _enc_lock:
        if wav in _enc["pending"]:
            return False
        _enc["pending"].add(wav)
        if _enc["thread"] is None or not _enc["thread"].is_alive():
            _enc["thread"] = threading.Thread(target=_enc_worker, name="enc-worker", daemon=True)
            _enc["thread"].start()
    _enc["q"].put(wav)
    return True


def enc_sweep(d):
    if not _cfg_get("record_convert") or not encoder_path():
        return 0
    a = ENGINE.a
    skip = a["path"] if a else ""
    n = 0
    for name, _size in recordings_list(d):
        p = os.path.join(d, name)
        if name.endswith(".wav") and p != skip and enc_enqueue(p):
            n += 1
    return n


_enc_job = {"running": False, "key": "", "lines": deque(maxlen=400), "rc": None}
_enc_job_lock = threading.Lock()


def _enc_install_run(key):
    pkgs = ENCODERS[key]["pkgs"]
    script = ("export DEBIAN_FRONTEND=noninteractive; "
              "echo '$ apt-get update'; apt-get update -q -o DPkg::Lock::Timeout=120 || exit 1; echo; "
              f"echo '$ apt-get install -y --no-install-recommends {pkgs}'; "
              f"apt-get install -y --no-install-recommends -o DPkg::Lock::Timeout=120 {pkgs} || exit 1")
    cmd = ["sh", "-c", script]
    tmo = shutil.which("timeout")
    if tmo:
        cmd = [tmo, str(ENCODER_INSTALL_SEC)] + cmd
    rc = 1
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                text=True, errors="replace")
        for line in proc.stdout:
            with _enc_job_lock:
                _enc_job["lines"].append(line.rstrip("\n")[:300])
        rc = proc.wait()
    except OSError as exc:
        with _enc_job_lock:
            _enc_job["lines"].append(f"could not run apt-get: {exc}")
    found = bool(encoder_path(key))
    with _enc_job_lock:
        _enc_job["lines"].append("")
        _enc_job["lines"].append(f"{key} is installed." if found else f"{key} is not installed (exit {rc}).")
        _enc_job["rc"] = rc
        _enc_job["running"] = False
    if found:
        log_event(f"{ENCODERS[key]['bin']} installed from the Setup tab", "ok")
        try:
            enc_sweep(storage_pick()["path"])
        except OSError:
            pass
    else:
        log_event(f"{ENCODERS[key]['bin']} install failed (exit {rc})", "err")


def encoder_install(body):
    key = str((body or {}).get("encoder", "")).strip()
    if key not in ENCODERS:
        return {"ok": False, "error": "Pick one of: " + ", ".join(ENCODER_IDS) + "."}
    if os.geteuid() != 0:
        return {"ok": False, "error": "Installing needs root: run Node Recorder as root."}
    if encoder_path(key):
        return {"ok": True, "message": f"{ENCODERS[key]['bin']} is already installed."}
    with _enc_job_lock:
        if _enc_job["running"]:
            return {"ok": False, "error": "An install is already running."}
        _enc_job.update(running=True, key=key, rc=None)
        _enc_job["lines"].clear()
    threading.Thread(target=_enc_install_run, args=(key,), name="enc-install", daemon=True).start()
    return {"ok": True, "message": f"Installing {ENCODERS[key]['pkgs']}..."}


def encoder_view():
    with _enc_job_lock:
        job = {"running": _enc_job["running"], "key": _enc_job["key"], "rc": _enc_job["rc"], "lines": list(_enc_job["lines"])}
    with _enc_lock:
        st = {"queued": len(_enc["pending"]), "current": _enc["current"], "done": _enc["done"],
              "failed": _enc["failed"], "last": _enc["last"]}
    encs = [{"id": k, "label": v["label"], "note": v["note"], "pkgs": v["pkgs"], "ext": v["ext"], "kbps": v["kbps"],
             "installed": bool(encoder_path(k)), "version": encoder_version(k)} for k, v in ENCODERS.items()]
    return {"ok": True, "enabled": _cfg_get("record_convert"), "encoder": _cfg_get("record_encoder"),
            "kbps": _cfg_get("record_kbps"), "kbps_choices": list(MP3_KBPS), "encoders": encs, "job": job, "convert": st}


class RecordingEngine:
    def __init__(self):
        self.lock = threading.Lock()
        self.a = None
        self.closing = None

    def feed(self, pcm):
        a = self.a
        if a is None:
            return
        try:
            a["q"].put_nowait(pcm)
        except queue.Full:
            a["dropped"] += 1

    def healthy(self):
        a = self.a
        if a is None:
            return True, ""
        if a["error"]:
            return False, a["error"]
        if not a["thread"].is_alive():
            return False, "the recording writer stopped"
        return True, ""

    def start(self, entry, window):
        with self.lock:
            if self.a is not None:
                return False, "a recording is already open", None
            if self.closing is not None and self.closing.is_alive():
                return False, "the previous recording is still closing", None
            pick = storage_pick()
            if not pick["ok"]:
                return False, pick["reason"], None
            d = pick["path"]
            fmt = entry["format"]
            secs = max(60.0, (window[1] - datetime.now()).total_seconds()) if window else 3600.0
            need = int(secs * (8000 if fmt == "ulaw" else 16000))
            try:
                os.makedirs(d, exist_ok=True)
            except OSError as exc:
                return False, f"cannot create {d}: {exc}", None
            repair_recordings(d)
            enc_sweep(d)
            retention_enforce(d, need)
            try:
                st = os.statvfs(d)
            except OSError as exc:
                return False, f"cannot check the free space in {d}: {exc}", None
            free = st.f_bavail * st.f_frsize
            if free < need + RECORD_RESERVE_BYTES:
                return False, (f"not enough free space in {d}: {free // 1048576} MB free, "
                               f"{(need + RECORD_RESERVE_BYTES) // 1048576} MB needed for this window"), None
            slug = re.sub(r"[^A-Za-z0-9._-]+", "-", entry["name"]).strip("-.")[:48] or "recording"
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"{stamp}_{slug}.wav"
            n = 1
            while any(os.path.exists(os.path.join(d, name[:-4] + e)) for e in (".wav", ".mp3", ".opus", ".flac")):
                n += 1
                name = f"{stamp}_{slug}-{n}.wav"
            path = os.path.join(d, name)
            try:
                fh = open(path, "xb", buffering=65536)
                fh.write(wav_header(fmt, 0, 0))
                fh.flush()
            except OSError as exc:
                return False, f"cannot create {path}: {exc}", None
            a = {"q": queue.Queue(RECORD_QUEUE_FRAMES), "fh": fh, "path": path, "name": name, "dir": d, "fmt": fmt,
                 "bytes": 0, "samples": 0, "dropped": 0, "error": "", "thread": None, "t0": time.monotonic(),
                 "stop": threading.Event()}
            a["thread"] = threading.Thread(target=self._writer, args=(a,), name="rec-writer", daemon=True)
            self.a = a
            a["thread"].start()
            HUB.recorder = self
        log_event(f"Recording started: {path} ({'u-law' if fmt == 'ulaw' else 'PCM'})", "ok")
        return True, f"recording to {path}", name

    def _patch(self, a):
        fh = a["fh"]
        fh.flush()
        fh.seek(0)
        fh.write(wav_header(a["fmt"], a["bytes"], a["samples"]))
        fh.flush()
        fh.seek(0, 2)

    def _writer(self, a):
        fh, q, ulaw = a["fh"], a["q"], a["fmt"] == "ulaw"
        last_sync = last_hdr = time.monotonic()
        try:
            while True:
                try:
                    pcm = q.get(timeout=1.0)
                except queue.Empty:
                    pcm = b""
                if pcm:
                    data = ulaw_encode(pcm) if ulaw else pcm
                    fh.write(data)
                    a["bytes"] += len(data)
                    a["samples"] += len(pcm) // 2
                elif a["stop"].is_set() and q.empty():
                    break
                now = time.monotonic()
                if now - last_hdr >= RECORD_HEADER_SEC:
                    self._patch(a)
                    last_hdr = now
                if now - last_sync >= RECORD_SYNC_SEC:
                    fh.flush()
                    os.fsync(fh.fileno())
                    last_sync = now
            self._patch(a)
            os.fsync(fh.fileno())
        except (OSError, ValueError) as exc:
            a["error"] = f"writing {a['name']} failed: {exc}"
            if HUB.recorder is self:
                HUB.recorder = None
            log_event(a["error"], "err")
        finally:
            try:
                fh.close()
            except (OSError, ValueError):
                pass

    def stop(self):
        with self.lock:
            a = self.a
            if a is None:
                return True, "no recording was open", None
            self.a = None
            if HUB.recorder is self:
                HUB.recorder = None
            a["stop"].set()
            a["thread"].join(RECORD_CLOSE_SEC)
            alive = a["thread"].is_alive()
            if alive:
                self.closing = a["thread"]
        secs = a["samples"] / 8000.0
        if alive:
            msg = (f"{a['name']} did not close within {int(RECORD_CLOSE_SEC)} s; the drive is slow. "
                   "It is kept, still closing in the background, and converted at the next window")
            log_event(msg, "err")
            return False, msg, None
        removed = retention_enforce(a["dir"], 0)
        note = f", {a['dropped']} frames dropped" if a["dropped"] else ""
        if a["error"]:
            return False, f"{a['error']} (kept {a['name']}, {round(secs)} s)", None
        log_event(f"Recording saved: {a['name']} ({round(secs)} s, {a['bytes'] / 1048576:.1f} MB{note})", "ok")
        enc_enqueue(a["path"])
        return True, f"saved {a['name']} ({round(secs)} s, {a['bytes'] / 1048576:.1f} MB{note})" + (f"; removed {removed} old" if removed else ""), None


ENGINE = RecordingEngine()


SCHEDULE_PATH = os.path.join(CONFIG_DIR, "schedule.json")
SCHEDULE_STATE_PATH = os.path.join(CONFIG_DIR, "schedule_state.json")
SCHEDULE_MAX = 40
SCHEDULE_GAP_MIN = 2
SCHEDULE_FORMATS = ("ulaw", "pcm")
SCHEDULE_NAME_MAX = 40
SCHEDULE_DAY_NAMES = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
STEP_TIMEOUT = {"connect": 120, "start": 15, "stop": 30, "disconnect": 60}
LINK_CHECK_SEC = 5
LINK_LOST_CHECKS = 2
MISSED_LOOKBACK = timedelta(hours=24)
ENGINE_READY = True
_sched_lock = threading.RLock()
_sched_cache = {"key": None, "data": None}
_ENTRY_ID_RE = re.compile(r"^[a-z0-9]{1,16}$")
_HM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _hm_minutes(value, what):
    m = _HM_RE.match(str(value or "").strip())
    if not m:
        raise ValueError(f"{what} must be a time such as 06:30")
    return int(m.group(1)) * 60 + int(m.group(2))


def _hm_text(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _norm_days(raw):
    if raw == "*":
        return list(range(7))
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    days = set()
    for x in raw:
        try:
            d = int(x)
        except (TypeError, ValueError):
            raise ValueError("days must be 0 (Sunday) to 6 (Saturday)")
        if not 0 <= d <= 6:
            raise ValueError("days must be 0 (Sunday) to 6 (Saturday)")
        days.add(d)
    if not days:
        raise ValueError("Pick at least one day")
    return sorted(days)


def _target_keys(f):
    return {k: f[k] for k in ("mode", "num", "module", "net", "label") if k in f}


def schedule_norm_entry(raw, check_target=True):
    if not isinstance(raw, dict):
        raise ValueError("bad schedule entry")
    start = _hm_minutes(raw.get("start"), "Start")
    end = _hm_minutes(raw.get("end"), "End")
    if start == end:
        raise ValueError("Start and end must differ")
    if check_target:
        try:
            target = _target_keys(_tune_fav(raw.get("target")))
        except ValueError as exc:
            msg = str(exc)
            if "DMR network list" in msg:
                msg += ". Add the network on the Setup tab (Digital card), or use Copy from Node Controller there."
            raise ValueError(msg)
    else:
        t = raw.get("target")
        if not isinstance(t, dict) or not t.get("mode") or not t.get("num"):
            raise ValueError("bad target")
        target = _target_keys(t)
    fmt = str(raw.get("format", "ulaw") or "ulaw").strip().lower()
    if fmt not in SCHEDULE_FORMATS:
        raise ValueError("format must be ulaw or pcm")
    eid = str(raw.get("id") or "").strip().lower() or secrets.token_hex(4)
    if not _ENTRY_ID_RE.match(eid):
        raise ValueError("bad entry id")
    name = _CALL_TRIM.sub(" ", str(raw.get("name") or "")).strip()[:SCHEDULE_NAME_MAX]
    if not name:
        name = fav_name(target) if check_target else str(target.get("label") or target.get("num"))
    rev = str(raw.get("rev") or "")
    try:
        datetime.fromisoformat(rev)
    except ValueError:
        rev = ""
    kind = str(raw.get("kind") or "regular").strip().lower()
    if kind not in ("regular", "special"):
        raise ValueError("kind must be regular or special")
    date = ""
    if kind == "special":
        date = str(raw.get("date") or "").strip()
        if not _DATE_RE.match(date):
            raise ValueError("a special needs a date such as 2026-11-30")
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("a special needs a real date such as 2026-11-30")
        days = []
    else:
        days = _norm_days(raw.get("days", raw.get("day")))
    return {"id": eid, "name": name, "enabled": _parse_bool(raw.get("enabled", True)),
            "days": days, "start": _hm_text(start), "end": _hm_text(end),
            "duration_min": (end - start) % 1440, "target": target, "format": fmt, "rev": rev,
            "kind": kind, "date": date}


def _special_window(e):
    s = datetime.fromisoformat(e["date"]) + timedelta(minutes=_hm_minutes(e["start"], "Start"))
    return s, s + timedelta(minutes=e["duration_min"])


def _sched_pieces(e, gap):
    out = []
    start = _hm_minutes(e["start"], "Start")
    for d in e["days"]:
        s = d * 1440 + start
        t = s + e["duration_min"] + gap
        if t <= 10080:
            out.append((s, t, d))
        else:
            out.append((s, 10080, d))
            out.append((0, t - 10080, d))
    return out


def schedule_conflicts(entries):
    items = []
    for e in entries:
        if e.get("enabled") and e.get("kind") != "special":
            for p in _sched_pieces(e, SCHEDULE_GAP_MIN):
                items.append((e, p))
    seen, out = set(), []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (ea, pa), (eb, pb) = items[i], items[j]
            if ea["id"] == eb["id"] and pa[2] == pb[2]:
                continue
            if pa[0] < pb[1] and pb[0] < pa[1]:
                key = tuple(sorted((ea["id"], eb["id"])))
                if key not in seen:
                    seen.add(key)
                    if ea["id"] == eb["id"]:
                        out.append(f"{ea['name']} runs into its own next window; shorten it")
                    else:
                        out.append(f"{ea['name']} and {eb['name']} overlap or are less than {SCHEDULE_GAP_MIN} minutes apart")
    gap = timedelta(minutes=SCHEDULE_GAP_MIN)
    sps = [e for e in entries if e.get("enabled") and e.get("kind") == "special"]
    for i in range(len(sps)):
        for j in range(i + 1, len(sps)):
            a0, a1 = _special_window(sps[i])
            b0, b1 = _special_window(sps[j])
            if a0 < b1 + gap and b0 < a1 + gap:
                out.append(f"{sps[i]['name']} and {sps[j]['name']} are both specials on overlapping times")
    return out


def _cron_dow(day):
    return (day.weekday() + 1) % 7


def schedule_windows(e, now, back=1, ahead=8):
    if e.get("kind") == "special":
        return [_special_window(e)]
    hh, mm = divmod(_hm_minutes(e["start"], "Start"), 60)
    out = []
    for off in range(-back, ahead + 1):
        day = (now + timedelta(days=off)).date()
        if _cron_dow(day) in e["days"]:
            s = datetime(day.year, day.month, day.day, hh, mm)
            out.append((s, s + timedelta(minutes=e["duration_min"])))
    return out


def schedule_current(e, now):
    return next((w for w in schedule_windows(e, now) if w[0] <= now < w[1]), None)


def schedule_next(e, now):
    return next((w for w in schedule_windows(e, now) if w[0] > now), None)


def schedule_last_ended(e, now):
    ended = [w for w in schedule_windows(e, now) if w[1] <= now]
    return ended[-1] if ended else None


def _sched_empty():
    return {"version": 1, "entries": [], "error": ""}


def schedule_load():
    with _sched_lock:
        key = _file_key(SCHEDULE_PATH)
        if key is None:
            return _sched_empty()
        if key == _sched_cache["key"]:
            return _sched_cache["data"]
        data = _sched_empty()
        try:
            with open(SCHEDULE_PATH, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            raw = doc.get("entries") if isinstance(doc, dict) else None
            if not isinstance(raw, list):
                raise ValueError("the file has no entries list")
            for r in raw[:SCHEDULE_MAX]:
                try:
                    data["entries"].append(schedule_norm_entry(r, check_target=False))
                except ValueError as exc:
                    log_event(f"Schedule: skipped an entry ({exc})", "warn")
        except (OSError, ValueError) as exc:
            data["error"] = f"{SCHEDULE_PATH} could not be read ({exc}); the schedule is empty until it is fixed or replaced"
            log_event("Schedule: " + data["error"], "err")
            bad = SCHEDULE_PATH + ".bad"
            if not os.path.exists(bad):
                try:
                    shutil.copy2(SCHEDULE_PATH, bad)
                except OSError:
                    pass
        _sched_cache.update(key=key, data=data)
        return data


def schedule_store(entries):
    body = json.dumps({"version": 1, "entries": entries}, indent=1) + "\n"
    _atomic_write(SCHEDULE_PATH, body, 0o644)
    with _sched_lock:
        _sched_cache["key"] = None


def schedule_set(body):
    raw = body.get("entry") if isinstance(body, dict) else None
    e = schedule_norm_entry(raw)
    e["rev"] = datetime.now().isoformat(timespec="seconds")
    if e["kind"] == "special" and _special_window(e)[1] <= datetime.now():
        return {"ok": False, "error": "That special has already ended. Pick a later date or time."}
    running = SCHED.is_running(e["id"])
    with _sched_lock:
        data = schedule_load()
        if data["error"]:
            return {"ok": False, "error": data["error"]}
        entries = [x for x in data["entries"] if x["id"] != e["id"]]
        if len(entries) >= SCHEDULE_MAX and not any(x["id"] == e["id"] for x in data["entries"]):
            return {"ok": False, "error": f"The schedule is full ({SCHEDULE_MAX} entries)."}
        if running:
            return {"ok": False, "error": f"{e['name']} is recording now; change it when the recording ends."}
        entries.append(e)
        bad = schedule_conflicts(entries)
        if bad:
            return {"ok": False, "error": "; ".join(bad) + ".", "conflicts": bad}
        order = {x["id"]: i for i, x in enumerate(data["entries"])}
        entries.sort(key=lambda x: order.get(x["id"], len(order)))
        try:
            schedule_store(entries)
        except OSError as exc:
            return {"ok": False, "error": f"could not save {SCHEDULE_PATH}: {exc}"}
    what = f"special on {e['date']}" if e["kind"] == "special" else ", ".join(SCHEDULE_DAY_NAMES[d] for d in e["days"])
    log_event(f"Schedule: saved {e['name']} ({what} {e['start']}-{e['end']})", "ok")
    return {"ok": True, "entry": e, "message": "Saved."}


def schedule_remove(body):
    eid = str(body.get("id", "") if isinstance(body, dict) else "").strip().lower()
    if SCHED.is_running(eid):
        SCHED.stop_by_hand()
    with _sched_lock:
        data = schedule_load()
        if data["error"]:
            return {"ok": False, "error": data["error"]}
        hit = next((x for x in data["entries"] if x["id"] == eid), None)
        if hit is None:
            return {"ok": False, "error": "No such schedule entry."}
        try:
            schedule_store([x for x in data["entries"] if x["id"] != eid])
        except OSError as exc:
            return {"ok": False, "error": f"could not save {SCHEDULE_PATH}: {exc}"}
    SCHED.forget(eid)
    log_event(f"Schedule: removed {hit['name']}", "ok")
    return {"ok": True, "message": f"Removed {hit['name']}."}


def _run_step(fn, timeout, *args):
    box = {}

    def work():
        try:
            box["r"] = fn(*args)
        except Exception as exc:
            box["r"] = (False, str(exc) or exc.__class__.__name__, None)

    t = threading.Thread(target=work, name="sched-step", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return False, f"timed out after {timeout} s", None
    return box["r"]


def _entry_linked(target):
    node, _err = _connect_node()
    if not node:
        return None
    ok, links = rpt_links(node, max_age=0)
    if not ok:
        return None
    peers = {l["node"] for l in links}
    f = _tune_fav(target)
    if f["mode"] in ("ASL", "EchoLink"):
        return fav_target(f) in peers
    bridge = bridge_nodes().get("m17" if f["mode"] == "M17" else "digital")
    return bool(bridge) and bridge in peers


class DryActions:
    def connect(self, entry):
        return True, f"dry run: would connect {entry['name']}", None

    def link_alive(self, entry):
        return True

    def healthy(self, entry):
        return True, ""

    def start(self, entry, window):
        return True, f"dry run: would start a {entry['format']} recording", "dry-run"

    def stop(self):
        return True, "dry run: would stop the recording", None

    def disconnect(self, entry):
        return True, f"dry run: would disconnect {entry['name']}", None


class RealActions:
    def connect(self, entry):
        r = tune_connect(entry["target"])
        return bool(r.get("ok")), str(r.get("message") or r.get("error") or ""), None

    def link_alive(self, entry):
        return _entry_linked(entry["target"])

    def healthy(self, entry):
        return ENGINE.healthy()

    def start(self, entry, window):
        return ENGINE.start(entry, window)

    def stop(self):
        return ENGINE.stop()

    def disconnect(self, entry):
        r = tune_disconnect(entry["target"])
        return bool(r.get("ok")), str(r.get("message") or r.get("error") or ""), None


def run_sequence(entry, actions, end_at, abort, set_state, now_fn, sleep_fn, timeouts=None, window=None):
    timeouts = timeouts or STEP_TIMEOUT
    steps = []

    def do(name, fn, *args):
        t0 = now_fn()
        ok, msg, val = _run_step(fn, timeouts[name], *args)
        steps.append({"step": name, "ok": bool(ok), "msg": str(msg or ""), "secs": round(now_fn() - t0, 1)})
        return ok, msg, val

    def done(result, detail=""):
        return {"result": result, "detail": detail, "steps": steps}

    set_state("connecting")
    ok, msg, _ = do("connect", actions.connect, entry)
    if not ok:
        do("disconnect", actions.disconnect, entry)
        return done("connect_failed", f"connect failed: {msg}")
    if abort.is_set():
        do("disconnect", actions.disconnect, entry)
        return done("aborted", "stopped before the recording started")
    ok, msg, fname = do("start", actions.start, entry, window)
    if not ok:
        do("stop", actions.stop)
        do("disconnect", actions.disconnect, entry)
        return done("start_failed", f"could not start recording: {msg}")
    set_state("recording", file=fname or "")
    result, detail, lost = "ok", "", 0
    next_check = now_fn() + LINK_CHECK_SEC
    while True:
        t = now_fn()
        if abort.is_set():
            result, detail = "aborted", "Node Recorder was stopping"
            break
        if t >= end_at:
            break
        try:
            healthy, why = actions.healthy(entry)
        except Exception:
            healthy, why = True, ""
        if not healthy:
            result, detail = "write_failed", why
            break
        if t >= next_check:
            try:
                alive = actions.link_alive(entry)
            except Exception:
                alive = None
            lost = lost + 1 if alive is False else 0
            if lost >= LINK_LOST_CHECKS:
                result, detail = "link_lost", "the link dropped during the recording"
                break
            next_check = t + LINK_CHECK_SEC
        sleep_fn(min(1.0, max(0.05, end_at - t)))
    set_state("stopping")
    ok, msg, _ = do("stop", actions.stop)
    if not ok and result == "ok":
        result, detail = "stop_failed", f"the recording did not stop cleanly: {msg}"
    set_state("disconnecting")
    ok, msg, _ = do("disconnect", actions.disconnect, entry)
    if not ok and result == "ok":
        result, detail = "disconnect_failed", f"the link was not dropped: {msg}"
    return done(result, detail)


def _special_remove(eid):
    with _sched_lock:
        data = schedule_load()
        if data["error"]:
            return
        keep = [x for x in data["entries"] if x["id"] != eid]
        if len(keep) == len(data["entries"]):
            return
        try:
            schedule_store(keep)
        except OSError as exc:
            log_event(f"Schedule: could not remove the special {eid}: {exc}", "err")


class Scheduler:
    def __init__(self, real_actions=None, dry_actions=None):
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.real = real_actions or RealActions
        self.dry = dry_actions or DryActions
        self.clock = time.time
        self.sleep = time.sleep
        self.thread = None
        self.state = "idle"
        self.cur = None
        self.run_abort = threading.Event()
        self.user_stop = False
        self.preempt = False
        self.results = deque(maxlen=20)
        self.done = {}
        self.active = None
        self.booted = False

    def _state_load(self):
        try:
            with open(SCHEDULE_STATE_PATH, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            if isinstance(doc, dict):
                if isinstance(doc.get("done"), dict):
                    self.done = {str(k): str(v) for k, v in doc["done"].items()}
                a = doc.get("active")
                if isinstance(a, dict) and a.get("id") and a.get("start"):
                    self.active = {"id": str(a["id"]), "start": str(a["start"])}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log_event(f"Schedule: {SCHEDULE_STATE_PATH} could not be read ({exc}); starting without it", "warn")

    def _state_save(self):
        try:
            _atomic_write(SCHEDULE_STATE_PATH, json.dumps({"active": self.active, "done": self.done}) + "\n", 0o644)
        except OSError as exc:
            log_event(f"Schedule: could not save {SCHEDULE_STATE_PATH}: {exc}", "warn")

    def is_running(self, eid):
        with self.lock:
            return self.cur is not None and self.cur["id"] == eid

    def forget(self, eid):
        with self.lock:
            changed = self.done.pop(eid, None) is not None
            if self.active and self.active["id"] == eid:
                self.active, changed = None, True
            if changed:
                self._state_save()

    def status(self):
        with self.lock:
            cur = dict(self.cur) if self.cur else None
            if cur:
                cur["elapsed"] = int(self.clock() - cur["started"])
            return {"state": self.state, "current": cur, "results": list(self.results)}

    def _set_state(self, state, file=None):
        with self.lock:
            self.state = state
            if self.cur is not None and file is not None:
                self.cur["file"] = file

    def _note(self, entry, window_start, result, detail, manual=False):
        row = {"id": entry["id"], "name": entry["name"], "window": window_start, "result": result,
               "detail": detail, "at": datetime.now().isoformat(timespec="seconds")}
        self.results.append(row)
        level = "ok" if result == "ok" else "warn"
        label = "Record now" if manual else "Schedule"
        log_event(f"{label}: {entry['name']} {window_start}: {result}" + (f" ({detail})" if detail else ""), level)

    def _dry(self):
        return bool(_cfg_get("schedule_dry_run")) or not ENGINE_READY

    def _due_special(self, specials, now):
        for e in specials:
            w = schedule_current(e, now)
            if w and self.done.get(e["id"]) != w[0].isoformat(timespec="minutes"):
                return e, w
        return None

    def tick(self, now=None):
        now = now or datetime.now()
        data = schedule_load()
        entries = [e for e in data["entries"] if e["enabled"]]
        specials = [e for e in entries if e.get("kind") == "special"]
        regulars = [e for e in entries if e.get("kind") != "special"]
        prune = []
        with self.lock:
            if not self.booted:
                self.booted = True
                self._state_load()
                if self.active:
                    e = next((x for x in data["entries"] if x["id"] == self.active["id"]), None)
                    w = None
                    if e:
                        w = next((w for w in schedule_windows(e, now) if w[0].isoformat(timespec="minutes") == self.active["start"]), None)
                    if e and w and w[0] <= now < w[1] and e["enabled"]:
                        log_event(f"Schedule: {e['name']} was recording when Node Recorder stopped; resuming", "warn")
                    else:
                        name = e["name"] if e else self.active["id"]
                        self.results.append({"id": self.active["id"], "name": name, "window": self.active["start"],
                                             "result": "interrupted", "detail": "Node Recorder stopped during this window and it has ended",
                                             "at": now.isoformat(timespec="seconds")})
                        log_event(f"Schedule: {name} {self.active['start']}: interrupted by a restart or power loss", "warn")
                        self.done[self.active["id"]] = self.active["start"]
                        self.active = None
                        self._state_save()
            due = self._due_special(specials, now)
            if self.thread is not None and self.thread.is_alive():
                if due and self.cur is not None and self.cur.get("kind") != "special" and not self.preempt:
                    self.preempt = True
                    log_event(f"Schedule: {due[0]['name']} takes over from {self.cur['name']}; that window resumes after it", "warn")
                    self.run_abort.set()
                return
            ids = {e["id"] for e in data["entries"]}
            for k in [k for k in self.done if k not in ids]:
                del self.done[k]
            if due:
                self._start_run(due[0], due[1], now)
                return
            covered = any(schedule_current(e, now) for e in specials)
            for e in regulars:
                w = schedule_current(e, now)
                if w and not covered and self.done.get(e["id"]) != w[0].isoformat(timespec="minutes"):
                    late = (now - w[0]).total_seconds()
                    if late > 60:
                        log_event(f"Schedule: {e['name']} starts {int(late)} s late", "warn")
                    self._start_run(e, w, now)
                    return
            changed = False
            for e in entries:
                w = schedule_last_ended(e, now)
                if w is None:
                    continue
                key = w[0].isoformat(timespec="minutes")
                if now - w[1] > MISSED_LOOKBACK:
                    if e.get("kind") == "special":
                        prune.append(e["id"])
                    continue
                if self.done.get(e["id"]) == key:
                    if e.get("kind") == "special":
                        prune.append(e["id"])
                    continue
                self.done[e["id"]] = key
                changed = True
                if e.get("kind") == "special":
                    prune.append(e["id"])
                    self._note(e, key, "missed", "Node Recorder was not running or was busy")
                    continue
                if any(_special_window(x)[0] < w[1] and w[0] < _special_window(x)[1] for x in specials):
                    continue
                try:
                    saved = datetime.fromisoformat(e["rev"]) if e["rev"] else None
                except ValueError:
                    saved = None
                if saved is not None and w[1] > saved:
                    self._note(e, key, "missed", "Node Recorder was not running or was busy")
            if changed:
                self._state_save()
        for eid in prune:
            _special_remove(eid)

    def start_manual(self, entry, window):
        with self.lock:
            if self.cur is not None or (self.thread is not None and self.thread.is_alive()):
                return False, "A recording is already running."
            now = datetime.now()
            data = schedule_load()
            due = [e["name"] for e in data["entries"] if e["enabled"] and schedule_current(e, now)]
            if due:
                return False, f"{due[0]} is due now; record by hand after its window ends."
            self._start_run(entry, window, now, manual=True)
        return True, ""

    def _start_run(self, entry, window, now, manual=False):
        end_at = self.clock() + (window[1] - now).total_seconds()
        s_iso = window[0].isoformat(timespec="minutes")
        dry = self._dry()
        with self.lock:
            abort = threading.Event()
            self.run_abort = abort
            self.user_stop = False
            self.preempt = False
            if not manual:
                self.active = {"id": entry["id"], "start": s_iso}
            self.cur = {"id": entry["id"], "name": entry["name"], "start": s_iso, "manual": manual, "kind": entry.get("kind", "regular"),
                        "end": window[1].isoformat(timespec="minutes"), "started": self.clock(), "file": "", "dry_run": dry}
            self.state = "connecting"
            self._state_save()
        actions = (self.dry if dry else self.real)()
        self.thread = threading.Thread(target=self._run, args=(entry, window, s_iso, end_at, actions, abort, manual),
                                       name="sched-run", daemon=True)
        self.thread.start()

    def stop_by_hand(self):
        with self.lock:
            if self.cur is None:
                return False, "Nothing is being recorded."
            if self.run_abort.is_set():
                return True, "Already stopping."
            self.user_stop = True
            name = self.cur["name"]
            self.run_abort.set()
        log_event(f"Recording stopped by hand: {name}", "warn")
        return True, f"Stopping {name}. What was recorded is saved and the link is dropped."

    def _run(self, entry, window, s_iso, end_at, actions, abort, manual):
        try:
            res = run_sequence(entry, actions, end_at, abort, self._set_state, self.clock, self.sleep, window=window)
        except Exception as exc:
            res = {"result": "error", "detail": str(exc), "steps": []}
        special = entry.get("kind") == "special"
        with self.lock:
            preempted = self.preempt and not self.user_stop and res["result"] == "aborted"
            if self.user_stop and res["result"] == "aborted":
                res["detail"] = "stopped by hand"
            elif preempted:
                res["detail"] = "a special recording took over; this window resumes after it"
            self._note(entry, s_iso, res["result"], res["detail"], manual)
            if not manual:
                if not preempted:
                    self.done[entry["id"]] = s_iso
                self.active = None
                self._state_save()
            self.cur = None
            self.state = "idle"
        if special:
            _special_remove(entry["id"])

    def loop(self):
        while not self.stop.wait(1.0):
            try:
                self.tick()
            except Exception as exc:
                log_event(f"Schedule: {exc}", "err")

    def shutdown(self, wait=45.0):
        self.stop.set()
        self.run_abort.set()
        t = self.thread
        if t is not None and t.is_alive():
            t.join(wait)


SCHED = Scheduler()


def schedule_dry_run(body):
    if not isinstance(body, dict):
        raise ValueError("bad request")
    if body.get("entry") is not None:
        entry = schedule_norm_entry(body["entry"])
    else:
        eid = str(body.get("id", "")).strip().lower()
        entry = next((x for x in schedule_load()["entries"] if x["id"] == eid), None)
        if entry is None:
            return {"ok": False, "error": "No such schedule entry."}
        entry = schedule_norm_entry(entry)
    clock = {"t": 0.0}

    def sleep(sec):
        clock["t"] += sec

    states = []
    res = run_sequence(entry, DryActions(), entry["duration_min"] * 60.0, threading.Event(),
                       lambda s, file=None: states.append(s), lambda: clock["t"], sleep)
    return {"ok": True, "result": res["result"], "detail": res["detail"], "steps": res["steps"], "states": states,
            "message": "Dry run finished: nothing was connected or recorded."}


def recorder_status():
    st = SCHED.status()
    cur = st["current"] or {}
    dry = bool(cur.get("dry_run"))
    return {"ok": True, "version": VERSION, "state": st["state"], "busy": st["state"] != "idle" and not dry, "dry_run": dry,
            "entry": cur.get("name", ""), "start": cur.get("start", ""), "end": cur.get("end", ""),
            "elapsed": cur.get("elapsed", 0), "file": cur.get("file", "")}


MANUAL_MAX_SEC = 4 * 3600


def recording_start(body):
    raw = body.get("entry") if isinstance(body, dict) else None
    if not isinstance(raw, dict):
        return {"ok": False, "error": "bad request"}
    try:
        entry = schedule_norm_entry({"name": raw.get("name", ""), "target": raw.get("target"), "format": raw.get("format", "ulaw"),
                                     "start": "00:00", "end": "00:01", "days": list(range(7))})
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    now = datetime.now()
    ok, msg = SCHED.start_manual(entry, (now, now + timedelta(seconds=MANUAL_MAX_SEC)))
    if not ok:
        return {"ok": False, "error": msg}
    return {"ok": True, "message": f"Recording {entry['name']}. Press Stop recording to end it (it stops by itself after 4 hours)."}


def recording_stop():
    ok, msg = SCHED.stop_by_hand()
    return {"ok": ok, "message": msg} if ok else {"ok": False, "error": msg}


TALKER_FAV_PATH = os.environ.get("NODERECORDER_TALKER_FAV", "/etc/asl_dvs/nodetalker_favorites.conf")
TALKER_FAV_JSON = os.environ.get("NODERECORDER_TALKER_FAV_JSON", "/etc/asl_dvs/nodetalker_favorites.json")


_DSTAR_TUNE_RE = re.compile(r"^([A-Z0-9]{3,6}) *([A-Z])L$")


def _fav_pick(f):
    out = {k: str(f[k]) for k in ("mode", "num", "module", "net", "label") if f.get(k) not in (None, "")}
    if out.get("mode") == "DSTAR":
        m = _DSTAR_TUNE_RE.match(out.get("num", "").upper())
        if m:
            out["num"], out["module"] = m.group(1), m.group(2)
        else:
            parts = out.get("num", "").split()
            out["num"] = parts[0] if parts else ""
            if len(parts) > 1:
                out["module"] = parts[1]
    return out


def _read_talker_favs():
    try:
        with open(TALKER_FAV_PATH, "r", encoding="utf-8", errors="replace") as fh:
            return True, [_fav_pick(f) for f in parse_fav_conf(fh.read())["favs"]]
    except OSError:
        pass
    try:
        with open(TALKER_FAV_JSON, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return True, [_fav_pick(f) for f in data if isinstance(f, dict) and f.get("mode") and f.get("num")]
    except (OSError, ValueError):
        return False, []


def schedule_sources(_body=None):
    found, talker = _read_talker_favs()
    dash = dashboard_conf()
    return {"ok": True, "talker": talker, "talker_found": found, "talker_path": TALKER_FAV_PATH,
            "controller": [_fav_pick(f) for f in dash["favs"]], "controller_found": os.path.exists(DASH_CONF),
            "controller_path": DASH_CONF, "nets": [n["name"] for n in nets_load()], "modes": list(FAV_MODES)}


def schedule_view():
    data = schedule_load()
    now = datetime.now()
    rows = []
    for e in data["entries"]:
        row = dict(e)
        nxt = schedule_next(e, now) if e["enabled"] else None
        cur = schedule_current(e, now) if e["enabled"] else None
        row["next"] = (cur or nxt)[0].strftime("%a %d %b %H:%M") if (cur or nxt) else ""
        row["now"] = bool(cur)
        rows.append(row)
    return {"ok": True, "entries": rows, "error": data["error"], "max": SCHEDULE_MAX, "gap_min": SCHEDULE_GAP_MIN,
            "formats": list(SCHEDULE_FORMATS), "status": SCHED.status(), "engine_ready": ENGINE_READY,
            "dry_run": bool(_cfg_get("schedule_dry_run")) or not ENGINE_READY, "now": now.strftime("%a %d %b %H:%M")}


_CSS = r"""@font-face{font-family:"Readex Pro";font-style:normal;font-weight:400;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2")}
@font-face{font-family:"Readex Pro";font-style:normal;font-weight:700;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2")}
:root{--bg:#0d1117;--card:#161e2e;--card2:#0d1117;--line:#2e4060;--line2:#3a5278;--text:#f0f8ff;--muted:#9fb0bf;
--soft:#c9d4de;--accent:#00ffb0;--accent-ink:#0d1117;--accent-dim:#005538;--amber:#ffd040;--amber-bg:#2a2000;--red:#ff3d5a;--red-line:#ff3d5a}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--text);font:15px/1.45 "Readex Pro",Arial,Helvetica,sans-serif}
body{display:flex;flex-direction:column;height:100vh;height:100dvh;overflow:hidden}
header{flex:none;display:flex;align-items:center;gap:10px;padding:calc(12px + env(safe-area-inset-top)) 16px 12px;border-bottom:2px solid var(--amber);background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);z-index:5;box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
header .hdr-left{display:flex;flex-direction:column;min-width:0}
header h1{font-size:1.089rem;margin:0;white-space:nowrap;color:var(--amber);letter-spacing:.1em;text-transform:uppercase;text-shadow:0 0 10px rgba(255,208,64,.9),0 0 30px rgba(255,208,64,.5),0 0 60px rgba(255,208,64,.2)}
header .hdr-pills{display:flex;flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:6px;min-width:0;margin-left:auto}
header .logo-sub{font-size:.715rem;letter-spacing:.22em;text-transform:uppercase;color:var(--amber);margin-top:.1rem}

header .ver{color:var(--muted);font-size:12px}
header .sp{flex:1}
.pill{display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 12px;border:1px solid var(--line2);border-radius:999px;color:var(--text);text-decoration:none;background:transparent;cursor:pointer;font:inherit;font-size:10.53px;white-space:nowrap}
.pill:hover{border-color:var(--accent)}
.ql-row{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 2px}
.ql{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;text-decoration:none;white-space:nowrap;color:var(--amber);border:1px solid rgba(244,192,78,.45);background:rgba(255,61,90,.15);text-shadow:0 0 8px rgba(255,208,64,.4);border-radius:4px;padding:8px 12px;cursor:pointer;transition:all .14s}
.ql:hover{filter:brightness(1.5);box-shadow:0 0 10px currentColor}
.ql:active{transform:scale(.95)}
main{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:14px max(16px,calc((100% - 608px) / 2)) 24px;overflow-wrap:anywhere}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.card h2{font-size:15px;margin:0 0 10px}
.card.fold{padding-top:4px;padding-bottom:4px}
.card.fold h2{margin:0}
.fold-btn{width:100%;min-height:44px;display:flex;align-items:center;gap:8px;padding:0;border:0;background:transparent;color:var(--text);font:inherit;font-size:15px;font-weight:700;text-align:left;cursor:pointer}
.fold-t{flex:none}
.fold-sum{flex:1;min-width:0;color:var(--muted);font-size:13px;font-weight:400;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fold-i{flex:none;width:14px;margin-left:auto;color:var(--muted);text-align:center}
.kc-graph{width:100%;height:120px;display:block;margin:8px 0}
.kc-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:4px 0;border-top:1px solid var(--line)}
.kc-row span{flex:1;min-width:200px}
.kc-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
.kc-min{width:64px}
.kc-sub{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-top:8px}
.kc-sub-head{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:13px;color:var(--muted)}
.kc-json{width:100%;min-height:160px;font:11px ui-monospace,Menlo,Consolas,monospace;background:#0a1016;color:var(--text);border:1px solid var(--line);border-radius:6px;margin:8px 0}
.fold-body{padding:6px 0 10px}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}
button{font:inherit;color:var(--text)}
.btn{min-height:44px;padding:0 16px;border-radius:10px;border:1px solid var(--line2);background:#1b2633;cursor:pointer;font-weight:600}
.btn:hover{border-color:var(--accent)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.btn.danger{background:transparent;border-color:var(--red-line);color:var(--red)}
.btn.connect{background:transparent;border-color:var(--accent-dim);color:var(--accent)}
.btn.connect:hover{border-color:#7fffd0}
.btn.disconnect{background:transparent;border-color:#6b0e20;color:var(--red)}
.btn.disconnect:hover{border-color:#ff8a9a}
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
.big-num{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:22px;font-weight:700}
.meter{position:relative;height:12px;flex:1;min-width:140px;background:#1b2530;border-radius:6px;overflow:hidden}
.meter i{position:absolute;left:0;top:0;bottom:0;width:0;background:linear-gradient(90deg,#22c3a6,#22c3a6 70%,#e3a008 90%,#f2545b);transition:width .1s}
.dot{display:inline-block;width:11px;height:11px;border-radius:50%;background:#33404d;vertical-align:middle;margin-right:6px}
.dot.on{background:var(--accent);box-shadow:0 0 8px var(--accent)}
.dot.rx{background:var(--amber);box-shadow:0 0 8px var(--amber)}
.dot.tx{background:var(--red-line);box-shadow:0 0 8px var(--red-line)}
.dot.warn{background:#e3a008}.dot.err{background:var(--red-line)}
.msg{margin-top:8px;font-size:14px;min-height:1em;overflow-wrap:anywhere}
#login-tls{max-width:300px;font-size:.78rem;color:#ff3d5a;margin-top:.4rem}#login-tls:empty{display:none}
.msg.ok{color:var(--accent)}.msg.err{color:var(--red)}.msg.warn{color:var(--amber)}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{text-align:left;padding:6px 6px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
table.links{font-size:calc(clamp(10.5px,3.1vw,14px) + var(--sett-font) - 15px);font-variant-numeric:tabular-nums}
#cd-links .small{font-size:calc(13px + var(--sett-font) - 15px)}
table.links td,table.links th{padding:6px 3px;white-space:nowrap;overflow-wrap:normal}
table.links td:nth-child(2){width:100%;max-width:0;overflow:hidden;text-overflow:ellipsis}
.listen-row{flex-wrap:nowrap}
.listen-row .btn.big{min-width:112px;flex:none}
.listen-row input[type=range]{flex:1;min-width:0}
.vol-i{flex:none;width:22px;height:22px;color:var(--muted)}
th{color:var(--muted);font-weight:600;white-space:nowrap;overflow-wrap:normal}
code{background:var(--card2);border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:12px;word-break:break-all}
#log{max-height:260px;overflow:auto;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;background:var(--card2);border:1px solid var(--line);border-radius:8px;padding:8px}
.enc-opt{border-top:1px solid var(--line);padding:4px 0}.enc-opt p{margin:2px 0 4px}
#conv-term{max-height:260px;overflow:auto;margin:6px 0;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;background:#05080f;color:#c8f7c5;border:1px solid var(--line);border-radius:8px;padding:8px;white-space:pre-wrap;word-break:break-all}
#log .err{color:var(--red)}#log .warn{color:var(--amber)}#log .ok{color:var(--accent)}
.hidden{display:none !important}
.na{opacity:.45}
.na,.na *{cursor:not-allowed}
.why{margin:4px 0 8px}
:root{--tn-gap:2px;--tn-h:40px;--tn-font:14px;--lt-font:15px;--lt-h:64px;--sett-font:15px;--sett-h:44px}
.tn-bar{display:flex;flex-wrap:wrap;gap:var(--tn-gap);align-items:center}
.tn-bar select,.tn-bar input{min-height:var(--tn-h);font-size:var(--tn-font)}
#t-mode{flex:0 0 auto;width:7rem}
#t-net{flex:0 0 auto;width:7rem}
#t-mod{flex:0 0 auto;width:4.6rem}
#t-find{flex:1 1 6rem;min-width:5rem;max-width:10rem}
#t-pick{flex:2 1 7rem;min-width:0}
.tn-bar .btn{min-height:var(--tn-h);padding:0 14px}
.btn-last{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;font-weight:700;letter-spacing:.04em;min-height:var(--tn-h);padding:0 10px;border-radius:6px;border:1px solid rgba(244,192,78,.45);background:rgba(255,208,64,.05);color:var(--amber);cursor:pointer}
.btn-last.lh-off{opacity:.4;color:var(--muted);border-color:var(--muted);background:transparent;cursor:default}
.tn-msg{margin-top:8px;font-size:13px;color:var(--muted);min-height:1em}
.tn-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:10px}
#t-now{flex:1;min-width:0;overflow-wrap:anywhere;text-align:center}
.tn-bar #t-go{flex:1 1 100%;min-height:56px;font-size:17px}
.btn-pair{display:flex;gap:8px;width:100%}
.tn-bar .btn-pair>.btn{flex:1 1 0!important;width:auto!important;min-width:0}
#tab-connect{min-height:100%;display:flex;flex-direction:column}
#tab-connect .card{padding:8px 10px;margin-bottom:8px}
#tab-connect h2{font-size:14px;margin:0 0 4px}
#tab-connect .sel-card{margin-top:4px;padding:6px 8px;gap:3px}
#tab-connect .big-num{font-size:18px}
#tab-connect .btn.big{min-height:40px;font-size:14px;min-width:0}
#tab-connect .tn-bar{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--tn-gap)}
#tab-connect .tn-bar>*{width:100%!important;flex:none!important;max-width:none!important;min-width:0}
#tab-connect #t-find,#tab-connect #t-pick{grid-column:span 2}
#tab-connect .tn-pair{grid-column:1 / -1}
#tab-connect #t-go{min-height:44px;font-size:15px}
#tab-connect .tn-msg,#tab-connect .msg,#tab-connect .small{font-size:12px;margin-top:2px}
#tab-connect .tn-foot{margin-top:2px}
#cd-sys .row{justify-content:center}
#tab-connect .tn-bar .btn-last{min-height:40px}
#tab-connect #cd-tune .tn-msg{min-height:0}
#da-wrap{margin:0 0 8px}
#da-btn{width:100%;min-height:clamp(44px,8vh,64px);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;padding:4px 12px;border-width:2px}
#da-btn .da-t{font-size:clamp(14px,calc(1.6vh + 1vw),18px);font-weight:700;letter-spacing:.04em;line-height:1.15}
#da-btn .da-s{font-size:clamp(10px,calc(.9vh + .5vw),12px);font-weight:500;color:var(--muted);line-height:1.2;max-width:100%;overflow-wrap:anywhere}
#da-btn:disabled{opacity:.55;cursor:default}
#da-wrap .msg:empty{display:none}
#tab-listen .lpanel{padding:8px 10px}
@media (max-width:560px){#t-mode,#t-net,#t-mod{flex:1 1 40%;width:auto}#t-find{flex:1 1 100%;max-width:none}#t-pick{flex:1 1 100%}.tn-bar .btn.primary{flex:1 1 auto}}
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
nav.tabs{flex:none;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));background:var(--card);border-top:1px solid var(--line);padding:4px 6px calc(8px + env(safe-area-inset-bottom));z-index:5}
nav.tabs button{background:transparent;border:1px solid var(--line2);border-bottom:0;border-radius:5px 5px 0 0;min-height:52px;text-transform:uppercase;letter-spacing:.08em;font-weight:700;color:var(--muted);font-size:13px;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}
nav.tabs button[aria-current=page]{color:#22d4ff;border-color:#22d4ff;background:rgba(34,212,255,.12);box-shadow:0 0 10px rgba(34,212,255,.35)}
nav.tabs svg{width:22px;height:22px}
main.fit{padding-top:10px;padding-bottom:12px}
#tab-listen{min-height:100%;display:flex;flex-direction:column;font-size:var(--lt-font)}
#tab-setup{font-size:var(--sett-font)}
#tab-setup .btn{min-height:var(--sett-h)}
#tab-setup .fav-row button{min-height:40px}
.lpanel{flex:1 0 auto;display:flex;flex-direction:column;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.lpanel>*{flex:none}
.lpanel .row{margin:0}
.lpanel .msg{margin-top:0;min-height:0}
.lpanel #listen-msg:empty{display:none}
#listen-msg{display:none}
.lstat{display:flex;align-items:center;justify-content:center;gap:12px;font-size:13px;color:var(--soft);white-space:nowrap;overflow:hidden}
.lstat>span{flex:none;display:inline-flex;align-items:center}
.lstat #st-node{font-weight:700;color:var(--text)}
.lstat #st-feed-w{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis}
.lstat .dot{margin-right:4px}
.spec{flex:1 1 0;min-height:14px;display:flex;flex-direction:column;gap:4px}
.spec-box{position:relative;flex:1;min-height:0;border-radius:8px;overflow:hidden;background:#0a1016;border:1px solid var(--line)}
.spec-box canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.spec-lo{position:absolute;left:0;top:0;bottom:0;width:7.5%;background:rgba(244,192,78,.10);border-right:1px dashed rgba(244,192,78,.45);pointer-events:none}
.spec-t{position:absolute;bottom:2px;transform:translateX(-50%);font:10px ui-monospace,Menlo,Consolas,monospace;color:var(--muted);pointer-events:none}
.spec.small .spec-box,.spec.off .spec-box{display:none}
.gap-cd{position:absolute;top:0;right:0;width:25%;height:50%;display:flex;align-items:center;justify-content:center;font:700 40px ui-monospace,Menlo,Consolas,monospace;color:#fff;opacity:.25;pointer-events:none;line-height:1}
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
.tone-scroll{overflow-x:auto}
table.tone-t{table-layout:auto}
.chk-min{display:grid;grid-template-columns:76px repeat(var(--n,5),minmax(0,1fr));gap:3px;font-size:11px;align-items:end}
.chk-min .lab{color:var(--muted);align-self:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chk-min .cell{display:flex;flex-direction:column;align-items:center;gap:2px}
.chk-min .bar{width:100%;height:36px;background:var(--line);border-radius:3px;position:relative;overflow:hidden}
.chk-min .fill{position:absolute;left:0;right:0;bottom:0;background:#4da3ff}
.chk-min .val{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:10px}
table.tone-t td,table.tone-t th{padding:4px 3px;font-size:11px;white-space:nowrap}
table.chk-t td{font-family:ui-monospace,Menlo,Consolas,monospace}
.sug{display:flex;gap:8px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--line);font-size:14px}
.sug .t{flex:1}
.sug .btn{min-height:36px;padding:0 12px;font-size:13px}
.st-ok{color:var(--accent)}.st-warn{color:var(--amber)}.st-bad{color:var(--red)}
.spec-meter .meter{height:6px;min-width:0}
#ptt-card{display:flex;flex-direction:column;gap:4px;margin-bottom:2px}
.ptt-row{display:flex;gap:8px}
.ptt-row #ptt{flex:1;min-width:0}
#ptt-mark{flex:0 0 38%;height:var(--lt-h);border-radius:16px;border:3px solid var(--amber);background:var(--amber-bg);color:var(--amber);font-size:15px;font-weight:700;cursor:pointer;padding:0 8px}
#ptt-mark:active{filter:brightness(1.3)}
#ptt{width:100%;height:var(--lt-h);border-radius:16px;border:3px solid var(--line2);background:#1b2633;color:var(--text);font-size:17px;font-weight:700;cursor:pointer;padding:0 20px;
touch-action:none;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;display:flex;align-items:center;justify-content:space-between;gap:10px;overflow:hidden}
#ptt-label{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#ptt.ready{border-color:var(--accent)}
#ptt.busy{border-color:var(--amber)}
#ptt.talking{background:#4a1418;border-color:var(--red-line);box-shadow:0 0 0 6px rgba(242,84,91,.15)}
.ptt-line{font-size:12px;text-align:center;min-height:16px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
#ptt-msg:not(:empty)+#ptt-info{display:none}
#ptt:disabled{opacity:.45;cursor:default}
#ptt-time{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:15px;color:var(--soft)}
#ptt.guard-warn{border-color:var(--amber);box-shadow:0 0 0 6px rgba(244,192,78,.18)}
#ptt.guard-warn #ptt-time{color:var(--amber);animation:guardblink 1s steps(2,start) infinite}
@keyframes guardblink{to{visibility:hidden}}
.sel-card{display:flex;flex-direction:column;gap:6px;background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:10px}
.tag{display:inline-block;padding:2px 8px;border:1px solid var(--accent);border-radius:7px;color:#7fd8c6;font-size:12px;font-weight:700;font-family:ui-monospace,Menlo,Consolas,monospace}
#listen-btn{line-height:1.05}
#listen-btn .lb{display:inline-block;font-size:.72em;line-height:1.05}
.lk-badge{display:inline-block;padding:0 .4em;border:1px solid var(--accent);border-radius:.3em;color:#7fd8c6;font-size:1em;line-height:1.4;font-weight:700;font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:.03em;vertical-align:baseline}
.fav-row{display:grid;grid-template-columns:110px 124px minmax(0,1fr) 44px;gap:6px;margin:6px 0}
.fav-row input,.fav-row select{min-width:0;width:100%}
.fav-row button{min-height:40px;border-radius:8px;border:1px solid var(--line2);background:transparent;color:var(--red);cursor:pointer}
@media (max-width:420px){header{gap:6px;padding:calc(10px + env(safe-area-inset-top)) 12px 10px}header .ver{display:none}.pill{padding:0 10px}}
@media (max-width:480px){.fav-row{grid-template-columns:92px 108px minmax(0,1fr) 40px}}
.fav-row .fav-net{grid-column:2/-1}
.fav-row .fav-gain{grid-column:1/-1;display:flex;gap:6px;align-items:center;font-size:.85em;opacity:.85}
.fav-row .fav-gain span{flex:1 1 auto;min-width:0}
.fav-row .fav-gain input{width:72px;min-width:0}
.net-row{display:grid;grid-template-columns:minmax(0,.8fr) minmax(0,1.3fr) minmax(0,.9fr) 44px;gap:6px;margin:6px 0}
.net-row input{min-width:0;width:100%}
.net-row .net-url{grid-column:1/-1}
.net-row button{min-height:40px;border-radius:8px;border:1px solid var(--line2);background:transparent;color:var(--red);cursor:pointer}
@media (max-width:480px){.net-row{grid-template-columns:minmax(0,1fr) minmax(0,1fr) 40px}.net-row .net-pw{grid-column:1/3}}
"""

_JS = r"""const $ = (id) => document.getElementById(id);
let authed = false, publicListen = false, dashPort = 8989, tab = 'listen', lastLogId = 0, lastStatus = null;
let favNets = [], favModes = ['ASL', 'EchoLink', 'M17'];
let nets = [], netMax = 10;
async function api(url, opts) {
  opts = opts || {};
  opts.headers = Object.assign({'X-Requested-With': 'XMLHttpRequest'}, opts.headers || {});
  if (opts.body && typeof opts.body !== 'string') {
    opts.body = JSON.stringify(opts.body);
    opts.headers['Content-Type'] = 'application/json';
  }
  let r;
  try { r = await fetch(url, opts); } catch (e) { return {ok: false, error: 'Node Recorder is not answering.'}; }
  let d = {};
  try { d = await r.json(); } catch (e) { d = {ok: false, error: 'HTTP ' + r.status}; }
  if (r.status === 401 && url !== '/api/login' && authed) { authed = false; render(); }
  return d;
}
const post = (url, body) => api(url, {method: 'POST', body: body});
function note(id, cls, text) {
  const el = $(id);
  el.className = cls ? 'msg ' + cls : 'msg';
  el.textContent = text;
}
const msgTimers = {};
function setMsg(id, d) {
  note(id, d.warn ? 'warn' : d.ok ? 'ok' : 'err', d.ok ? (d.message || 'Done.') : (d.error || 'Failed.'));
  clearTimeout(msgTimers[id]);
  const shown = $(id).textContent;
  msgTimers[id] = setTimeout(() => { if ($(id).textContent === shown) note(id, '', ''); }, 30000);
}
function fmtGain(v) { return (v > 0 ? '+' : '') + v + ' dB'; }
function addOption(sel, value, text) {
  const o = document.createElement('option');
  o.value = value; o.textContent = text;
  sel.appendChild(o);
}
function foldOpen(k) { return !$('cb-' + k).classList.contains('hidden'); }
function sum(k, text) { const el = $('sum-' + k); if (el) el.textContent = text; }
function openNamedTab(url, name) {
  let w = null;
  try { w = window.open('', name); } catch (e) {}
  if (!w) { window.open(url, name); return; }
  let blank = false;
  try { blank = w.location.href === 'about:blank'; } catch (e) {}
  if (blank) w.location.href = url;
  try { w.focus(); } catch (e) {}
}
function hostLinks(d) {
  if (d.dash_port) dashPort = d.dash_port;
  const a = $('dash-link'), base = 'http://' + location.hostname;
  const nc = !!d.dash_running, im = !nc && !!d.instmon_port;
  a.href = base + ':' + (nc ? dashPort : im ? d.instmon_port : dashPort) + '/';
  a.textContent = im ? 'InstMon' : 'Node Controller';
  a.setAttribute('aria-label', im ? 'Open InstMon' : 'Open Node Controller');
  a.dataset.win = im ? 'asl_dvs_instmon' : 'asl_dvs_dash';
  a.classList.toggle('hidden', !nc && !im);
  const L = d.links || {};
  let any = false;
  document.querySelectorAll('.ql[data-ql]').forEach((q) => {
    q.href = q.dataset.qlPath ? base + q.dataset.qlPath : base + ':' + q.dataset.qlPort + '/';
    const on = !!L[q.dataset.ql];
    q.classList.toggle('hidden', !on);
    any = any || on;
  });
  $('ql-row').classList.toggle('hidden', !any);
}
async function pollHostLinks() {
  if (document.visibilityState !== 'visible') return;
  const d = await api('/api/whoami');
  if (d.ok) hostLinks(d);
}
async function doReboot() {
  if (!confirm('Reboot the system?')) return;
  const d = await post('/api/system/reboot', {});
  if (!d.ok) { note('sys-msg', 'err', d.error || 'Reboot failed'); return; }
  note('sys-msg', 'warn', d.message || 'Rebooting…');
}
async function doShutdown() {
  if (!confirm('Shut down the system?')) return;
  const d = await post('/api/system/shutdown', {});
  if (!d.ok) { note('sys-msg', 'err', d.error || 'Shutdown failed'); return; }
  note('sys-msg', 'warn', d.message || 'Shutting down…');
}
function fmtDb(db) { return db <= -119 ? '-inf' : ((Math.round(db) || 0) + ' dBFS'); }
function dbPct(db) { return Math.max(0, Math.min(100, (db + 60) / 60 * 100)); }
function modeName(m) { return m === 'DSTAR' ? 'D-STAR' : m; }
let linkedNodes = new Set();
async function setupCheck() {
  if ($('setup-dlg').open) return;
  const d = await api('/api/setup');
  if ($('setup-dlg').open) return;
  if (!d.ok || !d.pending || (!d.steps.length && !d.blocked.length)) return;
  const list = $('setup-steps');
  list.innerHTML = '';
  d.steps.forEach((s) => { const li = document.createElement('li'); li.textContent = s.text; list.appendChild(li); });
  $('setup-blocked').textContent = d.blocked.join(' ');
  $('setup-blocked').classList.toggle('hidden', !d.blocked.length);
  $('setup-ok').disabled = d.blocked.length > 0 || !d.steps.length;
  $('setup-ok').classList.remove('hidden');
  $('setup-later').textContent = 'Not now';
  $('setup-dlg-msg').textContent = '';
  $('setup-dlg').showModal();
}
async function loadTuneInfo() {
  const d = await api('/api/tune-info');
  if (!d.ok) return;
  favNets = d.nets || [];
  favNetLinks = d.net_links || {};
  favModes = d.modes || favModes;
  tnNets();
}
function paintModes() {
  $('cd-tune').dataset.mode = $('t-mode') ? $('t-mode').value : '';
}
let connMsgTimer = null, connBusy = false, connBack = false;
let netAsk = null;
function netHide() {
  $('t-ask').classList.add('hidden');
  netAsk = null;
}
async function netAnswer(action) {
  const a = netAsk;
  netHide();
  if (!a) return;
  if (action === '') { note(a.box.msg, '', ''); return; }
  const text = action === 'add' ? 'Adding the network to Node Controller and tuning...' : 'Tuning...';
  await connectFlow(Object.assign({}, a.body, {net_action: action}), a.label, text, a.url, a.box);
}
const TN_MODES = ['ASL', 'EchoLink', 'DMR', 'STFU', 'YSF', 'P25', 'NXDN', 'DSTAR', 'M17'];
const TN_SEARCH = ['ASL', 'EchoLink'];
const TN_HINT = {ASL: 'Node #, call or place', EchoLink: 'Node # or call', DMR: 'TG number', STFU: 'TG, ID or name', YSF: 'Name, # or IP:port', P25: 'TG # or host',
  NXDN: 'TG # or host', DSTAR: 'REF001 C or callsign', M17: 'M17-USA A'};
const TN_NOUN = {ASL: 'nodes', EchoLink: 'stations', STFU: 'talkgroups', YSF: 'reflectors', P25: 'talkgroups', NXDN: 'talkgroups', DSTAR: 'reflectors', M17: 'reflectors'};
const TN_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const TN_TYPED = {ASL: /^\d{1,7}$/, EchoLink: /^\d{1,6}$/, DMR: /^\d{1,8}$/, STFU: /^\d{1,8}$/, P25: /^\d{1,8}$/, NXDN: /^\d{1,8}$/,
  YSF: /^(\d{1,5}|[A-Za-z0-9.-]+:\d{1,5})$/,
  DSTAR: /^(?:(?:REF|XRF|DCS)\d{3}|[A-Z0-9]{1,3}\d[A-Z]{1,4})(?:\s+[A-Z])?$/i,
  M17: /^[A-Z0-9]+-[A-Z0-9-]{1,14}(?:\s+(?:[A-Z]|@ALL))?$/i};
const SIZE_SETS = {
  tn: {store: 'nlTuneSize', def: {h: 40, font: 14}},
  lt: {store: 'nlListenSize', def: {font: 15, h: 64}},
  sett: {store: 'nlSetupSize', def: {font: 15, h: 44}}};
const tnLists = {};
let favNetLinks = {}, tnWin = null, tnTimer = 0, tnState = {};
function tnRemember() {
  tnState = {mode: $('t-mode').value, net: $('t-net').value || tnState.net, mod: $('t-mod').value,
    find: $('t-find').value, pick: $('t-pick').value};
}
function sizeLoad(p) {
  let v = {};
  try { v = JSON.parse(localStorage.getItem(SIZE_SETS[p].store) || '{}') || {}; } catch (e) {}
  const def = SIZE_SETS[p].def;
  Object.keys(def).forEach((k) => {
    const n = Number(v[k]), r = $(p + '-' + k);
    r.value = Number.isFinite(n) && n >= Number(r.min) && n <= Number(r.max) ? n : def[k];
  });
  sizeApply(p, false);
}
function sizeApply(p, save) {
  const v = {};
  Object.keys(SIZE_SETS[p].def).forEach((k) => {
    v[k] = Number($(p + '-' + k).value);
    document.documentElement.style.setProperty('--' + p + '-' + k, v[k] + 'px');
    $(p + '-' + k + '-v').textContent = v[k] + ' px';
  });
  if (save) { try { localStorage.setItem(SIZE_SETS[p].store, JSON.stringify(v)); } catch (e) {} }
}
function sizeReset(p) {
  const def = SIZE_SETS[p].def;
  Object.keys(def).forEach((k) => { $(p + '-' + k).value = def[k]; });
  sizeApply(p, false);
  try { localStorage.removeItem(SIZE_SETS[p].store); } catch (e) {}
}
function sizeInit(p) {
  Object.keys(SIZE_SETS[p].def).forEach((k) => $(p + '-' + k).addEventListener('input', () => sizeApply(p, true)));
  $(p + '-reset').addEventListener('click', () => sizeReset(p));
  sizeLoad(p);
}
function tnInit() {
  const m = $('t-mode');
  TN_MODES.forEach((x) => addOption(m, x, modeName(x)));
  m.value = 'ASL';
  $('t-find').value = tnState.find || '';
  $('t-mode').addEventListener('change', () => { tnMode(false); paintModes(); });
  $('t-net').addEventListener('change', () => { tnButtons(); tnRemember(); });
  $('t-mod').addEventListener('change', () => { tnButtons(); tnRemember(); });
  $('t-find').addEventListener('input', () => {
    tnButtons();
    clearTimeout(tnTimer);
    const m = $('t-mode').value;
    tnTimer = setTimeout(() => { if (TN_SEARCH.includes(m)) tnSearch(m); else tnFill(); tnRemember(); }, TN_SEARCH.includes(m) ? 300 : 150);
  });
  $('t-find').addEventListener('keydown', (e) => { if (e.key === 'Enter') tnConnect(); });
  $('t-pick').addEventListener('change', () => { tnMods(); tnButtons(); tnRemember(); });
  $('t-go').addEventListener('click', tnConnect);
  $('t-disc').addEventListener('click', () => linksDisconnect('t-msg'));
  $('t-lh').addEventListener('click', tnOpenLink);
  sizeInit('tn');
  tnMode(true);
}
function tnNets() {
  const sel = $('t-net'), keep = sel.value || tnState.net;
  sel.innerHTML = '';
  if (!favNets.length) addOption(sel, '', 'No networks');
  favNets.forEach((n) => addOption(sel, n, n));
  if (keep && favNets.includes(keep)) sel.value = keep;
  const m = $('t-mode').value;
  if (m === 'DMR') tnFill();
  else if (TN_SEARCH.includes(m)) { if (!tnLists[m]) tnSearch(m); }
  else tnLoad(m);
}
function tnMods() {
  const m = $('t-mode').value, sel = $('t-mod'), keep = sel.value || tnState.mod, r = tnRow();
  const list = m === 'M17' ? ['@ALL'].concat((r && r[3] ? r[3] : TN_LETTERS).split('')) : TN_LETTERS.split('');
  sel.innerHTML = '';
  list.forEach((x) => addOption(sel, x, x === '@ALL' ? 'All' : x));
  sel.value = list.includes(keep) ? keep : (m === 'M17' ? '@ALL' : 'C');
}
function tnMode(first) {
  const m = $('t-mode').value;
  netHide();
  note('t-msg', '', '');
  $('t-net').classList.toggle('hidden', m !== 'DMR');
  $('t-mod').classList.toggle('hidden', m !== 'DSTAR' && m !== 'M17');
  $('t-pick').classList.toggle('hidden', m === 'DMR');
  $('t-find').placeholder = TN_HINT[m];
  if (!first) $('t-find').value = '';
  tnMods();
  tnFill(first ? tnState.pick : '');
  if (TN_SEARCH.includes(m)) { if (authed) tnSearch(m, first ? tnState.pick : undefined); }
  else if (m !== 'DMR' && authed) tnLoad(m);
  if (!first) tnRemember();
}
async function tnLoad(m, want) {
  const c = tnLists[m];
  if (c && (c.loading || Date.now() - c.at < 300000)) return;
  const s = tnLists[m] = Object.assign(c || {rows: [], files: [], found: false}, {loading: true, at: Date.now(), err: ''});
  if (!c) tnFill(want);
  const d = await api('/api/tune-list?mode=' + encodeURIComponent(m));
  s.loading = false;
  if (d.ok) {
    s.rows = d.rows || [];
    s.found = !!d.found;
    s.files = d.files || [];
    s.rows.forEach((r) => { r.s = (r[0] + ' ' + r[1]).toLowerCase(); });
  } else {
    s.at = 0;
    s.err = d.error || 'Could not load the list.';
  }
  if ($('t-mode').value === m) tnFill(want);
}
let tnSeq = 0;
async function tnSearch(m, want) {
  const q = $('t-find').value.trim();
  const seq = ++tnSeq;
  if (q.length < 2) {
    tnLists[m] = {search: true, short: true, rows: [], found: true, files: [], count: 0};
    tnFill(want);
    return;
  }
  const d = await api('/api/tune-search?mode=' + encodeURIComponent(m) + '&q=' + encodeURIComponent(q));
  if (seq !== tnSeq || $('t-mode').value !== m) return;
  const s = tnLists[m] = {search: true, rows: d.rows || [], found: !!d.found, files: d.file ? [d.file] : [],
    count: d.count || 0, err: d.ok ? '' : (d.error || 'Search failed.')};
  s.rows.forEach((r) => { r.s = (r[0] + ' ' + r[1]).toLowerCase(); });
  tnFill(want);
}
let tunedNow = '';
function tnLinkedB(tb) {
  if (!tb) return false;
  const num = String(tb.num);
  if (tb.mode === 'ASL') return linkedNodes.has(num);
  if (tb.mode === 'EchoLink') return linkedNodes.has('3' + num.padStart(6, '0'));
  return !!tunedNow && tunedNow.includes(num);
}
function tnLinked() { return tnLinkedB(tnBody()); }
let tnLast = null, tnPrimed = false, defaultMode = '';
function tnSnap() {
  return {mode: $('t-mode').value, net: $('t-net').value, mod: $('t-mod').value,
    find: $('t-find').value, pick: $('t-pick').value};
}
function defaultSel() {
  return {mode: TN_MODES.includes(defaultMode) ? defaultMode : 'ASL', net: '', mod: '', find: '', pick: ''};
}
function tnSetSel(s) {
  tnPrimed = true;
  tnState = {mode: s.mode, net: s.net || '', mod: s.mod || '', find: s.find || '', pick: s.pick || ''};
  $('t-mode').value = s.mode;
  paintModes();
  $('t-find').value = s.find || '';
  tnMode(true);
  if (s.net && favNets.includes(s.net)) $('t-net').value = s.net;
  if (s.mod) $('t-mod').value = s.mod;
  tnButtons();
}
function connectTabEnter() {
  if (tnLast && tnLinkedB(tnLast.b)) tnSetSel(tnLast.snap);
  else tnSetSel(defaultSel());
  if (!daPoll) daStatus();
}
function tnRow() {
  const s = tnLists[$('t-mode').value], v = $('t-pick').value;
  return s && v ? s.rows.find((r) => r[0] === v) || null : null;
}
function tnFill(want) {
  const m = $('t-mode').value, s = tnLists[m], sel = $('t-pick');
  if (m === 'DMR') {
    $('t-list').textContent = favNets.length ? 'Type the talkgroup number.' : 'Add a DMR network on the Setup tab (Digital card) first.';
    tnButtons();
    return;
  }
  const keep = want !== undefined ? want : (sel.value || tnState.pick || '');
  sel.textContent = '';
  if (s && s.search && (s.short || !s.found || s.err)) {
    addOption(sel, '', 'Type to search...');
    sel.disabled = true;
    $('t-list').textContent = s.err ? s.err : s.short ? 'Type 2 or more characters to search, or a ' + (m === 'ASL' ? 'node' : 'station') + ' number.'
      : 'No ' + (m === 'ASL' ? 'AllStar node list (' + (s.files[0] || 'astdb.txt') + ')' : 'EchoLink station list (is EchoLink loaded in Asterisk?)')
        + ' was found. You can still type a number.';
    tnButtons();
    return;
  }
  if (!s || s.loading || !s.found) {
    addOption(sel, '', s && !s.loading ? 'No list' : 'Loading...');
    sel.disabled = true;
    $('t-list').textContent = !s || s.loading ? 'Loading the ' + modeName(m) + ' list...'
      : (s.err || 'No ' + modeName(m) + ' list was found on the Pi.') + ' You can still type one.';
    tnButtons();
    return;
  }
  const words = $('t-find').value.toLowerCase().split(/\s+/).filter(Boolean);
  const list = s.search ? s.rows : s.rows.filter((r) => words.every((w) => r.s.includes(w)));
  addOption(sel, '', list.length ? 'Select... (' + list.length.toLocaleString() + ')' : 'No matches');
  const frag = document.createDocumentFragment();
  list.forEach((r) => { const o = document.createElement('option'); o.value = r[0]; o.textContent = r[1]; frag.appendChild(o); });
  sel.appendChild(frag);
  sel.disabled = list.length === 0;
  if (keep && list.some((r) => r[0] === keep)) sel.value = keep;
  else if (list.length === 1) sel.value = list[0][0];
  const n = list.length, t = s.search ? s.count : s.rows.length, noun = t === 1 ? TN_NOUN[m].slice(0, -1) : TN_NOUN[m];
  $('t-list').textContent = s.search ? (t === 0 ? 'No matches (' + s.files.join(', ') + ').'
      : n < t ? 'Showing ' + n + ' of ' + t.toLocaleString() + ' matches (' + s.files.join(', ') + '). Type more to narrow it down.'
      : t.toLocaleString() + ' ' + (t === 1 ? 'match' : 'matches') + ' (' + s.files.join(', ') + ').')
    : (n === t ? t.toLocaleString() + ' ' + noun
      : 'Showing ' + n.toLocaleString() + ' of ' + t.toLocaleString() + ' ' + noun) + ' (' + s.files.join(', ') + ').';
  if (m === 'M17') tnMods();
  tnButtons();
}
function tnBody() {
  const m = $('t-mode').value, r = tnRow(), t = $('t-find').value.trim(), typed = TN_TYPED[m].test(t) ? t : '';
  const b = {mode: m};
  if (m === 'DMR') {
    b.net = $('t-net').value;
    b.num = typed;
  } else if (r) {
    b.num = r[0];
    if (['YSF', 'STFU', 'ASL', 'EchoLink'].includes(m)) b.label = r[1];
  } else {
    b.num = typed;
  }
  if (m === 'DSTAR' || m === 'M17') b.module = $('t-mod').value;
  return b.num && (m !== 'DMR' || b.net) ? b : null;
}
function tnName(b) {
  return modeName(b.mode) + (b.net ? ' ' + b.net : '') + ' ' + (b.label || b.num) + (b.module && !/\s/.test(b.num) ? ' ' + b.module : '');
}
function tnLink() {
  const m = $('t-mode').value;
  if (m === 'DMR') return favNetLinks[$('t-net').value] || '';
  const r = tnRow();
  return r ? r[2] || '' : '';
}
function tnButtons() {
  const ok = !!tnBody();
  const on = tnLinked(), go = $('t-go');
  go.textContent = 'Connect';
  go.disabled = connBusy || on || !ok;
  $('t-lh').classList.toggle('lh-off', !tnLink());
  $('t-lh').setAttribute('aria-disabled', tnLink() ? 'false' : 'true');
  $('t-lh').disabled = !tnLink();
}
function tnOpenLink() {
  const u = tnLink();
  if (!u) return;
  if (tnWin && !tnWin.closed) { tnWin.location.href = u; tnWin.focus(); }
  else tnWin = window.open(u, 'nt_lh');
}
async function tnConnect() {
  const b = tnBody();
  if (!b || connBusy) return;
  netHide();
  tnRemember();
  const link = TN_SEARCH.includes(b.mode);
  await connectFlow(b, (link ? 'Connecting to ' : 'Tuning ') + tnName(b) + '...', link ? 'Connecting... (checking the link for up to 15 s)' : 'Tuning...',
    '/api/tune', {msg: 't-msg', btn: 't-go', ask: 't-ask'});
  if ($('t-msg').classList.contains('ok')) {
    tnLast = {b: b, snap: tnSnap(), seen: false};
  }
  tnButtons();
}
let daPoll = null, daMine = false, daList = 'md380-emu, Analog_Bridge, MMDVM_Bridge, USRP2M17 and Asterisk';
function daShow(d) {
  if (!d || !d.ok) return;
  if (d.installed) {
    daList = d.installed.length ? d.installed.join(', ') : '';
  }
  $('da-btn').disabled = !!d.running;
  const steps = d.steps || [];
  if (d.running) {
    const i = steps.findIndex((x) => x.state === 'running');
    note('da-msg', 'warn', i >= 0 ? steps[i].name + '... (' + (i + 1) + ' of ' + steps.length + ')' : 'Working...');
  } else if (daMine && d.message) {
    const bad = steps.filter((x) => x.state === 'failed' || x.state === 'warn').map((x) => x.name + ': ' + x.note);
    note('da-msg', d.level === 'err' ? 'err' : (bad.length ? 'warn' : 'ok'), d.message + (bad.length ? ' ' + bad.join('; ') + '.' : ''));
  }
}
async function daStatus() {
  daPoll = null;
  const d = await api('/api/disconnect-all/status');
  daShow(d);
  if (d.ok && d.running) { daPoll = setTimeout(daStatus, 1000); return; }
  if (d.ok && daMine && d.finished) { tnLast = null; tnButtons(); pollStatus(); }
}
async function linksDisconnect(msgId) {
  tnLast = null;
  note(msgId, '', 'Disconnecting...');
  try { setMsg(msgId, await post('/api/disconnect-links', {})); }
  finally { connectLabel(); tnButtons(); }
  setTimeout(pollStatus, 1000);
}
async function loadDigital() {
  const d = await api('/api/digital');
  if (!d.ok) return;
  const nc = d.control === 'nc';
  $('dg-control').textContent = nc ? 'Node Controller is running: Node Recorder tunes through it' : 'Solo: Node Recorder tunes DVSwitch and M17 itself';
  const found = [];
  found.push(d.dvswitch ? 'dvswitch.sh' : 'no dvswitch.sh');
  if (d.analog_bridge) found.push('Analog_Bridge');
  found.push(d.m17 ? 'USRP2M17' : 'no USRP2M17');
  if (d.m17_hosts) found.push('M17Hosts.json');
  $('dg-found').textContent = found.join(' · ');
  $('dg-svc').textContent = Object.keys(d.services || {}).map((k) => k + ' ' + (SVC_TXT[d.services[k]] || d.services[k])).join(' · ') || '-';
  $('dg-tuned').textContent = d.tuned || 'nothing';
  const b = d.bridges || {};
  $('dg-dbridge').value = d.set.digital_bridge; $('dg-dbridge').placeholder = b.digital || 'none';
  $('dg-mbridge').value = d.set.m17_bridge; $('dg-mbridge').placeholder = b.m17 || 'none';
  $('dg-call').value = d.set.callsign; $('dg-call').placeholder = d.callsign || 'none';
  const src = (v, s) => v ? v + (s && s !== 'set here' ? ' (from ' + s + ')' : '') : 'none found';
  $('dg-auto').textContent = 'In use: digital bridge ' + src(b.digital, b.digital_src) + ', M17 bridge ' + src(b.m17, b.m17_src)
    + ', callsign ' + src(d.callsign, d.callsign_src) + '. Leave a box empty to find it on its own.';
  $('nw-import').disabled = !d.dash_nets;
  sum('dig', [nc ? 'Node Controller' : 'Solo', d.tuned || '', (d.nets || []).length ? (d.nets.length + ' DMR network' + (d.nets.length > 1 ? 's' : '')) : ''].filter((x) => x).join(' · '));
  nets = (d.nets || []).map((n) => ({orig: n.name, name: n.name, address: n.address, url: n.url, password: '', has: n.has_password}));
  netMax = d.net_max || 10;
  drawNets();
}
function drawNets() {
  const box = $('nw-rows');
  box.innerHTML = '';
  nets.forEach((n, i) => {
    const row = document.createElement('div'); row.className = 'net-row';
    const mk = (key, ph, aria, cls, type) => {
      const el = document.createElement('input'); el.value = n[key] || ''; el.placeholder = ph;
      el.setAttribute('aria-label', aria + ' ' + (i + 1)); if (cls) el.className = cls; if (type) el.type = type;
      el.autocomplete = 'off'; el.oninput = () => { n[key] = el.value; }; return el;
    };
    const x = document.createElement('button'); x.type = 'button'; x.textContent = '✕'; x.setAttribute('aria-label', 'Remove network ' + (i + 1));
    x.onclick = () => { nets.splice(i, 1); drawNets(); };
    row.appendChild(mk('name', 'Name', 'Network name', '', ''));
    row.appendChild(mk('address', 'host:port', 'Network address', '', ''));
    row.appendChild(mk('password', n.has ? '(saved)' : 'Password', 'Network password', 'net-pw', 'password'));
    row.appendChild(x);
    row.appendChild(mk('url', 'Dashboard link (optional)', 'Network link', 'net-url', ''));
    box.appendChild(row);
  });
  $('nw-add').disabled = nets.length >= netMax;
}
function nwAdd() { if (nets.length < netMax) { nets.push({orig: '', name: '', address: '', url: '', password: '', has: false}); drawNets(); } }
async function nwSave() {
  const d = await post('/api/dmr-networks', {nets: nets.map((n) => ({orig: n.orig, name: n.name.trim(), address: n.address.trim(), url: (n.url || '').trim(), password: n.password}))});
  setMsg('nw-msg', d);
  if (d.ok) { loadDigital(); loadTuneInfo(); loadSchedSources(); }
}
async function nwImport() {
  const d = await post('/api/dmr-networks/import', {});
  setMsg('nw-msg', d);
  if (d.ok) { loadDigital(); loadTuneInfo(); loadSchedSources(); }
}
async function dgSave() {
  const d = await post('/api/digital', {digital_bridge: $('dg-dbridge').value.trim(), m17_bridge: $('dg-mbridge').value.trim(), callsign: $('dg-call').value.trim()});
  setMsg('dg-msg', d);
  if (d.ok) loadDigital();
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
let sysmonPort = null;
const TABS = ['connect', 'record', 'setup'];
const FOLDS = ['setup', 'sched', 'dig', 'node', 'store', 'conv', 'rx', 'log'];
const CFG_BOOL = ['https'];
const SVC_TXT = {active: 'running', inactive: 'stopped', failed: 'failed', missing: 'not installed', unknown: '?'};
function showTab(name) {
  if (!authed || TABS.indexOf(name) < 0) name = 'connect';
  tab = name;
  TABS.forEach((t) => {
    $('tab-' + t).classList.toggle('hidden', t !== name || !authed);
    const b = $('nav-' + t);
    if (t === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  if (name === 'connect') { loadTuneInfo(); connectTabEnter(); loadSchedSources(); }
  if (name === 'record') { loadSchedule(); loadStorage(); }
  if (name === 'setup') { loadStorage(); loadRecNode(); loadConfig(); loadSchedule(); loadDigital(); loadConv(); }
  document.querySelector('main').classList.toggle('fit', name === 'record' || name === 'connect');
}
function render() {
  const wasOpen = $('login-screen').classList.contains('open');
  $('login-screen').classList.toggle('open', !authed);
  if (!authed && !wasOpen) $('pw').focus();
  $('nav').classList.toggle('hidden', !authed);
  $('logout').classList.toggle('hidden', !authed);
  if (!authed) { TABS.forEach((t) => $('tab-' + t).classList.add('hidden')); return; }
  showTab('connect');
}
async function whoami() {
  const d = await api('/api/whoami');
  authed = !!d.authed;
  hostLinks(d);
  sysmonPort = d.sysmon_port || null;
  if (!d.backend) $('login-msg').textContent = 'No root password is set on this Pi, so login cannot work.';
  render();
  if (authed) setupCheck();
}
async function login(ev) {
  ev.preventDefault();
  $('login-btn').disabled = true;
  $('login-msg').textContent = '';
  const d = await post('/api/login', {password: $('pw').value});
  $('login-btn').disabled = false;
  $('pw').value = '';
  if (d.ok) { authed = true; render(); pollHostLinks(); setupCheck(); }
  else $('login-msg').textContent = d.error || 'Login failed.';
}
async function logout() {
  await post('/api/logout');
  authed = false;
  render();
}
function foldSet(k, open) {
  const b = $('cd-' + k).querySelector('.fold-btn');
  $('cb-' + k).classList.toggle('hidden', !open);
  b.setAttribute('aria-expanded', open ? 'true' : 'false');
  b.querySelector('.fold-i').textContent = open ? '▾' : '▸';
  if (!open) return;
  if (k === 'sched') loadSchedule();
  if (k === 'dig') loadDigital();
  if (k === 'node') loadRecNode();
  if (k === 'log') pollLog();
}
function pollEvery(fn, ms) {
  setTimeout(async () => {
    try { await fn(); } catch (e) {}
    pollEvery(fn, ms);
  }, ms);
}
async function pollStatus() {
  if (!authed || document.visibilityState === 'hidden') return;
  const d = await api('/api/status');
  if (!d || d.ok === false) return;
  lastStatus = d;
  $('st-node').textContent = d.node || '(not set)';
  const feedCls = d.receiving ? 'on' : (d.packets ? 'warn' : 'err');
  const feedTxt = d.receiving ? ('receiving, ' + d.packets_per_sec + ' packets/s')
    : (d.last_rx_age != null ? 'no audio for ' + Math.round(d.last_rx_age) + ' s' : 'nothing received yet');
  $('st-feed').className = 'dot ' + feedCls;
  $('st-feed-t').textContent = d.receiving ? 'feed' : (d.last_rx_age != null ? 'no feed ' + Math.round(d.last_rx_age) + ' s' : 'no feed yet');
  $('st-feed-w').title = 'Audio from Asterisk: ' + feedTxt;
  $('st-active').className = 'dot ' + (d.audio_active ? 'rx' : '');
  $('st-level').textContent = fmtDb(d.peak_db);
  $('meter-bar').style.width = dbPct(d.peak_db) + '%';
  if (d.rx_load_pct != null) $('rx-load').textContent = d.rx_load_pct + ' % of one CPU core (last 5 s)';
  $('rn-udp').textContent = d.udp_error ? d.udp_error : (d.receiving ? 'receiving audio' : 'listening, no audio yet');
  const talker = d.talker || {};
  $('rn-talker').textContent = talker.active ? 'Node Talker is running: audio comes from its forward.'
    : (talker.installed ? 'Node Talker is installed but stopped: Node Recorder listens on the node itself.' : 'Node Talker is not installed.');
  const tb = $('s-links');
  tb.innerHTML = '';
  const links = d.links || [];
  const recNode = (d.rec_node && d.rec_node.node) || '';
  links.forEach((l) => {
    const tr = document.createElement('tr');
    [l.node + (l.node === recNode ? ' (recorder)' : ''), '', l.dir, l.time, l.state].forEach((v) => {
      const td = document.createElement('td'); td.textContent = v || ''; td.title = v || ''; tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  $('s-nolinks').classList.toggle('hidden', links.length > 0);
  $('s-links-err').classList.toggle('hidden', d.links_ok !== false);
  linkedNodes = new Set(links.map((l) => l.node));
  $('t-now').textContent = d.tuned_now ? 'Tuned: ' + d.tuned_now : '';
  tunedNow = d.tuned_now || '';
  defaultMode = d.default_mode || '';
  if (tnLast) {
    if (tnLinkedB(tnLast.b)) tnLast.seen = true;
    else if (tnLast.seen) tnLast = null;
  }
  if (!tnPrimed && authed) tnSetSel(defaultSel());
  tnButtons();
}
async function connectFlow(body, listenText, connectText, url, box) {
  url = url || '/api/tune';
  box = box || {msg: 't-msg', btn: 't-go', ask: 't-ask'};
  $(box.btn).disabled = true;
  connBusy = true;
  note(box.msg, '', connectText);
  let d = {};
  try { d = await post(url, body); }
  finally { $(box.btn).disabled = false; connBusy = false; }
  setMsg(box.msg, d);
  if (!d.ok && d.need_net) { netAsk = {url: url, body: body, box: box, label: listenText}; $(box.ask).classList.remove('hidden'); }
  pollStatus();
  return d;
}
async function daGo() {
  if (!confirm('Disconnect All?\n\nDrops every link and restarts ' + (daList || 'the node services') +
               '. The node is off the air until they are back up, up to a minute or two.')) return;
  $('da-btn').disabled = true;
  const d = await post('/api/disconnect-all', {});
  if (!d.ok) { $('da-btn').disabled = false; note('da-msg', 'err', d.error || 'Could not start Disconnect All.'); return; }
  daMine = true;
  tnLast = null;
  note('da-msg', 'warn', d.message || 'Disconnect All started.');
  if (daPoll) clearTimeout(daPoll);
  daStatus();
}
async function setupApply() {
  $('setup-ok').disabled = true;
  note('setup-dlg-msg', '', 'Setting up. Asterisk restarts, so the links on this node drop for a moment...');
  const d = await post('/api/setup/apply', {});
  if (!d.ok) { $('setup-ok').disabled = false; note('setup-dlg-msg', 'err', d.error || 'Setup did not finish.'); return; }
  note('setup-dlg-msg', 'ok', d.message || 'Done.');
  $('setup-ok').classList.add('hidden');
  $('setup-later').textContent = 'Close';
  loadRecNode(); loadConfig();
}
async function astRestart(msgId) {
  if (!confirm('Restart Asterisk now? Every link on this node drops and reconnects.')) return;
  note(msgId, '', 'Restarting Asterisk...');
  setMsg(msgId, await post('/api/asterisk/restart', {}));
  setTimeout(loadRecNode, 4000);
}
async function loadRecNode() {
  const d = await api('/api/recnode');
  if (!d.ok) { $('rn-state').textContent = d.error || 'Could not read rpt.conf.'; sum('node', 'Could not read rpt.conf'); return; }
  $('rn-node').textContent = d.node;
  $('rn-rxch').textContent = d.rxchannel;
  $('rn-main').textContent = d.main || '(not set)';
  const talker = d.owner === 'talker';
  let s;
  if (d.error) s = d.error;
  else if (!d.defined) s = 'Not set up.';
  else if (!d.owner) s = 'rpt.conf has a [' + d.node + '] node that Node Recorder did not add.';
  else if (talker) s = 'Set up by Node Talker, which owns this node.';
  else if (!d.nodes_line) s = 'Its [nodes] line is missing or has the wrong IAX port: press Add node ' + d.node + ' to fix it.';
  else if (!d.rx_ok) s = 'Set up, but its rxchannel is not ' + d.rxchannel + '.';
  else if (d.linked === null) s = 'Set up. Asterisk does not know it yet: restart Asterisk.';
  else s = d.linked ? 'Set up and linked to node ' + d.main + '.' : 'Set up; linking to node ' + d.main + ' (checked every 20 s).';
  $('rn-state').textContent = s;
  sum('node', d.error ? 'Could not read rpt.conf' : !d.defined ? 'Not set up' : talker ? 'Node Talker owns it'
    : !(d.nodes_line && d.rx_ok) ? 'Needs attention' : d.linked === null ? 'Restart Asterisk' : d.linked ? 'Set up and linked' : 'Set up, linking');
  $('rn-add').disabled = d.defined && (talker || d.nodes_line);
  $('rn-remove').disabled = !(d.defined && d.owner === 'recorder') && !d.nodes_line;
}
const STATE_TXT = {idle: 'Idle.', connecting: 'Connecting...', recording: 'Recording', stopping: 'Stopping the recording...', disconnecting: 'Disconnecting...'};
const RESULT_TXT = {ok: 'done', connect_failed: 'could not connect', start_failed: 'could not start', link_lost: 'link dropped',
  stop_failed: 'did not stop cleanly', write_failed: 'could not write the file', disconnect_failed: 'did not disconnect', aborted: 'stopped early', interrupted: 'interrupted by a restart',
  missed: 'missed', error: 'failed'};
function schedDays(days) {
  return days.length === 7 ? 'Every day' : days.map((d) => ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d]).join(' ');
}
function schedDstar(num) {
  const m = /^([A-Z0-9]{3,6}) *([A-Z])L$/.exec(String(num || '').toUpperCase());
  return m ? [m[1], m[2]] : [String(num || '').split(' ')[0], String(num || '').split(' ')[1] || ''];
}

function schedTarget(t) {
  if (t.label) return t.label;
  if (t.mode === 'DSTAR') { const p = schedDstar(t.num); return 'D-STAR ' + p[0] + (t.module || p[1] ? ' ' + (t.module || p[1]) : ''); }
  return t.mode + ' ' + t.num + (t.module ? ' ' + t.module : '');
}
async function loadSchedule() {
  if (!authed) return;
  const d = await api('/api/schedule');
  if (!d.ok) return;
  schedRows = d.entries;
  const st = d.status || {}, cur = st.current;
  $('rec-state').textContent = (STATE_TXT[st.state] || st.state) + (cur ? ' ' + cur.name + ' until ' + cur.end.slice(11) + (cur.dry_run ? ' (dry run)' : '') : '');
  $('rec-start').disabled = st.state !== 'idle';
  $('rec-stop').disabled = st.state !== 'connecting' && st.state !== 'recording';
  $('sch-note').textContent = 'Times are the Pi\'s clock (now ' + d.now + ').' + (d.dry_run ? ' Dry run: windows are walked through without connecting or recording.' : '');
  $('sch-err').textContent = d.error || '';
  $('sch-err').classList.toggle('hidden', !d.error);
  const rows = (id, manage) => {
    const tb = $(id);
    tb.innerHTML = '';
    d.entries.forEach((e) => {
      const tr = document.createElement('tr');
      const cell = (lines) => { const td = document.createElement('td'); lines.forEach((v, i) => { const x = document.createElement('div'); x.textContent = v || ''; if (i) x.className = 'muted small'; td.appendChild(x); }); tr.appendChild(td); };
      cell([e.name + (e.enabled ? '' : ' (off)'), schedTarget(e.target)]);
      cell([(e.kind === 'special' ? 'Special ' + e.date : schedDays(e.days)) + ' ' + e.start + '-' + e.end + ' ' + (e.format === 'pcm' ? 'PCM' : 'u-law'), 'Next: ' + (e.now ? 'now' : e.next)]);
      const tr2 = document.createElement('tr');
      const act = document.createElement('td');
      act.colSpan = 3;
      tr2.appendChild(act);
      const btn = (text, fn) => { const b = document.createElement('button'); b.className = 'btn'; b.type = 'button'; b.textContent = text; b.addEventListener('click', fn); act.appendChild(b); };
      btn('Dry run', () => schedDryRun(e.id));
      if (manage) {
        const on = document.createElement('input'); on.type = 'checkbox'; on.checked = e.enabled; on.title = 'On';
        on.addEventListener('change', () => schedToggle(e, on.checked));
        act.appendChild(on);
        btn('Edit', () => schedEdit(e));
        btn('Remove', () => schedRemove(e));
      }
      tb.appendChild(tr);
      tb.appendChild(tr2);
    });
  };
  rows('sch-rows', false);
  rows('sl-rows', true);
  $('sch-none').classList.toggle('hidden', d.entries.length > 0);
  $('sl-none').classList.toggle('hidden', d.entries.length > 0);
  sum('sched', d.entries.length + (d.entries.length === 1 ? ' entry' : ' entries'));
  $('sch-results').textContent = (st.results || []).slice(-5).reverse()
    .map((r) => r.name + ' ' + r.window.replace('T', ' ') + ': ' + (RESULT_TXT[r.result] || r.result) + (r.detail ? ' (' + r.detail + ')' : '')).join(' | ');
}
function fmtBytes(n) {
  if (n == null) return '-';
  return n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : Math.round(n / 1048576) + ' MB';
}
async function loadStorage() {
  if (!authed) return;
  const d = await api('/api/storage');
  if (!d.ok) return;
  $('rs-path').textContent = d.path + (d.kind === 'usb' ? ' (USB drive)' : d.kind === 'sd' ? ' (SD card)' : '');
  $('rs-source').textContent = d.source;
  $('rs-free').textContent = fmtBytes(d.free) + (d.total ? ' of ' + fmtBytes(d.total) : '');
  $('rs-files').textContent = d.files + ' file' + (d.files === 1 ? '' : 's') + ', ' + fmtBytes(d.bytes) + ' (keeps at most ' + d.cap_mb + ' MB)';
  $('rs-block').textContent = d.usable ? '' : 'Recording is blocked: ' + d.reason;
  $('rs-block').classList.toggle('hidden', !!d.usable);
  $('rs-conflict').textContent = d.conflict
    ? 'Two folders are set. Node Recorder uses ' + d.path + ' (the Recordings folder setting). Pibrary\'s library is at ' + d.pibrary_path + ', so Pibrary will not list these recordings.' : '';
  $('rs-conflict').classList.toggle('hidden', !d.conflict);
  sum('store', d.path);
}
let convTimer = null, convBuilt = false;
function convBuild(d) {
  const box = $('conv-list');
  box.textContent = '';
  d.encoders.forEach((e) => {
    const row = document.createElement('div');
    row.className = 'enc-opt';
    row.id = 'enc-' + e.id;
    const head = document.createElement('div');
    head.className = 'row';
    const lab = document.createElement('label');
    const radio = document.createElement('input');
    radio.type = 'radio'; radio.name = 'cfg-record_encoder'; radio.value = e.id;
    radio.addEventListener('change', convSum);
    const name = document.createElement('b');
    name.textContent = ' ' + e.label;
    lab.appendChild(radio); lab.appendChild(name);
    const st = document.createElement('span');
    st.className = 'small enc-st';
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'btn hidden'; btn.textContent = 'Install';
    btn.addEventListener('click', () => installEncoder(e.id));
    head.appendChild(lab); head.appendChild(st); head.appendChild(btn);
    const note = document.createElement('p');
    note.className = 'muted small';
    note.textContent = e.note + ' (apt package: ' + e.pkgs + '; file type ' + e.ext + ')';
    row.appendChild(head); row.appendChild(note);
    box.appendChild(row);
  });
  convBuilt = true;
}
function convPicked() {
  const r = document.querySelector('input[name="cfg-record_encoder"]:checked');
  return r ? r.value : '';
}
function convSum() {
  $('cfg-record_kbps').disabled = convPicked() === 'flac';
}
async function loadConv() {
  if (!authed) return;
  const d = await api('/api/convert');
  if (!d.ok) return;
  if (!convBuilt) convBuild(d);
  const sel = $('cfg-record_kbps');
  if (!sel.options.length) d.kbps_choices.forEach((k) => addOption(sel, String(k), k + ' kbps'));
  const run = d.job.running;
  if (!$('conv-list').contains(document.activeElement) && document.activeElement !== sel && document.activeElement !== $('cfg-record_convert')) {
    sel.value = String(d.kbps);
    $('cfg-record_convert').checked = !!d.enabled;
    const r = document.querySelector('input[name="cfg-record_encoder"][value="' + d.encoder + '"]');
    if (r) r.checked = true;
  }
  d.encoders.forEach((e) => {
    const row = $('enc-' + e.id);
    row.querySelector('.enc-st').textContent = e.installed ? 'installed' + (e.version ? ' (' + e.version + ')' : '') : 'not installed';
    const btn = row.querySelector('button');
    btn.classList.toggle('hidden', e.installed);
    btn.disabled = run;
  });
  convSum();
  const c = d.convert;
  $('conv-stat').textContent = (c.current ? 'Converting ' + c.current + '. ' : '') + (c.queued ? c.queued + ' waiting or running. ' : '') +
    (c.done || c.failed ? c.done + ' converted, ' + c.failed + ' failed since Node Recorder started.' : '') + (c.last ? ' Last: ' + c.last : '');
  const term = $('conv-term'), lines = d.job.lines;
  term.classList.toggle('hidden', !lines.length);
  if (lines.length) {
    const atEnd = term.scrollTop + term.clientHeight >= term.scrollHeight - 8;
    term.textContent = lines.join('\n');
    if (atEnd || run) term.scrollTop = term.scrollHeight;
  }
  const cur = d.encoders.find((e) => e.id === d.encoder);
  sum('conv', !d.enabled ? 'off (WAV kept)' : cur && !cur.installed ? cur.label + ' missing' : cur ? cur.label : '');
  const poll = run || c.queued > 0;
  if (poll && !convTimer) convTimer = setInterval(() => { if (tab === 'setup') loadConv(); }, 2000);
  if (!poll && convTimer) { clearInterval(convTimer); convTimer = null; }
}
async function saveConv() {
  note('conv-msg', '', 'Saving...');
  setMsg('conv-msg', await post('/api/config', {record_convert: $('cfg-record_convert').checked,
    record_encoder: convPicked(), record_kbps: $('cfg-record_kbps').value}));
  loadConv();
}
async function installEncoder(id) {
  note('conv-msg', '', 'Starting...');
  setMsg('conv-msg', await post('/api/convert/install', {encoder: id}));
  loadConv();
}
async function saveStore() {
  note('store-msg', '', 'Saving...');
  setMsg('store-msg', await post('/api/config', {record_path: $('cfg-record_path').value.trim(), record_max_mb: $('cfg-record_max_mb').value}));
  loadStorage();
}
async function schedDryRun(id) {
  note('sch-msg', '', 'Walking through the steps...');
  const d = await post('/api/schedule/dryrun', {id: id});
  setMsg('sch-msg', d);
  const box = $('sch-trace');
  box.textContent = '';
  (d.steps || []).forEach((s) => {
    const row = document.createElement('div');
    row.textContent = s.step + ': ' + (s.ok ? 'ok' : 'failed') + (s.msg ? ' - ' + s.msg : '');
    box.appendChild(row);
  });
  box.classList.toggle('hidden', !(d.steps && d.steps.length));
}
async function recNodeEnable() { setMsg('rn-msg', await post('/api/recnode/enable', {})); loadRecNode(); }
async function recNodeDisable() {
  if (!confirm('Remove node 1921 from rpt.conf? Recording stops working until it is added again.')) return;
  setMsg('rn-msg', await post('/api/recnode/disable', {})); loadRecNode();
}
async function loadConfig() {
  const d = await api('/api/config');
  if (!d.ok) return;
  CFG_BOOL.forEach((k) => { $('cfg-' + k).checked = !!d.config[k]; });
  $('cfg-record_path').value = d.config.record_path || '';
  $('cfg-record_max_mb').value = d.config.record_max_mb;
  sum('cfg', d.config.https ? 'HTTPS' : 'HTTP');
  $('tune-on').checked = !!d.config.tune_enabled;
  $('tune-rx').value = d.config.rx_gain_db;
  $('rx-hpf').checked = !!d.config.rx_hpf;
  $('rx-agc').checked = !!d.config.rx_agc;
  $('rx-gate').value = String(d.config.rx_gate);
  tuneUi();
}
function tuneUi() {
  const on = $('tune-on').checked;
  const clean = [];
  if ($('rx-hpf').checked) clean.push('300 Hz cut');
  if ($('rx-agc').checked) clean.push('auto level');
  if ($('rx-gate').value !== '0') clean.push('gate ' + ($('rx-gate').value === '2' ? 'strong' : 'light'));
  sum('rx', [on ? 'RX ' + fmtGain(Number($('tune-rx').value)) : ''].concat(clean).filter((x) => x).join(' · ') || 'Off (audio unchanged)');
  $('tune-rx').disabled = !on;
  $('tune-rx-v').textContent = fmtGain(Number($('tune-rx').value));
}
async function saveTune(msgId = 'rx-msg') {
  const body = {tune_enabled: $('tune-on').checked, rx_gain_db: $('tune-rx').value,
    rx_hpf: $('rx-hpf').checked, rx_agc: $('rx-agc').checked, rx_gate: $('rx-gate').value};
  setMsg(msgId, await post('/api/config', body));
}
async function saveConfig() {
  const body = {};
  CFG_BOOL.forEach((k) => { body[k] = $('cfg-' + k).checked; });
  setMsg('cfg-msg', await post('/api/config', body));
}
const SC_FIELDS = {ASL: {num: 'Node'}, EchoLink: {num: 'Number'}, DMR: {num: 'Talkgroup', net: true}, STFU: {num: 'Talkgroup'}, YSF: {num: 'Reflector'},
  P25: {num: 'Talkgroup'}, NXDN: {num: 'Talkgroup'}, DSTAR: {num: 'Reflector', mod: true}, M17: {num: 'Reflector', mod: true}};
let schedRows = [], schedSrc = null, schedEditId = '', schedLabel = '';
function schedDaysValue() {
  return Array.from($('sc-days').querySelectorAll('input:checked')).map((c) => Number(c.value));
}
function schedSetDays(days) {
  $('sc-days').querySelectorAll('input').forEach((c) => { c.checked = days.indexOf(Number(c.value)) >= 0; });
}
function schedFieldsShow() {
  const m = $('sc-mode').value, f = SC_FIELDS[m] || SC_FIELDS.ASL;
  $('sc-num-l').textContent = f.num;
  $('sc-net-w').classList.toggle('hidden', !f.net);
  $('sc-mod-w').classList.toggle('hidden', !f.mod);
  $('cd-sched-form').dataset.mode = m;
}
function schedNetFill(want) {
  const sel = $('sc-net'), nets = schedSrc ? schedSrc.nets : [];
  sel.innerHTML = '';
  addOption(sel, '', nets.length ? 'Network...' : 'Add a DMR network on the Setup tab first');
  nets.forEach((n) => addOption(sel, n, n));
  if (want && !nets.includes(want)) addOption(sel, want, want + ' (not in the list)');
  sel.value = want || '';
}
function schedPickFill() {
  const m = $('sc-mode').value, sel = $('sc-pick');
  sel.innerHTML = '';
  addOption(sel, '', 'Pick a favorite...');
  if (!schedSrc) return;
  [['talker', 'Node Talker'], ['controller', 'Node Controller']].forEach((src) => {
    const list = schedSrc[src[0]].map((f, i) => [f, i]).filter((x) => x[0].mode === m);
    if (!list.length) return;
    const g = document.createElement('optgroup');
    g.label = src[1];
    list.forEach((x) => { const o = document.createElement('option'); o.value = src[0] + ':' + x[1]; o.textContent = x[0].label || schedTarget(x[0]); g.appendChild(o); });
    sel.appendChild(g);
  });
}
async function loadSchedSources() {
  if (!authed) return;
  const d = await api('/api/schedule/sources');
  if (!d.ok) return;
  schedSrc = d;
  schedPickFill();
  schedNetFill($('sc-net').value);
  $('sc-src').textContent = 'Favorites to pick from, read only: Node Talker ' + (d.talker_found ? d.talker.length : 'not found')
    + ', Node Controller ' + (d.controller_found ? d.controller.length : 'not found') + '. A pick is copied into the entry; it does not stay linked.';
}
function schedModeChanged() {
  schedFieldsShow();
  schedPickFill();
  $('sc-num').value = ''; $('sc-mod').value = ''; schedNetFill(''); schedLabel = '';
}
function schedPick() {
  const v = $('sc-pick').value;
  if (!v || !schedSrc) return;
  const parts = v.split(':'), f = schedSrc[parts[0]][Number(parts[1])];
  if (!f) return;
  $('sc-num').value = f.num || '';
  $('sc-mod').value = f.module || '';
  schedNetFill(f.net || '');
  schedLabel = f.label || '';
  note('sc-msg', 'ok', 'Copied ' + (f.label || schedTarget(f)) + '. Changing it later in ' + (parts[0] === 'talker' ? 'Node Talker' : 'Node Controller') + ' will not change this entry.');
}
function schedClear(keepMsg) {
  schedEditId = ''; schedLabel = '';
  $('sc-title').textContent = 'Schedule a recording';
  $('sc-name').value = '';
  $('sc-special').checked = false; $('sc-date').value = ''; schedKindShow();
  schedSetDays([0, 1, 2, 3, 4, 5, 6]);
  $('sc-start').value = '20:00'; $('sc-end').value = '21:00';
  $('sc-mode').value = 'ASL';
  schedFieldsShow(); schedPickFill();
  $('sc-num').value = ''; $('sc-mod').value = ''; schedNetFill('');
  $('sc-format').value = 'ulaw'; $('sc-enabled').checked = true;
  if (!keepMsg) note('sc-msg', '', '');
}
function schedEntry(e, on) {
  return {id: e.id, name: e.name, enabled: on, days: e.days, start: e.start, end: e.end, target: e.target, format: e.format, kind: e.kind || 'regular', date: e.date || ''};
}
function schedKindShow() {
  const sp = $('sc-special').checked;
  $('sc-days').style.display = sp ? 'none' : 'flex';
  $('sc-date-w').classList.toggle('hidden', !sp);
  if (sp && !$('sc-date').value) {
    const d = new Date();
    $('sc-date').value = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
}
function schedFormEntry() {
  const m = $('sc-mode').value, f = SC_FIELDS[m] || SC_FIELDS.ASL;
  const target = {mode: m, num: $('sc-num').value.trim()};
  if (f.net) target.net = $('sc-net').value;
  if (f.mod && $('sc-mod').value.trim()) target.module = $('sc-mod').value.trim().toUpperCase();
  if (schedLabel) target.label = schedLabel;
  const sp = $('sc-special').checked;
  return {name: $('sc-name').value.trim(), enabled: $('sc-enabled').checked, days: sp ? [] : schedDaysValue(), start: $('sc-start').value,
    end: $('sc-end').value, target: target, format: $('sc-format').value, kind: sp ? 'special' : 'regular', date: sp ? $('sc-date').value : ''};
}
async function recStart() {
  $('rec-start').disabled = true;
  const e = schedFormEntry();
  setMsg('rec-msg', await post('/api/recording/start', {entry: {name: e.name, target: e.target, format: e.format}}));
  loadSchedule();
}
async function recStop() {
  $('rec-stop').disabled = true;
  setMsg('rec-msg', await post('/api/recording/stop', {}));
  loadSchedule();
}
async function schedSet() {
  const entry = schedFormEntry();
  if (schedEditId) entry.id = schedEditId;
  note('sc-msg', '', 'Saving...');
  const d = await post('/api/schedule/set', {entry: entry});
  setMsg('sc-msg', d);
  if (d.ok) { schedClear(true); loadSchedule(); }
}
function schedEdit(e) {
  schedEditId = e.id;
  $('sc-title').textContent = 'Change a recording';
  $('sc-name').value = e.name;
  schedSetDays(e.days);
  $('sc-special').checked = e.kind === 'special'; $('sc-date').value = e.date || ''; schedKindShow();
  $('sc-start').value = e.start; $('sc-end').value = e.end;
  $('sc-mode').value = e.target.mode;
  schedFieldsShow(); schedPickFill();
  let num = e.target.num || '', mod = e.target.module || '';
  if (e.target.mode === 'DSTAR') { const dp = schedDstar(num); num = dp[0]; mod = mod || dp[1]; }
  $('sc-num').value = num; $('sc-mod').value = mod;
  schedNetFill(e.target.net || '');
  schedLabel = e.target.label || '';
  $('sc-format').value = e.format; $('sc-enabled').checked = e.enabled;
  showTab('connect');
  note('sc-msg', '', 'Change it and press Set.');
  $('cd-sched-form').scrollIntoView();
}
async function schedToggle(e, on) {
  const d = await post('/api/schedule/set', {entry: schedEntry(e, on)});
  setMsg('sl-msg', d);
  loadSchedule();
}
async function schedRemove(e) {
  if (!confirm('Remove ' + e.name + ' from the schedule?')) return;
  setMsg('sl-msg', await post('/api/schedule/remove', {id: e.id}));
  if (schedEditId === e.id) schedClear();
  loadSchedule();
}
function schedInit() {
  Object.keys(SC_FIELDS).forEach((m) => addOption($('sc-mode'), m, modeName(m)));
  schedClear();
}
function initPage() {
  $('login-form').addEventListener('submit', login);
  $('logout').addEventListener('click', logout);
  TABS.forEach((t) => $('nav-' + t).addEventListener('click', () => showTab(t)));
  $('rn-add').addEventListener('click', recNodeEnable);
  $('rec-start').addEventListener('click', recStart);
  $('sc-special').addEventListener('change', schedKindShow);
  $('rec-stop').addEventListener('click', recStop);
  $('rn-remove').addEventListener('click', recNodeDisable);
  $('nw-add').addEventListener('click', nwAdd);
  $('nw-import').addEventListener('click', nwImport);
  $('dig-save').addEventListener('click', async () => { await nwSave(); await dgSave(); });
  $('t-net-add').addEventListener('click', () => netAnswer('add'));
  $('t-net-once').addEventListener('click', () => netAnswer('once'));
  $('t-net-no').addEventListener('click', () => netAnswer(''));
  tnInit();
  sizeInit('sett');
  $('conv-save').addEventListener('click', saveConv);
  $('setup-save').addEventListener('click', async () => { note('setup-msg', '', 'Saving...'); await saveConfig(); note('setup-msg', '', ''); });
  $('setup-restart').addEventListener('click', () => astRestart('setup-msg'));
  $('setup-ok').addEventListener('click', setupApply);
  $('setup-later').addEventListener('click', () => $('setup-dlg').close());
  $('rx-save').addEventListener('click', () => saveTune('rx-msg'));
  ['tune-on', 'tune-rx', 'rx-hpf', 'rx-agc', 'rx-gate'].forEach((id) => $(id).addEventListener('input', tuneUi));
  $('store-save').addEventListener('click', saveStore);
  $('dash-link').addEventListener('click', (ev) => { ev.preventDefault(); openNamedTab($('dash-link').href, $('dash-link').dataset.win || 'asl_dvs_dash'); });
  $('sys-reboot').addEventListener('click', doReboot);
  $('sys-shutdown').addEventListener('click', doShutdown);
  $('da-btn').addEventListener('click', daGo);
  schedInit();
  $('sc-mode').addEventListener('change', schedModeChanged);
  $('sc-pick').addEventListener('change', schedPick);
  ['sc-num', 'sc-mod', 'sc-net'].forEach((id) => $(id).addEventListener('input', () => { schedLabel = ''; }));
  $('sc-set').addEventListener('click', schedSet);
  $('sc-clear').addEventListener('click', () => schedClear());
  setInterval(pollHostLinks, 30000);
  FOLDS.forEach((k) => $('cd-' + k).querySelector('.fold-btn').addEventListener('click', () => foldSet(k, !foldOpen(k))));
  whoami();
  pollEvery(pollStatus, 1500);
  pollEvery(pollLog, 3000);
  pollEvery(() => (tab === 'record' ? loadSchedule() : null), 4000);
  pollEvery(() => (tab === 'record' ? loadStorage() : null), 15000);
}
document.addEventListener('DOMContentLoaded', initPage);
"""

_ICON_CONNECT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"></path><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"></path></svg>'
_ICON_RECORD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8"></circle><circle cx="12" cy="12" r="3.5" fill="currentColor"></circle></svg>'
_ICON_SETUP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"></path><circle cx="16" cy="7" r="2"></circle><circle cx="10" cy="17" r="2"></circle></svg>'

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
html[data-theme="light"]{filter:invert(1) hue-rotate(180deg);--red:#ff7d8c;--red2:#ff7d8c;--red-line:#ff7d8c;--green:#44be99;--amber:#ce9e44;--blue:#59b9de;--teal:#44bcb0;--accent:#44bcb0;--fcs:#51c1af;--orange:#e89542;--cloudflare:#ed9647;--pink:#ff78d2;--purple:#d778ff;--lime:#9bab41}
html[data-theme="light"] img,html[data-theme="light"] video,html[data-theme="light"] canvas,html[data-theme="light"] iframe,html[data-theme="light"] input[type="checkbox"],html[data-theme="light"] input[type="radio"]{filter:invert(1) hue-rotate(180deg)}
html[data-theme="light"] *{text-shadow:none!important}
.theme-row{grid-column:1/-1;display:flex;justify-content:flex-end;align-items:center;gap:.5rem;margin:1rem 0 .4rem;padding:0 .2rem}
.theme-row .theme-lbl{font-size:.72rem;color:#aab8cc;letter-spacing:.04em}
.theme-sw{display:inline-flex;border:1px solid #3a5278;border-radius:4px;overflow:hidden}
.theme-sw>button.theme-opt{all:unset;box-sizing:border-box;cursor:pointer;padding:.28rem .75rem;font-family:inherit;font-size:.72rem;line-height:1.2;color:#aab8cc;background:transparent}
.theme-sw>button.theme-opt+button.theme-opt{border-left:1px solid #3a5278}
.theme-sw>button.theme-opt[aria-pressed="true"]{background:#1e2a3f;color:#ffffff}
.theme-sw>button.theme-opt:focus-visible{outline:2px solid #22d4ff;outline-offset:-2px}
</style>
<script>
(function(){var K="asl_dvs_theme",d=document.documentElement;function g(){try{return localStorage.getItem(K)==="light"?"light":"dark"}catch(e){return"dark"}}function a(t){d.setAttribute("data-theme",t);var b=document.querySelectorAll("[data-theme-set]");for(var i=0;i<b.length;i++)b[i].setAttribute("aria-pressed",String(b[i].getAttribute("data-theme-set")===t))}a(g());document.addEventListener("DOMContentLoaded",function(){a(g())});document.addEventListener("click",function(e){var b=e.target&&e.target.closest?e.target.closest("[data-theme-set]"):null;if(!b)return;var t=b.getAttribute("data-theme-set")==="light"?"light":"dark";try{localStorage.setItem(K,t)}catch(x){}a(t)});window.addEventListener("storage",function(e){if(e.key===K)a(g())})})();
</script>
<meta name="theme-color" content="#161e2e">
<title>Node Recorder</title>
<style>__CSS__</style>
<style>
/* v0.9.60: mode colours on Connect cards and Listen badge (same palette as Node Controller) */
.card[data-mode="ASL"]{border-color:rgb(0,255,229)!important}
.card[data-mode="ASL"] select,.card[data-mode="ASL"] input{border-color:rgb(0,255,229)!important;color:rgb(0,255,229)!important}
#c-mode[data-mode="ASL"]{color:rgb(0,255,229)!important}
.lk-badge[data-mode="ASL"]{border-color:rgb(0,255,229)!important;color:rgb(0,255,229)!important}
.card[data-mode="ECHO"]{border-color:rgb(255,208,64)!important}
.card[data-mode="ECHO"] select,.card[data-mode="ECHO"] input{border-color:rgb(255,208,64)!important;color:rgb(255,208,64)!important}
#c-mode[data-mode="ECHO"]{color:rgb(255,208,64)!important}
.lk-badge[data-mode="ECHO"]{border-color:rgb(255,208,64)!important;color:rgb(255,208,64)!important}
.card[data-mode="DMR"]{border-color:rgb(34,212,255)!important}
.card[data-mode="DMR"] select,.card[data-mode="DMR"] input{border-color:rgb(34,212,255)!important;color:rgb(34,212,255)!important}
#c-mode[data-mode="DMR"]{color:rgb(34,212,255)!important}
.lk-badge[data-mode="DMR"]{border-color:rgb(34,212,255)!important;color:rgb(34,212,255)!important}
.card[data-mode="STFU"]{border-color:rgb(0,255,176)!important}
.card[data-mode="STFU"] select,.card[data-mode="STFU"] input{border-color:rgb(0,255,176)!important;color:rgb(0,255,176)!important}
#c-mode[data-mode="STFU"]{color:rgb(0,255,176)!important}
.lk-badge[data-mode="STFU"]{border-color:rgb(0,255,176)!important;color:rgb(0,255,176)!important}
.card[data-mode="YSF"]{border-color:rgb(212,102,255)!important}
.card[data-mode="YSF"] select,.card[data-mode="YSF"] input{border-color:rgb(212,102,255)!important;color:rgb(212,102,255)!important}
#c-mode[data-mode="YSF"]{color:rgb(212,102,255)!important}
.lk-badge[data-mode="YSF"]{border-color:rgb(212,102,255)!important;color:rgb(212,102,255)!important}
.card[data-mode="FCS"]{border-color:rgb(0,196,160)!important}
.card[data-mode="FCS"] select,.card[data-mode="FCS"] input{border-color:rgb(0,196,160)!important;color:rgb(0,196,160)!important}
#c-mode[data-mode="FCS"]{color:rgb(0,196,160)!important}
.lk-badge[data-mode="FCS"]{border-color:rgb(0,196,160)!important;color:rgb(0,196,160)!important}
.card[data-mode="P25"]{border-color:rgb(255,170,34)!important}
.card[data-mode="P25"] select,.card[data-mode="P25"] input{border-color:rgb(255,170,34)!important;color:rgb(255,170,34)!important}
#c-mode[data-mode="P25"]{color:rgb(255,170,34)!important}
.lk-badge[data-mode="P25"]{border-color:rgb(255,170,34)!important;color:rgb(255,170,34)!important}
.card[data-mode="NXDN"]{border-color:rgb(212,255,0)!important}
.card[data-mode="NXDN"] select,.card[data-mode="NXDN"] input{border-color:rgb(212,255,0)!important;color:rgb(212,255,0)!important}
#c-mode[data-mode="NXDN"]{color:rgb(212,255,0)!important}
.lk-badge[data-mode="NXDN"]{border-color:rgb(212,255,0)!important;color:rgb(212,255,0)!important}
.card[data-mode="DSTAR"]{border-color:rgb(255,68,204)!important}
.card[data-mode="DSTAR"] select,.card[data-mode="DSTAR"] input{border-color:rgb(255,68,204)!important;color:rgb(255,68,204)!important}
#c-mode[data-mode="DSTAR"]{color:rgb(255,68,204)!important}
.lk-badge[data-mode="DSTAR"]{border-color:rgb(255,68,204)!important;color:rgb(255,68,204)!important}
.card[data-mode="XLX"]{border-color:rgb(0,255,229)!important}
.card[data-mode="XLX"] select,.card[data-mode="XLX"] input{border-color:rgb(0,255,229)!important;color:rgb(0,255,229)!important}
#c-mode[data-mode="XLX"]{color:rgb(0,255,229)!important}
.lk-badge[data-mode="XLX"]{border-color:rgb(0,255,229)!important;color:rgb(0,255,229)!important}
.card[data-mode="M17"]{border-color:rgb(212,102,255)!important}
.card[data-mode="M17"] select,.card[data-mode="M17"] input{border-color:rgb(212,102,255)!important;color:rgb(212,102,255)!important}
#c-mode[data-mode="M17"]{color:rgb(212,102,255)!important}
.lk-badge[data-mode="M17"]{border-color:rgb(212,102,255)!important;color:rgb(212,102,255)!important}
/* v0.9.64.1: Connect card Connect/Disconnect buttons match the Tune card pair and fill the row */
#tab-connect .sel-card .btn-pair{gap:var(--tn-gap)}
#tab-connect .sel-card .btn-pair>.btn{flex:1 1 0;width:auto;min-width:0;min-height:var(--tn-h);padding:0 14px}
#tab-connect #c-connect{min-height:44px;font-size:15px}
/* v0.9.62: Connect/Tune card text follows the mode colour (mode tag border, big number); headings unchanged */
.card[data-mode="ASL"] .big-num{color:rgb(0,255,229)!important}
#c-mode[data-mode="ASL"]{border-color:rgb(0,255,229)!important}
.card[data-mode="ECHO"] .big-num{color:rgb(255,208,64)!important}
#c-mode[data-mode="ECHO"]{border-color:rgb(255,208,64)!important}
.card[data-mode="DMR"] .big-num{color:rgb(34,212,255)!important}
#c-mode[data-mode="DMR"]{border-color:rgb(34,212,255)!important}
.card[data-mode="STFU"] .big-num{color:rgb(0,255,176)!important}
#c-mode[data-mode="STFU"]{border-color:rgb(0,255,176)!important}
.card[data-mode="YSF"] .big-num{color:rgb(212,102,255)!important}
#c-mode[data-mode="YSF"]{border-color:rgb(212,102,255)!important}
.card[data-mode="FCS"] .big-num{color:rgb(0,196,160)!important}
#c-mode[data-mode="FCS"]{border-color:rgb(0,196,160)!important}
.card[data-mode="P25"] .big-num{color:rgb(255,170,34)!important}
#c-mode[data-mode="P25"]{border-color:rgb(255,170,34)!important}
.card[data-mode="NXDN"] .big-num{color:rgb(212,255,0)!important}
#c-mode[data-mode="NXDN"]{border-color:rgb(212,255,0)!important}
.card[data-mode="DSTAR"] .big-num{color:rgb(255,68,204)!important}
#c-mode[data-mode="DSTAR"]{border-color:rgb(255,68,204)!important}
.card[data-mode="XLX"] .big-num{color:rgb(0,255,229)!important}
#c-mode[data-mode="XLX"]{border-color:rgb(0,255,229)!important}
.card[data-mode="M17"] .big-num{color:rgb(212,102,255)!important}
#c-mode[data-mode="M17"]{border-color:rgb(212,102,255)!important}
</style>
</head>
<body>
<header><div class="hdr-left"><h1>Node Recorder</h1></div><span class="ver">v__VERSION__</span><span class="sp"></span>
<div class="hdr-pills"><a id="dash-link" class="pill hidden" href="#" aria-label="Open Node Controller">Node Controller</a>
<button id="logout" class="pill hidden" type="button">Log Out</button></div></header>
<div id="login-screen">
<div id="login-card">
<h2>Node Recorder Login</h2>
<form id="login-form">
<input type="password" id="pw" placeholder="Root password" autocomplete="current-password" aria-label="Root password" required>
<button id="login-btn" type="submit">Log In</button>
</form>
<div id="login-msg"></div>
<div id="login-tls">__TLS_NOTE__</div>
</div>
</div>
<main>

<section id="tab-connect" class="hidden">
<div class="card" id="cd-tune">
<h2>Tune</h2>
<div class="tn-bar">
<select id="t-mode" aria-label="Mode"></select>
<select id="t-net" aria-label="DMR network"></select>
<select id="t-mod" aria-label="Module"></select>
<input id="t-find" type="search" maxlength="40" aria-label="Search or type" autocomplete="off" autocapitalize="off" spellcheck="false">
<select id="t-pick" aria-label="Pick from the list"></select>
<button id="t-lh" class="btn-last lh-off" type="button" aria-label="Open Last Heard">LH</button>
<div class="btn-pair tn-pair"><button id="t-go" class="btn big primary" type="button">Connect</button><button id="t-disc" class="btn big danger" type="button">Disconnect</button></div>
</div>
<div id="t-list" class="tn-msg"></div>
<div id="t-msg" class="msg"></div>
<div id="t-ask" class="hidden">
<div class="row"><button id="t-net-add" class="btn primary" type="button">Add it to Node Controller and tune</button>
<button id="t-net-once" class="btn" type="button">Tune this once</button>
<button id="t-net-no" class="btn" type="button">Cancel</button></div>
</div>
<div class="tn-foot"><span id="t-now" class="muted small"></span></div>
</div>
<div class="card" id="cd-sched-form">
<h2 id="sc-title">Schedule a recording</h2>
<div class="row"><label>Name <input type="text" id="sc-name" maxlength="40" placeholder="optional" style="width:150px"></label>
<label><input type="checkbox" id="sc-special"> Special (one time)</label><label id="sc-date-w" class="hidden">Date <input type="date" id="sc-date"></label><span class="daypick" id="sc-days" role="group" aria-label="Days" style="display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center"><span class="muted small">Days</span><label><input type="checkbox" value="0"> Sun</label><label><input type="checkbox" value="1"> Mon</label><label><input type="checkbox" value="2"> Tue</label><label><input type="checkbox" value="3"> Wed</label><label><input type="checkbox" value="4"> Thu</label><label><input type="checkbox" value="5"> Fri</label><label><input type="checkbox" value="6"> Sat</label></span>
<label>From <input type="time" id="sc-start" value="20:00"></label>
<label>To <input type="time" id="sc-end" value="21:00"></label></div>
<div class="row"><label>Mode <select id="sc-mode"></select></label>
<label>Favorite <select id="sc-pick"></select></label></div>
<div class="row"><label><span id="sc-num-l">Node</span> <input type="text" id="sc-num" maxlength="40" style="width:150px"></label>
<label id="sc-net-w" class="hidden">Network <select id="sc-net"></select></label>
<label id="sc-mod-w" class="hidden">Module <input type="text" id="sc-mod" maxlength="2" style="width:48px;text-transform:uppercase"></label></div>
<div class="row"><label>Format <select id="sc-format"><option value="ulaw">u-law (half the size)</option><option value="pcm">PCM</option></select></label>
<label><input type="checkbox" id="sc-enabled" checked> On</label></div>
<div class="row"><button id="sc-set" class="btn primary" type="button">Set</button><button id="sc-clear" class="btn" type="button">Clear</button></div>
<div id="sc-msg" class="msg"></div>
<div id="sc-src" class="muted small"></div>
</div>
<div id="da-wrap">
<button id="da-btn" class="btn danger" type="button"><span class="da-t">Disconnect All</span></button>
<div id="da-msg" class="msg"></div>
</div>
</section>

<section id="tab-record" class="hidden">
<div class="card" id="cd-rec">
<h2>Record</h2>
<div class="lstat"><span class="mono" id="st-node" title="Node">-</span>
<span id="st-feed-w"><span id="st-feed" class="dot"></span><span id="st-feed-t">feed</span></span>
<span title="Lit while the node is passing audio"><span id="st-active" class="dot"></span>RX</span></div>
<div class="spec-meter" id="spec-meter"><div class="meter"><i id="meter-bar"></i></div><span id="st-level" class="muted small mono">-inf</span></div>
<div id="rec-state" class="muted" style="margin-top:8px">Idle.</div>
<div class="row"><button id="rec-start" class="btn primary" type="button">Record now</button><button id="rec-stop" class="btn danger" type="button" disabled>Stop recording</button></div>
<p class="muted small">Record now records the target set in the Connect tab's schedule form, until you press Stop. It stops by itself after 4 hours.</p>
<div id="rec-msg" class="msg"></div>
</div>
<div class="card" id="cd-rstore">
<h2>Storage</h2>
<table>
<tr><th>Saving to</th><td id="rs-path">-</td></tr>
<tr><th>Chosen by</th><td id="rs-source">-</td></tr>
<tr><th>Free</th><td id="rs-free">-</td></tr>
<tr><th>Recordings</th><td id="rs-files">-</td></tr>
</table>
<div id="rs-block" class="msg err hidden"></div>
<div id="rs-conflict" class="msg warn hidden"></div>
</div>
<div class="card" id="cd-rsched">
<h2>Schedule</h2>
<div id="sch-note" class="muted small"></div>
<table class="links"><thead><tr><th>Recording</th><th>When</th><th></th></tr></thead><tbody id="sch-rows"></tbody></table>
<div id="sch-none" class="muted small" style="margin-top:8px">No scheduled recordings.</div>
<div id="sch-err" class="msg err hidden"></div>
<div id="sch-msg" class="msg"></div>
<div id="sch-trace" class="mono small hidden"></div>
<div id="sch-results" class="muted small"></div>
</div>
</section>

<section id="tab-setup" class="hidden">
<div class="card" id="cd-sys">
<h2>System</h2>
<div class="row"><button id="sys-reboot" class="btn danger" type="button">Reboot</button>
<button id="sys-shutdown" class="btn" type="button">Shutdown</button></div>
<div id="sys-msg" class="msg"></div>
<div id="ql-row" class="ql-row hidden">
<a class="ql hidden" data-ql="allmon3" data-ql-path="/allmon3" href="#" target="_blank" rel="noopener">Allmon3</a>
<a class="ql hidden" data-ql="dvswitch" data-ql-path="/dvswitch" href="#" target="_blank" rel="noopener">DVSwitch</a>
<a class="ql hidden" data-ql="cockpit" data-ql-port="9090" href="#" target="_blank" rel="noopener">Cockpit</a>
</div>
</div>
<div class="card" id="cd-links">
<h2>Links</h2>
<table class="links"><thead><tr><th>Node</th><th>Name</th><th>Dir</th><th>Time</th><th>State</th></tr></thead><tbody id="s-links"></tbody></table>
<div id="s-nolinks" class="muted small" style="margin-top:8px">No links.</div>
<div id="s-links-err" class="msg warn hidden">Could not ask Asterisk for the links (rpt lstats).</div>
</div>
<div class="card fold" id="cd-setup">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-setup"><span class="fold-t">Setup</span><span class="fold-sum" id="sum-cfg"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-setup">
<h3 style="margin:6px 0 4px">1. Node Recorder settings</h3>
<div id="cb-cfg">
<div class="row"><label><input type="checkbox" id="cfg-https"> HTTPS</label></div>
<p class="muted small">HTTPS uses a certificate made on this Pi, so the browser shows a warning: accept it to continue. Changing HTTPS restarts Node Recorder. The web port is 8995.</p>
<div id="cfg-msg" class="msg"></div>
<h3 style="margin:14px 0 4px">Tune card on this phone</h3>
<div class="row"><label>Text <input type="range" id="tn-font" min="10" max="18" step="0.5"> <span id="tn-font-v" class="mono small"></span></label></div>
<div class="row"><label>Height <input type="range" id="tn-h" min="32" max="56" step="1"> <span id="tn-h-v" class="mono small"></span></label></div>
<div class="row"><button id="tn-reset" class="btn" type="button">Default spacing</button></div>
<h3>Setup tab on this phone</h3>
<div class="row"><label>Text <input type="range" id="sett-font" min="10" max="20" step="0.5"> <span id="sett-font-v" class="mono small"></span></label></div>
<div class="row"><label>Height (buttons) <input type="range" id="sett-h" min="36" max="64" step="1"> <span id="sett-h-v" class="mono small"></span></label></div>
<div class="row"><button id="sett-reset" class="btn" type="button">Default size</button></div>
</div>
<div class="row"><button id="setup-save" class="btn primary" type="button">Save</button>
<button id="setup-restart" class="btn danger" type="button">Restart Asterisk</button></div>
<div id="setup-msg" class="msg"></div>
</div>
</div>
<div class="card fold" id="cd-sched">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-sched"><span class="fold-t">Schedule</span><span class="fold-sum" id="sum-sched"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-sched">
<p class="muted small">Add recordings on the Connect tab. Here you can turn an entry off or on, change it, remove it or try it with a dry run. Windows must be at least 2 minutes apart.</p>
<table class="links"><thead><tr><th>Recording</th><th>When</th><th></th></tr></thead><tbody id="sl-rows"></tbody></table>
<div id="sl-none" class="muted small" style="margin-top:8px">No scheduled recordings.</div>
<div id="sl-msg" class="msg"></div>
</div>
</div>
<div class="card fold" id="cd-dig">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-dig"><span class="fold-t">Digital</span><span class="fold-sum" id="sum-dig"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-dig">
<p class="muted small">Without Node Controller, Node Recorder tunes DVSwitch and M17 itself: it sets the mode, tunes and
links the bridge node to the main node. While Node Controller runs, ASL, EchoLink, DVSwitch and M17 all go through it.
A DMR network Node Controller doesn't have can be added to it, or used for one tune, from the Connect tab.</p>
<table>
<tr><th>Control</th><td id="dg-control">-</td></tr>
<tr><th>Found</th><td id="dg-found">-</td></tr>
<tr><th>Services</th><td id="dg-svc">-</td></tr>
<tr><th>Tuned here</th><td id="dg-tuned">-</td></tr>
</table>
<div class="row"><label>Digital bridge <input type="text" inputmode="numeric" id="dg-dbridge" maxlength="7" style="width:96px"></label>
<label>M17 bridge <input type="text" inputmode="numeric" id="dg-mbridge" maxlength="7" style="width:96px"></label>
<label>Callsign <input type="text" id="dg-call" maxlength="10" style="width:110px;text-transform:uppercase"></label></div>
<p class="muted small" id="dg-auto"></p>
<div id="dg-msg" class="msg"></div>
<h3 style="margin:14px 0 4px">DMR networks</h3>
<p class="muted small">Each DMR entry joins its network with <code>password@address:port</code> before it tunes the
talkgroup, as Node Controller does. Leave a password empty to keep the saved one.</p>
<div id="nw-rows"></div>
<div class="row"><button id="nw-add" class="btn" type="button">Add network</button>
<button id="nw-import" class="btn" type="button">Copy from Node Controller</button></div>
<div id="nw-msg" class="msg"></div>
<div class="row"><button id="dig-save" class="btn primary" type="button">Save digital and DMR networks</button></div>
</div>
</div>
<div class="card fold" id="cd-node">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-node"><span class="fold-t">Recorder node <span id="rn-node">1921</span></span><span class="fold-sum" id="sum-node"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-node">
<p class="muted small">Node Recorder records the audio of the private node above, linked to the main node. Node Talker uses the same node: when Node Talker owns it, Node Recorder records the audio Node Recorder forwards.</p>
<table>
<tr><th>State</th><td id="rn-state">-</td></tr>
<tr><th>Channel</th><td><code id="rn-rxch">-</code></td></tr>
<tr><th>Linked to</th><td id="rn-main">-</td></tr>
<tr><th>Audio</th><td id="rn-udp">-</td></tr>
<tr><th>Node Talker</th><td id="rn-talker">-</td></tr>
</table>
<div class="row"><button id="rn-add" class="btn primary" type="button">Add node 1921</button>
<button id="rn-remove" class="btn" type="button">Remove</button></div>
<div id="rn-msg" class="msg"></div>
</div>
</div>
<div class="card fold" id="cd-store">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-store"><span class="fold-t">Storage</span><span class="fold-sum" id="sum-store"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-store">
<p class="muted small">Recordings are written as u-law WAV files (about 29 MB an hour) or PCM WAV (about 58 MB an hour), then turned into MP3 if the MP3 card is on. Leave the folder empty to use the Pibrary library (or a USB drive) automatically, so Pibrary lists and plays them. Recordings never go to the SD card while a USB drive is mounted.</p>
<div class="row"><label>Recordings folder <input type="text" id="cfg-record_path" maxlength="200" placeholder="automatic" style="width:260px"></label></div>
<div class="row"><label>Keep at most <input type="number" id="cfg-record_max_mb" min="100" max="2000000" style="width:110px"> MB (the oldest recordings go first)</label></div>
<div class="row"><button id="store-save" class="btn primary" type="button">Save</button></div>
<div id="store-msg" class="msg"></div>
</div>
</div>
<div class="card fold" id="cd-conv">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-conv"><span class="fold-t">Convert</span><span class="fold-sum" id="sum-conv"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-conv">
<p class="muted small">When a recording ends, Node Recorder compresses the WAV file with the encoder chosen below and then deletes the WAV. If the conversion fails the WAV is kept. It runs at the lowest priority, one file at a time, and only if the encoder is installed. ffmpeg is not used: it is a very large install for this job.</p>
<div class="row"><label><input type="checkbox" id="cfg-record_convert"> Convert recordings and delete the WAV</label>
<label>Quality <select id="cfg-record_kbps"></select></label></div>
<div id="conv-list"></div>
<div class="row"><button id="conv-save" class="btn primary" type="button">Save</button></div>
<div id="conv-msg" class="msg"></div>
<pre id="conv-term" class="hidden" aria-live="polite"></pre>
<p id="conv-stat" class="muted small"></p>
</div>
</div>
<div class="card fold" id="cd-rx">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-rx"><span class="fold-t">RX</span><span class="fold-sum" id="sum-rx"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-rx">
<div class="row"><label><input type="checkbox" id="tune-on"> Adjust audio levels</label></div>
<div class="row"><label>RX gain <input type="range" id="tune-rx" min="-12" max="12" step="1"> <span id="tune-rx-v" class="mono small"></span></label></div>
<div class="row"><label><input type="checkbox" id="rx-hpf"> 300 Hz cut</label>
<label><input type="checkbox" id="rx-agc"> Auto level</label>
<label>Gate <select id="rx-gate"><option value="0">Off</option><option value="1">Light</option><option value="2">Strong</option></select></label></div>
<div class="row"><button id="rx-save" class="btn primary" type="button">Save</button></div>
<div id="rx-msg" class="msg"></div>
<table><tr><th>Processing load</th><td id="rx-load">-</td></tr></table>
</div>
</div>

<div class="card fold" id="cd-log">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-log"><span class="fold-t">Log</span><span class="fold-sum" id="sum-log"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-log">
<div id="log"></div>
</div>
</div>

<div class="theme-row"><span class="theme-lbl">Theme</span><span class="theme-sw" role="group" aria-label="Page theme"><button type="button" class="theme-opt" data-theme-set="dark" aria-pressed="true">Dark</button><button type="button" class="theme-opt" data-theme-set="light" aria-pressed="false">Light</button></span></div>
</section>
</main>
<nav class="tabs hidden" id="nav" aria-label="Main">
<button id="nav-connect" type="button">__ICON_CONNECT__Connect</button>
<button id="nav-record" type="button">__ICON_RECORD__Record</button>
<button id="nav-setup" type="button">__ICON_SETUP__Setup</button>
</nav>
<script>__JS__</script>
<dialog id="setup-dlg" class="setup-dlg" aria-labelledby="setup-title">
<h2 id="setup-title">Set up Node Recorder</h2>
<p>Node Recorder needs this change to <code>rpt.conf</code> before it can record through this node:</p>
<ul id="setup-steps"></ul>
<p id="setup-blocked" class="msg warn hidden"></p>
<p class="muted small">Reversible. rpt.conf is backed up before each change, and the backup's path is shown in the result. Remove on the Recorder node card puts back what Node Recorder added. Asterisk restarts after the change, so the links on this node drop for a moment.</p>
<div class="row"><button id="setup-ok" class="btn primary" type="button">OK, install</button><button id="setup-later" class="btn" type="button">Not now</button></div>
<div id="setup-dlg-msg" class="msg"></div>
</dialog>
</body>
</html>
"""


_page = None
_TLS_NOTE = ""


def render_page():
    global _page
    if _page is None:
        html = _HTML_TEMPLATE
        for key, val in (("__CSS__", _CSS), ("__JS__", _JS), ("__ICON_CONNECT__", _ICON_CONNECT), ("__ICON_RECORD__", _ICON_RECORD),
                         ("__ICON_SETUP__", _ICON_SETUP), ("__VERSION__", VERSION), ("__TLS_NOTE__", _TLS_NOTE)):
            html = html.replace(key, val)
        _page = html.encode("utf-8")
    return _page


_POST_ACTIONS = {
    "/api/config": (config_update, ()),
    "/api/recnode/enable": (lambda b: rec_node_enable(), (OSError,)),
    "/api/setup/apply": (lambda b: setup_apply(), (OSError,)),
    "/api/convert/install": (encoder_install, ()),
    "/api/schedule/set": (schedule_set, (ValueError,)),
    "/api/schedule/remove": (schedule_remove, ()),
    "/api/recording/start": (recording_start, (ValueError,)),
    "/api/recording/stop": (lambda b: recording_stop(), ()),
    "/api/schedule/dryrun": (schedule_dry_run, (ValueError,)),
    "/api/recnode/disable": (lambda b: rec_node_disable(), (OSError,)),
    "/api/disconnect-links": (disconnect_links, ()),
    "/api/tune": (tune_connect, ()),
    "/api/tune/disconnect": (tune_disconnect, ()),
    "/api/asterisk/restart": (lambda b: restart_asterisk(), ()),
    "/api/disconnect-all": (disconnect_all, ()),
    "/api/system/reboot": (lambda b: system_power("reboot"), ()),
    "/api/system/shutdown": (lambda b: system_power("shutdown"), ()),
    "/api/digital": (digital_save, ()),
    "/api/dmr-networks": (lambda b: nets_save(b.get("nets")), ()),
    "/api/dmr-networks/import": (lambda b: nets_import(), ()),
}
_OPEN_GET_PATHS = ("/", "/index.html", "/api/health", "/api/whoami")
_PUBLIC_LISTEN_PATHS = ("/api/status", "/api/listen")


class Handler(BaseHTTPRequestHandler):
    server_version = "noderecorder/" + VERSION
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

    def _local_peer(self):
        peer = _parse_ip(self._peer())
        return bool(peer is not None and peer.is_loopback and not self._proxied())

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
        self._json(403, {"ok": False, "error": "Node Recorder is not open to the internet (allow_wan is off)."})
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
        if isinstance(obj, dict) and obj.get("error") and "message" not in obj:
            obj = dict(obj, message=obj["error"])
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
        if path == "/api/recorder/status":
            if self._local_peer():
                self._json(200, recorder_status())
            else:
                self._json(403, {"ok": False, "error": "The recording status is for programs on this Pi only."})
            return
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
                dport = dashboard_conf()["port"]
                dash = port_open_cached(dport, ttl=5.0)
                self._json(200, {"ok": True, "authed": authed, "public_listen": _cfg_get("public_listen"),
                                 "backend": _root_backend_available(), "dash_port": dport,
                                 "dash_running": dash,
                                 "instmon_port": INSTMON_PORT if not dash and port_open_cached(INSTMON_PORT, ttl=5.0) else None,
                                 "links": quick_links() if authed else {},
                                 "sysmon_port": SYSMON_PORT if authed and port_open_cached(SYSMON_PORT) else None})
            elif path == "/api/status":
                self._json(200, dict(build_status(authed), ok=True))
            elif path == "/api/listen":
                self._stream((query.get("fmt") or [""])[0] == "s16")
            elif path == "/api/disconnect-all/status":
                self._json(200, disconnect_all_status())
            elif path == "/api/storage":
                self._json(200, storage_view())
            elif path == "/api/convert":
                self._json(200, encoder_view())
            elif path == "/api/schedule/sources":
                self._json(200, schedule_sources())
            elif path == "/api/schedule":
                self._json(200, schedule_view())
            elif path == "/api/recnode":
                self._json(200, dict(rec_node_state(), ok=True))
            elif path == "/api/setup":
                self._json(200, dict(setup_plan(), ok=True))
            elif path == "/api/tune-info":
                self._json(200, {"ok": True, "modes": list(FAV_MODES), "nets": [n["name"] for n in nets_load()],
                                 "net_links": {n["name"]: n["url"] for n in nets_load()}})
            elif path == "/api/tune-search":
                self._json(200, tune_search(query.get("mode", [""])[0], query.get("q", [""])[0]))
            elif path == "/api/tune-list":
                self._json(200, tune_list(query.get("mode", [""])[0]))
            elif path == "/api/digital":
                self._json(200, digital_info())
            elif path == "/api/config":
                with _config_lock:
                    cfg = dict(_config)
                self._json(200, {"ok": True, "config": cfg})
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
    load_config()
    port = PORT
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
                    log_event("No new HTTPS certificate; serving plain HTTP", "err")
        else:
            log_event("No HTTPS certificate; serving plain HTTP", "err")
        if httpd.ssl_ctx is None:
            _TLS_NOTE = ("HTTPS is on in Setup but could not start, so this page is not encrypted and the password "
                         "is sent in plain text. See the Node Recorder log.")
    _solo_load()
    fav_doc()
    threading.Thread(target=KEYED.loop, name="ami-keyed", daemon=True).start()
    threading.Thread(target=HUB.pump_loop, name="pump", daemon=True).start()
    threading.Thread(target=pi_loop, name="pi-health", daemon=True).start()
    threading.Thread(target=lambda: (repair_recordings(storage_pick()["path"]), enc_sweep(storage_pick()["path"])),
                     name="rec-repair", daemon=True).start()
    threading.Thread(target=SCHED.loop, name="schedule", daemon=True).start()
    threading.Thread(target=usrp_loop, args=(FWD_PORT, None), name="usrp-fwd", daemon=True).start()
    threading.Thread(target=usrp_loop, args=(REC_USRP_IN, talker_idle), name="usrp-node", daemon=True).start()
    threading.Thread(target=link_keeper_loop, name="link-keeper", daemon=True).start()
    threading.Thread(target=guard_loop, name="link-guard", daemon=True).start()
    threading.Thread(target=_sd_watchdog_loop, args=(port, httpd.ssl_ctx is not None), name="watchdog", daemon=True).start()
    scheme = "https" if httpd.ssl_ctx is not None else "http"
    log_event(f"{APP_NAME} v{VERSION} on {scheme} port {port}, node audio on 127.0.0.1:{FWD_PORT}/udp "
              f"and, without Node Talker, 127.0.0.1:{REC_USRP_IN}/udp", "ok")
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
        SCHED.shutdown()
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


def _restore_after_update():
    try:
        with open(RESTORE_PATH, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return
    _remove_quiet(RESTORE_PATH)
    if not isinstance(rec, dict):
        return
    try:
        age = time.time() - float(rec.get("time", 0))
    except (TypeError, ValueError):
        return
    if not 0 <= age <= RESTORE_MAX_AGE_SEC:
        print(f"  [i] Ignored {RESTORE_PATH}: older than {RESTORE_MAX_AGE_SEC // 60} minutes")
        return
    print(f"  [i] The uninstall {int(age)} s ago changed rpt.conf (an update); putting its Node Recorder lines back")
    try:
        if rec.get("node") is True:
            r = rec_node_enable()
            print(f"  [+] Put back node {REC_NODE}" if r.get("ok") else f"  [!] Node {REC_NODE}: {r.get('error')}")
            if r.get("changed"):
                print("      Asterisk needs no restart, unless it was restarted while Node Recorder was out.")
    except OSError as exc:
        print(f"  [!] Could not put the rpt.conf lines back: {exc}")


def _replace_link(path, target):
    tmp = f"{path}.{secrets.token_hex(4)}.tmp"
    os.symlink(target, tmp)
    os.replace(tmp, path)


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


def allmon3_sync(text, add=(), remove=(), own=""):
    import re
    hdr = re.compile(r"^\s*\[([^\]]+)\]")
    kvre = re.compile(r"^\s*([^;=\s][^=]*?)\s*=>?\s*(.*)$")
    lines = text.splitlines()
    secs = []
    for i, line in enumerate(lines):
        m = hdr.match(line)
        if m:
            if secs:
                secs[-1]["end"] = i
            secs.append({"name": m.group(1).strip(), "start": i, "end": len(lines)})
    names = {s["name"] for s in secs}
    notes = []
    public = [s for s in secs if s["name"].isdigit() and not 1000 <= int(s["name"]) <= 1999]
    public.sort(key=lambda s: s["name"] != own)
    drop = set()
    for s in secs:
        if s["name"] in remove:
            drop.update(range(s["start"], s["end"]))
            notes.append("allmon3.ini: [%s] removed" % s["name"])
    out = [line for i, line in enumerate(lines) if i not in drop]
    adds = sorted((n for n in add if n not in names and n not in remove), key=int)
    if adds and not public:
        notes.append("allmon3.ini has no public node section to copy host/user/pass from; add "
                     + ", ".join(adds) + " to Allmon3 by hand")
        return "\n".join(out) + "\n", notes
    for n in adds:
        src = public[0]
        body = []
        for i in range(src["start"] + 1, src["end"]):
            s = lines[i].strip()
            m = None if not s or s.startswith(";") or s.startswith("[") else kvre.match(lines[i])
            if m and m.group(1).strip().lower() in ("host", "port", "user", "pass"):
                body.append(lines[i].rstrip())
        while out and not out[-1].strip():
            out.pop()
        out += ["", "[%s]" % n] + body
        notes.append("allmon3.ini: [%s] added (host/user/pass copied from [%s])" % (n, src["name"]))
    return "\n".join(out) + "\n", notes


SETUP_PATH = os.path.join(CONFIG_DIR, "noderecorder_setup.json")


def setup_pending():
    try:
        with open(SETUP_PATH, "r", encoding="utf-8") as fh:
            return bool(json.load(fh).get("pending"))
    except (OSError, ValueError, AttributeError):
        return False


def setup_mark(pending):
    _atomic_write(SETUP_PATH, json.dumps({"pending": bool(pending), "version": VERSION}) + "\n", 0o644)


def setup_plan(full=False):
    pending = setup_pending()
    if not pending and not full:
        return {"pending": False, "steps": [], "blocked": [], "node": "", "rpt": RPT_CONF}
    main = main_node()
    steps, blocked = [], []
    if not main:
        blocked.append("Pick the node on the Node card first.")
    else:
        st = rec_node_state(main)
        if st.get("defined") and not st.get("owner"):
            blocked.append(f"rpt.conf already has a node {REC_NODE} that Node Recorder didn't add. Remove it or pick another node.")
        elif st.get("owner") != "talker" and not st.get("ready"):
            steps.append({"id": "node", "text": f"Add node {REC_NODE} to rpt.conf: its own stanza, a USRP channel on "
                          f"127.0.0.1 ports {REC_USRP_IN} and {REC_USRP_OUT}, and a [nodes] line. Node Recorder then links it to node {main}."})
    if pending and not steps and not blocked:
        setup_mark(False)
        pending = False
    return {"pending": pending, "steps": steps, "blocked": blocked, "node": main or "", "rpt": RPT_CONF}


def setup_apply():
    plan = setup_plan(full=True)
    if plan["blocked"]:
        return {"ok": False, "error": " ".join(plan["blocked"])}
    ids = {s["id"] for s in plan["steps"]}
    msgs = []
    if "node" in ids:
        r = rec_node_enable()
        if not r.get("ok"):
            return r
        msgs.append(r.get("message", ""))
        r = restart_asterisk()
        if not r.get("ok"):
            return {"ok": False, "error": " ".join(msgs + [r.get("error", "")]) + " Restart Asterisk by hand."}
        msgs.append(r.get("message", ""))
    setup_mark(False)
    log_event("Node Recorder setup finished", "ok")
    return {"ok": True, "message": " ".join(m for m in msgs if m) or "Nothing to change."}


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
    if not os.path.exists(CONFIG_PATH):
        save_config(dict(DEFAULT_CONFIG))
        print(f"  [+] Wrote {CONFIG_PATH}")
    load_config()
    save_config(dict(_config))
    _print_digital()
    if not os.path.exists(SETUP_PATH):
        setup_mark(True)
        print("  [i] Node Recorder will ask to set up its node on first open (rpt.conf is backed up first).")
    _restore_after_update()
    _atomic_write(SYSTEMD_SERVICE_PATH, service_content(INSTALL_BIN_PATH), 0o644)
    print(f"  [+] Wrote {SYSTEMD_SERVICE_PATH}")
    mark, msg = open_firewall_port(PORT)
    print(f"  [{mark}] {msg}")
    for args in (("daemon-reload",), ("enable", SERVICE_NAME)):
        r = _systemctl(*args)
        if r.returncode != 0:
            print(f"  [!] systemctl {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    r = _systemctl("restart", SERVICE_NAME)
    if r.returncode != 0:
        print(f"  [!] systemctl restart failed: {(r.stderr or r.stdout).strip()}")
        print(f"      The previous version (if any) is still in {INSTALL_DIR}")
        sys.exit(1)
    print(f"  [+] {SERVICE_NAME} enabled and started")
    for name in os.listdir(INSTALL_DIR):
        old = os.path.join(INSTALL_DIR, name)
        if old != dest and name.endswith(".py") and os.path.isfile(old) and not os.path.islink(old):
            os.remove(old)
            print(f"  [-] Removed the previous version {old}")
    print(f"Open http://<pi-address>:{PORT} , log in, and pick the node on the Node card.")


def _print_digital():
    b = bridge_nodes(0)
    found = [name for name, ok in (("dvswitch.sh", dvs_path()), ("Analog_Bridge", os.path.isfile(AB_INI)),
                                   ("USRP2M17", _m17_present()), ("M17Hosts.json", os.path.isfile(M17_HOSTS))) if ok]
    print(f"  [i] Digital: found {', '.join(found) or 'nothing'}; bridge nodes: digital {b['digital'] or 'none'}, "
          f"M17 {b['m17'] or 'none'}")
    if not dvs_path():
        print("      DMR, STFU, YSF, P25, NXDN and D-STAR favorites need DVSwitch (dvswitch.sh).")


def uninstall_service():
    if os.geteuid() != 0:
        print("Error: uninstalling needs root. Run with sudo.")
        sys.exit(1)
    print(f"Removing {APP_NAME}...")
    load_config()
    try:
        r = rec_node_disable()
        if r.get("changed"):
            print(f"  [-] {r.get('message')} (backup {r.get('backup')})")
            print("      Restart Asterisk to apply: systemctl restart asterisk")
            rec = {"time": time.time(), "version": VERSION, "node": True}
            try:
                _atomic_write(RESTORE_PATH, json.dumps(rec) + "\n", mode=0o600)
                print(f"      An install within {RESTORE_MAX_AGE_SEC // 60} minutes (an update) puts these back.")
            except OSError as exc:
                print(f"  [!] Could not write {RESTORE_PATH}: {exc}")
    except OSError as exc:
        print(f"  [!] Could not check {RPT_CONF}: {exc}")
    _systemctl("disable", "--now", SERVICE_NAME)
    for p in (SYSTEMD_SERVICE_PATH, INSTALL_BIN_PATH):
        if os.path.lexists(p):
            os.remove(p)
            print(f"  [-] Removed {p}")
    _systemctl("daemon-reload")
    if os.path.isdir(INSTALL_DIR):
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        print(f"  [-] Removed {INSTALL_DIR}")
    _remove_launcher_if_unused()
    print(f"  Settings kept in {CONFIG_PATH} and {BACKUP_DIR}")
    mark, msg = close_firewall_port(PORT)
    print(f"  [{mark}] {msg}")


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{VERSION}: scheduled recording of an ASL node's audio")
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
