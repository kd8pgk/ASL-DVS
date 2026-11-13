#!/usr/bin/env python3

import argparse
import base64
import configparser
import ctypes
import ctypes.util
import fcntl
import gzip
import hashlib
import grp
import hmac
import http.cookies
import io
import ipaddress
import re
import json
import os
import pwd
import secrets
import shutil
import signal
import socket
import stat
import ssl
import struct
import syslog
import subprocess
import sys
import tempfile
import termios
import threading
import time
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.2.5"
DATE_STR = "2026-11-13"
APP_NAME = "Terminal Monitor"
SERVICE_NAME = "termon.service"
INSTALL_BIN_PATH = "/usr/local/bin/termon.py"
INSTALL_DIR = "/usr/local/lib/asl_dvs/termon"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/termon.service"
CONFIG_DIR = os.environ.get("TERMON_CONFIG_DIR", "/etc/asl_dvs")
CONFIG_PATH = os.path.join(CONFIG_DIR, "termon.conf")
CONFIG_SECTION = "termon"
DEFAULT_PORT = 7878
BTOP_DEFAULT_MS = 100
BTOP_MIN_MS = 100
BTOP_MAX_MS = 10000
PYTHON_BIN = "/usr/bin/python3"
RPT_CONF = os.environ.get("TERMON_RPT_CONF", "/etc/asterisk/rpt.conf")
TALKER_SERVICES = ("nodetalker.service", "nodelisten.service")
LOCK_PATH = os.environ.get("TERMON_LOCK", "/run/termon.lock" if os.geteuid() == 0 else "/run/termon/termon.lock")
HELPER_SOCK = os.environ.get("TERMON_HELPER_SOCK", "/run/termon-helper/helper.sock")
HELPER_LOCK = os.environ.get("TERMON_HELPER_LOCK", "/run/termon-helper/helper.lock")
HELPER_SERVICE = "termon-helper.service"
HELPER_SERVICE_PATH = "/etc/systemd/system/termon-helper.service"
DEFAULT_WEB_USER = "termon"
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
RPC_MAX_BYTES = 65536
RPC_MAX_CONNS = 32
SUDO_CACHE_SEC = 30
REAP_AFTER_SEC = 300


MAX_JSON_BYTES = 64 * 1024
MAX_SESSIONS = 4
RING_MAX_BYTES = 256 * 1024
TERM_INPUT_MAX = 16 * 1024
TICKET_TTL_SEC = 60
SESSION_COOKIE = "termon_session"
SESSION_TTL_SEC = 2 * 3600
SESSION_MAX_SEC = 12 * 3600
AUTH_MAX_FAILURES = 5
AUTH_LOCKOUT_BASE_SEC = 5
AUTH_LOCKOUT_MAX_SEC = 900
GLOBAL_FAIL_LIMIT = 20
GLOBAL_FAIL_WINDOW_SEC = 300
GLOBAL_FAIL_DELAY_SEC = 2.0
AUTH_FORGET_SEC = 3600
AUTH_TRACK_MAX = 1000
JOB_OUTPUT_MAX = 32 * 1024
DEAD_SESSION_KEEP_SEC = 300
DETACHED_KEEP_SEC = 600
STREAM_PING_SEC = 15
MAX_ALLOWED_HOSTS = 16
REQ_TIMEOUT_SEC = 30
MAX_CONNS = 64
TLS_DIR = os.path.join(CONFIG_DIR, "termon_tls")
TLS_CERT = os.path.join(TLS_DIR, "cert.pem")
TLS_KEY = os.path.join(TLS_DIR, "key.pem")
_SERVICE_ENV = ("NOTIFY_SOCKET", "WATCHDOG_USEC", "WATCHDOG_PID", "INVOCATION_ID", "JOURNAL_STREAM",
                "MAINPID", "MANAGERPID", "SYSTEMD_EXEC_PID", "TERMON_CONFIG_DIR", "TERMON_LOCK",
                "TERMON_RPT_CONF", "TERMON_HELPER_SOCK", "TERMON_HELPER_LOCK")

MONITOR_PROGS = {"top": "top", "htop": "htop", "btop": "btop"}
INSTALL_PKGS = {"procps": "top", "htop": "htop", "btop": "btop"}
DPKG_LOCKS = ("/var/lib/dpkg/lock-frontend", "/var/lib/dpkg/lock",
              "/var/lib/apt/lists/lock", "/var/cache/apt/archives/lock")

SEC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _csp(nonce=None):
    script = "script-src 'self'" + (f" 'nonce-{nonce}'" if nonce else "")
    return ("default-src 'self'; " + script + "; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; object-src 'none'; form-action 'self'")


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} termon: {msg}", file=sys.stderr, flush=True)


def audit(msg):
    log(msg)
    try:
        syslog.openlog("termon", syslog.LOG_PID, syslog.LOG_AUTHPRIV)
        syslog.syslog(syslog.LOG_NOTICE, msg)
    except (OSError, ValueError):
        pass


class HttpErr(Exception):
    def __init__(self, code, msg, html=False, headers=()):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.html = html
        self.headers = headers


def _clamp(value, lo, hi, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in _SERVICE_ENV and not k.startswith("LISTEN_")}
    env.update(extra)
    return env


def atomic_write(path, content, mode=0o644):
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_CFG_LOCK = threading.Lock()


def _norm_port(value):
    try:
        p = int(str(value).strip())
    except ValueError:
        return None
    return p if 1024 <= p <= 65535 else None


def load_config():
    cp = configparser.ConfigParser()
    try:
        cp.read(CONFIG_PATH, encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        log(f"config unreadable, using defaults: {exc}")
    sec = cp[CONFIG_SECTION] if cp.has_section(CONFIG_SECTION) else {}
    port = _norm_port(sec.get("port", "")) or DEFAULT_PORT
    last = sec.get("monitor_last", "top")
    if last not in MONITOR_PROGS:
        last = "top"
    https = str(sec.get("https", "true")).strip().lower() not in ("0", "false", "no", "off")
    shell_user = str(sec.get("shell_user", "")).strip()
    if shell_user == "root" or not USER_RE.match(shell_user):
        shell_user = ""
    web_user = str(sec.get("web_user", DEFAULT_WEB_USER)).strip()
    if web_user == "root" or not USER_RE.match(web_user):
        web_user = DEFAULT_WEB_USER
    bind_ip = str(sec.get("bind_session_ip", "false")).strip().lower() in ("1", "true", "yes", "on")
    btop_ms = _clamp(sec.get("btop_update_ms", BTOP_DEFAULT_MS), BTOP_MIN_MS, BTOP_MAX_MS, BTOP_DEFAULT_MS)
    return {"port": port, "monitor_last": last, "https": https, "shell_user": shell_user,
            "web_user": web_user, "bind_session_ip": bind_ip, "btop_update_ms": btop_ms,
            "allowed_hosts": _parse_hosts(sec.get("allowed_hosts", ""))}


def save_config(cfg):
    cp = configparser.ConfigParser()
    cp[CONFIG_SECTION] = {"port": str(cfg["port"]), "monitor_last": cfg["monitor_last"],
                          "https": "true" if cfg.get("https", True) else "false",
                          "shell_user": cfg.get("shell_user", ""),
                          "web_user": cfg.get("web_user", DEFAULT_WEB_USER),
                          "bind_session_ip": "true" if cfg.get("bind_session_ip") else "false",
                          "btop_update_ms": str(cfg.get("btop_update_ms", BTOP_DEFAULT_MS)),
                          "allowed_hosts": ",".join(cfg.get("allowed_hosts", []))}
    buf = io.StringIO()
    cp.write(buf)
    content = buf.getvalue()
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            if fh.read() == content:
                os.chmod(CONFIG_PATH, 0o644)
                return
    except OSError:
        pass
    atomic_write(CONFIG_PATH, content, mode=0o644)


def _remember_monitor(prog):
    with _CFG_LOCK:
        cfg = load_config()
        if cfg["monitor_last"] == prog:
            return
        cfg["monitor_last"] = prog
        try:
            save_config(cfg)
        except OSError as exc:
            log(f"cannot remember the monitor program: {exc}")


_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
_OWN_NAMES = frozenset()
_EXTRA_HOSTS = frozenset()
HOST_REFUSED_PAGE = ("<!doctype html><meta charset=utf-8><title>Terminal Monitor</title>"
                     "<p>This address is not allowed. Open this node by its IP address. "
                     "To use a name, add it under Setup, Allowed names.</p>")


def _is_ip_text(text):
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _norm_host(name):
    if not isinstance(name, str):
        return None
    n = name.strip().lower().rstrip(".")
    if not n or len(n) > 253 or not _HOST_RE.match(n):
        return None
    return n


def _parse_hosts(text):
    out = []
    for item in str(text).split(","):
        n = _norm_host(item)
        if n and not _is_ip_text(n) and n not in out:
            out.append(n)
    return out[:MAX_ALLOWED_HOSTS]


def _init_names(cfg=None):
    global _OWN_NAMES, _EXTRA_HOSTS
    cfg = cfg or load_config()
    own = set()
    host = _norm_host(socket.gethostname())
    if host:
        short = host.split(".")[0]
        own.update((host, short, short + ".local", host + ".local"))
    _OWN_NAMES = frozenset(own)
    _EXTRA_HOSTS = frozenset(cfg["allowed_hosts"])


def _parse_host_header(value):
    if not isinstance(value, str) or not value or len(value) > 300:
        return None
    v = value.strip()
    if v.startswith("["):
        end = v.find("]")
        if end < 0:
            return None
        inner, rest = v[1:end], v[end + 1:]
        if rest and not (rest.startswith(":") and rest[1:].isdigit() and len(rest) <= 6):
            return None
        if "%" in inner:
            return None
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            return None
        return (inner.lower(), True)
    if v.count(":") > 1:
        return None
    host = v
    if ":" in v:
        host, port = v.rsplit(":", 1)
        if not port.isdigit() or len(port) > 5:
            return None
    host = host.strip()
    try:
        ipaddress.IPv4Address(host)
        return (host, True)
    except ValueError:
        pass
    n = _norm_host(host)
    return (n, False) if n else None


def _host_ok(values):
    if not values or len(values) != 1:
        return False
    parsed = _parse_host_header(values[0])
    if parsed is None:
        return False
    name, is_ip = parsed
    return is_ip or name == "localhost" or name in _OWN_NAMES or name in _EXTRA_HOSTS


_crypt_fn = None


def _libcrypt():
    global _crypt_fn
    if _crypt_fn is None:
        _crypt_fn = False
        names = ["libcrypt.so.1", "libcrypt.so.2", "libcrypt.so", ctypes.util.find_library("crypt")]
        for name in names:
            if not name:
                continue
            try:
                lib = ctypes.CDLL(name)
                fn = lib.crypt
                fn.restype = ctypes.c_char_p
                fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
                _crypt_fn = fn
                break
            except (OSError, AttributeError):
                continue
        if _crypt_fn is False:
            log("login: no usable libcrypt found, and python-pam is not installed")
    return _crypt_fn


def _crypt_verify(password, stored_hash):
    if not stored_hash or stored_hash[0] in "!*":
        return False
    fn = _libcrypt()
    if not fn:
        return False
    out = fn(password.encode("utf-8"), stored_hash.encode("ascii", "replace"))
    if not out:
        return False
    return hmac.compare_digest(out.decode("ascii", "replace"), stored_hash)


def _shadow_hash(account):
    with open("/etc/shadow", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split(":")
            if parts[0] == account:
                return parts[1] if len(parts) > 1 else None
    return None


def _verify_account_password(account, password):
    try:
        import pam as _pam
    except ImportError:
        _pam = None
    if _pam is not None:
        try:
            return bool(_pam.pam().authenticate(account, password, service="login"))
        except Exception as exc:
            log(f"login: PAM check failed: {exc!r}")
            return False
    try:
        stored = _shadow_hash(account)
    except OSError as exc:
        log(f"login: cannot read /etc/shadow ({exc}); the helper must run as root")
        return False
    if stored is None:
        return False
    return _crypt_verify(password, stored)


_sess_lock = threading.Lock()
_sessions = {}
_ticket_lock = threading.Lock()
_tickets = {}
_auth_lock = threading.Lock()
_login_lock = threading.Lock()
_auth_state = {}
_global_fails = deque()


def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_BIND_IP = False


def _session_dead(rec, now):
    return rec[0] < now or rec[1] < now


def _issue_session(ip=""):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _sess_lock:
        for k in [k for k, v in _sessions.items() if _session_dead(v, now)]:
            del _sessions[k]
        _sessions[_digest(token)] = [now + SESSION_TTL_SEC, now + SESSION_MAX_SEC, _lock_key(ip) if ip else ""]
    return token


def _session_valid(token, touch=True, ip=None):
    if not token:
        return False
    now = time.time()
    d = _digest(token)
    with _sess_lock:
        rec = _sessions.get(d)
        if rec is None:
            return False
        if _session_dead(rec, now):
            _sessions.pop(d, None)
            return False
        if _BIND_IP and ip is not None and rec[2] and rec[2] != _lock_key(ip):
            _sessions.pop(d, None)
            refused = True
        else:
            refused = False
            if touch:
                rec[0] = now + SESSION_TTL_SEC
    if refused:
        audit(f"session: ended, it was used from {_lock_key(ip)} but signed in from {rec[2]}")
        _close_owner(d)
        return False
    return True


def _revoke_session(token):
    if token:
        d = _digest(token)
        with _sess_lock:
            _sessions.pop(d, None)
        _close_owner(d)


def _issue_ticket(token):
    t = secrets.token_urlsafe(24)
    now = time.time()
    with _ticket_lock:
        for k in [k for k, v in _tickets.items() if v[1] < now]:
            del _tickets[k]
        _tickets[t] = (_digest(token), now + TICKET_TTL_SEC)
    return t


def _take_ticket(ticket, token):
    if not ticket:
        return False
    with _ticket_lock:
        rec = _tickets.pop(ticket, None)
    return rec is not None and rec[1] >= time.time() and rec[0] == _digest(token)


def _lock_key(ip):
    try:
        addr = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return str(ip)
    if addr.version == 6 and addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    if addr.version == 6:
        return str(ipaddress.ip_network((addr, 64), strict=False))
    return str(addr)


def _lock_remaining(ip):
    key = _lock_key(ip)
    now = time.time()
    with _auth_lock:
        rec = _auth_state.get(key)
        if rec is None:
            return 0
        if now - rec[2] > AUTH_FORGET_SEC and rec[1] <= now:
            _auth_state.pop(key, None)
            return 0
        return max(0, int(rec[1] - now + 0.999))


def _record_fail(ip):
    key = _lock_key(ip)
    now = time.time()
    with _auth_lock:
        if len(_auth_state) >= AUTH_TRACK_MAX:
            for k in [k for k, v in _auth_state.items() if now - v[2] > AUTH_FORGET_SEC and v[1] <= now]:
                del _auth_state[k]
            if len(_auth_state) >= AUTH_TRACK_MAX and key not in _auth_state:
                order = sorted(_auth_state.items(), key=lambda kv: (kv[1][1] > now, kv[1][2]))
                for k, _ in order[:max(1, len(_auth_state) - AUTH_TRACK_MAX + 1)]:
                    del _auth_state[k]
        rec = _auth_state.setdefault(key, [0, 0.0, now])
        rec[0] += 1
        rec[2] = now
        if rec[0] >= AUTH_MAX_FAILURES:
            step = rec[0] - AUTH_MAX_FAILURES
            wait = min(AUTH_LOCKOUT_BASE_SEC * (2 ** min(step, 16)), AUTH_LOCKOUT_MAX_SEC)
            rec[1] = now + wait
            audit(f"login: {key} locked for {wait}s after {rec[0]} failed attempts")
        _global_fails.append(now)
        while _global_fails and now - _global_fails[0] > GLOBAL_FAIL_WINDOW_SEC:
            _global_fails.popleft()


def _global_delay():
    now = time.time()
    with _auth_lock:
        while _global_fails and now - _global_fails[0] > GLOBAL_FAIL_WINDOW_SEC:
            _global_fails.popleft()
        busy = len(_global_fails) >= GLOBAL_FAIL_LIMIT
    return GLOBAL_FAIL_DELAY_SEC if busy else 0.0


def _record_ok(ip):
    with _auth_lock:
        _auth_state.pop(_lock_key(ip), None)


_LAN_NETS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fe80::/10", "fc00::/7"))
_TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
_PROXY_HEADERS = ("Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto",
                  "X-Real-IP", "CF-Connecting-IP", "True-Client-IP", "Tailscale-Funnel-Request")


def _is_lan(text):
    try:
        ip = ipaddress.ip_address(str(text).split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.version == 6 and ip in _TAILNET_V6:
        return False
    return any(net.version == ip.version and ip in net for net in _LAN_NETS)


_pty_lock = threading.Lock()
_ptys = {}


class PtySession:
    def __init__(self, kind, prog, rows, cols, owner, peer=""):
        info = _priv(BACKEND.spawn, kind, prog, rows, cols)
        self.pid = info["pid"]
        self.fd = info["fd"]
        self.label = info["label"]
        self.sid = secrets.token_hex(16)
        self.owner = owner
        self.peer = peer
        self.cond = threading.Condition()
        self.ring = deque()
        self.ring_bytes = 0
        self.seq = 0
        self.alive = True
        self.exit_code = None
        self.started_at = time.time()
        self.ended_at = 0.0
        self.attached = 0
        self.idle_since = self.started_at
        self.resize(rows, cols)
        audit(f"terminal {self.label} opened from {peer or 'unknown'} (pid {self.pid})")
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            try:
                data = os.read(self.fd, 4096)
            except OSError:
                data = b""
            if not data:
                break
            with self.cond:
                self.seq += 1
                self.ring.append((self.seq, data))
                self.ring_bytes += len(data)
                while self.ring_bytes > RING_MAX_BYTES and len(self.ring) > 1:
                    _, old = self.ring.popleft()
                    self.ring_bytes -= len(old)
                self.cond.notify_all()
        code = None
        try:
            code = BACKEND.wait(self.pid)
        except PrivError:
            pass
        with self.cond:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.alive = False
            self.exit_code = code
            self.ended_at = time.time()
            self.cond.notify_all()
        audit(f"terminal {self.label} from {self.peer or 'unknown'} closed after "
              f"{int(self.ended_at - self.started_at)}s (exit {code})")

    def attach(self):
        with self.cond:
            self.attached += 1

    def detach(self):
        with self.cond:
            self.attached = max(0, self.attached - 1)
            if self.attached == 0:
                self.idle_since = time.time()

    def write(self, data):
        if not self.alive:
            return False
        view = memoryview(data)
        try:
            while view:
                n = os.write(self.fd, view)
                view = view[n:]
        except OSError:
            return False
        return True

    def resize(self, rows, cols):
        if not self.alive:
            return
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def _signal(self, name):
        try:
            BACKEND.signal(self.pid, name)
        except PrivError as exc:
            log(f"terminal {self.label}: could not signal it: {exc.msg}")

    def close(self):
        if self.alive:
            self._signal("HUP")
            timer = threading.Timer(2.0, self._force)
            timer.daemon = True
            timer.start()

    def _force(self):
        if self.alive:
            self._signal("KILL")


def _reap_locked():
    now = time.time()
    for sid, s in list(_ptys.items()):
        if not s.alive and now - s.ended_at > DEAD_SESSION_KEEP_SEC:
            del _ptys[sid]
        elif s.alive and s.attached == 0 and now - s.idle_since > DETACHED_KEEP_SEC:
            log(f"terminal {s.label}: closed after {DETACHED_KEEP_SEC // 60} min with no page attached")
            s.close()
            del _ptys[sid]


def _start_session(kind, prog, rows, cols, owner, peer=""):
    with _pty_lock:
        _reap_locked()
        for sid, s in list(_ptys.items()):
            if s.owner == owner:
                if s.alive:
                    s.close()
                del _ptys[sid]
        if sum(1 for s in _ptys.values() if s.alive) >= MAX_SESSIONS:
            raise HttpErr(409, f"{MAX_SESSIONS} terminals are already open for other logins. Try again later.")
        sess = PtySession(kind, prog, rows, cols, owner, peer)
        _ptys[sess.sid] = sess
    return sess


def _get_session(sid, token):
    with _pty_lock:
        sess = _ptys.get(sid) if isinstance(sid, str) else None
    if sess is None or sess.owner != _digest(token):
        raise HttpErr(404, "No such terminal session.")
    return sess


def _close_all_sessions():
    with _pty_lock:
        sessions = list(_ptys.values())
    for s in sessions:
        s.close()


def _close_owner(owner):
    with _pty_lock:
        for sid, s in list(_ptys.items()):
            if s.owner == owner:
                s.close()
                del _ptys[sid]


def _sweep():
    now = time.time()
    with _sess_lock:
        for k in [k for k, v in _sessions.items() if _session_dead(v, now)]:
            del _sessions[k]
        live = set(_sessions)
    with _pty_lock:
        for sid, s in list(_ptys.items()):
            if s.owner not in live:
                log(f"terminal {s.label}: closed because its login ended")
                s.close()
                del _ptys[sid]


def _maint_loop():
    while True:
        time.sleep(20)
        try:
            _sweep()
        except Exception as exc:
            log(f"maintenance error: {exc!r}")


_job_lock = threading.Lock()
_job = {"id": 0, "pkg": "", "state": "idle", "output": "", "code": None}


def _job_view():
    with _job_lock:
        return dict(_job)


def _job_add(jid, text):
    with _job_lock:
        if jid == _job["id"]:
            _job["output"] = (_job["output"] + text)[-JOB_OUTPUT_MAX:]


def _dpkg_busy():
    busy = []
    for path in DPKG_LOCKS:
        if not os.path.exists(path):
            continue
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            continue
        try:
            try:
                fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.lockf(fd, fcntl.LOCK_UN)
            except OSError:
                busy.append(path)
        finally:
            os.close(fd)
    return busy


def _run_install(jid, pkg):
    env = _clean_env(DEBIAN_FRONTEND="noninteractive", LC_ALL="C.UTF-8")
    steps = (["apt-get", "update", "-qq"], ["apt-get", "install", "-y", "--no-install-recommends", pkg])
    code = -1
    try:
        for cmd in steps:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, env=env, text=True,
                                    errors="replace", bufsize=1)
            for line in proc.stdout:
                _job_add(jid, line)
            code = proc.wait()
            if code != 0:
                break
    except OSError as exc:
        _job_add(jid, f"could not start apt: {exc}\n")
    ok = code == 0 and bool(shutil.which(INSTALL_PKGS[pkg]))
    with _job_lock:
        if _job["id"] == jid:
            _job["state"] = "ok" if ok else "failed"
            _job["code"] = code
    audit(f"install: apt {pkg} {'finished' if ok else 'failed'} (exit {code})")


def firewall_backend():
    try:
        if shutil.which("firewall-cmd") and subprocess.run(
                ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=10).stdout.strip() == "running":
            return "firewalld"
        if shutil.which("ufw") and "Status: active" in subprocess.run(
                ["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout:
            return "ufw"
    except (OSError, subprocess.SubprocessError):
        pass
    return "none"


def _fw_run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()


def open_firewall_port(port, proto="tcp"):
    spec = f"{port}/{proto}"
    backend = firewall_backend()
    try:
        if backend == "firewalld":
            zone = _fw_run(["firewall-cmd", "--get-default-zone"])
            check = ["firewall-cmd", f"--zone={zone}", f"--query-port={spec}"]
            if _fw_run(["firewall-cmd", f"--zone={zone}", "--get-target"]) == "ACCEPT" or _fw_run(check) == "yes":
                return "=", f"{spec} is already open in firewalld zone {zone}"
            _fw_run(["firewall-cmd", f"--zone={zone}", f"--add-port={spec}"])
            _fw_run(["firewall-cmd", "--permanent", f"--zone={zone}", f"--add-port={spec}"])
            if _fw_run(check) == "yes":
                return "+", f"opened {spec} in firewalld zone {zone} (now and after a reboot)"
            return "!", f"could not open {spec} in firewalld zone {zone}"
        if backend == "ufw":
            allow = rf"^{port}/{proto}\s+ALLOW"
            status = _fw_run(["ufw", "status", "verbose"])
            if "Default: allow (incoming)" in status or re.search(allow, status, re.M):
                return "=", f"{spec} is already open in ufw"
            _fw_run(["ufw", "allow", spec])
            if re.search(allow, _fw_run(["ufw", "status", "verbose"]), re.M):
                return "+", f"opened {spec} in ufw"
            return "!", f"could not open {spec} in ufw"
    except (OSError, subprocess.SubprocessError) as exc:
        return "!", f"could not open {spec} in {backend}: {exc}"
    return "=", f"no active firewall (ufw or firewalld), so {spec} is not blocked"


def close_firewall_port(port, proto="tcp"):
    spec = f"{port}/{proto}"
    backend = firewall_backend()
    try:
        if backend == "firewalld":
            zone = _fw_run(["firewall-cmd", "--get-default-zone"])
            check = ["firewall-cmd", f"--zone={zone}", f"--query-port={spec}"]
            was_open = _fw_run(check) == "yes"
            _fw_run(["firewall-cmd", f"--zone={zone}", f"--remove-port={spec}"])
            _fw_run(["firewall-cmd", "--permanent", f"--zone={zone}", f"--remove-port={spec}"])
            if _fw_run(check) == "yes":
                return "!", f"could not close {spec} in firewalld zone {zone}"
            return ("-", f"closed {spec} in firewalld zone {zone}") if was_open else \
                ("=", f"{spec} was not open in firewalld zone {zone}")
        if backend == "ufw":
            allow = rf"^{port}/{proto}\s+ALLOW"
            if not re.search(allow, _fw_run(["ufw", "status", "verbose"]), re.M):
                return "=", f"{spec} was not open in ufw"
            _fw_run(["ufw", "--force", "delete", "allow", spec])
            status = _fw_run(["ufw", "status", "verbose"])
            if re.search(allow, status, re.M):
                return "!", f"could not close {spec} in ufw"
            if "Default: allow (incoming)" in status:
                return "!", f"closed {spec} in ufw, but ufw's default allows incoming traffic, so it stays reachable"
            return "-", f"closed {spec} in ufw"
    except (OSError, subprocess.SubprocessError) as exc:
        return "!", f"could not close {spec} in {backend}: {exc}"
    return "=", f"no active firewall (ufw or firewalld), so {spec} was not blocked"


def _port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _restart_later():
    time.sleep(1.5)
    if not os.environ.get("INVOCATION_ID"):
        log("port changed: not running under systemd; restart termon to apply")
        return
    log("port changed: restarting the service to apply it")
    try:
        subprocess.run(["systemd-run", "--on-active=2s", "--unit=termon-port-restart",
                        "systemctl", "restart", SERVICE_NAME], check=False)
    except OSError:
        subprocess.run(["systemctl", "restart", "--no-block", SERVICE_NAME], check=False)


class PrivError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


BACKEND = None
_PTY_EXEC = ("import os, sys, fcntl, termios\n"
             "uid, gid, user = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]\n"
             "os.setsid()\n"
             "fcntl.ioctl(0, termios.TIOCSCTTY, 1)\n"
             "if uid != 0:\n"
             "    os.initgroups(user, gid)\n"
             "    os.setgid(gid)\n"
             "    os.setuid(uid)\n"
             "os.execvp(sys.argv[4], sys.argv[4:])\n")
_NO_LOGIN_SHELLS = ("nologin", "false")
_sudo_cache = {}


def _priv(fn, *args):
    try:
        return fn(*args)
    except PrivError as exc:
        raise HttpErr(exc.code, exc.msg)


def _proc_start(pid):
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            return fh.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return ""


def _file_problem(path):
    real = os.path.realpath(path)
    cur = real
    while True:
        try:
            st = os.stat(cur)
        except OSError as exc:
            return f"{cur}: {exc.strerror}"
        if st.st_uid != 0:
            return f"{cur} does not belong to root"
        sticky_dir = stat.S_ISDIR(st.st_mode) and st.st_mode & stat.S_ISVTX
        if st.st_mode & 0o022 and not sticky_dir:
            return f"{cur} can be changed by group or others"
        parent = os.path.dirname(cur)
        if parent == cur:
            return ""
        cur = parent


def _install_source_problem(path):
    st = os.stat(path)
    if st.st_mode & 0o022:
        return "it can be changed by group or others"
    allowed = {0}
    try:
        allowed.add(int(os.environ.get("SUDO_UID", "")))
    except ValueError:
        pass
    if st.st_uid not in allowed:
        return f"it belongs to uid {st.st_uid}, not root or the user running sudo"
    return ""


_btop_flag_cache = {}


def _btop_args(exe, ms):
    ok = _btop_flag_cache.get(exe)
    if ok is None:
        try:
            r = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=5,
                               stdin=subprocess.DEVNULL, env=_clean_env(TERM="dumb"))
            ok = "--update" in (r.stdout + r.stderr)
        except (OSError, subprocess.SubprocessError):
            ok = False
        _btop_flag_cache[exe] = ok
    return ["--update", str(ms)] if ok else []


def _no_login_shell(pw):
    return not pw.pw_shell or os.path.basename(pw.pw_shell) in _NO_LOGIN_SHELLS


def _sudo_state(user):
    if user == "root":
        return "root"
    now = time.time()
    hit = _sudo_cache.get(user)
    if hit and now - hit[0] < SUDO_CACHE_SEC:
        return hit[1]
    state = "unknown"
    exe = shutil.which("sudo")
    if not exe:
        state = "none"
    else:
        try:
            r = subprocess.run([exe, "-n", "-l", "-U", user], capture_output=True, text=True, timeout=10,
                               stdin=subprocess.DEVNULL, env=_clean_env(LC_ALL="C"))
            out = r.stdout + r.stderr
            if "not allowed to run sudo" in out:
                state = "none"
            elif "NOPASSWD" in out:
                state = "nopasswd"
            elif r.returncode == 0:
                state = "password"
        except (OSError, subprocess.SubprocessError):
            pass
    _sudo_cache[user] = (now, state)
    return state


def _ensure_system_user(name):
    try:
        pw = pwd.getpwnam(name)
    except KeyError:
        nologin = shutil.which("nologin") or "/usr/sbin/nologin"
        r = subprocess.run(["useradd", "--system", "--no-create-home", "--user-group",
                            "--home-dir", "/nonexistent", "--shell", nologin, name],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise PrivError(500, "Could not create the user: " + (r.stderr.strip() or r.stdout.strip())[:200])
        return pwd.getpwnam(name)
    if pw.pw_uid == 0:
        raise PrivError(400, "The web service user cannot be root.")
    if not _no_login_shell(pw):
        raise PrivError(400, "That account can log in. Use a system account with no login shell.")
    return pw


def _chown_tls(owner):
    try:
        pw = pwd.getpwnam(owner)
    except KeyError:
        return
    for path, mode in ((TLS_DIR, 0o700), (TLS_KEY, 0o600), (TLS_CERT, 0o644)):
        if os.path.exists(path):
            os.chown(path, pw.pw_uid, pw.pw_gid)
            os.chmod(path, mode)


class Privileged:
    split = False

    def __init__(self):
        self._procs = {}
        self._lock = threading.Lock()
        self._fails = deque()
        self.sock_path = None
        self.pids_path = None
        threading.Thread(target=self._reap_loop, daemon=True).start()

    def _save_pids(self):
        if not self.pids_path:
            return
        with self._lock:
            table = {str(pid): rec[2] for pid, rec in self._procs.items()}
        try:
            atomic_write(self.pids_path, json.dumps(table), mode=0o600)
        except OSError as exc:
            log(f"cannot record running terminals: {exc}")

    def kill_leftovers(self):
        if not self.pids_path:
            return 0
        try:
            with open(self.pids_path, encoding="utf-8") as fh:
                table = json.load(fh)
        except (OSError, ValueError):
            return 0
        killed = 0
        for pid_text, started in (table.items() if isinstance(table, dict) else ()):
            try:
                pid = int(pid_text)
            except ValueError:
                continue
            if pid > 1 and started and _proc_start(pid) == started:
                try:
                    os.killpg(pid, signal.SIGKILL)
                    killed += 1
                    log(f"helper: ended terminal process {pid} left by an earlier helper")
                except OSError:
                    pass
        try:
            atomic_write(self.pids_path, "{}", mode=0o600)
        except OSError:
            pass
        return killed

    def available(self):
        return True

    def ping(self):
        return True

    def _penalty(self, failed):
        now = time.time()
        with self._lock:
            while self._fails and now - self._fails[0] > 60:
                self._fails.popleft()
            if failed:
                self._fails.append(now)
            n = len(self._fails)
        if failed and n > 3:
            time.sleep(min(0.5 * (n - 3), 2.0))

    def _reap_loop(self):
        while True:
            time.sleep(30)
            now = time.time()
            with self._lock:
                for pid, (proc, born, _) in list(self._procs.items()):
                    if proc.poll() is not None and now - born > REAP_AFTER_SEC:
                        del self._procs[pid]

    def verify(self, password):
        account = load_config()["shell_user"] or "root"
        ok = _verify_account_password(account, password)
        self._penalty(not ok)
        return ok

    def spawn(self, kind, prog, rows, cols):
        cfg = load_config()
        account = cfg["shell_user"] or "root"
        try:
            pw = pwd.getpwnam(account)
        except KeyError:
            raise PrivError(409, f"The shell account {account} does not exist. Fix it in Setup.")
        if kind == "shell":
            argv = ["bash", "-l"]
            label = "Root shell" if account == "root" else f"Shell ({account})"
        elif kind == "monitor":
            if not isinstance(prog, str) or prog not in MONITOR_PROGS:
                raise PrivError(400, "Unknown program.")
            exe = shutil.which(MONITOR_PROGS[prog])
            if not exe:
                raise PrivError(409, f"{prog} is not installed. Use the Setup card to install it.")
            argv, label = [exe], prog
            if prog == "btop":
                argv += _btop_args(exe, cfg["btop_update_ms"])
            _remember_monitor(prog)
        else:
            raise PrivError(400, "Unknown terminal kind.")
        cwd = pw.pw_dir if os.path.isdir(pw.pw_dir) else "/"
        env = _clean_env(TERM="xterm-256color", COLORTERM="truecolor", LANG="C.UTF-8", LC_ALL="C.UTF-8",
                         HOME=pw.pw_dir, USER=account, LOGNAME=account)
        master, slave = os.openpty()
        try:
            if pw.pw_uid != 0:
                try:
                    tty_gid = grp.getgrnam("tty").gr_gid
                except KeyError:
                    tty_gid = pw.pw_gid
                os.fchown(slave, pw.pw_uid, tty_gid)
                os.fchmod(slave, 0o620)
            proc = subprocess.Popen([sys.executable, "-I", "-S", "-c", _PTY_EXEC,
                                     str(pw.pw_uid), str(pw.pw_gid), account] + argv,
                                    stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env, close_fds=True)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        with self._lock:
            self._procs[proc.pid] = (proc, time.time(), _proc_start(proc.pid))
        self._save_pids()
        return {"pid": proc.pid, "fd": master, "label": label}

    def signal(self, pid, name):
        sig = {"HUP": signal.SIGHUP, "KILL": signal.SIGKILL}.get(name)
        with self._lock:
            known = pid in self._procs
        if sig is None or not known:
            return
        try:
            os.killpg(pid, sig)
        except OSError:
            pass

    def wait(self, pid):
        with self._lock:
            rec = self._procs.get(pid)
        if rec is None:
            return None
        code = rec[0].wait()
        with self._lock:
            self._procs.pop(pid, None)
        self._save_pids()
        return code

    def install(self, pkg, who=""):
        if not isinstance(pkg, str) or pkg not in INSTALL_PKGS:
            raise PrivError(400, "Only top (procps), htop and btop can be installed here.")
        if shutil.which(INSTALL_PKGS[pkg]):
            raise PrivError(409, "Already installed.")
        busy = _dpkg_busy()
        if busy:
            raise PrivError(409, "Another package job holds: " + ", ".join(busy) + ". Try again shortly.")
        with _job_lock:
            if _job["state"] == "running":
                raise PrivError(409, "An install is already running.")
            _job["id"] += 1
            jid = _job["id"]
            _job.update(pkg=pkg, state="running", output="", code=None)
        audit(f"install: apt {pkg} started (requested from {who})")
        threading.Thread(target=_run_install, args=(jid, pkg), daemon=True).start()
        return jid

    def job_view(self):
        return _job_view()

    def set_port(self, port, who=""):
        port = _norm_port(port)
        if port is None:
            raise PrivError(400, "Use a port from 1024 to 65535.")
        with _CFG_LOCK:
            cfg = load_config()
            cur = cfg["port"]
            if port != cur:
                if not _port_free(port):
                    raise PrivError(409, f"Port {port} is in use. Pick another.")
                cfg["port"] = port
                try:
                    save_config(cfg)
                except OSError as exc:
                    raise PrivError(500, f"Could not save the config: {exc}")
                audit(f"port: changed from {cur} to {port} (requested from {who})")
                for action, number in ((open_firewall_port, port), (close_firewall_port, cur)):
                    mark, msg = action(number)
                    if mark == "=":
                        log(f"firewall: {msg}")
                    else:
                        audit(f"firewall: {msg}")
        restarting = port != cur
        if restarting:
            threading.Thread(target=_restart_later, daemon=True).start()
        return restarting

    def set_hosts(self, names, who=""):
        out = []
        if not isinstance(names, list) or len(names) > MAX_ALLOWED_HOSTS:
            raise PrivError(400, f"At most {MAX_ALLOWED_HOSTS} names.")
        for x in names:
            n = _norm_host(x)
            if n is None or _is_ip_text(n):
                raise PrivError(400, "Not a valid host name (IP addresses are always allowed): " + str(x)[:60])
            if n not in out:
                out.append(n)
        with _CFG_LOCK:
            cfg = load_config()
            cfg["allowed_hosts"] = out
            try:
                save_config(cfg)
            except OSError as exc:
                raise PrivError(500, f"Could not save the config: {exc}")
        audit(f"allowed names changed to {out or 'none'} (requested from {who})")
        return out

    def set_shell_user(self, user, password, who=""):
        user = str(user or "").strip()
        if user == "root":
            user = ""
        if user and not USER_RE.match(user):
            raise PrivError(400, "Not a valid user name.")
        account = user or "root"
        try:
            pw = pwd.getpwnam(account)
        except KeyError:
            raise PrivError(400, "No such user.")
        if user:
            if pw.pw_uid == 0:
                raise PrivError(400, "Use root by leaving the name empty.")
            if _no_login_shell(pw):
                raise PrivError(400, "That account has no login shell.")
            if user == load_config()["web_user"]:
                raise PrivError(400, "That is the web service user.")
        if not isinstance(password, str) or not password or len(password) > 1024 or "\0" in password:
            raise PrivError(400, "Enter that account's password.")
        ok = _verify_account_password(account, password)
        self._penalty(not ok)
        if not ok:
            audit(f"setup: shell account change to {account} refused, wrong password (from {who})")
            raise PrivError(401, "Incorrect password for that account.")
        with _CFG_LOCK:
            cfg = load_config()
            cfg["shell_user"] = user
            try:
                save_config(cfg)
            except OSError as exc:
                raise PrivError(500, f"Could not save the config: {exc}")
        audit(f"setup: shell account is now {account} (requested from {who})")
        return {"account": account, "sudo": _sudo_state(account)}

    def set_web_user(self, name, who=""):
        name = str(name or "").strip()
        if not USER_RE.match(name) or name == "root":
            raise PrivError(400, "Not a valid user name.")
        cfg = load_config()
        if name == cfg["shell_user"]:
            raise PrivError(400, "That is the shell account.")
        pw = _ensure_system_user(name)
        with _CFG_LOCK:
            cfg = load_config()
            cfg["web_user"] = name
            try:
                save_config(cfg)
                _chown_tls(name)
            except OSError as exc:
                raise PrivError(500, f"Could not apply the change: {exc}")
        if os.path.exists(SYSTEMD_SERVICE_PATH):
            try:
                atomic_write(SYSTEMD_SERVICE_PATH, _web_unit_text(name), mode=0o644)
            except OSError as exc:
                raise PrivError(500, f"Could not rewrite the unit: {exc}")
            _systemctl("daemon-reload")
        if self.sock_path and os.path.exists(self.sock_path):
            try:
                os.chown(self.sock_path, pw.pw_uid, -1)
            except OSError:
                pass
        audit(f"setup: web service user is now {name} (requested from {who})")
        restarting = os.path.exists(SYSTEMD_SERVICE_PATH)
        if restarting:
            threading.Thread(target=_restart_later, daemon=True).start()
        return restarting

    def set_option(self, name, value, who=""):
        if name != "bind_session_ip" or not isinstance(value, bool):
            raise PrivError(400, "Unknown setting.")
        with _CFG_LOCK:
            cfg = load_config()
            cfg[name] = value
            try:
                save_config(cfg)
            except OSError as exc:
                raise PrivError(500, f"Could not save the config: {exc}")
        audit(f"setup: {name} is now {'on' if value else 'off'} (requested from {who})")
        return value

    def regen_cert(self, who=""):
        with _CFG_LOCK:
            cfg = load_config()
            if not cfg["https"]:
                raise PrivError(409, "HTTPS is off, so there is no certificate to replace.")
            moved = []
            for path in (TLS_CERT, TLS_KEY):
                if os.path.exists(path):
                    os.replace(path, path + ".old")
                    moved.append(path)
            if not ensure_tls_cert():
                for path in moved:
                    os.replace(path + ".old", path)
                raise PrivError(500, "Could not create a new certificate. The old one is kept.")
            for path in moved:
                try:
                    os.unlink(path + ".old")
                except OSError:
                    pass
            _chown_tls(cfg["web_user"])
        audit(f"setup: new HTTPS certificate {_cert_fingerprint()} (requested from {who})")
        restarting = os.path.exists(SYSTEMD_SERVICE_PATH)
        if restarting:
            threading.Thread(target=_restart_later, daemon=True).start()
        return {"restarting": restarting, "sha256": _cert_fingerprint()}

    def account_info(self):
        cfg = load_config()
        account = cfg["shell_user"] or "root"
        return {"account": account, "sudo": _sudo_state(account), "web_user": cfg["web_user"],
                "split": self.split}


def _clean_text(value, limit=64):
    return "".join(c for c in str(value or "")[:limit] if c.isprintable())


class HelperServer:
    def __init__(self, path, priv):
        self.path = path
        self.priv = priv
        self.slots = threading.BoundedSemaphore(RPC_MAX_CONNS)
        self.sock = None

    def _web_uid(self):
        try:
            return pwd.getpwnam(load_config()["web_user"]).pw_uid
        except KeyError:
            return None

    def bind(self):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, mode=0o755, exist_ok=True)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            self.sock.bind(self.path)
        finally:
            os.umask(old)
        uid = self._web_uid()
        if uid is not None:
            try:
                os.chown(self.path, uid, -1)
            except OSError:
                pass
        self.priv.sock_path = self.path
        self.sock.listen(16)

    def serve_forever(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            if not self.slots.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            try:
                uid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                          struct.calcsize("3i")))[1]
            except OSError:
                return
            if uid != 0 and uid != self._web_uid():
                log(f"helper: refused a connection from uid {uid}")
                return
            conn.settimeout(30)
            raw = b""
            while b"\n" not in raw and len(raw) < RPC_MAX_BYTES:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                raw += chunk
            try:
                req = json.loads(raw.split(b"\n", 1)[0].decode("utf-8"))
                op, args = req["op"], req.get("args", {})
                if not isinstance(op, str) or not isinstance(args, dict):
                    raise ValueError("bad request")
            except (ValueError, KeyError, UnicodeDecodeError):
                conn.sendall(b'{"ok":false,"code":400,"message":"Bad request."}\n')
                return
            fd = None
            try:
                result, fd = self._run(op, args, conn)
                payload = json.dumps(dict(result, ok=True)).encode("utf-8") + b"\n"
            except PrivError as exc:
                payload = json.dumps({"ok": False, "code": exc.code, "message": exc.msg}).encode("utf-8") + b"\n"
            except Exception as exc:
                log(f"helper: error in {op}: {exc!r}")
                payload = b'{"ok":false,"code":500,"message":"Internal error in the helper."}\n'
            try:
                if fd is not None:
                    socket.send_fds(conn, [payload], [fd])
                else:
                    conn.sendall(payload)
            finally:
                if fd is not None:
                    os.close(fd)
        except OSError:
            pass
        finally:
            conn.close()
            self.slots.release()

    def _run(self, op, args, conn):
        p = self.priv
        who = _clean_text(args.get("who"))
        if op == "ping":
            return {}, None
        if op == "verify":
            pw = args.get("password")
            if not isinstance(pw, str) or not pw or len(pw) > 1024 or "\0" in pw:
                return {"valid": False}, None
            return {"valid": p.verify(pw)}, None
        if op == "spawn":
            info = p.spawn(args.get("kind"), args.get("prog"), _clamp(args.get("rows"), 2, 500, 24),
                           _clamp(args.get("cols"), 2, 500, 80))
            return {"pid": info["pid"], "label": info["label"]}, info["fd"]
        if op == "signal":
            p.signal(_clamp(args.get("pid"), 1, 2 ** 31 - 1, 0), str(args.get("name")))
            return {}, None
        if op == "wait":
            conn.settimeout(None)
            return {"code": p.wait(_clamp(args.get("pid"), 1, 2 ** 31 - 1, 0))}, None
        if op == "install":
            return {"job": p.install(args.get("pkg"), who)}, None
        if op == "job":
            return {"job": p.job_view()}, None
        if op == "set_port":
            return {"restarting": p.set_port(args.get("port"), who)}, None
        if op == "set_hosts":
            return {"hosts": p.set_hosts(args.get("hosts"), who)}, None
        if op == "set_shell_user":
            return p.set_shell_user(args.get("user"), args.get("password"), who), None
        if op == "set_web_user":
            return {"restarting": p.set_web_user(args.get("name"), who)}, None
        if op == "set_option":
            return {"value": p.set_option(args.get("name"), args.get("value"), who)}, None
        if op == "regen_cert":
            return p.regen_cert(who), None
        if op == "account":
            return {"info": dict(p.account_info(), split=True)}, None
        raise PrivError(400, "Unknown request.")


class RemoteBackend:
    split = True

    def __init__(self, path):
        self.path = path

    def _call(self, op, args=None, want_fd=False, timeout=30):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        fds = []
        try:
            try:
                s.connect(self.path)
                s.sendall(json.dumps({"op": op, "args": args or {}}).encode("utf-8") + b"\n")
                if want_fd:
                    data, fds, _, _ = socket.recv_fds(s, RPC_MAX_BYTES, 1)
                else:
                    data = b""
                    while not data.endswith(b"\n") and len(data) < RPC_MAX_BYTES:
                        chunk = s.recv(65536)
                        if not chunk:
                            break
                        data += chunk
            except (OSError, ValueError):
                raise PrivError(503, "The Terminal Monitor helper is not running.")
        finally:
            s.close()
        try:
            res = json.loads(data.decode("utf-8"))
        except ValueError:
            for fd in fds:
                os.close(fd)
            raise PrivError(502, "The helper sent a bad reply.")
        if not res.get("ok"):
            for fd in fds:
                os.close(fd)
            raise PrivError(int(res.get("code", 500)), str(res.get("message", "The helper refused.")))
        if want_fd:
            if not fds:
                raise PrivError(502, "The helper sent no terminal.")
            res["fd"] = fds[0]
            for extra in fds[1:]:
                os.close(extra)
        return res

    def available(self):
        try:
            self._call("ping")
            return True
        except PrivError:
            return False

    def ping(self):
        return self.available()

    def verify(self, password):
        return bool(self._call("verify", {"password": password})["valid"])

    def spawn(self, kind, prog, rows, cols):
        res = self._call("spawn", {"kind": kind, "prog": prog, "rows": rows, "cols": cols}, want_fd=True)
        return {"pid": res["pid"], "fd": res["fd"], "label": res["label"]}

    def signal(self, pid, name):
        self._call("signal", {"pid": pid, "name": name})

    def wait(self, pid):
        return self._call("wait", {"pid": pid}, timeout=None)["code"]

    def install(self, pkg, who=""):
        return self._call("install", {"pkg": pkg, "who": who})["job"]

    def job_view(self):
        return self._call("job")["job"]

    def set_port(self, port, who=""):
        return self._call("set_port", {"port": port, "who": who})["restarting"]

    def set_hosts(self, names, who=""):
        return self._call("set_hosts", {"hosts": names, "who": who})["hosts"]

    def set_shell_user(self, user, password, who=""):
        res = self._call("set_shell_user", {"user": user, "password": password, "who": who})
        return {"account": res["account"], "sudo": res["sudo"]}

    def set_web_user(self, name, who=""):
        return self._call("set_web_user", {"name": name, "who": who})["restarting"]

    def set_option(self, name, value, who=""):
        return self._call("set_option", {"name": name, "value": value, "who": who})["value"]

    def regen_cert(self, who=""):
        res = self._call("regen_cert", {"who": who})
        return {"restarting": res["restarting"], "sha256": res["sha256"]}

    def account_info(self):
        return self._call("account")["info"]


_ASSET_RAW = {
    "xterm.js": ("application/javascript; charset=utf-8", "f0aea0f75f48559013ae6643c2479dd737d26da42d5524e6d2b70915ae6523c7", """
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
+YyIWykrSTkuQJoVJOg+hf+FRg1cmG+T61qY7sj7SSKlGJwCxj3NFbq1lcp3NzxFW2m9wQUq/QbpQif2Oq/MdZ42F3jZQv9G3FV8
0VKWNidt1TVfvc9uHMMW0aTPz2gV76swcFcovRV21m1hd0kLfOrDmprNmEEVqQnN1tZmurU1MCIjB3Rxw56FUuVhFfTDcB8ZNNvz
KNXIJINITZ/K0wPjaWg8xUbXoRd9JnwCHxhB+0GxHXeeIzPiv19zRZIwYqKUyUIzUs2PlEUzNRaEU97FAwYFfu0oIyjVcGkQO8pX
AUrpQtLPaq1sQ1ayUV+dyrB7Vkz/glwDdwt2oQ9pj/kwfWSp7HYwOTVeDX9fQM6Tl387OXt+ePzyzeufX+KF8Ou3Z+/eHx69Pvk7
PLkPWc2QnY8Hg0dwoPSV39l7Epmge3uNtlGaf5UW5CL/dneHD2/IZTK+fTm5JAcd5pnUGXbSCckvi+R6Cvy6jvBa2xnVVsrZe0/2
+j/uY3Rush/Dw96P94kT6w43BAhacqSCEmn5gaAOFGS2yfv8huk3/zS7vZ7Sj41XNJnt64tXyay8VQKR8VYZJrBgsqSZAZf2fuNq
jiYELAvuBVZVdqqkjhzNp1Frh/WGFX53+hp+d54g4GVocQDCSdNtLuSHp4+e7IgGnj7eHdTozuCfEwlBAFjAiWy4YJ7pwwUVk9B8
mojM2mhf5HhfRyzoxD2qRsjwmu9F5m50fQP4uH4f7T3+HtFZHsjw0DRT1GK9bxGhzThtfAfFrAUI4HA2o3lslVWEecgTeaqZVKBO
hxy4ZQ0hemd8QosI/cPaTaPF5IWylhTfrfw5DbAHn/qRMDnXO8N1fWZj/GVSKPMPGq4aFgq9RZiIU7wOaegA5OjtS5ozRThyNPoZ
igjY6wR1E04T1DzRb0V5OhLNmr0MVRIHfUBcD9iGBUuhY4LF6NXemRyp+MCekR6Q//B9iuP+wRIMWV0ZnG7rcXG9cWBCwNLwk7/l
7wOOoD0QTmv33LwRGSfs2WEaDTewf+u0/DuxIw15SZNtUIsZFxpOa33l6x/ruo1425AkbMnd2izm+oR3r9D8s4qqmAifEKYVEs5B
wqELTau0Lc7JcwI39roxcYy7UZzhwlfYVXa/fxAoQV/j5jTvSeDni40uMlNu5ydUuKNhOO59Oz/+Yen6e0mdZ0WPbdq4UjvWXEbo
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
/w/8/bD5DFMEAA==
"""),
    "xterm.css": ("text/css; charset=utf-8", "832f3f2c603b43ad4351ff04970150cc7a873014276db126a6065c6dd81e4872", """
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
AAA=
"""),
    "addon-fit.js": ("application/javascript; charset=utf-8", "10f3194c5f17c1786fb7d5db865c1ec8539b6736a318063fd38bdaaf7c46848f", """
H4sIAAAAAAACA5VU247TMBB95yvaIFW2SN3CYyNTcZWQ2AWxAh4QqrzxZOvFiSN7elmS/Dt20m636YJKHmJ75sycM6Oxh9mqSFGZ
gkCMtIrM9S2kGHGOdyWYbADb0lh0o9GJJzdypWHeLWyH40joLNrnPIAlZKqA0ahbmcjlvNuSHz897+xvvPPdyt4rfCWlKVoCODo2
xIHOYkIof9n+qmjlYODQKp8xWQs7AF41iQVc2aJDBCNySD61tKzT8tmaEizeEYyjxQLcRVtaFHu0XsFsOG1ojAfqtVFyMH1oSbVw
rhK+9rVAIEArXCrHFgg2V4XQHBqpXGkcEFo1mfLiq9QUDr3AFll6Bd77VuVQON9AR2iiMjKEuh4ep6pr5S7FJQGWGu3o4WjNxlHa
1Zp0yZEfx7JFaiwkPWMI5Jx3GUajnjewtN6wqWuCbGGhkGCvwK5V6u0ahCW+Qb2s4NRv2MmM9/KaRwqtQqHH0fsyTj0MNPhQPOnL
3sFK4fXhu+503A94tB+xn4d+UfJeX9Aw9Q1AljrHUtCabZTEZV33rEtQN8seoeUt6JjUlOGKOOZSa7S+Fumv+dRP9lrBJoz8zv5a
2O+BJ1Z8owppNuwG8I3JyxWCvMI7DeSsBsSGe4ODDwUSFXLsh/1bmG0SdbIjSmPHLwQuWS62ZBr/M6ZtgA+hcfGf4misuRmT++zF
I9lLIaUqbsZoSs/x7CzstUE0eStJcHcmgd1Vfh6FhiyA6djuHpQqTPbsvmcv4nabaWMsEZP+vHhl4Qoc8M8f4vXkdJJo4z/qbxaE
P6XJk8nk6cCZlU3hQpSlF/X1y0e+DT0ei/AOjf3Lwm6dT1/+Af32InrfBQAA
"""),
}

_asset_cache = {}


def _asset(name):
    if name not in _ASSET_RAW:
        return None
    if name not in _asset_cache:
        ctype, sha, b64 = _ASSET_RAW[name]
        raw = gzip.decompress(base64.b64decode("".join(b64.split())))
        if hashlib.sha256(raw).hexdigest() != sha:
            log(f"asset {name} failed its checksum; not served")
            return None
        _asset_cache[name] = (ctype, raw)
    return _asset_cache[name]


def _token_of(h):
    raw = h.headers.get("Cookie", "")
    try:
        jar = http.cookies.SimpleCookie()
        jar.load(raw)
    except http.cookies.CookieError:
        return ""
    m = jar.get(_cookie_name(h))
    return m.value if m else ""


def _is_tls(h):
    return isinstance(h.connection, ssl.SSLSocket)


def _cookie_name(h):
    return ("__Host-" if _is_tls(h) else "") + SESSION_COOKIE


def _set_cookie(h, token, clear=False):
    parts = [f"{_cookie_name(h)}={'' if clear else token}", "Path=/", "HttpOnly", "SameSite=Strict"]
    if _is_tls(h):
        parts.append("Secure")
    if clear:
        parts.append("Max-Age=0")
    return ("Set-Cookie", "; ".join(parts))


def _need(h, touch=True):
    tok = _token_of(h)
    if not _session_valid(tok, touch=touch, ip=h._peer()):
        raise HttpErr(401, "Sign in first.")
    return tok


def _host_only(h):
    host = h.headers.get("Host", "")
    if not host:
        return socket.gethostname()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def pw_eye_html(input_id, nonce=""):
    import json
    attr = ' nonce="%s"' % nonce if nonce else ""
    css = (
        ".pw-wrap{position:relative;display:block}"
        ".pw-wrap>input{box-sizing:border-box;width:100%;padding-right:2.7rem}"
        ".pw-wrap>.pw-eye{position:absolute!important;top:50%!important;right:.3rem!important;transform:translateY(-50%)!important;"
        "width:2.1rem!important;height:2.1rem!important;min-width:0!important;min-height:0!important;margin:0!important;padding:0!important;"
        "border:0!important;border-radius:4px!important;background:transparent!important;color:inherit!important;opacity:.7;"
        "cursor:pointer;box-shadow:none!important;filter:none!important;text-shadow:none!important;text-transform:none!important;"
        "letter-spacing:0!important;font-size:1rem!important;line-height:1!important;display:flex!important;align-items:center!important;"
        "justify-content:center!important}"
        ".pw-wrap>.pw-eye:hover,.pw-wrap>.pw-eye:focus-visible{opacity:1;background:rgba(127,127,127,.2)!important;box-shadow:none!important;filter:none!important}"
        ".pw-wrap>.pw-eye:active{transform:translateY(-50%)!important}"
        ".pw-eye svg{width:1.25rem;height:1.25rem;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;"
        "stroke-linejoin:round;pointer-events:none}"
        ".pw-eye .pw-off{display:none}"
        '.pw-eye[aria-pressed="true"] .pw-on{display:none}'
        '.pw-eye[aria-pressed="true"] .pw-off{display:block}'
    )
    js = (
        "(function(){var ID=" + json.dumps(input_id).replace("</", "<\\/") + ";"
        "function go(){var input=document.getElementById(ID);if(!input||input.getAttribute('data-pw-eye'))return;"
        "input.setAttribute('data-pw-eye','1');"
        "var wrap=document.createElement('span');wrap.className='pw-wrap';"
        "input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);"
        "var b=document.createElement('button');b.type='button';b.className='pw-eye';"
        "b.innerHTML='<svg class=\"pw-on\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z\"/>"
        "<circle cx=\"12\" cy=\"12\" r=\"3\"/></svg><svg class=\"pw-off\" viewBox=\"0 0 24 24\" aria-hidden=\"true\">"
        "<path d=\"M17.9 17.9A10.9 10.9 0 0 1 12 19C5 19 1 12 1 12a18.5 18.5 0 0 1 5.1-5.9M9.9 5.1A10.9 10.9 0 0 1 12 5c7 0 11 7 11 7"
        "a18.5 18.5 0 0 1-2.2 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2\"/><path d=\"M1 1l22 22\"/></svg>';"
        "function show(on){input.type=on?'text':'password';b.setAttribute('aria-pressed',on?'true':'false');"
        "var t=on?'Hide password':'Show password';b.setAttribute('aria-label',t);b.title=t;}"
        "show(false);"
        "b.addEventListener('mousedown',function(e){e.preventDefault();});"
        "b.addEventListener('click',function(){show(input.type==='password');input.focus();});"
        "if(input.form)input.form.addEventListener('submit',function(){show(false);});"
        "document.addEventListener('visibilitychange',function(){if(document.hidden)show(false);});"
        "window.addEventListener('pagehide',function(){show(false);});"
        "wrap.appendChild(b);}"
        "if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go();})();"
    )
    return "<style%s>%s</style><script%s>%s</script>" % (attr, css, attr, js)


def pw_eye_inject(html, input_id, nonce=""):
    head, sep, tail = html.rpartition("</body>")
    if not sep:
        return html
    return head + pw_eye_html(input_id, nonce) + sep + tail


def r_page(h, q):
    nonce = secrets.token_urlsafe(18)
    body = pw_eye_inject(PAGE.replace("__NONCE__", nonce), "pw", nonce)
    h._send(200, "text/html; charset=utf-8", body.encode("utf-8"), csp=_csp(nonce))


def r_static(h, name):
    a = _asset(name)
    if a is None:
        raise HttpErr(404, "Not found.")
    h._send(200, a[0], a[1])


def r_health(h, q):
    h._json(200, {"ok": True})


def r_whoami(h, q):
    h._json(200, {"ok": True, "logged_in": _session_valid(_token_of(h), ip=h._peer())})


def r_login(h, q):
    ip = h._peer()
    wait = _lock_remaining(ip)
    if wait:
        raise HttpErr(429, f"Too many attempts. Wait {wait} seconds.")
    body = h._body()
    pw = body.get("password", "")
    if not isinstance(pw, str) or not pw or len(pw) > 1024 or "\0" in pw:
        raise HttpErr(400, "Enter the password.")
    delay = 0.0
    with _login_lock:
        wait = _lock_remaining(ip)
        if wait:
            raise HttpErr(429, f"Too many attempts. Wait {wait} seconds.")
        ok = bool(_priv(BACKEND.verify, pw))
        if ok:
            _record_ok(ip)
        else:
            _record_fail(ip)
            delay = _global_delay()
    if not ok:
        audit(f"login: failed sign-in from {ip}")
        if delay:
            time.sleep(delay)
        raise HttpErr(401, "Incorrect password.")
    tok = _issue_session(ip)
    audit(f"login: signed in from {ip}")
    h._json(200, {"ok": True}, extra=[_set_cookie(h, tok)])


def r_logout(h, q):
    _revoke_session(_token_of(h))
    h._json(200, {"ok": True}, extra=[_set_cookie(h, "", clear=True)])


def r_setup(h, q):
    _need(h)
    cfg = load_config()
    installed = {name: shutil.which(binary) is not None for name, binary in
                 (("top", "top"), ("htop", "htop"), ("btop", "btop"))}
    helper = True
    try:
        account = BACKEND.account_info()
        job = BACKEND.job_view()
    except PrivError:
        helper = False
        account = {"account": cfg["shell_user"] or "root", "sudo": "unknown", "web_user": cfg["web_user"],
                   "split": getattr(BACKEND, "split", False)}
        job = _job_view()
    h._json(200, {"ok": True, "installed": installed, "port": cfg["port"],
                  "monitor_last": cfg["monitor_last"], "helper": helper, "account": account,
                  "cert": {"https": cfg["https"], "sha256": _cert_fingerprint() if cfg["https"] else ""},
                  "options": {"bind_session_ip": _BIND_IP},
                  "limits": {"idle_sec": SESSION_TTL_SEC, "max_sec": SESSION_MAX_SEC},
                  "hosts": {"own": sorted(_OWN_NAMES), "extra": sorted(_EXTRA_HOSTS)},
                  "job": job, "version": VERSION})


def r_setup_install(h, q):
    _need(h)
    body = h._body()
    if body.get("confirm") is not True:
        raise HttpErr(400, "Confirmation required.")
    jid = _priv(BACKEND.install, body.get("pkg"), h._peer())
    h._json(200, {"ok": True, "job": jid})


def r_setup_port(h, q):
    _need(h)
    body = h._body()
    if body.get("confirm") is not True:
        raise HttpErr(400, "Confirmation required.")
    port = _norm_port(body.get("port"))
    if port is None:
        raise HttpErr(400, "Use a port from 1024 to 65535.")
    restarting = _priv(BACKEND.set_port, port, h._peer())
    scheme = "https" if _is_tls(h) else "http"
    h._json(200, {"ok": True, "url": f"{scheme}://{_host_only(h)}:{port}/", "restarting": bool(restarting)})


def r_setup_hosts(h, q):
    global _EXTRA_HOSTS
    _need(h)
    body = h._body()
    if body.get("confirm") is not True:
        raise HttpErr(400, "Confirmation required.")
    raw = body.get("hosts", "")
    if not isinstance(raw, str) or len(raw) > 2000:
        raise HttpErr(400, "Names must be text.")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    if len(items) > MAX_ALLOWED_HOSTS:
        raise HttpErr(400, f"At most {MAX_ALLOWED_HOSTS} names.")
    names = _priv(BACKEND.set_hosts, items, h._peer())
    _EXTRA_HOSTS = frozenset(names)
    h._json(200, {"ok": True, "hosts": names})


def r_setup_shell_user(h, q):
    _need(h)
    ip = h._peer()
    wait = _lock_remaining(ip)
    if wait:
        raise HttpErr(429, f"Too many attempts. Wait {wait} seconds.")
    body = h._body()
    if body.get("confirm") is not True:
        raise HttpErr(400, "Confirmation required.")
    user, pw = body.get("user", ""), body.get("password", "")
    if not isinstance(user, str) or not isinstance(pw, str):
        raise HttpErr(400, "Send the user name and its password as text.")
    try:
        res = BACKEND.set_shell_user(user, pw, ip)
    except PrivError as exc:
        if exc.code == 401:
            _record_fail(ip)
        raise HttpErr(exc.code, exc.msg)
    _record_ok(ip)
    with _sess_lock:
        _sessions.clear()
    _close_all_sessions()
    h._json(200, {"ok": True, "account": res["account"], "sudo": res["sudo"]},
            extra=[_set_cookie(h, "", clear=True)])


def r_setup_web_user(h, q):
    _need(h)
    body = h._body()
    if body.get("confirm") is not True:
        raise HttpErr(400, "Confirmation required.")
    name = body.get("name", "")
    if not isinstance(name, str):
        raise HttpErr(400, "Send the user name as text.")
    restarting = _priv(BACKEND.set_web_user, name, h._peer())
    h._json(200, {"ok": True, "restarting": bool(restarting)})


def r_logout_all(h, q):
    _need(h)
    with _sess_lock:
        _sessions.clear()
    _close_all_sessions()
    audit(f"session: every sign-in ended (requested from {h._peer()})")
    h._json(200, {"ok": True}, extra=[_set_cookie(h, "", clear=True)])


def r_setup_options(h, q):
    global _BIND_IP
    _need(h)
    body = h._body()
    if body.get("confirm") is not True:
        raise HttpErr(400, "Confirmation required.")
    value = body.get("bind_session_ip")
    if not isinstance(value, bool):
        raise HttpErr(400, "Send true or false.")
    _priv(BACKEND.set_option, "bind_session_ip", value, h._peer())
    _BIND_IP = value
    h._json(200, {"ok": True, "bind_session_ip": value})


def r_setup_cert(h, q):
    _need(h)
    body = h._body()
    if body.get("confirm") is not True:
        raise HttpErr(400, "Confirmation required.")
    res = _priv(BACKEND.regen_cert, h._peer())
    h._json(200, {"ok": True, "restarting": bool(res["restarting"]), "sha256": res["sha256"]})


def r_cert_pem(h, q):
    _need(h)
    try:
        with open(TLS_CERT, "rb") as fh:
            data = fh.read()
    except OSError:
        raise HttpErr(404, "There is no certificate (HTTPS is off).")
    h._send(200, "application/x-pem-file", data, extra=[("Content-Disposition", 'attachment; filename="termon.pem"')])


def r_term_ticket(h, q):
    tok = _need(h)
    h._json(200, {"ok": True, "ticket": _issue_ticket(tok)})


def r_term_open(h, q):
    tok = _need(h)
    body = h._body()
    if not _take_ticket(str(body.get("ticket", "")), tok):
        raise HttpErr(403, "Ticket missing, used or expired. Reload the page.")
    kind = body.get("kind")
    rows = _clamp(body.get("rows"), 2, 500, 24)
    cols = _clamp(body.get("cols"), 2, 500, 80)
    prog = body.get("prog")
    if kind not in ("shell", "monitor"):
        raise HttpErr(400, "Unknown terminal kind.")
    if kind == "monitor" and (not isinstance(prog, str) or prog not in MONITOR_PROGS):
        raise HttpErr(400, "Unknown program.")
    sess = _start_session(kind, prog, rows, cols, _digest(tok), h._peer())
    h._json(200, {"ok": True, "sid": sess.sid, "label": sess.label})


def r_term_stream(h, q):
    tok = _need(h, touch=False)
    sess = _get_session(q.get("sid", [""])[0], tok)
    after = _clamp(q.get("after", ["0"])[0], 0, 2 ** 62, 0)
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache, no-transform")
    h.send_header("X-Accel-Buffering", "no")
    h.send_header("Connection", "close")
    for k, v in SEC_HEADERS.items():
        h.send_header(k, v)
    h.send_header("Content-Security-Policy", _csp())
    h.end_headers()
    sess.attach()
    try:
        _stream_loop(h, sess, tok, after)
    finally:
        sess.detach()


def _stream_loop(h, sess, tok, after):
    last = after
    while True:
        with sess.cond:
            pending = [c for c in sess.ring if c[0] > last]
            if not pending and sess.alive:
                sess.cond.wait(STREAM_PING_SEC)
                pending = [c for c in sess.ring if c[0] > last]
            alive = sess.alive
            code = sess.exit_code
        for seq, data in pending:
            payload = json.dumps({"seq": seq, "d": base64.b64encode(data).decode("ascii")})
            h.wfile.write(f"event: out\ndata: {payload}\n\n".encode("utf-8"))
            last = seq
        if not pending and alive:
            h.wfile.write(b": ping\n\n")
        h.wfile.flush()
        if not alive and not pending:
            h.wfile.write(f"event: exit\ndata: {json.dumps({'code': code})}\n\n".encode("utf-8"))
            h.wfile.flush()
            return
        if not _session_valid(tok, touch=False, ip=h._peer()):
            _sweep()
            return


def r_term_info(h, q):
    tok = _need(h)
    sess = _get_session(q.get("sid", [""])[0], tok)
    h._json(200, {"ok": True, "alive": sess.alive, "code": sess.exit_code})


def r_term_input(h, q):
    tok = _need(h)
    body = h._body()
    sess = _get_session(body.get("sid"), tok)
    data = body.get("data", "")
    if not isinstance(data, str):
        raise HttpErr(400, "Input must be text.")
    if len(data) > TERM_INPUT_MAX:
        raise HttpErr(413, "Input too large.")
    if not sess.write(data.encode("utf-8", "replace")):
        raise HttpErr(410, "The terminal has ended.")
    h._json(200, {"ok": True})


def r_term_resize(h, q):
    tok = _need(h)
    body = h._body()
    sess = _get_session(body.get("sid"), tok)
    sess.resize(_clamp(body.get("rows"), 2, 500, 24), _clamp(body.get("cols"), 2, 500, 80))
    h._json(200, {"ok": True})


def r_term_close(h, q):
    tok = _need(h)
    body = h._body()
    sess = _get_session(body.get("sid"), tok)
    sess.close()
    with _pty_lock:
        _ptys.pop(sess.sid, None)
    h._json(200, {"ok": True})


GET_ROUTES = {
    "/": r_page,
    "/api/health": r_health,
    "/api/whoami": r_whoami,
    "/api/setup": r_setup,
    "/api/term/stream": r_term_stream,
    "/api/term/info": r_term_info,
    "/api/cert.pem": r_cert_pem,
}
POST_ROUTES = {
    "/api/login": r_login,
    "/api/logout": r_logout,
    "/api/logout_all": r_logout_all,
    "/api/setup/install": r_setup_install,
    "/api/setup/port": r_setup_port,
    "/api/setup/hosts": r_setup_hosts,
    "/api/setup/shell_user": r_setup_shell_user,
    "/api/setup/web_user": r_setup_web_user,
    "/api/setup/options": r_setup_options,
    "/api/setup/cert": r_setup_cert,
    "/api/term/ticket": r_term_ticket,
    "/api/term/open": r_term_open,
    "/api/term/input": r_term_input,
    "/api/term/resize": r_term_resize,
    "/api/term/close": r_term_close,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "http"
    sys_version = ""
    timeout = REQ_TIMEOUT_SEC

    def log_message(self, fmt, *args):
        return

    def __getattr__(self, name):
        if name.startswith("do_") and len(name) > 3:
            method = name[3:]
            return lambda: self._dispatch(method)
        raise AttributeError(name)

    def send_error(self, code, message=None, explain=None):
        body = json.dumps({"ok": False, "message": message or "Request refused."}).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            for k, v in SEC_HEADERS.items():
                self.send_header(k, v)
            self.send_header("Content-Security-Policy", _csp())
            self.end_headers()
            if self.command != "HEAD" and code >= 200 and code not in (204, 304):
                self.wfile.write(body)
        except OSError:
            pass
        self.close_connection = True

    def _send(self, code, ctype, body, extra=(), csp=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in SEC_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Security-Policy", csp or _csp())
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj, extra=()):
        self._send(code, "application/json; charset=utf-8", json.dumps(obj).encode("utf-8"), extra)

    def _peer(self):
        return self.client_address[0]

    def _body(self):
        ctype = self.headers.get("Content-Type", "")
        if not ctype.lower().startswith("application/json"):
            raise HttpErr(415, "Send JSON.")
        lengths = self.headers.get_all("Content-Length") or ["0"]
        if len(lengths) != 1 or not (lengths[0].isascii() and lengths[0].isdigit()):
            raise HttpErr(400, "Bad Content-Length.")
        n = int(lengths[0])
        if n > MAX_JSON_BYTES:
            raise HttpErr(413, "Request too large.")
        raw = self.rfile.read(n) if n else b""
        try:
            obj = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise HttpErr(400, "Bad JSON.")
        if not isinstance(obj, dict):
            raise HttpErr(400, "Expected a JSON object.")
        return obj

    def _gate(self):
        for name in _PROXY_HEADERS:
            if self.headers.get(name) is not None:
                raise HttpErr(403, "Refused: proxied requests are not allowed.")
        if not _is_lan(self._peer()):
            raise HttpErr(403, f"{APP_NAME} is LAN only. This address is not on the local network.")
        if not _host_ok(self.headers.get_all("Host")):
            log(f"refused request from {self._peer()}: Host header not allowed")
            raise HttpErr(403, "This address is not allowed. Open this node by its IP address.", html=True)
        if self.headers.get("Transfer-Encoding") is not None:
            raise HttpErr(501, "Transfer-Encoding is not supported.")

    def _check_origin(self):
        if (self.headers.get("X-Requested-With") or "") != "XMLHttpRequest":
            raise HttpErr(403, "Refused: missing X-Requested-With header.")
        origins = self.headers.get_all("Origin") or []
        sites = self.headers.get_all("Sec-Fetch-Site") or []
        if len(origins) > 1 or len(sites) > 1:
            raise HttpErr(403, "Refused: cross-site request.")
        if sites and sites[0].strip().lower() != "same-origin":
            log(f"refused POST from {self._peer()}: Sec-Fetch-Site {sites[0][:30]!r}")
            raise HttpErr(403, "Refused: cross-site request.")
        if origins:
            want = ("https" if _is_tls(self) else "http") + "://" + (self.headers.get("Host") or "")
            if origins[0].strip().lower() != want.strip().lower():
                log(f"refused POST from {self._peer()}: Origin {origins[0][:60]!r}")
                raise HttpErr(403, "Refused: cross-site request.")

    def _dispatch(self, method):
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        q = urllib.parse.parse_qs(url.query)
        try:
            self._gate()
            if method not in ("GET", "POST"):
                raise HttpErr(405, "Method not allowed.", headers=[("Allow", "GET, POST")])
            if method == "POST":
                self._check_origin()
            if method == "GET" and path.startswith("/static/"):
                return r_static(self, path[len("/static/"):])
            fn = (GET_ROUTES if method == "GET" else POST_ROUTES).get(path)
            if fn is None:
                raise HttpErr(404, "Not found.")
            fn(self, q)
        except HttpErr as exc:
            try:
                if exc.html and not path.startswith("/api/"):
                    self._send(exc.code, "text/html; charset=utf-8", HOST_REFUSED_PAGE.encode("utf-8"))
                else:
                    self._json(exc.code, {"ok": False, "message": exc.msg}, extra=exc.headers)
            except OSError:
                pass
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            log(f"error on {method} {path}: {exc!r}")
            try:
                self._json(500, {"ok": False, "message": "Internal error. See the journal."})
            except OSError:
                pass


_lock_fh = None
_TERMON_CMD = re.compile(r"^termon([-_].*)?\.py$")


def acquire_instance_lock(path=None):
    global _lock_fh
    path = path or LOCK_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = open(path, "a+")
    except OSError as exc:
        log(f"cannot open {path}: {exc}")
        return False
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()) + "\n")
    fh.flush()
    _lock_fh = fh
    return True


def _proc_table():
    table = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
                stat = fh.read()
            ppid = int(stat[stat.rindex(")") + 2:].split()[1])
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
        except (OSError, ValueError, IndexError):
            continue
        table[pid] = (ppid, argv)
    return table


def _ancestors(table, pid):
    out, cur = set(), pid
    while cur in table and cur not in out and cur > 1:
        out.add(cur)
        cur = table[cur][0]
    return out


def _is_termon_cmd(argv):
    return any(_TERMON_CMD.match(os.path.basename(a)) for a in argv)


def _is_termon_server(argv):
    if not argv or not os.path.basename(argv[0]).startswith("python"):
        return False
    if any(a in ("--install", "--uninstall") for a in argv):
        return False
    return _is_termon_cmd(argv)


def _inside_termon():
    table = _proc_table()
    me = os.getpid()
    return any(pid in table and _is_termon_server(table[pid][1]) for pid in _ancestors(table, me))


def _kill_other_termons():
    table = _proc_table()
    me = os.getpid()
    keep = _ancestors(table, me)
    roots = [p for p, (_, argv) in table.items() if p not in keep and _is_termon_server(argv)]
    if not roots:
        return 0
    children = {}
    for pid, (ppid, _) in table.items():
        children.setdefault(ppid, []).append(pid)
    kids, stack = set(), list(roots)
    while stack:
        for c in children.get(stack.pop(), []):
            if c not in keep and c not in roots and c not in kids:
                kids.add(c)
                stack.append(c)
    for pid in roots:
        log(f"removing old instance pid {pid}")
        _signal(pid, signal.SIGTERM)
    for pid in kids:
        _signal(pid, signal.SIGHUP)
    deadline = time.time() + 3
    everyone = roots + list(kids)
    while time.time() < deadline and any(_alive(p) for p in everyone):
        time.sleep(0.1)
    for pid in everyone:
        if _alive(pid):
            _signal(pid, signal.SIGKILL)
    return len(roots)


def _signal(pid, sig):
    try:
        os.kill(pid, sig)
    except OSError:
        pass


def _alive(pid):
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


_UNIT_NAME_RE = re.compile(r"^termon(-[A-Za-z0-9_.@-]+)?\.service$")
_UNIT_DIRS = ("/etc/systemd/system", "/lib/systemd/system", "/usr/lib/systemd/system")


def _is_termon_unit_file(path):
    if os.path.islink(path):
        return True
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(65536)
    except OSError:
        return False
    return any(line.startswith("ExecStart=") and "termon" in line for line in text.splitlines())


def _remove_existing():
    units = {SERVICE_NAME}
    r = _systemctl("list-unit-files", "--no-legend", "--plain", "termon*.service")
    for line in r.stdout.splitlines():
        parts = line.split()
        if parts and _UNIT_NAME_RE.match(parts[0]):
            units.add(parts[0])
    for unit in sorted(units):
        _systemctl("disable", "--now", unit)
    for folder in _UNIT_DIRS:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if _UNIT_NAME_RE.match(name) and _is_termon_unit_file(path):
                log(f"removing unit file {path}")
                os.unlink(path)
    _kill_other_termons()
    for path in (INSTALL_BIN_PATH, INSTALL_BIN_PATH + ".new"):
        if os.path.lexists(path):
            os.unlink(path)
    shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    _systemctl("daemon-reload")


def _refuse_inside_termon(action):
    if _inside_termon():
        sys.exit(f"{action} would stop the Terminal Monitor shell you are running it from. "
                 "Run it over SSH or another terminal instead.")


_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")


def _lan_ips():
    ips = {"127.0.0.1"}
    try:
        r = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3)
        ips.update(x for x in r.stdout.split() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", x))
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            ips.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(ips)


def ensure_tls_cert():
    if os.path.exists(TLS_CERT) and os.path.exists(TLS_KEY):
        return True
    openssl = shutil.which("openssl")
    if not openssl:
        log("openssl not found: cannot create the HTTPS certificate")
        return False
    host = socket.gethostname().split(".")[0]
    if not _HOSTNAME_RE.match(host):
        host = "termon"
    try:
        os.makedirs(TLS_DIR, mode=0o700, exist_ok=True)
        os.chmod(TLS_DIR, 0o700)
    except OSError as exc:
        log(f"cannot create {TLS_DIR}: {exc}")
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
        log(f"openssl failed: {exc}")
        return False
    finally:
        os.umask(old_umask)
    if r.returncode != 0 or not (os.path.exists(key_tmp) and os.path.exists(cert_tmp)):
        log(f"openssl failed: {r.stderr.strip()[:300]}")
        for p in (key_tmp, cert_tmp):
            try:
                os.unlink(p)
            except OSError:
                pass
        return False
    os.chmod(key_tmp, 0o600)
    os.chmod(cert_tmp, 0o644)
    os.replace(key_tmp, TLS_KEY)
    os.replace(cert_tmp, TLS_CERT)
    log(f"created a self-signed HTTPS certificate for {host} ({san})")
    return True


def _cert_fingerprint():
    try:
        with open(TLS_CERT, encoding="ascii") as fh:
            der = ssl.PEM_cert_to_DER_cert(fh.read())
    except (OSError, ValueError):
        return ""
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def make_ssl_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(TLS_CERT, TLS_KEY)
    return ctx


class LimitedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, *args, ssl_ctx=None, **kwargs):
        self._slots = threading.BoundedSemaphore(MAX_CONNS)
        self.ssl_ctx = ssl_ctx
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not _is_lan(client_address[0]) or not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            if self.ssl_ctx is not None:
                try:
                    request.settimeout(REQ_TIMEOUT_SEC)
                    request = self.ssl_ctx.wrap_socket(request, server_side=True)
                except (ssl.SSLError, OSError):
                    try:
                        request.close()
                    except OSError:
                        pass
                    return
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def sd_notify(msg):
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr[0] == "@":
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(msg.encode("utf-8"))
    except OSError as exc:
        log(f"sd_notify failed: {exc}")


def _start_watchdog():
    usec = os.environ.get("WATCHDOG_USEC")
    if not usec:
        return
    try:
        interval = max(1.0, int(usec) / 2_000_000)
    except ValueError:
        return

    def loop():
        while True:
            sd_notify("WATCHDOG=1")
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()


def _systemctl(*args):
    return subprocess.run(["systemctl", *args], capture_output=True, text=True)


def _require_root(action):
    if os.geteuid() != 0:
        sys.exit(f"{action} needs root (use sudo).")


def _web_unit_text(user):
    return (f"[Unit]\n"
            f"Description={APP_NAME} v{VERSION} (LAN only, web side)\n"
            f"After=network-online.target {HELPER_SERVICE}\n"
            f"Wants=network-online.target\n"
            f"Requires={HELPER_SERVICE}\n\n"
            f"[Service]\n"
            f"Type=notify\n"
            f"User={user}\n"
            f"ExecStart={PYTHON_BIN} {INSTALL_BIN_PATH}\n"
            f"Environment=PYTHONUNBUFFERED=1\n"
            f"RuntimeDirectory=termon\n"
            f"WatchdogSec=60\n"
            f"Restart=on-failure\n"
            f"RestartSec=3\n"
            f"NoNewPrivileges=yes\n"
            f"CapabilityBoundingSet=\n"
            f"ProtectSystem=strict\n"
            f"ProtectHome=yes\n"
            f"PrivateTmp=yes\n"
            f"ProtectKernelTunables=yes\n"
            f"ProtectControlGroups=yes\n"
            f"RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX\n\n"
            f"[Install]\n"
            f"WantedBy=multi-user.target\n")


def _helper_unit_text():
    return (f"[Unit]\n"
            f"Description={APP_NAME} v{VERSION} helper (root, starts the terminals)\n"
            f"After=network-online.target\n"
            f"Before={SERVICE_NAME}\n\n"
            f"[Service]\n"
            f"Type=notify\n"
            f"ExecStart={PYTHON_BIN} {INSTALL_BIN_PATH} --helper\n"
            f"Environment=PYTHONUNBUFFERED=1\n"
            f"RuntimeDirectory=termon-helper\n"
            f"WatchdogSec=60\n"
            f"Restart=on-failure\n"
            f"RestartSec=3\n"
            f"KillMode=control-group\n"
            f"TimeoutStopSec=10\n\n"
            f"[Install]\n"
            f"WantedBy=multi-user.target\n")


def _report_talker():
    if _systemctl("is-active", "--quiet", TALKER_SERVICES[0]).returncode == 0:
        print("Node Talker (nodetalker.service) is still running. It can run beside termon.\n"
              "  To stop it when you are ready: sudo systemctl disable --now nodetalker.service")
    hooks = []
    try:
        with open(RPT_CONF, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                if "nodetalker:" in line or "nodelisten:" in line or "--feed" in line:
                    hooks.append(str(n))
    except OSError:
        pass
    if hooks:
        print(f"{RPT_CONF} still has Node Talker feed hooks (line {', '.join(hooks[:8])}).\n"
              "  termon does not edit rpt.conf. Remove those lines by hand, then reload Asterisk.")


def _sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def install_service():
    _require_root("--install")
    _refuse_inside_termon("--install")
    src = os.path.realpath(__file__)
    problem = _install_source_problem(src)
    if problem:
        sys.exit(f"Refusing to install {src}: {problem}. This file will run as root; "
                 "copy it somewhere only you can write and run --install again.")
    _remove_existing()
    os.makedirs(INSTALL_DIR, exist_ok=True)
    os.chown(INSTALL_DIR, 0, 0)
    os.chmod(INSTALL_DIR, 0o755)
    lib = os.path.join(INSTALL_DIR, f"termon-{VERSION}.py")
    if os.path.realpath(lib) != src:
        shutil.copyfile(src, lib)
        if _sha256_file(lib) != _sha256_file(src):
            os.unlink(lib)
            sys.exit("The installed copy does not match the source file; nothing was installed.")
    os.chown(lib, 0, 0)
    os.chmod(lib, 0o755)
    tmp_link = INSTALL_BIN_PATH + ".new"
    if os.path.lexists(tmp_link):
        os.unlink(tmp_link)
    os.symlink(lib, tmp_link)
    os.replace(tmp_link, INSTALL_BIN_PATH)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    cfg = load_config()
    try:
        _ensure_system_user(cfg["web_user"])
    except PrivError as exc:
        sys.exit(exc.msg)
    save_config(cfg)
    if cfg["https"]:
        if not ensure_tls_cert():
            sys.exit("Could not create the HTTPS certificate (is openssl installed?). "
                     "Install it, or set https = false in " + CONFIG_PATH + ".")
        _chown_tls(cfg["web_user"])
    atomic_write(HELPER_SERVICE_PATH, _helper_unit_text(), mode=0o644)
    atomic_write(SYSTEMD_SERVICE_PATH, _web_unit_text(cfg["web_user"]), mode=0o644)
    _report_talker()
    _systemctl("daemon-reload")
    for unit in (HELPER_SERVICE, SERVICE_NAME):
        r = _systemctl("enable", "--now", unit)
        if r.returncode != 0:
            sys.exit((r.stderr or r.stdout).strip() or f"systemctl enable {unit} failed")
    mark, fw_msg = open_firewall_port(cfg["port"])
    print(f"  Firewall: {fw_msg}" + ("  (open it by hand, or the page will not answer from the LAN)" if mark == "!" else ""))
    print(f"{APP_NAME} v{VERSION} installed and started.\n"
          f"  The web page runs as '{cfg['web_user']}'; the root helper starts the terminals.\n"
          f"  The shell account is {cfg['shell_user'] or 'root'} (change it under Setup).\n"
          + (f"  Certificate SHA-256: {_cert_fingerprint()}\n" if cfg["https"] else "") +
          f"  Open {'https' if cfg['https'] else 'http'}://<this node's LAN address>:{cfg['port']}/")


def uninstall_service():
    _require_root("--uninstall")
    _refuse_inside_termon("--uninstall")
    _remove_existing()
    mark, fw_msg = close_firewall_port(load_config()["port"])
    print(f"Firewall: {fw_msg}")
    print(f"{APP_NAME} removed. Config kept at {CONFIG_PATH}. The '{load_config()['web_user']}' user is kept.")


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="referrer" content="same-origin">
<title>Terminal Monitor</title>
<link rel="stylesheet" href="/static/xterm.css">
<style nonce="__NONCE__">
@font-face{font-family:"Readex Pro";font-style:normal;font-weight:400;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2")}
@font-face{font-family:"Readex Pro";font-style:normal;font-weight:700;font-display:swap;src:url(data:font/woff2;base64,d09GMgABAAAAAC8EABAAAAAAZgwAAC6kAAE0ewAAAAAAAAAAAAAAAAAAAAAAAAAAGoEAG7JWHIYsBmA/U1RBVEAAg2wRCAr5SN8hATYCJAOHaAuDfAAEIAWEFgcgDAcb1VWjoqz2ppjBcR42Dh6G22YUJZRzqOw/HHBDBvSJr0SENNWA0/FS21vVOrY1VBsiq4rXRpewDA8/JyHOzI9XxI9jP/GS6iy1IzQ5RSsP9fvxO3vf+ypAE5Fk6lEt6nSiVkswnelUEt5JYvsDP7feH2OwDdjYRmyDZcCCkaMWRWzkkHJEhIpK23kqBnaAlacYfWHcWad3Z51eev7vN9cnFeDkziDv0GLeNZOXm7Qza0X0udDf6S/mvuCF5Yn/Qz7vzPvNth7voC2JLabQamoFaUZNQx6iynNpa1RWtFTU2tK2TE/LTNCKMiVDJZoG0SAWxBaxHMO+LJLn2JP8EbNbsPQbKWn1CwV2khK+AQWoZA6bq9Y+pCLaJu6n7NSB2Wz7fSh2Q7RlTcmW7f0EZCbgxP+zabYz3ux78vGGUMrLIfWAVbjlppr9u97R7EQn2Tra1YGkQ+lAYLNyMLfy4wDbCZcAIJ0uL7IDSBWWANDnpelTNenapOc2RdekqMIDufxledAVg5ArkVF4rMqGGkpV+2k6tL6aUoXDKITu9vQJder8r2nT/x6l7zx6UagVLhO1kuJMZqmbT3chFF2rcDlUJOfcaRCKQaIM47Eh5jzy7MterLgiiwyxO99eK/c4Q1NCMA/jBaFpRghhRDDCu67P7RqbC+Y6sAmjAAPeuL0pBNAOzAQKDIQRwswOkSYLIkcHRKcuKO99gvDhLhBLCC0DFOEGAR2MQQmGeyYqIeV6het8D2lfacaFjx+0kojmtmRZciZQvmwuqwHKd0Wt9UCBBsymjNNHm+vBE6jBi4IZ9GthT268mmff7IC4xO68P/lvnonRnw+ZC7OujzKWHyoKd6GeKFodpbp0lYUd7ZXe+NjHo74b6Uj6+dzr+MNhQesSKKw9qVVONaXaePadS1fAf+i/X3iiOReii9Q6v66uG+ullzmNOEzQ1Ynryqbe63U3AnRtaU6HEgjhAbTAieXFe8colB0jeP7FC13w/OdsUkRycnRqEYJEScCmQyhmkkoiJ1TLVSFMVajTqJ1e57+0GbZZkh32SrHfARlGjMpywilO51yQ65oxBTzsnXJg0uEZR9mx1fOLa/wdyv6B4yNujqM4R+QCETf+YzwfSJ7Ew6WDJxRsHFw8fAJCktFuDm/CUcceu2vTEY417vzLtHQsbevkENpwJm/m6PbMjvXWyE3zil+3w9mBYtfIblR0gLZ3XuY9MrJDGOF6esTiNZ4DE83+aZBk5M7YDuTPLbeTh8bg4vWlhhIZSxO5Ng7GZrgheclUFuJYeiHmBdmFTv0NEtX80WkMiAOzcAZTXxPytbU3YjEyPHDYoGxOJP6kzKRffdiox9Nsnh6EtDCg7EXJFILVuCWJTwojMe+5BwuWaXUcBzuh7QpjaggGCfPVrubdUkJS1XFnElxdPs0H5Tw26ngYzCE+p5NZxzgmW81pIirySWoOwzYrfELETuMAHV9kxCk5LEQzirlBc4fhsUefYhq9Rr3vZ7ab5pOqKw7gNC+HzKcSFEVRFJXaT6JGGIoEGZkbNHcYHhUuAX6eotoYbMkcwsXDJyAkqaJnxNCKFSdeAj0DYzHtlRnZAlY2SVIUKDSeS5FiJco/qpxVtVjjQqcdGVxwa0LBxsHFwycgJAnl09QDYVX4ZkVU0cBsc8w1z3wLLLbE0nDZKszACiutsjrcRqsA2Ge/Aw465LBjH51crnGZ5oVBbkdMe1bG02lXieDSwhNKoQ+wJXOAi4dPQEhSRQ/F0IoVJ14CPQMjEzMLK5ukdspKsjEUaC6E8VyKFCvJpVFVhqD8pASSBq7Do0yOAoQQQggf4/hvLdEM+kOavr3ZZLIHc6PqvAf6Nn2aeD07KpmeLNEDMUwrVpx4CfQMjEzMLKxskiYHG4AILkWKlSgf7QlJDcUNmjsMjz36BNSESLOu4Ml3YBb1IDORQ9NY46wmLVq1/WeEFzQQSBCIYG58gD5gAFDa0YAG7as6DpHjAEhCGY+trTxaDHIdGBzKBdgm3wGDltYI8JMireV3OTqG/U347D0neacV8ODurtFZON1YRVZ/Wd4Pd3fGptKG7amzw/kZBwGYoHhiaWqq4mbHvlV2oKbJmTIsCMazanNsF2Un7amf2lmwy9EGixneQOq7wtne7LSn7WCnsSu4Ce3ZEM5Yk/Ky97rxVDBNz1xlDqk5FJ/xj9NLVZjDMSLA0e5ElxrTx2QbnM5XHJXjlZdces/5zmcHwZw97+DKp+F/NGS2ElDUgUVzKWGJVXkmR07LyIuhjLsVQ5oOShu1/mYnLrRQT+iwB+eSQxgkkoCS2YSt0SuNfV/0ThmATQ6sOnoUtLlMUsnwowXfzU2Dtxr6F4ue2lcZaJivkpOmEyNbmF14yTeKtuXbjiBOBrHrZn7bM6ENzlNQKnFEncMm3kuSmzxTH1xaRwMG7xKOLd31YbWHAAFLYMTgVrZzELu2rQU0+Fjn4wdCvZbq09NZuGUrv/l/4djC4b61QtPf6rweyw5LoCZJwoI3orc+L+KbHpXJefkbi2j6Jem2Uj1ajkcaBsRWyQrDLB02ibTc2HH1XW48Phc4H14f9UWwQhBDq1ZIYzaHKdFyXQE3h1oRCNsz3YVG3Tc4bijSGE5902NbUJyvHWePEe3RVLTA9AQKGliwRSIoETiTjVE/vinOr2WofEXGZVMkjmM5n+Doi1+0ZUkm01mPCr32dRVAuEj+sZrNbmCzAotPf6r145dkrbuoAJ/LqDfvm8vm75HG7bCnT2O6dXEC+f+DoUVMBIB2f3xZ4HRS/n6ivdkITMqKAWmcWnsw9pgnR/IHVhmzjn4pQONGpRs3qm/9Ag+BBdpRYNEFI2FL4EfHTiNNNr0cXayGbVbvhFManXVWi/MuaIWihfDgxpMnNCwsPi/eED5I0MjIBCgoAtDR4QUJwhKslU8IISLGJrm/jQgpyWTEkduBQqi4U1MojHQaWyRcBB+R9BdFPJ2NomdAZWQwk40wS4KRTK4U0qTSk93GSpMFK5tecsg07owgV358t0AZlHJQrIIUlfRWRZRq20+NBh4aKdXEIM22TIs2RO301UEvneSaQC8TSTCJWF1KcBgcMISXgDwXLiRQwnwGGoFvUXDw3HgRUJkbP1JUUr87RV3DDSi4AQUsCMCADl8EwWs+SbQEiHjmSRA/gW8keg/FP4xT7554nJVAlN7JUJZ6OtkOgQdwwMMH7mCBDDa8lfIj/gxvmMi0WYMdQ0BGdQ5K8w1UoaWePn0zSBAKaKDPsFwu1RpN1G3YDpre56pbP/LEC38EBQiyqbr16NWn36DpZ5Ttd2AXTu5+a8xDTzyFeDqA0jdyEg5i/xBKz8jgqH4IsLrnjqEvCAMSpo3j4c3+iJjCU8/zu6czjKmabBArVnQwkYyHA0tw8wXOjGNg5vE5mer50udJ1Y06KJiY/0JQeNDAdHFQ36AcB/f+zs46D1nEzWM5CsZ5oNXNcyBAAVEU87rVo7T+QmXs4+aiYgZS1Z3MY+EuI0vcq8TMhY5X6YPFbyfmDra+l2w4GHyNDS5/nZ70dBvIwF390A2+NjDvo+/j3eMx8R7xnvFYwf3d6/DhukawfVbfUAeOf/ztC8j+rqqiCFzfNZTUQvmOWjSjE1PQ/3DmD211zTBfUAEEr9X0VJ9aiQkIPICCGzBAw/0lji8e21v9QrOdcSMYeOYDzhFG8mNmC6gn9wKFJFAym6Sr9CSzn46DMHIMdwOnduijMiaPUrRDFJR+kQ7JfokSIA2GqbbsRyb3h8iu7gqEBK/CR9CiWUuBMQCP4u5jjQiObM/P6v0NpEBxqumJEUgGOdyERB0g6DpFrMOaJYLy57PPsBCocAZlkdW8BgAenrn7J9TMIBwiE7j5yScmzzidUGxSV+y6dB/uTTJ0aS+j3EG50xxgdbro2EeVeOv4N0EFLAD/f85twjqsRyS3V2skUL+o1GZhpa+jwFBuEFMKCsCORhZesTTHgSAAF76sbEWGqBQxE5TwB6QQRH8718CrVhCCrKDjQWggYqh+mqGiTPG1jcKisYJZHJaAQ/oagKEUoq17QGYFsoIwtp4VH37/lv54MvdJ/6MrgPAHpjsG4rz199QT231rnwdeGnPVqOP2+t5mhw3bb4utnnrsiZ2uQWDhePFBRuHHH12QYAxMbCISUjJyIdTCaISLdMoBpz034oNoOnpGZslSpLLLlmOcXHkKlCpXoVK1Go2aNGvR7oQ7TvrZJjvc89B937nrhvdumuyiZ4645Q+3/WSNtT564brdPvnGFJesN2SDXdzn0X9sNAxPeCQERL5oAgSi8sbCx8ElxPMjAZVQCkoRxKrEiaGVIFa8RAZJLKxssqRJl8EkX5FC45VweaRYg1p16rUq0+a8C85AIBkQAP4B4jeIJoCut2DAU4D6Nqi6ASgJUQi3Rq0Hiqqqv4gMXUMAqKCJEpRLJcWl16YjGikCbCIre02N4kh2UtXvxRf9TUY0YXqAQpe2cxXkjKhtRLZMG6GNe9jEO8qntGEDo4xPgUatYLjJbnrGiCHTmnsvrSPeUTRH7wXlPozhcCkqwfIoD7B0dopdSmSyxc9uo5DRFPXGB8FrPTScC/AP4WDe1VFCYhNDI4gs6o5B9BTZ0KLgYLSXBRT44BWnY4hENFhAJZHlH6V6zRkRQAxAW0IUf5WoEFkjiUe8hJu83ESATrS58dFJaExAYrQXNkbxWiJoxa7cWExbRAxHQ8PAQIcDh7PbPQ3mfP1VAp0iFlEYFF9i1oLg4Lk8XlnUPTq7LCUK7dUCuMYPx/l7xphwEDHQ66a+rglW6Ba/y6O0ITWQw7SypK4q8tByqaIj3CmkiiwviASp2z2higRzSjZYVS/aJ+D9yMFMbjmZAC+gnmCIMVrck3bqmc9zGxj9qGdgkC1ygndhZsBtH4F29jerlU+fj2EL9MVEE/CebF/aYf4L9eC5A8aO6VQlSVKjpZAwqeSxEN0ZLBrdaKqTmEqa7qb0BKNQoVx5YEF8vkDemFMws4UNE8Qx6OZUpGydDS6YdNMgln+OSZEFvzDH1UyZAW9GLOby6cbCqGeQZ5xMO7ePyCo142IdPqA08OJyH9Si2lpSMFopr9iX7Pl3C3kF2Me3v2M2HVXGSh9jZOR0nicZU+J1AOLrCcoF/W2mzEiNOeGadGXGAbVbLmR4Pm/bTj1C29CQY4lPTQ4Qv6PsfFULkT86mLKIdmKAXRqjQQQWCSRTM5jyFxut4jb/U493Rc0FV2lcWRnB1pr9cTpkwwdXGNXakqurPirVVanXRiSvurDqw118x7QUp6plgisjMAudutBBNSes1E+xdGkCmoUKDSL5ViVehmfOjP1xMV/RKOmTUXJXuRUAPvpZDSU3yzeCdzIehR13HxLCaihdeVT57B6ind5iid1QbJ15fCA3hHJdFlpmJdMLNvZJW9rcpUxmBdPFcrD1uV5A4oFbfw0UmzXl3EOUb1AZAlx5g5eNh4I0IV1kOx6FE5D0RW1MRpx3w1uYSCmJ1n0yFprHugmiDu8ePJWLaxZpXq0m5DOJ/HKES7sfH+2VrR4WQBCs2ScdjvAih11IXWXM+NN0z74qW1mq9VOaUnIXFaDKm9HRzojzTkUfm09LPQBWb8H56lft5GFmTzKWbFQtJbjC+NOxTX4wrtRzA++FODuTUHhf1Cxnzoe+v/039AtJIbW0Fwj1nhuTy8H4MngPszGOgBV/LksrOGdIWABrdvkxhCTU4Qyx1ecLRR5mk2tYAR3lLxKIafVu7CVUnlgozQH0B9PFa+A2XyiZrq+wxoGcbWSK2caT1cS4beNFTUVRhRe38JtKS3KLi6nnzatxcQgfbSuKfs+O8LbxGDOsggIi3lZYXxhER1rhs7LbOB6VjXYP0GB5cJFuDtvLUdDoBWaUfVU2cz72cu4XZVKAaz9hAEAkWE0bc/RQxd2n+dHzOrx7M8ecJ+s7sm1KCA0QXYE68tr1ooDRID2YvAwS0jjQLKIMHGmxKkzjKgi01c2DLHgTo6fys3Xpha9rzIyISG7VFURD2ogVDMaRdLAaSityIcHyadCICdkO5qMEgrG2opuIFv156YFXayuvc6ESoFzUOVuFzu2NaiC57pVUqp7hN4tbrwweG6hWdB5VofUmKod9V07qEezwWqGRw0JXSdzjT5vbrb7TDDmqTronwcY7eqdoUV1c81TzoL0wP/wq5KFCVcyu1lWV81uXog9d+2gd7bx+OfagX+TU7CRxbKO6MwF2/UyFMdywHzm541yjax2liEpUoMyTo/nEc62TE0kpDtuph4lih4tu2rtA9OuHn0cB0DhelY01eEkoyG+FnnVGMASQ24vdulVZulxJAwIRC1rKdzF6grUM8o8Z8dFIlXzTSY7f4kfLWwCwCHjwUxhDzdI+nvdnOdsneGAIi0KYfiMt5qT2zrXY6lL48JxLRddwkmh6PvLgYtFcYhM7iKuwjqziZI+0VIRXYInsYZYH2Rc2J5CKZu473h1/hQVHW7LEAXhHvZ1o1rqcUsD5aPFORrvXaycdJqoSTNI9nBHiUgyfxpsmbjrT+mHRrQTrcTSPaLBFs3BgryzTH/O03OrrFjyLk3EBrS2NqwDA4EKVn4J1XaZwIUOFxGQB3C6RU+TChupHeJdKg8h/Y22z/Bv+cP8Ff0qqkrsVQjCI7xRsib5uFUUUXzpZUMjide9ewpsHVHrmFxkCw4AKKjZw9tIv5zS8wPPj0QsohifV8wrbAWO6MnZRLqKNY/rsAgAGpsd7jf4qQZjFH4AUQq1+DFH9dOPYpwX2nZE7sFVp9YmmutT3aW8LkgWVyGNR8sloIZFk6eBU7lh3GNmB5FzHqY5q1BEdYV+Oo/TGHHaCs8TnoJxgULRqQ/+6cvh8DVf6x/B8XLEYMGHBzrt14yDxVkzhvjotqojh2gVjjxX5zs4RvM3+ZMgwuHDXcxjPRZJgHVwuAvONTrop1cKsyKQlTQxP2s/uEE3XTZBHQ2Y3bQukoA3EVwzmjMSPmiFzYuDIn/VYgo9w2rPAv4Cg7jy1pd0e4vU3hiPT2x7CFsi9Q+mFVbM0Zgq5VECAKkkhkdEWm3xmLIxQuzIWMNR561lGxgylB11Lm6DVR3/wQzOYPtzbSJtmTTTz/nF6yqyieNIrJ2lJxriQKBY2ekMjB0nDfHYrBnnd2U5v5c7Y2H/AfUpv+NTuTnAdXbrQQIrmgXqMvsiqWxn1ghO8DETtPKISnrvYRgM7ipohZsDLYjx8cX2hcTMtqxiBf0DCODiaSt3k7pVmtjO1yzW4mTLjk8hC/PktY9xFPek4eEedRNGI5jR1snrvliKNpEo3cafSNPxE3UE4+ZFiWjPkKGqaDFgFPEWxB22F04EiaSTmw/U0+kKhQSYdmS6mSSdawVT7tLf/Qmwd05XzhlNkT8qCPMjWFIiqSxRUcdz5j2G+Apl58IQB0Rl7pfnHCWI8T0j8eE9+KwFfC/DNoylDn0sOLVbMcTzPaBxNleoZLspTCq3KYRRWZOsfRaKp9xacIeaQwBcfxHTFl7282hA7ZLkRE+o8n4GghhgJ3XA9u4msHMP/NwIoIwtIIzv6i0sJHx8bTuU8/hoo+lzcAU1PgqYHPF+O+M0xz6BNpy0wz3k9B583sDtgWSsbnKPh1mKROjkiJtregL5iUPEtIRqeXReWS41YM3e55CU/oGFt8KKeyTRFiB9rv6wdFmPt/WEuV1i/PTW8r6RoUGNXjaemq25Xtj9N5oeKTHRNsDU0JMhWmkwPZXYzyel9E9OlpYHgHBWmTFXl5Su7U1KVU/Pyp6hSJ7U55ogT6c8CLXJ5oOVZIl08fy5w2Z2GTiKbMb9z9NXCxOXJC4eCZ9fMdrwqt4/m4ufVzqsJXLZ4GazCZg5qiorUfampEX2lRTM1GVHlwZnqPZV1ynRBmNTCqAxOlsuZSdOTmDKmrruWRks7Oc1K80PhDIrGnLQOGeBGt48W3guXE1ZeXgm2+e2r2+cvWz+F4I4V6IiNY78WlUmIweRAUwQ1vmfJoiW16WpO2sMMJty9Kp0/ruDbjhHe9ABUVnOx80jRLH7ksteKFV9W1wDu5uLR4Tv5ngtxJu4piWFUxMfrPOeW3iE9GQ0f3CqwLlSVcfPw6KrJCKbWwx5JZLyAJVh7v8bl0vTbUzngKlIirj6N5kR9hHKkrBPrg/l0q1TGXsFwi8WGYME3mixakZuphpmsT8k3DKHmkzE8POdoqK4iJqZcp4+pqYjV9b9Guhv8eVmB1Ayuf0P5KhoGSHJFZGCibz0qoX4i1kNZPb5qstOj3IpN/x/qWENNVFxpoi6uokZrWPnpp73aXYHnszdOnEUrN9Po0y4wuyAeWznXotJVtCp0JXINfedMMuHlAsYM/apMwSDdJE+wjO/QmMq7EixV5S9ThdLg49Vkosh3tKU6h/sHxxRiMZZN0sBb/tiy1GV3+TDF3TloSumy79mxWUBfz+Xvkwo2D++xJ3cNmCA4YGTfgOsE4dKRKmbvp6iX3a5dgSPw4NbIrqqGeXhdJ8FVNmHfjErKjHLKnte9Ij1JHhTXXllRv/3WSO/wAvbyefDxfqR/743bYbTBc7jJ0x3XZB/001LOiC+Ad4GLNu/MPXU26pTiuM9KH0M5aJvb3kXplq4mNjW/Hz22FIpN4gsi4dU94/PfTYqw6ouEmrT4Mh5W5RCGmBTiH7fkUGKGPEsX+30u3OBD+LSdRHti30g3J24wBMP3WHW6MNSkEP92eRw55sJKv4Ali+nC+qNSiTDRylNxW14aq38xciwEnrPbYJroiBWUm2yFokhrozG+E5LB7vfKvplAeLmTRH9i36jOsOtCHIFFSBb5SpGnn7DWNb6gcGJkkiKZUh2UKGuDASwvgeyQmqWenUt/Wp+Cy6FzbrON1ebYLodDO6nKVDvI0z2SSMfSebz0R1LJo3QIxaZMNBu7Uh3GronmFHO7ip5ddSrvMVWw8ItQ4LWIRztufZ9dRZ2gAiLWUGuMhfCDrzUbeTo/IzO6Mnvo2VLPjk8B/+kSyah+vu6xVPZYx+eJSyb9LQARJrndqO+wakQFRnOuWKVKFYUlLS5kCqjpjFR5t6L8bXVkRlpMJaPL6tT1t9tSprNU3/N53ylZLOVDPv97VUuPl261cOVCFknXRD0CemxOr9E00R4nLLdYi0UxkXlCvZlbhMUPB+TGIJTAjZvoovqjUikv0cRVsjNe2qrk+utEhCp5mCw9TRnO/9wnb73QgSNN2kxiptHEuZMH8wch6nlCN29yRNMnR6BM/eWNPOduYZmdKbM06RLaUx0JkxqMpuDalyktbKx7x4qXiYIym7GKF18u7PlNLP2tV8hv/k0i+a0JzM/WxuI3zLRzZdo0hchlNg5FsajqdX7aLY8p2jSaGBzkIbJ9UohExI+Vyw6WHBI8dw4CbsZOMpgsr4eIFlVhkRzdkhqCe2MHy+VUYfC/qQ2kcKy+i/BkVeSEz/9dSkjPhp5dOPK2yeluBjN+psFEXoEen7bV+TqOJnr5/IeWuvuD9BRqfIZS7DLrhyJC64V+sumPKTFDkfJ5fAoKgDl//N1rils3HpveY7J22dOYiJWe0Y1daXbU/WNmBq/kC8bz/2Iet+WLWPilBTq4OuU1tl6J8aDv0vT92xWY1lfjS9NYIYYqo5bqoWknVZsMIWmcjsbUwpZcXuKYWDKm4/HTf5SKH6Udlp1ab8YiKWb7KpNRPrCzMaWwWeYV3fp9XoDIO+wPjrHWFNtlT+Ni1Sa9QE/J9KYa3btWvCWf56Zd0wV1DuL4qwmz4+Zljd4mFJOeHZDs2WSh+Kdufx6IBWKTOxTRRRm/pwRxvTWvp+Ao2NY1Hm8M7Cy1nqWMto4XRcpSyQbulsxC+O4GhVD6egoWv25p/3XrrzqWBn6lqSNTi2WwAyv5a3lcXewxIsPKFXQkCmdnW+7wp/sw5vOF3eKPaz6aoqrqolMSSoRRNg1r10cmyZGeGJIXo410FUVeb5+5fCa0rBha8f/AnLI58C82OkMlK9RbhhTKFxK/oOk3Kdoh8jL32m83zkphw5sfSXv7ppdOm7PnFxKM7CRtLcrOqMMWtuKairK2HiC1t9BPN1FhbuM2tfkm83TdhvDk6+yYu6Ks8rrT619klVeeOw4zn3fSkQxQHGrA934Nqy38bUYR9fATUu5zUBUGlqqpfUeKPPO0fn0wc5BfHZwUFsI2XxJGhsaq9W3RbVZF8PkEbC71FZt7L8jvYnDg/mK4ME2ZJJaYQ0IlliSJMjRJIrOGhEjNNrEqi3aMzTlCC/iOxbkMdmxhX5ZxXVMTE2leiP/VWDA/wdBQUWNoSkgwNtVUGBvgtlLDz1hsDF56sahusUC5bNsyiGVnXPqRNFXXQKZ4w+q/LPXjZKM12VmhXBdXrI7OjaX/wkrQWKtXbqHY8pdBMDZrsikse1JK4i8cetCDUQaz8y7bR5AXwSvefOQhG71g15cXn+ubw4khaex/ufZQk6muIw7y1DmoP0Pqrs2hGfqKts86A1SMvTtuVV7ZHANTwqIeD2KM4Zj+5fveW4ok6oULEjYzv9vIrHzL1FdotdUmo6G+LQH44YUCk0GYpyHQ8pVFAa7131gH76zg2xjml0zLI50pSyiKKY6Lroiz6dpb9JbZTPw+VtDpLwxW0B4Gc58XHIGT5Km1Sy77pGEaQIwyt4YbC2KEsY0L846kFv7Ai4jLqlYm6qqVcVkRvJGC7v7vjWphijrGWNiqsQwGHRwIpA4OB9MOLaUGLjlIVVHTHX7+joxAaobD38+RDtejvh85cc1odopEUePjosq1VkNrmyFJU8A36YTZKi7eEGjmpNY7d2Q2MF/vDGaufcNkXJnHou26CtewymSlNDsiSuxMVqhVNoXYGRUhyU5ShpbTTonEp2lBT8WiJ9AMHI8D8vRWg7Mu2jsYtN6ZZY7XV+II3mM+5OR7yeG/JymU0cb4EFFN1x5T4KE82I0Vv2PJUqkSsv8BX0JvgPfBO/Wzxk8cynuIzWjLzF7S5hGyJZSX/Qj4a225tkMR7xcQV15J8plQeWM3OW3//Wr4xpNh9nMpUumz/AM2kXyX+BOFKY+pO1/m799Gm3b2590MzmSEGZtrhhOepuzCtFhxfopGw/2pWGr9zurDKyZGJXoYY8WRhgSVcFwiS5RGWk72nUCiLPclzwCt56AId6L0DS9xQAQncWIDo5fJ3TOT9U8tM8QeqxX9amcyo+Rg2cdlNusZohTKZbLvUYrfYTL5KGUNqZVIHPQll/kS+2HIk3urWWr9R0LktvhE6f0N8ZIIg04prDKwpIb0wnStOD9ZI7xHme5L6aQQl1N8OwF9a2TR7RGYihOPSUU/CcWPZCIE9kuvej3IuEXeLqCwbnEZb7cI2FMPL4fy/+cQerG9MdZtVi22n9A7U4UVP5IKP/Js5j3sSbMJfdgebZhC7J3Y40dZ6WPpk756x+qxvPp9C40S85VM+8B/k9b4LlmTy1IbXRp1frQyND3X+NW4MiT6IBSPyURPsfQRWHibnclaAmmMtynh41hhhqK9qULTelyX5voRdtwVPEsRCFOf8Sv8LFUoSHkGG13eA0hXRljegMZjIEaTNyWfRZje4jPnU0eeJn9aDHYwTJPblvWOMAANHSNzO0auLe7N7WUuxk/P0M7ecb3gPodGtq2lfrTB+urAn4XrqGQhqO8uylkEEd/NfDLziFRFhSd7C3uBdXRC0tSfZ8/qfibd5mblxeceq6nOHc2Lg+Kj4+zukeqa3BHyu0HzokHttegkFjMgQQKFqhPdom5J9zdqKEx3FVb6cZol0zBcJCPamGIjEWwUY0oUksFyG5SB9hqKv21M++fePkmZHztiOB1RSWyC1HDKk93ibultFoD9+ETx9CXOKatWTAfZ8cuDF0+EhbsYhEsC5uyDF6MeLOCS8c8uN4aSmbfBtP3V/DDSz34PmpgP9hyP+fWSgzXnwGE4Qtv1xGvnz3nxHUeRziPQE5Qf34lI+5HceK8uLPvJHhszPGwL2lQOm/nLZjjTA66hnBlhLpdqML09/dii3jOGBvtUWV6GotlkFEwyFhVEhAuOMpm+LGTxV5U+kSuSm0PFmREKXklihlMdxnz3gP9b0MKF0TERfUT6C46OnK1Iiq/qiMwu3xDZWhO7qtTAr7ZZawUmhc7rcibfsDOTYcKTkmiIMCFEiKNcnUthhgTbpKxhMJpsBxesqlAb/73tHx6ZUapIVDlZCTGXptg86+h+P/xNoXzGoX2tDkPs2m3nsaldWkt5vC2zNZNRUjyrXcZ+d0UqNDDzOOm6pfOktXpnVmwFCz7H/BIXnqlRjI9NjHCVagwrR4cXKROfpUTNgtweQdoGh7/v5u+zgn6Yj78qDg1NLg2xK9IoCcKJGbkDr45RODUBhEhlRQbDSrfYA4JCE7P40/wUOQEW8czU8QfsTKZgApXQ1lyZFWykmeyREqk+U7yen1X09k8C+TXdGKBODZElKpWhjtIQmOGbPBBRUho5kJISOSBkrE5O6Y8orQkRqhuzLsaliSyIiWKv6/Sk8PSBLxRVrhgCtS0zgJrVSvXtilfWPDf5abJiq2QOh6wqNg4Bh10HiY2tlNntgbhYBFIdNieg3piadbpGo0HfIHfWqM4R6PX8cWpDYmODTp+oSg9VpKvVlJquUIVlKpRK8GRmhmYmcHP0xPCqH95OFDxkc3HcyO+Kei5wvV5jcd/hhS8BOz00SSK1yEI4bJMoFJQkschlUqvkDnH5zv+PRHqzztd33a/y4P7bDWmnNi3fBBmXZ66auZI3Y9UMSEixd5lNXakOJjDtX5EgJ65x7fMeNGiDkHp83NMHRetUTk6pG1jeWzqxrGBNZi0E1sUUqDTOyEhNDsyYgnPegM581U1lSYkzt7i84oestJLi7MzEN34fSP4BpI9+lI+kAH/Shx2bcrKLysbl5J0rLs4bX1IM8djiubHi9N7qytCooG9mkgkvFson6pMJZdEKZ8xXtTeRPaCOsLZPKBaGX6EdE4z7WTTbgbuRxsLvJuzMYOPWVMOxsGTKSa6ZQ16PXXXwRCLRFFvWGJlkrgyZ1VnwcQM96MisIGZQ1xAxMZBRablXzTGRjGepThLbSE6IajpWztAw/95lYtADXDfNlYzx7OMG11bXV64rxB22/fB43XRZ94MVngjhxQJ4odvb+7kX+D9P/3M6zFZXVLoKKsuriguKKioKx4PkfN/XvnhM7y+nUcuW0IJay2iB5YO0JfT+Miq1/J07Tw8sGwCdofdV78sHPa96oMo7cUrWfnPWvq/kvh+LYYd3byXltzlhSsY+c8Z+0Gn6/uz7FNv/Z795dObymTD5MrGzAPMCfxFLjme0jLeVp/pWF7449+1mnG9CYDMSz8z8Dn6ouv3qw2xbOOArv2vpe9iyYV2gA9lIA9vQwTVhbHo4zS9k2y2/8DXkJeiSh9xfNqZ5Gb/TnHV/ClvGRpbeHnFZ1HaVzBkVKXOmKsPCUpRSZ1SEPCdFpawgZh0JCjqSRSS2XwySnBIfVTlUcmdElMxpV4WpU1TvRVRFnXJi9hG6ZEFgvXOXgsSnoblR8qNI8FUk/kHMf0KVXKMd3ookVzPh77YQmogvl+9FwGz+ts5auXc2bDeFWhtZk6ElfcG8btfjrbhgcSYD/s5mNZCZLPcGNrvBncV0a2DZiQYfXwORaCASDKAdT5TWByd5EMJF43BRcQ6NL67hYQPeRxSeg3cb84P0zvLUclj2CWvzu/wT3qvOn+BlrEuX6cLJAsa4hxYsnO+lI2LuaYlsh4h3ilHQaLEb4HzzU0pk240WWPmGZy9PUXgbtL8TT6/Om1ZNXWAKhr/Xcfea2dyoM1zePiuXbd7LTfdt9yWTuD9xMP9PmT0hoAPn40Yu1VuSIkniVZ8rsd53oERITxDAUjODfCYEGeoySgVc1y9myb9MASAwAANVXQyLXQgny4sfpg2Cu+cBPxBwv+UjWChJDvMbYwUqLviXigOGdBeCyQRlKvU0CMpeFhYY1cSrAxYmKD0NIkIWFvwvJLxHwwvgeyvcdm8ZQCro4REIgY6SibWjbkj0DQaUhSnG2C7AEW/zsNvBoecbDlvmRSLWIGoG4QkqXDhKuhQcW1YEFr3bpA95bV6CgpKaIGoOjI6o1AE1JbVA1ByY2yQMLUZjJwFZ8RYGxJGO7uMzEHKGAzR54ypck6u55MwCGOOR5ezHLzLO0x42rmXcHhRMKDNAHBAznTTLnsXZizn2meugeQ6Z74gFDjxeKFE++bn8yHpGiDyeUUVg3UcAwVlyDbyUvL/VnAztPnu1uLb4hR8fM2sYYgYZBnHGVpsvQPFNq2sYHhP8TVqV70Dhmc314h1Hk1FDSjFw+Ao63+yEct6/BNYv80a5AAj4Kynlsj9Zo8D1Vlf8xa9cS6+k19Ib6e1z+Q7Mv/P09Tjy9MPpP31w45b3X2DIep9iul92A64ClDdnT5KXtrIao3VXc0nXYlrbK5ygrIr0LC/1r75O2EB8BFKQwRXfaAIOfydlcb9Cz3IRgYip8GQs71Y9y0tnrk6zl1mN2cYX/YQEu+TL4cleMlfmy6bRAYavxUQsoz9Xfniyl8xN5iOB6IwG2TmIjYN93QRxIEkJfD+JWAD+7JB5cZlzoIUXSkGWvWSuzFcAFrLoooPsJXMJYu7ZiqqM9JTKRVo3ymDT6aAa0xewuB5wOCD92wrKXQXKmbvGS3a0lQdoqfSidwmSHzYAVj+qY6gpiEY8VHZyQl+u4WRcpJWHhCmNiF4nTlZklfuR5Qw78tOyy4tDJ8j62KQYL6sTdSg4oBrUu7LDwgnB/vlOdIxk7H6DxdMD/5Th/ute24r64n72jSOxIY/XLq7dpol2LwujqGZfis/6CLMtz/qbwOzInb6FQy8e+RVfcEX5nbRNceUE66olOismYfMbiSGjE2Koj81dC61AhQAx88fOBbXoI0H7f4Cb2yvA+2fVLgA+/3XX9rX9y7719cUABAYKIMDfiRCPBK7//aBBXK+rH7UQ9SjYNllPXdrjnD1Iuu1w0OA8dF4HOFm17/EG6fHqKGUDbsixVcR9Qaw4w+pZFu27hNTmk+TyLs3iZVDwqfd7Ev/Ow+5/Mjb3Ve7Vi7HK2YX2Lfswbae9uMDWcILNdaaP1YXMZePguThzMkkpmYXeNZTZxZxECeEAIpXunG0CK5NDbuw+WgzSFuYooucME1+D/deNAxbYAhDpx8mlzz1vkboWPfP4tU8iuMfzrnQqEqTWcYf8AqoWIh1/9ItsRsbSXkXHXrcZ5Ju5mF1HVDVzeehN4d8lyM3AaiJ2pRTNJmqC4CzHCxcttQQpwcty1DRipxMnNsJMJU49NmcqOQKdp4VZP9E4J4yGdvBPPIiB8WEBsodH0u9stcS0Y6mCtPRS5uLmEN/+ILRpMMXCz9IxyHbkhLCcE12HyLNBZHcRZZAwA7CxjRAeWoY5uFyH/TfH/hUYsiBy3irhigo/0XBMcHcfkfiX9JwjOjhQ9Qtp47D9fQj5h0ehKIlWenQyqxJShaBOotBklDFMzRJaPUGG8bW+tPX0JYCILUmnwCPH7Jp0B68yVZJGBJhA+KF8Fc/Ct/BSvNnzIH+QSl3WFhmUby4wTpt2BhTSmgMB/in+K13sKay8ruu3mckNUmN1m1egP4JiX38UTxf6u1EZ64/GCPR3RwtjD4ygRA6HALRHZn8EGHE1o8g9hYg/n5hCr0GjCZpVqVCpFYuKglIUlkyVyoSld6VIKes0CYdmDYlVO7ykxUrURlalBo+1WEWk0mrV2K1oofdQhSqycJtiIUo0qBOqABdPkRa2d1uiRpV6oZo1eeNd22IbTDdY7RxSCjGeqhEjlZ07G8WAfueXs527ogTOhj5Yle1QjyWdvRx2Gk7GLSZoFFDBjR0sKlIvxgz4gZUr0qZWKzcAKams6a/ztf9PmwMA) format("woff2")}
:root{--bg:#0d1117;--card:#161e2e;--line:#2e4060;--line2:#3a5278;--text:#f0f8ff;--muted:#9fb0bf;--soft:#c9d4de;--accent:#00ffb0;--accent-ink:#0d1117;--accent-dim:#005538;--amber:#ffd040;--red:#ff3d5a;--red-line:#ff3d5a}
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font-family:"Readex Pro",Arial,Helvetica,sans-serif}
body{padding:env(safe-area-inset-top,0px) env(safe-area-inset-right,0px) env(safe-area-inset-bottom,0px) env(safe-area-inset-left,0px)}
header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 14px;background:var(--card);border-bottom:1px solid var(--line)}
header h1{margin:0;font-size:17px;color:var(--accent);letter-spacing:.02em}
.ver{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;color:var(--muted);border:1px solid var(--line2);border-radius:999px;padding:1px 8px}
.tabs{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap}
.btn{min-height:40px;padding:0 14px;border-radius:10px;border:1px solid var(--line2);background:#1b2633;color:var(--text);cursor:pointer;font:600 14px "Readex Pro",Arial,sans-serif}
.btn:hover{border-color:var(--accent)}
.btn:disabled{opacity:.45;cursor:default;border-color:var(--line2)}
.btn.on{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
main{padding:12px;max-width:1280px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:12px}
.card h2{font-size:15px;margin:0 0 10px}
.card-head{justify-content:space-between;margin-bottom:10px}
.card-head h2{margin:0}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.muted{color:var(--muted);font-size:13px}
.status{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:var(--amber);border:1px solid rgba(255,208,64,.45);border-radius:6px;padding:4px 8px}
.term{height:62vh;min-height:280px;background:#000;border:1px solid var(--line);border-radius:8px;padding:6px;overflow:hidden}
.srow{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:6px 0;border-bottom:1px solid var(--line)}
.srow:last-child{border-bottom:0}
.srow .nm{font-family:ui-monospace,Menlo,Consolas,monospace;min-width:120px}
.ok{color:var(--accent)}
.miss{color:var(--amber)}
input.port{width:110px;min-height:40px;background:#0a1020;color:#fff;border:1px solid var(--line2);border-radius:8px;padding:0 10px;font:14px ui-monospace,Menlo,monospace}
pre.out{background:#000;border:1px solid var(--line);border-radius:8px;padding:8px;max-height:220px;overflow:auto;font:12px/1.4 ui-monospace,Menlo,monospace;color:var(--soft);white-space:pre-wrap;word-break:break-word}
textarea.copybox{width:100%;min-height:120px;margin-top:10px;background:#0a1020;color:#fff;border:1px solid var(--line2);border-radius:8px;padding:8px;font:12px ui-monospace,Menlo,monospace}
a.lnk{color:var(--accent);word-break:break-all}
#login{position:fixed;inset:0;background:rgba(0,0,0,.75);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px}
#login-card{background:var(--card);border:1px solid var(--line2);border-radius:12px;padding:22px;width:min(360px,100%);text-align:center}
#login-card h2{margin:0 0 10px;color:var(--amber);font-size:17px}
#pw{width:100%;min-height:44px;background:#0a1020;color:#fff;border:1px solid var(--line2);border-radius:8px;padding:0 12px;font:15px Arial,sans-serif;margin-bottom:10px}
#login-btn{width:100%}
#login-msg{min-height:20px;color:var(--red);font-size:13px;margin-top:10px}
@media (max-width:560px){.term{height:56vh}header h1{font-size:15px}.srow .nm{min-width:90px}}
</style>
</head>
<body>
<header>
  <h1>Terminal Monitor</h1><span class="ver" id="ver" hidden></span>
  <div class="tabs">
    <button class="btn" id="tab-monitor" type="button">Monitor</button>
    <button class="btn" id="tab-terminal" type="button">Terminal</button>
    <button class="btn" id="logout" type="button" hidden>Sign out</button>
  </div>
</header>
<main>
  <section id="pg-monitor">
    <div class="card">
      <div class="row">
        <button class="btn" data-prog="top" type="button">top</button>
        <button class="btn" data-prog="htop" type="button">htop</button>
        <button class="btn" data-prog="btop" type="button">btop</button>
        <span class="status" id="mon-status" hidden></span>
      </div>
      <div class="term" id="mon-host" style="margin-top:10px"></div>
    </div>
    <div class="card" id="setup">
      <div class="row card-head">
        <h2>Setup</h2>
        <button class="btn" id="setup-toggle" type="button" aria-expanded="false" aria-controls="setup-body">Show</button>
      </div>
      <div id="setup-body" hidden>
      <div id="setup-rows"></div>
      <pre class="out" id="job-out" hidden></pre>
      <div class="row" style="margin-top:12px">
        <span class="muted">Port</span>
        <input class="port" id="port" type="number" min="1024" max="65535" value="7878">
        <button class="btn" id="port-apply" type="button">Apply port</button>
        <a class="lnk" id="port-link" hidden></a>
      </div>
      <div class="row" style="margin-top:12px">
        <span class="muted">Allowed names</span>
        <input class="port" id="hosts" type="text" style="width:min(320px,100%)" placeholder="e.g. magicbox, node.lan">
        <button class="btn" id="hosts-apply" type="button">Save names</button>
      </div>
      <div class="muted" id="hosts-note" style="margin-top:6px"></div>
      <div class="row" style="margin-top:12px">
        <span class="muted">Shell account</span>
        <input class="port" id="shell-user" type="text" style="width:150px" placeholder="root" autocomplete="off" spellcheck="false">
        <input class="port" id="shell-pw" type="password" style="width:190px" placeholder="that account's password" autocomplete="new-password">
        <button class="btn" id="shell-apply" type="button">Save account</button>
      </div>
      <div class="muted" id="shell-note" style="margin-top:6px"></div>
      <div class="row" style="margin-top:12px">
        <span class="muted">Web service user</span>
        <input class="port" id="web-user" type="text" style="width:150px" placeholder="termon" autocomplete="off" spellcheck="false">
        <button class="btn" id="web-apply" type="button">Save user</button>
      </div>
      <div class="muted" id="web-note" style="margin-top:6px"></div>
      <div class="row" style="margin-top:12px">
        <span class="muted">Certificate</span>
        <a class="lnk" id="cert-dl" href="/api/cert.pem" download="termon.pem">Download</a>
        <button class="btn" id="cert-new" type="button">New certificate</button>
      </div>
      <div class="muted" id="cert-note" style="margin-top:6px;word-break:break-all"></div>
      <div class="row" style="margin-top:12px">
        <label class="muted"><input type="checkbox" id="bind-ip"> Tie each sign-in to the address it came from</label>
      </div>
      <div class="muted" id="session-note" style="margin-top:6px"></div>
      <div class="row" style="margin-top:12px">
        <button class="btn" id="logout-all" type="button">Sign out everywhere</button>
      </div>
      <div class="muted" id="setup-note" style="margin-top:8px"></div>
      </div>
    </div>
  </section>
  <section id="pg-terminal" hidden>
    <div class="card">
      <div class="row">
        <span class="status" id="sh-status">idle</span>
        <button class="btn" id="sh-copy" type="button">Copy output</button>
        <button class="btn" id="sh-new" type="button">New shell</button>
        <span class="muted" id="copy-note"></span>
      </div>
      <div class="term" id="sh-host" style="margin-top:10px"></div>
      <textarea class="copybox" id="copy-box" hidden readonly></textarea>
    </div>
  </section>
</main>
<div id="login" hidden>
  <div id="login-card">
    <h2>Terminal Monitor</h2>
    <div class="muted" style="margin-bottom:12px">Sign in with the password of the shell account (root unless Setup says otherwise).</div>
    <input id="pw" type="password" autocomplete="current-password" placeholder="Root password">
    <button class="btn on" id="login-btn" type="button">Sign in</button>
    <div id="login-msg"></div>
  </div>
</div>
<script src="/static/xterm.js"></script>
<script src="/static/addon-fit.js"></script>
<script nonce="__NONCE__">
(function () {
  'use strict';
  var COPY_MAX = 1048576;
  var ANSI_RE = /\x1b\[[0-?]*[ -\/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]/g;
  var PROGS = ['top', 'htop', 'btop'];
  var PKG_ROWS = [['top', 'procps', 'top (procps)'], ['htop', 'htop', 'htop'], ['btop', 'btop', 'btop']];
  var st = {
    started: false, setup: null, mon: null, sh: null, monProg: '', shStarted: false,
    polling: false, shBuf: [], shLen: 0, shTrunc: false
  };

  function $(id) { return document.getElementById(id); }

  function b64ToBytes(s) {
    var bin = atob(s);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function api(method, path, body) {
    var opt = { method: method, credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        j.status = r.status;
        if (r.status === 401 && path !== '/api/login') showLogin('Your session ended. Sign in again.');
        if (!r.ok && !j.message) j.message = 'HTTP ' + r.status;
        if (j.ok === undefined) j.ok = r.ok;
        return j;
      });
    }, function (e) {
      return { ok: false, status: 0, message: 'Network error: ' + e.message };
    });
  }

  function showLogin(msg) {
    st.shStarted = false;
    $('login').hidden = false;
    $('logout').hidden = true;
    $('login-msg').textContent = msg || '';
    $('pw').value = '';
    $('pw').focus();
  }

  function showApp() {
    $('login').hidden = true;
    $('logout').hidden = false;
  }

  function doLogin() {
    var pw = $('pw').value;
    if (!pw) { $('login-msg').textContent = 'Enter the password.'; return; }
    $('login-btn').disabled = true;
    api('POST', '/api/login', { password: pw }).then(function (j) {
      $('login-btn').disabled = false;
      if (j.ok) { showApp(); start(); }
      else showLogin(j.message || 'Sign-in failed.');
    });
  }
  $('login-btn').onclick = doLogin;
  $('pw').addEventListener('keydown', function (e) { if (e.key === 'Enter') doLogin(); });

  function stopAll() {
    if (st.mon) st.mon.close();
    if (st.sh) st.sh.close();
    st.shStarted = false;
  }

  $('logout').onclick = function () {
    api('POST', '/api/logout', {}).then(function () {
      stopAll();
      showLogin('Signed out.');
    });
  };

  // ---- terminal pane (xterm.js + SSE output + POST input)

  function Pane(hostId, statusId, opts) {
    var self = this;
    this.statusEl = statusId ? $(statusId) : null;
    this.opts = opts || {};
    this.sid = null;
    this.es = null;
    this.alive = false;
    this.lastSeq = 0;
    this.fails = 0;
    this.retry = null;
    this.sentRows = 0;
    this.sentCols = 0;
    this.queue = Promise.resolve();
    this.decoder = new TextDecoder('utf-8');
    this.term = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      scrollback: 2000,
      fontFamily: 'ui-monospace,Menlo,Consolas,monospace',
      theme: { background: '#000000', foreground: '#e6edf3', cursor: '#00ffb0' }
    });
    this.fit = new FitAddon.FitAddon();
    this.term.loadAddon(this.fit);
    this.term.open($(hostId));
    this.term.onData(function (d) { self.send(d); });
  }

  Pane.prototype.status = function (t) {
    if (this.statusEl) this.statusEl.textContent = t;
  };

  Pane.prototype.fitNow = function () {
    try { this.fit.fit(); } catch (e) { return; }
    var rows = this.term.rows, cols = this.term.cols;
    if (this.alive && this.sid && (rows !== this.sentRows || cols !== this.sentCols)) {
      this.sentRows = rows;
      this.sentCols = cols;
      api('POST', '/api/term/resize', { sid: this.sid, rows: rows, cols: cols });
    }
  };

  Pane.prototype.send = function (data) {
    if (!this.alive || !this.sid) return;
    var sid = this.sid;
    this.queue = this.queue.then(function () {
      return api('POST', '/api/term/input', { sid: sid, data: data });
    });
  };

  Pane.prototype.open = function (kind, prog) {
    var self = this;
    this.close();
    this.term.reset();
    this.decoder = new TextDecoder('utf-8');
    this.lastSeq = 0;
    this.fails = 0;
    this.sentRows = 0;
    this.sentCols = 0;
    this.status('starting');
    try { this.fit.fit(); } catch (e) { /* hidden pane: fit later */ }
    return api('POST', '/api/term/ticket', {}).then(function (t) {
      if (!t.ok) throw new Error(t.message || 'Could not get a ticket.');
      var body = { kind: kind, ticket: t.ticket, rows: self.term.rows || 24, cols: self.term.cols || 80 };
      if (prog) body.prog = prog;
      return api('POST', '/api/term/open', body);
    }).then(function (o) {
      if (!o.ok) throw new Error(o.message || 'Could not open.');
      self.sid = o.sid;
      self.alive = true;
      self.status('connected');
      self.connect();
      self.fitNow();
    }).catch(function (e) {
      self.alive = false;
      self.status('error');
      self.term.write('\r\n[' + e.message + ']\r\n');
      if (self.opts.onError) self.opts.onError(e.message);
    });
  };

  Pane.prototype.connect = function () {
    var self = this, sid = this.sid;
    if (this.es) { this.es.close(); this.es = null; }
    var es = new EventSource('/api/term/stream?sid=' + encodeURIComponent(sid) + '&after=' + this.lastSeq);
    this.es = es;
    es.addEventListener('out', function (ev) {
      if (self.es !== es) return;
      var j = JSON.parse(ev.data);
      self.lastSeq = j.seq;
      self.fails = 0;
      var bytes = b64ToBytes(j.d);
      self.term.write(bytes);
      if (self.opts.onBytes) self.opts.onBytes(self.decoder.decode(bytes, { stream: true }));
    });
    es.addEventListener('exit', function (ev) {
      if (self.es !== es) return;
      var code = 0;
      try { code = JSON.parse(ev.data).code; } catch (e) { /* keep 0 */ }
      self.endSession('exited, code ' + code);
    });
    es.onerror = function () {
      if (self.es !== es) return;
      es.close();
      self.es = null;
      if (!self.alive) return;
      self.fails++;
      var again = function () {
        self.retry = setTimeout(function () {
          self.retry = null;
          if (self.alive && self.sid === sid) self.connect();
        }, 1500);
      };
      if (self.fails < 3) { again(); return; }
      api('GET', '/api/term/info?sid=' + encodeURIComponent(sid)).then(function (j) {
        if (self.sid !== sid) return;
        if (!j.ok || j.alive === false) { self.endSession('session ended'); return; }
        again();
      });
    };
  };

  Pane.prototype.endSession = function (why) {
    if (this.retry) { clearTimeout(this.retry); this.retry = null; }
    if (this.es) { this.es.close(); this.es = null; }
    var wasAlive = this.alive;
    this.alive = false;
    this.status('ended');
    this.term.write('\r\n[' + (this.opts.label || 'session') + ' ' + why + ']\r\n');
    if (wasAlive && this.opts.onEnd) this.opts.onEnd();
  };

  Pane.prototype.close = function () {
    if (this.retry) { clearTimeout(this.retry); this.retry = null; }
    if (this.es) { this.es.close(); this.es = null; }
    if (this.alive && this.sid) api('POST', '/api/term/close', { sid: this.sid });
    this.alive = false;
    this.sid = null;
  };

  // ---- Terminal page: copy buffer

  function bufAdd(s) {
    st.shBuf.push(s);
    st.shLen += s.length;
    while (st.shLen > COPY_MAX && st.shBuf.length > 1) {
      st.shLen -= st.shBuf.shift().length;
      st.shTrunc = true;
    }
  }

  function bufText() {
    return st.shBuf.join('').replace(/\r\n/g, '\n').replace(/\r/g, '').replace(ANSI_RE, '');
  }

  function note(t) { $('copy-note').textContent = t; }

  function legacyCopy(t) {
    var box = $('copy-box');
    box.value = t;
    box.hidden = false;
    box.focus();
    box.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    if (ok) box.hidden = true;
    return ok;
  }

  function copyOutput() {
    var t = bufText();
    if (!t.trim()) { note('Nothing to copy yet.'); return; }
    var done = function (ok) {
      if (ok) note(st.shTrunc ? 'Copied. The copy holds the last 1 MB of output.' : 'Copied.');
      else note('The browser blocked copying. The text is in the box below: select it and copy by hand.');
    };
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(function () { done(true); }, function () { done(legacyCopy(t)); });
    } else {
      done(legacyCopy(t));
    }
  }

  $('sh-copy').onclick = copyOutput;

  function shNew() {
    st.shBuf = [];
    st.shLen = 0;
    st.shTrunc = false;
    note('');
    st.shStarted = true;
    st.sh.open('shell');
  }
  $('sh-new').onclick = shNew;

  // ---- tabs

  function showTab(name) {
    var mon = name === 'monitor';
    $('pg-monitor').hidden = !mon;
    $('pg-terminal').hidden = mon;
    $('tab-monitor').classList.toggle('on', mon);
    $('tab-terminal').classList.toggle('on', !mon);
    if (mon && st.mon) setTimeout(function () { st.mon.fitNow(); }, 0);
    if (!mon && st.sh) {
      if (!st.shStarted) shNew();
      else setTimeout(function () { st.sh.fitNow(); }, 0);
    }
  }
  $('tab-monitor').onclick = function () { showTab('monitor'); };
  $('tab-terminal').onclick = function () { showTab('terminal'); };

  // ---- Monitor page

  function monStatus(t) {
    var el = $('mon-status');
    el.textContent = t || '';
    el.hidden = !t;
  }

  function markProgs() {
    var inst = st.setup ? st.setup.installed : {};
    document.querySelectorAll('[data-prog]').forEach(function (b) {
      var p = b.getAttribute('data-prog');
      b.disabled = !inst[p];
      b.classList.toggle('on', p === st.monProg);
      b.title = inst[p] ? '' : p + ' is not installed. Use Setup below.';
    });
  }

  function monSelect(prog) {
    if (st.monProg === prog && st.mon.alive) return;
    st.monProg = prog;
    markProgs();
    monStatus('');
    st.mon.open('monitor', prog).then(markProgs);
  }

  function monStart() {
    return api('GET', '/api/setup').then(function (s) {
      if (!s.ok) { monStatus('Could not read setup: ' + s.message); return; }
      applySetup(s);
      var want = s.monitor_last;
      var msg = '';
      if (!s.installed[want]) {
        var alt = PROGS.filter(function (p) { return s.installed[p]; })[0];
        if (!alt) { monStatus('No monitor program is installed yet. Install one in Setup below.'); return; }
        msg = want + ' is not installed, so ' + alt + ' is shown.';
        want = alt;
      }
      monSelect(want);
      if (msg) monStatus(msg);
    });
  }

  document.querySelectorAll('[data-prog]').forEach(function (b) {
    b.onclick = function () {
      if (!b.disabled) monSelect(b.getAttribute('data-prog'));
    };
  });

  // ---- Setup card

  function applySetup(s) {
    st.setup = s;
    renderSetup();
    markProgs();
    if (s.job && s.job.state === 'running') pollJob();
  }

  function renderSetup() {
    var s = st.setup;
    if (!s) return;
    var box = $('setup-rows');
    box.textContent = '';
    PKG_ROWS.forEach(function (r) {
      var bin = r[0], pkg = r[1], label = r[2];
      var row = document.createElement('div');
      row.className = 'srow';
      var nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = label;
      var stt = document.createElement('span');
      stt.className = s.installed[bin] ? 'ok' : 'miss';
      stt.textContent = s.installed[bin] ? 'installed' : 'not installed';
      row.appendChild(nm);
      row.appendChild(stt);
      if (!s.installed[bin]) {
        var b = document.createElement('button');
        b.className = 'btn';
        b.type = 'button';
        b.textContent = 'Install ' + label;
        b.disabled = !s.helper || s.job.state === 'running';
        b.onclick = function () { installPkg(pkg, label); };
        row.appendChild(b);
      }
      box.appendChild(row);
    });
    $('setup-note').textContent = s.helper ? '' : 'The root helper is not answering, so installs and settings are disabled.';
    applyAccount(s);
    applyCert(s);
    if (s.version) { var vb = $('ver'); vb.textContent = 'v' + s.version; vb.hidden = false; }
    if (s.hosts) {
      var hi = $('hosts');
      if (document.activeElement !== hi) hi.value = s.hosts.extra.join(', ');
      $('hosts-note').textContent = 'Always allowed: IP addresses, localhost' +
        (s.hosts.own.length ? ', ' + s.hosts.own.join(', ') : '') + '.';
    }
  }

  var SUDO_TEXT = {
    root: 'This is root.',
    password: 'sudo asks for this account\'s password, so root needs a second step.',
    nopasswd: 'Warning: sudo does not ask this account for a password, so it is as strong as root.',
    none: 'This account has no sudo rights, so it cannot become root.',
    unknown: 'Its sudo rights could not be read.'
  };

  function applyAccount(s) {
    var a = s.account;
    if (!a) return;
    var su = $('shell-user');
    if (document.activeElement !== su) su.value = a.account === 'root' ? '' : a.account;
    var wu = $('web-user');
    if (document.activeElement !== wu) wu.value = a.web_user;
    $('shell-note').textContent = 'Terminals run as ' + a.account + '. ' + (SUDO_TEXT[a.sudo] || '');
    $('web-note').textContent = a.split
      ? 'This page runs as ' + a.web_user + ' and asks the root helper for terminals.'
      : 'Single-process mode: this page runs as root (started by hand, not by the service).';
  }

  function applyCert(s) {
    if (!s.cert) return;
    $('cert-dl').hidden = !s.cert.https;
    $('cert-new').disabled = !s.cert.https || !s.helper;
    $('cert-note').textContent = s.cert.https
      ? 'SHA-256 ' + s.cert.sha256 + '. Compare it with the one in your browser\'s certificate view or in the install output.'
      : 'HTTPS is off (https = false in the config).';
    var bi = $('bind-ip');
    if (s.options && document.activeElement !== bi) bi.checked = !!s.options.bind_session_ip;
    bi.disabled = !s.helper;
    if (s.limits) {
      $('session-note').textContent = 'A sign-in ends ' + (s.limits.idle_sec / 3600) + ' hours after the last click or key, and at most ' +
        (s.limits.max_sec / 3600) + ' hours after it started.' +
        (s.options && s.options.bind_session_ip ? ' It also ends if it is used from another address.' : '');
    }
  }

  function installPkg(pkg, label) {
    if (!window.confirm('Install ' + label + ' with apt? It runs as root and can take a few minutes.')) return;
    api('POST', '/api/setup/install', { pkg: pkg, confirm: true }).then(function (j) {
      if (!j.ok) { $('setup-note').textContent = j.message; return; }
      pollJob();
    });
  }

  function pollJob() {
    if (st.polling) return;
    st.polling = true;
    var out = $('job-out');
    out.hidden = false;
    var tick = function () {
      api('GET', '/api/setup').then(function (s) {
        if (!s.ok) { st.polling = false; return; }
        var job = s.job || {};
        out.textContent = (job.pkg ? 'apt ' + job.pkg + ': ' + job.state + '\n' : '') + (job.output || '');
        out.scrollTop = out.scrollHeight;
        applySetup(s);
        if (job.state === 'running') { setTimeout(tick, 1500); return; }
        st.polling = false;
        if (job.state === 'ok' && !(st.mon && st.mon.alive)) monStart();
      });
    };
    tick();
  }

  $('port-apply').onclick = function () {
    var p = parseInt($('port').value, 10);
    if (!(p >= 1024 && p <= 65535)) { $('setup-note').textContent = 'Use a port from 1024 to 65535.'; return; }
    if (!window.confirm('Move Terminal Monitor to port ' + p + '? The page will disconnect and you will need the new address.')) return;
    api('POST', '/api/setup/port', { port: p, confirm: true }).then(function (j) {
      if (!j.ok) { $('setup-note').textContent = j.message; return; }
      var a = $('port-link');
      a.textContent = j.url;
      a.href = j.url;
      a.hidden = false;
      $('setup-note').textContent = j.restarting
        ? 'Restarting on port ' + p + '. Open the new address once the service is back.'
        : 'Port unchanged.';
    });
  };

  $('shell-apply').onclick = function () {
    var u = $('shell-user').value.trim();
    var pw = $('shell-pw').value;
    if (!pw) { $('shell-note').textContent = 'Enter that account\'s password to confirm the change.'; return; }
    if (!window.confirm('Run terminals as ' + (u || 'root') + '? Everyone is signed out and must use that account\'s password.')) return;
    api('POST', '/api/setup/shell_user', { user: u, password: pw, confirm: true }).then(function (j) {
      $('shell-pw').value = '';
      if (!j.ok) { $('shell-note').textContent = j.message; return; }
      stopAll();
      showLogin('Shell account is now ' + j.account + '. Sign in with its password.');
    });
  };

  $('cert-new').onclick = function () {
    if (!window.confirm('Make a new certificate? The page restarts and every browser and app that saved the old one must accept the new one.')) return;
    api('POST', '/api/setup/cert', { confirm: true }).then(function (j) {
      $('cert-note').textContent = j.ok
        ? 'New certificate, SHA-256 ' + j.sha256 + (j.restarting ? '. The page restarts in a moment; reload it.' : '. Restart termon to use it.')
        : j.message;
    });
  };

  $('bind-ip').onchange = function () {
    var box = this;
    api('POST', '/api/setup/options', { bind_session_ip: box.checked, confirm: true }).then(function (j) {
      if (!j.ok) { box.checked = !box.checked; $('session-note').textContent = j.message; return; }
      api('GET', '/api/setup').then(function (s) { if (s.ok) applyCert(s); });
    });
  };

  $('logout-all').onclick = function () {
    if (!window.confirm('End every sign-in, including other browsers, and close every terminal?')) return;
    api('POST', '/api/logout_all', {}).then(function () {
      stopAll();
      showLogin('Signed out everywhere.');
    });
  };

  $('web-apply').onclick = function () {
    var n = $('web-user').value.trim();
    if (!n) { $('web-note').textContent = 'Enter a user name.'; return; }
    if (!window.confirm('Run this page as ' + n + '? It is created as a system user with no login if it does not exist, and the page restarts.')) return;
    api('POST', '/api/setup/web_user', { name: n, confirm: true }).then(function (j) {
      $('web-note').textContent = j.ok
        ? (j.restarting ? 'Saved. The page restarts in a moment; reload it.' : 'Saved. It applies when the service is installed.')
        : j.message;
    });
  };

  $('setup-toggle').onclick = function () {
    var body = $('setup-body');
    var show = body.hidden;
    body.hidden = !show;
    this.textContent = show ? 'Hide' : 'Show';
    this.setAttribute('aria-expanded', show ? 'true' : 'false');
  };

    $('hosts-apply').onclick = function () {
    if (!window.confirm('Save these allowed names? Names not listed here are refused.')) return;
    api('POST', '/api/setup/hosts', { hosts: $('hosts').value, confirm: true }).then(function (j) {
      $('setup-note').textContent = j.ok ? 'Names saved.' : j.message;
      if (j.ok) api('GET', '/api/setup').then(function (s) { if (s.ok) applySetup(s); });
    });
  };

  window.addEventListener('pagehide', function () {
    [st.mon, st.sh].forEach(function (p) {
      if (p && p.alive && p.sid) {
        fetch('/api/term/close', { method: 'POST', credentials: 'same-origin', keepalive: true,
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify({ sid: p.sid }) }).catch(function () {});
      }
    });
  });

  window.addEventListener('resize', function () {
    if (!$('pg-monitor').hidden && st.mon) st.mon.fitNow();
    if (!$('pg-terminal').hidden && st.sh) st.sh.fitNow();
  });

  function start() {
    if (!st.mon) {
      st.mon = new Pane('mon-host', null, {
        label: 'program',
        onError: monStatus,
        onEnd: function () { monStatus(st.monProg + ' ended. Click it to restart.'); }
      });
      st.sh = new Pane('sh-host', 'sh-status', { label: 'shell', onBytes: bufAdd });
    }
    st.started = true;
    showTab('monitor');
    monStart();
  }

  api('GET', '/api/whoami').then(function (j) {
    if (j.logged_in) { showApp(); start(); }
    else showLogin('');
  });
})();
</script>
</body>
</html>
"""


def run_helper():
    if os.geteuid() != 0:
        log("the helper must run as root")
        return 1
    if not acquire_instance_lock(HELPER_LOCK):
        log(f"another helper is already running (lock {HELPER_LOCK}); not starting")
        return 1
    problem = _file_problem(__file__)
    if problem:
        log(f"refusing to start: this file runs as root and {problem}")
        return 1
    priv = Privileged()
    priv.split = True
    priv.pids_path = os.path.join(os.path.dirname(HELPER_SOCK), "pids.json")
    priv.kill_leftovers()
    server = HelperServer(HELPER_SOCK, priv)
    try:
        server.bind()
    except OSError as exc:
        log(f"cannot open {HELPER_SOCK}: {exc}")
        return 1
    log(f"{APP_NAME} v{VERSION} helper listening on {HELPER_SOCK}")
    sd_notify("READY=1")
    _start_watchdog()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None):
    global BACKEND
    ap = argparse.ArgumentParser(description=f"{APP_NAME} v{VERSION}: LAN-only web terminal and process monitor")
    ap.add_argument("--install", action="store_true", help="Install as systemd services and start them")
    ap.add_argument("--uninstall", action="store_true", help="Stop and remove the systemd services")
    ap.add_argument("--helper", action="store_true", help="Run the root helper (started by systemd)")
    ap.add_argument("--port", type=int, metavar="PORT",
                    help="Listen on PORT instead of the configured port (testing)")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION} ({DATE_STR})")
    args = ap.parse_args(argv)
    if args.install:
        install_service()
        return 0
    if args.uninstall:
        uninstall_service()
        return 0
    if args.helper:
        return run_helper()
    cfg = load_config()
    _init_names(cfg)
    port = args.port or cfg["port"]
    if _norm_port(port) is None:
        log(f"port {port} is out of range")
        return 2
    ctx = None
    if cfg["https"]:
        try:
            if not ensure_tls_cert():
                log("HTTPS is on but there is no certificate; not starting. Fix openssl, or set https = false in the config")
                return 1
            ctx = make_ssl_context()
        except (ssl.SSLError, OSError) as exc:
            log(f"cannot load the HTTPS certificate: {exc}")
            return 1
    else:
        log("WARNING: HTTPS is off; the password and terminal travel in clear text")
    global _BIND_IP
    _BIND_IP = cfg["bind_session_ip"]
    BACKEND = Privileged() if os.geteuid() == 0 else RemoteBackend(HELPER_SOCK)
    try:
        server = LimitedServer(("0.0.0.0", port), Handler, ssl_ctx=ctx)
    except OSError as exc:
        log(f"cannot listen on port {port}: {exc}")
        return 1
    server.daemon_threads = True
    if not acquire_instance_lock():
        log(f"another termon is already running (lock {LOCK_PATH}); not starting")
        server.server_close()
        return 1
    log(f"{APP_NAME} v{VERSION} listening on 0.0.0.0:{port} ({'HTTPS' if ctx else 'HTTP'}, LAN only)")
    if ctx:
        log(f"certificate SHA-256 {_cert_fingerprint()}")
    if os.geteuid() == 0:
        log("single-process mode: the web side runs as root. --install sets up the split service.")
    elif not BACKEND.ping():
        log("WARNING: the root helper is not answering; sign-in and terminals will fail until it starts")
    sd_notify("READY=1")
    _start_watchdog()
    threading.Thread(target=_maint_loop, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _close_all_sessions()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
