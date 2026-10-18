#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import array
import configparser
import hmac
import http.client
import json
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.2.0"
DATE_STR = "2026-10-18"
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


_NORMALIZERS = {
    "port": _norm_port,
    "udp_port": _norm_port,
    "node": _norm_node,
    "max_listeners": _norm_listeners,
    "public_listen": _parse_bool,
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
    restart = cfg["port"] != old["port"] or cfg["udp_port"] != old["udp_port"]
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
        msg += " Node Listen restarts to use the new port."
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


def _http_responsive(port):
    try:
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


def _sd_watchdog_loop(port):
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
            if pump_ok and _http_responsive(port):
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
            enc = ulaw_encode(frame) if frame is not None else ULAW_SILENCE
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
    st.update({"version": VERSION, "node": _cfg_get("node"), "uptime": int(time.time() - _START_TIME)})
    if full:
        st["feeder_pids"] = feeder_pids()
    else:
        st.pop("listener_list", None)
        st.pop("udp_error", None)
    return st


_CSS = r""":root{--bg:#0f1419;--card:#182029;--line:#2a3542;--text:#e6edf3;--muted:#8b98a5;--accent:#3d8bfd;
--ok:#2ea043;--warn:#d29922;--err:#f85149}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--line);background:#121a22}
header h1{font-size:18px;margin:0}
header .ver{color:var(--muted);font-size:13px}
header .sp{flex:1}
main{max-width:760px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.card h2{font-size:16px;margin:0 0 12px}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}
button{background:#263241;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 14px;font:inherit;cursor:pointer}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.big{font-size:18px;padding:12px 28px;min-width:160px}
button.danger{border-color:var(--err);color:var(--err)}
button:disabled{opacity:.5;cursor:default}
input,select{background:#0f1419;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:7px 9px;font:inherit}
input[type=number]{width:110px}
label{color:var(--muted)}
.meter{position:relative;height:14px;flex:1;min-width:160px;background:#0f1419;border:1px solid var(--line);border-radius:7px;overflow:hidden}
.meter i{position:absolute;left:0;top:0;bottom:0;width:0;background:linear-gradient(90deg,var(--ok),var(--warn) 80%,var(--err));transition:width .1s}
.dot{display:inline-block;width:12px;height:12px;border-radius:50%;background:#33404d;vertical-align:middle;margin-right:6px}
.dot.on{background:var(--ok);box-shadow:0 0 8px var(--ok)}
.dot.warn{background:var(--warn)}
.dot.err{background:var(--err)}
.muted{color:var(--muted)}
.msg{margin-top:8px;font-size:14px}
.msg.ok{color:var(--ok)}.msg.err{color:var(--err)}.msg.warn{color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{text-align:left;padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}
code{background:#0f1419;border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:13px;word-break:break-all}
#log{max-height:260px;overflow:auto;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;background:#0f1419;border:1px solid var(--line);border-radius:6px;padding:8px}
#log .err{color:var(--err)}#log .warn{color:var(--warn)}#log .ok{color:var(--ok)}
.hidden{display:none}
@media (max-width:520px){main{padding:10px}button.big{width:100%}}
"""

_JS = r"""const $ = (id) => document.getElementById(id);
let authed = false, publicListen = false, lastLogId = 0;
let ctx = null, gainNode = null, ctrl = null, playing = false, nextT = 0;
let mediaDest = null, wakeLock = null, nodeLabel = '';
let pend = new Float32Array(1600), pendN = 0, peakLocal = 0, retryTimer = null;
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
  const r = await fetch(url, opts);
  let d = {};
  try { d = await r.json(); } catch (e) { d = {ok: false, error: 'HTTP ' + r.status}; }
  if (r.status === 401 && url !== '/api/login') { authed = false; render(); }
  return d;
}

function setMsg(id, d) {
  const el = $(id);
  el.className = 'msg ' + (d.ok ? 'ok' : 'err');
  el.textContent = d.ok ? (d.message || 'Done.') : (d.error || 'Failed.');
}

function render() {
  $('login-card').classList.toggle('hidden', authed);
  $('listen-card').classList.toggle('hidden', !(authed || publicListen));
  ['node-card', 'cfg-card', 'log-card'].forEach((id) => $(id).classList.toggle('hidden', !authed));
  $('logout').classList.toggle('hidden', !authed);
  if (authed) { loadNode(); loadConfig(); }
}

async function whoami() {
  const d = await api('/api/whoami');
  authed = !!d.authed;
  publicListen = !!d.public_listen;
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
  await api('/api/logout', {method: 'POST'});
  authed = false;
  stopListen();
  render();
}

function fmtDb(db) { return db <= -119 ? '-inf' : db.toFixed(0) + ' dBFS'; }
function dbPct(db) { return Math.max(0, Math.min(100, (db + 60) / 60 * 100)); }

async function pollStatus() {
  if (!(authed || publicListen)) return;
  let d;
  try { d = await api('/api/status'); } catch (e) { return; }
  if (!d || d.ok === false) return;
  $('st-node').textContent = d.node || '(not set)';
  if ((d.node || '') !== nodeLabel) { nodeLabel = d.node || ''; setMediaInfo(); }
  $('st-listeners').textContent = d.listeners + ' / ' + d.max_listeners;
  const feed = $('st-feed');
  feed.className = 'dot ' + (d.receiving ? 'on' : (d.packets ? 'warn' : 'err'));
  $('st-feed-t').textContent = d.receiving ? ('receiving, ' + d.packets_per_sec + ' packets/s')
    : (d.last_rx_age != null ? 'no audio for ' + Math.round(d.last_rx_age) + ' s' : 'nothing received yet');
  $('st-active').className = 'dot ' + (d.audio_active ? 'on' : '');
  $('st-level').textContent = fmtDb(d.peak_db);
  if (!playing) $('meter-bar').style.width = dbPct(d.peak_db) + '%';
  if (authed && d.feeder_pids !== undefined) {
    $('nd-feeder').textContent = d.feeder_pids.length ? 'running (pid ' + d.feeder_pids.join(', ') + ')' : 'not running';
    $('nd-udp').textContent = d.udp_error ? d.udp_error : '127.0.0.1:' + d.udp_port + ' (listening)';
  }
}

function flush() {
  if (!pendN || !ctx) return;
  const buf = ctx.createBuffer(1, pendN, 8000);
  buf.copyToChannel(pend.subarray(0, pendN), 0);
  pendN = 0;
  const now = ctx.currentTime;
  if (nextT < now + 0.05 || nextT > now + 1.5) nextT = now + 0.25;
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

async function startListen() {
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) { $('listen-msg').textContent = 'This browser cannot play live audio.'; return; }
  if (!ctx) {
    ctx = new AC();
    gainNode = ctx.createGain();
    gainNode.gain.value = $('vol').value / 100;
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
  const want = playing && $('keep-awake').checked && document.visibilityState === 'visible';
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
  if (!d.nodes.length) { $('nd-msg').className = 'msg warn'; $('nd-msg').textContent = 'No numbered node stanzas found in rpt.conf.'; }
}

async function nodeEnable() {
  const n = $('nd-select').value;
  if (!n) return;
  setMsg('nd-msg', await api('/api/node/enable', {method: 'POST', body: {node: n}}));
  loadNode();
}

async function nodeDisable() {
  setMsg('nd-msg', await api('/api/node/disable', {method: 'POST', body: {}}));
  loadNode();
}

async function astRestart() {
  if (!confirm('Restart Asterisk now? Every link on this node drops and reconnects.')) return;
  $('nd-msg').className = 'msg'; $('nd-msg').textContent = 'Restarting Asterisk...';
  setMsg('nd-msg', await api('/api/asterisk/restart', {method: 'POST', body: {}}));
}

async function loadConfig() {
  const d = await api('/api/config');
  if (!d.ok) return;
  ['port', 'udp_port', 'max_listeners'].forEach((k) => { $('cfg-' + k).value = d.config[k]; });
  $('cfg-public_listen').checked = !!d.config.public_listen;
}

async function saveConfig() {
  const body = {
    port: $('cfg-port').value, udp_port: $('cfg-udp_port').value,
    max_listeners: $('cfg-max_listeners').value, public_listen: $('cfg-public_listen').checked,
  };
  const d = await api('/api/config', {method: 'POST', body: body});
  setMsg('cfg-msg', d);
  if (d.ok) { publicListen = body.public_listen; loadNode(); }
}

async function pollLog() {
  if (!authed) return;
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
  $('listen-btn').addEventListener('click', toggleListen);
  $('vol').addEventListener('input', () => { if (gainNode) gainNode.gain.value = $('vol').value / 100; });
  if ('wakeLock' in navigator) {
    $('awake-row').classList.remove('hidden');
    try { $('keep-awake').checked = localStorage.getItem('nlKeepAwake') === '1'; } catch (e) {}
  }
  $('keep-awake').addEventListener('change', () => {
    try { localStorage.setItem('nlKeepAwake', $('keep-awake').checked ? '1' : '0'); } catch (e) {}
    wakeLockApply();
  });
  document.addEventListener('visibilitychange', wakeLockApply);
  setupMediaSession();
  $('nd-enable').addEventListener('click', nodeEnable);
  $('nd-disable').addEventListener('click', nodeDisable);
  $('nd-restart').addEventListener('click', astRestart);
  $('nd-refresh').addEventListener('click', loadNode);
  $('cfg-save').addEventListener('click', saveConfig);
  whoami();
  setInterval(pollStatus, 1000);
  setInterval(pollLog, 3000);
});
"""

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Node Listen</title>
<style>__CSS__</style>
</head>
<body>
<header><h1>Node Listen</h1><span class="ver">v__VERSION__</span><span class="sp"></span>
<button id="logout" class="hidden">Log out</button></header>
<main>
<section class="card" id="login-card">
<h2>Log in</h2>
<form id="login-form" class="row">
<input type="password" id="pw" placeholder="Pi root password" autocomplete="current-password">
<button type="submit" class="primary">Log in</button>
</form>
<div id="login-msg" class="msg"></div>
</section>

<section class="card hidden" id="listen-card">
<h2>Listen</h2>
<div class="row"><button id="listen-btn" class="primary big">Listen</button>
<label>Volume <input type="range" id="vol" min="0" max="200" value="100"></label></div>
<div class="row"><div class="meter"><i id="meter-bar"></i></div><span id="st-level" class="muted">-inf</span></div>
<div class="row hidden" id="awake-row"><label><input type="checkbox" id="keep-awake"> Keep the screen on while listening</label></div>
<audio id="player" playsinline class="hidden"></audio>
<div id="listen-msg" class="msg"></div>
<table>
<tr><th>Node</th><td id="st-node">-</td></tr>
<tr><th>Feed from Asterisk</th><td><span id="st-feed" class="dot"></span><span id="st-feed-t">-</span></td></tr>
<tr><th>Audio</th><td><span id="st-active" class="dot"></span>lit while the node is passing audio</td></tr>
<tr><th>Listeners</th><td id="st-listeners">-</td></tr>
</table>
<p class="muted">Sound plays through the browser's media player, so it can carry on with the tab in the background; the phone's media controls show Node Listen and can stop it.</p>
</section>

<section class="card hidden" id="node-card">
<h2>Node</h2>
<p class="muted">Asterisk sends a node's audio here through one <code>outstreamcmd</code> line in
<code id="nd-path">rpt.conf</code>. Changes take effect after Asterisk restarts.</p>
<table><thead><tr><th>Node</th><th>outstreamcmd</th></tr></thead><tbody id="nd-rows"></tbody></table>
<div class="row"><label>Node <select id="nd-select"></select></label>
<button id="nd-enable" class="primary">Send its audio here</button>
<button id="nd-disable">Remove</button>
<button id="nd-restart" class="danger">Restart Asterisk</button>
<button id="nd-refresh">Refresh</button></div>
<div id="nd-msg" class="msg"></div>
<table>
<tr><th>Line added</th><td><code id="nd-line">-</code></td></tr>
<tr><th>Feeder process</th><td id="nd-feeder">-</td></tr>
<tr><th>UDP input</th><td id="nd-udp">-</td></tr>
</table>
</section>

<section class="card hidden" id="cfg-card">
<h2>Settings</h2>
<div class="row"><label>Web port <input type="number" id="cfg-port" min="1024" max="65535"></label>
<label>UDP port <input type="number" id="cfg-udp_port" min="1024" max="65535"></label>
<label>Max listeners <input type="number" id="cfg-max_listeners" min="1" max="10"></label></div>
<div class="row"><label><input type="checkbox" id="cfg-public_listen"> Listen without logging in</label></div>
<p class="muted">Each listener uses about 64 kbit/s. Changing a port restarts Node Listen.</p>
<div class="row"><button id="cfg-save" class="primary">Save</button></div>
<div id="cfg-msg" class="msg"></div>
</section>

<section class="card hidden" id="log-card">
<h2>Log</h2>
<div id="log"></div>
</section>
</main>
<script>__JS__</script>
</body>
</html>
"""


def render_page():
    return (_HTML_TEMPLATE.replace("__CSS__", _CSS).replace("__JS__", _JS)
            .replace("__VERSION__", VERSION)).encode("utf-8")


_OPEN_GET_PATHS = ("/", "/index.html", "/api/health", "/api/whoami")
_PUBLIC_LISTEN_PATHS = ("/api/status", "/api/listen")


class Handler(BaseHTTPRequestHandler):
    server_version = "nodelisten/" + VERSION
    sys_version = ""

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
            return None
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return body if isinstance(body, dict) else None

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
                self._json(200, {"ok": True, "authed": authed, "public_listen": _cfg_get("public_listen"),
                                 "backend": _root_backend_available()})
            elif path == "/api/status":
                d = build_status(authed)
                d["ok"] = True
                self._json(200, d)
            elif path == "/api/listen":
                self._stream()
            elif path == "/api/node":
                try:
                    d = rpt_state()
                except OSError as exc:
                    self._json(200, {"ok": False, "error": f"Could not read {RPT_CONF}: {exc}"})
                    return
                d.update(ok=True, config_node=_cfg_get("node"))
                self._json(200, d)
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

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            self._json(403, {"ok": False, "error": "Missing X-Requested-With header."})
            return
        body = self._read_json()
        if body is None:
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
                self._json(200, {"ok": True}, {"Set-Cookie": _session_cookie_header(token, _SESSION_TTL_SEC)})
            else:
                _record_auth_failure(ip)
                log_event(f"Failed login from {ip}", "warn")
                self._json(401, {"ok": False, "error": "Wrong password."})
            return
        if path == "/api/logout":
            _revoke_session(self._token())
            self._json(200, {"ok": True}, {"Set-Cookie": _session_cookie_header("", 0)})
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

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, socket.timeout)):
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
    threading.Thread(target=HUB.pump_loop, name="pump", daemon=True).start()
    threading.Thread(target=udp_loop, args=(_cfg_get("udp_port"),), name="udp", daemon=True).start()
    threading.Thread(target=_sd_watchdog_loop, args=(port,), name="watchdog", daemon=True).start()
    log_event(f"{APP_NAME} v{VERSION} on port {port}, node audio on 127.0.0.1:{_cfg_get('udp_port')}/udp", "ok")
    _sd_notify("READY=1")
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _sd_notify("STOPPING=1")
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
        r = hook_disable()
        if r.get("changed"):
            print(f"  [-] Removed the outstreamcmd line from {RPT_CONF} (backup {r.get('backup')})")
            print("      Restart Asterisk to stop the feed: systemctl restart asterisk")
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
