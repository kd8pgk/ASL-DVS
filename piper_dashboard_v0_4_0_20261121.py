VERSION = "0.4.0"

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
import pwd
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
INSTALL_ROOT = "/opt/piper_dashboard"
UNIT_PATH = "/etc/systemd/system/piper_dashboard.service"
INI_PATH = "/etc/piper_dashboard.ini"
DATA_ROOT = "/srv/piper_dashboard"
DEFAULT_USER = "piperdash"
USER_MARK = "/etc/piper_dashboard.user"
KEEP_VERSIONS = 3
EXPORT_FORMATS = {"ulaw": ".ulaw", "sln": ".sln", "wav8": "-8k.wav"}
MAX_EXPORT_BYTES = 16 * 1024 * 1024
EXPORT_LOCK = threading.Lock()
RADIO_LOCK = threading.Lock()
RADIO_BASE = "pipertts"
OUT_EXTS = {".wav", ".ulaw", ".sln"}
UPDATE_MAX = 2 * 1024 * 1024
STAGED = "piper_dashboard.py"
VER_RE = re.compile(r'^VERSION = "([0-9][0-9A-Za-z.\-]{0,30})"$', re.M)

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
        del JOB["log"][:-60]


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


def install_engine():
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
pre { background: var(--bg); border: 1px solid var(--border); border-radius: 3px; padding: .4rem; font-size: .75rem; color: var(--text-bright); max-height: 140px; overflow: auto; white-space: pre-wrap; }
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
</style></head><body>
<header>
  <div class="hdr-left">
    <div class="logo">Pi-Piper TTS</div>
    <div class="logo-sub">Text to speech</div>
  </div>
  <div class="hdr-right"><div class="hdr-ver">v__VERSION__</div></div>
</header>
<div class="wrap">
<div id="eng"></div>

<details id="inst"><summary>Install engine / voices</summary>
<fieldset><legend>Engine</legend>
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
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
async function loadEngine() {
  try {
    const s = await getJSON('/api/status');
    const parts = [s.engine_ok ? 'engine ok' : 'engine MISSING: ' + s.engine_error];
    parts.push(s.loaded ? 'loaded: ' + s.loaded : 'no voice loaded');
    parts.push(s.busy ? 'busy' : 'idle');
    if (s.rss_mb !== null) parts.push('RSS ' + s.rss_mb + ' MB');
    $('eng').textContent = parts.join(' | ');
    $('eng').className = s.engine_ok ? '' : 'err';
    $('unload').disabled = !s.loaded;
    $('ieng').disabled = s.engine_ok;
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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
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
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
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
    const r = await fetch('/api/unload', { method: 'POST' });
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
      headers: { 'X-Filename': encodeURIComponent(f.name) },
      body: f
    });
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
  const t0 = performance.now();
  try {
    const r = await fetch('/api/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody()),
      signal: ctrl.signal
    });
    if (!r.ok) {
      const j = await r.json();
      throw new Error(j.error || r.statusText);
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
  try {
    const r = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody())
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    setStatus('Done: ' + j.audio + ' (' + j.seconds + ' s)');
    play(j.audio);
    loadOutputs();
  } catch (e) {
    setStatus('Failed: ' + e.message, true);
  }
  setBusy(false);
  loadEngine();
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


class Handler(BaseHTTPRequestHandler):
    server_version = "PiperDash/" + VERSION

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, HTML.replace("__VERSION__", VERSION), "text/html; charset=utf-8")
        elif path == "/api/voices":
            self._json(200, list_voices(CFG["voices"]))
        elif path == "/api/files":
            self._json(200, list_files(CFG["workdir"], TEXT_EXTS))
        elif path == "/api/outputs":
            self._json(200, list_files(CFG["outdir"], OUT_EXTS))
        elif path == "/api/status":
            kb = rss_kb()
            self._json(200, {
                "version": VERSION,
                "engine_ok": ENGINE_ERR is None,
                "engine_error": ENGINE_ERR,
                "loaded": ENG.name,
                "busy": ENG.lock.locked(),
                "rss_mb": None if kb is None else round(kb / 1024),
                "platform": sysconfig.get_platform(),
                "venv": CFG["venv"],
                "radio": {"enabled": radio_enabled(), "nodes": CFG.get("radio_nodes", [])},
                "update": {"enabled": bool(CFG.get("update_token"))},
            })
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
        limit = {"/api/upload": MAX_UPLOAD, "/api/update": UPDATE_MAX}.get(path, MAX_JSON)
        if length > limit:
            self.close_connection = True
            return self._json(413, {"error": "request too large"})
        raw = self.rfile.read(length)
        if path == "/api/upload":
            return self.handle_upload(raw)
        if path == "/api/run":
            return self.handle_run(raw)
        if path == "/api/unload":
            return self.handle_unload()
        if path == "/api/stream":
            return self.handle_stream(raw)
        if path == "/api/update":
            return self.handle_update(raw)
        if path == "/api/export":
            return self.handle_export(raw)
        if path == "/api/output/delete":
            return self.handle_output_delete(raw)
        if path == "/api/radio/play":
            return self.handle_radio_play(raw)
        if path == "/api/install/engine":
            return self.handle_install_engine()
        if path == "/api/install/voice":
            return self.handle_install_voice(raw)
        self._json(404, {"error": "not found"})

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

    def handle_update(self, raw):
        tok = CFG.get("update_token", "")
        if not tok:
            return self._json(403, {"error": "self-update is not enabled ([update] enabled + token)"})
        if not hmac.compare_digest(self.headers.get("X-Update-Token", "").encode("utf-8"), tok.encode("utf-8")):
            time.sleep(1)
            return self._json(403, {"error": "bad token"})
        try:
            ver = stage_update(CFG["update_dir"], raw)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except OSError as e:
            return self._json(500, {"error": "stage failed: %s" % e})
        restart = self.headers.get("X-Restart", "") == "1" and under_systemd()
        self._json(200, {"staged": ver, "restarting": restart})
        if restart:
            threading.Timer(1.0, _self_terminate).start()

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
        out = Path(CFG["outdir"]) / out_name
        t0 = time.time()
        with ENG.lock:
            try:
                v = ENG.ensure(voice)
                with wave.open(str(out), "wb") as wf:
                    v.synthesize_wav(text, wf, syn_config=cfg)
            except Exception as e:
                try:
                    out.unlink()
                except OSError:
                    pass
                return self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})
        self._json(200, {"audio": out_name, "seconds": round(time.time() - t0, 1)})

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
            self.send_header("Connection", "close")
            self.send_header("X-Audio-Format", "s16le")
            self.send_header("X-Audio-Sample-Rate", str(v.config.sample_rate))
            self.send_header("X-Audio-Sample-Width", "2")
            self.send_header("X-Audio-Channels", "1")
            self.end_headers()
            gen = v.synthesize(text, syn_config=cfg)
            try:
                for chunk in gen:
                    data = chunk.audio_int16_bytes
                    if data:
                        self.wfile.write(data)
            except OSError:
                pass
            except Exception as e:
                print("stream failed: %s: %s" % (type(e).__name__, e), file=sys.stderr)
            finally:
                close = getattr(gen, "close", None)
                if close:
                    close()
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


def under_systemd():
    return bool(os.environ.get("INVOCATION_ID"))


def _self_terminate():
    os.kill(os.getpid(), signal.SIGTERM)


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


def _p(destdir, path):
    return os.path.join(destdir, path.lstrip("/")) if destdir else path


def user_home(user, pw=None):
    if pw:
        return pw.pw_dir
    return "/root" if user == "root" else "/home/" + user


def unit_text(user, home):
    lines = [
        "[Unit]",
        "Description=Piper TTS web dashboard",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=notify",
        "NotifyAccess=main",
    ]
    if user != "root":
        lines.append("User=" + user)
    py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
    lines += [
        "Environment=HOME=" + home,
        "Environment=PYTHONUNBUFFERED=1",
        "ExecStartPre=-+%s %s/root/%s.py --config %s --apply-staged" % (py, INSTALL_ROOT, APP, INI_PATH),
        "ExecStart=%s %s/current/%s.py --config %s" % (py, INSTALL_ROOT, APP, INI_PATH),
        "WatchdogSec=30",
        "Restart=always",
        "RestartSec=3",
        "TimeoutStopSec=15",
        "NoNewPrivileges=yes",
        "PrivateTmp=yes",
        "ProtectSystem=full",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ]
    return "\n".join(lines)


def ini_text(host, port, venv):
    return """[server]
host = %s
port = %d

[paths]
voices = %s/voices
workdir = %s/input
outdir = %s/output
venv = %s

[engine]
cuda = false
preload =

[catalog]
voices_base = %s

[radio]
# Play-on-node is OFF until both nodes and sounds_dir are set. It TRANSMITS; you are the control operator.
# sounds_dir must be a dedicated directory this service user can write and Asterisk can read.
# The service user also needs permission to run `asterisk -rx` (e.g. group asterisk). Both are manual steps.
nodes =
sounds_dir =
max_seconds = 60
asterisk_cmd = asterisk

[update]
# Self-update card is OFF until enabled = true AND a token is set. Anyone holding the token can replace the
# program code the service runs (as the service user; root only copies the staged file), so use a long random token.
enabled = false
token =
dir = %s/update
""" % (host, port, DATA_ROOT, DATA_ROOT, DATA_ROOT, venv, VOICES_BASE, DATA_ROOT)


def _atomic_write(path, text, mode):
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _systemctl(*args, check=True):
    return subprocess.run(["systemctl"] + list(args), check=check)


def _place_version(root, src_file, version):
    lib = os.path.join(root, "lib")
    name = "%s-%s" % (APP, version)
    vdir = os.path.join(lib, name)
    os.makedirs(vdir, exist_ok=True)
    dst = os.path.join(vdir, APP + ".py")
    tmp = dst + ".new"
    shutil.copyfile(src_file, tmp)
    os.chmod(tmp, 0o755)
    os.replace(tmp, dst)
    cur = os.path.join(root, "current")
    cur_new = cur + ".new"
    if os.path.lexists(cur_new):
        os.unlink(cur_new)
    os.symlink(os.path.join("lib", name), cur_new)
    os.replace(cur_new, cur)
    keep = sorted((n for n in os.listdir(lib) if os.path.isdir(os.path.join(lib, n))),
                  key=lambda n: os.stat(os.path.join(lib, n)).st_mtime_ns, reverse=True)
    for n in keep[KEEP_VERSIONS:]:
        if n != name:
            shutil.rmtree(os.path.join(lib, n), ignore_errors=True)
    return name


def validate_update(data):
    if len(data) > UPDATE_MAX:
        raise ValueError("file too large")
    try:
        src = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("not UTF-8 text")
    try:
        compile(src, STAGED, "exec")
    except (SyntaxError, ValueError) as e:
        raise ValueError("syntax error: %s" % e)
    m = VER_RE.search(src)
    if not m:
        raise ValueError("no VERSION found")
    if 'APP = "piper_dashboard"' not in src or "def main():" not in src:
        raise ValueError("not a Pi-Piper TTS dashboard file")
    return m.group(1)


def stage_update(update_dir, data):
    ver = validate_update(data)
    if ver == VERSION:
        raise ValueError("same version as the running program (%s)" % ver)
    os.makedirs(update_dir, exist_ok=True)
    tmp = os.path.join(update_dir, STAGED + ".new")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(update_dir, STAGED))
    return ver


def apply_staged(destdir, update_dir):
    f = os.path.join(update_dir, STAGED)
    if not os.path.isfile(f):
        return None
    try:
        with open(f, "rb") as fh:
            ver = validate_update(fh.read(UPDATE_MAX + 1))
    except (ValueError, OSError) as e:
        try:
            os.replace(f, f + ".rejected")
        except OSError:
            pass
        return "rejected staged update: %s" % e
    name = _place_version(_p(destdir, INSTALL_ROOT), f, ver)
    os.unlink(f)
    return "applied staged update %s" % name


def do_apply_staged(a):
    if not a.destdir and os.geteuid() != 0:
        sys.exit("--apply-staged must run as root")
    print(apply_staged(a.destdir, a.update_dir) or "no staged update")
    return 0


def do_rollback(a):
    stage = a.destdir
    if not stage and os.geteuid() != 0:
        sys.exit("--rollback must run as root (try sudo)")
    root = _p(stage, INSTALL_ROOT)
    lib = os.path.join(root, "lib")
    cur = os.path.join(root, "current")
    if not os.path.islink(cur):
        sys.exit("not installed: no current symlink")
    now = os.path.basename(os.readlink(cur))
    vers = sorted((n for n in os.listdir(lib) if os.path.isdir(os.path.join(lib, n))),
                  key=lambda n: os.stat(os.path.join(lib, n)).st_mtime_ns, reverse=True)
    if now not in vers or vers.index(now) + 1 >= len(vers):
        sys.exit("no older version to roll back to")
    prev = vers[vers.index(now) + 1]
    cur_new = cur + ".new"
    if os.path.lexists(cur_new):
        os.unlink(cur_new)
    os.symlink(os.path.join("lib", prev), cur_new)
    os.replace(cur_new, cur)
    print("rolled back %s -> %s" % (now, prev))
    if not stage:
        _systemctl("restart", APP + ".service", check=False)
    return 0


def do_install(a):
    stage = a.destdir
    if not stage:
        if os.geteuid() != 0:
            sys.exit("--install must run as root (try sudo)")
        if not shutil.which("systemctl"):
            sys.exit("systemctl not found: systemd is required")
    user = a.run_as
    pw = None
    created_user = False
    if not stage and user != "root":
        try:
            pw = pwd.getpwnam(user)
        except KeyError:
            subprocess.run(["useradd", "--system", "--create-home", "--home-dir", "/home/" + user,
                            "--shell", "/usr/sbin/nologin", user], check=True)
            pw = pwd.getpwnam(user)
            created_user = True
            print("created system user", user)

    home = user_home(user, pw)
    if stage:
        os.makedirs(_p(stage, home), exist_ok=True)
    venv = home + "/venv"
    for sub in ("", "voices", "input", "output", "update"):
        d = _p(stage, DATA_ROOT + ("/" + sub if sub else ""))
        os.makedirs(d, exist_ok=True)
        if pw:
            os.chown(d, pw.pw_uid, pw.pw_gid)

    root = _p(stage, INSTALL_ROOT)
    name = _place_version(root, os.path.abspath(__file__), VERSION)
    rdir = os.path.join(root, "root")
    os.makedirs(rdir, exist_ok=True)
    rtmp = os.path.join(rdir, APP + ".py.new")
    shutil.copyfile(os.path.abspath(__file__), rtmp)
    os.chmod(rtmp, 0o755)
    os.replace(rtmp, os.path.join(rdir, APP + ".py"))

    ini = _p(stage, INI_PATH)
    if os.path.exists(ini):
        print("kept existing config", INI_PATH)
    else:
        os.makedirs(os.path.dirname(ini), exist_ok=True)
        _atomic_write(ini, ini_text(a.host, a.port, venv), 0o640)
        if pw:
            os.chown(ini, 0, pw.pw_gid)
        print("wrote config", INI_PATH)

    unit = _p(stage, UNIT_PATH)
    os.makedirs(os.path.dirname(unit), exist_ok=True)
    _atomic_write(unit, unit_text(user, home), 0o644)
    os.makedirs(os.path.dirname(_p(stage, USER_MARK)), exist_ok=True)
    _atomic_write(_p(stage, USER_MARK), "%s %d\n" % (user, 1 if created_user else 0), 0o644)
    print("installed %s -> %s/current (service user %s, venv %s)" % (name, INSTALL_ROOT, user, venv))

    if stage:
        print("staged install under %s (no systemctl/useradd/chown run)" % stage)
        return 0
    _systemctl("daemon-reload")
    _systemctl("enable", APP + ".service")
    _systemctl("restart", APP + ".service", check=False)
    time.sleep(2)
    r = subprocess.run(["systemctl", "is-active", APP + ".service"], capture_output=True, text=True)
    state = r.stdout.strip()
    print("service:", state)
    if state != "active":
        print("check: journalctl -u %s -n 30 --no-pager" % APP)
        return 1
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(INI_PATH)
    print("listening on %s:%s (edit %s to change, then: systemctl restart %s)" % (
        cp.get("server", "host", fallback="?"), cp.get("server", "port", fallback="?"), INI_PATH, APP))
    return 0


def do_uninstall(a):
    stage = a.destdir
    if not stage:
        if os.geteuid() != 0:
            sys.exit("--uninstall must run as root (try sudo)")
        if shutil.which("systemctl"):
            _systemctl("disable", "--now", APP + ".service", check=False)
    unit = _p(stage, UNIT_PATH)
    if os.path.exists(unit):
        os.unlink(unit)
        print("removed", UNIT_PATH)
    if not stage and shutil.which("systemctl"):
        _systemctl("daemon-reload", check=False)
    root = _p(stage, INSTALL_ROOT)
    if os.path.isdir(root):
        shutil.rmtree(root)
        print("removed", INSTALL_ROOT)
    ini = _p(stage, INI_PATH)
    data = _p(stage, DATA_ROOT)
    if a.purge:
        if os.path.exists(ini):
            os.unlink(ini)
            print("removed", INI_PATH)
        if os.path.isdir(data):
            shutil.rmtree(data)
            print("removed", DATA_ROOT)
        mark = _p(stage, USER_MARK)
        owner, created = "", 0
        if os.path.exists(mark):
            with open(mark, encoding="utf-8") as f:
                parts = f.read().split()
            if len(parts) == 2:
                owner, created = parts[0], int(parts[1] == "1")
        if owner:
            if stage:
                home = user_home(owner)
            else:
                try:
                    home = pwd.getpwnam(owner).pw_dir
                except KeyError:
                    home = None
            if home:
                shutil.rmtree(_p(stage, home + "/venv"), ignore_errors=True)
            if created and not stage:
                subprocess.run(["userdel", "--remove", owner], check=False)
                print("removed user %s and its home" % owner)
            elif created and stage:
                shutil.rmtree(_p(stage, user_home(owner)), ignore_errors=True)
            print("removed venv of service user %s" % owner)
        if os.path.exists(mark):
            os.unlink(mark)
    else:
        print("kept %s, %s and the service user's home (venv); use --uninstall --purge to remove"
              % (INI_PATH, DATA_ROOT))
    return 0


def run_selftests():
    import argparse as _ap
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

        def test_venv_site_and_user_home(self):
            self.assertTrue(str(M.venv_site("/v")).startswith("/v/lib/python3."))
            self.assertEqual(M.user_home("root"), "/root")
            self.assertEqual(M.user_home("piperdash"), "/home/piperdash")
            self.assertEqual(M.user_home("x", types.SimpleNamespace(pw_dir="/srv/x")), "/srv/x")

        def test_unit_text_contents(self):
            u = M.unit_text("piperdash", "/home/piperdash")
            for want in ("Type=notify", "WatchdogSec=30", "User=piperdash", "ExecStartPre=-+", "--apply-staged",
                         "Restart=always", "HOME=/home/piperdash"):
                self.assertIn(want, u)
            self.assertNotIn("User=", M.unit_text("root", "/root"))

        def test_ini_defaults_flow_into_parser(self):
            cp = configparser.ConfigParser(interpolation=None)
            cp.read_string(M.ini_text("0.0.0.0", 9999, "/h/venv"))
            a = M.build_parser(cp).parse_args([])
            self.assertEqual((a.host, a.port, a.venv, a.radio_nodes), ("0.0.0.0", 9999, "/h/venv", ""))
            self.assertEqual(M.build_parser(cp).parse_args(["--port", "1"]).port, 1)
            self.assertFalse(cp.getboolean("update", "enabled"))
            self.assertEqual(cp.get("update", "token"), "")

        def test_validate_update_accepts_and_rejects(self):
            self.assertEqual(M.validate_update(variant("3.2.1")), "3.2.1")
            for bad in (b"def (", b"x = 1\n", b'VERSION = "1.0"\n', b"\xff\xfe", b"#" * (M.UPDATE_MAX + 1)):
                with self.assertRaises(ValueError):
                    M.validate_update(bad)

        def test_stage_update_rejects_same_version(self):
            d = tempfile.mkdtemp()
            with self.assertRaises(ValueError):
                M.stage_update(d, variant(M.VERSION))
            self.assertEqual(M.stage_update(d, variant("8.8.8")), "8.8.8")
            self.assertTrue(os.path.isfile(os.path.join(d, M.STAGED)))

        def test_apply_staged_copies_and_rejects(self):
            d, up = tempfile.mkdtemp(), tempfile.mkdtemp()
            self.assertIsNone(M.apply_staged(d, up))
            open(os.path.join(up, M.STAGED), "wb").write(variant("7.7.7"))
            self.assertIn("7.7.7", M.apply_staged(d, up))
            root = M._p(d, M.INSTALL_ROOT)
            self.assertEqual(os.readlink(os.path.join(root, "current")), "lib/piper_dashboard-7.7.7")
            self.assertFalse(os.path.exists(os.path.join(up, M.STAGED)))
            open(os.path.join(up, M.STAGED), "wb").write(b"not python (")
            self.assertIn("rejected", M.apply_staged(d, up))
            self.assertTrue(os.path.exists(os.path.join(up, M.STAGED + ".rejected")))
            self.assertEqual(os.readlink(os.path.join(root, "current")), "lib/piper_dashboard-7.7.7")

        def test_rollback_steps_back_once_per_version(self):
            d = tempfile.mkdtemp()
            root = M._p(d, M.INSTALL_ROOT)
            src = os.path.join(d, "src.py")
            open(src, "w").write("x")
            for v in ("0.0.1", "0.0.2"):
                M._place_version(root, src, v)
                time.sleep(0.01)
            ns = _ap.Namespace(destdir=d)
            self.assertEqual(quiet(M.do_rollback, ns), 0)
            self.assertEqual(os.readlink(os.path.join(root, "current")), "lib/piper_dashboard-0.0.1")
            with self.assertRaises(SystemExit):
                quiet(M.do_rollback, ns)

        def test_install_uninstall_staged(self):
            d = tempfile.mkdtemp()
            ns = _ap.Namespace(destdir=d, run_as="piperdash", host="127.0.0.1", port=8765, purge=False)
            quiet(M.do_install, ns)
            ini = M._p(d, M.INI_PATH)
            self.assertEqual(oct(os.stat(ini).st_mode & 0o777), "0o640")
            self.assertTrue(os.access(os.path.join(M._p(d, M.INSTALL_ROOT), "current", "piper_dashboard.py"), os.X_OK))
            self.assertIn("Type=notify", open(M._p(d, M.UNIT_PATH)).read())
            ns.port = 1111
            quiet(M.do_install, ns)
            self.assertIn("port = 8765", open(ini).read())
            quiet(M.do_uninstall, ns)
            self.assertFalse(os.path.exists(M._p(d, M.UNIT_PATH)))
            self.assertFalse(os.path.exists(M._p(d, M.INSTALL_ROOT)))
            self.assertTrue(os.path.exists(ini))
            ns.purge = True
            quiet(M.do_uninstall, ns)
            self.assertFalse(os.path.exists(ini))
            self.assertFalse(os.path.exists(M._p(d, M.DATA_ROOT)))

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

        @classmethod
        def tearDownClass(cls):
            cls.srv.shutdown()
            cls.srv.server_close()
            for k, v in cls.saved.items():
                setattr(M, k, v)
            M.CFG.clear()
            M.CFG.update(cls.saved_cfg)
            shutil.rmtree(cls.tmp, ignore_errors=True)

        def call(self, method, path, body=None, headers=None, raw=False):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
            data = body if isinstance(body, (bytes, bytearray)) else (None if body is None else json.dumps(body).encode())
            c.request(method, path, body=data, headers=headers or {})
            r = c.getresponse()
            b = r.read()
            c.close()
            return r.status, (b if raw else json.loads(b)), dict(r.getheaders())

        def run_wav(self):
            c, j, _ = self.call("POST", "/api/run", {"voice": "a.onnx", "file": "t.txt"})
            self.assertEqual(c, 200, j)
            return j["audio"]

        def test_status_fields(self):
            c, j, _ = self.call("GET", "/api/status")
            self.assertEqual((c, j["version"], j["engine_ok"]), (200, M.VERSION, True))
            self.assertFalse(j["radio"]["enabled"])
            self.assertFalse(j["update"]["enabled"])
            self.assertTrue(M.healthy("127.0.0.1", self.port))

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
            self.assertEqual((c, j["bytes"]), (200, 8000))
            c, b, h = self.call("GET", "/audio/" + j["name"], raw=True)
            self.assertEqual((c, len(b)), (200, 8000))
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

        def test_update_endpoint_gating_and_staging(self):
            upd = self.tmp + "/upd"
            good = variant("9.9.9")
            self.assertEqual(self.call("POST", "/api/update", good)[0], 403)
            M.CFG["update_token"] = "s3cret-token"
            try:
                self.assertEqual(self.call("POST", "/api/update", good, {"X-Update-Token": "wrong"})[0], 403)
                self.assertFalse(os.listdir(upd))
                h = {"X-Update-Token": "s3cret-token", "X-Restart": "1"}
                with mock.patch.object(M, "under_systemd", lambda: False):
                    c, j, _ = self.call("POST", "/api/update", good, h)
                self.assertEqual((c, j["staged"], j["restarting"]), (200, "9.9.9", False))
                self.assertTrue(os.path.isfile(upd + "/" + M.STAGED))
                self.assertEqual(self.call("POST", "/api/update", variant(M.VERSION), h)[0], 400)
                self.assertEqual(self.call("POST", "/api/update", b"def (", h)[0], 400)
                hits = []
                with mock.patch.object(M, "under_systemd", lambda: True), \
                        mock.patch.object(M, "_self_terminate", lambda: hits.append(1)):
                    c, j, _ = self.call("POST", "/api/update", variant("9.9.8"), h)
                    self.assertEqual((c, j["restarting"]), (200, True))
                    time.sleep(1.4)
                self.assertEqual(hits, [1])
            finally:
                M.CFG["update_token"] = ""

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
    ap.add_argument("--host", default=g("server", "host", "127.0.0.1"),
                    help="bind address (0.0.0.0 exposes it on the LAN, no auth)")
    ap.add_argument("--port", type=int, default=cp.getint("server", "port", fallback=8765))
    ap.add_argument("--voices", default=g("paths", "voices", os.path.expanduser("~/piper/voices")),
                    help="dir with .onnx + .onnx.json")
    ap.add_argument("--workdir", default=g("paths", "workdir", os.path.expanduser("~/piper/input")),
                    help="uploaded text files")
    ap.add_argument("--outdir", default=g("paths", "outdir", os.path.expanduser("~/piper/output")),
                    help="generated WAV files")
    ap.add_argument("--venv", default=g("paths", "venv", os.path.expanduser("~/piper/venv")),
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
    ap.add_argument("--update-dir", default=g("update", "dir", os.path.expanduser("~/piper/update")),
                    help="where self-update stages the uploaded file")
    ap.add_argument("--apply-staged", action="store_true", help="install a staged update (root; run by the unit's ExecStartPre)")
    ap.add_argument("--rollback", action="store_true", help="point `current` at the previous installed version (root)")
    ap.add_argument("--selftest", action="store_true", help="run the embedded unit tests and exit")
    ap.add_argument("--install", action="store_true", help="install as a systemd service (root)")
    ap.add_argument("--uninstall", action="store_true", help="remove the service and program files (root)")
    ap.add_argument("--purge", action="store_true", help="with --uninstall: also remove config, data and service user")
    ap.add_argument("--run-as", default=DEFAULT_USER, metavar="USER",
                    help="service user for --install (default %s; 'root' allowed)" % DEFAULT_USER)
    ap.add_argument("--destdir", metavar="DIR", help="stage --install/--uninstall under DIR, no systemctl/useradd")
    ap.add_argument("--version", action="version", version=VERSION)
    return ap


def main():
    global ENG
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config")
    known, _rest = pre.parse_known_args()
    cp = configparser.ConfigParser(interpolation=None)
    if known.config and not cp.read(known.config):
        sys.exit("cannot read config file: %s" % known.config)
    try:
        ap = build_parser(cp)
    except ValueError as e:
        sys.exit("bad value in %s: %s" % (known.config, e))
    a = ap.parse_args()

    if sum(map(bool, (a.install, a.uninstall, a.apply_staged, a.rollback, a.selftest))) > 1:
        ap.error("--install, --uninstall, --apply-staged, --rollback and --selftest are mutually exclusive")
    if a.purge and not a.uninstall:
        ap.error("--purge only applies to --uninstall")
    if a.selftest:
        sys.exit(run_selftests())
    if a.apply_staged:
        sys.exit(do_apply_staged(a))
    if a.rollback:
        sys.exit(do_rollback(a))
    if a.install:
        sys.exit(do_install(a))
    if a.uninstall:
        sys.exit(do_uninstall(a))

    for d in (a.voices, a.workdir, a.outdir):
        os.makedirs(d, exist_ok=True)

    nodes = [n.strip() for n in a.radio_nodes.split(",") if n.strip()]
    if any(not n.isdigit() for n in nodes):
        sys.exit("radio nodes must be numbers, comma separated: %s" % a.radio_nodes)
    if nodes and not (a.radio_sounds and os.path.isdir(a.radio_sounds)):
        print("warning: play-on-node disabled: sounds dir missing: %r" % a.radio_sounds, file=sys.stderr)
        nodes = []
    try:
        upd_on = cp.getboolean("update", "enabled", fallback=False)
    except ValueError as e:
        sys.exit("bad [update] enabled in %s: %s" % (known.config, e))
    upd_tok = cp.get("update", "token", fallback="").strip()
    if upd_on and not upd_tok:
        print("warning: self-update disabled: [update] token is empty", file=sys.stderr)
    CFG.update(update_token=upd_tok if upd_on else "", update_dir=a.update_dir)
    CFG.update(voices=a.voices, workdir=a.workdir, outdir=a.outdir,
               venv=a.venv, voices_base=a.voices_base, radio_nodes=nodes,
               radio_sounds=a.radio_sounds, radio_max_seconds=max(1, a.radio_max_seconds),
               asterisk=a.asterisk)
    if not try_import_engine(a.venv):
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


if __name__ == "__main__":
    main()
