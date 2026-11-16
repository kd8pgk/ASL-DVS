#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import configparser
import glob
import gzip
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


VERSION = "0.5.1"
DATE_STR = "2026-11-16"
APP_NAME = "Node Monitor"
PORT = 7777

INSTALL_BIN_PATH = "/usr/local/bin/nodemon.py"
INSTALL_DIR = "/usr/local/lib/asl_dvs/nodemon"
SERVICE_NAME = "nodemon.service"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/nodemon.service"
_SYSTEMD_UNIT_DIR = "/etc/systemd/system"

CONFIG_DIR = os.environ.get("NODEMON_CONFIG_DIR", "/etc/asl_dvs")
CONFIG_PATH = os.path.join(CONFIG_DIR, "nodemon.conf")
CONFIG_SECTION = "nodemon"
RPT_CONF = os.environ.get("NODEMON_RPT_CONF", "/etc/asterisk/rpt.conf")
AMI_CONF = os.environ.get("NODEMON_AMI_CONF", "/etc/asterisk/manager.conf")
AMI_HOST = "127.0.0.1"
AMI_PORT = int(os.environ.get("NODEMON_AMI_PORT", "5038"))
AMI_RETRY_SEC = 10.0
AMI_REPLY_SEC = 5.0
AMI_MAX_BYTES = 1000000
ABINFO_GLOB = os.environ.get("NODEMON_ABINFO_GLOB", "/tmp/ABInfo_*.json")
M17_INI = os.environ.get("NODEMON_M17_INI", "/opt/USRP2M17/USRP2M17.ini")
SVX_CONF = os.environ.get("NODEMON_SVX_CONF", "/usr/local/etc/svxlink/svxlink.conf")
SVX_LOG = os.environ.get("NODEMON_SVX_LOG", "/var/log/svxlink")
SVX_LOG_TAIL = 262144
UNIT_AB = "analog_bridge"
UNIT_M17 = "usrp2m17"
UNIT_SVX = "svxlink-usrp"

MAX_JSON_BYTES = 64 * 1024
GZIP_MIN_BYTES = 600
POLL_MIN_SEC = 1
POLL_MAX_SEC = 30
PRIVATE_MIN = 1000
PRIVATE_MAX = 1999
_START_TIME = time.time()
_OPEN_GET_PATHS = ("/", "/index.html", "/api/health", "/api/whoami")



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

def _atomic_write(path, data, mode=0o644, like=None):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if like is not None:
        atomic_write(path, data, new_mode=like.st_mode & 0o7777)
    else:
        atomic_write(path, data, mode=mode)

def _remove_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass

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

def sess_policy(tier):
    if tier == "standard":
        return {"idle": 12 * 3600, "absolute": 0, "renew": 3600, "max": 50}
    if tier == "strict":
        return {"idle": 2 * 3600, "absolute": 12 * 3600, "renew": 3600, "max": 50}
    raise ValueError("unknown session tier: %s" % (tier,))

def sess_digest(token):
    import hashlib
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()

def sess_stamp(password_hash):
    import hashlib
    return hashlib.sha256((password_hash or "").encode("utf-8")).hexdigest()[:32]

def sess_dead(rec, now):
    return rec["idle"] <= now or bool(rec["abs"] and rec["abs"] <= now)

def sess_new(store, policy, now, stamp="", ip=""):
    import secrets
    for key in [k for k, r in store.items() if sess_dead(r, now)]:
        del store[key]
    while len(store) >= policy["max"]:
        del store[min(store, key=lambda k: store[k]["born"])]
    token = secrets.token_hex(32)
    idle = now + policy["idle"]
    hard = now + policy["absolute"] if policy["absolute"] else 0
    store[sess_digest(token)] = {"idle": min(idle, hard) if hard else idle, "abs": hard, "born": now,
                                 "renew": now, "stamp": stamp, "ip": ip}
    return token, int(min(idle, hard) - now if hard else idle - now)

def sess_check(store, token, policy, now, stamp=None, touch=True, ip=None):
    if not token:
        return False, False, 0
    key = sess_digest(token)
    rec = store.get(key)
    if rec is None:
        return False, False, 0
    if (sess_dead(rec, now) or (stamp is not None and rec["stamp"] != stamp)
            or (ip is not None and rec["ip"] and rec["ip"] != ip)):
        del store[key]
        return False, False, 0
    if touch:
        rec["idle"] = now + policy["idle"]
        if rec["abs"]:
            rec["idle"] = min(rec["idle"], rec["abs"])
    renew = bool(touch and now - rec["renew"] >= policy["renew"])
    if renew:
        rec["renew"] = now
    return True, renew, int(rec["idle"] - now)

def sess_drop(store, token):
    return store.pop(sess_digest(token), None) is not None if token else False

def sess_drop_all(store):
    count = len(store)
    store.clear()
    return count

def sess_cookie_name(name, secure):
    return ("__Host-" if secure else "") + name

def sess_cookie(name, token, max_age, secure):
    parts = [sess_cookie_name(name, secure) + "=" + token, "Path=/", "HttpOnly", "SameSite=Strict",
             "Max-Age=%d" % max(0, int(max_age))]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)

def sess_cookie_clear(name, secure):
    return sess_cookie(name, "", 0, secure)

def sess_token_from(cookie_header, name):
    wanted = (name, "__Host-" + name)
    for part in (cookie_header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key in wanted and value:
            return value
    return None

def lock_wait(state, ip, now, wan=False):
    recent = state.setdefault("wan", [])
    while recent and now - recent[0] > 600:
        recent.pop(0)
    rec = state.setdefault("ip", {}).get(ip)
    wait = max(0.0, rec["until"] - now) if rec else 0.0
    if wan and len(recent) >= 20:
        wait = max(wait, recent[0] + 600 - now)
    return wait

def lock_fail(state, ip, now, wan=False):
    table = state.setdefault("ip", {})
    recent = state.setdefault("wan", [])
    for key in [k for k, r in table.items() if now - r["last"] > 3600 and r["until"] <= now]:
        del table[key]
    while len(table) >= 1000 and ip not in table:
        del table[min(table, key=lambda k: table[k]["last"])]
    if wan:
        recent.append(now)
        del recent[:-20]
    rec = table.setdefault(ip, {"n": 0, "until": 0.0, "last": now})
    rec["n"] += 1
    rec["last"] = now
    if rec["n"] >= 5:
        rec["until"] = now + min(5 * 2 ** min(rec["n"] - 5, 10), 300)
    return max(0.0, rec["until"] - now)

def lock_ok(state, ip):
    state.setdefault("ip", {}).pop(ip, None)

_sessions = {}

_sessions_lock = threading.Lock()

_sess_local = threading.local()

_stamp_cache = [0.0, ""]

_lock_state = {}

_lock_lock = threading.Lock()

def _sess_now():
    return time.time()

def _pw_stamp():
    now = time.time()
    if now - _stamp_cache[0] > 5:
        try:
            value = sess_stamp(_read_shadow_hash(_AUTH_ACCOUNT) or "")
        except Exception:
            value = ""
        _stamp_cache[0] = now
        _stamp_cache[1] = value
    return _stamp_cache[1]

def _issue_session():
    with _sessions_lock:
        return sess_new(_sessions, _SESS_POLICY, _sess_now(), _pw_stamp())

def _check_session(token):
    _sess_local.renew = 0
    with _sessions_lock:
        ok, renew, age = sess_check(_sessions, token, _SESS_POLICY, _sess_now(), _pw_stamp())
    if ok and renew:
        _sess_local.renew = age
    return ok

def _revoke_all_sessions():
    with _sessions_lock:
        return sess_drop_all(_sessions)

def _auth_lockout_remaining(client_ip, wan=False):
    with _lock_lock:
        return lock_wait(_lock_state, client_ip, time.time(), wan)

def _record_auth_failure(client_ip, wan=False):
    with _lock_lock:
        wait = lock_fail(_lock_state, client_ip, time.time(), wan)
        wan_count = len(_lock_state.get("wan", ()))
    if wan and wan_count == 20:
        log_event("Auth: 20 failed internet logins in 10 min; internet logins wait until that window ends", "warn")
    if wait > 0:
        log_event(f"Auth: {client_ip} locked out for {int(wait)}s after repeated failed attempts", "warn")

def _record_auth_success(client_ip):
    with _lock_lock:
        lock_ok(_lock_state, client_ip)

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

def login_ui_html(input_id, nonce=""):
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
    skin = (
        ".lg-screen{position:fixed;inset:0;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;"
        "gap:14px;box-sizing:border-box;padding:24px 16px 56px;background:#070b13;color:#e6edf6;"
        "font-family:'Readex Pro',Arial,Helvetica,sans-serif}"
        ".lg-screen.hidden,.lg-screen[hidden]{display:none}"
        ".lg-card{box-sizing:border-box;width:100%;max-width:320px;margin:0;padding:25.6px 22.4px 19.2px;background:#121a29;"
        "border:1px solid #2c3d5a;border-radius:10px;box-shadow:0 12px 40px rgba(0,0,0,.5);display:flex;flex-direction:column;"
        "gap:12px;text-align:center}"
        ".lg-form{margin:0;padding:0;display:flex;flex-direction:column;gap:12px}"
        ".lg-title{margin:0 0 4px;padding:0;font-family:inherit;font-size:18.4px;font-weight:700;line-height:1.2;"
        "letter-spacing:.02em;color:#ffd040;text-shadow:none}"
        "input.lg-in{box-sizing:border-box;width:100%;min-height:0;height:auto;margin:0;padding:9.6px 11.2px;font-family:inherit;"
        "font-size:15.2px;line-height:1.2;background:#0a1020;color:#fff;border:1px solid #2c3d5a;border-radius:6px;outline:none}"
        "input.lg-in:focus,input.lg-in:focus-visible{border-color:#ffd040;outline:none}"
        "button.lg-btn{box-sizing:border-box;width:100%;min-height:0;margin:0;padding:10.4px;font-family:inherit;font-size:14.4px;"
        "font-weight:700;line-height:1.2;letter-spacing:0;text-transform:none;background:#ffd040;color:#1a1300;border:0;"
        "border-radius:6px;cursor:pointer;box-shadow:none;text-shadow:none;filter:none;transition:none}"
        "button.lg-btn:hover:not(:disabled){background:#ffd040;color:#1a1300;filter:brightness(1.08);box-shadow:none}"
        "button.lg-btn:disabled{opacity:.5;cursor:default}"
        ".lg-msg{min-height:17.6px;margin:0;font-size:12.8px;line-height:1.3;color:#ff5d73;text-align:center}"
        ".lg-note{margin:0;max-width:300px;font-size:12.5px;color:#ff5d73}.lg-note:empty{display:none}"
        "button.lg-link{width:auto;min-height:0;margin:0 auto;padding:3.2px 8px;background:none;border:0;box-shadow:none;"
        "color:#8aa0bf;font-family:inherit;font-size:12.8px;text-decoration:underline;text-transform:none;letter-spacing:0;cursor:pointer}"
        ".lg-license{position:absolute;left:0;right:0;bottom:14px;text-align:center;font-size:11.5px;letter-spacing:.04em;color:#7d8aa0}"
        ".lg-license a{color:#6cb6ff}"
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
    return "<style%s>%s</style><script%s>%s</script>" % (attr, skin + css, attr, js)

def login_ui_inject(html, input_id, nonce=""):
    head, sep, tail = html.rpartition("</body>")
    if not sep:
        return html
    return head + login_ui_html(input_id, nonce) + sep + tail

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

def rpt_scan(text):
    import re
    hdr = re.compile(r"^\s*\[([^\]]+)\]\s*(\([^)]*\))?")
    rxline = re.compile(r"^\s*rxchannel\s*=>?\s*([^;\s]+)", re.I)
    usrp = re.compile(r"USRP/[^:\s]+:(\d+):(\d+)", re.I)
    lines = text.split("\n")
    secs = []
    for i, line in enumerate(lines):
        m = hdr.match(line)
        if m:
            if secs:
                secs[-1]["end"] = i
            secs.append({"name": m.group(1).strip(), "start": i, "end": len(lines),
                         "template": (m.group(2) or "").replace(" ", "")})
    used = set()
    ports = set()
    notes = {}
    rx = {}
    nodes_sec = None
    for s in secs:
        name = s["name"]
        if name.isdigit():
            used.add(name)
        elif name.lower().startswith("functions") and name[9:].isdigit():
            used.add(name[9:])
        if name.lower() == "nodes":
            nodes_sec = s
            for i in range(s["start"] + 1, s["end"]):
                body = lines[i].split(";", 1)[0]
                key = body.split("=", 1)[0].strip()
                if "=" in body and key.isdigit():
                    used.add(key)
        for i in range(s["start"] + 1, s["end"]):
            m = rxline.match(lines[i])
            if m:
                rx[name] = m.group(1)
                u = usrp.match(m.group(1))
                if u:
                    ports.update((int(u.group(1)), int(u.group(2))))
        notes[name] = lines[s["start"] - 1].strip() if s["start"] > 0 else ""
    return {"lines": lines, "secs": secs, "used": used, "ports": ports, "notes": notes, "rx": rx,
            "nodes": nodes_sec}



_SESSION_COOKIE_NAME = "nodemon_session"
_SESS_POLICY = sess_policy("standard")
_FONTS = r"""@font-face{font-family:"Readex Pro";font-style:normal;font-weight:400;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2")}
@font-face{font-family:"Readex Pro";font-style:normal;font-weight:700;font-display:swap;src:url(data:font/woff2;base64,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) format("woff2")}"""


DEFAULT_CONFIG = {"port": PORT, "poll_sec": 3, "allow_wan": False, "main_node": ""}
_config = dict(DEFAULT_CONFIG)
_config_lock = threading.Lock()


def _parse_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _clamp_int(value, lo, hi, default):
    try:
        n = int(str(value).strip())
    except ValueError:
        return default
    return n if lo <= n <= hi else default


def _cfg_get(key):
    with _config_lock:
        return _config[key]


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(CONFIG_PATH, encoding="utf-8")
    except (configparser.Error, OSError) as exc:
        log_event(f"Config: {CONFIG_PATH} could not be read ({exc}); using defaults", "warn")
    if cp.has_section(CONFIG_SECTION):
        sec = cp[CONFIG_SECTION]
        cfg["port"] = _clamp_int(sec.get("port", ""), 1024, 65535, PORT)
        cfg["poll_sec"] = _clamp_int(sec.get("poll_sec", ""), POLL_MIN_SEC, POLL_MAX_SEC, 3)
        cfg["allow_wan"] = _parse_bool(sec.get("allow_wan", "off"))
        node = sec.get("main_node", "").strip()
        cfg["main_node"] = node if node.isdigit() else ""
    with _config_lock:
        _config.clear()
        _config.update(cfg)


def save_config(cfg):
    text = (f"[{CONFIG_SECTION}]\nport = {cfg['port']}\npoll_sec = {cfg['poll_sec']}\n"
            f"allow_wan = {'on' if cfg['allow_wan'] else 'off'}\nmain_node = {cfg['main_node']}\n")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    _atomic_write(CONFIG_PATH, text, 0o644)


def _is_private_node(name):
    return name.isdigit() and PRIVATE_MIN <= int(name) <= PRIVATE_MAX


_BRIDGE_KINDS = {34001: ("dvswitch", "DVSwitch bridge"), 34008: ("m17", "M17 bridge"),
                 34000: ("svx", "SvxLink bridge"), 34018: ("nodetalker", "Node Talker transmit")}
_BRIDGE_BY_NODE = {"1999": 34001, "1917": 34008, "1900": 34000, "1921": 34018}
_USRP_RX_RE = re.compile(r"USRP/[^:\s]+:(\d+):(\d+)", re.I)


def node_plan():
    try:
        with open(RPT_CONF, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        return {"ok": False, "error": f"{RPT_CONF}: {exc.strerror or exc}", "public": [], "private": [], "kind": {}}
    scan = rpt_scan(text)
    names = []
    for s in scan["secs"]:
        n = s["name"]
        if n.isdigit() and n not in names:
            names.append(n)
    public = [n for n in names if not _is_private_node(n)]
    private = [n for n in names if _is_private_node(n)]
    kind = {}
    for n in names:
        m = _USRP_RX_RE.match(scan["rx"].get(n, ""))
        port = int(m.group(1)) if m else _BRIDGE_BY_NODE.get(n)
        if port in _BRIDGE_KINDS:
            kind[n] = _BRIDGE_KINDS[port]
    want = _cfg_get("main_node")
    main = want if want in public else (public[0] if public else "")
    return {"ok": True, "error": "", "main": main, "public": public, "private": private, "kind": kind}


_MODE_NAMES = {"T": "Transceive", "R": "Monitor (receive only)", "C": "Connecting"}


def _int0(text):
    try:
        return int(text)
    except ValueError:
        return 0


def parse_xstat(lines):
    conns = []
    linked = {}
    alinks = {}
    vars_ = {}
    for ln in lines:
        if ln.startswith("Conn: "):
            parts = ln[6:].split()
            if len(parts) >= 6:
                conns.append({"node": parts[0], "peer": parts[1], "reconnects": _int0(parts[2]),
                              "direction": parts[3], "since": parts[4], "state": " ".join(parts[5:])})
        elif ln.startswith("LinkedNodes: "):
            for item in ln[13:].split(","):
                item = item.strip()
                if item and item != "<NONE>":
                    mode, num = (item[0], item[1:]) if not item[0].isdigit() else ("", item)
                    linked[num] = mode
        elif ln.startswith("Var: ") and "=" in ln:
            k, v = ln[5:].split("=", 1)
            vars_[k.strip()] = v.strip()
    for item in vars_.get("RPT_ALINKS", "").split(",")[1:]:
        item = item.strip()
        if len(item) >= 3 and item[-1] in "KU" and item[-2] in "TRC":
            alinks[item[:-2]] = (item[-2], item[-1])
    links = []
    seen = set()
    for c in conns:
        num = c["node"]
        seen.add(num)
        mode = linked.get(num) or (alinks.get(num) or ("", ""))[0]
        links.append(dict(c, mode=mode, mode_name=_MODE_NAMES.get(mode, ""),
                          keyed=(alinks.get(num) or ("", "U"))[1] == "K"))
    for num, mode in linked.items():
        if num not in seen:
            links.append({"node": num, "peer": "", "reconnects": 0, "direction": "", "since": "",
                          "state": "CONNECTING" if mode == "C" else "UNKNOWN", "mode": mode,
                          "mode_name": _MODE_NAMES.get(mode, ""), "keyed": False})
    return {"links": links, "txkeyed": vars_.get("RPT_TXKEYED") == "1", "rxkeyed": vars_.get("RPT_RXKEYED") == "1"}


_REG_ROW_RE = re.compile(r"^\s*(\S+)\s+(\d{4,7})\s+(\S+)\s+(\d+)\s+(.+?)\s*$")


def parse_registrations(lines):
    out = {}
    for ln in lines:
        if not ln.startswith("Output: "):
            continue
        m = _REG_ROW_RE.match(ln[8:])
        if m:
            out[m.group(2)] = {"host": m.group(1), "perceived": m.group(3), "refresh": _int0(m.group(4)),
                               "state": m.group(5)}
    return out


def parse_localnodes(lines):
    out = []
    for ln in lines:
        if ln.startswith("Output: "):
            tok = ln[8:].strip()
            if tok.isdigit() and tok not in out:
                out.append(tok)
    return out


IDLE_AFTER_SEC = 30.0
WAKE_WAIT_SEC = 4.0


class Monitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.snap = {"ok": False, "error": "starting", "at": 0.0, "banner": "", "loaded": [], "regs": {},
                     "nodes": {}, "idle": False}
        self.refused = None
        self.wake_event = threading.Event()
        self.last_ask = -1e9

    def touch(self):
        self.last_ask = time.monotonic()
        self.wake_event.set()

    def _wanted(self):
        return time.monotonic() - self.last_ask < IDLE_AFTER_SEC

    def waiting(self):
        with self.lock:
            return self.snap["idle"] or self.snap["error"] == "starting"

    def state(self):
        with self.lock:
            return json.loads(json.dumps(self.snap))

    def _put(self, **kw):
        with self.lock:
            self.snap.update(kw)

    def _down(self, error):
        with self.lock:
            was = self.snap["ok"]
            self.snap.update(ok=False, error=error, nodes={}, regs={}, loaded=[], idle=False)
        if was:
            log_event(f"Asterisk link lost ({error})", "warn")

    def _session(self, user, secret):
        sock = socket.create_connection((AMI_HOST, AMI_PORT), timeout=5)
        try:
            fh = sock.makefile("rb")
            banner = fh.readline(256).decode("utf-8", "replace").strip()
            if not banner.startswith("Asterisk Call Manager"):
                raise ValueError("that port is not the Asterisk manager")
            sock.sendall(_ami_msg(Action="Login", Username=user, Secret=secret, Events="off", ActionID="nmlogin"))
            reply = _ami_read_for(fh, "nmlogin")
            if "Response: Success" not in reply:
                if "Response: Error" in reply:
                    raise AmiRefused("Asterisk refused the AMI login")
                raise ValueError("the manager gave no answer to the login")
            self._put(banner=banner)
            if self.snap["idle"]:
                log_event("A page is open again: polling Asterisk again", "info")
            n = 0
            while True:
                n += 1
                plan = node_plan()
                nodes = [x for x in (plan["public"] + plan["private"])]

                def ask(**fields):
                    nonlocal n
                    n += 1
                    aid = f"nm{n}"
                    sock.sendall(_ami_msg(ActionID=aid, **fields))
                    return _ami_read_for(fh, aid)

                loaded = parse_localnodes(ask(Action="Command", Command="rpt localnodes"))
                regs = parse_registrations(ask(Action="Command", Command="rpt show registrations"))
                out = {}
                for node in nodes:
                    reply = ask(Action="RptStatus", Command="XStat", Node=node)
                    if "Response: Success" in reply:
                        out[node] = dict(parse_xstat(reply), ok=True, error="")
                    else:
                        msg = next((x[9:] for x in reply if x.startswith("Message: ")), "no answer")
                        out[node] = {"links": [], "txkeyed": False, "rxkeyed": False, "ok": False, "error": msg}
                with self.lock:
                    first = not self.snap["ok"]
                    self.snap.update(ok=True, error="", at=time.time(), loaded=loaded, regs=regs, nodes=out, idle=False)
                if first:
                    log_event(f"Link state from Asterisk (AMI {AMI_HOST}:{AMI_PORT}): {banner}", "ok")
                time.sleep(_cfg_get("poll_sec"))
                if not self._wanted():
                    self._put(idle=True)
                    log_event("No page is open: Asterisk is not polled until one is", "info")
                    return
        finally:
            sock.close()

    def loop(self):
        while True:
            if not self._wanted():
                self.wake_event.clear()
                if not self._wanted():
                    self.wake_event.wait()
                continue
            user, secret = ami_credentials(AMI_CONF)
            if not user or not secret:
                self._down(f"no AMI login found in {AMI_CONF}")
            elif self.refused == (user, secret):
                self._down(f"Asterisk refused the AMI login for {user} in {AMI_CONF}")
            else:
                try:
                    self._session(user, secret)
                    continue
                except AmiRefused as exc:
                    self.refused = (user, secret)
                    self._down(f"{exc} for {user} in {AMI_CONF}")
                except (OSError, ValueError) as exc:
                    self._down(f"AMI {AMI_HOST}:{AMI_PORT}: {exc}")
            time.sleep(AMI_RETRY_SEC)


MON = Monitor()

_unit_cache = {}


def unit_active(name):
    now = time.monotonic()
    hit = _unit_cache.get(name)
    if hit and now - hit[0] < 5.0:
        return hit[1]
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5)
        val = r.stdout.strip() == "active"
    except (OSError, subprocess.TimeoutExpired):
        val = None
    _unit_cache[name] = (now, val)
    return val


def _gateway(kind, state, text, detail="", source=""):
    return {"kind": kind, "state": state, "text": text, "detail": detail, "source": source}


def _root_owned(path):
    try:
        return os.stat(path).st_uid == 0
    except OSError:
        return False


def read_dvswitch():
    last = None
    try:
        files = [f for f in glob.glob(ABINFO_GLOB) if _root_owned(f)]
        if files:
            with open(max(files, key=os.path.getmtime), encoding="utf-8", errors="replace") as fh:
                d = json.load(fh)
            last = str(d.get("last_tune", "")) if isinstance(d, dict) else ""
    except (OSError, ValueError):
        last = None
    active = unit_active(UNIT_AB)
    src = "Analog_Bridge status file"
    if active is False and last is None:
        return _gateway("dvswitch", "unknown", "DVSwitch is not running", source=src)
    if last is None:
        return _gateway("dvswitch", "unknown", "no Analog_Bridge status file", source=src)
    if active is False:
        return _gateway("dvswitch", "down", "Analog_Bridge is stopped", last, src)
    if not last.strip() or last.strip() in ("0", "4000"):
        return _gateway("dvswitch", "idle", "nothing tuned", last, src)
    return _gateway("dvswitch", "connected", last, "", src)


def _ini_read(path):
    out = {}
    sec = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    sec = line[1:-1].strip().lower()
                elif "=" in line and not line.startswith((";", "#")):
                    k, _, v = line.partition("=")
                    out.setdefault(sec, {})[k.strip().lower()] = v.strip()
    except OSError:
        return None
    return out


def read_m17():
    src = "USRP2M17 settings"
    ini = _ini_read(M17_INI)
    if ini is None:
        return _gateway("m17", "unknown", "M17 is not installed", source=src)
    net = ini.get("m17 network", {})
    name = net.get("name", "")
    addr = net.get("address", "")
    active = unit_active(UNIT_M17)
    if active is False:
        return _gateway("m17", "down", "USRP2M17 is stopped", name, src)
    if not name:
        return _gateway("m17", "idle", "no reflector set", "", src)
    return _gateway("m17", "connected", name, addr, src)


_SVX_TAIL_RE = re.compile(r"^(?:\w{3} \w{3}\s+\d+ [\d:]+ \d{4}: )(.*)$")


def svx_events(lines):
    state = ""
    tg = ""
    host = ""
    link = True
    for raw in lines:
        m = _SVX_TAIL_RE.match(raw.rstrip())
        text = m.group(1) if m else raw.strip()
        if text.startswith("ReflectorLogic: Authentication OK"):
            state = "connected"
        elif text.startswith("ReflectorLogic: Disconnected from "):
            state = "down"
            host = text[len("ReflectorLogic: Disconnected from "):].split(":", 2)
            host = ":".join(host[:2]).strip()
        elif text.startswith("NOTICE[ReflectorLogic]: Connected to "):
            host = text.split("Connected to ", 1)[1].split(" ", 1)[0]
        elif text.startswith("ReflectorLogic: Connecting to"):
            state = state or "connecting"
        else:
            mt = re.match(r"ReflectorLogic: Selecting TG #(\d+)", text)
            if mt:
                tg = mt.group(1)
            else:
                ml = re.match(r"(?:(De)a|A)ctivating link '?ReflectorLink'?", text)
                if ml:
                    link = not ml.group(1)
    return {"state": state, "tg": tg, "host": host, "link": link}


def read_svx():
    src = "SvxLink log"
    conf = _ini_read(SVX_CONF)
    if conf is None:
        return _gateway("svx", "unknown", "SvxLink is not installed", source=src)
    rl = conf.get("reflectorlogic", {})
    where = rl.get("hosts", "")
    if where and rl.get("host_port"):
        where += ":" + rl["host_port"]
    active = unit_active(UNIT_SVX)
    if active is False:
        return _gateway("svx", "down", "SvxLink is stopped", where, src)
    try:
        with open(SVX_LOG, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - SVX_LOG_TAIL))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return _gateway("svx", "unknown", "SvxLink log not readable", where, src)
    ev = svx_events(lines)
    if not ev["state"]:
        return _gateway("svx", "unknown", "no reflector login in the log yet", where, src)
    if ev["state"] != "connected":
        return _gateway("svx", ev["state"], "not logged in to the reflector", ev["host"] or where, src)
    if not ev["link"]:
        return _gateway("svx", "idle", "reflector link is off", where, src)
    tg = ev["tg"]
    text = ("TG " + tg) if tg and tg != "0" else "no talkgroup selected"
    return _gateway("svx", "connected" if tg and tg != "0" else "idle", text, where, src)


_READERS = {"dvswitch": read_dvswitch, "m17": read_m17, "svx": read_svx}


def gateway_for(kind):
    fn = _READERS.get(kind)
    if fn is None:
        return None
    try:
        return fn()
    except Exception as exc:
        return _gateway(kind, "unknown", f"could not read the status ({exc.__class__.__name__})")


def _link_view(link, kinds, gateways):
    row = dict(link)
    kind = kinds.get(link["node"])
    row["gateway"] = gateways.get(kind[0]) if kind else None
    row["bridge"] = kind[1] if kind else ""
    return row


TOOL_LINKS = (
    ("nodecontrol", "Node Controller", 8989, "http", "/"),
    ("sysmon", "SysMon", 9999, "http", "/"),
    ("instmon", "instmon", 8990, "http", "/"),
    ("wifimon", "wifimon", 8991, "http", "/"),
    ("44helper", "44helper", 9997, "http", "/"),
    ("nodetalker", "Node Talker", 8993, "http", "/"),
    ("noderecorder", "Node Recorder", 8995, "http", "/"),
    ("pibrary", "Pibrary", 9000, "http", "/"),
    ("termon", "Terminal Monitor", 7878, "https", "/"),
    ("cockpit", "Cockpit", 9090, "https", "/"),
)
WEB_PAGES = (("dvswitch", "DVSwitch", "/dvswitch/"),)
LINK_TTL_SEC = 15.0
_links_cache = {"t": -1e9, "v": []}


def port_open(port, timeout=0.3):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def page_answers(path, port=80, timeout=0.5):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("HEAD", path)
        return conn.getresponse().status < 400
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def quick_links():
    now = time.monotonic()
    if now - _links_cache["t"] < LINK_TTL_SEC:
        return _links_cache["v"]
    own = _cfg_get("port")
    out = []
    for key, label, port, scheme, path in TOOL_LINKS:
        if port != own and port_open(port):
            out.append({"key": key, "label": label, "port": port, "scheme": scheme, "path": path})
    for key, label, path in WEB_PAGES:
        if page_answers(path):
            out.append({"key": key, "label": label, "port": 80, "scheme": "http", "path": path})
    _links_cache.update(t=now, v=out)
    return out


def build_status(authed=True):
    if authed:
        MON.touch()
        end = time.monotonic() + WAKE_WAIT_SEC
        while MON.waiting() and time.monotonic() < end:
            time.sleep(0.1)
    plan = node_plan()
    snap = MON.state()
    kinds = plan["kind"]
    gateways = {}
    for _node, (kind, _label) in kinds.items():
        if kind not in gateways:
            g = gateway_for(kind)
            if g is not None:
                gateways[kind] = g
    loaded = set(snap["loaded"])
    out = {"version": VERSION, "ami": {"ok": snap["ok"], "error": snap["error"], "banner": snap["banner"],
                                        "age": (time.time() - snap["at"]) if snap["at"] else None},
           "plan": {"ok": plan["ok"], "error": plan["error"]}, "main": None, "private": [],
           "gateways": gateways, "poll_sec": _cfg_get("poll_sec"), "links": quick_links() if authed else []}
    if not plan["ok"]:
        return out

    def node_view(node, role):
        st = snap["nodes"].get(node)
        kind = kinds.get(node)
        view = {"node": node, "role": role, "bridge": kind[1] if kind else "", "kind": kind[0] if kind else "",
                "loaded": (node in loaded) if snap["ok"] else None,
                "ok": bool(st and st["ok"]), "error": (st or {}).get("error", "") if snap["ok"] else snap["error"],
                "txkeyed": bool(st and st["txkeyed"]), "rxkeyed": bool(st and st["rxkeyed"]),
                "links": [_link_view(link, kinds, gateways) for link in (st or {}).get("links", [])]}
        if kind and kind[0] in gateways:
            view["gateway"] = gateways[kind[0]]
        return view

    if plan["main"]:
        main = node_view(plan["main"], "main")
        reg = snap["regs"].get(plan["main"])
        main["registration"] = reg if reg else ({"state": "not listed"} if snap["ok"] else None)
        out["main"] = main
    out["private"] = [node_view(n, "private") for n in plan["private"]]
    return out


_cmd_lock = threading.Lock()
_NODE_RE = re.compile(r"^\d{1,7}$")
_TEXT_RE = re.compile(r"^[A-Za-z0-9 .,:;!?_@#()/+=-]{1,100}$")

COMMANDS = (
    {"op": 3, "label": "Connect: transceive", "group": "Connect", "target": "node"},
    {"op": 2, "label": "Connect: monitor only", "group": "Connect", "target": "node"},
    {"op": 8, "label": "Connect: local monitor only", "group": "Connect", "target": "node"},
    {"op": 1, "label": "Disconnect a link", "group": "Disconnect", "target": "node"},
    {"op": 6, "label": "Disconnect all links", "group": "Disconnect", "target": "none",
     "confirm": "Disconnect every link on this node?"},
    {"op": 16, "label": "Reconnect the links dropped by Disconnect all", "group": "Disconnect", "target": "none"},
    {"op": 13, "label": "Permanent link: transceive", "group": "Permanent links", "target": "node",
     "confirm": "Make this link permanent? It comes back after a restart."},
    {"op": 12, "label": "Permanent link: monitor only", "group": "Permanent links", "target": "node",
     "confirm": "Make this link permanent? It comes back after a restart."},
    {"op": 18, "label": "Permanent link: local monitor only", "group": "Permanent links", "target": "node",
     "confirm": "Make this link permanent? It comes back after a restart."},
    {"op": 11, "label": "Disconnect a permanent link", "group": "Permanent links", "target": "node",
     "confirm": "Disconnect this permanent link?"},
    {"op": 4, "label": "Enter command mode on a link", "group": "Other", "target": "node"},
    {"op": 9, "label": "Send a text message (node, or 0 for all links)", "group": "Other", "target": "node0",
     "text": True},
    {"op": 5, "label": "System status (announced on the air)", "group": "Announce on the air", "target": "none",
     "confirm": "This makes the node transmit its status on the air. Continue?"},
    {"op": 7, "label": "Last node to key up (announced on the air)", "group": "Announce on the air",
     "target": "none", "confirm": "This makes the node transmit on the air. Continue?"},
    {"op": 15, "label": "Full system status (announced on the air)", "group": "Announce on the air",
     "target": "none", "confirm": "This makes the node transmit on the air. Continue?"},
    {"op": 17, "label": "MDC test (announced on the air)", "group": "Announce on the air", "target": "none",
     "confirm": "This makes the node transmit a test on the air. Continue?"},
)
_COMMAND_BY_OP = {c["op"]: c for c in COMMANDS}


def ami_command(line):
    user, secret = ami_credentials(AMI_CONF)
    if not user or not secret:
        raise OSError(f"no AMI login found in {AMI_CONF}")
    with _cmd_lock:
        sock = socket.create_connection((AMI_HOST, AMI_PORT), timeout=5)
        try:
            fh = sock.makefile("rb")
            if not fh.readline(256).startswith(b"Asterisk Call Manager"):
                raise OSError("that port is not the Asterisk manager")
            sock.sendall(_ami_msg(Action="Login", Username=user, Secret=secret, Events="off", ActionID="nclogin"))
            if "Response: Success" not in _ami_read_for(fh, "nclogin"):
                raise OSError("Asterisk refused the AMI login")
            sock.sendall(_ami_msg(Action="Command", Command=line, ActionID="nccmd"))
            reply = _ami_read_for(fh, "nccmd")
            try:
                sock.sendall(_ami_msg(Action="Logoff", ActionID="nclogoff"))
            except OSError:
                pass
            return reply
        finally:
            sock.close()


def command_line(body):
    plan = node_plan()
    if not plan["ok"]:
        return None, plan["error"]
    node = str(body.get("node", "")).strip()
    if node not in plan["public"] + plan["private"]:
        return None, f"Node {node[:12] or '?'} is not a node on this server."
    try:
        op = int(body.get("op"))
    except (TypeError, ValueError):
        return None, "Pick a command."
    cmd = _COMMAND_BY_OP.get(op)
    if cmd is None:
        return None, "Unknown command."
    parts = ["rpt", "cmd", node, "ilink", str(op)]
    target = str(body.get("target", "")).strip()
    if cmd["target"] in ("node", "node0"):
        if not _NODE_RE.match(target) or (target == "0" and cmd["target"] != "node0"):
            return None, "Type or pick the node number to use."
        if target == node:
            return None, "A node cannot be linked to itself."
        parts.append(target)
    elif target:
        return None, "This command takes no node."
    if cmd.get("text"):
        text = str(body.get("text", "")).strip()
        if not _TEXT_RE.match(text):
            return None, "Type a message of up to 100 letters, digits and simple punctuation."
        parts.append(text)
    return " ".join(parts), cmd


def run_command(body, who="?"):
    line, cmd = command_line(body)
    if line is None:
        return {"ok": False, "error": cmd}
    try:
        reply = ami_command(line)
    except (OSError, ValueError) as exc:
        log_event(f"Command from {who} failed ({line}): {exc}", "err")
        return {"ok": False, "error": f"Asterisk could not be reached: {exc}"}
    out = [x[8:].strip() for x in reply if x.startswith("Output: ")]
    out = [x for x in out if x]
    if "Response: Success" not in reply or out:
        msg = " ".join(out) or next((x[9:] for x in reply if x.startswith("Message: ")), "Asterisk refused it.")
        log_event(f"Command from {who}: {line}: {msg}", "warn")
        return {"ok": False, "error": msg}
    log_event(f"Command from {who}: {line}", "ok")
    return {"ok": True, "message": f"Sent: {cmd['label']}. The link table shows what happened.", "line": line}


POWER_CMDS = {"reboot": (["reboot"], "Rebooting..."), "shutdown": (["shutdown", "-h", "now"], "Shutting down...")}


def system_power(what, who="?"):
    if what not in POWER_CMDS:
        return {"ok": False, "error": "Unknown action."}
    cmd, message = POWER_CMDS[what]
    if os.geteuid() != 0:
        return {"ok": False, "error": f"root required for {what}"}
    log_event(f"System {what} requested from {who}", "warn")

    def go():
        time.sleep(1)
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log_event(f"System {what} failed: {exc}", "err")

    threading.Thread(target=go, daemon=True).start()
    return {"ok": True, "message": message}


def _discon_one(plan, node, who):
    kind = (plan["kind"].get(node) or ("", ""))[0]
    r = run_command({"node": node, "op": 6}, who)
    if not r["ok"]:
        return False, "links not dropped: " + r["error"]
    text = "links dropped"
    if kind == "nodetalker":
        text += "; Node Talker's transmit link stays down until Node Talker links it again"
    return True, text


def discon_all(plan, who):
    main = plan["main"]
    snap = MON.state()
    keep = []
    for link in (snap["nodes"].get(main) or {}).get("links", []):
        kind = plan["kind"].get(link["node"])
        if kind and kind[0] == "nodetalker" and link["node"] not in keep:
            keep.append(link["node"])
    parts = []
    bad = False
    for node in plan["private"]:
        kind = (plan["kind"].get(node) or ("", ""))[0]
        if kind == "nodetalker" or (snap["ok"] and node not in snap["loaded"]):
            continue
        ok, text = _discon_one(plan, node, who)
        bad = bad or not ok
        parts.append(f"{node}: {text}")
    r = run_command({"node": main, "op": 6}, who)
    if r["ok"]:
        parts.append(f"{main}: links dropped")
    else:
        bad = True
        parts.append(f"{main}: links not dropped: {r['error']}")
    if keep and r["ok"]:
        time.sleep(1.0)
        again = [n for n in keep if run_command({"node": main, "op": 3, "target": n}, who)["ok"]]
        if again:
            parts.append("Node Talker's transmit node " + ", ".join(again) + " linked again")
    return not bad, "; ".join(parts)


def node_discon(node, who="?"):
    plan = node_plan()
    if not plan["ok"]:
        return {"ok": False, "error": plan["error"]}
    node = str(node or "").strip()
    if node not in plan["public"] + plan["private"]:
        return {"ok": False, "error": f"Node {node[:12] or '?'} is not a node on this server."}
    if node == plan["main"]:
        ok, text = discon_all(plan, who)
        log_event(f"Disconnect all from {who}: {text}", "warn")
        return {"ok": True, "message": "Everything disconnected. " + text + "."} if ok else \
            {"ok": False, "error": "Not everything could be disconnected. " + text + "."}
    ok, text = _discon_one(plan, node, who)
    log_event(f"Disconnect node {node} from {who}: {text}", "warn")
    return {"ok": True, "message": f"Node {node}: {text}."} if ok else \
        {"ok": False, "error": f"Node {node}: {text}."}


_CSS = r""":root{--bg:#0d1117;--surface:#161e2e;--surface2:#1e2a3f;--border:#2e4060;--border2:#3a5278;--amber:#ffd040;--green:#00ffb0;--red:#ff3d5a;--blue:#22d4ff;--teal:#00ffe5;--lime:#d4ff00;--orange:#ffaa22;--text:#ffffff;--text-bright:#f0f8ff;--sans:"Readex Pro",Arial,Helvetica,sans-serif;--mono:ui-monospace,Menlo,Consolas,"DejaVu Sans Mono",monospace;--fs-xs:.66rem;--fs-sm:.72rem;--fs-base:.8rem;--fs-md:.9rem;--fs-lg:1rem}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:var(--fs-base);min-height:100vh;padding-bottom:3rem}
button,input,select{font-family:var(--sans)}
header{background:linear-gradient(90deg,#0f1a2e,#161e2e 50%,#0f1a2e);border-bottom:2px solid var(--amber);padding:.45rem 1rem;display:flex;align-items:center;justify-content:space-between;gap:.5rem;position:sticky;top:0;z-index:100;box-shadow:0 2px 0 rgba(255,208,64,.25),0 6px 30px rgba(0,0,0,.7)}
.logo{font-size:1.21rem;color:var(--amber);letter-spacing:.1em;text-shadow:0 0 10px rgba(255,208,64,.9),0 0 30px rgba(255,208,64,.5)}
.logo-sub{font-size:.715rem;letter-spacing:.22em;text-transform:uppercase;color:var(--amber);margin-top:.1rem}
.hdr-right{display:flex;flex-direction:column;align-items:flex-end;white-space:nowrap;line-height:1.4;gap:.2rem}
.ver{font-size:var(--fs-sm);color:var(--text)}
.pill{font-size:var(--fs-sm);padding:.15rem .6rem;border-radius:999px;border:1px solid var(--border2);background:var(--surface2);color:var(--text);cursor:pointer}
.hidden{display:none!important}
main{padding:.6rem 1rem;max-width:1100px;margin:0 auto}
.tabs{display:flex;flex-wrap:nowrap;overflow-x:auto;gap:.3rem;padding:.6rem 0 1px;scrollbar-width:none;border-bottom:1px solid var(--border)}
.tabs::-webkit-scrollbar{display:none}
.tab{font-size:.9rem;font-weight:bold;letter-spacing:.08em;text-transform:uppercase;padding:.52rem 1.1rem;border-radius:5px 5px 0 0;border:1px solid var(--border2);border-bottom:none;background:var(--surface2);color:#fff;cursor:pointer;flex-shrink:0;user-select:none}
.tab:hover{background:#253550;border-color:#5a7898}
.tab.active{color:var(--mc);border-color:var(--mc);background:rgba(var(--mc-rgb),.18);box-shadow:0 -2px 18px rgba(var(--mc-rgb),.35);text-shadow:0 0 14px rgba(var(--mc-rgb),1)}
.t-ov{--mc:var(--orange);--mc-rgb:255,170,34}
.t-main{--mc:var(--teal);--mc-rgb:0,255,229}
.t-conn{--mc:var(--amber);--mc-rgb:255,208,64}
.t-priv{--mc:var(--lime);--mc-rgb:212,255,0}
.t-log{--mc:var(--blue);--mc-rgb:34,212,255}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:.7rem .8rem;margin-top:.7rem}
.card h2{font-size:var(--fs-md);color:var(--amber);letter-spacing:.06em;margin-bottom:.45rem;display:flex;gap:.6rem;align-items:center;flex-wrap:wrap}
.row{display:flex;flex-wrap:wrap;gap:.35rem 1.1rem;align-items:center;margin:.25rem 0}
.k{color:#9db4d0;font-size:var(--fs-sm)}
.mono{font-family:var(--mono)}
.badge{display:inline-block;font-size:var(--fs-xs);font-weight:bold;letter-spacing:.06em;text-transform:uppercase;padding:.12rem .5rem;border-radius:4px;border:1px solid currentColor}
.s-connected,.s-ok,.s-ESTABLISHED,.s-registered{color:var(--green)}
.s-connecting,.s-CONNECTING,.s-warn{color:var(--amber)}
.s-down,.s-err{color:var(--red)}
.s-idle{color:var(--blue)}
.s-unknown{color:#aab8cc}
.banner{margin-top:.7rem;padding:.45rem .7rem;border-radius:6px;border:1px solid;font-size:var(--fs-base)}
.banner.ok{color:var(--green);border-color:rgba(0,255,176,.4);background:rgba(0,255,176,.07)}
.banner.warn{color:var(--amber);border-color:rgba(255,208,64,.4);background:rgba(255,208,64,.07)}
.banner.err{color:var(--red);border-color:rgba(255,61,90,.45);background:rgba(255,61,90,.08)}
.scroll{overflow-x:auto;margin-top:.3rem}
table{border-collapse:collapse;width:100%;min-width:560px}
th,td{text-align:left;padding:.35rem .55rem;border-bottom:1px solid var(--border);font-size:var(--fs-base);white-space:nowrap}
th{color:var(--amber);font-size:var(--fs-sm);letter-spacing:.06em;text-transform:uppercase}
td.mono{font-family:var(--mono)}
.empty{color:#aab8cc;padding:.4rem 0}
.keyed{color:var(--lime)}
.r{text-align:right}
.btn.discon{padding:.3rem .8rem;font-size:var(--fs-sm)}
@media (max-width:600px) and (orientation:portrait){.nodes-tbl{min-width:0;width:100%}.nodes-tbl th,.nodes-tbl td{padding:.35rem .3rem}.nodes-tbl td:nth-child(2){white-space:normal}.nodes-tbl .btn.discon{padding:.3rem .5rem;font-size:.7rem}.nodes-tbl th:nth-child(4),.nodes-tbl td:nth-child(4),.nodes-tbl th:nth-child(5),.nodes-tbl td:nth-child(5){display:none}}
.sec-lbl{font-size:.66rem;letter-spacing:.28em;text-transform:uppercase;color:#fff;margin:1rem 0 .3rem}
.btn{padding:.48rem 1rem;border-radius:4px;border:1px solid;background:transparent;cursor:pointer;transition:all .14s;white-space:nowrap;font-size:var(--fs-base)}
.btn:hover{filter:brightness(1.6);box-shadow:0 0 12px currentColor}
.btn:active{transform:scale(.95)}
.btn:disabled{opacity:.5;cursor:default}
.btn-red{color:var(--red);border-color:#6b0e20}
.btn-muted{color:#fff;border-color:var(--border2)}
.act-bar{padding:.65rem .9rem;display:flex;flex-wrap:wrap;gap:.4rem;border-top:1px solid var(--border);background:#131c2d;position:sticky;bottom:0;border-radius:6px}
.act-bar .btn{flex:1;min-width:8rem;text-align:center}
.sysmsg{font-size:var(--fs-sm);min-height:1.2em;margin-top:.3rem}
.sysmsg.ok{color:var(--green)}
.sysmsg.err{color:var(--red)}
@media (max-width:560px){.act-bar{flex-direction:column}.act-bar .btn{min-width:0}}
.ql-row{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 2px}
.ql{font-family:var(--mono);font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;text-decoration:none;white-space:nowrap;color:var(--amber);border:1px solid rgba(244,192,78,.45);background:rgba(255,61,90,.15);text-shadow:0 0 8px rgba(255,208,64,.4);border-radius:4px;padding:8px 12px;cursor:pointer;transition:all .14s}
.ql:hover{filter:brightness(1.5);box-shadow:0 0 10px currentColor}
.ql:active{transform:scale(.95)}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.5rem;margin-top:.3rem}
.sum .box{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:.45rem .6rem}
.sum .box .n{font-size:1.15rem;font-weight:bold;color:var(--text-bright)}
.sum .box.lit{border-color:#b8860b;background:rgba(255,208,64,.12);box-shadow:0 0 18px rgba(255,208,64,.22)}
.sum .box.lit .n{color:var(--amber);text-shadow:0 0 14px rgba(255,208,64,1)}
tr.lit td{background:rgba(255,208,64,.10)}
tr.lit td:first-child{border-left:3px solid #b8860b;color:var(--amber);font-weight:bold;text-shadow:0 0 14px rgba(255,208,64,1)}
tr.hot td{background:rgba(255,61,90,.7);color:var(--amber);text-shadow:0 0 8px rgba(255,208,64,.4)}
tr.hot td:first-child{border-left-color:var(--amber)}
tr.hot .badge,tr.hot .btn{text-shadow:none}
.sum .box .t{font-size:var(--fs-xs);letter-spacing:.08em;text-transform:uppercase;color:#9db4d0}
.cmdbar{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
.cmdbar select,.cmdbar input{background:var(--surface2);color:var(--text);border:1px solid var(--border2);border-radius:5px;padding:.3rem .5rem;font-size:var(--fs-base);max-width:100%}
.cmdbar input{width:9rem}
.cmdbar input.msg{width:15rem}
.cmdbar select:focus,.cmdbar input:focus{outline:2px solid var(--amber);outline-offset:1px}
.cmdbar .go{background:rgba(255,208,64,.16);border-color:var(--amber);color:var(--amber);font-weight:bold}
.cmdbar .go:disabled{opacity:.5;cursor:default}
.cmdres{font-size:var(--fs-sm)}
.cmdres.ok{color:var(--green)}
.cmdres.err{color:var(--red)}
.logbox{background:#080c12;border:1px solid var(--border);border-radius:6px;padding:.5rem;font-family:var(--mono);font-size:var(--fs-sm);max-height:60vh;overflow:auto;white-space:pre-wrap;word-break:break-word}
.logbox .l-warn{color:var(--amber)}
.logbox .l-err{color:var(--red)}
.logbox .l-ok{color:var(--green)}
#login-screen{display:none}
#login-screen.open{display:flex}
@media (max-width:600px){main{padding:.5rem 16px}header{padding:.45rem 16px}.tab{padding:.45rem .8rem;font-size:.82rem}}
"""

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Node Monitor</title>
<style nonce="__NONCE__">__FONTS__
__CSS__</style>
</head>
<body>
<header><div class="hdr-left"><div class="logo">Node Monitor</div><div class="logo-sub" id="hdr-node"></div></div>
<div class="hdr-right"><span class="ver">v__VERSION__</span><button id="logout" class="pill hidden" type="button">Log Out</button></div></header>
<div id="login-screen" class="lg-screen">
<div id="login-card" class="lg-card">
<h2 class="lg-title">Node Monitor</h2>
<form id="login-form" class="lg-form">
<input class="lg-in" type="password" id="pw" placeholder="Password" autocomplete="current-password" aria-label="Password" required>
<button class="lg-btn" id="login-btn" type="submit">Log in</button>
</form>
<div id="login-msg" class="lg-msg"></div>
</div>
<div class="lg-license">Node Monitor · <a href="https://creativecommons.org/licenses/by-nc/4.0/" target="_blank" rel="noopener">CC BY-NC 4.0</a></div>
</div>
<main id="app" class="hidden">
<div class="tabs" id="tabs" role="tablist">
<div class="tab t-ov active" id="tab-ov" data-tab="ov" role="tab">Overview</div>
<div class="tab t-main" id="tab-main" data-tab="main" role="tab">Main node</div>
<div class="tab t-conn" id="tab-conn" data-tab="conn" role="tab">Connections</div>
<div class="tab t-priv" id="tab-priv" data-tab="priv" role="tab">Private nodes</div>
<div class="tab t-log" id="tab-log" data-tab="log" role="tab">Log</div>
</div>
<div id="status-banner"></div>
<section id="pg-ov"></section>
<section id="pg-main" class="hidden"></section>
<section id="pg-conn" class="hidden"></section>
<section id="pg-priv" class="hidden"></section>
<section id="pg-log" class="hidden"><div class="card"><h2>Node Monitor log</h2><div class="logbox" id="logbox"></div></div></section>
<div id="sysbar">
<div class="sec-lbl">System</div>
<div class="act-bar">
<button class="btn btn-muted" id="sys-disc" type="button">Disconnect All</button>
<button class="btn btn-red" id="sys-reboot" type="button">Reboot</button>
<button class="btn btn-muted" id="sys-shutdown" type="button">Shutdown</button>
</div>
<div class="sysmsg" id="sysmsg" role="status"></div>
</div>
</main>
<script nonce="__NONCE__">__JS__</script>
</body>
</html>
"""

_JS = r"""const $ = (id) => document.getElementById(id);
let authed = false, current = 'ov', status = null, logSince = 0, timer = null, COMMANDS = [];
const bars = {};
const discoBusy = {};
let disconMsg = null;
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function badge(state, text) { return el('span', 'badge s-' + state, text || state); }
async function api(path, opts) {
  const o = opts || {};
  const init = {method: o.method || 'GET', headers: {'X-Requested-With': 'XMLHttpRequest'}};
  if (o.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(o.body); }
  try {
    const r = await fetch(path, init);
    let d = {};
    try { d = await r.json(); } catch (e) { d = {}; }
    if (r.status === 401 && path !== '/api/login' && authed) { authed = false; render(); }
    return d;
  } catch (e) { return {ok: false, error: 'Server unreachable.'}; }
}
function render() {
  const wasOpen = $('login-screen').classList.contains('open');
  $('login-screen').classList.toggle('open', !authed);
  $('app').classList.toggle('hidden', !authed);
  $('logout').classList.toggle('hidden', !authed);
  if (!authed && !wasOpen) $('pw').focus();
  if (authed) poll(); else if (timer) { clearTimeout(timer); timer = null; }
}
async function login(ev) {
  ev.preventDefault();
  $('login-btn').disabled = true;
  $('login-msg').textContent = '';
  const d = await api('/api/login', {method: 'POST', body: {password: $('pw').value}});
  $('login-btn').disabled = false;
  $('pw').value = '';
  if (d.ok) { authed = true; await loadCommands(); render(); } else $('login-msg').textContent = d.error || 'Login failed.';
}
async function logout() { await api('/api/logout', {method: 'POST', body: {}}); authed = false; render(); }
function showTab(name) {
  current = name;
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  ['ov', 'main', 'conn', 'priv', 'log'].forEach((n) => $('pg-' + n).classList.toggle('hidden', n !== name));
  if (name === 'log') pollLog();
}
function kv(label, node) {
  const r = el('div', 'row');
  r.appendChild(el('span', 'k', label));
  if (typeof node === 'string') r.appendChild(el('span', '', node)); else r.appendChild(node);
  return r;
}
function stateOf(n) {
  if (n.loaded === false) return ['err', 'not loaded in Asterisk'];
  if (!n.ok) return ['err', n.error || 'no status'];
  return ['ok', 'up'];
}
function table(cols, rows, empty, right) {
  const rt = right || [];
  if (!rows.length) return el('div', 'empty', empty);
  const wrap = el('div', 'scroll');
  const t = el('table');
  const hr = el('tr');
  cols.forEach((c, i) => hr.appendChild(el('th', rt.includes(i) ? 'r' : '', c)));
  t.appendChild(hr);
  rows.forEach((cells) => {
    const tr = el('tr');
    cells.forEach((c, i) => {
      const td = el('td', (c && c.mono ? 'mono' : '') + (rt.includes(i) ? ' r' : ''));
      if (c && c.node) td.appendChild(c.node); else td.textContent = c && c.text !== undefined ? c.text : (c === null ? '' : c);
      tr.appendChild(td);
    });
    t.appendChild(tr);
  });
  wrap.appendChild(t);
  return wrap;
}
function linkRows(n) {
  return n.links.map((l) => {
    const gw = l.gateway;
    const type = l.bridge ? l.bridge : 'AllStar node';
    const st = String(l.state || '').toUpperCase();
    return [{text: l.node, mono: true}, type, gw ? {node: el('span', '', gw.text)} : '',
            {node: badge(st === 'ESTABLISHED' ? 'connected' : st === 'CONNECTING' ? 'connecting' : 'unknown', l.state || '?')},
            l.mode_name || '-', l.direction || '-', {text: l.since || '-', mono: true},
            {node: el('span', l.keyed ? 'keyed' : '', l.keyed ? 'keyed' : '')}];
  });
}
const LINK_COLS = ['Node', 'Type', 'Tuned to', 'State', 'Mode', 'Direction', 'Connected', 'Audio'];
function byOp(op) { return COMMANDS.find((c) => String(c.op) === String(op)); }
function buildBar(node) {
  const bar = el('div', 'cmdbar');
  const sel = el('select');
  sel.setAttribute('aria-label', 'Command for node ' + node);
  const groups = {};
  COMMANDS.forEach((c) => {
    let g = groups[c.group];
    if (!g) { g = document.createElement('optgroup'); g.label = c.group; groups[c.group] = g; sel.appendChild(g); }
    const o = el('option', '', c.label);
    o.value = c.op;
    g.appendChild(o);
  });
  const tgt = el('input');
  tgt.type = 'text'; tgt.placeholder = 'Node'; tgt.maxLength = 7; tgt.autocomplete = 'off'; tgt.inputMode = 'numeric';
  tgt.setAttribute('list', 'dl-' + node);
  tgt.setAttribute('aria-label', 'Node to use');
  const dl = document.createElement('datalist');
  dl.id = 'dl-' + node;
  const txt = el('input', 'msg');
  txt.type = 'text'; txt.placeholder = 'Message'; txt.maxLength = 100; txt.autocomplete = 'off';
  txt.setAttribute('aria-label', 'Message');
  const go = el('button', 'pill go', 'Send');
  go.type = 'button';
  const res = el('span', 'cmdres');
  res.setAttribute('role', 'status');
  const sync = () => {
    const c = byOp(sel.value);
    tgt.classList.toggle('hidden', !c || c.target === 'none');
    txt.classList.toggle('hidden', !(c && c.text));
    tgt.placeholder = c && c.target === 'node0' ? 'Node, or 0 for all' : 'Node';
  };
  sel.addEventListener('change', () => { sync(); res.textContent = ''; });
  sync();
  go.addEventListener('click', async () => {
    const c = byOp(sel.value);
    if (!c) return;
    if (c.confirm && !window.confirm('Node ' + node + ': ' + c.confirm)) return;
    go.disabled = true;
    res.className = 'cmdres';
    res.textContent = 'Sending...';
    const d = await api('/api/command', {method: 'POST', body: {node: node, op: c.op, target: c.target === 'none' ? '' : tgt.value.trim(), text: c.text ? txt.value.trim() : ''}});
    go.disabled = false;
    res.className = 'cmdres ' + (d.ok ? 'ok' : 'err');
    res.textContent = d.ok ? d.message : (d.error || 'It failed.');
    if (document.activeElement && bar.contains(document.activeElement)) document.activeElement.blur();
    poll();
    setTimeout(poll, 1500);
  });
  [sel, tgt, txt, go, res, dl].forEach((x) => bar.appendChild(x));
  bar._dl = dl;
  return bar;
}
function cmdBar(n) {
  if (!bars[n.node]) bars[n.node] = buildBar(n.node);
  const bar = bars[n.node];
  const seen = {};
  const pick = [];
  n.links.forEach((l) => { if (!seen[l.node]) { seen[l.node] = 1; pick.push(l.node); } });
  const others = [];
  if (status) {
    if (status.main) others.push(status.main.node);
    status.private.forEach((p) => others.push(p.node));
  }
  others.forEach((x) => { if (x !== n.node && !seen[x]) { seen[x] = 1; pick.push(x); } });
  bar._dl.textContent = '';
  pick.forEach((x) => { const o = document.createElement('option'); o.value = x; bar._dl.appendChild(o); });
  return bar;
}
function nodeCard(n, title) {
  const card = el('div', 'card');
  const h = el('h2');
  h.appendChild(el('span', '', title + ' ' + n.node));
  const st = stateOf(n);
  h.appendChild(badge(st[0], st[1]));
  if (n.txkeyed) h.appendChild(badge('warn', 'transmitting'));
  if (n.rxkeyed) h.appendChild(badge('ok', 'receiving'));
  card.appendChild(h);
  if (n.bridge) card.appendChild(kv('Bridge', n.bridge));
  if (n.gateway) {
    const g = n.gateway;
    const box = el('span');
    box.appendChild(badge(g.state, g.state));
    box.appendChild(el('span', '', ' ' + g.text + (g.detail ? ' (' + g.detail + ')' : '')));
    card.appendChild(kv('Gateway', box));
  }
  if (n.ok && COMMANDS.length) card.appendChild(kv('Command', cmdBar(n)));
  card.appendChild(table(LINK_COLS, linkRows(n), 'No links.'));
  return card;
}
async function disconNode(node) {
  if (discoBusy[node]) return;
  discoBusy[node] = true;
  if (status) renderOv(status);
  const d = await api('/api/node-discon', {method: 'POST', body: {node: node}});
  delete discoBusy[node];
  disconMsg = {text: d.ok ? d.message : (d.error || 'It failed.'), cls: d.ok ? 'ok' : 'err', at: Date.now()};
  if (current !== 'ov') { const sm = $('sysmsg'); sm.className = 'sysmsg ' + disconMsg.cls; sm.textContent = disconMsg.text; }
  if (status) renderOv(status);
  poll();
  setTimeout(poll, 1500);
}
function disconCell(n) {
  if (!n.ok || n.loaded === false) return '';
  const b = el('button', 'btn btn-muted discon', n.role === 'main' ? 'Disconnect All' : 'Disconnect');
  b.type = 'button';
  b.disabled = !!discoBusy[n.node];
  b.setAttribute('aria-label', (n.role === 'main' ? 'Disconnect everything: node ' : 'Disconnect node ') + n.node);
  b.addEventListener('click', () => disconNode(n.node));
  return {node: b};
}
function nodeSummary(n) {
  const st = stateOf(n);
  const linked = n.links.map((l) => l.node);
  const reg = n.registration;
  const down = st[0] !== 'ok';
  const cells = [{text: n.node, mono: true}, n.role === 'main' ? 'Main node' : (n.bridge || 'Private node'),
                 {node: badge(st[0], down ? 'down' : 'up')},
                 linked.length ? linked.length + ': ' + linked.join(', ') : 'none'];
  let note = down ? st[1] : '';
  if (n.txkeyed) note = 'transmitting';
  else if (n.rxkeyed) note = 'receiving';
  if (n.gateway) note += (note ? '; ' : '') + n.gateway.text;
  if (reg) note += (note ? '; ' : '') + 'ASL3 ' + reg.state.toLowerCase();
  cells.push(note || '-');
  cells.push(disconCell(n));
  return cells;
}
function renderOv(d) {
  const root = $('pg-ov');
  root.textContent = '';
  const nodes = (d.main ? [d.main] : []).concat(d.private);
  const up = nodes.filter((n) => n.ok && n.loaded !== false).length;
  const links = nodes.reduce((a, n) => a + n.links.length, 0);
  const gws = Object.keys(d.gateways || {});
  const gwOn = gws.filter((k) => d.gateways[k].state === 'connected').length;
  const reg = d.main && d.main.registration ? d.main.registration.state : 'unknown';
  const c1 = el('div', 'card');
  const h = el('h2');
  h.appendChild(el('span', '', 'Status'));
  h.appendChild(badge(d.ami.ok ? 'ok' : 'err', d.ami.ok ? 'Asterisk connected' : 'No Asterisk'));
  c1.appendChild(h);
  const sum = el('div', 'sum');
  [[up + ' of ' + nodes.length, 'Nodes up', up > 0], [String(links), 'Links on the nodes', links > 0],
   [gwOn + ' of ' + gws.length, 'Gateways tuned', gwOn > 0], [reg, 'ASL3 registration', /^registered$/i.test(reg)]].forEach((x) => {
    const b = el('div', 'box' + (x[2] ? ' lit' : ''));
    b.appendChild(el('div', 'n', x[0]));
    b.appendChild(el('div', 't', x[1]));
    sum.appendChild(b);
  });
  c1.appendChild(sum);
  root.appendChild(c1);
  const c2 = el('div', 'card');
  c2.appendChild(el('h2', '', 'Nodes'));
  const tbl = table(['Node', 'What', 'State', 'Linked to', 'Notes', 'DisCon'], nodes.map(nodeSummary), 'No nodes were found in rpt.conf.', [5]);
  const tb = tbl.querySelector('table');
  if (tb) tb.classList.add('nodes-tbl');
  const trs = tbl.querySelectorAll('tr');
  nodes.forEach((n, i) => {
    if (!trs[i + 1] || !n.ok || n.loaded === false) return;
    trs[i + 1].classList.add('lit');
    if (n.txkeyed || n.rxkeyed) trs[i + 1].classList.add('hot');
  });
  c2.appendChild(tbl);
  if (disconMsg && Date.now() - disconMsg.at < 15000) c2.appendChild(el('div', 'sysmsg ' + disconMsg.cls, disconMsg.text));
  root.appendChild(c2);
  const c3 = el('div', 'card');
  c3.appendChild(el('h2', '', 'Links'));
  const row = el('div', 'ql-row');
  (d.links || []).forEach((l) => {
    const a = el('a', 'ql', l.label);
    a.href = l.scheme + '://' + location.hostname + (l.port === 80 ? '' : ':' + l.port) + l.path;
    a.target = '_blank';
    a.rel = 'noopener';
    row.appendChild(a);
  });
  if (!row.children.length) row.appendChild(el('span', 'empty', 'No other tool pages are answering on this node.'));
  c3.appendChild(row);
  root.appendChild(c3);
}
function renderMain(d) {
  const root = $('pg-main');
  root.textContent = '';
  if (!d.main) { root.appendChild(el('div', 'banner warn', 'No node was found in rpt.conf.')); return; }
  const n = d.main;
  const card = nodeCard(n, 'Node');
  const reg = n.registration;
  const rbox = el('span');
  if (!reg) rbox.appendChild(badge('unknown', 'unknown'));
  else {
    const ok = /^registered$/i.test(reg.state);
    rbox.appendChild(badge(ok ? 'registered' : (reg.state === 'not listed' ? 'unknown' : 'warn'), reg.state));
    if (reg.host && reg.host !== '(null)') rbox.appendChild(el('span', 'mono', ' ' + reg.host));
    if (reg.perceived && !/^</.test(reg.perceived)) rbox.appendChild(el('span', 'mono', ' seen as ' + reg.perceived));
    if (reg.refresh) rbox.appendChild(el('span', '', ' refresh ' + reg.refresh + ' s'));
  }
  card.insertBefore(kv('ASL3 registration', rbox), card.children[1]);
  root.appendChild(card);
  const gws = Object.keys(d.gateways || {});
  if (gws.length) {
    const c2 = el('div', 'card');
    c2.appendChild(el('h2', '', 'Gateways'));
    c2.appendChild(gatewayTable(d));
    root.appendChild(c2);
  }
}
const GW_NAMES = {dvswitch: 'DVSwitch', m17: 'M17', svx: 'SvxLink'};
function gatewayTable(d) {
  const rows = Object.keys(d.gateways).map((k) => {
    const g = d.gateways[k];
    return [GW_NAMES[k] || k, {node: badge(g.state, g.state)}, g.text, g.detail || '', g.source || ''];
  });
  return table(['Gateway', 'State', 'Tuned to', 'Detail', 'Source'], rows, 'No gateways.');
}
function renderConn(d) {
  const root = $('pg-conn');
  root.textContent = '';
  if (!d.main) { root.appendChild(el('div', 'banner warn', 'No node was found in rpt.conf.')); return; }
  const c1 = el('div', 'card');
  c1.appendChild(el('h2', '', 'Connected to node ' + d.main.node));
  c1.appendChild(table(LINK_COLS, linkRows(d.main), 'Nothing is linked to this node.'));
  root.appendChild(c1);
  const c2 = el('div', 'card');
  c2.appendChild(el('h2', '', 'Gateways'));
  c2.appendChild(gatewayTable(d));
  root.appendChild(c2);
}
function renderPriv(d) {
  const root = $('pg-priv');
  root.textContent = '';
  if (!d.private.length) { root.appendChild(el('div', 'banner warn', 'No private nodes (1000 to 1999) in rpt.conf.')); return; }
  d.private.forEach((n) => root.appendChild(nodeCard(n, 'Private node')));
}
function renderBanner(d) {
  const b = $('status-banner');
  b.textContent = '';
  let cls = 'ok', text = 'Connected to Asterisk (' + d.ami.banner + '), refreshed every ' + d.poll_sec + ' s.';
  if (!d.plan.ok) { cls = 'err'; text = d.plan.error; }
  else if (!d.ami.ok) { cls = 'err'; text = 'No link state from Asterisk: ' + d.ami.error; }
  else if (d.ami.age !== null && d.ami.age > d.poll_sec * 4 + 10) { cls = 'warn'; text = 'The link state is ' + Math.round(d.ami.age) + ' s old.'; }
  b.appendChild(el('div', 'banner ' + cls, text));
}
function renderAll(d) {
  status = d;
  $('hdr-node').textContent = d.main ? 'Node ' + d.main.node : '';
  renderBanner(d);
  const busy = document.activeElement && document.activeElement.closest && document.activeElement.closest('.cmdbar');
  if (busy) return;
  renderOv(d);
  renderMain(d);
  renderConn(d);
  renderPriv(d);
}
async function poll() {
  if (!authed) return;
  if (timer) clearTimeout(timer);
  if (document.visibilityState !== 'hidden') {
    const d = await api('/api/status');
    if (d && d.ok !== false && d.ami) renderAll(d);
    else if (d && d.error === 'Server unreachable.') {
      $('status-banner').textContent = '';
      $('status-banner').appendChild(el('div', 'banner err', 'Node Monitor is not answering. Retrying every few seconds.'));
    }
    if (current === 'log') pollLog();
  }
  const ms = Math.max(1000, ((status && status.poll_sec) || 3) * 1000);
  timer = setTimeout(poll, ms);
}
async function pollLog() {
  const d = await api('/api/log?since=' + logSince);
  if (!d || !d.lines) return;
  const box = $('logbox');
  d.lines.forEach((x) => {
    logSince = Math.max(logSince, x.id);
    const line = el('div', 'l-' + (x.level || 'info'), x.ts + '  ' + x.msg);
    box.appendChild(line);
  });
  while (box.children.length > 400) box.removeChild(box.firstChild);
  if (d.lines.length) box.scrollTop = box.scrollHeight;
}
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));
$('login-form').addEventListener('submit', login);
$('logout').addEventListener('click', logout);
$('sys-disc').addEventListener('click', () => sysAction('disc'));
$('sys-reboot').addEventListener('click', () => sysAction('reboot'));
$('sys-shutdown').addEventListener('click', () => sysAction('shutdown'));
document.addEventListener('visibilitychange', () => { if (document.visibilityState !== 'hidden') poll(); });
async function sysAction(kind) {
  const node = status && status.main ? status.main.node : '';
  if (kind === 'disc') { disconNode(node); return; }
  const ask = {reboot: 'Reboot the system?', shutdown: 'Shut down the system?'};
  const path = {reboot: '/api/system/reboot', shutdown: '/api/system/shutdown'};
  if (!window.confirm(ask[kind])) return;
  const msg = $('sysmsg');
  ['sys-disc', 'sys-reboot', 'sys-shutdown'].forEach((id) => { $(id).disabled = true; });
  msg.className = 'sysmsg';
  msg.textContent = 'Sending...';
  const d = await api(path[kind], {method: 'POST', body: {}});
  ['sys-disc', 'sys-reboot', 'sys-shutdown'].forEach((id) => { $(id).disabled = false; });
  msg.className = 'sysmsg ' + (d.ok ? 'ok' : 'err');
  msg.textContent = d.ok ? d.message : (d.error || 'It failed.');
}
async function loadCommands() {
  const d = await api('/api/commands');
  COMMANDS = d.commands || [];
}
(async () => {
  const d = await api('/api/whoami');
  authed = !!d.authed;
  if (authed) await loadCommands();
  render();
})();
"""


_page_cache = {}


def _csp(nonce):
    return ("default-src 'self'; script-src 'self' 'nonce-" + nonce + "'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; object-src 'none'; form-action 'self'")


def render_page(nonce, packed):
    html = _page_cache.get("html")
    if html is None:
        html = _HTML_TEMPLATE
        for key, val in (("__FONTS__", _FONTS), ("__CSS__", _CSS), ("__JS__", _JS), ("__VERSION__", VERSION)):
            html = html.replace(key, val)
        html = login_ui_inject(html, "pw", "__NONCE__")
        _page_cache["html"] = html
    body = html.replace("__NONCE__", nonce).encode("utf-8")
    return gzip.compress(body, 4, mtime=0) if packed else body


def _status_view(authed):
    return dict(build_status(authed), ok=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "nodemon/" + VERSION
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

    def _wan_refused(self):
        if _cfg_get("allow_wan") or not self._wan():
            return False
        self.close_connection = True
        self._json(403, {"ok": False, "error": "Node Monitor is not open to the internet (allow_wan is off)."})
        return True

    def _token(self):
        cookie = self.headers.get("Cookie", "")
        return sess_token_from(cookie, _SESSION_COOKIE_NAME) or ""

    def _authed(self):
        return _check_session(self._token())

    def _cookie(self, token, max_age):
        return sess_cookie(_SESSION_COOKIE_NAME, token, max_age, False)

    def _head(self, code, ctype, headers):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in headers.items():
            self.send_header(k, v)
        age = getattr(_sess_local, "renew", 0)
        if age:
            _sess_local.renew = 0
            if "Set-Cookie" not in headers:
                self.send_header("Set-Cookie", self._cookie(self._token(), age))
        self.end_headers()

    def _accepts_gzip(self):
        for token in self.headers.get("Accept-Encoding", "").split(","):
            name, _, params = token.strip().partition(";")
            if name.strip().lower() in ("gzip", "x-gzip"):
                return params.strip().replace(" ", "") not in ("q=0", "q=0.0", "q=0.00", "q=0.000")
        return False

    def _send(self, code, body, ctype, headers=None):
        headers = dict(headers or {})
        if ctype.startswith("application/json") and len(body) >= GZIP_MIN_BYTES and self._accepts_gzip():
            body = gzip.compress(body, 5, mtime=0)
            headers["Content-Encoding"] = "gzip"
            headers["Vary"] = "Accept-Encoding"
        self._head(code, ctype, dict(headers, **{"Content-Length": str(len(body))}))
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_page(self):
        nonce = secrets.token_urlsafe(18)
        packed = self._accepts_gzip()
        body = render_page(nonce, packed)
        headers = {"Content-Length": str(len(body)), "Vary": "Accept-Encoding",
                   "Content-Security-Policy": _csp(nonce)}
        if packed:
            headers["Content-Encoding"] = "gzip"
        self._head(200, "text/html; charset=utf-8", headers)
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

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self._wan_refused():
            return
        path = urllib.parse.urlsplit(self.path).path
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        authed = self._authed()
        if path not in _OPEN_GET_PATHS and not authed:
            self._json(401, {"ok": False, "error": "Log in first."})
            return
        try:
            if path in ("/", "/index.html"):
                self._send_page()
            elif path == "/api/health":
                self._json(200, {"ok": True, "version": VERSION})
            elif path == "/api/whoami":
                self._json(200, {"ok": True, "authed": authed, "version": VERSION,
                                 "backend": _root_backend_available()})
            elif path == "/api/commands":
                self._json(200, {"ok": True, "commands": list(COMMANDS)})
            elif path == "/api/status":
                self._json(200, _status_view(authed))
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
            wait = _auth_lockout_remaining(ip, wan)
            if wait > 0:
                self._json(429, {"ok": False, "error": f"Too many attempts. Try again in {int(wait) + 1} s."})
                return
            where = " (internet)" if wan else ""
            if _verify_root_password(str(body.get("password", ""))):
                _record_auth_success(ip)
                token, age = _issue_session()
                log_event(f"Login from {ip}{where}", "warn" if wan else "ok")
                self._json(200, {"ok": True}, {"Set-Cookie": self._cookie(token, age)})
            else:
                _record_auth_failure(ip, wan)
                log_event(f"Failed login from {ip}{where}", "warn")
                self._json(401, {"ok": False, "error": "Wrong password."})
            return
        if path == "/api/logout":
            _revoke_all_sessions()
            self._json(200, {"ok": True}, {"Set-Cookie": self._cookie("", 0)})
            return
        if not self._authed():
            self._json(401, {"ok": False, "error": "Log in first."})
            return
        if path == "/api/command":
            self._json(200, run_command(body, ip))
            return
        if path == "/api/node-discon":
            self._json(200, node_discon(body.get("node"), ip))
            return
        if path in ("/api/system/reboot", "/api/system/shutdown"):
            self._json(200, system_power(path.rsplit("/", 1)[1], ip))
            return
        self._json(404, {"ok": False, "error": "Not found."})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, socket.timeout)):
            return
        log_event(f"Request error from {client_address[0] if client_address else '?'}: {exc}", "warn")


def _watchdog_loop(port):
    if not os.environ.get("NOTIFY_SOCKET"):
        return
    try:
        interval_usec = int(os.environ.get("WATCHDOG_USEC", "0"))
    except ValueError:
        interval_usec = 0
    period = (interval_usec / 1e6 / 2.0) if interval_usec > 0 else 30.0
    period = max(5.0, min(period, 300.0))
    while True:
        try:
            if _http_responsive(port):
                _sd_notify("WATCHDOG=1")
        except Exception:
            pass
        time.sleep(period)


def run_server():
    load_config()
    port = _cfg_get("port")
    try:
        httpd = Server(("0.0.0.0", port), Handler)
    except OSError as exc:
        log_event(f"Cannot listen on port {port}: {exc}", "err")
        return 1
    threading.Thread(target=MON.loop, name="ami-poll", daemon=True).start()
    threading.Thread(target=_watchdog_loop, args=(port,), name="watchdog", daemon=True).start()
    log_event(f"{APP_NAME} v{VERSION} on http port {port}", "ok")
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
        httpd.server_close()
    return 0


def service_content(run_path):
    return f"""[Unit]
Description=Node Monitor: link and registration status for the ASL node
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
    load_config()
    if not os.path.exists(CONFIG_PATH):
        save_config(dict(_config))
        print(f"  [+] Wrote {CONFIG_PATH}")
    _atomic_write(SYSTEMD_SERVICE_PATH, service_content(INSTALL_BIN_PATH), 0o644)
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
        print(f"      The previous version (if any) is still in {INSTALL_DIR}")
        sys.exit(1)
    print(f"  [+] {SERVICE_NAME} enabled and started")
    for name in os.listdir(INSTALL_DIR):
        old = os.path.join(INSTALL_DIR, name)
        if old != dest and name.endswith(".py") and os.path.isfile(old) and not os.path.islink(old):
            os.remove(old)
            print(f"  [-] Removed the previous version {old}")
    print(f"Open http://<node-address>:{_cfg_get('port')} and log in with the root password.")


def uninstall_service():
    if os.geteuid() != 0:
        print("Error: uninstalling needs root. Run with sudo.")
        sys.exit(1)
    print(f"Removing {APP_NAME}...")
    load_config()
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
    print(f"  Settings kept in {CONFIG_PATH}")
    mark, msg = close_firewall_port(_cfg_get("port"))
    print(f"  [{mark}] {msg}")


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{VERSION}: link and registration status for an ASL node")
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
