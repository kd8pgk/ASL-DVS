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
import json
import math
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

VERSION = "0.4.3"
DATE_STR = "2026-10-19"
APP_NAME = "Node Listen"

INSTALL_BIN_PATH = "/usr/local/bin/nodelisten.py"
INSTALL_DIR = "/usr/local/lib/asl_dvs/nodelisten"
SERVICE_NAME = "nodelisten.service"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/nodelisten.service"
_SYSTEMD_UNIT_DIR = "/etc/systemd/system"

CONFIG_DIR = os.environ.get("NODELISTEN_CONFIG_DIR", "/etc/asl_dvs")
CONFIG_PATH = os.path.join(CONFIG_DIR, "nodelisten.conf")
CONFIG_SECTION = "nodelisten"
BACKUP_DIR = os.path.join(CONFIG_DIR, "nodelisten_backups")
BACKUP_KEEP = 10
RESTORE_PATH = os.path.join(CONFIG_DIR, "nodelisten_restore.json")
RESTORE_MAX_AGE_SEC = 1800
RPT_CONF = os.environ.get("NODELISTEN_RPT_CONF", "/etc/asterisk/rpt.conf")
FEED_PYTHON = "/usr/bin/python3"
FEED_MARK = "nodelisten.py,--feed,"
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

SYSTEMD_SERVICE_CONTENT = f"""[Unit]
Description=Node Listen: ASL node audio in the browser
After=network.target asterisk.service

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
}


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _norm_port(value):
    v = int(str(value).strip())
    if not 1024 <= v <= 65535:
        raise ValueError("port must be 1024-65535")
    return v


def _norm_listeners(value):
    v = int(str(value).strip())
    if not 1 <= v <= 10:
        raise ValueError("max_listeners must be 1-10")
    return v


def _norm_node(value):
    v = str(value).strip()
    if v and not re.fullmatch(r"\d{1,7}", v):
        raise ValueError("node must be a node number")
    return v


def _norm_tot(value):
    v = int(str(value).strip())
    if not 30 <= v <= 600:
        raise ValueError("tot_sec must be 30-600")
    return v


def _norm_gain(value):
    v = int(round(float(str(value).strip())))
    if not -12 <= v <= 12:
        raise ValueError("gains must be -12 to +12 dB")
    return v


def _norm_txbuf(value):
    v = int(str(value).strip())
    if not 40 <= v <= 400:
        raise ValueError("tx_buffer_ms must be 40-400")
    return v


def _norm_jitter(value):
    v = int(str(value).strip())
    if not 100 <= v <= 1500:
        raise ValueError("jitter_ms must be 100-1500")
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
    if cp.has_section(CONFIG_SECTION):
        for key, norm in _NORMALIZERS.items():
            if cp.has_option(CONFIG_SECTION, key):
                try:
                    cfg[key] = norm(cp.get(CONFIG_SECTION, key))
                except ValueError as exc:
                    log_event(f"Config: bad {key} ({exc}); using {DEFAULT_CONFIG[key]}", "warn")
    with _config_lock:
        _config.clear()
        _config.update(cfg)
    return cfg


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
        try:
            os.remove(tmp)
        except OSError:
            pass
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
    lines = [f"[{CONFIG_SECTION}]"]
    for key in DEFAULT_CONFIG:
        val = cfg[key]
        lines.append(f"{key} = {'true' if val is True else 'false' if val is False else val}")
    _atomic_write(CONFIG_PATH, "\n".join(lines) + "\n", 0o644)


def config_update(body):
    with _config_lock:
        cfg = dict(_config)
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
    with _config_lock:
        old = dict(_config)
    try:
        save_config(cfg)
    except OSError as exc:
        return {"ok": False, "error": f"could not save {CONFIG_PATH}: {exc}"}
    with _config_lock:
        _config.update(cfg)
    restart = cfg["port"] != old["port"] or cfg["udp_port"] != old["udp_port"] or cfg["https"] != old["https"]
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
        msg += " Node Listen restarts to use the new setting."
        if not _schedule_restart():
            msg += " (Restart it by hand: systemctl restart nodelisten)"
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
    import importlib.util
    if importlib.util.find_spec("pam") is not None:
        return True
    stored = _read_shadow_hash(_AUTH_ACCOUNT)
    return bool(stored) and stored[0] not in ("!", "*")


_SESSION_COOKIE_NAME = "nodelisten_session"
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
            backoff = min(AUTH_LOCKOUT_BASE_SEC * (2 ** (rec["fails"] - AUTH_MAX_FAILURES)),
                          AUTH_LOCKOUT_MAX_SEC)
            rec["locked_until"] = time.time() + backoff
            log_event(f"Auth: {client_ip} locked out for {backoff}s after {rec['fails']} failed attempts", "warn")


def _record_auth_success(client_ip):
    with _auth_failures_lock:
        _auth_failures.pop(client_ip, None)


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
                          "--unit=nodelisten-selfrestart", "systemctl", "restart", SERVICE_NAME],
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


def ulaw_encode(frame):
    a = array.array("H")
    a.frombytes(frame)
    return bytes(map(ULAW_TABLE.__getitem__, a))


def frame_db(frame):
    a = array.array("h")
    a.frombytes(frame)
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


def apply_gain(frame, gain_db):
    if not gain_db:
        return frame
    g = 10.0 ** (gain_db / 20.0)
    a = array.array("h")
    a.frombytes(frame)
    for i, x in enumerate(a):
        v = int(x * g)
        a[i] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
    return a.tobytes()


def peak_db(frame):
    a = array.array("h")
    a.frombytes(frame)
    if not a:
        return -120.0
    pk = max(max(a), -min(a))
    return -120.0 if pk <= 0 else max(-120.0, 20.0 * math.log10(pk / 32768.0))


class _Listener:
    __slots__ = ("q", "closed", "ip", "since")

    def __init__(self, ip):
        self.q = deque(maxlen=LISTENER_QUEUE_MAX)
        self.closed = False
        self.ip = ip
        self.since = time.time()


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
        self.udp_error = ""

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

    def add_listener(self, ip):
        with self.lock:
            if len(self.listeners) >= _cfg_get("max_listeners"):
                return None
            lst = _Listener(ip)
            self.listeners.add(lst)
        log_event(f"Listener connected from {ip}")
        return lst

    def remove_listener(self, lst):
        with self.cond:
            lst.closed = True
            self.listeners.discard(lst)
            self.cond.notify_all()
        log_event(f"Listener from {lst.ip} left after {int(time.time() - lst.since)}s")

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
            enc = ulaw_encode(apply_gain(frame, tune_value("rx_gain_db"))) if frame is not None else ULAW_SILENCE
            with self.cond:
                for lst in self.listeners:
                    lst.q.append(enc)
                self.cond.notify_all()
        self.pump_beat = now

    def pump_loop(self):
        nxt = time.monotonic()
        last_rate = nxt
        last_packets = 0
        while True:
            nxt += FRAME_SEC
            delay = nxt - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.5:
                nxt = time.monotonic()
            try:
                self.tick()
            except Exception as exc:
                log_event(f"Audio pump error: {exc}", "err")
            t = time.monotonic()
            if t - last_rate >= 1.0:
                self.rate_window.append(self.packets - last_packets)
                last_packets = self.packets
                last_rate = t

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
            "audio_active": now - self.last_active < ACTIVE_HOLD_SEC,
            "listeners": n,
            "listener_list": listeners,
            "max_listeners": _cfg_get("max_listeners"),
            "udp_port": _cfg_get("udp_port"),
            "udp_error": self.udp_error,
        }


HUB = Hub()


def udp_loop(port):
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
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


def hook_line(port=None):
    p = _cfg_get("udp_port") if port is None else port
    return f"outstreamcmd = {FEED_PYTHON},{INSTALL_BIN_PATH},--feed,{p}"


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


def _is_ours(value):
    return bool(value) and FEED_MARK in value.replace(" ", "")


def rpt_state():
    with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    _, stanzas = parse_rpt(text)
    by_name = {s["name"]: s for s in stanzas}
    nodes = []
    for s in stanzas:
        if not re.fullmatch(r"\d+", s["name"]):
            continue
        inherited = None
        for t in s["templates"]:
            ts = by_name.get(t)
            if ts and ts["outstream"]:
                inherited = {"template": t, "value": ts["outstream"]}
        nodes.append({
            "node": s["name"],
            "outstream": s["outstream"],
            "ours": _is_ours(s["outstream"]),
            "ours_port_ok": _is_ours(s["outstream"]) and s["outstream"].replace(" ", "").endswith(f",{_cfg_get('udp_port')}"),
            "inherited": inherited,
        })
    return {"path": RPT_CONF, "nodes": nodes, "hook_line": hook_line()}


def _backup_rpt():
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, "rpt.conf." + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    shutil.copy2(RPT_CONF, dest)
    olds = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("rpt.conf."))
    for f in olds[:-BACKUP_KEEP]:
        try:
            os.remove(os.path.join(BACKUP_DIR, f))
        except OSError:
            pass
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


_rpt_lock = threading.Lock()


def hook_enable(node):
    node = _norm_node(node)
    if not node:
        return {"ok": False, "error": "Pick a node."}
    with _rpt_lock:
        with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        lines, stanzas = parse_rpt(text)
        target = next((s for s in stanzas if s["name"] == node), None)
        if target is None:
            return {"ok": False, "error": f"Node {node} is not in {RPT_CONF}."}
        if target["outstream"] and not _is_ours(target["outstream"]):
            return {"ok": False, "error": f"Node {node} already has outstreamcmd = {target['outstream']} "
                                           "(a Broadcastify feed?). A node takes one outstreamcmd; remove that line first."}
        want = hook_line()
        if (_is_ours(target["outstream"]) and target["outstream"].replace(" ", "") == want.split("=", 1)[1].replace(" ", "")
                and sum(1 for s in stanzas if _is_ours(s["outstream"])) == 1):
            return {"ok": True, "changed": False, "message": f"Node {node} already sends its audio here."}
        lines, _ = _remove_ours(lines, stanzas)
        lines, stanzas = parse_rpt("\n".join(lines))
        target = next(s for s in stanzas if s["name"] == node)
        at = target["header"] + 1
        lines[at:at] = [HOOK_NOTE, want]
        try:
            backup = _write_rpt(lines)
        except OSError as exc:
            return {"ok": False, "error": f"Could not write {RPT_CONF}: {exc}"}
    with _config_lock:
        _config["node"] = node
        cfg = dict(_config)
    try:
        save_config(cfg)
    except OSError:
        pass
    log_event(f"rpt.conf: node {node} now sends its audio to Node Listen (backup {backup})", "ok")
    return {"ok": True, "changed": True, "backup": backup,
            "message": f"Added to node {node}. Restart Asterisk for it to take effect. Backup: {backup}"}


def hook_disable():
    with _rpt_lock:
        with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        lines, stanzas = parse_rpt(text)
        lines, changed = _remove_ours(lines, stanzas)
        if not changed:
            return {"ok": True, "changed": False, "message": "No node sends its audio here."}
        try:
            backup = _write_rpt(lines)
        except OSError as exc:
            return {"ok": False, "error": f"Could not write {RPT_CONF}: {exc}"}
    log_event(f"rpt.conf: Node Listen line removed (backup {backup})", "ok")
    return {"ok": True, "changed": True, "backup": backup,
            "message": f"Removed. Restart Asterisk for it to take effect. Backup: {backup}"}


def restart_asterisk():
    try:
        r = subprocess.run(["systemctl", "restart", "asterisk"], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"systemctl failed: {exc}"}
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout).strip() or f"exit {r.returncode}"}
    log_event("Asterisk restarted from Node Listen", "ok")
    return {"ok": True, "message": "Asterisk restarted. Audio should arrive within a few seconds of the node hearing anything."}


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
            if b"nodelisten.py\0--feed\0" in cmd:
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
        tx = tx_state()
        tx.update(TALKER.state())
        st["tx"] = {k: tx.get(k) for k in ("node", "ready", "linked", "keyed", "who", "secs", "tot",
                                            "peak_db", "last_peak_db", "gaps", "last_gaps")}
    else:
        st.pop("listener_list", None)
        st.pop("udp_error", None)
    return st


AST_BIN = os.environ.get("NODELISTEN_ASTERISK", "asterisk")
DASH_CONF = os.environ.get("NODELISTEN_DASH_CONF", "/etc/asl_dvs/asl_dvs.conf")
FAV_PATH = os.path.join(CONFIG_DIR, "nodelisten_favorites.json")
FAV_MAX = 10
TLS_DIR = os.path.join(CONFIG_DIR, "nodelisten_tls")
TLS_CERT = os.path.join(TLS_DIR, "cert.pem")
TLS_KEY = os.path.join(TLS_DIR, "key.pem")
TX_NODE = "1921"
TX_USRP_SEND = 32018
TX_USRP_LISTEN = 34018
TX_NOTE = "; nodelisten: transmit node for the Node Listen page (remove it from that page)"
IAX_CONF = os.environ.get("NODELISTEN_IAX_CONF", "/etc/asterisk/iax.conf")
LOCAL_KEY_PATH = os.environ.get("NODELISTEN_LOCAL_KEY", "/etc/asl_dvs/local_api.key")
SYSMON_PORT = 9999
TX_BUSY_GRACE_SEC = 1.0
_TX_NODES_LINE_RE = re.compile(r"^\s*" + TX_NODE + r"\s*=\s*radio@127\.0\.0\.1(?::\d+)?/" + TX_NODE + r",NONE\s*$")
TX_QUEUE_MAX = 50
TX_DEADMAN_SEC = 1.0
USRP_HEADER = struct.Struct(">4s7i")
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
_CALL_TRIM = re.compile(r"[\x00-\x1f\x7f]")


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
                links.append({"node": parts[0], "dir": parts[3] if len(parts) > 3 else "",
                              "time": parts[4] if len(parts) > 4 else "",
                              "state": parts[5] if len(parts) > 5 else ""})
    with _lstats_lock:
        _lstats_cache.update(t=time.monotonic(), node=node, ok=ok, links=links)
    return ok, links


def _lstats_invalidate():
    with _lstats_lock:
        _lstats_cache["t"] = 0.0


def dashboard_conf():
    out = {"asl_node": "", "port": 8989, "bridges": set(), "favs": []}
    try:
        with open(DASH_CONF, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return out
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().upper()
            continue
        if section == "CONFIG" and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == "asl_node" and v.isdigit():
                out["asl_node"] = v
            elif k == "port" and v.isdigit():
                out["port"] = int(v)
            elif k in ("bridge_node", "bridge_nodes"):
                out["bridges"].update(x.strip() for x in v.split(",") if x.strip())
        elif section in ("ASL", "ECHO") and "|" in line and not line.lower().startswith("network_url"):
            name, _, num = line.rpartition("|")
            num = num.strip()
            if num.isdigit() and len(num) <= 7 and int(num) > 0 and len(out["favs"]) < 200:
                out["favs"].append({"mode": "ASL" if section == "ASL" else "EchoLink",
                                    "num": str(int(num)), "label": _CALL_TRIM.sub(" ", name.strip())[:40]})
    out["favs"] = [f for f in out["favs"] if not (f["mode"] == "ASL" and f["num"] in out["bridges"])]
    return out


def main_node():
    n = _cfg_get("node")
    return n or dashboard_conf()["asl_node"]


def _norm_fav(f):
    if not isinstance(f, dict):
        raise ValueError("bad favorite")
    mode = "EchoLink" if str(f.get("mode", "")).lower().startswith("echo") else "ASL"
    num = str(f.get("num", "")).strip()
    if not num.isdigit() or int(num) <= 0 or len(num) > (6 if mode == "EchoLink" else 7):
        raise ValueError(f"{mode} number must be digits ({'up to 6' if mode == 'EchoLink' else 'up to 7'})")
    if mode == "ASL" and num == TX_NODE:
        raise ValueError(f"Node {TX_NODE} is the transmit node, not a favorite")
    label = _CALL_TRIM.sub(" ", str(f.get("label", ""))).strip()[:40]
    return {"mode": mode, "num": str(int(num)), "label": label or f"{mode} {int(num)}"}


def fav_target(f):
    return f["num"] if f["mode"] == "ASL" else "3" + f["num"].zfill(6)


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
            return {"ok": False, "error": f"{f['mode']} {f['num']} is listed twice."}
        seen.add(key)
    try:
        _atomic_write(FAV_PATH, json.dumps(clean, indent=1) + "\n", 0o644)
    except OSError as exc:
        return {"ok": False, "error": f"Could not save: {exc}"}
    log_event(f"Favorites saved ({len(clean)})", "ok")
    return {"ok": True, "message": f"Saved {len(clean)} favorite(s).", "favs": clean}


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


def local_key():
    try:
        with open(LOCAL_KEY_PATH, "r", encoding="ascii") as fh:
            key = fh.read().strip()
        if len(key) >= 32:
            return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(LOCAL_KEY_PATH), exist_ok=True)
        fd = os.open(LOCAL_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(key + "\n")
        return key
    except FileExistsError:
        try:
            with open(LOCAL_KEY_PATH, "r", encoding="ascii") as fh:
                return fh.read().strip()
        except OSError:
            return ""
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
    try:
        d = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"ok": False, "error": f"Node Controller answered HTTP {resp.status}"}
    if not isinstance(d, dict):
        return {"ok": False, "error": f"Node Controller answered HTTP {resp.status}"}
    msg = str(d.get("message", ""))
    return {"ok": bool(d.get("ok")), "message": msg, "error": msg or f"Node Controller answered HTTP {resp.status}"}


def local_nodes():
    try:
        with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
            _, stanzas = parse_rpt(fh.read())
    except OSError:
        return []
    bridges = dashboard_conf()["bridges"]
    return [x["name"] for x in stanzas
            if re.fullmatch(r"\d+", x["name"]) and x["name"] != TX_NODE and x["name"] not in bridges]


def _from_node(from_node):
    main = main_node()
    n = str(from_node or "").strip() or main
    if not n:
        return None, "Set the node on the Setup tab first."
    if n != main and n not in local_nodes():
        return None, f"Node {n} is not a local node in rpt.conf."
    return n, ""


def fav_connect(index, from_node=None):
    favs = fav_load()
    try:
        f = favs[int(index)]
    except (ValueError, TypeError, IndexError):
        return {"ok": False, "error": "Pick a favorite."}
    node, err = _from_node(from_node)
    if not node:
        return {"ok": False, "error": err}
    if node == dashboard_conf()["asl_node"]:
        r = dash_call({"action": "connect", "mode": f["mode"], "node": f["num"], "name": f["label"]})
        if r is not None:
            _lstats_invalidate()
            if r["ok"]:
                log_event(f"Connect {f['mode']} {f['num']} through Node Controller", "ok")
                return {"ok": True, "message": f"{r['message'] or 'Connected'} (through Node Controller)"}
            return {"ok": False, "error": f"Node Controller: {r['error']}"}
    ok, out = ast_cli(f"rpt cmd {node} ilink 3 {fav_target(f)}")
    _lstats_invalidate()
    if not ok:
        return {"ok": False, "error": f"Asterisk refused: {out.strip()[:200] or 'no answer'}"}
    log_event(f"Connect {f['mode']} {f['num']} from node {node}", "ok")
    return {"ok": True, "message": f"Connecting node {node} to {f['mode']} {f['num']}..."}


def fav_disconnect(from_node=None):
    node, err = _from_node(from_node)
    if not node:
        return {"ok": False, "error": err}
    targets = {fav_target(f): f for f in fav_load()}
    _, links = rpt_links(node, max_age=0)
    hit = [l["node"] for l in links if l["node"] in targets]
    if not hit:
        return {"ok": True, "message": "No favorite is linked."}
    via = node == dashboard_conf()["asl_node"]
    for peer in hit:
        r = dash_call({"action": "disconnect", "node": peer}) if via else None
        if r is None:
            via = False
            ast_cli(f"rpt cmd {node} ilink 1 {peer}")
    _lstats_invalidate()
    log_event(f"Disconnect {', '.join(hit)} from node {node}" + (" through Node Controller" if via else ""), "ok")
    return {"ok": True, "message": f"Disconnected {', '.join(hit)}."}


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
        host = "nodelisten"
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
            try:
                os.remove(p)
            except OSError:
                pass
        return False
    os.chmod(key_tmp, 0o600)
    os.chmod(cert_tmp, 0o644)
    os.replace(key_tmp, TLS_KEY)
    os.replace(cert_tmp, TLS_CERT)
    log_event(f"Created a self-signed HTTPS certificate for {host} ({san})", "ok")
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
        host = f"{_lan_ips()[0]}:{_cfg_get('port')}"
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
        self.beat = time.monotonic()
        self.last_unkey = 0.0
        self.peak = -120.0
        self.last_peak = None
        self.gaps = 0
        self.last_gaps = None
        self.primed_once = False

    def _socket(self):
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return self.sock

    def _packet(self, payload, keyup):
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
        if (_cfg_get("busy_lockout") and HUB.snapshot()["audio_active"]
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
            self._packet(b"\x00" * FRAME_BYTES, False)
        log_event(f"TX: {who} unkeyed after {secs:.1f} s ({why})" + (f", {gaps} audio gap(s)" if gaps else ""),
                  "warn" if why in ("timeout", "deadman") or gaps else "ok")
        if owner is not None:
            owner.send_json({"ev": "unkeyed", "why": why, "secs": round(secs, 1)})

    def pacer_loop(self):
        nxt = time.monotonic()
        while True:
            nxt += FRAME_SEC
            delay = nxt - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.5:
                nxt = time.monotonic()
            self.beat = time.monotonic()
            try:
                self._tick()
            except Exception as exc:
                log_event(f"TX pacer error: {exc}", "err")

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
                    frame = b"\x00" * FRAME_BYTES
                if self.releasing and not self.q:
                    why = "release"
                elif now - self.last_rx > TX_DEADMAN_SEC:
                    why = "deadman"
            if why is None and self.sending:
                if self.q:
                    frame = self.q.popleft()
                elif self.releasing:
                    why = "release"
                elif now - self.last_rx > TX_DEADMAN_SEC:
                    why = "deadman"
                else:
                    self.gaps += 1
                    self.sending = False
                    frame = b"\x00" * FRAME_BYTES
        if why:
            self._unkey(why)
        elif frame is not None:
            self._packet(frame, True)


TALKER = Talker()


def usrp_drain_loop():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", TX_USRP_LISTEN))
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


def tx_state():
    out = {"node": TX_NODE, "main": main_node(), "defined": False, "ours": False, "nodes_line": False,
           "ready": False, "linked": None, "rxchannel": f"USRP/127.0.0.1:{TX_USRP_LISTEN}:{TX_USRP_SEND}"}
    try:
        with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        out["error"] = f"Could not read {RPT_CONF}: {exc}"
        return out
    lines, stanzas = parse_rpt(text)
    s, end = _tx_stanza(lines, stanzas)
    if s is not None:
        out["defined"] = True
        h = s["header"]
        out["ours"] = h > 0 and lines[h - 1].strip() == TX_NOTE
        body = "\n".join(lines[h:end]).replace(" ", "")
        out["rx_ok"] = f"rxchannel={out['rxchannel']}" in body
    want = tx_nodes_line().replace(" ", "")
    out["nodes_line"] = any(ln.strip().replace(" ", "") == want for ln in lines)
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
        with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        lines, stanzas = parse_rpt(text)
        s, _ = _tx_stanza(lines, stanzas)
        if s is not None:
            if s["header"] > 0 and lines[s["header"] - 1].strip() == TX_NOTE:
                want = tx_nodes_line()
                if any(ln.strip().replace(" ", "") == want.replace(" ", "") for ln in lines):
                    return {"ok": True, "changed": False, "message": f"Node {TX_NODE} is already set up."}
                new = [ln for ln in lines if not _TX_NODES_LINE_RE.match(ln)]
                _, st2 = parse_rpt("\n".join(new))
                nst = next((x for x in st2 if x["name"].lower() == "nodes"), None)
                if nst is not None:
                    new.insert(nst["header"] + 1, want)
                else:
                    new += ["[nodes]", want, ""]
                try:
                    backup = _write_rpt(new)
                except OSError as exc:
                    return {"ok": False, "error": f"Could not write {RPT_CONF}: {exc}"}
                log_event(f"rpt.conf: fixed the [nodes] line for node {TX_NODE}: {want} (backup {backup})", "ok")
                return {"ok": True, "changed": True, "backup": backup,
                        "message": f"Fixed the [nodes] line for node {TX_NODE} ({want}). Restart Asterisk. Backup: {backup}"}
            return {"ok": False, "error": f"rpt.conf already has a [{TX_NODE}] node that Node Listen didn't add. Remove it or pick another node."}
        main_st = next((x for x in stanzas if x["name"] == main), None)
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
        nodes_line = tx_nodes_line()
        new = [ln for ln in new if not _TX_NODES_LINE_RE.match(ln)]
        _, stanzas2 = parse_rpt("\n".join(new))
        nodes_st = next((x for x in stanzas2 if x["name"].lower() == "nodes"), None)
        if nodes_st is not None:
            new.insert(nodes_st["header"] + 1, nodes_line)
        else:
            new += ["[nodes]", nodes_line, ""]
        try:
            backup = _write_rpt(new)
        except OSError as exc:
            return {"ok": False, "error": f"Could not write {RPT_CONF}: {exc}"}
    log_event(f"rpt.conf: added transmit node {TX_NODE} for node {main} (backup {backup})", "ok")
    return {"ok": True, "changed": True, "backup": backup,
            "message": f"Added node {TX_NODE}. Restart Asterisk, then Node Listen links it to node {main}. Backup: {backup}"}


def tx_unlink(why):
    main = main_node()
    if not main:
        return
    ok, links = rpt_links(main, max_age=0)
    if ok and any(l["node"] == TX_NODE for l in links):
        ast_cli(f"rpt cmd {main} ilink 1 {TX_NODE}")
        _lstats_invalidate()
        log_event(f"Unlinked node {TX_NODE} from node {main} ({why})", "ok")


def tx_disable():
    tx_unlink("transmit node removed")
    with _rpt_lock:
        with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        lines, stanzas = parse_rpt(text)
        s, end = _tx_stanza(lines, stanzas)
        drop = set()
        if s is not None and s["header"] > 0 and lines[s["header"] - 1].strip() == TX_NOTE:
            drop.update(range(s["header"] - 1, end))
        for i, ln in enumerate(lines):
            if _TX_NODES_LINE_RE.match(ln):
                drop.add(i)
        if not drop:
            return {"ok": True, "changed": False, "message": f"Node Listen has no node {TX_NODE} in rpt.conf."}
        new = [ln for i, ln in enumerate(lines) if i not in drop]
        while len(new) > 1 and new[-1].strip() == "" and new[-2].strip() == "":
            new.pop()
        try:
            backup = _write_rpt(new)
        except OSError as exc:
            return {"ok": False, "error": f"Could not write {RPT_CONF}: {exc}"}
    log_event(f"rpt.conf: removed transmit node {TX_NODE} (backup {backup})", "ok")
    return {"ok": True, "changed": True, "backup": backup,
            "message": f"Removed node {TX_NODE}. Restart Asterisk for it to take effect. Backup: {backup}"}


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
            ok, out = ast_cli(f"rpt cmd {st['main']} ilink 3 {TX_NODE}")
            _lstats_invalidate()
            if last is not False:
                log_event(f"Node {TX_NODE} was not linked to node {st['main']}; linking it"
                          + ("" if ok else f" failed: {out.strip()[:120]}"), "warn")
            last = False
        except Exception as exc:
            log_event(f"Link keeper error: {exc}", "err")


_CSS = r""":root{--bg:#0e141b;--card:#161f29;--card2:#121a23;--line:#243140;--line2:#2a3846;--text:#e6edf3;--muted:#9fb0bf;
--soft:#c9d4de;--accent:#22c3a6;--accent-ink:#06231e;--accent-dim:#123a35;--amber:#f4c04e;--amber-bg:#3a2a07;--red:#ff8a8f;--red-line:#f2545b}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line);background:#111922;position:sticky;top:0;z-index:5}
header h1{font-size:18px;margin:0;white-space:nowrap}
header .ver{color:var(--muted);font-size:12px}
header .sp{flex:1}
.pill{display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 12px;border:1px solid var(--line2);border-radius:999px;color:var(--text);text-decoration:none;font-size:13px;background:transparent;cursor:pointer;font:inherit;font-size:13px}
.pill:hover{border-color:var(--accent)}
.pill{white-space:nowrap}
main{max-width:640px;margin:0 auto;padding:14px 16px 96px;overflow-wrap:anywhere}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:14px}
.card h2{font-size:15px;margin:0 0 10px}
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
th{color:var(--muted);font-weight:600}
code{background:var(--card2);border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:12px;word-break:break-all}
#log{max-height:260px;overflow:auto;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;background:var(--card2);border:1px solid var(--line);border-radius:8px;padding:8px}
#log .err{color:var(--red)}#log .warn{color:var(--amber)}#log .ok{color:var(--accent)}
.hidden{display:none !important}
nav.tabs{position:fixed;left:0;right:0;bottom:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));background:#111922;border-top:1px solid var(--line);padding:4px 6px calc(8px + env(safe-area-inset-bottom));z-index:5}
nav.tabs button{background:transparent;border:0;min-height:52px;color:var(--muted);font-size:13px;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}
nav.tabs button[aria-current=page]{color:var(--accent);font-weight:700}
nav.tabs svg{width:22px;height:22px}
.ptt-wrap{display:flex;flex-direction:column;align-items:center;gap:10px;padding:8px 0}
#ptt{width:180px;height:180px;border-radius:50%;border:3px solid var(--line2);background:#1b2633;color:var(--text);font-size:19px;font-weight:700;cursor:pointer;
touch-action:none;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px}
#ptt.ready{border-color:var(--accent)}
#ptt.talking{background:#4a1418;border-color:var(--red-line);box-shadow:0 0 0 12px rgba(242,84,91,.15)}
#ptt:disabled{opacity:.45;cursor:default}
#ptt-time{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:15px;color:var(--soft)}
.sel-card{display:flex;flex-direction:column;gap:6px;background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:10px}
.tag{display:inline-block;padding:2px 8px;border:1px solid var(--accent);border-radius:7px;color:#7fd8c6;font-size:12px;font-weight:700;font-family:ui-monospace,Menlo,Consolas,monospace}
.fav-row{display:grid;grid-template-columns:110px 96px minmax(0,1fr) 44px;gap:6px;margin:6px 0}
.fav-row input,.fav-row select{min-width:0;width:100%}
.fav-row button{min-height:40px;border-radius:8px;border:1px solid var(--line2);background:transparent;color:var(--red);cursor:pointer}
@media (max-width:420px){header{gap:6px;padding:10px 12px}header .ver{display:none}.pill{padding:0 10px}}
@media (max-width:480px){.fav-row{grid-template-columns:96px 84px minmax(0,1fr) 40px}#ptt{width:160px;height:160px}}
"""

_JS = r"""const $ = (id) => document.getElementById(id);
let authed = false, publicListen = false, dashPort = 8989, tab = 'listen', lastLogId = 0, lastStatus = null;
let ctx = null, gainNode = null, ctrl = null, playing = false, nextT = 0;
let mediaDest = null, wakeLock = null, nodeLabel = '';
let pend = new Float32Array(1600), pendN = 0, peakLocal = 0, retryTimer = null;
let favs = [], favEdit = [], dashFavs = [], favMax = 10;
let ws = null, wsReady = false, wsRetry = null, talking = false, keyed = false, keyedAt = 0, totSec = 120;
let micPending = false, jitterSec = 0.25, sysmonPort = null, dashNode = '';
let capCtx = null, micStream = null, capSrc = null, capNode = null, capSink = null, workletReady = false, preKey = [], talkTimer = null;
let rs = null, frameSink = null, testing = false, testBuf = [];
const MIC_DEFAULTS = {agc: true, ns: true, ec: false, gain: 0, hp: true};
let mic = Object.assign({}, MIC_DEFAULTS);
try { Object.assign(mic, JSON.parse(localStorage.getItem('nlMic') || '{}')); } catch (e) {}

function makeResampler(inRate) {
  const ratio = inRate / 8000, half = Math.ceil(8 * ratio), taps = 2 * half + 1, phases = 32;
  const fc = 3400 / inRate, kern = [];
  for (let p = 0; p <= phases; p++) {
    const k = new Float32Array(taps), off = p / phases;
    let sum = 0;
    for (let i = 0; i < taps; i++) {
      const t = i - half - off;
      const sinc = t === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * t) / (Math.PI * t);
      const w = Math.abs(t) > half ? 0 : 0.42 + 0.5 * Math.cos(Math.PI * t / half) + 0.08 * Math.cos(2 * Math.PI * t / half);
      k[i] = sinc * w; sum += k[i];
    }
    for (let i = 0; i < taps; i++) k[i] /= sum;
    kern.push(k);
  }
  return {ratio: ratio, half: half, taps: taps, phases: phases, kern: kern,
    buf: new Float32Array(half), pos: half, out: new Int16Array(160), n: 0, hpX: 0, hpY: 0, peak: 0};
}
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
  try { r = await fetch(url, opts); } catch (e) { return {ok: false, error: 'Node Listen is not answering.'}; }
  let d = {};
  try { d = await r.json(); } catch (e) { d = {ok: false, error: 'HTTP ' + r.status}; }
  if (r.status === 401 && url !== '/api/login' && authed) { authed = false; render(); }
  return d;
}

function setMsg(id, d) {
  const el = $(id);
  el.className = 'msg ' + (d.ok ? 'ok' : 'err');
  el.textContent = d.ok ? (d.message || 'Done.') : (d.error || 'Failed.');
}

function showTab(name) {
  if (!authed && name !== 'listen') name = 'listen';
  tab = name;
  ['status', 'connect', 'listen', 'setup'].forEach((t) => {
    $('tab-' + t).classList.toggle('hidden', t !== name || !(authed || (t === 'listen' && publicListen)));
    const b = $('nav-' + t);
    if (t === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  try { localStorage.setItem('nlTab', name); } catch (e) {}
  if (name === 'connect') loadFavs();
  if (name === 'setup') { loadNode(); loadTx(); loadConfig(); loadFavEditor(); }
  if (name === 'listen') openTalk();
}

function render() {
  const anyView = authed || publicListen;
  $('login-card').classList.toggle('hidden', authed);
  $('nav').classList.toggle('hidden', !authed);
  $('logout').classList.toggle('hidden', !authed);
  $('ptt-card').classList.toggle('hidden', !authed);
  if (!anyView) { ['status', 'connect', 'listen', 'setup'].forEach((t) => $('tab-' + t).classList.add('hidden')); return; }
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
  if (d.dash_port) dashPort = d.dash_port;
  $('dash-link').href = location.protocol.replace('https', 'http') + '//' + location.hostname + ':' + dashPort + '/';
  $('dash-link').classList.toggle('hidden', !d.dash_running);
  sysmonPort = d.sysmon_port || null;
  if (!d.backend) $('login-msg').textContent = 'No root password is set on this Pi, so login cannot work.';
  render();
}

async function login(ev) {
  ev.preventDefault();
  const d = await api('/api/login', {method: 'POST', body: {password: $('pw').value}});
  $('pw').value = '';
  if (d.ok) { authed = true; $('login-msg').textContent = ''; render(); }
  else { $('login-msg').className = 'msg err'; $('login-msg').textContent = d.error || 'Login failed.'; }
}

async function logout() {
  pttUp();
  if (ws) { try { ws.close(); } catch (e) {} }
  await api('/api/logout', {method: 'POST'});
  authed = false;
  stopListen();
  render();
}

function fmtDb(db) { return db <= -119 ? '-inf' : ((Math.round(db) || 0) + ' dBFS'); }
function dbPct(db) { return Math.max(0, Math.min(100, (db + 60) / 60 * 100)); }
function fmtSecs(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }

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
  $('s-node').textContent = d.node || '(not set)';
  if ((d.node || '') !== nodeLabel) { nodeLabel = d.node || ''; setMediaInfo(); }
  $('st-listeners').textContent = d.listeners + ' / ' + d.max_listeners;
  const feedCls = d.receiving ? 'on' : (d.packets ? 'warn' : 'err');
  const feedTxt = d.receiving ? ('receiving, ' + d.packets_per_sec + ' packets/s')
    : (d.last_rx_age != null ? 'no audio for ' + Math.round(d.last_rx_age) + ' s' : 'nothing received yet');
  ['st-feed', 's-feed'].forEach((id) => { $(id).className = 'dot ' + feedCls; });
  ['st-feed-t', 's-feed-t'].forEach((id) => { $(id).textContent = feedTxt; });
  ['st-active', 's-rx'].forEach((id) => { $(id).className = 'dot ' + (d.audio_active ? 'rx' : ''); });
  $('st-level').textContent = fmtDb(d.peak_db);
  if (d.jitter_ms) jitterSec = d.jitter_ms / 1000;
  if (!playing) $('meter-bar').style.width = dbPct(d.peak_db) + '%';
  if (!authed) return;
  const tx = d.tx || {};
  $('s-tx').className = 'dot ' + (tx.keyed ? 'tx' : '');
  $('s-tx-t').textContent = tx.keyed ? ('transmitting: ' + tx.who + ' ' + fmtSecs(tx.secs)) : (tx.ready ? 'idle' : 'transmit node not set up');
  totSec = tx.tot || totSec;
  $('tune-txpk').textContent = tx.keyed && tx.peak_db != null ? fmtDb(tx.peak_db) + ' (now)'
    : (tx.last_peak_db != null ? fmtDb(tx.last_peak_db) + ' (last transmission)' : 'no transmission yet');
  $('tune-rxpk').textContent = fmtDb(d.peak_db);
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
    [l.node + (l.node === tx.node ? ' (transmit)' : ''), f ? f.label : '', l.dir, l.time, l.state].forEach((v) => {
      const td = document.createElement('td'); td.textContent = v || ''; tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  $('s-nolinks').classList.toggle('hidden', links.length > 0);
  $('s-links-err').classList.toggle('hidden', d.links_ok !== false);
  const lf = linkedFavs(d);
  $('c-linked').textContent = lf.length ? lf.map((f) => f.mode + ' ' + f.num).join(', ') : 'No favorite linked';
  $('c-disc').disabled = !lf.length;
  $('nd-feeder').textContent = d.feeder_pids && d.feeder_pids.length ? 'running (pid ' + d.feeder_pids.join(', ') + ')' : 'not running';
  if (d.udp_port) $('nd-udp').textContent = d.udp_error ? d.udp_error : '127.0.0.1:' + d.udp_port + ' (listening)';
}

function flush() {
  if (!pendN || !ctx) return;
  const buf = ctx.createBuffer(1, pendN, 8000);
  buf.copyToChannel(pend.subarray(0, pendN), 0);
  pendN = 0;
  const now = ctx.currentTime;
  if (nextT < now + 0.05 || nextT > now + jitterSec + 1.25) nextT = now + jitterSec;
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(gainNode);
  src.start(nextT);
  nextT += buf.duration;
  const db = peakLocal > 0 ? 20 * Math.log10(peakLocal) : -120;
  $('meter-bar').style.width = dbPct(db) + '%';
  peakLocal = 0;
}

function push(bytes) {
  for (let i = 0; i < bytes.length; i++) {
    const v = UL[bytes[i]];
    pend[pendN++] = v;
    const a = v < 0 ? -v : v;
    if (a > peakLocal) peakLocal = a;
    if (pendN >= 800) flush();
  }
}

function listenVolume() { return talking ? 0 : $('vol').value / 100; }

async function startListen() {
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) { $('listen-msg').textContent = 'This browser cannot play live audio.'; return; }
  if (!ctx) {
    ctx = new AC();
    gainNode = ctx.createGain();
    gainNode.gain.value = listenVolume();
    const player = $('player');
    if (ctx.createMediaStreamDestination && player && 'srcObject' in player) {
      mediaDest = ctx.createMediaStreamDestination();
      gainNode.connect(mediaDest);
      player.srcObject = mediaDest.stream;
    } else {
      gainNode.connect(ctx.destination);
    }
  }
  await ctx.resume();
  if (mediaDest) {
    try { await $('player').play(); }
    catch (e) { mediaDest = null; gainNode.disconnect(); gainNode.connect(ctx.destination); }
  }
  playing = true;
  setMediaState();
  wakeLockApply();
  nextT = 0; pendN = 0;
  $('listen-btn').textContent = 'Stop';
  $('listen-btn').classList.remove('primary');
  $('listen-msg').className = 'msg';
  $('listen-msg').textContent = 'Connecting...';
  ctrl = new AbortController();
  try {
    const r = await fetch('/api/listen', {signal: ctrl.signal, cache: 'no-store'});
    if (!r.ok) {
      let e = 'HTTP ' + r.status;
      try { const d = await r.json(); e = d.error || e; } catch (x) {}
      throw new Error(e);
    }
    $('listen-msg').className = 'msg ok';
    $('listen-msg').textContent = 'Listening.';
    const rd = r.body.getReader();
    for (;;) {
      const {value, done} = await rd.read();
      if (done) break;
      push(value);
    }
    if (playing) throw new Error('stream ended');
  } catch (e) {
    if (!playing) return;
    $('listen-msg').className = 'msg warn';
    $('listen-msg').textContent = 'Disconnected (' + e.message + '). Retrying in 3 s...';
    retryTimer = setTimeout(() => { if (playing) startListen(); }, 3000);
  }
}

function stopListen() {
  playing = false;
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  if (ctrl) { ctrl.abort(); ctrl = null; }
  if (mediaDest) $('player').pause();
  if (ctx) ctx.suspend();
  setMediaState();
  wakeLockApply();
  $('listen-btn').textContent = 'Listen';
  $('listen-btn').classList.add('primary');
  $('listen-msg').className = 'msg';
  $('listen-msg').textContent = '';
}

function toggleListen() { if (playing) stopListen(); else startListen(); }

function setMediaInfo() {
  if (!('mediaSession' in navigator) || typeof MediaMetadata === 'undefined') return;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: nodeLabel ? 'Node ' + nodeLabel : 'ASL node',
    artist: 'Node Listen',
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
  on('play', () => { if (!playing) startListen(); });
  on('pause', () => { if (playing) stopListen(); });
  on('stop', () => { if (playing) stopListen(); });
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

function pttUi(state, text) {
  const b = $('ptt');
  b.classList.toggle('talking', state === 'talking' || state === 'keying');
  b.classList.toggle('ready', state === 'ready');
  b.disabled = state === 'off';
  $('ptt-label').textContent = state === 'talking' ? 'TALKING' : state === 'keying' ? 'Keying...' : 'Hold to talk';
  if (text !== undefined) {
    $('ptt-msg').className = 'msg ' + (state === 'error' ? 'err' : state === 'warn' ? 'warn' : '');
    $('ptt-msg').textContent = text;
  }
}

function openTalk() {
  if (!authed || tab !== 'listen' || document.visibilityState === 'hidden') return;
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
    if (m.ev === 'keyed') {
      keyed = true; keyedAt = performance.now(); totSec = m.tot || totSec;
      preKey.forEach((f) => ws.send(f)); preKey = [];
      pttUi('talking', '');
      if (navigator.vibrate) navigator.vibrate(30);
    } else if (m.ev === 'denied') {
      const why = {busy: 'The node is busy (someone is talking). Try again when it is quiet.',
        'in-use': 'Someone else is transmitting from Node Listen.',
        'not-ready': 'Node 1921 is not set up yet (Setup tab).',
        'not-linked': 'Node 1921 is not linked to the node yet. Restart Asterisk once after adding it; Node Listen relinks it within 20 s.'}[m.why] || ('Refused: ' + m.why);
      endTalk(); pttUi('ready', why); $('ptt-msg').className = 'msg warn';
    } else if (m.ev === 'unkeyed') {
      const was = talking;
      keyed = false; endTalk();
      const why = {timeout: 'Time-out: transmission stopped after ' + fmtSecs(m.secs) + '. Release and press again.',
        deadman: 'Audio stopped reaching the node, so it unkeyed.'}[m.why];
      pttUi('ready', why || (was ? '' : ''));
      if (why) $('ptt-msg').className = 'msg warn';
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
    let ph = Math.round((pos - base) * r.phases);
    const k = r.kern[ph];
    const start = base - r.half;
    let acc = 0;
    for (let i = 0; i < r.taps; i++) acc += merged[start + i] * k[i];
    let v = acc;
    if (mic.hp) { const y = hpA * (r.hpY + v - r.hpX); r.hpX = v; r.hpY = y; v = y * hpK; }
    const a = v < 0 ? -v : v;
    if (a > r.peak) r.peak = a;
    v = v > 1 ? 1 : v < -1 ? -1 : v;
    r.out[r.n++] = Math.round(v * 32767);
    if (r.n === 160) { if (frameSink) frameSink(r.out.slice(0).buffer); r.n = 0; }
    pos += r.ratio;
  }
  const keepFrom = Math.max(0, Math.floor(pos) - r.half);
  r.buf = merged.slice(keepFrom);
  r.pos = pos - keepFrom;
}

async function startMic(sink) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('This browser blocks the microphone here (use the https:// page).');
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!capCtx) capCtx = new AC();
  await capCtx.resume();
  const stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: !!mic.ec, noiseSuppression: !!mic.ns,
    autoGainControl: !!mic.agc, channelCount: 1}});
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

function saveMic() {
  mic = {agc: $('mic-agc').checked, ns: $('mic-ns').checked, ec: $('mic-ec').checked,
    hp: $('mic-hp').checked, gain: Number($('mic-gain').value)};
  try { localStorage.setItem('nlMic', JSON.stringify(mic)); } catch (e) {}
  $('mic-gain-v').textContent = (mic.gain > 0 ? '+' : '') + mic.gain + ' dB';
}

function loadMicUi() {
  $('mic-agc').checked = !!mic.agc; $('mic-ns').checked = !!mic.ns; $('mic-ec').checked = !!mic.ec;
  $('mic-hp').checked = !!mic.hp; $('mic-gain').value = mic.gain;
  $('mic-gain-v').textContent = (mic.gain > 0 ? '+' : '') + mic.gain + ' dB';
}

async function micTest() {
  if (testing || talking) return;
  testing = true; testBuf = [];
  $('mic-test').disabled = true;
  const AC = window.AudioContext || window.webkitAudioContext;
  const pc = new AC();
  try { pc.resume(); } catch (e) {}
  $('mic-test-msg').className = 'msg'; $('mic-test-msg').textContent = 'Recording 4 s: talk as you would on the air...';
  try {
    await startMic((buf) => testBuf.push(new Int16Array(buf)));
  } catch (e) {
    testing = false; $('mic-test').disabled = false; pc.close();
    $('mic-test-msg').className = 'msg err'; $('mic-test-msg').textContent = 'Microphone: ' + (e.message || e.name);
    return;
  }
  await new Promise((res) => setTimeout(res, 4000));
  const peak = rs ? rs.peak : 0;
  stopMic(); testing = false;
  const n = testBuf.reduce((a, b) => a + b.length, 0);
  if (!n) { pc.close(); $('mic-test').disabled = false; $('mic-test-msg').textContent = 'Nothing was recorded.'; return; }
  const ab = pc.createBuffer(1, n, 8000), ch = ab.getChannelData(0);
  let o = 0;
  testBuf.forEach((f) => { for (let i = 0; i < f.length; i++) ch[o++] = f[i] / 32768; });
  const src = pc.createBufferSource(); src.buffer = ab; src.connect(pc.destination); src.start();
  const db = peak > 0 ? 20 * Math.log10(peak) : -120;
  $('mic-test-msg').className = 'msg ' + (db > -1 ? 'warn' : db < -20 ? 'warn' : 'ok');
  $('mic-test-msg').textContent = 'Playing back what the node would get. Peak ' + fmtDb(db) +
    (db > -1 ? ': too hot, lower the mic gain.' : db < -20 ? ': quiet, raise the mic gain.' : ': good.');
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
  talking = false;
  preKey = [];
  stopMic();
  if (talkTimer) { clearInterval(talkTimer); talkTimer = null; }
  $('ptt-time').textContent = '';
  setTimeout(() => { if (gainNode && !talking) gainNode.gain.value = listenVolume(); }, 1000);
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
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({op: 'unkey'}));
    keyed = false; endTalk();
    pttUi('ready', 'Microphone: ' + (e.message || e.name)); $('ptt-msg').className = 'msg err';
  }
  micPending = false;
}

function pttUp(ev) {
  if (ev) ev.preventDefault();
  if (!talking) return;
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({op: 'unkey'}));
  keyed = false;
  endTalk();
  pttUi(wsReady ? 'ready' : 'off');
}

async function loadFavs() {
  const d = await api('/api/favorites');
  if (!d.ok) return;
  favs = d.favs || [];
  favMax = d.max || 10;
  dashNode = d.dash_node || '';
  const fsel = $('c-from'), fkeep = fsel.value;
  fsel.innerHTML = '';
  const nodes = (d.from_nodes || []).slice();
  if (d.main && nodes.indexOf(d.main) < 0) nodes.unshift(d.main);
  nodes.forEach((n) => {
    const o = document.createElement('option');
    o.value = n;
    o.textContent = n + (n === d.main ? ' (main node)' : '') + (n === dashNode ? ' · through Node Controller' : '');
    fsel.appendChild(o);
  });
  fsel.value = (fkeep && nodes.indexOf(fkeep) >= 0) ? fkeep : (d.main || nodes[0] || '');
  $('c-from-row').classList.toggle('hidden', nodes.length < 2 && !dashNode);
  const sel = $('c-fav'), keep = sel.value;
  sel.innerHTML = '';
  favs.forEach((f, i) => {
    const o = document.createElement('option');
    o.value = String(i);
    o.textContent = f.mode + ' ' + f.num + '  ·  ' + f.label;
    sel.appendChild(o);
  });
  if (keep && Number(keep) < favs.length) sel.value = keep;
  $('c-empty').classList.toggle('hidden', favs.length > 0);
  $('c-pick').classList.toggle('hidden', favs.length === 0);
  showSelected();
}

function showSelected() {
  const f = favs[Number($('c-fav').value)];
  $('c-mode').textContent = f ? f.mode : '';
  $('c-num').textContent = f ? f.num : '';
  $('c-label').textContent = f ? f.label : '';
}

async function favConnect() {
  const i = $('c-fav').value;
  if (i === '') return;
  $('c-msg').className = 'msg'; $('c-msg').textContent = 'Connecting...';
  setMsg('c-msg', await api('/api/connect', {method: 'POST', body: {index: Number(i), from: $('c-from').value}}));
  setTimeout(pollStatus, 1500);
}

async function favDisconnect() {
  setMsg('c-msg', await api('/api/disconnect', {method: 'POST', body: {from: $('c-from').value}}));
  setTimeout(pollStatus, 1000);
}

async function loadNode() {
  const d = await api('/api/node');
  if (!d.ok) { $('nd-msg').className = 'msg err'; $('nd-msg').textContent = d.error || 'Could not read rpt.conf.'; return; }
  $('nd-path').textContent = d.path;
  $('nd-line').textContent = d.hook_line;
  const sel = $('nd-select'), keep = sel.value;
  sel.innerHTML = '';
  const tb = $('nd-rows');
  tb.innerHTML = '';
  d.nodes.forEach((n) => {
    if (n.node === '1921') return;
    const o = document.createElement('option');
    o.value = o.textContent = n.node;
    sel.appendChild(o);
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
}

async function nodeEnable() {
  const n = $('nd-select').value;
  if (!n) return;
  setMsg('nd-msg', await api('/api/node/enable', {method: 'POST', body: {node: n}}));
  loadNode(); loadTx();
}

async function nodeDisable() {
  setMsg('nd-msg', await api('/api/node/disable', {method: 'POST', body: {}}));
  loadNode();
}

async function astRestart(msgId) {
  if (!confirm('Restart Asterisk now? Every link on this node drops and reconnects.')) return;
  $(msgId).className = 'msg'; $(msgId).textContent = 'Restarting Asterisk...';
  setMsg(msgId, await api('/api/asterisk/restart', {method: 'POST', body: {}}));
  setTimeout(loadTx, 4000);
}

async function loadTx() {
  const d = await api('/api/tx');
  if (!d.ok) { $('tx-state').textContent = d.error || 'Could not read rpt.conf.'; return; }
  $('tx-node').textContent = d.node;
  $('tx-rxch').textContent = d.rxchannel;
  $('tx-main').textContent = d.main || '(not set)';
  let s;
  if (d.error) s = d.error;
  else if (!d.defined) s = 'Not set up.';
  else if (!d.ours) s = 'rpt.conf has a [' + d.node + '] node that Node Listen did not add.';
  else if (!d.nodes_line) s = 'Its [nodes] line is missing or has the wrong IAX port: press Add node 1921 to fix it.';
  else if (!d.rx_ok) s = 'Set up, but its rxchannel is not ' + d.rxchannel + '.';
  else if (d.linked === null) s = 'Set up. Asterisk does not know it yet: restart Asterisk.';
  else s = d.linked ? 'Set up and linked to node ' + d.main + '.' : 'Set up; linking to node ' + d.main + ' (checked every 20 s).';
  $('tx-state').textContent = s;
  $('tx-add').disabled = d.defined && d.nodes_line;
  $('tx-remove').disabled = !(d.defined && d.ours) && !d.nodes_line;
}

async function txEnable() { setMsg('tx-msg', await api('/api/tx/enable', {method: 'POST', body: {}})); loadTx(); }
async function txDisable() {
  if (!confirm('Remove node 1921 from rpt.conf? Push-to-talk stops working until it is added again.')) return;
  setMsg('tx-msg', await api('/api/tx/disable', {method: 'POST', body: {}})); loadTx();
}

async function loadFavEditor() {
  const d = await api('/api/favorites');
  if (!d.ok) return;
  favEdit = (d.favs || []).map((f) => ({mode: f.mode, num: f.num, label: f.label}));
  favMax = d.max || 10;
  drawFavEditor();
  const dd = await api('/api/dash-favorites');
  dashFavs = dd.ok ? dd.favs : [];
  const sel = $('fe-dash');
  sel.innerHTML = '';
  const o0 = document.createElement('option'); o0.value = ''; o0.textContent = dashFavs.length ? 'From the Dashboard...' : 'No Dashboard favorites found';
  sel.appendChild(o0);
  dashFavs.forEach((f, i) => {
    const o = document.createElement('option'); o.value = String(i);
    o.textContent = f.mode + ' ' + f.num + ' · ' + f.label; sel.appendChild(o);
  });
}

function drawFavEditor() {
  const box = $('fe-rows');
  box.innerHTML = '';
  favEdit.forEach((f, i) => {
    const row = document.createElement('div'); row.className = 'fav-row';
    const m = document.createElement('select'); m.setAttribute('aria-label', 'Network ' + (i + 1));
    ['ASL', 'EchoLink'].forEach((v) => { const o = document.createElement('option'); o.value = o.textContent = v; m.appendChild(o); });
    m.value = f.mode; m.onchange = () => { f.mode = m.value; };
    const n = document.createElement('input'); n.inputMode = 'numeric'; n.value = f.num; n.placeholder = 'Number';
    n.setAttribute('aria-label', 'Node number ' + (i + 1)); n.oninput = () => { f.num = n.value.trim(); };
    const l = document.createElement('input'); l.value = f.label; l.maxLength = 40; l.placeholder = 'Name';
    l.setAttribute('aria-label', 'Name ' + (i + 1)); l.oninput = () => { f.label = l.value; };
    const x = document.createElement('button'); x.type = 'button'; x.textContent = '✕'; x.setAttribute('aria-label', 'Remove favorite ' + (i + 1));
    x.onclick = () => { favEdit.splice(i, 1); drawFavEditor(); };
    row.appendChild(m); row.appendChild(n); row.appendChild(l); row.appendChild(x);
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
  const f = dashFavs[Number(i)];
  favEdit.push({mode: f.mode, num: f.num, label: f.label});
  drawFavEditor();
}
async function feSave() {
  const d = await api('/api/favorites', {method: 'POST', body: {favs: favEdit}});
  setMsg('fe-msg', d);
  if (d.ok) { favEdit = d.favs.map((f) => ({mode: f.mode, num: f.num, label: f.label})); drawFavEditor(); loadFavs(); }
}

async function loadConfig() {
  const d = await api('/api/config');
  if (!d.ok) return;
  ['port', 'udp_port', 'max_listeners', 'tot_sec'].forEach((k) => { $('cfg-' + k).value = d.config[k]; });
  ['public_listen', 'https', 'busy_lockout'].forEach((k) => { $('cfg-' + k).checked = !!d.config[k]; });
  $('tune-on').checked = !!d.config.tune_enabled;
  $('tune-tx').value = d.config.tx_gain_db;
  $('tune-rx').value = d.config.rx_gain_db;
  $('tune-jit').value = String(d.config.jitter_ms);
  $('tune-txbuf').value = String(d.config.tx_buffer_ms);
  tuneUi();
  $('tune-sysmon').classList.toggle('hidden', !sysmonPort);
  if (sysmonPort) $('tune-sysmon-link').href = 'http://' + location.hostname + ':' + sysmonPort + '/';
}

function tuneUi() {
  const on = $('tune-on').checked;
  ['tune-tx', 'tune-rx', 'tune-jit', 'tune-txbuf'].forEach((id) => { $(id).disabled = !on; });
  const sgn = (v) => (v > 0 ? '+' : '') + v + ' dB';
  $('tune-tx-v').textContent = sgn(Number($('tune-tx').value));
  $('tune-rx-v').textContent = sgn(Number($('tune-rx').value));
  $('tune-body').classList.toggle('muted', !on);
}

async function saveTune() {
  const body = {tune_enabled: $('tune-on').checked, tx_gain_db: $('tune-tx').value,
    rx_gain_db: $('tune-rx').value, jitter_ms: $('tune-jit').value, tx_buffer_ms: $('tune-txbuf').value};
  const d = await api('/api/config', {method: 'POST', body: body});
  setMsg('tune-msg', d);
}

function tuneReset() {
  $('tune-tx').value = 0; $('tune-rx').value = 0; $('tune-jit').value = '250'; $('tune-txbuf').value = '120'; tuneUi();
}

async function saveConfig() {
  const body = {
    port: $('cfg-port').value, udp_port: $('cfg-udp_port').value, max_listeners: $('cfg-max_listeners').value,
    tot_sec: $('cfg-tot_sec').value, public_listen: $('cfg-public_listen').checked,
    https: $('cfg-https').checked, busy_lockout: $('cfg-busy_lockout').checked,
  };
  const d = await api('/api/config', {method: 'POST', body: body});
  setMsg('cfg-msg', d);
  if (d.ok) { publicListen = body.public_listen; loadNode(); }
}

async function pollLog() {
  if (!authed || tab !== 'setup') return;
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
  ['status', 'connect', 'listen', 'setup'].forEach((t) => $('nav-' + t).addEventListener('click', () => showTab(t)));
  $('listen-btn').addEventListener('click', toggleListen);
  $('vol').addEventListener('input', () => { if (gainNode) gainNode.gain.value = listenVolume(); });
  if ('wakeLock' in navigator) {
    $('awake-row').classList.remove('hidden');
    try { $('keep-awake').checked = localStorage.getItem('nlKeepAwake') === '1'; } catch (e) {}
  }
  $('keep-awake').addEventListener('change', () => {
    try { localStorage.setItem('nlKeepAwake', $('keep-awake').checked ? '1' : '0'); } catch (e) {}
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
    wakeLockApply();
  });
  $('c-fav').addEventListener('change', showSelected);
  $('c-connect').addEventListener('click', favConnect);
  $('c-disc').addEventListener('click', favDisconnect);
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
  $('cfg-save').addEventListener('click', saveConfig);
  ['tune-on', 'tune-tx', 'tune-rx'].forEach((id) => $(id).addEventListener('input', tuneUi));
  $('tune-save').addEventListener('click', saveTune);
  loadMicUi();
  ['mic-agc', 'mic-ns', 'mic-ec', 'mic-hp', 'mic-gain'].forEach((id) => $(id).addEventListener('input', saveMic));
  $('mic-test').addEventListener('click', micTest);
  try { window.name = 'asl_dvs_listen'; } catch (e) {}
  $('dash-link').addEventListener('click', (ev) => { ev.preventDefault(); openNamedTab($('dash-link').href, 'asl_dvs_dash'); });
  $('tune-reset').addEventListener('click', tuneReset);
  setupMediaSession();
  pttUi('off', '');
  whoami().then(() => { if (authed) loadFavs(); });
  setInterval(pollStatus, 1500);
  setInterval(pollLog, 3000);
});
"""

_ICON_STATUS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-7 4 14 3-7h4"></path></svg>'
_ICON_CONNECT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"></path><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"></path></svg>'
_ICON_LISTEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 14v-2a8 8 0 0 1 16 0v2"></path><rect x="3" y="14" width="4" height="6" rx="1.5"></rect><rect x="17" y="14" width="4" height="6" rx="1.5"></rect></svg>'
_ICON_SETUP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"></path><circle cx="16" cy="7" r="2"></circle><circle cx="10" cy="17" r="2"></circle></svg>'

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#111922">
<title>Node Listen</title>
<style>__CSS__</style>
</head>
<body>
<header><h1>Node Listen</h1><span class="ver">v__VERSION__</span><span class="sp"></span>
<a id="dash-link" class="pill" href="#" aria-label="Open Node Controller">Node Controller</a>
<button id="logout" class="pill hidden" type="button">Log out</button></header>
<main>
<section class="card" id="login-card">
<h2>Log in</h2>
<form id="login-form" class="row">
<input type="password" id="pw" placeholder="Pi root password" autocomplete="current-password" aria-label="Pi root password">
<button type="submit" class="btn primary">Log in</button>
</form>
<div id="login-msg" class="msg"></div>
</section>

<section id="tab-status" class="hidden">
<div class="card">
<div class="row" style="justify-content:space-between;margin:0"><span class="muted small">Node</span><span class="big-num" id="s-node">-</span></div>
<table>
<tr><th>Receive</th><td><span id="s-rx" class="dot"></span>lit while the node is passing audio</td></tr>
<tr><th>Transmit</th><td><span id="s-tx" class="dot"></span><span id="s-tx-t">-</span></td></tr>
<tr><th>Feed</th><td><span id="s-feed" class="dot"></span><span id="s-feed-t">-</span></td></tr>
</table>
</div>
<div class="card">
<h2>Links</h2>
<table><thead><tr><th>Node</th><th>Name</th><th>Dir</th><th>Time</th><th>State</th></tr></thead><tbody id="s-links"></tbody></table>
<div id="s-nolinks" class="muted small" style="margin-top:8px">No links.</div>
<div id="s-links-err" class="msg warn hidden">Could not ask Asterisk for the links (rpt lstats).</div>
</div>
</section>

<section id="tab-connect" class="hidden">
<div class="card">
<h2>Connect</h2>
<div id="c-empty" class="muted">No favorites yet. Add up to 10 on the Setup tab.</div>
<div id="c-from-row" class="row hidden"><label for="c-from">Connect from</label>
<select id="c-from" style="flex:1;min-height:44px"></select></div>
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
<div class="card">
<div class="row" style="justify-content:space-between;margin:0">
<div><div class="muted small">Linked now</div><div class="mono" id="c-linked" style="font-weight:700">-</div></div>
<button id="c-disc" class="btn danger" type="button" disabled>Disconnect</button>
</div>
<div class="muted small" style="margin-top:6px">Disconnect drops linked favorites only; other links stay.</div>
</div>
</section>

<section id="tab-listen" class="hidden">
<div class="card">
<div class="row"><button id="listen-btn" class="btn primary big" type="button">Listen</button>
<label>Volume <input type="range" id="vol" min="0" max="200" value="100"></label></div>
<div class="row"><div class="meter"><i id="meter-bar"></i></div><span id="st-level" class="muted small mono">-inf</span></div>
<div class="row hidden" id="awake-row"><label><input type="checkbox" id="keep-awake"> Keep the screen on while listening or talking</label></div>
<audio id="player" playsinline class="hidden"></audio>
<div id="listen-msg" class="msg"></div>
<table>
<tr><th>Node</th><td id="st-node">-</td></tr>
<tr><th>Feed</th><td><span id="st-feed" class="dot"></span><span id="st-feed-t">-</span></td></tr>
<tr><th>Audio</th><td><span id="st-active" class="dot"></span>lit while the node is passing audio</td></tr>
<tr><th>Listeners</th><td id="st-listeners">-</td></tr>
</table>
</div>
<div class="card" id="ptt-card">
<div class="ptt-wrap">
<button id="ptt" type="button" disabled aria-label="Push to talk: hold to transmit"><span id="ptt-label">Hold to talk</span><span id="ptt-time"></span></button>
<div id="ptt-info" class="muted small" style="text-align:center">-</div>
<div id="ptt-msg" class="msg" style="text-align:center"></div>
</div>
</div>
</section>

<section id="tab-setup" class="hidden">
<div class="card">
<h2>Receive: node audio to this page</h2>
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

<div class="card">
<h2>Transmit: node <span id="tx-node">1921</span></h2>
<p class="muted small">Push-to-talk sends your voice to private node 1921, which stays linked to the main node.
Node Listen adds its stanza and <code>[nodes]</code> line to rpt.conf (with a backup) and relinks it if it drops.</p>
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

<div class="card">
<h2>Favorites <span class="muted small" id="fe-count"></span></h2>
<p class="muted small">The Connect tab offers only these. EchoLink numbers are the station's own number.</p>
<div id="fe-rows"></div>
<div class="row"><button id="fe-add" class="btn" type="button">Add row</button>
<select id="fe-dash" aria-label="Dashboard favorites"></select><button id="fe-dash-add" class="btn" type="button">Add</button></div>
<div class="row"><button id="fe-save" class="btn primary" type="button">Save favorites</button></div>
<div id="fe-msg" class="msg"></div>
</div>

<div class="card">
<h2>Tune: audio levels</h2>
<div class="row"><label><input type="checkbox" id="tune-on"> Adjust audio levels here</label></div>
<p class="muted small">Off: Node Listen passes audio through unchanged. These change only this page's path,
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
<h2 style="margin-top:14px">This device's microphone</h2>
<p class="muted small">Saved in this browser only; each phone keeps its own. Browsers can't change the phone's own
mic volume, so the gain here is applied in the page.</p>
<div class="row"><label><input type="checkbox" id="mic-agc"> Automatic gain (the browser levels the mic)</label></div>
<div class="row"><label><input type="checkbox" id="mic-ns"> Noise suppression</label></div>
<div class="row"><label><input type="checkbox" id="mic-ec"> Echo cancellation (rarely needed: listen audio is muted while you talk)</label></div>
<div class="row"><label><input type="checkbox" id="mic-hp"> Voice filter (cuts rumble below about 250 Hz)</label></div>
<div class="row"><label for="mic-gain" style="min-width:130px">Mic gain</label>
<input type="range" id="mic-gain" min="-12" max="24" step="1" style="flex:1"><span id="mic-gain-v" class="mono small">0 dB</span></div>
<p class="muted small">With automatic gain on, the browser undoes most of the mic gain; turn it off for a fixed level.</p>
<div class="row"><button id="mic-test" class="btn" type="button">Test mic (4 s, plays back)</button></div>
<div id="mic-test-msg" class="msg"></div>
<p id="tune-sysmon" class="small hidden">SysMon is installed: for the node's own levels (radio, DVSwitch and USRP gains)
use <a id="tune-sysmon-link" href="#" target="_blank" rel="noopener">SysMon</a>.</p>
<div class="row"><button id="tune-save" class="btn primary" type="button">Save</button>
<button id="tune-reset" class="btn" type="button">Reset to 0 dB</button></div>
<div id="tune-msg" class="msg"></div>
</div>

<div class="card">
<h2>Settings</h2>
<div class="row"><label>Web port <input type="number" id="cfg-port" min="1024" max="65535"></label>
<label>UDP port <input type="number" id="cfg-udp_port" min="1024" max="65535"></label>
<label>Max listeners <input type="number" id="cfg-max_listeners" min="1" max="10"></label>
<label>TX time-out (s) <input type="number" id="cfg-tot_sec" min="30" max="600"></label></div>
<div class="row"><label><input type="checkbox" id="cfg-https"> HTTPS (needed for the microphone)</label></div>
<div class="row"><label><input type="checkbox" id="cfg-busy_lockout"> Don't transmit while the node is busy</label></div>
<div class="row"><label><input type="checkbox" id="cfg-public_listen"> Listen without logging in</label></div>
<p class="muted small">HTTPS uses a certificate made on this Pi, so the browser shows a warning: accept it to continue. Changing a port or HTTPS restarts Node Listen.</p>
<div class="row"><button id="cfg-save" class="btn primary" type="button">Save</button></div>
<div id="cfg-msg" class="msg"></div>
</div>

<div class="card">
<h2>Log</h2>
<div id="log"></div>
</div>
</section>
</main>
<nav class="tabs hidden" id="nav" aria-label="Main">
<button id="nav-status" type="button">__ICON_STATUS__Status</button>
<button id="nav-connect" type="button">__ICON_CONNECT__Connect</button>
<button id="nav-listen" type="button">__ICON_LISTEN__Listen</button>
<button id="nav-setup" type="button">__ICON_SETUP__Setup</button>
</nav>
<script>__JS__</script>
</body>
</html>
"""


def render_page():
    return (_HTML_TEMPLATE.replace("__CSS__", _CSS).replace("__JS__", _JS)
            .replace("__ICON_STATUS__", _ICON_STATUS).replace("__ICON_CONNECT__", _ICON_CONNECT)
            .replace("__ICON_LISTEN__", _ICON_LISTEN).replace("__ICON_SETUP__", _ICON_SETUP)
            .replace("__VERSION__", VERSION)).encode("utf-8")


_OPEN_GET_PATHS = ("/", "/index.html", "/api/health", "/api/whoami")
_PUBLIC_LISTEN_PATHS = ("/api/status", "/api/listen")


class Handler(BaseHTTPRequestHandler):
    server_version = "nodelisten/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 60

    def log_message(self, fmt, *args):
        pass

    def _ip(self):
        return self.client_address[0] if self.client_address else "?"

    def _token(self):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == _SESSION_COOKIE_NAME:
                return v
        return ""

    def _authed(self):
        return _check_session(self._token())

    def _send(self, code, body, ctype, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
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
        return c + "; Secure" if self.server.ssl_ctx is not None else c

    def do_GET(self):
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
                self._json(200, {"ok": True, "authed": authed, "public_listen": _cfg_get("public_listen"),
                                 "backend": _root_backend_available(), "dash_port": dport,
                                 "dash_running": port_open_cached(dport),
                                 "sysmon_port": SYSMON_PORT if authed and port_open_cached(SYSMON_PORT) else None,
                                 "https": self.server.ssl_ctx is not None})
            elif path == "/api/status":
                d = build_status(authed)
                d["ok"] = True
                self._json(200, d)
            elif path == "/api/listen":
                self._stream()
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
                d = tx_state()
                d["ok"] = True
                self._json(200, d)
            elif path == "/api/favorites":
                self._json(200, {"ok": True, "max": FAV_MAX, "main": main_node(), "from_nodes": local_nodes(),
                                 "dash_node": dashboard_conf()["asl_node"] if port_open_cached(dashboard_conf()["port"]) else "",
                                 "favs": [dict(f, target=fav_target(f)) for f in fav_load()]})
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

    def _stream(self):
        lst = HUB.add_listener(self._ip())
        if lst is None:
            self.close_connection = True
            self._json(503, {"ok": False, "error": f"All {_cfg_get('max_listeners')} listener slots are in use."})
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Audio-Format", "mulaw; rate=8000; channels=1")
            self.send_header("Connection", "close")
            self.end_headers()
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
            st = tx_state()
            ws.send_json({"ev": "hello", "ready": st["ready"], "node": TX_NODE, "tot": _cfg_get("tot_sec")})
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
            wait = _auth_lockout_remaining(ip)
            if wait > 0:
                self._json(429, {"ok": False, "error": f"Too many attempts. Try again in {int(wait) + 1} s."})
                return
            if _verify_root_password(str(body.get("password", ""))):
                _record_auth_success(ip)
                token = _issue_session()
                log_event(f"Login from {ip}", "ok")
                self._json(200, {"ok": True}, {"Set-Cookie": self._cookie(token, _SESSION_TTL_SEC)})
            else:
                _record_auth_failure(ip)
                log_event(f"Failed login from {ip}", "warn")
                self._json(401, {"ok": False, "error": "Wrong password."})
            return
        if path == "/api/logout":
            _revoke_session(self._token())
            self._json(200, {"ok": True}, {"Set-Cookie": self._cookie("", 0)})
            return
        if not self._authed():
            self._json(401, {"ok": False, "error": "Log in first."})
            return
        try:
            if path == "/api/config":
                self._json(200, config_update(body))
            elif path == "/api/node/enable":
                try:
                    self._json(200, hook_enable(body.get("node", "")))
                except (ValueError, OSError) as exc:
                    self._json(200, {"ok": False, "error": str(exc)})
            elif path == "/api/node/disable":
                try:
                    self._json(200, hook_disable())
                except OSError as exc:
                    self._json(200, {"ok": False, "error": str(exc)})
            elif path == "/api/tx/enable":
                try:
                    self._json(200, tx_enable())
                except OSError as exc:
                    self._json(200, {"ok": False, "error": str(exc)})
            elif path == "/api/tx/disable":
                try:
                    self._json(200, tx_disable())
                except OSError as exc:
                    self._json(200, {"ok": False, "error": str(exc)})
            elif path == "/api/favorites":
                self._json(200, fav_save(body.get("favs")))
            elif path == "/api/connect":
                self._json(200, fav_connect(body.get("index"), body.get("from")))
            elif path == "/api/disconnect":
                self._json(200, fav_disconnect(body.get("from")))
            elif path == "/api/asterisk/restart":
                self._json(200, restart_asterisk())
            elif path == "/api/restart":
                ok = _schedule_restart()
                self._json(200, {"ok": ok, "message": "Restarting." if ok else "",
                                 "error": "" if ok else "Not running under systemd."})
            else:
                self._json(404, {"ok": False, "error": "Not found."})
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
                log_event(f"HTTPS certificate could not be loaded ({exc}); serving plain HTTP", "err")
        else:
            log_event("No HTTPS certificate; serving plain HTTP (push-to-talk needs HTTPS)", "err")
    threading.Thread(target=HUB.pump_loop, name="pump", daemon=True).start()
    threading.Thread(target=udp_loop, args=(_cfg_get("udp_port"),), name="udp", daemon=True).start()
    threading.Thread(target=TALKER.pacer_loop, name="tx-pacer", daemon=True).start()
    threading.Thread(target=usrp_drain_loop, name="tx-drain", daemon=True).start()
    threading.Thread(target=link_keeper_loop, name="link-keeper", daemon=True).start()
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
                tx_unlink("Node Listen stopped")
        except Exception as exc:
            log_event(f"Could not unlink node {TX_NODE} on stop: {exc}", "warn")
        httpd.server_close()
    return 0


def _write_launcher():
    tmp = _LAUNCHER_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(_LAUNCHER_CODE)
    os.chmod(tmp, 0o755)
    os.replace(tmp, _LAUNCHER_PATH)
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
            if os.path.isfile(p) and _LAUNCHER_PATH in open(p, errors="replace").read():
                return
        except OSError:
            continue
    try:
        os.remove(_LAUNCHER_PATH)
    except FileNotFoundError:
        return
    print(f"  [-] Removed {_LAUNCHER_PATH} (no other service uses it)")


def _systemctl(*args):
    return subprocess.run(["systemctl", *args], capture_output=True, text=True)


def _hook_node_now():
    try:
        with open(RPT_CONF, "r", encoding="utf-8", errors="replace") as fh:
            _, stanzas = parse_rpt(fh.read())
    except OSError:
        return ""
    return next((s["name"] for s in stanzas if _is_ours(s["outstream"])), "")


def _restore_after_update():
    try:
        with open(RESTORE_PATH, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return
    try:
        os.remove(RESTORE_PATH)
    except OSError:
        pass
    if not isinstance(rec, dict):
        return
    try:
        age = time.time() - float(rec.get("time", 0))
    except (TypeError, ValueError):
        return
    if not 0 <= age <= RESTORE_MAX_AGE_SEC:
        print(f"  [i] Ignored {RESTORE_PATH}: older than {RESTORE_MAX_AGE_SEC // 60} minutes")
        return
    print(f"  [i] The uninstall {int(age)} s ago changed rpt.conf (an update); putting its Node Listen lines back")
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
        print("      Asterisk needs no restart, unless it was restarted while Node Listen was out.")


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
        tmp = dest + ".tmp"
        shutil.copy2(current, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        print(f"  [+] Copied {os.path.basename(current)} -> {dest}")
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
    _write_launcher()
    if not os.path.exists(CONFIG_PATH):
        load_config()
        save_config(dict(DEFAULT_CONFIG))
        print(f"  [+] Wrote {CONFIG_PATH}")
    load_config()
    _restore_after_update()
    with open(SYSTEMD_SERVICE_PATH, "w") as f:
        f.write(SYSTEMD_SERVICE_CONTENT)
    print(f"  [+] Wrote {SYSTEMD_SERVICE_PATH}")
    _systemctl("daemon-reload")
    _systemctl("enable", SERVICE_NAME)
    r = _systemctl("restart", SERVICE_NAME)
    if r.returncode != 0:
        print(f"  [!] systemctl restart failed: {(r.stderr or r.stdout).strip()}")
        sys.exit(1)
    load_config()
    print(f"  [+] {SERVICE_NAME} enabled and started")
    print(f"Open http://<pi-address>:{_cfg_get('port')} , log in, and pick the node on the Node card.")


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
