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

VERSION = "0.6.8"
DATE_STR = "2026-10-20"
APP_NAME = "Node Talker"

INSTALL_BIN_PATH = "/usr/local/bin/nodetalker.py"
INSTALL_DIR = "/usr/local/lib/asl_dvs/nodetalker"
SERVICE_NAME = "nodetalker.service"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/nodetalker.service"
LEGACY_BIN_PATH = "/usr/local/bin/nodelisten.py"
LEGACY_INSTALL_DIR = "/usr/local/lib/asl_dvs/nodelisten"
LEGACY_SERVICE = "nodelisten.service"
LEGACY_SERVICE_PATH = "/etc/systemd/system/nodelisten.service"
_SYSTEMD_UNIT_DIR = "/etc/systemd/system"

CONFIG_DIR = os.environ.get("NODETALKER_CONFIG_DIR", "/etc/asl_dvs")
CONFIG_PATH = os.path.join(CONFIG_DIR, "nodetalker.conf")
CONFIG_SECTION = "nodetalker"
LEGACY_SECTION = "nodelisten"
BACKUP_DIR = os.path.join(CONFIG_DIR, "nodetalker_backups")
BACKUP_KEEP = 10
RESTORE_PATH = os.path.join(CONFIG_DIR, "nodetalker_restore.json")
RESTORE_MAX_AGE_SEC = 1800
RPT_CONF = os.environ.get("NODETALKER_RPT_CONF", "/etc/asterisk/rpt.conf")
FEED_PYTHON = "/usr/bin/python3"
FEED_MARKS = ("nodelisten.py,--feed,", "nodetalker.py,--feed,")
HOOK_NOTE = "; nodelisten: sends this node's audio to the Node Listen page (remove it from that page)"

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

def service_content(run_path):
    return f"""[Unit]
Description=Node Talker: ASL node audio in the browser
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
Alias=nodelisten.service
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
    "port": 8993,
    "udp_port": 6200,
    "node": "",
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
    "ptt_mode": "hold",
    "ptt_guard_sec": 60,
    "ptt_rx_gap": False,
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


PTT_GUARDS = (30, 60, 90, 120, 180)


def _norm_ptt_mode(value):
    v = str(value).strip().lower()
    if v not in ("hold", "tap"):
        raise ValueError("ptt_mode must be hold or tap")
    return v


def _norm_ptt_guard(value):
    v = int(str(value).strip())
    if v not in PTT_GUARDS:
        raise ValueError("ptt_guard_sec must be 30, 60, 90, 120 or 180")
    return v


def _norm_node(value):
    v = str(value).strip()
    if v and not re.fullmatch(r"\d{1,7}", v):
        raise ValueError("node must be a node number")
    return v


def _norm_gain(value):
    v = int(round(float(str(value).strip())))
    if not -12 <= v <= 12:
        raise ValueError("gains must be -12 to +12 dB")
    return v


_NORMALIZERS = {
    "port": _norm_port,
    "udp_port": _norm_port,
    "node": _norm_node,
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
    "ptt_mode": _norm_ptt_mode,
    "ptt_guard_sec": _norm_ptt_guard,
    "ptt_rx_gap": _parse_bool,
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
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{os.path.basename(path)}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        if like is not None:
            os.chmod(tmp, like.st_mode & 0o7777)
            try:
                os.chown(tmp, like.st_uid, like.st_gid)
            except OSError:
                pass
        else:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        _remove_quiet(tmp)
        raise
    try:
        fd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def save_config(cfg):
    body = [f"{key} = {'true' if cfg[key] is True else 'false' if cfg[key] is False else cfg[key]}" for key in DEFAULT_CONFIG]
    lines = [f"[{CONFIG_SECTION}]"] + body + ["", f"[{LEGACY_SECTION}]"] + body
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
    if cfg["port"] == cfg["udp_port"]:
        errors.append("port and udp_port must differ")
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    try:
        save_config(cfg)
    except OSError as exc:
        return {"ok": False, "error": f"could not save {CONFIG_PATH}: {exc}"}
    with _config_lock:
        _config.update(cfg)
    restart = any(cfg[k] != old[k] for k in ("port", "udp_port", "https"))
    msg = "Saved."
    if cfg["udp_port"] != old["udp_port"]:
        try:
            st = rpt_state()
            hooked = [n["node"] for n in st["nodes"] if n["ours"]]
            if hooked:
                r = hook_enable(hooked[0])
                msg += " " + r.get("message", r.get("error", ""))
        except OSError as exc:
            msg += f" rpt.conf not updated: {exc}"
    if restart:
        msg += " Node Talker restarts to use the new setting."
        if not _schedule_restart():
            msg += " (Restart it by hand: systemctl restart nodetalker)"
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


_SESSION_COOKIE_NAME = "nodetalker_session"
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
            pump_ok = time.monotonic() - HUB.pump_beat < 5.0 and time.monotonic() - TALKER.beat < 5.0
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
                          "--unit=nodetalker-selfrestart", "systemctl", "restart", SERVICE_NAME],
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


class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.inbuf = bytearray()
        self.frames = deque()
        self.listeners = set()
        self.packets = 0
        self.dropped = 0
        self.last_rx = 0.0
        self.level_db = -120.0
        self.peak_db = -120.0
        self.last_active = 0.0
        self.pump_beat = time.monotonic()
        self.rate_window = deque(maxlen=60)
        self.udp_error = ""

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
            "receiving": self.last_rx > 0 and now - self.last_rx < 3.0,
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
            "udp_port": _cfg_get("udp_port"),
            "udp_error": self.udp_error,
            "rx_load_pct": RXC.load_pct,
        }


HUB = Hub()


def udp_loop(port):
    while True:
        try:
            sock = udp_socket(port)
        except OSError as exc:
            HUB.udp_error = f"cannot listen on 127.0.0.1:{port}: {exc}"
            log_event(HUB.udp_error + "; retrying in 10s", "err")
            time.sleep(10)
            continue
        HUB.udp_error = ""
        log_event(f"Waiting for node audio on 127.0.0.1:{port}/udp")
        try:
            while True:
                data = sock.recv(8192)
                if data:
                    HUB.feed(data)
        except OSError as exc:
            log_event(f"UDP receive error: {exc}", "err")
        finally:
            sock.close()
        time.sleep(1)


def run_feed(port):
    sock = udp_socket()
    dest = ("127.0.0.1", port)
    fd = sys.stdin.fileno()
    while True:
        try:
            data = os.read(fd, 4096)
        except InterruptedError:
            continue
        except OSError:
            break
        if not data:
            break
        try:
            sock.sendto(data, dest)
        except OSError:
            pass
    return 0


_STANZA_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:\(([^)]*)\))?")
_OUTSTREAM_RE = re.compile(r"^\s*outstreamcmd\s*=>?\s*(.*?)\s*$", re.I)


def legacy_bin_ours():
    if os.path.islink(LEGACY_BIN_PATH) or not os.path.lexists(LEGACY_BIN_PATH):
        return True
    try:
        with open(LEGACY_BIN_PATH, "rb") as fh:
            head = fh.read(8192)
    except OSError:
        return False
    return b'APP_NAME = "Node Listen"' in head or b'APP_NAME = "Node Talker"' in head


def hook_line():
    path = LEGACY_BIN_PATH if legacy_bin_ours() else INSTALL_BIN_PATH
    return f"outstreamcmd = {FEED_PYTHON},{path},--feed,{_cfg_get('udp_port')}"


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
                   "header": i, "outstream": None, "outstream_line": None}
            stanzas.append(cur)
            continue
        if cur is not None:
            mo = _OUTSTREAM_RE.match(line)
            if mo:
                cur["outstream"] = _strip_comment(mo.group(1))
                cur["outstream_line"] = i
    return lines, stanzas


def read_rpt():
    with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
        return parse_rpt(fh.read())


def _is_ours(value):
    return bool(value) and any(m in _squash(value) for m in FEED_MARKS)


def rpt_state():
    _, stanzas = read_rpt()
    by_name = {s["name"]: s for s in stanzas}
    nodes = []
    port_end = f",{_cfg_get('udp_port')}"
    for s in stanzas:
        if not _is_node_name(s["name"]):
            continue
        inherited = None
        for t in s["templates"]:
            ts = by_name.get(t)
            if ts and ts["outstream"]:
                inherited = {"template": t, "value": ts["outstream"]}
        ours = _is_ours(s["outstream"])
        nodes.append({
            "node": s["name"],
            "outstream": s["outstream"],
            "ours": ours,
            "ours_port_ok": ours and _squash(s["outstream"]).endswith(port_end),
            "inherited": inherited,
        })
    return {"path": RPT_CONF, "nodes": nodes, "hook_line": hook_line()}


def _backup_rpt():
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, "rpt.conf." + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    shutil.copy2(RPT_CONF, dest)
    olds = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("rpt.conf."))
    for f in olds[:-BACKUP_KEEP]:
        _remove_quiet(os.path.join(BACKUP_DIR, f))
    return dest


def _remove_ours(lines, stanzas):
    drop = set()
    for s in stanzas:
        if _is_ours(s["outstream"]):
            i = s["outstream_line"]
            drop.add(i)
            if i > 0 and lines[i - 1].strip() == HOOK_NOTE:
                drop.add(i - 1)
    return [ln for i, ln in enumerate(lines) if i not in drop], bool(drop)


def _write_rpt(lines):
    st = os.stat(RPT_CONF)
    backup = _backup_rpt()
    _atomic_write(RPT_CONF, "\n".join(lines), like=st)
    return backup


def _write_failed(exc):
    return {"ok": False, "error": f"Could not write {RPT_CONF}: {exc}"}


def _changed(backup, message):
    return {"ok": True, "changed": True, "backup": backup, "message": f"{message} Backup: {backup}"}


_rpt_lock = threading.Lock()


def hook_enable(node):
    node = _norm_node(node)
    if not node:
        return {"ok": False, "error": "Pick a node."}
    with _rpt_lock:
        lines, stanzas = read_rpt()
        target = _find_stanza(stanzas, node)
        if target is None:
            return {"ok": False, "error": f"Node {node} is not in {RPT_CONF}."}
        if target["outstream"] and not _is_ours(target["outstream"]):
            return {"ok": False, "error": f"Node {node} already has outstreamcmd = {target['outstream']} "
                                           "(a Broadcastify feed?). A node takes one outstreamcmd; remove that line first."}
        want = hook_line()
        if (_is_ours(target["outstream"]) and _squash(target["outstream"]) == _squash(want.split("=", 1)[1])
                and sum(1 for s in stanzas if _is_ours(s["outstream"])) == 1):
            return {"ok": True, "changed": False, "message": f"Node {node} already sends its audio here."}
        lines, _ = _remove_ours(lines, stanzas)
        lines, stanzas = parse_rpt("\n".join(lines))
        at = _find_stanza(stanzas, node)["header"] + 1
        lines[at:at] = [HOOK_NOTE, want]
        try:
            backup = _write_rpt(lines)
        except OSError as exc:
            return _write_failed(exc)
    with _config_lock:
        _config["node"] = node
        cfg = dict(_config)
    try:
        save_config(cfg)
    except OSError:
        pass
    log_event(f"rpt.conf: node {node} now sends its audio to Node Talker (backup {backup})", "ok")
    return _changed(backup, f"Added to node {node}. Restart Asterisk for it to take effect.")


def hook_disable():
    with _rpt_lock:
        lines, stanzas = read_rpt()
        lines, changed = _remove_ours(lines, stanzas)
        if not changed:
            return {"ok": True, "changed": False, "message": "No node sends its audio here."}
        try:
            backup = _write_rpt(lines)
        except OSError as exc:
            return _write_failed(exc)
    log_event(f"rpt.conf: Node Talker line removed (backup {backup})", "ok")
    return _changed(backup, "Removed. Restart Asterisk for it to take effect.")


def restart_asterisk():
    try:
        r = subprocess.run(["systemctl", "restart", "asterisk"], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"systemctl failed: {exc}"}
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout).strip() or f"exit {r.returncode}"}
    log_event("Asterisk restarted from Node Talker", "ok")
    return {"ok": True, "message": "Asterisk restarted. Audio should arrive within a few seconds of the node hearing anything."}


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
    log_event(f"System {what} requested from Node Talker", "warn")

    def go():
        time.sleep(1)
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log_event(f"System {what} failed: {exc}", "err")

    threading.Thread(target=go, daemon=True).start()
    return {"ok": True, "message": message}


_feeder_cache = {"t": 0.0, "pids": []}


def feeder_pids():
    now = time.monotonic()
    if now - _feeder_cache["t"] < 5.0:
        return _feeder_cache["pids"]
    pids = []
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/cmdline", "rb") as fh:
                    cmd = fh.read()
            except OSError:
                continue
            if b"nodelisten.py\0--feed\0" in cmd or b"nodetalker.py\0--feed\0" in cmd:
                pids.append(int(name))
    except OSError:
        pass
    _feeder_cache.update(t=now, pids=pids)
    return pids


def build_status(full):
    st = HUB.snapshot()
    st.update({"version": VERSION, "node": _cfg_get("node"), "uptime": int(time.time() - _START_TIME),
               "jitter_ms": tune_value("jitter_ms")})
    if full:
        st["feeder_pids"] = feeder_pids()
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
        tx = tx_state(node)
        tx.update(TALKER.state())
        st["tx"] = {k: tx.get(k) for k in ("node", "ready", "linked", "keyed", "who", "secs", "tot",
                                            "peak_db", "last_peak_db", "gaps", "last_gaps")}
    else:
        st.pop("listener_list", None)
        st.pop("udp_error", None)
        st.pop("rx_load_pct", None)
    return st


AST_BIN = os.environ.get("NODETALKER_ASTERISK", "asterisk")
DASH_CONF = os.environ.get("NODETALKER_DASH_CONF", "/etc/asl_dvs/asl_dvs.conf")
FAV_PATH = os.path.join(CONFIG_DIR, "nodetalker_favorites.json")
FAV_CONF_PATH = os.path.join(CONFIG_DIR, "nodetalker_favorites.conf")
TUNED_PATH = os.path.join(CONFIG_DIR, "nodetalker_tuned.json")
FAV_MAX = 15
FAV_JSON_MAX = 10
DMR_NET_MAX = 10
DVS_MODES = ("DMR", "STFU", "YSF", "P25", "NXDN", "DSTAR")
FAV_MODES = ("ASL", "EchoLink") + DVS_MODES + ("M17",)
DVS_SEARCH_PATHS = tuple(p for p in (os.environ.get("NODETALKER_DVSWITCH", ""), "/opt/MMDVM_Bridge/dvswitch.sh",
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
AB_INI = os.environ.get("NODETALKER_AB_INI", "/opt/Analog_Bridge/Analog_Bridge.ini")
M17_INI = os.environ.get("NODETALKER_M17_INI", "/opt/USRP2M17/USRP2M17.ini")
M17_HOSTS = os.environ.get("NODETALKER_M17_HOSTS", "/var/lib/mmdvm/M17Hosts.json")
M17_SERVICE = "usrp2m17"
M17_NET_PORTS = (17010, 17000)
M17_USRP_PORTS = (32008, 34008)
M17_GAIN_DB = 3
DEFAULT_BRIDGES = ("1999", "1917")
BLANK_NAME, BLANK_ADDR = "blank", "000000"
_DMR_ADDR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}:\d{1,5}$")
_CALLSIGN_RE = re.compile(r"^[A-Z0-9][A-Z0-9/-]{2,9}$")
TLS_DIR = os.path.join(CONFIG_DIR, "nodetalker_tls")
TLS_CERT = os.path.join(TLS_DIR, "cert.pem")
TLS_KEY = os.path.join(TLS_DIR, "key.pem")
TX_NODE = "1921"
TX_USRP_SEND = 32018
TX_USRP_LISTEN = 34018
TX_NOTE = "; nodelisten: transmit node for the Node Listen page (remove it from that page)"
IAX_CONF = os.environ.get("NODETALKER_IAX_CONF", "/etc/asterisk/iax.conf")
LOCAL_KEY_PATH = os.environ.get("NODETALKER_LOCAL_KEY", "/etc/asl_dvs/local_api.key")
SYSMON_PORT = 9999
INSTMON_PORT = 8990
COCKPIT_PORT = 9090
WEB_PAGES = (("allmon3", "/allmon3/"), ("dvswitch", "/dvswitch/"))
LINK_TTL_SEC = 30.0
POWER_CMDS = {"reboot": (["reboot"], "Rebooting…"), "shutdown": (["shutdown", "-h", "now"], "Shutting down…")}
TX_BUSY_GRACE_SEC = 1.0
_TX_NODES_LINE_RE = re.compile(r"^\s*" + TX_NODE + r"\s*=\s*radio@127\.0\.0\.1(?::\d+)?/" + TX_NODE + r",NONE\s*$")
TX_QUEUE_MAX = 50
TX_DEADMAN_SEC = 1.0
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


def tx_nodes_line():
    port = iax_bindport()
    host = "127.0.0.1" if port == "4569" else f"127.0.0.1:{port}"
    return f"{TX_NODE} = radio@{host}/{TX_NODE},NONE"


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
    s = _CALL_TRIM.sub(" ", str(value or "")).replace("|", "/").strip()[:40]
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


def _norm_fav(f, nets=None):
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
    if mode == "ASL" and num == TX_NODE:
        raise ValueError(f"Node {TX_NODE} is the transmit node, not a favorite")
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


def _fav_line(f):
    if f["mode"] == "M17":
        return f"{f['label']}|{f['num']}|{f['module']}|{f.get('ip', '')}"
    return f"{f['label']}|{f['num']}"


def parse_fav_conf(text, fav_limit=FAV_MAX, net_limit=DMR_NET_MAX):
    nets, cfg, bad, rows = [], {}, [], []
    section = ""
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and "]" in line:
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
    out = ["# nodetalker_favorites.conf: Node Talker favorites in Node Controller's asl_dvs.conf format.",
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


def _check_favs(clean):
    bridges = {v for k, v in bridge_nodes().items() if k in ("digital", "m17") and v}
    seen = set()
    for f in clean:
        if f["mode"] == "ASL" and f["num"] in bridges:
            raise ValueError(f"Node {f['num']} is a bridge node, not a favorite")
        key = fav_target(f)
        if key in seen:
            raise ValueError(f"{fav_name(f)} is listed twice.")
        seen.add(key)


def fav_save(items):
    if not isinstance(items, list):
        return {"ok": False, "error": "favorites must be a list"}
    if len(items) > FAV_MAX:
        return {"ok": False, "error": f"At most {FAV_MAX} favorites."}
    with _fav_lock:
        doc = fav_doc()
        nets, added = list(doc["nets"]), []
        for f in items:
            if not isinstance(f, dict) or _mode_safe(f) != "DMR":
                continue
            net = str(f.get("net", "") or "").strip().lower()
            if not net or any(n["name"].lower() == net for n in nets):
                continue
            hit = next((n for n in dashboard_conf()["nets"] if n["name"].lower() == net), None)
            if hit is not None and len(nets) < DMR_NET_MAX:
                nets.append(hit)
                added.append(hit["name"])
        try:
            clean = [_norm_fav(f, nets) for f in items]
            _check_favs(clean)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            _write_fav_doc(clean, nets, doc["cfg"])
        except OSError as exc:
            return {"ok": False, "error": f"Could not save: {exc}"}
    log_event(f"Favorites saved ({len(clean)})" + (f"; DMR network {', '.join(added)} copied from Node Controller" if added else ""), "ok")
    msg = f"Saved {len(clean)} favorite(s)."
    if added:
        msg += f" Copied DMR network {', '.join(added)} from Node Controller."
    return {"ok": True, "message": msg, "favs": clean}


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
    if v == TX_NODE:
        raise ValueError(f"Node {TX_NODE} is the transmit node, not a bridge node")
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


def fav_file_text():
    doc = fav_doc()
    return render_fav_conf(doc["favs"], doc["nets"], doc["cfg"])


def fav_file_put(text):
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "error": "The file is empty."}
    if len(text) > 48 * 1024:
        return {"ok": False, "error": "The file is too big for a favorites file."}
    d = parse_fav_conf(text)
    if d["bad"]:
        return {"ok": False, "error": "Not loaded: " + "; ".join(d["bad"][:3]) + (" ..." if len(d["bad"]) > 3 else "")}
    if d["more"]:
        return {"ok": False, "error": f"Not loaded: the file has more than {FAV_MAX} favorites."}
    try:
        call = _norm_callsign(d["cfg"].get("callsign"))
        b = (d["cfg"].get("bridge_nodes", "").split(",") + ["", ""])[:2]
        dg, m = _norm_bridge(b[0], "The digital bridge node"), _norm_bridge(b[1], "The M17 bridge node")
        _check_favs(d["favs"])
    except ValueError as exc:
        return {"ok": False, "error": f"Not loaded: {exc}"}
    cfg = {"callsign": call, "bridge_nodes": f"{dg},{m}" if dg or m else ""}
    try:
        _write_fav_doc(d["favs"], d["nets"], cfg)
    except OSError as exc:
        return {"ok": False, "error": f"Could not save: {exc}"}
    _bridge_cache["t"] = -60.0
    _dvs_now["dmr"] = ""
    log_event(f"Favorites file loaded ({len(d['favs'])} favorites, {len(d['nets'])} DMR networks)", "ok")
    return {"ok": True, "message": f"Loaded {len(d['favs'])} favorite(s) and {len(d['nets'])} DMR network(s)."}


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
        if not _is_node_name(s["name"]) or s["name"] == TX_NODE:
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
        err = "this version can't connect M17 for Node Talker; update Node Controller."
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
    keep = set(keep) | {TX_NODE}
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
    public = [p for p in peers if p != TX_NODE and p not in bridges and not is_private(p)]
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
        return {"ok": False, "error": f"DVSwitch goes through Node Controller's node {dash_node}, but Node Talker's node is {node}. "
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
                return {"ok": False, "error": "this version of Node Controller can't take networks from Node Talker; update it."
                        if _nc_old(r) else f"Node Controller: {r['error']}"}
            log_event(f"Added DMR network {net['name']} to Node Controller", "ok")
    r = dash_call(body, timeout=100)
    _nc_dvs_status["t"] = -M17_STATUS_TTL
    _lstats_invalidate()
    if r is None:
        return {"ok": False, "error": "Node Controller is not answering."}
    if not r["ok"]:
        if _nc_old(r):
            return {"ok": False, "error": "Node Controller is running, but this version can't tune DVSwitch for Node Talker: update Node Controller."}
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
        return {"ok": False, "error": f"M17 goes through Node Controller's node {dash_node}, but Node Talker's node is {node}. "
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


def fav_connect(index, net_action=None):
    favs = fav_load()
    try:
        f = favs[int(index)]
    except (ValueError, TypeError, IndexError):
        return {"ok": False, "error": "Pick a favorite."}
    node, err = _connect_node()
    if not node:
        return {"ok": False, "error": err}
    if f["mode"] in DVS_MODES:
        return solo_dvs(f, node, net_action if net_action in ("add", "once") else None)
    if f["mode"] == "M17":
        return m17_connect(f, node)
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
    node, err = _connect_node()
    if not node:
        return {"ok": False, "error": err}
    favs = fav_load()
    if index is not None:
        try:
            favs = [favs[int(index)]]
        except (ValueError, TypeError, IndexError):
            return {"ok": False, "error": "Pick a favorite."}
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
    return {"ok": True, "message": f"Disconnected {', '.join(done + hit)}."}


MMDVM_DIR = os.environ.get("NODETALKER_MMDVM_DIR", "/var/lib/mmdvm")
TUNE_LIST_FILES = {
    "YSF": (("YSFHosts.txt", "/opt/YSFGateway"),),
    "P25": (("P25Hosts.txt", "/opt/P25Gateway"),),
    "NXDN": (("NXDNHosts.txt", "/opt/NXDNGateway"),),
    "STFU": (("TGList_BM.txt", ""),),
    "DSTAR": (("DPlus_Hosts.txt", ""), ("DExtra_Hosts.txt", ""), ("DCS_Hosts.txt", "")),
}
TUNE_TEXT_MAX = 64
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


def _tune_fav(b):
    if not isinstance(b, dict):
        raise ValueError("Pick a mode and a station.")
    mode = _mode_of(b.get("mode"))
    if mode not in DVS_MODES and mode != "M17":
        raise ValueError(f"{mode} is not a digital mode; connect it from a favorite.")
    num = str(b.get("num", "") or "").strip()
    if not num:
        raise ValueError("Type or pick a talkgroup, room or reflector first.")
    mod = str(b.get("module", "") or "").strip().upper()
    f = {"mode": mode, "num": num, "net": b.get("net", ""), "label": b.get("label", "")}
    if mode == "DSTAR" and mod and " " not in num and not num.upper().endswith("L"):
        f["num"] = f"{num} {mod}"
    if mode == "M17":
        f["module"] = mod
    return _norm_fav(f, nets_load())


def tune_connect(b):
    try:
        f = _tune_fav(b)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    node, err = _connect_node()
    if not node:
        return {"ok": False, "error": err}
    if f["mode"] == "M17":
        return m17_connect(f, node)
    act = b.get("net_action")
    return solo_dvs(f, node, act if act in ("add", "once") else None)


def tune_save(b):
    try:
        f = _tune_fav(b)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    favs = fav_load()
    if any(fav_target(x) == fav_target(f) for x in favs):
        return {"ok": True, "message": f"{fav_name(f)} is already in favorites."}
    if len(favs) >= FAV_MAX:
        return {"ok": False, "error": f"Favorites are full ({FAV_MAX}). Remove one on the Setup tab first."}
    n = len(favs) + 1
    r = fav_save(favs + [f])
    if r.get("ok"):
        log_event(f"Saved {fav_name(f)} to favorites", "ok")
        return {"ok": True, "message": f"Saved {fav_name(f)} to favorites ({n} of {FAV_MAX})."}
    return r


def tune_disconnect():
    node, err = _connect_node()
    if not node:
        return {"ok": False, "error": err}
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
        self.seq = 0
        self.sock = None
        self.send_lock = threading.Lock()
        self.beat = time.monotonic()
        self.last_unkey = 0.0
        self.peak = -120.0
        self.last_peak = None
        self.gaps = 0
        self.last_gaps = None
        self.primed_once = False

    def _socket(self):
        if self.sock is None:
            self.sock = udp_socket()
        return self.sock

    def _packet(self, payload, keyup):
        with self.send_lock:
            self.seq = (self.seq + 1) & 0x7FFFFFFF
            head = USRP_HEADER.pack(b"USRP", self.seq, 0, 1 if keyup else 0, 0, 0, 0, 0)
            try:
                self._socket().sendto(head + payload, ("127.0.0.1", TX_USRP_SEND))
            except OSError:
                pass

    def state(self):
        with self.lock:
            return {"keyed": self.keyed, "who": self.who if self.keyed else "",
                    "secs": round(time.monotonic() - self.start, 1) if self.keyed else 0,
                    "tot": _cfg_get("tot_sec"), "peak_db": round(self.peak, 1) if self.keyed else None,
                    "last_peak_db": self.last_peak, "gaps": self.gaps if self.keyed else None,
                    "last_gaps": self.last_gaps}

    def key(self, owner, who):
        st = tx_state()
        if not st["ready"]:
            return False, "not-ready"
        if st["linked"] is False:
            return False, "not-linked"
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
        log_event(f"TX: {who} keyed node {TX_NODE}", "ok")
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
        for _ in range(3):
            self._packet(PCM_SILENCE, False)
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


def usrp_drain_loop():
    while True:
        try:
            s = udp_socket(TX_USRP_LISTEN)
        except OSError as exc:
            log_event(f"Can't listen on 127.0.0.1:{TX_USRP_LISTEN} for node {TX_NODE}: {exc}", "warn")
            time.sleep(60)
            continue
        try:
            while True:
                s.recv(4096)
        except OSError:
            pass
        finally:
            s.close()
        time.sleep(1)


def _tx_stanza(lines, stanzas):
    for i, s in enumerate(stanzas):
        if s["name"] == TX_NODE:
            end = stanzas[i + 1]["header"] if i + 1 < len(stanzas) else len(lines)
            return s, end
    return None, None


def _tx_ours(lines, s):
    h = s["header"]
    return h > 0 and lines[h - 1].strip() == TX_NOTE


def _has_line(lines, want):
    want = _squash(want)
    return any(_squash(ln.strip()) == want for ln in lines)


def _put_nodes_line(lines, nodes_line):
    new = [ln for ln in lines if not _TX_NODES_LINE_RE.match(ln)]
    _, stanzas = parse_rpt("\n".join(new))
    nodes_st = next((x for x in stanzas if x["name"].lower() == "nodes"), None)
    if nodes_st is not None:
        new.insert(nodes_st["header"] + 1, nodes_line)
    else:
        new += ["[nodes]", nodes_line, ""]
    return new


def tx_state(main=None):
    out = {"node": TX_NODE, "main": main_node() if main is None else main, "defined": False, "ours": False, "nodes_line": False,
           "ready": False, "linked": None, "rxchannel": f"USRP/127.0.0.1:{TX_USRP_LISTEN}:{TX_USRP_SEND}"}
    try:
        lines, stanzas = read_rpt()
    except OSError as exc:
        out["error"] = f"Could not read {RPT_CONF}: {exc}"
        return out
    s, end = _tx_stanza(lines, stanzas)
    if s is not None:
        out["defined"] = True
        out["ours"] = _tx_ours(lines, s)
        body = _squash("\n".join(lines[s["header"]:end]))
        out["rx_ok"] = f"rxchannel={out['rxchannel']}" in body
    out["nodes_line"] = _has_line(lines, tx_nodes_line())
    out["nodes_line_other"] = not out["nodes_line"] and any(_TX_NODES_LINE_RE.match(ln) for ln in lines)
    out["ready"] = out["defined"] and out.get("rx_ok", False) and bool(out["main"]) and out["nodes_line"]
    if out["ready"]:
        ok, links = rpt_links(out["main"])
        out["linked"] = any(l["node"] == TX_NODE for l in links) if ok else None
    return out


def tx_enable():
    main = main_node()
    if not main:
        return {"ok": False, "error": "Set the node first (Send its audio here, or the Dashboard's node number)."}
    with _rpt_lock:
        lines, stanzas = read_rpt()
        s, _ = _tx_stanza(lines, stanzas)
        if s is not None:
            if _tx_ours(lines, s):
                want = tx_nodes_line()
                if _has_line(lines, want):
                    return {"ok": True, "changed": False, "message": f"Node {TX_NODE} is already set up."}
                try:
                    backup = _write_rpt(_put_nodes_line(lines, want))
                except OSError as exc:
                    return _write_failed(exc)
                log_event(f"rpt.conf: fixed the [nodes] line for node {TX_NODE}: {want} (backup {backup})", "ok")
                return _changed(backup, f"Fixed the [nodes] line for node {TX_NODE} ({want}). Restart Asterisk.")
            return {"ok": False, "error": f"rpt.conf already has a [{TX_NODE}] node that Node Talker didn't add. Remove it or pick another node."}
        main_st = _find_stanza(stanzas, main)
        if main_st is None:
            return {"ok": False, "error": f"Node {main} is not in {RPT_CONF}."}
        tpl = f"({','.join(main_st['templates'])})" if main_st["templates"] else ""
        block = ["", TX_NOTE, f"[{TX_NODE}]{tpl}", f"rxchannel = USRP/127.0.0.1:{TX_USRP_LISTEN}:{TX_USRP_SEND}",
                 "duplex = 0", "hangtime = 0", "althangtime = 0", "holdofftelem = 1", "telemdefault = 0",
                 "nounkeyct = 1"]
        new = list(lines)
        while new and new[-1].strip() == "":
            new.pop()
        new += block + [""]
        try:
            backup = _write_rpt(_put_nodes_line(new, tx_nodes_line()))
        except OSError as exc:
            return _write_failed(exc)
    log_event(f"rpt.conf: added transmit node {TX_NODE} for node {main} (backup {backup})", "ok")
    return _changed(backup, f"Added node {TX_NODE}. Restart Asterisk, then Node Talker links it to node {main}.")


def tx_unlink(why):
    main = main_node()
    if not main:
        return
    ok, links = rpt_links(main, max_age=0)
    if ok and any(l["node"] == TX_NODE for l in links):
        ilink(main, 1, TX_NODE)
        log_event(f"Unlinked node {TX_NODE} from node {main} ({why})", "ok")


def tx_disable():
    tx_unlink("transmit node removed")
    with _rpt_lock:
        lines, stanzas = read_rpt()
        s, end = _tx_stanza(lines, stanzas)
        drop = set()
        if s is not None and _tx_ours(lines, s):
            drop.update(range(s["header"] - 1, end))
        for i, ln in enumerate(lines):
            if _TX_NODES_LINE_RE.match(ln):
                drop.add(i)
        if not drop:
            return {"ok": True, "changed": False, "message": f"Node Talker has no node {TX_NODE} in rpt.conf."}
        new = [ln for i, ln in enumerate(lines) if i not in drop]
        while len(new) > 1 and new[-1].strip() == "" and new[-2].strip() == "":
            new.pop()
        try:
            backup = _write_rpt(new)
        except OSError as exc:
            return _write_failed(exc)
    log_event(f"rpt.conf: removed transmit node {TX_NODE} (backup {backup})", "ok")
    return _changed(backup, f"Removed node {TX_NODE}. Restart Asterisk for it to take effect.")


def link_keeper_loop():
    last = None
    while True:
        time.sleep(20)
        try:
            st = tx_state()
            if not st["ready"] or st["linked"] is None:
                continue
            if st["linked"]:
                if last is False:
                    log_event(f"Node {TX_NODE} is linked to node {st['main']} again", "ok")
                last = True
                continue
            ok, out = ilink(st["main"], 3, TX_NODE)
            if last is not False:
                log_event(f"Node {TX_NODE} was not linked to node {st['main']}; linking it"
                          + ("" if ok else f" failed: {out.strip()[:120]}"), "warn")
            last = False
        except Exception as exc:
            log_event(f"Link keeper error: {exc}", "err")


_CSS = r""":root{--bg:#0e141b;--card:#161f29;--card2:#121a23;--line:#243140;--line2:#2a3846;--text:#e6edf3;--muted:#9fb0bf;
--soft:#c9d4de;--accent:#22c3a6;--accent-ink:#06231e;--accent-dim:#123a35;--amber:#f4c04e;--amber-bg:#3a2a07;--red:#ff8a8f;--red-line:#f2545b}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
body{display:flex;flex-direction:column;height:100vh;height:100dvh;overflow:hidden}
header{flex:none;display:flex;align-items:center;gap:10px;padding:calc(12px + env(safe-area-inset-top)) 16px 12px;border-bottom:1px solid var(--line);background:#111922;z-index:5}
header h1{font-size:18px;margin:0;white-space:nowrap}
header .ver{color:var(--muted);font-size:12px}
header .sp{flex:1}
.pill{display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 12px;border:1px solid var(--line2);border-radius:999px;color:var(--text);text-decoration:none;background:transparent;cursor:pointer;font:inherit;font-size:13px;white-space:nowrap}
.pill:hover{border-color:var(--accent)}
.ql-row{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 2px}
.ql{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;text-decoration:none;white-space:nowrap;color:var(--amber);border:1px solid rgba(244,192,78,.45);background:rgba(255,61,90,.15);text-shadow:0 0 8px rgba(255,208,64,.4);border-radius:4px;padding:8px 12px;cursor:pointer;transition:all .14s}
.ql:hover{filter:brightness(1.5);box-shadow:0 0 10px currentColor}
.ql:active{transform:scale(.95)}
main{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:14px max(16px,calc((100% - 608px) / 2)) 24px;overflow-wrap:anywhere}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:14px}
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
#login-tls{max-width:300px;font-size:.78rem;color:#ff3d5a;margin-top:.4rem}#login-tls:empty{display:none}
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
:root{--tn-gap:8px;--tn-h:44px;--tn-font:15px}
.tn-bar{display:flex;flex-wrap:wrap;gap:var(--tn-gap);align-items:center}
.tn-bar select,.tn-bar input{min-height:var(--tn-h);font-size:var(--tn-font)}
#t-mode{flex:0 0 auto;width:6.2rem}
#t-net{flex:0 0 auto;width:7rem}
#t-mod{flex:0 0 auto;width:4.6rem}
#t-find{flex:1 1 6rem;min-width:5rem;max-width:10rem}
#t-pick{flex:2 1 7rem;min-width:0}
.tn-bar .btn{min-height:var(--tn-h);padding:0 14px}
.btn-last{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;font-weight:700;letter-spacing:.04em;min-height:var(--tn-h);padding:0 10px;border-radius:6px;border:1px solid rgba(244,192,78,.45);background:rgba(255,208,64,.05);color:var(--amber);cursor:pointer}
.btn-last.lh-off{opacity:.4;color:var(--muted);border-color:var(--muted);background:transparent;cursor:default}
.tn-msg{margin-top:8px;font-size:13px;color:var(--muted);min-height:1em}
.tn-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:10px}
#t-now{flex:1;min-width:0;overflow-wrap:anywhere}
#t-off{flex:none;white-space:nowrap}
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
nav.tabs{flex:none;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));background:#111922;border-top:1px solid var(--line);padding:4px 6px calc(8px + env(safe-area-inset-bottom));z-index:5}
nav.tabs button{background:transparent;border:0;min-height:52px;color:var(--muted);font-size:13px;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}
nav.tabs button[aria-current=page]{color:var(--accent);font-weight:700}
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
#ptt.guard-warn{border-color:var(--amber);box-shadow:0 0 0 6px rgba(244,192,78,.18)}
#ptt.guard-warn #ptt-time{color:var(--amber);animation:guardblink 1s steps(2,start) infinite}
@keyframes guardblink{to{visibility:hidden}}
.sel-card{display:flex;flex-direction:column;gap:6px;background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:10px}
.tag{display:inline-block;padding:2px 8px;border:1px solid var(--accent);border-radius:7px;color:#7fd8c6;font-size:12px;font-weight:700;font-family:ui-monospace,Menlo,Consolas,monospace}
.fav-row{display:grid;grid-template-columns:110px 124px minmax(0,1fr) 44px;gap:6px;margin:6px 0}
.fav-row input,.fav-row select{min-width:0;width:100%}
.fav-row button{min-height:40px;border-radius:8px;border:1px solid var(--line2);background:transparent;color:var(--red);cursor:pointer}
@media (max-width:420px){header{gap:6px;padding:calc(10px + env(safe-area-inset-top)) 12px 10px}header .ver{display:none}.pill{padding:0 10px}}
@media (max-width:480px){.fav-row{grid-template-columns:92px 108px minmax(0,1fr) 40px}}
.fav-row .fav-net{grid-column:2/-1}
.net-row{display:grid;grid-template-columns:minmax(0,.8fr) minmax(0,1.3fr) minmax(0,.9fr) 44px;gap:6px;margin:6px 0}
.net-row input{min-width:0;width:100%}
.net-row .net-url{grid-column:1/-1}
.net-row button{min-height:40px;border-radius:8px;border:1px solid var(--line2);background:transparent;color:var(--red);cursor:pointer}
@media (max-width:480px){.net-row{grid-template-columns:minmax(0,1fr) minmax(0,1fr) 40px}.net-row .net-pw{grid-column:1/3}}
"""

_JS = r"""const $ = (id) => document.getElementById(id);
let loginWanted = false;
let authed = false, publicListen = false, dashPort = 8989, tab = 'listen', lastLogId = 0, lastStatus = null;
let ctx = null, gainNode = null, ctrl = null, playing = false, nextT = 0;
let mediaDest = null, wakeLock = null, nodeLabel = '';
let pend = new Float32Array(1600), pendN = 0, peakLocal = 0, retryTimer = null;
let favs = [], favEdit = [], dashFavs = [], favMax = 15, favNets = [], favModes = ['ASL', 'EchoLink', 'M17'];
let nets = [], netMax = 10;
const FAV_HINT = {ASL: ['Node', 'Node number', 'numeric'], EchoLink: ['Number', 'EchoLink number', 'numeric'],
  DMR: ['TG', 'DMR talkgroup', 'numeric'], STFU: ['TG', 'STFU talkgroup', 'numeric'], YSF: ['Reflector', 'YSF reflector', 'text'],
  P25: ['TG', 'P25 talkgroup', 'numeric'], NXDN: ['TG', 'NXDN talkgroup', 'numeric'],
  DSTAR: ['REF001 C', 'D-STAR reflector and module', 'text'], M17: ['M17-USA A', 'Reflector and module', 'text']};
let ws = null, wsReady = false, wsRetry = null, talking = false, keyed = false, keyedAt = 0, totSec = 120;
let micPending = false, jitterSec = 0.25, sysmonPort = null;
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
let streamPcm = false, oddByte = -1, ups = null, otaRec = null, nodeTesting = false, autoWait = null, starting = false;
let listenAt = 0, rxLastDb = -120, chk = null, chkUndo = {}, chkCfg = null;
let busNode = null, analyser = null, specBins = null, specRaf = 0, specLast = 0, busyText = '', pttState = 'off', ownUnkeyAt = -1e9;
let specMode = 'waterfall';
let hs = {out: '', mic: '', btn: 'listen'};
try { Object.assign(hs, JSON.parse(localStorage.getItem('nlHeadset') || '{}')); } catch (e) {}
let hsTx = false, outLost = 0, devCount = -1, lastDevChange = 0;
const PTT_GUARDS = [30, 60, 90, 120, 180], TAP_IGNORE_MS = 500, GUARD_WARN_SEC = 10;
const RX_GAP_MS = 4000, RX_QUIET_MS = 300, RX_ACTIVE_DB = -50, OWN_TX_IGNORE_MS = 2500, RX_LOCAL_TRUST_MS = 2000, RX_HOLD_MS = 600;
let ptt = {mode: 'hold', guard: 60, gap: false}, pttSrc = '', tapAt = 0, guardWarned = false, guardStop = '';
let rxSeenAt = -1e9, rxLocalAt = -1e9, rxStatusOn = false, gapShown = '';
try {
  const s = JSON.parse(localStorage.getItem('nlPtt') || 'null');
  if (s && (s.mode === 'hold' || s.mode === 'tap') && PTT_GUARDS.includes(Number(s.guard))) { ptt = {mode: s.mode, guard: Number(s.guard), gap: s.gap === true}; pttSrc = 'phone'; }
} catch (e) {}
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

const FOLDS = ['rx', 'tx', 'cfg', 'fav', 'dig', 'chk', 'lvl', 'mic', 'hs', 'play', 'log'];

function foldOpen(k) { return !$('cb-' + k).classList.contains('hidden'); }

function foldSet(k, open) {
  const b = $('cd-' + k).querySelector('.fold-btn');
  $('cb-' + k).classList.toggle('hidden', !open);
  b.setAttribute('aria-expanded', open ? 'true' : 'false');
  b.querySelector('.fold-i').textContent = open ? '▾' : '▸';
  if (!open) return;
  if (k === 'fav') loadDashFavs();
  if (k === 'dig') loadDigital();
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
  try { localStorage.setItem('nlTab', name); } catch (e) {}
  if (name === 'connect') loadFavs();
  if (name === 'setup') { loadNode(); loadTx(); loadConfig(); loadFavEditor(); loadDigital(); micSummary(); playSummary(); if (chkShown && !chk) chkShow(chkShown); }
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
  let want = 'listen';
  try { want = localStorage.getItem('nlTab') || 'listen'; } catch (e) {}
  showTab(authed ? want : 'listen');
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
  hostLinks(d);
  sysmonPort = d.sysmon_port || null;
  if (!d.backend) $('login-msg').textContent = 'No root password is set on this Pi, so login cannot work.';
  render();
  autoListen();
  if (authed) pttFromPi(false);
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

async function login(ev) {
  ev.preventDefault();
  $('login-btn').disabled = true;
  $('login-msg').textContent = '';
  const d = await post('/api/login', {password: $('pw').value});
  $('login-btn').disabled = false;
  $('pw').value = '';
  if (d.ok) { authed = true; loginWanted = false; render(); autoListen(); loadFavs(); pttFromPi(false); pollHostLinks(); }
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

function favNum(f) {
  if (f.mode === 'M17') return f.num + (f.module ? ' ' + f.module : '');
  if (f.mode === 'DMR') return (f.net ? f.net + ' ' : '') + f.num;
  if (f.mode === 'DSTAR') return f.num.trim().replace(/ +/, ' ');
  return f.num;
}
function modeName(m) { return m === 'DSTAR' ? 'D-STAR' : m; }
const DVS = ['DMR', 'STFU', 'YSF', 'P25', 'NXDN', 'DSTAR'];

let linkedTargets = new Set();
function linkedFavs(d) {
  const links = (d && d.links) || [];
  const set = new Set(links.map((l) => l.node));
  if (d && d.m17) set.add(d.m17);
  if (d && d.tuned) set.add(d.tuned);
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
  const feedCls = d.receiving ? 'on' : (d.packets ? 'warn' : 'err');
  const feedTxt = d.receiving ? ('receiving, ' + d.packets_per_sec + ' packets/s')
    : (d.last_rx_age != null ? 'no audio for ' + Math.round(d.last_rx_age) + ' s' : 'nothing received yet');
  $('st-feed').className = 'dot ' + feedCls;
  $('st-feed-t').textContent = d.receiving ? 'feed' : (d.last_rx_age != null ? 'no feed ' + Math.round(d.last_rx_age) + ' s' : 'no feed yet');
  $('st-feed-w').title = 'Feed from Asterisk: ' + feedTxt;
  $('st-active').className = 'dot ' + (d.audio_active ? 'rx' : '');
  if (!talking) $('st-level').textContent = fmtDb(d.peak_db);
  if (d.jitter_ms) jitterSec = d.jitter_ms / 1000;
  if (!playing && !talking) $('meter-bar').style.width = dbPct(d.peak_db) + '%';
  if (chk && chk.running) chkPoll(d);
  if (!authed) return;
  const tx = d.tx || {};
  $('s-tx').className = 'dot ' + (tx.keyed ? 'tx' : '');
  $('s-tx-w').title = tx.keyed ? 'Transmitting: ' + tx.who + ' ' + fmtSecs(tx.secs) : (tx.ready ? 'Nobody is transmitting' : 'Transmit node not set up');
  busyText = tx.keyed && !talking && !keyed && performance.now() - ownUnkeyAt > 2500 ? 'Busy: ' + tx.who + ' ' + fmtSecs(tx.secs) : '';
  rxStatus(!!d.audio_active || !!busyText);
  pttLabel();
  totSec = tx.tot || totSec;
  $('tune-txpk').textContent = tx.keyed && tx.peak_db != null ? fmtDb(tx.peak_db) + ' (now)'
    : (tx.last_peak_db != null ? fmtDb(tx.last_peak_db) + ' (last transmission)' : 'no transmission yet');
  $('tune-rxpk').textContent = fmtDb(d.peak_db);
  if (d.rx_load_pct != null) $('rx-load').textContent = d.rx_load_pct + ' % of one CPU core (last 5 s)';
  const gaps = tx.keyed ? tx.gaps : tx.last_gaps;
  $('tune-gaps').textContent = gaps == null ? '-' : (gaps ? gaps + ' (raise the TX buffer if this keeps happening)' : 'none');
  $('ptt-info').textContent = tx.ready ? ('Node ' + tx.node + (tx.linked === false ? ' (not linked yet)' : '') + ' · time-out ' + fmtSecs(totSec))
    : 'Set up node ' + (tx.node || '1921') + ' on the Setup tab to transmit.';
  const tb = $('s-links');
  tb.innerHTML = '';
  const links = d.links || [];
  links.forEach((l) => {
    const tr = document.createElement('tr');
    const f = favs.find((x) => x.target === l.node);
    [l.node + (l.node === tx.node ? ' (TX)' : ''), f ? f.label : '', l.dir, l.time, l.state].forEach((v) => {
      const td = document.createElement('td'); td.textContent = v || ''; td.title = v || ''; tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  $('s-nolinks').classList.toggle('hidden', links.length > 0);
  $('s-links-err').classList.toggle('hidden', d.links_ok !== false);
  linkedTargets = new Set(linkedFavs(d).map((f) => f.target));
  connectLabel();
  $('t-now').textContent = d.tuned_now ? 'Tuned: ' + d.tuned_now : '';
  $('nd-feeder').textContent = d.feeder_pids && d.feeder_pids.length ? 'running (pid ' + d.feeder_pids.join(', ') + ')' : 'not running';
  if (d.udp_port) $('nd-udp').textContent = d.udp_error ? d.udp_error : '127.0.0.1:' + d.udp_port + ' (listening)';
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
  if (peakDb(peakLocal) > RX_ACTIVE_DB) rxSeen();
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

function framesOf(f32) {
  const out = [];
  for (let i = 0; i + 160 <= f32.length; i += 160) {
    let ss = 0, pk = 0;
    for (let j = i; j < i + 160; j++) { const v = f32[j], a = v < 0 ? -v : v; ss += v * v; if (a > pk) pk = a; }
    out.push({db: ss > 0 ? 10 * Math.log10(ss / 160) : -120, pk: peakDb(pk), lim: 0, gate: false});
  }
  return out;
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

function lagOf(tx, rx) {
  const e = (f) => Math.max(0, f.db + 60);
  let best = 0, bestS = -1;
  for (let L = 0; L < Math.min(150, rx.length); L++) {
    let s = 0;
    for (let i = 0; i < tx.length && i + L < rx.length; i++) s += e(tx[i]) * e(rx[i + L]);
    if (s > bestS) { bestS = s; best = L; }
  }
  return best;
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
  if (chk && chk.running && talking && keyed && !testing && !nodeTesting) accAdd(chk.tx, st);
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
  if (otaRec) otaRec.push(v);
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
  const tap = ptt.mode === 'tap';
  $('ptt-label').textContent = pttState === 'talking' ? (hsTx ? 'TALKING (headset)' : tap ? 'TALKING · tap to stop' : 'TALKING')
    : pttState === 'keying' ? 'Keying...' : (busyText || (gapLeft() > 0 ? 'Wait...' : tap ? 'Tap to talk' : 'Hold to talk'));
  $('ptt').setAttribute('aria-label', tap ? 'Push to talk: tap to transmit, tap again to stop' : 'Push to talk: hold to transmit');
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
  ws.onopen = () => { wsReady = true; pttUi('ready', connBusy ? undefined : ''); };
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
        'not-ready': 'Node 1921 is not set up yet (Setup tab).',
        'not-linked': 'Node 1921 is not linked to the node yet. Restart Asterisk once after adding it; Node Talker relinks it within 20 s.'}[m.why] || ('Refused: ' + m.why);
      endTalk(); pttUi('ready', why, 'warn');
    } else if (m.ev === 'unkeyed') {
      keyed = false; endTalk();
      if (guardStop) { pttUi('ready', guardStop, 'warn'); guardStop = ''; return; }
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

async function nodeTest() {
  const out = 'node-test-msg';
  if (testing || talking || nodeTesting) return;
  const tx = (lastStatus && lastStatus.tx) || {};
  if (!tx.ready) { note(out, 'warn', 'Set up node 1921 first (Transmit card).'); return; }
  if (!window.confirm('This transmits for 4 s through the node: it goes out over the air and to every linked node. Go ahead?')) return;
  nodeTesting = true; $('node-test').disabled = true;
  const pc = newAudioCtx();
  try { pc.resume(); } catch (e) {}
  const wasPlaying = playing;
  try {
    note(out, '', 'Connecting...');
    if (!playing) startListen();
    if (!wsReady) openTalk(true);
    for (let i = 0; i < 40 && !(wsReady && playing && /^Listening/.test($('listen-msg').textContent)); i++) await sleep(100);
    if (!wsReady) throw new Error('the talk channel did not open');
    if (!/^Listening/.test($('listen-msg').textContent)) throw new Error('the listen stream did not start');
    otaRec = [];
    const rxT0 = performance.now();
    let txT0 = 0;
    const txF = [], tap = (st) => { if (!txT0) txT0 = performance.now(); txF.push(st); };
    micTaps.push(tap);
    vuHold = {db: -120, t: 0};
    note(out, '', 'Transmitting 4 s: talk as you would on the air...');
    await pttDown();
    vuRun($('vu-mic'), () => nodeTesting && talking);
    for (let i = 0; i < 30 && talking && !keyed; i++) await sleep(100);
    if (!keyed) { const m = $('ptt-msg').textContent; if (talking) pttUp(); throw new Error(m || 'the node did not key'); }
    await sleep(4000);
    pttUp();
    micTaps = micTaps.filter((f) => f !== tap);
    $('vu-mic').classList.add('hidden');
    note(out, '', 'Collecting what the node sent...');
    await sleep(1500);
    const rec = Float32Array.from(otaRec || []);
    otaRec = null;
    if (!wasPlaying) stopListen();
    let pk = 0;
    for (let i = 0; i < rec.length; i++) { const a = rec[i] < 0 ? -rec[i] : rec[i]; if (a > pk) pk = a; }
    if (!rec.length || pk < 0.003) throw new Error('nothing came back from the node (is its audio feed set up?)');
    const src = playBack(pc, rec);
    const rxF = framesOf(rec), txA = analyze(txF), rxA = analyze(rxF);
    const off = Math.round((txT0 - rxT0) / 20), lag = lagOf(txF, rxF.slice(Math.max(0, off)));
    const delay = lag * 0.02, diff = rxA.speech - txA.speech, agcOn = $('rx-agc').checked;
    $('rep-node').classList.remove('hidden');
    const len = Math.max(txF.length, rxF.length);
    stripDraw($('rep-node-tx'), txF, len);
    stripDraw($('rep-node-rx'), rxF.slice(Math.max(0, off)), len);
    repNumbers($('rep-node-n'), [['Sent', fmtDb(txA.speech)], ['Came back', fmtDb(rxA.speech)],
      ['Difference', (diff >= 0 ? '+' : '') + diff.toFixed(1) + ' dB'], ['Round trip', '~' + delay.toFixed(1) + ' s'],
      ['Came-back peak', fmtDb(rxA.peak)]]);
    let v;
    if (rxA.peak > -1) v = {cls: 'warn', text: 'What came back is clipping: lower TX gain (Audio levels) or the radio and DVSwitch levels (SysMon, Tune).'};
    else if (!agcOn && diff < -6) v = {cls: 'warn', text: 'It came back ' + Math.round(-diff) + ' dB quieter than you sent it: raise TX gain (Audio levels) by about ' + clampStep(-diff - 2) + ' dB, or check the node\'s levels in SysMon, Tune.'};
    else if (!agcOn && diff > 6) v = {cls: 'warn', text: 'It came back ' + Math.round(diff) + ' dB louder than you sent it: lower TX gain (Audio levels) by about ' + clampStep(diff - 2) + ' dB.'};
    else v = {cls: 'ok', text: 'Good: it came back ' + (agcOn ? 'clean' : 'within ' + Math.round(Math.abs(diff)) + ' dB of what you sent') + ', about ' + delay.toFixed(1) + ' s later.'};
    if (agcOn) v.text += ' (Automatic level is on, so what comes back is evened out; turn it off in Audio levels for an exact level comparison.)';
    $('rep-node-v').className = 'rep-v ' + v.cls;
    $('rep-node-v').textContent = v.text;
    note(out, '', 'Playing back what the node sent out.');
    playhead($('rep-node-rx').parentNode, src, pc, rec.length / 8000);
    src.onended = () => { pc.close(); };
  } catch (e) {
    otaRec = null;
    micTaps = micTaps.filter((f) => f === chkMic);
    $('vu-mic').classList.add('hidden');
    if (!wasPlaying && playing) stopListen();
    note(out, 'err', 'Node test: ' + (e.message || e));
    pc.close();
  } finally {
    nodeTesting = false; $('node-test').disabled = false;
  }
}

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
  $('ptt').classList.remove('guard-warn');
  $('ptt-time').textContent = '';
  setTimeout(() => { if (gainNode && !talking) gainNode.gain.value = listenVolume(); }, 1000);
  if (playing && mediaDest && $('player').paused) $('player').play().catch(() => {});
  wakeLockApply();
}

async function pttDown(ev) {
  if (ev) ev.preventDefault();
  if (talking || testing) return;
  const wait = gapLeft();
  if (wait > 0) {
    note('ptt-msg', 'warn', 'Waiting after receive: talk in ' + Math.ceil(wait / 1000) + ' s.');
    if (navigator.vibrate) navigator.vibrate(15);
    return;
  }
  if (!wsReady) { openTalk(); return; }
  talking = true; keyed = false; preKey = []; guardWarned = false; guardStop = '';
  if (gainNode) gainNode.gain.value = 0;
  pttUi('keying', '');
  ws.send(JSON.stringify({op: 'key'}));
  talkTimer = setInterval(talkTick, 250);
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

function ownRecent(now) { return talking || keyed || now - ownUnkeyAt < OWN_TX_IGNORE_MS; }

function rxSeen() {
  const now = performance.now();
  if (ownRecent(now)) return;
  rxSeenAt = rxLocalAt = now;
}

function rxStatus(on) {
  const now = performance.now();
  if (on && !ownRecent(now)) { rxStatusOn = true; return; }
  if (!rxStatusOn) return;
  rxStatusOn = false;
  if (now - rxLocalAt > RX_LOCAL_TRUST_MS && !ownRecent(now)) rxSeenAt = Math.max(rxSeenAt, now - RX_HOLD_MS);
}

function rxRef() {
  const now = performance.now();
  return rxStatusOn && now - rxLocalAt > RX_LOCAL_TRUST_MS ? now : rxSeenAt;
}

function gapLeft() { return ptt.gap ? Math.max(0, RX_GAP_MS - (performance.now() - rxRef())) : 0; }

function gapTick() {
  const left = gapLeft();
  const since = performance.now() - rxRef();
  const txt = left > 0 && since >= RX_QUIET_MS ? String(Math.min(3, Math.floor(left / 1000))) : '';
  if (txt === gapShown) return;
  gapShown = txt;
  const el = $('gap-cd'), box = $('spec-box');
  const showBox = !!txt && box.offsetParent !== null && box.clientHeight > 0;
  if (showBox) el.style.fontSize = Math.max(14, Math.round(Math.min(box.clientHeight * 0.5 * 0.8, box.clientWidth * 0.25 / 0.6 * 0.8))) + 'px';
  el.textContent = showBox ? txt : '';
  el.classList.toggle('hidden', !showBox);
  if (!talking) $('ptt-time').textContent = txt && !showBox ? txt : '';
  pttLabel();
}

function guardOn() { return ptt.mode === 'tap' || hsTx; }
function guardSec() { return Math.min(ptt.guard, totSec); }

function guardBeep() {
  try {
    const c = ctx || newAudioCtx();
    const out = ctx ? (mediaDest || ctx.destination) : c.destination;
    const t0 = c.currentTime + 0.02;
    [0, 0.2].forEach((d) => {
      const o = c.createOscillator(), g = c.createGain();
      o.frequency.value = 1000;
      g.gain.setValueAtTime(0, t0 + d);
      g.gain.linearRampToValueAtTime(0.18, t0 + d + 0.005);
      g.gain.setValueAtTime(0.18, t0 + d + 0.075);
      g.gain.linearRampToValueAtTime(0, t0 + d + 0.08);
      o.connect(g); g.connect(out);
      o.start(t0 + d); o.stop(t0 + d + 0.09);
    });
    if (!ctx) setTimeout(() => { c.close().catch(() => {}); }, 700);
  } catch (e) {}
}

function talkTick() {
  if (!keyed) return;
  const secs = (performance.now() - keyedAt) / 1000;
  if (!guardOn()) { $('ptt-time').textContent = fmtSecs(secs) + ' / ' + fmtSecs(totSec); return; }
  const left = guardSec() - secs;
  $('ptt-time').textContent = fmtSecs(Math.max(0, Math.ceil(left)));
  if (left <= GUARD_WARN_SEC && !guardWarned) {
    guardWarned = true;
    $('ptt').classList.add('guard-warn');
    guardBeep();
    if (navigator.vibrate) navigator.vibrate([60, 60, 60]);
  }
  if (left <= 0) {
    guardStop = 'Guard timer: unkeyed after ' + fmtSecs(guardSec()) + '.';
    if (chk && chk.running) chk.timeout++;
    pttUp();
    pttUi(wsReady ? 'ready' : 'off', guardStop, 'warn');
  }
}

function pttPress(e) {
  if (ptt.mode !== 'tap') { try { $('ptt').setPointerCapture(e.pointerId); } catch (x) {} pttDown(e); return; }
  e.preventDefault();
  if (talking) { if (performance.now() - tapAt >= TAP_IGNORE_MS) pttUp(); return; }
  tapAt = performance.now();
  pttDown(e);
}

function pttRelease(e) { if (ptt.mode !== 'tap') pttUp(e); }

function pttKey(e, down) {
  if (e.key !== ' ' && e.key !== 'Enter') return;
  if (ptt.mode !== 'tap') { if (down && !e.repeat) pttDown(e); else if (!down) pttUp(e); return; }
  e.preventDefault();
  if (down && !e.repeat) pttPress(e);
}

function pttSetUi() {
  $('ptt-hold').checked = ptt.mode === 'hold';
  $('ptt-tap').checked = ptt.mode === 'tap';
  $('ptt-guard').value = String(ptt.guard);
  $('ptt-gap').checked = !!ptt.gap;
  const g = Number($('ptt-guard').value);
  $('ptt-guard-note').textContent = g > totSec ? 'The node\'s TX time-out is ' + fmtSecs(totSec) + ', so it stops then.' : '';
  $('ptt-src').textContent = pttSrc === 'phone' ? 'Saved on this phone; a copy is kept on the Pi.'
    : pttSrc === 'pi' ? 'This phone had nothing saved, so these came from the Pi.' : 'Defaults (nothing saved yet).';
  pttLabel();
}

async function pttFromPi(force) {
  if (pttSrc === 'phone' && !force) { pttSetUi(); return null; }
  const d = await api('/api/config');
  if (!d.ok) return d;
  const c = d.config || {};
  if ((c.ptt_mode === 'hold' || c.ptt_mode === 'tap') && PTT_GUARDS.includes(Number(c.ptt_guard_sec))) {
    ptt = {mode: c.ptt_mode, guard: Number(c.ptt_guard_sec), gap: c.ptt_rx_gap === true};
    pttSrc = 'pi';
  }
  if (force) {
    try { localStorage.setItem('nlPtt', JSON.stringify(ptt)); pttSrc = 'phone'; } catch (e) {}
  }
  pttSetUi();
  return d;
}

async function pttSave() {
  if (talking) pttUp();
  ptt = {mode: $('ptt-tap').checked ? 'tap' : 'hold', guard: Number($('ptt-guard').value) || 60, gap: $('ptt-gap').checked};
  let local = true;
  try { localStorage.setItem('nlPtt', JSON.stringify(ptt)); pttSrc = 'phone'; } catch (e) { local = false; }
  const d = await post('/api/config', {ptt_mode: ptt.mode, ptt_guard_sec: ptt.guard, ptt_rx_gap: ptt.gap});
  pttSetUi();
  if (!d.ok) { setMsg('ptt-set-msg', {ok: local, warn: true, message: 'Saved on this phone, but the copy on the Pi failed: ' + (d.error || '?'), error: d.error}); return; }
  setMsg('ptt-set-msg', local ? {ok: true, message: 'Saved on this phone, with a copy on the Pi.'}
    : {ok: true, warn: true, message: 'This browser can\'t keep settings, so they were saved on the Pi only.'});
}

async function pttRestore() {
  if (talking) pttUp();
  const d = await pttFromPi(true);
  setMsg('ptt-set-msg', d && d.ok ? {ok: true, message: 'Restored from the Pi.'} : (d || {ok: false, error: 'Failed.'}));
}

async function loadFavs() {
  const d = await api('/api/favorites');
  if (!d.ok) return;
  favs = d.favs || [];
  favMax = d.max || 10;
  const sel = $('c-fav'), keep = sel.value;
  sel.innerHTML = '';
  favNets = d.nets || [];
  favNetLinks = d.net_links || {};
  favModes = d.modes || favModes;
  favs.forEach((f, i) => addOption(sel, String(i), f.label || (modeName(f.mode) + ' ' + favNum(f))));
  tnNets();
  if (keep && Number(keep) < favs.length) sel.value = keep;
  $('c-empty').classList.toggle('hidden', favs.length > 0);
  $('c-pick').classList.toggle('hidden', favs.length === 0);
  showSelected();
}

function showSelected() {
  const f = favs[Number($('c-fav').value)];
  $('c-mode').textContent = f ? modeName(f.mode) : '';
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
  const f = favs[Number(i)];
  const off = selectedLinked();
  netHide();
  if (!off) {
    const tune = f && (f.mode === 'M17' || DVS.includes(f.mode));
    await connectFlow({index: Number(i)}, (tune ? 'Tuning ' : 'Connecting to ') + (f ? f.label : 'the favorite') + '...',
      tune ? 'Tuning...' : 'Connecting... (checking the link for up to 15 s)');
    return;
  }
  $('c-connect').disabled = true;
  note('c-msg', '', 'Disconnecting...');
  try { setMsg('c-msg', await post('/api/disconnect', {index: Number(i)})); }
  finally { $('c-connect').disabled = false; }
  setTimeout(pollStatus, 1000);
}

let connMsgTimer = null, connBusy = false;
async function connectFlow(body, listenText, connectText, url, box) {
  url = url || '/api/connect';
  box = box || {msg: 'c-msg', btn: 'c-connect', ask: 'c-net'};
  $(box.btn).disabled = true;
  connBusy = true;
  note(box.msg, '', connectText);
  showTab('listen');
  if (connMsgTimer) { clearTimeout(connMsgTimer); connMsgTimer = null; }
  note('ptt-msg', '', listenText);
  let d = {};
  try { d = await post(url, body); }
  finally { $(box.btn).disabled = false; connBusy = false; }
  setMsg(box.msg, d);
  if (d.ok) {
    setMsg('ptt-msg', d);
    const shown = $('ptt-msg').textContent;
    connMsgTimer = setTimeout(() => { if ($('ptt-msg').textContent === shown) note('ptt-msg', '', ''); }, 8000);
  } else {
    if ($('ptt-msg').textContent === listenText) note('ptt-msg', '', '');
    if (tab === 'listen') showTab('connect');
    if (d.need_net) { netAsk = {url: url, body: body, box: box, label: listenText}; $(box.ask).classList.remove('hidden'); }
  }
  pollStatus();
  return d;
}

let netAsk = null;
function netHide() {
  $('c-net').classList.add('hidden');
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

const TN_MODES = ['DMR', 'STFU', 'YSF', 'P25', 'NXDN', 'DSTAR', 'M17'];
const TN_HINT = {DMR: 'TG number', STFU: 'TG, ID or name', YSF: 'Name, # or IP:port', P25: 'TG # or host',
  NXDN: 'TG # or host', DSTAR: 'REF001 C or callsign', M17: 'M17-USA A'};
const TN_NOUN = {STFU: 'talkgroups', YSF: 'reflectors', P25: 'talkgroups', NXDN: 'talkgroups', DSTAR: 'reflectors', M17: 'reflectors'};
const TN_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const TN_TYPED = {DMR: /^\d{1,8}$/, STFU: /^\d{1,8}$/, P25: /^\d{1,8}$/, NXDN: /^\d{1,8}$/,
  YSF: /^(\d{1,5}|[A-Za-z0-9.-]+:\d{1,5})$/,
  DSTAR: /^(?:(?:REF|XRF|DCS)\d{3}|[A-Z0-9]{1,3}\d[A-Z]{1,4})(?:\s+[A-Z])?$/i,
  M17: /^[A-Z0-9]+-[A-Z0-9-]{1,14}(?:\s+(?:[A-Z]|@ALL))?$/i};
const TN_SIZE = {gap: 8, h: 44, font: 15};
const tnLists = {};
let favNetLinks = {}, tnWin = null, tnTimer = 0, tnState = {};
try { tnState = JSON.parse(localStorage.getItem('nlTune') || '{}') || {}; } catch (e) {}

function tnRemember() {
  tnState = {mode: $('t-mode').value, net: $('t-net').value || tnState.net, mod: $('t-mod').value,
    find: $('t-find').value, pick: $('t-pick').value};
  try { localStorage.setItem('nlTune', JSON.stringify(tnState)); } catch (e) {}
}

function tnSizeLoad() {
  let v = {};
  try { v = JSON.parse(localStorage.getItem('nlTuneSize') || '{}') || {}; } catch (e) {}
  Object.keys(TN_SIZE).forEach((k) => {
    const n = Number(v[k]), r = $('tn-' + k);
    r.value = Number.isFinite(n) && n >= Number(r.min) && n <= Number(r.max) ? n : TN_SIZE[k];
  });
  tnSizeApply(false);
}

function tnSizeApply(save) {
  const v = {};
  Object.keys(TN_SIZE).forEach((k) => {
    v[k] = Number($('tn-' + k).value);
    document.documentElement.style.setProperty('--tn-' + k, v[k] + 'px');
    $('tn-' + k + '-v').textContent = v[k] + ' px';
  });
  if (save) { try { localStorage.setItem('nlTuneSize', JSON.stringify(v)); } catch (e) {} }
}

function tnSizeReset() {
  Object.keys(TN_SIZE).forEach((k) => { $('tn-' + k).value = TN_SIZE[k]; });
  tnSizeApply(false);
  try { localStorage.removeItem('nlTuneSize'); } catch (e) {}
}

function tnInit() {
  const m = $('t-mode');
  TN_MODES.forEach((x) => addOption(m, x, modeName(x)));
  m.value = TN_MODES.includes(tnState.mode) ? tnState.mode : 'DMR';
  $('t-find').value = tnState.find || '';
  $('t-mode').addEventListener('change', () => tnMode(false));
  $('t-net').addEventListener('change', () => { tnButtons(); tnRemember(); });
  $('t-mod').addEventListener('change', () => { tnButtons(); tnRemember(); });
  $('t-find').addEventListener('input', () => { tnButtons(); clearTimeout(tnTimer); tnTimer = setTimeout(() => { tnFill(); tnRemember(); }, 150); });
  $('t-find').addEventListener('keydown', (e) => { if (e.key === 'Enter') tnConnect(); });
  $('t-pick').addEventListener('change', () => { tnMods(); tnButtons(); tnRemember(); });
  $('t-go').addEventListener('click', tnConnect);
  $('t-lh').addEventListener('click', tnLast);
  $('t-save').addEventListener('click', tnSaveFav);
  $('t-off').addEventListener('click', tnOff);
  ['gap', 'h', 'font'].forEach((k) => $('tn-' + k).addEventListener('input', () => tnSizeApply(true)));
  $('tn-reset').addEventListener('click', tnSizeReset);
  tnSizeLoad();
  tnMode(true);
}

function tnNets() {
  const sel = $('t-net'), keep = sel.value || tnState.net;
  sel.innerHTML = '';
  if (!favNets.length) addOption(sel, '', 'No networks');
  favNets.forEach((n) => addOption(sel, n, n));
  if (keep && favNets.includes(keep)) sel.value = keep;
  if ($('t-mode').value === 'DMR') tnFill();
  else tnLoad($('t-mode').value);
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
  if (m !== 'DMR' && authed) tnLoad(m);
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
  if (!s || s.loading || !s.found) {
    addOption(sel, '', s && !s.loading ? 'No list' : 'Loading...');
    sel.disabled = true;
    $('t-list').textContent = !s || s.loading ? 'Loading the ' + modeName(m) + ' list...'
      : (s.err || 'No ' + modeName(m) + ' list was found on the Pi.') + ' You can still type one.';
    tnButtons();
    return;
  }
  const words = $('t-find').value.toLowerCase().split(/\s+/).filter(Boolean);
  const list = s.rows.filter((r) => words.every((w) => r.s.includes(w)));
  addOption(sel, '', list.length ? 'Select... (' + list.length.toLocaleString() + ')' : 'No matches');
  const frag = document.createDocumentFragment();
  list.forEach((r) => { const o = document.createElement('option'); o.value = r[0]; o.textContent = r[1]; frag.appendChild(o); });
  sel.appendChild(frag);
  sel.disabled = list.length === 0;
  if (keep && list.some((r) => r[0] === keep)) sel.value = keep;
  else if (list.length === 1) sel.value = list[0][0];
  const n = list.length, t = s.rows.length, noun = t === 1 ? TN_NOUN[m].slice(0, -1) : TN_NOUN[m];
  $('t-list').textContent = (n === t ? t.toLocaleString() + ' ' + noun
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
    if (m === 'YSF' || m === 'STFU') b.label = r[1];
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
  $('t-go').disabled = !ok || connBusy;
  $('t-save').disabled = !ok;
  $('t-lh').classList.toggle('lh-off', !tnLink());
  $('t-lh').setAttribute('aria-disabled', tnLink() ? 'false' : 'true');
}

function tnLast() {
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
  await connectFlow(b, 'Tuning ' + tnName(b) + '...', 'Tuning...', '/api/tune', {msg: 't-msg', btn: 't-go', ask: 't-ask'});
  tnButtons();
}

async function tnSaveFav() {
  const b = tnBody();
  if (!b) return;
  $('t-save').disabled = true;
  try { setMsg('t-msg', await post('/api/tune/save', b)); }
  finally { tnButtons(); }
  loadFavs();
}

async function tnOff() {
  $('t-off').disabled = true;
  note('t-msg', '', 'Disconnecting...');
  try { setMsg('t-msg', await post('/api/tune/disconnect', {})); }
  finally { $('t-off').disabled = false; }
  setTimeout(pollStatus, 1000);
}

async function loadNode() {
  const d = await api('/api/node');
  if (!d.ok) { note('nd-msg', 'err', d.error || 'Could not read rpt.conf.'); sum('rx', 'Could not read rpt.conf'); return; }
  $('nd-path').textContent = d.path;
  $('nd-line').textContent = d.hook_line;
  const sel = $('nd-select'), keep = sel.value;
  sel.innerHTML = '';
  const tb = $('nd-rows');
  tb.innerHTML = '';
  d.nodes.forEach((n) => {
    if (n.node === '1921') return;
    addOption(sel, n.node, n.node);
    const tr = document.createElement('tr');
    const a = document.createElement('td'); a.textContent = n.node;
    const b = document.createElement('td');
    if (n.ours) b.textContent = n.ours_port_ok ? 'Sends audio here' : 'Sends audio here, but to another UDP port (press Send again)';
    else if (n.outstream) b.textContent = 'Other outstreamcmd: ' + n.outstream;
    else if (n.inherited) b.textContent = 'Inherits outstreamcmd from [' + n.inherited.template + ']: ' + n.inherited.value;
    else b.textContent = 'Not sending';
    tr.appendChild(a); tr.appendChild(b); tb.appendChild(tr);
  });
  const hooked = d.nodes.find((n) => n.ours);
  sel.value = keep || (hooked ? hooked.node : (d.config_node || (d.nodes[0] ? d.nodes[0].node : '')));
  sum('rx', !hooked ? 'Not set up' : hooked.ours_port_ok ? 'Node ' + hooked.node + ' sends audio here' : 'Node ' + hooked.node + ': wrong UDP port');
}

async function nodeEnable() {
  const n = $('nd-select').value;
  if (!n) return;
  setMsg('nd-msg', await post('/api/node/enable', {node: n}));
  loadNode(); loadTx();
}

async function nodeDisable() {
  setMsg('nd-msg', await post('/api/node/disable', {}));
  loadNode();
}

async function astRestart(msgId) {
  if (!confirm('Restart Asterisk now? Every link on this node drops and reconnects.')) return;
  note(msgId, '', 'Restarting Asterisk...');
  setMsg(msgId, await post('/api/asterisk/restart', {}));
  setTimeout(loadTx, 4000);
}

async function loadTx() {
  const d = await api('/api/tx');
  if (!d.ok) { $('tx-state').textContent = d.error || 'Could not read rpt.conf.'; sum('tx', 'Could not read rpt.conf'); return; }
  $('tx-node').textContent = d.node;
  $('tx-rxch').textContent = d.rxchannel;
  $('tx-main').textContent = d.main || '(not set)';
  let s;
  if (d.error) s = d.error;
  else if (!d.defined) s = 'Not set up.';
  else if (!d.ours) s = 'rpt.conf has a [' + d.node + '] node that Node Talker did not add.';
  else if (!d.nodes_line) s = 'Its [nodes] line is missing or has the wrong IAX port: press Add node 1921 to fix it.';
  else if (!d.rx_ok) s = 'Set up, but its rxchannel is not ' + d.rxchannel + '.';
  else if (d.linked === null) s = 'Set up. Asterisk does not know it yet: restart Asterisk.';
  else s = d.linked ? 'Set up and linked to node ' + d.main + '.' : 'Set up; linking to node ' + d.main + ' (checked every 20 s).';
  $('tx-state').textContent = s;
  sum('tx', d.error ? 'Could not read rpt.conf' : !d.defined ? 'Not set up' : !(d.ours && d.nodes_line && d.rx_ok) ? 'Needs attention'
    : d.linked === null ? 'Restart Asterisk' : d.linked ? 'Set up and linked' : 'Set up, linking');
  $('tx-add').disabled = d.defined && d.nodes_line;
  $('tx-remove').disabled = !(d.defined && d.ours) && !d.nodes_line;
}

async function txEnable() { setMsg('tx-msg', await post('/api/tx/enable', {})); loadTx(); }
async function txDisable() {
  if (!confirm('Remove node 1921 from rpt.conf? Push-to-talk stops working until it is added again.')) return;
  setMsg('tx-msg', await post('/api/tx/disable', {})); loadTx();
}

function favCopy(f) { return {mode: f.mode, num: f.num, module: f.module, net: f.net, ip: f.ip, label: f.label}; }

async function loadFavEditor() {
  const d = await api('/api/favorites');
  if (!d.ok) return;
  favEdit = (d.favs || []).map(favCopy);
  favMax = d.max || 15;
  favNets = d.nets || [];
  favModes = d.modes || favModes;
  drawFavEditor();
  if (foldOpen('fav')) loadDashFavs();
}

async function loadDashFavs() {
  const dd = await api('/api/dash-favorites');
  dashFavs = dd.ok ? dd.favs : [];
  const sel = $('fe-dash');
  sel.innerHTML = '';
  addOption(sel, '', dashFavs.length ? 'From the Dashboard...' : 'No Dashboard favorites found');
  dashFavs.forEach((f, i) => addOption(sel, String(i), f.label || (modeName(f.mode) + ' ' + favNum(f))));
}

function drawFavEditor() {
  const box = $('fe-rows');
  box.innerHTML = '';
  favEdit.forEach((f, i) => {
    const row = document.createElement('div'); row.className = 'fav-row';
    const m = document.createElement('select'); m.setAttribute('aria-label', 'Network ' + (i + 1));
    favModes.forEach((v) => addOption(m, v, modeName(v)));
    const n = document.createElement('input'); n.value = f.mode === 'DMR' ? f.num : favNum(f);
    const net = document.createElement('select'); net.className = 'fav-net'; net.setAttribute('aria-label', 'DMR network ' + (i + 1));
    addOption(net, '', favNets.length ? 'DMR network...' : 'Add a DMR network on the Digital card first');
    favNets.forEach((v) => addOption(net, v, v));
    if (f.net && !favNets.includes(f.net)) addOption(net, f.net, f.net + ' (not in the list)');
    net.value = f.net || '';
    net.onchange = () => { f.net = net.value; };
    const numUi = () => {
      const k = FAV_HINT[f.mode] || FAV_HINT.ASL;
      n.inputMode = k[2]; n.placeholder = k[0];
      n.setAttribute('aria-label', k[1] + ' ' + (i + 1));
      net.classList.toggle('hidden', f.mode !== 'DMR');
    };
    m.value = f.mode; m.onchange = () => { f.mode = m.value; numUi(); };
    numUi();
    n.oninput = () => { f.num = n.value.trim(); f.module = ''; f.ip = ''; };
    const l = document.createElement('input'); l.value = f.label; l.maxLength = 40; l.placeholder = 'Name';
    l.setAttribute('aria-label', 'Name ' + (i + 1)); l.oninput = () => { f.label = l.value; };
    const x = document.createElement('button'); x.type = 'button'; x.textContent = '✕'; x.setAttribute('aria-label', 'Remove favorite ' + (i + 1));
    x.onclick = () => { favEdit.splice(i, 1); drawFavEditor(); };
    row.appendChild(m); row.appendChild(n); row.appendChild(l); row.appendChild(x); row.appendChild(net);
    box.appendChild(row);
  });
  $('fe-count').textContent = favEdit.length + ' / ' + favMax;
  $('fe-add').disabled = favEdit.length >= favMax;
  $('fe-dash-add').disabled = favEdit.length >= favMax;
}

function feAdd() { if (favEdit.length < favMax) { favEdit.push({mode: 'ASL', num: '', label: ''}); drawFavEditor(); } }
function feAddDash() {
  const i = $('fe-dash').value;
  if (i === '' || favEdit.length >= favMax) return;
  favEdit.push(favCopy(dashFavs[Number(i)]));
  drawFavEditor();
}
async function feSave() {
  const d = await post('/api/favorites', {favs: favEdit});
  setMsg('fe-msg', d);
  if (d.ok) { favEdit = d.favs.map(favCopy); drawFavEditor(); loadFavs(); }
}


const SVC_TXT = {active: 'running', inactive: 'stopped', failed: 'failed', missing: 'not installed', unknown: '?'};

async function loadDigital() {
  const d = await api('/api/digital');
  if (!d.ok) return;
  const nc = d.control === 'nc';
  $('dg-control').textContent = nc ? 'Node Controller is running: Node Talker tunes through it' : 'Solo: Node Talker tunes DVSwitch and M17 itself';
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
  $('dg-file').textContent = d.file || 'nodetalker_favorites.conf';
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
  if (d.ok) { loadDigital(); loadFavEditor(); loadFavs(); }
}

async function nwImport() {
  const d = await post('/api/dmr-networks/import', {});
  setMsg('nw-msg', d);
  if (d.ok) { loadDigital(); loadFavEditor(); }
}

async function dgSave() {
  const d = await post('/api/digital', {digital_bridge: $('dg-dbridge').value.trim(), m17_bridge: $('dg-mbridge').value.trim(), callsign: $('dg-call').value.trim()});
  setMsg('dg-msg', d);
  if (d.ok) loadDigital();
}

async function ffUpload() {
  const file = $('ff-up').files[0];
  $('ff-up').value = '';
  if (!file) return;
  if (file.size > 48 * 1024) { note('ff-msg', 'err', 'The file is too big for a favorites file.'); return; }
  const d = await post('/api/favorites-file', {text: await file.text()});
  setMsg('ff-msg', d);
  if (d.ok) { loadDigital(); loadFavEditor(); loadFavs(); }
}

const CFG_NUM = ['port', 'udp_port', 'max_listeners', 'tot_sec'], CFG_BOOL = ['public_listen', 'https', 'busy_lockout'];

async function loadConfig() {
  const d = await api('/api/config');
  if (!d.ok) return;
  CFG_NUM.forEach((k) => { $('cfg-' + k).value = d.config[k]; });
  CFG_BOOL.forEach((k) => { $('cfg-' + k).checked = !!d.config[k]; });
  sum('cfg', (d.config.https ? 'HTTPS' : 'HTTP') + ' · ' + d.config.max_listeners + ' listeners' + (d.config.public_listen ? ' · public' : '')
    + (ptt.mode === 'tap' ? ' · tap to talk ' + ptt.guard + ' s' : '') + (ptt.gap ? ' · 4 s wait' : ''));
  pttSetUi();
  $('tune-on').checked = !!d.config.tune_enabled;
  $('tune-tx').value = d.config.tx_gain_db;
  $('tune-rx').value = d.config.rx_gain_db;
  $('tune-jit').value = String(d.config.jitter_ms);
  $('tune-txbuf').value = String(d.config.tx_buffer_ms);
  $('rx-hpf').checked = !!d.config.rx_hpf;
  $('rx-agc').checked = !!d.config.rx_agc;
  $('rx-gate').value = String(d.config.rx_gate);
  tuneUi();
  $('tune-sysmon').classList.toggle('hidden', !sysmonPort);
  if (sysmonPort) $('tune-sysmon-link').href = 'http://' + location.hostname + ':' + sysmonPort + '/';
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
  if (d.ok) { publicListen = body.public_listen; loadNode(); }
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
  p.addEventListener('pointerdown', pttPress);
  p.addEventListener('pointerup', pttRelease);
  p.addEventListener('pointercancel', pttRelease);
  p.addEventListener('lostpointercapture', () => { if (ptt.mode !== 'tap') pttUp(); });
  p.addEventListener('contextmenu', (e) => e.preventDefault());
  p.addEventListener('keydown', (e) => pttKey(e, true));
  p.addEventListener('keyup', (e) => pttKey(e, false));
  $('ptt-save').addEventListener('click', pttSave);
  $('ptt-restore').addEventListener('click', pttRestore);
  $('ptt-guard').addEventListener('change', () => { $('ptt-guard-note').textContent = Number($('ptt-guard').value) > totSec ? 'The node\'s TX time-out is ' + fmtSecs(totSec) + ', so it stops then.' : ''; });
  window.addEventListener('blur', () => { if (!micPending) pttUp(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') pttUp(); else { openTalk(); pollStatus(); }
    specKick();
    wakeLockApply();
  });
  $('c-fav').addEventListener('change', showSelected);
  $('c-connect').addEventListener('click', favConnect);
  $('nd-enable').addEventListener('click', nodeEnable);
  $('nd-disable').addEventListener('click', nodeDisable);
  $('nd-restart').addEventListener('click', () => astRestart('nd-msg'));
  $('nd-refresh').addEventListener('click', loadNode);
  $('tx-add').addEventListener('click', txEnable);
  $('tx-remove').addEventListener('click', txDisable);
  $('tx-restart').addEventListener('click', () => astRestart('tx-msg'));
  $('fe-add').addEventListener('click', feAdd);
  $('fe-dash-add').addEventListener('click', feAddDash);
  $('fe-save').addEventListener('click', feSave);
  $('nw-add').addEventListener('click', nwAdd);
  ['c', 't'].forEach((p) => {
    $(p + '-net-add').addEventListener('click', () => netAnswer('add'));
    $(p + '-net-once').addEventListener('click', () => netAnswer('once'));
    $(p + '-net-no').addEventListener('click', () => netAnswer(''));
  });
  $('c-fav').addEventListener('change', netHide);
  tnInit();
  $('nw-save').addEventListener('click', nwSave);
  $('nw-import').addEventListener('click', nwImport);
  $('dg-save').addEventListener('click', dgSave);
  $('ff-up').addEventListener('change', ffUpload);
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
  $('node-test').addEventListener('click', nodeTest);
  try { window.name = 'asl_dvs_listen'; } catch (e) {}
  $('dash-link').addEventListener('click', (ev) => { ev.preventDefault(); openNamedTab($('dash-link').href, $('dash-link').dataset.win || 'asl_dvs_dash'); });
  $('sys-reboot').addEventListener('click', doReboot);
  $('sys-shutdown').addEventListener('click', doShutdown);
  setInterval(pollHostLinks, 30000);
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
  setInterval(gapTick, 100);
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
<meta name="theme-color" content="#111922">
<title>Node Talker</title>
<style>__CSS__</style>
</head>
<body>
<header><h1>Node Talker</h1><span class="ver">v__VERSION__</span><span class="sp"></span>
<a id="dash-link" class="pill hidden" href="#" aria-label="Open Node Controller">Node Controller</a>
<button id="login-open" class="pill hidden" type="button">Log In</button>
<button id="logout" class="pill hidden" type="button">Log Out</button></header>
<div id="login-screen">
<div id="login-card">
<h2>Node Talker Login</h2>
<form id="login-form">
<input type="password" id="pw" placeholder="Root password" autocomplete="current-password" aria-label="Root password" required>
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
<h2>Connect</h2>
<div id="c-empty" class="muted">No favorites yet. Add up to 15 on the Setup tab.</div>
<div id="c-pick">
<label for="c-fav">Favorite</label>
<select id="c-fav" style="width:100%;min-height:52px;margin-top:6px;font-size:15.2px"></select>
<div class="sel-card">
<div class="row" style="margin:0"><span class="tag" id="c-mode"></span><span class="big-num" id="c-num"></span></div>
<div class="muted" id="c-label"></div>
<button id="c-connect" class="btn primary big" type="button">Connect</button>
</div>
</div>
<div id="c-msg" class="msg"></div>
<div id="c-net" class="hidden">
<div class="row"><button id="c-net-add" class="btn primary" type="button">Add it to Node Controller and tune</button>
<button id="c-net-once" class="btn" type="button">Tune this once</button>
<button id="c-net-no" class="btn" type="button">Cancel</button></div>
</div>
</div>
<div class="card" id="cd-tune">
<h2>Tune</h2>
<div class="tn-bar">
<select id="t-mode" aria-label="Mode"></select>
<select id="t-net" aria-label="DMR network"></select>
<select id="t-mod" aria-label="Module"></select>
<input id="t-find" type="search" maxlength="40" aria-label="Search or type" autocomplete="off" autocapitalize="off" spellcheck="false">
<select id="t-pick" aria-label="Pick from the list"></select>
<button id="t-go" class="btn primary" type="button">Connect</button>
<button id="t-lh" class="btn-last lh-off" type="button" aria-label="Open Last Heard">LH</button>
<button id="t-save" class="btn" type="button" aria-label="Save to favorites">Save</button>
</div>
<div id="t-list" class="tn-msg"></div>
<div id="t-msg" class="msg"></div>
<div id="t-ask" class="hidden">
<div class="row"><button id="t-net-add" class="btn primary" type="button">Add it to Node Controller and tune</button>
<button id="t-net-once" class="btn" type="button">Tune this once</button>
<button id="t-net-no" class="btn" type="button">Cancel</button></div>
</div>
<div class="tn-foot"><span id="t-now" class="muted small"></span><button id="t-off" class="btn danger" type="button">Disconnect</button></div>
</div>
</section>

<section id="tab-listen" class="hidden">
<div class="lpanel">
<div class="row listen-row"><button id="listen-btn" class="btn primary big" type="button">Listen</button>
<svg class="vol-i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z"></path><path d="M16 9a4 4 0 0 1 0 6"></path></svg>
<input type="range" id="vol" min="0" max="200" value="100" aria-label="Volume"></div>
<div class="lstat"><span class="mono" id="st-node" title="Node">-</span>
<span id="st-feed-w"><span id="st-feed" class="dot"></span><span id="st-feed-t">feed</span></span>
<span title="Lit while the node is passing audio"><span id="st-active" class="dot"></span>RX</span>
<span id="s-tx-w" title="Lit while someone transmits from Node Talker"><span id="s-tx" class="dot"></span>TX</span>
<span id="st-listeners" title="Listeners">-</span><span id="chk-badge" class="chk hidden" title="An audio check is running (Setup tab)"></span></div>
<div class="spec" id="spec-wrap">
<div class="spec-box" id="spec-box"><canvas id="spec" aria-label="Audio spectrum: tap to switch between waterfall and bars"></canvas>
<span id="gap-cd" class="gap-cd hidden" aria-hidden="true"></span>
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
<div class="card fold" id="cd-rx">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-rx"><span class="fold-t">Receive</span><span class="fold-sum" id="sum-rx"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-rx">
<p class="muted small">Asterisk sends a node's audio here through one <code>outstreamcmd</code> line in <code id="nd-path">rpt.conf</code>.</p>
<table><thead><tr><th>Node</th><th>outstreamcmd</th></tr></thead><tbody id="nd-rows"></tbody></table>
<div class="row"><label>Node <select id="nd-select"></select></label>
<button id="nd-enable" class="btn primary" type="button">Send its audio here</button>
<button id="nd-disable" class="btn" type="button">Remove</button>
<button id="nd-restart" class="btn danger" type="button">Restart Asterisk</button>
<button id="nd-refresh" class="btn" type="button">Refresh</button></div>
<div id="nd-msg" class="msg"></div>
<table>
<tr><th>Line added</th><td><code id="nd-line">-</code></td></tr>
<tr><th>Feeder</th><td id="nd-feeder">-</td></tr>
<tr><th>UDP input</th><td id="nd-udp">-</td></tr>
</table>
</div>
</div>

<div class="card fold" id="cd-tx">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-tx"><span class="fold-t">Transmit: node <span id="tx-node">1921</span></span><span class="fold-sum" id="sum-tx"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-tx">
<p class="muted small">Push-to-talk sends your voice to private node 1921, which stays linked to the main node.
Node Talker adds its stanza and <code>[nodes]</code> line to rpt.conf (with a backup) and relinks it if it drops.</p>
<table>
<tr><th>State</th><td id="tx-state">-</td></tr>
<tr><th>Main node</th><td id="tx-main">-</td></tr>
<tr><th>rxchannel</th><td><code id="tx-rxch">-</code></td></tr>
</table>
<div class="row"><button id="tx-add" class="btn primary" type="button">Add node 1921</button>
<button id="tx-remove" class="btn" type="button">Remove</button>
<button id="tx-restart" class="btn danger" type="button">Restart Asterisk</button></div>
<div id="tx-msg" class="msg"></div>
</div>
</div>

<div class="card fold" id="cd-cfg">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-cfg"><span class="fold-t">Settings</span><span class="fold-sum" id="sum-cfg"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-cfg">
<div class="row"><label>Web port <input type="number" id="cfg-port" min="1024" max="65535"></label>
<label>UDP port <input type="number" id="cfg-udp_port" min="1024" max="65535"></label>
<label>Max listeners <input type="number" id="cfg-max_listeners" min="1" max="10"></label>
<label>TX time-out (s) <input type="number" id="cfg-tot_sec" min="30" max="600"></label></div>
<div class="row"><label><input type="checkbox" id="cfg-https"> HTTPS (needed for the microphone)</label></div>
<div class="row"><label><input type="checkbox" id="cfg-busy_lockout"> Don't transmit while the node is busy</label></div>
<div class="row"><label><input type="checkbox" id="cfg-public_listen"> Listen without logging in</label></div>
<p class="muted small">HTTPS uses a certificate made on this Pi, so the browser shows a warning: accept it to continue. Changing a port or HTTPS restarts Node Talker.</p>
<div class="row"><button id="cfg-save" class="btn primary" type="button">Save</button></div>
<div id="cfg-msg" class="msg"></div>
<h3 style="margin:14px 0 4px">Push-to-talk on this phone</h3>
<div class="row"><label><input type="radio" name="ptt-mode" id="ptt-hold" value="hold"> Hold to talk</label>
<label><input type="radio" name="ptt-mode" id="ptt-tap" value="tap"> Tap to talk, tap to stop</label></div>
<div class="row"><label>Guard timer <select id="ptt-guard"><option value="30">30 s</option><option value="60">60 s</option>
<option value="90">90 s</option><option value="120">120 s</option><option value="180">180 s</option></select></label></div>
<div class="row"><label><input type="checkbox" id="ptt-gap"> Wait 4 s after receive before talking</label></div>
<p class="muted small">With the wait on, push-to-talk is locked while the node receives and for 4 s after, counting
3 to 0 in the corner of the waterfall, so other stations get a chance to answer first.</p>
<p class="muted small">The guard timer stops a tap-to-talk (or headset) transmission: two short beeps 10 s before, then it
unkeys. It never runs past the node's TX time-out. <span id="ptt-guard-note"></span></p>
<p class="muted small" id="ptt-src"></p>
<div class="row"><button id="ptt-save" class="btn primary" type="button">Save on this phone</button>
<button id="ptt-restore" class="btn" type="button">Restore from the Pi</button></div>
<div id="ptt-set-msg" class="msg"></div>
<h3 style="margin:14px 0 4px">Tune card on this phone</h3>
<div class="row"><label>Gap <input type="range" id="tn-gap" min="2" max="20" step="1"> <span id="tn-gap-v" class="mono small"></span></label></div>
<div class="row"><label>Height <input type="range" id="tn-h" min="32" max="56" step="1"> <span id="tn-h-v" class="mono small"></span></label></div>
<div class="row"><label>Text <input type="range" id="tn-font" min="12" max="18" step="0.5"> <span id="tn-font-v" class="mono small"></span></label></div>
<div class="row"><button id="tn-reset" class="btn" type="button">Default spacing</button></div>
</div>
</div>

<div class="card fold" id="cd-fav">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-fav"><span class="fold-t">Favorites</span><span class="fold-sum" id="fe-count"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-fav">
<p class="muted small">The Connect tab offers only these. EchoLink numbers are the station's own number.
DMR: the talkgroup and its network (Digital card). STFU, YSF, P25 and NXDN: the talkgroup or reflector, as DVSwitch
tunes it. D-STAR: the reflector and module, for example <code>REF001 C</code>. M17: the reflector and module, for example
<code>M17-USA A</code> (or <code>@ALL</code> for every module). Connect sets the mode, tunes and links the bridge node;
while Node Controller runs, it does that instead.</p>
<div id="fe-rows"></div>
<div class="row"><button id="fe-add" class="btn" type="button">Add row</button>
<select id="fe-dash" aria-label="Dashboard favorites"></select><button id="fe-dash-add" class="btn" type="button">Add</button></div>
<div class="row"><button id="fe-save" class="btn primary" type="button">Save favorites</button></div>
<div id="fe-msg" class="msg"></div>
</div>
</div>

<div class="card fold" id="cd-dig">
<h2><button class="fold-btn" type="button" aria-expanded="false" aria-controls="cb-dig"><span class="fold-t">Digital</span><span class="fold-sum" id="sum-dig"></span><span class="fold-i" aria-hidden="true">▸</span></button></h2>
<div class="fold-body hidden" id="cb-dig">
<p class="muted small">Without Node Controller, Node Talker tunes DVSwitch and M17 itself: it sets the mode, tunes and
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
<div class="row"><button id="dg-save" class="btn primary" type="button">Save</button></div>
<div id="dg-msg" class="msg"></div>
<h3 style="margin:14px 0 4px">DMR networks</h3>
<p class="muted small">Each DMR favorite joins its network with <code>password@address:port</code> before it tunes the
talkgroup, as Node Controller does. Leave a password empty to keep the saved one.</p>
<div id="nw-rows"></div>
<div class="row"><button id="nw-add" class="btn" type="button">Add network</button>
<button id="nw-import" class="btn" type="button">Copy from Node Controller</button></div>
<div class="row"><button id="nw-save" class="btn primary" type="button">Save networks</button></div>
<div id="nw-msg" class="msg"></div>
<h3 style="margin:14px 0 4px">Favorites file</h3>
<p class="muted small"><code id="dg-file">nodetalker_favorites.conf</code> holds the favorites, the DMR networks and these
settings in Node Controller's format. It holds the DMR passwords too.</p>
<div class="row"><a id="ff-down" class="btn" href="/api/favorites-file" download="nodetalker_favorites.conf" style="display:inline-flex;align-items:center;text-decoration:none">Download</a>
<label class="btn" style="display:inline-flex;align-items:center">Upload<input type="file" id="ff-up" accept=".conf,text/plain" class="hidden"></label></div>
<div id="ff-msg" class="msg"></div>
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
not the node, the radio or DVSwitch.</p>
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
<p id="tune-sysmon" class="small hidden">SysMon is installed: for the node's own levels (radio, DVSwitch and USRP gains)
use <a id="tune-sysmon-link" href="#" target="_blank" rel="noopener">SysMon</a>.</p>
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
<div class="row"><button id="node-test" class="btn" type="button">Test through the node (transmits 4 s)</button></div>
<p class="muted small">Keys node 1921, records what the node sends out and plays it back. It goes out over the air and to linked nodes.</p>
<div id="node-test-msg" class="msg"></div>
<div class="rep hidden" id="rep-node">
<h3>Node test report</h3>
<div class="rep-strip"><canvas id="rep-node-tx"></canvas><span class="rep-lbl">sent (TX)</span></div>
<div class="rep-strip"><canvas id="rep-node-rx"></canvas><span class="rep-lbl">came back from the node (RX)</span><i class="rep-head"></i></div>
<div class="rep-n" id="rep-node-n"></div>
<div class="rep-v" id="rep-node-v"></div>
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


_POST_ACTIONS = {
    "/api/config": (config_update, ()),
    "/api/node/enable": (lambda b: hook_enable(b.get("node", "")), (ValueError, OSError)),
    "/api/node/disable": (lambda b: hook_disable(), (OSError,)),
    "/api/tx/enable": (lambda b: tx_enable(), (OSError,)),
    "/api/tx/disable": (lambda b: tx_disable(), (OSError,)),
    "/api/favorites": (lambda b: fav_save(b.get("favs")), ()),
    "/api/connect": (lambda b: fav_connect(b.get("index"), b.get("net_action")), ()),
    "/api/disconnect": (lambda b: fav_disconnect(b.get("index")), ()),
    "/api/tune": (tune_connect, ()),
    "/api/tune/save": (tune_save, ()),
    "/api/tune/disconnect": (lambda b: tune_disconnect(), ()),
    "/api/asterisk/restart": (lambda b: restart_asterisk(), ()),
    "/api/system/reboot": (lambda b: system_power("reboot"), ()),
    "/api/system/shutdown": (lambda b: system_power("shutdown"), ()),
    "/api/digital": (digital_save, ()),
    "/api/dmr-networks": (lambda b: nets_save(b.get("nets")), ()),
    "/api/dmr-networks/import": (lambda b: nets_import(), ()),
    "/api/favorites-file": (lambda b: fav_file_put(b.get("text")), ()),
}
_OPEN_GET_PATHS = ("/", "/index.html", "/api/health", "/api/whoami")
_PUBLIC_LISTEN_PATHS = ("/api/status", "/api/listen")


class Handler(BaseHTTPRequestHandler):
    server_version = "nodetalker/" + VERSION
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
            elif path == "/api/talk":
                self._talk()
            elif path == "/api/node":
                try:
                    d = rpt_state()
                except OSError as exc:
                    self._json(200, {"ok": False, "error": f"Could not read {RPT_CONF}: {exc}"})
                    return
                d.update(ok=True, config_node=_cfg_get("node") or main_node())
                self._json(200, d)
            elif path == "/api/tx":
                self._json(200, dict(tx_state(), ok=True))
            elif path == "/api/favorites":
                dash = dashboard_conf()
                self._json(200, {"ok": True, "max": FAV_MAX, "main": main_node(),
                                 "dash_node": dash["asl_node"] if port_open_cached(dash["port"]) else "",
                                 "modes": list(FAV_MODES), "nets": [n["name"] for n in nets_load()],
                                 "net_links": {n["name"]: n["url"] for n in nets_load()},
                                 "favs": [dict(f, target=fav_target(f)) for f in fav_load()]})
            elif path == "/api/tune-list":
                self._json(200, tune_list(query.get("mode", [""])[0]))
            elif path == "/api/digital":
                self._json(200, digital_info())
            elif path == "/api/favorites-file":
                self._send(200, fav_file_text().encode("utf-8"), "text/plain; charset=utf-8",
                           {"Content-Disposition": 'attachment; filename="nodetalker_favorites.conf"'})
            elif path == "/api/dash-favorites":
                self._json(200, {"ok": True, "favs": dashboard_conf()["favs"]})
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
    _solo_load()
    fav_doc()
    threading.Thread(target=HUB.pump_loop, name="pump", daemon=True).start()
    threading.Thread(target=udp_loop, args=(_cfg_get("udp_port"),), name="udp", daemon=True).start()
    threading.Thread(target=TALKER.pacer_loop, name="tx-pacer", daemon=True).start()
    threading.Thread(target=usrp_drain_loop, name="tx-drain", daemon=True).start()
    threading.Thread(target=link_keeper_loop, name="link-keeper", daemon=True).start()
    threading.Thread(target=guard_loop, name="link-guard", daemon=True).start()
    threading.Thread(target=_sd_watchdog_loop, args=(port, httpd.ssl_ctx is not None), name="watchdog", daemon=True).start()
    scheme = "https" if httpd.ssl_ctx is not None else "http"
    log_event(f"{APP_NAME} v{VERSION} on {scheme} port {port}, node audio on 127.0.0.1:{_cfg_get('udp_port')}/udp, "
              f"transmit to node {TX_NODE} on 127.0.0.1:{TX_USRP_SEND}/udp", "ok")
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
        try:
            if tx_state()["ready"]:
                tx_unlink("Node Talker stopped")
        except Exception as exc:
            log_event(f"Could not unlink node {TX_NODE} on stop: {exc}", "warn")
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


def _hook_node_now():
    try:
        _, stanzas = read_rpt()
    except OSError:
        return ""
    return next((s["name"] for s in stanzas if _is_ours(s["outstream"])), "")


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
    print(f"  [i] The uninstall {int(age)} s ago changed rpt.conf (an update); putting its Node Talker lines back")
    put_back = False
    try:
        node = _norm_node(rec.get("hook_node") or "")
        if node:
            r = hook_enable(node)
            print(f"  [+] Put back the audio feed from node {node}" if r.get("ok") else f"  [!] Audio feed from node {node}: {r.get('error')}")
            put_back = put_back or bool(r.get("changed"))
        if rec.get("tx") is True:
            r = tx_enable()
            print(f"  [+] Put back transmit node {TX_NODE}" if r.get("ok") else f"  [!] Transmit node {TX_NODE}: {r.get('error')}")
            put_back = put_back or bool(r.get("changed"))
    except OSError as exc:
        print(f"  [!] Could not put the rpt.conf lines back: {exc}")
        return
    if put_back:
        print("      Asterisk needs no restart, unless it was restarted while Node Talker was out.")


LEGACY_DATA = (("nodelisten.conf", "nodetalker.conf"), ("nodelisten_favorites.conf", "nodetalker_favorites.conf"),
               ("nodelisten_favorites.json", "nodetalker_favorites.json"), ("nodelisten_tuned.json", "nodetalker_tuned.json"),
               ("nodelisten_restore.json", "nodetalker_restore.json"), ("nodelisten_tls", "nodetalker_tls"),
               ("nodelisten_backups", "nodetalker_backups"))
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
    fav_doc()
    if not os.path.exists(FAV_CONF_PATH):
        _write_fav_doc([], [], {})
        print(f"  [+] Wrote {FAV_CONF_PATH}")
    _print_digital()
    legacy = _legacy_unit_real()
    aside = LEGACY_SERVICE_PATH + LEGACY_ASIDE
    if legacy:
        _systemctl("disable", "--now", LEGACY_SERVICE)
        os.replace(LEGACY_SERVICE_PATH, aside)
        print(f"  [-] Stopped Node Listen ({LEGACY_SERVICE}); its unit is kept as {aside} until {SERVICE_NAME} runs")
    run_path, bin_undo = INSTALL_BIN_PATH, None
    if legacy_bin_ours():
        if os.path.islink(LEGACY_BIN_PATH):
            bin_undo = ("link", os.readlink(LEGACY_BIN_PATH))
        elif os.path.lexists(LEGACY_BIN_PATH):
            os.replace(LEGACY_BIN_PATH, LEGACY_BIN_PATH + LEGACY_ASIDE)
            bin_undo = ("file", LEGACY_BIN_PATH + LEGACY_ASIDE)
        else:
            bin_undo = ("none", "")
        _replace_link(LEGACY_BIN_PATH, INSTALL_BIN_PATH)
        run_path = LEGACY_BIN_PATH
        print(f"  [+] Symlinked {LEGACY_BIN_PATH} -> {INSTALL_BIN_PATH} (rpt.conf and older tools use this name)")
    _restore_after_update()
    _atomic_write(SYSTEMD_SERVICE_PATH, service_content(run_path), 0o644)
    print(f"  [+] Wrote {SYSTEMD_SERVICE_PATH}")
    for args in (("daemon-reload",), ("enable", SERVICE_NAME)):
        r = _systemctl(*args)
        if r.returncode != 0:
            print(f"  [!] systemctl {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    r = _systemctl("restart", SERVICE_NAME)
    if r.returncode != 0:
        print(f"  [!] systemctl restart failed: {(r.stderr or r.stdout).strip()}")
        if bin_undo is not None:
            kind, what = bin_undo
            if kind == "link":
                _replace_link(LEGACY_BIN_PATH, what)
            elif kind == "file":
                os.replace(what, LEGACY_BIN_PATH)
            else:
                _remove_quiet(LEGACY_BIN_PATH)
        if legacy:
            _systemctl("disable", SERVICE_NAME)
            _remove_quiet(SYSTEMD_SERVICE_PATH)
            os.replace(aside, LEGACY_SERVICE_PATH)
            _systemctl("daemon-reload")
            r2 = _systemctl("enable", "--now", LEGACY_SERVICE)
            print(f"  [!] Put Node Listen back ({LEGACY_SERVICE}" + (" running)" if r2.returncode == 0 else ", but it did not start)"))
        else:
            print(f"      The previous version (if any) is still in {INSTALL_DIR}")
        sys.exit(1)
    print(f"  [+] {SERVICE_NAME} enabled and started (also answers to {LEGACY_SERVICE})")
    if bin_undo is not None and bin_undo[0] == "file":
        _remove_quiet(bin_undo[1])
    if legacy:
        _remove_quiet(aside)
    if os.path.isdir(LEGACY_INSTALL_DIR) and not os.path.islink(LEGACY_INSTALL_DIR):
        shutil.rmtree(LEGACY_INSTALL_DIR, ignore_errors=True)
        print(f"  [-] Removed Node Listen's {LEGACY_INSTALL_DIR}")
    for name in os.listdir(INSTALL_DIR):
        old = os.path.join(INSTALL_DIR, name)
        if old != dest and name.endswith(".py") and os.path.isfile(old) and not os.path.islink(old):
            os.remove(old)
            print(f"  [-] Removed the previous version {old}")
    print(f"Open http://<pi-address>:{_cfg_get('port')} , log in, and pick the node on the Node card.")


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
        hook_node = _hook_node_now()
        r = hook_disable()
        if r.get("changed"):
            print(f"  [-] Removed the outstreamcmd line from {RPT_CONF} (backup {r.get('backup')})")
        r2 = tx_disable()
        if r2.get("changed"):
            print(f"  [-] Removed transmit node {TX_NODE} from {RPT_CONF} (backup {r2.get('backup')})")
        if r.get("changed") or r2.get("changed"):
            print("      Restart Asterisk to apply: systemctl restart asterisk")
            rec = {"time": time.time(), "version": VERSION,
                   "hook_node": hook_node if r.get("changed") else "", "tx": bool(r2.get("changed"))}
            try:
                _atomic_write(RESTORE_PATH, json.dumps(rec) + "\n", mode=0o600)
                print(f"      An install within {RESTORE_MAX_AGE_SEC // 60} minutes (an update) puts these back.")
            except OSError as exc:
                print(f"  [!] Could not write {RESTORE_PATH}: {exc}")
    except OSError as exc:
        print(f"  [!] Could not check {RPT_CONF}: {exc}")
    _systemctl("disable", "--now", SERVICE_NAME)
    legacy_ours = (os.path.islink(LEGACY_BIN_PATH) and os.path.realpath(LEGACY_BIN_PATH).startswith(
        (os.path.realpath(INSTALL_DIR) + os.sep, os.path.realpath(INSTALL_BIN_PATH)))) or \
        (os.path.isfile(LEGACY_BIN_PATH) and not os.path.islink(LEGACY_BIN_PATH) and legacy_bin_ours())
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
    print(f"  Settings kept in {CONFIG_PATH}, {FAV_CONF_PATH} and {BACKUP_DIR}")


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{VERSION}: an ASL node's audio in the browser")
    parser.add_argument("--install", action="store_true", help="Install as a systemd service & start")
    parser.add_argument("--uninstall", action="store_true", help="Stop & remove the systemd service")
    parser.add_argument("--feed", type=int, metavar="UDP_PORT",
                        help="Read node audio on stdin and send it to 127.0.0.1:UDP_PORT (run by Asterisk's outstreamcmd)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION} ({DATE_STR})")
    args = parser.parse_args()
    if args.feed is not None:
        return run_feed(args.feed)
    if args.install:
        install_service()
        return 0
    if args.uninstall:
        uninstall_service()
        return 0
    return run_server()


if __name__ == "__main__":
    sys.exit(main())
