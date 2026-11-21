VERSION = "0.8.0"

import argparse
import configparser
import gc
import hashlib
import hmac
import http.client
import io
import importlib
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import sysconfig
import threading
import time
import urllib.parse
import urllib.request
import wave
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

VOICES_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

APP = "piper_dashboard"
INSTALL_BIN_PATH = "/usr/local/bin/piper_dashboard.py"
INSTALL_DIR = "/usr/local/lib/piper_dashboard"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/piper_dashboard.service"
SERVICE_NAME = "piper_dashboard.service"
CONFIG_PATH = "/etc/asl_dvs/piper_dashboard.conf"
PIBRARY_CONF = "/etc/pibrary/pibrary.conf"
PIBRARY_SECTION = "pibrary"
PIBRARY_SERVICE = "pibrary.service"
DATA_ROOT = "/srv/piper_dashboard"
EXPORT_FORMATS = {"ulaw": ".ulaw", "sln": ".sln", "wav8": "-8k.wav"}
MAX_EXPORT_BYTES = 16 * 1024 * 1024
EXPORT_LOCK = threading.Lock()
RADIO_LOCK = threading.Lock()
RADIO_BASE = "pipertts"
OUT_EXTS = {".wav", ".ulaw", ".sln"}
_SYSTEMD_UNIT_DIR = "/etc/systemd/system"
_LAUNCHER_PATH = "/usr/local/bin/asl_dvs_launch.py"
_LAUNCHER_CODE = '#!/usr/bin/env python3\nimport os\nimport runpy\nimport sys\n\n_OFF = "/etc/asl_dvs/launch_no_"\n_AGAIN = "ASL_DVS_LAUNCH"\n\nif _AGAIN in os.environ:\n    if os.environ.pop(_AGAIN) == "arena":\n        os.environ.pop("MALLOC_ARENA_MAX", None)\nelse:\n    flags = []\n    env = dict(os.environ)\n    env[_AGAIN] = ""\n    if sys.flags.optimize < 2 and not os.path.exists(_OFF + "optimize"):\n        flags.append("-OO")\n    if "MALLOC_ARENA_MAX" not in env and not os.path.exists(_OFF + "arena_cap"):\n        env["MALLOC_ARENA_MAX"] = "2"\n        env[_AGAIN] = "arena"\n    if (flags or env[_AGAIN]) and sys.executable:\n        try:\n            os.execve(sys.executable, [sys.executable] + flags + sys.argv, env)\n        except OSError:\n            pass\n\ndef _trim_loop():\n    import time\n    time.sleep(60)\n    try:\n        import ctypes\n        trim = ctypes.CDLL("libc.so.6").malloc_trim\n    except (ImportError, OSError, AttributeError):\n        return\n    trim.argtypes = [ctypes.c_size_t]\n    while True:\n        trim(0)\n        time.sleep(300)\n\nif not os.path.exists(_OFF + "trim"):\n    import threading\n    threading.Thread(target=_trim_loop, name="mem-trim", daemon=True).start()\n\ntarget = os.path.realpath(sys.argv[1])\nname = os.path.splitext(os.path.basename(target))[0]\nsys.argv = [target] + sys.argv[2:]\nsys.path.insert(0, os.path.dirname(target))\nif name.isidentifier():\n    runpy.run_module(name, run_name="__main__", alter_sys=True)\nelse:\n    import importlib.util\n    spec = importlib.util.spec_from_file_location("__main__", target)\n    main = importlib.util.module_from_spec(spec)\n    sys.modules["__main__"] = main\n    spec.loader.exec_module(main)\n'


PiperVoice = SynthesisConfig = None
ENGINE_ERR = "not checked"


def venv_site(venv):
    return Path(venv) / "lib" / ("python%d.%d" % sys.version_info[:2]) / "site-packages"


def try_import_engine(venv=None):
    global PiperVoice, SynthesisConfig, ENGINE_ERR
    if venv:
        sp = str(venv_site(venv))
        if os.path.isdir(sp) and sp not in sys.path:
            sys.path.insert(0, sp)
    importlib.invalidate_caches()
    try:
        from piper import PiperVoice as pv, SynthesisConfig as sc
    except Exception as e:
        for k in [k for k in sys.modules if k == "piper" or k.startswith("piper.")]:
            del sys.modules[k]
        ENGINE_ERR = "%s: %s" % (type(e).__name__, e)
        return False
    PiperVoice, SynthesisConfig, ENGINE_ERR = pv, sc, None
    return True

MAX_UPLOAD = 5 * 1024 * 1024
MAX_JSON = 1 << 20
MAX_TEXT = 100000
TEXT_EXTS = {".txt", ".md", ".csv"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

CFG = {}


_SESSION_COOKIE_NAME = "piper_session"
SESS_TIER = "standard"
SESS_STORE = {}
SESS_LOCK = threading.Lock()
LOCK_STATE = {}
AUTH_ACCOUNT = "root"
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def _read_shadow_hash(account):
    try:
        with open("/etc/shadow", "r") as fh:
            for line in fh:
                parts = line.rstrip("\n").split(":")
                if len(parts) >= 2 and parts[0] == account:
                    return parts[1]
    except OSError:
        return None
    return None


def _crypt_verify(password, stored_hash):
    import ctypes
    import ctypes.util
    for name in ("libcrypt.so.1", "libcrypt.so.2", "libcrypt.so", ctypes.util.find_library("crypt")):
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            lib.crypt.restype = ctypes.c_char_p
            lib.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        except (OSError, AttributeError):
            continue
        out = lib.crypt(password.encode("utf-8", "surrogateescape"), stored_hash.encode("utf-8", "surrogateescape"))
        if out is None:
            return False
        return hmac.compare_digest(out.decode("utf-8", "surrogateescape"), stored_hash)
    return False


def verify_root_password(password):
    if not password:
        return False
    try:
        import pam as pam_mod
        return bool(pam_mod.pam().authenticate(AUTH_ACCOUNT, password, service="login"))
    except ImportError:
        pass
    except Exception:
        pass
    stored = _read_shadow_hash(AUTH_ACCOUNT)
    if not stored or stored[0] in ("!", "*"):
        return False
    return _crypt_verify(password, stored)


def auth_stamp():
    return sess_stamp(_read_shadow_hash(AUTH_ACCOUNT) or "")


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


class Engine:

    def __init__(self, voices_dir, cuda):
        self.lock = threading.Lock()
        self.voices_dir = voices_dir
        self.cuda = cuda
        self.voice = None
        self.name = None

    def ensure(self, name):
        if self.voice is not None and self.name == name:
            return self.voice
        self.drop()
        self.voice = PiperVoice.load(str(Path(self.voices_dir) / name), use_cuda=self.cuda)
        self.name = name
        return self.voice

    def drop(self):
        self.voice = None
        self.name = None
        gc.collect()


ENG = None


def rss_kb():
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def list_voices(d):
    out = []
    for m in sorted(Path(d).glob("*.onnx")):
        cfg = Path(str(m) + ".json")
        if not SAFE_NAME.match(m.name) or not cfg.is_file():
            continue
        speakers = 1
        try:
            speakers = int(json.loads(cfg.read_text(encoding="utf-8")).get("num_speakers", 1))
        except (ValueError, OSError):
            pass
        out.append({"name": m.name, "speakers": max(1, speakers)})
    return out


def list_files(d, exts=None):
    items = []
    for p in Path(d).iterdir():
        if p.is_file() and SAFE_NAME.match(p.name) and (exts is None or p.suffix.lower() in exts):
            items.append(p)
    items.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "bytes": p.stat().st_size} for p in items]


def safe_join(base, name):
    if not SAFE_NAME.match(name):
        return None
    p = Path(base) / name
    return p if p.is_file() else None


_ULAW_EXP = (256, 512, 1024, 2048, 4096, 8192, 16384)


def _numpy():
    try:
        import numpy
        return numpy
    except Exception:
        return None


def to_8k(np, x, sr):
    if sr > 8000:
        taps = 101
        n = np.arange(taps, dtype=np.float32) - (taps - 1) / 2.0
        fc = 3600.0 / sr
        h = (2 * fc * np.sinc(2 * fc * n) * np.blackman(taps)).astype(np.float32)
        h /= h.sum()
        x = np.convolve(x, h, mode="same")
    if sr == 8000 or len(x) < 2:
        return x
    count = int(len(x) * 8000.0 / sr)
    pos = np.arange(count, dtype=np.float64) * (sr / 8000.0)
    i = pos.astype(np.int32)
    frac = (pos - i).astype(np.float32)
    i1 = np.minimum(i + 1, len(x) - 1)
    return (x[i] * (1.0 - frac) + x[i1] * frac).astype(np.float32)


def ulaw_encode(np, pcm):
    s = pcm.astype(np.int32)
    sign = np.where(s < 0, 0x80, 0)
    s = np.minimum(np.abs(s), 32635) + 0x84
    exp = np.searchsorted(np.array(_ULAW_EXP), s, side="right")
    mant = (s >> (exp + 3)) & 0x0F
    return (~(sign | (exp << 4) | mant) & 0xFF).astype(np.uint8)


def export_audio(np, path, fmt):
    if path.stat().st_size > MAX_EXPORT_BYTES:
        raise ValueError("too long to convert (over %d MB)" % (MAX_EXPORT_BYTES >> 20))
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("only 16-bit WAV is supported")
        ch, sr = w.getnchannels(), w.getframerate()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if ch > 1:
        x = x[: (len(x) // ch) * ch].reshape(-1, ch).mean(axis=1)
    if len(x) == 0:
        raise ValueError("empty audio")
    pcm = np.clip(np.rint(to_8k(np, x, sr)), -32768, 32767).astype("<i2")
    if fmt == "ulaw":
        return ulaw_encode(np, pcm).tobytes()
    if fmt == "sln":
        return pcm.tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def air_info(p):
    n = p.stat().st_size
    ext = p.suffix.lower()
    if ext == ".ulaw":
        return n / 8000.0, True
    if ext == ".sln":
        return n / 16000.0, True
    if ext == ".wav":
        try:
            with wave.open(str(p), "rb") as w:
                ok = w.getframerate() == 8000 and w.getnchannels() == 1 and w.getsampwidth() == 2
                return w.getnframes() / 8000.0, ok
        except (wave.Error, EOFError):
            return 0.0, False
    return 0.0, False


def radio_enabled():
    return bool(CFG.get("radio_nodes")) and bool(CFG.get("radio_sounds"))


JOB_LOCK = threading.Lock()
JOB = {"kind": None, "name": None, "state": "idle", "msg": "", "done": 0, "total": 0, "log": []}
CAT = {"t": 0.0, "data": None}
CAT_LOCK = threading.Lock()
CAT_TTL = 3600
MAX_CATALOG = 8 * 1024 * 1024
VOICE_KEY = re.compile(r"^[A-Za-z0-9_]+-[A-Za-z0-9_]+-[A-Za-z0-9_]+$")
CAT_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")
UA = {"User-Agent": "piper_dashboard/" + VERSION}


def job_set(**kw):
    with JOB_LOCK:
        JOB.update(kw)


def job_log(line):
    with JOB_LOCK:
        JOB["log"].append(line.rstrip()[:300])
        del JOB["log"][:-180]


def job_add(n):
    with JOB_LOCK:
        JOB["done"] += n


def job_snapshot():
    with JOB_LOCK:
        j = dict(JOB)
        j["log"] = list(JOB["log"])
    return j


def start_job(kind, name, fn, *args):
    with JOB_LOCK:
        if JOB["state"] == "running":
            return False
        JOB.update(kind=kind, name=name, state="running", msg="starting", done=0, total=0, log=[])
    threading.Thread(target=run_job, args=(fn, args), daemon=True).start()
    return True


def run_job(fn, args):
    try:
        fn(*args)
        job_set(state="done")
    except Exception as e:
        job_set(state="error", msg="%s: %s" % (type(e).__name__, e))


def run_cmd(cmd, timeout):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, errors="replace")
    timer = threading.Timer(timeout, p.kill)
    timer.start()
    tail = []
    try:
        for line in p.stdout:
            if line.strip():
                job_log(line)
                tail.append(line)
                del tail[:-20]
        rc = p.wait()
    finally:
        timer.cancel()
        if p.poll() is None:
            p.kill()
    if rc != 0:
        out = "".join(tail)
        hint = ""
        if "ensurepip" in out or "python3-venv" in out:
            hint = " (try: sudo apt install python3-venv)"
        elif "No matching distribution" in out:
            hint = " (needs 64-bit Python on x86_64 or aarch64)"
        elif rc < 0:
            hint = " (timed out or killed)"
        raise RuntimeError("command failed, exit %d%s" % (rc, hint))


LEGACY_VENV_GLOBS = ("/root/piper/venv", "/home/*/piper/venv", "/home/*/piper-tts/venv",
                     "/opt/piper/venv", "/usr/local/piper/venv", "/srv/piper_dashboard/venv")
LEGACY_CLI_PATHS = ("/usr/local/bin/piper", "/usr/bin/piper")


def piper_site_ok(venv):
    return any(Path(venv).glob("lib/python*/site-packages/piper/__init__.py"))


def find_legacy_venvs():
    import glob
    cands = [CFG.get("venv", "")]
    for g in LEGACY_VENV_GLOBS:
        cands += sorted(glob.glob(g))
    seen = []
    for c in cands:
        if c and c not in seen and os.path.isdir(c) and piper_site_ok(c):
            seen.append(c)
    return seen


def find_legacy_cli():
    for p in LEGACY_CLI_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def install_engine():
    for v in find_legacy_venvs():
        if try_import_engine(v):
            CFG["venv"] = v
            job_set(msg="found an existing piper-tts install at %s: not reinstalling" % v)
            return
    plat = sysconfig.get_platform()
    if plat not in ("linux-x86_64", "linux-aarch64"):
        raise RuntimeError("no piper-tts wheel for %s (needs 64-bit Linux, x86_64 or aarch64)" % plat)
    venv = Path(CFG["venv"])
    py = venv / "bin" / "python"
    if not py.is_file():
        job_set(msg="creating venv")
        run_cmd([sys.executable, "-m", "venv", str(venv)], 300)
    job_set(msg="pip install piper-tts (large download, be patient)")
    run_cmd([str(py), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
             "--only-binary", ":all:", "piper-tts"], 1800)
    if not try_import_engine(CFG["venv"]):
        raise RuntimeError("installed but import failed: %s" % ENGINE_ERR)
    job_set(msg="engine ready")


def parse_voice(key, v):
    if not VOICE_KEY.match(key) or not isinstance(v, dict):
        return None
    lang_code, vname, quality = key.split("-")
    want = (key + ".onnx.json", key + ".onnx")
    files = {}
    raw_files = v.get("files")
    if isinstance(raw_files, dict) and raw_files:
        for path, meta in raw_files.items():
            base = path.rsplit("/", 1)[-1]
            if (base in want and CAT_PATH.match(path) and not path.startswith("/")
                    and ".." not in path.split("/")):
                meta = meta if isinstance(meta, dict) else {}
                files[base] = (path, int(meta.get("size_bytes") or 0), str(meta.get("md5_digest") or ""))
    else:
        for base in want:
            files[base] = ("%s/%s/%s/%s/%s" % (lang_code.split("_")[0], lang_code, vname, quality, base), 0, "")
    if len(files) != 2:
        return None
    lang = v.get("language") if isinstance(v.get("language"), dict) else {}
    return {
        "key": key,
        "lang": str(lang.get("code") or lang_code),
        "lang_name": str(lang.get("name_english") or ""),
        "name": str(v.get("name") or vname),
        "quality": str(v.get("quality") or quality),
        "speakers": max(1, int(v.get("num_speakers") or 1)),
        "files": [files[b] for b in want],
    }


def fetch_catalog(force=False):
    with CAT_LOCK:
        if CAT["data"] is not None and not force and time.time() - CAT["t"] < CAT_TTL:
            return CAT["data"]
        url = CFG["voices_base"].rstrip("/") + "/voices.json?download=true"
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            raw = r.read(MAX_CATALOG + 1)
        if len(raw) > MAX_CATALOG:
            raise RuntimeError("catalog too large")
        data = {}
        for key, v in json.loads(raw.decode("utf-8")).items():
            try:
                ent = parse_voice(key, v)
            except (ValueError, TypeError):
                ent = None
            if ent:
                data[key] = ent
        CAT["data"], CAT["t"] = data, time.time()
        return data


def install_voice(key):
    ent = (CAT["data"] or {}).get(key)
    if ent is None:
        raise RuntimeError("unknown voice (refresh the catalog)")
    d = Path(CFG["voices"])
    total = sum(f[1] for f in ent["files"])
    free = shutil.disk_usage(d).free
    if total and free < total * 1.1 + (1 << 20):
        raise RuntimeError("not enough free space: need %d MB, have %d MB"
                           % (total >> 20, free >> 20))
    job_set(total=total, msg="downloading")
    base_url = CFG["voices_base"].rstrip("/")
    for path, size, md5 in ent["files"]:
        name = path.rsplit("/", 1)[-1]
        tmp = d / (name + ".part")
        h = hashlib.md5()
        n = 0
        try:
            req = urllib.request.Request(
                base_url + "/" + urllib.parse.quote(path) + "?download=true", headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                while True:
                    b = r.read(65536)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    n += len(b)
                    job_add(len(b))
            if size and n != size:
                raise RuntimeError("size mismatch for %s" % name)
            if md5 and h.hexdigest() != md5:
                raise RuntimeError("md5 mismatch for %s" % name)
            os.replace(tmp, d / name)
            job_log("ok " + name)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    job_set(msg="installed " + key)


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pi-Piper TTS</title>
<style>
/* ── Node Control theme: variables ── */
:root {
  --bg: #0d1117;
  --surface: #161e2e;
  --surface2: #1e2a3f;
  --border: #2e4060;
  --border2: #3a5278;
  --amber: #ffd040;
  --amber-dim: #6b4800;
  --green: #00ffb0;
  --green-dim: #005538;
  --red: #ff3d5a;
  --red-dim: #6b0e20;
  --blue: #22d4ff;
  --blue-dim: #083a58;
  --purple: #d466ff;
  --purple-dim: #52087a;
  --teal: #00ffe5;
  --teal-dim: #004840;
  --orange: #ffaa22;
  --orange-dim: #703800;
  --text: #ffffff;
  --text-bright: #f0f8ff;
  --muted: #ffffff;
  --mono: Arial, Helvetica, sans-serif;
  --sans: Arial, Helvetica, sans-serif;
}
/* ── Body + header ── */
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: var(--sans); min-height: 100vh; padding-bottom: 3rem; }
header {
  background: linear-gradient(90deg, #0f1a2e, #161e2e 50%, #0f1a2e);
  border-bottom: 2px solid var(--amber);
  padding: .45rem 1rem;
  display: flex; align-items: center; justify-content: space-between; gap: .5rem;
  position: sticky; top: 0; z-index: 100;
  box-shadow: 0 2px 0 rgba(255,208,64,.25), 0 6px 30px rgba(0,0,0,.7);
}
.hdr-left { display: flex; flex-direction: column; min-width: 0; flex-shrink: 1; }
.hdr-right { display: flex; flex-direction: column; align-items: flex-end; flex-shrink: 0; white-space: nowrap; line-height: 1.4; }
.logo {
  font-family: var(--mono); font-size: 1.21rem; color: var(--amber); letter-spacing: .1em;
  text-shadow: 0 0 10px rgba(255,208,64,.9), 0 0 30px rgba(255,208,64,.5), 0 0 60px rgba(255,208,64,.2);
}
.logo-sub { font-size: .715rem; letter-spacing: .22em; text-transform: uppercase; color: var(--amber); margin-top: .1rem; }
.hdr-ver { font-size: .72rem; color: var(--muted); font-family: var(--mono); }
.wrap { max-width: 860px; margin: 0 auto; padding: 1rem; display: flex; flex-direction: column; gap: .55rem; }
.wrap > * { min-width: 0; }
/* ── Cards, labels ── */
fieldset { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; margin: 0; padding: .7rem .8rem .8rem; }
legend { font-size: .66rem; letter-spacing: .28em; text-transform: uppercase; color: #ffffff; padding: 0 .4rem; }
label { display: block; margin: .6rem 0 .2rem; font-size: .66rem; letter-spacing: .2em; text-transform: uppercase; color: #ffffff; }
details { margin: 0; }
details > summary { cursor: pointer; font-size: .72rem; letter-spacing: .22em; text-transform: uppercase; color: var(--amber); padding: .3rem 0; }
details details { margin-top: .6rem; }
#inst { margin-bottom: .55rem; }
#inst > fieldset { margin-top: .55rem; }
/* ── Inputs ── */
select, input, textarea {
  font-family: var(--mono); font-size: .946rem; width: 100%; min-width: 0; padding: .3rem .48rem;
  background: var(--surface2); color: var(--text-bright); border: 1px solid var(--border2);
  border-radius: 3px; outline: none; transition: border-color .15s;
}
select:focus, input:focus, textarea:focus { border-color: var(--amber); box-shadow: 0 0 6px rgba(255,208,64,.2); }
select:disabled, input:disabled { opacity: .5; }
textarea { resize: vertical; min-height: 7rem; margin-top: .6rem; }
#txtcount { font-size: .7rem; color: var(--muted); text-align: right; margin-top: .2rem; }
input[type=file] { padding: .25rem .4rem; }
.row { display: flex; gap: .5rem; }
.row > div { flex: 1; min-width: 0; }
/* ── Buttons ── */
button {
  font-family: var(--mono); font-size: .902rem; font-weight: bold; letter-spacing: .05em; text-transform: uppercase;
  width: 100%; padding: .48rem 1rem; margin-top: .6rem; border-radius: 4px; border: 1px solid;
  background: transparent; cursor: pointer; transition: all .14s; white-space: nowrap;
  color: var(--green); border-color: var(--green-dim);
}
button:hover:not(:disabled) { filter: brightness(1.6); box-shadow: 0 0 12px currentColor; }
button:active:not(:disabled) { transform: scale(.95); }
button:disabled { opacity: .4; cursor: default; }
button.sec { color: #ffffff; border-color: var(--border2); }
#stop { color: var(--red); border-color: var(--red-dim); }
#ieng { color: var(--amber); border-color: var(--amber-dim); }
#unload { color: var(--orange); border-color: var(--orange-dim); }
.row button { margin-top: 0; }
/* ── Status, job, outputs ── */
#status, #jobtxt { min-height: 1.4em; margin-top: .6rem; font-size: .85rem; color: var(--text-bright); }
#eng { min-height: 1.4em; font-size: .72rem; letter-spacing: .08em; color: var(--teal); }
.err { color: var(--red) !important; }
audio { width: 100%; margin-top: .6rem; color-scheme: dark; }
progress { width: 100%; height: 10px; margin-top: .5rem; accent-color: var(--green); }
pre { background: var(--bg); border: 1px solid var(--border); border-radius: 3px; padding: .4rem; font-size: .75rem; color: var(--text-bright); max-height: 420px; overflow: auto; white-space: pre-wrap; }
ul { padding-left: 1.1rem; }
li { margin: .25rem 0; }
a { color: var(--blue); }
.vrow { display: flex; justify-content: space-between; align-items: center; gap: .5rem; padding: .25rem 0; border-bottom: 1px solid var(--border); font-size: .85rem; }
.vrow button { width: auto; margin: 0; padding: .2rem .7rem; font-size: .77rem; color: var(--teal); border-color: var(--teal-dim); }
#outs { list-style: none; padding: 0; }
.orow { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; padding: .25rem 0; border-bottom: 1px solid var(--border); font-size: .85rem; }
.orow a { flex: 1 1 12rem; min-width: 0; overflow-wrap: anywhere; }
.orow button { width: auto; margin: 0; padding: .15rem .55rem; font-size: .72rem; color: var(--blue); border-color: var(--blue-dim); }
.orow button.air, .orow button.del { color: var(--red); border-color: var(--red-dim); }
#clist { max-height: 260px; overflow: auto; margin-top: .5rem; }
#logout{width:auto;margin:.2rem 0 0;padding:.15rem .6rem;font-size:.72rem}
.tabs{display:flex;gap:.4rem}.tab{flex:1;margin:0}.tab.on{color:var(--amber);border-color:var(--amber)}
</style></head><body>
<div id="lg" class="lg-screen" hidden>
<form class="lg-card" id="lgform">
<div class="lg-title">Pi-Piper TTS</div>
<input id="lg-pw" class="lg-in" type="password" autocomplete="current-password" placeholder="Root password">
<button class="lg-btn" type="submit">Sign in</button>
<div class="lg-msg" id="lg-msg"></div>
</form>
</div>
<header>
  <div class="hdr-left">
    <div class="logo">Pi-Piper TTS</div>
    <div class="logo-sub">Text to speech</div>
  </div>
  <div class="hdr-right"><div class="hdr-ver">v__VERSION__</div><button id="logout" class="sec" hidden>Sign out</button></div>
</header>
<div class="wrap">
<div class="tabs"><button id="tab-run" class="tab on">Run</button><button id="tab-cfg" class="tab">Settings</button></div>
<div id="pg-run">
<div id="eng"></div>

<details id="inst"><summary>Install engine / voices</summary>
<fieldset id="engcard"><legend>Engine</legend>
<div id="engtxt"></div>
<button id="ieng" class="sec">Install piper-tts (venv + pip)</button>
</fieldset>
<fieldset><legend>Voices</legend>
<button id="bcat" class="sec">Browse voice catalog</button>
<div class="row">
<div><label for="clang">Language</label><select id="clang"></select></div>
<div><label for="cq">Search</label><input id="cq" type="text" placeholder="lessac, medium..."></div>
</div>
<div id="clist"></div>
</fieldset>
<fieldset id="updbox" hidden><legend>Self-update</legend>
<label for="updfile">New piper_dashboard.py</label>
<input id="updfile" type="file" accept=".py">
<label for="updtok">Update token</label>
<input id="updtok" type="password" autocomplete="off">
<label><input id="updrs" type="checkbox" checked style="width:auto"> Restart service after staging</label>
<button id="upd" class="sec">Stage update</button>
</fieldset>
<div id="jobtxt"></div>
<progress id="jp" max="100" hidden></progress>
<pre id="joblog" hidden></pre>
</details>

<fieldset><legend>1. Voice</legend>
<select id="voice"></select>
<label for="speaker">Speaker</label>
<select id="speaker"><option value="0">0</option></select>
<label for="ls">Length scale (lower = faster, higher = slower)</label>
<input id="ls" type="number" step="0.05" min="0.3" max="3" value="1.0">
<details><summary>Advanced</summary>
<div class="row">
<div><label for="ns">Noise scale</label><input id="ns" type="number" step="0.05" min="0" max="2" value="0.667"></div>
<div><label for="nw">Noise W scale</label><input id="nw" type="number" step="0.05" min="0" max="2" value="0.8"></div>
<div><label for="pre">Stream prebuffer (s)</label><input id="pre" type="number" step="0.5" min="0" max="30" value="2"></div>
</div>
</details>
<button id="unload" class="sec">Unload voice (free RAM)</button>
</fieldset>

<fieldset><legend>2. Text</legend>
<select id="src"><option value="file">Text file</option><option value="text">Pasted text</option></select>
<div id="srcfile">
<select id="file" style="margin-top:.6rem"></select>
<label for="up">Upload text file (.txt, .md, .csv; max 5 MB)</label>
<input id="up" type="file" accept=".txt,.md,.csv">
</div>
<div id="srctext" hidden>
<textarea id="txt" rows="8" maxlength="100000" placeholder="Paste or type text to speak..."></textarea>
<div id="txtcount">0 / 100000</div>
</div>
</fieldset>

<fieldset><legend>3. Run</legend>
<div class="row">
<div><button id="run">Run (save WAV)</button></div>
<div><button id="stream">Stream</button></div>
</div>
<button id="stop" class="sec" hidden>Stop</button>
<progress id="runp" max="100" value="0" hidden></progress>
<div id="status"></div>
<audio id="player" controls hidden></audio>
</fieldset>

<fieldset><legend>Outputs</legend>
<div id="radiobox" hidden>
<label for="node">Play on node (transmits)</label>
<select id="node"></select>
</div>
<ul id="outs"></ul>
</fieldset>
</div>

<div id="pg-cfg" hidden>
<fieldset><legend>Server</legend>
<label for="cf-host">Bind address (0.0.0.0 serves the LAN)</label><input id="cf-host" type="text" maxlength="255">
<label for="cf-port">Port</label><input id="cf-port" type="number" min="1" max="65535">
</fieldset>
<fieldset><legend>Engine and voices</legend>
<label><input id="cf-cuda" type="checkbox"> Use GPU (needs onnxruntime-gpu)</label>
<label for="cf-preload">Preload voice at start (.onnx file name, blank = none)</label><input id="cf-preload" type="text" maxlength="140">
<label for="cf-vbase">Voice catalog URL</label><input id="cf-vbase" type="text" maxlength="300">
</fieldset>
<fieldset><legend>Save output to Pibrary</legend>
<label for="cf-pib">Drive</label><select id="cf-pib"></select>
<div class="small" id="cf-pibnote"></div>
</fieldset>
<fieldset><legend>Play on node (transmits)</legend>
<label for="cf-nodes">Node numbers (blank = off)</label><input id="cf-nodes" type="text" maxlength="200">
<label for="cf-sounds">Sounds directory (dedicated; Asterisk must read it)</label><input id="cf-sounds" type="text" maxlength="300">
<label for="cf-maxs">Longest clip on air (seconds)</label><input id="cf-maxs" type="number" min="1" max="600">
<label for="cf-ast">Asterisk command</label><input id="cf-ast" type="text" maxlength="200">
</fieldset>
<button id="cf-save">Save settings</button>
<button id="cf-restart" class="sec">Restart service to apply</button>
<div id="cf-msg"></div>
</div>
</div>
<script>
const $ = id => document.getElementById(id);
let voices = [];
let cat = [];
let polling = null;
let sc = null;
let radio = { enabled: false, nodes: [] };
let curVersion = null;
let autoOpened = false;

function opt(sel, value, text) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = text;
  sel.appendChild(o);
}
function setStatus(msg, err) {
  const s = $('status');
  s.textContent = msg;
  s.className = err ? 'err' : '';
}
async function getJSON(url) {
  const r = await fetch(url);
  if (r.status === 401) showLogin();
  const j = await r.json();
  if (!r.ok) throw new Error(j.message || j.error || r.statusText);
  return j;
}
async function loadEngine() {
  try {
    const s = await getJSON('/api/status');
    $('logout').hidden = !s.auth;
    if (!s.auth) { $('eng').textContent = ''; return; }
    const parts = [s.engine_ok ? 'engine ok' : 'engine MISSING: ' + s.engine_error];
    parts.push(s.loaded ? 'loaded: ' + s.loaded : 'no voice loaded');
    parts.push(s.busy ? 'busy' : 'idle');
    if (s.rss_mb !== null) parts.push('RSS ' + s.rss_mb + ' MB');
    $('eng').textContent = parts.join(' | ');
    $('eng').className = s.engine_ok ? '' : 'err';
    $('unload').disabled = !s.loaded;
    $('ieng').disabled = s.engine_ok;
    $('engcard').hidden = !!s.engine_ok;
    const r = s.radio || { enabled: false, nodes: [] };
    const changed = r.enabled !== radio.enabled;
    radio = r;
    $('radiobox').hidden = !r.enabled;
    curVersion = s.version;
    $('updbox').hidden = !(s.update && s.update.enabled);
    const ns = $('node');
    if (r.enabled && ns.options.length !== r.nodes.length) {
      ns.textContent = '';
      r.nodes.forEach(n => opt(ns, n, n));
    }
    if (changed) loadOutputs().catch(() => {});
    $('engtxt').textContent = s.engine_ok ? 'piper-tts installed' : 'piper-tts not installed (' + s.platform + ', venv ' + s.venv + ')';
    if (!s.engine_ok && !autoOpened) { $('inst').open = true; autoOpened = true; }
  } catch (e) {
    $('eng').textContent = 'status failed: ' + e.message;
    $('eng').className = 'err';
  }
}
function updateSpeakers() {
  const v = voices.find(x => x.name === $('voice').value);
  const n = v ? v.speakers : 1;
  const sp = $('speaker');
  sp.textContent = '';
  for (let i = 0; i < n; i++) opt(sp, i, String(i));
  sp.disabled = n <= 1;
}
async function loadVoices() {
  voices = await getJSON('/api/voices');
  const sel = $('voice');
  const prev = sel.value;
  sel.textContent = '';
  if (!voices.length) opt(sel, '', '(no voices found)');
  voices.forEach(v => opt(sel, v.name, v.name));
  if (prev && voices.some(v => v.name === prev)) sel.value = prev;
  updateSpeakers();
}
async function loadFiles(selectName) {
  const files = await getJSON('/api/files');
  const sel = $('file');
  sel.textContent = '';
  if (!files.length) opt(sel, '', '(no files, upload one)');
  files.forEach(f => opt(sel, f.name, f.name));
  if (selectName) sel.value = selectName;
}
function play(name) {
  const p = $('player');
  p.src = '/audio/' + encodeURIComponent(name);
  p.hidden = false;
  p.play().catch(() => {});
}
function outBtn(label, cls, fn) {
  const b = document.createElement('button');
  b.textContent = label;
  if (cls) b.className = cls;
  b.onclick = fn;
  return b;
}
async function exportOut(name, fmt) {
  try {
    const j = await post('/api/export', { name: name, format: fmt });
    setStatus('Exported ' + j.name + ' (' + j.bytes + ' bytes)');
    loadOutputs();
  } catch (e) {
    setStatus('Export failed: ' + e.message, true);
  }
}
async function deleteOut(name) {
  if (!confirm('Delete ' + name + '?')) return;
  try {
    await post('/api/output/delete', { name: name });
    const pl = $('player');
    if (!pl.hidden && pl.src.endsWith('/' + encodeURIComponent(name))) {
      pl.pause();
      pl.removeAttribute('src');
      pl.hidden = true;
    }
    setStatus('Deleted ' + name);
    loadOutputs();
  } catch (e) {
    setStatus('Delete failed: ' + e.message, true);
  }
}
async function airOut(name) {
  const node = $('node').value;
  if (!confirm('TRANSMIT ' + name + ' on node ' + node + '?')) return;
  try {
    await post('/api/radio/play', { name: name, node: node });
    setStatus('Sent to node ' + node + ': ' + name);
  } catch (e) {
    setStatus('Play failed: ' + e.message, true);
  }
}
async function loadOutputs() {
  const outs = await getJSON('/api/outputs');
  const ul = $('outs');
  ul.textContent = '';
  outs.forEach(o => {
    const li = document.createElement('li');
    li.className = 'orow';
    const a = document.createElement('a');
    a.href = '/audio/' + encodeURIComponent(o.name);
    a.textContent = o.name;
    const isWav = o.name.endsWith('.wav');
    if (isWav) a.onclick = e => { e.preventDefault(); play(o.name); };
    li.appendChild(a);
    if (isWav && !o.name.endsWith('-8k.wav')) {
      li.appendChild(outBtn('ulaw', '', () => exportOut(o.name, 'ulaw')));
      li.appendChild(outBtn('8k wav', '', () => exportOut(o.name, 'wav8')));
      li.appendChild(outBtn('sln', '', () => exportOut(o.name, 'sln')));
    } else if (radio.enabled) {
      li.appendChild(outBtn('On air', 'air', () => airOut(o.name)));
    }
    li.appendChild(outBtn('Delete', 'del', () => deleteOut(o.name)));
    ul.appendChild(li);
  });
}

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    body: JSON.stringify(body || {})
  });
  if (r.status === 401) showLogin();
  const j = await r.json();
  if (!r.ok) throw new Error(j.message || j.error || r.statusText);
  return j;
}
function showJob(msg, err) {
  $('jobtxt').textContent = msg;
  $('jobtxt').className = err ? 'err' : '';
}
function renderCat() {
  const lang = $('clang').value;
  const q = $('cq').value.trim().toLowerCase();
  const rows = cat.filter(c => (!lang || c.lang === lang) && (!q || c.key.toLowerCase().includes(q)));
  const box = $('clist');
  box.textContent = '';
  if (!rows.length) box.textContent = '(no matches)';
  rows.slice(0, 200).forEach(c => {
    const d = document.createElement('div');
    d.className = 'vrow';
    const t = document.createElement('span');
    t.textContent = c.key + ' - ' + c.mb + ' MB' + (c.speakers > 1 ? ' - ' + c.speakers + ' speakers' : '');
    d.appendChild(t);
    const b = document.createElement('button');
    b.textContent = c.installed ? 'Installed' : 'Install';
    b.disabled = c.installed;
    b.onclick = () => installVoice(c.key);
    d.appendChild(b);
    box.appendChild(d);
  });
  if (rows.length > 200) {
    const n = document.createElement('div');
    n.textContent = 'showing 200 of ' + rows.length + ', narrow the filter';
    box.appendChild(n);
  }
}
async function loadCatalog(refresh) {
  const prev = $('clang').value;
  cat = await getJSON('/api/catalog' + (refresh ? '?refresh=1' : ''));
  const langs = new Map();
  cat.forEach(c => langs.set(c.lang, c.lang_name));
  const sel = $('clang');
  sel.textContent = '';
  opt(sel, '', 'All languages');
  Array.from(langs.keys()).sort().forEach(k => opt(sel, k, k + (langs.get(k) ? ' - ' + langs.get(k) : '')));
  sel.value = prev || (langs.has('en_US') ? 'en_US' : '');
  renderCat();
}
async function installVoice(key) {
  try {
    await post('/api/install/voice', { key: key });
    pollJob();
  } catch (e) {
    showJob('Install failed: ' + e.message, true);
  }
}
async function tickJob() {
  let j;
  try { j = await getJSON('/api/job'); } catch (e) { return false; }
  const run = j.state === 'running';
  showJob(j.state === 'idle' ? '' : j.kind + ' ' + j.name + ': ' + j.state + ' - ' + j.msg, j.state === 'error');
  const p = $('jp');
  p.hidden = !run;
  if (j.total > 0) { p.max = j.total; p.value = j.done; } else { p.removeAttribute('value'); }
  const lg = $('joblog');
  lg.hidden = !j.log.length;
  lg.textContent = j.log.join('\n');
  lg.scrollTop = lg.scrollHeight;
  if (!run && polling) {
    clearInterval(polling);
    polling = null;
    loadEngine();
    loadVoices();
    if (cat.length) loadCatalog(false).catch(() => {});
  }
  return run;
}
function pollJob() {
  if (!polling) polling = setInterval(tickJob, 1000);
  tickJob();
}

$('voice').onchange = updateSpeakers;
$('src').onchange = () => {
  const t = $('src').value === 'text';
  $('srcfile').hidden = t;
  $('srctext').hidden = !t;
};
$('txt').oninput = () => { $('txtcount').textContent = $('txt').value.length + ' / 100000'; };
$('clang').onchange = renderCat;
$('cq').oninput = renderCat;

$('bcat').onclick = async () => {
  $('bcat').disabled = true;
  showJob('Fetching voice catalog...');
  try {
    await loadCatalog(true);
    showJob(cat.length + ' voices in catalog');
  } catch (e) {
    showJob('Catalog failed: ' + e.message, true);
  }
  $('bcat').disabled = false;
};

async function waitRestart() {
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      const s = await getJSON('/api/status');
      if (s.version !== curVersion) { location.reload(); return; }
    } catch (e) { /* server restarting */ }
  }
  showJob('Restart not confirmed, check the service', true);
}
$('upd').onclick = async () => {
  const f = $('updfile').files[0];
  if (!f || !$('updtok').value) { showJob('Pick a .py file and enter the token', true); return; }
  $('upd').disabled = true;
  try {
    const r = await fetch('/api/update', {
      method: 'POST',
      headers: { 'X-Update-Token': $('updtok').value, 'X-Restart': $('updrs').checked ? '1' : '0' },
      body: f
    });
    if (r.status === 401) showLogin();
  const j = await r.json();
    if (!r.ok) throw new Error(j.message || j.error || r.statusText);
    showJob('Staged ' + j.staged + (j.restarting ? ', restarting...' : ' (restart the service to apply)'));
    if (j.restarting) waitRestart();
  } catch (e) {
    showJob('Update failed: ' + e.message, true);
  }
  $('updtok').value = '';
  $('upd').disabled = false;
};

$('ieng').onclick = async () => {
  try {
    await post('/api/install/engine');
    pollJob();
  } catch (e) {
    showJob('Install failed: ' + e.message, true);
  }
};

$('unload').onclick = async () => {
  try {
    const r = await fetch('/api/unload', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (r.status === 401) showLogin();
  const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    setStatus('Voice unloaded');
  } catch (e) {
    setStatus('Unload failed: ' + e.message, true);
  }
  loadEngine();
};

$('up').onchange = async () => {
  const f = $('up').files[0];
  if (!f) return;
  setStatus('Uploading ' + f.name + '...');
  try {
    const r = await fetch('/api/upload', {
      method: 'POST',
      headers: { 'X-Filename': encodeURIComponent(f.name), 'X-Requested-With': 'XMLHttpRequest' },
      body: f
    });
    if (r.status === 401) showLogin();
  const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    await loadFiles(j.name);
    setStatus('Uploaded ' + j.name);
  } catch (e) {
    setStatus('Upload failed: ' + e.message, true);
  }
  $('up').value = '';
};

function reqBody() {
  const b = {
    voice: $('voice').value,
    speaker: parseInt($('speaker').value || '0', 10),
    length_scale: parseFloat($('ls').value),
    noise_scale: parseFloat($('ns').value),
    noise_w_scale: parseFloat($('nw').value)
  };
  if ($('src').value === 'text') b.text = $('txt').value;
  else b.file = $('file').value;
  return b;
}
function checkSrc() {
  if ($('src').value === 'text' && !$('txt').value.trim()) {
    setStatus('Enter some text first', true);
    return false;
  }
  return true;
}
let progTimer = null;
function trackProgress() {
  const p = $('runp');
  p.hidden = false;
  p.value = 0;
  clearInterval(progTimer);
  progTimer = setInterval(async () => {
    try {
      const j = await getJSON('/api/progress');
      if (j.total > 0) { p.max = j.total; p.value = j.done; }
      if (j.state !== 'running') {
        clearInterval(progTimer);
        progTimer = null;
        setTimeout(() => { p.hidden = true; }, 1500);
      }
    } catch (e) {}
  }, 400);
}
function setBusy(b) {
  $('run').disabled = b;
  $('stream').disabled = b;
}
function pcmFloats(u8, carry) {
  let b = u8;
  if (carry.length) {
    b = new Uint8Array(carry.length + u8.length);
    b.set(carry);
    b.set(u8, carry.length);
  }
  const n = b.length >> 1;
  const f = new Float32Array(n);
  const dv = new DataView(b.buffer, b.byteOffset, n * 2);
  for (let i = 0; i < n; i++) f[i] = dv.getInt16(i * 2, true) / 32768;
  return { f: f, carry: b.slice(n * 2) };
}

$('stop').onclick = () => {
  if (!sc) return;
  sc.ctrl.abort();
  sc.ctx.close().catch(() => {});
  sc = null;
  $('stop').hidden = true;
};

$('stream').onclick = async () => {
  if (!checkSrc()) return;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) { setStatus('Web Audio not supported in this browser', true); return; }
  const ctx = new AC();
  ctx.resume();
  const ctrl = new AbortController();
  const mine = { ctrl: ctrl, ctx: ctx };
  sc = mine;
  $('stop').hidden = false;
  setBusy(true);
  setStatus('Streaming... (first run loads the voice)');
  trackProgress();
  const t0 = performance.now();
  try {
    const r = await fetch('/api/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(reqBody()),
      signal: ctrl.signal
    });
    if (!r.ok) {
      if (r.status === 401) showLogin();
  const j = await r.json();
      throw new Error(j.message || j.error || r.statusText);
    }
    const rate = parseInt(r.headers.get('X-Audio-Sample-Rate') || '22050', 10);
    const pre = Math.max(0, parseFloat($('pre').value) || 0);
    const rd = r.body.getReader();
    let carry = new Uint8Array(0);
    let queue = [];
    let buffered = 0;
    let total = 0;
    let playing = false;
    let next = 0;
    let first = null;
    const sched = f => {
      const ab = ctx.createBuffer(1, f.length, rate);
      ab.copyToChannel(f, 0);
      const s = ctx.createBufferSource();
      s.buffer = ab;
      s.connect(ctx.destination);
      next = Math.max(next, ctx.currentTime + 0.05);
      s.start(next);
      next += ab.duration;
    };
    const flush = () => {
      playing = true;
      queue.forEach(sched);
      queue = [];
    };
    for (;;) {
      const x = await rd.read();
      if (x.done) break;
      if (first === null) first = (performance.now() - t0) / 1000;
      const p = pcmFloats(x.value, carry);
      carry = p.carry;
      if (!p.f.length) continue;
      total += p.f.length / rate;
      if (playing) {
        sched(p.f);
      } else {
        queue.push(p.f);
        buffered += p.f.length / rate;
        if (buffered >= pre) flush();
      }
      setStatus('Streaming... ' + total.toFixed(1) + ' s of audio received');
    }
    if (!playing) flush();
    const wall = (performance.now() - t0) / 1000;
    if (total > 0) {
      setStatus('Stream done: ' + total.toFixed(1) + ' s audio in ' + wall.toFixed(1) + ' s (RTF '
        + (wall / total).toFixed(2) + ', first audio ' + first.toFixed(1) + ' s)'
        + (wall > total ? ' - slower than real time, raise prebuffer' : ''));
    } else {
      setStatus('Stream ended with no audio (synthesis may have failed)', true);
    }
    setTimeout(() => {
      ctx.close().catch(() => {});
      if (sc === mine) { sc = null; $('stop').hidden = true; }
    }, Math.max(0, next - ctx.currentTime) * 1000 + 500);
  } catch (e) {
    ctx.close().catch(() => {});
    if (sc === mine) { sc = null; $('stop').hidden = true; }
    if (e.name === 'AbortError') setStatus('Stopped');
    else setStatus('Stream failed: ' + e.message, true);
  }
  setBusy(false);
  loadEngine();
};

$('run').onclick = async () => {
  if (!checkSrc()) return;
  setBusy(true);
  setStatus('Synthesizing... (first run loads the voice; slow on a Pi)');
  trackProgress();
  try {
    const r = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(reqBody())
    });
    if (r.status === 401) showLogin();
  const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    setStatus('Done: ' + j.audio + ' (' + j.seconds + ' s)' + (j.note ? ' - ' + j.note : ''));
    play(j.audio);
    loadOutputs();
  } catch (e) {
    setStatus('Failed: ' + e.message, true);
  }
  setBusy(false);
  loadEngine();
};

function showLogin() {
  $('lg').hidden = false;
  $('lg-pw').focus();
}
$('lgform').onsubmit = async e => {
  e.preventDefault();
  $('lg-msg').textContent = '';
  try {
    await post('/api/login', { password: $('lg-pw').value });
    location.reload();
  } catch (err) {
    $('lg-msg').textContent = err.message;
  }
};
function showTab(which) {
  $('pg-run').hidden = which !== 'run';
  $('pg-cfg').hidden = which !== 'cfg';
  $('tab-run').className = 'tab' + (which === 'run' ? ' on' : '');
  $('tab-cfg').className = 'tab' + (which === 'cfg' ? ' on' : '');
  if (which === 'cfg') loadConfig();
}
function cfgMsg(m, err) {
  $('cf-msg').textContent = m;
  $('cf-msg').className = err ? 'err' : '';
}
async function loadConfig() {
  try {
    const c = await getJSON('/api/config');
    $('cf-host').value = c.host;
    $('cf-port').value = c.port;
    $('cf-cuda').checked = c.cuda;
    $('cf-preload').value = c.preload;
    $('cf-vbase').value = c.voices_base;
    $('cf-nodes').value = c.nodes;
    $('cf-sounds').value = c.sounds_dir;
    $('cf-maxs').value = c.max_seconds;
    $('cf-ast').value = c.asterisk_cmd;
    const sel = $('cf-pib');
    sel.textContent = '';
    c.pibrary.options.forEach(o => opt(sel, o.root, o.label));
    sel.value = c.pibrary_root;
    $('cf-pibnote').textContent = c.pibrary.running
      ? 'Pibrary is running. Audio goes to the drive\'s audio/TTS folder.'
      : 'Pibrary is not running: audio goes to the local output folder.';
    cfgMsg('');
  } catch (e) {
    cfgMsg('Load failed: ' + e.message, true);
  }
}
async function saveConfig(extra) {
  const body = {
    host: $('cf-host').value, port: $('cf-port').value, cuda: $('cf-cuda').checked,
    preload: $('cf-preload').value, voices_base: $('cf-vbase').value, nodes: $('cf-nodes').value,
    sounds_dir: $('cf-sounds').value, max_seconds: $('cf-maxs').value, asterisk_cmd: $('cf-ast').value,
    pibrary_root: $('cf-pib').value
  };
  Object.assign(body, extra || {});
  const r = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    body: JSON.stringify(body)
  });
  if (r.status === 401) showLogin();
  const j = await r.json();
  if (r.status === 409 && j.confirm === 'radio') {
    if (confirm('Play on node transmits on your node. Turn it on?')) return saveConfig({ radio_confirm: true });
    loadConfig();
    return null;
  }
  if (!r.ok) throw new Error(j.message || r.statusText);
  return j;
}
$('cf-save').onclick = async () => {
  try {
    const j = await saveConfig();
    if (j) cfgMsg(j.message, false);
  } catch (e) {
    cfgMsg('Save failed: ' + e.message, true);
  }
};
$('cf-restart').onclick = async () => {
  if (!confirm('Restart the Pi-Piper service now? Any run in progress stops.')) return;
  try {
    await post('/api/restart');
    cfgMsg('Restarting...');
  } catch (e) {
    cfgMsg('Restart failed: ' + e.message, true);
  }
};
$('tab-run').onclick = () => showTab('run');
$('tab-cfg').onclick = () => showTab('cfg');
$('logout').onclick = async () => {
  try { await post('/api/logout'); } catch (e) {}
  location.reload();
};
(async () => {
  try {
    await loadVoices();
    await loadFiles();
    await loadOutputs();
  } catch (e) {
    setStatus('Load failed: ' + e.message, true);
  }
  loadEngine();
  if (await tickJob()) pollJob();
})();
</script>
</body></html>
"""


def clamp_float(v, lo, hi, default):
    if v is None:
        return default
    f = float(v)
    if not math.isfinite(f):
        return default
    return min(max(f, lo), hi)


PROG_LOCK = threading.Lock()
PROG = {"state": "idle", "done": 0, "total": 0}


def sentence_count(text):
    return max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)))


def prog_start(text):
    with PROG_LOCK:
        PROG.update(state="running", done=0, total=sentence_count(text))


def prog_tick():
    with PROG_LOCK:
        if PROG["state"] == "running" and PROG["done"] < PROG["total"] - 1:
            PROG["done"] += 1


def prog_end(ok):
    with PROG_LOCK:
        PROG["state"] = "done" if ok else "error"
        if ok:
            PROG["done"] = PROG["total"]


def prog_snapshot():
    with PROG_LOCK:
        return dict(PROG)


class Handler(BaseHTTPRequestHandler):
    server_version = "PiperDash/" + VERSION

    _renew_token = None

    def log_message(self, fmt, *args):
        pass

    def _sec_headers(self):
        return {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer", "Content-Security-Policy": CSP}

    def authed(self):
        token = sess_token_from(self.headers.get("Cookie"), _SESSION_COOKIE_NAME)
        now = time.time()
        with SESS_LOCK:
            ok, renew, _left = sess_check(SESS_STORE, token, sess_policy(SESS_TIER), now, stamp=auth_stamp())
        if ok and renew:
            self._renew_token = token
        return ok

    def handle_login(self, raw):
        ip = self.client_address[0]
        now = time.time()
        with SESS_LOCK:
            wait = lock_wait(LOCK_STATE, ip, now)
        if wait > 0:
            return self._json(429, {"message": "too many attempts; wait %d s" % int(wait + 0.5)})
        try:
            pw = str(json.loads(raw.decode("utf-8")).get("password", ""))
        except (ValueError, AttributeError):
            return self._json(400, {"message": "bad request"})
        if not verify_root_password(pw):
            with SESS_LOCK:
                wait = lock_fail(LOCK_STATE, ip, now)
            msg = "wrong password" + ("; wait %d s" % int(wait + 0.5) if wait > 0 else "")
            return self._json(401, {"message": msg})
        with SESS_LOCK:
            lock_ok(LOCK_STATE, ip)
            token, max_age = sess_new(SESS_STORE, sess_policy(SESS_TIER), now, stamp=auth_stamp())
        self._send(200, json.dumps({"ok": True}),
                   extra={"Set-Cookie": sess_cookie(_SESSION_COOKIE_NAME, token, max_age, False)})

    def handle_logout(self):
        with SESS_LOCK:
            sess_drop_all(SESS_STORE)
        self._send(200, json.dumps({"ok": True}),
                   extra={"Set-Cookie": sess_cookie_clear(_SESSION_COOKIE_NAME, False)})

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in self._sec_headers().items():
            self.send_header(k, v)
        if self._renew_token:
            self.send_header("Set-Cookie", sess_cookie(_SESSION_COOKIE_NAME, self._renew_token,
                                                       sess_policy(SESS_TIER)["idle"], False))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def do_GET(self):
        path = urlparse(self.path).path
        if path not in ("/", "/api/status") and not self.authed():
            return self._json(401, {"message": "login required", "login": True})
        if path == "/":
            self._send(200, login_ui_inject(HTML.replace("__VERSION__", VERSION), "lg-pw"),
                       "text/html; charset=utf-8")
        elif path == "/api/voices":
            self._json(200, list_voices(CFG["voices"]))
        elif path == "/api/files":
            self._json(200, list_files(CFG["workdir"], TEXT_EXTS))
        elif path == "/api/outputs":
            self._json(200, list_files(CFG["outdir"], OUT_EXTS))
        elif path == "/api/status":
            if not self.authed():
                return self._json(200, {"version": VERSION, "engine_ok": ENGINE_ERR is None, "auth": False})
            kb = rss_kb()
            self._json(200, {
                "version": VERSION,
                "auth": True,
                "engine_ok": ENGINE_ERR is None,
                "engine_error": ENGINE_ERR,
                "loaded": ENG.name,
                "busy": ENG.lock.locked(),
                "rss_mb": None if kb is None else round(kb / 1024),
                "platform": sysconfig.get_platform(),
                "venv": CFG["venv"],
                "legacy_cli": find_legacy_cli(),
                "radio": {"enabled": radio_enabled(), "nodes": CFG.get("radio_nodes", [])},
            })
        elif path == "/api/config":
            self.handle_config_get()
        elif path == "/api/progress":
            self._json(200, prog_snapshot())
        elif path == "/api/job":
            self._json(200, job_snapshot())
        elif path == "/api/catalog":
            self.handle_catalog()
        elif path.startswith("/audio/"):
            p = safe_join(CFG["outdir"], unquote(path[len("/audio/"):]))
            if p is None:
                return self._json(404, {"error": "not found"})
            if p.suffix.lower() == ".wav":
                self._send(200, p.read_bytes(), "audio/wav")
            else:
                self._send(200, p.read_bytes(), "application/octet-stream",
                           {"Content-Disposition": 'attachment; filename="%s"' % p.name})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        limit = MAX_UPLOAD if path == "/api/upload" else MAX_JSON
        if length > limit:
            self.close_connection = True
            return self._json(413, {"error": "request too large"})
        raw = self.rfile.read(length)
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            return self._json(403, {"message": "forbidden"})
        if path == "/api/login":
            return self.handle_login(raw)
        if not self.authed():
            return self._json(401, {"message": "login required", "login": True})
        if path == "/api/logout":
            return self.handle_logout()
        if path == "/api/upload":
            return self.handle_upload(raw)
        if path == "/api/run":
            return self.handle_run(raw)
        if path == "/api/unload":
            return self.handle_unload()
        if path == "/api/stream":
            return self.handle_stream(raw)
        if path == "/api/export":
            return self.handle_export(raw)
        if path == "/api/output/delete":
            return self.handle_output_delete(raw)
        if path == "/api/radio/play":
            return self.handle_radio_play(raw)
        if path == "/api/config":
            return self.handle_config_save(raw)
        if path == "/api/restart":
            return self.handle_restart()
        if path == "/api/install/engine":
            return self.handle_install_engine()
        if path == "/api/install/voice":
            return self.handle_install_voice(raw)
        self._json(404, {"error": "not found"})

    def handle_config_get(self):
        try:
            vals = config_values(read_config())
        except (ValueError, configparser.Error) as e:
            return self._json(500, {"message": "settings unreadable: %s" % e})
        vals["pibrary"] = pibrary_choices(vals["pibrary_root"])
        self._json(200, vals)

    def handle_config_save(self, raw):
        try:
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("bad request")
            vals = validate_config(body, config_values(read_config()))
        except ConfirmNeeded as e:
            return self._json(409, {"message": str(e), "confirm": "radio"})
        except (ValueError, TypeError, AttributeError, configparser.Error) as e:
            return self._json(400, {"message": str(e)})
        try:
            _atomic_write(CONFIG_PATH, config_text(vals), 0o644)
        except OSError as e:
            return self._json(500, {"message": "could not write %s: %s" % (CONFIG_PATH, e)})
        self._json(200, {"ok": True, "message": "Saved. Restart the service to apply."})

    def handle_restart(self):
        if not os.environ.get("INVOCATION_ID"):
            return self._json(409, {"message": "not running under systemd; restart it by hand"})
        threading.Timer(1.0, lambda: subprocess.run(
            ["systemctl", "--no-block", "restart", SERVICE_NAME], capture_output=True)).start()
        self._json(202, {"ok": True})

    def handle_upload(self, raw):
        name = Path(unquote(self.headers.get("X-Filename", ""))).name
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        if not name or Path(name).suffix.lower() not in TEXT_EXTS:
            return self._json(400, {"error": "use a .txt, .md or .csv file"})
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            return self._json(400, {"error": "file must be UTF-8 text"})
        (Path(CFG["workdir"]) / name).write_bytes(raw)
        self._json(200, {"name": name})

    def handle_catalog(self):
        force = "refresh" in parse_qs(urlparse(self.path).query)
        try:
            data = fetch_catalog(force)
        except Exception as e:
            return self._json(502, {"error": "catalog fetch failed: %s: %s" % (type(e).__name__, e)})
        have = {v["name"] for v in list_voices(CFG["voices"])}
        out = [{"key": e["key"], "lang": e["lang"], "lang_name": e["lang_name"],
                "name": e["name"], "quality": e["quality"], "speakers": e["speakers"],
                "mb": round(sum(f[1] for f in e["files"]) / 1048576, 1),
                "installed": (e["key"] + ".onnx") in have} for e in data.values()]
        out.sort(key=lambda e: e["key"])
        self._json(200, out)

    def handle_install_engine(self):
        if ENGINE_ERR is None:
            return self._json(409, {"error": "engine already installed"})
        if not start_job("engine", "piper-tts", install_engine):
            return self._json(409, {"error": "another install is running"})
        self._json(202, {"ok": True})

    def handle_install_voice(self, raw):
        try:
            key = str(json.loads(raw.decode("utf-8")).get("key", ""))
        except (ValueError, AttributeError):
            return self._json(400, {"error": "bad request"})
        if (CAT["data"] or {}).get(key) is None:
            return self._json(400, {"error": "unknown voice (refresh the catalog)"})
        if key in {v["name"][:-5] for v in list_voices(CFG["voices"])}:
            return self._json(409, {"error": "already installed"})
        if not start_job("voice", key, install_voice, key):
            return self._json(409, {"error": "another install is running"})
        self._json(202, {"ok": True})


    def handle_output_delete(self, raw):
        try:
            name = str(json.loads(raw.decode("utf-8")).get("name", ""))
        except (ValueError, AttributeError):
            return self._json(400, {"error": "bad request"})
        p = safe_join(CFG["outdir"], name)
        if p is None or p.suffix.lower() not in OUT_EXTS:
            return self._json(400, {"error": "unknown output"})
        try:
            p.unlink()
        except OSError as e:
            return self._json(500, {"error": "delete failed: %s" % e})
        self._json(200, {"ok": True})

    def handle_export(self, raw):
        try:
            req = json.loads(raw.decode("utf-8"))
            name = str(req.get("name", ""))
            fmt = str(req.get("format", ""))
        except (ValueError, AttributeError):
            return self._json(400, {"error": "bad request"})
        if fmt not in EXPORT_FORMATS:
            return self._json(400, {"error": "format must be one of: " + ", ".join(EXPORT_FORMATS)})
        src = safe_join(CFG["outdir"], name)
        if src is None or src.suffix.lower() != ".wav" or name.endswith("-8k.wav"):
            return self._json(400, {"error": "pick a saved full-rate WAV"})
        np = _numpy()
        if np is None:
            return self._json(500, {"error": "numpy not available (install the engine first)"})
        out_name = src.stem + EXPORT_FORMATS[fmt]
        out = Path(CFG["outdir"]) / out_name
        with EXPORT_LOCK:
            try:
                data = export_audio(np, src, fmt)
                tmp = out.with_name(out_name + ".part")
                tmp.write_bytes(data)
                os.replace(tmp, out)
            except (ValueError, wave.Error, EOFError) as e:
                return self._json(400, {"error": str(e)})
            except OSError as e:
                return self._json(500, {"error": "write failed: %s" % e})
        self._json(200, {"name": out_name, "bytes": len(data)})

    def handle_radio_play(self, raw):
        if not radio_enabled():
            return self._json(403, {"error": "play-on-node is not enabled (set [radio] nodes and sounds_dir)"})
        try:
            req = json.loads(raw.decode("utf-8"))
            name = str(req.get("name", ""))
            node = str(req.get("node", ""))
        except (ValueError, AttributeError):
            return self._json(400, {"error": "bad request"})
        if node not in CFG["radio_nodes"]:
            return self._json(400, {"error": "node not in the configured list"})
        src = safe_join(CFG["outdir"], name)
        if src is None:
            return self._json(400, {"error": "unknown file"})
        try:
            secs, ok = air_info(src)
        except OSError as e:
            return self._json(500, {"error": str(e)})
        if not ok:
            return self._json(400, {"error": "export to ulaw, sln or 8k wav first"})
        if secs > CFG["radio_max_seconds"]:
            return self._json(400, {"error": "%.0f s exceeds the %d s on-air limit" % (secs, CFG["radio_max_seconds"])})
        sd = Path(CFG["radio_sounds"])
        with RADIO_LOCK:
            try:
                for old in sd.glob(RADIO_BASE + ".*"):
                    old.unlink()
                dst = sd / (RADIO_BASE + src.suffix.lower())
                tmp = sd / (RADIO_BASE + ".part")
                shutil.copyfile(src, tmp)
                os.chmod(tmp, 0o644)
                os.replace(tmp, dst)
                r = subprocess.run([CFG["asterisk"], "-rx", "rpt playback %s %s" % (node, sd / RADIO_BASE)],
                                   capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.SubprocessError) as e:
                return self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})
        if r.returncode != 0:
            return self._json(500, {"error": "asterisk failed: " + (r.stderr or r.stdout).strip()[-200:]})
        self._json(200, {"ok": True, "seconds": round(secs, 1), "output": r.stdout.strip()[-200:]})

    def handle_unload(self):
        if not ENG.lock.acquire(blocking=False):
            return self._json(409, {"error": "busy synthesizing"})
        try:
            ENG.drop()
        finally:
            ENG.lock.release()
        self._json(200, {"ok": True})

    def _parse_run(self, raw):
        if ENGINE_ERR is not None:
            self._json(500, {"error": "piper engine unavailable: " + ENGINE_ERR})
            return None
        try:
            req = json.loads(raw.decode("utf-8"))
            voice = str(req.get("voice", ""))
            pasted = req.get("text")
            fname = str(req.get("file", ""))
            speaker = max(0, int(req.get("speaker", 0)))
            ls = clamp_float(req.get("length_scale"), 0.3, 3.0, 1.0)
            ns = clamp_float(req.get("noise_scale"), 0.0, 2.0, None)
            nw = clamp_float(req.get("noise_w_scale"), 0.0, 2.0, None)
        except (ValueError, TypeError, AttributeError):
            self._json(400, {"error": "bad request"})
            return None

        voice_info = {v["name"]: v for v in list_voices(CFG["voices"])}
        if voice not in voice_info:
            self._json(400, {"error": "unknown voice"})
            return None
        nspk = voice_info[voice]["speakers"]
        if speaker >= nspk:
            self._json(400, {"error": "speaker out of range for this voice"})
            return None

        if isinstance(pasted, str):
            stem = "text"
            text = " ".join(pasted.split())
        else:
            src = safe_join(CFG["workdir"], fname)
            if src is None:
                self._json(400, {"error": "unknown file"})
                return None
            stem = src.stem
            text = " ".join(src.read_text(encoding="utf-8", errors="replace").split())
        if not text:
            self._json(400, {"error": "text is empty"})
            return None
        if len(text) > MAX_TEXT:
            self._json(413, {"error": "text too long (%d > %d chars)" % (len(text), MAX_TEXT)})
            return None
        cfg = SynthesisConfig(
            speaker_id=speaker if nspk > 1 else None,
            length_scale=ls,
            noise_scale=ns,
            noise_w_scale=nw,
        )
        return voice, stem, text, cfg

    def handle_run(self, raw):
        r = self._parse_run(raw)
        if r is None:
            return
        voice, stem, text, cfg = r
        out_name = "%s-%s-%s.wav" % (stem, Path(voice).stem, time.strftime("%Y%m%d-%H%M%S"))
        out_dir, note = tts_output_dir()
        out = Path(out_dir) / out_name
        t0 = time.time()
        with ENG.lock:
            prog_start(text)
            try:
                v = ENG.ensure(voice)
                with wave.open(str(out), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(v.config.sample_rate)
                    for chunk in v.synthesize(text, syn_config=cfg):
                        if chunk.audio_int16_bytes:
                            wf.writeframes(chunk.audio_int16_bytes)
                        prog_tick()
                prog_end(True)
            except Exception as e:
                prog_end(False)
                try:
                    out.unlink()
                except OSError:
                    pass
                return self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})
        self._json(200, {"audio": out_name, "seconds": round(time.time() - t0, 1),
                         "saved_to": str(out), "note": note})

    def handle_stream(self, raw):
        r = self._parse_run(raw)
        if r is None:
            return
        voice, _stem, text, cfg = r
        if not ENG.lock.acquire(timeout=5):
            return self._json(409, {"error": "engine busy"})
        try:
            try:
                v = ENG.ensure(voice)
            except Exception as e:
                return self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})
            self.connection.settimeout(30)
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            for hk, hv in self._sec_headers().items():
                self.send_header(hk, hv)
            self.send_header("Connection", "close")
            self.send_header("X-Audio-Format", "s16le")
            self.send_header("X-Audio-Sample-Rate", str(v.config.sample_rate))
            self.send_header("X-Audio-Sample-Width", "2")
            self.send_header("X-Audio-Channels", "1")
            self.end_headers()
            gen = v.synthesize(text, syn_config=cfg)
            prog_start(text)
            ok = False
            try:
                for chunk in gen:
                    data = chunk.audio_int16_bytes
                    if data:
                        self.wfile.write(data)
                    prog_tick()
                ok = True
            except OSError:
                pass
            except Exception as e:
                print("stream failed: %s: %s" % (type(e).__name__, e), file=sys.stderr)
            finally:
                close = getattr(gen, "close", None)
                if close:
                    close()
                prog_end(ok)
        finally:
            ENG.lock.release()


def sd_notify(msg):
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return False
    if path[0] == "@":
        path = "\0" + path[1:]
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        s.connect(path)
        s.sendall(msg.encode("utf-8"))
        return True
    except OSError:
        return False
    finally:
        s.close()


def healthy(host, port):
    try:
        c = http.client.HTTPConnection(host, port, timeout=5)
        try:
            c.request("GET", "/api/status")
            return c.getresponse().status == 200
        finally:
            c.close()
    except (OSError, http.client.HTTPException):
        return False


def start_watchdog(host, port):
    try:
        usec = int(os.environ.get("WATCHDOG_USEC", "0"))
    except ValueError:
        usec = 0
    if usec <= 0:
        return
    interval = max(1.0, usec / 2e6)
    hh = "127.0.0.1" if host in ("", "0.0.0.0") else host

    def loop():
        while True:
            if healthy(hh, port):
                sd_notify("WATCHDOG=1")
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()


def run_selftests():
    import contextlib
    import struct
    import tempfile
    import types
    import unittest
    import unittest.mock as mock

    M = sys.modules[__name__]
    np = _numpy()
    need_np = unittest.skipUnless(np is not None, "numpy not installed")
    TONE = b"".join(struct.pack("<h", int(8000 * __import__("math").sin(6.2831853 * 440 * i / 22050)))
                    for i in range(22050))

    def fake_chunk(b):
        return types.SimpleNamespace(audio_int16_bytes=b)

    class FakeVoice:
        @staticmethod
        def load(path, use_cuda=False):
            if "broken" in path:
                raise RuntimeError("bad model")
            v = FakeVoice()
            v.config = types.SimpleNamespace(sample_rate=22050)
            return v

        def synthesize(self, text, syn_config=None):
            yield fake_chunk(TONE[:4410])
            yield fake_chunk(TONE[:4410])

        def synthesize_wav(self, text, wf, syn_config=None):
            wf.setframerate(22050)
            wf.setsampwidth(2)
            wf.setnchannels(1)
            wf.writeframes(TONE)

    def fake_synth_cfg(**kw):
        return types.SimpleNamespace(**kw)

    def variant(ver):
        with open(__file__, encoding="utf-8") as f:
            return re.sub(r'^VERSION = ".*"$', 'VERSION = "%s"' % ver, f.read(), flags=re.M).encode("utf-8")

    def quiet(fn, *a):
        with contextlib.redirect_stdout(io.StringIO()):
            return fn(*a)

    class PureTests(unittest.TestCase):
        def test_safe_name_rules(self):
            self.assertTrue(M.SAFE_NAME.match("a.b-c_d.txt"))
            for bad in ("../x", "a b", "", "a/b", "x" * 129):
                self.assertFalse(M.SAFE_NAME.match(bad), bad)

        def test_safe_join_blocks_traversal(self):
            d = tempfile.mkdtemp()
            open(os.path.join(d, "ok.txt"), "w").close()
            self.assertIsNotNone(M.safe_join(d, "ok.txt"))
            self.assertIsNone(M.safe_join(d, "../ok.txt"))
            self.assertIsNone(M.safe_join(d, "missing.txt"))

        def test_clamp_float_bounds(self):
            self.assertEqual(M.clamp_float(None, 0, 1, 0.5), 0.5)
            self.assertEqual(M.clamp_float("9", 0, 2, 1), 2)
            self.assertEqual(M.clamp_float(-5, 0.3, 3, 1), 0.3)

        def test_list_voices_needs_json_and_reads_speakers(self):
            d = tempfile.mkdtemp()
            for n, spk in (("a", 1), ("b", 4)):
                open(os.path.join(d, n + ".onnx"), "w").close()
                open(os.path.join(d, n + ".onnx.json"), "w").write(json.dumps({"num_speakers": spk}))
            open(os.path.join(d, "orphan.onnx"), "w").close()
            self.assertEqual([(v["name"], v["speakers"]) for v in M.list_voices(d)], [("a.onnx", 1), ("b.onnx", 4)])

        def test_list_files_filters_and_sorts(self):
            d = tempfile.mkdtemp()
            for i, n in enumerate(("old.txt", "new.txt", "skip.bin")):
                p = os.path.join(d, n)
                open(p, "w").close()
                os.utime(p, (1000 + i, 1000 + i))
            self.assertEqual([f["name"] for f in M.list_files(d, {".txt"})], ["new.txt", "old.txt"])

        def test_parse_voice_with_files(self):
            v = {"language": {"code": "en_US", "name_english": "English"}, "num_speakers": 2, "files": {
                "en/en_US/x/low/en_US-x-low.onnx": {"size_bytes": 5, "md5_digest": "ab"},
                "en/en_US/x/low/en_US-x-low.onnx.json": {"size_bytes": 2, "md5_digest": "cd"},
                "en/en_US/x/low/MODEL_CARD": {}}}
            e = M.parse_voice("en_US-x-low", v)
            self.assertEqual([f[0].rsplit("/", 1)[-1] for f in e["files"]], ["en_US-x-low.onnx.json", "en_US-x-low.onnx"])
            self.assertEqual((e["lang"], e["speakers"], e["quality"]), ("en_US", 2, "low"))

        def test_parse_voice_fallback_layout(self):
            e = M.parse_voice("de_DE-thorsten-high", {})
            self.assertEqual(e["files"][1][0], "de/de_DE/thorsten/high/de_DE-thorsten-high.onnx")

        def test_parse_voice_rejects_bad_input(self):
            self.assertIsNone(M.parse_voice("evil-../x-y", {}))
            self.assertIsNone(M.parse_voice("en_US-x-low", {"files": {"../../etc/passwd": {}, "a/en_US-x-low.onnx": {}}}))
            self.assertIsNone(M.parse_voice("en_US-x-low", "notadict"))


        def test_ini_defaults_flow_into_parser(self):
            v = M.default_values("0.0.0.0", 9999)
            cp = configparser.ConfigParser(interpolation=None)
            cp.read_string(M.config_text(v))
            self.assertEqual(M.config_values(cp), v)
            a = M.build_parser(cp).parse_args([])
            self.assertEqual((a.host, a.port, a.venv, a.radio_nodes), ("0.0.0.0", 9999, M.DATA_ROOT + "/venv", ""))
            self.assertFalse(cp.has_section("update"))

        def test_legacy_venv_is_found_and_counted(self):
            d = tempfile.mkdtemp(prefix="pd_legacy_")
            try:
                os.makedirs(os.path.join(d, "lib", "python3.13", "site-packages", "piper"))
                open(os.path.join(d, "lib", "python3.13", "site-packages", "piper", "__init__.py"), "w").close()
                saved = (M.LEGACY_VENV_GLOBS, dict(M.CFG))
                try:
                    M.LEGACY_VENV_GLOBS = (d,)
                    M.CFG.pop("venv", None)
                    self.assertEqual(M.find_legacy_venvs(), [d])
                    self.assertEqual(M.sentence_count("Hello there. Bye! Ok?"), 3)
                finally:
                    M.LEGACY_VENV_GLOBS = saved[0]
                    M.CFG.clear()
                    M.CFG.update(saved[1])
            finally:
                shutil.rmtree(d, ignore_errors=True)

        def test_config_validation_and_confirm(self):
            cur = M.default_values("0.0.0.0", 8765)
            good = {"host": "0.0.0.0", "port": "8765", "cuda": False, "preload": "", "voices_base": M.VOICES_BASE,
                    "nodes": "", "sounds_dir": "", "max_seconds": 60, "asterisk_cmd": "asterisk", "pibrary_root": ""}
            self.assertEqual(M.validate_config(good, cur)["port"], 8765)
            for bad in ({"port": "0"}, {"host": "bad host!"}, {"preload": "../x.onnx"}, {"voices_base": "ftp://x"},
                        {"nodes": "12,ab"}, {"pibrary_root": "relative/path"}, {"max_seconds": "9999"}):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        M.validate_config(dict(good, **bad), cur)
            with self.assertRaises(M.ConfirmNeeded):
                M.validate_config(dict(good, nodes="1234", sounds_dir="/var/lib/x"), cur)
            ok = M.validate_config(dict(good, nodes="1234", sounds_dir="/var/lib/x", radio_confirm=True), cur)
            self.assertEqual(ok["nodes"], "1234")

        def test_pibrary_output_falls_back_to_local(self):
            saved = dict(M.CFG)
            try:
                M.CFG.update(outdir="/srv/local-out")
                self.assertEqual(M.tts_output_dir(), ("/srv/local-out", ""))
            finally:
                M.CFG.clear()
                M.CFG.update(saved)


        def test_sd_notify_datagram(self):
            d = tempfile.mkdtemp()
            path = os.path.join(d, "n.sock")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            s.bind(path)
            s.settimeout(2)
            with mock.patch.dict(os.environ, {"NOTIFY_SOCKET": path}):
                self.assertTrue(M.sd_notify("READY=1"))
            self.assertEqual(s.recv(100), b"READY=1")
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertFalse(M.sd_notify("READY=1"))
            s.close()

        def test_healthy_false_on_dead_port(self):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            s.close()
            self.assertFalse(M.healthy("127.0.0.1", port))

        def test_only_one_job_at_a_time(self):
            ev = threading.Event()
            M.JOB.update(state="idle")
            self.assertTrue(M.start_job("t", "one", ev.wait, 5))
            self.assertFalse(M.start_job("t", "two", ev.wait, 5))
            ev.set()
            for _ in range(40):
                if M.job_snapshot()["state"] == "done":
                    break
                time.sleep(0.05)
            self.assertEqual(M.job_snapshot()["state"], "done")

        @need_np
        def test_ulaw_known_values(self):
            got = M.ulaw_encode(np, np.array([0, -1, 100, -100, 32767, -32768], dtype=np.int16)).tolist()
            self.assertEqual(got, [0xFF, 0x7F, 0xF2, 0x72, 0x80, 0x00])

        @need_np
        def test_resample_length_and_passband(self):
            t = np.arange(44100) / 22050.0
            x = (10000 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
            y = M.to_8k(np, x, 22050)
            self.assertEqual(len(y), int(44100 * 8000 / 22050))
            self.assertGreater(float(np.sqrt((y ** 2).mean())) / float(np.sqrt((x ** 2).mean())), 0.95)

        @need_np
        def test_export_sizes_and_air_info(self):
            d = tempfile.mkdtemp()
            w = os.path.join(d, "a.wav")
            with wave.open(w, "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(22050)
                f.writeframes(TONE)
            sizes = {fmt: len(M.export_audio(np, Path(w), fmt)) for fmt in M.EXPORT_FORMATS}
            self.assertEqual((sizes["ulaw"], sizes["sln"], sizes["wav8"]), (8000, 16000, 16044))
            for fmt, ext in (("ulaw", ".ulaw"), ("sln", ".sln"), ("wav8", ".wav")):
                p = Path(d) / ("e" + ext)
                p.write_bytes(M.export_audio(np, Path(w), fmt))
                secs, ok = M.air_info(p)
                self.assertTrue(ok, fmt)
                self.assertAlmostEqual(secs, 1.0, places=1)
            secs, ok = M.air_info(Path(w))
            self.assertFalse(ok)

    class HttpTests(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.tmp = tempfile.mkdtemp(prefix="pd_test_")
            for sub in ("v", "i", "o", "snd", "upd"):
                os.makedirs(os.path.join(cls.tmp, sub))
            for n in ("a", "multi", "broken"):
                open(os.path.join(cls.tmp, "v", n + ".onnx"), "w").write("x")
                open(os.path.join(cls.tmp, "v", n + ".onnx.json"), "w").write(
                    json.dumps({"num_speakers": 3 if n == "multi" else 1}))
            open(os.path.join(cls.tmp, "i", "t.txt"), "w").write("Hello there.")
            cls.saved = {k: getattr(M, k) for k in ("PiperVoice", "SynthesisConfig", "ENGINE_ERR", "ENG")}
            cls.saved_cfg = dict(M.CFG)
            cls.saved_verify = M.verify_root_password
            M.verify_root_password = lambda pw: pw == "pw-test"
            M.PiperVoice, M.SynthesisConfig, M.ENGINE_ERR = FakeVoice, fake_synth_cfg, None
            M.CFG.clear()
            M.CFG.update(voices=cls.tmp + "/v", workdir=cls.tmp + "/i", outdir=cls.tmp + "/o", venv=cls.tmp + "/nov",
                         voices_base="http://127.0.0.1:9", radio_nodes=[], radio_sounds="", radio_max_seconds=60,
                         asterisk="false", update_token="", update_dir=cls.tmp + "/upd")
            M.ENG = M.Engine(cls.tmp + "/v", False)
            cls.srv = M.ThreadingHTTPServer(("127.0.0.1", 0), M.Handler)
            cls.srv.daemon_threads = True
            cls.port = cls.srv.server_address[1]
            threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
            conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=15)
            conn.request("POST", "/api/login", body=json.dumps({"password": "pw-test"}),
                         headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
            conn.close()
            cls.cookie = resp.getheader("Set-Cookie", "").split(";")[0]

        @classmethod
        def tearDownClass(cls):
            cls.srv.shutdown()
            cls.srv.server_close()
            for k, v in cls.saved.items():
                setattr(M, k, v)
            M.CFG.clear()
            M.CFG.update(cls.saved_cfg)
            M.verify_root_password = cls.saved_verify
            shutil.rmtree(cls.tmp, ignore_errors=True)

        def call(self, method, path, body=None, headers=None, raw=False, auth=True):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
            data = body if isinstance(body, (bytes, bytearray)) else (None if body is None else json.dumps(body).encode())
            hdr = dict(headers or {})
            if auth:
                hdr.setdefault("Cookie", self.cookie)
                hdr.setdefault("X-Requested-With", "XMLHttpRequest")
            c.request(method, path, body=data, headers=hdr)
            r = c.getresponse()
            b = r.read()
            c.close()
            return r.status, (b if raw else json.loads(b)), dict(r.getheaders())

        def test_login_gate_and_headers(self):
            xhr = {"X-Requested-With": "XMLHttpRequest"}
            c, j, _ = self.call("GET", "/api/voices", auth=False)
            self.assertEqual(c, 401, j)
            c, _, h = self.call("GET", "/", auth=False, raw=True)
            self.assertEqual(c, 200)
            self.assertEqual(h.get("X-Frame-Options"), "DENY")
            self.assertEqual(h.get("Referrer-Policy"), "no-referrer")
            self.assertIn("default-src 'self'", h.get("Content-Security-Policy", ""))
            c, _, _ = self.call("POST", "/api/run", {"voice": "a.onnx", "file": "t.txt"}, auth=False)
            self.assertEqual(c, 403)
            c, _, _ = self.call("POST", "/api/run", {"voice": "a.onnx", "file": "t.txt"}, xhr, auth=False)
            self.assertEqual(c, 401)
            c, j, _ = self.call("POST", "/api/login", {"password": "wrong"}, xhr, auth=False)
            self.assertEqual(c, 401, j)
            c, _, h = self.call("POST", "/api/login", {"password": "pw-test"}, xhr, auth=False)
            self.assertEqual(c, 200)
            self.assertTrue(h.get("Set-Cookie", "").startswith("piper_session="))
            c, j, _ = self.call("GET", "/api/status", auth=False)
            self.assertEqual((c, j.get("auth")), (200, False))

        def test_logout_ends_every_session(self):
            xhr = {"X-Requested-With": "XMLHttpRequest"}
            other = self.call("POST", "/api/login", {"password": "pw-test"}, xhr, auth=False)[2]["Set-Cookie"].split(";")[0]
            c, _, _ = self.call("POST", "/api/logout", {}, dict(xhr, Cookie=other), auth=False)
            self.assertEqual(c, 200)
            c, _, _ = self.call("GET", "/api/voices", None, {"Cookie": self.cookie}, auth=False)
            self.assertEqual(c, 401)
            type(self).cookie = self.call("POST", "/api/login", {"password": "pw-test"}, xhr, auth=False)[2]["Set-Cookie"].split(";")[0]

        def run_wav(self):
            c, j, _ = self.call("POST", "/api/run", {"voice": "a.onnx", "file": "t.txt"})
            self.assertEqual(c, 200, j)
            return j["audio"]

        def test_status_fields(self):
            c, j, _ = self.call("GET", "/api/status")
            self.assertEqual((c, j["version"], j["engine_ok"]), (200, M.VERSION, True))
            self.assertFalse(j["radio"]["enabled"])
            self.assertNotIn("update", j)
            self.assertTrue(M.healthy("127.0.0.1", self.port))

        def test_service_unit_uses_the_suite_launcher(self):
            unit = M.service_content()
            self.assertIn("Type=notify", unit)
            self.assertIn("ExecStart=/usr/bin/python3 %s %s --config %s" % (M._LAUNCHER_PATH, M.INSTALL_BIN_PATH, M.CONFIG_PATH), unit)
            self.assertNotIn("ExecStartPre", unit)

        def test_progress_reports_the_finished_run(self):
            self.run_wav()
            c, j, _ = self.call("GET", "/api/progress")
            self.assertEqual(c, 200)
            self.assertEqual(j["state"], "done")
            self.assertTrue(j["total"] > 0)
            self.assertEqual(j["done"], j["total"])

        def test_index_page_has_title_and_version(self):
            c, b, _ = self.call("GET", "/", raw=True)
            self.assertEqual(c, 200)
            self.assertIn(b"Pi-Piper TTS", b)
            self.assertIn(("v" + M.VERSION).encode(), b)

        def test_run_file_and_pasted_text(self):
            name = self.run_wav()
            self.assertTrue(os.path.isfile(self.tmp + "/o/" + name))
            c, j, _ = self.call("POST", "/api/run", {"voice": "a.onnx", "text": " KD8PGK \n 73 "})
            self.assertEqual(c, 200)
            self.assertTrue(j["audio"].startswith("text-a-"))

        def test_run_validation_errors(self):
            bad = [{"voice": "nope.onnx", "file": "t.txt"}, {"voice": "multi.onnx", "file": "t.txt", "speaker": 5},
                   {"voice": "a.onnx", "text": "   "}, {"voice": "../a.onnx", "file": "t.txt"},
                   {"voice": "a.onnx", "file": "missing.txt"}, {"voice": "a.onnx", "file": "../x"}]
            for body in bad:
                self.assertEqual(self.call("POST", "/api/run", body)[0], 400, body)
            self.assertEqual(self.call("POST", "/api/run", {"voice": "multi.onnx", "file": "t.txt", "speaker": 2})[0], 200)
            M.ENGINE_ERR = "x"
            try:
                self.assertEqual(self.call("POST", "/api/run", {"voice": "a.onnx", "file": "t.txt"})[0], 500)
            finally:
                M.ENGINE_ERR = None

        def test_load_failure_is_json_error(self):
            c, j, _ = self.call("POST", "/api/run", {"voice": "broken.onnx", "file": "t.txt"})
            self.assertEqual(c, 500)
            self.assertIn("bad model", j["error"])

        def test_stream_headers_and_length(self):
            c, b, h = self.call("POST", "/api/stream", {"voice": "a.onnx", "file": "t.txt"}, raw=True)
            self.assertEqual((c, len(b)), (200, 8820))
            self.assertEqual((h["X-Audio-Sample-Rate"], h["X-Audio-Format"], h["X-Audio-Channels"]), ("22050", "s16le", "1"))
            self.assertEqual(self.call("POST", "/api/stream", {"voice": "broken.onnx", "file": "t.txt"})[0], 500)

        def test_unload_clears_loaded_voice(self):
            self.run_wav()
            self.assertEqual(self.call("GET", "/api/status")[1]["loaded"], "a.onnx")
            self.assertEqual(self.call("POST", "/api/unload", {})[0], 200)
            self.assertIsNone(self.call("GET", "/api/status")[1]["loaded"])

        def test_upload_rules(self):
            h = {"X-Filename": "n.txt"}
            self.assertEqual(self.call("POST", "/api/upload", b"hi", h)[0], 200)
            self.assertEqual(self.call("POST", "/api/upload", b"hi", {"X-Filename": "evil.exe"})[0], 400)
            self.assertEqual(self.call("POST", "/api/upload", b"\xff\xfe\x00", h)[0], 400)

        def test_output_delete_rules(self):
            name = self.run_wav()
            self.assertEqual(self.call("POST", "/api/output/delete", {"name": name})[0], 200)
            self.assertFalse(os.path.exists(self.tmp + "/o/" + name))
            for bad in (name, "../i/t.txt", "t.txt"):
                self.assertEqual(self.call("POST", "/api/output/delete", {"name": bad})[0], 400, bad)

        @need_np
        def test_export_and_download(self):
            name = self.run_wav()
            c, j, _ = self.call("POST", "/api/export", {"name": name, "format": "ulaw"})
            self.assertEqual((c, j["bytes"]), (200, 1600))
            c, b, h = self.call("GET", "/audio/" + j["name"], raw=True)
            self.assertEqual((c, len(b)), (200, 1600))
            self.assertIn("attachment", h["Content-Disposition"])
            self.assertEqual(self.call("POST", "/api/export", {"name": name, "format": "mp3"})[0], 400)
            c, j2, _ = self.call("POST", "/api/export", {"name": name, "format": "wav8"})
            self.assertEqual(self.call("POST", "/api/export", {"name": j2["name"], "format": "ulaw"})[0], 400)
            self.assertEqual(self.call("POST", "/api/export", {"name": "../x.wav", "format": "ulaw"})[0], 400)

        def test_radio_disabled_by_default(self):
            self.assertEqual(self.call("POST", "/api/radio/play", {"name": "x.ulaw", "node": "1"})[0], 403)

        @need_np
        def test_radio_play_gates_and_command(self):
            snd, log = self.tmp + "/snd", self.tmp + "/ast.log"
            script = self.tmp + "/fakeast.sh"
            open(script, "w").write('#!/bin/bash\necho "$@" >> %s\n' % log)
            os.chmod(script, 0o755)
            name = self.run_wav()
            ulaw = self.call("POST", "/api/export", {"name": name, "format": "ulaw"})[1]["name"]
            M.CFG.update(radio_nodes=["652701"], radio_sounds=snd, asterisk=script, radio_max_seconds=60)
            try:
                open(snd + "/pipertts.sln", "w").write("stale")
                c, j, _ = self.call("POST", "/api/radio/play", {"name": ulaw, "node": "652701"})
                self.assertEqual(c, 200, j)
                self.assertEqual(sorted(os.listdir(snd)), ["pipertts.ulaw"])
                self.assertIn("rpt playback 652701 " + snd + "/pipertts", open(log).read())
                self.assertEqual(self.call("POST", "/api/radio/play", {"name": ulaw, "node": "999"})[0], 400)
                self.assertEqual(self.call("POST", "/api/radio/play", {"name": name, "node": "652701"})[0], 400)
                M.CFG["radio_max_seconds"] = 0
                self.assertEqual(self.call("POST", "/api/radio/play", {"name": ulaw, "node": "652701"})[0], 400)
                M.CFG.update(radio_max_seconds=60, asterisk="false")
                self.assertEqual(self.call("POST", "/api/radio/play", {"name": ulaw, "node": "652701"})[0], 500)
            finally:
                M.CFG.update(radio_nodes=[], radio_sounds="", asterisk="false")


    loader = unittest.TestLoader()
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(PureTests), loader.loadTestsFromTestCase(HttpTests)])
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if res.wasSuccessful() else 1


def preload_voice(name):
    if not SAFE_NAME.match(name) or not (Path(CFG["voices"]) / name).is_file():
        print("warning: --preload voice not found: %s" % name, file=sys.stderr)
        return
    try:
        with ENG.lock:
            ENG.ensure(name)
    except Exception as e:
        print("warning: preload failed: %s: %s" % (type(e).__name__, e), file=sys.stderr)


def build_parser(cp):
    def g(sec, key, default):
        return cp.get(sec, key, fallback=default)

    ap = argparse.ArgumentParser(description="Piper TTS web dashboard")
    ap.add_argument("--config", metavar="INI", help="INI config file (CLI flags override it)")
    ap.add_argument("--host", default=g("server", "host", "0.0.0.0"),
                    help="bind address (0.0.0.0 serves the LAN; every page needs the root password)")
    ap.add_argument("--port", type=int, default=cp.getint("server", "port", fallback=8765))
    ap.add_argument("--voices", default=g("paths", "voices", DATA_ROOT + "/voices"),
                    help="dir with .onnx + .onnx.json")
    ap.add_argument("--workdir", default=g("paths", "workdir", DATA_ROOT + "/input"),
                    help="uploaded text files")
    ap.add_argument("--outdir", default=g("paths", "outdir", DATA_ROOT + "/output"),
                    help="generated WAV files")
    ap.add_argument("--venv", default=g("paths", "venv", DATA_ROOT + "/venv"),
                    help="venv for the installed piper-tts engine")
    ap.add_argument("--voices-base", default=g("catalog", "voices_base", VOICES_BASE),
                    help="voice catalog/download base URL")
    ap.add_argument("--preload", metavar="VOICE", default=g("engine", "preload", "") or None,
                    help="voice .onnx filename to load at startup")
    ap.add_argument("--cuda", action="store_true", default=cp.getboolean("engine", "cuda", fallback=False),
                    help="use GPU (needs onnxruntime-gpu)")
    ap.add_argument("--radio-nodes", default=g("radio", "nodes", ""), metavar="N[,N]",
                    help="node numbers allowed for play-on-node (empty = feature off)")
    ap.add_argument("--radio-sounds", default=g("radio", "sounds_dir", ""), metavar="DIR",
                    help="dedicated Asterisk sounds dir for play-on-node")
    ap.add_argument("--radio-max-seconds", type=int, default=cp.getint("radio", "max_seconds", fallback=60),
                    help="refuse to play longer clips on air")
    ap.add_argument("--asterisk", default=g("radio", "asterisk_cmd", "asterisk"), help="asterisk CLI binary")
    ap.add_argument("--selftest", action="store_true", help="run the embedded unit tests and exit")
    ap.add_argument("--install", action="store_true", help="install as a systemd service (root)")
    ap.add_argument("--uninstall", action="store_true", help="remove the service and program files (root)")
    ap.add_argument("--version", action="version", version=VERSION)
    return ap


def main():
    global ENG
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config")
    known, _rest = pre.parse_known_args()
    cfg_path = known.config or (CONFIG_PATH if os.path.isfile(CONFIG_PATH) else None)
    cp = configparser.ConfigParser(interpolation=None)
    if cfg_path and not cp.read(cfg_path):
        sys.exit("cannot read config file: %s" % cfg_path)
    try:
        ap = build_parser(cp)
    except ValueError as e:
        sys.exit("bad value in %s: %s" % (cfg_path, e))
    a = ap.parse_args()

    if sum(map(bool, (a.install, a.uninstall, a.selftest))) > 1:
        ap.error("--install, --uninstall and --selftest are mutually exclusive")
    if a.selftest:
        sys.exit(run_selftests())
    if a.install:
        sys.exit(install_service(a))
    if a.uninstall:
        sys.exit(uninstall_service(a))

    for d in (a.voices, a.workdir, a.outdir):
        os.makedirs(d, exist_ok=True)

    nodes = [n.strip() for n in a.radio_nodes.split(",") if n.strip()]
    if any(not n.isdigit() for n in nodes):
        sys.exit("radio nodes must be numbers, comma separated: %s" % a.radio_nodes)
    if nodes and not (a.radio_sounds and os.path.isdir(a.radio_sounds)):
        print("warning: play-on-node disabled: sounds dir missing: %r" % a.radio_sounds, file=sys.stderr)
        nodes = []
    CFG.update(voices=a.voices, workdir=a.workdir, outdir=a.outdir,
               venv=a.venv, voices_base=a.voices_base, radio_nodes=nodes,
               radio_sounds=a.radio_sounds, radio_max_seconds=max(1, a.radio_max_seconds),
               asterisk=a.asterisk)
    if not try_import_engine(a.venv):
        for v in find_legacy_venvs():
            if try_import_engine(v):
                CFG["venv"] = v
                print("piper engine found in an existing install: %s" % v, file=sys.stderr)
                break
        else:
            print("warning: piper engine unavailable: %s (install from the UI)" % ENGINE_ERR, file=sys.stderr)
    ENG = Engine(a.voices, a.cuda)

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    signal.signal(signal.SIGTERM,
                  lambda *_: threading.Thread(target=srv.shutdown, daemon=True).start())
    sd_notify("READY=1\nSTATUS=listening on %s:%d" % (a.host, a.port))
    start_watchdog(a.host, a.port)
    if a.preload and ENGINE_ERR is None:
        threading.Thread(target=preload_voice, args=(a.preload,), daemon=True).start()

    print("piper_dashboard %s on http://%s:%d" % (VERSION, a.host, a.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sd_notify("STOPPING=1")
        srv.server_close()


class ConfirmNeeded(ValueError):
    pass


RE_HOST = re.compile(r"^[A-Za-z0-9.\-:]{1,255}$")
RE_PRELOAD = re.compile(r"^([A-Za-z0-9._-]{1,128}\.onnx)?$")
RE_NODES = re.compile(r"^([0-9]{1,8}(\s*,\s*[0-9]{1,8})*)?$")
RE_ASTERISK = re.compile(r"^[A-Za-z0-9_./-]{1,200}$")


def default_values(host, port):
    return {"host": host, "port": port, "cuda": False, "preload": "", "voices_base": VOICES_BASE,
            "nodes": "", "sounds_dir": "", "max_seconds": 60, "asterisk_cmd": "asterisk", "pibrary_root": ""}


def read_config():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(CONFIG_PATH)
    return cp


def config_values(cp):
    d = default_values("0.0.0.0", 8765)
    return {
        "host": cp.get("server", "host", fallback=d["host"]),
        "port": cp.getint("server", "port", fallback=d["port"]),
        "cuda": cp.getboolean("engine", "cuda", fallback=d["cuda"]),
        "preload": cp.get("engine", "preload", fallback=d["preload"]),
        "voices_base": cp.get("catalog", "voices_base", fallback=d["voices_base"]),
        "nodes": cp.get("radio", "nodes", fallback=d["nodes"]),
        "sounds_dir": cp.get("radio", "sounds_dir", fallback=d["sounds_dir"]),
        "max_seconds": cp.getint("radio", "max_seconds", fallback=d["max_seconds"]),
        "asterisk_cmd": cp.get("radio", "asterisk_cmd", fallback=d["asterisk_cmd"]),
        "pibrary_root": cp.get("pibrary", "root", fallback=d["pibrary_root"]),
    }


def config_text(v):
    cp = configparser.ConfigParser(interpolation=None)
    cp["server"] = {"host": v["host"], "port": str(v["port"])}
    cp["paths"] = {"voices": DATA_ROOT + "/voices", "workdir": DATA_ROOT + "/input",
                   "outdir": DATA_ROOT + "/output", "venv": DATA_ROOT + "/venv"}
    cp["engine"] = {"cuda": "true" if v["cuda"] else "false", "preload": v["preload"]}
    cp["catalog"] = {"voices_base": v["voices_base"]}
    cp["radio"] = {"nodes": v["nodes"], "sounds_dir": v["sounds_dir"],
                   "max_seconds": str(v["max_seconds"]), "asterisk_cmd": v["asterisk_cmd"]}
    cp["pibrary"] = {"root": v["pibrary_root"]}
    buf = io.StringIO()
    cp.write(buf)
    return buf.getvalue()


def _clean_path(value, what):
    if value and (not value.startswith("/") or ".." in value.split("/") or len(value) > 300):
        raise ValueError("%s must be an absolute path" % what)
    return value


def validate_config(b, current):
    host = str(b.get("host", "")).strip()
    if not RE_HOST.match(host):
        raise ValueError("bind address must be an IP address or host name")
    try:
        port = int(b.get("port"))
    except (TypeError, ValueError):
        raise ValueError("port must be a number")
    if not 1 <= port <= 65535:
        raise ValueError("port must be 1 to 65535")
    preload = str(b.get("preload", "")).strip()
    if not RE_PRELOAD.match(preload):
        raise ValueError("preload must be a voice .onnx file name, or blank")
    vbase = str(b.get("voices_base", "")).strip().rstrip("/")
    if not re.match(r"^https?://[^\s]{1,300}$", vbase):
        raise ValueError("voice catalog must be an http or https URL")
    nodes = str(b.get("nodes", "")).strip()
    if not RE_NODES.match(nodes):
        raise ValueError("node numbers must be digits, comma separated")
    nodes = ",".join(n.strip() for n in nodes.split(",") if n.strip())
    sounds = _clean_path(str(b.get("sounds_dir", "")).strip(), "sounds directory")
    if nodes and not sounds:
        raise ValueError("play on node needs a sounds directory")
    if nodes and not current.get("nodes") and not b.get("radio_confirm"):
        raise ConfirmNeeded("Play on node transmits on your node. Confirm to turn it on.")
    try:
        maxs = int(b.get("max_seconds", 60))
    except (TypeError, ValueError):
        raise ValueError("longest clip must be a number of seconds")
    if not 1 <= maxs <= 600:
        raise ValueError("longest clip must be 1 to 600 seconds")
    ast_cmd = str(b.get("asterisk_cmd", "asterisk")).strip()
    if not RE_ASTERISK.match(ast_cmd):
        raise ValueError("asterisk command must be a name or a path")
    pib = _clean_path(str(b.get("pibrary_root", "")).strip(), "Pibrary drive")
    return {"host": host, "port": port, "cuda": bool(b.get("cuda")), "preload": preload,
            "voices_base": vbase, "nodes": nodes, "sounds_dir": sounds, "max_seconds": maxs,
            "asterisk_cmd": ast_cmd, "pibrary_root": pib}


def pibrary_roots():
    if not shutil.which("systemctl"):
        return None
    r = subprocess.run(["systemctl", "is-active", PIBRARY_SERVICE], capture_output=True, text=True, timeout=10)
    if r.stdout.strip() != "active":
        return None
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(PIBRARY_CONF)
    if not cp.has_section(PIBRARY_SECTION):
        return []
    items = [cp.get(PIBRARY_SECTION, "library_root", fallback="").strip()]
    items += re.split(r"[,\n]", cp.get(PIBRARY_SECTION, "extra_roots", fallback=""))
    roots = []
    for item in items:
        item = item.strip()
        if item and item not in roots:
            roots.append(item)
    return roots


def pibrary_choices(current):
    roots = pibrary_roots()
    options = [{"root": "", "label": "Local output folder"}]
    if roots:
        options += [{"root": r, "label": r + "/audio/TTS"} for r in roots]
    if current and current not in [o["root"] for o in options]:
        options.append({"root": current, "label": current + " (not available now)"})
    return {"running": roots is not None, "options": options}


def tts_output_dir():
    try:
        root = read_config().get("pibrary", "root", fallback="").strip()
    except configparser.Error:
        root = ""
    if not root:
        return CFG["outdir"], ""
    roots = pibrary_roots()
    if roots is None:
        return CFG["outdir"], "Pibrary is not running: saved to the local output folder"
    if root not in roots or not os.path.isdir(root):
        return CFG["outdir"], "the Pibrary drive %s is missing: saved to the local output folder" % root
    d = os.path.join(root, "audio", "TTS")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as e:
        return CFG["outdir"], "cannot write to %s (%s): saved to the local output folder" % (d, e)
    if not os.access(d, os.W_OK):
        return CFG["outdir"], "%s is not writable: saved to the local output folder" % d
    return d, ""


def _atomic_write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    atomic_write(path, text, mode=mode)


def _systemctl(*args):
    return subprocess.run(["systemctl"] + list(args), capture_output=True, text=True)


def _replace_link(path, target):
    tmp = path + ".tmp"
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, path)


def _write_launcher():
    _atomic_write(_LAUNCHER_PATH, _LAUNCHER_CODE, 0o755)
    print("  [+] Wrote launcher %s" % _LAUNCHER_PATH)


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
        print("  [-] Removed unused launcher %s" % _LAUNCHER_PATH)
    except OSError:
        pass


def service_content():
    return f"""[Unit]
Description=Pi-Piper TTS: Piper text-to-speech dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 {_LAUNCHER_PATH} {INSTALL_BIN_PATH} --config {CONFIG_PATH}
Restart=always
RestartSec=3s
TimeoutStopSec=15s
WatchdogSec=30s
StandardOutput=journal
StandardError=journal
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full

[Install]
WantedBy=multi-user.target
"""


def install_service(a):
    if os.geteuid() != 0:
        print("Error: installing needs root. Run with sudo.")
        return 1
    if not shutil.which("systemctl"):
        print("Error: systemd is required (systemctl not found).")
        return 1
    current = os.path.realpath(__file__)
    print("Installing %s v%s..." % (APP, VERSION))
    os.makedirs(INSTALL_DIR, mode=0o755, exist_ok=True)
    dest = os.path.join(INSTALL_DIR, APP + ".py")
    if current != dest:
        tmp = dest + ".tmp"
        shutil.copy2(current, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        print("  [+] Copied %s -> %s" % (os.path.basename(current), dest))
    os.chmod(dest, 0o755)
    _replace_link(INSTALL_BIN_PATH, dest)
    print("  [+] Symlinked %s -> %s" % (INSTALL_BIN_PATH, dest))
    _write_launcher()
    for sub in ("voices", "input", "output"):
        os.makedirs(os.path.join(DATA_ROOT, sub), exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        _atomic_write(CONFIG_PATH, config_text(default_values(a.host, a.port)), 0o644)
        print("  [+] Wrote %s" % CONFIG_PATH)
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(CONFIG_PATH)
    port = cp.getint("server", "port", fallback=8765)
    _atomic_write(SYSTEMD_SERVICE_PATH, service_content(), 0o644)
    print("  [+] Wrote %s" % SYSTEMD_SERVICE_PATH)
    mark, msg = open_firewall_port(port)
    print("  [%s] %s" % (mark, msg))
    for args in (("daemon-reload",), ("enable", SERVICE_NAME)):
        r = _systemctl(*args)
        if r.returncode != 0:
            print("  [!] systemctl %s failed: %s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    r = _systemctl("restart", SERVICE_NAME)
    if r.returncode != 0:
        print("  [!] systemctl restart failed: %s" % (r.stderr or r.stdout).strip())
        print("      check: journalctl -u %s -n 30 --no-pager" % SERVICE_NAME)
        return 1
    print("  [+] %s enabled and started" % SERVICE_NAME)
    print("Open http://<node-address>:%d and sign in with the root password." % port)
    return 0


def uninstall_service(a):
    if os.geteuid() != 0:
        print("Error: uninstalling needs root. Run with sudo.")
        return 1
    print("Removing %s..." % APP)
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(CONFIG_PATH)
    port = cp.getint("server", "port", fallback=8765)
    _systemctl("disable", "--now", SERVICE_NAME)
    for p in (SYSTEMD_SERVICE_PATH, INSTALL_BIN_PATH):
        if os.path.lexists(p):
            os.remove(p)
            print("  [-] Removed %s" % p)
    _systemctl("daemon-reload")
    if os.path.isdir(INSTALL_DIR):
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        print("  [-] Removed %s" % INSTALL_DIR)
    _remove_launcher_if_unused()
    print("  Settings kept in %s; voices, input and output kept in %s" % (CONFIG_PATH, DATA_ROOT))
    mark, msg = close_firewall_port(port)
    print("  [%s] %s" % (mark, msg))
    return 0


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


if __name__ == "__main__":
    main()
